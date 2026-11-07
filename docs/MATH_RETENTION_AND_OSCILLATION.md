# Math retention, oscillation, and pruning (P10)

Status: implemented in `runner_riddle/math_retention.py`; tests in
`tests/test_math_retention.py` (10 tests).

This is a **structural control plane**. It scores declared integer features,
plans tier changes, and prunes mappings through the existing `MathStore` CAS
ledger. It never evaluates mathematical truth, proof, or content.

## Retention score

`RetentionFeatures` accepts only non-negative integers:

```text
utility, relation_importance, derivation_value, predictive_usefulness,
recompute_savings, storage_cost, dependency_count, reuse_count
```

The score is a weighted sum with `storage_cost` subtracted. Negative utility is
not a signal to prune; it is invalid input. A low-value object is represented by
`utility=0` and a high declared storage cost.

## Tiers

`scratch < archived < active < persistent`

- `scratch` is non-authoritative and bounded.
- `archived` is recoverable; canonical content is retained.
- `active` is the hot working set.
- `persistent` is canonical and never evicted.

No tier permits payload deletion. Pruning changes lifecycle/tier state and the
mapping ledger, not the canonical mathematical content.

## Prune protocol

1. `PrunePlanner.build(store)` produces a deterministic `PrunePlan` with
   mapping version/generation/target-digest expectations.
2. `shadow_evaluate(store, plan)` or `MathRetention.shadow(plan)` checks the
   plan without mutation. Truth/proof/refutation objects are marked
   `protected` and retained even when their score would otherwise prune them.
3. `MathRetention.apply(plan)` writes append-only retention records and updates
   the mapping pointer only on CAS success.
4. `MathRetention.rollback(plan)` / `restore(mapping_id)` returns the mapping to
   its recorded restore tier using the same CAS checks.

`apply_prune_plan`, `rollback_prune_plan`, and `restore_mapping` are functional
entry points for callers that do not need the manager facade.

## Oscillation budget

`OscillationBudget(max_depth, max_fanout, fuel, max_candidates, max_flips,
dwell_ticks, hysteresis)` bounds rewrite exploration. `OscillationState.advance`
returns a typed `OscillationOutcome`; duplicate states, repeated content,
depth/fan-out/fuel/candidate exhaustion, and rewrite cycles stop exploration
instead of looping. A `RewriteCycleDetector` quarantines repeated forms after
the configured flips/dwell.

Oscillation and pruning are host control outcomes only. They never set
mathematical validity, truth, or proof status.

## Tests

Tests cover typed features/scoring, tier policy, deterministic plans, proof
preservation, shadow/apply/restore, rollback, stale generations, duplicate and
fuel stops, rewrite-cycle quarantine, and functional helpers.
