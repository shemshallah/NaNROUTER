"""Lease-gated, crash-ambiguous journal for native NaN16 head observations.

This is deliberately an INTERNAL staging boundary, not an HTTP route and not a
chart-commit engine. It never accepts client assertions of lease validity,
ring epoch, chart snapshot or guest provenance. All four are read from injected
router-owned authorities before reserving at-most-once work.

The database may be the existing durable HERMES dispatch SQLite database; this
module uses its own table and never changes N16T framing/journal semantics.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Mapping
from pathlib import Path

from .head_bank_handoff import (
    BANK_BYTES, HeadBankHandoff, check_native_observation_receipt,
)
from .native_head_guest import NativeHeadBankGuest


class HermesHeadObservationError(ValueError):
    pass


class HermesHeadObservationConflict(HermesHeadObservationError):
    pass


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class HermesHeadObservationJournal:
    """Lease-authorized, durable and non-replaying native-head staging queue.

    The caller MUST supply the *router-owned* live lease registry, ring epoch
    reader and HERMES chart-fence reader, not request-provided substitutes.
    A successful result is only a recoverable staged bank, never a chart write,
    NANNET merge, trained language model, or mathematical rule promotion.
    """

    MAX_OUTSTANDING = 128

    def __init__(self, database, *, lease_registry, ring_epoch_reader: Callable,
                 chart_fence_reader: Callable):
        if not callable(getattr(lease_registry, "resolve", None)):
            raise TypeError("live HermesLeaseRegistry.resolve is required")
        if not callable(ring_epoch_reader) or not callable(chart_fence_reader):
            raise TypeError("router epoch and chart fence authorities are required")
        self.database = str(database)
        self.lease_registry = lease_registry
        self.ring_epoch_reader = ring_epoch_reader
        self.chart_fence_reader = chart_fence_reader
        Path(self.database).parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("""CREATE TABLE IF NOT EXISTS hermes_head_observation (
                installation_id TEXT NOT NULL,
                dispatch_id TEXT NOT NULL,
                request_sha256 TEXT NOT NULL,
                lease_id INTEGER NOT NULL,
                universe_id INTEGER NOT NULL,
                lease_generation INTEGER NOT NULL,
                head_index INTEGER NOT NULL,
                ring_epoch INTEGER NOT NULL,
                bank_before_sha256 TEXT NOT NULL,
                bank_after BLOB,
                bank_after_sha256 TEXT,
                native_receipt_json TEXT,
                PRIMARY KEY(installation_id,dispatch_id)
            )""")

    def _db(self):
        db = sqlite3.connect(self.database, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=15000")
        return db

    def _authorize(self, *, request, lease_receipt, network_head, for_execution):
        if not isinstance(request, HeadBankHandoff):
            raise HermesHeadObservationError("validated native head request required")
        if type(network_head) is not int or not 0 <= network_head <= 254:
            raise HermesHeadObservationError("NANNET head is outside 0..254")
        # This calls the existing MAC/SQLite/revocation/expiry validator. It is
        # not a boolean supplied by the caller and no lease secret is copied.
        resolved = self.lease_registry.resolve(
            installation_id=request.installation_id,
            receipt=lease_receipt,
            head_index=network_head,
        )
        if resolved.get("admitted") is not True:
            raise HermesHeadObservationError("router lease not admitted")
        expected_universe = "hermes-universe-" + str(resolved["universe_id"])
        for actual, expected, field in (
            (request.universe_id, expected_universe, "universe_id"),
            (request.lease_id, resolved["lease_id"], "lease_id"),
            (request.lease_generation, resolved["generation"], "lease_generation"),
            (request.head_index, network_head + 1, "head_index"),
        ):
            if type(actual) is not type(expected) or actual != expected:
                raise HermesHeadObservationConflict("request/lease mismatch: " + field)
        if for_execution:
            # The epoch comes from the actual router ring authority, NEVER from
            # an N16T request. Recheck immediately before the VM reservation.
            epoch = self.ring_epoch_reader()
            if type(epoch) is not int or epoch < 1 or request.ring_epoch != epoch:
                raise HermesHeadObservationConflict("stale or unavailable ring epoch")
        return resolved

    def _fence(self, request, resolved):
        # A storage reader is mandatory; digest alone cannot attest the chart
        # generation or parent. The reader must be backed by HERMES storage.
        state = self.chart_fence_reader(resolved["universe_id"])
        if not isinstance(state, Mapping):
            raise HermesHeadObservationError("chart snapshot authority unavailable")
        for field, expected in (
            ("parent_root_sha256", request.parent_root_sha256),
            ("chart_generation", request.chart_generation),
            ("bank_sha256", request.bank_before_sha256),
        ):
            if type(state.get(field)) is not type(expected) or state[field] != expected:
                raise HermesHeadObservationConflict("stale chart fence: " + field)

    @staticmethod
    def _scope(row, request, resolved):
        for field, expected in (
            ("request_sha256", request.prepared()["request_sha256"]),
            ("lease_id", resolved["lease_id"]),
            ("universe_id", resolved["universe_id"]),
            ("lease_generation", resolved["generation"]),
            ("head_index", request.head_index),
            ("ring_epoch", request.ring_epoch),
            ("bank_before_sha256", request.bank_before_sha256),
        ):
            if type(row[field]) is not type(expected) or row[field] != expected:
                raise HermesHeadObservationConflict(
                    "dispatch already bound to different native head work: " + field
                )

    @staticmethod
    def _verified_output(row, request):
        raw = row["bank_after"]
        if raw is None:
            raise HermesHeadObservationConflict(
                "native head outcome pending or ambiguous; never replay"
            )
        raw = bytes(raw)
        if len(raw) != BANK_BYTES or _sha(raw) != row["bank_after_sha256"]:
            raise HermesHeadObservationError("durable native bank digest mismatch")
        try:
            receipt = json.loads(row["native_receipt_json"])
            check_native_observation_receipt(request, receipt)
        except (TypeError, ValueError) as exc:
            raise HermesHeadObservationError("stored native guest receipt invalid") from exc
        if receipt["bank_after_sha256"] != row["bank_after_sha256"]:
            raise HermesHeadObservationError("stored receipt/bank digest mismatch")
        return {
            "schema": "nanrouter.hermes-head-staging/1",
            "raw_bank": raw,
            "receipt": receipt,
            "bank_after_sha256": _sha(raw),
            "native_guest_invoked_locally": True,
            "authenticated_lease_admitted": True,
            "chart_commit_verified": False,
            "canonical_training_committed": False,
            "nannet_merge_issued": False,
        }

    def execute(self, *, request: HeadBankHandoff, lease_receipt: dict,
                network_head: int, raw_bank: bytes,
                native_guest: NativeHeadBankGuest,
                allow_genesis_format: bool = False):
        """Reserve *before* VM work. Crashes leave an ambiguous, fenced slot."""
        resolved = self._authorize(
            request=request, lease_receipt=lease_receipt,
            network_head=network_head, for_execution=True,
        )
        if type(raw_bank) is not bytes or len(raw_bank) != BANK_BYTES:
            raise HermesHeadObservationError("exact native bank bytes required")
        if _sha(raw_bank) != request.bank_before_sha256:
            raise HermesHeadObservationConflict("input bank digest mismatch")
        if (not isinstance(native_guest, NativeHeadBankGuest)
                or native_guest.image_sha256 != request.native_image_sha256):
            raise HermesHeadObservationError("pinned native NaN16 guest required")
        if type(allow_genesis_format) is not bool:
            raise HermesHeadObservationError("genesis permission must be boolean")
        key = (request.installation_id, request.dispatch_id)

        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                """SELECT * FROM hermes_head_observation
                   WHERE installation_id=? AND dispatch_id=?""", key
            ).fetchone()
            if existing is not None:
                self._scope(existing, request, resolved)
                result = self._verified_output(existing, request)
                result["replayed_from_journal"] = True
                return result
            self._fence(request, resolved)
            count = db.execute(
                "SELECT COUNT(*) FROM hermes_head_observation"
            ).fetchone()[0]
            if count >= self.MAX_OUTSTANDING:
                raise HermesHeadObservationError("native head journal capacity exhausted")
            db.execute("""INSERT INTO hermes_head_observation
                (installation_id, dispatch_id, request_sha256, lease_id,
                 universe_id, lease_generation, head_index, ring_epoch,
                 bank_before_sha256) VALUES (?,?,?,?,?,?,?,?,?)""", (
                *key, request.prepared()["request_sha256"], resolved["lease_id"],
                resolved["universe_id"], resolved["generation"], request.head_index,
                request.ring_epoch, request.bank_before_sha256,
            ))
        # The pending row is DURABLE now. Never rerun after error or power loss.
        output = native_guest.observe(
            request=request, raw_bank=raw_bank,
            allow_genesis_format=allow_genesis_format,
        )
        if not isinstance(output, Mapping):
            raise HermesHeadObservationError("native guest returned invalid result")
        raw = output.get("raw_bank")
        receipt = output.get("receipt")
        if type(raw) is not bytes or len(raw) != BANK_BYTES:
            raise HermesHeadObservationError("native guest output is not a full bank")
        check_native_observation_receipt(request, receipt)
        if _sha(raw) != receipt["bank_after_sha256"]:
            raise HermesHeadObservationError("native receipt bytes do not match")
        if (output.get("native_guest_invoked_locally") is not True
                or output.get("canonical_training_committed") is not False):
            raise HermesHeadObservationError("native staging provenance mismatch")
        encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":"))
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            updated = db.execute("""UPDATE hermes_head_observation SET
                bank_after=?,bank_after_sha256=?,native_receipt_json=?
                WHERE installation_id=? AND dispatch_id=? AND bank_after IS NULL""",
                (raw, _sha(raw), encoded, *key)
            )
            if updated.rowcount != 1:
                raise HermesHeadObservationConflict("native reservation altered")
        with self._db() as db:
            row = db.execute("""SELECT * FROM hermes_head_observation
                WHERE installation_id=? AND dispatch_id=?""", key).fetchone()
        result = self._verified_output(row, request)
        result["replayed_from_journal"] = False
        return result

    def inspect(self, *, request: HeadBankHandoff, lease_receipt: dict,
                network_head: int, include_bank: bool = False):
        """Read-only recovery; a later ring epoch may inspect but not re-execute."""
        resolved = self._authorize(
            request=request, lease_receipt=lease_receipt,
            network_head=network_head, for_execution=False,
        )
        if type(include_bank) is not bool:
            raise HermesHeadObservationError("include_bank must be boolean")
        with self._db() as db:
            row = db.execute("""SELECT * FROM hermes_head_observation
                WHERE installation_id=? AND dispatch_id=?""",
                (request.installation_id, request.dispatch_id)).fetchone()
        if row is None:
            return {"state": "not_recorded", "canonical_training_committed": False}
        self._scope(row, request, resolved)
        if row["bank_after"] is None:
            return {"state": "pending_or_ambiguous",
                    "request_sha256": request.prepared()["request_sha256"],
                    "canonical_training_committed": False}
        result = self._verified_output(row, request)
        result["state"] = "completed_staging_only"
        if not include_bank:
            result.pop("raw_bank")
        return result
