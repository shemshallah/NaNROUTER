from __future__ import annotations

import json
import unittest

from runner_riddle.lm_ablation import (
    ABLATION_SCHEMA,
    ADAPTER_OFF,
    ADAPTER_ON,
    BASE_ONLY,
    COMPARISONS,
    DuplicateTaskError,
    EncodedState,
    LMAdapterAblation,
    LMAdapterAblationError,
    ModelBindingError,
    ModelHookError,
    ResidualExecutorError,
    ResidualResult,
    SplitLeakageError,
    ZERO_RESIDUAL,
    AblationSpec,
    AblationTask,
    AblationTaskSet,
)
from runner_riddle.wave_adapter import WaveAdapterConfig

MODEL_ID = "fake-frozen-lm.v1"


class FakeFrozenModel:
    """Deterministic stand-in. The adapter changes state only via the executor."""

    model_id = MODEL_ID

    def __init__(
        self,
        answers: dict[str, str],
        *,
        adapter_helps: bool = True,
        helpful_seeds: set[int] | None = None,
        base_correct: bool = False,
    ) -> None:
        self.answers = dict(answers)
        self.adapter_helps = adapter_helps
        self.helpful_seeds = helpful_seeds
        self.base_correct = base_correct
        self.encode_calls = 0
        self.predict_calls = 0
        self.predict_conditions: list[str] = []

    def encode(self, prompt: str, *, task_id: str, seed: int) -> EncodedState:
        self.encode_calls += 1
        return EncodedState(
            base_state=("base", task_id, seed),
            readout_state=("readout", task_id, seed),
        )

    def predict(
        self,
        state: object,
        prompt: str,
        *,
        task_id: str,
        seed: int,
        condition: str,
    ) -> str:
        self.predict_calls += 1
        self.predict_conditions.append(condition)
        correct = self.answers[task_id]
        if condition == ADAPTER_ON:
            adapted = (
                isinstance(state, tuple)
                and bool(state)
                and state[0] == "adapted"
            )
            helps = self.adapter_helps and (
                self.helpful_seeds is None or seed in self.helpful_seeds
            )
            if adapted and helps:
                return correct
            return f"wrong:{task_id}"
        if self.base_correct:
            return correct
        return f"wrong:{task_id}"


class FakeResidualExecutor:
    executor_id = "fake-residual-executor"
    evidence = "unit-test-only"

    def __init__(self) -> None:
        self.requests = []
        self.calls = 0

    def __call__(self, request):
        self.calls += 1
        self.requests.append(request)
        if not request.enabled:
            return ResidualResult(state=request.base_state, applied=False)
        if request.beta == 0.0:
            return ResidualResult(state=request.base_state, applied=True)
        return ResidualResult(
            state=("adapted", request.base_state), applied=True
        )


class BadOffExecutor(FakeResidualExecutor):
    def __call__(self, request):
        result = super().__call__(request)
        if request.condition == ADAPTER_OFF:
            return ResidualResult(
                state=("tampered", request.base_state), applied=False
            )
        return result


class BadOnAppliedExecutor(FakeResidualExecutor):
    def __call__(self, request):
        result = super().__call__(request)
        if request.condition == ADAPTER_ON:
            return ResidualResult(state=result.state, applied=False)
        return result


def make_tasks(count: int = 20) -> tuple[AblationTask, ...]:
    return tuple(
        AblationTask(
            task_id=f"t{index:02d}",
            prompt=f"prompt {index:02d}",
            expected=f"answer-{index:02d}",
        )
        for index in range(count)
    )


def make_answers(count: int = 20) -> dict[str, str]:
    return {
        f"t{index:02d}": f"answer-{index:02d}" for index in range(count)
    }


def make_task_set(
    count: int = 20,
    *,
    dataset_id: str = "heldout-unit",
    synthetic: bool = False,
    excluded_tasks: tuple[AblationTask, ...] = (),
) -> AblationTaskSet:
    return AblationTaskSet(
        dataset_id=dataset_id,
        tasks=make_tasks(count),
        excluded_tasks=excluded_tasks,
        synthetic=synthetic,
        provenance="unit-test",
    )


def make_config(**overrides) -> WaveAdapterConfig:
    values = {
        "adapter_id": "r9-unit",
        "universe_id": "u-unit",
        "base_model_id": MODEL_ID,
        "readout_dim": 128,
        "residual_scale": 0.125,
        "mode": "ring_readout",
        "evidence_level": "native_verified",
        "ablations": ("ring_on_off",),
    }
    values.update(overrides)
    return WaveAdapterConfig(**values)


def make_spec(**overrides) -> AblationSpec:
    values = {
        "seeds": (0, 1),
        "bootstrap_samples": 300,
        "bootstrap_seed": 11,
        "min_tasks": 8,
        "min_seeds": 2,
        "min_effect": 0.0,
        "label_control_shift": 1,
    }
    values.update(overrides)
    return AblationSpec(**values)


class LMAdapterAblationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = make_config()
        self.spec = make_spec()
        self.answers = make_answers()

    def run_case(
        self,
        *,
        count: int = 20,
        task_set: AblationTaskSet | None = None,
        model: object | None = None,
        executor: object | None = None,
        config: WaveAdapterConfig | None = None,
        spec: AblationSpec | None = None,
    ):
        task_set = task_set or make_task_set(count)
        model = model or FakeFrozenModel(self.answers,)
        executor = executor or FakeResidualExecutor()
        harness = LMAdapterAblation(config or self.config, spec=spec or self.spec)
        report = harness.run(
            task_set, frozen_model=model, residual_executor=executor
        )
        return report, model, executor, harness, task_set

    # -- Construction and evidence -------------------------------------------

    def test_construction_does_not_require_model_or_dataset(self):
        harness = LMAdapterAblation(self.config, spec=self.spec)
        described = harness.describe()

        self.assertEqual(described["schema"], ABLATION_SCHEMA)
        self.assertEqual(described["mode"], "control-plane")
        self.assertFalse(described["model_required_for_construction"])
        self.assertEqual(described["model_calls_made"], 0)
        self.assertEqual(len(harness.adapter_config_digest), 64)
        self.assertEqual(harness.base_model_id, MODEL_ID)
        self.assertEqual(
            described["adapter_config_digest"], harness.adapter_config_digest
        )

    def test_passing_ablation_emits_digests_paired_deltas_and_counts(self):
        report, model, executor, harness, task_set = self.run_case()

        self.assertEqual(report["schema"], ABLATION_SCHEMA)
        self.assertEqual(report["status"], "ablation_passed")
        self.assertEqual(report["evidence_level"], "ablation_passed")
        self.assertTrue(report["passed"])
        self.assertFalse(report["claim"]["creativity_claim"])
        self.assertFalse(report["claim"]["generalization_claim"])
        self.assertEqual(report["base_model_id"], MODEL_ID)
        self.assertEqual(report["adapter_config_digest"], harness.adapter_config_digest)
        self.assertEqual(report["task_split_digest"], task_set.split_digest())
        self.assertEqual(len(report["task_split_digest"]), 64)
        self.assertEqual(report["dataset"]["task_count"], 20)
        self.assertFalse(report["dataset"]["missing"])
        self.assertTrue(report["dataset"]["admissible"])
        self.assertEqual(report["adapter"]["evidence_level_before"], "native_verified")
        self.assertEqual(self.config.evidence_level, "native_verified")

        self.assertEqual(len(report["per_task"]), 20)
        first = report["per_task"][0]
        self.assertEqual(first["task_id"], "t00")
        self.assertEqual(len(first["runs"]), 2)
        for run in first["runs"]:
            self.assertEqual(
                set(run["conditions"]),
                {BASE_ONLY, ADAPTER_ON, ADAPTER_OFF, ZERO_RESIDUAL},
            )
            self.assertTrue(run["conditions"][ADAPTER_ON]["match"])
            self.assertTrue(run["conditions"][ADAPTER_ON]["exact"])
            self.assertFalse(run["conditions"][BASE_ONLY]["match"])
            self.assertFalse(run["conditions"][ADAPTER_OFF]["match"])
            self.assertFalse(run["conditions"][ZERO_RESIDUAL]["match"])
            self.assertFalse(run["shuffled_labels"]["match"])
            for comparison in COMPARISONS:
                self.assertEqual(run["deltas"][comparison], 1.0)

        conditions = report["aggregates"]["conditions"]
        self.assertEqual(conditions["base_only"]["match_rate"], 0.0)
        self.assertEqual(conditions["adapter_on"]["match_rate"], 1.0)
        self.assertEqual(conditions["adapter_off"]["match_rate"], 0.0)
        self.assertEqual(conditions["zero_residual"]["match_rate"], 0.0)
        self.assertEqual(conditions["shuffled_labels"]["match_rate"], 0.0)

        for comparison in COMPARISONS:
            delta = report["aggregates"]["deltas"][comparison]
            self.assertEqual(delta["mean_delta"], 1.0)
            self.assertEqual(delta["ci_low"], 1.0)
            self.assertEqual(delta["ci_high"], 1.0)
            self.assertEqual(delta["improved_tasks"], 20)
            self.assertEqual(delta["worse_tasks"], 0)
            self.assertEqual(delta["tied_tasks"], 0)
            self.assertTrue(delta["reproducible"])
            self.assertEqual(delta["status"], "pass")
            self.assertEqual(len(delta["per_seed"]), 2)
            self.assertEqual(
                [item["mean_delta"] for item in delta["per_seed"]],
                [1.0, 1.0],
            )

        self.assertEqual(report["call_counts"]["encode"], 40)
        self.assertEqual(report["call_counts"]["predict"], 160)
        self.assertEqual(report["call_counts"]["residual_executor"], 120)
        self.assertTrue(report["call_counts"]["matches_expected"])
        self.assertEqual(model.encode_calls, 40)
        self.assertEqual(model.predict_calls, 160)
        self.assertEqual(executor.calls, 120)
        self.assertEqual(
            set(model.predict_conditions),
            {BASE_ONLY, ADAPTER_ON, ADAPTER_OFF, ZERO_RESIDUAL},
        )

        by_condition = {condition: [] for condition in (
            ADAPTER_ON, ADAPTER_OFF, ZERO_RESIDUAL
        )}
        for request in executor.requests:
            by_condition[request.condition].append(request)
        self.assertTrue(all(len(items) == 40 for items in by_condition.values()))
        for request in by_condition[ADAPTER_ON]:
            self.assertTrue(request.enabled)
            self.assertEqual(request.beta, 0.125)
            self.assertEqual(request.readout_dim, 128)
            self.assertEqual(
                request.adapter_config_digest, report["adapter_config_digest"]
            )
        for request in by_condition[ADAPTER_OFF]:
            self.assertFalse(request.enabled)
            self.assertEqual(request.beta, 0.0)
        for request in by_condition[ZERO_RESIDUAL]:
            self.assertTrue(request.enabled)
            self.assertEqual(request.beta, 0.0)

        self.assertTrue(report["passed"])
        self.assertEqual(report["gate"]["reasons"], [])
        self.assertTrue(
            all(check["status"] == "pass" for check in report["gate"]["checks"])
        )
        json.dumps(report)

    def test_no_improvement_is_rejected(self):
        model = FakeFrozenModel(self.answers, adapter_helps=False)
        report, _, _, _, _ = self.run_case(model=model)

        self.assertEqual(report["status"], "rejected")
        self.assertFalse(report["passed"])
        self.assertEqual(
            report["aggregates"]["deltas"]["adapter_on_vs_base_only"][
                "mean_delta"
            ],
            0.0,
        )
        self.assertEqual(
            report["aggregates"]["deltas"]["adapter_on_vs_base_only"]["status"],
            "fail",
        )
        reasons = " ".join(report["gate"]["reasons"])
        self.assertIn("beats_base_only", reasons)

    def test_matched_controls_block_a_pass(self):
        model = FakeFrozenModel(self.answers, base_correct=True)
        report, _, _, _, _ = self.run_case(model=model)

        self.assertEqual(report["status"], "rejected")
        self.assertFalse(report["passed"])
        deltas = report["aggregates"]["deltas"]
        for comparison in (
            "adapter_on_vs_base_only",
            "adapter_on_vs_adapter_off",
            "adapter_on_vs_zero_residual",
        ):
            self.assertEqual(deltas[comparison]["mean_delta"], 0.0)
            self.assertEqual(deltas[comparison]["status"], "fail")
        self.assertEqual(
            deltas["adapter_on_vs_shuffled_labels"]["mean_delta"], 1.0
        )

    def test_shuffled_label_control_blocks_pass_when_labels_are_identical(self):
        tasks = tuple(
            AblationTask(
                task_id=f"t{index:02d}",
                prompt=f"prompt {index:02d}",
                expected="same-answer",
            )
            for index in range(12)
        )
        task_set = AblationTaskSet(
            "same-label-unit", tasks, provenance="unit-test"
        )
        answers = {task.task_id: "same-answer" for task in tasks}
        model = FakeFrozenModel(answers)
        report, _, _, _, _ = self.run_case(task_set=task_set, model=model)

        self.assertEqual(report["status"], "rejected")
        self.assertFalse(report["passed"])
        shuffled = report["aggregates"]["deltas"][
            "adapter_on_vs_shuffled_labels"
        ]
        self.assertEqual(shuffled["mean_delta"], 0.0)
        self.assertEqual(shuffled["status"], "fail")
        self.assertIn(
            "beats_shuffled_labels", " ".join(report["gate"]["reasons"])
        )

    def test_non_reproducible_seed_effect_is_inconclusive(self):
        model = FakeFrozenModel(self.answers, helpful_seeds={0})
        report, _, _, _, _ = self.run_case(model=model)

        self.assertEqual(report["status"], "inconclusive")
        self.assertFalse(report["passed"])
        delta = report["aggregates"]["deltas"]["adapter_on_vs_base_only"]
        self.assertEqual(delta["mean_delta"], 0.5)
        self.assertEqual(delta["ci_low"], 0.5)
        self.assertFalse(delta["reproducible"])
        self.assertEqual(delta["status"], "inconclusive")
        self.assertEqual(
            [item["mean_delta"] for item in delta["per_seed"]], [1.0, 0.0]
        )
        self.assertIn("not positive for every seed", delta["reason"])

    def test_underpowered_and_synthetic_sets_never_pass(self):
        underpowered = make_task_set(4)
        report, _, _, _, _ = self.run_case(task_set=underpowered)
        self.assertEqual(report["status"], "inconclusive")
        self.assertFalse(report["passed"])
        self.assertFalse(report["dataset"]["admissible"])
        reasons = " ".join(report["gate"]["reasons"])
        self.assertIn("min_tasks", reasons)

        synthetic = make_task_set(20, synthetic=True)
        report, _, _, _, _ = self.run_case(task_set=synthetic)
        self.assertEqual(report["status"], "inconclusive")
        self.assertFalse(report["passed"])
        self.assertFalse(report["dataset"]["admissible"])
        self.assertIn("synthetic", " ".join(report["gate"]["reasons"]))

        no_effect = FakeFrozenModel(self.answers, adapter_helps=False)
        report, _, _, _, _ = self.run_case(
            task_set=synthetic, model=no_effect
        )
        self.assertEqual(report["status"], "inconclusive")
        self.assertFalse(report["passed"])

    def test_missing_and_empty_datasets_are_inconclusive_without_calls(self):
        harness = LMAdapterAblation(self.config, spec=self.spec)

        missing = harness.run()
        self.assertEqual(missing["status"], "inconclusive")
        self.assertFalse(missing["passed"])
        self.assertTrue(missing["dataset"]["missing"])
        self.assertIsNone(missing["task_split_digest"])
        self.assertEqual(missing["call_counts"]["encode"], 0)
        self.assertEqual(missing["call_counts"]["predict"], 0)
        self.assertEqual(missing["call_counts"]["residual_executor"], 0)

        empty = AblationTaskSet("empty-unit", ())
        empty_report = harness.run(empty)
        self.assertEqual(empty_report["status"], "inconclusive")
        self.assertFalse(empty_report["passed"])
        self.assertTrue(empty_report["dataset"]["missing"])
        self.assertEqual(len(empty_report["task_split_digest"]), 64)
        self.assertEqual(empty_report["call_counts"]["encode"], 0)
        self.assertEqual(empty_report["per_task"], [])
        self.assertEqual(empty_report["aggregates"]["deltas"], {})

    # -- Split integrity ------------------------------------------------------

    def test_non_heldout_split_is_rejected_as_leakage(self):
        with self.assertRaises(SplitLeakageError):
            AblationTaskSet(
                "leaky-unit",
                (
                    AblationTask(
                        task_id="t00",
                        prompt="prompt 00",
                        expected="answer-00",
                        split="train",
                    ),
                ),
            )

    def test_excluded_task_id_and_prompt_overlap_are_rejected(self):
        heldout = make_task_set(4)
        with self.assertRaises(SplitLeakageError):
            AblationTaskSet(
                "leaky-id",
                heldout.tasks,
                excluded_tasks=(
                    AblationTask(
                        task_id="t00",
                        prompt="different prompt",
                        expected="different",
                        split="train",
                    ),
                ),
            )
        with self.assertRaises(SplitLeakageError):
            AblationTaskSet(
                "leaky-prompt",
                heldout.tasks,
                excluded_tasks=(
                    AblationTask(
                        task_id="train-00",
                        prompt="  PROMPT   00  ",
                        expected="different",
                        split="train",
                    ),
                ),
            )

    def test_duplicate_tasks_are_rejected(self):
        with self.assertRaises(DuplicateTaskError):
            AblationTaskSet(
                "duplicate-id",
                (
                    AblationTask("t00", "prompt 00", "answer-00"),
                    AblationTask("t00", "prompt 01", "answer-01"),
                ),
            )
        with self.assertRaises(DuplicateTaskError):
            AblationTaskSet(
                "duplicate-prompt",
                (
                    AblationTask("t00", "Prompt 00", "answer-00"),
                    AblationTask("t01", "prompt   00", "answer-01"),
                ),
            )

    def test_task_split_digest_is_order_independent(self):
        forward = make_task_set(8)
        backward = AblationTaskSet(
            "heldout-unit",
            tuple(reversed(forward.tasks)),
            provenance="unit-test",
        )
        self.assertEqual(forward.split_digest(), backward.split_digest())
        changed = AblationTaskSet(
            "heldout-unit",
            (
                AblationTask("t00", "prompt 00", "different-answer"),
                *make_tasks(8)[1:],
            ),
            provenance="unit-test",
        )
        self.assertNotEqual(forward.split_digest(), changed.split_digest())

    # -- Hook and executor contracts -----------------------------------------

    def test_model_binding_and_hook_requirements(self):
        task_set = make_task_set(4)
        executor = FakeResidualExecutor()
        harness = LMAdapterAblation(self.config, spec=self.spec)

        with self.assertRaises(ModelBindingError):
            harness.run(task_set, frozen_model=None, residual_executor=executor)

        wrong_model = FakeFrozenModel(self.answers)
        wrong_model.model_id = "other-model"
        with self.assertRaises(ModelBindingError):
            harness.run(
                task_set,
                frozen_model=wrong_model,
                residual_executor=executor,
            )

        valid_model = FakeFrozenModel(self.answers)
        with self.assertRaises(ResidualExecutorError):
            harness.run(task_set, frozen_model=valid_model)

        class BadEncodeModel(FakeFrozenModel):
            def encode(self, prompt, *, task_id, seed):
                return {"base_state": "x", "readout_state": "y"}

        with self.assertRaises(ModelHookError):
            harness.run(
                task_set,
                frozen_model=BadEncodeModel(self.answers),
                residual_executor=executor,
            )

        class BadPredictModel(FakeFrozenModel):
            def predict(self, state, prompt, *, task_id, seed, condition):
                return 17

        with self.assertRaises(ModelHookError):
            harness.run(
                task_set,
                frozen_model=BadPredictModel(self.answers),
                residual_executor=executor,
            )

    def test_executor_contract_violations_are_rejected(self):
        task_set = make_task_set(4)
        model = FakeFrozenModel(self.answers)
        harness = LMAdapterAblation(self.config, spec=self.spec)

        with self.assertRaises(ResidualExecutorError):
            harness.run(
                task_set,
                frozen_model=model,
                residual_executor=BadOffExecutor(),
            )
        with self.assertRaises(ResidualExecutorError):
            harness.run(
                task_set,
                frozen_model=model,
                residual_executor=BadOnAppliedExecutor(),
            )

    def test_adapter_config_mapping_is_accepted_and_digest_is_stable(self):
        harness = LMAdapterAblation(self.config, spec=self.spec)
        restored = LMAdapterAblation(self.config.to_dict(), spec=self.spec)
        self.assertEqual(
            harness.adapter_config_digest, restored.adapter_config_digest
        )

    def test_invalid_spec_and_exception_type_are_checked(self):
        with self.assertRaises(LMAdapterAblationError):
            LMAdapterAblation(self.config, spec=object())
        with self.assertRaises(LMAdapterAblationError):
            AblationSpec(seeds=())
        with self.assertRaises(LMAdapterAblationError):
            AblationSpec(seeds=(1, 1))
        with self.assertRaises(LMAdapterAblationError):
            AblationSpec(min_tasks=1)


if __name__ == "__main__":
    unittest.main()
