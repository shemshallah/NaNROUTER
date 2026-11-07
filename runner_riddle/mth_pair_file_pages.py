"""Immutable file-backed 16x16 NaN16 matrix pages and atomic output generations.

The format is deliberately separate from BS0DB/MC0DB control databases and
never mounts, formats, or mutates provider volumes. A caller supplies a root
directory on the desired storage tier.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid
from typing import Any, Sequence

from .mth_pair_tile_executor import (
    NAN16_WORD_BYTES,
    OperatorSnapshot,
    PageStrip,
    STRIP_BYTES,
)
from .wave_tile_orchestrator import TileDescriptor, TileManifest

PAGE_SIDE = 16
MATRIX_SIDE = 256
PAGE_WORDS = PAGE_SIDE * PAGE_SIDE
PAGE_BYTES = PAGE_WORDS * NAN16_WORD_BYTES
PAGE_COUNT = (MATRIX_SIDE // PAGE_SIDE) ** 2
PAGE_STORE_SCHEMA = "nanrouter.mth-pair-page-store.v1"
OPERATOR_SCHEMA = "nanrouter.mth-pair-operator-pages.v1"
OUTPUT_HEAD_SCHEMA = "nanrouter.mth-pair-output-head.v1"
OUTPUT_GENERATION_SCHEMA = "nanrouter.mth-pair-output-generation.v1"


class FilePageStoreError(RuntimeError):
    """Base error for immutable matrix pages and atomic output generations."""


class StaleOutputGenerationError(FilePageStoreError):
    """The canonical output head no longer matches the expected base generation."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _valid_digest(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_json(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(json.dumps(document, sort_keys=True, indent=2).encode("utf-8") + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


@dataclass
class FileCandidate:
    candidate_id: str
    staging_path: Path
    base_generation: int
    target_generation: int
    plan_digest: str
    snapshot: OperatorSnapshot
    tile_digests: dict[int, str] = field(default_factory=dict)
    published_path: Path | None = None


class FilePairTilePageStore:
    """Concrete read-only input snapshot + candidate output page store.

    Each 256x256 matrix is stored as 256 row-major 16x16 page files. A page is
    exactly 256 little-endian 64-bit NaN16 words (2,048 bytes). Input operator
    directories are immutable and addressed by their content-derived digest.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.operators = self.root / "operators"
        self.outputs = self.root / "outputs"
        self.staging = self.outputs / "staging"
        self.generations = self.outputs / "generations"
        self.current_operator_path = self.root / "CURRENT_OPERATOR.json"
        self.current_output_path = self.outputs / "CURRENT_OUTPUT.json"
        self.lock_path = self.outputs / ".publish.lock"
        for path in (self.operators, self.staging, self.generations):
            path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _page_name(tile_row: int, tile_col: int) -> str:
        return f"r{tile_row:03d}_c{tile_col:03d}.n16"

    @classmethod
    def install_operator_snapshot(
        cls, root: str | Path, *, generation: int,
        l_pages: Sequence[bytes], u_pages: Sequence[bytes],
        make_current: bool = True,
    ) -> OperatorSnapshot:
        """Install a complete immutable operator from two row-major page lists.

        This is an ingestion helper. It requires exactly 256 pages per matrix
        and never overwrites an existing operator digest.
        """
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
            raise FilePageStoreError("generation must be a non-negative integer")
        if len(l_pages) != PAGE_COUNT or len(u_pages) != PAGE_COUNT:
            raise FilePageStoreError("L and U must each contain exactly 256 pages")
        for page in (*l_pages, *u_pages):
            if not isinstance(page, bytes) or len(page) != PAGE_BYTES:
                raise FilePageStoreError("every matrix page must be exactly 2,048 bytes")

        l_hashes = [_sha256(page) for page in l_pages]
        u_hashes = [_sha256(page) for page in u_pages]
        l_hasher, u_hasher = hashlib.sha256(), hashlib.sha256()
        for page in l_pages:
            l_hasher.update(page)
        for page in u_pages:
            u_hasher.update(page)
        l_digest, u_digest = l_hasher.hexdigest(), u_hasher.hexdigest()
        page_set_digest = _sha256(
            b"L\0" + bytes.fromhex(l_digest) + b"U\0" + bytes.fromhex(u_digest)
        )
        core = {
            "schema": OPERATOR_SCHEMA,
            "generation": generation,
            "shape": [MATRIX_SIDE, MATRIX_SIDE],
            "page_shape": [PAGE_SIDE, PAGE_SIDE],
            "word_bytes": NAN16_WORD_BYTES,
            "word_encoding": "little-endian-nan16-u64",
            "l_digest": l_digest,
            "u_digest": u_digest,
            "page_set_digest": page_set_digest,
            "l_page_digests": l_hashes,
            "u_page_digests": u_hashes,
        }
        operator_digest = _sha256(_canonical(core))
        manifest = {**core, "operator_digest": operator_digest}
        store = cls(root)
        destination = store.operators / operator_digest
        if destination.exists():
            raise FilePageStoreError("operator digest already exists; immutable input pages cannot be replaced")
        temporary = store.operators / (".install-" + uuid.uuid4().hex)
        try:
            for matrix, pages in (("L", l_pages), ("U", u_pages)):
                matrix_dir = temporary / matrix
                matrix_dir.mkdir(parents=True)
                for index, page in enumerate(pages):
                    row, col = divmod(index, MATRIX_SIDE // PAGE_SIDE)
                    (matrix_dir / cls._page_name(row, col)).write_bytes(page)
            (temporary / "operator.json").write_bytes(
                json.dumps(manifest, sort_keys=True, indent=2).encode("utf-8") + b"\n"
            )
            _fsync_directory(temporary / "L")
            _fsync_directory(temporary / "U")
            _fsync_directory(temporary)
            os.replace(temporary, destination)
            _fsync_directory(store.operators)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        snapshot = OperatorSnapshot(
            generation=generation,
            operator_digest=operator_digest,
            l_digest=l_digest,
            u_digest=u_digest,
            page_set_digest=page_set_digest,
            snapshot_id=_sha256(_canonical(manifest)),
        )
        if make_current:
            _atomic_json(store.current_operator_path, {
                "schema": "nanrouter.mth-current-operator.v1",
                "generation": generation,
                "operator_digest": operator_digest,
                "snapshot_id": snapshot.snapshot_id,
            })
        return snapshot

    def _load_operator_manifest(self, operator_digest: str) -> dict[str, Any]:
        if not _valid_digest(operator_digest):
            raise FilePageStoreError("operator digest must be lowercase SHA-256 hex")
        path = self.operators / operator_digest / "operator.json"
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise FilePageStoreError("immutable operator manifest is unavailable or invalid") from exc
        if not isinstance(manifest, dict) or manifest.get("schema") != OPERATOR_SCHEMA:
            raise FilePageStoreError("unsupported operator page manifest")
        core = {k: v for k, v in manifest.items() if k != "operator_digest"}
        if _sha256(_canonical(core)) != operator_digest or manifest.get("operator_digest") != operator_digest:
            raise FilePageStoreError("operator manifest digest mismatch")
        if manifest.get("shape") != [256, 256] or manifest.get("page_shape") != [16, 16]:
            raise FilePageStoreError("unsupported matrix or page shape")
        if len(manifest.get("l_page_digests", [])) != PAGE_COUNT or len(manifest.get("u_page_digests", [])) != PAGE_COUNT:
            raise FilePageStoreError("operator manifest must list all 512 matrix pages")
        return manifest

    def pin_snapshot(self, *, expected_operator_digest: str | None = None) -> OperatorSnapshot:
        if expected_operator_digest is None:
            try:
                pointer = json.loads(self.current_operator_path.read_text(encoding="utf-8"))
                expected_operator_digest = pointer["operator_digest"]
            except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
                raise FilePageStoreError("CURRENT_OPERATOR pointer is unavailable or invalid") from exc
        manifest = self._load_operator_manifest(expected_operator_digest)
        root = self.operators / expected_operator_digest
        # Verify all input pages before pinning; subsequent reads verify their own
        # page hashes again to detect mutation after this initial scan.
        for matrix, hashes_key in (("L", "l_page_digests"), ("U", "u_page_digests")):
            for index, expected_hash in enumerate(manifest[hashes_key]):
                row, col = divmod(index, MATRIX_SIDE // PAGE_SIDE)
                page_path = root / matrix / self._page_name(row, col)
                try:
                    data = page_path.read_bytes()
                except OSError as exc:
                    raise FilePageStoreError(f"missing immutable {matrix} page {index}") from exc
                if len(data) != PAGE_BYTES or _sha256(data) != expected_hash:
                    raise FilePageStoreError(f"immutable {matrix} page {index} failed digest verification")
        snapshot_id = _sha256(_canonical(manifest))
        return OperatorSnapshot(
            generation=manifest["generation"],
            operator_digest=expected_operator_digest,
            l_digest=manifest["l_digest"],
            u_digest=manifest["u_digest"],
            page_set_digest=manifest["page_set_digest"],
            snapshot_id=snapshot_id,
        )

    def read_strip(self, snapshot: OperatorSnapshot, *, matrix: str,
                   row_base: int, col_base: int, rows: int, cols: int) -> PageStrip:
        snapshot.validate()
        if matrix not in ("L", "U"):
            raise FilePageStoreError("matrix must be L or U")
        if rows not in (16, 256) or cols not in (16, 256) or rows * cols != 4096:
            raise FilePageStoreError("strip shape must be 16x256 or 256x16")
        if row_base % 16 or col_base % 16 or not (0 <= row_base <= 240 and 0 <= col_base <= 240):
            raise FilePageStoreError("strip origin must be a valid 16-aligned matrix tile")
        manifest = self._load_operator_manifest(snapshot.operator_digest)
        if _sha256(_canonical(manifest)) != snapshot.snapshot_id:
            raise FilePageStoreError("snapshot identity changed after pinning")
        if (manifest["generation"], manifest["l_digest"], manifest["u_digest"],
                manifest["page_set_digest"]) != (
            snapshot.generation, snapshot.l_digest, snapshot.u_digest, snapshot.page_set_digest
        ):
            raise FilePageStoreError("snapshot metadata changed after pinning")

        matrix_root = self.operators / snapshot.operator_digest / matrix
        hashes = manifest["l_page_digests"] if matrix == "L" else manifest["u_page_digests"]
        page_data: dict[tuple[int, int], bytes] = {}

        def load_page(tile_row: int, tile_col: int) -> bytes:
            index = tile_row * 16 + tile_col
            path = matrix_root / self._page_name(tile_row, tile_col)
            try:
                data = path.read_bytes()
            except OSError as exc:
                raise FilePageStoreError(f"missing {matrix} page ({tile_row},{tile_col})") from exc
            if len(data) != PAGE_BYTES or _sha256(data) != hashes[index]:
                raise FilePageStoreError(f"{matrix} page ({tile_row},{tile_col}) changed after snapshot pin")
            return data

        if rows == 16:
            tile_row = row_base // 16
            for tile_col in range(16):
                page_data[(tile_row, tile_col)] = load_page(tile_row, tile_col)
            assembled = bytearray()
            for local_row in range(16):
                for tile_col in range(16):
                    page = page_data[(tile_row, tile_col)]
                    start = local_row * 16 * NAN16_WORD_BYTES
                    assembled.extend(page[start:start + 16 * NAN16_WORD_BYTES])
        else:
            tile_col = col_base // 16
            for tile_row in range(16):
                page_data[(tile_row, tile_col)] = load_page(tile_row, tile_col)
            assembled = bytearray().join(
                page_data[(tile_row, tile_col)] for tile_row in range(16)
            )
        if len(assembled) != STRIP_BYTES:
            raise FilePageStoreError("assembled strip has an invalid byte length")
        return PageStrip(
            matrix=matrix, row_base=row_base, col_base=col_base,
            rows=rows, cols=cols, data=bytes(assembled),
            generation=snapshot.generation,
            operator_digest=snapshot.operator_digest,
            matrix_digest=snapshot.l_digest if matrix == "L" else snapshot.u_digest,
            page_set_digest=snapshot.page_set_digest,
        )

    def initialize_output_head(self, *, generation: int, page_set_digest: str) -> None:
        """Initialize the output CAS head once, before the first derived generation."""
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
            raise FilePageStoreError("generation must be a non-negative integer")
        if not _valid_digest(page_set_digest):
            raise FilePageStoreError("page_set_digest must be lowercase SHA-256 hex")
        if self.current_output_path.exists():
            raise FilePageStoreError("output head already exists and is immutable through initialization")
        _atomic_json(self.current_output_path, {
            "schema": OUTPUT_HEAD_SCHEMA,
            "generation": generation,
            "page_set_digest": page_set_digest,
        })

    def begin_candidate(self, *, expected_current_generation: int,
                        target_generation: int, plan_digest: str,
                        snapshot: OperatorSnapshot) -> FileCandidate:
        snapshot.validate()
        try:
            head = json.loads(self.current_output_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise FilePageStoreError("output head must be initialized before candidate execution") from exc
        if head.get("generation") != expected_current_generation:
            raise StaleOutputGenerationError("output head does not match the pinned input generation")
        if target_generation != expected_current_generation + 1:
            raise FilePageStoreError("target generation must be exactly base generation + 1")
        if not _valid_digest(plan_digest):
            raise FilePageStoreError("plan_digest must be lowercase SHA-256 hex")
        candidate_id = uuid.uuid4().hex
        staging_path = self.staging / candidate_id
        (staging_path / "tiles").mkdir(parents=True)
        return FileCandidate(
            candidate_id=candidate_id, staging_path=staging_path,
            base_generation=expected_current_generation,
            target_generation=target_generation, plan_digest=plan_digest,
            snapshot=snapshot,
        )

    def write_tile(self, candidate: FileCandidate, descriptor: TileDescriptor,
                   output: bytes, tile_digest: str) -> None:
        self._require_live_candidate(candidate)
        index = descriptor.tile_index
        if index in candidate.tile_digests:
            raise FilePageStoreError(f"output tile {index} was already written")
        if not isinstance(output, bytes) or len(output) != PAGE_BYTES:
            raise FilePageStoreError("output tile must be exactly one 16x16 NaN16 page")
        if not _valid_digest(tile_digest) or _sha256(output) != tile_digest:
            raise FilePageStoreError("output tile digest mismatch")
        row, col = divmod(index, 16)
        path = candidate.staging_path / "tiles" / self._page_name(row, col)
        fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(output)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, path)
            _fsync_directory(path.parent)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        candidate.tile_digests[index] = tile_digest

    def candidate_page_set_digest(self, candidate: FileCandidate) -> str:
        self._require_live_candidate(candidate)
        if len(candidate.tile_digests) != PAGE_COUNT or set(candidate.tile_digests) != set(range(PAGE_COUNT)):
            raise FilePageStoreError("candidate output must contain all 256 tiles")
        hasher = hashlib.sha256()
        for index in range(PAGE_COUNT):
            row, col = divmod(index, 16)
            path = candidate.staging_path / "tiles" / self._page_name(row, col)
            data = path.read_bytes()
            digest = _sha256(data)
            if digest != candidate.tile_digests[index]:
                raise FilePageStoreError(f"candidate tile {index} changed after write")
            hasher.update(index.to_bytes(2, "big"))
            hasher.update(bytes.fromhex(digest))
        return hasher.hexdigest()

    def publish_candidate(self, candidate: FileCandidate, *, expected_current_generation: int,
                          expected_page_set_digest: str, manifest: TileManifest) -> dict[str, Any]:
        self._require_live_candidate(candidate)
        if expected_current_generation != candidate.base_generation:
            raise StaleOutputGenerationError("publish base generation differs from candidate")
        if manifest.generation != candidate.target_generation or manifest.plan_digest != candidate.plan_digest:
            raise FilePageStoreError("manifest generation or plan digest does not match candidate")
        if len(manifest.tiles) != PAGE_COUNT:
            raise FilePageStoreError("manifest must contain exactly 256 tile records")
        if any(manifest.tiles[i].digest != candidate.tile_digests.get(i) for i in range(PAGE_COUNT)):
            raise FilePageStoreError("manifest tile digests do not match staged output pages")
        actual_page_digest = self.candidate_page_set_digest(candidate)
        if actual_page_digest != expected_page_set_digest:
            raise FilePageStoreError("candidate output page-set digest mismatch")

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+b") as lock_stream:
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
            try:
                try:
                    head = json.loads(self.current_output_path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    raise FilePageStoreError("canonical output head is unavailable") from exc
                if head.get("generation") != expected_current_generation:
                    raise StaleOutputGenerationError("canonical output generation advanced during execution")
                destination = self.generations / f"g{candidate.target_generation:020d}"
                if destination.exists():
                    raise FilePageStoreError("target output generation already exists")
                generation_manifest = {
                    "schema": OUTPUT_GENERATION_SCHEMA,
                    "generation": candidate.target_generation,
                    "base_generation": candidate.base_generation,
                    "plan_digest": candidate.plan_digest,
                    "input_operator_digest": candidate.snapshot.operator_digest,
                    "input_page_set_digest": candidate.snapshot.page_set_digest,
                    "output_page_set_digest": actual_page_digest,
                    "tile_manifest_digest": manifest.digest,
                    "tile_count": PAGE_COUNT,
                }
                _atomic_json(candidate.staging_path / "generation.json", generation_manifest)
                os.replace(candidate.staging_path, destination)
                _fsync_directory(self.generations)
                pointer = {
                    "schema": OUTPUT_HEAD_SCHEMA,
                    "generation": candidate.target_generation,
                    "page_set_digest": actual_page_digest,
                    "tile_manifest_digest": manifest.digest,
                    "plan_digest": candidate.plan_digest,
                }
                _atomic_json(self.current_output_path, pointer)
                candidate.published_path = destination
                return pointer
            finally:
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)

    def discard_candidate(self, candidate: FileCandidate) -> None:
        if not isinstance(candidate, FileCandidate):
            raise FilePageStoreError("candidate handle is invalid")
        if candidate.published_path is None:
            shutil.rmtree(candidate.staging_path, ignore_errors=True)

    @staticmethod
    def _require_live_candidate(candidate: FileCandidate) -> None:
        if not isinstance(candidate, FileCandidate) or candidate.published_path is not None:
            raise FilePageStoreError("candidate is invalid or already published")
        if not candidate.staging_path.is_dir():
            raise FilePageStoreError("candidate staging directory is unavailable")

    def read_output_tile(self, *, generation: int, tile_index: int) -> bytes:
        if not 0 <= tile_index < PAGE_COUNT:
            raise FilePageStoreError("tile index must be in 0..255")
        row, col = divmod(tile_index, 16)
        path = self.generations / f"g{generation:020d}" / "tiles" / self._page_name(row, col)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise FilePageStoreError("published output tile is unavailable") from exc
        if len(data) != PAGE_BYTES:
            raise FilePageStoreError("published output tile has invalid size")
        return data


__all__ = [
    "FileCandidate",
    "FilePageStoreError",
    "FilePairTilePageStore",
    "OPERATOR_SCHEMA",
    "OUTPUT_GENERATION_SCHEMA",
    "OUTPUT_HEAD_SCHEMA",
    "PAGE_BYTES",
    "PAGE_COUNT",
    "PAGE_SIDE",
    "PAGE_STORE_SCHEMA",
    "StaleOutputGenerationError",
]
