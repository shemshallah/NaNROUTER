from __future__ import annotations

import unittest

from runner_riddle.math_objects import (
    MathAdmission,
    MathCandidate,
    MathFunction,
    MathLeaf,
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


if __name__ == "__main__":
    unittest.main()
