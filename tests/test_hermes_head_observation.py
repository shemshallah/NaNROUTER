"""Authenticated lease, ring-fence and crash-replay regression for head staging.

The deliberately mocked observe below tests the ledger and gate only; the
separate native-head-guest workflow compiles and executes the real NaN16 VM.
"""
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from runner_riddle.head_bank_handoff import BANK_BYTES, HeadBankHandoff
from runner_riddle.hermes_head_observation import (
    HermesHeadObservationJournal, HermesHeadObservationConflict,
    HermesHeadObservationError,
)
from runner_riddle.hermes_leases import HermesLeaseRegistry, HermesLeaseError
from runner_riddle.native_head_guest import NativeHeadBankGuest


def digest(value):
    return hashlib.sha256(value).hexdigest()


class HeadObservationJournalTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "hermes.sqlite"
        self.registry = HermesLeaseRegistry(
            self.path, b"test-head-lease-key-is-long-and-not-deployable"
        )
        self.installation = "installation-head-001"
        self.lease = self.registry.open(
            installation_id=self.installation, node_point=3,
            request_id="head-open-req-0001",
        )
        self.raw = bytes(BANK_BYTES)
        self.changed = bytes((0xFE,)) + self.raw[1:]
        self.epoch = 7
        self.chart_generation = 5
        self.parent = digest(b"test-parent")
        self.guest_image = digest(b"native-guest-image")
        self.chart_bank_digest = digest(self.raw)
        self.chart_sha = digest(b"verified-eight-megabyte-chart")
        self.root_sha = digest(b"mounted-native-root")
        self.calls = 0
        self.journal = self.make_journal()
        self.request = self.make_request()

    def make_request(self, **changes):
        properties = dict(
            universe_id="hermes-universe-" + str(self.lease["universe_id"]),
            installation_id=self.installation,
            dispatch_id="native-head-dispatch-0001",
            lease_id=self.lease["lease_id"],
            lease_generation=self.lease["generation"],
            ring_epoch=self.epoch,
            head_index=1, feature_index=127, increment=3,
            parent_root_sha256=self.parent,
            bank_before_sha256=digest(self.raw),
            chart_generation=self.chart_generation,
            observation_sha256=digest(b"test observation"),
            native_image_sha256=self.guest_image,
        )
        properties.update(changes)
        return HeadBankHandoff(**properties)

    def make_journal(self):
        return HermesHeadObservationJournal(
            self.path, lease_registry=self.registry,
            ring_epoch_reader=lambda: self.epoch,
            chart_fence_reader=lambda universe: {
                "schema": "nanlm.native-head-checkpoint-fence/1",
                "parent_root_sha256": self.parent,
                "chart_generation": self.chart_generation,
                "bank_sha256": self.chart_bank_digest,
                "root_block_sha256": self.root_sha,
                "chart_sha256": self.chart_sha,
                "snapshot_verified": True,
                "canonical_training_committed": False,
            },
        )

    def guest(self, failure=None, *, changed=None):
        # A typed stub for JOURNAL tests only, not a claim of NaN16 execution.
        # The real VM adapter is separately tested against native guest CI.
        guest = object.__new__(NativeHeadBankGuest)
        guest.image_sha256 = self.guest_image

        def observe(*, request, raw_bank, allow_genesis_format=False):
            self.calls += 1
            if failure:
                raise failure
            result = self.changed if changed is None else changed
            receipt = {
                **request.prepared(), "kind": "native-head-observation",
                "native_status": 0, "head_generation_before": 0,
                "head_generation_after": 1, "bank_after_sha256": digest(result),
            }
            return {
                "raw_bank": result, "receipt": receipt,
                "native_guest_invoked_locally": True,
                "canonical_training_committed": False,
            }

        guest.observe = observe
        return guest

    def invoke(self, guest=None, **kwargs):
        return self.journal.execute(
            request=kwargs.pop("request", self.request),
            lease_receipt=kwargs.pop("lease_receipt", self.lease),
            network_head=kwargs.pop("network_head", 0),
            raw_bank=kwargs.pop("raw_bank", self.raw),
            native_guest=guest or self.guest(), **kwargs,
        )

    def inspect(self, **kwargs):
        return self.journal.inspect(
            request=kwargs.pop("request", self.request),
            lease_receipt=kwargs.pop("lease_receipt", self.lease),
            network_head=kwargs.pop("network_head", 0), **kwargs,
        )

    def test_native_result_staged_once_and_recovered_after_reopen(self):
        first = self.invoke()
        self.assertEqual(self.calls, 1)
        self.assertTrue(first["authenticated_lease_admitted"])
        self.assertFalse(first["canonical_training_committed"])
        self.assertFalse(first["chart_commit_verified"])
        self.assertEqual(first["raw_bank"], self.changed)
        self.assertEqual(self.inspect()["state"], "completed_staging_only")
        self.assertNotIn("raw_bank", self.inspect())
        self.assertEqual(self.inspect(include_bank=True)["raw_bank"], self.changed)
        self.journal = self.make_journal()
        second = self.invoke()
        self.assertEqual(self.calls, 1, "journal replay must never call native guest")
        self.assertTrue(second["replayed_from_journal"])
        self.assertEqual(second["bank_after_sha256"], first["bank_after_sha256"])

    def test_rejects_cross_head_lease_identity_and_epoch_before_native(self):
        for changed in (
            {"request": self.make_request(head_index=2)},
            {"request": self.make_request(lease_id=self.request.lease_id + 1)},
            {"request": self.make_request(lease_generation=self.request.lease_generation + 1)},
            {"request": self.make_request(universe_id="hermes-universe-wrong")},
            {"network_head": 1},
            {"raw_bank": bytes((1,)) + self.raw[1:]},
            {"request": self.make_request(native_image_sha256=digest(b"untrusted guest"))},
        ):
            with self.subTest(changed=changed):
                with self.assertRaises((HermesHeadObservationError, HermesHeadObservationConflict)):
                    self.invoke(**changed)
        self.assertEqual(self.calls, 0)
        self.epoch = 8
        with self.assertRaisesRegex(HermesHeadObservationConflict, "epoch"):
            self.invoke()
        self.assertEqual(self.inspect()["state"], "not_recorded")
        self.assertEqual(self.calls, 0)

    def test_chart_fence_and_revoked_lease_fail_closed(self):
        self.chart_generation += 1
        with self.assertRaisesRegex(HermesHeadObservationConflict, "chart fence"):
            self.invoke()
        self.assertEqual(self.calls, 0)
        self.chart_generation -= 1
        self.chart_bank_digest = digest(b"elsewhere")
        with self.assertRaisesRegex(HermesHeadObservationConflict, "chart fence"):
            self.invoke()
        self.chart_bank_digest = digest(self.raw)
        self.registry.release(installation_id=self.installation, receipt=self.lease)
        with self.assertRaises(HermesLeaseError):
            self.invoke()
        self.assertEqual(self.calls, 0)

    def test_unverified_or_rootless_chart_fence_refused_before_native_guest(self):
        real = self.journal.chart_fence_reader
        for mutation in (
            {"snapshot_verified": False},
            {"snapshot_verified": "yes"},
            {"schema": "untrusted-digest-labels/1"},
            {"schema": None},
            {"root_block_sha256": None},
            {"root_block_sha256": "G" * 64},
            {"chart_sha256": "A" * 64},
            {"canonical_training_committed": True},
        ):
            with self.subTest(mutation=mutation):
                self.journal.chart_fence_reader = (
                    lambda universe, mutation=mutation: {
                        **real(universe), **mutation
                    }
                )
                with self.assertRaises(HermesHeadObservationError):
                    self.invoke()
                self.assertEqual(self.calls, 0)
        self.journal.chart_fence_reader = real
        self.assertEqual(self.inspect()["state"], "not_recorded")

    def test_certified_chart_source_sha_persisted_across_restart(self):
        result = self.invoke()
        self.assertTrue(result["source_snapshot_bound"])
        self.assertEqual(result["source_chart_sha256"], self.chart_sha)
        self.assertEqual(result["source_root_block_sha256"], self.root_sha)
        self.journal = self.make_journal()
        durable = self.inspect(include_bank=True)
        self.assertEqual(durable["source_chart_sha256"], self.chart_sha)
        self.assertEqual(durable["source_root_block_sha256"], self.root_sha)
        self.assertTrue(durable["source_snapshot_bound"])
        self.assertEqual(self.calls, 1)

    def test_native_guest_cannot_stage_when_other_chart_bytes_change_same_generation(self):
        guest = self.guest()
        original = guest.observe

        def change_unrelated_chart(*args, **kwargs):
            result = original(*args, **kwargs)
            self.chart_sha = digest(b"same-bank-different-temporal-or-MP-cell")
            return result

        guest.observe = change_unrelated_chart
        with self.assertRaisesRegex(
                HermesHeadObservationConflict, "full chart/root identity changed"):
            self.invoke(guest=guest)
        self.assertEqual(self.calls, 1)
        self.assertEqual(self.inspect()["state"], "pending_or_ambiguous")
        with self.assertRaisesRegex(HermesHeadObservationConflict, "never replay"):
            self.invoke()
        self.assertEqual(self.calls, 1)

    def test_changed_root_block_with_same_parent_bank_generation_is_denied(self):
        guest = self.guest()
        original = guest.observe

        def change_root(*args, **kwargs):
            result = original(*args, **kwargs)
            self.root_sha = digest(b"new-native-root")
            return result

        guest.observe = change_root
        with self.assertRaisesRegex(
                HermesHeadObservationConflict, "full chart/root identity changed"):
            self.invoke(guest=guest)
        self.assertEqual(self.calls, 1)
        self.assertEqual(self.inspect()["state"], "pending_or_ambiguous")

    def test_source_identity_corruption_is_not_trusted_on_restart(self):
        self.invoke()
        with sqlite3.connect(self.path) as db:
            db.execute(
                "UPDATE hermes_head_observation SET source_chart_sha256=?",
                ("A" * 64,),
            )
        with self.assertRaisesRegex(
                HermesHeadObservationError, "corrupt native source chart"):
            self.inspect()
        with self.assertRaisesRegex(
                HermesHeadObservationError, "corrupt native source chart"):
            self.invoke()
        self.assertEqual(self.calls, 1)

    def test_crash_after_reservation_is_ambiguous_and_cannot_replay(self):
        with self.assertRaisesRegex(RuntimeError, "power loss"):
            self.invoke(guest=self.guest(RuntimeError("power loss")))
        self.assertEqual(self.calls, 1)
        self.assertEqual(self.inspect()["state"], "pending_or_ambiguous")
        self.journal = self.make_journal()
        with self.assertRaisesRegex(HermesHeadObservationConflict, "never replay"):
            self.invoke()
        self.assertEqual(self.calls, 1)

    def test_invalid_guest_payload_is_never_saved_as_success(self):
        with self.assertRaisesRegex(HermesHeadObservationError, "not a full bank"):
            self.invoke(guest=self.guest(changed=b"short"))
        self.assertEqual(self.inspect()["state"], "pending_or_ambiguous")

    def test_corrupt_stored_bank_fails_on_read_or_retry(self):
        self.invoke()
        with sqlite3.connect(self.path) as db:
            db.execute(
                "UPDATE hermes_head_observation SET bank_after=?",
                (b"tampered",),
            )
        with self.assertRaisesRegex(HermesHeadObservationError, "digest mismatch"):
            self.inspect(include_bank=True)
        with self.assertRaisesRegex(HermesHeadObservationError, "digest mismatch"):
            self.invoke()
        self.assertEqual(self.calls, 1)

    def test_routing_index_conversion_preserves_native_head_255(self):
        task = self.make_request(
            head_index=255, dispatch_id="native-head-dispatch-0255",
        )
        self.assertEqual(
            self.journal.inspect(request=task, lease_receipt=self.lease,
                                 network_head=254)["state"],
            "not_recorded",
        )
        with self.assertRaises(HermesHeadObservationConflict):
            self.journal.inspect(
                request=task, lease_receipt=self.lease, network_head=253
            )


    def confirm(self, request=None):
        return self.journal.confirm_local_checkpoint(
            request=self.request if request is None else request,
            lease_receipt=self.lease, network_head=0,
        )

    def test_staged_bank_reclaimed_only_after_exact_verified_next_checkpoint(self):
        self.invoke()
        with self.assertRaisesRegex(HermesHeadObservationConflict, "chart_generation"):
            self.confirm()
        self.chart_generation = self.request.chart_generation + 1
        with self.assertRaisesRegex(HermesHeadObservationConflict, "bank_sha256"):
            self.confirm()
        self.chart_bank_digest = digest(self.changed)
        recorded = self.confirm()
        self.assertTrue(recorded["local_checkpoint_verified"])
        self.assertFalse(recorded["canonical_training_committed"])
        self.assertEqual(recorded["checkpoint_generation"], 6)
        self.assertEqual(self.inspect()["state"], "checkpointed_locally")
        self.assertNotIn("raw_bank", self.inspect(include_bank=True))
        with sqlite3.connect(self.path) as db:
            row = db.execute(
                "SELECT bank_after,checkpoint_generation,checkpointed_at "
                "FROM hermes_head_observation"
            ).fetchone()
        self.assertIsNone(row[0])
        self.assertEqual(row[1], 6)
        self.assertIsNotNone(row[2])
        self.journal = self.make_journal()
        replayed = self.invoke()
        self.assertTrue(replayed["replayed_from_journal"])
        self.assertEqual(self.calls, 1)
        self.assertEqual(self.confirm()["checkpoint_generation"], 6)

    def test_permanent_tombstone_prevents_new_request_under_old_dispatch_id(self):
        self.invoke()
        self.chart_generation = 6
        self.chart_bank_digest = digest(self.changed)
        self.confirm()
        with self.assertRaisesRegex(HermesHeadObservationConflict, "different native head"):
            self.invoke(request=self.make_request(increment=4))
        self.assertEqual(self.calls, 1)

    def test_capacity_can_be_reused_only_after_a_verified_local_checkpoint(self):
        self.journal.MAX_OUTSTANDING = 1
        self.invoke()
        next_request = self.make_request(dispatch_id="native-head-dispatch-0002")
        with self.assertRaisesRegex(HermesHeadObservationError, "capacity"):
            self.invoke(request=next_request)
        self.chart_generation = 6
        self.chart_bank_digest = digest(self.changed)
        self.confirm()
        next_request = self.make_request(
            dispatch_id="native-head-dispatch-0002",
            chart_generation=6,
            bank_before_sha256=digest(self.changed),
        )
        next_bank = bytes([0xDA]) + self.changed[1:]
        result = self.invoke(
            request=next_request, raw_bank=self.changed,
            guest=self.guest(changed=next_bank),
        )
        self.assertEqual(result["bank_after_sha256"], digest(next_bank))
        self.assertEqual(self.calls, 2)

    def test_checkpoint_requires_validated_snapshot_not_only_digest_labels(self):
        self.invoke()
        self.chart_generation = 6
        self.chart_bank_digest = digest(self.changed)
        original = self.journal.chart_fence_reader
        self.journal.chart_fence_reader = lambda universe: {
            **original(universe), "snapshot_verified": False,
        }
        with self.assertRaisesRegex(HermesHeadObservationError, "SHA-verified"):
            self.confirm()
        self.journal.chart_fence_reader = original
        self.assertEqual(self.inspect()["state"], "completed_staging_only")

    def test_checkpoint_tombstone_corruption_is_detected(self):
        self.invoke()
        self.chart_generation = 6
        self.chart_bank_digest = digest(self.changed)
        self.confirm()
        with sqlite3.connect(self.path) as db:
            db.execute(
                "UPDATE hermes_head_observation SET bank_after_sha256=?",
                (digest(b"tampered checkpoint record"),),
            )
        with self.assertRaisesRegex(HermesHeadObservationError, "digest mismatch"):
            self.inspect()


    def test_epoch_handoff_during_guest_cannot_persist_native_result(self):
        guest = self.guest()
        native_observe = guest.observe

        def racing_guest(**kwargs):
            output = native_observe(**kwargs)
            self.epoch += 1
            return output

        guest.observe = racing_guest
        with self.assertRaisesRegex(HermesHeadObservationConflict, "epoch"):
            self.invoke(guest=guest)
        self.assertEqual(self.calls, 1)
        self.assertEqual(self.inspect()["state"], "pending_or_ambiguous")
        self.epoch -= 1
        with self.assertRaisesRegex(HermesHeadObservationConflict, "never replay"):
            self.invoke()
        self.assertEqual(self.calls, 1)

    def test_new_chart_checkpoint_during_guest_cannot_persist_stale_result(self):
        guest = self.guest()
        native_observe = guest.observe

        def racing_guest(**kwargs):
            output = native_observe(**kwargs)
            self.chart_generation += 1
            self.chart_bank_digest = digest(output["raw_bank"])
            return output

        guest.observe = racing_guest
        with self.assertRaisesRegex(HermesHeadObservationConflict, "chart fence"):
            self.invoke(guest=guest)
        self.assertEqual(self.calls, 1)
        self.assertEqual(self.inspect()["state"], "pending_or_ambiguous")

    def test_lease_revocation_during_guest_cannot_publish_result(self):
        guest = self.guest()
        native_observe = guest.observe

        def racing_guest(**kwargs):
            output = native_observe(**kwargs)
            self.registry.release(
                installation_id=self.installation,
                receipt=self.lease,
            )
            return output

        guest.observe = racing_guest
        with self.assertRaises(HermesLeaseError):
            self.invoke(guest=guest)
        with sqlite3.connect(self.path) as db:
            row = db.execute(
                "SELECT bank_after,checkpointed_at FROM hermes_head_observation"
            ).fetchone()
        self.assertEqual(self.calls, 1)
        self.assertIsNone(row[0])
        self.assertIsNone(row[1])

    def test_legacy_journal_columns_migrate_without_deleting_records(self):
        previous = Path(self.path.parent) / "old-hermes-head.sqlite"
        with sqlite3.connect(previous) as db:
            db.execute("""CREATE TABLE hermes_head_observation (
                installation_id TEXT NOT NULL, dispatch_id TEXT NOT NULL,
                request_sha256 TEXT NOT NULL, lease_id INTEGER NOT NULL,
                universe_id INTEGER NOT NULL, lease_generation INTEGER NOT NULL,
                head_index INTEGER NOT NULL, ring_epoch INTEGER NOT NULL,
                bank_before_sha256 TEXT NOT NULL, bank_after BLOB,
                bank_after_sha256 TEXT, native_receipt_json TEXT,
                PRIMARY KEY(installation_id,dispatch_id))""")
            db.execute("""INSERT INTO hermes_head_observation
                (installation_id,dispatch_id,request_sha256,lease_id,
                 universe_id,lease_generation,head_index,ring_epoch,
                 bank_before_sha256)
                 VALUES (?,?,?,?,?,?,?,?,?)""", (
                self.installation, "legacy-durable-dispatch-001",
                digest(b"legacy request"), self.lease["lease_id"],
                self.lease["universe_id"], self.lease["generation"],
                1, 7, digest(self.raw),
            ))
        HermesHeadObservationJournal(
            previous, lease_registry=self.registry,
            ring_epoch_reader=lambda: self.epoch,
            chart_fence_reader=self.journal.chart_fence_reader,
        )
        with sqlite3.connect(previous) as db:
            row = db.execute("SELECT COUNT(*),source_chart_sha256,"
                             "source_root_block_sha256 FROM hermes_head_observation").fetchone()
        self.assertEqual(row[0], 1)
        self.assertIsNone(row[1])
        self.assertIsNone(row[2])
        with sqlite3.connect(previous) as db:
            types = {
                item[1]: item[2].upper()
                for item in db.execute(
                    "PRAGMA table_info(hermes_head_observation)"
                )
            }
            self.assertEqual(types["source_chart_sha256"], "TEXT")
            self.assertEqual(types["source_root_block_sha256"], "TEXT")
            # SQLite INTEGER affinity would silently coerce all-digit
            # SHA-shaped values to a number and destroy leading zeroes.
            chart, root = "0" * 64, "1" * 64
            db.execute(
                "UPDATE hermes_head_observation "
                "SET source_chart_sha256=?, source_root_block_sha256=?",
                (chart, root),
            )
            roundtrip = db.execute(
                "SELECT source_chart_sha256, source_root_block_sha256, "
                "typeof(source_chart_sha256), typeof(source_root_block_sha256) "
                "FROM hermes_head_observation"
            ).fetchone()
            self.assertEqual(roundtrip, (chart, root, "text", "text"))

    def test_already_upgraded_integer_sha_affinity_is_repaired_without_row_loss(self):
        previous = self.path.parent / "wrong-type-hermes-head.sqlite"
        with sqlite3.connect(previous) as db:
            db.execute("""CREATE TABLE hermes_head_observation (
                installation_id TEXT NOT NULL, dispatch_id TEXT NOT NULL,
                request_sha256 TEXT NOT NULL, lease_id INTEGER NOT NULL,
                universe_id INTEGER NOT NULL, lease_generation INTEGER NOT NULL,
                head_index INTEGER NOT NULL, ring_epoch INTEGER NOT NULL,
                bank_before_sha256 TEXT NOT NULL,
                source_chart_sha256 INTEGER, source_root_block_sha256 INTEGER,
                bank_after BLOB, bank_after_sha256 TEXT, native_receipt_json TEXT,
                checkpoint_generation INTEGER, checkpointed_at INTEGER,
                PRIMARY KEY(installation_id,dispatch_id))""")
            expected = (
                self.installation, "legacy-permanent-tombstone-001",
                digest(b"legacy request"), self.lease["lease_id"],
                self.lease["universe_id"], self.lease["generation"],
                1, self.epoch, digest(self.raw),
                digest(b"source chart sha"), digest(b"mounted root block sha"),
                None, digest(self.changed), '{"native_status":0}', 6, 123456,
            )
            db.execute(
                "INSERT INTO hermes_head_observation VALUES (?,?,?,?,?,?,?,?,"
                "?,?,?,?,?,?,?,?)", expected,
            )
        for _ in range(2):
            HermesHeadObservationJournal(
                previous, lease_registry=self.registry,
                ring_epoch_reader=lambda: self.epoch,
                chart_fence_reader=self.journal.chart_fence_reader,
            )
            with sqlite3.connect(previous) as db:
                typed = {
                    r[1]: r[2].upper() for r in db.execute(
                        "PRAGMA table_info(hermes_head_observation)"
                    )
                }
                self.assertEqual(typed["source_chart_sha256"], "TEXT")
                self.assertEqual(typed["source_root_block_sha256"], "TEXT")
                stored = db.execute(
                    "SELECT * FROM hermes_head_observation"
                ).fetchone()
                self.assertEqual(stored, expected)
                self.assertEqual(db.execute(
                    "SELECT COUNT(*) FROM hermes_head_observation"
                ).fetchone()[0], 1)
        with sqlite3.connect(previous) as db:
            db.execute(
                "UPDATE hermes_head_observation "
                "SET source_chart_sha256=?, source_root_block_sha256=?",
                ("0" * 64, "1" * 64),
            )
            stored = db.execute(
                "SELECT source_chart_sha256, source_root_block_sha256 "
                "FROM hermes_head_observation"
            ).fetchone()
        self.assertEqual(stored, ("0" * 64, "1" * 64))


    def test_concurrent_router_startup_retypes_legacy_sha_columns_once(self):
        """Overlapping router constructors cannot lose records during DDL."""
        import threading
        from concurrent.futures import ThreadPoolExecutor

        previous = self.path.parent / "parallel-wrong-affinity.sqlite"
        with sqlite3.connect(previous) as db:
            db.execute("""CREATE TABLE hermes_head_observation (
                installation_id TEXT NOT NULL, dispatch_id TEXT NOT NULL,
                request_sha256 TEXT NOT NULL, lease_id INTEGER NOT NULL,
                universe_id INTEGER NOT NULL, lease_generation INTEGER NOT NULL,
                head_index INTEGER NOT NULL, ring_epoch INTEGER NOT NULL,
                bank_before_sha256 TEXT NOT NULL,
                source_chart_sha256 INTEGER, source_root_block_sha256 INTEGER,
                bank_after BLOB, bank_after_sha256 TEXT, native_receipt_json TEXT,
                checkpoint_generation INTEGER, checkpointed_at INTEGER,
                PRIMARY KEY(installation_id,dispatch_id))""")
            expected = (
                self.installation, "legacy-concurrent-tombstone-001",
                digest(b"legacy concurrent request"), self.lease["lease_id"],
                self.lease["universe_id"], self.lease["generation"],
                1, self.epoch, digest(self.raw),
                digest(b"source chart"), digest(b"root block"),
                None, digest(self.changed), '{"native_status":0}', 6, 123456,
            )
            db.execute(
                "INSERT INTO hermes_head_observation VALUES (?,?,?,?,?,?,?,?,"
                "?,?,?,?,?,?,?,?)", expected,
            )
        barrier = threading.Barrier(8, timeout=20)

        def start_router(_):
            barrier.wait()
            HermesHeadObservationJournal(
                previous, lease_registry=self.registry,
                ring_epoch_reader=lambda: self.epoch,
                chart_fence_reader=self.journal.chart_fence_reader,
            )

        # All eight router processes independently encounter a migration
        # candidate. They must serialize the schema upgrade and retain the
        # permanent replay tombstone, never drop/recreate the journal.
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(start_router, range(8)))
        with sqlite3.connect(previous) as db:
            self.assertEqual(
                db.execute("SELECT * FROM hermes_head_observation").fetchone(),
                expected,
            )
            types = {row[1]: row[2].upper() for row in db.execute(
                "PRAGMA table_info(hermes_head_observation)"
            )}
            self.assertEqual(types["source_chart_sha256"], "TEXT")
            self.assertEqual(types["source_root_block_sha256"], "TEXT")
            db.execute(
                "UPDATE hermes_head_observation "
                "SET source_chart_sha256=?,source_root_block_sha256=?",
                ("0" * 64, "1" * 64),
            )
            self.assertEqual(db.execute(
                "SELECT source_chart_sha256,source_root_block_sha256 "
                "FROM hermes_head_observation"
            ).fetchone(), ("0" * 64, "1" * 64))


if __name__ == "__main__":
    unittest.main()
