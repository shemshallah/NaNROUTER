"""Host-control NMP packet and state projection.

NMP is the typed control-plane envelope that carries a selected mathematical
candidate through preflight, admission, queuing, execution, and evidence.  It
does not evaluate mathematics and it does not import an executor.  The durable
job/lease truth remains in ``WaveStore`` (MC0DB); this module only:

* validates and canonicalises packet records,
* enforces the NMP transition table,
* deduplicates content-identical operations in an explicitly in-memory table,
* builds parent/child batches without a parent lease,
* checks the execution gate, and
* projects packet state from WaveStore-like job/lease rows.

There is deliberately no private durable NMP table here.  A restarted process
must reconstruct state from the job/lease rows; :func:`project_packet` and
:meth:`NmpProjection.to_packet` do that without reading packet-owned state.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import json
import re
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

from .math_objects import canonical_json, digest_object
from .native_preflight_receipt import (
    NativePreflightLeaseBinding,
    NativePreflightReceipt,
    NativePreflightReceiptError,
)

NMP_SCHEMA = "nanrouter.nmp.v1"
JAHS_SEAL = "JAHS"

# The ring has 255 logical lane positions (0..254).  Position 255 is NANNET0,
# the meta/control position; it is not a lane and can never own a packet.
MAX_LANE = 254
NANNET0_LANE = 255
NANNET0 = NANNET0_LANE
LANE_COUNT = 255
LANES = LANE_COUNT

CREATED = "CREATED"
RESOLVED = "RESOLVED"
CLASSIFIED = "CLASSIFIED"
PROPOSED = "PROPOSED"
PREFLIGHTED = "PREFLIGHTED"
QUEUED = "QUEUED"
EXECUTING = "EXECUTING"
COMPLETED = "COMPLETED"
COMMITTED = "COMMITTED"

NULL = "NULL"
UNDEFINED = "UNDEFINED"
REJECTED = "REJECTED"
UNAVAILABLE = "UNAVAILABLE"
UNAUTHORIZED = "UNAUTHORIZED"
STALE = "STALE"
FAILED = "FAILED"
CANCELLED = "CANCELLED"

# GAME_PLAN_:: §9.3 also names INVALID and EXPERIMENTAL in the transition
# table.  They are kept as optional typed terminals for preflight results.
INVALID = "INVALID"
EXPERIMENTAL = "EXPERIMENTAL"

STATES = (
    CREATED,
    RESOLVED,
    CLASSIFIED,
    PROPOSED,
    PREFLIGHTED,
    QUEUED,
    EXECUTING,
    COMPLETED,
    COMMITTED,
)

TERMINAL_STATES = frozenset({
    NULL,
    UNDEFINED,
    REJECTED,
    UNAVAILABLE,
    UNAUTHORIZED,
    STALE,
    FAILED,
    CANCELLED,
})

# The canonical transition table also names INVALID and EXPERIMENTAL.  They
# are kept as optional typed preflight terminals, but the required terminal
# set above remains exactly the eight control outcomes.
OPTIONAL_TERMINAL_STATES = frozenset({INVALID, EXPERIMENTAL})
ALL_TERMINAL_STATES = TERMINAL_STATES | OPTIONAL_TERMINAL_STATES

# Backwards/explicit alias for consumers that want every terminal state.
REQUIRED_TERMINAL_STATES = TERMINAL_STATES

ALL_STATES = frozenset(STATES) | ALL_TERMINAL_STATES
SUCCESS_TERMINAL_STATES = frozenset({COMMITTED})

_PRE_EXECUTION_STATES = frozenset({CREATED, RESOLVED, CLASSIFIED, PROPOSED, PREFLIGHTED})

# The minimum transition table from GAME_PLAN_:: §9.3.  It is intentionally
# explicit rather than inferred: a state not listed has no outgoing edge.
TRANSITIONS = MappingProxyType({
    CREATED: frozenset({RESOLVED, REJECTED, CANCELLED}),
    RESOLVED: frozenset({CLASSIFIED, NULL, UNDEFINED, INVALID, CANCELLED}),
    CLASSIFIED: frozenset({PROPOSED, NULL, UNDEFINED, INVALID, CANCELLED}),
    PROPOSED: frozenset({PREFLIGHTED, NULL, REJECTED, CANCELLED}),
    PREFLIGHTED: frozenset({
        QUEUED, UNAVAILABLE, UNAUTHORIZED, STALE, EXPERIMENTAL, CANCELLED,
    }),
    QUEUED: frozenset({EXECUTING, CANCELLED, FAILED}),
    EXECUTING: frozenset({COMPLETED, FAILED, CANCELLED}),
    COMPLETED: frozenset({COMMITTED, FAILED}),
    COMMITTED: frozenset(),
    **{state: frozenset() for state in ALL_TERMINAL_STATES},
})

# A parent packet is a batch envelope, never executable work.
_BATCH_PARENT_FORBIDDEN_STATES = frozenset({QUEUED, EXECUTING, COMPLETED, COMMITTED})

_STATE_ORDER = {
    CREATED: 0,
    RESOLVED: 1,
    CLASSIFIED: 2,
    PROPOSED: 3,
    PREFLIGHTED: 4,
    QUEUED: 5,
    EXECUTING: 6,
    COMPLETED: 7,
    COMMITTED: 8,
}

_DIGEST_RE = re.compile(r"^(?:(?:sha256|pf):)?([0-9a-fA-F]{64})$")
_FUNCTION_RE = re.compile(r"^math\.[a-z0-9][a-z0-9_.-]{0,120}$")

_ADMISSION_FAILURE = {
    "VALID": None,
    "NULL": NULL,
    "UNDEFINED": UNDEFINED,
    "INVALID": REJECTED,
    "UNSUPPORTED": REJECTED,
    "UNKNOWN": REJECTED,
    "UNRECOGNIZED": REJECTED,
    "VOID": REJECTED,
    "UNAVAILABLE": UNAVAILABLE,
    "UNAUTHORIZED": UNAUTHORIZED,
    "STALE": STALE,
    "EXPERIMENTAL": EXPERIMENTAL,
}

_CAPABILITY_OK = frozenset({"native_verified"})
_CAPABILITY_DECLARED_OK = frozenset({"declared", "native_verified"})


class NmpError(ValueError):
    """Base error for invalid NMP control records."""


class NmpValidationError(NmpError):
    """A packet field violates the canonical record contract."""


class NmpLaneError(NmpValidationError):
    """A lane is outside 0..254 or names NANNET0."""


class NmpTransitionError(NmpError):
    """A transition is not in the closed NMP state table."""


class NmpGateError(NmpError):
    """The execution gate refused to authorize a packet."""

    def __init__(self, decision: "NmpGateDecision") -> None:
        self.decision = decision
        self.failure = decision.failure
        self.state = decision.failure
        super().__init__(f"{decision.failure}: {decision.reason}")


class NmpProjectionError(NmpError):
    """A job/lease projection cannot support a claimed packet state."""


class NmpBatchError(NmpError):
    """Invalid batch parent/child relationship."""


class NmpDedupeError(NmpError):
    """Invalid dedupe/in-flight operation."""


class NmpSealError(NmpError):
    """A batch seal was requested before all children were terminal."""


# ---------------------------------------------------------------------------
# Small canonical helpers
# ---------------------------------------------------------------------------


def _text(value: Any, name: str, *, maximum: int = 512, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise NmpValidationError(f"{name} must be a string")
    if not value and not allow_empty:
        raise NmpValidationError(f"{name} must be non-empty")
    if len(value) > maximum:
        raise NmpValidationError(f"{name} must be <= {maximum} characters")
    return value


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise NmpValidationError(f"{name} must be an integer >= {minimum}")
    return value


def normalize_digest(value: Any, name: str, *, allow_none: bool = False) -> str | None:
    """Return a bare 64-character lowercase SHA-256 digest.

    Both bare hex and the ``sha256:``/``pf:`` display prefixes are accepted.  Comparisons
    therefore never fail merely because one producer used the display prefix.
    """
    if value is None and allow_none:
        return None
    if not isinstance(value, str):
        raise NmpValidationError(f"{name} must be a SHA-256 digest")
    match = _DIGEST_RE.fullmatch(value.strip())
    if match is None:
        raise NmpValidationError(f"{name} must be 64 hex characters (optionally sha256:/pf: prefixed)")
    return match.group(1).lower()


def _snapshot_ref(value: Any, name: str) -> str:
    if isinstance(value, Mapping):
        for key in ("snapshot_id", "ruleset_snapshot_id", "digest", "ruleset_digest"):
            if value.get(key):
                return _snapshot_ref(value[key], name)
        raise NmpValidationError(f"{name} must carry a snapshot identifier")
    return _text(value, name, maximum=512)


def _tuple_of_dicts(value: Any, name: str) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, Mapping)):
        raise NmpValidationError(f"{name} must be a list of objects")
    result: list[dict[str, Any]] = []
    try:
        iterator = iter(value)
    except TypeError as exc:
        raise NmpValidationError(f"{name} must be a list of objects") from exc
    for entry in iterator:
        if not isinstance(entry, Mapping):
            raise NmpValidationError(f"{name} entries must be objects")
        result.append(dict(entry))
    return tuple(result)


def _object_dict(value: Any) -> dict[str, Any]:
    """Best-effort duck-typed conversion for math objects and rows."""
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        data = to_dict()
        if isinstance(data, Mapping):
            return dict(data)
    data = getattr(value, "__dict__", None)
    if isinstance(data, Mapping):
        return dict(data)
    raise NmpValidationError(f"expected an object record, got {type(value).__name__}")


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    if isinstance(row, Mapping):
        return row.get(key, default)
    keys = getattr(row, "keys", None)
    if callable(keys):
        try:
            if key in keys():
                return row[key]
        except (KeyError, TypeError):
            pass
    return getattr(row, key, default)


def _row_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, Mapping):
        return dict(row)
    keys = getattr(row, "keys", None)
    if callable(keys):
        try:
            return {str(key): row[key] for key in keys()}
        except (KeyError, TypeError):
            pass
    to_dict = getattr(row, "to_dict", None)
    if callable(to_dict):
        try:
            data = to_dict()
            if isinstance(data, Mapping):
                return dict(data)
        except Exception:  # pragma: no cover - defensive duck typing
            pass
    data = getattr(row, "__dict__", None)
    if isinstance(data, Mapping):
        return dict(data)
    return {}


def _payload(job: Any) -> dict[str, Any]:
    raw = _row_get(job, "payload_json")
    if isinstance(raw, Mapping):
        return dict(raw)
    if isinstance(raw, (str, bytes)):
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return dict(value) if isinstance(value, Mapping) else {}
    raw = _row_get(job, "payload")
    return dict(raw) if isinstance(raw, Mapping) else {}


def _job_value(job: Any, payload: Mapping[str, Any], *keys: str) -> Any:
    """Read a binding from a row field first, then from its payload."""
    for key in keys:
        value = _row_get(job, key)
        if value is not None:
            return value
    for key in keys:
        if payload.get(key) is not None:
            return payload[key]
    return None


def is_valid_lane(lane_id: Any) -> bool:
    return (
        isinstance(lane_id, int)
        and not isinstance(lane_id, bool)
        and 0 <= lane_id <= MAX_LANE
    )


def validate_lane(lane_id: Any) -> int:
    if isinstance(lane_id, bool) or not isinstance(lane_id, int):
        raise NmpLaneError("lane_id must be an integer")
    if lane_id == NANNET0_LANE:
        raise NmpLaneError(
            "lane 255 is NANNET0 (ring position 255), not a NMP lane; "
            f"valid lanes are 0..{MAX_LANE}"
        )
    if not 0 <= lane_id <= MAX_LANE:
        raise NmpLaneError(f"lane_id must be in 0..{MAX_LANE}")
    return lane_id


def _normalise_capability_set(value: Any) -> tuple[dict[str, Any], ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        value = (value,)
    elif isinstance(value, str):
        value = ({"required": value},)
    entries: list[dict[str, Any]] = []
    try:
        iterator = iter(value)
    except TypeError as exc:
        raise NmpValidationError("capability_set must be a collection") from exc
    for entry in iterator:
        if isinstance(entry, str):
            entries.append({"required": _text(entry, "capability", maximum=256)})
        elif isinstance(entry, Mapping):
            entries.append(dict(entry))
        else:
            raise NmpValidationError("capability_set entries must be objects or strings")
    # A capability *set* is order independent.  Sorting also makes the digest
    # stable across callers that enumerate requirements differently.
    entries.sort(key=canonical_json)
    return tuple(entries)


def _input_identity(entry: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("leaf_id", "version", "digest", "content_digest", "kind", "type")
    selected = {key: entry[key] for key in keys if key in entry}
    return selected or dict(entry)


def _candidate_fields(candidate: Any) -> dict[str, Any]:
    if candidate is None:
        return {}
    if isinstance(candidate, str):
        return {"candidate_id": candidate}
    data = _object_dict(candidate)
    return data


def _admission_fields(admission: Any) -> dict[str, Any]:
    if admission is None:
        return {}
    if isinstance(admission, str):
        return {"verdict": admission}
    return _object_dict(admission)


def _preflight_fields(preflight: Any) -> dict[str, Any]:
    if preflight is None:
        return {}
    if isinstance(preflight, str):
        return {"result": preflight}
    return _object_dict(preflight)


def _preflight_result(data: Mapping[str, Any]) -> str | None:
    value = data.get("result", data.get("verdict"))
    return value.upper() if isinstance(value, str) else None


# ---------------------------------------------------------------------------
# Dedupe identity
# ---------------------------------------------------------------------------


def dedupe_key_for(
    *,
    snapshot_id: str,
    function_id: str,
    function_version: int = 1,
    candidate_id: str = "",
    inputs: Iterable[Mapping[str, Any]] = (),
    base_generation: int = 0,
    ruleset_snapshot_id: str = "",
    numerical_policy: Mapping[str, Any] | None = None,
    capability_set: Any = (),
    commutative: bool = False,
) -> str:
    """Return the content-based operation key.

    The key deliberately excludes ``packet_id``, ``request_id``, lane, batch
    position, timestamps and state.  ``request_id`` is evidence, never an
    idempotency key.  A changed snapshot, function contract, ruleset snapshot,
    numerical policy or capability requirement produces a different key.
    """
    snapshot = _snapshot_ref(snapshot_id, "snapshot_id")
    function = _text(function_id, "function_id", maximum=256)
    _integer(function_version, "function_version", minimum=1)
    _integer(base_generation, "base_generation")
    identities = [_input_identity(entry) for entry in inputs]
    if commutative:
        identities.sort(key=canonical_json)
    capabilities = _normalise_capability_set(capability_set)
    payload = {
        "snapshot_id": snapshot,
        "base_generation": base_generation,
        "function_id": function,
        "function_version": function_version,
        # Candidate IDs are convenience identities.  When input identities are
        # available the operation key uses those, so two producers that name
        # the same content differently still deduplicate.
        "candidate_id": "" if identities else candidate_id,
        "inputs": identities,
        "ruleset_snapshot_id": ruleset_snapshot_id,
        "numerical_policy": dict(numerical_policy or {}),
        "capability_set": list(capabilities),
        "commutative": bool(commutative),
    }
    return digest_object(payload)


def packet_id_for(
    *,
    dedupe_key: str,
    lane_id: int = 0,
    batch_id: str | None = None,
    batch_index: int | None = None,
    candidate_id: str = "",
) -> str:
    """Derive a deterministic packet identity from content and placement.

    ``candidate_id`` is included so two selected candidates that resolve to the
    same operation content still have distinct packet records; they share a
    dedupe key and subscribe to one execution.  ``request_id`` is deliberately
    excluded because it is evidence, not identity.
    """
    validate_lane(lane_id)
    _text(dedupe_key, "dedupe_key", maximum=128)
    payload = {
        "schema": NMP_SCHEMA,
        "dedupe_key": dedupe_key,
        "candidate_id": candidate_id,
        "lane_id": lane_id,
        "batch_id": batch_id,
        "batch_index": batch_index,
    }
    return "nmp:" + digest_object(payload)


def batch_id_for(parent: "NmpPacket", children: Sequence["NmpPacket"]) -> str:
    """Content-based batch identity (parent + child operation keys)."""
    if not children:
        raise NmpBatchError("a batch requires at least one child")
    payload = {
        "schema": NMP_SCHEMA,
        "parent_packet_id": parent.packet_id,
        "snapshot_id": parent.snapshot_id,
        "base_generation": parent.base_generation,
        "children": [
            {
                "dedupe_key": child.dedupe_key,
                "candidate_id": child.candidate_id,
                "lane_id": child.lane_id,
            }
            for child in children
        ],
    }
    return "bch:" + digest_object(payload)


# ---------------------------------------------------------------------------
# Packet
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NmpPacket:
    """Immutable host-control packet.

    State changes return a new packet.  The canonical record carries only
    references and digests; payloads live in the math store.  No field holds a
    secret or a host-computed numeric result.
    """

    packet_id: str = ""
    snapshot_id: str = ""
    base_generation: int = 0
    generation: int | None = None
    lane_id: int = 0
    universe_id: str = "U0"
    function_id: str = ""
    function_version: int = 1
    candidate_id: str = ""
    inputs: tuple[dict[str, Any], ...] = ()
    admission_id: str | None = None
    admission_verdict: str | None = None
    preflight_digest: str | None = None
    preflight_result: str | None = None
    ruleset_id: str = ""
    ruleset_version: int = 1
    ruleset_snapshot_id: str = ""
    capability_set: tuple[dict[str, Any], ...] = ()
    capability_set_digest: str | None = None
    capability_epoch: int = 0
    guest_words: int = 0
    plan_digest: str | None = None
    numerical_policy: dict[str, Any] | None = None
    commutative: bool = False
    operation_id: str | None = None
    request_id: str | None = None
    cancel_epoch: int = 0
    state: str = CREATED
    result_digest: str | None = None
    result_status: str | None = None
    output_leaf_id: str | None = None
    output_kind: str = "scalar"
    job_id: str | None = None
    lease_epoch: int | None = None
    ring_incarnation: str | None = None
    ring_epoch: int | None = None
    jahs: str | None = JAHS_SEAL
    batch_id: str | None = None
    batch_index: int | None = None
    batch_count: int | None = None
    parent_packet_id: str | None = None
    child_packet_ids: tuple[str, ...] = ()
    is_batch_parent: bool = False
    reason: str | None = None
    failure_class: str | None = None
    provenance: dict[str, Any] | None = None
    evidence: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    created_tick: int = 0
    updated_tick: int = 0
    history: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        # Lane validation comes first so NANNET0/out-of-range cannot be hidden
        # behind another missing field.
        object.__setattr__(self, "lane_id", validate_lane(self.lane_id))
        object.__setattr__(self, "snapshot_id", _snapshot_ref(self.snapshot_id, "snapshot_id"))
        object.__setattr__(self, "base_generation", _integer(self.base_generation, "base_generation"))
        if self.generation is None:
            object.__setattr__(self, "generation", self.base_generation)
        else:
            object.__setattr__(self, "generation", _integer(self.generation, "generation"))
        if self.generation < self.base_generation:
            raise NmpValidationError("generation cannot be older than base_generation")

        object.__setattr__(self, "universe_id", _text(self.universe_id, "universe_id", maximum=128))
        object.__setattr__(self, "function_id", _text(self.function_id, "function_id", maximum=256))
        if not _FUNCTION_RE.fullmatch(self.function_id):
            raise NmpValidationError(
                "function_id must be a math.<family>.<name> identifier"
            )
        object.__setattr__(self, "function_version", _integer(self.function_version, "function_version", minimum=1))
        object.__setattr__(self, "candidate_id", _text(self.candidate_id, "candidate_id", maximum=256))
        object.__setattr__(self, "inputs", _tuple_of_dicts(self.inputs, "inputs"))

        for field_name in ("admission_id", "preflight_result", "request_id",
                           "output_leaf_id", "reason", "failure_class", "job_id",
                           "ring_incarnation", "jahs"):
            value = getattr(self, field_name)
            if value is not None:
                _text(value, field_name, maximum=512)
        if self.admission_verdict is not None:
            verdict = _text(self.admission_verdict, "admission_verdict", maximum=64).upper()
            object.__setattr__(self, "admission_verdict", verdict)
        if self.preflight_result is not None:
            result = _text(self.preflight_result, "preflight_result", maximum=64).upper()
            object.__setattr__(self, "preflight_result", result)

        object.__setattr__(self, "preflight_digest", normalize_digest(
            self.preflight_digest, "preflight_digest", allow_none=True,
        ))
        object.__setattr__(self, "plan_digest", normalize_digest(
            self.plan_digest, "plan_digest", allow_none=True,
        ))
        object.__setattr__(self, "result_digest", normalize_digest(
            self.result_digest, "result_digest", allow_none=True,
        ))
        if self.result_status is not None:
            object.__setattr__(self, "result_status", _text(self.result_status, "result_status", maximum=128))

        object.__setattr__(self, "capability_set", _normalise_capability_set(self.capability_set))
        computed_cap_digest = digest_object(list(self.capability_set))
        if self.capability_set_digest is None:
            object.__setattr__(self, "capability_set_digest", computed_cap_digest)
        else:
            supplied = normalize_digest(self.capability_set_digest, "capability_set_digest")
            if supplied != computed_cap_digest:
                raise NmpValidationError(
                    "capability_set_digest does not match the canonical capability_set"
                )
            object.__setattr__(self, "capability_set_digest", supplied)
        object.__setattr__(self, "capability_epoch", _integer(self.capability_epoch, "capability_epoch"))
        object.__setattr__(self, "guest_words", _integer(self.guest_words, "guest_words"))
        object.__setattr__(self, "cancel_epoch", _integer(self.cancel_epoch, "cancel_epoch"))
        object.__setattr__(self, "created_tick", _integer(self.created_tick, "created_tick"))
        object.__setattr__(self, "updated_tick", _integer(self.updated_tick, "updated_tick"))
        if self.lease_epoch is not None:
            object.__setattr__(self, "lease_epoch", _integer(self.lease_epoch, "lease_epoch", minimum=1))
        if self.ring_epoch is not None:
            object.__setattr__(self, "ring_epoch", _integer(self.ring_epoch, "ring_epoch"))
        if self.ring_incarnation is not None:
            object.__setattr__(self, "ring_incarnation", _text(self.ring_incarnation, "ring_incarnation", maximum=256))
        if self.ruleset_id:
            object.__setattr__(self, "ruleset_id", _text(self.ruleset_id, "ruleset_id", maximum=256))
        object.__setattr__(self, "ruleset_version", _integer(self.ruleset_version, "ruleset_version", minimum=1))
        object.__setattr__(self, "ruleset_snapshot_id", _text(
            self.ruleset_snapshot_id, "ruleset_snapshot_id", maximum=512, allow_empty=True,
        ))

        object.__setattr__(self, "numerical_policy", dict(self.numerical_policy or {}))
        object.__setattr__(self, "provenance", dict(self.provenance or {}))
        object.__setattr__(self, "evidence", dict(self.evidence or {}))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))
        object.__setattr__(self, "history", _tuple_of_dicts(self.history, "history"))
        object.__setattr__(self, "child_packet_ids", tuple(
            _text(item, "child_packet_id", maximum=512) for item in (self.child_packet_ids or ())
        ))
        object.__setattr__(self, "commutative", bool(self.commutative))

        state = _text(self.state, "state", maximum=32).upper()
        if state not in ALL_STATES:
            raise NmpValidationError(f"unknown NMP state: {state!r}")
        object.__setattr__(self, "state", state)

        if self.batch_index is not None:
            object.__setattr__(self, "batch_index", _integer(self.batch_index, "batch_index"))
        if self.batch_count is not None:
            object.__setattr__(self, "batch_count", _integer(self.batch_count, "batch_count", minimum=1))
        if self.batch_index is not None and self.batch_count is not None:
            if self.batch_index >= self.batch_count:
                raise NmpValidationError("batch_index must be < batch_count")
        if self.is_batch_parent:
            if self.parent_packet_id is not None:
                raise NmpValidationError("a batch parent cannot also be a batch child")
            if self.batch_index is not None:
                raise NmpValidationError("a batch parent has no batch_index")
            if self.job_id is not None or self.lease_epoch is not None:
                raise NmpValidationError("a batch parent must not hold a job or lease")
        elif self.parent_packet_id is not None:
            if not self.batch_id:
                raise NmpValidationError("a batch child requires batch_id")
            if self.batch_index is None or self.batch_count is None:
                raise NmpValidationError("a batch child requires batch_index and batch_count")
        elif self.batch_id or self.batch_index is not None or self.batch_count is not None:
            raise NmpValidationError(
                "batch fields require either is_batch_parent or parent_packet_id"
            )

        if not self.packet_id:
            object.__setattr__(self, "packet_id", packet_id_for(
                dedupe_key=self.dedupe_key,
                lane_id=self.lane_id,
                batch_id=self.batch_id,
                batch_index=self.batch_index,
                candidate_id=self.candidate_id,
            ))
        else:
            object.__setattr__(self, "packet_id", _text(self.packet_id, "packet_id", maximum=512))
        if not self.operation_id:
            object.__setattr__(self, "operation_id", "op:" + self.dedupe_key)
        else:
            object.__setattr__(self, "operation_id", _text(self.operation_id, "operation_id", maximum=512))

        if self.state == COMMITTED:
            self._require_commit_evidence()
        if (
            self.state in ALL_TERMINAL_STATES
            and self.state != FAILED
            and self.result_digest is not None
        ):
            raise NmpValidationError(
                f"{self.state} is a typed non-result terminal and cannot carry result_digest"
            )

    # -- canonical identity -------------------------------------------------

    @property
    def status(self) -> str:
        """Alias for ``state`` used by callers that call it packet status."""
        return self.state

    @property
    def admission(self) -> dict[str, Any]:
        return {
            "admission_id": self.admission_id,
            "verdict": self.admission_verdict,
            "snapshot_id": self.snapshot_id,
            "rule_snapshot_id": self.ruleset_snapshot_id or None,
            "preflight_digest": self.preflight_digest,
        }

    @property
    def preflight(self) -> dict[str, Any]:
        return {
            "result": self.preflight_result,
            "digest": self.preflight_digest,
            "rule_snapshot_id": self.ruleset_snapshot_id or None,
        }

    @property
    def ruleset(self) -> dict[str, Any]:
        return {
            "id": self.ruleset_id or None,
            "version": self.ruleset_version,
            "snapshot_id": self.ruleset_snapshot_id or None,
        }

    @property
    def capability(self) -> dict[str, Any]:
        return {
            "set": [dict(item) for item in self.capability_set],
            "digest": self.capability_set_digest,
            "epoch": self.capability_epoch,
        }

    @property
    def resources(self) -> dict[str, Any]:
        return {"guest_words": self.guest_words}

    @property
    def output(self) -> dict[str, Any]:
        return {
            "leaf_id": self.output_leaf_id,
            "digest": self.result_digest,
            "kind": self.output_kind,
            "status": self.result_status,
        }

    @property
    def ring(self) -> dict[str, Any]:
        return {
            "incarnation": self.ring_incarnation,
            "epoch": self.ring_epoch,
        }

    @property
    def dedupe_key(self) -> str:
        return dedupe_key_for(
            snapshot_id=self.snapshot_id,
            function_id=self.function_id,
            function_version=self.function_version,
            candidate_id=self.candidate_id,
            inputs=self.inputs,
            base_generation=self.base_generation,
            ruleset_snapshot_id=self.ruleset_snapshot_id,
            numerical_policy=self.numerical_policy,
            capability_set=self.capability_set,
            commutative=self.commutative,
        )

    @property
    def is_terminal(self) -> bool:
        return self.state in ALL_TERMINAL_STATES or self.state == COMMITTED

    @property
    def is_failure_terminal(self) -> bool:
        return self.state in ALL_TERMINAL_STATES

    @property
    def cancel_requested(self) -> bool:
        return bool(self.metadata.get("cancel_requested"))

    def _require_commit_evidence(self) -> None:
        if not self.result_digest:
            raise NmpValidationError("COMMITTED requires a result_digest")
        provenance = (
            bool(self.provenance)
            or bool(self.evidence.get("provenance"))
            or bool(self.evidence.get("job_id"))
            or bool(self.output_leaf_id)
        )
        if not provenance:
            raise NmpValidationError(
                "COMMITTED requires provenance (or an output leaf reference)"
            )
        if self.jahs != JAHS_SEAL:
            raise NmpValidationError("COMMITTED requires the JAHS handoff seal")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": NMP_SCHEMA,
            "packet_id": self.packet_id,
            "state": self.state,
            "status": self.state,
            "snapshot_id": self.snapshot_id,
            "base_generation": self.base_generation,
            "generation": self.generation,
            "lane_id": self.lane_id,
            "universe_id": self.universe_id,
            "parent_packet_id": self.parent_packet_id,
            "batch_id": self.batch_id,
            "batch_index": self.batch_index,
            "batch_count": self.batch_count,
            "child_packet_ids": list(self.child_packet_ids),
            "is_batch_parent": self.is_batch_parent,
            "operation_id": self.operation_id,
            "request_id": self.request_id,
            "function_id": self.function_id,
            "function_version": self.function_version,
            "candidate_id": self.candidate_id,
            "inputs": [dict(item) for item in self.inputs],
            "admission_id": self.admission_id,
            "admission_verdict": self.admission_verdict,
            "preflight_digest": self.preflight_digest,
            "preflight_result": self.preflight_result,
            "ruleset_snapshot_id": self.ruleset_snapshot_id or None,
            "capability_set": [dict(item) for item in self.capability_set],
            "capability_set_digest": self.capability_set_digest,
            "guest_words": self.guest_words,
            "cancel_epoch": self.cancel_epoch,
            "result_digest": self.result_digest,
            "ring_incarnation": self.ring_incarnation,
            "ring_epoch": self.ring_epoch,
            "jahs": self.jahs,
            "result_status": self.result_status,
            "preflight": {
                "result": self.preflight_result,
                "digest": self.preflight_digest,
                "rule_snapshot_id": self.ruleset_snapshot_id or None,
            },
            "ruleset": {
                "id": self.ruleset_id or None,
                "version": self.ruleset_version,
                "snapshot_id": self.ruleset_snapshot_id or None,
            },
            "capability": {
                "set": [dict(item) for item in self.capability_set],
                "digest": self.capability_set_digest,
                "epoch": self.capability_epoch,
            },
            "resources": {"guest_words": self.guest_words},
            "plan_digest": self.plan_digest,
            "numerical_policy": dict(self.numerical_policy),
            "commutative": self.commutative,
            "output": {
                "leaf_id": self.output_leaf_id,
                "digest": self.result_digest,
                "kind": self.output_kind,
                "status": self.result_status,
            },
            "evidence": {
                **dict(self.evidence),
                "job_id": self.job_id,
                "lease_epoch": self.lease_epoch,
                "ring_incarnation": self.ring_incarnation,
                "ring_epoch": self.ring_epoch,
                "result_status": self.result_status,
                "cancel_epoch": self.cancel_epoch,
                "jahs": self.jahs,
            },
            "provenance": dict(self.provenance),
            "reason": self.reason,
            "failure_class": self.failure_class,
            "created_tick": self.created_tick,
            "updated_tick": self.updated_tick,
            "history": [dict(item) for item in self.history],
            "metadata": dict(self.metadata),
        }

    def digest(self) -> str:
        return digest_object(self.to_dict())

    def append_evidence(self, **values: Any) -> "NmpPacket":
        """Append immutable evidence without changing packet state."""
        return replace(
            self,
            evidence={**dict(self.evidence), **values},
        )

    @classmethod
    def create(cls, **fields: Any) -> "NmpPacket":
        """Named constructor for callers that prefer an explicit factory."""
        return cls(**fields)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NmpPacket":
        """Rebuild a packet from canonical ``to_dict`` evidence.

        Unknown fields are ignored; the nested preflight/ruleset/capability/
        resources/output/evidence groups are flattened back to packet fields.
        """
        if not isinstance(data, Mapping):
            raise NmpValidationError("packet record must be an object")
        preflight = data.get("preflight") if isinstance(data.get("preflight"), Mapping) else {}
        ruleset = data.get("ruleset") if isinstance(data.get("ruleset"), Mapping) else {}
        capability = data.get("capability") if isinstance(data.get("capability"), Mapping) else {}
        resources = data.get("resources") if isinstance(data.get("resources"), Mapping) else {}
        output = data.get("output") if isinstance(data.get("output"), Mapping) else {}
        evidence = data.get("evidence") if isinstance(data.get("evidence"), Mapping) else {}
        known_evidence = {
            "job_id", "lease_epoch", "ring_incarnation", "ring_epoch",
            "result_status", "cancel_epoch", "jahs",
        }
        extra_evidence = {
            key: value for key, value in evidence.items()
            if key not in known_evidence
        }
        fields: dict[str, Any] = {
            "packet_id": data.get("packet_id", ""),
            "snapshot_id": data.get("snapshot_id", ""),
            "base_generation": data.get("base_generation", 0),
            "generation": data.get("generation"),
            "lane_id": data.get("lane_id", 0),
            "universe_id": data.get("universe_id", "U0"),
            "function_id": data.get("function_id", ""),
            "function_version": data.get("function_version", 1),
            "candidate_id": data.get("candidate_id", ""),
            "inputs": data.get("inputs", ()),
            "admission_id": data.get("admission_id"),
            "admission_verdict": data.get("admission_verdict"),
            "preflight_digest": preflight.get("digest", data.get("preflight_digest")),
            "preflight_result": preflight.get("result", data.get("preflight_result")),
            "ruleset_id": ruleset.get("id") or data.get("ruleset_id", ""),
            "ruleset_version": ruleset.get("version", data.get("ruleset_version", 1)),
            "ruleset_snapshot_id": (
                ruleset.get("snapshot_id")
                or preflight.get("rule_snapshot_id")
                or data.get("ruleset_snapshot_id")
                or ""
            ),
            "capability_set": capability.get("set", data.get("capability_set", ())),
            "capability_set_digest": capability.get("digest", data.get("capability_set_digest")),
            "capability_epoch": capability.get("epoch", data.get("capability_epoch", 0)),
            "guest_words": resources.get("guest_words", data.get("guest_words", 0)),
            "plan_digest": data.get("plan_digest"),
            "numerical_policy": data.get("numerical_policy", {}),
            "commutative": data.get("commutative", False),
            "operation_id": data.get("operation_id"),
            "request_id": data.get("request_id"),
            "cancel_epoch": evidence.get("cancel_epoch", data.get("cancel_epoch", 0)),
            "state": data.get("state", data.get("status", CREATED)),
            "result_digest": output.get("digest", data.get("result_digest")),
            "result_status": output.get("status", evidence.get("result_status")),
            "output_leaf_id": output.get("leaf_id", data.get("output_leaf_id")),
            "output_kind": output.get("kind", data.get("output_kind", "scalar")),
            "job_id": evidence.get("job_id", data.get("job_id")),
            "lease_epoch": evidence.get("lease_epoch", data.get("lease_epoch")),
            "ring_incarnation": evidence.get("ring_incarnation", data.get("ring_incarnation")),
            "ring_epoch": evidence.get("ring_epoch", data.get("ring_epoch")),
            "jahs": evidence.get("jahs", data.get("jahs")),
            "batch_id": data.get("batch_id"),
            "batch_index": data.get("batch_index"),
            "batch_count": data.get("batch_count"),
            "parent_packet_id": data.get("parent_packet_id"),
            "child_packet_ids": data.get("child_packet_ids", ()),
            "is_batch_parent": data.get("is_batch_parent", False),
            "reason": data.get("reason"),
            "failure_class": data.get("failure_class"),
            "provenance": data.get("provenance", {}),
            "evidence": extra_evidence,
            "metadata": data.get("metadata", {}),
            "created_tick": data.get("created_tick", 0),
            "updated_tick": data.get("updated_tick", 0),
            "history": data.get("history", ()),
        }
        return cls(**fields)

    # -- state machine ------------------------------------------------------

    def check_transition(
        self,
        next_state: str,
        *,
        result_digest: str | None = None,
        provenance: Mapping[str, Any] | None = None,
        output_leaf_id: str | None = None,
    ) -> str:
        state = _text(next_state, "next_state", maximum=32).upper()
        if state not in ALL_STATES:
            raise NmpTransitionError(f"unknown target state: {state!r}")
        if self.state in ALL_TERMINAL_STATES or self.state == COMMITTED:
            raise NmpTransitionError(
                f"{self.state} is terminal for packet {self.packet_id}"
            )
        if self.is_batch_parent and state in _BATCH_PARENT_FORBIDDEN_STATES:
            raise NmpTransitionError(
                "a batch parent is a control envelope and cannot be leased or executed"
            )
        allowed = TRANSITIONS[self.state]
        if state not in allowed:
            raise NmpTransitionError(
                f"invalid NMP transition {self.state} -> {state} "
                f"(allowed: {sorted(allowed)})"
            )
        if state == COMMITTED:
            # Validate the prospective record before it is constructed.
            if not (self.result_digest or result_digest):
                raise NmpTransitionError("COMMITTED requires a result_digest")
            if self.result_digest and result_digest is not None:
                try:
                    proposed_digest = normalize_digest(result_digest, "result_digest")
                except NmpValidationError as exc:
                    raise NmpTransitionError("COMMITTED result_digest is malformed") from exc
                if proposed_digest != self.result_digest:
                    raise NmpTransitionError(
                        "COMMITTED cannot replace the completed result digest"
                    )
            prospective_provenance = provenance is not None and bool(provenance)
            provenance_ok = (
                bool(self.provenance)
                or bool(self.evidence.get("provenance"))
                or bool(self.evidence.get("job_id"))
                or bool(self.output_leaf_id)
                or bool(output_leaf_id)
                or prospective_provenance
            )
            if not provenance_ok:
                raise NmpTransitionError(
                    "COMMITTED requires provenance (or an output leaf reference)"
                )
            if self.jahs != JAHS_SEAL:
                raise NmpTransitionError("COMMITTED requires the JAHS handoff seal")
        return state

    def can_transition(self, next_state: str, **kwargs: Any) -> bool:
        try:
            self.check_transition(next_state, **kwargs)
        except NmpTransitionError:
            return False
        return True

    def transition(
        self,
        next_state: str,
        *,
        reason: str | None = None,
        failure_class: str | None = None,
        tick: int = 0,
        result_digest: str | None = None,
        result_status: str | None = None,
        output_leaf_id: str | None = None,
        provenance: Mapping[str, Any] | None = None,
        job_id: str | None = None,
        lease_epoch: int | None = None,
        ring_incarnation: str | None = None,
        ring_epoch: int | None = None,
        evidence: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> "NmpPacket":
        """Return a new packet after one validated transition.

        This enforces the closed transition table and the COMMITTED evidence
        requirement.  Execution authorization is separate: use :meth:`queue`
        or :meth:`start_execution`, which require an :class:`NmpGateDecision`.
        """
        target = _text(next_state, "next_state", maximum=32).upper()
        self.check_transition(
            target,
            result_digest=result_digest,
            provenance=provenance,
            output_leaf_id=output_leaf_id,
        )
        if tick:
            _integer(tick, "tick")
        updates: dict[str, Any] = {
            "state": target,
            "updated_tick": tick or self.updated_tick,
        }
        if target == COMMITTED and result_digest is None:
            # COMMITTED may reuse the result already present on COMPLETED.
            result_digest = self.result_digest
        if result_digest is not None:
            updates["result_digest"] = result_digest
        if result_status is not None:
            updates["result_status"] = result_status
        elif target == COMPLETED and self.result_status is None:
            updates["result_status"] = "OK"
        if output_leaf_id is not None:
            updates["output_leaf_id"] = output_leaf_id
        if provenance is not None:
            updates["provenance"] = {**dict(self.provenance), **dict(provenance)}
        if job_id is not None:
            updates["job_id"] = job_id
        if lease_epoch is not None:
            updates["lease_epoch"] = lease_epoch
        if ring_incarnation is not None:
            updates["ring_incarnation"] = ring_incarnation
        if ring_epoch is not None:
            updates["ring_epoch"] = ring_epoch
        if evidence is not None:
            updates["evidence"] = {**dict(self.evidence), **dict(evidence)}
        if metadata is not None:
            updates["metadata"] = {**dict(self.metadata), **dict(metadata)}
        if reason is not None:
            updates["reason"] = reason
        if failure_class is not None:
            updates["failure_class"] = failure_class
        entry = {
            "from": self.state,
            "to": target,
            "reason": reason,
            "tick": tick or self.updated_tick,
            "cancel_epoch": self.cancel_epoch,
            "job_id": job_id if job_id is not None else self.job_id,
            "lease_epoch": lease_epoch if lease_epoch is not None else self.lease_epoch,
        }
        updates["history"] = self.history + (entry,)
        return replace(self, **updates)

    # Convenience transitions -------------------------------------------------

    def advance(self, next_state: str, **kwargs: Any) -> "NmpPacket":
        """Alias for :meth:`transition`."""
        return self.transition(next_state, **kwargs)

    transition_to = advance

    def resolve(self, **kwargs: Any) -> "NmpPacket":
        return self.transition(RESOLVED, **kwargs)

    def classify(self, **kwargs: Any) -> "NmpPacket":
        return self.transition(CLASSIFIED, **kwargs)

    def propose(self, **kwargs: Any) -> "NmpPacket":
        return self.transition(PROPOSED, **kwargs)

    def mark_preflight(
        self,
        *,
        result: str | None = None,
        digest: str | None = None,
        reason: str | None = None,
        receipt: NativePreflightReceipt | Mapping[str, Any] | None = None,
        admission: Any = None,
        **kwargs: Any,
    ) -> "NmpPacket":
        """Advance PROPOSED -> PREFLIGHTED; optionally bind a native guest receipt."""
        preflight_result = (result or self.preflight_result or "").upper()
        preflight_digest = digest or self.preflight_digest
        receipt_obj: NativePreflightReceipt | None = None
        admission_data = _admission_fields(admission) if admission is not None else {}
        if receipt is not None:
            try:
                receipt_obj = (
                    receipt if isinstance(receipt, NativePreflightReceipt)
                    else NativePreflightReceipt.from_dict(receipt)
                )
                receipt_obj.verify_packet(self)
            except NativePreflightReceiptError as exc:
                raise NmpTransitionError(f"native preflight receipt refused: {exc}") from exc
            if admission is None:
                raise NmpTransitionError("native preflight receipt requires a VALID admission record")
            if _preflight_result(admission_data) != "VALID":
                raise NmpTransitionError("native preflight receipt requires VALID admission")
            if admission_data.get("candidate_id") != self.candidate_id:
                raise NmpTransitionError("admission candidate does not match native receipt packet")
            if admission_data.get("snapshot_id") != self.snapshot_id:
                raise NmpTransitionError("admission snapshot does not match native receipt packet")
            admission_ruleset = admission_data.get("rule_snapshot_id") or admission_data.get("ruleset_snapshot_id")
            if admission_ruleset != self.ruleset_snapshot_id:
                raise NmpTransitionError("admission ruleset snapshot does not match native receipt packet")
            admission_digest = admission_data.get("preflight_digest")
            if admission_digest is not None and admission_digest != receipt_obj.receipt_digest:
                raise NmpTransitionError("admission digest does not match native receipt")
            if preflight_digest is not None and preflight_digest != receipt_obj.receipt_digest:
                raise NmpTransitionError("preflight digest does not match native receipt")
            preflight_digest = receipt_obj.receipt_digest
            preflight_result = "VALID"
        if preflight_result != "VALID":
            raise NmpTransitionError(
                f"preflight result {preflight_result or 'MISSING'!r} cannot authorize PREFLIGHTED"
            )
        if preflight_digest is None:
            raise NmpTransitionError("PREFLIGHTED requires a preflight digest")
        updates: dict[str, Any] = {
            "preflight_result": "VALID",
            "preflight_digest": preflight_digest,
        }
        if receipt_obj is not None:
            updates["admission_id"] = admission_data.get("admission_id")
            updates["admission_verdict"] = "VALID"
        if reason is not None:
            updates["reason"] = reason
        if receipt_obj is not None:
            updates["evidence"] = {
                **dict(self.evidence),
                "native_preflight_receipt": receipt_obj.to_dict(),
            }
            updates["metadata"] = {
                **dict(self.metadata),
                "native_preflight_required": True,
            }
        packet = replace(self, **updates)
        if "evidence" in kwargs and receipt_obj is not None:
            kwargs["evidence"] = {
                **dict(kwargs["evidence"] or {}),
                "native_preflight_receipt": receipt_obj.to_dict(),
            }
        if "metadata" in kwargs and receipt_obj is not None:
            kwargs["metadata"] = {
                **dict(kwargs["metadata"] or {}),
                "native_preflight_required": True,
            }
        return packet.transition(PREFLIGHTED, **kwargs)

    def bind_native_lease(
        self,
        job: Mapping[str, Any],
        lease: Mapping[str, Any],
        ring_snapshot: Mapping[str, Any],
        *,
        ring_incarnation: str,
    ) -> "NmpPacket":
        """Bind the stored native receipt to one active worker lease and ring epoch."""
        if not self.metadata.get("native_preflight_required"):
            raise NmpTransitionError("packet has no native preflight receipt requirement")
        receipt_data = self.evidence.get("native_preflight_receipt")
        if not isinstance(receipt_data, Mapping):
            raise NmpTransitionError("packet is missing its native preflight receipt")
        try:
            receipt_obj = NativePreflightReceipt.from_dict(receipt_data)
            binding = NativePreflightLeaseBinding.from_live_lease(
                self, receipt_obj, job, lease, ring_snapshot,
                ring_incarnation=ring_incarnation,
            )
        except NativePreflightReceiptError as exc:
            raise NmpTransitionError(f"native lease binding refused: {exc}") from exc
        return replace(
            self,
            evidence={
                **dict(self.evidence),
                "native_preflight_lease_binding": binding.to_dict(),
            },
        )

    def queue(
        self,
        *,
        gate: "NmpGateDecision" | None = None,
        tick: int = 0,
        **gate_kwargs: Any,
    ) -> "NmpPacket":
        """Gate then move PREFLIGHTED -> QUEUED.

        There is no unchecked queue path in this API.
        """
        decision = gate if gate is not None else execution_gate(self, **gate_kwargs)
        if not decision.ok:
            raise NmpGateError(decision)
        if decision.packet_id != self.packet_id:
            raise NmpGateError(NmpGateDecision(
                packet_id=self.packet_id,
                from_state=self.state,
                failure=REJECTED,
                reason="gate decision belongs to another packet",
            ))
        if decision.from_state != self.state:
            raise NmpGateError(NmpGateDecision(
                packet_id=self.packet_id,
                from_state=self.state,
                failure=STALE,
                reason=f"gate was evaluated at {decision.from_state}, packet is {self.state}",
            ))
        return self.transition(
            QUEUED,
            reason="execution gate accepted",
            tick=tick,
            evidence={"gate": decision.to_dict()},
        )

    def start_execution(
        self,
        *,
        gate: "NmpGateDecision" | None = None,
        lease_binding: NativePreflightLeaseBinding | Mapping[str, Any] | None = None,
        job_id: str | None = None,
        lease_epoch: int | None = None,
        ring_incarnation: str | None = None,
        ring_epoch: int | None = None,
        tick: int = 0,
        **gate_kwargs: Any,
    ) -> "NmpPacket":
        """Gate then move QUEUED -> EXECUTING at lease time."""
        decision = gate if gate is not None else execution_gate(self, **gate_kwargs)
        if not decision.ok:
            raise NmpGateError(decision)
        if decision.packet_id != self.packet_id:
            raise NmpGateError(NmpGateDecision(
                packet_id=self.packet_id,
                from_state=self.state,
                failure=REJECTED,
                reason="gate decision belongs to another packet",
            ))
        if decision.from_state != self.state:
            raise NmpGateError(NmpGateDecision(
                packet_id=self.packet_id,
                from_state=self.state,
                failure=STALE,
                reason=f"gate was evaluated at {decision.from_state}, packet is {self.state}",
            ))
        evidence = {"lease_gate": decision.to_dict()}
        transition_fields: dict[str, Any] = {}
        if self.metadata.get("native_preflight_required"):
            stored = self.evidence.get("native_preflight_lease_binding")
            if not isinstance(stored, Mapping):
                raise NmpGateError(NmpGateDecision(
                    packet_id=self.packet_id,
                    from_state=self.state,
                    failure=STALE,
                    reason="native preflight receipt has not been bound to a worker lease",
                ))
            try:
                stored_binding = NativePreflightLeaseBinding.from_dict(stored)
                supplied_binding = (
                    lease_binding if isinstance(lease_binding, NativePreflightLeaseBinding)
                    else NativePreflightLeaseBinding.from_dict(lease_binding)
                    if lease_binding is not None else stored_binding
                )
            except NativePreflightReceiptError as exc:
                raise NmpGateError(NmpGateDecision(
                    packet_id=self.packet_id,
                    from_state=self.state,
                    failure=STALE,
                    reason=f"native lease binding is malformed: {exc}",
                )) from exc
            if supplied_binding.binding_digest != stored_binding.binding_digest:
                raise NmpGateError(NmpGateDecision(
                    packet_id=self.packet_id,
                    from_state=self.state,
                    failure=STALE,
                    reason="supplied lease binding differs from the packet-bound receipt",
                ))
            if stored_binding.packet_id != self.packet_id or stored_binding.candidate_id != self.candidate_id:
                raise NmpGateError(NmpGateDecision(
                    packet_id=self.packet_id,
                    from_state=self.state,
                    failure=STALE,
                    reason="native lease binding belongs to another packet/candidate",
                ))
            receipt_data = self.evidence.get("native_preflight_receipt")
            try:
                receipt_obj = NativePreflightReceipt.from_dict(receipt_data)
            except NativePreflightReceiptError as exc:
                raise NmpGateError(NmpGateDecision(
                    packet_id=self.packet_id,
                    from_state=self.state,
                    failure=STALE,
                    reason=f"native receipt is unavailable at lease start: {exc}",
                )) from exc
            if (
                stored_binding.receipt_digest != receipt_obj.receipt_digest
                or stored_binding.output_generation != receipt_obj.output_generation
                or stored_binding.cancel_epoch != self.cancel_epoch
            ):
                raise NmpGateError(NmpGateDecision(
                    packet_id=self.packet_id,
                    from_state=self.state,
                    failure=STALE,
                    reason="native lease binding no longer matches receipt/output/cancel epoch",
                ))
            for name, supplied, expected in (
                ("job_id", job_id, stored_binding.job_id),
                ("lease_epoch", lease_epoch, stored_binding.lease_epoch),
                ("ring_incarnation", ring_incarnation, stored_binding.ring_incarnation),
                ("ring_epoch", ring_epoch, stored_binding.ring_epoch),
            ):
                if supplied is not None and supplied != expected:
                    raise NmpGateError(NmpGateDecision(
                        packet_id=self.packet_id,
                        from_state=self.state,
                        failure=STALE,
                        reason=f"native lease {name} changed after receipt binding",
                    ))
            transition_fields = {
                "job_id": stored_binding.job_id,
                "lease_epoch": stored_binding.lease_epoch,
                "ring_incarnation": stored_binding.ring_incarnation,
                "ring_epoch": stored_binding.ring_epoch,
            }
            evidence["native_preflight_lease_binding"] = stored_binding.to_dict()
        return self.transition(
            EXECUTING,
            reason="lease gate accepted",
            tick=tick,
            evidence=evidence,
            **transition_fields,
        )

    def complete(
        self,
        result_digest: str,
        *,
        result_status: str = "OK",
        output_leaf_id: str | None = None,
        evidence: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> "NmpPacket":
        return self.transition(
            COMPLETED,
            result_digest=result_digest,
            result_status=result_status,
            output_leaf_id=output_leaf_id,
            evidence=evidence,
            **kwargs,
        )

    def commit(
        self,
        *,
        result_digest: str | None = None,
        output_leaf_id: str | None = None,
        provenance: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> "NmpPacket":
        return self.transition(
            COMMITTED,
            result_digest=result_digest,
            output_leaf_id=output_leaf_id,
            provenance=provenance,
            **kwargs,
        )

    def fail(self, reason: str = "execution failed", *,
             failure_class: str = "EXECUTION_FAILED",
             **kwargs: Any) -> "NmpPacket":
        return self.transition(FAILED, reason=reason, failure_class=failure_class, **kwargs)

    # -- gate ---------------------------------------------------------------

    def execution_gate(self, **kwargs: Any) -> "NmpGateDecision":
        return execution_gate(self, **kwargs)

    # Common names for the same side-effect-free check.
    def gate(self, **kwargs: Any) -> "NmpGateDecision":
        return execution_gate(self, **kwargs)

    def can_execute(self, **kwargs: Any) -> bool:
        return execution_gate(self, **kwargs).ok

    def require_executable(self, **kwargs: Any) -> None:
        decision = execution_gate(self, **kwargs)
        if not decision.ok:
            raise NmpGateError(decision)

    assert_executable = require_executable

    # -- cancellation (cooperative, plan-step granularity) -------------------

    def request_cancel(
        self,
        *,
        epoch: int | None = None,
        reason: str = "cancelled",
        tick: int = 0,
        job: Any = None,
        lease: Any = None,
        plan_step: int | None = None,
    ) -> "NmpCancellation":
        """Request cancellation without claiming hard preemption.

        * Before a lease: the packet is CANCELLED immediately.
        * After a lease / while executing: the cancel epoch advances and the
          packet stays EXECUTING until :meth:`acknowledge_cancel` observes a
          plan-step boundary.
        * After the job is done: cancellation is too late; the result stands.
        """
        _text(reason, "reason", maximum=512)
        _integer(tick, "tick")
        if plan_step is not None:
            _integer(plan_step, "plan_step")
        job_state = str(_row_get(job, "state", "") or "").lower()
        if self.state in (COMPLETED, COMMITTED) or job_state == "done":
            return NmpCancellation(
                packet=self,
                status="too_late",
                reason="job result already exists; cancellation cannot replace it",
                cancel_epoch=self.cancel_epoch,
                action="result_stands",
            )
        if self.state in ALL_TERMINAL_STATES:
            return NmpCancellation(
                packet=self,
                status="terminal",
                reason=f"packet is already terminal ({self.state})",
                cancel_epoch=self.cancel_epoch,
                action="none",
            )
        if job_state in {"failed", "dead"}:
            return NmpCancellation(
                packet=self,
                status="terminal",
                reason=f"job is already {job_state}; cancellation is too late",
                cancel_epoch=self.cancel_epoch,
                action="none",
            )

        if epoch is None:
            next_epoch = self.cancel_epoch + 1
        else:
            next_epoch = _integer(epoch, "cancel_epoch", minimum=1)
            if next_epoch < self.cancel_epoch:
                raise NmpValidationError("cancel_epoch cannot move backwards")
            if next_epoch == self.cancel_epoch:
                # Idempotent repeat of the current cancellation request.
                if self.state == CANCELLED:
                    return NmpCancellation(
                        packet=self, status="cancelled", reason=reason,
                        cancel_epoch=self.cancel_epoch, action="cancel_queued_job",
                    )
                return NmpCancellation(
                    packet=self, status="requested", reason=reason,
                    cancel_epoch=self.cancel_epoch,
                    action="cooperative_plan_step",
                )

        metadata = {
            **dict(self.metadata),
            "cancel_requested": True,
            "cancel_reason": reason,
        }
        if plan_step is not None:
            metadata["cancel_plan_step"] = plan_step
        requested = replace(
            self,
            cancel_epoch=next_epoch,
            updated_tick=tick or self.updated_tick,
            metadata=metadata,
            evidence={
                **dict(self.evidence),
                "cancel": {
                    "epoch": next_epoch,
                    "reason": reason,
                    "cooperative": True,
                    "plan_step_granularity": True,
                    "hard_preemption": False,
                },
            },
        )

        leased = job_state == "leased" or (
            _row_get(lease, "state") == "active"
        )
        if leased:
            if _row_get(lease, "state") in {"completed"} or job_state == "done":
                return NmpCancellation(
                    packet=requested,
                    status="too_late",
                    reason="lease completed before cancellation was observed",
                    cancel_epoch=next_epoch,
                    action="result_stands",
                )
            return NmpCancellation(
                packet=requested,
                status="requested",
                reason=reason,
                cancel_epoch=next_epoch,
                action="cooperative_plan_step",
            )

        if self.state in _PRE_EXECUTION_STATES or self.state == QUEUED:
            action = "cancel_before_enqueue" if self.state != QUEUED else "cancel_queued_job"
            cancelled = requested.transition(
                CANCELLED,
                reason=reason,
                tick=tick,
                evidence={"cancel_status": "cancelled_before_execution"},
            )
            return NmpCancellation(
                packet=cancelled,
                status="cancelled",
                reason=reason,
                cancel_epoch=next_epoch,
                action=action,
            )

        # EXECUTING without a lease row: remain cooperative.  The caller must
        # acknowledge at a plan-step boundary before the state becomes
        # CANCELLED.
        return NmpCancellation(
            packet=requested,
            status="requested",
            reason=reason,
            cancel_epoch=next_epoch,
            action="cooperative_plan_step",
        )

    def acknowledge_cancel(
        self,
        *,
        tick: int = 0,
        plan_step: int | None = None,
        job: Any = None,
        lease: Any = None,
        reason: str = "cancelled at plan-step boundary",
    ) -> "NmpCancellation":
        """Apply a previously requested cancellation at a plan-step boundary."""
        _text(reason, "reason", maximum=512)
        _integer(tick, "tick")
        if plan_step is not None:
            _integer(plan_step, "plan_step")
        job_state = str(_row_get(job, "state", "") or "").lower()
        if self.state == CANCELLED:
            return NmpCancellation(
                packet=self, status="cancelled", reason=reason,
                cancel_epoch=self.cancel_epoch, action="none",
            )
        if self.state in (COMPLETED, COMMITTED) or job_state == "done":
            return NmpCancellation(
                packet=self, status="too_late",
                reason="job completed before the cancellation boundary",
                cancel_epoch=self.cancel_epoch, action="result_stands",
            )
        if self.state not in (EXECUTING, QUEUED):
            return NmpCancellation(
                packet=self, status="terminal" if self.is_terminal else "not_requested",
                reason=f"packet is {self.state}", cancel_epoch=self.cancel_epoch,
                action="none",
            )
        if not self.cancel_requested:
            return NmpCancellation(
                packet=self, status="not_requested",
                reason="no cancellation epoch has been requested",
                cancel_epoch=self.cancel_epoch, action="none",
            )
        if _row_get(lease, "state") in {"completed"}:
            return NmpCancellation(
                packet=self, status="too_late",
                reason="lease completed before the cancellation boundary",
                cancel_epoch=self.cancel_epoch, action="result_stands",
            )
        evidence = {
            "cancel_status": "cancelled_at_plan_step",
            "cancel_plan_step": plan_step,
        }
        cancelled = self.transition(
            CANCELLED,
            reason=reason,
            tick=tick,
            evidence=evidence,
            metadata={"cancel_acknowledged": True},
        )
        return NmpCancellation(
            packet=cancelled,
            status="cancelled",
            reason=reason,
            cancel_epoch=self.cancel_epoch,
            action="cooperative_plan_step",
        )

    def cancel(self, **kwargs: Any) -> "NmpCancellation":
        """Alias for :meth:`request_cancel`."""
        return self.request_cancel(**kwargs)

    cancel_request = cancel

    # -- result binding -----------------------------------------------------

    def accepts_result(
        self,
        *,
        snapshot_id: str | None = None,
        ruleset_snapshot_id: str | None = None,
        result_digest: str | None = None,
        result_generation: int | None = None,
        generation: int | None = None,
        allow_newer: bool = False,
    ) -> bool:
        """Check snapshot/generation equality for an incoming result."""
        try:
            return self._check_result(
                snapshot_id=snapshot_id,
                ruleset_snapshot_id=ruleset_snapshot_id,
                result_digest=result_digest,
                result_generation=result_generation,
                generation=generation,
                allow_newer=allow_newer,
            )
        except NmpError:
            return False

    def _check_result(
        self,
        *,
        snapshot_id: str | None = None,
        ruleset_snapshot_id: str | None = None,
        result_digest: str | None = None,
        result_generation: int | None = None,
        generation: int | None = None,
        allow_newer: bool = False,
    ) -> bool:
        if snapshot_id is not None and snapshot_id != self.snapshot_id:
            raise NmpProjectionError("result belongs to another snapshot")
        if ruleset_snapshot_id is not None and self.ruleset_snapshot_id and (
            ruleset_snapshot_id != self.ruleset_snapshot_id
        ):
            raise NmpProjectionError("result belongs to another ruleset snapshot")
        if generation is not None:
            _integer(generation, "generation")
            if generation < self.base_generation:
                raise NmpProjectionError("result generation is older than the packet")
            if generation != self.generation and not allow_newer:
                raise NmpProjectionError("result generation is not the packet generation")
        if result_generation is not None:
            _integer(result_generation, "result_generation")
            expected_generation = self.generation if generation is None else generation
            if result_generation != expected_generation and not allow_newer:
                raise NmpProjectionError("result generation is not the job generation")
        if result_digest is not None and self.result_digest is not None:
            if normalize_digest(result_digest, "result_digest") != self.result_digest:
                raise NmpProjectionError("result digest does not match the committed result")
        return True


@dataclass(frozen=True)
class NmpCancellation:
    """Outcome of a cancellation request or acknowledgement."""

    packet: NmpPacket
    status: str
    reason: str | None = None
    cancel_epoch: int = 0
    cooperative: bool = True
    plan_step_granularity: bool = True
    hard_preemption: bool = False
    action: str = "none"

    @property
    def state(self) -> str:
        return self.packet.state

    @property
    def cancelled(self) -> bool:
        return self.status == "cancelled"

    @property
    def pending(self) -> bool:
        return self.status == "requested"

    @property
    def too_late(self) -> bool:
        return self.status == "too_late"

    def __getattr__(self, name: str) -> Any:
        # Keep cancellation results convenient to treat as the resulting
        # packet without duplicating fields.
        return getattr(self.packet, name)

    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet.packet_id,
            "state": self.state,
            "status": self.status,
            "reason": self.reason,
            "cancel_epoch": self.cancel_epoch,
            "cooperative": self.cooperative,
            "plan_step_granularity": self.plan_step_granularity,
            "hard_preemption": self.hard_preemption,
            "action": self.action,
        }


NmpCancellationResult = NmpCancellation


# ---------------------------------------------------------------------------
# Execution gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NmpGateDecision:
    packet_id: str
    from_state: str
    ok: bool = False
    failure: str | None = None
    reason: str | None = None
    checks: Mapping[str, bool] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "checks", dict(self.checks or {}))
        if self.ok and self.failure is not None:
            raise NmpValidationError("an accepted gate decision cannot carry a failure")
        if not self.ok and self.failure is None:
            raise NmpValidationError("a refused gate decision requires a typed failure")
        if self.failure is not None and self.failure not in ALL_TERMINAL_STATES:
            raise NmpValidationError(f"unknown gate failure state: {self.failure!r}")

    @property
    def allowed(self) -> bool:
        return self.ok

    def __bool__(self) -> bool:
        return self.ok

    @property
    def state(self) -> str:
        return self.failure if not self.ok else self.from_state

    @property
    def status(self) -> str:
        return "VALID" if self.ok else str(self.failure)

    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "from_state": self.from_state,
            "ok": self.ok,
            "failure": self.failure,
            "reason": self.reason,
            "checks": dict(self.checks or {}),
        }


def _admission_verdict(admission: Any) -> tuple[str | None, dict[str, Any]]:
    data = _admission_fields(admission)
    verdict = data.get("verdict", data.get("result"))
    return (str(verdict).upper() if verdict is not None else None), data


def _external_digest(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        for key in ("digest", "preflight_digest", "snapshot_id"):
            if value.get(key) is not None:
                try:
                    return normalize_digest(value[key], "digest", allow_none=True)
                except NmpValidationError:
                    return str(value[key])
        return None
    try:
        return normalize_digest(value, "digest", allow_none=True)
    except NmpValidationError:
        return str(value)


def _capability_rows(capability: Any) -> list[dict[str, Any]]:
    if capability is None:
        return []
    if isinstance(capability, Mapping):
        return [dict(capability)]
    rows = []
    try:
        iterator = iter(capability)
    except TypeError as exc:
        raise NmpValidationError("capability must be a row or a list of rows") from exc
    for row in iterator:
        if not isinstance(row, Mapping):
            raise NmpValidationError("capability rows must be objects")
        rows.append(dict(row))
    return rows


def _normalise_requirement(requirement: Any) -> dict[str, Any]:
    if isinstance(requirement, str):
        return {"required": requirement}
    if isinstance(requirement, Mapping):
        return dict(requirement)
    raise NmpValidationError("capability requirement must be an object or string")


def _requirement_names(requirement: Mapping[str, Any]) -> tuple[str, ...]:
    names = []
    for key in ("required", "kernel_id", "implementation_id", "function_id"):
        value = requirement.get(key)
        if isinstance(value, str) and value:
            names.append(value)
    return tuple(names)


def _row_names(row: Mapping[str, Any]) -> tuple[str, ...]:
    names = []
    for key in ("kernel_id", "required", "implementation_id", "function_id"):
        value = row.get(key)
        if isinstance(value, str) and value:
            names.append(value)
    return tuple(names)


def _match_capability(requirement: Mapping[str, Any],
                      rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    names = _requirement_names(requirement)
    if not names:
        return rows[0] if len(rows) == 1 else None
    # A caller may hand the gate one already-selected capability row without
    # repeating its kernel id.  That is still an explicit capability decision.
    if len(rows) == 1 and not _row_names(rows[0]):
        return rows[0]
    for row in rows:
        row_names = _row_names(row)
        if any(
            name == row_name or name in row_name or row_name in name
            for name in names
            for row_name in row_names
        ):
            return row
    return None


def _capability_epoch_ok(packet: NmpPacket, row: Mapping[str, Any]) -> tuple[bool, str | None]:
    required = int(packet.capability_epoch or 0)
    if required <= 0:
        return True, None
    if row.get("epoch") is None:
        return False, "capability row does not declare an epoch"
    row_epoch = row.get("epoch")
    if isinstance(row_epoch, bool) or not isinstance(row_epoch, int):
        return False, "capability epoch is not an integer"
    if row_epoch < required:
        return False, "capability epoch is older than the packet snapshot"
    return True, None


def _check_capabilities(
    packet: NmpPacket,
    capability: Any,
    *,
    required_capability: Any = None,
    workspace: int | None = None,
    allow_declared: bool = False,
) -> tuple[bool, str | None, str | None]:
    """Return (available, failure_state, reason)."""
    requirements: list[dict[str, Any]] = []
    if required_capability is not None:
        requirements.append(_normalise_requirement(required_capability))
    requirements.extend(dict(item) for item in packet.capability_set)
    if not requirements:
        requirements.append({"required": packet.function_id})
    if packet.guest_words <= 0:
        return False, UNAVAILABLE, "packet declares no guest workspace"
    rows = _capability_rows(capability)
    if not rows:
        return False, UNAVAILABLE, "no capability row is available for this operation"
    required_workspace = max(
        int(packet.guest_words or 0),
        int(workspace or 0),
        max((int(item.get("workspace") or 0) for item in requirements), default=0),
    )
    allowed_status = _CAPABILITY_DECLARED_OK if allow_declared else _CAPABILITY_OK
    for requirement in requirements:
        row = _match_capability(requirement, rows)
        if row is None:
            return False, UNAVAILABLE, "required capability is not in the dispatchable set"
        if row.get("available") is False:
            return False, UNAVAILABLE, "capability row is marked unavailable"
        status = row.get("status")
        if status is None:
            # A row with no lifecycle status is only usable if it carries a
            # verified digest, keeping the default fail-closed.
            if not (row.get("verified_digest") or row.get("digest")):
                return False, UNAVAILABLE, "capability row is not verified"
        elif str(status).lower() not in allowed_status:
            return False, UNAVAILABLE, f"capability status is {status!r}"
        row_workspace = row.get("workspace", row.get("guest_words", 0))
        if isinstance(row_workspace, bool) or not isinstance(row_workspace, int):
            return False, UNAVAILABLE, "capability workspace is not an integer"
        if row_workspace < required_workspace:
            return False, UNAVAILABLE, (
                f"capability workspace {row_workspace} < required {required_workspace}"
            )
        requirement_digest = requirement.get("verified_digest", requirement.get("digest"))
        if requirement_digest is not None:
            try:
                expected = normalize_digest(requirement_digest, "verified_digest")
            except NmpValidationError:
                return False, UNAVAILABLE, "capability requirement digest is malformed"
            actual = row.get("verified_digest", row.get("digest"))
            try:
                actual_normalized = normalize_digest(actual, "verified_digest")
            except NmpValidationError:
                return False, UNAVAILABLE, "capability row digest is malformed"
            if expected != actual_normalized:
                return False, UNAVAILABLE, "capability digest does not match"
        requirement_runner = requirement.get("runner_id", requirement.get("selected_runner"))
        if requirement_runner is not None and row.get("runner_id") not in (
            requirement_runner, None
        ):
            return False, UNAVAILABLE, "capability runner does not match"
        requirement_precision = requirement.get("precision")
        if requirement_precision is not None and row.get("precision") not in (
            requirement_precision, None
        ):
            return False, UNAVAILABLE, "capability precision does not match"
        epoch_ok, epoch_reason = _capability_epoch_ok(packet, row)
        if not epoch_ok:
            return False, STALE, epoch_reason
    return True, None, None


def _admission_gate(
    packet: NmpPacket,
    admission: Any,
    preflight: Any,
) -> tuple[bool, str | None, str | None, dict[str, Any]]:
    """Check admission and preflight evidence.  Returns (ok, failure, reason, data)."""
    external_admission = _admission_fields(admission)
    verdict, _admission_data = _admission_verdict(admission)
    if verdict is None:
        verdict = packet.admission_verdict
    # The packet's own bound evidence cannot be overridden by a caller note.
    if packet.admission_verdict is not None and packet.admission_verdict != "VALID":
        failure = _ADMISSION_FAILURE.get(packet.admission_verdict, REJECTED)
        return False, failure, (
            f"packet-bound admission verdict is {packet.admission_verdict}"
        ), external_admission
    if packet.preflight_result is not None and packet.preflight_result != "VALID":
        return False, REJECTED, (
            f"packet-bound preflight result is {packet.preflight_result}"
        ), external_admission
    if verdict is None:
        return False, REJECTED, "a VALID admission record is required", external_admission
    if verdict != "VALID":
        failure = _ADMISSION_FAILURE.get(verdict, REJECTED)
        return False, failure, f"admission verdict is {verdict}", external_admission

    admission_id = external_admission.get("admission_id")
    if admission_id and packet.admission_id:
        if str(admission_id) != packet.admission_id:
            return False, REJECTED, "admission_id does not match the packet", external_admission
    admission_candidate = external_admission.get("candidate_id")
    if admission_candidate and str(admission_candidate) != packet.candidate_id:
        return False, REJECTED, "admission candidate does not match the packet", external_admission
    admission_snapshot = external_admission.get("snapshot_id")
    if admission_snapshot and str(admission_snapshot) != packet.snapshot_id:
        return False, STALE, "admission was issued for another snapshot", external_admission
    admission_ruleset = (
        external_admission.get("rule_snapshot_id")
        or external_admission.get("ruleset_snapshot_id")
    )
    if admission_ruleset and packet.ruleset_snapshot_id and (
        str(admission_ruleset) != packet.ruleset_snapshot_id
    ):
        return False, STALE, "admission was issued for another ruleset snapshot", external_admission

    external_preflight = _preflight_fields(preflight)
    preflight_result = _preflight_result(external_preflight)
    if preflight_result is None:
        preflight_result = packet.preflight_result
    if preflight_result != "VALID":
        return False, REJECTED, (
            f"preflight result {preflight_result or 'MISSING'!r} is not VALID"
        ), external_admission
    if not packet.preflight_digest:
        return False, REJECTED, "packet has no preflight digest", external_admission
    external_digest = external_preflight.get("digest") or external_preflight.get("preflight_digest")
    if external_digest is not None:
        try:
            normalized = normalize_digest(external_digest, "preflight_digest")
        except NmpValidationError:
            return False, STALE, "preflight digest is malformed", external_admission
        if normalized != packet.preflight_digest:
            return False, STALE, "preflight digest does not match the packet", external_admission
    admission_preflight = external_admission.get("preflight_digest")
    if admission_preflight:
        try:
            normalized = normalize_digest(admission_preflight, "preflight_digest")
        except NmpValidationError:
            return False, STALE, "admission preflight digest is malformed", external_admission
        if packet.preflight_digest and normalized != packet.preflight_digest:
            return False, STALE, "admission preflight digest does not match", external_admission
    return True, None, None, external_admission


def _ruleset_gate(packet: NmpPacket, ruleset_snapshot: Any) -> tuple[bool, str | None, str | None]:
    if not packet.ruleset_snapshot_id:
        return False, STALE, "packet is not bound to a ruleset snapshot"
    if ruleset_snapshot is None:
        return True, None, None
    try:
        current = _snapshot_ref(ruleset_snapshot, "ruleset_snapshot")
    except NmpValidationError:
        return False, STALE, "ruleset snapshot reference is malformed"
    if current != packet.ruleset_snapshot_id:
        return False, STALE, "ruleset snapshot changed after admission"
    return True, None, None


def _ring_gate(
    packet: NmpPacket,
    ring_incarnation: Any,
    ring_epoch: Any,
) -> tuple[bool, str | None, str | None]:
    if not packet.ring_incarnation:
        return False, STALE, "packet is not bound to a ring incarnation"
    if packet.ring_epoch is None or packet.ring_epoch < 1:
        return False, STALE, "packet is not bound to an activated ring epoch"
    if ring_incarnation is not None and str(ring_incarnation) != packet.ring_incarnation:
        return False, STALE, "ring incarnation changed"
    if ring_epoch is not None:
        if isinstance(ring_epoch, bool) or not isinstance(ring_epoch, int):
            return False, STALE, "ring epoch is not an integer"
        if ring_epoch != packet.ring_epoch:
            return False, STALE, "ring epoch changed"
    return True, None, None


def _job_gate(
    packet: NmpPacket,
    job: Any,
    lease: Any,
    *,
    now_tick: int | None,
) -> tuple[bool, str | None, str | None]:
    if job is None and lease is None:
        return True, None, None
    job_state = str(_row_get(job, "state", "") or "").lower()
    if job_state not in {"", "queued", "leased"}:
        failure = CANCELLED if job_state == "failed" and _is_cancelled_job(job) else FAILED
        if job_state == "done":
            failure = STALE
        return False, failure, f"job state {job_state!r} cannot be gated for execution"
    job_id = _row_get(job, "job_id")
    if job_id is not None and packet.job_id is not None and str(job_id) != packet.job_id:
        return False, REJECTED, "job_id does not match the packet"
    job_generation = _row_get(job, "generation")
    if job_generation is not None:
        if isinstance(job_generation, bool) or not isinstance(job_generation, int):
            return False, STALE, "job generation is not an integer"
        if job_generation != packet.generation:
            return False, STALE, "job generation does not match the packet snapshot"
    payload = _payload(job)
    for candidate_snapshot in (
        _job_value(job, payload, "snapshot_id", "nmp_snapshot_id", "math_snapshot_id"),
    ):
        if candidate_snapshot is not None and str(candidate_snapshot) != packet.snapshot_id:
            return False, STALE, "job payload belongs to another snapshot"
    job_ruleset = _job_value(job, payload, "ruleset_snapshot_id")
    if job_ruleset is not None and packet.ruleset_snapshot_id and (
        str(job_ruleset) != packet.ruleset_snapshot_id
    ):
        return False, STALE, "job payload belongs to another ruleset snapshot"
    job_preflight = _job_value(job, payload, "preflight_digest")
    if job_preflight is not None and packet.preflight_digest:
        try:
            if normalize_digest(job_preflight, "preflight_digest") != packet.preflight_digest:
                return False, STALE, "job preflight digest does not match the packet"
        except NmpValidationError:
            return False, STALE, "job preflight digest is malformed"
    payload_ring = _job_value(job, payload, "ring_incarnation")
    payload_epoch = _job_value(job, payload, "ring_epoch")
    if payload_ring is not None and packet.ring_incarnation and (
        str(payload_ring) != packet.ring_incarnation
    ):
        return False, STALE, "job ring incarnation does not match the packet"
    if payload_epoch is not None and packet.ring_epoch is not None and (
        payload_epoch != packet.ring_epoch
    ):
        return False, STALE, "job ring epoch does not match the packet"
    job_cancel = _job_value(job, payload, "cancel_epoch")
    if (
        job_cancel is not None
        and isinstance(job_cancel, int)
        and not isinstance(job_cancel, bool)
        and job_cancel > packet.cancel_epoch
    ):
        return False, CANCELLED, "a newer cancel epoch is recorded on the job"
    lease_state = str(_row_get(lease, "state", "") or "").lower()
    if lease_state and lease_state != "active":
        return False, STALE, f"lease state {lease_state!r} is not active"
    if lease_state == "active" and job_state == "queued":
        return False, STALE, "an active lease cannot belong to a queued job"
    lease_token = _row_get(lease, "lease_token")
    job_token = _row_get(job, "lease_token")
    if lease_token is not None and job_token is not None and lease_token != job_token:
        return False, STALE, "lease token does not match the job"
    lease_epoch = _row_get(lease, "lease_epoch")
    if lease_epoch is None:
        lease_epoch = _row_get(job, "lease_epoch")
    if lease_epoch is not None:
        if isinstance(lease_epoch, bool) or not isinstance(lease_epoch, int):
            return False, STALE, "lease epoch is not an integer"
        job_epoch = _row_get(job, "lease_epoch")
        if job_epoch is not None and lease_epoch != int(job_epoch):
            return False, STALE, "lease epoch does not match the job"
        if packet.lease_epoch is not None and lease_epoch != packet.lease_epoch:
            return False, STALE, "lease epoch does not match the packet"
    deadline = _row_get(lease, "deadline_tick", _row_get(job, "deadline_tick"))
    if now_tick is not None and deadline is not None:
        if isinstance(deadline, bool) or not isinstance(deadline, int):
            return False, STALE, "lease deadline is not an integer"
        if now_tick >= deadline:
            return False, STALE, "lease has expired"
    return True, None, None


def _is_cancelled_job(job: Any) -> bool:
    payload = _payload(job)
    if payload.get("cancelled") is True or payload.get("cancel_requested") is True:
        return True
    error = str(_row_get(job, "error", "") or "").lower()
    return "cancel" in error


def _native_preflight_receipt_gate(packet: NmpPacket) -> tuple[bool, str | None]:
    """Validate a packet-bound native receipt when the packet requires one."""
    if not packet.metadata.get("native_preflight_required"):
        return True, None
    receipt_data = packet.evidence.get("native_preflight_receipt")
    if not isinstance(receipt_data, Mapping):
        return False, "native preflight receipt is missing"
    try:
        receipt = NativePreflightReceipt.from_dict(receipt_data)
        receipt.verify_packet(packet)
    except NativePreflightReceiptError as exc:
        return False, f"native preflight receipt is stale or malformed: {exc}"
    if packet.preflight_result != "VALID" or packet.preflight_digest != receipt.receipt_digest:
        return False, "packet preflight fields do not match the native receipt"
    return True, None


def execution_gate(
    packet: NmpPacket,
    *,
    admission: Any = None,
    preflight: Any = None,
    capability: Any = None,
    ruleset_snapshot: Any = None,
    ring_incarnation: Any = None,
    ring_epoch: Any = None,
    cancel_epoch: int | None = None,
    required_capability: Any = None,
    workspace: int | None = None,
    allow_declared: bool = False,
    job: Any = None,
    lease: Any = None,
    now_tick: int | None = None,
) -> NmpGateDecision:
    """Evaluate the execution gate.

    All of these must hold:

    * the packet is PREFLIGHTED (queue gate), QUEUED (lease gate), or
      EXECUTING (pre-dispatch recheck);
    * admission is VALID and bound to the same candidate/snapshot/ruleset;
    * preflight is VALID and its digest matches the packet;
    * the ruleset snapshot is still current;
    * a verified capability row covers the required workspace;
    * the ring incarnation and epoch match the packet binding; and
    * no newer cancellation epoch has been observed.

    Missing capability or workspace is UNAVAILABLE, never NULL.  The decision
    is side-effect free; :meth:`NmpPacket.queue` applies it.
    """
    if workspace is not None:
        _integer(workspace, "workspace")
    checks: dict[str, bool] = {}

    def refuse(state: str, reason: str) -> NmpGateDecision:
        return NmpGateDecision(
            packet_id=packet.packet_id,
            from_state=packet.state,
            ok=False,
            failure=state,
            reason=reason,
            checks=checks,
        )

    if packet.state not in (PREFLIGHTED, QUEUED, EXECUTING):
        checks["state"] = False
        return refuse(REJECTED, f"packet state {packet.state} is not gateable")
    checks["state"] = True

    if packet.jahs != JAHS_SEAL:
        checks["jahs"] = False
        return refuse(REJECTED, "the JAHS handoff seal is missing")
    checks["jahs"] = True

    admission_ok, failure, reason, _ = _admission_gate(packet, admission, preflight)
    checks["admission"] = admission_ok
    if not admission_ok:
        return refuse(failure or REJECTED, reason or "admission refused")

    native_receipt_ok, reason = _native_preflight_receipt_gate(packet)
    checks["native_preflight_receipt"] = native_receipt_ok
    if not native_receipt_ok:
        return refuse(STALE, reason or "native preflight receipt refused")

    ruleset_ok, failure, reason = _ruleset_gate(packet, ruleset_snapshot)
    checks["ruleset"] = ruleset_ok
    if not ruleset_ok:
        return refuse(failure or STALE, reason or "ruleset snapshot refused")

    ring_ok, failure, reason = _ring_gate(packet, ring_incarnation, ring_epoch)
    checks["ring"] = ring_ok
    if not ring_ok:
        return refuse(failure or STALE, reason or "ring binding refused")

    if cancel_epoch is not None:
        _integer(cancel_epoch, "cancel_epoch")
        if cancel_epoch < packet.cancel_epoch:
            checks["cancel_epoch"] = False
            return refuse(STALE, "cancel epoch is older than the packet")
        if cancel_epoch > packet.cancel_epoch:
            checks["cancel_epoch"] = False
            return refuse(CANCELLED, "a newer cancellation epoch has superseded the packet")
    checks["cancel_epoch"] = True

    capability_ok, failure, reason = _check_capabilities(
        packet,
        capability,
        required_capability=required_capability,
        workspace=workspace,
        allow_declared=allow_declared,
    )
    checks["capability"] = capability_ok
    if not capability_ok:
        return refuse(failure or UNAVAILABLE, reason or "capability is unavailable")

    job_ok, failure, reason = _job_gate(packet, job, lease, now_tick=now_tick)
    checks["job"] = job_ok
    if not job_ok:
        return refuse(failure or STALE, reason or "job/lease evidence refused")

    return NmpGateDecision(
        packet_id=packet.packet_id,
        from_state=packet.state,
        ok=True,
        checks=checks,
    )


# Compatibility alias; the name is intentionally explicit about checking.
check_execution_gate = execution_gate


# ---------------------------------------------------------------------------
# Packet construction helper
# ---------------------------------------------------------------------------


def prepare(
    candidate: Any,
    preflight: Any = None,
    *,
    snapshot_id: str | None = None,
    base_generation: int = 0,
    lane_id: int = 0,
    universe_id: str = "U0",
    admission: Any = None,
    capability_set: Any = (),
    capability_epoch: int = 0,
    resources: Mapping[str, Any] | None = None,
    guest_words: int | None = None,
    ruleset_id: str = "",
    ruleset_version: int = 1,
    ruleset_snapshot_id: str | None = None,
    ring_incarnation: str | None = None,
    ring_epoch: int | None = None,
    plan_digest: str | None = None,
    numerical_policy: Mapping[str, Any] | None = None,
    commutative: bool = False,
    request_id: str | None = None,
    jahs: str | None = JAHS_SEAL,
    metadata: Mapping[str, Any] | None = None,
    defer_preflight: bool = False,
    tick: int = 0,
) -> NmpPacket:
    """Build an NMP packet from a selected candidate.

    Set defer_preflight=True when the packet must be staged as PROPOSED and
    evaluated by the NaN16 guest before mark_preflight(receipt=...) is called.
    Without deferral, a VALID supplied preflight yields PREFLIGHTED and an
    invalid/missing result yields its specific typed terminal state.
    """
    candidate_data = _candidate_fields(candidate)
    candidate_id = candidate_data.get("candidate_id") or candidate_data.get("candidate")
    if not candidate_id:
        raise NmpValidationError("candidate is missing a candidate_id")
    function_id = candidate_data.get("function_id")
    if not function_id:
        raise NmpValidationError("candidate is missing function_id")
    function_version = candidate_data.get("function_version", 1)
    packet_snapshot = snapshot_id or candidate_data.get("snapshot_id")
    if not packet_snapshot:
        raise NmpValidationError("snapshot_id is required")

    preflight_data = _preflight_fields(preflight)
    admission_data = _admission_fields(admission)
    if admission is None and preflight_data.get("admission_id"):
        admission_data = preflight_data
    evaluated_preflight = _preflight_result(preflight_data)
    evaluated_admission = _preflight_result(admission_data)
    preflight_result = evaluated_preflight
    if evaluated_preflight is not None and evaluated_preflight != "VALID":
        control_result = evaluated_preflight
    elif evaluated_admission is not None:
        control_result = evaluated_admission
    else:
        control_result = evaluated_preflight
    preflight_digest = preflight_data.get("digest") or preflight_data.get("preflight_digest")
    if preflight_digest is None:
        preflight_digest = admission_data.get("preflight_digest")
    if (
        evaluated_preflight is None
        and evaluated_admission == "VALID"
        and preflight_digest is not None
    ):
        # An admission record may carry the preflight digest; in that case the
        # preflight outcome is VALID by construction and can be bound.
        preflight_result = "VALID"
    ruleset_snapshot = (
        ruleset_snapshot_id
        or preflight_data.get("rule_snapshot_id")
        or preflight_data.get("ruleset_snapshot_id")
        or admission_data.get("rule_snapshot_id")
        or admission_data.get("ruleset_snapshot_id")
        or ""
    )
    if not ruleset_id:
        ruleset_id = preflight_data.get("ruleset_id", "") or admission_data.get("ruleset_id", "")
    if resources is None:
        resources = {}
    if guest_words is None:
        guest_words = resources.get("guest_words", 0)
    if plan_digest is None:
        plan_digest = preflight_data.get("plan_digest") or resources.get("plan_digest")

    packet = NmpPacket(
        snapshot_id=packet_snapshot,
        base_generation=base_generation,
        lane_id=lane_id,
        universe_id=universe_id,
        function_id=function_id,
        function_version=function_version,
        candidate_id=candidate_id,
        inputs=candidate_data.get("inputs") or (),
        admission_id=admission_data.get("admission_id"),
        admission_verdict=admission_data.get("verdict"),
        preflight_digest=preflight_digest,
        preflight_result=preflight_result,
        ruleset_id=ruleset_id,
        ruleset_version=preflight_data.get(
            "ruleset_version", admission_data.get("ruleset_version", ruleset_version)
        ),
        ruleset_snapshot_id=ruleset_snapshot,
        capability_set=capability_set,
        capability_epoch=capability_epoch,
        guest_words=guest_words,
        plan_digest=plan_digest,
        numerical_policy=numerical_policy or {},
        commutative=commutative,
        request_id=request_id,
        ring_incarnation=ring_incarnation,
        ring_epoch=ring_epoch,
        jahs=jahs,
        metadata=metadata or {},
        state=CREATED,
        updated_tick=tick,
    )
    packet = packet.transition(RESOLVED, reason="candidate inputs resolved", tick=tick)
    packet = packet.transition(CLASSIFIED, reason="candidate function classified", tick=tick)
    if control_result != "VALID":
        failure = _ADMISSION_FAILURE.get(control_result or "", REJECTED)
        if failure is None:
            failure = REJECTED
        # Finalize the most specific reachable control terminal.  These are
        # already typed failures; none of them is an empty/NULL result.
        if failure in (NULL, UNDEFINED):
            return packet.transition(
                failure,
                reason=control_result or "preflight failed",
                failure_class=failure,
                tick=tick,
            )
        packet = packet.transition(PROPOSED, reason="candidate selected", tick=tick)
        if failure in (UNAVAILABLE, UNAUTHORIZED, STALE, EXPERIMENTAL):
            packet = packet.transition(
                PREFLIGHTED,
                reason=f"preflight evaluated: {control_result or 'MISSING'}",
                tick=tick,
            )
            return packet.transition(
                failure,
                reason=f"preflight/admission result {control_result or 'MISSING'}",
                failure_class=failure,
                tick=tick,
            )
        return packet.transition(
            REJECTED,
            reason=f"preflight/admission result {control_result or 'MISSING'}",
            failure_class=failure,
            tick=tick,
        )
    packet = packet.transition(PROPOSED, reason="candidate selected", tick=tick)
    if defer_preflight and control_result is None:
        return packet
    return packet.transition(PREFLIGHTED, reason="preflight VALID", tick=tick)


# ---------------------------------------------------------------------------
# Dedupe / in-flight table (memory only)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NmpDedupeResult:
    key: str
    duplicate: bool
    packet: NmpPacket
    existing: NmpPacket | None = None
    subscribers: tuple[str, ...] = ()
    reusable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "duplicate": self.duplicate,
            "packet_id": self.packet.packet_id,
            "existing_packet_id": None if self.existing is None else self.existing.packet_id,
            "subscribers": list(self.subscribers),
            "reusable": self.reusable,
        }


class NmpInFlightTable:
    """Explicitly in-memory duplicate/subscriber index.

    This is not durable state and not a second job ledger.  Restart recovery
    must use the WaveStore job/lease projection in :func:`project_packet`.
    """

    durable = False
    owns_jobs = False

    def __init__(self) -> None:
        self._entries: dict[str, NmpPacket] = {}
        self._subscribers: dict[str, list[str]] = {}

    def key_for(self, packet: NmpPacket) -> str:
        return packet.dedupe_key

    def lookup(self, packet_or_key: NmpPacket | str) -> NmpPacket | None:
        key = packet_or_key.dedupe_key if isinstance(packet_or_key, NmpPacket) else str(packet_or_key)
        return self._entries.get(key)

    def subscribe(self, key: str, packet_id: str) -> tuple[str, ...]:
        if not key or not packet_id:
            raise NmpDedupeError("key and packet_id are required")
        subscribers = self._subscribers.setdefault(key, [])
        if packet_id not in subscribers:
            subscribers.append(packet_id)
        return tuple(subscribers)

    def put(self, packet: NmpPacket) -> NmpDedupeResult:
        key = packet.dedupe_key
        existing = self._entries.get(key)
        if existing is not None:
            if existing.snapshot_id != packet.snapshot_id:
                raise NmpDedupeError("dedupe key collision across snapshots")
            subscribers = self.subscribe(key, packet.packet_id)
            reusable = existing.state == COMMITTED and existing.result_digest is not None
            return NmpDedupeResult(
                key=key,
                duplicate=True,
                packet=existing,
                existing=existing,
                subscribers=subscribers,
                reusable=reusable,
            )
        self._entries[key] = packet
        self._subscribers.setdefault(key, [packet.packet_id])
        return NmpDedupeResult(
            key=key,
            duplicate=False,
            packet=packet,
            existing=None,
            subscribers=tuple(self._subscribers[key]),
            reusable=False,
        )

    def replace(self, packet: NmpPacket) -> None:
        """Update the in-memory record for an existing content key."""
        key = packet.dedupe_key
        if key not in self._entries:
            raise NmpDedupeError("cannot replace an operation that is not in-flight")
        self._entries[key] = packet

    def remove(self, packet_or_key: NmpPacket | str) -> NmpPacket | None:
        key = packet_or_key.dedupe_key if isinstance(packet_or_key, NmpPacket) else str(packet_or_key)
        self._subscribers.pop(key, None)
        return self._entries.pop(key, None)

    def __len__(self) -> int:
        return len(self._entries)


def dedupe_key(
    *,
    snapshot_id: str,
    function_id: str,
    function_version: int = 1,
    candidate_id: str = "",
    inputs: Iterable[Mapping[str, Any]] = (),
    base_generation: int = 0,
    ruleset_snapshot_id: str = "",
    numerical_policy: Mapping[str, Any] | None = None,
    capability_set: Any = (),
    commutative: bool = False,
) -> str:
    """Module-level alias for :func:`dedupe_key_for`."""
    return dedupe_key_for(
        snapshot_id=snapshot_id,
        function_id=function_id,
        function_version=function_version,
        candidate_id=candidate_id,
        inputs=inputs,
        base_generation=base_generation,
        ruleset_snapshot_id=ruleset_snapshot_id,
        numerical_policy=numerical_policy,
        capability_set=capability_set,
        commutative=commutative,
    )


# ---------------------------------------------------------------------------
# Batch
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NmpBatchSeal:
    batch_id: str
    parent_packet_id: str
    digest: str
    child_digests: tuple[str, ...]
    child_states: tuple[str, ...]
    jahs: str = JAHS_SEAL
    promotion_eligible: bool = False
    parent_lease: None = None
    sealed_tick: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "nanrouter.nmp.batch-seal.v1",
            "batch_id": self.batch_id,
            "parent_packet_id": self.parent_packet_id,
            "digest": self.digest,
            "child_digests": list(self.child_digests),
            "child_states": list(self.child_states),
            "jahs": self.jahs,
            "promotion_eligible": self.promotion_eligible,
            "parent_lease": None,
            "sealed_tick": self.sealed_tick,
        }


@dataclass(frozen=True)
class NmpBatch:
    """One parent envelope and N independently leased child packets.

    The parent is never leased and is never a second job ledger.  Children own
    their job/lease references individually, so a handoff may occur between
    children.  The batch seal is computed only when every child is terminal.
    """

    parent: NmpPacket
    children: tuple[NmpPacket, ...]
    batch_id: str | None = None

    def __post_init__(self) -> None:
        if not self.children:
            raise NmpBatchError("a batch requires at least one child")
        if self.parent.job_id is not None or self.parent.lease_epoch is not None:
            raise NmpBatchError("a batch parent must not hold a lease")
        if self.parent.state in _BATCH_PARENT_FORBIDDEN_STATES:
            raise NmpBatchError("a batch parent cannot be in an execution state")
        batch_id = self.batch_id or self.parent.batch_id
        if not batch_id:
            child_batch_ids = {child.batch_id for child in self.children if child.batch_id}
            if len(child_batch_ids) > 1:
                raise NmpBatchError("children name different batches and the parent has no batch_id")
            if child_batch_ids:
                batch_id = next(iter(child_batch_ids))
        if not batch_id:
            batch_id = batch_id_for(self.parent, self.children)
        _text(batch_id, "batch_id", maximum=512)
        parent = replace(
            self.parent,
            is_batch_parent=True,
            batch_id=batch_id,
            batch_count=len(self.children),
            child_packet_ids=tuple(child.packet_id for child in self.children),
        )
        normalized: list[NmpPacket] = []
        seen: set[str] = set()
        for index, child in enumerate(self.children):
            if child.is_batch_parent:
                raise NmpBatchError("a batch child cannot itself be a batch parent")
            if child.snapshot_id != self.parent.snapshot_id:
                raise NmpBatchError("batch children must share the parent snapshot")
            if child.base_generation != self.parent.base_generation:
                raise NmpBatchError("batch children must share the parent generation")
            if child.parent_packet_id is not None and child.parent_packet_id != parent.packet_id:
                raise NmpBatchError("child belongs to another parent packet")
            if child.batch_id is not None and child.batch_id != batch_id:
                raise NmpBatchError("child belongs to another batch")
            if child.batch_index is not None and child.batch_index != index:
                raise NmpBatchError("child batch_index does not match its position")
            if child.batch_count is not None and child.batch_count != len(self.children):
                raise NmpBatchError("child batch_count does not match the batch")
            if child.packet_id in seen or child.packet_id == parent.packet_id:
                raise NmpBatchError("batch packet ids must be distinct")
            seen.add(child.packet_id)
            normalized.append(replace(
                child,
                batch_id=batch_id,
                batch_index=index,
                batch_count=len(self.children),
                parent_packet_id=parent.packet_id,
                is_batch_parent=False,
            ))
        object.__setattr__(self, "parent", parent)
        object.__setattr__(self, "children", tuple(normalized))
        object.__setattr__(self, "batch_id", batch_id)

    @classmethod
    def create(cls, parent: NmpPacket, children: Sequence[NmpPacket], *,
               batch_id: str | None = None) -> "NmpBatch":
        return cls(parent, tuple(children), batch_id=batch_id)

    @property
    def parent_lease(self) -> None:
        """A parent lease never exists."""
        return None

    @property
    def snapshot_id(self) -> str:
        return self.parent.snapshot_id

    @property
    def base_generation(self) -> int:
        return self.parent.base_generation

    @property
    def child_states(self) -> tuple[str, ...]:
        return tuple(child.state for child in self.children)

    @property
    def finished(self) -> bool:
        return all(child.is_terminal for child in self.children)

    @property
    def sealed(self) -> bool:
        return self.finished

    def __len__(self) -> int:
        return len(self.children)

    def __iter__(self):
        return iter(self.children)

    def __getitem__(self, index: int | str) -> NmpPacket:
        return self.child(index)

    def child(self, index_or_id: int | str) -> NmpPacket:
        if isinstance(index_or_id, int):
            if not isinstance(index_or_id, int) or isinstance(index_or_id, bool):
                raise NmpBatchError("child index must be an integer")
            try:
                return self.children[index_or_id]
            except IndexError as exc:
                raise NmpBatchError("child index out of range") from exc
        for child in self.children:
            if child.packet_id == index_or_id:
                return child
        raise NmpBatchError(f"unknown child packet: {index_or_id}")

    def replace_child(self, child: NmpPacket) -> "NmpBatch":
        found = False
        children: list[NmpPacket] = []
        for current in self.children:
            if current.packet_id == child.packet_id:
                children.append(child)
                found = True
            else:
                children.append(current)
        if not found:
            raise NmpBatchError("replacement child is not in this batch")
        return NmpBatch(self.parent, tuple(children), batch_id=self.batch_id)

    def lease_parent(self, **_: Any) -> None:
        raise NmpBatchError("a batch parent has no lease and cannot be executed")

    def assert_no_parent_lease(self) -> None:
        if self.parent.job_id is not None or self.parent.lease_epoch is not None:
            raise NmpBatchError("a batch parent must not hold a lease")

    def try_seal(self, *, tick: int = 0) -> NmpBatchSeal | None:
        if not self.finished:
            return None
        self.assert_no_parent_lease()
        child_digests = tuple(child.digest() for child in self.children)
        child_states = self.child_states
        payload = {
            "schema": NMP_SCHEMA,
            "batch_id": self.batch_id,
            "parent_packet_id": self.parent.packet_id,
            "snapshot_id": self.parent.snapshot_id,
            "base_generation": self.parent.base_generation,
            "children": [
                {
                    "packet_id": child.packet_id,
                    "state": child.state,
                    "digest": digest,
                    "result_digest": child.result_digest,
                }
                for child, digest in zip(self.children, child_digests)
            ],
            "jahs": JAHS_SEAL,
            "promotion_eligible": False,
            "parent_lease": None,
        }
        return NmpBatchSeal(
            batch_id=str(self.batch_id),
            parent_packet_id=self.parent.packet_id,
            digest=digest_object(payload),
            child_digests=child_digests,
            child_states=child_states,
            jahs=JAHS_SEAL,
            promotion_eligible=False,
            parent_lease=None,
            sealed_tick=tick,
        )

    def seal(self, *, tick: int = 0) -> NmpBatchSeal:
        seal = self.try_seal(tick=tick)
        if seal is None:
            raise NmpSealError("batch cannot be sealed until every child is terminal")
        return seal

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "nanrouter.nmp.batch.v1",
            "batch_id": self.batch_id,
            "parent": self.parent.to_dict(),
            "children": [child.to_dict() for child in self.children],
            "parent_lease": None,
            "sealed": self.try_seal().to_dict() if self.finished else None,
        }


def make_batch(parent: NmpPacket, children: Sequence[NmpPacket], *,
               batch_id: str | None = None) -> NmpBatch:
    return NmpBatch(parent, tuple(children), batch_id=batch_id)


# ---------------------------------------------------------------------------
# Projection from WaveStore-like job/lease rows
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NmpProjection:
    """Evidence-derived packet state; never a private durable claim."""

    packet_id: str
    claimed_state: str
    state: str | None
    supported: bool
    job_state: str | None = None
    lease_state: str | None = None
    job_id: str | None = None
    lease_epoch: int | None = None
    result_digest: str | None = None
    result_generation: int | None = None
    ring_incarnation: str | None = None
    ring_epoch: int | None = None
    reason: str | None = None
    source: str = "job/lease"
    evidence: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", dict(self.evidence or {}))

    @property
    def authoritative_state(self) -> str | None:
        return self.state

    @property
    def packet_claim_supported(self) -> bool:
        return self.supported

    def require_supported(self) -> "NmpProjection":
        if not self.supported or self.state is None:
            raise NmpProjectionError(
                self.reason or f"job/lease evidence does not support {self.claimed_state}"
            )
        return self

    def to_packet(self, template: NmpPacket, *, tick: int = 0) -> NmpPacket:
        """Reconstruct a packet from authoritative job/lease evidence."""
        self.require_supported()
        target = self.state
        assert target is not None
        if target == template.state and (
            self.result_digest is None or self.result_digest == template.result_digest
        ):
            return template
        updates: dict[str, Any] = {
            "state": target,
            "updated_tick": tick or template.updated_tick,
            "history": template.history + ({
                "from": template.state,
                "to": target,
                "reason": "projection from job/lease rows",
                "tick": tick or template.updated_tick,
                "job_state": self.job_state,
                "lease_state": self.lease_state,
            },),
        }
        if self.job_id is not None:
            updates["job_id"] = self.job_id
        if self.lease_epoch is not None:
            updates["lease_epoch"] = self.lease_epoch
        if self.result_digest is not None:
            updates["result_digest"] = self.result_digest
        if self.ring_incarnation is not None:
            updates["ring_incarnation"] = self.ring_incarnation
        if self.ring_epoch is not None:
            updates["ring_epoch"] = self.ring_epoch
        if self.reason is not None and target in ALL_TERMINAL_STATES:
            updates["reason"] = self.reason
        if target == COMMITTED:
            updates.setdefault("provenance", dict(template.provenance))
        if target == CANCELLED:
            updates["result_digest"] = None
        return replace(template, **updates)

    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "claimed_state": self.claimed_state,
            "state": self.state,
            "supported": self.supported,
            "job_state": self.job_state,
            "lease_state": self.lease_state,
            "job_id": self.job_id,
            "lease_epoch": self.lease_epoch,
            "result_digest": self.result_digest,
            "result_generation": self.result_generation,
            "ring_incarnation": self.ring_incarnation,
            "ring_epoch": self.ring_epoch,
            "reason": self.reason,
            "source": self.source,
            "evidence": dict(self.evidence or {}),
        }


_PRE_JOB_CONTROL = frozenset({
    CREATED, RESOLVED, CLASSIFIED, PROPOSED, PREFLIGHTED,
    NULL, UNDEFINED, REJECTED, UNAVAILABLE, UNAUTHORIZED, STALE, FAILED,
    CANCELLED, INVALID, EXPERIMENTAL,
})


def _claim_supported(claimed: str, effective: str, packet: NmpPacket) -> bool:
    if effective == COMMITTED:
        return claimed in STATES
    if effective == COMPLETED:
        if claimed == COMMITTED:
            try:
                packet._require_commit_evidence()
            except NmpValidationError:
                return False
            return True
        return claimed in STATES and _STATE_ORDER.get(claimed, 99) <= _STATE_ORDER[COMPLETED]
    if effective in (FAILED, CANCELLED, STALE):
        if claimed in (effective, STALE):
            return True
        if claimed in ALL_TERMINAL_STATES:
            return False
        return _STATE_ORDER.get(claimed, 99) <= _STATE_ORDER[EXECUTING]
    if effective == EXECUTING:
        return claimed in STATES and _STATE_ORDER.get(claimed, 99) <= _STATE_ORDER[EXECUTING]
    if effective == QUEUED:
        return claimed in STATES and _STATE_ORDER.get(claimed, 99) <= _STATE_ORDER[QUEUED]
    return claimed == effective


def _lease_expired(job: Any, lease: Any, now_tick: int | None) -> bool:
    if now_tick is None:
        return False
    deadline = _row_get(lease, "deadline_tick", _row_get(job, "deadline_tick"))
    if deadline is None:
        return False
    if isinstance(deadline, bool) or not isinstance(deadline, int):
        return True
    return now_tick >= deadline


def project_packet(
    packet: NmpPacket,
    *,
    job: Any = None,
    lease: Any = None,
    store: Any = None,
    now_tick: int | None = None,
    allow_newer: bool = False,
) -> NmpProjection:
    """Project the authoritative state from job/lease rows.

    ``store`` may be a WaveStore-like object with ``get_job(job_id)``; the
    module does not import or write to it.  The packet's own state is treated
    as a claim, not as truth.  If no job row exists, execution states are
    unsupported and return ``state=None``.
    """
    if store is not None and job is None and packet.job_id:
        get_job = getattr(store, "get_job", None)
        if callable(get_job):
            job = get_job(packet.job_id)
    job_state = str(_row_get(job, "state", "") or "").lower() or None
    lease_state = str(_row_get(lease, "state", "") or "").lower() or None
    job_id = _row_get(job, "job_id")
    if job_id is None:
        job_id = packet.job_id

    if job is None:
        if packet.state in _PRE_JOB_CONTROL:
            return NmpProjection(
                packet_id=packet.packet_id,
                claimed_state=packet.state,
                state=packet.state,
                supported=True,
                job_id=packet.job_id,
                lease_epoch=packet.lease_epoch,
                ring_incarnation=packet.ring_incarnation,
                ring_epoch=packet.ring_epoch,
                reason=None,
                source="control-plane (no job row)",
                evidence={"job": None, "lease": None},
            )
        return NmpProjection(
            packet_id=packet.packet_id,
            claimed_state=packet.state,
            state=None,
            supported=False,
            reason="no job/lease row supports an execution state",
            source="job/lease",
            evidence={"job": None, "lease": None},
        )

    evidence: dict[str, Any] = {
        "job_state": job_state,
        "lease_state": lease_state,
        "job_generation": _row_get(job, "generation"),
        "result_generation": _row_get(job, "result_generation"),
        "lease_token": _row_get(job, "lease_token"),
        "deadline_tick": _row_get(job, "deadline_tick"),
    }

    def projection(state: str | None, supported: bool, reason: str | None,
                   **updates: Any) -> NmpProjection:
        return NmpProjection(
            packet_id=packet.packet_id,
            claimed_state=packet.state,
            state=state,
            supported=supported,
            job_state=job_state,
            lease_state=lease_state,
            job_id=str(job_id) if job_id is not None else None,
            reason=reason,
            evidence=evidence,
            **updates,
        )

    # Snapshot/generation binding ------------------------------------------
    job_generation = _row_get(job, "generation")
    if job_generation is not None:
        if isinstance(job_generation, bool) or not isinstance(job_generation, int):
            return projection(STALE, False, "job generation is malformed")
        if job_generation < packet.base_generation:
            return projection(STALE, False, "job generation is older than the packet")
        if job_generation != packet.generation and not allow_newer:
            return projection(STALE, False, "job generation does not match the packet")
    result_generation = _row_get(job, "result_generation")
    if result_generation is not None:
        if isinstance(result_generation, bool) or not isinstance(result_generation, int):
            return projection(STALE, False, "result generation is malformed")
        if job_generation is not None and result_generation != job_generation and not allow_newer:
            return projection(STALE, False, "result generation is not the job generation")

    payload = _payload(job)
    evidence["payload"] = payload
    job_snapshot = _job_value(
        job, payload, "snapshot_id", "nmp_snapshot_id", "math_snapshot_id",
    )
    if job_snapshot is not None and str(job_snapshot) != packet.snapshot_id:
        return projection(STALE, False, "job payload belongs to another snapshot")
    job_ruleset = _job_value(job, payload, "ruleset_snapshot_id")
    if job_ruleset is not None and packet.ruleset_snapshot_id and (
        str(job_ruleset) != packet.ruleset_snapshot_id
    ):
        return projection(STALE, False, "job payload belongs to another ruleset snapshot")
    job_preflight = _job_value(job, payload, "preflight_digest")
    if job_preflight is not None and packet.preflight_digest:
        try:
            if normalize_digest(job_preflight, "preflight_digest") != packet.preflight_digest:
                return projection(STALE, False, "job preflight digest does not match the packet")
        except NmpValidationError:
            return projection(STALE, False, "job preflight digest is malformed")
    payload_ring = _job_value(job, payload, "ring_incarnation")
    payload_epoch = _job_value(job, payload, "ring_epoch")
    if payload_ring is not None and packet.ring_incarnation and (
        str(payload_ring) != packet.ring_incarnation
    ):
        return projection(STALE, False, "job ring incarnation does not match the packet")
    if payload_epoch is not None and packet.ring_epoch is not None and (
        payload_epoch != packet.ring_epoch
    ):
        return projection(STALE, False, "job ring epoch does not match the packet")
    payload_cancel = _job_value(job, payload, "cancel_epoch")
    if payload_cancel is not None:
        evidence["cancel_epoch"] = payload_cancel
        if (
            isinstance(payload_cancel, int)
            and not isinstance(payload_cancel, bool)
            and payload_cancel > packet.cancel_epoch
        ):
            # A newer epoch is a cancellation request.  It does not by itself
            # prove that the executor observed a plan-step boundary.
            evidence["cancel_requested"] = True

    # Job/lease consistency -------------------------------------------------
    job_token = _row_get(job, "lease_token")
    lease_token = _row_get(lease, "lease_token")
    if lease_token is not None and job_token is not None and lease_token != job_token:
        return projection(STALE, False, "lease token does not match the job")
    job_epoch = _row_get(job, "lease_epoch")
    lease_epoch = _row_get(lease, "lease_epoch")
    if lease_epoch is not None:
        if isinstance(lease_epoch, bool) or not isinstance(lease_epoch, int):
            return projection(STALE, False, "lease epoch is malformed")
        if job_epoch is not None and int(job_epoch) != lease_epoch:
            return projection(STALE, False, "lease epoch does not match the job")
        if packet.lease_epoch is not None and lease_epoch != packet.lease_epoch:
            return projection(STALE, False, "lease epoch does not match the packet")
    if lease_state is not None:
        if lease_state == "active" and job_state not in {"leased", None, ""}:
            return projection(STALE, False, "active lease exists for a non-leased job")
        if lease_state in {"completed", "failed"} and job_state not in {"done", "failed"}:
            return projection(STALE, False, f"lease is {lease_state} but job is {job_state}")
        if lease_state == "expired" and job_state == "leased":
            return projection(STALE, True, "lease expired; packet is not executing", lease_epoch=lease_epoch)
    if job_state == "leased" and _lease_expired(job, lease, now_tick):
        return projection(STALE, True, "lease deadline has expired", lease_epoch=lease_epoch)

    common = {
        "lease_epoch": lease_epoch if lease_epoch is not None else job_epoch,
        "ring_incarnation": payload_ring or packet.ring_incarnation,
        "ring_epoch": payload_epoch if payload_epoch is not None else packet.ring_epoch,
        "result_generation": result_generation,
    }

    if job_state == "queued":
        if lease_state is not None and lease_state != "expired":
            return projection(STALE, False, "queued job carries a lease")
        supported = _claim_supported(packet.state, QUEUED, packet)
        return projection(QUEUED, supported, None if supported else "packet claims a later state than the queued job", **common)
    if job_state == "leased":
        supported = _claim_supported(packet.state, EXECUTING, packet)
        return projection(EXECUTING, supported, None if supported else "packet claim is not supported by the active lease", **common)
    if job_state == "done":
        result_digest = _row_get(job, "result_digest")
        if result_digest is not None:
            try:
                result_digest = normalize_digest(result_digest, "result_digest")
            except NmpValidationError:
                return projection(STALE, False, "job result digest is malformed")
        if packet.result_digest is not None and result_digest is not None and (
            packet.result_digest != result_digest
        ):
            return projection(STALE, False, "job result digest does not match the packet")
        effective = COMPLETED
        if packet.state == COMMITTED:
            try:
                packet._require_commit_evidence()
            except NmpValidationError as exc:
                return projection(COMPLETED, False, str(exc))
            if result_digest is None:
                return projection(STALE, False, "COMMITTED claim has no evidenced result digest")
            effective = COMMITTED
        supported = _claim_supported(packet.state, effective, packet)
        return projection(
            effective,
            supported,
            None if supported else "packet claim is not supported by the completed job",
            result_digest=result_digest,
            **common,
        )
    if job_state == "failed":
        cancelled = _is_cancelled_job(job) or payload.get("cancel_requested") is True
        effective = CANCELLED if cancelled else FAILED
        supported = _claim_supported(packet.state, effective, packet)
        return projection(
            effective,
            supported,
            None if supported else "packet claim is not supported by the failed job",
            **common,
        )
    if job_state == "dead":
        supported = _claim_supported(packet.state, FAILED, packet)
        return projection(FAILED, supported, None if supported else "packet claim is not supported by the dead job", **common)
    return projection(STALE, False, f"unknown job state: {job_state!r}", **common)


def project(
    packet: NmpPacket,
    *,
    job: Any = None,
    lease: Any = None,
    store: Any = None,
    now_tick: int | None = None,
    allow_newer: bool = False,
) -> NmpProjection:
    """Alias for :func:`project_packet`."""
    return project_packet(
        packet,
        job=job,
        lease=lease,
        store=store,
        now_tick=now_tick,
        allow_newer=allow_newer,
    )


def reconstruct_packet(
    packet: NmpPacket,
    *,
    job: Any = None,
    lease: Any = None,
    store: Any = None,
    now_tick: int | None = None,
    allow_newer: bool = False,
    tick: int = 0,
) -> NmpPacket:
    """Restart helper: rebuild a packet from job/lease rows alone."""
    projection = project_packet(
        packet,
        job=job,
        lease=lease,
        store=store,
        now_tick=now_tick,
        allow_newer=allow_newer,
    )
    return projection.to_packet(packet, tick=tick)


class NmpProjector:
    """Convenience wrapper around job/lease projection.

    ``store`` is any WaveStore-like object exposing ``get_job(job_id)``.
    This class never writes to the store and owns no durable state.
    """

    durable = False
    owns_jobs = False

    def __init__(self, store: Any = None) -> None:
        self.store = store

    def project(
        self,
        packet: NmpPacket,
        *,
        job: Any = None,
        lease: Any = None,
        now_tick: int | None = None,
        allow_newer: bool = False,
    ) -> NmpProjection:
        return project_packet(
            packet,
            job=job,
            lease=lease,
            store=self.store,
            now_tick=now_tick,
            allow_newer=allow_newer,
        )

    def reconstruct(
        self,
        packet: NmpPacket,
        *,
        job: Any = None,
        lease: Any = None,
        now_tick: int | None = None,
        allow_newer: bool = False,
        tick: int = 0,
    ) -> NmpPacket:
        return reconstruct_packet(
            packet,
            job=job,
            lease=lease,
            store=self.store,
            now_tick=now_tick,
            allow_newer=allow_newer,
            tick=tick,
        )


# Common discoverable aliases.
NmpStateProjection = NmpProjection
NmpDeduplicator = NmpInFlightTable


def admission_is_current(packet: NmpPacket, admission: Any) -> bool:
    """True when an admission record is still bound to the packet snapshot."""
    verdict, data = _admission_verdict(admission)
    if verdict != "VALID":
        return False
    snapshot = data.get("snapshot_id")
    if snapshot is not None and str(snapshot) != packet.snapshot_id:
        return False
    ruleset = data.get("rule_snapshot_id") or data.get("ruleset_snapshot_id")
    if ruleset is not None and packet.ruleset_snapshot_id and str(ruleset) != packet.ruleset_snapshot_id:
        return False
    preflight = data.get("preflight_digest")
    if preflight is not None and packet.preflight_digest is not None:
        try:
            if normalize_digest(preflight, "preflight_digest") != packet.preflight_digest:
                return False
        except NmpValidationError:
            return False
    return True


# Module-level discoverable aliases.
prepare_packet = prepare
gate = execution_gate
project_state = project_packet
restore_packet = reconstruct_packet


def can_execute(packet: NmpPacket, **kwargs: Any) -> bool:
    """Module-level boolean execution gate."""
    return execution_gate(packet, **kwargs).ok


__all__ = [
    "ALL_STATES",
    "ALL_TERMINAL_STATES",
    "CANCELLED",
    "CLASSIFIED",
    "COMMITTED",
    "COMPLETED",
    "CREATED",
    "EXECUTING",
    "EXPERIMENTAL",
    "FAILED",
    "INVALID",
    "JAHS_SEAL",
    "LANE_COUNT",
    "LANES",
    "MAX_LANE",
    "NANNET0",
    "NANNET0_LANE",
    "NMP_SCHEMA",
    "NULL",
    "OPTIONAL_TERMINAL_STATES",
    "NmpBatch",
    "NmpBatchError",
    "NmpBatchSeal",
    "NmpCancellation",
    "NmpCancellationResult",
    "NmpDedupeError",
    "NmpDedupeResult",
    "NmpDeduplicator",
    "NmpError",
    "NmpGateDecision",
    "NmpGateError",
    "NmpInFlightTable",
    "NmpLaneError",
    "NmpPacket",
    "NmpProjection",
    "NmpProjectionError",
    "NmpProjector",
    "NmpSealError",
    "NmpStateProjection",
    "NmpTransitionError",
    "NmpValidationError",
    "PREFLIGHTED",
    "PROPOSED",
    "QUEUED",
    "REJECTED",
    "REQUIRED_TERMINAL_STATES",
    "RESOLVED",
    "STALE",
    "STATES",
    "SUCCESS_TERMINAL_STATES",
    "TERMINAL_STATES",
    "TRANSITIONS",
    "UNAUTHORIZED",
    "UNAVAILABLE",
    "UNDEFINED",
    "admission_is_current",
    "batch_id_for",
    "can_execute",
    "check_execution_gate",
    "dedupe_key",
    "dedupe_key_for",
    "execution_gate",
    "gate",
    "is_valid_lane",
    "make_batch",
    "normalize_digest",
    "packet_id_for",
    "prepare",
    "prepare_packet",
    "project",
    "project_packet",
    "project_state",
    "reconstruct_packet",
    "restore_packet",
    "validate_lane",
]
