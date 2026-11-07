from __future__ import annotations

from types import SimpleNamespace
import unittest
from pathlib import Path

from runner_riddle.mth_registry import MthRegistry
from runner_riddle.nmp_plan import NmpPlan, NmpPlanError


REPO = Path(__file__).resolve().parents[1]
PLAN_SPEC = {
    "schema": "nanrouter.mth-plan-spec.v1",
    "plan_id": "nmp-plan.test",
    "steps": [{
        "name": "dot",
        "kernel_id": "mth.vector.dot256.f32",
        "inputs": ["f32[256].a", "f32[256].b"],
        "outputs": ["f32.score"],
        "depends_on": [],
    }],
}


class NmpPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = MthRegistry.load(REPO / "spec" / "wave-capabilities.json")
        cls.plan = cls.registry.compose(PLAN_SPEC)

    def make(self, **overrides):
        values = {
            "plan": self.plan,
            "candidate_id": "cnd:" + "a" * 64,
            "snapshot_id": "snp:" + "b" * 64,
            "admission_id": "adm:" + "c" * 64,
            "preflight_digest": "pf:" + "d" * 64,
            "ruleset_snapshot_id": "rsn:" + "e" * 64,
            "capability_set_digest": "mth.vector.dot256.f32",
            "numerical_policy": {"precision": "float32"},
            "peak_workspace_words": 512,
        }
        values.update(overrides)
        return NmpPlan(**values)

    def test_wrapper_binds_context_without_changing_the_v1_plan(self):
        wrapper = self.make()
        document = wrapper.to_dict()
        self.assertEqual(document["schema"], "nanrouter.nmp-plan.v2")
        self.assertEqual(document["plan"], self.plan.to_dict())
        self.assertEqual(document["plan_digest"], wrapper.plan_digest)
        self.assertEqual(len(wrapper.plan_digest), 64)
        self.assertEqual(len(wrapper.digest()), 64)

    def test_plan_digest_tampering_is_rejected(self):
        with self.assertRaises(NmpPlanError):
            self.make(plan_digest="f" * 64)

    def test_required_context_is_validated(self):
        with self.assertRaises(NmpPlanError):
            self.make(candidate_id="")
        with self.assertRaises(NmpPlanError):
            self.make(admission_id="not-an-admission")
        with self.assertRaises(NmpPlanError):
            self.make(preflight_digest="not-a-preflight")
        with self.assertRaises(NmpPlanError):
            self.make(peak_workspace_words=-1)

    def test_from_compiled_uses_admission_scope(self):
        candidate = SimpleNamespace(candidate_id="cnd:" + "1" * 64)
        admission = SimpleNamespace(
            admission_id="adm:" + "2" * 64,
            snapshot_id="snp:" + "3" * 64,
            preflight_digest="pf:" + "4" * 64,
            rule_snapshot_id="rsn:" + "5" * 64,
            scope={"capability": {"selected": {
                "kernel_id": "mth.vector.dot256.f32",
            }}},
        )
        compiled = SimpleNamespace(
            plan=self.plan, candidate=candidate, admission=admission,
            workspace_words=512,
        )
        wrapper = NmpPlan.from_compiled(compiled)
        self.assertEqual(wrapper.candidate_id, candidate.candidate_id)
        self.assertEqual(wrapper.snapshot_id, admission.snapshot_id)
        self.assertEqual(
            wrapper.capability_set_digest, "mth.vector.dot256.f32"
        )
        self.assertEqual(wrapper.peak_workspace_words, 512)

    def test_digest_is_stable_and_plan_is_independently_serializable(self):
        first = self.make()
        second = self.make()
        self.assertEqual(first.digest(), second.digest())
        self.assertEqual(first.plan.to_dict(), self.plan.to_dict())


if __name__ == "__main__":
    unittest.main()
