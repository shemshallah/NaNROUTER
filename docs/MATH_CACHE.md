# Disposable math cache

Status: implemented in `runner_riddle/math_cache.py`; tests in
`tests/test_math_cache.py` (5 tests).

The cache is a disposable LRU index over `MathStore` leaf versions. It owns no
canonical content.

## Invariants

- Eviction/clear removes only local entries; canonical payload/version rows
  remain in the store.
- A cache miss reloads from `MathStore`; missing or corrupt payloads surface as
  `MathReferenceError`/`MathPayloadError`, never zero, null, or empty.
- Leaf identity is `(leaf_id, version)`, so versions are distinct cache keys.
- `put()` caches an already-canonical leaf but never writes the store.
- The cache is bounded and token-free.
- Cache health is a local status projection, not evidence of mathematical
  validity or truth.

## API

- `MathCache(store, max_entries=128)`
- `get(leaf_id, version=None)`
- `put(leaf)`
- `invalidate(leaf_id, version=None)`
- `evict(count)` / `clear()`
- `stats()`
