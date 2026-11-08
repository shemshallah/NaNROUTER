from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runner_riddle.mth_registry import (
    MthKernelDescriptor,
    MthPlan,
    MthPlanError,
    MthPlanStep,
    MthRegistry,
)
from runner_riddle.mth_system import (
    DEFAULT_GUEST_BUDGET_BYTES,
    POINT_ZERO_ADDRESS,
    MthSystem,
    MthSystemConfigError,
    MthSystemPlanError,
    MthSystemSlotError,
    MthSystemWorkspaceError,
)
from runner_riddle.wave_ring_scheduler import WaveRingScheduler
from runner_riddle.wave_service import WaveService
from runner_riddle.wave_store import StaleGenerationError, WaveStore

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "spec" / "wave-capabilities.json"

PLAN_SPEC = {
    "schema": "nanrouter.mth-plan-spec.v1",
    "plan_id": "cosine.match.v1",
    "steps": [
        {
            "name": "score",
            "kernel_id": "mth.vector.cosine256.f32",
            "inputs": ["f32[256].a", "f32[256].b"],
            "outputs": ["f32.score"],
            "depends_on": [],
        },
    ],
}


class MthSystemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = MthRegistry.load(MANIFEST)

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = WaveStore(root / "bs0db.sqlite3", root / "mc0db.sqlite3")
        self.submit_token = "submit-token-0000000000000000"
        self.worker_token = "worker-token-1111111111111111"
        self.admin_token = "admin-token-22222222222222222"
        self.service = WaveService(
            self.store,
            self.submit_token,
            self.worker_token,
            self.admin_token,
        )
        self.scheduler = WaveRingScheduler(cycle_ticks=10, now_tick=0)
        self.system = self.make_system()
        self.operator_digest = "a" * 64
        self.result_digest = "d" * 64
        self.signature = "c" * 64

    def make_system(self, **overrides) -> MthSystem:
        scheduler = overrides.pop("scheduler", self.scheduler)
        options = {
            "guest_budget_bytes": None,
            "workspace_word_bytes": 8,
            "enforce_active_slot": True,
        }
        options.update(overrides)
        return MthSystem(
            self.registry, self.store, self.service, scheduler, **options
        )

    def make_plan(self, system: MthSystem | None = None, **overrides) -> MthPlan:
        spec = dict(PLAN_SPEC)
        spec.update(overrides)
        return (system or self.system).plan(spec)

    def submit(
        self,
        plan: MthPlan,
        *,
        system: MthSystem | None = None,
        job_id: str = "job-1",
        generation: int = 7,
        tick: int = 10,
        payload=None,
        **kwargs,
    ):
        return (system or self.system).submit_plan(
            plan,
            self.submit_token,
            job_id,
            "universe-0",
            self.operator_digest,
            generation,
            {"step": 1} if payload is None else payload,
            tick,
            **kwargs,
        )

    # -- Planning -------------------------------------------------------------

    def test_plan_resolves_validated_mth_plan(self):
        plan = self.system.plan(PLAN_SPEC)
        self.assertIsInstance(plan, MthPlan)
        self.assertEqual(plan.plan_id, "cosine.match.v1")
        self.assertEqual(plan.kernel_ids, ("mth.vector.cosine256.f32",))
        self.assertEqual(plan.workspace_words, 4)
        self.assertTrue(plan.deterministic)
        self.assertEqual(plan.to_dict()["schema"], "nanrouter.mth-plan.v1")
        self.assertIs(self.registry.validate_plan(plan), plan)

        with self.assertRaises(MthPlanError):
            self.system.plan({"plan_id": "empty", "steps": []})

    # -- Jobs and leases ------------------------------------------------------

    def test_submit_lease_complete_happy_path(self):
        self.scheduler.start(0)
        plan = self.make_plan()

        job = self.submit(plan)
        self.assertEqual(job["job_id"], "job-1")
        self.assertEqual(job["state"], "queued")
        self.assertEqual(job["generation"], 7)
        self.assertEqual(job["workspace"], plan.workspace_words)
        self.assertEqual(job["payload"], {"step": 1})

        lease = self.system.lease(
            self.worker_token,
            "MC0:0/R0",
            20,
            16,
            expected_generation=7,
        )
        self.assertIsNotNone(lease)
        self.assertEqual(lease["job_id"], "job-1")
        self.assertEqual(lease["lease_owner"], "MC0:0/R0")
        self.assertEqual(lease["deadline_tick"], 36)
        self.assertEqual(len(lease["lease_token"]), 64)

        done = self.system.complete(
            self.worker_token,
            "job-1",
            lease["lease_token"],
            lease["lease_epoch"],
            self.result_digest,
            30,
            result_generation=8,
            lease_owner="MC0:0/R0",
        )
        self.assertEqual(done["state"], "done")
        self.assertEqual(done["result_digest"], self.result_digest)
        self.assertEqual(done["result_generation"], 8)
        self.assertEqual(self.store.health()["jobs"]["done"], 1)
        self.assertIsNone(
            self.system.lease(self.worker_token, "MC0:0/R0", 31, 16)
        )

    def test_lease_requires_the_jahs_handoff_seal(self):
        class MissingJahsScheduler(WaveRingScheduler):
            def snapshot(self, now_tick=None):
                snapshot = super().snapshot(now_tick)
                snapshot.pop("jahs", None)
                return snapshot

        scheduler = MissingJahsScheduler(cycle_ticks=10, now_tick=0)
        scheduler.start(0)
        system = self.make_system(scheduler=scheduler)
        with self.assertRaises(MthSystemSlotError):
            system.lease(self.worker_token, "MC0:0/R0", 10)

    def test_lease_rejects_inactive_slot_and_accepts_active_alias(self):
        idle_system = self.make_system(scheduler=WaveRingScheduler(now_tick=0))
        with self.assertRaises(MthSystemSlotError):
            idle_system.lease(self.worker_token, "MC0:0/R0", 20, 16)

        self.scheduler.start(0)
        plan = self.make_plan()
        self.submit(plan)

        for owner in ("MC0:0/R1", "NANROUTER-5"):
            with self.subTest(owner=owner):
                with self.assertRaises(MthSystemSlotError):
                    self.system.lease(self.worker_token, owner, 20, 16)
        self.assertEqual(self.store.get_job("job-1")["state"], "queued")

        lease = self.system.lease(
            self.worker_token, "NANROUTER-0", 20, 16
        )
        self.assertIsNotNone(lease)
        self.assertEqual(lease["lease_owner"], "NANROUTER-0")

    def test_stale_generation_is_rejected_before_mutation(self):
        plan = self.make_plan()
        self.submit(plan, generation=7, tick=10)
        with self.assertRaises(StaleGenerationError):
            self.submit(plan, generation=6, tick=11)

        job = self.store.get_job("job-1")
        self.assertEqual(job["generation"], 7)
        self.assertEqual(job["state"], "queued")
        self.assertEqual(self.store.health()["jobs"]["queued"], 1)

    # -- Workspace bounds -----------------------------------------------------

    def test_submit_plan_caps_requested_workspace_at_plan_bound(self):
        plan = self.make_plan(workspace_words=64)
        self.assertEqual(plan.workspace_words, 64)
        job = self.submit(plan, workspace=1024)
        self.assertEqual(job["workspace"], 64)
        self.assertLessEqual(job["workspace"], plan.workspace_words)

        with self.assertRaises(MthSystemWorkspaceError):
            self.submit(plan, job_id="job-small", workspace=2)

    def test_submit_plan_admits_declared_liveness_by_peak_not_sum(self):
        def descriptor(name, workspace):
            return MthKernelDescriptor(
                kernel_id=f"mth.test.{name}.f32",
                source=f"{name}.nas",
                fixture=f"{name}_test.nas",
                marker="TEST",
                steps=1,
                precision="float32",
                workspace_words=workspace,
                shape=(1,),
                status="native_verified",
                ci_verified=True,
                source_digest="a" * 64,
                fixture_digest="b" * 64,
            )
        registry = MthRegistry([
            descriptor("a", 10), descriptor("b", 20), descriptor("c", 30),
        ])
        system = MthSystem(
            registry, self.store, self.service, self.scheduler,
            guest_budget_bytes=None,
            workspace_word_bytes=8,
            enforce_active_slot=True,
        )
        self.scheduler.start(0)
        steps = (
            MthPlanStep(name="a", kernel_id="mth.test.a.f32"),
            MthPlanStep(
                name="b", kernel_id="mth.test.b.f32", depends_on=("a",),
            ),
            MthPlanStep(name="c", kernel_id="mth.test.c.f32"),
        )
        plan = MthPlan(plan_id="peak-plan", steps=steps, workspace_words=30)
        job = self.submit(plan, system=system)
        self.assertEqual(job["workspace"], 30)
        below = MthPlan(
            plan_id="peak-below", steps=steps, workspace_words=29,
        )
        with self.assertRaises(MthPlanError):
            self.submit(below, system=system, job_id="job-below")

    def test_plan_workspace_over_seven_gib_runner_budget_is_rejected(self):
        words = (7 * 1024 ** 3) // 8 + 1
        descriptor = MthKernelDescriptor(
            kernel_id="mth.test.oversized.u32",
            source="oversized.nas",
            fixture="oversized_test.nas",
            marker="TEST OVERSIZED",
            steps=1,
            precision="u32",
            workspace_words=words,
            shape=(1,),
            status="native_verified",
            ci_verified=True,
            source_digest="a" * 64,
            fixture_digest="b" * 64,
        )
        registry = MthRegistry([descriptor])
        system = MthSystem(registry, self.store, self.service, self.scheduler)
        plan = registry.compose({
            "plan_id": "oversized",
            "steps": [{
                "name": "step",
                "kernel_id": descriptor.kernel_id,
                "inputs": [],
                "outputs": [],
                "depends_on": [],
            }],
        })
        self.assertEqual(plan.workspace_words, words)
        with self.assertRaises(MthSystemWorkspaceError):
            self.submit(plan, system=system)
        self.assertEqual(self.store.health()["jobs"]["queued"], 0)

    def test_default_guest_budget_is_2_mib_and_overridable(self):
        self.assertEqual(self.system.guest_budget_bytes, DEFAULT_GUEST_BUDGET_BYTES)
        self.assertEqual(DEFAULT_GUEST_BUDGET_BYTES, 2 * 1024 * 1024)
        self.assertEqual(self.system.guest_budget_words, 262_144)
        self.assertEqual(self.system.guest_budget_pages, 64)
        self.assertEqual(self.system.workspace_budget_bytes, 2 * 1024 * 1024)
        larger = self.make_system(guest_budget_bytes=4 * 1024 * 1024)
        self.assertEqual(larger.workspace_budget_bytes, 4 * 1024 * 1024)
        by_words = self.make_system(guest_budget_words=131_072)
        self.assertEqual(by_words.guest_budget_bytes, 1024 * 1024)

    def test_2_mib_default_admits_full_u_and_512_kib_override_rejects(self):
        words = 73_990
        descriptor = MthKernelDescriptor(
            kernel_id="mth.test.full_u.f32",
            source="full_u.nas",
            fixture="full_u_test.nas",
            marker="TEST FULL U",
            steps=1,
            precision="float32",
            workspace_words=words,
            shape=(1,),
            status="native_verified",
            ci_verified=True,
            source_digest="a" * 64,
            fixture_digest="b" * 64,
        )
        registry = MthRegistry([descriptor])
        plan = registry.compose({
            "plan_id": "full-u",
            "steps": [{
                "name": "step",
                "kernel_id": descriptor.kernel_id,
                "inputs": [],
                "outputs": [],
                "depends_on": [],
            }],
        })
        default_system = MthSystem(registry, self.store, self.service, self.scheduler)
        job = self.submit(plan, system=default_system, job_id="job-full-u")
        self.assertEqual(job["workspace"], words)
        small_system = MthSystem(
            registry,
            self.store,
            self.service,
            self.scheduler,
            guest_budget_bytes=512 * 1024,
        )
        with self.assertRaises(MthSystemWorkspaceError):
            self.submit(plan, system=small_system, job_id="job-full-u-small")

    def test_2_mib_default_admits_full_pair_and_legacy_1_mib_rejects(self):
        words = 196_608
        descriptor = MthKernelDescriptor(
            kernel_id="mth.test.full_pair.f32",
            source="full_pair.nas",
            fixture="full_pair_test.nas",
            marker="TEST FULL PAIR",
            steps=1,
            precision="float32",
            workspace_words=words,
            shape=(1,),
            status="native_verified",
            ci_verified=True,
            source_digest="a" * 64,
            fixture_digest="b" * 64,
        )
        registry = MthRegistry([descriptor])
        plan = registry.compose({
            "plan_id": "full-pair",
            "steps": [{
                "name": "step",
                "kernel_id": descriptor.kernel_id,
                "inputs": [],
                "outputs": [],
                "depends_on": [],
            }],
        })
        default_system = MthSystem(registry, self.store, self.service, self.scheduler)
        job = self.submit(plan, system=default_system, job_id="job-full-pair")
        self.assertEqual(job["workspace"], words)
        legacy_system = MthSystem(
            registry, self.store, self.service, self.scheduler,
            guest_budget_words=131_072,
        )
        with self.assertRaises(MthSystemWorkspaceError):
            self.submit(plan, system=legacy_system, job_id="job-full-pair-legacy")

    def test_exact_2_mib_plan_bound_is_accepted_and_one_word_over_is_rejected(self):
        boundary_words = 262_144
        descriptor = MthKernelDescriptor(
            kernel_id="mth.test.exact_2mib.f32",
            source="exact_2mib.nas",
            fixture="exact_2mib_test.nas",
            marker="TEST EXACT 2 MIB",
            steps=1,
            precision="float32",
            workspace_words=boundary_words,
            shape=(1,),
            status="native_verified",
            ci_verified=True,
            source_digest="a" * 64,
            fixture_digest="b" * 64,
        )
        registry = MthRegistry([descriptor])
        system = MthSystem(registry, self.store, self.service, self.scheduler)
        self.assertEqual(system.workspace_budget_bytes, 2 * 1024 * 1024)
        spec = {
            "plan_id": "exact-2mib",
            "steps": [{
                "name": "step",
                "kernel_id": descriptor.kernel_id,
                "inputs": [],
                "outputs": [],
                "depends_on": [],
            }],
        }

        at_limit = registry.compose(spec)
        self.assertEqual(at_limit.workspace_words, boundary_words)
        job = self.submit(
            at_limit, system=system, job_id="job-exact-2mib"
        )
        self.assertEqual(job["workspace"], boundary_words)
        self.assertEqual(self.store.health()["jobs"]["queued"], 1)

        over_limit = registry.compose({
            **spec,
            "plan_id": "exact-2mib-over",
            "workspace_words": boundary_words + 1,
        })
        self.assertEqual(over_limit.workspace_words, boundary_words + 1)
        with self.assertRaises(MthSystemWorkspaceError):
            self.submit(
                over_limit, system=system, job_id="job-exact-2mib-over"
            )
        self.assertEqual(self.store.health()["jobs"]["queued"], 1)
        self.assertIsNone(self.store.get_job("job-exact-2mib-over"))

    def test_separately_declared_guest_budget_is_enforced(self):
        plan = self.make_plan()
        guest_system = self.make_system(guest_budget_bytes=16)
        self.assertEqual(guest_system.workspace_budget_bytes, 16)
        with self.assertRaises(MthSystemWorkspaceError):
            self.submit(plan, system=guest_system, job_id="job-guest")
        self.assertEqual(self.store.health()["jobs"]["queued"], 0)

    # -- Capabilities and evidence -------------------------------------------

    def test_capability_and_evidence_delegates(self):
        capability = self.system.register_capability(
            self.admin_token,
            "mth.vector.cosine256.f32",
            "MC0:0/R0",
            self.operator_digest,
            4,
            "float32",
            status="native_verified",
            epoch=1,
            nanclock_tick=7,
        )
        self.assertEqual(capability["status"], "native_verified")
        self.assertEqual(capability["verified_digest"], self.operator_digest)

        trace = self.system.store_trace(
            self.submit_token,
            "universe-0",
            7,
            self.operator_digest,
            "MC0:0/R0",
            100,
            self.signature,
            payload={"kind": "trace"},
            job_id="job-1",
        )
        seal = self.system.store_seal(
            self.admin_token,
            "universe-0",
            7,
            self.operator_digest,
            "MC0:0/R0",
            101,
            self.signature,
            payload={"kind": "seal"},
            job_id="job-1",
        )
        signature = self.system.store_signature(
            self.submit_token,
            "universe-0",
            7,
            "ring",
            self.operator_digest,
            "MC0:0/R0",
            102,
            self.signature,
            payload={"kind": "signature"},
        )
        self.assertEqual(trace["payload"], {"kind": "trace"})
        self.assertEqual(seal["payload"], {"kind": "seal"})
        self.assertEqual(signature["payload"], {"kind": "signature"})
        stats = self.store.stats()
        self.assertEqual(stats["bs0"]["wave_trace"], 1)
        self.assertEqual(stats["bs0"]["wave_seal"], 1)
        self.assertEqual(stats["bs0"]["wave_signature"], 1)
        self.assertEqual(self.store.health()["native_verified_capabilities"], 1)

    # -- Ring, point 0, and health -------------------------------------------

    def test_ring_snapshot_and_stable_point_zero_route(self):
        before = self.system.point_zero_route()
        self.assertEqual(before["route"], POINT_ZERO_ADDRESS)
        self.assertIsNone(before["active_slot"])
        self.assertEqual(before["health"], "idle")

        started = self.scheduler.start(0)
        self.assertEqual(self.system.ring(), started)
        first = self.system.active_slot()
        self.assertEqual(first["route"], POINT_ZERO_ADDRESS)
        self.assertEqual(first["active_slot"], 0)
        self.assertEqual(first["active_slot_id"], "MC0:0/R0")
        self.assertEqual(first["jahs"]["seal"], "JAHS")

        self.scheduler.cycle(1)
        second = self.system.point_zero_route()
        self.assertEqual(second["route"], POINT_ZERO_ADDRESS)
        self.assertEqual(second["active_slot"], 1)
        self.assertEqual(second["active_alias"], "NANROUTER-1")

        for document in (before, first, second):
            route = document["route"]
            self.assertNotIn("R0", route)
            self.assertNotIn("R1", route)
            self.assertNotIn("NANROUTER", route)
            self.assertNotIn("MC0:0/R", route)

    def test_math_mode_requires_valid_admission_payload(self):
        system = self.make_system(require_math_admission=True)
        plan = self.make_plan(system)
        with self.assertRaises(MthSystemPlanError):
            self.submit(plan, system=system)
        job = self.submit(
            plan, system=system,
            payload={"math_admission": {"verdict": "VALID"}},
        )
        self.assertEqual(job["state"], "queued")

    def test_health_includes_and_gates_on_optional_math_health(self):
        healthy = self.make_system(math_health=lambda: {"status": "green"})
        self.assertEqual(healthy.health()["math"]["status"], "green")

        degraded = self.make_system(math_health=lambda: {"status": "red"})
        self.assertEqual(degraded.health()["status"], "degraded")

        def broken():
            raise RuntimeError("math store unavailable")

        failed = self.make_system(math_health=broken)
        health = failed.health()
        self.assertEqual(health["status"], "degraded")
        self.assertEqual(health["math"]["reason"], "math_health_provider_failed")

    def test_health_merges_components_without_secrets(self):
        self.scheduler.start(0)
        plan = self.make_plan()
        self.submit(plan)
        lease = self.system.lease(self.worker_token, "MC0:0/R0", 20, 16)
        self.system.complete(
            self.worker_token,
            "job-1",
            lease["lease_token"],
            lease["lease_epoch"],
            self.result_digest,
            30,
        )

        health = self.system.health()
        self.assertEqual(health["schema"], "nanrouter.mth-system-health.v1")
        self.assertEqual(health["status"], "green")
        self.assertEqual(health["store"]["schema"],
                         "nanrouter.wave-store-health.v1")
        self.assertEqual(health["registry"]["schema"],
                         "nanrouter.mth-registry-health.v1")
        self.assertEqual(health["ring"]["schema"],
                         "nanrouter.wave-ring-scheduler.v1")
        self.assertEqual(health["point_zero"]["route"], POINT_ZERO_ADDRESS)
        self.assertEqual(health["universe_map"]["pages"], 256)
        self.assertEqual(health["universe_map"]["universe_words"], 1_048_576)
        self.assertEqual(health["universe_map"]["relation_points"], 32_896)
        self.assertEqual(health["universe_map"]["coverage"], 1.0)
        self.assertEqual(
            health["budgets"]["runner_budget_bytes"],
            self.scheduler.max_active_memory_bytes,
        )
        self.assertEqual(
            health["budgets"]["guest_budget_bytes"],
            DEFAULT_GUEST_BUDGET_BYTES,
        )
        self.assertEqual(health["budgets"]["workspace_word_bytes"], 8)
        self.assertEqual(health["budgets"]["page_bytes"], 32 * 1024)
        self.assertFalse(health["budgets"]["page_limit_enforced"])
        self.assertIsNone(health["budgets"]["page_size_limit_bytes"])
        self.assertNotIn("glt_enforced", health["budgets"])
        self.assertEqual(health["budgets"]["guest_budget_words"], 262144)
        self.assertEqual(health["budgets"]["guest_budget_pages"], 64)
        self.assertEqual(health["budgets"]["workspace_budget_words"], 262144)
        self.assertEqual(health["store"]["jobs"]["done"], 1)
        self.assertIsNone(health["math"])

        rendered = json.dumps(health, sort_keys=True)
        for token in (self.submit_token, self.worker_token, self.admin_token):
            self.assertNotIn(token, rendered)
            self.assertNotIn(token, repr(self.system))
        self.assertNotIn("lease_token", rendered)
        self.assertNotIn("token", rendered.lower())

    # -- Construction ---------------------------------------------------------

    def test_constructor_validates_budgets_and_component_identity(self):
        with self.assertRaises(MthSystemConfigError):
            self.make_system(guest_budget_bytes=-1)
        with self.assertRaises(MthSystemConfigError):
            self.make_system(workspace_word_bytes=0)
        with self.assertRaises(MthSystemConfigError):
            self.make_system(enforce_active_slot="yes")

        other_store = WaveStore(
            Path(self.tmp.name) / "other-bs0.sqlite3",
            Path(self.tmp.name) / "other-mc0.sqlite3",
        )
        other_service = WaveService(
            other_store,
            "other-submit-token-000000000",
            "other-worker-token-111111111",
            "other-admin-token-2222222222",
        )
        with self.assertRaises(MthSystemConfigError):
            MthSystem(
                self.registry,
                self.store,
                other_service,
                self.scheduler,
            )


if __name__ == "__main__":
    unittest.main()
