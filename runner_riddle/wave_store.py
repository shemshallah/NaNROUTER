"""Durable BS0DB/MC0DB control and evidence store for wave jobs.

The wave store is a control/evidence plane, not the canonical universe.  It
schedules bounded work, tracks leases and capabilities, and appends immutable
trace/seal/signature evidence.  It never stores dense wave arrays, host-computed
mathematics, or secret key material.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Iterator

SCHEMA_VERSION = 1

JOB_STATES = ("queued", "leased", "done", "failed", "dead")
LEASE_STATES = ("active", "expired", "completed", "failed")
OPERATOR_STATUSES = ("candidate", "active", "deprecated", "revoked")
CAPABILITY_STATUSES = ("declared", "native_verified", "degraded", "revoked")
EVIDENCE_LEVELS = ("declared", "measured", "replayed", "native_verified", "certified")
FEEDBACK_STATES = ("pending", "acked")


class WaveStoreError(ValueError):
    pass


class JobConflictError(WaveStoreError):
    pass


class StaleGenerationError(WaveStoreError):
    pass


class LeaseError(WaveStoreError):
    pass


class OperatorConflictError(WaveStoreError):
    pass


class CapabilityConflictError(WaveStoreError):
    pass


_MC0_SCHEMA = """
CREATE TABLE IF NOT EXISTS wave_job (
    job_id TEXT PRIMARY KEY,
    universe_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK(generation >= 0),
    operator_digest TEXT NOT NULL CHECK(length(operator_digest) = 64),
    operator_id TEXT,
    precision TEXT,
    workspace INTEGER NOT NULL DEFAULT 0 CHECK(workspace >= 0),
    kind TEXT NOT NULL DEFAULT 'wave',
    payload_json TEXT NOT NULL DEFAULT '{}',
    state TEXT NOT NULL DEFAULT 'queued'
        CHECK(state IN ('queued','leased','done','failed','dead')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
    lease_owner TEXT,
    lease_token TEXT,
    lease_epoch INTEGER NOT NULL DEFAULT 0 CHECK(lease_epoch >= 0),
    deadline_tick INTEGER,
    result_digest TEXT,
    result_generation INTEGER,
    error TEXT,
    created_tick INTEGER NOT NULL CHECK(created_tick >= 0),
    updated_tick INTEGER NOT NULL CHECK(updated_tick >= 0)
);
CREATE INDEX IF NOT EXISTS wave_job_ready
    ON wave_job(state, generation, created_tick, job_id);
CREATE INDEX IF NOT EXISTS wave_job_lease
    ON wave_job(lease_owner, lease_epoch);

CREATE TABLE IF NOT EXISTS wave_lease (
    lease_token TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES wave_job(job_id) ON DELETE RESTRICT,
    lease_owner TEXT NOT NULL,
    lease_epoch INTEGER NOT NULL CHECK(lease_epoch >= 1),
    acquired_tick INTEGER NOT NULL CHECK(acquired_tick >= 0),
    deadline_tick INTEGER NOT NULL CHECK(deadline_tick >= acquired_tick),
    state TEXT NOT NULL DEFAULT 'active'
        CHECK(state IN ('active','expired','completed','failed')),
    released_tick INTEGER,
    UNIQUE(job_id, lease_epoch)
);
CREATE INDEX IF NOT EXISTS wave_lease_expiry
    ON wave_lease(state, deadline_tick);

CREATE TABLE IF NOT EXISTS wave_operator (
    operator_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version >= 1),
    digest TEXT NOT NULL CHECK(length(digest) = 64),
    shape_json TEXT NOT NULL,
    precision TEXT NOT NULL,
    evidence_level TEXT NOT NULL
        CHECK(evidence_level IN ('declared','measured','replayed','native_verified','certified')),
    workspace INTEGER NOT NULL CHECK(workspace >= 0),
    status TEXT NOT NULL
        CHECK(status IN ('candidate','active','deprecated','revoked')),
    created_tick INTEGER NOT NULL CHECK(created_tick >= 0),
    PRIMARY KEY(operator_id, version),
    UNIQUE(operator_id, digest)
);

CREATE TABLE IF NOT EXISTS wave_capability (
    kernel_id TEXT NOT NULL,
    runner_id TEXT NOT NULL,
    verified_digest TEXT NOT NULL CHECK(length(verified_digest) = 64),
    workspace INTEGER NOT NULL CHECK(workspace >= 0),
    precision TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK(status IN ('declared','native_verified','degraded','revoked')),
    epoch INTEGER NOT NULL CHECK(epoch >= 0),
    updated_tick INTEGER NOT NULL CHECK(updated_tick >= 0),
    PRIMARY KEY(kernel_id, runner_id)
);
CREATE INDEX IF NOT EXISTS wave_capability_dispatch
    ON wave_capability(status, verified_digest, workspace);

CREATE TABLE IF NOT EXISTS wave_fold_certificate (
    certificate_id TEXT PRIMARY KEY,
    universe_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK(generation >= 0),
    operator_digest TEXT NOT NULL CHECK(length(operator_digest) = 64),
    basis_digest TEXT NOT NULL CHECK(length(basis_digest) = 64),
    residual_q16 INTEGER NOT NULL DEFAULT 0 CHECK(residual_q16 >= 0),
    evidence_level TEXT NOT NULL
        CHECK(evidence_level IN ('declared','measured','replayed','native_verified','certified')),
    producer TEXT NOT NULL,
    nanclock_tick INTEGER NOT NULL CHECK(nanclock_tick >= 0),
    payload_json TEXT NOT NULL DEFAULT '{}',
    signature TEXT NOT NULL CHECK(length(signature) = 64),
    created_tick INTEGER NOT NULL CHECK(created_tick >= 0)
);
CREATE INDEX IF NOT EXISTS wave_fold_certificate_lookup
    ON wave_fold_certificate(universe_id, generation, nanclock_tick);

CREATE TABLE IF NOT EXISTS wave_match_index (
    match_id TEXT PRIMARY KEY,
    universe_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    signature_id TEXT NOT NULL,
    digest TEXT NOT NULL CHECK(length(digest) = 64),
    score_q16 INTEGER,
    producer TEXT NOT NULL,
    nanclock_tick INTEGER NOT NULL CHECK(nanclock_tick >= 0),
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_tick INTEGER NOT NULL CHECK(created_tick >= 0)
);
CREATE INDEX IF NOT EXISTS wave_match_index_lookup
    ON wave_match_index(universe_id, kind, nanclock_tick);
"""

_BS0_SCHEMA = """
CREATE TABLE IF NOT EXISTS wave_trace (
    trace_id TEXT PRIMARY KEY,
    job_id TEXT,
    universe_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK(generation >= 0),
    digest TEXT NOT NULL CHECK(length(digest) = 64),
    producer TEXT NOT NULL,
    nanclock_tick INTEGER NOT NULL CHECK(nanclock_tick >= 0),
    payload_json TEXT,
    payload_blob BLOB,
    signature TEXT NOT NULL CHECK(length(signature) = 64),
    created_tick INTEGER NOT NULL CHECK(created_tick >= 0),
    CHECK(payload_json IS NOT NULL OR payload_blob IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS wave_trace_lookup
    ON wave_trace(universe_id, generation, nanclock_tick);
CREATE TRIGGER IF NOT EXISTS wave_trace_no_update
    BEFORE UPDATE ON wave_trace
    BEGIN SELECT RAISE(ABORT, 'wave_trace is append-only'); END;
CREATE TRIGGER IF NOT EXISTS wave_trace_no_delete
    BEFORE DELETE ON wave_trace
    BEGIN SELECT RAISE(ABORT, 'wave_trace is append-only'); END;

CREATE TABLE IF NOT EXISTS wave_seal (
    seal_id TEXT PRIMARY KEY,
    job_id TEXT,
    universe_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK(generation >= 0),
    digest TEXT NOT NULL CHECK(length(digest) = 64),
    producer TEXT NOT NULL,
    nanclock_tick INTEGER NOT NULL CHECK(nanclock_tick >= 0),
    payload_json TEXT,
    payload_blob BLOB,
    signature TEXT NOT NULL CHECK(length(signature) = 64),
    created_tick INTEGER NOT NULL CHECK(created_tick >= 0),
    CHECK(payload_json IS NOT NULL OR payload_blob IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS wave_seal_lookup
    ON wave_seal(universe_id, generation, nanclock_tick);
CREATE TRIGGER IF NOT EXISTS wave_seal_no_update
    BEFORE UPDATE ON wave_seal
    BEGIN SELECT RAISE(ABORT, 'wave_seal is append-only'); END;
CREATE TRIGGER IF NOT EXISTS wave_seal_no_delete
    BEFORE DELETE ON wave_seal
    BEGIN SELECT RAISE(ABORT, 'wave_seal is append-only'); END;

CREATE TABLE IF NOT EXISTS wave_signature (
    signature_id TEXT PRIMARY KEY,
    universe_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK(generation >= 0),
    kind TEXT NOT NULL,
    digest TEXT NOT NULL CHECK(length(digest) = 64),
    producer TEXT NOT NULL,
    nanclock_tick INTEGER NOT NULL CHECK(nanclock_tick >= 0),
    payload_json TEXT,
    payload_blob BLOB,
    signature TEXT NOT NULL CHECK(length(signature) = 64),
    created_tick INTEGER NOT NULL CHECK(created_tick >= 0),
    CHECK(payload_json IS NOT NULL OR payload_blob IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS wave_signature_search
    ON wave_signature(universe_id, kind, nanclock_tick, signature_id);
CREATE TRIGGER IF NOT EXISTS wave_signature_no_update
    BEFORE UPDATE ON wave_signature
    BEGIN SELECT RAISE(ABORT, 'wave_signature is append-only'); END;
CREATE TRIGGER IF NOT EXISTS wave_signature_no_delete
    BEFORE DELETE ON wave_signature
    BEGIN SELECT RAISE(ABORT, 'wave_signature is append-only'); END;

CREATE TABLE IF NOT EXISTS wave_feedback (
    feedback_id TEXT PRIMARY KEY,
    universe_id TEXT NOT NULL,
    generation INTEGER NOT NULL CHECK(generation >= 0),
    candidate_digest TEXT NOT NULL CHECK(length(candidate_digest) = 64),
    producer TEXT NOT NULL,
    nanclock_tick INTEGER NOT NULL CHECK(nanclock_tick >= 0),
    payload_json TEXT NOT NULL,
    signature TEXT NOT NULL CHECK(length(signature) = 64),
    state TEXT NOT NULL DEFAULT 'pending'
        CHECK(state IN ('pending','acked')),
    created_tick INTEGER NOT NULL CHECK(created_tick >= 0),
    acked_tick INTEGER
);
CREATE INDEX IF NOT EXISTS wave_feedback_pending
    ON wave_feedback(state, nanclock_tick, feedback_id);
"""


def _require_text(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WaveStoreError(f"{name} must be a non-empty string")
    return value


def _require_int(name: str, value: Any, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise WaveStoreError(f"{name} must be an integer >= {minimum}")
    return value


def _require_digest(name: str, value: Any) -> str:
    if (not isinstance(value, str) or len(value) != 64
            or any(ch not in "0123456789abcdef" for ch in value)):
        raise WaveStoreError(f"{name} must be lowercase SHA-256 hex")
    return value


def _require_enum(name: str, value: Any, allowed: Iterable[str]) -> str:
    choices = tuple(allowed)
    if value not in choices:
        raise WaveStoreError(f"{name} must be one of: {', '.join(choices)}")
    return value


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise WaveStoreError("payload must be JSON serializable") from exc


def _row_record(row: sqlite3.Row) -> dict[str, Any]:
    """Expose decoded JSON aliases while retaining the raw DB columns."""
    record = dict(row)
    for column in tuple(record):
        if column.endswith("_json") and record[column] is not None:
            record[column[:-5]] = json.loads(record[column])
    if record.get("payload_blob") is not None:
        record["payload_blob"] = bytes(record["payload_blob"])
    return record


class WaveStore:
    """One process owning the BS0DB evidence store and the MC0DB control store."""

    def __init__(self, bs0_path: str | Path, mc0_path: str | Path,
                 *, max_payload_bytes: int = 1_048_576):
        if Path(bs0_path).resolve() == Path(mc0_path).resolve():
            raise WaveStoreError("BS0DB and MC0DB must be distinct databases")
        _require_int("max_payload_bytes", max_payload_bytes, minimum=1)
        self.bs0_path = str(bs0_path)
        self.mc0_path = str(mc0_path)
        self.max_payload_bytes = max_payload_bytes
        self._initialize(self.bs0_path, "BS0DB", _BS0_SCHEMA)
        self._initialize(self.mc0_path, "MC0DB", _MC0_SCHEMA)

    @contextmanager
    def _connect(self, path: str) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(path, timeout=30, isolation_level=None)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=30000")
            yield db
        finally:
            db.close()

    def _initialize(self, path: str, store: str, schema_sql: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect(path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("""
                CREATE TABLE IF NOT EXISTS wave_schema (
                    store TEXT PRIMARY KEY CHECK(store IN ('BS0DB','MC0DB')),
                    version INTEGER NOT NULL CHECK(version >= 1),
                    applied_tick INTEGER NOT NULL DEFAULT 0 CHECK(applied_tick >= 0)
                )
            """)
            row = db.execute(
                "SELECT version FROM wave_schema WHERE store=?", (store,)
            ).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO wave_schema(store, version, applied_tick) VALUES (?, ?, 0)",
                    (store, SCHEMA_VERSION),
                )
            elif int(row["version"]) != SCHEMA_VERSION:
                raise WaveStoreError(
                    f"{store} schema version {row['version']} is not supported "
                    f"(expected {SCHEMA_VERSION})"
                )
            db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            db.executescript(schema_sql)

    def _payload(self, payload: Any = None,
                 payload_blob: bytes | None = None) -> tuple[str | None, bytes | None]:
        if payload is None and payload_blob is None:
            raise WaveStoreError("payload JSON or payload blob is required")
        if payload is not None and payload_blob is not None:
            raise WaveStoreError("provide either payload JSON or payload blob, not both")
        if payload_blob is not None:
            if not isinstance(payload_blob, (bytes, bytearray, memoryview)):
                raise WaveStoreError("payload_blob must be bytes")
            blob = bytes(payload_blob)
            if not blob or len(blob) > self.max_payload_bytes:
                raise WaveStoreError("payload blob is empty or exceeds the store bound")
            return None, blob
        encoded = _canonical_json(payload)
        if len(encoded.encode("utf-8")) > self.max_payload_bytes:
            raise WaveStoreError("payload JSON exceeds the store bound")
        return encoded, None

    def _append_record(self, path: str, table: str, id_column: str,
                       record_id: str, values: dict[str, Any],
                       *, conflict_message: str) -> dict[str, Any]:
        columns = (id_column, *values.keys())
        placeholders = ", ".join("?" for _ in columns)
        with self._connect(path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                f"SELECT * FROM {table} WHERE {id_column}=?", (record_id,)
            ).fetchone()
            if row is not None:
                conflict = any(row[column] != value for column, value in values.items())
                db.commit()
                if conflict:
                    raise WaveStoreError(conflict_message)
                return _row_record(row)
            db.execute(
                f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
                (record_id, *values.values()),
            )
            row = db.execute(
                f"SELECT * FROM {table} WHERE {id_column}=?", (record_id,)
            ).fetchone()
            db.commit()
            return _row_record(row)

    # -- MC0DB jobs and leases ------------------------------------------------

    def enqueue_job(self, job_id: str, *, universe_id: str, generation: int,
                    operator_digest: str, payload: Any = None,
                    kind: str = "wave", operator_id: str | None = None,
                    precision: str | None = None, workspace: int = 0,
                    nanclock_tick: int = 0) -> dict[str, Any]:
        _require_text("job_id", job_id)
        _require_text("universe_id", universe_id)
        _require_int("generation", generation)
        _require_digest("operator_digest", operator_digest)
        _require_text("kind", kind)
        _require_int("workspace", workspace)
        _require_int("nanclock_tick", nanclock_tick)
        if operator_id is not None:
            _require_text("operator_id", operator_id)
        if precision is not None:
            _require_text("precision", precision)
        payload_json = _canonical_json({} if payload is None else payload)
        if len(payload_json.encode("utf-8")) > self.max_payload_bytes:
            raise WaveStoreError("job payload exceeds the store bound")

        values = {
            "universe_id": universe_id,
            "generation": generation,
            "operator_digest": operator_digest,
            "operator_id": operator_id,
            "precision": precision,
            "workspace": workspace,
            "kind": kind,
            "payload_json": payload_json,
        }
        with self._connect(self.mc0_path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM wave_job WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is not None:
                same = all(row[column] == value for column, value in values.items())
                if not same and int(row["generation"]) != generation:
                    db.rollback()
                    raise StaleGenerationError(
                        f"job {job_id} is already bound to generation {row['generation']}"
                    )
                db.commit()
                if not same:
                    raise JobConflictError(
                        f"job {job_id} already exists with a different contract"
                    )
                return _row_record(row)
            db.execute("""
                INSERT INTO wave_job
                (job_id, universe_id, generation, operator_digest, operator_id,
                 precision, workspace, kind, payload_json, state, attempts,
                 created_tick, updated_tick)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', 0, ?, ?)
            """, (job_id, universe_id, generation, operator_digest, operator_id,
                  precision, workspace, kind, payload_json, nanclock_tick,
                  nanclock_tick))
            row = db.execute(
                "SELECT * FROM wave_job WHERE job_id=?", (job_id,)
            ).fetchone()
            db.commit()
            return _row_record(row)

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        _require_text("job_id", job_id)
        with self._connect(self.mc0_path) as db:
            row = db.execute(
                "SELECT * FROM wave_job WHERE job_id=?", (job_id,)
            ).fetchone()
        return None if row is None else _row_record(row)

    def lease_job(self, *, owner: str, now_tick: int, lease_ticks: int = 64,
                  expected_generation: int | None = None,
                  max_attempts: int = 8,
                  job_id: str | None = None) -> dict[str, Any] | None:
        _require_text("owner", owner)
        _require_int("now_tick", now_tick)
        _require_int("lease_ticks", lease_ticks, minimum=1)
        _require_int("max_attempts", max_attempts, minimum=1)
        if expected_generation is not None:
            _require_int("expected_generation", expected_generation)
        if job_id is not None:
            _require_text("job_id", job_id)

        query = "SELECT * FROM wave_job WHERE state='queued' AND attempts < ?"
        args: list[Any] = [max_attempts]
        if expected_generation is not None:
            query += " AND generation=?"
            args.append(expected_generation)
        if job_id is not None:
            query += " AND job_id=?"
            args.append(job_id)
        query += " ORDER BY created_tick, job_id LIMIT 1"

        with self._connect(self.mc0_path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(query, args).fetchone()
            if row is None:
                db.commit()
                return None
            lease_epoch = int(row["lease_epoch"]) + 1
            token = hashlib.sha256(
                f"{row['job_id']}\0{owner}\0{lease_epoch}\0{now_tick}".encode()
            ).hexdigest()
            deadline = now_tick + lease_ticks
            db.execute("""
                UPDATE wave_job SET state='leased', attempts=attempts + 1,
                    lease_owner=?, lease_token=?, lease_epoch=?, deadline_tick=?,
                    updated_tick=?
                WHERE job_id=? AND state='queued'
            """, (owner, token, lease_epoch, deadline, now_tick, row["job_id"]))
            db.execute("""
                INSERT INTO wave_lease
                (lease_token, job_id, lease_owner, lease_epoch, acquired_tick,
                 deadline_tick, state)
                VALUES (?, ?, ?, ?, ?, ?, 'active')
            """, (token, row["job_id"], owner, lease_epoch, now_tick, deadline))
            leased = db.execute(
                "SELECT * FROM wave_job WHERE job_id=?", (row["job_id"],)
            ).fetchone()
            db.commit()
            return _row_record(leased)

    def _leased_row(self, db, job_id: str, *, lease_token: str,
                    lease_epoch: int, now_tick: int,
                    lease_owner: str | None = None) -> sqlite3.Row:
        row = db.execute(
            "SELECT * FROM wave_job WHERE job_id=?", (job_id,)
        ).fetchone()
        if row is None:
            raise LeaseError("unknown job")
        if row["state"] != "leased":
            raise LeaseError(f"job is not leased (state={row['state']})")
        if row["lease_token"] != lease_token or int(row["lease_epoch"]) != lease_epoch:
            raise LeaseError("lease token or epoch is stale")
        if lease_owner is not None and row["lease_owner"] != lease_owner:
            raise LeaseError("lease owner does not match")
        deadline = row["deadline_tick"]
        if deadline is None or now_tick >= int(deadline):
            raise LeaseError("lease has expired")
        return row

    def complete_job(self, job_id: str, *, lease_token: str, lease_epoch: int,
                     result_digest: str, now_tick: int,
                     result_generation: int | None = None,
                     lease_owner: str | None = None) -> dict[str, Any]:
        _require_text("job_id", job_id)
        _require_text("lease_token", lease_token)
        _require_int("lease_epoch", lease_epoch, minimum=1)
        _require_digest("result_digest", result_digest)
        _require_int("now_tick", now_tick)
        if lease_owner is not None:
            _require_text("lease_owner", lease_owner)

        with self._connect(self.mc0_path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM wave_job WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None:
                db.rollback()
                raise LeaseError("unknown job")
            generation = int(row["generation"])
            if result_generation is None:
                result_generation = generation
            _require_int("result_generation", result_generation)
            if result_generation < generation:
                db.rollback()
                raise StaleGenerationError(
                    f"result generation {result_generation} is older than job generation {generation}"
                )

            if row["state"] == "done":
                same = (
                    row["lease_token"] == lease_token
                    and int(row["lease_epoch"]) == lease_epoch
                    and row["result_digest"] == result_digest
                    and int(row["result_generation"]) == result_generation
                )
                db.commit()
                if same:
                    return _row_record(row)
                if (row["lease_token"] != lease_token
                        or int(row["lease_epoch"]) != lease_epoch):
                    raise LeaseError("lease token or epoch is stale")
                raise JobConflictError("job already completed with a different result")

            row = self._leased_row(
                db, job_id, lease_token=lease_token, lease_epoch=lease_epoch,
                now_tick=now_tick, lease_owner=lease_owner,
            )
            db.execute("""
                UPDATE wave_job SET state='done', result_digest=?,
                    result_generation=?, updated_tick=? WHERE job_id=?
            """, (result_digest, result_generation, now_tick, job_id))
            db.execute("""
                UPDATE wave_lease SET state='completed', released_tick=?
                WHERE lease_token=? AND state='active'
            """, (now_tick, lease_token))
            completed = db.execute(
                "SELECT * FROM wave_job WHERE job_id=?", (job_id,)
            ).fetchone()
            db.commit()
            return _row_record(completed)

    def fail_job(self, job_id: str, *, lease_token: str, lease_epoch: int,
                 now_tick: int, error: str,
                 lease_owner: str | None = None) -> dict[str, Any]:
        _require_text("job_id", job_id)
        _require_text("lease_token", lease_token)
        _require_int("lease_epoch", lease_epoch, minimum=1)
        _require_int("now_tick", now_tick)
        _require_text("error", error)
        if lease_owner is not None:
            _require_text("lease_owner", lease_owner)

        with self._connect(self.mc0_path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM wave_job WHERE job_id=?", (job_id,)
            ).fetchone()
            if row is None:
                db.rollback()
                raise LeaseError("unknown job")
            if row["state"] == "failed":
                same = (
                    row["lease_token"] == lease_token
                    and int(row["lease_epoch"]) == lease_epoch
                    and row["error"] == error
                )
                db.commit()
                if same:
                    return _row_record(row)
                if (row["lease_token"] != lease_token
                        or int(row["lease_epoch"]) != lease_epoch):
                    raise LeaseError("lease token or epoch is stale")
                raise JobConflictError("job already failed with a different error")
            row = self._leased_row(
                db, job_id, lease_token=lease_token, lease_epoch=lease_epoch,
                now_tick=now_tick, lease_owner=lease_owner,
            )
            db.execute("""
                UPDATE wave_job SET state='failed', error=?, updated_tick=?
                WHERE job_id=?
            """, (error, now_tick, job_id))
            db.execute("""
                UPDATE wave_lease SET state='failed', released_tick=?
                WHERE lease_token=? AND state='active'
            """, (now_tick, lease_token))
            failed = db.execute(
                "SELECT * FROM wave_job WHERE job_id=?", (job_id,)
            ).fetchone()
            db.commit()
            return _row_record(failed)

    def expire_leases(self, *, now_tick: int,
                      max_attempts: int = 8) -> list[dict[str, Any]]:
        _require_int("now_tick", now_tick)
        _require_int("max_attempts", max_attempts, minimum=1)
        expired: list[dict[str, Any]] = []
        with self._connect(self.mc0_path) as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("""
                SELECT * FROM wave_job
                WHERE state='leased' AND deadline_tick IS NOT NULL
                  AND deadline_tick <= ?
                ORDER BY deadline_tick, job_id
            """, (now_tick,)).fetchall()
            for row in rows:
                new_state = "dead" if int(row["attempts"]) >= max_attempts else "queued"
                error = row["error"]
                if new_state == "dead" and not error:
                    error = "lease attempts exhausted"
                db.execute("""
                    UPDATE wave_job SET state=?, lease_owner=NULL, lease_token=NULL,
                        deadline_tick=NULL, error=?, updated_tick=? WHERE job_id=?
                """, (new_state, error, now_tick, row["job_id"]))
                db.execute("""
                    UPDATE wave_lease SET state='expired', released_tick=?
                    WHERE job_id=? AND lease_epoch=? AND state='active'
                """, (now_tick, row["job_id"], row["lease_epoch"]))
                expired.append({
                    "job_id": row["job_id"],
                    "state": new_state,
                    "lease_owner": row["lease_owner"],
                    "lease_epoch": int(row["lease_epoch"]),
                })
            db.commit()
        return expired

    def list_jobs(self, *, state: str | None = None, limit: int = 128) -> list[dict[str, Any]]:
        _require_int("limit", limit, minimum=1)
        if limit > 1024:
            raise WaveStoreError("limit must be <= 1024")
        query = "SELECT * FROM wave_job"
        args: list[Any] = []
        if state is not None:
            _require_enum("state", state, JOB_STATES)
            query += " WHERE state=?"
            args.append(state)
        query += " ORDER BY created_tick, job_id LIMIT ?"
        args.append(limit)
        with self._connect(self.mc0_path) as db:
            rows = db.execute(query, args).fetchall()
        return [_row_record(row) for row in rows]

    # -- MC0DB operator/capability registries ---------------------------------

    def register_operator(self, *, operator_id: str, version: int, digest: str,
                          shape: Any, precision: str, evidence_level: str,
                          workspace: int, status: str = "active",
                          nanclock_tick: int = 0) -> dict[str, Any]:
        _require_text("operator_id", operator_id)
        _require_int("version", version, minimum=1)
        _require_digest("digest", digest)
        _require_text("precision", precision)
        _require_enum("evidence_level", evidence_level, EVIDENCE_LEVELS)
        _require_int("workspace", workspace)
        _require_enum("status", status, OPERATOR_STATUSES)
        _require_int("nanclock_tick", nanclock_tick)
        shape_json = _canonical_json(shape)
        if len(shape_json.encode("utf-8")) > self.max_payload_bytes:
            raise WaveStoreError("operator shape descriptor exceeds the store bound")

        values = {
            "digest": digest,
            "shape_json": shape_json,
            "precision": precision,
            "evidence_level": evidence_level,
            "workspace": workspace,
            "status": status,
        }
        with self._connect(self.mc0_path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""
                SELECT * FROM wave_operator WHERE operator_id=? AND version=?
            """, (operator_id, version)).fetchone()
            if row is not None:
                same = all(row[column] == value for column, value in values.items())
                db.commit()
                if not same:
                    raise OperatorConflictError(
                        f"operator {operator_id} v{version} is already registered "
                        "with a different digest or contract"
                    )
                return _row_record(row)
            duplicate = db.execute("""
                SELECT version FROM wave_operator WHERE operator_id=? AND digest=?
            """, (operator_id, digest)).fetchone()
            if duplicate is not None:
                db.rollback()
                raise OperatorConflictError(
                    f"operator digest is already registered for version "
                    f"{duplicate['version']}"
                )
            db.execute("""
                INSERT INTO wave_operator
                (operator_id, version, digest, shape_json, precision,
                 evidence_level, workspace, status, created_tick)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (operator_id, version, digest, shape_json, precision,
                  evidence_level, workspace, status, nanclock_tick))
            row = db.execute("""
                SELECT * FROM wave_operator WHERE operator_id=? AND version=?
            """, (operator_id, version)).fetchone()
            db.commit()
            return _row_record(row)

    def get_operator(self, operator_id: str,
                     version: int | None = None) -> dict[str, Any] | None:
        _require_text("operator_id", operator_id)
        query = "SELECT * FROM wave_operator WHERE operator_id=?"
        args: list[Any] = [operator_id]
        if version is not None:
            _require_int("version", version, minimum=1)
            query += " AND version=?"
            args.append(version)
        query += " ORDER BY version DESC LIMIT 1"
        with self._connect(self.mc0_path) as db:
            row = db.execute(query, args).fetchone()
        return None if row is None else _row_record(row)

    def register_capability(self, *, kernel_id: str, runner_id: str,
                            verified_digest: str, workspace: int, precision: str,
                            status: str = "declared", epoch: int = 1,
                            nanclock_tick: int = 0) -> dict[str, Any]:
        _require_text("kernel_id", kernel_id)
        _require_text("runner_id", runner_id)
        _require_digest("verified_digest", verified_digest)
        _require_int("workspace", workspace)
        _require_text("precision", precision)
        _require_enum("status", status, CAPABILITY_STATUSES)
        _require_int("epoch", epoch, minimum=1)
        _require_int("nanclock_tick", nanclock_tick)

        values = {
            "verified_digest": verified_digest,
            "workspace": workspace,
            "precision": precision,
            "status": status,
            "epoch": epoch,
            "updated_tick": nanclock_tick,
        }
        with self._connect(self.mc0_path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""
                SELECT * FROM wave_capability WHERE kernel_id=? AND runner_id=?
            """, (kernel_id, runner_id)).fetchone()
            if row is not None:
                stored_epoch = int(row["epoch"])
                if epoch < stored_epoch:
                    db.rollback()
                    raise CapabilityConflictError(
                        f"capability epoch {epoch} is older than stored epoch {stored_epoch}"
                    )
                if epoch == stored_epoch:
                    contract = {
                        column: value for column, value in values.items()
                        if column != "updated_tick"
                    }
                    same = all(row[column] == value
                               for column, value in contract.items())
                    db.commit()
                    if not same:
                        raise CapabilityConflictError(
                            "capability epoch is already registered with a different contract"
                        )
                    return _row_record(row)
                db.execute("""
                    UPDATE wave_capability SET verified_digest=?, workspace=?,
                        precision=?, status=?, epoch=?, updated_tick=?
                    WHERE kernel_id=? AND runner_id=?
                """, (verified_digest, workspace, precision, status, epoch,
                      nanclock_tick, kernel_id, runner_id))
            else:
                db.execute("""
                    INSERT INTO wave_capability
                    (kernel_id, runner_id, verified_digest, workspace, precision,
                     status, epoch, updated_tick)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (kernel_id, runner_id, verified_digest, workspace,
                      precision, status, epoch, nanclock_tick))
            row = db.execute("""
                SELECT * FROM wave_capability WHERE kernel_id=? AND runner_id=?
            """, (kernel_id, runner_id)).fetchone()
            db.commit()
            return _row_record(row)

    def dispatchable_capabilities(self, *, workspace: int,
                                  operator_digest: str | None = None,
                                  digest: str | None = None,
                                  precision: str | None = None,
                                  limit: int = 64) -> list[dict[str, Any]]:
        _require_int("workspace", workspace)
        _require_int("limit", limit, minimum=1)
        if limit > 1024:
            raise WaveStoreError("limit must be <= 1024")
        if operator_digest is not None and digest is not None and operator_digest != digest:
            raise WaveStoreError("operator_digest and digest disagree")
        target = operator_digest if operator_digest is not None else digest
        if target is None:
            raise WaveStoreError("a verified operator digest is required")
        _require_digest("operator_digest", target)
        query = """
            SELECT * FROM wave_capability
            WHERE status='native_verified' AND verified_digest=? AND workspace >= ?
        """
        args: list[Any] = [target, workspace]
        if precision is not None:
            _require_text("precision", precision)
            query += " AND precision=?"
            args.append(precision)
        query += " ORDER BY runner_id, kernel_id LIMIT ?"
        args.append(limit)
        with self._connect(self.mc0_path) as db:
            rows = db.execute(query, args).fetchall()
        return [_row_record(row) for row in rows]

    # -- MC0DB fold certificates and match index ------------------------------

    def append_fold_certificate(self, *, universe_id: str, generation: int,
                                operator_digest: str, basis_digest: str,
                                producer: str, nanclock_tick: int, signature: str,
                                certificate_id: str | None = None,
                                residual_q16: int = 0,
                                evidence_level: str = "native_verified",
                                payload: Any = None) -> dict[str, Any]:
        _require_text("universe_id", universe_id)
        _require_int("generation", generation)
        _require_digest("operator_digest", operator_digest)
        _require_digest("basis_digest", basis_digest)
        _require_text("producer", producer)
        _require_int("nanclock_tick", nanclock_tick)
        _require_digest("signature", signature)
        _require_int("residual_q16", residual_q16)
        _require_enum("evidence_level", evidence_level, EVIDENCE_LEVELS)
        if certificate_id is None:
            certificate_id = hashlib.sha256(
                f"fold\0{universe_id}\0{generation}\0{operator_digest}\0"
                f"{basis_digest}\0{producer}\0{nanclock_tick}".encode()
            ).hexdigest()
        else:
            _require_text("certificate_id", certificate_id)
        payload_json = _canonical_json({} if payload is None else payload)
        if len(payload_json.encode("utf-8")) > self.max_payload_bytes:
            raise WaveStoreError("fold certificate payload exceeds the store bound")
        values = {
            "universe_id": universe_id,
            "generation": generation,
            "operator_digest": operator_digest,
            "basis_digest": basis_digest,
            "residual_q16": residual_q16,
            "evidence_level": evidence_level,
            "producer": producer,
            "nanclock_tick": nanclock_tick,
            "payload_json": payload_json,
            "signature": signature,
            "created_tick": nanclock_tick,
        }
        return self._append_record(
            self.mc0_path, "wave_fold_certificate", "certificate_id",
            certificate_id, values,
            conflict_message="fold certificate id already contains different evidence",
        )

    def index_match(self, *, universe_id: str, kind: str, signature_id: str,
                    digest: str, producer: str, nanclock_tick: int,
                    score_q16: int | None = None, payload: Any = None,
                    match_id: str | None = None) -> dict[str, Any]:
        _require_text("universe_id", universe_id)
        _require_text("kind", kind)
        _require_text("signature_id", signature_id)
        _require_digest("digest", digest)
        _require_text("producer", producer)
        _require_int("nanclock_tick", nanclock_tick)
        if score_q16 is not None and (isinstance(score_q16, bool)
                                      or not isinstance(score_q16, int)):
            raise WaveStoreError("score_q16 must be an integer or null")
        if match_id is None:
            match_id = hashlib.sha256(
                f"match\0{universe_id}\0{kind}\0{signature_id}\0{digest}".encode()
            ).hexdigest()
        else:
            _require_text("match_id", match_id)
        payload_json = _canonical_json({} if payload is None else payload)
        if len(payload_json.encode("utf-8")) > self.max_payload_bytes:
            raise WaveStoreError("match payload exceeds the store bound")
        values = {
            "universe_id": universe_id,
            "kind": kind,
            "signature_id": signature_id,
            "digest": digest,
            "score_q16": score_q16,
            "producer": producer,
            "nanclock_tick": nanclock_tick,
            "payload_json": payload_json,
            "created_tick": nanclock_tick,
        }
        return self._append_record(
            self.mc0_path, "wave_match_index", "match_id", match_id, values,
            conflict_message="match id already contains different evidence",
        )

    # -- BS0DB append-only evidence -------------------------------------------

    def append_trace(self, *, universe_id: str, generation: int, digest: str,
                     producer: str, nanclock_tick: int, signature: str,
                     payload: Any = None, payload_blob: bytes | None = None,
                     trace_id: str | None = None,
                     job_id: str | None = None) -> dict[str, Any]:
        _require_text("universe_id", universe_id)
        _require_int("generation", generation)
        _require_digest("digest", digest)
        _require_text("producer", producer)
        _require_int("nanclock_tick", nanclock_tick)
        _require_digest("signature", signature)
        if job_id is not None:
            _require_text("job_id", job_id)
        payload_json, blob = self._payload(payload, payload_blob)
        if trace_id is None:
            trace_id = hashlib.sha256(
                f"trace\0{universe_id}\0{generation}\0{digest}".encode()
            ).hexdigest()
        else:
            _require_text("trace_id", trace_id)
        values = {
            "job_id": job_id,
            "universe_id": universe_id,
            "generation": generation,
            "digest": digest,
            "producer": producer,
            "nanclock_tick": nanclock_tick,
            "payload_json": payload_json,
            "payload_blob": blob,
            "signature": signature,
            "created_tick": nanclock_tick,
        }
        return self._append_record(
            self.bs0_path, "wave_trace", "trace_id", trace_id, values,
            conflict_message="trace id already contains different evidence",
        )

    def append_seal(self, *, universe_id: str, generation: int, digest: str,
                    producer: str, nanclock_tick: int, signature: str,
                    payload: Any = None, payload_blob: bytes | None = None,
                    seal_id: str | None = None,
                    job_id: str | None = None) -> dict[str, Any]:
        _require_text("universe_id", universe_id)
        _require_int("generation", generation)
        _require_digest("digest", digest)
        _require_text("producer", producer)
        _require_int("nanclock_tick", nanclock_tick)
        _require_digest("signature", signature)
        if job_id is not None:
            _require_text("job_id", job_id)
        payload_json, blob = self._payload(payload, payload_blob)
        if seal_id is None:
            seal_id = hashlib.sha256(
                f"seal\0{universe_id}\0{generation}\0{digest}".encode()
            ).hexdigest()
        else:
            _require_text("seal_id", seal_id)
        values = {
            "job_id": job_id,
            "universe_id": universe_id,
            "generation": generation,
            "digest": digest,
            "producer": producer,
            "nanclock_tick": nanclock_tick,
            "payload_json": payload_json,
            "payload_blob": blob,
            "signature": signature,
            "created_tick": nanclock_tick,
        }
        return self._append_record(
            self.bs0_path, "wave_seal", "seal_id", seal_id, values,
            conflict_message="seal id already contains different evidence",
        )

    def append_signature(self, *, universe_id: str, generation: int, kind: str,
                         digest: str, producer: str, nanclock_tick: int,
                         signature: str, payload: Any = None,
                         payload_blob: bytes | None = None,
                         signature_id: str | None = None) -> dict[str, Any]:
        _require_text("universe_id", universe_id)
        _require_int("generation", generation)
        _require_text("kind", kind)
        _require_digest("digest", digest)
        _require_text("producer", producer)
        _require_int("nanclock_tick", nanclock_tick)
        _require_digest("signature", signature)
        payload_json, blob = self._payload(payload, payload_blob)
        if signature_id is None:
            signature_id = hashlib.sha256(
                f"signature\0{universe_id}\0{generation}\0{kind}\0{digest}\0"
                f"{producer}\0{nanclock_tick}".encode()
            ).hexdigest()
        else:
            _require_text("signature_id", signature_id)
        values = {
            "universe_id": universe_id,
            "generation": generation,
            "kind": kind,
            "digest": digest,
            "producer": producer,
            "nanclock_tick": nanclock_tick,
            "payload_json": payload_json,
            "payload_blob": blob,
            "signature": signature,
            "created_tick": nanclock_tick,
        }
        return self._append_record(
            self.bs0_path, "wave_signature", "signature_id", signature_id,
            values, conflict_message="signature id already contains different evidence",
        )

    def search_signatures(self, *, universe_id: str | None = None,
                          generation: int | None = None,
                          kind: str | None = None,
                          since_tick: int | None = None,
                          until_tick: int | None = None,
                          limit: int = 20) -> list[dict[str, Any]]:
        _require_int("limit", limit, minimum=1)
        if limit > 1024:
            raise WaveStoreError("limit must be <= 1024")
        query = "SELECT * FROM wave_signature WHERE 1=1"
        args: list[Any] = []
        if universe_id is not None:
            _require_text("universe_id", universe_id)
            query += " AND universe_id=?"
            args.append(universe_id)
        if generation is not None:
            _require_int("generation", generation)
            query += " AND generation=?"
            args.append(generation)
        if kind is not None:
            _require_text("kind", kind)
            query += " AND kind=?"
            args.append(kind)
        if since_tick is not None:
            _require_int("since_tick", since_tick)
            query += " AND nanclock_tick >= ?"
            args.append(since_tick)
        if until_tick is not None:
            _require_int("until_tick", until_tick)
            query += " AND nanclock_tick <= ?"
            args.append(until_tick)
        query += " ORDER BY nanclock_tick DESC, signature_id ASC LIMIT ?"
        args.append(limit)
        with self._connect(self.bs0_path) as db:
            rows = db.execute(query, args).fetchall()
        return [_row_record(row) for row in rows]

    def append_feedback(self, *, universe_id: str, generation: int,
                        candidate_digest: str, producer: str,
                        nanclock_tick: int, signature: str,
                        payload: Any = None,
                        feedback_id: str | None = None) -> dict[str, Any]:
        _require_text("universe_id", universe_id)
        _require_int("generation", generation)
        _require_digest("candidate_digest", candidate_digest)
        _require_text("producer", producer)
        _require_int("nanclock_tick", nanclock_tick)
        _require_digest("signature", signature)
        payload_json = _canonical_json({} if payload is None else payload)
        if len(payload_json.encode("utf-8")) > self.max_payload_bytes:
            raise WaveStoreError("feedback payload exceeds the store bound")
        if feedback_id is None:
            feedback_id = hashlib.sha256(
                f"feedback\0{universe_id}\0{generation}\0{candidate_digest}\0"
                f"{producer}\0{nanclock_tick}".encode()
            ).hexdigest()
        else:
            _require_text("feedback_id", feedback_id)
        values = {
            "universe_id": universe_id,
            "generation": generation,
            "candidate_digest": candidate_digest,
            "producer": producer,
            "nanclock_tick": nanclock_tick,
            "payload_json": payload_json,
            "signature": signature,
            "created_tick": nanclock_tick,
        }
        return self._append_record(
            self.bs0_path, "wave_feedback", "feedback_id", feedback_id,
            values, conflict_message="feedback id already contains different evidence",
        )

    def ack_feedback(self, feedback_id: str, *, now_tick: int) -> dict[str, Any]:
        _require_text("feedback_id", feedback_id)
        _require_int("now_tick", now_tick)
        with self._connect(self.bs0_path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM wave_feedback WHERE feedback_id=?", (feedback_id,)
            ).fetchone()
            if row is None:
                db.rollback()
                raise WaveStoreError("unknown feedback record")
            if row["state"] != "acked":
                db.execute("""
                    UPDATE wave_feedback SET state='acked', acked_tick=?
                    WHERE feedback_id=?
                """, (now_tick, feedback_id))
            row = db.execute(
                "SELECT * FROM wave_feedback WHERE feedback_id=?", (feedback_id,)
            ).fetchone()
            db.commit()
            return _row_record(row)

    # -- Observability --------------------------------------------------------

    def _table_count(self, path: str, table: str) -> int:
        with self._connect(path) as db:
            return int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def _schema_version(self, path: str, store: str) -> int:
        with self._connect(path) as db:
            row = db.execute(
                "SELECT version FROM wave_schema WHERE store=?", (store,)
            ).fetchone()
        if row is None:
            raise WaveStoreError(f"{store} schema metadata is missing")
        return int(row["version"])

    def stats(self) -> dict[str, Any]:
        bs0 = {
            "schema_version": self._schema_version(self.bs0_path, "BS0DB"),
            "wave_trace": self._table_count(self.bs0_path, "wave_trace"),
            "wave_seal": self._table_count(self.bs0_path, "wave_seal"),
            "wave_signature": self._table_count(self.bs0_path, "wave_signature"),
            "wave_feedback": self._table_count(self.bs0_path, "wave_feedback"),
        }
        jobs = {state: 0 for state in JOB_STATES}
        leases = {state: 0 for state in LEASE_STATES}
        with self._connect(self.mc0_path) as db:
            job_rows = db.execute(
                "SELECT state, COUNT(*) AS n FROM wave_job GROUP BY state"
            ).fetchall()
            lease_rows = db.execute(
                "SELECT state, COUNT(*) AS n FROM wave_lease GROUP BY state"
            ).fetchall()
        jobs.update({row["state"]: int(row["n"]) for row in job_rows})
        leases.update({row["state"]: int(row["n"]) for row in lease_rows})
        mc0 = {
            "schema_version": self._schema_version(self.mc0_path, "MC0DB"),
            "wave_job": sum(jobs.values()),
            "wave_lease": sum(leases.values()),
            "wave_operator": self._table_count(self.mc0_path, "wave_operator"),
            "wave_capability": self._table_count(self.mc0_path, "wave_capability"),
            "wave_fold_certificate": self._table_count(
                self.mc0_path, "wave_fold_certificate"
            ),
            "wave_match_index": self._table_count(self.mc0_path, "wave_match_index"),
        }
        return {
            "schema": "nanrouter.wave-store-stats.v1",
            "schema_version": SCHEMA_VERSION,
            "bs0": bs0,
            "mc0": mc0,
            "jobs": jobs,
            "leases": leases,
        }

    def health(self) -> dict[str, Any]:
        stats = self.stats()
        dead = int(stats["jobs"]["dead"])
        with self._connect(self.mc0_path) as db:
            verified = db.execute("""
                SELECT COUNT(*) FROM wave_capability WHERE status='native_verified'
            """).fetchone()[0]
        return {
            "schema": "nanrouter.wave-store-health.v1",
            "status": "degraded" if dead else "green",
            "schema_version": SCHEMA_VERSION,
            "stores": {"BS0DB": "ok", "MC0DB": "ok"},
            "jobs": stats["jobs"],
            "leases": stats["leases"],
            "native_verified_capabilities": int(verified),
        }
