"""R7 held-out creativity/association experiment control plane.

This module is an evidence harness, not a model and not a creativity claim.  It
schedules caller-supplied baseline and coupled evaluators (or caller-supplied
prediction mappings) over a deterministic held-out association task set.  It
scores returned strings, computes paired deltas with a deterministic paired
bootstrap interval and a sign-flip permutation p-value, and gates the result to
``supported``, ``rejected``, or ``inconclusive``.

The harness never encodes a prompt, applies a coupling matrix, computes an
eigenvalue, predicts an answer, or calls a network or native process.  Native
evidence is accepted as validated caller data:

* an avoided-crossing sweep record (couplings, gaps, and optional eigenvalues);
* a phase-coherence record (the 128-sample coherence ratio ``R``); and
* a coupling record (``eta``).

Simple descriptive statistics over those supplied scalars are recorded.  No
matrix or eigensolver mathematics is performed here.

Novelty is never sufficient evidence.  A result can only be ``supported`` if the
coupled candidate improves held-out correctness over every required baseline
and the full set of controls and evidence checks passes.  Nothing here proves
creativity, consciousness, quantum tunneling, or general capability.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

R7_SCHEMA = "nanrouter.r7-experiment.v1"
R7_SPLIT_SCHEMA = "nanrouter.r7-split.v1"
R7_NATIVE_SCHEMA = "nanrouter.r7-native-evidence.v1"
HARNESS_VERSION = 1

HELDOUT_SPLIT = "heldout"

CONDITION_DISCONNECTED = "disconnected"
CONDITION_RANDOM = "random_coupling"
CONDITION_COUPLED = "coupled"
BASELINE_CONDITIONS = (CONDITION_DISCONNECTED, CONDITION_RANDOM)
CANDIDATE_CONDITION = CONDITION_COUPLED
CONDITIONS = (*BASELINE_CONDITIONS, CANDIDATE_CONDITION)

STATUS_SUPPORTED = "supported"
STATUS_REJECTED = "rejected"
STATUS_INCONCLUSIVE = "inconclusive"

CHECK_PASS = "pass"
CHECK_FAIL = "fail"
CHECK_INCONCLUSIVE = "inconclusive"

NATIVE_EVIDENCE_STATUSES = (
    "native_verified",
    "fixture_pass",
    "pass",
    "caller_supplied",
)

AVOIDED_CROSSING_MARKER = "MTH AVOIDED CROSSING SWEEP PASS"
PHASE_COHERENCE_MARKER = "MTH PHASE COHERENCE 128 PASS"
COUPLING_MARKER = "MTH GRAPH COUPLE 128 PASS"

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

LIMITATIONS = (
    "No model is implemented, bundled, or called. Baseline and coupled "
    "evaluators/predictions are entirely caller-supplied.",
    "No coupling matrix, eigenvalue, phase phasor, or native process is "
    "computed here. Native records are caller data, not independently "
    "verified by this harness.",
    "The harness cannot prove the candidate evaluator was trained without the "
    "held-out prompts or answers. Dataset hygiene depends on caller provenance.",
    "The bootstrap interval and permutation test resample the supplied held-out "
    "tasks only. They do not establish generalization to other tasks, datasets, "
    "or models.",
    "Synthetic, missing, or underpowered datasets are never admissible support.",
    "Novelty, usefulness, diversity, latency, and energy are recorded only when "
    "the caller supplies them; none can substitute for held-out correctness.",
    "A supported result is report-local. It is not persisted, does not mutate "
    "any registry, and is not a creativity, intelligence, consciousness, or "
    "quantum-tunneling claim.",
    "Multiple baseline comparisons are reported individually; the caller must "
    "apply any family-wise correction for a broader claim.",
    "Only the disconnected and random-coupling baselines are scheduled. The "
    "shuffled-geometry (S1) and phase-scrambled (P1) controls in the R7 "
    "protocol are not implemented by this runner.",
    "The harness cannot verify that the random baseline is topology- or "
    "norm-matched, or that the candidate and baselines are compute-matched.",
)

CLAIM_SCOPE = {
    "scope": "held-out association-task match rate under caller-supplied hooks",
    "creativity_claim": False,
    "tunneling_claim": False,
    "generalization_claim": False,
    "note": (
        "supported means only that this held-out task set, baseline matrix, "
        "native evidence record, and seeded protocol met the gate. It is not "
        "a creativity or physical-tunneling claim."
    ),
}


class R7ExperimentError(ValueError):
    """Base class for R7 contract, evidence, and evaluator failures."""


class SplitLeakageError(R7ExperimentError):
    """A task belongs to the held-out split incorrectly or leaks train data."""


class DuplicateTaskError(R7ExperimentError):
    """A task ID or normalized prompt appears more than once."""


class EvaluatorBindingError(R7ExperimentError):
    """A baseline/coupled evaluator or prediction source is missing or invalid."""


class EvaluatorHookError(R7ExperimentError):
    """A caller-supplied evaluator failed or returned a bad type."""


class NativeEvidenceError(R7ExperimentError):
    """A caller-supplied native evidence record is malformed."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_text(_canonical_json(value))


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().split()).casefold()


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        raise ValueError("percentile requires at least one value")
    if q <= 0.0:
        return sorted_values[0]
    if q >= 1.0:
        return sorted_values[-1]
    position = (len(sorted_values) - 1) * q
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return (
        sorted_values[lower]
        + (sorted_values[upper] - sorted_values[lower]) * fraction
    )


def _paired_bootstrap_ci(
    values: list[float],
    *,
    samples: int,
    confidence: float,
    seed: int,
) -> tuple[float | None, float | None]:
    """Return a deterministic percentile bootstrap CI for the paired mean."""
    if len(values) < 2:
        return None, None
    rng = random.Random(seed)
    n = len(values)
    means: list[float] = []
    for _ in range(samples):
        total = 0.0
        for _ in range(n):
            total += values[rng.randrange(n)]
        means.append(total / n)
    means.sort()
    alpha = (1.0 - confidence) / 2.0
    return (
        round(_percentile(means, alpha), 12),
        round(_percentile(means, 1.0 - alpha), 12),
    )


def _sign_flip_permutation_p(
    values: list[float],
    *,
    samples: int,
    seed: int,
) -> float | None:
    """Return a deterministic two-sided paired sign-flip permutation p-value."""
    if len(values) < 2:
        return None
    observed = abs(_mean(values))
    rng = random.Random(seed)
    hits = 0
    n = len(values)
    for _ in range(samples):
        signed_mean = sum(
            value if rng.random() < 0.5 else -value for value in values
        ) / n
        if abs(signed_mean) >= observed - 1e-15:
            hits += 1
    # Add-one smoothing keeps a Monte Carlo p-value strictly positive.
    return round((hits + 1) / (samples + 1), 12)


def _require_text(
    value: Any,
    name: str,
    *,
    maximum: int = 256,
    error_cls: type[R7ExperimentError] = R7ExperimentError,
) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum
    ):
        raise error_cls(
            f"{name} must be a non-empty string of at most {maximum} characters"
        )
    return value


def _require_int(
    value: Any,
    name: str,
    *,
    minimum: int = 0,
    error_cls: type[R7ExperimentError] = R7ExperimentError,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise error_cls(f"{name} must be an integer >= {minimum}")
    return value


def _require_number(
    value: Any,
    name: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    error_cls: type[R7ExperimentError] = R7ExperimentError,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise error_cls(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise error_cls(f"{name} must be a finite number")
    if minimum is not None and number < minimum:
        raise error_cls(f"{name} must be >= {minimum}")
    if maximum is not None and number > maximum:
        raise error_cls(f"{name} must be <= {maximum}")
    return number


def _optional_score(value: Any, name: str) -> float | None:
    if value is None:
        return None
    return _require_number(value, name, minimum=0.0, maximum=1.0)


def _float_tuple(
    value: Any,
    name: str,
    *,
    maximum_length: int | None = None,
    error_cls: type[R7ExperimentError] = NativeEvidenceError,
) -> tuple[float, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value, Sequence
    ):
        raise error_cls(f"{name} must be a sequence of finite numbers")
    result: list[float] = []
    for item in value:
        result.append(_require_number(item, name, error_cls=error_cls))
    if not result:
        raise error_cls(f"{name} cannot be empty")
    if maximum_length is not None and len(result) > maximum_length:
        raise error_cls(
            f"{name} has {len(result)} entries; maximum is {maximum_length}"
        )
    return tuple(result)


def _get_alias(
    value: Mapping[str, Any],
    names: tuple[str, ...],
    field: str,
    *,
    error_cls: type[R7ExperimentError] = NativeEvidenceError,
) -> Any:
    for name in names:
        if name in value:
            return value[name]
    raise error_cls(f"{field} is required (accepted keys: {', '.join(names)})")


def _accepted_answers(task: "R7Task") -> tuple[str, ...]:
    expected = task.expected
    if isinstance(expected, str):
        values: tuple[Any, ...] = (expected,)
    elif isinstance(expected, (tuple, list)):
        values = tuple(expected)
    else:
        raise R7ExperimentError(
            "R7Task.expected must be a string or a tuple of strings"
        )
    if not values:
        raise R7ExperimentError("R7Task.expected cannot be empty")
    result: list[str] = []
    for item in values:
        if not isinstance(item, str) or not item.strip():
            raise R7ExperimentError(
                "R7Task.expected entries must be non-empty strings"
            )
        result.append(item)
    return tuple(result)


def _validate_task_identity(task: "R7Task") -> None:
    _require_text(task.task_id, "R7Task.task_id", maximum=128)
    if not isinstance(task.prompt, str) or not task.prompt.strip():
        raise R7ExperimentError("R7Task.prompt cannot be empty")
    if not isinstance(task.task_family, str) or not task.task_family.strip():
        raise R7ExperimentError("R7Task.task_family cannot be empty")
    _accepted_answers(task)


def _score_prediction(
    prediction: "R7Prediction", accepted: tuple[str, ...]
) -> dict[str, Any]:
    """Score one caller-supplied prediction; no model work is performed."""
    text = prediction.text
    exact = any(text.strip() == answer.strip() for answer in accepted)
    normalized_prediction = _normalize_text(text)
    matched_answer: str | None = None
    match = False
    for answer in accepted:
        if normalized_prediction == _normalize_text(answer):
            match = True
            matched_answer = answer
            break

    if exact:
        token_match = 1.0
    else:
        prediction_tokens = set(_TOKEN_RE.findall(normalized_prediction))
        best = 0.0
        for answer in accepted:
            answer_tokens = set(_TOKEN_RE.findall(_normalize_text(answer)))
            if not answer_tokens:
                continue
            overlap = len(prediction_tokens & answer_tokens)
            best = max(best, overlap / len(answer_tokens))
        token_match = round(best, 12)

    return {
        "prediction": text,
        "exact": exact,
        "match": match,
        "token_match": token_match,
        "matched_answer": matched_answer,
        "novelty": prediction.novelty,
        "usefulness": prediction.usefulness,
    }


def _match_delta(
    treatment: Mapping[str, Any], control: Mapping[str, Any]
) -> float:
    return float(bool(treatment["match"])) - float(bool(control["match"]))


def _ids(record: Any) -> str | None:
    for name in ("evaluator_id", "model_id", "kernel_id", "__name__"):
        value = getattr(record, name, None)
        if isinstance(value, str) and value:
            return value
    return None


@dataclass(frozen=True)
class R7Task:
    """One held-out association task with one or more accepted answers."""

    task_id: str
    prompt: str
    expected: str | tuple[str, ...]
    split: str = HELDOUT_SPLIT
    task_family: str = "association"

    def __post_init__(self) -> None:
        if isinstance(self.expected, list):
            object.__setattr__(self, "expected", tuple(self.expected))

    def accepted_answers(self) -> tuple[str, ...]:
        return _accepted_answers(self)


@dataclass(frozen=True)
class R7TaskSet:
    """A held-out split plus caller-declared non-held-out (train/dev) material.

    ``excluded_tasks`` are never evaluated.  They exist so the harness can
    reject task-ID or normalized-prompt leakage from train/dev material into the
    held-out split.
    """

    dataset_id: str
    tasks: tuple[R7Task, ...]
    excluded_tasks: tuple[R7Task, ...] = ()
    synthetic: bool = False
    provenance: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.tasks, tuple):
            object.__setattr__(self, "tasks", tuple(self.tasks))
        if not isinstance(self.excluded_tasks, tuple):
            object.__setattr__(
                self, "excluded_tasks", tuple(self.excluded_tasks)
            )
        self.validate()

    def validate(self) -> None:
        _require_text(self.dataset_id, "dataset_id", maximum=128)
        if not isinstance(self.synthetic, bool):
            raise R7ExperimentError("synthetic must be a boolean")
        if not isinstance(self.provenance, str):
            raise R7ExperimentError("provenance must be a string")

        heldout_ids: set[str] = set()
        heldout_prompts: set[str] = set()
        for task in self.tasks:
            if not isinstance(task, R7Task):
                raise R7ExperimentError("tasks must contain R7Task instances")
            _validate_task_identity(task)
            if task.split != HELDOUT_SPLIT:
                raise SplitLeakageError(
                    f"task {task.task_id!r} has split {task.split!r}; "
                    f"only {HELDOUT_SPLIT!r} tasks may be evaluated"
                )
            normalized_prompt = _normalize_text(task.prompt)
            if task.task_id in heldout_ids:
                raise DuplicateTaskError(
                    f"duplicate held-out task_id: {task.task_id!r}"
                )
            if normalized_prompt in heldout_prompts:
                raise DuplicateTaskError(
                    "duplicate held-out prompt after normalization: "
                    f"{task.prompt!r}"
                )
            heldout_ids.add(task.task_id)
            heldout_prompts.add(normalized_prompt)

        excluded_ids: set[str] = set()
        excluded_prompts: set[str] = set()
        for task in self.excluded_tasks:
            if not isinstance(task, R7Task):
                raise R7ExperimentError(
                    "excluded_tasks must contain R7Task instances"
                )
            _validate_task_identity(task)
            if task.split == HELDOUT_SPLIT:
                raise SplitLeakageError(
                    "excluded task is marked as held-out: "
                    f"{task.task_id!r}"
                )
            if not isinstance(task.split, str) or not task.split.strip():
                raise R7ExperimentError(
                    f"excluded task {task.task_id!r} must declare a non-empty "
                    "non-held-out split such as 'train' or 'dev'"
                )
            normalized_prompt = _normalize_text(task.prompt)
            if task.task_id in excluded_ids:
                raise DuplicateTaskError(
                    f"duplicate excluded task_id: {task.task_id!r}"
                )
            if normalized_prompt in excluded_prompts:
                raise DuplicateTaskError(
                    "duplicate excluded prompt after normalization: "
                    f"{task.prompt!r}"
                )
            if task.task_id in heldout_ids:
                raise SplitLeakageError(
                    "excluded task_id leaks into the held-out split: "
                    f"{task.task_id!r}"
                )
            if normalized_prompt in heldout_prompts:
                raise SplitLeakageError(
                    "excluded prompt leaks into the held-out split: "
                    f"{task.prompt!r}"
                )
            excluded_ids.add(task.task_id)
            excluded_prompts.add(normalized_prompt)

    @property
    def train_tasks(self) -> tuple[R7Task, ...]:
        """Alias for the caller-declared non-held-out material."""
        return self.excluded_tasks

    def split_digest(self) -> str:
        self.validate()
        payload = {
            "schema": R7_SPLIT_SCHEMA,
            "dataset_id": self.dataset_id,
            "synthetic": self.synthetic,
            "provenance": self.provenance,
            "tasks": [
                {
                    "task_id": task.task_id,
                    "prompt": _normalize_text(task.prompt),
                    "expected": sorted(
                        _normalize_text(answer)
                        for answer in task.accepted_answers()
                    ),
                    "split": task.split,
                    "task_family": task.task_family,
                }
                for task in sorted(self.tasks, key=lambda item: item.task_id)
            ],
            "excluded_tasks": [
                {
                    "task_id": task.task_id,
                    "prompt": _normalize_text(task.prompt),
                    "expected": sorted(
                        _normalize_text(answer)
                        for answer in task.accepted_answers()
                    ),
                    "split": task.split,
                    "task_family": task.task_family,
                }
                for task in sorted(
                    self.excluded_tasks, key=lambda item: item.task_id
                )
            ],
        }
        return _sha256_json(payload)

    def to_evidence(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": R7_SPLIT_SCHEMA,
            "dataset_id": self.dataset_id,
            "task_split_digest": self.split_digest(),
            "split": HELDOUT_SPLIT,
            "task_count": len(self.tasks),
            "task_ids": sorted(task.task_id for task in self.tasks),
            "task_families": sorted(
                {task.task_family for task in self.tasks}
            ),
            "excluded_task_count": len(self.excluded_tasks),
            "excluded_task_ids": sorted(
                task.task_id for task in self.excluded_tasks
            ),
            "excluded_splits": sorted(
                {task.split for task in self.excluded_tasks}
            ),
            "synthetic": self.synthetic,
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class R7Condition:
    """A named experimental condition and its coupling coefficient."""

    condition_id: str
    role: str
    eta: float
    description: str = ""

    def __post_init__(self) -> None:
        if self.condition_id not in CONDITIONS:
            raise R7ExperimentError(
                f"unknown condition_id: {self.condition_id!r}"
            )
        if self.role not in ("baseline", "candidate"):
            raise R7ExperimentError(
                "condition role must be 'baseline' or 'candidate'"
            )
        object.__setattr__(
            self,
            "eta",
            _require_number(self.eta, "condition eta", minimum=0.0, maximum=1.0),
        )
        if not isinstance(self.description, str):
            raise R7ExperimentError("condition description must be a string")

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition_id": self.condition_id,
            "role": self.role,
            "eta": self.eta,
            "description": self.description,
        }


@dataclass(frozen=True)
class R7Spec:
    """Evaluation protocol, baseline matrix, and hard-gate thresholds."""

    seeds: tuple[int, ...] = (0, 1)
    bootstrap_samples: int = 2000
    permutation_samples: int = 2000
    bootstrap_seed: int = 20261107
    permutation_seed: int = 20261108
    confidence: float = 0.95
    min_tasks: int = 8
    min_seeds: int = 2
    min_effect: float = 0.0
    candidate_eta: float = 0.25
    random_eta: float | None = None
    novelty_floor: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.seeds, tuple):
            object.__setattr__(self, "seeds", tuple(self.seeds))
        if not self.seeds:
            raise R7ExperimentError("seeds cannot be empty")
        for seed in self.seeds:
            _require_int(seed, "seed")
        if len(set(self.seeds)) != len(self.seeds):
            raise R7ExperimentError("seeds must be unique")
        for name, value in (
            ("bootstrap_samples", self.bootstrap_samples),
            ("permutation_samples", self.permutation_samples),
            ("bootstrap_seed", self.bootstrap_seed),
            ("permutation_seed", self.permutation_seed),
            ("min_tasks", self.min_tasks),
            ("min_seeds", self.min_seeds),
        ):
            _require_int(value, name)
        if self.bootstrap_samples < 1:
            raise R7ExperimentError("bootstrap_samples must be >= 1")
        if self.permutation_samples < 1:
            raise R7ExperimentError("permutation_samples must be >= 1")
        if self.min_tasks < 2:
            raise R7ExperimentError("min_tasks must be >= 2")
        if self.min_seeds < 2:
            raise R7ExperimentError(
                "min_seeds must be >= 2 so support cannot rest on one seed"
            )
        object.__setattr__(
            self,
            "confidence",
            _require_number(self.confidence, "confidence"),
        )
        if not 0.0 < self.confidence < 1.0:
            raise R7ExperimentError("confidence must be in (0, 1)")
        object.__setattr__(
            self,
            "min_effect",
            _require_number(
                self.min_effect, "min_effect", minimum=0.0, maximum=1.0
            ),
        )
        object.__setattr__(
            self,
            "candidate_eta",
            _require_number(
                self.candidate_eta,
                "candidate_eta",
                minimum=0.0,
                maximum=1.0,
            ),
        )
        if self.random_eta is not None:
            object.__setattr__(
                self,
                "random_eta",
                _require_number(
                    self.random_eta,
                    "random_eta",
                    minimum=0.0,
                    maximum=1.0,
                ),
            )
        object.__setattr__(
            self,
            "novelty_floor",
            _require_number(
                self.novelty_floor, "novelty_floor", minimum=0.0, maximum=1.0
            ),
        )

    def conditions(self) -> tuple[R7Condition, ...]:
        random_eta = (
            self.candidate_eta if self.random_eta is None else self.random_eta
        )
        return (
            R7Condition(
                CONDITION_DISCONNECTED,
                "baseline",
                0.0,
                "disconnected baseline (eta=0)",
            ),
            R7Condition(
                CONDITION_RANDOM,
                "baseline",
                random_eta,
                "norm-matched random-coupling baseline",
            ),
            R7Condition(
                CONDITION_COUPLED,
                "candidate",
                self.candidate_eta,
                "coupled candidate",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "seeds": list(self.seeds),
            "bootstrap_samples": self.bootstrap_samples,
            "permutation_samples": self.permutation_samples,
            "bootstrap_seed": self.bootstrap_seed,
            "permutation_seed": self.permutation_seed,
            "confidence": self.confidence,
            "min_tasks": self.min_tasks,
            "min_seeds": self.min_seeds,
            "min_effect": self.min_effect,
            "candidate_eta": self.candidate_eta,
            "random_eta": (
                self.candidate_eta
                if self.random_eta is None
                else self.random_eta
            ),
            "novelty_floor": self.novelty_floor,
            "conditions": [condition.to_dict() for condition in self.conditions()],
        }


@dataclass(frozen=True)
class R7EvaluationRequest:
    """Typed request passed to a caller-supplied evaluator.

    The accepted answers are deliberately absent.  An evaluator sees only the
    public task prompt, identity, family, split, seed, and condition metadata.
    """

    dataset_id: str
    task_id: str
    prompt: str
    task_family: str
    split: str
    seed: int
    condition: str
    role: str
    eta: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "task_id": self.task_id,
            "prompt": self.prompt,
            "task_family": self.task_family,
            "split": self.split,
            "seed": self.seed,
            "condition": self.condition,
            "role": self.role,
            "eta": self.eta,
        }


@dataclass(frozen=True)
class R7Prediction:
    """Caller-supplied prediction string plus optional novelty/usefulness."""

    text: str
    novelty: float | None = None
    usefulness: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise R7ExperimentError("R7Prediction.text must be a string")
        object.__setattr__(
            self, "novelty", _optional_score(self.novelty, "novelty")
        )
        object.__setattr__(
            self,
            "usefulness",
            _optional_score(self.usefulness, "usefulness"),
        )


@dataclass(frozen=True)
class AvoidedCrossingEvidence:
    """Caller-supplied avoided-crossing sweep output.

    ``couplings``, ``gaps``, and optional ``lower``/``upper`` arrays are the
    fixture outputs.  The harness validates shape/finiteness and summarizes
    them; it does not recompute eigenvalues.
    """

    couplings: tuple[float, ...]
    gaps: tuple[float, ...]
    lower: tuple[float, ...] = ()
    upper: tuple[float, ...] = ()
    a: float | None = None
    b: float | None = None
    source: str = "caller_supplied"
    status: str = "caller_supplied"
    marker: str = AVOIDED_CROSSING_MARKER
    steps: int | None = None

    def __post_init__(self) -> None:
        if isinstance(self.couplings, (str, bytes)) or not isinstance(
            self.couplings, Sequence
        ):
            raise NativeEvidenceError("couplings must be a sequence")
        if isinstance(self.gaps, (str, bytes)) or not isinstance(
            self.gaps, Sequence
        ):
            raise NativeEvidenceError("gaps must be a sequence")
        object.__setattr__(
            self,
            "couplings",
            _float_tuple(self.couplings, "couplings", maximum_length=256),
        )
        object.__setattr__(
            self,
            "gaps",
            _float_tuple(self.gaps, "gaps", maximum_length=256),
        )
        if len(self.couplings) != len(self.gaps):
            raise NativeEvidenceError(
                "couplings and gaps must have the same length"
            )
        if any(gap < 0.0 for gap in self.gaps):
            raise NativeEvidenceError("gaps must be nonnegative")
        for name in ("lower", "upper"):
            value = getattr(self, name)
            if value is None:
                object.__setattr__(self, name, ())
                continue
            if isinstance(value, (str, bytes, bytearray)) or not isinstance(
                value, Sequence
            ):
                raise NativeEvidenceError(f"{name} must be a sequence")
            coerced = (
                _float_tuple(value, name, maximum_length=256)
                if value
                else ()
            )
            object.__setattr__(self, name, coerced)
            if coerced and len(coerced) != len(self.couplings):
                raise NativeEvidenceError(
                    f"{name} must have the same length as couplings"
                )
        if self.lower or self.upper:
            if not (self.lower and self.upper):
                raise NativeEvidenceError(
                    "lower and upper must be supplied together"
                )
            if any(
                low > high for low, high in zip(self.lower, self.upper)
            ):
                raise NativeEvidenceError("lower must be <= upper at each index")
        if self.a is not None:
            object.__setattr__(
                self, "a", _require_number(self.a, "a", error_cls=NativeEvidenceError)
            )
        if self.b is not None:
            object.__setattr__(
                self, "b", _require_number(self.b, "b", error_cls=NativeEvidenceError)
            )
        _require_text(
            self.source, "avoided-crossing source", error_cls=NativeEvidenceError
        )
        if self.status not in NATIVE_EVIDENCE_STATUSES:
            raise NativeEvidenceError(
                f"unknown avoided-crossing status: {self.status!r}"
            )
        _require_text(
            self.marker, "avoided-crossing marker", error_cls=NativeEvidenceError
        )
        if self.steps is not None:
            _require_int(
                self.steps,
                "avoided-crossing steps",
                minimum=1,
                error_cls=NativeEvidenceError,
            )

    def metrics(self) -> dict[str, Any]:
        min_index = min(range(len(self.gaps)), key=self.gaps.__getitem__)
        zero_gap = next(
            (
                gap
                for coupling, gap in zip(self.couplings, self.gaps)
                if coupling == 0.0
            ),
            None,
        )
        monotonic = all(
            self.gaps[index] <= self.gaps[index + 1] + 1e-12
            for index in range(len(self.gaps) - 1)
        )
        metrics: dict[str, Any] = {
            "coupling_count": len(self.couplings),
            "coupling_min": round(min(self.couplings), 12),
            "coupling_max": round(max(self.couplings), 12),
            "min_gap": round(self.gaps[min_index], 12),
            "max_gap": round(max(self.gaps), 12),
            "mean_gap": round(_mean(list(self.gaps)), 12),
            "gap_range": round(max(self.gaps) - min(self.gaps), 12),
            "min_gap_coupling": round(self.couplings[min_index], 12),
            "zero_coupling_gap": (
                None if zero_gap is None else round(zero_gap, 12)
            ),
            "decoupled_count": sum(1 for gap in self.gaps if gap == 0.0),
            "gap_monotonic_nondecreasing": monotonic,
        }
        if self.lower:
            metrics["lower_min"] = round(min(self.lower), 12)
            metrics["upper_max"] = round(max(self.upper), 12)
        return metrics

    def _digest_payload(self) -> dict[str, Any]:
        return {
            "a": self.a,
            "b": self.b,
            "couplings": list(self.couplings),
            "gaps": list(self.gaps),
            "lower": list(self.lower),
            "upper": list(self.upper),
            "source": self.source,
            "status": self.status,
            "marker": self.marker,
            "steps": self.steps,
        }

    def to_evidence(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "status": self.status,
            "marker": self.marker,
            "steps": self.steps,
            "a": self.a,
            "b": self.b,
            "arrays_digest": _sha256_json(self._digest_payload()),
            "metrics": self.metrics(),
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "AvoidedCrossingEvidence":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise NativeEvidenceError(
                "avoided-crossing evidence must be a mapping or "
                "AvoidedCrossingEvidence"
            )
        return cls(
            couplings=_get_alias(value, ("couplings", "c"), "couplings"),
            gaps=_get_alias(value, ("gaps", "gap"), "gaps"),
            lower=value.get("lower", ()),
            upper=value.get("upper", ()),
            a=value.get("a"),
            b=value.get("b"),
            source=value.get("source", "caller_supplied"),
            status=value.get("status", "caller_supplied"),
            marker=value.get("marker", AVOIDED_CROSSING_MARKER),
            steps=value.get("steps"),
        )


@dataclass(frozen=True)
class PhaseCoherenceEvidence:
    """Caller-supplied 128-sample phase-coherence output ``R``."""

    coherence: float
    sample_count: int = 128
    source: str = "caller_supplied"
    status: str = "caller_supplied"
    marker: str = PHASE_COHERENCE_MARKER
    steps: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "coherence",
            _require_number(
                self.coherence,
                "coherence",
                minimum=-1e-5,
                maximum=1.0 + 1e-5,
                error_cls=NativeEvidenceError,
            ),
        )
        _require_int(
            self.sample_count,
            "sample_count",
            minimum=1,
            error_cls=NativeEvidenceError,
        )
        if self.status != "caller_supplied" and self.sample_count != 128:
            raise NativeEvidenceError(
                "the native phase-coherence fixture is fixed at 128 samples"
            )
        _require_text(
            self.source, "phase-coherence source", error_cls=NativeEvidenceError
        )
        if self.status not in NATIVE_EVIDENCE_STATUSES:
            raise NativeEvidenceError(
                f"unknown phase-coherence status: {self.status!r}"
            )
        _require_text(
            self.marker, "phase-coherence marker", error_cls=NativeEvidenceError
        )
        if self.steps is not None:
            _require_int(
                self.steps,
                "phase-coherence steps",
                minimum=1,
                error_cls=NativeEvidenceError,
            )

    def metrics(self) -> dict[str, Any]:
        return {
            "coherence": round(self.coherence, 12),
            "incoherence": round(1.0 - self.coherence, 12),
            "sample_count": self.sample_count,
        }

    def _digest_payload(self) -> dict[str, Any]:
        return {
            "coherence": self.coherence,
            "sample_count": self.sample_count,
            "source": self.source,
            "status": self.status,
            "marker": self.marker,
            "steps": self.steps,
        }

    def to_evidence(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "status": self.status,
            "marker": self.marker,
            "steps": self.steps,
            "metrics": self.metrics(),
            "record_digest": _sha256_json(self._digest_payload()),
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "PhaseCoherenceEvidence":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise NativeEvidenceError(
                "phase-coherence evidence must be a mapping or "
                "PhaseCoherenceEvidence"
            )
        return cls(
            coherence=_get_alias(
                value,
                ("coherence", "phase_coherence", "ratio", "r"),
                "coherence",
            ),
            sample_count=value.get(
                "sample_count", value.get("samples", 128)
            ),
            source=value.get("source", "caller_supplied"),
            status=value.get("status", "caller_supplied"),
            marker=value.get("marker", PHASE_COHERENCE_MARKER),
            steps=value.get("steps"),
        )


@dataclass(frozen=True)
class CouplingEvidence:
    """Caller-supplied ``eta`` from the two-region coupling primitive."""

    eta: float
    source: str = "caller_supplied"
    status: str = "caller_supplied"
    marker: str = COUPLING_MARKER
    steps: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "eta",
            _require_number(
                self.eta,
                "eta",
                minimum=0.0,
                maximum=1.0,
                error_cls=NativeEvidenceError,
            ),
        )
        _require_text(self.source, "coupling source", error_cls=NativeEvidenceError)
        if self.status not in NATIVE_EVIDENCE_STATUSES:
            raise NativeEvidenceError(
                f"unknown coupling status: {self.status!r}"
            )
        _require_text(
            self.marker, "coupling marker", error_cls=NativeEvidenceError
        )
        if self.steps is not None:
            _require_int(
                self.steps,
                "coupling steps",
                minimum=1,
                error_cls=NativeEvidenceError,
            )

    def metrics(self) -> dict[str, Any]:
        return {
            "eta": round(self.eta, 12),
            "partial_coupling": 0.0 < self.eta < 1.0,
            "disconnected": self.eta == 0.0,
            "full_mixing": self.eta == 1.0,
            "inner_weight": round(1.0 - self.eta, 12),
            "outer_weight": round(self.eta, 12),
        }

    def _digest_payload(self) -> dict[str, Any]:
        return {
            "eta": self.eta,
            "source": self.source,
            "status": self.status,
            "marker": self.marker,
            "steps": self.steps,
        }

    def to_evidence(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "status": self.status,
            "marker": self.marker,
            "steps": self.steps,
            "metrics": self.metrics(),
            "record_digest": _sha256_json(self._digest_payload()),
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "CouplingEvidence":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise NativeEvidenceError(
                "coupling evidence must be a mapping or CouplingEvidence"
            )
        return cls(
            eta=_get_alias(value, ("eta", "coupling_eta"), "eta"),
            source=value.get("source", "caller_supplied"),
            status=value.get("status", "caller_supplied"),
            marker=value.get("marker", COUPLING_MARKER),
            steps=value.get("steps"),
        )


@dataclass(frozen=True)
class R7NativeEvidence:
    """Avoided-crossing, coupling, and phase-coherence evidence in one record."""

    avoided_crossing: AvoidedCrossingEvidence
    phase_coherence: PhaseCoherenceEvidence
    coupling: CouplingEvidence | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.avoided_crossing, Mapping):
            object.__setattr__(
                self,
                "avoided_crossing",
                AvoidedCrossingEvidence.from_mapping(self.avoided_crossing),
            )
        if not isinstance(self.avoided_crossing, AvoidedCrossingEvidence):
            raise NativeEvidenceError(
                "avoided_crossing must be AvoidedCrossingEvidence or a mapping"
            )
        if isinstance(self.phase_coherence, Mapping):
            object.__setattr__(
                self,
                "phase_coherence",
                PhaseCoherenceEvidence.from_mapping(self.phase_coherence),
            )
        if not isinstance(self.phase_coherence, PhaseCoherenceEvidence):
            raise NativeEvidenceError(
                "phase_coherence must be PhaseCoherenceEvidence or a mapping"
            )
        if self.coupling is not None:
            if isinstance(self.coupling, Mapping):
                object.__setattr__(
                    self,
                    "coupling",
                    CouplingEvidence.from_mapping(self.coupling),
                )
            if not isinstance(self.coupling, CouplingEvidence):
                raise NativeEvidenceError(
                    "coupling must be CouplingEvidence, a mapping, or None"
                )
        if not isinstance(self.note, str):
            raise NativeEvidenceError("note must be a string")

    def _digest_payload(self) -> dict[str, Any]:
        return {
            "avoided_crossing": self.avoided_crossing._digest_payload(),
            "phase_coherence": self.phase_coherence._digest_payload(),
            "coupling": (
                None
                if self.coupling is None
                else self.coupling._digest_payload()
            ),
            "note": self.note,
        }

    def digest(self) -> str:
        return _sha256_json(self._digest_payload())

    def to_evidence(self) -> dict[str, Any]:
        return {
            "schema": R7_NATIVE_SCHEMA,
            "present": True,
            "verified_by_harness": False,
            "note": self.note,
            "evidence_digest": self.digest(),
            "transition_metrics": self.avoided_crossing.metrics(),
            "coupling_metrics": (
                None
                if self.coupling is None
                else self.coupling.metrics()
            ),
            "phase_metrics": self.phase_coherence.metrics(),
            "avoided_crossing": self.avoided_crossing.to_evidence(),
            "coupling": (
                None
                if self.coupling is None
                else self.coupling.to_evidence()
            ),
            "phase_coherence": self.phase_coherence.to_evidence(),
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "R7NativeEvidence":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise NativeEvidenceError(
                "native evidence must be a mapping or R7NativeEvidence"
            )
        return cls(
            avoided_crossing=_get_alias(
                value,
                ("avoided_crossing", "sweep", "transition"),
                "avoided_crossing",
            ),
            phase_coherence=_get_alias(
                value,
                ("phase_coherence", "phase"),
                "phase_coherence",
            ),
            coupling=value.get("coupling"),
            note=value.get("note", ""),
        )


def _empty_native_evidence() -> dict[str, Any]:
    return {
        "schema": R7_NATIVE_SCHEMA,
        "present": False,
        "verified_by_harness": False,
        "note": "",
        "evidence_digest": None,
        "transition_metrics": None,
        "coupling_metrics": None,
        "phase_metrics": None,
        "avoided_crossing": None,
        "coupling": None,
        "phase_coherence": None,
    }


class R7Experiment:
    """Orchestrate the R7 held-out association baseline matrix.

    Construction validates only the protocol.  No evaluator, task set, model,
    or native record is required until :meth:`run` is called.
    """

    def __init__(self, spec: R7Spec | None = None) -> None:
        if spec is None:
            spec = R7Spec()
        if not isinstance(spec, R7Spec):
            raise R7ExperimentError("spec must be an R7Spec")
        self.spec = spec

    def __repr__(self) -> str:
        return (
            "R7Experiment("
            f"candidate_eta={self.spec.candidate_eta!r}, "
            f"seeds={self.spec.seeds!r})"
        )

    def describe(self) -> dict[str, Any]:
        """Describe the protocol without calling any evaluator."""
        return {
            "schema": R7_SCHEMA,
            "harness_version": HARNESS_VERSION,
            "mode": "control-plane",
            "evaluator_required_for_construction": False,
            "evaluator_calls_made": 0,
            "protocol": self.spec.to_dict(),
            "baseline_conditions": list(BASELINE_CONDITIONS),
            "candidate_condition": CANDIDATE_CONDITION,
            "native_evidence_required_for_support": True,
            "limitations": list(LIMITATIONS),
        }

    def run(
        self,
        task_set: R7TaskSet | None = None,
        *,
        baseline_evaluator: Any = None,
        coupled_evaluator: Any = None,
        baseline_predictions: Mapping[str, Any] | None = None,
        coupled_predictions: Mapping[str, Any] | None = None,
        native_evidence: R7NativeEvidence | Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run the matrix and return a JSON-serializable evidence record."""
        if task_set is not None and not isinstance(task_set, R7TaskSet):
            raise R7ExperimentError("task_set must be an R7TaskSet")
        if task_set is not None:
            task_set.validate()
        evidence = (
            None
            if native_evidence is None
            else R7NativeEvidence.from_mapping(native_evidence)
        )

        if task_set is None:
            return self._inadmissible_report(
                None, evidence, "missing held-out task set"
            )
        if not task_set.tasks:
            return self._inadmissible_report(
                task_set, evidence, "held-out task set is empty"
            )

        baseline_source = self._bind_role(
            "baseline",
            baseline_evaluator,
            baseline_predictions,
        )
        coupled_source = self._bind_role(
            "candidate",
            coupled_evaluator,
            coupled_predictions,
        )
        baseline_kind, baseline_hook, baseline_map = baseline_source
        coupled_kind, coupled_hook, coupled_map = coupled_source

        tasks = sorted(task_set.tasks, key=lambda task: task.task_id)
        conditions = {condition.condition_id: condition for condition in self.spec.conditions()}
        call_counts = {
            "baseline_evaluator_calls": 0,
            "coupled_evaluator_calls": 0,
            "prediction_lookups": 0,
            "evaluations": 0,
        }

        runs_by_task: list[dict[str, Any]] = []
        for task in tasks:
            accepted = task.accepted_answers()
            task_runs: list[dict[str, Any]] = []
            for seed in self.spec.seeds:
                scores: dict[str, dict[str, Any]] = {}
                for condition_id in CONDITIONS:
                    condition = conditions[condition_id]
                    request = R7EvaluationRequest(
                        dataset_id=task_set.dataset_id,
                        task_id=task.task_id,
                        prompt=task.prompt,
                        task_family=task.task_family,
                        split=task.split,
                        seed=seed,
                        condition=condition.condition_id,
                        role=condition.role,
                        eta=condition.eta,
                    )
                    prediction = self._evaluate(
                        request,
                        condition.role,
                        baseline_kind,
                        baseline_hook,
                        baseline_map,
                        coupled_kind,
                        coupled_hook,
                        coupled_map,
                        call_counts,
                    )
                    scores[condition_id] = _score_prediction(
                        prediction, accepted
                    )

                deltas = {
                    baseline: _match_delta(
                        scores[CANDIDATE_CONDITION], scores[baseline]
                    )
                    for baseline in BASELINE_CONDITIONS
                }
                novelty_deltas: dict[str, float | None] = {}
                for baseline in BASELINE_CONDITIONS:
                    candidate_novelty = scores[CANDIDATE_CONDITION]["novelty"]
                    baseline_novelty = scores[baseline]["novelty"]
                    novelty_deltas[baseline] = (
                        None
                        if candidate_novelty is None or baseline_novelty is None
                        else round(candidate_novelty - baseline_novelty, 12)
                    )
                task_runs.append(
                    {
                        "seed": seed,
                        "conditions": scores,
                        "deltas": deltas,
                        "novelty_deltas": novelty_deltas,
                    }
                )

            runs_by_task.append(
                {
                    "task_id": task.task_id,
                    "split": task.split,
                    "task_family": task.task_family,
                    "prompt_digest": _sha256_text(
                        _normalize_text(task.prompt)
                    ),
                    "expected": list(accepted),
                    "runs": task_runs,
                    "mean_deltas": {
                        baseline: round(
                            _mean(
                                [
                                    run["deltas"][baseline]
                                    for run in task_runs
                                ]
                            ),
                            12,
                        )
                        for baseline in BASELINE_CONDITIONS
                    },
                }
            )

        condition_aggregates = {
            condition_id: self._aggregate_condition(
                runs_by_task, condition_id
            )
            for condition_id in CONDITIONS
        }
        delta_aggregates = {
            baseline: self._aggregate_delta(
                runs_by_task,
                baseline,
                condition_aggregates,
            )
            for baseline in BASELINE_CONDITIONS
        }

        dataset = task_set.to_evidence()
        dataset["missing"] = False
        dataset["admissible"] = (
            not task_set.synthetic and len(tasks) >= self.spec.min_tasks
        )

        checks = self._gate_checks(
            task_set,
            dataset,
            delta_aggregates,
            evidence,
        )
        status, reasons = self._combine_checks(checks)
        if not dataset["admissible"]:
            # Synthetic or underpowered data can never support or reject the
            # hypothesis, regardless of the observed effect.
            status = STATUS_INCONCLUSIVE

        expected_evaluations = len(tasks) * len(self.spec.seeds) * len(CONDITIONS)
        call_counts["expected_evaluations"] = expected_evaluations
        call_counts["matches_expected"] = (
            call_counts["evaluations"] == expected_evaluations
        )

        return {
            "schema": R7_SCHEMA,
            "harness_version": HARNESS_VERSION,
            "mode": "control-plane",
            "status": status,
            "evidence_level": status,
            "passed": status == STATUS_SUPPORTED,
            "claim": dict(CLAIM_SCOPE),
            "task_split_digest": dataset["task_split_digest"],
            "dataset": dataset,
            "protocol": {
                **self.spec.to_dict(),
                "baseline_conditions": list(BASELINE_CONDITIONS),
                "candidate_condition": CANDIDATE_CONDITION,
                "normalization": (
                    "strip, collapse whitespace, and casefold before matching"
                ),
                "bootstrap_unit": "task (per-task mean over seeds)",
                "interval_method": "paired percentile bootstrap",
                "test_method": "two-sided paired sign-flip permutation",
                "alpha": round(1.0 - self.spec.confidence, 12),
            },
            "evaluators": {
                "baseline": {
                    "kind": baseline_kind,
                    "id": _ids(baseline_hook),
                },
                "coupled": {
                    "kind": coupled_kind,
                    "id": _ids(coupled_hook),
                },
            },
            "native_evidence": (
                _empty_native_evidence()
                if evidence is None
                else evidence.to_evidence()
            ),
            "call_counts": call_counts,
            "per_task": runs_by_task,
            "aggregates": {
                "conditions": condition_aggregates,
                "deltas": delta_aggregates,
            },
            "gate": {
                "status": status,
                "passed": status == STATUS_SUPPORTED,
                "checks": checks,
                "reasons": reasons,
            },
            "limitations": list(LIMITATIONS),
        }

    # -- Binding and evaluation ----------------------------------------------

    @staticmethod
    def _bind_role(
        role: str,
        evaluator: Any,
        predictions: Mapping[str, Any] | None,
    ) -> tuple[str, Any, Mapping[str, Any] | None]:
        if evaluator is not None and predictions is not None:
            raise EvaluatorBindingError(
                f"{role}: supply an evaluator or predictions, not both"
            )
        if evaluator is None and predictions is None:
            raise EvaluatorBindingError(
                f"{role}: an evaluator or prediction mapping is required"
            )
        if evaluator is not None:
            if not callable(evaluator):
                raise EvaluatorBindingError(f"{role} evaluator must be callable")
            return "evaluator", evaluator, None
        if not isinstance(predictions, Mapping):
            raise EvaluatorBindingError(
                f"{role}_predictions must be a mapping"
            )
        return "predictions", None, predictions

    def _evaluate(
        self,
        request: R7EvaluationRequest,
        role: str,
        baseline_kind: str,
        baseline_hook: Any,
        baseline_map: Mapping[str, Any] | None,
        coupled_kind: str,
        coupled_hook: Any,
        coupled_map: Mapping[str, Any] | None,
        call_counts: dict[str, int],
    ) -> R7Prediction:
        if role == "baseline":
            kind = baseline_kind
            hook = baseline_hook
            mapping = baseline_map
            calls_key = "baseline_evaluator_calls"
        else:
            kind = coupled_kind
            hook = coupled_hook
            mapping = coupled_map
            calls_key = "coupled_evaluator_calls"

        if kind == "evaluator":
            try:
                result = hook(request)
            except Exception as exc:  # noqa: BLE001 - caller hook boundary
                raise EvaluatorHookError(
                    f"{role} evaluator failed for task "
                    f"{request.task_id!r}, condition {request.condition!r}, "
                    f"seed {request.seed}: {exc}"
                ) from exc
            call_counts[calls_key] += 1
            call_counts["evaluations"] += 1
            return self._coerce_prediction(result, role, request, hook_error=True)

        if mapping is None:
            raise EvaluatorBindingError(
                f"{role}: prediction mapping was not bound"
            )
        selected = self._prediction_map_for(mapping, request.condition)
        if request.task_id not in selected:
            raise EvaluatorBindingError(
                f"{role} predictions have no entry for task "
                f"{request.task_id!r}, condition {request.condition!r}"
            )
        call_counts["prediction_lookups"] += 1
        call_counts["evaluations"] += 1
        return self._coerce_prediction(
            selected[request.task_id], role, request, hook_error=False
        )

    @staticmethod
    def _prediction_map_for(
        predictions: Mapping[str, Any], condition: str
    ) -> Mapping[str, Any]:
        nested = predictions.get(condition)
        if isinstance(nested, Mapping):
            return nested
        return predictions

    @staticmethod
    def _coerce_prediction(
        result: Any,
        role: str,
        request: R7EvaluationRequest,
        *,
        hook_error: bool,
    ) -> R7Prediction:
        error_cls = EvaluatorHookError if hook_error else EvaluatorBindingError
        if isinstance(result, R7Prediction):
            return result
        if isinstance(result, str):
            try:
                return R7Prediction(result)
            except R7ExperimentError as exc:
                raise error_cls(str(exc)) from exc
        raise error_cls(
            f"{role} evaluation for task {request.task_id!r}, condition "
            f"{request.condition!r}, seed {request.seed} must return a string "
            "or R7Prediction"
        )

    # -- Aggregation ----------------------------------------------------------

    @staticmethod
    def _aggregate_condition(
        runs_by_task: list[dict[str, Any]],
        condition_id: str,
    ) -> dict[str, Any]:
        total = 0
        matches = 0
        exacts = 0
        token_total = 0.0
        novelty_values: list[float] = []
        usefulness_values: list[float] = []
        for task_record in runs_by_task:
            for run in task_record["runs"]:
                result = run["conditions"][condition_id]
                total += 1
                matches += int(bool(result["match"]))
                exacts += int(bool(result["exact"]))
                token_total += float(result["token_match"])
                if result["novelty"] is not None:
                    novelty_values.append(float(result["novelty"]))
                if result["usefulness"] is not None:
                    usefulness_values.append(float(result["usefulness"]))
        if total == 0:
            return {
                "condition": condition_id,
                "n": 0,
                "match_count": 0,
                "exact_count": 0,
                "match_rate": 0.0,
                "exact_rate": 0.0,
                "token_match_rate": 0.0,
                "novelty_mean": None,
                "novelty_n": 0,
                "usefulness_mean": None,
                "usefulness_n": 0,
            }
        return {
            "condition": condition_id,
            "n": total,
            "match_count": matches,
            "exact_count": exacts,
            "match_rate": round(matches / total, 12),
            "exact_rate": round(exacts / total, 12),
            "token_match_rate": round(token_total / total, 12),
            "novelty_mean": (
                round(_mean(novelty_values), 12) if novelty_values else None
            ),
            "novelty_n": len(novelty_values),
            "usefulness_mean": (
                round(_mean(usefulness_values), 12)
                if usefulness_values
                else None
            ),
            "usefulness_n": len(usefulness_values),
        }

    def _aggregate_delta(
        self,
        runs_by_task: list[dict[str, Any]],
        baseline: str,
        condition_aggregates: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any]:
        task_deltas: list[float] = []
        per_seed_values: dict[int, list[float]] = {
            seed: [] for seed in self.spec.seeds
        }
        novelty_pairs: list[float] = []
        improved_tasks = 0
        worse_tasks = 0
        tied_tasks = 0

        for task_record in runs_by_task:
            deltas: list[float] = []
            for run in task_record["runs"]:
                delta = _match_delta(
                    run["conditions"][CANDIDATE_CONDITION],
                    run["conditions"][baseline],
                )
                deltas.append(delta)
                per_seed_values[run["seed"]].append(delta)
                novelty_delta = run["novelty_deltas"][baseline]
                if novelty_delta is not None:
                    novelty_pairs.append(novelty_delta)
            mean_delta = _mean(deltas)
            task_deltas.append(mean_delta)
            if mean_delta > 1e-12:
                improved_tasks += 1
            elif mean_delta < -1e-12:
                worse_tasks += 1
            else:
                tied_tasks += 1

        mean_delta = round(_mean(task_deltas), 12)
        ci_seed = int(
            _sha256_text(f"{self.spec.bootstrap_seed}:{baseline}")[:16], 16
        )
        permutation_seed = int(
            _sha256_text(
                f"{self.spec.permutation_seed}:{baseline}"
            )[:16],
            16,
        )
        ci_low, ci_high = _paired_bootstrap_ci(
            task_deltas,
            samples=self.spec.bootstrap_samples,
            confidence=self.spec.confidence,
            seed=ci_seed,
        )
        permutation_p = _sign_flip_permutation_p(
            task_deltas,
            samples=self.spec.permutation_samples,
            seed=permutation_seed,
        )
        per_seed = []
        for seed in self.spec.seeds:
            values = per_seed_values[seed]
            seed_mean = round(_mean(values), 12)
            per_seed.append(
                {
                    "seed": seed,
                    "n": len(values),
                    "mean_delta": seed_mean,
                    "improved": sum(1 for value in values if value > 1e-12),
                    "worse": sum(1 for value in values if value < -1e-12),
                    "ties": sum(
                        1 for value in values if abs(value) <= 1e-12
                    ),
                }
            )
        reproducible = (
            len(per_seed) >= self.spec.min_seeds
            and all(
                item["mean_delta"] > self.spec.min_effect
                for item in per_seed
            )
        )
        novelty_delta = (
            round(_mean(novelty_pairs), 12) if novelty_pairs else None
        )
        novelty_without_correctness = (
            novelty_delta is not None
            and novelty_delta > self.spec.novelty_floor
            and mean_delta <= self.spec.min_effect
        )
        status, reason = self._classify_delta(
            baseline,
            mean_delta,
            ci_low,
            ci_high,
            permutation_p,
            reproducible,
            per_seed,
        )
        candidate_aggregate = condition_aggregates[CANDIDATE_CONDITION]
        baseline_aggregate = condition_aggregates[baseline]
        return {
            "candidate": CANDIDATE_CONDITION,
            "baseline": baseline,
            "n_tasks": len(task_deltas),
            "n_seeds": len(self.spec.seeds),
            "mean_delta": mean_delta,
            "ci_low": ci_low,
            "ci_high": ci_high,
            "confidence": self.spec.confidence,
            "bootstrap_samples": self.spec.bootstrap_samples,
            "bootstrap_seed": ci_seed,
            "permutation_samples": self.spec.permutation_samples,
            "permutation_seed": permutation_seed,
            "permutation_p_value": permutation_p,
            "alpha": round(1.0 - self.spec.confidence, 12),
            "candidate_match_rate": candidate_aggregate["match_rate"],
            "baseline_match_rate": baseline_aggregate["match_rate"],
            "candidate_novelty_mean": candidate_aggregate["novelty_mean"],
            "baseline_novelty_mean": baseline_aggregate["novelty_mean"],
            "novelty_delta": novelty_delta,
            "novelty_without_correctness": novelty_without_correctness,
            "improved_tasks": improved_tasks,
            "worse_tasks": worse_tasks,
            "tied_tasks": tied_tasks,
            "per_seed": per_seed,
            "reproducible": reproducible,
            "status": status,
            "reason": reason,
        }

    def _classify_delta(
        self,
        baseline: str,
        mean_delta: float,
        ci_low: float | None,
        ci_high: float | None,
        permutation_p: float | None,
        reproducible: bool,
        per_seed: list[Mapping[str, Any]],
    ) -> tuple[str, str]:
        name = f"{CANDIDATE_CONDITION}_vs_{baseline}"
        if mean_delta < -self.spec.min_effect:
            return (
                CHECK_FAIL,
                f"{name}: candidate is worse by {-mean_delta:.6f}, above "
                f"the harm threshold {self.spec.min_effect:.6f}",
            )
        if mean_delta <= self.spec.min_effect:
            return (
                CHECK_FAIL,
                f"{name}: mean delta {mean_delta:.6f} is not above "
                f"min_effect {self.spec.min_effect:.6f}",
            )
        if ci_low is None or ci_high is None:
            return (
                CHECK_INCONCLUSIVE,
                f"{name}: paired bootstrap needs at least two tasks",
            )
        if ci_low <= self.spec.min_effect:
            return (
                CHECK_INCONCLUSIVE,
                f"{name}: {self.spec.confidence:.0%} CI lower bound "
                f"{ci_low:.6f} is not above min_effect "
                f"{self.spec.min_effect:.6f}",
            )
        alpha = 1.0 - self.spec.confidence
        if permutation_p is None:
            return (
                CHECK_INCONCLUSIVE,
                f"{name}: permutation test needs at least two tasks",
            )
        if permutation_p > alpha:
            return (
                CHECK_INCONCLUSIVE,
                f"{name}: permutation p={permutation_p:.6f} exceeds "
                f"alpha {alpha:.6f}",
            )
        if len(per_seed) < self.spec.min_seeds:
            return (
                CHECK_INCONCLUSIVE,
                f"{name}: only {len(per_seed)} seeds; min_seeds is "
                f"{self.spec.min_seeds}",
            )
        if not reproducible:
            seed_means = ", ".join(
                f"{item['seed']}={item['mean_delta']:.6f}"
                for item in per_seed
            )
            return (
                CHECK_INCONCLUSIVE,
                f"{name}: effect is not positive for every seed "
                f"({seed_means})",
            )
        return (
            CHECK_PASS,
            f"{name}: mean delta {mean_delta:.6f} with "
            f"{self.spec.confidence:.0%} CI "
            f"[{ci_low:.6f}, {ci_high:.6f}] and permutation "
            f"p={permutation_p:.6f}",
        )

    # -- Gate -----------------------------------------------------------------

    def _gate_checks(
        self,
        task_set: R7TaskSet,
        dataset: Mapping[str, Any],
        deltas: Mapping[str, Mapping[str, Any]],
        evidence: R7NativeEvidence | None,
    ) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []

        def add(name: str, status: str, detail: str) -> None:
            checks.append(
                {"name": name, "status": status, "detail": detail}
            )

        task_count = len(task_set.tasks)
        add(
            "heldout_dataset_present",
            CHECK_PASS if task_count else CHECK_INCONCLUSIVE,
            f"{task_count} held-out tasks",
        )
        if task_set.synthetic:
            add(
                "dataset_admissible",
                CHECK_INCONCLUSIVE,
                "synthetic/toy dataset is not admissible evidence",
            )
        elif task_count < self.spec.min_tasks:
            add(
                "dataset_admissible",
                CHECK_INCONCLUSIVE,
                f"{task_count} tasks is below min_tasks "
                f"{self.spec.min_tasks}",
            )
        else:
            add(
                "dataset_admissible",
                CHECK_PASS,
                "non-synthetic held-out dataset meets min_tasks",
            )
        add(
            "enough_tasks",
            CHECK_PASS
            if task_count >= self.spec.min_tasks
            else CHECK_INCONCLUSIVE,
            f"{task_count} tasks; minimum {self.spec.min_tasks}",
        )
        add(
            "enough_seeds",
            CHECK_PASS
            if len(self.spec.seeds) >= self.spec.min_seeds
            else CHECK_INCONCLUSIVE,
            f"{len(self.spec.seeds)} seeds; minimum {self.spec.min_seeds}",
        )
        add(
            "candidate_eta_partial",
            CHECK_PASS
            if 0.0 < self.spec.candidate_eta < 1.0
            else CHECK_FAIL,
            f"candidate eta={self.spec.candidate_eta}; the R7 hypothesis "
            "requires 0 < eta < 1",
        )
        add(
            "dataset_split_binding",
            CHECK_PASS,
            f"task_split_digest={dataset.get('task_split_digest')}",
        )

        if evidence is None:
            add(
                "native_evidence_present",
                CHECK_INCONCLUSIVE,
                "no avoided-crossing, coupling, or phase-coherence evidence "
                "was supplied",
            )
        else:
            add(
                "native_evidence_present",
                CHECK_PASS,
                f"evidence_digest={evidence.digest()}",
            )
            add(
                "native_avoided_crossing",
                *self._native_record_check(
                    evidence.avoided_crossing.status,
                    evidence.avoided_crossing.marker,
                    AVOIDED_CROSSING_MARKER,
                    "avoided-crossing",
                ),
            )
            add(
                "native_phase_coherence",
                *self._native_record_check(
                    evidence.phase_coherence.status,
                    evidence.phase_coherence.marker,
                    PHASE_COHERENCE_MARKER,
                    "phase-coherence",
                ),
            )
            if evidence.coupling is None:
                add(
                    "native_coupling",
                    CHECK_INCONCLUSIVE,
                    "no coupling eta evidence was supplied",
                )
            else:
                add(
                    "native_coupling",
                    *self._native_record_check(
                        evidence.coupling.status,
                        evidence.coupling.marker,
                        COUPLING_MARKER,
                        "coupling",
                    ),
                )
                matches = math.isclose(
                    evidence.coupling.eta,
                    self.spec.candidate_eta,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
                add(
                    "native_coupling_matches_candidate",
                    CHECK_PASS if matches else CHECK_FAIL,
                    f"evidence eta={evidence.coupling.eta}, candidate eta="
                    f"{self.spec.candidate_eta}",
                )

        novelty_conflicts = [
            baseline
            for baseline, delta in deltas.items()
            if delta["novelty_without_correctness"]
        ]
        add(
            "novelty_not_sole_evidence",
            CHECK_FAIL if novelty_conflicts else CHECK_PASS,
            (
                "novelty improved without a correctness improvement versus "
                f"{', '.join(novelty_conflicts)}"
                if novelty_conflicts
                else "correctness gate is independent of novelty"
            ),
        )

        for baseline in BASELINE_CONDITIONS:
            delta = deltas[baseline]
            add(
                f"beats_{baseline}",
                str(delta["status"]),
                str(delta["reason"]),
            )
        return checks

    @staticmethod
    def _native_record_check(
        status: str,
        marker: str,
        expected_marker: str,
        label: str,
    ) -> tuple[str, str]:
        if status not in NATIVE_EVIDENCE_STATUSES:
            return CHECK_FAIL, f"{label}: unsupported evidence status {status!r}"
        if status == "native_verified" and marker != expected_marker:
            return (
                CHECK_FAIL,
                f"{label}: native_verified marker {marker!r} does not match "
                f"{expected_marker!r}",
            )
        return CHECK_PASS, f"{label}: status={status}, marker={marker}"

    @staticmethod
    def _combine_checks(
        checks: list[Mapping[str, Any]],
    ) -> tuple[str, list[str]]:
        statuses = {check["status"] for check in checks}
        if CHECK_FAIL in statuses:
            status = STATUS_REJECTED
        elif CHECK_INCONCLUSIVE in statuses:
            status = STATUS_INCONCLUSIVE
        else:
            status = STATUS_SUPPORTED
        reasons = [
            f"{check['name']}: {check['detail']}"
            for check in checks
            if check["status"] != CHECK_PASS
        ]
        return status, reasons

    # -- Missing/inadmissible report -----------------------------------------

    def _inadmissible_report(
        self,
        task_set: R7TaskSet | None,
        evidence: R7NativeEvidence | None,
        reason: str,
    ) -> dict[str, Any]:
        if task_set is not None:
            dataset = task_set.to_evidence()
            dataset["missing"] = True
            dataset["admissible"] = False
        else:
            dataset = {
                "schema": R7_SPLIT_SCHEMA,
                "dataset_id": None,
                "task_split_digest": None,
                "split": HELDOUT_SPLIT,
                "task_count": 0,
                "task_ids": [],
                "task_families": [],
                "excluded_task_count": 0,
                "excluded_task_ids": [],
                "excluded_splits": [],
                "synthetic": False,
                "provenance": "",
                "missing": True,
                "admissible": False,
            }
        checks = [
            {
                "name": "heldout_dataset_present",
                "status": CHECK_INCONCLUSIVE,
                "detail": reason,
            }
        ]
        status, reasons = self._combine_checks(checks)
        return {
            "schema": R7_SCHEMA,
            "harness_version": HARNESS_VERSION,
            "mode": "control-plane",
            "status": status,
            "evidence_level": status,
            "passed": False,
            "claim": dict(CLAIM_SCOPE),
            "task_split_digest": dataset.get("task_split_digest"),
            "dataset": dataset,
            "protocol": {
                **self.spec.to_dict(),
                "baseline_conditions": list(BASELINE_CONDITIONS),
                "candidate_condition": CANDIDATE_CONDITION,
                "normalization": (
                    "strip, collapse whitespace, and casefold before matching"
                ),
                "bootstrap_unit": "task (per-task mean over seeds)",
                "interval_method": "paired percentile bootstrap",
                "test_method": "two-sided paired sign-flip permutation",
                "alpha": round(1.0 - self.spec.confidence, 12),
            },
            "evaluators": {
                "baseline": {"kind": None, "id": None},
                "coupled": {"kind": None, "id": None},
            },
            "native_evidence": (
                _empty_native_evidence()
                if evidence is None
                else evidence.to_evidence()
            ),
            "call_counts": {
                "baseline_evaluator_calls": 0,
                "coupled_evaluator_calls": 0,
                "prediction_lookups": 0,
                "evaluations": 0,
                "expected_evaluations": 0,
                "matches_expected": True,
            },
            "per_task": [],
            "aggregates": {"conditions": {}, "deltas": {}},
            "gate": {
                "status": status,
                "passed": False,
                "checks": checks,
                "reasons": reasons,
            },
            "limitations": list(LIMITATIONS),
        }


def run_r7_experiment(
    task_set: R7TaskSet | None = None,
    *,
    spec: R7Spec | None = None,
    baseline_evaluator: Any = None,
    coupled_evaluator: Any = None,
    baseline_predictions: Mapping[str, Any] | None = None,
    coupled_predictions: Mapping[str, Any] | None = None,
    native_evidence: R7NativeEvidence | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Convenience wrapper that constructs an :class:`R7Experiment` and runs it."""
    return R7Experiment(spec).run(
        task_set,
        baseline_evaluator=baseline_evaluator,
        coupled_evaluator=coupled_evaluator,
        baseline_predictions=baseline_predictions,
        coupled_predictions=coupled_predictions,
        native_evidence=native_evidence,
    )
