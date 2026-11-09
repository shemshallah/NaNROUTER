from __future__ import annotations

import unittest

from runner_riddle.mirror_retrieval_index import (
    MirrorRetrievalError,
    MirrorRetrievalIndex,
    anchor,
)


class MirrorRetrievalIndexTests(unittest.TestCase):
    def test_anchor_is_deterministic_and_in_range(self):
        for concept in (0, 1, 2, 255, 1024, 0xFFFFFFFF):
            with self.subTest(concept=concept):
                a, b, pair = anchor(concept)
                self.assertEqual((a, b, pair), anchor(concept))
                self.assertLess(a, b)
                self.assertGreaterEqual(a, 1)
                self.assertLessEqual(b, 255)
                self.assertGreaterEqual(pair, 1)
                self.assertLessEqual(pair, 32640)

    def test_exact_and_posting_agree(self):
        index = MirrorRetrievalIndex()
        for source in range(1, 101):
            index.add_fact(source, 1, source + 1000, strength=0.5)
        self.assertEqual(len(index), 100)
        for source in range(1, 101):
            exact = index.exact(source, 1)
            posting = index.posting(source, 1)
            self.assertIsNotNone(exact)
            self.assertEqual(exact, posting)
            self.assertEqual(posting.destination, source + 1000)
        self.assertIsNone(index.exact(9999, 1))
        self.assertIsNone(index.posting(9999, 1))

    def test_two_hop_directed_relation(self):
        index = MirrorRetrievalIndex()
        index.add_fact(10, 1, 20)
        index.add_fact(20, 1, 30)
        index.add_fact(30, 2, 40)
        self.assertTrue(index.two_hop(10, 30, 1))
        self.assertFalse(index.two_hop(10, 40, 1))
        self.assertFalse(index.two_hop(20, 30, 2))
        self.assertFalse(index.two_hop(10, 40, 2))

    def test_collision_is_resolved_by_source_and_relation(self):
        index = MirrorRetrievalIndex()
        by_anchor = {}
        pair = None
        pair_sources = []
        for concept in range(1, 20000):
            a, b, candidate = anchor(concept)
            by_anchor.setdefault(candidate, []).append(concept)
            if len(by_anchor[candidate]) >= 2:
                pair = candidate
                pair_sources = by_anchor[candidate][:2]
                break
        self.assertIsNotNone(pair)
        first, second = pair_sources
        index.add_fact(first, 1, 100)
        index.add_fact(second, 2, 200)
        self.assertEqual(index.posting(first, 1).destination, 100)
        self.assertEqual(index.posting(second, 2).destination, 200)
        self.assertIsNone(index.posting(first, 2))

    def test_status_declares_no_dense_or_native_claim(self):
        index = MirrorRetrievalIndex()
        index.add_fact(1, 1, 2)
        status = index.status()
        self.assertEqual(status["schema"], "nanrouter.mirror-retrieval-index.v1")
        self.assertFalse(status["uses_dense_matrix"])
        self.assertFalse(status["executes_native"])
        self.assertFalse(status["trains_model"])
        self.assertFalse(status["canonical_merge"])
        self.assertEqual(status["source_archive_sha256"][:8], "19572e59")

    def test_bounds_and_digest(self):
        index = MirrorRetrievalIndex()
        with self.assertRaises(MirrorRetrievalError):
            index.add_fact(-1, 1, 2)
        with self.assertRaises(MirrorRetrievalError):
            index.add_fact(1, 1, 2, strength=2.0)
        with self.assertRaises(MirrorRetrievalError):
            index.get(0)
        index.add_fact(1, 1, 2)
        index.add_fact(2, 1, 3)
        self.assertEqual(index.digest(), index.digest())
        self.assertEqual(len(index.digest()), 64)


if __name__ == "__main__":
    unittest.main()
