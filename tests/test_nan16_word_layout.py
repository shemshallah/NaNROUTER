from __future__ import annotations

import json
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
LAYOUT = REPO / "spec" / "nan16-word-layout.json"


class Nan16WordLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads(LAYOUT.read_text())

    def test_word_and_face_shape_is_frozen(self):
        doc = self.document
        self.assertEqual(doc["schema"], "nanrouter.nan16-word-layout.v1")
        self.assertEqual(doc["word_bits"], 64)
        self.assertEqual(doc["word_bytes"], 8)
        self.assertEqual(doc["face_count"], 2)
        self.assertEqual(doc["face_bits"], 32)
        self.assertEqual(doc["face_bits"] * doc["face_count"], doc["word_bits"])
        self.assertEqual(doc["ordered_class_bits"], 4)
        self.assertEqual(doc["face_class_bits"], 2)

    def test_all_sixteen_ordered_class_pairs_are_distinct(self):
        pairs = self.document["class_pairs"]
        self.assertEqual(len(pairs), 16)
        self.assertEqual({row["class"] for row in pairs}, set(range(16)))
        for row in pairs:
            self.assertEqual(
                row["class"], (row["near"] << 2) | row["far"]
            )
            self.assertIn(row["near"], range(4))
            self.assertIn(row["far"], range(4))

    def test_face_class_encoding_is_quiet_then_sign(self):
        classes = self.document["face_classes"]
        self.assertEqual(len(classes), 4)
        for row in classes:
            self.assertEqual(
                row["class"], (row["quiet"] << 1) | row["sign"]
            )
        self.assertEqual(
            [(row["sign"], row["quiet"]) for row in classes],
            [(0, 0), (1, 0), (0, 1), (1, 1)],
        )

    def test_bswapm_is_an_involution_and_distinct_from_pair_codec(self):
        bswapm = self.document["bswapm"]
        self.assertTrue(bswapm["swaps_faces"])
        self.assertTrue(bswapm["preserves_class_nibble"])
        self.assertTrue(bswapm["involution"])
        self.assertIn(
            "not the double-endian redundant pair codec",
            " ".join(self.document["non_claims"]),
        )


if __name__ == "__main__":
    unittest.main()
