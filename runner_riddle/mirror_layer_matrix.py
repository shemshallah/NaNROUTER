"""Bounded L0-L9 relation matrix over the one NaNROUTER mirror topology.

Structural head<->mirror adjacency is algebraic and immutable. Only *sparse*
learned relation candidates are stored in existing MC0DB, with immutable
revision history, canonical parent-root binding and optimistic CAS. This
does NOT implement an MTH kernel, create a second database, prove a theorem,
or authenticate the caller; the external router/lease/dispatch chain owns
those actions. Each edge here is evidence, never automatic model truth.
"""
from __future__ import annotations

from collections import deque
import hashlib
import json
import re
from typing import Any

from .address import parse_address
from .math_auth import READ, WRITE
from .math_store import MathStore, StaleGenerationError
from .mirror_point_register import (
    HEADS, NANNET_HEAD, PAIR_COUNT, TOPOLOGY_DIGEST, MirrorLeafDirectory,
    MirrorRegister, pair_heads, pair_number,
)

SCHEMA = "nanrouter.mirror-layer-matrix/1"
ROOT_ROUTE = "nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0"
MAX_RESULTS = 64
MAX_DEPTH = 4
MAX_VISITED = 128
RELATIONS = frozenset({
    "aligned", "cooccurs", "contradicts", "defines", "entails", "related",
    "part_of", "transforms", "abstracts_to", "refines",
})
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_SCHEMA_SQL = (
    """CREATE TABLE IF NOT EXISTS nan_layer_relation (
        edge_id TEXT PRIMARY KEY,
        parent_root TEXT NOT NULL,
        topology_digest TEXT NOT NULL,
        source_kind TEXT NOT NULL CHECK(source_kind IN ('head','mp')),
        source_id INTEGER NOT NULL,
        source_layer INTEGER NOT NULL CHECK(source_layer BETWEEN 0 AND 9),
        target_kind TEXT NOT NULL CHECK(target_kind IN ('head','mp')),
        target_id INTEGER NOT NULL,
        target_layer INTEGER NOT NULL CHECK(target_layer BETWEEN 0 AND 9),
        relation TEXT NOT NULL,
        polarity INTEGER NOT NULL CHECK(polarity BETWEEN -1 AND 1),
        strength_q16 INTEGER NOT NULL CHECK(strength_q16 BETWEEN 0 AND 65536),
        evidence_sha256 TEXT NOT NULL,
        origin_head INTEGER NOT NULL CHECK(origin_head BETWEEN 1 AND 255),
        generation INTEGER NOT NULL CHECK(generation >= 1),
        tick INTEGER NOT NULL CHECK(tick >= 0)
    )""",
    """CREATE INDEX IF NOT EXISTS nan_layer_relation_source
       ON nan_layer_relation(parent_root,source_kind,source_id,source_layer,edge_id)""",
    """CREATE TABLE IF NOT EXISTS nan_layer_relation_history (
        edge_id TEXT NOT NULL,
        generation INTEGER NOT NULL CHECK(generation >= 1),
        polarity INTEGER NOT NULL,
        strength_q16 INTEGER NOT NULL,
        evidence_sha256 TEXT NOT NULL,
        origin_head INTEGER NOT NULL,
        tick INTEGER NOT NULL,
        PRIMARY KEY(edge_id,generation)
    )""",
)


class LayerMatrixError(ValueError):
    pass


def _int(name: str, value: Any, lo: int, hi: int) -> int:
    if type(value) is not int or not lo <= value <= hi:
        raise LayerMatrixError(f"{name} must be an integer in {lo}..{hi}")
    return value


def _digest(name: str, value: Any) -> str:
    if type(value) is not str or _HEX.fullmatch(value) is None:
        raise LayerMatrixError(f"{name} must be lowercase SHA-256")
    return value


def _node(kind: str, ordinal: int) -> tuple[str, int]:
    if kind == "head":
        return kind, _int("head", ordinal, 0, HEADS - 1)
    if kind == "mp":
        return kind, _int("MP", ordinal, 0, PAIR_COUNT - 1)
    raise LayerMatrixError("node kind must be head or mp")


def _validate_levels(level: int, target_level: int, relation: str):
    _int("source layer", level, 0, 9)
    _int("target layer", target_level, 0, 9)
    if relation not in RELATIONS:
        raise LayerMatrixError("unknown typed relationship")
    if relation == "abstracts_to":
        if target_level != level + 1:
            raise LayerMatrixError("abstracts_to must move upward exactly one L layer")
    elif relation == "refines":
        if target_level != level - 1:
            raise LayerMatrixError("refines must move downward exactly one L layer")
    elif target_level != level:
        raise LayerMatrixError("same-layer relationship cannot bypass adjacent abstraction")


def _edge_id(root: str, src: tuple[str, int], src_layer: int,
             dst: tuple[str, int], dst_layer: int, relation: str) -> str:
    key = [SCHEMA, root, TOPOLOGY_DIGEST, src[0], src[1], src_layer,
           dst[0], dst[1], dst_layer, relation]
    return hashlib.sha256(json.dumps(key, separators=(",", ":")).encode()).hexdigest()


def _row(row):
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


class NanLayerMatrix:
    """Sparsely learned L0-L9 typed edges, never a duplicate physical chart."""

    def __init__(self, store: MathStore, *, canonical_parent_sha256: str):
        if not isinstance(store, MathStore):
            raise LayerMatrixError("existing MC0DB MathStore required")
        self.store = store
        self.parent = _digest("canonical parent", canonical_parent_sha256)
        self.leaves = MirrorLeafDirectory(store)

    def _read(self, sql: str, params=()):
        with self.store._connect(self.store.mc0_path) as db:
            if db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='nan_layer_relation'"
            ).fetchone() is None:
                return []
            return [_row(row) for row in db.execute(sql, params).fetchall()]

    def propose(self, *, source_kind: str, source_id: int, source_layer: int,
                target_kind: str, target_id: int, target_layer: int,
                relation: str, polarity: int, strength_q16: int,
                evidence_sha256: str, source_head: int,
                expected_generation: int, tick: int = 0) -> dict:
        """Record one provisional weighted relation; no MTH/approval occurs."""
        src, dst = _node(source_kind, source_id), _node(target_kind, target_id)
        _validate_levels(source_layer, target_layer, relation)
        _int("polarity", polarity, -1, 1)
        _int("strength_q16", strength_q16, 0, 65536)
        _int("source head", source_head, 1, 255)
        _int("generation", expected_generation, 0, 2147483647)
        _int("tick", tick, 0, 9223372036854775807)
        _digest("evidence", evidence_sha256)
        # Only a real originating head may propose its own head or MP edge.
        if src[0] == "head" and src[1] != source_head:
            raise LayerMatrixError("source head is not the origin node")
        if src[0] == "mp" and source_head not in pair_heads(src[1]):
            raise LayerMatrixError("source head is not an MP endpoint")
        if dst == ("head", NANNET_HEAD):
            raise LayerMatrixError("NANNET0 cannot be a learned destination")
        edge_id = _edge_id(self.parent, src, source_layer,
                           dst, target_layer, relation)
        self.store._authorize(WRITE, "mirror_layer", edge_id)
        with self.store._write(self.store.mc0_path) as db:
            for ddl in _SCHEMA_SQL:
                db.execute(ddl)
            old = db.execute(
                "SELECT generation,polarity,strength_q16,evidence_sha256 "
                "FROM nan_layer_relation WHERE edge_id=?", (edge_id,)
            ).fetchone()
            if old is None:
                if expected_generation != 0:
                    raise StaleGenerationError("new relation must expect generation zero")
                generation = 1
                db.execute(
                    "INSERT INTO nan_layer_relation "
                    "(edge_id,parent_root,topology_digest,source_kind,source_id,"
                    "source_layer,target_kind,target_id,target_layer,relation,"
                    "polarity,strength_q16,evidence_sha256,origin_head,generation,tick)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (edge_id, self.parent, TOPOLOGY_DIGEST, src[0], src[1],
                     source_layer, dst[0], dst[1], target_layer, relation,
                     polarity, strength_q16, evidence_sha256, source_head,
                     generation, tick),
                )
            else:
                if old["generation"] != expected_generation:
                    raise StaleGenerationError("stale L0-L9 relation generation")
                if (old["polarity"], old["strength_q16"],
                    old["evidence_sha256"]) == (
                        polarity, strength_q16, evidence_sha256):
                    generation = int(old["generation"])
                else:
                    generation = int(old["generation"]) + 1
                    db.execute(
                        "UPDATE nan_layer_relation SET polarity=?,strength_q16=?,"
                        "evidence_sha256=?,origin_head=?,generation=?,tick=?"
                        " WHERE edge_id=?",
                        (polarity, strength_q16, evidence_sha256, source_head,
                         generation, tick, edge_id),
                    )
            db.execute(
                "INSERT OR IGNORE INTO nan_layer_relation_history "
                "(edge_id,generation,polarity,strength_q16,evidence_sha256,"
                "origin_head,tick) VALUES (?,?,?,?,?,?,?)",
                (edge_id, generation, polarity, strength_q16,
                 evidence_sha256, source_head, tick),
            )
        return {"schema": SCHEMA, "edge_id": edge_id,
                "generation": generation, "candidate_recorded": True,
                "native_execution_verified": False, "math_rule_promoted": False,
                "canonical_training_committed": False}

    def neighbors(self, *, kind: str, ordinal: int, layer: int,
                  limit: int = 32, offset: int = 0) -> dict:
        """Paginated directed matrix row for one concrete head/MP at one layer."""
        node = _node(kind, ordinal)
        _int("layer", layer, 0, 9)
        _int("limit", limit, 1, MAX_RESULTS)
        _int("offset", offset, 0, 1_000_000)
        self.store._authorize(READ, "mirror_layer", f"{node[0]}:{node[1]}:L{layer}")
        rows = self._read(
            "SELECT * FROM nan_layer_relation WHERE parent_root=? AND "
            "topology_digest=? AND source_kind=? AND source_id=? AND "
            "source_layer=? ORDER BY edge_id LIMIT ? OFFSET ?",
            (self.parent, TOPOLOGY_DIGEST, node[0], node[1],
             layer, limit + 1, offset),
        )
        more = len(rows) > limit
        rows = rows[:limit]
        return {"schema": SCHEMA, "node": {"kind": node[0], "id": node[1],
                                          "layer": layer},
                "relations": rows, "next_offset": offset + len(rows) if more else None,
                "candidate_only": True, "topology_sha256": TOPOLOGY_DIGEST,
                "parent_root_sha256": self.parent}

    def structural(self, *, kind: str, ordinal: int,
                   offset: int = 0, limit: int = 32) -> dict:
        """Implicit full head↔MP incidence, never 8M materialized edge rows."""
        node = _node(kind, ordinal)
        _int("offset", offset, 0, 65536)
        _int("limit", limit, 1, MAX_RESULTS)
        if node[0] == "mp":
            ids = list(pair_heads(node[1]))
            entries = [{"kind":"head","id":h} for h in ids]
        else:
            entries = [{"kind":"mp", "id":pair_number(node[1], b)}
                       for b in range(HEADS) if b != node[1]]
        self.store._authorize(READ, "mirror_topology", f"{kind}:{ordinal}")
        return {"schema": SCHEMA, "node": {"kind": kind, "id": ordinal},
                "topology_sha256": TOPOLOGY_DIGEST,
                "total": len(entries), "neighbors": entries[offset:offset+limit],
                "next_offset": min(offset+limit, len(entries))
                               if offset+limit < len(entries) else None,
                "generated_not_stored": True}

    def route(self, uri: str, *, limit: int = 32) -> dict:
        """One nan:// HW0 head/MP/Layer path to physical and relational views."""
        parsed = parse_address(uri)
        if parsed.root != ROOT_ROUTE:
            raise LayerMatrixError("route root does not match this universe")
        if len(parsed.layer_selectors) > 1 or parsed.object_selectors:
            raise LayerMatrixError("typed leaf context is separate from nan:// route")
        level = parsed.layer_selectors[0].level if parsed.layer_selectors else 0
        if len(parsed.mirror_pair_selectors) == 1:
            mp = parsed.mirror_pair_selectors[0]
            if mp.is_range:
                raise LayerMatrixError("MP ranges must be queried with pagination")
            record = self.leaves.resolve_address(uri)
            node = ("mp", mp.start)
        elif len(parsed.head_selectors) == 1:
            head = parsed.head_selectors[0]
            if head.namespace != 0 or len(head.heads) != 1:
                raise LayerMatrixError("single HW0 head required")
            node = ("head", head.heads[0])
            record = MirrorRegister.head(node[1]).as_dict()
        else:
            raise LayerMatrixError("route needs one HW0 head or MP")
        return {"schema": SCHEMA, "route": parsed.canonical_with_selectors(),
                "coordinate": record,
                "resolution": f"L{level}",
                "structural": self.structural(kind=node[0], ordinal=node[1],
                                              limit=limit),
                "learned": self.neighbors(kind=node[0], ordinal=node[1],
                                           layer=level, limit=limit),
                "native_execution_verified": False}

    def walk(self, *, kind: str, ordinal: int, layer: int,
             depth: int = 2, max_nodes: int = 32) -> dict:
        """Bounded BFS over *learned* edges, preserving every node's L level."""
        kind, ordinal = _node(kind, ordinal)
        _int("layer", layer, 0, 9)
        _int("depth", depth, 0, MAX_DEPTH)
        _int("max_nodes", max_nodes, 1, MAX_VISITED)
        source = (kind, ordinal, layer)
        queue = deque([(source, 0)])
        seen = {source}
        edges = []
        while queue and len(seen) <= max_nodes:
            node, distance = queue.popleft()
            if distance >= depth:
                continue
            page = self.neighbors(kind=node[0], ordinal=node[1],
                                  layer=node[2], limit=MAX_RESULTS)
            for relation in page["relations"]:
                nxt = (relation["target_kind"], relation["target_id"],
                       relation["target_layer"])
                edges.append({"edge_id": relation["edge_id"],
                              "source": list(node), "target": list(nxt),
                              "relation": relation["relation"],
                              "polarity": relation["polarity"]})
                if nxt not in seen and len(seen) < max_nodes:
                    seen.add(nxt)
                    queue.append((nxt, distance + 1))
            if len(seen) >= max_nodes:
                break
        return {"schema": SCHEMA, "root": list(source),
                "nodes": [list(n) for n in sorted(seen)],
                "edges": edges, "depth_limit": depth,
                "node_limit": max_nodes, "candidate_only": True}
