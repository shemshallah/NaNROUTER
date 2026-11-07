"""Single-active handoff scheduler for the six-slot MC0:0 runner ring.

The ring has six identities, ``MC0:0/R0`` through ``MC0:0/R5``.  The
``NANROUTER-0`` through ``NANROUTER-5`` labels are aliases for those same six
slots; they are not additional runners.

Only one slot is ever active.  The active slot may reserve memory up to the
hard ``7 GiB`` ceiling and may hold leases.  A handoff must first reach zero
leases and zero reserved memory, then checkpoint the old slot.  The old slot
becomes standby (or degraded after a forced failover) and the next non-revoked
slot is activated with a new epoch.

This module is an in-process control-plane model.  It enforces the scheduling
invariants, but it does not reserve host memory, stop a remote process, or
persist a checkpoint payload.  Callers remain responsible for making the real
runner honor the state reported here.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import threading
from typing import Any, Callable

SLOT_COUNT = 6
MC0_SLOTS = tuple(f"MC0:0/R{i}" for i in range(SLOT_COUNT))
NANROUTER_ALIASES = tuple(f"NANROUTER-{i}" for i in range(SLOT_COUNT))
RING_SLOTS = MC0_SLOTS

SLOT_ALIASES = {slot_id: index for index, slot_id in enumerate(MC0_SLOTS)}
SLOT_ALIASES.update(
    {alias: index for index, alias in enumerate(NANROUTER_ALIASES)}
)

DEFAULT_CYCLE_TICKS = 64
DEFAULT_MAX_ACTIVE_MEMORY_BYTES = 7 * 1024 ** 3
SNAPSHOT_SCHEMA = "nanrouter.wave-ring-scheduler.v1"

SLOT_STATUSES = (
    "active",
    "standby",
    "draining",
    "checkpointing",
    "degraded",
    "revoked",
)


class WaveRingSchedulerError(ValueError):
    """Base class for scheduler validation and state errors."""


class RingCapacityError(WaveRingSchedulerError):
    """The active slot would exceed the hard working-memory ceiling."""


class RingBusyError(WaveRingSchedulerError):
    """A handoff was requested while leases or memory are still live."""


class RingCheckpointError(WaveRingSchedulerError):
    """The checkpoint store failed, so activation was not advanced."""


class RingStateError(WaveRingSchedulerError):
    """The requested operation is invalid in the current ring state."""


def resolve_slot(slot: int | str) -> int:
    """Return the canonical 0..5 index for an MC0 or NANROUTER slot label."""
    if isinstance(slot, bool):
        raise WaveRingSchedulerError("slot must be an integer or slot label")
    if isinstance(slot, int):
        index = slot
    elif isinstance(slot, str):
        try:
            index = SLOT_ALIASES[slot]
        except KeyError as exc:
            raise WaveRingSchedulerError(f"unknown runner-ring slot: {slot!r}") from exc
    else:
        raise WaveRingSchedulerError("slot must be an integer or slot label")
    if not 0 <= index < SLOT_COUNT:
        raise WaveRingSchedulerError("runner slot must be in 0..5")
    return index


def _require_int(name: str, value: Any, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise WaveRingSchedulerError(f"{name} must be an integer")
    if value < minimum:
        raise WaveRingSchedulerError(f"{name} must be >= {minimum}")
    return value


def _require_reason(reason: Any) -> str:
    if not isinstance(reason, str) or not reason.strip():
        raise WaveRingSchedulerError("failover reason must be a non-blank string")
    if len(reason) > 256 or any(ord(char) < 32 for char in reason):
        raise WaveRingSchedulerError(
            "failover reason must be <= 256 printable characters"
        )
    return reason


@dataclass
class _Slot:
    index: int
    slot_id: str
    alias: str
    status: str = "standby"
    heartbeat_tick: int | None = None
    memory_reserved_bytes: int = 0
    lease_count: int = 0
    checkpoint_digest: str | None = None
    activated_epoch: int = 0


class WaveRingScheduler:
    """One-active-at-a-time scheduler for ``MC0:0/R0`` .. ``MC0:0/R5``.

    ``cycle_ticks`` is both the expected rotation cadence and the heartbeat
    staleness threshold.  A heartbeat is stale when
    ``now_tick - heartbeat_tick > cycle_ticks``.
    """

    def __init__(
        self,
        cycle_ticks: int = DEFAULT_CYCLE_TICKS,
        *,
        max_active_memory_bytes: int = DEFAULT_MAX_ACTIVE_MEMORY_BYTES,
        now_tick: int = 0,
        checkpoint_store: Callable[[str], Any] | None = None,
    ):
        self.cycle_ticks = _require_int(
            "cycle_ticks", cycle_ticks, minimum=1
        )
        self.max_active_memory_bytes = _require_int(
            "max_active_memory_bytes", max_active_memory_bytes, minimum=1
        )
        self._last_tick = _require_int("now_tick", now_tick)
        if checkpoint_store is not None and not callable(checkpoint_store):
            raise WaveRingSchedulerError("checkpoint_store must be callable")
        self._checkpoint_store = checkpoint_store
        self._lock = threading.RLock()
        self._slots = [
            _Slot(index=index, slot_id=slot_id, alias=alias)
            for index, (slot_id, alias) in enumerate(
                zip(MC0_SLOTS, NANROUTER_ALIASES)
            )
        ]
        self._started = False
        self._active_index: int | None = None
        self._epoch = 0
        self._last_checkpoint: dict[str, Any] | None = None
        self._last_failover_reason: str | None = None
        self._last_failover_tick: int | None = None

    # -- public operations -------------------------------------------------

    def start(self, now_tick: int | None = None) -> dict[str, Any]:
        """Activate exactly one slot; normally slot 0 unless it is revoked."""
        with self._lock:
            tick = self._read_tick(now_tick)
            if self._started:
                raise RingStateError("scheduler has already been started")
            index = self._first_eligible()
            if index is None:
                raise RingStateError("no runner slot is eligible for activation")
            slot = self._slots[index]
            slot.status = "active"
            slot.heartbeat_tick = tick
            slot.memory_reserved_bytes = 0
            slot.lease_count = 0
            slot.activated_epoch = 1
            self._active_index = index
            self._epoch = 1
            self._started = True
            self._last_tick = tick
            return self.snapshot(tick)

    def reserve_memory(self, n: int) -> dict[str, Any]:
        """Reserve ``n`` bytes for the active slot, enforcing the 7 GiB cap."""
        with self._lock:
            active = self._require_active()
            if active.status != "active":
                raise RingStateError(
                    f"slot {active.slot_id} is {active.status}; cannot reserve memory"
                )
            amount = _require_int("memory bytes", n)
            if amount == 0:
                return self.snapshot()
            if active.memory_reserved_bytes + amount > self.max_active_memory_bytes:
                raise RingCapacityError(
                    "reservation would exceed max_active_memory_bytes "
                    f"({active.memory_reserved_bytes} + {amount} > "
                    f"{self.max_active_memory_bytes})"
                )
            active.memory_reserved_bytes += amount
            return self.snapshot()

    def release_memory(self, n: int) -> dict[str, Any]:
        """Release ``n`` bytes from the active slot without underflow."""
        with self._lock:
            active = self._require_active()
            if active.status not in ("active", "draining", "degraded"):
                raise RingStateError(
                    f"slot {active.slot_id} is {active.status}; cannot release memory"
                )
            amount = _require_int("memory bytes", n)
            if amount > active.memory_reserved_bytes:
                raise RingStateError(
                    "cannot release more memory than the active slot has reserved"
                )
            active.memory_reserved_bytes -= amount
            return self.snapshot()

    def register_lease(self, count: int = 1) -> dict[str, Any]:
        """Register one or more live leases on the active slot."""
        with self._lock:
            active = self._require_active()
            if active.status != "active":
                raise RingStateError(
                    f"slot {active.slot_id} is {active.status}; cannot take a lease"
                )
            amount = _require_int("lease count", count, minimum=1)
            active.lease_count += amount
            return self.snapshot()

    def release_lease(self, count: int = 1) -> dict[str, Any]:
        """Release one or more leases from the active slot without underflow."""
        with self._lock:
            active = self._require_active()
            if active.status not in ("active", "draining", "degraded"):
                raise RingStateError(
                    f"slot {active.slot_id} is {active.status}; cannot release a lease"
                )
            amount = _require_int("lease count", count, minimum=1)
            if amount > active.lease_count:
                raise RingStateError(
                    "cannot release more leases than the active slot holds"
                )
            active.lease_count -= amount
            return self.snapshot()

    def heartbeat(self, now_tick: int | None = None) -> dict[str, Any]:
        """Record a live heartbeat for the one active slot."""
        with self._lock:
            tick = self._read_tick(now_tick)
            active = self._require_active()
            active.heartbeat_tick = tick
            self._last_tick = tick
            return self.snapshot(tick)

    def cycle(self, now_tick: int | None = None) -> dict[str, Any]:
        """Checkpoint the active slot and activate the next eligible slot.

        If the active slot still has leases or reserved memory, the handoff is
        refused and the active slot enters ``draining``.  Callers must release
        the remaining leases and memory and call ``cycle`` again.
        """
        with self._lock:
            tick = self._read_tick(now_tick)
            active = self._require_active()
            next_index = self._next_eligible(active.index)
            if next_index is None:
                raise RingStateError("no other runner slot is eligible for activation")
            if active.lease_count > 0 or active.memory_reserved_bytes > 0:
                if active.status == "active":
                    active.status = "draining"
                active.heartbeat_tick = tick
                self._last_tick = tick
                raise RingBusyError(
                    "handoff refused: active leases="
                    f"{active.lease_count}, active memory="
                    f"{active.memory_reserved_bytes}"
                )
            self._checkpoint_and_activate(
                tick, next_index, forced=False, reason=None
            )
            return self.snapshot(tick)

    def force_failover(
        self, now_tick: int | None = None, reason: str = "forced"
    ) -> dict[str, Any]:
        """Checkpoint and advance after a failure, marking the old slot degraded.

        Failover is allowed only when the active slot has zero leases and zero
        reserved memory, because otherwise a live working set would overlap the
        next activation.
        """
        with self._lock:
            tick = self._read_tick(now_tick)
            active = self._require_active()
            failover_reason = _require_reason(reason)
            next_index = self._next_eligible(active.index)
            if next_index is None:
                raise RingStateError("no other runner slot is eligible for activation")
            if active.lease_count > 0 or active.memory_reserved_bytes > 0:
                if active.status == "active":
                    active.status = "draining"
                active.heartbeat_tick = tick
                self._last_tick = tick
                raise RingBusyError(
                    "failover refused: active leases="
                    f"{active.lease_count}, active memory="
                    f"{active.memory_reserved_bytes}"
                )
            self._checkpoint_and_activate(
                tick, next_index, forced=True, reason=failover_reason
            )
            return self.snapshot(tick)

    def revoke_slot(self, slot: int | str) -> dict[str, Any]:
        """Revoke a standby or degraded slot so activation skips it."""
        with self._lock:
            index = resolve_slot(slot)
            candidate = self._slots[index]
            if index == self._active_index:
                raise RingStateError("the active slot cannot be revoked in place")
            if candidate.memory_reserved_bytes or candidate.lease_count:
                raise RingStateError("a slot with live resources cannot be revoked")
            candidate.status = "revoked"
            candidate.heartbeat_tick = None
            return self.snapshot()

    def restore_slot(self, slot: int | str) -> dict[str, Any]:
        """Return a revoked slot to standby so it can be activated again."""
        with self._lock:
            index = resolve_slot(slot)
            candidate = self._slots[index]
            if candidate.status != "revoked":
                raise RingStateError("only a revoked slot can be restored")
            candidate.status = "standby"
            candidate.heartbeat_tick = None
            return self.snapshot()

    def is_stale(self, now_tick: int | None = None) -> bool:
        """Return whether the active heartbeat exceeds ``cycle_ticks``."""
        with self._lock:
            tick = self._last_tick if now_tick is None else _require_int(
                "now_tick", now_tick
            )
            if self._active_index is None:
                return False
            active = self._slots[self._active_index]
            if active.heartbeat_tick is None:
                return False
            return tick - active.heartbeat_tick > self.cycle_ticks

    def stale_slots(self, now_tick: int | None = None) -> tuple[int, ...]:
        """Return the indices of stale slots (at most the one active slot)."""
        with self._lock:
            tick = self._last_tick if now_tick is None else _require_int(
                "now_tick", now_tick
            )
            if self._active_index is None:
                return ()
            active = self._slots[self._active_index]
            if (
                active.heartbeat_tick is not None
                and tick - active.heartbeat_tick > self.cycle_ticks
            ):
                return (active.index,)
            return ()

    def snapshot(self, now_tick: int | None = None) -> dict[str, Any]:
        """Return a detached, plain-data view of the scheduler state."""
        with self._lock:
            tick = self._last_tick if now_tick is None else _require_int(
                "now_tick", now_tick
            )
            active = (
                self._slots[self._active_index]
                if self._active_index is not None
                else None
            )
            stale = bool(
                active is not None
                and active.heartbeat_tick is not None
                and tick - active.heartbeat_tick > self.cycle_ticks
            )
            slots = [self._slot_snapshot(slot, tick, stale) for slot in self._slots]
            active_count = sum(slot["status"] == "active" for slot in slots)
            if not self._started:
                health = "idle"
            elif active is None:
                health = "failed"
            elif stale:
                health = "stale"
            elif active.status in ("draining", "checkpointing", "degraded"):
                health = "degraded"
            elif any(
                slot.status in ("degraded", "revoked") for slot in self._slots
            ):
                health = "degraded"
            else:
                health = "green"
            return {
                "schema": SNAPSHOT_SCHEMA,
                "slot_count": SLOT_COUNT,
                "slot_ids": list(MC0_SLOTS),
                "slot_aliases": list(NANROUTER_ALIASES),
                "started": self._started,
                "now_tick": tick,
                "cycle_ticks": self.cycle_ticks,
                "max_active_memory_bytes": self.max_active_memory_bytes,
                "epoch": self._epoch,
                "active_slot": (
                    self._active_index if self._active_index is not None else None
                ),
                "active_slot_id": active.slot_id if active is not None else None,
                "active_alias": active.alias if active is not None else None,
                "active_memory_bytes": (
                    active.memory_reserved_bytes if active is not None else 0
                ),
                "active_memory_reserved_bytes": (
                    active.memory_reserved_bytes if active is not None else 0
                ),
                "active_lease_count": (
                    active.lease_count if active is not None else 0
                ),
                "active_count": active_count,
                "stale": stale,
                "last_checkpoint": (
                    dict(self._last_checkpoint)
                    if self._last_checkpoint is not None
                    else None
                ),
                "last_failover_reason": self._last_failover_reason,
                "last_failover_tick": self._last_failover_tick,
                "health": health,
                "slots": slots,
            }

    # -- internal state transitions ---------------------------------------

    def _read_tick(self, now_tick: int | None) -> int:
        if now_tick is None:
            return self._last_tick
        tick = _require_int("now_tick", now_tick)
        if tick < self._last_tick:
            raise WaveRingSchedulerError("scheduler tick cannot move backwards")
        return tick

    def _require_active(self) -> _Slot:
        if not self._started or self._active_index is None:
            raise RingStateError("scheduler has not been started")
        return self._slots[self._active_index]

    def _first_eligible(self) -> int | None:
        for slot in self._slots:
            if slot.status != "revoked":
                return slot.index
        return None

    def _next_eligible(self, current_index: int) -> int | None:
        for step in range(1, SLOT_COUNT + 1):
            index = (current_index + step) % SLOT_COUNT
            if self._slots[index].status != "revoked":
                return index
        return None

    def _checkpoint_and_activate(
        self,
        tick: int,
        next_index: int,
        *,
        forced: bool,
        reason: str | None,
    ) -> None:
        active = self._slots[self._active_index]  # type: ignore[index]
        next_slot = self._slots[next_index]
        if next_slot.memory_reserved_bytes or next_slot.lease_count:
            raise RingStateError("next slot still holds a live working set")
        if active.memory_reserved_bytes or active.lease_count:
            raise RingStateError("active slot still holds a live working set")

        active.status = "checkpointing"
        digest = self._checkpoint_digest(active, tick)
        if self._checkpoint_store is not None:
            try:
                self._checkpoint_store(digest)
            except Exception as exc:
                active.status = "degraded"
                active.heartbeat_tick = tick
                self._last_tick = tick
                raise RingCheckpointError(
                    "checkpoint store failed; handoff aborted"
                ) from exc

        active.checkpoint_digest = digest
        active.memory_reserved_bytes = 0
        active.lease_count = 0
        active.heartbeat_tick = None
        active.status = "degraded" if forced else "standby"
        self._last_checkpoint = {
            "slot": active.index,
            "slot_id": active.slot_id,
            "alias": active.alias,
            "epoch": self._epoch,
            "tick": tick,
            "digest": digest,
        }

        next_slot.status = "active"
        next_slot.heartbeat_tick = tick
        next_slot.memory_reserved_bytes = 0
        next_slot.lease_count = 0
        self._active_index = next_index
        self._epoch += 1
        next_slot.activated_epoch = self._epoch
        self._last_tick = tick
        if forced:
            self._last_failover_reason = reason
            self._last_failover_tick = tick

    def _checkpoint_digest(self, slot: _Slot, tick: int) -> str:
        prior = slot.checkpoint_digest or ""
        material = (
            f"{slot.slot_id}\0{self._epoch}\0{tick}\0{prior}".encode("utf-8")
        )
        return hashlib.sha256(material).hexdigest()

    def _slot_snapshot(
        self, slot: _Slot, now_tick: int, stale: bool
    ) -> dict[str, Any]:
        age = (
            max(0, now_tick - slot.heartbeat_tick)
            if slot.heartbeat_tick is not None
            else None
        )
        return {
            "index": slot.index,
            "slot": slot.index,
            "slot_id": slot.slot_id,
            "runner_id": slot.slot_id,
            "alias": slot.alias,
            "status": slot.status,
            "heartbeat_tick": slot.heartbeat_tick,
            "heartbeat_age_ticks": age,
            "stale": stale and slot.index == self._active_index,
            "memory_reserved_bytes": slot.memory_reserved_bytes,
            "lease_count": slot.lease_count,
            "checkpoint_digest": slot.checkpoint_digest,
            "activated_epoch": slot.activated_epoch,
        }


__all__ = [
    "DEFAULT_CYCLE_TICKS",
    "DEFAULT_MAX_ACTIVE_MEMORY_BYTES",
    "MC0_SLOTS",
    "NANROUTER_ALIASES",
    "RING_SLOTS",
    "RingBusyError",
    "RingCapacityError",
    "RingCheckpointError",
    "RingStateError",
    "SLOT_ALIASES",
    "SLOT_COUNT",
    "SLOT_STATUSES",
    "SNAPSHOT_SCHEMA",
    "WaveRingScheduler",
    "WaveRingSchedulerError",
    "resolve_slot",
]
