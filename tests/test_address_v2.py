import unittest

from runner_riddle import AddressError, parse_address
from runner_riddle.address import HeadSelector, ObjectSelector

APEX = "nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0"


class ApexAddressTests(unittest.TestCase):
    def test_apex_root_is_canonical(self):
        parsed = parse_address(APEX)
        self.assertEqual(parsed.root, APEX)
        self.assertEqual(parsed.legacy_root, "nan://GM0:SC0:MC0:BS0:0:HW0:0")
        self.assertEqual(parsed.canonical, APEX)
        self.assertEqual(parsed.gm_instance, 0)
        self.assertEqual(parsed.sc_instance, 0)
        self.assertEqual(parsed.mc_instance, 0)

    def test_apex_instances_are_not_collapsed(self):
        parsed = parse_address(
            "nan://GM7:3::SC2:4::MC1:9::BS5:6::HW8:7"
        )
        self.assertEqual(parsed.root, "nan://GM7:3::SC2:4::MC1:9::BS5:6::HW8:7")
        self.assertEqual(parsed.gm, 7)
        self.assertEqual(parsed.gm_instance, 3)
        self.assertEqual(parsed.sc, 2)
        self.assertEqual(parsed.sc_instance, 4)
        self.assertEqual(parsed.mc, 1)
        self.assertEqual(parsed.mc_instance, 9)
        self.assertEqual(parsed.bs_class, 5)
        self.assertEqual(parsed.bs_node, 6)
        self.assertEqual(parsed.root_namespace, 8)
        self.assertEqual(parsed.root_head, 7)

    def test_runner_ring_range_is_expanded_and_rendered_compactly(self):
        parsed = parse_address(APEX + "::HW0:1-255")
        self.assertEqual(len(parsed.head_selectors), 1)
        self.assertEqual(parsed.head_selectors[0].heads, tuple(range(1, 256)))
        self.assertEqual(
            parsed.canonical_with_selectors(), APEX + "::HW0:1-255"
        )

    def test_mixed_head_list_and_range(self):
        parsed = parse_address(APEX + "::HW0:1-3,8,10-12")
        self.assertEqual(parsed.head_selectors[0].heads, (1, 2, 3, 8, 10, 11, 12))
        self.assertEqual(parsed.head_selectors[0].ranges, ((1, 3), (8, 8), (10, 12)))
        self.assertEqual(
            parsed.canonical_with_selectors(), APEX + "::HW0:1-3,8,10-12"
        )

    def test_vector_leaf_and_subrelation(self):
        text = APEX + "::HW0:1-255:vector#1337:subrelation(42)"
        parsed = parse_address(text)
        self.assertEqual(parsed.canonical_with_selectors(), text)
        self.assertEqual(len(parsed.object_selectors), 1)
        leaf = parsed.object_selectors[0]
        self.assertEqual(leaf.kind, "vector")
        self.assertEqual(leaf.object_id, "1337")
        self.assertEqual(leaf.subrelation, "42")

    def test_subrelation_hash_spelling_is_normalized(self):
        parsed = parse_address(APEX + "::HW0:1:vector#1337:subrelation#42")
        self.assertEqual(
            parsed.canonical_with_selectors(),
            APEX + "::HW0:1:vector#1337:subrelation(42)",
        )

    def test_leaf_directly_after_root(self):
        parsed = parse_address(APEX + ":vector#7")
        self.assertEqual(parsed.canonical_with_selectors(), APEX + ":vector#7")
        self.assertIsInstance(parsed.selectors[0], ObjectSelector)

    def test_legacy_root_and_object_spelling_normalize(self):
        parsed = parse_address(
            "nan://GM0:SC0:MC0:BS0:0:HW0:0::HW0:1,2,3::vector1337"
        )
        self.assertEqual(parsed.root, APEX)
        self.assertEqual(
            parsed.canonical_with_selectors(),
            APEX + "::HW0:1-3:vector#1337",
        )
        self.assertEqual(parsed.selectors[0], HeadSelector(0, (1, 2, 3)))
        self.assertEqual(
            parsed.selectors[1], ObjectSelector("vector", "1337", None)
        )

    def test_rejects_malformed_apex_or_selector(self):
        bad = (
            "nan://GM0:SC0:MC0:BS0:0:HW0:0",  # legacy valid, not here
            "nan://GM0:0:SC0:0:MC0:0:BS0:0:HW0:0",
            "nan://GM0:0::SC0:0::MC0:0::BS0:0",
            "nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:256",
            APEX + "::HW0:3-1",
            APEX + "::HW0:1,1",
            APEX + "::HW0:256",
            APEX + "::memory1337",
            APEX + "::HW0:1::",
            APEX + "::HW0:1:vector#",
        )
        for value in bad[1:]:
            with self.subTest(value=value), self.assertRaises(AddressError):
                parse_address(value)
        # The pre-v2 spelling is explicitly supported as a migration alias.
        self.assertEqual(parse_address(bad[0]).root, APEX)

    def test_math_context_is_rejected(self):
        with self.assertRaises(AddressError) as raised:
            parse_address("math://vector:1")
        self.assertIn("route_context_mismatch", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
