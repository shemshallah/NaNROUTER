from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "spec" / "round043-associative-memory.v1.json"


class Round043MemoryTests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads(SPEC.read_text(encoding="utf-8"))

    def test_archive_and_cache_shape(self):
        self.assertEqual(len(self.document["source_archive"]["sha256"]), 64)
        cache = self.document["cache"]
        self.assertEqual(cache["rows"], 4096)
        self.assertEqual(cache["trained_rows"], 3968)
        self.assertEqual(cache["reserved_rows"], 128)
        self.assertEqual(cache["lanes"], 32)
        self.assertEqual(cache["context_length"], 3)

    def test_reported_mean_loss_reduction(self):
        results = self.document["results"]
        self.assertAlmostEqual(results["base_mean_nats_per_byte"], 1.744586)
        self.assertAlmostEqual(results["native_memory_mean_nats_per_byte"], 1.645717)
        self.assertAlmostEqual(results["relative_reduction_percent"], 5.67)
        self.assertTrue(results["flat_conventional_cache_matches_native"])
        self.assertEqual(results["target_bytes_per_seed"], 124996)

    def test_post_gauge_and_online_write(self):
        results = self.document["results"]
        self.assertAlmostEqual(results["gauge_error_max"], 1.2878910638391972e-05)
        self.assertEqual(
            results["post_gauge_delete_restore_error_max"],
            1.2878910638391972e-05,
        )
        self.assertEqual(results["online_unseen_context_probability_before"], 0.0)
        self.assertAlmostEqual(
            results["online_unseen_context_probability_after"], 0.953869
        )

    def test_negative_findings_are_retained(self):
        text = " ".join(self.document["negative_findings"])
        for phrase in (
            "flat cache ties native",
            "Deleting the 80 most frequent contexts",
            "largely incoherent",
            "not the learned multi-hop graph reasoner",
            "not end-to-end trained",
        ):
            self.assertIn(phrase, text)

    def test_non_claims_block_geometry_and_fluency(self):
        text = " ".join(self.document["non_claims"])
        for phrase in (
            "No proven NaN-bit",
            "flat cache matches",
            "not fluent",
            "not multi-hop reasoning",
            "No live deployment",
        ):
            self.assertIn(phrase, text)
        self.assertFalse(self.document["native_integration"]["production_authority"])


if __name__ == "__main__":
    unittest.main()
