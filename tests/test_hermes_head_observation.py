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
                "parent_root_sha256": self.parent,
                "chart_generation": self.chart_generation,
                "bank_sha256": self.chart_bank_digest,
                "snapshot_verified": True,
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
        with self.assertRaisesRegex(HermesHeadObservationError, "trusted durable"):
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


if __name__ == "__main__":
    unittest.main()
