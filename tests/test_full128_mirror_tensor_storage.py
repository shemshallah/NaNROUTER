#!/usr/bin/env python3
"""Storage geometry regression only: never implements tensor learning."""
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from init_full128_mirror_tensor_storage import (
    BANK_BYTES, TOTAL_BYTES, create, physical_offset, verify,
)


class FullMirror128Test(unittest.TestCase):
    def test_full_banks_and_mirror_isolation(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "full_tensor.f32le"
            manifest = Path(d) / "full_tensor.json"
            info = create(path, manifest)
            self.assertEqual(path.stat().st_size, 128 * 1024 * 1024)
            self.assertEqual(info["weights_per_bank"], 256**3)
            self.assertTrue(verify(path, manifest)["verified"])

            x0, canonical, lane0 = physical_offset(0, 1, 2, 3)
            x1, mirrored, lane1 = physical_offset(0, 1, 3, 2)
            xc, canonical_candidate, lane_candidate = physical_offset(1, 1, 2, 3)
            self.assertEqual((canonical, lane0), (765, 0))
            self.assertEqual((mirrored, lane1), (765, 1))
            self.assertEqual((canonical_candidate, lane_candidate), (765, 0))
            self.assertEqual(x1-x0, 4)
            self.assertEqual(xc-x0, BANK_BYTES)
            self.assertNotEqual(x0, xc)

            # Test-only transport exercise, not a training update or
            # admission: neither root nor native model is ever modified.
            with path.open("r+b") as f:
                f.seek(x0)
                f.write(struct.pack("<f", 0.25))
                f.seek(x1)
                f.write(struct.pack("<f", -0.75))
                f.seek(xc)
                f.write(struct.pack("<f", 1.25))
                f.flush()
                f.seek(x0)
                self.assertEqual(struct.unpack("<f", f.read(4))[0], 0.25)
                self.assertEqual(struct.unpack("<f", f.read(4))[0], -0.75)
                f.seek(xc)
                self.assertEqual(struct.unpack("<f", f.read(4))[0], 1.25)
                f.seek(x0)
                f.write(b"\x00" * 8)
                f.seek(xc)
                f.write(b"\x00" * 4)
            self.assertTrue(verify(path, manifest)["verified"])

            # Refuse to overwrite the existing full tensor or its manifest.
            with self.assertRaises(FileExistsError):
                create(path, manifest)

    def test_all_255_active_banks_have_independent_candidate_addresses(self):
        for h in range(255):
            left, cell, lane = physical_offset(0, h, 7, 11)
            reverse, other_cell, other_lane = physical_offset(0, h, 11, 7)
            right, candidate_cell, candidate_lane = physical_offset(1, h, 7, 11)
            self.assertEqual(cell, other_cell)
            self.assertEqual(cell, candidate_cell)
            self.assertEqual((lane, other_lane, candidate_lane), (0, 1, 0))
            self.assertEqual(reverse, left + 4)
            self.assertEqual(right, left + BANK_BYTES)
            self.assertGreaterEqual(left, 0)
            self.assertLess(right + 4, TOTAL_BYTES)

    def test_void_and_nonexistent_banks_reject(self):
        for axis in range(3):
            coords = [1, 2, 3]
            coords[axis] = 255
            with self.assertRaises(ValueError):
                physical_offset(0, *coords)
            coords[axis] = -1
            with self.assertRaises(ValueError):
                physical_offset(0, *coords)
        for bank in [-1, 2]:
            with self.assertRaises(ValueError):
                physical_offset(bank, 1, 2, 3)


if __name__ == "__main__":
    unittest.main()
