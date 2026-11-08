"""Complete mirror routing 65536 addresses, separate head/MP namespaces."""
import hashlib
import tempfile
import unittest

from runner_riddle.address import AddressError, MirrorPairSelector, parse_address
from runner_riddle.math_objects import MathLeaf
from runner_riddle.math_store import MathStore, StaleGenerationError
from runner_riddle.wave_store import WaveStore
from runner_riddle.mirror_point_register import (
    CANONICAL_CELLS, FIXED_POINTS, PAIR_COUNT, RAW_ADDRESSES,
    LOOKUP_BYTES, INVERSE_BYTES, RAW_TO_CELL, CELL_TO_RAW,
    MAX_PAGE, TOPOLOGY_DIGEST, MirrorRegister, MirrorLeafDirectory,
    MirrorPointError, address, reverse16, pair_number, pair_heads,
    mapping_key,
)

APEX = "nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0"


class AddressMicrotableTests(unittest.TestCase):
    def test_all_palindrome_and_mirror_cells_exhaust_exact_16bit_space(self):
        multiplicities = [0] * CANONICAL_CELLS
        for raw in range(RAW_ADDRESSES):
            forward = MirrorRegister.from_raw(raw)
            mirrored = MirrorRegister.from_raw(reverse16(raw))
            self.assertEqual(forward["canonical_cell"], mirrored["canonical_cell"])
            self.assertEqual(forward["canonical_address"], mirrored["canonical_address"])
            self.assertEqual(forward["addresses"], mirrored["addresses"])
            multiplicities[forward["canonical_cell"]] += 1
        self.assertEqual(multiplicities[:FIXED_POINTS], [1] * FIXED_POINTS)
        self.assertEqual(multiplicities[FIXED_POINTS:], [2] * PAIR_COUNT)
        self.assertEqual(len(RAW_TO_CELL), LOOKUP_BYTES)
        self.assertEqual(len(CELL_TO_RAW), INVERSE_BYTES)
        self.assertEqual(MirrorRegister.status()["topology_sha256"], TOPOLOGY_DIGEST)
        self.assertFalse(MirrorRegister.status()["mutable"])

    def test_all_32640_mp_microtables_roundtrip_by_rank_and_heads(self):
        for n in range(PAIR_COUNT):
            a, b = pair_heads(n)
            self.assertLess(a, b)
            self.assertEqual(pair_number(b, a), n)
            micro = MirrorRegister.mp(n)
            self.assertEqual(micro.canonical_cell, 256 + n)
            self.assertEqual(micro.forward_address, address(a, b))
            self.assertEqual(micro.mirror_address, address(b, a))
        for h in range(FIXED_POINTS):
            m = MirrorRegister.head(h)
            self.assertEqual(m.canonical_cell, h)
            self.assertEqual(m.forward_address, m.mirror_address)
        self.assertEqual(MirrorRegister.from_heads(0, 0)["writable_heads"], [])
        self.assertEqual(MirrorRegister.from_heads(0, 7)["writable_heads"], [7])
        for invalid in (-1, 32640, True):
            with self.assertRaises(MirrorPointError):
                MirrorRegister.mp(invalid)

    def test_hw0_mp_routes_and_compact_range_without_expansion(self):
        for text in (
            APEX + "::HW0:MP0",
            APEX + "::HW0:MP32639",
            APEX + "::HW0:MP0-32639",
            APEX + "::HW0:8::HW0:MP2001",
            APEX + "::HW0:MP3:vector#7",
        ):
            parsed = parse_address(text)
            self.assertEqual(parsed.canonical_with_selectors(), text)
            self.assertEqual(len(parsed.mirror_pair_selectors), 1)
            self.assertIsInstance(parsed.mirror_pair_selectors[0], MirrorPairSelector)
        rng = parse_address(APEX + "::HW0:MP0-32639").mirror_pair_selectors[0]
        self.assertTrue(rng.is_range)
        self.assertEqual((rng.start, rng.end), (0, PAIR_COUNT - 1))
        for bad in ("HW0:MP32640", "HW0:MP-1", "HW0:MP6-4",
                    "HW1:MP1", "HW0:MP5-32640", "HW0:MP3a"):
            with self.subTest(bad=bad), self.assertRaises(AddressError):
                parse_address(APEX + "::" + bad)


class MathematicalLeafLinkTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        bs = folder.name + "/bs0db.sqlite"
        mc = folder.name + "/mc0db.sqlite"
        WaveStore(bs, mc)
        self.store = MathStore(bs, mc)
        self.links = MirrorLeafDirectory(self.store)
        self.leaf_id = "nml:mirror:test:1"
        self.store.put_leaf(MathLeaf(
            leaf_id=self.leaf_id, kind="scalar", type={"kind": "scalar"},
            content={"value": 7}, provenance={"producer": "unit_test"}))
        self.digest = self.store.get_mapping("leaf:" + self.leaf_id)["target_digest"]

    def test_two_directions_one_leaf_and_head_acl(self):
        n = pair_number(7, 200)
        self.assertEqual(self.links.resolve_mp(n)["status"], "unbound")
        record = self.links.bind(n, source_head=200, leaf_id=self.leaf_id,
                                 leaf_version=1, leaf_digest=self.digest,
                                 expected_version=0, expected_generation=0,
                                 tick=42)
        self.assertFalse(record["native_head_mutated"])
        one = self.links.resolve_address(APEX + f"::HW0:7::HW0:MP{n}")
        two = self.links.resolve_address(APEX + f"::HW0:200::HW0:MP{n}")
        direct = self.links.resolve_address(APEX + f"::HW0:MP{n}")
        self.assertTrue(direct["bound"])
        self.assertEqual(one["leaf"], two["leaf"])
        self.assertEqual(two["leaf"], direct["leaf"])
        self.assertEqual(direct["leaf"]["generation"], 1)
        self.assertEqual(one["selected_head"], 7)
        self.assertEqual(two["selected_head"], 200)
        self.assertEqual(mapping_key(n), f"palpair:v1:{n:05d}")
        for route in (APEX + f"::HW0:16::HW0:MP{n}",
                      APEX + f"::HW0:0::HW0:MP{n}",
                      APEX + f"::HW0:7,200::HW0:MP{n}"):
            with self.assertRaises(MirrorPointError):
                self.links.resolve_address(route)
        for requester in (0, 16, 256):
            with self.assertRaises(MirrorPointError):
                self.links.bind(n, source_head=requester, leaf_id=self.leaf_id,
                                leaf_version=1, leaf_digest=self.digest,
                                expected_version=1, expected_generation=1)
        with self.assertRaises(StaleGenerationError):
            self.links.bind(n, source_head=7, leaf_id=self.leaf_id,
                            leaf_version=1, leaf_digest=self.digest,
                            expected_version=0, expected_generation=0)
        self.assertEqual(self.links.bind(
            n, source_head=7, leaf_id=self.leaf_id, leaf_version=1,
            leaf_digest=self.digest, expected_version=1,
            expected_generation=1)["mapping"]["generation"], 1)

    def test_router_projects_bounded_digested_master_scratch_pages(self):
        n = pair_number(0, 8)
        self.links.bind(n, source_head=8, leaf_id=self.leaf_id,
                        leaf_version=1, leaf_digest=self.digest,
                        expected_version=0, expected_generation=0)
        root = hashlib.sha256(b"chart").hexdigest()
        page = self.links.master_page(parent_root_sha256=root, chart_generation=2)
        self.assertEqual(page["schema"], "nanrouter.mirror-master-scratch/1")
        self.assertEqual(page["total_bound"], 1)
        self.assertEqual(page["entries"][0]["mp"], n)
        self.assertEqual(page["entries"][0]["addresses"],
                         [address(0, 8), address(8, 0)])
        self.assertEqual(page["head_counts"][0], 0)
        self.assertEqual(page["head_counts"][8], 1)
        self.assertFalse(page["native_execution_verified"])
        self.assertEqual(page["next_offset"], None)
        self.assertEqual(self.links.master_page(
            parent_root_sha256=root, chart_generation=2, offset=1)["entries"], [])
        self.assertEqual(self.links.resolve_address(
            APEX + "::HW0:MP0-32639")["status"], "range_requires_bounded_pagination")
        with self.assertRaises(MirrorPointError):
            self.links.master_page(parent_root_sha256=root, chart_generation=2,
                                   limit=MAX_PAGE + 1)


if __name__ == "__main__":
    unittest.main()
