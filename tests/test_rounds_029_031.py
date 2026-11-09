from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "spec" / "rounds-029-031-native-learning.v1.json"


class Rounds029031EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads(SPEC.read_text(encoding="utf-8"))

    def test_archives_are_pinned(self):
        self.assertEqual(len(self.document["archives"]), 3)
        for entry in self.document["archives"].values():
            self.assertEqual(len(entry["sha256"]), 64)

    def test_round_029_cycle_ties_conventional_and_beats_raw(self):
        results = self.document["round_029"]["results"]
        self.assertEqual(
            results["true_cycle_triangle_shift"]["accuracy"],
            results["correct_conventional_triangle"]["accuracy"],
        )
        self.assertGreater(
            results["true_cycle_triangle_shift"]["accuracy"],
            results["raw_directed_pair_shift"]["accuracy"] * 4,
        )
        native = self.document["round_029"]["native_root"]
        self.assertEqual(native["bytes"], 8388608)
        self.assertLess(native["max_gauge_error"], 2e-6)
        self.assertEqual(native["max_reverse_error"], 0.0)

    def test_round_030_native_training_and_conventional_control(self):
        results = self.document["round_030"]["results"]
        self.assertAlmostEqual(results["mean_cycle_shift_accuracy"], 0.42083333333333334)
        self.assertGreater(
            results["conventional_no_intercept_logistic_accuracy"],
            results["mean_cycle_shift_accuracy"],
        )
        self.assertLess(results["native_gradient_max_abs_error"], 2e-9)
        self.assertLess(results["max_logit_delta_101_shifts"], 3e-4)
        self.assertTrue(results["mirror_antisymmetry"])
        self.assertTrue(results["snapshot_bitwise_restore"])

    def test_round_031_dense_control_wins_bits_per_byte(self):
        bpb = self.document["round_031"]["wordnet_bits_per_byte"]
        for seed in ("seed_17", "seed_29"):
            self.assertLess(bpb[seed]["ordinary"], bpb[seed]["native_cycle"])
        audit = self.document["round_031"]["native_audit"]
        self.assertTrue(audit["mirror_audit"])
        self.assertEqual(audit["snapshot_max_diff"], 0.0)
        self.assertAlmostEqual(audit["gauge_max_diff"], 1.2293457984924316e-06)

    def test_non_claims_block_nan_quantum_and_language_promotion(self):
        text = " ".join(self.document["non_claims"])
        for phrase in (
            "No NaN-encoding advantage",
            "No quantum effect",
            "No general language-model",
            "external to the native root",
            "not matched to neural AdamW",
        ):
            self.assertIn(phrase, text)
        self.assertFalse(self.document["native_integration"]["production_authority"])


if __name__ == "__main__":
    unittest.main()
