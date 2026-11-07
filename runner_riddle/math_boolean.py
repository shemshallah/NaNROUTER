"""Boolean-head experiment gate for ``GAME_PLAN_::`` §13.4 and §20.8 X-15.

A Boolean head is a utility/experiment signal.  It may rank candidates, propose
a rule change, or support a **promotion recommendation**; it may never set
mathematical ``truth``, ``validity``, ``proof``, or ``lifecycle`` state.  This
module is deliberately only a gate:

* the caller supplies :class:`BooleanObservation` records for the candidate
  head, at least :data:`MIN_CONTROL_HEADS` control heads, and a shuffled-label
  baseline;
* every report must contain exactly :data:`REQUIRED_DECISIONS` observations;
* the candidate must be 1,024/1,024 correct, have zero label/feature leakage,
  beat every reported control head, and keep the shuffled baseline at or below
  chance;
* structural defects (missing/short/duplicate observations, invalid labels or
  decisions, mismatched subject IDs, leakage) fail closed with typed errors.

The result is :class:`BooleanHeadGateResult`.  Its ``can_set`` method and
``authority`` evidence field are the machine-checkable non-authority surface:
only ``utility`` and ``experiment_evidence`` can be affected.

No model, dataset, native kernel, proof checker, store, or lifecycle service is
called or mutated here.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

BOOLEAN_HEAD_SCHEMA = "nanrouter.math-boolean-head.v1"
BOOLEAN_HEAD_GATE_SCHEMA = "nanrouter.math-boolean-head-gate.v1"

# X-15 is an exact-count gate.  It is intentionally not configurable.
REQUIRED_DECISIONS = 1024
MIN_CONTROL_HEADS = 6
CHANCE_TOLERANCE = 0.02

STATUS_ELIGIBLE = "eligible"
STATUS_INELIGIBLE = "ineligible"

AUTHORITY_AXES = ("utility", "experiment_evidence")
FORBIDDEN_AXES = ("truth", "validity", "proof", "lifecycle")
_AUTHORITY_EFFECTS = frozenset(AUTHORITY_AXES)

CHECK_PASS = "pass"
CHECK_FAIL = "fail"

LIMITATIONS = (
    "The gate scores caller-supplied decisions and labels; it does not train, "
    "call, or inspect a model or head implementation.",
    "The gate cannot prove the held-out split was never present in training. "
    "Leakage is represented only by the caller-supplied leaked_label and "
    "leaked_feature flags.",
    "Control reports are compared by current accuracy.  The gate cannot prove "
    "a control head was not modified before it was submitted.",
    "The shuffled baseline is one caller-supplied evaluation, not a "
    "distributional significance test.",
    "Eligibility is utility/experiment evidence only.  It cannot set truth, "
    "validity, proof, or lifecycle state and cannot authorize execution.",
    "The result is report-local; it is not persisted and mutates no registry.",
)


class BooleanHeadGateError(ValueError):
    """Base class for Boolean-head contract and gate failures."""


class MissingObservationError(BooleanHeadGateError):
    """A required observation set or control set is absent/empty."""


class ObservationCountError(BooleanHeadGateError):
    """A report does not contain exactly the required number of observations."""


class DuplicateObservationError(BooleanHeadGateError):
    """A subject ID appears more than once in one report."""


class InvalidLabelError(BooleanHeadGateError):
    """A label is not a Boolean."""


class InvalidDecisionError(BooleanHeadGateError):
    """A head decision is not a Boolean."""


class SubjectMismatchError(BooleanHeadGateError):
    """Reports do not cover exactly the same subject IDs."""


class LeakageError(BooleanHeadGateError):
    """A report contains leaked label or feature information."""


class LabelLeakageError(LeakageError):
    """A report contains a leaked label."""


class FeatureLeakageError(LeakageError):
    """A report contains leaked feature information."""


class DuplicateHeadError(BooleanHeadGateError):
    """A head ID is reused across the candidate/control/shuffled reports."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_text(value: Any, name: str, *, maximum: int = 128) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
    ):
        raise BooleanHeadGateError(
            f"{name} must be a non-empty, non-padded string of at most "
            f"{maximum} characters"
        )
    return value


def _require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise BooleanHeadGateError(f"{name} must be a boolean")
    return value


@dataclass(frozen=True)
class BooleanObservation:
    """One Boolean decision for one subject, with explicit leakage flags."""

    subject_id: str
    decision: bool
    label: bool
    leaked_label: bool = False
    leaked_feature: bool = False

    def __post_init__(self) -> None:
        _require_text(self.subject_id, "subject_id")
        if not isinstance(self.decision, bool):
            raise InvalidDecisionError("decision must be a boolean")
        if not isinstance(self.label, bool):
            raise InvalidLabelError("label must be a boolean")
        _require_bool(self.leaked_label, "leaked_label")
        _require_bool(self.leaked_feature, "leaked_feature")

    @property
    def correct(self) -> bool:
        return self.decision is self.label

    @property
    def leaked(self) -> bool:
        return self.leaked_label or self.leaked_feature

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "decision": self.decision,
            "label": self.label,
            "correct": self.correct,
            "leaked_label": self.leaked_label,
            "leaked_feature": self.leaked_feature,
        }


@dataclass(frozen=True)
class BooleanHeadReport:
    """A complete head evaluation as typed observations.

    Observations may be supplied as any sequence; they are stored as a tuple.
    The constructor validates record shapes only.  :meth:`validate` applies the
    exact-count, duplicate, subject-identity, and leakage rules.
    """

    head_id: str
    observations: tuple[BooleanObservation, ...]
    synthetic: bool = False
    provenance: str = ""

    def __post_init__(self) -> None:
        _require_text(self.head_id, "head_id")
        if not isinstance(self.observations, tuple):
            if isinstance(self.observations, Sequence) and not isinstance(
                self.observations, (str, bytes, bytearray)
            ):
                object.__setattr__(
                    self, "observations", tuple(self.observations)
                )
            else:
                raise BooleanHeadGateError(
                    "observations must be a sequence of BooleanObservation"
                )
        for observation in self.observations:
            if not isinstance(observation, BooleanObservation):
                raise BooleanHeadGateError(
                    "observations must contain BooleanObservation instances"
                )
        _require_bool(self.synthetic, "synthetic")
        if not isinstance(self.provenance, str):
            raise BooleanHeadGateError("provenance must be a string")

    @property
    def total(self) -> int:
        return len(self.observations)

    @property
    def correct(self) -> int:
        return sum(1 for observation in self.observations if observation.correct)

    @property
    def accuracy(self) -> float:
        if not self.observations:
            return 0.0
        return self.correct / self.total

    @property
    def leakage_count(self) -> int:
        return sum(
            1 for observation in self.observations if observation.leaked
        )

    @property
    def label_prevalence(self) -> float:
        if not self.observations:
            return 0.0
        positives = sum(1 for observation in self.observations if observation.label)
        return positives / self.total

    @property
    def chance_accuracy(self) -> float:
        """Majority-class accuracy for this report's labels."""
        prevalence = self.label_prevalence
        return max(prevalence, 1.0 - prevalence)

    def validate(self, *, role: str = "head") -> None:
        """Fail closed on missing, short, duplicate, or leaked observations."""
        if not self.observations:
            raise MissingObservationError(
                f"{role} {self.head_id!r} has no observations"
            )
        if self.total != REQUIRED_DECISIONS:
            raise ObservationCountError(
                f"{role} {self.head_id!r} has {self.total} observations; "
                f"exactly {REQUIRED_DECISIONS} are required"
            )
        seen: set[str] = set()
        for observation in self.observations:
            if observation.subject_id in seen:
                raise DuplicateObservationError(
                    f"{role} {self.head_id!r} repeats subject_id "
                    f"{observation.subject_id!r}"
                )
            seen.add(observation.subject_id)
            if observation.leaked_label:
                raise LabelLeakageError(
                    f"{role} {self.head_id!r} has a leaked label for subject "
                    f"{observation.subject_id!r}"
                )
            if observation.leaked_feature:
                raise FeatureLeakageError(
                    f"{role} {self.head_id!r} has a leaked feature for subject "
                    f"{observation.subject_id!r}"
                )

    def subject_ids(self) -> frozenset[str]:
        return frozenset(
            observation.subject_id for observation in self.observations
        )

    def digest(self) -> str:
        return _sha256_json(
            {
                "schema": BOOLEAN_HEAD_SCHEMA,
                "head_id": self.head_id,
                "synthetic": self.synthetic,
                "provenance": self.provenance,
                "observations": [
                    observation.to_dict()
                    for observation in sorted(
                        self.observations,
                        key=lambda item: item.subject_id,
                    )
                ],
            }
        )

    def to_evidence(self) -> dict[str, Any]:
        return {
            "schema": BOOLEAN_HEAD_SCHEMA,
            "head_id": self.head_id,
            "report_digest": self.digest(),
            "synthetic": self.synthetic,
            "provenance": self.provenance,
            "total": self.total,
            "correct": self.correct,
            "accuracy": round(self.accuracy, 12),
            "leakage": self.leakage_count,
            "label_prevalence": round(self.label_prevalence, 12),
            "chance_accuracy": round(self.chance_accuracy, 12),
        }


@dataclass(frozen=True)
class BooleanHeadGateResult:
    """Utility-only gate result; never a mathematical authority record."""

    head: BooleanHeadReport
    control_heads: tuple[BooleanHeadReport, ...]
    shuffled_baseline: BooleanHeadReport
    checks: tuple[dict[str, Any], ...]
    reasons: tuple[str, ...]
    eligible: bool

    @property
    def status(self) -> str:
        return STATUS_ELIGIBLE if self.eligible else STATUS_INELIGIBLE

    @property
    def max_control_accuracy(self) -> float:
        if not self.control_heads:
            return 0.0
        return max(control.accuracy for control in self.control_heads)

    @property
    def authority_axes(self) -> tuple[str, ...]:
        return AUTHORITY_AXES

    @property
    def forbidden_axes(self) -> tuple[str, ...]:
        return FORBIDDEN_AXES

    def can_set(self, axis: str) -> bool:
        """Return True only for the utility/experiment evidence axes.

        Every forbidden or unknown axis is denied by default.  This is the
        callable proof that a gate result cannot set truth, validity, proof, or
        lifecycle state.
        """
        if not isinstance(axis, str):
            return False
        return axis.strip().casefold() in _AUTHORITY_EFFECTS

    def authority(self) -> dict[str, Any]:
        """Machine-readable non-authority declaration."""
        return {
            "mode": "utility_experiment_only",
            "affects": list(AUTHORITY_AXES),
            "forbidden": list(FORBIDDEN_AXES),
            "can_set_truth": False,
            "can_set_validity": False,
            "can_set_proof": False,
            "can_set_lifecycle": False,
            "can_promote_rule": False,
            "can_execute_candidate": False,
            "requires_separate_proof_checker": True,
            "requires_separate_lifecycle_protocol": True,
            "note": (
                "Eligibility is an experiment recommendation only. It cannot "
                "set mathematical validity, truth, proof, or lifecycle state."
            ),
        }

    def to_evidence(self) -> dict[str, Any]:
        return {
            "schema": BOOLEAN_HEAD_GATE_SCHEMA,
            "mode": "utility_experiment_only",
            "status": self.status,
            "eligible": self.eligible,
            "eligible_for_experiment": self.eligible,
            "eligible_for_promotion_recommendation": self.eligible,
            "required_decisions": REQUIRED_DECISIONS,
            "head": self.head.to_evidence(),
            "control_heads": [
                control.to_evidence() for control in self.control_heads
            ],
            "shuffled_baseline": self.shuffled_baseline.to_evidence(),
            "comparison": {
                "minimum_control_heads": MIN_CONTROL_HEADS,
                "control_head_count": len(self.control_heads),
                "max_control_accuracy": round(
                    self.max_control_accuracy, 12
                ),
                "head_beats_all_control_heads": (
                    self.head.accuracy > self.max_control_accuracy
                ),
                "shuffled_baseline_accuracy": round(
                    self.shuffled_baseline.accuracy, 12
                ),
                "chance_accuracy": round(self.head.chance_accuracy, 12),
                "chance_tolerance": CHANCE_TOLERANCE,
                "head_beats_chance": (
                    self.head.accuracy > self.head.chance_accuracy
                ),
                "shuffled_baseline_at_or_below_chance": (
                    self.shuffled_baseline.accuracy
                    <= self.head.chance_accuracy + CHANCE_TOLERANCE
                ),
            },
            "checks": [dict(check) for check in self.checks],
            "reasons": list(self.reasons),
            "authority": self.authority(),
            "limitations": list(LIMITATIONS),
        }


class BooleanHeadGate:
    """Apply the X-15 Boolean-head eligibility gate.

    The gate is stateless and does not retain caller data.  Structural defects
    raise typed :class:`BooleanHeadGateError` subclasses; a structurally valid
    but insufficient result returns ``eligible=False`` with explicit reasons.
    """

    required_decisions = REQUIRED_DECISIONS
    min_control_heads = MIN_CONTROL_HEADS
    chance_tolerance = CHANCE_TOLERANCE

    def evaluate(
        self,
        head: BooleanHeadReport,
        *,
        control_heads: Sequence[BooleanHeadReport],
        shuffled_baseline: BooleanHeadReport,
    ) -> BooleanHeadGateResult:
        if not isinstance(head, BooleanHeadReport):
            raise BooleanHeadGateError(
                "head must be a BooleanHeadReport"
            )
        if not isinstance(shuffled_baseline, BooleanHeadReport):
            raise BooleanHeadGateError(
                "shuffled_baseline must be a BooleanHeadReport"
            )
        if isinstance(control_heads, BooleanHeadReport):
            controls = (control_heads,)
        elif control_heads is None:
            raise MissingObservationError(
                "at least one control head report is required"
            )
        else:
            controls = tuple(control_heads)
        if not controls:
            raise MissingObservationError(
                "at least one control head report is required"
            )

        head.validate(role="head")
        for control in controls:
            if not isinstance(control, BooleanHeadReport):
                raise BooleanHeadGateError(
                    "control_heads must contain BooleanHeadReport instances"
                )
            control.validate(role="control head")
        shuffled_baseline.validate(role="shuffled baseline")

        head_ids = {report.head_id for report in controls}
        head_ids.add(head.head_id)
        if shuffled_baseline.head_id in head_ids:
            raise DuplicateHeadError(
                f"duplicate head_id {shuffled_baseline.head_id!r}"
            )
        if len(head_ids) != len(controls) + 1:
            raise DuplicateHeadError("control head IDs must be unique")

        head_subjects = head.subject_ids()
        for report in (*controls, shuffled_baseline):
            _require_same_subjects(head_subjects, report)

        checks: list[dict[str, Any]] = []

        def add(name: str, passed: bool, detail: str) -> None:
            checks.append(
                {
                    "name": name,
                    "status": CHECK_PASS if passed else CHECK_FAIL,
                    "detail": detail,
                }
            )

        add(
            "exact_decision_count",
            head.total == REQUIRED_DECISIONS,
            f"{head.total}/{REQUIRED_DECISIONS} candidate observations",
        )
        add(
            "all_decisions_correct",
            head.correct == REQUIRED_DECISIONS,
            f"{head.correct}/{REQUIRED_DECISIONS} correct",
        )
        add(
            "leakage_zero",
            head.leakage_count == 0,
            f"{head.leakage_count} leaked labels/features",
        )
        add(
            "not_synthetic",
            not head.synthetic,
            f"synthetic={head.synthetic}",
        )
        add(
            "minimum_control_heads",
            len(controls) >= MIN_CONTROL_HEADS,
            f"{len(controls)} control heads; minimum {MIN_CONTROL_HEADS}",
        )
        max_control_accuracy = max(control.accuracy for control in controls)
        add(
            "beats_all_control_heads",
            head.accuracy > max_control_accuracy,
            f"head accuracy {head.accuracy:.6f}; best control "
            f"{max_control_accuracy:.6f}",
        )
        chance_accuracy = head.chance_accuracy
        add(
            "head_above_chance",
            head.accuracy > chance_accuracy,
            f"head accuracy {head.accuracy:.6f}; majority-class chance "
            f"{chance_accuracy:.6f}",
        )
        shuffled_accuracy = shuffled_baseline.accuracy
        add(
            "shuffled_baseline_at_chance",
            shuffled_accuracy <= chance_accuracy + CHANCE_TOLERANCE,
            f"shuffled accuracy {shuffled_accuracy:.6f}; chance "
            f"{chance_accuracy:.6f} + tolerance {CHANCE_TOLERANCE:.6f}",
        )

        eligible = all(check["status"] == CHECK_PASS for check in checks)
        reasons = tuple(
            f"{check['name']}: {check['detail']}"
            for check in checks
            if check["status"] != CHECK_PASS
        )
        return BooleanHeadGateResult(
            head=head,
            control_heads=controls,
            shuffled_baseline=shuffled_baseline,
            checks=tuple(checks),
            reasons=reasons,
            eligible=eligible,
        )


def _require_same_subjects(
    expected: frozenset[str], report: BooleanHeadReport
) -> None:
    actual = report.subject_ids()
    if actual == expected:
        return
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    raise SubjectMismatchError(
        f"report {report.head_id!r} subject IDs do not match the candidate "
        f"head; missing={missing[:5]}{'...' if len(missing) > 5 else ''}, "
        f"extra={extra[:5]}{'...' if len(extra) > 5 else ''}"
    )


def evaluate_boolean_head(
    head: BooleanHeadReport,
    *,
    control_heads: Sequence[BooleanHeadReport],
    shuffled_baseline: BooleanHeadReport,
) -> BooleanHeadGateResult:
    """Convenience wrapper around :class:`BooleanHeadGate`."""
    return BooleanHeadGate().evaluate(
        head,
        control_heads=control_heads,
        shuffled_baseline=shuffled_baseline,
    )
