"""Additive mathematical persistence over the existing BS0DB/MC0DB files.

This module is deliberately *additive*.  It creates ``math_*`` tables and a
separate ``math_schema`` row in the same SQLite files used by
:class:`runner_riddle.wave_store.WaveStore`.  It never bumps, rewrites, or
reinterprets ``wave_schema``; the wave store keeps owning its schema version
and the math layer owns only its own row.

Ownership follows GAME_PLAN_:: §10:

* MC0DB owns the current math indexes (leaves, versions, functions, rules,
  candidates, admissions, mappings, and the disposable preflight cache).
* BS0DB owns immutable payloads, append-only math events, and certificates.

Leaves are immutable content/version records.  Current pointers are changed
with compare-and-swap on both expected version and expected generation.  A
rollback changes only the mapping pointer and appends a new event; it never
deletes or rewrites a version row.  Missing or corrupt payloads raise a
reference error.  They are never converted to zero or ``None``.

Payloads are content addressed by SHA-256.  A blob larger than
``chunk_bytes`` (1 MiB by default) is split into independently stored chunks,
so a 2 MiB math payload does not depend on a deployed provider accepting one
oversized SQLite blob.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from .math_objects import (
    MathAdmission, MathCandidate, MathFunction, MathLeaf, MathObjectError,
    MathRule, VERDICTS, canonical_json, digest_object, sha256_text,
)

MATH_SCHEMA_VERSION = 1
MATH_STORE_SCHEMA = "nanrouter.math-store.v1"
MATH_STORE_HEALTH_SCHEMA = "nanrouter.math-store-health.v1"

DEFAULT_CHUNK_BYTES = 1_048_576          # 1 MiB, the existing wave payload bound
DEFAULT_MAX_PAYLOAD_BYTES = 2_097_152    # 2 MiB total math payload bound

MAPPING_OBJECT_TYPES = frozenset({"leaf", "function", "rule", "relation"})
COMMIT_INTENT_STATES = frozenset({"pending", "finalized", "failed"})
EVENT_TYPES = frozenset({
    "propose", "preflight", "execute", "commit", "null", "void", "rollback",
    "mapping", "admission", "candidate", "leaf", "function", "rule",
    "relation", "cache", "certificate",
})


class MathStoreError(ValueError):
    """Base error for the additive math persistence layer."""


class MathSchemaError(MathStoreError):
    """The math schema row is absent, unsupported, or inconsistent."""


class MathConflictError(MathStoreError):
    """An immutable id/version already names different content."""


class StaleGenerationError(MathStoreError):
    """A compare-and-swap used a stale version or generation."""


class MathCommitError(MathConflictError):
    """A cross-store commit intent cannot be finalized as requested."""


class MathReferenceError(MathStoreError):
    """A referenced math object or payload is missing."""


class MathPayloadError(MathReferenceError):
    """A stored payload is truncated, missing a chunk, or digest-corrupt."""


class MathContentDigestError(MathPayloadError):
    """A leaf's declared ``content["digest"]`` is not the canonical content."""


def _require_text(name: str, value: Any, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise MathStoreError(
            f"{name} must be a non-empty string <= {maximum} characters"
        )
    return value


def _require_int(name: str, value: Any, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise MathStoreError(f"{name} must be an integer >= {minimum}")
    return value


def _require_digest(name: str, value: Any, *, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return ""
    if (not isinstance(value, str) or len(value) != 64
            or any(ch not in "0123456789abcdef" for ch in value)):
        raise MathStoreError(f"{name} must be lowercase SHA-256 hex")
    return value


def _optional_digest(name: str, value: Any) -> str | None:
    if value is None:
        return None
    return _require_digest(name, value)


def _canonical(value: Any, name: str) -> str:
    try:
        return canonical_json(value)
    except MathObjectError as exc:
        raise MathStoreError(f"{name} is not canonical JSON") from exc


def _row_record(row: sqlite3.Row) -> dict[str, Any]:
    """Decode ``*_json`` columns while retaining the raw columns."""
    record = dict(row)
    for column in tuple(record):
        if column.endswith("_json") and record[column] is not None:
            try:
                record[column[:-5]] = json.loads(record[column])
            except (TypeError, ValueError) as exc:
                raise MathReferenceError(
                    f"stored {column} is not valid JSON"
                ) from exc
    if record.get("blob") is not None:
        record["blob"] = bytes(record["blob"])
    return record


_MC0_MATH_SCHEMA = """
CREATE TABLE IF NOT EXISTS math_schema (
    store TEXT PRIMARY KEY CHECK(store IN ('BS0DB','MC0DB')),
    version INTEGER NOT NULL CHECK(version >= 1),
    applied_tick INTEGER NOT NULL DEFAULT 0 CHECK(applied_tick >= 0)
);

CREATE TABLE IF NOT EXISTS math_leaf (
    leaf_id TEXT PRIMARY KEY,
    current_version INTEGER NOT NULL CHECK(current_version >= 1),
    generation INTEGER NOT NULL CHECK(generation >= 0),
    kind TEXT NOT NULL,
    type_digest TEXT NOT NULL CHECK(length(type_digest) = 64),
    content_digest TEXT
        CHECK(content_digest IS NULL OR length(content_digest) = 64),
    status TEXT NOT NULL,
    created_tick INTEGER NOT NULL CHECK(created_tick >= 0),
    updated_tick INTEGER NOT NULL CHECK(updated_tick >= 0)
);
CREATE INDEX IF NOT EXISTS math_leaf_status
    ON math_leaf(status, updated_tick, leaf_id);

CREATE TABLE IF NOT EXISTS math_leaf_version (
    leaf_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version >= 1),
    leaf_digest TEXT NOT NULL CHECK(length(leaf_digest) = 64),
    kind TEXT NOT NULL,
    type_json TEXT NOT NULL,
    type_digest TEXT NOT NULL CHECK(length(type_digest) = 64),
    content_digest TEXT
        CHECK(content_digest IS NULL OR length(content_digest) = 64),
    payload_ref TEXT
        CHECK(payload_ref IS NULL OR length(payload_ref) = 64),
    storage_tier TEXT NOT NULL DEFAULT 'BS0DB',
    leaf_json TEXT NOT NULL,
    created_tick INTEGER NOT NULL CHECK(created_tick >= 0),
    PRIMARY KEY(leaf_id, version),
    FOREIGN KEY(leaf_id) REFERENCES math_leaf(leaf_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS math_leaf_version_payload
    ON math_leaf_version(payload_ref);
CREATE TRIGGER IF NOT EXISTS math_leaf_version_no_update
    BEFORE UPDATE ON math_leaf_version
    BEGIN SELECT RAISE(ABORT, 'math_leaf_version is immutable'); END;
CREATE TRIGGER IF NOT EXISTS math_leaf_version_no_delete
    BEFORE DELETE ON math_leaf_version
    BEGIN SELECT RAISE(ABORT, 'math_leaf_version is immutable'); END;

CREATE TABLE IF NOT EXISTS math_function (
    function_id TEXT PRIMARY KEY,
    current_version INTEGER NOT NULL CHECK(current_version >= 1),
    generation INTEGER NOT NULL CHECK(generation >= 0),
    contract_digest TEXT NOT NULL CHECK(length(contract_digest) = 64),
    status TEXT NOT NULL,
    proof_status TEXT NOT NULL,
    created_tick INTEGER NOT NULL CHECK(created_tick >= 0),
    updated_tick INTEGER NOT NULL CHECK(updated_tick >= 0)
);

CREATE TABLE IF NOT EXISTS math_function_version (
    function_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version >= 1),
    contract_digest TEXT NOT NULL CHECK(length(contract_digest) = 64),
    payload_ref TEXT NOT NULL CHECK(length(payload_ref) = 64),
    function_json TEXT NOT NULL,
    status TEXT NOT NULL,
    proof_status TEXT NOT NULL,
    created_tick INTEGER NOT NULL CHECK(created_tick >= 0),
    PRIMARY KEY(function_id, version),
    FOREIGN KEY(function_id) REFERENCES math_function(function_id)
        ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS math_function_version_payload
    ON math_function_version(payload_ref);
CREATE TRIGGER IF NOT EXISTS math_function_version_no_update
    BEFORE UPDATE ON math_function_version
    BEGIN SELECT RAISE(ABORT, 'math_function_version is immutable'); END;
CREATE TRIGGER IF NOT EXISTS math_function_version_no_delete
    BEFORE DELETE ON math_function_version
    BEGIN SELECT RAISE(ABORT, 'math_function_version is immutable'); END;

CREATE TABLE IF NOT EXISTS math_rule (
    rule_id TEXT PRIMARY KEY,
    current_version INTEGER NOT NULL CHECK(current_version >= 1),
    generation INTEGER NOT NULL CHECK(generation >= 0),
    level INTEGER NOT NULL CHECK(level BETWEEN 0 AND 3),
    rule_digest TEXT NOT NULL CHECK(length(rule_digest) = 64),
    status TEXT NOT NULL,
    proof_status TEXT NOT NULL,
    created_tick INTEGER NOT NULL CHECK(created_tick >= 0),
    updated_tick INTEGER NOT NULL CHECK(updated_tick >= 0)
);
CREATE INDEX IF NOT EXISTS math_rule_level
    ON math_rule(level, status, rule_id);

CREATE TABLE IF NOT EXISTS math_rule_version (
    rule_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version >= 1),
    level INTEGER NOT NULL CHECK(level BETWEEN 0 AND 3),
    rule_digest TEXT NOT NULL CHECK(length(rule_digest) = 64),
    payload_ref TEXT NOT NULL CHECK(length(payload_ref) = 64),
    rule_json TEXT NOT NULL,
    status TEXT NOT NULL,
    proof_status TEXT NOT NULL,
    certificate_digest TEXT
        CHECK(certificate_digest IS NULL OR length(certificate_digest) = 64),
    created_tick INTEGER NOT NULL CHECK(created_tick >= 0),
    PRIMARY KEY(rule_id, version),
    FOREIGN KEY(rule_id) REFERENCES math_rule(rule_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS math_rule_version_payload
    ON math_rule_version(payload_ref);
CREATE TRIGGER IF NOT EXISTS math_rule_version_no_update
    BEFORE UPDATE ON math_rule_version
    BEGIN SELECT RAISE(ABORT, 'math_rule_version is immutable'); END;
CREATE TRIGGER IF NOT EXISTS math_rule_version_no_delete
    BEFORE DELETE ON math_rule_version
    BEGIN SELECT RAISE(ABORT, 'math_rule_version is immutable'); END;

CREATE TABLE IF NOT EXISTS math_relation (
    relation_id TEXT PRIMARY KEY,
    current_version INTEGER NOT NULL CHECK(current_version >= 1),
    generation INTEGER NOT NULL CHECK(generation >= 0),
    relation_digest TEXT NOT NULL CHECK(length(relation_digest) = 64),
    status TEXT NOT NULL,
    created_tick INTEGER NOT NULL CHECK(created_tick >= 0),
    updated_tick INTEGER NOT NULL CHECK(updated_tick >= 0)
);

CREATE TABLE IF NOT EXISTS math_relation_version (
    relation_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version >= 1),
    relation_digest TEXT NOT NULL CHECK(length(relation_digest) = 64),
    payload_ref TEXT NOT NULL CHECK(length(payload_ref) = 64),
    relation_json TEXT NOT NULL,
    created_tick INTEGER NOT NULL CHECK(created_tick >= 0),
    PRIMARY KEY(relation_id, version),
    FOREIGN KEY(relation_id) REFERENCES math_relation(relation_id)
        ON DELETE RESTRICT
);
CREATE TRIGGER IF NOT EXISTS math_relation_version_no_update
    BEFORE UPDATE ON math_relation_version
    BEGIN SELECT RAISE(ABORT, 'math_relation_version is immutable'); END;
CREATE TRIGGER IF NOT EXISTS math_relation_version_no_delete
    BEFORE DELETE ON math_relation_version
    BEGIN SELECT RAISE(ABORT, 'math_relation_version is immutable'); END;

CREATE TABLE IF NOT EXISTS math_candidate (
    candidate_id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL,
    function_id TEXT NOT NULL,
    function_version INTEGER NOT NULL CHECK(function_version >= 1),
    rank INTEGER NOT NULL CHECK(rank >= 0),
    preflight_hint TEXT NOT NULL,
    candidate_digest TEXT NOT NULL CHECK(length(candidate_digest) = 64),
    payload_ref TEXT NOT NULL CHECK(length(payload_ref) = 64),
    candidate_json TEXT NOT NULL,
    created_tick INTEGER NOT NULL CHECK(created_tick >= 0)
);
CREATE INDEX IF NOT EXISTS math_candidate_snapshot
    ON math_candidate(snapshot_id, rank, candidate_id);
CREATE TRIGGER IF NOT EXISTS math_candidate_no_update
    BEFORE UPDATE ON math_candidate
    BEGIN SELECT RAISE(ABORT, 'math_candidate is immutable'); END;
CREATE TRIGGER IF NOT EXISTS math_candidate_no_delete
    BEFORE DELETE ON math_candidate
    BEGIN SELECT RAISE(ABORT, 'math_candidate is immutable'); END;

CREATE TABLE IF NOT EXISTS math_admission (
    admission_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    verdict TEXT NOT NULL,
    rule_snapshot_id TEXT NOT NULL DEFAULT '',
    preflight_digest TEXT NOT NULL DEFAULT '',
    admission_digest TEXT NOT NULL CHECK(length(admission_digest) = 64),
    payload_ref TEXT NOT NULL CHECK(length(payload_ref) = 64),
    admission_json TEXT NOT NULL,
    created_tick INTEGER NOT NULL CHECK(created_tick >= 0)
);
CREATE INDEX IF NOT EXISTS math_admission_candidate
    ON math_admission(candidate_id, verdict, admission_id);
CREATE TRIGGER IF NOT EXISTS math_admission_no_update
    BEFORE UPDATE ON math_admission
    BEGIN SELECT RAISE(ABORT, 'math_admission is immutable'); END;
CREATE TRIGGER IF NOT EXISTS math_admission_no_delete
    BEFORE DELETE ON math_admission
    BEGIN SELECT RAISE(ABORT, 'math_admission is immutable'); END;

CREATE TABLE IF NOT EXISTS math_mapping (
    mapping_id TEXT PRIMARY KEY,
    object_type TEXT NOT NULL
        CHECK(object_type IN ('leaf','function','rule','relation')),
    object_id TEXT NOT NULL,
    current_version INTEGER NOT NULL CHECK(current_version >= 1),
    generation INTEGER NOT NULL CHECK(generation >= 1),
    target_digest TEXT NOT NULL CHECK(length(target_digest) = 64),
    storage_tier TEXT NOT NULL DEFAULT 'BS0DB',
    route TEXT NOT NULL DEFAULT 'local',
    status TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('active','rolled_back','disabled')),
    created_tick INTEGER NOT NULL CHECK(created_tick >= 0),
    updated_tick INTEGER NOT NULL CHECK(updated_tick >= 0),
    UNIQUE(object_type, object_id)
);
CREATE INDEX IF NOT EXISTS math_mapping_object
    ON math_mapping(object_type, object_id, generation);

CREATE TABLE IF NOT EXISTS math_preflight_cache (
    cache_key TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    verdict TEXT NOT NULL,
    result_digest TEXT NOT NULL CHECK(length(result_digest) = 64),
    invalidation_digest TEXT NOT NULL CHECK(length(invalidation_digest) = 64),
    result_json TEXT NOT NULL,
    generation INTEGER NOT NULL DEFAULT 1 CHECK(generation >= 1),
    created_tick INTEGER NOT NULL CHECK(created_tick >= 0),
    updated_tick INTEGER NOT NULL CHECK(updated_tick >= 0),
    expires_tick INTEGER CHECK(expires_tick IS NULL OR expires_tick >= 0)
);
CREATE INDEX IF NOT EXISTS math_preflight_cache_snapshot
    ON math_preflight_cache(snapshot_id, candidate_id, updated_tick);

CREATE TABLE IF NOT EXISTS math_commit_intent (
    intent_id TEXT PRIMARY KEY,
    mapping_id TEXT NOT NULL,
    object_type TEXT NOT NULL
        CHECK(object_type IN ('leaf','function','rule','relation')),
    object_id TEXT NOT NULL,
    target_version INTEGER NOT NULL CHECK(target_version >= 1),
    target_digest TEXT NOT NULL CHECK(length(target_digest) = 64),
    evidence_digest TEXT NOT NULL CHECK(length(evidence_digest) = 64),
    base_version INTEGER NOT NULL CHECK(base_version >= 0),
    base_generation INTEGER NOT NULL CHECK(base_generation >= 0),
    base_mapping_digest TEXT
        CHECK(base_mapping_digest IS NULL OR length(base_mapping_digest) = 64),
    state TEXT NOT NULL DEFAULT 'pending'
        CHECK(state IN ('pending','finalized','failed')),
    evidence_ref TEXT
        CHECK(evidence_ref IS NULL OR length(evidence_ref) = 64),
    failure_reason TEXT,
    created_tick INTEGER NOT NULL CHECK(created_tick >= 0),
    updated_tick INTEGER NOT NULL CHECK(updated_tick >= 0),
    finalized_tick INTEGER CHECK(finalized_tick IS NULL OR finalized_tick >= 0)
);
CREATE INDEX IF NOT EXISTS math_commit_intent_state
    ON math_commit_intent(state, created_tick, intent_id);
CREATE INDEX IF NOT EXISTS math_commit_intent_target
    ON math_commit_intent(mapping_id, target_version, intent_id);
"""

_BS0_MATH_SCHEMA = """
CREATE TABLE IF NOT EXISTS math_schema (
    store TEXT PRIMARY KEY CHECK(store IN ('BS0DB','MC0DB')),
    version INTEGER NOT NULL CHECK(version >= 1),
    applied_tick INTEGER NOT NULL DEFAULT 0 CHECK(applied_tick >= 0)
);

CREATE TABLE IF NOT EXISTS math_payload (
    digest TEXT NOT NULL CHECK(length(digest) = 64),
    encoding TEXT NOT NULL,
    chunk_index INTEGER NOT NULL CHECK(chunk_index >= 0),
    chunk_count INTEGER NOT NULL CHECK(chunk_count >= 1),
    total_length INTEGER NOT NULL CHECK(total_length >= 0),
    chunk_length INTEGER NOT NULL CHECK(chunk_length >= 0),
    blob BLOB NOT NULL,
    created_tick INTEGER NOT NULL CHECK(created_tick >= 0),
    PRIMARY KEY(digest, chunk_index),
    CHECK(chunk_index < chunk_count)
);
CREATE INDEX IF NOT EXISTS math_payload_digest
    ON math_payload(digest, chunk_index);
CREATE TRIGGER IF NOT EXISTS math_payload_no_update
    BEFORE UPDATE ON math_payload
    BEGIN SELECT RAISE(ABORT, 'math_payload is append-only'); END;
CREATE TRIGGER IF NOT EXISTS math_payload_no_delete
    BEFORE DELETE ON math_payload
    BEGIN SELECT RAISE(ABORT, 'math_payload is append-only'); END;

CREATE TABLE IF NOT EXISTS math_event (
    event_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id TEXT NOT NULL,
    version INTEGER CHECK(version IS NULL OR version >= 0),
    generation INTEGER CHECK(generation IS NULL OR generation >= 0),
    digest TEXT CHECK(digest IS NULL OR length(digest) = 64),
    actor TEXT NOT NULL,
    tick INTEGER NOT NULL CHECK(tick >= 0),
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_tick INTEGER NOT NULL CHECK(created_tick >= 0)
);
CREATE INDEX IF NOT EXISTS math_event_object
    ON math_event(object_type, object_id, event_seq);
CREATE INDEX IF NOT EXISTS math_event_type
    ON math_event(event_type, event_seq);
CREATE TRIGGER IF NOT EXISTS math_event_no_update
    BEFORE UPDATE ON math_event
    BEGIN SELECT RAISE(ABORT, 'math_event is append-only'); END;
CREATE TRIGGER IF NOT EXISTS math_event_no_delete
    BEFORE DELETE ON math_event
    BEGIN SELECT RAISE(ABORT, 'math_event is append-only'); END;

CREATE TABLE IF NOT EXISTS math_certificate (
    certificate_id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    certificate_digest TEXT NOT NULL CHECK(length(certificate_digest) = 64),
    payload_ref TEXT CHECK(payload_ref IS NULL OR length(payload_ref) = 64),
    certificate_json TEXT NOT NULL,
    created_tick INTEGER NOT NULL CHECK(created_tick >= 0)
);
CREATE INDEX IF NOT EXISTS math_certificate_subject
    ON math_certificate(subject_type, subject_id, kind);
CREATE TRIGGER IF NOT EXISTS math_certificate_no_update
    BEFORE UPDATE ON math_certificate
    BEGIN SELECT RAISE(ABORT, 'math_certificate is append-only'); END;
CREATE TRIGGER IF NOT EXISTS math_certificate_no_delete
    BEFORE DELETE ON math_certificate
    BEGIN SELECT RAISE(ABORT, 'math_certificate is append-only'); END;

CREATE TABLE IF NOT EXISTS math_commit_evidence (
    intent_id TEXT PRIMARY KEY,
    evidence_digest TEXT NOT NULL CHECK(length(evidence_digest) = 64),
    mapping_id TEXT NOT NULL,
    object_type TEXT NOT NULL
        CHECK(object_type IN ('leaf','function','rule','relation')),
    object_id TEXT NOT NULL,
    target_version INTEGER NOT NULL CHECK(target_version >= 1),
    target_digest TEXT NOT NULL CHECK(length(target_digest) = 64),
    evidence_json TEXT NOT NULL,
    created_tick INTEGER NOT NULL CHECK(created_tick >= 0)
);
CREATE INDEX IF NOT EXISTS math_commit_evidence_target
    ON math_commit_evidence(mapping_id, target_version, intent_id);
CREATE TRIGGER IF NOT EXISTS math_commit_evidence_no_update
    BEFORE UPDATE ON math_commit_evidence
    BEGIN SELECT RAISE(ABORT, 'math_commit_evidence is append-only'); END;
CREATE TRIGGER IF NOT EXISTS math_commit_evidence_no_delete
    BEFORE DELETE ON math_commit_evidence
    BEGIN SELECT RAISE(ABORT, 'math_commit_evidence is append-only'); END;
"""


class MathStore:
    """Additive math persistence on the existing BS0DB/MC0DB file pair."""

    def __init__(self, bs0_path: str | Path, mc0_path: str | Path, *,
                 max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
                 chunk_bytes: int = DEFAULT_CHUNK_BYTES,
                 strict_content_digest: bool = False):
        if Path(bs0_path).resolve() == Path(mc0_path).resolve():
            raise MathStoreError("BS0DB and MC0DB must be distinct databases")
        _require_int("max_payload_bytes", max_payload_bytes, minimum=1)
        _require_int("chunk_bytes", chunk_bytes, minimum=1)
        if not isinstance(strict_content_digest, bool):
            raise MathStoreError("strict_content_digest must be a boolean")
        self.bs0_path = str(bs0_path)
        self.mc0_path = str(mc0_path)
        self.max_payload_bytes = max_payload_bytes
        self.chunk_bytes = chunk_bytes
        # Legacy records without metadata_version remain loadable.  Setting
        # metadata_version on a leaf (or this flag on the store) opts into
        # declared-content-digest equality for both writes and reloads.
        self.strict_content_digest = strict_content_digest
        self._initialize(self.bs0_path, "BS0DB", _BS0_MATH_SCHEMA)
        self._initialize(self.mc0_path, "MC0DB", _MC0_MATH_SCHEMA)

    # -- lifecycle -----------------------------------------------------------

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

    @contextmanager
    def _write(self, path: str) -> Iterator[sqlite3.Connection]:
        with self._connect(path) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except BaseException:
                db.rollback()
                raise
            else:
                db.commit()

    def _initialize(self, path: str, store: str, schema_sql: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect(path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("""
                CREATE TABLE IF NOT EXISTS math_schema (
                    store TEXT PRIMARY KEY CHECK(store IN ('BS0DB','MC0DB')),
                    version INTEGER NOT NULL CHECK(version >= 1),
                    applied_tick INTEGER NOT NULL DEFAULT 0
                        CHECK(applied_tick >= 0)
                )
            """)
            row = db.execute(
                "SELECT version FROM math_schema WHERE store=?", (store,)
            ).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO math_schema(store, version, applied_tick) "
                    "VALUES (?, ?, 0)",
                    (store, MATH_SCHEMA_VERSION),
                )
            elif int(row["version"]) != MATH_SCHEMA_VERSION:
                raise MathSchemaError(
                    f"{store} math schema version {row['version']} is not "
                    f"supported (expected {MATH_SCHEMA_VERSION})"
                )
            # Additive only: wave_schema and PRAGMA user_version are owned by
            # WaveStore and are intentionally left untouched here.
            db.executescript(schema_sql)

    # -- small helpers -------------------------------------------------------

    def _schema_version(self, path: str, store: str) -> int:
        with self._connect(path) as db:
            row = db.execute(
                "SELECT version FROM math_schema WHERE store=?", (store,)
            ).fetchone()
        if row is None:
            raise MathSchemaError(f"{store} math schema metadata is missing")
        return int(row["version"])

    def _table_count(self, path: str, table: str) -> int:
        with self._connect(path) as db:
            return int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def health(self) -> dict[str, Any]:
        """Token-free, read-only health projection of the math schema."""
        try:
            bs0_version = self._schema_version(self.bs0_path, "BS0DB")
            mc0_version = self._schema_version(self.mc0_path, "MC0DB")
            counts = {
                "leaves": self._table_count(self.mc0_path, "math_leaf"),
                "leaf_versions": self._table_count(
                    self.mc0_path, "math_leaf_version"
                ),
                "functions": self._table_count(self.mc0_path, "math_function"),
                "rules": self._table_count(self.mc0_path, "math_rule"),
                "mappings": self._table_count(self.mc0_path, "math_mapping"),
                "commit_intents": self._table_count(
                    self.mc0_path, "math_commit_intent"
                ),
                "commit_evidence": self._table_count(
                    self.bs0_path, "math_commit_evidence"
                ),
                "events": self._table_count(self.bs0_path, "math_event"),
                "payloads": self._table_count(self.bs0_path, "math_payload"),
            }
            status = "green"
            error = None
        except Exception as exc:
            bs0_version = None
            mc0_version = None
            counts = {}
            status = "unhealthy"
            error = type(exc).__name__
        return {
            "schema": MATH_STORE_HEALTH_SCHEMA,
            "status": status,
            "versions": {"bs0": bs0_version, "mc0": mc0_version},
            "counts": counts,
            "error": error,
            "strict_content_digest": self.strict_content_digest,
        }

    @staticmethod
    def _mapping_id(object_type: str, object_id: str) -> str:
        return f"{object_type}:{object_id}"

    def _object_version_digest_tx(self, db: sqlite3.Connection,
                                  object_type: str, object_id: str,
                                  version: int) -> str | None:
        if object_type == "leaf":
            query = ("SELECT leaf_digest AS digest FROM math_leaf_version "
                     "WHERE leaf_id=? AND version=?")
        elif object_type == "function":
            query = ("SELECT contract_digest AS digest "
                     "FROM math_function_version "
                     "WHERE function_id=? AND version=?")
        elif object_type == "rule":
            query = ("SELECT rule_digest AS digest FROM math_rule_version "
                     "WHERE rule_id=? AND version=?")
        elif object_type == "relation":
            query = ("SELECT relation_digest AS digest "
                     "FROM math_relation_version "
                     "WHERE relation_id=? AND version=?")
        else:
            raise MathStoreError(f"unknown mapping object type: {object_type!r}")
        row = db.execute(query, (object_id, version)).fetchone()
        return None if row is None else str(row["digest"])

    def _sync_mapping_tx(self, db: sqlite3.Connection, object_type: str,
                         object_id: str, version: int, digest: str,
                         generation: int, tick: int) -> str:
        mapping_id = self._mapping_id(object_type, object_id)
        row = db.execute(
            "SELECT * FROM math_mapping WHERE mapping_id=?", (mapping_id,)
        ).fetchone()
        if row is None:
            db.execute(
                "INSERT INTO math_mapping(mapping_id, object_type, object_id, "
                "current_version, generation, target_digest, storage_tier, "
                "route, status, created_tick, updated_tick) "
                "VALUES (?, ?, ?, ?, ?, ?, 'BS0DB', 'local', 'active', ?, ?)",
                (mapping_id, object_type, object_id, version, max(1, generation),
                 digest, tick, tick),
            )
        else:
            db.execute(
                "UPDATE math_mapping SET current_version=?, generation=?, "
                "target_digest=?, status='active', updated_tick=? "
                "WHERE mapping_id=?",
                (version, generation, digest, tick, mapping_id),
            )
        return mapping_id

    # -- payloads ------------------------------------------------------------

    @staticmethod
    def _decode_payload_rows(rows: list[sqlite3.Row], digest: str,
                             *, encoding: str | None = None) -> tuple[bytes, dict[str, Any]]:
        if not rows:
            raise MathReferenceError(f"math payload {digest} is missing")
        first = rows[0]
        chunk_count = int(first["chunk_count"])
        total_length = int(first["total_length"])
        if chunk_count < 1 or len(rows) != chunk_count:
            raise MathPayloadError(
                f"math payload {digest} has {len(rows)} of {chunk_count} chunks"
            )
        chunks: list[bytes] = []
        for index, row in enumerate(rows):
            if int(row["chunk_index"]) != index:
                raise MathPayloadError(
                    f"math payload {digest} is missing chunk {index}"
                )
            if int(row["chunk_count"]) != chunk_count:
                raise MathPayloadError(
                    f"math payload {digest} has inconsistent chunk counts"
                )
            blob = bytes(row["blob"])
            if len(blob) != int(row["chunk_length"]):
                raise MathPayloadError(
                    f"math payload {digest} chunk {index} is truncated"
                )
            chunks.append(blob)
        data = b"".join(chunks)
        if len(data) != total_length:
            raise MathPayloadError(
                f"math payload {digest} length mismatch: "
                f"{len(data)} != {total_length}"
            )
        actual = hashlib.sha256(data).hexdigest()
        if actual != digest:
            raise MathPayloadError(
                f"math payload {digest} digest mismatch: {actual}"
            )
        if encoding is not None and first["encoding"] != encoding:
            raise MathPayloadError(
                f"math payload {digest} encoding {first['encoding']!r} != "
                f"{encoding!r}"
            )
        return data, {
            "digest": digest,
            "encoding": str(first["encoding"]),
            "chunk_count": chunk_count,
            "chunk_bytes": max(
                (len(chunk) for chunk in chunks), default=0
            ),
            "total_length": total_length,
            "created_tick": int(first["created_tick"]),
        }

    def _fetch_payload_rows(self, digest: str) -> list[sqlite3.Row]:
        with self._connect(self.bs0_path) as db:
            return db.execute(
                "SELECT * FROM math_payload WHERE digest=? "
                "ORDER BY chunk_index ASC",
                (digest,),
            ).fetchall()

    def put_payload(self, data: bytes | bytearray | memoryview, *,
                    encoding: str = "binary", tick: int = 0) -> dict[str, Any]:
        """Store a content-addressed blob, chunking it when necessary."""
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise MathStoreError("payload data must be bytes")
        blob = bytes(data)
        if not blob:
            raise MathStoreError("payload data must not be empty")
        if len(blob) > self.max_payload_bytes:
            raise MathStoreError(
                f"payload of {len(blob)} bytes exceeds the math store bound "
                f"of {self.max_payload_bytes}"
            )
        _require_text("encoding", encoding, maximum=64)
        _require_int("tick", tick)
        digest = hashlib.sha256(blob).hexdigest()
        chunk_count = (len(blob) + self.chunk_bytes - 1) // self.chunk_bytes

        with self._write(self.bs0_path) as db:
            rows = db.execute(
                "SELECT * FROM math_payload WHERE digest=? "
                "ORDER BY chunk_index ASC",
                (digest,),
            ).fetchall()
            if rows:
                try:
                    self._decode_payload_rows(rows, digest, encoding=encoding)
                except MathReferenceError as exc:
                    raise MathConflictError(
                        f"payload {digest} already exists with different "
                        f"content or metadata"
                    ) from exc
                record = _row_record(rows[0])
                record["reused"] = True
                record["chunk_count"] = int(rows[0]["chunk_count"])
                record["chunk_bytes"] = max(
                    int(row["chunk_length"]) for row in rows
                )
                record.pop("blob", None)
                return record
            for index in range(chunk_count):
                start = index * self.chunk_bytes
                chunk = blob[start:start + self.chunk_bytes]
                db.execute(
                    "INSERT INTO math_payload(digest, encoding, chunk_index, "
                    "chunk_count, total_length, chunk_length, blob, "
                    "created_tick) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (digest, encoding, index, chunk_count, len(blob),
                     len(chunk), chunk, tick),
                )
        return {
            "digest": digest,
            "encoding": encoding,
            "chunk_count": chunk_count,
            "chunk_bytes": min(self.chunk_bytes, len(blob)),
            "total_length": len(blob),
            "created_tick": tick,
            "reused": False,
        }

    def get_payload(self, digest: str, *, encoding: str | None = None) -> bytes:
        _require_digest("digest", digest)
        rows = self._fetch_payload_rows(digest)
        data, _ = self._decode_payload_rows(rows, digest, encoding=encoding)
        return data

    def get_payload_record(self, digest: str) -> dict[str, Any]:
        _require_digest("digest", digest)
        rows = self._fetch_payload_rows(digest)
        data, meta = self._decode_payload_rows(rows, digest)
        meta["data"] = data
        meta["chunks"] = [
            {
                "chunk_index": int(row["chunk_index"]),
                "chunk_length": int(row["chunk_length"]),
                "digest": hashlib.sha256(bytes(row["blob"])).hexdigest(),
            }
            for row in rows
        ]
        return meta

    def list_payload_chunks(self, digest: str) -> list[dict[str, Any]]:
        _require_digest("digest", digest)
        rows = self._fetch_payload_rows(digest)
        self._decode_payload_rows(rows, digest)
        return [
            {
                "digest": digest,
                "encoding": str(row["encoding"]),
                "chunk_index": int(row["chunk_index"]),
                "chunk_count": int(row["chunk_count"]),
                "chunk_length": int(row["chunk_length"]),
                "total_length": int(row["total_length"]),
                "blob_digest": hashlib.sha256(bytes(row["blob"])).hexdigest(),
                "created_tick": int(row["created_tick"]),
            }
            for row in rows
        ]

    def _store_json_payload(self, value: Any, *, name: str,
                            tick: int) -> tuple[str, str]:
        try:
            encoded = canonical_json(value)
        except MathObjectError as exc:
            raise MathStoreError(f"{name} is not canonical JSON") from exc
        data = encoded.encode("utf-8")
        record = self.put_payload(data, encoding="canonical-json", tick=tick)
        digest = str(record["digest"])
        if digest != sha256_text(encoded):
            raise MathPayloadError(f"{name} digest changed during storage")
        return digest, encoded

    def _require_payload(self, digest: str, *, encoding: str | None = None) -> bytes:
        return self.get_payload(digest, encoding=encoding)

    # -- leaves --------------------------------------------------------------

    @staticmethod
    def _coerce_leaf(leaf: Any, overrides: dict[str, Any]) -> MathLeaf:
        if isinstance(leaf, MathLeaf):
            if not overrides:
                return leaf
            document = leaf.to_dict()
            document.update({key: value for key, value in overrides.items()
                             if value is not None})
            document.pop("schema", None)
            try:
                return MathLeaf(**document)
            except MathObjectError as exc:
                raise MathStoreError(f"invalid leaf override: {exc}") from exc
        if isinstance(leaf, Mapping):
            document = dict(leaf)
            document.update({key: value for key, value in overrides.items()
                             if value is not None})
            document.pop("schema", None)
            try:
                return MathLeaf(**document)
            except MathObjectError as exc:
                raise MathStoreError(f"invalid leaf document: {exc}") from exc
        if leaf is None:
            document = {key: value for key, value in overrides.items()
                        if value is not None}
            try:
                return MathLeaf(**document)
            except MathObjectError as exc:
                raise MathStoreError(f"invalid leaf document: {exc}") from exc
        raise MathStoreError("leaf must be a MathLeaf, mapping, or keyword fields")

    @staticmethod
    def _payload_content_digest(leaf: MathLeaf) -> str | None:
        """Digest the canonical payload, excluding the self-describing field.

        ``content["digest"]`` cannot include itself without becoming a
        fixed-point equation.  It therefore claims the SHA-256 of the
        canonical content object with that one envelope key removed.
        """
        if leaf.content is None:
            return None
        payload = {
            key: value for key, value in leaf.content.items() if key != "digest"
        }
        return sha256_text(_canonical(payload, "leaf content payload"))

    def _verify_declared_content_digest(
        self, leaf: MathLeaf, computed: str | None, *, operation: str,
    ) -> None:
        """Reject a declared content digest that is not the canonical payload.

        Legacy records created before ``metadata_version`` exist may carry an
        external payload/evidence digest instead; those remain readable and
        writable unless ``strict_content_digest=True``.  A leaf that declares
        ``metadata_version`` always opts into equality on both paths.
        """
        if leaf.content is None or computed is None:
            return
        declared = leaf.content.get("digest")
        if declared is None:
            return
        if not isinstance(declared, str) or len(declared) != 64 \
                or any(ch not in "0123456789abcdef" for ch in declared):
            raise MathContentDigestError(
                f"{operation}: leaf {leaf.leaf_id!r} version {leaf.version} "
                "content.digest must be 64 lowercase hex characters"
            )
        if declared == computed:
            return
        if self.strict_content_digest or leaf.metadata_version is not None:
            raise MathContentDigestError(
                f"{operation}: leaf {leaf.leaf_id!r} version {leaf.version} "
                f"declares content digest {declared}, but canonical payload "
                f"digest is {computed}"
            )

    def _leaf_payload(self, leaf: MathLeaf, *, tick: int) -> tuple[str | None, str | None]:
        if leaf.content is None:
            return None, None
        digest, _ = self._store_json_payload(
            leaf.content, name="leaf content", tick=tick
        )
        return digest, digest

    def _insert_leaf_version_tx(self, db: sqlite3.Connection, leaf: MathLeaf, *,
                                tick: int, content_digest: str | None,
                                payload_ref: str | None) -> str:
        try:
            document = leaf.to_dict()
            leaf_json = canonical_json(document)
        except MathObjectError as exc:
            raise MathStoreError("leaf is not canonical JSON") from exc
        leaf_digest = sha256_text(leaf_json)
        type_digest = digest_object(leaf.type)
        try:
            type_json = canonical_json(leaf.type)
        except MathObjectError as exc:
            raise MathStoreError("leaf type is not canonical JSON") from exc
        db.execute(
            "INSERT INTO math_leaf_version(leaf_id, version, leaf_digest, "
            "kind, type_json, type_digest, content_digest, payload_ref, "
            "storage_tier, leaf_json, created_tick) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'BS0DB', ?, ?)",
            (leaf.leaf_id, leaf.version, leaf_digest, leaf.kind, type_json,
             type_digest, content_digest, payload_ref, leaf_json, tick),
        )
        return leaf_digest

    def put_leaf(self, leaf: MathLeaf | Mapping[str, Any] | None = None, *,
                 expected_version: int | None = None,
                 expected_generation: int | None = None,
                 tick: int = 0,
                 **leaf_fields: Any) -> MathLeaf:
        """Store a new leaf (version 1) or replay an identical creation.

        ``leaf`` may be a :class:`MathLeaf`, a mapping with the same field
        names, or ``None`` when the fields are supplied as keywords.
        """
        _require_int("tick", tick)
        overrides = dict(leaf_fields)
        if "producer" in overrides:
            producer = overrides.pop("producer")
            provenance = dict(overrides.get("provenance") or {})
            if producer is not None:
                provenance.setdefault("producer", producer)
            overrides["provenance"] = provenance
        candidate = self._coerce_leaf(leaf, overrides)
        if expected_version is not None and expected_version not in (0, 1):
            raise StaleGenerationError(
                "expected_version for a new leaf must be 0 or 1"
            )
        if expected_generation is not None and expected_generation not in (0, 1):
            raise StaleGenerationError(
                "expected_generation for a new leaf must be 0 or 1"
            )
        if candidate.version != 1:
            raise MathStoreError("put_leaf only creates version 1")

        self._verify_declared_content_digest(
            candidate, self._payload_content_digest(candidate),
            operation="put_leaf",
        )
        content_digest, payload_ref = self._leaf_payload(candidate, tick=tick)
        leaf_json = _canonical(candidate.to_dict(), "leaf")
        leaf_digest = sha256_text(leaf_json)

        with self._write(self.mc0_path) as db:
            head = db.execute(
                "SELECT * FROM math_leaf WHERE leaf_id=?",
                (candidate.leaf_id,),
            ).fetchone()
            if head is not None:
                existing = db.execute(
                    "SELECT leaf_json, leaf_digest FROM math_leaf_version "
                    "WHERE leaf_id=? AND version=?",
                    (candidate.leaf_id, 1),
                ).fetchone()
                if (existing is not None
                        and str(existing["leaf_digest"]) == leaf_digest
                        and str(existing["leaf_json"]) == leaf_json):
                    replay = True
                else:
                    raise MathConflictError(
                        f"leaf {candidate.leaf_id!r} already exists with "
                        "different content or provenance"
                    )
            else:
                replay = False
                db.execute(
                    "INSERT INTO math_leaf(leaf_id, current_version, "
                    "generation, kind, type_digest, content_digest, status, "
                    "created_tick, updated_tick) "
                    "VALUES (?, 1, 1, ?, ?, ?, ?, ?, ?)",
                    (candidate.leaf_id, candidate.kind,
                     digest_object(candidate.type), content_digest,
                     candidate.status, tick, tick),
                )
                self._insert_leaf_version_tx(
                    db, candidate, tick=tick,
                    content_digest=content_digest, payload_ref=payload_ref,
                )
                self._sync_mapping_tx(
                    db, "leaf", candidate.leaf_id, 1, leaf_digest, 1, tick
                )
        if not replay:
            self.append_event(
                "commit", "leaf", candidate.leaf_id, version=1, generation=1,
                digest=leaf_digest,
                payload={"operation": "put_leaf", "content_digest": content_digest},
                tick=tick,
            )
        return self.get_leaf(candidate.leaf_id, version=1)

    def put_version(self, leaf_id: str, content: Mapping[str, Any] | None = None,
                    parents: Iterable[Mapping[str, Any]] | None = None, *,
                    operation: Mapping[str, Any] | None = None,
                    metadata: Mapping[str, Any] | None = None,
                    expected_version: int | None = None,
                    expected_generation: int | None = None,
                    tick: int = 0) -> MathLeaf:
        """Append an immutable leaf version and CAS the current pointer.

        ``expected_version``/``expected_generation`` default to the values
        read at the start of the call.  Passing either explicitly makes a
        stale writer fail with :class:`StaleGenerationError`; the old pointer
        remains active and no version row is written.
        """
        _require_text("leaf_id", leaf_id, maximum=200)
        _require_int("tick", tick)
        current = self.get_leaf(leaf_id)
        head = self.get_leaf_meta(leaf_id)
        exp_version = current.version if expected_version is None else expected_version
        exp_generation = (head["generation"] if expected_generation is None
                          else expected_generation)
        _require_int("expected_version", exp_version, minimum=1)
        _require_int("expected_generation", exp_generation, minimum=1)

        try:
            next_leaf = current.next_version(
                content=None if content is None else dict(content),
                parents=parents,
                operation=None if operation is None else dict(operation),
                metadata=None if metadata is None else dict(metadata),
            )
        except MathObjectError as exc:
            raise MathStoreError(f"invalid next leaf version: {exc}") from exc
        self._verify_declared_content_digest(
            next_leaf, self._payload_content_digest(next_leaf),
            operation="put_version",
        )
        content_digest, payload_ref = self._leaf_payload(next_leaf, tick=tick)
        leaf_json = _canonical(next_leaf.to_dict(), "leaf")
        leaf_digest = sha256_text(leaf_json)
        new_generation = exp_generation + 1

        with self._write(self.mc0_path) as db:
            head_row = db.execute(
                "SELECT * FROM math_leaf WHERE leaf_id=?", (leaf_id,)
            ).fetchone()
            if head_row is None:
                raise MathReferenceError(f"unknown leaf {leaf_id!r}")
            if (int(head_row["current_version"]) != exp_version
                    or int(head_row["generation"]) != exp_generation):
                raise StaleGenerationError(
                    f"leaf {leaf_id!r} is at version "
                    f"{head_row['current_version']} generation "
                    f"{head_row['generation']}, not version {exp_version} "
                    f"generation {exp_generation}"
                )
            if next_leaf.version != exp_version + 1:
                raise MathStoreError("next leaf version is not contiguous")
            exists = db.execute(
                "SELECT 1 FROM math_leaf_version WHERE leaf_id=? AND version=?",
                (leaf_id, next_leaf.version),
            ).fetchone()
            if exists is not None:
                raise MathConflictError(
                    f"leaf {leaf_id!r} version {next_leaf.version} already exists"
                )
            self._insert_leaf_version_tx(
                db, next_leaf, tick=tick,
                content_digest=content_digest, payload_ref=payload_ref,
            )
            db.execute(
                "UPDATE math_leaf SET current_version=?, generation=?, "
                "kind=?, type_digest=?, content_digest=?, status=?, "
                "updated_tick=? WHERE leaf_id=?",
                (next_leaf.version, new_generation, next_leaf.kind,
                 digest_object(next_leaf.type), content_digest,
                 next_leaf.status, tick, leaf_id),
            )
            self._sync_mapping_tx(
                db, "leaf", leaf_id, next_leaf.version, leaf_digest,
                new_generation, tick,
            )
        self.append_event(
            "commit", "leaf", leaf_id, version=next_leaf.version,
            generation=new_generation, digest=leaf_digest,
            payload={"operation": "put_version",
                     "previous_version": exp_version,
                     "content_digest": content_digest},
            tick=tick,
        )
        return self.get_leaf(leaf_id, version=next_leaf.version)

    def _leaf_version_row(self, leaf_id: str,
                          version: int | None) -> sqlite3.Row:
        with self._connect(self.mc0_path) as db:
            if version is None:
                head = db.execute(
                    "SELECT current_version FROM math_leaf WHERE leaf_id=?",
                    (leaf_id,),
                ).fetchone()
                if head is None:
                    raise MathReferenceError(f"unknown leaf {leaf_id!r}")
                version = int(head["current_version"])
            row = db.execute(
                "SELECT * FROM math_leaf_version WHERE leaf_id=? AND version=?",
                (leaf_id, version),
            ).fetchone()
        if row is None:
            raise MathReferenceError(
                f"leaf {leaf_id!r} version {version} is missing"
            )
        return row

    def get_leaf(self, leaf_id: str, version: int | None = None) -> MathLeaf:
        """Load and verify one immutable leaf version (current by default)."""
        _require_text("leaf_id", leaf_id, maximum=200)
        if version is not None:
            _require_int("version", version, minimum=1)
        row = self._leaf_version_row(leaf_id, version)
        try:
            stored_json = str(row["leaf_json"])
            document = json.loads(stored_json)
            if canonical_json(document) != stored_json:
                raise MathReferenceError(
                    f"leaf {leaf_id!r} version {row['version']} is not canonical"
                )
        except MathReferenceError:
            raise
        except (TypeError, ValueError) as exc:
            raise MathReferenceError(
                f"leaf {leaf_id!r} version {row['version']} has invalid JSON"
            ) from exc
        except MathObjectError as exc:
            raise MathReferenceError(
                f"leaf {leaf_id!r} version {row['version']} is not canonical"
            ) from exc
        try:
            leaf = MathLeaf(**{key: value for key, value in document.items()
                               if key != "schema"})
        except MathObjectError as exc:
            raise MathReferenceError(
                f"leaf {leaf_id!r} version {row['version']} is invalid"
            ) from exc
        computed = leaf.digest()
        if computed != str(row["leaf_digest"]):
            raise MathReferenceError(
                f"leaf {leaf_id!r} version {row['version']} digest mismatch"
            )
        if digest_object(leaf.type) != str(row["type_digest"]):
            raise MathReferenceError(
                f"leaf {leaf_id!r} version {row['version']} type digest mismatch"
            )
        content_digest = row["content_digest"]
        payload_ref = row["payload_ref"]
        if leaf.content is None:
            if content_digest is not None or payload_ref is not None:
                raise MathReferenceError(
                    f"leaf {leaf_id!r} version {row['version']} has an "
                    "unexpected payload reference"
                )
        else:
            if content_digest is None or payload_ref is None:
                raise MathReferenceError(
                    f"leaf {leaf_id!r} version {row['version']} has no "
                    "content payload reference"
                )
            payload = self._require_payload(
                str(payload_ref), encoding="canonical-json"
            )
            if hashlib.sha256(payload).hexdigest() != str(content_digest):
                raise MathPayloadError(
                    f"leaf {leaf_id!r} version {row['version']} content "
                    "digest mismatch"
                )
            try:
                decoded = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise MathPayloadError(
                    f"leaf {leaf_id!r} version {row['version']} payload is "
                    "not canonical JSON"
                ) from exc
            if decoded != leaf.content:
                raise MathPayloadError(
                    f"leaf {leaf_id!r} version {row['version']} payload does "
                    "not match the leaf content"
                )
        self._verify_declared_content_digest(
            leaf, self._payload_content_digest(leaf), operation="get_leaf",
        )
        return leaf

    def get_leaf_meta(self, leaf_id: str) -> dict[str, Any]:
        """Return current pointer metadata for a leaf (no payload load)."""
        _require_text("leaf_id", leaf_id, maximum=200)
        with self._connect(self.mc0_path) as db:
            row = db.execute(
                "SELECT * FROM math_leaf WHERE leaf_id=?", (leaf_id,)
            ).fetchone()
        if row is None:
            raise MathReferenceError(f"unknown leaf {leaf_id!r}")
        return _row_record(row)

    def list_versions(self, leaf_id: str, *, limit: int = 1024) -> list[dict[str, Any]]:
        """List immutable versions for a leaf in ascending version order."""
        _require_text("leaf_id", leaf_id, maximum=200)
        _require_int("limit", limit, minimum=1)
        if limit > 65536:
            raise MathStoreError("limit must be <= 65536")
        with self._connect(self.mc0_path) as db:
            head = db.execute(
                "SELECT * FROM math_leaf WHERE leaf_id=?", (leaf_id,)
            ).fetchone()
            rows = db.execute(
                "SELECT * FROM math_leaf_version WHERE leaf_id=? "
                "ORDER BY version ASC LIMIT ?",
                (leaf_id, limit),
            ).fetchall()
        if head is None:
            raise MathReferenceError(f"unknown leaf {leaf_id!r}")
        versions = []
        for row in rows:
            stored_json = str(row["leaf_json"])
            if sha256_text(stored_json) != str(row["leaf_digest"]):
                raise MathReferenceError(
                    f"leaf {leaf_id!r} version {row['version']} digest mismatch"
                )
            versions.append({
                "leaf_id": leaf_id,
                "version": int(row["version"]),
                "leaf_digest": str(row["leaf_digest"]),
                "kind": str(row["kind"]),
                "type_digest": str(row["type_digest"]),
                "content_digest": row["content_digest"],
                "payload_ref": row["payload_ref"],
                "storage_tier": str(row["storage_tier"]),
                "created_tick": int(row["created_tick"]),
                "current": int(row["version"]) == int(head["current_version"]),
                "generation": int(head["generation"]),
            })
        return versions

    def resolve(self, leaf_ref: str, required_version: int | None = None, *,
                expected_generation: int | None = None) -> MathLeaf:
        """Resolve a leaf id, ``id@version``, or ``map:<mapping_id>``.

        Historical versions remain resolvable after newer versions or a
        mapping rollback.  A mapping generation mismatch is a stale error.
        """
        _require_text("leaf_ref", leaf_ref, maximum=300)
        if required_version is not None:
            _require_int("required_version", required_version, minimum=1)
        if expected_generation is not None:
            _require_int("expected_generation", expected_generation, minimum=0)

        if leaf_ref.startswith("map:"):
            mapping_id = leaf_ref[4:]
            _require_text("mapping_id", mapping_id, maximum=300)
            mapping = self.get_mapping(mapping_id)
            if mapping["object_type"] != "leaf":
                raise MathReferenceError(
                    f"mapping {mapping_id!r} is not a leaf mapping"
                )
            if (expected_generation is not None
                    and int(mapping["generation"]) != expected_generation):
                raise StaleGenerationError(
                    f"mapping {mapping_id!r} is at generation "
                    f"{mapping['generation']}, not {expected_generation}"
                )
            version = (int(mapping["current_version"])
                       if required_version is None else required_version)
            return self.get_leaf(str(mapping["object_id"]), version)

        version = required_version
        leaf_id = leaf_ref
        if "@" in leaf_ref:
            candidate_id, _, suffix = leaf_ref.rpartition("@")
            if candidate_id and suffix.lstrip("v").isdigit():
                leaf_id = candidate_id
                embedded = int(suffix.lstrip("v"))
                if version is not None and version != embedded:
                    raise MathConflictError(
                        "required_version conflicts with the leaf reference"
                    )
                version = embedded
        elif "#" in leaf_ref:
            candidate_id, _, suffix = leaf_ref.rpartition("#")
            if candidate_id and suffix.lstrip("v").isdigit():
                leaf_id = candidate_id
                embedded = int(suffix.lstrip("v"))
                if version is not None and version != embedded:
                    raise MathConflictError(
                        "required_version conflicts with the leaf reference"
                    )
                version = embedded
        if expected_generation is not None:
            head = self.get_leaf_meta(leaf_id)
            if int(head["generation"]) != expected_generation:
                raise StaleGenerationError(
                    f"leaf {leaf_id!r} is at generation "
                    f"{head['generation']}, not {expected_generation}"
                )
        return self.get_leaf(leaf_id, version)

    # -- functions -----------------------------------------------------------

    def put_function(self, function: MathFunction, *,
                     expected_version: int | None = None,
                     expected_generation: int | None = None,
                     tick: int = 0) -> MathFunction:
        if not isinstance(function, MathFunction):
            raise MathStoreError("function must be a MathFunction")
        _require_int("tick", tick)
        try:
            document = function.to_dict()
            function_json = canonical_json(document)
        except MathObjectError as exc:
            raise MathStoreError(f"invalid function contract: {exc}") from exc
        contract_digest = function.digest()
        if function.contract_digest is not None:
            _require_digest("contract_digest", function.contract_digest)
            if function.contract_digest != contract_digest:
                raise MathStoreError(
                    "function contract_digest does not match the contract"
                )
        payload_ref, _ = self._store_json_payload(
            document, name="function contract", tick=tick
        )

        with self._write(self.mc0_path) as db:
            head = db.execute(
                "SELECT * FROM math_function WHERE function_id=?",
                (function.function_id,),
            ).fetchone()
            if head is None:
                if function.version != 1:
                    raise MathStoreError(
                        "a new function contract must start at version 1"
                    )
                if (expected_version not in (None, 0, 1)
                        or expected_generation not in (None, 0, 1)):
                    raise StaleGenerationError(
                        "new function CAS must expect version/generation 0 or 1"
                    )
                db.execute(
                    "INSERT INTO math_function(function_id, current_version, "
                    "generation, contract_digest, status, proof_status, "
                    "created_tick, updated_tick) VALUES (?, 1, 1, ?, ?, ?, ?, ?)",
                    (function.function_id, contract_digest, function.status,
                     function.proof_status, tick, tick),
                )
                db.execute(
                    "INSERT INTO math_function_version(function_id, version, "
                    "contract_digest, payload_ref, function_json, status, "
                    "proof_status, created_tick) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (function.function_id, 1, contract_digest, payload_ref,
                     function_json, function.status, function.proof_status,
                     tick),
                )
                self._sync_mapping_tx(
                    db, "function", function.function_id, 1, contract_digest,
                    1, tick,
                )
                replay = False
            else:
                existing = db.execute(
                    "SELECT * FROM math_function_version WHERE function_id=? "
                    "AND version=?",
                    (function.function_id, function.version),
                ).fetchone()
                if (existing is not None
                        and str(existing["function_json"]) == function_json
                        and str(existing["contract_digest"]) == contract_digest):
                    replay = True
                else:
                    exp_version = (int(head["current_version"])
                                   if expected_version is None
                                   else expected_version)
                    exp_generation = (int(head["generation"])
                                      if expected_generation is None
                                      else expected_generation)
                    _require_int("expected_version", exp_version, minimum=1)
                    _require_int("expected_generation", exp_generation, minimum=1)
                    if (int(head["current_version"]) != exp_version
                            or int(head["generation"]) != exp_generation):
                        raise StaleGenerationError(
                            f"function {function.function_id!r} is at version "
                            f"{head['current_version']} generation "
                            f"{head['generation']}, not version {exp_version} "
                            f"generation {exp_generation}"
                        )
                    if function.version != exp_version + 1:
                        raise MathConflictError(
                            f"function {function.function_id!r} version must "
                            f"be {exp_version + 1}"
                        )
                    new_generation = exp_generation + 1
                    db.execute(
                        "INSERT INTO math_function_version(function_id, "
                        "version, contract_digest, payload_ref, function_json, "
                        "status, proof_status, created_tick) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (function.function_id, function.version,
                         contract_digest, payload_ref, function_json,
                         function.status, function.proof_status, tick),
                    )
                    db.execute(
                        "UPDATE math_function SET current_version=?, "
                        "generation=?, contract_digest=?, status=?, "
                        "proof_status=?, updated_tick=? WHERE function_id=?",
                        (function.version, new_generation, contract_digest,
                         function.status, function.proof_status, tick,
                         function.function_id),
                    )
                    self._sync_mapping_tx(
                        db, "function", function.function_id, function.version,
                        contract_digest, new_generation, tick,
                    )
                    replay = False
        if not replay:
            self.append_event(
                "function", "function", function.function_id,
                version=function.version,
                generation=(1 if head is None else int(head["generation"]) + 1),
                digest=contract_digest, payload={"operation": "put_function"},
                tick=tick,
            )
        return self.get_function(function.function_id, function.version)

    def get_function(self, function_id: str,
                     version: int | None = None) -> MathFunction:
        _require_text("function_id", function_id, maximum=160)
        if version is not None:
            _require_int("version", version, minimum=1)
        with self._connect(self.mc0_path) as db:
            if version is None:
                head = db.execute(
                    "SELECT current_version FROM math_function WHERE function_id=?",
                    (function_id,),
                ).fetchone()
                if head is None:
                    raise MathReferenceError(
                        f"unknown function {function_id!r}"
                    )
                version = int(head["current_version"])
            row = db.execute(
                "SELECT * FROM math_function_version WHERE function_id=? "
                "AND version=?",
                (function_id, version),
            ).fetchone()
        if row is None:
            raise MathReferenceError(
                f"function {function_id!r} version {version} is missing"
            )
        payload = self._require_payload(
            str(row["payload_ref"]), encoding="canonical-json"
        )
        try:
            document = json.loads(payload.decode("utf-8"))
            if canonical_json(document) != payload.decode("utf-8"):
                raise MathReferenceError(
                    f"function {function_id!r} version {version} is not canonical"
                )
        except MathReferenceError:
            raise
        except (UnicodeDecodeError, ValueError) as exc:
            raise MathPayloadError(
                f"function {function_id!r} version {version} payload is "
                "not canonical JSON"
            ) from exc
        except MathObjectError as exc:
            raise MathReferenceError(
                f"function {function_id!r} version {version} is not canonical"
            ) from exc
        try:
            function = MathFunction(
                **{key: value for key, value in document.items()
                   if key != "schema"}
            )
        except MathObjectError as exc:
            raise MathReferenceError(
                f"function {function_id!r} version {version} is invalid"
            ) from exc
        if function.digest() != str(row["contract_digest"]):
            raise MathReferenceError(
                f"function {function_id!r} version {version} digest mismatch"
            )
        return function

    def get_function_meta(self, function_id: str) -> dict[str, Any]:
        _require_text("function_id", function_id, maximum=160)
        with self._connect(self.mc0_path) as db:
            row = db.execute(
                "SELECT * FROM math_function WHERE function_id=?",
                (function_id,),
            ).fetchone()
        if row is None:
            raise MathReferenceError(f"unknown function {function_id!r}")
        return _row_record(row)

    # -- rules ---------------------------------------------------------------

    def put_rule(self, rule: MathRule, *, expected_version: int | None = None,
                 expected_generation: int | None = None,
                 tick: int = 0) -> MathRule:
        if not isinstance(rule, MathRule):
            raise MathStoreError("rule must be a MathRule")
        _require_int("tick", tick)
        try:
            document = rule.to_dict()
            rule_json = canonical_json(document)
        except MathObjectError as exc:
            raise MathStoreError(f"invalid rule contract: {exc}") from exc
        rule_digest = sha256_text(rule_json)
        payload_ref, _ = self._store_json_payload(
            document, name="rule contract", tick=tick
        )

        with self._write(self.mc0_path) as db:
            head = db.execute(
                "SELECT * FROM math_rule WHERE rule_id=?", (rule.rule_id,)
            ).fetchone()
            if head is None:
                if rule.version != 1:
                    raise MathStoreError(
                        "a new rule contract must start at version 1"
                    )
                if (expected_version not in (None, 0, 1)
                        or expected_generation not in (None, 0, 1)):
                    raise StaleGenerationError(
                        "new rule CAS must expect version/generation 0 or 1"
                    )
                db.execute(
                    "INSERT INTO math_rule(rule_id, current_version, "
                    "generation, level, rule_digest, status, proof_status, "
                    "created_tick, updated_tick) "
                    "VALUES (?, 1, 1, ?, ?, ?, ?, ?, ?)",
                    (rule.rule_id, rule.level, rule_digest, rule.status,
                     rule.proof_status, tick, tick),
                )
                db.execute(
                    "INSERT INTO math_rule_version(rule_id, version, level, "
                    "rule_digest, payload_ref, rule_json, status, "
                    "proof_status, certificate_digest, created_tick) "
                    "VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (rule.rule_id, rule.level, rule_digest, payload_ref,
                     rule_json, rule.status, rule.proof_status,
                     rule.certificate_digest, tick),
                )
                self._sync_mapping_tx(
                    db, "rule", rule.rule_id, 1, rule_digest, 1, tick
                )
                replay = False
            else:
                existing = db.execute(
                    "SELECT * FROM math_rule_version WHERE rule_id=? "
                    "AND version=?",
                    (rule.rule_id, rule.version),
                ).fetchone()
                if (existing is not None
                        and str(existing["rule_json"]) == rule_json
                        and str(existing["rule_digest"]) == rule_digest):
                    replay = True
                else:
                    exp_version = (int(head["current_version"])
                                   if expected_version is None
                                   else expected_version)
                    exp_generation = (int(head["generation"])
                                      if expected_generation is None
                                      else expected_generation)
                    _require_int("expected_version", exp_version, minimum=1)
                    _require_int("expected_generation", exp_generation, minimum=1)
                    if (int(head["current_version"]) != exp_version
                            or int(head["generation"]) != exp_generation):
                        raise StaleGenerationError(
                            f"rule {rule.rule_id!r} is at version "
                            f"{head['current_version']} generation "
                            f"{head['generation']}, not version {exp_version} "
                            f"generation {exp_generation}"
                        )
                    if rule.version != exp_version + 1:
                        raise MathConflictError(
                            f"rule {rule.rule_id!r} version must be "
                            f"{exp_version + 1}"
                        )
                    new_generation = exp_generation + 1
                    db.execute(
                        "INSERT INTO math_rule_version(rule_id, version, "
                        "level, rule_digest, payload_ref, rule_json, status, "
                        "proof_status, certificate_digest, created_tick) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (rule.rule_id, rule.version, rule.level, rule_digest,
                         payload_ref, rule_json, rule.status,
                         rule.proof_status, rule.certificate_digest, tick),
                    )
                    db.execute(
                        "UPDATE math_rule SET current_version=?, generation=?, "
                        "level=?, rule_digest=?, status=?, proof_status=?, "
                        "updated_tick=? WHERE rule_id=?",
                        (rule.version, new_generation, rule.level, rule_digest,
                         rule.status, rule.proof_status, tick, rule.rule_id),
                    )
                    self._sync_mapping_tx(
                        db, "rule", rule.rule_id, rule.version, rule_digest,
                        new_generation, tick,
                    )
                    replay = False
        if not replay:
            self.append_event(
                "rule", "rule", rule.rule_id, version=rule.version,
                generation=(1 if head is None else int(head["generation"]) + 1),
                digest=rule_digest, payload={"operation": "put_rule"},
                tick=tick,
            )
        return self.get_rule(rule.rule_id, rule.version)

    def get_rule(self, rule_id: str, version: int | None = None) -> MathRule:
        _require_text("rule_id", rule_id, maximum=160)
        if version is not None:
            _require_int("version", version, minimum=1)
        with self._connect(self.mc0_path) as db:
            if version is None:
                head = db.execute(
                    "SELECT current_version FROM math_rule WHERE rule_id=?",
                    (rule_id,),
                ).fetchone()
                if head is None:
                    raise MathReferenceError(f"unknown rule {rule_id!r}")
                version = int(head["current_version"])
            row = db.execute(
                "SELECT * FROM math_rule_version WHERE rule_id=? AND version=?",
                (rule_id, version),
            ).fetchone()
        if row is None:
            raise MathReferenceError(
                f"rule {rule_id!r} version {version} is missing"
            )
        payload = self._require_payload(
            str(row["payload_ref"]), encoding="canonical-json"
        )
        try:
            document = json.loads(payload.decode("utf-8"))
            if canonical_json(document) != payload.decode("utf-8"):
                raise MathReferenceError(
                    f"rule {rule_id!r} version {version} is not canonical"
                )
        except MathReferenceError:
            raise
        except (UnicodeDecodeError, ValueError) as exc:
            raise MathPayloadError(
                f"rule {rule_id!r} version {version} payload is not canonical "
                "JSON"
            ) from exc
        except MathObjectError as exc:
            raise MathReferenceError(
                f"rule {rule_id!r} version {version} is not canonical"
            ) from exc
        try:
            rule = MathRule(
                **{key: value for key, value in document.items()
                   if key != "schema"}
            )
        except MathObjectError as exc:
            raise MathReferenceError(
                f"rule {rule_id!r} version {version} is invalid"
            ) from exc
        if sha256_text(canonical_json(rule.to_dict())) != str(row["rule_digest"]):
            raise MathReferenceError(
                f"rule {rule_id!r} version {version} digest mismatch"
            )
        return rule

    def get_rule_meta(self, rule_id: str) -> dict[str, Any]:
        _require_text("rule_id", rule_id, maximum=160)
        with self._connect(self.mc0_path) as db:
            row = db.execute(
                "SELECT * FROM math_rule WHERE rule_id=?", (rule_id,)
            ).fetchone()
        if row is None:
            raise MathReferenceError(f"unknown rule {rule_id!r}")
        return _row_record(row)

    # -- candidates and admissions ------------------------------------------

    def put_candidate(self, candidate: MathCandidate, *, tick: int = 0) -> MathCandidate:
        if not isinstance(candidate, MathCandidate):
            raise MathStoreError("candidate must be a MathCandidate")
        _require_int("tick", tick)
        try:
            document = candidate.to_dict()
            candidate_json = canonical_json(document)
        except MathObjectError as exc:
            raise MathStoreError(f"invalid candidate: {exc}") from exc
        candidate_digest = sha256_text(candidate_json)
        payload_ref, _ = self._store_json_payload(
            document, name="candidate", tick=tick
        )
        inserted = False
        with self._write(self.mc0_path) as db:
            row = db.execute(
                "SELECT candidate_json, candidate_digest FROM math_candidate "
                "WHERE candidate_id=?",
                (candidate.candidate_id,),
            ).fetchone()
            if row is not None:
                if (str(row["candidate_json"]) != candidate_json
                        or str(row["candidate_digest"]) != candidate_digest):
                    raise MathConflictError(
                        f"candidate {candidate.candidate_id!r} already exists "
                        "with different content"
                    )
            else:
                db.execute(
                    "INSERT INTO math_candidate(candidate_id, snapshot_id, "
                    "function_id, function_version, rank, preflight_hint, "
                    "candidate_digest, payload_ref, candidate_json, "
                    "created_tick) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (candidate.candidate_id, candidate.snapshot_id,
                     candidate.function_id, candidate.function_version,
                     candidate.rank, candidate.preflight_hint,
                     candidate_digest, payload_ref, candidate_json, tick),
                )
                inserted = True
        if inserted:
            self.append_event(
                "candidate", "candidate", candidate.candidate_id,
                version=1, digest=candidate_digest,
                payload={"snapshot_id": candidate.snapshot_id,
                         "function_id": candidate.function_id},
                tick=tick,
            )
        return self.get_candidate(candidate.candidate_id)

    def get_candidate(self, candidate_id: str) -> MathCandidate:
        _require_text("candidate_id", candidate_id, maximum=200)
        with self._connect(self.mc0_path) as db:
            row = db.execute(
                "SELECT * FROM math_candidate WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()
        if row is None:
            raise MathReferenceError(f"unknown candidate {candidate_id!r}")
        payload = self._require_payload(
            str(row["payload_ref"]), encoding="canonical-json"
        )
        if hashlib.sha256(payload).hexdigest() != str(row["candidate_digest"]):
            raise MathReferenceError(
                f"candidate {candidate_id!r} payload digest mismatch"
            )
        try:
            document = json.loads(payload.decode("utf-8"))
            candidate = MathCandidate(
                **{key: value for key, value in document.items()
                   if key != "schema"}
            )
        except (UnicodeDecodeError, ValueError, MathObjectError) as exc:
            raise MathReferenceError(
                f"candidate {candidate_id!r} payload is invalid"
            ) from exc
        return candidate

    def put_admission(self, admission: MathAdmission, *,
                      tick: int = 0) -> MathAdmission:
        if not isinstance(admission, MathAdmission):
            raise MathStoreError("admission must be a MathAdmission")
        _require_int("tick", tick)
        if admission.preflight_digest:
            _require_digest("preflight_digest", admission.preflight_digest)
        try:
            document = admission.to_dict()
            admission_json = canonical_json(document)
        except MathObjectError as exc:
            raise MathStoreError(f"invalid admission: {exc}") from exc
        admission_digest = sha256_text(admission_json)
        payload_ref, _ = self._store_json_payload(
            document, name="admission", tick=tick
        )
        inserted = False
        with self._write(self.mc0_path) as db:
            row = db.execute(
                "SELECT admission_json, admission_digest FROM math_admission "
                "WHERE admission_id=?",
                (admission.admission_id,),
            ).fetchone()
            if row is not None:
                if (str(row["admission_json"]) != admission_json
                        or str(row["admission_digest"]) != admission_digest):
                    raise MathConflictError(
                        f"admission {admission.admission_id!r} already exists "
                        "with different content"
                    )
            else:
                db.execute(
                    "INSERT INTO math_admission(admission_id, candidate_id, "
                    "snapshot_id, verdict, rule_snapshot_id, "
                    "preflight_digest, admission_digest, payload_ref, "
                    "admission_json, created_tick) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (admission.admission_id, admission.candidate_id,
                     admission.snapshot_id, admission.verdict,
                     admission.rule_snapshot_id, admission.preflight_digest,
                     admission_digest, payload_ref, admission_json, tick),
                )
                inserted = True
        if inserted:
            self.append_event(
                "admission", "admission", admission.admission_id,
                version=1, digest=admission_digest,
                payload={"candidate_id": admission.candidate_id,
                         "verdict": admission.verdict},
                tick=tick,
            )
        return self.get_admission(admission.admission_id)

    def get_admission(self, admission_id: str) -> MathAdmission:
        _require_text("admission_id", admission_id, maximum=200)
        with self._connect(self.mc0_path) as db:
            row = db.execute(
                "SELECT * FROM math_admission WHERE admission_id=?",
                (admission_id,),
            ).fetchone()
        if row is None:
            raise MathReferenceError(f"unknown admission {admission_id!r}")
        payload = self._require_payload(
            str(row["payload_ref"]), encoding="canonical-json"
        )
        if hashlib.sha256(payload).hexdigest() != str(row["admission_digest"]):
            raise MathReferenceError(
                f"admission {admission_id!r} payload digest mismatch"
            )
        try:
            document = json.loads(payload.decode("utf-8"))
            admission = MathAdmission(
                **{key: value for key, value in document.items()
                   if key != "schema"}
            )
        except (UnicodeDecodeError, ValueError, MathObjectError) as exc:
            raise MathReferenceError(
                f"admission {admission_id!r} payload is invalid"
            ) from exc
        return admission

    # -- mappings ------------------------------------------------------------

    def get_mapping(self, mapping_id: str) -> dict[str, Any]:
        _require_text("mapping_id", mapping_id, maximum=300)
        with self._connect(self.mc0_path) as db:
            row = db.execute(
                "SELECT * FROM math_mapping WHERE mapping_id=?", (mapping_id,)
            ).fetchone()
        if row is None:
            raise MathReferenceError(f"unknown mapping {mapping_id!r}")
        return _row_record(row)

    def list_mappings(self, *, object_type: str | None = None,
                      limit: int = 1024) -> list[dict[str, Any]]:
        _require_int("limit", limit, minimum=1)
        if limit > 65536:
            raise MathStoreError("limit must be <= 65536")
        query = "SELECT * FROM math_mapping"
        args: list[Any] = []
        if object_type is not None:
            if object_type not in MAPPING_OBJECT_TYPES:
                raise MathStoreError(
                    f"object_type must be one of: {', '.join(sorted(MAPPING_OBJECT_TYPES))}"
                )
            query += " WHERE object_type=?"
            args.append(object_type)
        query += " ORDER BY mapping_id ASC LIMIT ?"
        args.append(limit)
        with self._connect(self.mc0_path) as db:
            rows = db.execute(query, args).fetchall()
        return [_row_record(row) for row in rows]

    def set_mapping(self, mapping_id: str, *, object_type: str, object_id: str,
                    version: int, digest: str,
                    storage_tier: str = "BS0DB", route: str = "local",
                    expected_version: int | None = None,
                    expected_generation: int | None = None,
                    tick: int = 0) -> dict[str, Any]:
        """CAS a stable identity to an existing immutable object version."""
        _require_text("mapping_id", mapping_id, maximum=300)
        if object_type not in MAPPING_OBJECT_TYPES:
            raise MathStoreError(
                f"object_type must be one of: {', '.join(sorted(MAPPING_OBJECT_TYPES))}"
            )
        _require_text("object_id", object_id, maximum=200)
        _require_int("version", version, minimum=1)
        _require_digest("digest", digest)
        _require_text("storage_tier", storage_tier, maximum=64)
        _require_text("route", route, maximum=128)
        _require_int("tick", tick)
        if expected_version is not None:
            _require_int("expected_version", expected_version, minimum=0)
        if expected_generation is not None:
            _require_int("expected_generation", expected_generation, minimum=0)

        with self._write(self.mc0_path) as db:
            target = self._object_version_digest_tx(
                db, object_type, object_id, version
            )
            if target is None:
                raise MathReferenceError(
                    f"{object_type} {object_id!r} version {version} is missing"
                )
            if target != digest:
                raise MathConflictError(
                    f"mapping digest does not match {object_type} "
                    f"{object_id!r} version {version}"
                )
            row = db.execute(
                "SELECT * FROM math_mapping WHERE mapping_id=?", (mapping_id,)
            ).fetchone()
            if row is None:
                if (expected_version not in (None, 0)
                        or expected_generation not in (None, 0)):
                    raise StaleGenerationError(
                        "new mapping CAS must expect version/generation 0"
                    )
                new_generation = 1
                previous = None
                db.execute(
                    "INSERT INTO math_mapping(mapping_id, object_type, "
                    "object_id, current_version, generation, target_digest, "
                    "storage_tier, route, status, created_tick, updated_tick) "
                    "VALUES (?, ?, ?, ?, 1, ?, ?, ?, 'active', ?, ?)",
                    (mapping_id, object_type, object_id, version, digest,
                     storage_tier, route, tick, tick),
                )
                action = "publish"
            else:
                if (row["object_type"] != object_type
                        or row["object_id"] != object_id):
                    raise MathConflictError(
                        f"mapping {mapping_id!r} names a different object"
                    )
                exp_version = (int(row["current_version"])
                               if expected_version is None
                               else expected_version)
                exp_generation = (int(row["generation"])
                                  if expected_generation is None
                                  else expected_generation)
                if (int(row["current_version"]) != exp_version
                        or int(row["generation"]) != exp_generation):
                    raise StaleGenerationError(
                        f"mapping {mapping_id!r} is at version "
                        f"{row['current_version']} generation "
                        f"{row['generation']}, not version {exp_version} "
                        f"generation {exp_generation}"
                    )
                if (int(row["current_version"]) == version
                        and str(row["target_digest"]) == digest):
                    return _row_record(row)
                previous = int(row["current_version"])
                new_generation = exp_generation + 1
                db.execute(
                    "UPDATE math_mapping SET current_version=?, generation=?, "
                    "target_digest=?, storage_tier=?, route=?, "
                    "status='active', updated_tick=? WHERE mapping_id=?",
                    (version, new_generation, digest, storage_tier, route,
                     tick, mapping_id),
                )
                action = "update"
        self.append_event(
            "mapping", "mapping", mapping_id, version=version,
            generation=new_generation, digest=digest,
            payload={"action": action, "object_type": object_type,
                     "object_id": object_id, "previous_version": previous},
            tick=tick,
        )
        return self.get_mapping(mapping_id)

    def rollback_mapping(self, mapping_id: str, target_version: int, *,
                         expected_version: int | None = None,
                         expected_generation: int | None = None,
                         tick: int = 0) -> dict[str, Any]:
        """Move a mapping to an older existing version as a new event.

        Leaf/function/rule current heads are not rewritten; only the stable
        mapping pointer moves.  The previous pointer and all immutable
        versions remain recoverable.
        """
        _require_text("mapping_id", mapping_id, maximum=300)
        _require_int("target_version", target_version, minimum=1)
        _require_int("tick", tick)
        if expected_version is not None:
            _require_int("expected_version", expected_version, minimum=0)
        if expected_generation is not None:
            _require_int("expected_generation", expected_generation, minimum=0)

        with self._write(self.mc0_path) as db:
            row = db.execute(
                "SELECT * FROM math_mapping WHERE mapping_id=?", (mapping_id,)
            ).fetchone()
            if row is None:
                raise MathReferenceError(f"unknown mapping {mapping_id!r}")
            exp_version = (int(row["current_version"])
                           if expected_version is None else expected_version)
            exp_generation = (int(row["generation"])
                              if expected_generation is None
                              else expected_generation)
            if (int(row["current_version"]) != exp_version
                    or int(row["generation"]) != exp_generation):
                raise StaleGenerationError(
                    f"mapping {mapping_id!r} is at version "
                    f"{row['current_version']} generation {row['generation']}, "
                    f"not version {exp_version} generation {exp_generation}"
                )
            if int(row["current_version"]) == target_version:
                return _row_record(row)
            target_digest = self._object_version_digest_tx(
                db, str(row["object_type"]), str(row["object_id"]),
                target_version,
            )
            if target_digest is None:
                raise MathReferenceError(
                    f"{row['object_type']} {row['object_id']!r} version "
                    f"{target_version} is missing"
                )
            previous = int(row["current_version"])
            new_generation = exp_generation + 1
            db.execute(
                "UPDATE math_mapping SET current_version=?, generation=?, "
                "target_digest=?, status='rolled_back', updated_tick=? "
                "WHERE mapping_id=?",
                (target_version, new_generation, target_digest, tick,
                 mapping_id),
            )
            object_type = str(row["object_type"])
            object_id = str(row["object_id"])
        self.append_event(
            "rollback", "mapping", mapping_id, version=target_version,
            generation=new_generation, digest=target_digest,
            payload={"action": "rollback", "object_type": object_type,
                     "object_id": object_id, "previous_version": previous,
                     "target_version": target_version},
            tick=tick,
        )
        return self.get_mapping(mapping_id)

    def rollback(self, mapping_id: str, target_version: int, **kwargs: Any) -> dict[str, Any]:
        """Alias for :meth:`rollback_mapping`."""
        return self.rollback_mapping(mapping_id, target_version, **kwargs)

    def rollback_leaf(self, leaf_id: str, target_version: int, *,
                      expected_version: int | None = None,
                      expected_generation: int | None = None,
                      tick: int = 0) -> dict[str, Any]:
        """Rollback the leaf mapping for ``leaf_id``."""
        return self.rollback_mapping(
            self._mapping_id("leaf", leaf_id), target_version,
            expected_version=expected_version,
            expected_generation=expected_generation, tick=tick,
        )

    # -- preflight cache -----------------------------------------------------

    def put_preflight_cache(self, cache_key: str, *, snapshot_id: str,
                            candidate_id: str, verdict: str, result: Any,
                            invalidation_digest: str,
                            expires_tick: int | None = None,
                            tick: int = 0) -> dict[str, Any]:
        _require_text("cache_key", cache_key, maximum=300)
        _require_text("snapshot_id", snapshot_id, maximum=300)
        _require_text("candidate_id", candidate_id, maximum=200)
        if verdict not in VERDICTS:
            raise MathStoreError(f"unknown preflight verdict: {verdict!r}")
        _require_digest("invalidation_digest", invalidation_digest)
        _require_int("tick", tick)
        if expires_tick is not None:
            _require_int("expires_tick", expires_tick)
        result_json = _canonical(result, "preflight result")
        result_digest = sha256_text(result_json)
        with self._write(self.mc0_path) as db:
            row = db.execute(
                "SELECT generation FROM math_preflight_cache WHERE cache_key=?",
                (cache_key,),
            ).fetchone()
            if row is None:
                generation = 1
                db.execute(
                    "INSERT INTO math_preflight_cache(cache_key, snapshot_id, "
                    "candidate_id, verdict, result_digest, "
                    "invalidation_digest, result_json, generation, "
                    "created_tick, updated_tick, expires_tick) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
                    (cache_key, snapshot_id, candidate_id, verdict,
                     result_digest, invalidation_digest, result_json, tick,
                     tick, expires_tick),
                )
            else:
                generation = int(row["generation"]) + 1
                db.execute(
                    "UPDATE math_preflight_cache SET snapshot_id=?, "
                    "candidate_id=?, verdict=?, result_digest=?, "
                    "invalidation_digest=?, result_json=?, generation=?, "
                    "updated_tick=?, expires_tick=? WHERE cache_key=?",
                    (snapshot_id, candidate_id, verdict, result_digest,
                     invalidation_digest, result_json, generation, tick,
                     expires_tick, cache_key),
                )
        self.append_event(
            "preflight", "cache", cache_key, version=generation,
            generation=generation, digest=result_digest,
            payload={"snapshot_id": snapshot_id, "candidate_id": candidate_id,
                     "verdict": verdict},
            tick=tick,
        )
        return self.get_preflight_cache(
            cache_key, invalidation_digest=invalidation_digest,
        )  # type: ignore[return-value]

    def get_preflight_cache(self, cache_key: str, *,
                            invalidation_digest: str | None = None,
                            now_tick: int | None = None) -> dict[str, Any] | None:
        """Return a cache hit, or ``None`` for a miss/stale/expired entry."""
        _require_text("cache_key", cache_key, maximum=300)
        if invalidation_digest is not None:
            _require_digest("invalidation_digest", invalidation_digest)
        if now_tick is not None:
            _require_int("now_tick", now_tick)
        with self._connect(self.mc0_path) as db:
            row = db.execute(
                "SELECT * FROM math_preflight_cache WHERE cache_key=?",
                (cache_key,),
            ).fetchone()
        if row is None:
            return None
        if (invalidation_digest is not None
                and str(row["invalidation_digest"]) != invalidation_digest):
            return None
        if (now_tick is not None and row["expires_tick"] is not None
                and now_tick > int(row["expires_tick"])):
            return None
        result_json = str(row["result_json"])
        if sha256_text(result_json) != str(row["result_digest"]):
            raise MathReferenceError(
                f"preflight cache entry {cache_key!r} is corrupt"
            )
        record = _row_record(row)
        record["hit"] = True
        return record

    def invalidate_preflight_cache(self, cache_key: str, *,
                                   tick: int = 0) -> bool:
        _require_text("cache_key", cache_key, maximum=300)
        _require_int("tick", tick)
        with self._write(self.mc0_path) as db:
            cursor = db.execute(
                "DELETE FROM math_preflight_cache WHERE cache_key=?",
                (cache_key,),
            )
            removed = cursor.rowcount > 0
        if removed:
            self.append_event(
                "cache", "cache", cache_key,
                payload={"action": "invalidate"}, tick=tick,
            )
        return removed

    # -- cross-store commit intents -----------------------------------------
    #
    # BS0DB and MC0DB are separate SQLite databases, so this is not a
    # distributed transaction.  A commit is crash-consistent instead:
    #
    #   1. MC0DB records an intent with the expected base mapping and the
    #      evidence digest that must be present in BS0DB.
    #   2. BS0DB appends that evidence idempotently.
    #   3. MC0DB verifies both stores under BEGIN IMMEDIATE, CASes the active
    #      mapping, and marks the intent finalized in one local transaction.
    #
    # A pending intent with matching evidence can be finalized by recovery.
    # Missing/mismatched evidence or a stale base fails the intent without
    # changing the active mapping.  Replays are idempotent.

    @staticmethod
    def _commit_intent_id(object_type: str, object_id: str, mapping_id: str,
                          target_version: int, target_digest: str,
                          evidence_digest: str, base_version: int,
                          base_generation: int,
                          base_mapping_digest: str | None) -> str:
        return sha256_text(canonical_json({
            "object_type": object_type,
            "object_id": object_id,
            "mapping_id": mapping_id,
            "target_version": target_version,
            "target_digest": target_digest,
            "evidence_digest": evidence_digest,
            "base_version": base_version,
            "base_generation": base_generation,
            "base_mapping_digest": base_mapping_digest,
        }))

    @staticmethod
    def _intent_matches(row: sqlite3.Row | Mapping[str, Any],
                        **fields: Any) -> bool:
        for name, value in fields.items():
            if value is not None and row[name] != value:
                return False
        return True

    def begin_commit_intent(
        self, object_type: str, object_id: str,
        target_version: int | None = None,
        target_digest: str | None = None,
        evidence_digest: str | None = None, *,
        expected_version: int | None = None,
        expected_generation: int | None = None,
        expected_mapping_digest: str | None = None,
        mapping_id: str | None = None,
        intent_id: str | None = None,
        tick: int = 0,
        version: int | None = None,
        digest: str | None = None,
        base_version: int | None = None,
        base_generation: int | None = None,
        base_digest: str | None = None,
    ) -> dict[str, Any]:
        """Record a pending cross-store commit intent in MC0DB.

        ``expected_version``/``expected_generation`` (aliases ``base_*``)
        default to the current mapping pointer, or 0/0 when no mapping exists.
        The target immutable version need not exist yet; finalization verifies
        it.  Repeating the same intent is idempotent.
        """
        if object_type not in MAPPING_OBJECT_TYPES:
            raise MathStoreError(
                f"object_type must be one of: "
                f"{', '.join(sorted(MAPPING_OBJECT_TYPES))}"
            )
        _require_text("object_id", object_id, maximum=200)
        if target_version is None:
            target_version = version
        if target_digest is None:
            target_digest = digest
        if target_version is None:
            raise MathStoreError("target_version is required")
        if target_digest is None:
            raise MathStoreError("target_digest is required")
        if evidence_digest is None:
            raise MathStoreError("evidence_digest is required")
        _require_int("target_version", target_version, minimum=1)
        _require_digest("target_digest", target_digest)
        _require_digest("evidence_digest", evidence_digest)
        _require_int("tick", tick)
        if expected_version is None:
            expected_version = base_version
        if expected_generation is None:
            expected_generation = base_generation
        if expected_mapping_digest is None:
            expected_mapping_digest = base_digest
        if expected_version is not None:
            _require_int("expected_version", expected_version, minimum=0)
        if expected_generation is not None:
            _require_int(
                "expected_generation", expected_generation, minimum=0
            )
        if expected_mapping_digest is not None:
            _require_digest(
                "expected_mapping_digest", expected_mapping_digest
            )
        if mapping_id is None:
            mapping_id = self._mapping_id(object_type, object_id)
        _require_text("mapping_id", mapping_id, maximum=300)
        if intent_id is not None:
            _require_text("intent_id", intent_id, maximum=300)

        with self._write(self.mc0_path) as db:
            if intent_id is not None:
                existing = db.execute(
                    "SELECT * FROM math_commit_intent WHERE intent_id=?",
                    (intent_id,),
                ).fetchone()
                if existing is not None:
                    if not self._intent_matches(
                        existing, object_type=object_type,
                        object_id=object_id, mapping_id=mapping_id,
                        target_version=target_version,
                        target_digest=target_digest,
                        evidence_digest=evidence_digest,
                        base_version=expected_version,
                        base_generation=expected_generation,
                        base_mapping_digest=expected_mapping_digest,
                    ):
                        raise MathConflictError(
                            f"commit intent {intent_id!r} already exists with "
                            "different bindings"
                        )
                    return _row_record(existing)

            mapping = db.execute(
                "SELECT * FROM math_mapping WHERE mapping_id=?",
                (mapping_id,),
            ).fetchone()
            if mapping is None:
                if expected_version is None:
                    expected_version = 0
                if expected_generation is None:
                    expected_generation = 0
                if expected_mapping_digest is None:
                    expected_mapping_digest = None
            else:
                if (str(mapping["object_type"]) != object_type
                        or str(mapping["object_id"]) != object_id):
                    raise MathConflictError(
                        f"mapping {mapping_id!r} names a different object"
                    )
                if expected_version is None:
                    expected_version = int(mapping["current_version"])
                if expected_generation is None:
                    expected_generation = int(mapping["generation"])
                if expected_mapping_digest is None:
                    expected_mapping_digest = str(mapping["target_digest"])
            if intent_id is None:
                intent_id = self._commit_intent_id(
                    object_type, object_id, mapping_id, target_version,
                    target_digest, evidence_digest, expected_version,
                    expected_generation, expected_mapping_digest,
                )
            existing = db.execute(
                "SELECT * FROM math_commit_intent WHERE intent_id=?",
                (intent_id,),
            ).fetchone()
            if existing is not None:
                if not self._intent_matches(
                    existing, object_type=object_type, object_id=object_id,
                    mapping_id=mapping_id, target_version=target_version,
                    target_digest=target_digest,
                    evidence_digest=evidence_digest,
                    base_version=expected_version,
                    base_generation=expected_generation,
                    base_mapping_digest=expected_mapping_digest,
                ):
                    raise MathConflictError(
                        f"commit intent {intent_id!r} already exists with "
                        "different bindings"
                    )
                return _row_record(existing)

            db.execute(
                "INSERT INTO math_commit_intent(intent_id, mapping_id, "
                "object_type, object_id, target_version, target_digest, "
                "evidence_digest, base_version, base_generation, "
                "base_mapping_digest, state, created_tick, updated_tick) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
                (intent_id, mapping_id, object_type, object_id,
                 target_version, target_digest, evidence_digest,
                 expected_version, expected_generation,
                 expected_mapping_digest, tick, tick),
            )
            row = db.execute(
                "SELECT * FROM math_commit_intent WHERE intent_id=?",
                (intent_id,),
            ).fetchone()
        return _row_record(row)

    def _load_commit_evidence(self,
                              intent_id: str) -> dict[str, Any] | None:
        with self._connect(self.bs0_path) as db:
            row = db.execute(
                "SELECT * FROM math_commit_evidence WHERE intent_id=?",
                (intent_id,),
            ).fetchone()
        return None if row is None else _row_record(row)

    def append_commit_evidence(self, intent_id: str,
                               evidence: Any = None, *,
                               payload: Any = None,
                               tick: int = 0) -> dict[str, Any]:
        """Append canonical evidence to BS0DB for an existing intent.

        The evidence digest must equal the digest declared by the intent.  A
        byte-identical replay returns the stored row without appending again.
        """
        _require_text("intent_id", intent_id, maximum=300)
        _require_int("tick", tick)
        if evidence is None:
            evidence = payload
        if evidence is None:
            raise MathStoreError("evidence is required")
        evidence_json = _canonical(evidence, "commit evidence")
        evidence_digest = sha256_text(evidence_json)

        with self._connect(self.mc0_path) as db:
            intent_row = db.execute(
                "SELECT * FROM math_commit_intent WHERE intent_id=?",
                (intent_id,),
            ).fetchone()
        if intent_row is None:
            raise MathReferenceError(f"unknown commit intent {intent_id!r}")
        intent = _row_record(intent_row)
        if evidence_digest != str(intent["evidence_digest"]):
            raise MathConflictError(
                f"evidence digest {evidence_digest} does not match commit "
                f"intent {intent_id!r} evidence digest "
                f"{intent['evidence_digest']}"
            )

        with self._write(self.bs0_path) as db:
            existing = db.execute(
                "SELECT * FROM math_commit_evidence WHERE intent_id=?",
                (intent_id,),
            ).fetchone()
            if existing is not None:
                same = (
                    str(existing["evidence_digest"]) == evidence_digest
                    and str(existing["evidence_json"]) == evidence_json
                    and str(existing["mapping_id"]) == str(intent["mapping_id"])
                    and str(existing["object_type"])
                    == str(intent["object_type"])
                    and str(existing["object_id"]) == str(intent["object_id"])
                    and int(existing["target_version"])
                    == int(intent["target_version"])
                    and str(existing["target_digest"])
                    == str(intent["target_digest"])
                )
                if not same:
                    raise MathConflictError(
                        f"commit evidence for intent {intent_id!r} already "
                        "exists with different content"
                    )
                record = _row_record(existing)
                record["reused"] = True
                return record
            db.execute(
                "INSERT INTO math_commit_evidence(intent_id, evidence_digest, "
                "mapping_id, object_type, object_id, target_version, "
                "target_digest, evidence_json, created_tick) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (intent_id, evidence_digest, str(intent["mapping_id"]),
                 str(intent["object_type"]), str(intent["object_id"]),
                 int(intent["target_version"]), str(intent["target_digest"]),
                 evidence_json, tick),
            )
            row = db.execute(
                "SELECT * FROM math_commit_evidence WHERE intent_id=?",
                (intent_id,),
            ).fetchone()
            record = _row_record(row)
            record["reused"] = False
            return record

    def get_commit_intent(self, intent_id: str) -> dict[str, Any]:
        _require_text("intent_id", intent_id, maximum=300)
        with self._connect(self.mc0_path) as db:
            row = db.execute(
                "SELECT * FROM math_commit_intent WHERE intent_id=?",
                (intent_id,),
            ).fetchone()
        if row is None:
            raise MathReferenceError(f"unknown commit intent {intent_id!r}")
        return _row_record(row)

    def get_intent(self, intent_id: str) -> dict[str, Any]:
        """Alias for :meth:`get_commit_intent`."""
        return self.get_commit_intent(intent_id)

    def list_commit_intents(self, *, state: str | None = None,
                            limit: int = 1024) -> list[dict[str, Any]]:
        _require_int("limit", limit, minimum=1)
        if limit > 65536:
            raise MathStoreError("limit must be <= 65536")
        query = "SELECT * FROM math_commit_intent"
        args: list[Any] = []
        if state is not None:
            if state not in COMMIT_INTENT_STATES:
                raise MathStoreError(
                    f"state must be one of: "
                    f"{', '.join(sorted(COMMIT_INTENT_STATES))}"
                )
            query += " WHERE state=?"
            args.append(state)
        query += " ORDER BY created_tick ASC, intent_id ASC LIMIT ?"
        args.append(limit)
        with self._connect(self.mc0_path) as db:
            rows = db.execute(query, args).fetchall()
        return [_row_record(row) for row in rows]

    def list_pending_intents(self, *, limit: int = 1024) -> list[dict[str, Any]]:
        """List pending intents in recovery order."""
        return self.list_commit_intents(state="pending", limit=limit)

    def get_commit_evidence(self, intent_id: str) -> dict[str, Any]:
        _require_text("intent_id", intent_id, maximum=300)
        record = self._load_commit_evidence(intent_id)
        if record is None:
            raise MathReferenceError(
                f"commit evidence for intent {intent_id!r} is missing"
            )
        actual = sha256_text(str(record["evidence_json"]))
        if actual != str(record["evidence_digest"]):
            raise MathReferenceError(
                f"commit evidence for intent {intent_id!r} is corrupt"
            )
        return record

    def get_evidence(self, intent_id: str) -> dict[str, Any]:
        """Alias for :meth:`get_commit_evidence`."""
        return self.get_commit_evidence(intent_id)

    def list_commit_evidence(self, *, limit: int = 1024) -> list[dict[str, Any]]:
        _require_int("limit", limit, minimum=1)
        if limit > 65536:
            raise MathStoreError("limit must be <= 65536")
        with self._connect(self.bs0_path) as db:
            rows = db.execute(
                "SELECT * FROM math_commit_evidence "
                "ORDER BY created_tick ASC, intent_id ASC LIMIT ?",
                (limit,),
            ).fetchall()
        records = []
        for row in rows:
            record = _row_record(row)
            if sha256_text(str(record["evidence_json"])) != str(
                    record["evidence_digest"]):
                raise MathReferenceError(
                    f"commit evidence for intent {record['intent_id']!r} "
                    "is corrupt"
                )
            records.append(record)
        return records

    @staticmethod
    def _verify_commit_evidence_record(intent: Mapping[str, Any],
                                       evidence: Mapping[str, Any]) -> None:
        if str(evidence["evidence_digest"]) != str(intent["evidence_digest"]):
            raise MathCommitError(
                f"commit intent {intent['intent_id']!r} evidence digest "
                "does not match the intent"
            )
        if (str(evidence["mapping_id"]) != str(intent["mapping_id"])
                or str(evidence["object_type"]) != str(intent["object_type"])
                or str(evidence["object_id"]) != str(intent["object_id"])
                or int(evidence["target_version"])
                != int(intent["target_version"])
                or str(evidence["target_digest"])
                != str(intent["target_digest"])):
            raise MathCommitError(
                f"commit evidence for intent {intent['intent_id']!r} names "
                "different target bindings"
            )
        actual = sha256_text(str(evidence["evidence_json"]))
        if actual != str(evidence["evidence_digest"]):
            raise MathReferenceError(
                f"commit evidence for intent {intent['intent_id']!r} is "
                "corrupt"
            )

    def verify_commit_evidence(self, intent_id: str, *,
                               evidence_digest: str | None = None) -> bool:
        """Verify that BS0DB evidence matches the MC0DB intent bindings."""
        _require_text("intent_id", intent_id, maximum=300)
        if evidence_digest is not None:
            _require_digest("evidence_digest", evidence_digest)
        intent = self.get_commit_intent(intent_id)
        evidence = self._load_commit_evidence(intent_id)
        if evidence is None:
            raise MathReferenceError(
                f"commit evidence for intent {intent_id!r} is missing"
            )
        if (evidence_digest is not None
                and str(evidence["evidence_digest"]) != evidence_digest):
            raise MathCommitError(
                f"commit evidence for intent {intent_id!r} has digest "
                f"{evidence['evidence_digest']}, not {evidence_digest}"
            )
        self._verify_commit_evidence_record(intent, evidence)
        return True

    def verify_evidence(self, intent_id: str, *,
                        evidence_digest: str | None = None) -> bool:
        """Alias for :meth:`verify_commit_evidence`."""
        return self.verify_commit_evidence(
            intent_id, evidence_digest=evidence_digest
        )

    def _check_commit_base_tx(self, intent: Mapping[str, Any],
                              mapping: sqlite3.Row | None) -> None:
        base_version = int(intent["base_version"])
        base_generation = int(intent["base_generation"])
        base_digest = intent["base_mapping_digest"]
        if mapping is None:
            if base_version != 0 or base_generation != 0:
                raise StaleGenerationError(
                    f"mapping {intent['mapping_id']!r} is absent, not at "
                    f"version {base_version} generation {base_generation}"
                )
            if base_digest is not None:
                raise StaleGenerationError(
                    f"mapping {intent['mapping_id']!r} is absent, not at "
                    f"digest {base_digest}"
                )
            return
        if (str(mapping["object_type"]) != str(intent["object_type"])
                or str(mapping["object_id"]) != str(intent["object_id"])):
            raise MathConflictError(
                f"mapping {intent['mapping_id']!r} names a different object"
            )
        if (int(mapping["current_version"]) != base_version
                or int(mapping["generation"]) != base_generation):
            raise StaleGenerationError(
                f"mapping {intent['mapping_id']!r} is at version "
                f"{mapping['current_version']} generation "
                f"{mapping['generation']}, not version {base_version} "
                f"generation {base_generation}"
            )
        if (base_digest is not None
                and str(mapping["target_digest"]) != str(base_digest)):
            raise StaleGenerationError(
                f"mapping {intent['mapping_id']!r} is at digest "
                f"{mapping['target_digest']}, not {base_digest}"
            )

    def _finalize_commit_intent_tx(
        self, intent_id: str, tick: int,
    ) -> tuple[dict[str, Any], MathStoreError | None]:
        with self._write(self.mc0_path) as db:
            row = db.execute(
                "SELECT * FROM math_commit_intent WHERE intent_id=?",
                (intent_id,),
            ).fetchone()
            if row is None:
                raise MathReferenceError(
                    f"unknown commit intent {intent_id!r}"
                )
            intent = _row_record(row)
            if intent["state"] == "finalized":
                return intent, None
            if intent["state"] == "failed":
                return intent, MathCommitError(
                    f"commit intent {intent_id!r} already failed: "
                    f"{intent.get('failure_reason') or 'unknown reason'}"
                )

            try:
                target = self._object_version_digest_tx(
                    db, str(intent["object_type"]), str(intent["object_id"]),
                    int(intent["target_version"]),
                )
                if target is None:
                    raise MathReferenceError(
                        f"{intent['object_type']} {intent['object_id']!r} "
                        f"version {intent['target_version']} is missing"
                    )
                if target != str(intent["target_digest"]):
                    raise MathCommitError(
                        f"target {intent['object_type']} "
                        f"{intent['object_id']!r} version "
                        f"{intent['target_version']} digest is {target}, "
                        f"not {intent['target_digest']}"
                    )
                evidence = self._load_commit_evidence(intent_id)
                if evidence is None:
                    raise MathReferenceError(
                        f"commit evidence for intent {intent_id!r} is missing"
                    )
                self._verify_commit_evidence_record(intent, evidence)
                mapping = db.execute(
                    "SELECT * FROM math_mapping WHERE mapping_id=?",
                    (str(intent["mapping_id"]),),
                ).fetchone()
                self._check_commit_base_tx(intent, mapping)
            except MathStoreError as exc:
                reason = str(exc) or type(exc).__name__
                db.execute(
                    "UPDATE math_commit_intent SET state='failed', "
                    "failure_reason=?, updated_tick=? "
                    "WHERE intent_id=? AND state='pending'",
                    (reason[:512], tick, intent_id),
                )
                failed = db.execute(
                    "SELECT * FROM math_commit_intent WHERE intent_id=?",
                    (intent_id,),
                ).fetchone()
                return _row_record(failed), exc

            if mapping is None:
                new_generation = 1
                db.execute(
                    "INSERT INTO math_mapping(mapping_id, object_type, "
                    "object_id, current_version, generation, target_digest, "
                    "storage_tier, route, status, created_tick, updated_tick) "
                    "VALUES (?, ?, ?, ?, 1, ?, 'BS0DB', 'local', 'active', "
                    "?, ?)",
                    (str(intent["mapping_id"]),
                     str(intent["object_type"]), str(intent["object_id"]),
                     int(intent["target_version"]),
                     str(intent["target_digest"]), tick, tick),
                )
            else:
                same_target = (
                    int(mapping["current_version"])
                    == int(intent["target_version"])
                    and str(mapping["target_digest"])
                    == str(intent["target_digest"])
                )
                if same_target:
                    new_generation = int(mapping["generation"])
                else:
                    new_generation = int(mapping["generation"]) + 1
                    db.execute(
                        "UPDATE math_mapping SET current_version=?, "
                        "generation=?, target_digest=?, status='active', "
                        "updated_tick=? WHERE mapping_id=?",
                        (int(intent["target_version"]), new_generation,
                         str(intent["target_digest"]), tick,
                         str(intent["mapping_id"])),
                    )
            db.execute(
                "UPDATE math_commit_intent SET state='finalized', "
                "evidence_ref=?, failure_reason=NULL, updated_tick=?, "
                "finalized_tick=? WHERE intent_id=? AND state='pending'",
                (str(intent["evidence_digest"]), tick, tick, intent_id),
            )
            finalized = db.execute(
                "SELECT * FROM math_commit_intent WHERE intent_id=?",
                (intent_id,),
            ).fetchone()
            return _row_record(finalized), None

    def finalize_commit_intent(self, intent_id: str, *,
                               tick: int = 0) -> dict[str, Any]:
        """Atomically verify evidence/base state, CAS the mapping, finalize.

        A pending intent whose evidence and base generation match is committed
        in one MC0DB transaction.  Any mismatch fails the intent and leaves the
        previous active mapping untouched.  Replaying a finalized intent is a
        no-op that returns the finalized record.
        """
        _require_text("intent_id", intent_id, maximum=300)
        _require_int("tick", tick)
        record, failure = self._finalize_commit_intent_tx(intent_id, tick)
        if failure is not None:
            raise failure
        return record

    def finalize_intent(self, intent_id: str, *,
                        tick: int = 0) -> dict[str, Any]:
        """Alias for :meth:`finalize_commit_intent`."""
        return self.finalize_commit_intent(intent_id, tick=tick)

    def fail_commit_intent(self, intent_id: str, reason: str = "aborted", *,
                           tick: int = 0) -> dict[str, Any]:
        """Mark a pending intent failed without touching the active mapping."""
        _require_text("intent_id", intent_id, maximum=300)
        _require_text("reason", reason, maximum=512)
        _require_int("tick", tick)
        with self._write(self.mc0_path) as db:
            row = db.execute(
                "SELECT * FROM math_commit_intent WHERE intent_id=?",
                (intent_id,),
            ).fetchone()
            if row is None:
                raise MathReferenceError(
                    f"unknown commit intent {intent_id!r}"
                )
            intent = _row_record(row)
            if intent["state"] == "finalized":
                raise MathCommitError(
                    f"commit intent {intent_id!r} is already finalized"
                )
            if intent["state"] == "failed":
                return intent
            db.execute(
                "UPDATE math_commit_intent SET state='failed', "
                "failure_reason=?, updated_tick=? WHERE intent_id=?",
                (reason, tick, intent_id),
            )
            failed = db.execute(
                "SELECT * FROM math_commit_intent WHERE intent_id=?",
                (intent_id,),
            ).fetchone()
        return _row_record(failed)

    def abort_commit_intent(self, intent_id: str, reason: str = "aborted", *,
                            tick: int = 0) -> dict[str, Any]:
        """Alias for :meth:`fail_commit_intent`."""
        return self.fail_commit_intent(intent_id, reason, tick=tick)

    def recover_pending_intents(self, *, tick: int = 0,
                                limit: int = 1024) -> list[dict[str, Any]]:
        """Finalize or fail every pending intent, returning the outcomes.

        Matching evidence commits the mapping; missing/mismatched evidence or
        a stale base marks that intent failed and leaves the mapping intact.
        """
        _require_int("tick", tick)
        _require_int("limit", limit, minimum=1)
        if limit > 65536:
            raise MathStoreError("limit must be <= 65536")
        with self._connect(self.mc0_path) as db:
            rows = db.execute(
                "SELECT intent_id FROM math_commit_intent "
                "WHERE state='pending' ORDER BY created_tick ASC, "
                "intent_id ASC LIMIT ?",
                (limit,),
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            intent_id = str(row["intent_id"])
            try:
                record, failure = self._finalize_commit_intent_tx(
                    intent_id, tick
                )
            except MathStoreError as exc:
                results.append({
                    "intent_id": intent_id,
                    "state": "pending",
                    "recovered": False,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                })
                continue
            outcome = dict(record)
            outcome["recovered"] = failure is None
            if failure is not None:
                outcome["error"] = str(failure)
                outcome["error_type"] = type(failure).__name__
            results.append(outcome)
        return results

    def recover_intents(self, *, tick: int = 0,
                        limit: int = 1024) -> list[dict[str, Any]]:
        """Alias for :meth:`recover_pending_intents`."""
        return self.recover_pending_intents(tick=tick, limit=limit)

    # Aliases kept intentionally small and explicit for callers that use the
    # shorter §9.7 vocabulary.
    begin_intent = begin_commit_intent
    begin_commit = begin_commit_intent
    append_evidence = append_commit_evidence
    append_intent_evidence = append_commit_evidence
    verify_intent_evidence = verify_commit_evidence
    finalize_commit = finalize_commit_intent
    fail_intent = fail_commit_intent
    list_intents = list_commit_intents
    pending_intents = list_pending_intents
    list_evidence = list_commit_evidence
    recover_commit_intents = recover_pending_intents
    recover = recover_pending_intents

    # -- events --------------------------------------------------------------

    def append_event(self, event_type: str, object_type: str, object_id: str,
                     *, version: int | None = None,
                     generation: int | None = None,
                     digest: str | None = None,
                     actor: str = "math_store", payload: Any = None,
                     tick: int = 0) -> dict[str, Any]:
        """Append an immutable math event to BS0DB."""
        if event_type not in EVENT_TYPES:
            raise MathStoreError(f"unknown math event type: {event_type!r}")
        _require_text("object_type", object_type, maximum=64)
        _require_text("object_id", object_id, maximum=300)
        _require_text("actor", actor, maximum=128)
        _require_int("tick", tick)
        if version is not None:
            _require_int("version", version, minimum=0)
        if generation is not None:
            _require_int("generation", generation, minimum=0)
        if digest is not None:
            _require_digest("digest", digest)
        payload_json = _canonical({} if payload is None else payload,
                                  "event payload")
        with self._write(self.bs0_path) as db:
            next_seq = int(db.execute(
                "SELECT COALESCE(MAX(event_seq), 0) + 1 FROM math_event"
            ).fetchone()[0])
            event_id = hashlib.sha256(canonical_json({
                "event_type": event_type, "object_type": object_type,
                "object_id": object_id, "version": version,
                "generation": generation, "digest": digest, "actor": actor,
                "tick": tick, "payload": payload_json, "seq": next_seq,
            }).encode("utf-8")).hexdigest()
            db.execute(
                "INSERT INTO math_event(event_seq, event_id, event_type, "
                "object_type, object_id, version, generation, digest, actor, "
                "tick, payload_json, created_tick) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (next_seq, event_id, event_type, object_type, object_id,
                 version, generation, digest, actor, tick, payload_json, tick),
            )
            row = db.execute(
                "SELECT * FROM math_event WHERE event_seq=?", (next_seq,)
            ).fetchone()
        return _row_record(row)

    def list_events(self, *, event_type: str | None = None,
                    object_type: str | None = None,
                    object_id: str | None = None,
                    since_tick: int | None = None,
                    limit: int = 1024) -> list[dict[str, Any]]:
        _require_int("limit", limit, minimum=1)
        if limit > 65536:
            raise MathStoreError("limit must be <= 65536")
        query = "SELECT * FROM math_event WHERE 1=1"
        args: list[Any] = []
        if event_type is not None:
            if event_type not in EVENT_TYPES:
                raise MathStoreError(f"unknown math event type: {event_type!r}")
            query += " AND event_type=?"
            args.append(event_type)
        if object_type is not None:
            _require_text("object_type", object_type, maximum=64)
            query += " AND object_type=?"
            args.append(object_type)
        if object_id is not None:
            _require_text("object_id", object_id, maximum=300)
            query += " AND object_id=?"
            args.append(object_id)
        if since_tick is not None:
            _require_int("since_tick", since_tick)
            query += " AND tick >= ?"
            args.append(since_tick)
        query += " ORDER BY event_seq ASC LIMIT ?"
        args.append(limit)
        with self._connect(self.bs0_path) as db:
            rows = db.execute(query, args).fetchall()
        return [_row_record(row) for row in rows]

    def events(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Alias for :meth:`list_events`."""
        return self.list_events(**kwargs)

    # -- health --------------------------------------------------------------

    def math_health(self) -> dict[str, Any]:
        """Report store integrity without substituting zero for missing data."""
        issues: list[str] = []
        stores: dict[str, str] = {}
        schema_versions: dict[str, int | None] = {}
        for path, store in ((self.bs0_path, "BS0DB"),
                            (self.mc0_path, "MC0DB")):
            try:
                schema_versions[store] = self._schema_version(path, store)
                stores[store] = "ok"
            except MathStoreError as exc:
                schema_versions[store] = None
                stores[store] = "error"
                issues.append(str(exc))
            if schema_versions[store] != MATH_SCHEMA_VERSION:
                issues.append(
                    f"{store} math schema is {schema_versions[store]}, "
                    f"expected {MATH_SCHEMA_VERSION}"
                )

        wave_versions: dict[str, int | None] = {}
        for path, store in ((self.bs0_path, "BS0DB"),
                            (self.mc0_path, "MC0DB")):
            wave_versions[store] = self._wave_schema_version(path, store)
            if wave_versions[store] is not None and wave_versions[store] != 1:
                issues.append(
                    f"{store} wave schema changed to {wave_versions[store]}"
                )

        # Verify every stored payload, including multi-chunk blobs.
        with self._connect(self.bs0_path) as db:
            payload_digests = [
                str(row["digest"]) for row in db.execute(
                    "SELECT DISTINCT digest FROM math_payload ORDER BY digest"
                ).fetchall()
            ]
            chunk_count = int(db.execute(
                "SELECT COUNT(*) FROM math_payload"
            ).fetchone()[0])
        corrupt_payloads: list[str] = []
        for digest in payload_digests:
            try:
                rows = self._fetch_payload_rows(digest)
                self._decode_payload_rows(rows, digest)
            except MathReferenceError:
                corrupt_payloads.append(digest)
        if corrupt_payloads:
            issues.append(
                f"{len(corrupt_payloads)} corrupt math payload(s)"
            )

        # Verify every immutable version digest and its payload reference.
        missing_refs: list[str] = []
        corrupt_versions: list[str] = []
        with self._connect(self.mc0_path) as db:
            leaf_versions = db.execute(
                "SELECT leaf_id, version, leaf_digest, leaf_json, payload_ref "
                "FROM math_leaf_version"
            ).fetchall()
            refs = db.execute("""
                SELECT payload_ref FROM math_leaf_version
                WHERE payload_ref IS NOT NULL
                UNION SELECT payload_ref FROM math_function_version
                UNION SELECT payload_ref FROM math_rule_version
                UNION SELECT payload_ref FROM math_relation_version
                UNION SELECT payload_ref FROM math_candidate
                UNION SELECT payload_ref FROM math_admission
            """).fetchall()
            counts = {
                "math_leaf": self._table_count(self.mc0_path, "math_leaf"),
                "math_leaf_version": len(leaf_versions),
                "math_function": self._table_count(
                    self.mc0_path, "math_function"
                ),
                "math_function_version": self._table_count(
                    self.mc0_path, "math_function_version"
                ),
                "math_rule": self._table_count(self.mc0_path, "math_rule"),
                "math_rule_version": self._table_count(
                    self.mc0_path, "math_rule_version"
                ),
                "math_relation": self._table_count(
                    self.mc0_path, "math_relation"
                ),
                "math_relation_version": self._table_count(
                    self.mc0_path, "math_relation_version"
                ),
                "math_candidate": self._table_count(
                    self.mc0_path, "math_candidate"
                ),
                "math_admission": self._table_count(
                    self.mc0_path, "math_admission"
                ),
                "math_mapping": self._table_count(
                    self.mc0_path, "math_mapping"
                ),
                "math_preflight_cache": self._table_count(
                    self.mc0_path, "math_preflight_cache"
                ),
                "math_commit_intent": self._table_count(
                    self.mc0_path, "math_commit_intent"
                ),
                "math_commit_evidence": self._table_count(
                    self.bs0_path, "math_commit_evidence"
                ),
                "math_event": self._table_count(
                    self.bs0_path, "math_event"
                ),
                "math_payload": len(payload_digests),
                "math_payload_chunks": chunk_count,
                "math_certificate": self._table_count(
                    self.bs0_path, "math_certificate"
                ),
            }
        for row in leaf_versions:
            label = f"leaf:{row['leaf_id']}@{row['version']}"
            if sha256_text(str(row["leaf_json"])) != str(row["leaf_digest"]):
                corrupt_versions.append(label)
        with self._connect(self.bs0_path) as db:
            present_payloads = {
                str(row["digest"]) for row in db.execute(
                    "SELECT DISTINCT digest FROM math_payload"
                ).fetchall()
            }
            certificate_refs = [
                str(row["payload_ref"]) for row in db.execute(
                    "SELECT payload_ref FROM math_certificate "
                    "WHERE payload_ref IS NOT NULL"
                ).fetchall()
            ]
        referenced_payloads = [str(row["payload_ref"]) for row in refs]
        referenced_payloads.extend(certificate_refs)
        for ref in referenced_payloads:
            if ref not in present_payloads:
                missing_refs.append(ref)
        if corrupt_versions:
            issues.append(
                f"{len(corrupt_versions)} corrupt math version(s)"
            )
        if missing_refs:
            issues.append(
                f"{len(missing_refs)} missing math payload reference(s)"
            )

        # Resolve current leaf heads through the same verification path as
        # readers; a dangling current pointer must never look healthy.
        current_errors: list[str] = []
        with self._connect(self.mc0_path) as db:
            heads = db.execute(
                "SELECT leaf_id, current_version FROM math_leaf"
            ).fetchall()
        for head in heads:
            try:
                self.get_leaf(str(head["leaf_id"]), int(head["current_version"]))
            except MathStoreError:
                current_errors.append(
                    f"leaf:{head['leaf_id']}@{head['current_version']}"
                )
        if current_errors:
            issues.append(f"{len(current_errors)} current leaf error(s)")

        status = "green"
        if issues:
            status = "red" if (
                corrupt_payloads or missing_refs or corrupt_versions
                or current_errors or any(value != MATH_SCHEMA_VERSION
                                         for value in schema_versions.values())
                or any(value is not None and value != 1
                       for value in wave_versions.values())
            ) else "degraded"
        return {
            "schema": "nanrouter.math-store-health.v1",
            "status": status,
            "schema_version": MATH_SCHEMA_VERSION,
            "math_schema_version": MATH_SCHEMA_VERSION,
            "schema_versions": schema_versions,
            "wave_schema_versions": wave_versions,
            "wave_schema_untouched": all(
                value is None or value == 1
                for value in wave_versions.values()
            ),
            "stores": stores,
            "counts": counts,
            "corrupt_payloads": corrupt_payloads,
            "corrupt_versions": corrupt_versions,
            "missing_payload_refs": missing_refs,
            "current_leaf_errors": current_errors,
            "issues": issues,
        }

    def _wave_schema_version(self, path: str, store: str) -> int | None:
        """Read (never write) the wave schema row when it already exists."""
        with self._connect(path) as db:
            table = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='wave_schema'"
            ).fetchone()
            if table is None:
                return None
            row = db.execute(
                "SELECT version FROM wave_schema WHERE store=?", (store,)
            ).fetchone()
        return None if row is None else int(row["version"])


__all__ = [
    "COMMIT_INTENT_STATES", "DEFAULT_CHUNK_BYTES",
    "DEFAULT_MAX_PAYLOAD_BYTES", "EVENT_TYPES", "MAPPING_OBJECT_TYPES",
    "MATH_SCHEMA_VERSION", "MATH_STORE_SCHEMA", "MathCommitError",
    "MathConflictError", "MathPayloadError", "MathReferenceError",
    "MathSchemaError", "MathStore", "MathStoreError", "StaleGenerationError",
]
