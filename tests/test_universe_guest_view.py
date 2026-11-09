from __future__ import annotations

import hashlib
import json
import unittest
from typing import Any

from runner_riddle import universe_map
from runner_riddle.mirror_point_register import MirrorRegister
from runner_riddle.universe_guest_view import (
    CANONICAL_CELLS,
    FIXED_POINTS,
    FULL_ADDRESS_SPACE_BYTES,
    FULL_ADDRESS_SPACE_WORDS,
    MAX_LAYER,
    NANNET0_ALIASES,
    NANNET0_HEAD,
    NANNET0_PAGE,
    NANNET0_RING_POSITION,
    PAGE_BYTES,
    PAGE_WORDS,
    PAIR_COUNT,
    ROUTE_ROOT,
    SCHEMA,
    UNIVERSE_BYTES,
    UNIVERSE_PAGES,
    UNIVERSE_WORDS,
    VIEW_KIND,
    WORD_BYTES,
    UniverseGuestViewError,
    assert_full_coverage,
    build_view,
    digest,
    page_view,
    point_view,
    resolve_nannet0,
    resolve_raw,
    route,
    status,
    to_json,
)


def _canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class UniverseGuestViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.view = build_view()
        cls.pages = cls.view["page_directory"]
        cls.points = cls.view["relation_points"]

    def test_descriptor_declares_a_host_only_full_universe_view(self):
        view = self.view
        self.assertEqual(view["schema"], SCHEMA)
        self.assertEqual(view["kind"], VIEW_KIND)
        self.assertTrue(view["host_only"])
        self.assertFalse(view["executes_kernels"])
        self.assertFalse(view["executes_math"])
        self.assertFalse(view["native_execution_verified"])
        self.assertFalse(view["native_execution_claimed"])
        self.assertFalse(view["host_mapping_equals_native_execution"])
        self.assertFalse(view["claims_relations_true"])
        self.assertTrue(view["native_required"])

        space = view["address_space"]
        self.assertEqual(space["pages"], 256)
        self.assertEqual(space["words"], 1_048_576)
        self.assertEqual(space["bytes"], 8 * 1024 * 1024)
        self.assertEqual(space["page_words"], 4096)
        self.assertEqual(space["page_bytes"], 32 * 1024)
        self.assertEqual(space["word_bytes"], 8)
        self.assertEqual(space["first_page"], 0)
        self.assertEqual(space["last_page"], 255)
        self.assertEqual(space["first_word"], 0)
        self.assertEqual(space["last_word"], 1_048_575)
        self.assertEqual(space["first_byte"], 0)
        self.assertEqual(space["last_byte"], 8 * 1024 * 1024 - 1)
        self.assertEqual(space["end_byte_exclusive"], 8 * 1024 * 1024)
        self.assertEqual(space["covered_bytes"], 8 * 1024 * 1024)
        self.assertEqual(space["uncovered_bytes"], 0)
        self.assertTrue(space["covers_full_8_mib"])

        assertions = view["assertions"]
        self.assertTrue(assertions["full_8_mib_address_space"])
        self.assertTrue(assertions["page_directory_contiguous"])
        self.assertTrue(assertions["every_page_present"])
        self.assertTrue(assertions["every_canonical_cell_present"])
        self.assertTrue(assertions["every_relation_route_present"])
        self.assertTrue(assertions["nannet0_aliases_resolve"])
        self.assertEqual(
            assertions["full_address_space_bytes"], FULL_ADDRESS_SPACE_BYTES
        )
        self.assertEqual(
            assertions["full_address_space_words"], FULL_ADDRESS_SPACE_WORDS
        )
        self.assertFalse(assertions["kernel_execution"])
        self.assertFalse(assertions["native_execution"])
        self.assertFalse(assertions["host_mapping_equals_native_execution"])
        self.assertIn("8 MiB", assertions["coverage_assertion"])

        report = assert_full_coverage(view)
        self.assertEqual(report["status"], "green")
        self.assertEqual(report["pages"], 256)
        self.assertEqual(report["words"], 1_048_576)
        self.assertEqual(report["bytes"], 8 * 1024 * 1024)
        self.assertEqual(report["first_byte"], 0)
        self.assertEqual(report["end_byte_exclusive"], 8 * 1024 * 1024)
        self.assertTrue(report["covers_full_8_mib"])
        self.assertEqual(report["relation_points"], 32_896)
        self.assertFalse(report["executes_kernels"])
        self.assertFalse(report["host_mapping_equals_native_execution"])

        compact = status()
        self.assertEqual(compact["schema"], SCHEMA)
        self.assertEqual(compact["pages"], UNIVERSE_PAGES)
        self.assertEqual(compact["universe_words"], UNIVERSE_WORDS)
        self.assertEqual(compact["universe_bytes"], UNIVERSE_BYTES)
        self.assertEqual(compact["relation_points"], CANONICAL_CELLS)
        self.assertEqual(compact["nannet0_aliases"], list(NANNET0_ALIASES))
        self.assertEqual(
            compact["page_directory_sha256"],
            universe_map.status()["page_directory_sha256"],
        )
        self.assertFalse(compact["executes_kernels"])

    def test_every_page_has_a_complete_descriptor(self):
        pages = self.pages
        self.assertEqual(len(pages), UNIVERSE_PAGES)
        self.assertEqual(
            [entry["page"] for entry in pages],
            list(range(UNIVERSE_PAGES)),
        )
        self.assertEqual(
            [entry["offset_words"] for entry in pages],
            [index * PAGE_WORDS for index in range(UNIVERSE_PAGES)],
        )
        self.assertEqual(
            [entry["offset_bytes"] for entry in pages],
            [index * PAGE_BYTES for index in range(UNIVERSE_PAGES)],
        )

        for page_id, entry in enumerate(pages):
            expected = universe_map.page(page_id)
            self.assertEqual(page_view(page_id), entry)
            self.assertEqual(entry["page"], page_id)
            self.assertEqual(entry["offset_words"], page_id * PAGE_WORDS)
            self.assertEqual(entry["offset_bytes"], page_id * PAGE_BYTES)
            self.assertEqual(
                entry["offset_end_words"], (page_id + 1) * PAGE_WORDS
            )
            self.assertEqual(
                entry["offset_end_bytes"], (page_id + 1) * PAGE_BYTES
            )
            self.assertEqual(entry["page_words"], PAGE_WORDS)
            self.assertEqual(entry["page_bytes"], PAGE_BYTES)
            self.assertTrue(entry["covers_full_page"])
            self.assertEqual(entry["kind"], expected.kind)
            self.assertEqual(entry["head"], expected.head)
            self.assertEqual(entry["route"], expected.route)
            self.assertEqual(
                entry["ring_head_index"], expected.ring_head_index
            )
            self.assertEqual(
                entry["relation_slot_base_word"],
                expected.relation_slot_base_word,
            )
            self.assertEqual(entry["relation_slots"], expected.relation_slots)

        self.assertEqual(pages[0]["offset_bytes"], 0)
        self.assertEqual(pages[-1]["offset_end_bytes"], UNIVERSE_BYTES)
        self.assertEqual(pages[-1]["page"], NANNET0_PAGE)
        self.assertEqual(pages[-1]["kind"], "nannet0")
        self.assertEqual(pages[-1]["head"], NANNET0_HEAD)
        self.assertEqual(pages[-1]["relation_slots"], 0)

    def test_every_canonical_cell_has_identity_offsets_and_route(self):
        points = self.points
        routes = self.view["relation_point_routes"]
        self.assertEqual(len(points), CANONICAL_CELLS)
        self.assertEqual(len(routes), CANONICAL_CELLS)
        self.assertEqual(
            self.view["relation_point_summary"]["count"], CANONICAL_CELLS
        )
        self.assertEqual(
            self.view["relation_point_summary"]["fixed_heads"], FIXED_POINTS
        )
        self.assertEqual(
            self.view["relation_point_summary"]["mirror_pairs"], PAIR_COUNT
        )

        fixed = 0
        mirror_pairs = 0
        seen_pages: set[int] = set()
        for cell, entry in enumerate(points):
            expected = universe_map.point(cell)
            self.assertEqual(point_view(cell), entry)
            self.assertEqual(entry["canonical_cell"], cell)
            self.assertEqual(entry["kind"], expected.kind)
            self.assertEqual(entry["ordinal"], expected.ordinal)
            self.assertEqual(entry["page"], expected.page)
            self.assertEqual(entry["word"], expected.word)
            self.assertEqual(entry["guest_word"], expected.guest_word)
            self.assertEqual(entry["offset_words"], expected.guest_word)
            self.assertEqual(entry["page_offset_words"], expected.word)
            self.assertEqual(
                entry["page_offset_bytes"], expected.word * WORD_BYTES
            )
            self.assertEqual(
                entry["offset_bytes"], expected.guest_word * WORD_BYTES
            )
            self.assertEqual(
                entry["guest_word"],
                entry["page"] * PAGE_WORDS + entry["word"],
            )
            self.assertEqual(entry["route"], expected.route)
            self.assertEqual(entry["route"], routes[cell])
            self.assertTrue(entry["route"].startswith(ROUTE_ROOT))
            self.assertEqual(entry["nannet0"], cell == NANNET0_HEAD)
            if entry["kind"] == "head":
                fixed += 1
            else:
                self.assertEqual(entry["kind"], "mp")
                mirror_pairs += 1
            seen_pages.add(entry["page"])

        self.assertEqual(fixed, FIXED_POINTS)
        self.assertEqual(mirror_pairs, PAIR_COUNT)
        self.assertEqual(seen_pages, set(range(UNIVERSE_PAGES)))
        self.assertEqual(points[0]["page"], NANNET0_PAGE)
        self.assertEqual(points[0]["word"], 0)
        self.assertEqual(points[0]["guest_word"], NANNET0_PAGE * PAGE_WORDS)
        self.assertEqual(points[-1]["canonical_cell"], CANONICAL_CELLS - 1)
        self.assertEqual(
            points[-1]["canonical_cell"], FIXED_POINTS + PAIR_COUNT - 1
        )

    def test_every_relation_point_route_supports_all_layers(self):
        for cell in (0, 1, 255, 256, 32767, CANONICAL_CELLS - 1):
            base = universe_map.point(cell).route
            for layer in range(MAX_LAYER + 1):
                self.assertEqual(route(cell, layer), f"{base}::L{layer}")
                layered = point_view(cell, layer)
                self.assertEqual(layered["layer"], layer)
                self.assertEqual(layered["layer_route"], f"{base}::L{layer}")
        self.assertEqual(
            route(CANONICAL_CELLS - 1),
            ROUTE_ROOT + "::HW0:MP32639",
        )

    def test_nannet0_aliases_resolve_to_the_one_control_point(self):
        self.assertEqual(
            tuple(NANNET0_ALIASES), ("HW0:0", "page:255", "ring:255")
        )
        self.assertEqual(
            tuple(self.view["nannet0_aliases"]), NANNET0_ALIASES
        )
        expected = universe_map.head(NANNET0_HEAD)
        targets = []
        for alias in NANNET0_ALIASES:
            value = resolve_nannet0(alias)
            self.assertTrue(value["resolved"])
            self.assertEqual(value["alias"], alias)
            self.assertEqual(value["canonical_cell"], NANNET0_HEAD)
            self.assertEqual(value["head"], NANNET0_HEAD)
            self.assertEqual(value["page"], NANNET0_PAGE)
            self.assertEqual(
                value["ring_position"], NANNET0_RING_POSITION
            )
            self.assertEqual(value["word"], 0)
            self.assertEqual(
                value["guest_word"], NANNET0_PAGE * PAGE_WORDS
            )
            self.assertEqual(
                value["offset_bytes"],
                NANNET0_PAGE * PAGE_WORDS * WORD_BYTES,
            )
            self.assertEqual(value["route"], expected.route)
            self.assertTrue(value["nannet0"])
            targets.append((
                value["canonical_cell"],
                value["page"],
                value["ring_position"],
                value["word"],
                value["guest_word"],
                value["offset_bytes"],
                value["route"],
            ))
        self.assertEqual(len(set(targets)), 1)
        self.assertEqual(
            self.view["nannet0"]["canonical_cell"], NANNET0_HEAD
        )
        self.assertEqual(self.view["nannet0"]["page"], NANNET0_PAGE)
        self.assertEqual(
            self.view["nannet0"]["ring_position"],
            NANNET0_RING_POSITION,
        )
        self.assertEqual(self.view["nannet0"]["route"], expected.route)

    def test_raw_addresses_resolve_through_mirror_register(self):
        raws = {0x0000, 0x0001, 0x00FF, 0x0100, 0x0101,
                0x7FFF, 0x8000, 0xFFFF}
        for head_id in range(FIXED_POINTS):
            raws.add(MirrorRegister.head(head_id).forward_address)
        for mp in range(0, PAIR_COUNT, 257):
            table = MirrorRegister.mp(mp)
            raws.add(table.forward_address)
            raws.add(table.mirror_address)
        final = MirrorRegister.mp(PAIR_COUNT - 1)
        raws.add(final.forward_address)
        raws.add(final.mirror_address)

        for raw in sorted(raws):
            table = MirrorRegister.from_raw(raw)
            cell = table["canonical_cell"]
            expected = universe_map.point(cell)
            value = resolve_raw(raw)
            self.assertEqual(value["raw"], raw)
            self.assertEqual(value["raw_address"], raw)
            self.assertEqual(value["raw_address_hex"], f"0x{raw:04x}")
            self.assertEqual(value["canonical_cell"], cell)
            self.assertEqual(value["kind"], expected.kind)
            self.assertEqual(value["page"], expected.page)
            self.assertEqual(value["word"], expected.word)
            self.assertEqual(value["guest_word"], expected.guest_word)
            self.assertEqual(value["offset_words"], expected.guest_word)
            self.assertEqual(
                value["offset_bytes"], expected.guest_word * WORD_BYTES
            )
            self.assertEqual(value["route"], expected.route)
            self.assertEqual(value["raw_heads"], table["heads"])
            self.assertEqual(
                value["canonical_address"], table["canonical_address"]
            )
            self.assertEqual(value["addresses"], table["addresses"])
            self.assertEqual(
                value["forward_address"], table["addresses"][0]
            )
            self.assertEqual(
                value["mirror_address"], table["addresses"][1]
            )
            self.assertEqual(value["orientation"], table["orientation"])
            self.assertEqual(
                value["topology_sha256"], table["topology_sha256"]
            )
            self.assertEqual(
                value["resolved_via"], "MirrorRegister.from_raw"
            )
            self.assertTrue(value["canonical_map_agrees"])

    def test_bounds_and_types_are_rejected(self):
        for bad_page in (
            -1, UNIVERSE_PAGES, True, False, 1.0, "0", None, [0],
        ):
            with self.subTest(page=bad_page):
                with self.assertRaises(UniverseGuestViewError):
                    page_view(bad_page)
        for bad_cell in (
            -1, CANONICAL_CELLS, True, False, 1.0, "0", None, [0],
        ):
            with self.subTest(cell=bad_cell):
                with self.assertRaises(UniverseGuestViewError):
                    point_view(bad_cell)
        for bad_layer in (-1, MAX_LAYER + 1, True, False, 1.0, "0"):
            with self.subTest(layer=bad_layer):
                with self.assertRaises(UniverseGuestViewError):
                    point_view(0, bad_layer)
                with self.assertRaises(UniverseGuestViewError):
                    route(0, bad_layer)
        for bad_alias in (
            "HW0:1", "page:254", "ring:0", "page:255 ", "", 0, None, True,
        ):
            with self.subTest(alias=bad_alias):
                with self.assertRaises(UniverseGuestViewError):
                    resolve_nannet0(bad_alias)
        for bad_raw in (
            -1, 65536, True, False, 1.0, "0", None, [0],
        ):
            with self.subTest(raw=bad_raw):
                with self.assertRaises(UniverseGuestViewError):
                    resolve_raw(bad_raw)
        self.assertTrue(route(0, 0).endswith("::L0"))
        self.assertTrue(
            route(CANONICAL_CELLS - 1, MAX_LAYER).endswith("::L9")
        )

    def test_json_digests_and_view_are_deterministic(self):
        first = self.view
        second = build_view()
        self.assertEqual(first, second)
        self.assertEqual(to_json(first), to_json(second))
        self.assertEqual(to_json(), to_json(second))
        self.assertEqual(json.loads(to_json(first)), first)
        self.assertEqual(json.loads(to_json(first, indent=2)), first)
        self.assertEqual(digest(first), first["view_sha256"])
        self.assertEqual(digest(second), second["view_sha256"])

        payload = json.loads(to_json(first))
        payload.pop("view_sha256")
        self.assertEqual(_canonical_sha256(payload), first["view_sha256"])
        self.assertEqual(
            first["page_directory_content_sha256"],
            _canonical_sha256({
                "schema": SCHEMA,
                "pages": first["page_directory"],
            }),
        )
        self.assertEqual(
            first["relation_points_sha256"],
            _canonical_sha256({
                "schema": SCHEMA,
                "relation_points": first["relation_points"],
            }),
        )
        self.assertEqual(
            first["page_directory_sha256"],
            universe_map.status()["page_directory_sha256"],
        )
        self.assertEqual(len(first["view_sha256"]), 64)

    def test_assertions_reject_incomplete_or_misaligned_views(self):
        with self.assertRaises(UniverseGuestViewError):
            assert_full_coverage(None.__class__)

        short = json.loads(to_json(self.view))
        short["relation_points"].pop()
        with self.assertRaises(UniverseGuestViewError):
            assert_full_coverage(short)

        gap = json.loads(to_json(self.view))
        gap["page_directory"][-1]["offset_end_bytes"] -= 1
        with self.assertRaises(UniverseGuestViewError):
            assert_full_coverage(gap)

        shifted = json.loads(to_json(self.view))
        shifted["relation_points"][123]["guest_word"] += 1
        with self.assertRaises(UniverseGuestViewError):
            assert_full_coverage(shifted)

        wrong_route = json.loads(to_json(self.view))
        wrong_route["relation_point_routes"][456] = "nan://elsewhere"
        with self.assertRaises(UniverseGuestViewError):
            assert_full_coverage(wrong_route)


if __name__ == "__main__":
    unittest.main()
