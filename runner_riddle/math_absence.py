"""Typed null/void/undefined algebra for GAME_PLAN_:: (P7).

This module defines the *absence* layer of the mathematical control plane.  It
never evaluates mathematics, never imports a numerical library, and never
imports an executor, runtime, store, or service.  Its job is to keep the
distinct states

    ZERO, NULL, VOID, EMPTY, UNDEFINED, INFINITY, UNKNOWN, ERROR, CANCELLED

from collapsing into one another.

The module builds on :mod:`runner_riddle.math_objects` for the durable
``MathLeaf`` envelope.  An absence record is the canonical in-memory form; a
``MathLeaf`` is the committed/serializable envelope.  A missing reference is a
``VOID`` record with ``failure_class = MISSING_REFERENCE`` and an explicit
``reference_error`` flag; it is never converted to zero, empty, or undefined.

``AbsenceAlgebra`` is stateless apart from its pinned rule snapshot.  It does
not persist anything and does not mutate its inputs.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import re
from typing import Any, Iterable, Mapping

from .math_objects import (
    LEAF_SCHEMA,
    MathLeaf,
    canonical_json,
    digest_object,
)

ABSENCE_SCHEMA = "nanrouter.math-absence.v1"
ABSENCE_CLASSIFICATION_SCHEMA = "nanrouter.math-absence-classification.v1"
CONJUNCTION_SCHEMA = "nanrouter.math-absence-conjunction.v1"
PRESENCE_SCHEMA = "nanrouter.math-presence.v1"
ABSENCE_REQUIRED_SCHEMA = "nanrouter.math-absence-required.v1"

LINKER_ID = "math.absence.v1"
DEFAULT_RULE_SNAPSHOT: dict[str, Any] = {
    "rule_snapshot_id": "math.rules.absence.v1",
    "version": 1,
}

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_LEAF_ID_RE = re.compile(r"^nml:[A-Za-z0-9_.:-]{1,180}$")
_FAILURE_CLASS_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")


class AbsenceError(ValueError):
    """Invalid absence state, record, policy, or conjunction."""


class SnapshotMismatchError(AbsenceError):
    """Operands were classified under different rule snapshots."""


class AbsenceState(str, Enum):
    """The nine distinct P7 states.

    ``ZERO``, ``EMPTY`` and ``INFINITY`` are *present* states.  ``NULL``,
    ``VOID``, ``UNDEFINED``, ``UNKNOWN``, ``ERROR`` and ``CANCELLED`` are
    non-result states.  A non-result is not a numeric value.
    """

    ZERO = "ZERO"
    NULL = "NULL"
    VOID = "VOID"
    EMPTY = "EMPTY"
    UNDEFINED = "UNDEFINED"
    INFINITY = "INFINITY"
    UNKNOWN = "UNKNOWN"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @classmethod
    def parse(cls, value: "AbsenceState | str") -> "AbsenceState":
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            try:
                return cls(value)
            except ValueError as exc:
                raise AbsenceError(
                    f"unknown absence state: {value!r}; expected one of "
                    f"{', '.join(state.value for state in cls)}"
                ) from exc
        raise AbsenceError(f"absence state must be a string, got {type(value).__name__}")

    @property
    def present(self) -> bool:
        return self in PRESENT_STATES

    @property
    def absent(self) -> bool:
        return self in ABSENT_STATES

    @property
    def requires_failure_class(self) -> bool:
        return self in FAILURE_CLASS_REQUIRED


class FailureClass(str, Enum):
    """Closed categories for typed non-result states.

    ``reason`` carries the specific explanation (for example
    ``DIVISION_BY_ZERO``); ``failure_class`` carries the stable category.
    """

    NO_VALID_RESULT = "NO_VALID_RESULT"
    NO_CANDIDATE = "NO_CANDIDATE"
    MISSING_REFERENCE = "MISSING_REFERENCE"
    NO_OBJECT = "NO_OBJECT"
    MATHEMATICALLY_UNDEFINED = "MATHEMATICALLY_UNDEFINED"
    NOT_ESTABLISHED = "NOT_ESTABLISHED"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    CANCELLED = "CANCELLED"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


ALL_STATES: tuple[AbsenceState, ...] = tuple(AbsenceState)
PRESENT_STATES = frozenset({
    AbsenceState.ZERO,
    AbsenceState.EMPTY,
    AbsenceState.INFINITY,
})
ABSENT_STATES = frozenset(set(ALL_STATES) - PRESENT_STATES)
FAILURE_CLASS_REQUIRED = ABSENT_STATES
FAILURE_CLASSES = frozenset(item.value for item in FailureClass)

DEFAULT_FAILURE_CLASS: dict[AbsenceState, str] = {
    AbsenceState.NULL: FailureClass.NO_VALID_RESULT.value,
    AbsenceState.VOID: FailureClass.NO_OBJECT.value,
    AbsenceState.UNDEFINED: FailureClass.MATHEMATICALLY_UNDEFINED.value,
    AbsenceState.UNKNOWN: FailureClass.NOT_ESTABLISHED.value,
    AbsenceState.ERROR: FailureClass.EXECUTION_FAILED.value,
    AbsenceState.CANCELLED: FailureClass.CANCELLED.value,
}

EMPTY_KINDS = frozenset({
    "vector", "matrix", "tensor", "relation", "hypergraph", "index", "mask",
    "basis",
})

_LEAF_KIND_TO_STATE: dict[str, AbsenceState] = {
    "null": AbsenceState.NULL,
    "void": AbsenceState.VOID,
    "undefined": AbsenceState.UNDEFINED,
    "unknown": AbsenceState.UNKNOWN,
    "error": AbsenceState.ERROR,
}

_STATE_TO_LEAF_KIND: dict[AbsenceState, str] = {
    AbsenceState.ZERO: "scalar",
    AbsenceState.NULL: "null",
    AbsenceState.VOID: "void",
    AbsenceState.EMPTY: "vector",
    AbsenceState.UNDEFINED: "undefined",
    AbsenceState.INFINITY: "scalar",
    AbsenceState.UNKNOWN: "unknown",
    AbsenceState.ERROR: "error",
    # math_objects has no ``cancelled`` leaf kind; cancellation is a typed
    # non-result carried by a null-kind leaf with an explicit absence_state.
    AbsenceState.CANCELLED: "null",
}

VOID_POLICIES = frozenset({"DEFER", "REFERENCE_ERROR"})
VOID_VOID_POLICIES = frozenset({"VOID", "REFERENCE_ERROR"})

# Deterministic precedence only when both operands are non-result states.  A
# reference error is handled before this table because resolution precedes
# mathematical evaluation.
_ABSENCE_PRECEDENCE: dict[AbsenceState, int] = {
    AbsenceState.CANCELLED: 0,
    AbsenceState.ERROR: 1,
    AbsenceState.UNDEFINED: 2,
    AbsenceState.NULL: 3,
    AbsenceState.UNKNOWN: 4,
    AbsenceState.VOID: 5,
}


def _require_text(value: Any, name: str, *, maximum: int = 1024) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise AbsenceError(f"{name} must be a non-empty string <= {maximum}")
    return value


def _require_int(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise AbsenceError(f"{name} must be an integer >= {minimum}")
    return value


def _require_leaf_id(value: Any, name: str = "leaf_id") -> str:
    if not isinstance(value, str) or not _LEAF_ID_RE.fullmatch(value):
        raise AbsenceError(f"{name} must be an nml: identifier")
    return value


def _require_digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise AbsenceError(f"{name} must be 64 lowercase hex characters")
    return value


def _normalize_parents(value: Any) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, (tuple, list)):
        raise AbsenceError("parents must be a list of objects")
    parents: list[dict[str, Any]] = []
    for entry in value:
        if not isinstance(entry, Mapping) or not entry:
            raise AbsenceError("parent entries must be non-empty objects")
        parent = dict(entry)
        if "leaf_id" in parent:
            _require_leaf_id(parent["leaf_id"], "parent.leaf_id")
        if "version" in parent:
            _require_int(parent["version"], "parent.version", minimum=1)
        parents.append(parent)
    return tuple(parents)


def _normalize_rule_snapshot(value: Any, *, default: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if value is None and default is not None:
        value = default
    if value is None:
        value = DEFAULT_RULE_SNAPSHOT
    if not isinstance(value, Mapping) or not value:
        raise AbsenceError("rule_snapshot must be a non-empty object")
    snapshot = dict(value)
    identifier = snapshot.get("rule_snapshot_id", snapshot.get("ruleset_id"))
    if not isinstance(identifier, str) or not identifier.strip():
        raise AbsenceError("rule_snapshot requires rule_snapshot_id or ruleset_id")
    return snapshot


def _normalize_failure_class(value: Any, state: AbsenceState) -> str | None:
    if state.present:
        if value is not None:
            raise AbsenceError(
                f"{state.value} is a present state and must not carry failure_class"
            )
        return None
    if value is None:
        value = DEFAULT_FAILURE_CLASS[state]
    if isinstance(value, FailureClass):
        value = value.value
    if not isinstance(value, str) or not _FAILURE_CLASS_RE.fullmatch(value):
        raise AbsenceError("failure_class must be an uppercase identifier")
    if value not in FAILURE_CLASSES:
        raise AbsenceError(
            f"unknown failure_class: {value!r}; expected one of "
            f"{', '.join(sorted(FAILURE_CLASSES))}"
        )
    return value


def _shape_has_zero(shape: Any) -> bool:
    if not isinstance(shape, (tuple, list)):
        return False
    for dimension in shape:
        if isinstance(dimension, bool) or not isinstance(dimension, int):
            raise AbsenceError("shape dimensions must be non-negative integers")
        if dimension < 0:
            raise AbsenceError("shape dimensions must be non-negative integers")
        if dimension == 0:
            return True
    return False


def _normalize_value(state: AbsenceState, value: Any) -> dict[str, Any] | None:
    if state.absent:
        if value is not None:
            raise AbsenceError(
                f"{state.value} must not carry a value/structure descriptor; "
                "absence is not a numeric value"
            )
        return None
    if not isinstance(value, Mapping) or not value:
        raise AbsenceError(f"{state.value} requires a non-empty value descriptor")
    descriptor = dict(value)
    if state is AbsenceState.ZERO:
        canonical = descriptor.get("canonical")
        if canonical != "0":
            raise AbsenceError("ZERO descriptor requires canonical == '0'")
        descriptor.setdefault("kind", "zero")
        return descriptor
    if state is AbsenceState.INFINITY:
        canonical = descriptor.get("canonical")
        if canonical not in {"+inf", "-inf"}:
            raise AbsenceError("INFINITY descriptor requires canonical '+inf' or '-inf'")
        descriptor.setdefault("kind", "infinity")
        descriptor.setdefault("domain", "extended_real")
        return descriptor
    # EMPTY: a valid structure whose extent is zero.  It is present, not null.
    kind = descriptor.get("kind", "vector")
    if kind not in EMPTY_KINDS:
        raise AbsenceError(f"EMPTY descriptor kind must be one of {sorted(EMPTY_KINDS)}")
    shape = descriptor.get("shape", [0])
    if not isinstance(shape, (tuple, list)):
        raise AbsenceError("EMPTY descriptor shape must be a list")
    shape = list(shape)
    count = descriptor.get("count")
    if count is not None and (isinstance(count, bool) or not isinstance(count, int) or count < 0):
        raise AbsenceError("EMPTY descriptor count must be a non-negative integer")
    empty = descriptor.get("empty") is True or count == 0 or _shape_has_zero(shape)
    if not empty:
        raise AbsenceError("EMPTY descriptor must prove zero extent (shape 0 or count 0)")
    descriptor["kind"] = kind
    descriptor["shape"] = shape
    descriptor.setdefault("count", 0)
    return descriptor


def _normalize_metadata(value: Any, state: AbsenceState) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise AbsenceError("metadata must be an object")
    metadata = dict(value)
    declared = metadata.get("absence_state")
    if declared is not None and AbsenceState.parse(declared) is not state:
        raise AbsenceError("metadata.absence_state disagrees with record state")
    return metadata


def _default_value(state: AbsenceState) -> dict[str, Any] | None:
    if state is AbsenceState.ZERO:
        return {"kind": "zero", "canonical": "0"}
    if state is AbsenceState.INFINITY:
        return {"kind": "infinity", "canonical": "+inf", "domain": "extended_real"}
    if state is AbsenceState.EMPTY:
        return {"kind": "vector", "shape": [0], "count": 0, "empty": True}
    return None


def _default_type(state: AbsenceState, value: Mapping[str, Any] | None) -> dict[str, Any]:
    if state is AbsenceState.ZERO:
        return {"name": "scalar", "domain": "real", "shape": [], "precision": "canonical"}
    if state is AbsenceState.INFINITY:
        return {"name": "scalar", "domain": "extended_real", "shape": []}
    if state is AbsenceState.EMPTY:
        value = value or {}
        return {
            "name": str(value.get("kind", "vector")),
            "domain": "structural",
            "shape": list(value.get("shape", [0])),
        }
    return {"name": "absence", "domain": "opaque", "shape": []}


@dataclass(frozen=True)
class AbsenceRecord:
    """Canonical typed absence record.

    Present states carry a value/structure descriptor.  Non-result states carry
    no value descriptor at all; they carry a reason, a failure class, parents,
    and the rule snapshot under which the state was established.
    """

    state: AbsenceState | str
    reason: str
    failure_class: str | None = None
    parents: tuple[dict[str, Any], ...] = ()
    rule_snapshot: dict[str, Any] = field(default_factory=lambda: dict(DEFAULT_RULE_SNAPSHOT))
    linker_id: str = LINKER_ID
    value: dict[str, Any] | None = None
    type: dict[str, Any] = field(default_factory=dict)
    leaf_id: str | None = None
    version: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)
    schema: str = ABSENCE_SCHEMA

    def __post_init__(self) -> None:
        state = AbsenceState.parse(self.state)
        if self.schema != ABSENCE_SCHEMA:
            raise AbsenceError(f"schema must be {ABSENCE_SCHEMA!r}")
        reason = _require_text(self.reason, "reason")
        failure_class = _normalize_failure_class(self.failure_class, state)
        parents = _normalize_parents(self.parents)
        rule_snapshot = _normalize_rule_snapshot(self.rule_snapshot)
        linker_id = _require_text(self.linker_id, "linker_id", maximum=128)
        value = _normalize_value(state, self.value)
        if not isinstance(self.type, Mapping):
            raise AbsenceError("type must be an object")
        leaf_id = None if self.leaf_id is None else _require_leaf_id(self.leaf_id)
        version = _require_int(self.version, "version", minimum=1)
        metadata = _normalize_metadata(self.metadata, state)
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "failure_class", failure_class)
        object.__setattr__(self, "parents", parents)
        object.__setattr__(self, "rule_snapshot", rule_snapshot)
        object.__setattr__(self, "linker_id", linker_id)
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "type", dict(self.type))
        object.__setattr__(self, "leaf_id", leaf_id)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "metadata", metadata)

    @property
    def is_present(self) -> bool:
        return self.state.present

    @property
    def is_absent(self) -> bool:
        return self.state.absent

    @property
    def reference_error(self) -> bool:
        return (
            self.failure_class == FailureClass.MISSING_REFERENCE.value
            or self.metadata.get("missing_reference") is True
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "state": self.state.value,
            "reason": self.reason,
            "failure_class": self.failure_class,
            "parents": [dict(parent) for parent in self.parents],
            "rule_snapshot": dict(self.rule_snapshot),
            "linker_id": self.linker_id,
            "value": None if self.value is None else dict(self.value),
            "type": dict(self.type),
            "leaf_id": self.leaf_id,
            "version": self.version,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AbsenceRecord":
        if not isinstance(data, Mapping):
            raise AbsenceError("absence record must be an object")
        return cls(
            state=data.get("state"),
            reason=data.get("reason"),
            failure_class=data.get("failure_class"),
            parents=tuple(data.get("parents", ())),
            rule_snapshot=data.get("rule_snapshot"),
            linker_id=data.get("linker_id", LINKER_ID),
            value=data.get("value"),
            type=data.get("type", {}),
            leaf_id=data.get("leaf_id"),
            version=data.get("version", 1),
            metadata=data.get("metadata", {}),
            schema=data.get("schema", ABSENCE_SCHEMA),
        )

    def digest(self) -> str:
        return digest_object(self.to_dict())


@dataclass(frozen=True)
class ObjectRef:
    """A resolved present object reference (not an absence record)."""

    leaf_id: str
    version: int = 1
    content_digest: str | None = None
    kind: str = "object"
    type: dict[str, Any] = field(default_factory=dict)
    content: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    parents: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        leaf_id = _require_leaf_id(self.leaf_id)
        version = _require_int(self.version, "version", minimum=1)
        content_digest = None
        if self.content_digest is not None:
            content_digest = _require_digest(self.content_digest, "content_digest")
        kind = _require_text(self.kind, "kind", maximum=64)
        if not isinstance(self.type, Mapping):
            raise AbsenceError("type must be an object")
        if self.content is not None and not isinstance(self.content, Mapping):
            raise AbsenceError("content must be an object or null")
        if not isinstance(self.metadata, Mapping):
            raise AbsenceError("metadata must be an object")
        parents = _normalize_parents(self.parents)
        object.__setattr__(self, "leaf_id", leaf_id)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "content_digest", content_digest)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "type", dict(self.type))
        object.__setattr__(self, "content", None if self.content is None else dict(self.content))
        object.__setattr__(self, "metadata", dict(self.metadata))
        object.__setattr__(self, "parents", parents)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "nanrouter.math-object-ref.v1",
            "leaf_id": self.leaf_id,
            "version": self.version,
            "content_digest": self.content_digest,
            "kind": self.kind,
            "type": dict(self.type),
            "content": None if self.content is None else dict(self.content),
            "metadata": dict(self.metadata),
            "parents": [dict(parent) for parent in self.parents],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ObjectRef":
        if not isinstance(data, Mapping):
            raise AbsenceError("object reference must be an object")
        return cls(
            leaf_id=data.get("leaf_id"),
            version=data.get("version", 1),
            content_digest=data.get("content_digest"),
            kind=data.get("kind", "object"),
            type=data.get("type", {}),
            content=data.get("content"),
            metadata=data.get("metadata", {}),
            parents=tuple(data.get("parents", ())),
        )


@dataclass(frozen=True)
class MissingReference:
    """Explicit missing-reference marker.

    This is deliberately not ``None`` and not a bare ``VOID`` state: it records
    that a required leaf reference could not be resolved.  It classifies to
    ``VOID`` with ``failure_class = MISSING_REFERENCE`` and sets the reference
    error flag.
    """

    leaf_id: str
    version: int | None = None
    reason: str = "REFERENCE_NOT_FOUND"
    failure_class: str = FailureClass.MISSING_REFERENCE.value
    rule_snapshot: dict[str, Any] | None = None
    parents: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        leaf_id = _require_leaf_id(self.leaf_id)
        version = None
        if self.version is not None:
            version = _require_int(self.version, "version", minimum=1)
        reason = _require_text(self.reason, "reason")
        failure_class = self.failure_class
        if isinstance(failure_class, FailureClass):
            failure_class = failure_class.value
        if failure_class != FailureClass.MISSING_REFERENCE.value:
            raise AbsenceError("MissingReference failure_class must be MISSING_REFERENCE")
        if self.rule_snapshot is not None:
            _normalize_rule_snapshot(self.rule_snapshot)
        if not isinstance(self.metadata, Mapping):
            raise AbsenceError("metadata must be an object")
        object.__setattr__(self, "leaf_id", leaf_id)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "failure_class", failure_class)
        object.__setattr__(self, "parents", _normalize_parents(self.parents))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "nanrouter.math-missing-reference.v1",
            "leaf_id": self.leaf_id,
            "version": self.version,
            "reason": self.reason,
            "failure_class": self.failure_class,
            "rule_snapshot": None if self.rule_snapshot is None else dict(self.rule_snapshot),
            "parents": [dict(parent) for parent in self.parents],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ClassifiedOperand:
    """Typed classification of one operand.

    ``state`` is ``None`` only for a present ordinary object (a resolved object
    reference with no absence state).  ``present`` is True for ordinary
    objects, ``ZERO``, ``EMPTY`` and ``INFINITY``.
    """

    state: AbsenceState | None
    present: bool
    reason: str
    failure_class: str | None
    parents: tuple[dict[str, Any], ...]
    rule_snapshot: dict[str, Any]
    leaf_id: str | None = None
    version: int = 1
    content_digest: str | None = None
    reference_error: bool = False
    record: AbsenceRecord | None = None
    ref: ObjectRef | None = None
    schema: str = ABSENCE_CLASSIFICATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != ABSENCE_CLASSIFICATION_SCHEMA:
            raise AbsenceError(f"schema must be {ABSENCE_CLASSIFICATION_SCHEMA!r}")
        state = None if self.state is None else AbsenceState.parse(self.state)
        if not isinstance(self.present, bool):
            raise AbsenceError("present must be a boolean")
        reason = _require_text(self.reason, "reason")
        failure_class = None if self.failure_class is None else str(self.failure_class)
        if state is None:
            if not self.present:
                raise AbsenceError("a classification without a state must be a present object")
            if failure_class is not None:
                raise AbsenceError("a present object must not carry failure_class")
            if self.record is not None:
                raise AbsenceError("a present object cannot carry an absence record")
        elif state.present:
            if not self.present:
                raise AbsenceError(f"{state.value} is a present state")
            if failure_class is not None:
                raise AbsenceError(f"{state.value} must not carry failure_class")
        else:
            if self.present:
                raise AbsenceError(f"{state.value} is not present")
            failure_class = _normalize_failure_class(failure_class, state)
        if (self.record is None) == (self.ref is None):
            raise AbsenceError("classification requires exactly one of record or ref")
        parents = _normalize_parents(self.parents)
        rule_snapshot = _normalize_rule_snapshot(self.rule_snapshot)
        leaf_id = None
        if self.leaf_id is not None:
            leaf_id = _require_leaf_id(self.leaf_id)
        version = _require_int(self.version, "version", minimum=1)
        content_digest = None
        if self.content_digest is not None:
            content_digest = _require_digest(self.content_digest, "content_digest")
        record = self.record
        ref = self.ref
        reference_error = self.reference_error
        if record is not None:
            if state is None or record.state is not state:
                raise AbsenceError("record state disagrees with classification state")
            if record.reason != reason:
                raise AbsenceError("record reason disagrees with classification reason")
            if record.failure_class != failure_class:
                raise AbsenceError("record failure_class disagrees with classification")
            if record.parents != parents or record.rule_snapshot != rule_snapshot:
                raise AbsenceError("record parents/rule_snapshot disagree with classification")
            if leaf_id is not None and record.leaf_id is not None and leaf_id != record.leaf_id:
                raise AbsenceError("record leaf_id disagrees with classification")
            if record.leaf_id is not None and leaf_id is None:
                leaf_id = record.leaf_id
            if record.version != version:
                raise AbsenceError("record version disagrees with classification")
            reference_error = record.reference_error
        else:
            assert ref is not None
            if state is not None:
                raise AbsenceError("object references must classify as a present object")
            if ref.leaf_id != leaf_id or ref.version != version:
                raise AbsenceError("object reference identity disagrees with classification")
            if content_digest is not None and ref.content_digest != content_digest:
                raise AbsenceError("object reference digest disagrees with classification")
            if content_digest is None:
                content_digest = ref.content_digest
            reference_error = False
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "failure_class", failure_class)
        object.__setattr__(self, "parents", parents)
        object.__setattr__(self, "rule_snapshot", rule_snapshot)
        object.__setattr__(self, "leaf_id", leaf_id)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "content_digest", content_digest)
        object.__setattr__(self, "reference_error", reference_error)
        object.__setattr__(self, "record", record)
        object.__setattr__(self, "ref", ref)

    @property
    def is_absence(self) -> bool:
        return not self.present

    @property
    def is_null(self) -> bool:
        return self.state is AbsenceState.NULL

    @property
    def is_void(self) -> bool:
        return self.state is AbsenceState.VOID

    @property
    def is_undefined(self) -> bool:
        return self.state is AbsenceState.UNDEFINED

    @property
    def is_empty(self) -> bool:
        return self.state is AbsenceState.EMPTY

    @property
    def is_zero(self) -> bool:
        return self.state is AbsenceState.ZERO

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "state": None if self.state is None else self.state.value,
            "present": self.present,
            "reason": self.reason,
            "failure_class": self.failure_class,
            "parents": [dict(parent) for parent in self.parents],
            "rule_snapshot": dict(self.rule_snapshot),
            "leaf_id": self.leaf_id,
            "version": self.version,
            "content_digest": self.content_digest,
            "reference_error": self.reference_error,
            "record": None if self.record is None else self.record.to_dict(),
            "ref": None if self.ref is None else self.ref.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ClassifiedOperand":
        if not isinstance(data, Mapping):
            raise AbsenceError("classification must be an object")
        record = None
        if data.get("record") is not None:
            record = AbsenceRecord.from_dict(data["record"])
        ref = None
        if data.get("ref") is not None:
            ref = ObjectRef.from_dict(data["ref"])
        if record is not None:
            return cls(
                state=record.state,
                present=record.is_present,
                reason=record.reason,
                failure_class=record.failure_class,
                parents=record.parents,
                rule_snapshot=record.rule_snapshot,
                leaf_id=record.leaf_id,
                version=record.version,
                content_digest=data.get("content_digest"),
                reference_error=record.reference_error,
                record=record,
                ref=None,
            )
        if ref is not None:
            return cls(
                state=None,
                present=True,
                reason=data.get("reason", "OBJECT_PRESENT"),
                failure_class=None,
                parents=tuple(data.get("parents", ref.parents)),
                rule_snapshot=data.get("rule_snapshot") or DEFAULT_RULE_SNAPSHOT,
                leaf_id=ref.leaf_id,
                version=ref.version,
                content_digest=ref.content_digest,
                reference_error=False,
                record=None,
                ref=ref,
            )
        raise AbsenceError("classification requires a record or object reference")

    def digest(self) -> str:
        return digest_object(self.to_dict())


@dataclass(frozen=True)
class ConjoinPolicy:
    """Explicit policy for the two void cases and registered null algebra."""

    void_policy: str = "DEFER"
    void_void_policy: str = "VOID"
    null_algebra_id: str | None = None

    def __post_init__(self) -> None:
        if self.void_policy not in VOID_POLICIES:
            raise AbsenceError(f"void_policy must be one of {sorted(VOID_POLICIES)}")
        if self.void_void_policy not in VOID_VOID_POLICIES:
            raise AbsenceError(f"void_void_policy must be one of {sorted(VOID_VOID_POLICIES)}")
        null_algebra_id = None
        if self.null_algebra_id is not None:
            null_algebra_id = _require_text(self.null_algebra_id, "null_algebra_id", maximum=128)
            if null_algebra_id.upper() == "VOID" or null_algebra_id == "*":
                raise AbsenceError("null_algebra_id must identify a registered algebra, not a wildcard")
        object.__setattr__(self, "null_algebra_id", null_algebra_id)

    @classmethod
    def strict(cls) -> "ConjoinPolicy":
        return cls(void_policy="REFERENCE_ERROR", void_void_policy="REFERENCE_ERROR")

    def to_dict(self) -> dict[str, Any]:
        return {
            "void_policy": self.void_policy,
            "void_void_policy": self.void_void_policy,
            "null_algebra_id": self.null_algebra_id,
        }


@dataclass(frozen=True)
class _Outcome:
    state: AbsenceState | None
    present: bool
    candidates_allowed: bool
    reason: str
    failure_class: str | None
    reference_error: bool
    null_algebra_id: str | None
    value: dict[str, Any] | None


@dataclass(frozen=True)
class ConjunctionResult:
    """Typed result of one explicit absence-aware conjunction."""

    state: AbsenceState | None
    present: bool
    candidates_allowed: bool
    reason: str
    failure_class: str | None
    operands: tuple[ClassifiedOperand, ...]
    parents: tuple[dict[str, Any], ...]
    rule_snapshot: dict[str, Any]
    policy: ConjoinPolicy = field(default_factory=ConjoinPolicy)
    reference_error: bool = False
    null_algebra_id: str | None = None
    value: dict[str, Any] | None = None
    schema: str = CONJUNCTION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != CONJUNCTION_SCHEMA:
            raise AbsenceError(f"schema must be {CONJUNCTION_SCHEMA!r}")
        state = None if self.state is None else AbsenceState.parse(self.state)
        if not isinstance(self.present, bool) or not isinstance(self.candidates_allowed, bool):
            raise AbsenceError("present/candidates_allowed must be booleans")
        reason = _require_text(self.reason, "reason")
        if len(self.operands) != 2 or not all(
            isinstance(operand, ClassifiedOperand) for operand in self.operands
        ):
            raise AbsenceError("conjunction requires exactly two classified operands")
        parents = _normalize_parents(self.parents)
        rule_snapshot = _normalize_rule_snapshot(self.rule_snapshot)
        if not isinstance(self.policy, ConjoinPolicy):
            raise AbsenceError("policy must be a ConjoinPolicy")
        failure_class = self.failure_class
        if state is None:
            if not self.present and not self.null_algebra_id:
                raise AbsenceError("state-less conjunction must be present or null-algebra resolved")
            if failure_class is not None:
                raise AbsenceError("state-less conjunction must not carry failure_class")
            if not self.candidates_allowed:
                raise AbsenceError("a state-less conjunction must allow candidates")
        elif state.present:
            if not self.present or not self.candidates_allowed:
                raise AbsenceError(f"{state.value} is present and may generate candidates")
            if failure_class is not None:
                raise AbsenceError(f"{state.value} must not carry failure_class")
        else:
            if self.present or self.candidates_allowed:
                raise AbsenceError(f"{state.value} cannot present or allow candidates")
            failure_class = _normalize_failure_class(failure_class, state)
        null_algebra_id = None
        if self.null_algebra_id is not None:
            null_algebra_id = _require_text(self.null_algebra_id, "null_algebra_id", maximum=128)
        if null_algebra_id is not None and state is not None:
            raise AbsenceError("null_algebra_id only applies to a resolved state-less conjunction")
        reference_error = bool(self.reference_error)
        if reference_error:
            if state is not AbsenceState.VOID:
                raise AbsenceError("reference_error requires VOID state")
            if failure_class != FailureClass.MISSING_REFERENCE.value:
                raise AbsenceError("reference_error requires MISSING_REFERENCE failure_class")
        value = self.value
        if state is not None and state.absent:
            if value is not None:
                raise AbsenceError(f"{state.value} must not carry a value descriptor")
        elif value is not None:
            if not isinstance(value, Mapping):
                raise AbsenceError("value must be an object or null")
            value = dict(value)
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "failure_class", failure_class)
        object.__setattr__(self, "parents", parents)
        object.__setattr__(self, "rule_snapshot", rule_snapshot)
        object.__setattr__(self, "reference_error", reference_error)
        object.__setattr__(self, "null_algebra_id", null_algebra_id)
        object.__setattr__(self, "value", value)

    @property
    def is_absence(self) -> bool:
        return not self.present

    def to_record(self) -> AbsenceRecord:
        if self.state is None:
            raise AbsenceError("a state-less conjunction has no absence record")
        metadata: dict[str, Any] = {"conjunction": self.digest()}
        if self.reference_error:
            for operand in self.operands:
                if operand.reference_error and operand.record is not None:
                    metadata.update(operand.record.metadata)
        return AbsenceRecord(
            state=self.state,
            reason=self.reason,
            failure_class=self.failure_class,
            parents=self.parents,
            rule_snapshot=self.rule_snapshot,
            value=self.value,
            metadata=metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "state": None if self.state is None else self.state.value,
            "present": self.present,
            "candidates_allowed": self.candidates_allowed,
            "reason": self.reason,
            "failure_class": self.failure_class,
            "reference_error": self.reference_error,
            "null_algebra_id": self.null_algebra_id,
            "parents": [dict(parent) for parent in self.parents],
            "rule_snapshot": dict(self.rule_snapshot),
            "policy": self.policy.to_dict(),
            "value": None if self.value is None else dict(self.value),
            "operands": [operand.to_dict() for operand in self.operands],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ConjunctionResult":
        if not isinstance(data, Mapping):
            raise AbsenceError("conjunction result must be an object")
        policy = data.get("policy", {})
        if isinstance(policy, ConjoinPolicy):
            policy_obj = policy
        else:
            policy_obj = ConjoinPolicy(**dict(policy))
        operands = tuple(ClassifiedOperand.from_dict(item) for item in data.get("operands", ()))
        return cls(
            state=data.get("state"),
            present=data.get("present", False),
            candidates_allowed=data.get("candidates_allowed", False),
            reason=data.get("reason"),
            failure_class=data.get("failure_class"),
            operands=operands,
            parents=tuple(data.get("parents", ())),
            rule_snapshot=data.get("rule_snapshot"),
            policy=policy_obj,
            reference_error=data.get("reference_error", False),
            null_algebra_id=data.get("null_algebra_id"),
            value=data.get("value"),
            schema=data.get("schema", CONJUNCTION_SCHEMA),
        )

    def digest(self) -> str:
        return digest_object(self.to_dict())


@dataclass(frozen=True)
class PresenceResult:
    """Successful result of ``require_present``."""

    leaf_id: str | None
    version: int
    state: AbsenceState | None
    reason: str
    operand: ClassifiedOperand
    schema: str = PRESENCE_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PRESENCE_SCHEMA:
            raise AbsenceError(f"schema must be {PRESENCE_SCHEMA!r}")
        if self.leaf_id is not None:
            _require_leaf_id(self.leaf_id)
        _require_int(self.version, "version", minimum=1)
        if self.state is not None:
            state = AbsenceState.parse(self.state)
            if not state.present:
                raise AbsenceError("require_present cannot succeed for an absent state")
            object.__setattr__(self, "state", state)
        if not isinstance(self.operand, ClassifiedOperand) or not self.operand.present:
            raise AbsenceError("PresenceResult requires a present operand")
        _require_text(self.reason, "reason")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "leaf_id": self.leaf_id,
            "version": self.version,
            "state": None if self.state is None else self.state.value,
            "reason": self.reason,
            "operand": self.operand.to_dict(),
        }

    def digest(self) -> str:
        return digest_object(self.to_dict())


class AbsenceRequiredError(AbsenceError):
    """A present operand was required, but the typed state is absent."""

    def __init__(self, operand: ClassifiedOperand, purpose: str = "operation") -> None:
        if not isinstance(operand, ClassifiedOperand) or operand.present:
            raise AbsenceError("AbsenceRequiredError requires an absent classification")
        self.operand = operand
        self.purpose = _require_text(purpose, "purpose", maximum=256)
        self.state = operand.state
        self.failure_class = operand.failure_class
        self.reason = operand.reason
        self.reference_error = operand.reference_error
        state = "ABSENT" if operand.state is None else operand.state.value
        super().__init__(
            f"{self.purpose} requires a present operand; got {state} "
            f"({operand.failure_class or 'NO_FAILURE_CLASS'}: {operand.reason})"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": ABSENCE_REQUIRED_SCHEMA,
            "purpose": self.purpose,
            "state": None if self.state is None else self.state.value,
            "failure_class": self.failure_class,
            "reason": self.reason,
            "reference_error": self.reference_error,
            "operand": self.operand.to_dict(),
        }


class MissingReferenceError(AbsenceRequiredError):
    """Required leaf reference could not be resolved; never zero/empty/null."""

    def __init__(self, operand: ClassifiedOperand, purpose: str = "operation") -> None:
        if not operand.reference_error:
            raise AbsenceError("MissingReferenceError requires a reference_error classification")
        super().__init__(operand, purpose)
        self.missing_leaf_id = (
            operand.record.metadata.get("missing_leaf_id")
            if operand.record is not None
            else None
        )


class AbsenceAlgebra:
    """Stateless, deterministic null/void/undefined classifier and conjoiner.

    The algebra pins a rule snapshot for records it builds.  It never persists,
    never executes, and never performs numeric evaluation.
    """

    def __init__(
        self,
        *,
        rule_snapshot: Mapping[str, Any] | None = None,
        linker_id: str = LINKER_ID,
    ) -> None:
        self._rule_snapshot = _normalize_rule_snapshot(rule_snapshot)
        self._linker_id = _require_text(linker_id, "linker_id", maximum=128)

    @property
    def rule_snapshot(self) -> dict[str, Any]:
        return dict(self._rule_snapshot)

    @property
    def linker_id(self) -> str:
        return self._linker_id

    def classify(
        self,
        value: Any,
        *,
        reason: str | None = None,
        failure_class: str | None = None,
        parents: Iterable[Mapping[str, Any]] | None = None,
        rule_snapshot: Mapping[str, Any] | None = None,
        value_descriptor: Mapping[str, Any] | None = None,
        type: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
        leaf_id: str | None = None,
        version: int | None = None,
    ) -> ClassifiedOperand:
        """Classify a state, record, leaf, object reference, or serialized form.

        ``None`` is rejected on purpose: use :class:`MissingReference` or an
        explicit ``VOID`` record.  This prevents Python ``None`` from becoming a
        wildcard absence.
        """

        overrides = {
            "reason": reason,
            "failure_class": failure_class,
            "parents": parents,
            "rule_snapshot": rule_snapshot,
            "value_descriptor": value_descriptor,
            "type": type,
            "metadata": metadata,
            "leaf_id": leaf_id,
            "version": version,
        }
        supplied = {key: item for key, item in overrides.items() if item is not None}

        if isinstance(value, ClassifiedOperand):
            if supplied:
                raise AbsenceError("field overrides apply only when classifying a state")
            return value
        if isinstance(value, ConjunctionResult):
            if supplied:
                raise AbsenceError("field overrides apply only when classifying a state")
            return self._operand_from_conjunction(value)
        if isinstance(value, AbsenceRecord):
            if supplied:
                data = value.to_dict()
                if reason is not None:
                    data["reason"] = reason
                if failure_class is not None:
                    data["failure_class"] = failure_class
                if parents is not None:
                    data["parents"] = [dict(parent) for parent in parents]
                if rule_snapshot is not None:
                    data["rule_snapshot"] = dict(rule_snapshot)
                if value_descriptor is not None:
                    data["value"] = dict(value_descriptor)
                if type is not None:
                    data["type"] = dict(type)
                if metadata is not None:
                    merged = dict(data.get("metadata", {}))
                    merged.update(dict(metadata))
                    data["metadata"] = merged
                if leaf_id is not None:
                    data["leaf_id"] = leaf_id
                if version is not None:
                    data["version"] = version
                value = AbsenceRecord.from_dict(data)
            return self._operand_from_record(value)
        if isinstance(value, MissingReference):
            if supplied:
                raise AbsenceError("field overrides apply only when classifying a state")
            return self._operand_from_missing_reference(value)
        if isinstance(value, ObjectRef):
            if supplied:
                raise AbsenceError("field overrides apply only when classifying a state")
            return self._operand_from_object_ref(value)
        if isinstance(value, MathLeaf):
            if supplied:
                raise AbsenceError("field overrides apply only when classifying a state")
            return self._operand_from_leaf(value)
        if isinstance(value, Mapping):
            if supplied:
                raise AbsenceError("field overrides apply only when classifying a state")
            return self._operand_from_mapping(value)
        if isinstance(value, (AbsenceState, str)):
            return self._classify_state(
                value,
                reason=reason,
                failure_class=failure_class,
                parents=parents,
                rule_snapshot=rule_snapshot,
                value_descriptor=value_descriptor,
                type=type,
                metadata=metadata,
                leaf_id=leaf_id,
                version=version,
            )
        if value is None:
            raise AbsenceError(
                "None is not a typed absence; use MissingReference for a failed "
                "reference or an explicit VOID record for no object"
            )
        raise AbsenceError(f"cannot classify {value.__class__.__name__} as an absence state")

    def conjoin(
        self,
        left: Any,
        right: Any,
        *,
        policy: ConjoinPolicy | Mapping[str, Any] | None = None,
        rule_snapshot: Mapping[str, Any] | None = None,
        parents: Iterable[Mapping[str, Any]] | None = None,
    ) -> ConjunctionResult:
        """Apply the explicit P7 conjunction matrix.

        This only classifies absence/result semantics.  It does not enumerate
        mathematical candidates, execute anything, or authorize anything.
        """

        if policy is None:
            policy_obj = ConjoinPolicy()
        elif isinstance(policy, ConjoinPolicy):
            policy_obj = policy
        elif isinstance(policy, Mapping):
            policy_obj = ConjoinPolicy(**dict(policy))
        else:
            raise AbsenceError("policy must be a ConjoinPolicy or object")

        lhs = self.classify(left)
        rhs = self.classify(right)
        if lhs.rule_snapshot != rhs.rule_snapshot:
            raise SnapshotMismatchError(
                "operands were classified under different rule snapshots"
            )
        snapshot = (
            _normalize_rule_snapshot(rule_snapshot)
            if rule_snapshot is not None
            else dict(lhs.rule_snapshot)
        )
        outcome = self._conjoin_operands(lhs, rhs, policy_obj)
        result_parents = self._conjunction_parents(lhs, rhs, parents)
        return ConjunctionResult(
            state=outcome.state,
            present=outcome.present,
            candidates_allowed=outcome.candidates_allowed,
            reason=outcome.reason,
            failure_class=outcome.failure_class,
            operands=(lhs, rhs),
            parents=result_parents,
            rule_snapshot=snapshot,
            policy=policy_obj,
            reference_error=outcome.reference_error,
            null_algebra_id=outcome.null_algebra_id,
            value=outcome.value,
        )

    def to_leaf(
        self,
        value: Any,
        *,
        leaf_id: str | None = None,
        version: int | None = None,
        parents: Iterable[Mapping[str, Any]] | None = None,
        rule_snapshot: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
        status: str = "committed",
    ) -> MathLeaf:
        """Convert a typed absence/result into a ``MathLeaf`` envelope.

        ``ZERO``, ``EMPTY`` and ``INFINITY`` get value-bearing object leaves.
        Non-result states get ``null``/``void``/``undefined``/``unknown``/
        ``error`` leaves with no content.  ``CANCELLED`` uses the ``null`` leaf
        kind plus ``metadata.absence_state = CANCELLED`` because
        ``math_objects`` has no dedicated cancelled kind.
        """

        record = self._record_for_leaf(value)
        data = record.to_dict()
        if leaf_id is not None:
            data["leaf_id"] = leaf_id
        if version is not None:
            data["version"] = version
        if parents is not None:
            data["parents"] = [dict(parent) for parent in parents]
        if rule_snapshot is not None:
            data["rule_snapshot"] = dict(rule_snapshot)
        if metadata is not None:
            merged = dict(data.get("metadata", {}))
            merged.update(dict(metadata))
            data["metadata"] = merged
        record = AbsenceRecord.from_dict(data)
        return self._math_leaf_from_record(record, status=status)

    def require_present(
        self,
        value: Any,
        *,
        purpose: str = "operation",
    ) -> PresenceResult:
        """Return a typed presence result or raise a typed absence error.

        This method is atomic: it does not create, persist, or mutate a leaf.
        A missing reference raises :class:`MissingReferenceError`; other absent
        states raise :class:`AbsenceRequiredError`.  Neither is converted to
        zero, empty, or a plain null.
        """

        operand = self.classify(value)
        if operand.reference_error:
            raise MissingReferenceError(operand, purpose)
        if not operand.present:
            raise AbsenceRequiredError(operand, purpose)
        return PresenceResult(
            leaf_id=operand.leaf_id,
            version=operand.version,
            state=operand.state,
            reason="PRESENT",
            operand=operand,
        )

    # ------------------------------------------------------------------
    # Classification helpers
    # ------------------------------------------------------------------

    def _classify_state(
        self,
        value: AbsenceState | str,
        *,
        reason: str | None,
        failure_class: str | None,
        parents: Iterable[Mapping[str, Any]] | None,
        rule_snapshot: Mapping[str, Any] | None,
        value_descriptor: Mapping[str, Any] | None,
        type: Mapping[str, Any] | None,
        metadata: Mapping[str, Any] | None,
        leaf_id: str | None,
        version: int | None,
    ) -> ClassifiedOperand:
        state = AbsenceState.parse(value)
        record = AbsenceRecord(
            state=state,
            reason=reason if reason is not None else state.value,
            failure_class=failure_class,
            parents=tuple(parents or ()),
            rule_snapshot=self._snapshot_or_default(rule_snapshot),
            linker_id=self._linker_id,
            value=(
                value_descriptor
                if value_descriptor is not None
                else _default_value(state)
            ),
            type={} if type is None else dict(type),
            leaf_id=leaf_id,
            version=1 if version is None else version,
            metadata={} if metadata is None else dict(metadata),
        )
        return self._operand_from_record(record)

    def _operand_from_record(self, record: AbsenceRecord) -> ClassifiedOperand:
        return ClassifiedOperand(
            state=record.state,
            present=record.is_present,
            reason=record.reason,
            failure_class=record.failure_class,
            parents=record.parents,
            rule_snapshot=record.rule_snapshot,
            leaf_id=record.leaf_id,
            version=record.version,
            reference_error=record.reference_error,
            record=record,
            ref=None,
        )

    def _operand_from_missing_reference(self, missing: MissingReference) -> ClassifiedOperand:
        record = AbsenceRecord(
            state=AbsenceState.VOID,
            reason=missing.reason,
            failure_class=FailureClass.MISSING_REFERENCE.value,
            parents=missing.parents,
            rule_snapshot=self._snapshot_or_default(missing.rule_snapshot),
            linker_id=self._linker_id,
            value=None,
            leaf_id=None,
            metadata={
                "missing_reference": True,
                "missing_leaf_id": missing.leaf_id,
                "missing_version": missing.version,
                **dict(missing.metadata),
            },
        )
        return self._operand_from_record(record)

    def _operand_from_object_ref(self, ref: ObjectRef) -> ClassifiedOperand:
        metadata = dict(ref.metadata)
        declared = metadata.get("absence_state")
        state: AbsenceState | None = None
        if declared is not None:
            state = AbsenceState.parse(declared)
        elif ref.kind in _LEAF_KIND_TO_STATE:
            state = _LEAF_KIND_TO_STATE[ref.kind]
        elif self._value_is_empty(ref.type, ref.content):
            state = AbsenceState.EMPTY

        if state is None:
            return ClassifiedOperand(
                state=None,
                present=True,
                reason="OBJECT_PRESENT",
                failure_class=None,
                parents=ref.parents,
                rule_snapshot=self._snapshot_or_default(metadata.get("rule_snapshot")),
                leaf_id=ref.leaf_id,
                version=ref.version,
                content_digest=ref.content_digest,
                reference_error=False,
                record=None,
                ref=ref,
            )

        value = metadata.get("value")
        if value is None:
            if state is AbsenceState.EMPTY:
                value = self._empty_value(ref.type, ref.content)
            else:
                value = _default_value(state)
        record = AbsenceRecord(
            state=state,
            reason=metadata.get("reason", state.value),
            failure_class=metadata.get("failure_class"),
            parents=ref.parents,
            rule_snapshot=self._snapshot_or_default(metadata.get("rule_snapshot")),
            linker_id=self._linker_id,
            value=value,
            type=ref.type,
            leaf_id=ref.leaf_id,
            version=ref.version,
            metadata=metadata,
        )
        return self._operand_from_record(record)

    def _operand_from_leaf(self, leaf: MathLeaf) -> ClassifiedOperand:
        metadata = dict(leaf.metadata)
        declared = metadata.get("absence_state")
        state: AbsenceState | None = None
        if declared is not None:
            state = AbsenceState.parse(declared)
        elif leaf.kind in _LEAF_KIND_TO_STATE:
            state = _LEAF_KIND_TO_STATE[leaf.kind]
        elif self._value_is_empty(leaf.type, leaf.content):
            state = AbsenceState.EMPTY

        content_digest = leaf.content_digest
        if state is None:
            ref = ObjectRef(
                leaf_id=leaf.leaf_id,
                version=leaf.version,
                content_digest=content_digest,
                kind=leaf.kind,
                type=leaf.type,
                content=leaf.content,
                metadata=metadata,
                parents=leaf.parents,
            )
            return self._operand_from_object_ref(ref)

        value = metadata.get("value")
        if value is None:
            if state is AbsenceState.EMPTY:
                value = self._empty_value(leaf.type, leaf.content)
            elif state is AbsenceState.ZERO:
                content = leaf.content or {}
                canonical = content.get("canonical", "0")
                if canonical != "0":
                    raise AbsenceError("ZERO leaf content must have canonical '0'")
                value = _default_value(state)
            elif state is AbsenceState.INFINITY:
                content = leaf.content or {}
                canonical = content.get("canonical", "+inf")
                value = {
                    "kind": "infinity",
                    "canonical": canonical,
                    "domain": content.get("domain", "extended_real"),
                }
            else:
                value = _default_value(state)
        record = AbsenceRecord(
            state=state,
            reason=metadata.get("reason", state.value),
            failure_class=metadata.get("failure_class"),
            parents=leaf.parents,
            rule_snapshot=self._snapshot_or_default(metadata.get("rule_snapshot")),
            linker_id=metadata.get("linker_id", self._linker_id),
            value=value,
            type=leaf.type,
            leaf_id=leaf.leaf_id,
            version=leaf.version,
            metadata=metadata,
        )
        return self._operand_from_record(record)

    def _operand_from_conjunction(self, result: ConjunctionResult) -> ClassifiedOperand:
        if result.state is None:
            raise AbsenceError("a candidate-allowed conjunction has no absence record")
        record = AbsenceRecord(
            state=result.state,
            reason=result.reason,
            failure_class=result.failure_class,
            parents=result.parents,
            rule_snapshot=result.rule_snapshot,
            linker_id=self._linker_id,
            value=result.value,
            metadata={"conjunction": result.digest()},
        )
        return self._operand_from_record(record)

    def _operand_from_mapping(self, data: Mapping[str, Any]) -> ClassifiedOperand:
        schema = data.get("schema")
        if schema == ABSENCE_CLASSIFICATION_SCHEMA:
            return ClassifiedOperand.from_dict(data)
        if schema == CONJUNCTION_SCHEMA:
            return self._operand_from_conjunction(ConjunctionResult.from_dict(data))
        if schema == ABSENCE_SCHEMA or "state" in data:
            return self._operand_from_record(AbsenceRecord.from_dict(data))
        if schema == LEAF_SCHEMA or ("leaf_id" in data and "kind" in data):
            leaf = MathLeaf(
                leaf_id=data["leaf_id"],
                kind=data["kind"],
                version=data.get("version", 1),
                type=data.get("type", {}),
                content=data.get("content"),
                parents=tuple(data.get("parents", ())),
                operation=data.get("operation"),
                status=data.get("status", "committed"),
                provenance=data.get("provenance", {}),
                aliases=tuple(data.get("aliases", ())),
                metadata=data.get("metadata", {}),
            )
            return self._operand_from_leaf(leaf)
        if data.get("missing_reference") is True and "leaf_id" in data:
            missing = MissingReference(
                leaf_id=data["leaf_id"],
                version=data.get("version"),
                reason=data.get("reason", "REFERENCE_NOT_FOUND"),
                rule_snapshot=data.get("rule_snapshot"),
                parents=tuple(data.get("parents", ())),
                metadata=data.get("metadata", {}),
            )
            return self._operand_from_missing_reference(missing)
        raise AbsenceError("unrecognized absence/classification/leaf object")

    # ------------------------------------------------------------------
    # Conjunction helpers
    # ------------------------------------------------------------------

    def _conjoin_operands(
        self,
        lhs: ClassifiedOperand,
        rhs: ClassifiedOperand,
        policy: ConjoinPolicy,
    ) -> _Outcome:
        # Resolution precedes mathematics: an unresolved required reference is
        # always a reference error, regardless of the void deferral policy.
        if lhs.reference_error or rhs.reference_error:
            source = lhs if lhs.reference_error else rhs
            return _Outcome(
                state=AbsenceState.VOID,
                present=False,
                candidates_allowed=False,
                reason=source.reason,
                failure_class=FailureClass.MISSING_REFERENCE.value,
                reference_error=True,
                null_algebra_id=None,
                value=None,
            )

        if lhs.present and rhs.present:
            empty = next(
                (operand for operand in (lhs, rhs) if operand.state is AbsenceState.EMPTY),
                None,
            )
            if empty is not None:
                assert empty.record is not None
                return _Outcome(
                    state=AbsenceState.EMPTY,
                    present=True,
                    candidates_allowed=True,
                    reason="EMPTY_STRUCTURE_PRESENT",
                    failure_class=None,
                    reference_error=False,
                    null_algebra_id=None,
                    value=dict(empty.record.value or {}),
                )
            return _Outcome(
                state=None,
                present=True,
                candidates_allowed=True,
                reason="OPERANDS_PRESENT",
                failure_class=None,
                reference_error=False,
                null_algebra_id=None,
                value=None,
            )

        absent = tuple(
            operand for operand in (lhs, rhs) if not operand.present
        )

        if len(absent) == 1:
            operand = absent[0]
            state = operand.state
            assert state is not None
            if state is AbsenceState.VOID:
                if policy.void_policy == "REFERENCE_ERROR":
                    return _Outcome(
                        state=AbsenceState.VOID,
                        present=False,
                        candidates_allowed=False,
                        reason="MISSING_REQUIRED_REFERENCE",
                        failure_class=FailureClass.MISSING_REFERENCE.value,
                        reference_error=True,
                        null_algebra_id=None,
                        value=None,
                    )
                return _Outcome(
                    state=AbsenceState.UNKNOWN,
                    present=False,
                    candidates_allowed=False,
                    reason="VOID_INPUT_MAY_ARRIVE",
                    failure_class=FailureClass.NOT_ESTABLISHED.value,
                    reference_error=False,
                    null_algebra_id=None,
                    value=None,
                )
            if state is AbsenceState.NULL and policy.null_algebra_id is not None:
                return _Outcome(
                    state=None,
                    present=False,
                    candidates_allowed=True,
                    reason="REGISTERED_NULL_ALGEBRA",
                    failure_class=None,
                    reference_error=False,
                    null_algebra_id=policy.null_algebra_id,
                    value=None,
                )
            return _Outcome(
                state=state,
                present=False,
                candidates_allowed=False,
                reason=operand.reason,
                failure_class=operand.failure_class,
                reference_error=False,
                null_algebra_id=None,
                value=None,
            )

        # Both operands are non-result states.
        if policy.null_algebra_id is not None and all(
            operand.state is AbsenceState.NULL for operand in absent
        ):
            return _Outcome(
                state=None,
                present=False,
                candidates_allowed=True,
                reason="REGISTERED_NULL_ALGEBRA",
                failure_class=None,
                reference_error=False,
                null_algebra_id=policy.null_algebra_id,
                value=None,
            )

        if all(operand.state is AbsenceState.VOID for operand in absent):
            if policy.void_void_policy == "REFERENCE_ERROR":
                return _Outcome(
                    state=AbsenceState.VOID,
                    present=False,
                    candidates_allowed=False,
                    reason="VOID_VOID_REFERENCE_ERROR",
                    failure_class=FailureClass.MISSING_REFERENCE.value,
                    reference_error=True,
                    null_algebra_id=None,
                    value=None,
                )
            return _Outcome(
                state=AbsenceState.VOID,
                present=False,
                candidates_allowed=False,
                reason="VOID_CONJUNCTION",
                failure_class=FailureClass.NO_OBJECT.value,
                reference_error=False,
                null_algebra_id=None,
                value=None,
            )

        chosen = min(
            absent,
            key=lambda operand: _ABSENCE_PRECEDENCE[operand.state],  # type: ignore[index]
        )
        return _Outcome(
            state=chosen.state,
            present=False,
            candidates_allowed=False,
            reason=chosen.reason,
            failure_class=chosen.failure_class,
            reference_error=False,
            null_algebra_id=None,
            value=None,
        )

    def _conjunction_parents(
        self,
        lhs: ClassifiedOperand,
        rhs: ClassifiedOperand,
        explicit: Iterable[Mapping[str, Any]] | None,
    ) -> tuple[dict[str, Any], ...]:
        parents: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add(entry: Mapping[str, Any]) -> None:
            item = dict(entry)
            key = canonical_json(item)
            if key in seen:
                return
            seen.add(key)
            parents.append(item)

        for entry in explicit or ():
            if not isinstance(entry, Mapping):
                raise AbsenceError("parents entries must be objects")
            add(entry)

        for role, operand in (("left", lhs), ("right", rhs)):
            if operand.leaf_id is not None:
                item = {
                    "leaf_id": operand.leaf_id,
                    "version": operand.version,
                    "role": role,
                }
                if operand.content_digest is not None:
                    item["content_digest"] = operand.content_digest
                add(item)
            for parent in operand.parents:
                add(parent)
        return _normalize_parents(parents)

    # ------------------------------------------------------------------
    # Leaf helpers
    # ------------------------------------------------------------------

    def _record_for_leaf(self, value: Any) -> AbsenceRecord:
        if isinstance(value, AbsenceRecord):
            return value
        if isinstance(value, ClassifiedOperand):
            if value.record is None:
                raise AbsenceError("a present object reference has no absence leaf")
            return value.record
        if isinstance(value, ConjunctionResult):
            return value.to_record()
        if isinstance(value, MissingReference):
            operand = self._operand_from_missing_reference(value)
            assert operand.record is not None
            return operand.record
        if isinstance(value, (AbsenceState, str)):
            operand = self.classify(value)
            assert operand.record is not None
            return operand.record
        operand = self.classify(value)
        if operand.record is None:
            raise AbsenceError("a present object reference has no absence leaf")
        return operand.record

    def _math_leaf_from_record(self, record: AbsenceRecord, *, status: str) -> MathLeaf:
        state = record.state
        if state is AbsenceState.CANCELLED:
            kind = "null"
        elif state is AbsenceState.EMPTY:
            assert record.value is not None
            kind = str(record.value.get("kind", "vector"))
            if kind not in EMPTY_KINDS:
                raise AbsenceError("EMPTY leaf kind is not a structure kind")
        else:
            kind = _STATE_TO_LEAF_KIND[state]

        content = None if record.value is None else dict(record.value)
        metadata = dict(record.metadata)
        metadata.update({
            "absence_state": state.value,
            "reason": record.reason,
            "failure_class": record.failure_class,
            "rule_snapshot": dict(record.rule_snapshot),
            "linker_id": record.linker_id,
        })
        if record.value is not None:
            metadata["value"] = dict(record.value)

        leaf_id = record.leaf_id
        if leaf_id is None:
            leaf_id = (
                f"nml:U0:absence:{state.value.lower()}:"
                f"{record.digest()[:16]}"
            )

        return MathLeaf(
            leaf_id=leaf_id,
            kind=kind,
            version=record.version,
            type=dict(record.type) or _default_type(state, record.value),
            content=content,
            parents=record.parents,
            operation=None,
            status=status,
            provenance={
                "producer": record.linker_id,
                "absence_state": state.value,
            },
            metadata=metadata,
        )

    def _snapshot_or_default(self, value: Any) -> dict[str, Any]:
        if value is None:
            return dict(self._rule_snapshot)
        return _normalize_rule_snapshot(value)

    @staticmethod
    def _value_is_empty(type_doc: Mapping[str, Any], content: Mapping[str, Any] | None) -> bool:
        shape = type_doc.get("shape")
        if isinstance(shape, (tuple, list)):
            try:
                if _shape_has_zero(shape):
                    return True
            except AbsenceError:
                pass
        if content is None:
            return False
        if content.get("empty") is True:
            return True
        for key in ("count", "word_count"):
            value = content.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value == 0:
                return True
        return False

    @staticmethod
    def _empty_value(
        type_doc: Mapping[str, Any],
        content: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        shape = type_doc.get("shape")
        if not isinstance(shape, (tuple, list)):
            shape = [0]
        shape = list(shape)
        kind = type_doc.get("name", "vector")
        if kind not in EMPTY_KINDS:
            kind = "vector"
        value = {
            "kind": kind,
            "shape": shape,
            "count": 0,
            "empty": True,
        }
        if content is not None:
            for key in ("digest", "word_count"):
                if key in content:
                    value[key] = content[key]
        return value


__all__ = [
    "ABSENCE_CLASSIFICATION_SCHEMA",
    "ABSENCE_REQUIRED_SCHEMA",
    "ABSENCE_SCHEMA",
    "ABSENT_STATES",
    "ALL_STATES",
    "AbsenceAlgebra",
    "AbsenceError",
    "AbsenceRecord",
    "AbsenceRequiredError",
    "AbsenceState",
    "ClassifiedOperand",
    "CONJUNCTION_SCHEMA",
    "ConjoinPolicy",
    "ConjunctionResult",
    "DEFAULT_FAILURE_CLASS",
    "DEFAULT_RULE_SNAPSHOT",
    "EMPTY_KINDS",
    "FAILURE_CLASSES",
    "FailureClass",
    "LINKER_ID",
    "MissingReference",
    "MissingReferenceError",
    "ObjectRef",
    "PRESENT_STATES",
    "PRESENCE_SCHEMA",
    "PresenceResult",
    "SnapshotMismatchError",
    "VOID_POLICIES",
    "VOID_VOID_POLICIES",
    "canonical_json",
    "digest_object",
]
