from __future__ import annotations

import unittest

from runner_riddle.math_objects import (
    FUNCTION_SCHEMA,
    LEAF_SCHEMA,
    RULE_SCHEMA,
    MathAdmission,
    MathCandidate,
    MathFunction,
    MathLeaf,
    MathObjectError,
    MathRule,
    admission_id_for,
    candidate_id_for,
    canonical_json,
    digest_object,
)


def vector_leaf(leaf_id="nml:U0:vector:123", version=1, digest="a" * 64):
    return MathLeaf(
        leaf_id=leaf_id,
        version=version,
        kind="vector",
        type={"element": "float32", "shape": [256], "layout": "row_major"},
        content={"digest": digest, "word_count": 256, "storage": "BS0DB"},
    )


class MathObjectTests(unittest.TestCase):
    def test_canonical_json_is_order_independent(self):
        self.assertEqual(canonical_json({"b": 2, "a": 1}), canonical_json({"a": 1, "b": 2}))
        self.assertEqual(digest_object({"b": 2, "a": 1}), digest_object({"a": 1, "b": 2}))

    def test_same_content_can_have_distinct_leaf_identity(self):
        a = vector_leaf("nml:U0:vector:123")
        b = vector_leaf("nml:U0:vector:456")
        self.assertEqual(a.content_digest, b.content_digest)
        self.assertNotEqual(a.leaf_id, b.leaf_id)
        self.assertNotEqual(a.digest(), b.digest())

    def test_version_is_append_only_and_old_version_remains(self):
        a = vector_leaf()
        b = a.next_version(content={"digest": "b" * 64, "word_count": 256})
        self.assertEqual(a.version, 1)
        self.assertEqual(b.version, 2)
        self.assertEqual(a.content_digest, "a" * 64)
        self.assertEqual(b.content_digest, "b" * 64)

    def test_null_and_zero_are_distinct_records(self):
        zero = MathLeaf(
            leaf_id="nml:U0:scalar:zero",
            kind="scalar",
            type={"element": "float32", "shape": []},
            content={"digest": "c" * 64, "value": "0"},
        )
        null = MathLeaf(
            leaf_id="nml:U0:null:1",
            kind="null",
            type={"element": "opaque", "shape": []},
            content=None,
            metadata={"reason": "NO_VALID_TRANSFORM"},
        )
        self.assertIsNotNone(zero.content)
        self.assertIsNone(null.content)
        self.assertNotEqual(zero.to_dict()["kind"], null.to_dict()["kind"])

    def test_null_requires_reason(self):
        with self.assertRaises(Exception):
            MathLeaf(
                leaf_id="nml:U0:null:2", kind="null",
                type={"element": "opaque", "shape": []}, content=None,
            )

    def test_candidate_identity_excludes_rank(self):
        inputs = ({"leaf_id": "nml:U0:vector:123", "version": 1},)
        cid = candidate_id_for("snp:" + "d" * 64, inputs, "math.vector.dot", 1)
        a = MathCandidate(cid, inputs, "math.vector.dot", 1, rank=1)
        b = MathCandidate(cid, inputs, "math.vector.dot", 1, rank=9)
        self.assertEqual(a.candidate_id, b.candidate_id)
        self.assertNotEqual(a.rank, b.rank)
        self.assertNotEqual(cid, candidate_id_for("snp:" + "e" * 64, inputs, "math.vector.dot", 1))

    def test_admission_is_typed_and_not_a_zero(self):
        cid = "cnd:" + "f" * 64
        admission = MathAdmission(
            admission_id=admission_id_for(cid, "snp:" + "d" * 64, "UNDEFINED"),
            candidate_id=cid,
            verdict="UNDEFINED",
            snapshot_id="snp:" + "d" * 64,
            reason="DIV_ZERO",
        )
        self.assertEqual(admission.verdict, "UNDEFINED")
        self.assertNotEqual(admission.verdict, "VALID")

    def test_function_contract_digest_is_stable_and_versioned(self):
        function = MathFunction(
            function_id="math.vector.dot",
            version=1,
            signature={"inputs": 2, "output": "scalar"},
            semantics={"definition": "sum a[i]*b[i]"},
            implementations=({"kernel_id": "mth.vector.dot256.f32"},),
            proof_status="verified",
        )
        self.assertEqual(function.digest(), function.digest())
        self.assertEqual(len(function.digest()), 64)
        with self.assertRaises(Exception):
            MathFunction(function_id="mth.vector.dot256.f32", signature={"x": 1})


class DeepImmutabilityTests(unittest.TestCase):
    def test_leaf_nested_dicts_and_lists_reject_mutation(self):
        leaf = MathLeaf(
            leaf_id="nml:U0:vector:frozen",
            kind="vector",
            type={"nested": {"shape": [256]}},
            content={"digest": "a" * 64, "vector": [1, 2], "nested": {"x": 1}},
            parents=({"leaf_id": "nml:U0:vector:parent", "role": "left"},),
            provenance={"job": {"id": "job-1"}},
            aliases=({"name": "old"},),
            metadata={"detail": {"flag": True}},
        )
        self.assertIsInstance(leaf.type, dict)
        self.assertEqual(canonical_json(leaf.type), '{"nested":{"shape":[256]}}')
        mutations = (
            lambda: leaf.type.__setitem__("nested", {}),
            lambda: leaf.type["nested"]["shape"].append(512),
            lambda: leaf.content.__setitem__("vector", []),
            lambda: leaf.content["nested"].__setitem__("x", 2),
            lambda: leaf.parents[0].__setitem__("role", "right"),
            lambda: leaf.provenance["job"].__setitem__("id", "job-2"),
            lambda: leaf.aliases[0].__setitem__("name", "new"),
            lambda: leaf.metadata["detail"].__setitem__("flag", False),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                with self.assertRaises(TypeError):
                    mutate()
        self.assertEqual(leaf.type["nested"]["shape"], [256])
        self.assertEqual(leaf.content["nested"]["x"], 1)

    def test_function_and_rule_nested_fields_reject_mutation(self):
        function = MathFunction(
            function_id="math.vector.dot",
            signature={"inputs": [{"types": ["vector"]}]},
            semantics={"nested": {"definition": "dot"}},
            preconditions=({"check": {"values": [1]}},),
            numerical_policy={"nested": {"precision": "float32"}},
            implementations=({"kernel": {"id": "mth.vector.dot256.f32"}},),
            proof_status="stated",
        )
        rule = MathRule(
            rule_id="math.rule.frozen",
            contract={"claim": "assoc", "nested": {"values": [1, 2]}},
            scope={"family": "vector", "nested": {"flag": True}},
        )
        mutations = (
            lambda: function.signature["inputs"].append({}),
            lambda: function.signature["inputs"][0]["types"].append("scalar"),
            lambda: function.semantics["nested"].__setitem__("definition", "x"),
            lambda: function.preconditions[0]["check"]["values"].append(2),
            lambda: function.numerical_policy["nested"].__setitem__("precision", "x"),
            lambda: function.implementations[0]["kernel"].__setitem__("id", "x"),
            lambda: rule.contract["nested"]["values"].append(3),
            lambda: rule.contract.__setitem__("claim", "commutative"),
            lambda: rule.scope["nested"].__setitem__("flag", False),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                with self.assertRaises(TypeError):
                    mutate()

    def test_to_dict_returns_an_independent_mutable_copy(self):
        leaf = MathLeaf(
            leaf_id="nml:U0:vector:copy",
            kind="vector",
            type={"nested": {"shape": [256]}},
            content={"digest": "a" * 64, "nested": {"x": 1}},
            provenance={"job": {"id": "job-1"}},
        )
        document = leaf.to_dict()
        document["type"]["nested"]["shape"].append(512)
        document["content"]["nested"]["x"] = 99
        document["provenance"]["job"]["id"] = "job-2"
        self.assertEqual(leaf.type["nested"]["shape"], [256])
        self.assertEqual(leaf.content["nested"]["x"], 1)
        self.assertEqual(leaf.provenance["job"]["id"], "job-1")

    def test_legacy_canonical_digests_are_preserved(self):
        leaf_document = {
            "leaf_id": "nml:U0:vector:legacy",
            "version": 1,
            "kind": "vector",
            "type": {"element": "float32", "shape": [256],
                     "nested": {"layout": ["row"]}},
            "content": {"digest": "a" * 64, "word_count": 256},
            "parents": [{"leaf_id": "nml:U0:vector:parent", "version": 1,
                         "role": "left"}],
            "operation": None,
            "status": "committed",
            "provenance": {"producer": "legacy"},
            "aliases": [{"name": "old"}],
            "metadata": {"detail": [1, {"flag": True}]},
        }
        leaf = MathLeaf(**leaf_document)
        self.assertEqual(
            leaf.digest(),
            digest_object({"schema": LEAF_SCHEMA, **leaf_document}),
        )

        function_document = {
            "function_id": "math.vector.dot",
            "version": 1,
            "signature": {"inputs": [{"type": "vector"}],
                          "output": {"type": "scalar"}},
            "semantics": {"definition": "dot"},
            "preconditions": [{"check": "shape"}],
            "postconditions": [],
            "undefined_conditions": [],
            "numerical_policy": {"precision": "float32"},
            "implementations": [{"kernel_id": "mth.vector.dot256.f32"}],
            "proof_status": "stated",
            "status": "active",
            "contract_digest": None,
        }
        function = MathFunction(**function_document)
        expected_function = {"schema": FUNCTION_SCHEMA, **function_document}
        expected_function.pop("contract_digest")
        self.assertEqual(function.digest(), digest_object(expected_function))

        rule_document = {
            "rule_id": "math.rule.legacy",
            "version": 1,
            "level": 1,
            "contract": {"claim": "assoc", "nested": {"values": [1]}},
            "proof_status": "stated",
            "status": "proposed",
            "scope": {"family": "vector"},
            "certificate_digest": None,
        }
        rule = MathRule(**rule_document)
        self.assertEqual(
            digest_object(rule.to_dict()),
            digest_object({"schema": RULE_SCHEMA, **rule_document}),
        )

    def test_metadata_version_is_optional_and_append_only(self):
        leaf = vector_leaf()
        self.assertIsNone(leaf.metadata_version)
        self.assertNotIn("metadata_version", leaf.to_dict())

        versioned = MathLeaf(
            leaf_id=leaf.leaf_id,
            kind=leaf.kind,
            type=leaf.type,
            content=leaf.content,
            metadata_version=1,
        )
        self.assertEqual(versioned.to_dict()["metadata_version"], 1)
        self.assertEqual(
            versioned.next_version(content={"digest": "b" * 64}).metadata_version,
            1,
        )
        self.assertNotEqual(versioned.digest(), leaf.digest())
        for invalid in (0, -1, True, "1"):
            with self.subTest(metadata_version=invalid):
                with self.assertRaises(MathObjectError):
                    MathLeaf(
                        leaf_id=leaf.leaf_id, kind=leaf.kind,
                        type=leaf.type, metadata_version=invalid,
                    )

    def test_result_leaf_requires_operation_and_provenance_identity(self):
        result = MathLeaf(
            leaf_id="nml:U0:result:1",
            kind="result",
            type={"element": "float32", "shape": []},
            content={"digest": "f" * 64, "word_count": 1},
            parents=({"leaf_id": "nml:U0:vector:1", "version": 1,
                      "role": "left"},),
            operation={"function_id": "math.vector.dot",
                       "function_version": 1},
            provenance={"producer": "MC0:0/R0", "job_id": "job-1"},
        )
        self.assertEqual(result.kind, "result")
        invalid = (
            {"operation": None, "provenance": {"producer": "p"}},
            {"operation": {}, "provenance": {"producer": "p"}},
            {"operation": {"function_id": "math.vector.dot"}, "provenance": {}},
            {"operation": {"function_id": "math.vector.dot"},
             "provenance": {"note": "no identity"}},
        )
        for fields in invalid:
            with self.subTest(fields=fields):
                with self.assertRaises(MathObjectError):
                    MathLeaf(
                        leaf_id="nml:U0:result:2",
                        kind="result",
                        type={"element": "float32", "shape": []},
                        content={"digest": "f" * 64, "word_count": 1},
                        **fields,
                    )


if __name__ == "__main__":
    unittest.main()
