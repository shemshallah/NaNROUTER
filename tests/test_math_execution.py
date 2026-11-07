from __future__ import annotations

from dataclasses import replace
import tempfile
import unittest
from pathlib import Path

from runner_riddle.math_execution import (
    MathExecutionBindingError,
    MathExecutionBridge,
    MathExecutionError,
    MathExecutionGateError,
    MathExecutionRingError,
    MathExecutionStateError,
)
from runner_riddle.math_objects import MathRule
from runner_riddle.math_registry import MathFunctionRegistry
from runner_riddle.math_runtime import MathRuntime, MathRuntimePlanError
from runner_riddle.math_store import MathStore
from runner_riddle.mth_registry import MthRegistry
from runner_riddle.mth_system import MthSystem
from runner_riddle.wave_ring_scheduler import WaveRingScheduler
from runner_riddle.wave_service import WaveService
from runner_riddle.wave_store import WaveStore

from tests.test_math_end_to_end import REPO, make_leaf

SUBMIT_TOKEN = "submit-token-0000000000000000"
WORKER_TOKEN = "worker-token-1111111111111111"
ADMIN_TOKEN = "admin-token-22222222222222222"


class MathExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.native = MthRegistry.load(REPO / "spec" / "wave-capabilities.json")
        cls.functions = MathFunctionRegistry.load(
            REPO / "spec" / "math-functions.v1.json",
            implementations=cls.native,
        )

    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        root = Path(self._temp.name)
        self.math_store = MathStore(root / "bs0.sqlite3", root / "mc0.sqlite3")
        self.a = self.math_store.put_leaf(make_leaf(1, "a"))
        self.b = self.math_store.put_leaf(make_leaf(2, "b"))
        self.wave_store = WaveStore(
            root / "wave-bs.sqlite3", root / "wave-mc.sqlite3",
        )
        self.service = WaveService(
            self.wave_store, SUBMIT_TOKEN, WORKER_TOKEN, ADMIN_TOKEN,
        )
        self.scheduler = WaveRingScheduler(cycle_ticks=10, now_tick=0)
        self.system = MthSystem(
            self.native, self.wave_store, self.service, self.scheduler,
        )
        self.runtime = MathRuntime(
            self.functions, store=self.math_store, system=self.system,
        )
        self.bridge = self.make_bridge()

    def make_bridge(self):
        return MathExecutionBridge(
            self.runtime,
            self.system,
            submit_token=SUBMIT_TOKEN,
            worker_token=WORKER_TOKEN,
        )

    def compile_dot(self):
        result = self.runtime.propose(
            [f"{self.a.leaf_id}@v1", f"{self.b.leaf_id}@v1"],
            snapshot_id="snp:" + "f" * 64,
            max_candidates=8,
        )
        candidate = next(
            item for item in result.items
            if item.function_id == "math.vector.dot"
        )
        admission = self.runtime.preflight(candidate)
        self.assertEqual(admission.verdict, "VALID")
        return self.runtime.compile(candidate, admission)

    def register_capability(self, *, workspace=1, epoch=1, runner="NANROUTER-0"):
        compiled = self.compile_dot()
        descriptor = self.native.require(compiled.plan.kernel_ids[0])
        return self.wave_store.register_capability(
            kernel_id=descriptor.kernel_id,
            runner_id=runner,
            verified_digest=descriptor.source_digest,
            workspace=workspace,
            precision=descriptor.precision,
            status="native_verified",
            epoch=epoch,
        )

    def test_compile_rejects_admission_for_another_candidate_or_snapshot(self):
        compiled = self.compile_dot()
        admission = compiled.admission
        with self.assertRaises(MathRuntimePlanError):
            self.runtime.compile(
                replace(compiled.candidate,
                        candidate_id="cnd:" + "1" * 64),
                admission,
            )
        with self.assertRaises(MathRuntimePlanError):
            self.runtime.compile(
                compiled.candidate,
                replace(admission, snapshot_id="snp:" + "e" * 64),
            )
        with self.assertRaises(MathRuntimePlanError):
            self.runtime.compile(
                compiled.candidate,
                replace(
                    admission,
                    scope={
                        **admission.scope,
                        "capability": {
                            **admission.scope.get("capability", {}),
                            "selected": {"kernel_id": "mth.vector.dot999.f32"},
                        },
                    },
                ),
            )

    def test_bridge_rejects_compiled_admission_for_another_candidate(self):
        compiled = self.compile_dot()
        bad = replace(
            compiled,
            admission=replace(
                compiled.admission,
                candidate_id="cnd:" + "1" * 64,
            ),
        )
        packet = self.bridge.prepare_packet(compiled)
        with self.assertRaises(MathExecutionBindingError):
            self.bridge._validate_compiled_binding(packet, bad)

    def test_ruleset_change_after_lease_blocks_dispatch_before_executor(self):
        class Provider:
            rules = ()

            def active_rules(self, *, include_isolated=False):
                return tuple(self.rules)

        provider = Provider()
        runtime = MathRuntime(
            self.functions, store=self.math_store, system=self.system,
            rule_provider=provider,
        )
        bridge = MathExecutionBridge(
            runtime, self.system,
            submit_token=SUBMIT_TOKEN, worker_token=WORKER_TOKEN,
        )
        self.register_capability()
        self.scheduler.start(0)
        result = runtime.propose(
            [f"{self.a.leaf_id}@v1", f"{self.b.leaf_id}@v1"],
            snapshot_id="snp:" + "f" * 64,
            max_candidates=8,
        )
        candidate = next(
            item for item in result.items
            if item.function_id == "math.vector.dot"
        )
        admission = runtime.preflight(candidate)
        compiled = runtime.compile(candidate, admission)
        packet = bridge.prepare_packet(compiled)
        submission = bridge.submit(packet, compiled, now_tick=0)
        lease = bridge.lease(submission, now_tick=0)
        self.assertIsNotNone(lease)

        provider.rules = (
            MathRule(
                rule_id="math.rule.late.change",
                version=1,
                level=1,
                contract={"claims": {}},
                proof_status="verified",
                status="active",
                scope={"function_ids": ["math.vector.dot"]},
            ),
        )
        calls = []
        with self.assertRaises(MathExecutionStateError):
            bridge.execute(
                lease,
                lambda: calls.append("called") or "c" * 64,
                now_tick=1,
            )
        self.assertEqual(calls, [])

    def test_execute_rejects_expired_lease_before_calling_executor(self):
        self.register_capability()
        self.scheduler.start(0)
        compiled = self.compile_dot()
        packet = self.bridge.prepare_packet(compiled)
        submission = self.bridge.submit(packet, compiled, now_tick=0)
        lease = self.bridge.lease(submission, now_tick=0)
        self.assertIsNotNone(lease)
        calls = []
        expired = replace(lease, deadline_tick=0)
        with self.assertRaises(MathExecutionStateError):
            self.bridge.execute(
                expired,
                lambda: calls.append("called") or "a" * 64,
                now_tick=1,
            )
        self.assertEqual(calls, [])

    def test_lease_and_result_serialization_redact_bearer_token(self):
        self.register_capability()
        self.scheduler.start(0)
        compiled = self.compile_dot()
        packet = self.bridge.prepare_packet(compiled)
        submission = self.bridge.submit(packet, compiled, now_tick=0)
        lease = self.bridge.lease(submission, now_tick=0)
        self.assertIsNotNone(lease)
        raw = lease.lease_token
        rendered = lease.to_dict()
        self.assertNotIn("lease_token", rendered)
        self.assertIn("lease_token_digest", rendered)
        result = self.bridge.execute(
            lease, lambda: "c" * 64, now_tick=1, commit=True,
        )
        self.assertNotIn("lease_token", result.to_dict())
        self.assertIn("lease_token_digest", result.to_dict()["packet"]["evidence"])
        self.assertNotIn(raw, str(result.to_dict()["packet"]["provenance"]))
        self.assertNotIn(raw, str(result.to_dict()))

    def test_ring_must_be_active_and_authenticated(self):
        compiled = self.compile_dot()
        with self.assertRaises(MathExecutionRingError):
            self.bridge.ring_binding()
        self.scheduler.start(0)
        binding = self.bridge.ring_binding()
        self.assertTrue(binding.started)
        self.assertEqual(binding.jahs, "JAHS")
        packet = self.bridge.prepare_packet(compiled)
        with self.assertRaises(MathExecutionGateError) as raised:
            self.bridge.submit(packet, compiled, now_tick=0)
        self.assertEqual(raised.exception.decision.failure, "UNAVAILABLE")
        self.register_capability()
        submission = self.bridge.submit(packet, compiled, now_tick=0)
        self.assertEqual(submission.packet.state, "QUEUED")
        self.assertEqual(submission.job["state"], "queued")

    def test_submit_lease_execute_complete_projects_and_releases_ring(self):
        self.register_capability()
        self.scheduler.start(0)
        compiled = self.compile_dot()
        packet = self.bridge.prepare_packet(compiled)
        submission = self.bridge.submit(packet, compiled, now_tick=0)
        lease = self.bridge.lease(submission, now_tick=0)
        self.assertIsNotNone(lease)
        self.assertEqual(lease.owner, "MC0:0/R0")
        self.assertEqual(lease.workspace_words, 1)
        self.assertEqual(lease.memory_bytes, 8)
        result = self.bridge.execute(
            lease, lambda: "a" * 64, now_tick=1, commit=True,
        )
        self.assertEqual(result.state, "COMMITTED")
        self.assertEqual(result.job_state, "done")
        self.assertTrue(result.ring_released)
        self.assertEqual(dict(self.bridge._ring_resources), {})
        job = self.wave_store.get_job(submission.job_id)
        self.assertEqual(job["state"], "done")
        self.assertEqual(job["result_digest"], "a" * 64)
        projection = self.bridge.project(result.packet, job=job, now_tick=1)
        self.assertEqual(projection.state, "COMMITTED")
        self.assertTrue(projection.supported)
        packet_row = self.math_store.get_nmp_packet(submission.packet_id)
        self.assertEqual(packet_row["state"], "COMMITTED")
        transitions = self.math_store.list_nmp_transitions(submission.packet_id)
        self.assertEqual(
            [(row["from_state"], row["to_state"]) for row in transitions],
            [
                ("PREFLIGHTED", "QUEUED"),
                ("QUEUED", "EXECUTING"),
                ("EXECUTING", "COMPLETED"),
                ("COMPLETED", "COMMITTED"),
            ],
        )

    def test_duplicate_submit_reuses_one_durable_job(self):
        self.register_capability()
        self.scheduler.start(0)
        compiled = self.compile_dot()
        packet = self.bridge.prepare_packet(compiled)
        first = self.bridge.submit(packet, compiled, now_tick=0)
        second = self.bridge.submit(packet, compiled, now_tick=0)
        self.assertFalse(first.duplicate)
        self.assertTrue(second.duplicate)
        self.assertEqual(second.job_id, first.job_id)
        self.assertEqual(second.job["job_id"], first.job_id)

    def test_cancel_before_lease_is_terminal_and_prevents_dispatch(self):
        self.register_capability()
        self.scheduler.start(0)
        compiled = self.compile_dot()
        packet = self.bridge.prepare_packet(compiled)
        submission = self.bridge.submit(packet, compiled, now_tick=0)
        cancellation = self.bridge.cancel(
            submission, now_tick=0, reason="user stopped",
        )
        self.assertEqual(cancellation.state, "CANCELLED")
        self.assertEqual(cancellation.status, "cancelled")
        job = self.wave_store.get_job(submission.job_id)
        self.assertEqual(job["state"], "failed")
        self.assertIsNone(self.bridge.lease(submission, now_tick=1))
        self.assertEqual(
            self.math_store.get_nmp_packet(submission.packet_id)["state"],
            "CANCELLED",
        )
        transitions = self.math_store.list_nmp_transitions(submission.packet_id)
        self.assertEqual(
            (transitions[-1]["from_state"], transitions[-1]["to_state"]),
            ("QUEUED", "CANCELLED"),
        )

    def test_capability_workspace_must_cover_the_guard_word(self):
        self.scheduler.start(0)
        compiled = self.compile_dot()
        packet = self.bridge.prepare_packet(compiled)
        self.register_capability(workspace=0)
        with self.assertRaises(MathExecutionGateError):
            self.bridge.submit(packet, compiled, now_tick=0)
        descriptor = self.native.require(compiled.plan.kernel_ids[0])
        self.wave_store.register_capability(
            kernel_id=descriptor.kernel_id,
            runner_id="NANROUTER-0",
            verified_digest=descriptor.source_digest,
            workspace=1,
            precision=descriptor.precision,
            status="native_verified",
            epoch=2,
        )
        submission = self.bridge.submit(packet, compiled, now_tick=0)
        self.assertEqual(submission.job["state"], "queued")

    def test_tampered_packet_candidate_is_refused_before_job_creation(self):
        self.register_capability()
        self.scheduler.start(0)
        compiled = self.compile_dot()
        packet = self.bridge.prepare_packet(compiled)
        tampered = replace(packet, candidate_id="cnd:" + "0" * 64)
        with self.assertRaises(MathExecutionBindingError):
            self.bridge.submit(tampered, compiled, now_tick=0)
        jobs = self.wave_store.list_jobs() if hasattr(
            self.wave_store, "list_jobs"
        ) else []
        self.assertEqual(jobs, [])

    def test_restart_reconstructs_completed_packet_from_durable_rows(self):
        self.register_capability()
        self.scheduler.start(0)
        compiled = self.compile_dot()
        packet = self.bridge.prepare_packet(compiled)
        submission = self.bridge.submit(packet, compiled, now_tick=0)
        lease = self.bridge.lease(submission, now_tick=0)
        result = self.bridge.execute(lease, lambda: "b" * 64, now_tick=1)
        restarted = self.make_bridge()
        reconstructed = restarted.restart(result.packet, tick=2)
        self.assertEqual(reconstructed.state, "COMPLETED")
        self.assertEqual(reconstructed.result_digest, "b" * 64)
        report = restarted.project_execution(result.packet, now_tick=2)
        self.assertEqual(report["projection"]["state"], "COMPLETED")


if __name__ == "__main__":
    unittest.main()
