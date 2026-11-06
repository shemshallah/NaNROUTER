"""Durable NaN source inbox for a supervised Runner Riddle worker."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Callable, Any


class InboxError(ValueError):
    pass


@dataclass(frozen=True)
class LeasedSource:
    event_id: str
    universe_id: str
    node_point: int
    head_index: int
    source_kind: str
    source_hash: str
    payload: bytes
    acl_digest: str
    nanclock_tick: int
    lease_owner: str
    attempts: int


class SQLiteSourceInbox:
    """WAL-backed idempotent intake with leases, ACKs, retries, and dead letters."""

    def __init__(self, path: str | Path, max_payload_bytes: int = 1_048_576):
        self.path = str(path)
        self.max_payload_bytes = max_payload_bytes
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS source_event (
                    event_id TEXT PRIMARY KEY,
                    universe_id TEXT NOT NULL,
                    node_point INTEGER NOT NULL CHECK(node_point BETWEEN 0 AND 255),
                    head_index INTEGER NOT NULL CHECK(head_index BETWEEN 0 AND 255),
                    source_kind TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    payload BLOB NOT NULL,
                    acl_digest TEXT NOT NULL,
                    nanclock_tick INTEGER NOT NULL,
                    state TEXT NOT NULL DEFAULT 'queued'
                        CHECK(state IN ('queued','leased','acked','deadletter')),
                    lease_owner TEXT,
                    lease_until_tick INTEGER,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    result_digest TEXT,
                    result_generation INTEGER,
                    UNIQUE(universe_id, node_point, head_index, source_hash)
                );
                CREATE INDEX IF NOT EXISTS source_event_ready
                    ON source_event(state, nanclock_tick, lease_until_tick);
                CREATE TABLE IF NOT EXISTS trace_log (
                    event_id TEXT PRIMARY KEY REFERENCES source_event(event_id),
                    trace_json TEXT NOT NULL,
                    created_tick INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS feedback_event (
                    feedback_id TEXT PRIMARY KEY,
                    feedback_json TEXT NOT NULL,
                    created_tick INTEGER NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending'
                        CHECK(state IN ('pending','acked'))
                );
            """)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        return db

    def enqueue(self, *, universe_id: str, node_point: int, head_index: int,
                source_kind: str, payload: bytes, acl_digest: str,
                nanclock_tick: int) -> str:
        if not universe_id or not source_kind or not isinstance(payload, bytes):
            raise InboxError("universe, source kind, and byte payload are required")
        if not payload or len(payload) > self.max_payload_bytes:
            raise InboxError("source payload is empty or exceeds the intake bound")
        if not 0 <= node_point <= 255 or not 0 <= head_index <= 255:
            raise InboxError("node point and head index must be in 0..255")
        if len(acl_digest) != 64 or any(ch not in "0123456789abcdef" for ch in acl_digest):
            raise InboxError("ACL digest must be lowercase SHA-256 hex")
        if nanclock_tick < 0:
            raise InboxError("nanclock tick must be nonnegative")
        source_hash = hashlib.sha256(payload).hexdigest()
        event_id = hashlib.sha256(
            f"{universe_id}:{node_point}:{head_index}:{source_hash}".encode()
        ).hexdigest()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""
                INSERT OR IGNORE INTO source_event
                (event_id, universe_id, node_point, head_index, source_kind,
                 source_hash, payload, acl_digest, nanclock_tick)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (event_id, universe_id, node_point, head_index, source_kind,
                  source_hash, payload, acl_digest, nanclock_tick))
            db.commit()
        return event_id

    def lease_next(self, *, owner: str, now_tick: int,
                   lease_ticks: int = 64, max_attempts: int = 8) -> LeasedSource | None:
        if not owner or lease_ticks < 1 or now_tick < 0 or max_attempts < 1:
            raise InboxError("invalid lease parameters")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""
                SELECT * FROM source_event
                WHERE attempts < ?
                  AND (state = 'queued' OR
                       (state = 'leased' AND lease_until_tick <= ?))
                ORDER BY nanclock_tick, event_id LIMIT 1
            """, (max_attempts, now_tick)).fetchone()
            if row is None:
                db.commit()
                return None
            attempts = int(row["attempts"]) + 1
            db.execute("""
                UPDATE source_event SET state='leased', lease_owner=?,
                    lease_until_tick=?, attempts=? WHERE event_id=?
            """, (owner, now_tick + lease_ticks, attempts, row["event_id"]))
            db.commit()
            return LeasedSource(
                row["event_id"], row["universe_id"], row["node_point"],
                row["head_index"], row["source_kind"], row["source_hash"],
                bytes(row["payload"]), row["acl_digest"], row["nanclock_tick"],
                owner, attempts
            )

    def get_leased(self, event_id: str, owner: str) -> LeasedSource:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM source_event WHERE event_id=? AND state='leased' AND lease_owner=?",
                (event_id, owner)
            ).fetchone()
        if row is None:
            raise InboxError("event is not leased by this worker")
        return LeasedSource(
            row["event_id"], row["universe_id"], row["node_point"],
            row["head_index"], row["source_kind"], row["source_hash"],
            bytes(row["payload"]), row["acl_digest"], row["nanclock_tick"],
            owner, row["attempts"]
        )

    def ack(self, event: LeasedSource, *, result_digest: str,
            result_generation: int, trace: dict[str, Any]) -> bool:
        if len(result_digest) != 64 or any(ch not in "0123456789abcdef" for ch in result_digest):
            raise InboxError("result digest must be lowercase SHA-256 hex")
        if result_generation < 0:
            raise InboxError("result generation must be nonnegative")
        if trace.get("source_hash") != event.source_hash or trace.get("acl_digest") != event.acl_digest:
            raise InboxError("trace provenance does not match leased source")
        trace_json = json.dumps(trace, sort_keys=True, separators=(",", ":"))
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM source_event WHERE event_id=?",
                             (event.event_id,)).fetchone()
            if row is None:
                db.rollback()
                raise InboxError("unknown source event")
            if row["state"] == "acked":
                same = row["result_digest"] == result_digest and row["result_generation"] == result_generation
                db.commit()
                return bool(same)
            if row["state"] != "leased" or row["lease_owner"] != event.lease_owner:
                db.rollback()
                raise InboxError("lease owner mismatch or event is not leased")
            db.execute("""
                INSERT OR REPLACE INTO trace_log(event_id, trace_json, created_tick)
                VALUES (?, ?, ?)
            """, (event.event_id, trace_json, int(trace.get("nanclock_tick", 0))))
            db.execute("""
                UPDATE source_event SET state='acked', result_digest=?,
                    result_generation=?, lease_owner=NULL, lease_until_tick=NULL
                WHERE event_id=?
            """, (result_digest, result_generation, event.event_id))
            db.commit()
            return True

    def retry(self, event: LeasedSource, *, max_attempts: int = 8) -> str:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state, lease_owner, attempts FROM source_event WHERE event_id=?",
                             (event.event_id,)).fetchone()
            if row is None or row["state"] != "leased" or row["lease_owner"] != event.lease_owner:
                db.rollback()
                raise InboxError("lease owner mismatch or event is not leased")
            state = "deadletter" if int(row["attempts"]) >= max_attempts else "queued"
            db.execute("""
                UPDATE source_event SET state=?, lease_owner=NULL, lease_until_tick=NULL
                WHERE event_id=?
            """, (state, event.event_id))
            db.commit()
            return state

    def record_feedback(self, feedback: dict[str, Any]) -> str:
        required = (
            "schema", "universe_id", "macrocluster", "stage", "completed_steps",
            "base_generation", "candidate_digest", "acl_digest", "live_map_commit", "signature",
        )
        if any(key not in feedback for key in required):
            raise InboxError("bootstrap feedback envelope is incomplete")
        if feedback.get("schema") != "nanrouter.bootstrap-feedback.v1":
            raise InboxError("unsupported bootstrap feedback schema")
        if feedback.get("macrocluster") != "MC0:0" or feedback.get("live_map_commit") is not False:
            raise InboxError("feedback must target MC0:0 and remain candidate-only")
        if feedback.get("stage") not in ("LEARN_BOOLEAN", "LEARN_ROUTING", "LANGUAGE_DEMO"):
            raise InboxError("unsupported feedback stage")
        if not feedback.get("universe_id") or int(feedback.get("nanclock_tick", 0)) < 0:
            raise InboxError("feedback universe and NaN clock tick are required")
        for field in ("candidate_digest", "acl_digest"):
            value = str(feedback.get(field, ""))
            if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
                raise InboxError(f"feedback {field} must be lowercase SHA-256 hex")
        if int(feedback.get("completed_steps", -1)) < 0 or int(feedback.get("base_generation", -1)) < 0:
            raise InboxError("feedback counters must be nonnegative")
        signature = str(feedback.get("signature", ""))
        if len(signature) != 64 or any(ch not in "0123456789abcdef" for ch in signature):
            raise InboxError("feedback signature must be lowercase SHA-256 hex")
        feedback_json = json.dumps(feedback, sort_keys=True, separators=(",", ":"))
        feedback_id = hashlib.sha256(feedback_json.encode()).hexdigest()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""
                INSERT OR IGNORE INTO feedback_event
                (feedback_id, feedback_json, created_tick, state)
                VALUES (?, ?, ?, 'pending')
            """, (feedback_id, feedback_json, int(feedback.get("nanclock_tick", 0))))
            db.commit()
        return feedback_id

    def list_feedback(self, limit: int = 128) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1024:
            raise InboxError("feedback page limit must be in 1..1024")
        with self._connect() as db:
            rows = db.execute("""
                SELECT feedback_id, feedback_json FROM feedback_event
                WHERE state='pending' ORDER BY created_tick, feedback_id LIMIT ?
            """, (limit,)).fetchall()
        return [{"feedback_id": row["feedback_id"],
                 "feedback": json.loads(row["feedback_json"])} for row in rows]

    def ack_feedback(self, feedback_id: str) -> bool:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state FROM feedback_event WHERE feedback_id=?",
                             (feedback_id,)).fetchone()
            if row is None:
                db.rollback()
                raise InboxError("unknown feedback event")
            if row["state"] == "acked":
                db.commit()
                return True
            db.execute("UPDATE feedback_event SET state='acked' WHERE feedback_id=?",
                       (feedback_id,))
            db.commit()
            return True

    def stats(self) -> dict[str, int]:
        with self._connect() as db:
            rows = db.execute("SELECT state, COUNT(*) AS n FROM source_event GROUP BY state").fetchall()
        counts = {"queued": 0, "leased": 0, "acked": 0, "deadletter": 0}
        counts.update({row["state"]: int(row["n"]) for row in rows})
        return counts


class RunnerRiddleWorker:
    """One supervised learning step; the learner returns a provenance-bound trace."""

    def __init__(self, inbox: SQLiteSourceInbox, learner: Callable[[LeasedSource], dict[str, Any]],
                 worker_id: str):
        self.inbox = inbox
        self.learner = learner
        self.worker_id = worker_id

    def run_once(self, *, now_tick: int, base_generation: int) -> bool:
        event = self.inbox.lease_next(owner=self.worker_id, now_tick=now_tick)
        if event is None:
            return False
        try:
            trace = self.learner(event)
            if trace.get("schema") != "nanrouter.trace.v1":
                raise InboxError("learner returned an unsupported trace")
            if trace.get("source_hash") != event.source_hash:
                raise InboxError("learner trace does not identify the source bytes")
            if trace.get("acl_digest") != event.acl_digest:
                raise InboxError("learner trace ACL differs from source ACL")
            if trace.get("universe_id") != event.universe_id:
                raise InboxError("learner trace universe mismatch")
            digest = hashlib.sha256(json.dumps(
                trace, sort_keys=True, separators=(",", ":")
            ).encode()).hexdigest()
            self.inbox.ack(event, result_digest=digest,
                           result_generation=base_generation, trace=trace)
            return True
        except Exception:
            self.inbox.retry(event)
            raise
