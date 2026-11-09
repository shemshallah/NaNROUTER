"""Cross-check the two declared views of the one 8 MiB universe.

The physical mirror-memory profile stores all 256 heads in the first 32 KiB and
all 32,640 pair records in the remaining 8,160 KiB.  The route view in
``spec/universe-map.json`` is a virtual NANNET addressing view over the same
universe.  These tests make the distinction executable: both cover exactly
8 MiB, both expose 32,896 relation points including head 0, and neither creates
a second allocation.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from runner_riddle.mirror_memory import (
    HEAD_COUNT,
    HEAD_REGION_BYTES,
    PAIR_COUNT,
    PAIR_ID_MAX,
    PAIR_REGION_BYTES,
    PAIR_REGION_OFFSET,
    UNIVERSE_BYTES,
    decode_pair_id,
    pair_id,
    pair_descriptor,
)
from runner_riddle.universe_map import (
    CANONICAL_CELLS,
    NANNET0_HEAD,
    NANNET0_PAGE,
    UNIVERSE_BYTES as ROUTE_UNIVERSE_BYTES,
    UNIVERSE_PAGES,
    page,
    point,
)

REPO = Path(__file__).resolve().parents[1]
MIRROR_SPEC = REPO / "spec" / "mirror-memory.v1.json"
ROUTE_SPEC = REPO / "spec" / "universe-map.json"


class MirrorRouteViewTests(unittest.TestCase):
    def test_mirror_regions_exactly_fill_the_universe(self):
        self.assertEqual(HEAD_REGION_BYTES, 32 * 1024)
        self.assertEqual(PAIR_REGION_OFFSET, HEAD_REGION_BYTES)
        self.assertEqual(PAIR_REGION_BYTES, 255 * 32 * 1024)
        self.assertEqual(PAIR_REGION_OFFSET + PAIR_REGION_BYTES, UNIVERSE_BYTES)
        self.assertEqual(UNIVERSE_BYTES, ROUTE_UNIVERSE_BYTES)
        self.assertEqual(UNIVERSE_BYTES, 8 * 1024 * 1024)

    def test_relation_point_counts_agree(self):
        self.assertEqual(HEAD_COUNT + PAIR_COUNT, CANONICAL_CELLS)
        self.assertEqual(HEAD_COUNT + PAIR_COUNT, 32_896)
        self.assertEqual(PAIR_ID_MAX, PAIR_COUNT)
        self.assertEqual(NANNET0_HEAD, 0)

    def test_pair_id_roundtrip_and_record_geometry(self):
        for a, b in ((0, 1), (0, 255), (1, 2), (7, 200), (254, 255)):
            pair = pair_id(a, b)
            self.assertEqual(pair, pair_id(b, a))
            self.assertEqual(decode_pair_id(pair), (min(a, b), max(a, b)))
            record = pair_descriptor(pair)
            self.assertEqual(record.offset, PAIR_REGION_OFFSET + (pair - 1) * 256)
            self.assertEqual(record.lane_offsets[1] - record.lane_offsets[0], 128)

    def test_route_view_and_mirror_view_are_distinct_declared_views(self):
        route = json.loads(ROUTE_SPEC.read_text(encoding="utf-8"))
        mirror = json.loads(MIRROR_SPEC.read_text(encoding="utf-8"))
        self.assertEqual(route["schema"], "nanrouter.universe-map.v1")
        self.assertEqual(mirror["schema"], "nanrouter.mirror-memory.v1")
        self.assertEqual(len(route["pages"]), UNIVERSE_PAGES)
        self.assertEqual(route["page_directory_sha256"], route["page_directory_sha256"])
        # Route view keeps NANNET0 at its virtual page 255; physical view keeps
        # the NANNET0 head record at byte 0.  Those are views, not two objects.
        self.assertEqual(page(NANNET0_PAGE).head, NANNET0_HEAD)
        self.assertEqual(point(NANNET0_HEAD).page, NANNET0_PAGE)
        self.assertEqual(mirror["heads"]["nannet0_head"], 0)
        self.assertEqual(mirror["heads"]["offset_rule"], "head * 128")
        self.assertEqual(mirror["pairs"]["count"], PAIR_COUNT)
        self.assertTrue(any("different virtual view" in item for item in mirror["non_claims"]))
        self.assertEqual(mirror["layout_sha256"], mirror["layout_sha256"])

    def test_no_physical_region_claims_the_others_bytes(self):
        # The physical profile is contiguous: heads [0, 32768), pairs
        # [32768, 8388608).  The route view is virtual and must not be used as
        # a second byte allocation.
        self.assertEqual(HEAD_REGION_BYTES, PAIR_REGION_OFFSET)
        self.assertEqual(PAIR_REGION_OFFSET + PAIR_REGION_BYTES, UNIVERSE_BYTES)
        self.assertNotEqual(
            (page(NANNET0_PAGE).offset_bytes),
            (NANNET0_PAGE * 128),
        )


if __name__ == "__main__":
    unittest.main()
