from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "spec" / "rounds-038-039-free-generation.v1.json"


class Rounds038039EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads(SPEC.read_text(encoding="utf-8"))

    def test_schema_archive_and_round_038_source_provenance(self):
        self.assertEqual(
            self.document["schema"],
            "nanrouter.rounds-038-039-free-generation.v1",
        )
        self.assertEqual(len(self.document["source_archive"]["sha256"]), 64)
        self.assertTrue(self.document["source_archive"]["contains_round_038_sources"])
        self.assertFalse(
            self.document["source_archive"]["round_038_standalone_archive_present"]
        )

    def test_round_038_is_recorded_as_superseded(self):
        round_038 = self.document["round_038"]
        self.assertEqual(round_038["held_out_tokens"], 3511)
        self.assertEqual(
            round_038["models"]["conventional_recurrent"]["perplexity"], 183.3
        )
        self.assertEqual(
            round_038["models"]["native_mirror_cycle"]["perplexity"], 186.8
        )
        self.assertEqual(
            round_038["native_without_learned_cycle_readout"]["perplexity"], 262.2
        )
        self.assertIn("superseded", round_038["caveat"])

    def test_round_039_reports_dense_control_win_and_memory_ablation(self):
        variants = self.document["round_039"]["variants"]
        self.assertLess(
            variants["plain_17"]["full_perplexity"],
            variants["native_17"]["full_perplexity"],
        )
        self.assertLess(
            variants["plain_29"]["full_perplexity"],
            variants["native_29"]["full_perplexity"],
        )
        for name in ("plain_17", "native_17", "plain_29", "native_29"):
            self.assertGreater(
                variants[name]["no_memory_perplexity"],
                variants[name]["full_perplexity"],
            )
        self.assertLess(
            variants["native_17"]["gauge_max_abs"], 1.13e-6
        )
        self.assertLess(
            variants["native_29"]["gauge_max_abs"], 1.10e-6
        )

    def test_optimizer_matching_caveat_is_explicit(self):
        architecture = self.document["architecture"]
        self.assertFalse(architecture["optimizers_strictly_matched"])
        self.assertEqual(architecture["adapter_coefficients"], 256)
        self.assertEqual(architecture["parameters"], 463984)

    def test_non_claims_block_fluency_and_geometry_promotion(self):
        text = " ".join(self.document["non_claims"])
        for phrase in (
            "did not beat the dense control",
            "not fluent",
            "not NaN16 production execution",
            "superseded windowing protocol",
            "No live deployment",
        ):
            self.assertIn(phrase, text)
        self.assertFalse(self.document["native_integration"]["production_authority"])


if __name__ == "__main__":
    unittest.main()
