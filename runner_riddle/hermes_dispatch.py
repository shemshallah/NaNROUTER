"""Durable, at-most-once HERMES N16T dispatch journal for BS0:0.

N16T framing, CRC, state, and response construction remain exclusively in
the existing native NaN16 guest pool. This store only binds an opaque frame
hash and guest-produced response bytes to a router-authenticated lease and
head. A crash after reservation is intentionally *ambiguous*; it cannot
silently re-execute potentially non-idempotent guest work.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from pathlib import Path

from .n16t_guest import MIN_FRAME_BYTES, MAX_FRAME_BYTES


class HermesDispatchError(ValueError):
    pass


class HermesDispatchConflict(HermesDispatchError):
    pass


class HermesDispatchJournal:
    def __init__(self, database):
        self.database = str(database)
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("""CREATE TABLE IF NOT EXISTS hermes_dispatch (
                installation_id TEXT NOT NULL,
                dispatch_id TEXT NOT NULL,
                lease_id INTEGER NOT NULL,
                universe_id INTEGER NOT NULL,
                generation INTEGER NOT NULL,
                head_index INTEGER NOT NULL,
                frame_sha256 TEXT NOT NULL,
                response BLOB,
                response_sha256 TEXT,
                issued_at INTEGER NOT NULL,
                acknowledged_at INTEGER,
                PRIMARY KEY(installation_id, dispatch_id)
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS hermes_dispatch_lease ON hermes_dispatch(installation_id, lease_id, head_index)")

    def _db(self):
        db = sqlite3.connect(self.database, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=15000")
        return db

    @staticmethod
    def _id(value):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{12,128}", value):
            raise HermesDispatchError("dispatch_id must be a bounded opaque identifier")
        return value

    @staticmethod
    def _frame(value):
        if not isinstance(value, bytes) or not MIN_FRAME_BYTES <= len(value) <= MAX_FRAME_BYTES:
            raise HermesDispatchError("N16T frame must be 36..65572 opaque bytes")
        return value

    def dispatch(self, *, row, installation_id, head_index, dispatch_id,
                 frame, native_exchange):
        dispatch_id = self._id(dispatch_id)
        frame = self._frame(frame)
        frame_sha = hashlib.sha256(frame).hexdigest()
        key = (installation_id, dispatch_id)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM hermes_dispatch WHERE installation_id=? AND dispatch_id=?",
                key).fetchone()
            if existing is None:
                count = db.execute(
                    "SELECT COUNT(*) FROM hermes_dispatch WHERE acknowledged_at IS NULL"
                ).fetchone()[0]
                if count >= 4096:
                    raise HermesDispatchError("HERMES dispatch journal is at capacity")
                db.execute("""INSERT INTO hermes_dispatch
                    (installation_id,dispatch_id,lease_id,universe_id,generation,
                     head_index,frame_sha256,issued_at)
                    VALUES(?,?,?,?,?,?,?,?)""", (
                    installation_id, dispatch_id, row["lease_id"],
                    row["universe_id"], row["generation"], head_index,
                    frame_sha, int(time.time())))
                fresh = True
            else:
                for key_name, expected in (
                    ("lease_id", row["lease_id"]),
                    ("universe_id", row["universe_id"]),
                    ("generation", row["generation"]),
                    ("head_index", head_index),
                    ("frame_sha256", frame_sha),
                ):
                    if existing[key_name] != expected:
                        raise HermesDispatchConflict(
                            "dispatch_id is already bound to another lease/head/frame")
                fresh = False
                if existing["response"] is None:
                    raise HermesDispatchConflict(
                        "dispatch outcome is pending or ambiguous; never blindly replay")
                response = bytes(existing["response"])
                if hashlib.sha256(response).hexdigest() != existing["response_sha256"]:
                    raise HermesDispatchError("durable N16T response digest mismatch")
                return self._result(dispatch_id, frame_sha, response,
                                    existing["acknowledged_at"] is not None, replayed=True)

        # Frame bytes go directly to the existing real native N16T guest.
        # If this raises or the process crashes, the journal remains pending.
        # A retry may only inspect/reconcile, never silently run the frame twice.
        response = native_exchange(frame)
        self._frame(response)
        response_digest = hashlib.sha256(response).hexdigest()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            result = db.execute("""UPDATE hermes_dispatch
                SET response=?,response_sha256=?
                WHERE installation_id=? AND dispatch_id=? AND response IS NULL""",
                (response, response_digest, installation_id, dispatch_id))
            if result.rowcount != 1:
                raise HermesDispatchConflict("dispatch reservation was altered")
        return self._result(dispatch_id, frame_sha, response, False, replayed=False)

    @staticmethod
    def _result(dispatch_id, frame_sha256, response, acknowledged, replayed):
        return {
            "dispatch_id": dispatch_id,
            "frame_sha256": frame_sha256,
            "response_frame_hex": response.hex(),
            "response_sha256": hashlib.sha256(response).hexdigest(),
            "n16t_native_guest_exchange": True,
            "acknowledged": acknowledged,
            "replayed_from_journal": replayed,
            "model_training_committed": False,
        }

    def acknowledge(self, *, row, installation_id, head_index,
                    dispatch_id, response_sha256):
        dispatch_id = self._id(dispatch_id)
        if (not isinstance(response_sha256, str)
                or not re.fullmatch("[a-f0-9]{64}", response_sha256)):
            raise HermesDispatchError("response_sha256 must be lowercase SHA-256")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            entry = db.execute(
                "SELECT * FROM hermes_dispatch WHERE installation_id=? AND dispatch_id=?",
                (installation_id, dispatch_id)).fetchone()
            if entry is None or entry["response"] is None:
                raise HermesDispatchConflict("dispatch is not completed")
            if (entry["lease_id"] != row["lease_id"]
                    or entry["universe_id"] != row["universe_id"]
                    or entry["generation"] != row["generation"]
                    or entry["head_index"] != head_index
                    or entry["response_sha256"] != response_sha256):
                raise HermesDispatchConflict("response acknowledgment does not match the authenticated dispatch")
            if entry["acknowledged_at"] is None:
                db.execute("""UPDATE hermes_dispatch SET acknowledged_at=?
                    WHERE installation_id=? AND dispatch_id=? AND acknowledged_at IS NULL""",
                    (int(time.time()), installation_id, dispatch_id))
        return {"acknowledged": True, "dispatch_id": dispatch_id,
                "response_sha256": response_sha256,
                "model_training_committed": False}
