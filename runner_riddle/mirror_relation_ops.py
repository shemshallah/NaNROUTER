"""Host-only typed relation-operator registry for the Round 027 gap.

This module is deliberately a *control-plane contract*, not a math engine.
It declares the eight candidate relation operators requested for the mirror
layer (`is_a`, `part_of`, `causes`, `supports`, `refutes`, `equivalent`,
`transforms`, `observes`), validates only the composition rules explicitly
written into their descriptors, and plans bounded chains in the order the
caller supplied.  It never adds transitive closure, inheritance, or any other
inference over an unseen path.

Every operator must eventually be backed by a native NaN16 implementation.
A descriptor that is merely ``declared`` or ``planned`` is reported as typed
``UNAVAILABLE``; no Python function, arithmetic expression, or truth value is
substituted for the missing kernel.  The registry may carry evidence metadata,
but it never claims mathematical validation or execution authority.

Round 028 (generalization to unseen paths) is intentionally *not* implemented
here.  A query that supplies only endpoints and no explicit operator chain is
rejected rather than searched or guessed.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
import hashlib
import json
from typing import Any

RELATION_OPS_SCHEMA = "nanrouter.mirror-relation-ops/1"
RELATION_OPERATOR_SCHEMA = "nanrouter.mirror-relation-operator/1"
RELATION_PLAN_SCHEMA = "nanrouter.mirror-relation-plan/1"
RELATION_COMPATIBILITY_SCHEMA = "nanrouter.mirror-relation-compatibility/1"

ROUND = 27
ROUND_028_IMPLEMENTED = False

DIRECTION_FORWARD = "forward"
DIRECTION_REVERSE = "reverse"
DIRECTION_SYMMETRIC = "symmetric"
DIRECTION_VALUES = frozenset({
    DIRECTION_FORWARD, DIRECTION_REVERSE, DIRECTION_SYMMETRIC,
})

OP_STATUS_DECLARED = "declared"
OP_STATUS_PLANNED = "planned"
OP_STATUS_NATIVE_VERIFIED = "native_verified"
OP_STATUSES = frozenset({
    OP_STATUS_DECLARED, OP_STATUS_PLANNED, OP_STATUS_NATIVE_VERIFIED,
})

RESULT_STATUS_PLANNED = "PLANNED"
RESULT_STATUS_UNAVAILABLE = "UNAVAILABLE"
RESULT_STATUS_REJECTED = "REJECTED"

# Spelling aliases used by adjacent control-plane modules.
STATUS_DECLARED = OP_STATUS_DECLARED
STATUS_PLANNED = OP_STATUS_PLANNED
STATUS_NATIVE_VERIFIED = OP_STATUS_NATIVE_VERIFIED
RELATION_STATUS_PLANNED = RESULT_STATUS_PLANNED
RELATION_STATUS_UNAVAILABLE = RESULT_STATUS_UNAVAILABLE
RELATION_STATUS_REJECTED = RESULT_STATUS_REJECTED

REASON_UNKNOWN_OPERATOR = "unknown_operator"
REASON_INVALID_DESCRIPTOR = "invalid_descriptor"
REASON_DUPLICATE_OPERATOR = "operator_already_registered"
REASON_COMPOSITION_NOT_DECLARED = "composition_not_declared"
REASON_DOMAIN_CODOMAIN_MISMATCH = "domain_codomain_mismatch"
REASON_DIRECTION_NOT_ALLOWED = "direction_not_allowed"
REASON_REVERSE_NOT_DECLARED = "reverse_not_declared"
REASON_NONCOMMUTING = "noncommuting_order"
REASON_UNORDERED_CHAIN = "unordered_chain"
REASON_STEP_LIMIT = "step_limit_exceeded"
REASON_INVALID_BOUND = "invalid_bound"
REASON_BOUND_HARD_LIMIT = "bound_exceeds_hard_limit"
REASON_EMPTY_CHAIN = "empty_chain"
REASON_NATIVE_UNAVAILABLE = "native_implementation_unavailable"
REASON_EXPLICIT_CHAIN_REQUIRED = "explicit_chain_required"
REASON_INVALID_QUERY = "invalid_query"
REASON_ROUTE_UNAVAILABLE = "route_unavailable"
REASON_OPERATOR_NOT_NATIVE = REASON_NATIVE_UNAVAILABLE

DEFAULT_MAX_PATH_STEPS = 4
MAX_PATH_STEPS = 8

# Composition is allowed only when the right operator id is listed in the
# left operator's rules.  Empty rules mean "no composition"; they do not mean
# "transitive closure", "inheritance", or "same relation repeats".
DEFAULT_COMPOSITION_RULES = {
    "is_a": (),
    "part_of": ("equivalent",),
    "causes": ("equivalent",),
    "supports": ("equivalent",),
    "refutes": ("equivalent",),
    "equivalent": (
        "equivalent", "part_of", "causes", "supports", "refutes",
        "transforms",
    ),
    "transforms": ("transforms", "equivalent"),
    "observes": (),
}

_CHAIN_QUERY_KEYS = (
    "chain", "operators", "operator_chain", "ops", "path", "steps",
    "relations",
)
_SINGLE_QUERY_KEYS = ("operator", "op")


class RelationOperatorError(ValueError):
    """Base class for registry, descriptor, and planner failures."""

    reason = "relation_operator_error"

    def __init__(self, message: str, *, reason: str | None = None) -> None:
        super().__init__(message)
        self.reason = reason or type(self).reason


class RelationDescriptorError(RelationOperatorError):
    """An operator descriptor is malformed or claims unverifiable support."""

    reason = REASON_INVALID_DESCRIPTOR


class UnknownOperatorError(RelationOperatorError):
    """The requested operator is not present in this registry."""

    reason = REASON_UNKNOWN_OPERATOR


class RelationCompositionError(RelationOperatorError):
    """The supplied chain has no explicitly declared composition."""

    reason = REASON_COMPOSITION_NOT_DECLARED


class RelationDirectionError(RelationOperatorError):
    """The requested traversal direction is not declared by the operator."""

    reason = REASON_DIRECTION_NOT_ALLOWED


class RelationNoncommutingError(RelationOperatorError):
    """The caller asked to treat noncommuting operators as reorderable."""

    reason = REASON_NONCOMMUTING


class RelationBoundError(RelationOperatorError):
    """A chain or planner request exceeds its declared step bound."""

    reason = REASON_STEP_LIMIT


class RelationUnavailableError(RelationOperatorError):
    """A caller required a plan although no native implementation exists."""

    reason = REASON_NATIVE_UNAVAILABLE


def _require_text(value: Any, name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(character.isspace() for character in value)
    ):
        raise RelationDescriptorError(f"{name} must be a nonempty token")
    return value


def _optional_text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, name)


def _text_tuple(value: Any, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        values: tuple[Any, ...] = (value,)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        values = tuple(value)
    else:
        raise RelationDescriptorError(
            f"{name} must be a string or a sequence of strings"
        )
    checked = []
    for item in values:
        checked.append(_require_text(item, name))
    return tuple(dict.fromkeys(checked))


def _normalise_direction(value: Any) -> str:
    if not isinstance(value, str):
        raise RelationDirectionError(
            "direction must be forward, reverse, or symmetric",
            reason=REASON_DIRECTION_NOT_ALLOWED,
        )
    aliases = {
        "forward": DIRECTION_FORWARD,
        "directed": DIRECTION_FORWARD,
        "reverse": DIRECTION_REVERSE,
        "reversed": DIRECTION_REVERSE,
        "symmetric": DIRECTION_SYMMETRIC,
        "bidirectional": DIRECTION_SYMMETRIC,
        "both": DIRECTION_SYMMETRIC,
        "undirected": DIRECTION_SYMMETRIC,
    }
    normalised = aliases.get(value.strip().lower())
    if normalised is None:
        raise RelationDirectionError(
            f"unknown relation direction: {value!r}",
            reason=REASON_DIRECTION_NOT_ALLOWED,
        )
    return normalised


def _normalise_bound(value: Any, *, default: int = DEFAULT_MAX_PATH_STEPS) -> int:
    if value is None:
        value = default
    if type(value) is not int or value < 1:
        raise RelationBoundError(
            "max_steps must be a positive integer",
            reason=REASON_INVALID_BOUND,
        )
    if value > MAX_PATH_STEPS:
        raise RelationBoundError(
            f"max_steps exceeds the hard maximum of {MAX_PATH_STEPS}",
            reason=REASON_BOUND_HARD_LIMIT,
        )
    return value


def canonical_relation_json(value: Any) -> str:
    """Return deterministic JSON for registry and plan documents."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise RelationOperatorError("value is not canonical JSON") from exc


# Alias with the same spelling used by other control-plane modules.
canonical_json = canonical_relation_json


def plan_digest(value: RelationPlanResult | Mapping[str, Any]) -> str:
    """Return the SHA-256 of a result document, excluding its digest field."""
    if isinstance(value, RelationPlanResult):
        document = value.to_dict()
    elif isinstance(value, Mapping):
        document = dict(value)
    else:
        raise RelationOperatorError(
            "plan_digest requires a RelationPlanResult or mapping"
        )
    document.pop("plan_digest", None)
    return hashlib.sha256(
        canonical_relation_json(document).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, init=False)
class RelationOperatorDescriptor:
    """One typed relation operator and its explicitly declared composition.

    ``composition_rules`` names the operator ids that may immediately follow
    this operator.  A missing entry denies composition.  ``status`` describes
    implementation availability only; it is never a proof of mathematical
    truth.  ``native_implementation_requirement`` names the native NaN16
    kernel that would be needed, while ``native_implementation`` is populated
    only for an already registered native implementation.
    """

    id: str
    domain: str
    codomain: str
    composition_rules: tuple[str, ...]
    direction: str
    noncommuting: bool
    status: str
    native_implementation_requirement: str | None
    native_implementation: str | None
    evidence: tuple[str, ...]
    description: str

    def __init__(
        self,
        id: str | None = None,
        *,
        operator_id: str | None = None,
        op_id: str | None = None,
        domain: str = "entity",
        codomain: str = "entity",
        composition_rules: Sequence[str] | str | None = None,
        composes_with: Sequence[str] | str | None = None,
        composition: Sequence[str] | str | None = None,
        rules: Sequence[str] | str | None = None,
        direction: str = DIRECTION_FORWARD,
        noncommuting: bool = True,
        non_commuting: bool | None = None,
        status: str = OP_STATUS_DECLARED,
        native_implementation_requirement: str | None = None,
        native_requirement: str | None = None,
        requires_native: str | bool | None = None,
        native_implementation_required: str | bool | None = None,
        requires_native_implementation: str | bool | None = None,
        native_implementation: str | None = None,
        evidence: Sequence[str] | str | None = None,
        description: str = "",
        **aliases: Any,
    ) -> None:
        if aliases:
            names = ", ".join(sorted(aliases))
            raise RelationDescriptorError(
                f"unknown descriptor fields: {names}",
                reason=REASON_INVALID_DESCRIPTOR,
            )
        identifiers = [value for value in (id, operator_id, op_id)
                       if value is not None]
        if len(identifiers) != 1:
            raise RelationDescriptorError(
                "exactly one of id, operator_id, or op_id is required",
                reason=REASON_INVALID_DESCRIPTOR,
            )
        operator = _require_text(identifiers[0], "operator id")
        domain_text = _require_text(domain, "domain")
        codomain_text = _require_text(codomain, "codomain")

        rule_values = None
        for candidate in (composition_rules, composes_with, composition, rules):
            if candidate is not None:
                if rule_values is not None:
                    raise RelationDescriptorError(
                        "composition rules were supplied more than once",
                        reason=REASON_INVALID_DESCRIPTOR,
                    )
                rule_values = candidate
        declared_rules = _text_tuple(rule_values, "composition rules")

        direction_value = _normalise_direction(direction)
        if non_commuting is not None:
            noncommuting = non_commuting
        if not isinstance(noncommuting, bool):
            raise RelationDescriptorError(
                "noncommuting must be a boolean",
                reason=REASON_INVALID_DESCRIPTOR,
            )
        if not isinstance(status, str):
            raise RelationDescriptorError(
                "status must be a string",
                reason=REASON_INVALID_DESCRIPTOR,
            )
        status_value = status.strip().lower()
        if status_value not in OP_STATUSES:
            raise RelationDescriptorError(
                f"unknown operator status: {status!r}",
                reason=REASON_INVALID_DESCRIPTOR,
            )

        requirement = native_implementation_requirement
        if requirement is None:
            requirement = native_requirement
        for candidate in (
            requires_native,
            native_implementation_required,
            requires_native_implementation,
        ):
            if isinstance(candidate, str):
                if requirement is None:
                    requirement = candidate
            elif candidate is True and requirement is None:
                requirement = f"mth.relation.{operator}.q16.16"
        requirement_value = _optional_text(
            requirement, "native implementation requirement"
        )
        implementation_value = _optional_text(
            native_implementation, "native implementation"
        )
        evidence_value = _text_tuple(evidence, "evidence")
        if not isinstance(description, str):
            raise RelationDescriptorError(
                "description must be a string",
                reason=REASON_INVALID_DESCRIPTOR,
            )

        if status_value == OP_STATUS_NATIVE_VERIFIED:
            if implementation_value is None:
                raise RelationDescriptorError(
                    "native_verified requires a native implementation id",
                    reason=REASON_INVALID_DESCRIPTOR,
                )
            if not evidence_value:
                raise RelationDescriptorError(
                    "native_verified requires evidence metadata",
                    reason=REASON_INVALID_DESCRIPTOR,
                )
            if requirement_value is None:
                requirement_value = implementation_value

        object.__setattr__(self, "id", operator)
        object.__setattr__(self, "domain", domain_text)
        object.__setattr__(self, "codomain", codomain_text)
        object.__setattr__(self, "composition_rules", declared_rules)
        object.__setattr__(self, "direction", direction_value)
        object.__setattr__(self, "noncommuting", noncommuting)
        object.__setattr__(self, "status", status_value)
        object.__setattr__(
            self, "native_implementation_requirement", requirement_value
        )
        object.__setattr__(
            self, "native_implementation", implementation_value
        )
        object.__setattr__(self, "evidence", evidence_value)
        object.__setattr__(self, "description", description)

    @property
    def operator_id(self) -> str:
        return self.id

    @property
    def composes_with(self) -> tuple[str, ...]:
        return self.composition_rules

    @property
    def native_available(self) -> bool:
        return (
            self.status == OP_STATUS_NATIVE_VERIFIED
            and self.native_implementation is not None
            and bool(self.evidence)
        )

    @property
    def native_implementation_required(self) -> bool:
        return not self.native_available

    @property
    def requires_native_nan16(self) -> bool:
        return True

    @property
    def composition(self) -> tuple[str, ...]:
        return self.composition_rules

    @property
    def native_requirement(self) -> str | None:
        return self.native_implementation_requirement

    @property
    def native_required(self) -> bool:
        return self.native_implementation_required

    @property
    def non_commuting(self) -> bool:
        return self.noncommuting

    @property
    def validated(self) -> bool:
        return self.native_available

    def as_dict(self) -> dict[str, Any]:
        return self.to_dict()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RELATION_OPERATOR_SCHEMA,
            "id": self.id,
            "domain": self.domain,
            "codomain": self.codomain,
            "composition_rules": list(self.composition_rules),
            "direction": self.direction,
            "noncommuting": self.noncommuting,
            "status": self.status,
            "native_implementation_requirement": (
                self.native_implementation_requirement
            ),
            "native_implementation": self.native_implementation,
            "native_available": self.native_available,
            "evidence": list(self.evidence),
            "description": self.description,
            "native_execution_verified": False,
            "mathematical_truth_promoted": False,
            "authority_granted": False,
        }


# Friendly aliases for callers that prefer a shorter or contract-style name.
RelationOperator = RelationOperatorDescriptor
OperatorDescriptor = RelationOperatorDescriptor
TypedRelationOperator = RelationOperatorDescriptor


def _default_operator_descriptors() -> tuple[RelationOperatorDescriptor, ...]:
    specs = (
        {
            "id": "is_a",
            "domain": "entity",
            "codomain": "category",
            "direction": DIRECTION_FORWARD,
            "noncommuting": True,
            "description": "instance-to-category classification",
        },
        {
            "id": "part_of",
            "domain": "entity",
            "codomain": "entity",
            "direction": DIRECTION_FORWARD,
            "noncommuting": True,
            "description": "component or member containment",
        },
        {
            "id": "causes",
            "domain": "entity",
            "codomain": "entity",
            "direction": DIRECTION_FORWARD,
            "noncommuting": True,
            "description": "directed causal claim",
        },
        {
            "id": "supports",
            "domain": "entity",
            "codomain": "entity",
            "direction": DIRECTION_FORWARD,
            "noncommuting": True,
            "description": "positive evidential support",
        },
        {
            "id": "refutes",
            "domain": "entity",
            "codomain": "entity",
            "direction": DIRECTION_FORWARD,
            "noncommuting": True,
            "description": "negative evidential challenge",
        },
        {
            "id": "equivalent",
            "domain": "entity",
            "codomain": "entity",
            "direction": DIRECTION_SYMMETRIC,
            "noncommuting": False,
            "description": "explicit symmetric equivalence",
        },
        {
            "id": "transforms",
            "domain": "entity",
            "codomain": "entity",
            "direction": DIRECTION_FORWARD,
            "noncommuting": True,
            "description": "ordered state transformation",
        },
        {
            "id": "observes",
            "domain": "entity",
            "codomain": "observation",
            "direction": DIRECTION_FORWARD,
            "noncommuting": True,
            "description": "directed observation to an observation record",
        },
    )
    descriptors = []
    for spec in specs:
        operator = str(spec["id"])
        descriptors.append(RelationOperatorDescriptor(
            id=operator,
            domain=str(spec["domain"]),
            codomain=str(spec["codomain"]),
            composition_rules=DEFAULT_COMPOSITION_RULES.get(operator, ()),
            direction=str(spec["direction"]),
            noncommuting=bool(spec["noncommuting"]),
            status=OP_STATUS_DECLARED,
            native_implementation_requirement=(
                f"mth.relation.{operator}.q16.16"
            ),
            evidence=(f"round-027:declared-candidate:{operator}",),
            description=str(spec["description"]),
        ))
    return tuple(descriptors)


DEFAULT_OPERATORS = _default_operator_descriptors()
DEFAULT_OPERATOR_IDS = tuple(item.id for item in DEFAULT_OPERATORS)


@dataclass(frozen=True)
class CompatibilityResult:
    """Typed explanation of one adjacent composition decision."""

    left: str
    right: str
    compatible: bool
    reason: str | None = None
    detail: str | None = None
    direction: str = DIRECTION_FORWARD
    commute: bool = False

    def __bool__(self) -> bool:
        return self.compatible

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RELATION_COMPATIBILITY_SCHEMA,
            "left": self.left,
            "right": self.right,
            "compatible": self.compatible,
            "reason": self.reason,
            "detail": self.detail,
            "direction": self.direction,
            "commute": self.commute,
            "composition_only_when_declared": True,
            "implicit_transitivity": False,
            "inheritance_inference": False,
            "native_execution_verified": False,
            "authority_granted": False,
        }


@dataclass(frozen=True)
class RelationPlanResult:
    """A bounded composition decision, never a native execution receipt."""

    status: str
    chain: tuple[str, ...]
    steps: tuple[dict[str, Any], ...]
    max_steps: int
    reason: str | None = None
    detail: str | None = None
    composition_valid: bool = False
    native_implementation_available: bool = False
    unavailable_operators: tuple[str, ...] = ()
    plan_digest: str | None = None
    query_id: str | None = None
    direction: str = DIRECTION_FORWARD
    schema: str = RELATION_PLAN_SCHEMA
    deterministic: bool = True
    native_execution_verified: bool = False
    mathematical_truth_promoted: bool = False
    authority_granted: bool = False
    generalization: bool = False
    round_028_implemented: bool = False

    @property
    def available(self) -> bool:
        return self.status == RESULT_STATUS_PLANNED

    @property
    def step_count(self) -> int:
        return len(self.steps)

    @property
    def operators(self) -> tuple[str, ...]:
        return self.chain

    @property
    def unavailable(self) -> tuple[str, ...]:
        return self.unavailable_operators

    @property
    def native_available(self) -> bool:
        return self.native_implementation_available

    @property
    def valid(self) -> bool:
        return self.composition_valid

    @property
    def plan(self) -> RelationPlanResult | None:
        return self if self.available else None

    @property
    def digest(self) -> str | None:
        return self.plan_digest

    def require_plan(self) -> RelationPlanResult:
        if not self.available:
            raise RelationUnavailableError(
                f"relation route is {self.status}: "
                f"{self.detail or self.reason or REASON_ROUTE_UNAVAILABLE}",
                reason=self.reason or REASON_ROUTE_UNAVAILABLE,
            )
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "status": self.status,
            "chain": list(self.chain),
            "operators": list(self.chain),
            "steps": [dict(step) for step in self.steps],
            "step_count": len(self.steps),
            "max_steps": self.max_steps,
            "reason": self.reason,
            "detail": self.detail,
            "composition_valid": self.composition_valid,
            "native_implementation_available": (
                self.native_implementation_available
            ),
            "unavailable_operators": list(self.unavailable_operators),
            "plan_digest": self.plan_digest,
            "query_id": self.query_id,
            "direction": self.direction,
            "deterministic": self.deterministic,
            "native_execution_verified": False,
            "mathematical_truth_promoted": False,
            "authority_granted": False,
            "generalization": False,
            "round_028_implemented": False,
        }

    def to_json(self) -> str:
        """Return the deterministic JSON document for this result."""
        return canonical_relation_json(self.to_dict())

    # Mapping-style access keeps the result usable by both attribute and
    # document-oriented callers without creating a second result type.
    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def keys(self):
        return self.to_dict().keys()

    def values(self):
        return self.to_dict().values()

    def items(self):
        return self.to_dict().items()

    def __contains__(self, key: str) -> bool:
        return key in self.to_dict()

    def __iter__(self):
        return iter(self.to_dict())


def _chain_items(value: Any) -> tuple[Any, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, RelationOperatorDescriptor):
        return (value,)
    if isinstance(value, Mapping):
        for key in _CHAIN_QUERY_KEYS:
            if key in value:
                return _chain_items(value[key])
        for key in _SINGLE_QUERY_KEYS:
            if key in value:
                return _chain_items(value[key])
        raise RelationCompositionError(
            "an explicit operator chain is required",
            reason=REASON_INVALID_QUERY,
        )
    if isinstance(value, (set, frozenset)):
        raise RelationCompositionError(
            "an unordered operator set cannot define a chain",
            reason=REASON_UNORDERED_CHAIN,
        )
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return tuple(value)
    if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        return tuple(value)
    raise RelationCompositionError(
        "operator chain must be a sequence or operator id",
        reason=REASON_INVALID_QUERY,
    )


def _best_effort_chain_ids(value: Any) -> tuple[str, ...]:
    try:
        items = _chain_items(value)
    except RelationOperatorError:
        return ()
    identifiers = []
    for item in items:
        if isinstance(item, str):
            identifiers.append(item)
        elif isinstance(item, RelationOperatorDescriptor):
            identifiers.append(item.id)
        elif isinstance(item, Mapping):
            for key in ("id", "operator_id", "op_id"):
                if isinstance(item.get(key), str):
                    identifiers.append(item[key])
                    break
    return tuple(identifiers)


def _step_documents(
    operators: Sequence[RelationOperatorDescriptor],
) -> tuple[dict[str, Any], ...]:
    documents = []
    for index, operator in enumerate(operators):
        documents.append({
            "index": index,
            "operator": operator.id,
            "domain": operator.domain,
            "codomain": operator.codomain,
            "direction": operator.direction,
            "noncommuting": operator.noncommuting,
            "status": operator.status,
            "native_implementation_requirement": (
                operator.native_implementation_requirement
            ),
            "native_implementation": operator.native_implementation,
            "native_available": operator.native_available,
            "evidence": list(operator.evidence),
            "native_execution_verified": False,
            "authority_granted": False,
        })
    return tuple(documents)


def _rejected_result(
    chain: tuple[str, ...],
    reason: str,
    detail: str,
    max_steps: int,
    *,
    query_id: str | None = None,
    direction: str = DIRECTION_FORWARD,
) -> RelationPlanResult:
    return RelationPlanResult(
        status=RESULT_STATUS_REJECTED,
        chain=chain,
        steps=(),
        max_steps=max_steps,
        reason=reason,
        detail=detail,
        composition_valid=False,
        native_implementation_available=False,
        unavailable_operators=(),
        plan_digest=None,
        query_id=query_id,
        direction=direction,
    )


class RelationOperatorRegistry:
    """Typed operators, explicit composition rules, and a bounded planner.

    Instances are independent and deterministic.  With no constructor
    arguments the eight Round 027 candidates are registered as ``declared``
    and therefore remain unavailable until a native implementation is
    explicitly registered with evidence.
    """

    def __init__(
        self,
        operators: Iterable[RelationOperatorDescriptor | Mapping[str, Any]] | Mapping[str, Any] | None = None,
        *,
        include_defaults: bool | None = None,
    ) -> None:
        self._operators: dict[str, RelationOperatorDescriptor] = {}
        if include_defaults is None:
            include_defaults = operators is None
        if include_defaults:
            for descriptor in DEFAULT_OPERATORS:
                self._operators[descriptor.id] = descriptor
        if operators is not None:
            if isinstance(operators, Mapping):
                candidates = operators.values()
            else:
                candidates = operators
            for operator in candidates:
                self.register(operator, replace=True)

    @property
    def operator_ids(self) -> tuple[str, ...]:
        return tuple(self._operators)

    @property
    def ids(self) -> tuple[str, ...]:
        return self.operator_ids

    @property
    def operators(self) -> tuple[RelationOperatorDescriptor, ...]:
        return tuple(self._operators.values())

    def __len__(self) -> int:
        return len(self._operators)

    def __iter__(self):
        return iter(self._operators.values())

    def __contains__(self, operator_id: Any) -> bool:
        if isinstance(operator_id, RelationOperatorDescriptor):
            operator_id = operator_id.id
        return isinstance(operator_id, str) and operator_id in self._operators

    def register(
        self,
        operator: RelationOperatorDescriptor | Mapping[str, Any] | str | None = None,
        *,
        replace: bool = False,
        **fields: Any,
    ) -> RelationOperatorDescriptor:
        """Register a descriptor; duplicates require an explicit replace."""
        if operator is None:
            descriptor = RelationOperatorDescriptor(**fields)
        elif isinstance(operator, RelationOperatorDescriptor):
            if fields:
                raise RelationDescriptorError(
                    "fields cannot accompany a descriptor instance",
                    reason=REASON_INVALID_DESCRIPTOR,
                )
            descriptor = operator
        elif isinstance(operator, Mapping):
            document = dict(operator)
            document.update(fields)
            descriptor = RelationOperatorDescriptor(**document)
        elif isinstance(operator, str):
            document = dict(fields)
            document.setdefault("id", operator)
            descriptor = RelationOperatorDescriptor(**document)
        else:
            raise RelationDescriptorError(
                "register requires a descriptor, mapping, or operator id",
                reason=REASON_INVALID_DESCRIPTOR,
            )

        existing = self._operators.get(descriptor.id)
        if existing is not None and not replace:
            if existing.to_dict() == descriptor.to_dict():
                return existing
            raise RelationDescriptorError(
                f"operator {descriptor.id!r} is already registered",
                reason=REASON_DUPLICATE_OPERATOR,
            )
        self._operators[descriptor.id] = descriptor
        return descriptor

    def require(self, operator_id: Any) -> RelationOperatorDescriptor:
        """Return a registered descriptor or raise ``UnknownOperatorError``."""
        if isinstance(operator_id, RelationOperatorDescriptor):
            operator_id = operator_id.id
        elif isinstance(operator_id, Mapping):
            operator_id = (
                operator_id.get("id")
                or operator_id.get("operator_id")
                or operator_id.get("op_id")
            )
        if not isinstance(operator_id, str) or not operator_id:
            raise UnknownOperatorError(
                "operator id must be a nonempty string",
                reason=REASON_UNKNOWN_OPERATOR,
            )
        descriptor = self._operators.get(operator_id)
        if descriptor is None:
            raise UnknownOperatorError(
                f"unknown relation operator: {operator_id!r}",
                reason=REASON_UNKNOWN_OPERATOR,
            )
        return descriptor

    def _resolve(self, value: Any) -> RelationOperatorDescriptor:
        if isinstance(value, RelationOperatorDescriptor):
            return self.require(value.id)
        if isinstance(value, Mapping):
            return self.require(value)
        if isinstance(value, str):
            return self.require(value)
        raise UnknownOperatorError(
            "operator must be a registered descriptor or id",
            reason=REASON_UNKNOWN_OPERATOR,
        )

    def compatibility(
        self,
        left: Any,
        right: Any,
        *,
        direction: str = DIRECTION_FORWARD,
        commute: bool = False,
    ) -> CompatibilityResult:
        """Explain whether ``right`` may immediately follow ``left``.

        ``direction='reverse'`` evaluates the reversed adjacent pair and is
        accepted only for symmetric or explicitly reversible operators.
        ``commute=True`` is rejected whenever either operator is marked
        noncommuting; it never sorts or rewrites the chain.
        """
        left_operator = self._resolve(left)
        right_operator = self._resolve(right)
        direction_value = _normalise_direction(direction)
        if not isinstance(commute, bool):
            raise RelationCompositionError(
                "commute must be a boolean",
                reason=REASON_INVALID_QUERY,
            )

        if direction_value == DIRECTION_REVERSE:
            first, second = right_operator, left_operator
            for operator in (first, second):
                if operator.direction not in (
                    DIRECTION_SYMMETRIC, DIRECTION_REVERSE,
                ):
                    return CompatibilityResult(
                        left=left_operator.id,
                        right=right_operator.id,
                        compatible=False,
                        reason=REASON_REVERSE_NOT_DECLARED,
                        detail=(
                            f"operator {operator.id!r} has no declared "
                            "reverse traversal"
                        ),
                        direction=direction_value,
                        commute=commute,
                    )
        else:
            first, second = left_operator, right_operator
            for operator in (first, second):
                if operator.direction not in (
                    DIRECTION_FORWARD, DIRECTION_SYMMETRIC,
                ):
                    return CompatibilityResult(
                        left=left_operator.id,
                        right=right_operator.id,
                        compatible=False,
                        reason=REASON_DIRECTION_NOT_ALLOWED,
                        detail=(
                            f"operator {operator.id!r} is not declared in "
                            "the requested forward direction"
                        ),
                        direction=direction_value,
                        commute=commute,
                    )

        if commute and (first.noncommuting or second.noncommuting):
            return CompatibilityResult(
                left=left_operator.id,
                right=right_operator.id,
                compatible=False,
                reason=REASON_NONCOMMUTING,
                detail="a noncommuting operator cannot be reordered",
                direction=direction_value,
                commute=commute,
            )
        if first.codomain != second.domain:
            return CompatibilityResult(
                left=left_operator.id,
                right=right_operator.id,
                compatible=False,
                reason=REASON_DOMAIN_CODOMAIN_MISMATCH,
                detail=(
                    f"codomain {first.codomain!r} does not match "
                    f"domain {second.domain!r}"
                ),
                direction=direction_value,
                commute=commute,
            )
        if second.id not in first.composition_rules:
            return CompatibilityResult(
                left=left_operator.id,
                right=right_operator.id,
                compatible=False,
                reason=REASON_COMPOSITION_NOT_DECLARED,
                detail=(
                    f"{first.id!r} does not explicitly declare composition "
                    f"with {second.id!r}"
                ),
                direction=direction_value,
                commute=commute,
            )
        return CompatibilityResult(
            left=left_operator.id,
            right=right_operator.id,
            compatible=True,
            direction=direction_value,
            commute=commute,
        )

    def compatible(
        self,
        left: Any,
        right: Any,
        *,
        direction: str = DIRECTION_FORWARD,
        commute: bool = False,
    ) -> bool:
        """Boolean form of :meth:`compatibility` for predicate callers."""
        return self.compatibility(
            left, right, direction=direction, commute=commute
        ).compatible

    def check_compatible(
        self,
        left: Any,
        right: Any,
        *,
        direction: str = DIRECTION_FORWARD,
        commute: bool = False,
    ) -> CompatibilityResult:
        """Alias of :meth:`compatibility` with an explicit typed return."""
        return self.compatibility(
            left, right, direction=direction, commute=commute
        )

    explain_compatible = check_compatible

    def compose(
        self,
        chain: Any,
        *,
        direction: str = DIRECTION_FORWARD,
        max_steps: int | None = None,
        commute: bool = False,
    ) -> RelationPlanResult:
        """Plan one explicitly ordered chain or return typed UNAVAILABLE.

        Structural rejection (unknown operator, undeclared composition,
        wrong direction, noncommuting reorder, or a bound violation) raises a
        typed :class:`RelationOperatorError`.  A structurally valid chain
        whose operators lack a native NaN16 implementation returns
        ``UNAVAILABLE`` with no plan digest.  Only a chain whose every
        operator is registered as ``native_verified`` with evidence returns
        ``PLANNED``; even then no kernel is executed here.
        """
        items = _chain_items(chain)
        bound = _normalise_bound(max_steps)
        if not items:
            raise RelationCompositionError(
                "at least one operator is required",
                reason=REASON_EMPTY_CHAIN,
            )
        if len(items) > bound:
            raise RelationBoundError(
                f"chain has {len(items)} steps, above the bound of {bound}",
                reason=REASON_STEP_LIMIT,
            )
        if not isinstance(commute, bool):
            raise RelationCompositionError(
                "commute must be a boolean",
                reason=REASON_INVALID_QUERY,
            )
        direction_value = _normalise_direction(direction)
        resolved = tuple(self._resolve(item) for item in items)

        if commute:
            for operator in resolved:
                if operator.noncommuting:
                    raise RelationNoncommutingError(
                        f"operator {operator.id!r} is noncommuting and "
                        "cannot be reordered",
                        reason=REASON_NONCOMMUTING,
                    )

        if direction_value == DIRECTION_REVERSE:
            for operator in resolved:
                if operator.direction not in (
                    DIRECTION_SYMMETRIC, DIRECTION_REVERSE,
                ):
                    raise RelationDirectionError(
                        f"operator {operator.id!r} has no declared reverse "
                        "traversal",
                        reason=REASON_REVERSE_NOT_DECLARED,
                    )
            ordered = tuple(reversed(resolved))
        else:
            for operator in resolved:
                if operator.direction not in (
                    DIRECTION_FORWARD, DIRECTION_SYMMETRIC,
                ):
                    raise RelationDirectionError(
                        f"operator {operator.id!r} is not declared in the "
                        "forward direction",
                        reason=REASON_DIRECTION_NOT_ALLOWED,
                    )
            ordered = resolved

        for first, second in zip(ordered, ordered[1:]):
            decision = self.compatibility(
                first, second,
                direction=DIRECTION_FORWARD,
                commute=False,
            )
            if not decision.compatible:
                if decision.reason in (
                    REASON_DIRECTION_NOT_ALLOWED,
                    REASON_REVERSE_NOT_DECLARED,
                ):
                    raise RelationDirectionError(
                        decision.detail or "direction rejected",
                        reason=decision.reason,
                    )
                if decision.reason == REASON_NONCOMMUTING:
                    raise RelationNoncommutingError(
                        decision.detail or "noncommuting order rejected",
                        reason=REASON_NONCOMMUTING,
                    )
                raise RelationCompositionError(
                    decision.detail or "composition rejected",
                    reason=(
                        decision.reason
                        or REASON_COMPOSITION_NOT_DECLARED
                    ),
                )

        ordered_ids = tuple(operator.id for operator in ordered)
        steps = _step_documents(ordered)
        unavailable = tuple(
            operator.id for operator in ordered
            if not operator.native_available
        )
        if unavailable:
            return RelationPlanResult(
                status=RESULT_STATUS_UNAVAILABLE,
                chain=ordered_ids,
                steps=steps,
                max_steps=bound,
                reason=REASON_NATIVE_UNAVAILABLE,
                detail=(
                    "no native NaN16 implementation is registered for: "
                    f"{', '.join(unavailable)}"
                ),
                composition_valid=True,
                native_implementation_available=False,
                unavailable_operators=unavailable,
                plan_digest=None,
                direction=direction_value,
            )

        result = RelationPlanResult(
            status=RESULT_STATUS_PLANNED,
            chain=ordered_ids,
            steps=steps,
            max_steps=bound,
            composition_valid=True,
            native_implementation_available=True,
            unavailable_operators=(),
            plan_digest=None,
            direction=direction_value,
        )
        return replace(result, plan_digest=plan_digest(result))

    def plan_path(
        self,
        query: Any,
        *,
        direction: str | None = None,
        max_steps: int | None = None,
        commute: bool | None = None,
    ) -> RelationPlanResult:
        """Plan a bounded, explicitly requested operator chain.

        ``query`` may be an operator id, a sequence of ids, or a mapping with
        ``chain``/``operators`` and optional ``direction``, ``max_steps``, and
        ``commute`` fields.  A mapping containing only endpoints is rejected
        with ``explicit_chain_required``: this module does not search for or
        generalize to unseen paths.
        """
        query_direction = None
        query_max_steps = None
        query_commute = None
        query_id = None
        query_error = None
        chain_value = query
        if isinstance(query, Mapping):
            for key in _CHAIN_QUERY_KEYS:
                if key in query:
                    chain_value = query[key]
                    break
            else:
                for key in _SINGLE_QUERY_KEYS:
                    if key in query:
                        chain_value = query[key]
                        break
                else:
                    if "source" in query or "target" in query:
                        query_error = RelationCompositionError(
                            "an explicit operator chain is required; "
                            "endpoint-only queries are not searched",
                            reason=REASON_EXPLICIT_CHAIN_REQUIRED,
                        )
                        chain_value = ()
                    else:
                        chain_value = query
            query_direction = query.get("direction")
            for key in ("max_steps", "max_path_steps", "limit"):
                if query.get(key) is not None:
                    query_max_steps = query[key]
                    break
            for key in ("commute", "unordered", "commutative"):
                if query.get(key) is not None:
                    query_commute = query[key]
                    break
            for key in ("query_id", "id"):
                if isinstance(query.get(key), str):
                    query_id = query[key]
                    break

        if direction is None:
            direction = query_direction or DIRECTION_FORWARD
        if max_steps is None:
            max_steps = query_max_steps
        if commute is None:
            commute = bool(query_commute)

        bound = DEFAULT_MAX_PATH_STEPS
        direction_label = (
            direction if isinstance(direction, str) else DIRECTION_FORWARD
        )
        try:
            if query_error is not None:
                raise query_error
            if max_steps is not None:
                bound = _normalise_bound(max_steps)
            result = self.compose(
                chain_value,
                direction=direction,
                max_steps=bound,
                commute=commute,
            )
        except RelationOperatorError as exc:
            return _rejected_result(
                _best_effort_chain_ids(chain_value),
                exc.reason,
                str(exc),
                bound,
                query_id=query_id,
                direction=direction_label,
            )
        if query_id is not None:
            result = replace(result, query_id=query_id)
        return result

    def status(self, operator_id: Any | None = None) -> dict[str, Any]:
        """Return registry status, or one descriptor document when named."""
        if operator_id is not None:
            descriptor = self.require(operator_id)
            document = descriptor.to_dict()
            document["registry_schema"] = RELATION_OPS_SCHEMA
            return document

        operators = tuple(self._operators.values())
        counts = Counter(descriptor.status for descriptor in operators)
        native_available = tuple(
            descriptor.id for descriptor in operators
            if descriptor.native_available
        )
        return {
            "schema": RELATION_OPS_SCHEMA,
            "round": ROUND,
            "round_028_implemented": False,
            "generalization": False,
            "unseen_path_inference": False,
            "implicit_transitivity": False,
            "inheritance_inference": False,
            "operator_count": len(operators),
            "operator_ids": [descriptor.id for descriptor in operators],
            "status_counts": {
                status: counts.get(status, 0) for status in OP_STATUSES
            },
            "native_available": list(native_available),
            "unavailable": [
                descriptor.id for descriptor in operators
                if not descriptor.native_available
            ],
            "composition_rules": {
                descriptor.id: list(descriptor.composition_rules)
                for descriptor in operators
            },
            "operators": [
                descriptor.to_dict() for descriptor in operators
            ],
            "declared_only_is_unavailable": True,
            "native_execution_verified": False,
            "mathematical_truth_promoted": False,
            "authority_granted": False,
            "deterministic": True,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.status()

    def as_dict(self) -> dict[str, Any]:
        return self.status()

    report = status
    describe = status


# Convention-friendly aliases.  They are the same class, not alternate
# authorities or a second registry implementation.
RelationRegistry = RelationOperatorRegistry
TypedRelationRegistry = RelationOperatorRegistry
OperatorRegistry = RelationOperatorRegistry


__all__ = [
    "DEFAULT_COMPOSITION_RULES",
    "DEFAULT_MAX_PATH_STEPS",
    "DEFAULT_OPERATORS",
    "DEFAULT_OPERATOR_IDS",
    "DIRECTION_FORWARD",
    "DIRECTION_REVERSE",
    "DIRECTION_SYMMETRIC",
    "DIRECTION_VALUES",
    "MAX_PATH_STEPS",
    "OP_STATUSES",
    "OP_STATUS_DECLARED",
    "OP_STATUS_NATIVE_VERIFIED",
    "OP_STATUS_PLANNED",
    "OperatorDescriptor",
    "OperatorRegistry",
    "REASON_BOUND_HARD_LIMIT",
    "REASON_COMPOSITION_NOT_DECLARED",
    "REASON_DIRECTION_NOT_ALLOWED",
    "REASON_DOMAIN_CODOMAIN_MISMATCH",
    "REASON_DUPLICATE_OPERATOR",
    "REASON_EMPTY_CHAIN",
    "REASON_EXPLICIT_CHAIN_REQUIRED",
    "REASON_INVALID_BOUND",
    "REASON_INVALID_DESCRIPTOR",
    "REASON_INVALID_QUERY",
    "REASON_NATIVE_UNAVAILABLE",
    "REASON_NONCOMMUTING",
    "REASON_REVERSE_NOT_DECLARED",
    "REASON_ROUTE_UNAVAILABLE",
    "REASON_STEP_LIMIT",
    "REASON_UNKNOWN_OPERATOR",
    "REASON_UNORDERED_CHAIN",
    "RELATION_COMPATIBILITY_SCHEMA",
    "RELATION_OPERATOR_SCHEMA",
    "RELATION_OPS_SCHEMA",
    "RELATION_PLAN_SCHEMA",
    "RELATION_STATUS_PLANNED",
    "RELATION_STATUS_REJECTED",
    "RELATION_STATUS_UNAVAILABLE",
    "REASON_OPERATOR_NOT_NATIVE",
    "RESULT_STATUS_PLANNED",
    "RESULT_STATUS_REJECTED",
    "RESULT_STATUS_UNAVAILABLE",
    "ROUND",
    "ROUND_028_IMPLEMENTED",
    "STATUS_DECLARED",
    "STATUS_NATIVE_VERIFIED",
    "STATUS_PLANNED",
    "RelationBoundError",
    "RelationCompatibilityResult",
    "RelationCompositionError",
    "RelationDescriptorError",
    "RelationDirectionError",
    "RelationNoncommutingError",
    "RelationOperator",
    "RelationOperatorDescriptor",
    "RelationOperatorError",
    "RelationOperatorRegistry",
    "RelationPlanResult",
    "RelationRegistry",
    "RelationUnavailableError",
    "TypedRelationOperator",
    "TypedRelationRegistry",
    "UnknownOperatorError",
    "canonical_json",
    "canonical_relation_json",
    "plan_digest",
]

# CompatibilityResult is exported under a relation-prefixed alias as well.
RelationCompatibilityResult = CompatibilityResult
