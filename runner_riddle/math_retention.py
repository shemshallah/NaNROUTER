"""Bounded oscillation, retention scoring, and structural pruning (P10).

This module is a control plane.  It does not execute a mathematical function,
evaluate a mathematical value, or delete canonical mathematical content.  It
consumes typed :mod:`runner_riddle.math_objects` records and the mapping view
owned by :class:`runner_riddle.math_store.MathStore`.

The three cooperating pieces are deliberately separate:

* :class:`OscillationState` bounds depth, fan-out, fuel, candidate count,
  duplicate rediscovery, and rewrite cycles.  It only records stop reasons; it
  never drives an executor.
* :class:`RetentionPolicy` and :class:`TierController` score declared integer
  features and apply deterministic hysteresis/dwell to tier changes.  A score
  can choose a cache tier; it can never change truth, proof, or validity.
* :class:`PrunePlanner`, :func:`shadow_evaluate`, and
  :func:`apply_prune_plan` build and gate a structural plan over MathStore
  mappings.  Archival and tombstones are append-only retention events; a
  restore creates a new retention generation.  Cache eviction removes only a
  disposable preflight cache row.

Truth, proof, refutation, and audit records are protected.  A protected object
is always retained and is re-verified by the prune shadow gate before any plan
is allowed to run.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import re
from typing import Any, Callable, Iterable, Mapping

from .math_objects import (
    MathFunction,
    MathLeaf,
    MathObjectError,
    MathRule,
    canonical_json,
    digest_object,
)
from .math_store import (
    MAPPING_OBJECT_TYPES,
    MathReferenceError,
    MathStore,
    MathStoreError,
    StaleGenerationError,
)

RETENTION_SCHEMA = "nanrouter.math-retention.v1"
RETENTION_RECORD_SCHEMA = "nanrouter.math-retention-record.v1"
RETENTION_EVENT_SCHEMA = "nanrouter.math-retention-event.v1"
OSCILLATION_SCHEMA = "nanrouter.math-oscillation.v1"
PRUNE_PLAN_SCHEMA = "nanrouter.math-prune-plan.v1"
SHADOW_SCHEMA = "nanrouter.math-prune-shadow.v1"

RETENTION_ACTOR = "math_retention"

STOP_DEPTH_LIMIT = "depth_limit"
STOP_FANOUT_LIMIT = "fanout_limit"
STOP_FUEL_EXHAUSTED = "fuel_exhausted"
STOP_CANDIDATE_LIMIT = "candidate_limit"
STOP_DUPLICATE_STATE = "duplicate_state"
STOP_NO_PROGRESS = "no_progress"
STOP_REWRITE_CYCLE = "rewrite_cycle"
STOP_OPERATOR_CANCELLED = "operator_cancelled"
STOP_CONTRADICTION = "contradiction"

STOP_REASONS = frozenset({
    STOP_DEPTH_LIMIT,
    STOP_FANOUT_LIMIT,
    STOP_FUEL_EXHAUSTED,
    STOP_CANDIDATE_LIMIT,
    STOP_DUPLICATE_STATE,
    STOP_NO_PROGRESS,
    STOP_REWRITE_CYCLE,
    STOP_OPERATOR_CANCELLED,
    STOP_CONTRADICTION,
})

PRUNE_ACTIONS = frozenset({"archive", "tombstone", "retain"})
LIFECYCLE_STATES = frozenset({"active", "archived", "tombstoned"})

PROTECTED_PROOF_STATUSES = frozenset({
    "proven", "verified", "checked", "axiom", "refuted", "rejected",
})
PROTECTED_TRUTH_STATUSES = frozenset({
    "definitional", "theorem", "proven", "verified", "true", "axiom",
    "refuted", "rejected", "counterexample",
})
REFUTATION_KEYS = frozenset({
    "refutation", "refuted", "counterexample", "counterexample_digest",
})

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class MathRetentionError(ValueError):
    """Base error for retention, oscillation, and pruning control records."""


class RetentionBudgetError(MathRetentionError):
    """A declared oscillation or retention budget is invalid."""


class RetentionGateError(MathRetentionError):
    """A prune plan failed the shadow gate or a protected-object check."""


class RetentionPlanError(MathRetentionError):
    """A pruning plan is malformed, stale, or internally inconsistent."""


class RetentionConflictError(MathRetentionError):
    """A retention-generation compare-and-swap is stale."""


class RetentionLedgerError(MathRetentionError):
    """Append-only retention evidence cannot be replayed."""


# ---------------------------------------------------------------------------
# small validators
# ---------------------------------------------------------------------------


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _require_int(value: Any, name: str, *, minimum: int | None = 0,
                 maximum: int | None = None) -> int:
    if not _is_int(value):
        raise MathRetentionError(f"{name} must be an integer")
    if minimum is not None and value < minimum:
        raise MathRetentionError(f"{name} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise MathRetentionError(f"{name} must be <= {maximum}")
    return value


def _require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise MathRetentionError(f"{name} must be a boolean")
    return value


def _require_text(value: Any, name: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise MathRetentionError(
            f"{name} must be a non-empty string <= {maximum} characters"
        )
    return value


def _require_digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise MathRetentionError(f"{name} must be 64 lowercase hex characters")
    return value


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MathRetentionError(f"{name} must be an object")
    return dict(value)


def _tier_value(value: Any) -> "RetentionTier":
    if isinstance(value, RetentionTier):
        return value
    if isinstance(value, str):
        try:
            return RetentionTier(value)
        except ValueError as exc:
            raise MathRetentionError(f"unknown retention tier: {value!r}") from exc
    raise MathRetentionError(f"unknown retention tier: {value!r}")


# ---------------------------------------------------------------------------
# tiers
# ---------------------------------------------------------------------------


class RetentionTier(str, Enum):
    """Storage classes from GAME_PLAN_:: section 14.4.

    ``SCRATCH`` is explicit non-authoritative work; ``ACTIVE`` is hot but
    disposable on the cache side; ``PERSISTENT`` is canonical and retained;
    ``ARCHIVED`` is cold, recoverable, and never the only copy of a truth.
    """

    SCRATCH = "scratch"
    ACTIVE = "active"
    PERSISTENT = "persistent"
    ARCHIVED = "archived"


@dataclass(frozen=True)
class TierPolicy:
    """Declared eviction policy for one tier.

    No tier permits deleting a canonical mathematical payload.  ``evictable``
    refers only to cache/scratch copies; the canonical store remains the
    authority.
    """

    tier: RetentionTier
    rank: int
    evictable: bool
    canonical: bool
    permits_payload_delete: bool = False
    description: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "tier", _tier_value(self.tier))
        _require_int(self.rank, "rank", minimum=0)
        _require_bool(self.evictable, "evictable")
        _require_bool(self.canonical, "canonical")
        _require_bool(self.permits_payload_delete, "permits_payload_delete")
        if self.permits_payload_delete:
            raise MathRetentionError(
                "no retention tier may delete canonical mathematical payloads"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier.value,
            "rank": self.rank,
            "evictable": self.evictable,
            "canonical": self.canonical,
            "permits_payload_delete": self.permits_payload_delete,
            "description": self.description,
        }


TIER_POLICIES: dict[RetentionTier, TierPolicy] = {
    RetentionTier.SCRATCH: TierPolicy(
        RetentionTier.SCRATCH, 0, True, False,
        description="non-authoritative, bounded scratch",
    ),
    RetentionTier.ARCHIVED: TierPolicy(
        RetentionTier.ARCHIVED, 1, False, True,
        description="cold, recoverable, canonical content retained",
    ),
    RetentionTier.ACTIVE: TierPolicy(
        RetentionTier.ACTIVE, 2, True, True,
        description="hot working set; cache copies may be evicted",
    ),
    RetentionTier.PERSISTENT: TierPolicy(
        RetentionTier.PERSISTENT, 3, False, True,
        description="canonical mapping/version, retained",
    ),
}

# Convenience aliases used by integration code.
TIERS = TIER_POLICIES
ACTIVE_TIER = RetentionTier.ACTIVE
PERSISTENT_TIER = RetentionTier.PERSISTENT
ARCHIVED_TIER = RetentionTier.ARCHIVED
SCRATCH_TIER = RetentionTier.SCRATCH


def tier_policy(tier: RetentionTier | str) -> TierPolicy:
    return TIER_POLICIES[_tier_value(tier)]


# ---------------------------------------------------------------------------
# retention scoring
# ---------------------------------------------------------------------------

FEATURE_NAMES = (
    "utility",
    "relation_importance",
    "derivation_value",
    "predictive_usefulness",
    "recompute_savings",
    "storage_cost",
    "dependency_count",
    "reuse_count",
)

_FEATURE_ALIASES = {
    "utility": "utility",
    "u": "utility",
    "relation_importance": "relation_importance",
    "relation": "relation_importance",
    "importance": "relation_importance",
    "derivation_value": "derivation_value",
    "derivation": "derivation_value",
    "predictive_usefulness": "predictive_usefulness",
    "predictive": "predictive_usefulness",
    "recompute_savings": "recompute_savings",
    "recompute": "recompute_savings",
    "storage_cost": "storage_cost",
    "cost": "storage_cost",
    "dependency_count": "dependency_count",
    "dependencies": "dependency_count",
    "reuse_count": "reuse_count",
    "reuse": "reuse_count",
}


@dataclass(frozen=True)
class RetentionFeatures:
    """Declared integer features.  No host floating-point math is accepted."""

    utility: int = 0
    relation_importance: int = 0
    derivation_value: int = 0
    predictive_usefulness: int = 0
    recompute_savings: int = 0
    storage_cost: int = 0
    dependency_count: int = 0
    reuse_count: int = 0

    def __post_init__(self) -> None:
        for name in FEATURE_NAMES:
            _require_int(getattr(self, name), name, minimum=0)

    @classmethod
    def from_value(cls, value: Any, *,
                   allow_unknown: bool = False) -> "RetentionFeatures":
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        document = _require_mapping(value, "retention features")
        fields: dict[str, int] = {}
        for raw_key, raw_value in document.items():
            key = _FEATURE_ALIASES.get(str(raw_key))
            if key is None:
                if allow_unknown:
                    continue
                raise MathRetentionError(
                    f"unknown retention feature: {raw_key!r}"
                )
            if key in fields and fields[key] != raw_value:
                raise MathRetentionError(
                    f"conflicting values for retention feature {key!r}"
                )
            fields[key] = _require_int(raw_value, key, minimum=0)
        return cls(**fields)

    def to_dict(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in FEATURE_NAMES}


@dataclass(frozen=True)
class RetentionWeights:
    """Integer policy weights for ``R(x)``.

    Using integers keeps score computation exact and platform-independent.  A
    deployment that needs finer granularity scales all weights and features by
    a declared common factor instead of introducing host floats.
    """

    utility: int = 4
    relation_importance: int = 3
    derivation_value: int = 3
    predictive_usefulness: int = 2
    recompute_savings: int = 2
    storage_cost: int = 1

    _WEIGHT_NAMES = (
        "utility",
        "relation_importance",
        "derivation_value",
        "predictive_usefulness",
        "recompute_savings",
        "storage_cost",
    )

    def __post_init__(self) -> None:
        for name in self._WEIGHT_NAMES:
            _require_int(getattr(self, name), name, minimum=0)

    @classmethod
    def from_value(cls, value: Any) -> "RetentionWeights":
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        document = _require_mapping(value, "retention weights")
        unknown = set(document) - set(cls._WEIGHT_NAMES)
        if unknown:
            raise MathRetentionError(
                f"unknown retention weight(s): {', '.join(sorted(unknown))}"
            )
        return cls(**{name: document[name] for name in document})

    def to_dict(self) -> dict[str, int]:
        return {name: getattr(self, name) for name in self._WEIGHT_NAMES}


@dataclass(frozen=True)
class RetentionScore:
    """Exact integer score with a deterministic component breakdown."""

    score: int
    components: tuple[tuple[str, int], ...]
    features_digest: str
    weights_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RETENTION_SCHEMA,
            "score": self.score,
            "components": [[name, value] for name, value in self.components],
            "features_digest": self.features_digest,
            "weights_digest": self.weights_digest,
        }

    def digest(self) -> str:
        return digest_object(self.to_dict())


class RetentionScorer:
    """Deterministic integer scorer for declared retention features."""

    def __init__(self, weights: RetentionWeights | Mapping[str, Any] | None = None) -> None:
        self.weights = RetentionWeights.from_value(weights)

    def score(self, features: RetentionFeatures | Mapping[str, Any]) -> RetentionScore:
        value = RetentionFeatures.from_value(features)
        positive = (
            ("utility", value.utility),
            ("relation_importance", value.relation_importance),
            ("derivation_value", value.derivation_value),
            ("predictive_usefulness", value.predictive_usefulness),
            ("recompute_savings", value.recompute_savings),
        )
        components = [
            (name, int(getattr(self.weights, name)) * amount)
            for name, amount in positive
        ]
        components.append(
            ("storage_cost", -int(self.weights.storage_cost) * value.storage_cost)
        )
        components.sort(key=lambda item: item[0])
        score = sum(amount for _, amount in components)
        return RetentionScore(
            score=score,
            components=tuple(components),
            features_digest=digest_object(value.to_dict()),
            weights_digest=digest_object(self.weights.to_dict()),
        )

    def __call__(self,
                 features: RetentionFeatures | Mapping[str, Any]) -> RetentionScore:
        return self.score(features)


def score_retention(features: RetentionFeatures | Mapping[str, Any],
                    weights: RetentionWeights | Mapping[str, Any] | None = None
                    ) -> RetentionScore:
    return RetentionScorer(weights).score(features)


def retention_score(features: RetentionFeatures | Mapping[str, Any],
                    weights: RetentionWeights | Mapping[str, Any] | None = None
                    ) -> int:
    return score_retention(features, weights).score


# ---------------------------------------------------------------------------
# tier hysteresis / dwell
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetentionPolicy:
    """Integer tier thresholds plus hysteresis/dwell policy."""

    weights: RetentionWeights = field(default_factory=RetentionWeights)
    archive_below: int = -10
    persistent_min: int = 20
    tombstone_below: int = -40
    hysteresis: int = 2
    dwell_ticks: int = 2
    max_actions: int = 1024

    def __post_init__(self) -> None:
        object.__setattr__(self, "weights", RetentionWeights.from_value(self.weights))
        _require_int(self.archive_below, "archive_below", minimum=None)
        _require_int(self.persistent_min, "persistent_min", minimum=None)
        _require_int(self.tombstone_below, "tombstone_below", minimum=None)
        _require_int(self.hysteresis, "hysteresis", minimum=0)
        _require_int(self.dwell_ticks, "dwell_ticks", minimum=1)
        _require_int(self.max_actions, "max_actions", minimum=1)
        if self.archive_below >= self.persistent_min:
            raise RetentionBudgetError(
                "archive_below must be below persistent_min"
            )
        if self.tombstone_below > self.archive_below:
            raise RetentionBudgetError(
                "tombstone_below must be <= archive_below"
            )

    def tier_for_score(self, score: int, *, protected: bool = False) -> RetentionTier:
        _require_int(score, "score", minimum=None)
        if protected:
            return RetentionTier.PERSISTENT
        if score < self.tombstone_below:
            return RetentionTier.ARCHIVED
        if score < self.archive_below:
            return RetentionTier.ARCHIVED
        if score >= self.persistent_min:
            return RetentionTier.PERSISTENT
        return RetentionTier.ACTIVE

    def action_for_score(self, score: int, *, protected: bool = False) -> str:
        if protected:
            return "retain"
        tier = self.tier_for_score(score)
        if tier is not RetentionTier.ARCHIVED:
            return "retain"
        if score < self.tombstone_below:
            return "tombstone"
        return "archive"

    def lower_bound(self, tier: RetentionTier | str) -> int | None:
        tier = _tier_value(tier)
        if tier is RetentionTier.PERSISTENT:
            return self.persistent_min
        if tier is RetentionTier.ACTIVE:
            return self.archive_below
        return None

    def upper_bound(self, tier: RetentionTier | str) -> int | None:
        tier = _tier_value(tier)
        if tier is RetentionTier.ARCHIVED:
            return self.archive_below - 1
        if tier is RetentionTier.ACTIVE:
            return self.persistent_min - 1
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "weights": self.weights.to_dict(),
            "archive_below": self.archive_below,
            "persistent_min": self.persistent_min,
            "tombstone_below": self.tombstone_below,
            "hysteresis": self.hysteresis,
            "dwell_ticks": self.dwell_ticks,
            "max_actions": self.max_actions,
        }


@dataclass
class _TierState:
    tier: RetentionTier
    pending: RetentionTier | None = None
    streak: int = 0


@dataclass(frozen=True)
class TierDecision:
    """One deterministic tier observation."""

    key: str
    score: int
    tier: RetentionTier
    candidate_tier: RetentionTier
    changed: bool
    dwell: int
    required_dwell: int
    hysteresis_blocked: bool
    protected: bool
    reason: str
    tick: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "score": self.score,
            "tier": self.tier.value,
            "candidate_tier": self.candidate_tier.value,
            "changed": self.changed,
            "dwell": self.dwell,
            "required_dwell": self.required_dwell,
            "hysteresis_blocked": self.hysteresis_blocked,
            "protected": self.protected,
            "reason": self.reason,
            "tick": self.tick,
        }


class TierController:
    """Track tier changes with hysteresis and dwell.

    A tier move toward a higher retention class requires the candidate's lower
    bound plus ``hysteresis``.  A move down requires the candidate's upper
    bound minus ``hysteresis``.  A candidate must persist for ``dwell_ticks``
    observations before the tier actually changes.
    """

    def __init__(self, policy: RetentionPolicy | None = None) -> None:
        self.policy = policy or RetentionPolicy()
        self._states: dict[str, _TierState] = {}

    def reset(self) -> None:
        self._states.clear()

    def tier_of(self, key: str) -> RetentionTier | None:
        state = self._states.get(key)
        return None if state is None else state.tier

    def observe(self, key: str, score: int, *, tick: int = 0,
                protected: bool = False) -> TierDecision:
        _require_text(key, "key", maximum=300)
        _require_int(score, "score", minimum=None)
        _require_int(tick, "tick")
        _require_bool(protected, "protected")
        candidate = self.policy.tier_for_score(score, protected=protected)
        state = self._states.get(key)
        if state is None:
            self._states[key] = _TierState(tier=candidate)
            return TierDecision(
                key=key, score=score, tier=candidate, candidate_tier=candidate,
                changed=True, dwell=1,
                required_dwell=self.policy.dwell_ticks,
                hysteresis_blocked=False, protected=protected,
                reason="initial", tick=tick,
            )

        current = state.tier
        if protected and current.rank < RetentionTier.PERSISTENT.rank:
            state.tier = RetentionTier.PERSISTENT
            state.pending = None
            state.streak = 0
            return TierDecision(
                key=key, score=score, tier=state.tier,
                candidate_tier=RetentionTier.PERSISTENT, changed=True,
                dwell=1, required_dwell=self.policy.dwell_ticks,
                hysteresis_blocked=False, protected=True,
                reason="protected_persistent", tick=tick,
            )

        if candidate is current:
            state.pending = None
            state.streak = 0
            return TierDecision(
                key=key, score=score, tier=current, candidate_tier=candidate,
                changed=False, dwell=0,
                required_dwell=self.policy.dwell_ticks,
                hysteresis_blocked=False, protected=protected,
                reason="stable", tick=tick,
            )

        blocked = not self._passes_hysteresis(current, candidate, score,
                                              protected=protected)
        if blocked:
            state.pending = None
            state.streak = 0
            return TierDecision(
                key=key, score=score, tier=current, candidate_tier=candidate,
                changed=False, dwell=0,
                required_dwell=self.policy.dwell_ticks,
                hysteresis_blocked=True, protected=protected,
                reason="hysteresis", tick=tick,
            )

        if state.pending is candidate:
            state.streak += 1
        else:
            state.pending = candidate
            state.streak = 1
        if state.streak < self.policy.dwell_ticks:
            return TierDecision(
                key=key, score=score, tier=current, candidate_tier=candidate,
                changed=False, dwell=state.streak,
                required_dwell=self.policy.dwell_ticks,
                hysteresis_blocked=False, protected=protected,
                reason="dwell", tick=tick,
            )

        state.tier = candidate
        state.pending = None
        state.streak = 0
        return TierDecision(
            key=key, score=score, tier=candidate, candidate_tier=candidate,
            changed=True, dwell=self.policy.dwell_ticks,
            required_dwell=self.policy.dwell_ticks,
            hysteresis_blocked=False, protected=protected,
            reason="dwell_elapsed", tick=tick,
        )

    def _passes_hysteresis(self, current: RetentionTier,
                           candidate: RetentionTier, score: int, *,
                           protected: bool) -> bool:
        if protected:
            return True
        if candidate.rank > current.rank:
            lower = self.policy.lower_bound(candidate)
            return lower is not None and score >= lower + self.policy.hysteresis
        if candidate.rank < current.rank:
            upper = self.policy.upper_bound(candidate)
            return upper is None or score <= upper - self.policy.hysteresis
        return True


TierTracker = TierController


# ---------------------------------------------------------------------------
# bounded oscillation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OscillationBudget:
    """Static bounds for one oscillation run."""

    max_depth: int = 8
    max_fanout: int = 8
    fuel: int = 1024
    max_candidates: int = 64
    max_flips: int = 3
    dwell_ticks: int = 2
    hysteresis: int = 0

    def __post_init__(self) -> None:
        _require_int(self.max_depth, "max_depth", minimum=0)
        _require_int(self.max_fanout, "max_fanout", minimum=0)
        _require_int(self.fuel, "fuel", minimum=0)
        _require_int(self.max_candidates, "max_candidates", minimum=0)
        _require_int(self.max_flips, "max_flips", minimum=0)
        _require_int(self.dwell_ticks, "dwell_ticks", minimum=1)
        _require_int(self.hysteresis, "hysteresis", minimum=0)

    @classmethod
    def from_value(cls, value: Any) -> "OscillationBudget":
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        document = _require_mapping(value, "oscillation budget")
        aliases = {
            "max_depth": "max_depth",
            "depth": "max_depth",
            "max_fanout": "max_fanout",
            "fanout": "max_fanout",
            "max_fanout_per_step": "max_fanout",
            "fuel": "fuel",
            "max_fuel": "fuel",
            "max_candidates": "max_candidates",
            "candidate_budget": "max_candidates",
            "candidate_count": "max_candidates",
            "max_flips": "max_flips",
            "flip_budget": "max_flips",
            "dwell_ticks": "dwell_ticks",
            "dwell": "dwell_ticks",
            "hysteresis": "hysteresis",
        }
        values: dict[str, int] = {}
        for key, raw in document.items():
            target = aliases.get(str(key))
            if target is None:
                raise RetentionBudgetError(f"unknown oscillation budget: {key!r}")
            values[target] = _require_int(raw, target, minimum=0)
        return cls(**values)

    def to_dict(self) -> dict[str, int]:
        return {
            "max_depth": self.max_depth,
            "max_fanout": self.max_fanout,
            "fuel": self.fuel,
            "max_candidates": self.max_candidates,
            "max_flips": self.max_flips,
            "dwell_ticks": self.dwell_ticks,
            "hysteresis": self.hysteresis,
        }


@dataclass(frozen=True)
class RewriteCycleVerdict:
    detected: bool
    quarantined: bool
    flips: int
    cycle: tuple[str, ...]
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "detected": self.detected,
            "quarantined": self.quarantined,
            "flips": self.flips,
            "cycle": list(self.cycle),
            "reason": self.reason,
        }


class RewriteCycleDetector:
    """Detect non-consecutive rewrite repeats and enforce a flip budget.

    Consecutive repeats are duplicates and are left to
    :class:`OscillationState`.  A repeat after at least one different rewrite
    key is a cycle.  Quarantine occurs when the flip count reaches both the
    declared flip budget and the dwell threshold, plus optional hysteresis.
    """

    def __init__(self, *, max_flips: int = 3, dwell_ticks: int = 2,
                 hysteresis: int = 0) -> None:
        _require_int(max_flips, "max_flips", minimum=0)
        _require_int(dwell_ticks, "dwell_ticks", minimum=1)
        _require_int(hysteresis, "hysteresis", minimum=0)
        self.max_flips = max_flips
        self.dwell_ticks = dwell_ticks
        self.hysteresis = hysteresis
        self._history: list[tuple[str, int]] = []
        self.flips = 0
        self.cycle: tuple[str, ...] = ()

    @property
    def history(self) -> tuple[tuple[str, int], ...]:
        return tuple(self._history)

    def observe(self, key: str, tick: int = 0) -> RewriteCycleVerdict:
        _require_text(key, "rewrite key", maximum=512)
        _require_int(tick, "tick")
        if self._history and self._history[-1][0] == key:
            return RewriteCycleVerdict(
                detected=False, quarantined=False, flips=self.flips,
                cycle=self.cycle, reason="consecutive_duplicate",
            )
        positions = [index for index, (seen, _) in enumerate(self._history)
                     if seen == key]
        self._history.append((key, tick))
        if not positions:
            return RewriteCycleVerdict(
                detected=False, quarantined=False, flips=self.flips,
                cycle=self.cycle,
            )
        first = positions[0]
        cycle = tuple(seen for seen, _ in self._history[first:])
        self.flips += 1
        self.cycle = cycle
        required = max(self.max_flips, self.dwell_ticks) + self.hysteresis
        quarantined = self.flips >= required and len(cycle) >= 2
        return RewriteCycleVerdict(
            detected=True,
            quarantined=quarantined,
            flips=self.flips,
            cycle=cycle,
            reason="rewrite_cycle_quarantine" if quarantined else "rewrite_cycle",
        )


CycleDetector = RewriteCycleDetector


@dataclass(frozen=True)
class OscillationOutcome:
    """Result of one bounded oscillation advance."""

    allowed: bool
    stop_reason: str | None
    depth: int
    fanout_used: int
    fuel_used: int
    candidate_count: int
    flips: int
    quarantined: bool
    duplicate: bool
    cycle: tuple[str, ...]
    tick: int
    state_key: str
    content_digest: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": OSCILLATION_SCHEMA,
            "allowed": self.allowed,
            "stop_reason": self.stop_reason,
            "depth": self.depth,
            "fanout_used": self.fanout_used,
            "fuel_used": self.fuel_used,
            "candidate_count": self.candidate_count,
            "flips": self.flips,
            "quarantined": self.quarantined,
            "duplicate": self.duplicate,
            "cycle": list(self.cycle),
            "tick": self.tick,
            "state_key": self.state_key,
            "content_digest": self.content_digest,
        }

    def digest(self) -> str:
        return digest_object(self.to_dict())


class OscillationState:
    """Bounded, non-executing oscillation tracker.

    ``advance`` consumes a declared state key and optional canonical content
    digest.  It returns an :class:`OscillationOutcome`; it never raises for a
    budget stop.  Subsequent calls after a stop return the same denied state
    until :meth:`reset` or :meth:`stop` with an explicit re-arm.
    """

    def __init__(self, budget: OscillationBudget | Mapping[str, Any] | None = None,
                 *, snapshot_id: str = "snp:unspecified",
                 cycle_detector: RewriteCycleDetector | None = None,
                 rewrite_cycle_hook: Callable[..., Any] | None = None) -> None:
        self.budget = OscillationBudget.from_value(budget)
        self.snapshot_id = _require_text(snapshot_id, "snapshot_id", maximum=300)
        self.cycle_detector = cycle_detector or RewriteCycleDetector(
            max_flips=self.budget.max_flips,
            dwell_ticks=self.budget.dwell_ticks,
            hysteresis=self.budget.hysteresis,
        )
        self.rewrite_cycle_hook = rewrite_cycle_hook
        self.depth = 0
        self.fanout_used = 0
        self.fuel_used = 0
        self.candidate_count = 0
        self.flips = 0
        self.quarantined = False
        self.stop_reason: str | None = None
        self.cycle: tuple[str, ...] = ()
        self.tick = 0
        self._last_state_key: str | None = None
        self._seen_state_keys: set[str] = set()
        self._seen_content: set[str] = set()
        self._last_outcome: OscillationOutcome | None = None

    @property
    def stopped(self) -> bool:
        return self.stop_reason is not None

    def reset(self) -> None:
        self.depth = 0
        self.fanout_used = 0
        self.fuel_used = 0
        self.candidate_count = 0
        self.flips = 0
        self.quarantined = False
        self.stop_reason = None
        self.cycle = ()
        self.tick = 0
        self._last_state_key = None
        self._seen_state_keys.clear()
        self._seen_content.clear()
        self._last_outcome = None
        self.cycle_detector = RewriteCycleDetector(
            max_flips=self.budget.max_flips,
            dwell_ticks=self.budget.dwell_ticks,
            hysteresis=self.budget.hysteresis,
        )

    def stop(self, reason: str, *, quarantined: bool = False) -> OscillationOutcome:
        _require_text(reason, "stop reason", maximum=128)
        if reason not in STOP_REASONS:
            raise MathRetentionError(f"unknown oscillation stop reason: {reason!r}")
        _require_bool(quarantined, "quarantined")
        self.stop_reason = reason
        self.quarantined = self.quarantined or quarantined
        return self._outcome(
            allowed=False, stop_reason=reason,
            state_key=self._last_state_key or "",
            content_digest=None, duplicate=False,
        )

    def advance(self, *, state_key: str, content_digest: str | None = None,
                rewrite_key: str | None = None, fanout: int = 1,
                fuel: int = 1, candidates: int = 1,
                depth: int | None = None, tick: int | None = None
                ) -> OscillationOutcome:
        _require_text(state_key, "state_key", maximum=512)
        if content_digest is not None:
            _require_text(content_digest, "content_digest", maximum=512)
        if rewrite_key is not None:
            _require_text(rewrite_key, "rewrite_key", maximum=512)
        _require_int(fanout, "fanout", minimum=0)
        _require_int(fuel, "fuel", minimum=0)
        _require_int(candidates, "candidates", minimum=0)
        step_depth = 1 if depth is None else _require_int(depth, "depth", minimum=0)
        step_tick = self.tick + 1 if tick is None else _require_int(tick, "tick")

        if self.stop_reason is not None:
            return self._outcome(
                allowed=False, stop_reason=self.stop_reason,
                state_key=state_key, content_digest=content_digest,
                duplicate=False,
            )

        if self.depth + step_depth > self.budget.max_depth:
            return self._deny(STOP_DEPTH_LIMIT, state_key, content_digest)
        if self.fanout_used + fanout > self.budget.max_fanout:
            return self._deny(STOP_FANOUT_LIMIT, state_key, content_digest)
        if self.fuel_used + fuel > self.budget.fuel:
            return self._deny(STOP_FUEL_EXHAUSTED, state_key, content_digest)
        if self.candidate_count + candidates > self.budget.max_candidates:
            return self._deny(STOP_CANDIDATE_LIMIT, state_key, content_digest)

        # A consecutive identical state key is duplicate rediscovery.  A
        # repeated content digest is no-progress even when the rewrite form
        # changed, because no new canonical content was produced.
        if state_key == self._last_state_key:
            return self._deny(STOP_DUPLICATE_STATE, state_key, content_digest,
                              duplicate=True)
        if content_digest is not None and content_digest in self._seen_content:
            return self._deny(STOP_NO_PROGRESS, state_key, content_digest)

        verdict = self._observe_cycle(rewrite_key or state_key, step_tick)
        if verdict is not None:
            self.flips = max(self.flips, int(verdict.get("flips", self.flips)))
            cycle = tuple(verdict.get("cycle") or ())
            if cycle:
                self.cycle = cycle
            if bool(verdict.get("quarantined", False)):
                self.quarantined = True
                return self._deny(STOP_REWRITE_CYCLE, state_key, content_digest,
                                  cycle=self.cycle)
            if bool(verdict.get("detected", False)) and not self.cycle:
                self.cycle = cycle

        self.tick = step_tick
        self.depth += step_depth
        self.fanout_used += fanout
        self.fuel_used += fuel
        self.candidate_count += candidates
        self._last_state_key = state_key
        self._seen_state_keys.add(state_key)
        if content_digest is not None:
            self._seen_content.add(content_digest)
        return self._outcome(
            allowed=True, stop_reason=None, state_key=state_key,
            content_digest=content_digest, duplicate=False,
        )

    observe = advance
    step = advance

    def _observe_cycle(self, key: str, tick: int) -> dict[str, Any] | None:
        hook = self.rewrite_cycle_hook
        if hook is not None:
            if hasattr(hook, "observe"):
                result = hook.observe(key, tick)
            else:
                result = hook(key, tick)
            if isinstance(result, RewriteCycleVerdict):
                return result.to_dict()
            if isinstance(result, Mapping):
                return dict(result)
            if isinstance(result, bool):
                return {
                    "detected": result,
                    "quarantined": result,
                    "flips": self.flips + (1 if result else 0),
                    "cycle": (key,) if result else (),
                    "reason": "hook",
                }
            raise MathRetentionError(
                "rewrite cycle hook must return a verdict, mapping, or bool"
            )
        if self.cycle_detector is None:
            return None
        return self.cycle_detector.observe(key, tick).to_dict()

    def _deny(self, reason: str, state_key: str,
              content_digest: str | None, *,
              duplicate: bool = False,
              cycle: tuple[str, ...] = ()) -> OscillationOutcome:
        self.stop_reason = reason
        return self._outcome(
            allowed=False, stop_reason=reason, state_key=state_key,
            content_digest=content_digest, duplicate=duplicate, cycle=cycle,
        )

    def _outcome(self, *, allowed: bool, stop_reason: str | None,
                 state_key: str, content_digest: str | None,
                 duplicate: bool,
                 cycle: tuple[str, ...] = ()) -> OscillationOutcome:
        outcome = OscillationOutcome(
            allowed=allowed,
            stop_reason=stop_reason,
            depth=self.depth,
            fanout_used=self.fanout_used,
            fuel_used=self.fuel_used,
            candidate_count=self.candidate_count,
            flips=self.flips,
            quarantined=self.quarantined,
            duplicate=duplicate,
            cycle=self.cycle if not cycle else cycle,
            tick=self.tick,
            state_key=state_key,
            content_digest=content_digest,
        )
        self._last_outcome = outcome
        return outcome

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": OSCILLATION_SCHEMA,
            "snapshot_id": self.snapshot_id,
            "budget": self.budget.to_dict(),
            "depth": self.depth,
            "fanout_used": self.fanout_used,
            "fuel_used": self.fuel_used,
            "candidate_count": self.candidate_count,
            "flips": self.flips,
            "quarantined": self.quarantined,
            "stop_reason": self.stop_reason,
            "cycle": list(self.cycle),
            "tick": self.tick,
            "seen_state_keys": sorted(self._seen_state_keys),
            "seen_content": sorted(self._seen_content),
            "last_outcome": (
                None if self._last_outcome is None
                else self._last_outcome.to_dict()
            ),
        }

    def digest(self) -> str:
        return digest_object(self.to_dict())


# ---------------------------------------------------------------------------
# truth / proof / refutation protection
# ---------------------------------------------------------------------------


def _status_strings(container: Mapping[str, Any],
                    keys: Iterable[str]) -> Iterable[tuple[str, str]]:
    for key in keys:
        if key not in container:
            continue
        value = container[key]
        if isinstance(value, Mapping):
            status = value.get("status")
            if isinstance(status, str) and status:
                yield key, status.lower()
        elif isinstance(value, str) and value:
            yield key, value.lower()
        elif value is True:
            yield key, "true"


def protection_reasons(obj: Any, object_type: str | None = None
                       ) -> tuple[str, ...]:
    """Return declared truth/proof/refutation protection reasons.

    The function is structural.  It reads object kind/status/metadata only and
    never interprets mathematical content.
    """
    reasons: set[str] = set()
    if object_type == "relation" or obj is None:
        reasons.add("relation_unscored")
        return tuple(sorted(reasons))

    if isinstance(obj, MathLeaf):
        object_type = object_type or "leaf"
        if obj.kind in {"proof", "certificate"}:
            reasons.add(f"proof_kind:{obj.kind}")
        metadata = dict(obj.metadata)
        for key, status in _status_strings(
                metadata, ("truth_status", "truth", "proof_status", "proof")):
            if key.startswith("truth"):
                if status not in {"open", "unknown", "none", "false"}:
                    reasons.add(f"truth:{status}")
            elif status in PROTECTED_PROOF_STATUSES:
                reasons.add(f"proof:{status}")
        for key in REFUTATION_KEYS:
            if key in metadata and metadata[key] not in (None, False, "", {}):
                reasons.add("refutation")
    elif isinstance(obj, MathRule):
        object_type = object_type or "rule"
        if obj.proof_status in PROTECTED_PROOF_STATUSES:
            reasons.add(f"proof:{obj.proof_status}")
        contract = dict(obj.contract)
        for key, status in _status_strings(
                contract, ("truth_status", "truth", "proof_status", "proof")):
            if key.startswith("truth"):
                if status not in {"open", "unknown", "none", "false"}:
                    reasons.add(f"truth:{status}")
            elif status in PROTECTED_PROOF_STATUSES:
                reasons.add(f"proof:{status}")
        for key in REFUTATION_KEYS:
            if key in contract and contract[key] not in (None, False, "", {}):
                reasons.add("refutation")
    elif isinstance(obj, MathFunction):
        object_type = object_type or "function"
        if obj.proof_status in PROTECTED_PROOF_STATUSES:
            reasons.add(f"proof:{obj.proof_status}")
        semantics = dict(obj.semantics)
        for key, status in _status_strings(
                semantics, ("truth_status", "truth", "proof_status", "proof")):
            if key.startswith("truth"):
                if status not in {"open", "unknown", "none", "false"}:
                    reasons.add(f"truth:{status}")
            elif status in PROTECTED_PROOF_STATUSES:
                reasons.add(f"proof:{status}")
    return tuple(sorted(reasons))


def is_protected(obj: Any, object_type: str | None = None) -> bool:
    return bool(protection_reasons(obj, object_type))


# ---------------------------------------------------------------------------
# pruning plan records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PreservedObject:
    """A truth/proof/refutation version that a plan promises to preserve."""

    object_type: str
    object_id: str
    version: int
    target_digest: str
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.object_type not in MAPPING_OBJECT_TYPES:
            raise RetentionPlanError(
                f"unknown preserved object_type: {self.object_type!r}"
            )
        _require_text(self.object_id, "object_id", maximum=200)
        _require_int(self.version, "version", minimum=1)
        _require_digest(self.target_digest, "target_digest")
        object.__setattr__(self, "reasons", tuple(
            _require_text(reason, "preservation reason", maximum=256)
            for reason in self.reasons
        ))

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_type": self.object_type,
            "object_id": self.object_id,
            "version": self.version,
            "digest": self.target_digest,
            "reasons": list(self.reasons),
        }

    def digest(self) -> str:
        return digest_object(self.to_dict())


@dataclass(frozen=True)
class PruneAction:
    """One structural action over an existing MathStore mapping."""

    action: str
    mapping_id: str
    object_type: str
    object_id: str
    version: int
    target_digest: str
    expected_version: int
    expected_generation: int
    target_tier: RetentionTier = RetentionTier.ARCHIVED
    score: int = 0
    protected: bool = False
    protection: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.action not in PRUNE_ACTIONS:
            raise RetentionPlanError(f"unknown prune action: {self.action!r}")
        _require_text(self.mapping_id, "mapping_id", maximum=300)
        if self.object_type not in MAPPING_OBJECT_TYPES:
            raise RetentionPlanError(
                f"unknown object_type: {self.object_type!r}"
            )
        _require_text(self.object_id, "object_id", maximum=200)
        _require_int(self.version, "version", minimum=1)
        _require_digest(self.target_digest, "target_digest")
        _require_int(self.expected_version, "expected_version", minimum=0)
        _require_int(self.expected_generation, "expected_generation", minimum=0)
        _require_int(self.score, "score", minimum=None)
        _require_bool(self.protected, "protected")
        object.__setattr__(self, "target_tier", _tier_value(self.target_tier))
        object.__setattr__(self, "protection", tuple(
            _require_text(item, "protection reason", maximum=256)
            for item in self.protection
        ))
        object.__setattr__(self, "reasons", tuple(
            _require_text(item, "prune reason", maximum=256)
            for item in self.reasons
        ))
        object.__setattr__(self, "metadata", dict(self.metadata))
        canonical_json(self.metadata)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "mapping_id": self.mapping_id,
            "object_type": self.object_type,
            "object_id": self.object_id,
            "version": self.version,
            "digest": self.target_digest,
            "expected_version": self.expected_version,
            "expected_generation": self.expected_generation,
            "target_tier": self.target_tier.value,
            "score": self.score,
            "protected": self.protected,
            "protection": list(self.protection),
            "reasons": list(self.reasons),
            "metadata": dict(self.metadata),
        }

    def digest(self) -> str:
        return digest_object(self.to_dict())


@dataclass(frozen=True)
class PrunePlan:
    """Immutable structural pruning plan with CAS preconditions."""

    plan_id: str
    actions: tuple[PruneAction, ...]
    cache_keys: tuple[str, ...]
    source_digest: str
    created_tick: int = 0
    preserved: tuple[PreservedObject, ...] = ()
    omitted_actions: int = 0
    shadow_required: bool = True

    def __post_init__(self) -> None:
        actions = tuple(self.actions)
        for action in actions:
            if not isinstance(action, PruneAction):
                raise RetentionPlanError("actions must be PruneAction records")
        object.__setattr__(self, "actions", actions)
        keys = tuple(sorted(set(self.cache_keys)))
        for key in keys:
            _require_text(key, "cache key", maximum=300)
        object.__setattr__(self, "cache_keys", keys)
        preserved = tuple(self.preserved)
        for item in preserved:
            if not isinstance(item, PreservedObject):
                raise RetentionPlanError(
                    "preserved entries must be PreservedObject records"
                )
        object.__setattr__(self, "preserved", preserved)
        _require_digest(self.source_digest, "source_digest")
        _require_int(self.created_tick, "created_tick")
        _require_int(self.omitted_actions, "omitted_actions")
        _require_bool(self.shadow_required, "shadow_required")
        expected_id = "prn:" + digest_object(self._content_dict())
        if self.plan_id == "":
            object.__setattr__(self, "plan_id", expected_id)
        elif self.plan_id != expected_id:
            raise RetentionPlanError(
                "plan_id does not match the canonical plan content"
            )

    def _content_dict(self) -> dict[str, Any]:
        return {
            "schema": PRUNE_PLAN_SCHEMA,
            "actions": [action.to_dict() for action in self.actions],
            "cache_keys": list(self.cache_keys),
            "source_digest": self.source_digest,
            "created_tick": self.created_tick,
            "preserved": [item.to_dict() for item in self.preserved],
            "omitted_actions": self.omitted_actions,
            "shadow_required": self.shadow_required,
        }

    @property
    def truth_digests(self) -> tuple[str, ...]:
        return tuple(sorted({item.target_digest for item in self.preserved}))

    @property
    def destructive_actions(self) -> tuple[PruneAction, ...]:
        return tuple(action for action in self.actions
                     if action.action in {"archive", "tombstone"})

    def to_dict(self) -> dict[str, Any]:
        document = self._content_dict()
        document["plan_id"] = self.plan_id
        return document

    def digest(self) -> str:
        return digest_object(self._content_dict())


@dataclass(frozen=True)
class ShadowEvaluation:
    """Result of the prune shadow-evaluation gate."""

    plan_id: str
    approved: bool
    actions: tuple[dict[str, Any], ...]
    reasons: tuple[str, ...]
    preserved: tuple[PreservedObject, ...] = ()
    cache_keys: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SHADOW_SCHEMA,
            "plan_id": self.plan_id,
            "approved": self.approved,
            "actions": [dict(item) for item in self.actions],
            "reasons": list(self.reasons),
            "preserved": [item.to_dict() for item in self.preserved],
            "cache_keys": list(self.cache_keys),
        }

    def digest(self) -> str:
        return digest_object(self.to_dict())


@dataclass(frozen=True)
class PruneResult:
    """Applied/rolled-back prune result."""

    plan_id: str
    applied: tuple["RetentionRecord", ...] = ()
    cache_evicted: tuple[str, ...] = ()
    rolled_back: bool = False
    reasons: tuple[str, ...] = ()
    shadow: ShadowEvaluation | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "applied": [record.to_dict() for record in self.applied],
            "cache_evicted": list(self.cache_evicted),
            "rolled_back": self.rolled_back,
            "reasons": list(self.reasons),
            "shadow": None if self.shadow is None else self.shadow.to_dict(),
        }

    def digest(self) -> str:
        return digest_object(self.to_dict())


# ---------------------------------------------------------------------------
# object access and declared features
# ---------------------------------------------------------------------------


def _load_object(store: MathStore, object_type: str, object_id: str,
                 version: int) -> Any | None:
    try:
        if object_type == "leaf":
            return store.get_leaf(object_id, version=version)
        if object_type == "function":
            return store.get_function(object_id, version=version)
        if object_type == "rule":
            return store.get_rule(object_id, version=version)
        if object_type == "relation":
            return None
        raise RetentionPlanError(f"unknown object_type: {object_type!r}")
    except (MathStoreError, MathObjectError) as exc:
        raise RetentionPlanError(
            f"cannot load {object_type} {object_id!r}@{version}"
        ) from exc


def _object_digest(obj: Any, object_type: str) -> str | None:
    if object_type == "leaf" and isinstance(obj, MathLeaf):
        return obj.digest()
    if object_type == "function" and isinstance(obj, MathFunction):
        return obj.digest()
    if object_type == "rule" and isinstance(obj, MathRule):
        return digest_object(obj.to_dict())
    return None


def _declared_metadata(obj: Any, object_type: str) -> dict[str, Any]:
    if object_type == "leaf" and isinstance(obj, MathLeaf):
        return dict(obj.metadata)
    if object_type == "rule" and isinstance(obj, MathRule):
        return dict(obj.contract)
    if object_type == "function" and isinstance(obj, MathFunction):
        return dict(obj.semantics)
    return {}


def features_for_object(obj: Any, object_type: str) -> RetentionFeatures:
    """Read declared integer features; derive only structural counts."""
    metadata = _declared_metadata(obj, object_type)
    declared = metadata.get("retention")
    if declared is None:
        declared = metadata.get("retention_features")
    if declared is None:
        declared = {}
    features = RetentionFeatures.from_value(declared, allow_unknown=True)
    if object_type == "leaf" and isinstance(obj, MathLeaf):
        if features.relation_importance == 0 and obj.parents:
            features = replace(features, relation_importance=len(obj.parents))
        if features.dependency_count == 0 and obj.parents:
            features = replace(features, dependency_count=len(obj.parents))
    return features


# ---------------------------------------------------------------------------
# planner
# ---------------------------------------------------------------------------


def _mapping_projection(row: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "mapping_id", "object_type", "object_id", "current_version",
        "generation", "target_digest", "storage_tier", "route", "status",
    )
    return {key: row.get(key) for key in keys}


class PrunePlanner:
    """Build a deterministic structural plan over MathStore mappings."""

    def __init__(self, policy: RetentionPolicy | None = None,
                 scorer: RetentionScorer | None = None) -> None:
        self.policy = policy or RetentionPolicy()
        self.scorer = scorer or RetentionScorer(self.policy.weights)

    def build(self, store: MathStore, *, tick: int = 0,
              cache_keys: Iterable[str] = (), max_actions: int | None = None,
              include_retain: bool = True) -> PrunePlan:
        if not isinstance(store, MathStore):
            raise RetentionPlanError("store must be a MathStore")
        _require_int(tick, "tick")
        limit = (self.policy.max_actions if max_actions is None
                 else _require_int(max_actions, "max_actions", minimum=1))
        rows = sorted(store.list_mappings(limit=65536),
                      key=lambda row: str(row.get("mapping_id", "")))
        source_digest = digest_object({
            "schema": PRUNE_PLAN_SCHEMA,
            "mappings": [_mapping_projection(row) for row in rows],
        })
        actions: list[PruneAction] = []
        preserved: list[PreservedObject] = []
        for row in rows:
            mapping_id = str(row["mapping_id"])
            object_type = str(row["object_type"])
            object_id = str(row["object_id"])
            version = int(row["current_version"])
            digest = str(row["target_digest"])
            expected_generation = int(row["generation"])
            try:
                obj = _load_object(store, object_type, object_id, version)
                protection = protection_reasons(obj, object_type)
                features = features_for_object(obj, object_type)
                score = self.scorer.score(features).score
            except (RetentionPlanError, MathRetentionError):
                protection = ("unresolved_object",)
                features = RetentionFeatures()
                score = 0
                obj = None
            if protection:
                action_name = "retain"
                target_tier = RetentionTier.PERSISTENT
                preserved.append(PreservedObject(
                    object_type=object_type,
                    object_id=object_id,
                    version=version,
                    target_digest=digest,
                    reasons=protection,
                ))
                reasons = ("protected",)
            else:
                action_name = self.policy.action_for_score(score)
                target_tier = (
                    RetentionTier.ARCHIVED
                    if action_name in {"archive", "tombstone"}
                    else self.policy.tier_for_score(score)
                )
                reasons = (
                    ("score_below_tombstone",)
                    if action_name == "tombstone"
                    else ("score_below_archive",)
                    if action_name == "archive"
                    else ("retained",)
                )
            if action_name == "retain" and not include_retain:
                continue
            actions.append(PruneAction(
                action=action_name,
                mapping_id=mapping_id,
                object_type=object_type,
                object_id=object_id,
                version=version,
                target_digest=digest,
                expected_version=version,
                expected_generation=expected_generation,
                target_tier=target_tier,
                score=score,
                protected=bool(protection),
                protection=tuple(protection),
                reasons=reasons,
                metadata={
                    "features": features.to_dict(),
                    "mapping_status": str(row.get("status", "")),
                    "storage_tier": str(row.get("storage_tier", "")),
                },
            ))
        total = len(actions)
        if total > limit:
            actions = actions[:limit]
            omitted = total - limit
        else:
            omitted = 0
        keys = tuple(sorted({_require_text(key, "cache key", maximum=300)
                             for key in cache_keys}))
        return PrunePlan(
            plan_id="",
            actions=tuple(actions),
            cache_keys=keys,
            source_digest=source_digest,
            created_tick=tick,
            preserved=tuple(preserved),
            omitted_actions=omitted,
        )

    plan = build


def plan_pruning(store: MathStore, *, policy: RetentionPolicy | None = None,
                 tick: int = 0, cache_keys: Iterable[str] = (),
                 max_actions: int | None = None,
                 include_retain: bool = True) -> PrunePlan:
    return PrunePlanner(policy).build(
        store, tick=tick, cache_keys=cache_keys,
        max_actions=max_actions, include_retain=include_retain,
    )


# ---------------------------------------------------------------------------
# shadow-evaluation gate
# ---------------------------------------------------------------------------


def _mapping_rows_by_id(store: MathStore) -> dict[str, dict[str, Any]]:
    return {str(row["mapping_id"]): row
            for row in store.list_mappings(limit=65536)}


def _shadow_action(store: MathStore, action: PruneAction,
                   rows: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "mapping_id": action.mapping_id,
        "action": action.action,
        "approved": False,
        "protected": False,
        "reason": "",
    }
    if action.action not in PRUNE_ACTIONS:
        result["reason"] = "unknown_action"
        return result
    row = rows.get(action.mapping_id)
    if row is None:
        result["reason"] = "mapping_missing"
        return result
    if (str(row["object_type"]) != action.object_type
            or str(row["object_id"]) != action.object_id):
        result["reason"] = "mapping_identity_mismatch"
        return result
    if (int(row["current_version"]) != action.expected_version
            or int(row["generation"]) != action.expected_generation):
        result["reason"] = "cas_stale"
        return result
    if (int(row["current_version"]) != action.version
            or str(row["target_digest"]) != action.target_digest):
        result["reason"] = "mapping_content_mismatch"
        return result
    if action.action == "retain":
        result["approved"] = True
        result["reason"] = "retained"
        return result

    try:
        obj = _load_object(store, action.object_type, action.object_id,
                           action.version)
    except RetentionPlanError:
        result["reason"] = "unresolved_object"
        return result
    protection = protection_reasons(obj, action.object_type)
    if protection:
        result["protected"] = True
        result["reason"] = "protected:" + ",".join(protection)
        return result
    if action.protected:
        result["protected"] = True
        result["reason"] = "plan_marks_protected"
        return result
    digest = _object_digest(obj, action.object_type)
    if digest is not None and digest != action.target_digest:
        result["reason"] = "object_digest_mismatch"
        return result
    result["approved"] = True
    result["reason"] = "shadow_ok"
    return result


def _shadow_preserved(store: MathStore, item: PreservedObject,
                      rows: Mapping[str, Mapping[str, Any]]) -> str | None:
    if item.object_type == "relation":
        for row in rows.values():
            if (str(row["object_type"]) == "relation"
                    and str(row["object_id"]) == item.object_id
                    and int(row["current_version"]) == item.version
                    and str(row["target_digest"]) == item.target_digest):
                return None
        return f"preserved_missing:{item.object_type}:{item.object_id}@{item.version}"
    try:
        obj = _load_object(store, item.object_type, item.object_id, item.version)
    except RetentionPlanError:
        return f"preserved_missing:{item.object_type}:{item.object_id}@{item.version}"
    digest = _object_digest(obj, item.object_type)
    if digest != item.target_digest:
        return f"preserved_digest:{item.object_type}:{item.object_id}@{item.version}"
    return None


def shadow_evaluate(store: MathStore, plan: PrunePlan, *,
                    verify_preserved: bool = True) -> ShadowEvaluation:
    """Evaluate a plan without mutating it.

    The gate checks mapping identity, CAS version/generation, target digest,
    actual object protection, and every promised truth/proof/refutation
    version.  Any failure blocks the whole plan by default.
    """
    if not isinstance(store, MathStore):
        raise RetentionPlanError("store must be a MathStore")
    if not isinstance(plan, PrunePlan):
        raise RetentionPlanError("plan must be a PrunePlan")
    rows = _mapping_rows_by_id(store)
    results: list[dict[str, Any]] = []
    reasons: set[str] = set()
    for action in plan.actions:
        result = _shadow_action(store, action, rows)
        results.append(result)
        if not result["approved"]:
            reasons.add(f"{action.mapping_id}:{result['reason']}")
    if verify_preserved:
        for item in plan.preserved:
            failure = _shadow_preserved(store, item, rows)
            if failure is not None:
                reasons.add(failure)
    for key in plan.cache_keys:
        _require_text(key, "cache key", maximum=300)
    return ShadowEvaluation(
        plan_id=plan.plan_id,
        approved=not reasons,
        actions=tuple(results),
        reasons=tuple(sorted(reasons)),
        preserved=plan.preserved,
        cache_keys=plan.cache_keys,
    )


# ---------------------------------------------------------------------------
# retention ledger: archival, tombstone, restore
# ---------------------------------------------------------------------------


def _transition_mapping(store: MathStore, mapping_id: str, *,
                        expected_version: int, expected_generation: int
                        ) -> dict[str, Any]:
    try:
        row = store.get_mapping(mapping_id)
    except MathReferenceError as exc:
        raise RetentionConflictError(
            f"unknown mapping {mapping_id!r}"
        ) from exc
    if (int(row["current_version"]) != expected_version
            or int(row["generation"]) != expected_generation):
        raise StaleGenerationError(
            f"mapping {mapping_id!r} is at version "
            f"{row['current_version']} generation {row['generation']}, not "
            f"version {expected_version} generation {expected_generation}"
        )
    return row


@dataclass(frozen=True)
class RetentionRecord:
    """Append-only retention lifecycle record (not a math object)."""

    mapping_id: str
    object_type: str
    object_id: str
    mapping_version: int
    mapping_generation: int
    target_digest: str
    retention_generation: int
    state: str
    tier: RetentionTier
    restore_tier: RetentionTier
    score: int
    protected: bool
    protection: tuple[str, ...]
    reason: str
    plan_id: str
    created_tick: int
    updated_tick: int

    def __post_init__(self) -> None:
        _require_text(self.mapping_id, "mapping_id", maximum=300)
        if self.object_type not in MAPPING_OBJECT_TYPES:
            raise RetentionLedgerError(
                f"unknown object_type: {self.object_type!r}"
            )
        _require_text(self.object_id, "object_id", maximum=200)
        _require_int(self.mapping_version, "mapping_version", minimum=1)
        _require_int(self.mapping_generation, "mapping_generation", minimum=0)
        _require_digest(self.target_digest, "target_digest")
        _require_int(self.retention_generation, "retention_generation", minimum=1)
        if self.state not in LIFECYCLE_STATES:
            raise RetentionLedgerError(f"unknown retention state: {self.state!r}")
        object.__setattr__(self, "tier", _tier_value(self.tier))
        object.__setattr__(self, "restore_tier", _tier_value(self.restore_tier))
        _require_int(self.score, "score", minimum=None)
        _require_bool(self.protected, "protected")
        object.__setattr__(self, "protection", tuple(self.protection))
        _require_text(self.reason, "reason", maximum=512)
        _require_text(self.plan_id, "plan_id", maximum=128)
        _require_int(self.created_tick, "created_tick")
        _require_int(self.updated_tick, "updated_tick")

    @property
    def generation(self) -> int:
        """Alias for the retention generation (not the math mapping generation)."""
        return self.retention_generation

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RETENTION_RECORD_SCHEMA,
            "mapping_id": self.mapping_id,
            "object_type": self.object_type,
            "object_id": self.object_id,
            "mapping_version": self.mapping_version,
            "mapping_generation": self.mapping_generation,
            "target_digest": self.target_digest,
            "retention_generation": self.retention_generation,
            "generation": self.retention_generation,
            "state": self.state,
            "tier": self.tier.value,
            "restore_tier": self.restore_tier.value,
            "score": self.score,
            "protected": self.protected,
            "protection": list(self.protection),
            "reason": self.reason,
            "plan_id": self.plan_id,
            "created_tick": self.created_tick,
            "updated_tick": self.updated_tick,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RetentionRecord":
        document = dict(value)
        document.pop("schema", None)
        document.pop("generation", None)
        document["protected"] = bool(document.get("protected", False))
        document["protection"] = tuple(document.get("protection") or ())
        return cls(**document)

    def digest(self) -> str:
        return digest_object(self.to_dict())


class RetentionLedger:
    """Append-only retention overlay over MathStore mappings.

    The overlay never edits a mapping row or deletes an object version.  Every
    transition is appended as a ``mapping`` event with actor ``math_retention``
    and the full retention record.  Replaying those events reconstructs state.
    """

    def __init__(self, store: MathStore | None = None) -> None:
        self.store = store
        self._records: dict[str, RetentionRecord] = {}
        if store is not None:
            self.replay(store)

    @classmethod
    def from_store(cls, store: MathStore) -> "RetentionLedger":
        return cls(store)

    def replay(self, store: MathStore) -> None:
        if not isinstance(store, MathStore):
            raise RetentionLedgerError("store must be a MathStore")
        records: dict[str, RetentionRecord] = {}
        events = store.list_events(object_type="mapping", limit=65536)
        for event in events:
            if event.get("actor") != RETENTION_ACTOR:
                continue
            payload = event.get("payload")
            if not isinstance(payload, Mapping):
                continue
            if payload.get("schema") != RETENTION_EVENT_SCHEMA:
                continue
            raw = payload.get("record")
            if not isinstance(raw, Mapping):
                continue
            try:
                record = RetentionRecord.from_dict(raw)
            except (MathRetentionError, TypeError) as exc:
                raise RetentionLedgerError(
                    f"retention event {event.get('event_id')} is invalid"
                ) from exc
            previous = records.get(record.mapping_id)
            if (previous is not None
                    and record.retention_generation
                    <= previous.retention_generation):
                continue
            records[record.mapping_id] = record
        self.store = store
        self._records = records

    def record(self, mapping_id: str) -> RetentionRecord | None:
        _require_text(mapping_id, "mapping_id", maximum=300)
        return self._records.get(mapping_id)

    def records(self) -> tuple[RetentionRecord, ...]:
        return tuple(self._records[key] for key in sorted(self._records))

    def archive(self, store: MathStore, mapping_id: str, *,
                expected_version: int, expected_generation: int,
                score: int = 0, reason: str = "archive",
                plan_id: str = "", tick: int = 0) -> RetentionRecord:
        return self._transition(
            store, mapping_id, state="archived",
            expected_version=expected_version,
            expected_generation=expected_generation,
            score=score, reason=reason, plan_id=plan_id, tick=tick,
        )

    def tombstone(self, store: MathStore, mapping_id: str, *,
                  expected_version: int, expected_generation: int,
                  score: int = 0, reason: str = "tombstone",
                  plan_id: str = "", tick: int = 0) -> RetentionRecord:
        return self._transition(
            store, mapping_id, state="tombstoned",
            expected_version=expected_version,
            expected_generation=expected_generation,
            score=score, reason=reason, plan_id=plan_id, tick=tick,
        )

    def _transition(self, store: MathStore, mapping_id: str, *, state: str,
                    expected_version: int, expected_generation: int,
                    score: int, reason: str, plan_id: str,
                    tick: int) -> RetentionRecord:
        if not isinstance(store, MathStore):
            raise RetentionLedgerError("store must be a MathStore")
        _require_text(mapping_id, "mapping_id", maximum=300)
        _require_int(expected_version, "expected_version", minimum=1)
        _require_int(expected_generation, "expected_generation", minimum=1)
        _require_int(score, "score", minimum=None)
        _require_text(reason, "reason", maximum=512)
        _require_int(tick, "tick")
        row = _transition_mapping(
            store, mapping_id,
            expected_version=expected_version,
            expected_generation=expected_generation,
        )
        object_type = str(row["object_type"])
        object_id = str(row["object_id"])
        obj = _load_object(store, object_type, object_id,
                           int(row["current_version"]))
        protection = protection_reasons(obj, object_type)
        if protection:
            raise RetentionGateError(
                f"mapping {mapping_id!r} is protected: "
                f"{', '.join(protection)}"
            )
        current = self._records.get(mapping_id)
        if current is not None:
            if current.state == "tombstoned" and state == "archived":
                return current
            if (current.state == state
                    and current.mapping_version == int(row["current_version"])
                    and current.mapping_generation
                    == int(row["generation"])):
                return current
        generation = 1 if current is None else current.retention_generation + 1
        restore_tier = (
            RetentionTier.ACTIVE
            if current is None else current.restore_tier
        )
        record = RetentionRecord(
            mapping_id=mapping_id,
            object_type=object_type,
            object_id=object_id,
            mapping_version=int(row["current_version"]),
            mapping_generation=int(row["generation"]),
            target_digest=str(row["target_digest"]),
            retention_generation=generation,
            state=state,
            tier=RetentionTier.ARCHIVED,
            restore_tier=restore_tier,
            score=score,
            protected=False,
            protection=(),
            reason=reason,
            plan_id=plan_id,
            created_tick=(tick if current is None else current.created_tick),
            updated_tick=tick,
        )
        self._persist(store, record, action=state, tick=tick)
        self._records[mapping_id] = record
        return record

    def restore(self, store: MathStore, mapping_id: str, *,
                expected_generation: int | None = None,
                reason: str = "restore", tick: int = 0) -> RetentionRecord:
        if not isinstance(store, MathStore):
            raise RetentionLedgerError("store must be a MathStore")
        _require_text(mapping_id, "mapping_id", maximum=300)
        _require_text(reason, "reason", maximum=512)
        _require_int(tick, "tick")
        current = self._records.get(mapping_id)
        if current is None:
            raise RetentionConflictError(
                f"mapping {mapping_id!r} has no retention record to restore"
            )
        if expected_generation is not None:
            _require_int(expected_generation, "expected_generation", minimum=1)
            if current.retention_generation != expected_generation:
                raise RetentionConflictError(
                    f"retention record {mapping_id!r} is at generation "
                    f"{current.retention_generation}, not {expected_generation}"
                )
        if current.state == "active":
            return current
        row = _transition_mapping(
            store, mapping_id,
            expected_version=current.mapping_version,
            expected_generation=current.mapping_generation,
        )
        generation = current.retention_generation + 1
        record = RetentionRecord(
            mapping_id=current.mapping_id,
            object_type=str(row["object_type"]),
            object_id=str(row["object_id"]),
            mapping_version=int(row["current_version"]),
            mapping_generation=int(row["generation"]),
            target_digest=str(row["target_digest"]),
            retention_generation=generation,
            state="active",
            tier=current.restore_tier,
            restore_tier=current.restore_tier,
            score=current.score,
            protected=current.protected,
            protection=current.protection,
            reason=reason,
            plan_id=current.plan_id,
            created_tick=current.created_tick,
            updated_tick=tick,
        )
        self._persist(store, record, action="restore", tick=tick)
        self._records[mapping_id] = record
        return record

    rollback = restore

    def _persist(self, store: MathStore, record: RetentionRecord, *,
                 action: str, tick: int) -> None:
        store.append_event(
            "mapping", "mapping", record.mapping_id,
            version=record.mapping_version,
            generation=record.retention_generation,
            digest=record.target_digest,
            actor=RETENTION_ACTOR,
            payload={
                "schema": RETENTION_EVENT_SCHEMA,
                "action": action,
                "record": record.to_dict(),
            },
            tick=tick,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RETENTION_SCHEMA,
            "records": [record.to_dict() for record in self.records()],
        }

    def digest(self) -> str:
        return digest_object(self.to_dict())


# ---------------------------------------------------------------------------
# plan application / rollback
# ---------------------------------------------------------------------------


def apply_prune_plan(store: MathStore, plan: PrunePlan, *,
                     ledger: RetentionLedger | None = None,
                     tick: int = 0, require_shadow: bool = True,
                     dry_run: bool = False) -> PruneResult:
    """Apply a gated prune plan without deleting canonical content."""
    if not isinstance(store, MathStore):
        raise RetentionPlanError("store must be a MathStore")
    if not isinstance(plan, PrunePlan):
        raise RetentionPlanError("plan must be a PrunePlan")
    _require_int(tick, "tick")
    evaluation = shadow_evaluate(store, plan)
    if plan.shadow_required or require_shadow:
        if not evaluation.approved:
            raise RetentionGateError(
                "prune plan failed the shadow gate: "
                + ", ".join(evaluation.reasons)
            )
    ledger = ledger or RetentionLedger.from_store(store)
    if dry_run:
        return PruneResult(
            plan_id=plan.plan_id, applied=(),
            cache_evicted=(), rolled_back=False,
            reasons=("dry_run",), shadow=evaluation,
        )

    applied: list[RetentionRecord] = []
    changed: list[RetentionRecord] = []
    evicted: list[str] = []
    try:
        for action in plan.actions:
            if action.action == "retain":
                continue
            before = ledger.record(action.mapping_id)
            if action.action == "archive":
                record = ledger.archive(
                    store, action.mapping_id,
                    expected_version=action.expected_version,
                    expected_generation=action.expected_generation,
                    score=action.score, reason="prune_plan",
                    plan_id=plan.plan_id, tick=tick,
                )
            elif action.action == "tombstone":
                record = ledger.tombstone(
                    store, action.mapping_id,
                    expected_version=action.expected_version,
                    expected_generation=action.expected_generation,
                    score=action.score, reason="prune_plan",
                    plan_id=plan.plan_id, tick=tick,
                )
            else:
                continue
            applied.append(record)
            if before is None or record != before:
                changed.append(record)
        for key in plan.cache_keys:
            if store.invalidate_preflight_cache(key, tick=tick):
                evicted.append(key)
    except BaseException:
        # Compensate only records this call changed.  Restoring is itself an
        # append-only new generation, never a delete of the archive event.
        for record in reversed(changed):
            try:
                ledger.restore(
                    store, record.mapping_id,
                    expected_generation=record.retention_generation,
                    reason="plan_apply_rollback", tick=tick,
                )
            except MathRetentionError:
                pass
        raise
    return PruneResult(
        plan_id=plan.plan_id,
        applied=tuple(applied),
        cache_evicted=tuple(evicted),
        rolled_back=False,
        reasons=(),
        shadow=evaluation,
    )


def rollback_prune_plan(store: MathStore, plan: PrunePlan, *,
                        ledger: RetentionLedger | None = None,
                        tick: int = 0) -> PruneResult:
    """Restore archived/tombstoned mappings as new retention generations."""
    if not isinstance(store, MathStore):
        raise RetentionPlanError("store must be a MathStore")
    if not isinstance(plan, PrunePlan):
        raise RetentionPlanError("plan must be a PrunePlan")
    _require_int(tick, "tick")
    ledger = ledger or RetentionLedger.from_store(store)
    restored: list[RetentionRecord] = []
    reasons: list[str] = []
    for action in reversed(plan.actions):
        if action.action not in {"archive", "tombstone"}:
            continue
        record = ledger.record(action.mapping_id)
        if record is None or record.state == "active":
            reasons.append(f"{action.mapping_id}:already_active")
            continue
        try:
            restored.append(ledger.restore(
                store, action.mapping_id,
                expected_generation=record.retention_generation,
                reason="prune_plan_rollback", tick=tick,
            ))
        except (MathRetentionError, StaleGenerationError) as exc:
            reasons.append(f"{action.mapping_id}:{exc}")
    return PruneResult(
        plan_id=plan.plan_id,
        applied=tuple(restored),
        cache_evicted=(),
        rolled_back=True,
        reasons=tuple(reasons),
        shadow=None,
    )


def restore_mapping(store: MathStore, mapping_id: str, *,
                    ledger: RetentionLedger | None = None,
                    expected_generation: int | None = None,
                    tick: int = 0) -> RetentionRecord:
    ledger = ledger or RetentionLedger.from_store(store)
    return ledger.restore(
        store, mapping_id, expected_generation=expected_generation,
        reason="restore", tick=tick,
    )


# ---------------------------------------------------------------------------
# facade
# ---------------------------------------------------------------------------


class MathRetention:
    """Small facade over the scorer, planner, gate, and retention ledger."""

    def __init__(self, store: MathStore, *,
                 policy: RetentionPolicy | None = None,
                 ledger: RetentionLedger | None = None,
                 scorer: RetentionScorer | None = None) -> None:
        if not isinstance(store, MathStore):
            raise MathRetentionError("store must be a MathStore")
        self.store = store
        self.policy = policy or RetentionPolicy()
        self.scorer = scorer or RetentionScorer(self.policy.weights)
        self.planner = PrunePlanner(self.policy, self.scorer)
        self.ledger = ledger or RetentionLedger.from_store(store)

    def score(self, features: RetentionFeatures | Mapping[str, Any]
              ) -> RetentionScore:
        return self.scorer.score(features)

    def plan(self, *, tick: int = 0, cache_keys: Iterable[str] = (),
             max_actions: int | None = None,
             include_retain: bool = True) -> PrunePlan:
        return self.planner.build(
            self.store, tick=tick, cache_keys=cache_keys,
            max_actions=max_actions, include_retain=include_retain,
        )

    def shadow(self, plan: PrunePlan) -> ShadowEvaluation:
        return shadow_evaluate(self.store, plan)

    def apply(self, plan: PrunePlan, *, tick: int = 0,
              require_shadow: bool = True,
              dry_run: bool = False) -> PruneResult:
        return apply_prune_plan(
            self.store, plan, ledger=self.ledger, tick=tick,
            require_shadow=require_shadow, dry_run=dry_run,
        )

    def rollback(self, plan: PrunePlan, *, tick: int = 0) -> PruneResult:
        return rollback_prune_plan(
            self.store, plan, ledger=self.ledger, tick=tick,
        )

    def restore(self, mapping_id: str, *, expected_generation: int | None = None,
                tick: int = 0) -> RetentionRecord:
        return self.ledger.restore(
            self.store, mapping_id,
            expected_generation=expected_generation, tick=tick,
        )

    def record(self, mapping_id: str) -> RetentionRecord | None:
        return self.ledger.record(mapping_id)

    def records(self) -> tuple[RetentionRecord, ...]:
        return self.ledger.records()


RetentionController = MathRetention
PruneController = MathRetention
RetentionManager = MathRetention


__all__ = [
    "ARCHIVED_TIER",
    "ACTIVE_TIER",
    "CycleDetector",
    "LIFECYCLE_STATES",
    "MAPPING_OBJECT_TYPES",
    "MathRetention",
    "MathRetentionError",
    "OSCILLATION_SCHEMA",
    "OscillationBudget",
    "OscillationOutcome",
    "OscillationState",
    "PERSISTENT_TIER",
    "PRUNE_ACTIONS",
    "PRUNE_PLAN_SCHEMA",
    "PruneAction",
    "PruneController",
    "PrunePlan",
    "PrunePlanner",
    "PruneResult",
    "PreservedObject",
    "REFUTATION_KEYS",
    "RETENTION_ACTOR",
    "RETENTION_EVENT_SCHEMA",
    "RETENTION_RECORD_SCHEMA",
    "RETENTION_SCHEMA",
    "RetentionBudgetError",
    "RetentionConflictError",
    "RetentionController",
    "RetentionFeatures",
    "RetentionGateError",
    "RetentionLedger",
    "RetentionLedgerError",
    "RetentionManager",
    "RetentionPlanError",
    "RetentionPolicy",
    "RetentionRecord",
    "RetentionScore",
    "RetentionScorer",
    "RetentionTier",
    "RetentionWeights",
    "RewriteCycleDetector",
    "RewriteCycleVerdict",
    "SCRATCH_TIER",
    "SHADOW_SCHEMA",
    "STOP_CANDIDATE_LIMIT",
    "STOP_CONTRADICTION",
    "STOP_DEPTH_LIMIT",
    "STOP_DUPLICATE_STATE",
    "STOP_FANOUT_LIMIT",
    "STOP_FUEL_EXHAUSTED",
    "STOP_NO_PROGRESS",
    "STOP_OPERATOR_CANCELLED",
    "STOP_REASONS",
    "STOP_REWRITE_CYCLE",
    "ShadowEvaluation",
    "TIERS",
    "TIER_POLICIES",
    "TierController",
    "TierDecision",
    "TierPolicy",
    "TierTracker",
    "apply_prune_plan",
    "features_for_object",
    "is_protected",
    "plan_pruning",
    "protection_reasons",
    "restore_mapping",
    "retention_score",
    "rollback_prune_plan",
    "score_retention",
    "shadow_evaluate",
    "tier_policy",
]
