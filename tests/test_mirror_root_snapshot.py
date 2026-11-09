"""Crash-safe host-only snapshots of the 8 MiB mirror root and arena bytes."""
import hashlib
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
import zlib

from runner_riddle.mirror_root_snapshot import (
    ARENA_LENGTH_OFFSET, HEADER_BYTES, HEADER_CRC_OFFSET, MAGIC,
    ROOT_BYTES, ROOT_LENGTH_OFFSET, VERSION,
    MirrorRootSnapshotAdapter, MirrorRootSnapshotCorrupt,
    MirrorRootSnapshotError, MirrorRootSnapshotForeign,
    MirrorRootSnapshotStale, MirrorRootSnapshotTruncated,
    read_snapshot, snapshot_digest, write_snapshot,
)

ROOT_A = bytes(range(256)) * (ROOT_BYTES // 256)
ROOT_B = bytes(reversed(range(256))) * (ROOT_BYTES // 256)
ARENA_A = b"hyperedge-arena:A:" + bytes(range(64))
ARENA_B = b"hyperedge-arena:B:" + bytes(range(64, 128))


class MirrorRootSnapshotTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.dir = Path(folder.name)
        self.path = self.dir / "mirror-root.n16mr"
        self.adapter = MirrorRootSnapshotAdapter(self.path)

    def _assert_no_temp_residue(self):
        residue = [
            entry.name for entry in self.dir.iterdir()
            if entry.name.endswith(".tmp") or entry.name.startswith(".n16mr-")
            or entry.name.endswith(".lock")
        ]
        self.assertEqual(residue, [])

    def _patch_header(self, offset, replacement, *, fix_crc=True,
                      path=None):
        path = path or self.path
        blob = bytearray(path.read_bytes())
        blob[offset:offset + len(replacement)] = replacement
        if fix_crc:
            crc = zlib.crc32(blob[:HEADER_CRC_OFFSET]) & 0xFFFFFFFF
            blob[HEADER_CRC_OFFSET:HEADER_CRC_OFFSET + 4] = struct.pack(
                "<I", crc
            )
        path.write_bytes(blob)

    def test_roundtrip_root_and_arena(self):
        written = self.adapter.write(ROOT_A, ARENA_A, generation=1)
        loaded = self.adapter.read(
            expected_generation=1, expected_arena_len=len(ARENA_A)
        )
        self.assertEqual(loaded.generation, 1)
        self.assertEqual(loaded.root, ROOT_A)
        self.assertEqual(loaded.arena, ARENA_A)
        self.assertEqual(loaded.root, written.root)
        self.assertEqual(loaded.arena, written.arena)
        self.assertEqual(loaded.root_length, ROOT_BYTES)
        self.assertEqual(loaded.arena_length, len(ARENA_A))
        self.assertEqual(loaded.root_sha256, hashlib.sha256(ROOT_A).hexdigest())
        self.assertEqual(loaded.arena_sha256, hashlib.sha256(ARENA_A).hexdigest())
        self.assertEqual(
            written.digest,
            snapshot_digest(ROOT_A, ARENA_A, generation=1),
        )
        self.assertEqual(loaded.digest, written.digest)
        self.assertEqual(
            self.path.stat().st_size,
            HEADER_BYTES + ROOT_BYTES + len(ARENA_A),
        )
        self._assert_no_temp_residue()

        empty = self.adapter.write(ROOT_B, b"", generation=2)
        loaded = read_snapshot(self.path, expected_generation=2,
                               expected_arena_len=0)
        self.assertEqual(loaded.root, ROOT_B)
        self.assertEqual(loaded.arena, b"")
        self.assertEqual(loaded.digest, empty.digest)
        self._assert_no_temp_residue()

    def test_deterministic_digest(self):
        first = self.adapter.write(ROOT_A, ARENA_A, generation=7)
        other = MirrorRootSnapshotAdapter(self.dir / "copy.n16mr")
        second = write_snapshot(
            other.path, ROOT_A, ARENA_A, generation=7
        )
        self.assertEqual(first.digest, second.digest)
        self.assertEqual(
            first.digest, snapshot_digest(ROOT_A, ARENA_A, generation=7)
        )
        self.assertEqual(first.digest, self.adapter.read().digest)
        self.assertNotEqual(
            first.digest, snapshot_digest(ROOT_A, ARENA_A, generation=8)
        )
        self.assertNotEqual(first.digest, snapshot_digest(ROOT_A, ARENA_B,
                                                          generation=7))

    def test_atomic_replace_with_newer_generation(self):
        self.adapter.write(ROOT_A, ARENA_A, generation=3)
        old_prefix = self.path.read_bytes()[:HEADER_BYTES + 64]
        replaced = self.adapter.write(ROOT_B, ARENA_B, generation=4)
        loaded = self.adapter.read(expected_generation=4)
        self.assertEqual(replaced.generation, 4)
        self.assertEqual(loaded.generation, 4)
        self.assertEqual(loaded.root, ROOT_B)
        self.assertEqual(loaded.arena, ARENA_B)
        blob = self.path.read_bytes()
        self.assertNotEqual(old_prefix, blob[:HEADER_BYTES + 64])
        self.assertEqual(blob[HEADER_BYTES:HEADER_BYTES + 64], ROOT_B[:64])
        self.assertEqual(blob[-len(ARENA_B):], ARENA_B)
        self._assert_no_temp_residue()

    def test_stale_generation_rejected(self):
        self.adapter.write(ROOT_A, ARENA_A, generation=5)
        original = self.path.read_bytes()
        with self.assertRaises(MirrorRootSnapshotStale):
            self.adapter.write(ROOT_B, ARENA_B, generation=4)
        self.assertEqual(self.path.read_bytes(), original)
        with self.assertRaises(MirrorRootSnapshotStale):
            self.adapter.write(ROOT_B, ARENA_B, generation=5)
        with self.assertRaises(MirrorRootSnapshotStale):
            self.adapter.write(ROOT_A, b"", generation=5)
        with self.assertRaises(MirrorRootSnapshotStale):
            self.adapter.write(ROOT_B, ARENA_B, generation=6,
                               expected_generation=4)
        with self.assertRaises(MirrorRootSnapshotStale):
            self.adapter.write(ROOT_B, ARENA_B, generation=6,
                               expected_generation=6)
        with self.assertRaises(MirrorRootSnapshotStale):
            self.adapter.read(expected_generation=4)
        # Equal generation and identical bytes is an idempotent no-op.
        same = self.adapter.write(ROOT_A, ARENA_A, generation=5)
        self.assertEqual(same.generation, 5)
        self.assertEqual(self.path.read_bytes(), original)
        advanced = self.adapter.write(
            ROOT_B, ARENA_B, generation=6, expected_generation=5
        )
        self.assertEqual(advanced.generation, 6)
        self.assertEqual(self.adapter.read().root, ROOT_B)
        with self.assertRaises(MirrorRootSnapshotStale):
            self.adapter.write(ROOT_A, ARENA_A, generation=5)
        self._assert_no_temp_residue()

    def test_write_rejects_bad_input_before_touching_disk(self):
        for bad_root in (b"", ROOT_A[:-1], ROOT_A + b"x", "not bytes"):
            with self.subTest(bad_root=type(bad_root).__name__):
                with self.assertRaises(MirrorRootSnapshotError):
                    self.adapter.write(bad_root, ARENA_A, generation=1)
        for bad_arena in ("not bytes", 7):
            with self.subTest(bad_arena=type(bad_arena).__name__):
                with self.assertRaises(MirrorRootSnapshotError):
                    self.adapter.write(ROOT_A, bad_arena, generation=1)
        for bad_generation in (-1, True, "1"):
            with self.subTest(bad_generation=bad_generation):
                with self.assertRaises(MirrorRootSnapshotError):
                    self.adapter.write(ROOT_A, ARENA_A,
                                       generation=bad_generation)
        self.assertFalse(self.path.exists())
        self._assert_no_temp_residue()

    def test_corrupted_root_rejected(self):
        self.adapter.write(ROOT_A, ARENA_A, generation=1)
        blob = bytearray(self.path.read_bytes())
        blob[HEADER_BYTES + 12345] ^= 0xFF
        self.path.write_bytes(blob)
        result = None
        with self.assertRaises(MirrorRootSnapshotCorrupt):
            result = self.adapter.read()
        self.assertIsNone(result)

    def test_corrupted_arena_rejected(self):
        self.adapter.write(ROOT_A, ARENA_A, generation=1)
        blob = bytearray(self.path.read_bytes())
        blob[HEADER_BYTES + ROOT_BYTES + 3] ^= 0xFF
        self.path.write_bytes(blob)
        result = None
        with self.assertRaises(MirrorRootSnapshotCorrupt):
            result = self.adapter.read()
        self.assertIsNone(result)

    def test_corrupted_header_rejected(self):
        cases = (
            ("crc", HEADER_CRC_OFFSET + 1, b"\xff", False),
            ("version", 8, struct.pack("<I", VERSION + 1), True),
            ("header size", 12, struct.pack("<I", HEADER_BYTES + 8), True),
            ("root length", ROOT_LENGTH_OFFSET,
             struct.pack("<Q", ROOT_BYTES - 1), True),
        )
        for name, offset, replacement, fix_crc in cases:
            with self.subTest(name=name):
                path = self.dir / f"header-{name.replace(' ', '-')}.n16mr"
                MirrorRootSnapshotAdapter(path).write(
                    ROOT_A, ARENA_A, generation=1
                )
                self._patch_header(offset, replacement,
                                   fix_crc=fix_crc, path=path)
                with self.assertRaises(MirrorRootSnapshotCorrupt):
                    MirrorRootSnapshotAdapter(path).read()

    def test_truncated_file_rejected(self):
        self.adapter.write(ROOT_A, ARENA_A, generation=1)
        full_size = self.path.stat().st_size
        for size in (0, HEADER_BYTES - 1, HEADER_BYTES,
                     full_size - 1, full_size - len(ARENA_A)):
            with self.subTest(size=size):
                self.path.unlink(missing_ok=True)
                self.adapter.write(ROOT_A, ARENA_A, generation=1)
                with open(self.path, "r+b") as stream:
                    stream.truncate(size)
                with self.assertRaises(MirrorRootSnapshotTruncated):
                    self.adapter.read()

    def test_foreign_magic_rejected(self):
        self.adapter.write(ROOT_A, ARENA_A, generation=1)
        self._patch_header(0, b"FOREIGN!", fix_crc=True)
        self.assertNotEqual(b"FOREIGN!", MAGIC)
        with self.assertRaises(MirrorRootSnapshotForeign):
            self.adapter.read()

    def test_unexpected_arena_length_rejected(self):
        self.adapter.write(ROOT_A, ARENA_A, generation=1)
        for expected in (len(ARENA_A) + 1, len(ARENA_A) - 1):
            with self.subTest(expected=expected):
                with self.assertRaises(MirrorRootSnapshotCorrupt):
                    self.adapter.read(expected_arena_len=expected)

        longer = ARENA_A + b"extra"
        self._patch_header(
            ARENA_LENGTH_OFFSET,
            struct.pack("<Q", len(ARENA_A) + 1),
            fix_crc=True,
        )
        with self.assertRaises(MirrorRootSnapshotTruncated):
            self.adapter.read()

        self.path.unlink()
        self.adapter.write(ROOT_A, longer, generation=2)
        self._patch_header(
            ARENA_LENGTH_OFFSET,
            struct.pack("<Q", len(longer) - 1),
            fix_crc=True,
        )
        with self.assertRaises(MirrorRootSnapshotCorrupt):
            self.adapter.read()
        with self.assertRaises(MirrorRootSnapshotCorrupt):
            self.adapter.read(expected_arena_len=len(longer) - 1)

    def test_no_temp_residue_after_failed_replace(self):
        self.adapter.write(ROOT_A, ARENA_A, generation=1)
        original = self.path.read_bytes()
        with mock.patch(
            "runner_riddle.mirror_root_snapshot.os.replace",
            side_effect=OSError("simulated rename failure"),
        ):
            with self.assertRaises(OSError):
                self.adapter.write(ROOT_B, ARENA_B, generation=2)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.adapter.read().generation, 1)
        self._assert_no_temp_residue()
        self.adapter.write(ROOT_B, ARENA_B, generation=2)
        self.assertEqual(self.adapter.read().generation, 2)
        self._assert_no_temp_residue()


if __name__ == "__main__":
    unittest.main()
