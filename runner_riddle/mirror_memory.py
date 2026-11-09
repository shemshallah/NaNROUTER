"""Physical mirror-memory profile for the ONE 8 MiB NaNROUTER universe.

This module is pure integer address arithmetic. It describes where head and
mirror-pair bytes live inside the existing 8,388,608-byte universe; it does
not execute a kernel, evaluate residual slots, read or write a chart, or make
any mathematical truth claim.

Physical profile
----------------
* total universe: 8,388,608 bytes;
* head region: offset 0, 256 records x 128 bytes = 32,768 bytes;
* head 0 is NANNET0; heads 1..255 are real heads;
* pair region: offset 32,768, 32,640 records x 256 bytes = 8,355,840 bytes;
* pair id 0 is the void sentinel; real pair ids are 1..32,640;
* pair id for a < b is ``1 + a*(511-a)/2 + (b-a-1)``;
* each pair record has lane 0 at +0 and lane 1 at +128, 128 bytes each.

The ``spec/universe-map.json`` route view is a *different virtual view over
the same one 8 MiB universe*: 255 real-head pages plus one NANNET0 page, with
pair records scattered into page slots. It is not a second universe, not a
second allocation, and not a copy. This physical profile stores those same
pair records contiguously at 32,768..8,388,608.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Iterator

SCHEMA = "nanrouter.mirror-memory.v1"
PROFILE = "physical-8mib"

UNIVERSE_BYTES = 8_388_608

HEAD_REGION_OFFSET = 0
HEAD_RECORD_BYTES = 128
HEAD_COUNT = 256
NANNET0_HEAD = 0
REAL_HEAD_FIRST = 1
REAL_HEAD_LAST = 255
REAL_HEAD_COUNT = 255
NANNET0_KIND = "nannet0"
REAL_HEAD_KIND = "real-head"
HEAD_REGION_BYTES = HEAD_COUNT * HEAD_RECORD_BYTES

PAIR_REGION_OFFSET = 32_768
PAIR_RECORD_BYTES = 256
PAIR_COUNT = 32_640
PAIR_ID_VOID = 0
PAIR_ID_MIN = 1
PAIR_ID_MAX = 32_640
PAIR_REGION_BYTES = PAIR_COUNT * PAIR_RECORD_BYTES

LANE_COUNT = 2
LANE_BYTES = 128
LANE0_OFFSET = 0
LANE1_OFFSET = 128

F32_BYTES = 4
U32_BYTES = 4
RESIDUAL_SLOTS = 26
RESIDUAL_SLOT_BYTES = 4
RESIDUAL_BYTES = RESIDUAL_SLOTS * RESIDUAL_SLOT_BYTES

FIELD_ENCODING_F32 = "f32"
FIELD_ENCODING_U32 = "u32"
FIELD_ENCODING_BYTES = "bytes"

PAIR_ID_FORMULA = "1 + a*(511-a)/2 + (b-a-1) for 0 <= a < b <= 255"

assert HEAD_REGION_BYTES == 32_768
assert PAIR_REGION_OFFSET == HEAD_REGION_BYTES
assert PAIR_REGION_BYTES == 8_355_840
assert PAIR_REGION_OFFSET + PAIR_REGION_BYTES == UNIVERSE_BYTES
assert PAIR_ID_MAX == PAIR_COUNT
assert LANE0_OFFSET + LANE_BYTES == LANE1_OFFSET
assert LANE1_OFFSET + LANE_BYTES == PAIR_RECORD_BYTES


class MirrorMemoryError(ValueError):
    """A head, pair id, lane, field, or byte offset is outside the profile."""


def _int(value: int, name: str, minimum: int, maximum: int) -> int:
    """Accept only real integers, rejecting bool and other numeric lookalikes."""
    if type(value) is not int or not minimum <= value <= maximum:
        raise MirrorMemoryError(f"{name} must be an integer {minimum}..{maximum}")
    return value


def _lane(value: int) -> int:
    return _int(value, "lane", 0, LANE_COUNT - 1)


@dataclass(frozen=True)
class RegionDescriptor:
    """A contiguous record region in the one physical 8 MiB universe."""

    name: str
    offset: int
    record_count: int
    record_bytes: int

    @property
    def size_bytes(self) -> int:
        return self.record_count * self.record_bytes

    @property
    def end_offset(self) -> int:
        return self.offset + self.size_bytes

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "offset_bytes": self.offset,
            "record_count": self.record_count,
            "record_bytes": self.record_bytes,
            "size_bytes": self.size_bytes,
            "end_offset": self.end_offset,
        }


@dataclass(frozen=True)
class FieldDescriptor:
    """A field inside a 128-byte head record or pair lane.

    ``offset`` is relative to the record start for pair fields and to the head
    record start for head fields. For lane 1 fields this means byte 128 is the
    first residual slot, matching the physical profile's byte numbering.
    """

    name: str
    offset: int
    size: int
    encoding: str
    lane: int | None = None
    index: int | None = None
    reserved: bool = False

    @property
    def end_offset(self) -> int:
        return self.offset + self.size

    def as_dict(self) -> dict:
        value = {
            "name": self.name,
            "offset_bytes": self.offset,
            "size_bytes": self.size,
            "encoding": self.encoding,
            "reserved": self.reserved,
        }
        if self.lane is not None:
            value["lane"] = self.lane
        if self.index is not None:
            value["index"] = self.index
        return value


@dataclass(frozen=True)
class HeadDescriptor:
    """One 128-byte head record."""

    head: int
    offset: int
    kind: str
    nannet0: bool
    record_bytes: int = HEAD_RECORD_BYTES

    def as_dict(self) -> dict:
        return {
            "head": self.head,
            "offset_bytes": self.offset,
            "record_bytes": self.record_bytes,
            "kind": self.kind,
            "nannet0": self.nannet0,
        }


@dataclass(frozen=True)
class LaneDescriptor:
    """One 128-byte lane inside a 256-byte pair record."""

    pair_id: int
    lane: int
    offset: int
    size_bytes: int = LANE_BYTES

    @property
    def end_offset(self) -> int:
        return self.offset + self.size_bytes

    def as_dict(self) -> dict:
        return {
            "pair_id": self.pair_id,
            "lane": self.lane,
            "offset_bytes": self.offset,
            "size_bytes": self.size_bytes,
            "end_offset": self.end_offset,
        }


@dataclass(frozen=True)
class PairDescriptor:
    """One 256-byte pair record and its canonical ordered head pair."""

    pair_id: int
    a: int
    b: int
    offset: int
    record_bytes: int = PAIR_RECORD_BYTES

    @property
    def lane_offsets(self) -> tuple[int, int]:
        return (self.offset + LANE0_OFFSET, self.offset + LANE1_OFFSET)

    def as_dict(self) -> dict:
        return {
            "pair_id": self.pair_id,
            "a": self.a,
            "b": self.b,
            "offset_bytes": self.offset,
            "record_bytes": self.record_bytes,
            "lane_offsets": list(self.lane_offsets),
        }


def _residual_fields(lane: int) -> tuple[FieldDescriptor, ...]:
    base = LANE0_OFFSET if lane == 0 else LANE1_OFFSET
    return tuple(
        FieldDescriptor(
            name="residual",
            offset=base + index * RESIDUAL_SLOT_BYTES,
            size=RESIDUAL_SLOT_BYTES,
            encoding=FIELD_ENCODING_F32,
            lane=lane,
            index=index,
        )
        for index in range(RESIDUAL_SLOTS)
    )


HEAD_FIELDS: tuple[FieldDescriptor, ...] = (
    FieldDescriptor("first_hyperedge", 0, 4, FIELD_ENCODING_U32),
    FieldDescriptor("state", 4, 4, FIELD_ENCODING_U32),
    FieldDescriptor("score", 8, 4, FIELD_ENCODING_F32),
    FieldDescriptor("generation", 12, 4, FIELD_ENCODING_U32),
    FieldDescriptor("identity", 16, 112, FIELD_ENCODING_BYTES, reserved=True),
)

PAIR_LANE0_FIELDS: tuple[FieldDescriptor, ...] = _residual_fields(0) + (
    FieldDescriptor("relation_type", 104, 4, FIELD_ENCODING_U32, lane=0),
    FieldDescriptor("confidence", 108, 4, FIELD_ENCODING_F32, lane=0),
    FieldDescriptor("hyperedge_head", 112, 4, FIELD_ENCODING_U32, lane=0),
    FieldDescriptor("cycle_flux", 116, 4, FIELD_ENCODING_F32, lane=0),
    FieldDescriptor("generation", 120, 4, FIELD_ENCODING_U32, lane=0),
    FieldDescriptor("flags", 124, 4, FIELD_ENCODING_U32, lane=0),
)

PAIR_LANE1_FIELDS: tuple[FieldDescriptor, ...] = _residual_fields(1) + (
    FieldDescriptor(
        "reserved", 232, 24, FIELD_ENCODING_BYTES, lane=1, reserved=True
    ),
)

PAIR_FIELDS: tuple[FieldDescriptor, ...] = PAIR_LANE0_FIELDS + PAIR_LANE1_FIELDS

HEAD_REGION = RegionDescriptor(
    "heads", HEAD_REGION_OFFSET, HEAD_COUNT, HEAD_RECORD_BYTES
)
PAIR_REGION = RegionDescriptor(
    "pairs", PAIR_REGION_OFFSET, PAIR_COUNT, PAIR_RECORD_BYTES
)
REGIONS = (HEAD_REGION, PAIR_REGION)

_HEAD_FIELD_BY_NAME = {field.name: field for field in HEAD_FIELDS}
_LANE_FIELD_BY_NAME = {
    lane: {field.name: field for field in fields if field.index is None}
    for lane, fields in ((0, PAIR_LANE0_FIELDS), (1, PAIR_LANE1_FIELDS))
}
_PAIR_STARTS = tuple(
    1 + a * (2 * HEAD_COUNT - 1 - a) // 2 for a in range(HEAD_COUNT - 1)
)


def pair_id(a: int, b: int) -> int:
    """Return the canonical 1..32640 id for two distinct heads.

    ``a`` and ``b`` are unordered at the API boundary and are canonicalized to
    ``a < b``, matching the existing mirror-point convention. Lane 0 is always
    the lower head of that canonical ordered pair.
    """
    a = _int(a, "head a", 0, HEAD_COUNT - 1)
    b = _int(b, "head b", 0, HEAD_COUNT - 1)
    if a == b:
        raise MirrorMemoryError("a palindromic head does not identify a pair record")
    if a > b:
        a, b = b, a
    return 1 + a * (2 * HEAD_COUNT - 1 - a) // 2 + (b - a - 1)


def decode_pair_id(value: int, *, allow_void: bool = False) -> tuple[int, int] | None:
    """Decode a real pair id to its canonical ordered head pair.

    Pair id 0 is the void sentinel rather than a record. It raises by default;
    ``allow_void=True`` returns ``None`` so callers can carry an explicit
    "no pair" state without inventing head coordinates.
    """
    if type(value) is int and value == PAIR_ID_VOID:
        if allow_void:
            return None
        raise MirrorMemoryError("pair id 0 is the void sentinel, not a record")
    value = _int(value, "pair id", PAIR_ID_MIN, PAIR_ID_MAX)
    low, high = 0, len(_PAIR_STARTS) - 1
    while low < high:
        middle = (low + high + 1) // 2
        if _PAIR_STARTS[middle] <= value:
            low = middle
        else:
            high = middle - 1
    a = low
    b = a + 1 + value - _PAIR_STARTS[a]
    if not 0 <= a < b < HEAD_COUNT:
        raise MirrorMemoryError("pair id does not decode inside the head range")
    return a, b


def pair_heads(value: int) -> tuple[int, int]:
    """Alias for :func:`decode_pair_id`; the void id is not a pair."""
    result = decode_pair_id(value)
    assert result is not None
    return result


def is_void_pair_id(value: object) -> bool:
    """True only for the integer sentinel 0 (bool is never a pair id)."""
    return type(value) is int and value == PAIR_ID_VOID


def head_offset(head: int) -> int:
    """Absolute byte offset of a 128-byte head record."""
    head = _int(head, "head", 0, HEAD_COUNT - 1)
    return HEAD_REGION_OFFSET + head * HEAD_RECORD_BYTES


def head_descriptor(head: int) -> HeadDescriptor:
    head = _int(head, "head", 0, HEAD_COUNT - 1)
    nannet0 = head == NANNET0_HEAD
    return HeadDescriptor(
        head=head,
        offset=head_offset(head),
        kind=NANNET0_KIND if nannet0 else REAL_HEAD_KIND,
        nannet0=nannet0,
    )


def head_descriptors() -> tuple[HeadDescriptor, ...]:
    return tuple(head_descriptor(head) for head in range(HEAD_COUNT))


def pair_offset(value: int) -> int:
    """Absolute byte offset of a 256-byte pair record; 0 is rejected."""
    value = _int(value, "pair id", PAIR_ID_MIN, PAIR_ID_MAX)
    return PAIR_REGION_OFFSET + (value - PAIR_ID_MIN) * PAIR_RECORD_BYTES


def pair_descriptor(value: int) -> PairDescriptor:
    value = _int(value, "pair id", PAIR_ID_MIN, PAIR_ID_MAX)
    a, b = decode_pair_id(value)  # type: ignore[misc]
    return PairDescriptor(
        pair_id=value,
        a=a,
        b=b,
        offset=pair_offset(value),
    )


def lane_offset(value: int, lane: int) -> int:
    """Absolute byte offset of lane 0 or lane 1 within a pair record."""
    lane = _lane(lane)
    return pair_offset(value) + lane * LANE_BYTES


def lane_descriptor(value: int, lane: int) -> LaneDescriptor:
    lane = _lane(lane)
    return LaneDescriptor(
        pair_id=_int(value, "pair id", PAIR_ID_MIN, PAIR_ID_MAX),
        lane=lane,
        offset=lane_offset(value, lane),
    )


def lane_descriptors(value: int) -> tuple[LaneDescriptor, ...]:
    return tuple(lane_descriptor(value, lane) for lane in range(LANE_COUNT))


def _parse_residual_name(field: object) -> int | None:
    if type(field) is not str or not field.startswith("residual_"):
        return None
    suffix = field[len("residual_"):]
    if not suffix.isdigit():
        return None
    return int(suffix)


def field_descriptor(
    field: str, lane: int = 0, index: int | None = None
) -> FieldDescriptor:
    """Return a pair field descriptor; offset is record-relative.

    Residual slots are addressed as ``field_descriptor("residual", lane, n)``
    (``residual_<n>`` is also accepted) and otherwise by canonical field name.
    """
    lane = _lane(lane)
    named = _LANE_FIELD_BY_NAME[lane]
    residual_index = index
    if type(field) is str and field in ("residual", "residual_slot", "slot"):
        if residual_index is None:
            raise MirrorMemoryError("residual slot requires an index 0..25")
    else:
        parsed = _parse_residual_name(field)
        if parsed is not None:
            if residual_index is not None:
                raise MirrorMemoryError("residual index was supplied twice")
            residual_index = parsed
        elif type(field) is str and field in named:
            if residual_index is not None:
                raise MirrorMemoryError("named fields do not take a slot index")
            return named[field]
        else:
            raise MirrorMemoryError(f"unknown lane {lane} field: {field!r}")
    residual_index = _int(
        residual_index, "residual slot", 0, RESIDUAL_SLOTS - 1  # type: ignore[arg-type]
    )
    base = LANE0_OFFSET if lane == 0 else LANE1_OFFSET
    return FieldDescriptor(
        name="residual",
        offset=base + residual_index * RESIDUAL_SLOT_BYTES,
        size=RESIDUAL_SLOT_BYTES,
        encoding=FIELD_ENCODING_F32,
        lane=lane,
        index=residual_index,
    )


def field_offset(field: str, lane: int = 0, index: int | None = None) -> int:
    """Record-relative byte offset of a pair field."""
    return field_descriptor(field, lane, index).offset


def pair_field_offset(
    value: int, field: str, lane: int = 0, index: int | None = None
) -> int:
    """Absolute byte offset of a pair field inside the 8 MiB universe."""
    return pair_offset(value) + field_offset(field, lane, index)


def head_field_descriptor(field: str) -> FieldDescriptor:
    if type(field) is not str or field not in _HEAD_FIELD_BY_NAME:
        raise MirrorMemoryError(f"unknown head field: {field!r}")
    return _HEAD_FIELD_BY_NAME[field]


def head_field_offset(head: int, field: str) -> int:
    """Absolute byte offset of a field inside a head record."""
    return head_offset(head) + head_field_descriptor(field).offset


def field_descriptors(lane: int) -> tuple[FieldDescriptor, ...]:
    """All field descriptors for one pair lane, in byte order."""
    lane = _lane(lane)
    return PAIR_LANE0_FIELDS if lane == 0 else PAIR_LANE1_FIELDS


def _check_tiling(
    fields: tuple[FieldDescriptor, ...], start: int, end: int, name: str
) -> None:
    cursor = start
    for field in sorted(fields, key=lambda item: item.offset):
        if field.size <= 0:
            raise MirrorMemoryError(f"{name} field {field.name!r} is empty")
        if field.offset != cursor:
            raise MirrorMemoryError(
                f"{name} fields overlap or leave a gap at byte {cursor}"
            )
        cursor = field.end_offset
    if cursor != end:
        raise MirrorMemoryError(f"{name} fields do not cover {start}..{end}")


def _layout_payload() -> dict:
    return {
        "schema": SCHEMA,
        "profile": PROFILE,
        "universe_bytes": UNIVERSE_BYTES,
        "regions": [region.as_dict() for region in REGIONS],
        "heads": {
            "count": HEAD_COUNT,
            "record_bytes": HEAD_RECORD_BYTES,
            "nannet0_head": NANNET0_HEAD,
            "real_heads": {
                "first": REAL_HEAD_FIRST,
                "last": REAL_HEAD_LAST,
                "count": REAL_HEAD_COUNT,
            },
            "fields": [field.as_dict() for field in HEAD_FIELDS],
        },
        "pairs": {
            "count": PAIR_COUNT,
            "record_bytes": PAIR_RECORD_BYTES,
            "id": {
                "void_sentinel": PAIR_ID_VOID,
                "first": PAIR_ID_MIN,
                "last": PAIR_ID_MAX,
                "formula": PAIR_ID_FORMULA,
                "order": "a < b",
            },
            "lanes": [
                {"lane": 0, "offset_bytes": LANE0_OFFSET, "size_bytes": LANE_BYTES},
                {"lane": 1, "offset_bytes": LANE1_OFFSET, "size_bytes": LANE_BYTES},
            ],
            "lane_0_fields": [field.as_dict() for field in PAIR_LANE0_FIELDS],
            "lane_1_fields": [field.as_dict() for field in PAIR_LANE1_FIELDS],
        },
    }


def canonical_json(value: object) -> str:
    """Canonical compact JSON: sorted keys, ASCII, no NaN/Infinity."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


LAYOUT_SHA256 = hashlib.sha256(
    canonical_json(_layout_payload()).encode("utf-8")
).hexdigest()


def validate() -> dict:
    """Exhaustively verify record, pair-id, lane, and field coverage."""
    if HEAD_REGION.offset != HEAD_REGION_OFFSET:
        raise MirrorMemoryError("head region does not start at byte 0")
    if HEAD_REGION.size_bytes != HEAD_REGION_BYTES:
        raise MirrorMemoryError("head region size is wrong")
    if PAIR_REGION.offset != HEAD_REGION.end_offset:
        raise MirrorMemoryError("pair region does not follow the head region")
    if PAIR_REGION.size_bytes != PAIR_REGION_BYTES:
        raise MirrorMemoryError("pair region size is wrong")
    if PAIR_REGION.end_offset != UNIVERSE_BYTES:
        raise MirrorMemoryError("regions do not cover the 8 MiB universe")

    head_end = HEAD_REGION.offset
    for head in range(HEAD_COUNT):
        descriptor = head_descriptor(head)
        if descriptor.offset != head_end:
            raise MirrorMemoryError("head records are not contiguous")
        if descriptor.nannet0 != (head == NANNET0_HEAD):
            raise MirrorMemoryError("NANNET0 head binding is inconsistent")
        if head == NANNET0_HEAD:
            if descriptor.kind != NANNET0_KIND or descriptor.offset != 0:
                raise MirrorMemoryError("head 0 must be NANNET0 at byte 0")
        elif descriptor.kind != REAL_HEAD_KIND:
            raise MirrorMemoryError("real head has the wrong kind")
        head_end = descriptor.offset + descriptor.record_bytes
    if head_end != HEAD_REGION.end_offset:
        raise MirrorMemoryError("head records do not fill the head region")

    pair_end = PAIR_REGION.offset
    for value in range(PAIR_ID_MIN, PAIR_ID_MAX + 1):
        descriptor = pair_descriptor(value)
        if descriptor.offset != pair_end:
            raise MirrorMemoryError("pair records are not contiguous")
        if pair_id(descriptor.a, descriptor.b) != value:
            raise MirrorMemoryError("pair id/head decode is not a roundtrip")
        lane0, lane1 = lane_descriptors(value)
        if lane0.offset != descriptor.offset + LANE0_OFFSET:
            raise MirrorMemoryError("lane 0 offset is wrong")
        if lane1.offset != descriptor.offset + LANE1_OFFSET:
            raise MirrorMemoryError("lane 1 offset is wrong")
        if lane0.end_offset != lane1.offset:
            raise MirrorMemoryError("pair lanes overlap")
        if lane1.end_offset != descriptor.offset + descriptor.record_bytes:
            raise MirrorMemoryError("pair lanes do not fill the record")
        pair_end = descriptor.offset + descriptor.record_bytes
    if pair_end != PAIR_REGION.end_offset:
        raise MirrorMemoryError("pair records do not fill the pair region")

    _check_tiling(HEAD_FIELDS, 0, HEAD_RECORD_BYTES, "head")
    _check_tiling(PAIR_LANE0_FIELDS, LANE0_OFFSET, LANE1_OFFSET, "lane 0")
    _check_tiling(PAIR_LANE1_FIELDS, LANE1_OFFSET, PAIR_RECORD_BYTES, "lane 1")
    _check_tiling(PAIR_FIELDS, 0, PAIR_RECORD_BYTES, "pair record")

    return {
        "schema": SCHEMA,
        "profile": PROFILE,
        "status": "green",
        "universe_bytes": UNIVERSE_BYTES,
        "regions": [region.as_dict() for region in REGIONS],
        "heads": {
            "count": HEAD_COUNT,
            "record_bytes": HEAD_RECORD_BYTES,
            "covered_bytes": HEAD_REGION_BYTES,
            "first_offset": head_descriptor(0).offset,
            "last_offset": head_descriptor(HEAD_COUNT - 1).offset,
            "nannet0_head": NANNET0_HEAD,
            "real_heads": REAL_HEAD_COUNT,
        },
        "pairs": {
            "count": PAIR_COUNT,
            "record_bytes": PAIR_RECORD_BYTES,
            "covered_bytes": PAIR_REGION_BYTES,
            "first_offset": pair_descriptor(PAIR_ID_MIN).offset,
            "last_offset": pair_descriptor(PAIR_ID_MAX).offset,
            "void_sentinel": PAIR_ID_VOID,
            "first_id": PAIR_ID_MIN,
            "last_id": PAIR_ID_MAX,
        },
        "lanes": {
            "count": LANE_COUNT,
            "bytes": LANE_BYTES,
            "lane_0_offset": LANE0_OFFSET,
            "lane_1_offset": LANE1_OFFSET,
        },
        "byte_coverage": "exact",
        "record_coverage": "exact",
        "field_coverage": "exact",
        "pair_id_roundtrip": "exact",
        "layout_sha256": LAYOUT_SHA256,
        "second_universe": False,
        "executes_math": False,
    }


_STATUS: dict | None = None


def status() -> dict:
    """Return the cached exhaustive coverage report."""
    global _STATUS
    if _STATUS is None:
        _STATUS = validate()
    return dict(_STATUS)


def document() -> dict:
    """Return the deterministic physical-profile document (also in spec/)."""
    report = status()
    return {
        "schema": SCHEMA,
        "profile": PROFILE,
        "status": report["status"],
        "universe": {
            "bytes": UNIVERSE_BYTES,
            "physical_profile": True,
            "one_universe": True,
        },
        "regions": report["regions"],
        "heads": {
            "count": HEAD_COUNT,
            "record_bytes": HEAD_RECORD_BYTES,
            "offset_rule": "head * 128",
            "nannet0_head": NANNET0_HEAD,
            "real_heads": {
                "first": REAL_HEAD_FIRST,
                "last": REAL_HEAD_LAST,
                "count": REAL_HEAD_COUNT,
            },
            "fields": [field.as_dict() for field in HEAD_FIELDS],
        },
        "pairs": {
            "count": PAIR_COUNT,
            "record_bytes": PAIR_RECORD_BYTES,
            "record_offset_rule": "32768 + (pair_id - 1) * 256",
            "id": {
                "void_sentinel": PAIR_ID_VOID,
                "first": PAIR_ID_MIN,
                "last": PAIR_ID_MAX,
                "formula": PAIR_ID_FORMULA,
                "order": "a < b",
            },
            "lanes": [
                {"lane": 0, "offset_bytes": LANE0_OFFSET, "size_bytes": LANE_BYTES},
                {"lane": 1, "offset_bytes": LANE1_OFFSET, "size_bytes": LANE_BYTES},
            ],
            "lane_0_fields": [field.as_dict() for field in PAIR_LANE0_FIELDS],
            "lane_1_fields": [field.as_dict() for field in PAIR_LANE1_FIELDS],
        },
        "views": {
            "physical": {
                "profile": PROFILE,
                "universe_bytes": UNIVERSE_BYTES,
                "heads": "contiguous at 0..32768",
                "pairs": "contiguous at 32768..8388608",
            },
            "route_view": {
                "spec": "spec/universe-map.json",
                "description": "255 real-head pages plus one NANNET0 page",
                "page_bytes": 32_768,
                "pages": 256,
                "same_universe": True,
                "second_universe": False,
                "second_allocation": False,
                "copy": False,
                "head_page_rule": (
                    "route page p (0..254) is physical head p+1; route page 255 "
                    "is physical head 0 (NANNET0)"
                ),
                "pair_rule": (
                    "route view scatters the same pair records into 128 two-word "
                    "slots per real-head page; the physical profile stores them "
                    "contiguously at 32768..8388608"
                ),
            },
        },
        "coverage": {
            "byte_coverage": report["byte_coverage"],
            "record_coverage": report["record_coverage"],
            "field_coverage": report["field_coverage"],
            "pair_id_roundtrip": report["pair_id_roundtrip"],
        },
        "layout_sha256": report["layout_sha256"],
        "non_claims": [
            "This is a physical byte-layout profile over the existing one 8 MiB universe.",
            "The spec/universe-map.json route view is a different virtual view, not a second universe or allocation.",
            "No residual slot is evaluated and no host numerical math library is used.",
            "No chart is read or written and no native MTH execution occurs here.",
            "A pair record is evidence of addressable structure, never a claim of mathematical truth.",
        ],
    }


def status_json() -> str:
    return canonical_json(status())


def document_json() -> str:
    return canonical_json(document())


# Readable aliases used by neighbouring router modules.
decode_pair = decode_pair_id
head_record_offset = head_offset
pair_record_offset = pair_offset
describe_head = head_descriptor
describe_pair = pair_descriptor
layout_document = document
status_document = document


__all__ = [
    "F32_BYTES",
    "FIELD_ENCODING_BYTES",
    "FIELD_ENCODING_F32",
    "FIELD_ENCODING_U32",
    "HEAD_COUNT",
    "HEAD_FIELDS",
    "HEAD_RECORD_BYTES",
    "HEAD_REGION",
    "HEAD_REGION_BYTES",
    "HEAD_REGION_OFFSET",
    "LANE0_OFFSET",
    "LANE1_OFFSET",
    "LANE_BYTES",
    "LANE_COUNT",
    "LAYOUT_SHA256",
    "MirrorMemoryError",
    "NANNET0_HEAD",
    "NANNET0_KIND",
    "PAIR_COUNT",
    "PAIR_FIELDS",
    "PAIR_ID_FORMULA",
    "PAIR_ID_MAX",
    "PAIR_ID_MIN",
    "PAIR_ID_VOID",
    "PAIR_LANE0_FIELDS",
    "PAIR_LANE1_FIELDS",
    "PAIR_RECORD_BYTES",
    "PAIR_REGION",
    "PAIR_REGION_BYTES",
    "PAIR_REGION_OFFSET",
    "PROFILE",
    "REAL_HEAD_COUNT",
    "REAL_HEAD_FIRST",
    "REAL_HEAD_KIND",
    "REAL_HEAD_LAST",
    "REGIONS",
    "RESIDUAL_BYTES",
    "RESIDUAL_SLOTS",
    "RESIDUAL_SLOT_BYTES",
    "SCHEMA",
    "UNIVERSE_BYTES",
    "U32_BYTES",
    "FieldDescriptor",
    "HeadDescriptor",
    "LaneDescriptor",
    "PairDescriptor",
    "RegionDescriptor",
    "canonical_json",
    "decode_pair",
    "decode_pair_id",
    "describe_head",
    "describe_pair",
    "document",
    "document_json",
    "field_descriptor",
    "field_descriptors",
    "field_offset",
    "head_descriptor",
    "head_descriptors",
    "head_field_descriptor",
    "head_field_offset",
    "head_offset",
    "head_record_offset",
    "is_void_pair_id",
    "lane_descriptor",
    "lane_descriptors",
    "lane_offset",
    "layout_document",
    "pair_descriptor",
    "pair_field_offset",
    "pair_heads",
    "pair_id",
    "pair_offset",
    "pair_record_offset",
    "status",
    "status_document",
    "status_json",
    "validate",
]
