"""Relation, hyperedge, and hypergraph control plane (GAME_PLAN_:: P8).

This module is a pure control-plane layer.  It validates explicit, typed
relation records; it does **not** evaluate mathematics, execute kernels, or
persist anything.  A relation is an explicitly declared hyperedge, never an
arbitrary JSON bag.

Design rules
------------

* Every relation has a stable ``relation_id`` and an immutable integer
  ``version``.  Versions are append-only; ``next_version`` creates a new
  record and never mutates the old one.
* Membership is a tuple of typed ``RelationMember`` records
  (``leaf_id``/``version``/``role``).  No free-form member dictionaries leak
  into a constructed record.
* ``RelationSchema`` freezes the relation contract: ordering, duplicate
  policy, direction, weight domain, roles, arity, and structural constraints.
* Weights are exact integers or canonical rational/decimal strings.  Host
  floats are rejected so canonical serialization and digests stay stable.
* A ``Hypergraph`` is a bounded composition of relation records.  Traversal
  enforces cycle, depth, fan-out, member, and relation limits.
* A relation record can be used as typed input (``to_math_leaf``) or as the
  start of a bounded hypergraph traversal.  This is the P8
  "hyperedge-as-input" seam; it does not imply automatic execution.

The module deliberately imports only ``math_objects`` and the standard
library.  It is not wired into the native MTH manifest and does not bypass
linker/validity authority.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import re
from typing import Any, Iterable, Mapping, Sequence

from .math_objects import (
    MathLeaf,
    MathObjectError,
    canonical_json,
    digest_object,
)

RELATION_RECORD_SCHEMA = "nanrouter.math-relation.v1"
# Short alias used by callers/tests that mirror ``LEAF_SCHEMA`` style names.
RELATION_SCHEMA = RELATION_RECORD_SCHEMA
RELATION_SCHEMA_DEFINITION_SCHEMA = "nanrouter.math-relation-schema.v1"
HYPERGRAPH_RECORD_SCHEMA = "nanrouter.math-hypergraph.v1"
HYPERGRAPH_SCHEMA = HYPERGRAPH_RECORD_SCHEMA

RELATION_SCHEMA_SCHEMA = RELATION_SCHEMA_DEFINITION_SCHEMA
HYPERGRAPH_RELATION_SCHEMA_ID = "nanrouter.math-relation.hypergraph.v1"

MAX_HYPEREDGE_MEMBERS = 256
DEFAULT_MAX_DEPTH = 8
DEFAULT_MAX_FANOUT = 32
DEFAULT_MAX_MEMBERS = MAX_HYPEREDGE_MEMBERS
DEFAULT_MAX_RELATIONS = 1024

DUPLICATE_POLICIES = frozenset({"forbid", "allow"})
WEIGHT_DOMAINS = frozenset({
    "none", "unit", "integer", "nonnegative_integer", "positive_integer",
    "rational", "real", "exact",
})
CONSTRAINT_OPS = frozenset({
    "requires_role", "forbids_role", "role_min", "role_max",
    "no_self_reference", "unique_leaf_ids", "unique_member_refs",
    "weights_nonnegative", "weights_positive",
    "min_distinct_roles", "max_distinct_roles", "nonempty",
})

_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,180}$")
_REFERENCE_RE = re.compile(r"^(?:nml|rel):[A-Za-z0-9_.:-]{1,180}$")
_HYPERGRAPH_ID_RE = re.compile(r"^(?:hg|nml|rel):[A-Za-z0-9_.:-]{1,180}$")
_ROLE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,63}$")
_RATIONAL_RE = re.compile(
    r"^[+-]?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:/[1-9][0-9]*)?$"
)
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")

_DUPLICATE_ALIASES = {
    "forbid": "forbid", "forbidden": "forbid", "reject": "forbid",
    "unique": "forbid", "none": "forbid", "distinct": "forbid",
    "allow": "allow", "allowed": "allow", "permit": "allow",
    "duplicates": "allow",
}
_WEIGHT_DOMAIN_ALIASES = {
    "none": "none", "no_weights": "none", "absent": "none",
    "unit": "unit", "unit_weight": "unit", "unit_weights": "unit",
    "integer": "integer", "int": "integer", "exact_integer": "integer",
    "nonnegative_integer": "nonnegative_integer",
    "non_negative_integer": "nonnegative_integer",
    "unsigned_integer": "nonnegative_integer",
    "positive_integer": "positive_integer", "natural": "positive_integer",
    "rational": "rational", "rationals": "rational", "fraction": "rational",
    "real": "real", "reals": "real", "decimal": "real",
    "exact": "exact", "exact_number": "exact",
}
_CONSTRAINT_ALIASES = {
    "requires_role": "requires_role", "require_role": "requires_role",
    "role_required": "requires_role",
    "forbids_role": "forbids_role", "forbid_role": "forbids_role",
    "role_forbidden": "forbids_role",
    "role_min": "role_min", "min_role_count": "role_min",
    "role_max": "role_max", "max_role_count": "role_max",
    "no_self_reference": "no_self_reference",
    "no_self_loops": "no_self_reference",
    "unique_leaf_ids": "unique_leaf_ids",
    "unique_members": "unique_leaf_ids",
    "unique_member_refs": "unique_member_refs",
    "weights_nonnegative": "weights_nonnegative",
    "weights_non_negative": "weights_nonnegative",
    "weights_positive": "weights_positive",
    "min_distinct_roles": "min_distinct_roles",
    "max_distinct_roles": "max_distinct_roles",
    "nonempty": "nonempty",
}
_NO_ARG_OPS = frozenset({
    "no_self_reference", "unique_leaf_ids", "unique_member_refs",
    "weights_nonnegative", "weights_positive", "nonempty",
})
_ROLE_OPS = frozenset({"requires_role", "forbids_role"})
_ROLE_VALUE_OPS = frozenset({"role_min", "role_max"})
_VALUE_OPS = frozenset({"min_distinct_roles", "max_distinct_roles"})


class RelationError(ValueError):
    """Base error for relation and hypergraph control-plane failures."""

    code = "RELATION_ERROR"

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        self.code = code or type(self).code
        self.message = message or self.code
        super().__init__(self.message)


class RelationValidationError(RelationError):
    code = "INVALID_RELATION"


class RelationSchemaError(RelationValidationError):
    code = "INVALID_SCHEMA"


class RelationMemberError(RelationValidationError):
    code = "INVALID_MEMBER"


class RelationDuplicateError(RelationMemberError):
    code = "DUPLICATE_MEMBER"


class RelationCompatibilityError(RelationValidationError):
    code = "SCHEMA_INCOMPATIBLE"


class RelationLimitError(RelationError):
    code = "RELATION_LIMIT"


class RelationDepthError(RelationLimitError):
    code = "DEPTH_LIMIT"


class RelationFanoutError(RelationLimitError):
    code = "FANOUT_LIMIT"


class RelationCycleError(RelationLimitError):
    code = "CYCLE_DETECTED"

    def __init__(self, message: str = "", *, cycle: Sequence[str] = (),
                 code: str | None = None) -> None:
        self.cycle = tuple(cycle)
        super().__init__(message, code=code)


class HypergraphError(RelationValidationError):
    code = "INVALID_HYPERGRAPH"


# ---------------------------------------------------------------------------
# Small validators and canonicalization helpers
# ---------------------------------------------------------------------------


def _require_identifier(value: Any, name: str, *, error: type[RelationError],
                        code: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise error(
            f"{name} must be 1..181 characters of [A-Za-z0-9_.:-] "
            "starting with a letter",
            code=code,
        )
    return value


def _require_role(value: Any, name: str = "role", *,
                  error: type[RelationError] = RelationSchemaError,
                  code: str = "INVALID_ROLE") -> str:
    if not isinstance(value, str) or not _ROLE_RE.fullmatch(value):
        raise error(
            f"{name} must be 1..64 characters of [A-Za-z0-9_.:-] "
            "starting with a letter",
            code=code,
        )
    return value


def _require_int(value: Any, name: str, *, minimum: int = 0,
                 error: type[RelationError] = RelationSchemaError,
                 code: str = "INVALID_INTEGER") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise error(f"{name} must be an integer >= {minimum}", code=code)
    return value


def _require_bool(value: Any, name: str, *,
                  error: type[RelationError] = RelationSchemaError,
                  code: str = "INVALID_BOOLEAN") -> bool:
    if not isinstance(value, bool):
        raise error(f"{name} must be a boolean", code=code)
    return value


def _freeze_json(value: Any, name: str, *, depth: int = 0,
                 error: type[RelationError] = RelationValidationError,
                 code: str = "INVALID_PROVENANCE") -> Any:
    """Validate and deep-copy a canonical-JSON metadata value.

    Host floats are rejected: control-plane digests use exact integers, text,
    booleans, null, lists, and objects only.
    """
    if depth > 16:
        raise error(f"{name} nesting exceeds 16", code=code)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        raise error(f"{name} must not contain host floats", code=code)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 256:
                raise error(
                    f"{name} keys must be non-empty strings <= 256",
                    code=code,
                )
            result[key] = _freeze_json(
                item, f"{name}.{key}", depth=depth + 1, error=error, code=code
            )
        return result
    if isinstance(value, (list, tuple)):
        if len(value) > 4096:
            raise error(f"{name} list exceeds 4096 entries", code=code)
        return [
            _freeze_json(item, f"{name}[{index}]", depth=depth + 1,
                         error=error, code=code)
            for index, item in enumerate(value)
        ]
    raise error(f"{name} contains a non-canonical value: {type(value).__name__}",
                code=code)


def _mapping_fields(value: Any, name: str, *, allowed: frozenset[str],
                    required: frozenset[str], error: type[RelationError],
                    code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise error(f"{name} must be an object", code=code)
    keys = set(value)
    unknown = keys - allowed
    missing = required - keys
    if unknown:
        raise error(
            f"{name} has unknown keys: {', '.join(sorted(unknown))}", code=code
        )
    if missing:
        raise error(
            f"{name} is missing keys: {', '.join(sorted(missing))}", code=code
        )
    return value


def _normalize_choice(value: Any, aliases: Mapping[str, str], name: str, *,
                      error: type[RelationError], code: str) -> str:
    if not isinstance(value, str):
        raise error(f"{name} must be text", code=code)
    normalized = aliases.get(value.strip().lower())
    if normalized is None:
        raise error(
            f"unknown {name}: {value!r}; expected one of "
            f"{', '.join(sorted(set(aliases.values())))}",
            code=code,
        )
    return normalized


def _canonical_weight_key(value: Any) -> str:
    return canonical_json(value)


def _weight_sign(value: int | str) -> int:
    """Return -1/0/1 without performing arithmetic on the weight."""
    if isinstance(value, int):
        return (value > 0) - (value < 0)
    text = value.strip()
    if text.startswith("-"):
        return -1
    if text.startswith("+"):
        text = text[1:]
    numerator = text.split("/", 1)[0]
    return 1 if any(ch in "123456789" for ch in numerator) else 0


def _coerce_role_spec(value: Any) -> "RoleSpec":
    if isinstance(value, RoleSpec):
        return value
    if isinstance(value, str):
        return RoleSpec(role=value)
    if isinstance(value, Mapping):
        data = _mapping_fields(
            value, "role spec",
            allowed=frozenset({"role", "min_count", "max_count", "required"}),
            required=frozenset({"role"}),
            error=RelationSchemaError, code="INVALID_ROLE_SPEC",
        )
        return RoleSpec(
            role=data["role"],
            min_count=data.get("min_count", 0),
            max_count=data.get("max_count"),
            required=data.get("required", False),
        )
    raise RelationSchemaError(
        "role specs must be RoleSpec, text, or objects",
        code="INVALID_ROLE_SPEC",
    )


def _coerce_constraint(value: Any) -> "RelationConstraint":
    if isinstance(value, RelationConstraint):
        return value
    if isinstance(value, str):
        return RelationConstraint(op=value)
    if isinstance(value, Mapping):
        data = _mapping_fields(
            value, "constraint",
            allowed=frozenset({"op", "role", "value"}),
            required=frozenset({"op"}),
            error=RelationSchemaError, code="INVALID_CONSTRAINT",
        )
        return RelationConstraint(
            op=data["op"], role=data.get("role"), value=data.get("value")
        )
    raise RelationSchemaError(
        "constraints must be RelationConstraint, text, or objects",
        code="INVALID_CONSTRAINT",
    )


def _coerce_member(value: Any) -> "RelationMember":
    if isinstance(value, RelationMember):
        return value
    if isinstance(value, Mapping):
        data = _mapping_fields(
            value, "relation member",
            allowed=frozenset({"leaf_id", "version", "role"}),
            required=frozenset({"leaf_id"}),
            error=RelationMemberError, code="INVALID_MEMBER",
        )
        return RelationMember(
            leaf_id=data["leaf_id"],
            version=data.get("version", 1),
            role=data.get("role"),
        )
    if isinstance(value, (tuple, list)):
        if len(value) not in (2, 3):
            raise RelationMemberError(
                "member tuples must be (leaf_id, version[, role])",
                code="INVALID_MEMBER",
            )
        return RelationMember(
            leaf_id=value[0], version=value[1],
            role=value[2] if len(value) == 3 else None,
        )
    raise RelationMemberError(
        "members must be RelationMember, objects, or tuples",
        code="INVALID_MEMBER",
    )


def _coerce_schema(value: Any) -> "RelationSchema":
    if isinstance(value, RelationSchema):
        return value
    if isinstance(value, Mapping):
        return RelationSchema.from_dict(value)
    raise RelationSchemaError(
        "schema must be a RelationSchema or schema object",
        code="INVALID_SCHEMA",
    )


def _normalize_weights(value: Any, count: int, domain: str) -> tuple[int | str, ...]:
    if value is None:
        raw: tuple[Any, ...] = ()
    elif isinstance(value, (tuple, list)):
        raw = tuple(value)
    else:
        raise RelationMemberError(
            "weights must be a list of exact weights", code="INVALID_WEIGHT"
        )
    if domain == "none":
        if raw:
            raise RelationMemberError(
                "weight_domain='none' forbids member weights",
                code="INVALID_WEIGHT",
            )
        return ()
    if not raw:
        # Non-unit domains still use an explicit, identity-stable unit vector.
        raw = (1,) * count
    if len(raw) != count:
        raise RelationMemberError(
            f"weights length {len(raw)} does not match {count} members",
            code="INVALID_WEIGHT",
        )
    result: list[int | str] = []
    for index, item in enumerate(raw):
        if isinstance(item, bool):
            raise RelationMemberError(
                f"weight[{index}] must not be boolean", code="INVALID_WEIGHT"
            )
        if isinstance(item, int):
            weight: int | str = item
        elif isinstance(item, str) and _RATIONAL_RE.fullmatch(item):
            weight = item
        else:
            raise RelationMemberError(
                f"weight[{index}] must be an integer or canonical "
                "rational/decimal text (host floats are forbidden)",
                code="INVALID_WEIGHT",
            )
        if domain == "unit" and weight != 1:
            raise RelationMemberError(
                "weight_domain='unit' requires every weight to be 1",
                code="INVALID_WEIGHT",
            )
        if domain in {"nonnegative_integer"} and (
            not isinstance(weight, int) or weight < 0
        ):
            raise RelationMemberError(
                f"weight[{index}] violates nonnegative_integer domain",
                code="INVALID_WEIGHT",
            )
        if domain in {"positive_integer"} and (
            not isinstance(weight, int) or weight < 1
        ):
            raise RelationMemberError(
                f"weight[{index}] violates positive_integer domain",
                code="INVALID_WEIGHT",
            )
        if domain in {"integer", "nonnegative_integer", "positive_integer"} and (
            not isinstance(weight, int)
        ):
            raise RelationMemberError(
                f"weight[{index}] must be an integer for domain {domain!r}",
                code="INVALID_WEIGHT",
            )
        result.append(weight)
    return tuple(result)


def _default_hypergraph_schema() -> "RelationSchema":
    return RelationSchema(
        schema_id=HYPERGRAPH_RELATION_SCHEMA_ID,
        version=1,
        ordered=False,
        duplicate_policy="forbid",
        directed=False,
        weight_domain="none",
        roles=(RoleSpec(role="member", min_count=0),),
        min_arity=0,
        max_arity=MAX_HYPEREDGE_MEMBERS,
        allow_unroled=False,
        provenance={"definition": "bounded hypergraph relation membership"},
    )



# ---------------------------------------------------------------------------
# Schema records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoleSpec:
    """Cardinality contract for one optional member role."""

    role: str
    min_count: int = 0
    max_count: int | None = None
    required: bool = False

    def __post_init__(self) -> None:
        _require_role(self.role)
        _require_int(self.min_count, "min_count", minimum=0)
        if self.max_count is not None:
            _require_int(self.max_count, "max_count", minimum=0)
        if not isinstance(self.required, bool):
            raise RelationSchemaError(
                "required must be a boolean", code="INVALID_ROLE_SPEC"
            )
        if self.max_count is not None and self.max_count < self.min_count:
            raise RelationSchemaError(
                "max_count must be >= min_count", code="INVALID_ROLE_SPEC"
            )
        if self.required and self.min_count == 0:
            object.__setattr__(self, "min_count", 1)
        if self.min_count > 0 and not self.required:
            object.__setattr__(self, "required", True)

    @property
    def maximum(self) -> int | None:
        return self.max_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "min_count": self.min_count,
            "max_count": self.max_count,
            "required": self.required,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)


@dataclass(frozen=True)
class RelationConstraint:
    """One finite structural invariant; never an arbitrary expression."""

    op: str
    role: str | None = None
    value: int | None = None

    def __post_init__(self) -> None:
        op = _normalize_choice(
            self.op, _CONSTRAINT_ALIASES, "constraint op",
            error=RelationSchemaError, code="INVALID_CONSTRAINT",
        )
        object.__setattr__(self, "op", op)
        if self.role is not None:
            _require_role(self.role, "constraint role",
                          error=RelationSchemaError,
                          code="INVALID_CONSTRAINT")
        if self.value is not None:
            _require_int(self.value, "constraint value", minimum=0)
        if op in _NO_ARG_OPS:
            if self.role is not None or self.value is not None:
                raise RelationSchemaError(
                    f"constraint {op!r} takes no role or value",
                    code="INVALID_CONSTRAINT",
                )
        elif op in _ROLE_OPS:
            if self.role is None or self.value is not None:
                raise RelationSchemaError(
                    f"constraint {op!r} requires role and no value",
                    code="INVALID_CONSTRAINT",
                )
        elif op in _ROLE_VALUE_OPS:
            if self.role is None or self.value is None:
                raise RelationSchemaError(
                    f"constraint {op!r} requires role and value",
                    code="INVALID_CONSTRAINT",
                )
        elif op in _VALUE_OPS:
            if self.role is not None or self.value is None:
                raise RelationSchemaError(
                    f"constraint {op!r} requires value and no role",
                    code="INVALID_CONSTRAINT",
                )
        else:  # Defensive: op was normalized from the finite set.
            raise RelationSchemaError(
                f"unknown constraint op: {op!r}", code="INVALID_CONSTRAINT"
            )

    def to_dict(self) -> dict[str, Any]:
        return {"op": self.op, "role": self.role, "value": self.value}

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)


@dataclass(frozen=True)
class SchemaCompatibility:
    """Deterministic compatibility result with named mismatch reasons."""

    compatible: bool
    reasons: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.compatible

    def to_dict(self) -> dict[str, Any]:
        return {"compatible": self.compatible, "reasons": list(self.reasons)}


@dataclass(frozen=True)
class RelationSchema:
    """Immutable relation contract.

    ``ordered`` and ``directed`` are independent flags.  If either ordering or
    direction is absent, member order is canonicalized before serialization
    and hashing.  ``duplicate_policy`` is ``forbid`` or ``allow`` and applies
    to ``(leaf_id, version)`` references.
    """

    schema_id: str
    version: int = 1
    ordered: bool = True
    duplicate_policy: str = "forbid"
    directed: bool = True
    weight_domain: str = "none"
    roles: tuple[RoleSpec | str | Mapping[str, Any], ...] = ()
    min_arity: int = 1
    max_arity: int = MAX_HYPEREDGE_MEMBERS
    constraints: tuple[
        RelationConstraint | str | Mapping[str, Any], ...
    ] = ()
    allow_unroled: bool = False
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_identifier(self.schema_id, "schema_id",
                            error=RelationSchemaError, code="INVALID_SCHEMA")
        _require_int(self.version, "version", minimum=1)
        _require_bool(self.ordered, "ordered")
        _require_bool(self.directed, "directed")
        _require_bool(self.allow_unroled, "allow_unroled")
        _require_int(self.min_arity, "min_arity", minimum=0)
        _require_int(self.max_arity, "max_arity", minimum=0)
        if self.max_arity > MAX_HYPEREDGE_MEMBERS:
            raise RelationSchemaError(
                f"max_arity must be <= {MAX_HYPEREDGE_MEMBERS}",
                code="ARITY_LIMIT",
            )
        if self.max_arity < self.min_arity:
            raise RelationSchemaError(
                "max_arity must be >= min_arity", code="INVALID_ARITY"
            )
        object.__setattr__(
            self, "duplicate_policy",
            _normalize_choice(
                self.duplicate_policy, _DUPLICATE_ALIASES, "duplicate policy",
                error=RelationSchemaError, code="INVALID_DUPLICATE_POLICY",
            ),
        )
        object.__setattr__(
            self, "weight_domain",
            _normalize_choice(
                self.weight_domain, _WEIGHT_DOMAIN_ALIASES, "weight domain",
                error=RelationSchemaError, code="INVALID_WEIGHT_DOMAIN",
            ),
        )
        roles = tuple(_coerce_role_spec(item) for item in self.roles)
        names = [spec.role for spec in roles]
        if len(set(names)) != len(names):
            raise RelationSchemaError(
                "role names must be unique", code="DUPLICATE_ROLE"
            )
        if sum(spec.min_count for spec in roles) > self.max_arity:
            raise RelationSchemaError(
                "required role cardinalities exceed max_arity",
                code="INVALID_ARITY",
            )
        for spec in roles:
            if spec.max_count is not None and spec.max_count > self.max_arity:
                raise RelationSchemaError(
                    f"role {spec.role!r} max_count exceeds max_arity",
                    code="INVALID_ARITY",
                )
        constraints = tuple(_coerce_constraint(item) for item in self.constraints)
        if len(set(constraints)) != len(constraints):
            raise RelationSchemaError(
                "constraints must be unique", code="DUPLICATE_CONSTRAINT"
            )
        declared_roles = set(names)
        for constraint in constraints:
            if constraint.role is not None and constraint.role not in declared_roles:
                raise RelationSchemaError(
                    f"constraint references undeclared role "
                    f"{constraint.role!r}",
                    code="INVALID_CONSTRAINT",
                )
            if constraint.op in {"weights_nonnegative", "weights_positive"} \
                    and self.weight_domain == "none":
                raise RelationSchemaError(
                    f"constraint {constraint.op!r} requires a weight domain",
                    code="INVALID_CONSTRAINT",
                )
        object.__setattr__(self, "roles", roles)
        object.__setattr__(self, "constraints", constraints)
        object.__setattr__(
            self, "provenance",
            _freeze_json(self.provenance, "schema provenance",
                         error=RelationSchemaError),
        )

    # -- descriptive properties -------------------------------------------

    @property
    def ordering(self) -> str:
        return "ordered" if self.ordered else "unordered"

    @property
    def direction(self) -> str:
        return "directed" if self.directed else "undirected"

    @property
    def role_names(self) -> tuple[str, ...]:
        return tuple(spec.role for spec in self.roles)

    @property
    def arity(self) -> tuple[int, int]:
        return (self.min_arity, self.max_arity)

    def role(self, name: str) -> RoleSpec | None:
        for spec in self.roles:
            if spec.role == name:
                return spec
        return None

    def arity_compatible(self, count: int) -> bool:
        return self.min_arity <= count <= self.max_arity

    def accepts_role(self, role: str | None) -> bool:
        if not self.roles:
            return role is None
        if role is None:
            return self.allow_unroled
        return self.role(role) is not None

    # -- compatibility -----------------------------------------------------

    def compatibility(self, other: Any, *,
                      require_same_version: bool = True) -> SchemaCompatibility:
        """Symmetric structural compatibility with another schema."""
        if not isinstance(other, RelationSchema):
            return SchemaCompatibility(False, ("not-a-schema",))
        reasons: list[str] = []
        if self.schema_id != other.schema_id:
            reasons.append("schema_id")
        if require_same_version and self.version != other.version:
            reasons.append("version")
        for name in (
            "ordered", "directed", "duplicate_policy", "weight_domain",
            "allow_unroled",
        ):
            if getattr(self, name) != getattr(other, name):
                reasons.append(name)
        if max(self.min_arity, other.min_arity) > min(
            self.max_arity, other.max_arity
        ):
            reasons.append("arity")
        self_roles = {spec.role: spec for spec in self.roles}
        other_roles = {spec.role: spec for spec in other.roles}
        if set(self_roles) != set(other_roles):
            reasons.append("roles")
        else:
            for name in sorted(self_roles):
                left = self_roles[name]
                right = other_roles[name]
                left_max = left.max_count if left.max_count is not None else self.max_arity
                right_max = right.max_count if right.max_count is not None else other.max_arity
                if max(left.min_count, right.min_count) > min(left_max, right_max):
                    reasons.append(f"role:{name}")
        if set(self.constraints) != set(other.constraints):
            reasons.append("constraints")
        return SchemaCompatibility(not reasons, tuple(reasons))

    def is_compatible_with(self, other: Any, *,
                           require_same_version: bool = True) -> bool:
        return bool(self.compatibility(
            other, require_same_version=require_same_version
        ))

    def compatible_with(self, other: Any, *,
                        require_same_version: bool = True) -> bool:
        return self.is_compatible_with(
            other, require_same_version=require_same_version
        )

    def accepts(self, other: Any, *,
                require_same_version: bool = True) -> bool:
        """Directional check: can ``self`` consume records from ``other``?"""
        if not isinstance(other, RelationSchema):
            return False
        if self.schema_id != other.schema_id:
            return False
        if require_same_version and self.version != other.version:
            return False
        for name in (
            "ordered", "directed", "duplicate_policy", "weight_domain",
        ):
            if getattr(self, name) != getattr(other, name):
                return False
        if self.min_arity > other.min_arity or self.max_arity < other.max_arity:
            return False
        self_roles = {spec.role: spec for spec in self.roles}
        other_roles = {spec.role: spec for spec in other.roles}
        if not set(other_roles).issubset(self_roles):
            return False
        for name, provider in other_roles.items():
            consumer = self_roles[name]
            provider_max = (
                provider.max_count if provider.max_count is not None
                else other.max_arity
            )
            consumer_max = (
                consumer.max_count if consumer.max_count is not None
                else self.max_arity
            )
            if consumer.min_count > provider.min_count:
                return False
            if consumer_max < provider_max:
                return False
        consumer_unroled = self.allow_unroled or not self.roles
        if other.allow_unroled and not consumer_unroled:
            return False
        if not set(self.constraints).issubset(other.constraints):
            return False
        return True

    def assert_compatible(self, other: Any, *,
                          require_same_version: bool = True) -> None:
        result = self.compatibility(
            other, require_same_version=require_same_version
        )
        if not result.compatible:
            raise RelationCompatibilityError(
                f"incompatible relation schemas: {', '.join(result.reasons)}",
                code="SCHEMA_INCOMPATIBLE",
            )

    # -- serialization -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RELATION_SCHEMA_DEFINITION_SCHEMA,
            "schema_id": self.schema_id,
            "version": self.version,
            "ordered": self.ordered,
            "ordering": self.ordering,
            "duplicate_policy": self.duplicate_policy,
            "directed": self.directed,
            "direction": self.direction,
            "weight_domain": self.weight_domain,
            "roles": [spec.to_dict() for spec in self.roles],
            "min_arity": self.min_arity,
            "max_arity": self.max_arity,
            "constraints": [item.to_dict() for item in self.constraints],
            "allow_unroled": self.allow_unroled,
            "provenance": _freeze_json(
                self.provenance, "schema provenance",
                error=RelationSchemaError,
            ),
        }

    def digest(self) -> str:
        return digest_object(self.to_dict())

    def next_version(self, *, version: int | None = None,
                     **changes: Any) -> "RelationSchema":
        if version is None:
            version = self.version + 1
        values = {
            "schema_id": self.schema_id,
            "version": version,
            "ordered": self.ordered,
            "duplicate_policy": self.duplicate_policy,
            "directed": self.directed,
            "weight_domain": self.weight_domain,
            "roles": self.roles,
            "min_arity": self.min_arity,
            "max_arity": self.max_arity,
            "constraints": self.constraints,
            "allow_unroled": self.allow_unroled,
            "provenance": dict(self.provenance),
        }
        values.update(changes)
        return RelationSchema(**values)

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> "RelationSchema":
        allowed = frozenset({
            "schema", "schema_id", "version", "ordered", "ordering",
            "duplicate_policy", "directed", "direction", "weight_domain",
            "roles", "min_arity", "max_arity", "constraints",
            "allow_unroled", "provenance",
        })
        data = _mapping_fields(
            document, "relation schema", allowed=allowed,
            required=frozenset({"schema_id"}),
            error=RelationSchemaError, code="INVALID_SCHEMA",
        )
        marker = data.get("schema")
        if marker is not None and marker != RELATION_SCHEMA_DEFINITION_SCHEMA:
            raise RelationSchemaError(
                f"unexpected schema marker: {marker!r}",
                code="INVALID_SCHEMA",
            )
        ordered = data.get("ordered")
        if ordered is None:
            ordering = data.get("ordering", "ordered")
            if ordering not in {"ordered", "unordered"}:
                raise RelationSchemaError(
                    f"unknown ordering: {ordering!r}", code="INVALID_SCHEMA"
                )
            ordered = ordering == "ordered"
        directed = data.get("directed")
        if directed is None:
            direction = data.get("direction", "directed")
            if direction not in {"directed", "undirected"}:
                raise RelationSchemaError(
                    f"unknown direction: {direction!r}", code="INVALID_SCHEMA"
                )
            directed = direction == "directed"
        return cls(
            schema_id=data["schema_id"],
            version=data.get("version", 1),
            ordered=ordered,
            duplicate_policy=data.get("duplicate_policy", "forbid"),
            directed=directed,
            weight_domain=data.get("weight_domain", "none"),
            roles=tuple(data.get("roles", ())),
            min_arity=data.get("min_arity", 1),
            max_arity=data.get("max_arity", MAX_HYPEREDGE_MEMBERS),
            constraints=tuple(data.get("constraints", ())),
            allow_unroled=data.get("allow_unroled", False),
            provenance=dict(data.get("provenance", {})),
        )


# ---------------------------------------------------------------------------
# Relation records
# ---------------------------------------------------------------------------


HYPERGRAPH_RELATION_SCHEMA = _default_hypergraph_schema()


@dataclass(frozen=True)
class RelationMember:
    """Typed member reference: a leaf/version plus an optional role."""

    leaf_id: str
    version: int = 1
    role: str | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.leaf_id, "leaf_id",
                            error=RelationMemberError, code="INVALID_MEMBER")
        _require_int(self.version, "member version", minimum=1,
                     error=RelationMemberError, code="INVALID_MEMBER")
        if self.role is not None:
            _require_role(self.role, "member role",
                          error=RelationMemberError, code="INVALID_ROLE")

    def to_dict(self) -> dict[str, Any]:
        return {
            "leaf_id": self.leaf_id,
            "version": self.version,
            "role": self.role,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> "RelationMember":
        return _coerce_member(document)


def _validate_role_membership(schema: RelationSchema,
                              members: Sequence[RelationMember]) -> None:
    specs = {spec.role: spec for spec in schema.roles}
    counts: Counter[str] = Counter()
    for member in members:
        if member.role is None:
            if specs and not schema.allow_unroled:
                raise RelationMemberError(
                    "schema requires an explicit role for every member",
                    code="MISSING_ROLE",
                )
            continue
        if member.role not in specs:
            raise RelationMemberError(
                f"role {member.role!r} is not declared by the schema",
                code="INVALID_ROLE",
            )
        counts[member.role] += 1
    for spec in schema.roles:
        count = counts.get(spec.role, 0)
        if count < spec.min_count:
            raise RelationMemberError(
                f"role {spec.role!r} requires at least {spec.min_count} "
                f"members, found {count}",
                code="ROLE_MIN_VIOLATION",
            )
        if spec.max_count is not None and count > spec.max_count:
            raise RelationMemberError(
                f"role {spec.role!r} allows at most {spec.max_count} "
                f"members, found {count}",
                code="ROLE_MAX_VIOLATION",
            )


def _apply_constraints(relation_id: str, schema: RelationSchema,
                       members: Sequence[RelationMember],
                       weights: Sequence[int | str]) -> None:
    role_counts: Counter[str] = Counter(
        member.role for member in members if member.role is not None
    )
    leaf_ids = [member.leaf_id for member in members]
    refs = [(member.leaf_id, member.version) for member in members]
    for constraint in schema.constraints:
        op = constraint.op
        role = constraint.role
        value = constraint.value
        satisfied = True
        message = ""
        if op == "requires_role":
            count = role_counts.get(role or "", 0)
            satisfied = count >= 1
            message = f"requires role {role!r} (found {count})"
        elif op == "forbids_role":
            count = role_counts.get(role or "", 0)
            satisfied = count == 0
            message = f"forbids role {role!r} (found {count})"
        elif op == "role_min":
            count = role_counts.get(role or "", 0)
            satisfied = count >= int(value or 0)
            message = f"role {role!r} needs >= {value} (found {count})"
        elif op == "role_max":
            count = role_counts.get(role or "", 0)
            satisfied = count <= int(value or 0)
            message = f"role {role!r} allows <= {value} (found {count})"
        elif op == "no_self_reference":
            satisfied = relation_id not in leaf_ids
            message = f"relation {relation_id!r} must not reference itself"
        elif op == "unique_leaf_ids":
            satisfied = len(set(leaf_ids)) == len(leaf_ids)
            message = "leaf ids must be unique"
        elif op == "unique_member_refs":
            satisfied = len(set(refs)) == len(refs)
            message = "member (leaf_id, version) references must be unique"
        elif op == "weights_nonnegative":
            satisfied = all(_weight_sign(weight) >= 0 for weight in weights)
            message = "weights must be nonnegative"
        elif op == "weights_positive":
            satisfied = all(_weight_sign(weight) > 0 for weight in weights)
            message = "weights must be positive"
        elif op == "min_distinct_roles":
            satisfied = len(role_counts) >= int(value or 0)
            message = f"needs >= {value} distinct roles"
        elif op == "max_distinct_roles":
            satisfied = len(role_counts) <= int(value or 0)
            message = f"allows <= {value} distinct roles"
        elif op == "nonempty":
            satisfied = bool(members)
            message = "members must not be empty"
        if not satisfied:
            raise RelationMemberError(
                f"constraint {op!r} violated: {message}",
                code="CONSTRAINT_VIOLATION",
            )


@dataclass(frozen=True)
class RelationRecord:
    """Immutable, schema-validated relation/hyperedge record."""

    relation_id: str
    schema: RelationSchema | Mapping[str, Any]
    version: int = 1
    members: tuple[
        RelationMember | Mapping[str, Any] | tuple[Any, ...], ...
    ] = ()
    weights: tuple[int | str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_identifier(self.relation_id, "relation_id",
                            error=RelationMemberError,
                            code="INVALID_RELATION_ID")
        _require_int(self.version, "version", minimum=1,
                     error=RelationMemberError, code="INVALID_VERSION")
        schema = _coerce_schema(self.schema)
        raw_members: Any = self.members
        if raw_members is None:
            raw_members = ()
        elif isinstance(raw_members, (RelationMember, Mapping)):
            raw_members = (raw_members,)
        members = tuple(_coerce_member(item) for item in raw_members)
        if not schema.arity_compatible(len(members)):
            raise RelationMemberError(
                f"relation arity {len(members)} is outside schema bounds "
                f"[{schema.min_arity}, {schema.max_arity}]",
                code="ARITY_VIOLATION",
            )
        refs = [(member.leaf_id, member.version) for member in members]
        if schema.duplicate_policy == "forbid" and len(set(refs)) != len(refs):
            raise RelationDuplicateError(
                "duplicate (leaf_id, version) member is forbidden by schema",
                code="DUPLICATE_MEMBER",
            )
        weights = _normalize_weights(
            self.weights, len(members), schema.weight_domain
        )
        # An unordered or undirected relation canonicalizes its member order
        # (and the paired weights) so identity and digests are order-stable.
        if not schema.ordered or not schema.directed:
            order = sorted(
                range(len(members)),
                key=lambda index: (
                    members[index].leaf_id,
                    members[index].version,
                    members[index].role or "",
                    _canonical_weight_key(weights[index]) if weights else "",
                ),
            )
            members = tuple(members[index] for index in order)
            if weights:
                weights = tuple(weights[index] for index in order)
        _validate_role_membership(schema, members)
        _apply_constraints(self.relation_id, schema, members, weights)
        object.__setattr__(self, "schema", schema)
        object.__setattr__(self, "members", members)
        object.__setattr__(self, "weights", weights)
        object.__setattr__(
            self, "provenance",
            _freeze_json(self.provenance, "relation provenance",
                         error=RelationMemberError),
        )

    # -- descriptive properties -------------------------------------------

    @property
    def schema_id(self) -> str:
        return self.schema.schema_id

    @property
    def schema_version(self) -> int:
        return self.schema.version

    @property
    def ordering(self) -> str:
        return self.schema.ordering

    @property
    def direction(self) -> str:
        return self.schema.direction

    @property
    def duplicate_policy(self) -> str:
        return self.schema.duplicate_policy

    @property
    def weight_domain(self) -> str:
        return self.schema.weight_domain

    @property
    def arity(self) -> int:
        return len(self.members)

    @property
    def leaf_ids(self) -> tuple[str, ...]:
        return tuple(member.leaf_id for member in self.members)

    @property
    def roles(self) -> tuple[str | None, ...]:
        return tuple(member.role for member in self.members)

    @property
    def member_refs(self) -> tuple[tuple[str, int, str | None], ...]:
        return tuple(
            (member.leaf_id, member.version, member.role)
            for member in self.members
        )

    def members_for_role(self, role: str) -> tuple[RelationMember, ...]:
        return tuple(member for member in self.members if member.role == role)

    def members_matching(self, leaf_id: str | None = None,
                         version: int | None = None,
                         role: Any = ...) -> tuple[RelationMember, ...]:
        result = []
        for member in self.members:
            if leaf_id is not None and member.leaf_id != leaf_id:
                continue
            if version is not None and member.version != version:
                continue
            if role is not ... and member.role != role:
                continue
            result.append(member)
        return tuple(result)

    def member(self, leaf_id: str, version: int | None = None,
               role: Any = ...) -> RelationMember:
        matches = self.members_matching(leaf_id, version, role)
        if len(matches) != 1:
            raise RelationMemberError(
                f"expected exactly one member for {leaf_id!r}, "
                f"found {len(matches)}",
                code="AMBIGUOUS_MEMBER",
            )
        return matches[0]

    def is_member(self, leaf_id: str, version: int | None = None) -> bool:
        return any(
            member.leaf_id == leaf_id
            and (version is None or member.version == version)
            for member in self.members
        )

    def contains(self, leaf_id: str, version: int | None = None) -> bool:
        return self.is_member(leaf_id, version)

    def __contains__(self, value: Any) -> bool:
        if isinstance(value, RelationMember):
            return value in self.members
        if isinstance(value, tuple) and len(value) in (2, 3):
            return self.is_member(value[0], value[1])
        if isinstance(value, Mapping):
            return self.is_member(
                value.get("leaf_id"), value.get("version")
            )
        if isinstance(value, str):
            return self.is_member(value)
        return False

    def incident_members(self, leaf_id: str) -> tuple[RelationMember, ...]:
        return self.members_matching(leaf_id=leaf_id)

    def incidence_map(self) -> dict[str, tuple[RelationMember, ...]]:
        result: dict[str, list[RelationMember]] = {}
        for member in self.members:
            result.setdefault(member.leaf_id, []).append(member)
        return {key: tuple(value) for key, value in result.items()}

    def incidence(self) -> dict[str, tuple[RelationMember, ...]]:
        return self.incidence_map()

    def degree(self, leaf_id: str | None = None) -> int:
        if leaf_id is None:
            return len(self.members)
        return sum(1 for member in self.members if member.leaf_id == leaf_id)

    # -- identity and versioning ------------------------------------------

    def content_payload(self) -> dict[str, Any]:
        return {
            "schema_digest": self.schema.digest(),
            "members": [member.to_dict() for member in self.members],
            "weights": list(self.weights),
        }

    def content_digest(self) -> str:
        return digest_object(self.content_payload())

    def identity_digest(self) -> str:
        return self.content_digest()

    def digest(self) -> str:
        return digest_object(self.to_dict())

    def same_content(self, other: Any) -> bool:
        return (
            isinstance(other, RelationRecord)
            and self.content_digest() == other.content_digest()
        )

    def is_same_relation(self, other: Any, *,
                         include_provenance: bool = True) -> bool:
        if not isinstance(other, RelationRecord):
            return False
        if self.relation_id != other.relation_id or self.version != other.version:
            return False
        if include_provenance:
            return self.digest() == other.digest()
        return self.content_digest() == other.content_digest()

    def equivalent(self, other: Any, *,
                   include_provenance: bool = True) -> bool:
        return self.is_same_relation(
            other, include_provenance=include_provenance
        )

    def schema_compatible_with(self, other: Any) -> bool:
        return (
            isinstance(other, RelationRecord)
            and self.schema.is_compatible_with(other.schema)
        )

    def next_version(self, *, members: Any = None, weights: Any = None,
                     schema: Any = None, provenance: Any = None,
                     version: int | None = None) -> "RelationRecord":
        if version is None:
            version = self.version + 1
        new_schema = self.schema if schema is None else _coerce_schema(schema)
        if members is None:
            new_members = self.members
        elif isinstance(members, (RelationMember, Mapping)):
            new_members = (members,)
        else:
            new_members = tuple(members)
        if weights is None:
            if new_schema.weight_domain == "none":
                new_weights: Any = ()
            elif members is None:
                new_weights = self.weights
            else:
                new_weights = ()
        else:
            new_weights = weights
        return RelationRecord(
            relation_id=self.relation_id,
            schema=new_schema,
            version=version,
            members=new_members,
            weights=new_weights,
            provenance=(
                dict(self.provenance) if provenance is None else provenance
            ),
        )

    # -- serialization -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RELATION_RECORD_SCHEMA,
            "relation_id": self.relation_id,
            "version": self.version,
            "schema_id": self.schema.schema_id,
            "schema_version": self.schema.version,
            "relation_schema": self.schema.to_dict(),
            "ordered": self.schema.ordered,
            "ordering": self.schema.ordering,
            "duplicate_policy": self.schema.duplicate_policy,
            "directed": self.schema.directed,
            "direction": self.schema.direction,
            "weight_domain": self.schema.weight_domain,
            "members": [member.to_dict() for member in self.members],
            "weights": list(self.weights),
            "provenance": _freeze_json(
                self.provenance, "relation provenance",
                error=RelationMemberError,
            ),
        }

    def to_math_leaf(self, *, leaf_id: str | None = None) -> MathLeaf:
        """Typed hyperedge/relation input for the linker/validity layers."""
        selected = self.relation_id if leaf_id is None else leaf_id
        if not isinstance(selected, str) or not selected.startswith("nml:"):
            raise RelationMemberError(
                "to_math_leaf requires an nml: leaf id (pass leaf_id=...)",
                code="INVALID_LEAF_ID",
            )
        try:
            return MathLeaf(
                leaf_id=selected,
                kind="relation",
                version=self.version,
                type={
                    "relation_id": self.relation_id,
                    "relation_schema": self.schema.schema_id,
                    "relation_schema_version": self.schema.version,
                    "ordered": self.schema.ordered,
                    "directed": self.schema.directed,
                    "duplicate_policy": self.schema.duplicate_policy,
                    "weight_domain": self.schema.weight_domain,
                    "arity": self.arity,
                },
                content={
                    "digest": self.digest(),
                    "content_digest": self.content_digest(),
                    "schema_digest": self.schema.digest(),
                    "member_count": len(self.members),
                },
                provenance=dict(self.provenance),
                metadata={"relation_id": self.relation_id},
            )
        except MathObjectError as exc:
            raise RelationMemberError(
                f"relation cannot be represented as a math leaf: {exc}",
                code="INVALID_LEAF_ID",
            ) from exc

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __len__(self) -> int:
        return len(self.members)

    def __iter__(self):
        return iter(self.members)

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> "RelationRecord":
        allowed = frozenset({
            "schema", "relation_id", "version", "schema_id",
            "schema_version", "relation_schema", "ordered", "ordering",
            "duplicate_policy", "directed", "direction", "weight_domain",
            "members", "weights", "provenance",
        })
        data = _mapping_fields(
            document, "relation record", allowed=allowed,
            required=frozenset({"relation_id"}),
            error=RelationMemberError, code="INVALID_RELATION",
        )
        marker = data.get("schema")
        schema_document = data.get("relation_schema")
        if schema_document is None and isinstance(marker, Mapping):
            schema_document = marker
            marker = None
        if marker is not None and marker != RELATION_RECORD_SCHEMA:
            raise RelationMemberError(
                f"unexpected schema marker: {marker!r}",
                code="INVALID_RELATION",
            )
        if schema_document is None:
            raise RelationMemberError(
                "relation record requires relation_schema",
                code="INVALID_RELATION",
            )
        schema = (
            schema_document if isinstance(schema_document, RelationSchema)
            else RelationSchema.from_dict(schema_document)
        )
        if "schema_id" in data and data["schema_id"] != schema.schema_id:
            raise RelationMemberError(
                "schema_id does not match relation_schema",
                code="INVALID_RELATION",
            )
        if "schema_version" in data and data["schema_version"] != schema.version:
            raise RelationMemberError(
                "schema_version does not match relation_schema",
                code="INVALID_RELATION",
            )
        return cls(
            relation_id=data["relation_id"],
            schema=schema,
            version=data.get("version", 1),
            members=tuple(data.get("members", ())),
            weights=tuple(data.get("weights", ())),
            provenance=dict(data.get("provenance", {})),
        )


def relation_id_for(schema: RelationSchema | Mapping[str, Any],
                    members: Iterable[Any],
                    weights: Iterable[int | str] | None = None, *,
                    prefix: str = "rel:") -> str:
    """Content-addressed relation id helper (not a version/authority)."""
    if not isinstance(prefix, str) or not re.fullmatch(
        r"[A-Za-z][A-Za-z0-9_.:-]{0,31}", prefix
    ):
        raise RelationMemberError(
            "prefix must be 1..32 safe identifier characters",
            code="INVALID_RELATION_ID",
        )
    placeholder = prefix + ("0" * 64)
    record = RelationRecord(
        relation_id=placeholder,
        schema=_coerce_schema(schema),
        members=tuple(members),
        weights=() if weights is None else tuple(weights),
    )
    return prefix + record.content_digest()


def schemas_compatible(left: Any, right: Any, *,
                       require_same_version: bool = True) -> bool:
    if not isinstance(left, RelationSchema):
        return False
    return left.is_compatible_with(
        right, require_same_version=require_same_version
    )


# ---------------------------------------------------------------------------
# Bounded hypergraph composition
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RelationLimits:
    """Hard bounds for construction and bounded traversal."""

    max_depth: int = DEFAULT_MAX_DEPTH
    max_fanout: int = DEFAULT_MAX_FANOUT
    max_members: int = DEFAULT_MAX_MEMBERS
    max_relations: int = DEFAULT_MAX_RELATIONS

    def __post_init__(self) -> None:
        _require_int(self.max_depth, "max_depth", minimum=0,
                     error=RelationLimitError, code="INVALID_LIMITS")
        _require_int(self.max_fanout, "max_fanout", minimum=0,
                     error=RelationLimitError, code="INVALID_LIMITS")
        _require_int(self.max_members, "max_members", minimum=0,
                     error=RelationLimitError, code="INVALID_LIMITS")
        _require_int(self.max_relations, "max_relations", minimum=0,
                     error=RelationLimitError, code="INVALID_LIMITS")

    def to_dict(self) -> dict[str, int]:
        return {
            "max_depth": self.max_depth,
            "max_fanout": self.max_fanout,
            "max_members": self.max_members,
            "max_relations": self.max_relations,
        }

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> "RelationLimits":
        allowed = frozenset({
            "max_depth", "max_fanout", "max_members", "max_relations",
        })
        data = _mapping_fields(
            document, "relation limits", allowed=allowed,
            required=frozenset(),
            error=RelationLimitError, code="INVALID_LIMITS",
        )
        return cls(
            max_depth=data.get("max_depth", DEFAULT_MAX_DEPTH),
            max_fanout=data.get("max_fanout", DEFAULT_MAX_FANOUT),
            max_members=data.get("max_members", DEFAULT_MAX_MEMBERS),
            max_relations=data.get("max_relations", DEFAULT_MAX_RELATIONS),
        )


def _coerce_limits(value: Any) -> RelationLimits:
    if value is None:
        return RelationLimits()
    if isinstance(value, RelationLimits):
        return value
    if isinstance(value, Mapping):
        return RelationLimits.from_dict(value)
    raise RelationLimitError(
        "limits must be RelationLimits or an object",
        code="INVALID_LIMITS",
    )


@dataclass(frozen=True)
class Hypergraph:
    """Immutable, bounded composition of relation records.

    The hypergraph itself is also a typed relation leaf: its members are the
    contained ``(relation_id, version)`` references under role ``member``.
    This makes ``hyperedge -> hypergraph`` a first-class, digest-stable
    operation without introducing a universal container.
    """

    hypergraph_id: str
    version: int = 1
    relations: tuple[RelationRecord | Mapping[str, Any], ...] = ()
    schema: RelationSchema | Mapping[str, Any] | None = None
    limits: RelationLimits | Mapping[str, Any] | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_identifier(self.hypergraph_id, "hypergraph_id",
                            error=HypergraphError,
                            code="INVALID_HYPERGRAPH")
        _require_int(self.version, "version", minimum=1,
                     error=HypergraphError, code="INVALID_VERSION")
        schema = (
            _default_hypergraph_schema() if self.schema is None
            else _coerce_schema(self.schema)
        )
        limits = (
            RelationLimits() if self.limits is None
            else _coerce_limits(self.limits)
        )
        raw_relations: Any = self.relations
        if raw_relations is None:
            raw_relations = ()
        elif isinstance(raw_relations, (RelationRecord, Mapping)):
            raw_relations = (raw_relations,)
        relations: list[RelationRecord] = []
        seen: set[tuple[str, int]] = set()
        for item in raw_relations:
            if isinstance(item, RelationRecord):
                record = item
            elif isinstance(item, Mapping):
                record = RelationRecord.from_dict(item)
            else:
                raise HypergraphError(
                    "hypergraph relations must be RelationRecord objects",
                    code="INVALID_HYPERGRAPH",
                )
            key = (record.relation_id, record.version)
            if key in seen:
                raise RelationDuplicateError(
                    f"duplicate relation {record.relation_id!r} "
                    f"version {record.version}",
                    code="DUPLICATE_RELATION",
                )
            if key == (self.hypergraph_id, self.version):
                raise HypergraphError(
                    "a contained relation cannot share the hypergraph's "
                    "own (id, version)",
                    code="HYPERGRAPH_SELF_COLLISION",
                )
            if len(record.members) > limits.max_members:
                raise RelationLimitError(
                    f"relation {record.relation_id!r} has "
                    f"{len(record.members)} members > max_members "
                    f"{limits.max_members}",
                    code="MEMBER_LIMIT",
                )
            seen.add(key)
            relations.append(record)
        if len(relations) > limits.max_relations:
            raise RelationLimitError(
                f"hypergraph has {len(relations)} relations > max_relations "
                f"{limits.max_relations}",
                code="RELATION_LIMIT",
            )
        object.__setattr__(self, "schema", schema)
        object.__setattr__(self, "limits", limits)
        object.__setattr__(self, "relations", tuple(relations))
        object.__setattr__(
            self, "provenance",
            _freeze_json(self.provenance, "hypergraph provenance",
                         error=HypergraphError),
        )
        # Validate the hypergraph's own relation shape eagerly.
        self._own_relation_record()

    # -- construction helpers ---------------------------------------------

    @classmethod
    def from_relation(cls, relation: RelationRecord, *,
                      hypergraph_id: str | None = None,
                      version: int = 1,
                      schema: RelationSchema | Mapping[str, Any] | None = None,
                      limits: RelationLimits | Mapping[str, Any] | None = None,
                      provenance: Mapping[str, Any] | None = None) -> "Hypergraph":
        if not isinstance(relation, RelationRecord):
            raise HypergraphError(
                "from_relation requires a RelationRecord",
                code="INVALID_HYPERGRAPH",
            )
        selected_id = hypergraph_id or ("hg:" + relation.content_digest())
        return cls(
            hypergraph_id=selected_id,
            version=version,
            relations=(relation,),
            schema=schema,
            limits=limits,
            provenance=(
                {"source_relation": relation.relation_id}
                if provenance is None else provenance
            ),
        )

    @classmethod
    def from_relations(cls, relations: Iterable[RelationRecord], *,
                       hypergraph_id: str | None = None,
                       version: int = 1,
                       schema: RelationSchema | Mapping[str, Any] | None = None,
                       limits: RelationLimits | Mapping[str, Any] | None = None,
                       provenance: Mapping[str, Any] | None = None) -> "Hypergraph":
        items = tuple(relations)
        if hypergraph_id is None:
            payload = [
                {
                    "relation_id": item.relation_id,
                    "version": item.version,
                    "content_digest": item.content_digest(),
                }
                for item in items
            ]
            hypergraph_id = "hg:" + digest_object(payload)
        return cls(
            hypergraph_id=hypergraph_id,
            version=version,
            relations=items,
            schema=schema,
            limits=limits,
            provenance={} if provenance is None else provenance,
        )

    # -- descriptive properties -------------------------------------------

    @property
    def relation_schema(self) -> RelationSchema:
        return self.schema

    @property
    def schema_ids(self) -> tuple[str, ...]:
        return tuple(sorted({record.schema.schema_id for record in self.relations}))

    def __len__(self) -> int:
        return len(self.relations)

    def __iter__(self):
        return iter(self.relations)

    # -- relation index / membership --------------------------------------

    def _own_relation_record(self) -> RelationRecord:
        role = "member" if "member" in self.schema.role_names else None
        if role is None and self.schema.roles and not self.schema.allow_unroled:
            raise HypergraphError(
                "hypergraph schema must declare role 'member' or allow "
                "unroled members",
                code="HYPERGRAPH_SCHEMA_ROLE",
            )
        return RelationRecord(
            relation_id=self.hypergraph_id,
            schema=self.schema,
            version=self.version,
            members=tuple(
                RelationMember(
                    leaf_id=record.relation_id,
                    version=record.version,
                    role=role,
                )
                for record in self.relations
            ),
            provenance=dict(self.provenance),
        )

    def as_relation_record(self) -> RelationRecord:
        return self._own_relation_record()

    def _index(self) -> dict[tuple[str, int], RelationRecord]:
        index = {
            (record.relation_id, record.version): record
            for record in self.relations
        }
        own = self._own_relation_record()
        index.setdefault((own.relation_id, own.version), own)
        return index

    def relation(self, relation_id: str, version: int | None = None) -> RelationRecord:
        if not isinstance(relation_id, str):
            raise HypergraphError(
                "relation_id must be text", code="UNKNOWN_RELATION"
            )
        if version is not None:
            _require_int(version, "version", minimum=1,
                         error=HypergraphError, code="UNKNOWN_RELATION")
        if relation_id == self.hypergraph_id and (
            version is None or version == self.version
        ):
            return self._own_relation_record()
        matches = [
            record for record in self.relations
            if record.relation_id == relation_id
            and (version is None or record.version == version)
        ]
        if not matches:
            raise HypergraphError(
                f"unknown relation {relation_id!r}@v{version}"
                if version is not None else f"unknown relation {relation_id!r}",
                code="UNKNOWN_RELATION",
            )
        if version is not None:
            return matches[0]
        return max(matches, key=lambda record: record.version)

    def relations_for(self, relation_id: str) -> tuple[RelationRecord, ...]:
        return tuple(sorted(
            (record for record in self.relations
             if record.relation_id == relation_id),
            key=lambda record: record.version,
        ))

    def relations_for_schema(self, schema_id: str,
                             version: int | None = None) -> tuple[RelationRecord, ...]:
        return tuple(
            record for record in self.relations
            if record.schema.schema_id == schema_id
            and (version is None or record.schema.version == version)
        )

    def compatible_relations(self,
                             record: RelationRecord) -> tuple[RelationRecord, ...]:
        if not isinstance(record, RelationRecord):
            raise HypergraphError(
                "compatible_relations requires a RelationRecord",
                code="INVALID_HYPERGRAPH",
            )
        return tuple(
            item for item in self.relations
            if item.schema.is_compatible_with(record.schema)
        )

    def __contains__(self, value: Any) -> bool:
        try:
            if isinstance(value, RelationRecord):
                self.relation(value.relation_id, value.version)
                return True
            if isinstance(value, tuple) and len(value) == 2:
                self.relation(value[0], value[1])
                return True
            if isinstance(value, str):
                self.relation(value)
                return True
        except HypergraphError:
            return False
        return False

    def __getitem__(self, key: Any) -> RelationRecord:
        if isinstance(key, tuple) and len(key) == 2:
            return self.relation(key[0], key[1])
        return self.relation(key)

    def members_of(self, relation_id: str,
                   version: int | None = None) -> tuple[RelationMember, ...]:
        return self.relation(relation_id, version).members

    def members(self, relation_id: str,
                version: int | None = None) -> tuple[RelationMember, ...]:
        return self.members_of(relation_id, version)

    def is_member(self, relation_id: str, leaf_id: str,
                  version: int | None = None) -> bool:
        return self.relation(relation_id).is_member(leaf_id, version)

    def incidence(self, leaf_id: str, version: int | None = None, *,
                  include_hypergraph: bool = False) -> tuple[RelationRecord, ...]:
        records = list(self.relations)
        if include_hypergraph:
            records.append(self._own_relation_record())
        return tuple(
            record for record in records
            if record.is_member(leaf_id, version)
        )

    def incidence_map(self, *, include_hypergraph: bool = False
                      ) -> dict[str, tuple[RelationRecord, ...]]:
        records = list(self.relations)
        if include_hypergraph:
            records.append(self._own_relation_record())
        result: dict[str, list[RelationRecord]] = {}
        for record in records:
            for member in record.members:
                result.setdefault(member.leaf_id, []).append(record)
        return {key: tuple(value) for key, value in result.items()}

    # -- bounded traversal / expansion ------------------------------------

    def _limits_with(self, limits: Any, *,
                     max_depth: int | None = None,
                     max_fanout: int | None = None,
                     max_members: int | None = None,
                     max_relations: int | None = None) -> RelationLimits:
        base = self.limits if limits is None else _coerce_limits(limits)
        return RelationLimits(
            max_depth=base.max_depth if max_depth is None else max_depth,
            max_fanout=base.max_fanout if max_fanout is None else max_fanout,
            max_members=base.max_members if max_members is None else max_members,
            max_relations=(
                base.max_relations if max_relations is None else max_relations
            ),
        )

    def _start_record(self, start: Any) -> RelationRecord:
        if start is None:
            return self._own_relation_record()
        if isinstance(start, RelationRecord):
            return start
        if isinstance(start, Mapping):
            return RelationRecord.from_dict(start)
        if isinstance(start, tuple) and len(start) == 2:
            return self.relation(start[0], start[1])
        if isinstance(start, str):
            return self.relation(start)
        raise HypergraphError(
            "start must be a relation id, (id, version), or RelationRecord",
            code="UNKNOWN_RELATION",
        )

    @staticmethod
    def _children(record: RelationRecord,
                  index: Mapping[tuple[str, int], RelationRecord]
                  ) -> tuple[RelationRecord, ...]:
        children: list[RelationRecord] = []
        seen: set[tuple[str, int]] = set()
        for member in record.members:
            key = (member.leaf_id, member.version)
            child = index.get(key)
            if child is not None and key not in seen:
                seen.add(key)
                children.append(child)
        return tuple(children)

    def children(self, relation: Any) -> tuple[RelationRecord, ...]:
        """Direct nested relation records (exact id/version matches only)."""
        return self._children(self._start_record(relation), self._index())

    @staticmethod
    def _traversal_key(record: RelationRecord) -> tuple[str, int]:
        return (record.relation_id, record.version)

    def _describe_path(self, path: Sequence[tuple[str, int]]) -> tuple[str, ...]:
        return tuple(f"{relation_id}@v{version}" for relation_id, version in path)

    def traverse(self, start: Any = None, *,
                 max_depth: int | None = None,
                 max_fanout: int | None = None,
                 max_members: int | None = None,
                 max_relations: int | None = None,
                 limits: Any = None,
                 include_start: bool = True) -> tuple[RelationRecord, ...]:
        """Deterministic pre-order traversal with cycle/depth/fan-out bounds.

        ``start`` may be a relation id, ``(id, version)``, ``RelationRecord``,
        or ``None`` for the hypergraph's own relation leaf.  A cycle on the
        current path raises ``RelationCycleError``.  A DAG sharing a node
        between different paths is visited once and is not a cycle.
        """
        bound = self._limits_with(
            limits, max_depth=max_depth, max_fanout=max_fanout,
            max_members=max_members, max_relations=max_relations,
        )
        seed = self._start_record(start)
        index = self._index()
        index.setdefault(self._traversal_key(seed), seed)
        visited: dict[tuple[str, int], RelationRecord] = {}
        order: list[RelationRecord] = []
        path: list[tuple[str, int]] = []
        path_set: set[tuple[str, int]] = set()

        def visit(record: RelationRecord, depth: int) -> None:
            key = self._traversal_key(record)
            if key in path_set:
                cycle = self._describe_path(tuple(path) + (key,))
                raise RelationCycleError(
                    "relation cycle: " + " -> ".join(cycle),
                    cycle=cycle, code="CYCLE_DETECTED",
                )
            if key in visited:
                return
            if len(visited) >= bound.max_relations:
                raise RelationLimitError(
                    f"traversal exceeds max_relations {bound.max_relations}",
                    code="RELATION_LIMIT",
                )
            if len(record.members) > bound.max_members:
                raise RelationLimitError(
                    f"relation {record.relation_id!r} has "
                    f"{len(record.members)} members > max_members "
                    f"{bound.max_members}",
                    code="MEMBER_LIMIT",
                )
            visited[key] = record
            if include_start or depth > 0:
                order.append(record)
            children = self._children(record, index)
            if len(children) > bound.max_fanout:
                raise RelationFanoutError(
                    f"relation {record.relation_id!r} has {len(children)} "
                    f"nested relations > max_fanout {bound.max_fanout}",
                    code="FANOUT_LIMIT",
                )
            if children and depth >= bound.max_depth:
                raise RelationDepthError(
                    f"traversal depth exceeds max_depth {bound.max_depth}",
                    code="DEPTH_LIMIT",
                )
            path.append(key)
            path_set.add(key)
            for child in children:
                visit(child, depth + 1)
            path.pop()
            path_set.remove(key)

        visit(seed, 0)
        return tuple(order)

    def expand(self, start: Any = None, *,
               max_depth: int | None = None,
               max_fanout: int | None = None,
               max_members: int | None = None,
               max_relations: int | None = None,
               limits: Any = None,
               include_start: bool = True) -> tuple[RelationRecord, ...]:
        return self.traverse(
            start, max_depth=max_depth, max_fanout=max_fanout,
            max_members=max_members, max_relations=max_relations,
            limits=limits, include_start=include_start,
        )

    def walk(self, start: Any = None, **kwargs: Any) -> tuple[RelationRecord, ...]:
        return self.traverse(start, **kwargs)

    def find_cycle(self, start: Any = None, *,
                   max_depth: int | None = None,
                   max_fanout: int | None = None,
                   max_members: int | None = None,
                   max_relations: int | None = None,
                   limits: Any = None) -> tuple[str, ...] | None:
        """Return one cycle path (id@version strings) or ``None``."""
        bound = self._limits_with(
            limits, max_depth=max_depth, max_fanout=max_fanout,
            max_members=max_members, max_relations=max_relations,
        )
        seed = self._start_record(start)
        index = self._index()
        index.setdefault(self._traversal_key(seed), seed)
        visited: set[tuple[str, int]] = set()
        path: list[tuple[str, int]] = []
        path_set: set[tuple[str, int]] = set()

        def dfs(record: RelationRecord, depth: int) -> tuple[str, ...] | None:
            key = self._traversal_key(record)
            if key in path_set:
                index_in_path = path.index(key)
                return self._describe_path(
                    tuple(path[index_in_path:]) + (key,)
                )
            if key in visited:
                return None
            if len(visited) >= bound.max_relations:
                raise RelationLimitError(
                    f"cycle search exceeds max_relations "
                    f"{bound.max_relations}",
                    code="RELATION_LIMIT",
                )
            if len(record.members) > bound.max_members:
                raise RelationLimitError(
                    f"relation {record.relation_id!r} has "
                    f"{len(record.members)} members > max_members "
                    f"{bound.max_members}",
                    code="MEMBER_LIMIT",
                )
            visited.add(key)
            children = self._children(record, index)
            if len(children) > bound.max_fanout:
                raise RelationFanoutError(
                    f"relation {record.relation_id!r} has {len(children)} "
                    f"nested relations > max_fanout {bound.max_fanout}",
                    code="FANOUT_LIMIT",
                )
            if children and depth >= bound.max_depth:
                return None
            path.append(key)
            path_set.add(key)
            try:
                for child in children:
                    found = dfs(child, depth + 1)
                    if found is not None:
                        return found
            finally:
                path.pop()
                path_set.remove(key)
            return None

        return dfs(seed, 0)

    def has_cycle(self, start: Any = None, **kwargs: Any) -> bool:
        return self.find_cycle(start, **kwargs) is not None

    def bounded_subgraph(self, start: Any = None, *,
                         max_depth: int | None = None,
                         max_fanout: int | None = None,
                         max_members: int | None = None,
                         max_relations: int | None = None,
                         limits: Any = None) -> "Hypergraph":
        records = self.traverse(
            start, max_depth=max_depth, max_fanout=max_fanout,
            max_members=max_members, max_relations=max_relations,
            limits=limits, include_start=True,
        )
        keep = {self._traversal_key(record) for record in records}
        relations = tuple(
            record for record in self.relations
            if self._traversal_key(record) in keep
        )
        return Hypergraph(
            hypergraph_id=self.hypergraph_id,
            version=self.version,
            relations=relations,
            schema=self.schema,
            limits=self.limits,
            provenance=dict(self.provenance),
        )

    # -- identity / versioning --------------------------------------------

    def content_payload(self) -> dict[str, Any]:
        return {
            "schema_digest": self.schema.digest(),
            "relations": [
                {
                    "relation_id": record.relation_id,
                    "version": record.version,
                    "content_digest": record.content_digest(),
                }
                for record in sorted(
                    self.relations,
                    key=lambda item: (item.relation_id, item.version),
                )
            ],
            "limits": self.limits.to_dict(),
        }

    def content_digest(self) -> str:
        return digest_object(self.content_payload())

    def digest(self) -> str:
        return digest_object(self.to_dict())

    def is_same_hypergraph(self, other: Any, *,
                           include_provenance: bool = True) -> bool:
        if not isinstance(other, Hypergraph):
            return False
        if self.hypergraph_id != other.hypergraph_id \
                or self.version != other.version:
            return False
        if include_provenance:
            return self.digest() == other.digest()
        return self.content_digest() == other.content_digest()

    def next_version(self, *, version: int | None = None,
                     relations: Iterable[RelationRecord] | None = None,
                     schema: Any = None,
                     limits: Any = None,
                     provenance: Any = None) -> "Hypergraph":
        return Hypergraph(
            hypergraph_id=self.hypergraph_id,
            version=self.version + 1 if version is None else version,
            relations=(
                self.relations if relations is None else tuple(relations)
            ),
            schema=self.schema if schema is None else schema,
            limits=self.limits if limits is None else limits,
            provenance=(
                dict(self.provenance) if provenance is None else provenance
            ),
        )

    def with_relation(self,
                      relation: RelationRecord,
                      *, version: int | None = None) -> "Hypergraph":
        if not isinstance(relation, RelationRecord):
            raise HypergraphError(
                "with_relation requires a RelationRecord",
                code="INVALID_HYPERGRAPH",
            )
        key = (relation.relation_id, relation.version)
        for existing in self.relations:
            if (existing.relation_id, existing.version) == key:
                if existing.digest() == relation.digest():
                    return self
                raise RelationDuplicateError(
                    f"relation {relation.relation_id!r}@v{relation.version} "
                    "already has different content",
                    code="DUPLICATE_RELATION",
                )
        return Hypergraph(
            hypergraph_id=self.hypergraph_id,
            version=self.version + 1 if version is None else version,
            relations=tuple(self.relations) + (relation,),
            schema=self.schema,
            limits=self.limits,
            provenance=dict(self.provenance),
        )

    # -- serialization -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": HYPERGRAPH_RECORD_SCHEMA,
            "hypergraph_id": self.hypergraph_id,
            "version": self.version,
            "relation_schema": self.schema.to_dict(),
            "relations": [
                record.to_dict()
                for record in sorted(
                    self.relations,
                    key=lambda item: (item.relation_id, item.version),
                )
            ],
            "limits": self.limits.to_dict(),
            "provenance": _freeze_json(
                self.provenance, "hypergraph provenance",
                error=HypergraphError,
            ),
        }

    def as_math_leaf(self, *, leaf_id: str | None = None) -> MathLeaf:
        selected = self.hypergraph_id if leaf_id is None else leaf_id
        if not isinstance(selected, str) or not selected.startswith("nml:"):
            raise HypergraphError(
                "as_math_leaf requires an nml: leaf id (pass leaf_id=...)",
                code="INVALID_LEAF_ID",
            )
        try:
            return MathLeaf(
                leaf_id=selected,
                kind="hypergraph",
                version=self.version,
                type={
                    "hypergraph_id": self.hypergraph_id,
                    "relation_schema": self.schema.schema_id,
                    "relation_schema_version": self.schema.version,
                    "relation_count": len(self.relations),
                },
                content={
                    "digest": self.digest(),
                    "content_digest": self.content_digest(),
                    "schema_digest": self.schema.digest(),
                    "relation_count": len(self.relations),
                },
                provenance=dict(self.provenance),
                metadata={"hypergraph_id": self.hypergraph_id},
            )
        except MathObjectError as exc:
            raise HypergraphError(
                f"hypergraph cannot be represented as a math leaf: {exc}",
                code="INVALID_LEAF_ID",
            ) from exc

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> "Hypergraph":
        allowed = frozenset({
            "schema", "hypergraph_id", "version", "relation_schema",
            "relations", "limits", "provenance",
        })
        data = _mapping_fields(
            document, "hypergraph", allowed=allowed,
            required=frozenset({"hypergraph_id"}),
            error=HypergraphError, code="INVALID_HYPERGRAPH",
        )
        marker = data.get("schema")
        if marker is not None and marker != HYPERGRAPH_RECORD_SCHEMA:
            raise HypergraphError(
                f"unexpected schema marker: {marker!r}",
                code="INVALID_HYPERGRAPH",
            )
        schema_document = data.get("relation_schema")
        schema = (
            None if schema_document is None
            else (
                schema_document if isinstance(schema_document, RelationSchema)
                else RelationSchema.from_dict(schema_document)
            )
        )
        return cls(
            hypergraph_id=data["hypergraph_id"],
            version=data.get("version", 1),
            relations=tuple(data.get("relations", ())),
            schema=schema,
            limits=data.get("limits"),
            provenance=dict(data.get("provenance", {})),
        )


__all__ = [
    "CONSTRAINT_OPS", "DEFAULT_MAX_DEPTH", "DEFAULT_MAX_FANOUT",
    "DEFAULT_MAX_MEMBERS", "DEFAULT_MAX_RELATIONS", "DUPLICATE_POLICIES",
    "HYPERGRAPH_RECORD_SCHEMA", "HYPERGRAPH_RELATION_SCHEMA",
    "HYPERGRAPH_RELATION_SCHEMA_ID", "HYPERGRAPH_SCHEMA",
    "Hypergraph", "HypergraphError", "MAX_HYPEREDGE_MEMBERS",
    "RELATION_RECORD_SCHEMA", "RELATION_SCHEMA",
    "RELATION_SCHEMA_DEFINITION_SCHEMA", "RELATION_SCHEMA_SCHEMA",
    "RelationCompatibilityError", "RelationConstraint", "RelationCycleError",
    "RelationDepthError", "RelationDuplicateError", "RelationError",
    "RelationFanoutError", "RelationLimitError", "RelationLimits",
    "RelationMember", "RelationMemberError", "RelationRecord",
    "RelationSchema", "RelationSchemaError", "RelationValidationError",
    "RoleSpec", "SchemaCompatibility", "WEIGHT_DOMAINS",
    "relation_id_for", "schemas_compatible",
]
