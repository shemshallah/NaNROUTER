from __future__ import annotations

import ast
import inspect
import json
import unittest
from pathlib import Path

from runner_riddle import loss_controller
from runner_riddle.loss_controller import (
    DEFAULT_LOSS_KIND,
    DEFAULT_OPTIMIZER,
    DEFAULT_STAGE_KERNELS,
    LOSS_KINDS,
    LOSS_KIND_KERNELS,
    LOSS_OPTIMIZERS,
    LOSS_REASON_CLIP_UNAVAILABLE,
    LOSS_REASON_GRADIENT_ACCUMULATE_UNAVAILABLE,
    LOSS_REASON_INVALID_LOSS_KIND,
    LOSS_REASON_INVALID_OPTIMIZER,
    LOSS_REASON_KERNEL_NOT_CI_VERIFIED,
    LOSS_REASON_KERNEL_NOT_NATIVE_VERIFIED,
    LOSS_REASON_LOSS_UNAVAILABLE,
    LOSS_REASON_MOVING_AVERAGE_UNAVAILABLE,
    LOSS_REASON_STEP_LIMIT,
    LOSS_REASON_UNKNOWN_KERNEL,
    LOSS_REASON_UPDATE_UNAVAILABLE,
    LOSS_REASON_WORKSPACE,
    LOSS_STAGES,
    LOSS_STATUS_PLANNED,
    LOSS_STATUS_UNAVAILABLE,
    OPTIMIZER_KERNELS,
    STAGE_KERNEL_FAMILIES,
    LossConfigError,
    LossKindError,
    LossKernelError,
    LossOptimizerController,
    LossOptimizerError,
    LossStepLimitError,
    LossUnavailableError,
    LossWorkspaceError,
    plan_digest,
)
from runner_riddle.mth_registry import MthKernelDescriptor, MthRegistry

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "spec" / "wave-capabilities.json"

_STAGE_UNAVAILABLE_REASONS = {
    "loss": LOSS_REASON_LOSS_UNAVAILABLE,
    "gradient_accumulate": LOSS_REASON_GRADIENT_ACCUMULATE_UNAVAILABLE,
    "clip": LOSS_REASON_CLIP_UNAVAILABLE,
    "moving_average": LOSS_REASON_MOVING_AVERAGE_UNAVAILABLE,
    "update": LOSS_REASON_UPDATE_UNAVAILABLE,
}


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
    for stage in LOSS_STAGES:
        if stage in omit:
            continue
        for kernel_id in STAGE_KERNEL_FAMILIES[stage]:
            options = overrides.get(kernel_id, {})
            descriptors.append(
                _descriptor(
                    kernel_id,
                    workspace_words=options.get(
                        "workspace_words", workspace_words
                    ),
                    status=options.get("status", "native_verified"),
                    ci_verified=options.get("ci_verified", True),
                )
            )
    return MthRegistry(descriptors)


class LossControllerPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.real_registry = MthRegistry.load(MANIFEST)

    def test_available_route_composes_explicit_native_stage_plan(self):
        registry = _registry(workspace_words=2)
        controller = LossOptimizerController(registry)
        result = controller.route()

        self.assertEqual(result.status, LOSS_STATUS_PLANNED)
        self.assertTrue(result.available)
        self.assertEqual(result.loss_kind, DEFAULT_LOSS_KIND)
        self.assertEqual(result.optimizer, DEFAULT_OPTIMIZER)
        self.assertEqual(result.stages, LOSS_STAGES)
        self.assertEqual(
            result.kernel_ids,
            tuple(DEFAULT_STAGE_KERNELS[stage] for stage in LOSS_STAGES),
        )
        self.assertEqual(result.step_count, len(LOSS_STAGES))
        self.assertEqual(result.workspace_words, 10)
        self.assertTrue(result.deterministic)
        self.assertRegex(result.plan_digest, r"^[0-9a-f]{64}$")

        plan = result.require_plan()
        self.assertIs(result.plan, plan)
        self.assertIs(registry.validate_plan(plan), plan)
        self.assertEqual(result.plan_digest, plan_digest(plan))
        self.assertEqual(
            [step.name for step in plan.steps],
            [
                "loss.compute",
                "loss.gradient-accumulate",
                "loss.clip",
                "loss.moving-average",
                "loss.update",
            ],
        )
        for previous, step in zip(plan.steps, plan.steps[1:]):
            self.assertEqual(step.depends_on, (previous.name,))
        self.assertEqual(
            plan.steps[0].inputs,
            (
                "f32[256].loss.logits",
                "u32[256].loss.targets",
            ),
        )
        self.assertEqual(
            plan.steps[0].outputs,
            (
                "f32[256].loss.cross_entropy.gradient",
                "f32.loss.cross_entropy.value",
            ),
        )
        self.assertEqual(
            plan.steps[1].inputs[0],
            "f32[256].loss.cross_entropy.gradient",
        )
        self.assertEqual(
            plan.steps[4].inputs,
            (
                "f32[256].optimizer.moving_average.updated",
                "f32[256].optimizer.adam.state",
                "f32[256].model.parameters",
            ),
        )
        self.assertEqual(
            plan.outputs[-1],
            "f32[256].model.parameters.adam.updated",
        )
        json.dumps(result.to_dict())

    def test_loss_kind_and_optimizer_select_declared_kernels(self):
        registry = _registry()
        controller = LossOptimizerController(registry)

        selected = controller.route(
            loss_kind="NLL", optimizer="MOMENTUM"
        )
        self.assertEqual(selected.status, LOSS_STATUS_PLANNED)
        self.assertEqual(selected.loss_kind, "nll")
        self.assertEqual(selected.optimizer, "momentum")
        self.assertEqual(
            selected.kernel_ids,
            (
                LOSS_KIND_KERNELS["nll"],
                DEFAULT_STAGE_KERNELS["gradient_accumulate"],
                DEFAULT_STAGE_KERNELS["clip"],
                DEFAULT_STAGE_KERNELS["moving_average"],
                OPTIMIZER_KERNELS["momentum"],
            ),
        )
        self.assertEqual(
            selected.plan.steps[0].outputs[0],
            "f32[256].loss.nll.gradient",
        )
        self.assertEqual(
            selected.plan.steps[4].outputs[0],
            "f32[256].model.parameters.momentum.updated",
        )
        self.assertEqual(
            controller.kernel_ids(loss_kind="nll", optimizer="momentum"),
            selected.kernel_ids,
        )

        default = controller.route()
        cross_entropy_nll = controller.route(loss_kind="nll")
        adam_momentum = controller.route(optimizer="momentum")
        self.assertNotEqual(default.plan_digest, cross_entropy_nll.plan_digest)
        self.assertNotEqual(default.plan_digest, adam_momentum.plan_digest)
        self.assertNotEqual(
            cross_entropy_nll.plan_digest, selected.plan_digest
        )
        self.assertEqual(tuple(LOSS_KINDS), ("cross_entropy", "nll"))
        self.assertEqual(LOSS_OPTIMIZERS, ("adam", "momentum"))

    def test_default_manifest_is_typed_unavailable_for_missing_loss_kernel(self):
        controller = LossOptimizerController(self.real_registry)
        result = controller.route()

        self.assertEqual(result.status, LOSS_STATUS_UNAVAILABLE)
        self.assertFalse(result.available)
        self.assertEqual(result.reason, LOSS_REASON_LOSS_UNAVAILABLE)
        self.assertIsNone(result.plan)
        self.assertIsNone(result.plan_digest)
        self.assertEqual(result.step_count, len(LOSS_STAGES))
        self.assertEqual(
            result.kernel_ids,
            tuple(DEFAULT_STAGE_KERNELS[stage] for stage in LOSS_STAGES),
        )
        self.assertIn(DEFAULT_STAGE_KERNELS["loss"], result.kernel_ids)
        with self.assertRaises(LossUnavailableError) as caught:
            result.require_plan()
        self.assertEqual(
            caught.exception.reason, LOSS_REASON_LOSS_UNAVAILABLE
        )
        self.assertEqual(
            controller.availability()["status"], LOSS_STATUS_UNAVAILABLE
        )

    def test_missing_each_stage_kernel_is_typed_unavailable(self):
        for stage in LOSS_STAGES:
            with self.subTest(stage=stage):
                registry = _registry(omit=(stage,))
                result = LossOptimizerController(registry).route()
                self.assertEqual(result.status, LOSS_STATUS_UNAVAILABLE)
                self.assertEqual(
                    result.reason, _STAGE_UNAVAILABLE_REASONS[stage]
                )
                self.assertIsNone(result.plan)
                self.assertIsNone(result.plan_digest)
                self.assertIn(
                    DEFAULT_STAGE_KERNELS[stage], result.kernel_ids
                )
                with self.assertRaises(LossUnavailableError):
                    result.require_plan()

    def test_unknown_override_kernel_and_stage_are_rejected(self):
        controller = LossOptimizerController(
            _registry(), {"loss": "mth.not.registered.loss.f32"}
        )
        with self.assertRaises(LossKernelError) as caught:
            controller.route()
        self.assertEqual(caught.exception.reason, LOSS_REASON_UNKNOWN_KERNEL)
        self.assertIn("mth.not.registered.loss.f32", str(caught.exception))

        with self.assertRaises(LossConfigError):
            LossOptimizerController(
                _registry(), {"projection": DEFAULT_STAGE_KERNELS["clip"]}
            )
        with self.assertRaises(LossConfigError):
            LossOptimizerController(_registry(), {"clip": {"kernel_id": ""}})
        with self.assertRaises(LossConfigError):
            LossOptimizerController(
                _registry(),
                {"clip": {"kernel_id": "mth.loss.nll.f32", "bogus": 1}},
            )

    def test_non_native_and_non_ci_kernels_are_rejected(self):
        non_native = _registry(
            overrides={
                LOSS_KIND_KERNELS["cross_entropy"]: {
                    "status": "source_written",
                    "ci_verified": False,
                },
            }
        )
        with self.assertRaises(LossKernelError) as caught:
            LossOptimizerController(non_native).route()
        self.assertEqual(
            caught.exception.reason,
            LOSS_REASON_KERNEL_NOT_NATIVE_VERIFIED,
        )

        non_ci = _registry(
            overrides={
                DEFAULT_STAGE_KERNELS["clip"]: {"ci_verified": False},
            }
        )
        with self.assertRaises(LossKernelError) as caught:
            LossOptimizerController(non_ci).route()
        self.assertEqual(
            caught.exception.reason, LOSS_REASON_KERNEL_NOT_CI_VERIFIED
        )

    def test_workspace_bounds_are_enforced(self):
        registry = _registry(workspace_words=4)
        controller = LossOptimizerController(registry)

        with self.assertRaises(LossWorkspaceError) as caught:
            controller.route(workspace_words=0)
        self.assertEqual(caught.exception.reason, LOSS_REASON_WORKSPACE)

        bounded = LossOptimizerController(registry, max_workspace_words=8)
        with self.assertRaises(LossWorkspaceError) as caught:
            bounded.route()
        self.assertEqual(caught.exception.reason, LOSS_REASON_WORKSPACE)

        planned = controller.route(workspace_words=64)
        self.assertEqual(planned.status, LOSS_STATUS_PLANNED)
        self.assertEqual(planned.plan.workspace_words, 64)

        with self.assertRaises(LossConfigError):
            LossOptimizerController(registry, max_workspace_words=-1)

    def test_step_limit_is_enforced(self):
        controller = LossOptimizerController(_registry(), max_steps=4)
        with self.assertRaises(LossStepLimitError) as caught:
            controller.route()
        self.assertEqual(caught.exception.reason, LOSS_REASON_STEP_LIMIT)

        for invalid in (0, -1, True):
            with self.subTest(invalid=invalid):
                with self.assertRaises(LossConfigError):
                    LossOptimizerController(_registry(), max_steps=invalid)

    def test_loss_kind_and_optimizer_validation(self):
        controller = LossOptimizerController(_registry())

        for invalid in ("mse", "", 7, True):
            with self.subTest(loss_kind=invalid):
                with self.assertRaises(LossKindError) as caught:
                    controller.route(loss_kind=invalid)
                self.assertEqual(
                    caught.exception.reason, LOSS_REASON_INVALID_LOSS_KIND
                )

        for invalid in ("rmsprop", "", 3, False):
            with self.subTest(optimizer=invalid):
                with self.assertRaises(LossOptimizerError) as caught:
                    controller.route(optimizer=invalid)
                self.assertEqual(
                    caught.exception.reason, LOSS_REASON_INVALID_OPTIMIZER
                )

        with self.assertRaises(LossKindError):
            LossOptimizerController(_registry(), loss_kind="mse")
        with self.assertRaises(LossOptimizerError):
            LossOptimizerController(_registry(), optimizer="rmsprop")

    def test_plan_digest_and_request_bounds_are_deterministic(self):
        registry = _registry()
        first = LossOptimizerController(registry).route()
        second = LossOptimizerController(registry).route()
        self.assertEqual(first.plan_digest, second.plan_digest)
        self.assertEqual(
            json.dumps(first.to_dict(), sort_keys=True),
            json.dumps(second.to_dict(), sort_keys=True),
        )

        renamed = LossOptimizerController(registry).route(
            plan_id="loss.optimize.alt"
        )
        self.assertNotEqual(first.plan_digest, renamed.plan_digest)

        bounded = LossOptimizerController(registry).route(
            fuel=100, cancel_after=25
        )
        self.assertEqual(bounded.plan.fuel, 100)
        self.assertEqual(bounded.plan.cancel_after, 25)
        self.assertEqual(bounded.to_dict()["plan"]["fuel"], 100)
        self.assertEqual(bounded.to_dict()["plan"]["cancel_after"], 25)
        self.assertEqual(bounded.plan_digest, plan_digest(bounded.plan))

    def test_availability_reports_status_without_execution(self):
        available = LossOptimizerController(_registry()).availability()
        self.assertEqual(available["status"], LOSS_STATUS_PLANNED)
        self.assertRegex(available["plan_digest"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            available["kernel_ids"],
            list(DEFAULT_STAGE_KERNELS[stage] for stage in LOSS_STAGES),
        )

        real = LossOptimizerController(self.real_registry).availability()
        self.assertEqual(real["status"], LOSS_STATUS_UNAVAILABLE)
        self.assertEqual(real["reason"], LOSS_REASON_LOSS_UNAVAILABLE)

        rejected = LossOptimizerController(
            _registry(), {"loss": "mth.not.registered.loss.f32"}
        ).availability()
        self.assertEqual(rejected["status"], "REJECTED")
        self.assertEqual(rejected["reason"], LOSS_REASON_UNKNOWN_KERNEL)

        invalid = LossOptimizerController(_registry()).availability(
            loss_kind="mse"
        )
        self.assertEqual(invalid["status"], "REJECTED")
        self.assertEqual(invalid["reason"], LOSS_REASON_INVALID_LOSS_KIND)


class LossControllerBoundaryTests(unittest.TestCase):
    def test_no_host_math_imports_or_execution_bypass(self):
        source = inspect.getsource(loss_controller)
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

        controller = LossOptimizerController(
            MthRegistry.load(MANIFEST)
        )
        for name in ("execute", "dispatch", "submit", "run", "apply"):
            self.assertFalse(hasattr(controller, name))
        for name in ("execute", "dispatch", "submit"):
            self.assertFalse(hasattr(loss_controller, name))


if __name__ == "__main__":
    unittest.main()
