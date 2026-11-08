"""At-most-once NaN16 head observation reservation in existing MC0DB.

Unlike N16T frames, these requests modify the native 255-head scratch bank.
A signed HermesLeaseRegistry receipt and one-active WaveRingScheduler snapshot
are required before an MC0DB reservation. Guest execution is NOT an SQL
transaction: a crash after reservation is ambiguous and must not auto-retry.
A successfully captured result is retained as opaque 542,704-byte raw words
until the existing HERMES SHA-verified chart checkpoint is read back.

No second DB, host NaN arithmetic, math-rule promotion, or silent NANNET merge.
The aggregate ring lease count is not a proof of individual job ownership;
a production caller must additionally enforce its actual NMP/job binding.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from typing import Callable

from .head_bank_handoff import (
    BANK_BYTES, BANK_OFFSET, BANK_END, HeadBankHandoff,
    check_native_observation_receipt,
)
from .hermes_leases import HermesLeaseRegistry, HermesLeaseError
from .math_auth import READ, WRITE
from .math_store import MathStore
from .native_head_guest import NativeHeadBankGuest
from .wave_ring_scheduler import WaveRingScheduler

SCHEMA = "nanrouter.head-observation-journal/1"
CHART_BYTES = 8 * 1024 * 1024
TABLE = "nan_head_observation_dispatch"
DDL = """
CREATE TABLE IF NOT EXISTS nan_head_observation_dispatch (
    installation_id TEXT NOT NULL,
    dispatch_id TEXT NOT NULL,
    universe_id TEXT NOT NULL,
    head_index INTEGER NOT NULL,
    lease_id INTEGER NOT NULL,
    lease_generation INTEGER NOT NULL,
    ring_epoch INTEGER NOT NULL,
    request_sha256 TEXT NOT NULL,
    parent_root_sha256 TEXT NOT NULL,
    chart_generation INTEGER NOT NULL,
    bank_before_sha256 TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('reserved','executed','checkpointed')),
    bank_after_sha256 TEXT,
    result_words BLOB,
    receipt_json TEXT,
    issued_at INTEGER NOT NULL,
    completed_at INTEGER,
    checkpointed_at INTEGER,
    PRIMARY KEY (installation_id, dispatch_id),
    UNIQUE (installation_id, universe_id, parent_root_sha256,
            chart_generation, bank_before_sha256)
)
"""


class HeadObservationJournalError(ValueError):
    pass


class HeadObservationConflict(HeadObservationJournalError):
    """A reserved operation has ambiguous outcome or a conflicting lease."""


class HeadObservationJournal:
    def __init__(self, store: MathStore, lease_registry: HermesLeaseRegistry,
                 scheduler: WaveRingScheduler):
        if (not isinstance(store, MathStore)
                or not isinstance(lease_registry, HermesLeaseRegistry)
                or not isinstance(scheduler, WaveRingScheduler)):
            raise HeadObservationJournalError(
                "existing MC0DB MathStore, signed lease registry and runner ring required"
            )
        self.store = store
        self.leases = lease_registry
        self.ring = scheduler
        self.store._authorize(WRITE, "native_head_dispatch", "schema")
        # This is an additive table in the existing MC0DB, not a new DB file.
        with self.store._write(self.store.mc0_path) as db:
            db.execute(DDL)

    @staticmethod
    def _key(request):
        if not isinstance(request, HeadBankHandoff):
            raise HeadObservationJournalError("typed head handoff required")
        return (request.installation_id, request.dispatch_id)

    def _gate(self, request, signed_lease, now=None):
        self._key(request)
        if not isinstance(signed_lease, dict):
            raise HeadObservationJournalError("signed HERMES lease required")
        # HERMES leased heads 0..254 map explicitly to native guest heads 1..255.
        # Never pass the NANNET0 head or infer a 256th independent worker.
        try:
            lease = self.leases.resolve(
                installation_id=request.installation_id,
                receipt=signed_lease, head_index=request.head_index - 1, now=now
            )
        except HermesLeaseError as exc:
            raise HeadObservationJournalError("HERMES lease denied") from exc
        expected_universe = "universe:" + str(lease["universe_id"]).zfill(10)
        if (request.universe_id != expected_universe
                or request.lease_id != lease["lease_id"]
                or request.lease_generation != lease["generation"]
                or request.head_index != lease["head_index"] + 1
                or lease.get("admitted") is not True):
            raise HeadObservationJournalError("lease/head/universe identity mismatch")
        snap = self.ring.snapshot()
        if (snap.get("started") is not True or snap.get("health") != "green"
                or snap.get("stale") is not False or snap.get("active_count") != 1
                or snap.get("active_slot") is None
                or type(snap.get("epoch")) is not int
                or request.ring_epoch != snap["epoch"]
                or type(snap.get("active_lease_count")) is not int
                or snap["active_lease_count"] < 1
                or snap.get("active_memory_reserved_bytes", 0) < BANK_BYTES + 2048):
            raise HeadObservationJournalError(
                "single-active runner ring epoch/lease/workspace not available"
            )
        return lease

    def _row(self, key):
        self.store._authorize(READ, "native_head_dispatch", key[1])
        with self.store._connect(self.store.mc0_path) as db:
            row = db.execute(
                "SELECT * FROM nan_head_observation_dispatch "
                "WHERE installation_id=? AND dispatch_id=?", key
            ).fetchone()
            return dict(row) if row is not None else None

    def reserve(self, *, request: HeadBankHandoff, signed_lease: dict,
                raw_bank: bytes, now=None) -> dict:
        """Durably reserve before native invocation; duplicates fail closed."""
        key = self._key(request)
        if type(raw_bank) is not bytes or len(raw_bank) != BANK_BYTES:
            raise HeadObservationJournalError("exact raw NaN16 bank bytes required")
        if hashlib.sha256(raw_bank).hexdigest() != request.bank_before_sha256:
            raise HeadObservationJournalError("wrong bank state at reservation")
        self._gate(request, signed_lease, now)
        self.store._authorize(WRITE, "native_head_dispatch", key[1])
        payload = request.prepared()
        with self.store._write(self.store.mc0_path) as db:
            old = db.execute(
                "SELECT request_sha256,state FROM nan_head_observation_dispatch "
                "WHERE installation_id=? AND dispatch_id=?", key
            ).fetchone()
            if old is not None:
                if old["request_sha256"] != payload["request_sha256"]:
                    raise HeadObservationConflict("dispatch ID reused for different request")
                raise HeadObservationConflict(
                    "dispatch already reserved/executed: inspect or recover, do not replay"
                )
            count = db.execute(
                "SELECT COUNT(*) FROM nan_head_observation_dispatch "
                "WHERE state IN ('reserved','executed')"
            ).fetchone()[0]
            if count >= 4096:
                raise HeadObservationJournalError("uncheckpointed native journal at capacity")
            try:
                db.execute(
                    "INSERT INTO nan_head_observation_dispatch "
                    "(installation_id,dispatch_id,universe_id,head_index,lease_id,"
                    "lease_generation,ring_epoch,request_sha256,parent_root_sha256,"
                    "chart_generation,bank_before_sha256,state,issued_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (request.installation_id, request.dispatch_id, request.universe_id,
                     request.head_index, request.lease_id, request.lease_generation,
                     request.ring_epoch, payload["request_sha256"],
                     request.parent_root_sha256, request.chart_generation,
                     request.bank_before_sha256, "reserved", int(time.time())),
                )
            except sqlite3.IntegrityError as exc:
                raise HeadObservationConflict(
                    "concurrent observation from same chart bank generation is reserved"
                ) from exc
        return {"schema": SCHEMA, "state": "reserved",
                "request_sha256": payload["request_sha256"],
                "lease_verified_at_reservation": True,
                "ring_epoch_checked_at_reservation": True,
                "native_guest_invoked": False, "canonical_training_committed": False}

    def record_native_result(self, *, request: HeadBankHandoff, result: dict) -> dict:
        """Persist opaque native guest output AFTER successful native execution."""
        key = self._key(request)
        if not isinstance(result, dict):
            raise HeadObservationJournalError("native result object required")
        output = result.get("raw_bank")
        receipt = result.get("receipt")
        if type(output) is not bytes or len(output) != BANK_BYTES:
            raise HeadObservationJournalError("invalid native guest word result length")
        if result.get("native_guest_invoked_locally") is not True:
            raise HeadObservationJournalError("native guest invocation evidence missing")
        try:
            checked = check_native_observation_receipt(request, receipt)
        except (ValueError, TypeError) as exc:
            raise HeadObservationJournalError("head guest receipt binding failed") from exc
        digest = hashlib.sha256(output).hexdigest()
        if checked["bank_after_sha256"] != digest:
            raise HeadObservationJournalError("native output SHA differs from receipt")
        receipt_json = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
        self.store._authorize(WRITE, "native_head_dispatch", key[1])
        with self.store._write(self.store.mc0_path) as db:
            current = db.execute(
                "SELECT request_sha256,state FROM nan_head_observation_dispatch "
                "WHERE installation_id=? AND dispatch_id=?", key
            ).fetchone()
            if (current is None or current["state"] != "reserved"
                    or current["request_sha256"] != request.prepared()["request_sha256"]):
                raise HeadObservationConflict("request was not exclusively reserved")
            changed = db.execute(
                "UPDATE nan_head_observation_dispatch SET state='executed',"
                "bank_after_sha256=?,result_words=?,receipt_json=?,completed_at=? "
                "WHERE installation_id=? AND dispatch_id=? AND state='reserved'",
                (digest, output, receipt_json, int(time.time()), *key)
            )
            if changed.rowcount != 1:
                raise HeadObservationConflict("reservation changed during native execution")
        return {"schema": SCHEMA, "state": "executed",
                "result_sha256": digest, "native_result_recorded": True,
                "authenticated_dispatch_attested": False,
                "canonical_training_committed": False}

    def run_native(self, *, request: HeadBankHandoff, signed_lease: dict,
                   raw_bank: bytes, guest: NativeHeadBankGuest, now=None,
                   allow_genesis_format: bool = False) -> dict:
        """Reserve -> native execute -> durable output. NO chart commit here."""
        if not isinstance(guest, NativeHeadBankGuest):
            raise HeadObservationJournalError("actual pinned NaN16 head guest required")
        self.reserve(request=request, signed_lease=signed_lease,
                     raw_bank=raw_bank, now=now)
        # If the guest throws, the reservation intentionally remains ambiguous.
        result = guest.observe(
            request=request, raw_bank=raw_bank,
            allow_genesis_format=allow_genesis_format,
        )
        self.record_native_result(request=request, result=result)
        return self.recover(request=request)

    def recover(self, *, request: HeadBankHandoff) -> dict:
        """Read persisted result without rerunning the guest; pending is unknown."""
        key = self._key(request)
        row = self._row(key)
        if row is None:
            return {"schema": SCHEMA, "state": "not_recorded"}
        if row["request_sha256"] != request.prepared()["request_sha256"]:
            raise HeadObservationConflict("cross-request dispatch ID collision")
        if row["state"] == "reserved":
            return {"schema": SCHEMA, "state": "ambiguous",
                    "native_guest_reinvoked": False, "raw_bank": None}
        if row["state"] == "checkpointed":
            return {"schema": SCHEMA, "state": "checkpointed",
                    "bank_after_sha256": row["bank_after_sha256"],
                    "native_guest_reinvoked": False, "raw_bank": None}
        raw = row["result_words"]
        if not isinstance(raw, bytes) or len(raw) != BANK_BYTES:
            raise HeadObservationJournalError("durable native bank result is missing")
        if hashlib.sha256(raw).hexdigest() != row["bank_after_sha256"]:
            raise HeadObservationJournalError("durable native bank result is corrupt")
        try:
            receipt = json.loads(row["receipt_json"])
            checked = check_native_observation_receipt(request, receipt)
        except (TypeError, ValueError) as exc:
            raise HeadObservationJournalError("durable native receipt corrupt") from exc
        if checked["bank_after_sha256"] != row["bank_after_sha256"]:
            raise HeadObservationJournalError("native receipt/bytes mismatch")
        return {"schema": SCHEMA, "state": "executed", "raw_bank": raw,
                "receipt": receipt, "native_guest_reinvoked": False,
                "canonical_training_committed": False}

    def acknowledge_checkpoint(self, *, request: HeadBankHandoff,
                               read_checkpoint: Callable) -> dict:
        """Verify the REAL HERMES checkpoint bank bytes before pruning result.

        read_checkpoint(parent_root) MUST call the existing SHA-verifying
        HERMES load_chart_snapshot. No user-supplied JSON digest substitutes
        for its (generation, full 8MiB chart bytes) return value.
        """
        key = self._key(request)
        if not callable(read_checkpoint):
            raise HeadObservationJournalError("trusted checkpoint reader required")
        staged = self.recover(request=request)
        if staged["state"] == "checkpointed":
            return {"schema": SCHEMA, "state": "checkpointed",
                    "canonical_training_committed": False}
        if staged["state"] != "executed":
            raise HeadObservationConflict("native result not ready for checkpoint")
        try:
            generation, page = read_checkpoint(request.parent_root_sha256)
        except Exception as exc:
            raise HeadObservationJournalError("verified HERMES checkpoint unavailable") from exc
        if (type(generation) is not int
                or generation != request.chart_generation + 1
                or type(page) is not bytes or len(page) != CHART_BYTES
                or page[:8] != b"NLMCHRT1"):
            raise HeadObservationJournalError("wrong chart checkpoint/generation")
        if hashlib.sha256(page[BANK_OFFSET:BANK_END]).hexdigest() != (
                staged["receipt"]["bank_after_sha256"]):
            raise HeadObservationJournalError("checkpoint bank does not match native output")
        self.store._authorize(WRITE, "native_head_dispatch", key[1])
        with self.store._write(self.store.mc0_path) as db:
            changed = db.execute(
                "UPDATE nan_head_observation_dispatch SET state='checkpointed',"
                "result_words=NULL,checkpointed_at=? WHERE installation_id=? "
                "AND dispatch_id=? AND state='executed' AND bank_after_sha256=?",
                (int(time.time()), *key, staged["receipt"]["bank_after_sha256"]),
            )
            if changed.rowcount != 1:
                raise HeadObservationConflict("concurrent checkpoint acknowledgment")
        return {"schema": SCHEMA, "state": "checkpointed",
                "bank_after_sha256": staged["receipt"]["bank_after_sha256"],
                "raw_result_pruned": True,
                "canonical_training_committed": False,
                "nannet_merge_issued": False}
