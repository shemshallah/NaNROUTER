"""Typed absence algebra for GAME_PLAN_:: (P7).

`ZERO`, `NULL`, `VOID`, `EMPTY`, `UNDEFINED`, `INFINITY`, `UNKNOWN`, `ERROR`,
and `CANCELLED` are distinct control-plane states.  This module never treats
absence as numeric zero and never uses a host-language numeric computation.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping

from .math_objects import MathLeaf

ZERO = "ZERO"
NULL = "NULL"
VOID = "VOID"
EMPTY = "EMPTY"
UNDEFINED = "UNDEFINED"
INFINITY = "INFINITY"
UNKNOWN = "UNKNOWN"
ERROR = "ERROR"
CANCELLED = "CANCELLED"

ABSENCE_STATES = frozenset({
    ZERO, NULL, VOID, EMPTY, UNDEFINED, INFINITY, UNKNOWN, ERROR, CANCELLED,
})
_RESULT_STATES = frozenset({NULL, VOID, UNDEFINED, UNKNOWN, ERROR, CANCELLED})


class AbsenceError(ValueError):
    """Invalid absence record or conjunction."""


@dataclass(frozen=True)
class AbsenceResult:
    state: str
    reason: str = ""
    leaf: MathLeaf | None = None
    parents: tuple[dict[str, Any], ...] = ()
    failure_class: str = ""
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.state not in ABSENCE_STATES:
            raise AbsenceError(f"unknown absence state: {self.state!r}")
        if self.state in _RESULT_STATES and not (self.reason or self.failure_class):
            raise AbsenceError("a terminal absence result requires a reason/failure_class")
        if self.leaf is not None and not isinstance(self.leaf, MathLeaf):
            raise AbsenceError("leaf must be a MathLeaf or None")

    @property
    def terminal(self) -> bool:
        return self.state in _RESULT_STATES

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "nanrouter.math-absence.v1",
            "state": self.state,
            "reason": self.reason,
            "failure_class": self.failure_class,
            "parents": [dict(item) for item in self.parents],
            "leaf": None if self.leaf is None else self.leaf.to_dict(),
            "metadata": dict(self.metadata or {}),
        }


def _state(value: Any) -> str:
    if not isinstance(value, str) or value.upper() not in ABSENCE_STATES:
        raise AbsenceError(f"unknown absence state: {value!r}")
    return value.upper()


class AbsenceAlgebra:
    """Deterministic, non-numeric absence/undefinedness semantics."""

    def classify(self, value: Any) -> str:
        if isinstance(value, AbsenceResult):
            return value.state
        if isinstance(value, MathLeaf):
            if value.kind in {"null", "void", "undefined", "unknown", "error"}:
                return value.kind.upper()
            return ZERO if value.kind == "scalar" else EMPTY
        if value is None:
            return UNKNOWN
        if isinstance(value, (tuple, list, dict, set)) and not value:
            return EMPTY
        if isinstance(value, bool):
            return ZERO
        if isinstance(value, (int, float)):
            raise AbsenceError(
                "raw host numbers are not an absence algebra input; use a typed leaf"
            )
        return EMPTY

    def to_leaf(
        self,
        state: str,
        *,
        reason: str = "",
        failure_class: str = "",
        parents: tuple[dict[str, Any], ...] = (),
        metadata: Mapping[str, Any] | None = None,
        leaf_id: str | None = None,
    ) -> MathLeaf:
        state = _state(state)
        if state not in _RESULT_STATES:
            raise AbsenceError("only terminal states produce absence leaves")
        payload = dict(metadata or {})
        payload.setdefault("reason", reason or failure_class or state)
        if failure_class:
            payload.setdefault("failure_class", failure_class)
        stable = json.dumps(
            {"state": state, "reason": reason, "failure_class": failure_class,
             "payload": payload},
            sort_keys=True, separators=(",", ":"),
        )
        digest = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24]
        return MathLeaf(
            leaf_id=leaf_id or f"nml:U0:{state.lower()}:{digest}",
            kind=state.lower(),
            type={"element": "opaque", "shape": []},
            content=None,
            parents=parents,
            status="committed",
            metadata=payload,
        )

    def _present(self, value: Any) -> bool:
        if isinstance(value, MathLeaf):
            return value.kind not in {"null", "void", "undefined", "unknown",
                                      "error", "cancelled"}
        if value is None:
            return False
        if isinstance(value, (tuple, list, dict, set)):
            return bool(value)
        return not isinstance(value, (int, float)) or isinstance(value, bool)

    def conjoin(self, left: Any, right: Any, *,
                missing_is_unknown: bool = True) -> AbsenceResult:
        """Apply the explicit absence conjunction table.

        Presence is represented by a non-absence typed leaf/value.  This is a
        control-plane policy result, not a mathematical operation.
        """
        left_state = self.classify(left)
        right_state = self.classify(right)
        if self._present(left) and self._present(right):
            return AbsenceResult(EMPTY, "BOTH_PRESENT")
        parents = ()
        for item in (left, right):
            if isinstance(item, MathLeaf):
                parents = parents + (
                    {"leaf_id": item.leaf_id, "version": item.version,
                     "content_digest": item.content_digest, "role": "operand"},
                )
        if NULL in (left_state, right_state):
            return AbsenceResult(NULL, "NULL_OPERAND", parents=parents,
                                 failure_class="NULL_OPERAND")
        if UNDEFINED in (left_state, right_state):
            return AbsenceResult(UNDEFINED, "UNDEFINED_OPERAND", parents=parents,
                                 failure_class="UNDEFINED_OPERAND")
        if ERROR in (left_state, right_state):
            return AbsenceResult(ERROR, "EXECUTION_ERROR", parents=parents,
                                 failure_class="EXECUTION_ERROR")
        if CANCELLED in (left_state, right_state):
            return AbsenceResult(CANCELLED, "CANCELLED_OPERAND", parents=parents,
                                 failure_class="CANCELLED_OPERAND")
        if ZERO in (left_state, right_state):
            return AbsenceResult(ZERO, "ZERO_IS_PRESENT", parents=parents)
        if INFINITY in (left_state, right_state):
            return AbsenceResult(INFINITY, "EXTENDED_VALUE", parents=parents)
        if VOID in (left_state, right_state):
            if left_state == VOID and right_state == VOID:
                return AbsenceResult(VOID, "VOID_VOID", parents=parents,
                                     failure_class="NO_OBJECT")
            return AbsenceResult(
                UNKNOWN if missing_is_unknown else ERROR,
                "MISSING_REQUIRED_OBJECT",
                parents=parents,
                failure_class="MISSING_REQUIRED_OBJECT",
            )
        if EMPTY in (left_state, right_state):
            return AbsenceResult(EMPTY, "EMPTY_STRUCTURE", parents=parents)
        # Two present operands are outside the absence algebra.
        return AbsenceResult(EMPTY, "BOTH_PRESENT", parents=parents)

    def require_present(self, value: Any) -> Any:
        state = self.classify(value)
        if state in _RESULT_STATES:
            raise AbsenceError(f"required object is absent: {state}")
        return value


__all__ = [
    "ABSENCE_STATES", "AbsenceAlgebra", "AbsenceError", "AbsenceResult",
    "CANCELLED", "EMPTY", "ERROR", "INFINITY", "NULL", "UNDEFINED", "UNKNOWN",
    "VOID", "ZERO",
]
