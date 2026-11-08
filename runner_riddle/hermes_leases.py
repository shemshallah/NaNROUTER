"""Durable HERMES per-universe lease authority on the BS0:0 router.

This is a *delegated control-plane* boundary. Only the NANNET portal may call
it, using a separate server-to-server secret after authenticating a device and
its right to allocate a universe. This module never parses client-supplied
bearer claims or executes NaN16: signed receipts are rechecked against SQLite
before a trusted adapter may pass their fields to the native guest.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
from pathlib import Path

SCHEMA = "nanrouter.hermes-lease.v1"
ROOT_PORT = "BS0:0"
HARDWARE_ROOT = "HW0:0"
MAX_ACTIVE = 16
_MAX_WORD = 0x7fffffff
_INSTALLATION = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_REQUEST = re.compile(r"^[A-Za-z0-9._:-]{12,128}$")


class HermesLeaseError(ValueError):
    """Untrusted, stale, or conflicting delegated lease operation."""


def _integer(value, name, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise HermesLeaseError(f"{name} is outside the permitted range")
    return value


def _identity(value, pattern, name):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise HermesLeaseError(f"invalid {name}")
    return value


def _canonical(doc):
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


class HermesLeaseRegistry:
    def __init__(self, database: str | Path, signing_key: bytes):
        if not isinstance(signing_key, bytes) or len(signing_key) < 32:
            raise HermesLeaseError("HERMES receipt signing key must contain at least 32 bytes")
        self.database = str(database)
        self.key = signing_key
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS hermes_universe_leases (
                lease_id INTEGER PRIMARY KEY,
                universe_id INTEGER UNIQUE NOT NULL,
                installation_id TEXT NOT NULL,
                slot INTEGER NOT NULL,
                node_point INTEGER NOT NULL,
                owner_tag INTEGER NOT NULL,
                generation INTEGER NOT NULL,
                revision INTEGER NOT NULL,
                issued_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                revoked_at INTEGER,
                request_id TEXT UNIQUE NOT NULL
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS hermes_lease_installation ON hermes_universe_leases(installation_id, expires_at)")
            db.execute("""CREATE TABLE IF NOT EXISTS hermes_slot_epochs (
                installation_id TEXT NOT NULL,
                slot INTEGER NOT NULL,
                generation INTEGER NOT NULL,
                PRIMARY KEY(installation_id, slot)
            )""")

    def _connect(self):
        db = sqlite3.connect(self.database, timeout=10, isolation_level="IMMEDIATE")
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def _owner_tag(self, installation_id):
        digest = hmac.new(self.key, ("hermes-owner:" + installation_id).encode(), hashlib.sha256).digest()
        return (int.from_bytes(digest[:4], "big") & _MAX_WORD) or 1

    def _receipt(self, row):
        signed = {
            "schema": SCHEMA,
            "issuer": "nanrouter/BS0:0",
            "network_port": ROOT_PORT,
            "hardware_root": HARDWARE_ROOT,
            "installation_id": row["installation_id"],
            "slot": row["slot"],
            "lease_id": row["lease_id"],
            "universe_id": row["universe_id"],
            "generation": row["generation"],
            "revision": row["revision"],
            "owner_tag": row["owner_tag"],
            "node_point": row["node_point"],
            "expires_at": row["expires_at"],
            "heads": 255,
            "nannet_port_head": 255,
        }
        signed["receipt_mac"] = hmac.new(self.key, b"HERMES/LEASE/v1\n" + _canonical(signed), hashlib.sha256).hexdigest()
        return signed

    def _live(self, db, receipt, installation_id, now):
        installation_id = _identity(installation_id, _INSTALLATION, "installation_id")
        if not isinstance(receipt, dict):
            raise HermesLeaseError("signed lease receipt required")
        mac = receipt.get("receipt_mac")
        if not isinstance(mac, str) or not re.fullmatch("[0-9a-f]{64}", mac):
            raise HermesLeaseError("invalid lease receipt signature")
        unsigned = {k: v for k, v in receipt.items() if k != "receipt_mac"}
        expected = hmac.new(self.key, b"HERMES/LEASE/v1\n" + _canonical(unsigned), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(mac, expected):
            raise HermesLeaseError("lease receipt signature mismatch")
        if receipt.get("schema") != SCHEMA or receipt.get("installation_id") != installation_id:
            raise HermesLeaseError("lease receipt is bound to another identity")
        lease_id = _integer(receipt.get("lease_id"), "lease_id", 1, _MAX_WORD)
        row = db.execute("SELECT * FROM hermes_universe_leases WHERE lease_id=?", (lease_id,)).fetchone()
        if row is None or row["revoked_at"] is not None or row["expires_at"] <= now:
            raise HermesLeaseError("lease is absent, expired or revoked")
        if receipt != self._receipt(row):
            raise HermesLeaseError("stale or mismatched lease receipt")
        return row

    @staticmethod
    def _now(now):
        return int(time.time()) if now is None else _integer(now, "now", 1, _MAX_WORD)

    @staticmethod
    def _ttl(ttl):
        return _integer(ttl, "ttl_seconds", 60, 3600)

    def open(self, *, installation_id, node_point, request_id, ttl_seconds=900, now=None):
        installation_id = _identity(installation_id, _INSTALLATION, "installation_id")
        request_id = _identity(request_id, _REQUEST, "request_id")
        node_point = _integer(node_point, "node_point", 1, 256)
        ttl = self._ttl(ttl_seconds)
        now = self._now(now)
        if now + ttl > _MAX_WORD:
            raise HermesLeaseError("clock rollover requires a new registry era")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT * FROM hermes_universe_leases WHERE request_id=?", (request_id,)
            ).fetchone()
            if previous is not None:
                if (previous["installation_id"] != installation_id
                        or previous["node_point"] != node_point
                        or previous["revoked_at"] is not None or previous["expires_at"] <= now):
                    raise HermesLeaseError("request_id replay or lease no longer active")
                return self._receipt(previous)
            active_rows = db.execute(
                "SELECT slot FROM hermes_universe_leases WHERE installation_id=? AND revoked_at IS NULL AND expires_at>?",
                (installation_id, now)).fetchall()
            used_slots = {row["slot"] for row in active_rows}
            slot = next((s for s in range(MAX_ACTIVE) if s not in used_slots), None)
            if slot is None:
                raise HermesLeaseError("installation native lease registry is full")
            previous_epoch = db.execute(
                "SELECT generation FROM hermes_slot_epochs WHERE installation_id=? AND slot=?",
                (installation_id, slot)).fetchone()
            generation = 1 if previous_epoch is None else previous_epoch["generation"] + 1
            if generation > _MAX_WORD:
                raise HermesLeaseError("native slot generation rollover requires a new era")
            # Exact collision safety is enforced by UNIQUE SQL keys; random IDs
            # are 31-bit NaN16 guest words, never unbounded Python UUID strings.
            for _ in range(32):
                lease_id = secrets.randbelow(_MAX_WORD - 1) + 1
                universe_id = secrets.randbelow(_MAX_WORD - 1) + 1
                if db.execute("SELECT 1 FROM hermes_universe_leases WHERE lease_id=? OR universe_id=?",
                              (lease_id, universe_id)).fetchone():
                    continue
                db.execute("""INSERT INTO hermes_universe_leases
                    (lease_id, universe_id, installation_id, slot, node_point, owner_tag,
                     generation, revision, issued_at, expires_at, revoked_at, request_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, NULL, ?)""",
                    (lease_id, universe_id, installation_id, slot, node_point,
                     self._owner_tag(installation_id), generation, now, now + ttl, request_id))
                db.execute("""INSERT INTO hermes_slot_epochs
                    (installation_id, slot, generation) VALUES (?, ?, ?)
                    ON CONFLICT(installation_id, slot)
                    DO UPDATE SET generation=excluded.generation""",
                    (installation_id, slot, generation))
                row = db.execute(
                    "SELECT * FROM hermes_universe_leases WHERE lease_id=?", (lease_id,)
                ).fetchone()
                return self._receipt(row)
            raise HermesLeaseError("unable to allocate a collision-free universe ID")

    def resolve(self, *, installation_id, receipt, head_index, now=None):
        now = self._now(now)
        head = _integer(head_index, "head_index", 0, 254)
        with self._connect() as db:
            row = self._live(db, receipt, installation_id, now)
        return {
            "admitted": True,
            "universe_id": row["universe_id"],
            "lease_id": row["lease_id"],
            "slot": row["slot"],
            "node_point": row["node_point"],
            "owner_tag": row["owner_tag"],
            "generation": row["generation"],
            "head_index": head,
            "expires_at": row["expires_at"],
            "network_port": ROOT_PORT,
            "hardware_root": HARDWARE_ROOT,
            "native_execution_committed": False,
        }

    def renew(self, *, installation_id, receipt, ttl_seconds=900, now=None):
        now = self._now(now)
        ttl = self._ttl(ttl_seconds)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._live(db, receipt, installation_id, now)
            expiry = max(now, row["expires_at"]) + ttl
            if expiry > _MAX_WORD:
                raise HermesLeaseError("clock rollover requires a new registry era")
            # A renewal keeps the *native slot generation* stable, as required
            # by nhl_renew, but advances the receipt revision. Old receipts
            # immediately fail the authoritative SQLite comparison.
            db.execute("UPDATE hermes_universe_leases SET expires_at=?,revision=revision+1 WHERE lease_id=?",
                       (expiry, row["lease_id"]))
            return self._receipt(db.execute("SELECT * FROM hermes_universe_leases WHERE lease_id=?",
                                            (row["lease_id"],)).fetchone())

    def release(self, *, installation_id, receipt, now=None):
        now = self._now(now)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._live(db, receipt, installation_id, now)
            db.execute("UPDATE hermes_universe_leases SET revoked_at=?,revision=revision+1 WHERE lease_id=?",
                       (now, row["lease_id"]))
        return {"released": True, "lease_id": row["lease_id"], "universe_id": row["universe_id"]}
