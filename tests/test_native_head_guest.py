"""Native end-to-end: pinned C VM imports 8-byte NaN faces and executes NaN16.

The native tests are enabled by the checkout-and-compile GitHub workflow;
without a pinned local NaN0S build they are skipped rather than simulated.
"""
import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from runner_riddle.head_bank_handoff import (
    BANK_BYTES, HeadBankHandoff, check_native_observation_receipt,
)
from runner_riddle.native_head_guest import (
    BANK_BASE, NativeHeadBankError, NativeHeadBankGuest,
)
from runner_riddle.n16t_guest import _NaN16GuestVM


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def make_request(raw, guest_digest, *, head=1, feature=12, increment=3,
                 dispatch="dispatch_native01"):
    return HeadBankHandoff(
        universe_id="universe_native01", installation_id="installation_001",
        dispatch_id=dispatch, lease_id=47, lease_generation=2, ring_epoch=3,
        head_index=head, feature_index=feature, increment=increment,
        parent_root_sha256=sha(b"chart-parent"),
        bank_before_sha256=sha(raw), chart_generation=1,
        observation_sha256=sha(b"observed lesson"),
        native_image_sha256=guest_digest,
    )


class DenyVM:
    """A guard: invalid requests must fail BEFORE any native allocation."""
    def __init__(self, *args, **kwargs):
        raise AssertionError("VM must not have been constructed")


class NativeHeadGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        for name in ("vm.so", "head.nan", "head.labels"):
            (self.dir / name).write_bytes(b"test-pinned-file")
        self.paths = dict(
            library_path=str(self.dir/"vm.so"), library_sha256=sha(b"test-pinned-file"),
            image_path=str(self.dir/"head.nan"), image_sha256=sha(b"test-pinned-file"),
            labels_path=str(self.dir/"head.labels"), labels_sha256=sha(b"test-pinned-file"),
        )
        # Override the labels file to have real names and pin its updated digest.
        labels=b"nh_format 1\nnh_open 2\nnhr_attach 3\nnhr_read 4\nnhr_observe 5\n"
        (self.dir/"head.labels").write_bytes(labels)
        self.paths["labels_sha256"]=sha(labels)

    def test_reject_invalid_digests_lengths_and_unapproved_genesis(self):
        guest = NativeHeadBankGuest(**self.paths, vm_factory=DenyVM)
        blank = bytes(BANK_BYTES)
        request = make_request(blank, self.paths["image_sha256"])
        with self.assertRaises(NativeHeadBankError):
            guest.observe(request=request,raw_bank=blank)
        with self.assertRaises(NativeHeadBankError):
            guest.observe(request=request,raw_bank=blank[:-8],
                          allow_genesis_format=True)
        with self.assertRaises(NativeHeadBankError):
            guest.observe(request=request,raw_bank=b"x"*BANK_BYTES,
                          allow_genesis_format=False)
        with self.assertRaises(NativeHeadBankError):
            guest.observe(request=request,raw_bank=b"x"*BANK_BYTES,
                          allow_genesis_format=True)
        mismatch = make_request(blank, sha(b"not the real image"))
        with self.assertRaises(NativeHeadBankError):
            guest.observe(request=mismatch,raw_bank=blank,
                          allow_genesis_format=True)
        with self.assertRaises(NativeHeadBankError):
            guest.observe(request=request,raw_bank=blank,
                          allow_genesis_format="yes")

    def test_label_digest_is_required_and_header_must_be_complete(self):
        with self.assertRaises(ValueError):
            NativeHeadBankGuest(**dict(self.paths,labels_sha256=sha(b"wrong")))
        (self.dir/"head.labels").write_text("nh_open 1\n")
        self.paths["labels_sha256"]=sha(b"nh_open 1\n")
        with self.assertRaises(NativeHeadBankError):
            NativeHeadBankGuest(**self.paths)
        self.assertEqual(BANK_BASE, 16384)


@unittest.skipUnless(
    all(os.environ.get(k) for k in (
        "NAN_HEAD_GUEST_LIBRARY", "NAN_HEAD_GUEST_IMAGE", "NAN_HEAD_GUEST_LABELS"
    )),
    "real pinned NaN0S C VM + NaN16 guest image not provided",
)
class NativeHeadLiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib=Path(os.environ["NAN_HEAD_GUEST_LIBRARY"])
        cls.image=Path(os.environ["NAN_HEAD_GUEST_IMAGE"])
        cls.labels=Path(os.environ["NAN_HEAD_GUEST_LABELS"])
        cls.image_digest=sha(cls.image.read_bytes())
        cls.worker=NativeHeadBankGuest(
            library_path=str(cls.lib),library_sha256=sha(cls.lib.read_bytes()),
            image_path=str(cls.image),image_sha256=cls.image_digest,
            labels_path=str(cls.labels),labels_sha256=sha(cls.labels.read_bytes()),
        )

    def test_full_guest_learning_and_corrupt_slot_recovery(self):
        blank=bytes(BANK_BYTES)
        first_req=make_request(blank,self.image_digest)
        first=self.worker.observe(request=first_req,raw_bank=blank,
                                  allow_genesis_format=True)
        self.assertEqual(first["receipt"]["head_generation_before"],0)
        self.assertEqual(first["receipt"]["head_generation_after"],1)
        self.assertTrue(first["native_guest_invoked_locally"])
        self.assertFalse(first["authenticated_dispatch_verified"])
        self.assertFalse(first["canonical_training_committed"])
        self.assertEqual(len(first["raw_bank"]), BANK_BYTES)
        self.assertNotEqual(sha(first["raw_bank"]), sha(blank))
        self.assertTrue(check_native_observation_receipt(
            first_req, first["receipt"])["bindings_consistent"])
        second_req=make_request(first["raw_bank"],self.image_digest,
                                increment=2,dispatch="dispatch_native02")
        second=self.worker.observe(request=second_req,raw_bank=first["raw_bank"])
        self.assertEqual(second["receipt"]["head_generation_before"],1)
        self.assertEqual(second["receipt"]["head_generation_after"],2)
        # A second head is virgin even when the first head has two revisions.
        third_req=make_request(second["raw_bank"],self.image_digest,
                               head=255,increment=7,dispatch="dispatch_native03")
        third=self.worker.observe(request=third_req,raw_bank=second["raw_bank"])
        self.assertEqual(third["receipt"]["head_generation_before"],0)
        self.assertEqual(third["receipt"]["head_generation_after"],1)
        self.assertEqual(third["raw_bank"][8*8:(8+266)*8],
                         second["raw_bank"][8*8:(8+266)*8])
        # Simulated tear of newest head-1 slot commit marker. The next
        # observation MUST resume from guest-validated older generation.
        torn=bytearray(third["raw_bank"])
        torn[(8+133+4)*8:(8+133+5)*8]=bytes(8)
        torn=bytes(torn)
        recovered_req=make_request(torn,self.image_digest,
                                   increment=4,dispatch="dispatch_native04")
        recovered=self.worker.observe(request=recovered_req,raw_bank=torn)
        self.assertEqual(recovered["receipt"]["head_generation_before"],1)
        self.assertEqual(recovered["receipt"]["head_generation_after"],2)
        # A nonempty corrupt bank cannot be interpreted as genesis.
        damaged=bytearray(blank)
        damaged[0]=0xAA
        bad=bytes(damaged)
        with self.assertRaises(NativeHeadBankError):
            self.worker.observe(
                request=make_request(bad,self.image_digest,
                                     dispatch="dispatch_native05"),
                raw_bank=bad,
            )

    def test_raw_word_class_and_payload_preserved_across_guest_reload(self):
        blank=bytes(BANK_BYTES)
        one=self.worker.observe(
            request=make_request(blank,self.image_digest),raw_bank=blank,
            allow_genesis_format=True,
        )
        # Native checksum includes NaN face nibble. Reimport and update
        # succeeds only if *raw* near/far class faces survive host transport.
        two=self.worker.observe(
            request=make_request(one["raw_bank"],self.image_digest,
                                 feature=127,increment=1,
                                 dispatch="dispatch_native06"),
            raw_bank=one["raw_bank"],
        )
        self.assertEqual(two["receipt"]["head_generation_before"],1)
        self.assertEqual(two["receipt"]["head_generation_after"],2)


if __name__ == "__main__":
    unittest.main()
