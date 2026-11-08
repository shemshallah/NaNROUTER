"""Exhaustive non-mutable head role and six-BSR/250-curriculum contract."""
import hashlib
import json
import unittest

from runner_riddle.head_role_contract import (
    SCHEMA, BSR_HEADS, BSR_SLOT_BY_HEAD, CONTRACT_SHA256,
    RAW_CONTRACT, describe_head, role_summary,
)
from runner_riddle.mirror_point_register import (
    HEADS, PAIR_COUNT, TOPOLOGY_DIGEST, MirrorPointError,
    MirrorRegister, pair_heads, reverse16,
)


class HeadRoleTests(unittest.TestCase):
    def test_256_fixed_heads_255_writer_eligible_250_curriculum(self):
        summary = role_summary()
        self.assertEqual(summary["schema"], SCHEMA)
        self.assertEqual(summary["topology_sha256"], TOPOLOGY_DIGEST)
        self.assertEqual(summary["physical_palindrome_heads"], 256)
        self.assertEqual(summary["mp_microtable_writer_eligible"], 255)
        self.assertEqual(summary["boolean_curriculum_eligible"], 250)
        self.assertEqual(summary["bsr_control_head_indices"], [0, 4, 5, 6, 7, 8])
        self.assertEqual(len(summary["mp_writable_head_indices"]), 255)
        self.assertEqual(len(summary["boolean_curriculum_head_indices"]), 250)
        self.assertFalse(summary["grants_permission"])
        self.assertFalse(summary["native_mth_executed"])
        self.assertEqual(summary["physical_chart_copies_created"], 0)
        self.assertEqual(set(summary["mp_writable_head_indices"]),
                         set(range(1, 256)))
        self.assertEqual(set(summary["boolean_curriculum_head_indices"]),
                         set(range(256)) - set(BSR_HEADS))

    def test_every_palindrome_head_preserved_and_existing_mp_acl_unchanged(self):
        eligible = curricular = control = root = 0
        for n in range(HEADS):
            with self.subTest(head=n):
                role = describe_head(n)
                micro = MirrorRegister.head(n).as_dict()
                self.assertEqual(role["canonical_cell"], n)
                self.assertEqual(role["raw_address"], micro["canonical_address"])
                self.assertEqual(role["raw_address"], reverse16(role["raw_address"]))
                self.assertEqual(role["role_contract_sha256"], CONTRACT_SHA256)
                self.assertEqual(role["topology_sha256"], TOPOLOGY_DIGEST)
                self.assertEqual(role["mp_microtable_writer_eligible"],
                                 n in micro["writable_heads"])
                self.assertEqual(role["bsr_control_head"], n in BSR_HEADS)
                self.assertEqual(role["boolean_curriculum_eligible"],
                                 n not in BSR_HEADS)
                self.assertEqual(role["nannet_root_head"], n == 0)
                self.assertEqual(role["bsr_wire_slot"], BSR_SLOT_BY_HEAD.get(n))
                self.assertFalse(role["grants_permission"])
                self.assertFalse(role["native_mth_executed"])
                eligible += role["mp_microtable_writer_eligible"]
                curricular += role["boolean_curriculum_eligible"]
                control += role["bsr_control_head"]
                root += role["nannet_root_head"]
        self.assertEqual((eligible, curricular, control, root), (255, 250, 6, 1))

    def test_every_mirror_pair_retains_same_one_or_two_writers(self):
        root_incident = other = 0
        for mp in range(PAIR_COUNT):
            a, b = pair_heads(mp)
            writers = MirrorRegister.mp(mp).as_dict()["writable_heads"]
            self.assertEqual(writers,
                             [h for h in (a, b) if h != 0])
            if 0 in (a, b):
                root_incident += 1
                self.assertEqual(len(writers), 1)
            else:
                other += 1
                self.assertEqual(len(writers), 2)
        self.assertEqual(root_incident, 255)
        self.assertEqual(other, 32385)

    def test_exact_identity_and_digest_are_deterministic(self):
        self.assertEqual(CONTRACT_SHA256,
                         hashlib.sha256(
                             b"nanrouter.local-head-role-contract/1\0"
                             + RAW_CONTRACT).hexdigest())
        raw = json.loads(RAW_CONTRACT)
        self.assertEqual(raw["physical_palindrome_heads"], 256)
        self.assertEqual(raw["bsr_control_head_indices"], [0, 4, 5, 6, 7, 8])

    def test_invalid_head_inputs_fail_before_any_projection(self):
        for value in (True, False, -1, 256, 1.0, "1", None):
            with self.subTest(value=value), self.assertRaises(MirrorPointError):
                describe_head(value)


if __name__ == "__main__":
    unittest.main()
