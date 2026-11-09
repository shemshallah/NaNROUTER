"""Host-only crash-safe snapshots of the 8 MiB mirror root and arena bytes.

This adapter persists exactly two opaque byte regions:

* the fixed 8,388,608 byte mirror root, and
* a variable-length hyperedge arena.

The file layout is one fixed header followed by the root and arena bytes.  The
header binds the format version, generation, both lengths, both SHA-256
digests, and a CRC-32 over the header fields.  Publication is a temp-file
write in the destination directory, ``fsync`` of the file, ``os.replace``, and
``fsync`` of the directory.  An existing newer generation is never replaced.

Reading validates magic, version, header checksum, lengths, file size, both
content digests, and (optionally) an expected generation/arena length before
returning any bytes.  The bytes are opaque: nothing is parsed, executed, used
for host arithmetic, or merged into a canonical universe.  No C++/torch or
native execution is involved.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import hmac
import os
from pathlib import Path
import struct
import tempfile
from typing import Iterator
import zlib

SCHEMA = "nanrouter.mirror-root-snapshot/1"
MAGIC = b"N16MR01\x00"
VERSION = 1
ROOT_BYTES = 8 * 1024 * 1024

# <magic:8> <version:4> <header_bytes:4> <generation:8>
# <root_len:8> <arena_len:8> <root_sha256:32> <arena_sha256:32>
# <header_crc32:4> <reserved:20>
HEADER_STRUCT = struct.Struct("<8sIIQQQ32s32sI20x")
HEADER_BYTES = HEADER_STRUCT.size
HEADER_CRC_OFFSET = struct.calcsize("<8sIIQQQ32s32s")
HEADER_CRC_BYTES = 4
GENERATION_OFFSET = 16
ROOT_LENGTH_OFFSET = 24
ARENA_LENGTH_OFFSET = 32
ROOT_DIGEST_OFFSET = 40
ARENA_DIGEST_OFFSET = 72

_SNAPSHOT_DOMAIN = b"nanrouter.mirror-root-snapshot/1\x00"
_TEMP_PREFIX = ".n16mr-"
_TEMP_SUFFIX = ".tmp"


class MirrorRootSnapshotError(ValueError):
    """Base error for mirror-root snapshot input, storage, or validation."""


class MirrorRootSnapshotCorrupt(MirrorRootSnapshotError):
    """The snapshot header, lengths, or content digests are not trustworthy."""


class MirrorRootSnapshotTruncated(MirrorRootSnapshotCorrupt):
    """The snapshot file is shorter than the header declares."""


class MirrorRootSnapshotForeign(MirrorRootSnapshotCorrupt):
    """The snapshot does not carry this adapter's magic."""


class MirrorRootSnapshotStale(MirrorRootSnapshotError):
    """A generation expectation or monotonic write check failed."""


@dataclass(frozen=True)
class MirrorRootSnapshot:
    """A verified, immutable copy of the root and arena bytes."""

    generation: int
    root: bytes
    arena: bytes
    root_sha256: str
    arena_sha256: str

    @property
    def root_length(self) -> int:
        return len(self.root)

    @property
    def arena_length(self) -> int:
        return len(self.arena)

    @property
    def digest(self) -> str:
        """Deterministic digest binding generation, root, and arena bytes."""
        return snapshot_digest(self.root, self.arena, generation=self.generation)


@dataclass(frozen=True)
class _Header:
    generation: int
    root_length: int
    arena_length: int
    root_sha256: bytes
    arena_sha256: bytes


def _require_generation(name: str, value: object) -> int:
    if type(value) is not int or value < 0:
        raise MirrorRootSnapshotError(f"{name} must be a nonnegative integer")
    return value


def _require_bytes(name: str, value: object) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise MirrorRootSnapshotError(f"{name} must be bytes")
    return bytes(value)


def _require_root(value: object) -> bytes:
    root = _require_bytes("root", value)
    if len(root) != ROOT_BYTES:
        raise MirrorRootSnapshotError(
            f"root has {len(root)} bytes; expected exactly {ROOT_BYTES}"
        )
    return root


def snapshot_digest(root: object, arena: object, *, generation: int = 0) -> str:
    """Return a deterministic SHA-256 over generation, root, and arena bytes."""
    root = _require_bytes("root", root)
    arena = _require_bytes("arena", arena)
    generation = _require_generation("generation", generation)
    digest = hashlib.sha256()
    digest.update(_SNAPSHOT_DOMAIN)
    digest.update(struct.pack("<IQQ", VERSION, generation, len(root)))
    digest.update(root)
    digest.update(struct.pack("<Q", len(arena)))
    digest.update(arena)
    return digest.hexdigest()


def _build_header(generation: int, root: bytes, arena: bytes) -> bytes:
    prefix = struct.pack(
        "<8sIIQQQ32s32s",
        MAGIC,
        VERSION,
        HEADER_BYTES,
        generation,
        len(root),
        len(arena),
        hashlib.sha256(root).digest(),
        hashlib.sha256(arena).digest(),
    )
    if len(prefix) != HEADER_CRC_OFFSET:
        raise AssertionError("snapshot header layout drifted")
    crc = zlib.crc32(prefix) & 0xFFFFFFFF
    return prefix + struct.pack("<I", crc) + b"\x00" * (
        HEADER_BYTES - HEADER_CRC_OFFSET - HEADER_CRC_BYTES
    )


def _parse_header(raw: bytes) -> _Header:
    if len(raw) != HEADER_BYTES:
        raise MirrorRootSnapshotTruncated(
            f"snapshot header has {len(raw)} bytes; expected {HEADER_BYTES}"
        )
    (magic, version, header_bytes, generation, root_length, arena_length,
     root_digest, arena_digest, stored_crc) = HEADER_STRUCT.unpack(raw)
    if magic != MAGIC:
        raise MirrorRootSnapshotForeign("snapshot magic is foreign")
    if version != VERSION:
        raise MirrorRootSnapshotCorrupt(
            f"snapshot version {version} is not supported (expected {VERSION})"
        )
    if header_bytes != HEADER_BYTES:
        raise MirrorRootSnapshotCorrupt(
            f"header declares {header_bytes} bytes; expected {HEADER_BYTES}"
        )
    actual_crc = zlib.crc32(raw[:HEADER_CRC_OFFSET]) & 0xFFFFFFFF
    if stored_crc != actual_crc:
        raise MirrorRootSnapshotCorrupt("snapshot header CRC-32 mismatch")
    if root_length != ROOT_BYTES:
        raise MirrorRootSnapshotCorrupt(
            f"root length {root_length} does not equal {ROOT_BYTES}"
        )
    return _Header(
        generation=generation,
        root_length=root_length,
        arena_length=arena_length,
        root_sha256=root_digest,
        arena_sha256=arena_digest,
    )


def _read_exact(stream, size: int, what: str) -> bytes:
    chunks = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise MirrorRootSnapshotTruncated(
                f"snapshot ended before {what} was complete"
            )
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_verified(path: Path, *, expected_generation: int | None,
                   expected_arena_len: int | None) -> MirrorRootSnapshot:
    with open(path, "rb") as stream:
        file_size = os.fstat(stream.fileno()).st_size
        if file_size < HEADER_BYTES:
            raise MirrorRootSnapshotTruncated(
                f"snapshot has {file_size} bytes; header requires {HEADER_BYTES}"
            )
        header = _parse_header(_read_exact(stream, HEADER_BYTES, "the header"))
        if expected_generation is not None:
            expected_generation = _require_generation(
                "expected_generation", expected_generation
            )
            if header.generation != expected_generation:
                raise MirrorRootSnapshotStale(
                    f"snapshot generation {header.generation} does not match "
                    f"expected {expected_generation}"
                )
        if expected_arena_len is not None:
            if type(expected_arena_len) is not int or expected_arena_len < 0:
                raise MirrorRootSnapshotError(
                    "expected_arena_len must be a nonnegative integer"
                )
            if header.arena_length != expected_arena_len:
                raise MirrorRootSnapshotCorrupt(
                    f"arena length {header.arena_length} does not match "
                    f"expected {expected_arena_len}"
                )
        declared_size = HEADER_BYTES + header.root_length + header.arena_length
        if file_size < declared_size:
            raise MirrorRootSnapshotTruncated(
                f"snapshot has {file_size} bytes; header declares {declared_size}"
            )
        if file_size > declared_size:
            raise MirrorRootSnapshotCorrupt(
                f"snapshot has {file_size} bytes; header declares {declared_size} "
                "(torn or trailing bytes)"
            )
        root = _read_exact(stream, header.root_length, "the root")
        arena = _read_exact(stream, header.arena_length, "the arena")
        if stream.read(1):
            raise MirrorRootSnapshotCorrupt(
                "snapshot grew while being read (torn input)"
            )
    root_digest = hashlib.sha256(root).digest()
    arena_digest = hashlib.sha256(arena).digest()
    if not hmac.compare_digest(root_digest, header.root_sha256):
        raise MirrorRootSnapshotCorrupt("snapshot root SHA-256 mismatch")
    if not hmac.compare_digest(arena_digest, header.arena_sha256):
        raise MirrorRootSnapshotCorrupt("snapshot arena SHA-256 mismatch")
    return MirrorRootSnapshot(
        generation=header.generation,
        root=root,
        arena=arena,
        root_sha256=root_digest.hex(),
        arena_sha256=arena_digest.hex(),
    )


@contextmanager
def _directory_lock(directory: Path) -> Iterator[None]:
    """Serialize cooperating writers without leaving a lock-file residue."""
    try:
        import fcntl
    except ImportError:  # pragma: no cover - non-POSIX hosts
        yield
        return
    fd = os.open(directory, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _fsync_directory(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class MirrorRootSnapshotAdapter:
    """Read and atomically publish one root+arena snapshot file."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)

    def read(self, *, expected_generation: int | None = None,
             expected_arena_len: int | None = None) -> MirrorRootSnapshot:
        """Read and fully verify a snapshot before returning any bytes."""
        return _read_verified(
            self.path,
            expected_generation=expected_generation,
            expected_arena_len=expected_arena_len,
        )

    def write(self, root: object, arena: object = b"", *,
              generation: int,
              expected_generation: int | None = None) -> MirrorRootSnapshot:
        """Atomically publish a snapshot; never replace a newer generation.

        ``expected_generation`` is an optional compare-and-swap expectation
        against the currently published file (0 when no file exists).  Equal
        generation with identical bytes is an idempotent no-op; equal
        generation with different bytes is rejected, as is any lower
        generation.
        """
        root = _require_root(root)
        arena = _require_bytes("arena", arena)
        generation = _require_generation("generation", generation)
        if expected_generation is not None:
            expected_generation = _require_generation(
                "expected_generation", expected_generation
            )

        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.parent.is_dir():
            raise MirrorRootSnapshotError("snapshot parent is not a directory")
        header = _build_header(generation, root, arena)
        root_digest = header[
            ROOT_DIGEST_OFFSET:ROOT_DIGEST_OFFSET + 32
        ]
        arena_digest = header[
            ARENA_DIGEST_OFFSET:ARENA_DIGEST_OFFSET + 32
        ]

        with _directory_lock(self.path.parent):
            existing = None
            if self.path.exists():
                existing = _read_verified(
                    self.path, expected_generation=None, expected_arena_len=None
                )
            if expected_generation is not None:
                current = existing.generation if existing is not None else 0
                if current != expected_generation:
                    raise MirrorRootSnapshotStale(
                        f"snapshot generation {current} does not match expected "
                        f"{expected_generation}"
                    )
            if existing is not None:
                if existing.generation > generation:
                    raise MirrorRootSnapshotStale(
                        f"refusing to replace generation {existing.generation} "
                        f"with older generation {generation}"
                    )
                if existing.generation == generation:
                    if (existing.root_sha256 == root_digest.hex()
                            and existing.arena_sha256 == arena_digest.hex()
                            and existing.arena_length == len(arena)):
                        return existing
                    raise MirrorRootSnapshotStale(
                        f"generation {generation} already names different bytes"
                    )

            fd, temporary_name = tempfile.mkstemp(
                prefix=_TEMP_PREFIX, suffix=_TEMP_SUFFIX,
                dir=self.path.parent,
            )
            temporary = Path(temporary_name)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(header)
                    stream.write(root)
                    stream.write(arena)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
                _fsync_directory(self.path.parent)
            finally:
                if temporary.exists():
                    temporary.unlink()

        return MirrorRootSnapshot(
            generation=generation,
            root=root,
            arena=arena,
            root_sha256=root_digest.hex(),
            arena_sha256=arena_digest.hex(),
        )


# Conventional aliases for callers that prefer a store/function API.
MirrorRootSnapshotStore = MirrorRootSnapshotAdapter


def read_snapshot(path: str | os.PathLike[str], *,
                  expected_generation: int | None = None,
                  expected_arena_len: int | None = None) -> MirrorRootSnapshot:
    return MirrorRootSnapshotAdapter(path).read(
        expected_generation=expected_generation,
        expected_arena_len=expected_arena_len,
    )


def write_snapshot(path: str | os.PathLike[str], root: object,
                   arena: object = b"", *, generation: int,
                   expected_generation: int | None = None) -> MirrorRootSnapshot:
    return MirrorRootSnapshotAdapter(path).write(
        root, arena, generation=generation,
        expected_generation=expected_generation,
    )
