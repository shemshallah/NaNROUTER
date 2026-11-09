"""Host-only exact and pair-posting retrieval over mirror-memory facts.

Round 032 showed that a conventional hash index is faster than the mirror-pair
posting list for this microbenchmark.  This adapter therefore keeps both
indexes explicit and separate: exact dictionary lookup for identity, and
concept-anchored pair postings for the mirror-memory seam.

It is control/data plumbing only.  It performs integer address hashing and
dictionary/list traversal, never numerical learning, native execution, or a
canonical merge.  The production MTH path remains NaN16-native.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib
from typing import Iterable

from .mirror_memory import pair_id

SCHEMA = "nanrouter.mirror-retrieval-index.v1"
GOLDEN = 0x9E3779B97F4A7C15
MASK64 = (1 << 64) - 1
MAX_FACTS = 1_000_000


class MirrorRetrievalError(ValueError):
    """A fact, concept, relation, or query is outside the index contract."""


def _u32(value: int, name: str) -> int:
    if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
        raise MirrorRetrievalError(f"{name} must be a u32")
    return value


def mix64(value: int) -> int:
    """SplitMix64 finalizer, used only for deterministic address routing."""
    value &= MASK64
    value ^= value >> 30
    value = (value * 0xBF58476D1CE4E5B9) & MASK64
    value ^= value >> 27
    value = (value * 0x94D049BB133111EB) & MASK64
    return (value ^ (value >> 31)) & MASK64


def anchor(concept_id: int) -> tuple[int, int, int]:
    """Return canonical (a, b, pair_id) for one concept id."""
    concept_id = _u32(concept_id, "concept_id")
    mixed = mix64(concept_id + GOLDEN)
    a = 1 + mixed % 255
    b = 1 + ((mixed >> 15) % 255)
    if a == b:
        b = b % 255 + 1
    if a > b:
        a, b = b, a
    if not (1 <= a < b <= 255):
        raise MirrorRetrievalError("anchor produced an invalid head pair")
    return a, b, pair_id(a, b)


@dataclass(frozen=True)
class Fact:
    fact_id: int
    source: int
    relation: int
    destination: int
    anchor_pair: int
    strength: float
    next: int

    def as_dict(self) -> dict:
        return {
            "fact_id": self.fact_id,
            "source": self.source,
            "relation": self.relation,
            "destination": self.destination,
            "anchor_pair": self.anchor_pair,
            "strength": self.strength,
            "next": self.next,
        }


class MirrorRetrievalIndex:
    """One append-only fact arena with exact and pair-posting indexes."""

    def __init__(self) -> None:
        self._facts: list[Fact | None] = [None]
        self._first: dict[int, int] = {}
        self._exact: dict[tuple[int, int], int] = {}
        self._edges: dict[int, list[int]] = defaultdict(list)

    def __len__(self) -> int:
        return len(self._facts) - 1

    def add_fact(
        self,
        source: int,
        relation: int,
        destination: int,
        *,
        strength: float = 1.0,
    ) -> Fact:
        source = _u32(source, "source")
        relation = _u32(relation, "relation")
        destination = _u32(destination, "destination")
        if type(strength) not in (int, float) or not 0.0 <= float(strength) <= 1.0:
            raise MirrorRetrievalError("strength must be in [0,1]")
        if len(self) >= MAX_FACTS:
            raise MirrorRetrievalError("fact arena capacity exceeded")
        a, b, anchor_pair = anchor(source)
        fact_id = len(self._facts)
        head = self._first.get(anchor_pair, 0)
        fact = Fact(
            fact_id=fact_id,
            source=source,
            relation=relation,
            destination=destination,
            anchor_pair=anchor_pair,
            strength=float(strength),
            next=head,
        )
        self._facts.append(fact)
        self._first[anchor_pair] = fact_id
        self._exact.setdefault((source, relation), fact_id)
        self._edges[source].append(fact_id)
        return fact

    def get(self, fact_id: int) -> Fact:
        if type(fact_id) is not int or not 1 <= fact_id < len(self._facts):
            raise MirrorRetrievalError("unknown fact id")
        fact = self._facts[fact_id]
        assert fact is not None
        return fact

    def exact(self, source: int, relation: int) -> Fact | None:
        source = _u32(source, "source")
        relation = _u32(relation, "relation")
        fact_id = self._exact.get((source, relation))
        return None if fact_id is None else self.get(fact_id)

    def posting(self, source: int, relation: int) -> Fact | None:
        """Resolve through the anchored pair posting list and verify collision."""
        source = _u32(source, "source")
        relation = _u32(relation, "relation")
        _, _, anchor_pair = anchor(source)
        fact_id = self._first.get(anchor_pair, 0)
        while fact_id:
            fact = self.get(fact_id)
            if fact.source == source and fact.relation == relation:
                return fact
            fact_id = fact.next
        return None

    def two_hop(self, start: int, goal: int, relation: int) -> bool:
        start = _u32(start, "start")
        goal = _u32(goal, "goal")
        relation = _u32(relation, "relation")
        for first_id in self._edges.get(start, ()):
            first = self.get(first_id)
            if first.relation != relation:
                continue
            for second_id in self._edges.get(first.destination, ()):
                second = self.get(second_id)
                if second.relation == relation and second.destination == goal:
                    return True
        return False

    def facts_for_source(self, source: int, *, limit: int = 64) -> list[Fact]:
        source = _u32(source, "source")
        if type(limit) is not int or not 1 <= limit <= 64:
            raise MirrorRetrievalError("limit must be 1..64")
        return [self.get(fact_id) for fact_id in self._edges.get(source, ())[:limit]]

    def status(self) -> dict:
        return {
            "schema": SCHEMA,
            "facts": len(self),
            "sources": len(self._edges),
            "anchor_pairs": len(self._first),
            "exact_index_entries": len(self._exact),
            "max_facts": MAX_FACTS,
            "uses_dense_matrix": False,
            "executes_native": False,
            "trains_model": False,
            "canonical_merge": False,
            "source_archive_sha256": (
                "19572e59a5038200b38f7e7ad063b2850458236de18ab58d83871ae46ccb11be"
            ),
        }

    def digest(self) -> str:
        payload = [
            self.get(index).as_dict() for index in range(1, len(self._facts))
        ]
        return hashlib.sha256(
            repr(payload).encode("utf-8")
        ).hexdigest()


__all__ = [
    "Fact",
    "GOLDEN",
    "MAX_FACTS",
    "MASK64",
    "MirrorRetrievalError",
    "MirrorRetrievalIndex",
    "SCHEMA",
    "anchor",
    "mix64",
]
