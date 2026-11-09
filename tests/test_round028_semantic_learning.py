from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "spec" / "round028-semantic-learning.v1.json"


class Round028EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads(SPEC.read_text(encoding="utf-8"))

    def test_schema_and_source_archive(self):
        self.assertEqual(
            self.document["schema"],
            "nanrouter.round028-semantic-learning.v1",
        )
        self.assertEqual(
            self.document["evidence_class"], "external-neural-experiment"
        )
        self.assertEqual(len(self.document["source_archive"]["sha256"]), 64)

    def test_measured_means_match_the_archive(self):
        models = self.document["models"]
        self.assertAlmostEqual(models["lexical"]["roc_auc_mean"], 0.8191033333333333)
        self.assertAlmostEqual(
            models["wide_lexical_matched"]["roc_auc_mean"], 0.8274333333333334
        )
        self.assertAlmostEqual(
            models["shared_composition"]["roc_auc_mean"], 0.82775
        )
        self.assertAlmostEqual(
            models["native_composition"]["roc_auc_mean"], 0.8277266666666666
        )
        self.assertLess(
            models["shared_composition"]["binary_cross_entropy_mean"],
            models["wide_lexical_matched"]["binary_cross_entropy_mean"],
        )

    def test_native_memory_does_not_claim_held_out_transfer(self):
        native = self.document["models"]["native_composition"]
        self.assertEqual(native["native_hyperedge_strength_mean_abs_held_out"], 0.0)
        self.assertIn("not observed", native["native_strength_contribution"])
        self.assertAlmostEqual(
            native["native_hyperedge_strength_mean_abs_train"], 0.007003
        )

    def test_caveats_keep_the_result_honest(self):
        text = " ".join(self.document["measured_non_claims"])
        for required in (
            "transductive",
            "not autonomous language generation",
            "held-out strengths remain exactly zero",
            "Hash collisions",
            "not crash-safe",
            "not a fact",
        ):
            self.assertIn(required, text)
        self.assertFalse(self.document["integration"]["production_authority"])

    def test_no_production_module_imports_the_experiment(self):
        # The experiment is recorded as evidence only. Production modules must
        # not import torch/numpy/sklearn because of this spec.
        for path in (REPO / "runner_riddle").glob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            self.assertNotIn("round028", text.lower(), path.name)


if __name__ == "__main__":
    unittest.main()
