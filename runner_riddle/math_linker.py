"""Exploratory ``::`` mathematical linker (GAME_PLAN_::, P4).

This module is a pure, deterministic *candidate generator*.  It parses a
``LinkQuery`` (mode ``conjoin`` or ``transform``), resolves pinned math-leaf
references, classifies their type/domain/shape/layout, snapshots the supplied
function/rule/capability context, and returns candidate transforms.

It deliberately does **not**:

* execute or evaluate mathematics;
* import an execution engine or service-layer authority;
* produce an admission/verdict or any other authorization;
* persist leaves, candidates, or snapshots.

The candidate set is evidence for a separate validity engine.  A candidate is
never an execution permit.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import inspect
import math
import re
from typing import Any, ClassVar, Iterable, Mapping, Sequence

from .math_objects import (
    LEAF_KINDS,
    LEAF_SCHEMA,
    PROOF_STATUSES,
    MathCandidate,
    MathFunction,
    MathLeaf,
    MathObjectError,
    MathRule,
    canonical_json,
    candidate_id_for,
    digest_object,
)

LINKER_ID = "math.linker.v1"
CANDIDATE_SET_SCHEMA = "nanrouter.math-candidate-set.v1"
LINK_MODES = frozenset({"conjoin", "transform"})
PROVED_COMMUTATIVE_STATUSES = frozenset({"axiom", "proven", "verified"})
_ABSENCE_KINDS = ("undefined", "null", "void", "unknown", "error")
_FUNCTION_ID_RE = re.compile(r"^math\.[a-z0-9][a-z0-9_.-]{0,120}$")
_LEAF_ID_RE = re.compile(r"^nml:[A-Za-z0-9_.:-]{1,180}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_HW_RE = re.compile(r"^HW\d*:", re.IGNORECASE)
_RAW_OFFSET_RE = re.compile(r"^[+-]?(?:0x[0-9a-f]+|\d+)(?::\d+)*$", re.IGNORECASE)
_URI_VERSION_RE = re.compile(r"^(?P<identifier>.+)@v(?P<version>\d+)$")
_MODE_PREFIX_RE = re.compile(r"^(?P<mode>conjoin|transform)\b\s*[:\-]?\s*", re.IGNORECASE)
_CONJOIN_SPLIT_RE = re.compile(r"\s*::\s*")

_DOMAIN_NAMES = frozenset({
    "real", "integer", "rational", "complex", "boolean", "bool", "natural",
    "finite", "exact", "symbolic",
})
_DOMAIN_WILDCARDS = frozenset({"any", "*", "numeric", "number", "unspecified", "unknown"})
_KIND_WILDCARDS = frozenset({"any", "*", "object", "leaf"})
_PRECISION_ALIASES = {
    "f16": "float16", "float16": "float16", "half": "float16",
    "f32": "float32", "float32": "float32", "single": "float32",
    "f64": "float64", "float64": "float64", "double": "float64",
}
_SHAPE_RULE_ALIASES = {
    "equal": "equal", "same": "equal", "same_shape": "equal",
    "shape_equal": "equal", "match": "equal",
    "operand0": "operand0", "input0": "operand0", "left": "operand0",
    "same_as_operand0": "operand0",
    "operand1": "operand1", "input1": "operand1", "right": "operand1",
    "same_as_operand1": "operand1",
    "operand2": "operand2", "input2": "operand2",
    "rows": "rows", "matrix_rows": "rows", "left_rows": "rows",
    "cols": "cols", "columns": "cols", "matrix_cols": "cols",
    "right_cols": "cols",
    "free": "free", "any": "free", "broadcast": "free", "none": "free",
}
_KIND_ALIASES = {
    "vec": "vector", "vectors": "vector",
    "mat": "matrix", "matrices": "matrix",
    "num": "numeric", "number": "numeric",
}


class LinkError(ValueError):
    """A rejected linker query or context, with a machine-readable code."""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        self.message = message or code
        text = code if not message else f"{code}: {message}"
        super().__init__(text)


@dataclass(frozen=True)
class MathRef:
    """A pinned mathematical leaf reference (never a route or raw offset)."""

    leaf_id: str
    version: int
    content_digest: str | None = None
    via_alias: str | None = None

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def as_dict(self) -> dict[str, Any]:
        return self.to_dict()

    def to_dict(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "leaf_id": self.leaf_id,
            "version": self.version,
        }
        if self.content_digest is not None:
            document["content_digest"] = self.content_digest
        if self.via_alias is not None:
            document["via_alias"] = self.via_alias
        return document


@dataclass(frozen=True)
class LeafClass:
    """Resolved static classification of a leaf; no content is evaluated."""

    leaf_id: str
    version: int
    kind: str
    domain: str
    shape: tuple[int, ...]
    shape_declared: bool
    layout: str
    precision: str
    element: str
    type_name: str
    content_digest: str | None
    leaf_digest: str
    relation_schema: str | None = None

    @property
    def shape_list(self) -> list[int]:
        return list(self.shape)

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def as_dict(self) -> dict[str, Any]:
        return self.to_dict()

    def to_dict(self) -> dict[str, Any]:
        return {
            "leaf_id": self.leaf_id,
            "version": self.version,
            "kind": self.kind,
            "domain": self.domain,
            "shape": list(self.shape),
            "shape_declared": self.shape_declared,
            "layout": self.layout,
            "precision": self.precision,
            "element": self.element,
            "type_name": self.type_name,
            "content_digest": self.content_digest,
            "leaf_digest": self.leaf_digest,
            "relation_schema": self.relation_schema,
        }


@dataclass(frozen=True)
class TransformGoal:
    """Optional static target for ``transform`` mode."""

    kind: str | None = None
    domain: str | None = None
    shape: tuple[int, ...] | None = None
    layout: str | None = None
    precision: str | None = None
    element: str | None = None

    def __post_init__(self) -> None:
        if self.kind is not None:
            kind = _text(self.kind, "goal.kind").lower()
            if kind not in LEAF_KINDS and kind not in _KIND_WILDCARDS and kind != "numeric":
                raise LinkError("invalid_goal", f"unknown goal kind: {kind!r}")
            object.__setattr__(self, "kind", kind)
        if self.domain is not None:
            object.__setattr__(self, "domain", _text(self.domain, "goal.domain").lower())
        if self.shape is not None:
            object.__setattr__(self, "shape", _parse_shape(self.shape, "goal.shape"))
        if self.layout is not None:
            object.__setattr__(self, "layout", _text(self.layout, "goal.layout").lower())
        if self.precision is not None:
            object.__setattr__(self, "precision", _text(self.precision, "goal.precision").lower())
        if self.element is not None:
            object.__setattr__(self, "element", _text(self.element, "goal.element").lower())

    @classmethod
    def from_value(cls, value: Any) -> "TransformGoal | None":
        if value is None:
            return None
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls(kind=value)
        if isinstance(value, Mapping):
            return cls(
                kind=value.get("kind") or value.get("type") or value.get("name"),
                domain=value.get("domain"),
                shape=value.get("shape"),
                layout=value.get("layout"),
                precision=value.get("precision"),
                element=value.get("element"),
            )
        raise LinkError("invalid_goal", "goal must be a kind, mapping, or TransformGoal")

    def matches(self, output: Mapping[str, Any]) -> bool:
        if self.kind is not None and not _kind_compatible(self.kind, str(output.get("kind", "unknown"))):
            return False
        if self.domain is not None and not _domain_compatible(self.domain, str(output.get("domain", "unknown"))):
            return False
        if self.shape is not None:
            shape = output.get("shape")
            if not isinstance(shape, (list, tuple)) or tuple(shape) != self.shape:
                return False
        if self.layout is not None and str(output.get("layout", "unspecified")).lower() != self.layout:
            return False
        if self.precision is not None:
            expected = _precision_key(self.precision)
            actual = _precision_key(str(output.get("precision", "unspecified")))
            if actual not in {"unspecified", expected}:
                return False
        if self.element is not None and str(output.get("element", "unknown")).lower() != self.element:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "domain": self.domain,
            "shape": None if self.shape is None else list(self.shape),
            "layout": self.layout,
            "precision": self.precision,
            "element": self.element,
        }


@dataclass(frozen=True)
class LinkBounds:
    """Static exploration bounds for one linker call."""

    max_depth: int = 1
    max_fanout: int = 64
    fuel: int = 4096

    def __post_init__(self) -> None:
        for name in ("max_depth", "max_fanout", "fuel"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise LinkError("invalid_bounds", f"{name} must be an integer >= 0")

    @classmethod
    def from_value(cls, value: Any) -> "LinkBounds":
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        if isinstance(value, Mapping):
            return cls(
                max_depth=value.get("max_depth", 1),
                max_fanout=value.get("max_fanout", 64),
                fuel=value.get("fuel", 4096),
            )
        raise LinkError("invalid_bounds", "bounds must be a mapping or LinkBounds")

    def to_dict(self) -> dict[str, int]:
        return {
            "max_depth": self.max_depth,
            "max_fanout": self.max_fanout,
            "fuel": self.fuel,
        }


@dataclass(frozen=True)
class LinkQuery:
    """Parsed ``::`` query.  Operands are refs, never bare routes."""

    operands: tuple[Any, ...]
    mode: str = "conjoin"
    objective: str = "association"
    max_candidates: int = 8
    goal: TransformGoal | None = None
    bounds: LinkBounds | None = None

    def __post_init__(self) -> None:
        operands = _operand_tuple(self.operands)
        object.__setattr__(self, "operands", operands)
        mode = _text(self.mode, "mode").lower()
        if mode not in LINK_MODES:
            raise LinkError("invalid_mode", f"mode must be one of {sorted(LINK_MODES)}")
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "objective", _text(self.objective, "objective"))
        if isinstance(self.max_candidates, bool) or not isinstance(self.max_candidates, int):
            raise LinkError("invalid_candidate_limit", "max_candidates must be an integer >= 0")
        if self.max_candidates < 0:
            raise LinkError("invalid_candidate_limit", "max_candidates must be an integer >= 0")
        object.__setattr__(self, "goal", TransformGoal.from_value(self.goal))
        object.__setattr__(self, "bounds", None if self.bounds is None else LinkBounds.from_value(self.bounds))
        minimum = 2 if mode == "conjoin" else 1
        if len(operands) < minimum:
            raise LinkError(
                "invalid_query",
                f"{mode} mode requires at least {minimum} operand(s)",
            )

    @classmethod
    def from_text(cls, text: str, **kwargs: Any) -> "LinkQuery":
        """Alias for :meth:`parse`."""
        return cls.parse(text, **kwargs)

    @classmethod
    def parse(
        cls,
        text: str,
        *,
        mode: str | None = None,
        objective: str = "association",
        max_candidates: int = 8,
        goal: Any = None,
        bounds: Any = None,
    ) -> "LinkQuery":
        """Parse ``A :: B`` with an optional ``conjoin``/``transform`` prefix."""
        if not isinstance(text, str) or not text.strip():
            raise LinkError("invalid_query", "query text must be a non-empty string")
        if "nan://" in text.lower():
            raise LinkError(
                "address_context_mismatch",
                "nan:// routes are address grammar, not :: operands",
            )
        stripped = text.strip()
        prefix = _MODE_PREFIX_RE.match(stripped)
        prefix_mode = None
        if prefix is not None:
            prefix_mode = prefix.group("mode").lower()
            stripped = stripped[prefix.end():].strip()
        if mode is not None and prefix_mode is not None and mode.lower() != prefix_mode:
            raise LinkError("mode_conflict", "query prefix and explicit mode disagree")
        chosen_mode = prefix_mode or (mode.lower() if mode is not None else "conjoin")
        pieces = _CONJOIN_SPLIT_RE.split(stripped)
        if any(not piece.strip() for piece in pieces):
            raise LinkError("invalid_query", "empty operand in :: query")
        return cls(
            operands=tuple(piece.strip() for piece in pieces),
            mode=chosen_mode,
            objective=objective,
            max_candidates=max_candidates,
            goal=goal,
            bounds=bounds,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "operands": [_json_operand(operand) for operand in self.operands],
            "objective": self.objective,
            "max_candidates": self.max_candidates,
            "goal": None if self.goal is None else self.goal.to_dict(),
            "bounds": None if self.bounds is None else self.bounds.to_dict(),
        }


@dataclass(frozen=True)
class LinkSnapshot:
    """Static function/rule/version/capability context of one proposal."""

    snapshot_id: str
    derived_snapshot_id: str
    function_digests: tuple[dict[str, Any], ...]
    function_snapshot_digest: str
    rule_digests: tuple[dict[str, Any], ...]
    rule_snapshot_digest: str
    capability_digest: str
    declared_capabilities: tuple[dict[str, Any], ...] = ()
    implementation_capabilities: tuple[dict[str, Any], ...] = ()

    @property
    def functions(self) -> tuple[dict[str, Any], ...]:
        return self.function_digests

    @property
    def rules(self) -> tuple[dict[str, Any], ...]:
        return self.rule_digests

    @property
    def function_snapshot_id(self) -> str:
        return self.function_snapshot_digest

    @property
    def rule_snapshot_id(self) -> str:
        return self.rule_snapshot_digest

    @property
    def capability_set_digest(self) -> str:
        return self.capability_digest

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "derived_snapshot_id": self.derived_snapshot_id,
            "function_digests": [dict(row) for row in self.function_digests],
            "function_snapshot_digest": self.function_snapshot_digest,
            "rule_digests": [dict(row) for row in self.rule_digests],
            "rule_snapshot_digest": self.rule_snapshot_digest,
            "capability_digest": self.capability_digest,
            "declared_capabilities": [dict(row) for row in self.declared_capabilities],
            "implementation_capabilities": [dict(row) for row in self.implementation_capabilities],
        }


class _TypedNullLeaf(MathLeaf):
    """A typed null leaf with read-only mapping-style field access."""

    @property
    def reason(self) -> str:
        return str(self.metadata.get("reason", ""))

    def __getitem__(self, key: str) -> Any:
        if key == "reason":
            return self.reason
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        if key == "reason":
            return self.reason
        return self.to_dict().get(key, default)


@dataclass(frozen=True)
class LinkResult:
    """Deterministic candidate set plus typed absence and bounded-search evidence."""

    mode: str
    snapshot: LinkSnapshot
    inputs: tuple[dict[str, Any], ...]
    candidates: tuple[MathCandidate, ...]
    functions: tuple[dict[str, Any], ...]
    rejected: tuple[dict[str, Any], ...]
    objective: str
    goal: TransformGoal | None = None
    null: MathLeaf | None = None
    truncated: bool = False
    incomplete: bool = False
    incomplete_reasons: tuple[str, ...] = ()
    omitted_candidate_count: int = 0
    search: dict[str, Any] = field(default_factory=dict)

    SCHEMA: ClassVar[str] = CANDIDATE_SET_SCHEMA

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    @property
    def items(self) -> tuple[MathCandidate, ...]:
        """Alias matching the plan's ``candidates.items`` seam."""
        return self.candidates

    @property
    def schema(self) -> str:
        return self.SCHEMA

    @property
    def candidate_ids(self) -> tuple[str, ...]:
        return tuple(candidate.candidate_id for candidate in self.candidates)

    @property
    def omitted(self) -> int:
        return self.omitted_candidate_count

    @property
    def null_leaf(self) -> MathLeaf | None:
        return self.null

    @property
    def null_record(self) -> dict[str, Any] | None:
        return None if self.null is None else self.null.to_dict()

    @property
    def null_reason(self) -> str | None:
        if self.null is None:
            return None
        return str(self.null.metadata.get("reason", ""))

    @property
    def snapshot_id(self) -> str:
        return self.snapshot.snapshot_id

    @property
    def function_snapshot_id(self) -> str:
        return self.snapshot.function_snapshot_digest

    @property
    def rule_snapshot_id(self) -> str:
        return self.snapshot.rule_snapshot_digest

    @property
    def capability_set_digest(self) -> str:
        return self.snapshot.capability_digest

    @property
    def authorized(self) -> bool:
        return False

    def digest(self) -> str:
        return digest_object(self.to_dict())

    @property
    def candidate_set_id(self) -> str:
        return "cset:" + self.digest()

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def as_dict(self) -> dict[str, Any]:
        return self.to_dict()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "linker_id": LINKER_ID,
            "mode": self.mode,
            "snapshot_id": self.snapshot.snapshot_id,
            "snapshot": self.snapshot.to_dict(),
            "objective": self.objective,
            "goal": None if self.goal is None else self.goal.to_dict(),
            "inputs": [dict(row) for row in self.inputs],
            "functions": [dict(row) for row in self.functions],
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "candidate_count": len(self.candidates),
            "rejected": [dict(row) for row in self.rejected],
            "null": None if self.null is None else self.null.to_dict(),
            "truncated": self.truncated,
            "incomplete": self.incomplete,
            "incomplete_reasons": list(self.incomplete_reasons),
            "omitted_candidate_count": self.omitted_candidate_count,
            "search": dict(self.search),
            "authorization": "not_granted",
            "execution": "not_performed",
        }


@dataclass(frozen=True)
class _TypeSpec:
    kind: str | None = None
    domain: str | None = None
    shape: tuple[int | None, ...] | None = None
    shape_rule: str | None = None
    layout: str | None = None
    precision: str | None = None
    element: str | None = None
    wildcard: bool = False

    @classmethod
    def from_value(cls, value: Any) -> "_TypeSpec":
        return _type_spec_from_value(value)


@dataclass(frozen=True)
class _FunctionSpec:
    function_id: str
    version: int
    status: str
    proof_status: str
    signature: dict[str, Any]
    semantics: dict[str, Any]
    implementations: tuple[dict[str, Any], ...]
    input_specs: tuple[_TypeSpec, ...]
    output_spec: _TypeSpec
    commutative: bool
    commutative_proved: bool
    contract_digest: str
    capability_digest: str
    shape_policy: str | None
    cross_domain: bool
    priority: int
    cost: int


@dataclass(frozen=True)
class _Match:
    reason: str | None = None
    detail: str = ""
    features: int = 0


@dataclass(frozen=True)
class _CandidateRecord:
    candidate: MathCandidate
    score: int
    match: _Match
    spec: _FunctionSpec
    output: dict[str, Any]
    canonical_order: bool
    goal_match: bool


# ---------------------------------------------------------------------------
# Reference parsing and resolution
# ---------------------------------------------------------------------------


def parse_ref(value: Any, *, aliases: Mapping[str, Any] | None = None,
              _depth: int = 0) -> MathRef:
    """Parse a pinned leaf reference, rejecting routes/offsets/heads/versions."""
    if _depth > 8:
        raise LinkError("alias_cycle", "alias expansion exceeded its bounded depth")
    if isinstance(value, MathRef):
        valid = _validate_leaf_id(value.leaf_id)
        if not valid:
            raise LinkError("invalid_reference", value.leaf_id)
        if isinstance(value.version, bool) or not isinstance(value.version, int) or value.version < 1:
            raise LinkError("unpinned_version", "leaf references require version >= 1")
        digest = _optional_digest(value.content_digest, "content_digest")
        return replace(value, content_digest=digest)
    if isinstance(value, MathLeaf):
        return MathRef(value.leaf_id, value.version, value.content_digest)

    if isinstance(value, Mapping):
        if isinstance(value.get("leaf"), MathLeaf):
            leaf = value["leaf"]
            return _validate_ref_version(MathRef(leaf.leaf_id, leaf.version, leaf.content_digest), value)
        if value.get("schema") == LEAF_SCHEMA and "kind" in value:
            try:
                leaf = _leaf_from_mapping(value)
            except LinkError:
                raise
            return MathRef(leaf.leaf_id, leaf.version, leaf.content_digest)
        if isinstance(value.get("ref"), (str, MathRef, MathLeaf)):
            return parse_ref(value["ref"], aliases=aliases, _depth=_depth + 1)
        if "leaf_id" not in value and "id" not in value and (
            "offset" in value or "address_offset" in value
        ):
            raise LinkError("raw_offset", "numeric offsets are not mathematical leaves")
        leaf_id = value.get("leaf_id", value.get("id"))
        if isinstance(leaf_id, bool) or isinstance(leaf_id, (int, float)):
            raise LinkError("raw_offset", "numeric offsets are not mathematical leaves")
        if isinstance(leaf_id, str):
            lowered = leaf_id.strip().lower()
            if lowered.startswith("nan://"):
                raise LinkError(
                    "address_context_mismatch",
                    "nan:// is a routing grammar, not a math leaf identity",
                )
            if _HW_RE.match(leaf_id.strip()):
                raise LinkError(
                    "unbound_head_reference",
                    "HW0:* is a hierarchy head unless an explicit alias binds it",
                )
            if _RAW_OFFSET_RE.fullmatch(leaf_id.strip()):
                raise LinkError("raw_offset", "numeric offsets are not mathematical leaves")
        if not isinstance(leaf_id, str) or not _validate_leaf_id(leaf_id):
            raise LinkError("invalid_reference", "leaf_id must be an nml: identifier")
        if "version" not in value or value.get("version") is None:
            raise LinkError("unpinned_version", f"{leaf_id} reference has no pinned version")
        version = _reference_version(value.get("version"), leaf_id)
        digest = _optional_digest(value.get("content_digest", value.get("digest")), "content_digest")
        return MathRef(leaf_id.strip(), version, digest)

    if isinstance(value, bool) or isinstance(value, (int, float)):
        raise LinkError("raw_offset", "numeric offsets are not mathematical leaves")
    if not isinstance(value, str):
        raise LinkError("invalid_reference", "operand must be a MathLeaf, ref mapping, or string")
    text = value.strip()
    if not text:
        raise LinkError("invalid_reference", "empty reference")
    lowered = text.lower()
    if lowered.startswith("nan://"):
        raise LinkError(
            "address_context_mismatch",
            "nan:// is a routing grammar; use a pinned math leaf reference",
        )
    if aliases is not None:
        if text in aliases:
            bound = parse_ref(aliases[text], aliases=aliases, _depth=_depth + 1)
            return replace(bound, via_alias=text)
        if text.upper() in aliases:
            bound = parse_ref(aliases[text.upper()], aliases=aliases, _depth=_depth + 1)
            return replace(bound, via_alias=text)

    if lowered.startswith("math://"):
        return _parse_math_uri(text)
    if _HW_RE.match(text):
        raise LinkError(
            "unbound_head_reference",
            "HW0:* is a hierarchy head unless an explicit alias binds it to a leaf",
        )
    if _RAW_OFFSET_RE.fullmatch(text):
        raise LinkError("raw_offset", "raw numeric offsets are not mathematical leaves")
    if lowered.startswith("nml:") or lowered.startswith("math."):
        return _parse_plain_ref(text)
    raise LinkError("invalid_reference", f"not a mathematical leaf reference: {text!r}")


def _parse_math_uri(text: str) -> MathRef:
    body = text[7:]
    for marker, kind in (
        ("/leaf/", "leaf"),
        ("/function/", "function"),
        ("/rule/", "rule"),
        ("/relation/", "relation"),
    ):
        index = body.rfind(marker)
        if index >= 0:
            if kind != "leaf":
                raise LinkError("reference_kind", ":: operands must be math leaf references")
            identifier = body[index + len(marker):]
            if not identifier or any(mark in identifier for mark in "/?#"):
                raise LinkError("invalid_reference", "malformed math:// leaf URI")
            match = _URI_VERSION_RE.fullmatch(identifier)
            if match is None:
                if "@v" in identifier:
                    raise LinkError("invalid_version", "malformed @v<version> pin")
                raise LinkError("unpinned_version", "math:// leaf references require @v<version>")
            leaf_id = match.group("identifier")
            if not _validate_leaf_id(leaf_id):
                raise LinkError("invalid_reference", "math:// leaf identifier must be nml:")
            return MathRef(leaf_id, _reference_version(int(match.group("version")), leaf_id))
    raise LinkError("invalid_reference", "math:// URI has no /leaf/ reference")


def _parse_plain_ref(text: str) -> MathRef:
    if text.lower().startswith("math."):
        raise LinkError("reference_kind", "function/rule IDs are not leaf operands")
    marker = text.rfind("@v")
    if marker < 0:
        raise LinkError("unpinned_version", "leaf references require an explicit @v<version>")
    leaf_id = text[:marker]
    version_text = text[marker + 2:]
    if not leaf_id or not version_text.isdigit():
        raise LinkError("invalid_version", "malformed @v<version> pin")
    if not _validate_leaf_id(leaf_id):
        raise LinkError("invalid_reference", "leaf_id must be an nml: identifier")
    return MathRef(leaf_id, _reference_version(int(version_text), leaf_id))


def _validate_ref_version(ref: MathRef, original: Any) -> MathRef:
    if not _validate_leaf_id(ref.leaf_id):
        raise LinkError("invalid_reference", ref.leaf_id)
    if isinstance(ref.version, bool) or not isinstance(ref.version, int) or ref.version < 1:
        raise LinkError("unpinned_version", "leaf references require version >= 1")
    if isinstance(original, Mapping):
        pinned = original.get("version")
        if pinned is not None:
            expected = _reference_version(pinned, ref.leaf_id)
            if expected != ref.version:
                raise LinkError("version_mismatch", "reference and leaf versions differ")
        digest = _optional_digest(original.get("content_digest"), "content_digest")
        if digest is not None and ref.content_digest is not None and digest != ref.content_digest:
            raise LinkError("digest_mismatch", "reference and leaf content digests differ")
    return ref


def _reference_version(value: Any, leaf_id: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LinkError("unpinned_version", f"{leaf_id} version must be an integer pin")
    if value < 1:
        raise LinkError("unpinned_version", f"{leaf_id} version must be >= 1")
    return value


def _optional_digest(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise LinkError("invalid_digest", f"{name} must be 64 hex characters")
    text = value.strip().lower()
    if text.startswith("sha256:"):
        text = text[7:]
    if not _DIGEST_RE.fullmatch(text):
        raise LinkError("invalid_digest", f"{name} must be 64 hex characters")
    return text


def _validate_leaf_id(value: str) -> bool:
    return isinstance(value, str) and bool(_LEAF_ID_RE.fullmatch(value))


def _leaf_from_mapping(document: Mapping[str, Any]) -> MathLeaf:
    fields = set(MathLeaf.__dataclass_fields__)
    payload = {key: document[key] for key in fields if key in document}
    try:
        return MathLeaf(**payload)
    except (TypeError, MathObjectError) as exc:
        raise LinkError("invalid_leaf", str(exc)) from exc


def _follow_alias(value: Any, aliases: Mapping[str, Any] | None) -> Any:
    if aliases is None or not isinstance(value, str):
        return None
    seen: set[str] = set()
    current: Any = value
    while isinstance(current, str) and current not in seen:
        seen.add(current)
        if current in aliases:
            current = aliases[current]
        elif current.upper() in aliases:
            current = aliases[current.upper()]
        else:
            return current if current != value else None
        if isinstance(current, (MathLeaf, Mapping)):
            return current
    return None


def _resolve_leaf(operand: Any, ref: MathRef, leaves: Any) -> MathLeaf:
    if isinstance(operand, MathLeaf):
        return operand
    if isinstance(operand, Mapping):
        if isinstance(operand.get("leaf"), MathLeaf):
            return operand["leaf"]
        if operand.get("kind") is not None and (
            operand.get("type") is not None or operand.get("schema") == LEAF_SCHEMA
        ):
            return _leaf_from_mapping(_leaf_document_for_ref(operand, ref))
    value: Any = None
    if leaves is None:
        raise LinkError("unknown_leaf", f"no leaf resolver supplied for {ref.leaf_id}")
    if callable(leaves):
        value = _call_resolver(leaves, ref)
    elif hasattr(leaves, "resolve"):
        value = _call_resolver(leaves.resolve, ref)
    elif hasattr(leaves, "get_leaf"):
        value = _call_resolver(leaves.get_leaf, ref)
    else:
        try:
            value = leaves.get((ref.leaf_id, ref.version))
            if value is None:
                value = leaves.get(ref.leaf_id)
        except AttributeError as exc:
            raise LinkError("invalid_resolver", "leaf resolver must be mapping/callable") from exc
    if isinstance(value, Mapping):
        value = _leaf_from_mapping(_leaf_document_for_ref(value, ref))
    if not isinstance(value, MathLeaf):
        raise LinkError("unknown_leaf", f"leaf not found: {ref.leaf_id}@v{ref.version}")
    if value.leaf_id != ref.leaf_id:
        raise LinkError("reference_mismatch", "resolved leaf_id differs from reference")
    if value.version != ref.version:
        raise LinkError("version_mismatch", "resolved leaf version differs from pinned version")
    if ref.content_digest is not None and value.content_digest != ref.content_digest:
        raise LinkError("digest_mismatch", "resolved content digest differs from reference")
    return value


def _leaf_document_for_ref(document: Mapping[str, Any], ref: MathRef) -> dict[str, Any]:
    payload = dict(document)
    payload.setdefault("leaf_id", ref.leaf_id)
    payload.setdefault("version", ref.version)
    if "content_digest" in payload and not isinstance(payload.get("content"), Mapping):
        digest = _optional_digest(payload.pop("content_digest"), "content_digest")
        if digest is not None:
            payload["content"] = {"digest": digest}
    return payload


def _call_resolver(resolver: Any, ref: MathRef) -> Any:
    signature = _safe_signature(resolver)
    attempts: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    if signature is not None:
        names = set(signature.parameters)
        kwargs = {}
        if "ref" in names or "reference" in names:
            kwargs["ref" if "ref" in names else "reference"] = ref
        if "leaf_id" in names:
            kwargs["leaf_id"] = ref.leaf_id
        if "version" in names:
            kwargs["version"] = ref.version
        if kwargs:
            attempts.append(((), kwargs))
    attempts.extend([
        ((ref,), {}),
        ((ref.leaf_id,), {}),
        ((ref.leaf_id, ref.version), {}),
        ((), {}),
    ])
    return _call_first(resolver, signature, attempts)


def classify_leaf(leaf: MathLeaf) -> LeafClass:
    """Classify type/domain/shape/layout without evaluating any content."""
    if not isinstance(leaf, MathLeaf):
        raise LinkError("invalid_leaf", "classify_leaf requires a MathLeaf")
    type_record = dict(leaf.type)
    kind = str(leaf.kind)
    shape_declared = type_record.get("shape") is not None
    shape = _parse_shape(type_record.get("shape", ()), "leaf.type.shape")
    domain = _leaf_domain(type_record)
    layout = _first_text(
        type_record.get("layout"),
        type_record.get("order"),
        type_record.get("storage_layout"),
        default="unspecified",
    ).lower()
    element = _first_text(
        type_record.get("element"),
        type_record.get("dtype"),
        type_record.get("scalar"),
        default="unknown",
    ).lower()
    precision = _first_text(
        type_record.get("precision"),
        type_record.get("dtype"),
        type_record.get("element"),
        default="unspecified",
    ).lower()
    type_name = _first_text(type_record.get("name"), type_record.get("type"), default=kind).lower()
    relation_schema = type_record.get("relation_schema")
    if relation_schema is None:
        relation_schema = leaf.metadata.get("relation_schema")
    try:
        content_digest = leaf.content_digest
        leaf_digest = leaf.digest()
    except MathObjectError as exc:
        raise LinkError("invalid_leaf", str(exc)) from exc
    return LeafClass(
        leaf_id=leaf.leaf_id,
        version=leaf.version,
        kind=kind,
        domain=domain,
        shape=shape,
        shape_declared=shape_declared,
        layout=layout,
        precision=precision,
        element=element,
        type_name=type_name,
        content_digest=content_digest,
        leaf_digest=leaf_digest,
        relation_schema=None if relation_schema is None else str(relation_schema),
    )


def _leaf_domain(type_record: Mapping[str, Any]) -> str:
    declared = type_record.get("domain") or type_record.get("field") or type_record.get("scalar_type")
    if declared is not None:
        return str(declared).lower()
    element = str(type_record.get("element") or type_record.get("dtype") or "").lower()
    if "complex" in element or "c64" in element or "c128" in element:
        return "complex"
    if "float" in element or element.startswith("f") or "real" in element:
        return "real"
    if "int" in element or "uint" in element:
        return "integer"
    if "bool" in element:
        return "boolean"
    return "unknown"


# ---------------------------------------------------------------------------
# Function contract normalization
# ---------------------------------------------------------------------------


def _normalize_function(value: Any, fallback_id: str | None = None) -> _FunctionSpec:
    preset_digest: str | None = None
    if isinstance(value, MathFunction):
        raw = value.to_dict()
        preset_digest = value.digest()
    elif isinstance(value, Mapping):
        raw = dict(value)
    elif hasattr(value, "to_dict"):
        document = value.to_dict()
        if not isinstance(document, Mapping):
            raise LinkError("invalid_contract", "contract to_dict() did not return an object")
        raw = dict(document)
    else:
        raise LinkError("invalid_contract", "function entries must be MathFunction or mappings")

    if isinstance(raw.get("function"), Mapping):
        raw = dict(raw["function"])
    contract = raw.get("contract")
    if isinstance(contract, Mapping):
        for key in (
            "signature", "semantics", "preconditions", "postconditions",
            "undefined_conditions", "numerical_policy", "implementations",
        ):
            if key not in raw and key in contract:
                raw[key] = contract[key]

    function_id = raw.get("function_id") or raw.get("id") or fallback_id
    if not isinstance(function_id, str) or not _FUNCTION_ID_RE.fullmatch(function_id):
        raise LinkError("invalid_function_id", "function_id must match math.<family>.<name>")
    version = raw.get("version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise LinkError("invalid_version", "function version must be an integer >= 1")
    status = str(raw.get("status", "active")).lower()
    if status not in {"proposed", "active", "deprecated", "revoked"}:
        raise LinkError("invalid_status", f"unknown function status: {status!r}")
    proof_status = str(raw.get("proof_status", raw.get("proof", "none"))).lower()
    if proof_status not in PROOF_STATUSES:
        raise LinkError("invalid_proof_status", f"unknown proof status: {proof_status!r}")

    signature_value = raw.get("signature", {})
    if isinstance(signature_value, Mapping):
        signature = dict(signature_value)
    elif signature_value is None:
        signature = {}
    elif isinstance(signature_value, (str, list, tuple)):
        signature = {"inputs": signature_value}
    else:
        raise LinkError("invalid_signature", "signature must be an object or input list")
    for key in (
        "inputs", "args", "arguments", "parameters", "input", "arity",
        "output", "outputs", "result", "returns", "kind",
        "shape_rule", "shape_constraint", "shape_policy",
        "commutative", "commutative_proof", "commutativity_proof",
        "cross_domain", "mixed_domains", "result_type",
    ):
        if key not in signature and key in raw:
            signature[key] = raw[key]
    semantics = raw.get("semantics")
    semantics = dict(semantics) if isinstance(semantics, Mapping) else {}

    input_specs, arity = _signature_inputs(signature, raw)
    if arity is None:
        raise LinkError("invalid_signature", "function contract must declare input arity/types")
    if input_specs and len(input_specs) != arity:
        raise LinkError("invalid_signature", "declared arity and input specs disagree")
    if not input_specs:
        input_specs = tuple(_TypeSpec(wildcard=True) for _ in range(arity))
    output_spec = _signature_output(signature, raw, semantics)

    implementations_value = raw.get("implementations", ())
    implementations = _tuple_of_mappings(implementations_value, "implementations")
    try:
        capability_digest = digest_object(list(implementations))
    except MathObjectError as exc:
        raise LinkError("invalid_contract", str(exc)) from exc

    commutative, commutative_proof = _commutative_declaration(raw, signature, semantics)
    if commutative_proof in PROVED_COMMUTATIVE_STATUSES:
        commutative = True
    commutative_proved = bool(
        commutative
        and (
            commutative_proof in PROVED_COMMUTATIVE_STATUSES
            or (commutative_proof in {None, "overall"} and proof_status in PROVED_COMMUTATIVE_STATUSES)
        )
    )

    shape_policy = _contract_shape_policy(raw, signature, semantics, input_specs)
    cross_domain = bool(
        _truthy(raw.get("cross_domain"))
        or _truthy(raw.get("mixed_domains"))
        or _truthy(signature.get("cross_domain"))
        or _truthy(semantics.get("cross_domain"))
        or _truthy(semantics.get("mixed_domains"))
    )

    priority = _rank_int(raw, ("priority", "utility", "preference", "rank_hint"), 0)
    cost = max(0, _rank_int(raw, ("cost", "rank_cost", "estimated_cost"), 0))

    contract_digest = _function_contract_digest(
        raw, preset_digest, function_id=function_id, version=version,
    )
    return _FunctionSpec(
        function_id=function_id,
        version=version,
        status=status,
        proof_status=proof_status,
        signature=signature,
        semantics=semantics,
        implementations=implementations,
        input_specs=tuple(input_specs),
        output_spec=output_spec,
        commutative=commutative,
        commutative_proved=commutative_proved,
        contract_digest=contract_digest,
        capability_digest=capability_digest,
        shape_policy=shape_policy,
        cross_domain=cross_domain,
        priority=priority,
        cost=cost,
    )


def _signature_inputs(signature: Mapping[str, Any], raw: Mapping[str, Any]) -> tuple[tuple[_TypeSpec, ...], int | None]:
    value: Any = None
    for key in ("inputs", "args", "arguments", "parameters", "operands"):
        if key in signature:
            value = signature[key]
            break
    if value is None and "input" in signature:
        value = signature["input"]
    if value is None:
        paired = _paired_inputs(signature, raw)
        if paired:
            return tuple(_TypeSpec.from_value(item) for item in paired), len(paired)
        kind = signature.get("kind")
        if isinstance(kind, str):
            derived = _derive_arity_kind(kind)
            if derived:
                return tuple(_TypeSpec(kind=item) for item in derived), len(derived)
        arity = raw.get("arity", signature.get("arity"))
        if isinstance(arity, int) and not isinstance(arity, bool) and arity >= 0:
            return (), arity
        return (), None

    if isinstance(value, bool):
        raise LinkError("invalid_signature", "input arity cannot be boolean")
    if isinstance(value, int):
        if value < 0:
            raise LinkError("invalid_signature", "input arity must be >= 0")
        return (), value
    if isinstance(value, str):
        if "<" in value or "[" in value:
            pieces = [value.strip()]
        else:
            pieces = [
                piece.strip()
                for piece in re.split(r"\s*,\s*|\s+", value)
                if piece.strip()
            ]
        return tuple(_TypeSpec.from_value(piece) for piece in pieces), len(pieces)
    if isinstance(value, Mapping):
        if _looks_like_type_spec(value):
            return (_TypeSpec.from_value(value),), 1
        if "items" in value and isinstance(value["items"], Sequence) and not isinstance(value["items"], str):
            items = list(value["items"])
        elif "types" in value and isinstance(value["types"], Sequence) and not isinstance(value["types"], str):
            items = list(value["types"])
        else:
            items = _ordered_mapping_values(value)
        return tuple(_TypeSpec.from_value(item) for item in items), len(items)
    if isinstance(value, Sequence):
        items = list(value)
        return tuple(_TypeSpec.from_value(item) for item in items), len(items)
    raise LinkError("invalid_signature", "unsupported inputs declaration")


def _paired_inputs(signature: Mapping[str, Any], raw: Mapping[str, Any]) -> list[Any] | None:
    for left, right in (("left", "right"), ("lhs", "rhs"), ("a", "b"), ("x", "y")):
        if left in signature and right in signature:
            return [signature[left], signature[right]]
        if left in raw and right in raw:
            return [raw[left], raw[right]]
    return None


def _ordered_mapping_values(value: Mapping[Any, Any]) -> list[Any]:
    keys = list(value.keys())
    preferred = ("left", "right", "lhs", "rhs", "a", "b", "x", "y")
    if all(key in value for key in ("left", "right")):
        return [value["left"], value["right"]]
    if all(key in value for key in ("lhs", "rhs")):
        return [value["lhs"], value["rhs"]]
    if all(key in value for key in ("a", "b")):
        return [value["a"], value["b"]]
    if all(key in value for key in ("x", "y")):
        return [value["x"], value["y"]]
    ordered = [key for key in preferred if key in value]
    ordered.extend(sorted((key for key in keys if key not in ordered), key=str))
    return [value[key] for key in ordered]


def _derive_arity_kind(value: str) -> tuple[str, ...] | None:
    text = value.strip().lower()
    derived = {
        "vector_binary": ("vector", "vector"),
        "scalar_binary": ("scalar", "scalar"),
        "matrix_binary": ("matrix", "matrix"),
        "vector_unary": ("vector",),
        "scalar_unary": ("scalar",),
        "matrix_unary": ("matrix",),
        "vector_scalar": ("vector", "scalar"),
        "scalar_vector": ("scalar", "vector"),
        "matrix_vector": ("matrix", "vector"),
        "vector_matrix": ("vector", "matrix"),
        "matrix_matrix": ("matrix", "matrix"),
    }
    return derived.get(text)


def _signature_output(signature: Mapping[str, Any], raw: Mapping[str, Any],
                      semantics: Mapping[str, Any]) -> _TypeSpec:
    value: Any = None
    for key in ("output", "outputs", "result", "returns"):
        if key in signature:
            value = signature[key]
            break
    if value is None:
        for key in ("result_type", "output", "returns"):
            if key in raw:
                value = raw[key]
                break
    if value is None:
        value = semantics.get("result_type", semantics.get("output"))
    if value is None:
        return _TypeSpec(wildcard=True)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, Mapping)):
        items = list(value)
        if not items:
            return _TypeSpec(wildcard=True)
        value = items[0]
    return _TypeSpec.from_value(value)


def _tuple_of_mappings(value: Any, name: str) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        return (dict(value),)
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise LinkError("invalid_contract", f"{name} must be a list of objects")
    result = []
    for item in value:
        if not isinstance(item, Mapping):
            raise LinkError("invalid_contract", f"{name} entries must be objects")
        result.append(dict(item))
    return tuple(result)


def _commutative_declaration(raw: Mapping[str, Any], signature: Mapping[str, Any],
                             semantics: Mapping[str, Any]) -> tuple[bool, str | None]:
    declared = False
    proof: str | None = None
    sources = (raw, signature, semantics)
    for source in sources:
        value = source.get("commutative")
        if isinstance(value, bool):
            declared = declared or value
        elif isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "yes", "declared"}:
                declared = True
            elif lowered in PROOF_STATUSES:
                declared = True
                proof = lowered
        elif isinstance(value, Mapping):
            if _truthy(value.get("declared", True)):
                declared = True
            nested_proof = value.get("proof_status", value.get("proof"))
            if isinstance(nested_proof, str) and nested_proof.strip().lower() in PROOF_STATUSES:
                proof = nested_proof.strip().lower()
        properties = source.get("properties")
        if isinstance(properties, (list, tuple, set)):
            if any(str(item).strip().lower() in {"commutative", "commutativity"} for item in properties):
                declared = True
        for key in (
            "commutative_proof", "commutativity_proof", "commutative_proof_status",
            "proof_of_commutativity",
        ):
            if key in source:
                value = source[key]
                if isinstance(value, bool):
                    if value:
                        declared = True
                        proof = "overall"
                elif isinstance(value, str):
                    lowered = value.strip().lower()
                    if lowered in PROOF_STATUSES:
                        declared = True
                        proof = lowered
        law = source.get("commutativity")
        if isinstance(law, Mapping):
            if _truthy(law.get("declared", True)):
                declared = True
            law_proof = law.get("proof_status", law.get("proof"))
            if isinstance(law_proof, str) and law_proof.strip().lower() in PROOF_STATUSES:
                declared = True
                proof = law_proof.strip().lower()
    return declared, proof


def _contract_shape_policy(raw: Mapping[str, Any], signature: Mapping[str, Any],
                           semantics: Mapping[str, Any],
                           input_specs: tuple[_TypeSpec, ...]) -> str | None:
    for source in (signature, semantics, raw):
        for key in ("shape_rule", "shape_constraint", "shape_policy"):
            value = source.get(key)
            if isinstance(value, str):
                rule = _normalize_shape_rule(value)
                if rule in {"equal", "free"}:
                    return rule
    for spec in input_specs:
        if spec.shape_rule in {"equal", "free"}:
            return spec.shape_rule
    text = _precondition_text(raw).lower()
    if "broadcast" in text:
        return "free"
    if (
        "same shape" in text
        or "equal shape" in text
        or "shape(a) == shape(b)" in text
        or "dimension mismatch" in text
        or "dimensions match" in text
    ):
        return "equal"
    return None


def _precondition_text(raw: Mapping[str, Any]) -> str:
    pieces: list[str] = []
    for key in ("preconditions", "postconditions", "undefined_conditions"):
        value = raw.get(key, ())
        if isinstance(value, str):
            pieces.append(value)
        elif isinstance(value, Mapping):
            pieces.extend(str(item) for item in value.values())
        elif isinstance(value, Sequence):
            for entry in value:
                if isinstance(entry, Mapping):
                    pieces.extend(str(item) for item in entry.values())
                else:
                    pieces.append(str(entry))
    return " ".join(pieces)


def _function_contract_digest(raw: Mapping[str, Any], preset_digest: str | None,
                              *, function_id: str, version: int) -> str:
    if preset_digest is not None:
        return _optional_digest(preset_digest, "contract_digest") or ""
    supplied = raw.get("contract_digest")
    if supplied is not None:
        normalized = _optional_digest(supplied, "contract_digest")
        if normalized is not None:
            return normalized
    document = {
        "function_id": function_id,
        "version": version,
        "signature": raw.get("signature", {}),
        "semantics": raw.get("semantics", {}),
        "preconditions": raw.get("preconditions", ()),
        "postconditions": raw.get("postconditions", ()),
        "undefined_conditions": raw.get("undefined_conditions", ()),
        "numerical_policy": raw.get("numerical_policy", {}),
        "implementations": raw.get("implementations", ()),
        "proof_status": str(raw.get("proof_status", raw.get("proof", "none"))).lower(),
    }
    try:
        return digest_object(document)
    except MathObjectError as exc:
        raise LinkError("invalid_contract", str(exc)) from exc


def _rank_int(raw: Mapping[str, Any], names: tuple[str, ...], default: int) -> int:
    for name in names:
        if name not in raw:
            continue
        value = raw[name]
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, float) and math.isfinite(value):
            return int(value)
        if isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value.strip()):
            return int(value.strip())
    return default


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1", "declared"}
    return bool(value)


# ---------------------------------------------------------------------------
# Type specs and matching
# ---------------------------------------------------------------------------


def _type_spec_from_value(value: Any) -> _TypeSpec:
    if isinstance(value, _TypeSpec):
        return value
    if value is None:
        return _TypeSpec(wildcard=True)
    if isinstance(value, str):
        text = value.strip()
        lowered = text.lower()
        if not text:
            raise LinkError("invalid_signature", "empty type spec")
        if lowered in _KIND_WILDCARDS:
            return _TypeSpec(wildcard=True)
        aliased = _KIND_ALIASES.get(lowered, lowered)
        if aliased in LEAF_KINDS:
            return _TypeSpec(kind=aliased)
        if lowered in _DOMAIN_WILDCARDS:
            return _TypeSpec(domain="numeric" if lowered in {"numeric", "number"} else lowered)
        if lowered in _DOMAIN_NAMES:
            return _TypeSpec(domain=lowered)
        if lowered in _PRECISION_ALIASES or re.fullmatch(r"(?:u?int|float|complex)\d+", lowered):
            return _TypeSpec(precision=lowered, element=lowered)
        match = re.fullmatch(
            r"(?P<kind>[a-z_]+)(?:<(?P<angle>[^>]+)>|\[(?P<bracket>[^\]]+)\])?(?::(?P<domain>[a-z0-9_]+))?",
            lowered,
        )
        if match:
            kind = _KIND_ALIASES.get(match.group("kind"), match.group("kind"))
            if kind in LEAF_KINDS:
                shape_text = match.group("angle") or match.group("bracket")
                domain = match.group("domain")
                shape = None
                if shape_text is not None:
                    shape_parts = [
                        part.strip()
                        for part in re.split(r"\s*[,x]\s*", shape_text)
                        if part.strip()
                    ]
                    if len(shape_parts) == 1 and shape_parts[0].lower() in _DOMAIN_NAMES:
                        domain = shape_parts[0].lower()
                    elif shape_parts and all(part.lower() in _DOMAIN_NAMES for part in shape_parts):
                        domain = shape_parts[0].lower()
                    else:
                        numeric = [part for part in shape_parts if re.fullmatch(r"\d+", part)]
                        domains = [part for part in shape_parts if part.lower() in _DOMAIN_NAMES]
                        if domains and domain is None:
                            domain = domains[0].lower()
                        if numeric:
                            shape = tuple(int(part) for part in numeric)
                        elif shape_parts:
                            raise LinkError("invalid_signature", f"unknown type shape: {shape_text!r}")
                return _TypeSpec(kind=kind, domain=domain, shape=shape)
        raise LinkError("invalid_signature", f"unknown type spec: {value!r}")
    if isinstance(value, bool):
        raise LinkError("invalid_signature", "boolean is not a type spec")
    if isinstance(value, int):
        return _TypeSpec(shape=_parse_shape(value, "type shape"))
    if isinstance(value, Sequence):
        return _TypeSpec(shape=_parse_shape(value, "type shape"))
    if not isinstance(value, Mapping):
        raise LinkError("invalid_signature", "unsupported type spec")

    document = dict(value)
    nested = document.get("type")
    if isinstance(nested, Mapping):
        merged = dict(nested)
        merged.update({key: item for key, item in document.items() if key != "type"})
        document = merged
    kind_value = (
        document.get("kind")
        or document.get("leaf_kind")
        or document.get("type_name")
    )
    if kind_value is None:
        candidate = document.get("type")
        if isinstance(candidate, str) and candidate.lower() in LEAF_KINDS:
            kind_value = candidate
    if kind_value is None:
        candidate = document.get("name")
        if isinstance(candidate, str) and candidate.lower() in LEAF_KINDS:
            kind_value = candidate
    kind = None
    if kind_value is not None:
        kind_text = str(kind_value).strip().lower()
        kind = _KIND_ALIASES.get(kind_text, kind_text)
        if kind not in LEAF_KINDS and kind not in _KIND_WILDCARDS and kind != "numeric":
            raise LinkError("invalid_signature", f"unknown type kind: {kind_value!r}")

    shape_value = document.get("shape", document.get("dimension"))
    shape: tuple[int | None, ...] | None = None
    shape_rule = None
    rule_value = document.get("shape_rule", document.get("shape_constraint", document.get("shape_policy")))
    if isinstance(rule_value, str):
        shape_rule = _normalize_shape_rule(rule_value)
    if isinstance(shape_value, str) and _normalize_shape_rule(shape_value) is not None:
        shape_rule = _normalize_shape_rule(shape_value)
        shape_value = None
    if shape_value is not None:
        shape = _parse_shape(shape_value, "type shape", allow_none=True)

    domain = document.get("domain")
    precision = document.get("precision")
    element = document.get("element", document.get("dtype"))
    layout = document.get("layout")
    return _TypeSpec(
        kind=kind,
        domain=None if domain is None else str(domain).strip().lower(),
        shape=shape,
        shape_rule=shape_rule,
        layout=None if layout is None else str(layout).strip().lower(),
        precision=None if precision is None else str(precision).strip().lower(),
        element=None if element is None else str(element).strip().lower(),
        wildcard=bool(kind in _KIND_WILDCARDS and shape is None and domain is None),
    )


def _looks_like_type_spec(value: Mapping[str, Any]) -> bool:
    keys = {str(key).lower() for key in value.keys()}
    type_keys = {"kind", "leaf_kind", "type_name", "domain", "shape", "dimension", "layout", "precision", "element", "dtype", "name"}
    named = {"left", "right", "lhs", "rhs", "a", "b", "x", "y", "items", "types", "args", "parameters"}
    return bool(keys & type_keys) and not bool(keys & named)


def _normalize_shape_rule(value: str) -> str | None:
    return _SHAPE_RULE_ALIASES.get(value.strip().lower())


def _parse_shape(value: Any, name: str, *, allow_none: bool = False) -> tuple[int | None, ...]:
    if isinstance(value, bool):
        raise LinkError("invalid_shape", f"{name} cannot be boolean")
    if isinstance(value, int):
        if value < 0:
            raise LinkError("invalid_shape", f"{name} dimensions must be >= 0")
        return (value,)
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in {"scalar", "()", "[]"}:
            return ()
        pieces = [piece.strip() for piece in text.replace("x", ",").replace(" ", ",").split(",") if piece.strip()]
        result: list[int | None] = []
        for piece in pieces:
            if piece in {"*", "?", "_", "none", "None"}:
                if not allow_none:
                    raise LinkError("invalid_shape", f"{name} cannot contain wildcard dimensions")
                result.append(None)
                continue
            if not re.fullmatch(r"\d+", piece):
                raise LinkError("invalid_shape", f"{name} has a non-integer dimension: {piece!r}")
            result.append(int(piece))
        return tuple(result)
    if isinstance(value, Sequence):
        result = []
        for item in value:
            if item is None:
                if not allow_none:
                    raise LinkError("invalid_shape", f"{name} cannot contain null dimensions")
                result.append(None)
            elif isinstance(item, bool) or not isinstance(item, int) or item < 0:
                raise LinkError("invalid_shape", f"{name} dimensions must be integers >= 0")
            else:
                result.append(item)
        return tuple(result)
    raise LinkError("invalid_shape", f"{name} must be an integer, string, or list")


def _match_function(spec: _FunctionSpec, classes: tuple[LeafClass, ...]) -> _Match:
    if len(spec.input_specs) != len(classes):
        return _Match(
            "arity_mismatch",
            f"expected {len(spec.input_specs)} inputs, received {len(classes)}",
        )
    features = 0
    for spec_item, leaf in zip(spec.input_specs, classes):
        if spec_item.wildcard:
            features += 1
            continue
        if spec_item.kind is not None and not _kind_compatible(spec_item.kind, leaf.kind):
            return _Match("kind_mismatch", f"{spec_item.kind} contract received {leaf.kind}")
        if spec_item.kind is not None:
            features += 8
        if spec_item.domain is not None and not _domain_compatible(spec_item.domain, leaf.domain):
            return _Match("domain_mismatch", f"{spec_item.domain} contract received {leaf.domain}")
        if spec_item.domain is not None:
            features += 4
        if spec_item.element is not None and leaf.element not in {"unknown", spec_item.element}:
            return _Match("element_mismatch", f"{spec_item.element} contract received {leaf.element}")
        if spec_item.precision is not None:
            expected = _precision_key(spec_item.precision)
            actual = _precision_key(leaf.precision)
            if actual not in {"unspecified", expected}:
                return _Match("precision_mismatch", f"{expected} contract received {actual}")
            features += 2
        if spec_item.layout is not None and leaf.layout not in {"unspecified", spec_item.layout}:
            return _Match("layout_mismatch", f"{spec_item.layout} contract received {leaf.layout}")
        if spec_item.layout is not None:
            features += 2
        if spec_item.shape is not None:
            if not _shape_matches(spec_item.shape, leaf):
                return _Match("dimension_mismatch", f"expected shape {list(spec_item.shape)}, received {list(leaf.shape)}")
            features += 6

    if spec.shape_policy == "equal" or _default_equal_vector_shape(spec, classes):
        if not _all_shapes_equal(classes):
            return _Match("dimension_mismatch", "operand shapes are not equal")
        features += 4
    for spec_item in spec.input_specs:
        if spec_item.shape_rule == "equal" and not _all_shapes_equal(classes):
            return _Match("dimension_mismatch", "contract requires equal operand shapes")
        index = _shape_rule_index(spec_item.shape_rule)
        if index is not None and index < len(classes):
            left = classes[index]
            if left.shape_declared:
                for leaf in classes:
                    if leaf.shape_declared and leaf.shape != left.shape:
                        return _Match("dimension_mismatch", "contract requires operand shapes to match")

    if not spec.cross_domain and not any(item.domain for item in spec.input_specs):
        if not _all_domains_equal(classes):
            return _Match("domain_mismatch", "operand domains are not equal")
    return _Match(None, "", features)


def _default_equal_vector_shape(spec: _FunctionSpec, classes: tuple[LeafClass, ...]) -> bool:
    if spec.shape_policy == "free" or len(classes) < 2:
        return False
    return all(leaf.kind == "vector" for leaf in classes)


def _kind_compatible(expected: str, actual: str) -> bool:
    expected = expected.strip().lower()
    actual = actual.strip().lower()
    if expected in _KIND_WILDCARDS or actual in _KIND_WILDCARDS:
        return True
    if expected == actual:
        return True
    if expected == "numeric":
        return actual in {"scalar", "vector", "matrix", "tensor"}
    if expected == "tensor":
        return actual in {"scalar", "vector", "matrix", "tensor"}
    if expected == "scalar" and actual == "hypergraph":
        return False
    return False


def _domain_compatible(expected: str, actual: str) -> bool:
    expected = expected.strip().lower()
    actual = actual.strip().lower()
    if expected in _DOMAIN_WILDCARDS or actual in _DOMAIN_WILDCARDS:
        return True
    if expected == actual:
        return True
    if expected in {"numeric", "number"}:
        return actual in {"real", "integer", "rational", "complex", "boolean"}
    if expected == "complex":
        return actual in {"real", "integer", "rational"}
    if expected == "real":
        return actual == "integer"
    return False


def _precision_key(value: str) -> str:
    text = value.strip().lower()
    return _PRECISION_ALIASES.get(text, text)


def _shape_matches(expected: tuple[int | None, ...], leaf: LeafClass) -> bool:
    if not leaf.shape_declared:
        return True
    actual = leaf.shape
    if len(expected) != len(actual):
        return False
    return all(wanted is None or wanted == got for wanted, got in zip(expected, actual))


def _all_shapes_equal(classes: tuple[LeafClass, ...]) -> bool:
    declared = [leaf.shape for leaf in classes if leaf.shape_declared]
    return len({shape for shape in declared}) <= 1


def _all_domains_equal(classes: tuple[LeafClass, ...]) -> bool:
    known = {leaf.domain for leaf in classes if leaf.domain not in {"unknown", "unspecified"}}
    return len(known) <= 1


def _shape_rule_index(rule: str | None) -> int | None:
    if rule in {"operand0", "rows"}:
        return 0
    if rule in {"operand1", "cols"}:
        return 1
    if rule == "operand2":
        return 2
    return None


def _resolve_output(spec: _FunctionSpec, classes: tuple[LeafClass, ...]) -> dict[str, Any]:
    output_spec = spec.output_spec
    kind = output_spec.kind
    if kind is None or kind in _KIND_WILDCARDS or kind == "numeric":
        kind = "unknown"
    domain = output_spec.domain
    if domain is None or domain in _DOMAIN_WILDCARDS:
        domain = classes[0].domain if classes else "unknown"
    shape: list[int | None] | None = None
    if output_spec.shape is not None:
        shape = list(output_spec.shape)
    elif output_spec.shape_rule is not None:
        shape = _shape_from_rule(output_spec.shape_rule, classes)
    elif kind == "scalar":
        shape = []
    elif kind == "vector":
        for leaf in classes:
            if leaf.kind == "vector" and leaf.shape_declared:
                shape = list(leaf.shape)
                break
    elif kind == "matrix":
        for leaf in classes:
            if leaf.kind == "matrix" and leaf.shape_declared:
                shape = list(leaf.shape)
                break
    reference = classes[0] if classes else None
    return {
        "kind": kind,
        "domain": domain,
        "shape": shape,
        "layout": output_spec.layout or (reference.layout if reference else "unspecified"),
        "precision": output_spec.precision or (reference.precision if reference else "unspecified"),
        "element": output_spec.element or (reference.element if reference else "unknown"),
    }


def _shape_from_rule(rule: str, classes: tuple[LeafClass, ...]) -> list[int | None] | None:
    index = _shape_rule_index(rule)
    if rule == "equal":
        for leaf in classes:
            if leaf.shape_declared:
                return list(leaf.shape)
        return None
    if index is not None:
        if rule in {"rows", "cols"}:
            if not classes or not classes[0].shape_declared:
                return None
            position = 0 if rule == "rows" else -1
            if not classes[0].shape:
                return None
            return [classes[0].shape[position]]
        if index < len(classes) and classes[index].shape_declared:
            return list(classes[index].shape)
    return None


# ---------------------------------------------------------------------------
# Ranking and registry adapters
# ---------------------------------------------------------------------------


def _rank_score(spec: _FunctionSpec, match: _Match, goal_match: bool,
                objective: str, output: Mapping[str, Any]) -> int:
    score = match.features * 100
    if goal_match:
        score += 5000
    score += spec.priority * 10
    score -= spec.cost
    output_kind = str(output.get("kind", "unknown"))
    objective_key = objective.strip().lower()
    if objective_key in {"association", "summary", "scalar", "compress", "reduce"}:
        if output_kind == "scalar":
            score += 300
        elif output_kind == "vector":
            score += 100
    elif objective_key in {"structure", "expand", "vector", "reveal"}:
        if output_kind in {"vector", "matrix", "tensor"}:
            score += 300
        elif output_kind == "scalar":
            score += 50
    elif objective_key in {"transform", "goal"} and goal_match:
        score += 300
    if spec.commutative_proved:
        score += 20
    if spec.proof_status in PROVED_COMMUTATIVE_STATUSES:
        score += 30
    elif spec.proof_status in {"tested", "empirical"}:
        score += 10
    return int(score)


def _rank_key(record: _CandidateRecord) -> tuple[Any, ...]:
    return (
        -record.score,
        record.spec.function_id,
        record.spec.version,
        record.candidate.candidate_id,
    )


def _invoke_registry(registry: Any, classes: tuple[LeafClass, ...], query: LinkQuery) -> Any:
    if isinstance(registry, Mapping):
        return registry
    if callable(registry):
        signature = _safe_signature(registry)
        attempts: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        known = {
            "inputs": classes,
            "operands": classes,
            "classes": classes,
            "query": query,
            "mode": query.mode,
            "objective": query.objective,
        }
        if signature is not None:
            names = set(signature.parameters)
            kwargs = {
                name: value for name, value in known.items()
                if name in names
            }
            # Supply only the first operand-container name if a callable
            # unexpectedly declares more than one of them.
            container_names = [name for name in ("inputs", "operands", "classes") if name in kwargs]
            for extra in container_names[1:]:
                kwargs.pop(extra, None)
            if any(
                parameter.kind is inspect.Parameter.VAR_KEYWORD
                for parameter in signature.parameters.values()
            ):
                kwargs = dict(known)
            if kwargs:
                attempts.append(((), kwargs))
        for name in ("inputs", "operands", "classes"):
            attempts.append((
                (),
                {
                    name: classes,
                    "query": query,
                    "mode": query.mode,
                    "objective": query.objective,
                },
            ))
        attempts.extend([
            ((classes, query, query.mode, query.objective), {}),
            ((classes, query, query.mode), {}),
            ((classes, query, query.objective), {}),
            ((classes, query), {}),
            ((query, classes), {}),
            ((classes,), {}),
            ((), {}),
        ])
        try:
            return _call_first(registry, signature, tuple(attempts))
        except LinkError:
            raise
        except Exception as exc:
            raise LinkError("registry_error", f"{type(exc).__name__}: {exc}") from exc
    if hasattr(registry, "items"):
        return registry
    if hasattr(registry, "functions"):
        return registry.functions
    if hasattr(registry, "function_id") and hasattr(registry, "signature"):
        return [registry]
    if isinstance(registry, Iterable) and not isinstance(registry, (str, bytes, Mapping)):
        return registry
    raise LinkError("invalid_registry", "registry must be a mapping or callable")


def _safe_signature(callable_value: Any) -> inspect.Signature | None:
    try:
        return inspect.signature(callable_value)
    except (TypeError, ValueError):
        return None


def _call_first(callable_value: Any, signature: inspect.Signature | None,
                attempts: Iterable[tuple[tuple[Any, ...], dict[str, Any]]]) -> Any:
    attempt_list = list(attempts)
    if signature is not None:
        for args, kwargs in attempt_list:
            try:
                signature.bind(*args, **kwargs)
            except TypeError:
                continue
            return callable_value(*args, **kwargs)
        raise LinkError("invalid_callable", "callable does not accept the linker context")
    last_error: TypeError | None = None
    for args, kwargs in attempt_list:
        try:
            return callable_value(*args, **kwargs)
        except TypeError as exc:
            last_error = exc
    raise LinkError("invalid_callable", str(last_error) if last_error else "callable failed")


def _prepare_registry(raw: Any) -> tuple[tuple[_FunctionSpec, ...], tuple[dict[str, Any], ...]]:
    if isinstance(raw, str) or raw is None:
        raise LinkError("invalid_registry", "registry did not return a function collection")
    if hasattr(raw, "function_id") and hasattr(raw, "signature"):
        raw = [raw]
    if not isinstance(raw, (Mapping, str, bytes)) and hasattr(raw, "functions"):
        raw = raw.functions
    items: list[tuple[Any, Any]] = []
    if isinstance(raw, Mapping):
        data: Mapping[Any, Any] = raw
        if "functions" in data and isinstance(data["functions"], (Mapping, Sequence)) and "function_id" not in data:
            data = data["functions"]  # type: ignore[assignment]
        if isinstance(data, Mapping) and "function_id" in data:
            items = [(data.get("function_id"), data)]
        elif isinstance(data, Mapping):
            items = list(data.items())
        else:
            raw = data
    if not items and hasattr(raw, "items") and not isinstance(raw, Mapping):
        items = list(raw.items())
    if not items and not isinstance(raw, Mapping):
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
            sequence = list(raw)
        elif isinstance(raw, Iterable) and not isinstance(raw, (str, bytes)):
            sequence = list(raw)
        else:
            raise LinkError("invalid_registry", "registry must produce functions")
        for entry in sequence:
            if (
                isinstance(entry, tuple)
                and len(entry) == 2
                and isinstance(entry[0], str)
                and not isinstance(entry[1], (str, bytes))
            ):
                items.append((entry[0], entry[1]))
            else:
                items.append((None, entry))

    specs: list[_FunctionSpec] = []
    rejected: list[dict[str, Any]] = []
    for key, value in items:
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, Mapping)):
            for item in value:
                specs, rejected = _normalize_with_fallback(key, item, specs, rejected)
        else:
            specs, rejected = _normalize_with_fallback(key, value, specs, rejected)
    specs.sort(key=lambda item: (item.function_id, item.version, item.contract_digest))
    rejected.sort(key=lambda row: (
        str(row.get("function_id", "")),
        int(row.get("version", 0)),
        str(row.get("reason", "")),
        canonical_json(row),
    ))
    return tuple(specs), tuple(rejected)


def _normalize_with_fallback(key: Any, value: Any, specs: list[_FunctionSpec],
                             rejected: list[dict[str, Any]]) -> tuple[list[_FunctionSpec], list[dict[str, Any]]]:
    fallback = key if isinstance(key, str) and key.startswith("math.") else None
    try:
        specs.append(_normalize_function(value, fallback_id=fallback))
    except LinkError as exc:
        rejected.append(_rejection(
            fallback or (str(key) if key is not None else "<registry>"),
            0,
            exc.code,
            exc.message,
        ))
    except MathObjectError as exc:
        rejected.append(_rejection(
            fallback or (str(key) if key is not None else "<registry>"),
            0,
            "invalid_contract",
            str(exc),
        ))
    return specs, rejected


def _rejection(function_id: Any, version: Any, reason: str, detail: str = "") -> dict[str, Any]:
    row: dict[str, Any] = {
        "function_id": str(function_id or "<registry>"),
        "version": version if isinstance(version, int) and not isinstance(version, bool) else 0,
        "reason": reason,
    }
    if detail:
        row["detail"] = str(detail)
    return row


# ---------------------------------------------------------------------------
# Snapshot construction
# ---------------------------------------------------------------------------


def _normalize_rule_rows(rules: Any) -> tuple[dict[str, Any], ...]:
    if rules is None:
        return ()
    entries: list[tuple[Any, Any]] = []
    if isinstance(rules, MathRule):
        entries = [(rules.rule_id, rules)]
    elif isinstance(rules, Mapping):
        if "rule_id" in rules:
            entries = [(rules.get("rule_id"), rules)]
        else:
            for key in sorted(rules.keys(), key=str):
                value = rules[key]
                if isinstance(value, Sequence) and not isinstance(value, (str, bytes, Mapping)):
                    for item in value:
                        entries.append((key, item))
                else:
                    entries.append((key, value))
    elif isinstance(rules, Sequence) and not isinstance(rules, (str, bytes)):
        entries = [(None, item) for item in rules]
    elif isinstance(rules, Iterable) and not isinstance(rules, (str, bytes, Mapping)):
        entries = [(None, item) for item in rules]
    else:
        raise LinkError("invalid_rule", "rules must be a mapping, sequence, or MathRule")

    rows = []
    for fallback, value in entries:
        if isinstance(value, MathRule):
            rule_id = value.rule_id
            version = value.version
            level = value.level
            proof_status = value.proof_status
            status = value.status
            try:
                rule_digest = digest_object(value.to_dict())
            except MathObjectError as exc:
                raise LinkError("invalid_rule", str(exc)) from exc
        elif isinstance(value, Mapping):
            rule_id = value.get("rule_id") or fallback
            if not isinstance(rule_id, str) or not rule_id:
                raise LinkError("invalid_rule", "rule_id is required")
            version = value.get("version", 1)
            if isinstance(version, bool) or not isinstance(version, int) or version < 1:
                raise LinkError("invalid_rule", f"invalid rule version for {rule_id}")
            level = value.get("level", 1)
            if isinstance(level, bool) or not isinstance(level, int) or level not in {0, 1, 2, 3}:
                raise LinkError("invalid_rule", f"invalid rule level for {rule_id}")
            proof_status = str(value.get("proof_status", "none")).lower()
            status = str(value.get("status", "proposed")).lower()
            document = dict(value)
            document.setdefault("rule_id", rule_id)
            document.setdefault("version", version)
            try:
                rule_digest = digest_object(document)
            except MathObjectError as exc:
                raise LinkError("invalid_rule", str(exc)) from exc
        else:
            raise LinkError("invalid_rule", "rule entries must be MathRule or mappings")
        rows.append({
            "rule_id": rule_id,
            "version": version,
            "level": level,
            "proof_status": proof_status,
            "status": status,
            "digest": rule_digest,
        })
    rows.sort(key=lambda row: (row["rule_id"], row["version"], row["digest"]))
    return tuple(rows)


def _normalize_capabilities(capabilities: Any, specs: tuple[_FunctionSpec, ...]) -> tuple[
    str, tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]
]:
    declared: list[dict[str, Any]] = []
    if capabilities is not None:
        if isinstance(capabilities, Mapping):
            if any(key in capabilities for key in ("capability", "capability_id", "kernel_id", "implementation_id")):
                declared.append(dict(capabilities))
            else:
                for key in sorted(capabilities.keys(), key=str):
                    value = capabilities[key]
                    if isinstance(value, Mapping):
                        row = dict(value)
                        row.setdefault("capability", str(key))
                    else:
                        row = {"capability": str(key), "value": value}
                    declared.append(row)
        elif isinstance(capabilities, str):
            declared.append({"capability": capabilities})
        elif isinstance(capabilities, Sequence):
            for item in capabilities:
                if isinstance(item, Mapping):
                    declared.append(dict(item))
                else:
                    declared.append({"capability": str(item)})
        elif isinstance(capabilities, Iterable):
            for item in capabilities:
                if isinstance(item, Mapping):
                    declared.append(dict(item))
                else:
                    declared.append({"capability": str(item)})
        else:
            raise LinkError("invalid_capability", "capabilities must be a mapping or sequence")

    derived: list[dict[str, Any]] = []
    for spec in specs:
        for implementation in spec.implementations:
            row = {
                key: implementation[key]
                for key in (
                    "kernel_id", "implementation_id", "capability", "capability_class",
                    "precision", "workspace", "workspace_words", "status", "version",
                )
                if key in implementation
            }
            if row:
                derived.append(row)
    try:
        declared.sort(key=canonical_json)
        derived.sort(key=canonical_json)
        capability_digest = digest_object({
            "declared": declared,
            "implementations": derived,
        })
    except MathObjectError as exc:
        raise LinkError("invalid_capability", str(exc)) from exc
    return capability_digest, tuple(declared), tuple(derived)


def _build_snapshot(specs: tuple[_FunctionSpec, ...], rules: Any, capabilities: Any,
                    snapshot_id: str | None) -> LinkSnapshot:
    function_rows = tuple({
        "function_id": spec.function_id,
        "version": spec.version,
        "contract_digest": spec.contract_digest,
        "capability_digest": spec.capability_digest,
        "status": spec.status,
        "proof_status": spec.proof_status,
    } for spec in specs)
    rule_rows = _normalize_rule_rows(rules)
    capability_digest, declared, derived = _normalize_capabilities(capabilities, specs)
    function_snapshot_digest = digest_object(list(function_rows))
    rule_snapshot_digest = digest_object(list(rule_rows))
    derived_snapshot_id = "snp:" + digest_object({
        "functions": list(function_rows),
        "rules": list(rule_rows),
        "capabilities": capability_digest,
    })
    if snapshot_id is None:
        chosen_snapshot_id = derived_snapshot_id
    else:
        if not isinstance(snapshot_id, str) or not snapshot_id.strip():
            raise LinkError("invalid_snapshot", "snapshot_id must be a non-empty string")
        chosen_snapshot_id = snapshot_id.strip()
    return LinkSnapshot(
        snapshot_id=chosen_snapshot_id,
        derived_snapshot_id=derived_snapshot_id,
        function_digests=function_rows,
        function_snapshot_digest=function_snapshot_digest,
        rule_digests=rule_rows,
        rule_snapshot_digest=rule_snapshot_digest,
        capability_digest=capability_digest,
        declared_capabilities=declared,
        implementation_capabilities=derived,
    )


# ---------------------------------------------------------------------------
# Public proposal API
# ---------------------------------------------------------------------------


def propose(
    query: LinkQuery | Iterable[Any] | Any = None,
    *,
    operands: Any = None,
    refs: Any = None,
    registry: Any = None,
    functions: Any = None,
    function_registry: Any = None,
    leaves: Any = None,
    rules: Any = (),
    capabilities: Any = None,
    snapshot_id: str | None = None,
    objective: str | None = None,
    max_candidates: int | None = None,
    mode: str | None = None,
    goal: Any = None,
    bounds: Any = None,
    aliases: Mapping[str, Any] | None = None,
    execute: bool = False,
) -> LinkResult:
    """Return a deterministic candidate set for a conjoin/transform query.

    ``registry`` (aliases: ``functions``, ``function_registry``) may be a
    mapping of function contracts or a callable that receives the classified
    operand views and query context.  The linker never executes a function,
    writes a leaf, or grants authorization.
    """
    if execute:
        raise LinkError(
            "execution_not_permitted",
            "the :: linker only proposes candidates; preflight/execution are separate",
        )
    if query is None:
        query = operands if operands is not None else refs
    if query is None:
        raise LinkError("invalid_query", "provide a LinkQuery or operands/refs")
    if registry is None:
        registry = functions if functions is not None else function_registry
    if registry is None:
        raise LinkError("missing_registry", "a function registry-like mapping/callable is required")

    if isinstance(query, LinkQuery):
        effective = query
        if objective is not None:
            effective = replace(effective, objective=objective)
        if max_candidates is not None:
            effective = replace(effective, max_candidates=max_candidates)
        if mode is not None:
            effective = replace(effective, mode=mode)
        if goal is not None:
            effective = replace(effective, goal=TransformGoal.from_value(goal))
        if bounds is not None:
            effective = replace(effective, bounds=LinkBounds.from_value(bounds))
    else:
        effective = LinkQuery(
            operands=_operand_tuple(query),
            mode=mode or "conjoin",
            objective=objective or "association",
            max_candidates=8 if max_candidates is None else max_candidates,
            goal=goal,
            bounds=bounds,
        )

    resolved: list[MathLeaf] = []
    for operand in effective.operands:
        reference = parse_ref(operand, aliases=aliases)
        alias_value = _follow_alias(operand, aliases)
        if isinstance(alias_value, MathLeaf):
            leaf = alias_value
        elif isinstance(alias_value, Mapping) and alias_value.get("kind") is not None and alias_value.get("type") is not None:
            leaf = _leaf_from_mapping(_leaf_document_for_ref(alias_value, reference))
        else:
            leaf = _resolve_leaf(operand, reference, leaves)
        if leaf.leaf_id != reference.leaf_id or leaf.version != reference.version:
            raise LinkError("version_mismatch", "alias leaf does not match its pin")
        if reference.content_digest is not None and leaf.content_digest != reference.content_digest:
            raise LinkError("digest_mismatch", "alias leaf content digest does not match its pin")
        resolved.append(leaf)
    classes = tuple(classify_leaf(leaf) for leaf in resolved)
    input_records = tuple(_input_record(item) for item in classes)

    raw_registry = _invoke_registry(registry, classes, effective)
    specs, prepared_rejections = _prepare_registry(raw_registry)
    rejected = list(prepared_rejections)
    snapshot = _build_snapshot(specs, rules, capabilities, snapshot_id)

    effective_bounds = effective.bounds or LinkBounds()
    incomplete_reasons: list[str] = []
    valid_records: list[_CandidateRecord] = []
    seen_candidates: dict[str, _FunctionSpec] = {}
    fuel_used = 0

    if effective_bounds.max_depth < 1:
        incomplete_reasons.append("depth_limit")
    else:
        for spec in specs:
            if fuel_used >= effective_bounds.fuel:
                incomplete_reasons.append("fuel_exhausted")
                break
            fuel_used += 1
            if spec.status not in {"active", "proposed"}:
                rejected.append(_rejection(
                    spec.function_id, spec.version, "inactive_function",
                    f"function status is {spec.status}",
                ))
                continue
            if spec.proof_status == "rejected":
                rejected.append(_rejection(
                    spec.function_id, spec.version, "rejected_function",
                    "function contract proof_status is rejected",
                ))
                continue
            match = _match_function(spec, classes)
            if match.reason is not None:
                rejected.append(_rejection(
                    spec.function_id, spec.version, match.reason, match.detail,
                ))
                continue
            output = _resolve_output(spec, classes)
            goal_match = True if effective.goal is None else effective.goal.matches(output)
            if effective.mode == "transform" and effective.goal is not None and not goal_match:
                rejected.append(_rejection(
                    spec.function_id, spec.version, "goal_mismatch",
                    f"output {output.get('kind')} does not satisfy transform goal",
                ))
                continue
            canonical_order = bool(spec.commutative_proved)
            ordered_classes = (
                tuple(sorted(classes, key=_canonical_input_key))
                if canonical_order else classes
            )
            candidate_inputs = tuple(_input_record(item) for item in ordered_classes)
            candidate_id = candidate_id_for(
                snapshot.snapshot_id,
                candidate_inputs,
                spec.function_id,
                spec.version,
            )
            if candidate_id in seen_candidates:
                rejected.append(_rejection(
                    spec.function_id, spec.version, "duplicate_candidate",
                    "candidate content key already exists in this set",
                ))
                continue
            seen_candidates[candidate_id] = spec
            hint = "experimental" if spec.proof_status == "experimental" else "candidate"
            candidate = MathCandidate(
                candidate_id=candidate_id,
                inputs=candidate_inputs,
                function_id=spec.function_id,
                function_version=spec.version,
                outputs=(output,),
                snapshot_id=snapshot.snapshot_id,
                rank=0,
                preflight_hint=hint,
            )
            score = _rank_score(spec, match, goal_match, effective.objective, output)
            valid_records.append(_CandidateRecord(
                candidate=candidate,
                score=score,
                match=match,
                spec=spec,
                output=output,
                canonical_order=canonical_order,
                goal_match=goal_match,
            ))

    valid_records.sort(key=_rank_key)
    total_valid = len(valid_records)
    if total_valid > effective_bounds.max_fanout:
        valid_records = valid_records[:effective_bounds.max_fanout]
        incomplete_reasons.append("fanout_limit")
    if len(valid_records) > effective.max_candidates:
        valid_records = valid_records[:effective.max_candidates]
        incomplete_reasons.append("candidate_limit")
    omitted = total_valid - len(valid_records)
    truncated = omitted > 0
    incomplete_reasons = _unique(incomplete_reasons)
    incomplete = bool(incomplete_reasons)

    ranked_candidates = tuple(
        _record_candidate(replace(record.candidate, rank=index), record)
        for index, record in enumerate(valid_records, start=1)
    )
    candidates = tuple(record.candidate for record in ranked_candidates)
    functions = tuple(_function_metadata(record) for record in ranked_candidates)
    rejected_rows = tuple(sorted(rejected, key=lambda row: (
        str(row.get("function_id", "")),
        int(row.get("version", 0)),
        str(row.get("reason", "")),
        canonical_json(row),
    )))

    null_leaf = None
    if not candidates:
        reason = _null_reason(
            effective, classes, specs, rejected_rows, incomplete_reasons,
        )
        null_leaf = _typed_null(
            reason,
            input_records,
            snapshot.snapshot_id,
            effective,
            rejected_rows,
            incomplete_reasons,
        )

    search = {
        "depth": min(1, effective_bounds.max_depth),
        "max_depth": effective_bounds.max_depth,
        "max_fanout": effective_bounds.max_fanout,
        "fuel": effective_bounds.fuel,
        "fuel_used": fuel_used,
        "registry_functions": len(specs),
        "valid_candidates": total_valid,
        "returned_candidates": len(candidates),
        "incomplete_reasons": list(incomplete_reasons),
    }
    return LinkResult(
        mode=effective.mode,
        snapshot=snapshot,
        inputs=input_records,
        candidates=candidates,
        functions=functions,
        rejected=rejected_rows,
        objective=effective.objective,
        goal=effective.goal,
        null=null_leaf,
        truncated=truncated,
        incomplete=incomplete,
        incomplete_reasons=tuple(incomplete_reasons),
        omitted_candidate_count=omitted,
        search=search,
    )


def link(query: LinkQuery | Iterable[Any] | Any, **kwargs: Any) -> LinkResult:
    """Alias for :func:`propose`."""
    return propose(query, **kwargs)


class MathLinker:
    """Reusable linker facade over a fixed registry/context."""

    def __init__(
        self,
        registry: Any = None,
        *,
        functions: Any = None,
        function_registry: Any = None,
        leaves: Any = None,
        rules: Any = (),
        capabilities: Any = None,
        snapshot_id: str | None = None,
        aliases: Mapping[str, Any] | None = None,
    ) -> None:
        if registry is None:
            registry = functions if functions is not None else function_registry
        self.registry = registry
        self.leaves = leaves
        self.rules = rules
        self.capabilities = capabilities
        self.snapshot_id = snapshot_id
        self.aliases = aliases

    def propose(self, query: LinkQuery | Iterable[Any] | Any = None,
                **kwargs: Any) -> LinkResult:
        options = {
            "registry": self.registry,
            "leaves": self.leaves,
            "rules": self.rules,
            "capabilities": self.capabilities,
            "snapshot_id": self.snapshot_id,
            "aliases": self.aliases,
        }
        options.update(kwargs)
        return propose(query, **options)

    def link(self, query: LinkQuery | Iterable[Any] | Any = None,
             **kwargs: Any) -> LinkResult:
        return self.propose(query, **kwargs)


def parse_link_query(text: str, **kwargs: Any) -> LinkQuery:
    """Convenience wrapper around :meth:`LinkQuery.parse`."""
    return LinkQuery.parse(text, **kwargs)


# ---------------------------------------------------------------------------
# Small deterministic helpers
# ---------------------------------------------------------------------------


def _operand_tuple(value: Any) -> tuple[Any, ...]:
    if isinstance(value, LinkQuery):
        return value.operands
    if isinstance(value, (str, bytes, Mapping, MathLeaf, MathRef)):
        return (value,)
    if isinstance(value, Sequence):
        return tuple(value)
    if isinstance(value, Iterable):
        return tuple(value)
    return (value,)


def _input_record(leaf: LeafClass) -> dict[str, Any]:
    return {
        "leaf_id": leaf.leaf_id,
        "version": leaf.version,
        "content_digest": leaf.content_digest,
    }


def _canonical_input_key(leaf: LeafClass) -> tuple[Any, ...]:
    return (
        leaf.leaf_id,
        leaf.version,
        leaf.content_digest or "",
        leaf.leaf_digest,
    )


def _record_candidate(candidate: MathCandidate, record: _CandidateRecord) -> _CandidateRecord:
    return replace(record, candidate=candidate)


def _function_metadata(record: _CandidateRecord) -> dict[str, Any]:
    output = record.output
    return {
        "function_id": record.spec.function_id,
        "version": record.spec.version,
        "contract_digest": record.spec.contract_digest,
        "result_type": output.get("kind"),
        "result": dict(output),
        "preflight_hint": record.candidate.preflight_hint,
        "rank": record.candidate.rank,
        "rank_score": record.score,
        "reason": _candidate_reason(record),
        "candidate_id": record.candidate.candidate_id,
        "commutative": record.spec.commutative,
        "commutative_proved": record.spec.commutative_proved,
        "commutative_canonical_order": record.canonical_order,
    }


def _candidate_reason(record: _CandidateRecord) -> str:
    output_kind = str(record.output.get("kind", "unknown"))
    return f"registered contract fits the resolved operand classes and yields {output_kind}"


def _null_reason(query: LinkQuery, classes: tuple[LeafClass, ...],
                 specs: tuple[_FunctionSpec, ...], rejected: tuple[dict[str, Any], ...],
                 incomplete_reasons: list[str]) -> str:
    if "depth_limit" in incomplete_reasons:
        return "DEPTH_LIMIT"
    if "fuel_exhausted" in incomplete_reasons:
        return "FUEL_EXHAUSTED"
    if "fanout_limit" in incomplete_reasons:
        return "FANOUT_LIMIT"
    if "candidate_limit" in incomplete_reasons:
        return "CANDIDATE_LIMIT"
    for kind in _ABSENCE_KINDS:
        if any(leaf.kind == kind for leaf in classes):
            return "INPUT_" + kind.upper()
    if query.mode == "transform" and query.goal is not None:
        if any(row.get("reason") == "goal_mismatch" for row in rejected):
            return "NO_TRANSFORM_MATCH"
    ignored = {"inactive_function", "rejected_function", "duplicate_candidate"}
    specific = {
        "arity_mismatch": "ARITY_MISMATCH",
        "kind_mismatch": "KIND_MISMATCH",
        "domain_mismatch": "DOMAIN_MISMATCH",
        "dimension_mismatch": "DIMENSION_MISMATCH",
        "element_mismatch": "ELEMENT_MISMATCH",
        "precision_mismatch": "PRECISION_MISMATCH",
        "layout_mismatch": "LAYOUT_MISMATCH",
        "goal_mismatch": "GOAL_MISMATCH",
    }
    reasons = {
        str(row.get("reason")) for row in rejected
        if row.get("reason") not in ignored
    }
    if len(reasons) == 1:
        reason = next(iter(reasons))
        if reason in specific:
            return specific[reason]
    if not specs:
        return "NO_REGISTERED_FUNCTION"
    if rejected and all(row.get("reason") == "inactive_function" for row in rejected):
        return "NO_ACTIVE_FUNCTION"
    return "NO_VALID_TRANSFORM"


def _typed_null(reason: str, inputs: tuple[dict[str, Any], ...], snapshot_id: str,
                query: LinkQuery, rejected: tuple[dict[str, Any], ...],
                incomplete_reasons: list[str]) -> MathLeaf:
    metadata = {
        "reason": reason,
        "snapshot_id": snapshot_id,
        "mode": query.mode,
        "objective": query.objective,
        "inputs": [dict(row) for row in inputs],
        "rejected_count": len(rejected),
        "incomplete_reasons": list(incomplete_reasons),
    }
    suffix = digest_object(metadata)[:24]
    parents = tuple({
        "leaf_id": row["leaf_id"],
        "version": row["version"],
        "role": f"operand{index}",
    } for index, row in enumerate(inputs))
    return _TypedNullLeaf(
        leaf_id=f"nml:U0:null:{suffix}",
        kind="null",
        type={
            "name": "null",
            "domain": "none",
            "shape": [],
            "layout": "none",
            "precision": "none",
        },
        content=None,
        parents=parents,
        metadata=metadata,
        provenance={"producer": LINKER_ID},
    )


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LinkError("invalid_argument", f"{name} must be a non-empty string")
    return value.strip()


def _first_text(*values: Any, default: str) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return default


def _json_operand(operand: Any) -> Any:
    if isinstance(operand, MathLeaf):
        return operand.to_dict()
    if isinstance(operand, MathRef):
        return operand.to_dict()
    if isinstance(operand, Mapping):
        return dict(operand)
    if isinstance(operand, (str, int, float, bool)) or operand is None:
        return operand
    return repr(operand)


__all__ = [
    "CANDIDATE_SET_SCHEMA",
    "LINKER_ID",
    "LINK_MODES",
    "LinkBounds",
    "LinkError",
    "LinkQuery",
    "LinkResult",
    "LinkSnapshot",
    "LeafClass",
    "MathRef",
    "MathLinker",
    "PROVED_COMMUTATIVE_STATUSES",
    "TransformGoal",
    "classify_leaf",
    "link",
    "parse_link_query",
    "parse_ref",
    "propose",
]
