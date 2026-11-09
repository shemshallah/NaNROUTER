"""Physical 8 MiB mirror-memory arithmetic: coverage, ids, lanes, fields."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from runner_riddle import mirror_memory as memory
from runner_riddle.mirror_memory import (
    HEAD_COUNT,
    HEAD_RECORD_BYTES,
    HEAD_REGION,
    HEAD_REGION_BYTES,
    HEAD_REGION_OFFSET,
    LANE0_OFFSET,
    LANE1_OFFSET,
    LANE_BYTES,
    LANE_COUNT,
    LAYOUT_SHA256,
    MirrorMemoryError,
    NANNET0_HEAD,
    PAIR_COUNT,
    PAIR_ID_MAX,
    PAIR_ID_MIN,
    PAIR_ID_VOID,
    PAIR_RECORD_BYTES,
    PAIR_REGION,
    PAIR_REGION_BYTES,
    PAIR_REGION_OFFSET,
    REAL_HEAD_COUNT,
    RESIDUAL_SLOTS,
    SCHEMA,
    UNIVERSE_BYTES,
    canonical_json,
    decode_pair_id,
    document,
    document_json,
    field_descriptor,
    field_descriptors,
    field_offset,
    head_descriptor,
    head_descriptors,
    head_field_offset,
    head_offset,
    is_void_pair_id,
    lane_descriptor,
    lane_descriptors,
    lane_offset,
    pair_descriptor,
    pair_field_offset,
    pair_id,
    pair_offset,
    status,
    status_json,
    validate,
)

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "spec" / "mirror-memory.v1.json"


class PhysicalCoverageTests(unittest.TestCase):
    def test_one_8_mib_universe_is_fully_covered_without_a_gap(self):
        self.assertEqual(UNIVERSE_BYTES, 8_388_608)
        self.assertEqual(HEAD_REGION_OFFSET, 0)
        self.assertEqual(HEAD_RECORD_BYTES, 128)
        self.assertEqual(HEAD_COUNT, 256)
        self.assertEqual(HEAD_REGION_BYTES, 32_768)
        self.assertEqual(PAIR_REGION_OFFSET, 32_768)
        self.assertEqual(PAIR_RECORD_BYTES, 256)
        self.assertEqual(PAIR_COUNT, 32_640)
        self.assertEqual(PAIR_REGION_BYTES, 8_355_840)
        self.assertEqual(HEAD_REGION.end_offset, PAIR_REGION.offset)
        self.assertEqual(PAIR_REGION.end_offset, UNIVERSE_BYTES)
        self.assertEqual(sum(region.size_bytes for region in memory.REGIONS),
                         UNIVERSE_BYTES)

        cursor = 0
        for head in range(HEAD_COUNT):
            descriptor = head_descriptor(head)
            self.assertEqual(descriptor.offset, cursor)
            self.assertEqual(descriptor.record_bytes, HEAD_RECORD_BYTES)
            cursor += descriptor.record_bytes
        self.assertEqual(cursor, HEAD_REGION_BYTES)

        for value in range(PAIR_ID_MIN, PAIR_ID_MAX + 1):
            descriptor = pair_descriptor(value)
            self.assertEqual(descriptor.offset, cursor)
            self.assertEqual(descriptor.record_bytes, PAIR_RECORD_BYTES)
            cursor += descriptor.record_bytes
        self.assertEqual(cursor, UNIVERSE_BYTES)
        self.assertEqual(validate()["byte_coverage"], "exact")
        self.assertEqual(validate()["record_coverage"], "exact")

    def test_head_zero_is_nannet0_and_the_other_255_are_real(self):
        heads = head_descriptors()
        self.assertEqual(len(heads), HEAD_COUNT)
        zero = head_descriptor(NANNET0_HEAD)
        self.assertEqual(zero.offset, 0)
        self.assertEqual(zero.kind, memory.NANNET0_KIND)
        self.assertTrue(zero.nannet0)
        self.assertEqual(REAL_HEAD_COUNT, 255)
        real = heads[1:]
        self.assertEqual(len(real), REAL_HEAD_COUNT)
        self.assertEqual([item.head for item in real], list(range(1, 256)))
        self.assertTrue(all(item.kind == memory.REAL_HEAD_KIND for item in real))
        self.assertTrue(all(not item.nannet0 for item in real))
        self.assertTrue(all(item.offset == item.head * HEAD_RECORD_BYTES
                            for item in real))
        self.assertEqual(head_offset(0), 0)
        self.assertEqual(head_offset(255), 32_640)


class PairIdTests(unittest.TestCase):
    def test_all_32640_pair_ids_roundtrip_exhaustively(self):
        seen = set()
        for a in range(HEAD_COUNT):
            for b in range(a + 1, HEAD_COUNT):
                value = pair_id(a, b)
                self.assertGreaterEqual(value, PAIR_ID_MIN)
                self.assertLessEqual(value, PAIR_ID_MAX)
                self.assertNotIn(value, seen)
                seen.add(value)
                self.assertEqual(decode_pair_id(value), (a, b))
                # The existing mirror convention accepts either order.
                self.assertEqual(pair_id(b, a), value)
        self.assertEqual(len(seen), PAIR_COUNT)
        self.assertEqual(seen, set(range(PAIR_ID_MIN, PAIR_ID_MAX + 1)))

        for value in range(PAIR_ID_MIN, PAIR_ID_MAX + 1):
            a, b = decode_pair_id(value)
            self.assertLess(a, b)
            self.assertEqual(pair_id(a, b), value)
            self.assertEqual(pair_descriptor(value).offset,
                             PAIR_REGION_OFFSET + (value - 1) * PAIR_RECORD_BYTES)
            self.assertEqual(pair_offset(value),
                             PAIR_REGION_OFFSET + (value - 1) * PAIR_RECORD_BYTES)

    def test_pair_id_formula_endpoints_and_void_sentinel(self):
        self.assertEqual(pair_id(0, 1), 1)
        self.assertEqual(pair_id(0, 255), 255)
        self.assertEqual(pair_id(1, 2), 256)
        self.assertEqual(pair_id(254, 255), 32_640)
        self.assertEqual(PAIR_ID_VOID, 0)
        self.assertTrue(is_void_pair_id(0))
        self.assertFalse(is_void_pair_id(False))
        self.assertFalse(is_void_pair_id(None))
        self.assertIsNone(decode_pair_id(PAIR_ID_VOID, allow_void=True))
        with self.assertRaises(MirrorMemoryError):
            decode_pair_id(PAIR_ID_VOID)
        for operation in (
            lambda: pair_offset(PAIR_ID_VOID),
            lambda: pair_descriptor(PAIR_ID_VOID),
            lambda: lane_offset(PAIR_ID_VOID, 0),
            lambda: lane_descriptor(PAIR_ID_VOID, 0),
        ):
            with self.subTest(operation=operation):
                with self.assertRaises(MirrorMemoryError):
                    operation()
        self.assertNotIn(PAIR_ID_VOID, {
            pair_id(a, b)
            for a in range(HEAD_COUNT)
            for b in range(a + 1, HEAD_COUNT)
        })


class LaneAndFieldTests(unittest.TestCase):
    def test_lanes_are_two_disjoint_128_byte_halves(self):
        self.assertEqual(LANE_COUNT, 2)
        self.assertEqual(LANE_BYTES, 128)
        self.assertEqual(LANE0_OFFSET, 0)
        self.assertEqual(LANE1_OFFSET, 128)
        for value in (1, 2, 255, 256, 32_639, 32_640):
            record = pair_descriptor(value)
            lane0, lane1 = lane_descriptors(value)
            self.assertEqual(lane0.offset, record.offset)
            self.assertEqual(lane1.offset, record.offset + 128)
            self.assertEqual(lane0.size_bytes, 128)
            self.assertEqual(lane1.size_bytes, 128)
            self.assertEqual(lane0.end_offset, lane1.offset)
            self.assertEqual(lane1.end_offset, record.offset + 256)
            self.assertEqual(record.lane_offsets,
                             (lane0.offset, lane1.offset))
            self.assertEqual(lane_offset(value, 0), lane0.offset)
            self.assertEqual(lane_offset(value, 1), lane1.offset)

    def test_every_field_tiles_its_region_without_overlap(self):
        for fields, start, end, label in (
            (memory.HEAD_FIELDS, 0, HEAD_RECORD_BYTES, "head"),
            (field_descriptors(0), LANE0_OFFSET, LANE1_OFFSET, "lane0"),
            (field_descriptors(1), LANE1_OFFSET, PAIR_RECORD_BYTES, "lane1"),
            (memory.PAIR_FIELDS, 0, PAIR_RECORD_BYTES, "pair"),
        ):
            with self.subTest(label=label):
                cursor = start
                for field in sorted(fields, key=lambda item: item.offset):
                    self.assertEqual(field.offset, cursor)
                    self.assertGreater(field.size, 0)
                    cursor = field.end_offset
                self.assertEqual(cursor, end)

    def test_residual_slots_and_named_field_offsets_match_contract(self):
        self.assertEqual(RESIDUAL_SLOTS, 26)
        self.assertEqual(len(field_descriptors(0)), 32)
        self.assertEqual(len(field_descriptors(1)), 27)
        for lane, base in ((0, 0), (1, 128)):
            for index in range(RESIDUAL_SLOTS):
                field = field_descriptor("residual", lane, index)
                self.assertEqual(field.offset, base + index * 4)
                self.assertEqual(field.size, 4)
                self.assertEqual(field.encoding, "f32")
                self.assertEqual(field.index, index)
                self.assertEqual(field_offset("residual", lane, index),
                                 base + index * 4)
                self.assertEqual(field_descriptor(f"residual_{index}", lane),
                                 field)

        expected_lane0 = {
            "relation_type": (104, "u32"),
            "confidence": (108, "f32"),
            "hyperedge_head": (112, "u32"),
            "cycle_flux": (116, "f32"),
            "generation": (120, "u32"),
            "flags": (124, "u32"),
        }
        for name, (offset, encoding) in expected_lane0.items():
            field = field_descriptor(name, 0)
            self.assertEqual((field.offset, field.size, field.encoding),
                             (offset, 4, encoding))

        lane1_reserved = field_descriptor("reserved", 1)
        self.assertEqual((lane1_reserved.offset, lane1_reserved.size),
                         (232, 24))
        self.assertTrue(lane1_reserved.reserved)

        expected_head = {
            "first_hyperedge": (0, 4, "u32"),
            "state": (4, 4, "u32"),
            "score": (8, 4, "f32"),
            "generation": (12, 4, "u32"),
            "identity": (16, 112, "bytes"),
        }
        for name, (offset, size, encoding) in expected_head.items():
            field = memory.head_field_descriptor(name)
            self.assertEqual((field.offset, field.size, field.encoding),
                             (offset, size, encoding))
            self.assertEqual(head_field_offset(7, name),
                             7 * HEAD_RECORD_BYTES + offset)

    def test_absolute_pair_field_offsets_stay_inside_the_record(self):
        for value in (1, 2, 777, 32_640):
            record = pair_descriptor(value)
            for lane in range(LANE_COUNT):
                for index in range(RESIDUAL_SLOTS):
                    absolute = pair_field_offset(value, "residual", lane, index)
                    self.assertGreaterEqual(absolute, record.offset)
                    self.assertLess(absolute + 4,
                                    record.offset + record.record_bytes)
            for name in ("relation_type", "confidence", "hyperedge_head",
                         "cycle_flux", "generation", "flags"):
                absolute = pair_field_offset(value, name, 0)
                self.assertGreaterEqual(absolute, record.offset)
                self.assertLess(absolute + 4,
                                record.offset + record.record_bytes)


class RejectionTests(unittest.TestCase):
    def test_head_pair_lane_and_field_bounds_and_types_are_rejected(self):
        for bad in (-1, HEAD_COUNT, True, False, 1.0, "0", None):
            with self.subTest(bad=bad):
                with self.assertRaises(MirrorMemoryError):
                    head_offset(bad)
                with self.assertRaises(MirrorMemoryError):
                    head_descriptor(bad)

        for bad in (PAIR_ID_VOID, PAIR_ID_MAX + 1, True, False, 1.0, "1", None):
            with self.subTest(pair_id=bad):
                with self.assertRaises(MirrorMemoryError):
                    decode_pair_id(bad)
                with self.assertRaises(MirrorMemoryError):
                    pair_offset(bad)
                with self.assertRaises(MirrorMemoryError):
                    pair_descriptor(bad)

        for a, b in ((-1, 0), (0, 256), (256, 255), (0, 0), (255, 255),
                     (True, 1), (0.0, 1), ("0", 1), (0, None)):
            with self.subTest(a=a, b=b):
                with self.assertRaises(MirrorMemoryError):
                    pair_id(a, b)

        for lane in (-1, LANE_COUNT, True, 1.0, "0", None):
            with self.subTest(lane=lane):
                with self.assertRaises(MirrorMemoryError):
                    lane_offset(1, lane)
                with self.assertRaises(MirrorMemoryError):
                    lane_descriptor(1, lane)
                with self.assertRaises(MirrorMemoryError):
                    field_descriptor("residual", lane, 0)

        for field, lane, index in (
            ("unknown", 0, None),
            ("residual", 0, None),
            ("residual", 0, -1),
            ("residual", 0, RESIDUAL_SLOTS),
            ("residual", 0, True),
            ("relation_type", 1, None),
            ("reserved", 0, None),
            ("relation_type", 0, 0),
            (None, 0, None),
            (7, 0, None),
        ):
            with self.subTest(field=field, lane=lane, index=index):
                with self.assertRaises(MirrorMemoryError):
                    field_descriptor(field, lane, index)

        for bad in (-1, HEAD_COUNT, True, 1.0, "0", None):
            with self.subTest(head=bad):
                with self.assertRaises(MirrorMemoryError):
                    head_field_offset(bad, "state")
        for bad in ("unknown", None, 7, ""):
            with self.subTest(field=bad):
                with self.assertRaises(MirrorMemoryError):
                    memory.head_field_descriptor(bad)

    def test_invalid_lane_residual_and_field_indices_never_write(self):
        # Address arithmetic is read-only: failures are exceptions, not state.
        before = document_json()
        for operation in (
            lambda: field_descriptor("residual", 0, 26),
            lambda: pair_field_offset(1, "residual", 1, 26),
            lambda: lane_offset(32_641, 0),
        ):
            with self.assertRaises(MirrorMemoryError):
                operation()
        self.assertEqual(document_json(), before)


class DeterministicDocumentTests(unittest.TestCase):
    def test_status_and_document_json_are_repeatable_and_canonical(self):
        first_status = status_json()
        second_status = status_json()
        self.assertEqual(first_status, second_status)
        self.assertEqual(json.loads(first_status), status())
        self.assertEqual(first_status, canonical_json(status()))

        first_document = document_json()
        second_document = document_json()
        self.assertEqual(first_document, second_document)
        self.assertEqual(json.loads(first_document), document())
        self.assertEqual(first_document, canonical_json(document()))
        self.assertNotIn("\n", first_document)
        self.assertTrue(first_document.startswith('{"'))
        self.assertIn('"second_universe":false', first_document)
        self.assertEqual(document()["layout_sha256"], LAYOUT_SHA256)
        self.assertEqual(status()["layout_sha256"], LAYOUT_SHA256)
        self.assertRegex(LAYOUT_SHA256, r"^[0-9a-f]{64}$")

    def test_frozen_spec_is_the_same_deterministic_document(self):
        frozen = json.loads(SPEC.read_text(encoding="utf-8"))
        self.assertEqual(frozen, document())
        self.assertEqual(frozen["schema"], SCHEMA)
        self.assertEqual(frozen["universe"]["bytes"], UNIVERSE_BYTES)
        self.assertEqual(frozen["regions"][0], HEAD_REGION.as_dict())
        self.assertEqual(frozen["regions"][1], PAIR_REGION.as_dict())
        self.assertEqual(frozen["layout_sha256"], LAYOUT_SHA256)
        self.assertFalse(frozen["views"]["route_view"]["second_universe"])
        self.assertFalse(frozen["views"]["route_view"]["second_allocation"])
        self.assertFalse(frozen["views"]["route_view"]["copy"])
        self.assertTrue(frozen["views"]["route_view"]["same_universe"])
        self.assertIn("not a second universe",
                      " ".join(frozen["non_claims"]))
        self.assertFalse(frozen["coverage"]["byte_coverage"] != "exact")


if __name__ == "__main__":
    unittest.main()
