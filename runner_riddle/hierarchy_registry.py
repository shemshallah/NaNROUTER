"""BS0-rooted hardware binding and future-tier route DB.

This is a durable identity index, NOT a Python NaN16 execution engine.
It never processes user-supplied arithmetic or creates runtime BS/MC/SC/GM
instances. Only the NANNET portal, after verifying Ed25519 pairing, may
delegate a key binding; the router's pinned NaN16 nhr_hw_admit guest must
admit that binding before a physical HERMES guest can be activated.

Hardware root HW0 and reserved HW1..4 remain permanently named. The first
HERMES paired key may bind HW2; distinct keys are assigned HW5..255. A new
BS1 can be named under MC0 before its physical executor exists. Higher
SC0/GM0 tiers are database-only and never advertise live compute.
"""
from __future__ import annotations

import base64
import hashlib
import re
import sqlite3
import time
from pathlib import Path

ROOT = "nan://GM0:SC0:MC0:BS0:0"
ROLES = {0: "router-hardware-root", 1: "android", 2: "hermes",
         3: "clocked", 4: "wordnet"}
_TIERS = ("HW", "BS", "MC", "SC", "GM")


class HierarchyError(ValueError):
    pass


def _number(value, name, upper=255):
    if type(value) is not int or not 0 <= value <= upper:
        raise HierarchyError(f"invalid {name} (must be unsigned bounded NaN node index)")
    return value


def _id(value):
    if not isinstance(value, str) or not re.fullmatch("[A-Za-z0-9._:-]{8,128}", value):
        raise HierarchyError("invalid paired installation ID")
    return value


def _key(value):
    if not isinstance(value, str) or not re.fullmatch("[A-Za-z0-9_-]{43}", value):
        raise HierarchyError("paired Ed25519 public key must be 32-byte base64url")
    try:
        raw = base64.urlsafe_b64decode(value + "=")
    except (ValueError, base64.binascii.Error) as exc:
        raise HierarchyError("invalid Ed25519 public key encoding") from exc
    if len(raw) != 32 or base64.urlsafe_b64encode(raw).decode().rstrip("=") != value:
        raise HierarchyError("invalid canonical Ed25519 public key")
    return hashlib.sha256(raw).hexdigest()


def _point(bs, hw):
    return f"nan://GM0:SC0:MC0:BS{bs}:0:HW{hw}:0"


class HierarchyRegistry:
    def __init__(self, database, sc0_database=None, gm0_database=None):
        self.database = str(database)
        self.sc0_database = str(sc0_database or Path(database).with_name("sc0-hierarchy.sqlite"))
        self.gm0_database = str(gm0_database or Path(database).with_name("gm0-hierarchy.sqlite"))
        for filename in (self.database, self.sc0_database, self.gm0_database):
            Path(filename).parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS hardware_binding (
                bs INTEGER NOT NULL CHECK (bs BETWEEN 0 AND 255),
                hw INTEGER NOT NULL CHECK (hw BETWEEN 0 AND 255),
                role TEXT NOT NULL,
                installation_id TEXT,
                key_sha256 TEXT,
                state TEXT NOT NULL CHECK (state IN ('reserved','bound','unallocated')),
                generation INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                PRIMARY KEY(bs, hw),
                UNIQUE(bs, installation_id),
                UNIQUE(bs, key_sha256)
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS bootstrap_point (
                mc INTEGER NOT NULL CHECK (mc BETWEEN 0 AND 255),
                bs INTEGER NOT NULL CHECK (bs BETWEEN 0 AND 255),
                state TEXT NOT NULL CHECK (state IN ('live','future','retired')),
                PRIMARY KEY(mc,bs)
            )""")
            db.execute("INSERT OR IGNORE INTO bootstrap_point(mc,bs,state) VALUES(0,0,'live')")
            for hw, role in ROLES.items():
                db.execute("""INSERT OR IGNORE INTO hardware_binding
                    (bs,hw,role,installation_id,key_sha256,state,generation,created_at)
                    VALUES(0,?,?,NULL,NULL,'reserved',0,?)""",
                    (hw, role, int(time.time())))
        # Database-only snapshots: creating these tables does not instantiate
        # a separate SC0/GM0 daemon, repository or network service.
        with sqlite3.connect(self.sc0_database) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS sc0_children(
                sc INTEGER NOT NULL, mc INTEGER NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('database-only','future')),
                PRIMARY KEY(sc,mc))""")
            db.execute("INSERT OR IGNORE INTO sc0_children VALUES(0,0,'database-only')")
        with sqlite3.connect(self.gm0_database) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS gm0_children(
                gm INTEGER NOT NULL, sc INTEGER NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('database-only','future')),
                PRIMARY KEY(gm,sc))""")
            db.execute("INSERT OR IGNORE INTO gm0_children VALUES(0,0,'database-only')")

    def _db(self):
        db = sqlite3.connect(self.database, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=15000")
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def bind_hermes(self, installation_id, public_key):
        """Atomic permanent ownership: first HERMES HW2, others HW5..255.

        Ed25519 verification is done ONLY by the existing portal.
        The router trusts *only* its private portal delegation bearer.
        Client request IDs/claimed node points cannot select hardware.
        """
        installation_id = _id(installation_id)
        key_digest = _key(public_key)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            same_id = db.execute(
                "SELECT * FROM hardware_binding WHERE bs=0 AND installation_id=?",
                (installation_id,)).fetchone()
            if same_id:
                if same_id["key_sha256"] != key_digest or same_id["role"] != "hermes":
                    raise HierarchyError("installation attempted hardware key rotation or role theft")
                return self._binding(same_id)
            same_key = db.execute(
                "SELECT * FROM hardware_binding WHERE bs=0 AND key_sha256=?",
                (key_digest,)).fetchone()
            if same_key:
                raise HierarchyError("paired public key already belongs to a different installation")
            reserved = db.execute(
                "SELECT * FROM hardware_binding WHERE bs=0 AND hw=2"
            ).fetchone()
            if reserved["installation_id"] is None:
                hw = 2
            else:
                hw = next((n for n in range(5, 256)
                           if db.execute("SELECT 1 FROM hardware_binding WHERE bs=0 AND hw=?",
                                         (n,)).fetchone() is None), None)
            if hw is None:
                raise HierarchyError("BS0 hardware node capacity exhausted (HW5..HW255)")
            if hw == 2:
                db.execute("""UPDATE hardware_binding
                    SET installation_id=?,key_sha256=?,state='bound',generation=generation+1
                    WHERE bs=0 AND hw=2 AND installation_id IS NULL""",
                    (installation_id, key_digest))
            else:
                db.execute("""INSERT INTO hardware_binding
                    (bs,hw,role,installation_id,key_sha256,state,generation,created_at)
                    VALUES(0,?,'hermes',?,?,'bound',1,?)""",
                    (hw, installation_id, key_digest, int(time.time())))
            record = db.execute(
                "SELECT * FROM hardware_binding WHERE bs=0 AND hw=?", (hw,)).fetchone()
            return self._binding(record)

    @staticmethod
    def _binding(row):
        return {"bs": row["bs"], "hw": row["hw"],
                "node_point": row["hw"] + 1, "role": row["role"],
                "state": row["state"], "generation": row["generation"],
                "route": _point(row["bs"], row["hw"]),
                "runner_port": f"BS{row['bs']}:0",
                "transport_active": row["bs"] == 0 and row["state"] == "bound",
                "native_guest_admitted": False}

    def binding_for(self, installation_id, public_key):
        identity = _id(installation_id)
        fingerprint = _key(public_key)
        with self._db() as db:
            row = db.execute(
                "SELECT * FROM hardware_binding WHERE bs=0 AND installation_id=?",
                (identity,)).fetchone()
            if row is None or row["key_sha256"] != fingerprint:
                raise HierarchyError("no authenticated hardware binding for paired installation")
            return self._binding(row)

    def hardware(self, hw, bs=0):
        hw, bs = _number(hw, "hardware id"), _number(bs, "bootstrap id")
        with self._db() as db:
            row = db.execute(
                "SELECT * FROM hardware_binding WHERE bs=? AND hw=?", (bs, hw)).fetchone()
        if row is not None:
            value = self._binding(row)
            if hw <= 4:
                value["permanent"] = True
            return value
        return {"bs": bs, "hw": hw, "node_point": hw + 1,
                "state": "unallocated", "runner_port": f"BS{bs}:0",
                "route": _point(bs, hw), "transport_active": False}

    def reserve_future_bootstrap(self, bs, mc=0):
        """Declare a potential MC0:BS1:0 address, not a running runner."""
        bs, mc = _number(bs, "BS"), _number(mc, "MC")
        if bs == 0 and mc == 0:
            raise HierarchyError("cannot redefine the live root BS0:0")
        if mc != 0:
            raise HierarchyError("new MC runtime not installed; reserve under MC0 only")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT state FROM bootstrap_point WHERE mc=? AND bs=?",
                             (mc, bs)).fetchone()
            if row and row["state"] != "future":
                raise HierarchyError("cannot convert live or retired BS to a future placeholder")
            db.execute("INSERT OR IGNORE INTO bootstrap_point VALUES(?,?,'future')",
                       (mc, bs))
        return {"route": f"nan://GM0:SC0:MC{mc}:BS{bs}:0",
                "state": "future", "transport_active": False,
                "runner_instantiated": False, "allocation_allowed": False}

    def resolve(self, address):
        """Read-only tree projection: an unresolved address NEVER routes."""
        if not isinstance(address, str) or len(address) > 128:
            raise HierarchyError("malformed bounded NaN hierarchy route")
        if address == "nan://GM0:0":
            return {"route": address, "tier": "GM", "state": "apex-database-only",
                    "transport_active": False}
        if address in ("nan://GM0:SC0:0", "nan://GM0:SC0:MC0:0"):
            return {"route": address, "tier": "SC" if "MC0" not in address else "MC",
                    "state": "database-only", "transport_active": False}
        match = re.fullmatch(r"nan://GM0:SC0:MC0:BS(\d{1,3}):0(?::HW(\d{1,3}):0)?", address)
        if not match:
            raise HierarchyError("unsupported or unregistered hierarchy namespace")
        bs, hw = int(match[1]), match[2]
        _number(bs, "BS")
        with self._db() as db:
            row = db.execute("SELECT state FROM bootstrap_point WHERE mc=0 AND bs=?",
                             (bs,)).fetchone()
        if row is None:
            return {"route": address, "state": "absent", "transport_active": False}
        if hw is None:
            return {"route": address, "tier": "BS", "state": row["state"],
                    "transport_active": row["state"] == "live" and bs == 0}
        result = self.hardware(_number(int(hw), "HW"), bs)
        if row["state"] != "live":
            result["state"] = "future"
            result["transport_active"] = False
        return result

    def summary(self):
        with self._db() as db:
            assigned = db.execute(
                "SELECT COUNT(*) FROM hardware_binding WHERE bs=0 AND role='hermes' "
                "AND state='bound'").fetchone()[0]
            futures = db.execute(
                "SELECT COUNT(*) FROM bootstrap_point WHERE state='future'").fetchone()[0]
        return {"network_root": "BS0:0", "hardware_fixed": [0, 1, 2, 3, 4],
                "hardware_dynamic_range": [5, 255],
                "hermes_bound_nodes": assigned, "future_bootstrap_points": futures,
                "mc0": "router database and control plane",
                "sc0": "database-only, no separate network service",
                "gm0": "database-only apex, no separate network service",
                "transport_active": False}
