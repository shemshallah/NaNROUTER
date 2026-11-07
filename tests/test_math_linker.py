from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path
import unittest

from runner_riddle.math_objects import MathFunction, MathLeaf, MathRule, candidate_id_for
from runner_riddle.math_linker import (
    LinkBounds,
    LinkError,
    LinkQuery,
    MathLinker,
    TransformGoal,
    classify_leaf,
    parse_link_query,
    parse_ref,
    propose,
)


SNAPSHOT_ID = "snp:" + "a" * 64


def vector_leaf(index: int, length: int = 128, *, domain: str = "real",
                layout: str = "row_major", version: int = 1) -> MathLeaf:
    digest_char = "0123456789abcdef"[index % 16]
    return MathLeaf(
        leaf_id=f"nml:U0:vector:{index}",
        version=version,
        kind="vector",
        type={
            "name": "vector",
            "domain": domain,
            "shape": [length],
            "layout": layout,
            "precision": "float32",
            "element": "float32",
        },
        content={"digest": digest_char * 64, "word_count": length, "storage": "BS0DB"},
    )


def function_contract(
    function_id: str,
    *,
    version: int = 1,
    inputs=("vector", "vector"),
    output="scalar",
    proof_status: str = "verified",
    commutative: bool = False,
    commutative_proof: str | None = None,
    priority: int = 0,
    status: str = "active",
    shape_rule: str | None = None,
):
    signature = {"inputs": list(inputs), "output": output}
    if shape_rule is not None:
        signature["shape_rule"] = shape_rule
    semantics = {}
    if commutative:
        semantics["commutative"] = True
    if commutative_proof is not None:
        semantics["commutative_proof"] = commutative_proof
    suffix = function_id.split(".", 1)[-1].replace(".", "_")
    return {
        "function_id": function_id,
        "version": version,
        "signature": signature,
        "semantics": semantics,
        "proof_status": proof_status,
        "status": status,
        "priority": priority,
        "implementations": ({
            "kernel_id": f"mth.{suffix}.f32",
            "capability_class": suffix,
            "precision": "float32",
        },),
    }


def vector_registry():
    return {
        "math.vector.dot": function_contract(
            "math.vector.dot", commutative=True,
        ),
        "math.vector.cosine": function_contract(
            "math.vector.cosine", commutative=True,
        ),
        "math.vector.add": function_contract(
            "math.vector.add",
            output={"kind": "vector", "shape": "equal"},
        ),
        "math.vector.subtract": function_contract(
            "math.vector.subtract",
            output={"kind": "vector", "shape": "equal"},
        ),
    }


class MathLinkerCandidateTests(unittest.TestCase):
    def test_scratch_is_invisible_unless_opted_in_and_quarantine_is_never_linkable(self):
        scratch = replace(vector_leaf(1), status="scratch")
        right = vector_leaf(2)
        with self.assertRaises(LinkError) as raised:
            propose(
                [scratch, right],
                registry=vector_registry(),
                snapshot_id=SNAPSHOT_ID,
            )
        self.assertIn("scratch", str(raised.exception).lower())

        opted = propose(
            [scratch, right],
            registry=vector_registry(),
            snapshot_id=SNAPSHOT_ID,
            allow_scratch=True,
        )
        self.assertGreater(opted.candidate_count, 0)

        quarantined = replace(vector_leaf(1), status="quarantined")
        with self.assertRaises(LinkError):
            propose(
                [quarantined, right],
                registry=vector_registry(),
                snapshot_id=SNAPSHOT_ID,
                allow_scratch=True,
            )

    def test_vector_vector_generates_multiple_candidates(self):
        left = vector_leaf(1)
        right = vector_leaf(2)
        result = propose(
            [left, right],
            registry=vector_registry(),
            snapshot_id=SNAPSHOT_ID,
        )

        self.assertEqual(result.schema, "nanrouter.math-candidate-set.v1")
        self.assertEqual(result.candidate_count, 4)
        self.assertEqual(
            {candidate.function_id for candidate in result.candidates},
            {
                "math.vector.dot",
                "math.vector.cosine",
                "math.vector.add",
                "math.vector.subtract",
            },
        )
        self.assertEqual([candidate.rank for candidate in result.candidates], [1, 2, 3, 4])
        for candidate in result.candidates:
            self.assertTrue(candidate.candidate_id.startswith("cnd:"))
            self.assertEqual(
                candidate.candidate_id,
                candidate_id_for(
                    result.snapshot_id,
                    candidate.inputs,
                    candidate.function_id,
                    candidate.function_version,
                ),
            )
            self.assertEqual(candidate.snapshot_id, SNAPSHOT_ID)
            self.assertEqual(candidate.outputs[0]["shape"], [] if candidate.outputs[0]["kind"] == "scalar" else [128])

        dot = next(c for c in result.candidates if c.function_id == "math.vector.dot")
        add = next(c for c in result.candidates if c.function_id == "math.vector.add")
        self.assertEqual(dot.outputs[0]["kind"], "scalar")
        self.assertEqual(add.outputs[0]["kind"], "vector")
        self.assertEqual(add.outputs[0]["shape"], [128])

        self.assertFalse(result.authorized)
        self.assertEqual(result.to_dict()["authorization"], "not_granted")
        self.assertEqual(result.to_dict()["execution"], "not_performed")

    def test_dimension_mismatch_returns_typed_null(self):
        left = vector_leaf(1, 128)
        right = vector_leaf(2, 256)
        result = propose(
            [left, right],
            registry=vector_registry(),
            snapshot_id=SNAPSHOT_ID,
        )

        self.assertEqual(result.candidate_count, 0)
        self.assertTrue(result.rejected)
        self.assertTrue(all(row["reason"] == "dimension_mismatch" for row in result.rejected))
        self.assertIsNotNone(result.null)
        self.assertEqual(result.null.kind, "null")
        self.assertIsNone(result.null.content)
        self.assertEqual(result.null.metadata["reason"], "DIMENSION_MISMATCH")
        self.assertNotEqual(result.null.kind, "scalar")
        self.assertEqual(result.to_dict()["null"]["kind"], "null")

    def test_proposed_contracts_are_proposed_but_deprecated_contracts_are_not(self):
        left = vector_leaf(1)
        right = vector_leaf(2)
        registry = {
            "math.vector.proposed": function_contract(
                "math.vector.proposed", status="proposed", proof_status="stated",
            ),
            "math.vector.deprecated": function_contract(
                "math.vector.deprecated", status="deprecated", proof_status="tested",
            ),
        }
        result = propose([left, right], registry=registry, snapshot_id=SNAPSHOT_ID)

        self.assertEqual(result.candidate_count, 1)
        self.assertEqual(result.candidates[0].function_id, "math.vector.proposed")
        self.assertEqual(result.candidates[0].preflight_hint, "candidate")
        self.assertIn(
            "inactive_function",
            {row["reason"] for row in result.rejected if row["function_id"] == "math.vector.deprecated"},
        )

    def test_zero_candidates_is_typed_null_not_zero(self):
        left = vector_leaf(1)
        right = vector_leaf(2)
        result = propose([left, right], registry={}, snapshot_id=SNAPSHOT_ID)

        self.assertEqual(result.candidate_count, 0)
        self.assertEqual(result.null.kind, "null")
        self.assertIsNone(result.null.content)
        self.assertEqual(result.null.metadata["reason"], "NO_REGISTERED_FUNCTION")
        self.assertEqual(
            result.null.metadata["failure_class"], "NO_REGISTERED_FUNCTION"
        )
        self.assertEqual(result.null.metadata["linker_id"], "math.linker.v1")
        self.assertEqual(result.null.metadata["candidate_count"], 0)
        self.assertIn("rule_snapshot_id", result.null.metadata)
        self.assertFalse(result.incomplete)
        self.assertEqual(result.candidate_ids, ())

    def test_scalar_only_registry_has_no_vector_candidate(self):
        left = vector_leaf(1)
        right = vector_leaf(2)
        registry = {
            "math.scalar.add": function_contract(
                "math.scalar.add", inputs=("scalar", "scalar"),
            )
        }
        result = propose([left, right], registry=registry, snapshot_id=SNAPSHOT_ID)

        self.assertEqual(result.candidate_count, 0)
        self.assertEqual(result.null.metadata["reason"], "KIND_MISMATCH")
        self.assertEqual(result.rejected[0]["reason"], "kind_mismatch")

    def test_snapshot_records_function_rule_and_capability_digests(self):
        left = vector_leaf(1)
        right = vector_leaf(2)
        rule_v1 = MathRule(
            rule_id="math.rule.core",
            version=1,
            level=1,
            contract={"shape": "equal"},
            proof_status="proven",
            status="active",
        )
        rule_v2 = MathRule(
            rule_id="math.rule.core",
            version=2,
            level=1,
            contract={"shape": "equal", "tightened": True},
            proof_status="proven",
            status="active",
        )
        first = propose(
            [left, right],
            registry=vector_registry(),
            snapshot_id=SNAPSHOT_ID,
            rules=[rule_v1],
            capabilities=[{"capability": "vector.dot", "status": "active"}],
        )
        second = propose(
            [left, right],
            registry=vector_registry(),
            snapshot_id=SNAPSHOT_ID,
            rules=[rule_v2],
            capabilities=[{"capability": "vector.dot", "status": "revoked"}],
        )

        self.assertEqual(len(first.snapshot.function_snapshot_digest), 64)
        self.assertEqual(len(first.snapshot.rule_snapshot_digest), 64)
        self.assertEqual(len(first.snapshot.capability_digest), 64)
        self.assertEqual(len(first.snapshot.function_digests), 4)
        self.assertTrue(all(len(row["contract_digest"]) == 64 for row in first.snapshot.function_digests))
        self.assertTrue(all(len(row["capability_digest"]) == 64 for row in first.snapshot.function_digests))
        self.assertNotEqual(first.snapshot.rule_snapshot_digest, second.snapshot.rule_snapshot_digest)
        self.assertNotEqual(first.snapshot.capability_digest, second.snapshot.capability_digest)
        self.assertNotEqual(first.snapshot.derived_snapshot_id, second.snapshot.derived_snapshot_id)
        self.assertEqual(first.snapshot.function_snapshot_digest, second.snapshot.function_snapshot_digest)
        self.assertTrue(first.snapshot.derived_snapshot_id.startswith("snp:"))

    def test_callable_registry_receives_classified_operands(self):
        left = vector_leaf(1, layout="column_major")
        right = vector_leaf(2, layout="column_major")
        seen = {}

        def registry(inputs, query):
            seen["kinds"] = [item.kind for item in inputs]
            seen["shapes"] = [item.shape for item in inputs]
            seen["layouts"] = [item.layout for item in inputs]
            seen["mode"] = query.mode
            return {"math.vector.dot": vector_registry()["math.vector.dot"]}

        result = propose([left, right], registry=registry, snapshot_id=SNAPSHOT_ID)

        self.assertEqual(seen["kinds"], ["vector", "vector"])
        self.assertEqual(seen["shapes"], [(128,), (128,)])
        self.assertEqual(seen["layouts"], ["column_major", "column_major"])
        self.assertEqual(seen["mode"], "conjoin")
        self.assertEqual(result.candidate_count, 1)

    def test_math_linker_facade_is_reusable(self):
        linker = MathLinker(
            vector_registry(), snapshot_id=SNAPSHOT_ID,
        )
        result = linker.propose([vector_leaf(1), vector_leaf(2)])
        self.assertEqual(result.candidate_count, 4)
        self.assertEqual(linker.link([vector_leaf(1), vector_leaf(2)]).candidate_count, 4)

    def test_math_function_objects_and_registry_objects_are_supported(self):
        dot = MathFunction(
            function_id="math.vector.dot",
            version=1,
            signature={
                "inputs": [
                    {"name": "a", "type": "vector", "domain": "real", "shape": [128]},
                    {"name": "b", "type": "vector", "domain": "real", "shape": [128]},
                ],
                "output": {"type": "scalar", "domain": "real"},
            },
            semantics={"commutative": True},
            proof_status="verified",
            implementations=({"kernel_id": "mth.vector.dot256.f32"},),
        )

        class RegistryView:
            functions = (dot,)

        result = propose(
            [vector_leaf(1), vector_leaf(2)],
            registry=RegistryView(),
            snapshot_id=SNAPSHOT_ID,
        )
        self.assertEqual(result.candidate_count, 1)
        self.assertEqual(result.candidates[0].function_id, "math.vector.dot")
        self.assertEqual(len(result.snapshot.function_digests[0]["contract_digest"]), 64)

    def test_conjoin_text_query_parses_pinned_leaf_references(self):
        left = vector_leaf(1)
        right = vector_leaf(2)
        query = LinkQuery.parse(f"{left.leaf_id}@v1 :: {right.leaf_id}@v1")
        self.assertEqual(query.mode, "conjoin")
        result = propose(
            query,
            registry={"math.vector.dot": vector_registry()["math.vector.dot"]},
            leaves={left.leaf_id: left, right.leaf_id: right},
            snapshot_id=SNAPSHOT_ID,
        )
        self.assertEqual(result.candidate_count, 1)
        self.assertEqual(result.inputs[0]["leaf_id"], left.leaf_id)


class MathLinkerDeterminismTests(unittest.TestCase):
    def test_duplicate_contracts_dedupe_by_content_key(self):
        left = vector_leaf(1)
        right = vector_leaf(2)
        dot = vector_registry()["math.vector.dot"]
        result = propose(
            [left, right],
            registry={"first": dot, "second": dict(dot)},
            snapshot_id=SNAPSHOT_ID,
        )

        self.assertEqual(result.candidate_count, 1)
        self.assertEqual(result.candidates[0].function_id, "math.vector.dot")
        self.assertIn("duplicate_candidate", {row["reason"] for row in result.rejected})

    def test_order_is_stable_across_registry_insertion_order(self):
        left = vector_leaf(1)
        right = vector_leaf(2)
        first_registry = vector_registry()
        reversed_registry = dict(reversed(list(first_registry.items())))
        first = propose([left, right], registry=first_registry, snapshot_id=SNAPSHOT_ID)
        second = propose([left, right], registry=reversed_registry, snapshot_id=SNAPSHOT_ID)

        self.assertEqual(first.candidate_ids, second.candidate_ids)
        self.assertEqual(
            [row["function_id"] for row in first.functions],
            [row["function_id"] for row in second.functions],
        )
        self.assertEqual(first.digest(), second.digest())
        self.assertEqual(first.candidate_set_id, second.candidate_set_id)

    def test_only_proved_commutative_functions_canonicalize_operands(self):
        left = vector_leaf(1)
        right = vector_leaf(2)
        registry = {
            "math.vector.dot": function_contract(
                "math.vector.dot", commutative=True,
            ),
            "math.vector.dot_tested": function_contract(
                "math.vector.dot_tested",
                commutative=True,
                commutative_proof="tested",
            ),
            "math.vector.subtract": function_contract(
                "math.vector.subtract",
                output={"kind": "vector", "shape": "equal"},
            ),
        }
        forward = propose([left, right], registry=registry, snapshot_id=SNAPSHOT_ID)
        reverse = propose([right, left], registry=registry, snapshot_id=SNAPSHOT_ID)

        forward_ids = {candidate.function_id: candidate.candidate_id for candidate in forward.candidates}
        reverse_ids = {candidate.function_id: candidate.candidate_id for candidate in reverse.candidates}
        self.assertEqual(forward_ids["math.vector.dot"], reverse_ids["math.vector.dot"])
        self.assertNotEqual(
            forward_ids["math.vector.dot_tested"],
            reverse_ids["math.vector.dot_tested"],
        )
        self.assertNotEqual(
            forward_ids["math.vector.subtract"],
            reverse_ids["math.vector.subtract"],
        )
        subtract = next(c for c in reverse.candidates if c.function_id == "math.vector.subtract")
        self.assertEqual(subtract.inputs[0]["leaf_id"], right.leaf_id)
        self.assertEqual(subtract.inputs[1]["leaf_id"], left.leaf_id)


class MathLinkerAddressTests(unittest.TestCase):
    def test_nan_route_is_rejected_in_linker_context(self):
        with self.assertRaises(LinkError) as caught:
            parse_ref("nan://GM0:SC0:MC0:BS0:0/point/0")
        self.assertEqual(caught.exception.code, "address_context_mismatch")
        with self.assertRaises(LinkError) as caught:
            LinkQuery.parse(
                "nan://GM0:SC0:MC0:BS0:0/point/0 :: "
                "nan://GM0:SC0:MC0:BS0:0/point/1"
            )
        self.assertEqual(caught.exception.code, "address_context_mismatch")
        with self.assertRaises(LinkError):
            propose(
                ["nan://GM0:SC0:MC0:BS0:0/point/0", vector_leaf(1)],
                registry=vector_registry(),
                snapshot_id=SNAPSHOT_ID,
            )

    def test_unbound_head_reference_and_raw_offsets_are_rejected(self):
        with self.assertRaises(LinkError) as caught:
            parse_ref("HW0:123")
        self.assertEqual(caught.exception.code, "unbound_head_reference")
        for value in ("17", "-1", "0x10", "128:2", 17):
            with self.assertRaises(LinkError) as caught:
                parse_ref(value)
            self.assertEqual(caught.exception.code, "raw_offset", msg=repr(value))

    def test_explicit_alias_can_bind_a_head_display_name(self):
        leaf = vector_leaf(1)
        reference = parse_ref(
            "HW0:123",
            aliases={"HW0:123": leaf},
        )
        self.assertEqual(reference.leaf_id, leaf.leaf_id)
        self.assertEqual(reference.version, 1)
        self.assertEqual(reference.via_alias, "HW0:123")

        result = propose(
            ["HW0:123", "nml:U0:vector:2@v1"],
            registry={"math.vector.dot": vector_registry()["math.vector.dot"]},
            leaves={"nml:U0:vector:1": leaf, "nml:U0:vector:2": vector_leaf(2)},
            aliases={"HW0:123": "nml:U0:vector:1@v1"},
            snapshot_id=SNAPSHOT_ID,
        )
        self.assertEqual(result.candidate_count, 1)

    def test_unpinned_versions_are_rejected(self):
        with self.assertRaises(LinkError) as caught:
            parse_ref("nml:U0:vector:123")
        self.assertEqual(caught.exception.code, "unpinned_version")
        with self.assertRaises(LinkError) as caught:
            parse_ref("math://GM0:SC0:MC0:BS0:0/leaf/nml:U0:vector:123")
        self.assertEqual(caught.exception.code, "unpinned_version")
        with self.assertRaises(LinkError) as caught:
            parse_ref({"leaf_id": "nml:U0:vector:123"})
        self.assertEqual(caught.exception.code, "unpinned_version")
        with self.assertRaises(LinkError) as caught:
            parse_ref({"leaf_id": "nml:U0:vector:123", "version": 0})
        self.assertEqual(caught.exception.code, "unpinned_version")
        with self.assertRaises(LinkError):
            propose(
                [{"leaf_id": "nml:U0:vector:1"}, vector_leaf(2)],
                registry=vector_registry(),
                leaves={"nml:U0:vector:1": vector_leaf(1)},
                snapshot_id=SNAPSHOT_ID,
            )

    def test_resolved_version_and_digest_must_match_the_pin(self):
        leaf = vector_leaf(1)
        other = vector_leaf(2)
        with self.assertRaises(LinkError) as caught:
            propose(
                ["nml:U0:vector:1@v2", other],
                registry=vector_registry(),
                leaves={"nml:U0:vector:1": leaf},
                snapshot_id=SNAPSHOT_ID,
            )
        self.assertEqual(caught.exception.code, "version_mismatch")

        with self.assertRaises(LinkError) as caught:
            propose(
                [{"leaf_id": "nml:U0:vector:1", "version": 1, "content_digest": "f" * 64}, other],
                registry=vector_registry(),
                leaves={"nml:U0:vector:1": leaf},
                snapshot_id=SNAPSHOT_ID,
            )
        self.assertEqual(caught.exception.code, "digest_mismatch")


class MathLinkerTransformAndBoundsTests(unittest.TestCase):
    def test_transform_mode_filters_by_goal(self):
        left = vector_leaf(1)
        right = vector_leaf(2)
        registry = vector_registry()
        scalar = propose(
            LinkQuery(
                operands=(left, right),
                mode="transform",
                goal=TransformGoal(kind="scalar"),
            ),
            registry=registry,
            snapshot_id=SNAPSHOT_ID,
        )
        vector = propose(
            LinkQuery(
                operands=(left, right),
                mode="transform",
                goal={"kind": "vector", "shape": [128]},
            ),
            registry=registry,
            snapshot_id=SNAPSHOT_ID,
        )
        self.assertEqual(
            {candidate.function_id for candidate in scalar.candidates},
            {"math.vector.dot", "math.vector.cosine"},
        )
        self.assertEqual(
            {candidate.function_id for candidate in vector.candidates},
            {"math.vector.add", "math.vector.subtract"},
        )
        self.assertTrue(all(candidate.outputs[0]["kind"] == "scalar" for candidate in scalar.candidates))
        self.assertTrue(all(candidate.outputs[0]["kind"] == "vector" for candidate in vector.candidates))

    def test_transform_goal_can_be_parsed_and_matched_with_unary_function(self):
        left = vector_leaf(1)
        right = vector_leaf(2)
        norm = function_contract("math.vector.norm", inputs=("vector",), output="scalar")
        query = parse_link_query(
            f"transform {left.leaf_id}@v1 :: {right.leaf_id}@v1",
            goal="scalar",
        )
        self.assertEqual(query.mode, "transform")
        self.assertEqual(query.goal.kind, "scalar")

        result = propose(
            LinkQuery(operands=(left,), mode="transform", goal="scalar"),
            registry={"math.vector.norm": norm},
            snapshot_id=SNAPSHOT_ID,
        )
        self.assertEqual(result.candidate_count, 1)
        self.assertEqual(result.candidates[0].function_id, "math.vector.norm")
        self.assertEqual(result.candidates[0].outputs[0]["kind"], "scalar")

    def test_transform_goal_without_match_is_typed_null(self):
        left = vector_leaf(1)
        right = vector_leaf(2)
        result = propose(
            LinkQuery(operands=(left, right), mode="transform", goal="matrix"),
            registry=vector_registry(),
            snapshot_id=SNAPSHOT_ID,
        )
        self.assertEqual(result.candidate_count, 0)
        self.assertEqual(result.null.metadata["reason"], "NO_TRANSFORM_MATCH")
        self.assertIn("goal_mismatch", {row["reason"] for row in result.rejected})

    def test_candidate_cap_truncates_deterministically(self):
        left = vector_leaf(1)
        right = vector_leaf(2)
        registry = {
            f"math.vector.candidate_{index}": function_contract(
                f"math.vector.candidate_{index}", priority=index,
            )
            for index in range(5)
        }
        first = propose(
            [left, right],
            registry=registry,
            snapshot_id=SNAPSHOT_ID,
            max_candidates=2,
        )
        second = propose(
            [left, right],
            registry=registry,
            snapshot_id=SNAPSHOT_ID,
            max_candidates=2,
        )

        self.assertEqual(first.candidate_count, 2)
        self.assertTrue(first.truncated)
        self.assertIn("candidate_limit", first.incomplete_reasons)
        self.assertEqual(first.omitted_candidate_count, 3)
        self.assertEqual([candidate.rank for candidate in first.candidates], [1, 2])
        self.assertEqual(first.candidate_ids, second.candidate_ids)
        self.assertEqual(first.digest(), second.digest())

    def test_fanout_fuel_and_depth_bounds_report_incompleteness(self):
        left = vector_leaf(1)
        right = vector_leaf(2)
        registry = {
            f"math.vector.bound_{index}": function_contract(
                f"math.vector.bound_{index}", priority=index,
            )
            for index in range(3)
        }
        fanout = propose(
            [left, right],
            registry=registry,
            snapshot_id=SNAPSHOT_ID,
            bounds=LinkBounds(max_fanout=1),
        )
        self.assertEqual(fanout.candidate_count, 1)
        self.assertTrue(fanout.truncated)
        self.assertIn("fanout_limit", fanout.incomplete_reasons)
        self.assertEqual(fanout.omitted_candidate_count, 2)

        fuel = propose(
            [left, right],
            registry=registry,
            snapshot_id=SNAPSHOT_ID,
            bounds={"fuel": 2},
        )
        self.assertEqual(fuel.candidate_count, 2)
        self.assertTrue(fuel.incomplete)
        self.assertIn("fuel_exhausted", fuel.incomplete_reasons)
        self.assertEqual(fuel.search["fuel_used"], 2)

        depth = propose(
            [left, right],
            registry=registry,
            snapshot_id=SNAPSHOT_ID,
            bounds={"max_depth": 0},
        )
        self.assertEqual(depth.candidate_count, 0)
        self.assertEqual(depth.null.metadata["reason"], "DEPTH_LIMIT")
        self.assertIn("depth_limit", depth.incomplete_reasons)


class MathLinkerIsolationTests(unittest.TestCase):
    def test_linker_does_not_import_execution_or_authorization_layers(self):
        source_path = Path(__file__).resolve().parents[1] / "runner_riddle" / "math_linker.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        forbidden = (
            "executor",
            "mth_system",
            "wave_service",
            "point0_bridge",
            "point0_http",
            "wave_http",
            "math_runtime",
            "live_preflight",
            "mth_registry",
        )
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imported.append(node.module)
                imported.extend(alias.name for alias in node.names)
        lowered = " ".join(imported).lower()
        for fragment in forbidden:
            self.assertNotIn(fragment, lowered)
        self.assertNotIn("MathAdmission", imported)

    def test_execute_request_is_rejected_without_dispatching(self):
        with self.assertRaises(LinkError) as caught:
            propose(
                [vector_leaf(1), vector_leaf(2)],
                registry=vector_registry(),
                snapshot_id=SNAPSHOT_ID,
                execute=True,
            )
        self.assertEqual(caught.exception.code, "execution_not_permitted")

    def test_classification_is_static_and_exposes_type_shape_layout(self):
        leaf = vector_leaf(1, layout="column_major")
        classified = classify_leaf(leaf)
        self.assertEqual(classified.kind, "vector")
        self.assertEqual(classified.domain, "real")
        self.assertEqual(classified.shape, (128,))
        self.assertEqual(classified.layout, "column_major")
        self.assertEqual(classified.precision, "float32")
        self.assertEqual(classified.content_digest, leaf.content_digest)
        self.assertEqual(len(classified.leaf_digest), 64)


if __name__ == "__main__":
    unittest.main()
