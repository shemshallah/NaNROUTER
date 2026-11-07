"""255 logical lane registry for the ``GAME_PLAN_::`` execution ring.

A lane is a durable logical work identity, not a runner.  The registry maps
lane IDs ``0..254`` to one 32 KiB home page each, groups them into 17 passes of
15 lanes, and declares the generic role/capability/numerical policy for every
lane.  ``NANNET0`` is the ring port at position 255 and is deliberately not a
lane.

This module is a control-plane contract only.  It performs no mathematical
execution, allocates no pages, imports no native/runtime facade, and keeps no
job or lease ledger.  Lane state is a projection of the one active execution
slot: ``concurrency`` is always 1, never 255 simultaneous runners.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

SCHEMA = "nanrouter.lane-ruleset.v1"
RULE_SCHEMA = SCHEMA
LANE_SCHEMA = "nanrouter.lane-record.v1"
GROUP_SCHEMA = "nanrouter.lane-group.v1"
AUTHORITY_SCHEMA = "nanrouter.lane-authority.v1"
HEALTH_SCHEMA = "nanrouter.lane-registry-health.v1"
PAGE_BUDGET_SCHEMA = "nanrouter.lane-page-budget.v1"

RULESET_ID = "nanrouter.lane.rules.v1"
RULESET_VERSION = 1
LANE_VERSION = 1

LANE_COUNT = 255
GROUP_COUNT = 17
LANES_PER_GROUP = 15
PASS_COUNT = GROUP_COUNT
RING_POSITIONS = LANE_COUNT + 1
NANNET0_RING_POSITION = 255
NANNET0_PAGE_KEY = "page:255"

PAGE_BYTES = 32 * 1024
HOME_PAGES_PER_LANE = 1
LANE_HOME_PAGES = LANE_COUNT * HOME_PAGES_PER_LANE
LANE_HOME_BYTES = LANE_HOME_PAGES * PAGE_BYTES
UNIVERSE_PAGES = 256
UNIVERSE_BYTES = UNIVERSE_PAGES * PAGE_BYTES
NANNET0_PAGES = 1
NANNET0_BYTES = NANNET0_PAGES * PAGE_BYTES

CONCURRENCY = 1
ACTIVE_RUNNER_SLOTS = 1
EXECUTING_LANE_RUNS = 1
STANDBY_SLOTS_WITH_LIVE_WORKING_SETS = 0
NATIVE_KERNEL_INVOCATIONS_IN_FLIGHT = 1

_LANE_KEY_RE = re.compile(r"^lane:(\d{1,3})$")
_PAGE_KEY_RE = re.compile(r"^page:(\d{1,3})$")
_GROUP_KEY_RE = re.compile(r"^group:(\d{1,2})$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_CAPABILITY_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_ROLE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class LaneRegistryError(ValueError):
    """Base class for lane ruleset, identity, and policy failures."""


class LaneBoundsError(LaneRegistryError):
    """A lane/group/page reference is outside the declared bounds."""


class Nannet0LaneError(LaneBoundsError):
    """NANNET0 (ring position/page 255) was used as a logical lane."""


class LaneRoleError(LaneRegistryError):
    """A role declaration or role mask is invalid."""


class LaneDuplicateError(LaneRegistryError):
    """A lane, page, group, or global role was declared more than once."""


class LanePolicyError(LaneRegistryError):
    """A capability, FP, fan-out, or page-budget policy is invalid."""


class Digest(str):
    """A hex digest that also supports the legacy ``record.digest()`` spelling."""

    def __call__(self) -> str:
        return str(self)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def canonical_json(value: Any) -> str:
    """Canonical JSON used for immutable lane/ruleset identities."""

    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise LaneRegistryError("value is not canonical JSON") from exc


def digest_object(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def digest_document(document: Mapping[str, Any]) -> str:
    """Digest a document with its top-level ``digest`` field removed."""

    if not isinstance(document, Mapping):
        raise LaneRegistryError("document must be a mapping")
    payload = {key: value for key, value in document.items() if key != "digest"}
    return digest_object(payload)


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_plain(item) for item in value]
    return value


def _require_text(value: Any, name: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise LaneRegistryError(f"{name} must be a non-empty string <= {maximum}")
    return value


def _require_int(value: Any, name: str, *, minimum: int = 0,
                 maximum: int | None = None,
                 error_cls: type[LaneRegistryError] = LaneRegistryError) -> int:
    if not _is_int(value) or value < minimum or (maximum is not None and value > maximum):
        bound = f" between {minimum} and {maximum}" if maximum is not None else f" >= {minimum}"
        raise error_cls(f"{name} must be an integer{bound}")
    return value


def lane_key(lane_id: int) -> str:
    _require_int(lane_id, "lane_id", minimum=0, maximum=LANE_COUNT - 1,
                 error_cls=LaneBoundsError)
    return f"lane:{lane_id:03d}"


def page_key(page_id: int) -> str:
    _require_int(page_id, "page_id", minimum=0, maximum=RING_POSITIONS - 1,
                 error_cls=LaneBoundsError)
    return f"page:{page_id:03d}"


def group_key(group_id: int) -> str:
    _require_int(group_id, "group_id", minimum=0, maximum=GROUP_COUNT - 1,
                 error_cls=LaneBoundsError)
    return f"group:{group_id:02d}"


# The proposed logical-head ranges from GAME_PLAN_:: section 11.3.  The six
# former scheduling lanes and the supervisory lane remain generic execution
# work identities; scheduling and supervision are declared once as global
# authorities below rather than duplicated per lane.
LANE_ROLE_RANGES: tuple[tuple[str, int, int], ...] = (
    ("address_resolution", 0, 15),
    ("classification", 16, 31),
    ("function_lookup", 32, 63),
    ("preflight", 64, 95),
    ("execution", 96, 159),
    ("hypergraph", 160, 191),
    ("hashing", 192, 207),
    ("learning", 208, 223),
    ("memory", 224, 239),
    ("pruning", 240, 247),
    ("execution", 248, 254),
)

_ROLE_METADATA: tuple[tuple[str, str, int, bool, bool, str, int, str], ...] = (
    ("address_resolution", "lane", 0, False, True, "address.resolve", 15, "none"),
    ("classification", "lane", 1, False, False, "type.classify", 15, "none"),
    ("function_lookup", "lane", 2, False, False, "function.lookup", 15, "none"),
    ("preflight", "lane", 3, False, True, "constraint.preflight", 15, "none"),
    ("execution", "lane", 4, False, False, "math.execute", 8, "binary32-rne"),
    ("hypergraph", "lane", 5, False, False, "relation.hypergraph", 15, "integer-exact"),
    ("hashing", "lane", 6, False, True, "provenance.hash", 15, "none"),
    ("learning", "lane", 7, False, False, "rule.propose", 8, "binary32-rne"),
    ("memory", "lane", 8, False, False, "page.index", 15, "none"),
    ("pruning", "lane", 9, False, True, "resource.prune", 8, "integer-exact"),
    ("scheduling", "global", 10, True, True, "ring.schedule", 1, "none"),
    ("supervisor", "global", 11, True, True, "ring.supervise", 1, "none"),
)

LANE_ROLES: tuple[str, ...] = tuple(row[0] for row in _ROLE_METADATA if row[1] == "lane")
GLOBAL_ROLES: tuple[str, ...] = tuple(row[0] for row in _ROLE_METADATA if row[1] == "global")
ROLES: tuple[str, ...] = LANE_ROLES + GLOBAL_ROLES

ROLE_BITS = MappingProxyType({row[0]: 1 << row[2] for row in _ROLE_METADATA})
LANE_ROLE_MASK = sum(ROLE_BITS[role] for role in LANE_ROLES)
GLOBAL_ROLE_MASK = sum(ROLE_BITS[role] for role in GLOBAL_ROLES)
ALL_ROLE_MASK = LANE_ROLE_MASK | GLOBAL_ROLE_MASK

ROLE_SCOPES = MappingProxyType({row[0]: row[1] for row in _ROLE_METADATA})
ROLE_AUTHORITIES = MappingProxyType({row[0]: row[3] for row in _ROLE_METADATA})
ROLE_CRITICAL = MappingProxyType({row[0]: row[4] for row in _ROLE_METADATA})
ROLE_CAPABILITY_CLASS = MappingProxyType({row[0]: row[5] for row in _ROLE_METADATA})
ROLE_MAX_FANOUT = MappingProxyType({row[0]: row[6] for row in _ROLE_METADATA})
ROLE_FP_POLICY = MappingProxyType({row[0]: row[7] for row in _ROLE_METADATA})

CRITICAL_ROLES = frozenset(role for role, critical in ROLE_CRITICAL.items() if critical)

_CAPABILITY_ROLES: dict[str, list[str]] = {}
for _row in _ROLE_METADATA:
    _CAPABILITY_ROLES.setdefault(_row[5], []).append(_row[0])
CAPABILITY_CLASS_ROLES = MappingProxyType({
    name: tuple(roles) for name, roles in _CAPABILITY_ROLES.items()
})
CAPABILITY_CLASS_NAMES = frozenset(CAPABILITY_CLASS_ROLES)

_CAPABILITY_DESCRIPTIONS = {
    "address.resolve": "address, identity, and page-key resolution",
    "type.classify": "type and domain classification",
    "function.lookup": "function/candidate lookup",
    "constraint.preflight": "constraint and validity preflight",
    "math.execute": "numerical/symbolic execution binding",
    "relation.hypergraph": "relation and hypergraph construction",
    "provenance.hash": "hashing, provenance, and commit",
    "rule.propose": "learning/evaluation rule proposals",
    "page.index": "memory indexing and retrieval",
    "resource.prune": "pruning and resource management",
    "ring.schedule": "global ring scheduling authority",
    "ring.supervise": "global supervisory/fault authority",
}

FP_POLICIES = MappingProxyType({
    "none": MappingProxyType({
        "precision": "none",
        "rounding": "none",
        "fma": False,
        "nan_propagation": "not_applicable",
        "deterministic": True,
    }),
    "integer-exact": MappingProxyType({
        "precision": "integer-exact",
        "rounding": "none",
        "fma": False,
        "nan_propagation": "not_applicable",
        "deterministic": True,
    }),
    "binary32-rne": MappingProxyType({
        "precision": "binary32",
        "rounding": "round-to-nearest-even",
        "fma": False,
        "nan_propagation": "declared",
        "deterministic": True,
    }),
    "binary64-rne": MappingProxyType({
        "precision": "binary64",
        "rounding": "round-to-nearest-even",
        "fma": False,
        "nan_propagation": "declared",
        "deterministic": True,
    }),
})
FP_POLICY_NAMES = frozenset(FP_POLICIES)


def _build_lane_role_table() -> tuple[str, ...]:
    table: list[str | None] = [None] * LANE_COUNT
    for role, first, last in LANE_ROLE_RANGES:
        if role not in LANE_ROLES:
            raise LaneRoleError(f"unknown lane role in range: {role!r}")
        for lane_id in range(first, last + 1):
            if not 0 <= lane_id < LANE_COUNT:
                raise LaneBoundsError("lane role range leaves 0..254")
            if table[lane_id] is not None:
                raise LaneDuplicateError(f"lane {lane_id} has more than one role range")
            table[lane_id] = role
    if any(role is None for role in table):
        raise LaneRoleError("lane role ranges must cover all 255 lanes")
    return tuple(role for role in table if role is not None)


_LANE_ROLE_BY_ID = _build_lane_role_table()


def role_for_lane(lane_id: int) -> str:
    if _is_int(lane_id) and lane_id == NANNET0_RING_POSITION:
        raise Nannet0LaneError(
            "NANNET0 is ring position/page 255, not a logical lane"
        )
    _require_int(lane_id, "lane_id", minimum=0, maximum=LANE_COUNT - 1,
                 error_cls=LaneBoundsError)
    return _LANE_ROLE_BY_ID[lane_id]


def role_mask(*roles: str) -> int:
    """Return the bit mask for one or more declared roles."""

    mask = 0
    for role in roles:
        if role not in ROLE_BITS:
            raise LaneRoleError(f"unknown role: {role!r}")
        mask |= ROLE_BITS[role]
    if mask == 0:
        raise LaneRoleError("at least one role is required")
    return mask


def roles_from_mask(mask: int) -> tuple[str, ...]:
    _require_int(mask, "role_mask", minimum=1, maximum=ALL_ROLE_MASK,
                 error_cls=LaneRoleError)
    if mask & ~ALL_ROLE_MASK:
        raise LaneRoleError("role_mask contains undeclared bits")
    return tuple(role for role in ROLES if mask & ROLE_BITS[role])


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)


def _group_roles(group_id: int) -> tuple[str, ...]:
    first = group_id * LANES_PER_GROUP
    return _ordered_unique(_LANE_ROLE_BY_ID[first:first + LANES_PER_GROUP])


def _role_documents() -> list[dict[str, Any]]:
    return [
        {
            "role": role,
            "scope": scope,
            "bit": 1 << bit,
            "authority": authority,
            "critical": critical,
            "capability_class": capability,
            "max_fanout": max_fanout,
            "fp_policy": fp_policy,
        }
        for (role, scope, bit, authority, critical, capability, max_fanout, fp_policy)
        in _ROLE_METADATA
    ]


def _capability_class_documents() -> dict[str, dict[str, Any]]:
    return {
        name: {
            "description": _CAPABILITY_DESCRIPTIONS[name],
            "roles": list(CAPABILITY_CLASS_ROLES[name]),
        }
        for name in sorted(CAPABILITY_CLASS_ROLES)
    }


def _fp_policy_documents() -> dict[str, dict[str, Any]]:
    return {name: _plain(policy) for name, policy in sorted(FP_POLICIES.items())}


def _state_model_document() -> dict[str, Any]:
    return {
        "lane_state": "projection",
        "job_ledger": "existing-control-plane",
        "lease_ledger": "existing-control-plane",
        "owns_jobs": False,
        "owns_leases": False,
        "owns_page_store": False,
        "note": "lane state projects existing job/lease authority; it is not a second ledger",
    }


def _duplicate_role_policy() -> dict[str, str]:
    return {
        "lane_roles": "repeat_allowed",
        "global_roles": "exactly_once",
        "lane_ids": "unique",
        "lane_keys": "unique",
        "home_pages": "unique",
        "global_authority_in_lane_mask": "reject",
        "nannet0_as_lane": "reject",
    }


def _nannet0_document() -> dict[str, Any]:
    return {
        "ring_position": NANNET0_RING_POSITION,
        "head_index": None,
        "lane_id": None,
        "is_lane": False,
        "page_key": NANNET0_PAGE_KEY,
        "learning_acl": False,
        "reason": "NANNET0 is the universe port at ring position 255, not a lane",
    }


def page_budget_document() -> dict[str, Any]:
    """Return the declarative one-home-page-per-lane budget."""

    return {
        "schema": PAGE_BUDGET_SCHEMA,
        "page_bytes": PAGE_BYTES,
        "pages_per_lane": HOME_PAGES_PER_LANE,
        "lane_count": LANE_COUNT,
        "pages": LANE_HOME_PAGES,
        "bytes": LANE_HOME_BYTES,
        "mib": "7.96875",
        "mib_approx": "7.97",
        "declared_home_pages": LANE_HOME_PAGES,
        "declared_home_bytes": LANE_HOME_BYTES,
        "declared_home_mib": "7.96875",
        "declared_home_mib_approx": "7.97",
        "head_pages": LANE_COUNT,
        "nannet0_pages": NANNET0_PAGES,
        "nannet0_bytes": NANNET0_BYTES,
        "universe_pages": UNIVERSE_PAGES,
        "universe_bytes": UNIVERSE_BYTES,
        "remaining_universe_pages": UNIVERSE_PAGES - LANE_HOME_PAGES,
        "concurrency": CONCURRENCY,
        "live_home_pages": CONCURRENCY,
        "live_home_bytes": CONCURRENCY * PAGE_BYTES,
        "live_pages": CONCURRENCY,
        "max_concurrent_lane_runs": CONCURRENCY,
        "standby_home_pages": STANDBY_SLOTS_WITH_LIVE_WORKING_SETS,
        "fits_universe": LANE_HOME_BYTES <= UNIVERSE_BYTES,
        "heavy_matrices": "transient page-sets, never per-lane persistent state",
    }


def execution_identity_document() -> dict[str, Any]:
    """Declare the single active execution identity behind 255 logical lanes."""

    return {
        "declared_logical_lanes": LANE_COUNT,
        "executing_lane_runs": EXECUTING_LANE_RUNS,
        "active_runner_slots": ACTIVE_RUNNER_SLOTS,
        "standby_slots_with_live_working_sets": STANDBY_SLOTS_WITH_LIVE_WORKING_SETS,
        "native_kernel_invocations_in_flight": NATIVE_KERNEL_INVOCATIONS_IN_FLIGHT,
        "concurrency": CONCURRENCY,
        "live_home_pages": CONCURRENCY,
        "lane_kind": "durable logical work identity, not a runner",
    }


def _digest_method_document() -> dict[str, Any]:
    return {
        "algorithm": "sha256",
        "canonical_form": (
            "UTF-8 JSON with the top-level 'digest' field removed, keys sorted "
            "lexicographically, separators ',' and ':', ensure_ascii=true, "
            "allow_nan=false"
        ),
        "lane_digest_form": "lane object with its 'digest' field removed",
        "digest_encoding": "lowercase hexadecimal",
    }


@dataclass(frozen=True)
class LaneRecord:
    """Immutable declarative lane identity and capability record."""

    lane_id: int
    lane_key: str
    group_id: int
    group_key: str
    index_in_group: int
    ring_position: int
    home_page: int
    home_page_key: str
    role: str
    role_mask: int
    capability_class: str
    max_fanout: int
    fp_policy: str
    critical: bool = False
    version: int = LANE_VERSION
    global_authority: bool = False

    def __post_init__(self) -> None:
        if _is_int(self.lane_id) and self.lane_id == NANNET0_RING_POSITION:
            raise Nannet0LaneError(
                "NANNET0 is ring position/page 255, not a logical lane"
            )
        _require_int(self.lane_id, "lane_id", minimum=0, maximum=LANE_COUNT - 1,
                     error_cls=LaneBoundsError)
        if self.ring_position == NANNET0_RING_POSITION:
            raise Nannet0LaneError("ring position 255 is NANNET0, not a lane")
        if self.ring_position != self.lane_id:
            raise LaneBoundsError("lane ring_position must equal lane_id in 0..254")
        if self.lane_key != lane_key(self.lane_id):
            raise LaneBoundsError("lane_key does not match the durable lane identity")
        expected_group = self.lane_id // LANES_PER_GROUP
        if self.group_id != expected_group or self.group_key != group_key(expected_group):
            raise LaneBoundsError("group identity does not match lane_id // 15")
        if self.index_in_group != self.lane_id % LANES_PER_GROUP:
            raise LaneBoundsError("index_in_group does not match lane_id % 15")
        if self.home_page != self.lane_id:
            raise LaneBoundsError("each lane owns exactly one home page equal to lane_id")
        if self.home_page_key != page_key(self.home_page):
            raise LaneBoundsError("home_page_key does not match the home page identity")
        if self.home_page_key == NANNET0_PAGE_KEY:
            raise Nannet0LaneError("page 255 is NANNET0, not a lane home page")

        if self.role not in LANE_ROLES:
            raise LaneRoleError("lane role must be one of the 10 lane-local roles")
        _require_int(self.role_mask, "role_mask", minimum=1, maximum=ALL_ROLE_MASK,
                     error_cls=LaneRoleError)
        if self.role_mask & ~LANE_ROLE_MASK:
            raise LaneRoleError(
                "lane role_mask may not contain global scheduling/supervisor bits"
            )
        if not self.role_mask & ROLE_BITS[self.role]:
            raise LaneRoleError("lane role_mask must include the primary role bit")
        if self.role_mask != ROLE_BITS[self.role]:
            raise LaneRoleError("lane role_mask must declare exactly its generic role")

        if not isinstance(self.capability_class, str) or not _CAPABILITY_RE.fullmatch(
                self.capability_class):
            raise LanePolicyError("capability_class must be a declared capability name")
        if self.capability_class not in CAPABILITY_CLASS_NAMES:
            raise LanePolicyError(f"unknown capability class: {self.capability_class!r}")
        if self.role not in CAPABILITY_CLASS_ROLES[self.capability_class]:
            raise LanePolicyError("capability class is not valid for this lane role")
        if self.capability_class != ROLE_CAPABILITY_CLASS[self.role]:
            raise LanePolicyError("lane capability_class does not match its generic role")

        _require_int(self.max_fanout, "max_fanout", minimum=1,
                     maximum=LANES_PER_GROUP, error_cls=LanePolicyError)
        if self.max_fanout != ROLE_MAX_FANOUT[self.role]:
            raise LanePolicyError("lane max_fanout does not match its generic role")

        if self.fp_policy not in FP_POLICY_NAMES:
            raise LanePolicyError(f"unknown FP policy: {self.fp_policy!r}")
        if self.fp_policy != ROLE_FP_POLICY[self.role]:
            raise LanePolicyError("lane FP policy does not match its generic role")

        if not isinstance(self.critical, bool):
            raise LanePolicyError("critical must be boolean")
        if self.critical != ROLE_CRITICAL[self.role]:
            raise LanePolicyError("lane critical flag does not match its role")
        _require_int(self.version, "version", minimum=1,
                     error_cls=LanePolicyError)
        if self.global_authority is not False:
            raise LaneRoleError(
                "scheduling/supervisor are global authorities, not per-lane records"
            )

    @property
    def roles(self) -> tuple[str, ...]:
        return roles_from_mask(self.role_mask)

    @property
    def assigned_role(self) -> str:
        return self.role

    @property
    def generic_role(self) -> str:
        return self.role

    @property
    def capability(self) -> dict[str, Any]:
        return {
            "class": self.capability_class,
            "max_fanout": self.max_fanout,
            "fp_policy": self.fp_policy,
        }

    @property
    def fp(self) -> dict[str, Any]:
        return _plain(FP_POLICIES[self.fp_policy])

    @property
    def scope(self) -> str:
        return "lane"

    @property
    def page_id(self) -> int:
        return self.home_page

    @property
    def page_key(self) -> str:
        return self.home_page_key

    @property
    def page_key_value(self) -> str:
        return self.home_page_key

    @property
    def head_index(self) -> int:
        return self.lane_id

    @property
    def durable_key(self) -> str:
        return self.lane_key

    def _payload(self) -> dict[str, Any]:
        return {
            "schema": LANE_SCHEMA,
            "lane_id": self.lane_id,
            "lane_key": self.lane_key,
            "group_id": self.group_id,
            "group_key": self.group_key,
            "index_in_group": self.index_in_group,
            "ring_position": self.ring_position,
            "home_page": self.home_page,
            "home_page_key": self.home_page_key,
            "role": self.role,
            "role_mask": self.role_mask,
            "roles": list(self.roles),
            "capability_class": self.capability_class,
            "max_fanout": self.max_fanout,
            "fp_policy": self.fp_policy,
            "critical": self.critical,
            "global_authority": self.global_authority,
            "scope": "lane",
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        document = self._payload()
        document["digest"] = str(self.digest)
        return document

    @property
    def digest(self) -> Digest:
        return Digest(digest_object(self._payload()))

    @classmethod
    def from_dict(cls, entry: Mapping[str, Any]) -> "LaneRecord":
        if not isinstance(entry, Mapping):
            raise LaneRegistryError("lane entry must be an object")
        allowed = {
            "schema", "lane_id", "lane_key", "group_id", "group_key",
            "index_in_group", "ring_position", "home_page", "home_page_key",
            "role", "role_mask", "roles", "capability_class", "max_fanout",
            "fp_policy", "critical", "global_authority", "scope", "version",
            "digest",
        }
        unknown = set(entry) - allowed
        if unknown:
            raise LaneRegistryError(f"unknown lane fields: {sorted(unknown)}")
        record = cls(
            lane_id=entry.get("lane_id"),
            lane_key=entry.get("lane_key"),
            group_id=entry.get("group_id"),
            group_key=entry.get("group_key"),
            index_in_group=entry.get("index_in_group"),
            ring_position=entry.get("ring_position"),
            home_page=entry.get("home_page"),
            home_page_key=entry.get("home_page_key"),
            role=entry.get("role"),
            role_mask=entry.get("role_mask"),
            capability_class=entry.get("capability_class"),
            max_fanout=entry.get("max_fanout"),
            fp_policy=entry.get("fp_policy"),
            critical=entry.get("critical", ROLE_CRITICAL.get(entry.get("role"), False)),
            version=entry.get("version", LANE_VERSION),
            global_authority=entry.get("global_authority", False),
        )
        if "roles" in entry and list(entry["roles"]) != list(record.roles):
            raise LaneRoleError("lane roles list does not match role_mask")
        if "scope" in entry and entry["scope"] != "lane":
            raise LaneRoleError("a lane record may not have global scope")
        if "schema" in entry and entry["schema"] != LANE_SCHEMA:
            raise LaneRegistryError("unsupported lane record schema")
        if entry.get("digest") is not None:
            if not isinstance(entry["digest"], str) or not _DIGEST_RE.fullmatch(
                    entry["digest"]):
                raise LaneRegistryError("lane digest must be 64 lowercase hex characters")
            if entry["digest"] != str(record.digest):
                raise LaneRegistryError("lane digest mismatch")
        return record


@dataclass(frozen=True)
class LaneGroup:
    """One deterministic 15-lane pass."""

    group_id: int
    group_key: str
    pass_index: int
    first_lane: int
    last_lane: int
    lane_ids: tuple[int, ...]
    roles: tuple[str, ...]
    lanes: tuple[LaneRecord, ...]

    def __post_init__(self) -> None:
        _require_int(self.group_id, "group_id", minimum=0,
                     maximum=GROUP_COUNT - 1, error_cls=LaneBoundsError)
        object.__setattr__(self, "lane_ids", tuple(self.lane_ids))
        object.__setattr__(self, "roles", tuple(self.roles))
        object.__setattr__(self, "lanes", tuple(self.lanes))
        expected_first = self.group_id * LANES_PER_GROUP
        expected_last = expected_first + LANES_PER_GROUP - 1
        if self.first_lane != expected_first or self.last_lane != expected_last:
            raise LaneBoundsError("group bounds must be 15*g .. 15*g+14")
        if self.group_key != group_key(self.group_id):
            raise LaneBoundsError("group_key does not match group_id")
        if self.pass_index != self.group_id:
            raise LaneBoundsError("pass_index must equal group_id")
        if self.lane_ids != tuple(range(expected_first, expected_last + 1)):
            raise LaneBoundsError("group lane_ids must be one contiguous 15-lane pass")
        if len(self.lanes) != LANES_PER_GROUP:
            raise LaneBoundsError("a group contains exactly 15 lane records")
        if tuple(lane.lane_id for lane in self.lanes) != self.lane_ids:
            raise LaneBoundsError("group lane records do not match lane_ids")
        if self.roles != _ordered_unique(role for lane in self.lanes for role in lane.roles):
            raise LaneRoleError("group roles do not match the lane role masks")

    def __len__(self) -> int:
        return len(self.lanes)

    def __iter__(self):
        return iter(self.lanes)

    def __getitem__(self, item):
        if isinstance(item, str):
            return self.to_dict()[item]
        return self.lanes[item]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": GROUP_SCHEMA,
            "group_id": self.group_id,
            "group_key": self.group_key,
            "pass_index": self.pass_index,
            "first_lane": self.first_lane,
            "last_lane": self.last_lane,
            "lane_count": len(self.lanes),
            "lane_ids": list(self.lane_ids),
            "roles": list(self.roles),
        }

    @property
    def digest(self) -> Digest:
        return Digest(digest_object(self.to_dict()))


@dataclass(frozen=True)
class GlobalAuthority:
    """A global scheduling/supervisory authority, declared exactly once."""

    authority_id: str
    role: str
    scope: str = "global"
    concurrency: int = CONCURRENCY
    max_fanout: int = 1
    version: int = RULESET_VERSION

    def __post_init__(self) -> None:
        if self.role not in GLOBAL_ROLES:
            raise LaneRoleError("a global authority must be scheduling or supervisor")
        if self.authority_id != f"authority:{self.role}":
            raise LaneRoleError("authority_id must match authority:<role>")
        if self.scope != "global":
            raise LaneRoleError("scheduling/supervisor scope is global, never per-lane")
        if self.concurrency != CONCURRENCY:
            raise LanePolicyError("global authorities expose concurrency=1")
        _require_int(self.max_fanout, "authority max_fanout", minimum=1,
                     error_cls=LanePolicyError)
        _require_int(self.version, "authority version", minimum=1,
                     error_cls=LanePolicyError)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": AUTHORITY_SCHEMA,
            "authority_id": self.authority_id,
            "role": self.role,
            "scope": self.scope,
            "concurrency": self.concurrency,
            "max_fanout": self.max_fanout,
            "version": self.version,
        }

    @property
    def digest(self) -> Digest:
        return Digest(digest_object(self.to_dict()))


class _CallableTuple(tuple):
    """Tuple that also supports the ``registry.lanes()`` spelling."""

    def __call__(self):
        return self


class _CallableDict(dict):
    """Fresh mapping that also supports the ``registry.page_budget()`` spelling."""

    def __call__(self):
        return self


def _new_lane(lane_id: int) -> LaneRecord:
    role = _LANE_ROLE_BY_ID[lane_id]
    return LaneRecord(
        lane_id=lane_id,
        lane_key=lane_key(lane_id),
        group_id=lane_id // LANES_PER_GROUP,
        group_key=group_key(lane_id // LANES_PER_GROUP),
        index_in_group=lane_id % LANES_PER_GROUP,
        ring_position=lane_id,
        home_page=lane_id,
        home_page_key=page_key(lane_id),
        role=role,
        role_mask=ROLE_BITS[role],
        capability_class=ROLE_CAPABILITY_CLASS[role],
        max_fanout=ROLE_MAX_FANOUT[role],
        fp_policy=ROLE_FP_POLICY[role],
        critical=ROLE_CRITICAL[role],
        version=LANE_VERSION,
        global_authority=False,
    )


def _group_document(group_id: int) -> dict[str, Any]:
    first = group_id * LANES_PER_GROUP
    last = first + LANES_PER_GROUP - 1
    return {
        "schema": GROUP_SCHEMA,
        "group_id": group_id,
        "group_key": group_key(group_id),
        "pass_index": group_id,
        "first_lane": first,
        "last_lane": last,
        "lane_count": LANES_PER_GROUP,
        "lane_ids": list(range(first, last + 1)),
        "roles": list(_group_roles(group_id)),
    }


def _authority_document(role: str) -> dict[str, Any]:
    return GlobalAuthority(
        authority_id=f"authority:{role}",
        role=role,
        scope="global",
        concurrency=CONCURRENCY,
        max_fanout=1,
        version=RULESET_VERSION,
    ).to_dict()


def build_ruleset() -> dict[str, Any]:
    """Build a fresh canonical ruleset document (safe to mutate by the caller)."""

    lanes = [_new_lane(lane_id).to_dict() for lane_id in range(LANE_COUNT)]
    document: dict[str, Any] = {
        "schema": SCHEMA,
        "ruleset_id": RULESET_ID,
        "version": RULESET_VERSION,
        "digest_method": _digest_method_document(),
        "lane_count": LANE_COUNT,
        "group_count": GROUP_COUNT,
        "lanes_per_group": LANES_PER_GROUP,
        "pass_count": PASS_COUNT,
        "ring_positions": RING_POSITIONS,
        "nannet0_ring_position": NANNET0_RING_POSITION,
        "declared_logical_lanes": LANE_COUNT,
        "executing_lane_runs": EXECUTING_LANE_RUNS,
        "active_runner_slots": ACTIVE_RUNNER_SLOTS,
        "standby_slots_with_live_working_sets": STANDBY_SLOTS_WITH_LIVE_WORKING_SETS,
        "native_kernel_invocations_in_flight": NATIVE_KERNEL_INVOCATIONS_IN_FLIGHT,
        "concurrency": CONCURRENCY,
        "nannet0": _nannet0_document(),
        "page_budget": page_budget_document(),
        "state_model": _state_model_document(),
        "roles": _role_documents(),
        "duplicate_role_policy": _duplicate_role_policy(),
        "global_authorities": [_authority_document(role) for role in GLOBAL_ROLES],
        "capability_classes": _capability_class_documents(),
        "fp_policies": _fp_policy_documents(),
        "groups": [_group_document(group_id) for group_id in range(GROUP_COUNT)],
        "lanes": lanes,
    }
    document["digest"] = digest_document(document)
    return document


def _check_int_field(container: Mapping[str, Any], key: str, expected: int,
                     *, error_cls: type[LaneRegistryError] = LaneBoundsError) -> int:
    value = container.get(key)
    if not _is_int(value) or value != expected:
        raise error_cls(f"{key} must be {expected}")
    return value


def _validate_state_model(state_model: Any) -> None:
    if not isinstance(state_model, Mapping):
        raise LanePolicyError("state_model must be an object")
    if state_model.get("lane_state") != "projection":
        raise LanePolicyError("lane state must be a projection of existing authority")
    for key in ("owns_jobs", "owns_leases", "owns_page_store"):
        if state_model.get(key) is not False:
            raise LanePolicyError(f"state_model.{key} must be false")
    if not isinstance(state_model.get("job_ledger"), str) or not state_model["job_ledger"]:
        raise LanePolicyError("state_model.job_ledger must name the existing authority")
    if not isinstance(state_model.get("lease_ledger"), str) or not state_model["lease_ledger"]:
        raise LanePolicyError("state_model.lease_ledger must name the existing authority")


def _validate_page_budget(budget: Any) -> None:
    if not isinstance(budget, Mapping):
        raise LanePolicyError("page_budget must be an object")
    expected = page_budget_document()
    int_keys = {key for key, value in expected.items() if _is_int(value)}
    bool_keys = {key for key, value in expected.items() if isinstance(value, bool)}
    for key, value in expected.items():
        if key not in budget:
            raise LanePolicyError(f"page_budget is missing {key}")
        observed = budget[key]
        if key in int_keys and (not _is_int(observed) or observed != value):
            raise LanePolicyError(f"page_budget {key} must be {value}")
        if key in bool_keys and not isinstance(observed, bool):
            raise LanePolicyError(f"page_budget {key} must be boolean")
        if observed != value:
            raise LanePolicyError(f"page_budget {key} must be {value!r}")
    if budget["pages_per_lane"] != HOME_PAGES_PER_LANE:
        raise LanePolicyError("each lane owns exactly one 32 KiB home page")
    if budget["declared_home_pages"] != LANE_HOME_PAGES:
        raise LanePolicyError("declared home pages must be 255")
    if budget["declared_home_bytes"] != LANE_HOME_BYTES:
        raise LanePolicyError("255 home pages must total 7.97 MiB")
    if budget["concurrency"] != CONCURRENCY:
        raise LanePolicyError("page budget may not claim concurrent live home pages")


def _validate_capability_classes(classes: Any) -> None:
    if not isinstance(classes, Mapping):
        raise LanePolicyError("capability_classes must be an object")
    if set(classes) != CAPABILITY_CLASS_NAMES:
        raise LanePolicyError("capability_classes must declare the canonical classes")
    for name, declaration in classes.items():
        if not isinstance(name, str) or not _CAPABILITY_RE.fullmatch(name):
            raise LanePolicyError("capability class names must be lowercase identifiers")
        if not isinstance(declaration, Mapping):
            raise LanePolicyError("capability class declarations must be objects")
        roles = declaration.get("roles")
        if not isinstance(roles, (list, tuple)) or not roles:
            raise LanePolicyError("capability class roles must be a non-empty list")
        if len(set(roles)) != len(roles):
            raise LaneRoleError("capability class roles contain duplicates")
        for role in roles:
            if role not in ROLES:
                raise LaneRoleError(f"unknown role in capability class: {role!r}")
        if tuple(roles) != CAPABILITY_CLASS_ROLES[name]:
            raise LaneRoleError("capability class roles do not match the canonical map")
        description = declaration.get("description")
        if not isinstance(description, str) or not description:
            raise LanePolicyError("capability class description is required")
    for role in ROLES:
        owners = [name for name, roles in CAPABILITY_CLASS_ROLES.items() if role in roles]
        if len(owners) != 1:
            raise LanePolicyError("each role must own exactly one capability class")


def _validate_fp_policies(policies: Any) -> None:
    if not isinstance(policies, Mapping):
        raise LanePolicyError("fp_policies must be an object")
    if set(policies) != FP_POLICY_NAMES:
        raise LanePolicyError("fp_policies must declare the canonical policy names")
    required = {"precision", "rounding", "fma", "nan_propagation", "deterministic"}
    for name, declaration in policies.items():
        if not isinstance(declaration, Mapping):
            raise LanePolicyError("FP policy declarations must be objects")
        missing = required - set(declaration)
        if missing:
            raise LanePolicyError(f"FP policy {name!r} is missing {sorted(missing)}")
        if not isinstance(declaration["precision"], str) or not declaration["precision"]:
            raise LanePolicyError("FP precision must be a non-empty string")
        if not isinstance(declaration["rounding"], str) or not declaration["rounding"]:
            raise LanePolicyError("FP rounding must be a non-empty string")
        if not isinstance(declaration["fma"], bool):
            raise LanePolicyError("FP fma must be boolean")
        if not isinstance(declaration["nan_propagation"], str) or not declaration["nan_propagation"]:
            raise LanePolicyError("FP nan_propagation must be a non-empty string")
        if not isinstance(declaration["deterministic"], bool):
            raise LanePolicyError("FP deterministic must be boolean")
        if _plain(declaration) != _plain(FP_POLICIES[name]):
            raise LanePolicyError(f"FP policy {name!r} does not match the canonical declaration")


def _validate_duplicate_policy(policy: Any) -> None:
    if not isinstance(policy, Mapping):
        raise LanePolicyError("duplicate_role_policy must be an object")
    expected = _duplicate_role_policy()
    for key, value in expected.items():
        if policy.get(key) != value:
            raise LanePolicyError(
                f"duplicate_role_policy.{key} must be {value!r}; "
                "global authorities are exactly-once and NANNET0 is never a lane"
            )


def _validate_roles(role_documents: Any) -> dict[str, Mapping[str, Any]]:
    if not isinstance(role_documents, (list, tuple)):
        raise LaneRoleError("roles must be a list")
    if len(role_documents) != len(ROLES):
        raise LaneRoleError("exactly 12 roles must be declared")
    seen: dict[str, Mapping[str, Any]] = {}
    names: list[str] = []
    for entry in role_documents:
        if not isinstance(entry, Mapping):
            raise LaneRoleError("each role declaration must be an object")
        role = entry.get("role")
        if role not in ROLE_BITS:
            raise LaneRoleError(f"unknown role: {role!r}")
        if role in seen:
            raise LaneDuplicateError(f"duplicate role declaration: {role!r}")
        seen[role] = entry
        names.append(role)
        if entry.get("bit") != ROLE_BITS[role]:
            raise LaneRoleError(f"role {role!r} has the wrong mask bit")
        if entry.get("scope") != ROLE_SCOPES[role]:
            raise LaneRoleError(f"role {role!r} has the wrong scope")
        if entry.get("authority") is not ROLE_AUTHORITIES[role]:
            raise LaneRoleError(f"role {role!r} has the wrong authority flag")
        if entry.get("critical") is not ROLE_CRITICAL[role]:
            raise LaneRoleError(f"role {role!r} has the wrong critical flag")
        capability = entry.get("capability_class")
        if capability not in CAPABILITY_CLASS_NAMES:
            raise LanePolicyError(f"role {role!r} has an unknown capability class")
        if role not in CAPABILITY_CLASS_ROLES[capability]:
            raise LanePolicyError(f"capability class is not valid for role {role!r}")
        if capability != ROLE_CAPABILITY_CLASS[role]:
            raise LanePolicyError(f"role {role!r} capability class is not canonical")
        _require_int(entry.get("max_fanout"), f"{role} max_fanout", minimum=1,
                     maximum=LANES_PER_GROUP, error_cls=LanePolicyError)
        if entry.get("max_fanout") != ROLE_MAX_FANOUT[role]:
            raise LanePolicyError(f"role {role!r} max_fanout is not canonical")
        fp_policy = entry.get("fp_policy")
        if fp_policy not in FP_POLICY_NAMES:
            raise LanePolicyError(f"role {role!r} has an unknown FP policy")
        if fp_policy != ROLE_FP_POLICY[role]:
            raise LanePolicyError(f"role {role!r} FP policy is not canonical")
    if tuple(names) != ROLES:
        raise LaneRoleError("roles must be declared in canonical order with no duplicates")
    return seen


def _validate_nannet0(nannet0: Any) -> None:
    if not isinstance(nannet0, Mapping):
        raise LanePolicyError("nannet0 declaration must be an object")
    if nannet0.get("ring_position") != NANNET0_RING_POSITION:
        raise Nannet0LaneError("NANNET0 must be ring position 255")
    if nannet0.get("page_key") != NANNET0_PAGE_KEY:
        raise Nannet0LaneError("NANNET0 must own page:255")
    if nannet0.get("is_lane") is not False:
        raise Nannet0LaneError("NANNET0 is ring position 255, not a lane")
    if nannet0.get("lane_id") is not None:
        raise Nannet0LaneError("NANNET0 may not have a lane_id")
    if nannet0.get("head_index") is not None:
        raise Nannet0LaneError("NANNET0 is not a head index")
    if nannet0.get("learning_acl") is not False:
        raise Nannet0LaneError("NANNET0 never receives a learning ACL")


def _validate_authorities(authorities: Any) -> None:
    if not isinstance(authorities, (list, tuple)):
        raise LaneRoleError("global_authorities must be a list")
    if len(authorities) != len(GLOBAL_ROLES):
        raise LaneRoleError("exactly two global authorities are required")
    seen_roles: set[str] = set()
    seen_ids: set[str] = set()
    for entry in authorities:
        if not isinstance(entry, Mapping):
            raise LaneRoleError("each global authority must be an object")
        role = entry.get("role")
        if role not in GLOBAL_ROLES:
            raise LaneRoleError(
                "only scheduling and supervisor are global authorities"
            )
        if role in seen_roles:
            raise LaneDuplicateError(
                f"duplicate global authority role: {role!r}; per-lane copies are forbidden"
            )
        seen_roles.add(role)
        authority_id = entry.get("authority_id")
        if not isinstance(authority_id, str) or not authority_id:
            raise LaneRoleError("global authority_id is required")
        if authority_id in seen_ids:
            raise LaneDuplicateError(f"duplicate authority_id: {authority_id!r}")
        seen_ids.add(authority_id)
        if entry.get("schema") not in (None, AUTHORITY_SCHEMA):
            raise LaneRoleError("unsupported global authority schema")
        GlobalAuthority(
            authority_id=authority_id,
            role=role,
            scope=entry.get("scope"),
            concurrency=entry.get("concurrency"),
            max_fanout=entry.get("max_fanout"),
            version=entry.get("version"),
        )
    if seen_roles != set(GLOBAL_ROLES):
        raise LaneRoleError("scheduling and supervisor must each appear exactly once")


def _validate_groups(groups: Any, lanes_by_id: Mapping[int, LaneRecord]) -> None:
    if not isinstance(groups, (list, tuple)):
        raise LaneBoundsError("groups must be a list")
    if len(groups) != GROUP_COUNT:
        raise LaneBoundsError("exactly 17 groups are required")
    seen: set[int] = set()
    for entry in groups:
        if not isinstance(entry, Mapping):
            raise LaneBoundsError("each group must be an object")
        group_id = entry.get("group_id")
        _require_int(group_id, "group_id", minimum=0, maximum=GROUP_COUNT - 1,
                     error_cls=LaneBoundsError)
        if group_id in seen:
            raise LaneDuplicateError(f"duplicate group_id: {group_id}")
        seen.add(group_id)
        expected = _group_document(group_id)
        for key in ("group_key", "pass_index", "first_lane", "last_lane",
                    "lane_count", "lane_ids", "roles"):
            if entry.get(key) != expected[key]:
                error_cls = LaneRoleError if key == "roles" else LaneBoundsError
                raise error_cls(f"group {group_id} {key} does not match the lane schedule")
        if entry.get("schema") not in (None, GROUP_SCHEMA):
            raise LaneBoundsError("unsupported group schema")
    if seen != set(range(GROUP_COUNT)):
        raise LaneBoundsError("groups must cover pass ids 0..16 exactly once")


def validate_ruleset(document: Mapping[str, Any], *,
                     require_digest: bool = False) -> dict[str, Any]:
    """Validate and normalize a lane ruleset; return a fresh canonical copy."""

    if not isinstance(document, Mapping):
        raise LaneRegistryError("ruleset must be a JSON object")
    original = copy.deepcopy(dict(document))
    document = copy.deepcopy(original)

    if document.get("schema") != SCHEMA:
        raise LaneRegistryError("unsupported lane ruleset schema")
    if document.get("ruleset_id") != RULESET_ID:
        raise LaneRegistryError("unsupported lane ruleset id")
    _require_int(document.get("version"), "ruleset version", minimum=1,
                 error_cls=LanePolicyError)

    _check_int_field(document, "lane_count", LANE_COUNT)
    _check_int_field(document, "group_count", GROUP_COUNT)
    _check_int_field(document, "lanes_per_group", LANES_PER_GROUP)
    _check_int_field(document, "pass_count", PASS_COUNT)
    _check_int_field(document, "ring_positions", RING_POSITIONS)
    _check_int_field(document, "nannet0_ring_position", NANNET0_RING_POSITION)
    _check_int_field(document, "declared_logical_lanes", LANE_COUNT)
    _check_int_field(document, "executing_lane_runs", EXECUTING_LANE_RUNS,
                     error_cls=LanePolicyError)
    _check_int_field(document, "active_runner_slots", ACTIVE_RUNNER_SLOTS,
                     error_cls=LanePolicyError)
    _check_int_field(document, "standby_slots_with_live_working_sets",
                     STANDBY_SLOTS_WITH_LIVE_WORKING_SETS, error_cls=LanePolicyError)
    _check_int_field(document, "native_kernel_invocations_in_flight",
                     NATIVE_KERNEL_INVOCATIONS_IN_FLIGHT, error_cls=LanePolicyError)
    _check_int_field(document, "concurrency", CONCURRENCY, error_cls=LanePolicyError)

    _validate_nannet0(document.get("nannet0"))
    _validate_page_budget(document.get("page_budget"))
    _validate_state_model(document.get("state_model"))
    _validate_duplicate_policy(document.get("duplicate_role_policy"))
    _validate_capability_classes(document.get("capability_classes"))
    _validate_fp_policies(document.get("fp_policies"))
    _validate_roles(document.get("roles"))
    _validate_authorities(document.get("global_authorities"))

    lane_entries = document.get("lanes")
    if not isinstance(lane_entries, (list, tuple)):
        raise LaneBoundsError("lanes must be a list")
    if len(lane_entries) != LANE_COUNT:
        raise LaneBoundsError("exactly 255 logical lanes are required")

    lanes: list[LaneRecord] = []
    for entry in lane_entries:
        lanes.append(LaneRecord.from_dict(entry))

    ids = [lane.lane_id for lane in lanes]
    if len(set(ids)) != LANE_COUNT or set(ids) != set(range(LANE_COUNT)):
        raise LaneDuplicateError(
            "lanes must cover ids 0..254 exactly once; 255 is NANNET0"
        )
    keys = [lane.lane_key for lane in lanes]
    if len(set(keys)) != LANE_COUNT:
        raise LaneDuplicateError("duplicate durable lane key")
    pages = [lane.home_page for lane in lanes]
    if len(set(pages)) != LANE_COUNT:
        raise LaneDuplicateError("duplicate lane home page")
    if NANNET0_RING_POSITION in ids or NANNET0_PAGE_KEY in {
            lane.home_page_key for lane in lanes}:
        raise Nannet0LaneError("NANNET0 page/ring position 255 may not be a lane")

    for lane in lanes:
        if lane.role != _LANE_ROLE_BY_ID[lane.lane_id]:
            raise LaneRoleError(
                "lane role does not match the canonical generic role assignment"
            )

    role_counts = Counter(lane.role for lane in lanes)
    for role in LANE_ROLES:
        if role_counts.get(role, 0) < 1:
            raise LaneRoleError(f"lane-local role has no lanes: {role!r}")
    for role in GLOBAL_ROLES:
        if role_counts.get(role, 0) != 0:
            raise LaneRoleError(
                f"global role {role!r} may not be duplicated as a per-lane role"
            )

    lanes_by_id = {lane.lane_id: lane for lane in lanes}
    _validate_groups(document.get("groups"), lanes_by_id)

    if "digest" in original:
        declared_digest = original.get("digest")
        if not isinstance(declared_digest, str) or not _DIGEST_RE.fullmatch(
                declared_digest):
            raise LaneRegistryError("ruleset digest must be 64 lowercase hex characters")
        if declared_digest != digest_document(original):
            raise LaneRegistryError("ruleset digest mismatch")
    elif require_digest:
        raise LaneRegistryError("ruleset digest is required")

    normalized: dict[str, Any] = copy.deepcopy(original)
    normalized["lanes"] = [
        lanes_by_id[lane_id].to_dict() for lane_id in range(LANE_COUNT)
    ]
    normalized.pop("digest", None)
    normalized["digest"] = digest_document(normalized)
    return normalized


def seal_ruleset(document: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute lane and top-level digests after an intentional test/edit.

    This is a helper for bounded validation tests.  It does not bypass any
    bounds, role, capability, duplicate, or page-budget check performed by
    :func:`validate_ruleset`.
    """

    if not isinstance(document, Mapping):
        raise LaneRegistryError("ruleset must be a JSON object")
    sealed = copy.deepcopy(dict(document))
    lanes = sealed.get("lanes")
    if isinstance(lanes, (list, tuple)):
        sealed_lanes = []
        for entry in lanes:
            if not isinstance(entry, Mapping):
                raise LaneRegistryError("lane entry must be an object")
            cleaned = {
                key: value for key, value in entry.items()
                if key not in {"digest", "roles"}
            }
            sealed_lanes.append(LaneRecord.from_dict(cleaned).to_dict())
        sealed["lanes"] = sealed_lanes
    sealed.pop("digest", None)
    sealed["digest"] = digest_document(sealed)
    return sealed


def default_spec_path() -> Path:
    return Path(__file__).resolve().parents[1] / "spec" / "lane-ruleset.v1.json"


def load_ruleset(path: str | Path | None = None, *,
                 require_digest: bool = True) -> dict[str, Any]:
    target = default_spec_path() if path is None else Path(path)
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LaneRegistryError(
            f"lane ruleset is unavailable or invalid JSON: {target}"
        ) from exc
    return validate_ruleset(document, require_digest=require_digest)


Lane = LaneRecord
NANNET0 = NANNET0_RING_POSITION


class LaneRegistry:
    """Deterministic, read-only registry over the 255 logical lanes."""

    def __init__(self, document: Mapping[str, Any] | str | Path | None = None):
        if document is None:
            document = build_ruleset()
        elif isinstance(document, (str, Path)):
            document = load_ruleset(document, require_digest=True)
        normalized = validate_ruleset(document, require_digest=False)
        self._document = normalized
        lanes = tuple(
            LaneRecord.from_dict(entry) for entry in normalized["lanes"]
        )
        if len(lanes) != LANE_COUNT:
            raise LaneBoundsError("registry must contain exactly 255 lanes")
        self._lanes = tuple(sorted(lanes, key=lambda lane: lane.lane_id))
        self._by_id = MappingProxyType({lane.lane_id: lane for lane in self._lanes})
        self._by_key = MappingProxyType({lane.lane_key: lane for lane in self._lanes})
        self._by_page = MappingProxyType({
            lane.home_page_key: lane for lane in self._lanes
        })
        self._groups = tuple(
            self._build_group(group_id) for group_id in range(GROUP_COUNT)
        )
        self._by_group = MappingProxyType({
            group.group_id: group for group in self._groups
        })
        self._authorities = tuple(
            GlobalAuthority(
                authority_id=entry["authority_id"],
                role=entry["role"],
                scope=entry["scope"],
                concurrency=entry["concurrency"],
                max_fanout=entry["max_fanout"],
                version=entry["version"],
            )
            for entry in normalized["global_authorities"]
        )
        self._by_authority_role = MappingProxyType({
            authority.role: authority for authority in self._authorities
        })

    @classmethod
    def from_spec(cls, path: str | Path | None = None) -> "LaneRegistry":
        return cls(load_ruleset(path, require_digest=True))

    @classmethod
    def from_default_spec(cls) -> "LaneRegistry":
        return cls.from_spec(default_spec_path())

    def _build_group(self, group_id: int) -> LaneGroup:
        first = group_id * LANES_PER_GROUP
        lanes = tuple(self._by_id[lane_id] for lane_id in range(
            first, first + LANES_PER_GROUP
        ))
        return LaneGroup(
            group_id=group_id,
            group_key=group_key(group_id),
            pass_index=group_id,
            first_lane=first,
            last_lane=first + LANES_PER_GROUP - 1,
            lane_ids=tuple(lane.lane_id for lane in lanes),
            roles=_ordered_unique(role for lane in lanes for role in lane.roles),
            lanes=lanes,
        )

    @property
    def ruleset_id(self) -> str:
        return self._document["ruleset_id"]

    @property
    def version(self) -> int:
        return self._document["version"]

    @property
    def digest(self) -> Digest:
        return Digest(self._document["digest"])

    @property
    def concurrency(self) -> int:
        return self._document["concurrency"]

    @property
    def active_runner_slots(self) -> int:
        return self._document["active_runner_slots"]

    @property
    def lanes(self) -> _CallableTuple:
        return _CallableTuple(self._lanes)

    @property
    def groups(self) -> _CallableTuple:
        return _CallableTuple(self._groups)

    @property
    def authorities(self) -> _CallableTuple:
        return _CallableTuple(self._authorities)

    @property
    def lane_ids(self) -> tuple[int, ...]:
        return tuple(lane.lane_id for lane in self._lanes)

    @property
    def page_keys(self) -> tuple[str, ...]:
        return tuple(lane.home_page_key for lane in self._lanes)

    @property
    def roles(self) -> _CallableTuple:
        return _CallableTuple(ROLES)

    @property
    def nannet0(self) -> _CallableDict:
        return _CallableDict(_plain(self._document["nannet0"]))

    @property
    def duplicate_role_policy(self) -> _CallableDict:
        return _CallableDict(_plain(self._document["duplicate_role_policy"]))

    @property
    def state_model(self) -> _CallableDict:
        return _CallableDict(_plain(self._document["state_model"]))

    @property
    def nannet0_ring_position(self) -> int:
        return self._document["nannet0_ring_position"]

    def __len__(self) -> int:
        return len(self._lanes)

    def __iter__(self):
        return iter(self._lanes)

    def __getitem__(self, item):
        if isinstance(item, str):
            return self.resolve(item)
        return self.lane(item)

    def lane(self, lane_ref: int | str) -> LaneRecord:
        if isinstance(lane_ref, str):
            return self.resolve(lane_ref)
        if _is_int(lane_ref) and lane_ref == NANNET0_RING_POSITION:
            raise Nannet0LaneError(
                "NANNET0 is ring position/page 255, not a logical lane"
            )
        lane_id = _require_int(lane_ref, "lane_id", minimum=0,
                               maximum=LANE_COUNT - 1,
                               error_cls=LaneBoundsError)
        return self._by_id[lane_id]

    def resolve(self, lane_ref: int | str) -> LaneRecord:
        """Resolve an ID, ``lane:NNN``, ``page:NNN``, or ``head:NNN`` reference."""

        if _is_int(lane_ref):
            return self.lane(lane_ref)
        if not isinstance(lane_ref, str):
            raise LaneBoundsError("lane reference must be an integer or string")
        text = lane_ref.strip()
        if not text:
            raise LaneBoundsError("lane reference may not be empty")
        compact = re.sub(r"[^A-Z0-9]", "", text.upper())
        if compact in {"NANNET0", "NANNETZERO"} or compact.startswith("NANNET0"):
            raise Nannet0LaneError(
                "NANNET0 is ring position/page 255, not a logical lane"
            )
        lower = text.lower()
        if lower in self._by_key:
            return self._by_key[lower]
        if NANNET0_PAGE_KEY in lower:
            raise Nannet0LaneError("page 255 belongs to NANNET0, not a lane")
        if lower in self._by_page:
            return self._by_page[lower]
        for prefix, pattern in (
            ("lane", _LANE_KEY_RE),
            ("page", _PAGE_KEY_RE),
            ("head", re.compile(r"^head:(\d{1,3})$")),
            ("ring", re.compile(r"^ring:(\d{1,3})$")),
        ):
            match = pattern.fullmatch(lower)
            if match:
                number = int(match.group(1))
                if number == NANNET0_RING_POSITION:
                    raise Nannet0LaneError(
                        "ring/page/head 255 belongs to NANNET0, not a lane"
                    )
                return self.lane(number)
        if lower.isdigit():
            number = int(lower)
            if number == NANNET0_RING_POSITION:
                raise Nannet0LaneError(
                    "ring/page/head 255 belongs to NANNET0, not a lane"
                )
            return self.lane(number)
        raise LaneRegistryError(f"unresolvable lane reference: {lane_ref!r}")

    def group(self, group_ref: int | str) -> LaneGroup:
        if isinstance(group_ref, str):
            text = group_ref.strip().lower()
            match = _GROUP_KEY_RE.fullmatch(text)
            if match:
                number = int(match.group(1))
            elif text.isdigit():
                number = int(text)
            else:
                raise LaneBoundsError(f"unresolvable group reference: {group_ref!r}")
        else:
            number = _require_int(group_ref, "group_id", minimum=0,
                                  maximum=GROUP_COUNT - 1,
                                  error_cls=LaneBoundsError)
        if not 0 <= number < GROUP_COUNT:
            raise LaneBoundsError("group_id must be in 0..16")
        return self._by_group[number]

    def passes(self, group_id: int | None = None):
        """Return all 17 deterministic passes, or one pass when selected."""

        if group_id is None:
            return self._groups
        return (self.group(group_id),)

    def pass_lane_ids(self) -> tuple[tuple[int, ...], ...]:
        return tuple(group.lane_ids for group in self._groups)

    def role_holders(self, role: str):
        if role not in ROLE_BITS:
            raise LaneRoleError(f"unknown role: {role!r}")
        if role in GLOBAL_ROLES:
            authority = self._by_authority_role[role]
            return (authority,)
        bit = ROLE_BITS[role]
        return tuple(lane for lane in self._lanes if lane.role_mask & bit)

    def resolve_role(self, role: str):
        return self.role_holders(role)

    def lanes_with_role(self, role: str) -> tuple[LaneRecord, ...]:
        if role not in ROLE_BITS:
            raise LaneRoleError(f"unknown role: {role!r}")
        if role in GLOBAL_ROLES:
            return ()
        bit = ROLE_BITS[role]
        return tuple(lane for lane in self._lanes if lane.role_mask & bit)

    def authority(self, role: str) -> GlobalAuthority:
        if role not in GLOBAL_ROLES:
            raise LaneRoleError(f"not a global authority role: {role!r}")
        return self._by_authority_role[role]

    @property
    def page_budget(self) -> _CallableDict:
        return _CallableDict(_plain(self._document["page_budget"]))

    @property
    def execution_identity(self) -> _CallableDict:
        return _CallableDict(execution_identity_document())

    def role_declarations(self) -> tuple[dict[str, Any], ...]:
        return tuple(_plain(entry) for entry in self._document["roles"])

    def validate(self) -> bool:
        validate_ruleset(self._document, require_digest=True)
        return True

    def health(self) -> dict[str, Any]:
        role_counts = {
            role: len(self.lanes_with_role(role)) for role in LANE_ROLES
        }
        authority_counts = {
            role: 1 if role in self._by_authority_role else 0
            for role in GLOBAL_ROLES
        }
        capability_counts = Counter(lane.capability_class for lane in self._lanes)
        fp_counts = Counter(lane.fp_policy for lane in self._lanes)
        return {
            "schema": HEALTH_SCHEMA,
            "status": "green",
            "healthy": True,
            "ruleset_id": self.ruleset_id,
            "version": self.version,
            "digest": str(self.digest),
            "lanes": len(self._lanes),
            "lane_count": len(self._lanes),
            "groups": len(self._groups),
            "group_count": len(self._groups),
            "lanes_per_group": LANES_PER_GROUP,
            "passes": PASS_COUNT,
            "pass_count": PASS_COUNT,
            "roles": role_counts,
            "global_authorities": authority_counts,
            "concurrency": self.concurrency,
            "active_runner_slots": self.active_runner_slots,
            "declared_logical_lanes": LANE_COUNT,
            "executing_lane_runs": EXECUTING_LANE_RUNS,
            "standby_slots_with_live_working_sets": STANDBY_SLOTS_WITH_LIVE_WORKING_SETS,
            "native_kernel_invocations_in_flight": NATIVE_KERNEL_INVOCATIONS_IN_FLIGHT,
            "active_execution_identity": self.execution_identity(),
            "state_model": self.state_model,
            "nannet0_ring_position": NANNET0_RING_POSITION,
            "nannet0_is_lane": False,
            "lane_255_rejected": True,
            "page_budget": self.page_budget(),
            "capability_classes": dict(sorted(capability_counts.items())),
            "fp_policies": dict(sorted(fp_counts.items())),
        }

    def summary(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "ruleset_id": self.ruleset_id,
            "version": self.version,
            "digest": str(self.digest),
            "lanes": len(self._lanes),
            "groups": len(self._groups),
            "lanes_per_group": LANES_PER_GROUP,
            "passes": PASS_COUNT,
            "concurrency": self.concurrency,
            "active_runner_slots": self.active_runner_slots,
            "nannet0_ring_position": NANNET0_RING_POSITION,
            "nannet0_is_lane": False,
            "health": self.health()["status"],
            "page_budget": self.page_budget(),
        }

    def lane_records(self) -> list[dict[str, Any]]:
        return [lane.to_dict() for lane in self._lanes]

    def group_records(self) -> list[dict[str, Any]]:
        return [group.to_dict() for group in self._groups]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._document)


__all__ = [
    "ACTIVE_RUNNER_SLOTS",
    "ALL_ROLE_MASK",
    "AUTHORITY_SCHEMA",
    "CAPABILITY_CLASS_NAMES",
    "CAPABILITY_CLASS_ROLES",
    "CONCURRENCY",
    "CRITICAL_ROLES",
    "Digest",
    "EXECUTING_LANE_RUNS",
    "FP_POLICIES",
    "FP_POLICY_NAMES",
    "GLOBAL_ROLES",
    "GLOBAL_ROLE_MASK",
    "GROUP_COUNT",
    "GROUP_SCHEMA",
    "GlobalAuthority",
    "HEALTH_SCHEMA",
    "HOME_PAGES_PER_LANE",
    "LANES_PER_GROUP",
    "LANE_COUNT",
    "LANE_HOME_BYTES",
    "LANE_HOME_PAGES",
    "LANE_ROLES",
    "LANE_ROLE_MASK",
    "LANE_ROLE_RANGES",
    "LANE_SCHEMA",
    "LANE_VERSION",
    "LaneBoundsError",
    "LaneDuplicateError",
    "Lane",
    "LaneGroup",
    "LanePolicyError",
    "LaneRecord",
    "LaneRegistry",
    "LaneRegistryError",
    "LaneRoleError",
    "NANNET0",
    "NANNET0_BYTES",
    "NANNET0_PAGE_KEY",
    "NANNET0_PAGES",
    "NANNET0_RING_POSITION",
    "NATIVE_KERNEL_INVOCATIONS_IN_FLIGHT",
    "PAGE_BYTES",
    "PAGE_BUDGET_SCHEMA",
    "PASS_COUNT",
    "RING_POSITIONS",
    "ROLES",
    "ROLE_BITS",
    "ROLE_CAPABILITY_CLASS",
    "ROLE_CRITICAL",
    "ROLE_FP_POLICY",
    "ROLE_MAX_FANOUT",
    "ROLE_SCOPES",
    "RULESET_ID",
    "RULESET_VERSION",
    "SCHEMA",
    "STANDBY_SLOTS_WITH_LIVE_WORKING_SETS",
    "UNIVERSE_BYTES",
    "UNIVERSE_PAGES",
    "build_ruleset",
    "canonical_json",
    "default_spec_path",
    "digest_document",
    "digest_object",
    "execution_identity_document",
    "group_key",
    "lane_key",
    "load_ruleset",
    "page_budget_document",
    "page_key",
    "role_for_lane",
    "role_mask",
    "roles_from_mask",
    "seal_ruleset",
    "validate_ruleset",
]
