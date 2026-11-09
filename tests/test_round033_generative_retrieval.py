from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "spec" / "round033-generative-retrieval.v1.json"


class Round033EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads(SPEC.read_text(encoding="utf-8"))

    def test_schema_and_source(self):
        self.assertEqual(
            self.document["schema"],
            "nanrouter.round033-generative-retrieval.v1",
        )
        self.assertEqual(
            self.document["evidence_class"], "external-cpp-pytorch-experiment"
        )
        self.assertEqual(len(self.document["source_archive"]["sha256"]), 64)

    def test_episodic_copy_is_exact_retrieval(self):
        episodic = self.document["episodic_copy"]
        self.assertEqual(episodic["total_correct"], 886)
        self.assertEqual(episodic["total_episodes"], 900)
        self.assertAlmostEqual(episodic["exact_copy_fraction"], 886 / 900)
        self.assertIn("retrieval-and-copy", episodic["interpretation"])

    def test_native_gauge_result_is_honest(self):
        native = self.document["native_root_episodic"]
        self.assertEqual(native["native_exact_clean"], 118)
        self.assertEqual(native["native_exact_after_gauge"], 118)
        self.assertEqual(native["conventional_copy_exact"], 118)
        self.assertAlmostEqual(
            native["raw_byte_accuracy_after_gauge"], 94 / 2880
        )
        self.assertIn("identical selection accuracy", native["interpretation"])

    def test_free_form_generation_is_tied_and_incoherent(self):
        lm = self.document["free_form_lm"]
        self.assertAlmostEqual(
            lm["mean_plain_bpb"], 3.6747549712879797
        )
        self.assertAlmostEqual(
            lm["mean_cycle_bpb"], 3.674789597477828
        )
        self.assertLess(
            abs(lm["mean_plain_bpb"] - lm["mean_cycle_bpb"]), 0.001
        )
        self.assertFalse(lm["samples_coherent"])

    def test_non_claims_block_unwarranted_promotion(self):
        text = " ".join(self.document["non_claims"])
        for phrase in (
            "not a fluent language model",
            "does not synthesize unseen prose",
            "identical 118/120",
            "No canonical merge",
        ):
            self.assertIn(phrase, text)
        self.assertFalse(self.document["integration"]["production_authority"])


if __name__ == "__main__":
    unittest.main()
