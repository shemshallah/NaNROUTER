"""Host-only append-only hyperedge arena for recursive mirror memory.

This module is deliberately a *plain in-memory* data structure.  It owns no
SQLite database, evaluates no mathematics, dispatches no native guest, and
performs no canonical merge.  A hyperedge is a small immutable record linked
into one pair-membership chain by an integer ``next`` index.  Stable IDs start
at 1 and 0 is the null hyperedge.

The arena exposes only copied records.  Internal list slots and chain pointers
never escape, and membership indexes only grow.  Traversal is bounded by an
explicit depth and record limit.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import struct
from typing import Any, Mapping

SCHEMA = "nanrouter.mirror-hyperedge-arena/1"
VERSION = 1
ARENA_SCHEMA = SCHEMA

PAIR_ID_MIN = 1
PAIR_ID_MAX = 32640
NULL_HYPEREDGE_ID = 0
NULL_ID = NULL_HYPEREDGE_ID
U32_MAX = 0xFFFFFFFF

DEFAULT_LIMIT = 32
MAX_LIMIT = 256
DEFAULT_MAX_DEPTH = 8
MAX_DEPTH = 32

_RECORD_KEYS = frozenset({
    "id", "pair_id", "concept_id", "relation_type", "strength", "next",
    "parent_hyperedge_id",
})
_HEX_DIGEST = frozenset("0123456789abcdef")


class HyperedgeArenaError(ValueError):
    """A hyperedge arena request violated the append-only contract."""


MirrorHyperedgeError = HyperedgeArenaError


def _uint(name: str, value: Any, maximum: int, *, allow_null: bool = False) -> int:
    if type(value) is not int:
        raise HyperedgeArenaError(f"{name} must be an integer")
    if allow_null and value == NULL_HYPEREDGE_ID:
        return NULL_HYPEREDGE_ID
    if not 0 <= value <= maximum:
        raise HyperedgeArenaError(f"{name} must be in 0..{maximum}")
    return value


def _pair_id(value: Any) -> int:
    n = _uint("pair_id", value, PAIR_ID_MAX)
    if n < PAIR_ID_MIN:
        raise HyperedgeArenaError(
            f"pair_id must be in {PAIR_ID_MIN}..{PAIR_ID_MAX}")
    return n


def clamp_pair_id(value: Any) -> int:
    """Clamp an integer pair ID into the inclusive 1..32640 table range."""
    if type(value) is not int:
        raise HyperedgeArenaError("pair_id must be an integer")
    return max(PAIR_ID_MIN, min(PAIR_ID_MAX, value))


def _f32(value: Any) -> float:
    """Normalize a finite host number to its exact IEEE-754 binary32 value."""
    if type(value) not in (int, float):
        raise HyperedgeArenaError("strength must be a finite number")
    try:
        packed = struct.pack("<f", float(value))
    except (OverflowError, struct.error) as exc:
        raise HyperedgeArenaError("strength must fit a finite f32") from exc
    normalized = struct.unpack("<f", packed)[0]
    if normalized != normalized or normalized in (float("inf"), float("-inf")):
        raise HyperedgeArenaError("strength must be a finite f32")
    return normalized


def _digest(value: Any) -> str:
    if (type(value) is not str or len(value) != 64
            or any(ch not in _HEX_DIGEST for ch in value)):
        raise HyperedgeArenaError("digest must be lowercase SHA-256")
    return value


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def _records_digest(records: list[dict]) -> str:
    payload = {"schema": SCHEMA, "version": VERSION, "records": records}
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


@dataclass(frozen=True, slots=True)
class HyperedgeRecord:
    """One immutable append-only hyperedge slot."""

    id: int
    pair_id: int
    concept_id: int
    relation_type: int
    strength: float
    next: int
    parent_hyperedge_id: int | None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "pair_id": self.pair_id,
            "concept_id": self.concept_id,
            "relation_type": self.relation_type,
            "strength": self.strength,
            "next": self.next,
            "parent_hyperedge_id": self.parent_hyperedge_id,
        }


class MirrorHyperedgeArena:
    """Append-only hyperedges indexed by pair chain and concept incidence.

    ``pair_head(pair_id)`` is the most recent hyperedge for that pair.  Each
    record's ``next`` points to the previous member of the same pair, forming
    a reverse-chronological chain for bounded traversal.  Concept incidence is
    a separate append-only list per concept.  Duplicate payloads are valid and
    each append creates a new stable ID and new memberships.
    """

    def __init__(self, *, clamp_pairs: bool = False):
        if type(clamp_pairs) is not bool:
            raise HyperedgeArenaError("clamp_pairs must be a boolean")
        self._records: list[HyperedgeRecord | None] = [None]
        self._pair_heads: dict[int, int] = {}
        self._pair_members: dict[int, list[int]] = {}
        self._concept_members: dict[int, list[int]] = {}
        self._clamp_pairs = clamp_pairs

    # -- append ---------------------------------------------------------

    def add_hyperedge(self, pair_id: Any = None, concept_id: Any = None,
                      relation_type: Any = None, strength: Any = 1.0,
                      parent_hyperedge_id: Any = None, *,
                      clamp_pair: bool | None = None,
                      pair: Any = None, concept: Any = None,
                      relation: Any = None) -> dict:
        """Append one validated hyperedge and return its copied record.

        The pair ID is strict by default.  Pass ``clamp_pair=True`` (or build
        the arena with ``clamp_pairs=True``) to clamp an integer into the pair
        table.  Every validation completes before any index is changed.
        """
        if pair is not None:
            if pair_id is not None:
                raise HyperedgeArenaError("specify pair_id or pair, not both")
            pair_id = pair
        if concept is not None:
            if concept_id is not None:
                raise HyperedgeArenaError(
                    "specify concept_id or concept, not both")
            concept_id = concept
        if relation is not None:
            if relation_type is not None:
                raise HyperedgeArenaError(
                    "specify relation_type or relation, not both")
            relation_type = relation

        if clamp_pair is None:
            clamp = self._clamp_pairs
        elif type(clamp_pair) is bool:
            clamp = clamp_pair
        else:
            raise HyperedgeArenaError("clamp_pair must be a boolean")

        pair_id = clamp_pair_id(pair_id) if clamp else _pair_id(pair_id)
        concept_id = _uint("concept_id", concept_id, U32_MAX)
        relation_type = _uint("relation_type", relation_type, U32_MAX)
        strength = _f32(strength)
        parent = self._parent_id(parent_hyperedge_id)

        new_id = len(self._records)
        if new_id > U32_MAX:
            raise HyperedgeArenaError("hyperedge ID space exhausted")
        chain = self._pair_heads.get(pair_id, NULL_HYPEREDGE_ID)
        record = HyperedgeRecord(
            id=new_id,
            pair_id=pair_id,
            concept_id=concept_id,
            relation_type=relation_type,
            strength=strength,
            next=chain,
            parent_hyperedge_id=parent,
        )
        # Validation is complete: the following mutations cannot fail.
        self._records.append(record)
        self._pair_heads[pair_id] = new_id
        self._pair_members.setdefault(pair_id, []).append(new_id)
        self._concept_members.setdefault(concept_id, []).append(new_id)
        return record.as_dict()

    def _parent_id(self, value: Any) -> int | None:
        if value is None:
            return None
        if type(value) is not int:
            raise HyperedgeArenaError(
                "parent_hyperedge_id must be an integer or null")
        if value == NULL_HYPEREDGE_ID:
            return None
        if not 1 <= value < len(self._records):
            raise HyperedgeArenaError("parent_hyperedge_id must already exist")
        return value

    # -- stable reads ---------------------------------------------------

    def get(self, hyperedge_id: Any) -> dict | None:
        """Return a copied record, or ``None`` for the null/missing ID."""
        hid = _uint("hyperedge_id", hyperedge_id, U32_MAX, allow_null=True)
        if hid == NULL_HYPEREDGE_ID or hid >= len(self._records):
            return None
        record = self._records[hid]
        assert record is not None
        return record.as_dict()

    def __len__(self) -> int:
        return len(self._records) - 1

    def __contains__(self, hyperedge_id: object) -> bool:
        return (type(hyperedge_id) is int
                and 0 < hyperedge_id < len(self._records))

    def pair_head(self, pair_id: Any, *, clamp: bool = False) -> int:
        """Return the newest hyperedge ID for a pair, or 0 when unbound."""
        if type(clamp) is not bool:
            raise HyperedgeArenaError("clamp must be a boolean")
        pair_id = clamp_pair_id(pair_id) if clamp else _pair_id(pair_id)
        return self._pair_heads.get(pair_id, NULL_HYPEREDGE_ID)

    def incident_hyperedges(self, pair: Any = None, concept: Any = None,
                            limit: int = DEFAULT_LIMIT, *,
                            pair_id: Any = None, concept_id: Any = None) -> dict:
        """Return newest-first memberships for a pair, a concept, or both.

        When both selectors are given the result is their ordered intersection.
        """
        if pair_id is not None:
            if pair is not None:
                raise HyperedgeArenaError("specify pair or pair_id, not both")
            pair = pair_id
        if concept_id is not None:
            if concept is not None:
                raise HyperedgeArenaError(
                    "specify concept or concept_id, not both")
            concept = concept_id
        if pair is None and concept is None:
            raise HyperedgeArenaError("pair or concept selector is required")
        if pair is not None:
            pair = _pair_id(pair)
        if concept is not None:
            concept = _uint("concept_id", concept, U32_MAX)
        limit = _bounded_limit(limit)

        total = 0
        ids: list[int] = []
        if pair is not None and concept is not None:
            source = reversed(self._pair_members.get(pair, ()))
            for hid in source:
                record = self._records[hid]
                assert record is not None
                if record.concept_id == concept:
                    total += 1
                    if len(ids) < limit:
                        ids.append(hid)
        elif pair is not None:
            source = self._pair_members.get(pair, ())
            total = len(source)
            ids = list(reversed(source[-limit:]))
        else:
            source = self._concept_members.get(concept, ())
            total = len(source)
            ids = list(reversed(source[-limit:]))

        return {
            "schema": SCHEMA,
            "version": VERSION,
            "pair_id": pair,
            "concept_id": concept,
            "limit": limit,
            "total": total,
            "count": len(ids),
            "truncated": total > len(ids),
            "ids": ids,
            "records": [self._records[hid].as_dict() for hid in ids],
        }

    def traverse(self, start: Any, max_depth: int = DEFAULT_MAX_DEPTH,
                 limit: int = DEFAULT_LIMIT) -> dict:
        """Follow the pair-membership ``next`` chain within hard bounds.

        ``max_depth`` counts links followed from ``start``; depth zero returns
        only the start record.  A null or missing start yields an empty page.
        """
        start = _uint("start", start, U32_MAX, allow_null=True)
        if type(max_depth) is not int or not 0 <= max_depth <= MAX_DEPTH:
            raise HyperedgeArenaError(
                f"max_depth must be an integer in 0..{MAX_DEPTH}")
        limit = _bounded_limit(limit)

        ids: list[int] = []
        current = start
        if start == NULL_HYPEREDGE_ID:
            terminated = "null"
        elif start >= len(self._records):
            terminated = "missing"
        else:
            terminated = "end"
        truncated = False
        while current != NULL_HYPEREDGE_ID and current < len(self._records):
            record = self._records[current]
            assert record is not None
            if len(ids) >= limit:
                truncated = True
                terminated = "limit"
                break
            ids.append(current)
            if len(ids) - 1 >= max_depth:
                if record.next != NULL_HYPEREDGE_ID:
                    truncated = True
                    terminated = "depth"
                else:
                    terminated = "end"
                break
            current = record.next

        return {
            "schema": SCHEMA,
            "version": VERSION,
            "start": start,
            "max_depth": max_depth,
            "limit": limit,
            "count": len(ids),
            "depth_reached": max(0, len(ids) - 1),
            "truncated": truncated,
            "terminated": terminated,
            "ids": ids,
            "records": [self._records[hid].as_dict() for hid in ids],
        }

    # -- serialization --------------------------------------------------

    @property
    def digest(self) -> str:
        return _records_digest(self._record_dicts())

    def _record_dicts(self) -> list[dict]:
        return [record.as_dict() for record in self._records[1:]
                if record is not None]

    def to_dict(self) -> dict:
        """Serialize append history plus reconstructed membership views."""
        records = self._record_dicts()
        return {
            "schema": SCHEMA,
            "version": VERSION,
            "digest": _records_digest(records),
            "record_count": len(records),
            "next_id": len(records) + 1,
            "records": records,
            "pair_heads": {str(k): v for k, v in sorted(
                self._pair_heads.items())},
            "concept_incidence": {str(k): list(v) for k, v in sorted(
                self._concept_members.items())},
        }

    def to_json(self, indent: int | None = None) -> str:
        if indent is not None and (type(indent) is not int or indent < 0):
            raise HyperedgeArenaError("indent must be a nonnegative integer")
        if indent is None:
            return _canonical_json(self.to_dict()).decode("utf-8")
        return json.dumps(self.to_dict(), sort_keys=True, indent=indent,
                          allow_nan=False)

    @classmethod
    def from_dict(cls, data: Mapping | str, *,
                  verify_digest: bool = True) -> "MirrorHyperedgeArena":
        """Restore and fully revalidate a serialized append history."""
        if type(verify_digest) is not bool:
            raise HyperedgeArenaError("verify_digest must be a boolean")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError as exc:
                raise HyperedgeArenaError("invalid arena JSON") from exc
        if not isinstance(data, Mapping):
            raise HyperedgeArenaError("arena serialization must be an object")
        if data.get("schema") != SCHEMA:
            raise HyperedgeArenaError("unsupported hyperedge arena schema")
        if type(data.get("version")) is not int or data["version"] != VERSION:
            raise HyperedgeArenaError("unsupported hyperedge arena version")
        raw_records = data.get("records")
        if type(raw_records) is not list:
            raise HyperedgeArenaError("records must be a list")

        normalized = [_normalize_serialized_record(raw, index + 1)
                      for index, raw in enumerate(raw_records)]
        digest = _records_digest(normalized)
        if verify_digest:
            supplied = _digest(data.get("digest"))
            if supplied != digest:
                raise HyperedgeArenaError("arena digest mismatch")
        if "record_count" in data and (
                type(data["record_count"]) is not int
                or data["record_count"] != len(normalized)):
            raise HyperedgeArenaError("record_count does not match records")
        if "next_id" in data and (
                type(data["next_id"]) is not int
                or data["next_id"] != len(normalized) + 1):
            raise HyperedgeArenaError("next_id does not match records")

        arena = cls()
        for raw in normalized:
            expected_next = arena._pair_heads.get(
                raw["pair_id"], NULL_HYPEREDGE_ID)
            if raw["next"] != expected_next:
                raise HyperedgeArenaError(
                    "pair membership chain does not match append history")
            parent = raw["parent_hyperedge_id"]
            if parent is not None and not 1 <= parent < len(arena._records):
                raise HyperedgeArenaError("parent hyperedge is not earlier")
            record = HyperedgeRecord(**raw)
            arena._records.append(record)
            arena._pair_heads[record.pair_id] = record.id
            arena._pair_members.setdefault(
                record.pair_id, []).append(record.id)
            arena._concept_members.setdefault(
                record.concept_id, []).append(record.id)

        _verify_serialized_view(arena, data, "pair_heads")
        _verify_serialized_view(arena, data, "concept_incidence")
        return arena

    @classmethod
    def from_json(cls, text: str, *,
                  verify_digest: bool = True) -> "MirrorHyperedgeArena":
        return cls.from_dict(text, verify_digest=verify_digest)

    def status(self) -> dict:
        return {
            "schema": SCHEMA,
            "version": VERSION,
            "digest": self.digest,
            "record_count": len(self),
            "next_id": len(self) + 1,
            "pair_count": len(self._pair_heads),
            "concept_count": len(self._concept_members),
            "membership_count": sum(
                len(ids) for ids in self._pair_members.values()),
            "append_only": True,
            "host_only": True,
            "raw_pointers_exposed": False,
            "sqlite": False,
            "host_math": False,
            "native_execution": False,
            "canonical_merge": False,
            "max_depth": MAX_DEPTH,
            "max_limit": MAX_LIMIT,
        }


# Short alias for callers that do not need the "Mirror" prefix.
HyperedgeArena = MirrorHyperedgeArena


def _bounded_limit(value: Any) -> int:
    if type(value) is not int or not 1 <= value <= MAX_LIMIT:
        raise HyperedgeArenaError(
            f"limit must be an integer in 1..{MAX_LIMIT}")
    return value


def _normalize_serialized_record(raw: Any, expected_id: int) -> dict:
    if not isinstance(raw, Mapping):
        raise HyperedgeArenaError("each record must be an object")
    keys = frozenset(raw)
    if not keys <= _RECORD_KEYS:
        raise HyperedgeArenaError("record has unknown fields")
    missing = _RECORD_KEYS - keys - {"parent_hyperedge_id"}
    if missing:
        raise HyperedgeArenaError(
            "record is missing fields: " + ", ".join(sorted(missing)))
    if type(raw.get("id")) is not int or raw["id"] != expected_id:
        raise HyperedgeArenaError("record IDs must be stable and contiguous")
    pair_id = _pair_id(raw.get("pair_id"))
    concept_id = _uint("concept_id", raw.get("concept_id"), U32_MAX)
    relation_type = _uint(
        "relation_type", raw.get("relation_type"), U32_MAX)
    strength = _f32(raw.get("strength"))
    next_id = _uint("next", raw.get("next"), U32_MAX, allow_null=True)
    parent = raw.get("parent_hyperedge_id")
    if parent is not None and type(parent) is not int:
        raise HyperedgeArenaError(
            "parent_hyperedge_id must be an earlier non-null ID")
    if parent == NULL_HYPEREDGE_ID:
        parent = None
    if parent is not None and not 1 <= parent < expected_id:
        raise HyperedgeArenaError(
            "parent_hyperedge_id must be an earlier non-null ID")
    return {
        "id": expected_id,
        "pair_id": pair_id,
        "concept_id": concept_id,
        "relation_type": relation_type,
        "strength": strength,
        "next": next_id,
        "parent_hyperedge_id": parent,
    }


def _verify_serialized_view(arena: MirrorHyperedgeArena, data: Mapping,
                            key: str) -> None:
    if key not in data:
        return
    view = data[key]
    if not isinstance(view, Mapping):
        raise HyperedgeArenaError(f"{key} must be an object")
    parsed: dict[int, Any] = {}
    for raw_key, value in view.items():
        if type(raw_key) is int:
            parsed_key = raw_key
        elif (type(raw_key) is str and raw_key.isdigit()
              and str(int(raw_key)) == raw_key):
            parsed_key = int(raw_key)
        else:
            raise HyperedgeArenaError(f"{key} keys must be integer IDs")
        if parsed_key in parsed:
            raise HyperedgeArenaError(f"duplicate {key} key")
        if key == "pair_heads":
            if type(value) is not int:
                raise HyperedgeArenaError(
                    "pair_heads values must be integer IDs")
        elif (not isinstance(value, list)
              or any(type(hid) is not int for hid in value)):
            raise HyperedgeArenaError(
                "concept_incidence values must be ID lists")
        parsed[parsed_key] = value
    if key == "pair_heads":
        expected = arena._pair_heads
    else:
        expected = {k: list(v) for k, v in arena._concept_members.items()}
    if parsed != expected:
        raise HyperedgeArenaError(f"{key} does not match append history")
