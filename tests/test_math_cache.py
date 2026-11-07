from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runner_riddle.math_cache import MathCache, MathCacheError
from runner_riddle.math_objects import MathLeaf
from runner_riddle.math_store import MathReferenceError, MathStore


def leaf(identifier: str, version: int = 1) -> MathLeaf:
    return MathLeaf(
        leaf_id=identifier,
        version=version,
        kind="scalar",
        type={"kind": "scalar"},
        content={"value": identifier},
        provenance={"producer": "cache-test"},
    )


class MathCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = MathStore(root / "bs0.sqlite3", root / "mc0.sqlite3")
        self.a = self.store.put_leaf(leaf("nml:cache:a"))
        self.b = self.store.put_leaf(leaf("nml:cache:b"))
        self.cache = MathCache(self.store, max_entries=1)

    def test_eviction_removes_only_cache_entry_and_reloads_canonical(self):
        self.assertEqual(self.cache.get("nml:cache:a").leaf_id, "nml:cache:a")
        self.assertEqual(self.cache.get("nml:cache:b").leaf_id, "nml:cache:b")
        self.assertEqual(self.cache.stats()["entries"], 1)
        self.assertIsNotNone(self.store.get_leaf("nml:cache:a"))
        reloaded = self.cache.get("nml:cache:a")
        self.assertEqual(reloaded.content, self.a.content)
        self.assertEqual(self.cache.stats()["status"], "green")

    def test_missing_or_corrupt_payload_is_a_reference_error_not_zero(self):
        with self.assertRaises(MathReferenceError):
            self.cache.get("nml:cache:missing")
        self.assertEqual(self.cache.stats()["status"], "green")

    def test_put_and_invalidate_do_not_write_canonical_store(self):
        extra = leaf("nml:cache:extra")
        self.cache.put(extra)
        with self.assertRaises(MathReferenceError):
            self.store.get_leaf("nml:cache:extra")
        self.assertTrue(self.cache.invalidate("nml:cache:extra"))
        self.assertFalse(self.cache.invalidate("nml:cache:extra"))

    def test_clear_and_evict_are_bounded(self):
        self.cache.put(self.a)
        self.cache.put(self.b)
        self.assertEqual(self.cache.clear(), 1)
        self.assertEqual(self.cache.stats()["entries"], 0)
        self.assertEqual(self.cache.evict(0), 0)
        with self.assertRaises(MathCacheError):
            MathCache(self.store, max_entries=0)

    def test_versions_are_distinct_cache_keys(self):
        cache = MathCache(self.store, max_entries=2)
        second = leaf("nml:cache:a", version=2)
        cache.put(second)
        first = cache.get("nml:cache:a", version=1)
        newer = cache.get("nml:cache:a", version=2)
        self.assertEqual(first.version, 1)
        self.assertEqual(newer.version, 2)


if __name__ == "__main__":
    unittest.main()
