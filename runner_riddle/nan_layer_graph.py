"""Versioned L0-L9 relations over one canonical NaN16 head/MP topology.

An edge is an indexed mathematical *claim*, not a native guest operation or
a proof. All edge endpoints are canonical topology cells. Only nonzero real
heads can propose edges, and each edge's evidence must be an existing
immutable typed MathLeaf. No copy of the 8 MiB chart is created.
"""
from __future__ import annotations
import hashlib
import json
import re
from .math_store import MathStore, StaleGenerationError
from .math_auth import READ, WRITE
from .mirror_point_register import MirrorRegister, PAIR_COUNT, CANONICAL_CELLS

SCHEMA = "nanrouter.nan-layer-graph/1"
EDGE_TYPES = frozenset(("isa", "part_of", "defines", "supports", "refutes",
                        "equivalent", "transforms", "causes", "depends_on",
                        "similar", "contradicts", "observes", "routes_to"))
_MAX_PAGE = 100
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SQL = (
"""CREATE TABLE IF NOT EXISTS nan_layer_edge (
edge_id TEXT PRIMARY KEY,
src INTEGER NOT NULL CHECK(src BETWEEN 0 AND 32895),
dst INTEGER NOT NULL CHECK(dst BETWEEN 0 AND 32895),
layer INTEGER NOT NULL CHECK(layer BETWEEN 0 AND 9),
relation TEXT NOT NULL,
evidence_id TEXT NOT NULL,
evidence_version INTEGER NOT NULL CHECK(evidence_version > 0),
evidence_digest TEXT NOT NULL,
source_head INTEGER NOT NULL CHECK(source_head BETWEEN 1 AND 255),
generation INTEGER NOT NULL CHECK(generation > 0),
tick INTEGER NOT NULL CHECK(tick >= 0),
status TEXT NOT NULL CHECK(status IN ('candidate','retracted'))
)""",
"""CREATE INDEX IF NOT EXISTS nan_layer_edge_src ON nan_layer_edge(src,layer)""",
"""CREATE INDEX IF NOT EXISTS nan_layer_edge_dst ON nan_layer_edge(dst,layer)""",
"""CREATE TABLE IF NOT EXISTS nan_layer_edge_history (
edge_id TEXT NOT NULL,
generation INTEGER NOT NULL,
payload TEXT NOT NULL,
PRIMARY KEY(edge_id,generation)
)""",
)


class NanGraphError(ValueError):
    pass


def cell(kind: str, ordinal: int) -> int:
    if kind == "head":
        if type(ordinal) is not int or not 0 <= ordinal < 256:
            raise NanGraphError("invalid head")
        return ordinal
    if kind == "mp":
        if type(ordinal) is not int or not 0 <= ordinal < PAIR_COUNT:
            raise NanGraphError("invalid MP")
        return 256 + ordinal
    raise NanGraphError("endpoint must be head or mp")


def cell_route(n: int) -> str:
    if type(n) is not int or not 0 <= n < CANONICAL_CELLS:
        raise NanGraphError("invalid canonical cell")
    return f"HW0:{n}" if n < 256 else f"HW0:MP{n-256}"


def _head_is_endpoint(h: int, n: int) -> bool:
    if n < 256:
        return n == h
    return h in MirrorRegister.mp(n - 256).as_dict()["writable_heads"]


class NanLayerGraph:
    def __init__(self, store: MathStore):
        if not isinstance(store, MathStore):
            raise NanGraphError("requires existing MC0DB MathStore")
        self.store = store

    def _ensure(self, db):
        for statement in _SQL:
            db.execute(statement)

    def propose(self, *, edge_id: str, src_kind: str, src_id: int,
                dst_kind: str, dst_id: int, layer: int, relation: str,
                source_head: int, evidence_id: str, evidence_version: int,
                evidence_digest: str, expected_generation: int = 0,
                tick: int = 0) -> dict:
        src, dst = cell(src_kind, src_id), cell(dst_kind, dst_id)
        if (type(layer) is not int or not 0 <= layer <= 9
                or relation not in EDGE_TYPES
                or type(source_head) is not int or not 1 <= source_head <= 255
                or not (_head_is_endpoint(source_head, src) or
                        _head_is_endpoint(source_head, dst))):
            raise NanGraphError("invalid layer, relation, or head endpoint authority")
        if (type(edge_id) is not str or not 1 <= len(edge_id) <= 160
                or not re.fullmatch(r"[a-zA-Z0-9_.:-]+", edge_id)
                or type(expected_generation) is not int or expected_generation < 0
                or type(tick) is not int or tick < 0
                or type(evidence_version) is not int or evidence_version < 1
                or type(evidence_digest) is not str
                or _SHA.fullmatch(evidence_digest) is None):
            raise NanGraphError("invalid evidence or CAS parameters")
        self.store._authorize(WRITE, "nan_layer_edge", edge_id)
        leaf = self.store.get_leaf(evidence_id, evidence_version)
        if leaf.digest() != evidence_digest:
            raise NanGraphError("evidence leaf digest mismatch")
        record = dict(edge_id=edge_id,src=src,dst=dst,layer=layer,
                      relation=relation,evidence_id=evidence_id,
                      evidence_version=evidence_version,
                      evidence_digest=evidence_digest,
                      source_head=source_head,tick=tick,status="candidate")
        with self.store._write(self.store.mc0_path) as db:
            self._ensure(db)
            old = db.execute("SELECT * FROM nan_layer_edge WHERE edge_id=?",
                             (edge_id,)).fetchone()
            generation = 1 if old is None else int(old["generation"]) + 1
            if expected_generation != generation - 1:
                raise StaleGenerationError("stale L0-L9 edge generation")
            record["generation"] = generation
            serialized = json.dumps(record,sort_keys=True,separators=(",",":"))
            db.execute(
                "INSERT INTO nan_layer_edge "
                "(edge_id,src,dst,layer,relation,evidence_id,evidence_version,"
                "evidence_digest,source_head,generation,tick,status) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(edge_id) DO UPDATE SET src=excluded.src,"
                "dst=excluded.dst,layer=excluded.layer,relation=excluded.relation,"
                "evidence_id=excluded.evidence_id,evidence_version=excluded.evidence_version,"
                "evidence_digest=excluded.evidence_digest,source_head=excluded.source_head,"
                "generation=excluded.generation,tick=excluded.tick,status=excluded.status",
                (edge_id,src,dst,layer,relation,evidence_id,evidence_version,
                 evidence_digest,source_head,generation,tick,"candidate"))
            db.execute("INSERT INTO nan_layer_edge_history VALUES (?,?,?)",
                       (edge_id,generation,serialized))
        return {**record,"src_route":cell_route(src),"dst_route":cell_route(dst),
                "native_executed":False,"mathematical_truth_promoted":False}

    def neighbors(self, *, kind: str, ordinal: int, layer: int | None = None,
                  offset: int = 0, limit: int = _MAX_PAGE) -> dict:
        node = cell(kind,ordinal)
        if (layer is not None and (type(layer) is not int or not 0 <= layer <= 9)
                or type(offset) is not int or offset < 0
                or type(limit) is not int or not 1 <= limit <= _MAX_PAGE):
            raise NanGraphError("invalid page or layer")
        self.store._authorize(READ, "nan_layer_edge", cell_route(node))
        with self.store._connect(self.store.mc0_path) as db:
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='nan_layer_edge'").fetchone() is None:
                rows = []
                total = 0
            else:
                where = "(src=? OR dst=?) AND status='candidate'"
                params = [node,node]
                if layer is not None:
                    where += " AND layer=?"
                    params.append(layer)
                total = db.execute("SELECT count(*) FROM nan_layer_edge WHERE "+where,
                                   params).fetchone()[0]
                rows = [dict(x) for x in db.execute(
                    "SELECT * FROM nan_layer_edge WHERE "+where+
                    " ORDER BY layer,edge_id LIMIT ? OFFSET ?",
                    params+[limit,offset]).fetchall()]
        for row in rows:
            row["src_route"] = cell_route(row["src"])
            row["dst_route"] = cell_route(row["dst"])
        data = {"schema":SCHEMA,"node":cell_route(node),"layer":layer,
                "total":total,"offset":offset,"edges":rows,
                "next_offset":offset+len(rows) if offset+len(rows)<total else None,
                "native_executed":False}
        data["page_sha256"] = hashlib.sha256(
            json.dumps(data,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        return data
