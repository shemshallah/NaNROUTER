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
    "result", "null", "void", "undefined", "unknown", "error", "hypergraph",
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


class MathObjectError(ValueError):
    """Invalid mathematical record or canonical serialization."""


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
        result.append(dict(entry))
    return tuple(result)


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

    def __post_init__(self) -> None:
        if not isinstance(self.leaf_id, str) or not _LEAF_ID_RE.fullmatch(self.leaf_id):
            raise MathObjectError("leaf_id must be an nml: identifier")
        if self.kind not in LEAF_KINDS:
            raise MathObjectError(f"unknown leaf kind: {self.kind!r}")
        _require_int(self.version, "version", minimum=1)
        if not isinstance(self.type, Mapping):
            raise MathObjectError("type must be an object")
        if self.status not in LEAF_STATUSES:
            raise MathObjectError(f"unknown leaf status: {self.status!r}")
        if self.content is not None and not isinstance(self.content, Mapping):
            raise MathObjectError("content must be an object or null")
        object.__setattr__(self, "type", dict(self.type))
        object.__setattr__(self, "content", None if self.content is None else dict(self.content))
        object.__setattr__(self, "parents", _tuple_of_dicts(self.parents, "parents"))
        object.__setattr__(self, "operation", None if self.operation is None else dict(self.operation))
        object.__setattr__(self, "provenance", dict(self.provenance))
        object.__setattr__(self, "aliases", _tuple_of_dicts(self.aliases, "aliases"))
        object.__setattr__(self, "metadata", dict(self.metadata))
        if self.kind in {"null", "void", "undefined", "unknown", "error"}:
            if self.content is not None:
                raise MathObjectError(f"{self.kind} leaves must not carry numeric content")
            if not self.metadata.get("reason") and not self.metadata.get("failure_class"):
                raise MathObjectError(f"{self.kind} leaf requires reason/failure_class")
        if self.kind == "result" and self.operation is None:
            raise MathObjectError("result leaves require an operation record")

    @property
    def content_digest(self) -> str | None:
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
            "type": dict(self.type),
            "content": None if self.content is None else dict(self.content),
            "parents": [dict(parent) for parent in self.parents],
            "operation": None if self.operation is None else dict(self.operation),
            "status": self.status,
            "provenance": dict(self.provenance),
            "aliases": [dict(alias) for alias in self.aliases],
            "metadata": dict(self.metadata),
        }
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
        if self.proof_status not in PROOF_STATUSES:
            raise MathObjectError(f"unknown proof_status: {self.proof_status!r}")
        if self.status not in {"proposed", "active", "deprecated", "revoked"}:
            raise MathObjectError(f"unknown function status: {self.status!r}")
        object.__setattr__(self, "signature", dict(self.signature))
        object.__setattr__(self, "semantics", dict(self.semantics))
        object.__setattr__(self, "preconditions", _tuple_of_dicts(self.preconditions, "preconditions"))
        object.__setattr__(self, "postconditions", _tuple_of_dicts(self.postconditions, "postconditions"))
        object.__setattr__(self, "undefined_conditions", _tuple_of_dicts(self.undefined_conditions, "undefined_conditions"))
        object.__setattr__(self, "numerical_policy", dict(self.numerical_policy))
        object.__setattr__(self, "implementations", _tuple_of_dicts(self.implementations, "implementations"))
        if self.contract_digest is not None:
            _require_digest(self.contract_digest, "contract_digest")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": FUNCTION_SCHEMA,
            "function_id": self.function_id,
            "version": self.version,
            "signature": dict(self.signature),
            "semantics": dict(self.semantics),
            "preconditions": [dict(x) for x in self.preconditions],
            "postconditions": [dict(x) for x in self.postconditions],
            "undefined_conditions": [dict(x) for x in self.undefined_conditions],
            "numerical_policy": dict(self.numerical_policy),
            "implementations": [dict(x) for x in self.implementations],
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
        object.__setattr__(self, "contract", dict(self.contract))
        object.__setattr__(self, "scope", dict(self.scope))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RULE_SCHEMA,
            "rule_id": self.rule_id,
            "version": self.version,
            "level": self.level,
            "scope": dict(self.scope),
            "contract": dict(self.contract),
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

    def __post_init__(self) -> None:
        if not isinstance(self.candidate_id, str) or not self.candidate_id.startswith("cnd:"):
            raise MathObjectError("candidate_id must start with cnd:")
        if not isinstance(self.function_id, str) or not _FUNCTION_ID_RE.fullmatch(self.function_id):
            raise MathObjectError("invalid function_id")
        _require_int(self.function_version, "function_version", minimum=1)
        _require_int(self.rank, "rank")
        object.__setattr__(self, "inputs", _tuple_of_dicts(self.inputs, "inputs"))
        object.__setattr__(self, "outputs", _tuple_of_dicts(self.outputs, "outputs"))
        object.__setattr__(self, "rejected", _tuple_of_dicts(self.rejected, "rejected"))
        if not self.inputs:
            raise MathObjectError("candidate requires at least one input")

    def to_dict(self) -> dict[str, Any]:
        return {
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
                     function_id: str, function_version: int) -> str:
    """Content identity for a candidate; excludes rank/time/producer."""
    payload = {
        "snapshot_id": snapshot_id,
        "inputs": [dict(item) for item in inputs],
        "function_id": function_id,
        "function_version": function_version,
    }
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
    "MathFunction", "MathLeaf", "MathObjectError", "MathRule",
    "PROOF_STATUSES", "RULE_LEVELS", "RULE_STATUSES", "RULE_SCHEMA",
    "VERDICTS", "admission_id_for", "candidate_id_for", "canonical_json",
    "digest_object", "sha256_text",
]
