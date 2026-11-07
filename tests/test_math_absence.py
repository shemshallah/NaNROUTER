from __future__ import annotations

from pathlib import Path
import unittest

from runner_riddle.math_absence import (
    ABSENCE_CLASSIFICATION_SCHEMA,
    ABSENCE_REQUIRED_SCHEMA,
    ABSENCE_SCHEMA,
    ABSENT_STATES,
    ALL_STATES,
    AbsenceAlgebra,
    AbsenceError,
    AbsenceRecord,
    AbsenceRequiredError,
    AbsenceState,
    ClassifiedOperand,
    ConjoinPolicy,
    ConjunctionResult,
    DEFAULT_RULE_SNAPSHOT,
    EMPTY_KINDS,
    FAILURE_CLASSES,
    FailureClass,
    MissingReference,
    MissingReferenceError,
    ObjectRef,
    PRESENT_STATES,
    SnapshotMismatchError,
    canonical_json,
)
from runner_riddle.math_objects import MathLeaf, MathObjectError

RULE_SNAPSHOT = {"rule_snapshot_id": "math.rules.absence.test", "version": 7}
PARENT = {"leaf_id": "nml:U0:vector:parent", "version": 2, "role": "input"}
VECTOR_ID = "nml:U0:vector:present"
VECTOR_REF = ObjectRef(
    leaf_id=VECTOR_ID,
    version=4,
    content_digest="a" * 64,
    kind="vector",
    type={"name": "vector", "domain": "real", "shape": [256]},
    content={"digest": "a" * 64, "word_count": 256},
    parents=(PARENT,),
)
MISSING_ID = "nml:U0:vector:missing"


def algebra() -> AbsenceAlgebra:
    return AbsenceAlgebra(rule_snapshot=RULE_SNAPSHOT)


def classify(state, **kwargs):
    return algebra().classify(state, rule_snapshot=RULE_SNAPSHOT, **kwargs)


class StateContractTests(unittest.TestCase):
    def test_all_nine_states_are_distinct_and_valid(self):
        self.assertEqual(len(ALL_STATES), 9)
        self.assertEqual(
            {state.value for state in ALL_STATES},
            {
                "ZERO", "NULL", "VOID", "EMPTY", "UNDEFINED",
                "INFINITY", "UNKNOWN", "ERROR", "CANCELLED",
            },
        )
        self.assertEqual(PRESENT_STATES, {
            AbsenceState.ZERO, AbsenceState.EMPTY, AbsenceState.INFINITY,
        })
        self.assertEqual(ABSENT_STATES, {
            AbsenceState.NULL, AbsenceState.VOID, AbsenceState.UNDEFINED,
            AbsenceState.UNKNOWN, AbsenceState.ERROR, AbsenceState.CANCELLED,
        })
        self.assertFalse(PRESENT_STATES & ABSENT_STATES)
        self.assertEqual(PRESENT_STATES | ABSENT_STATES, frozenset(ALL_STATES))

    def test_state_parser_is_strict(self):
        for state in ALL_STATES:
            self.assertIs(AbsenceState.parse(state), state)
            self.assertIs(AbsenceState.parse(state.value), state)
        for bad in ("NAN", "null", "Any", "OBJECT", "", "ZERO "):
            with self.assertRaises(AbsenceError):
                AbsenceState.parse(bad)
            with self.assertRaises(AbsenceError):
                algebra().classify(bad, reason="bad")

    def test_state_presence_and_failure_contract(self):
        alg = algebra()
        for state in ALL_STATES:
            operand = alg.classify(state, reason=f"reason:{state.value}")
            self.assertIs(operand.state, state)
            if state in PRESENT_STATES:
                self.assertTrue(operand.present)
                self.assertIsNone(operand.failure_class)
                self.assertIsNotNone(operand.record.value)
            else:
                self.assertFalse(operand.present)
                self.assertIn(operand.failure_class, FAILURE_CLASSES)
                self.assertIsNone(operand.record.value)

    def test_each_present_state_has_a_nonsemantic_descriptor(self):
        alg = algebra()
        zero = alg.classify("ZERO")
        empty = alg.classify("EMPTY")
        infinity = alg.classify("INFINITY")
        self.assertEqual(zero.record.value["canonical"], "0")
        self.assertEqual(empty.record.value["kind"], "vector")
        self.assertTrue(empty.record.value["empty"])
        self.assertEqual(empty.record.value["shape"], [0])
        self.assertEqual(infinity.record.value["canonical"], "+inf")
        self.assertEqual(infinity.record.value["domain"], "extended_real")
        self.assertIn(empty.record.value["kind"], EMPTY_KINDS)

    def test_present_states_cannot_carry_failure_class(self):
        for state in PRESENT_STATES:
            with self.assertRaises(AbsenceError):
                algebra().classify(state, failure_class=FailureClass.NO_VALID_RESULT.value)

    def test_absent_failure_classes_are_closed_and_distinct(self):
        expected = {
            AbsenceState.NULL: FailureClass.NO_VALID_RESULT.value,
            AbsenceState.VOID: FailureClass.NO_OBJECT.value,
            AbsenceState.UNDEFINED: FailureClass.MATHEMATICALLY_UNDEFINED.value,
            AbsenceState.UNKNOWN: FailureClass.NOT_ESTABLISHED.value,
            AbsenceState.ERROR: FailureClass.EXECUTION_FAILED.value,
            AbsenceState.CANCELLED: FailureClass.CANCELLED.value,
        }
        alg = algebra()
        for state, failure in expected.items():
            self.assertEqual(alg.classify(state).failure_class, failure)
        with self.assertRaises(AbsenceError):
            alg.classify("NULL", failure_class="DIV_ZERO")

    def test_unknown_error_and_cancelled_are_not_undefined(self):
        alg = algebra()
        self.assertEqual(alg.classify("UNDEFINED").failure_class,
                         FailureClass.MATHEMATICALLY_UNDEFINED.value)
        self.assertEqual(alg.classify("ERROR").failure_class,
                         FailureClass.EXECUTION_FAILED.value)
        self.assertEqual(alg.classify("CANCELLED").failure_class,
                         FailureClass.CANCELLED.value)
        self.assertNotEqual(alg.classify("ERROR").failure_class,
                            alg.classify("UNDEFINED").failure_class)
        self.assertNotEqual(alg.classify("CANCELLED").failure_class,
                            alg.classify("ERROR").failure_class)

    def test_null_cannot_carry_a_zero_or_any_value(self):
        alg = algebra()
        with self.assertRaises(AbsenceError):
            AbsenceRecord(
                state="NULL",
                reason="NO_VALID_RESULT",
                value={"canonical": "0"},
            )
        with self.assertRaises(AbsenceError):
            alg.classify("NULL", value_descriptor={"canonical": "0"})
        with self.assertRaises(AbsenceError):
            AbsenceRecord(
                state="VOID",
                reason="NO_OBJECT",
                value={"kind": "vector", "shape": [0], "count": 0},
            )

    def test_zero_and_infinity_descriptors_are_strict(self):
        with self.assertRaises(AbsenceError):
            AbsenceRecord(state="ZERO", reason="Z", value={"canonical": "1"})
        with self.assertRaises(AbsenceError):
            AbsenceRecord(state="INFINITY", reason="I", value={"canonical": "nan"})
        with self.assertRaises(AbsenceError):
            AbsenceRecord(state="INFINITY", reason="I", value={"canonical": "inf"})
        minus = AbsenceRecord(
            state="INFINITY", reason="NEG_INF",
            value={"canonical": "-inf"},
        )
        self.assertEqual(minus.value["domain"], "extended_real")

    def test_empty_requires_zero_extent(self):
        with self.assertRaises(AbsenceError):
            AbsenceRecord(
                state="EMPTY",
                reason="NOT_EMPTY",
                value={"kind": "vector", "shape": [2], "count": 2},
            )
        with self.assertRaises(AbsenceError):
            AbsenceRecord(
                state="EMPTY",
                reason="BAD_KIND",
                value={"kind": "scalar", "shape": [0], "count": 0},
            )
        record = AbsenceRecord(
            state="EMPTY", reason="EMPTY_MATRIX",
            value={"kind": "matrix", "shape": [0, 256], "count": 0},
        )
        self.assertTrue(record.is_present)


class ClassificationTests(unittest.TestCase):
    def test_classify_state_string_and_enum(self):
        alg = algebra()
        a = alg.classify("EMPTY")
        b = alg.classify(AbsenceState.EMPTY)
        self.assertEqual(a.to_dict(), b.to_dict())
        self.assertIs(a.state, AbsenceState.EMPTY)

    def test_classify_none_is_not_void(self):
        with self.assertRaises(AbsenceError) as caught:
            algebra().classify(None)
        self.assertIn("MissingReference", str(caught.exception))
        with self.assertRaises(AbsenceError):
            algebra().classify({"state": "VOID", "reason": None})

    def test_classify_resolved_object_is_present_without_state(self):
        operand = algebra().classify(VECTOR_REF)
        self.assertIsNone(operand.state)
        self.assertTrue(operand.present)
        self.assertEqual(operand.leaf_id, VECTOR_ID)
        self.assertEqual(operand.version, 4)
        self.assertIsNone(operand.record)
        self.assertIsNotNone(operand.ref)

    def test_classify_missing_reference_is_typed_void_reference_error(self):
        missing = MissingReference(
            MISSING_ID, version=3, reason="PAYLOAD_NOT_FOUND",
            parents=(PARENT,),
        )
        operand = algebra().classify(missing)
        self.assertIs(operand.state, AbsenceState.VOID)
        self.assertFalse(operand.present)
        self.assertTrue(operand.reference_error)
        self.assertEqual(operand.failure_class, FailureClass.MISSING_REFERENCE.value)
        self.assertEqual(operand.reason, "PAYLOAD_NOT_FOUND")
        self.assertIsNone(operand.record.value)
        self.assertIsNone(operand.record.leaf_id)
        self.assertEqual(operand.record.metadata["missing_leaf_id"], MISSING_ID)

    def test_missing_reference_rejects_non_missing_failure_class(self):
        with self.assertRaises(AbsenceError):
            MissingReference(MISSING_ID, failure_class=FailureClass.NO_OBJECT.value)

    def test_classify_serialized_record_and_leaf(self):
        alg = algebra()
        record = alg.classify(
            "UNDEFINED", reason="DIVISION_BY_ZERO", parents=(PARENT,),
        ).record
        restored_record = alg.classify(record.to_dict())
        self.assertEqual(restored_record.record.to_dict(), record.to_dict())
        leaf = alg.to_leaf(record)
        restored_leaf = alg.classify(leaf.to_dict())
        self.assertIs(restored_leaf.state, AbsenceState.UNDEFINED)
        self.assertEqual(restored_leaf.reason, "DIVISION_BY_ZERO")
        self.assertEqual(restored_leaf.parents, (dict(PARENT),))

    def test_classify_empty_math_leaf_from_zero_shape(self):
        leaf = MathLeaf(
            leaf_id="nml:U0:vector:empty",
            kind="vector",
            type={"name": "vector", "domain": "real", "shape": [0, 256]},
            content={"word_count": 0},
        )
        operand = algebra().classify(leaf)
        self.assertIs(operand.state, AbsenceState.EMPTY)
        self.assertTrue(operand.present)
        self.assertEqual(operand.record.value["shape"], [0, 256])

    def test_classify_rejects_untyped_values(self):
        for value in (0, 0.0, False, [], object()):
            with self.assertRaises(AbsenceError):
                algebra().classify(value)


class ConjunctionTests(unittest.TestCase):
    def assertOutcome(self, result, state, present, candidates, **kwargs):
        self.assertIsInstance(result, ConjunctionResult)
        self.assertIs(result.state, state)
        self.assertEqual(result.present, present)
        self.assertEqual(result.candidates_allowed, candidates)
        for key, value in kwargs.items():
            self.assertEqual(getattr(result, key), value)

    def test_object_object_proceeds_without_absence(self):
        result = algebra().conjoin(VECTOR_REF, VECTOR_REF)
        self.assertOutcome(result, None, True, True)
        self.assertEqual(result.reason, "OPERANDS_PRESENT")
        self.assertEqual(len(result.operands), 2)

    def test_zero_object_and_zero_zero_are_not_null(self):
        alg = algebra()
        result = alg.conjoin("ZERO", VECTOR_REF)
        self.assertOutcome(result, None, True, True)
        self.assertIsNot(result.state, AbsenceState.NULL)
        self.assertIn(VECTOR_ID, [p.get("leaf_id") for p in result.parents])
        zero_zero = alg.conjoin("ZERO", "ZERO")
        self.assertOutcome(zero_zero, None, True, True)
        self.assertNotEqual(zero_zero.state, AbsenceState.NULL)

    def test_empty_object_and_empty_empty_proceed_as_empty(self):
        alg = algebra()
        one = alg.conjoin("EMPTY", VECTOR_REF)
        self.assertOutcome(one, AbsenceState.EMPTY, True, True)
        self.assertEqual(one.value["shape"], [0])
        two = alg.conjoin("EMPTY", "EMPTY")
        self.assertOutcome(two, AbsenceState.EMPTY, True, True)
        self.assertNotEqual(two.state, AbsenceState.NULL)
        self.assertNotEqual(two.state, AbsenceState.VOID)

    def test_infinity_is_a_present_value(self):
        result = algebra().conjoin("INFINITY", VECTOR_REF)
        self.assertOutcome(result, None, True, True)

    def test_object_void_defaults_to_unknown_not_zero(self):
        alg = algebra()
        for left, right in ((VECTOR_REF, "VOID"), ("VOID", VECTOR_REF)):
            result = alg.conjoin(left, right)
            self.assertOutcome(
                result, AbsenceState.UNKNOWN, False, False,
                reason="VOID_INPUT_MAY_ARRIVE",
                failure_class=FailureClass.NOT_ESTABLISHED.value,
            )
            self.assertNotEqual(result.state, AbsenceState.ZERO)
            self.assertNotEqual(result.state, AbsenceState.NULL)

    def test_void_strict_policy_raises_reference_error(self):
        alg = algebra()
        for left, right in ((VECTOR_REF, "VOID"), ("VOID", VECTOR_REF)):
            result = alg.conjoin(left, right, policy=ConjoinPolicy.strict())
            self.assertOutcome(
                result, AbsenceState.VOID, False, False,
                failure_class=FailureClass.MISSING_REFERENCE.value,
                reference_error=True,
            )

    def test_void_void_is_explicit_void_or_reference_error(self):
        alg = algebra()
        default = alg.conjoin("VOID", "VOID")
        self.assertOutcome(
            default, AbsenceState.VOID, False, False,
            reason="VOID_CONJUNCTION",
            failure_class=FailureClass.NO_OBJECT.value,
        )
        strict = alg.conjoin("VOID", "VOID", policy=ConjoinPolicy.strict())
        self.assertOutcome(
            strict, AbsenceState.VOID, False, False,
            failure_class=FailureClass.MISSING_REFERENCE.value,
            reference_error=True,
        )

    def test_null_object_has_no_candidates_and_preserves_reason(self):
        alg = algebra()
        null = alg.classify(
            "NULL", reason="NO_VALID_TRANSFORM", parents=(PARENT,),
        )
        for left, right in ((null, VECTOR_REF), (VECTOR_REF, null)):
            result = alg.conjoin(left, right)
            self.assertOutcome(
                result, AbsenceState.NULL, False, False,
                reason="NO_VALID_TRANSFORM",
                failure_class=FailureClass.NO_VALID_RESULT.value,
            )
            parent_ids = [p.get("leaf_id") for p in result.parents]
            self.assertIn(PARENT["leaf_id"], parent_ids)
            self.assertIn(VECTOR_ID, parent_ids)

    def test_null_null_has_no_candidates_by_default(self):
        result = algebra().conjoin("NULL", "NULL")
        self.assertOutcome(result, AbsenceState.NULL, False, False)
        self.assertFalse(result.candidates_allowed)

    def test_registered_null_algebra_is_explicit_not_a_wildcard(self):
        alg = algebra()
        policy = ConjoinPolicy(null_algebra_id="math.null.algebra.v1")
        result = alg.conjoin("NULL", VECTOR_REF, policy=policy)
        self.assertOutcome(result, None, False, True)
        self.assertEqual(result.null_algebra_id, "math.null.algebra.v1")
        self.assertEqual(result.failure_class, None)
        self.assertFalse(result.reference_error)
        both = alg.conjoin("NULL", "NULL", policy=policy)
        self.assertOutcome(both, None, False, True)
        with self.assertRaises(AbsenceError):
            ConjoinPolicy(null_algebra_id="*")
        with self.assertRaises(AbsenceError):
            ConjoinPolicy(null_algebra_id="VOID")

    def test_registered_null_algebra_does_not_hide_undefined(self):
        policy = ConjoinPolicy(null_algebra_id="math.null.algebra.v1")
        result = algebra().conjoin("NULL", "UNDEFINED", policy=policy)
        self.assertOutcome(result, AbsenceState.UNDEFINED, False, False)

    def test_undefined_object_preserves_undefined_reason(self):
        alg = algebra()
        undefined = alg.classify("UNDEFINED", reason="DIVISION_BY_ZERO")
        for left, right in ((undefined, VECTOR_REF), (VECTOR_REF, undefined)):
            result = alg.conjoin(left, right)
            self.assertOutcome(
                result, AbsenceState.UNDEFINED, False, False,
                reason="DIVISION_BY_ZERO",
                failure_class=FailureClass.MATHEMATICALLY_UNDEFINED.value,
            )
            self.assertNotEqual(result.state, AbsenceState.NULL)
            self.assertNotEqual(result.state, AbsenceState.ERROR)

    def test_error_is_execution_failure_not_undefined(self):
        alg = algebra()
        error = alg.classify("ERROR", reason="KERNEL_FAULT")
        result = alg.conjoin(error, VECTOR_REF)
        self.assertOutcome(
            result, AbsenceState.ERROR, False, False,
            reason="KERNEL_FAULT",
            failure_class=FailureClass.EXECUTION_FAILED.value,
        )
        self.assertNotEqual(result.state, AbsenceState.UNDEFINED)
        self.assertNotEqual(result.state, AbsenceState.NULL)

    def test_cancelled_is_not_null_or_error(self):
        alg = algebra()
        cancelled = alg.classify("CANCELLED", reason="EPOCH_ADVANCED")
        result = alg.conjoin(cancelled, VECTOR_REF)
        self.assertOutcome(
            result, AbsenceState.CANCELLED, False, False,
            reason="EPOCH_ADVANCED",
            failure_class=FailureClass.CANCELLED.value,
        )
        self.assertNotEqual(result.state, AbsenceState.NULL)
        self.assertNotEqual(result.state, AbsenceState.ERROR)

    def test_unknown_object_has_no_candidates(self):
        result = algebra().conjoin("UNKNOWN", VECTOR_REF)
        self.assertOutcome(
            result, AbsenceState.UNKNOWN, False, False,
            failure_class=FailureClass.NOT_ESTABLISHED.value,
        )

    def test_empty_structure_is_not_void_or_null(self):
        alg = algebra()
        empty_void = alg.conjoin("EMPTY", "VOID")
        self.assertOutcome(empty_void, AbsenceState.UNKNOWN, False, False)
        self.assertNotEqual(empty_void.state, AbsenceState.VOID)
        empty_null = alg.conjoin("EMPTY", "NULL")
        self.assertOutcome(empty_null, AbsenceState.NULL, False, False)
        empty_undefined = alg.conjoin("EMPTY", "UNDEFINED")
        self.assertOutcome(empty_undefined, AbsenceState.UNDEFINED, False, False)

    def test_absent_precedence_is_deterministic(self):
        alg = algebra()
        cases = {
            ("ERROR", "CANCELLED"): AbsenceState.CANCELLED,
            ("ERROR", "UNDEFINED"): AbsenceState.ERROR,
            ("UNDEFINED", "NULL"): AbsenceState.UNDEFINED,
            ("NULL", "VOID"): AbsenceState.NULL,
            ("VOID", "UNKNOWN"): AbsenceState.UNKNOWN,
            ("VOID", "UNDEFINED"): AbsenceState.UNDEFINED,
            ("VOID", "ERROR"): AbsenceState.ERROR,
            ("VOID", "CANCELLED"): AbsenceState.CANCELLED,
        }
        for (left, right), expected in cases.items():
            with self.subTest(left=left, right=right):
                result = alg.conjoin(left, right)
                self.assertOutcome(result, expected, False, False)

    def test_all_state_pairs_have_a_valid_conjunction(self):
        alg = algebra()
        for left in ALL_STATES:
            for right in ALL_STATES:
                with self.subTest(left=left.value, right=right.value):
                    result = alg.conjoin(left, right)
                    self.assertIn(
                        result.state,
                        set(ALL_STATES) | {None},
                    )
                    if left in ABSENT_STATES or right in ABSENT_STATES:
                        if result.state is not None and result.state.present:
                            # Only EMPTY can be present when an operand is
                            # absent? No: absent must block candidates, so this
                            # branch should never happen.
                            self.fail(f"absence wildcard leaked: {left}::{right}")
                        self.assertFalse(result.candidates_allowed)
                    else:
                        self.assertTrue(result.present)
                        self.assertTrue(result.candidates_allowed)
                    if result.state is None:
                        self.assertTrue(result.present or result.null_algebra_id)

    def test_missing_reference_dominates_and_does_not_fabricate_a_leaf(self):
        alg = algebra()
        missing = MissingReference(
            MISSING_ID, version=3, reason="PAYLOAD_NOT_FOUND",
            parents=(PARENT,),
        )
        for policy in (ConjoinPolicy(), ConjoinPolicy.strict()):
            result = alg.conjoin(missing, VECTOR_REF, policy=policy)
            self.assertOutcome(
                result, AbsenceState.VOID, False, False,
                failure_class=FailureClass.MISSING_REFERENCE.value,
                reference_error=True,
            )
            parent_ids = [p.get("leaf_id") for p in result.parents]
            self.assertNotIn(MISSING_ID, parent_ids)
            self.assertIn(VECTOR_ID, parent_ids)
            record = result.to_record()
            self.assertIsNone(record.value)
            self.assertIsNone(record.leaf_id)
            self.assertEqual(record.metadata["missing_leaf_id"], MISSING_ID)

    def test_missing_reference_precedes_undefined(self):
        missing = MissingReference(MISSING_ID)
        result = algebra().conjoin(missing, "UNDEFINED")
        self.assertOutcome(
            result, AbsenceState.VOID, False, False,
            failure_class=FailureClass.MISSING_REFERENCE.value,
            reference_error=True,
        )

    def test_snapshot_mismatch_is_rejected(self):
        a = algebra()
        b = AbsenceAlgebra(rule_snapshot={"ruleset_id": "other.rules", "version": 2})
        with self.assertRaises(SnapshotMismatchError):
            a.conjoin(a.classify("NULL", reason="A"), b.classify("ZERO"))

    def test_invalid_policy_is_rejected(self):
        with self.assertRaises(AbsenceError):
            ConjoinPolicy(void_policy="ANY")
        with self.assertRaises(AbsenceError):
            ConjoinPolicy(void_void_policy="NULL")
        with self.assertRaises(AbsenceError):
            algebra().conjoin("VOID", "VOID", policy={"void_void_policy": "ZERO"})


class PresenceTests(unittest.TestCase):
    def test_require_present_returns_typed_presence(self):
        alg = algebra()
        for value, expected in (
            (VECTOR_REF, None),
            ("ZERO", AbsenceState.ZERO),
            ("EMPTY", AbsenceState.EMPTY),
            ("INFINITY", AbsenceState.INFINITY),
        ):
            with self.subTest(value=value):
                presence = alg.require_present(value, purpose="dot")
                self.assertTrue(presence.operand.present)
                self.assertIs(presence.state, expected)
                self.assertEqual(presence.reason, "PRESENT")
                self.assertTrue(presence.to_dict()["operand"]["present"])

    def test_require_present_rejects_each_absent_state(self):
        alg = algebra()
        expected_errors = {
            AbsenceState.NULL: AbsenceRequiredError,
            AbsenceState.VOID: AbsenceRequiredError,
            AbsenceState.UNDEFINED: AbsenceRequiredError,
            AbsenceState.UNKNOWN: AbsenceRequiredError,
            AbsenceState.ERROR: AbsenceRequiredError,
            AbsenceState.CANCELLED: AbsenceRequiredError,
        }
        for state, error_type in expected_errors.items():
            with self.subTest(state=state.value):
                with self.assertRaises(error_type) as caught:
                    alg.require_present(state, purpose="preflight")
                error = caught.exception
                self.assertIsInstance(error, AbsenceRequiredError)
                self.assertNotIsInstance(error, MissingReferenceError)
                self.assertIs(error.state, state)
                self.assertEqual(error.purpose, "preflight")
                self.assertFalse(error.operand.present)
                self.assertEqual(error.to_dict()["schema"], ABSENCE_REQUIRED_SCHEMA)

    def test_missing_reference_raises_typed_atomic_error(self):
        alg = algebra()
        missing = MissingReference(
            MISSING_ID, version=9, reason="MISSING_PAYLOAD",
            parents=(PARENT,),
        )
        with self.assertRaises(MissingReferenceError) as caught:
            alg.require_present(missing, purpose="conjunction")
        error = caught.exception
        self.assertIs(error.state, AbsenceState.VOID)
        self.assertEqual(error.failure_class, FailureClass.MISSING_REFERENCE.value)
        self.assertEqual(error.reason, "MISSING_PAYLOAD")
        self.assertTrue(error.reference_error)
        self.assertEqual(error.missing_leaf_id, MISSING_ID)
        self.assertIsNone(error.operand.record.leaf_id)
        self.assertIsNone(error.operand.record.value)
        self.assertEqual(error.to_dict()["purpose"], "conjunction")

        # Repeated attempts are deterministic and do not leave a synthesized
        # leaf or a mutation behind.
        first = alg.classify(missing).digest()
        with self.assertRaises(MissingReferenceError):
            alg.require_present(missing, purpose="conjunction")
        self.assertEqual(alg.classify(missing).digest(), first)
        self.assertFalse(hasattr(alg, "records"))
        self.assertFalse(hasattr(alg, "leaves"))
        self.assertEqual(set(alg.__dict__), {"_rule_snapshot", "_linker_id"})

    def test_missing_reference_is_not_empty_or_undefined(self):
        alg = algebra()
        operand = alg.classify(MissingReference(MISSING_ID))
        self.assertIsNot(operand.state, AbsenceState.EMPTY)
        self.assertIsNot(operand.state, AbsenceState.UNDEFINED)
        self.assertIsNot(operand.state, AbsenceState.NULL)
        self.assertEqual(operand.record.value, None)


class SerializationTests(unittest.TestCase):
    def test_record_roundtrip_and_stable_digest(self):
        alg = algebra()
        record = alg.classify(
            "UNDEFINED", reason="DIVISION_BY_ZERO", parents=(PARENT,),
        ).record
        data = record.to_dict()
        self.assertEqual(data["schema"], ABSENCE_SCHEMA)
        restored = AbsenceRecord.from_dict(data)
        self.assertEqual(restored, record)
        self.assertEqual(restored.digest(), record.digest())
        self.assertEqual(canonical_json(data), canonical_json(restored.to_dict()))

    def test_classification_roundtrip(self):
        alg = algebra()
        for value in (VECTOR_REF, "NULL", "EMPTY", "CANCELLED", MissingReference(MISSING_ID)):
            with self.subTest(value=type(value).__name__):
                operand = alg.classify(value)
                data = operand.to_dict()
                self.assertEqual(data["schema"], ABSENCE_CLASSIFICATION_SCHEMA)
                restored = ClassifiedOperand.from_dict(data)
                self.assertEqual(restored.to_dict(), data)
                self.assertEqual(restored.digest(), operand.digest())

    def test_conjunction_roundtrip(self):
        alg = algebra()
        result = alg.conjoin("NULL", VECTOR_REF, parents=(PARENT,))
        data = result.to_dict()
        restored = ConjunctionResult.from_dict(data)
        self.assertEqual(restored.to_dict(), data)
        self.assertEqual(restored.digest(), result.digest())
        self.assertEqual(restored.state, AbsenceState.NULL)
        self.assertFalse(restored.candidates_allowed)
        self.assertEqual(len(restored.operands), 2)

    def test_presence_roundtrip(self):
        presence = algebra().require_present(VECTOR_REF, purpose="dot")
        data = presence.to_dict()
        self.assertEqual(data["schema"], "nanrouter.math-presence.v1")
        self.assertEqual(data["leaf_id"], VECTOR_ID)
        self.assertEqual(canonical_json(data), canonical_json(presence.to_dict()))
        self.assertEqual(presence.digest(), presence.digest())

    def test_every_state_to_leaf_is_serializable_and_roundtrips(self):
        alg = algebra()
        expected_kind = {
            AbsenceState.ZERO: "scalar",
            AbsenceState.NULL: "null",
            AbsenceState.VOID: "void",
            AbsenceState.EMPTY: "vector",
            AbsenceState.UNDEFINED: "undefined",
            AbsenceState.INFINITY: "scalar",
            AbsenceState.UNKNOWN: "unknown",
            AbsenceState.ERROR: "error",
            AbsenceState.CANCELLED: "null",
        }
        for state in ALL_STATES:
            with self.subTest(state=state.value):
                operand = alg.classify(
                    state, reason=f"reason:{state.value}", parents=(PARENT,),
                )
                leaf = alg.to_leaf(operand)
                self.assertEqual(leaf.kind, expected_kind[state])
                self.assertEqual(leaf.metadata["absence_state"], state.value)
                self.assertEqual(leaf.metadata["rule_snapshot"], RULE_SNAPSHOT)
                self.assertEqual(leaf.parents, (dict(PARENT),))
                if state in PRESENT_STATES:
                    self.assertIsNotNone(leaf.content)
                else:
                    self.assertIsNone(leaf.content)
                restored = alg.classify(leaf)
                self.assertIs(restored.state, state)
                self.assertEqual(restored.reason, f"reason:{state.value}")
                self.assertEqual(restored.failure_class, operand.failure_class)
                self.assertEqual(restored.parents, (dict(PARENT),))
                self.assertEqual(restored.rule_snapshot, RULE_SNAPSHOT)
                self.assertEqual(leaf.to_dict()["schema"], "nanrouter.math-leaf.v1")
                self.assertEqual(leaf.digest(), leaf.digest())
                # The serialized envelope must be canonical JSON.
                self.assertEqual(canonical_json(leaf.to_dict()), canonical_json(leaf.to_dict()))

    def test_to_leaf_for_null_conjunction_has_no_content(self):
        alg = algebra()
        result = alg.conjoin("NULL", VECTOR_REF)
        leaf = alg.to_leaf(result)
        self.assertEqual(leaf.kind, "null")
        self.assertIsNone(leaf.content)
        self.assertEqual(leaf.metadata["absence_state"], "NULL")
        self.assertFalse(leaf.metadata["failure_class"] is None)
        self.assertEqual(alg.classify(leaf).state, AbsenceState.NULL)

    def test_to_leaf_rejects_present_object_without_absence_state(self):
        with self.assertRaises(AbsenceError):
            algebra().to_leaf(VECTOR_REF)

    def test_null_serialization_rejects_non_canonical_nan(self):
        record = AbsenceRecord(
            state="NULL",
            reason="NO_VALID_RESULT",
            metadata={"diagnostic": float("nan")},
        )
        with self.assertRaises(MathObjectError):
            record.digest()
        self.assertIsNone(record.value)
        self.assertNotIn("nan", str(record.value).lower())

    def test_zero_leaf_content_is_a_zero_descriptor_not_absence(self):
        alg = algebra()
        zero_leaf = alg.to_leaf(alg.classify("ZERO"))
        null_leaf = alg.to_leaf(alg.classify("NULL"))
        self.assertIsNotNone(zero_leaf.content)
        self.assertEqual(zero_leaf.content["canonical"], "0")
        self.assertIsNone(null_leaf.content)
        self.assertNotEqual(zero_leaf.digest(), null_leaf.digest())
        self.assertNotEqual(zero_leaf.kind, null_leaf.kind)


class NoConflationTests(unittest.TestCase):
    def test_null_and_zero_are_never_equal(self):
        alg = algebra()
        zero = alg.classify("ZERO")
        null = alg.classify("NULL")
        self.assertIsNot(zero.state, null.state)
        self.assertTrue(zero.present)
        self.assertFalse(null.present)
        self.assertIsNotNone(zero.record.value)
        self.assertIsNone(null.record.value)
        self.assertNotEqual(zero.record.digest(), null.record.digest())
        self.assertNotEqual(zero.to_dict()["state"], null.to_dict()["state"])
        self.assertNotEqual(zero.to_dict(), null.to_dict())

    def test_zero_operand_does_not_make_null_result_zero(self):
        alg = algebra()
        result = alg.conjoin("ZERO", "NULL")
        self.assertIs(result.state, AbsenceState.NULL)
        self.assertFalse(result.candidates_allowed)
        self.assertIsNone(result.value)
        with self.assertRaises(AbsenceRequiredError):
            alg.require_present("NULL")
        self.assertTrue(alg.require_present("ZERO").operand.present)

    def test_void_is_not_a_wildcard(self):
        alg = algebra()
        for other in ("ZERO", "EMPTY", "INFINITY", VECTOR_REF):
            with self.subTest(other=type(other).__name__):
                result = alg.conjoin("VOID", other)
                self.assertFalse(result.present)
                self.assertFalse(result.candidates_allowed)
                self.assertNotEqual(result.state, AbsenceState.ZERO)
                self.assertNotEqual(result.state, AbsenceState.EMPTY)
                self.assertNotEqual(result.state, AbsenceState.INFINITY)
        self.assertNotIn("ANY", {state.value for state in ALL_STATES})
        self.assertNotIn("*", {state.value for state in ALL_STATES})
        with self.assertRaises(AbsenceError):
            alg.classify("ANY")

    def test_empty_is_not_void_null_or_undefined(self):
        alg = algebra()
        empty = alg.classify("EMPTY")
        self.assertTrue(empty.present)
        self.assertIsNot(empty.state, AbsenceState.VOID)
        self.assertIsNot(empty.state, AbsenceState.NULL)
        self.assertIsNot(empty.state, AbsenceState.UNDEFINED)
        self.assertEqual(empty.record.value["count"], 0)

    def test_failure_classes_keep_error_cancelled_undefined_separate(self):
        values = {
            FailureClass.MISSING_REFERENCE.value,
            FailureClass.MATHEMATICALLY_UNDEFINED.value,
            FailureClass.EXECUTION_FAILED.value,
            FailureClass.CANCELLED.value,
            FailureClass.NOT_ESTABLISHED.value,
            FailureClass.NO_VALID_RESULT.value,
            FailureClass.NO_CANDIDATE.value,
            FailureClass.NO_OBJECT.value,
        }
        self.assertEqual(values, set(FAILURE_CLASSES))
        self.assertEqual(len(values), 8)


class ImportBoundaryTests(unittest.TestCase):
    def test_module_has_no_numeric_math_or_executor_imports(self):
        source = Path(
            "runner_riddle/math_absence.py"
        ).read_text(encoding="utf-8")
        import_lines = [
            line.strip() for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))
        ]
        forbidden = (
            "import math", "import numpy", "import scipy", "import cmath",
            "mth_system", "wave_service", "point0", "tile_executor",
            "math_runtime", "math_linker", "math_validity", "math_store",
        )
        for line in import_lines:
            for token in forbidden:
                self.assertNotIn(token, line, f"forbidden import: {line}")
        # The only math-layer import is the typed envelope module.
        self.assertTrue(any("math_objects" in line for line in import_lines))
        self.assertGreaterEqual(len(import_lines), 4)


if __name__ == "__main__":
    unittest.main()
