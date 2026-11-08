"""Bounded logical-lane work queues and capability-safe stealing (P11 §11.4).

A lane is a durable work identity, not a runner.  Work stealing moves only
independent, not-yet-executing NMP packets between lane queues.  It never
steals a partially executing packet, never creates a second runner, and never
grants a capability the destination runner does not hold.

The module is host-control only.  It performs no mathematics, owns no durable
job/lease ledger, and imports no executor or runtime facade.  The optional
:class:`LaneWorkAdapter` projects already submitted packets and already
acquired leases into these queues.  It never submits, leases, completes, or
executes work unless the caller explicitly delegates one of those bridge
operations; the WaveStore/MthSystem job and lease rows remain authoritative.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Iterable, Mapping

from .lane_registry import LANE_COUNT, role_for_lane

SCHEMA = "nanrouter.lane-work.v1"
ITEM_SCHEMA = "nanrouter.lane-work-item.v1"
STATS_SCHEMA = "nanrouter.lane-work-stats.v1"

QUEUED = "queued"
LEASED = "leased"
EXECUTING = "executing"
COMPLETED = "completed"
REJECTED = "rejected"
TERMINAL = frozenset({COMPLETED, REJECTED})
STEALABLE = frozenset({QUEUED})
CRITICAL_ROLES = frozenset({"preflight", "control", "supervisor"})


class LaneWorkError(ValueError):
    """Base error for queue/steal contract failures."""


class QueueFull(LaneWorkError):
    """A bounded lane/role queue has no room for another item."""


class WorkConflict(LaneWorkError):
    """The same packet identity is already present with different content."""


class NotStealable(LaneWorkError):
    """The selected work item is executing, terminal, or otherwise ineligible."""


class CapabilityMismatch(LaneWorkError):
    """The destination runner cannot satisfy the item's capability need."""


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_lane(value: Any) -> int:
    if not _is_int(value) or not (0 <= value < LANE_COUNT):
        raise LaneWorkError(
            f"lane_id must be an integer in 0..{LANE_COUNT - 1}"
        )
    return value


def _text(value: Any, name: str, *, maximum: int = 512,
          allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value) or len(value) > maximum:
        raise LaneWorkError(
            f"{name} must be a {'possibly empty ' if allow_empty else ''}string <= {maximum}"
        )
    return value


def _digest(value: Any, name: str, *, allow_none: bool = True) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or len(value) != 64 or any(
        ch not in "0123456789abcdef" for ch in value
    ):
        raise LaneWorkError(f"{name} must be lowercase SHA-256 hex")
    return value


def _canonical(value: Any) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    )


def _digest_object(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


_UNSET = object()
_FINISH_STATES = {
    COMPLETED: COMPLETED,
    "complete": COMPLETED,
    "committed": COMPLETED,
    "done": COMPLETED,
    REJECTED: REJECTED,
    "reject": REJECTED,
    "failed": REJECTED,
    "failure": REJECTED,
    "cancelled": REJECTED,
    "canceled": REJECTED,
}


def _finish_state(value: Any) -> str:
    state = _FINISH_STATES.get(str(value).lower())
    if state is None:
        raise LaneWorkError(
            "finish state must be completed, rejected, failed, or cancelled"
        )
    return state


def _record_get(record: Any, name: str, default: Any = None) -> Any:
    """Read one field from a mapping or a typed packet/lease record."""
    if isinstance(record, Mapping):
        return record.get(name, default)
    return getattr(record, name, default)


def _first_value(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _name_set(value: Iterable[str] | str | None) -> frozenset[str]:
    if value is None:
        return frozenset()
    if isinstance(value, str):
        return frozenset({value})
    try:
        return frozenset(str(item) for item in value)
    except TypeError as exc:
        raise LaneWorkError("expected a string or iterable of strings") from exc


def _packet_from_record(record: Any) -> Any:
    if record is None:
        raise LaneWorkError("a packet or submission/lease record is required")
    packet = _record_get(record, "packet")
    if packet is not None and packet is not record:
        return packet
    return record


def _preflight_digest_from(record: Any) -> Any:
    value = _record_get(record, "preflight_digest")
    if value is not None:
        return value
    preflight = _record_get(record, "preflight")
    if isinstance(preflight, Mapping):
        return preflight.get("digest")
    return None


def _capability_epoch_from(record: Any) -> Any:
    value = _record_get(record, "capability_epoch")
    if value is not None:
        return value
    capability = _record_get(record, "capability")
    if isinstance(capability, Mapping):
        return capability.get("epoch")
    return None


def _capability_names(value: Any) -> tuple[str, ...]:
    """Flatten packet capability rows into stable capability names."""
    if value is None:
        return ()
    if isinstance(value, str):
        value = (value,)
    elif isinstance(value, Mapping):
        value = (value,)
    try:
        entries = iter(value)
    except TypeError as exc:
        raise LaneWorkError("capability requirement must be a sequence") from exc
    names: list[str] = []
    for entry in entries:
        candidates: list[Any] = []
        if isinstance(entry, str):
            candidates.append(entry)
        elif isinstance(entry, Mapping):
            for key in (
                "required",
                "capability",
                "capability_class",
                "class",
                "kernel_id",
                "function_id",
            ):
                candidates.append(entry.get(key))
            for key in ("requirements", "capabilities", "set"):
                if key in entry:
                    candidates.extend(_capability_names(entry[key]))
        else:
            raise LaneWorkError(
                "capability requirement entries must be strings or objects"
            )
        for candidate in candidates:
            if (
                isinstance(candidate, str)
                and candidate
                and candidate not in names
            ):
                names.append(candidate)
    return tuple(names)


def _lane_role(lane_id: int) -> str:
    try:
        return role_for_lane(lane_id)
    except Exception:
        # A caller may use a custom role with a valid lane.  The queue still
        # validates the lane itself; only the default role lookup is optional.
        return "execution"


def _is_critical_role(role: str) -> bool:
    return role in CRITICAL_ROLES


@dataclass(frozen=True)
class WorkItem:
    """One independent queued packet; never a partially executing packet."""

    packet_id: str
    lane_id: int
    snapshot_id: str
    preflight_digest: str | None = None
    capability_requirement: tuple[str, ...] = ()
    capability_epoch: int = 0
    fuel: int = 0
    priority: int = 0
    critical: bool = False
    role: str = "execution"
    state: str = QUEUED
    enqueued_tick: int = 0
    attempts: int = 0
    job_id: str | None = None
    lease_id: str | None = None
    lease_epoch: int | None = None
    lease_owner: str | None = None
    lease_token_digest: str | None = None
    deadline_tick: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "packet_id", _text(self.packet_id, "packet_id"))
        object.__setattr__(self, "lane_id", _validate_lane(self.lane_id))
        object.__setattr__(self, "snapshot_id", _text(self.snapshot_id, "snapshot_id"))
        object.__setattr__(
            self, "preflight_digest",
            _digest(self.preflight_digest, "preflight_digest"),
        )
        requirements = self.capability_requirement
        if isinstance(requirements, str):
            requirements = (requirements,)
        if not isinstance(requirements, (tuple, list)):
            raise LaneWorkError("capability_requirement must be a sequence")
        cleaned = tuple(
            _text(item, "capability_requirement", maximum=160)
            for item in requirements
        )
        if len(set(cleaned)) != len(cleaned):
            raise LaneWorkError("capability_requirement contains duplicates")
        object.__setattr__(self, "capability_requirement", cleaned)
        for name in ("capability_epoch", "fuel", "priority", "enqueued_tick", "attempts"):
            value = getattr(self, name)
            if not _is_int(value) or value < 0:
                raise LaneWorkError(f"{name} must be an integer >= 0")
        if not isinstance(self.critical, bool):
            raise LaneWorkError("critical must be a boolean")
        object.__setattr__(self, "role", _text(self.role, "role", maximum=64))
        state = str(self.state).lower()
        if state not in {QUEUED, LEASED, EXECUTING, COMPLETED, REJECTED}:
            raise LaneWorkError(f"unknown work state: {state!r}")
        object.__setattr__(self, "state", state)
        if self.job_id is not None:
            object.__setattr__(self, "job_id", _text(self.job_id, "job_id"))
        if self.lease_id is not None:
            object.__setattr__(self, "lease_id", _text(self.lease_id, "lease_id"))
        if self.lease_epoch is not None:
            if not _is_int(self.lease_epoch) or self.lease_epoch < 0:
                raise LaneWorkError("lease_epoch must be an integer >= 0")
        if self.lease_owner is not None:
            object.__setattr__(
                self, "lease_owner", _text(self.lease_owner, "lease_owner")
            )
        object.__setattr__(
            self,
            "lease_token_digest",
            _digest(self.lease_token_digest, "lease_token_digest"),
        )
        if self.deadline_tick is not None:
            if not _is_int(self.deadline_tick) or self.deadline_tick < 0:
                raise LaneWorkError("deadline_tick must be an integer >= 0")

    @property
    def stealable(self) -> bool:
        return self.state in STEALABLE

    def identity(self) -> str:
        return _digest_object({
            "packet_id": self.packet_id,
            "lane_id": self.lane_id,
            "snapshot_id": self.snapshot_id,
            "preflight_digest": self.preflight_digest,
            "capability_requirement": list(self.capability_requirement),
            "capability_epoch": self.capability_epoch,
            "fuel": self.fuel,
            "priority": self.priority,
            "critical": self.critical,
            "role": self.role,
            "job_id": self.job_id,
            "lease_id": self.lease_id,
            "lease_epoch": self.lease_epoch,
        })

    def with_lane(self, lane_id: int) -> "WorkItem":
        return WorkItem(
            packet_id=self.packet_id,
            lane_id=lane_id,
            snapshot_id=self.snapshot_id,
            preflight_digest=self.preflight_digest,
            capability_requirement=self.capability_requirement,
            capability_epoch=self.capability_epoch,
            fuel=self.fuel,
            priority=self.priority,
            critical=self.critical,
            role=self.role,
            state=self.state,
            enqueued_tick=self.enqueued_tick,
            attempts=self.attempts + 1,
            job_id=self.job_id,
            lease_id=self.lease_id,
            lease_epoch=self.lease_epoch,
            lease_owner=self.lease_owner,
            lease_token_digest=self.lease_token_digest,
            deadline_tick=self.deadline_tick,
        )

    def transition(
        self,
        state: str,
        *,
        job_id: str | None = None,
        lease_id: str | None = None,
        lease_epoch: int | None = None,
        lease_owner: str | None = None,
        lease_token_digest: str | None = None,
        deadline_tick: int | None = None,
    ) -> "WorkItem":
        state = str(state).lower()
        if state not in {QUEUED, LEASED, EXECUTING, COMPLETED, REJECTED}:
            raise LaneWorkError(f"unknown work state: {state!r}")
        return WorkItem(
            packet_id=self.packet_id,
            lane_id=self.lane_id,
            snapshot_id=self.snapshot_id,
            preflight_digest=self.preflight_digest,
            capability_requirement=self.capability_requirement,
            capability_epoch=self.capability_epoch,
            fuel=self.fuel,
            priority=self.priority,
            critical=self.critical,
            role=self.role,
            state=state,
            enqueued_tick=self.enqueued_tick,
            attempts=self.attempts,
            job_id=job_id if job_id is not None else self.job_id,
            lease_id=lease_id if lease_id is not None else self.lease_id,
            lease_epoch=(
                lease_epoch if lease_epoch is not None else self.lease_epoch
            ),
            lease_owner=(
                lease_owner if lease_owner is not None else self.lease_owner
            ),
            lease_token_digest=(
                lease_token_digest
                if lease_token_digest is not None
                else self.lease_token_digest
            ),
            deadline_tick=(
                deadline_tick
                if deadline_tick is not None
                else self.deadline_tick
            ),
        )

    def with_lease(
        self,
        *,
        job_id: str | None = None,
        lease_id: str | None = None,
        lease_epoch: int | None = None,
        lease_owner: str | None = None,
        lease_token_digest: str | None = None,
        deadline_tick: int | None = None,
    ) -> "WorkItem":
        """Return the same work with lease identity metadata attached."""
        return self.transition(
            self.state,
            job_id=job_id,
            lease_id=lease_id,
            lease_epoch=lease_epoch,
            lease_owner=lease_owner,
            lease_token_digest=lease_token_digest,
            deadline_tick=deadline_tick,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": ITEM_SCHEMA,
            "packet_id": self.packet_id,
            "lane_id": self.lane_id,
            "snapshot_id": self.snapshot_id,
            "preflight_digest": self.preflight_digest,
            "capability_requirement": list(self.capability_requirement),
            "capability_epoch": self.capability_epoch,
            "fuel": self.fuel,
            "priority": self.priority,
            "critical": self.critical,
            "role": self.role,
            "state": self.state,
            "enqueued_tick": self.enqueued_tick,
            "attempts": self.attempts,
            "job_id": self.job_id,
            "lease_id": self.lease_id,
            "lease_epoch": self.lease_epoch,
            "lease_owner": self.lease_owner,
            "lease_token_digest": self.lease_token_digest,
            "deadline_tick": self.deadline_tick,
            "identity": self.identity(),
        }


@dataclass
class _LaneQueue:
    capacity: int
    critical_reserve: int = 1
    items: list[WorkItem] = field(default_factory=list)

    def _normal_items(self) -> int:
        return sum(1 for item in self.items if not item.critical)

    def has_room(self, item: WorkItem) -> bool:
        if item.critical:
            return len(self.items) < self.capacity
        return (
            len(self.items) < self.capacity
            and self._normal_items() + 1 <= self.capacity - self.critical_reserve
        )

    def push(self, item: WorkItem) -> None:
        if not self.has_room(item):
            raise QueueFull(
                f"lane {item.lane_id} queue is full "
                f"(capacity={self.capacity}, critical_reserve={self.critical_reserve})"
            )
        self.items.append(item)

    def pop(self) -> WorkItem | None:
        if not self.items:
            return None
        self.items.sort(
            key=lambda item: (
                0 if item.critical else 1,
                -item.priority,
                item.enqueued_tick,
                item.packet_id,
            )
        )
        return self.items.pop(0)


class LaneWorkQueues:
    """Deterministic bounded queues over the 255 logical lanes."""

    def __init__(
        self,
        *,
        capacity: int = 64,
        critical_reserve: int = 1,
        critical_roles: Iterable[str] = CRITICAL_ROLES,
    ) -> None:
        if not _is_int(capacity) or capacity < 1:
            raise LaneWorkError("capacity must be an integer >= 1")
        if not _is_int(critical_reserve) or not (0 <= critical_reserve < capacity):
            raise LaneWorkError(
                "critical_reserve must be an integer >= 0 and < capacity"
            )
        self.capacity = capacity
        self.critical_reserve = critical_reserve
        self.critical_roles = frozenset(critical_roles)
        self._queues = {
            lane: _LaneQueue(capacity, critical_reserve)
            for lane in range(LANE_COUNT)
        }
        self._by_packet: dict[str, WorkItem] = {}

    def enqueue(self, item: WorkItem) -> WorkItem:
        if not isinstance(item, WorkItem):
            raise LaneWorkError("enqueue requires a WorkItem")
        if item.state != QUEUED:
            raise LaneWorkError("only queued work may enter a lane queue")
        if item.role in self.critical_roles and not item.critical:
            raise LaneWorkError("critical-role work must be marked critical")
        existing = self._by_packet.get(item.packet_id)
        if existing is not None:
            if existing.identity() != item.identity():
                raise WorkConflict(
                    "packet identity is already queued with different content"
                )
            return existing
        queue = self._queues[item.lane_id]
        queue.push(item)
        self._by_packet[item.packet_id] = item
        return item

    def get(self, packet_id: str) -> WorkItem | None:
        return self._by_packet.get(packet_id)

    def dequeue(self, lane_id: int) -> WorkItem | None:
        lane_id = _validate_lane(lane_id)
        item = self._queues[lane_id].pop()
        if item is not None:
            self._by_packet.pop(item.packet_id, None)
        return item

    def _replace(self, old: WorkItem, new: WorkItem) -> None:
        self._by_packet[new.packet_id] = new
        if new.state in TERMINAL:
            self._remove_from_queues(new.packet_id)
        else:
            queue = self._queues[new.lane_id]
            for index, item in enumerate(queue.items):
                if item.packet_id == old.packet_id:
                    queue.items[index] = new
                    return
            queue.items.append(new)

    def _remove_from_queues(self, packet_id: str) -> None:
        for queue in self._queues.values():
            queue.items = [
                item for item in queue.items if item.packet_id != packet_id
            ]

    def bind_lease(
        self,
        packet_id: str,
        *,
        job_id: str | None = None,
        lease_id: str | None = None,
        lease_epoch: int | None = None,
        lease_owner: str | None = None,
        lease_token_digest: str | None = None,
        deadline_tick: int | None = None,
    ) -> WorkItem:
        """Attach already-authoritative lease identity to queued work.

        This only records the projection.  It never calls the bridge or
        MthSystem and never creates/acquires a lease.
        """
        item = self._by_packet.get(packet_id)
        if item is None:
            raise LaneWorkError("packet is not queued")
        if item.state in TERMINAL:
            raise NotStealable("terminal work cannot accept a new lease")
        updated = item.with_lease(
            job_id=job_id,
            lease_id=lease_id,
            lease_epoch=lease_epoch,
            lease_owner=lease_owner,
            lease_token_digest=lease_token_digest,
            deadline_tick=deadline_tick,
        )
        self._replace(item, updated)
        return updated

    attach_lease = bind_lease

    def begin(
        self,
        packet_id: str,
        *,
        job_id: str | None = None,
        lease_id: str | None = None,
        lease_epoch: int | None = None,
        lease_owner: str | None = None,
        lease_token_digest: str | None = None,
        deadline_tick: int | None = None,
    ) -> WorkItem:
        item = self._by_packet.get(packet_id)
        if item is None:
            raise LaneWorkError("packet is not queued")
        if item.state != QUEUED:
            raise NotStealable("packet is not in a queued state")
        updated = item.transition(
            LEASED,
            job_id=job_id,
            lease_id=lease_id,
            lease_epoch=lease_epoch,
            lease_owner=lease_owner,
            lease_token_digest=lease_token_digest,
            deadline_tick=deadline_tick,
        )
        self._replace(item, updated)
        return updated

    def executing(
        self,
        packet_id: str,
        *,
        job_id: str | None = None,
        lease_id: str | None = None,
        lease_epoch: int | None = None,
        lease_owner: str | None = None,
        lease_token_digest: str | None = None,
        deadline_tick: int | None = None,
    ) -> WorkItem:
        item = self._by_packet.get(packet_id)
        if item is None:
            raise LaneWorkError("packet is not queued")
        if item.state != LEASED:
            raise LaneWorkError("packet must be leased before executing")
        updated = item.transition(
            EXECUTING,
            job_id=job_id,
            lease_id=lease_id,
            lease_epoch=lease_epoch,
            lease_owner=lease_owner,
            lease_token_digest=lease_token_digest,
            deadline_tick=deadline_tick,
        )
        self._replace(item, updated)
        return updated

    def finish(
        self,
        packet_id: str,
        *,
        state: str = COMPLETED,
        job_id: str | None = None,
        lease_epoch: int | None = None,
    ) -> WorkItem:
        item = self._by_packet.get(packet_id)
        if item is None:
            raise LaneWorkError("packet is not queued")
        if item.state not in {LEASED, EXECUTING}:
            raise LaneWorkError("only leased/executing work can finish")
        updated = item.transition(
            _finish_state(state),
            job_id=job_id,
            lease_epoch=lease_epoch,
        )
        self._replace(item, updated)
        return updated

    def _check_steal_candidate(
        self,
        item: WorkItem,
        thief_lane: int,
        held: frozenset[str],
        capability_epoch: int,
        exclude: frozenset[str],
    ) -> None:
        if item.state not in STEALABLE:
            raise NotStealable("only queued work is stealable")
        if item.lane_id == thief_lane:
            raise NotStealable("packet is already assigned to the thief lane")
        if item.critical or item.role in self.critical_roles or item.role in exclude:
            raise NotStealable("critical work stays in its assigned lane")
        if item.capability_epoch > capability_epoch:
            raise CapabilityMismatch(
                "thief capability epoch is older than the work item"
            )
        missing = sorted(
            need for need in item.capability_requirement if need not in held
        )
        if missing:
            raise CapabilityMismatch(
                "thief lacks capability requirement(s): " + ", ".join(missing)
            )
        if not self._queues[thief_lane].has_room(item):
            raise QueueFull(
                f"thief lane {thief_lane} has no room for stolen work"
            )

    def _move_item(self, item: WorkItem, thief_lane: int) -> WorkItem:
        self._remove_from_queues(item.packet_id)
        moved = item.with_lane(thief_lane)
        self._queues[thief_lane].push(moved)
        self._by_packet[moved.packet_id] = moved
        return moved

    def steal_item(
        self,
        packet_id: str,
        thief_lane: int,
        *,
        capabilities: Iterable[str] = (),
        capability_epoch: int = 0,
        exclude_roles: Iterable[str] = (),
    ) -> WorkItem:
        """Move one named queued item or raise a typed capability error."""
        thief_lane = _validate_lane(thief_lane)
        held = _name_set(capabilities)
        if not _is_int(capability_epoch) or capability_epoch < 0:
            raise LaneWorkError("capability_epoch must be an integer >= 0")
        exclude = _name_set(exclude_roles)
        item = self._by_packet.get(packet_id)
        if item is None:
            raise LaneWorkError("packet is not queued")
        self._check_steal_candidate(
            item, thief_lane, held, capability_epoch, exclude,
        )
        return self._move_item(item, thief_lane)

    def can_steal(
        self,
        packet_id: str,
        thief_lane: int,
        *,
        capabilities: Iterable[str] = (),
        capability_epoch: int = 0,
        exclude_roles: Iterable[str] = (),
    ) -> bool:
        """Return whether :meth:`steal_item` would succeed, without moving."""
        thief_lane = _validate_lane(thief_lane)
        held = _name_set(capabilities)
        if not _is_int(capability_epoch) or capability_epoch < 0:
            raise LaneWorkError("capability_epoch must be an integer >= 0")
        exclude = _name_set(exclude_roles)
        item = self._by_packet.get(packet_id)
        if item is None:
            return False
        try:
            self._check_steal_candidate(
                item, thief_lane, held, capability_epoch, exclude,
            )
        except LaneWorkError:
            return False
        return True

    def steal(
        self,
        thief_lane: int,
        *,
        capabilities: Iterable[str] = (),
        capability_epoch: int = 0,
        exclude_roles: Iterable[str] = (),
        packet_id: str | None = None,
    ) -> WorkItem | None:
        """Steal one queued, capability-compatible item deterministically."""
        thief_lane = _validate_lane(thief_lane)
        held = _name_set(capabilities)
        if not _is_int(capability_epoch) or capability_epoch < 0:
            raise LaneWorkError("capability_epoch must be an integer >= 0")
        exclude = _name_set(exclude_roles)
        if packet_id is not None:
            return self.steal_item(
                packet_id,
                thief_lane,
                capabilities=held,
                capability_epoch=capability_epoch,
                exclude_roles=exclude,
            )
        candidates: list[WorkItem] = []
        for lane, queue in self._queues.items():
            if lane == thief_lane:
                continue
            for item in queue.items:
                if not item.stealable:
                    continue
                if item.critical:
                    continue
                if item.role in exclude or item.role in self.critical_roles:
                    continue
                if item.capability_epoch > capability_epoch:
                    continue
                if any(need not in held for need in item.capability_requirement):
                    continue
                candidates.append(item)
        if not candidates:
            return None
        candidates.sort(
            key=lambda item: (
                -item.priority,
                item.enqueued_tick,
                item.lane_id,
                item.packet_id,
            )
        )
        chosen = candidates[0]
        if not self._queues[thief_lane].has_room(chosen):
            raise QueueFull(f"thief lane {thief_lane} has no room for stolen work")
        return self._move_item(chosen, thief_lane)

    def reject(self, packet_id: str, *, reason: str = "") -> WorkItem:
        item = self._by_packet.get(packet_id)
        if item is None:
            raise LaneWorkError("packet is not queued")
        if item.state in TERMINAL:
            return item
        updated = item.transition(REJECTED)
        self._replace(item, updated)
        return updated

    def adapter(
        self,
        bridge: Any = None,
        **kwargs: Any,
    ) -> "LaneWorkAdapter":
        """Return an optional execution-path adapter over these queues."""
        return LaneWorkAdapter(self, bridge=bridge, **kwargs)

    def stats(self) -> dict[str, Any]:
        counts = {QUEUED: 0, LEASED: 0, EXECUTING: 0, COMPLETED: 0, REJECTED: 0}
        for item in self._by_packet.values():
            counts[item.state] += 1
        lanes = {
            str(lane): len(queue.items)
            for lane, queue in self._queues.items()
            if queue.items
        }
        return {
            "schema": STATS_SCHEMA,
            "capacity_per_lane": self.capacity,
            "critical_reserve": self.critical_reserve,
            "active_packets": len(self._by_packet),
            "states": counts,
            "nonempty_lanes": lanes,
            "executing": counts[EXECUTING],
        }


class LaneWorkAdapter:
    """Optional projection adapter from execution records to lane queues.

    The adapter accepts an already submitted packet/submission or an already
    leased :class:`MathExecutionLease`-like record.  It records only queue
    identity and lifecycle state.  It owns no job, lease, or result ledger and
    never invokes an executor for an enqueue/begin/executing/finish/steal
    operation.  When a ``bridge`` is supplied, the explicit ``submit``,
    ``lease``, ``execute``, ``complete``, ``fail``, and ``cancel`` wrappers
    delegate to that existing bridge before mirroring the resulting identity.
    """

    durable = False
    owns_jobs = False
    owns_lease_ledger = False

    def __init__(
        self,
        queues: Any = None,
        bridge: Any = None,
        *,
        system: Any = None,
        critical_roles: Iterable[str] | None = None,
        capacity: int = 64,
        critical_reserve: int = 1,
    ) -> None:
        # Allow either LaneWorkAdapter(queues, bridge) or
        # LaneWorkAdapter(bridge, queues); the first form is canonical.
        if (
            queues is not None
            and not isinstance(queues, LaneWorkQueues)
            and isinstance(bridge, LaneWorkQueues)
        ):
            queues, bridge = bridge, queues
        if queues is not None and not isinstance(queues, LaneWorkQueues):
            if bridge is not None:
                raise LaneWorkError("queues must be a LaneWorkQueues instance")
            bridge, queues = queues, None
        if queues is None:
            queues = LaneWorkQueues(
                capacity=capacity,
                critical_reserve=critical_reserve,
                **(
                    {}
                    if critical_roles is None
                    else {"critical_roles": critical_roles}
                ),
            )
        self.queues = queues
        self.bridge = bridge
        self.system = (
            system if system is not None else _record_get(bridge, "system")
        )
        self.critical_roles = frozenset(
            self.queues.critical_roles
            if critical_roles is None
            else critical_roles
        )

    def __repr__(self) -> str:
        return (
            "LaneWorkAdapter("
            f"queues={len(self.queues._by_packet)}, "
            f"bridge={'yes' if self.bridge is not None else 'no'}, "
            f"authoritative='WaveStore/MthSystem')"
        )

    # -- record projection ---------------------------------------------------

    @staticmethod
    def _job_field(record: Any, name: str) -> Any:
        job = _record_get(record, "job")
        if isinstance(job, Mapping):
            return job.get(name)
        return _record_get(job, name)

    def _build_item(
        self,
        record: Any,
        *,
        packet: Any = None,
        lane_id: int | None = None,
        snapshot_id: str | None = None,
        preflight_digest: Any = _UNSET,
        capability_requirement: Any = _UNSET,
        capabilities: Any = None,
        capability_epoch: Any = _UNSET,
        fuel: Any = _UNSET,
        priority: Any = _UNSET,
        role: Any = _UNSET,
        critical: Any = _UNSET,
        tick: Any = _UNSET,
        job_id: Any = _UNSET,
        lease_id: Any = _UNSET,
        lease_epoch: Any = _UNSET,
        lease_owner: Any = _UNSET,
        lease_token_digest: Any = _UNSET,
        deadline_tick: Any = _UNSET,
    ) -> WorkItem:
        packet = packet if packet is not None else _packet_from_record(record)
        lane_value = _first_value(
            lane_id, _record_get(packet, "lane_id"),
            _record_get(record, "lane_id"), 0,
        )
        lane = _validate_lane(lane_value)
        snapshot_value = _first_value(
            snapshot_id,
            _record_get(packet, "snapshot_id"),
            _record_get(record, "snapshot_id"),
            _record_get(packet, "snapshot"),
        )
        if not snapshot_value:
            raise LaneWorkError(
                "submitted packet/lease record has no snapshot_id"
            )
        if preflight_digest is _UNSET:
            preflight_digest = _first_value(
                _preflight_digest_from(packet),
                _preflight_digest_from(record),
            )
        if capability_requirement is _UNSET:
            if capabilities is not None:
                capability_requirement = _capability_names(capabilities)
            else:
                capability_requirement = _capability_names(_first_value(
                    _record_get(packet, "capability_requirement"),
                    _record_get(record, "capability_requirement"),
                    _record_get(packet, "capabilities"),
                    _record_get(record, "capabilities"),
                    _record_get(packet, "requirements"),
                    _record_get(record, "requirements"),
                    _record_get(packet, "capability_set"),
                    _record_get(record, "capability_set"),
                    (),
                ))
        else:
            capability_requirement = _capability_names(capability_requirement)
        if capability_epoch is _UNSET:
            capability_epoch = _first_value(
                _record_get(packet, "capability_epoch"),
                _capability_epoch_from(record),
                _record_get(record, "capability_epoch"),
                0,
            )
        if fuel is _UNSET:
            fuel = _first_value(
                _record_get(packet, "fuel"),
                _record_get(record, "fuel"),
                0,
            )
        if priority is _UNSET:
            priority = _first_value(
                _record_get(packet, "priority"),
                _record_get(record, "priority"),
                _record_get(_record_get(record, "metadata") or {}, "priority"),
                _record_get(_record_get(packet, "metadata") or {}, "priority"),
                0,
            )
        if role is _UNSET:
            role = _first_value(
                _record_get(packet, "role"),
                _record_get(record, "role"),
                _lane_role(lane),
            )
        if critical is _UNSET:
            observed = _record_get(record, "critical")
            if not isinstance(observed, bool):
                observed = _record_get(packet, "critical")
            if isinstance(observed, bool):
                critical = observed
            else:
                critical = (
                    role in self.critical_roles or _is_critical_role(role)
                )
        if tick is _UNSET:
            tick = _first_value(
                _record_get(packet, "enqueued_tick"),
                _record_get(packet, "created_tick"),
                _record_get(record, "enqueued_tick"),
                _record_get(record, "tick"),
                _record_get(record, "now_tick"),
                0,
            )
        if job_id is _UNSET:
            job_id = _first_value(
                _record_get(record, "job_id"),
                self._job_field(record, "job_id"),
                _record_get(packet, "job_id"),
            )
        if lease_id is _UNSET:
            lease_id = _first_value(
                _record_get(record, "lease_id"),
                _record_get(packet, "lease_id"),
            )
        if lease_epoch is _UNSET:
            lease_epoch = _first_value(
                _record_get(record, "lease_epoch"),
                self._job_field(record, "lease_epoch"),
                _record_get(packet, "lease_epoch"),
            )
        if lease_epoch == 0:
            # NMP uses zero as an unleased sentinel; real lease epochs are 1+.
            lease_epoch = None
        if lease_owner is _UNSET:
            lease_owner = _first_value(
                _record_get(record, "lease_owner"),
                _record_get(record, "owner"),
                self._job_field(record, "lease_owner"),
                _record_get(packet, "lease_owner"),
            )
        if lease_token_digest is _UNSET:
            lease_token_digest = _record_get(record, "lease_token_digest")
            if lease_token_digest is None:
                token = _first_value(
                    _record_get(record, "lease_token"),
                    self._job_field(record, "lease_token"),
                )
                if isinstance(token, str) and token:
                    lease_token_digest = hashlib.sha256(
                        token.encode("utf-8")
                    ).hexdigest()
        if deadline_tick is _UNSET:
            deadline_tick = _first_value(
                _record_get(record, "deadline_tick"),
                self._job_field(record, "deadline_tick"),
                _record_get(packet, "deadline_tick"),
            )
        return WorkItem(
            packet_id=_first_value(
                _record_get(packet, "packet_id"),
                _record_get(record, "packet_id"),
            ),
            lane_id=lane,
            snapshot_id=snapshot_value,
            preflight_digest=preflight_digest,
            capability_requirement=capability_requirement,
            capability_epoch=capability_epoch,
            fuel=fuel,
            priority=priority,
            critical=critical,
            role=role,
            state=QUEUED,
            enqueued_tick=tick,
            job_id=job_id,
            lease_id=lease_id,
            lease_epoch=lease_epoch,
            lease_owner=lease_owner,
            lease_token_digest=lease_token_digest,
            deadline_tick=deadline_tick,
        )

    @staticmethod
    def _lease_fields(item: WorkItem) -> dict[str, Any]:
        return {
            "job_id": item.job_id,
            "lease_id": item.lease_id,
            "lease_epoch": item.lease_epoch,
            "lease_owner": item.lease_owner,
            "lease_token_digest": item.lease_token_digest,
            "deadline_tick": item.deadline_tick,
        }

    @staticmethod
    def _assert_compatible(
        existing: WorkItem,
        candidate: WorkItem,
        *,
        check_lane: bool = False,
    ) -> None:
        if check_lane and existing.lane_id != candidate.lane_id:
            raise WorkConflict(
                "packet identity is already queued on another lane"
            )
        for name in (
            "snapshot_id",
            "preflight_digest",
            "capability_requirement",
            "capability_epoch",
            "fuel",
            "priority",
            "role",
            "critical",
        ):
            if getattr(existing, name) != getattr(candidate, name):
                raise WorkConflict(
                    "packet identity is already queued with different "
                    + name
                )
        if (
            existing.job_id is not None
            and candidate.job_id is not None
            and existing.job_id != candidate.job_id
        ):
            raise WorkConflict("packet is already bound to another job")
        if (
            existing.lease_id is not None
            and candidate.lease_id is not None
            and existing.lease_id != candidate.lease_id
        ):
            raise WorkConflict("packet is already bound to another lease")
        if (
            existing.lease_epoch is not None
            and candidate.lease_epoch is not None
            and existing.lease_epoch != candidate.lease_epoch
        ):
            raise WorkConflict("packet is already bound to another lease epoch")

    @staticmethod
    def _lease_executes(record: Any, packet: Any) -> bool:
        state = str(_first_value(
            _record_get(record, "state"),
            _record_get(packet, "state"),
            "",
        )).lower()
        return bool(_record_get(record, "executing", False)) or state in {
            "executing", "running",
        }

    def _finish_if_tracked(self, packet_id: str, state: str) -> None:
        item = self.queues.get(packet_id)
        if item is None or item.state in TERMINAL:
            return
        if item.state == QUEUED and _finish_state(state) == REJECTED:
            self.queues.reject(packet_id)
        elif item.state in {LEASED, EXECUTING}:
            self.queues.finish(packet_id, state=state)

    # -- public queue projection API ----------------------------------------

    def enqueue(self, record: Any, **kwargs: Any) -> WorkItem:
        """Enqueue a WorkItem, submission, packet, or lease record."""
        if isinstance(record, WorkItem):
            if kwargs:
                raise LaneWorkError(
                    "overrides cannot accompany a typed WorkItem"
                )
            return self.queues.enqueue(record)
        packet = _packet_from_record(record)
        state = str(_first_value(
            _record_get(record, "state"),
            _record_get(packet, "state"),
            "",
        )).lower()
        lease_epoch = _record_get(record, "lease_epoch")
        is_lease = (
            state in {"leased", "executing", "running"}
            or lease_epoch not in (None, 0)
            or any(
                _first_value(_record_get(record, name))
                for name in (
                    "lease_token",
                    "lease_id",
                    "lease_owner",
                    "owner",
                    "deadline_tick",
                )
            )
        )
        if is_lease:
            return self.enqueue_lease(record, **kwargs)
        return self.enqueue_submission(record, **kwargs)

    def enqueue_submission(self, submission: Any, **kwargs: Any) -> WorkItem:
        """Enqueue the queued/leased identity of a submitted packet."""
        candidate = self._build_item(submission, **kwargs)
        existing = self.queues.get(candidate.packet_id)
        if existing is not None:
            self._assert_compatible(existing, candidate, check_lane=True)
            return existing
        return self.queues.enqueue(candidate)

    def enqueue_packet(self, packet: Any, **kwargs: Any) -> WorkItem:
        return self.enqueue_submission(packet, **kwargs)

    def enqueue_lease(self, lease: Any, **kwargs: Any) -> WorkItem:
        """Mirror an already acquired lease; never acquire or extend one."""
        candidate = self._build_item(lease, **kwargs)
        packet = _packet_from_record(lease)
        existing = self.queues.get(candidate.packet_id)
        if existing is None:
            item = self.queues.enqueue(candidate)
        else:
            self._assert_compatible(existing, candidate)
            if existing.state in TERMINAL:
                return existing
            item = self.queues.bind_lease(
                existing.packet_id, **self._lease_fields(candidate)
            )
        fields = self._lease_fields(candidate)
        target_executing = self._lease_executes(lease, packet)
        if item.state == QUEUED:
            item = self.queues.begin(item.packet_id, **fields)
        if target_executing and item.state == LEASED:
            item = self.queues.executing(item.packet_id, **fields)
        return item

    def begin(self, packet_id: str, **lease_fields: Any) -> WorkItem:
        item = self.queues.get(packet_id)
        if item is None:
            raise LaneWorkError("packet is not queued")
        if item.state in TERMINAL:
            raise NotStealable("terminal work cannot begin")
        if item.state in {LEASED, EXECUTING}:
            # Idempotent for a retried bridge lease; never downgrade executing.
            provided = {
                key: value for key, value in lease_fields.items()
                if value is not None
            }
            if (
                "job_id" in provided
                and item.job_id is not None
                and provided["job_id"] != item.job_id
            ):
                raise WorkConflict("packet is already bound to another job")
            if (
                "lease_epoch" in provided
                and item.lease_epoch is not None
                and provided["lease_epoch"] != item.lease_epoch
            ):
                raise WorkConflict("packet is already bound to another lease epoch")
            return self.queues.bind_lease(packet_id, **provided)
        return self.queues.begin(packet_id, **lease_fields)

    def executing(self, packet_id: str, **lease_fields: Any) -> WorkItem:
        item = self.queues.get(packet_id)
        if item is None:
            raise LaneWorkError("packet is not queued")
        if item.state == EXECUTING:
            return self.queues.bind_lease(packet_id, **lease_fields) if lease_fields else item
        return self.queues.executing(packet_id, **lease_fields)

    def finish(
        self,
        packet_id: str,
        *,
        state: str = COMPLETED,
        job_id: str | None = None,
        lease_epoch: int | None = None,
    ) -> WorkItem:
        item = self.queues.get(packet_id)
        if item is None:
            raise LaneWorkError("packet is not queued")
        target = _finish_state(state)
        if item.state in TERMINAL:
            if item.state == target:
                return item
            raise WorkConflict(
                f"terminal work is already {item.state}, not {target}"
            )
        if job_id is not None and item.job_id is not None and job_id != item.job_id:
            raise WorkConflict("finish job does not match the queued work")
        if (
            lease_epoch is not None
            and item.lease_epoch is not None
            and lease_epoch != item.lease_epoch
        ):
            raise WorkConflict("finish lease epoch does not match the queued work")
        return self.queues.finish(
            packet_id, state=target, job_id=job_id, lease_epoch=lease_epoch,
        )

    def reject(self, packet_id: str, *, reason: str = "") -> WorkItem:
        return self.queues.reject(packet_id, reason=reason)

    def steal(
        self,
        thief_lane: int,
        *,
        capabilities: Iterable[str] = (),
        capability_epoch: int = 0,
        exclude_roles: Iterable[str] = (),
        packet_id: str | None = None,
    ) -> WorkItem | None:
        return self.queues.steal(
            thief_lane,
            capabilities=capabilities,
            capability_epoch=capability_epoch,
            exclude_roles=exclude_roles,
            packet_id=packet_id,
        )

    def steal_item(
        self,
        packet_id: str,
        thief_lane: int,
        *,
        capabilities: Iterable[str] = (),
        capability_epoch: int = 0,
        exclude_roles: Iterable[str] = (),
    ) -> WorkItem:
        return self.queues.steal_item(
            packet_id,
            thief_lane,
            capabilities=capabilities,
            capability_epoch=capability_epoch,
            exclude_roles=exclude_roles,
        )

    def can_steal(
        self,
        packet_id: str,
        thief_lane: int,
        *,
        capabilities: Iterable[str] = (),
        capability_epoch: int = 0,
        exclude_roles: Iterable[str] = (),
    ) -> bool:
        return self.queues.can_steal(
            packet_id,
            thief_lane,
            capabilities=capabilities,
            capability_epoch=capability_epoch,
            exclude_roles=exclude_roles,
        )

    def dequeue(self, lane_id: int) -> WorkItem | None:
        return self.queues.dequeue(lane_id)

    def get(self, packet_id: str) -> WorkItem | None:
        return self.queues.get(packet_id)

    def stats(self) -> dict[str, Any]:
        return self.queues.stats()

    @property
    def queue(self) -> LaneWorkQueues:
        return self.queues

    @property
    def work(self) -> LaneWorkQueues:
        return self.queues

    def transition(
        self,
        packet_id: str,
        state: str,
        **fields: Any,
    ) -> WorkItem:
        """Apply one explicit lifecycle transition by state name."""
        normalized = str(state).lower()
        if normalized in {QUEUED, LEASED}:
            if normalized == QUEUED:
                item = self.queues.get(packet_id)
                if item is None:
                    raise LaneWorkError("packet is not queued")
                return item
            return self.begin(packet_id, **fields)
        if normalized in {EXECUTING, "running"}:
            return self.executing(packet_id, **fields)
        return self.finish(packet_id, state=normalized, **fields)

    # Aliases used by callers that describe the operation as observation.
    mirror_submission = enqueue_submission
    track_submission = enqueue_submission
    observe_submission = enqueue_submission
    enqueue_submitted = enqueue_submission
    submitted = enqueue_submission
    admit = enqueue
    push = enqueue
    mirror_lease = enqueue_lease
    track_lease = enqueue_lease
    observe_lease = enqueue_lease
    begin_execution = begin
    mark_leased = begin
    mark_executing = executing
    try_steal = steal

    def mark_completed(self, packet_id: str, **fields: Any) -> WorkItem:
        return self.finish(packet_id, state=COMPLETED, **fields)

    def mark_failed(self, packet_id: str, **fields: Any) -> WorkItem:
        return self.finish(packet_id, state=REJECTED, **fields)

    def mark_cancelled(self, packet_id: str, **fields: Any) -> WorkItem:
        return self.finish(packet_id, state=REJECTED, **fields)

    def mark_rejected(self, packet_id: str, *, reason: str = "") -> WorkItem:
        return self.reject(packet_id, reason=reason)

    # -- explicit bridge delegation -----------------------------------------

    def _require_bridge(self, operation: str) -> Any:
        if self.bridge is None:
            raise LaneWorkError(
                f"{operation} requires an execution bridge; "
                "queue-only usage is supported without one"
            )
        method = getattr(self.bridge, operation, None)
        if not callable(method):
            raise LaneWorkError(
                f"execution bridge does not expose {operation}()"
            )
        return method

    def submit(self, *args: Any, **kwargs: Any) -> Any:
        submission = self._require_bridge("submit")(*args, **kwargs)
        self.enqueue_submission(submission)
        return submission

    def submit_batch(self, *args: Any, **kwargs: Any) -> Any:
        batch = self._require_bridge("submit_batch")(*args, **kwargs)
        for child in _record_get(batch, "children", ()) or ():
            self.enqueue_submission(child)
        return batch

    def lease(self, *args: Any, **kwargs: Any) -> Any:
        lease = self._require_bridge("lease")(*args, **kwargs)
        if lease is not None:
            self.enqueue_lease(lease)
        return lease

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        result = self._require_bridge("execute")(*args, **kwargs)
        outcome = str(_record_get(result, "outcome", "")).lower()
        state = (
            COMPLETED
            if outcome in {"completed", "committed"}
            or bool(_record_get(result, "committed", False))
            or bool(_record_get(result, "ok", False))
            else REJECTED
        )
        packet_id = _record_get(result, "packet_id")
        if not packet_id:
            packet = _record_get(result, "packet")
            packet_id = _record_get(packet, "packet_id")
        if isinstance(packet_id, str) and packet_id:
            self._finish_if_tracked(packet_id, state)
        return result

    def complete(self, *args: Any, **kwargs: Any) -> Any:
        result = self._require_bridge("complete")(*args, **kwargs)
        packet_id = _record_get(result, "packet_id")
        if isinstance(packet_id, str) and packet_id:
            self._finish_if_tracked(packet_id, COMPLETED)
        return result

    def fail(self, *args: Any, **kwargs: Any) -> Any:
        result = self._require_bridge("fail")(*args, **kwargs)
        packet_id = _record_get(result, "packet_id")
        if isinstance(packet_id, str) and packet_id:
            self._finish_if_tracked(packet_id, REJECTED)
        return result

    def cancel(self, *args: Any, **kwargs: Any) -> Any:
        result = self._require_bridge("cancel")(*args, **kwargs)
        packet = _packet_from_record(result)
        packet_state = str(_record_get(packet, "state", "")).lower()
        status = str(_record_get(result, "status", "")).lower()
        if packet_state == "cancelled" or status == "cancelled":
            packet_id = _record_get(result, "packet_id") or _record_get(
                packet, "packet_id"
            )
            if isinstance(packet_id, str) and packet_id:
                self._finish_if_tracked(packet_id, REJECTED)
        return result

    run = execute


# Common integration spellings.  The canonical class is LaneWorkAdapter.
LaneWorkExecutionAdapter = LaneWorkAdapter
LaneWorkBridgeAdapter = LaneWorkAdapter
LaneWorkQueueAdapter = LaneWorkAdapter
LaneWorkSubmissionAdapter = LaneWorkAdapter
LaneWorkLeaseAdapter = LaneWorkAdapter
WorkQueueAdapter = LaneWorkAdapter
ExecutionWorkAdapter = LaneWorkAdapter


__all__ = [
    "CRITICAL_ROLES",
    "CapabilityMismatch",
    "ExecutionWorkAdapter",
    "LaneWorkAdapter",
    "LaneWorkBridgeAdapter",
    "LaneWorkError",
    "LaneWorkExecutionAdapter",
    "LaneWorkLeaseAdapter",
    "LaneWorkQueueAdapter",
    "LaneWorkQueues",
    "LaneWorkSubmissionAdapter",
    "NotStealable",
    "QueueFull",
    "SCHEMA",
    "STATS_SCHEMA",
    "STEALABLE",
    "WorkConflict",
    "WorkItem",
    "WorkQueueAdapter",
]
