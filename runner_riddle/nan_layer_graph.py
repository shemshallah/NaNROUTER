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
            if old is not None and (
                    int(old["src"]) != src or int(old["dst"]) != dst
                    or int(old["source_head"]) != source_head):
                raise NanGraphError("edge endpoints and original proposer are immutable")
            if old is not None and tick < int(old["tick"]):
                raise NanGraphError("edge tick cannot move backward")
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

    def retract(self, *, edge_id: str, source_head: int,
                expected_generation: int, tick: int = 0) -> dict:
        """CAS tombstone, retaining immutable evidence and every earlier version."""
        if (type(edge_id) is not str or not 1 <= len(edge_id) <= 160
                or re.fullmatch(r"[a-zA-Z0-9_.:-]+", edge_id) is None
                or type(source_head) is not int or not 1 <= source_head <= 255
                or type(expected_generation) is not int or expected_generation < 1
                or type(tick) is not int or tick < 0):
            raise NanGraphError("invalid retraction parameters")
        self.store._authorize(WRITE, "nan_layer_edge", edge_id)
        with self.store._write(self.store.mc0_path) as db:
            self._ensure(db)
            old = db.execute(
                "SELECT * FROM nan_layer_edge WHERE edge_id=?", (edge_id,)
            ).fetchone()
            if old is None:
                raise NanGraphError("cannot retract nonexistent claim")
            if int(old["generation"]) != expected_generation:
                raise StaleGenerationError("stale retraction generation")
            if int(old["source_head"]) != source_head:
                raise NanGraphError("only original proposer may retract")
            if old["status"] != "candidate":
                raise NanGraphError("claim already retracted")
            if tick < int(old["tick"]):
                raise NanGraphError("retraction tick cannot go backward")
            record = dict(old)
            record.update(generation=expected_generation + 1,
                          tick=tick, status="retracted")
            serialized = json.dumps(record, sort_keys=True, separators=(",", ":"))
            db.execute(
                "UPDATE nan_layer_edge SET generation=?,tick=?,status='retracted' "
                "WHERE edge_id=? AND generation=? AND status='candidate'",
                (record["generation"], tick, edge_id, expected_generation)
            )
            db.execute("INSERT INTO nan_layer_edge_history VALUES (?,?,?)",
                       (edge_id, record["generation"], serialized))
        return {**record, "src_route": cell_route(record["src"]),
                "dst_route": cell_route(record["dst"]), "native_executed": False,
                "mathematical_truth_promoted": False}

    def master_graph_page(self, *, parent_root_sha256: str,
                          chart_generation: int, offset: int = 0,
                          limit: int = _MAX_PAGE,
                          history_offset: int | None = None,
                          history_limit: int = _MAX_PAGE) -> dict:
        """Bounded read projection; digests cover full state and full history.

        A SQLite snapshot transaction ensures the page and all digests refer
        to one consistent database state. This is NOT a router signature or
        an MTH execution receipt.
        """
        from .mirror_point_register import TOPOLOGY_DIGEST
        if (type(parent_root_sha256) is not str
                or _SHA.fullmatch(parent_root_sha256) is None
                or type(chart_generation) is not int or chart_generation < 0
                or type(offset) is not int or offset < 0
                or type(limit) is not int or not 1 <= limit <= _MAX_PAGE):
            raise NanGraphError("invalid master projection parameters")
        if history_offset is not None and (
                type(history_offset) is not int or history_offset < 0
                or type(history_limit) is not int
                or not 1 <= history_limit <= _MAX_PAGE):
            raise NanGraphError("invalid graph history page parameters")
        self.store._authorize(READ, "nan_layer_edge", "projection")
        state_hash = hashlib.sha256(b"nanrouter.nan-layer-state/1\0")
        history_hash = hashlib.sha256(b"nanrouter.nan-layer-history/1\0")
        entries, latest, last = [], {}, {}
        history_entries = []
        history_total = 0
        total = candidate_count = retracted_count = 0
        by_layer = [0] * 10
        with self.store._connect(self.store.mc0_path) as db:
            db.execute("BEGIN")
            try:
                names = {r["name"] for r in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name IN ('nan_layer_edge','nan_layer_edge_history')")}
                if len(names) == 1:
                    raise NanGraphError("partial graph/history schema")
                if len(names) == 2:
                    for row in db.execute(
                            "SELECT * FROM nan_layer_edge ORDER BY edge_id"):
                        record = dict(row)
                        raw = json.dumps(record,sort_keys=True,
                                         separators=(",",":")).encode()
                        state_hash.update(len(raw).to_bytes(8,"big") + raw)
                        latest[record["edge_id"]] = (
                            int(record["generation"]), raw.decode())
                        if offset <= total < offset + limit:
                            entries.append({
                                **record,
                                "src_route": cell_route(int(record["src"])),
                                "dst_route": cell_route(int(record["dst"]))})
                        total += 1
                        by_layer[int(record["layer"])] += 1
                        if record["status"] == "candidate":
                            candidate_count += 1
                        elif record["status"] == "retracted":
                            retracted_count += 1
                        else:
                            raise NanGraphError("invalid persisted status")
                    for row in db.execute(
                            "SELECT edge_id,generation,payload FROM "
                            "nan_layer_edge_history ORDER BY edge_id,generation"):
                        eid, gen, payload = (
                            row["edge_id"], int(row["generation"]), row["payload"])
                        try:
                            decoded = json.loads(payload)
                            canonical = json.dumps(decoded,sort_keys=True,
                                                   separators=(",",":"))
                        except (ValueError, TypeError) as exc:
                            raise NanGraphError("invalid graph history JSON") from exc
                        if (payload != canonical
                                or decoded.get("edge_id") != eid
                                or type(decoded.get("generation")) is not int
                                or decoded["generation"] != gen
                                or gen != last.get(eid, 0) + 1):
                            raise NanGraphError("discontinuous graph history")
                        raw = json.dumps([eid,gen,payload],sort_keys=True,
                                         separators=(",",":")).encode()
                        history_hash.update(len(raw).to_bytes(8,"big") + raw)
                        # History and state pages are selected from this SAME
                        # SQLite read transaction and share one commitment.
                        if (history_offset is not None
                                and history_offset <= history_total
                                < history_offset + history_limit):
                            history_entries.append({
                                "edge_id": eid, "generation": gen,
                                "payload": payload,
                            })
                        history_total += 1
                        last[eid] = gen
                        if eid not in latest:
                            raise NanGraphError("orphan graph history")
                        if gen == latest[eid][0] and payload != latest[eid][1]:
                            raise NanGraphError("graph state differs from latest history")
                    if any(last.get(k) != gen for k,(gen,_) in latest.items()):
                        raise NanGraphError("graph history does not match current state")
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
        header = {
            "schema": "nanrouter.nan-layer-master-commitment/1",
            "topology_sha256": TOPOLOGY_DIGEST,
            "parent_root_sha256": parent_root_sha256,
            "chart_generation": chart_generation,
            "total_edges": total,
            "candidate_edges": candidate_count,
            "retracted_edges": retracted_count,
            "layer_counts": by_layer,
            "state_sha256": state_hash.hexdigest(),
            "history_sha256": history_hash.hexdigest()}
        raw = json.dumps(header,sort_keys=True,separators=(",",":")).encode()
        result = {**header,
                "graph_commitment_sha256": hashlib.sha256(
                    b"nanrouter.nan-layer-commitment/1\0"+raw).hexdigest(),
                "offset":offset,
                "next_offset":offset+len(entries)
                    if offset+len(entries)<total else None,
                "entries":entries,
                "snapshot_consistent":True,
                "signed_by_router":False,
                "native_mth_receipt":False,
                "mathematical_truth_promoted":False}
        if history_offset is not None:
            result.update(
                history_offset=history_offset,
                history_entries=history_entries,
                history_total=history_total,
                history_next_offset=(
                    history_offset + len(history_entries)
                    if history_offset + len(history_entries) < history_total
                    else None
                ),
            )
        return result
