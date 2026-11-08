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
import time
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
            # Serialize schema upgrades with dispatch writes and with another
            # router starting against the same durable WAL database.
            db.execute("BEGIN IMMEDIATE")
            try:
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
                    source_chart_sha256 TEXT,
                    source_root_block_sha256 TEXT,
                    bank_after BLOB,
                    bank_after_sha256 TEXT,
                    native_receipt_json TEXT,
                    checkpoint_generation INTEGER,
                    checkpointed_at INTEGER,
                    PRIMARY KEY(installation_id,dispatch_id)
                )""")
                existing = {
                    row[1]: str(row[2]).upper()
                    for row in db.execute(
                        "PRAGMA table_info(hermes_head_observation)"
                    )
                }
                # Legacy deployments have no checkpoint/source columns.
                # SHA-256 values are TEXT, never SQLite INTEGER affinity:
                # all-decimal-looking hashes otherwise undergo numeric
                # coercion, losing leading zeroes or integer precision.
                for name, sql_type in (
                    ("checkpoint_generation", "INTEGER"),
                    ("checkpointed_at", "INTEGER"),
                    ("source_chart_sha256", "TEXT"),
                    ("source_root_block_sha256", "TEXT"),
                ):
                    if name not in existing:
                        db.execute(
                            "ALTER TABLE hermes_head_observation ADD COLUMN " +
                            name + " " + sql_type
                        )
                        existing[name] = sql_type
                if any(
                    existing[name] != "TEXT"
                    for name in (
                        "source_chart_sha256", "source_root_block_sha256",
                    )
                ):
                    # Repair databases upgraded by the earlier migration,
                    # which used INTEGER for these two SHA fields. Rebuild
                    # transactionally without deleting a pending reservation,
                    # staged native bank, or permanent checkpoint tombstone.
                    db.execute("""CREATE TABLE hermes_head_observation_retyped (
                        installation_id TEXT NOT NULL,
                        dispatch_id TEXT NOT NULL,
                        request_sha256 TEXT NOT NULL,
                        lease_id INTEGER NOT NULL,
                        universe_id INTEGER NOT NULL,
                        lease_generation INTEGER NOT NULL,
                        head_index INTEGER NOT NULL,
                        ring_epoch INTEGER NOT NULL,
                        bank_before_sha256 TEXT NOT NULL,
                        source_chart_sha256 TEXT,
                        source_root_block_sha256 TEXT,
                        bank_after BLOB,
                        bank_after_sha256 TEXT,
                        native_receipt_json TEXT,
                        checkpoint_generation INTEGER,
                        checkpointed_at INTEGER,
                        PRIMARY KEY(installation_id,dispatch_id)
                    )""")
                    columns = (
                        "installation_id,dispatch_id,request_sha256,lease_id,"
                        "universe_id,lease_generation,head_index,ring_epoch,"
                        "bank_before_sha256,source_chart_sha256,"
                        "source_root_block_sha256,bank_after,bank_after_sha256,"
                        "native_receipt_json,checkpoint_generation,checkpointed_at"
                    )
                    db.execute(
                        "INSERT INTO hermes_head_observation_retyped (" +
                        columns + ") SELECT " + columns +
                        " FROM hermes_head_observation"
                    )
                    db.execute("DROP TABLE hermes_head_observation")
                    db.execute(
                        "ALTER TABLE hermes_head_observation_retyped "
                        "RENAME TO hermes_head_observation"
                    )
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise

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

    @staticmethod
    def _verified_fence(state):
        # An arbitrary dictionary containing a matching bank SHA is NOT an
        # authenticated N16SNAP1 chart. The configured trusted HERMES reader
        # must report that it validated both the whole chart and N16ROOT1.
        if (not isinstance(state, Mapping)
                or state.get("schema") != "nanlm.native-head-checkpoint-fence/1"
                or state.get("snapshot_verified") is not True
                or state.get("canonical_training_committed") is not False):
            raise HermesHeadObservationError(
                "mounted SHA-verified N16SNAP1 chart authority required"
            )
        for field in ("root_block_sha256", "chart_sha256"):
            value = state.get(field)
            if (type(value) is not str or len(value) != 64
                    or any(c not in "0123456789abcdef" for c in value)):
                raise HermesHeadObservationError(
                    "chart authority has no valid " + field
                )
        return state

    def _fence(self, request, resolved):
        # Native observations require a real SHA-verified binary root and
        # 8 MiB chart. Digest labels alone are never sufficient authority.
        state = self._verified_fence(
            self.chart_fence_reader(resolved["universe_id"])
        )
        for field, expected in (
            ("parent_root_sha256", request.parent_root_sha256),
            ("chart_generation", request.chart_generation),
            ("bank_sha256", request.bank_before_sha256),
        ):
            if type(state.get(field)) is not type(expected) or state[field] != expected:
                raise HermesHeadObservationConflict("stale chart fence: " + field)
        return state

    @staticmethod
    def _source_identity(row):
        # Existing staged pre-upgrade entries remain inspectable but cannot
        # retroactively acquire a stronger identity claim. Newly reserved
        # operations must bind both exact chart and mounted-root SHA.
        chart_digest = row["source_chart_sha256"]
        root_digest = row["source_root_block_sha256"]
        if chart_digest is None and root_digest is None:
            return {
                "source_chart_sha256": None,
                "source_root_block_sha256": None,
                "source_snapshot_bound": False,
            }
        for label, value in (
            ("source_chart_sha256", chart_digest),
            ("source_root_block_sha256", root_digest),
        ):
            if (type(value) is not str or len(value) != 64
                    or any(c not in "0123456789abcdef" for c in value)):
                raise HermesHeadObservationError(
                    "corrupt native source chart identity: " + label
                )
        return {
            "source_chart_sha256": chart_digest,
            "source_root_block_sha256": root_digest,
            "source_snapshot_bound": True,
        }

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
    def _checkpointed_result(row, request):
        """Immutable tombstone: dispatch must NEVER be reused after reclaim."""
        if (row["checkpointed_at"] is None
                or row["checkpoint_generation"] != request.chart_generation + 1
                or row["bank_after"] is not None):
            raise HermesHeadObservationError("invalid checkpoint tombstone")
        try:
            receipt = json.loads(row["native_receipt_json"])
            check_native_observation_receipt(request, receipt)
        except (TypeError, ValueError) as exc:
            raise HermesHeadObservationError("checkpoint receipt invalid") from exc
        if receipt["bank_after_sha256"] != row["bank_after_sha256"]:
            raise HermesHeadObservationError("checkpoint result digest mismatch")
        return {
            "schema": "nanrouter.hermes-head-staging/1",
            **HermesHeadObservationJournal._source_identity(row),
            "request_sha256": row["request_sha256"],
            "bank_after_sha256": row["bank_after_sha256"],
            "checkpoint_generation": row["checkpoint_generation"],
            "local_checkpoint_verified": True,
            "native_guest_invoked_locally": True,
            "authenticated_lease_admitted": True,
            "chart_commit_verified": False,
            "canonical_training_committed": False,
            "nannet_merge_issued": False,
            "replayed_from_journal": True,
        }

    @staticmethod
    def _verified_output(row, request):
        if row["checkpointed_at"] is not None:
            return HermesHeadObservationJournal._checkpointed_result(row, request)
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
            **HermesHeadObservationJournal._source_identity(row),
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
            source_fence = self._fence(request, resolved)
            count = db.execute(
                "SELECT COUNT(*) FROM hermes_head_observation WHERE checkpointed_at IS NULL"
            ).fetchone()[0]
            if count >= self.MAX_OUTSTANDING:
                raise HermesHeadObservationError("native head journal capacity exhausted")
            db.execute("""INSERT INTO hermes_head_observation
                (installation_id, dispatch_id, request_sha256, lease_id,
                 universe_id, lease_generation, head_index, ring_epoch,
                 bank_before_sha256, source_chart_sha256,
                 source_root_block_sha256)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (
                *key, request.prepared()["request_sha256"], resolved["lease_id"],
                resolved["universe_id"], resolved["generation"], request.head_index,
                request.ring_epoch, request.bank_before_sha256,
                source_fence["chart_sha256"],
                source_fence["root_block_sha256"],
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
        # Recheck all live authorities AFTER the guest call and BEFORE making
        # its output recoverable. A handoff/revocation/checkpoint race must
        # leave the prior durable reservation ambiguous, never promote the
        # result under an epoch, lease or chart that has already changed.
        # This is a second fence, not a substitute for the global scheduler
        # lock required for canonical publication.
        resolved_after = self._authorize(
            request=request, lease_receipt=lease_receipt,
            network_head=network_head, for_execution=True,
        )
        final_fence = self._fence(request, resolved_after)
        if (source_fence["chart_sha256"] != final_fence["chart_sha256"]
                or source_fence["root_block_sha256"] !=
                final_fence["root_block_sha256"]):
            raise HermesHeadObservationConflict(
                "native guest ran while full chart/root identity changed"
            )
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
        if row["checkpointed_at"] is not None:
            result = self._checkpointed_result(row, request)
            result["state"] = "checkpointed_locally"
            return result
        if row["bank_after"] is None:
            return {
                "state": "pending_or_ambiguous",
                "request_sha256": request.prepared()["request_sha256"],
                **self._source_identity(row),
                "canonical_training_committed": False,
            }
        result = self._verified_output(row, request)
        result["state"] = "completed_staging_only"
        if not include_bank:
            result.pop("raw_bank")
        return result

    def confirm_local_checkpoint(self, *, request: HeadBankHandoff,
                                 lease_receipt: dict, network_head: int):
        """Reclaim staged BLOB after a *real* N16SNAP1 next-generation read.

        The reader must be the trusted HERMES SnapshotHeadBankFence, not a
        client-provided acknowledgement. Durable SHA equality to the staged
        native bytes, exact next generation and mounted root are required.
        Permanent dispatch-ID tombstones prevent at-most-once regression.
        This is LOCAL checkpoint verification, not a NANNET model merge.
        """
        resolved = self._authorize(
            request=request, lease_receipt=lease_receipt,
            network_head=network_head, for_execution=False,
        )
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            key = (request.installation_id, request.dispatch_id)
            row = db.execute("""SELECT * FROM hermes_head_observation
                WHERE installation_id=? AND dispatch_id=?""", key).fetchone()
            if row is None:
                raise HermesHeadObservationConflict("unknown native head dispatch")
            self._scope(row, request, resolved)
            if row["checkpointed_at"] is not None:
                return self._checkpointed_result(row, request)
            staged = self._verified_output(row, request)
            snapshot = self._verified_fence(
                self.chart_fence_reader(resolved["universe_id"])
            )
            for field, expected in (
                ("parent_root_sha256", request.parent_root_sha256),
                ("chart_generation", request.chart_generation + 1),
                ("bank_sha256", staged["bank_after_sha256"]),
            ):
                if type(snapshot.get(field)) is not type(expected) or snapshot[field] != expected:
                    raise HermesHeadObservationConflict(
                        "local native checkpoint fence mismatch: " + field
                    )
            # No UPDATE can remove this dispatch's primary-key tombstone.
            changed = db.execute("""UPDATE hermes_head_observation
                SET checkpoint_generation=?, checkpointed_at=?, bank_after=NULL
                WHERE installation_id=? AND dispatch_id=? AND
                      checkpointed_at IS NULL AND bank_after IS NOT NULL""",
                (request.chart_generation + 1, int(time.time()), *key))
            if changed.rowcount != 1:
                raise HermesHeadObservationConflict("checkpoint evidence changed")
            final = db.execute("""SELECT * FROM hermes_head_observation
                WHERE installation_id=? AND dispatch_id=?""", key).fetchone()
            return self._checkpointed_result(final, request)
