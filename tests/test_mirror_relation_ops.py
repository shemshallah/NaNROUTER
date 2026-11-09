"""Round 027 typed relation operators: explicit rules, no Round 028 paths."""
from __future__ import annotations

import ast
import inspect
import json
import unittest

from runner_riddle import mirror_relation_ops
from runner_riddle.mirror_relation_ops import (
    DEFAULT_MAX_PATH_STEPS,
    DIRECTION_FORWARD,
    DIRECTION_REVERSE,
    DIRECTION_SYMMETRIC,
    DIRECTION_VALUES,
    MAX_PATH_STEPS,
    OP_STATUS_DECLARED,
    OP_STATUS_NATIVE_VERIFIED,
    REASON_BOUND_HARD_LIMIT,
    REASON_COMPOSITION_NOT_DECLARED,
    REASON_DIRECTION_NOT_ALLOWED,
    REASON_DOMAIN_CODOMAIN_MISMATCH,
    REASON_DUPLICATE_OPERATOR,
    REASON_EMPTY_CHAIN,
    REASON_EXPLICIT_CHAIN_REQUIRED,
    REASON_INVALID_BOUND,
    REASON_INVALID_DESCRIPTOR,
    REASON_NATIVE_UNAVAILABLE,
    REASON_NONCOMMUTING,
    REASON_REVERSE_NOT_DECLARED,
    REASON_STEP_LIMIT,
    REASON_UNKNOWN_OPERATOR,
    REASON_UNORDERED_CHAIN,
    RESULT_STATUS_PLANNED,
    RESULT_STATUS_REJECTED,
    RESULT_STATUS_UNAVAILABLE,
    ROUND,
    ROUND_028_IMPLEMENTED,
    RelationBoundError,
    RelationCompositionError,
    RelationDescriptorError,
    RelationDirectionError,
    RelationNoncommutingError,
    RelationOperatorDescriptor,
    RelationOperatorRegistry,
    RelationUnavailableError,
    UnknownOperatorError,
    canonical_relation_json,
    plan_digest,
)

CANDIDATES = (
    "is_a", "part_of", "causes", "supports",
    "refutes", "equivalent", "transforms", "observes",
)


def native_descriptor(operator_id, **overrides):
    fields = dict(
        id=operator_id,
        domain="entity",
        codomain="entity",
        composition_rules=("transforms", "equivalent"),
        direction=DIRECTION_FORWARD,
        noncommuting=True,
        status=OP_STATUS_NATIVE_VERIFIED,
        native_implementation_requirement=(
            f"mth.relation.{operator_id}.q16.16"
        ),
        native_implementation=f"mth.relation.{operator_id}.q16.16",
        evidence=(f"native-fixture:{operator_id}",),
    )
    fields.update(overrides)
    return RelationOperatorDescriptor(**fields)


class RelationOperatorRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = RelationOperatorRegistry()

    def test_candidates_are_typed_declared_and_not_validated(self):
        self.assertEqual(self.registry.operator_ids, CANDIDATES)
        self.assertEqual(set(self.registry.status()["operator_ids"]), set(CANDIDATES))
        for operator_id in CANDIDATES:
            with self.subTest(operator_id=operator_id):
                descriptor = self.registry.require(operator_id)
                self.assertEqual(descriptor.id, operator_id)
                self.assertIsInstance(descriptor.domain, str)
                self.assertIsInstance(descriptor.codomain, str)
                self.assertIsInstance(descriptor.composition_rules, tuple)
                self.assertIn(descriptor.direction, DIRECTION_VALUES)
                self.assertIsInstance(descriptor.noncommuting, bool)
                self.assertEqual(descriptor.status, OP_STATUS_DECLARED)
                self.assertTrue(descriptor.native_implementation_requirement)
                self.assertIsNone(descriptor.native_implementation)
                self.assertTrue(descriptor.evidence)
                self.assertFalse(descriptor.native_available)
                self.assertFalse(descriptor.validated)
                document = descriptor.to_dict()
                self.assertFalse(document["native_execution_verified"])
                self.assertFalse(document["mathematical_truth_promoted"])
                self.assertFalse(document["authority_granted"])

        report = self.registry.status()
        self.assertEqual(report["round"], ROUND)
        self.assertFalse(report["round_028_implemented"])
        self.assertFalse(report["generalization"])
        self.assertFalse(report["unseen_path_inference"])
        self.assertFalse(report["implicit_transitivity"])
        self.assertFalse(report["inheritance_inference"])
        self.assertTrue(report["declared_only_is_unavailable"])
        self.assertEqual(report["status_counts"][OP_STATUS_DECLARED], len(CANDIDATES))
        self.assertEqual(report["native_available"], [])
        self.assertEqual(set(report["unavailable"]), set(CANDIDATES))
        self.assertFalse(report["native_execution_verified"])
        self.assertFalse(report["mathematical_truth_promoted"])
        self.assertFalse(report["authority_granted"])
        self.assertEqual(self.registry.status("is_a")["id"], "is_a")

    def test_duplicate_registration_and_unverifiable_native_claim(self):
        with self.assertRaises(RelationDescriptorError) as caught:
            self.registry.register(
                RelationOperatorDescriptor(
                    id="is_a", domain="entity", codomain="category",
                )
            )
        self.assertEqual(caught.exception.reason, REASON_DUPLICATE_OPERATOR)

        for fields in (
            {"status": OP_STATUS_NATIVE_VERIFIED,
             "native_implementation": "mth.relation.bad.q16.16",
             "evidence": ()},
            {"status": OP_STATUS_NATIVE_VERIFIED,
             "evidence": ("declared-but-not-implemented",)},
        ):
            with self.subTest(fields=fields):
                with self.assertRaises(RelationDescriptorError) as caught:
                    RelationOperatorDescriptor(id="bad", **fields)
                self.assertEqual(caught.exception.reason, REASON_INVALID_DESCRIPTOR)

    def test_explicit_composition_allow_and_deny(self):
        allowed = (
            ("transforms", "transforms"),
            ("transforms", "equivalent"),
            ("equivalent", "transforms"),
            ("equivalent", "equivalent"),
            ("part_of", "equivalent"),
            ("causes", "equivalent"),
            ("supports", "equivalent"),
            ("refutes", "equivalent"),
        )
        for left, right in allowed:
            with self.subTest(left=left, right=right):
                self.assertTrue(self.registry.compatible(left, right))
                decision = self.registry.explain_compatible(left, right)
                self.assertTrue(decision.compatible)
                self.assertIsNone(decision.reason)
                result = self.registry.compose((left, right))
                self.assertEqual(result.status, RESULT_STATUS_UNAVAILABLE)
                self.assertTrue(result.composition_valid)
                self.assertEqual(result.reason, REASON_NATIVE_UNAVAILABLE)

        denied = (
            ("is_a", "is_a"),
            ("part_of", "part_of"),
            ("causes", "causes"),
            ("supports", "supports"),
            ("refutes", "refutes"),
            ("is_a", "part_of"),
            ("transforms", "part_of"),
            ("observes", "equivalent"),
        )
        for left, right in denied:
            with self.subTest(left=left, right=right):
                self.assertFalse(self.registry.compatible(left, right))
                decision = self.registry.explain_compatible(left, right)
                self.assertFalse(decision.compatible)
                self.assertIn(
                    decision.reason,
                    (REASON_COMPOSITION_NOT_DECLARED,
                     REASON_DOMAIN_CODOMAIN_MISMATCH),
                )
                with self.assertRaises(RelationCompositionError) as caught:
                    self.registry.compose((left, right))
                self.assertIn(
                    caught.exception.reason,
                    (REASON_COMPOSITION_NOT_DECLARED,
                     REASON_DOMAIN_CODOMAIN_MISMATCH),
                )

    def test_directionality_never_infers_an_inverse(self):
        self.assertEqual(
            self.registry.require("equivalent").direction,
            DIRECTION_SYMMETRIC,
        )
        self.assertEqual(
            self.registry.require("is_a").direction,
            DIRECTION_FORWARD,
        )
        self.assertTrue(self.registry.compatible(
            "equivalent", "equivalent", direction=DIRECTION_REVERSE,
        ))
        reversed_plan = self.registry.compose(
            ("equivalent", "equivalent"), direction=DIRECTION_REVERSE,
        )
        self.assertEqual(reversed_plan.status, RESULT_STATUS_UNAVAILABLE)
        self.assertEqual(
            reversed_plan.chain, ("equivalent", "equivalent")
        )
        self.assertEqual(reversed_plan.direction, DIRECTION_REVERSE)

        for operator_id in ("is_a", "part_of", "transforms", "observes"):
            with self.subTest(operator_id=operator_id):
                with self.assertRaises(RelationDirectionError) as caught:
                    self.registry.compose(
                        (operator_id,), direction=DIRECTION_REVERSE,
                    )
                self.assertEqual(
                    caught.exception.reason, REASON_REVERSE_NOT_DECLARED,
                )
                self.assertFalse(self.registry.compatible(
                    operator_id, operator_id,
                    direction=DIRECTION_REVERSE,
                ))

    def test_noncommuting_rejection_and_unordered_input(self):
        decision = self.registry.explain_compatible(
            "transforms", "transforms", commute=True,
        )
        self.assertFalse(decision.compatible)
        self.assertEqual(decision.reason, REASON_NONCOMMUTING)
        self.assertFalse(self.registry.compatible(
            "transforms", "transforms", commute=True,
        ))
        with self.assertRaises(RelationNoncommutingError) as caught:
            self.registry.compose(
                ("transforms", "transforms"), commute=True,
            )
        self.assertEqual(caught.exception.reason, REASON_NONCOMMUTING)
        self.assertTrue(self.registry.compatible(
            "equivalent", "equivalent", commute=True,
        ))

        for unordered in (
            {"transforms", "equivalent"},
            frozenset(("transforms", "equivalent")),
        ):
            with self.subTest(kind=type(unordered).__name__):
                with self.assertRaises(RelationCompositionError) as caught:
                    self.registry.compose(unordered)
                self.assertEqual(
                    caught.exception.reason, REASON_UNORDERED_CHAIN,
                )

    def test_unknown_operator_is_typed(self):
        with self.assertRaises(UnknownOperatorError) as caught:
            self.registry.require("not_declared")
        self.assertEqual(caught.exception.reason, REASON_UNKNOWN_OPERATOR)
        with self.assertRaises(UnknownOperatorError):
            self.registry.compatible("not_declared", "equivalent")
        with self.assertRaises(UnknownOperatorError):
            self.registry.compose(("not_declared",))
        rejected = self.registry.plan_path(
            {"operators": ("not_declared",), "max_steps": 2},
        )
        self.assertEqual(rejected.status, RESULT_STATUS_REJECTED)
        self.assertEqual(rejected.reason, REASON_UNKNOWN_OPERATOR)

    def test_unavailable_is_typed_and_never_evaluated(self):
        result = self.registry.compose(("transforms", "transforms"))
        self.assertEqual(result.status, RESULT_STATUS_UNAVAILABLE)
        self.assertFalse(result.available)
        self.assertEqual(result.reason, REASON_NATIVE_UNAVAILABLE)
        self.assertTrue(result.composition_valid)
        self.assertFalse(result.native_implementation_available)
        self.assertEqual(
            result.unavailable_operators,
            ("transforms", "transforms"),
        )
        self.assertIsNone(result.plan_digest)
        document = result.to_dict()
        self.assertEqual(document["status"], RESULT_STATUS_UNAVAILABLE)
        self.assertFalse(document["native_execution_verified"])
        self.assertFalse(document["mathematical_truth_promoted"])
        self.assertFalse(document["authority_granted"])
        self.assertFalse(document["generalization"])
        self.assertFalse(document["round_028_implemented"])
        with self.assertRaises(RelationUnavailableError) as caught:
            result.require_plan()
        self.assertEqual(caught.exception.reason, REASON_NATIVE_UNAVAILABLE)

    def test_native_verified_chain_plans_without_executing(self):
        registry = RelationOperatorRegistry()
        registry.register(
            native_descriptor(
                "transforms",
                composition_rules=("transforms", "equivalent"),
            ),
            replace=True,
        )
        result = registry.compose(("transforms", "transforms"))
        self.assertEqual(result.status, RESULT_STATUS_PLANNED)
        self.assertTrue(result.available)
        self.assertTrue(result.composition_valid)
        self.assertTrue(result.native_implementation_available)
        self.assertIs(result.require_plan(), result)
        self.assertRegex(result.plan_digest, r"^[0-9a-f]{64}$")
        self.assertEqual(result.plan_digest, plan_digest(result))
        self.assertFalse(result.to_dict()["native_execution_verified"])
        self.assertFalse(result.to_dict()["mathematical_truth_promoted"])
        self.assertFalse(result.to_dict()["authority_granted"])

        partial = registry.compose(("transforms", "equivalent"))
        self.assertEqual(partial.status, RESULT_STATUS_UNAVAILABLE)
        self.assertEqual(partial.unavailable_operators, ("equivalent",))

    def test_bounded_path_length_and_no_unseen_path_search(self):
        chain = ("transforms",) * (DEFAULT_MAX_PATH_STEPS + 1)
        with self.assertRaises(RelationBoundError) as caught:
            self.registry.compose(chain)
        self.assertEqual(caught.exception.reason, REASON_STEP_LIMIT)
        self.assertEqual(
            self.registry.compose(
                chain, max_steps=MAX_PATH_STEPS,
            ).status,
            RESULT_STATUS_UNAVAILABLE,
        )
        with self.assertRaises(RelationBoundError) as caught:
            self.registry.compose(chain, max_steps=MAX_PATH_STEPS + 1)
        self.assertEqual(
            caught.exception.reason, REASON_BOUND_HARD_LIMIT,
        )

        rejected = self.registry.plan_path(chain)
        self.assertEqual(rejected.status, RESULT_STATUS_REJECTED)
        self.assertEqual(rejected.reason, REASON_STEP_LIMIT)
        rejected_hard = self.registry.plan_path(
            {"chain": chain, "max_steps": MAX_PATH_STEPS + 1},
        )
        self.assertEqual(rejected_hard.status, RESULT_STATUS_REJECTED)
        self.assertEqual(rejected_hard.reason, REASON_BOUND_HARD_LIMIT)
        rejected_bound = self.registry.plan_path(
            {"chain": ("transforms",), "max_steps": "four"},
        )
        self.assertEqual(rejected_bound.status, RESULT_STATUS_REJECTED)
        self.assertEqual(rejected_bound.reason, REASON_INVALID_BOUND)

        endpoint_only = self.registry.plan_path({
            "source": "claim:a",
            "target": "claim:b",
            "max_steps": 4,
        })
        self.assertEqual(endpoint_only.status, RESULT_STATUS_REJECTED)
        self.assertEqual(
            endpoint_only.reason, REASON_EXPLICIT_CHAIN_REQUIRED,
        )
        empty = self.registry.plan_path({"chain": ()})
        self.assertEqual(empty.status, RESULT_STATUS_REJECTED)
        self.assertEqual(empty.reason, REASON_EMPTY_CHAIN)

        bounded = self.registry.plan_path({
            "chain": chain[:DEFAULT_MAX_PATH_STEPS],
            "max_steps": DEFAULT_MAX_PATH_STEPS,
        })
        self.assertEqual(bounded.status, RESULT_STATUS_UNAVAILABLE)

    def test_deterministic_json_and_plan_digest(self):
        first = RelationOperatorRegistry()
        second = RelationOperatorRegistry()
        query = {"operators": ("transforms", "transforms"), "max_steps": 4}
        first_result = first.plan_path(query)
        second_result = second.plan_path(query)
        self.assertEqual(first_result.to_dict(), second_result.to_dict())
        self.assertEqual(
            canonical_relation_json(first_result.to_dict()),
            canonical_relation_json(second_result.to_dict()),
        )
        self.assertEqual(
            json.dumps(first_result.to_dict(), sort_keys=True),
            json.dumps(second_result.to_dict(), sort_keys=True),
        )
        self.assertEqual(first.status(), second.status())
        self.assertIsNone(first_result.plan_digest)

        first.register(native_descriptor(
            "transforms",
            composition_rules=("transforms", "equivalent"),
        ), replace=True)
        second.register(native_descriptor(
            "transforms",
            composition_rules=("transforms", "equivalent"),
        ), replace=True)
        first_plan = first.plan_path({"chain": ("transforms", "transforms")})
        second_plan = second.plan_path({"chain": ("transforms", "transforms")})
        self.assertEqual(first_plan.status, RESULT_STATUS_PLANNED)
        self.assertEqual(first_plan.plan_digest, second_plan.plan_digest)
        self.assertEqual(first_plan.plan_digest, plan_digest(first_plan))
        shorter = first.plan_path({"chain": ("transforms",)})
        self.assertNotEqual(first_plan.plan_digest, shorter.plan_digest)


class RelationOperatorBoundaryTests(unittest.TestCase):
    def test_no_host_math_imports_or_evaluation_bypass(self):
        source = inspect.getsource(mirror_relation_ops)
        tree = ast.parse(source)
        forbidden_imports = {
            "math", "numpy", "scipy", "sympy", "subprocess", "ctypes",
            "mmap", "sqlite3", "socket",
        }
        forbidden_calls = {
            "abs", "complex", "divmod", "eval", "exec", "float", "max",
            "min", "pow", "round", "sum",
        }
        arithmetic_ops = (
            ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
            ast.Mod, ast.Pow, ast.MatMult,
        )
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".", 1)[0]
                    self.assertNotIn(root, forbidden_imports)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                root = (node.module or "").split(".", 1)[0]
                self.assertNotIn(root, forbidden_imports)
            elif isinstance(node, ast.BinOp):
                self.assertNotIsInstance(node.op, arithmetic_ops)
            elif isinstance(node, ast.AugAssign):
                self.assertNotIsInstance(node.op, arithmetic_ops)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, forbidden_calls)

        for name in (
            "execute", "dispatch", "submit", "run", "apply", "evaluate",
            "infer",
        ):
            self.assertFalse(hasattr(mirror_relation_ops, name))
            self.assertFalse(hasattr(RelationOperatorRegistry, name))
        self.assertFalse(callable(RelationOperatorRegistry()))

    def test_no_authority_leak(self):
        self.assertFalse(ROUND_028_IMPLEMENTED)
        report = RelationOperatorRegistry().status()
        self.assertEqual(report["round"], ROUND)
        self.assertFalse(report["round_028_implemented"])
        self.assertFalse(report["generalization"])
        self.assertFalse(report["unseen_path_inference"])
        self.assertFalse(report["implicit_transitivity"])
        self.assertFalse(report["inheritance_inference"])
        self.assertFalse(report["native_execution_verified"])
        self.assertFalse(report["mathematical_truth_promoted"])
        self.assertFalse(report["authority_granted"])

        result = RelationOperatorRegistry().compose(
            ("equivalent", "equivalent")
        )
        document = result.to_dict()
        for key in (
            "native_execution_verified", "mathematical_truth_promoted",
            "authority_granted", "generalization", "round_028_implemented",
        ):
            self.assertFalse(document[key], key)
        self.assertEqual(
            document["unavailable_operators"],
            ["equivalent", "equivalent"],
        )


if __name__ == "__main__":
    unittest.main()
