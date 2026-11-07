from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runner_riddle.math_objects import MathLeaf
from runner_riddle.math_retention import (
    MathRetention,
    OscillationBudget,
    OscillationState,
    PrunePlanner,
    RetentionConflictError,
    RetentionFeatures,
    RetentionLedger,
    RetentionScorer,
    RetentionTier,
    RewriteCycleDetector,
    STOP_DUPLICATE_STATE,
    STOP_FUEL_EXHAUSTED,
    STOP_REWRITE_CYCLE,
    apply_prune_plan,
    features_for_object,
    is_protected,
    plan_pruning,
    protection_reasons,
    restore_mapping,
    retention_score,
    shadow_evaluate,
    tier_policy,
)
from runner_riddle.math_store import MathStore


def make_leaf(leaf_id: str, *, metadata=None):
    return MathLeaf(
        leaf_id=leaf_id,
        kind="vector",
        type={"element": "float32", "shape": [4], "domain": "real"},
        content={"digest": (leaf_id[-1] if leaf_id else "a") * 64, "word_count": 4},
        metadata=dict(metadata or {}),
    )


class RetentionTests(unittest.TestCase):
    def make_store(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        return MathStore(root / "bs0.sqlite3", root / "mc0.sqlite3")

    def test_features_are_typed_non_negative_and_scored_not_learned(self):
        features = RetentionFeatures(utility=10, storage_cost=3, reuse_count=2)
        score = retention_score(features)
        self.assertEqual(score, 37)
        self.assertEqual(RetentionScorer().score(features).score, score)
        with self.assertRaises(Exception):
            RetentionFeatures(utility=-1)
        with self.assertRaises(Exception):
            RetentionFeatures(storage_cost=-1)
        with self.assertRaises(Exception):
            RetentionFeatures.from_value({"utility": True})

    def test_tiers_are_distinct_and_never_claim_payload_deletion(self):
        active = tier_policy("active")
        archived = tier_policy(RetentionTier.ARCHIVED)
        persistent = tier_policy("persistent")
        self.assertGreater(active.rank, archived.rank)
        self.assertFalse(archived.permits_payload_delete)
        self.assertFalse(persistent.permits_payload_delete)
        self.assertTrue(persistent.canonical)

    def test_planner_is_deterministic_and_selects_tombstone_for_low_score(self):
        store = self.make_store()
        leaf = store.put_leaf(make_leaf(
            "nml:U0:vector:1",
            metadata={"retention": {"utility": 0, "storage_cost": 100}},
        ))
        first = PrunePlanner().build(store)
        second = PrunePlanner().build(store)
        self.assertEqual(first.digest(), second.digest())
        self.assertEqual(len(first.actions), 1)
        action = first.actions[0]
        self.assertEqual(action.action, "tombstone")
        self.assertEqual(action.object_id, leaf.leaf_id)
        self.assertEqual(action.target_digest, leaf.digest())
        self.assertFalse(action.protected)

    def test_truth_and_proof_objects_are_preserved(self):
        store = self.make_store()
        proof = store.put_leaf(make_leaf(
            "nml:U0:proof:1",
            metadata={
                "truth_status": "proved",
                "retention": {"utility": 0, "storage_cost": 100},
            },
        ))
        self.assertTrue(is_protected(proof))
        self.assertIn("truth:proved", protection_reasons(proof))
        plan = PrunePlanner().build(store)
        action = plan.actions[0]
        self.assertTrue(action.protected)
        self.assertEqual(action.action, "retain")
        self.assertEqual(len(plan.preserved), 1)

    def test_shadow_apply_and_restore_round_trip(self):
        store = self.make_store()
        leaf = store.put_leaf(make_leaf(
            "nml:U0:vector:2",
            metadata={"retention": {"utility": 0, "storage_cost": 100}},
        ))
        manager = MathRetention(store)
        plan = manager.plan()
        shadow = manager.shadow(plan)
        self.assertTrue(shadow.approved)
        result = manager.apply(plan, tick=1)
        self.assertEqual(result.applied[0].state, "tombstoned")
        self.assertEqual(manager.record("leaf:" + leaf.leaf_id).state, "tombstoned")
        restored = manager.restore(
            "leaf:" + leaf.leaf_id,
            expected_generation=result.applied[0].retention_generation,
            tick=2,
        )
        self.assertEqual(restored.state, "active")
        self.assertEqual(restored.tier, RetentionTier.ACTIVE)

    def test_rollback_prune_plan_restores_ledger_state(self):
        store = self.make_store()
        leaf = store.put_leaf(make_leaf(
            "nml:U0:vector:3",
            metadata={"retention": {"utility": 0, "storage_cost": 100}},
        ))
        manager = MathRetention(store)
        plan = manager.plan()
        manager.apply(plan, tick=1)
        rolled = manager.rollback(plan, tick=2)
        self.assertTrue(rolled.rolled_back)
        self.assertEqual(manager.record("leaf:" + leaf.leaf_id).state, "active")

    def test_stale_generation_and_missing_protection_checks(self):
        store = self.make_store()
        leaf = store.put_leaf(make_leaf(
            "nml:U0:vector:4",
            metadata={"retention": {"utility": 0, "storage_cost": 100}},
        ))
        ledger = RetentionLedger.from_store(store)
        row = store.get_mapping("leaf:" + leaf.leaf_id)
        with self.assertRaises(Exception):
            ledger.archive(
                store, "leaf:" + leaf.leaf_id,
                expected_version=row["current_version"],
                expected_generation=row["generation"] + 1,
            )
        with self.assertRaises(Exception):
            restore_mapping(store, "leaf:" + leaf.leaf_id, expected_generation=99)

    def test_oscillation_stops_on_duplicates_and_fuel(self):
        state = OscillationState(OscillationBudget(
            max_depth=4, max_fanout=4, fuel=2, max_candidates=4,
        ))
        first = state.advance(state_key="s1", content_digest="a", tick=0)
        self.assertTrue(first.allowed)
        duplicate = state.advance(state_key="s1", tick=1)
        self.assertFalse(duplicate.allowed)
        self.assertEqual(duplicate.stop_reason, STOP_DUPLICATE_STATE)
        self.assertTrue(duplicate.duplicate)
        fresh = OscillationState(OscillationBudget(
            max_depth=4, max_fanout=4, fuel=1, max_candidates=4,
        ))
        self.assertTrue(fresh.advance(state_key="a", fuel=1).allowed)
        denied = fresh.advance(state_key="b", fuel=1)
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.stop_reason, STOP_FUEL_EXHAUSTED)

    def test_rewrite_cycle_quarantines_repeated_forms(self):
        detector = RewriteCycleDetector(max_flips=1, dwell_ticks=1)
        self.assertFalse(detector.observe("a", 0).detected)
        self.assertFalse(detector.observe("b", 1).detected)
        verdict = detector.observe("a", 2)
        self.assertTrue(verdict.detected)
        self.assertTrue(verdict.quarantined)
        self.assertEqual(verdict.reason, "rewrite_cycle_quarantine")
        state = OscillationState(
            OscillationBudget(max_flips=1, dwell_ticks=1),
            rewrite_cycle_hook=detector,
        )
        denied = state.advance(state_key="c", rewrite_key="b", tick=3)
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.stop_reason, STOP_REWRITE_CYCLE)
        self.assertTrue(denied.quarantined)

    def test_plan_helpers_do_not_require_a_runtime(self):
        store = self.make_store()
        store.put_leaf(make_leaf(
            "nml:U0:vector:5",
            metadata={"retention": {"utility": 0, "storage_cost": 100}},
        ))
        plan = plan_pruning(store)
        self.assertTrue(shadow_evaluate(store, plan).approved)
        result = apply_prune_plan(store, plan, require_shadow=True)
        self.assertFalse(result.rolled_back)
        self.assertEqual(len(result.applied), 1)


if __name__ == "__main__":
    unittest.main()
