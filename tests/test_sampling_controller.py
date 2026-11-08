from __future__ import annotations

import ast
import inspect
import json
import unittest
from pathlib import Path

from runner_riddle import sampling_controller
from runner_riddle.sampling_controller import (
    DEFAULT_PENALTY_POLICY,
    DEFAULT_SAMPLING_MODE,
    DEFAULT_STAGE_KERNELS,
    PENALTY_KERNELS,
    SAMPLING_MAX_SEED,
    SAMPLING_MODES,
    SAMPLING_PENALTY_POLICIES,
    SAMPLING_REASON_GREEDY_TIEBREAK_UNAVAILABLE,
    SAMPLING_REASON_INVALID_MODE,
    SAMPLING_REASON_INVALID_PENALTY_POLICY,
    SAMPLING_REASON_INVALID_REQUEST,
    SAMPLING_REASON_LOGIT_SCALE_UNAVAILABLE,
    SAMPLING_REASON_NORMALIZE_UNAVAILABLE,
    SAMPLING_REASON_PENALTY_UNAVAILABLE,
    SAMPLING_REASON_SAMPLE_UNAVAILABLE,
    SAMPLING_REASON_STEP_LIMIT,
    SAMPLING_REASON_TEMPERATURE_UNAVAILABLE,
    SAMPLING_REASON_TOP_K_UNAVAILABLE,
    SAMPLING_REASON_TOP_P_UNAVAILABLE,
    SAMPLING_REASON_UNKNOWN_KERNEL,
    SAMPLING_REASON_WORKSPACE,
    SAMPLING_STAGES,
    SAMPLING_STATUS_PLANNED,
    SAMPLING_STATUS_UNAVAILABLE,
    STAGE_KERNEL_FAMILIES,
    SamplingConfigError,
    SamplingController,
    SamplingKernelError,
    SamplingModeError,
    SamplingPenaltyError,
    SamplingRequestError,
    SamplingStepLimitError,
    SamplingUnavailableError,
    SamplingWorkspaceError,
    plan_digest,
)
from runner_riddle.mth_registry import MthKernelDescriptor, MthRegistry

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "spec" / "wave-capabilities.json"

_SAMPLE_STAGES = (
    "logit_scale",
    "temperature",
    "top_k",
    "top_p",
    "normalize",
    "sample",
)

_STAGE_UNAVAILABLE_REASONS = {
    "logit_scale": SAMPLING_REASON_LOGIT_SCALE_UNAVAILABLE,
    "temperature": SAMPLING_REASON_TEMPERATURE_UNAVAILABLE,
    "penalty": SAMPLING_REASON_PENALTY_UNAVAILABLE,
    "top_k": SAMPLING_REASON_TOP_K_UNAVAILABLE,
    "top_p": SAMPLING_REASON_TOP_P_UNAVAILABLE,
    "normalize": SAMPLING_REASON_NORMALIZE_UNAVAILABLE,
    "sample": SAMPLING_REASON_SAMPLE_UNAVAILABLE,
    "greedy_tiebreak": SAMPLING_REASON_GREEDY_TIEBREAK_UNAVAILABLE,
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
    for stage in SAMPLING_STAGES:
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


class SamplingControllerPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.real_registry = MthRegistry.load(MANIFEST)

    def test_available_sample_route_composes_explicit_native_stage_plan(self):
        registry = _registry(workspace_words=2)
        controller = SamplingController(registry)
        result = controller.route()

        self.assertEqual(result.status, SAMPLING_STATUS_PLANNED)
        self.assertTrue(result.available)
        self.assertEqual(result.mode, DEFAULT_SAMPLING_MODE)
        self.assertEqual(result.penalty_policy, DEFAULT_PENALTY_POLICY)
        self.assertEqual(result.stages, _SAMPLE_STAGES)
        self.assertEqual(
            result.kernel_ids,
            tuple(DEFAULT_STAGE_KERNELS[stage] for stage in _SAMPLE_STAGES),
        )
        self.assertEqual(result.step_count, len(_SAMPLE_STAGES))
        self.assertEqual(result.workspace_words, 12)
        self.assertTrue(result.deterministic)
        self.assertIsNone(result.seed)
        self.assertRegex(result.plan_digest, r"^[0-9a-f]{64}$")

        plan = result.require_plan()
        self.assertIs(result.plan, plan)
        self.assertIs(registry.validate_plan(plan), plan)
        self.assertEqual(result.plan_digest, plan_digest(plan))
        self.assertEqual(
            [step.name for step in plan.steps],
            [
                "sampling.logit-scale",
                "sampling.temperature",
                "sampling.top-k",
                "sampling.top-p",
                "sampling.normalize",
                "sampling.sample",
            ],
        )
        for previous, step in zip(plan.steps, plan.steps[1:]):
            self.assertEqual(step.depends_on, (previous.name,))
        self.assertEqual(
            plan.steps[0].inputs,
            ("f32[256].sampling.logits",),
        )
        self.assertEqual(
            plan.steps[-1].inputs,
            (
                "f32[256].sampling.probabilities",
                "u64.sampling.seed",
            ),
        )
        self.assertEqual(plan.steps[-1].outputs, ("u32.sampling.token",))
        self.assertEqual(plan.outputs[-1], "u32.sampling.token")
        json.dumps(result.to_dict())

    def test_penalty_policy_adds_stage_and_greedy_mode_uses_tiebreak(self):
        registry = _registry()
        controller = SamplingController(registry)

        baseline = controller.route()
        repetition = controller.route(penalty_policy="REPETITION")
        frequency = controller.route(penalty_policy="frequency")

        self.assertNotIn("penalty", baseline.stages)
        self.assertIn("penalty", repetition.stages)
        self.assertIn("penalty", frequency.stages)
        self.assertEqual(repetition.step_count, 7)
        self.assertEqual(
            repetition.plan.steps[2].kernel_id,
            PENALTY_KERNELS["repetition"],
        )
        self.assertEqual(
            frequency.plan.steps[2].kernel_id,
            PENALTY_KERNELS["frequency"],
        )
        self.assertEqual(
            repetition.plan.steps[2].inputs[1],
            "u32[256].sampling.context.tokens",
        )
        self.assertEqual(
            repetition.plan.steps[2].outputs,
            ("f32[256].sampling.logits.penalized.repetition",),
        )
        self.assertEqual(
            frequency.plan.steps[2].outputs,
            ("f32[256].sampling.logits.penalized.frequency",),
        )
        self.assertNotEqual(baseline.plan_digest, repetition.plan_digest)
        self.assertNotEqual(repetition.plan_digest, frequency.plan_digest)

        greedy = controller.route(mode="GREEDY")
        self.assertEqual(greedy.status, SAMPLING_STATUS_PLANNED)
        self.assertEqual(greedy.mode, "greedy")
        self.assertEqual(
            greedy.stages,
            ("logit_scale", "temperature", "greedy_tiebreak"),
        )
        self.assertEqual(
            greedy.kernel_ids[-1], DEFAULT_STAGE_KERNELS["greedy_tiebreak"]
        )
        self.assertNotIn("sample", greedy.stages)
        self.assertNotIn("normalize", greedy.stages)
        self.assertEqual(
            greedy.plan.steps[-1].outputs,
            ("u32.sampling.token.greedy",),
        )
        self.assertNotEqual(baseline.plan_digest, greedy.plan_digest)

        penalised_greedy = controller.route(
            mode="greedy", penalty_policy="repetition"
        )
        self.assertEqual(penalised_greedy.step_count, 4)
        self.assertIn("penalty", penalised_greedy.stages)

        with self.assertRaises(SamplingRequestError):
            controller.route(mode="greedy", seed=7)

    def test_default_manifest_is_typed_unavailable_for_missing_kernels(self):
        controller = SamplingController(self.real_registry)
        result = controller.route()

        self.assertEqual(result.status, SAMPLING_STATUS_UNAVAILABLE)
        self.assertFalse(result.available)
        self.assertEqual(result.reason, SAMPLING_REASON_LOGIT_SCALE_UNAVAILABLE)
        self.assertIsNone(result.plan)
        self.assertIsNone(result.plan_digest)
        self.assertEqual(result.step_count, len(_SAMPLE_STAGES))
        self.assertEqual(
            result.kernel_ids,
            tuple(DEFAULT_STAGE_KERNELS[stage] for stage in _SAMPLE_STAGES),
        )
        with self.assertRaises(SamplingUnavailableError) as caught:
            result.require_plan()
        self.assertEqual(
            caught.exception.reason, SAMPLING_REASON_LOGIT_SCALE_UNAVAILABLE
        )
        self.assertEqual(
            controller.availability()["status"], SAMPLING_STATUS_UNAVAILABLE
        )

    def test_missing_each_stage_kernel_is_typed_unavailable(self):
        for stage in SAMPLING_STAGES:
            with self.subTest(stage=stage):
                registry = _registry(omit=(stage,))
                controller = SamplingController(registry)
                if stage == "greedy_tiebreak":
                    result = controller.route(mode="greedy")
                elif stage == "penalty":
                    result = controller.route(penalty_policy="repetition")
                else:
                    result = controller.route()
                self.assertEqual(result.status, SAMPLING_STATUS_UNAVAILABLE)
                self.assertEqual(
                    result.reason, _STAGE_UNAVAILABLE_REASONS[stage]
                )
                self.assertIsNone(result.plan)
                self.assertIsNone(result.plan_digest)
                with self.assertRaises(SamplingUnavailableError):
                    result.require_plan()

    def test_non_native_and_non_ci_default_kernels_are_unavailable(self):
        non_native = _registry(
            overrides={
                DEFAULT_STAGE_KERNELS["top_k"]: {
                    "status": "source_written",
                    "ci_verified": False,
                },
            }
        )
        result = SamplingController(non_native).route()
        self.assertEqual(result.status, SAMPLING_STATUS_UNAVAILABLE)
        self.assertEqual(result.reason, SAMPLING_REASON_TOP_K_UNAVAILABLE)
        self.assertIn("not 'native_verified'", result.detail)
        self.assertIsNone(result.plan)

        non_ci = _registry(
            overrides={
                DEFAULT_STAGE_KERNELS["greedy_tiebreak"]: {
                    "ci_verified": False,
                },
            }
        )
        result = SamplingController(non_ci).route(mode="greedy")
        self.assertEqual(result.status, SAMPLING_STATUS_UNAVAILABLE)
        self.assertEqual(
            result.reason, SAMPLING_REASON_GREEDY_TIEBREAK_UNAVAILABLE
        )
        self.assertIn("not CI-verified", result.detail)
        self.assertIsNone(result.plan)

        penalty_non_native = _registry(
            overrides={
                PENALTY_KERNELS["frequency"]: {"status": "source_written"},
            }
        )
        result = SamplingController(penalty_non_native).route(
            penalty_policy="frequency"
        )
        self.assertEqual(result.status, SAMPLING_STATUS_UNAVAILABLE)
        self.assertEqual(result.reason, SAMPLING_REASON_PENALTY_UNAVAILABLE)

    def test_unknown_override_kernel_and_stage_are_rejected(self):
        controller = SamplingController(
            _registry(), {"sample": "mth.not.registered.sample.f32"}
        )
        with self.assertRaises(SamplingKernelError) as caught:
            controller.route()
        self.assertEqual(caught.exception.reason, SAMPLING_REASON_UNKNOWN_KERNEL)
        self.assertIn("mth.not.registered.sample.f32", str(caught.exception))

        with self.assertRaises(SamplingKernelError) as caught:
            SamplingController(
                _registry(), {"top_k": "mth.sampling.unknown.topk.f32"}
            ).route()
        self.assertEqual(caught.exception.reason, SAMPLING_REASON_UNKNOWN_KERNEL)

        with self.assertRaises(SamplingConfigError):
            SamplingController(_registry(), {"beam": "mth.topk.256.f32"})
        with self.assertRaises(SamplingConfigError):
            SamplingController(_registry(), {"sample": {"kernel_id": ""}})
        with self.assertRaises(SamplingConfigError):
            SamplingController(
                _registry(),
                {"sample": {"kernel_id": "mth.sampling.categorical.seeded.f32",
                            "bogus": 1}},
            )
        with self.assertRaises(SamplingConfigError):
            SamplingController(_registry(), {1: "mth.topk.256.f32"})

    def test_workspace_bounds_are_enforced(self):
        registry = _registry(workspace_words=4)
        controller = SamplingController(registry)

        with self.assertRaises(SamplingWorkspaceError) as caught:
            controller.route(workspace_words=0)
        self.assertEqual(caught.exception.reason, SAMPLING_REASON_WORKSPACE)

        bounded = SamplingController(registry, max_workspace_words=8)
        with self.assertRaises(SamplingWorkspaceError) as caught:
            bounded.route()
        self.assertEqual(caught.exception.reason, SAMPLING_REASON_WORKSPACE)

        planned = controller.route(workspace_words=64)
        self.assertEqual(planned.status, SAMPLING_STATUS_PLANNED)
        self.assertEqual(planned.plan.workspace_words, 64)

        with self.assertRaises(SamplingConfigError):
            SamplingController(registry, max_workspace_words=-1)
        with self.assertRaises(SamplingRequestError):
            controller.route(workspace_words=True)

    def test_step_limit_is_enforced(self):
        registry = _registry()
        controller = SamplingController(registry, max_steps=5)
        with self.assertRaises(SamplingStepLimitError) as caught:
            controller.route()
        self.assertEqual(caught.exception.reason, SAMPLING_REASON_STEP_LIMIT)

        greedy = SamplingController(registry, max_steps=2)
        with self.assertRaises(SamplingStepLimitError):
            greedy.route(mode="greedy")

        for invalid in (0, -1, True):
            with self.subTest(invalid=invalid):
                with self.assertRaises(SamplingConfigError):
                    SamplingController(registry, max_steps=invalid)

    def test_mode_and_penalty_policy_validation(self):
        controller = SamplingController(_registry())

        for invalid in ("beam", "", 7, True):
            with self.subTest(mode=invalid):
                with self.assertRaises(SamplingModeError) as caught:
                    controller.route(mode=invalid)
                self.assertEqual(
                    caught.exception.reason, SAMPLING_REASON_INVALID_MODE
                )

        for invalid in ("presence", "", 3, False):
            with self.subTest(penalty_policy=invalid):
                with self.assertRaises(SamplingPenaltyError) as caught:
                    controller.route(penalty_policy=invalid)
                self.assertEqual(
                    caught.exception.reason,
                    SAMPLING_REASON_INVALID_PENALTY_POLICY,
                )

        with self.assertRaises(SamplingModeError):
            SamplingController(_registry(), sampling_mode="beam")
        with self.assertRaises(SamplingPenaltyError):
            SamplingController(_registry(), penalty_policy="presence")

        sample = controller.route(mode="SAMPLE")
        self.assertEqual(sample.mode, "sample")
        self.assertEqual(SAMPLING_MODES, ("sample", "greedy"))
        self.assertEqual(DEFAULT_SAMPLING_MODE, "sample")
        self.assertEqual(
            SAMPLING_PENALTY_POLICIES,
            ("none", "repetition", "frequency"),
        )
        self.assertEqual(DEFAULT_PENALTY_POLICY, "none")

    def test_plan_digest_seed_and_request_bounds_are_deterministic(self):
        registry = _registry()
        controller = SamplingController(registry)
        first = controller.route()
        second = controller.route()
        self.assertEqual(first.plan_digest, second.plan_digest)
        self.assertEqual(
            json.dumps(first.to_dict(), sort_keys=True),
            json.dumps(second.to_dict(), sort_keys=True),
        )

        renamed = SamplingController(registry).route(
            plan_id="sampling.generate.alt"
        )
        self.assertNotEqual(first.plan_digest, renamed.plan_digest)

        seeded = SamplingController(registry).route(seed=7)
        other_seed = SamplingController(registry).route(seed=8)
        self.assertEqual(seeded.seed, 7)
        self.assertIn(
            "u64.sampling.seed.7", seeded.plan.steps[-1].inputs
        )
        self.assertIn(
            "u64.sampling.seed.8", other_seed.plan.steps[-1].inputs
        )
        self.assertNotEqual(seeded.plan_digest, other_seed.plan_digest)
        self.assertNotEqual(first.plan_digest, seeded.plan_digest)

        for invalid in (-1, True, SAMPLING_MAX_SEED + 1):
            with self.subTest(seed=invalid):
                with self.assertRaises(SamplingRequestError) as caught:
                    controller.route(seed=invalid)
                self.assertEqual(
                    caught.exception.reason, SAMPLING_REASON_INVALID_REQUEST
                )

        bounded = SamplingController(registry).route(fuel=100, cancel_after=25)
        self.assertEqual(bounded.plan.fuel, 100)
        self.assertEqual(bounded.plan.cancel_after, 25)
        self.assertEqual(bounded.to_dict()["plan"]["fuel"], 100)
        self.assertEqual(bounded.to_dict()["plan"]["cancel_after"], 25)
        self.assertEqual(bounded.plan_digest, plan_digest(bounded.plan))

    def test_availability_reports_status_without_execution(self):
        available = SamplingController(_registry()).availability()
        self.assertEqual(available["status"], SAMPLING_STATUS_PLANNED)
        self.assertRegex(available["plan_digest"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            available["kernel_ids"],
            list(
                DEFAULT_STAGE_KERNELS[stage] for stage in _SAMPLE_STAGES
            ),
        )

        real = SamplingController(
            MthRegistry.load(MANIFEST)
        ).availability()
        self.assertEqual(real["status"], SAMPLING_STATUS_UNAVAILABLE)
        self.assertEqual(real["reason"], SAMPLING_REASON_LOGIT_SCALE_UNAVAILABLE)

        rejected = SamplingController(
            _registry(), {"sample": "mth.not.registered.sample.f32"}
        ).availability()
        self.assertEqual(rejected["status"], "REJECTED")
        self.assertEqual(rejected["reason"], SAMPLING_REASON_UNKNOWN_KERNEL)

        invalid = SamplingController(_registry()).availability(mode="beam")
        self.assertEqual(invalid["status"], "REJECTED")
        self.assertEqual(invalid["reason"], SAMPLING_REASON_INVALID_MODE)


class SamplingControllerBoundaryTests(unittest.TestCase):
    def test_no_host_math_imports_or_execution_bypass(self):
        source = inspect.getsource(sampling_controller)
        tree = ast.parse(source)
        forbidden_imports = {
            "math", "numpy", "scipy", "sympy", "subprocess", "ctypes",
            "mmap", "sqlite3", "socket", "random", "secrets", "statistics",
            "decimal", "fractions",
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

        controller = SamplingController(MthRegistry.load(MANIFEST))
        for name in ("execute", "dispatch", "submit", "run", "apply", "sample"):
            self.assertFalse(hasattr(controller, name))
        for name in ("execute", "dispatch", "submit"):
            self.assertFalse(hasattr(sampling_controller, name))


if __name__ == "__main__":
    unittest.main()
