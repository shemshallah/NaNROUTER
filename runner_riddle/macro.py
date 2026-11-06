"""Logic-first Bootstrap macro planner with allocator-bound range grants."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
from typing import Any

RESERVED_BSR_HEADS = frozenset({0, 4, 5, 6, 7, 8})
BOOLEAN_HEADS = tuple(i for i in range(256) if i not in RESERVED_BSR_HEADS)
MAPPING_LAYERS = (
    "bit-to-head", "address-to-head", "head-to-bin", "vector-to-bin",
    "hyperedge", "temporal-link", "logic-rule", "route",
    "merge-provenance", "meta-policy",
)


class PolicyError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


@dataclass(frozen=True)
class AddressRange:
    bin_name: str
    start: int
    end_exclusive: int
    permissions: tuple[str, ...]

    def contains(self, address: int) -> bool:
        return self.start <= address < self.end_exclusive


class SignedRangeManifest:
    """Exact allocator-issued ranges; no offsets are inferred or defaulted."""

    def __init__(self, document: dict[str, Any], key: bytes):
        self.document = document
        self.key = key
        self.ranges: tuple[AddressRange, ...] = ()
        self.verify()

    def verify(self) -> None:
        doc = self.document
        signature = str(doc.get("signature", ""))
        core = {k: v for k, v in doc.items() if k != "signature"}
        expected = hmac.new(self.key, _canonical(core), hashlib.sha256).hexdigest()
        if not signature or not hmac.compare_digest(signature, expected):
            raise PolicyError("allocator range manifest signature mismatch")
        if doc.get("schema") != "nanrouter.range-manifest.v1":
            raise PolicyError("unsupported range manifest schema")
        if doc.get("authority") != "nanlmind-canonical-allocator":
            raise PolicyError("range manifest is not from canonical allocator")
        if doc.get("verified") is not True:
            raise PolicyError("allocator manifest has not passed verification")
        limit = int(doc.get("address_limit_bytes", 0))
        if limit < 1 or limit > 2_147_483_648:
            raise PolicyError("address limit must be within 2 GiB")
        ranges = []
        for item in doc.get("ranges", []):
            start, end = int(item["start"]), int(item["end_exclusive"])
            if start < 0 or end <= start or end > limit:
                raise PolicyError("range is empty or exceeds allocator address limit")
            if not item.get("bin_name") or not item.get("permissions"):
                raise PolicyError("each range needs a bin and explicit permissions")
            ranges.append(AddressRange(
                str(item["bin_name"]), start, end, tuple(sorted(set(item["permissions"])))
            ))
        ordered = sorted(ranges, key=lambda r: (r.start, r.end_exclusive))
        for left, right in zip(ordered, ordered[1:]):
            if right.start < left.end_exclusive:
                raise PolicyError("allocator ranges overlap")
        if not ordered:
            raise PolicyError("empty range manifest is deny-all, not a training grant")
        self.ranges = tuple(ordered)

    def grant(self, bin_name: str, permission: str) -> tuple[AddressRange, ...]:
        return tuple(r for r in self.ranges
                     if r.bin_name == bin_name and permission in r.permissions)


@dataclass(frozen=True)
class CurriculumState:
    boolean_gate_passed: bool = False
    boolean_heads_verified: int = 0
    distinct_boolean_rules: int = 0
    routing_gate_passed: bool = False
    permanent_heads_mapped: int = 0
    mapped_layers: tuple[int, ...] = ()
    base_generation: int = 0


@dataclass(frozen=True)
class MacroJob:
    stage: str
    universe_id: str
    macrocluster: str
    learner_heads: tuple[int, ...]
    mapping_layers: tuple[int, ...]
    source_ranges: tuple[AddressRange, ...]
    base_generation: int
    writes_live_map: bool = False


class BootstrapMacroPlanner:
    """Plans bounded work; it does not directly mutate the master route cache."""

    def __init__(self, universe_id: str = "overbootstrap-mc0"):
        self.universe_id = universe_id

    def next_job(self, state: CurriculumState,
                 manifest: SignedRangeManifest) -> MacroJob:
        training_ranges = manifest.grant("BOOTSTRAP_BOOLEAN_TRAINING_BIN",
                                         "bootstrap.boolean.read")
        if not training_ranges:
            raise PolicyError("no allocator-approved Boolean training range")
        if not state.boolean_gate_passed:
            if state.boolean_heads_verified >= 250 and state.distinct_boolean_rules == 16:
                raise PolicyError("Boolean state is complete but its gate is not marked passed")
            return MacroJob(
                "LEARN_BOOLEAN", self.universe_id, "MC0:0", BOOLEAN_HEADS,
                (0,), training_ranges, state.base_generation, False
            )
        if not state.routing_gate_passed:
            route_ranges = manifest.grant("NANNET_ROUTE_BIN", "nannet.route.read")
            if not route_ranges:
                raise PolicyError("no allocator-approved NANNET route read range")
            return MacroJob(
                "LEARN_ROUTING", self.universe_id, "MC0:0", BOOLEAN_HEADS,
                tuple(range(10)), route_ranges, state.base_generation, False
            )
        # Language is deliberately deferred until the logic and mapping gates pass.
        language_ranges = manifest.grant("BOOTSTRAP_BOOLEAN_TRAINING_BIN",
                                         "bootstrap.language.demo")
        if not language_ranges:
            raise PolicyError("language demo range is not authorized")
        return MacroJob(
            "LANGUAGE_DEMO", self.universe_id, "MC0:0", BOOLEAN_HEADS,
            tuple(range(10)), language_ranges, state.base_generation, False
        )

    @staticmethod
    def feedback(job: MacroJob, *, completed_steps: int,
                 candidate_digest: str, acl_digest: str) -> dict[str, Any]:
        if completed_steps < 0 or len(candidate_digest) != 64 or len(acl_digest) != 64:
            raise PolicyError("invalid feedback provenance")
        return {
            "schema": "nanrouter.bootstrap-feedback.v1",
            "universe_id": job.universe_id,
            "macrocluster": job.macrocluster,
            "stage": job.stage,
            "completed_steps": completed_steps,
            "base_generation": job.base_generation,
            "candidate_digest": candidate_digest,
            "acl_digest": acl_digest,
            "live_map_commit": False,
        }
