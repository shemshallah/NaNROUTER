from __future__ import annotations

import ast
import inspect
import json
import unittest
from pathlib import Path

from runner_riddle import rss_controller
from runner_riddle.mth_registry import MthKernelDescriptor, MthRegistry
from runner_riddle.rss_controller import (
    DEFAULT_ROUTES,
    RSS_REASON_FILTER_NOT_CI_VERIFIED,
    RSS_REASON_FILTER_UNAVAILABLE,
    RSS_REASON_KERNEL_NOT_NATIVE_VERIFIED,
    RSS_REASON_STEP_LIMIT,
    RSS_REASON_UNKNOWN_KERNEL,
    RSS_REASON_UNKNOWN_VERB,
    RSS_REASON_WORKSPACE,
    RSS_STATUS_PLANNED,
    RSS_STATUS_UNAVAILABLE,
    RSS_VERBS,
    RssController,
    RssKernelError,
    RssPlanStepSpec,
    RssStepLimitError,
    RssUnavailableError,
    RssVerbError,
    RssWorkspaceError,
    plan_digest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "spec" / "wave-capabilities.json"


def _descriptor(
    kernel_id: str,
    *,
    workspace_words: int = 0,
    status: str = "native_verified",
    ci_verified: bool = True,
    precision: str = "float32",
) -> MthKernelDescriptor:
    return MthKernelDescriptor(
        kernel_id=kernel_id,
        source=f"mth/nan16/{kernel_id.rsplit('.', 2)[-1]}.nas",
        fixture=f"mth/tests/{kernel_id.rsplit('.', 2)[-1]}_test.nas",
        marker="TEST",
        steps=1,
        precision=precision,
        workspace_words=workspace_words,
        shape=(256,),
        status=status,
        ci_verified=ci_verified,
        source_digest="a" * 64,
        fixture_digest="b" * 64,
    )


class RssControllerRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = MthRegistry.load(MANIFEST)
        cls.controller = RssController(cls.registry)

    def test_default_routes_cover_exactly_the_eight_public_verbs(self):
        self.assertEqual(tuple(DEFAULT_ROUTES), RSS_VERBS)
        self.assertEqual(self.controller.verbs, RSS_VERBS)
        self.assertEqual(tuple(self.controller.routes), RSS_VERBS)
        expected = {
            "ENCODE": "mth.encode.256.full.f32",
            "QUERY": "mth.sparse.laplacian.q16.16",
            "MATCH": "mth.vector.cosine256.f32",
            "FILTER": "mth.graph.filter.poly2.q16.16",
            "DRIVE": "mth.drive.source.256.f32",
            "PROPAGATE": "mth.graph.wave_step.f32",
            "FOLD": "mth.graph.fold.f32",
            "DECODE": "mth.decode.256.full.f32",
        }
        for verb, kernel_id in expected.items():
            with self.subTest(verb=verb):
                self.assertEqual(
                    self.controller.routes[verb], (kernel_id,)
                )

    def test_composes_validated_plans_for_every_dispatchable_verb(self):
        for verb in RSS_VERBS:
            with self.subTest(verb=verb):
                result = self.controller.route(verb)
                if verb == "FILTER":
                    self.assertEqual(result.status, RSS_STATUS_UNAVAILABLE)
                    self.assertEqual(
                        result.reason, RSS_REASON_FILTER_NOT_CI_VERIFIED
                    )
                    self.assertIsNone(result.plan)
                    self.assertIsNone(result.plan_digest)
                    continue
                self.assertEqual(result.status, RSS_STATUS_PLANNED)
                self.assertTrue(result.available)
                plan = result.require_plan()
                self.assertIs(result.plan, plan)
                self.assertIs(self.registry.validate_plan(plan), plan)
                self.assertEqual(result.kernel_ids, plan.kernel_ids)
                self.assertEqual(result.step_count, len(plan.steps))
                self.assertEqual(
                    result.workspace_words, plan.workspace_words
                )
                self.assertTrue(plan.deterministic)
                self.assertRegex(result.plan_digest, r"^[0-9a-f]{64}$")
                self.assertEqual(result.plan_digest, plan_digest(plan))
                json.dumps(result.to_dict())

    def test_custom_route_composes_multiple_kernels_in_order(self):
        registry = MthRegistry([
            _descriptor("mth.test.alpha.f32", workspace_words=4),
            _descriptor("mth.test.beta.f32", workspace_words=6),
        ])
        controller = RssController(
            registry,
            {"query": (
                "mth.test.alpha.f32",
                RssPlanStepSpec(
                    name="beta",
                    kernel_id="mth.test.beta.f32",
                ),
            )},
        )
        result = controller.route("QUERY")
        self.assertEqual(result.status, RSS_STATUS_PLANNED)
        plan = result.require_plan()
        self.assertEqual(
            plan.kernel_ids, ("mth.test.alpha.f32", "mth.test.beta.f32")
        )
        first, second = plan.steps
        self.assertEqual((first.name, second.name), ("query.step0", "beta"))
        self.assertEqual(second.depends_on, (first.name,))
        self.assertEqual(second.inputs, (first.outputs[0],))
        self.assertEqual(plan.workspace_words, 10)
        self.assertEqual(result.step_count, 2)
        self.assertIs(registry.validate_plan(plan), plan)
        self.assertEqual(
            controller.to_dict()["routes"]["QUERY"][1]["kernel_id"],
            "mth.test.beta.f32",
        )

    def test_unknown_kernel_is_rejected(self):
        controller = RssController(
            self.registry, {"QUERY": ("mth.not.registered.kernel",)}
        )
        with self.assertRaises(RssKernelError) as caught:
            controller.route("QUERY")
        self.assertEqual(caught.exception.reason, RSS_REASON_UNKNOWN_KERNEL)
        self.assertIn("mth.not.registered.kernel", str(caught.exception))

    def test_non_native_verified_kernel_is_rejected(self):
        registry = MthRegistry([
            _descriptor(
                "mth.test.source_only.f32",
                status="source_written",
                ci_verified=False,
            ),
        ])
        controller = RssController(
            registry, {"MATCH": ("mth.test.source_only.f32",)}
        )
        with self.assertRaises(RssKernelError) as caught:
            controller.route("MATCH")
        self.assertEqual(
            caught.exception.reason, RSS_REASON_KERNEL_NOT_NATIVE_VERIFIED
        )

    def test_unknown_verb_is_rejected(self):
        with self.assertRaises(RssVerbError) as caught:
            self.controller.route("PROJECT")
        self.assertEqual(caught.exception.reason, RSS_REASON_UNKNOWN_VERB)
        with self.assertRaises(RssVerbError):
            RssController(self.registry, {"PROJECT": ("mth.vector.dot256.f32",)})

    def test_workspace_below_requirement_and_budget_are_rejected(self):
        registry = MthRegistry([
            _descriptor("mth.test.workspace.f32", workspace_words=8),
        ])
        controller = RssController(
            registry, {"QUERY": ("mth.test.workspace.f32",)}
        )
        with self.assertRaises(RssWorkspaceError) as caught:
            controller.route("QUERY", workspace_words=0)
        self.assertEqual(caught.exception.reason, RSS_REASON_WORKSPACE)

        bounded = RssController(
            registry,
            {"QUERY": ("mth.test.workspace.f32",)},
            max_workspace_words=4,
        )
        with self.assertRaises(RssWorkspaceError) as caught:
            bounded.route("QUERY")
        self.assertEqual(caught.exception.reason, RSS_REASON_WORKSPACE)

        planned = controller.route("QUERY", workspace_words=16)
        self.assertEqual(planned.plan.workspace_words, 16)

    def test_step_limit_is_enforced(self):
        registry = MthRegistry([
            _descriptor("mth.test.alpha.f32"),
            _descriptor("mth.test.beta.f32"),
        ])
        controller = RssController(
            registry,
            {"QUERY": ("mth.test.alpha.f32", "mth.test.beta.f32")},
            max_steps=1,
        )
        with self.assertRaises(RssStepLimitError) as caught:
            controller.route("QUERY")
        self.assertEqual(caught.exception.reason, RSS_REASON_STEP_LIMIT)

    def test_filter_without_registered_kernel_is_typed_unavailable(self):
        registry = MthRegistry([_descriptor("mth.test.present.f32")])
        controller = RssController(registry)
        result = controller.route("FILTER")
        self.assertEqual(result.status, RSS_STATUS_UNAVAILABLE)
        self.assertEqual(result.reason, RSS_REASON_FILTER_UNAVAILABLE)
        self.assertIsNone(result.plan)
        self.assertIsNone(result.plan_digest)
        self.assertEqual(
            result.kernel_ids, ("mth.graph.filter.poly2.q16.16",)
        )
        self.assertFalse(result.available)
        with self.assertRaises(RssUnavailableError):
            result.require_plan()
        self.assertEqual(
            controller.availability()["FILTER"]["status"],
            RSS_STATUS_UNAVAILABLE,
        )

    def test_real_filter_kernel_is_unavailable_until_ci_verified(self):
        descriptor = self.registry.require("mth.graph.filter.poly2.q16.16")
        self.assertEqual(descriptor.status, "native_verified")
        self.assertFalse(descriptor.ci_verified)
        result = self.controller.route("FILTER")
        self.assertEqual(result.status, RSS_STATUS_UNAVAILABLE)
        self.assertEqual(
            result.reason, RSS_REASON_FILTER_NOT_CI_VERIFIED
        )

    def test_plan_digest_is_deterministic(self):
        first = self.controller.route("MATCH")
        second = RssController(self.registry).route("MATCH")
        self.assertEqual(first.plan_digest, second.plan_digest)
        self.assertEqual(
            first.plan_digest,
            plan_digest(first.require_plan()),
        )
        self.assertEqual(
            first.to_dict()["plan_digest"], second.to_dict()["plan_digest"]
        )
        renamed = self.controller.route("MATCH", plan_id="rss.match.alt")
        self.assertNotEqual(first.plan_digest, renamed.plan_digest)
        self.assertEqual(
            json.dumps(first.to_dict(), sort_keys=True),
            json.dumps(second.to_dict(), sort_keys=True),
        )


class RssControllerBoundaryTests(unittest.TestCase):
    def test_no_host_math_imports_or_arithmetic_operations(self):
        source = inspect.getsource(rss_controller)
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

        controller = RssController(MthRegistry.load(MANIFEST))
        for name in ("execute", "dispatch", "submit", "run", "apply"):
            self.assertFalse(hasattr(controller, name))
        for name in ("execute", "dispatch", "submit"):
            self.assertFalse(hasattr(rss_controller, name))


if __name__ == "__main__":
    unittest.main()
