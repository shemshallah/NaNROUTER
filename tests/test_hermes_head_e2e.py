"""Real 3-repo Hermes dispatch: authenticated lease -> NaN16 -> N16SNAP1.

This integration test is opt-in when the GitHub workflow has compiled the
PINNED native NaN0S guest and checked out the HERMES chart source. It tests
actual native guest instructions and class-preserving transport; no mock VM.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from runner_riddle.head_bank_handoff import BANK_BYTES, HeadBankHandoff
from runner_riddle.hermes_head_observation import HermesHeadObservationJournal
from runner_riddle.hermes_leases import HermesLeaseRegistry
from runner_riddle.native_head_guest import NativeHeadBankGuest


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@unittest.skipUnless(
    all(os.environ.get(name) for name in (
        "NAN_HEAD_GUEST_LIBRARY", "NAN_HEAD_GUEST_IMAGE",
        "NAN_HEAD_GUEST_LABELS", "HERMES_CHECKPOINT_E2E",
    )),
    "real pinned native NaN0S guest and HERMES source unavailable",
)
class AuthenticatedNativeHeadCheckpointE2E(unittest.TestCase):
    def setUp(self):
        # Import here so regular router-only test discovery does not require
        # the HERMES Python package, which comes from a pinned CI checkout.
        from nanlmind_hermes.universe_chart import Chart8MiB
        from nanlmind_hermes.universe_root import attach_universe_root
        from nanlmind_hermes.chart_storage import save_chart_snapshot
        from nanlmind_hermes.native_head_fence import SnapshotHeadBankFence
        self.save = save_chart_snapshot
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.state = self.base / "hermes"
        self.chart = Chart8MiB.genesis()
        attach_universe_root(self.chart)
        self.parent = self.chart.root_hash
        self.chart.snapshot_generation = self.save(
            self.state, self.parent, self.chart.bytes, 0,
        )
        self.installation = "installation-head-e2e-001"
        self.registry = HermesLeaseRegistry(
            self.base / "leases.sqlite",
            b"only-a-ci-native-head-lease-signing-key-000001",
        )
        self.receipt = self.registry.open(
            installation_id=self.installation,
            node_point=3,
            request_id="native-head-e2e-lease-open-001",
        )
        self.universe_id = self.receipt["universe_id"]
        self.fence = SnapshotHeadBankFence(
            state_dir=self.state,
            parent_root_sha256=self.parent,
            universe_id=self.universe_id,
        )
        self.epoch = 31
        self.journal = HermesHeadObservationJournal(
            self.base / "dispatch.sqlite",
            lease_registry=self.registry,
            ring_epoch_reader=lambda: self.epoch,
            chart_fence_reader=self.fence,
        )
        library = Path(os.environ["NAN_HEAD_GUEST_LIBRARY"])
        image = Path(os.environ["NAN_HEAD_GUEST_IMAGE"])
        labels = Path(os.environ["NAN_HEAD_GUEST_LABELS"])
        self.image_sha256 = sha(image.read_bytes())
        self.guest = NativeHeadBankGuest(
            library_path=str(library), library_sha256=sha(library.read_bytes()),
            image_path=str(image), image_sha256=self.image_sha256,
            labels_path=str(labels), labels_sha256=sha(labels.read_bytes()),
        )

    def request(self, *, dispatch_id, raw, generation, feature, increment):
        return HeadBankHandoff(
            universe_id="hermes-universe-" + str(self.universe_id),
            installation_id=self.installation,
            dispatch_id=dispatch_id,
            lease_id=self.receipt["lease_id"],
            lease_generation=self.receipt["generation"],
            ring_epoch=self.epoch,
            head_index=1, feature_index=feature, increment=increment,
            parent_root_sha256=self.parent,
            bank_before_sha256=sha(raw), chart_generation=generation,
            observation_sha256=sha(dispatch_id.encode("ascii") + raw[:8]),
            native_image_sha256=self.image_sha256,
        )

    def journal_checkpoint(self, request, *, expected_after_sha256):
        from nanlmind_hermes.native_head_checkpoint import NativeHeadCheckpointCoordinator
        from nanlmind_hermes.universe_chart import restore_local_chart
        committer = NativeHeadCheckpointCoordinator(
            fence=self.fence, journal=self.journal
        )
        published = committer.commit(
            request=request, lease_receipt=self.receipt, network_head=0
        )
        self.assertTrue(published["local_checkpoint_verified"])
        self.assertTrue(published["authenticated_router_journal_checked"])
        self.assertFalse(published["canonical_training_committed"])
        self.assertFalse(published["nannet_merge_issued"])
        self.assertEqual(published["bank_after_sha256"], expected_after_sha256)
        # HERMES retains a single chart: synchronize its in-process view
        # with the independently committed SHA-verified N16SNAP1 overlay.
        self.assertEqual(
            restore_local_chart(self.chart, self.state),
            published["chart_generation"],
        )
        return published

    def test_pinned_guest_two_native_revisions_then_tombstones_survive_restart(self):
        from nanlmind_hermes.head_bank_transport import (
            export_guest_bank_bytes,
        )
        from nanlmind_hermes.universe_chart import (
            Chart8MiB, restore_local_chart,
        )
        raw = bytes(BANK_BYTES)
        first_fence = self.fence(self.universe_id)
        self.assertEqual(first_fence["bank_sha256"], sha(raw))
        self.assertEqual(first_fence["chart_generation"], 1)
        first_request = self.request(
            dispatch_id="native-head-e2e-dispatch-001", raw=raw,
            generation=1, feature=127, increment=3,
        )
        first = self.journal.execute(
            request=first_request, lease_receipt=self.receipt,
            network_head=0, raw_bank=raw, native_guest=self.guest,
            allow_genesis_format=True,
        )
        self.assertTrue(first["native_guest_invoked_locally"])
        self.assertEqual(first["receipt"]["head_generation_before"], 0)
        self.assertEqual(first["receipt"]["head_generation_after"], 1)
        self.assertFalse(first["canonical_training_committed"])
        self.assertEqual(len(first["raw_bank"]), BANK_BYTES)
        self.assertNotEqual(first["bank_after_sha256"], sha(raw))
        self.assertEqual(
            self.journal.inspect(
                request=first_request, lease_receipt=self.receipt,
                network_head=0,
            )["state"], "completed_staging_only",
        )
        verified = self.journal_checkpoint(
            first_request, expected_after_sha256=first["bank_after_sha256"],
        )
        self.assertEqual(verified["chart_generation"], 2)
        self.assertEqual(
            self.fence(self.universe_id)["bank_sha256"],
            first["bank_after_sha256"],
        )
        self.assertTrue(verified["local_checkpoint_verified"])
        self.assertFalse(verified["canonical_training_committed"])
        self.journal = HermesHeadObservationJournal(
            self.base / "dispatch.sqlite",
            lease_registry=self.registry,
            ring_epoch_reader=lambda: self.epoch,
            chart_fence_reader=self.fence,
        )
        # A duplicate returns the permanent tombstone without running NaN16.
        repeat = self.journal.execute(
            request=first_request, lease_receipt=self.receipt,
            network_head=0, raw_bank=raw, native_guest=self.guest,
            allow_genesis_format=True,
        )
        self.assertTrue(repeat["replayed_from_journal"])
        self.assertNotIn("raw_bank", repeat)
        self.assertEqual(repeat["bank_after_sha256"], first["bank_after_sha256"])

        second_request = self.request(
            dispatch_id="native-head-e2e-dispatch-002",
            raw=first["raw_bank"], generation=2, feature=0, increment=2,
        )
        second = self.journal.execute(
            request=second_request, lease_receipt=self.receipt,
            network_head=0, raw_bank=first["raw_bank"], native_guest=self.guest,
        )
        self.assertEqual(second["receipt"]["head_generation_before"], 1)
        self.assertEqual(second["receipt"]["head_generation_after"], 2)
        from nanlmind_hermes.native_head_checkpoint import NativeHeadCheckpointCoordinator
        second_checkpoint = self.journal_checkpoint(
            second_request, expected_after_sha256=second["bank_after_sha256"],
        )
        self.assertEqual(second_checkpoint["chart_generation"], 3)
        # The first completed update remains a permanent replay tombstone
        # even though two more chart slots have superseded its exact bank.
        historical = NativeHeadCheckpointCoordinator(
            fence=self.fence, journal=self.journal,
        ).commit(
            request=first_request, lease_receipt=self.receipt, network_head=0,
        )
        self.assertTrue(historical["historical_local_checkpoint_verified"])
        self.assertFalse(historical["current_chart_contains_result"])
        self.assertEqual(historical["chart_generation"], 2)
        self.assertEqual(historical["current_chart_generation"], 3)
        restored = Chart8MiB.genesis()
        self.assertEqual(restore_local_chart(restored, self.state), 3)
        self.assertEqual(export_guest_bank_bytes(restored), second["raw_bank"])
        self.assertEqual(self.fence(self.universe_id)["chart_generation"], 3)
        self.assertEqual(
            self.journal.inspect(
                request=second_request, lease_receipt=self.receipt,
                network_head=0,
            )["state"], "checkpointed_locally",
        )
        self.assertFalse(
            self.journal.inspect(
                request=second_request, lease_receipt=self.receipt,
                network_head=0,
            )["canonical_training_committed"]
        )

        # The exact class-bearing bytes from native learning must also survive
        # the offline N16PACK1 container. The pack is NOT a live restore.
        from nanlmind_hermes.universe_pack import (
            export_n16pack, inspect_n16pack,
        )
        stores = {}
        for store_name, filename in (
            ("MC0DB", "mapping.sqlite"),
            ("BS0DB", "content.sqlite"),
        ):
            path = self.base / filename
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "CREATE TABLE math_schema(store TEXT PRIMARY KEY,"
                    "version INTEGER NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO math_schema VALUES (?,1)", (store_name,)
                )
                connection.execute(
                    "CREATE TABLE evidence(key TEXT PRIMARY KEY,"
                    "value TEXT NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO evidence VALUES (?,?)",
                    ("native_bank_sha256", second["bank_after_sha256"]),
                )
            stores[store_name] = path
        packed = self.base / "single-real-native-universe.n16pack"
        archive = export_n16pack(
            state_dir=self.state,
            parent_root_sha256=self.parent,
            expected_chart_generation=3,
            mc0db=stores["MC0DB"], bs0db=stores["BS0DB"],
            destination=packed,
        )
        self.assertTrue(archive["verified"])
        self.assertEqual(archive["chart_generation"], 3)
        self.assertEqual(archive["sections"][0]["name"], "chart")
        self.assertEqual(
            archive["sections"][0]["sha256"], sha(bytes(self.chart.bytes)),
        )
        self.assertFalse(archive["import_to_live_allowed"])
        self.assertFalse(archive["cross_store_atomicity_attested"])
        self.assertFalse(archive["canonical_training_committed"])
        self.assertEqual(inspect_n16pack(packed)["sections"], archive["sections"])


if __name__ == "__main__":
    unittest.main()
