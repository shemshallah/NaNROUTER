"""Control-plane execution bridge for prepared NMP math packets.

The bridge is deliberately thin.  It is *not* a fifth authority and it owns no
durable job, lease, or result ledger.  Durable truth remains in
:class:`runner_riddle.wave_store.WaveStore` job/lease rows.  The bridge:

* refuses a packet unless :func:`runner_riddle.nmp.execution_gate` accepts the
  bound admission, preflight digest, ruleset snapshot, active ring
  incarnation/epoch, capability/workspace, cancellation epoch, and
  job/lease evidence;
* submits the already compiled :class:`runner_riddle.mth_registry.MthPlan`
  through :class:`runner_riddle.math_runtime.MathRuntime` and
  :class:`runner_riddle.mth_system.MthSystem`;
* leases only the scheduler's one active runner slot and mirrors the lease and
  memory reservation on :class:`runner_riddle.wave_ring_scheduler.WaveRingScheduler`;
* releases that ring lease/memory after complete, fail, or cancel; and
* reconstructs packet state from WaveStore rows after a restart.

No method in this module executes a native kernel or performs host
mathematics.  ``execute`` only calls a caller-supplied executor callback and
``complete`` accepts a caller-supplied result digest.  The bridge never turns a
missing result into zero, ``NULL``, or a fabricated leaf.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import inspect
from typing import Any, Callable, Iterable, Mapping, Sequence

from . import nmp
from .math_objects import MathAdmission, canonical_json, digest_object
from .math_runtime import CompiledMathPlan, MathRuntime
from .mth_registry import MthPlan
from .mth_system import MthSystem, MthSystemError, MthSystemSlotError
from .wave_ring_scheduler import (
    JAHS_SEAL,
    MC0_SLOTS,
    WaveRingScheduler,
    WaveRingSchedulerError,
    resolve_slot,
)
from .wave_store import WaveStore, WaveStoreError

BRIDGE_SCHEMA = "nanrouter.math-execution.v1"
SUBMISSION_SCHEMA = "nanrouter.math-execution-submission.v1"
LEASE_SCHEMA = "nanrouter.math-execution-lease.v1"
RESULT_SCHEMA = "nanrouter.math-execution-result.v1"
CANCELLATION_SCHEMA = "nanrouter.math-execution-cancellation.v1"
BATCH_SCHEMA = "nanrouter.math-execution-batch.v1"

DEFAULT_LEASE_TICKS = 64
DEFAULT_WORKSPACE_WORD_BYTES = 8


def _token_digest(token: str | None) -> str | None:
    if token is None:
        return None
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


_SECRET_KEYS = frozenset({
    "lease_token", "worker_token", "submit_token", "admin_token",
})


def _redact_secrets(value: Any) -> Any:
    """Recursively replace bearer secrets with one-way digests."""
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            if key in _SECRET_KEYS and isinstance(item, str):
                result[key + "_digest"] = _token_digest(item)
            else:
                result[key] = _redact_secrets(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_redact_secrets(item) for item in value]
    return value


class MathExecutionError(ValueError):
    """Base class for control-plane execution-bridge failures."""


class MathExecutionConfigError(MathExecutionError):
    """The bridge was composed with incompatible components."""


class MathExecutionBindingError(MathExecutionError):
    """A packet, admission, plan, job, or lease binding does not match."""


class MathExecutionStateError(MathExecutionError):
    """The requested operation is not valid in the current control state."""


class MathExecutionRingError(MathExecutionError):
    """The runner ring is not active, healthy, or owned by the wrong slot."""


class MathExecutionGateError(MathExecutionError):
    """The NMP execution gate refused the packet.

    ``decision`` is the original side-effect-free NMP decision so callers can
    preserve the typed failure (for example ``UNAVAILABLE`` versus ``NULL``).
    """

    def __init__(self, decision: nmp.NmpGateDecision) -> None:
        if decision.ok:
            raise ValueError("an accepted gate decision is not an error")
        self.decision = decision
        self.failure = decision.failure
        self.state = decision.failure
        self.reason = decision.reason
        self.checks = dict(decision.checks or {})
        super().__init__(f"{decision.failure}: {decision.reason}")


# Compatibility aliases for callers that prefer shorter names.
ExecutionGateError = MathExecutionGateError
MathExecutionBridgeError = MathExecutionError


class MathExecutionPlanError(MathExecutionError):
    """The supplied object is not a compiled math plan."""


# ---------------------------------------------------------------------------
# Ring binding
# ---------------------------------------------------------------------------


def ring_incarnation_for(target: Any) -> str:
    """Return a stable incarnation id for a scheduler or ring snapshot.

    ``WaveRingScheduler`` versions its activation with ``epoch`` but has no
    separate durable incarnation field.  The stable id is therefore derived
    from the ring's canonical slot identities, not from the current epoch.
    A process restart that keeps the same six slots keeps the same incarnation
    while an explicit replacement ring can use another value.
    """
    if hasattr(target, "snapshot") and callable(target.snapshot):
        snapshot = target.snapshot()
    elif isinstance(target, Mapping):
        snapshot = dict(target)
    else:
        raise MathExecutionConfigError(
            "ring incarnation requires a scheduler or scheduler snapshot"
        )
    slot_ids = snapshot.get("slot_ids") or list(MC0_SLOTS)
    material = "nanrouter.math-execution.ring.v1\0" + "\0".join(
        str(item) for item in slot_ids
    )
    return "ring:" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class MathRingBinding:
    """The active ring identity used to authorize one execution."""

    incarnation: str
    epoch: int
    active_slot: int | None = None
    active_slot_id: str | None = None
    active_alias: str | None = None
    jahs: str | None = None
    started: bool = False
    stale: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.incarnation, str) or not self.incarnation:
            raise MathExecutionConfigError("ring incarnation must be non-empty")
        if isinstance(self.epoch, bool) or not isinstance(self.epoch, int):
            raise MathExecutionConfigError("ring epoch must be an integer")
        if self.epoch < 0:
            raise MathExecutionConfigError("ring epoch must be >= 0")

    @property
    def slot_id(self) -> str | None:
        return self.active_slot_id

    @property
    def seal(self) -> str | None:
        return self.jahs

    def to_dict(self) -> dict[str, Any]:
        return {
            "incarnation": self.incarnation,
            "epoch": self.epoch,
            "active_slot": self.active_slot,
            "active_slot_id": self.active_slot_id,
            "active_alias": self.active_alias,
            "jahs": self.jahs,
            "started": self.started,
            "stale": self.stale,
        }


def _require_int(name: str, value: Any, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise MathExecutionConfigError(f"{name} must be an integer >= {minimum}")
    return value


def _job_payload(job: Any) -> dict[str, Any]:
    if job is None:
        return {}
    raw = job.get("payload_json") if isinstance(job, Mapping) else getattr(
        job, "payload_json", None
    )
    if isinstance(raw, Mapping):
        return dict(raw)
    if isinstance(raw, (str, bytes)):
        import json

        try:
            decoded = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return dict(decoded) if isinstance(decoded, Mapping) else {}
    raw = job.get("payload") if isinstance(job, Mapping) else getattr(job, "payload", None)
    return dict(raw) if isinstance(raw, Mapping) else {}


def lease_row_from_job(job: Any) -> dict[str, Any] | None:
    """Derive a WaveStore-like lease row from the authoritative job row.

    ``WaveStore`` exposes job completion/failure but no public lease lookup.
    The job row already carries the current lease token, epoch, owner and
    deadline, so the projection path can use those fields without a private
    lease ledger.  The derived state is only a read model for ``nmp``.
    """
    if job is None:
        return None
    job_state = str(job.get("state", "") or "").lower()
    token = job.get("lease_token")
    if not token:
        return None
    if job_state == "leased":
        state = "active"
    elif job_state == "done":
        state = "completed"
    elif job_state in {"failed", "dead"}:
        state = "failed"
    else:
        state = None
    if state is None:
        return None
    return {
        "lease_token": token,
        "job_id": job.get("job_id"),
        "lease_owner": job.get("lease_owner"),
        "lease_epoch": job.get("lease_epoch"),
        "acquired_tick": job.get("created_tick"),
        "deadline_tick": job.get("deadline_tick"),
        "released_tick": job.get("updated_tick")
        if state in {"completed", "failed"}
        else None,
        "state": state,
    }


def _normalize_capability_rows(capability: Any) -> list[dict[str, Any]]:
    if capability is None:
        return []
    if isinstance(capability, Mapping):
        return [dict(capability)]
    if isinstance(capability, (str, bytes)):
        raise MathExecutionBindingError("capability must be a row or list of rows")
    rows: list[dict[str, Any]] = []
    try:
        iterator = iter(capability)
    except TypeError as exc:
        raise MathExecutionBindingError(
            "capability must be a row or list of rows"
        ) from exc
    for row in iterator:
        if not isinstance(row, Mapping):
            raise MathExecutionBindingError("capability rows must be objects")
        rows.append(dict(row))
    return rows


def _admission_mapping(admission: Any) -> dict[str, Any]:
    if admission is None:
        return {}
    if isinstance(admission, Mapping):
        return dict(admission)
    to_dict = getattr(admission, "to_dict", None)
    if callable(to_dict):
        data = to_dict()
        if isinstance(data, Mapping):
            return dict(data)
    raise MathExecutionBindingError("admission must be a typed record or object")


def _packet_from(target: Any) -> nmp.NmpPacket:
    if isinstance(target, nmp.NmpPacket):
        return target
    packet = getattr(target, "packet", None)
    if isinstance(packet, nmp.NmpPacket):
        return packet
    if isinstance(target, Mapping):
        packet = target.get("packet")
        if isinstance(packet, nmp.NmpPacket):
            return packet
    raise MathExecutionBindingError("execution target has no NMP packet")


def _job_from(target: Any) -> Mapping[str, Any] | None:
    job = getattr(target, "job", None)
    if isinstance(job, Mapping):
        return job
    if isinstance(target, Mapping):
        job = target.get("job")
        if isinstance(job, Mapping):
            return job
    return None


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MathExecutionSubmission:
    """A queued math execution and the durable job it points at."""

    packet: nmp.NmpPacket
    compiled: CompiledMathPlan
    job: Mapping[str, Any]
    job_id: str
    dedupe_key: str
    duplicate: bool = False
    subscribers: tuple[str, ...] = ()
    gate: nmp.NmpGateDecision | None = None
    batch_id: str | None = None
    batch_index: int | None = None
    parent_packet_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "job", dict(self.job))
        object.__setattr__(self, "subscribers", tuple(self.subscribers))

    @property
    def packet_id(self) -> str:
        return self.packet.packet_id

    @property
    def state(self) -> str:
        return self.packet.state

    @property
    def job_state(self) -> str | None:
        return self.job.get("state")

    @property
    def result_digest(self) -> str | None:
        return self.packet.result_digest or self.job.get("result_digest")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SUBMISSION_SCHEMA,
            "packet_id": self.packet_id,
            "state": self.state,
            "job_id": self.job_id,
            "job_state": self.job_state,
            "dedupe_key": self.dedupe_key,
            "duplicate": self.duplicate,
            "subscribers": list(self.subscribers),
            "batch_id": self.batch_id,
            "batch_index": self.batch_index,
            "parent_packet_id": self.parent_packet_id,
            "gate": None if self.gate is None else self.gate.to_dict(),
            "packet": self.packet.to_dict(),
            "job": _redact_secrets(dict(self.job)),
            "plan": self.compiled.plan.to_dict(),
        }


@dataclass(frozen=True)
class MathExecutionLease:
    """One active lease acquired on the scheduler's active runner slot."""

    packet: nmp.NmpPacket
    job: Mapping[str, Any]
    job_id: str
    lease_token: str
    lease_epoch: int
    owner: str
    deadline_tick: int | None
    ring: MathRingBinding | None = None
    workspace_words: int = 0
    memory_bytes: int = 0
    ring_registered: bool = True
    duplicate: bool = False
    submission: MathExecutionSubmission | None = None
    plan: MthPlan | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "job", dict(self.job))

    @property
    def packet_id(self) -> str:
        return self.packet.packet_id

    @property
    def state(self) -> str:
        return self.packet.state

    @property
    def job_state(self) -> str | None:
        return self.job.get("state")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": LEASE_SCHEMA,
            "packet_id": self.packet_id,
            "state": self.state,
            "job_id": self.job_id,
            "job_state": self.job_state,
            "lease_token_digest": _token_digest(self.lease_token),
            "lease_epoch": self.lease_epoch,
            "owner": self.owner,
            "deadline_tick": self.deadline_tick,
            "ring": None if self.ring is None else self.ring.to_dict(),
            "workspace_words": self.workspace_words,
            "memory_bytes": self.memory_bytes,
            "ring_registered": self.ring_registered,
            "duplicate": self.duplicate,
            "packet": self.packet.to_dict(),
            "job": _redact_secrets(dict(self.job)),
        }


@dataclass(frozen=True)
class MathExecutionResult:
    """Terminal completion or failure of a leased math job."""

    packet: nmp.NmpPacket
    job: Mapping[str, Any]
    job_id: str
    lease_token: str | None
    lease_epoch: int | None
    outcome: str
    result_digest: str | None = None
    result_status: str | None = None
    output_leaf_id: str | None = None
    committed: bool = False
    ring_released: bool = False
    duplicate: bool = False
    projection: nmp.NmpProjection | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "job", dict(self.job))

    @property
    def packet_id(self) -> str:
        return self.packet.packet_id

    @property
    def state(self) -> str:
        return self.packet.state

    @property
    def job_state(self) -> str | None:
        return self.job.get("state")

    @property
    def ok(self) -> bool:
        return self.outcome in {nmp.COMPLETED, nmp.COMMITTED}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RESULT_SCHEMA,
            "packet_id": self.packet_id,
            "state": self.state,
            "job_id": self.job_id,
            "job_state": self.job_state,
            "lease_token_digest": _token_digest(self.lease_token),
            "lease_epoch": self.lease_epoch,
            "outcome": self.outcome,
            "result_digest": self.result_digest,
            "result_status": self.result_status,
            "output_leaf_id": self.output_leaf_id,
            "committed": self.committed,
            "ring_released": self.ring_released,
            "duplicate": self.duplicate,
            "packet": self.packet.to_dict(),
            "job": _redact_secrets(dict(self.job)),
            "projection": None if self.projection is None else _redact_secrets(self.projection.to_dict()),
        }


@dataclass(frozen=True)
class MathExecutionCancellation:
    """Cooperative cancellation result for a queued or leased packet."""

    packet: nmp.NmpPacket
    job: Mapping[str, Any] | None
    job_id: str | None
    status: str
    reason: str | None
    cancel_epoch: int
    action: str = "none"
    ring_released: bool = False
    projection: nmp.NmpProjection | None = None

    def __post_init__(self) -> None:
        if self.job is not None:
            object.__setattr__(self, "job", dict(self.job))

    @property
    def cancelled(self) -> bool:
        return self.status == "cancelled"

    @property
    def pending(self) -> bool:
        return self.status == "requested"

    @property
    def too_late(self) -> bool:
        return self.status == "too_late"

    @property
    def state(self) -> str:
        return self.packet.state

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CANCELLATION_SCHEMA,
            "packet_id": self.packet.packet_id,
            "state": self.state,
            "job_id": self.job_id,
            "status": self.status,
            "reason": self.reason,
            "cancel_epoch": self.cancel_epoch,
            "action": self.action,
            "ring_released": self.ring_released,
            "packet": self.packet.to_dict(),
            "job": None if self.job is None else dict(self.job),
            "projection": None if self.projection is None else _redact_secrets(self.projection.to_dict()),
        }


@dataclass(frozen=True)
class MathExecutionBatchSubmission:
    """Independent child submissions inside one NMP batch envelope."""

    batch: nmp.NmpBatch
    children: tuple[MathExecutionSubmission, ...]
    batch_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "children", tuple(self.children))

    @property
    def parent(self) -> nmp.NmpPacket:
        return self.batch.parent

    @property
    def job_ids(self) -> tuple[str, ...]:
        return tuple(child.job_id for child in self.children)

    @property
    def parent_lease(self) -> None:
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": BATCH_SCHEMA,
            "batch_id": self.batch_id,
            "parent_packet_id": self.parent.packet_id,
            "parent_lease": None,
            "job_ids": list(self.job_ids),
            "children": [child.to_dict() for child in self.children],
        }


# ---------------------------------------------------------------------------
# Bridge
# ---------------------------------------------------------------------------


class MathExecutionBridge:
    """Bind NMP authorization to one MthSystem/WaveStore/ring execution.

    The object keeps only two pieces of process-local state: the explicitly
    in-memory NMP duplicate table and a small map of ring resources that this
    process acquired.  Neither is durable truth.  Restart recovery calls
    :meth:`project`/:meth:`restart`, which read WaveStore job rows and derive
    the lease read model with :func:`lease_row_from_job`.
    """

    durable = False
    owns_jobs = False
    owns_lease_ledger = False

    def __init__(
        self,
        runtime: MathRuntime,
        system: MthSystem | None = None,
        *,
        store: WaveStore | None = None,
        scheduler: WaveRingScheduler | None = None,
        submit_token: str | None = None,
        worker_token: str | None = None,
        ring_incarnation: str | None = None,
        lease_ticks: int = DEFAULT_LEASE_TICKS,
        workspace_word_bytes: int | None = None,
    ) -> None:
        if not isinstance(runtime, MathRuntime):
            raise MathExecutionConfigError("runtime must be a MathRuntime")
        resolved_system = system if system is not None else runtime.system
        if resolved_system is not None and not isinstance(resolved_system, MthSystem):
            raise MathExecutionConfigError("system must be an MthSystem")
        resolved_store = store
        if resolved_store is None and resolved_system is not None:
            resolved_store = resolved_system.store
        if resolved_store is not None and not isinstance(resolved_store, WaveStore):
            raise MathExecutionConfigError("store must be a WaveStore")
        resolved_scheduler = scheduler
        if resolved_scheduler is None and resolved_system is not None:
            resolved_scheduler = resolved_system.scheduler
        if resolved_scheduler is not None and not isinstance(
            resolved_scheduler, WaveRingScheduler
        ):
            raise MathExecutionConfigError("scheduler must be a WaveRingScheduler")
        if resolved_system is not None:
            if resolved_store is not None and resolved_system.store is not resolved_store:
                raise MathExecutionConfigError(
                    "bridge and MthSystem must share one WaveStore"
                )
            if (
                resolved_scheduler is not None
                and resolved_system.scheduler is not resolved_scheduler
            ):
                raise MathExecutionConfigError(
                    "bridge and MthSystem must share one runner ring"
                )
        if submit_token is not None and not isinstance(submit_token, str):
            raise MathExecutionConfigError("submit_token must be a string")
        if worker_token is not None and not isinstance(worker_token, str):
            raise MathExecutionConfigError("worker_token must be a string")
        if ring_incarnation is not None and (
            not isinstance(ring_incarnation, str) or not ring_incarnation
        ):
            raise MathExecutionConfigError("ring_incarnation must be non-empty")

        self.runtime = runtime
        self.system = resolved_system
        self.store = resolved_store
        self.scheduler = resolved_scheduler
        self.submit_token = submit_token
        self.worker_token = worker_token
        self.ring_incarnation = ring_incarnation
        self.lease_ticks = _require_int("lease_ticks", lease_ticks, minimum=1)
        if workspace_word_bytes is None:
            workspace_word_bytes = (
                resolved_system.workspace_word_bytes
                if resolved_system is not None
                else DEFAULT_WORKSPACE_WORD_BYTES
            )
        self.workspace_word_bytes = _require_int(
            "workspace_word_bytes", workspace_word_bytes, minimum=1
        )
        # Explicitly non-durable duplicate index.
        self._dedupe = nmp.NmpInFlightTable()
        # Process-local ring accounting for resources this bridge registered.
        # This is not a job/lease ledger; it exists only so release is exactly
        # once per locally acquired scheduler lease.
        self._ring_resources: dict[tuple[str, int], tuple[str, int]] = {}

    def __repr__(self) -> str:
        return (
            "MathExecutionBridge("
            f"store={'yes' if self.store is not None else 'no'}, "
            f"scheduler={'yes' if self.scheduler is not None else 'no'})"
        )

    # -- ring ---------------------------------------------------------------

    @property
    def ring_active(self) -> bool:
        if self.scheduler is None:
            return False
        snapshot = self.scheduler.snapshot()
        return bool(snapshot.get("started")) and snapshot.get("active_slot") is not None

    def ring_binding(
        self,
        *,
        now_tick: int | None = None,
        require_active: bool = True,
    ) -> MathRingBinding:
        """Return the current active ring identity and validate its JAHS seal."""
        if self.scheduler is None:
            if self.ring_incarnation is None:
                if require_active:
                    raise MathExecutionRingError("no runner ring is configured")
                return MathRingBinding("ring:unconfigured", 0)
            if require_active:
                raise MathExecutionRingError("no runner ring is configured")
            return MathRingBinding(self.ring_incarnation, 0)
        snapshot = self.scheduler.snapshot(now_tick)
        incarnation = self.ring_incarnation or ring_incarnation_for(snapshot)
        epoch = int(snapshot.get("epoch") or 0)
        jahs = snapshot.get("jahs")
        seal = jahs.get("seal") if isinstance(jahs, Mapping) else None
        binding = MathRingBinding(
            incarnation=incarnation,
            epoch=epoch,
            active_slot=snapshot.get("active_slot"),
            active_slot_id=snapshot.get("active_slot_id"),
            active_alias=snapshot.get("active_alias"),
            jahs=seal,
            started=bool(snapshot.get("started")),
            stale=bool(snapshot.get("stale")),
        )
        if require_active:
            if not binding.started or binding.active_slot is None:
                raise MathExecutionRingError("runner ring has no active slot")
            if binding.jahs != JAHS_SEAL:
                raise MathExecutionRingError(
                    "runner ring handoff seal is missing; JAHS gate not satisfied"
                )
            if binding.stale:
                raise MathExecutionRingError("active runner slot heartbeat is stale")
            if binding.epoch < 1:
                raise MathExecutionRingError("runner ring has no activated epoch")
        return binding

    def _assert_owner(self, owner: str | None, binding: MathRingBinding) -> str:
        if binding.active_slot is None:
            raise MathExecutionRingError("runner ring has no active slot")
        if owner is None:
            if binding.active_slot_id is None:
                raise MathExecutionRingError("active runner slot has no id")
            return binding.active_slot_id
        try:
            index = resolve_slot(owner)
        except WaveRingSchedulerError as exc:
            raise MathExecutionRingError(str(exc)) from exc
        if index != binding.active_slot:
            raise MathExecutionRingError(
                f"lease owner {owner!r} is not the active runner slot"
            )
        return owner

    def _active_slot_identities(self, binding: MathRingBinding) -> set[str]:
        return {
            value
            for value in (binding.active_slot_id, binding.active_alias)
            if isinstance(value, str) and value
        }

    # -- packet preparation -------------------------------------------------

    def prepare_packet(
        self,
        compiled: CompiledMathPlan,
        *,
        lane_id: int = 0,
        capability_set: Any = (),
        capability_epoch: int = 1,
        guest_words: int | None = None,
        ruleset_id: str = "",
        ruleset_version: int = 1,
        request_id: str | None = None,
        ring: MathRingBinding | None = None,
    ) -> nmp.NmpPacket:
        """Prepare an NMP packet bound to the bridge's current ring identity.

        NMP requires a positive guest-workspace declaration even for a
        zero-workspace native kernel.  The bridge therefore binds at least a
        one-word guard bound; the compiled plan and the job keep the real
        (possibly zero) workspace bound.
        """
        if not isinstance(compiled, CompiledMathPlan):
            raise MathExecutionPlanError("compiled must be a CompiledMathPlan")
        binding = ring if ring is not None else self.ring_binding(require_active=False)
        workspace = max(
            1,
            int(compiled.workspace_words),
            int(guest_words or 0),
        )
        caps = capability_set
        if not caps:
            caps = (
                {
                    "required": compiled.plan.steps[0].kernel_id,
                    "workspace": workspace,
                },
            )
        return self.runtime.prepare_packet(
            compiled,
            lane_id=lane_id,
            capability_set=caps,
            capability_epoch=capability_epoch,
            ring_incarnation=binding.incarnation,
            ring_epoch=binding.epoch,
            guest_words=workspace,
            ruleset_id=ruleset_id,
            ruleset_version=ruleset_version,
            request_id=request_id,
        )

    # Compatibility alias.
    prepare = prepare_packet

    # -- gate ---------------------------------------------------------------

    def _validate_compiled_binding(
        self,
        packet: nmp.NmpPacket,
        compiled: CompiledMathPlan,
        admission: Any = None,
    ) -> None:
        if not isinstance(packet, nmp.NmpPacket):
            raise MathExecutionBindingError("a prepared NmpPacket is required")
        if not isinstance(compiled, CompiledMathPlan):
            raise MathExecutionPlanError("compiled must be a CompiledMathPlan")
        if packet.candidate_id != compiled.candidate.candidate_id:
            raise MathExecutionBindingError(
                "packet candidate does not match the compiled candidate"
            )
        if compiled.admission.candidate_id != compiled.candidate.candidate_id:
            raise MathExecutionBindingError(
                "compiled admission is bound to a different candidate"
            )
        if compiled.candidate.snapshot_id and (
            compiled.admission.snapshot_id != compiled.candidate.snapshot_id
        ):
            raise MathExecutionBindingError(
                "compiled admission is bound to a different snapshot"
            )
        if compiled.function.function_id != compiled.candidate.function_id:
            raise MathExecutionBindingError(
                "compiled function does not match the candidate"
            )
        if compiled.function.version != compiled.candidate.function_version:
            raise MathExecutionBindingError(
                "compiled function version does not match the candidate"
            )
        selected = (
            (compiled.admission.scope or {}).get("capability", {}) or {}
        ).get("selected") or {}
        selected_kernel = selected.get("kernel_id")
        if selected_kernel and tuple(compiled.plan.kernel_ids) != (
            selected_kernel,
        ):
            raise MathExecutionBindingError(
                "compiled plan kernel does not match the admission-selected kernel"
            )
        if packet.function_id != compiled.function.function_id:
            raise MathExecutionBindingError(
                "packet function does not match the compiled function"
            )
        if packet.function_version != compiled.function.version:
            raise MathExecutionBindingError(
                "packet function version does not match the compiled function"
            )
        if packet.snapshot_id != compiled.admission.snapshot_id:
            raise MathExecutionBindingError(
                "packet snapshot does not match the compiled admission"
            )
        if packet.admission_id and compiled.admission.admission_id:
            if packet.admission_id != compiled.admission.admission_id:
                raise MathExecutionBindingError(
                    "packet admission_id does not match the compiled admission"
                )
        if compiled.admission.rule_snapshot_id and packet.ruleset_snapshot_id:
            if packet.ruleset_snapshot_id != compiled.admission.rule_snapshot_id:
                raise MathExecutionBindingError(
                    "packet ruleset snapshot does not match the compiled admission"
                )
        if compiled.admission.preflight_digest and packet.preflight_digest:
            supplied = nmp.normalize_digest(
                compiled.admission.preflight_digest, "preflight_digest"
            )
            if supplied != packet.preflight_digest:
                raise MathExecutionBindingError(
                    "packet preflight digest does not match the compiled admission"
                )
        if packet.plan_digest is not None:
            expected = digest_object(compiled.plan.to_dict())
            if packet.plan_digest != expected:
                raise MathExecutionBindingError(
                    "packet plan digest does not match the compiled MthPlan"
                )
        if packet.guest_words and packet.guest_words < compiled.workspace_words:
            raise MathExecutionBindingError(
                "packet guest workspace is below the compiled plan bound"
            )
        external = _admission_mapping(admission) if admission is not None else {}
        if external:
            external_id = external.get("admission_id")
            if external_id and packet.admission_id and (
                str(external_id) != packet.admission_id
            ):
                raise MathExecutionBindingError(
                    "supplied admission_id does not match the packet"
                )
            external_candidate = external.get("candidate_id")
            if external_candidate and str(external_candidate) != packet.candidate_id:
                raise MathExecutionBindingError(
                    "supplied admission candidate does not match the packet"
                )
            external_snapshot = external.get("snapshot_id")
            if external_snapshot and str(external_snapshot) != packet.snapshot_id:
                raise MathExecutionBindingError(
                    "supplied admission snapshot does not match the packet"
                )

    def _gate_packet(
        self,
        packet: nmp.NmpPacket,
        compiled: CompiledMathPlan | None,
    ) -> tuple[nmp.NmpPacket, int, bool]:
        """Return (packet to gate, real workspace, guard-word normalized)."""
        if compiled is None:
            return packet, int(packet.guest_words or 0), False
        workspace = int(compiled.workspace_words)
        if packet.guest_words > 0:
            return packet, max(workspace, packet.guest_words), False
        if workspace == 0:
            # A zero-workspace native kernel still needs a non-null NMP
            # workspace declaration.  Use one guard word for the gate only.
            return replace(packet, guest_words=1), 0, True
        return packet, workspace, False

    def _augment_capabilities(
        self,
        rows: Iterable[Mapping[str, Any]],
        packet: nmp.NmpPacket,
        binding: MathRingBinding,
        *,
        guard_normalized: bool,
    ) -> list[dict[str, Any]]:
        active = self._active_slot_identities(binding)
        result: list[dict[str, Any]] = []
        for row in rows:
            candidate = dict(row)
            if candidate.get("function_id") is None:
                candidate["function_id"] = packet.function_id
            if guard_normalized:
                workspace = candidate.get("workspace", candidate.get("guest_words", 0))
                if isinstance(workspace, int) and not isinstance(workspace, bool):
                    if workspace < 1:
                        candidate["workspace"] = 1
            runner = candidate.get("runner_id")
            if active and isinstance(runner, str) and runner not in active:
                continue
            result.append(candidate)
        return result

    def _resolve_capabilities(
        self,
        packet: nmp.NmpPacket,
        compiled: CompiledMathPlan | None,
        capability: Any,
        binding: MathRingBinding,
        *,
        workspace: int,
        guard_normalized: bool,
        allow_declared: bool,
        kernel_ids: Sequence[str] = (),
    ) -> list[dict[str, Any]]:
        if capability is not None:
            rows = _normalize_capability_rows(capability)
            return self._augment_capabilities(
                rows, packet, binding, guard_normalized=guard_normalized
            )
        if self.store is None:
            return []
        if compiled is not None:
            descriptors = [
                self.runtime.functions.implementation_registry.require(kernel)
                for kernel in compiled.plan.kernel_ids
            ]
        elif kernel_ids:
            descriptors = []
            for kernel in kernel_ids:
                try:
                    descriptors.append(
                        self.runtime.functions.implementation_registry.require(kernel)
                    )
                except Exception:
                    descriptors = []
                    break
        else:
            return []
        rows: list[dict[str, Any]] = []
        for descriptor in descriptors:
            found = self.store.dispatchable_capabilities(
                workspace=workspace,
                operator_digest=descriptor.source_digest,
                precision=descriptor.precision,
            )
            rows.extend(found)
        return self._augment_capabilities(
            rows, packet, binding, guard_normalized=guard_normalized
        )

    def check(
        self,
        packet: nmp.NmpPacket,
        compiled: CompiledMathPlan | None = None,
        *,
        admission: Any = None,
        capability: Any = None,
        ruleset_snapshot: Any = None,
        cancel_epoch: int | None = None,
        workspace: int | None = None,
        allow_declared: bool = False,
        job: Any = None,
        lease: Any = None,
        now_tick: int | None = None,
        ring: MathRingBinding | None = None,
        kernel_ids: Sequence[str] = (),
    ) -> nmp.NmpGateDecision:
        """Evaluate the NMP execution gate without changing any state.

        The active ring identity is always part of the check.  Missing
        capability and missing workspace remain ``UNAVAILABLE``; an admission
        whose typed verdict is ``NULL`` remains ``NULL``.
        """
        if not isinstance(packet, nmp.NmpPacket):
            raise MathExecutionBindingError("a prepared NmpPacket is required")
        binding = ring if ring is not None else self.ring_binding(require_active=False)
        gate_packet, required_workspace, normalized = self._gate_packet(
            packet, compiled
        )
        if workspace is not None:
            _require_int("workspace", workspace)
            required_workspace = max(required_workspace, workspace)
        kernels: list[str] = list(kernel_ids)
        if compiled is not None:
            kernels = list(compiled.plan.kernel_ids)
        if not kernels and self.store is not None:
            payload = _job_payload(job)
            operator_id = None
            if isinstance(job, Mapping):
                operator_id = job.get("operator_id")
            operator_id = operator_id or payload.get("operator_id")
            if isinstance(operator_id, str) and operator_id:
                kernels = [operator_id]
        capabilities = self._resolve_capabilities(
            gate_packet,
            compiled,
            capability,
            binding,
            workspace=required_workspace,
            guard_normalized=normalized,
            allow_declared=allow_declared,
            kernel_ids=kernels,
        )
        admission_record: Any = admission
        if admission_record is None and compiled is not None:
            admission_record = compiled.admission
        preflight = {
            "result": packet.preflight_result or "VALID",
            "digest": packet.preflight_digest,
            "rule_snapshot_id": packet.ruleset_snapshot_id or None,
        }
        current_ruleset = (
            ruleset_snapshot
            if ruleset_snapshot is not None
            else (packet.ruleset_snapshot_id or None)
        )
        if cancel_epoch is None:
            payload = _job_payload(job)
            payload_cancel = payload.get("cancel_epoch")
            if isinstance(payload_cancel, int) and not isinstance(payload_cancel, bool):
                cancel_epoch = max(packet.cancel_epoch, payload_cancel)
            else:
                cancel_epoch = packet.cancel_epoch

        if not kernels:
            return nmp.execution_gate(
                gate_packet,
                admission=admission_record,
                preflight=preflight,
                capability=capabilities,
                ruleset_snapshot=current_ruleset,
                ring_incarnation=binding.incarnation,
                ring_epoch=binding.epoch,
                cancel_epoch=cancel_epoch,
                workspace=required_workspace,
                allow_declared=allow_declared,
                job=job,
                lease=lease,
                now_tick=now_tick,
            )

        last: nmp.NmpGateDecision | None = None
        workspace_requirement = max(
            required_workspace,
            max(
                (
                    int(item.get("workspace") or 0)
                    for item in gate_packet.capability_set
                ),
                default=0,
            ),
        )
        for kernel in kernels:
            decision = nmp.execution_gate(
                gate_packet,
                admission=admission_record,
                preflight=preflight,
                capability=capabilities,
                ruleset_snapshot=current_ruleset,
                ring_incarnation=binding.incarnation,
                ring_epoch=binding.epoch,
                cancel_epoch=cancel_epoch,
                required_capability={
                    "kernel_id": kernel,
                    "workspace": workspace_requirement,
                },
                workspace=required_workspace,
                allow_declared=allow_declared,
                job=job,
                lease=lease,
                now_tick=now_tick,
            )
            if not decision.ok:
                return decision
            last = decision
        assert last is not None
        return last

    # -- submit -------------------------------------------------------------

    @staticmethod
    def default_job_id(packet: nmp.NmpPacket) -> str:
        if ":" in packet.packet_id:
            suffix = packet.packet_id.split(":", 1)[1]
        else:
            suffix = digest_object(packet.to_dict())
        return "job:" + suffix

    def _find_job_by_dedupe(self, key: str) -> Mapping[str, Any] | None:
        if self.store is None or not key:
            return None
        matches: list[Mapping[str, Any]] = []
        for job in self.store.list_jobs(limit=1024):
            payload = _job_payload(job)
            if payload.get("nmp_dedupe_key") == key:
                matches.append(job)
        if not matches:
            return None
        for job in matches:
            if str(job.get("state")) == "done":
                return job
        return matches[0]

    def _find_job_for_packet(self, packet: nmp.NmpPacket) -> Mapping[str, Any] | None:
        if self.store is None:
            return None
        if packet.job_id:
            job = self.store.get_job(packet.job_id)
            if job is not None:
                return job
        key = packet.dedupe_key
        for job in self.store.list_jobs(limit=1024):
            payload = _job_payload(job)
            if payload.get("nmp_packet_id") == packet.packet_id:
                return job
            if key and payload.get("nmp_dedupe_key") == key:
                return job
        return None

    def _remember_packet(self, packet: nmp.NmpPacket) -> None:
        key = packet.dedupe_key
        if self._dedupe.lookup(key) is None:
            self._dedupe.put(packet)
        else:
            self._dedupe.replace(packet)

    def _binding_payload(
        self,
        packet: nmp.NmpPacket,
        compiled: CompiledMathPlan,
        admission: Any,
    ) -> dict[str, Any]:
        admission_record = (
            admission if admission is not None else compiled.admission
        )
        admission_data = _admission_mapping(admission_record)
        plan = compiled.plan
        return {
            "schema": BRIDGE_SCHEMA,
            "nmp_packet_id": packet.packet_id,
            "nmp_dedupe_key": packet.dedupe_key,
            "nmp_candidate_id": packet.candidate_id,
            "nmp_lane_id": packet.lane_id,
            "nmp_state": packet.state,
            "admission_id": packet.admission_id
            or admission_data.get("admission_id"),
            "admission_verdict": packet.admission_verdict
            or admission_data.get("verdict"),
            "math_admission": admission_data,
            "math_snapshot_id": packet.snapshot_id,
            "snapshot_id": packet.snapshot_id,
            "preflight_digest": packet.preflight_digest,
            "preflight_result": packet.preflight_result,
            "ruleset_id": packet.ruleset_id,
            "ruleset_version": packet.ruleset_version,
            "ruleset_snapshot_id": packet.ruleset_snapshot_id,
            "ring_incarnation": packet.ring_incarnation,
            "ring_epoch": packet.ring_epoch,
            "cancel_epoch": packet.cancel_epoch,
            "capability_set_digest": packet.capability_set_digest,
            "capability_epoch": packet.capability_epoch,
            "guest_words": packet.guest_words,
            "workspace_words": int(compiled.workspace_words),
            "plan_id": plan.plan_id,
            "plan_digest": digest_object(plan.to_dict()),
            "kernel_ids": list(plan.kernel_ids),
            "batch_id": packet.batch_id,
            "batch_index": packet.batch_index,
            "batch_count": packet.batch_count,
            "parent_packet_id": packet.parent_packet_id,
        }

    @staticmethod
    def _coerce_packet_and_compiled(
        first: Any, second: Any = None
    ) -> tuple[nmp.NmpPacket, CompiledMathPlan | None]:
        if isinstance(first, CompiledMathPlan):
            second, first = first, second
        if not isinstance(first, nmp.NmpPacket):
            raise MathExecutionBindingError("a prepared NmpPacket is required")
        if second is not None and not isinstance(second, CompiledMathPlan):
            raise MathExecutionPlanError("compiled must be a CompiledMathPlan")
        return first, second

    def submit(
        self,
        packet: nmp.NmpPacket | CompiledMathPlan,
        compiled: CompiledMathPlan | nmp.NmpPacket | None = None,
        *,
        admission: Any = None,
        job_id: str | None = None,
        universe_id: str | None = None,
        generation: int | None = None,
        payload: Mapping[str, Any] | None = None,
        now_tick: int = 0,
        submit_token: str | None = None,
        capability: Any = None,
        ruleset_snapshot: Any = None,
        cancel_epoch: int | None = None,
        workspace: int | None = None,
        allow_declared: bool = False,
    ) -> MathExecutionSubmission:
        """Gate and enqueue one prepared packet's compiled plan.

        The packet must be ``PREFLIGHTED``.  Submission never leases a job; it
        only moves the packet to ``QUEUED`` after the job row exists.  A
        duplicate operation key reuses the existing WaveStore job and never
        creates a second execution.
        """
        packet, compiled = self._coerce_packet_and_compiled(packet, compiled)
        self._validate_current_rules(packet)
        if compiled is None:
            raise MathExecutionPlanError("submit requires a compiled MthPlan")
        if self.system is None or self.store is None:
            raise MathExecutionConfigError("submit requires an MthSystem and WaveStore")
        if packet.is_batch_parent:
            raise MathExecutionStateError(
                "a batch parent is a control envelope and cannot be submitted"
            )
        if packet.state != nmp.PREFLIGHTED:
            raise MathExecutionStateError(
                f"submit requires PREFLIGHTED, packet is {packet.state}"
            )
        _require_int("now_tick", now_tick)
        self._validate_compiled_binding(packet, compiled, admission)
        if generation is None:
            generation = packet.generation
        if not isinstance(generation, int) or isinstance(generation, bool):
            raise MathExecutionBindingError("generation must be an integer")
        if generation != packet.generation:
            raise MathExecutionBindingError(
                "job generation must equal the packet generation"
            )
        if payload is not None and not isinstance(payload, Mapping):
            raise MathExecutionBindingError("payload must be an object")
        universe = universe_id or packet.universe_id
        job_id = job_id or self.default_job_id(packet)
        if not isinstance(job_id, str) or not job_id:
            raise MathExecutionBindingError("job_id must be non-empty")
        binding = self.ring_binding(now_tick=now_tick, require_active=True)
        decision = self.check(
            packet,
            compiled,
            admission=admission,
            capability=capability,
            ruleset_snapshot=ruleset_snapshot,
            cancel_epoch=cancel_epoch,
            workspace=workspace,
            allow_declared=allow_declared,
            now_tick=now_tick,
            ring=binding,
        )
        if not decision.ok:
            raise MathExecutionGateError(decision)

        existing = self._find_job_by_dedupe(packet.dedupe_key)
        if existing is not None:
            bound = replace(packet, job_id=str(existing.get("job_id") or job_id))
            projection = self.project(bound, job=existing, now_tick=now_tick)
            duplicate_packet = (
                projection.to_packet(bound, tick=now_tick)
                if projection.supported and projection.state is not None
                else bound
            )
            if projection.supported and projection.state is not None:
                duplicate_packet = replace(
                    duplicate_packet,
                    job_id=str(existing.get("job_id") or job_id),
                )
            self._dedupe.subscribe(packet.dedupe_key, packet.packet_id)
            if self._dedupe.lookup(packet.dedupe_key) is None:
                self._dedupe.put(duplicate_packet)
            return MathExecutionSubmission(
                packet=duplicate_packet,
                compiled=compiled,
                job=existing,
                job_id=str(existing.get("job_id") or job_id),
                dedupe_key=packet.dedupe_key,
                duplicate=True,
                subscribers=(packet.packet_id,),
                gate=decision,
                batch_id=packet.batch_id,
                batch_index=packet.batch_index,
                parent_packet_id=packet.parent_packet_id,
            )

        in_flight = self._dedupe.put(packet)
        if in_flight.duplicate:
            # The only non-durable entry without an authoritative job is a
            # previous failed submission attempt; replace it.
            if in_flight.existing is not None and not in_flight.existing.job_id:
                self._dedupe.remove(packet.dedupe_key)
                self._dedupe.put(packet)
            else:
                raise MathExecutionStateError(
                    "duplicate operation is already in flight without a job row"
                )

        bound_payload = dict(payload or {})
        bound_payload.update(self._binding_payload(packet, compiled, admission))
        token = submit_token if submit_token is not None else self.submit_token
        if token is None:
            raise MathExecutionConfigError("submit requires a submit token")
        try:
            job = self.runtime.submit(
                compiled,
                token,
                job_id,
                universe,
                generation,
                payload=bound_payload,
                now_tick=now_tick,
                nmp_packet=packet,
            )
            queued = packet.queue(gate=decision, tick=now_tick)
            queued = replace(
                queued,
                job_id=job_id,
                updated_tick=now_tick or queued.updated_tick,
                evidence={
                    **dict(queued.evidence),
                    "submission": {
                        "job_id": job_id,
                        "dedupe_key": packet.dedupe_key,
                        "plan_digest": bound_payload["plan_digest"],
                        "snapshot_id": packet.snapshot_id,
                        "preflight_digest": packet.preflight_digest,
                        "ring_incarnation": packet.ring_incarnation,
                        "ring_epoch": packet.ring_epoch,
                    },
                },
            )
        except Exception:
            self._dedupe.remove(packet.dedupe_key)
            raise
        self._dedupe.replace(queued)
        return MathExecutionSubmission(
            packet=queued,
            compiled=compiled,
            job=job,
            job_id=job_id,
            dedupe_key=packet.dedupe_key,
            duplicate=False,
            subscribers=(queued.packet_id,),
            gate=decision,
            batch_id=queued.batch_id,
            batch_index=queued.batch_index,
            parent_packet_id=queued.parent_packet_id,
        )

    # -- batch --------------------------------------------------------------

    def _compiled_for_child(
        self,
        compiled: Any,
        child: nmp.NmpPacket,
        index: int,
    ) -> CompiledMathPlan:
        if isinstance(compiled, CompiledMathPlan):
            return compiled
        if callable(compiled):
            value = compiled(child)
        elif isinstance(compiled, Mapping):
            if child.packet_id in compiled:
                value = compiled[child.packet_id]
            elif index in compiled:
                value = compiled[index]
            elif str(index) in compiled:
                value = compiled[str(index)]
            else:
                raise MathExecutionPlanError(
                    f"no compiled plan for batch child {child.packet_id}"
                )
        elif isinstance(compiled, Sequence) and not isinstance(
            compiled, (str, bytes)
        ):
            try:
                value = compiled[index]
            except IndexError as exc:
                raise MathExecutionPlanError(
                    "compiled plan list is shorter than the batch"
                ) from exc
        else:
            raise MathExecutionPlanError(
                "compiled must be a plan, sequence, mapping, or callable"
            )
        if not isinstance(value, CompiledMathPlan):
            raise MathExecutionPlanError(
                f"batch child {index} has no CompiledMathPlan"
            )
        return value

    def submit_batch(
        self,
        batch: nmp.NmpBatch,
        compiled: Any,
        *,
        job_ids: Mapping[int | str, str] | Sequence[str] | None = None,
        job_id_prefix: str = "",
        **kwargs: Any,
    ) -> MathExecutionBatchSubmission:
        """Submit every child independently; the parent is never leased.

        Dedupe still applies per child content key.  Children with distinct
        operations receive distinct jobs; children that are content-identical
        deliberately share the existing job rather than executing twice.
        """
        if not isinstance(batch, nmp.NmpBatch):
            raise MathExecutionBindingError("batch must be an NmpBatch")
        if batch.parent.job_id is not None or batch.parent.lease_epoch is not None:
            raise MathExecutionStateError("a batch parent must not hold a lease")
        if batch.parent.state in {
            nmp.QUEUED,
            nmp.EXECUTING,
            nmp.COMPLETED,
            nmp.COMMITTED,
        }:
            raise MathExecutionStateError(
                "a batch parent cannot enter an execution state"
            )
        children: list[MathExecutionSubmission] = []
        for index, child in enumerate(batch.children):
            child_compiled = self._compiled_for_child(compiled, child, index)
            child_job_id = None
            if job_ids is not None:
                if isinstance(job_ids, Mapping):
                    child_job_id = job_ids.get(index) or job_ids.get(child.packet_id)
                else:
                    try:
                        child_job_id = job_ids[index]
                    except IndexError:
                        child_job_id = None
            if child_job_id is None:
                child_job_id = (
                    f"{job_id_prefix}{index}" if job_id_prefix else None
                )
            children.append(
                self.submit(
                    child,
                    child_compiled,
                    job_id=child_job_id,
                    **kwargs,
                )
            )
        return MathExecutionBatchSubmission(
            batch=batch,
            children=tuple(children),
            batch_id=str(batch.batch_id),
        )

    # -- job binding --------------------------------------------------------

    def _job_for(
        self,
        packet: nmp.NmpPacket,
        job: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        resolved = job if job is not None else self._find_job_for_packet(packet)
        if resolved is None:
            raise MathExecutionBindingError(
                f"no WaveStore job supports packet {packet.packet_id}"
            )
        return resolved

    def _validate_job_binding(
        self,
        packet: nmp.NmpPacket,
        job: Mapping[str, Any],
    ) -> dict[str, Any]:
        payload = _job_payload(job)
        job_id = job.get("job_id")
        if packet.job_id is not None and job_id is not None and (
            str(job_id) != packet.job_id
        ):
            raise MathExecutionBindingError("job_id does not match the packet")
        generation = job.get("generation")
        if isinstance(generation, bool) or not isinstance(generation, int):
            raise MathExecutionBindingError("job generation is malformed")
        if generation != packet.generation:
            raise MathExecutionBindingError(
                "job generation does not match the packet snapshot"
            )
        for key in ("snapshot_id", "nmp_snapshot_id", "math_snapshot_id"):
            value = payload.get(key)
            if value is not None and str(value) != packet.snapshot_id:
                raise MathExecutionBindingError(
                    "job payload belongs to another snapshot"
                )
        job_ruleset = payload.get("ruleset_snapshot_id")
        if (
            job_ruleset is not None
            and packet.ruleset_snapshot_id
            and str(job_ruleset) != packet.ruleset_snapshot_id
        ):
            raise MathExecutionBindingError(
                "job payload belongs to another ruleset snapshot"
            )
        job_preflight = payload.get("preflight_digest")
        if job_preflight is not None and packet.preflight_digest is not None:
            try:
                normalized = nmp.normalize_digest(
                    job_preflight, "preflight_digest"
                )
            except nmp.NmpValidationError as exc:
                raise MathExecutionBindingError(
                    "job preflight digest is malformed"
                ) from exc
            if normalized != packet.preflight_digest:
                raise MathExecutionBindingError(
                    "job preflight digest does not match the packet"
                )
        job_ring = payload.get("ring_incarnation")
        if (
            job_ring is not None
            and packet.ring_incarnation
            and str(job_ring) != packet.ring_incarnation
        ):
            raise MathExecutionBindingError(
                "job ring incarnation does not match the packet"
            )
        job_epoch = payload.get("ring_epoch")
        if (
            job_epoch is not None
            and packet.ring_epoch is not None
            and job_epoch != packet.ring_epoch
        ):
            raise MathExecutionBindingError(
                "job ring epoch does not match the packet"
            )
        job_cancel = payload.get("cancel_epoch")
        if (
            isinstance(job_cancel, int)
            and not isinstance(job_cancel, bool)
            and job_cancel > packet.cancel_epoch
        ):
            raise MathExecutionStateError(
                "a newer cancellation epoch is recorded on the job"
            )
        return payload

    # -- lease --------------------------------------------------------------

    def _lease_owner(self, job: Mapping[str, Any]) -> str:
        owner = job.get("lease_owner")
        if not isinstance(owner, str) or not owner:
            raise MathExecutionLeaseError(
                "job has no lease owner"
            )
        return owner

    def _workspace_for(self, packet: nmp.NmpPacket, job: Mapping[str, Any]) -> int:
        payload = _job_payload(job)
        values = [
            packet.guest_words,
            payload.get("workspace_words"),
            job.get("workspace"),
        ]
        result = 0
        for value in values:
            if isinstance(value, int) and not isinstance(value, bool):
                result = max(result, value)
        return result

    def lease(
        self,
        target: Any,
        *,
        owner: str | None = None,
        now_tick: int,
        lease_ticks: int | None = None,
        worker_token: str | None = None,
        compiled: CompiledMathPlan | None = None,
        admission: Any = None,
        capability: Any = None,
        ruleset_snapshot: Any = None,
        cancel_epoch: int | None = None,
        workspace: int | None = None,
        allow_declared: bool = False,
        max_attempts: int = 8,
    ) -> MathExecutionLease | None:
        """Lease the packet's job only on the active runner slot.

        Ring memory is reserved and one ring lease is registered before the
        WaveStore job lease is attempted.  Any failed attempt rolls both back.
        """
        packet = _packet_from(target)
        if self.system is None or self.store is None:
            raise MathExecutionConfigError("lease requires an MthSystem and WaveStore")
        _require_int("now_tick", now_tick)
        _require_int("max_attempts", max_attempts, minimum=1)
        lease_ticks = (
            self.lease_ticks if lease_ticks is None else _require_int(
                "lease_ticks", lease_ticks, minimum=1
            )
        )
        job = self._job_for(packet, _job_from(target))
        job_id = str(job.get("job_id"))
        payload = self._validate_job_binding(packet, job)
        self._validate_current_rules(packet)
        binding = self.ring_binding(now_tick=now_tick, require_active=True)

        # Idempotent re-entry: the authoritative job already holds a lease.
        if str(job.get("state")) == "leased":
            lease_row = lease_row_from_job(job)
            assert lease_row is not None
            active_owner = str(job.get("lease_owner") or "")
            if owner is not None and resolve_slot(owner) != binding.active_slot:
                raise MathExecutionRingError(
                    f"lease owner {owner!r} is not the active runner slot"
                )
            if packet.state == nmp.QUEUED:
                decision = self.check(
                    packet,
                    compiled,
                    admission=admission,
                    capability=capability,
                    ruleset_snapshot=ruleset_snapshot,
                    cancel_epoch=cancel_epoch,
                    workspace=workspace,
                    allow_declared=allow_declared,
                    job=job,
                    lease=lease_row,
                    now_tick=now_tick,
                    ring=binding,
                )
                if not decision.ok:
                    raise MathExecutionGateError(decision)
                packet = packet.start_execution(
                    gate=decision,
                    tick=now_tick,
                    job_id=job_id,
                    lease_epoch=int(job.get("lease_epoch") or 0),
                    ring_incarnation=binding.incarnation,
                    ring_epoch=binding.epoch,
                )
                self._remember_packet(packet)
            elif packet.state != nmp.EXECUTING:
                raise MathExecutionStateError(
                    f"leased job cannot bind packet state {packet.state}"
                )
            workspace_words = self._workspace_for(packet, job)
            return MathExecutionLease(
                packet=packet,
                job=job,
                job_id=job_id,
                lease_token=str(job.get("lease_token")),
                lease_epoch=int(job.get("lease_epoch") or 0),
                owner=active_owner,
                deadline_tick=job.get("deadline_tick"),
                ring=binding,
                workspace_words=workspace_words,
                memory_bytes=workspace_words * self.workspace_word_bytes,
                ring_registered=(job_id, int(job.get("lease_epoch") or 0))
                in self._ring_resources,
                duplicate=True,
            )

        if str(job.get("state")) != "queued":
            raise MathExecutionStateError(
                f"job {job_id} is {job.get('state')}, not queued"
            )
        if packet.state != nmp.QUEUED:
            raise MathExecutionStateError(
                f"lease requires QUEUED, packet is {packet.state}"
            )
        owner = self._assert_owner(owner, binding)
        decision = self.check(
            packet,
            compiled,
            admission=admission,
            capability=capability,
            ruleset_snapshot=ruleset_snapshot,
            cancel_epoch=cancel_epoch,
            workspace=workspace,
            allow_declared=allow_declared,
            job=job,
            now_tick=now_tick,
            ring=binding,
        )
        if not decision.ok:
            raise MathExecutionGateError(decision)

        workspace_words = self._workspace_for(packet, job)
        memory_bytes = workspace_words * self.workspace_word_bytes
        token = worker_token if worker_token is not None else self.worker_token
        if token is None:
            raise MathExecutionConfigError("lease requires a worker token")
        reserved = False
        registered = False
        try:
            if memory_bytes:
                self.scheduler.reserve_memory(memory_bytes)
                reserved = True
            self.scheduler.register_lease(1)
            registered = True
            leased_job = self.system.lease(
                token,
                owner,
                now_tick,
                lease_ticks,
                expected_generation=packet.generation,
                max_attempts=max_attempts,
                job_id=job_id,
            )
        except Exception:
            if registered:
                try:
                    self.scheduler.release_lease(1)
                except WaveRingSchedulerError:
                    pass
            if reserved:
                try:
                    self.scheduler.release_memory(memory_bytes)
                except WaveRingSchedulerError:
                    pass
            raise
        if leased_job is None:
            if registered:
                try:
                    self.scheduler.release_lease(1)
                except WaveRingSchedulerError:
                    pass
            if reserved:
                try:
                    self.scheduler.release_memory(memory_bytes)
                except WaveRingSchedulerError:
                    pass
            return None
        if str(leased_job.get("job_id")) != job_id:
            # Pinned job_id makes this defensive only.
            self._fail_leased_job(
                leased_job, now_tick, "lease returned another job", token
            )
            self._rollback_ring(memory_bytes, registered, reserved)
            raise MathExecutionBindingError("lease returned another job")

        lease_row = lease_row_from_job(leased_job)
        if lease_row is None:
            self._rollback_ring(memory_bytes, registered, reserved)
            raise MathExecutionBindingError("leased job has no active lease row")
        decision = self.check(
            packet,
            compiled,
            admission=admission,
            capability=capability,
            ruleset_snapshot=ruleset_snapshot,
            cancel_epoch=cancel_epoch,
            workspace=workspace,
            allow_declared=allow_declared,
            job=leased_job,
            lease=lease_row,
            now_tick=now_tick,
            ring=binding,
        )
        if not decision.ok:
            self._fail_leased_job(
                leased_job, now_tick, "lease recheck refused", token
            )
            self._rollback_ring(memory_bytes, registered, reserved)
            raise MathExecutionGateError(decision)
        try:
            packet = packet.start_execution(
                gate=decision,
                tick=now_tick,
                job_id=job_id,
                lease_epoch=int(leased_job.get("lease_epoch") or 0),
                ring_incarnation=binding.incarnation,
                ring_epoch=binding.epoch,
            )
        except Exception:
            self._fail_leased_job(
                leased_job, now_tick, "packet lease transition failed", token
            )
            self._rollback_ring(memory_bytes, registered, reserved)
            raise
        self._ring_resources[(job_id, int(leased_job.get("lease_epoch") or 0))] = (
            owner,
            memory_bytes,
        )
        self._remember_packet(packet)
        return MathExecutionLease(
            packet=packet,
            job=leased_job,
            job_id=job_id,
            lease_token=str(leased_job.get("lease_token")),
            lease_epoch=int(leased_job.get("lease_epoch") or 0),
            owner=owner,
            deadline_tick=leased_job.get("deadline_tick"),
            ring=binding,
            workspace_words=workspace_words,
            memory_bytes=memory_bytes,
            ring_registered=True,
            duplicate=False,
            plan=compiled.plan if compiled is not None else None,
        )

    def _rollback_ring(
        self, memory_bytes: int, registered: bool, reserved: bool
    ) -> None:
        if registered:
            try:
                self.scheduler.release_lease(1)
            except WaveRingSchedulerError:
                pass
        if reserved and memory_bytes:
            try:
                self.scheduler.release_memory(memory_bytes)
            except WaveRingSchedulerError:
                pass

    def _fail_leased_job(
        self,
        job: Mapping[str, Any],
        now_tick: int,
        error: str,
        worker_token: str,
    ) -> None:
        token = job.get("lease_token")
        epoch = job.get("lease_epoch")
        if not token or not isinstance(epoch, int):
            return
        try:
            self._service_fail(
                worker_token,
                str(job.get("job_id")),
                str(token),
                epoch,
                now_tick,
                error,
                job.get("lease_owner"),
            )
        except Exception:
            # The original gate/transition failure is more useful than a
            # best-effort rollback failure.
            pass

    def _service_fail(
        self,
        worker_token: str,
        job_id: str,
        lease_token: str,
        lease_epoch: int,
        now_tick: int,
        error: str,
        lease_owner: str | None = None,
    ) -> Mapping[str, Any]:
        if self.system is None:
            raise MathExecutionConfigError("no MthSystem is configured")
        fail = getattr(self.system, "fail", None)
        if callable(fail):
            return fail(
                worker_token,
                job_id,
                lease_token,
                lease_epoch,
                now_tick,
                error,
                lease_owner=lease_owner,
            )
        return self.system.service.fail_job(
            worker_token,
            job_id,
            lease_token,
            lease_epoch,
            now_tick,
            error,
            lease_owner=lease_owner,
        )

    # -- complete / execute -------------------------------------------------

    @staticmethod
    def _executor_value(executor: Any, lease: MathExecutionLease) -> Any:
        if not callable(executor):
            return executor
        try:
            signature = inspect.signature(executor)
        except (TypeError, ValueError):
            return executor(lease)
        positional = [
            parameter
            for parameter in signature.parameters.values()
            if parameter.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]
        required = [
            parameter
            for parameter in positional
            if parameter.default is inspect.Parameter.empty
        ]
        if not positional:
            return executor()
        if len(required) <= 1:
            return executor(lease)
        return executor(lease.packet, lease)

    @staticmethod
    def _normalize_executor_result(value: Any) -> tuple[str, str, str | None]:
        if isinstance(value, str):
            return value, "OK", None
        if isinstance(value, Mapping):
            digest = (
                value.get("result_digest")
                or value.get("digest")
                or value.get("output_digest")
            )
            status = value.get("result_status") or value.get("status") or "OK"
            output = (
                value.get("output_leaf_id")
                or value.get("leaf_id")
                or value.get("output")
            )
            if not isinstance(digest, str):
                raise MathExecutionBindingError(
                    "executor result must carry a result digest"
                )
            return digest, str(status), output if isinstance(output, str) else None
        digest = getattr(value, "result_digest", None) or getattr(
            value, "digest", None
        )
        if isinstance(digest, str):
            status = getattr(value, "result_status", None) or getattr(
                value, "status", None
            ) or "OK"
            output = getattr(value, "output_leaf_id", None) or getattr(
                value, "leaf_id", None
            )
            return digest, str(status), output if isinstance(output, str) else None
        raise MathExecutionBindingError(
            "executor must return a digest string or a result object"
        )

    def _validate_current_rules(self, packet: nmp.NmpPacket) -> None:
        if getattr(self.runtime, "rule_provider", None) is None:
            return
        current = self.runtime.current_rule_snapshot_id()
        if packet.ruleset_snapshot_id != current:
            raise MathExecutionStateError(
                "ruleset snapshot changed before execution"
            )

    def _validate_dispatch(
        self,
        lease: MathExecutionLease,
        *,
        now_tick: int,
        worker_token: str | None,
    ) -> Mapping[str, Any]:
        """Fail before the executor if the lease cannot dispatch right now."""
        if not isinstance(lease, MathExecutionLease):
            raise MathExecutionBindingError("execute requires a MathExecutionLease")
        _require_int("now_tick", now_tick)
        packet = lease.packet
        self._validate_current_rules(packet)
        # Always re-read the durable job row.  A lease is a historical record;
        # trusting its embedded job snapshot would allow replay after commit.
        job = self._job_for(packet)
        self._validate_job_binding(packet, job)
        if packet.state != nmp.EXECUTING:
            raise MathExecutionStateError(
                f"execute requires EXECUTING, packet is {packet.state}"
            )
        if packet.cancel_requested:
            raise MathExecutionStateError("packet has a pending cancellation request")
        if lease.deadline_tick is not None and now_tick >= lease.deadline_tick:
            raise MathExecutionStateError("lease deadline has expired before dispatch")
        if lease.lease_token != str(job.get("lease_token")):
            raise MathExecutionBindingError("lease token does not match the job")
        if lease.lease_epoch != int(job.get("lease_epoch") or 0):
            raise MathExecutionBindingError("lease epoch does not match the job")
        if str(job.get("state")) != "leased":
            raise MathExecutionStateError(
                f"execute requires a leased job, job is {job.get('state')!r}"
            )
        token = worker_token if worker_token is not None else self.worker_token
        if token is None:
            raise MathExecutionConfigError("execute requires a worker token")
        service = getattr(self.system, "service", None)
        authorize = getattr(service, "_authorize", None)
        if callable(authorize):
            authorize(token, ("worker",))
        return job

    def execute(
        self,
        lease: MathExecutionLease,
        executor: Any,
        *,
        now_tick: int,
        result_status: str | None = None,
        output_leaf_id: str | None = None,
        evidence: Mapping[str, Any] | None = None,
        commit: bool = False,
        provenance: Mapping[str, Any] | None = None,
        result_generation: int | None = None,
        allow_newer: bool = False,
        worker_token: str | None = None,
        plan_step: int | None = None,
    ) -> MathExecutionResult:
        """Run a caller-supplied executor callback, then complete the job.

        The callback is the only execution path.  It may be a zero-argument
        callable, a callable accepting the lease, or a callable accepting
        ``(packet, lease)``.  It must return a digest string or an object with
        ``result_digest``/``digest``.  The bridge does not inspect or compute
        numerical content.
        """
        self._validate_dispatch(
            lease, now_tick=now_tick, worker_token=worker_token,
        )
        value = self._executor_value(executor, lease)
        digest, status, output = self._normalize_executor_result(value)
        return self.complete(
            lease,
            digest,
            now_tick=now_tick,
            result_status=result_status or status,
            output_leaf_id=output_leaf_id or output,
            evidence=evidence,
            commit=commit,
            provenance=provenance,
            result_generation=result_generation,
            allow_newer=allow_newer,
            worker_token=worker_token,
            plan_step=plan_step,
        )

    def complete(
        self,
        lease: MathExecutionLease | nmp.NmpPacket,
        result_digest: str,
        *,
        now_tick: int,
        result_status: str = "OK",
        output_leaf_id: str | None = None,
        evidence: Mapping[str, Any] | None = None,
        commit: bool = False,
        provenance: Mapping[str, Any] | None = None,
        result_generation: int | None = None,
        allow_newer: bool = False,
        worker_token: str | None = None,
        plan_step: int | None = None,
    ) -> MathExecutionResult:
        """Complete a leased job with a caller-supplied result digest."""
        _require_int("now_tick", now_tick)
        packet = _packet_from(lease)
        job = _job_from(lease)
        if job is None:
            job = self._job_for(packet)
        job_id = str(job.get("job_id"))
        self._validate_job_binding(packet, job)
        try:
            digest = nmp.normalize_digest(result_digest, "result_digest")
        except nmp.NmpValidationError as exc:
            raise MathExecutionBindingError("result_digest is malformed") from exc
        if not isinstance(result_status, str) or not result_status:
            raise MathExecutionBindingError("result_status must be non-empty")
        if result_generation is None:
            result_generation = packet.generation
        if isinstance(result_generation, bool) or not isinstance(
            result_generation, int
        ):
            raise MathExecutionBindingError("result_generation must be an integer")
        if not allow_newer and result_generation != packet.generation:
            raise MathExecutionBindingError(
                "result generation must equal the packet generation"
            )
        token = worker_token if worker_token is not None else self.worker_token
        if token is None:
            raise MathExecutionConfigError("complete requires a worker token")

        if isinstance(lease, MathExecutionLease):
            lease_token = lease.lease_token
            lease_epoch = lease.lease_epoch
            owner = lease.owner
        else:
            lease_token = str(job.get("lease_token") or "")
            lease_epoch = int(job.get("lease_epoch") or 0)
            owner = job.get("lease_owner")
            if not lease_token or lease_epoch < 1:
                raise MathExecutionBindingError("job has no active lease")
        if packet.state not in (nmp.EXECUTING, nmp.COMPLETED, nmp.COMMITTED):
            raise MathExecutionStateError(
                f"complete requires EXECUTING, packet is {packet.state}"
            )
        if packet.state == nmp.EXECUTING:
            if lease_token != str(job.get("lease_token")):
                raise MathExecutionBindingError("lease token does not match the job")
            if lease_epoch != int(job.get("lease_epoch") or 0):
                raise MathExecutionBindingError("lease epoch does not match the job")
        elif str(job.get("state")) != "done":
            raise MathExecutionBindingError(
                "completed packet is not backed by a completed job"
            )
        if (
            packet.result_digest is not None
            and packet.result_digest != digest
        ):
            raise MathExecutionBindingError(
                "completion cannot replace the packet result digest"
            )

        duplicate = str(job.get("state")) == "done"
        if duplicate:
            done = job
            if str(done.get("result_digest")) != digest:
                raise MathExecutionBindingError(
                    "completed job carries another result digest"
                )
        else:
            done = self.system.complete(
                token,
                job_id,
                lease_token,
                lease_epoch,
                digest,
                now_tick,
                result_generation=result_generation,
                lease_owner=owner,
            )
        released = self._release_ring(job_id, lease_epoch)
        try:
            if packet.state == nmp.EXECUTING:
                packet = packet.complete(
                    digest,
                    result_status=result_status,
                    output_leaf_id=output_leaf_id,
                    evidence={
                        **dict(evidence or {}),
                        "result_generation": result_generation,
                        "lease_token_digest": _token_digest(lease_token),
                        "plan_step": plan_step,
                    },
                    tick=now_tick,
                    job_id=job_id,
                    lease_epoch=lease_epoch,
                )
            committed = packet.state == nmp.COMMITTED
            if commit and packet.state == nmp.COMPLETED:
                commit_provenance = {
                    "job_id": job_id,
                    "lease_token_digest": _token_digest(lease_token),
                    "lease_epoch": lease_epoch,
                    "admission_id": packet.admission_id,
                    "snapshot_id": packet.snapshot_id,
                    "preflight_digest": packet.preflight_digest,
                    **dict(provenance or {}),
                }
                packet = packet.commit(
                    output_leaf_id=output_leaf_id,
                    provenance=commit_provenance,
                    evidence=evidence,
                    tick=now_tick,
                )
                committed = True
        finally:
            self._remember_packet(packet)
        projection = self.project(packet, job=done, now_tick=now_tick)
        return MathExecutionResult(
            packet=packet,
            job=done,
            job_id=job_id,
            lease_token=lease_token,
            lease_epoch=lease_epoch,
            outcome=nmp.COMMITTED if packet.state == nmp.COMMITTED else nmp.COMPLETED,
            result_digest=digest,
            result_status=result_status,
            output_leaf_id=output_leaf_id,
            committed=packet.state == nmp.COMMITTED,
            ring_released=released,
            duplicate=duplicate,
            projection=projection,
        )

    run = execute

    # -- fail ---------------------------------------------------------------

    def fail(
        self,
        target: Any,
        reason: str = "execution failed",
        *,
        now_tick: int,
        failure_class: str = "EXECUTION_FAILED",
        worker_token: str | None = None,
        evidence: Mapping[str, Any] | None = None,
        cancelled: bool = False,
    ) -> MathExecutionResult:
        """Fail the WaveStore job, transition the packet, and release ring state."""
        if not isinstance(reason, str) or not reason:
            raise MathExecutionBindingError("reason must be non-empty")
        _require_int("now_tick", now_tick)
        packet = _packet_from(target)
        job = _job_from(target)
        if job is None:
            job = self._job_for(packet)
        job_id = str(job.get("job_id"))
        payload = self._validate_job_binding(packet, job)
        token = worker_token if worker_token is not None else self.worker_token
        if token is None:
            raise MathExecutionConfigError("fail requires a worker token")
        job_state = str(job.get("state"))
        if job_state == "done":
            raise MathExecutionStateError("job already completed; failure is too late")
        if job_state == "queued":
            claimed = self._claim_queued_job(packet, job, now_tick, token)
            if claimed is None:
                raise MathExecutionStateError("queued job could not be claimed")
            job = claimed
            job_state = "leased"
        if job_state == "leased":
            self._service_fail(
                token,
                job_id,
                str(job.get("lease_token")),
                int(job.get("lease_epoch") or 0),
                now_tick,
                reason,
                job.get("lease_owner"),
            )
        elif job_state not in {"failed", "dead"}:
            raise MathExecutionStateError(
                f"job {job_id} cannot fail from state {job_state}"
            )
        failed = self.store.get_job(job_id) or job
        lease_epoch = int(job.get("lease_epoch") or 0)
        released = self._release_ring(job_id, lease_epoch)
        if packet.state in (nmp.QUEUED, nmp.EXECUTING):
            packet = packet.fail(
                reason,
                failure_class=failure_class,
                tick=now_tick,
                job_id=job_id,
                lease_epoch=lease_epoch or None,
                evidence={
                    **dict(evidence or {}),
                    "job_id": job_id,
                    "failure_class": failure_class,
                    "cancelled": bool(cancelled),
                },
            )
        elif packet.state in (nmp.FAILED, nmp.CANCELLED):
            pass
        else:
            raise MathExecutionStateError(
                f"packet {packet.packet_id} cannot fail from {packet.state}"
            )
        self._remember_packet(packet)
        projection = self.project(packet, job=failed, now_tick=now_tick)
        return MathExecutionResult(
            packet=packet,
            job=failed,
            job_id=job_id,
            lease_token=job.get("lease_token"),
            lease_epoch=lease_epoch or None,
            outcome=nmp.CANCELLED if cancelled else nmp.FAILED,
            result_status=failure_class,
            ring_released=released,
            projection=projection,
        )

    def _claim_queued_job(
        self,
        packet: nmp.NmpPacket,
        job: Mapping[str, Any],
        now_tick: int,
        worker_token: str,
    ) -> Mapping[str, Any] | None:
        """Lease a queued job only for an immediate terminal transition."""
        binding = self.ring_binding(now_tick=now_tick, require_active=True)
        owner = self._assert_owner(None, binding)
        return self.system.lease(
            worker_token,
            owner,
            now_tick,
            self.lease_ticks,
            expected_generation=packet.generation,
            job_id=str(job.get("job_id")),
        )

    # -- cancel -------------------------------------------------------------

    def cancel(
        self,
        target: Any,
        *,
        now_tick: int,
        reason: str = "cancelled",
        epoch: int | None = None,
        plan_step: int | None = None,
        worker_token: str | None = None,
    ) -> MathExecutionCancellation:
        """Cancel before lease, or acknowledge at a cooperative plan boundary."""
        if not isinstance(reason, str) or not reason:
            raise MathExecutionBindingError("reason must be non-empty")
        _require_int("now_tick", now_tick)
        packet = _packet_from(target)
        job = _job_from(target)
        if job is None:
            job = self._find_job_for_packet(packet)
        job_id = str(job.get("job_id")) if job is not None else packet.job_id
        lease_row = lease_row_from_job(job) if job is not None else None

        if job is None:
            cancellation = packet.request_cancel(
                epoch=epoch,
                reason=reason,
                tick=now_tick,
                plan_step=plan_step,
            )
            return MathExecutionCancellation(
                packet=cancellation.packet,
                job=None,
                job_id=job_id,
                status=cancellation.status,
                reason=cancellation.reason,
                cancel_epoch=cancellation.cancel_epoch,
                action=cancellation.action,
            )

        payload = self._validate_job_binding(packet, job)
        job_state = str(job.get("state"))
        token = worker_token if worker_token is not None else self.worker_token
        if token is None:
            raise MathExecutionConfigError("cancel requires a worker token")

        if job_state == "done":
            cancellation = packet.request_cancel(
                epoch=epoch,
                reason=reason,
                tick=now_tick,
                job=job,
                lease=lease_row,
                plan_step=plan_step,
            )
            return MathExecutionCancellation(
                packet=cancellation.packet,
                job=job,
                job_id=job_id,
                status="too_late",
                reason="job result already exists; cancellation cannot replace it",
                cancel_epoch=cancellation.cancel_epoch,
                action="result_stands",
                projection=self.project(
                    cancellation.packet, job=job, now_tick=now_tick
                ),
            )
        if job_state in {"failed", "dead"}:
            cancellation = packet.request_cancel(
                epoch=epoch,
                reason=reason,
                tick=now_tick,
                job=job,
                lease=lease_row,
                plan_step=plan_step,
            )
            return MathExecutionCancellation(
                packet=cancellation.packet,
                job=job,
                job_id=job_id,
                status="terminal",
                reason=f"job is already {job_state}",
                cancel_epoch=cancellation.cancel_epoch,
                action="none",
            )

        released = False
        if job_state == "queued":
            cancellation = packet.request_cancel(
                epoch=epoch,
                reason=reason,
                tick=now_tick,
                job=job,
                lease=None,
                plan_step=plan_step,
            )
            cancelled_packet = cancellation.packet
            claimed = self._claim_queued_job(cancelled_packet, job, now_tick, token)
            if claimed is not None:
                self._service_fail(
                    token,
                    job_id,
                    str(claimed.get("lease_token")),
                    int(claimed.get("lease_epoch") or 0),
                    now_tick,
                    "cancelled: " + reason,
                    claimed.get("lease_owner"),
                )
                job = self.store.get_job(job_id) or claimed
                job_state = str(job.get("state"))
            packet = cancelled_packet
        else:
            requested = packet.request_cancel(
                epoch=epoch,
                reason=reason,
                tick=now_tick,
                job=job,
                lease=lease_row,
                plan_step=plan_step,
            )
            packet = requested.packet
            if requested.too_late:
                return MathExecutionCancellation(
                    packet=packet,
                    job=job,
                    job_id=job_id,
                    status="too_late",
                    reason=requested.reason,
                    cancel_epoch=requested.cancel_epoch,
                    action=requested.action,
                )
            acknowledged = packet.acknowledge_cancel(
                tick=now_tick,
                plan_step=plan_step,
                job=job,
                lease=lease_row,
            )
            packet = acknowledged.packet
            cancellation = acknowledged
            if packet.state == nmp.CANCELLED and job_state == "leased":
                self._service_fail(
                    token,
                    job_id,
                    str(job.get("lease_token")),
                    int(job.get("lease_epoch") or 0),
                    now_tick,
                    "cancelled: " + reason,
                    job.get("lease_owner"),
                )
                job = self.store.get_job(job_id) or job
            elif packet.state != nmp.CANCELLED:
                return MathExecutionCancellation(
                    packet=packet,
                    job=job,
                    job_id=job_id,
                    status=cancellation.status,
                    reason=cancellation.reason,
                    cancel_epoch=cancellation.cancel_epoch,
                    action=cancellation.action,
                )
        lease_epoch = int(job.get("lease_epoch") or 0) if job else 0
        if lease_epoch:
            released = self._release_ring(job_id, lease_epoch)
        self._remember_packet(packet)
        projection = self.project(packet, job=job, now_tick=now_tick)
        return MathExecutionCancellation(
            packet=packet,
            job=job,
            job_id=job_id,
            status="cancelled" if packet.state == nmp.CANCELLED else "requested",
            reason=reason,
            cancel_epoch=packet.cancel_epoch,
            action="cancel_queued_job" if job_state != "leased" else "cooperative_plan_step",
            ring_released=released,
            projection=projection,
        )

    # -- ring release -------------------------------------------------------

    def _release_ring(self, job_id: str, lease_epoch: int) -> bool:
        entry = self._ring_resources.pop((job_id, int(lease_epoch)), None)
        if entry is None or self.scheduler is None:
            return False
        owner, memory_bytes = entry
        snapshot = self.scheduler.snapshot()
        active = snapshot.get("active_slot_id")
        alias = snapshot.get("active_alias")
        if owner not in {active, alias}:
            # A handoff cannot legally happen with a live lease; do not touch a
            # different slot's accounting.
            return False
        released = False
        if snapshot.get("active_lease_count", 0) > 0:
            try:
                self.scheduler.release_lease(1)
                released = True
            except WaveRingSchedulerError:
                pass
        if memory_bytes and snapshot.get("active_memory_reserved_bytes", 0) >= memory_bytes:
            try:
                self.scheduler.release_memory(memory_bytes)
                released = True
            except WaveRingSchedulerError:
                pass
        return released

    # -- projection / restart ----------------------------------------------

    def project(
        self,
        packet: nmp.NmpPacket,
        *,
        job: Any = None,
        lease: Any = None,
        now_tick: int | None = None,
        allow_newer: bool = False,
    ) -> nmp.NmpProjection:
        """Project authoritative packet state from WaveStore job/lease rows."""
        if not isinstance(packet, nmp.NmpPacket):
            raise MathExecutionBindingError("a prepared NmpPacket is required")
        resolved_job = job
        if resolved_job is None:
            resolved_job = self._find_job_for_packet(packet)
        resolved_lease = lease
        if resolved_lease is None and resolved_job is not None:
            resolved_lease = lease_row_from_job(resolved_job)
        return nmp.project_packet(
            packet,
            job=resolved_job,
            lease=resolved_lease,
            store=self.store,
            now_tick=now_tick,
            allow_newer=allow_newer,
        )

    def restart(
        self,
        packet: nmp.NmpPacket,
        *,
        job: Any = None,
        lease: Any = None,
        now_tick: int | None = None,
        allow_newer: bool = False,
        tick: int = 0,
    ) -> nmp.NmpPacket:
        """Rebuild a packet from WaveStore rows after a process restart."""
        return self.project(
            packet,
            job=job,
            lease=lease,
            now_tick=now_tick,
            allow_newer=allow_newer,
        ).to_packet(packet, tick=tick)

    reconstruct = restart
    restore_packet = restart

    def project_execution(
        self,
        packet: nmp.NmpPacket,
        *,
        now_tick: int | None = None,
        allow_newer: bool = False,
    ) -> dict[str, Any]:
        """Return a plain restart report without claiming a durable bridge row."""
        job = self._find_job_for_packet(packet)
        lease = lease_row_from_job(job) if job is not None else None
        projection = self.project(
            packet,
            job=job,
            lease=lease,
            now_tick=now_tick,
            allow_newer=allow_newer,
        )
        return {
            "schema": "nanrouter.math-execution-projection.v1",
            "packet_id": packet.packet_id,
            "job": None if job is None else dict(job),
            "lease": None if lease is None else dict(lease),
            "projection": projection.to_dict(),
        }

    # Friendly aliases.
    project_state = project
    reconstruct_packet = restart
    status = project_execution

    # -- in-memory dedupe ---------------------------------------------------

    def lookup_duplicate(self, packet_or_key: nmp.NmpPacket | str) -> Any:
        """Look up the explicitly in-memory duplicate index."""
        return self._dedupe.lookup(packet_or_key)

    @property
    def in_flight(self) -> nmp.NmpInFlightTable:
        return self._dedupe


__all__ = [
    "BATCH_SCHEMA",
    "BRIDGE_SCHEMA",
    "CANCELLATION_SCHEMA",
    "DEFAULT_LEASE_TICKS",
    "DEFAULT_WORKSPACE_WORD_BYTES",
    "ExecutionGateError",
    "LEASE_SCHEMA",
    "MathExecutionBatchSubmission",
    "MathExecutionBindingError",
    "MathExecutionBridge",
    "MathExecutionBridgeError",
    "MathExecutionCancellation",
    "MathExecutionConfigError",
    "MathExecutionError",
    "MathExecutionGateError",
    "MathExecutionLease",
    "MathExecutionPlanError",
    "MathExecutionResult",
    "MathExecutionRingError",
    "MathExecutionStateError",
    "MathExecutionSubmission",
    "MathRingBinding",
    "RESULT_SCHEMA",
    "SUBMISSION_SCHEMA",
    "lease_row_from_job",
    "ring_incarnation_for",
]
