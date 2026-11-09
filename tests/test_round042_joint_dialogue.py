from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "spec" / "round042-joint-dialogue.v1.json"


class Round042EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads(SPEC.read_text(encoding="utf-8"))

    def test_release_archive_and_scope(self):
        self.assertEqual(len(self.document["source_archive"]["release_sha256"]), 64)
        self.assertEqual(self.document["source_archive"]["release_files"], 61)
        setup = self.document["setup"]
        self.assertEqual(setup["seeds"], [17, 29, 43])
        self.assertEqual(setup["steps"], 650)
        self.assertTrue(setup["entity_boundaries_supplied"])
        self.assertTrue(setup["wordnet_child_split"])

    def test_joint_results_and_five_hop_boundary(self):
        results = self.document["results"]
        self.assertEqual(results["two_to_four_hop"]["correct"], 540)
        self.assertEqual(results["after_gauge"]["correct"], 540)
        self.assertEqual(results["five_hop"]["correct"], 525)
        self.assertEqual(results["matched_conventional_signed_adjacency"]["correct"], 540)
        self.assertEqual(results["independently_retrained_conventional"]["correct"], 540)

    def test_causal_and_four_state_results_are_recorded(self):
        results = self.document["results"]
        self.assertEqual(results["causal_deletion_abstentions"]["correct"], 240)
        self.assertEqual(results["causal_restoration"]["correct"], 240)
        self.assertEqual(results["four_state_responses"]["correct"], 480)
        self.assertEqual(results["four_state_after_gauge"]["correct"], 480)
        self.assertEqual(results["four_state_speaker_parameters"], 56628)

    def test_language_only_failure_is_not_hidden(self):
        language_only = self.document["results"]["language_only"]
        self.assertEqual(language_only["correct"], 90)
        self.assertEqual(language_only["positive"], 0)
        self.assertEqual(language_only["negative"], 90)
        self.assertIn("abstain", language_only["failure_mode"])

    def test_non_claims_block_fluency_and_clean_input_advantage(self):
        text = " ".join(self.document["non_claims"])
        for phrase in (
            "Not fluent open-domain language",
            "Entity boundaries and constrained relation forms are supplied",
            "no unique NaN geometric advantage",
            "Language-token loss alone collapsed",
            "No live deployment",
        ):
            self.assertIn(phrase, text)
        self.assertFalse(self.document["native_integration"]["production_authority"])


if __name__ == "__main__":
    unittest.main()
