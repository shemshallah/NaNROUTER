from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "spec" / "round037-prose-memory.v1.json"


class Round037EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads(SPEC.read_text(encoding="utf-8"))

    def test_schema_and_archive(self):
        self.assertEqual(
            self.document["schema"], "nanrouter.round037-prose-memory.v1"
        )
        self.assertEqual(
            self.document["evidence_class"], "external-cpp-pytorch-experiment"
        )
        self.assertEqual(len(self.document["source_archive"]["sha256"]), 64)

    def test_retention_and_new_knowledge_tie_conventional(self):
        queries = self.document["queries"]
        for stage in (
            "before_gauge",
            "after_gauge",
            "after_writer_adaptation",
            "after_root_restore",
            "old_after_new_memory_writes",
        ):
            self.assertEqual(queries[stage]["geometry_correct"], 400)
            self.assertEqual(queries[stage]["conventional_correct"], 400)
        self.assertEqual(queries["new_knowledge_positive"]["cycle_correct"], 80)
        self.assertAlmostEqual(
            queries["raw_edges_after_gauge_mean_fraction"], 0.6491666666666667
        )

    def test_generation_is_exact_copy_with_restricted_vocabulary(self):
        generation = self.document["generation"]
        self.assertEqual(generation["native_cycle_source_recovery"], 90)
        self.assertEqual(generation["raw_source_recovery"], 0)
        self.assertEqual(generation["native_semantic_correct"], 90)
        self.assertEqual(
            generation["conventional_index_semantic_correct"], 90
        )
        self.assertTrue(generation["restricted_entity_slot_vocabulary"])

    def test_native_geometry_audit(self):
        native = self.document["native"]
        self.assertEqual(native["root_bytes"], 8388608)
        self.assertEqual(native["cells_checked"], 600)
        self.assertAlmostEqual(
            native["max_absolute_error_after_gauge"], 1.811981201171875e-05
        )
        self.assertTrue(native["restoration_exact"])
        self.assertEqual(native["slot_count"], 32385)
        self.assertEqual(len(native["writer_classes"]), 4)

    def test_non_claims_prevent_agi_or_geometry_promotion(self):
        text = " ".join(self.document["non_claims"])
        for phrase in (
            "Not a full natural-language-trained generative model",
            "Entity boundaries and identities are supplied",
            "No accuracy advantage",
            "not NaN16 production execution",
            "No canonical merge",
        ):
            self.assertIn(phrase, text)
        self.assertFalse(self.document["integration"]["production_authority"])


if __name__ == "__main__":
    unittest.main()
