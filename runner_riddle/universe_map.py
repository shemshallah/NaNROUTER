"""Full 8 MiB NaN16 universe map and NANNET relation-point routing.

The guest address space maps every canonical universe page, not a 2 MiB
sub-window.  The workspace budget remains a separate planning bound; it is not
the guest's addressable span.

Layout (one 8 MiB universe, 256 logical 32 KiB pages):

* pages 0..254  -> canonical real heads 1..255 (ring head index 0..254)
* page 255      -> canonical head 0, the single NANNET0 control point

Every canonical relation point is addressable:

* 256 fixed head points: head 0..255;
* 32,640 mirror-pair points: canonical cells 256..32,895.

Mirror-pair records use a 2-word slot in the last 256 words of each real-head
page.  There are 128 slots per page and 255 pages, exactly 32,640 records.
The map is control-plane address arithmetic only.  It executes no kernel and
does not claim that a relation is true, authorized, or native-verified.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Iterator

from .mirror_point_register import (
    CANONICAL_CELLS,
    FIXED_POINTS,
    PAIR_COUNT,
    MirrorRegister,
)

SCHEMA = "nanrouter.universe-map.v1"
PAGE_BYTES = 32 * 1024
WORD_BYTES = 8
PAGE_WORDS = PAGE_BYTES // WORD_BYTES
UNIVERSE_PAGES = 256
UNIVERSE_BYTES = UNIVERSE_PAGES * PAGE_BYTES
UNIVERSE_WORDS = UNIVERSE_BYTES // WORD_BYTES
REAL_HEADS = 255
NANNET0_HEAD = 0
NANNET0_PAGE = 255
NANNET0_RING_POSITION = 255
MP_SLOT_BASE_WORD = 3840
MP_SLOT_WORDS = 2
MP_SLOTS_PER_PAGE = 128
MP_SLOT_END_WORD = MP_SLOT_BASE_WORD + MP_SLOTS_PER_PAGE * MP_SLOT_WORDS
MAX_RELATION_GUEST_WORD = (REAL_HEADS - 1) * PAGE_WORDS + MP_SLOT_END_WORD - MP_SLOT_WORDS
ROUTE_ROOT = "nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0"
MAX_LAYER = 9

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_STATUS: dict | None = None


class UniverseMapError(ValueError):
    """A page, head, mirror pair, cell, or layer is outside the map."""


def _int(value: int, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise UniverseMapError(f"{name} must be an integer {minimum}..{maximum}")
    return value


def _digest(value: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise UniverseMapError("expected lowercase SHA-256")
    return value


@dataclass(frozen=True)
class PageDescriptor:
    page: int
    offset_bytes: int
    offset_words: int
    kind: str
    head: int
    ring_head_index: int | None
    route: str
    relation_slot_base_word: int | None
    relation_slots: int

    def as_dict(self) -> dict:
        return {
            "page": self.page,
            "offset_bytes": self.offset_bytes,
            "offset_words": self.offset_words,
            "kind": self.kind,
            "head": self.head,
            "ring_head_index": self.ring_head_index,
            "route": self.route,
            "relation_slot_base_word": self.relation_slot_base_word,
            "relation_slots": self.relation_slots,
        }


@dataclass(frozen=True)
class RelationPoint:
    canonical_cell: int
    kind: str
    ordinal: int
    page: int
    word: int
    guest_word: int
    offset_bytes: int
    route: str
    nannet0: bool

    def as_dict(self, *, layer: int | None = None) -> dict:
        value = {
            "canonical_cell": self.canonical_cell,
            "kind": self.kind,
            "ordinal": self.ordinal,
            "page": self.page,
            "word": self.word,
            "guest_word": self.guest_word,
            "offset_bytes": self.offset_bytes,
            "route": self.route,
            "nannet0": self.nannet0,
        }
        if layer is not None:
            value["layer"] = layer
            value["layer_route"] = self.route + f"::L{layer}"
        return value


def _page_for_real_head(head: int) -> int:
    """Canonical head 1..255 maps to page 0..254."""
    return head - 1


def _head_point(head: int) -> RelationPoint:
    head = _int(head, "head", 0, FIXED_POINTS - 1)
    if head == NANNET0_HEAD:
        page = NANNET0_PAGE
        route = f"{ROUTE_ROOT}::HW0:0"
        nannet0 = True
        ring_head_index = None
    else:
        page = _page_for_real_head(head)
        route = f"{ROUTE_ROOT}::HW0:{head}"
        nannet0 = False
        ring_head_index = page
    guest_word = page * PAGE_WORDS
    return RelationPoint(
        canonical_cell=head,
        kind="head",
        ordinal=head,
        page=page,
        word=0,
        guest_word=guest_word,
        offset_bytes=guest_word * WORD_BYTES,
        route=route,
        nannet0=nannet0,
    )


def _mp_point(mp: int) -> RelationPoint:
    mp = _int(mp, "mirror pair", 0, PAIR_COUNT - 1)
    slot, page = divmod(mp, REAL_HEADS)
    if page >= REAL_HEADS:
        raise UniverseMapError("mirror-pair page exceeds real-head pages")
    word = MP_SLOT_BASE_WORD + slot * MP_SLOT_WORDS
    guest_word = page * PAGE_WORDS + word
    return RelationPoint(
        canonical_cell=FIXED_POINTS + mp,
        kind="mp",
        ordinal=mp,
        page=page,
        word=word,
        guest_word=guest_word,
        offset_bytes=guest_word * WORD_BYTES,
        route=f"{ROUTE_ROOT}::HW0:MP{mp}",
        nannet0=False,
    )


def page(page_id: int) -> PageDescriptor:
    page_id = _int(page_id, "page", 0, UNIVERSE_PAGES - 1)
    offset_words = page_id * PAGE_WORDS
    if page_id == NANNET0_PAGE:
        head = NANNET0_HEAD
        kind = "nannet0"
        ring_head_index = None
        route = f"{ROUTE_ROOT}::HW0:0"
        slots = 0
        slot_base = None
    else:
        head = page_id + 1
        kind = "head"
        ring_head_index = page_id
        route = f"{ROUTE_ROOT}::HW0:{head}"
        slots = MP_SLOTS_PER_PAGE
        slot_base = MP_SLOT_BASE_WORD
    return PageDescriptor(
        page=page_id,
        offset_bytes=offset_words * WORD_BYTES,
        offset_words=offset_words,
        kind=kind,
        head=head,
        ring_head_index=ring_head_index,
        route=route,
        relation_slot_base_word=slot_base,
        relation_slots=slots,
    )


def point(canonical_cell: int) -> RelationPoint:
    canonical_cell = _int(
        canonical_cell, "canonical cell", 0, CANONICAL_CELLS - 1
    )
    if canonical_cell < FIXED_POINTS:
        return _head_point(canonical_cell)
    return _mp_point(canonical_cell - FIXED_POINTS)


def head(head_id: int) -> RelationPoint:
    return _head_point(head_id)


def mirror_pair(mp: int) -> RelationPoint:
    return _mp_point(mp)


def from_raw(raw_address: int) -> RelationPoint:
    """Resolve a 16-bit double-endian address through the mirror register."""
    raw_address = _int(raw_address, "raw address", 0, 65535)
    return point(MirrorRegister.from_raw(raw_address)["canonical_cell"])


def route(canonical_cell: int, layer: int | None = None) -> str:
    """Return the NANNET-addressable route for one relation point."""
    record = point(canonical_cell)
    if layer is None:
        return record.route
    layer = _int(layer, "layer", 0, MAX_LAYER)
    return record.route + f"::L{layer}"


def iter_points() -> Iterator[RelationPoint]:
    """Yield all 32,896 relation points in canonical-cell order."""
    for cell in range(CANONICAL_CELLS):
        yield point(cell)


def page_directory() -> tuple[PageDescriptor, ...]:
    return tuple(page(index) for index in range(UNIVERSE_PAGES))


def _directory_digest(directory: tuple[PageDescriptor, ...]) -> str:
    payload = {
        "schema": SCHEMA,
        "page_bytes": PAGE_BYTES,
        "word_bytes": WORD_BYTES,
        "universe_pages": UNIVERSE_PAGES,
        "universe_words": UNIVERSE_WORDS,
        "real_heads": REAL_HEADS,
        "nannet0_head": NANNET0_HEAD,
        "nannet0_page": NANNET0_PAGE,
        "nannet0_ring_position": NANNET0_RING_POSITION,
        "mp_slot_base_word": MP_SLOT_BASE_WORD,
        "mp_slot_words": MP_SLOT_WORDS,
        "mp_slots_per_page": MP_SLOTS_PER_PAGE,
        "pages": [item.as_dict() for item in directory],
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate() -> dict:
    """Exhaustively check page and point coverage; return a compact report."""
    directory = page_directory()
    pages = [item.page for item in directory]
    if pages != list(range(UNIVERSE_PAGES)):
        raise UniverseMapError("page directory is not contiguous")
    if directory[-1].offset_bytes + PAGE_BYTES != UNIVERSE_BYTES:
        raise UniverseMapError("page directory does not cover 8 MiB")
    if MP_SLOT_END_WORD > PAGE_WORDS:
        raise UniverseMapError("mirror-pair slots exceed the logical page")
    counts: dict[int, int] = {index: 0 for index in range(UNIVERSE_PAGES)}
    mp_page_counts: dict[int, int] = {index: 0 for index in range(REAL_HEADS)}
    seen: set[int] = set()
    max_guest_word = -1
    for record in iter_points():
        if record.canonical_cell in seen:
            raise UniverseMapError("duplicate canonical cell")
        seen.add(record.canonical_cell)
        if not 0 <= record.page < UNIVERSE_PAGES:
            raise UniverseMapError("point page is out of range")
        if not 0 <= record.word < PAGE_WORDS:
            raise UniverseMapError("point word is out of range")
        expected = record.page * PAGE_WORDS + record.word
        if record.guest_word != expected or record.offset_bytes != expected * WORD_BYTES:
            raise UniverseMapError("point address arithmetic mismatch")
        if record.guest_word >= UNIVERSE_WORDS:
            raise UniverseMapError("point exceeds the 8 MiB universe")
        counts[record.page] += 1
        max_guest_word = max(max_guest_word, record.guest_word)
        if record.kind == "mp":
            if record.page == NANNET0_PAGE:
                raise UniverseMapError("mirror pair mapped onto NANNET0 page")
            if not MP_SLOT_BASE_WORD <= record.word < MP_SLOT_END_WORD:
                raise UniverseMapError("mirror pair outside relation slots")
            mp_page_counts[record.page] += 1
        elif record.nannet0:
            if record.page != NANNET0_PAGE or record.canonical_cell != NANNET0_HEAD:
                raise UniverseMapError("NANNET0 alias is inconsistent")
    if len(seen) != CANONICAL_CELLS:
        raise UniverseMapError("relation point coverage is incomplete")
    if counts[NANNET0_PAGE] != 1:
        raise UniverseMapError("NANNET0 page must contain exactly the NANNET0 head")
    if any(count != MP_SLOTS_PER_PAGE for count in mp_page_counts.values()):
        raise UniverseMapError("every real-head page must map 128 mirror pairs")
    if max_guest_word != NANNET0_PAGE * PAGE_WORDS:
        raise UniverseMapError("NANNET0 head is not anchored at the final page")
    return {
        "schema": SCHEMA,
        "status": "green",
        "pages": UNIVERSE_PAGES,
        "universe_bytes": UNIVERSE_BYTES,
        "universe_words": UNIVERSE_WORDS,
        "relation_points": CANONICAL_CELLS,
        "fixed_heads": FIXED_POINTS,
        "mirror_pairs": PAIR_COUNT,
        "nannet0_head": NANNET0_HEAD,
        "nannet0_page": NANNET0_PAGE,
        "nannet0_ring_position": NANNET0_RING_POSITION,
        "nannet0_aliases": ["HW0:0", "page:255", "ring:255"],
        "real_heads": REAL_HEADS,
        "mp_slots_per_page": MP_SLOTS_PER_PAGE,
        "mp_slot_base_word": MP_SLOT_BASE_WORD,
        "mp_slot_words": MP_SLOT_WORDS,
        "coverage": 1.0,
        "max_guest_word": max_guest_word,
        "page_directory_sha256": _directory_digest(page_directory()),
        "native_required": True,
        "executes_math": False,
        "claims_relations_true": False,
    }


def status() -> dict:
    global _STATUS
    if _STATUS is None:
        _STATUS = validate()
    return dict(_STATUS)


def page_directory_document() -> dict:
    directory = page_directory()
    report = validate()
    return {
        "schema": SCHEMA,
        "pages": [item.as_dict() for item in directory],
        "relation_points": {
            "count": CANONICAL_CELLS,
            "fixed_heads": FIXED_POINTS,
            "mirror_pairs": PAIR_COUNT,
            "mapping": {
                "head_0": "NANNET0 page 255, word 0",
                "head_1_255": "page head-1, word 0",
                "mirror_pair_n": "page n % 255, word 3840 + 2*(n // 255)",
            },
        },
        "page_directory_sha256": report["page_directory_sha256"],
        "nannet0_aliases": report["nannet0_aliases"],
    }


__all__ = [
    "CANONICAL_CELLS",
    "FIXED_POINTS",
    "MAX_LAYER",
    "MAX_RELATION_GUEST_WORD",
    "MP_SLOTS_PER_PAGE",
    "MP_SLOT_BASE_WORD",
    "MP_SLOT_END_WORD",
    "MP_SLOT_WORDS",
    "NANNET0_HEAD",
    "NANNET0_PAGE",
    "NANNET0_RING_POSITION",
    "PAIR_COUNT",
    "PAGE_BYTES",
    "PAGE_WORDS",
    "PageDescriptor",
    "REAL_HEADS",
    "ROUTE_ROOT",
    "RelationPoint",
    "SCHEMA",
    "UNIVERSE_BYTES",
    "UNIVERSE_PAGES",
    "UNIVERSE_WORDS",
    "UniverseMapError",
    "WORD_BYTES",
    "from_raw",
    "head",
    "iter_points",
    "mirror_pair",
    "page",
    "page_directory",
    "page_directory_document",
    "point",
    "route",
    "status",
    "validate",
]
