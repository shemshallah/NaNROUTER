"""Bounded 256-tile orchestration and atomic publication for R6 pair actions.

The module is a pure Python host control plane.  It builds the deterministic
16x16 tile grid for a 256x256 operand, keeps the execution window to one 16x16
input tile, one 16x16 accumulator/output tile, and one tile descriptor, and
collects per-tile evidence into an all-or-nothing publication manifest.

It does not execute a NaN16 kernel, perform matrix arithmetic, allocate a dense
matrix, open a database, or define a new schema.  A caller-supplied executor
bridges each :class:`TileDescriptor` to the existing K16/block16 kernel ABI.
The kernel selection lives in the descriptor; this module only orders the
tiles, enforces the page-window bound, and publishes after all evidence is
present and bound to the expected plan and generation.

The bounded K16 path is ``mth.graph.pair.tile16.k16.f32``.  Its guest working
set is 1,542 NaN16 words (four 16x16 input blocks, two 16x16 accumulators, and
six scratch words) per K slice; that is the executor's concern.  The host page
window described here is smaller and is counted separately:

    one 16x16 input window              256 words
    one 16x16 accumulator/output window 256 words
    one live tile descriptor              1 word (conservative)
    ------------------------------------------------
    window_words                        513 words = 4,104 bytes

The 1 MiB guest target is 131,072 NaN16 words.  It is deliberately separate
from the 7 GiB active-runner ceiling in ``wave_ring_scheduler``.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field, replace
import hashlib
import json
from typing import Any

ORCHESTRATOR_SCHEMA = "nanrouter.wave-tile-orchestrator.v1"
GRID_SCHEMA = "nanrouter.wave-tile-grid.v1"
EVIDENCE_SCHEMA = "nanrouter.wave-tile-evidence.v1"
MANIFEST_SCHEMA = "nanrouter.atomic-tile-publication.v1"
VERSION = 1

TILE_ROWS = 16
TILE_COLS = 16
GRID_ROWS = 256
GRID_COLS = 256
TILES_PER_AXIS = GRID_ROWS // TILE_ROWS
TILE_COUNT = TILES_PER_AXIS * TILES_PER_AXIS
TILE_WORDS = TILE_ROWS * TILE_COLS

# NaN16 words are 64-bit in the point-0 framing contract.
NAN16_WORD_BYTES = 8
GUEST_BUDGET_BYTES = 2 * 1024 * 1024
GUEST_BUDGET_WORDS = GUEST_BUDGET_BYTES // NAN16_WORD_BYTES
# Reference only: the orchestrator never allocates against this ceiling.
RUNNER_CEILING_BYTES = 7 * 1024 ** 3

TILE_DESCRIPTOR_WORDS = 1

K16_KERNEL_ID = "mth.graph.pair.tile16.k16.f32"
FULL_U_TILE_KERNEL_ID = "mth.graph.pair.tile16.f32"
BLOCK16_KERNEL_ID = "mth.matvec256.block16.f32"
DEFAULT_KERNEL_ID = K16_KERNEL_ID

_DIGEST_LENGTH = 64
_HEX_DIGITS = frozenset("0123456789abcdef")


class TileOrchestratorError(ValueError):
    """Base class for tile-grid, page-window, execution, and publication errors."""


class TileGridError(TileOrchestratorError):
    """The tile grid is not exactly 256 row-major 16x16 descriptors."""


class TileWindowBudgetError(TileOrchestratorError):
    """The live page window exceeds its guest budget or tile-count bound."""


class TileExecutionError(TileOrchestratorError):
    """An executor returned evidence that does not belong to the requested tile."""


class TilePublicationError(TileOrchestratorError):
    """Base class for all-or-nothing publication failures."""


class MissingTileError(TilePublicationError):
    """One or more of the 256 tile evidence entries are absent."""


class DuplicateTileError(TilePublicationError):
    """A tile index was submitted more than once."""


class OutOfOrderTileError(TilePublicationError):
    """Tile evidence was not submitted in deterministic row-major order."""


class GenerationMismatchError(TilePublicationError):
    """Tile evidence belongs to a different generation than the plan."""


class PlanMismatchError(TilePublicationError):
    """Tile evidence belongs to a different plan digest than the plan."""


class KernelMismatchError(TilePublicationError):
    """Tile evidence names a different kernel or K-slice count."""


class PublicationClosedError(TilePublicationError):
    """A manifest was already published; no more evidence may be added."""


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _require_int(name: str, value: Any, *, minimum: int = 0,
                 maximum: int | None = None,
                 error_cls: type[TileOrchestratorError] = TileOrchestratorError) -> int:
    if not _is_int(value):
        raise error_cls(f"{name} must be an integer")
    if value < minimum:
        raise error_cls(f"{name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise error_cls(f"{name} must be <= {maximum}")
    return value


def _require_digest(name: str, value: Any,
                    error_cls: type[TileOrchestratorError] = TileOrchestratorError) -> str:
    if (not isinstance(value, str) or len(value) != _DIGEST_LENGTH
            or any(character not in _HEX_DIGITS for character in value)):
        raise error_cls(f"{name} must be 64 lowercase hexadecimal characters")
    return value


def _require_text(name: str, value: Any, *, maximum: int = 256,
                  error_cls: type[TileOrchestratorError] = TileOrchestratorError) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise error_cls(f"{name} must be a non-empty string of at most {maximum} characters")
    return value


def canonical_json(value: Any) -> str:
    """Return canonical JSON: sorted keys, compact separators, UTF-8 text."""
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
    except (TypeError, ValueError) as exc:
        raise TileOrchestratorError("value must be JSON serializable") from exc


def sha256_canonical_json(value: Any) -> str:
    """Return the lowercase SHA-256 hex digest of :func:`canonical_json`."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TileKernelDescriptor:
    """The existing kernel ABI a tile descriptor is allowed to name."""

    kernel_id: str
    abi: str
    k_slices: int
    guest_workspace_words: int
    description: str = ""

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        _require_text("kernel_id", self.kernel_id, maximum=128)
        _require_text("abi", self.abi, maximum=128)
        _require_int("k_slices", self.k_slices, minimum=1)
        _require_int(
            "guest_workspace_words", self.guest_workspace_words, minimum=0
        )

    @property
    def guest_workspace_bytes(self) -> int:
        return self.guest_workspace_words * NAN16_WORD_BYTES

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "kernel_id": self.kernel_id,
            "abi": self.abi,
            "k_slices": self.k_slices,
            "guest_workspace_words": self.guest_workspace_words,
            "guest_workspace_bytes": self.guest_workspace_bytes,
            "description": self.description,
        }


K16_TILE_KERNEL = TileKernelDescriptor(
    kernel_id=K16_KERNEL_ID,
    abi="mth_graph_pair_tile16_k16_accum_f32",
    k_slices=16,
    guest_workspace_words=1542,
    description=(
        "bounded 16x16 K-slice streaming accumulator and finalizer "
        "(docs/MTH_GRAPH_PAIR_TILE16_K16_ABI_V1.md)"
    ),
)
FULL_U_TILE_KERNEL = TileKernelDescriptor(
    kernel_id=FULL_U_TILE_KERNEL_ID,
    abi="mth_graph_pair_tile16_f32",
    k_slices=1,
    guest_workspace_words=73990,
    description=(
        "full-U 16x16 reference tile; 73,990 words is inside the 1 MiB target "
        "(docs/MTH_GRAPH_PAIR_TILE16_ABI_V1.md)"
    ),
)
MATVEC_BLOCK16_KERNEL = TileKernelDescriptor(
    kernel_id=BLOCK16_KERNEL_ID,
    abi="mth_matvec256_block16",
    k_slices=1,
    guest_workspace_words=4368,
    description=(
        "paged 16x256 matrix-vector block; a 16x16 tile is the bounded "
        "column window (docs/MTH_MATVEC256_BLOCK16_ABI.md)"
    ),
)

TILE_KERNELS = {
    descriptor.kernel_id: descriptor
    for descriptor in (
        K16_TILE_KERNEL,
        FULL_U_TILE_KERNEL,
        MATVEC_BLOCK16_KERNEL,
    )
}
SUPPORTED_KERNEL_IDS = tuple(TILE_KERNELS)


def resolve_tile_kernel(kernel_id: str) -> TileKernelDescriptor:
    """Return the declared descriptor for a supported kernel ID."""
    if not isinstance(kernel_id, str) or kernel_id not in TILE_KERNELS:
        raise TileOrchestratorError(f"unsupported tile kernel_id: {kernel_id!r}")
    return TILE_KERNELS[kernel_id]


@dataclass(frozen=True)
class TileDescriptor:
    """One row-major 16x16 tile and the ABI that may execute it."""

    tile_index: int
    kernel_id: str = DEFAULT_KERNEL_ID

    def __post_init__(self) -> None:
        if not _is_int(self.tile_index):
            raise TileGridError("tile_index must be an integer")
        if not 0 <= self.tile_index < TILE_COUNT:
            raise TileGridError(f"tile_index must be in 0..{TILE_COUNT - 1}")
        try:
            resolve_tile_kernel(self.kernel_id)
        except TileOrchestratorError as exc:
            raise TileGridError(str(exc)) from exc

    @property
    def index(self) -> int:
        return self.tile_index

    @property
    def tile_row(self) -> int:
        return self.tile_index // TILES_PER_AXIS

    @property
    def tile_col(self) -> int:
        return self.tile_index % TILES_PER_AXIS

    @property
    def row(self) -> int:
        return self.tile_row

    @property
    def col(self) -> int:
        return self.tile_col

    @property
    def i_base(self) -> int:
        return self.tile_row * TILE_ROWS

    @property
    def j_base(self) -> int:
        return self.tile_col * TILE_COLS

    @property
    def row_base(self) -> int:
        return self.i_base

    @property
    def col_base(self) -> int:
        return self.j_base

    @property
    def rows(self) -> int:
        return TILE_ROWS

    @property
    def cols(self) -> int:
        return TILE_COLS

    @property
    def shape(self) -> tuple[int, int]:
        return (TILE_ROWS, TILE_COLS)

    @property
    def word_count(self) -> int:
        return TILE_WORDS

    @property
    def kernel(self) -> TileKernelDescriptor:
        return resolve_tile_kernel(self.kernel_id)

    @property
    def k_slices(self) -> int:
        return self.kernel.k_slices

    def to_dict(self) -> dict[str, Any]:
        return {
            "tile_index": self.tile_index,
            "tile_row": self.tile_row,
            "tile_col": self.tile_col,
            "i_base": self.i_base,
            "j_base": self.j_base,
            "rows": self.rows,
            "cols": self.cols,
            "kernel_id": self.kernel_id,
            "k_slices": self.k_slices,
        }


@dataclass(frozen=True)
class TileGrid:
    """Deterministic 16x16-by-16x16 row-major grid for a 256x256 operand."""

    kernel_id: str = DEFAULT_KERNEL_ID
    tiles: tuple[TileDescriptor, ...] = field(init=False)
    digest: str = field(init=False)

    def __post_init__(self) -> None:
        try:
            resolve_tile_kernel(self.kernel_id)
        except TileOrchestratorError as exc:
            raise TileGridError(str(exc)) from exc
        tiles = tuple(
            TileDescriptor(tile_index=index, kernel_id=self.kernel_id)
            for index in range(TILE_COUNT)
        )
        if len(tiles) != TILE_COUNT:
            raise TileGridError(f"tile grid must contain exactly {TILE_COUNT} tiles")
        for position, tile in enumerate(tiles):
            expected_row = position // TILES_PER_AXIS
            expected_col = position % TILES_PER_AXIS
            if tile.tile_index != position:
                raise TileGridError("tile grid is not row-major")
            if (tile.tile_row, tile.tile_col) != (expected_row, expected_col):
                raise TileGridError("tile origins are not row-major")
            if tile.i_base != expected_row * TILE_ROWS:
                raise TileGridError("tile row origin is inconsistent")
            if tile.j_base != expected_col * TILE_COLS:
                raise TileGridError("tile column origin is inconsistent")
        object.__setattr__(self, "tiles", tiles)
        object.__setattr__(self, "digest", sha256_canonical_json(self.payload()))

    @classmethod
    def build(cls, kernel_id: str = DEFAULT_KERNEL_ID) -> "TileGrid":
        return cls(kernel_id=kernel_id)

    @property
    def tile_count(self) -> int:
        return TILE_COUNT

    @property
    def rows(self) -> int:
        return GRID_ROWS

    @property
    def cols(self) -> int:
        return GRID_COLS

    @property
    def kernel(self) -> TileKernelDescriptor:
        return resolve_tile_kernel(self.kernel_id)

    def payload(self) -> dict[str, Any]:
        """Return the canonical grid document without its digest."""
        return {
            "schema": GRID_SCHEMA,
            "version": VERSION,
            "kernel_id": self.kernel_id,
            "tile_rows": TILE_ROWS,
            "tile_cols": TILE_COLS,
            "grid_rows": GRID_ROWS,
            "grid_cols": GRID_COLS,
            "tile_count": TILE_COUNT,
            "tiles": [tile.to_dict() for tile in self.tiles],
        }

    def to_dict(self) -> dict[str, Any]:
        document = self.payload()
        document["grid_digest"] = self.digest
        return document

    def tile(self, tile_index: int) -> TileDescriptor:
        _require_int(
            "tile_index", tile_index, minimum=0, maximum=TILE_COUNT - 1,
            error_cls=TileGridError,
        )
        return self.tiles[tile_index]

    def __iter__(self) -> Iterator[TileDescriptor]:
        return iter(self.tiles)

    def __len__(self) -> int:
        return len(self.tiles)

    def __getitem__(self, tile_index: int) -> TileDescriptor:
        return self.tiles[tile_index]


@dataclass(frozen=True)
class TilePageWindow:
    """The host page window: at most one input and one accumulator/output tile."""

    input_words: int = TILE_WORDS
    accumulator_output_words: int = TILE_WORDS
    descriptor_words: int = TILE_DESCRIPTOR_WORDS
    word_bytes: int = NAN16_WORD_BYTES
    guest_budget_bytes: int = GUEST_BUDGET_BYTES

    def __post_init__(self) -> None:
        _require_int(
            "input_words", self.input_words, minimum=0, maximum=TILE_WORDS,
            error_cls=TileWindowBudgetError,
        )
        _require_int(
            "accumulator_output_words", self.accumulator_output_words,
            minimum=0, maximum=TILE_WORDS, error_cls=TileWindowBudgetError,
        )
        _require_int(
            "descriptor_words", self.descriptor_words, minimum=0,
            maximum=TILE_DESCRIPTOR_WORDS, error_cls=TileWindowBudgetError,
        )
        _require_int(
            "word_bytes", self.word_bytes, minimum=1,
            error_cls=TileWindowBudgetError,
        )
        _require_int(
            "guest_budget_bytes", self.guest_budget_bytes, minimum=0,
            error_cls=TileWindowBudgetError,
        )
        self.assert_within_guest_budget()

    @property
    def input_windows(self) -> int:
        return 1 if self.input_words else 0

    @property
    def accumulator_output_windows(self) -> int:
        return 1 if self.accumulator_output_words else 0

    @property
    def tile_descriptors(self) -> int:
        return 1 if self.descriptor_words else 0

    @property
    def window_words(self) -> int:
        return (
            self.input_words
            + self.accumulator_output_words
            + self.descriptor_words
        )

    @property
    def window_bytes(self) -> int:
        return self.window_words * self.word_bytes

    @property
    def guest_budget_words(self) -> int:
        return self.guest_budget_bytes // self.word_bytes

    @property
    def within_guest_budget(self) -> bool:
        return self.window_bytes <= self.guest_budget_bytes

    def assert_within_guest_budget(self) -> "TilePageWindow":
        if not self.within_guest_budget:
            raise TileWindowBudgetError(
                f"page window of {self.window_words} words "
                f"({self.window_bytes} bytes) exceeds the guest budget of "
                f"{self.guest_budget_bytes} bytes"
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "nanrouter.wave-tile-page-window.v1",
            "version": VERSION,
            "input_words": self.input_words,
            "accumulator_output_words": self.accumulator_output_words,
            "descriptor_words": self.descriptor_words,
            "input_windows": self.input_windows,
            "accumulator_output_windows": self.accumulator_output_windows,
            "tile_descriptors": self.tile_descriptors,
            "window_words": self.window_words,
            "window_bytes": self.window_bytes,
            "word_bytes": self.word_bytes,
            "guest_budget_bytes": self.guest_budget_bytes,
            "guest_budget_words": self.guest_budget_words,
            "within_guest_budget": self.within_guest_budget,
        }


@dataclass(frozen=True)
class TileEvidence:
    """Digest and provenance for one completed 16x16 output tile.

    ``generation``, ``plan_digest``, ``kernel_id``, and ``k_slices`` may be
    omitted when the evidence is submitted directly to a publication; the
    publication binds them to its expected contract.  If supplied, they must
    match.
    """

    tile_index: int
    digest: str
    generation: int | None = None
    plan_digest: str | None = None
    kernel_id: str | None = None
    k_slices: int | None = None
    note: str = ""

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        _require_int(
            "tile_index", self.tile_index, minimum=0, maximum=TILE_COUNT - 1,
            error_cls=TilePublicationError,
        )
        _require_digest("digest", self.digest, error_cls=TilePublicationError)
        if self.generation is not None:
            _require_int(
                "generation", self.generation, minimum=0,
                error_cls=TilePublicationError,
            )
        if self.plan_digest is not None:
            _require_digest(
                "plan_digest", self.plan_digest, error_cls=TilePublicationError
            )
        if self.kernel_id is not None:
            try:
                resolve_tile_kernel(self.kernel_id)
            except TileOrchestratorError as exc:
                raise TilePublicationError(str(exc)) from exc
        if self.k_slices is not None:
            _require_int(
                "k_slices", self.k_slices, minimum=1,
                error_cls=TilePublicationError,
            )
        if not isinstance(self.note, str) or len(self.note) > 256:
            raise TilePublicationError("note must be a string of at most 256 characters")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": EVIDENCE_SCHEMA,
            "tile_index": self.tile_index,
            "digest": self.digest,
            "generation": self.generation,
            "plan_digest": self.plan_digest,
            "kernel_id": self.kernel_id,
            "k_slices": self.k_slices,
            "note": self.note,
        }


@dataclass(frozen=True)
class TileManifest:
    """The single immutable document published after all 256 tiles verify."""

    plan_digest: str
    generation: int
    grid_digest: str
    kernel_id: str
    tiles: tuple[TileEvidence, ...]
    window_words: int
    window_bytes: int
    digest: str = field(init=False)
    schema: str = MANIFEST_SCHEMA
    version: int = VERSION

    def __post_init__(self) -> None:
        _require_digest("plan_digest", self.plan_digest)
        _require_int("generation", self.generation, minimum=0)
        _require_digest("grid_digest", self.grid_digest)
        resolve_tile_kernel(self.kernel_id)
        _require_int("window_words", self.window_words, minimum=0)
        _require_int("window_bytes", self.window_bytes, minimum=0)
        if len(self.tiles) != TILE_COUNT:
            raise TilePublicationError(
                f"manifest must contain exactly {TILE_COUNT} tiles"
            )
        for expected_index, evidence in enumerate(self.tiles):
            if not isinstance(evidence, TileEvidence):
                raise TilePublicationError(
                    "manifest tiles must be TileEvidence instances"
                )
            if evidence.tile_index != expected_index:
                raise OutOfOrderTileError(
                    f"manifest tile order is not row-major at index {expected_index}"
                )
            if evidence.generation != self.generation:
                raise GenerationMismatchError(
                    f"tile {expected_index} generation does not match the manifest"
                )
            if evidence.plan_digest != self.plan_digest:
                raise PlanMismatchError(
                    f"tile {expected_index} plan digest does not match the manifest"
                )
            if evidence.kernel_id != self.kernel_id:
                raise KernelMismatchError(
                    f"tile {expected_index} kernel does not match the manifest"
                )
            expected_slices = resolve_tile_kernel(self.kernel_id).k_slices
            if evidence.k_slices != expected_slices:
                raise KernelMismatchError(
                    f"tile {expected_index} K-slice count does not match the manifest"
                )
        object.__setattr__(self, "digest", sha256_canonical_json(self.payload()))

    @property
    def tile_count(self) -> int:
        return len(self.tiles)

    @property
    def manifest_digest(self) -> str:
        return self.digest

    def payload(self) -> dict[str, Any]:
        """Return the canonical manifest document without its digest."""
        return {
            "schema": self.schema,
            "version": self.version,
            "plan_digest": self.plan_digest,
            "generation": self.generation,
            "grid_digest": self.grid_digest,
            "kernel_id": self.kernel_id,
            "tile_count": TILE_COUNT,
            "tiles": [
                {
                    "tile_index": evidence.tile_index,
                    "tile_row": evidence.tile_index // TILES_PER_AXIS,
                    "tile_col": evidence.tile_index % TILES_PER_AXIS,
                    "digest": evidence.digest,
                    "generation": evidence.generation,
                    "plan_digest": evidence.plan_digest,
                    "kernel_id": evidence.kernel_id,
                    "k_slices": evidence.k_slices,
                    "note": evidence.note,
                }
                for evidence in self.tiles
            ],
            "window_words": self.window_words,
            "window_bytes": self.window_bytes,
        }

    def to_dict(self) -> dict[str, Any]:
        document = self.payload()
        document["manifest_digest"] = self.digest
        return document

    @property
    def document(self) -> dict[str, Any]:
        return self.to_dict()

    def __getitem__(self, key: str) -> Any:
        if key == "digest":
            return self.digest
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        if key == "digest":
            return self.digest
        return self.to_dict().get(key, default)

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())


class AtomicTilePublication:
    """Collect 256 tile evidence entries and publish only a complete manifest.

    Evidence must arrive in deterministic row-major order starting at tile 0.
    A duplicate, an out-of-order tile, a mismatched generation/plan/kernel, or
    a missing tile prevents :meth:`publish` from producing a manifest.  Once a
    manifest exists the publication is closed and always returns the same
    immutable document.
    """

    def __init__(
        self,
        *,
        grid: TileGrid | None = None,
        generation: int | None = None,
        plan_digest: str | None = None,
        expected_generation: int | None = None,
        expected_plan_digest: str | None = None,
        expected_kernel_id: str | None = None,
        window: TilePageWindow | None = None,
        guest_budget_bytes: int | None = None,
    ) -> None:
        if grid is None:
            grid = TileGrid()
        if not isinstance(grid, TileGrid):
            raise TilePublicationError("grid must be a TileGrid")
        if expected_kernel_id is None:
            expected_kernel_id = grid.kernel_id
        else:
            resolve_tile_kernel(expected_kernel_id)
        if grid.kernel_id != expected_kernel_id:
            raise KernelMismatchError(
                "grid kernel_id does not match the expected publication kernel"
            )

        if generation is not None and expected_generation is not None:
            if generation != expected_generation:
                raise TilePublicationError(
                    "generation and expected_generation disagree"
                )
        resolved_generation = (
            generation if generation is not None else expected_generation
        )
        self.generation = (
            0 if resolved_generation is None
            else _require_int("generation", resolved_generation, minimum=0)
        )

        if plan_digest is not None and expected_plan_digest is not None:
            if plan_digest != expected_plan_digest:
                raise PlanMismatchError(
                    "plan_digest and expected_plan_digest disagree"
                )
        resolved_plan = (
            plan_digest if plan_digest is not None else expected_plan_digest
        )
        self.plan_digest = (
            grid.digest if resolved_plan is None
            else _require_digest("plan_digest", resolved_plan)
        )

        if window is not None and not isinstance(window, TilePageWindow):
            raise TileWindowBudgetError("window must be a TilePageWindow")
        if window is None:
            budget = (
                GUEST_BUDGET_BYTES if guest_budget_bytes is None
                else _require_int(
                    "guest_budget_bytes", guest_budget_bytes, minimum=0,
                    error_cls=TileWindowBudgetError,
                )
            )
            window = TilePageWindow(guest_budget_bytes=budget)
        elif (guest_budget_bytes is not None
              and guest_budget_bytes != window.guest_budget_bytes):
            raise TileWindowBudgetError(
                "window guest budget and guest_budget_bytes disagree"
            )
        window.assert_within_guest_budget()

        self.grid = grid
        self.expected_kernel_id = expected_kernel_id
        self.window = window
        self._expected_k_slices = resolve_tile_kernel(expected_kernel_id).k_slices
        self._tiles: dict[int, TileEvidence] = {}
        self._manifest: TileManifest | None = None

    def __repr__(self) -> str:
        return (
            "AtomicTilePublication("
            f"generation={self.generation}, "
            f"received={self.received_count}/{TILE_COUNT}, "
            f"published={self.published})"
        )

    @property
    def expected_generation(self) -> int:
        return self.generation

    @property
    def expected_plan_digest(self) -> str:
        return self.plan_digest

    @property
    def expected_tile_count(self) -> int:
        return TILE_COUNT

    @property
    def tile_count(self) -> int:
        return TILE_COUNT

    @property
    def received_count(self) -> int:
        return len(self._tiles)

    @property
    def missing_indices(self) -> tuple[int, ...]:
        return tuple(
            index for index in range(TILE_COUNT) if index not in self._tiles
        )

    @property
    def is_complete(self) -> bool:
        return len(self._tiles) == TILE_COUNT

    @property
    def published(self) -> bool:
        return self._manifest is not None

    @property
    def manifest(self) -> TileManifest | None:
        return self._manifest

    @property
    def digest(self) -> str | None:
        """Return the sealed manifest digest, or ``None`` before publication."""
        return None if self._manifest is None else self._manifest.digest

    @property
    def manifest_digest(self) -> str | None:
        return self.digest

    @property
    def window_words(self) -> int:
        return self.window.window_words

    @property
    def window_bytes(self) -> int:
        return self.window.window_bytes

    @property
    def guest_budget_bytes(self) -> int:
        return self.window.guest_budget_bytes

    @property
    def guest_budget_words(self) -> int:
        return self.window.guest_budget_words

    @property
    def within_guest_budget(self) -> bool:
        return self.window.within_guest_budget

    def add_tile(
        self,
        tile: TileEvidence | TileDescriptor | int | Mapping[str, Any] | None = None,
        digest: str | None = None,
        *,
        tile_index: int | None = None,
        generation: int | None = None,
        plan_digest: str | None = None,
        kernel_id: str | None = None,
        k_slices: int | None = None,
        note: str = "",
    ) -> TileEvidence:
        """Add one tile's evidence in row-major order.

        ``tile`` may be a :class:`TileEvidence`, a :class:`TileDescriptor`, a
        tile index, or a mapping containing ``tile_index`` and ``digest``.
        The index may also be supplied by keyword as ``tile_index``.
        """
        if self._manifest is not None:
            raise PublicationClosedError(
                "publication is already sealed by a published manifest"
            )
        if tile_index is not None:
            if tile is not None:
                raise TilePublicationError(
                    "provide tile positionally or as tile_index, not both"
                )
            tile = tile_index
        if tile is None:
            raise TilePublicationError("tile evidence requires a tile_index")
        evidence = self._coerce_evidence(
            tile,
            digest,
            generation=generation,
            plan_digest=plan_digest,
            kernel_id=kernel_id,
            k_slices=k_slices,
            note=note,
        )

        if evidence.tile_index in self._tiles:
            raise DuplicateTileError(
                f"tile {evidence.tile_index} was already submitted"
            )
        expected_index = len(self._tiles)
        if evidence.tile_index != expected_index:
            raise OutOfOrderTileError(
                f"expected tile {expected_index} next, received "
                f"tile {evidence.tile_index}"
            )

        bound_generation = (
            self.generation if evidence.generation is None else evidence.generation
        )
        bound_plan = (
            self.plan_digest if evidence.plan_digest is None else evidence.plan_digest
        )
        bound_kernel = (
            self.expected_kernel_id
            if evidence.kernel_id is None else evidence.kernel_id
        )
        bound_k_slices = (
            self._expected_k_slices
            if evidence.k_slices is None else evidence.k_slices
        )

        if bound_generation != self.generation:
            raise GenerationMismatchError(
                f"tile {evidence.tile_index} generation {bound_generation} "
                f"does not match expected {self.generation}"
            )
        if bound_plan != self.plan_digest:
            raise PlanMismatchError(
                f"tile {evidence.tile_index} plan digest does not match "
                "the expected plan"
            )
        if bound_kernel != self.expected_kernel_id:
            raise KernelMismatchError(
                f"tile {evidence.tile_index} kernel {bound_kernel!r} does not "
                f"match expected {self.expected_kernel_id!r}"
            )
        if bound_k_slices != self._expected_k_slices:
            raise KernelMismatchError(
                f"tile {evidence.tile_index} K-slice count {bound_k_slices} "
                f"does not match expected {self._expected_k_slices}"
            )

        normalized = replace(
            evidence,
            generation=bound_generation,
            plan_digest=bound_plan,
            kernel_id=bound_kernel,
            k_slices=bound_k_slices,
        )
        self._tiles[normalized.tile_index] = normalized
        return normalized

    # Familiar aliases for callers and tests.
    add = add_tile
    record_tile = add_tile
    add_evidence = add_tile

    def _coerce_evidence(
        self,
        tile: TileEvidence | TileDescriptor | int | Mapping[str, Any],
        digest: str | None,
        *,
        generation: int | None,
        plan_digest: str | None,
        kernel_id: str | None,
        k_slices: int | None,
        note: str,
    ) -> TileEvidence:
        if isinstance(tile, TileEvidence):
            if any(value is not None for value in (
                digest, generation, plan_digest, kernel_id, k_slices
            )) or note:
                raise TilePublicationError(
                    "extra tile fields must not accompany TileEvidence"
                )
            return tile

        if isinstance(tile, TileDescriptor):
            tile_index = tile.tile_index
            if kernel_id is None:
                kernel_id = tile.kernel_id
            if k_slices is None:
                k_slices = tile.k_slices
        elif isinstance(tile, Mapping):
            data = dict(tile)
            tile_index = data.pop("tile_index", data.pop("index", None))
            if digest is None:
                digest = data.pop("digest", None)
            if generation is None:
                generation = data.pop("generation", None)
            if plan_digest is None:
                plan_digest = data.pop("plan_digest", None)
            if kernel_id is None:
                kernel_id = data.pop("kernel_id", None)
            if k_slices is None:
                k_slices = data.pop("k_slices", None)
            if not note:
                note = data.pop("note", "")
            if data:
                raise TilePublicationError(
                    f"unknown tile evidence fields: {', '.join(sorted(data))}"
                )
        elif _is_int(tile):
            tile_index = tile
        else:
            raise TilePublicationError(
                "tile must be TileEvidence, TileDescriptor, an index, or a mapping"
            )

        if tile_index is None:
            raise TilePublicationError("tile evidence requires a tile_index")
        if digest is None:
            raise TilePublicationError("tile evidence requires a digest")
        if note is None:
            note = ""
        return TileEvidence(
            tile_index=tile_index,
            digest=digest,
            generation=generation,
            plan_digest=plan_digest,
            kernel_id=kernel_id,
            k_slices=k_slices,
            note=note,
        )

    def publish(self) -> TileManifest:
        """Return the sealed manifest, or raise while evidence is incomplete."""
        if self._manifest is not None:
            return self._manifest

        missing = self.missing_indices
        if missing:
            raise MissingTileError(
                f"publication blocked: {len(missing)} of {TILE_COUNT} tiles are "
                f"missing; first missing tile is {missing[0]}"
            )

        ordered = tuple(self._tiles[index] for index in range(TILE_COUNT))
        for expected_index, evidence in enumerate(ordered):
            if evidence.tile_index != expected_index:
                raise OutOfOrderTileError(
                    f"publication tile order is not row-major at index "
                    f"{expected_index}"
                )
            if evidence.generation != self.generation:
                raise GenerationMismatchError(
                    f"tile {expected_index} generation does not match"
                )
            if evidence.plan_digest != self.plan_digest:
                raise PlanMismatchError(
                    f"tile {expected_index} plan digest does not match"
                )
            if evidence.kernel_id != self.expected_kernel_id:
                raise KernelMismatchError(
                    f"tile {expected_index} kernel does not match"
                )
            if evidence.k_slices != self._expected_k_slices:
                raise KernelMismatchError(
                    f"tile {expected_index} K-slice count does not match"
                )

        manifest = TileManifest(
            plan_digest=self.plan_digest,
            generation=self.generation,
            grid_digest=self.grid.digest,
            kernel_id=self.expected_kernel_id,
            tiles=ordered,
            window_words=self.window_words,
            window_bytes=self.window_bytes,
        )
        self._manifest = manifest
        return manifest


class TileOrchestrator:
    """Drive a caller-supplied executor across the 256-tile page window.

    The orchestrator never computes a tile.  For each descriptor in row-major
    order it calls ``executor(descriptor)``.  The executor may return a 64-hex
    tile digest, the raw output-window bytes to digest, a :class:`TileEvidence`,
    or a mapping with a ``digest`` key.  The resulting evidence is added to one
    publication; only a complete publication yields a manifest.
    """

    def __init__(
        self,
        *,
        kernel_id: str = DEFAULT_KERNEL_ID,
        grid: TileGrid | None = None,
        window: TilePageWindow | None = None,
        guest_budget_bytes: int | None = None,
    ) -> None:
        self.kernel = resolve_tile_kernel(kernel_id)
        if grid is None:
            grid = TileGrid(kernel_id=kernel_id)
        if not isinstance(grid, TileGrid):
            raise TileGridError("grid must be a TileGrid")
        if grid.kernel_id != kernel_id:
            raise KernelMismatchError(
                "grid kernel_id does not match the orchestrator kernel"
            )

        if window is not None and not isinstance(window, TilePageWindow):
            raise TileWindowBudgetError("window must be a TilePageWindow")
        if window is None:
            budget = (
                GUEST_BUDGET_BYTES if guest_budget_bytes is None
                else _require_int(
                    "guest_budget_bytes", guest_budget_bytes, minimum=0,
                    error_cls=TileWindowBudgetError,
                )
            )
            window = TilePageWindow(guest_budget_bytes=budget)
        elif (guest_budget_bytes is not None
              and guest_budget_bytes != window.guest_budget_bytes):
            raise TileWindowBudgetError(
                "window guest budget and guest_budget_bytes disagree"
            )
        window.assert_within_guest_budget()

        self.grid = grid
        self.window = window

    def __repr__(self) -> str:
        return (
            "TileOrchestrator("
            f"kernel_id={self.kernel.kernel_id!r}, "
            f"tiles={TILE_COUNT}, window_words={self.window_words})"
        )

    @property
    def kernel_id(self) -> str:
        return self.kernel.kernel_id

    @property
    def tiles(self) -> tuple[TileDescriptor, ...]:
        return self.grid.tiles

    @property
    def tile_count(self) -> int:
        return TILE_COUNT

    @property
    def digest(self) -> str:
        return self.grid.digest

    @property
    def window_words(self) -> int:
        return self.window.window_words

    @property
    def window_bytes(self) -> int:
        return self.window.window_bytes

    @property
    def guest_budget_bytes(self) -> int:
        return self.window.guest_budget_bytes

    @property
    def guest_budget_words(self) -> int:
        return self.window.guest_budget_words

    @property
    def within_guest_budget(self) -> bool:
        return self.window.within_guest_budget

    def iter_tiles(self) -> Iterator[TileDescriptor]:
        """Yield exactly one descriptor at a time in row-major order."""
        return iter(self.grid.tiles)

    def new_publication(
        self,
        *,
        generation: int | None = None,
        plan_digest: str | None = None,
        expected_generation: int | None = None,
        expected_plan_digest: str | None = None,
        guest_budget_bytes: int | None = None,
    ) -> AtomicTilePublication:
        return AtomicTilePublication(
            grid=self.grid,
            generation=generation,
            plan_digest=plan_digest,
            expected_generation=expected_generation,
            expected_plan_digest=expected_plan_digest,
            expected_kernel_id=self.kernel.kernel_id,
            window=self.window,
            guest_budget_bytes=guest_budget_bytes,
        )

    publication_for = new_publication

    def execute(
        self,
        executor: Callable[[TileDescriptor], Any],
        *,
        generation: int | None = None,
        plan_digest: str | None = None,
        expected_generation: int | None = None,
        expected_plan_digest: str | None = None,
        publication: AtomicTilePublication | None = None,
    ) -> TileManifest:
        """Run all 256 tiles and return the sealed manifest.

        Executor exceptions propagate unchanged.  In that case the publication
        remains open and incomplete; no manifest is produced.
        """
        if not callable(executor):
            raise TileExecutionError("executor must be callable")

        if publication is None:
            publication = self.new_publication(
                generation=generation,
                plan_digest=plan_digest,
                expected_generation=expected_generation,
                expected_plan_digest=expected_plan_digest,
            )
        else:
            if not isinstance(publication, AtomicTilePublication):
                raise TilePublicationError(
                    "publication must be an AtomicTilePublication"
                )
            if publication.grid.digest != self.grid.digest:
                raise TilePublicationError(
                    "publication is bound to a different tile grid"
                )
            if publication.expected_kernel_id != self.kernel.kernel_id:
                raise KernelMismatchError(
                    "publication is bound to a different kernel"
                )
            requested_generation = (
                generation if generation is not None else expected_generation
            )
            if (requested_generation is not None
                    and requested_generation != publication.generation):
                raise GenerationMismatchError(
                    "publication generation does not match the requested generation"
                )
            requested_plan = (
                plan_digest if plan_digest is not None else expected_plan_digest
            )
            if (requested_plan is not None
                    and requested_plan != publication.plan_digest):
                raise PlanMismatchError(
                    "publication plan digest does not match the requested plan"
                )

        for descriptor in self.grid.tiles[publication.received_count:]:
            result = executor(descriptor)
            evidence = self._coerce_executor_result(descriptor, result)
            publication.add_tile(evidence)
        return publication.publish()

    run = execute

    @staticmethod
    def _coerce_executor_result(
        descriptor: TileDescriptor, result: Any
    ) -> TileEvidence:
        if isinstance(result, TileEvidence):
            if result.tile_index != descriptor.tile_index:
                raise TileExecutionError(
                    f"executor returned evidence for tile "
                    f"{result.tile_index} while executing tile "
                    f"{descriptor.tile_index}"
                )
            return result

        if isinstance(result, str):
            return TileEvidence(
                tile_index=descriptor.tile_index,
                digest=result,
                kernel_id=descriptor.kernel_id,
                k_slices=descriptor.k_slices,
            )

        if isinstance(result, (bytes, bytearray, memoryview)):
            return TileEvidence(
                tile_index=descriptor.tile_index,
                digest=hashlib.sha256(bytes(result)).hexdigest(),
                kernel_id=descriptor.kernel_id,
                k_slices=descriptor.k_slices,
            )

        if isinstance(result, Mapping):
            data = dict(result)
            tile_index = data.pop(
                "tile_index", data.pop("index", descriptor.tile_index)
            )
            if tile_index != descriptor.tile_index:
                raise TileExecutionError(
                    f"executor returned evidence for tile {tile_index} while "
                    f"executing tile {descriptor.tile_index}"
                )
            digest = data.pop("digest", None)
            if digest is None:
                raise TileExecutionError(
                    f"executor mapping for tile {descriptor.tile_index} has no digest"
                )
            generation = data.pop("generation", None)
            plan_digest = data.pop("plan_digest", None)
            kernel_id = data.pop("kernel_id", descriptor.kernel_id)
            k_slices = data.pop("k_slices", descriptor.k_slices)
            note = data.pop("note", "")
            if data:
                raise TileExecutionError(
                    f"unknown executor evidence fields: {', '.join(sorted(data))}"
                )
            return TileEvidence(
                tile_index=tile_index,
                digest=digest,
                generation=generation,
                plan_digest=plan_digest,
                kernel_id=kernel_id,
                k_slices=k_slices,
                note=note,
            )

        raise TileExecutionError(
            f"executor returned unsupported evidence for tile "
            f"{descriptor.tile_index}: {type(result).__name__}"
        )


# Clear aliases for callers that prefer the longer names.
TilePublication = AtomicTilePublication
AtomicPublication = AtomicTilePublication
TilePublicationManifest = TileManifest

__all__ = [
    "AtomicPublication",
    "AtomicTilePublication",
    "BLOCK16_KERNEL_ID",
    "DEFAULT_KERNEL_ID",
    "DuplicateTileError",
    "EVIDENCE_SCHEMA",
    "FULL_U_TILE_KERNEL",
    "FULL_U_TILE_KERNEL_ID",
    "GRID_COLS",
    "GRID_ROWS",
    "GRID_SCHEMA",
    "GUEST_BUDGET_BYTES",
    "GUEST_BUDGET_WORDS",
    "GenerationMismatchError",
    "K16_KERNEL_ID",
    "K16_TILE_KERNEL",
    "KernelMismatchError",
    "MANIFEST_SCHEMA",
    "MATVEC_BLOCK16_KERNEL",
    "MissingTileError",
    "NAN16_WORD_BYTES",
    "ORCHESTRATOR_SCHEMA",
    "OutOfOrderTileError",
    "PlanMismatchError",
    "PublicationClosedError",
    "RUNNER_CEILING_BYTES",
    "SUPPORTED_KERNEL_IDS",
    "TILE_COUNT",
    "TILE_COLS",
    "TILE_DESCRIPTOR_WORDS",
    "TILE_KERNELS",
    "TILE_ROWS",
    "TILE_WORDS",
    "TILES_PER_AXIS",
    "TileDescriptor",
    "TileEvidence",
    "TileExecutionError",
    "TileGrid",
    "TileGridError",
    "TileKernelDescriptor",
    "TileManifest",
    "TileOrchestrator",
    "TileOrchestratorError",
    "TilePageWindow",
    "TilePublication",
    "TilePublicationError",
    "TilePublicationManifest",
    "TileWindowBudgetError",
    "VERSION",
    "canonical_json",
    "resolve_tile_kernel",
    "sha256_canonical_json",
]
