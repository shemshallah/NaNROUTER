# Cross-store math commit protocol

Status: implemented in `runner_riddle/math_store.py`; tests in
`tests/test_math_store_cross.py` (12 tests).

BS0DB and MC0DB are separate SQLite stores. The math layer does **not** claim a
distributed transaction. It provides a crash-consistent intent/finalize
protocol with idempotent replay:

1. `begin_commit_intent(...)` writes an MC0DB intent bound to the mapping,
   target version/digest, evidence digest, and expected base version,
   generation, and mapping digest.
2. `append_commit_evidence(...)` appends canonical evidence to BS0DB
   idempotently. Same content replays; different content conflicts.
3. `verify_commit_evidence(...)` cross-checks BS0DB evidence against the MC0DB
   intent.
4. `finalize_commit_intent(...)` verifies the target immutable version,
   evidence, and base CAS in one MC0DB `BEGIN IMMEDIATE` transaction, updates
   the mapping, and marks the intent finalized together.
5. `recover_pending_intents(...)` finalizes pending intents with matching
   evidence; missing, mismatched, or stale intents fail without touching the
   active mapping.

Evidence remains append-only even when an intent fails. A failed finalize
leaves the old mapping active and does not create a partial active mapping.
Replay is a no-op.

## Non-claims

- This is not a distributed transaction across two databases.
- Finalization CASes an already-written immutable version; new versions still
  go through the normal immutable version path first.
- `wave_schema` remains 1; the math tables and `math_schema` are additive.
