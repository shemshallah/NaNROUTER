"""Oracle-strength checks for the PARTIAL T/A rows in VERIFICATION_MATRIX.md.

The tests deliberately assert the object/result contract around a verdict, not
just the verdict itself, and use the production control path
(``MathRuntime`` / ``MathExecutionBridge`` / ``MathStore`` / ``WaveStore`` /
``MthSystem``) where one exists.

Covered here:
* T01/T03/T04: linker candidate output kind/shape plus VALID admission, and
  compiled-plan/result-leaf contracts for the executable dot/matvec paths.
* T05: incompatible matrix x vector is INVALID, the linker emits a typed null,
  and NMP/bridge refuse it without creating a WaveStore job.
* T09: OBJECT::VOID goes through the linker and absence algebra as a typed
  UNKNOWN/VOID/reference error; it is never a zero scalar.
* T10: a zero vector remains a present ZERO operand and dot ordering keeps the
  declared scalar result contract; no host arithmetic is performed here.
* T14: two distinct packet subscribers for one conjunction content key share
  one durable job, one executor call, one commit, and the same result digest.
* T16: experimental/level-3 admissions cannot compile or enter the production
  bridge; they remain EXPERIMENTAL and create no job.
* T20: derivational generation over a function cycle stops at depth/fuel
  bounds, reports incompleteness, and emits no duplicate proposals.
* A17: completing (but not committing) and then restarting the whole stack
  yields one COMPLETED->COMMITTED transition and one terminal job.

Not expressible with the current production APIs, therefore skipped rather
than approximated:

* T07/T08 have no linker candidate-generation seam for relation/hypergraph
  operands.  ``math_linker`` only proposes registered scalar/vector/matrix
  function candidates; relation traversal/validation is a separate module.
  A test of the full T07/T08 oracle would need new production candidate
  generation, so this file does not fake it with the relation API.
* T12's remaining item is a vocabulary freeze (preflight ``UNSUPPORTED`` vs NMP
  gate ``REJECTED``), i.e. a documentation/naming decision rather than an
  additional executable oracle.
"""

from __future__ import annotations

from dataclasses import replace
import tempfile
import unittest
from pathlib import Path

from runner_riddle import nmp
from runner_riddle.math_absence import (
    AbsenceAlgebra,
    AbsenceState,
    ConjoinPolicy,
    ObjectRef,
)
from runner_riddle.math_discovery import DiscoveryRequest, propose_derivational
from runner_riddle.math_execution import MathExecutionBridge
from runner_riddle.math_linker import propose as link_propose
from runner_riddle.math_objects import (
    MathCandidate,
    MathFunction,
    MathLeaf,
    MathRule,
    candidate_id_for,
)
from runner_riddle.math_registry import MathFunctionRegistry
from runner_riddle.math_runtime import MathRuntime, MathRuntimePlanError
from runner_riddle.math_store import MathStore
from runner_riddle.math_validity import (
    EXPERIMENTAL,
    INVALID,
    AdmissionRejected,
    MathSnapshot,
    MathValidityEngine,
    UNDEFINED,
    VALID,
)
from runner_riddle.mth_registry import MthRegistry
from runner_riddle.mth_system import MthSystem
from runner_riddle.wave_ring_scheduler import WaveRingScheduler
from runner_riddle.wave_service import WaveService
from runner_riddle.wave_store import WaveStore

from tests.test_math_end_to_end import REPO
from tests.test_math_execution import ADMIN_TOKEN, SUBMIT_TOKEN, WORKER_TOKEN

SNAP = "snp:" + "a" * 64
DIGITS = "0123456789abcdef"


def _vector_leaf(
    index: int,
    length: int = 256,
    *,
    kind: str = "vector",
    shape: tuple[int, ...] | None = None,
    metadata: dict | None = None,
    content: dict | None = None,
) -> MathLeaf:
    leaf_shape = [length] if shape is None else list(shape)
    if content is None:
        content = {
            "digest": DIGITS[index % len(DIGITS)] * 64,
            "word_count": max(1, leaf_shape[0]),
        }
    return MathLeaf(
        leaf_id=f"nml:U0:{kind}:{index}",
        kind=kind,
        type={
            "name": kind,
            "domain": "real",
            "shape": leaf_shape,
            "layout": "row_major",
            "precision": "float32",
        },
        content=content,
        metadata=metadata or {},
    )


def _matrix_leaf(index: int = 9, rows: int = 128, cols: int = 128) -> MathLeaf:
    return _vector_leaf(
        index,
        kind="matrix",
        shape=(rows, cols),
        content={"digest": DIGITS[index % len(DIGITS)] * 64,
                 "word_count": rows * cols},
    )


def _vector_endpoint(name: str, length: int = 256) -> dict:
    return {
        "name": name,
        "type": "vector",
        "domain": "real",
        "shape": [length],
        "precision": "float32",
    }


def _vector_add_contract() -> MathFunction:
    """A semantic vector-add contract with a declared (test-only) kernel row.

    The frozen manifest has no vector-add kernel; the validity oracle still
    requires an implementation declaration.  This test never executes it.
    """
    return MathFunction(
        function_id="math.vector.add",
        version=1,
        signature={
            "inputs": [_vector_endpoint("a"), _vector_endpoint("b")],
            "output": _vector_endpoint("out"),
        },
        numerical_policy={"precision": "float32", "deterministic": True},
        implementations=(
            {
                "kernel_id": "mth.vector.add256.f32",
                "capability_class": "vector.add",
                "status": "declared",
            },
        ),
        proof_status="verified",
        status="active",
    )


def _matvec_contract() -> MathFunction:
    """A 128x128 matrix-vector contract over the real native matvec kernel.

    The catalogue contract uses ``expr`` undefined-conditions that the
    validity predicate evaluator does not implement, so the executable oracle
    uses the same native kernel and shape contract with no expression
    predicates.  This is still the real kernel/plan path, not host math.
    """
    return MathFunction(
        function_id="math.vector.matvec",
        version=1,
        signature={
            "inputs": [
                {
                    "name": "matrix",
                    "type": "matrix",
                    "domain": "real",
                    "shape": [128, 128],
                    "precision": "float32",
                },
                {
                    "name": "vector",
                    "type": "vector",
                    "domain": "real",
                    "shape": [128],
                    "precision": "float32",
                },
            ],
            "output": {
                "name": "out",
                "type": "vector",
                "domain": "real",
                "shape": [128],
                "precision": "float32",
            },
        },
        numerical_policy={"precision": "float32", "deterministic": True},
        implementations=(
            {
                "kernel_id": "mth.matvec.128.f32",
                "capability_class": "matrix.matvec",
            },
        ),
        proof_status="verified",
        status="active",
    )


def _pin(leaf: MathLeaf) -> dict:
    return {
        "leaf_id": leaf.leaf_id,
        "version": leaf.version,
        "content_digest": leaf.content_digest,
        "kind": leaf.kind,
        "type": dict(leaf.type),
        "status": leaf.status,
        "workspace_words": int((leaf.content or {}).get("word_count", 0)),
    }


def _candidate_for(
    function: MathFunction,
    leaves: tuple[MathLeaf, ...],
    *,
    snapshot_id: str = SNAP,
) -> MathCandidate:
    inputs = tuple(
        {
            "leaf_id": leaf.leaf_id,
            "version": leaf.version,
            "content_digest": leaf.content_digest,
        }
        for leaf in leaves
    )
    return MathCandidate(
        candidate_id_for(
            snapshot_id, inputs, function.function_id, function.version,
        ),
        inputs,
        function.function_id,
        function.version,
        snapshot_id=snapshot_id,
    )


class MathVerificationExtraTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.native = MthRegistry.load(REPO / "spec" / "wave-capabilities.json")
        catalog = MathFunctionRegistry.load(
            REPO / "spec" / "math-functions.v1.json",
            implementations=cls.native,
        )
        cls.dot = next(
            item for item in catalog.functions
            if item.function_id == "math.vector.dot"
        )
        cls.matvec = _matvec_contract()
        cls.dot_kernel = "mth.vector.dot256.f32"
        cls.matvec_kernel = "mth.matvec.128.f32"

    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)
        self.math_bs_path = self.root / "bs0.sqlite3"
        self.math_mc_path = self.root / "mc0.sqlite3"
        self.wave_bs_path = self.root / "wave-bs.sqlite3"
        self.wave_mc_path = self.root / "wave-mc.sqlite3"

        self.math_store = MathStore(self.math_bs_path, self.math_mc_path)
        self.a = self.math_store.put_leaf(_vector_leaf(1))
        self.b = self.math_store.put_leaf(_vector_leaf(2))
        self.matrix = self.math_store.put_leaf(_matrix_leaf())
        self.vector128 = self.math_store.put_leaf(
            _vector_leaf(3, length=128)
        )
        self.wrong_vector = self.math_store.put_leaf(
            _vector_leaf(4, length=3)
        )
        self.zero_vector = self.math_store.put_leaf(
            _vector_leaf(
                5,
                content={"canonical": "0", "word_count": 256},
                metadata={"absence_state": "ZERO"},
            )
        )
        self.void_leaf = self.math_store.put_leaf(
            MathLeaf(
                leaf_id="nml:U0:void:1",
                kind="void",
                type={
                    "name": "void",
                    "domain": "none",
                    "shape": [],
                    "layout": "none",
                    "precision": "none",
                },
                metadata={
                    "reason": "NO_OBJECT",
                    "failure_class": "NO_OBJECT",
                },
            )
        )

        self.wave_store = WaveStore(self.wave_bs_path, self.wave_mc_path)
        self.service = WaveService(
            self.wave_store, SUBMIT_TOKEN, WORKER_TOKEN, ADMIN_TOKEN,
        )
        self.scheduler = WaveRingScheduler(cycle_ticks=10, now_tick=0)
        self.system = MthSystem(
            self.native, self.wave_store, self.service, self.scheduler,
        )
        self.runtime = self._make_runtime((self.dot,))
        self.bridge = self._make_bridge(self.runtime)

    # -- helpers ------------------------------------------------------------

    def _make_runtime(self, functions, **kwargs) -> MathRuntime:
        registry = MathFunctionRegistry(tuple(functions), self.native)
        return MathRuntime(
            registry,
            store=self.math_store,
            system=self.system,
            **kwargs,
        )

    @staticmethod
    def _make_bridge(runtime: MathRuntime) -> MathExecutionBridge:
        return MathExecutionBridge(
            runtime,
            runtime.system,
            submit_token=SUBMIT_TOKEN,
            worker_token=WORKER_TOKEN,
        )

    def _compile_dot(self, runtime: MathRuntime) -> object:
        result = runtime.propose(
            [f"{self.a.leaf_id}@v1", f"{self.b.leaf_id}@v1"],
            snapshot_id=SNAP,
            max_candidates=8,
        )
        candidate = next(
            item for item in result.items
            if item.function_id == "math.vector.dot"
        )
        admission = runtime.preflight(candidate)
        self.assertEqual(admission.verdict, VALID)
        return runtime.compile(candidate, admission)

    def _register_dot_capability(self, wave_store: WaveStore) -> dict:
        descriptor = self.native.require(self.dot_kernel)
        return wave_store.register_capability(
            kernel_id=descriptor.kernel_id,
            runner_id="NANROUTER-0",
            verified_digest=descriptor.source_digest,
            workspace=1,
            precision=descriptor.precision,
            status="native_verified",
            epoch=1,
        )

    def _build_stack(self):
        """Rebuild every process-local object over the same durable paths."""
        wave_store = WaveStore(self.wave_bs_path, self.wave_mc_path)
        service = WaveService(
            wave_store, SUBMIT_TOKEN, WORKER_TOKEN, ADMIN_TOKEN,
        )
        scheduler = WaveRingScheduler(cycle_ticks=10, now_tick=0)
        system = MthSystem(self.native, wave_store, service, scheduler)
        math_store = MathStore(self.math_bs_path, self.math_mc_path)
        runtime = MathRuntime(
            MathFunctionRegistry((self.dot,), self.native),
            store=math_store,
            system=system,
        )
        bridge = MathExecutionBridge(
            runtime,
            system,
            submit_token=SUBMIT_TOKEN,
            worker_token=WORKER_TOKEN,
        )
        return wave_store, scheduler, runtime, bridge

    @staticmethod
    def _commit_transitions(transitions) -> list[tuple[str, str]]:
        return [
            (row["from_state"], row["to_state"])
            for row in transitions
            if row["to_state"] == "COMMITTED"
        ]

    # -- T01/T03/T04 --------------------------------------------------------

    def test_t01_vector_add_is_valid_with_vector_result_contract(self):
        add = _vector_add_contract()
        links = link_propose(
            (self.a, self.b),
            registry=(add,),
            snapshot_id=SNAP,
        )
        self.assertEqual(links.candidate_count, 1)
        candidate = links.candidates[0]
        self.assertEqual(candidate.function_id, add.function_id)
        self.assertEqual(len(candidate.outputs), 1)
        output = candidate.outputs[0]
        self.assertEqual(output["kind"], "vector")
        self.assertEqual(output["shape"], [256])
        self.assertEqual(output["precision"], "float32")
        self.assertEqual(links.functions[0]["result_type"], "vector")

        engine = MathValidityEngine(MathSnapshot(
            snapshot_id=SNAP,
            functions=(add,),
            leaf_pins=(_pin(self.a), _pin(self.b)),
        ))
        admission = engine.preflight(candidate)
        self.assertEqual(admission.verdict, VALID)
        self.assertEqual(admission.reason, "")
        self.assertEqual(admission.scope["math_verdict"], VALID)
        checked = {row["check"] for row in admission.scope["checks"]}
        self.assertIn("output", checked)

    def test_t03_dot_is_valid_and_compiles_to_a_scalar_leaf_contract(self):
        runtime = self._make_runtime((self.dot,))
        links = runtime.propose(
            [f"{self.a.leaf_id}@v1", f"{self.b.leaf_id}@v1"],
            snapshot_id=SNAP,
            max_candidates=8,
        )
        candidate = next(
            item for item in links.items
            if item.function_id == "math.vector.dot"
        )
        self.assertEqual(len(candidate.outputs), 1)
        output = candidate.outputs[0]
        self.assertEqual(output["kind"], "scalar")
        self.assertEqual(output["shape"], [])
        self.assertEqual(output["precision"], "float32")
        self.assertEqual(links.functions[0]["result_type"], "scalar")

        admission = runtime.preflight(candidate)
        self.assertEqual(admission.verdict, VALID)
        checked = {row["check"] for row in admission.scope["checks"]}
        self.assertIn("output", checked)
        compiled = runtime.compile(candidate, admission)
        self.assertEqual(compiled.plan.kernel_ids, (self.dot_kernel,))
        self.assertEqual(compiled.function.signature["output"]["type"], "scalar")
        packet = runtime.prepare_packet(compiled)
        self.assertEqual(packet.state, nmp.PREFLIGHTED)
        self.assertEqual(packet.candidate_id, candidate.candidate_id)

    def test_t04_matrix_vector_is_valid_with_vector_result_contract(self):
        runtime = self._make_runtime((self.matvec,))
        links = runtime.propose(
            [f"{self.matrix.leaf_id}@v1", f"{self.vector128.leaf_id}@v1"],
            snapshot_id=SNAP,
            max_candidates=8,
        )
        candidate = next(
            item for item in links.items
            if item.function_id == "math.vector.matvec"
        )
        self.assertEqual(len(candidate.outputs), 1)
        output = candidate.outputs[0]
        self.assertEqual(output["kind"], "vector")
        self.assertEqual(output["shape"], [128])
        self.assertEqual(output["precision"], "float32")
        self.assertEqual(links.functions[0]["result_type"], "vector")

        admission = runtime.preflight(candidate)
        self.assertEqual(admission.verdict, VALID)
        checked = {row["check"] for row in admission.scope["checks"]}
        self.assertIn("output", checked)
        compiled = runtime.compile(candidate, admission)
        self.assertEqual(compiled.plan.kernel_ids, (self.matvec_kernel,))
        self.assertEqual(
            compiled.function.signature["output"]["type"], "vector",
        )
        packet = runtime.prepare_packet(compiled)
        self.assertEqual(packet.state, nmp.PREFLIGHTED)
        self.assertEqual(packet.candidate_id, candidate.candidate_id)

    # -- T05 ----------------------------------------------------------------

    def test_t05_incompatible_matvec_is_invalid_typed_null_and_not_run(self):
        runtime = self._make_runtime((self.matvec,))
        links = runtime.propose(
            [f"{self.matrix.leaf_id}@v1", f"{self.wrong_vector.leaf_id}@v1"],
            snapshot_id=SNAP,
            max_candidates=8,
        )
        self.assertEqual(links.candidate_count, 0)
        self.assertIsNotNone(links.null)
        typed_null = links.null
        self.assertEqual(typed_null.kind, "null")
        self.assertIsNone(typed_null.content)
        self.assertEqual(typed_null.metadata["reason"], "DIMENSION_MISMATCH")
        self.assertEqual(
            typed_null.metadata["failure_class"], "DIMENSION_MISMATCH",
        )
        self.assertNotIn(typed_null.kind, {"scalar", "vector", "matrix"})
        self.assertNotEqual(typed_null.to_dict(), self.zero_vector.to_dict())

        candidate = _candidate_for(
            self.matvec, (self.matrix, self.wrong_vector),
        )
        admission = runtime.preflight(candidate)
        self.assertEqual(admission.verdict, INVALID)
        self.assertEqual(admission.reason, "SHAPE_MISMATCH")
        self.assertNotIn(admission.verdict, {UNDEFINED, "NULL", "VOID"})

        packet = nmp.prepare(candidate, admission)
        self.assertEqual(packet.state, nmp.REJECTED)
        self.assertEqual(packet.admission_verdict, INVALID)
        bridge = self._make_bridge(runtime)
        decision = bridge.check(packet)
        self.assertFalse(decision.ok)
        self.assertEqual(decision.failure, nmp.REJECTED)
        self.assertEqual(self.wave_store.list_jobs(), [])

    # -- T09 ----------------------------------------------------------------

    def test_t09_object_void_is_typed_absence_never_zero(self):
        runtime = self._make_runtime((self.dot,))
        links = runtime.propose(
            (self.a, self.void_leaf),
            snapshot_id=SNAP,
            max_candidates=8,
        )
        self.assertEqual(links.candidate_count, 0)
        self.assertIsNotNone(links.null)
        self.assertEqual(links.null.kind, "null")
        self.assertIsNone(links.null.content)
        self.assertEqual(links.null.metadata["reason"], "INPUT_VOID")
        self.assertEqual(
            links.null.metadata["failure_class"], "INPUT_VOID",
        )
        self.assertNotIn(
            links.null.metadata["reason"],
            {"ZERO", "NULL", "EMPTY"},
        )

        algebra = AbsenceAlgebra()
        object_ref = ObjectRef(
            leaf_id=self.a.leaf_id,
            version=self.a.version,
            content_digest=self.a.content_digest,
            kind=self.a.kind,
            type=dict(self.a.type),
            content=dict(self.a.content or {}),
        )
        deferred = algebra.conjoin(object_ref, "VOID")
        self.assertIs(deferred.state, AbsenceState.UNKNOWN)
        self.assertEqual(deferred.reason, "VOID_INPUT_MAY_ARRIVE")
        self.assertFalse(deferred.present)
        self.assertFalse(deferred.candidates_allowed)
        self.assertNotEqual(deferred.state, AbsenceState.ZERO)

        strict = algebra.conjoin(
            object_ref, "VOID", policy=ConjoinPolicy.strict(),
        )
        self.assertIs(strict.state, AbsenceState.VOID)
        self.assertTrue(strict.reference_error)
        self.assertFalse(strict.present)
        self.assertNotEqual(strict.state, AbsenceState.ZERO)
        self.assertIsNone(strict.value)

    # -- T10 ----------------------------------------------------------------

    def test_t10_zero_vector_dot_keeps_valid_scalar_zero_semantics(self):
        algebra = AbsenceAlgebra()
        zero_operand = algebra.classify(self.zero_vector)
        self.assertIs(zero_operand.state, AbsenceState.ZERO)
        self.assertTrue(zero_operand.present)
        self.assertTrue(zero_operand.is_zero)
        self.assertEqual(zero_operand.record.value["canonical"], "0")
        self.assertIsNotNone(zero_operand.record.value)

        runtime = self._make_runtime((self.dot,))
        links = runtime.propose(
            [f"{self.zero_vector.leaf_id}@v1", f"{self.b.leaf_id}@v1"],
            snapshot_id=SNAP,
            max_candidates=8,
        )
        candidate = next(
            item for item in links.items
            if item.function_id == "math.vector.dot"
        )
        self.assertEqual(candidate.outputs[0]["kind"], "scalar")
        self.assertEqual(candidate.outputs[0]["shape"], [])
        admission = runtime.preflight(candidate)
        self.assertEqual(admission.verdict, VALID)
        self.assertNotEqual(admission.verdict, UNDEFINED)
        self.assertNotIn(admission.verdict, {INVALID, "NULL", "VOID"})
        self.assertEqual(admission.scope["math_verdict"], VALID)
        self.assertNotIn(
            algebra.classify(self.zero_vector).state,
            {AbsenceState.NULL, AbsenceState.VOID, AbsenceState.UNDEFINED},
        )

    # -- T14 ----------------------------------------------------------------

    def test_t14_duplicate_conjunction_shares_one_execution_and_result(self):
        compiled = self._compile_dot(self.runtime)
        self._register_dot_capability(self.wave_store)
        self.scheduler.start(0)
        first_packet = self.bridge.prepare_packet(
            compiled, lane_id=0, request_id="subscriber-one",
        )
        second_packet = self.bridge.prepare_packet(
            compiled, lane_id=1, request_id="subscriber-two",
        )
        self.assertEqual(first_packet.dedupe_key, second_packet.dedupe_key)
        self.assertNotEqual(first_packet.packet_id, second_packet.packet_id)

        first = self.bridge.submit(first_packet, compiled, now_tick=0)
        second = self.bridge.submit(second_packet, compiled, now_tick=0)
        self.assertFalse(first.duplicate)
        self.assertTrue(second.duplicate)
        self.assertEqual(second.job_id, first.job_id)
        self.assertEqual(second.subscribers, (second_packet.packet_id,))
        self.assertEqual(len(self.wave_store.list_jobs()), 1)

        calls: list[str] = []
        result_digest = "d" * 64

        def executor() -> str:
            calls.append("called")
            return result_digest

        lease = self.bridge.lease(first, now_tick=0)
        self.assertIsNotNone(lease)
        result = self.bridge.execute(
            lease, executor, now_tick=1, commit=True,
        )
        self.assertEqual(calls, ["called"])
        self.assertEqual(result.state, nmp.COMMITTED)
        self.assertTrue(result.committed)
        self.assertEqual(result.result_digest, result_digest)

        transitions = self.math_store.list_nmp_transitions(first_packet.packet_id)
        self.assertEqual(
            self._commit_transitions(transitions),
            [("COMPLETED", "COMMITTED")],
        )
        self.assertEqual(len(self.wave_store.list_jobs()), 1)

        late = self.bridge.submit(second_packet, compiled, now_tick=2)
        self.assertTrue(late.duplicate)
        self.assertEqual(late.job_id, first.job_id)
        self.assertEqual(late.job["state"], "done")
        self.assertEqual(late.result_digest, result_digest)

        projection = self.bridge.project(second_packet, now_tick=2)
        self.assertTrue(projection.supported)
        self.assertEqual(projection.result_digest, result_digest)
        restarted = self.bridge.restart(second_packet, tick=2)
        self.assertEqual(restarted.result_digest, result_digest)
        self.assertEqual(len(self._commit_transitions(
            self.math_store.list_nmp_transitions(first_packet.packet_id)
        )), 1)
        self.assertEqual(len(self.wave_store.list_jobs()), 1)

    # -- T16 ----------------------------------------------------------------

    def test_t16_experimental_and_level3_cannot_enter_production(self):
        experimental_dot = replace(
            self.dot,
            semantics={**dict(self.dot.semantics), "experimental": True},
            contract_digest=None,
        )
        runtime = self._make_runtime((experimental_dot,))
        links = runtime.propose(
            [f"{self.a.leaf_id}@v1", f"{self.b.leaf_id}@v1"],
            snapshot_id=SNAP,
            max_candidates=8,
        )
        candidate = links.candidates[0]
        admission = runtime.preflight(candidate)
        self.assertEqual(admission.verdict, EXPERIMENTAL)
        self.assertEqual(admission.reason, "LEVEL3_ISOLATION")
        self.assertTrue(admission.scope["isolated"])
        with self.assertRaises(AdmissionRejected) as raised:
            runtime.validity.require_admission(admission)
        self.assertEqual(raised.exception.verdict, EXPERIMENTAL)
        self.assertEqual(
            raised.exception.reason, "EXPERIMENTAL_NOT_EXECUTABLE",
        )
        with self.assertRaises(MathRuntimePlanError):
            runtime.compile(candidate, admission)
        packet = nmp.prepare(candidate, admission)
        self.assertEqual(packet.state, EXPERIMENTAL)
        self.assertEqual(packet.admission_verdict, EXPERIMENTAL)
        bridge = self._make_bridge(runtime)
        decision = bridge.check(packet)
        self.assertFalse(decision.ok)
        self.assertIn(decision.failure, {nmp.REJECTED, nmp.EXPERIMENTAL})
        self.assertEqual(self.wave_store.list_jobs(), [])

        rule = MathRule(
            rule_id="math.rule.experimental.dot",
            version=1,
            level=3,
            contract={"claims": {}},
            proof_status="verified",
            status="active",
            scope={"function_ids": ["math.vector.dot"]},
        )
        scoped_dot = replace(
            self.dot,
            semantics={
                **dict(self.dot.semantics),
                "rule_ids": [rule.rule_id],
            },
            contract_digest=None,
        )

        class RuleProvider:
            @staticmethod
            def active_rules(*, include_isolated: bool = False):
                return (rule,)

        runtime = self._make_runtime(
            (scoped_dot,), rule_provider=RuleProvider(),
        )
        links = runtime.propose(
            [f"{self.a.leaf_id}@v1", f"{self.b.leaf_id}@v1"],
            snapshot_id=SNAP,
            max_candidates=8,
        )
        candidate = links.candidates[0]
        admission = runtime.preflight(candidate)
        self.assertEqual(admission.verdict, EXPERIMENTAL)
        self.assertEqual(admission.scope["rule_level"], 3)
        self.assertTrue(admission.scope["isolated"])
        with self.assertRaises(AdmissionRejected):
            runtime.validity.require_admission(admission)
        with self.assertRaises(MathRuntimePlanError):
            runtime.compile(candidate, admission)
        packet = nmp.prepare(candidate, admission)
        self.assertEqual(packet.state, EXPERIMENTAL)
        bridge = self._make_bridge(runtime)
        decision = bridge.check(packet)
        self.assertFalse(decision.ok)
        self.assertEqual(self.wave_store.list_jobs(), [])

    # -- T20 ----------------------------------------------------------------

    def test_t20_bounded_recursive_generation_stops_at_depth_and_fuel(self):
        def unary(index: int) -> MathFunction:
            endpoint = _vector_endpoint("x", length=4)
            return MathFunction(
                function_id=f"math.test.cycle{index}",
                version=1,
                signature={
                    "inputs": [endpoint],
                    "output": _vector_endpoint("out", length=4),
                },
                numerical_policy={
                    "precision": "float32",
                    "deterministic": True,
                },
                proof_status="tested",
                status="active",
            )

        functions = tuple(unary(index) for index in range(1, 5))
        request = DiscoveryRequest(
            functions=functions,
            bounds={
                "max_proposals": 64,
                "max_fanout": 8,
                "max_depth": 2,
                "fuel": 256,
            },
        )
        result = propose_derivational(request)
        self.assertLessEqual(result.fuel_used, request.bounds.fuel)
        self.assertGreater(result.proposal_count, 0)
        self.assertEqual(
            len(result.proposal_ids), len(set(result.proposal_ids)),
        )
        self.assertEqual(
            len(result.proposals),
            len({proposal.content_key for proposal in result.proposals}),
        )
        for proposal in result.proposals:
            self.assertEqual(proposal.mechanism, "derivational")
            self.assertLessEqual(
                proposal.evidence["depth"], request.bounds.max_depth,
            )
            self.assertLessEqual(
                len(proposal.evidence["components"]),
                request.bounds.max_depth + 1,
            )

        depth_zero = propose_derivational(DiscoveryRequest(
            functions=functions,
            bounds={"max_depth": 0, "max_fanout": 8, "fuel": 64},
        ))
        self.assertEqual(depth_zero.proposal_count, 0)
        self.assertIn("depth_limit", depth_zero.incomplete_reasons)

        fuel_bound = propose_derivational(DiscoveryRequest(
            functions=functions,
            bounds={"max_depth": 32, "max_fanout": 64, "fuel": 5},
        ))
        self.assertLessEqual(fuel_bound.fuel_used, 5)
        self.assertIn("fuel_exhausted", fuel_bound.incomplete_reasons)

    # -- A17 ----------------------------------------------------------------

    def test_a17_complete_then_crash_before_commit_has_one_terminal_commit(self):
        compiled = self._compile_dot(self.runtime)
        self._register_dot_capability(self.wave_store)
        self.scheduler.start(0)
        packet = self.bridge.prepare_packet(compiled)
        submission = self.bridge.submit(packet, compiled, now_tick=0)
        lease = self.bridge.lease(submission, now_tick=0)
        self.assertIsNotNone(lease)
        calls: list[str] = []
        result_digest = "e" * 64

        def executor() -> str:
            calls.append("called")
            return result_digest

        completed = self.bridge.execute(
            lease, executor, now_tick=1, commit=False,
        )
        self.assertEqual(calls, ["called"])
        self.assertEqual(completed.state, nmp.COMPLETED)
        self.assertFalse(completed.committed)
        self.assertEqual(completed.job_state, "done")
        before = self.math_store.list_nmp_transitions(packet.packet_id)
        self.assertEqual(self._commit_transitions(before), [])
        self.assertEqual(
            [(row["from_state"], row["to_state"]) for row in before],
            [
                ("PREFLIGHTED", "QUEUED"),
                ("QUEUED", "EXECUTING"),
                ("EXECUTING", "COMPLETED"),
            ],
        )

        # Process dies here.  A fresh store/system/runtime/bridge represents
        # restart recovery; only durable WaveStore/MathStore rows survive.
        wave_store, scheduler, _runtime, restarted_bridge = self._build_stack()
        scheduler.start(0)
        recovered = restarted_bridge.restart(completed.packet, tick=2)
        self.assertEqual(recovered.state, nmp.COMPLETED)
        self.assertEqual(recovered.result_digest, result_digest)
        self.assertEqual(recovered.job_id, submission.job_id)

        committed = restarted_bridge.complete(
            recovered,
            result_digest,
            now_tick=2,
            commit=True,
        )
        self.assertEqual(committed.state, nmp.COMMITTED)
        self.assertTrue(committed.committed)
        self.assertTrue(committed.duplicate)
        self.assertEqual(committed.result_digest, result_digest)
        after = self.math_store.list_nmp_transitions(packet.packet_id)
        self.assertEqual(
            self._commit_transitions(after),
            [("COMPLETED", "COMMITTED")],
        )
        self.assertEqual(
            [row["to_state"] for row in after].count(nmp.COMMITTED), 1,
        )
        self.assertEqual(len(wave_store.list_jobs()), 1)

        replay = restarted_bridge.complete(
            committed.packet,
            result_digest,
            now_tick=3,
            commit=True,
        )
        self.assertEqual(replay.state, nmp.COMMITTED)
        self.assertTrue(replay.committed)
        self.assertTrue(replay.duplicate)
        self.assertEqual(len(self._commit_transitions(
            self.math_store.list_nmp_transitions(packet.packet_id)
        )), 1)
        jobs = wave_store.list_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["job_id"], submission.job_id)
        self.assertEqual(jobs[0]["state"], "done")
        self.assertEqual(jobs[0]["result_digest"], result_digest)


if __name__ == "__main__":
    unittest.main()
