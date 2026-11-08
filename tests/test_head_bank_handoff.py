"""Handoff must bind a native head update without becoming math authority."""
import hashlib
import unittest

from runner_riddle.head_bank_handoff import (
    BANK_BYTES, BANK_END, BANK_GUEST_WORD_OFFSET, BANK_OFFSET,
    HeadBankHandoff, HeadBankHandoffError, check_native_observation_receipt,
)


def sha(tag):
    return hashlib.sha256(tag.encode()).hexdigest()


def task():
    return HeadBankHandoff(
        universe_id="universe_test01", installation_id="install_test01",
        dispatch_id="dispatch_test01", lease_id=123, lease_generation=2,
        ring_epoch=17, head_index=255, feature_index=127, increment=3,
        parent_root_sha256=sha("root"), bank_before_sha256=sha("before"),
        chart_generation=4, observation_sha256=sha("sample"),
        native_image_sha256=sha("guest"),
    )


def receipt(t):
    p = t.prepared()
    return {**p, "kind": "native-head-observation", "native_status": 0,
            "head_generation_before": 4, "head_generation_after": 5,
            "bank_after_sha256": sha("after")}


class HeadBankHandoffTests(unittest.TestCase):
    def test_geometry_identity_and_prepared_digest(self):
        t = task()
        p = t.prepared()
        self.assertEqual(BANK_BYTES, 67838 * 8)
        self.assertEqual(BANK_END, BANK_OFFSET + BANK_BYTES)
        self.assertEqual(BANK_GUEST_WORD_OFFSET * 8, BANK_OFFSET)
        self.assertEqual(p["head_index"], 255)
        self.assertEqual(p, t.prepared())
        self.assertFalse(p["execution_authorized"])
        self.assertFalse(p["native_execution_verified"])
        self.assertIsNone(p["mathematical_validity"])

    def test_cannot_address_nannet0_or_invent_training_increment(self):
        basic = vars(task()).copy()
        for name, value in (("head_index", 0), ("head_index", 256),
                            ("increment", 0), ("increment", 256),
                            ("feature_index", -1), ("feature_index", 128),
                            ("chart_generation", -1), ("ring_epoch", 0),
                            ("parent_root_sha256", "A" * 64),
                            ("dispatch_id", "a"), ("lease_id", True)):
            with self.subTest(name=name, value=value):
                invalid = dict(basic, **{name: value})
                with self.assertRaises(HeadBankHandoffError):
                    HeadBankHandoff(**invalid)

    def test_binding_of_native_guest_receipt_but_not_trusted_execution(self):
        t = task()
        actual = check_native_observation_receipt(t, receipt(t))
        self.assertTrue(actual["bindings_consistent"])
        self.assertFalse(actual["native_execution_attested"])
        self.assertFalse(actual["mathematical_rule_promoted"])
        self.assertFalse(actual["canonical_training_committed"])

    def test_cross_head_lease_epoch_replay_and_wrong_root_denied(self):
        t = task()
        for key, value in (
            ("head_index", 1), ("lease_id", 124), ("lease_generation", 3),
            ("ring_epoch", 18), ("dispatch_id", "dispatch_other12"),
            ("chart_generation", 5), ("parent_root_sha256", sha("new root")),
            ("bank_before_sha256", sha("other old bytes")),
            ("native_image_sha256", sha("different guest")),
            ("request_sha256", sha("wrong request")),
            ("observation_sha256", sha("new observation")),
            ("feature_index", 0), ("increment", 4),
        ):
            with self.subTest(key=key):
                modified = dict(receipt(t), **{key: value})
                with self.assertRaises(HeadBankHandoffError):
                    check_native_observation_receipt(t, modified)

    def test_corrupt_guest_result_denied(self):
        t = task()
        for overrides in (
            {"head_generation_after": 4},
            {"head_generation_after": 6},
            {"head_generation_after": True},
            {"native_status": 1},
            {"native_status": False},
            {"bank_after_sha256": "BAD"},
            {"bank_after_sha256": t.bank_before_sha256},
            {"kind": "native-mth-result"},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(HeadBankHandoffError):
                    check_native_observation_receipt(t, dict(receipt(t), **overrides))


if __name__ == "__main__":
    unittest.main()
