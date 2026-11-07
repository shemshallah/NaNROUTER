from __future__ import annotations

import ast
from pathlib import Path
import unittest

from runner_riddle.math_objects import (
    MathAdmission,
    MathCandidate,
    MathFunction,
    MathRule,
    admission_id_for,
    candidate_id_for,
    digest_object,
)
from runner_riddle.math_validity import (
    AdmissionRejected,
    EXPERIMENTAL,
    INVALID,
    MathPreflightCache,
    MathSnapshot,
    MathSnapshotError,
    MathValidityEngine,
    STALE,
    UNAVAILABLE,
    UNDEFINED,
    UNKNOWN,
    UNSUPPORTED,
    VALID,
    coerce_snapshot,
    evaluate_predicates,
    preflight,
    require_admission,
)

SNP1 = "snp:" + "1" * 64
SNP2 = "snp:" + "2" * 64
CERT = "c" * 64


def vector_spec(name="a", shape=(256,), domain="real", precision="float32",
                layout="row_major"):
    return {
        "name": name,
        "type": "vector",
        "domain": domain,
        "shape": list(shape),
        "precision": precision,
        "layout": layout,
    }


def scalar_spec(name="x"):
    return {
        "name": name,
        "type": "scalar",
        "domain": "real",
        "shape": [],
        "precision": "float32",
    }


def vector_add(version=1, *, semantics=None, preconditions=(), postconditions=(),
               undefined_conditions=(), status="active",
               function_id="math.vector.add"):
    return MathFunction(
        function_id=function_id,
        version=version,
        signature={
            "inputs": [vector_spec("a"), vector_spec("b")],
            "output": vector_spec("out"),
        },
        semantics=dict(semantics or {}),
        preconditions=preconditions,
        postconditions=postconditions,
        undefined_conditions=undefined_conditions,
        implementations=({
            "kernel_id": "mth.vector.add256.f32",
            "capability_class": "vector.add",
            "status": "declared",
        },),
        proof_status="verified",
        status=status,
    )


def vector_dot(version=1, *, semantics=None):
    return MathFunction(
        function_id="math.vector.dot",
        version=version,
        signature={
            "inputs": [vector_spec("a"), vector_spec("b")],
            "output": scalar_spec("out"),
        },
        semantics=dict(semantics or {}),
        implementations=({
            "kernel_id": "mth.vector.dot256.f32",
            "capability_class": "vector.dot",
            "status": "declared",
        },),
        proof_status="verified",
    )


def matrix_spec(name="m", rows=2, cols=2):
    return {
        "name": name,
        "type": "matrix",
        "domain": "real",
        "shape": [rows, cols],
        "precision": "float32",
        "layout": "row_major",
    }


def matrix_vector(rows=2, cols=2):
    return MathFunction(
        function_id="math.matrix.matvec",
        version=1,
        signature={
            "inputs": [matrix_spec("m", rows, cols), vector_spec("v", shape=(cols,))],
            "output": vector_spec("out", shape=(rows,)),
        },
        implementations=({
            "kernel_id": "mth.matvec256.block16.f32",
            "capability_class": "matrix.matvec",
            "status": "declared",
        },),
        proof_status="verified",
    )


def scalar_div(*, preconditions=(), postconditions=(), undefined_conditions=()):
    return MathFunction(
        function_id="math.scalar.div",
        version=1,
        signature={
            "inputs": [scalar_spec("a"), scalar_spec("b")],
            "output": scalar_spec("out"),
        },
        preconditions=preconditions,
        postconditions=postconditions,
        undefined_conditions=undefined_conditions,
        implementations=({
            "kernel_id": "mth.scalar.div.f32",
            "capability_class": "scalar.div",
            "status": "declared",
        },),
        proof_status="verified",
    )


def vector_norm(*, preconditions=(), postconditions=()):
    return MathFunction(
        function_id="math.vector.norm",
        version=1,
        signature={
            "inputs": [vector_spec("a")],
            "output": scalar_spec("out"),
        },
        preconditions=preconditions,
        postconditions=postconditions,
        implementations=({
            "kernel_id": "mth.vector.norm256.f32",
            "capability_class": "vector.norm",
            "status": "declared",
        },),
        proof_status="verified",
    )


def leaf_pin(leaf_id, shape=(256,), *, kind="vector", precision="float32",
             domain="real", layout="row_major", version=1,
             workspace_words=256, content=None, digest=None, status="committed",
             type_extra=None, **extra):
    type_doc = {
        "kind": kind,
        "name": kind,
        "domain": domain,
        "shape": list(shape),
        "precision": precision,
        "layout": layout,
    }
    if type_extra:
        type_doc.update(type_extra)
    pin = {
        "leaf_id": leaf_id,
        "version": version,
        "content_digest": digest or digest_object({"leaf": leaf_id, "shape": list(shape)}),
        "type": type_doc,
        "workspace_words": workspace_words,
        "status": status,
    }
    if content is not None:
        pin["content"] = content
    pin.update(extra)
    return pin


def rule_definition(rule_id="math.rule.vector.core", version=1, level=1,
                    function_ids=("math.vector.add",), status="active",
                    claims=None, certificate=None, contract_extra=None):
    contract = {}
    if claims is not None:
        contract["claims"] = dict(claims)
    if contract_extra:
        contract.update(contract_extra)
    return MathRule(
        rule_id=rule_id,
        version=version,
        level=level,
        contract=contract,
        proof_status="verified",
        status=status,
        scope={"function_ids": list(function_ids)},
        certificate_digest=certificate,
    )


def snapshot(snapshot_id=SNP1, *, functions=(), rules=(), pins=(), **kwargs):
    return MathSnapshot(
        snapshot_id=snapshot_id,
        functions=tuple(functions),
        rules=tuple(rules),
        leaf_pins=tuple(pins),
        **kwargs,
    )


def refs_for(pins):
    return tuple({
        "leaf_id": pin["leaf_id"],
        "version": pin["version"],
        "content_digest": pin["content_digest"],
    } for pin in pins)


def candidate_for(function, pins, *, snapshot_id=SNP1, version=None,
                  outputs=(), rank=0):
    inputs = refs_for(pins)
    function_version = function.version if version is None else version
    identifier = candidate_id_for(
        snapshot_id, inputs, function.function_id, function_version,
    )
    return MathCandidate(
        identifier,
        inputs,
        function.function_id,
        function_version,
        outputs=tuple(outputs),
        snapshot_id=snapshot_id,
        rank=rank,
    )


def plan_for(admission, **overrides):
    document = {
        "admission_id": admission.admission_id,
        "preflight_digest": admission.preflight_digest,
        "snapshot_id": admission.snapshot_id,
        "rule_snapshot_id": admission.rule_snapshot_id,
        "candidate_id": admission.candidate_id,
        "verdict": admission.verdict,
    }
    document.update(overrides)
    return document


class MathValidityTests(unittest.TestCase):
    def setUp(self):
        self.a = leaf_pin("nml:U0:vector:a", (256,))
        self.b = leaf_pin("nml:U0:vector:b", (256,))
        self.add = vector_add()
        self.dot = vector_dot()
        self.core_rule = rule_definition()
        self.base_snapshot = snapshot(
            functions=(self.add, self.dot),
            rules=(self.core_rule,),
            pins=(self.a, self.b),
            resources={"workspace_words": 100_000},
        )

    def test_t01_vector_add_is_valid(self):
        engine = MathValidityEngine(self.base_snapshot)
        candidate = candidate_for(self.add, (self.a, self.b))
        admission = engine.preflight(candidate)
        self.assertEqual(admission.verdict, VALID)
        self.assertEqual(admission.reason, "")
        self.assertEqual(admission.snapshot_id, SNP1)
        self.assertEqual(admission.scope["rule_level"], 1)
        self.assertEqual(admission.scope["math_verdict"], VALID)
        self.assertTrue(admission.scope["semantic_key"].startswith("sem:"))
        self.assertTrue(admission.scope["dispatch_key"].startswith("dsp:"))
        self.assertTrue(admission.preflight_digest.startswith("pf:"))
        checked = {item["check"] for item in admission.scope["checks"]}
        self.assertIn("shape", checked)
        self.assertIn("layout", checked)
        self.assertIn("precision", checked)
        self.assertIn("domain", checked)
        self.assertIn("workspace", checked)
        self.assertIs(engine.require_admission(admission, plan=plan_for(admission)), admission)

    def test_t03_dot_is_valid_scalar_contract(self):
        engine = MathValidityEngine(self.base_snapshot)
        admission = engine.preflight(candidate_for(self.dot, (self.a, self.b)))
        self.assertEqual(admission.verdict, VALID)
        self.assertEqual(admission.scope["math_verdict"], VALID)
        self.assertEqual(admission.scope["rule_level"], 0)

    def test_matrix_vector_compatible_and_incompatible(self):
        matvec = matrix_vector(2, 2)
        matrix = leaf_pin(
            "nml:U0:matrix:m", (2, 2), kind="matrix", workspace_words=4,
        )
        vector = leaf_pin("nml:U0:vector:v", (2,), workspace_words=2)
        base = snapshot(functions=(matvec,), pins=(matrix, vector))
        engine = MathValidityEngine(base)
        admission = engine.preflight(candidate_for(matvec, (matrix, vector)))
        self.assertEqual(admission.verdict, VALID)
        self.assertEqual(admission.scope["math_verdict"], VALID)

        wrong = leaf_pin("nml:U0:vector:wrong", (3,), workspace_words=3)
        base = snapshot(functions=(matvec,), pins=(matrix, wrong))
        engine = MathValidityEngine(base)
        admission = engine.preflight(candidate_for(matvec, (matrix, wrong)))
        self.assertEqual(admission.verdict, INVALID)
        self.assertEqual(admission.reason, "SHAPE_MISMATCH")

    def test_t10_zero_vector_dot_stays_a_valid_numeric_result(self):
        zero = leaf_pin(
            "nml:U0:vector:zero", (256,), type_extra={"zero": True},
        )
        base = snapshot(functions=(self.dot,), pins=(zero, self.b))
        engine = MathValidityEngine(base)
        admission = engine.preflight(candidate_for(self.dot, (zero, self.b)))
        self.assertEqual(admission.verdict, VALID)
        self.assertNotEqual(admission.verdict, UNDEFINED)

    def test_t02_unequal_dimensions_invalid_and_no_execution(self):
        short = leaf_pin("nml:U0:vector:short", (128,))
        base = snapshot(
            functions=(self.add, self.dot),
            pins=(self.a, short),
        )
        engine = MathValidityEngine(base)
        admission = engine.preflight(candidate_for(self.add, (self.a, short)))
        self.assertEqual(admission.verdict, INVALID)
        self.assertEqual(admission.reason, "SHAPE_MISMATCH")
        plan = plan_for(admission)
        with self.assertRaises(AdmissionRejected) as raised:
            engine.require_admission(admission, plan=plan)
        self.assertEqual(raised.exception.verdict, INVALID)
        self.assertEqual(raised.exception.admission, admission)

    def test_t11_division_by_zero_is_undefined_not_null(self):
        dividend = leaf_pin("nml:U0:scalar:one", (), kind="scalar", content={"value": "1"})
        zero = leaf_pin("nml:U0:scalar:zero", (), kind="scalar", content={"value": "0"})
        divisor = scalar_div(undefined_conditions=(
            {"op": "zero", "operand": 1, "reason": "DIVISION_BY_ZERO"},
        ))
        base = snapshot(functions=(divisor,), pins=(dividend, zero))
        engine = MathValidityEngine(base)
        admission = engine.preflight(candidate_for(divisor, (dividend, zero)))
        self.assertEqual(admission.verdict, UNDEFINED)
        self.assertEqual(admission.reason, "DIVISION_BY_ZERO")
        self.assertNotEqual(admission.verdict, "NULL")
        with self.assertRaises(AdmissionRejected):
            engine.require_admission(admission)

        two = leaf_pin("nml:U0:scalar:two", (), kind="scalar", content={"value": "2"})
        base = snapshot(functions=(divisor,), pins=(dividend, two))
        engine = MathValidityEngine(base)
        self.assertEqual(
            engine.preflight(candidate_for(divisor, (dividend, two))).verdict,
            VALID,
        )

        equals_zero = scalar_div(undefined_conditions=(
            {
                "op": "eq",
                "left": {"input": 1, "field": "content.value"},
                "right": "0",
                "reason": "DIVISION_BY_ZERO",
            },
        ))
        base = snapshot(functions=(equals_zero,), pins=(dividend, zero))
        engine = MathValidityEngine(base)
        self.assertEqual(
            engine.preflight(candidate_for(equals_zero, (dividend, zero))).verdict,
            UNDEFINED,
        )

    def test_t12_unknown_function_is_unsupported_before_execution(self):
        engine = MathValidityEngine(self.base_snapshot)
        missing = MathFunction(
            function_id="math.vector.missing", version=1,
            signature={"inputs": [vector_spec()]},
        )
        admission = engine.preflight(candidate_for(missing, (self.a,)))
        self.assertEqual(admission.verdict, UNSUPPORTED)
        self.assertEqual(admission.reason, "UNKNOWN_FUNCTION")
        with self.assertRaises(AdmissionRejected) as raised:
            engine.require_admission(admission)
        self.assertEqual(raised.exception.verdict, UNSUPPORTED)

    def test_t13_modified_ruleset_stale_and_cache_invalidated(self):
        engine = MathValidityEngine(self.base_snapshot)
        old_candidate = candidate_for(self.add, (self.a, self.b))
        old_admission = engine.preflight(old_candidate)
        self.assertEqual(old_admission.verdict, VALID)
        self.assertEqual(engine.cache.semantic_size, 1)

        new_rule = rule_definition(version=2)
        new_snapshot = snapshot(
            SNP2,
            functions=(self.add, self.dot),
            rules=(new_rule,),
            pins=(self.a, self.b),
            resources={"workspace_words": 100_000},
        )
        engine.install_snapshot(new_snapshot)
        self.assertEqual(engine.cache.semantic_size, 0)
        self.assertEqual(engine.cache.dispatch_size, 0)

        stale = engine.preflight(old_candidate)
        self.assertEqual(stale.verdict, STALE)
        self.assertEqual(stale.reason, "STALE_SNAPSHOT")
        with self.assertRaises(AdmissionRejected) as raised:
            engine.require_admission(old_admission)
        self.assertEqual(raised.exception.verdict, STALE)

        current = candidate_for(self.add, (self.a, self.b), snapshot_id=SNP2)
        self.assertEqual(engine.preflight(current).verdict, VALID)

    def test_t14_identical_conjunction_reuses_semantic_and_dispatch_keys(self):
        engine = MathValidityEngine(self.base_snapshot)
        first = candidate_for(self.add, (self.a, self.b), rank=1)
        second = candidate_for(self.add, (self.a, self.b), rank=9)
        self.assertEqual(first.candidate_id, second.candidate_id)
        self.assertEqual(
            engine.semantic_key(first),
            engine.semantic_key(second),
        )
        admission_one = engine.preflight(first)
        admission_two = engine.preflight(second)
        self.assertEqual(admission_one.admission_id, admission_two.admission_id)
        self.assertEqual(admission_one.preflight_digest, admission_two.preflight_digest)
        self.assertEqual(engine.cache.dispatch_size, 1)

        semantic = engine.semantic_key(first)
        dispatch = engine.dispatch_key(semantic)
        engine.set_dispatch_context({"slot": 2, "epoch": 7, "tick": 99})
        self.assertEqual(engine.semantic_key(first), semantic)
        self.assertNotEqual(engine.dispatch_key(semantic), dispatch)
        third = engine.preflight(second)
        self.assertEqual(third.verdict, VALID)
        self.assertEqual(third.admission_id, admission_one.admission_id)
        self.assertEqual(third.scope["cache"], "semantic-hit")

    def test_cache_invalidation_is_explicit_and_context_aware(self):
        engine = MathValidityEngine(self.base_snapshot)
        candidate = candidate_for(self.add, (self.a, self.b))
        admission = engine.preflight(candidate)
        semantic = admission.scope["semantic_key"]
        self.assertEqual(engine.cache.semantic_size, 1)
        self.assertEqual(engine.cache.invalidate_semantic(semantic), 1)
        self.assertEqual(engine.cache.semantic_size, 0)
        self.assertEqual(engine.cache.dispatch_size, 1)
        engine.set_dispatch_context({"slot": 2})
        self.assertEqual(engine.cache.dispatch_size, 0)
        self.assertEqual(engine.preflight(candidate).verdict, VALID)
        self.assertEqual(engine.cache.semantic_size, 1)

        engine.set_authorization({"allowed": True})
        self.assertEqual(engine.cache.semantic_size, 0)
        self.assertEqual(engine.cache.dispatch_size, 0)
        self.assertEqual(engine.preflight(candidate).verdict, VALID)

        engine.set_capabilities({
            "capability_class": "vector.add",
            "status": "unavailable",
        })
        self.assertEqual(engine.cache.dispatch_size, 0)
        self.assertEqual(engine.preflight(candidate).verdict, UNAVAILABLE)

    def test_capability_unavailable_is_not_mathematical_invalid_or_null(self):
        base = snapshot(
            functions=(self.add,),
            pins=(self.a, self.b),
            capabilities=({"capability_class": "vector.add", "status": "unavailable"},),
        )
        engine = MathValidityEngine(base)
        admission = engine.preflight(candidate_for(self.add, (self.a, self.b)))
        self.assertEqual(admission.verdict, UNAVAILABLE)
        self.assertEqual(admission.reason, "CAPABILITY_UNAVAILABLE")
        self.assertEqual(admission.scope["math_verdict"], VALID)
        self.assertNotIn(admission.verdict, {INVALID, UNDEFINED, "NULL"})
        with self.assertRaises(AdmissionRejected) as raised:
            engine.require_admission(admission)
        self.assertEqual(raised.exception.verdict, UNAVAILABLE)

        available = snapshot(
            functions=(self.add,),
            pins=(self.a, self.b),
            capabilities=({"capability_class": "vector.add", "status": "native_verified"},),
        )
        engine = MathValidityEngine(available)
        self.assertEqual(
            engine.preflight(candidate_for(self.add, (self.a, self.b))).verdict,
            VALID,
        )

    def test_authorization_and_capability_are_separate_outcomes(self):
        denied = snapshot(
            functions=(self.add,),
            pins=(self.a, self.b),
            authorization={"allowed": False},
            capabilities=({"capability_class": "vector.add", "status": "unavailable"},),
        )
        engine = MathValidityEngine(denied)
        admission = engine.preflight(candidate_for(self.add, (self.a, self.b)))
        self.assertEqual(admission.verdict, "UNAUTHORIZED")
        self.assertEqual(admission.scope["math_verdict"], VALID)

        allowed = snapshot(
            functions=(self.add,),
            pins=(self.a, self.b),
            authorization={"allowed": True},
            capabilities=({"capability_class": "vector.add", "status": "unavailable"},),
        )
        engine = MathValidityEngine(allowed)
        admission = engine.preflight(candidate_for(self.add, (self.a, self.b)))
        self.assertEqual(admission.verdict, UNAVAILABLE)
        self.assertEqual(admission.scope["authorization"]["status"], "ALLOWED")

    def test_contradiction_blocks_only_affected_function_without_last_writer(self):
        first_rule = rule_definition(
            "math.rule.vector.assoc", claims={"associative": True},
        )
        second_rule = rule_definition(
            "math.rule.vector.not_assoc", claims={"associative": False},
        )
        for rules in ((first_rule, second_rule), (second_rule, first_rule)):
            base = snapshot(
                functions=(self.add, self.dot),
                rules=rules,
                pins=(self.a, self.b),
            )
            engine = MathValidityEngine(base)
            admission = engine.preflight(candidate_for(self.add, (self.a, self.b)))
            self.assertEqual(admission.verdict, INVALID)
            self.assertTrue(admission.reason.startswith("CONTRADICTION:"))
            self.assertIn("math.rule.vector.assoc", admission.reason)
            self.assertIn("math.rule.vector.not_assoc", admission.reason)
            dot_admission = engine.preflight(candidate_for(self.dot, (self.a, self.b)))
            self.assertEqual(dot_admission.verdict, VALID)

    def test_level3_is_isolation_only_and_cannot_self_promote(self):
        experimental = rule_definition(
            "math.rule.experimental.add",
            level=3,
            function_ids=("math.vector.add",),
        )
        isolated_add = vector_add(
            semantics={"rule_ids": ["math.rule.experimental.add"]},
        )
        base = snapshot(
            functions=(isolated_add, self.dot),
            rules=(experimental,),
            pins=(self.a, self.b),
        )
        engine = MathValidityEngine(base)
        admission = engine.preflight(candidate_for(isolated_add, (self.a, self.b)))
        self.assertEqual(admission.verdict, EXPERIMENTAL)
        self.assertTrue(admission.scope["isolated"])
        self.assertEqual(admission.scope["rule_level"], 3)
        with self.assertRaises(AdmissionRejected) as raised:
            engine.require_admission(admission)
        self.assertEqual(raised.exception.verdict, EXPERIMENTAL)
        with self.assertRaises(AdmissionRejected):
            engine.require_admission(
                admission,
                plan=plan_for(admission),
                allow_experimental=True,
            )
        engine.require_admission(
            admission,
            plan=plan_for(admission, isolated=True),
            allow_experimental=True,
        )
        self.assertEqual(
            engine.preflight(candidate_for(self.dot, (self.a, self.b))).verdict,
            VALID,
        )

        production_claim = rule_definition(
            "math.rule.experimental.add",
            level=3,
            function_ids=("math.vector.add",),
            contract_extra={"production": True},
        )
        base = snapshot(
            functions=(isolated_add,),
            rules=(production_claim,),
            pins=(self.a, self.b),
        )
        engine = MathValidityEngine(base)
        admission = engine.preflight(candidate_for(isolated_add, (self.a, self.b)))
        self.assertEqual(admission.verdict, INVALID)
        self.assertEqual(admission.reason, "SELF_PROMOTION_FORBIDDEN")

        promoted = snapshot(
            SNP2,
            functions=(isolated_add, self.dot),
            rules=(rule_definition(
                "math.rule.experimental.add", version=2, level=1,
                function_ids=("math.vector.add",),
            ),),
            pins=(self.a, self.b),
        )
        with self.assertRaises(MathSnapshotError) as raised:
            engine.install_snapshot(promoted)
        self.assertIn("RULE_LEVEL_CHANGE_REQUIRES_PROMOTION", str(raised.exception))

    def test_level0_rule_is_immutable_across_snapshots(self):
        level0 = rule_definition("math.rule.core.types", level=0)
        base = snapshot(
            functions=(self.add,),
            rules=(level0,),
            pins=(self.a, self.b),
        )
        engine = MathValidityEngine(base)
        changed = snapshot(
            SNP2,
            functions=(self.add,),
            rules=(rule_definition(
                "math.rule.core.types", version=2, level=0,
                claims={"changed": True},
            ),),
            pins=(self.a, self.b),
        )
        with self.assertRaises(MathSnapshotError) as raised:
            engine.install_snapshot(changed)
        self.assertIn("LEVEL0_IMMUTABLE", str(raised.exception))
        removed = snapshot(
            SNP2,
            functions=(self.add,),
            rules=(),
            pins=(self.a, self.b),
        )
        with self.assertRaises(MathSnapshotError) as raised:
            engine.install_snapshot(removed)
        self.assertIn("LEVEL0_IMMUTABLE", str(raised.exception))

    def test_numeric_predicate_requires_pinned_certificate_digest(self):
        constraint = {"op": "lte", "path": "inputs.0.type.max_abs", "value": "1"}
        function = vector_norm(preconditions=(constraint,))
        pin = leaf_pin("nml:U0:vector:norm", (256,), type_extra={"max_abs": 1})
        base = snapshot(functions=(function,), pins=(pin,))
        engine = MathValidityEngine(base)
        candidate = candidate_for(function, (pin,))
        admission = engine.preflight(candidate)
        self.assertEqual(admission.verdict, UNKNOWN)
        self.assertEqual(
            admission.reason, "NUMERIC_PREDICATE_CERTIFICATE_REQUIRED",
        )

        certified = vector_norm(preconditions=(
            dict(constraint, certificate_digest=CERT),
        ))
        base = snapshot(
            functions=(certified,), pins=(pin,), certificates=(CERT,),
        )
        engine = MathValidityEngine(base)
        self.assertEqual(
            engine.preflight(candidate_for(certified, (pin,))).verdict,
            VALID,
        )

        declared_only = snapshot(functions=(certified,), pins=(pin,))
        engine = MathValidityEngine(declared_only)
        admission = engine.preflight(candidate_for(certified, (pin,)))
        self.assertEqual(admission.verdict, UNKNOWN)
        self.assertEqual(admission.reason, "CERTIFICATE_NOT_PINNED")

        unpinned = vector_norm(preconditions=(
            dict(constraint, certificate_digest="d" * 64),
        ))
        base = snapshot(
            functions=(unpinned,), pins=(pin,), certificates=(CERT,),
        )
        engine = MathValidityEngine(base)
        admission = engine.preflight(candidate_for(unpinned, (pin,)))
        self.assertEqual(admission.verdict, UNKNOWN)
        self.assertEqual(admission.reason, "CERTIFICATE_NOT_PINNED")

        malformed = vector_norm(preconditions=(
            dict(constraint, certificate_digest="not-a-digest"),
        ))
        base = snapshot(functions=(malformed,), pins=(pin,))
        engine = MathValidityEngine(base)
        admission = engine.preflight(candidate_for(malformed, (pin,)))
        self.assertEqual(admission.verdict, INVALID)
        self.assertEqual(admission.reason, "CERTIFICATE_MALFORMED")

    def test_typed_layout_precision_domain_alias_and_workspace_checks(self):
        def check(pin, function, expected_reason):
            base = snapshot(functions=(function,), pins=(pin,), resources={"workspace_words": 1000})
            engine = MathValidityEngine(base)
            admission = engine.preflight(candidate_for(function, (pin, pin)))
            self.assertEqual(admission.verdict, INVALID)
            self.assertEqual(admission.reason, expected_reason)
            return admission

        wrong_precision = leaf_pin("nml:U0:vector:p64", (256,), precision="float64")
        check(wrong_precision, self.add, "PRECISION_MISMATCH")

        wrong_layout = leaf_pin("nml:U0:vector:col", (256,), layout="column_major")
        check(wrong_layout, self.add, "LAYOUT_MISMATCH")

        integer_function = MathFunction(
            function_id="math.vector.integer_add",
            version=1,
            signature={
                "inputs": [
                    vector_spec("a", domain="integer"),
                    vector_spec("b", domain="integer"),
                ],
                "output": vector_spec("out", domain="integer"),
            },
            implementations=({"kernel_id": "mth.vector.add256.i32", "status": "declared"},),
        )
        real_pin = leaf_pin("nml:U0:vector:real", (256,), domain="real")
        base = snapshot(functions=(integer_function,), pins=(real_pin,))
        engine = MathValidityEngine(base)
        admission = engine.preflight(candidate_for(integer_function, (real_pin, real_pin)))
        self.assertEqual(admission.verdict, INVALID)
        self.assertEqual(admission.reason, "DOMAIN_MISMATCH")

        heavy = leaf_pin("nml:U0:vector:heavy", (256,), workspace_words=60)
        base = snapshot(
            functions=(self.add,),
            pins=(heavy,),
            resources={"workspace_words": 100},
        )
        engine = MathValidityEngine(base)
        admission = engine.preflight(candidate_for(self.add, (heavy, heavy)))
        self.assertEqual(admission.verdict, INVALID)
        self.assertEqual(admission.reason, "WORKSPACE_EXCEEDED")

        aliased = leaf_pin("nml:U0:vector:aliased", (256,), kind="vec")
        base = snapshot(
            functions=(self.add,),
            pins=(aliased,),
            aliases={"vec": "vector"},
        )
        engine = MathValidityEngine(base)
        self.assertEqual(
            engine.preflight(candidate_for(self.add, (aliased, aliased))).verdict,
            VALID,
        )

        conflict = snapshot(
            functions=(self.add,),
            pins=(self.a, self.b),
            aliases=(
                {"alias": "vec", "target": "vector"},
                {"alias": "vec", "target": "matrix"},
            ),
        )
        engine = MathValidityEngine(conflict)
        admission = engine.preflight(candidate_for(self.add, (self.a, self.b)))
        self.assertEqual(admission.verdict, INVALID)
        self.assertEqual(admission.reason, "ALIAS_CONFLICT")

    def test_invalid_preflight_and_missing_binding_cannot_execute(self):
        engine = MathValidityEngine(self.base_snapshot)
        valid = engine.preflight(candidate_for(self.add, (self.a, self.b)))
        self.assertIs(
            engine.require_admission(None, plan={"preflight_digest": valid.preflight_digest}),
            valid,
        )
        with self.assertRaises(AdmissionRejected) as raised:
            engine.require_admission(valid, plan={"candidate_id": valid.candidate_id})
        self.assertEqual(raised.exception.reason, "PLAN_MISSING_ADMISSION")

        mismatch = plan_for(valid, preflight_digest="pf:" + "e" * 64)
        with self.assertRaises(AdmissionRejected) as raised:
            engine.require_admission(valid, plan=mismatch)
        self.assertEqual(raised.exception.reason, "PLAN_PREFLIGHT_DIGEST_MISMATCH")

        short = leaf_pin("nml:U0:vector:short", (128,))
        base = snapshot(functions=(self.add,), pins=(self.a, short))
        engine = MathValidityEngine(base)
        invalid = engine.preflight(candidate_for(self.add, (self.a, short)))
        with self.assertRaises(AdmissionRejected) as raised:
            engine.require_admission(invalid, plan=plan_for(invalid))
        self.assertEqual(raised.exception.verdict, INVALID)

        forged = MathAdmission(
            admission_id_for(invalid.candidate_id, invalid.snapshot_id, VALID),
            invalid.candidate_id,
            VALID,
            invalid.snapshot_id,
            rule_snapshot_id=engine.rule_snapshot_id,
            preflight_digest="pf:" + "f" * 64,
        )
        with self.assertRaises(AdmissionRejected) as raised:
            engine.require_admission(forged)
        self.assertEqual(raised.exception.verdict, UNKNOWN)

    def test_stale_function_and_leaf_version_pins(self):
        engine = MathValidityEngine(self.base_snapshot)
        newer_function = candidate_for(
            self.add, (self.a, self.b), version=2,
        )
        admission = engine.preflight(newer_function)
        self.assertEqual(admission.verdict, STALE)
        self.assertEqual(admission.reason, "STALE_FUNCTION_VERSION")

        newer_leaf = dict(refs_for((self.a,))[0])
        newer_leaf["version"] = 2
        inputs = (newer_leaf, refs_for((self.b,))[0])
        identifier = candidate_id_for(
            SNP1, inputs, self.add.function_id, self.add.version,
        )
        candidate = MathCandidate(
            identifier, inputs, self.add.function_id, self.add.version,
            snapshot_id=SNP1,
        )
        admission = engine.preflight(candidate)
        self.assertEqual(admission.verdict, STALE)
        self.assertEqual(admission.reason, "STALE_LEAF_VERSION")

    def test_unknown_snapshot_pin_is_unknown_not_zero(self):
        engine = MathValidityEngine(self.base_snapshot)
        missing = leaf_pin("nml:U0:vector:absent", (256,))
        candidate = MathCandidate(
            candidate_id_for(SNP1, ({"leaf_id": missing["leaf_id"], "version": 1},),
                             self.add.function_id, self.add.version),
            ({"leaf_id": missing["leaf_id"], "version": 1},),
            self.add.function_id,
            self.add.version,
            snapshot_id=SNP1,
        )
        admission = engine.preflight(candidate)
        self.assertEqual(admission.verdict, UNKNOWN)
        self.assertEqual(admission.reason, "LEAF_NOT_PINNED")
        with self.assertRaises(AdmissionRejected):
            engine.require_admission(admission)

    def test_postconditions_are_structured_obligations(self):
        shape_post = {
            "op": "shape_equal",
            "left": {"output": 0, "field": "type.shape"},
            "right": {"literal": [256]},
        }
        function = vector_add(postconditions=(shape_post,))
        output = {
            "type": {"kind": "vector", "shape": [256]},
        }
        candidate = candidate_for(
            function, (self.a, self.b), outputs=(output,),
        )
        base = snapshot(functions=(function,), pins=(self.a, self.b))
        engine = MathValidityEngine(base)
        admission = engine.preflight(candidate)
        self.assertEqual(admission.verdict, VALID)
        self.assertEqual(admission.scope["obligations"][0]["status"], "SATISFIED")

        no_output = candidate_for(function, (self.a, self.b))
        admission = engine.preflight(no_output)
        self.assertEqual(admission.verdict, VALID)
        self.assertEqual(admission.scope["obligations"][0]["status"], "UNKNOWN")
        enforced = engine.preflight(no_output, enforce_postconditions=True)
        self.assertEqual(enforced.verdict, UNKNOWN)
        self.assertEqual(enforced.reason, "OPERAND_NOT_ESTABLISHED")

    def test_structured_predicate_helper_and_metadata(self):
        function = vector_add()
        context = {
            "candidate": candidate_for(function, (self.a, self.b)),
            "function": function,
            "snapshot": self.base_snapshot,
            "inputs": (
                {"type": {"shape": [256]}},
                {"type": {"shape": [256]}},
            ),
            "outputs": (),
            "certificates": (),
        }
        result = evaluate_predicates(
            (
                {
                    "op": "shape_equal",
                    "left": {"input": 0, "field": "type.shape"},
                    "right": {"input": 1, "field": "type.shape"},
                },
                {
                    "op": "gte",
                    "path": "inputs.0.type.rank",
                    "value": 1,
                },
            ),
            context,
        )
        self.assertEqual(result[0].status, "SATISFIED")
        self.assertEqual(result[1].status, "UNKNOWN")
        self.assertEqual(
            result[1].reason, "NUMERIC_PREDICATE_CERTIFICATE_REQUIRED",
        )

    def test_no_host_float_or_forbidden_runtime_import(self):
        source_path = Path(__file__).resolve().parents[1] / "runner_riddle" / "math_validity.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        forbidden_imports = {
            "math", "numpy", "cmath", "statistics", "decimal", "fractions",
        }
        forbidden_fragments = (
            "mth_system", "wave_service", "executor", "live_preflight",
            "point0", "r7_experiment",
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name.split(".")[0], forbidden_imports)
                    self.assertFalse(any(
                        fragment in alias.name for fragment in forbidden_fragments
                    ))
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                self.assertNotIn(module.split(".")[0], forbidden_imports)
                self.assertFalse(any(
                    fragment in module for fragment in forbidden_fragments
                ))
            elif isinstance(node, ast.Constant) and isinstance(node.value, float):
                self.fail(f"host float literal at line {node.lineno}")

        function = vector_norm(preconditions=(
            {"op": "lt", "path": "inputs.0.type.rank", "value": 1.5},
        ))
        pin = leaf_pin("nml:U0:vector:float", (256,), type_extra={"rank": 1})
        base = snapshot(functions=(function,), pins=(pin,))
        engine = MathValidityEngine(base)
        admission = engine.preflight(candidate_for(function, (pin,)))
        self.assertEqual(admission.verdict, UNKNOWN)
        self.assertEqual(admission.reason, "HOST_FLOAT_FORBIDDEN")
        with self.assertRaises(AdmissionRejected):
            engine.require_admission(admission)

    def test_module_level_preflight_and_require_admission(self):
        admission = preflight(
            candidate_for(self.add, (self.a, self.b)),
            self.base_snapshot,
        )
        self.assertEqual(admission.verdict, VALID)
        self.assertIs(
            require_admission(admission, self.base_snapshot),
            admission,
        )
        engine = MathValidityEngine(self.base_snapshot)
        issued = engine.preflight(candidate_for(self.add, (self.a, self.b)))
        plan = plan_for(issued)
        self.assertIs(require_admission(issued, plan, engine=engine), issued)
        stale_snapshot = snapshot(
            SNP2,
            functions=(self.add,),
            pins=(self.a, self.b),
        )
        with self.assertRaises(AdmissionRejected) as raised:
            require_admission(admission, stale_snapshot)
        self.assertEqual(raised.exception.verdict, STALE)

    def test_snapshot_mapping_and_cache_object_are_accepted(self):
        document = self.base_snapshot.to_dict()
        coerced = coerce_snapshot(document)
        self.assertEqual(coerced.snapshot_id, SNP1)
        self.assertEqual(coerced.rule_snapshot_id, self.base_snapshot.rule_snapshot_id)
        cache = MathPreflightCache(max_entries=2)
        engine = MathValidityEngine(document, cache=cache)
        admission = engine.preflight(candidate_for(self.add, (self.a, self.b)))
        self.assertEqual(admission.verdict, VALID)
        self.assertEqual(engine.cache.stats()["dispatch_size"], 1)


if __name__ == "__main__":
    unittest.main()
