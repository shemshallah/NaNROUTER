"""NmpPlan: an additive context wrapper around the frozen MthPlan v1 record.

``MthPlan`` serialization is intentionally frozen.  ``NmpPlan`` binds the plan
to the candidate, admission, snapshot, ruleset, capability set, numerical
policy, and peak workspace without mutating or reinterpreting the v1 record.
It is host-control metadata; it performs no mathematics and grants no
authorization.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Mapping

from .math_objects import canonical_json
from .mth_registry import MthPlan

SCHEMA = "nanrouter.nmp-plan.v2"
WRAPPER_VERSION = 2


class NmpPlanError(ValueError):
    """Malformed or inconsistent NmpPlan context."""


def _text(value: Any, name: str, *, maximum: int = 512,
          allow_empty: bool = True) -> str:
    if not isinstance(value, str) or len(value) > maximum or (
        not allow_empty and not value
    ):
        raise NmpPlanError(f"{name} must be a string <= {maximum}")
    return value


def _digest(value: Any, name: str, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or len(value) != 64 or any(
        ch not in "0123456789abcdef" for ch in value
    ):
        raise NmpPlanError(f"{name} must be lowercase SHA-256 hex")
    return value


def _plan_digest(plan: MthPlan) -> str:
    return hashlib.sha256(canonical_json(plan.to_dict()).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class NmpPlan:
    plan: MthPlan
    candidate_id: str
    snapshot_id: str
    admission_id: str | None = None
    preflight_digest: str | None = None
    ruleset_snapshot_id: str = ""
    capability_set_digest: str = ""
    numerical_policy: Mapping[str, Any] = field(default_factory=dict)
    peak_workspace_words: int = 0
    plan_digest: str = ""
    wrapper_version: int = WRAPPER_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.plan, MthPlan):
            raise NmpPlanError("plan must be an MthPlan")
        object.__setattr__(
            self, "candidate_id",
            _text(self.candidate_id, "candidate_id", allow_empty=False),
        )
        object.__setattr__(
            self, "snapshot_id",
            _text(self.snapshot_id, "snapshot_id", allow_empty=False),
        )
        for name in ("admission_id", "preflight_digest"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(
                    self, name, _text(value, name, maximum=512)
                )
        if self.admission_id is not None and not self.admission_id.startswith("adm:"):
            raise NmpPlanError("admission_id must start with adm:")
        if self.preflight_digest is not None and not self.preflight_digest.startswith("pf:"):
            raise NmpPlanError("preflight_digest must start with pf:")
        object.__setattr__(
            self, "ruleset_snapshot_id",
            _text(self.ruleset_snapshot_id, "ruleset_snapshot_id"),
        )
        object.__setattr__(
            self, "capability_set_digest",
            _text(self.capability_set_digest, "capability_set_digest"),
        )
        if self.peak_workspace_words < 0 or isinstance(
            self.peak_workspace_words, bool
        ) or not isinstance(self.peak_workspace_words, int):
            raise NmpPlanError("peak_workspace_words must be a non-negative integer")
        if self.wrapper_version != WRAPPER_VERSION:
            raise NmpPlanError(
                f"wrapper_version must be {WRAPPER_VERSION}"
            )
        object.__setattr__(self, "numerical_policy", dict(self.numerical_policy or {}))
        expected = _plan_digest(self.plan)
        if self.plan_digest:
            if self.plan_digest != expected:
                raise NmpPlanError("plan_digest does not match the wrapped plan")
        else:
            object.__setattr__(self, "plan_digest", expected)

    @classmethod
    def from_compiled(cls, compiled: Any) -> "NmpPlan":
        """Build from a CompiledMathPlan without importing the runtime module."""
        plan = getattr(compiled, "plan", None)
        candidate = getattr(compiled, "candidate", None)
        admission = getattr(compiled, "admission", None)
        if not isinstance(plan, MthPlan) or candidate is None or admission is None:
            raise NmpPlanError("compiled object lacks plan/candidate/admission")
        capabilities = getattr(admission, "scope", {}).get("capability", {})
        selected = capabilities.get("selected") or {}
        capability_digest = capabilities.get("context_digest") or ""
        return cls(
            plan=plan,
            candidate_id=str(getattr(candidate, "candidate_id", "")),
            snapshot_id=str(getattr(admission, "snapshot_id", "")),
            admission_id=getattr(admission, "admission_id", None),
            preflight_digest=getattr(admission, "preflight_digest", None),
            ruleset_snapshot_id=str(getattr(admission, "rule_snapshot_id", "")),
            capability_set_digest=str(selected.get("kernel_id") or capability_digest),
            numerical_policy=getattr(plan, "numerical_policy", {}) or {},
            peak_workspace_words=int(getattr(compiled, "workspace_words", 0)),
        )

    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self.to_dict()).encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "wrapper_version": self.wrapper_version,
            "plan_digest": self.plan_digest,
            "candidate_id": self.candidate_id,
            "snapshot_id": self.snapshot_id,
            "admission_id": self.admission_id,
            "preflight_digest": self.preflight_digest,
            "ruleset_snapshot_id": self.ruleset_snapshot_id,
            "capability_set_digest": self.capability_set_digest,
            "numerical_policy": dict(self.numerical_policy),
            "peak_workspace_words": self.peak_workspace_words,
            "plan": self.plan.to_dict(),
        }


__all__ = ["NmpPlan", "NmpPlanError", "SCHEMA", "WRAPPER_VERSION"]
