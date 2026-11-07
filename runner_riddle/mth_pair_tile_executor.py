"""Parallel, page-backed execution of the native 16x16 K16 pair driver.

This is an adapter boundary, not a matrix store or a host-side math kernel.
Page providers pin an immutable operator snapshot; native guest callbacks do
all pair arithmetic; an independent full-U guest callback supplies the dense
reference tile; candidate stores own page persistence and atomic generation
switching.
"""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import hashlib
from typing import Any, Mapping, Protocol

from .wave_tile_orchestrator import (
    AtomicTilePublication,
    DEFAULT_KERNEL_ID,
    FULL_U_TILE_KERNEL,
    K16_TILE_KERNEL,
    TileDescriptor,
    TileEvidence,
    TileGrid,
    TileManifest,
    sha256_canonical_json,
)

NAN16_WORD_BYTES = 8
STRIP_WORDS = 16 * 256
STRIP_BYTES = STRIP_WORDS * NAN16_WORD_BYTES
OUTPUT_TILE_BYTES = 16 * 16 * NAN16_WORD_BYTES
K16_DRIVER_WORKSPACE_WORDS = 17_170
DENSE_REFERENCE_WORKSPACE_WORDS = FULL_U_TILE_KERNEL.guest_workspace_words
DEFAULT_GUEST_BUDGET_WORDS = 131_072

STRIP_LAYOUT = {
    "L_IK": ("L", "row"),
    "U_KJ": ("U", "col"),
    "U_IK": ("U", "row"),
    "L_JK": ("L", "row"),
}


class PairTileExecutionError(RuntimeError):
    """A page, native result, reference result, or publication contract failed."""


class SnapshotMismatchError(PairTileExecutionError):
    """A page window did not belong to the pinned immutable operator snapshot."""


class DenseReferenceMismatchError(PairTileExecutionError):
    """The bounded K16 result differs byte-for-byte from the dense guest reference."""


@dataclass(frozen=True)
class OperatorSnapshot:
    """Immutable input generation and content digests pinned for one execution."""

    generation: int
    operator_digest: str
    l_digest: str
    u_digest: str
    page_set_digest: str
    snapshot_id: str

    def validate(self) -> None:
        if isinstance(self.generation, bool) or not isinstance(self.generation, int) or self.generation < 0:
            raise PairTileExecutionError("snapshot generation must be a non-negative integer")
        for name in ("operator_digest", "l_digest", "u_digest", "page_set_digest"):
            value = getattr(self, name)
            if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise PairTileExecutionError(f"{name} must be lowercase SHA-256 hex")
        if not isinstance(self.snapshot_id, str) or not self.snapshot_id:
            raise PairTileExecutionError("snapshot_id is required")


@dataclass(frozen=True)
class PageStrip:
    """One row/column strip containing all sixteen K16 blocks for a tile."""

    matrix: str
    row_base: int
    col_base: int
    rows: int
    cols: int
    data: bytes
    generation: int
    operator_digest: str
    matrix_digest: str
    page_set_digest: str

    def validate_for(self, snapshot: OperatorSnapshot, *, matrix: str,
                     row_base: int, col_base: int, rows: int, cols: int) -> None:
        if (self.matrix, self.row_base, self.col_base, self.rows, self.cols) != (
            matrix, row_base, col_base, rows, cols
        ):
            raise SnapshotMismatchError("page provider returned a strip for the wrong matrix window")
        if self.generation != snapshot.generation:
            raise SnapshotMismatchError("page strip belongs to a different generation")
        if self.operator_digest != snapshot.operator_digest:
            raise SnapshotMismatchError("page strip operator digest changed during execution")
        expected_matrix_digest = snapshot.l_digest if matrix == "L" else snapshot.u_digest
        if self.matrix_digest != expected_matrix_digest:
            raise SnapshotMismatchError(f"{matrix} matrix digest does not match the pinned snapshot")
        if self.page_set_digest != snapshot.page_set_digest:
            raise SnapshotMismatchError("page strip belongs to a different immutable page set")
        if not isinstance(self.data, bytes) or len(self.data) != rows * cols * NAN16_WORD_BYTES:
            raise SnapshotMismatchError("page strip byte length does not match its declared shape")


class PairTilePageSource(Protocol):
    def pin_snapshot(self, *, expected_operator_digest: str | None = None) -> OperatorSnapshot:
        """Pin one immutable L/U page set for the full candidate generation."""

    def read_strip(self, snapshot: OperatorSnapshot, *, matrix: str,
                   row_base: int, col_base: int, rows: int, cols: int) -> PageStrip:
        """Read one bounded strip from exactly the pinned snapshot."""


class NativePairTileGuest(Protocol):
    def run_k16_driver(self, descriptor: TileDescriptor,
                       strips: Mapping[str, bytes],
                       snapshot: OperatorSnapshot) -> bytes:
        """Run the native 16-slice driver and its finalizer; return 256 NaN16 words."""

    def run_full_u_reference(self, descriptor: TileDescriptor,
                             snapshot: OperatorSnapshot) -> bytes:
        """Run the independent full-U native reference tile for the same snapshot."""


class CandidatePageStore(Protocol):
    def begin_candidate(self, *, expected_current_generation: int,
                        target_generation: int, plan_digest: str,
                        snapshot: OperatorSnapshot) -> Any:
        """Create an unpublished candidate page set without changing the canonical head."""

    def write_tile(self, candidate: Any, descriptor: TileDescriptor,
                   output: bytes, tile_digest: str) -> None:
        """Write one output tile into candidate pages; duplicate writes must fail."""

    def candidate_page_set_digest(self, candidate: Any) -> str:
        """Return the digest of the complete staged output page set."""

    def publish_candidate(self, candidate: Any, *, expected_current_generation: int,
                          expected_page_set_digest: str, manifest: TileManifest) -> Any:
        """Atomically compare-and-swap the canonical generation pointer."""

    def discard_candidate(self, candidate: Any) -> None:
        """Discard an unpublished candidate; must never touch the canonical generation."""


def _tile_strips(source: PairTilePageSource, snapshot: OperatorSnapshot,
                 descriptor: TileDescriptor) -> dict[str, bytes]:
    i, j = descriptor.i_base, descriptor.j_base
    windows = {
        "L_IK": ("L", i, 0, 16, 256),
        "U_KJ": ("U", 0, j, 256, 16),
        "U_IK": ("U", i, 0, 16, 256),
        "L_JK": ("L", j, 0, 16, 256),
    }
    staged: dict[str, bytes] = {}
    for name, (matrix, row_base, col_base, rows, cols) in windows.items():
        page = source.read_strip(
            snapshot, matrix=matrix, row_base=row_base, col_base=col_base,
            rows=rows, cols=cols,
        )
        page.validate_for(
            snapshot, matrix=matrix, row_base=row_base, col_base=col_base,
            rows=rows, cols=cols,
        )
        staged[name] = page.data
    return staged


def build_pair_plan_digest(snapshot: OperatorSnapshot, grid: TileGrid,
                           *, target_generation: int) -> str:
    snapshot.validate()
    return sha256_canonical_json({
        "schema": "nanrouter.mth-pair-tile16-plan.v1",
        "base_generation": snapshot.generation,
        "target_generation": target_generation,
        "operator_digest": snapshot.operator_digest,
        "l_digest": snapshot.l_digest,
        "u_digest": snapshot.u_digest,
        "input_page_set_digest": snapshot.page_set_digest,
        "grid_digest": grid.digest,
        "kernel_id": K16_TILE_KERNEL.kernel_id,
        "k_slices": K16_TILE_KERNEL.k_slices,
        "guest_workspace_words": K16_DRIVER_WORKSPACE_WORDS,
        "dense_reference_kernel": FULL_U_TILE_KERNEL.kernel_id,
    })


class PairTileGenerationExecutor:
    """Execute all 256 tiles in parallel and publish only a verified full generation.

    K16 guest calls run in a bounded worker pool. Dense full-U reference calls
    run on the coordinator thread, one at a time, so their larger 73,990-word
    workspace is not multiplied by the tile worker count. Tile outputs are
    streamed into unpublished candidate pages; only compact evidence is kept
    in memory until the canonical manifest is sealed.
    """

    def __init__(self, *, source: PairTilePageSource, guest: NativePairTileGuest,
                 page_store: CandidatePageStore, max_workers: int = 3,
                 guest_budget_words: int = DEFAULT_GUEST_BUDGET_WORDS,
                 grid: TileGrid | None = None) -> None:
        if not isinstance(max_workers, int) or isinstance(max_workers, bool) or max_workers < 1:
            raise PairTileExecutionError("max_workers must be a positive integer")
        if not isinstance(guest_budget_words, int) or isinstance(guest_budget_words, bool) or guest_budget_words < 1:
            raise PairTileExecutionError("guest_budget_words must be a positive integer")
        self.source, self.guest, self.page_store = source, guest, page_store
        self.grid = grid or TileGrid(kernel_id=DEFAULT_KERNEL_ID)
        if self.grid.kernel_id != K16_TILE_KERNEL.kernel_id:
            raise PairTileExecutionError("the page executor requires the native K16 driver")
        required = DENSE_REFERENCE_WORKSPACE_WORDS + max_workers * K16_DRIVER_WORKSPACE_WORDS
        if required > guest_budget_words:
            maximum = max(0, (guest_budget_words - DENSE_REFERENCE_WORKSPACE_WORDS) // K16_DRIVER_WORKSPACE_WORDS)
            raise PairTileExecutionError(
                f"{max_workers} workers plus one dense reference need {required} words; "
                f"budget is {guest_budget_words} (maximum workers: {maximum})"
            )
        self.max_workers = max_workers
        self.guest_budget_words = guest_budget_words

    def execute(self, *, expected_operator_digest: str | None = None) -> TileManifest:
        snapshot = self.source.pin_snapshot(expected_operator_digest=expected_operator_digest)
        snapshot.validate()
        target_generation = snapshot.generation + 1
        plan_digest = build_pair_plan_digest(snapshot, self.grid, target_generation=target_generation)
        publication = AtomicTilePublication(
            grid=self.grid, generation=target_generation, plan_digest=plan_digest,
            expected_kernel_id=K16_TILE_KERNEL.kernel_id,
        )
        candidate = self.page_store.begin_candidate(
            expected_current_generation=snapshot.generation,
            target_generation=target_generation,
            plan_digest=plan_digest,
            snapshot=snapshot,
        )
        evidence: dict[int, TileEvidence] = {}

        def run_one(descriptor: TileDescriptor) -> tuple[TileDescriptor, bytes]:
            strips = _tile_strips(self.source, snapshot, descriptor)
            output = self.guest.run_k16_driver(descriptor, strips, snapshot)
            if not isinstance(output, bytes) or len(output) != OUTPUT_TILE_BYTES:
                raise PairTileExecutionError(
                    f"native K16 driver returned an invalid output tile for {descriptor.tile_index}"
                )
            return descriptor, output

        try:
            with ThreadPoolExecutor(max_workers=self.max_workers,
                                    thread_name_prefix="mth-pair-tile") as pool:
                futures: dict[Future[tuple[TileDescriptor, bytes]], TileDescriptor] = {
                    pool.submit(run_one, descriptor): descriptor for descriptor in self.grid
                }
                for future in as_completed(futures):
                    descriptor, output = future.result()
                    reference = self.guest.run_full_u_reference(descriptor, snapshot)
                    if not isinstance(reference, bytes) or len(reference) != OUTPUT_TILE_BYTES:
                        raise PairTileExecutionError(
                            f"dense reference returned an invalid output tile for {descriptor.tile_index}"
                        )
                    if output != reference:
                        raise DenseReferenceMismatchError(
                            f"K16 tile {descriptor.tile_index} differs from full-U reference"
                        )
                    digest = hashlib.sha256(output).hexdigest()
                    self.page_store.write_tile(candidate, descriptor, output, digest)
                    evidence[descriptor.tile_index] = TileEvidence(
                        tile_index=descriptor.tile_index,
                        digest=digest,
                        generation=target_generation,
                        plan_digest=plan_digest,
                        kernel_id=K16_TILE_KERNEL.kernel_id,
                        k_slices=K16_TILE_KERNEL.k_slices,
                        note="byte-identical to native full-U reference",
                    )

            if len(evidence) != len(self.grid):
                raise PairTileExecutionError("not all 256 tile results were verified")
            for index in range(len(self.grid)):
                publication.add_tile(evidence[index])
            manifest = publication.publish()
            output_page_set_digest = self.page_store.candidate_page_set_digest(candidate)
            if (not isinstance(output_page_set_digest, str) or len(output_page_set_digest) != 64
                    or any(c not in "0123456789abcdef" for c in output_page_set_digest)):
                raise PairTileExecutionError("candidate page-set digest is not SHA-256 hex")
            self.page_store.publish_candidate(
                candidate,
                expected_current_generation=snapshot.generation,
                expected_page_set_digest=output_page_set_digest,
                manifest=manifest,
            )
            return manifest
        except BaseException:
            self.page_store.discard_candidate(candidate)
            raise


__all__ = [
    "CandidatePageStore",
    "DENSE_REFERENCE_WORKSPACE_WORDS",
    "DEFAULT_GUEST_BUDGET_WORDS",
    "K16_DRIVER_WORKSPACE_WORDS",
    "NativePairTileGuest",
    "OperatorSnapshot",
    "OUTPUT_TILE_BYTES",
    "PageStrip",
    "PairTileExecutionError",
    "PairTileGenerationExecutor",
    "PairTilePageSource",
    "SnapshotMismatchError",
    "DenseReferenceMismatchError",
    "STRIP_BYTES",
    "STRIP_LAYOUT",
    "STRIP_WORDS",
    "build_pair_plan_digest",
]
