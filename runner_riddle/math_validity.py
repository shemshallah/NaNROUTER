"""Authoritative mathematical validity/preflight engine for GAME_PLAN_::.

This module is a control-plane authority.  It compares typed metadata,
digests, declared bounds, rule levels, and structured predicates.  It never
evaluates a mathematical expression, never imports a numerical library, and
never imports the runtime/executor stack (``MthSystem``, ``WaveService``,
point-0, or tile executors).

A candidate may only execute with a current ``VALID`` admission.  A numeric
side condition must carry a certificate digest pinned in the snapshot;
otherwise the engine returns ``UNKNOWN``.  Authorization and capability
outcomes are deliberately separate from mathematical validity.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import re
from typing import Any, Mapping

from .math_objects import (
    ADMISSION_SCHEMA,
    SNAPSHOT_SCHEMA,
    MathAdmission,
    MathCandidate,
    MathFunction,
    MathRule,
    admission_id_for,
    digest_object,
)

VALID = "VALID"
INVALID = "INVALID"
UNDEFINED = "UNDEFINED"
UNAUTHORIZED = "UNAUTHORIZED"
UNSUPPORTED = "UNSUPPORTED"
UNAVAILABLE = "UNAVAILABLE"
STALE = "STALE"
EXPERIMENTAL = "EXPERIMENTAL"
UNKNOWN = "UNKNOWN"

MATH_VERDICTS = frozenset({
    VALID, INVALID, UNDEFINED, UNSUPPORTED, STALE, EXPERIMENTAL, UNKNOWN,
})
TERMINAL_MATH_VERDICTS = frozenset({
    INVALID, UNDEFINED, UNSUPPORTED, STALE, UNKNOWN,
})
EXECUTABLE_VERDICTS = frozenset({VALID})

PREDICATE_STATUSES = frozenset({
    "SATISFIED", "VIOLATED", "UNKNOWN", "UNSUPPORTED",
})

NUMERIC_PREDICATE_OPS = frozenset({
    "numeric", "numeric_eq", "numeric_ne", "lt", "lte", "gt", "gte",
    "nonzero", "non_zero", "norm_le", "norm_ge", "residual_le",
    "residual_ge", "workspace_le", "workspace_ge", "approx_eq",
})

STRUCTURAL_PREDICATE_OPS = frozenset({
    "eq", "equals", "ne", "not_equals", "in", "not_in", "exists",
    "shape_equal", "shape_compatible", "layout_equal", "precision_equal",
    "domain_equal", "domain_compatible", "kind_equal", "alias_ok",
    "certificate", "zero", "is_zero", "always", "never",
})

_ALL_OPS = NUMERIC_PREDICATE_OPS | STRUCTURAL_PREDICATE_OPS

_OP_ALIASES = {
    "==": "eq",
    "=": "eq",
    "!=": "ne",
    "<": "lt",
    "<=": "lte",
    ">": "gt",
    ">=": "gte",
    "equals": "eq",
    "not_equals": "ne",
    "non_zero": "nonzero",
    "is_zero": "zero",
    "equals_zero": "zero",
    "divisor_zero": "zero",
    "divisor_nonzero": "nonzero",
    "nonzero_divisor": "nonzero",
}

_LAYOUT_ALIASES = {
    "row-major": "row_major",
    "rowmajor": "row_major",
    "row_major": "row_major",
    "c": "row_major",
    "col-major": "column_major",
    "colmajor": "column_major",
    "column-major": "column_major",
    "column_major": "column_major",
    "col_major": "column_major",
    "fortran": "column_major",
    "f": "column_major",
    "strided": "strided",
    "dense": "dense",
}

_PRECISION_ALIASES = {
    "f16": "float16",
    "float16": "float16",
    "half": "float16",
    "f32": "float32",
    "float32": "float32",
    "single": "float32",
    "f64": "float64",
    "float64": "float64",
    "double": "float64",
    "int8": "int8",
    "int16": "int16",
    "int32": "int32",
    "int64": "int64",
    "bool": "boolean",
    "boolean": "boolean",
}

_DOMAIN_ALIASES = {
    "r": "real",
    "real": "real",
    "reals": "real",
    "float": "real",
    "q": "rational",
    "rational": "rational",
    "z": "integer",
    "int": "integer",
    "integer": "integer",
    "natural": "integer",
    "n": "integer",
    "bool": "boolean",
    "boolean": "boolean",
    "c": "complex",
    "complex": "complex",
    "any": "any",
}

_KIND_ALIASES = {
    "vec": "vector",
    "vector": "vector",
    "mat": "matrix",
    "matrix": "matrix",
    "tensor": "tensor",
    "scalar": "scalar",
    "relation": "relation",
    "hyperedge": "relation",
    "hypergraph": "hypergraph",
    "rule": "rule",
    "function": "function",
    "result": "result",
}

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_PREFLIGHT_PREFIX = "pf:"
_SEMANTIC_PREFIX = "sem:"
_DISPATCH_PREFIX = "dsp:"

_MISSING = object()


class MathValidityError(ValueError):
    """Base error for invalid snapshot/request/preflight use."""


class MathSnapshotError(MathValidityError):
    """An authoritative snapshot is malformed or violates a pinned rule."""


class AdmissionRejected(MathValidityError):
    """A plan/job is not bound to a current, valid preflight admission."""

    def __init__(self, message: str, *, verdict: str = UNKNOWN,
                 reason: str = "", admission: MathAdmission | None = None) -> None:
        super().__init__(message)
        self.verdict = verdict
        self.reason = reason
        self.admission = admission


MathAdmissionRejected = AdmissionRejected


@dataclass(frozen=True)
class PredicateResult:
    """Structured result for one pre/post/undefined predicate."""

    phase: str
    index: int
    op: str
    status: str
    reason: str = ""
    certificate_digest: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in PREDICATE_STATUSES:
            raise MathValidityError(f"unknown predicate status: {self.status!r}")
        object.__setattr__(self, "detail", _safe_value(self.detail))

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "index": self.index,
            "op": self.op,
            "status": self.status,
            "reason": self.reason,
            "certificate_digest": self.certificate_digest,
            "detail": dict(self.detail),
        }


def _safe_value(value: Any) -> Any:
    """Return a canonical-JSON-safe copy; floats are never interpreted."""
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return {"__host_float__": "forbidden"}
    if isinstance(value, Mapping):
        return {str(key): _safe_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_safe_value(item) for item in value]
    return {"__type__": type(value).__name__}


def _contains_float(value: Any) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, Mapping):
        return any(_contains_float(item) for item in value.values())
    if isinstance(value, (tuple, list, set, frozenset)):
        return any(_contains_float(item) for item in value)
    return False


def _is_int(value: Any, *, minimum: int | None = None) -> bool:
    if isinstance(value, bool) or not isinstance(value, int):
        return False
    return minimum is None or value >= minimum


def _digest_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value[7:] if value.startswith("sha256:") else value
    return text if _DIGEST_RE.fullmatch(text) else None


def _normalise_key(value: Any) -> str:
    return str(value).strip().lower().replace(" ", "_")


def _layout(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return _LAYOUT_ALIASES.get(value.strip().lower(), value.strip().lower())


def _precision(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return _PRECISION_ALIASES.get(value.strip().lower(), value.strip().lower())


def _domain(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return _DOMAIN_ALIASES.get(value.strip().lower(), value.strip().lower())


def _kind(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return _KIND_ALIASES.get(value.strip().lower(), value.strip().lower())


def _domain_compatible(expected: str, actual: str) -> bool:
    if expected == actual or expected == "any":
        return True
    if expected == "real":
        return actual in {"real", "rational", "integer"}
    if expected == "complex":
        return actual in {"complex", "real", "rational", "integer"}
    if expected == "rational":
        return actual in {"rational", "integer"}
    return False


def _mapping_copy(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise MathSnapshotError(f"{name} must be an object")
    return {str(key): item for key, item in value.items()}


def _tuple_of_mappings(value: Any, name: str) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        raise MathSnapshotError(f"{name} must be a list of objects")
    if not isinstance(value, (tuple, list)):
        raise MathSnapshotError(f"{name} must be a list of objects")
    result = []
    for entry in value:
        if not isinstance(entry, Mapping):
            raise MathSnapshotError(f"{name} entries must be objects")
        result.append({str(key): item for key, item in entry.items()})
    return tuple(result)


def _normalise_aliases(value: Any) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        return tuple(
            {"alias": str(alias), "target": str(target)}
            for alias, target in value.items()
        )
    result = []
    for entry in _tuple_of_mappings(value, "aliases"):
        alias = entry.get("alias", entry.get("name", entry.get("from")))
        target = entry.get("target", entry.get("to", entry.get("canonical")))
        if not isinstance(alias, str) or not alias:
            raise MathSnapshotError("alias name must be a non-empty string")
        if not isinstance(target, str) or not target:
            raise MathSnapshotError("alias target must be a non-empty string")
        result.append({"alias": alias, "target": target})
    return tuple(result)


def _normalise_capabilities(value: Any) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        result = []
        for key, item in value.items():
            if isinstance(item, Mapping):
                entry = {str(k): v for k, v in item.items()}
                entry.setdefault("capability_class", str(key))
            else:
                entry = {"capability_class": str(key), "status": str(item)}
            result.append(entry)
        return tuple(result)
    return _tuple_of_mappings(value, "capabilities")


def _normalise_certificates(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = (value,)
    if not isinstance(value, (tuple, list, set, frozenset)):
        raise MathSnapshotError("certificates must be strings")
    result = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise MathSnapshotError("certificate digest must be a string")
        digest = _digest_text(item)
        result.append(digest if digest is not None else item)
    return tuple(sorted(set(result)))


def _function_from_mapping(value: Any) -> MathFunction:
    if isinstance(value, MathFunction):
        return value
    if not isinstance(value, Mapping):
        raise MathSnapshotError("function entries must be MathFunction objects or objects")
    names = (
        "function_id", "version", "signature", "semantics", "preconditions",
        "postconditions", "undefined_conditions", "numerical_policy",
        "implementations", "proof_status", "status", "contract_digest",
    )
    return MathFunction(**{name: value[name] for name in names if name in value})


def _rule_from_mapping(value: Any) -> MathRule:
    if isinstance(value, MathRule):
        return value
    if not isinstance(value, Mapping):
        raise MathSnapshotError("rule entries must be MathRule objects or objects")
    names = (
        "rule_id", "version", "level", "contract", "proof_status", "status",
        "scope", "certificate_digest",
    )
    return MathRule(**{name: value[name] for name in names if name in value})


@dataclass(frozen=True)
class MathSnapshot:
    """A digest-bound set of leaf/function/rule/capability pins.

    The snapshot is input to the validity engine; it is not an admission.
    Leaf pins are metadata records (``leaf_id``, ``version``, optional
    ``content_digest``/``type``/``workspace_words``/``content``).
    """

    snapshot_id: str
    functions: tuple[MathFunction, ...] = ()
    rules: tuple[MathRule, ...] = ()
    leaf_pins: tuple[dict[str, Any], ...] = ()
    aliases: tuple[dict[str, Any], ...] = ()
    capabilities: tuple[dict[str, Any], ...] = ()
    authorization: dict[str, Any] = field(default_factory=dict)
    certificates: tuple[str, ...] = ()
    numerical_policy: dict[str, Any] = field(default_factory=dict)
    resources: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    parent_snapshot_id: str = ""
    rule_snapshot_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot_id, str) or not self.snapshot_id:
            raise MathSnapshotError("snapshot_id must be a non-empty string")
        if not _is_int(self.version, minimum=1):
            raise MathSnapshotError("snapshot version must be an integer >= 1")
        functions = self.functions or ()
        rules = self.rules or ()
        if isinstance(functions, Mapping):
            functions = tuple(functions.values())
        if isinstance(rules, Mapping):
            rules = tuple(rules.values())
        leaf_pins = self.leaf_pins
        if isinstance(leaf_pins, Mapping):
            leaf_pins = tuple(
                dict(pin, leaf_id=pin.get("leaf_id", leaf_id))
                if isinstance(pin, Mapping) else pin
                for leaf_id, pin in leaf_pins.items()
            )
        object.__setattr__(
            self, "functions",
            tuple(_function_from_mapping(item) for item in functions),
        )
        object.__setattr__(
            self, "rules",
            tuple(_rule_from_mapping(item) for item in rules),
        )
        object.__setattr__(self, "leaf_pins", _tuple_of_mappings(leaf_pins, "leaf_pins"))
        object.__setattr__(self, "aliases", _normalise_aliases(self.aliases))
        object.__setattr__(self, "capabilities", _normalise_capabilities(self.capabilities))
        object.__setattr__(self, "authorization", _mapping_copy(self.authorization, "authorization"))
        object.__setattr__(self, "certificates", _normalise_certificates(self.certificates))
        object.__setattr__(self, "numerical_policy", _mapping_copy(self.numerical_policy, "numerical_policy"))
        object.__setattr__(self, "resources", _mapping_copy(self.resources, "resources"))
        object.__setattr__(self, "metadata", _mapping_copy(self.metadata, "metadata"))
        if self.parent_snapshot_id and not isinstance(self.parent_snapshot_id, str):
            raise MathSnapshotError("parent_snapshot_id must be a string")
        if not self.rule_snapshot_id:
            object.__setattr__(self, "rule_snapshot_id", self._compute_rule_snapshot_id())
        elif not isinstance(self.rule_snapshot_id, str):
            raise MathSnapshotError("rule_snapshot_id must be a string")

    def _compute_rule_snapshot_id(self) -> str:
        documents = [
            rule.to_dict()
            for rule in sorted(self.rules, key=lambda item: (item.rule_id, item.version))
        ]
        return "rsn:" + digest_object(documents)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SNAPSHOT_SCHEMA,
            "snapshot_id": self.snapshot_id,
            "version": self.version,
            "parent_snapshot_id": self.parent_snapshot_id,
            "rule_snapshot_id": self.rule_snapshot_id,
            "functions": [function.to_dict() for function in self.functions],
            "rules": [rule.to_dict() for rule in self.rules],
            "leaf_pins": [dict(pin) for pin in self.leaf_pins],
            "aliases": [dict(alias) for alias in self.aliases],
            "capabilities": [dict(capability) for capability in self.capabilities],
            "authorization": dict(self.authorization),
            "certificates": list(self.certificates),
            "numerical_policy": dict(self.numerical_policy),
            "resources": dict(self.resources),
            "metadata": dict(self.metadata),
        }

    def digest(self) -> str:
        return digest_object(self.to_dict())

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MathSnapshot":
        if not isinstance(value, Mapping):
            raise MathSnapshotError("snapshot must be an object")
        return cls(
            snapshot_id=value.get("snapshot_id", ""),
            version=value.get("version", 1),
            parent_snapshot_id=value.get("parent_snapshot_id", ""),
            rule_snapshot_id=value.get("rule_snapshot_id", ""),
            functions=value.get("functions", ()) or (),
            rules=value.get("rules", ()) or (),
            leaf_pins=value.get("leaf_pins", value.get("leaves", ())) or (),
            aliases=value.get("aliases", ()) or (),
            capabilities=value.get("capabilities", ()) or (),
            authorization=value.get("authorization", {}) or {},
            certificates=value.get("certificates", ()) or (),
            numerical_policy=value.get("numerical_policy", {}) or {},
            resources=value.get("resources", {}) or {},
            metadata=value.get("metadata", {}) or {},
        )

    def function(self, function_id: str, version: int) -> MathFunction | None:
        for function in self.functions:
            if function.function_id == function_id and function.version == version:
                return function
        return None

    def leaf_pin(self, leaf_id: str) -> dict[str, Any] | None:
        for pin in self.leaf_pins:
            if pin.get("leaf_id") == leaf_id:
                return pin
        return None


def coerce_snapshot(value: Any) -> MathSnapshot:
    if isinstance(value, MathSnapshot):
        return value
    if isinstance(value, Mapping):
        return MathSnapshot.from_mapping(value)
    raise MathSnapshotError("snapshot must be a MathSnapshot or object")


def _candidate_from_mapping(value: Mapping[str, Any]) -> MathCandidate:
    names = (
        "candidate_id", "inputs", "function_id", "function_version", "outputs",
        "snapshot_id", "rank", "preflight_hint", "rejected", "contract_digest",
    )
    return MathCandidate(**{name: value[name] for name in names if name in value})


def _coerce_candidate(value: Any) -> MathCandidate:
    if isinstance(value, MathCandidate):
        return value
    if isinstance(value, Mapping):
        return _candidate_from_mapping(value)
    raise TypeError("candidate must be a MathCandidate or mapping")


@dataclass(frozen=True)
class _MathDecision:
    verdict: str
    reason: str = ""
    checks: tuple[dict[str, Any], ...] = ()
    predicates: tuple[PredicateResult, ...] = ()
    obligations: tuple[dict[str, Any], ...] = ()
    rule_level: int = 0
    rule_ids: tuple[str, ...] = ()
    isolated: bool = False

    def __post_init__(self) -> None:
        if self.verdict not in MATH_VERDICTS:
            raise MathValidityError(f"unknown math verdict: {self.verdict!r}")


class _PredicateContext:
    def __init__(self, candidate: MathCandidate, function: MathFunction,
                 snapshot: MathSnapshot, inputs: tuple[dict[str, Any], ...],
                 outputs: tuple[dict[str, Any], ...],
                 certificates: frozenset[str]) -> None:
        self.candidate = candidate
        self.function = function
        self.snapshot = snapshot
        self.inputs = inputs
        self.outputs = outputs
        self.certificates = certificates


def _alias_map(aliases: tuple[dict[str, Any], ...]) -> tuple[dict[str, str], str]:
    mapping: dict[str, str] = {}
    for entry in aliases:
        alias = entry.get("alias")
        target = entry.get("target")
        if not isinstance(alias, str) or not isinstance(target, str):
            return {}, "MALFORMED_ALIAS"
        previous = mapping.get(alias)
        if previous is not None and previous != target:
            return {}, "ALIAS_CONFLICT"
        mapping[alias] = target
    resolved: dict[str, str] = {}
    for alias in mapping:
        seen = []
        current = alias
        while current in mapping:
            if current in seen:
                return {}, "ALIAS_CYCLE"
            seen.append(current)
            current = mapping[current]
        resolved[alias] = current
    return resolved, ""


def _input_kind(item: dict[str, Any]) -> str | None:
    type_doc = item.get("type") if isinstance(item.get("type"), Mapping) else {}
    for candidate in (
        item.get("kind"), type_doc.get("kind"), type_doc.get("name"),
        item.get("type") if isinstance(item.get("type"), str) else None,
    ):
        result = _kind(candidate)
        if result is not None:
            return result
    return None


def _input_shape(item: dict[str, Any]) -> list[Any] | None:
    type_doc = item.get("type") if isinstance(item.get("type"), Mapping) else {}
    shape = item.get("shape", type_doc.get("shape"))
    if shape is None:
        return None
    if not isinstance(shape, (tuple, list)):
        return None
    return list(shape)


def _input_precision(item: dict[str, Any]) -> str | None:
    type_doc = item.get("type") if isinstance(item.get("type"), Mapping) else {}
    for key in ("precision", "element", "dtype"):
        value = item.get(key, type_doc.get(key))
        result = _precision(value)
        if result is not None:
            return result
    return None


def _input_domain(item: dict[str, Any]) -> str | None:
    type_doc = item.get("type") if isinstance(item.get("type"), Mapping) else {}
    for key in ("domain", "field"):
        value = item.get(key, type_doc.get(key))
        result = _domain(value)
        if result is not None:
            return result
    return None


def _input_layout(item: dict[str, Any]) -> str | None:
    type_doc = item.get("type") if isinstance(item.get("type"), Mapping) else {}
    for key in ("layout", "order", "memory_order"):
        value = item.get(key, type_doc.get(key))
        result = _layout(value)
        if result is not None:
            return result
    return None


def _shape_matches(expected: list[Any], actual: list[Any]) -> bool:
    if len(expected) != len(actual):
        return False
    for left, right in zip(expected, actual):
        if left in ("*", -1) or left is None:
            continue
        if left != right:
            return False
    return True


def _shape_text(shape: list[Any] | None) -> Any:
    if shape is None:
        return None
    return [_safe_value(item) for item in shape]


def _display(value: Any) -> Any:
    if _contains_float(value):
        return "<host-float-forbidden>"
    return _safe_value(value)


def _resolve_path(root: Any, path: str) -> Any:
    current = root
    for raw_part in path.replace("[", ".").replace("]", "").split("."):
        part = raw_part.strip()
        if not part:
            continue
        if isinstance(current, Mapping):
            if part not in current:
                return _MISSING
            current = current[part]
        elif isinstance(current, (tuple, list)):
            if not part.isdigit():
                return _MISSING
            index = int(part)
            if index < 0 or index >= len(current):
                return _MISSING
            current = current[index]
        else:
            return _MISSING
    return current


def _resolve_ref(ref: Any, context: _PredicateContext) -> Any:
    roots = {
        "candidate": context.candidate.to_dict(),
        "function": context.function.to_dict(),
        "snapshot": context.snapshot.to_dict(),
        "inputs": list(context.inputs),
        "outputs": list(context.outputs),
    }
    if isinstance(ref, str):
        for prefix in ("candidate", "function", "snapshot", "inputs", "outputs"):
            if ref == prefix:
                return roots[prefix]
            if ref.startswith(prefix + ".") or ref.startswith(prefix + "["):
                result = _resolve_path(roots[prefix], ref[len(prefix) + 1:])
                return ref if result is _MISSING else result
        return ref
    if not isinstance(ref, Mapping):
        return ref
    if "literal" in ref:
        return ref["literal"]
    for selector in ("input", "operand", "arg"):
        if selector in ref:
            index = ref[selector]
            if not _is_int(index, minimum=0) or index >= len(context.inputs):
                return _MISSING
            item = context.inputs[index]
            field = ref.get("field", ref.get("path"))
            if field is None:
                return item
            result = _resolve_path(item, str(field))
            return _MISSING if result is _MISSING else result
    if "output" in ref:
        index = ref["output"]
        if not _is_int(index, minimum=0) or index >= len(context.outputs):
            return _MISSING
        item = context.outputs[index]
        field = ref.get("field", ref.get("path"))
        if field is None:
            return item
        result = _resolve_path(item, str(field))
        return _MISSING if result is _MISSING else result
    if "function" in ref:
        field = ref.get("field")
        root = context.function.to_dict()
        if field is None:
            return root
        result = _resolve_path(root, str(field))
        return _MISSING if result is _MISSING else result
    if "snapshot" in ref:
        field = ref.get("field")
        root = context.snapshot.to_dict()
        if field is None:
            return root
        result = _resolve_path(root, str(field))
        return _MISSING if result is _MISSING else result
    if "candidate" in ref:
        field = ref.get("field")
        root = context.candidate.to_dict()
        if field is None:
            return root
        result = _resolve_path(root, str(field))
        return _MISSING if result is _MISSING else result
    if "path" in ref:
        path = ref["path"]
        if isinstance(path, str):
            result = _resolve_path({key: value for key, value in roots.items()}, path)
            if result is not _MISSING:
                return result
            for prefix, root in roots.items():
                if path.startswith(prefix + ".") or path.startswith(prefix + "["):
                    result = _resolve_path(root, path[len(prefix) + 1:])
                    if result is not _MISSING:
                        return result
        return _MISSING
    if "value" in ref:
        return ref["value"]
    return ref


def _legacy_expr_predicate(predicate: Mapping[str, Any]) -> dict[str, Any] | None:
    """Translate the small symbolic expressions used by the function catalogue.

    This is deliberately a closed, audited vocabulary.  It does not evaluate
    arbitrary text and it never performs numeric arithmetic.
    """
    expr = predicate.get("expr")
    if not isinstance(expr, str):
        return None
    compact = re.sub(r"\s+", "", expr).lower()
    shape = {"input": 0, "field": "type.shape"}
    shape_b = {"input": 1, "field": "type.shape"}
    domain = {"input": 0, "field": "type.domain"}
    domain_b = {"input": 1, "field": "type.domain"}
    translated: dict[str, Any] = {}
    if compact in {"shape(a)==shape(b)", "shape(a)equalshape(b)"}:
        translated = {"op": "shape_equal", "left": shape, "right": shape_b}
    elif compact in {"shape(a)!=shape(b)", "shape(a)notequalshape(b)"}:
        translated = {"op": "ne", "left": shape, "right": shape_b}
    elif compact in {"domain(a)compatibledomain(b)", "domain(a)==domain(b)"}:
        translated = {"op": "domain_compatible", "left": domain, "right": domain_b}
    elif compact in {"incompatibledomains", "domain(a)incompatibledomain(b)"}:
        translated = {"op": "ne", "left": domain, "right": domain_b}
    elif compact in {"result==sum_ia[i]*b[i]underthedeclarednumericalpolicy",}:
        translated = {"op": "certificate"}  # a numeric postcondition needs evidence
    else:
        return None
    for key in ("reason", "failure_class", "certificate_digest", "certificate", "value"):
        if key in predicate:
            translated[key] = predicate[key]
    return translated


def _predicate_op(predicate: Mapping[str, Any]) -> str:
    raw = predicate.get(
        "op",
        predicate.get(
            "kind",
            predicate.get("predicate", predicate.get("operator", predicate.get("type"))),
        ),
    )
    if not isinstance(raw, str) or not raw:
        return ""
    op = _normalise_key(raw)
    return _OP_ALIASES.get(op, op)


def _declared_zero(value: Any) -> bool | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value == 0
    if isinstance(value, str):
        text = value.strip()
        if text in {"0", "-0", "+0", "0/1", "-0/1", "+0/1"}:
            return True
        if re.fullmatch(r"[+-]?[0-9]+", text):
            return text.lstrip("+-").lstrip("0") == ""
        fraction = re.fullmatch(r"([+-]?[0-9]+)/([0-9]+)", text)
        if fraction is not None and fraction.group(2).strip("0") != "":
            return fraction.group(1).lstrip("+-").lstrip("0") == ""
        return None
    if isinstance(value, Mapping):
        for key in ("is_zero", "zero"):
            if isinstance(value.get(key), bool):
                return bool(value[key])
        for key in ("value", "canonical", "content", "metadata", "pin", "input", "declared_value"):
            if key in value:
                result = _declared_zero(value[key])
                if result is not None:
                    return result
        if value.get("nonzero") is True:
            return False
    return None


def _certificate_of(predicate: Mapping[str, Any]) -> Any:
    for key in ("certificate_digest", "certificate", "cert"):
        if key in predicate:
            value = predicate[key]
            if isinstance(value, Mapping):
                return value.get("digest", value.get("certificate_digest"))
            return value
    return None


def _predicate_result(phase: str, index: int, op: str, status: str,
                      reason: str = "", certificate: str | None = None,
                      detail: dict[str, Any] | None = None) -> PredicateResult:
    return PredicateResult(
        phase=phase,
        index=index,
        op=op,
        status=status,
        reason=reason,
        certificate_digest=certificate,
        detail=detail or {},
    )


def _evaluate_predicate(predicate: Any, phase: str, index: int,
                        context: _PredicateContext) -> PredicateResult:
    if not isinstance(predicate, Mapping):
        return _predicate_result(
            phase, index, "", "UNSUPPORTED", "PREDICATE_NOT_STRUCTURED",
            detail={"predicate_type": type(predicate).__name__},
        )
    if _contains_float(predicate):
        return _predicate_result(phase, index, "", "UNKNOWN", "HOST_FLOAT_FORBIDDEN")
    if not _predicate_op(predicate):
        translated = _legacy_expr_predicate(predicate)
        if translated is not None:
            predicate = translated
    op = _predicate_op(predicate)
    if op not in _ALL_OPS:
        return _predicate_result(phase, index, op, "UNSUPPORTED", "PREDICATE_OP_UNSUPPORTED")

    custom_reason = predicate.get("reason", predicate.get("failure_class", ""))
    if not isinstance(custom_reason, str):
        custom_reason = ""
    certificate = _certificate_of(predicate)
    certificate_text = _digest_text(certificate) if certificate is not None else None
    certificate_argument = None if certificate is None else (
        certificate_text if certificate_text is not None else str(certificate)
    )

    if op == "always":
        value = predicate.get("value", True)
        status = "SATISFIED" if value is not False else "VIOLATED"
        return _predicate_result(phase, index, op, status, custom_reason)
    if op == "never":
        value = predicate.get("value", True)
        status = "VIOLATED" if value is not False else "SATISFIED"
        return _predicate_result(phase, index, op, status, custom_reason)
    if op == "certificate":
        if certificate is None:
            return _predicate_result(phase, index, op, "UNKNOWN", "CERTIFICATE_REQUIRED")
        if certificate_text is None:
            return _predicate_result(phase, index, op, "VIOLATED", "CERTIFICATE_MALFORMED")
        if certificate_text in context.certificates:
            return _predicate_result(
                phase, index, op, "SATISFIED", custom_reason,
                certificate=certificate_text,
            )
        return _predicate_result(
            phase, index, op, "UNKNOWN", "CERTIFICATE_NOT_PINNED",
            certificate=certificate_text,
        )

    left_ref = predicate.get("left", predicate.get("a"))
    right_ref = predicate.get("right", predicate.get("b"))
    if left_ref is None and "path" in predicate:
        left_ref = {"path": predicate["path"]}
    if right_ref is None and "path" in predicate and "value" in predicate:
        right_ref = {"literal": predicate["value"]}
    elif right_ref is None and "value" in predicate:
        right_ref = {"literal": predicate["value"]}
    left = _resolve_ref(left_ref, context) if left_ref is not None else _MISSING
    right = _resolve_ref(right_ref, context) if right_ref is not None else _MISSING

    if op in {"zero", "nonzero"}:
        ref = predicate.get("operand", predicate.get("input", predicate.get("ref")))
        if ref is None:
            ref = left_ref
        if _is_int(ref, minimum=0):
            ref = {"input": ref}
        value = _resolve_ref(ref, context) if ref is not None else _MISSING
        if value is _MISSING:
            if certificate is not None:
                return _evaluate_numeric_certificate(
                    phase, index, op, certificate_argument, context, custom_reason,
                )
            return _predicate_result(phase, index, op, "UNKNOWN", "OPERAND_NOT_ESTABLISHED")
        zero = _declared_zero(value)
        if zero is None:
            if certificate is not None:
                return _evaluate_numeric_certificate(
                    phase, index, op, certificate_argument, context, custom_reason,
                )
            return _predicate_result(
                phase, index, op, "UNKNOWN",
                "NUMERIC_PREDICATE_CERTIFICATE_REQUIRED",
            )
        if op == "zero":
            status = "SATISFIED" if zero else "VIOLATED"
        else:
            status = "SATISFIED" if not zero else "VIOLATED"
        return _predicate_result(phase, index, op, status, custom_reason)

    if op in NUMERIC_PREDICATE_OPS:
        return _evaluate_numeric_certificate(
            phase, index, op, certificate_argument, context, custom_reason,
        )

    if op == "exists":
        ref = predicate.get("operand", predicate.get("input", predicate.get("ref")))
        if _is_int(ref, minimum=0):
            ref = {"input": ref}
        value = _resolve_ref(ref, context) if ref is not None else left
        status = "SATISFIED" if value is not _MISSING else "VIOLATED"
        return _predicate_result(phase, index, op, status, custom_reason)

    if op in {"eq", "ne"}:
        if left is _MISSING or right is _MISSING:
            return _predicate_result(phase, index, op, "UNKNOWN", "OPERAND_NOT_ESTABLISHED")
        left_zero = _declared_zero(left)
        right_zero = _declared_zero(right)
        if (left_zero is True or right_zero is True) and \
                left_zero is not None and right_zero is not None:
            equal = left_zero == right_zero
            status = "SATISFIED" if (equal if op == "eq" else not equal) else "VIOLATED"
            return _predicate_result(phase, index, op, status, custom_reason)
        if (_is_int(left) or _is_int(right)) and not isinstance(left, (list, tuple, Mapping)) \
                and not isinstance(right, (list, tuple, Mapping)):
            return _evaluate_numeric_certificate(
                phase, index, op, certificate_argument, context, custom_reason,
            )
        equal = _safe_value(left) == _safe_value(right)
        status = "SATISFIED" if (equal if op == "eq" else not equal) else "VIOLATED"
        return _predicate_result(phase, index, op, status, custom_reason)

    if left is _MISSING or right is _MISSING:
        return _predicate_result(phase, index, op, "UNKNOWN", "OPERAND_NOT_ESTABLISHED")

    if op in {"in", "not_in"}:
        options = right if isinstance(right, (tuple, list)) else [right]
        contained = any(_safe_value(left) == _safe_value(option) for option in options)
        status = "SATISFIED" if (contained if op == "in" else not contained) else "VIOLATED"
        return _predicate_result(phase, index, op, status, custom_reason)

    if op in {"shape_equal", "shape_compatible"}:
        if not isinstance(left, (tuple, list)) or not isinstance(right, (tuple, list)):
            return _predicate_result(phase, index, op, "UNKNOWN", "SHAPE_UNKNOWN")
        left_shape = list(left)
        right_shape = list(right)
        if op == "shape_equal":
            matched = left_shape == right_shape
        else:
            matched = _shape_matches(left_shape, right_shape)
        return _predicate_result(
            phase, index, op, "SATISFIED" if matched else "VIOLATED",
            custom_reason if not matched else "",
            detail={"left_shape": _shape_text(left_shape), "right_shape": _shape_text(right_shape)},
        )

    if op == "layout_equal":
        left_layout = _layout(left)
        right_layout = _layout(right)
        if left_layout is None or right_layout is None:
            return _predicate_result(phase, index, op, "UNKNOWN", "LAYOUT_UNKNOWN")
        return _predicate_result(
            phase, index, op, "SATISFIED" if left_layout == right_layout else "VIOLATED",
            custom_reason,
        )

    if op == "precision_equal":
        left_precision = _precision(left)
        right_precision = _precision(right)
        if left_precision is None or right_precision is None:
            return _predicate_result(phase, index, op, "UNKNOWN", "PRECISION_UNKNOWN")
        return _predicate_result(
            phase, index, op,
            "SATISFIED" if left_precision == right_precision else "VIOLATED",
            custom_reason,
        )

    if op in {"domain_equal", "domain_compatible"}:
        left_domain = _domain(left)
        right_domain = _domain(right)
        if left_domain is None or right_domain is None:
            return _predicate_result(phase, index, op, "UNKNOWN", "DOMAIN_UNKNOWN")
        if op == "domain_equal":
            matched = left_domain == right_domain
        else:
            matched = _domain_compatible(left_domain, right_domain)
        return _predicate_result(
            phase, index, op, "SATISFIED" if matched else "VIOLATED", custom_reason,
        )

    if op == "kind_equal":
        left_kind = _kind(left)
        right_kind = _kind(right)
        if left_kind is None or right_kind is None:
            return _predicate_result(phase, index, op, "UNKNOWN", "KIND_UNKNOWN")
        return _predicate_result(
            phase, index, op, "SATISFIED" if left_kind == right_kind else "VIOLATED",
            custom_reason,
        )

    if op == "alias_ok":
        mapping, error = _alias_map(context.snapshot.aliases)
        if error:
            return _predicate_result(phase, index, op, "VIOLATED", error)
        left_name = left if isinstance(left, str) else _kind(left)
        right_name = right if isinstance(right, str) else _kind(right)
        if left_name is None or right_name is None:
            return _predicate_result(phase, index, op, "UNKNOWN", "ALIAS_TARGET_UNKNOWN")
        canonical = mapping.get(left_name, left_name)
        matched = canonical == right_name or _kind(canonical) == _kind(right_name)
        return _predicate_result(
            phase, index, op, "SATISFIED" if matched else "VIOLATED",
            "" if matched else (custom_reason or "ALIAS_CONFLICT"),
        )

    return _predicate_result(phase, index, op, "UNSUPPORTED", "PREDICATE_OP_UNSUPPORTED")


def _evaluate_numeric_certificate(phase: str, index: int, op: str,
                                  certificate: str | None,
                                  context: _PredicateContext,
                                  custom_reason: str) -> PredicateResult:
    if certificate is None:
        return _predicate_result(
            phase, index, op, "UNKNOWN", "NUMERIC_PREDICATE_CERTIFICATE_REQUIRED",
        )
    if _DIGEST_RE.fullmatch(certificate) is None:
        return _predicate_result(
            phase, index, op, "VIOLATED", "CERTIFICATE_MALFORMED",
            certificate=certificate,
        )
    if certificate in context.certificates:
        return _predicate_result(
            phase, index, op, "SATISFIED", custom_reason, certificate=certificate,
        )
    return _predicate_result(
        phase, index, op, "UNKNOWN", "CERTIFICATE_NOT_PINNED",
        certificate=certificate,
    )


def evaluate_predicates(predicates: Any, context: Any, *, phase: str = "precondition") -> tuple[PredicateResult, ...]:
    """Evaluate structured predicates against a metadata context.

    ``context`` must be a ``_PredicateContext``-compatible mapping with
    ``candidate``, ``function``, ``snapshot``, ``inputs``, ``outputs`` and
    ``certificates`` keys.  This helper is exposed for tests and evidence
    tooling; preflight uses the same evaluator.
    """
    if not isinstance(context, _PredicateContext):
        if not isinstance(context, Mapping):
            raise TypeError("predicate context must be a mapping")
        context = _PredicateContext(
            candidate=_coerce_candidate(context.get("candidate")),
            function=context.get("function"),
            snapshot=coerce_snapshot(context.get("snapshot")),
            inputs=tuple(context.get("inputs", ())),
            outputs=tuple(context.get("outputs", ())),
            certificates=frozenset(_normalise_certificates(context.get("certificates", ()))),
        )
    if not isinstance(predicates, (tuple, list)):
        predicates = (predicates,)
    return tuple(
        _evaluate_predicate(predicate, phase, index, context)
        for index, predicate in enumerate(predicates)
    )


class MathPreflightCache:
    """Two-level deterministic preflight cache.

    The semantic cache contains only the mathematical decision and excludes
    time, slot, runner, authorization, and capability context.  The dispatch
    cache contains the final admission and includes the authorization,
    capability, and dispatch context digests.
    """

    def __init__(self, max_entries: int = 256) -> None:
        if not _is_int(max_entries, minimum=1):
            raise MathValidityError("max_entries must be a positive integer")
        self.max_entries = max_entries
        self._semantic: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._dispatch: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.hits = 0
        self.misses = 0

    @property
    def semantic_size(self) -> int:
        return len(self._semantic)

    @property
    def dispatch_size(self) -> int:
        return len(self._dispatch)

    def semantic_key_present(self, key: str) -> bool:
        return key in self._semantic

    def dispatch_key_present(self, key: str) -> bool:
        return key in self._dispatch

    def _store(self, bucket: OrderedDict[str, dict[str, Any]], key: str,
               value: Any, snapshot_id: str, rule_snapshot_id: str) -> None:
        bucket[key] = {
            "value": value,
            "snapshot_id": snapshot_id,
            "rule_snapshot_id": rule_snapshot_id,
        }
        bucket.move_to_end(key)
        while len(bucket) > self.max_entries:
            bucket.popitem(last=False)

    def _load(self, bucket: OrderedDict[str, dict[str, Any]], key: str,
              snapshot_id: str, rule_snapshot_id: str) -> Any:
        entry = bucket.get(key)
        if entry is None:
            self.misses += 1
            return None
        if entry["snapshot_id"] != snapshot_id or entry["rule_snapshot_id"] != rule_snapshot_id:
            del bucket[key]
            self.misses += 1
            return None
        bucket.move_to_end(key)
        self.hits += 1
        return entry["value"]

    def put_semantic(self, key: str, value: Any, *, snapshot_id: str,
                     rule_snapshot_id: str) -> None:
        self._store(self._semantic, key, value, snapshot_id, rule_snapshot_id)

    def get_semantic(self, key: str, *, snapshot_id: str,
                     rule_snapshot_id: str) -> Any:
        return self._load(self._semantic, key, snapshot_id, rule_snapshot_id)

    def put_dispatch(self, key: str, value: MathAdmission, *, snapshot_id: str,
                     rule_snapshot_id: str) -> None:
        self._store(self._dispatch, key, value, snapshot_id, rule_snapshot_id)

    def get_dispatch(self, key: str, *, snapshot_id: str,
                     rule_snapshot_id: str) -> MathAdmission | None:
        return self._load(self._dispatch, key, snapshot_id, rule_snapshot_id)

    def invalidate_semantic(self, key: str | None = None) -> int:
        if key is None:
            count = len(self._semantic)
            self._semantic.clear()
            return count
        return 1 if self._semantic.pop(key, None) is not None else 0

    def invalidate_dispatch(self, key: str | None = None) -> int:
        if key is None:
            count = len(self._dispatch)
            self._dispatch.clear()
            return count
        return 1 if self._dispatch.pop(key, None) is not None else 0

    def invalidate_snapshot(self, snapshot_id: str) -> int:
        count = 0
        for bucket in (self._semantic, self._dispatch):
            for key in tuple(bucket):
                if bucket[key]["snapshot_id"] == snapshot_id:
                    del bucket[key]
                    count += 1
        return count

    def invalidate_all(self, reason: str = "") -> int:
        count = len(self._semantic) + len(self._dispatch)
        self._semantic.clear()
        self._dispatch.clear()
        self.last_invalidation_reason = reason
        return count

    def stats(self) -> dict[str, int]:
        return {
            "semantic_size": self.semantic_size,
            "dispatch_size": self.dispatch_size,
            "hits": self.hits,
            "misses": self.misses,
        }


class MathValidityEngine:
    """The only writer of mathematical preflight admissions.

    Construction installs the authoritative snapshot.  ``install_snapshot`` is
    transactional for level-0 immutability and rule-level promotion: a level-0
    rule cannot be changed/removed, and a rule cannot silently change level.
    """

    def __init__(self, snapshot: Any = None, *, authorization: Any = None,
                 capabilities: Any = None, certificates: Any = None,
                 dispatch_context: Any = None, cache: MathPreflightCache | None = None,
                 max_cache_entries: int = 256,
                 baseline_snapshot: Any = None) -> None:
        self._snapshot: MathSnapshot | None = None
        self._generation = 0
        self._cache = cache if cache is not None else MathPreflightCache(max_cache_entries)
        self._issued: dict[str, MathAdmission] = {}
        self._issued_by_id: dict[str, MathAdmission] = {}
        self._level0: dict[str, dict[str, Any]] = {}
        self._rule_history: dict[str, dict[str, Any]] = {}
        self._authorization_override = None if authorization is None else _mapping_copy(
            authorization, "authorization",
        )
        self._capability_override = None if capabilities is None else _normalise_capabilities(
            capabilities,
        )
        self._certificate_override = _normalise_certificates(certificates)
        self._dispatch_context = _mapping_copy(dispatch_context, "dispatch_context")
        if baseline_snapshot is not None:
            self.install_snapshot(baseline_snapshot)
        if snapshot is not None:
            self.install_snapshot(snapshot)

    @property
    def snapshot(self) -> MathSnapshot | None:
        return self._snapshot

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def cache(self) -> MathPreflightCache:
        return self._cache

    @property
    def dispatch_context(self) -> dict[str, Any]:
        return dict(self._dispatch_context)

    @property
    def rule_snapshot_id(self) -> str:
        return "" if self._snapshot is None else self._snapshot.rule_snapshot_id

    def install_snapshot(self, snapshot: Any, *,
                         allow_level0_change: bool = False,
                         allow_rule_level_change: bool = False) -> MathSnapshot:
        candidate = coerce_snapshot(snapshot)
        self._check_snapshot_structure(candidate)
        previous = self._snapshot
        if previous is not None:
            if candidate.snapshot_id == previous.snapshot_id and \
                    candidate.digest() != previous.digest():
                raise MathSnapshotError(
                    "SNAPSHOT_ID_REUSED: snapshot_id is bound to different content",
                )
            self._check_rule_transition(
                candidate,
                allow_level0_change=allow_level0_change,
                allow_rule_level_change=allow_rule_level_change,
            )
        if not self._level0:
            self._level0 = {
                rule.rule_id: {
                    "version": rule.version,
                    "level": rule.level,
                    "digest": digest_object(rule.to_dict()),
                }
                for rule in candidate.rules
                if rule.level == 0
            }
        self._remember_rules(candidate)
        self._snapshot = candidate
        self._generation += 1
        self._cache.invalidate_all("SNAPSHOT_INSTALLED")
        return candidate

    def _check_snapshot_structure(self, snapshot: MathSnapshot) -> None:
        function_keys = set()
        for function in snapshot.functions:
            key = (function.function_id, function.version)
            if key in function_keys:
                raise MathSnapshotError(
                    f"duplicate function version: {function.function_id}@{function.version}",
                )
            function_keys.add(key)
        rule_keys = set()
        for rule in snapshot.rules:
            key = (rule.rule_id, rule.version)
            if key in rule_keys:
                raise MathSnapshotError(
                    f"duplicate rule version: {rule.rule_id}@{rule.version}",
                )
            rule_keys.add(key)

    def _check_rule_transition(self, snapshot: MathSnapshot, *,
                               allow_level0_change: bool,
                               allow_rule_level_change: bool) -> None:
        if not allow_level0_change:
            current_level0 = {
                rule.rule_id: rule for rule in snapshot.rules if rule.level == 0
            }
            for rule_id, baseline in self._level0.items():
                rule = current_level0.get(rule_id)
                if rule is None:
                    raise MathSnapshotError(
                        f"LEVEL0_IMMUTABLE: level-0 rule removed: {rule_id}",
                    )
                if rule.version != baseline["version"] or \
                        digest_object(rule.to_dict()) != baseline["digest"]:
                    raise MathSnapshotError(
                        f"LEVEL0_IMMUTABLE: level-0 rule changed: {rule_id}",
                    )
        for rule in snapshot.rules:
            history = self._rule_history.get(rule.rule_id)
            if history is None:
                continue
            if rule.level != history["level"] and not allow_rule_level_change:
                raise MathSnapshotError(
                    "RULE_LEVEL_CHANGE_REQUIRES_PROMOTION: "
                    f"{rule.rule_id} was level {history['level']} and is now "
                    f"level {rule.level}",
                )
            old = self._rule_history.get(
                f"{rule.rule_id}@{rule.version}",
            )
            if old is not None and old != digest_object(rule.to_dict()):
                raise MathSnapshotError(
                    f"RULE_VERSION_IMMUTABLE: {rule.rule_id}@{rule.version}",
                )

    def _remember_rules(self, snapshot: MathSnapshot) -> None:
        for rule in snapshot.rules:
            digest = digest_object(rule.to_dict())
            existing = self._rule_history.get(rule.rule_id)
            if existing is None or rule.version >= existing["version"]:
                self._rule_history[rule.rule_id] = {
                    "version": rule.version,
                    "level": rule.level,
                    "digest": digest,
                }
            self._rule_history[f"{rule.rule_id}@{rule.version}"] = digest

    def set_authorization(self, authorization: Any) -> None:
        self._authorization_override = _mapping_copy(authorization, "authorization")
        self._cache.invalidate_all("AUTHORIZATION_CHANGED")

    def set_capabilities(self, capabilities: Any) -> None:
        self._capability_override = _normalise_capabilities(capabilities)
        self._cache.invalidate_all("CAPABILITY_CHANGED")

    def set_certificates(self, certificates: Any) -> None:
        self._certificate_override = _normalise_certificates(certificates)
        self._cache.invalidate_all("CERTIFICATES_CHANGED")

    def set_dispatch_context(self, context: Any) -> None:
        self._dispatch_context = _mapping_copy(context, "dispatch_context")
        self._cache.invalidate_dispatch()

    def invalidate_cache(self, reason: str = "MANUAL") -> int:
        return self._cache.invalidate_all(reason)

    def current_authorization(self, override: Any = None) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self._snapshot is not None:
            result.update(self._snapshot.authorization)
        if self._authorization_override is not None:
            result.update(self._authorization_override)
        if override is not None:
            result.update(_mapping_copy(override, "authorization"))
        return _safe_value(result)

    def current_capabilities(self, override: Any = None) -> tuple[dict[str, Any], ...]:
        if override is not None:
            return _normalise_capabilities(override)
        if self._capability_override is not None:
            return self._capability_override
        if self._snapshot is not None:
            return self._snapshot.capabilities
        return ()

    def current_certificates(self) -> frozenset[str]:
        values = set(self._certificate_override)
        if self._snapshot is not None:
            values.update(self._snapshot.certificates)
        return frozenset(values)

    def _resolve_snapshot(self, snapshot: Any) -> tuple[MathSnapshot, str]:
        if snapshot is None:
            if self._snapshot is None:
                raise MathValidityError("no authoritative snapshot is installed")
            return self._snapshot, ""
        candidate = coerce_snapshot(snapshot)
        if self._snapshot is None:
            self.install_snapshot(candidate)
            return self._snapshot, ""
        if candidate.snapshot_id != self._snapshot.snapshot_id:
            return candidate, "STALE_SNAPSHOT"
        if candidate.digest() != self._snapshot.digest():
            return candidate, "STALE_SNAPSHOT_CONTENT"
        return self._snapshot, ""

    def _resolve_function(self, candidate: MathCandidate, snapshot: MathSnapshot,
                          function: Any) -> tuple[MathFunction | None, str, str]:
        if function is not None and not isinstance(function, MathFunction):
            raise TypeError("function must be a MathFunction")
        snapshot_function = snapshot.function(
            candidate.function_id, candidate.function_version,
        )
        if function is not None:
            if function.function_id != candidate.function_id or \
                    function.version != candidate.function_version:
                return None, INVALID, "FUNCTION_PIN_MISMATCH"
            if snapshot_function is None:
                if not any(
                    item.function_id == candidate.function_id
                    for item in snapshot.functions
                ):
                    return None, UNSUPPORTED, "UNKNOWN_FUNCTION"
                return None, STALE, "STALE_FUNCTION_VERSION"
            if digest_object(function.to_dict()) != digest_object(snapshot_function.to_dict()):
                return None, STALE, "STALE_FUNCTION_CONTRACT"
            return snapshot_function, "", ""
        if snapshot_function is None:
            if not any(
                item.function_id == candidate.function_id
                for item in snapshot.functions
            ):
                return None, UNSUPPORTED, "UNKNOWN_FUNCTION"
            return None, STALE, "STALE_FUNCTION_VERSION"
        return snapshot_function, "", ""

    def semantic_key(self, candidate: Any, function: Any = None,
                     snapshot: Any = None, rules: Any = None, *,
                     isolated: bool = False,
                     enforce_postconditions: bool = False) -> str:
        candidate = _coerce_candidate(candidate)
        if snapshot is None:
            if self._snapshot is None:
                raise MathValidityError("no authoritative snapshot is installed")
            snapshot = self._snapshot
        else:
            snapshot = coerce_snapshot(snapshot)
        function_object = function if isinstance(function, MathFunction) else None
        if function_object is None:
            function_object = snapshot.function(
                candidate.function_id, candidate.function_version,
            )
        requested_rules = ()
        if rules is not None:
            requested_rules = tuple(sorted(
                digest_object(rule.to_dict())
                for rule in _normalise_rule_argument(rules)
            ))
        payload = {
            "v": 1,
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_digest": snapshot.digest(),
            "rule_snapshot_id": snapshot.rule_snapshot_id,
            "function": None if function_object is None else function_object.to_dict(),
            "candidate_function": {
                "function_id": candidate.function_id,
                "function_version": candidate.function_version,
            },
            "inputs": [_safe_value(item) for item in candidate.inputs],
            "outputs": [_safe_value(item) for item in candidate.outputs],
            "numerical_policy": _safe_value({
                **snapshot.numerical_policy,
                **({} if function_object is None else function_object.numerical_policy),
            }),
            "resources": _safe_value(snapshot.resources),
            "aliases": _safe_value(snapshot.aliases),
            "certificates": sorted(snapshot.certificates),
            "requested_rules": requested_rules,
            "isolated": bool(isolated),
            "enforce_postconditions": bool(enforce_postconditions),
        }
        return _SEMANTIC_PREFIX + digest_object(payload)

    def dispatch_key(self, semantic_key: str, *, authorization: Any = None,
                     capabilities: Any = None, isolated: bool = False) -> str:
        authorization_digest = digest_object(
            self.current_authorization(authorization),
        )
        capability_digest = digest_object(
            [_safe_value(item) for item in self.current_capabilities(capabilities)],
        )
        payload = {
            "v": 1,
            "semantic_key": semantic_key,
            "authorization_digest": authorization_digest,
            "capability_digest": capability_digest,
            "dispatch_context": _safe_value(self._dispatch_context),
            "isolated": bool(isolated),
        }
        return _DISPATCH_PREFIX + digest_object(payload)

    def preflight(self, candidate: Any, snapshot: Any = None, function: Any = None,
                  rules: Any = None, *, authorization: Any = None,
                  capabilities: Any = None, capability: Any = None,
                  isolated: bool = False, use_cache: bool = True,
                  enforce_postconditions: bool = False) -> MathAdmission:
        candidate = _coerce_candidate(candidate)
        if isinstance(snapshot, MathFunction):
            if function is not None and rules is None:
                rules = function
            function = snapshot
            snapshot = None
        elif isinstance(snapshot, MathRule):
            if rules is None:
                rules = (snapshot,)
            snapshot = None
        elif isinstance(snapshot, (tuple, list)) and all(
                isinstance(item, MathRule) for item in snapshot):
            if rules is None:
                rules = snapshot
            snapshot = None
        if capability is not None:
            if capabilities is not None:
                raise MathValidityError("pass capabilities or capability, not both")
            capabilities = capability
        if rules is not None:
            rules = _normalise_rule_argument(rules)

        snapshot_object, stale_reason = self._resolve_snapshot(snapshot)
        if stale_reason:
            decision = _MathDecision(
                STALE,
                stale_reason,
                checks=({
                    "check": "snapshot",
                    "status": "FAIL",
                    "reason": stale_reason,
                },),
            )
            semantic = self.semantic_key(
                candidate, function=function, snapshot=snapshot_object,
                rules=rules, isolated=isolated,
                enforce_postconditions=enforce_postconditions,
            )
            dispatch = self.dispatch_key(
                semantic, authorization=authorization,
                capabilities=capabilities, isolated=isolated,
            )
            return self._build_admission(
                candidate, snapshot_object, decision,
                authorization_outcome=None, capability_outcome=None,
                semantic_key=semantic, dispatch_key=dispatch,
                cache_state="miss",
                admission_snapshot_id=candidate.snapshot_id or snapshot_object.snapshot_id,
            )

        if not candidate.snapshot_id:
            decision = self._terminal(INVALID, "SNAPSHOT_PIN_REQUIRED")
            semantic = self.semantic_key(
                candidate, function=function, snapshot=snapshot_object,
                rules=rules, isolated=isolated,
                enforce_postconditions=enforce_postconditions,
            )
            dispatch = self.dispatch_key(
                semantic, authorization=authorization,
                capabilities=capabilities, isolated=isolated,
            )
            return self._build_admission(
                candidate, snapshot_object, decision,
                authorization_outcome=None, capability_outcome=None,
                semantic_key=semantic, dispatch_key=dispatch,
                cache_state="miss",
            )
        if candidate.snapshot_id != snapshot_object.snapshot_id:
            decision = self._terminal(STALE, "STALE_SNAPSHOT")
            semantic = self.semantic_key(
                candidate, function=function, snapshot=snapshot_object,
                rules=rules, isolated=isolated,
                enforce_postconditions=enforce_postconditions,
            )
            dispatch = self.dispatch_key(
                semantic, authorization=authorization,
                capabilities=capabilities, isolated=isolated,
            )
            return self._build_admission(
                candidate, snapshot_object, decision,
                authorization_outcome=None, capability_outcome=None,
                semantic_key=semantic, dispatch_key=dispatch,
                cache_state="miss",
            )

        function_object, verdict, reason = self._resolve_function(
            candidate, snapshot_object, function,
        )
        if function_object is None:
            decision = self._terminal(verdict, reason)
            semantic = self.semantic_key(
                candidate, function=function, snapshot=snapshot_object,
                rules=rules, isolated=isolated,
                enforce_postconditions=enforce_postconditions,
            )
            dispatch = self.dispatch_key(
                semantic, authorization=authorization,
                capabilities=capabilities, isolated=isolated,
            )
            return self._build_admission(
                candidate, snapshot_object, decision,
                authorization_outcome=None, capability_outcome=None,
                semantic_key=semantic, dispatch_key=dispatch,
                cache_state="miss",
            )

        semantic = self.semantic_key(
            candidate, function=function_object, snapshot=snapshot_object,
            rules=rules, isolated=isolated,
            enforce_postconditions=enforce_postconditions,
        )
        dispatch = self.dispatch_key(
            semantic, authorization=authorization,
            capabilities=capabilities, isolated=isolated,
        )
        if use_cache:
            cached = self._cache.get_dispatch(
                dispatch,
                snapshot_id=snapshot_object.snapshot_id,
                rule_snapshot_id=snapshot_object.rule_snapshot_id,
            )
            if cached is not None:
                self._remember_admission(cached)
                return cached

        cache_state = "miss"
        decision = None
        if use_cache:
            decision = self._cache.get_semantic(
                semantic,
                snapshot_id=snapshot_object.snapshot_id,
                rule_snapshot_id=snapshot_object.rule_snapshot_id,
            )
            if decision is not None:
                cache_state = "semantic-hit"

        if decision is None:
            decision = self._evaluate_math(
                candidate, function_object, snapshot_object, rules,
                isolated=isolated,
                enforce_postconditions=enforce_postconditions,
            )
            if use_cache:
                self._cache.put_semantic(
                    semantic, decision,
                    snapshot_id=snapshot_object.snapshot_id,
                    rule_snapshot_id=snapshot_object.rule_snapshot_id,
                )

        authorization_outcome = None
        capability_outcome = None
        if decision.verdict in {VALID, EXPERIMENTAL}:
            authorization_outcome = self._authorization_outcome(
                function_object, authorization,
            )
            if authorization_outcome["status"] != "DENIED":
                capability_outcome = self._capability_outcome(
                    function_object, snapshot_object, capabilities,
                )

        admission = self._build_admission(
            candidate, snapshot_object, decision,
            authorization_outcome=authorization_outcome,
            capability_outcome=capability_outcome,
            semantic_key=semantic, dispatch_key=dispatch,
            cache_state=cache_state,
        )
        if use_cache:
            self._cache.put_dispatch(
                dispatch, admission,
                snapshot_id=snapshot_object.snapshot_id,
                rule_snapshot_id=snapshot_object.rule_snapshot_id,
            )
        return admission

    def admit(self, candidate: Any, snapshot: Any = None, function: Any = None,
              rules: Any = None, **kwargs: Any) -> MathAdmission:
        return self.preflight(candidate, snapshot, function, rules, **kwargs)

    def _terminal(self, verdict: str, reason: str) -> _MathDecision:
        return _MathDecision(verdict, reason)

    def _evaluate_math(self, candidate: MathCandidate, function: MathFunction,
                       snapshot: MathSnapshot, rules: Any, *,
                       isolated: bool, enforce_postconditions: bool) -> _MathDecision:
        if function.status == "revoked":
            return self._terminal(UNSUPPORTED, "FUNCTION_REVOKED")
        if function.status == "deprecated":
            return self._terminal(UNSUPPORTED, "FUNCTION_DEPRECATED")

        checks: list[dict[str, Any]] = []
        level0_problem = self._validate_level0_against_baseline(snapshot)
        if level0_problem:
            return self._terminal(INVALID, level0_problem)

        resolved_inputs, input_decision, input_checks = self._resolve_inputs(
            candidate, snapshot,
        )
        checks.extend(input_checks)
        if input_decision is not None:
            return _MathDecision(
                input_decision.verdict, input_decision.reason,
                checks=tuple(checks), rule_level=0,
            )

        alias_mapping, alias_error = _alias_map(snapshot.aliases)
        if alias_error:
            return _MathDecision(
                INVALID, alias_error, checks=tuple(checks),
            )

        signature_decision = self._check_signature(
            candidate, function, resolved_inputs, alias_mapping, checks,
        )
        if signature_decision is not None:
            return _MathDecision(
                signature_decision.verdict, signature_decision.reason,
                checks=tuple(checks),
                rule_level=0,
            )

        output_decision = self._check_outputs(
            candidate, function, alias_mapping, checks,
        )
        if output_decision is not None:
            return _MathDecision(
                output_decision.verdict, output_decision.reason,
                checks=tuple(checks), rule_level=0,
            )

        workspace_decision = self._check_workspace(
            candidate, function, snapshot, resolved_inputs, checks,
        )
        if workspace_decision is not None:
            return _MathDecision(
                workspace_decision.verdict, workspace_decision.reason,
                checks=tuple(checks), rule_level=0,
            )

        rule_decision = self._evaluate_rules(
            function, snapshot, rules, isolated=isolated,
        )
        checks.extend(rule_decision.checks)
        if rule_decision.verdict in TERMINAL_MATH_VERDICTS:
            return _MathDecision(
                rule_decision.verdict, rule_decision.reason,
                checks=tuple(checks),
                predicates=rule_decision.predicates,
                obligations=rule_decision.obligations,
                rule_level=rule_decision.rule_level,
                rule_ids=rule_decision.rule_ids,
                isolated=rule_decision.isolated,
            )

        context = _PredicateContext(
            candidate=candidate,
            function=function,
            snapshot=snapshot,
            inputs=tuple(resolved_inputs),
            outputs=tuple(dict(item) for item in candidate.outputs),
            certificates=self.current_certificates(),
        )
        predicate_decision = self._evaluate_conditions(
            function, context,
            enforce_postconditions=enforce_postconditions or bool(candidate.outputs),
        )
        checks.extend(predicate_decision.checks)
        if predicate_decision.verdict in TERMINAL_MATH_VERDICTS:
            return _MathDecision(
                predicate_decision.verdict, predicate_decision.reason,
                checks=tuple(checks),
                predicates=predicate_decision.predicates,
                obligations=predicate_decision.obligations,
                rule_level=rule_decision.rule_level,
                rule_ids=rule_decision.rule_ids,
                isolated=rule_decision.isolated,
            )

        isolated_result = (
            rule_decision.isolated
            or bool(function.semantics.get("experimental"))
            or function.semantics.get("isolation") in {"experimental", "level3", "level_3"}
            or function.status == "proposed"
        )
        if isolated_result:
            return _MathDecision(
                EXPERIMENTAL, "LEVEL3_ISOLATION",
                checks=tuple(checks),
                predicates=predicate_decision.predicates,
                obligations=predicate_decision.obligations,
                rule_level=max(rule_decision.rule_level, 3),
                rule_ids=rule_decision.rule_ids,
                isolated=True,
            )
        return _MathDecision(
            VALID, "",
            checks=tuple(checks),
            predicates=predicate_decision.predicates,
            obligations=predicate_decision.obligations,
            rule_level=rule_decision.rule_level,
            rule_ids=rule_decision.rule_ids,
            isolated=False,
        )

    def _validate_level0_against_baseline(self, snapshot: MathSnapshot) -> str:
        for rule in snapshot.rules:
            if rule.level != 0:
                continue
            baseline = self._level0.get(rule.rule_id)
            if baseline is None:
                continue
            if rule.version != baseline["version"] or \
                    digest_object(rule.to_dict()) != baseline["digest"]:
                return f"LEVEL0_IMMUTABLE:{rule.rule_id}"
        for rule_id in self._level0:
            if not any(rule.rule_id == rule_id for rule in snapshot.rules):
                return f"LEVEL0_IMMUTABLE:{rule_id}"
        return ""

    def _resolve_inputs(self, candidate: MathCandidate, snapshot: MathSnapshot
                        ) -> tuple[list[dict[str, Any]], _MathDecision | None,
                                   tuple[dict[str, Any], ...]]:
        pins: dict[str, dict[str, Any]] = {}
        for pin in snapshot.leaf_pins:
            leaf_id = pin.get("leaf_id")
            if isinstance(leaf_id, str):
                pins[leaf_id] = pin
        alias_mapping, alias_error = _alias_map(snapshot.aliases)
        if alias_error:
            return [], self._terminal(INVALID, alias_error), ()
        resolved = []
        checks = []
        for index, raw in enumerate(candidate.inputs):
            if _contains_float(raw):
                return [], self._terminal(UNKNOWN, "HOST_FLOAT_FORBIDDEN"), tuple(checks)
            leaf_id = raw.get("leaf_id", raw.get("id", raw.get("ref")))
            if not isinstance(leaf_id, str) or not leaf_id:
                return [], self._terminal(INVALID, "INPUT_LEAF_ID_REQUIRED"), tuple(checks)
            alias_target = alias_mapping.get(leaf_id)
            if alias_target is not None:
                leaf_id = alias_target
                checks.append({
                    "check": "alias",
                    "operand": index,
                    "status": "PASS",
                })
            version = raw.get("version")
            if not _is_int(version, minimum=1):
                return [], self._terminal(INVALID, "INPUT_VERSION_REQUIRED"), tuple(checks)
            pin = pins.get(leaf_id)
            if pin is None:
                return [], self._terminal(UNKNOWN, "LEAF_NOT_PINNED"), tuple(checks)
            if _contains_float(pin):
                return [], self._terminal(UNKNOWN, "HOST_FLOAT_FORBIDDEN"), tuple(checks)
            pin_version = pin.get("version")
            if not _is_int(pin_version, minimum=1):
                return [], self._terminal(UNKNOWN, "LEAF_PIN_VERSION_UNKNOWN"), tuple(checks)
            if pin_version != version:
                return [], self._terminal(STALE, "STALE_LEAF_VERSION"), tuple(checks)
            input_digest = raw.get("content_digest", raw.get("digest"))
            pin_digest = pin.get("content_digest", pin.get("digest"))
            if input_digest is not None and pin_digest is not None and \
                    input_digest != pin_digest:
                return [], self._terminal(STALE, "STALE_LEAF_DIGEST"), tuple(checks)
            pin_alias = pin.get("alias_of")
            alias_of = raw.get("alias_of")
            if isinstance(pin_alias, str) and pin_alias in alias_mapping and \
                    alias_mapping[pin_alias] != leaf_id:
                return [], self._terminal(INVALID, "ALIAS_CONFLICT"), tuple(checks)
            if isinstance(alias_of, str) and alias_of in alias_mapping and \
                    alias_mapping[alias_of] != leaf_id:
                return [], self._terminal(INVALID, "ALIAS_CONFLICT"), tuple(checks)
            pin_type = pin.get("type") if isinstance(pin.get("type"), Mapping) else {}
            input_type = raw.get("type") if isinstance(raw.get("type"), Mapping) else {}
            for key, value in input_type.items():
                if key in pin_type and _safe_value(pin_type[key]) != _safe_value(value):
                    return [], self._terminal(INVALID, "INPUT_TYPE_CONFLICT"), tuple(checks)
            type_doc = {str(key): value for key, value in pin_type.items()}
            type_doc.update({str(key): value for key, value in input_type.items()})
            if pin.get("kind") is not None and "kind" not in type_doc:
                type_doc["kind"] = pin["kind"]
            status = pin.get("status", "committed")
            if status == "quarantined":
                return [], self._terminal(UNKNOWN, "LEAF_QUARANTINED"), tuple(checks)
            if status in {"tombstoned", "superseded"}:
                return [], self._terminal(STALE, "LEAF_TOMBSTONED"), tuple(checks)
            if status == "scratch":
                return [], self._terminal(UNKNOWN, "LEAF_SCRATCH_NOT_AUTHORITATIVE"), tuple(checks)
            if pin.get("available") is False:
                return [], self._terminal(UNKNOWN, "LEAF_UNAVAILABLE"), tuple(checks)
            item = {
                "leaf_id": leaf_id,
                "version": version,
                "content_digest": pin_digest,
                "type": type_doc,
                "kind": _input_kind({"type": type_doc, "kind": pin.get("kind")}),
                "shape": _input_shape({"type": type_doc}),
                "precision": _input_precision({"type": type_doc}),
                "domain": _input_domain({"type": type_doc}),
                "layout": _input_layout({"type": type_doc}),
                "workspace_words": pin.get("workspace_words", 0),
                "content": pin.get("content"),
                "metadata": pin.get("metadata"),
                "pin": pin,
                "input": dict(raw),
            }
            for key in ("content", "value", "is_zero", "zero", "metadata",
                        "declared_value"):
                if key in raw and key not in item:
                    item[key] = raw[key]
            resolved.append(item)
            checks.append({
                "check": "leaf_pin",
                "operand": index,
                "status": "PASS",
                "version": version,
            })
        return resolved, None, tuple(checks)

    def _signature_specs(self, function: MathFunction
                         ) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
        signature = function.signature
        inputs = signature.get("inputs")
        specs = None
        if isinstance(inputs, (tuple, list)):
            specs = []
            for spec in inputs:
                if isinstance(spec, str):
                    specs.append({"kind": spec})
                elif isinstance(spec, Mapping):
                    specs.append({str(key): value for key, value in spec.items()})
                else:
                    specs.append({})
        output = signature.get("output")
        output_spec = None
        if isinstance(output, str):
            output_spec = {"kind": output}
        elif isinstance(output, Mapping):
            output_spec = {str(key): value for key, value in output.items()}
        return specs, output_spec

    def _expected_field(self, spec: dict[str, Any], name: str) -> Any:
        if name in spec:
            return spec[name]
        type_doc = spec.get("type")
        if isinstance(type_doc, Mapping):
            if name in type_doc:
                return type_doc[name]
            if name == "kind":
                return type_doc.get("kind", type_doc.get("name"))
        if name == "kind" and isinstance(type_doc, str):
            return type_doc
        return None

    def _check_signature(self, candidate: MathCandidate, function: MathFunction,
                         resolved: list[dict[str, Any]],
                         alias_mapping: dict[str, str],
                         checks: list[dict[str, Any]]) -> _MathDecision | None:
        specs, _ = self._signature_specs(function)
        if specs is None:
            inputs = function.signature.get("inputs")
            if _is_int(inputs, minimum=0) and inputs != len(resolved):
                return self._terminal(INVALID, "ARITY_MISMATCH")
            return None
        required = [spec for spec in specs if not spec.get("optional")]
        if len(resolved) < len(required) or len(resolved) > len(specs):
            return self._terminal(INVALID, "ARITY_MISMATCH")
        unknown = None
        for index, spec in enumerate(specs):
            if index >= len(resolved):
                continue
            item = resolved[index]
            expected_kind = _kind(self._expected_field(spec, "kind"))
            actual_kind = item.get("kind")
            if expected_kind is not None and actual_kind is not None:
                canonical = alias_mapping.get(actual_kind, actual_kind)
                canonical_kind = _kind(canonical)
                if canonical_kind != expected_kind:
                    return self._terminal(INVALID, "KIND_MISMATCH")
                checks.append({
                    "check": "kind",
                    "operand": index,
                    "status": "PASS",
                })
            elif expected_kind is not None and actual_kind is None:
                unknown = unknown or "KIND_UNKNOWN"
            expected_shape = self._expected_field(spec, "shape")
            actual_shape = item.get("shape")
            if expected_shape is not None:
                if _contains_float(expected_shape) or _contains_float(actual_shape):
                    return self._terminal(UNKNOWN, "HOST_FLOAT_FORBIDDEN")
                if not isinstance(expected_shape, (tuple, list)):
                    return self._terminal(INVALID, "SHAPE_SPEC_INVALID")
                if actual_shape is None:
                    unknown = unknown or "SHAPE_UNKNOWN"
                elif not _shape_matches(list(expected_shape), list(actual_shape)):
                    checks.append({
                        "check": "shape",
                        "operand": index,
                        "status": "FAIL",
                        "expected": _shape_text(list(expected_shape)),
                        "actual": _shape_text(list(actual_shape)),
                    })
                    return self._terminal(INVALID, "SHAPE_MISMATCH")
                else:
                    checks.append({
                        "check": "shape",
                        "operand": index,
                        "status": "PASS",
                        "expected": _shape_text(list(expected_shape)),
                        "actual": _shape_text(list(actual_shape)),
                    })
            expected_layout = _layout(self._expected_field(spec, "layout"))
            if expected_layout is None:
                expected_layout = _layout(function.numerical_policy.get("layout"))
            actual_layout = item.get("layout")
            if expected_layout is not None:
                if actual_layout is None:
                    unknown = unknown or "LAYOUT_UNKNOWN"
                elif actual_layout != expected_layout:
                    return self._terminal(INVALID, "LAYOUT_MISMATCH")
                else:
                    checks.append({"check": "layout", "operand": index, "status": "PASS"})
            expected_precision = _precision(self._expected_field(spec, "precision"))
            if expected_precision is None:
                expected_precision = _precision(function.numerical_policy.get("precision"))
            actual_precision = item.get("precision")
            accepted = self._expected_field(spec, "accepts_precision")
            if expected_precision is not None:
                if actual_precision is None:
                    unknown = unknown or "PRECISION_UNKNOWN"
                else:
                    allowed = [expected_precision]
                    if isinstance(accepted, (tuple, list)):
                        allowed.extend(
                            value for value in (_precision(item) for item in accepted)
                            if value is not None
                        )
                    if actual_precision not in allowed:
                        return self._terminal(INVALID, "PRECISION_MISMATCH")
                    checks.append({
                        "check": "precision",
                        "operand": index,
                        "status": "PASS",
                    })
            expected_domain = _domain(self._expected_field(spec, "domain"))
            actual_domain = item.get("domain")
            if expected_domain is not None:
                if actual_domain is None:
                    unknown = unknown or "DOMAIN_UNKNOWN"
                else:
                    accepted_domains = self._expected_field(spec, "domains")
                    if isinstance(accepted_domains, (tuple, list)):
                        allowed_domains = {
                            value for value in (_domain(item) for item in accepted_domains)
                            if value is not None
                        }
                        matched = actual_domain in allowed_domains
                    else:
                        matched = _domain_compatible(expected_domain, actual_domain)
                    if not matched:
                        return self._terminal(INVALID, "DOMAIN_MISMATCH")
                    checks.append({"check": "domain", "operand": index, "status": "PASS"})
        if unknown is not None:
            return self._terminal(UNKNOWN, unknown)
        return None

    def _check_outputs(self, candidate: MathCandidate, function: MathFunction,
                       alias_mapping: dict[str, str],
                       checks: list[dict[str, Any]]) -> _MathDecision | None:
        if not candidate.outputs:
            return None
        _, output_spec = self._signature_specs(function)
        if output_spec is None:
            return None
        expected_kind = _kind(self._expected_field(output_spec, "kind"))
        expected_shape = self._expected_field(output_spec, "shape")
        expected_precision = _precision(self._expected_field(output_spec, "precision"))
        unknown = None
        for index, raw in enumerate(candidate.outputs):
            if _contains_float(raw):
                return self._terminal(UNKNOWN, "HOST_FLOAT_FORBIDDEN")
            actual_kind = _input_kind(raw)
            if expected_kind is not None:
                if actual_kind is None:
                    unknown = unknown or "OUTPUT_KIND_UNKNOWN"
                else:
                    canonical = alias_mapping.get(actual_kind, actual_kind)
                    if _kind(canonical) != expected_kind:
                        return self._terminal(INVALID, "OUTPUT_KIND_MISMATCH")
            actual_shape = _input_shape(raw)
            if expected_shape is not None:
                if _contains_float(expected_shape) or _contains_float(actual_shape):
                    return self._terminal(UNKNOWN, "HOST_FLOAT_FORBIDDEN")
                if actual_shape is None:
                    unknown = unknown or "OUTPUT_SHAPE_UNKNOWN"
                elif not _shape_matches(list(expected_shape), actual_shape):
                    return self._terminal(INVALID, "OUTPUT_SHAPE_MISMATCH")
            actual_precision = _input_precision(raw)
            if expected_precision is not None and actual_precision is not None and \
                    actual_precision != expected_precision:
                return self._terminal(INVALID, "OUTPUT_PRECISION_MISMATCH")
            checks.append({"check": "output", "index": index, "status": "PASS"})
        if unknown is not None:
            return self._terminal(UNKNOWN, unknown)
        return None

    def _check_workspace(self, candidate: MathCandidate, function: MathFunction,
                         snapshot: MathSnapshot, resolved: list[dict[str, Any]],
                         checks: list[dict[str, Any]]) -> _MathDecision | None:
        required = 0
        for item in resolved:
            value = item.get("workspace_words", 0)
            raw = item.get("input") if isinstance(item.get("input"), Mapping) else {}
            if (value is None or value == 0) and "workspace_words" in raw:
                value = raw["workspace_words"]
            if value is None:
                value = 0
            if not _is_int(value, minimum=0):
                return self._terminal(UNKNOWN, "WORKSPACE_NOT_INTEGER")
            required += value
        extra_values = []
        for key in ("workspace_words", "peak_workspace_words"):
            if key in function.numerical_policy:
                extra_values.append(function.numerical_policy[key])
            if key in function.signature:
                extra_values.append(function.signature[key])
        for value in extra_values:
            if not _is_int(value, minimum=0):
                return self._terminal(UNKNOWN, "WORKSPACE_NOT_INTEGER")
            required += value
        limit = None
        for key in ("workspace_words", "guest_words", "max_workspace_words", "limit_words"):
            if key in snapshot.resources:
                limit = snapshot.resources[key]
                break
        if limit is not None and not _is_int(limit, minimum=0):
            return self._terminal(UNKNOWN, "WORKSPACE_LIMIT_NOT_INTEGER")
        if limit is not None and required > limit:
            checks.append({
                "check": "workspace",
                "status": "FAIL",
                "required": required,
                "limit": limit,
            })
            return self._terminal(INVALID, "WORKSPACE_EXCEEDED")
        checks.append({
            "check": "workspace",
            "status": "PASS",
            "required": required,
            "limit": limit,
        })
        return None

    def _rule_refs(self, function: MathFunction) -> list[dict[str, Any]]:
        raw_refs = []
        for key in ("rule_ids", "rules", "rule_refs", "required_rules"):
            value = function.semantics.get(key)
            if value is not None:
                raw_refs.append(value)
        value = function.signature.get("rule_ids")
        if value is not None:
            raw_refs.append(value)
        refs = []
        for raw in raw_refs:
            if isinstance(raw, str):
                refs.append({"rule_id": raw})
            elif isinstance(raw, Mapping):
                rule_id = raw.get("rule_id", raw.get("id"))
                if isinstance(rule_id, str):
                    refs.append({
                        "rule_id": rule_id,
                        "version": raw.get("version"),
                    })
            elif isinstance(raw, (tuple, list)):
                for item in raw:
                    if isinstance(item, str):
                        refs.append({"rule_id": item})
                    elif isinstance(item, Mapping):
                        rule_id = item.get("rule_id", item.get("id"))
                        if isinstance(rule_id, str):
                            refs.append({
                                "rule_id": rule_id,
                                "version": item.get("version"),
                            })
        return refs

    def _select_rules(self, function: MathFunction, snapshot: MathSnapshot,
                      rules: Any) -> tuple[tuple[MathRule, ...], tuple[MathRule, ...],
                                            _MathDecision | None]:
        by_id: dict[str, list[MathRule]] = {}
        for rule in snapshot.rules:
            by_id.setdefault(rule.rule_id, []).append(rule)
        selected: list[MathRule] = []
        selected_keys = set()
        refs = self._rule_refs(function)
        if refs:
            for ref in refs:
                rule_id = ref["rule_id"]
                version = ref.get("version")
                candidates = by_id.get(rule_id, [])
                if not candidates:
                    return (), (), self._terminal(UNSUPPORTED, "RULE_REF_UNKNOWN")
                if version is not None:
                    matches = [rule for rule in candidates if rule.version == version]
                    if not matches:
                        return (), (), self._terminal(STALE, "STALE_RULE_VERSION")
                    rule = matches[0]
                else:
                    if len(candidates) != 1:
                        return (), (), self._terminal(UNKNOWN, "AMBIGUOUS_RULE_REF")
                    rule = candidates[0]
                key = (rule.rule_id, rule.version)
                if key not in selected_keys:
                    selected.append(rule)
                    selected_keys.add(key)
        applicable = [
            rule for rule in snapshot.rules
            if rule.level != 3
            and self._rule_applies(rule, function.function_id)
        ]
        if not refs:
            selected = list(applicable)
            selected_keys = {(rule.rule_id, rule.version) for rule in selected}
        if rules is not None:
            for rule in rules:
                key = (rule.rule_id, rule.version)
                existing = [
                    item for item in snapshot.rules
                    if item.rule_id == rule.rule_id and item.version == rule.version
                ]
                if not existing or digest_object(existing[0].to_dict()) != digest_object(rule.to_dict()):
                    return (), (), self._terminal(STALE, "RULE_NOT_IN_SNAPSHOT")
                if key not in selected_keys:
                    selected.append(rule)
                    selected_keys.add(key)
                if not self._rule_applies(rule, function.function_id):
                    scope_ids = self._rule_scope_ids(rule)
                    if scope_ids:
                        return (), (), self._terminal(INVALID, "RULE_SCOPE_MISMATCH")
        return tuple(selected), tuple(applicable), None

    def _rule_scope_ids(self, rule: MathRule) -> tuple[str, ...]:
        scope = rule.scope
        values = []
        for key in ("function_ids", "functions", "applies_to"):
            raw = scope.get(key)
            if isinstance(raw, str):
                values.append(raw)
            elif isinstance(raw, (tuple, list)):
                values.extend(item for item in raw if isinstance(item, str))
        raw = scope.get("function_id")
        if isinstance(raw, str):
            values.append(raw)
        return tuple(dict.fromkeys(values))

    def _rule_applies(self, rule: MathRule, function_id: str) -> bool:
        scope_ids = self._rule_scope_ids(rule)
        if scope_ids:
            return function_id in scope_ids
        family = rule.scope.get("family")
        if isinstance(family, str) and family:
            return (
                function_id.startswith("math." + family + ".")
                or ("." + family + ".") in function_id
            )
        if rule.scope.get("global") is True or rule.scope.get("all") is True:
            return True
        return not any(
            key in rule.scope
            for key in ("function_ids", "function_id", "functions", "applies_to", "family")
        )

    def _rule_certificate(self, rule: MathRule) -> str | None:
        if rule.certificate_digest is not None:
            return rule.certificate_digest
        for key in ("certificate_digest", "certificate", "derivation_digest"):
            value = rule.contract.get(key)
            if isinstance(value, Mapping):
                value = value.get("digest", value.get("certificate_digest"))
            if isinstance(value, str):
                return value
        return None

    def _rule_self_promotion(self, rule: MathRule) -> str:
        contract = rule.contract
        if contract.get("self_promoted") is True or \
                contract.get("self_promotion") is True or \
                contract.get("promote_self") is True:
            return "SELF_PROMOTION_FORBIDDEN"
        for key in ("promote_to_level", "promoted_to_level", "level_override",
                    "acts_as_level", "authority_level", "requested_level",
                    "promoted_level", "target_level", "claimed_level",
                    "effective_level"):
            if key in contract:
                value = contract[key]
                if not _is_int(value, minimum=0) or value != rule.level:
                    return "SELF_PROMOTION_FORBIDDEN"
        source = contract.get("promoted_from_level")
        if source is not None and _is_int(source, minimum=0) and source > rule.level:
            return "SELF_PROMOTION_FORBIDDEN"
        if rule.level == 0 and (
            contract.get("mutable") is True
            or contract.get("immutable") is False
            or contract.get("learnable") is True
        ):
            return "LEVEL0_IMMUTABLE"
        if rule.level == 3 and (
            contract.get("production") is True
            or contract.get("authoritative") is True
            or contract.get("promote_to_production") is True
            or rule.scope.get("production") is True
            or rule.scope.get("isolated") is False
        ):
            return "SELF_PROMOTION_FORBIDDEN"
        return ""

    def _evaluate_rules(self, function: MathFunction, snapshot: MathSnapshot,
                        rules: Any, *, isolated: bool) -> _MathDecision:
        selected, applicable, decision = self._select_rules(function, snapshot, rules)
        if decision is not None:
            return decision
        evaluation = list(selected)
        evaluation_keys = {(rule.rule_id, rule.version) for rule in evaluation}
        for rule in applicable:
            key = (rule.rule_id, rule.version)
            if key not in evaluation_keys:
                evaluation.append(rule)
                evaluation_keys.add(key)
        levels_by_rule: dict[str, set[int]] = {}
        for rule in evaluation:
            levels_by_rule.setdefault(rule.rule_id, set()).add(rule.level)
        for rule_id, levels in sorted(levels_by_rule.items()):
            if len(levels) > 1:
                return _MathDecision(
                    INVALID, f"SELF_PROMOTION_FORBIDDEN:{rule_id}",
                    rule_level=max(levels),
                    rule_ids=tuple(sorted(rule.rule_id for rule in evaluation)),
                )
        checks = []
        isolated_result = False
        unknown_reason = ""
        max_level = 0
        for rule in evaluation:
            max_level = max(max_level, rule.level)
            promotion = self._rule_self_promotion(rule)
            if promotion:
                return _MathDecision(
                    INVALID, promotion,
                    checks=tuple(checks), rule_level=max_level,
                    rule_ids=tuple(sorted(rule.rule_id for rule in evaluation)),
                )
            if rule.status in {"blocked", "revoked"}:
                return _MathDecision(
                    INVALID, f"RULE_BLOCKED:{rule.rule_id}",
                    checks=tuple(checks), rule_level=max_level,
                    rule_ids=tuple(sorted(rule.rule_id for rule in evaluation)),
                )
            if rule.status == "deprecated":
                return _MathDecision(
                    UNSUPPORTED, f"RULE_DEPRECATED:{rule.rule_id}",
                    checks=tuple(checks), rule_level=max_level,
                    rule_ids=tuple(sorted(rule.rule_id for rule in evaluation)),
                )
            if rule.status == "proposed" and rule.level != 3:
                unknown_reason = unknown_reason or f"RULE_PROPOSED:{rule.rule_id}"
            if rule.level == 0:
                if rule.status not in {"active", "validated"}:
                    return _MathDecision(
                        INVALID, f"LEVEL0_NOT_ACTIVE:{rule.rule_id}",
                        checks=tuple(checks), rule_level=max_level,
                        rule_ids=tuple(sorted(rule.rule_id for rule in evaluation)),
                    )
                baseline = self._level0.get(rule.rule_id)
                if baseline is not None and (
                    rule.version != baseline["version"]
                    or digest_object(rule.to_dict()) != baseline["digest"]
                ):
                    return _MathDecision(
                        INVALID, f"LEVEL0_IMMUTABLE:{rule.rule_id}",
                        checks=tuple(checks), rule_level=max_level,
                        rule_ids=tuple(sorted(rule.rule_id for rule in evaluation)),
                    )
            if rule.level == 2:
                certificate = self._rule_certificate(rule)
                certificate_text = _digest_text(certificate) if certificate is not None else None
                pinned_certificates = self.current_certificates()
                if certificate is None:
                    unknown_reason = unknown_reason or f"LEVEL2_CERTIFICATE_REQUIRED:{rule.rule_id}"
                elif certificate_text is None:
                    return _MathDecision(
                        INVALID, f"CERTIFICATE_MALFORMED:{rule.rule_id}",
                        checks=tuple(checks), rule_level=max_level,
                        rule_ids=tuple(sorted(rule.rule_id for rule in evaluation)),
                    )
                elif certificate_text not in pinned_certificates and pinned_certificates:
                    unknown_reason = unknown_reason or f"CERTIFICATE_NOT_PINNED:{rule.rule_id}"
            if rule.level == 3:
                isolated_result = True
            checks.append({
                "check": "rule",
                "rule_id": rule.rule_id,
                "version": rule.version,
                "level": rule.level,
                "status": "PASS",
            })
        contradiction = self._find_contradiction(
            evaluation, include_level3=isolated_result or isolated,
        )
        if contradiction:
            return _MathDecision(
                INVALID, contradiction,
                checks=tuple(checks), rule_level=max_level,
                rule_ids=tuple(sorted(rule.rule_id for rule in evaluation)),
                isolated=isolated_result,
            )
        if unknown_reason:
            return _MathDecision(
                UNKNOWN, unknown_reason,
                checks=tuple(checks), rule_level=max_level,
                rule_ids=tuple(sorted(rule.rule_id for rule in evaluation)),
                isolated=isolated_result,
            )
        return _MathDecision(
            VALID, "",
            checks=tuple(checks), rule_level=max_level,
            rule_ids=tuple(sorted(rule.rule_id for rule in evaluation)),
            isolated=isolated_result,
        )

    def _find_contradiction(self, rules: list[MathRule], *,
                            include_level3: bool) -> str:
        live = [
            rule for rule in rules
            if rule.status in {"active", "validated"}
            and (include_level3 or rule.level != 3)
        ]
        live.sort(key=lambda item: (item.rule_id, item.version))
        claims: dict[str, list[tuple[MathRule, Any]]] = {}
        requires: dict[str, list[MathRule]] = {}
        forbids: dict[str, list[MathRule]] = {}
        for rule in live:
            for key, value in self._rule_claims(rule).items():
                claims.setdefault(key, []).append((rule, _safe_value(value)))
            for token in self._rule_tokens(rule, "requires"):
                requires.setdefault(token, []).append(rule)
            for token in self._rule_tokens(rule, "forbids"):
                forbids.setdefault(token, []).append(rule)
        for key, values in claims.items():
            first_value = values[0][1]
            for rule, value in values[1:]:
                if value != first_value:
                    involved = sorted({
                        values[0][0].rule_id, rule.rule_id,
                    })
                    return "CONTRADICTION:" + ",".join(involved)
        for token in sorted(set(requires) & set(forbids)):
            involved = sorted({
                requires[token][0].rule_id, forbids[token][0].rule_id,
            })
            return "CONTRADICTION:" + ",".join(involved)
        by_key = {(rule.rule_id, rule.version): rule for rule in live}
        for rule in live:
            targets = rule.contract.get("contradicts")
            if targets is None:
                continue
            if isinstance(targets, (str, Mapping)):
                targets = [targets]
            if not isinstance(targets, (tuple, list)):
                continue
            for target in targets:
                target_id = target.get("rule_id", target.get("id")) \
                    if isinstance(target, Mapping) else target
                if not isinstance(target_id, str):
                    continue
                target_version = target.get("version") if isinstance(target, Mapping) else None
                matches = [
                    item for (rule_id, version), item in by_key.items()
                    if rule_id == target_id
                    and (target_version is None or version == target_version)
                ]
                if matches:
                    involved = sorted({rule.rule_id, target_id})
                    return "CONTRADICTION:" + ",".join(involved)
        return ""

    def _rule_claims(self, rule: MathRule) -> dict[str, Any]:
        raw = rule.contract.get("claims")
        if raw is None:
            raw = rule.contract.get("asserts")
        result: dict[str, Any] = {}
        if isinstance(raw, Mapping):
            for key, value in raw.items():
                result[str(key)] = value
        elif isinstance(raw, (tuple, list)):
            for entry in raw:
                if not isinstance(entry, Mapping):
                    continue
                key = entry.get("key", entry.get("name"))
                if isinstance(key, str):
                    result[key] = entry.get("value")
        return result

    def _rule_tokens(self, rule: MathRule, key: str) -> tuple[str, ...]:
        raw = rule.contract.get(key)
        if isinstance(raw, str):
            return (raw,)
        if isinstance(raw, (tuple, list)):
            return tuple(item for item in raw if isinstance(item, str))
        if isinstance(raw, Mapping):
            return tuple(str(item) for item in raw)
        return ()

    def _evaluate_conditions(self, function: MathFunction,
                             context: _PredicateContext, *,
                             enforce_postconditions: bool) -> _MathDecision:
        checks: list[dict[str, Any]] = []
        undefined_results = tuple(
            _evaluate_predicate(predicate, "undefined", index, context)
            for index, predicate in enumerate(function.undefined_conditions)
        )
        checks.extend(_predicate_check(result) for result in undefined_results)
        for result in undefined_results:
            if result.status == "SATISFIED":
                reason = result.reason or "UNDEFINED_CONDITION"
                return _MathDecision(
                    UNDEFINED, reason, checks=tuple(checks),
                    predicates=undefined_results,
                )
            if result.status == "UNSUPPORTED":
                return _MathDecision(
                    UNSUPPORTED, result.reason or "UNDEFINED_CONDITION_UNSUPPORTED",
                    checks=tuple(checks), predicates=undefined_results,
                )

        precondition_results = tuple(
            _evaluate_predicate(predicate, "precondition", index, context)
            for index, predicate in enumerate(function.preconditions)
        )
        checks.extend(_predicate_check(result) for result in precondition_results)
        for result in precondition_results:
            if result.status == "VIOLATED":
                reason = result.reason or "PRECONDITION_VIOLATED"
                return _MathDecision(
                    INVALID, reason, checks=tuple(checks),
                    predicates=undefined_results + precondition_results,
                )
            if result.status == "UNSUPPORTED":
                return _MathDecision(
                    UNSUPPORTED, result.reason or "PRECONDITION_UNSUPPORTED",
                    checks=tuple(checks),
                    predicates=undefined_results + precondition_results,
                )
            if result.status == "UNKNOWN":
                return _MathDecision(
                    UNKNOWN, result.reason or "PRECONDITION_UNKNOWN",
                    checks=tuple(checks),
                    predicates=undefined_results + precondition_results,
                )
        for result in undefined_results:
            if result.status == "UNKNOWN":
                return _MathDecision(
                    UNKNOWN, result.reason or "UNDEFINED_CONDITION_UNKNOWN",
                    checks=tuple(checks),
                    predicates=undefined_results + precondition_results,
                )

        postcondition_results = tuple(
            _evaluate_predicate(predicate, "postcondition", index, context)
            for index, predicate in enumerate(function.postconditions)
        )
        checks.extend(_predicate_check(result) for result in postcondition_results)
        obligations = tuple(result.to_dict() for result in postcondition_results)
        if enforce_postconditions:
            for result in postcondition_results:
                if result.status == "VIOLATED":
                    return _MathDecision(
                        INVALID, result.reason or "POSTCONDITION_VIOLATED",
                        checks=tuple(checks),
                        predicates=undefined_results + precondition_results + postcondition_results,
                        obligations=obligations,
                    )
                if result.status == "UNSUPPORTED":
                    return _MathDecision(
                        UNSUPPORTED, result.reason or "POSTCONDITION_UNSUPPORTED",
                        checks=tuple(checks),
                        predicates=undefined_results + precondition_results + postcondition_results,
                        obligations=obligations,
                    )
                if result.status == "UNKNOWN":
                    return _MathDecision(
                        UNKNOWN, result.reason or "POSTCONDITION_UNKNOWN",
                        checks=tuple(checks),
                        predicates=undefined_results + precondition_results + postcondition_results,
                        obligations=obligations,
                    )
        return _MathDecision(
            VALID, "", checks=tuple(checks),
            predicates=undefined_results + precondition_results + postcondition_results,
            obligations=obligations,
        )

    def _authorization_outcome(self, function: MathFunction,
                               override: Any) -> dict[str, Any]:
        config = self.current_authorization(override)
        context_digest = digest_object(config)
        result = {
            "status": "ALLOWED",
            "reason": "",
            "context_digest": context_digest,
            "checked": bool(config),
        }
        deny_flags = (
            config.get("allowed") is False,
            config.get("allow") is False,
            config.get("denied") is True,
            config.get("deny") is True,
            config.get("mode") in {"deny", "denied"},
        )
        if any(deny_flags):
            result["status"] = "DENIED"
            result["reason"] = "AUTHORIZATION_DENIED"
            return result
        allowed_functions = config.get("allowed_functions", config.get("function_ids"))
        if allowed_functions is not None:
            if isinstance(allowed_functions, str):
                allowed_functions = [allowed_functions]
            if not isinstance(allowed_functions, (tuple, list)) or \
                    function.function_id not in allowed_functions:
                result["status"] = "DENIED"
                result["reason"] = "AUTHORIZATION_FUNCTION_DENIED"
                return result
        denied_functions = config.get("denied_functions", config.get("deny_functions", ()))
        if isinstance(denied_functions, str):
            denied_functions = [denied_functions]
        if isinstance(denied_functions, (tuple, list)) and \
                function.function_id in denied_functions:
            result["status"] = "DENIED"
            result["reason"] = "AUTHORIZATION_FUNCTION_DENIED"
            return result
        universes = config.get("universes", config.get("universe_ids"))
        if universes is not None:
            universe = config.get("universe_id", config.get("universe"))
            if isinstance(universes, str):
                universes = [universes]
            if not isinstance(universes, (tuple, list)) or universe not in universes:
                result["status"] = "DENIED"
                result["reason"] = "AUTHORIZATION_UNIVERSE_DENIED"
                return result
        principals = config.get("principals", config.get("allowed_principals"))
        if principals is not None:
            principal = config.get("principal")
            if isinstance(principals, str):
                principals = [principals]
            if not isinstance(principals, (tuple, list)) or principal not in principals:
                result["status"] = "DENIED"
                result["reason"] = "AUTHORIZATION_PRINCIPAL_DENIED"
                return result
        return result

    def _capability_outcome(self, function: MathFunction, snapshot: MathSnapshot,
                            override: Any) -> dict[str, Any]:
        implementations = list(function.implementations)
        capabilities = self.current_capabilities(override)
        context_digest = digest_object([
            _safe_value(item) for item in capabilities
        ])
        result: dict[str, Any] = {
            "status": "UNCHECKED",
            "reason": "",
            "context_digest": context_digest,
            "checked": bool(capabilities),
            "required": [],
            "selected": None,
        }
        if not implementations:
            result["status"] = "UNSUPPORTED"
            result["reason"] = "NO_IMPLEMENTATION"
            return result
        usable = []
        for implementation in implementations:
            status = str(implementation.get("status", "declared")).lower()
            if status in {"unsupported", "removed", "invalid"}:
                continue
            if status in {"unavailable", "revoked", "disabled"}:
                continue
            usable.append(implementation)
        if not usable:
            result["status"] = "UNAVAILABLE"
            result["reason"] = "CAPABILITY_UNAVAILABLE"
            return result
        if not capabilities:
            result["selected"] = {
                "kernel_id": usable[0].get("kernel_id"),
                "implementation_id": usable[0].get("implementation_id"),
                "capability_class": usable[0].get("capability_class"),
            }
            return result
        status_by_key: dict[str, dict[str, Any]] = {}
        for capability in capabilities:
            for key in ("capability_class", "kernel_id", "implementation_id"):
                value = capability.get(key)
                if isinstance(value, str) and value:
                    status_by_key[value] = capability
        required = []
        for implementation in usable:
            for key in ("capability_class", "kernel_id", "implementation_id"):
                value = implementation.get(key)
                if isinstance(value, str) and value and value not in required:
                    required.append(value)
        if function.semantics.get("capability_class") and \
                function.semantics["capability_class"] not in required:
            required.append(function.semantics["capability_class"])
        result["required"] = required
        if not required:
            return result
        for implementation in usable:
            keys = [
                implementation.get(key) for key in
                ("capability_class", "kernel_id", "implementation_id")
            ]
            matching = [
                status_by_key[key] for key in keys
                if isinstance(key, str) and key in status_by_key
            ]
            if not matching:
                continue
            statuses = [
                str(item.get("status", "available")).lower() for item in matching
            ]
            if any(status in {"unavailable", "revoked", "disabled", "missing",
                              "absent", "none", "unregistered"}
                   for status in statuses):
                continue
            if any(status in {"unsupported", "removed"} for status in statuses):
                continue
            result["status"] = "AVAILABLE"
            result["selected"] = {
                "kernel_id": implementation.get("kernel_id"),
                "implementation_id": implementation.get("implementation_id"),
                "capability_class": implementation.get("capability_class"),
                "verified": any(
                    status in {"native_verified", "verified"}
                    for status in statuses
                ),
            }
            return result
        result["status"] = "UNAVAILABLE"
        result["reason"] = "CAPABILITY_UNAVAILABLE"
        return result

    def _build_admission(self, candidate: MathCandidate, snapshot: MathSnapshot,
                         decision: _MathDecision, *,
                         authorization_outcome: dict[str, Any] | None,
                         capability_outcome: dict[str, Any] | None,
                         semantic_key: str, dispatch_key: str,
                         cache_state: str,
                         admission_snapshot_id: str | None = None) -> MathAdmission:
        verdict = decision.verdict
        reason = decision.reason
        if verdict in {VALID, EXPERIMENTAL}:
            if authorization_outcome is not None and \
                    authorization_outcome.get("status") == "DENIED":
                verdict = UNAUTHORIZED
                reason = authorization_outcome.get("reason", "AUTHORIZATION_DENIED")
            elif capability_outcome is not None and verdict != EXPERIMENTAL:
                capability_status = capability_outcome.get("status")
                if capability_status == "UNAVAILABLE":
                    verdict = UNAVAILABLE
                    reason = capability_outcome.get("reason", "CAPABILITY_UNAVAILABLE")
                elif capability_status == "UNSUPPORTED":
                    verdict = UNSUPPORTED
                    reason = capability_outcome.get("reason", "UNSUPPORTED")
        snapshot_id = admission_snapshot_id or snapshot.snapshot_id
        scope = {
            "semantic_key": semantic_key,
            "dispatch_key": dispatch_key,
            "rule_snapshot_id": snapshot.rule_snapshot_id,
            "rule_level": decision.rule_level,
            "rule_ids": list(decision.rule_ids),
            "isolated": bool(decision.isolated),
            "math_verdict": decision.verdict,
            "checks": [dict(check) for check in decision.checks],
            "predicates": [item.to_dict() for item in decision.predicates],
            "obligations": [dict(item) for item in decision.obligations],
            "authorization": authorization_outcome or {"status": "NOT_EVALUATED"},
            "capability": capability_outcome or {"status": "NOT_EVALUATED"},
            "cache": cache_state,
            "generation": self._generation,
            "snapshot_version": snapshot.version,
        }
        payload = {
            "schema": ADMISSION_SCHEMA,
            "candidate_id": candidate.candidate_id,
            "snapshot_id": snapshot_id,
            "rule_snapshot_id": snapshot.rule_snapshot_id,
            "verdict": verdict,
            "reason": reason,
            "semantic_key": semantic_key,
            "dispatch_key": dispatch_key,
            "rule_level": decision.rule_level,
            "isolated": bool(decision.isolated),
            "scope": _safe_value(scope),
        }
        preflight_digest = _PREFLIGHT_PREFIX + digest_object(payload)
        admission = MathAdmission(
            admission_id=admission_id_for(
                candidate.candidate_id,
                snapshot_id,
                verdict,
                snapshot.rule_snapshot_id,
            ),
            candidate_id=candidate.candidate_id,
            verdict=verdict,
            snapshot_id=snapshot_id,
            reason=reason,
            rule_snapshot_id=snapshot.rule_snapshot_id,
            preflight_digest=preflight_digest,
            scope=scope,
        )
        self._remember_admission(admission)
        return admission

    def _remember_admission(self, admission: MathAdmission) -> None:
        self._issued[admission.preflight_digest] = admission
        self._issued_by_id[admission.admission_id] = admission

    def require_admission(self, admission: MathAdmission | None = None,
                          plan: Any = None, job: Any = None, *,
                          allow_experimental: bool = False,
                          authorization: Any = None,
                          capabilities: Any = None) -> MathAdmission:
        """Reject a plan/job unless it is bound to a current VALID admission.

        ``EXPERIMENTAL`` admissions are rejected unless the caller explicitly
        allows isolated execution, the admission carries ``isolated=True``,
        and the plan/job also declares ``isolated``/``experimental`` true.
        Supplying ``authorization``/``capabilities`` checks the admission
        against that request context instead of only the engine defaults.
        """
        if admission is None:
            admission = self._admission_from_binding(plan if plan is not None else job)
        if not isinstance(admission, MathAdmission):
            raise AdmissionRejected(
                "a typed MathAdmission is required before execution",
                verdict=UNKNOWN, reason="ADMISSION_MISSING",
            )
        if admission.verdict == EXPERIMENTAL:
            if not allow_experimental or admission.scope.get("isolated") is not True:
                raise AdmissionRejected(
                    "experimental admission is isolated and cannot execute in production",
                    verdict=admission.verdict, reason="EXPERIMENTAL_NOT_EXECUTABLE",
                    admission=admission,
                )
            binding = plan if plan is not None else job
            if not _binding_isolated(binding):
                raise AdmissionRejected(
                    "experimental admission requires an isolated plan/job binding",
                    verdict=admission.verdict, reason="ISOLATION_BINDING_REQUIRED",
                    admission=admission,
                )
            capability_record = admission.scope.get("capability", {})
            if isinstance(capability_record, Mapping) and \
                    capability_record.get("status") in {"UNAVAILABLE", "UNSUPPORTED"}:
                raise AdmissionRejected(
                    "experimental admission has no available isolated capability",
                    verdict=admission.verdict, reason="ISOLATED_CAPABILITY_UNAVAILABLE",
                    admission=admission,
                )
        elif admission.verdict != VALID:
            raise AdmissionRejected(
                f"admission is not VALID: {admission.verdict}",
                verdict=admission.verdict, reason=admission.reason or "NOT_VALID",
                admission=admission,
            )
        if self._snapshot is None:
            raise AdmissionRejected(
                "engine has no current snapshot",
                verdict=UNKNOWN, reason="NO_CURRENT_SNAPSHOT", admission=admission,
            )
        if admission.snapshot_id != self._snapshot.snapshot_id:
            raise AdmissionRejected(
                "admission snapshot is stale",
                verdict=STALE, reason="STALE_SNAPSHOT", admission=admission,
            )
        if admission.rule_snapshot_id != self._snapshot.rule_snapshot_id:
            raise AdmissionRejected(
                "admission rule snapshot is stale",
                verdict=STALE, reason="STALE_RULE_SNAPSHOT", admission=admission,
            )
        if not isinstance(admission.preflight_digest, str) or \
                not admission.preflight_digest.startswith(_PREFLIGHT_PREFIX) or \
                _DIGEST_RE.fullmatch(admission.preflight_digest[len(_PREFLIGHT_PREFIX):]) is None:
            raise AdmissionRejected(
                "admission lacks a well-formed preflight digest",
                verdict=UNKNOWN, reason="PREFLIGHT_DIGEST_MALFORMED",
                admission=admission,
            )
        issued = self._issued.get(admission.preflight_digest)
        if issued is None:
            raise AdmissionRejected(
                "admission was not issued by this validity engine",
                verdict=UNKNOWN, reason="UNKNOWN_ADMISSION", admission=admission,
            )
        if issued.to_dict() != admission.to_dict():
            raise AdmissionRejected(
                "admission content does not match the issued record",
                verdict=UNKNOWN, reason="ADMISSION_DIGEST_MISMATCH",
                admission=admission,
            )
        authorization_record = admission.scope.get("authorization", {})
        if isinstance(authorization_record, Mapping) and \
                authorization_record.get("context_digest"):
            current = digest_object(self.current_authorization(authorization))
            if authorization_record["context_digest"] != current:
                raise AdmissionRejected(
                    "authorization context changed; re-run preflight",
                    verdict=STALE, reason="AUTHORIZATION_CONTEXT_CHANGED",
                    admission=admission,
                )
        capability_record = admission.scope.get("capability", {})
        if isinstance(capability_record, Mapping) and \
                capability_record.get("context_digest"):
            current = digest_object([
                _safe_value(item)
                for item in self.current_capabilities(capabilities)
            ])
            if capability_record["context_digest"] != current:
                raise AdmissionRejected(
                    "capability context changed; re-run preflight",
                    verdict=STALE, reason="CAPABILITY_CONTEXT_CHANGED",
                    admission=admission,
                )
        self.require_binding(
            admission, plan=plan, job=job,
            allow_experimental=allow_experimental,
        )
        return admission

    def require_binding(self, admission: MathAdmission, *, plan: Any = None,
                        job: Any = None, allow_experimental: bool = False) -> None:
        for label, binding in (("plan", plan), ("job", job)):
            if binding is None:
                continue
            fields = _binding_fields(binding)
            admission_id = fields.get("admission_id")
            preflight_digest = fields.get("preflight_digest")
            if admission_id is None and preflight_digest is None:
                raise AdmissionRejected(
                    f"{label} does not reference a preflight admission",
                    verdict=UNKNOWN, reason=f"{label.upper()}_MISSING_ADMISSION",
                    admission=admission,
                )
            if admission_id is not None and admission_id != admission.admission_id:
                raise AdmissionRejected(
                    f"{label} admission id does not match",
                    verdict=UNKNOWN, reason=f"{label.upper()}_ADMISSION_ID_MISMATCH",
                    admission=admission,
                )
            if preflight_digest is not None and preflight_digest != admission.preflight_digest:
                raise AdmissionRejected(
                    f"{label} preflight digest does not match",
                    verdict=UNKNOWN, reason=f"{label.upper()}_PREFLIGHT_DIGEST_MISMATCH",
                    admission=admission,
                )
            snapshot_id = fields.get("snapshot_id")
            if snapshot_id is not None and snapshot_id != admission.snapshot_id:
                raise AdmissionRejected(
                    f"{label} snapshot does not match the admission",
                    verdict=STALE, reason=f"{label.upper()}_STALE_SNAPSHOT",
                    admission=admission,
                )
            rule_snapshot_id = fields.get("rule_snapshot_id")
            if rule_snapshot_id is not None and rule_snapshot_id != admission.rule_snapshot_id:
                raise AdmissionRejected(
                    f"{label} rule snapshot does not match the admission",
                    verdict=STALE, reason=f"{label.upper()}_STALE_RULE_SNAPSHOT",
                    admission=admission,
                )
            candidate_id = fields.get("candidate_id")
            if candidate_id is not None and candidate_id != admission.candidate_id:
                raise AdmissionRejected(
                    f"{label} candidate does not match the admission",
                    verdict=UNKNOWN, reason=f"{label.upper()}_CANDIDATE_MISMATCH",
                    admission=admission,
                )
            verdict = fields.get("verdict")
            if verdict is not None and verdict != admission.verdict:
                raise AdmissionRejected(
                    f"{label} verdict does not match the admission",
                    verdict=admission.verdict, reason=f"{label.upper()}_VERDICT_MISMATCH",
                    admission=admission,
                )
            if admission.verdict == EXPERIMENTAL and not _binding_isolated(binding):
                raise AdmissionRejected(
                    f"{label} does not declare isolated execution",
                    verdict=admission.verdict, reason=f"{label.upper()}_ISOLATION_REQUIRED",
                    admission=admission,
                )

    def _admission_from_binding(self, binding: Any) -> MathAdmission | None:
        fields = _binding_fields(binding)
        digest = fields.get("preflight_digest")
        if isinstance(digest, str) and digest in self._issued:
            return self._issued[digest]
        admission_id = fields.get("admission_id")
        if isinstance(admission_id, str):
            return self._issued_by_id.get(admission_id)
        return None


def _normalise_rule_argument(rules: Any) -> tuple[MathRule, ...]:
    if isinstance(rules, MathRule):
        return (rules,)
    if rules is None:
        return ()
    if not isinstance(rules, (tuple, list)):
        raise TypeError("rules must be MathRule objects")
    result = []
    for rule in rules:
        if not isinstance(rule, MathRule):
            raise TypeError("rules must be MathRule objects")
        result.append(rule)
    return tuple(result)


def _predicate_check(result: PredicateResult) -> dict[str, Any]:
    return {
        "check": "predicate",
        "phase": result.phase,
        "index": result.index,
        "op": result.op,
        "status": result.status,
        "reason": result.reason,
    }


def _binding_fields(binding: Any) -> dict[str, Any]:
    if binding is None:
        return {}
    if isinstance(binding, str):
        return {"admission_id": binding}
    sources = []
    if isinstance(binding, Mapping):
        sources.append(binding)
    else:
        source = {}
        for key in (
            "admission_id", "preflight_digest", "snapshot_id", "rule_snapshot_id",
            "candidate_id", "verdict", "isolated", "experimental",
        ):
            if hasattr(binding, key):
                source[key] = getattr(binding, key)
        sources.append(source)
    for key in ("admission", "preflight"):
        nested = binding.get(key) if isinstance(binding, Mapping) else getattr(binding, key, None)
        if isinstance(nested, Mapping):
            sources.append(nested)
        elif isinstance(nested, MathAdmission):
            sources.append({
                "admission_id": nested.admission_id,
                "preflight_digest": nested.preflight_digest,
                "snapshot_id": nested.snapshot_id,
                "rule_snapshot_id": nested.rule_snapshot_id,
                "candidate_id": nested.candidate_id,
                "verdict": nested.verdict,
            })
    result: dict[str, Any] = {}
    for source in sources:
        for key in (
            "admission_id", "preflight_digest", "snapshot_id", "rule_snapshot_id",
            "candidate_id", "verdict", "isolated", "experimental",
        ):
            if key not in source or source[key] is None:
                continue
            value = source[key]
            if key == "preflight_digest" and isinstance(value, str) and \
                    _DIGEST_RE.fullmatch(value) is not None:
                value = _PREFLIGHT_PREFIX + value
            result.setdefault(key, value)
        if "digest" in source and "preflight_digest" not in result:
            value = source["digest"]
            if isinstance(value, str):
                if _DIGEST_RE.fullmatch(value) is not None:
                    value = _PREFLIGHT_PREFIX + value
                result["preflight_digest"] = value
    return result


def _binding_isolated(binding: Any) -> bool:
    if binding is None:
        return False
    fields = _binding_fields(binding)
    return fields.get("isolated") is True or fields.get("experimental") is True


def preflight(candidate: Any, snapshot: Any = None, function: Any = None,
              rules: Any = None, *, engine: MathValidityEngine | None = None,
              **kwargs: Any) -> MathAdmission:
    """Module-level convenience wrapper around ``MathValidityEngine.preflight``."""
    if engine is None:
        engine = MathValidityEngine(snapshot)
        snapshot = None
    return engine.preflight(candidate, snapshot, function, rules, **kwargs)


def require_admission(admission: MathAdmission | None = None, snapshot: Any = None,
                      *, engine: MathValidityEngine | None = None,
                      plan: Any = None, job: Any = None,
                      allow_experimental: bool = False,
                      authorization: Any = None,
                      capabilities: Any = None) -> MathAdmission:
    """Module-level preflight gate.

    When ``engine`` is supplied the engine's issued-admission ledger is
    authoritative.  Otherwise a snapshot is required and the admission is
    checked structurally against it.
    """
    if isinstance(snapshot, Mapping) and plan is None and \
            ("admission_id" in snapshot or "preflight_digest" in snapshot) and \
            not any(key in snapshot for key in ("functions", "rules", "leaf_pins", "leaves")):
        plan = snapshot
        snapshot = None
    if engine is not None:
        return engine.require_admission(
            admission, plan=plan, job=job,
            allow_experimental=allow_experimental,
            authorization=authorization, capabilities=capabilities,
        )
    if snapshot is None:
        raise AdmissionRejected(
            "require_admission needs an engine or a current snapshot",
            verdict=UNKNOWN, reason="NO_CURRENT_SNAPSHOT",
            admission=admission,
        )
    current = coerce_snapshot(snapshot)
    if admission is None:
        binding = plan if plan is not None else job
        fields = _binding_fields(binding)
        digest = fields.get("preflight_digest")
        if not isinstance(digest, str):
            raise AdmissionRejected(
                "binding does not reference a preflight admission",
                verdict=UNKNOWN, reason="ADMISSION_MISSING",
            )
        raise AdmissionRejected(
            "an unissued admission cannot be resolved without the issuing engine",
            verdict=UNKNOWN, reason="UNKNOWN_ADMISSION",
        )
    if not isinstance(admission, MathAdmission):
        raise AdmissionRejected(
            "a typed MathAdmission is required before execution",
            verdict=UNKNOWN, reason="ADMISSION_MISSING", admission=admission,
        )
    if admission.verdict == EXPERIMENTAL:
        if not allow_experimental or admission.scope.get("isolated") is not True:
            raise AdmissionRejected(
                "experimental admission is isolated",
                verdict=admission.verdict, reason="EXPERIMENTAL_NOT_EXECUTABLE",
                admission=admission,
            )
    elif admission.verdict != VALID:
        raise AdmissionRejected(
            f"admission is not VALID: {admission.verdict}",
            verdict=admission.verdict, reason=admission.reason or "NOT_VALID",
            admission=admission,
        )
    if admission.snapshot_id != current.snapshot_id:
        raise AdmissionRejected(
            "admission snapshot is stale",
            verdict=STALE, reason="STALE_SNAPSHOT", admission=admission,
        )
    if admission.rule_snapshot_id != current.rule_snapshot_id:
        raise AdmissionRejected(
            "admission rule snapshot is stale",
            verdict=STALE, reason="STALE_RULE_SNAPSHOT", admission=admission,
        )
    if not isinstance(admission.preflight_digest, str) or \
            not admission.preflight_digest.startswith(_PREFLIGHT_PREFIX) or \
            _DIGEST_RE.fullmatch(admission.preflight_digest[len(_PREFLIGHT_PREFIX):]) is None:
        raise AdmissionRejected(
            "admission lacks a well-formed preflight digest",
            verdict=UNKNOWN, reason="PREFLIGHT_DIGEST_MALFORMED",
            admission=admission,
        )
    authorization_config = dict(current.authorization)
    if authorization is not None:
        authorization_config.update(_mapping_copy(authorization, "authorization"))
    capability_config = (
        current.capabilities if capabilities is None
        else _normalise_capabilities(capabilities)
    )
    authorization_record = admission.scope.get("authorization", {})
    if isinstance(authorization_record, Mapping) and \
            authorization_record.get("context_digest"):
        if authorization_record["context_digest"] != digest_object(
                _safe_value(authorization_config)):
            raise AdmissionRejected(
                "authorization context changed",
                verdict=STALE, reason="AUTHORIZATION_CONTEXT_CHANGED",
                admission=admission,
            )
    capability_record = admission.scope.get("capability", {})
    if isinstance(capability_record, Mapping) and \
            capability_record.get("context_digest"):
        if capability_record["context_digest"] != digest_object(
                [_safe_value(item) for item in capability_config]):
            raise AdmissionRejected(
                "capability context changed",
                verdict=STALE, reason="CAPABILITY_CONTEXT_CHANGED",
                admission=admission,
            )
    for label, binding in (("plan", plan), ("job", job)):
        if binding is None:
            continue
        fields = _binding_fields(binding)
        if fields.get("admission_id") is None and fields.get("preflight_digest") is None:
            raise AdmissionRejected(
                f"{label} does not reference a preflight admission",
                verdict=UNKNOWN, reason=f"{label.upper()}_MISSING_ADMISSION",
                admission=admission,
            )
        if fields.get("admission_id") is not None and \
                fields["admission_id"] != admission.admission_id:
            raise AdmissionRejected(
                f"{label} admission id does not match",
                verdict=UNKNOWN, reason=f"{label.upper()}_ADMISSION_ID_MISMATCH",
                admission=admission,
            )
        if fields.get("preflight_digest") is not None and \
                fields["preflight_digest"] != admission.preflight_digest:
            raise AdmissionRejected(
                f"{label} preflight digest does not match",
                verdict=UNKNOWN, reason=f"{label.upper()}_PREFLIGHT_DIGEST_MISMATCH",
                admission=admission,
            )
        if fields.get("snapshot_id") is not None and \
                fields["snapshot_id"] != admission.snapshot_id:
            raise AdmissionRejected(
                f"{label} snapshot does not match",
                verdict=STALE, reason=f"{label.upper()}_STALE_SNAPSHOT",
                admission=admission,
            )
        if admission.verdict == EXPERIMENTAL and not _binding_isolated(binding):
            raise AdmissionRejected(
                f"{label} does not declare isolated execution",
                verdict=admission.verdict, reason=f"{label.upper()}_ISOLATION_REQUIRED",
                admission=admission,
            )
    return admission


__all__ = [
    "AdmissionRejected", "EXPERIMENTAL", "INVALID", "MATH_VERDICTS",
    "MathAdmissionRejected", "MathPreflightCache", "MathSnapshot",
    "MathSnapshotError", "MathValidityEngine", "MathValidityError",
    "NUMERIC_PREDICATE_OPS", "PREDICATE_STATUSES", "PredicateResult",
    "STALE", "TERMINAL_MATH_VERDICTS", "UNAUTHORIZED", "UNAVAILABLE",
    "UNDEFINED", "UNKNOWN", "UNSUPPORTED", "VALID", "coerce_snapshot",
    "evaluate_predicates", "preflight", "require_admission",
]
