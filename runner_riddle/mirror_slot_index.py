"""Round 037 triangle-slot index over the canonical mirror memory.

Round 037 stored evidence in 32,385 reference slots (head 0, pairs 1..255).
This module is pure integer address mapping: slot -> (a,b) -> canonical pair
record.  It performs no arithmetic on stored evidence and no learning.
"""
from __future__ import annotations

from dataclasses import dataclass

from .mirror_memory import (
    NANNET0_HEAD,
    PAIR_RECORD_BYTES,
    PAIR_REGION_OFFSET,
    pair_id,
)

SCHEMA = "nanrouter.mirror-slot-index.v1"
SLOT_COUNT = 32_385
FIRST_HEAD = 1
LAST_HEAD = 255
MAX_HEAD = 255


class MirrorSlotError(ValueError):
    """A slot or head pair is outside the reference-slot index."""


def _slot(value: int) -> int:
    if type(value) is not int or not 0 <= value < SLOT_COUNT:
        raise MirrorSlotError("slot must be an integer 0..32384")
    return value


def _heads(a: int, b: int) -> tuple[int, int]:
    if type(a) is not int or type(b) is not int:
        raise MirrorSlotError("heads must be integers")
    if not (FIRST_HEAD <= a < b <= LAST_HEAD):
        raise MirrorSlotError("expected 1 <= a < b <= 255")
    return a, b


def pair_for_slot(slot: int) -> tuple[int, int]:
    """Return the (a,b) pair for one lexical reference slot."""
    remaining = _slot(slot)
    a = FIRST_HEAD
    while True:
        width = LAST_HEAD - a
        if remaining < width:
            return a, a + 1 + remaining
        remaining -= width
        a += 1
        if a >= LAST_HEAD:
            raise MirrorSlotError("slot index exhausted")


@dataclass(frozen=True)
class SlotDescriptor:
    slot: int
    a: int
    b: int
    pair_id: int
    record_offset: int

    def as_dict(self) -> dict:
        return {
            "slot": self.slot,
            "a": self.a,
            "b": self.b,
            "pair_id": self.pair_id,
            "record_offset": self.record_offset,
            "record_bytes": PAIR_RECORD_BYTES,
        }


def slot_descriptor(slot: int) -> SlotDescriptor:
    a, b = pair_for_slot(slot)
    canonical = pair_id(a, b)
    return SlotDescriptor(
        slot=_slot(slot),
        a=a,
        b=b,
        pair_id=canonical,
        record_offset=PAIR_REGION_OFFSET + (canonical - 1) * PAIR_RECORD_BYTES,
    )


def slot_for_pair(a: int, b: int) -> int:
    """Inverse mapping: lexical (a,b) with 1 <= a < b <= 255 -> slot."""
    a, b = _heads(a, b)
    before = sum(LAST_HEAD - first for first in range(FIRST_HEAD, a))
    return before + (b - a - 1)


def validate() -> dict:
    seen: set[tuple[int, int]] = set()
    max_offset = -1
    previous_pair_id = 0
    for slot in range(SLOT_COUNT):
        record = slot_descriptor(slot)
        if record.pair_id <= previous_pair_id:
            raise MirrorSlotError("pair ids are not increasing")
        previous_pair_id = record.pair_id
        if record.a < FIRST_HEAD or record.b > LAST_HEAD or record.a >= record.b:
            raise MirrorSlotError("slot head pair is invalid")
        if (record.a, record.b) in seen:
            raise MirrorSlotError("duplicate slot pair")
        seen.add((record.a, record.b))
        if slot_for_pair(record.a, record.b) != slot:
            raise MirrorSlotError("slot inverse mapping mismatch")
        if record.record_offset < PAIR_REGION_OFFSET:
            raise MirrorSlotError("slot record precedes the pair region")
        max_offset = max(max_offset, record.record_offset)
    return {
        "schema": SCHEMA,
        "status": "green",
        "slots": SLOT_COUNT,
        "heads": LAST_HEAD,
        "reference_head": NANNET0_HEAD,
        "first_pair": pair_for_slot(0),
        "last_pair": pair_for_slot(SLOT_COUNT - 1),
        "last_pair_id": previous_pair_id,
        "max_record_offset": max_offset,
        "coverage": 1.0,
        "pair_region_offset": PAIR_REGION_OFFSET,
        "record_bytes": PAIR_RECORD_BYTES,
    }


__all__ = [
    "FIRST_HEAD",
    "LAST_HEAD",
    "MirrorSlotError",
    "SCHEMA",
    "SLOT_COUNT",
    "SlotDescriptor",
    "pair_for_slot",
    "slot_descriptor",
    "slot_for_pair",
    "validate",
]
