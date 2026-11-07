"""Bounded discovery proposals for the five GAME_PLAN_:: learning mechanisms.

This module implements only the *proposal* half of GAME_PLAN_:: §13.1.  It
groups statically classified leaves and function metadata into deterministic
discovery candidates and returns them as immutable, non-authoritative records.

The five mechanisms are:

``structural``
    Group/pair leaves by kind, domain, shape, and layout.
``transformational``
    Propose leaf-to-function-output transitions when a leaf statically
    satisfies a registered input contract.
``derivational``
    Propose bounded function compositions when one output contract satisfies
    the next consumer input contract.
``relational``
    Propose a typed relation schema plus a member set for structurally
    compatible leaves.
``operational``
    Propose implementation/workspace/determinism/cache policy observations
    from function metadata.

This layer deliberately does **not**:

* evaluate mathematics or perform arithmetic on mathematical values;
* run or import an executor, validity engine, store, or authority layer;
* assign validity, truth, proof, authorization, or promotion status;
* persist proposals or mutate the linker/runtime snapshot.

A proposal is evidence for a separate review/validation pipeline.  It cannot
execute or promote itself.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
import re
from typing import Any

from .math_linker import LeafClass, LinkError, classify_leaf
from .math_objects import (
    MathFunction,
    MathLeaf,
    MathObjectError,
    canonical_json,
    digest_object,
)
from .math_relation import (
    MAX_HYPEREDGE_MEMBERS,
    RelationError,
    RelationMember,
    RelationRecord,
    RelationSchema,
    RoleSpec,
    relation_id_for,
)

DISCOVERY_ID = "math.discovery.v1"
REQUEST_SCHEMA = "nanrouter.math-discovery-request.v1"
PROPOSAL_SCHEMA = "nanrouter.math-discovery-proposal.v1"
RESULT_SCHEMA = "nanrouter.math-discovery-result.v1"

MECHANISMS = (
    "structural",
    "transformational",
    "derivational",
    "relational",
    "operational",
)
_MECHANISM_ORDER = {name: index for index, name in enumerate(MECHANISMS)}

_REASON_ORDER = {
    "depth_limit": 0,
    "fuel_exhausted": 1,
    "fanout_limit": 2,
    "proposal_limit": 3,
}

_KIND_ALIASES = {
    "vec": "vector",
    "vectors": "vector",
    "mat": "matrix",
    "matrices": "matrix",
    "num": "numeric",
    "number": "numeric",
}
_KIND_WILDCARDS = frozenset({"any", "*", "object", "leaf"})
_DOMAIN_WILDCARDS = frozenset({
    "any", "*", "numeric", "number", "unspecified", "unknown",
})
_NUMERIC_KINDS = frozenset({"scalar", "vector", "matrix", "tensor"})
_NUMERIC_DOMAINS = frozenset({
    "real", "integer", "rational", "complex", "boolean", "bool", "natural",
    "finite", "exact", "symbolic",
})
_PRECISION_ALIASES = {
    "f16": "float16", "float16": "float16", "half": "float16",
    "f32": "float32", "float32": "float32", "single": "float32",
    "f64": "float64", "float64": "float64", "double": "float64",
}
_IMPLEMENTATION_KEYS = (
    "kernel_id", "version", "precision", "shape", "workspace_words",
    "capability_class", "implementation_digest", "source_digest",
    "fixture_digest", "status", "marker", "steps", "tags", "notes", "source",
    "fixture",
)
_MAX_JSON_ITEMS = 4096
_MAX_JSON_DEPTH = 16


class DiscoveryError(ValueError):
    """Invalid discovery request, record, or bound."""


# ---------------------------------------------------------------------------
# Canonical JSON helpers
# ---------------------------------------------------------------------------


def _canonical_copy(value: Any, name: str, *, depth: int = 0) -> Any:
    """Deep-copy canonical JSON values and reject host floats/opaque objects."""
    if depth > _MAX_JSON_DEPTH:
        raise DiscoveryError(f"{name} nesting exceeds {_MAX_JSON_DEPTH}")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        raise DiscoveryError(f"{name} must not contain host floats")
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 256:
                raise DiscoveryError(
                    f"{name} keys must be non-empty strings <= 256 characters"
                )
            result[key] = _canonical_copy(
                item, f"{name}.{key}", depth=depth + 1,
            )
        return result
    if isinstance(value, (list, tuple)):
        if len(value) > _MAX_JSON_ITEMS:
            raise DiscoveryError(f"{name} exceeds {_MAX_JSON_ITEMS} entries")
        return [
            _canonical_copy(item, f"{name}[{index}]", depth=depth + 1)
            for index, item in enumerate(value)
        ]
    raise DiscoveryError(
        f"{name} contains a non-canonical value: {type(value).__name__}"
    )


def _plain(value: Any) -> Any:
    """Return plain mutable JSON containers without aliasing record state."""
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _require_text(value: Any, name: str, *, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise DiscoveryError(f"{name} must be a non-empty string <= {maximum}")
    return value.strip()


def _require_int(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise DiscoveryError(f"{name} must be an integer >= {minimum}")
    return value


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)


def _sorted_reasons(values: Iterable[str]) -> tuple[str, ...]:
    unique = _unique(values)
    return tuple(sorted(
        unique,
        key=lambda item: (_REASON_ORDER.get(item, 99), item),
    ))


# ---------------------------------------------------------------------------
# Bounds and request
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiscoveryBounds:
    """Hard bounds for one discovery call."""

    max_proposals: int = 32
    max_fanout: int = 32
    max_depth: int = 2
    fuel: int = 1024

    def __post_init__(self) -> None:
        _require_int(self.max_proposals, "max_proposals", minimum=0)
        _require_int(self.max_fanout, "max_fanout", minimum=0)
        _require_int(self.max_depth, "max_depth", minimum=0)
        _require_int(self.fuel, "fuel", minimum=0)

    @classmethod
    def from_value(cls, value: Any) -> "DiscoveryBounds":
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        if isinstance(value, Mapping):
            return cls(
                max_proposals=value.get("max_proposals", 32),
                max_fanout=value.get("max_fanout", 32),
                max_depth=value.get("max_depth", 2),
                fuel=value.get("fuel", 1024),
            )
        raise DiscoveryError("bounds must be a mapping or DiscoveryBounds")

    def to_dict(self) -> dict[str, int]:
        return {
            "max_proposals": self.max_proposals,
            "max_fanout": self.max_fanout,
            "max_depth": self.max_depth,
            "fuel": self.fuel,
        }


@dataclass(frozen=True)
class DiscoveryRequest:
    """Typed input to one mechanism or to :func:`propose_all`.

    ``mechanism`` is a request label; ``"all"`` means every mechanism.  A
    per-mechanism function may still be called directly with any request.
    """

    mechanism: str = "all"
    leaves: tuple[MathLeaf, ...] = ()
    functions: tuple[MathFunction, ...] = ()
    relations: tuple[Any, ...] = ()
    objective: str = "discovery"
    bounds: DiscoveryBounds | Mapping[str, Any] = field(
        default_factory=DiscoveryBounds
    )
    snapshot_id: str | None = None
    allow_scratch: bool = False

    def __post_init__(self) -> None:
        mechanism = _require_text(self.mechanism, "mechanism", maximum=64).lower()
        if mechanism != "all" and mechanism not in MECHANISMS:
            raise DiscoveryError(
                f"mechanism must be 'all' or one of {', '.join(MECHANISMS)}"
            )
        object.__setattr__(self, "mechanism", mechanism)
        object.__setattr__(self, "objective", _require_text(self.objective, "objective"))

        for name, expected in (
            ("leaves", MathLeaf),
            ("functions", MathFunction),
        ):
            raw = getattr(self, name)
            if not isinstance(raw, (tuple, list)):
                raise DiscoveryError(f"{name} must be a list of {expected.__name__}")
            values = []
            for item in raw:
                if not isinstance(item, expected):
                    raise DiscoveryError(
                        f"{name} entries must be {expected.__name__} records"
                    )
                values.append(item)
            object.__setattr__(self, name, tuple(values))

        if not isinstance(self.relations, (tuple, list)):
            raise DiscoveryError(
                "relations must be a list of RelationSchema/RelationRecord"
            )
        relation_values = []
        for item in self.relations:
            if not isinstance(item, (RelationSchema, RelationRecord)):
                raise DiscoveryError(
                    "relations entries must be RelationSchema or RelationRecord"
                )
            relation_values.append(item)
        object.__setattr__(self, "relations", tuple(relation_values))

        object.__setattr__(self, "bounds", DiscoveryBounds.from_value(self.bounds))
        if not isinstance(self.allow_scratch, bool):
            raise DiscoveryError("allow_scratch must be a boolean")
        if self.snapshot_id is not None:
            object.__setattr__(
                self, "snapshot_id",
                _require_text(self.snapshot_id, "snapshot_id", maximum=256),
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": REQUEST_SCHEMA,
            "mechanism": self.mechanism,
            "objective": self.objective,
            "snapshot_id": self.snapshot_id,
            "allow_scratch": self.allow_scratch,
            "bounds": self.bounds.to_dict(),
            "leaf_count": len(self.leaves),
            "function_count": len(self.functions),
            "relation_count": len(self.relations),
        }


# ---------------------------------------------------------------------------
# Proposal and result records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiscoveryProposal:
    """One non-authoritative discovery candidate.

    There are intentionally no validity, truth, proof, or authorization
    fields.  ``non_authoritative`` is always true and execution/promotion are
    hard failures.
    """

    proposal_id: str
    mechanism: str
    kind: str
    refs: tuple[dict[str, Any], ...]
    evidence: dict[str, Any]
    rank: int
    snapshot_id: str
    non_authoritative: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.proposal_id, str) or not self.proposal_id.startswith("dsc:"):
            raise DiscoveryError("proposal_id must start with dsc:")
        mechanism = _require_text(self.mechanism, "mechanism", maximum=64).lower()
        if mechanism not in MECHANISMS:
            raise DiscoveryError(f"unknown discovery mechanism: {mechanism!r}")
        object.__setattr__(self, "mechanism", mechanism)
        object.__setattr__(self, "kind", _require_text(self.kind, "kind", maximum=128))
        object.__setattr__(self, "snapshot_id", _require_text(
            self.snapshot_id, "snapshot_id", maximum=256,
        ))
        _require_int(self.rank, "rank", minimum=1)
        if not isinstance(self.refs, (tuple, list)) or not self.refs:
            raise DiscoveryError("refs must be a non-empty list of reference objects")
        refs = []
        for ref in self.refs:
            if not isinstance(ref, Mapping):
                raise DiscoveryError("refs entries must be objects")
            refs.append(_canonical_copy(ref, "refs entry"))
        object.__setattr__(self, "refs", tuple(refs))
        if not isinstance(self.evidence, Mapping):
            raise DiscoveryError("evidence must be an object")
        object.__setattr__(
            self, "evidence", _canonical_copy(self.evidence, "evidence"),
        )
        if self.non_authoritative is not True:
            raise DiscoveryError("discovery proposals must be non-authoritative")

    @property
    def content_key(self) -> str:
        """Mechanism-independent content identity used for dedupe."""
        return digest_object({
            "snapshot_id": self.snapshot_id,
            "kind": self.kind,
            "refs": list(self.refs),
            "evidence": self.evidence,
        })

    @property
    def executable(self) -> bool:
        return False

    @property
    def promotable(self) -> bool:
        return False

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        raise DiscoveryError(
            "discovery proposals are non-authoritative and cannot execute"
        )

    def promote(self, *args: Any, **kwargs: Any) -> Any:
        raise DiscoveryError(
            "discovery proposals are non-authoritative and cannot promote"
        )

    def digest(self) -> str:
        return digest_object(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PROPOSAL_SCHEMA,
            "discoverer_id": DISCOVERY_ID,
            "proposal_id": self.proposal_id,
            "content_key": self.content_key,
            "mechanism": self.mechanism,
            "kind": self.kind,
            "refs": [_plain(ref) for ref in self.refs],
            "evidence": _plain(self.evidence),
            "rank": self.rank,
            "snapshot_id": self.snapshot_id,
            "non_authoritative": True,
            "execution": "not_performed",
            "promotion": "not_permitted",
        }


@dataclass(frozen=True)
class DiscoveryResult:
    """Deterministic, bounded proposal set with explicit non-authority."""

    requested_mechanism: str
    mechanisms: tuple[str, ...]
    snapshot_id: str
    derived_snapshot_id: str
    objective: str
    proposals: tuple[DiscoveryProposal, ...]
    bounds: DiscoveryBounds | Mapping[str, Any] = field(
        default_factory=DiscoveryBounds
    )
    incomplete: bool = False
    incomplete_reasons: tuple[str, ...] = ()
    fuel_used: int = 0
    considered: int = 0
    omitted_proposal_count: int = 0
    search: dict[str, Any] = field(default_factory=dict)
    non_authoritative: bool = True

    def __post_init__(self) -> None:
        requested = _require_text(
            self.requested_mechanism, "requested_mechanism", maximum=64,
        ).lower()
        if requested != "all" and requested not in MECHANISMS:
            raise DiscoveryError("invalid requested_mechanism")
        object.__setattr__(self, "requested_mechanism", requested)
        if not isinstance(self.mechanisms, (tuple, list)) or not self.mechanisms:
            raise DiscoveryError("mechanisms must be a non-empty list")
        mechanisms = []
        for item in self.mechanisms:
            name = _require_text(item, "mechanism", maximum=64).lower()
            if name not in MECHANISMS:
                raise DiscoveryError(f"unknown discovery mechanism: {name!r}")
            mechanisms.append(name)
        if len(set(mechanisms)) != len(mechanisms):
            raise DiscoveryError("mechanisms must be unique")
        object.__setattr__(
            self, "mechanisms",
            tuple(sorted(mechanisms, key=lambda name: _MECHANISM_ORDER[name])),
        )
        object.__setattr__(self, "snapshot_id", _require_text(
            self.snapshot_id, "snapshot_id", maximum=256,
        ))
        object.__setattr__(self, "derived_snapshot_id", _require_text(
            self.derived_snapshot_id, "derived_snapshot_id", maximum=256,
        ))
        object.__setattr__(self, "objective", _require_text(self.objective, "objective"))

        if not isinstance(self.proposals, (tuple, list)):
            raise DiscoveryError("proposals must be a list")
        proposals = []
        seen_ids: set[str] = set()
        seen_keys: set[str] = set()
        for item in self.proposals:
            if not isinstance(item, DiscoveryProposal):
                raise DiscoveryError("proposals entries must be DiscoveryProposal")
            if item.snapshot_id != self.snapshot_id:
                raise DiscoveryError("proposal snapshot_id does not match result")
            if item.proposal_id in seen_ids or item.content_key in seen_keys:
                raise DiscoveryError("duplicate proposal in discovery result")
            seen_ids.add(item.proposal_id)
            seen_keys.add(item.content_key)
            proposals.append(item)
        ranked = tuple(sorted(
            proposals,
            key=lambda item: (
                item.rank,
                _MECHANISM_ORDER[item.mechanism],
                item.kind,
                canonical_json(list(item.refs)),
                canonical_json(item.evidence),
            ),
        ))
        expected_ranks = tuple(range(1, len(ranked) + 1))
        if tuple(item.rank for item in ranked) != expected_ranks:
            raise DiscoveryError("proposal ranks must be contiguous from 1")
        object.__setattr__(self, "proposals", ranked)

        object.__setattr__(self, "bounds", DiscoveryBounds.from_value(self.bounds))
        reasons = []
        if not isinstance(self.incomplete_reasons, (tuple, list)):
            raise DiscoveryError("incomplete_reasons must be a list of strings")
        for reason in self.incomplete_reasons:
            reasons.append(_require_text(reason, "incomplete reason", maximum=128))
        object.__setattr__(self, "incomplete_reasons", _sorted_reasons(reasons))
        object.__setattr__(self, "incomplete", bool(reasons))
        _require_int(self.fuel_used, "fuel_used", minimum=0)
        _require_int(self.considered, "considered", minimum=0)
        _require_int(
            self.omitted_proposal_count, "omitted_proposal_count", minimum=0,
        )
        if not isinstance(self.search, Mapping):
            raise DiscoveryError("search must be an object")
        object.__setattr__(self, "search", _canonical_copy(self.search, "search"))
        if self.non_authoritative is not True:
            raise DiscoveryError("discovery results must be non-authoritative")

    @property
    def proposal_count(self) -> int:
        return len(self.proposals)

    @property
    def proposal_ids(self) -> tuple[str, ...]:
        return tuple(item.proposal_id for item in self.proposals)

    @property
    def executable(self) -> bool:
        return False

    @property
    def promotable(self) -> bool:
        return False

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        raise DiscoveryError(
            "discovery results are non-authoritative and cannot execute"
        )

    def promote(self, *args: Any, **kwargs: Any) -> Any:
        raise DiscoveryError(
            "discovery results are non-authoritative and cannot promote"
        )

    def digest(self) -> str:
        return digest_object(self.to_dict())

    @property
    def result_id(self) -> str:
        return "dset:" + self.digest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RESULT_SCHEMA,
            "discoverer_id": DISCOVERY_ID,
            "requested_mechanism": self.requested_mechanism,
            "mechanisms": list(self.mechanisms),
            "snapshot_id": self.snapshot_id,
            "derived_snapshot_id": self.derived_snapshot_id,
            "objective": self.objective,
            "proposals": [item.to_dict() for item in self.proposals],
            "proposal_count": len(self.proposals),
            "bounds": self.bounds.to_dict(),
            "incomplete": self.incomplete,
            "incomplete_reasons": list(self.incomplete_reasons),
            "fuel_used": self.fuel_used,
            "considered": self.considered,
            "omitted_proposal_count": self.omitted_proposal_count,
            "search": _plain(self.search),
            "non_authoritative": True,
            "execution": "not_performed",
            "promotion": "not_permitted",
        }


# ---------------------------------------------------------------------------
# Function/leaf classification helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _FunctionView:
    function_id: str
    version: int
    status: str
    inputs: tuple[dict[str, Any], ...]
    output: dict[str, Any]
    contract_digest: str
    implementations: tuple[dict[str, Any], ...]
    numerical_policy: dict[str, Any]


@dataclass(frozen=True)
class _Prepared:
    classes: tuple[LeafClass, ...]
    ignored_leaves: tuple[dict[str, Any], ...]
    functions: tuple[_FunctionView, ...]
    ignored_functions: tuple[dict[str, Any], ...]
    relation_schemas: tuple[RelationSchema, ...]
    ignored_relations: tuple[dict[str, Any], ...]
    derived_snapshot_id: str


def _leaf_sort_key(leaf: LeafClass) -> tuple[Any, ...]:
    return (
        leaf.leaf_id,
        leaf.version,
        leaf.content_digest or "",
        leaf.leaf_digest,
    )


def _function_sort_key(function: _FunctionView) -> tuple[Any, ...]:
    return (
        function.function_id,
        function.version,
        function.contract_digest,
    )


def _shape_value(value: Any) -> tuple[int | None, ...] | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return None if value < 0 else (value,)
    if isinstance(value, str):
        text = value.strip().lower()
        if not text or text in {"any", "*", "equal", "free", "broadcast"}:
            return None
        pieces = [
            piece for piece in re.split(r"\s*[,x]\s*|\s+", text)
            if piece
        ]
        if not pieces:
            return None
        dimensions: list[int | None] = []
        for piece in pieces:
            if piece in {"*", "?", "_", "none"}:
                dimensions.append(None)
            elif piece.isdigit():
                dimensions.append(int(piece))
            else:
                return None
        return tuple(dimensions)
    if isinstance(value, (list, tuple)):
        dimensions = []
        for item in value:
            if item is None:
                dimensions.append(None)
            elif isinstance(item, bool) or not isinstance(item, int) or item < 0:
                return None
            else:
                dimensions.append(item)
        return tuple(dimensions)
    return None


def _precision_key(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().lower()
    return _PRECISION_ALIASES.get(text, text)


def _endpoint_doc(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        raw = dict(value)
        nested = raw.get("type")
        if isinstance(nested, Mapping):
            merged = dict(nested)
            merged.update({key: item for key, item in raw.items() if key != "type"})
            raw = merged
    elif isinstance(value, str):
        raw = {"type": value}
    else:
        raw = {}

    type_value = raw.get("kind") or raw.get("leaf_kind")
    if type_value is None and isinstance(raw.get("type"), str):
        type_value = raw["type"]
    kind: str | None = None
    if isinstance(type_value, str):
        text = type_value.strip().lower()
        for separator in ("<", "["):
            if separator in text:
                text = text.split(separator, 1)[0].strip()
        kind = _KIND_ALIASES.get(text, text)

    domain = raw.get("domain", "any")
    if domain is None:
        domain = "any"
    domain = str(domain).strip().lower()

    layout = raw.get("layout", raw.get("order", raw.get("storage_layout")))
    if layout is not None:
        layout = str(layout).strip().lower()

    precision = raw.get("precision")
    if precision is None:
        precision = raw.get("dtype")
    precision = _precision_key(precision)

    element = raw.get("element")
    if element is None:
        element = raw.get("dtype")
    if element is not None:
        element = str(element).strip().lower()

    name = raw.get("name")
    return {
        "name": None if not isinstance(name, str) or not name.strip() else name.strip(),
        "kind": kind,
        "domain": domain,
        "shape": _shape_value(raw.get("shape", raw.get("dimension"))),
        "layout": layout,
        "precision": precision,
        "element": element,
    }


def _function_view(function: MathFunction) -> _FunctionView:
    signature = function.signature
    if not isinstance(signature, Mapping):
        raise DiscoveryError(f"{function.function_id}: signature must be an object")
    raw_inputs = signature.get("inputs", ())
    if raw_inputs is None:
        raw_inputs = ()
    elif isinstance(raw_inputs, Mapping):
        raw_inputs = (raw_inputs,)
    elif isinstance(raw_inputs, (str, bytes)):
        raw_inputs = (raw_inputs,)
    elif isinstance(raw_inputs, Sequence):
        raw_inputs = tuple(raw_inputs)
    else:
        raise DiscoveryError(f"{function.function_id}: unsupported inputs declaration")

    raw_output = signature.get("output")
    if raw_output is None:
        raw_output = signature.get("result")

    try:
        contract_digest = function.contract_digest or function.digest()
    except MathObjectError as exc:
        raise DiscoveryError(
            f"{function.function_id}: cannot compute contract digest: {exc}"
        ) from exc

    return _FunctionView(
        function_id=function.function_id,
        version=function.version,
        status=function.status,
        inputs=tuple(_endpoint_doc(item) for item in raw_inputs),
        output={} if raw_output is None else _endpoint_doc(raw_output),
        contract_digest=contract_digest,
        implementations=tuple(dict(item) for item in function.implementations),
        numerical_policy=dict(function.numerical_policy),
    )


def _leaf_class_doc(leaf: LeafClass) -> dict[str, Any]:
    return {
        "leaf_id": leaf.leaf_id,
        "version": leaf.version,
        "kind": leaf.kind,
        "domain": leaf.domain,
        "shape": list(leaf.shape),
        "shape_declared": leaf.shape_declared,
        "layout": leaf.layout,
        "precision": leaf.precision,
        "element": leaf.element,
        "type_name": leaf.type_name,
    }


def _leaf_ref(leaf: LeafClass, role: str | None = None) -> dict[str, Any]:
    ref: dict[str, Any] = {
        "ref_type": "leaf",
        "leaf_id": leaf.leaf_id,
        "version": leaf.version,
        "leaf_digest": leaf.leaf_digest,
    }
    if leaf.content_digest is not None:
        ref["content_digest"] = leaf.content_digest
    if role is not None:
        ref["role"] = role
    return ref


def _function_ref(function: _FunctionView, role: str | None = None) -> dict[str, Any]:
    ref: dict[str, Any] = {
        "ref_type": "function",
        "function_id": function.function_id,
        "version": function.version,
        "contract_digest": function.contract_digest,
    }
    if role is not None:
        ref["role"] = role
    return ref


def _relation_ref(relation: RelationSchema | RelationRecord,
                  role: str | None = None) -> dict[str, Any]:
    if isinstance(relation, RelationRecord):
        ref = {
            "ref_type": "relation",
            "relation_id": relation.relation_id,
            "version": relation.version,
            "schema_id": relation.schema.schema_id,
            "schema_version": relation.schema.version,
            "relation_digest": relation.digest(),
        }
    else:
        ref = {
            "ref_type": "relation-schema",
            "schema_id": relation.schema_id,
            "version": relation.version,
            "schema_digest": relation.digest(),
        }
    if role is not None:
        ref["role"] = role
    return ref


def _derive_snapshot_id(classes: tuple[LeafClass, ...],
                        functions: tuple[_FunctionView, ...],
                        schemas: tuple[RelationSchema, ...]) -> str:
    payload = {
        "leaves": [
            {
                "leaf_id": leaf.leaf_id,
                "version": leaf.version,
                "kind": leaf.kind,
                "leaf_digest": leaf.leaf_digest,
                "content_digest": leaf.content_digest,
            }
            for leaf in sorted(classes, key=_leaf_sort_key)
        ],
        "functions": [
            {
                "function_id": function.function_id,
                "version": function.version,
                "status": function.status,
                "contract_digest": function.contract_digest,
            }
            for function in sorted(functions, key=_function_sort_key)
        ],
        "relations": [
            {
                "schema_id": schema.schema_id,
                "version": schema.version,
                "schema_digest": schema.digest(),
            }
            for schema in sorted(
                schemas, key=lambda item: (item.schema_id, item.version, item.digest()),
            )
        ],
    }
    return "dsnp:" + digest_object(payload)


def _prepare(request: DiscoveryRequest) -> _Prepared:
    classes: list[LeafClass] = []
    ignored_leaves: list[dict[str, Any]] = []
    for leaf in request.leaves:
        try:
            classes.append(classify_leaf(leaf, allow_scratch=request.allow_scratch))
        except (LinkError, MathObjectError) as exc:
            code = getattr(exc, "code", "invalid_leaf")
            ignored_leaves.append({
                "leaf_id": leaf.leaf_id,
                "version": leaf.version,
                "reason": code,
            })
    classes.sort(key=_leaf_sort_key)

    functions: list[_FunctionView] = []
    ignored_functions: list[dict[str, Any]] = []
    for function in request.functions:
        try:
            functions.append(_function_view(function))
        except DiscoveryError as exc:
            ignored_functions.append({
                "function_id": function.function_id,
                "version": function.version,
                "reason": str(exc),
            })
    functions.sort(key=_function_sort_key)

    schemas: dict[str, RelationSchema] = {}
    ignored_relations: list[dict[str, Any]] = []
    for relation in request.relations:
        schema = relation if isinstance(relation, RelationSchema) else relation.schema
        try:
            existing = schemas.get(schema.schema_id)
            if existing is None or (
                schema.version, schema.digest()
            ) > (
                existing.version, existing.digest()
            ):
                schemas[schema.schema_id] = schema
        except RelationError as exc:
            ignored_relations.append({
                "schema_id": str(getattr(schema, "schema_id", "")),
                "reason": str(exc),
            })

    ordered_schemas = tuple(sorted(
        schemas.values(),
        key=lambda item: (item.schema_id, item.version, item.digest()),
    ))
    return _Prepared(
        classes=tuple(classes),
        ignored_leaves=tuple(sorted(
            ignored_leaves,
            key=lambda item: (item["leaf_id"], item["version"], item["reason"]),
        )),
        functions=tuple(functions),
        ignored_functions=tuple(sorted(
            ignored_functions,
            key=lambda item: (
                item["function_id"], item["version"], item["reason"],
            ),
        )),
        relation_schemas=ordered_schemas,
        ignored_relations=tuple(sorted(
            ignored_relations,
            key=lambda item: (item["schema_id"], item["reason"]),
        )),
        derived_snapshot_id=_derive_snapshot_id(
            tuple(classes), tuple(functions), ordered_schemas,
        ),
    )


# ---------------------------------------------------------------------------
# Static compatibility
# ---------------------------------------------------------------------------


def _kind_matches(required: str | None, actual: str | None) -> bool:
    if required is None or required in _KIND_WILDCARDS:
        return True
    if actual in (None, "unknown", ""):
        return False
    if required == actual:
        return True
    if required == "numeric":
        return actual in _NUMERIC_KINDS
    if required == "tensor":
        return actual in _NUMERIC_KINDS
    return False


def _domain_matches(required: str | None, actual: str | None) -> bool:
    if required is None or required in _DOMAIN_WILDCARDS:
        return True
    if actual in (None, "unknown", ""):
        return False
    if required == actual:
        return True
    if required == "numeric":
        return actual in _NUMERIC_DOMAINS
    if required == "complex":
        return actual in {"real", "integer", "rational"}
    if required == "real":
        return actual == "integer"
    return False


def _shape_matches(required: tuple[int | None, ...] | None,
                   actual: tuple[int, ...] | tuple[int | None, ...] | None,
                   actual_declared: bool) -> bool:
    if required is None:
        return True
    if not actual_declared:
        return True
    if actual is None or len(required) != len(actual):
        return False
    return all(
        wanted is None or wanted == got
        for wanted, got in zip(required, actual)
    )


def _layout_matches(required: str | None, actual: str | None) -> bool:
    if not required or required in {"any", "*", "unspecified"}:
        return True
    if not actual or actual in {"any", "*", "unspecified"}:
        return True
    return required == actual


def _precision_matches(required: str | None, actual: str | None, *,
                       require_declared: bool = False) -> bool:
    if not required or required in {"any", "*", "unspecified"}:
        return True
    if not actual or actual in {"any", "*", "unspecified"}:
        return not require_declared
    return _precision_key(required) == _precision_key(actual)


def _element_matches(required: str | None, actual: str | None, *,
                     require_declared: bool = False) -> bool:
    if not required or required in {"any", "*", "unspecified", "unknown"}:
        return True
    if not actual or actual in {"any", "*", "unspecified", "unknown"}:
        return not require_declared
    return required == actual


def _input_matches(endpoint: Mapping[str, Any], leaf: LeafClass) -> tuple[bool, str]:
    if not _kind_matches(endpoint.get("kind"), leaf.kind):
        return False, "kind_mismatch"
    if not _domain_matches(endpoint.get("domain"), leaf.domain):
        return False, "domain_mismatch"
    if not _shape_matches(endpoint.get("shape"), leaf.shape, leaf.shape_declared):
        return False, "shape_mismatch"
    if not _layout_matches(endpoint.get("layout"), leaf.layout):
        return False, "layout_mismatch"
    if not _precision_matches(endpoint.get("precision"), leaf.precision):
        return False, "precision_mismatch"
    if not _element_matches(endpoint.get("element"), leaf.element):
        return False, "element_mismatch"
    return True, ""


def _output_satisfies_input(output: Mapping[str, Any],
                            required: Mapping[str, Any]) -> tuple[bool, str]:
    if not _kind_matches(required.get("kind"), output.get("kind")):
        return False, "kind_mismatch"
    if not _domain_matches(required.get("domain"), output.get("domain")):
        return False, "domain_mismatch"

    required_shape = required.get("shape")
    if required_shape is not None:
        output_shape = output.get("shape")
        if output_shape is None:
            return False, "output_shape_undeclared"
        if len(required_shape) != len(output_shape):
            return False, "shape_mismatch"
        if not all(
            wanted is None or wanted == got
            for wanted, got in zip(required_shape, output_shape)
        ):
            return False, "shape_mismatch"

    if not _layout_matches(required.get("layout"), output.get("layout")):
        return False, "layout_mismatch"
    if not _precision_matches(
        required.get("precision"), output.get("precision"),
        require_declared=True,
    ):
        return False, "precision_mismatch"
    if not _element_matches(
        required.get("element"), output.get("element"),
        require_declared=True,
    ):
        return False, "element_mismatch"
    return True, ""


# ---------------------------------------------------------------------------
# Collection and bounded search
# ---------------------------------------------------------------------------


@dataclass
class _Fuel:
    limit: int
    used: int = 0
    exhausted: bool = False

    def consume(self) -> bool:
        if self.used >= self.limit:
            self.exhausted = True
            return False
        self.used += 1
        return True


@dataclass(frozen=True)
class _MechanismOutcome:
    mechanism: str
    proposals: tuple[DiscoveryProposal, ...]
    reasons: tuple[str, ...]
    fuel_used: int
    considered: int
    omitted: int
    duplicates: int
    search: dict[str, Any]


class _Collector:
    def __init__(self, mechanism: str, request: DiscoveryRequest,
                 prepared: _Prepared, fuel: _Fuel,
                 snapshot_id: str) -> None:
        self.mechanism = mechanism
        self.request = request
        self.prepared = prepared
        self.bounds = request.bounds
        self.fuel = fuel
        self.snapshot_id = snapshot_id
        self._fuel_start = fuel.used
        self._proposals: list[DiscoveryProposal] = []
        self._seen: set[str] = set()
        self._reasons: set[str] = set()
        self._counts: dict[str, int] = {}
        self.considered = 0
        self.duplicates = 0

    def _count(self, name: str, amount: int = 1) -> None:
        self._counts[name] = self._counts.get(name, 0) + amount

    def depth_ok(self, level: int) -> bool:
        if level > self.bounds.max_depth:
            self._reasons.add("depth_limit")
            return False
        return True

    def consume(self) -> bool:
        if not self.fuel.consume():
            self._reasons.add("fuel_exhausted")
            return False
        return True

    def consider(self) -> None:
        self.considered += 1

    def take_fanout(self, values: Iterable[Any]) -> tuple[tuple[Any, ...], bool]:
        items = tuple(values)
        if len(items) > self.bounds.max_fanout:
            self._reasons.add("fanout_limit")
            return items[:self.bounds.max_fanout], True
        return items, False

    def add(self, kind: str, refs: Iterable[Mapping[str, Any]],
            evidence: Mapping[str, Any]) -> DiscoveryProposal | None:
        refs_tuple = tuple(dict(ref) for ref in refs)
        evidence_copy = _canonical_copy(evidence, "evidence")
        content_key = digest_object({
            "snapshot_id": self.snapshot_id,
            "kind": kind,
            "refs": list(refs_tuple),
            "evidence": evidence_copy,
        })
        proposal_id = "dsc:" + digest_object({
            "snapshot_id": self.snapshot_id,
            "mechanism": self.mechanism,
            "content_key": content_key,
        })
        proposal = DiscoveryProposal(
            proposal_id=proposal_id,
            mechanism=self.mechanism,
            kind=kind,
            refs=refs_tuple,
            evidence=evidence_copy,
            rank=1,
            snapshot_id=self.snapshot_id,
        )
        if proposal_id in self._seen:
            self.duplicates += 1
            return None
        self._seen.add(proposal_id)
        self._proposals.append(proposal)
        return proposal

    def finish(self) -> _MechanismOutcome:
        proposals = sorted(
            self._proposals,
            key=lambda item: (
                item.kind,
                canonical_json(list(item.refs)),
                canonical_json(item.evidence),
            ),
        )
        total = len(proposals)
        omitted = 0
        if total > self.bounds.max_proposals:
            omitted = total - self.bounds.max_proposals
            proposals = proposals[:self.bounds.max_proposals]
            self._reasons.add("proposal_limit")
        ranked = tuple(
            replace(proposal, rank=index)
            for index, proposal in enumerate(proposals, start=1)
        )
        reasons = _sorted_reasons(self._reasons)
        search = {
            "fuel_used": self.fuel.used - self._fuel_start,
            "considered": self.considered,
            "returned_proposals": len(ranked),
            "omitted_proposals": omitted,
            "duplicate_candidates": self.duplicates,
            "incomplete_reasons": list(reasons),
            "counts": dict(sorted(self._counts.items())),
        }
        return _MechanismOutcome(
            mechanism=self.mechanism,
            proposals=ranked,
            reasons=reasons,
            fuel_used=self.fuel.used - self._fuel_start,
            considered=self.considered,
            omitted=omitted,
            duplicates=self.duplicates,
            search=search,
        )


# ---------------------------------------------------------------------------
# Mechanism 1: structural
# ---------------------------------------------------------------------------


def _leaf_key(leaf: LeafClass) -> tuple[Any, ...]:
    return (leaf.kind, leaf.domain, leaf.shape, leaf.layout)


def _key_doc(key: tuple[Any, ...]) -> dict[str, Any]:
    kind, domain, shape, layout = key
    return {
        "kind": kind,
        "domain": domain,
        "shape": list(shape),
        "layout": layout,
    }


def _structural(collector: _Collector) -> None:
    if not collector.depth_ok(1):
        return
    classes = collector.prepared.classes
    if not classes:
        return

    groups: dict[tuple[Any, ...], list[LeafClass]] = {}
    for leaf in classes:
        groups.setdefault(_leaf_key(leaf), []).append(leaf)

    for key in sorted(groups, key=lambda item: (
        item[0], item[1], item[2], item[3],
    )):
        group = sorted(groups[key], key=_leaf_sort_key)
        if len(group) < 2:
            continue
        if not collector.consume():
            break
        collector.consider()
        collector._count("groups")
        members, truncated = collector.take_fanout(group)
        members = tuple(members)
        if len(members) < 2:
            continue
        evidence = {
            "basis": "same kind/domain/shape/layout",
            "group_key": _key_doc(key),
            "member_count": len(members),
            "total_member_count": len(group),
            "truncated": truncated,
        }
        collector.add(
            "structural_group",
            (_leaf_ref(leaf, "member") for leaf in members),
            evidence,
        )

        pair_count = 0
        pair_fanout_hit = False
        pair_fuel_hit = False
        for left_index, left in enumerate(members):
            for right in members[left_index + 1:]:
                if pair_count >= collector.bounds.max_fanout:
                    pair_fanout_hit = True
                    break
                if not collector.consume():
                    pair_fuel_hit = True
                    break
                collector.consider()
                collector._count("pairs")
                collector.add(
                    "structural_pair",
                    (_leaf_ref(left, "left"), _leaf_ref(right, "right")),
                    {
                        "basis": "same kind/domain/shape/layout",
                        "shared": _key_doc(key),
                        "pair": [left.leaf_id, right.leaf_id],
                    },
                )
                pair_count += 1
            if pair_fanout_hit or pair_fuel_hit:
                break
        if pair_fanout_hit:
            collector._reasons.add("fanout_limit")

    if collector.bounds.max_depth < 2:
        return

    layout_groups: dict[tuple[Any, ...], list[LeafClass]] = {}
    for leaf in classes:
        layout_groups.setdefault(
            (leaf.kind, leaf.domain, leaf.shape), []
        ).append(leaf)

    for key in sorted(layout_groups, key=lambda item: (
        item[0], item[1], item[2],
    )):
        group = sorted(layout_groups[key], key=_leaf_sort_key)
        variants = 0
        for left_index, left in enumerate(group):
            for right in group[left_index + 1:]:
                if left.layout == right.layout:
                    continue
                if variants >= collector.bounds.max_fanout:
                    collector._reasons.add("fanout_limit")
                    return
                if not collector.consume():
                    return
                collector.consider()
                collector._count("layout_variants")
                collector.add(
                    "structural_layout_variant",
                    (_leaf_ref(left, "left"), _leaf_ref(right, "right")),
                    {
                        "basis": "same kind/domain/shape with different layout",
                        "kind": key[0],
                        "domain": key[1],
                        "shape": list(key[2]),
                        "left_layout": left.layout,
                        "right_layout": right.layout,
                    },
                )
                variants += 1


# ---------------------------------------------------------------------------
# Mechanism 2: transformational
# ---------------------------------------------------------------------------


def _transformational(collector: _Collector) -> None:
    if not collector.depth_ok(1):
        return
    classes = collector.prepared.classes
    functions = collector.prepared.functions
    if not classes or not functions:
        return

    for function in functions:
        if function.status not in {"active", "proposed"}:
            continue
        if not function.inputs or not function.output:
            continue
        matches = 0
        for leaf in classes:
            if not collector.consume():
                return
            collector.consider()
            collector._count("leaf_function_pairs")
            matched = []
            for index, endpoint in enumerate(function.inputs):
                ok, reason = _input_matches(endpoint, leaf)
                if ok:
                    matched.append({
                        "index": index,
                        "name": endpoint.get("name"),
                        "endpoint": endpoint,
                    })
                elif reason:
                    collector._count(reason)
            if not matched:
                continue
            if matches >= collector.bounds.max_fanout:
                collector._reasons.add("fanout_limit")
                break
            matches += 1
            collector.add(
                "transform_goal",
                (
                    _leaf_ref(leaf, "source"),
                    _function_ref(function, "transform"),
                ),
                {
                    "transition": "leaf-as-registered-input",
                    "source": _leaf_class_doc(leaf),
                    "matched_inputs": matched,
                    "matched_input_count": len(matched),
                    "required_input_count": len(function.inputs),
                    "target": function.output,
                },
            )


# ---------------------------------------------------------------------------
# Mechanism 3: derivational
# ---------------------------------------------------------------------------


def _derivational(collector: _Collector) -> None:
    if not collector.depth_ok(1):
        return
    functions = tuple(
        function for function in collector.prepared.functions
        if function.status in {"active", "proposed"}
        and function.inputs and function.output
    )
    if len(functions) < 2:
        return

    unary = tuple(
        function for function in functions if len(function.inputs) == 1
    )
    if not unary:
        return

    def expand(chain: tuple[_FunctionView, ...],
               opened: list[int]) -> None:
        last = chain[-1]
        if len(chain) - 1 >= collector.bounds.max_depth:
            return
        for consumer in unary:
            if consumer in chain:
                continue
            if not collector.consume():
                return
            collector.consider()
            collector._count("composition_edges")
            ok, reason = _output_satisfies_input(
                last.output, consumer.inputs[0],
            )
            if not ok:
                collector._count(reason)
                continue
            if opened[0] >= collector.bounds.max_fanout:
                collector._reasons.add("fanout_limit")
                return
            opened[0] += 1
            next_chain = chain + (consumer,)
            steps = []
            for left, right in zip(next_chain, next_chain[1:]):
                steps.append({
                    "from": _function_ref(left),
                    "to": _function_ref(right),
                    "output": left.output,
                    "input": right.inputs[0],
                    "input_index": 0,
                })
            collector.add(
                "composition",
                tuple(
                    _function_ref(function, f"component{index}")
                    for index, function in enumerate(next_chain)
                ),
                {
                    "transition": "left-to-right-contract-composition",
                    "components": [
                        _function_ref(function) for function in next_chain
                    ],
                    "steps": steps,
                    "depth": len(next_chain) - 1,
                    "output": consumer.output,
                },
            )
            expand(next_chain, opened)

    for source in functions:
        if not collector.consume():
            return
        collector.consider()
        collector._count("composition_sources")
        expand((source,), [0])


# ---------------------------------------------------------------------------
# Mechanism 4: relational
# ---------------------------------------------------------------------------


def _auto_relation_schema(key: tuple[Any, ...]) -> RelationSchema:
    suffix = digest_object(_key_doc(key))[:16]
    return RelationSchema(
        schema_id=f"math.discovery.relation.{suffix}",
        version=1,
        ordered=True,
        duplicate_policy="forbid",
        directed=False,
        weight_domain="none",
        roles=(RoleSpec("member", min_count=2, required=True),),
        min_arity=2,
        max_arity=MAX_HYPEREDGE_MEMBERS,
        constraints=("unique_leaf_ids", "unique_member_refs"),
        allow_unroled=False,
        provenance={
            "producer": DISCOVERY_ID,
            "basis": "structurally compatible discovery group",
            "group_key": _key_doc(key),
        },
    )


def _schema_for_group(key: tuple[Any, ...], members: tuple[LeafClass, ...],
                      schemas: tuple[RelationSchema, ...]) -> RelationSchema:
    requested = {
        leaf.relation_schema for leaf in members if leaf.relation_schema
    }
    if len(requested) == 1:
        schema_id = next(iter(requested))
        for schema in schemas:
            if schema.schema_id == schema_id and schema.accepts_role("member"):
                return schema
    return _auto_relation_schema(key)


def _relational(collector: _Collector) -> None:
    if not collector.depth_ok(1):
        return
    classes = collector.prepared.classes
    if not classes:
        return

    groups: dict[tuple[Any, ...], list[LeafClass]] = {}
    for leaf in classes:
        groups.setdefault(_leaf_key(leaf), []).append(leaf)

    for key in sorted(groups, key=lambda item: (
        item[0], item[1], item[2], item[3],
    )):
        group = sorted(groups[key], key=_leaf_sort_key)
        if len(group) < 2:
            continue
        if not collector.consume():
            break
        collector.consider()
        collector._count("relation_groups")
        members, truncated = collector.take_fanout(group)
        members = tuple(members)
        if len(members) < 2:
            continue
        schema = _schema_for_group(key, members, collector.prepared.relation_schemas)
        relation_members = tuple(
            RelationMember(leaf.leaf_id, version=leaf.version, role="member")
            for leaf in members
        )
        try:
            relation_id = relation_id_for(
                schema, relation_members, prefix="nml:U0:relation:",
            )
            relation = RelationRecord(
                relation_id=relation_id,
                schema=schema,
                version=1,
                members=relation_members,
                provenance={
                    "producer": DISCOVERY_ID,
                    "basis": "structurally compatible discovery group",
                },
            )
        except RelationError as exc:
            collector._count("invalid_relation_candidate")
            collector._reasons.add("relation_candidate_rejected")
            collector._count(f"relation_reject:{exc.code}")
            continue
        collector.add(
            "relation_candidate",
            tuple(_leaf_ref(leaf, "member") for leaf in members),
            {
                "basis": "compatible leaves form a typed hyperedge candidate",
                "schema": schema.to_dict(),
                "schema_digest": schema.digest(),
                "members": [leaf.to_dict() for leaf in relation.members],
                "member_count": len(relation.members),
                "total_member_count": len(group),
                "truncated": truncated,
                "relation": relation.to_dict(),
                "relation_digest": relation.digest(),
            },
        )


# ---------------------------------------------------------------------------
# Mechanism 5: operational
# ---------------------------------------------------------------------------


def _implementation_sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    workspace = row.get("workspace_words")
    if isinstance(workspace, bool) or not isinstance(workspace, int):
        workspace_key = (1, 0)
    else:
        workspace_key = (0, workspace)
    return (
        workspace_key,
        str(row.get("kernel_id", "")),
        str(row.get("implementation_digest", "")),
    )


def _implementation_view(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: _canonical_copy(row[key], f"implementation.{key}")
        for key in _IMPLEMENTATION_KEYS
        if key in row
    }


def _operational(collector: _Collector) -> None:
    if not collector.depth_ok(1):
        return
    if collector.bounds.max_fanout == 0:
        collector._reasons.add("fanout_limit")
        return
    functions = collector.prepared.functions
    if not functions:
        return

    for function in functions:
        if not collector.consume():
            return
        collector.consider()
        collector._count("functions_considered")
        if not function.implementations and not function.numerical_policy:
            collector._count("functions_without_operational_metadata")
            continue

        implementations = tuple(sorted(
            function.implementations, key=_implementation_sort_key,
        ))
        selected, truncated = collector.take_fanout(implementations)
        try:
            rows = [_implementation_view(row) for row in selected]
        except DiscoveryError:
            collector._count("non_canonical_implementation_metadata")
            collector._reasons.add("operational_metadata_rejected")
            continue
        preferred = rows[0] if rows else None

        deterministic = function.numerical_policy.get("deterministic")
        if deterministic is True:
            cache_policy = "cache_eligible"
        elif deterministic is False:
            cache_policy = "recompute_only"
        else:
            cache_policy = "policy_undeclared"

        capability_classes = sorted({
            str(row.get("capability_class"))
            for row in function.implementations
            if row.get("capability_class") is not None
        })
        kernel_ids = sorted({
            str(row.get("kernel_id"))
            for row in function.implementations
            if row.get("kernel_id") is not None
        })
        workspace_policy = None
        if preferred is not None:
            workspace_policy = {
                "kernel_id": preferred.get("kernel_id"),
                "workspace_words": preferred.get("workspace_words"),
            }
        try:
            collector.add(
                "operational_policy",
                (
                    _function_ref(function, "function"),
                    *(
                        {
                            "ref_type": "implementation",
                            "kernel_id": row.get("kernel_id"),
                            "role": "implementation",
                        }
                        for row in rows
                    ),
                ),
                {
                    "basis": "function implementation and numerical-policy metadata",
                    "function_id": function.function_id,
                    "version": function.version,
                    "contract_digest": function.contract_digest,
                    "lifecycle_status": function.status,
                    "implementation_count": len(function.implementations),
                    "implementations": rows,
                    "truncated": truncated,
                    "preferred_implementation": preferred,
                    "workspace_policy": workspace_policy,
                    "capability_classes": capability_classes,
                    "kernel_ids": kernel_ids,
                    "precision": function.numerical_policy.get("precision"),
                    "deterministic": deterministic,
                    "cache_policy": cache_policy,
                    "numerical_policy": function.numerical_policy,
                },
            )
        except DiscoveryError:
            collector._count("non_canonical_operational_metadata")
            collector._reasons.add("operational_metadata_rejected")


_MECHANISM_RUNNERS = {
    "structural": _structural,
    "transformational": _transformational,
    "derivational": _derivational,
    "relational": _relational,
    "operational": _operational,
}


def _mechanism_search(outcome: _MechanismOutcome) -> dict[str, Any]:
    search = dict(outcome.search)
    search["mechanism"] = outcome.mechanism
    return search


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _discover(request: DiscoveryRequest,
              mechanisms: tuple[str, ...]) -> DiscoveryResult:
    if not isinstance(request, DiscoveryRequest):
        raise DiscoveryError("request must be a DiscoveryRequest")
    prepared = _prepare(request)
    snapshot_id = request.snapshot_id or prepared.derived_snapshot_id
    fuel = _Fuel(request.bounds.fuel)
    outcomes: list[_MechanismOutcome] = []

    for mechanism in mechanisms:
        collector = _Collector(
            mechanism, request, prepared, fuel, snapshot_id,
        )
        _MECHANISM_RUNNERS[mechanism](collector)
        outcomes.append(collector.finish())

    seen_keys: set[str] = set()
    combined: list[DiscoveryProposal] = []
    cross_duplicates = 0
    reasons: list[str] = []
    omitted = 0
    for outcome in outcomes:
        reasons.extend(outcome.reasons)
        omitted += outcome.omitted
        for proposal in outcome.proposals:
            if proposal.content_key in seen_keys:
                cross_duplicates += 1
                continue
            seen_keys.add(proposal.content_key)
            combined.append(proposal)

    combined.sort(key=lambda item: (
        _MECHANISM_ORDER[item.mechanism],
        item.kind,
        canonical_json(list(item.refs)),
        canonical_json(item.evidence),
    ))
    total_candidates = len(combined)
    if total_candidates > request.bounds.max_proposals:
        omitted += total_candidates - request.bounds.max_proposals
        combined = combined[:request.bounds.max_proposals]
        reasons.append("proposal_limit")

    ranked = tuple(
        replace(proposal, rank=index)
        for index, proposal in enumerate(combined, start=1)
    )
    search = {
        "ignored_leaves": [_plain(row) for row in prepared.ignored_leaves],
        "ignored_functions": [_plain(row) for row in prepared.ignored_functions],
        "ignored_relations": [_plain(row) for row in prepared.ignored_relations],
        "mechanisms": {
            outcome.mechanism: _mechanism_search(outcome)
            for outcome in outcomes
        },
        "cross_mechanism_duplicates": cross_duplicates,
        "dedupe": "proposal-content-digest",
        "ordering": ["mechanism", "kind", "refs", "evidence"],
    }
    return DiscoveryResult(
        requested_mechanism=request.mechanism,
        mechanisms=tuple(mechanisms),
        snapshot_id=snapshot_id,
        derived_snapshot_id=prepared.derived_snapshot_id,
        objective=request.objective,
        proposals=ranked,
        bounds=request.bounds,
        incomplete=bool(reasons),
        incomplete_reasons=_sorted_reasons(reasons),
        fuel_used=fuel.used,
        considered=sum(outcome.considered for outcome in outcomes),
        omitted_proposal_count=omitted,
        search=search,
    )


def propose_structural(request: DiscoveryRequest) -> DiscoveryResult:
    """Run only the structural mechanism."""
    return _discover(request, ("structural",))


def propose_transformational(request: DiscoveryRequest) -> DiscoveryResult:
    """Run only the transformational mechanism."""
    return _discover(request, ("transformational",))


def propose_derivational(request: DiscoveryRequest) -> DiscoveryResult:
    """Run only the derivational mechanism."""
    return _discover(request, ("derivational",))


def propose_relational(request: DiscoveryRequest) -> DiscoveryResult:
    """Run only the relational mechanism."""
    return _discover(request, ("relational",))


def propose_operational(request: DiscoveryRequest) -> DiscoveryResult:
    """Run only the operational mechanism."""
    return _discover(request, ("operational",))


def propose_all(request: DiscoveryRequest) -> DiscoveryResult:
    """Run all five mechanisms under one shared fuel/proposal budget."""
    return _discover(request, MECHANISMS)


def propose(mechanism: str | DiscoveryRequest,
            request: DiscoveryRequest | None = None) -> DiscoveryResult:
    """Dispatch to one mechanism, or to :func:`propose_all` for ``"all"``.

    ``propose(request)`` uses ``request.mechanism``; ``propose(name, request)``
    selects a mechanism explicitly.
    """
    if isinstance(mechanism, DiscoveryRequest):
        if request is not None:
            raise DiscoveryError(
                "pass either a request or a mechanism name plus a request"
            )
        selected = mechanism
        if selected.mechanism == "all":
            return propose_all(selected)
        return _discover(selected, (selected.mechanism,))
    if request is None:
        raise DiscoveryError("a DiscoveryRequest is required")
    name = _require_text(mechanism, "mechanism", maximum=64).lower()
    if name == "all":
        return propose_all(request)
    if name not in _MECHANISM_RUNNERS:
        raise DiscoveryError(
            f"mechanism must be 'all' or one of {', '.join(MECHANISMS)}"
        )
    return _discover(request, (name,))


class MathDiscovery:
    """Reusable facade over a fixed request."""

    def __init__(self, request: DiscoveryRequest) -> None:
        if not isinstance(request, DiscoveryRequest):
            raise DiscoveryError("request must be a DiscoveryRequest")
        self.request = request

    def structural(self) -> DiscoveryResult:
        return propose_structural(self.request)

    def transformational(self) -> DiscoveryResult:
        return propose_transformational(self.request)

    def derivational(self) -> DiscoveryResult:
        return propose_derivational(self.request)

    def relational(self) -> DiscoveryResult:
        return propose_relational(self.request)

    def operational(self) -> DiscoveryResult:
        return propose_operational(self.request)

    def propose_all(self) -> DiscoveryResult:
        return propose_all(self.request)

    def propose(self) -> DiscoveryResult:
        return propose_all(self.request)


__all__ = [
    "DISCOVERY_ID",
    "DiscoveryBounds",
    "DiscoveryError",
    "DiscoveryProposal",
    "DiscoveryRequest",
    "DiscoveryResult",
    "MECHANISMS",
    "MathDiscovery",
    "PROPOSAL_SCHEMA",
    "REQUEST_SCHEMA",
    "RESULT_SCHEMA",
    "propose",
    "propose_all",
    "propose_derivational",
    "propose_operational",
    "propose_relational",
    "propose_structural",
    "propose_transformational",
]
