# Durable universe page records

Status: implemented in `runner_riddle/math_store.py`; tests in
`tests/test_math_store_pages.py` (12 tests). Schema contract in
`spec/math-store.schema.json`.

The math store now owns a durable MC0DB page-record table for the fixed
256-page universe described in `DEEP_PLAN_CONT.md` §4.5. This is additive to
the existing `math_schema=1` contract. `wave_schema` stays 1 and is never
rewritten or reinterpreted.

## Identity, not an address

| Position | Role |
|---|---|
| `page_id` 0..254 | One head page each |
| `page_id` 255 | The single NANNET0 node page |
| `page:000`..`page:255` | Canonical page keys |

Page 255 is a page address, not lane 255, head 255, or a seventh runner slot.
`get_page(255)` returns `kind="nannet0"`, `lane_id=None`, and `head=None`;
pages 0..254 return `kind="head"` with the matching lane/head projection.
Page ids outside 0..255 are rejected with `MathPageBoundsError`.

## Tables

### `math_page` (MC0DB, current head)

| Field | Meaning |
|---|---|
| `page_id` | Primary key, constrained to 0..255 |
| `owner` | Runner/worker currently holding the pin |
| `generation` | Monotonic CAS generation, starts at 1 |
| `state` | `pinned`, `sealed`, `evicted`, `released`, or `quarantined` |
| `kind` | `head` for 0..254; `nannet0` for 255 (table CHECK enforces the pairing) |
| `leaf_id`, `leaf_version`, `leaf_digest` | Immutable canonical leaf binding |
| `storage_tier` | Where the page content lives (default `MC0DB`) |
| `pin_count` | Non-negative pin count |
| `operator_id`, `operator_version`, `operator_digest` | Optional operator binding used by cache invalidation |
| `page_digest` | SHA-256 of the canonical immutable page snapshot |
| `created_tick`, `updated_tick` | Page creation and last mutation ticks |

### `math_page_version` (MC0DB, immutable history)

Primary key `(page_id, generation)`. Every accepted pin, release, or state
change writes exactly one version row in the same `BEGIN IMMEDIATE`
transaction as the current head update. It carries the same binding fields plus
`page_json` (canonical snapshot) and `page_digest`. `UPDATE` and `DELETE` are
rejected by triggers.

## API

```python
store.pin_page(page_id, owner, leaf_ref, digest=None, generation=None,
               tick=0, ...) -> dict
store.release_page(page_id, expected_generation=None, *, tick=0) -> dict
store.get_page(page_id, *, generation=None) -> dict
store.list_pages(*, owner=None, state=None, leaf_id=None, limit=1024) -> list
store.update_page_state(page_id, state, expected_generation=None, *,
                        tick=0) -> dict
store.page_map(*, include_digest=True) -> dict
store.page_map_digest() -> str
store.page_key(page_id) -> str
store.page_kind(page_id) -> str
```

`leaf_ref` may be a `MathLeaf`, a mapping with `leaf_id` and optional
`version`/`leaf_version`, an `id@vN`/`id` reference, or `None` with explicit
`leaf_id`/`leaf_version` keywords. The binding is always resolved against the
stored immutable leaf version; callers cannot declare a digest the store has
not already accepted.

`pin_page` semantics:

- a new page starts at generation 1 and pin count 1;
- `generation`/`expected_generation` is the expected current generation
  (0 or 1 accepted only for a new page; `None` accepts the current head);
- pinning the same leaf binding again increments `pin_count` and `generation`;
- a different leaf id, version, or digest is rejected with
  `MathPageConflictError`; a page is never rebound;
- a stale generation is rejected with `StaleGenerationError`, leaving both the
  head and history unchanged;
- all head/version writes for one accepted mutation are atomic in MC0DB.

`release_page` performs the generation CAS first, then decrements
`pin_count`. Releasing at zero raises `MathPageUnderflowError` without changing
the head or appending a version. Releasing the last pin moves a non-quarantined
page to `released`.

`update_page_state` CASes the state without changing the leaf binding. It
rejects `released` with a live pin count and `pinned` with zero pins, and it is
a no-op when the requested state already matches the current generation.

## Page-map digest

`page_map()` returns all 256 slots in ascending page order (`None` for empty
slots) with `schema="nanrouter.math-page-map.v1"`, `page_count=256`,
`head_page_count=255`, `nannet0_page=255`, and `page_bytes=32768`. The digest
is SHA-256 over the canonical JSON document with its top-level `digest` field
removed.

The digest covers page content identity only:

- `page_id`, `kind`;
- `leaf_id`, `leaf_version`, `leaf_digest`;
- `operator_id`, `operator_version`, `operator_digest`.

It deliberately ignores `owner`, `pin_count`, `state`, `page_digest`,
timestamps, and insertion order. Pin/release/state churn therefore does not
invalidate an operator descriptor carrying the same page-map digest; binding a
different leaf version or operator version does. This is the cache-invalidation
hook for A-39: an operator version change produces a different page-map digest.

## Invariants

- Page ids are exactly 0..255; booleans, strings, negatives, and 256+ are
  rejected.
- Page 255 is NANNET0, never a logical lane or head index.
- `math_page_version` is append-only and every generation is reconstructible.
- Leaf binding is immutable after first publication.
- Generations move only by compare-and-swap.
- Pin counts never underflow.
- A failed CAS, conflict, or SQL failure leaves no partial publication.
- A corrupt current page digest is a reference error, never zero/null.
- `wave_schema=1` and `math_schema=1` remain unchanged.

## Non-claims

- These are durable **records** for universe pages, not a provider-mounted
  8 MiB page file or an MC0DB signature exchange (E-07).
- The page map is not a second job/lease authority and does not schedule
  runners or lanes.
- Page-record events are appended to BS0DB after the MC0DB transaction, so the
  cross-database event is not a distributed transaction. Use the existing
  cross-store intent protocol where cross-store atomic evidence is required.
- The store does not execute pages, allocate guest memory, or prove that a
  leaf's content is numerically correct.
