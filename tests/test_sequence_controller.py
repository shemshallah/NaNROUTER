from __future__ import annotations

import ast
import inspect
import json
import unittest
from pathlib import Path

from runner_riddle import sequence_controller
from runner_riddle.sequence_controller import (
    DEFAULT_MASK_POLICY,
    DEFAULT_NGRAM_ORDER,
    DEFAULT_STAGE_KERNELS,
    SEQUENCE_BASE_STAGES,
    SEQUENCE_MAX_NGRAM_ORDER,
    SEQUENCE_MAX_WINDOW,
    SEQUENCE_MASK_POLICIES,
    SEQUENCE_OPTIONAL_STAGES,
    SEQUENCE_REASON_EMBEDDING_GATHER_UNAVAILABLE,
    SEQUENCE_REASON_HEAD_CONCAT_UNAVAILABLE,
    SEQUENCE_REASON_INVALID_MASK_POLICY,
    SEQUENCE_REASON_KERNEL_NOT_CI_VERIFIED,
    SEQUENCE_REASON_KERNEL_NOT_NATIVE_VERIFIED,
    SEQUENCE_REASON_MASK_APPLY_UNAVAILABLE,
    SEQUENCE_REASON_NGRAM_BUILD_UNAVAILABLE,
    SEQUENCE_REASON_POSITION_ADD_UNAVAILABLE,
    SEQUENCE_REASON_SLICE_WINDOW_UNAVAILABLE,
    SEQUENCE_REASON_STEP_LIMIT,
    SEQUENCE_REASON_UNKNOWN_KERNEL,
    SEQUENCE_REASON_WORKSPACE,
    SEQUENCE_STAGES,
    SEQUENCE_STATUS_PLANNED,
    SEQUENCE_STATUS_UNAVAILABLE,
    STAGE_KERNEL_FAMILIES,
    SequenceConfigError,
    SequenceController,
    SequenceKernelError,
    SequenceMaskError,
    SequenceRequestError,
    SequenceStepLimitError,
    SequenceUnavailableError,
    SequenceWorkspaceError,
    plan_digest,
)
from runner_riddle.mth_registry import MthKernelDescriptor, MthRegistry

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "spec" / "wave-capabilities.json"

_STAGE_UNAVAILABLE_REASONS = {
    "embedding_gather": SEQUENCE_REASON_EMBEDDING_GATHER_UNAVAILABLE,
    "position_add": SEQUENCE_REASON_POSITION_ADD_UNAVAILABLE,
    "slice_window": SEQUENCE_REASON_SLICE_WINDOW_UNAVAILABLE,
    "mask_apply": SEQUENCE_REASON_MASK_APPLY_UNAVAILABLE,
    "ngram_build": SEQUENCE_REASON_NGRAM_BUILD_UNAVAILABLE,
    "head_concat": SEQUENCE_REASON_HEAD_CONCAT_UNAVAILABLE,
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
    for stage in SEQUENCE_STAGES:
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


class SequenceControllerPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.real_registry = MthRegistry.load(MANIFEST)

    def test_available_route_composes_explicit_native_stage_plan(self):
        registry = _registry(workspace_words=2)
        controller = SequenceController(registry)
        result = controller.route()

        self.assertEqual(result.status, SEQUENCE_STATUS_PLANNED)
        self.assertTrue(result.available)
        self.assertEqual(result.mask_policy, DEFAULT_MASK_POLICY)
        self.assertFalse(result.include_head_concat)
        self.assertIsNone(result.window)
        self.assertEqual(result.ngram_order, DEFAULT_NGRAM_ORDER)
        self.assertEqual(result.stages, SEQUENCE_BASE_STAGES)
        self.assertEqual(
            result.kernel_ids,
            tuple(DEFAULT_STAGE_KERNELS[stage] for stage in SEQUENCE_BASE_STAGES),
        )
        self.assertEqual(result.step_count, len(SEQUENCE_BASE_STAGES))
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
                "sequence.embedding-gather",
                "sequence.position-add",
                "sequence.slice-window",
                "sequence.mask-apply",
                "sequence.ngram-build",
            ],
        )
        for previous, step in zip(plan.steps, plan.steps[1:]):
            self.assertEqual(step.depends_on, (previous.name,))
        self.assertEqual(
            plan.steps[0].inputs,
            (
                "u32[256].sequence.tokens",
                "f32[256].sequence.embedding.table",
            ),
        )
        self.assertEqual(
            plan.steps[1].inputs,
            (
                "f32[256].sequence.embedded",
                "u32[256].sequence.positions",
            ),
        )
        self.assertEqual(
            plan.steps[2].outputs,
            ("f32[256].sequence.window.unbounded",),
        )
        self.assertEqual(
            plan.steps[3].outputs,
            ("f32[256].sequence.masked.causal",),
        )
        self.assertEqual(
            plan.steps[4].outputs,
            ("u32[256].sequence.ngram.2",),
        )
        self.assertEqual(plan.outputs[-1], "u32[256].sequence.ngram.2")
        json.dumps(result.to_dict())

    def test_head_concat_is_optional_and_changes_the_plan(self):
        controller = SequenceController(_registry())
        base = controller.route()
        with_head = controller.route(include_head_concat=True)

        self.assertEqual(base.status, SEQUENCE_STATUS_PLANNED)
        self.assertEqual(with_head.status, SEQUENCE_STATUS_PLANNED)
        self.assertEqual(with_head.stages, SEQUENCE_STAGES)
        self.assertEqual(with_head.step_count, len(SEQUENCE_STAGES))
        self.assertEqual(
            with_head.kernel_ids[-1], DEFAULT_STAGE_KERNELS["head_concat"]
        )
        self.assertEqual(
            with_head.plan.steps[-1].outputs,
            ("f32[256].sequence.heads.concat",),
        )
        self.assertEqual(
            with_head.plan.steps[-1].inputs,
            (
                "u32[256].sequence.ngram.2",
                "f32[256].sequence.heads.context",
            ),
        )
        self.assertNotEqual(base.plan_digest, with_head.plan_digest)
        self.assertEqual(
            controller.kernel_ids(include_head_concat=True),
            with_head.kernel_ids,
        )
        self.assertEqual(SEQUENCE_OPTIONAL_STAGES, ("head_concat",))

        for invalid in ("yes", 1, None):
            with self.subTest(include_head_concat=invalid):
                with self.assertRaises(SequenceRequestError):
                    controller.route(include_head_concat=invalid)
        with self.assertRaises(SequenceConfigError):
            SequenceController(_registry(), include_head_concat="yes")

    def test_default_manifest_is_typed_unavailable_for_missing_embedding(self):
        controller = SequenceController(self.real_registry)
        result = controller.route()

        self.assertEqual(result.status, SEQUENCE_STATUS_UNAVAILABLE)
        self.assertFalse(result.available)
        self.assertEqual(
            result.reason, SEQUENCE_REASON_EMBEDDING_GATHER_UNAVAILABLE
        )
        self.assertIsNone(result.plan)
        self.assertIsNone(result.plan_digest)
        self.assertEqual(result.step_count, len(SEQUENCE_BASE_STAGES))
        self.assertEqual(
            result.kernel_ids,
            tuple(DEFAULT_STAGE_KERNELS[stage] for stage in SEQUENCE_BASE_STAGES),
        )
        with self.assertRaises(SequenceUnavailableError) as caught:
            result.require_plan()
        self.assertEqual(
            caught.exception.reason,
            SEQUENCE_REASON_EMBEDDING_GATHER_UNAVAILABLE,
        )
        self.assertEqual(
            controller.availability()["status"], SEQUENCE_STATUS_UNAVAILABLE
        )

    def test_missing_each_stage_kernel_is_typed_unavailable(self):
        for stage in SEQUENCE_STAGES:
            with self.subTest(stage=stage):
                registry = _registry(omit=(stage,))
                controller = SequenceController(registry)
                if stage == "head_concat":
                    result = controller.route(include_head_concat=True)
                else:
                    result = controller.route()
                self.assertEqual(result.status, SEQUENCE_STATUS_UNAVAILABLE)
                self.assertEqual(
                    result.reason, _STAGE_UNAVAILABLE_REASONS[stage]
                )
                self.assertIsNone(result.plan)
                self.assertIsNone(result.plan_digest)
                with self.assertRaises(SequenceUnavailableError) as caught:
                    result.require_plan()
                self.assertEqual(
                    caught.exception.reason,
                    _STAGE_UNAVAILABLE_REASONS[stage],
                )

    def test_non_native_and_non_ci_declared_kernels_are_unavailable(self):
        non_native = _registry(
            overrides={
                DEFAULT_STAGE_KERNELS["embedding_gather"]: {
                    "status": "source_written",
                    "ci_verified": False,
                },
            }
        )
        result = SequenceController(non_native).route()
        self.assertEqual(result.status, SEQUENCE_STATUS_UNAVAILABLE)
        self.assertEqual(
            result.reason, SEQUENCE_REASON_EMBEDDING_GATHER_UNAVAILABLE
        )
        self.assertIn("not 'native_verified'", result.detail)
        self.assertIsNone(result.plan)

        non_ci = _registry(
            overrides={
                DEFAULT_STAGE_KERNELS["mask_apply"]: {"ci_verified": False},
            }
        )
        result = SequenceController(non_ci).route()
        self.assertEqual(result.status, SEQUENCE_STATUS_UNAVAILABLE)
        self.assertEqual(result.reason, SEQUENCE_REASON_MASK_APPLY_UNAVAILABLE)
        self.assertIn("not CI-verified", result.detail)
        self.assertIsNone(result.plan)

        non_native_head = _registry(
            overrides={
                DEFAULT_STAGE_KERNELS["head_concat"]: {
                    "status": "source_written",
                },
            }
        )
        result = SequenceController(non_native_head).route(
            include_head_concat=True
        )
        self.assertEqual(result.status, SEQUENCE_STATUS_UNAVAILABLE)
        self.assertEqual(
            result.reason, SEQUENCE_REASON_HEAD_CONCAT_UNAVAILABLE
        )

    def test_unknown_override_kernel_and_invalid_config_are_rejected(self):
        controller = SequenceController(
            _registry(), {"embedding_gather": "mth.not.registered.embed.f32"}
        )
        with self.assertRaises(SequenceKernelError) as caught:
            controller.route()
        self.assertEqual(caught.exception.reason, SEQUENCE_REASON_UNKNOWN_KERNEL)
        self.assertIn("mth.not.registered.embed.f32", str(caught.exception))

        with self.assertRaises(SequenceKernelError) as caught:
            SequenceController(
                _registry(),
                {"head_concat": "mth.not.registered.head.f32"},
            ).route(include_head_concat=True)
        self.assertEqual(caught.exception.reason, SEQUENCE_REASON_UNKNOWN_KERNEL)

        with self.assertRaises(SequenceConfigError):
            SequenceController(_registry(), {"beam": "mth.topk.256.f32"})
        with self.assertRaises(SequenceConfigError):
            SequenceController(_registry(), {"mask_apply": {"kernel_id": ""}})
        with self.assertRaises(SequenceConfigError):
            SequenceController(
                _registry(),
                {
                    "mask_apply": {
                        "kernel_id": DEFAULT_STAGE_KERNELS["mask_apply"],
                        "bogus": 1,
                    }
                },
            )
        with self.assertRaises(SequenceConfigError):
            SequenceController(_registry(), {1: "mth.topk.256.f32"})
        with self.assertRaises(SequenceConfigError):
            SequenceController(object())

    def test_workspace_bounds_are_enforced(self):
        registry = _registry(workspace_words=4)
        controller = SequenceController(registry)

        with self.assertRaises(SequenceWorkspaceError) as caught:
            controller.route(workspace_words=0)
        self.assertEqual(caught.exception.reason, SEQUENCE_REASON_WORKSPACE)

        bounded = SequenceController(registry, max_workspace_words=8)
        with self.assertRaises(SequenceWorkspaceError) as caught:
            bounded.route()
        self.assertEqual(caught.exception.reason, SEQUENCE_REASON_WORKSPACE)

        planned = controller.route(workspace_words=64)
        self.assertEqual(planned.status, SEQUENCE_STATUS_PLANNED)
        self.assertEqual(planned.plan.workspace_words, 64)

        with self.assertRaises(SequenceConfigError):
            SequenceController(registry, max_workspace_words=-1)
        with self.assertRaises(SequenceRequestError):
            controller.route(workspace_words=True)

    def test_step_limit_is_enforced(self):
        registry = _registry()
        controller = SequenceController(registry, max_steps=4)
        with self.assertRaises(SequenceStepLimitError) as caught:
            controller.route()
        self.assertEqual(caught.exception.reason, SEQUENCE_REASON_STEP_LIMIT)

        base_at_limit = SequenceController(registry, max_steps=5)
        self.assertEqual(
            base_at_limit.route().status, SEQUENCE_STATUS_PLANNED
        )
        with self.assertRaises(SequenceStepLimitError):
            base_at_limit.route(include_head_concat=True)

        head_at_limit = SequenceController(registry, max_steps=6)
        self.assertEqual(
            head_at_limit.route(include_head_concat=True).status,
            SEQUENCE_STATUS_PLANNED,
        )

        for invalid in (0, -1, True):
            with self.subTest(invalid=invalid):
                with self.assertRaises(SequenceConfigError):
                    SequenceController(registry, max_steps=invalid)

    def test_window_ngram_and_mask_bounds_are_validated(self):
        controller = SequenceController(_registry())

        for invalid in ("triangular", "", 7, True):
            with self.subTest(mask_policy=invalid):
                with self.assertRaises(SequenceMaskError) as caught:
                    controller.route(mask_policy=invalid)
                self.assertEqual(
                    caught.exception.reason,
                    SEQUENCE_REASON_INVALID_MASK_POLICY,
                )
        with self.assertRaises(SequenceMaskError):
            SequenceController(_registry(), mask_policy="triangular")

        for invalid in (0, -1, True, "4", SEQUENCE_MAX_WINDOW + 1):
            with self.subTest(window=invalid):
                with self.assertRaises(SequenceRequestError):
                    controller.route(window=invalid)
        with self.assertRaises(SequenceConfigError):
            SequenceController(_registry(), window=0)

        for invalid in (
            0, -1, True, "2", SEQUENCE_MAX_NGRAM_ORDER + 1,
        ):
            with self.subTest(ngram_order=invalid):
                with self.assertRaises(SequenceRequestError):
                    controller.route(ngram_order=invalid)
        with self.assertRaises(SequenceConfigError):
            SequenceController(_registry(), ngram_order=0)

    def test_mask_window_and_ngram_variants_have_distinct_digests(self):
        controller = SequenceController(_registry())
        causal = controller.route()
        padding = controller.route(mask_policy="PADDING")
        combined = controller.route(mask_policy="causal_padding")
        no_mask = controller.route(mask_policy="none")

        self.assertEqual(SEQUENCE_MASK_POLICIES,
                         ("none", "causal", "padding", "causal_padding"))
        self.assertEqual(padding.mask_policy, "padding")
        self.assertEqual(
            causal.plan.steps[3].outputs,
            ("f32[256].sequence.masked.causal",),
        )
        self.assertEqual(
            padding.plan.steps[3].outputs,
            ("f32[256].sequence.masked.padding",),
        )
        self.assertEqual(
            combined.plan.steps[3].outputs,
            ("f32[256].sequence.masked.causal.padding",),
        )
        self.assertEqual(
            no_mask.plan.steps[3].outputs,
            ("f32[256].sequence.masked.none",),
        )
        self.assertEqual(
            len({
                causal.plan_digest,
                padding.plan_digest,
                combined.plan_digest,
                no_mask.plan_digest,
            }),
            4,
        )

        window_64 = controller.route(window=64)
        window_128 = controller.route(window=128)
        self.assertEqual(
            window_64.plan.steps[2].outputs,
            ("f32[256].sequence.window.64",),
        )
        self.assertEqual(
            window_128.plan.steps[2].outputs,
            ("f32[256].sequence.window.128",),
        )
        self.assertNotEqual(window_64.plan_digest, window_128.plan_digest)

        order_3 = controller.route(ngram_order=3)
        self.assertEqual(
            order_3.plan.steps[4].outputs,
            ("u32[256].sequence.ngram.3",),
        )
        self.assertNotEqual(causal.plan_digest, order_3.plan_digest)

        configured = SequenceController(
            _registry(), window=32, ngram_order=4, mask_policy="padding"
        ).route()
        self.assertEqual(
            configured.plan.steps[2].outputs,
            ("f32[256].sequence.window.32",),
        )
        self.assertEqual(
            configured.plan.steps[3].outputs,
            ("f32[256].sequence.masked.padding",),
        )
        self.assertEqual(
            configured.plan.steps[4].outputs,
            ("u32[256].sequence.ngram.4",),
        )

    def test_plan_digest_and_request_bounds_are_deterministic(self):
        registry = _registry()
        first = SequenceController(registry).route()
        second = SequenceController(registry).route()
        self.assertEqual(first.plan_digest, second.plan_digest)
        self.assertEqual(
            json.dumps(first.to_dict(), sort_keys=True),
            json.dumps(second.to_dict(), sort_keys=True),
        )

        renamed = SequenceController(registry).route(
            plan_id="sequence.compose.alt"
        )
        self.assertNotEqual(first.plan_digest, renamed.plan_digest)

        bounded = SequenceController(registry).route(
            fuel=100, cancel_after=25
        )
        self.assertEqual(bounded.plan.fuel, 100)
        self.assertEqual(bounded.plan.cancel_after, 25)
        self.assertEqual(bounded.to_dict()["plan"]["fuel"], 100)
        self.assertEqual(bounded.to_dict()["plan"]["cancel_after"], 25)
        self.assertEqual(bounded.plan_digest, plan_digest(bounded.plan))

        # Composition is an alias and still never executes the plan.
        composed = SequenceController(registry).compose(window=16)
        routed = SequenceController(registry).route(window=16)
        self.assertEqual(composed.plan_digest, routed.plan_digest)

    def test_availability_reports_status_without_execution(self):
        available = SequenceController(_registry()).availability()
        self.assertEqual(available["status"], SEQUENCE_STATUS_PLANNED)
        self.assertRegex(available["plan_digest"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            available["kernel_ids"],
            list(DEFAULT_STAGE_KERNELS[stage] for stage in SEQUENCE_BASE_STAGES),
        )

        real = SequenceController(
            MthRegistry.load(MANIFEST)
        ).availability()
        self.assertEqual(real["status"], SEQUENCE_STATUS_UNAVAILABLE)
        self.assertEqual(
            real["reason"], SEQUENCE_REASON_EMBEDDING_GATHER_UNAVAILABLE
        )

        rejected = SequenceController(
            _registry(),
            {"embedding_gather": "mth.not.registered.embed.f32"},
        ).availability()
        self.assertEqual(rejected["status"], "REJECTED")
        self.assertEqual(rejected["reason"], SEQUENCE_REASON_UNKNOWN_KERNEL)

        invalid = SequenceController(_registry()).availability(
            mask_policy="triangular"
        )
        self.assertEqual(invalid["status"], "REJECTED")
        self.assertEqual(
            invalid["reason"], SEQUENCE_REASON_INVALID_MASK_POLICY
        )


class SequenceControllerBoundaryTests(unittest.TestCase):
    def test_no_host_math_token_arithmetic_or_execution_bypass(self):
        source = inspect.getsource(sequence_controller)
        tree = ast.parse(source)
        forbidden_imports = {
            "math", "numpy", "scipy", "sympy", "subprocess", "ctypes",
            "mmap", "sqlite3", "socket", "random", "secrets", "statistics",
            "decimal", "fractions", "hashlib_hmac", "hmac",
        }
        forbidden_calls = {
            "abs", "complex", "divmod", "eval", "exec", "float", "int",
            "max", "min", "pow", "round", "sum", "ord", "chr", "bin", "hex",
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

        controller = SequenceController(MthRegistry.load(MANIFEST))
        for name in (
            "execute", "dispatch", "submit", "run", "apply",
            "gather", "slice", "tokenize", "encode", "decode", "mask",
        ):
            self.assertFalse(hasattr(controller, name))
        for name in ("execute", "dispatch", "submit"):
            self.assertFalse(hasattr(sequence_controller, name))


if __name__ == "__main__":
    unittest.main()
