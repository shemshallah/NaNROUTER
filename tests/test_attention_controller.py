from __future__ import annotations

import ast
import inspect
import json
import unittest
from pathlib import Path

from runner_riddle import attention_controller
from runner_riddle.attention_controller import (
    ATTENTION_CRITICAL_STAGES,
    ATTENTION_MASK_POLICIES,
    ATTENTION_REASON_INVALID_MASK_POLICY,
    ATTENTION_REASON_KERNEL_NOT_CI_VERIFIED,
    ATTENTION_REASON_KERNEL_NOT_NATIVE_VERIFIED,
    ATTENTION_REASON_MASK_UNAVAILABLE,
    ATTENTION_REASON_SOFTMAX_UNAVAILABLE,
    ATTENTION_REASON_STEP_LIMIT,
    ATTENTION_REASON_UNKNOWN_KERNEL,
    ATTENTION_REASON_WEIGHTED_SUM_UNAVAILABLE,
    ATTENTION_REASON_WORKSPACE,
    ATTENTION_STAGES,
    ATTENTION_STATUS_PLANNED,
    ATTENTION_STATUS_UNAVAILABLE,
    DEFAULT_MASK_POLICY,
    DEFAULT_STAGE_KERNELS,
    AttentionConfigError,
    AttentionController,
    AttentionKernelError,
    AttentionMaskError,
    AttentionStepLimitError,
    AttentionUnavailableError,
    AttentionWorkspaceError,
    plan_digest,
)
from runner_riddle.mth_registry import MthKernelDescriptor, MthRegistry

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


def _registry(
    *,
    omit: tuple[str, ...] = (),
    workspace_words: int = 0,
    overrides: dict[str, dict[str, object]] | None = None,
) -> MthRegistry:
    overrides = overrides or {}
    descriptors = []
    for stage in ATTENTION_STAGES:
        if stage in omit:
            continue
        options = overrides.get(stage, {})
        descriptors.append(
            _descriptor(
                DEFAULT_STAGE_KERNELS[stage],
                workspace_words=options.get("workspace_words", workspace_words),
                status=options.get("status", "native_verified"),
                ci_verified=options.get("ci_verified", True),
            )
        )
    return MthRegistry(descriptors)


class AttentionControllerPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = MthRegistry.load(MANIFEST)

    def test_available_route_composes_explicit_native_stage_plan(self):
        registry = _registry(workspace_words=2)
        controller = AttentionController(registry)
        result = controller.route()

        self.assertEqual(result.status, ATTENTION_STATUS_PLANNED)
        self.assertTrue(result.available)
        self.assertEqual(result.mask_policy, DEFAULT_MASK_POLICY)
        self.assertEqual(result.stages, ATTENTION_STAGES)
        self.assertEqual(
            result.kernel_ids,
            tuple(DEFAULT_STAGE_KERNELS[stage] for stage in ATTENTION_STAGES),
        )
        self.assertEqual(result.step_count, len(ATTENTION_STAGES))
        self.assertEqual(result.workspace_words, 14)
        self.assertTrue(result.deterministic)
        self.assertRegex(result.plan_digest, r"^[0-9a-f]{64}$")

        plan = result.require_plan()
        self.assertIs(result.plan, plan)
        self.assertIs(registry.validate_plan(plan), plan)
        self.assertEqual(result.plan_digest, plan_digest(plan))
        self.assertEqual(
            [step.name for step in plan.steps],
            [
                "attention.qk-dot",
                "attention.scale",
                "attention.mask",
                "attention.softmax",
                "attention.weighted-sum",
                "attention.head-concat",
                "attention.projection",
            ],
        )
        for previous, step in zip(plan.steps, plan.steps[1:]):
            self.assertEqual(step.depends_on, (previous.name,))
        self.assertEqual(
            plan.steps[0].inputs,
            ("f32[256].attention.query", "f32[256].attention.key"),
        )
        self.assertEqual(
            plan.steps[4].inputs,
            (
                "f32[256].attention.weights",
                "f32[256].attention.value",
            ),
        )
        self.assertEqual(
            plan.steps[-1].outputs,
            ("f32[256].attention.projected",),
        )
        self.assertEqual(
            plan.outputs[-1], "f32[256].attention.projected"
        )
        json.dumps(result.to_dict())

    def test_default_manifest_is_unavailable_for_missing_mask_kernel(self):
        controller = AttentionController(self.registry)
        result = controller.route()

        self.assertEqual(result.status, ATTENTION_STATUS_UNAVAILABLE)
        self.assertFalse(result.available)
        self.assertEqual(result.reason, ATTENTION_REASON_MASK_UNAVAILABLE)
        self.assertIsNone(result.plan)
        self.assertIsNone(result.plan_digest)
        self.assertEqual(result.step_count, len(ATTENTION_STAGES))
        self.assertEqual(
            result.kernel_ids,
            tuple(DEFAULT_STAGE_KERNELS[stage] for stage in ATTENTION_STAGES),
        )
        with self.assertRaises(AttentionUnavailableError) as caught:
            result.require_plan()
        self.assertEqual(caught.exception.reason, ATTENTION_REASON_MASK_UNAVAILABLE)
        self.assertEqual(
            controller.availability()["status"], ATTENTION_STATUS_UNAVAILABLE
        )

    def test_missing_softmax_kernel_is_typed_unavailable(self):
        registry = _registry(omit=("softmax",))
        result = AttentionController(registry).route()

        self.assertEqual(result.status, ATTENTION_STATUS_UNAVAILABLE)
        self.assertEqual(result.reason, ATTENTION_REASON_SOFTMAX_UNAVAILABLE)
        self.assertIsNone(result.plan)
        self.assertIsNone(result.plan_digest)
        self.assertIn(DEFAULT_STAGE_KERNELS["softmax"], result.kernel_ids)
        with self.assertRaises(AttentionUnavailableError) as caught:
            result.require_plan()
        self.assertEqual(
            caught.exception.reason, ATTENTION_REASON_SOFTMAX_UNAVAILABLE
        )

    def test_missing_mask_or_weighted_sum_kernel_is_typed_unavailable(self):
        cases = (
            ("mask", ATTENTION_REASON_MASK_UNAVAILABLE),
            ("weighted_sum", ATTENTION_REASON_WEIGHTED_SUM_UNAVAILABLE),
        )
        for stage, reason in cases:
            with self.subTest(stage=stage):
                registry = _registry(omit=(stage,))
                result = AttentionController(registry).route()
                self.assertEqual(result.status, ATTENTION_STATUS_UNAVAILABLE)
                self.assertEqual(result.reason, reason)
                self.assertIsNone(result.plan)
                self.assertIsNone(result.plan_digest)

    def test_non_ci_critical_kernel_is_typed_unavailable_not_host_fallback(self):
        registry = _registry(overrides={"softmax": {"ci_verified": False}})
        result = AttentionController(registry).route()

        self.assertEqual(result.status, ATTENTION_STATUS_UNAVAILABLE)
        self.assertEqual(result.reason, ATTENTION_REASON_SOFTMAX_UNAVAILABLE)
        self.assertIsNone(result.plan)
        self.assertIsNone(result.plan_digest)

    def test_unknown_noncritical_kernel_and_stage_are_rejected(self):
        controller = AttentionController(
            _registry(), {"qk_dot": "mth.not.registered.dot.f32"}
        )
        with self.assertRaises(AttentionKernelError) as caught:
            controller.route()
        self.assertEqual(caught.exception.reason, ATTENTION_REASON_UNKNOWN_KERNEL)
        self.assertIn("mth.not.registered.dot.f32", str(caught.exception))

        controller = AttentionController(
            _registry(), {"head_concat": "mth.not.registered.concat.f32"}
        )
        with self.assertRaises(AttentionKernelError) as caught:
            controller.route()
        self.assertEqual(caught.exception.reason, ATTENTION_REASON_UNKNOWN_KERNEL)

        with self.assertRaises(AttentionConfigError):
            AttentionController(_registry(), {"project": "mth.vector.dot256.f32"})
        with self.assertRaises(AttentionConfigError):
            AttentionController(_registry(), {"qk_dot": {"kernel_id": ""}})

    def test_non_native_and_non_ci_noncritical_kernels_are_rejected(self):
        controller = AttentionController(
            _registry(overrides={"qk_dot": {"status": "source_written",
                                            "ci_verified": False}})
        )
        with self.assertRaises(AttentionKernelError) as caught:
            controller.route()
        self.assertEqual(
            caught.exception.reason, ATTENTION_REASON_KERNEL_NOT_NATIVE_VERIFIED
        )

        controller = AttentionController(
            _registry(overrides={"qk_dot": {"ci_verified": False}})
        )
        with self.assertRaises(AttentionKernelError) as caught:
            controller.route()
        self.assertEqual(
            caught.exception.reason, ATTENTION_REASON_KERNEL_NOT_CI_VERIFIED
        )

    def test_workspace_bounds_are_enforced(self):
        registry = _registry(workspace_words=4)
        controller = AttentionController(registry)

        with self.assertRaises(AttentionWorkspaceError) as caught:
            controller.route(workspace_words=0)
        self.assertEqual(caught.exception.reason, ATTENTION_REASON_WORKSPACE)

        bounded = AttentionController(registry, max_workspace_words=8)
        with self.assertRaises(AttentionWorkspaceError) as caught:
            bounded.route()
        self.assertEqual(caught.exception.reason, ATTENTION_REASON_WORKSPACE)

        planned = controller.route(workspace_words=64)
        self.assertEqual(planned.status, ATTENTION_STATUS_PLANNED)
        self.assertEqual(planned.plan.workspace_words, 64)

    def test_step_limit_is_enforced(self):
        registry = _registry()
        controller = AttentionController(registry, max_steps=3)
        with self.assertRaises(AttentionStepLimitError) as caught:
            controller.route()
        self.assertEqual(caught.exception.reason, ATTENTION_REASON_STEP_LIMIT)

        with self.assertRaises(AttentionConfigError):
            AttentionController(registry, max_steps=0)

    def test_mask_policy_validation_and_none_policy(self):
        controller = AttentionController(_registry())

        for invalid in ("triangular", "causal+padding", "", 7, True):
            with self.subTest(invalid=invalid):
                with self.assertRaises(AttentionMaskError) as caught:
                    controller.route(mask_policy=invalid)
                self.assertEqual(
                    caught.exception.reason,
                    ATTENTION_REASON_INVALID_MASK_POLICY,
                )

        none = controller.route(mask_policy="none")
        self.assertEqual(none.status, ATTENTION_STATUS_PLANNED)
        self.assertEqual(none.mask_policy, "none")
        self.assertNotIn("mask", none.stages)
        self.assertEqual(none.step_count, 6)
        self.assertEqual(
            none.plan.steps[2].inputs,
            ("f32[256].attention.qk.scaled",),
        )
        self.assertNotIn(
            "f32[256].attention.qk.masked.none",
            tuple(
                name
                for step in none.plan.steps
                for name in (*step.inputs, *step.outputs)
            ),
        )

        causal = controller.route(mask_policy="CAUSAL")
        padding = controller.route(mask_policy="padding")
        combined = controller.route(mask_policy="causal_padding")
        self.assertEqual(causal.mask_policy, "causal")
        self.assertEqual(
            causal.plan.steps[2].outputs,
            ("f32[256].attention.qk.masked.causal",),
        )
        self.assertEqual(
            padding.plan.steps[2].outputs,
            ("f32[256].attention.qk.masked.padding",),
        )
        self.assertEqual(
            combined.plan.steps[2].outputs,
            ("f32[256].attention.qk.masked.causal.padding",),
        )
        self.assertNotEqual(causal.plan_digest, padding.plan_digest)
        self.assertNotEqual(causal.plan_digest, combined.plan_digest)
        self.assertEqual(
            tuple(ATTENTION_MASK_POLICIES),
            ("none", "causal", "padding", "causal_padding"),
        )
        self.assertEqual(
            ATTENTION_CRITICAL_STAGES, ("mask", "softmax", "weighted_sum")
        )

    def test_plan_digest_and_request_bounds_are_deterministic(self):
        registry = _registry()
        first = AttentionController(registry).route()
        second = AttentionController(registry).route()
        self.assertEqual(first.plan_digest, second.plan_digest)
        self.assertEqual(
            json.dumps(first.to_dict(), sort_keys=True),
            json.dumps(second.to_dict(), sort_keys=True),
        )

        renamed = AttentionController(registry).route(
            plan_id="attention.attend.alt"
        )
        self.assertNotEqual(first.plan_digest, renamed.plan_digest)

        bounded = AttentionController(registry).route(fuel=100, cancel_after=25)
        self.assertEqual(bounded.plan.fuel, 100)
        self.assertEqual(bounded.plan.cancel_after, 25)
        self.assertEqual(bounded.to_dict()["plan"]["fuel"], 100)
        self.assertEqual(bounded.to_dict()["plan"]["cancel_after"], 25)
        self.assertEqual(bounded.plan_digest, plan_digest(bounded.plan))


class AttentionControllerBoundaryTests(unittest.TestCase):
    def test_no_host_math_imports_or_execution_bypass(self):
        source = inspect.getsource(attention_controller)
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

        controller = AttentionController(MthRegistry.load(MANIFEST))
        for name in ("execute", "dispatch", "submit", "run", "apply"):
            self.assertFalse(hasattr(controller, name))
        for name in ("execute", "dispatch", "submit"):
            self.assertFalse(hasattr(attention_controller, name))


if __name__ == "__main__":
    unittest.main()
