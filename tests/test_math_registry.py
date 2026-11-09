from __future__ import annotations

import ast
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from runner_riddle import math_registry as math_registry_module
from runner_riddle.math_registry import (
    CATALOG_SCHEMA,
    COMPATIBILITY_SCHEMA,
    HEALTH_SCHEMA,
    MathCatalogError,
    MathCompositionError,
    MathFunctionError,
    MathFunctionRegistry,
    MathImplementationError,
    MathRegistryError,
    implementation_digest,
)
from runner_riddle.mth_registry import MthRegistry

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "spec" / "wave-capabilities.json"
CATALOG = REPO_ROOT / "spec" / "math-functions.v1.json"
MATH_REGISTRY_SOURCE = Path(math_registry_module.__file__)


def _catalog_document() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def _function(document: dict, function_id: str) -> dict:
    for function in document["functions"]:
        if function["function_id"] == function_id:
            return function
    raise AssertionError(f"missing catalog function {function_id}")


def _only_function(document: dict, function_id: str) -> dict:
    document["functions"] = [_function(document, function_id)]
    return document


class MathFunctionRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mth = MthRegistry.load(MANIFEST)
        cls.registry = MathFunctionRegistry.load(
            CATALOG, implementations=cls.mth
        )

    def _load_document(self, document: dict, implementations=None):
        if implementations is None:
            implementations = self.mth
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "math-functions.v1.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            return MathFunctionRegistry.load(path, implementations=implementations)

    def _assert_document_rejected(self, document: dict,
                                  exception: type[BaseException] = MathRegistryError,
                                  implementations=None) -> str:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "math-functions.v1.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaises(exception) as caught:
                MathFunctionRegistry.load(path, implementations=implementations or self.mth)
        return str(caught.exception)

    def test_catalog_loads_and_serializes(self):
        self.assertEqual(self.registry.version, 1)
        self.assertEqual(len(self.registry), 19)
        self.assertEqual(len(self.registry.functions), 19)
        self.assertEqual(
            self.registry.to_dict()["schema"], CATALOG_SCHEMA,
        )
        expected = {
            "math.scalar.add", "math.scalar.sub", "math.scalar.mul",
            "math.scalar.div", "math.vector.add", "math.vector.sub",
            "math.vector.dot", "math.vector.norm", "math.vector.cosine",
            "math.vector.distance", "math.vector.axpy", "math.vector.matvec",
            "math.vector.topk", "math.vector.projection",
            "math.matrix.multiply", "math.matrix.pair_space",
            "math.relation.hyperedge", "math.relation.hyperedge_equal",
            "math.relation.hyperedge_hash",
        }
        self.assertEqual(set(self.registry._by_id), expected)
        for function_id in expected:
            function = self.registry.require(function_id)
            self.assertEqual(function.function_id, function_id)
            self.assertEqual(function.version, 1)
            self.assertRegex(function.contract_digest, r"^[0-9a-f]{64}$")
            self.assertEqual(function.contract_digest, function.digest())
            self.assertTrue(function.signature["inputs"])
            self.assertIn("output", function.signature)
            self.assertTrue(function.numerical_policy)
            self.assertIsInstance(function.preconditions, tuple)
            self.assertIsInstance(function.postconditions, tuple)
            self.assertIsInstance(function.undefined_conditions, tuple)

        clone = MathFunctionRegistry.from_dict(
            self.registry.to_dict(), self.mth,
        )
        self.assertEqual(
            [item.function_id for item in clone.functions],
            [item.function_id for item in self.registry.functions],
        )
        self.assertEqual(
            [item.contract_digest for item in clone.functions],
            [item.contract_digest for item in self.registry.functions],
        )

    def test_default_load_uses_sibling_manifest(self):
        loaded = MathFunctionRegistry.load(CATALOG)
        self.assertEqual(len(loaded.implementation_registry), 131)
        self.assertEqual(
            loaded.require("math.vector.dot").contract_digest,
            self.registry.require("math.vector.dot").contract_digest,
        )

    def test_manifest_remains_frozen_and_unchanged(self):
        before = MANIFEST.read_bytes()
        MathFunctionRegistry.load(CATALOG)
        after = MANIFEST.read_bytes()
        self.assertEqual(before, after)
        self.assertEqual(len(self.mth), 131)
        self.assertEqual(
            self.registry.health()["mth_kernels"], 131,
        )

    def test_unknown_function_lookup_and_require(self):
        self.assertIsNone(self.registry.lookup("math.vector.not_a_function"))
        self.assertIsNone(self.registry.lookup("math.vector.dot", version=99))
        self.assertIsNone(self.registry.lookup(123))
        self.assertNotIn("math.vector.not_a_function", self.registry)
        with self.assertRaises(MathFunctionError):
            self.registry.require("math.vector.not_a_function")
        with self.assertRaises(MathFunctionError):
            self.registry.require("math.vector.dot", version=99)
        with self.assertRaises(MathFunctionError):
            self.registry.require("")

    def test_every_implementation_matches_mth_facts(self):
        implementation_count = 0
        for function in self.registry.functions:
            for implementation in function.implementations:
                implementation_count += 1
                descriptor = self.mth.require(implementation["kernel_id"])
                self.assertEqual(descriptor.status, "native_verified")
                self.assertTrue(descriptor.ci_verified)
                self.assertEqual(implementation["version"], descriptor.version)
                self.assertEqual(
                    implementation["source_digest"], descriptor.source_digest,
                )
                self.assertEqual(
                    implementation["fixture_digest"], descriptor.fixture_digest,
                )
                self.assertEqual(
                    implementation["precision"], descriptor.precision,
                )
                self.assertEqual(
                    tuple(implementation["shape"]), descriptor.shape,
                )
                self.assertEqual(
                    implementation["workspace_words"],
                    descriptor.workspace_words,
                )
                self.assertRegex(
                    implementation_digest(descriptor), r"^[0-9a-f]{64}$",
                )
        self.assertEqual(implementation_count, 8)

    def test_missing_implementation_rejected(self):
        document = _catalog_document()
        dot = _function(document, "math.vector.dot")
        dot["implementations"][0]["kernel_id"] = "mth.vector.dot512.f32"
        message = self._assert_document_rejected(
            document, MathImplementationError,
        )
        self.assertIn("missing implementation kernel", message)

    def test_revoked_and_unverified_implementations_rejected(self):
        descriptor = self.mth.require("mth.vector.dot256.f32")
        cases = (
            (replace(descriptor, status="revoked"), "revoked"),
            (replace(descriptor, ci_verified=False), "CI-verified"),
            (replace(descriptor, status="degraded"), "native_verified"),
        )
        for mutated, expected in cases:
            with self.subTest(expected=expected):
                implementation_registry = MthRegistry([mutated])
                document = _only_function(
                    _catalog_document(), "math.vector.dot",
                )
                message = self._assert_document_rejected(
                    document,
                    MathImplementationError,
                    implementations=implementation_registry,
                )
                self.assertIn(expected, message)

    def test_wrong_precision_shape_workspace_and_digest_rejected(self):
        mutations = (
            ("precision", "q16.16", "precision"),
            ("shape", [128], "shape"),
            ("workspace_words", 4, "workspace_words"),
            ("source_digest", "0" * 64, "source_digest"),
            ("fixture_digest", "1" * 64, "fixture_digest"),
            ("version", 2, "version"),
            ("implementation_digest", "2" * 64, "implementation_digest"),
        )
        for field, value, expected in mutations:
            with self.subTest(field=field):
                document = _catalog_document()
                implementation = _function(
                    document, "math.vector.dot",
                )["implementations"][0]
                implementation[field] = value
                message = self._assert_document_rejected(
                    document, MathImplementationError,
                )
                self.assertIn(expected, message)

    def test_signature_shape_mismatch_rejected(self):
        document = _catalog_document()
        dot = _function(document, "math.vector.dot")
        dot["signature"]["inputs"][0]["shape"] = [128]
        dot["signature"]["inputs"][1]["shape"] = [128]
        message = self._assert_document_rejected(
            document, MathImplementationError,
        )
        self.assertIn("signature", message)

    def test_contract_digest_mismatch_rejected(self):
        document = _catalog_document()
        _function(document, "math.vector.dot")["contract_digest"] = "0" * 64
        message = self._assert_document_rejected(document, MathCatalogError)
        self.assertIn("contract_digest", message)

    def test_proof_status_validation(self):
        cases = (
            ({"proof_status": "trusted"}, MathCatalogError),
            ({"proof_status": "none"}, MathFunctionError),
            ({"proof_status": "rejected"}, MathFunctionError),
            ({"proof_status": "verified", "implementations": []},
             MathFunctionError),
        )
        for mutation, exception in cases:
            with self.subTest(mutation=mutation):
                document = _catalog_document()
                dot = _function(document, "math.vector.dot")
                dot.update(mutation)
                self._assert_document_rejected(document, exception)

    def test_resolve_filters_and_health(self):
        active = self.registry.resolve(
            status="active", require_implementations=True,
        )
        self.assertEqual(
            {item.function_id for item in active},
            {
                "math.vector.dot", "math.vector.norm", "math.vector.cosine",
                "math.vector.axpy", "math.vector.matvec",
                "math.vector.topk", "math.matrix.pair_space",
            },
        )
        vector_functions = self.registry.resolve(family="vector")
        self.assertEqual(len(vector_functions), 10)
        self.assertTrue(
            all(item.function_id.startswith("math.vector.")
                for item in vector_functions)
        )
        tagged = self.registry.resolve(tags="family:vector")
        self.assertEqual(tagged, vector_functions)
        small = self.registry.resolve(
            require_implementations=True, max_workspace=0,
        )
        self.assertNotIn(
            "math.matrix.pair_space",
            {item.function_id for item in small},
        )
        self.assertNotIn(
            "math.vector.cosine",
            {item.function_id for item in small},
        )
        pair_workspace = self.registry.resolve(
            require_implementations=True, max_workspace=2000,
        )
        self.assertIn(
            "math.matrix.pair_space",
            {item.function_id for item in pair_workspace},
        )
        with self.assertRaises(MathFunctionError):
            self.registry.resolve(status="bogus")
        with self.assertRaises(MathFunctionError):
            self.registry.resolve(proof_status="bogus")
        with self.assertRaises(MathFunctionError):
            self.registry.resolve(tags=object())

        health = self.registry.health()
        self.assertEqual(health["schema"], HEALTH_SCHEMA)
        self.assertTrue(health["healthy"])
        self.assertEqual(health["functions"], 19)
        self.assertEqual(health["implemented_functions"], 7)
        self.assertEqual(health["unimplemented_functions"], 12)
        self.assertEqual(health["implementations"], 8)
        self.assertEqual(health["native_verified_ci"], 8)
        self.assertEqual(health["implementation_kernels"], 8)
        self.assertEqual(health["mth_kernels"], 131)
        self.assertEqual(health["status"], {"active": 7, "proposed": 12})
        self.assertEqual(health["proof_status"], {"stated": 12, "verified": 7})

    def test_one_function_multiple_implementations(self):
        function = self.registry.require("math.matrix.pair_space")
        self.assertEqual(len(function.implementations), 2)
        self.assertEqual(
            {item["kernel_id"] for item in function.implementations},
            {
                "mth.graph.pair.tile16.f32",
                "mth.graph.pair.tile16.k16.f32",
            },
        )
        digests = {
            implementation_digest(self.mth.require(item["kernel_id"]))
            for item in function.implementations
        }
        self.assertEqual(len(digests), 2)
        self.assertNotEqual(
            function.implementations[0]["workspace_words"],
            function.implementations[1]["workspace_words"],
        )
        self.assertEqual(function.proof_status, "verified")
        self.assertEqual(function.status, "active")

    def test_compatible_composition(self):
        axpy = self.registry.require("math.vector.axpy")
        norm = self.registry.require("math.vector.norm")
        composed = self.registry.compose([axpy, norm])
        self.assertTrue(composed.function_id.startswith("math.composition."))
        self.assertEqual(composed.signature["inputs"], axpy.signature["inputs"])
        self.assertEqual(composed.signature["output"], norm.signature["output"])
        self.assertEqual(composed.implementations, ())
        self.assertEqual(composed.status, "active")
        self.assertEqual(composed.proof_status, "stated")
        self.assertRegex(composed.contract_digest, r"^[0-9a-f]{64}$")
        self.assertEqual(composed.contract_digest, composed.digest())
        self.assertEqual(
            composed.semantics["composition"],
            ["math.vector.axpy", "math.vector.norm"],
        )
        again = self.registry.compose("math.vector.axpy", "math.vector.norm")
        self.assertEqual(composed.function_id, again.function_id)
        self.assertEqual(composed.contract_digest, again.contract_digest)
        single = self.registry.compose([norm])
        self.assertEqual(single.function_id, norm.function_id)
        self.assertEqual(single.contract_digest, norm.contract_digest)

    def test_incompatible_composition(self):
        dot = self.registry.require("math.vector.dot")
        norm = self.registry.require("math.vector.norm")
        with self.assertRaises(MathCompositionError) as caught:
            self.registry.compose([dot, norm])
        self.assertIn("type", str(caught.exception))

        matvec = self.registry.require("math.vector.matvec")
        with self.assertRaises(MathCompositionError) as caught:
            self.registry.compose([matvec, norm])
        self.assertIn("shape", str(caught.exception))

        axpy = self.registry.require("math.vector.axpy")
        with self.assertRaises(MathCompositionError) as caught:
            self.registry.compose([norm, axpy])
        self.assertIn("exactly one input", str(caught.exception))

        with self.assertRaises(MathFunctionError):
            self.registry.compose(["math.vector.not_a_function"])
        with self.assertRaises(MathCompositionError):
            self.registry.compose([])

    def test_catalog_endpoint_descriptor_roundtrip(self):
        document = _catalog_document()
        fields = {
            "element_type": "float32",
            "stride": [1],
            "layout": "row_major",
            "units": "1",
            "rank": 1,
        }
        _function(document, "math.vector.axpy")["signature"]["output"].update(
            fields,
        )
        _function(document, "math.vector.norm")["signature"]["inputs"][0].update(
            fields,
        )
        registry = self._load_document(document)
        axpy = registry.require("math.vector.axpy")
        norm = registry.require("math.vector.norm")
        self.assertEqual(axpy.signature["output"]["element_type"], "float32")
        self.assertEqual(axpy.signature["output"]["stride"], [1])
        self.assertEqual(norm.signature["inputs"][0]["units"], "1")
        self.assertEqual(norm.signature["inputs"][0]["rank"], 1)
        self.assertEqual(axpy.contract_digest, axpy.digest())
        self.assertNotEqual(
            axpy.contract_digest,
            self.registry.require("math.vector.axpy").contract_digest,
        )
        roundtrip = {
            item["function_id"]: item
            for item in registry.to_dict()["functions"]
        }
        self.assertEqual(
            roundtrip["math.vector.axpy"]["signature"]["output"]["stride"],
            [1],
        )
        self.assertEqual(
            roundtrip["math.vector.norm"]["signature"]["inputs"][0]["layout"],
            "row_major",
        )

    def test_compatible_endpoint_descriptor_handoff(self):
        document = _catalog_document()
        fields = {
            "element_type": "float32",
            "stride": [1],
            "layout": "row_major",
            "units": "1",
            "rank": 1,
            "context": {"frame": "world"},
        }
        _function(document, "math.vector.axpy")["signature"]["output"].update(
            fields,
        )
        _function(document, "math.vector.norm")["signature"]["inputs"][0].update(
            fields,
        )
        _function(document, "math.vector.norm")["signature"]["output"].update({
            "element_type": "float32",
            "stride": 0,
            "layout": "row_major",
            "units": "1",
            "rank": 0,
            "context": {"frame": "world"},
        })
        registry = self._load_document(document)
        composed = registry.compose("math.vector.axpy", "math.vector.norm")
        self.assertEqual(composed.signature["output"]["units"], "1")
        self.assertEqual(
            composed.signature["output"]["context"], {"frame": "world"},
        )
        self.assertEqual(composed.contract_digest, composed.digest())

    def test_incompatible_endpoint_descriptor_handoff(self):
        cases = (
            ("element_type", "float32", "float64"),
            ("stride", [1], [2]),
            ("layout", "row_major", "column_major"),
            ("units", "1", "m"),
        )
        for field, producer_value, consumer_value in cases:
            with self.subTest(field=field):
                document = _catalog_document()
                _function(
                    document, "math.vector.axpy",
                )["signature"]["output"][field] = producer_value
                _function(
                    document, "math.vector.norm",
                )["signature"]["inputs"][0][field] = consumer_value
                registry = self._load_document(document)
                with self.assertRaises(MathCompositionError) as caught:
                    registry.compose(
                        "math.vector.axpy", "math.vector.norm",
                    )
                self.assertIn(field, str(caught.exception))
                self.assertIn("cannot compose", str(caught.exception))

    def test_one_sided_endpoint_descriptor_handoff_is_compatible(self):
        descriptors = {
            "element_type": "float32",
            "stride": [1],
            "layout": "row_major",
            "units": "1",
            "rank": 1,
        }
        for producer_declares, consumer_declares in ((True, False), (False, True)):
            with self.subTest(
                    producer=producer_declares, consumer=consumer_declares):
                document = _catalog_document()
                if producer_declares:
                    _function(
                        document, "math.vector.axpy",
                    )["signature"]["output"].update(descriptors)
                if consumer_declares:
                    _function(
                        document, "math.vector.norm",
                    )["signature"]["inputs"][0].update(descriptors)
                registry = self._load_document(document)
                composed = registry.compose(
                    "math.vector.axpy", "math.vector.norm",
                )
                self.assertTrue(
                    composed.function_id.startswith("math.composition.")
                )

    def test_compatibility_index_is_deterministic(self):
        first = self.registry.compatibility_index()
        second = self.registry.compatibility_index()
        self.assertEqual(first, second)
        self.assertEqual(first["schema"], COMPATIBILITY_SCHEMA)
        self.assertGreaterEqual(first["functions"], len(self.registry))
        keys = {
            (entry["signature_key"], entry["function_id"])
            for entry in first["entries"]
        }
        self.assertEqual(len(keys), len(first["entries"]))

    def test_no_executor_imports(self):
        tree = ast.parse(MATH_REGISTRY_SOURCE.read_text(encoding="utf-8"))
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.add(node.module or "")
        allowed = {
            "__future__", "json", "re", "collections", "collections.abc",
            "dataclasses", "pathlib", "typing", "math_objects", "mth_registry",
        }
        self.assertEqual(modules - allowed, set())
        self.assertIn("math_objects", modules)
        self.assertIn("mth_registry", modules)
        forbidden = (
            "mth_system", "wave", "point0", "nmp", "runtime", "store",
            "executor", "preflight", "orchestrator", "subprocess", "socket",
        )
        for module in modules:
            for marker in forbidden:
                self.assertNotIn(marker, module)


if __name__ == "__main__":
    unittest.main()
