"""High-value negative tests A01-A05, A06, A09-A16, A20, and T07/T08/T19.

These tests exercise the real ``MathRuntime``/``MathExecutionBridge``/
``WaveStore``/``MthSystem``/``MathStore``/relation/learning/retention control
paths with a local executor spy.  They are test-only: no production module is
modified here.
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
from runner_riddle.math_learning import (
    Level0ImmutableError,
    LifecycleStateError,
    MathLearningService,
    RuleProposal,
    SelfApprovalDenied,
)
from runner_riddle.math_linker import classify_leaf, propose as link_propose
from runner_riddle.math_objects import MathRule, digest_object
from runner_riddle.math_relation import (
    Hypergraph,
    HypergraphError,
    RelationDepthError,
    RelationDuplicateError,
    RelationMember,
    RelationRecord,
    RelationSchema,
    RoleSpec,
)
from runner_riddle.math_registry import MathFunctionRegistry
from runner_riddle.math_retention import (
    STOP_DEPTH_LIMIT,
    STOP_DUPLICATE_STATE,
    MathRetention,
    OscillationBudget,
    OscillationState,
)
from runner_riddle.math_runtime import MathRuntime, MathRuntimePlanError
from runner_riddle.math_store import (
    MathConflictError,
    MathContentDigestError,
    MathReferenceError,
    MathStore,
    StaleGenerationError,
)
from runner_riddle.mth_registry import MthPlanStep, MthRegistry
from runner_riddle.mth_system import MthSystem
from runner_riddle.wave_ring_scheduler import WaveRingScheduler
from runner_riddle.wave_service import WaveService, WaveServiceAuthError
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

    @staticmethod
    def make_rule_proposal(rule_id, *, level=1, claims=None):
        return RuleProposal(
            rule_id=rule_id,
            level=level,
            contract={"claims": dict(claims or {"a13": True})},
            scope={"function_ids": ["math.vector.dot"]},
            claim_class="rewrite",
        )

    def activate_rule(self, service, rule_id, *, level=1):
        service.propose(
            self.make_rule_proposal(rule_id, level=level),
            proposer="learning:proposer",
        )
        service.hash_proposal(rule_id, actor="learning:proposer")
        service.validate(rule_id, validator="validity:validator")
        service.test(
            rule_id,
            tester="experiment:tester",
            harness="harness:bounded-1",
            cases=[{"outcome": "pass"}],
        )
        service.approve(rule_id, approver="owner:approver")
        service.commit(rule_id, actor="lifecycle:committer")
        return service.activate(rule_id, actor="lifecycle:activator")

    # -- A01 ----------------------------------------------------------------

    def test_a01_tampered_content_digest_is_rejected_before_mapping(self):
        executor = RecordingExecutor()
        leaf = make_leaf(3, "c")
        bad = replace(leaf, metadata_version=1)
        before = {
            row["mapping_id"]: row["current_version"]
            for row in self.math_store.list_mappings()
        }
        patcher, commits = self.count_commits()
        with patcher:
            with self.assertRaises(MathContentDigestError):
                self.math_store.put_leaf(bad)

        after = {
            row["mapping_id"]: row["current_version"]
            for row in self.math_store.list_mappings()
        }
        self.assertEqual(after, before)
        with self.assertRaises(MathReferenceError):
            self.math_store.get_leaf(bad.leaf_id)
        self.assertEqual(executor.calls, 0)
        self.assertEqual(self.wave_store.list_jobs(), [])
        self.assertEqual(commits, [])

    # -- A02 ----------------------------------------------------------------

    def test_a02_same_content_distinct_identity_conflict_keeps_original(self):
        executor = RecordingExecutor()
        base = make_leaf(10, "d")
        first = self.math_store.put_leaf(base)
        twin = self.math_store.put_leaf(replace(
            base,
            leaf_id="nml:U0:vector:11",
            provenance={"producer": "twin"},
        ))
        self.assertNotEqual(first.leaf_id, twin.leaf_id)
        self.assertEqual(first.content_digest, twin.content_digest)

        mapping_id = "leaf:" + first.leaf_id
        before = self.math_store.get_mapping(mapping_id)
        versions_before = self.math_store.list_versions(first.leaf_id)
        patcher, commits = self.count_commits()
        with patcher:
            with self.assertRaises(MathConflictError):
                self.math_store.put_leaf(replace(
                    base, provenance={"producer": "different"},
                ))

        self.assertEqual(self.math_store.get_mapping(mapping_id), before)
        self.assertEqual(
            self.math_store.list_versions(first.leaf_id), versions_before,
        )
        self.assertEqual(
            self.math_store.get_leaf(first.leaf_id).content, base.content,
        )
        self.assertEqual(executor.calls, 0)
        self.assertEqual(self.wave_store.list_jobs(), [])
        self.assertEqual(commits, [])

    # -- A03 ----------------------------------------------------------------

    def test_a03_bad_version_digest_and_stale_cas_leave_mapping_intact(self):
        executor = RecordingExecutor()
        base = make_leaf(12, "e")
        payload = {
            key: value for key, value in dict(base.content).items()
            if key != "digest"
        }
        good = replace(
            base,
            content={**dict(base.content), "digest": digest_object(payload)},
            metadata_version=1,
        )
        leaf = self.math_store.put_leaf(good)
        mapping_id = "leaf:" + leaf.leaf_id
        before = self.math_store.get_mapping(mapping_id)

        patcher, commits = self.count_commits()
        with patcher:
            with self.assertRaises(MathContentDigestError):
                self.math_store.put_version(
                    leaf.leaf_id,
                    {"digest": "f" * 64, "value": 2},
                    expected_version=1,
                    expected_generation=1,
                )
            self.assertEqual(self.math_store.get_mapping(mapping_id), before)
            self.assertEqual(
                [row["version"] for row in
                 self.math_store.list_versions(leaf.leaf_id)],
                [1],
            )

            second = self.math_store.put_version(
                leaf.leaf_id,
                {"digest": digest_object({"value": 2}), "value": 2},
                expected_version=1,
                expected_generation=1,
            )
            self.assertEqual(second.version, 2)
            moved = self.math_store.get_mapping(mapping_id)
            self.assertEqual(moved["current_version"], 2)

            with self.assertRaises(StaleGenerationError):
                self.math_store.put_version(
                    leaf.leaf_id,
                    {"digest": digest_object({"value": 3}), "value": 3},
                    expected_version=1,
                    expected_generation=1,
                )

        self.assertEqual(self.math_store.get_mapping(mapping_id), moved)
        self.assertEqual(
            [row["version"] for row in
             self.math_store.list_versions(leaf.leaf_id)],
            [1, 2],
        )
        self.assertEqual(
            self.math_store.get_leaf(leaf.leaf_id).content,
            {"digest": digest_object({"value": 2}), "value": 2},
        )
        self.assertEqual(executor.calls, 0)
        self.assertEqual(self.wave_store.list_jobs(), [])
        self.assertEqual(commits, [])

    # -- A04 ----------------------------------------------------------------

    def test_a04_vector_vector_candidate_set_is_deterministic_and_inert(self):
        executor = RecordingExecutor()
        refs = [f"{self.a.leaf_id}@v1", f"{self.b.leaf_id}@v1"]
        patcher, commits = self.count_commits()
        with patcher:
            first = self.runtime.propose(
                refs, snapshot_id="snp:" + "1" * 64, max_candidates=8,
            )
            second = self.runtime.propose(
                refs, snapshot_id="snp:" + "1" * 64, max_candidates=8,
            )

        self.assertGreaterEqual(first.candidate_count, 2)
        self.assertEqual(first.candidate_ids, second.candidate_ids)
        self.assertEqual(
            len(set(first.candidate_ids)), len(first.candidate_ids),
        )
        self.assertEqual(first.to_dict()["execution"], "not_performed")
        self.assertFalse(first.authorized)
        self.assertEqual(executor.calls, 0)
        self.assertEqual(self.wave_store.list_jobs(), [])
        self.assertEqual(commits, [])

    # -- A05 ----------------------------------------------------------------

    def test_a05_zero_candidate_is_typed_null_and_never_executes(self):
        executor = RecordingExecutor()
        patcher, commits = self.count_commits()
        with patcher:
            result = link_propose(
                [self.a, self.b],
                registry={},
                snapshot_id="snp:" + "2" * 64,
            )

        self.assertEqual(result.candidate_count, 0)
        self.assertEqual(result.candidate_ids, ())
        self.assertIsNotNone(result.null)
        self.assertEqual(result.null.kind, "null")
        self.assertIsNone(result.null.content)
        self.assertNotEqual(result.null.kind, "scalar")
        self.assertEqual(
            result.null.metadata["reason"], "NO_REGISTERED_FUNCTION",
        )
        self.assertEqual(
            result.null.metadata["failure_class"], "NO_REGISTERED_FUNCTION",
        )
        self.assertEqual(result.to_dict()["execution"], "not_performed")
        self.assertEqual(executor.calls, 0)
        self.assertEqual(self.wave_store.list_jobs(), [])
        self.assertEqual(commits, [])

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

    # -- A13 ----------------------------------------------------------------

    def test_a13_self_validation_approval_commit_and_promotion_denied(self):
        service = MathLearningService(self.math_store)
        rule_id = "math.rule.a13.self"
        proposer = "learning:proposer"
        service.propose(
            self.make_rule_proposal(rule_id), proposer=proposer,
        )
        service.hash_proposal(rule_id, actor=proposer)

        def denied(action):
            before = self.math_store.get_rule_meta(rule_id)
            with self.assertRaises(SelfApprovalDenied):
                action()
            self.assertEqual(
                self.math_store.get_rule_meta(rule_id), before,
            )

        denied(lambda: service.validate(rule_id, validator=proposer))
        service.validate(rule_id, validator="validity:validator")
        denied(lambda: service.test(
            rule_id, tester="validity:validator",
            harness="harness:bounded-1", cases=[{"outcome": "pass"}],
        ))
        service.test(
            rule_id, tester="experiment:tester",
            harness="harness:bounded-1", cases=[{"outcome": "pass"}],
        )
        denied(lambda: service.approve(
            rule_id, approver="experiment:tester",
        ))
        service.approve(rule_id, approver="owner:approver")
        denied(lambda: service.commit(rule_id, actor=proposer))
        service.commit(rule_id, actor="lifecycle:committer")
        denied(lambda: service.activate(rule_id, actor=proposer))

        active = service.activate(rule_id, actor="lifecycle:activator")
        self.assertEqual(active.state, "active")
        mapping_id = "rule:" + rule_id
        before_meta = self.math_store.get_rule_meta(rule_id)
        before_mapping = self.math_store.get_mapping(mapping_id)
        with self.assertRaises(SelfApprovalDenied):
            service.promote(rule_id, 2, actor=proposer)
        self.assertEqual(self.math_store.get_rule_meta(rule_id), before_meta)
        self.assertEqual(self.math_store.get_mapping(mapping_id), before_mapping)

        actions = {
            event["action"]
            for event in service.audit(rule_id)["events"]
        }
        self.assertTrue({
            "denied_validate", "denied_test", "denied_approve",
            "denied_commit", "denied_activate",
        }.issubset(actions))
        executor = RecordingExecutor()
        patcher, commits = self.count_commits()
        with patcher:
            pass
        self.assertEqual(executor.calls, 0)
        self.assertEqual(self.wave_store.list_jobs(), [])
        self.assertEqual(commits, [])

    # -- A14 ----------------------------------------------------------------

    def test_a14_level0_and_invalid_rollback_never_move_the_mapping(self):
        executor = RecordingExecutor()
        level0_id = "math.rule.a14.level0"
        self.math_store.put_rule(MathRule(
            rule_id=level0_id,
            level=0,
            contract={"claims": {"types": "closed"}},
            proof_status="axiom",
            status="active",
        ))
        service = MathLearningService(self.math_store)
        before = self.math_store.get_rule_meta(level0_id)
        with self.assertRaises(Level0ImmutableError):
            service.propose(
                self.make_rule_proposal(level0_id, level=1),
                proposer="learning:proposer",
            )
        with self.assertRaises(Level0ImmutableError):
            service.propose(
                self.make_rule_proposal(
                    "math.rule.a14.new_level0", level=0,
                ),
                proposer="learning:proposer",
            )
        with self.assertRaises(Level0ImmutableError):
            service.promote(
                level0_id, 1, actor="lifecycle:activator",
            )
        self.assertEqual(self.math_store.get_rule_meta(level0_id), before)
        self.assertEqual(self.math_store.get_rule(level0_id).level, 0)

        rule_id = "math.rule.a14.rollback"
        active = self.activate_rule(service, rule_id)
        first_active = active.version
        experiment = service.record_experiment(
            rule_id,
            {
                "source": "r7",
                "outcome": "supported",
                "sample_size": 32,
                "data_digest": "a" * 64,
            },
            actor="experiment:r7",
        )
        self.assertGreater(experiment.version, first_active)
        mapping_id = "rule:" + rule_id
        before_mapping = self.math_store.get_mapping(mapping_id)
        with self.assertRaises(LifecycleStateError):
            service.rollback(
                rule_id, actor="lifecycle:activator", target_version=2,
            )
        self.assertEqual(
            self.math_store.get_mapping(mapping_id), before_mapping,
        )

        rolled = service.rollback(
            rule_id, actor="lifecycle:activator",
            target_version=first_active,
        )
        self.assertEqual(rolled.state, "rolled_back")
        mapping = self.math_store.get_mapping(mapping_id)
        self.assertEqual(mapping["current_version"], first_active)
        self.assertEqual(mapping["status"], "rolled_back")
        self.assertEqual(
            self.math_store.get_rule(rule_id, experiment.version).version,
            experiment.version,
        )
        patcher, commits = self.count_commits()
        with patcher:
            pass
        self.assertEqual(executor.calls, 0)
        self.assertEqual(self.wave_store.list_jobs(), [])
        self.assertEqual(commits, [])

    # -- A15 ----------------------------------------------------------------

    def test_a15_oscillation_budgets_stop_without_dispatch(self):
        executor = RecordingExecutor()
        state = OscillationState(OscillationBudget(
            max_depth=8, max_fanout=2, fuel=4, max_candidates=4,
            max_flips=1, dwell_ticks=1,
        ))
        first = state.advance(
            state_key="state:1", content_digest="a" * 64,
        )
        self.assertTrue(first.allowed)
        duplicate = state.advance(
            state_key="state:1", content_digest="b" * 64,
        )
        self.assertFalse(duplicate.allowed)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(duplicate.stop_reason, STOP_DUPLICATE_STATE)
        self.assertTrue(state.stopped)
        for _ in range(3):
            repeated = state.advance(state_key="state:2")
            self.assertFalse(repeated.allowed)
            self.assertEqual(repeated.stop_reason, STOP_DUPLICATE_STATE)

        depth_state = OscillationState(OscillationBudget(
            max_depth=1, max_fanout=2, fuel=4, max_candidates=4,
        ))
        self.assertTrue(depth_state.advance(
            state_key="depth:1", depth=1,
        ).allowed)
        blocked = depth_state.advance(state_key="depth:2", depth=1)
        self.assertFalse(blocked.allowed)
        self.assertEqual(blocked.stop_reason, STOP_DEPTH_LIMIT)
        self.assertTrue(depth_state.stopped)

        patcher, commits = self.count_commits()
        with patcher:
            pass
        self.assertEqual(executor.calls, 0)
        self.assertEqual(self.wave_store.list_jobs(), [])
        self.assertEqual(commits, [])

    # -- A16 ----------------------------------------------------------------

    def test_a16_retention_preserves_truth_and_payload_without_execution(self):
        executor = RecordingExecutor()
        truth = self.math_store.put_leaf(replace(
            make_leaf(30, "f"),
            metadata={
                "truth_status": "proved",
                "retention": {"utility": 0, "storage_cost": 100},
            },
        ))
        low = self.math_store.put_leaf(replace(
            make_leaf(31, "1"),
            metadata={"retention": {"utility": 0, "storage_cost": 100}},
        ))
        manager = MathRetention(self.math_store)
        plan = manager.plan()
        truth_action = next(
            action for action in plan.actions
            if action.object_id == truth.leaf_id
        )
        low_action = next(
            action for action in plan.actions
            if action.object_id == low.leaf_id
        )
        self.assertEqual(truth_action.action, "retain")
        self.assertTrue(truth_action.protected)
        self.assertIn("truth:proved", truth_action.protection)
        self.assertEqual(low_action.action, "tombstone")
        self.assertFalse(low_action.protected)
        self.assertTrue(manager.shadow(plan).approved)

        patcher, commits = self.count_commits()
        with patcher:
            result = manager.apply(plan, tick=1)

        self.assertIn(
            "leaf:" + low.leaf_id,
            [record.mapping_id for record in result.applied],
        )
        self.assertIsNone(manager.record("leaf:" + truth.leaf_id))
        self.assertEqual(
            manager.record("leaf:" + low.leaf_id).state, "tombstoned",
        )
        self.assertEqual(
            self.math_store.get_leaf(truth.leaf_id).content, truth.content,
        )
        self.assertEqual(
            self.math_store.get_leaf(low.leaf_id).content, low.content,
        )
        self.assertEqual(
            self.math_store.get_mapping("leaf:" + truth.leaf_id)[
                "current_version"
            ],
            1,
        )
        self.assertEqual(executor.calls, 0)
        self.assertEqual(self.wave_store.list_jobs(), [])
        self.assertEqual(commits, [])

    # -- A20 ----------------------------------------------------------------

    def test_a20_unauthorized_submit_and_lease_tokens_precede_executor(self):
        compiled = self.compile_dot()
        self.register_capability()
        self.scheduler.start(0)
        packet = self.bridge.prepare_packet(compiled)
        executor = RecordingExecutor()
        bad_token = "0" * 32
        patcher, commits = self.count_commits()
        with patcher:
            with self.assertRaises(WaveServiceAuthError):
                self.bridge.submit(
                    packet, compiled, now_tick=0, submit_token=bad_token,
                )
            self.assertEqual(self.wave_store.list_jobs(), [])

            submission = self.bridge.submit(packet, compiled, now_tick=0)
            self.assertEqual(submission.job["state"], "queued")
            with self.assertRaises(WaveServiceAuthError):
                self.bridge.lease(
                    submission, now_tick=0, worker_token=bad_token,
                )

        job = self.wave_store.get_job(submission.job_id)
        self.assertEqual(job["state"], "queued")
        self.assertFalse(job["lease_epoch"])
        self.assertIsNone(job["result_digest"])
        snapshot = self.scheduler.snapshot()
        self.assertEqual(snapshot["active_lease_count"], 0)
        self.assertEqual(snapshot["active_memory_reserved_bytes"], 0)
        self.assertEqual(dict(self.bridge._ring_resources), {})
        self.assertEqual(executor.calls, 0)
        self.assertEqual(commits, [])

    def test_a20_unauthorized_worker_token_never_reaches_executor(self):
        """Production gap: execute authenticates only after the executor.

        ``MathExecutionBridge._validate_dispatch`` checks that a worker token
        is present but not that it authenticates the worker role.  A wrong
        token therefore calls the executor, then ``complete`` raises
        ``WaveServiceAuthError`` and leaves the job leased.  The required
        behavior is zero executor calls, an unchanged leased/queued row, and
        no commit.
        """
        compiled = self.compile_dot()
        self.register_capability()
        self.scheduler.start(0)
        packet = self.bridge.prepare_packet(compiled)
        submission = self.bridge.submit(packet, compiled, now_tick=0)
        lease = self.bridge.lease(submission, now_tick=0)
        self.assertIsNotNone(lease)
        executor = RecordingExecutor()
        bad_token = "0" * 32
        patcher, commits = self.count_commits()
        with patcher:
            with self.assertRaises(WaveServiceAuthError):
                self.bridge.execute(
                    lease, executor, now_tick=1, worker_token=bad_token,
                )

        self.assertEqual(executor.calls, 0)
        self.assertEqual(commits, [])
        job = self.wave_store.get_job(submission.job_id)
        self.assertEqual(job["state"], "leased")
        self.assertIsNone(job["result_digest"])

    # -- T07 ----------------------------------------------------------------

    def test_t07_vector_hyperedge_is_typed_and_not_silently_executed(self):
        executor = RecordingExecutor()
        schema = RelationSchema(
            schema_id="math.relation.t07",
            ordered=False,
            duplicate_policy="forbid",
            directed=False,
            roles=(RoleSpec("member", min_count=2),),
            min_arity=2,
            max_arity=2,
        )
        relation = RelationRecord(
            "nml:U0:relation:t07",
            schema,
            1,
            (
                RelationMember(self.a.leaf_id, version=1, role="member"),
                RelationMember(self.b.leaf_id, version=1, role="member"),
            ),
        )
        hyperedge = relation.to_math_leaf(leaf_id="nml:U0:hyperedge:t07")
        classified = classify_leaf(hyperedge)
        self.assertEqual(classified.kind, "relation")
        self.assertEqual(classified.relation_schema, "math.relation.t07")

        patcher, commits = self.count_commits()
        with patcher:
            result = link_propose(
                [self.a, hyperedge],
                registry=self.functions.functions,
                snapshot_id="snp:" + "3" * 64,
            )

        self.assertEqual(result.candidate_count, 0)
        self.assertIsNotNone(result.null)
        self.assertEqual(result.null.kind, "null")
        self.assertIsNone(result.null.content)
        self.assertEqual(result.to_dict()["execution"], "not_performed")
        self.assertEqual(executor.calls, 0)
        self.assertEqual(self.wave_store.list_jobs(), [])
        self.assertEqual(commits, [])

    # -- T08 ----------------------------------------------------------------

    def test_t08_hyperedge_hypergraph_rejects_identity_and_depth_violations(self):
        executor = RecordingExecutor()
        schema = RelationSchema(
            schema_id="math.relation.t08",
            ordered=False,
            duplicate_policy="forbid",
            directed=False,
            roles=(RoleSpec("member", min_count=1),),
            min_arity=1,
            max_arity=2,
        )
        relation = RelationRecord(
            "nml:U0:relation:t08",
            schema,
            1,
            (RelationMember(self.a.leaf_id, version=1, role="member"),),
        )
        nested = RelationRecord(
            "nml:U0:relation:t08:nested",
            schema,
            1,
            (
                RelationMember(relation.relation_id, version=1, role="member"),
                RelationMember(self.b.leaf_id, version=1, role="member"),
            ),
        )
        hypergraph = Hypergraph("hg:t08", relations=(relation,))
        self.assertEqual(
            [member.leaf_id for member in hypergraph.members_of("hg:t08")],
            [relation.relation_id],
        )
        hypergraph_leaf = hypergraph.as_relation_record().to_math_leaf(
            leaf_id="nml:U0:hypergraph:t08",
        )
        self.assertEqual(classify_leaf(hypergraph_leaf).kind, "relation")

        with self.assertRaises(RelationDuplicateError):
            Hypergraph("hg:t08:duplicate", relations=(relation, relation))
        with self.assertRaises(HypergraphError):
            Hypergraph(relation.relation_id, relations=(relation,))
        bounded = Hypergraph("hg:t08:bounded", relations=(relation, nested))
        with self.assertRaises(RelationDepthError):
            bounded.traverse(nested.relation_id, max_depth=0)

        patcher, commits = self.count_commits()
        with patcher:
            pass
        self.assertEqual(executor.calls, 0)
        self.assertEqual(self.wave_store.list_jobs(), [])
        self.assertEqual(commits, [])

    # -- T19 ----------------------------------------------------------------

    def test_t19_location_does_not_change_contract_or_dedupe_identity(self):
        first_compiled = self.compile_dot()
        second_compiled = self.compile_dot()
        self.scheduler.start(0)
        executor = RecordingExecutor()
        patcher, commits = self.count_commits()
        with patcher:
            first = self.bridge.prepare_packet(
                first_compiled,
                lane_id=0,
                request_id="worker:site-a",
            )
            second = self.bridge.prepare_packet(
                second_compiled,
                lane_id=7,
                request_id="worker:site-b",
            )

        self.assertEqual(
            first_compiled.candidate.candidate_id,
            second_compiled.candidate.candidate_id,
        )
        self.assertEqual(
            first_compiled.plan.to_dict(),
            second_compiled.plan.to_dict(),
        )
        self.assertEqual(
            first_compiled.admission.preflight_digest,
            second_compiled.admission.preflight_digest,
        )
        self.assertEqual(first.candidate_id, second.candidate_id)
        self.assertEqual(first.snapshot_id, second.snapshot_id)
        self.assertEqual(first.dedupe_key, second.dedupe_key)
        self.assertNotEqual(first.packet_id, second.packet_id)
        self.assertEqual(first.request_id, "worker:site-a")
        self.assertEqual(second.request_id, "worker:site-b")
        self.assertEqual(executor.calls, 0)
        self.assertEqual(self.wave_store.list_jobs(), [])
        self.assertEqual(commits, [])


if __name__ == "__main__":
    unittest.main()
