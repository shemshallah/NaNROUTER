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


def verify_feedback_signature(feedback: dict[str, Any], key: bytes) -> bool:
    signature = str(feedback.get("signature", ""))
    core = {name: value for name, value in feedback.items() if name != "signature"}
    expected = hmac.new(
        key, json.dumps(core, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


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
        if doc.get("platform") == "android" and limit > 8_388_608:
            raise PolicyError("Android mapping limit is 8 MiB")
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
    input_ranges: tuple[AddressRange, ...]
    candidate_ranges: tuple[AddressRange, ...]
    base_generation: int
    writes_live_map: bool = False


class BootstrapMacroPlanner:
    """Plans bounded work; it does not directly mutate the master route cache."""

    def __init__(self, universe_id: str = "overbootstrap-mc0"):
        self.universe_id = universe_id

    def next_job(self, state: CurriculumState,
                 manifest: SignedRangeManifest) -> MacroJob:
        if state.boolean_gate_passed and (
            state.boolean_heads_verified != 250 or state.distinct_boolean_rules != 16
        ):
            raise PolicyError("Boolean promotion requires all 250 heads and all 16 rules")
        if state.routing_gate_passed and (
            set(state.mapped_layers) != set(range(10)) or state.permanent_heads_mapped < 1
        ):
            raise PolicyError("routing promotion requires all ten layers and permanent-head evidence")
        training_ranges = manifest.grant("BOOTSTRAP_BOOLEAN_TRAINING_BIN",
                                         "bootstrap.boolean.read")
        training_candidates = manifest.grant("BOOTSTRAP_BOOLEAN_TRAINING_BIN",
                                              "bootstrap.boolean.candidate-write")
        if not training_ranges or not training_candidates:
            raise PolicyError("Boolean training input and candidate ranges are both required")
        if not state.boolean_gate_passed:
            if state.boolean_heads_verified >= 250 and state.distinct_boolean_rules == 16:
                raise PolicyError("Boolean state is complete but its gate is not marked passed")
            return MacroJob(
                "LEARN_BOOLEAN", self.universe_id, "MC0:0", BOOLEAN_HEADS,
                (0,), training_ranges, training_candidates, state.base_generation, False
            )
        if not state.routing_gate_passed:
            route_ranges = manifest.grant("NANNET_ROUTE_BIN", "nannet.route.read")
            route_candidates = manifest.grant("NANNET_ROUTE_BIN", "nannet.route.candidate-write")
            if not route_ranges or not route_candidates:
                raise PolicyError("NANNET route input and candidate ranges are both required")
            return MacroJob(
                "LEARN_ROUTING", self.universe_id, "MC0:0", BOOLEAN_HEADS,
                tuple(range(10)), route_ranges, route_candidates, state.base_generation, False
            )
        # Language is deliberately deferred until the logic and mapping gates pass.
        language_ranges = manifest.grant("BOOTSTRAP_LANGUAGE_DEMO_BIN",
                                         "bootstrap.language.read")
        language_candidates = manifest.grant("BOOTSTRAP_LANGUAGE_DEMO_BIN",
                                             "bootstrap.language.candidate-write")
        if not language_ranges or not language_candidates:
            raise PolicyError("language demo remains disabled until its own bin is authorized")
        return MacroJob(
            "LANGUAGE_DEMO", self.universe_id, "MC0:0", BOOLEAN_HEADS,
            tuple(range(10)), language_ranges, language_candidates, state.base_generation, False
        )

    @staticmethod
    def feedback_envelope(*, universe_id: str, stage: str, base_generation: int,
                          completed_steps: int, candidate_digest: str,
                          acl_digest: str) -> dict[str, Any]:
        if (not universe_id or stage not in ("LEARN_BOOLEAN", "LEARN_ROUTING", "LANGUAGE_DEMO")
                or base_generation < 0 or completed_steps < 0
                or len(candidate_digest) != 64 or len(acl_digest) != 64):
            raise PolicyError("invalid feedback provenance")
        return {
            "schema": "nanrouter.bootstrap-feedback.v1",
            "universe_id": universe_id,
            "macrocluster": "MC0:0",
            "stage": stage,
            "completed_steps": completed_steps,
            "base_generation": base_generation,
            "candidate_digest": candidate_digest,
            "acl_digest": acl_digest,
            "live_map_commit": False,
        }

    @staticmethod
    def feedback(job: MacroJob, *, completed_steps: int,
                 candidate_digest: str, acl_digest: str) -> dict[str, Any]:
        return BootstrapMacroPlanner.feedback_envelope(
            universe_id=job.universe_id, stage=job.stage,
            base_generation=job.base_generation, completed_steps=completed_steps,
            candidate_digest=candidate_digest, acl_digest=acl_digest,
        )
