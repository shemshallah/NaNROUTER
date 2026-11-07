"""Disposable math payload cache with canonical-store recovery.

The cache owns no canonical data. Eviction removes only the local index entry;
the immutable payload remains in ``MathStore`` and is reloaded on the next
read. A missing or corrupt canonical payload raises a reference error; it is
never converted to zero, null, or an empty object.
"""
from __future__ import annotations

from collections import OrderedDict
import threading
from typing import Any

from .math_objects import MathLeaf
from .math_store import MathStore, MathStoreError

SCHEMA = "nanrouter.math-cache.v1"
CACHE_HEALTH_SCHEMA = "nanrouter.math-cache-health.v1"


class MathCacheError(ValueError):
    """Base error for disposable cache configuration/use."""


class MathCache:
    """Bounded LRU cache over canonical ``MathStore`` leaf versions."""

    def __init__(self, store: MathStore, *, max_entries: int = 128) -> None:
        if not isinstance(store, MathStore):
            raise MathCacheError("store must be a MathStore")
        if isinstance(max_entries, bool) or not isinstance(max_entries, int) \
                or max_entries < 1:
            raise MathCacheError("max_entries must be an integer >= 1")
        self.store = store
        self.max_entries = max_entries
        self._entries: OrderedDict[tuple[str, int | None], MathLeaf] = OrderedDict()
        self._lock = threading.RLock()
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def get(self, leaf_id: str, version: int | None = None) -> MathLeaf:
        key = (leaf_id, version)
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None:
                self.hits += 1
                self._entries.move_to_end(key)
                return cached
            self.misses += 1
        try:
            leaf = self.store.get_leaf(leaf_id, version=version)
        except MathStoreError:
            raise
        with self._lock:
            existing = self._entries.get(key)
            if existing is not None:
                return existing
            self._entries[key] = leaf
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
                self.evictions += 1
            return leaf

    def put(self, leaf: MathLeaf) -> MathLeaf:
        """Cache a leaf already known to be canonical; never writes the store."""
        if not isinstance(leaf, MathLeaf):
            raise MathCacheError("put requires a MathLeaf")
        key = (leaf.leaf_id, leaf.version)
        with self._lock:
            self._entries[key] = leaf
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
                self.evictions += 1
        return leaf

    def invalidate(self, leaf_id: str, version: int | None = None) -> bool:
        with self._lock:
            if version is None:
                keys = [key for key in self._entries if key[0] == leaf_id]
                found = bool(keys)
                for key in keys:
                    self._entries.pop(key, None)
                return found
            return self._entries.pop((leaf_id, version), None) is not None

    def evict(self, count: int = 1) -> int:
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise MathCacheError("count must be an integer >= 0")
        with self._lock:
            removed = 0
            while self._entries and removed < count:
                self._entries.popitem(last=False)
                removed += 1
            self.evictions += removed
            return removed

    def clear(self) -> int:
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
            return count

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "schema": CACHE_HEALTH_SCHEMA,
                "status": "green",
                "max_entries": self.max_entries,
                "entries": len(self._entries),
                "hits": self.hits,
                "misses": self.misses,
                "evictions": self.evictions,
                "canonical_store": "MathStore",
            }


__all__ = [
    "CACHE_HEALTH_SCHEMA", "MathCache", "MathCacheError", "SCHEMA",
]
