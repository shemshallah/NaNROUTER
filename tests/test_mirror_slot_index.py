from __future__ import annotations

import unittest

from runner_riddle.mirror_slot_index import (
    SLOT_COUNT,
    MirrorSlotError,
    pair_for_slot,
    slot_descriptor,
    slot_for_pair,
    validate,
)
from runner_riddle.mirror_memory import pair_id


class MirrorSlotIndexTests(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(pair_for_slot(0), (1, 2))
        self.assertEqual(pair_for_slot(253), (1, 255))
        self.assertEqual(pair_for_slot(254), (2, 3))
        self.assertEqual(pair_for_slot(SLOT_COUNT - 1), (254, 255))

    def test_all_slots_are_unique_inverse_and_contiguous(self):
        seen = set()
        for slot in range(SLOT_COUNT):
            a, b = pair_for_slot(slot)
            self.assertLess(a, b)
            self.assertGreaterEqual(a, 1)
            self.assertLessEqual(b, 255)
            self.assertNotIn((a, b), seen)
            seen.add((a, b))
            self.assertEqual(slot_for_pair(a, b), slot)
            self.assertEqual(slot_descriptor(slot).pair_id, pair_id(a, b))
        self.assertEqual(len(seen), SLOT_COUNT)

    def test_descriptor_offset_and_digestable_status(self):
        record = slot_descriptor(0)
        self.assertEqual(record.record_offset, 98048)
        self.assertEqual(record.pair_id, 256)
        report = validate()
        self.assertEqual(report["status"], "green")
        self.assertEqual(report["slots"], 32385)
        self.assertEqual(report["coverage"], 1.0)
        self.assertEqual(report["first_pair"], (1, 2))
        self.assertEqual(report["last_pair"], (254, 255))
        self.assertEqual(report["last_pair_id"], 32640)

    def test_bounds_rejected(self):
        for bad in (-1, SLOT_COUNT, True, 1.0, "0"):
            with self.subTest(bad=bad):
                with self.assertRaises(MirrorSlotError):
                    pair_for_slot(bad)
        for a, b in ((1, 1), (0, 2), (2, 1), (255, 256)):
            with self.subTest(a=a, b=b):
                with self.assertRaises(MirrorSlotError):
                    slot_for_pair(a, b)


if __name__ == "__main__":
    unittest.main()
