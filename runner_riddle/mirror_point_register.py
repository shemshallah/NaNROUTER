"""Resident mathematical mirror-point topology and versioned leaf routing.

A microtable for HW0:MPn is calculated from a fixed rank/unrank transform:
two ordered 16-bit addresses -> one canonical pair cell -> optional MC0DB
typed leaf binding. The 256 palindrome fixed points are separate head records.

No math execution occurs here: NMP preflight and native MTH remain exclusive
execution authorities. No 8 MiB chart copy or second persistence store.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import hashlib
import json
import re
import sqlite3
import struct
from typing import Any

from .address import HeadSelector, MirrorPairSelector, ObjectSelector, parse_address
from .math_auth import READ, WRITE
from .math_store import MathReferenceError, MathStore, StaleGenerationError

HEADS = 256
NANNET_HEAD = 0
FIXED_POINTS = HEADS
PAIR_COUNT = HEADS * (HEADS - 1) // 2
CANONICAL_CELLS = FIXED_POINTS + PAIR_COUNT
RAW_ADDRESSES = HEADS * HEADS
LOOKUP_BYTES = RAW_ADDRESSES * 2
INVERSE_BYTES = CANONICAL_CELLS * 2
PREFIX = "palpair:v1:"
SCHEMA = "nanrouter.mirror-point-register/1"
MASTER_SCHEMA = "nanrouter.mirror-master-scratch/1"
MAX_PAGE = 100
_HEX = re.compile(r"[0-9a-f]{64}\Z")


class MirrorPointError(ValueError):
    pass


def _point(n: int) -> int:
    if type(n) is not int or not 0 <= n < HEADS:
        raise MirrorPointError("head must be a number 0..255")
    return n


def _ordinal(n: int) -> int:
    if type(n) is not int or not 0 <= n < PAIR_COUNT:
        raise MirrorPointError("MP index must be 0..32639")
    return n


def _digest(value: str) -> str:
    if type(value) is not str or _HEX.fullmatch(value) is None:
        raise MirrorPointError("expected lowercase SHA256")
    return value


def reverse8(n: int) -> int:
    n = _point(n)
    n = (n >> 4) | ((n & 15) << 4)
    n = ((n & 0xCC) >> 2) | ((n & 0x33) << 2)
    return ((n & 0xAA) >> 1) | ((n & 0x55) << 1)


def reverse16(n: int) -> int:
    if type(n) is not int or not 0 <= n <= 65535:
        raise MirrorPointError("16-bit address required")
    return (reverse8(n & 255) << 8) | reverse8(n >> 8)


def address(a: int, b: int) -> int:
    return (_point(a) << 8) | reverse8(_point(b))


def pair_number(a: int, b: int) -> int:
    a, b = _point(a), _point(b)
    if a == b:
        raise MirrorPointError("palindromic head is not an MP leaf")
    if a > b:
        a, b = b, a
    return a * (2 * HEADS - a - 1) // 2 + b - a - 1


_START = tuple(a * (2 * HEADS - a - 1) // 2 for a in range(HEADS))


def pair_heads(mp: int) -> tuple[int, int]:
    mp = _ordinal(mp)
    a = bisect_right(_START, mp) - 1
    return a, a + 1 + mp - _START[a]


def _materialize() -> tuple[bytes, bytes]:
    raw_to_cell = bytearray(LOOKUP_BYTES)
    cell_to_raw = bytearray(INVERSE_BYTES)
    # The canonical array order deliberately equals Chart8MiB.genesis:
    # 256 fixed-point heads first, followed by a<b in lexicographic order.
    for a in range(HEADS):
        fixed = address(a, a)
        struct.pack_into("<H", raw_to_cell, 2 * fixed, a)
        struct.pack_into("<H", cell_to_raw, 2 * a, fixed)
    for a in range(HEADS):
        for b in range(a + 1, HEADS):
            n = pair_number(a, b)
            cell = FIXED_POINTS + n
            forward, mirror = address(a, b), address(b, a)
            struct.pack_into("<H", raw_to_cell, 2 * forward, cell)
            struct.pack_into("<H", raw_to_cell, 2 * mirror, cell)
            struct.pack_into("<H", cell_to_raw, 2 * cell, forward)
    return bytes(raw_to_cell), bytes(cell_to_raw)


# Created once per Python process, never copied per user or route.
RAW_TO_CELL, CELL_TO_RAW = _materialize()
TOPOLOGY_DIGEST = hashlib.sha256(
    b"nanrouter.mirror-point-register/1\0" + RAW_TO_CELL + CELL_TO_RAW
).hexdigest()


def mapping_key(mp: int) -> str:
    return f"{PREFIX}{_ordinal(mp):05d}"


@dataclass(frozen=True)
class Microtable:
    """A fixed head or MP microtable: dynamic leaf link is separate."""
    kind: str
    ordinal: int
    a: int
    b: int
    forward_address: int
    mirror_address: int
    canonical_cell: int
    canonical_address: int

    def as_dict(self, source: int | None = None, target: int | None = None) -> dict:
        return {
            "kind": self.kind,
            "route": f"HW0:{self.a}" if self.kind == "head" else f"HW0:MP{self.ordinal}",
            "ordinal": self.ordinal,
            "heads": [self.a] if self.kind == "head" else [self.a, self.b],
            "writable_heads": sorted({h for h in (self.a, self.b)
                                      if h != NANNET_HEAD}),
            "addresses": [self.forward_address, self.mirror_address],
            "canonical_address": self.canonical_address,
            "canonical_cell": self.canonical_cell,
            "orientation": ("fixed" if self.kind == "head"
                            else "forward" if source is None or source < target
                            else "mirror"),
            "topology_sha256": TOPOLOGY_DIGEST,
        }


class MirrorRegister:
    """Always-resident 128 KiB forward map + 65,792 byte inverse map."""

    @staticmethod
    def head(h: int) -> Microtable:
        h = _point(h)
        raw = address(h, h)
        return Microtable("head", h, h, h, raw, raw, h, raw)

    @staticmethod
    def mp(n: int) -> Microtable:
        n = _ordinal(n)
        a, b = pair_heads(n)
        forward = address(a, b)
        mirror = address(b, a)
        cell = struct.unpack_from("<H", RAW_TO_CELL, forward * 2)[0]
        return Microtable("mp", n, a, b, forward, mirror, cell, forward)

    @classmethod
    def from_heads(cls, a: int, b: int) -> dict:
        a, b = _point(a), _point(b)
        table = cls.head(a) if a == b else cls.mp(pair_number(a, b))
        return table.as_dict(a, b)

    @classmethod
    def from_raw(cls, raw: int) -> dict:
        if type(raw) is not int or not 0 <= raw < RAW_ADDRESSES:
            raise MirrorPointError("16-bit raw address required")
        a, b = raw >> 8, reverse8(raw & 255)
        result = cls.from_heads(a, b)
        assert result["canonical_cell"] == struct.unpack_from("<H", RAW_TO_CELL, 2 * raw)[0]
        return result

    @staticmethod
    def status() -> dict:
        return {"schema": SCHEMA, "heads": FIXED_POINTS,
                "mirror_points": PAIR_COUNT, "canonical_cells": CANONICAL_CELLS,
                "raw_addresses": RAW_ADDRESSES, "map_bytes": LOOKUP_BYTES,
                "inverse_bytes": INVERSE_BYTES, "topology_sha256": TOPOLOGY_DIGEST,
                "resident": True, "mutable": False, "nannet0_writable": False}


class MirrorLeafDirectory:
    """One MC0DB many-to-one MP -> immutable leaf-version index.

    Existing MathStore.math_mapping enforces UNIQUE(object_type, object_id):
    using it for individual MPs would forbid multiple MPs sharing a leaf.
    This additive MC0DB table instead keys *the link* by MP, not the leaf,
    and retains immutable binding history. No second SQLite file is created.
    """

    _SCHEMA = """
        CREATE TABLE IF NOT EXISTS nan_mp_binding (
            mp INTEGER PRIMARY KEY CHECK(mp BETWEEN 0 AND 32639),
            leaf_id TEXT NOT NULL,
            leaf_version INTEGER NOT NULL CHECK(leaf_version >= 1),
            leaf_digest TEXT NOT NULL,
            generation INTEGER NOT NULL CHECK(generation >= 1),
            source_head INTEGER NOT NULL CHECK(source_head BETWEEN 1 AND 255),
            tick INTEGER NOT NULL CHECK(tick >= 0),
            status TEXT NOT NULL DEFAULT 'active'
        );
        CREATE INDEX IF NOT EXISTS nan_mp_binding_leaf
            ON nan_mp_binding(leaf_id, leaf_version);
        CREATE TABLE IF NOT EXISTS nan_mp_binding_history (
            mp INTEGER NOT NULL CHECK(mp BETWEEN 0 AND 32639),
            generation INTEGER NOT NULL CHECK(generation >= 1),
            leaf_id TEXT NOT NULL,
            leaf_version INTEGER NOT NULL CHECK(leaf_version >= 1),
            leaf_digest TEXT NOT NULL,
            source_head INTEGER NOT NULL CHECK(source_head BETWEEN 1 AND 255),
            tick INTEGER NOT NULL CHECK(tick >= 0),
            PRIMARY KEY(mp, generation)
        );
    """

    def __init__(self, store: MathStore):
        if not isinstance(store, MathStore):
            raise MirrorPointError("MathStore required: no parallel JSON store")
        self.store = store

    def _rows(self, sql: str, params=()):
        with self.store._connect(self.store.mc0_path) as db:
            if db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='nan_mp_binding'"
            ).fetchone() is None:
                return None
            return db.execute(sql, params).fetchall()

    def resolve_mp(self, n: int) -> dict:
        n = _ordinal(n)
        self.store._authorize(READ, "mirror_pair", mapping_key(n))
        record = MirrorRegister.mp(n).as_dict()
        rows = self._rows("SELECT * FROM nan_mp_binding WHERE mp=?", (n,))
        if not rows:
            record.update({"bound": False, "leaf": None, "status": "unbound"})
            return record
        pointer = rows[0]
        record.update({"bound": True, "status": pointer["status"],
                       "leaf": {
                           "id": pointer["leaf_id"],
                           "version": int(pointer["leaf_version"]),
                           "digest": pointer["leaf_digest"],
                           "generation": int(pointer["generation"]),
                           "storage_tier": "BS0DB",
                       }, "mathematical_validity": None})
        return record

    def resolve_address(self, text: str) -> dict:
        parsed = parse_address(text)
        selectors = parsed.mirror_pair_selectors
        if len(selectors) != 1:
            raise MirrorPointError("exactly one HW0:MP selector is required")
        mp = selectors[0]
        if mp.is_range:
            return {"schema": SCHEMA, "route": parsed.canonical_with_selectors(),
                    "first_mp": mp.start, "last_mp": mp.end,
                    "status": "range_requires_bounded_pagination",
                    "bound": False, "topology_sha256": TOPOLOGY_DIGEST}
        record = self.resolve_mp(mp.start)
        head_selectors = parsed.head_selectors
        # Head-prefix is a directional ACL, not a second pair cell.
        if len(head_selectors) > 1 or (head_selectors and
            (head_selectors[0].namespace != 0 or
             len(head_selectors[0].heads) != 1 or
             head_selectors[0].heads[0] not in record["writable_heads"])):
            raise MirrorPointError("head selector is not an endpoint of this mirror pair")
        if parsed.object_selectors:
            raise MirrorPointError("MP leaf resolves through MC0DB, not route text")
        record["route_address"] = parsed.canonical_with_selectors()
        record["selected_head"] = head_selectors[0].heads[0] if head_selectors else None
        return record

    def bind(self, mp: int, *, source_head: int, leaf_id: str,
             leaf_version: int, leaf_digest: str, expected_version: int,
             expected_generation: int, tick: int = 0) -> dict:
        table = MirrorRegister.mp(mp)
        head = _point(source_head)
        if head == 0 or head not in (table.a, table.b):
            raise MirrorPointError("only a real endpoint head may propose a leaf mapping")
        if (type(expected_version) is not int or expected_version < 0
                or type(expected_generation) is not int or expected_generation < 0):
            raise MirrorPointError("mapping CAS version and generation must be explicit")
        if type(tick) is not int or tick < 0:
            raise MirrorPointError("tick must be nonnegative")
        if type(leaf_version) is not int or leaf_version < 1:
            raise MirrorPointError("leaf version must be positive")
        if type(leaf_id) is not str or not leaf_id or leaf_id.startswith("nan://"):
            raise MirrorPointError("a typed MathStore leaf ID is required")
        _digest(leaf_digest)
        self.store._authorize(WRITE, "mirror_pair", mapping_key(mp))
        # Leaf versions are immutable, so this check binds an existing,
        # structurally sound leaf but does NOT grant mathematical validity.
        leaf = self.store.get_leaf(leaf_id, leaf_version)
        if leaf.digest() != leaf_digest:
            raise MirrorPointError("leaf identity/version digest mismatch")
        with self.store._write(self.store.mc0_path) as db:
            # DDL is scoped to MC0DB; existing MathStore tables stay intact.
            for statement in self._SCHEMA.split(";"):
                if statement.strip():
                    db.execute(statement)
            existing = db.execute(
                "SELECT * FROM nan_mp_binding WHERE mp=?", (mp,)
            ).fetchone()
            if existing is None:
                if expected_version != 0 or expected_generation != 0:
                    raise StaleGenerationError("MP binding creation requires CAS (0,0)")
                gen = 1
                db.execute(
                    "INSERT INTO nan_mp_binding "
                    "(mp,leaf_id,leaf_version,leaf_digest,generation,source_head,tick) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (mp,leaf_id,leaf_version,leaf_digest,gen,head,tick))
            else:
                if (expected_version != existing["leaf_version"]
                        or expected_generation != existing["generation"]):
                    raise StaleGenerationError("stale MP binding version/generation")
                if existing["leaf_id"] == leaf_id and (
                        existing["leaf_version"] == leaf_version
                        and existing["leaf_digest"] == leaf_digest):
                    gen = int(existing["generation"])
                else:
                    gen = int(existing["generation"]) + 1
                    db.execute(
                        "UPDATE nan_mp_binding SET leaf_id=?,leaf_version=?,"
                        "leaf_digest=?,generation=?,source_head=?,tick=? WHERE mp=?",
                        (leaf_id,leaf_version,leaf_digest,gen,head,tick,mp))
            # Each distinct generation is immutable, and revisions are
            # recoverable without rewriting a physical NaN chart cell.
            db.execute(
                "INSERT OR IGNORE INTO nan_mp_binding_history "
                "(mp,generation,leaf_id,leaf_version,leaf_digest,source_head,tick) "
                "VALUES (?,?,?,?,?,?,?)",
                (mp,gen,leaf_id,leaf_version,leaf_digest,head,tick))
        return {"microtable": table.as_dict(),
                "mapping": {"mp":mp, "object_type":"leaf", "object_id":leaf_id,
                            "current_version":leaf_version,"target_digest":leaf_digest,
                            "generation":gen,"storage_tier":"BS0DB","status":"active"},
                "native_head_mutated":False,
                "math_preflight_authorized":False,
                "mathematical_truth_promoted":False}

    def master_page(self, *, parent_root_sha256: str,
                    chart_generation: int, offset: int = 0, limit: int = MAX_PAGE) -> dict:
        """Bounded master-register projection, never a signed execution receipt."""
        _digest(parent_root_sha256)
        if (type(chart_generation) is not int or chart_generation < 0
                or type(offset) is not int or offset < 0
                or type(limit) is not int or not 1 <= limit <= MAX_PAGE):
            raise MirrorPointError("invalid snapshot generation or page bounds")
        self.store._authorize(READ, "mirror_pair", "projection")
        rows = self._rows("SELECT * FROM nan_mp_binding ORDER BY mp")
        if rows is None:
            rows = []
        counts = [0] * HEADS
        for row in rows:
            a,b = pair_heads(int(row["mp"]))
            if a:
                counts[a] += 1
            if b:
                counts[b] += 1
        items = []
        for row in rows[offset:offset+limit]:
            n = int(row["mp"])
            table = MirrorRegister.mp(n)
            items.append({
                "mp":n,"cell":table.canonical_cell,
                "addresses":[table.forward_address,table.mirror_address],
                "heads":[table.a,table.b],
                "leaf_id":row["leaf_id"], "leaf_version":int(row["leaf_version"]),
                "leaf_digest":row["leaf_digest"],
                "mapping_generation":int(row["generation"]),
            })
        page = {"schema":MASTER_SCHEMA,"topology_sha256":TOPOLOGY_DIGEST,
                "parent_root_sha256":parent_root_sha256,
                "chart_generation":chart_generation,
                "total_bound":len(rows),"offset":offset,
                "next_offset":offset+len(items) if offset+len(items)<len(rows) else None,
                "head_counts":counts,"entries":items}
        raw=json.dumps(page,sort_keys=True,separators=(",",":")).encode()
        page["page_sha256"]=hashlib.sha256(raw).hexdigest()
        page["native_execution_verified"]=False
        page["master_register_projection_only"]=True
        return page
