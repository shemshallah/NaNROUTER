"""Frozen-base LM adapter ablation harness for the R9 boundary.

This module is deliberately a control plane.  It never encodes a prompt,
computes a residual, applies a decode map, or invents a model prediction.
Callers supply every piece of model behaviour:

* a frozen model object exposing ``model_id``,
  ``encode(prompt, *, task_id, seed) -> EncodedState`` and
  ``predict(state, prompt, *, task_id, seed, condition) -> str``;
* a held-out :class:`AblationTaskSet`; and
* a residual executor ``executor(ResidualRequest) -> ResidualResult`` that is
  expected to wrap the verified native NaN16 residual kernel.

The harness schedules those calls, scores returned strings, computes paired
deltas and deterministic paired-bootstrap intervals, and decides whether the
evidence supports ``ablation_passed``.  A missing, synthetic, or underpowered
dataset can never pass the gate, and no creativity or general-capability claim
is made from this record.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .wave_adapter import WaveAdapterConfig, WaveAdapterError

ABLATION_SCHEMA = "nanrouter.lm-ablation.v1"
SPLIT_SCHEMA = "nanrouter.lm-ablation-split.v1"
HARNESS_VERSION = 1

HELDOUT_SPLIT = "heldout"

BASE_ONLY = "base_only"
ADAPTER_ON = "adapter_on"
ADAPTER_OFF = "adapter_off"
ZERO_RESIDUAL = "zero_residual"
SHUFFLED_LABELS = "shuffled_labels"

MODEL_CONDITIONS = (BASE_ONLY, ADAPTER_ON, ADAPTER_OFF, ZERO_RESIDUAL)
CONTROLS = (ZERO_RESIDUAL, SHUFFLED_LABELS)

COMPARISON_BASE = "adapter_on_vs_base_only"
COMPARISON_OFF = "adapter_on_vs_adapter_off"
COMPARISON_ZERO = "adapter_on_vs_zero_residual"
COMPARISON_SHUFFLED = "adapter_on_vs_shuffled_labels"
COMPARISONS = (
    COMPARISON_BASE,
    COMPARISON_OFF,
    COMPARISON_ZERO,
    COMPARISON_SHUFFLED,
)

STATUS_PASSED = "ablation_passed"
STATUS_REJECTED = "rejected"
STATUS_INCONCLUSIVE = "inconclusive"

CHECK_PASS = "pass"
CHECK_FAIL = "fail"
CHECK_INCONCLUSIVE = "inconclusive"

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

LIMITATIONS = (
    "No model mathematics is implemented here; encode, predict, and the "
    "residual executor are caller-supplied.",
    "The harness does not verify that the residual callback is native, "
    "correct, deterministic, reentrant-safe, or digest-bound.",
    "Call counts cover only calls issued by the harness. Internal calls made "
    "by caller hooks are not observable.",
    "Seed replicates are independent only if the caller's hooks vary with "
    "seed. Deterministic hooks demonstrate repeatability, not independent "
    "replication.",
    "The paired bootstrap resamples held-out tasks from this task set; it "
    "does not establish generalization beyond the supplied tasks.",
    "Synthetic, underpowered, or missing datasets are never admissible "
    "evidence for an ablation_passed result.",
    "No creativity, intelligence, consciousness, or quantum-tunneling claim "
    "is made from match-rate deltas.",
    "The result is report-local; this harness does not mutate the "
    "WaveAdapterConfig or persist the evidence record.",
)

CLAIM_SCOPE = {
    "scope": "held-out task match rate under caller-supplied hooks",
    "creativity_claim": False,
    "generalization_claim": False,
    "note": (
        "ablation_passed means only that this held-out task set, controls, "
        "and seed protocol met the gate; it is not a creativity or "
        "general-capability claim."
    ),
}


class LMAdapterAblationError(ValueError):
    """Base class for harness validation, hook, and executor failures."""


class SplitLeakageError(LMAdapterAblationError):
    """A task belongs to a non-held-out split or overlaps excluded data."""


class DuplicateTaskError(LMAdapterAblationError):
    """A held-out task ID or normalized prompt appears more than once."""


class ModelBindingError(LMAdapterAblationError):
    """The frozen model hooks are missing or do not match the adapter."""


class ModelHookError(LMAdapterAblationError):
    """A caller-supplied encode or predict hook failed or returned a bad type."""


class ResidualExecutorError(LMAdapterAblationError):
    """The residual executor is missing, failed, or violated its contract."""


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


def _json_safe(value: Any) -> Any:
    """Return ``value`` when JSON-serializable, otherwise ``None``."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    try:
        json.dumps(value, sort_keys=True)
    except (TypeError, ValueError):
        return None
    return value


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
    """Return a deterministic percentile bootstrap CI for the mean."""
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


def _accepted_answers(task: "AblationTask") -> tuple[str, ...]:
    expected = task.expected
    if isinstance(expected, str):
        values: tuple[Any, ...] = (expected,)
    elif isinstance(expected, (tuple, list)):
        values = tuple(expected)
    else:
        raise LMAdapterAblationError(
            "AblationTask.expected must be a string or a tuple of strings"
        )
    if not values:
        raise LMAdapterAblationError("AblationTask.expected cannot be empty")
    result: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise LMAdapterAblationError(
                "AblationTask.expected entries must be non-empty strings"
            )
        result.append(value)
    return tuple(result)


def _validate_task_identity(task: "AblationTask") -> None:
    if not isinstance(task.task_id, str) or not 1 <= len(task.task_id) <= 128:
        raise LMAdapterAblationError(
            "AblationTask.task_id must be 1..128 characters"
        )
    if not isinstance(task.prompt, str) or not task.prompt.strip():
        raise LMAdapterAblationError("AblationTask.prompt cannot be empty")
    _accepted_answers(task)


def _score_prediction(
    prediction: str, accepted: tuple[str, ...]
) -> dict[str, Any]:
    """Score one returned string without doing any model work."""
    if not isinstance(prediction, str):
        raise LMAdapterAblationError("prediction must be a string")

    exact = any(prediction.strip() == answer.strip() for answer in accepted)
    normalized_prediction = _normalize_text(prediction)
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
        "prediction": prediction,
        "exact": exact,
        "match": match,
        "token_match": token_match,
        "matched_answer": matched_answer,
    }


def _match_delta(treatment: Mapping[str, Any], control: Mapping[str, Any]) -> float:
    return float(bool(treatment["match"])) - float(bool(control["match"]))


@dataclass(frozen=True)
class AblationTask:
    """One held-out task with one or more accepted exact answers."""

    task_id: str
    prompt: str
    expected: str | tuple[str, ...]
    split: str = HELDOUT_SPLIT

    def __post_init__(self) -> None:
        if isinstance(self.expected, list):
            object.__setattr__(self, "expected", tuple(self.expected))

    def accepted_answers(self) -> tuple[str, ...]:
        return _accepted_answers(self)


@dataclass(frozen=True)
class AblationTaskSet:
    """A held-out task split plus optional excluded train/dev material.

    ``excluded_tasks`` are not evaluated.  They exist so the harness can reject
    task-ID or normalized-prompt leakage between the held-out split and any
    caller-declared non-held-out data.
    """

    dataset_id: str
    tasks: tuple[AblationTask, ...]
    excluded_tasks: tuple[AblationTask, ...] = ()
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
        if not isinstance(self.dataset_id, str) or not 1 <= len(self.dataset_id) <= 128:
            raise LMAdapterAblationError(
                "dataset_id must be 1..128 characters"
            )
        if not isinstance(self.synthetic, bool):
            raise LMAdapterAblationError("synthetic must be a boolean")
        if not isinstance(self.provenance, str):
            raise LMAdapterAblationError("provenance must be a string")

        heldout_ids: set[str] = set()
        heldout_prompts: set[str] = set()
        for task in self.tasks:
            if not isinstance(task, AblationTask):
                raise LMAdapterAblationError(
                    "tasks must contain AblationTask instances"
                )
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

        for task in self.excluded_tasks:
            if not isinstance(task, AblationTask):
                raise LMAdapterAblationError(
                    "excluded_tasks must contain AblationTask instances"
                )
            _validate_task_identity(task)
            normalized_prompt = _normalize_text(task.prompt)
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

    def split_digest(self) -> str:
        self.validate()
        payload = {
            "schema": SPLIT_SCHEMA,
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
                }
                for task in sorted(self.tasks, key=lambda item: item.task_id)
            ],
            "excluded_task_ids": sorted(
                task.task_id for task in self.excluded_tasks
            ),
            "excluded_prompts": sorted(
                _normalize_text(task.prompt) for task in self.excluded_tasks
            ),
        }
        return _sha256_json(payload)

    def to_evidence(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": SPLIT_SCHEMA,
            "dataset_id": self.dataset_id,
            "task_split_digest": self.split_digest(),
            "split": HELDOUT_SPLIT,
            "task_count": len(self.tasks),
            "task_ids": sorted(task.task_id for task in self.tasks),
            "excluded_task_count": len(self.excluded_tasks),
            "excluded_task_ids": sorted(
                task.task_id for task in self.excluded_tasks
            ),
            "synthetic": self.synthetic,
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class AblationSpec:
    """Evaluation protocol and hard-gate thresholds."""

    seeds: tuple[int, ...] = (0, 1)
    bootstrap_samples: int = 2000
    confidence: float = 0.95
    bootstrap_seed: int = 20261107
    min_tasks: int = 8
    min_seeds: int = 2
    min_effect: float = 0.0
    label_control_shift: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.seeds, tuple):
            object.__setattr__(self, "seeds", tuple(self.seeds))
        if not self.seeds:
            raise LMAdapterAblationError("seeds cannot be empty")
        for seed in self.seeds:
            if isinstance(seed, bool) or not isinstance(seed, int):
                raise LMAdapterAblationError("seeds must be integers")
        if len(set(self.seeds)) != len(self.seeds):
            raise LMAdapterAblationError("seeds must be unique")
        for name, value in (
            ("bootstrap_samples", self.bootstrap_samples),
            ("bootstrap_seed", self.bootstrap_seed),
            ("min_tasks", self.min_tasks),
            ("min_seeds", self.min_seeds),
            ("label_control_shift", self.label_control_shift),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise LMAdapterAblationError(f"{name} must be an integer")
        if self.bootstrap_samples < 1:
            raise LMAdapterAblationError("bootstrap_samples must be >= 1")
        if self.min_tasks < 2:
            raise LMAdapterAblationError("min_tasks must be >= 2")
        if self.min_seeds < 1:
            raise LMAdapterAblationError("min_seeds must be >= 1")
        if self.label_control_shift < 1:
            raise LMAdapterAblationError("label_control_shift must be >= 1")
        if isinstance(self.confidence, bool) or not isinstance(
            self.confidence, (int, float)
        ):
            raise LMAdapterAblationError("confidence must be a number")
        if not 0.0 < float(self.confidence) < 1.0:
            raise LMAdapterAblationError("confidence must be in (0, 1)")
        if isinstance(self.min_effect, bool) or not isinstance(
            self.min_effect, (int, float)
        ):
            raise LMAdapterAblationError("min_effect must be a number")
        if not 0.0 <= float(self.min_effect) <= 1.0:
            raise LMAdapterAblationError("min_effect must be in [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "seeds": list(self.seeds),
            "bootstrap_samples": self.bootstrap_samples,
            "confidence": float(self.confidence),
            "bootstrap_seed": self.bootstrap_seed,
            "min_tasks": self.min_tasks,
            "min_seeds": self.min_seeds,
            "min_effect": float(self.min_effect),
            "label_control_shift": self.label_control_shift,
        }


@dataclass(frozen=True)
class EncodedState:
    """Caller-owned base and readout state; the harness never inspects values."""

    base_state: Any
    readout_state: Any


@dataclass(frozen=True)
class ResidualRequest:
    """Typed request passed to the caller-supplied residual executor."""

    adapter_id: str
    adapter_mode: str
    adapter_config_digest: str
    task_id: str
    prompt: str
    seed: int
    condition: str
    base_state: Any
    readout_state: Any
    beta: float
    enabled: bool
    readout_dim: int


@dataclass(frozen=True)
class ResidualResult:
    """Executor result. ``applied`` must reflect whether the residual path ran."""

    state: Any
    applied: bool
    note: str = ""


class LMAdapterAblation:
    """Orchestrate the frozen-base ablation matrix for one adapter config.

    Construction validates only the adapter descriptor and protocol.  It never
    requires, retains, or calls a model or executor.  Model hooks and the
    executor are bound per :meth:`run` call.
    """

    def __init__(
        self,
        adapter_config: WaveAdapterConfig | Mapping[str, Any],
        spec: AblationSpec | None = None,
    ) -> None:
        if isinstance(adapter_config, WaveAdapterConfig):
            config = adapter_config
        elif isinstance(adapter_config, Mapping):
            config = WaveAdapterConfig.from_dict(dict(adapter_config))
        else:
            raise LMAdapterAblationError(
                "adapter_config must be a WaveAdapterConfig or mapping"
            )
        try:
            config.validate()
        except WaveAdapterError as exc:
            raise LMAdapterAblationError(str(exc)) from exc
        if spec is None:
            spec = AblationSpec()
        if not isinstance(spec, AblationSpec):
            raise LMAdapterAblationError("spec must be an AblationSpec")

        self.adapter_config = config
        self.spec = spec
        self.adapter_config_digest = _sha256_json(config.to_dict())
        self.base_model_id = config.base_model_id

    def __repr__(self) -> str:
        return (
            "LMAdapterAblation("
            f"adapter_id={self.adapter_config.adapter_id!r}, "
            f"base_model_id={self.base_model_id!r}, "
            f"seeds={self.spec.seeds!r})"
        )

    def describe(self) -> dict[str, Any]:
        """Describe the harness without calling a model or executor."""
        return {
            "schema": ABLATION_SCHEMA,
            "harness_version": HARNESS_VERSION,
            "mode": "control-plane",
            "model_required_for_construction": False,
            "model_calls_made": 0,
            "base_model_id": self.base_model_id,
            "adapter_config_digest": self.adapter_config_digest,
            "adapter": self.adapter_config.to_dict(),
            "protocol": self.spec.to_dict(),
            "model_conditions": list(MODEL_CONDITIONS),
            "controls": list(CONTROLS),
            "comparisons": list(COMPARISONS),
            "limitations": list(LIMITATIONS),
        }

    def run(
        self,
        task_set: AblationTaskSet | None = None,
        *,
        frozen_model: Any = None,
        residual_executor: Any = None,
    ) -> dict[str, Any]:
        """Run all conditions, score them, and return an evidence record.

        A missing or empty task set returns an ``inconclusive`` record without
        calling any hook.  With tasks present, ``frozen_model`` and
        ``residual_executor`` are required.
        """
        if task_set is None:
            return self._inadmissible_report(
                None, "missing held-out task set"
            )
        if not isinstance(task_set, AblationTaskSet):
            raise LMAdapterAblationError(
                "task_set must be an AblationTaskSet"
            )
        task_set.validate()
        if not task_set.tasks:
            return self._inadmissible_report(
                task_set, "held-out task set is empty"
            )

        model_id, encode, predict = self._bind_model(frozen_model)
        executor = self._bind_executor(residual_executor)

        tasks = sorted(task_set.tasks, key=lambda task: task.task_id)
        task_count = len(tasks)
        seed_count = len(self.spec.seeds)
        shift = self.spec.label_control_shift % task_count
        encoder_calls = 0
        predict_calls = 0
        executor_calls = 0

        runs_by_task: list[dict[str, Any]] = []
        for index, task in enumerate(tasks):
            accepted = task.accepted_answers()
            shuffled_task = tasks[(index + shift) % task_count]
            shuffled_accepted = shuffled_task.accepted_answers()
            task_runs: list[dict[str, Any]] = []

            for seed in self.spec.seeds:
                encoded = self._call_encode(encode, task, seed)
                encoder_calls += 1

                base_prediction = self._call_predict(
                    predict, encoded.base_state, task, seed, BASE_ONLY
                )
                predict_calls += 1

                on_request = self._residual_request(
                    task, seed, ADAPTER_ON, encoded,
                    beta=float(self.adapter_config.residual_scale),
                    enabled=True,
                )
                on_result = self._call_executor(executor, on_request)
                executor_calls += 1
                if on_result.applied is not True:
                    raise ResidualExecutorError(
                        "adapter_on executor result must report applied=True"
                    )
                on_prediction = self._call_predict(
                    predict, on_result.state, task, seed, ADAPTER_ON
                )
                predict_calls += 1

                off_request = self._residual_request(
                    task, seed, ADAPTER_OFF, encoded,
                    beta=0.0,
                    enabled=False,
                )
                off_result = self._call_executor(executor, off_request)
                executor_calls += 1
                if off_result.applied is not False:
                    raise ResidualExecutorError(
                        "adapter_off executor result must report applied=False"
                    )
                self._require_base_state(
                    off_result.state, encoded.base_state, ADAPTER_OFF
                )
                off_prediction = self._call_predict(
                    predict, off_result.state, task, seed, ADAPTER_OFF
                )
                predict_calls += 1

                zero_request = self._residual_request(
                    task, seed, ZERO_RESIDUAL, encoded,
                    beta=0.0,
                    enabled=True,
                )
                zero_result = self._call_executor(executor, zero_request)
                executor_calls += 1
                if zero_result.applied is not True:
                    raise ResidualExecutorError(
                        "zero_residual executor result must report applied=True"
                    )
                self._require_base_state(
                    zero_result.state, encoded.base_state, ZERO_RESIDUAL
                )
                zero_prediction = self._call_predict(
                    predict, zero_result.state, task, seed, ZERO_RESIDUAL
                )
                predict_calls += 1

                conditions = {
                    BASE_ONLY: _score_prediction(base_prediction, accepted),
                    ADAPTER_ON: _score_prediction(on_prediction, accepted),
                    ADAPTER_OFF: _score_prediction(off_prediction, accepted),
                    ZERO_RESIDUAL: _score_prediction(
                        zero_prediction, accepted
                    ),
                }
                shuffled = _score_prediction(
                    conditions[ADAPTER_ON]["prediction"], shuffled_accepted
                )
                shuffled.update(
                    {
                        "source_task_id": shuffled_task.task_id,
                        "shift": shift,
                    }
                )
                deltas = {
                    COMPARISON_BASE: _match_delta(
                        conditions[ADAPTER_ON], conditions[BASE_ONLY]
                    ),
                    COMPARISON_OFF: _match_delta(
                        conditions[ADAPTER_ON], conditions[ADAPTER_OFF]
                    ),
                    COMPARISON_ZERO: _match_delta(
                        conditions[ADAPTER_ON], conditions[ZERO_RESIDUAL]
                    ),
                    COMPARISON_SHUFFLED: _match_delta(
                        conditions[ADAPTER_ON], shuffled
                    ),
                }
                task_runs.append(
                    {
                        "seed": seed,
                        "conditions": conditions,
                        "shuffled_labels": shuffled,
                        "deltas": deltas,
                    }
                )

            runs_by_task.append(
                {
                    "task_id": task.task_id,
                    "split": task.split,
                    "prompt_digest": _sha256_text(_normalize_text(task.prompt)),
                    "expected": list(accepted),
                    "runs": task_runs,
                    "mean_deltas": {
                        comparison: round(
                            _mean(
                                [
                                    run["deltas"][comparison]
                                    for run in task_runs
                                ]
                            ),
                            12,
                        )
                        for comparison in COMPARISONS
                    },
                }
            )

        condition_aggregates = {
            condition: self._aggregate_condition(
                runs_by_task,
                lambda run, name=condition: run["conditions"][name],
            )
            for condition in MODEL_CONDITIONS
        }
        condition_aggregates[SHUFFLED_LABELS] = self._aggregate_condition(
            runs_by_task, lambda run: run["shuffled_labels"]
        )

        delta_aggregates = {
            COMPARISON_BASE: self._aggregate_delta(
                runs_by_task,
                COMPARISON_BASE,
                lambda run: run["conditions"][ADAPTER_ON],
                lambda run: run["conditions"][BASE_ONLY],
                degenerate=False,
            ),
            COMPARISON_OFF: self._aggregate_delta(
                runs_by_task,
                COMPARISON_OFF,
                lambda run: run["conditions"][ADAPTER_ON],
                lambda run: run["conditions"][ADAPTER_OFF],
                degenerate=False,
            ),
            COMPARISON_ZERO: self._aggregate_delta(
                runs_by_task,
                COMPARISON_ZERO,
                lambda run: run["conditions"][ADAPTER_ON],
                lambda run: run["conditions"][ZERO_RESIDUAL],
                degenerate=False,
            ),
            COMPARISON_SHUFFLED: self._aggregate_delta(
                runs_by_task,
                COMPARISON_SHUFFLED,
                lambda run: run["conditions"][ADAPTER_ON],
                lambda run: run["shuffled_labels"],
                degenerate=shift == 0,
            ),
        }

        dataset = task_set.to_evidence()
        dataset["missing"] = False
        dataset["admissible"] = (
            not task_set.synthetic and task_count >= self.spec.min_tasks
        )

        checks = self._gate_checks(
            task_set, dataset, delta_aggregates, shift, task_count
        )
        status, reasons = self._combine_checks(checks)
        if not dataset["admissible"]:
            # A toy or underpowered set cannot reject or accept the adapter;
            # it can only leave the hypothesis inconclusive.
            status = STATUS_INCONCLUSIVE

        expected_calls = {
            "encode": task_count * seed_count,
            "predict": task_count * seed_count * len(MODEL_CONDITIONS),
            "residual_executor": task_count * seed_count * 3,
        }
        actual_calls = {
            "encode": encoder_calls,
            "predict": predict_calls,
            "residual_executor": executor_calls,
        }

        return {
            "schema": ABLATION_SCHEMA,
            "harness_version": HARNESS_VERSION,
            "mode": "control-plane",
            "status": status,
            "evidence_level": status,
            "passed": status == STATUS_PASSED,
            "claim": dict(CLAIM_SCOPE),
            "base_model_id": self.base_model_id,
            "adapter_config_digest": self.adapter_config_digest,
            "task_split_digest": dataset.get("task_split_digest"),
            "model": {
                "reported_id": model_id,
                "binding_verified": model_id == self.base_model_id,
                "frozen": "caller-declared; not verifiable by this harness",
            },
            "adapter": {
                "config": self.adapter_config.to_dict(),
                "config_digest": self.adapter_config_digest,
                "evidence_level_before": self.adapter_config.evidence_level,
                "recommended_evidence_level": status,
            },
            "dataset": dataset,
            "protocol": {
                **self.spec.to_dict(),
                "model_conditions": list(MODEL_CONDITIONS),
                "controls": list(CONTROLS),
                "comparisons": list(COMPARISONS),
                "label_control_shift_effective": shift,
                "normalization": (
                    "strip, collapse whitespace, and casefold before matching"
                ),
                "bootstrap_unit": "task (per-task mean over seeds)",
            },
            "residual_executor": {
                "executor_id": self._executor_id(executor),
                "native_evidence": _json_safe(
                    getattr(executor, "evidence", None)
                ),
                "native_verified_by_harness": False,
            },
            "call_counts": {
                **actual_calls,
                "expected": expected_calls,
                "matches_expected": actual_calls == expected_calls,
                "per_task_seed": {
                    "encode": 1,
                    "predict": len(MODEL_CONDITIONS),
                    "residual_executor": 3,
                },
                "note": (
                    "Counts only harness-issued calls; caller hooks may make "
                    "additional internal calls that are not observable."
                ),
            },
            "per_task": runs_by_task,
            "aggregates": {
                "conditions": condition_aggregates,
                "deltas": delta_aggregates,
            },
            "gate": {
                "status": status,
                "passed": status == STATUS_PASSED,
                "checks": checks,
                "reasons": reasons,
            },
            "limitations": list(LIMITATIONS),
        }

    # -- Hook binding and invocation -----------------------------------------

    def _bind_model(self, frozen_model: Any):
        if frozen_model is None:
            raise ModelBindingError(
                "frozen_model is required when a held-out task set is present"
            )
        model_id = getattr(frozen_model, "model_id", None)
        if not isinstance(model_id, str) or not model_id:
            raise ModelBindingError(
                "frozen_model.model_id must be a non-empty string"
            )
        if model_id != self.base_model_id:
            raise ModelBindingError(
                f"frozen model {model_id!r} does not match adapter "
                f"base_model_id {self.base_model_id!r}"
            )
        encode = getattr(frozen_model, "encode", None)
        predict = getattr(frozen_model, "predict", None)
        if not callable(encode):
            raise ModelBindingError("frozen_model.encode must be callable")
        if not callable(predict):
            raise ModelBindingError("frozen_model.predict must be callable")
        return model_id, encode, predict

    @staticmethod
    def _bind_executor(residual_executor: Any):
        if residual_executor is None:
            raise ResidualExecutorError(
                "residual_executor is required when a held-out task set is "
                "present"
            )
        if not callable(residual_executor):
            raise ResidualExecutorError(
                "residual_executor must be callable"
            )
        return residual_executor

    @staticmethod
    def _call_encode(encode: Any, task: AblationTask, seed: int) -> EncodedState:
        try:
            encoded = encode(task.prompt, task_id=task.task_id, seed=seed)
        except Exception as exc:  # noqa: BLE001 - caller hook boundary
            raise ModelHookError(
                f"encode failed for task {task.task_id!r}, seed {seed}: {exc}"
            ) from exc
        if not isinstance(encoded, EncodedState):
            raise ModelHookError(
                "encode must return an EncodedState with base_state and "
                "readout_state"
            )
        return encoded

    @staticmethod
    def _call_predict(
        predict: Any,
        state: Any,
        task: AblationTask,
        seed: int,
        condition: str,
    ) -> str:
        try:
            prediction = predict(
                state,
                task.prompt,
                task_id=task.task_id,
                seed=seed,
                condition=condition,
            )
        except Exception as exc:  # noqa: BLE001 - caller hook boundary
            raise ModelHookError(
                f"predict failed for task {task.task_id!r}, seed {seed}, "
                f"condition {condition!r}: {exc}"
            ) from exc
        if not isinstance(prediction, str):
            raise ModelHookError(
                "predict must return a string for task "
                f"{task.task_id!r}, seed {seed}, condition {condition!r}"
            )
        return prediction

    @staticmethod
    def _call_executor(executor: Any, request: ResidualRequest) -> ResidualResult:
        try:
            result = executor(request)
        except Exception as exc:  # noqa: BLE001 - caller callback boundary
            raise ResidualExecutorError(
                f"residual executor failed for task {request.task_id!r}, "
                f"seed {request.seed}, condition {request.condition!r}: {exc}"
            ) from exc
        if not isinstance(result, ResidualResult):
            raise ResidualExecutorError(
                "residual executor must return a ResidualResult"
            )
        if not isinstance(result.applied, bool):
            raise ResidualExecutorError(
                "ResidualResult.applied must be a boolean"
            )
        return result

    @staticmethod
    def _require_base_state(
        state: Any, base_state: Any, condition: str
    ) -> None:
        try:
            same = bool(state == base_state)
        except Exception as exc:  # noqa: BLE001 - opaque caller state
            raise ResidualExecutorError(
                f"{condition} state equality could not be evaluated: {exc}"
            ) from exc
        if not same:
            raise ResidualExecutorError(
                f"{condition} must return the unchanged base state"
            )

    def _residual_request(
        self,
        task: AblationTask,
        seed: int,
        condition: str,
        encoded: EncodedState,
        *,
        beta: float,
        enabled: bool,
    ) -> ResidualRequest:
        return ResidualRequest(
            adapter_id=self.adapter_config.adapter_id,
            adapter_mode=self.adapter_config.mode,
            adapter_config_digest=self.adapter_config_digest,
            task_id=task.task_id,
            prompt=task.prompt,
            seed=seed,
            condition=condition,
            base_state=encoded.base_state,
            readout_state=encoded.readout_state,
            beta=beta,
            enabled=enabled,
            readout_dim=self.adapter_config.readout_dim,
        )

    @staticmethod
    def _executor_id(executor: Any) -> str | None:
        for name in ("executor_id", "kernel_id", "__name__"):
            value = getattr(executor, name, None)
            if isinstance(value, str) and value:
                return value
        return None

    # -- Aggregation and gate -------------------------------------------------

    @staticmethod
    def _aggregate_condition(
        runs_by_task: list[dict[str, Any]],
        getter: Any,
    ) -> dict[str, Any]:
        total = 0
        matches = 0
        exacts = 0
        token_total = 0.0
        for task_record in runs_by_task:
            for run in task_record["runs"]:
                result = getter(run)
                total += 1
                matches += int(bool(result["match"]))
                exacts += int(bool(result["exact"]))
                token_total += float(result["token_match"])
        if total == 0:
            return {
                "n": 0,
                "match_count": 0,
                "exact_count": 0,
                "match_rate": 0.0,
                "exact_rate": 0.0,
                "token_match_rate": 0.0,
            }
        return {
            "n": total,
            "match_count": matches,
            "exact_count": exacts,
            "match_rate": round(matches / total, 12),
            "exact_rate": round(exacts / total, 12),
            "token_match_rate": round(token_total / total, 12),
        }

    def _aggregate_delta(
        self,
        runs_by_task: list[dict[str, Any]],
        name: str,
        treatment_getter: Any,
        control_getter: Any,
        *,
        degenerate: bool,
    ) -> dict[str, Any]:
        task_deltas: list[float] = []
        per_seed_values: dict[int, list[float]] = {
            seed: [] for seed in self.spec.seeds
        }
        improved_tasks = 0
        worse_tasks = 0
        tied_tasks = 0

        for task_record in runs_by_task:
            deltas: list[float] = []
            for run in task_record["runs"]:
                delta = _match_delta(
                    treatment_getter(run), control_getter(run)
                )
                deltas.append(delta)
                per_seed_values[run["seed"]].append(delta)
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
            _sha256_text(f"{self.spec.bootstrap_seed}:{name}")[:16], 16
        )
        ci_low, ci_high = _paired_bootstrap_ci(
            task_deltas,
            samples=self.spec.bootstrap_samples,
            confidence=float(self.spec.confidence),
            seed=ci_seed,
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
                item["mean_delta"] > float(self.spec.min_effect)
                for item in per_seed
            )
        )
        status, reason = self._classify_delta(
            name,
            mean_delta,
            ci_low,
            ci_high,
            reproducible,
            degenerate,
            per_seed,
        )
        return {
            "treatment": ADAPTER_ON,
            "control": (
                SHUFFLED_LABELS
                if name == COMPARISON_SHUFFLED
                else name.removeprefix("adapter_on_vs_")
            ),
            "n_tasks": len(task_deltas),
            "n_seeds": len(self.spec.seeds),
            "mean_delta": mean_delta,
            "ci_low": ci_low,
            "ci_high": ci_high,
            "confidence": float(self.spec.confidence),
            "bootstrap_samples": self.spec.bootstrap_samples,
            "bootstrap_seed": ci_seed,
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
        name: str,
        mean_delta: float,
        ci_low: float | None,
        ci_high: float | None,
        reproducible: bool,
        degenerate: bool,
        per_seed: list[Mapping[str, Any]],
    ) -> tuple[str, str]:
        if degenerate:
            return (
                CHECK_INCONCLUSIVE,
                f"{name}: label control is degenerate because the effective "
                "shuffle shift is zero",
            )
        if mean_delta <= float(self.spec.min_effect):
            return (
                CHECK_FAIL,
                f"{name}: mean delta {mean_delta:.6f} is not above "
                f"min_effect {float(self.spec.min_effect):.6f}",
            )
        if ci_low is None or ci_high is None:
            return (
                CHECK_INCONCLUSIVE,
                f"{name}: paired bootstrap needs at least two tasks",
            )
        if ci_low <= float(self.spec.min_effect):
            return (
                CHECK_INCONCLUSIVE,
                f"{name}: {float(self.spec.confidence):.0%} CI lower bound "
                f"{ci_low:.6f} is not above min_effect "
                f"{float(self.spec.min_effect):.6f}",
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
            f"{float(self.spec.confidence):.0%} CI "
            f"[{ci_low:.6f}, {ci_high:.6f}]",
        )

    def _gate_checks(
        self,
        task_set: AblationTaskSet,
        dataset: Mapping[str, Any],
        deltas: Mapping[str, Mapping[str, Any]],
        shift: int,
        task_count: int,
    ) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []

        def add(name: str, status: str, detail: str) -> None:
            checks.append(
                {"name": name, "status": status, "detail": detail}
            )

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
            "adapter_scale_positive",
            CHECK_PASS
            if self.adapter_config.residual_scale > 0.0
            else CHECK_FAIL,
            f"residual_scale={self.adapter_config.residual_scale}",
        )
        add(
            "model_binding",
            CHECK_PASS,
            f"model_id matched base_model_id {self.base_model_id!r}",
        )
        add(
            "label_control_non_degenerate",
            CHECK_PASS if shift != 0 else CHECK_INCONCLUSIVE,
            f"effective label shift={shift} across {task_count} tasks",
        )
        add(
            "dataset_split_binding",
            CHECK_PASS,
            f"task_split_digest={dataset.get('task_split_digest')}",
        )
        check_names = {
            COMPARISON_BASE: "beats_base_only",
            COMPARISON_OFF: "beats_adapter_off",
            COMPARISON_ZERO: "beats_zero_residual",
            COMPARISON_SHUFFLED: "beats_shuffled_labels",
        }
        for comparison in COMPARISONS:
            delta = deltas[comparison]
            add(
                check_names[comparison],
                str(delta["status"]),
                str(delta["reason"]),
            )
        return checks

    @staticmethod
    def _combine_checks(
        checks: list[Mapping[str, Any]]
    ) -> tuple[str, list[str]]:
        statuses = {check["status"] for check in checks}
        if CHECK_FAIL in statuses:
            status = STATUS_REJECTED
        elif CHECK_INCONCLUSIVE in statuses:
            status = STATUS_INCONCLUSIVE
        else:
            status = STATUS_PASSED
        reasons = [
            f"{check['name']}: {check['detail']}"
            for check in checks
            if check["status"] != CHECK_PASS
        ]
        return status, reasons

    # -- Missing/inadmissible report -----------------------------------------

    def _inadmissible_report(
        self, task_set: AblationTaskSet | None, reason: str
    ) -> dict[str, Any]:
        if task_set is not None:
            dataset = task_set.to_evidence()
            dataset["missing"] = True
            dataset["admissible"] = False
        else:
            dataset = {
                "schema": SPLIT_SCHEMA,
                "dataset_id": None,
                "task_split_digest": None,
                "split": HELDOUT_SPLIT,
                "task_count": 0,
                "task_ids": [],
                "excluded_task_count": 0,
                "excluded_task_ids": [],
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
            "schema": ABLATION_SCHEMA,
            "harness_version": HARNESS_VERSION,
            "mode": "control-plane",
            "status": status,
            "evidence_level": status,
            "passed": False,
            "claim": dict(CLAIM_SCOPE),
            "base_model_id": self.base_model_id,
            "adapter_config_digest": self.adapter_config_digest,
            "task_split_digest": dataset.get("task_split_digest"),
            "model": {
                "reported_id": None,
                "binding_verified": False,
                "frozen": "no model bound",
            },
            "adapter": {
                "config": self.adapter_config.to_dict(),
                "config_digest": self.adapter_config_digest,
                "evidence_level_before": self.adapter_config.evidence_level,
                "recommended_evidence_level": status,
            },
            "dataset": dataset,
            "protocol": {
                **self.spec.to_dict(),
                "model_conditions": list(MODEL_CONDITIONS),
                "controls": list(CONTROLS),
                "comparisons": list(COMPARISONS),
                "normalization": (
                    "strip, collapse whitespace, and casefold before matching"
                ),
                "bootstrap_unit": "task (per-task mean over seeds)",
            },
            "residual_executor": {
                "executor_id": None,
                "native_evidence": None,
                "native_verified_by_harness": False,
            },
            "call_counts": {
                "encode": 0,
                "predict": 0,
                "residual_executor": 0,
                "expected": {
                    "encode": 0,
                    "predict": 0,
                    "residual_executor": 0,
                },
                "matches_expected": True,
                "per_task_seed": {
                    "encode": 1,
                    "predict": len(MODEL_CONDITIONS),
                    "residual_executor": 3,
                },
                "note": "No hook was called because no held-out data was run.",
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


def run_lm_adapter_ablation(
    adapter_config: WaveAdapterConfig | Mapping[str, Any],
    task_set: AblationTaskSet | None = None,
    *,
    frozen_model: Any = None,
    residual_executor: Any = None,
    spec: AblationSpec | None = None,
) -> dict[str, Any]:
    """Convenience wrapper around :class:`LMAdapterAblation`."""
    return LMAdapterAblation(adapter_config, spec=spec).run(
        task_set,
        frozen_model=frozen_model,
        residual_executor=residual_executor,
    )
