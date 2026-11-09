from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "spec" / "rounds-034-036.v1.json"


class Rounds034To036Tests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads(SPEC.read_text(encoding="utf-8"))

    def test_archives_and_schema(self):
        self.assertEqual(self.document["schema"], "nanrouter.rounds-034-036.v1")
        self.assertEqual(
            self.document["evidence_class"], "external-cpp-pytorch-experiments"
        )
        self.assertEqual(len(self.document["archives"]), 3)
        for archive in self.document["archives"]:
            self.assertEqual(len(archive["sha256"]), 64)

    def test_round034_router_and_native_controls(self):
        r34 = self.document["round_034"]
        self.assertAlmostEqual(
            r34["learned_router"]["accept_accuracy_mean"], 0.99
        )
        self.assertAlmostEqual(
            r34["learned_router"]["false_answer_rate_mean"], 0.0044444444444444444
        )
        self.assertEqual(r34["native_audit"]["native_exact"], 89)
        self.assertEqual(r34["native_audit"]["conventional_index_exact"], 89)
        self.assertEqual(r34["native_audit"]["raw_single_edge_exact"], 0)
        self.assertIn("not synthesis", r34["hybrid_bits_per_byte"]["note"])

    def test_round035_composition_and_caveat(self):
        r35 = self.document["round_035"]
        self.assertEqual(r35["two_hop_gate"]["test_accuracy"], 1.0)
        self.assertEqual(r35["native_three_hop"]["cycle_exact_answers"], 120)
        self.assertEqual(r35["native_three_hop"]["raw_edge_exact_answers"], 60)
        self.assertIn(
            "not evidence of autonomous language understanding",
            r35["two_hop_gate"]["caveat"],
        )
        self.assertEqual(
            r35["second_source_removed"]["correct"], 450
        )

    def test_round036_generation_limits(self):
        r36 = self.document["round_036"]
        self.assertEqual(r36["data"]["synsets"], 81499)
        self.assertEqual(r36["data"]["parameter_count"], 38268)
        self.assertEqual(r36["original_model"]["seed_17_semantic_accuracy"], 0.5)
        self.assertEqual(r36["original_model"]["seed_29_semantic_accuracy"], 1.0)
        self.assertEqual(r36["native_audit"]["native_exact_after_gauge"], 90)
        self.assertEqual(r36["stress"]["contradiction_abstentions"], 0)
        self.assertEqual(r36["stress"]["four_hop_correct"], 0)
        self.assertEqual(r36["robust_training"]["connected_correct"], 1499)

    def test_non_claims_block_language_or_geometry_promotion(self):
        text = " ".join(self.document["non_claims"])
        for phrase in (
            "No fluent open-domain language model",
            "No unique NaN-specific advantage",
            "not synthesis",
            "not NaN16 production execution",
            "No canonical merge",
        ):
            self.assertIn(phrase, text)
        self.assertFalse(self.document["integration"]["production_authority"])


if __name__ == "__main__":
    unittest.main()
