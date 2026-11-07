from __future__ import annotations

import json
import unittest

from runner_riddle.math_boolean import (
    BOOLEAN_HEAD_GATE_SCHEMA,
    FORBIDDEN_AXES,
    MIN_CONTROL_HEADS,
    REQUIRED_DECISIONS,
    BooleanHeadGate,
    BooleanHeadGateError,
    BooleanHeadReport,
    BooleanObservation,
    DuplicateObservationError,
    FeatureLeakageError,
    InvalidDecisionError,
    InvalidLabelError,
    LabelLeakageError,
    MissingObservationError,
    ObservationCountError,
    SubjectMismatchError,
    evaluate_boolean_head,
)


def make_report(
    head_id: str,
    *,
    correct: int = REQUIRED_DECISIONS,
    subject_offset: int = 0,
    all_labels_true: bool = False,
    leaked_label: bool = False,
    leaked_feature: bool = False,
    duplicate_subject: bool = False,
    synthetic: bool = False,
) -> BooleanHeadReport:
    observations = []
    for index in range(REQUIRED_DECISIONS):
        label = True if all_labels_true else index % 2 == 0
        decision = label if index < correct else not label
        subject_id = f"s{index + subject_offset:05d}"
        if duplicate_subject and index == 1:
            subject_id = f"s{subject_offset:05d}"
        observations.append(
            BooleanObservation(
                subject_id=subject_id,
                decision=decision,
                label=label,
                leaked_label=leaked_label and index == 0,
                leaked_feature=leaked_feature and index == 0,
            )
        )
    return BooleanHeadReport(
        head_id=head_id,
        observations=tuple(observations),
        synthetic=synthetic,
        provenance="unit-test",
    )


def constant_report(
    head_id: str, *, decision: bool = True
) -> BooleanHeadReport:
    """Every decision is ``decision``; balanced labels give 50% accuracy."""
    return BooleanHeadReport(
        head_id=head_id,
        observations=tuple(
            BooleanObservation(
                subject_id=f"s{index:05d}",
                decision=decision,
                label=index % 2 == 0,
            )
            for index in range(REQUIRED_DECISIONS)
        ),
        provenance="unit-test",
    )


def controls(*, correct: int = 512, count: int = MIN_CONTROL_HEADS):
    return tuple(
        make_report(f"control-{index}", correct=correct)
        for index in range(count)
    )


class BooleanHeadGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gate = BooleanHeadGate()
        self.head = make_report("candidate-head")
        self.shuffled = constant_report("shuffled-labels")
        self.controls = controls()

    def evaluate(self, head=None, control_heads=None, shuffled=None):
        return self.gate.evaluate(
            head or self.head,
            control_heads=(
                self.controls if control_heads is None else control_heads
            ),
            shuffled_baseline=self.shuffled if shuffled is None else shuffled,
        )

    def test_perfect_head_is_eligible_and_reports_all_comparisons(self):
        result = self.evaluate()
        evidence = result.to_evidence()

        self.assertTrue(result.eligible)
        self.assertEqual(evidence["status"], "eligible")
        self.assertEqual(evidence["schema"], BOOLEAN_HEAD_GATE_SCHEMA)
        self.assertEqual(evidence["required_decisions"], REQUIRED_DECISIONS)
        self.assertEqual(evidence["head"]["correct"], REQUIRED_DECISIONS)
        self.assertEqual(evidence["head"]["total"], REQUIRED_DECISIONS)
        self.assertEqual(evidence["head"]["accuracy"], 1.0)
        self.assertEqual(evidence["head"]["leakage"], 0)
        self.assertEqual(len(evidence["control_heads"]), MIN_CONTROL_HEADS)
        self.assertEqual(
            [control["head_id"] for control in evidence["control_heads"]],
            [f"control-{index}" for index in range(MIN_CONTROL_HEADS)],
        )
        self.assertEqual(
            evidence["comparison"]["max_control_accuracy"], 0.5
        )
        self.assertEqual(
            evidence["comparison"]["shuffled_baseline_accuracy"], 0.5
        )
        self.assertEqual(evidence["comparison"]["chance_accuracy"], 0.5)
        self.assertTrue(
            evidence["comparison"]["head_beats_all_control_heads"]
        )
        self.assertTrue(evidence["comparison"]["head_beats_chance"])
        self.assertTrue(
            evidence["comparison"]["shuffled_baseline_at_or_below_chance"]
        )
        self.assertEqual(evidence["reasons"], [])
        self.assertTrue(
            all(check["status"] == "pass" for check in evidence["checks"])
        )
        json.dumps(evidence)
        self.assertEqual(result.head.digest(), self.head.digest())

    def test_missing_and_short_observations_fail_closed(self):
        with self.assertRaises(MissingObservationError):
            self.evaluate(head=BooleanHeadReport("empty-head", ()))

        short = BooleanHeadReport(
            "short-head", self.head.observations[: REQUIRED_DECISIONS - 1]
        )
        with self.assertRaises(ObservationCountError):
            self.evaluate(head=short)

        long = BooleanHeadReport(
            "long-head",
            self.head.observations
            + (BooleanObservation("extra-subject", True, True),),
        )
        with self.assertRaises(ObservationCountError):
            self.evaluate(head=long)

    def test_duplicate_subject_ids_fail_closed(self):
        duplicate = make_report("duplicate-head", duplicate_subject=True)
        with self.assertRaises(DuplicateObservationError):
            self.evaluate(head=duplicate)

        with self.assertRaises(DuplicateObservationError):
            self.evaluate(head=self.head, control_heads=(
                make_report("duplicate-control", duplicate_subject=True),
            ))

    def test_invalid_labels_and_decisions_fail_closed(self):
        for label in (1, 0, "true", None):
            with self.subTest(label=label):
                with self.assertRaises(InvalidLabelError):
                    BooleanObservation("s00000", True, label)
        for decision in (1, 0, "true", None):
            with self.subTest(decision=decision):
                with self.assertRaises(InvalidDecisionError):
                    BooleanObservation("s00000", decision, True)

    def test_mismatched_subject_ids_fail_closed(self):
        offset_control = make_report(
            "offset-control", correct=512, subject_offset=1
        )
        with self.assertRaises(SubjectMismatchError):
            self.evaluate(control_heads=(offset_control,))

        offset_shuffled = constant_report("offset-shuffled")
        shifted = tuple(
            BooleanObservation(
                f"s{index + 1:05d}",
                observation.decision,
                observation.label,
            )
            for index, observation in enumerate(
                offset_shuffled.observations[:-1]
            )
        ) + (BooleanObservation("s99999", True, True),)
        with self.assertRaises(SubjectMismatchError):
            self.evaluate(
                shuffled=BooleanHeadReport("offset-shuffled", shifted)
            )

    def test_any_label_or_feature_leakage_rejects(self):
        with self.assertRaises(LabelLeakageError):
            self.evaluate(head=make_report("leaky-label", leaked_label=True))
        with self.assertRaises(FeatureLeakageError):
            self.evaluate(
                head=make_report("leaky-feature", leaked_feature=True)
            )
        with self.assertRaises(LabelLeakageError):
            self.evaluate(control_heads=(
                make_report("leaky-control", correct=512, leaked_label=True),
            ))

    def test_head_at_or_below_control_is_ineligible(self):
        equal_controls = controls(correct=REQUIRED_DECISIONS)
        result = self.evaluate(control_heads=equal_controls)

        self.assertFalse(result.eligible)
        self.assertEqual(result.status, "ineligible")
        self.assertFalse(
            result.to_evidence()["eligible_for_experiment"]
        )
        self.assertFalse(
            result.to_evidence()["eligible_for_promotion_recommendation"]
        )
        self.assertIn(
            "beats_all_control_heads",
            " ".join(result.reasons),
        )

        imperfect = make_report("imperfect-head", correct=REQUIRED_DECISIONS - 1)
        result = self.evaluate(head=imperfect)
        self.assertFalse(result.eligible)
        self.assertIn("all_decisions_correct", " ".join(result.reasons))

    def test_shuffled_baseline_above_chance_and_fewer_controls_are_ineligible(self):
        high_shuffled = make_report("high-shuffled", correct=800)
        result = self.evaluate(shuffled=high_shuffled)
        self.assertFalse(result.eligible)
        self.assertIn(
            "shuffled_baseline_at_chance", " ".join(result.reasons)
        )
        self.assertGreater(
            result.to_evidence()["comparison"][
                "shuffled_baseline_accuracy"
            ],
            result.to_evidence()["comparison"]["chance_accuracy"],
        )

        result = self.evaluate(control_heads=controls(count=MIN_CONTROL_HEADS - 1))
        self.assertFalse(result.eligible)
        self.assertIn("minimum_control_heads", " ".join(result.reasons))
        self.assertEqual(
            result.to_evidence()["comparison"]["control_head_count"],
            MIN_CONTROL_HEADS - 1,
        )

    def test_utility_only_authority_surface_is_explicit(self):
        result = self.evaluate()
        evidence = result.to_evidence()
        authority = evidence["authority"]

        self.assertEqual(evidence["mode"], "utility_experiment_only")
        self.assertEqual(authority["mode"], "utility_experiment_only")
        self.assertEqual(authority["affects"], ["utility", "experiment_evidence"])
        self.assertEqual(
            list(FORBIDDEN_AXES),
            ["truth", "validity", "proof", "lifecycle"],
        )
        for axis in FORBIDDEN_AXES:
            with self.subTest(axis=axis):
                self.assertFalse(result.can_set(axis))
                self.assertFalse(authority[f"can_set_{axis}"])
        self.assertFalse(result.can_set("unknown-axis"))
        self.assertFalse(result.can_set(None))
        self.assertTrue(result.can_set("utility"))
        self.assertTrue(result.can_set("experiment_evidence"))
        self.assertFalse(authority["can_promote_rule"])
        self.assertFalse(authority["can_execute_candidate"])
        for forbidden_key in (
            "truth_status",
            "validity_level",
            "proof_status",
            "lifecycle_state",
        ):
            self.assertNotIn(forbidden_key, evidence)
        json.dumps(evidence)

    def test_wrapper_matches_gate_and_rejects_bad_arguments(self):
        via_wrapper = evaluate_boolean_head(
            self.head,
            control_heads=self.controls,
            shuffled_baseline=self.shuffled,
        )
        self.assertTrue(via_wrapper.eligible)
        self.assertEqual(
            via_wrapper.to_evidence(), self.evaluate().to_evidence()
        )

        with self.assertRaises(BooleanHeadGateError):
            self.gate.evaluate(
                object(),
                control_heads=self.controls,
                shuffled_baseline=self.shuffled,
            )
        with self.assertRaises(MissingObservationError):
            self.evaluate(control_heads=())


if __name__ == "__main__":
    unittest.main()
