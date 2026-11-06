"""Read-only trace aggregation; learned patterns are proposals, never routes."""
from __future__ import annotations
from collections import Counter
from dataclasses import dataclass

@dataclass(frozen=True)
class PatternCandidate:
    source_ref: str
    target_ref: str
    observations: int
    successes: int
    confidence_q16: int


class TracePatternMiner:
    def __init__(self) -> None:
        self._counts: Counter[tuple[str, str]] = Counter()
        self._success: Counter[tuple[str, str]] = Counter()

    def observe(self, trace: dict) -> None:
        if trace.get("schema") != "nanrouter.trace.v1":
            raise ValueError("unsupported trace schema")
        if not trace.get("acl_digest") or not trace.get("source_hash"):
            raise ValueError("trace provenance and ACL digest required")
        source = str(trace.get("source_ref", ""))
        target = str(trace.get("target_ref", ""))
        if not source or not target:
            raise ValueError("trace source_ref and target_ref required")
        key = (source, target)
        self._counts[key] += 1
        if trace.get("correct") is True:
            self._success[key] += 1

    def candidates(self, minimum_observations: int = 8) -> list[PatternCandidate]:
        if minimum_observations < 1:
            raise ValueError("minimum_observations must be positive")
        found = []
        for key, count in self._counts.items():
            if count < minimum_observations:
                continue
            success = self._success[key]
            found.append(PatternCandidate(
                key[0], key[1], count, success,
                min(65535, (success * 65535) // count)
            ))
        return sorted(found, key=lambda item: (-item.observations, item.source_ref, item.target_ref))
