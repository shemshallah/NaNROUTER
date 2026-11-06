"""Six-slot MC0:0 runner-ring registry reconciliation.

Runners acknowledge the exact signed volume-registry generation and digest.
This is control-plane convergence, not a claim that remote runners can directly
mount Koyeb disks. Koyeb mount health remains an independently verified input.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

RING_SLOTS = tuple(f"MC0:0/R{i}" for i in range(6))


class RunnerRingError(ValueError):
    pass


class RunnerRing:
    def __init__(self, path: str | Path, *, stale_after_ticks: int = 256):
        if stale_after_ticks < 1:
            raise RunnerRingError("stale_after_ticks must be positive")
        self.path = str(path)
        self.stale_after_ticks = stale_after_ticks
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("""
                CREATE TABLE IF NOT EXISTS runner_ring_heartbeat (
                    slot INTEGER PRIMARY KEY CHECK(slot BETWEEN 0 AND 5),
                    runner_id TEXT NOT NULL UNIQUE,
                    registry_generation INTEGER NOT NULL CHECK(registry_generation >= 1),
                    registry_digest TEXT NOT NULL,
                    nanclock_tick INTEGER NOT NULL CHECK(nanclock_tick >= 0)
                )
            """)

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        db.row_factory = sqlite3.Row
        return db

    def heartbeat(self, *, slot: int, runner_id: str, registry_generation: int,
                  registry_digest: str, nanclock_tick: int,
                  expected_generation: int, expected_digest: str) -> dict[str, Any]:
        if not isinstance(slot, int) or not 0 <= slot < 6:
            raise RunnerRingError("runner slot must be in 0..5")
        if runner_id != RING_SLOTS[slot]:
            raise RunnerRingError("runner identity does not match its reserved MC0:0 slot")
        if registry_generation != expected_generation or registry_digest != expected_digest:
            raise RunnerRingError("runner is not acknowledging the current signed volume registry")
        if len(registry_digest) != 64 or any(c not in "0123456789abcdef" for c in registry_digest):
            raise RunnerRingError("registry digest must be lowercase SHA-256 hex")
        if nanclock_tick < 0:
            raise RunnerRingError("NaN clock tick must be nonnegative")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT nanclock_tick FROM runner_ring_heartbeat WHERE slot=?", (slot,)
            ).fetchone()
            if row is not None and nanclock_tick < int(row["nanclock_tick"]):
                db.rollback()
                raise RunnerRingError("runner heartbeat clock cannot move backwards")
            collision = db.execute(
                "SELECT slot FROM runner_ring_heartbeat WHERE runner_id=?", (runner_id,)
            ).fetchone()
            if collision is not None and int(collision["slot"]) != slot:
                db.rollback()
                raise RunnerRingError("runner identity is already assigned to another slot")
            db.execute("""
                INSERT INTO runner_ring_heartbeat
                (slot, runner_id, registry_generation, registry_digest, nanclock_tick)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(slot) DO UPDATE SET
                    runner_id=excluded.runner_id,
                    registry_generation=excluded.registry_generation,
                    registry_digest=excluded.registry_digest,
                    nanclock_tick=excluded.nanclock_tick
            """, (slot, runner_id, registry_generation, registry_digest, nanclock_tick))
            db.commit()
        return self.snapshot(
            expected_generation=expected_generation, expected_digest=expected_digest,
            now_tick=nanclock_tick,
        )

    def latest_tick(self) -> int:
        with self._connect() as db:
            row = db.execute("SELECT MAX(nanclock_tick) AS tick FROM runner_ring_heartbeat").fetchone()
        return int(row["tick"] or 0)

    def snapshot(self, *, expected_generation: int, expected_digest: str,
                 now_tick: int) -> dict[str, Any]:
        if now_tick < 0:
            raise RunnerRingError("NaN clock tick must be nonnegative")
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM runner_ring_heartbeat ORDER BY slot"
            ).fetchall()
        by_slot = {int(row["slot"]): row for row in rows}
        slots = []
        for slot in range(6):
            row = by_slot.get(slot)
            if row is None:
                state = "waiting"
                runner_id = RING_SLOTS[slot]
                last_tick = None
            else:
                runner_id = row["runner_id"]
                last_tick = int(row["nanclock_tick"])
                age = max(0, now_tick - last_tick)
                if age > self.stale_after_ticks:
                    state = "stale"
                elif (int(row["registry_generation"]) != expected_generation
                      or row["registry_digest"] != expected_digest):
                    state = "drift"
                else:
                    state = "in_sync"
            slots.append({
                "slot": slot, "runner_id": runner_id, "state": state,
                "last_heartbeat_tick": last_tick,
            })
        green = all(item["state"] == "in_sync" for item in slots)
        return {
            "macrocluster": "MC0:0",
            "slot_count": 6,
            "registry_generation": expected_generation,
            "registry_digest": expected_digest,
            "health": "green" if green else "degraded",
            "in_sync": sum(item["state"] == "in_sync" for item in slots),
            "slots": slots,
        }
