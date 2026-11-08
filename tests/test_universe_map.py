from __future__ import annotations

import json
import unittest

from runner_riddle.universe_map import (
    CANONICAL_CELLS,
    FIXED_POINTS,
    MAX_LAYER,
    MAX_RELATION_GUEST_WORD,
    MP_SLOTS_PER_PAGE,
    MP_SLOT_BASE_WORD,
    NANNET0_HEAD,
    NANNET0_PAGE,
    NANNET0_RING_POSITION,
    PAGE_BYTES,
    PAGE_WORDS,
    PAIR_COUNT,
    UNIVERSE_BYTES,
    UNIVERSE_PAGES,
    UNIVERSE_WORDS,
    UniverseMapError,
    from_raw,
    head,
    iter_points,
    mirror_pair,
    page,
    page_directory,
    page_directory_document,
    point,
    route,
    status,
    validate,
)
from runner_riddle.mirror_point_register import MirrorRegister


class UniverseMapTests(unittest.TestCase):
    def test_layout_is_the_full_eight_mib_universe(self):
        self.assertEqual(UNIVERSE_PAGES, 256)
        self.assertEqual(UNIVERSE_BYTES, 8 * 1024 * 1024)
        self.assertEqual(UNIVERSE_WORDS, 1_048_576)
        self.assertEqual(PAGE_WORDS, 4096)
        directory = page_directory()
        self.assertEqual(len(directory), 256)
        self.assertEqual(
            [item.page for item in directory], list(range(256))
        )
        self.assertEqual(
            directory[-1].offset_bytes + PAGE_BYTES, UNIVERSE_BYTES
        )
        self.assertEqual(directory[-1].offset_bytes + 4096 * 8, UNIVERSE_BYTES)
        self.assertEqual(directory[-1].kind, "nannet0")
        self.assertEqual(directory[-1].head, NANNET0_HEAD)
        self.assertEqual(directory[-1].relation_slots, 0)
        for item in directory[:-1]:
            self.assertEqual(item.kind, "head")
            self.assertEqual(item.head, item.page + 1)
            self.assertEqual(item.ring_head_index, item.page)
            self.assertEqual(item.relation_slots, MP_SLOTS_PER_PAGE)
            self.assertEqual(item.relation_slot_base_word, MP_SLOT_BASE_WORD)

    def test_nannet0_is_one_point_with_explicit_aliases(self):
        record = head(0)
        self.assertTrue(record.nannet0)
        self.assertEqual(record.page, NANNET0_PAGE)
        self.assertEqual(record.word, 0)
        self.assertEqual(record.guest_word, NANNET0_PAGE * PAGE_WORDS)
        self.assertEqual(record.route, "nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0::HW0:0")
        self.assertEqual(point(NANNET0_HEAD), record)
        self.assertEqual(page(NANNET0_PAGE).head, NANNET0_HEAD)
        report = status()
        self.assertEqual(report["nannet0_ring_position"], NANNET0_RING_POSITION)
        self.assertEqual(
            report["nannet0_aliases"], ["HW0:0", "page:255", "ring:255"]
        )

    def test_fixed_heads_map_to_pages_and_record_word_zero(self):
        for head_id in range(256):
            with self.subTest(head=head_id):
                record = head(head_id)
                expected_page = (
                    NANNET0_PAGE if head_id == 0 else head_id - 1
                )
                self.assertEqual(record.page, expected_page)
                self.assertEqual(record.word, 0)
                self.assertEqual(record.guest_word, expected_page * PAGE_WORDS)
                self.assertEqual(record.kind, "head")
                self.assertEqual(record.ordinal, head_id)
                self.assertEqual(
                    record.route.endswith(f"::HW0:{head_id}"), True
                )

    def test_all_mirror_pairs_cover_every_real_head_page(self):
        counts = [0] * 255
        for mp in range(PAIR_COUNT):
            with self.subTest(mp=mp):
                record = mirror_pair(mp)
                self.assertEqual(record.canonical_cell, 256 + mp)
                self.assertEqual(record.kind, "mp")
                self.assertEqual(record.ordinal, mp)
                self.assertEqual(record.page, mp % 255)
                self.assertEqual(record.word, 3840 + 2 * (mp // 255))
                self.assertLess(record.word, PAGE_WORDS)
                self.assertFalse(record.nannet0)
                self.assertNotEqual(record.page, NANNET0_PAGE)
                counts[record.page] += 1
        self.assertEqual(counts, [128] * 255)

    def test_every_relation_point_is_unique_and_inside_the_universe(self):
        seen_cells = set()
        seen_pages = set()
        max_word = -1
        for record in iter_points():
            with self.subTest(cell=record.canonical_cell):
                self.assertNotIn(record.canonical_cell, seen_cells)
                seen_cells.add(record.canonical_cell)
                seen_pages.add(record.page)
                self.assertGreaterEqual(record.guest_word, 0)
                self.assertLess(record.guest_word, UNIVERSE_WORDS)
                self.assertEqual(
                    record.guest_word,
                    record.page * PAGE_WORDS + record.word,
                )
                self.assertEqual(
                    record.offset_bytes, record.guest_word * 8
                )
                max_word = max(max_word, record.guest_word)
        self.assertEqual(len(seen_cells), CANONICAL_CELLS)
        self.assertEqual(seen_cells, set(range(CANONICAL_CELLS)))
        self.assertEqual(seen_pages, set(range(UNIVERSE_PAGES)))
        self.assertEqual(max_word, NANNET0_PAGE * PAGE_WORDS)
        self.assertEqual(max_word, 1_044_480)
        self.assertGreater(MAX_RELATION_GUEST_WORD, 0)
        self.assertLess(MAX_RELATION_GUEST_WORD, max_word)

    def test_route_supports_all_points_and_layers(self):
        for cell in (0, 1, 255, 256, 32767, 32895):
            for layer in range(MAX_LAYER + 1):
                with self.subTest(cell=cell, layer=layer):
                    value = route(cell, layer)
                    self.assertTrue(value.startswith("nan://"))
                    self.assertTrue(value.endswith(f"::L{layer}"))
        self.assertIn("HW0:0", route(0))
        self.assertIn("HW0:255", route(255))
        self.assertIn("HW0:MP0", route(256))
        self.assertIn("HW0:MP32639", route(32895))
        for bad_cell in (-1, CANONICAL_CELLS, True):
            with self.assertRaises(UniverseMapError):
                route(bad_cell)
        for bad_layer in (-1, MAX_LAYER + 1, True):
            with self.assertRaises(UniverseMapError):
                route(0, bad_layer)

    def test_raw_double_endian_addresses_resolve_through_mirror_register(self):
        for raw in (0x0000, 0x0100, 0x07FF, 0xFFFF):
            with self.subTest(raw=hex(raw)):
                expected = MirrorRegister.from_raw(raw)
                record = from_raw(raw)
                self.assertEqual(record.canonical_cell, expected["canonical_cell"])
                self.assertEqual(record.route, point(expected["canonical_cell"]).route)
        with self.assertRaises(UniverseMapError):
            from_raw(65536)
        with self.assertRaises(UniverseMapError):
            from_raw(True)

    def test_validate_is_exhaustive_and_stable(self):
        report = validate()
        self.assertEqual(report["status"], "green")
        self.assertEqual(report["pages"], 256)
        self.assertEqual(report["universe_bytes"], 8 * 1024 * 1024)
        self.assertEqual(report["universe_words"], 1_048_576)
        self.assertEqual(report["relation_points"], 32_896)
        self.assertEqual(report["fixed_heads"], 256)
        self.assertEqual(report["mirror_pairs"], 32_640)
        self.assertEqual(report["coverage"], 1.0)
        self.assertEqual(report["mp_slots_per_page"], 128)
        self.assertEqual(report["max_guest_word"], 1_044_480)
        self.assertFalse(report["executes_math"])
        self.assertFalse(report["claims_relations_true"])
        self.assertEqual(len(report["page_directory_sha256"]), 64)
        self.assertEqual(report, validate())
        self.assertEqual(report, status())

    def test_page_directory_document_is_json_safe_and_deterministic(self):
        document = page_directory_document()
        self.assertEqual(document["schema"], "nanrouter.universe-map.v1")
        self.assertEqual(len(document["pages"]), 256)
        self.assertEqual(document["relation_points"]["count"], 32_896)
        self.assertEqual(
            json.loads(json.dumps(document, sort_keys=True)), document
        )
        self.assertEqual(document, page_directory_document())
        from pathlib import Path
        spec = Path(__file__).resolve().parents[1] / "spec" / "universe-map.json"
        self.assertEqual(json.loads(spec.read_text(encoding="utf-8")), document)

    def test_page_and_point_bounds_are_typed(self):
        for value in (-1, 256, True, 1.0, "0"):
            with self.subTest(value=value):
                with self.assertRaises(UniverseMapError):
                    page(value)
        for value in (-1, 256, True):
            with self.assertRaises(UniverseMapError):
                head(value)
        for value in (-1, PAIR_COUNT, True):
            with self.assertRaises(UniverseMapError):
                mirror_pair(value)
        for value in (-1, CANONICAL_CELLS, True):
            with self.assertRaises(UniverseMapError):
                point(value)


if __name__ == "__main__":
    unittest.main()
