from __future__ import annotations

import json
import unittest

from runner_riddle.r7_experiment import (
    AVOIDED_CROSSING_MARKER,
    BASELINE_CONDITIONS,
    CANDIDATE_CONDITION,
    CONDITION_DISCONNECTED,
    CONDITION_RANDOM,
    CONDITIONS,
    AvoidedCrossingEvidence,
    CouplingEvidence,
    DuplicateTaskError,
    EvaluatorBindingError,
    NativeEvidenceError,
    PhaseCoherenceEvidence,
    R7_SCHEMA,
    R7Experiment,
    R7ExperimentError,
    R7NativeEvidence,
    R7Prediction,
    R7Spec,
    R7Task,
    R7TaskSet,
    SplitLeakageError,
    run_r7_experiment,
)

_MISSING = object()


def make_tasks(count: int = 12) -> tuple[R7Task, ...]:
    return tuple(
        R7Task(
            task_id=f"t{index:02d}",
            prompt=f"prompt {index:02d}",
            expected=f"answer-{index:02d}",
            task_family="association",
        )
        for index in range(count)
    )


def answers_for(tasks: tuple[R7Task, ...]) -> dict[str, str]:
    return {
        task.task_id: task.accepted_answers()[0] for task in tasks
    }


def make_task_set(
    tasks: tuple[R7Task, ...] | None = None,
    *,
    dataset_id: str = "heldout-r7-unit",
    excluded_tasks: tuple[R7Task, ...] = (),
    synthetic: bool = False,
    provenance: str = "unit-test",
) -> R7TaskSet:
    return R7TaskSet(
        dataset_id=dataset_id,
        tasks=tasks if tasks is not None else make_tasks(),
        excluded_tasks=excluded_tasks,
        synthetic=synthetic,
        provenance=provenance,
    )


def make_spec(**overrides) -> R7Spec:
    values = {
        "seeds": (0, 1),
        "bootstrap_samples": 200,
        "permutation_samples": 200,
        "bootstrap_seed": 11,
        "permutation_seed": 12,
        "confidence": 0.95,
        "min_tasks": 8,
        "min_seeds": 2,
        "min_effect": 0.0,
        "candidate_eta": 0.25,
        "novelty_floor": 0.0,
    }
    values.update(overrides)
    return R7Spec(**values)


class FakeEvaluator:
    """Deterministic fake evaluator; it never runs or contains a model."""

    evaluator_id = "fake-r7-evaluator"

    def __init__(
        self,
        answers: dict[str, str],
        *,
        correct: bool = True,
        correct_seeds: set[int] | None = None,
        novelty: float | None = None,
        usefulness: float | None = None,
    ) -> None:
        self.answers = dict(answers)
        self.correct = correct
        self.correct_seeds = correct_seeds
        self.novelty = novelty
        self.usefulness = usefulness
        self.calls = []

    def __call__(self, request):
        self.calls.append(request)
        if self.correct_seeds is not None:
            is_correct = request.seed in self.correct_seeds
        else:
            is_correct = self.correct
        text = (
            self.answers[request.task_id]
            if is_correct
            else f"wrong-{request.task_id}"
        )
        return R7Prediction(
            text,
            novelty=self.novelty,
            usefulness=self.usefulness,
        )


def make_native_evidence(
    *,
    eta: float = 0.25,
    coherence: float = 1.0,
) -> R7NativeEvidence:
    """Fixture-derived constants supplied as caller evidence, not executed."""
    return R7NativeEvidence(
        avoided_crossing=AvoidedCrossingEvidence(
            couplings=(0.0, 1.0, 2.0),
            gaps=(0.0, 2.8284270763397217, 4.4721360206604),
            lower=(
                1.0,
                0.5857864618301392,
                -0.2360679805278778,
            ),
            upper=(
                3.0,
                3.4142136573791504,
                4.236067771911621,
            ),
            a=1.0,
            b=3.0,
            source="mth/tests/mth_avoided_crossing_sweep_test.nas",
            status="native_verified",
            marker=AVOIDED_CROSSING_MARKER,
            steps=11651,
        ),
        phase_coherence=PhaseCoherenceEvidence(
            coherence=coherence,
            sample_count=128,
            source="mth/tests/mth_phase_coherence_128_test.nas",
            status="native_verified",
            steps=11381,
        ),
        coupling=CouplingEvidence(
            eta=eta,
            source="mth/tests/mth_graph_couple_128_test.nas",
            status="native_verified",
            steps=8637,
        ),
        note="unit-test values copied from fixture documentation",
    )


class R7TaskContractTests(unittest.TestCase):
    def test_non_heldout_split_is_rejected_as_leakage(self):
        with self.assertRaises(SplitLeakageError):
            R7TaskSet(
                "leaky-heldout",
                (
                    R7Task(
                        "t00",
                        "prompt 00",
                        "answer-00",
                        split="train",
                    ),
                ),
            )

    def test_excluded_train_id_or_prompt_overlap_is_rejected(self):
        heldout = make_tasks(4)
        with self.assertRaises(SplitLeakageError):
            R7TaskSet(
                "leaky-id",
                heldout,
                excluded_tasks=(
                    R7Task(
                        "t00",
                        "different train prompt",
                        "different",
                        split="train",
                    ),
                ),
            )
        with self.assertRaises(SplitLeakageError):
            R7TaskSet(
                "leaky-prompt",
                heldout,
                excluded_tasks=(
                    R7Task(
                        "train-00",
                        "  PROMPT   00  ",
                        "different",
                        split="train",
                    ),
                ),
            )

    def test_excluded_tasks_must_not_be_marked_heldout(self):
        with self.assertRaises(SplitLeakageError):
            R7TaskSet(
                "excluded-heldout",
                make_tasks(4),
                excluded_tasks=(
                    R7Task(
                        "train-00",
                        "unseen train prompt",
                        "answer",
                        split="heldout",
                    ),
                ),
            )
        # Non-held-out labels are metadata; a caller may use "test" as an
        # excluded holdback. It is never evaluated.
        task_set = R7TaskSet(
            "excluded-test",
            make_tasks(4),
            excluded_tasks=(
                R7Task(
                    "test-00",
                    "held-back test prompt",
                    "answer",
                    split="test",
                ),
            ),
        )
        self.assertEqual(task_set.excluded_tasks[0].split, "test")

    def test_duplicate_tasks_are_rejected(self):
        with self.assertRaises(DuplicateTaskError):
            R7TaskSet(
                "duplicate-id",
                (
                    R7Task("t00", "prompt 00", "answer-00"),
                    R7Task("t00", "prompt 01", "answer-01"),
                ),
            )
        with self.assertRaises(DuplicateTaskError):
            R7TaskSet(
                "duplicate-prompt",
                (
                    R7Task("t00", "Prompt 00", "answer-00"),
                    R7Task("t01", "prompt   00", "answer-01"),
                ),
            )
        with self.assertRaises(DuplicateTaskError):
            R7TaskSet(
                "duplicate-train-id",
                make_tasks(4),
                excluded_tasks=(
                    R7Task("train-00", "train prompt", "a", split="train"),
                    R7Task("train-00", "other prompt", "b", split="train"),
                ),
            )

    def test_split_digest_is_order_independent_and_content_bound(self):
        forward = make_task_set(make_tasks(8))
        backward = make_task_set(tuple(reversed(forward.tasks)))
        self.assertEqual(forward.split_digest(), backward.split_digest())
        self.assertEqual(len(forward.split_digest()), 64)

        changed_answer = make_task_set(
            (
                R7Task("t00", "prompt 00", "different-answer"),
                *make_tasks(8)[1:],
            )
        )
        changed_dataset = make_task_set(
            make_tasks(8), dataset_id="heldout-r7-other"
        )
        changed_provenance = make_task_set(
            make_tasks(8), provenance="different provenance"
        )
        self.assertNotEqual(forward.split_digest(), changed_answer.split_digest())
        self.assertNotEqual(
            forward.split_digest(), changed_dataset.split_digest()
        )
        self.assertNotEqual(
            forward.split_digest(), changed_provenance.split_digest()
        )

    def test_split_evidence_records_excluded_train_material(self):
        excluded = (
            R7Task("train-00", "train prompt", "train answer", split="train"),
            R7Task("dev-00", "dev prompt", "dev answer", split="dev"),
        )
        task_set = make_task_set(make_tasks(8), excluded_tasks=excluded)
        evidence = task_set.to_evidence()

        self.assertEqual(evidence["task_count"], 8)
        self.assertEqual(evidence["excluded_task_count"], 2)
        self.assertEqual(task_set.train_tasks, excluded)
        self.assertEqual(evidence["excluded_splits"], ["dev", "train"])
        self.assertEqual(
            evidence["excluded_task_ids"], ["dev-00", "train-00"]
        )
        self.assertEqual(
            evidence["task_split_digest"], task_set.split_digest()
        )


class R7ExperimentGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = make_spec()

    def run_case(
        self,
        *,
        count: int = 12,
        task_set: R7TaskSet | None = None,
        baseline_correct: bool = False,
        coupled_correct: bool = True,
        baseline_novelty: float | None = None,
        coupled_novelty: float | None = None,
        correct_seeds: set[int] | None = None,
        native_evidence=_MISSING,
        spec: R7Spec | None = None,
        use_predictions: bool = False,
    ):
        tasks = make_tasks(count)
        task_set = task_set or make_task_set(tasks)
        answers = answers_for(tasks)
        baseline = FakeEvaluator(
            answers,
            correct=baseline_correct,
            novelty=baseline_novelty,
        )
        coupled = FakeEvaluator(
            answers,
            correct=coupled_correct,
            correct_seeds=correct_seeds,
            novelty=coupled_novelty,
        )
        harness = R7Experiment(spec or self.spec)
        kwargs = {}
        if use_predictions:
            kwargs["baseline_predictions"] = {
                task.task_id: (
                    answers[task.task_id]
                    if baseline_correct
                    else f"wrong-{task.task_id}"
                )
                for task in tasks
            }
            kwargs["coupled_predictions"] = {
                task.task_id: (
                    answers[task.task_id]
                    if coupled_correct
                    else f"wrong-{task.task_id}"
                )
                for task in tasks
            }
        else:
            kwargs["baseline_evaluator"] = baseline
            kwargs["coupled_evaluator"] = coupled
        if native_evidence is _MISSING:
            native_evidence = make_native_evidence()
        elif native_evidence is False:
            native_evidence = None
        report = harness.run(
            task_set,
            native_evidence=native_evidence,
            **kwargs,
        )
        return report, baseline, coupled, harness, task_set

    def test_supported_improvement_records_paired_evidence(self):
        report, baseline, coupled, harness, task_set = self.run_case(
            baseline_novelty=0.1,
            coupled_novelty=0.9,
        )

        self.assertEqual(report["schema"], R7_SCHEMA)
        self.assertEqual(report["status"], "supported")
        self.assertEqual(report["evidence_level"], "supported")
        self.assertTrue(report["passed"])
        self.assertFalse(report["claim"]["creativity_claim"])
        self.assertFalse(report["claim"]["tunneling_claim"])
        self.assertFalse(report["claim"]["generalization_claim"])
        self.assertEqual(report["task_split_digest"], task_set.split_digest())
        self.assertEqual(report["dataset"]["task_count"], 12)
        self.assertFalse(report["dataset"]["missing"])
        self.assertTrue(report["dataset"]["admissible"])

        for condition in CONDITIONS:
            aggregate = report["aggregates"]["conditions"][condition]
            self.assertEqual(aggregate["n"], 24)
            if condition == CANDIDATE_CONDITION:
                self.assertEqual(aggregate["match_rate"], 1.0)
            else:
                self.assertEqual(aggregate["match_rate"], 0.0)

        for condition in BASELINE_CONDITIONS:
            delta = report["aggregates"]["deltas"][condition]
            self.assertEqual(delta["mean_delta"], 1.0)
            self.assertEqual(delta["ci_low"], 1.0)
            self.assertEqual(delta["ci_high"], 1.0)
            self.assertLessEqual(delta["permutation_p_value"], delta["alpha"])
            self.assertEqual(delta["improved_tasks"], 12)
            self.assertEqual(delta["worse_tasks"], 0)
            self.assertEqual(delta["tied_tasks"], 0)
            self.assertTrue(delta["reproducible"])
            self.assertEqual(delta["status"], "pass")
            self.assertEqual(
                [item["mean_delta"] for item in delta["per_seed"]],
                [1.0, 1.0],
            )
            self.assertEqual(delta["novelty_delta"], 0.8)
            self.assertFalse(delta["novelty_without_correctness"])

        native = report["native_evidence"]
        self.assertTrue(native["present"])
        self.assertFalse(native["verified_by_harness"])
        self.assertEqual(native["coupling_metrics"]["eta"], 0.25)
        self.assertTrue(native["coupling_metrics"]["partial_coupling"])
        self.assertEqual(native["phase_metrics"]["coherence"], 1.0)
        self.assertEqual(native["transition_metrics"]["coupling_count"], 3)
        self.assertEqual(native["transition_metrics"]["min_gap"], 0.0)
        self.assertEqual(
            native["transition_metrics"]["min_gap_coupling"], 0.0
        )
        self.assertEqual(len(native["evidence_digest"]), 64)

        self.assertEqual(report["call_counts"]["evaluations"], 72)
        self.assertEqual(report["call_counts"]["expected_evaluations"], 72)
        self.assertTrue(report["call_counts"]["matches_expected"])
        self.assertEqual(report["call_counts"]["baseline_evaluator_calls"], 48)
        self.assertEqual(report["call_counts"]["coupled_evaluator_calls"], 24)
        self.assertEqual(len(baseline.calls), 48)
        self.assertEqual(len(coupled.calls), 24)
        for request in coupled.calls:
            self.assertEqual(request.condition, CANDIDATE_CONDITION)
            self.assertEqual(request.role, "candidate")
            self.assertEqual(request.eta, 0.25)
            self.assertFalse(hasattr(request, "expected"))

        for check in report["gate"]["checks"]:
            self.assertEqual(check["status"], "pass", check)
        self.assertEqual(report["gate"]["reasons"], [])
        self.assertEqual(report["evaluators"]["baseline"]["id"], "fake-r7-evaluator")
        self.assertEqual(report["evaluators"]["coupled"]["id"], "fake-r7-evaluator")
        json.dumps(report)

    def test_candidate_baseline_tie_is_rejected(self):
        report, _, _, _, _ = self.run_case(
            baseline_correct=False,
            coupled_correct=False,
        )

        self.assertEqual(report["status"], "rejected")
        self.assertFalse(report["passed"])
        for condition in BASELINE_CONDITIONS:
            delta = report["aggregates"]["deltas"][condition]
            self.assertEqual(delta["mean_delta"], 0.0)
            self.assertEqual(delta["status"], "fail")
            self.assertIn("not above min_effect", delta["reason"])
        reasons = " ".join(report["gate"]["reasons"])
        self.assertIn("beats_disconnected", reasons)
        self.assertIn("beats_random_coupling", reasons)

    def test_candidate_harm_is_rejected(self):
        report, _, _, _, _ = self.run_case(
            baseline_correct=True,
            coupled_correct=False,
        )

        self.assertEqual(report["status"], "rejected")
        self.assertFalse(report["passed"])
        for condition in BASELINE_CONDITIONS:
            delta = report["aggregates"]["deltas"][condition]
            self.assertEqual(delta["mean_delta"], -1.0)
            self.assertEqual(delta["status"], "fail")
            self.assertIn("candidate is worse", delta["reason"])
            self.assertEqual(delta["worse_tasks"], 12)

    def test_small_sample_is_inconclusive_even_with_large_effect(self):
        report, _, _, _, _ = self.run_case(count=4)

        self.assertEqual(report["status"], "inconclusive")
        self.assertFalse(report["passed"])
        self.assertFalse(report["dataset"]["admissible"])
        self.assertEqual(report["dataset"]["task_count"], 4)
        self.assertIn("min_tasks", " ".join(report["gate"]["reasons"]))
        # The delta itself is large; the sample is what blocks a claim.
        delta = report["aggregates"]["deltas"][CONDITION_DISCONNECTED]
        self.assertEqual(delta["mean_delta"], 1.0)
        self.assertIn(delta["status"], {"pass", "inconclusive"})

    def test_synthetic_dataset_never_supports(self):
        tasks = make_tasks(12)
        report, _, _, _, _ = self.run_case(
            task_set=make_task_set(tasks, synthetic=True)
        )

        self.assertEqual(report["status"], "inconclusive")
        self.assertFalse(report["passed"])
        self.assertFalse(report["dataset"]["admissible"])
        self.assertIn("synthetic", " ".join(report["gate"]["reasons"]))

    def test_novelty_alone_is_rejected(self):
        report, _, _, _, _ = self.run_case(
            baseline_correct=False,
            coupled_correct=False,
            baseline_novelty=0.0,
            coupled_novelty=0.99,
        )

        self.assertEqual(report["status"], "rejected")
        self.assertFalse(report["passed"])
        delta = report["aggregates"]["deltas"][CONDITION_DISCONNECTED]
        self.assertEqual(delta["mean_delta"], 0.0)
        self.assertTrue(delta["novelty_without_correctness"])
        self.assertGreater(delta["novelty_delta"], 0.0)
        novelty_check = next(
            check
            for check in report["gate"]["checks"]
            if check["name"] == "novelty_not_sole_evidence"
        )
        self.assertEqual(novelty_check["status"], "fail")
        self.assertIn("novelty", " ".join(report["gate"]["reasons"]))

    def test_missing_native_evidence_is_inconclusive(self):
        report, _, _, _, _ = self.run_case(native_evidence=False)

        self.assertEqual(report["status"], "inconclusive")
        self.assertFalse(report["passed"])
        self.assertFalse(report["native_evidence"]["present"])
        self.assertIsNone(report["native_evidence"]["evidence_digest"])
        self.assertIn(
            "native_evidence_present", " ".join(report["gate"]["reasons"])
        )

    def test_native_coupling_eta_mismatch_blocks_support(self):
        report, _, _, _, _ = self.run_case(
            native_evidence=make_native_evidence(eta=0.05)
        )

        self.assertEqual(report["status"], "rejected")
        self.assertFalse(report["passed"])
        check = next(
            check
            for check in report["gate"]["checks"]
            if check["name"] == "native_coupling_matches_candidate"
        )
        self.assertEqual(check["status"], "fail")
        self.assertIn("evidence eta=0.05", check["detail"])

    def test_seed_instability_is_inconclusive(self):
        report, _, _, _, _ = self.run_case(correct_seeds={0})

        self.assertEqual(report["status"], "inconclusive")
        self.assertFalse(report["passed"])
        delta = report["aggregates"]["deltas"][CONDITION_DISCONNECTED]
        self.assertEqual(delta["mean_delta"], 0.5)
        self.assertFalse(delta["reproducible"])
        self.assertEqual(delta["status"], "inconclusive")
        self.assertEqual(
            [item["mean_delta"] for item in delta["per_seed"]], [1.0, 0.0]
        )
        self.assertIn("not positive for every seed", delta["reason"])

    def test_prediction_mappings_are_accepted_in_direct_and_nested_form(self):
        report, baseline, coupled, _, task_set = self.run_case(
            use_predictions=True
        )
        self.assertEqual(report["status"], "supported")
        self.assertEqual(report["call_counts"]["evaluations"], 72)
        self.assertEqual(report["call_counts"]["prediction_lookups"], 72)
        self.assertEqual(report["call_counts"]["baseline_evaluator_calls"], 0)
        self.assertEqual(report["call_counts"]["coupled_evaluator_calls"], 0)
        self.assertEqual(len(baseline.calls), 0)
        self.assertEqual(len(coupled.calls), 0)

        tasks = task_set.tasks
        answers = answers_for(tasks)
        nested = R7Experiment(self.spec).run(
            task_set,
            baseline_predictions={
                CONDITION_DISCONNECTED: {
                    task.task_id: f"disconnected-{task.task_id}"
                    for task in tasks
                },
                CONDITION_RANDOM: {
                    task.task_id: answers[task.task_id] for task in tasks
                },
            },
            coupled_predictions={
                CANDIDATE_CONDITION: {
                    task.task_id: answers[task.task_id] for task in tasks
                }
            },
            native_evidence=make_native_evidence(),
        )
        disconnected = nested["aggregates"]["conditions"][
            CONDITION_DISCONNECTED
        ]
        random_baseline = nested["aggregates"]["conditions"][CONDITION_RANDOM]
        coupled_aggregate = nested["aggregates"]["conditions"][
            CANDIDATE_CONDITION
        ]
        self.assertEqual(disconnected["match_rate"], 0.0)
        self.assertEqual(random_baseline["match_rate"], 1.0)
        self.assertEqual(coupled_aggregate["match_rate"], 1.0)
        self.assertEqual(
            nested["aggregates"]["deltas"][CONDITION_DISCONNECTED][
                "mean_delta"
            ],
            1.0,
        )
        self.assertEqual(
            nested["aggregates"]["deltas"][CONDITION_RANDOM]["mean_delta"],
            0.0,
        )
        self.assertEqual(nested["status"], "rejected")

    def test_missing_or_ambiguous_evaluator_binding_is_rejected(self):
        task_set = make_task_set()
        harness = R7Experiment(self.spec)
        with self.assertRaises(EvaluatorBindingError):
            harness.run(
                task_set,
                coupled_evaluator=FakeEvaluator(answers_for(make_tasks())),
                native_evidence=make_native_evidence(),
            )
        with self.assertRaises(EvaluatorBindingError):
            harness.run(
                task_set,
                baseline_evaluator=FakeEvaluator(answers_for(make_tasks())),
                native_evidence=make_native_evidence(),
            )
        with self.assertRaises(EvaluatorBindingError):
            harness.run(
                task_set,
                baseline_evaluator=FakeEvaluator(answers_for(make_tasks())),
                baseline_predictions={},
                coupled_evaluator=FakeEvaluator(answers_for(make_tasks())),
            )

    def test_native_evidence_mapping_and_convenience_wrapper(self):
        mapping = {
            "avoided_crossing": {
                "couplings": [0.0, 0.5, 1.0],
                "gaps": [0.0, 1.0, 2.0],
                "source": "caller-avoided-crossing",
                "status": "caller_supplied",
            },
            "phase_coherence": {
                "coherence": 0.75,
                "sample_count": 128,
                "source": "caller-phase",
                "status": "caller_supplied",
            },
            "coupling": {
                "eta": 0.25,
                "source": "caller-coupling",
                "status": "caller_supplied",
            },
            "note": "mapping-unit-test",
        }
        evidence = R7NativeEvidence.from_mapping(mapping)
        self.assertEqual(evidence.phase_coherence.coherence, 0.75)
        self.assertEqual(evidence.coupling.eta, 0.25)
        self.assertEqual(evidence.avoided_crossing.metrics()["max_gap"], 2.0)

        tasks = make_tasks(8)
        answers = answers_for(tasks)
        report = run_r7_experiment(
            make_task_set(tasks),
            spec=self.spec,
            baseline_evaluator=FakeEvaluator(answers, correct=False),
            coupled_evaluator=FakeEvaluator(answers, correct=True),
            native_evidence=mapping,
        )
        self.assertEqual(report["status"], "supported")
        self.assertEqual(
            report["native_evidence"]["phase_metrics"]["coherence"], 0.75
        )

    def test_report_is_reproducible_and_json_serializable(self):
        tasks = make_tasks(12)
        task_set = make_task_set(tasks)
        answers = answers_for(tasks)

        def run_once():
            return R7Experiment(self.spec).run(
                task_set,
                baseline_evaluator=FakeEvaluator(answers, correct=False),
                coupled_evaluator=FakeEvaluator(answers, correct=True),
                native_evidence=make_native_evidence(),
            )

        first = run_once()
        second = run_once()
        self.assertEqual(first, second)
        self.assertEqual(
            json.dumps(first, sort_keys=True),
            json.dumps(second, sort_keys=True),
        )

    def test_missing_and_empty_datasets_are_inconclusive_without_calls(self):
        harness = R7Experiment(self.spec)
        described = harness.describe()
        self.assertEqual(described["schema"], R7_SCHEMA)
        self.assertFalse(described["evaluator_required_for_construction"])
        self.assertEqual(described["evaluator_calls_made"], 0)

        missing = harness.run()
        self.assertEqual(missing["status"], "inconclusive")
        self.assertFalse(missing["passed"])
        self.assertTrue(missing["dataset"]["missing"])
        self.assertIsNone(missing["task_split_digest"])
        self.assertEqual(missing["call_counts"]["evaluations"], 0)
        self.assertEqual(missing["per_task"], [])

        empty_set = R7TaskSet("empty-r7", ())
        empty_baseline = FakeEvaluator({})
        empty_coupled = FakeEvaluator({})
        empty = harness.run(
            empty_set,
            baseline_evaluator=empty_baseline,
            coupled_evaluator=empty_coupled,
            native_evidence=make_native_evidence(),
        )
        self.assertEqual(empty["status"], "inconclusive")
        self.assertFalse(empty["passed"])
        self.assertTrue(empty["dataset"]["missing"])
        self.assertEqual(len(empty["task_split_digest"]), 64)
        self.assertEqual(empty["call_counts"]["evaluations"], 0)
        self.assertEqual(empty["per_task"], [])
        self.assertEqual(empty["aggregates"]["deltas"], {})
        self.assertEqual(len(empty_baseline.calls), 0)
        self.assertEqual(len(empty_coupled.calls), 0)

    def test_invalid_spec_and_native_evidence_are_rejected(self):
        with self.assertRaises(R7ExperimentError):
            R7Experiment(spec=object())
        with self.assertRaises(R7ExperimentError):
            R7Spec(seeds=())
        with self.assertRaises(R7ExperimentError):
            R7Spec(seeds=(1, 1))
        with self.assertRaises(R7ExperimentError):
            R7Spec(min_tasks=1)
        with self.assertRaises(R7ExperimentError):
            R7Spec(min_seeds=1)
        with self.assertRaises(R7ExperimentError):
            R7Spec(candidate_eta=1.5)
        with self.assertRaises(R7ExperimentError):
            R7Prediction("answer", novelty=1.5)

        with self.assertRaises(NativeEvidenceError):
            AvoidedCrossingEvidence(couplings=(0.0, 1.0), gaps=(0.0,))
        with self.assertRaises(NativeEvidenceError):
            AvoidedCrossingEvidence(
                couplings=(0.0, 1.0),
                gaps=(0.0, -1.0),
            )
        with self.assertRaises(NativeEvidenceError):
            PhaseCoherenceEvidence(coherence=1.2)
        with self.assertRaises(NativeEvidenceError):
            CouplingEvidence(eta=-0.1)
        with self.assertRaises(NativeEvidenceError):
            R7NativeEvidence.from_mapping({"avoided_crossing": {}})


if __name__ == "__main__":
    unittest.main()
