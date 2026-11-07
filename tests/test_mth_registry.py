from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from runner_riddle.mth_registry import (
    KERNEL_STATUSES,
    MANIFEST_SCHEMA,
    PLAN_SCHEMA,
    PLAN_SPEC_SCHEMA,
    PRECISIONS,
    REGISTRY_SCHEMA,
    MthKernelDescriptor,
    MthManifestError,
    MthPlan,
    MthPlanError,
    MthPlanStep,
    MthRegistry,
    MthRegistryError,
    sha256_file,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "spec" / "wave-capabilities.json"
SCHEMA = REPO_ROOT / "spec" / "mth-system.schema.json"


def _document() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _mutated_manifest(root: str | Path, mutate) -> Path:
    document = _document()
    mutate(document)
    path = Path(root) / "wave-capabilities.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


class RealManifestRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = _document()
        cls.registry = MthRegistry.load(MANIFEST)

    def test_loads_every_declared_kernel_in_manifest_order(self):
        declared = [kernel["kernel_id"] for kernel in self.document["kernels"]]
        loaded = [descriptor.kernel_id for descriptor in self.registry]
        self.assertGreaterEqual(len(loaded), 31)
        self.assertEqual(len(loaded), len(declared))
        self.assertEqual(loaded, declared)
        self.assertEqual(len(loaded), len(set(loaded)))
        for kernel_id in (
            "mth.k256.laplacian.u16",
            "mth.ring255.port.f32",
            "mth.graph.pair.full.128.f32",
            "mth.graph.transmission.128.f32",
        ):
            self.assertIn(kernel_id, self.registry)

    def test_digests_are_computed_from_source_and_fixture_bytes(self):
        for descriptor in self.registry:
            self.assertRegex(descriptor.source_digest, r"^[0-9a-f]{64}$")
            self.assertRegex(descriptor.fixture_digest, r"^[0-9a-f]{64}$")
        for descriptor in (self.registry.kernels[0], self.registry.kernels[-1]):
            source = (REPO_ROOT / descriptor.source).read_bytes()
            fixture = (REPO_ROOT / descriptor.fixture).read_bytes()
            self.assertEqual(
                descriptor.source_digest,
                hashlib.sha256(source).hexdigest(),
            )
            self.assertEqual(
                descriptor.fixture_digest,
                hashlib.sha256(fixture).hexdigest(),
            )
            self.assertEqual(
                descriptor.source_digest,
                sha256_file(REPO_ROOT / descriptor.source),
            )

    def test_descriptor_contract_and_derived_tags(self):
        descriptor = self.registry.require("mth.ring255.port.f32")
        self.assertIsInstance(descriptor, MthKernelDescriptor)
        self.assertEqual(descriptor.version, 1)
        self.assertEqual(descriptor.source, "mth/nan16/mth_ring255_port.nas")
        self.assertEqual(descriptor.fixture, "mth/tests/mth_ring255_port_test.nas")
        self.assertEqual(descriptor.marker, "MTH RING255 PORT ASSEMBLE PASS")
        self.assertEqual(descriptor.steps, 3353)
        self.assertEqual(descriptor.precision, "float32")
        self.assertEqual(descriptor.workspace_words, 0)
        self.assertEqual(descriptor.shape, (255, 1, 256))
        self.assertEqual(descriptor.status, "native_verified")
        self.assertTrue(descriptor.ci_verified)
        self.assertIn("family:ring255", descriptor.tags)
        self.assertIn("precision:float32", descriptor.tags)
        self.assertIn("shape:255x1x256", descriptor.tags)
        self.assertIn("ci:verified", descriptor.tags)
        self.assertIn("workspace:zero", descriptor.tags)

    def test_lookup_and_require(self):
        descriptor = self.registry.lookup("mth.vector.dot256.f32")
        self.assertIsNotNone(descriptor)
        self.assertIs(descriptor, self.registry.require("mth.vector.dot256.f32"))
        self.assertIsNone(self.registry.lookup("mth.not.a.real.kernel"))
        self.assertNotIn("mth.not.a.real.kernel", self.registry)
        with self.assertRaises(MthRegistryError):
            self.registry.require("mth.not.a.real.kernel")

    def test_resolve_requires_ci_by_default_and_preserves_manifest_order(self):
        expected = tuple(
            descriptor for descriptor in self.registry if descriptor.ci_verified
        )
        selected = self.registry.resolve()
        self.assertEqual(selected, expected)
        self.assertGreaterEqual(len(selected), 31)
        self.assertTrue(all(descriptor.ci_verified for descriptor in selected))
        self.assertEqual(
            self.registry.resolve(require_ci=False),
            tuple(self.registry),
        )

    def test_resolve_filters_by_workspace_bound(self):
        for limit in (0, 4, 16, 256):
            expected = tuple(
                descriptor for descriptor in self.registry
                if descriptor.workspace_words <= limit
            )
            with self.subTest(limit=limit):
                selected = self.registry.resolve(
                    max_workspace=limit, require_ci=False
                )
                self.assertEqual(selected, expected)
                self.assertTrue(
                    all(descriptor.workspace_words <= limit for descriptor in selected)
                )
        with self.assertRaises(MthRegistryError):
            self.registry.resolve(max_workspace=-1)

    def test_resolve_filters_all_requested_tags(self):
        vector = self.registry.resolve(tags="family:vector")
        self.assertEqual(
            [descriptor.kernel_id for descriptor in vector],
            [
                "mth.vector.dot256.f32",
                "mth.vector.norm256.f32",
                "mth.vector.axpy256.f32",
                "mth.vector.cosine256.f32",
            ],
        )
        self.assertEqual(
            self.registry.resolve(tags=["family:vector", "precision:float32"]),
            vector,
        )
        zero_workspace = self.registry.resolve(
            tags=["family:vector"], max_workspace=0
        )
        self.assertEqual(
            [descriptor.kernel_id for descriptor in zero_workspace],
            [
                "mth.vector.dot256.f32",
                "mth.vector.norm256.f32",
                "mth.vector.axpy256.f32",
            ],
        )
        self.assertEqual(self.registry.resolve(tags="family:missing"), ())

    def test_health_counts_match_manifest(self):
        health = self.registry.health()
        self.assertEqual(health["schema"], "nanrouter.mth-registry-health.v1")
        self.assertEqual(health["kernels"], len(self.registry))
        status_counts = dict(sorted(Counter(
            descriptor.status for descriptor in self.registry
        ).items()))
        precision_counts = dict(sorted(Counter(
            descriptor.precision for descriptor in self.registry
        ).items()))
        ci_counts = Counter(descriptor.ci_verified for descriptor in self.registry)
        self.assertEqual(health["status"], status_counts)
        self.assertEqual(health["precision"], precision_counts)
        self.assertEqual(health["ci"], {
            "verified": ci_counts.get(True, 0),
            "unverified": ci_counts.get(False, 0),
        })
        self.assertEqual(health["ci_verified"], ci_counts.get(True, 0))
        self.assertEqual(health["ci_unverified"], ci_counts.get(False, 0))
        self.assertEqual(
            health["native_verified_ci"],
            sum(
                1 for descriptor in self.registry
                if descriptor.status == "native_verified" and descriptor.ci_verified
            ),
        )

    def test_registry_document(self):
        document = self.registry.to_dict()
        self.assertEqual(document["schema"], REGISTRY_SCHEMA)
        self.assertEqual(document["version"], 1)
        self.assertEqual(len(document["kernels"]), len(self.registry))
        first = document["kernels"][0]
        self.assertIsInstance(first["shape"], list)
        self.assertIsInstance(first["tags"], list)
        self.assertRegex(first["source_digest"], r"^[0-9a-f]{64}$")
        json.dumps(document)


class InvalidManifestTests(unittest.TestCase):
    def _load(self, temp: str, mutate) -> MthRegistry:
        path = _mutated_manifest(temp, mutate)
        return MthRegistry.load(path, root=REPO_ROOT)

    def test_rejects_duplicate_kernel_id(self):
        def mutate(document):
            document["kernels"].append(dict(document["kernels"][0]))

        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(MthManifestError):
                self._load(temp, mutate)

    def test_rejects_missing_source_or_fixture_file(self):
        for field in ("source", "fixture"):
            def mutate(document, field=field):
                document["kernels"][0][field] = "mth/nan16/does_not_exist.nas"

            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp:
                with self.assertRaises(MthManifestError):
                    self._load(temp, mutate)

    def test_rejects_invalid_kernel_fields(self):
        cases = {
            "steps_zero": lambda kernel: kernel.update(steps=0),
            "steps_bool": lambda kernel: kernel.update(steps=True),
            "precision": lambda kernel: kernel.update(precision="int8"),
            "workspace": lambda kernel: kernel.update(workspace_words=-1),
            "shape_empty": lambda kernel: kernel.update(shape=[]),
            "shape_type": lambda kernel: kernel.update(shape="256"),
            "shape_value": lambda kernel: kernel.update(shape=[0]),
            "status": lambda kernel: kernel.update(status="bogus"),
            "ci_type": lambda kernel: kernel.update(ci_verified="yes"),
            "marker": lambda kernel: kernel.update(marker=""),
            "version": lambda kernel: kernel.update(version=0),
            "tags": lambda kernel: kernel.update(tags=["Not A Tag"]),
            "duplicate_tags": lambda kernel: kernel.update(tags=["extra", "extra"]),
        }
        for label, change in cases.items():
            def mutate(document, change=change):
                change(document["kernels"][0])

            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp:
                with self.assertRaises(MthManifestError):
                    self._load(temp, mutate)

    def test_rejects_wrong_schema_or_empty_kernel_list(self):
        cases = {
            "schema": lambda document: document.update(schema="nanrouter.other.v1"),
            "empty": lambda document: document.update(kernels=[]),
            "not_list": lambda document: document.update(kernels={}),
        }
        for label, mutate in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp:
                with self.assertRaises(MthManifestError):
                    self._load(temp, mutate)

    def test_rejects_absolute_or_escaping_member_paths(self):
        cases = {
            "absolute": lambda document: document["kernels"][0].update(
                fixture="/etc/passwd"
            ),
            "escape": lambda document: document["kernels"][0].update(
                source="../outside.nas"
            ),
        }
        for label, mutate in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp:
                with self.assertRaises(MthManifestError):
                    self._load(temp, mutate)

    def test_rejects_missing_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(MthManifestError):
                MthRegistry.load(Path(temp) / "missing.json")


class MthPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = MthRegistry.load(MANIFEST)

    def test_compose_builds_ordered_typed_plan(self):
        plan = self.registry.compose({
            "schema": PLAN_SPEC_SCHEMA,
            "plan_id": "vector.match.v1",
            "steps": [
                {
                    "name": "dot",
                    "kernel_id": "mth.vector.dot256.f32",
                    "inputs": ["f32[256].a", "f32[256].b"],
                    "outputs": ["f32.dot"],
                    "depends_on": [],
                },
                {
                    "name": "norm",
                    "kernel_id": "mth.vector.norm256.f32",
                    "inputs": ["f32[256].a"],
                    "outputs": ["f32.norm"],
                    "depends_on": [],
                },
                {
                    "name": "score",
                    "kernel_id": "mth.vector.cosine256.f32",
                    "inputs": ["f32[256].a", "f32[256].b", "f32.dot"],
                    "outputs": ["f32.score"],
                    "depends_on": ["dot"],
                },
            ],
        })
        self.assertIsInstance(plan, MthPlan)
        self.assertEqual(plan.plan_id, "vector.match.v1")
        self.assertEqual(plan.version, 1)
        self.assertEqual(tuple(step.name for step in plan.steps), ("dot", "norm", "score"))
        self.assertEqual(plan.kernel_ids, (
            "mth.vector.dot256.f32",
            "mth.vector.norm256.f32",
            "mth.vector.cosine256.f32",
        ))
        self.assertEqual(plan.workspace_words, 4)
        self.assertTrue(plan.deterministic)
        self.assertEqual(plan.inputs, ("f32[256].a", "f32[256].b"))
        self.assertEqual(plan.outputs, ("f32.dot", "f32.norm", "f32.score"))
        self.assertIs(self.registry.validate_plan(plan), plan)

        document = plan.to_dict()
        self.assertEqual(document["schema"], PLAN_SCHEMA)
        self.assertEqual(document["version"], 1)
        self.assertEqual(document["kernel_ids"], list(plan.kernel_ids))
        self.assertEqual(document["inputs"], list(plan.inputs))
        self.assertEqual(document["outputs"], list(plan.outputs))
        self.assertTrue(document["deterministic"])
        json.dumps(document)

    def test_compose_orders_steps_by_dependencies(self):
        plan = self.registry.compose({
            "plan_id": "ordered",
            "steps": [
                {
                    "name": "second",
                    "kernel_id": "mth.vector.norm256.f32",
                    "inputs": ["f32[256].a"],
                    "outputs": ["f32.second"],
                    "depends_on": ["first"],
                },
                {
                    "name": "first",
                    "kernel_id": "mth.vector.dot256.f32",
                    "inputs": ["f32[256].a", "f32[256].b"],
                    "outputs": ["f32.first"],
                    "depends_on": [],
                },
            ],
        })
        self.assertEqual(tuple(step.name for step in plan.steps), ("first", "second"))
        self.assertEqual(plan.outputs, ("f32.first", "f32.second"))

    def test_compose_allows_in_place_and_reused_typed_names(self):
        plan = self.registry.compose({
            "plan_id": "in-place",
            "steps": [
                {
                    "name": "update",
                    "kernel_id": "mth.vector.axpy256.f32",
                    "inputs": ["f32[256].state", "f32[256].delta"],
                    "outputs": ["f32[256].state"],
                    "depends_on": [],
                },
                {
                    "name": "renorm",
                    "kernel_id": "mth.vector.norm256.f32",
                    "inputs": ["f32[256].state"],
                    "outputs": ["f32[256].state"],
                    "depends_on": ["update"],
                },
            ],
        })
        self.assertEqual(
            tuple(step.name for step in plan.steps), ("update", "renorm")
        )
        self.assertEqual(plan.inputs, ("f32[256].delta",))
        self.assertEqual(plan.outputs, ("f32[256].state",))

    def test_compose_accepts_an_explicit_workspace_bound(self):
        plan = self.registry.compose({
            "plan_id": "workspace",
            "workspace_words": 32,
            "steps": [{
                "name": "score",
                "kernel_id": "mth.vector.cosine256.f32",
                "inputs": ["f32[256].a", "f32[256].b"],
                "outputs": ["f32.score"],
                "depends_on": [],
            }],
        })
        self.assertEqual(plan.workspace_words, 32)

    def test_compose_rejects_invalid_specs(self):
        dot = {
            "name": "dot",
            "kernel_id": "mth.vector.dot256.f32",
            "inputs": ["f32[256].a", "f32[256].b"],
            "outputs": ["f32.dot"],
            "depends_on": [],
        }
        cases = {
            "duplicate_name": {
                "steps": [dot, dict(dot, outputs=["f32.dot2"])],
            },
            "unknown_kernel": {
                "steps": [dict(dot, kernel_id="mth.not.real")],
            },
            "unknown_dependency": {
                "steps": [dict(dot, depends_on=["missing"])],
            },
            "cycle": {
                "steps": [
                    dict(dot, name="a", depends_on=["b"]),
                    dict(dot, name="b", outputs=["f32.dot2"], depends_on=["a"]),
                ],
            },
            "workspace_too_small": {
                "workspace_words": 0,
                "steps": [{
                    "name": "score",
                    "kernel_id": "mth.vector.cosine256.f32",
                    "inputs": ["f32[256].a", "f32[256].b"],
                    "outputs": ["f32.score"],
                    "depends_on": [],
                }],
            },
            "unknown_plan_field": {"steps": [dot], "surprise": True},
            "unknown_step_field": {"steps": [dict(dot, surprise=True)]},
            "bad_schema": {"schema": "nanrouter.other.v1", "steps": [dot]},
            "empty_steps": {"steps": []},
        }
        for label, spec in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(MthPlanError):
                    self.registry.compose(spec)

    def test_validate_plan_rejects_forward_dependency(self):
        plan = MthPlan(
            plan_id="forward",
            steps=(
                MthPlanStep(
                    name="second",
                    kernel_id="mth.vector.norm256.f32",
                    depends_on=("first",),
                ),
                MthPlanStep(name="first", kernel_id="mth.vector.dot256.f32"),
            ),
        )
        with self.assertRaises(MthPlanError):
            self.registry.validate_plan(plan)

    def test_validate_plan_rejects_duplicate_step_names(self):
        plan = MthPlan(
            plan_id="duplicate",
            steps=(
                MthPlanStep(name="same", kernel_id="mth.vector.dot256.f32"),
                MthPlanStep(name="same", kernel_id="mth.vector.norm256.f32"),
            ),
        )
        with self.assertRaises(MthPlanError):
            self.registry.validate_plan(plan)

    def test_plan_workspace_peak_releases_completed_steps(self):
        def descriptor(name, workspace):
            return MthKernelDescriptor(
                kernel_id=f"mth.test.{name}.f32",
                source=f"{name}.nas",
                fixture=f"{name}_test.nas",
                marker="TEST",
                steps=1,
                precision="float32",
                workspace_words=workspace,
                shape=(1,),
                status="native_verified",
                ci_verified=True,
                source_digest="a" * 64,
                fixture_digest="b" * 64,
            )
        registry = MthRegistry([
            descriptor("a", 10), descriptor("b", 20), descriptor("c", 30),
        ])
        plan = MthPlan(
            plan_id="peak",
            steps=(
                MthPlanStep(name="a", kernel_id="mth.test.a.f32"),
                MthPlanStep(name="b", kernel_id="mth.test.b.f32", depends_on=("a",)),
                MthPlanStep(name="c", kernel_id="mth.test.c.f32"),
            ),
            workspace_words=60,
        )
        self.assertEqual(registry.plan_workspace_peak(plan), 30)
        self.assertEqual(plan.workspace_words, 60)

    def test_validate_plan_requires_workspace_bound(self):
        step = MthPlanStep(
            name="score",
            kernel_id="mth.vector.cosine256.f32",
            inputs=("f32[256].a", "f32[256].b"),
            outputs=("f32.score",),
        )
        with self.assertRaises(MthPlanError):
            self.registry.validate_plan(MthPlan(
                plan_id="too-small", steps=(step,), workspace_words=0,
            ))
        plan = MthPlan(
            plan_id="bounded", steps=(step,), workspace_words=4,
        )
        self.assertIs(self.registry.validate_plan(plan), plan)

    def test_validate_plan_rejects_unknown_kernel(self):
        plan = MthPlan(
            plan_id="unknown",
            steps=(MthPlanStep(name="x", kernel_id="mth.not.real"),),
        )
        with self.assertRaises(MthPlanError):
            self.registry.validate_plan(plan)

    def test_validate_plan_rejects_unverified_or_non_native_kernel(self):
        cases = {
            "unverified": lambda kernel: kernel.update(ci_verified=False),
            "declared": lambda kernel: kernel.update(status="declared"),
        }
        for label, change in cases.items():
            def mutate(document, change=change):
                change(document["kernels"][0])

            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp:
                path = _mutated_manifest(temp, mutate)
                registry = MthRegistry.load(path, root=REPO_ROOT)
                kernel_id = _document()["kernels"][0]["kernel_id"]
                with self.assertRaises(MthPlanError):
                    registry.compose({
                        "plan_id": label,
                        "steps": [{
                            "name": "step",
                            "kernel_id": kernel_id,
                            "inputs": ["f32[256].a"],
                            "outputs": ["f32.out"],
                            "depends_on": [],
                        }],
                    })


class SchemaDocumentTests(unittest.TestCase):
    def test_schema_is_valid_json_and_covers_the_contract(self):
        document = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(
            document["$schema"], "https://json-schema.org/draft/2020-12/schema"
        )
        definitions = document["$defs"]
        for name in (
            "kernelDescriptor", "planStep", "planSpec",
            "registryDocument", "planDocument",
        ):
            self.assertIn(name, definitions)
        self.assertEqual(tuple(definitions["precision"]["enum"]), PRECISIONS)
        self.assertEqual(tuple(definitions["kernelStatus"]["enum"]), KERNEL_STATUSES)
        descriptor_required = set(definitions["kernelDescriptor"]["required"])
        self.assertTrue({
            "kernel_id", "version", "source", "fixture", "marker", "steps",
            "precision", "workspace_words", "shape", "status", "ci_verified",
            "source_digest", "fixture_digest", "tags",
        }.issubset(descriptor_required))
        step_required = set(definitions["planStep"]["required"])
        self.assertEqual(step_required, {
            "name", "kernel_id", "inputs", "outputs", "depends_on",
        })
        plan_required = set(definitions["planDocument"]["required"])
        self.assertTrue({
            "schema", "version", "plan_id", "steps", "kernel_ids",
            "inputs", "outputs", "workspace_words", "deterministic",
        }.issubset(plan_required))
        self.assertEqual(
            definitions["registryDocument"]["properties"]["schema"]["const"],
            REGISTRY_SCHEMA,
        )
        self.assertEqual(
            definitions["planDocument"]["properties"]["schema"]["const"],
            PLAN_SCHEMA,
        )
        self.assertEqual(
            definitions["planSpec"]["properties"]["schema"]["const"],
            PLAN_SPEC_SCHEMA,
        )
        self.assertEqual(MANIFEST_SCHEMA, "nanrouter.wave-capabilities.v1")


if __name__ == "__main__":
    unittest.main()
