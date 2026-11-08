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
        from nanlmind_hermes.universe_chart import (
            Chart8MiB, LocalRunner, TemporalRegister,
        )
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
        class TestContext:
            def get_config(inner, key, default=None):
                return str(self.state) if key == "state_dir" else default
        self.runner = LocalRunner(
            self.chart, TemporalRegister.open(TestContext(), self.chart),
        )
        self.chart.snapshot_generation = self.save(
            self.state, self.parent, self.chart.bytes, 0,
        )
        self.chart._dirty = False
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

    def request(self, *, dispatch_id, raw, generation, feature, increment,
                head_index=1):
        return HeadBankHandoff(
            universe_id="hermes-universe-" + str(self.universe_id),
            installation_id=self.installation,
            dispatch_id=dispatch_id,
            lease_id=self.receipt["lease_id"],
            lease_generation=self.receipt["generation"],
            ring_epoch=self.epoch,
            head_index=head_index, feature_index=feature, increment=increment,
            parent_root_sha256=self.parent,
            bank_before_sha256=sha(raw), chart_generation=generation,
            observation_sha256=sha(dispatch_id.encode("ascii") + raw[:8]),
            native_image_sha256=self.image_sha256,
        )

    def journal_checkpoint(self, request, *, expected_after_sha256, network_head=0):
        from nanlmind_hermes.native_head_checkpoint import NativeHeadCheckpointCoordinator
        committer = NativeHeadCheckpointCoordinator(
            fence=self.fence, journal=self.journal
        )
        identity = id(self.runner.chart)
        published = self.runner.commit_native_head_observation(
            coordinator=committer, request=request,
            lease_receipt=self.receipt, network_head=network_head,
        )
        self.assertTrue(published["local_checkpoint_verified"])
        self.assertTrue(published["single_chart_object_preserved"])
        self.assertTrue(published["head_bank_rebased"])
        self.assertEqual(id(self.runner.chart), identity)
        self.assertIs(self.runner.register.chart, self.runner.chart)
        self.assertIs(self.runner.heads.chart, self.runner.chart)
        self.assertFalse(published["canonical_training_committed"])
        self.assertFalse(published["nannet_merge_issued"])
        self.assertEqual(published["native_bank_sha256"], expected_after_sha256)
        self.assertEqual(
            self.fence(self.universe_id)["chart_generation"],
            published["chart_generation"],
        )
        return published

    def test_native_all_16_near_far_faces_survive_head_revisions(self):
        """NaN16 guest owns checksums and preserves every class pairing."""
        from runner_riddle.head_bank_handoff import BANK_WORDS
        from runner_riddle.native_head_guest import (
            BANK_BASE, STAGING_BASE, READBACK_BASE,
        )
        from runner_riddle.n16t_guest import _NaN16GuestVM

        # Each raw word has independent far/near members of the four
        # sign x quiet classes. Only the test fixture constructs a word;
        # the real NaN16 nh_put / nhr_observe guest does all state math.
        heads = (0x7FF1, 0xFFF1, 0x7FF8, 0xFFF8)

        def word(payload, klass):
            return (
                heads[klass & 3].to_bytes(2, "big")
                + payload.to_bytes(4, "little")
                + heads[(klass >> 2) & 3].to_bytes(2, "little")
            )

        classes = bytes().join(word(1, i % 16) for i in range(128))
        vm = _NaN16GuestVM(
            self.guest.library, self.guest.image, self.guest.labels,
            required_labels=("nh_format", "nh_put", "nhr_attach", "nhr_read"),
        )
        try:
            vm.call("nh_format", {1: BANK_BASE})
            self.assertEqual(vm.reg(5), 0)
            vm.write_raw_words(STAGING_BASE, classes)
            # The native guest computes slot checksum and commit marker.
            vm.call("nh_put", {1: BANK_BASE, 2: 1, 3: STAGING_BASE})
            self.assertEqual(vm.reg(5), 0)
            self.assertEqual(vm.reg(4), 1)
            seeded = vm.read_raw_words(BANK_BASE, BANK_WORDS)
        finally:
            vm.close()

        request = self.request(
            dispatch_id="native-16-class-faces-e2e-001", raw=seeded,
            generation=1, feature=7, increment=3,
        )
        # A completely fresh VM reimports the actual native 8-byte words.
        observed = self.guest.observe(request=request, raw_bank=seeded)
        self.assertEqual(observed["receipt"]["head_generation_before"], 1)
        self.assertEqual(observed["receipt"]["head_generation_after"], 2)
        self.assertFalse(observed["canonical_training_committed"])

        readback = _NaN16GuestVM(
            self.guest.library, self.guest.image, self.guest.labels,
            required_labels=("nhr_attach", "nhr_read"),
        )
        try:
            readback.write_raw_words(BANK_BASE, observed["raw_bank"])
            readback.call("nhr_attach", {1: BANK_BASE})
            self.assertEqual(readback.reg(5), 0)
            readback.call("nhr_read", {1: 1, 2: READBACK_BASE})
            self.assertEqual(readback.reg(5), 0)
            self.assertEqual(readback.reg(6), 2)
            committed = readback.read_raw_words(READBACK_BASE, 128)
        finally:
            readback.close()

        self.assertEqual(len(committed), 1024)
        for feature in range(128):
            old = classes[feature*8:(feature+1)*8]
            new = committed[feature*8:(feature+1)*8]
            self.assertEqual(new[:2], old[:2])
            self.assertEqual(new[6:], old[6:])
            self.assertEqual(new[2:6], (4 if feature == 7 else 1).to_bytes(4, "little"))
        # Corrupt ONLY one class face in the latest slot while retaining
        # the original SHA-valid 8-byte transport length. Native nh_valid
        # must reject generation 2's class-sensitive checksum and fall back
        # to immutable generation 1; no host checksum implementation.
        damaged = bytearray(observed["raw_bank"])
        slot1_feature7_word = 8 + 133 + 5 + 7
        damaged[slot1_feature7_word*8 + 6] ^= 0x80
        damaged = bytes(damaged)
        fallback = self.guest.observe(
            request=self.request(
                dispatch_id="native-16-class-faces-e2e-002", raw=damaged,
                generation=1, feature=7, increment=2,
            ),
            raw_bank=damaged,
        )
        self.assertEqual(fallback["receipt"]["head_generation_before"], 1)
        self.assertEqual(fallback["receipt"]["head_generation_after"], 2)

    def test_real_head1_and_head255_share_one_chart_without_slot_aliasing(self):
        """The native bank retains disjoint HW0:1 and HW0:255 revisions."""
        from nanlmind_hermes.head_bank_transport import (
            export_guest_bank_bytes,
        )
        from nanlmind_hermes.universe_chart import (
            Chart8MiB, restore_local_chart,
        )
        # Exact *byte geometry* from NaN0S n16_head_store.nas; the VM,
        # never this host test, chooses slots and validates NaN classes.
        stride_words = 266
        header_words = 8

        def head_span(head):
            begin = (header_words + (head - 1) * stride_words) * 8
            return begin, begin + stride_words * 8

        first_span = head_span(1)
        last_span = head_span(255)
        self.assertTrue(0 <= first_span[0] < first_span[1] <= last_span[0])
        self.assertEqual(last_span[1], BANK_BYTES)
        raw0 = bytes(BANK_BYTES)
        source0 = self.fence(self.universe_id)
        req1 = self.request(
            dispatch_id="native-multihead-0001", raw=raw0,
            generation=1, feature=127, increment=3, head_index=1,
        )
        native1 = self.journal.execute(
            request=req1, lease_receipt=self.receipt, network_head=0,
            raw_bank=raw0, native_guest=self.guest,
            allow_genesis_format=True,
        )
        self.assertTrue(native1["native_guest_invoked_locally"])
        self.assertTrue(native1["source_snapshot_bound"])
        self.assertEqual(native1["source_chart_sha256"], source0["chart_sha256"])
        self.assertEqual(native1["receipt"]["head_generation_after"], 1)
        # Genesis formatting initializes NaN class-bearing slot metadata
        # throughout the bank, so the comparison baseline is this newly
        # formatted first revision, NOT the all-zero unformatted input.
        self.assertNotEqual(
            native1["raw_bank"][first_span[0]:first_span[1]],
            raw0[first_span[0]:first_span[1]],
        )
        self.assertEqual(
            self.journal_checkpoint(
                req1, expected_after_sha256=native1["bank_after_sha256"],
            )["chart_generation"], 2,
        )
        source1 = self.fence(self.universe_id)
        req255 = self.request(
            dispatch_id="native-multihead-0255", raw=native1["raw_bank"],
            generation=2, feature=0, increment=2, head_index=255,
        )
        native255 = self.journal.execute(
            request=req255, lease_receipt=self.receipt, network_head=254,
            raw_bank=native1["raw_bank"], native_guest=self.guest,
        )
        self.assertTrue(native255["native_guest_invoked_locally"])
        self.assertTrue(native255["source_snapshot_bound"])
        self.assertEqual(
            native255["source_chart_sha256"], source1["chart_sha256"],
        )
        self.assertEqual(native255["receipt"]["head_generation_after"], 1)
        # Verify the second native guest changed ONLY head255's 266-word
        # dual-slot storage region, preserving the entire first head.
        before, after = native1["raw_bank"], native255["raw_bank"]
        self.assertEqual(after[:last_span[0]], before[:last_span[0]])
        self.assertNotEqual(after[last_span[0]:last_span[1]],
                            before[last_span[0]:last_span[1]])
        self.assertEqual(after[first_span[0]:first_span[1]],
                         before[first_span[0]:first_span[1]])
        self.assertEqual(
            self.journal_checkpoint(
                req255, expected_after_sha256=native255["bank_after_sha256"],
                network_head=254,
            )["chart_generation"], 3,
        )
        self.assertIs(self.runner.register.chart, self.runner.chart)
        self.assertIs(self.runner.heads.chart, self.runner.chart)
        self.assertEqual(export_guest_bank_bytes(self.runner.chart), after)
        restored = Chart8MiB.genesis()
        self.assertEqual(restore_local_chart(restored, self.state), 3)
        self.assertEqual(export_guest_bank_bytes(restored), after)
        for request, network_head in ((req1, 0), (req255, 254)):
            historical = self.journal.inspect(
                request=request, lease_receipt=self.receipt,
                network_head=network_head,
            )
            self.assertEqual(historical["state"], "checkpointed_locally")
            self.assertTrue(historical["source_snapshot_bound"])
            self.assertFalse(historical["canonical_training_committed"])
        self.assertEqual(self.fence(self.universe_id)["chart_generation"], 3)

    def test_real_native_head255_routes_and_survives_single_chart_restore(self):
        """Network 254 maps to real NaN16 HW0:255 with durable bank bytes."""
        from nanlmind_hermes.native_head_checkpoint import (
            NativeHeadCheckpointCoordinator,
        )
        from nanlmind_hermes.universe_chart import (
            Chart8MiB, restore_local_chart,
        )
        from nanlmind_hermes.head_bank_transport import export_guest_bank_bytes
        from runner_riddle.hermes_head_observation import (
            HermesHeadObservationConflict,
        )
        raw = bytes(BANK_BYTES)
        source = self.fence(self.universe_id)
        request = self.request(
            dispatch_id="native-head-hw255-e2e-001", raw=raw,
            generation=source["chart_generation"], feature=127,
            increment=2, head_index=255,
        )
        # Invalid network index must not admit this head or run the guest.
        with self.assertRaises(HermesHeadObservationConflict):
            self.journal.inspect(
                request=request, lease_receipt=self.receipt,
                network_head=253,
            )
        self.assertEqual(self.fence(self.universe_id)["chart_generation"], 1)
        result = self.journal.execute(
            request=request, lease_receipt=self.receipt,
            network_head=254, raw_bank=raw, native_guest=self.guest,
            allow_genesis_format=True,
        )
        self.assertTrue(result["native_guest_invoked_locally"])
        self.assertTrue(result["source_snapshot_bound"])
        self.assertEqual(result["source_chart_sha256"], source["chart_sha256"])
        self.assertEqual(result["source_root_block_sha256"], source["root_block_sha256"])
        self.assertEqual(result["receipt"]["head_generation_before"], 0)
        self.assertEqual(result["receipt"]["head_generation_after"], 1)
        self.assertNotEqual(result["bank_after_sha256"], sha(raw))
        coordinator = NativeHeadCheckpointCoordinator(
            fence=self.fence, journal=self.journal,
        )
        published = self.runner.commit_native_head_observation(
            coordinator=coordinator, request=request,
            lease_receipt=self.receipt, network_head=254,
        )
        self.assertTrue(published["head_bank_rebased"])
        self.assertTrue(published["single_chart_object_preserved"])
        self.assertEqual(published["chart_generation"], 2)
        self.assertEqual(
            self.fence(self.universe_id)["bank_sha256"],
            result["bank_after_sha256"],
        )
        restored = Chart8MiB.genesis()
        self.assertEqual(restore_local_chart(restored, self.state), 2)
        self.assertEqual(export_guest_bank_bytes(restored), result["raw_bank"])
        self.assertFalse(published["canonical_training_committed"])
        self.assertFalse(published["nannet_merge_issued"])
        repeat = self.journal.execute(
            request=request, lease_receipt=self.receipt,
            network_head=254, raw_bank=raw, native_guest=self.guest,
            allow_genesis_format=True,
        )
        self.assertTrue(repeat["replayed_from_journal"])
        self.assertEqual(self.fence(self.universe_id)["chart_generation"], 2)

    def test_checksum_valid_immutable_forgery_is_denied_before_native_guest(self):
        """Independent real-router entry point cannot reserve or run for forged mapping."""
        from unittest.mock import patch
        from nanlmind_hermes.chart_storage import HEADER, MAGIC, SLOT_NAMES
        from nanlmind_hermes.native_head_fence import NativeHeadFenceError
        from nanlmind_hermes.universe_chart import (
            OFF_CANON, OFF_INDEX, OFF_PAIR_TABLE,
        )
        raw_bank = bytes(BANK_BYTES)
        folder = self.state / "language" / "chart-checkpoints"
        slot0 = folder / SLOT_NAMES[0]
        original = slot0.read_bytes()
        before = self.fence(self.universe_id)
        self.assertEqual(before["chart_generation"], 1)
        for name, offset in (
            ("header-genome", 12), ("address-index", OFF_INDEX),
            ("canonical-address", OFF_CANON), ("mirror-pair", OFF_PAIR_TABLE),
        ):
            with self.subTest(section=name):
                forged = bytearray(self.chart.bytes)
                forged[offset] ^= 0x01
                # Every forged page is a legitimate-size chart, with a
                # recomputed SHA-valid N16SNAP1 envelope and mounted root.
                slot0.write_bytes(
                    HEADER.pack(
                        MAGIC, 1, bytes.fromhex(self.parent),
                        hashlib.sha256(forged).digest(),
                    ) + forged
                )
                request = self.request(
                    dispatch_id="native-immutable-fence-" + name,
                    raw=raw_bank, generation=1, feature=17, increment=1,
                )
                try:
                    with patch.object(
                        self.guest, "observe",
                        side_effect=AssertionError("native VM must not run"),
                    ) as observation:
                        with self.assertRaisesRegex(
                            NativeHeadFenceError, "immutable reconstruction"
                        ):
                            self.journal.execute(
                                request=request, lease_receipt=self.receipt,
                                network_head=0, raw_bank=raw_bank,
                                native_guest=self.guest, allow_genesis_format=True,
                            )
                        observation.assert_not_called()
                    with sqlite3.connect(self.base / "dispatch.sqlite") as db:
                        self.assertEqual(
                            db.execute(
                                "SELECT COUNT(*) FROM hermes_head_observation"
                            ).fetchone()[0], 0,
                        )
                finally:
                    slot0.write_bytes(original)
        self.assertEqual(self.fence(self.universe_id)["chart_sha256"],
                         before["chart_sha256"])

    def test_two_distinct_valid_pages_at_one_generation_never_reach_native_vm(self):
        """Ambiguous durable chart history must not create a router reservation."""
        from nanlmind_hermes.chart_storage import HEADER, MAGIC, SLOT_NAMES
        from nanlmind_hermes.native_head_fence import NativeHeadFenceError
        before = self.fence(self.universe_id)
        raw = bytes(BANK_BYTES)
        request = self.request(
            dispatch_id="native-head-ambiguous-chart-001", raw=raw,
            generation=before["chart_generation"], feature=17, increment=1,
        )
        alternate = bytearray(self.chart.bytes)
        alternate[0x7000] ^= 0x01  # unrelated valid chart region
        root = self.state / "language" / "chart-checkpoints"
        (root / SLOT_NAMES[1]).write_bytes(
            HEADER.pack(MAGIC, before["chart_generation"],
                        bytes.fromhex(self.parent),
                        hashlib.sha256(alternate).digest()) + alternate
        )
        with self.assertRaises(NativeHeadFenceError):
            self.journal.execute(
                request=request, lease_receipt=self.receipt, network_head=0,
                raw_bank=raw, native_guest=self.guest, allow_genesis_format=True,
            )
        with sqlite3.connect(self.base / "dispatch.sqlite") as db:
            count = db.execute(
                "SELECT COUNT(*) FROM hermes_head_observation"
            ).fetchone()[0]
        self.assertEqual(count, 0)
        # Both valid pages survive for explicit/manual resolution; neither
        # may silently become a new local generation or a false NANNET claim.
        self.assertEqual((root / SLOT_NAMES[0]).stat().st_size,
                         HEADER.size + len(alternate))
        self.assertEqual((root / SLOT_NAMES[1]).stat().st_size,
                         HEADER.size + len(alternate))

    def test_two_authenticated_guest_results_from_same_page_only_one_commits(self):
        """Competing genuine native revisions cannot double-publish a chart."""
        from nanlmind_hermes.native_head_checkpoint import (
            NativeHeadCheckpointCoordinator, NativeHeadCheckpointConflict,
        )
        raw = bytes(BANK_BYTES)
        before = self.fence(self.universe_id)
        first_request = self.request(
            dispatch_id="native-head-concurrent-001", raw=raw,
            generation=before["chart_generation"], feature=127, increment=3,
        )
        second_request = self.request(
            dispatch_id="native-head-concurrent-002", raw=raw,
            generation=before["chart_generation"], feature=0, increment=2,
        )
        first = self.journal.execute(
            request=first_request, lease_receipt=self.receipt,
            network_head=0, raw_bank=raw, native_guest=self.guest,
            allow_genesis_format=True,
        )
        second = self.journal.execute(
            request=second_request, lease_receipt=self.receipt,
            network_head=0, raw_bank=raw, native_guest=self.guest,
            allow_genesis_format=True,
        )
        self.assertTrue(first["native_guest_invoked_locally"])
        self.assertTrue(second["native_guest_invoked_locally"])
        self.assertTrue(first["source_snapshot_bound"])
        self.assertTrue(second["source_snapshot_bound"])
        self.assertEqual(first["source_chart_sha256"], before["chart_sha256"])
        self.assertEqual(second["source_chart_sha256"], before["chart_sha256"])
        self.assertNotEqual(
            first["bank_after_sha256"], second["bank_after_sha256"],
        )
        winner = self.journal_checkpoint(
            first_request, expected_after_sha256=first["bank_after_sha256"],
        )
        self.assertEqual(winner["chart_generation"], 2)
        loser_writer = NativeHeadCheckpointCoordinator(
            fence=self.fence, journal=self.journal,
        )
        with self.assertRaises(NativeHeadCheckpointConflict):
            loser_writer.commit(
                request=second_request, lease_receipt=self.receipt,
                network_head=0,
            )
        self.assertEqual(self.fence(self.universe_id)["chart_generation"], 2)
        self.assertEqual(
            self.fence(self.universe_id)["bank_sha256"],
            first["bank_after_sha256"],
        )
        # Losing result remains a nonpromoted journal stage. Retry returns
        # the original native receipt without rerunning the guest.
        loser = self.journal.inspect(
            request=second_request, lease_receipt=self.receipt,
            network_head=0,
        )
        self.assertEqual(loser["state"], "completed_staging_only")
        self.assertFalse(loser["canonical_training_committed"])
        repeat = self.journal.execute(
            request=second_request, lease_receipt=self.receipt,
            network_head=0, raw_bank=raw, native_guest=self.guest,
            allow_genesis_format=True,
        )
        self.assertTrue(repeat["replayed_from_journal"])
        self.assertEqual(
            repeat["bank_after_sha256"], second["bank_after_sha256"],
        )
        self.assertEqual(self.fence(self.universe_id)["chart_generation"], 2)
        self.assertFalse(repeat["canonical_training_committed"])

    def test_real_native_guest_ring_handoff_denies_staging_and_reexecution(self):
        """Epoch changes after native instructions cannot publish guest output."""
        from runner_riddle.hermes_head_observation import (
            HermesHeadObservationConflict,
        )
        raw = bytes(BANK_BYTES)
        request = self.request(
            dispatch_id="native-head-real-epoch-race-001",
            raw=raw, generation=1, feature=127, increment=1,
        )
        observed = [0]
        original = self.guest.observe

        def handoff_during_guest(**kwargs):
            output = original(**kwargs)
            observed[0] += 1
            self.epoch += 1
            return output

        self.guest.observe = handoff_during_guest
        with self.assertRaisesRegex(HermesHeadObservationConflict, "epoch"):
            self.journal.execute(
                request=request, lease_receipt=self.receipt,
                network_head=0, raw_bank=raw, native_guest=self.guest,
                allow_genesis_format=True,
            )
        self.assertEqual(observed[0], 1)
        self.assertEqual(self.fence(self.universe_id)["chart_generation"], 1)
        pending = self.journal.inspect(
            request=request, lease_receipt=self.receipt, network_head=0,
        )
        self.assertEqual(pending["state"], "pending_or_ambiguous")
        self.assertFalse(pending["canonical_training_committed"])
        # Even if the test clock goes backwards, the durable reservation
        # refuses to execute the same native dispatch a second time.
        self.epoch -= 1
        with self.assertRaisesRegex(HermesHeadObservationConflict, "never replay"):
            self.journal.execute(
                request=request, lease_receipt=self.receipt,
                network_head=0, raw_bank=raw, native_guest=self.guest,
                allow_genesis_format=True,
            )
        self.assertEqual(observed[0], 1)
        self.assertEqual(self.fence(self.universe_id)["chart_generation"], 1)

    def test_real_native_guest_revoked_lease_does_not_stage_result(self):
        """A revoked signed lease cannot complete after true NaN16 execution."""
        from runner_riddle.hermes_leases import HermesLeaseError
        raw = bytes(BANK_BYTES)
        request = self.request(
            dispatch_id="native-head-real-lease-race-002",
            raw=raw, generation=1, feature=0, increment=1,
        )
        observed = [0]
        original = self.guest.observe

        def revoke_during_guest(**kwargs):
            output = original(**kwargs)
            observed[0] += 1
            self.registry.release(
                installation_id=self.installation, receipt=self.receipt,
            )
            return output

        self.guest.observe = revoke_during_guest
        with self.assertRaises(HermesLeaseError):
            self.journal.execute(
                request=request, lease_receipt=self.receipt,
                network_head=0, raw_bank=raw, native_guest=self.guest,
                allow_genesis_format=True,
            )
        self.assertEqual(observed[0], 1)
        self.assertEqual(self.fence(self.universe_id)["chart_generation"], 1)
        with sqlite3.connect(self.base / "dispatch.sqlite") as db:
            row = db.execute(
                "SELECT bank_after, checkpointed_at "
                "FROM hermes_head_observation WHERE dispatch_id=?",
                (request.dispatch_id,),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertIsNone(row[0])
        self.assertIsNone(row[1])
        with self.assertRaises(HermesLeaseError):
            self.journal.execute(
                request=request, lease_receipt=self.receipt,
                network_head=0, raw_bank=raw, native_guest=self.guest,
                allow_genesis_format=True,
            )
        self.assertEqual(observed[0], 1)

    def test_real_native_cas_recovers_after_crash_before_router_ack(self):
        """Real guest runs once; a failed post-CAS ACK cannot double-write."""
        from nanlmind_hermes.native_head_checkpoint import (
            NativeHeadCheckpointCoordinator,
        )
        raw = bytes(BANK_BYTES)
        source = self.fence(self.universe_id)
        request = self.request(
            dispatch_id="native-head-e2e-interrupted-ack-003",
            raw=raw, generation=source["chart_generation"],
            feature=63, increment=1,
        )
        staged = self.journal.execute(
            request=request, lease_receipt=self.receipt, network_head=0,
            raw_bank=raw, native_guest=self.guest, allow_genesis_format=True,
        )
        self.assertTrue(staged["native_guest_invoked_locally"])
        self.assertTrue(staged["source_snapshot_bound"])
        self.assertEqual(
            staged["source_chart_sha256"], source["chart_sha256"],
        )
        self.assertEqual(
            staged["source_root_block_sha256"], source["root_block_sha256"],
        )
        def crash_before_ack(*, request, lease_receipt, network_head):
            raise RuntimeError("simulated crash after full-page CAS")

        self.journal.confirm_local_checkpoint = crash_before_ack
        coordinator = NativeHeadCheckpointCoordinator(
            fence=self.fence, journal=self.journal,
        )
        with self.assertRaisesRegex(RuntimeError, "after full-page CAS"):
            coordinator.commit(
                request=request, lease_receipt=self.receipt, network_head=0,
            )
        durable = self.fence(self.universe_id)
        self.assertEqual(durable["chart_generation"], 2)
        self.assertEqual(durable["bank_sha256"], staged["bank_after_sha256"])
        self.assertEqual(
            self.journal.inspect(
                request=request, lease_receipt=self.receipt, network_head=0,
            )["state"], "completed_staging_only",
        )

        # Restart the actual durable router journal. The next coordinator
        # verifies both adjacent chart snapshots, ACKs the old dispatch and
        # never calls the native guest or creates an extra chart generation.
        self.journal = HermesHeadObservationJournal(
            self.base / "dispatch.sqlite",
            lease_registry=self.registry,
            ring_epoch_reader=lambda: self.epoch,
            chart_fence_reader=self.fence,
        )
        recovered = NativeHeadCheckpointCoordinator(
            fence=self.fence, journal=self.journal,
        ).commit(
            request=request, lease_receipt=self.receipt, network_head=0,
        )
        self.assertTrue(recovered["recovered_prior_local_checkpoint"])
        self.assertTrue(recovered["local_checkpoint_verified"])
        self.assertTrue(recovered["source_snapshot_bound"])
        self.assertEqual(
            recovered["source_chart_sha256"], source["chart_sha256"],
        )
        self.assertFalse(recovered["native_execution_newly_invoked"])
        self.assertFalse(recovered["canonical_training_committed"])
        self.assertEqual(self.fence(self.universe_id)["chart_generation"], 2)
        history = self.journal.inspect(
            request=request, lease_receipt=self.receipt, network_head=0,
        )
        self.assertEqual(history["state"], "checkpointed_locally")
        self.assertTrue(history["source_snapshot_bound"])
        self.assertEqual(
            history["source_root_block_sha256"], source["root_block_sha256"],
        )
        replay = self.journal.execute(
            request=request, lease_receipt=self.receipt, network_head=0,
            raw_bank=raw, native_guest=self.guest, allow_genesis_format=True,
        )
        self.assertTrue(replay["replayed_from_journal"])
        self.assertNotIn("raw_bank", replay)
        self.assertEqual(self.fence(self.universe_id)["chart_generation"], 2)

    def test_pinned_guest_two_native_revisions_then_tombstones_survive_restart(self):
        from nanlmind_hermes.head_bank_transport import (
            export_guest_bank_bytes,
        )
        from nanlmind_hermes.universe_chart import (
            Chart8MiB, restore_local_chart, make_word,
        )
        from nanlmind_hermes.head_bank_transport import BANK_OFFSET, BANK_END
        from nanlmind_hermes.chart_storage import load_chart_snapshot
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
        self.assertTrue(first["source_snapshot_bound"])
        self.assertEqual(first["source_chart_sha256"], first_fence["chart_sha256"])
        self.assertEqual(
            first["source_root_block_sha256"], first_fence["root_block_sha256"],
        )
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
        self.assertTrue(repeat["source_snapshot_bound"])
        self.assertEqual(repeat["source_chart_sha256"], first_fence["chart_sha256"])
        self.assertNotIn("raw_bank", repeat)
        self.assertEqual(repeat["bank_after_sha256"], first["bank_after_sha256"])
        # The live chart is the very same object: replay must not allocate
        # another 8 MiB chart, mutate its bank, or advance its generation.
        from nanlmind_hermes.native_head_checkpoint import NativeHeadCheckpointCoordinator
        again = self.runner.commit_native_head_observation(
            coordinator=NativeHeadCheckpointCoordinator(
                fence=self.fence, journal=self.journal,
            ),
            request=first_request, lease_receipt=self.receipt,
            network_head=0,
        )
        self.assertFalse(again["head_bank_rebased"])
        self.assertEqual(self.runner.chart.snapshot_generation, 2)

        second_request = self.request(
            dispatch_id="native-head-e2e-dispatch-002",
            raw=first["raw_bank"], generation=2, feature=0, increment=2,
        )
        second_source = self.fence(self.universe_id)
        second = self.journal.execute(
            request=second_request, lease_receipt=self.receipt,
            network_head=0, raw_bank=first["raw_bank"], native_guest=self.guest,
        )
        self.assertTrue(second["source_snapshot_bound"])
        self.assertEqual(
            second["source_chart_sha256"], second_source["chart_sha256"],
        )
        self.assertEqual(
            second["source_root_block_sha256"],
            second_source["root_block_sha256"],
        )
        self.assertNotEqual(
            first["source_chart_sha256"], second["source_chart_sha256"],
        )
        self.assertEqual(second["receipt"]["head_generation_before"], 1)
        self.assertEqual(second["receipt"]["head_generation_after"], 2)
        # Simulate a pending, unrelated HERMES temporal edit while a real
        # authenticated NaN16 head result is staged. Its new bank must be
        # rebased into this chart without throwing the pending rail away.
        dirty_word = make_word(0x1234)
        self.runner.chart.write_rail(17, 136, 0, dirty_word)
        self.assertEqual(self.runner.chart.read_rail(17, 136, 0), dirty_word)
        self.assertTrue(self.runner.chart._dirty)
        from nanlmind_hermes.native_head_checkpoint import NativeHeadCheckpointCoordinator
        second_checkpoint = self.journal_checkpoint(
            second_request, expected_after_sha256=second["bank_after_sha256"],
        )
        self.assertEqual(second_checkpoint["chart_generation"], 3)
        self.assertTrue(second_checkpoint["pending_nonbank_edits_preserved"])
        self.assertTrue(self.runner.chart._dirty)
        self.assertEqual(self.runner.chart.read_rail(17, 136, 0), dirty_word)
        self.assertEqual(
            bytes(self.runner.chart.bytes[BANK_OFFSET:BANK_END]),
            second["raw_bank"],
        )
        # The first completed update remains a permanent replay tombstone
        # even though two more chart slots have superseded its exact bank.
        historical = NativeHeadCheckpointCoordinator(
            fence=self.fence, journal=self.journal,
        ).commit(
            request=first_request, lease_receipt=self.receipt, network_head=0,
        )
        self.assertTrue(historical["historical_local_checkpoint_verified"])
        self.assertTrue(historical["source_snapshot_bound"])
        self.assertEqual(
            historical["source_chart_sha256"], first["source_chart_sha256"],
        )
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
        # Offline export sees the durable gen3 page, not the unrelated
        # still-dirty in-memory temporal edit. A later HERMES checkpoint
        # publishes that edit without reverting either native head revision.
        packed_generation, packed_page = load_chart_snapshot(self.state, self.parent)
        self.assertEqual(packed_generation, 3)
        self.assertEqual(archive["sections"][0]["sha256"], sha(packed_page))
        self.assertFalse(archive["import_to_live_allowed"])
        self.assertFalse(archive["cross_store_atomicity_attested"])
        self.assertFalse(archive["canonical_training_committed"])
        self.assertEqual(inspect_n16pack(packed)["sections"], archive["sections"])

        # The next ordinary HERMES checkpoint must converge the pending
        # temporal rail and the real native-generated bank in ONE live chart.
        later = self.runner.checkpoint()
        self.assertEqual(later["generation"], 4)
        persisted_generation, persisted_page = load_chart_snapshot(
            self.state, self.parent,
        )
        self.assertEqual(persisted_generation, 4)
        self.assertEqual(
            persisted_page[BANK_OFFSET:BANK_END], second["raw_bank"],
        )
        rail_offset = self.runner.chart.cell_offset(17, 136)
        self.assertEqual(
            persisted_page[rail_offset:rail_offset + 8],
            dirty_word.to_bytes(8, "little"),
        )
        self.assertEqual(self.fence(self.universe_id)["chart_generation"], 4)
        self.assertIs(self.runner.register.chart, self.runner.chart)
        self.assertIs(self.runner.heads.chart, self.runner.chart)


if __name__ == "__main__":
    unittest.main()
