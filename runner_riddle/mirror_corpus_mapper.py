"""Bounded corpus-to-mirror mapping for the one NaNROUTER universe.

This module is host control/data plumbing only.  It reads canonical JSONL
rows, normalizes their text, derives stable content-addressed concept ids and
maps concepts onto the existing 256-head / 32,640-pair mirror topology.  It
emits plain JSON-compatible leaf, relation, observation and optional cycle
candidate records.

It does **not** write MC0DB/BS0DB, dispatch a native guest, evaluate MTH,
perform pair/cycle arithmetic, train a model, or claim that anything was
learned.  Cycle candidates carry only the ``F_ij`` formula metadata; a guest
or an explicitly authorized maintenance pass owns any later evaluation.

The concept identity is the domain-separated
``SHA-256("concept\\0" + casefold(normalized_term))`` digest.  Records also
carry the compact ``concept:<32hex>`` alias from the first 16 digest bytes.
The deterministic head is FNV-1a modulo 256 and the mirror is
``reverse8(head)``.  Pair ids use the canonical 1-based formula
``1 + a*(511-a)/2 + (b-a-1)`` for ``0 <= a < b <= 255``.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
import hashlib
import json
import math
import os
from pathlib import Path
import re
import unicodedata
from typing import Any

SCHEMA = "nanrouter.mirror-corpus-mapper/1"
VERSION = 1
MAP_SCHEMA = SCHEMA

MAX_ROWS = 10000
MAX_BATCH = MAX_ROWS
MAX_LINE_BYTES = 65536
MAX_TEXT_CHARS = 4000
MIN_TEXT_CHARS = 2
MAX_TERM_CHARS = 256
MAX_METADATA_CHARS = 256

HEADS = 256
HEAD_COUNT = HEADS
NANNET0_HEAD = 0
REFERENCE_HEAD = NANNET0_HEAD
PAIR_ID_MIN = 1
PAIR_ID_MAX = 32640
PAIR_COUNT = PAIR_ID_MAX
PAIR_ID_FORMULA = "1 + a*(511-a)/2 + (b-a-1) for 0 <= a < b <= 255"
CONCEPT_DOMAIN = b"concept\0"
CONCEPT_PREFIX = "concept:"
CONCEPT_DIGEST_BYTES = 16
SOURCE_DOMAIN = b"nanrouter.mirror-corpus-mapper/1\0source\0"
RELATION_DOMAIN = b"nanrouter.mirror-corpus-mapper/1\0relation\0"
CYCLE_DOMAIN = b"nanrouter.mirror-corpus-mapper/1\0cycle\0"
OBSERVATION_DOMAIN = b"nanrouter.mirror-corpus-mapper/1\0observation\0"

DEFAULT_CONFIDENCE = 0.5
VALID_SPLITS = frozenset({"train", "validation", "test"})
VALID_POLARITIES = frozenset({"supports", "refutes", "neutral"})

DB_WRITES = False
NATIVE_EXECUTION = False
TRAINING_PERFORMED = False
LEARNING_CLAIMED = False

_HEX64 = re.compile(r"[0-9a-fA-F]{64}\Z")
_WHITESPACE = re.compile(r"\s+", re.UNICODE)
_RELATION_PARTS = ("subject", "predicate", "object")

_POLARITY_ALIASES = {
    "support": "supports",
    "supports": "supports",
    "supported": "supports",
    "positive": "supports",
    "pos": "supports",
    "true": "supports",
    "yes": "supports",
    "+": "supports",
    "+1": "supports",
    "plus": "supports",
    "1": "supports",
    "refute": "refutes",
    "refutes": "refutes",
    "refuted": "refutes",
    "negative": "refutes",
    "neg": "refutes",
    "false": "refutes",
    "no": "refutes",
    "-": "refutes",
    "-1": "refutes",
    "minus": "refutes",
    "contradicts": "refutes",
    "neutral": "neutral",
    "unknown": "neutral",
    "none": "neutral",
    "zero": "neutral",
    "0": "neutral",
}
_SPLIT_ALIASES = {
    "train": "train",
    "training": "train",
    "validation": "validation",
    "valid": "validation",
    "val": "validation",
    "dev": "validation",
    "test": "test",
    "testing": "test",
    "eval": "test",
    "evaluation": "test",
    "holdout": "test",
    "heldout": "test",
}


class CorpusMapperError(ValueError):
    """Base error for corpus input, bounds or mapping validation."""


class CorpusRowError(CorpusMapperError):
    """A row cannot be represented without inventing or losing identity."""


class CorpusBoundError(CorpusMapperError):
    """A declared hard bound was exceeded."""


# Compatibility aliases for callers that use a mirror-specific name.
CorpusMappingError = CorpusMapperError
MirrorCorpusError = CorpusMapperError


# ---------------------------------------------------------------------------
# Deterministic JSON, normalization and digests
# ---------------------------------------------------------------------------

def _sanitize(value: Any, depth: int = 0) -> Any:
    """Return deterministic JSON-safe data without evaluating anything."""
    if depth > 32:
        return {"truncated": True}
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Mapping):
        return {str(key): _sanitize(item, depth + 1)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, depth + 1) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_sanitize(item, depth + 1) for item in value),
                      key=canonical_json)
    return str(value)


def canonical_json(value: Any) -> str:
    """Canonical compact JSON used for stable identities and checksums."""
    return json.dumps(
        _sanitize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _digest(domain: bytes, value: Any) -> str:
    return hashlib.sha256(domain + canonical_json(value).encode("utf-8")).hexdigest()


def normalize_text(value: Any) -> str:
    """NFKC-normalize, trim and collapse whitespace without changing case."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise CorpusMapperError("text fields must be strings")
    text = unicodedata.normalize("NFKC", value).strip()
    return _WHITESPACE.sub(" ", text)


def identity_text(value: Any) -> str:
    """Case-folded identity form of normalized text."""
    return normalize_text(value).casefold()


def _require_identity(value: Any, name: str = "term") -> str:
    normalized = normalize_text(value)
    if not normalized:
        raise CorpusMapperError(f"{name} must not be empty")
    return normalized.casefold()


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and _HEX64.fullmatch(value) is not None


# ---------------------------------------------------------------------------
# Head, mirror and canonical pair arithmetic
# ---------------------------------------------------------------------------

def _head(value: Any) -> int:
    if type(value) is not int or not 0 <= value < HEADS:
        raise CorpusMapperError("head must be an integer 0..255")
    return value


def _pair_int(value: Any) -> int:
    if type(value) is not int or not PAIR_ID_MIN <= value <= PAIR_ID_MAX:
        raise CorpusMapperError("pair_id must be an integer 1..32640")
    return value


def reverse8(head: Any) -> int:
    """Reverse the eight bits of a head address (the mirror link)."""
    n = _head(head)
    n = (n >> 4) | ((n & 15) << 4)
    n = ((n & 0xCC) >> 2) | ((n & 0x33) << 2)
    return ((n & 0xAA) >> 1) | ((n & 0x55) << 1)


def fnv_head(term: Any) -> int:
    """Deterministic FNV-1a head for a normalized, case-folded term."""
    identity = _require_identity(term)
    value = 2166136261
    for byte in identity.encode("utf-8"):
        value ^= byte
        value = (value * 16777619) & 0xFFFFFFFF
    return value % HEADS


def concept_head(term: Any) -> int:
    """Public alias for the deterministic concept head mapping."""
    return fnv_head(term)


head_for_term = fnv_head
head_for_concept = concept_head
head_for_key = concept_head


def concept_mirror(term: Any) -> int:
    """Mirror (bit-reversed) head for a concept."""
    return reverse8(fnv_head(term))


def _pair_start(a: int) -> int:
    return 1 + a * (511 - a) // 2


def pair_id(a: Any, b: Any) -> int:
    """Canonical 1..32640 pair id for two distinct heads."""
    a, b = _head(a), _head(b)
    if a == b:
        raise CorpusMapperError("a palindromic head does not identify a pair")
    if a > b:
        a, b = b, a
    return 1 + a * (511 - a) // 2 + (b - a - 1)


pair_id_for_heads = pair_id
rank_of_pair = pair_id


def decode_pair_id(value: Any, *, allow_void: bool = False) -> tuple[int, int] | None:
    """Decode a canonical pair id to ``(a, b)`` with ``a < b``."""
    if type(value) is int and value == 0:
        if allow_void:
            return None
        raise CorpusMapperError("pair id 0 is the void sentinel, not a pair")
    value = _pair_int(value)
    low, high = 0, HEADS - 2
    while low <= high:
        middle = (low + high) // 2
        start = _pair_start(middle)
        end = _pair_start(middle + 1) - 1
        if value < start:
            high = middle - 1
        elif value > end:
            low = middle + 1
        else:
            a = middle
            b = a + 1 + value - start
            if not 0 <= a < b < HEADS:
                break
            return a, b
    raise CorpusMapperError("pair id does not decode inside the head range")


def pair_heads(value: Any) -> tuple[int, int]:
    """Alias for :func:`decode_pair_id`; the void id is not a pair."""
    result = decode_pair_id(value)
    assert result is not None
    return result


def is_void_pair_id(value: Any) -> bool:
    return type(value) is int and value == 0


# ---------------------------------------------------------------------------
# Concept identities
# ---------------------------------------------------------------------------

def concept_digest(term: Any) -> str:
    """Full SHA-256 of the domain-separated concept identity."""
    identity = _require_identity(term, "concept")
    return hashlib.sha256(CONCEPT_DOMAIN + identity.encode("utf-8")).hexdigest()


def concept_id(term: Any) -> str:
    """Full 64-hex SHA-256 concept identity (domain separated)."""
    return concept_digest(term)


def concept_alias(term: Any) -> str:
    """Compact ``concept:<32hex>`` leaf alias (first 16 digest bytes)."""
    return CONCEPT_PREFIX + concept_digest(term)[:32]


def concept_hex(term: Any) -> str:
    """First 16 digest bytes as 32 lowercase hex characters."""
    return concept_digest(term)[:32]


concept_id_raw = concept_hex
concept_id_hex = concept_hex
concept_sha256 = concept_digest
concept_id_full = concept_digest


def map_concept(term: Any) -> dict[str, Any]:
    """Map one concept to its stable id, head, mirror and related pair ids."""
    normalized = normalize_text(term)
    if not normalized:
        raise CorpusMapperError("concept must not be empty")
    identity = normalized.casefold()
    head = fnv_head(identity)
    mirror = reverse8(head)
    head_pair = pair_id(REFERENCE_HEAD, head) if head != REFERENCE_HEAD else None
    mirror_pair = (pair_id(REFERENCE_HEAD, mirror)
                   if mirror != REFERENCE_HEAD else None)
    head_mirror = pair_id(head, mirror) if head != mirror else None
    digest = concept_digest(identity)
    return {
        "schema": SCHEMA,
        "concept_id": digest,
        "concept_digest": digest,
        "concept_hex": digest[:32],
        "concept_alias": CONCEPT_PREFIX + digest[:32],
        "text": normalized,
        "identity": identity,
        "head": head,
        "head_fnv": head,
        "head_sha256": int(digest[:2], 16),
        "sha256_head": int(digest[:2], 16),
        "mirror_head": mirror,
        "palindromic_head": head == mirror,
        "reference_head": REFERENCE_HEAD,
        "head_pair_id": head_pair,
        "mirror_pair_id": mirror_pair,
        "head_mirror_pair_id": head_mirror,
        "pair_id": head_mirror,
        "host_only": True,
        "native_execution": False,
        "training_performed": False,
    }


# ---------------------------------------------------------------------------
# Field coercion
# ---------------------------------------------------------------------------

def _bounded_int(name: str, value: Any, default: int, maximum: int) -> int:
    if value is None:
        return default
    if type(value) is not int or not 1 <= value <= maximum:
        raise CorpusBoundError(f"{name} must be an integer 1..{maximum}")
    return value


def _optional_text(value: Any, name: str, *,
                   maximum: int = MAX_METADATA_CHARS) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CorpusRowError(f"{name} must be a string")
    normalized = normalize_text(value)
    if not normalized:
        return None
    if len(normalized) > maximum:
        raise CorpusRowError(f"{name} exceeds {maximum} characters")
    return normalized


def _row_optional(item: Mapping[str, Any], name: str,
                  aliases: tuple[str, ...] = (),
                  maximum: int = MAX_METADATA_CHARS) -> str | None:
    value = item.get(name)
    if value is None:
        for alias in aliases:
            if item.get(alias) is not None:
                value = item.get(alias)
                break
    return _optional_text(value, name, maximum=maximum)


def _parse_split(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CorpusRowError("split must be a string")
    key = value.strip().casefold()
    if not key:
        return None
    split = _SPLIT_ALIASES.get(key)
    if split is None:
        raise CorpusRowError("split must be train, validation or test")
    return split


def _parse_confidence(value: Any) -> float:
    if value is None:
        return DEFAULT_CONFIDENCE
    if type(value) is bool or not isinstance(value, (int, float)):
        raise CorpusRowError("confidence must be a finite number in [0, 1]")
    confidence = float(value)
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise CorpusRowError("confidence must be a finite number in [0, 1]")
    return confidence


def _parse_polarity(value: Any) -> tuple[str, int]:
    if value is None:
        return "neutral", 0
    if type(value) is bool:
        raise CorpusRowError("polarity must not be a boolean")
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number) or not -1.0 <= number <= 1.0:
            raise CorpusRowError("numeric polarity must be in [-1, 1]")
        if number > 0:
            return "supports", 1
        if number < 0:
            return "refutes", -1
        return "neutral", 0
    if not isinstance(value, str):
        raise CorpusRowError("polarity must be a string or number")
    key = value.strip().casefold()
    if not key:
        return "neutral", 0
    name = _POLARITY_ALIASES.get(key)
    if name is None:
        raise CorpusRowError("polarity must be supports, refutes or neutral")
    return name, {"supports": 1, "refutes": -1, "neutral": 0}[name]


def _normalize_source_digest(value: Any) -> str:
    if not _is_digest(value):
        raise CorpusRowError("source_digest must be a full SHA-256 hex digest")
    return value.lower()


def _default_source(value: Any) -> str | None:
    return None if value is None else _normalize_source_digest(value)


# ---------------------------------------------------------------------------
# Provenance and record construction
# ---------------------------------------------------------------------------

def _row_identity(item: Mapping[str, Any], *, text: str,
                  parts: Mapping[str, str], synset: str | None,
                  lexfile: str | None) -> dict[str, Any]:
    identity: dict[str, Any] = {"text": identity_text(text)}
    if parts:
        identity["relation"] = {name: identity_text(value)
                                for name, value in sorted(parts.items())}
    for key in ("record_id", "source"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            identity[key] = value.strip()
    if synset is not None:
        identity["synset"] = identity_text(synset)
    if lexfile is not None:
        identity["lexfile"] = identity_text(lexfile)
    return identity


def _source_digest(item: Mapping[str, Any], identity: Mapping[str, Any],
                   default: str | None = None) -> tuple[str, bool]:
    raw = item.get("source_digest")
    if raw is None:
        raw = default
    if raw is not None:
        return _normalize_source_digest(raw), False
    return _digest(SOURCE_DOMAIN, {"identity": identity}), True


def _provenance(item: Mapping[str, Any], *, line: int, source_digest: str,
                derived: bool, split: str | None, synset: str | None,
                lexfile: str | None) -> dict[str, Any]:
    raw = item.get("provenance")
    if raw is None:
        supplied: dict[str, Any] = {}
    elif isinstance(raw, Mapping):
        supplied = _sanitize(raw)
    else:
        raise CorpusRowError("provenance must be an object")
    provenance: dict[str, Any] = {
        "schema": SCHEMA,
        "source_digest": source_digest,
        "line": line,
        "jsonl_lines": [line],
    }
    if derived:
        provenance["source_digest_derived"] = True
        provenance["derived"] = True
    for name, value in (("split", split), ("synset", synset),
                        ("lexfile", lexfile)):
        if value is not None:
            provenance[name] = value
    for key in ("record_id", "source"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            provenance[key] = value.strip()[:MAX_METADATA_CHARS]
    if supplied:
        provenance["input"] = supplied
    return provenance


def _concept_fields(term: str) -> dict[str, Any]:
    mapped = map_concept(term)
    return {
        "text": mapped["text"],
        "identity": mapped["identity"],
        "concept_id": mapped["concept_id"],
        "concept_digest": mapped["concept_digest"],
        "concept_hex": mapped["concept_hex"],
        "concept_alias": mapped["concept_alias"],
        "leaf_id": mapped["concept_alias"],
        "head": mapped["head"],
        "head_fnv": mapped["head_fnv"],
        "head_sha256": mapped["head_sha256"],
        "sha256_head": mapped["sha256_head"],
        "mirror_head": mapped["mirror_head"],
        "head_pair_id": mapped["head_pair_id"],
        "mirror_pair_id": mapped["mirror_pair_id"],
        "head_mirror_pair_id": mapped["head_mirror_pair_id"],
        "pair_id": mapped["pair_id"],
    }


def _leaf_record(text: str, *, kind: str, roles: Iterable[str],
                 source_digest: str, provenance: Mapping[str, Any],
                 split: str | None, synset: str | None, lexfile: str | None,
                 confidence: float, polarity: str, polarity_value: int,
                 relation_status: str, parts: Mapping[str, Any],
                 missing: Iterable[str]) -> dict[str, Any]:
    concept = _concept_fields(text)
    role_list = sorted(set(roles))
    record = {
        "type": "leaf",
        "record_type": "observation" if kind == "observation" else "leaf",
        "schema": SCHEMA,
        "leaf_id": concept["leaf_id"],
        "kind": kind,
        "role": role_list[0] if len(role_list) == 1 else "multiple",
        "roles": role_list,
        "text": normalize_text(text),
        "identity": identity_text(text),
        "source_digest": source_digest,
        "provenance": _sanitize(dict(provenance)),
        "split": split,
        "synset": synset,
        "lexfile": lexfile,
        "confidence": confidence,
        "polarity": polarity,
        "polarity_value": polarity_value,
        "polarity_int": polarity_value,
        "relation_status": relation_status,
        "status": ("incomplete_relation" if relation_status == "incomplete"
                   else "observation" if kind == "observation"
                   else "relation_evidence" if kind == "evidence"
                   else "concept"),
        "neutral": polarity == "neutral",
        "parts": _sanitize(dict(parts)),
        "part_texts": {
            name: value["text"] for name, value in sorted(parts.items())
            if isinstance(value, Mapping) and "text" in value
        },
        "provided_relation_fields": sorted(parts),
        "missing_relation_fields": sorted(set(missing)),
        "immutable": True,
        "candidate_only": True,
        "observation": kind == "observation",
        "host_only": True,
        "db_write": False,
        "native_execution": False,
        "native_execution_verified": False,
        "training_performed": False,
        "math_rule_promoted": False,
        "canonical_training_committed": False,
        "learning_claimed": False,
        "learned": False,
        "occurrences": 1,
    }
    for name in _RELATION_PARTS:
        if name in record["part_texts"]:
            record[name] = record["part_texts"][name]
    record.update(concept)
    return record


def _relation_record(item: Mapping[str, Any], *, subject: str, predicate: str,
                     obj: str, source_digest: str,
                     provenance: Mapping[str, Any], split: str | None,
                     synset: str | None, lexfile: str | None,
                     confidence: float, polarity: str,
                     polarity_value: int) -> dict[str, Any]:
    subject_map = map_concept(subject)
    predicate_map = map_concept(predicate)
    object_map = map_concept(obj)
    semantics = {
        "schema": SCHEMA,
        "subject": subject.casefold(),
        "predicate": predicate.casefold(),
        "object": obj.casefold(),
        "polarity": polarity,
        "polarity_value": polarity_value,
        "confidence": round(confidence, 6),
        "source_digest": source_digest,
    }
    relation_hash = _digest(RELATION_DOMAIN, semantics)
    relation_id = "rel:" + relation_hash[:32]

    def pair_entry(first: Mapping[str, Any], second: Mapping[str, Any]) -> dict[str, Any] | None:
        a, b = first["head"], second["head"]
        if a == b:
            return None
        low, high = (a, b) if a < b else (b, a)
        return {"pair_id": pair_id(low, high), "heads": [low, high]}

    subject_predicate = pair_entry(subject_map, predicate_map)
    predicate_object = pair_entry(predicate_map, object_map)
    subject_object = pair_entry(subject_map, object_map)
    pairs = {
        "subject_predicate": subject_predicate,
        "predicate_object": predicate_object,
        "subject_object": subject_object,
    }
    pair_ids = sorted({entry["pair_id"] for entry in pairs.values()
                       if entry is not None})
    record = {
        "type": "relation",
        "record_type": "relation",
        "schema": SCHEMA,
        "relation_id": relation_id,
        "relation_hash": relation_hash,
        "subject": subject,
        "predicate": predicate,
        "object": obj,
        "subject_identity": subject.casefold(),
        "predicate_identity": predicate.casefold(),
        "object_identity": obj.casefold(),
        "subject_concept_id": subject_map["concept_id"],
        "predicate_concept_id": predicate_map["concept_id"],
        "object_concept_id": object_map["concept_id"],
        "subject_id": subject_map["concept_id"],
        "predicate_id": predicate_map["concept_id"],
        "object_id": object_map["concept_id"],
        "subject_leaf_id": subject_map["concept_alias"],
        "predicate_leaf_id": predicate_map["concept_alias"],
        "object_leaf_id": object_map["concept_alias"],
        "subject_concept_alias": subject_map["concept_alias"],
        "predicate_concept_alias": predicate_map["concept_alias"],
        "object_concept_alias": object_map["concept_alias"],
        "subject_digest": subject_map["concept_digest"],
        "predicate_digest": predicate_map["concept_digest"],
        "object_digest": object_map["concept_digest"],
        "subject_head": subject_map["head"],
        "predicate_head": predicate_map["head"],
        "object_head": object_map["head"],
        "subject_mirror": subject_map["mirror_head"],
        "predicate_mirror": predicate_map["mirror_head"],
        "object_mirror": object_map["mirror_head"],
        "subject_pair_id": subject_map["pair_id"],
        "predicate_pair_id": predicate_map["pair_id"],
        "object_pair_id": object_map["pair_id"],
        "subject_head_pair_id": subject_map["head_pair_id"],
        "predicate_head_pair_id": predicate_map["head_pair_id"],
        "object_head_pair_id": object_map["head_pair_id"],
        "heads": [subject_map["head"], predicate_map["head"],
                  object_map["head"]],
        "mirror_heads": [subject_map["mirror_head"],
                         predicate_map["mirror_head"],
                         object_map["mirror_head"]],
        "pair_id": subject_object["pair_id"] if subject_object else None,
        "pair_heads": subject_object["heads"] if subject_object else None,
        "pair_status": "canonical" if subject_object else "same_head",
        "subject_object_pair_id": (subject_object["pair_id"]
                                   if subject_object else None),
        "subject_predicate_pair_id": (subject_predicate["pair_id"]
                                      if subject_predicate else None),
        "predicate_object_pair_id": (predicate_object["pair_id"]
                                     if predicate_object else None),
        "pairs": pairs,
        "pair_ids": pair_ids,
        "source_digest": source_digest,
        "provenance": _sanitize(dict(provenance)),
        "split": split,
        "synset": synset,
        "lexfile": lexfile,
        "confidence": confidence,
        "polarity": polarity,
        "polarity_value": polarity_value,
        "polarity_int": polarity_value,
        "relation_status": "complete",
        "status": "relation",
        "neutral": polarity == "neutral",
        "candidate_only": True,
        "host_only": True,
        "db_write": False,
        "native_execution": False,
        "native_execution_verified": False,
        "training_performed": False,
        "math_rule_promoted": False,
        "canonical_training_committed": False,
        "learning_claimed": False,
        "learned": False,
        "occurrences": 1,
    }
    return record


def _cycle_record(relation: Mapping[str, Any]) -> dict[str, Any] | None:
    """Build formula-only cycle metadata for reference head 0, or ``None``."""
    i = relation["subject_head"]
    j = relation["object_head"]
    if i == REFERENCE_HEAD or j == REFERENCE_HEAD or i == j:
        return None
    low, high = (i, j) if i < j else (j, i)
    pair_0_i = pair_id(REFERENCE_HEAD, i)
    pair_i_j = pair_id(low, high)
    pair_0_j = pair_id(REFERENCE_HEAD, j)
    cycle_hash = _digest(CYCLE_DOMAIN, {
        "reference_head": REFERENCE_HEAD,
        "heads": [low, high],
        "source_digest": relation["source_digest"],
    })
    formula = "anti(0,i) + anti(i,j) - anti(0,j)"
    anti_formula = "0.5 * (w(i,j) - w(j,i))"
    from_provenance = _sanitize(relation.get("provenance", {}))
    return {
        "type": "cycle_candidate",
        "record_type": "cycle_candidate",
        "kind": "cycle_candidate",
        "schema": SCHEMA,
        "cycle_id": "cycle:" + cycle_hash[:32],
        "cycle_hash": cycle_hash,
        "reference_head": REFERENCE_HEAD,
        "heads": [i, j],
        "cycle": [REFERENCE_HEAD, i, j],
        "cycle_heads": [REFERENCE_HEAD, i, j],
        "canonical_heads": [low, high],
        "triangle": [REFERENCE_HEAD, i, j, REFERENCE_HEAD],
        "pairs": [
            {"from": REFERENCE_HEAD, "to": i, "pair_id": pair_0_i,
             "heads": [REFERENCE_HEAD, i]},
            {"from": i, "to": j, "pair_id": pair_i_j, "heads": [low, high]},
            {"from": REFERENCE_HEAD, "to": j, "pair_id": pair_0_j,
             "heads": [REFERENCE_HEAD, j]},
        ],
        "edges": [
            {"source_head": REFERENCE_HEAD, "target_head": i,
             "pair_id": pair_0_i},
            {"source_head": i, "target_head": j, "pair_id": pair_i_j},
            {"source_head": j, "target_head": REFERENCE_HEAD,
             "pair_id": pair_0_j},
        ],
        "pair_ids": [pair_0_i, pair_i_j, pair_0_j],
        "F_ij": {
            "name": "F_ij",
            "formula": formula,
            "anti_formula": anti_formula,
            "terms": [
                {"edge": [REFERENCE_HEAD, i], "pair_id": pair_0_i,
                 "coefficient": 1},
                {"edge": [i, j], "pair_id": pair_i_j, "coefficient": 1},
                {"edge": [REFERENCE_HEAD, j], "pair_id": pair_0_j,
                 "coefficient": -1},
            ],
            "evaluated": False,
            "value": None,
            "evaluation": "deferred_to_guest_or_authorized_maintenance",
        },
        "F_ij_formula": formula,
        "formula_compact": "anti(0,i)+anti(i,j)-anti(0,j)",
        "anti_formula": anti_formula,
        "anti_formula_compact": "0.5*(w(i,j)-w(j,i))",
        "cycle_loss_formula": "mean(F_ij^2)",
        "formula_metadata_only": True,
        "host_math_performed": False,
        "math_execution": False,
        "executed": False,
        "evaluated": False,
        "value": None,
        "relation_id": relation["relation_id"],
        "source_digest": relation["source_digest"],
        "provenance": from_provenance,
        "split": relation.get("split"),
        "candidate_only": True,
        "host_only": True,
        "db_write": False,
        "native_execution": False,
        "native_execution_verified": False,
        "training_performed": False,
        "math_rule_promoted": False,
        "canonical_training_committed": False,
        "learning_claimed": False,
        "learned": False,
        "occurrences": 1,
    }


def cycle_metadata(i: Any, j: Any, *, source_digest: Any = None,
                   relation_id: str | None = None,
                   provenance: Mapping[str, Any] | None = None,
                   split: str | None = None) -> dict[str, Any]:
    """Public formula-only cycle metadata helper for ``(0, i, j)``.

    No flux is evaluated.  ``i`` and ``j`` are head coordinates, not terms.
    """
    i, j = _head(i), _head(j)
    if i == REFERENCE_HEAD or j == REFERENCE_HEAD or i == j:
        raise CorpusMapperError("cycle (0,i,j) requires three distinct heads")
    if source_digest is None:
        digest = _digest(CYCLE_DOMAIN, {
            "reference_head": REFERENCE_HEAD,
            "heads": sorted((i, j)),
        })
    else:
        digest = _normalize_source_digest(source_digest)
    relation = {
        "subject_head": i,
        "object_head": j,
        "source_digest": digest,
        "relation_id": relation_id or "cycle-source",
        "provenance": _sanitize(dict(provenance or {})),
        "split": split,
    }
    cycle = _cycle_record(relation)
    assert cycle is not None
    return cycle


cycle_candidate = cycle_metadata
cycle_candidates = cycle_metadata


# ---------------------------------------------------------------------------
# Row mapping and idempotent deduplication
# ---------------------------------------------------------------------------

def _record_key(record: Mapping[str, Any]) -> tuple[Any, ...]:
    kind = record.get("type")
    if kind == "leaf":
        return (kind, record.get("leaf_id"), record.get("source_digest"),
                record.get("kind"), record.get("split"))
    if kind == "relation":
        return (kind, record.get("relation_id"), record.get("source_digest"),
                record.get("split"))
    if kind == "cycle_candidate":
        return (kind, record.get("cycle_id"), record.get("source_digest"),
                record.get("split"))
    return (kind, canonical_json(record))


def _merge_provenance(existing: dict[str, Any], incoming: Mapping[str, Any]) -> None:
    left = existing.setdefault("provenance", {})
    right = incoming.get("provenance", {})
    if not isinstance(left, dict) or not isinstance(right, Mapping):
        return
    lines = set(left.get("jsonl_lines", ())) | set(right.get("jsonl_lines", ()))
    if lines:
        left["jsonl_lines"] = sorted(lines)
    for key in ("source", "record_id"):
        if left.get(key) is None and right.get(key) is not None:
            left[key] = right[key]


def _absorb(existing: dict[str, Any], incoming: Mapping[str, Any]) -> None:
    existing["occurrences"] = int(existing.get("occurrences", 1)) + int(
        incoming.get("occurrences", 1))
    _merge_provenance(existing, incoming)
    if existing.get("type") == "leaf":
        roles = set(existing.get("roles", ())) | set(incoming.get("roles", ()))
        existing["roles"] = sorted(roles)
        existing["role"] = (existing["roles"][0] if len(roles) == 1
                            else "multiple")
        for key in ("synset", "lexfile"):
            if existing.get(key) is None and incoming.get(key) is not None:
                existing[key] = incoming[key]


def _prepare_row(item: Any, *, line: int, max_text_chars: int,
                 default_source_digest: str | None = None) -> list[dict[str, Any]]:
    if not isinstance(item, Mapping):
        raise CorpusRowError(f"row {line} must be a JSON object")
    raw_text = item.get("text")
    if not isinstance(raw_text, str):
        raise CorpusRowError(f"row {line} requires string text")
    text = normalize_text(raw_text)
    if len(text) < MIN_TEXT_CHARS:
        raise CorpusRowError(
            f"row {line} text must be at least {MIN_TEXT_CHARS} characters")
    if len(text) > max_text_chars:
        raise CorpusRowError(
            f"row {line} text exceeds {max_text_chars} characters")

    parts: dict[str, str] = {}
    for name in _RELATION_PARTS:
        value = item.get(name)
        if name == "predicate" and value is None:
            value = item.get("role")
        if value is None:
            continue
        if not isinstance(value, str):
            raise CorpusRowError(f"row {line} {name} must be a string")
        normalized = normalize_text(value)
        if not normalized:
            continue
        if len(normalized) > MAX_TERM_CHARS:
            raise CorpusRowError(
                f"row {line} {name} exceeds {MAX_TERM_CHARS} characters")
        parts[name] = normalized
    missing = [name for name in _RELATION_PARTS if name not in parts]
    complete = len(parts) == len(_RELATION_PARTS)
    incomplete = bool(parts) and not complete

    split = _parse_split(item.get("split"))
    synset = _row_optional(item, "synset", ("synset_id",))
    lexfile = _row_optional(item, "lexfile", ("lex_file", "lexname"))
    confidence = _parse_confidence(item.get("confidence"))
    polarity, polarity_value = _parse_polarity(item.get("polarity"))
    identity = _row_identity(item, text=text, parts=parts,
                             synset=synset, lexfile=lexfile)
    source_digest, derived = _source_digest(
        item, identity, default=default_source_digest)
    provenance = _provenance(
        item, line=line, source_digest=source_digest, derived=derived,
        split=split, synset=synset, lexfile=lexfile,
    )

    part_concepts = {name: _concept_fields(value)
                     for name, value in sorted(parts.items())}
    relation_status = ("complete" if complete else
                       "incomplete" if incomplete else "absent")
    records: list[dict[str, Any]] = []
    records.append(_leaf_record(
        text,
        kind="evidence" if complete else "observation",
        roles=["evidence"] if complete else ["observation"],
        source_digest=source_digest,
        provenance=provenance,
        split=split,
        synset=synset,
        lexfile=lexfile,
        confidence=confidence,
        polarity=polarity,
        polarity_value=polarity_value,
        relation_status=relation_status,
        parts=part_concepts,
        missing=missing if incomplete else (),
    ))

    if complete:
        for name in _RELATION_PARTS:
            records.append(_leaf_record(
                parts[name],
                kind="concept",
                roles=[name],
                source_digest=source_digest,
                provenance=provenance,
                split=split,
                synset=synset,
                lexfile=lexfile,
                confidence=confidence,
                polarity=polarity,
                polarity_value=polarity_value,
                relation_status="complete",
                parts={name: part_concepts[name]},
                missing=(),
            ))
        relation = _relation_record(
            item,
            subject=parts["subject"],
            predicate=parts["predicate"],
            obj=parts["object"],
            source_digest=source_digest,
            provenance=provenance,
            split=split,
            synset=synset,
            lexfile=lexfile,
            confidence=confidence,
            polarity=polarity,
            polarity_value=polarity_value,
        )
        records.append(relation)
    return records


def _prepare_records_from_pairs(
    pairs: Iterable[tuple[int, Any]], *, max_rows: int,
    max_text_chars: int, cycle_candidates: bool,
    default_source_digest: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    limit = _bounded_int("max_rows", max_rows, MAX_ROWS, MAX_ROWS)
    text_limit = _bounded_int(
        "max_text_chars", max_text_chars, MAX_TEXT_CHARS, MAX_TEXT_CHARS)
    ordered: dict[tuple[Any, ...], dict[str, Any]] = {}
    count = 0
    for line, row in pairs:
        count += 1
        if count > limit:
            raise CorpusBoundError(f"JSONL row count exceeds {limit}")
        prepared = _prepare_row(
            row, line=line, max_text_chars=text_limit,
            default_source_digest=default_source_digest)
        if cycle_candidates:
            relation = next((record for record in prepared
                             if record.get("type") == "relation"), None)
            if relation is not None:
                cycle = _cycle_record(relation)
                if cycle is not None:
                    prepared.append(cycle)
        for record in prepared:
            key = _record_key(record)
            existing = ordered.get(key)
            if existing is None:
                ordered[key] = record
            else:
                _absorb(existing, record)
    return list(ordered.values()), count


def _cycle_choice(cycle_candidates: Any,
                  include_cycles: Any = None) -> bool:
    if type(cycle_candidates) is not bool:
        raise CorpusMapperError("cycle_candidates must be a boolean")
    if include_cycles is None:
        return cycle_candidates
    if type(include_cycles) is not bool:
        raise CorpusMapperError("include_cycles must be a boolean")
    return include_cycles


def _as_rows(rows: Any) -> Iterable[Any]:
    if isinstance(rows, Mapping):
        return [rows]
    if isinstance(rows, (str, bytes, bytearray)):
        raise CorpusMapperError("rows must be an iterable of objects")
    try:
        return iter(rows)
    except TypeError as exc:
        raise CorpusMapperError("rows must be an iterable of objects") from exc


def prepare_records(rows: Any, *, max_rows: int = MAX_ROWS,
                    max_text_chars: int = MAX_TEXT_CHARS,
                    cycle_candidates: bool = False,
                    include_cycles: bool | None = None,
                    source_digest: str | None = None
                    ) -> list[dict[str, Any]]:
    """Prepare records from bounded in-memory rows; pure and idempotent."""
    cycle_candidates = _cycle_choice(cycle_candidates, include_cycles)
    default_source = _default_source(source_digest)
    pairs = ((index, row) for index, row in enumerate(_as_rows(rows), 1))
    records, _count = _prepare_records_from_pairs(
        pairs, max_rows=max_rows, max_text_chars=max_text_chars,
        cycle_candidates=cycle_candidates,
        default_source_digest=default_source,
    )
    return records


def _batch_from_records(records: list[dict[str, Any]], count: int) -> dict[str, Any]:
    safe_records = [_sanitize(record) for record in records]
    leaves = [record for record in safe_records
              if record.get("type") == "leaf"]
    relations = [record for record in safe_records
                 if record.get("type") == "relation"]
    observations = [record for record in leaves
                    if record.get("kind") == "observation"]
    cycles = [record for record in safe_records
              if record.get("type") == "cycle_candidate"]
    digests = sorted({str(record.get("source_digest"))
                      for record in safe_records if record.get("source_digest")})
    splits = sorted({str(record.get("split"))
                     for record in safe_records if record.get("split")})
    counts = {
        "rows": count,
        "records": len(safe_records),
        "leaves": len(leaves),
        "relations": len(relations),
        "observations": len(observations),
        "cycle_candidates": len(cycles),
        "concepts": len({record.get("concept_id") for record in leaves}),
        "incomplete_observations": sum(
            1 for record in observations
            if record.get("relation_status") == "incomplete"),
        "neutral_relations": sum(
            1 for record in relations
            if record.get("polarity") == "neutral"),
        "duplicate_occurrences": sum(
            int(record.get("occurrences", 1)) - 1
            for record in safe_records),
    }
    checksum = hashlib.sha256(canonical_json(safe_records).encode("utf-8")).hexdigest()
    return {
        "schema": SCHEMA,
        "records": safe_records,
        "leaves": leaves,
        "relations": relations,
        "observations": observations,
        "cycle_candidates": cycles,
        "leaf_records": leaves,
        "relation_records": relations,
        "observation_records": observations,
        "cycle_candidate_records": cycles,
        "counts": counts,
        "source_digests": digests,
        "splits": splits,
        "records_sha256": checksum,
        "bounded": True,
        "matrix_free": True,
        "dense_matrices_allocated": 0,
        "candidate_only": True,
        "host_only": True,
        "db_writes": False,
        "native_execution": False,
        "native_execution_verified": False,
        "training_performed": False,
        "math_rule_promoted": False,
        "canonical_training_committed": False,
        "learning_claimed": False,
    }


def prepare_batch(rows: Any, *, max_rows: int = MAX_ROWS,
                  max_text_chars: int = MAX_TEXT_CHARS,
                  cycle_candidates: bool = False,
                  include_cycles: bool | None = None,
                  source_digest: str | None = None) -> dict[str, Any]:
    """Prepare one bounded batch plus compact counts and checksum."""
    cycle_candidates = _cycle_choice(cycle_candidates, include_cycles)
    default_source = _default_source(source_digest)
    pairs = ((index, row) for index, row in enumerate(_as_rows(rows), 1))
    records, count = _prepare_records_from_pairs(
        pairs, max_rows=max_rows, max_text_chars=max_text_chars,
        cycle_candidates=cycle_candidates,
        default_source_digest=default_source,
    )
    return _batch_from_records(records, count)


# ---------------------------------------------------------------------------
# Bounded JSONL reader
# ---------------------------------------------------------------------------

class _DuplicateKey(ValueError):
    pass


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateKey(f"duplicate JSON key {key!r}")
        value[key] = item
    return value


def _iter_lines(source: Any) -> Iterator[str]:
    if isinstance(source, (str, os.PathLike, Path)):
        try:
            with open(source, "r", encoding="utf-8", newline="") as stream:
                yield from stream
        except (OSError, UnicodeDecodeError) as exc:
            raise CorpusMapperError(f"cannot read JSONL source: {exc}") from exc
        return
    if hasattr(source, "read"):
        data = source.read()
        if isinstance(data, bytes):
            try:
                data = data.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise CorpusMapperError("JSONL source is not UTF-8") from exc
        if not isinstance(data, str):
            raise CorpusMapperError("JSONL stream must return text")
        yield from data.splitlines()
        return
    if isinstance(source, (bytes, bytearray)):
        raise CorpusMapperError("JSONL source must be a path, stream or lines")
    try:
        iterator = iter(source)
    except TypeError as exc:
        raise CorpusMapperError("JSONL source must be iterable") from exc
    for item in iterator:
        if isinstance(item, bytes):
            try:
                item = item.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise CorpusMapperError("JSONL line is not UTF-8") from exc
        if not isinstance(item, str):
            raise CorpusMapperError("JSONL lines must be strings")
        yield item


def _iter_jsonl_with_lines(source: Any, *, max_rows: int,
                           max_line_bytes: int
                           ) -> Iterator[tuple[int, dict[str, Any]]]:
    row_limit = _bounded_int("max_rows", max_rows, MAX_ROWS, MAX_ROWS)
    line_limit = _bounded_int(
        "max_line_bytes", max_line_bytes, MAX_LINE_BYTES, MAX_LINE_BYTES)
    count = 0
    for line_number, raw in enumerate(_iter_lines(source), 1):
        if len(raw.encode("utf-8")) > line_limit:
            raise CorpusBoundError(
                f"JSONL line {line_number} exceeds {line_limit} bytes")
        text = raw.lstrip("\ufeff").strip()
        if not text:
            continue
        count += 1
        if count > row_limit:
            raise CorpusBoundError(f"JSONL row count exceeds {row_limit}")
        try:
            value = json.loads(text, object_pairs_hook=_no_duplicate_keys)
        except (json.JSONDecodeError, _DuplicateKey) as exc:
            raise CorpusRowError(
                f"malformed JSON on line {line_number}: {exc}") from exc
        if not isinstance(value, dict):
            raise CorpusRowError(
                f"JSONL line {line_number} must contain one object")
        yield line_number, value


def iter_jsonl(source: Any, *, max_rows: int = MAX_ROWS,
               max_line_bytes: int = MAX_LINE_BYTES) -> Iterator[dict[str, Any]]:
    """Yield bounded JSON objects from a path, stream or iterable of lines."""
    for _line, row in _iter_jsonl_with_lines(
            source, max_rows=max_rows, max_line_bytes=max_line_bytes):
        yield row


def read_jsonl(source: Any, *, max_rows: int = MAX_ROWS,
               max_line_bytes: int = MAX_LINE_BYTES) -> list[dict[str, Any]]:
    """Read a bounded JSONL source into a list of JSON objects."""
    return list(iter_jsonl(source, max_rows=max_rows,
                           max_line_bytes=max_line_bytes))


load_jsonl = read_jsonl


def prepare_jsonl(source: Any, *, max_rows: int = MAX_ROWS,
                  max_line_bytes: int = MAX_LINE_BYTES,
                  max_text_chars: int = MAX_TEXT_CHARS,
                  cycle_candidates: bool = False,
                  include_cycles: bool | None = None,
                  source_digest: str | None = None) -> dict[str, Any]:
    """Read a bounded JSONL source and prepare one mapping batch."""
    cycle_candidates = _cycle_choice(cycle_candidates, include_cycles)
    default_source = _default_source(source_digest)
    pairs = _iter_jsonl_with_lines(
        source, max_rows=max_rows, max_line_bytes=max_line_bytes)
    records, count = _prepare_records_from_pairs(
        pairs, max_rows=max_rows, max_text_chars=max_text_chars,
        cycle_candidates=cycle_candidates,
        default_source_digest=default_source,
    )
    return _batch_from_records(records, count)


def map_rows(rows: Any, *, max_rows: int = MAX_ROWS,
             max_text_chars: int = MAX_TEXT_CHARS,
             max_line_bytes: int = MAX_LINE_BYTES,
             cycle_candidates: bool = False,
             include_cycles: bool | None = None,
             source_digest: str | None = None) -> dict[str, Any]:
    """Map in-memory rows or a JSONL path/stream to one batch."""
    if isinstance(rows, (str, os.PathLike, Path)) or hasattr(rows, "read"):
        return prepare_jsonl(
            rows, max_rows=max_rows, max_line_bytes=max_line_bytes,
            max_text_chars=max_text_chars,
            cycle_candidates=cycle_candidates, include_cycles=include_cycles,
            source_digest=source_digest)
    return prepare_batch(
        rows, max_rows=max_rows, max_text_chars=max_text_chars,
        cycle_candidates=cycle_candidates, include_cycles=include_cycles,
        source_digest=source_digest)


map_corpus = map_rows
map_jsonl = prepare_jsonl
prepare_corpus = map_rows


class CorpusMirrorMapper:
    """Reusable bounded host plumber; owns no database or native state."""

    def __init__(self, *, max_rows: int = MAX_ROWS,
                 max_line_bytes: int = MAX_LINE_BYTES,
                 max_text_chars: int = MAX_TEXT_CHARS):
        self.max_rows = _bounded_int("max_rows", max_rows, MAX_ROWS, MAX_ROWS)
        self.max_line_bytes = _bounded_int(
            "max_line_bytes", max_line_bytes, MAX_LINE_BYTES, MAX_LINE_BYTES)
        self.max_text_chars = _bounded_int(
            "max_text_chars", max_text_chars, MAX_TEXT_CHARS, MAX_TEXT_CHARS)

    def prepare_records(self, rows: Any, *,
                        cycle_candidates: bool = False,
                        include_cycles: bool | None = None,
                        source_digest: str | None = None
                        ) -> list[dict[str, Any]]:
        return prepare_records(
            rows, max_rows=self.max_rows, max_text_chars=self.max_text_chars,
            cycle_candidates=cycle_candidates, include_cycles=include_cycles,
            source_digest=source_digest)

    def prepare(self, rows: Any, *, cycle_candidates: bool = False,
                include_cycles: bool | None = None,
                source_digest: str | None = None) -> dict[str, Any]:
        return prepare_batch(
            rows, max_rows=self.max_rows, max_text_chars=self.max_text_chars,
            cycle_candidates=cycle_candidates, include_cycles=include_cycles,
            source_digest=source_digest)

    def map_rows(self, rows: Any, *, cycle_candidates: bool = False,
                 include_cycles: bool | None = None,
                 source_digest: str | None = None) -> dict[str, Any]:
        return map_rows(
            rows, max_rows=self.max_rows,
            max_line_bytes=self.max_line_bytes,
            max_text_chars=self.max_text_chars,
            cycle_candidates=cycle_candidates, include_cycles=include_cycles,
            source_digest=source_digest)

    map = map_rows

    def read_jsonl(self, source: Any) -> list[dict[str, Any]]:
        return read_jsonl(source, max_rows=self.max_rows,
                          max_line_bytes=self.max_line_bytes)

    def prepare_jsonl(self, source: Any, *,
                      cycle_candidates: bool = False,
                      include_cycles: bool | None = None,
                      source_digest: str | None = None) -> dict[str, Any]:
        return prepare_jsonl(
            source, max_rows=self.max_rows,
            max_line_bytes=self.max_line_bytes,
            max_text_chars=self.max_text_chars,
            cycle_candidates=cycle_candidates, include_cycles=include_cycles,
            source_digest=source_digest)

    map_jsonl = prepare_jsonl


CorpusToMirrorMapper = CorpusMirrorMapper
MirrorCorpusMapper = CorpusMirrorMapper


def status() -> dict[str, Any]:
    """Describe the bounded host-only mapper without allocating a matrix."""
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "max_rows": MAX_ROWS,
        "max_line_bytes": MAX_LINE_BYTES,
        "max_text_chars": MAX_TEXT_CHARS,
        "min_text_chars": MIN_TEXT_CHARS,
        "heads": HEADS,
        "reference_head": REFERENCE_HEAD,
        "pair_count": PAIR_ID_MAX,
        "pair_id_formula": PAIR_ID_FORMULA,
        "concept_domain": CONCEPT_DOMAIN.decode("utf-8"),
        "concept_id_format": "sha256-hex (64 lowercase)",
        "concept_alias_format": "concept:<32hex>",
        "head_mapping": "fnv1a32(utf8(casefold(normalized(term)))) % 256",
        "mirror_mapping": "reverse8(head)",
        "bounded": True,
        "matrix_free": True,
        "dense_matrices_allocated": 0,
        "host_only": True,
        "db_writes": DB_WRITES,
        "native_execution": NATIVE_EXECUTION,
        "native_execution_verified": False,
        "training_performed": TRAINING_PERFORMED,
        "math_rule_promoted": False,
        "canonical_training_committed": False,
        "learning_claimed": LEARNING_CLAIMED,
        "cycle_candidates_optional": True,
        "cycle_reference_head": REFERENCE_HEAD,
        "cycle_formula": "anti(0,i) + anti(i,j) - anti(0,j)",
        "cycle_evaluation": "deferred_to_guest_or_authorized_maintenance",
    }


__all__ = [
    "SCHEMA", "VERSION", "MAP_SCHEMA",
    "MAX_ROWS", "MAX_BATCH", "MAX_LINE_BYTES", "MAX_TEXT_CHARS",
    "MIN_TEXT_CHARS", "MAX_TERM_CHARS", "HEADS", "HEAD_COUNT",
    "NANNET0_HEAD", "REFERENCE_HEAD", "PAIR_ID_MIN", "PAIR_ID_MAX",
    "PAIR_COUNT", "PAIR_ID_FORMULA", "CONCEPT_PREFIX",
    "CONCEPT_DIGEST_BYTES", "DEFAULT_CONFIDENCE", "VALID_SPLITS",
    "VALID_POLARITIES",
    "CorpusMapperError", "CorpusRowError", "CorpusBoundError",
    "CorpusMappingError", "MirrorCorpusError",
    "normalize_text", "identity_text", "canonical_json",
    "concept_digest", "concept_id", "concept_alias", "concept_hex",
    "concept_id_raw", "concept_id_hex", "concept_sha256",
    "concept_id_full", "fnv_head", "concept_head", "head_for_term",
    "head_for_concept", "head_for_key", "concept_mirror", "reverse8",
    "pair_id", "pair_id_for_heads", "rank_of_pair", "decode_pair_id",
    "pair_heads", "is_void_pair_id", "map_concept", "cycle_metadata",
    "cycle_candidate", "cycle_candidates",
    "prepare_records", "prepare_batch", "prepare_jsonl",
    "read_jsonl", "load_jsonl", "iter_jsonl",
    "map_rows", "map_corpus", "map_jsonl", "prepare_corpus",
    "CorpusMirrorMapper", "CorpusToMirrorMapper", "MirrorCorpusMapper",
    "status",
]
