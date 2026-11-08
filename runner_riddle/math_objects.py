"""Typed mathematical object records for the GAME_PLAN_:: vertical slice.

These are control-plane records.  They do not evaluate mathematics.  Import
this module from ``math_*`` layers; do not add these objects to the native MTH
manifest.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any, Iterable, Mapping

LEAF_SCHEMA = "nanrouter.math-leaf.v1"
FUNCTION_SCHEMA = "nanrouter.math-function.v1"
RULE_SCHEMA = "nanrouter.math-rule.v1"
CANDIDATE_SCHEMA = "nanrouter.math-candidate.v1"
ADMISSION_SCHEMA = "nanrouter.math-admission.v1"
SNAPSHOT_SCHEMA = "nanrouter.math-snapshot.v1"

LEAF_KINDS = frozenset({
    "scalar", "vector", "matrix", "tensor", "function", "relation", "rule",
    "result", "null", "void", "undefined", "unknown", "error", "cancelled", "hypergraph",
    "basis", "operator", "mask", "index", "proof", "certificate",
})
LEAF_STATUSES = frozenset({"scratch", "committed", "superseded", "quarantined", "tombstoned"})
PROOF_STATUSES = frozenset({"none", "stated", "axiom", "proven", "verified", "tested", "empirical", "experimental", "rejected"})
RULE_LEVELS = frozenset({0, 1, 2, 3})
RULE_STATUSES = frozenset({"proposed", "validated", "active", "deprecated", "revoked", "blocked"})
VERDICTS = frozenset({
    "VALID", "INVALID", "UNDEFINED", "UNAUTHORIZED", "UNSUPPORTED",
    "UNAVAILABLE", "STALE", "EXPERIMENTAL", "UNKNOWN", "NULL", "VOID",
})
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_LEAF_ID_RE = re.compile(r"^nml:[A-Za-z0-9_.:-]{1,180}$")
_FUNCTION_ID_RE = re.compile(r"^math\.[a-z0-9][a-z0-9_.-]{0,120}$")
_RULE_ID_RE = re.compile(r"^math\.rule\.[a-z0-9][a-z0-9_.-]{0,120}$")
_RESULT_PROVENANCE_KEYS = frozenset({
    "producer", "candidate_id", "admission_id", "packet_id", "job_id",
    "linker_id", "runner_id", "output_leaf_id",
})

# Optional semantic type descriptors.  They live inside an existing
# ``MathLeaf.type`` object or a function signature endpoint, so records that do
# not declare them serialize and digest exactly as before.
TYPE_DESCRIPTOR_FIELDS = (
    "element_type", "stride", "layout", "units", "rank", "shape", "domain",
    "context",
)
TYPE_DESCRIPTOR_ALIASES = {
    "element_type": ("element_type", "element", "dtype"),
    "stride": ("stride", "strides"),
    "units": ("units", "unit"),
}
_DESCRIPTOR_WILDCARDS = frozenset({"any", "*"})
_ELEMENT_TYPE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:+-]{0,63}$")
_LAYOUT_RE = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")
_UNIT_ATOM = r"[A-Za-z%°µ][A-Za-z0-9%°µ_]*"
_UNIT_RE = re.compile(
    rf"^(?:1|{_UNIT_ATOM}(?:\^[-+]?\d+)?"
    rf"(?:[*/]{_UNIT_ATOM}(?:\^[-+]?\d+)?)*)$"
)


class MathObjectError(ValueError):
    """Invalid mathematical record or canonical serialization."""


class MathImmutabilityError(MathObjectError, TypeError):
    """Attempted in-place mutation of a frozen mathematical field."""


class _FrozenDict(dict):
    """Read-only ``dict`` that still serializes and compares as a plain dict.

    Subclassing ``dict`` keeps ``json``/``canonical_json``, ``Mapping`` checks,
    equality with legacy dictionaries, and dataclass ``replace`` compatible
    while rejecting every normal Python mutator.
    """

    __slots__ = ()

    def __init__(self, value: Any = (), **kwargs: Any) -> None:
        dict.__init__(self)
        source = dict(value, **kwargs)
        for key, item in source.items():
            dict.__setitem__(self, key, _freeze_json(item))

    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        raise MathImmutabilityError("frozen mathematical object is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    __ior__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable


class _FrozenList(list):
    """Read-only ``list`` that still serializes as a canonical JSON array."""

    __slots__ = ()

    def __init__(self, value: Any = ()) -> None:
        list.__init__(self, (_freeze_json(item) for item in value))

    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        raise MathImmutabilityError("frozen mathematical object is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable


def _freeze_json(value: Any) -> Any:
    """Recursively freeze mappings/lists, preserving JSON-compatible values."""
    if isinstance(value, (_FrozenDict, _FrozenList)):
        return value
    if isinstance(value, Mapping):
        return _FrozenDict(value)
    if isinstance(value, list):
        return _FrozenList(value)
    if isinstance(value, tuple):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    """Return plain mutable containers so ``to_dict()`` never aliases state."""
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_thaw_json(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_thaw_json(item) for item in value)
    return value


def canonical_json(value: Any) -> str:
    """Deterministic JSON for control-plane objects (no fractional numbers)."""
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise MathObjectError("object is not canonical JSON") from exc


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def digest_object(value: Any) -> str:
    return sha256_text(canonical_json(value))


def _require_text(value: Any, name: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise MathObjectError(f"{name} must be a non-empty string <= {maximum}")
    return value


def _require_int(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise MathObjectError(f"{name} must be an integer >= {minimum}")
    return value


def _require_digest(value: Any, name: str, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise MathObjectError(f"{name} must be 64 lowercase hex characters")
    return value


def _tuple_of_dicts(value: Any, name: str) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    if not isinstance(value, (tuple, list)):
        raise MathObjectError(f"{name} must be a list of objects")
    result = []
    for entry in value:
        if not isinstance(entry, Mapping):
            raise MathObjectError(f"{name} entries must be objects")
        result.append(_freeze_json(entry))
    return tuple(result)


def _alias_value(source: Mapping[str, Any], aliases: Iterable[str], name: str,
                 error_cls: type[MathObjectError]) -> Any:
    """Return one alias value, rejecting conflicting declarations."""
    found = [
        (key, source[key]) for key in aliases
        if key in source and source[key] is not None
    ]
    if not found:
        return None
    _, first_value = found[0]
    for key, value in found[1:]:
        if canonical_json(value) != canonical_json(first_value):
            declared = ", ".join(item[0] for item in found)
            raise error_cls(
                f"{name} aliases disagree ({declared}); use one declaration"
            )
    return first_value


def _normalize_descriptor_shape(value: Any, name: str,
                                error_cls: type[MathObjectError]
                                ) -> tuple[int, ...] | str | None:
    if value is None:
        return None
    if isinstance(value, str):
        if value in _DESCRIPTOR_WILDCARDS:
            return "any"
        raise error_cls(f"{name} must be a list of dimensions or 'any'")
    if isinstance(value, bool) or not isinstance(value, (list, tuple)):
        raise error_cls(f"{name} must be a list of dimensions or 'any'")
    dimensions: list[int] = []
    for dimension in value:
        if (isinstance(dimension, bool) or not isinstance(dimension, int)
                or dimension < 0):
            raise error_cls(f"{name} dimensions must be integers >= 0")
        dimensions.append(dimension)
    return tuple(dimensions)


def _normalize_descriptor_stride(value: Any, name: str,
                                 error_cls: type[MathObjectError]
                                 ) -> int | tuple[int, ...] | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise error_cls(f"{name} must be an integer >= 0 or a list of them")
    if isinstance(value, int):
        if value < 0:
            raise error_cls(f"{name} must be an integer >= 0 or a list of them")
        return value
    if not isinstance(value, (list, tuple)):
        raise error_cls(f"{name} must be an integer >= 0 or a list of them")
    strides: list[int] = []
    for stride in value:
        if isinstance(stride, bool) or not isinstance(stride, int) or stride < 0:
            raise error_cls(f"{name} strides must be integers >= 0")
        strides.append(stride)
    return tuple(strides)


def _normalize_descriptor_element(value: Any, name: str,
                                  error_cls: type[MathObjectError]) -> str | None:
    if value is None:
        return None
    if (not isinstance(value, str) or not value
            or value not in _DESCRIPTOR_WILDCARDS
            and not _ELEMENT_TYPE_RE.fullmatch(value)):
        raise error_cls(
            f"{name} must be an element type token <= 64 characters"
        )
    return value


def _normalize_descriptor_layout(value: Any, name: str,
                                 error_cls: type[MathObjectError]) -> str | None:
    if value is None:
        return None
    if (not isinstance(value, str) or not value
            or value not in _DESCRIPTOR_WILDCARDS
            and not _LAYOUT_RE.fullmatch(value)):
        raise error_cls(f"{name} must be a lowercase layout token")
    return value


def _normalize_descriptor_units(value: Any, name: str,
                                error_cls: type[MathObjectError]) -> str | None:
    if value is None:
        return None
    if (not isinstance(value, str) or not value
            or value not in _DESCRIPTOR_WILDCARDS
            and not _UNIT_RE.fullmatch(value)):
        raise error_cls(
            f"{name} must be a unit expression such as 'm/s^2' or 'any'"
        )
    return value


def _normalize_descriptor_domain(value: Any, name: str,
                                 error_cls: type[MathObjectError]) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > 64:
        raise error_cls(f"{name} must be a non-empty string <= 64 characters")
    return value


def _descriptor_token(value: str) -> str:
    return value.strip().lower()


def _descriptor_stride_key(value: int | tuple[int, ...]) -> tuple[int, ...]:
    return (value,) if isinstance(value, int) else tuple(value)


@dataclass(frozen=True)
class MathTypeDescriptor:
    """Optional semantic type metadata shared by leaves and signature endpoints.

    The descriptor is a *view* over fields already present in ``MathLeaf.type``
    or a function endpoint.  Leaf serialization keeps the original spelling
    (for example ``element`` rather than ``element_type``); canonical aliases
    are only used by :meth:`to_dict`, :meth:`digest`, and compatibility checks.
    """

    element_type: str | None = None
    stride: int | tuple[int, ...] | None = None
    layout: str | None = None
    units: str | None = None
    rank: int | None = None
    shape: tuple[int, ...] | str | None = None
    domain: str | None = None
    context: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        element_type = _normalize_descriptor_element(
            self.element_type, "element_type", MathObjectError,
        )
        stride = _normalize_descriptor_stride(
            self.stride, "stride", MathObjectError,
        )
        layout = _normalize_descriptor_layout(
            self.layout, "layout", MathObjectError,
        )
        units = _normalize_descriptor_units(self.units, "units", MathObjectError)
        rank = self.rank
        if rank is not None:
            if isinstance(rank, bool) or not isinstance(rank, int) or rank < 0:
                raise MathObjectError("rank must be an integer >= 0")
        shape = _normalize_descriptor_shape(self.shape, "shape", MathObjectError)
        domain = _normalize_descriptor_domain(
            self.domain, "domain", MathObjectError,
        )
        if not isinstance(self.context, Mapping):
            raise MathObjectError("context must be an object")
        if (rank is not None and shape not in (None, "any")
                and len(shape) != rank):
            raise MathObjectError(
                f"rank {rank} does not match shape rank {len(shape)}"
            )
        object.__setattr__(self, "element_type", element_type)
        object.__setattr__(self, "stride", stride)
        object.__setattr__(self, "layout", layout)
        object.__setattr__(self, "units", units)
        object.__setattr__(self, "shape", shape)
        object.__setattr__(self, "domain", domain)
        object.__setattr__(self, "context", _freeze_json(dict(self.context)))

    @classmethod
    def from_mapping(cls, value: Any, name: str = "type descriptor", *,
                     error_cls: type[MathObjectError] = MathObjectError,
                     include_nested_type: bool = True
                     ) -> "MathTypeDescriptor":
        """Validate descriptor fields in a leaf type or signature endpoint.

        With ``include_nested_type`` (the signature-endpoint form), descriptor
        fields inside a nested ``type`` object are considered as well; the
        top-level endpoint fields take precedence.
        """
        if not isinstance(value, Mapping):
            raise error_cls(f"{name} must be an object")
        source = dict(value)
        if include_nested_type:
            nested = source.get("type")
            if isinstance(nested, Mapping):
                merged = dict(nested)
                merged.update({
                    key: item for key, item in source.items() if key != "type"
                })
                source = merged
        context_value = source.get("context")
        try:
            return cls(
                element_type=_alias_value(
                    source, TYPE_DESCRIPTOR_ALIASES["element_type"],
                    f"{name}.element_type", error_cls,
                ),
                stride=_alias_value(
                    source, TYPE_DESCRIPTOR_ALIASES["stride"],
                    f"{name}.stride", error_cls,
                ),
                layout=source.get("layout"),
                units=_alias_value(
                    source, TYPE_DESCRIPTOR_ALIASES["units"],
                    f"{name}.units", error_cls,
                ),
                rank=source.get("rank"),
                shape=source.get("shape"),
                domain=source.get("domain"),
                context={} if context_value is None else context_value,
            )
        except MathObjectError as exc:
            if error_cls is MathObjectError:
                raise
            raise error_cls(str(exc)) from exc

    def declared(self) -> frozenset[str]:
        """Return the canonical names of fields that were declared."""
        fields: set[str] = set()
        for name in TYPE_DESCRIPTOR_FIELDS:
            value = getattr(self, name)
            if name == "context":
                if value:
                    fields.add(name)
            elif value is not None:
                fields.add(name)
        return frozenset(fields)

    def to_dict(self) -> dict[str, Any]:
        document: dict[str, Any] = {}
        for name in TYPE_DESCRIPTOR_FIELDS:
            value = getattr(self, name)
            if name == "context":
                if value:
                    document[name] = _thaw_json(value)
                continue
            if value is None:
                continue
            document[name] = (
                list(value) if isinstance(value, tuple) else value
            )
        return document

    def digest(self) -> str:
        return digest_object(self.to_dict())

    def compatibility_issues(
        self, required: "MathTypeDescriptor",
    ) -> tuple[str, ...]:
        """Return first-class mismatches against a consumer requirement.

        Only fields declared by *both* descriptors are compared.  Wildcards
        (``any``/``*``) match anything.  Units are compared textually; no
        dimensional analysis or unit conversion is performed.
        """
        if not isinstance(required, MathTypeDescriptor):
            raise MathObjectError("required must be a MathTypeDescriptor")
        issues: list[str] = []
        for field in ("element_type", "layout", "units"):
            produced = getattr(self, field)
            needed = getattr(required, field)
            if produced is None or needed is None:
                continue
            if (produced in _DESCRIPTOR_WILDCARDS
                    or needed in _DESCRIPTOR_WILDCARDS):
                continue
            produced_key = (
                _descriptor_token(produced) if field != "units" else produced
            )
            needed_key = (
                _descriptor_token(needed) if field != "units" else needed
            )
            if produced_key != needed_key:
                issues.append(
                    f"{field} {produced!r} does not satisfy {needed!r}"
                )
        if self.stride is not None and required.stride is not None:
            produced_stride = _descriptor_stride_key(self.stride)
            needed_stride = _descriptor_stride_key(required.stride)
            if produced_stride != needed_stride:
                issues.append(
                    f"stride {list(produced_stride)!r} does not satisfy "
                    f"{list(needed_stride)!r}"
                )
        if (self.rank is not None and required.rank is not None
                and self.rank != required.rank):
            issues.append(
                f"rank {self.rank!r} does not satisfy {required.rank!r}"
            )
        return tuple(issues)


@dataclass(frozen=True)
class MathLeaf:
    """Immutable typed mathematical packet."""

    leaf_id: str
    kind: str
    version: int = 1
    type: dict[str, Any] = field(default_factory=dict)
    content: dict[str, Any] | None = None
    parents: tuple[dict[str, Any], ...] = ()
    operation: dict[str, Any] | None = None
    status: str = "committed"
    provenance: dict[str, Any] = field(default_factory=dict)
    aliases: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    metadata_version: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.leaf_id, str) or not _LEAF_ID_RE.fullmatch(self.leaf_id):
            raise MathObjectError("leaf_id must be an nml: identifier")
        if self.kind not in LEAF_KINDS:
            raise MathObjectError(f"unknown leaf kind: {self.kind!r}")
        _require_int(self.version, "version", minimum=1)
        if not isinstance(self.type, Mapping):
            raise MathObjectError("type must be an object")
        MathTypeDescriptor.from_mapping(
            self.type, "type", include_nested_type=False,
        )
        if self.status not in LEAF_STATUSES:
            raise MathObjectError(f"unknown leaf status: {self.status!r}")
        if self.content is not None and not isinstance(self.content, Mapping):
            raise MathObjectError("content must be an object or null")
        if self.metadata_version is not None:
            _require_int(self.metadata_version, "metadata_version", minimum=1)
        object.__setattr__(self, "type", _freeze_json(self.type))
        object.__setattr__(
            self, "content",
            None if self.content is None else _freeze_json(self.content),
        )
        object.__setattr__(self, "parents", _tuple_of_dicts(self.parents, "parents"))
        object.__setattr__(
            self, "operation",
            None if self.operation is None else _freeze_json(self.operation),
        )
        object.__setattr__(self, "provenance", _freeze_json(self.provenance))
        object.__setattr__(self, "aliases", _tuple_of_dicts(self.aliases, "aliases"))
        object.__setattr__(self, "metadata", _freeze_json(self.metadata))
        if self.kind in {"null", "void", "undefined", "unknown", "error", "cancelled"}:
            if self.content is not None:
                raise MathObjectError(f"{self.kind} leaves must not carry numeric content")
            if not self.metadata.get("reason") and not self.metadata.get("failure_class"):
                raise MathObjectError(f"{self.kind} leaf requires reason/failure_class")
        if self.kind == "result":
            if self.operation is None:
                raise MathObjectError("result leaves require an operation record")
            function_id = self.operation.get("function_id")
            if not isinstance(function_id, str) or not function_id:
                raise MathObjectError(
                    "result leaves require operation.function_id"
                )
            if not self.provenance:
                raise MathObjectError("result leaves require provenance")
            if not any(self.provenance.get(key) for key in _RESULT_PROVENANCE_KEYS):
                raise MathObjectError(
                    "result leaf provenance requires a producer/candidate/job "
                    "identity"
                )

    @property
    def type_descriptor(self) -> MathTypeDescriptor:
        """Optional semantic descriptor declared inside ``type``."""
        return MathTypeDescriptor.from_mapping(
            self.type, "type", include_nested_type=False,
        )

    @property
    def content_digest(self) -> str | None:
        """Declared digest of the canonical payload in ``content["digest"]``.

        ``MathStore`` verifies the declaration against the canonical content
        with the self-describing ``digest`` key removed.
        """
        if self.content is None:
            return None
        digest = self.content.get("digest")
        return None if digest is None else _require_digest(digest, "content.digest", allow_none=True)

    def to_dict(self) -> dict[str, Any]:
        document = {
            "schema": LEAF_SCHEMA,
            "leaf_id": self.leaf_id,
            "version": self.version,
            "kind": self.kind,
            "type": _thaw_json(self.type),
            "content": None if self.content is None else _thaw_json(self.content),
            "parents": [_thaw_json(parent) for parent in self.parents],
            "operation": None if self.operation is None else _thaw_json(self.operation),
            "status": self.status,
            "provenance": _thaw_json(self.provenance),
            "aliases": [_thaw_json(alias) for alias in self.aliases],
            "metadata": _thaw_json(self.metadata),
        }
        if self.metadata_version is not None:
            document["metadata_version"] = self.metadata_version
        return document

    def digest(self) -> str:
        return digest_object(self.to_dict())

    def next_version(self, *, content: dict[str, Any] | None = None,
                     parents: Iterable[dict[str, Any]] | None = None,
                     operation: dict[str, Any] | None = None,
                     metadata: dict[str, Any] | None = None) -> "MathLeaf":
        if self.status != "committed":
            raise MathObjectError("only committed leaves can be versioned")
        return MathLeaf(
            leaf_id=self.leaf_id,
            kind=self.kind,
            version=self.version + 1,
            type=dict(self.type),
            content=dict(content) if content is not None else (None if self.content is None else dict(self.content)),
            parents=tuple(parents) if parents is not None else self.parents,
            operation=operation if operation is not None else self.operation,
            status="committed",
            provenance=dict(self.provenance),
            aliases=self.aliases,
            metadata=dict(metadata) if metadata is not None else dict(self.metadata),
            metadata_version=self.metadata_version,
        )


@dataclass(frozen=True)
class MathFunction:
    """Semantic function contract; implementations are native kernel IDs."""

    function_id: str
    version: int = 1
    signature: dict[str, Any] = field(default_factory=dict)
    semantics: dict[str, Any] = field(default_factory=dict)
    preconditions: tuple[dict[str, Any], ...] = ()
    postconditions: tuple[dict[str, Any], ...] = ()
    undefined_conditions: tuple[dict[str, Any], ...] = ()
    numerical_policy: dict[str, Any] = field(default_factory=dict)
    implementations: tuple[dict[str, Any], ...] = ()
    proof_status: str = "none"
    status: str = "active"
    contract_digest: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.function_id, str) or not _FUNCTION_ID_RE.fullmatch(self.function_id):
            raise MathObjectError("function_id must be a math.<family>.<name> identifier")
        _require_int(self.version, "version", minimum=1)
        if not isinstance(self.signature, Mapping) or not self.signature:
            raise MathObjectError("signature must be a non-empty object")
        raw_inputs = self.signature.get("inputs")
        if isinstance(raw_inputs, (list, tuple)):
            for index, endpoint in enumerate(raw_inputs):
                if isinstance(endpoint, Mapping):
                    MathTypeDescriptor.from_mapping(
                        endpoint, f"signature.inputs[{index}]",
                        include_nested_type=True,
                    )
        output = self.signature.get("output")
        if isinstance(output, Mapping):
            MathTypeDescriptor.from_mapping(
                output, "signature.output", include_nested_type=True,
            )
        if self.proof_status not in PROOF_STATUSES:
            raise MathObjectError(f"unknown proof_status: {self.proof_status!r}")
        if self.status not in {"proposed", "active", "deprecated", "revoked"}:
            raise MathObjectError(f"unknown function status: {self.status!r}")
        object.__setattr__(self, "signature", _freeze_json(self.signature))
        object.__setattr__(self, "semantics", _freeze_json(self.semantics))
        object.__setattr__(self, "preconditions", _tuple_of_dicts(self.preconditions, "preconditions"))
        object.__setattr__(self, "postconditions", _tuple_of_dicts(self.postconditions, "postconditions"))
        object.__setattr__(self, "undefined_conditions", _tuple_of_dicts(self.undefined_conditions, "undefined_conditions"))
        object.__setattr__(self, "numerical_policy", _freeze_json(self.numerical_policy))
        object.__setattr__(self, "implementations", _tuple_of_dicts(self.implementations, "implementations"))
        if self.contract_digest is not None:
            _require_digest(self.contract_digest, "contract_digest")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": FUNCTION_SCHEMA,
            "function_id": self.function_id,
            "version": self.version,
            "signature": _thaw_json(self.signature),
            "semantics": _thaw_json(self.semantics),
            "preconditions": [_thaw_json(x) for x in self.preconditions],
            "postconditions": [_thaw_json(x) for x in self.postconditions],
            "undefined_conditions": [_thaw_json(x) for x in self.undefined_conditions],
            "numerical_policy": _thaw_json(self.numerical_policy),
            "implementations": [_thaw_json(x) for x in self.implementations],
            "proof_status": self.proof_status,
            "status": self.status,
            "contract_digest": self.contract_digest,
        }

    def digest(self) -> str:
        document = self.to_dict()
        document.pop("contract_digest", None)
        return digest_object(document)


@dataclass(frozen=True)
class MathRule:
    rule_id: str
    version: int = 1
    level: int = 1
    contract: dict[str, Any] = field(default_factory=dict)
    proof_status: str = "none"
    status: str = "proposed"
    scope: dict[str, Any] = field(default_factory=dict)
    certificate_digest: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.rule_id, str) or not _RULE_ID_RE.fullmatch(self.rule_id):
            raise MathObjectError("rule_id must be a math.rule.<name> identifier")
        _require_int(self.version, "version", minimum=1)
        if self.level not in RULE_LEVELS:
            raise MathObjectError("rule level must be 0..3")
        if self.proof_status not in PROOF_STATUSES:
            raise MathObjectError(f"unknown proof_status: {self.proof_status!r}")
        if self.status not in RULE_STATUSES:
            raise MathObjectError(f"unknown rule status: {self.status!r}")
        if not isinstance(self.contract, Mapping):
            raise MathObjectError("contract must be an object")
        if self.certificate_digest is not None:
            _require_digest(self.certificate_digest, "certificate_digest")
        object.__setattr__(self, "contract", _freeze_json(self.contract))
        object.__setattr__(self, "scope", _freeze_json(self.scope))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RULE_SCHEMA,
            "rule_id": self.rule_id,
            "version": self.version,
            "level": self.level,
            "scope": _thaw_json(self.scope),
            "contract": _thaw_json(self.contract),
            "proof_status": self.proof_status,
            "status": self.status,
            "certificate_digest": self.certificate_digest,
        }


@dataclass(frozen=True)
class MathCandidate:
    candidate_id: str
    inputs: tuple[dict[str, Any], ...]
    function_id: str
    function_version: int
    outputs: tuple[dict[str, Any], ...] = ()
    snapshot_id: str = ""
    rank: int = 0
    preflight_hint: str = "candidate"
    rejected: tuple[dict[str, Any], ...] = ()
    contract_digest: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_id, str) or not self.candidate_id.startswith("cnd:"):
            raise MathObjectError("candidate_id must start with cnd:")
        if not isinstance(self.function_id, str) or not _FUNCTION_ID_RE.fullmatch(self.function_id):
            raise MathObjectError("invalid function_id")
        _require_int(self.function_version, "function_version", minimum=1)
        _require_int(self.rank, "rank")
        if self.contract_digest is not None:
            _require_digest(self.contract_digest, "contract_digest")
        object.__setattr__(self, "inputs", _tuple_of_dicts(self.inputs, "inputs"))
        object.__setattr__(self, "outputs", _tuple_of_dicts(self.outputs, "outputs"))
        object.__setattr__(self, "rejected", _tuple_of_dicts(self.rejected, "rejected"))
        if not self.inputs:
            raise MathObjectError("candidate requires at least one input")

    def to_dict(self) -> dict[str, Any]:
        document = {
            "schema": CANDIDATE_SCHEMA,
            "candidate_id": self.candidate_id,
            "snapshot_id": self.snapshot_id,
            "function_id": self.function_id,
            "function_version": self.function_version,
            "inputs": [dict(x) for x in self.inputs],
            "outputs": [dict(x) for x in self.outputs],
            "rank": self.rank,
            "preflight_hint": self.preflight_hint,
            "rejected": [dict(x) for x in self.rejected],
        }
        if self.contract_digest is not None:
            document["contract_digest"] = self.contract_digest
        return document


@dataclass(frozen=True)
class MathAdmission:
    admission_id: str
    candidate_id: str
    verdict: str
    snapshot_id: str
    reason: str = ""
    rule_snapshot_id: str = ""
    preflight_digest: str = ""
    scope: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.admission_id, str) or not self.admission_id.startswith("adm:"):
            raise MathObjectError("admission_id must start with adm:")
        if not isinstance(self.candidate_id, str) or not self.candidate_id.startswith("cnd:"):
            raise MathObjectError("candidate_id must start with cnd:")
        if self.verdict not in VERDICTS:
            raise MathObjectError(f"unknown verdict: {self.verdict!r}")
        if not self.snapshot_id:
            raise MathObjectError("snapshot_id is required")
        object.__setattr__(self, "scope", dict(self.scope))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": ADMISSION_SCHEMA,
            "admission_id": self.admission_id,
            "candidate_id": self.candidate_id,
            "verdict": self.verdict,
            "snapshot_id": self.snapshot_id,
            "reason": self.reason,
            "rule_snapshot_id": self.rule_snapshot_id,
            "preflight_digest": self.preflight_digest,
            "scope": dict(self.scope),
        }


def candidate_id_for(snapshot_id: str, inputs: Iterable[Mapping[str, Any]],
                     function_id: str, function_version: int,
                     contract_digest: str | None = None) -> str:
    """Content identity for a candidate; excludes rank/time/producer.

    ``contract_digest`` is optional.  When supplied it binds the candidate to
    the canonical function contract and changes the identity.  When omitted the
    payload is byte-for-byte the legacy candidate identity, so previously issued
    ``cnd:`` identifiers remain valid.
    """
    payload = {
        "snapshot_id": snapshot_id,
        "inputs": [dict(item) for item in inputs],
        "function_id": function_id,
        "function_version": function_version,
    }
    digest = _require_digest(
        contract_digest, "contract_digest", allow_none=True,
    )
    if digest is not None:
        payload["contract_digest"] = digest
    return "cnd:" + digest_object(payload)


def admission_id_for(candidate_id: str, snapshot_id: str, verdict: str,
                     rule_snapshot_id: str = "") -> str:
    return "adm:" + digest_object({
        "candidate_id": candidate_id,
        "snapshot_id": snapshot_id,
        "verdict": verdict,
        "rule_snapshot_id": rule_snapshot_id,
    })


__all__ = [
    "ADMISSION_SCHEMA", "CANDIDATE_SCHEMA", "FUNCTION_SCHEMA", "LEAF_SCHEMA",
    "LEAF_KINDS", "LEAF_STATUSES", "MathAdmission", "MathCandidate",
    "MathFunction", "MathImmutabilityError", "MathLeaf", "MathObjectError",
    "MathRule", "MathTypeDescriptor",
    "PROOF_STATUSES", "RULE_LEVELS", "RULE_STATUSES", "RULE_SCHEMA",
    "TYPE_DESCRIPTOR_ALIASES", "TYPE_DESCRIPTOR_FIELDS",
    "VERDICTS", "admission_id_for", "candidate_id_for", "canonical_json",
    "digest_object", "sha256_text",
]
