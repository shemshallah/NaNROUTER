from __future__ import annotations

import json
from pathlib import Path
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
    MathTypeDescriptor,
    admission_id_for,
    candidate_id_for,
    canonical_json,
    digest_object,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
LEAF_SCHEMA_PATH = REPO_ROOT / "spec" / "math-leaf.schema.json"
FUNCTION_SCHEMA_PATH = REPO_ROOT / "spec" / "math-function.schema.json"


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


class ContractDigestIdentityTests(unittest.TestCase):
    SNAPSHOT = "snp:" + "d" * 64
    INPUTS = ({"leaf_id": "nml:U0:vector:123", "version": 1},)

    def test_legacy_candidate_identity_and_serialization_are_unchanged(self):
        expected_payload = {
            "snapshot_id": self.SNAPSHOT,
            "inputs": [dict(item) for item in self.INPUTS],
            "function_id": "math.vector.dot",
            "function_version": 1,
        }
        legacy_id = "cnd:" + digest_object(expected_payload)
        self.assertEqual(
            candidate_id_for(
                self.SNAPSHOT, self.INPUTS, "math.vector.dot", 1,
            ),
            legacy_id,
        )
        candidate = MathCandidate(
            legacy_id,
            self.INPUTS,
            "math.vector.dot",
            1,
            snapshot_id=self.SNAPSHOT,
        )
        self.assertIsNone(candidate.contract_digest)
        self.assertNotIn("contract_digest", candidate.to_dict())
        self.assertEqual(candidate.candidate_id, legacy_id)

    def test_contract_digest_binds_candidate_identity_and_roundtrips(self):
        contract_digest = "a" * 64
        legacy_id = candidate_id_for(
            self.SNAPSHOT, self.INPUTS, "math.vector.dot", 1,
        )
        bound_id = candidate_id_for(
            self.SNAPSHOT, self.INPUTS, "math.vector.dot", 1,
            contract_digest=contract_digest,
        )
        self.assertNotEqual(legacy_id, bound_id)
        self.assertEqual(
            bound_id,
            candidate_id_for(
                self.SNAPSHOT, self.INPUTS, "math.vector.dot", 1,
                contract_digest=contract_digest,
            ),
        )
        self.assertNotEqual(
            bound_id,
            candidate_id_for(
                self.SNAPSHOT, self.INPUTS, "math.vector.dot", 1,
                contract_digest="b" * 64,
            ),
        )

        candidate = MathCandidate(
            bound_id,
            self.INPUTS,
            "math.vector.dot",
            1,
            snapshot_id=self.SNAPSHOT,
            contract_digest=contract_digest,
        )
        document = candidate.to_dict()
        self.assertEqual(document["contract_digest"], contract_digest)
        rebuilt = MathCandidate(**{
            key: value for key, value in document.items() if key != "schema"
        })
        self.assertEqual(rebuilt, candidate)
        self.assertEqual(rebuilt.to_dict(), document)
        self.assertEqual(rebuilt.contract_digest, contract_digest)

    def test_malformed_contract_digest_is_rejected(self):
        invalid = ("", "A" * 64, "a" * 63, "a" * 65, 1, True)
        for contract_digest in invalid:
            with self.subTest(contract_digest=contract_digest):
                with self.assertRaises(MathObjectError):
                    MathCandidate(
                        "cnd:" + "e" * 64,
                        self.INPUTS,
                        "math.vector.dot",
                        1,
                        contract_digest=contract_digest,
                    )
                with self.assertRaises(MathObjectError):
                    candidate_id_for(
                        self.SNAPSHOT, self.INPUTS, "math.vector.dot", 1,
                        contract_digest=contract_digest,
                    )


class SemanticTypeDescriptorTests(unittest.TestCase):
    def test_absent_descriptor_keeps_legacy_serialization_and_digest(self):
        leaf = MathLeaf(
            leaf_id="nml:U0:vector:legacy-free",
            kind="vector",
            type={"name": "legacy-vector"},
            content={"digest": "a" * 64, "word_count": 256},
        )
        document = leaf.to_dict()
        self.assertNotIn("element_type", document["type"])
        self.assertNotIn("stride", document["type"])
        self.assertNotIn("units", document["type"])
        self.assertEqual(leaf.type_descriptor.declared(), frozenset())
        self.assertEqual(leaf.digest(), digest_object(document))

        function_document = {
            "function_id": "math.vector.dot",
            "version": 1,
            "signature": {
                "inputs": [{"name": "a", "type": "vector"},
                           {"name": "b", "type": "vector"}],
                "output": {"type": "scalar"},
            },
            "semantics": {"definition": "dot"},
            "proof_status": "stated",
            "status": "active",
        }
        function = MathFunction(**function_document)
        self.assertEqual(
            function.to_dict()["signature"],
            function_document["signature"],
        )
        self.assertEqual(
            MathTypeDescriptor.from_mapping({}).to_dict(),
            {},
        )

    def test_leaf_descriptor_declared_roundtrip(self):
        type_document = {
            "kind": "vector",
            "element_type": "float32",
            "stride": [1],
            "layout": "row_major",
            "units": "m/s",
            "rank": 1,
            "shape": [256],
            "domain": "real",
            "context": {"frame": "world", "axes": ["x"]},
        }
        leaf = MathLeaf(
            leaf_id="nml:U0:vector:semantic",
            kind="vector",
            type=type_document,
            content={"digest": "a" * 64, "word_count": 256},
        )
        self.assertEqual(leaf.to_dict()["type"], type_document)
        descriptor = leaf.type_descriptor
        self.assertEqual(descriptor.element_type, "float32")
        self.assertEqual(descriptor.stride, (1,))
        self.assertEqual(descriptor.layout, "row_major")
        self.assertEqual(descriptor.units, "m/s")
        self.assertEqual(descriptor.rank, 1)
        self.assertEqual(descriptor.shape, (256,))
        self.assertEqual(descriptor.domain, "real")
        self.assertEqual(descriptor.context["frame"], "world")
        self.assertEqual(
            descriptor.declared(),
            frozenset({
                "element_type", "stride", "layout", "units", "rank",
                "shape", "domain", "context",
            }),
        )
        self.assertEqual(
            descriptor.to_dict()["stride"], [1],
        )
        self.assertEqual(descriptor.digest(), digest_object(descriptor.to_dict()))
        self.assertEqual(leaf.digest(), leaf.digest())
        self.assertNotEqual(leaf.digest(), vector_leaf().digest())
        versioned = leaf.next_version(content={"digest": "b" * 64})
        self.assertEqual(versioned.to_dict()["type"], type_document)

    def test_leaf_descriptor_aliases_and_conflicts(self):
        descriptor = MathTypeDescriptor.from_mapping({
            "element": "float32",
            "dtype": "float32",
            "stride": [1],
            "strides": [1],
            "unit": "m",
            "units": "m",
        })
        self.assertEqual(descriptor.element_type, "float32")
        self.assertEqual(descriptor.stride, (1,))
        self.assertEqual(descriptor.units, "m")
        self.assertEqual(
            descriptor.to_dict(),
            {
                "element_type": "float32",
                "stride": [1],
                "units": "m",
            },
        )
        conflicts = (
            {"element": "float32", "dtype": "float64"},
            {"unit": "m", "units": "s"},
            {"stride": [1], "strides": [2]},
        )
        for document in conflicts:
            with self.subTest(document=document):
                with self.assertRaises(MathObjectError):
                    MathTypeDescriptor.from_mapping(document)

    def test_invalid_units_rejected(self):
        valid = ("1", "m", "m/s", "m/s^2", "kg*m/s^2", "any", "*")
        for units in valid:
            with self.subTest(units=units):
                self.assertEqual(
                    MathTypeDescriptor.from_mapping({"units": units}).units,
                    units,
                )
        invalid = ("m//s", "metres per second", "m/", "", "kg m", 3, ["m"])
        for units in invalid:
            with self.subTest(units=units):
                with self.assertRaises(MathObjectError):
                    MathLeaf(
                        leaf_id="nml:U0:vector:units",
                        kind="vector",
                        type={"units": units},
                    )
                with self.assertRaises(MathObjectError):
                    MathFunction(
                        function_id="math.vector.dot",
                        signature={
                            "inputs": [{"type": "vector", "units": units}],
                            "output": {"type": "scalar"},
                        },
                    )

    def test_invalid_stride_rank_and_shape_rank_mismatch_rejected(self):
        invalid_strides = (-1, True, [1, -2], [1.5], "1", [True])
        for stride in invalid_strides:
            with self.subTest(stride=stride):
                with self.assertRaises(MathObjectError):
                    MathLeaf(
                        leaf_id="nml:U0:vector:stride",
                        kind="vector",
                        type={"stride": stride},
                    )
        for rank in (-1, True, "1"):
            with self.subTest(rank=rank):
                with self.assertRaises(MathObjectError):
                    MathLeaf(
                        leaf_id="nml:U0:vector:rank",
                        kind="vector",
                        type={"rank": rank},
                    )
        with self.assertRaises(MathObjectError):
            MathLeaf(
                leaf_id="nml:U0:vector:rank-shape",
                kind="vector",
                type={"rank": 2, "shape": [256]},
            )

    def test_function_endpoint_descriptor_roundtrip_and_validation(self):
        input_endpoint = {
            "name": "a",
            "type": "vector",
            "domain": "real",
            "shape": [256],
            "precision": "float32",
            "element_type": "float32",
            "stride": [1],
            "layout": "row_major",
            "units": "m",
            "rank": 1,
            "context": {"frame": "world"},
        }
        output_endpoint = {
            "type": "scalar",
            "domain": "real",
            "shape": [],
            "precision": "float32",
            "element_type": "float32",
            "stride": 0,
            "layout": "row_major",
            "units": "1",
            "rank": 0,
            "context": {"frame": "world"},
        }
        function = MathFunction(
            function_id="math.vector.dot",
            version=1,
            signature={
                "inputs": [input_endpoint, dict(input_endpoint, name="b")],
                "output": output_endpoint,
            },
            proof_status="stated",
        )
        document = function.to_dict()
        self.assertEqual(document["signature"]["inputs"][0], input_endpoint)
        self.assertEqual(document["signature"]["output"], output_endpoint)
        for field, value in (
            ("units", "m//s"), ("stride", -1), ("layout", "Row Major"),
        ):
            with self.subTest(field=field):
                with self.assertRaises(MathObjectError):
                    MathFunction(
                        function_id="math.vector.dot",
                        signature={
                            "inputs": [{"type": "vector", field: value}],
                            "output": {"type": "scalar"},
                        },
                    )

    def test_descriptor_compatibility_helper(self):
        producer = MathTypeDescriptor.from_mapping({
            "element_type": "float32",
            "stride": 1,
            "layout": "row_major",
            "units": "m/s",
            "rank": 1,
        })
        compatible = MathTypeDescriptor.from_mapping({
            "dtype": "Float32",
            "strides": [1],
            "layout": "row_major",
            "units": "m/s",
            "rank": 1,
        })
        self.assertEqual(producer.compatibility_issues(compatible), ())
        wildcard = MathTypeDescriptor.from_mapping({
            "element_type": "any",
            "layout": "*",
            "units": "any",
        })
        self.assertEqual(producer.compatibility_issues(wildcard), ())
        self.assertEqual(
            MathTypeDescriptor.from_mapping({}).compatibility_issues(compatible),
            (),
        )
        self.assertEqual(
            producer.compatibility_issues(MathTypeDescriptor.from_mapping({})),
            (),
        )
        mismatches = (
            ({"element_type": "float64"}, "element_type"),
            ({"stride": [2]}, "stride"),
            ({"layout": "column_major"}, "layout"),
            ({"units": "s"}, "units"),
            ({"rank": 2}, "rank"),
        )
        for fields, expected in mismatches:
            with self.subTest(field=expected):
                required = MathTypeDescriptor.from_mapping(fields)
                issues = producer.compatibility_issues(required)
                self.assertEqual(len(issues), 1)
                self.assertIn(expected, issues[0])

    def test_schemas_cover_semantic_descriptor_fields(self):
        leaf_schema = json.loads(LEAF_SCHEMA_PATH.read_text(encoding="utf-8"))
        function_schema = json.loads(
            FUNCTION_SCHEMA_PATH.read_text(encoding="utf-8")
        )
        descriptor_fields = {
            "element_type", "element", "dtype", "stride", "strides",
            "layout", "units", "unit", "rank", "shape", "domain", "context",
        }
        self.assertTrue(
            descriptor_fields.issubset(
                set(leaf_schema["properties"]["type"]["properties"])
            )
        )
        endpoint = function_schema["$defs"]["endpoint"]["properties"]
        self.assertTrue(descriptor_fields.issubset(set(endpoint)))
        signature = function_schema["properties"]["signature"]["properties"]
        self.assertEqual(
            signature["inputs"]["items"]["$ref"], "#/$defs/endpoint",
        )
        self.assertEqual(
            signature["output"]["$ref"], "#/$defs/endpoint",
        )
        for schema in (leaf_schema, function_schema):
            self.assertEqual(
                schema["$schema"],
                "https://json-schema.org/draft/2020-12/schema",
            )
            for definition in (
                "elementType", "stride", "layout", "units", "rank", "shape",
                "domain", "context",
            ):
                self.assertIn(definition, schema["$defs"])


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
