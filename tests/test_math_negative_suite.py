"""High-value negative tests A06, A09, A10, A11, and A12.

These tests exercise the real ``MathRuntime``/``MathExecutionBridge``/
``WaveStore``/``MthSystem`` control path with a local executor spy.  They are
test-only: no production module is modified here.
"""
from __future__ import annotations

from dataclasses import replace
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runner_riddle import nmp
from runner_riddle.math_execution import (
    MathExecutionBindingError,
    MathExecutionBridge,
    MathExecutionGateError,
    MathExecutionPlanError,
    MathExecutionStateError,
)
from runner_riddle.math_registry import MathFunctionRegistry
from runner_riddle.math_runtime import MathRuntime, MathRuntimePlanError
from runner_riddle.math_store import MathStore
from runner_riddle.mth_registry import MthPlanStep, MthRegistry
from runner_riddle.mth_system import MthSystem
from runner_riddle.wave_ring_scheduler import WaveRingScheduler
from runner_riddle.wave_service import WaveService
from runner_riddle.wave_store import WaveStore

from tests.test_math_end_to_end import REPO, make_leaf
from tests.test_math_execution import (
    ADMIN_TOKEN,
    SUBMIT_TOKEN,
    WORKER_TOKEN,
)
from tests.test_nmp import make_admission


class RecordingExecutor:
    """Local executor spy with an exact call counter."""

    def __init__(self, digest: str = "a" * 64) -> None:
        self.digest = digest
        self.calls = 0
        self.leases: list[object] = []

    def __call__(self, lease: object = None) -> str:
        self.calls += 1
        self.leases.append(lease)
        return self.digest


class MathNegativeSuiteTests(unittest.TestCase):
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
        self.bridge = MathExecutionBridge(
            self.runtime,
            self.system,
            submit_token=SUBMIT_TOKEN,
            worker_token=WORKER_TOKEN,
        )

    # -- helpers ------------------------------------------------------------

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

    def register_capability(
        self,
        *,
        kernel_id: str | None = None,
        workspace: int = 1,
        epoch: int = 1,
        runner: str = "NANROUTER-0",
        status: str = "native_verified",
    ):
        kernel_id = kernel_id or self.compile_dot().plan.kernel_ids[0]
        descriptor = self.native.require(kernel_id)
        return self.wave_store.register_capability(
            kernel_id=descriptor.kernel_id,
            runner_id=runner,
            verified_digest=descriptor.source_digest,
            workspace=workspace,
            precision=descriptor.precision,
            status=status,
            epoch=epoch,
        )

    @staticmethod
    def count_commits():
        """Patch ``NmpPacket.commit`` with a counter for one test block."""
        original = nmp.NmpPacket.commit
        calls: list[str] = []

        def counted(instance, *args, **kwargs):
            calls.append(instance.packet_id)
            return original(instance, *args, **kwargs)

        return mock.patch.object(nmp.NmpPacket, "commit", new=counted), calls

    # -- A06 ----------------------------------------------------------------

    def test_a06_invalid_preflight_cannot_reach_executor(self):
        compiled = self.compile_dot()
        executor = RecordingExecutor()
        expected_packet_state = {
            "INVALID": nmp.REJECTED,
            "UNDEFINED": nmp.UNDEFINED,
            "UNAVAILABLE": nmp.UNAVAILABLE,
            "STALE": nmp.STALE,
        }
        # INVALID maps to the generic REJECTED control terminal; the others
        # keep their specific typed state.
        expected_gate_failure = {
            "INVALID": nmp.REJECTED,
            "UNDEFINED": nmp.UNDEFINED,
            "UNAVAILABLE": nmp.UNAVAILABLE,
            "STALE": nmp.STALE,
        }

        for verdict, expected_state in expected_packet_state.items():
            with self.subTest(verdict=verdict):
                admission = make_admission(
                    verdict=verdict,
                    candidate_id=compiled.candidate.candidate_id,
                    snapshot_id=compiled.candidate.snapshot_id,
                    ruleset_snapshot_id=compiled.admission.rule_snapshot_id,
                    preflight_digest=compiled.admission.preflight_digest,
                )
                # A non-VALID admission cannot compile into a plan.
                with self.assertRaises(MathRuntimePlanError):
                    self.runtime.compile(compiled.candidate, admission)

                packet = nmp.prepare(
                    compiled.candidate,
                    {
                        "result": verdict,
                        "digest": compiled.admission.preflight_digest,
                        "rule_snapshot_id": compiled.admission.rule_snapshot_id,
                    },
                    snapshot_id=compiled.candidate.snapshot_id,
                    admission=admission,
                    resources={
                        "guest_words": max(1, compiled.workspace_words),
                    },
                    ring_incarnation="ring:negative-a06",
                    ring_epoch=1,
                )
                self.assertEqual(packet.state, expected_state)
                self.assertIsNone(packet.result_digest)

                # The natural typed terminal cannot be submitted at all.
                with self.assertRaises(MathExecutionStateError):
                    self.bridge.submit(
                        packet,
                        replace(compiled, admission=admission),
                        now_tick=0,
                    )

                # Even a forged PREFLIGHTED claim is refused by the typed gate.
                forced = replace(packet, state=nmp.PREFLIGHTED)
                decision = self.bridge.check(
                    forced, replace(compiled, admission=admission),
                )
                self.assertFalse(decision.ok)
                self.assertEqual(
                    decision.failure, expected_gate_failure[verdict],
                )

                self.assertEqual(self.wave_store.list_jobs(), [])
                self.assertEqual(executor.calls, 0)

    # -- A09 ----------------------------------------------------------------

    def test_a09_capability_unavailable_or_revoked_is_unavailable(self):
        compiled = self.compile_dot()
        self.scheduler.start(0)
        packet = self.bridge.prepare_packet(compiled)
        executor = RecordingExecutor()

        # No dispatchable capability row.
        with self.assertRaises(MathExecutionGateError) as missing:
            self.bridge.submit(packet, compiled, now_tick=0)
        self.assertEqual(missing.exception.failure, nmp.UNAVAILABLE)
        self.assertNotEqual(missing.exception.failure, nmp.NULL)

        # A registered but revoked row is still UNAVAILABLE, not NULL.
        self.register_capability(status="revoked")
        with self.assertRaises(MathExecutionGateError) as revoked:
            self.bridge.submit(packet, compiled, now_tick=0)
        self.assertEqual(revoked.exception.failure, nmp.UNAVAILABLE)
        self.assertNotEqual(revoked.exception.failure, nmp.NULL)

        decision = self.bridge.check(
            packet,
            compiled,
            capability={
                "kernel_id": compiled.plan.kernel_ids[0],
                "status": "revoked",
                "workspace": max(1, compiled.workspace_words),
            },
            now_tick=0,
        )
        self.assertFalse(decision.ok)
        self.assertEqual(decision.failure, nmp.UNAVAILABLE)
        self.assertNotEqual(decision.failure, nmp.NULL)
        self.assertEqual(self.wave_store.list_jobs(), [])
        self.assertEqual(executor.calls, 0)

    # -- A10 ----------------------------------------------------------------

    def test_a10_implementation_binding_mismatch_is_rejected_before_job(self):
        compiled = self.compile_dot()
        self.register_capability()
        self.scheduler.start(0)
        packet = self.bridge.prepare_packet(compiled)
        executor = RecordingExecutor()

        bad_candidate = replace(
            compiled,
            candidate=replace(
                compiled.candidate,
                candidate_id="cnd:" + "1" * 64,
            ),
        )
        bad_snapshot = replace(
            compiled,
            admission=replace(
                compiled.admission,
                snapshot_id="snp:" + "e" * 64,
            ),
        )
        bad_function_version = replace(
            compiled,
            function=replace(compiled.function, version=2),
        )
        for label, tampered in (
            ("candidate", bad_candidate),
            ("snapshot", bad_snapshot),
            ("function_version", bad_function_version),
        ):
            with self.subTest(binding=label):
                with self.assertRaises(MathExecutionBindingError):
                    self.bridge.submit(packet, tampered, now_tick=0)
                self.assertEqual(self.wave_store.list_jobs(), [])
                self.assertEqual(executor.calls, 0)

        # The admission-selected implementation is bound at compile time.
        selected = {
            **(compiled.admission.scope.get("capability") or {}),
            "selected": {"kernel_id": "mth.vector.dot999.f32"},
        }
        bad_admission = replace(
            compiled.admission,
            scope={
                **compiled.admission.scope,
                "capability": selected,
            },
        )
        with self.assertRaises(MathRuntimePlanError):
            self.runtime.compile(compiled.candidate, bad_admission)
        self.assertEqual(self.wave_store.list_jobs(), [])
        self.assertEqual(executor.calls, 0)

    def test_a10_bridge_rejects_plan_kernel_not_selected_by_admission(self):
        """Production gap: the bridge does not re-check the selected kernel.

        ``MathRuntime.compile`` binds the admission-selected implementation,
        but a compiled object whose plan names another valid kernel is still
        accepted by ``MathExecutionBridge.submit`` and creates a job for that
        kernel.  The admission still claims the original selected kernel.
        """
        compiled = self.compile_dot()
        self.register_capability()
        self.register_capability(kernel_id="mth.vector.axpy256.f32")
        self.scheduler.start(0)

        descriptor = self.native.require("mth.vector.axpy256.f32")
        original_step = compiled.plan.steps[0]
        tampered_plan = replace(
            compiled.plan,
            steps=(
                MthPlanStep(
                    name=original_step.name,
                    kernel_id=descriptor.kernel_id,
                    inputs=original_step.inputs,
                    outputs=original_step.outputs,
                ),
            ),
            workspace_words=max(
                compiled.plan.workspace_words,
                descriptor.workspace_words,
            ),
        )
        self.native.validate_plan(tampered_plan)
        self.assertNotEqual(
            tampered_plan.kernel_ids,
            (compiled.admission.scope["capability"]["selected"]["kernel_id"],),
        )
        tampered = replace(compiled, plan=tampered_plan)
        packet = self.bridge.prepare_packet(tampered)
        executor = RecordingExecutor()

        with self.assertRaises(
            (MathExecutionBindingError, MathExecutionPlanError)
        ):
            self.bridge.submit(packet, tampered, now_tick=0)
        self.assertEqual(self.wave_store.list_jobs(), [])
        self.assertEqual(executor.calls, 0)

    # -- A11 ----------------------------------------------------------------

    def test_a11_expired_and_stale_lease_rejected_before_executor(self):
        compiled = self.compile_dot()
        self.register_capability()
        self.scheduler.start(0)
        packet = self.bridge.prepare_packet(compiled)
        submission = self.bridge.submit(packet, compiled, now_tick=0)
        lease = self.bridge.lease(submission, now_tick=0)
        self.assertIsNotNone(lease)
        self.assertIsNotNone(lease.deadline_tick)
        executor = RecordingExecutor()

        # Past the real WaveStore lease deadline.
        with self.assertRaises(MathExecutionStateError):
            self.bridge.execute(
                lease, executor, now_tick=lease.deadline_tick + 1,
            )
        self.assertEqual(executor.calls, 0)

        # The durable lease is expired/reclaimed; the old read model is stale.
        expired = self.wave_store.expire_leases(now_tick=lease.deadline_tick)
        self.assertEqual([row["job_id"] for row in expired], [lease.job_id])
        self.assertNotEqual(
            self.wave_store.get_job(lease.job_id)["state"], "leased",
        )
        with self.assertRaises(MathExecutionStateError):
            self.bridge.execute(
                lease, executor, now_tick=lease.deadline_tick + 1,
            )
        self.assertEqual(executor.calls, 0)

        # Stale token and stale lease epoch are bindings, not executions.
        with self.assertRaises(MathExecutionBindingError):
            self.bridge.execute(
                replace(lease, lease_token="0" * 64),
                executor,
                now_tick=1,
            )
        with self.assertRaises(MathExecutionBindingError):
            self.bridge.execute(
                replace(lease, lease_epoch=lease.lease_epoch + 1),
                executor,
                now_tick=1,
            )
        self.assertEqual(executor.calls, 0)
        job = self.wave_store.get_job(lease.job_id)
        self.assertNotEqual(job["state"], "done")
        self.assertIsNone(job["result_digest"])

    def test_a11_lease_deadline_boundary_is_rejected_before_executor(self):
        """Production gap: dispatch uses ``now_tick > deadline``.

        ``nmp.execution_gate`` and ``WaveStore._leased_row`` both treat
        ``now_tick == deadline_tick`` as expired, but
        ``MathExecutionBridge._validate_dispatch`` only rejects ``>``.  At the
        exact boundary the executor is called and completion then fails with
        ``LeaseError``.
        """
        compiled = self.compile_dot()
        self.register_capability()
        self.scheduler.start(0)
        packet = self.bridge.prepare_packet(compiled)
        submission = self.bridge.submit(packet, compiled, now_tick=0)
        lease = self.bridge.lease(submission, now_tick=0)
        self.assertIsNotNone(lease)
        executor = RecordingExecutor()

        with self.assertRaises(MathExecutionStateError):
            self.bridge.execute(
                lease, executor, now_tick=lease.deadline_tick,
            )
        self.assertEqual(executor.calls, 0)
        self.assertNotEqual(
            self.wave_store.get_job(lease.job_id)["state"], "done",
        )

    # -- A12 ----------------------------------------------------------------

    def test_a12_duplicate_conjunction_one_job_executor_and_commit(self):
        compiled = self.compile_dot()
        self.register_capability()
        self.scheduler.start(0)
        packet = self.bridge.prepare_packet(compiled)
        executor = RecordingExecutor("b" * 64)

        first = self.bridge.submit(packet, compiled, now_tick=0)
        duplicate = self.bridge.submit(packet, compiled, now_tick=0)
        self.assertFalse(first.duplicate)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(duplicate.job_id, first.job_id)
        self.assertEqual(len(self.wave_store.list_jobs()), 1)
        self.assertEqual(executor.calls, 0)

        lease = self.bridge.lease(first, now_tick=0)
        self.assertIsNotNone(lease)
        patcher, commits = self.count_commits()
        with patcher:
            result = self.bridge.execute(
                lease, executor, now_tick=1, commit=True,
            )
            self.assertTrue(result.committed)
            self.assertEqual(result.state, nmp.COMMITTED)
            self.assertEqual(result.result_digest, executor.digest)
            self.assertEqual(commits, [result.packet_id])
            self.assertEqual(executor.calls, 1)

            # Duplicate submission reuses the durable job and does not commit.
            late = self.bridge.submit(packet, compiled, now_tick=2)
            self.assertTrue(late.duplicate)
            self.assertEqual(late.job_id, first.job_id)
            self.assertEqual(late.job["state"], "done")
            self.assertEqual(late.result_digest, executor.digest)
            self.assertEqual(len(commits), 1)

            # Replaying completion against the committed packet is idempotent.
            replay = self.bridge.complete(
                result.packet,
                executor.digest,
                now_tick=3,
                commit=True,
            )
            self.assertTrue(replay.duplicate)
            self.assertTrue(replay.committed)
            self.assertEqual(replay.state, nmp.COMMITTED)
            self.assertEqual(len(commits), 1)
            self.assertEqual(executor.calls, 1)

        jobs = self.wave_store.list_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["job_id"], first.job_id)
        self.assertEqual(jobs[0]["state"], "done")
        self.assertEqual(jobs[0]["result_digest"], executor.digest)

    def test_a12_stale_lease_replay_does_not_reexecute_or_recommit(self):
        """Production gap: replaying an old lease re-runs the executor.

        ``_validate_dispatch`` trusts the job snapshot embedded in the
        ``MathExecutionLease`` instead of re-reading the durable WaveStore row.
        After the first commit, executing that stale lease calls the executor
        again and ``NmpPacket.commit`` runs a second time.
        """
        compiled = self.compile_dot()
        self.register_capability()
        self.scheduler.start(0)
        packet = self.bridge.prepare_packet(compiled)
        submission = self.bridge.submit(packet, compiled, now_tick=0)
        lease = self.bridge.lease(submission, now_tick=0)
        self.assertIsNotNone(lease)
        executor = RecordingExecutor("c" * 64)

        patcher, commits = self.count_commits()
        with patcher:
            result = self.bridge.execute(
                lease, executor, now_tick=1, commit=True,
            )
            self.assertTrue(result.committed)
            self.assertEqual(executor.calls, 1)
            self.assertEqual(len(commits), 1)

            with self.assertRaises(
                (MathExecutionStateError, MathExecutionBindingError)
            ):
                self.bridge.execute(
                    lease, executor, now_tick=2, commit=True,
                )
            self.assertEqual(executor.calls, 1)
            self.assertEqual(len(commits), 1)
            self.assertEqual(len(self.wave_store.list_jobs()), 1)


if __name__ == "__main__":
    unittest.main()
