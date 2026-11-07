"""Bounded logical-lane work queues and capability-safe stealing (P11 §11.4).

A lane is a durable work identity, not a runner.  Work stealing moves only
independent, not-yet-executing NMP packets between lane queues.  It never
steals a partially executing packet, never creates a second runner, and never
grants a capability the destination runner does not hold.

The module is host-control only.  It performs no mathematics, owns no durable
job/lease ledger, and imports no executor or runtime facade.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Iterable, Mapping

from .lane_registry import LANE_COUNT

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
            "role": self.role,
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
        )

    def transition(self, state: str, *, job_id: str | None = None) -> "WorkItem":
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

    def begin(self, packet_id: str, *, job_id: str | None = None) -> WorkItem:
        item = self._by_packet.get(packet_id)
        if item is None:
            raise LaneWorkError("packet is not queued")
        if item.state != QUEUED:
            raise NotStealable("packet is not in a queued state")
        updated = item.transition(LEASED, job_id=job_id)
        self._replace(item, updated)
        return updated

    def executing(self, packet_id: str) -> WorkItem:
        item = self._by_packet.get(packet_id)
        if item is None:
            raise LaneWorkError("packet is not queued")
        if item.state != LEASED:
            raise LaneWorkError("packet must be leased before executing")
        updated = item.transition(EXECUTING)
        self._replace(item, updated)
        return updated

    def finish(self, packet_id: str, *, state: str = COMPLETED) -> WorkItem:
        item = self._by_packet.get(packet_id)
        if item is None:
            raise LaneWorkError("packet is not queued")
        if item.state not in {LEASED, EXECUTING}:
            raise LaneWorkError("only leased/executing work can finish")
        updated = item.transition(state)
        self._replace(item, updated)
        return updated

    def steal(
        self,
        thief_lane: int,
        *,
        capabilities: Iterable[str] = (),
        capability_epoch: int = 0,
        exclude_roles: Iterable[str] = (),
    ) -> WorkItem | None:
        """Steal one queued, capability-compatible item deterministically."""
        thief_lane = _validate_lane(thief_lane)
        held = frozenset(str(item) for item in capabilities)
        if not _is_int(capability_epoch) or capability_epoch < 0:
            raise LaneWorkError("capability_epoch must be an integer >= 0")
        exclude = frozenset(str(role) for role in exclude_roles)
        candidates: list[WorkItem] = []
        for lane, queue in self._queues.items():
            if lane == thief_lane:
                continue
            for item in queue.items:
                if not item.stealable:
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
        self._remove_from_queues(chosen.packet_id)
        moved = chosen.with_lane(thief_lane)
        self._queues[thief_lane].push(moved)
        self._by_packet[moved.packet_id] = moved
        return moved

    def reject(self, packet_id: str, *, reason: str = "") -> WorkItem:
        item = self._by_packet.get(packet_id)
        if item is None:
            raise LaneWorkError("packet is not queued")
        if item.state in TERMINAL:
            return item
        updated = item.transition(REJECTED)
        self._replace(item, updated)
        return updated

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


__all__ = [
    "CRITICAL_ROLES",
    "CapabilityMismatch",
    "LaneWorkError",
    "LaneWorkQueues",
    "NotStealable",
    "QueueFull",
    "SCHEMA",
    "STATS_SCHEMA",
    "STEALABLE",
    "WorkConflict",
    "WorkItem",
]
