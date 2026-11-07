"""Thin runtime facade over the MTH registry, wave store, service, and ring.

:class:`MthSystem` composes four existing control-plane objects into one small
entry point:

* :class:`runner_riddle.mth_registry.MthRegistry` resolves and validates plans;
* :class:`runner_riddle.wave_store.WaveStore` owns durable job/evidence state;
* :class:`runner_riddle.wave_service.WaveService` enforces caller roles;
* :class:`runner_riddle.wave_ring_scheduler.WaveRingScheduler` selects the one
  active runner slot.

This module deliberately adds no fifth authority.  It performs no host
mathematics, executes no kernel, opens no database, starts no process, and
stores no credential.  Every mutating call is delegated to the object that
already owns that operation.
"""
from __future__ import annotations

from typing import Any

from .mth_registry import MthPlan, MthRegistry
from .wave_ring_scheduler import JAHS_SEAL, WaveRingScheduler, resolve_slot
from .wave_service import WaveService
from .wave_store import WaveStore

SYSTEM_SCHEMA = "nanrouter.mth-system.v1"
HEALTH_SCHEMA = "nanrouter.mth-system-health.v1"
POINT_ZERO_SCHEMA = "nanrouter.mth-point-zero.v1"

# The canonical public ingress from spec/address-grammar.md.  It is stable and
# intentionally contains no runner-slot identity.
POINT_ZERO_ADDRESS = "nan://GM0:SC0:MC0:BS0:0:HW0:0"
POINT_ZERO_ROUTE = POINT_ZERO_ADDRESS
POINT_ZERO_IDENTITY = "BS0:0"
POINT_ZERO_WIRE = "BSR0"

# NaN16 words are 64-bit in the point-0 framing contract.  Callers may override
# this if their plan workspace is expressed in a different word width.
DEFAULT_WORKSPACE_WORD_BYTES = 8

# The announced 1 MiB guest target.  Callers may override this per plan or
# deployment; the effective budget is still min(guest, runner-ceiling).
DEFAULT_GUEST_BUDGET_BYTES = 1024 * 1024
DEFAULT_PAGE_BYTES = 32 * 1024


class MthSystemError(ValueError):
    """Base class for runtime-facade validation and state failures."""


class MthSystemConfigError(MthSystemError):
    """The facade was constructed with incompatible or invalid components."""


class MthSystemPlanError(MthSystemError):
    """A submitted object is not a valid MTH plan."""


class MthSystemWorkspaceError(MthSystemError):
    """A plan or job exceeds its declared workspace bound or budget."""


class MthSystemSlotError(MthSystemError):
    """A lease owner is not the scheduler's current active slot."""


def _require_int(name: str, value: Any, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise MthSystemConfigError(f"{name} must be an integer")
    if value < minimum:
        raise MthSystemConfigError(f"{name} must be >= {minimum}")
    return value


class MthSystem:
    """Compose the registry, store, service, and scheduler into one facade.

    The constructor does not start the scheduler.  Callers still call
    ``scheduler.start()`` (and later ``cycle()``/``force_failover()``) on the
    ring they passed in.  The facade only reads the ring snapshot.

    ``guest_budget_bytes`` is the separately declared guest working-set budget.
    When omitted, :data:`DEFAULT_GUEST_BUDGET_BYTES` (1 MiB) is used.  The
    effective workspace budget is the smaller of the guest budget and the
    runner ceiling.  Callers can override both values; no hardware size is
    inferred from the 7 GiB runner ceiling.
    """

    def __init__(
        self,
        registry: MthRegistry,
        store: WaveStore,
        service: WaveService,
        scheduler: WaveRingScheduler,
        *,
        guest_budget_bytes: int | None = None,
        workspace_word_bytes: int = DEFAULT_WORKSPACE_WORD_BYTES,
        enforce_active_slot: bool = True,
    ) -> None:
        if not isinstance(registry, MthRegistry):
            raise MthSystemConfigError("registry must be an MthRegistry")
        if not isinstance(store, WaveStore):
            raise MthSystemConfigError("store must be a WaveStore")
        if not isinstance(service, WaveService):
            raise MthSystemConfigError("service must be a WaveService")
        if not isinstance(scheduler, WaveRingScheduler):
            raise MthSystemConfigError("scheduler must be a WaveRingScheduler")
        if service.store is not store:
            raise MthSystemConfigError(
                "service and facade must share the same WaveStore"
            )
        if not isinstance(enforce_active_slot, bool):
            raise MthSystemConfigError("enforce_active_slot must be a boolean")

        self.registry = registry
        self.store = store
        self.service = service
        self.scheduler = scheduler
        self.workspace_word_bytes = _require_int(
            "workspace_word_bytes", workspace_word_bytes, minimum=1
        )
        self.runner_budget_bytes = scheduler.max_active_memory_bytes
        if guest_budget_bytes is None:
            guest_budget_bytes = DEFAULT_GUEST_BUDGET_BYTES
        self.guest_budget_bytes = _require_int(
            "guest_budget_bytes", guest_budget_bytes, minimum=0
        )
        self.workspace_budget_bytes = min(
            self.guest_budget_bytes, self.runner_budget_bytes
        )
        self.enforce_active_slot = enforce_active_slot

    def __repr__(self) -> str:
        return (
            "MthSystem("
            f"kernels={len(self.registry)}, "
            f"workspace_budget_bytes={self.workspace_budget_bytes}, "
            f"enforce_active_slot={self.enforce_active_slot})"
        )

    # -- Planning -------------------------------------------------------------

    def plan(self, plan_spec: dict[str, Any]) -> MthPlan:
        """Compose and validate a deterministic plan through the registry."""
        return self.registry.compose(plan_spec)

    # -- Jobs and leases ------------------------------------------------------

    def submit_plan(
        self,
        plan: MthPlan,
        submit_token: str,
        job_id: str,
        universe_id: str,
        operator_digest: str,
        generation: int,
        payload: Any = None,
        now_tick: int = 0,
        *,
        kind: str = "wave",
        operator_id: str | None = None,
        precision: str | None = None,
        workspace: int | None = None,
    ) -> dict[str, Any]:
        """Enqueue a validated plan as a bounded wave job.

        The job workspace is capped by ``plan.workspace_words``.  A plan whose
        declared bound exceeds the effective guest/runner budget is rejected
        before the service or store is called.
        """
        if not isinstance(plan, MthPlan):
            raise MthSystemPlanError("plan must be an MthPlan")
        self.registry.validate_plan(plan)

        plan_bound = plan.workspace_words
        plan_bytes = plan_bound * self.workspace_word_bytes
        if plan_bytes > self.workspace_budget_bytes:
            raise MthSystemWorkspaceError(
                f"plan workspace bound {plan_bound} words ({plan_bytes} bytes) "
                f"exceeds the workspace budget of "
                f"{self.workspace_budget_bytes} bytes"
            )

        required_words = sum(
            self.registry.require(step.kernel_id).workspace_words
            for step in plan.steps
        )
        if workspace is None:
            job_workspace = plan_bound
        else:
            if isinstance(workspace, bool) or not isinstance(workspace, int):
                raise MthSystemWorkspaceError("workspace must be an integer")
            if workspace < 0:
                raise MthSystemWorkspaceError("workspace must be >= 0")
            # The plan bound is the hard cap; a larger request cannot widen it.
            job_workspace = min(workspace, plan_bound)
        if job_workspace < required_words:
            raise MthSystemWorkspaceError(
                f"job workspace {job_workspace} words is below the plan's "
                f"required {required_words} words"
            )

        return self.service.submit_job(
            submit_token,
            job_id,
            universe_id,
            operator_digest,
            generation,
            payload,
            now_tick,
            kind=kind,
            operator_id=operator_id,
            precision=precision,
            workspace=job_workspace,
        )

    def lease(
        self,
        worker_token: str,
        owner: str,
        now_tick: int,
        lease_ticks: int = 64,
        *,
        expected_generation: int | None = None,
        max_attempts: int = 8,
        job_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Lease one job for the active runner slot or one of its aliases."""
        if self.enforce_active_slot:
            snapshot = self.scheduler.snapshot()
            active = snapshot["active_slot"]
            if not snapshot["started"] or active is None:
                raise MthSystemSlotError("runner ring has no active slot")
            jahs = snapshot.get("jahs")
            if not isinstance(jahs, dict) or jahs.get("seal") != JAHS_SEAL:
                raise MthSystemSlotError(
                    "runner ring handoff seal is missing; JAHS gate not satisfied"
                )
            try:
                owner_index = resolve_slot(owner)
            except ValueError as exc:
                raise MthSystemSlotError(str(exc)) from exc
            if owner_index != active:
                raise MthSystemSlotError(
                    f"lease owner {owner!r} is not the active runner slot"
                )
        return self.service.lease_job(
            worker_token,
            owner,
            now_tick,
            lease_ticks,
            expected_generation=expected_generation,
            max_attempts=max_attempts,
            job_id=job_id,
        )

    def complete(
        self,
        worker_token: str,
        job_id: str,
        lease_token: str,
        lease_epoch: int,
        result_digest: str,
        now_tick: int,
        *,
        result_generation: int | None = None,
        lease_owner: str | None = None,
    ) -> dict[str, Any]:
        """Complete a leased job through the authenticated service."""
        return self.service.complete_job(
            worker_token,
            job_id,
            lease_token,
            lease_epoch,
            result_digest,
            now_tick,
            result_generation=result_generation,
            lease_owner=lease_owner,
        )

    # -- Capability registration ---------------------------------------------

    def register_capability(
        self,
        admin_token: str,
        kernel_id: str,
        runner_id: str,
        verified_digest: str,
        workspace: int,
        precision: str,
        *,
        status: str = "declared",
        epoch: int = 1,
        nanclock_tick: int = 0,
    ) -> dict[str, Any]:
        """Register a runner capability through the authenticated service."""
        return self.service.register_capability(
            admin_token,
            kernel_id,
            runner_id,
            verified_digest,
            workspace,
            precision,
            status=status,
            epoch=epoch,
            nanclock_tick=nanclock_tick,
        )

    # -- Evidence -------------------------------------------------------------

    def store_trace(
        self,
        token: str,
        universe_id: str,
        generation: int,
        digest: str,
        producer: str,
        nanclock_tick: int,
        signature: str,
        *,
        payload: Any = None,
        payload_blob: bytes | None = None,
        trace_id: str | None = None,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        """Append trace evidence through the authenticated service."""
        return self.service.store_trace(
            token,
            universe_id,
            generation,
            digest,
            producer,
            nanclock_tick,
            signature,
            payload=payload,
            payload_blob=payload_blob,
            trace_id=trace_id,
            job_id=job_id,
        )

    def store_seal(
        self,
        token: str,
        universe_id: str,
        generation: int,
        digest: str,
        producer: str,
        nanclock_tick: int,
        signature: str,
        *,
        payload: Any = None,
        payload_blob: bytes | None = None,
        seal_id: str | None = None,
        job_id: str | None = None,
    ) -> dict[str, Any]:
        """Append seal evidence through the authenticated service."""
        return self.service.store_seal(
            token,
            universe_id,
            generation,
            digest,
            producer,
            nanclock_tick,
            signature,
            payload=payload,
            payload_blob=payload_blob,
            seal_id=seal_id,
            job_id=job_id,
        )

    def store_signature(
        self,
        token: str,
        universe_id: str,
        generation: int,
        kind: str,
        digest: str,
        producer: str,
        nanclock_tick: int,
        signature: str,
        *,
        payload: Any = None,
        payload_blob: bytes | None = None,
        signature_id: str | None = None,
    ) -> dict[str, Any]:
        """Append signature evidence through the authenticated service."""
        return self.service.store_signature(
            token,
            universe_id,
            generation,
            kind,
            digest,
            producer,
            nanclock_tick,
            signature,
            payload=payload,
            payload_blob=payload_blob,
            signature_id=signature_id,
        )

    # Familiar aliases matching WaveStore/WaveService naming.
    append_trace = store_trace
    append_seal = store_seal
    append_signature = store_signature

    # -- Ring and point 0 -----------------------------------------------------

    def ring(self) -> dict[str, Any]:
        """Return the scheduler's detached, plain-data snapshot."""
        return self.scheduler.snapshot()

    def active_slot(self) -> dict[str, Any]:
        """Return the stable point-0 route plus current active-slot evidence."""
        return self._point_zero_document(self.scheduler.snapshot())

    def point_zero_route(self) -> dict[str, Any]:
        """Return the stable public route; the active slot is evidence only."""
        return self._point_zero_document(self.scheduler.snapshot())

    def _point_zero_document(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema": POINT_ZERO_SCHEMA,
            "route": POINT_ZERO_ADDRESS,
            "point_zero": POINT_ZERO_IDENTITY,
            "wire": POINT_ZERO_WIRE,
            "started": snapshot["started"],
            "active_slot": snapshot["active_slot"],
            "active_slot_id": snapshot["active_slot_id"],
            "active_alias": snapshot["active_alias"],
            "epoch": snapshot["epoch"],
            "jahs": snapshot.get("jahs"),
            "stale": snapshot["stale"],
            "health": snapshot["health"],
        }

    # -- Observability --------------------------------------------------------

    def health(self) -> dict[str, Any]:
        """Merge token-free store, registry, ring, and budget health."""
        store_health = self.store.health()
        registry_health = self.registry.health()
        ring_snapshot = self.scheduler.snapshot()

        ring_health = ring_snapshot["health"]
        if store_health.get("status") != "green":
            status = "degraded"
        elif ring_health == "green":
            status = "green"
        elif ring_health == "idle":
            status = "idle"
        else:
            status = "degraded"

        return {
            "schema": HEALTH_SCHEMA,
            "status": status,
            "store": store_health,
            "registry": registry_health,
            "ring": ring_snapshot,
            "point_zero": {
                "route": POINT_ZERO_ADDRESS,
                "point_zero": POINT_ZERO_IDENTITY,
                "wire": POINT_ZERO_WIRE,
            },
            "budgets": {
                "workspace_word_bytes": self.workspace_word_bytes,
                "page_bytes": DEFAULT_PAGE_BYTES,
                "guest_budget_bytes": self.guest_budget_bytes,
                "guest_budget_words": (
                    self.guest_budget_bytes // self.workspace_word_bytes
                ),
                "guest_budget_pages": (
                    self.guest_budget_bytes // DEFAULT_PAGE_BYTES
                ),
                "runner_budget_bytes": self.runner_budget_bytes,
                "workspace_budget_bytes": self.workspace_budget_bytes,
                "workspace_budget_words": (
                    self.workspace_budget_bytes // self.workspace_word_bytes
                ),
            },
            "enforce_active_slot": self.enforce_active_slot,
        }


__all__ = [
    "DEFAULT_GUEST_BUDGET_BYTES",
    "DEFAULT_PAGE_BYTES",
    "DEFAULT_WORKSPACE_WORD_BYTES",
    "HEALTH_SCHEMA",
    "MthSystem",
    "MthSystemConfigError",
    "MthSystemError",
    "MthSystemPlanError",
    "MthSystemSlotError",
    "MthSystemWorkspaceError",
    "POINT_ZERO_ADDRESS",
    "POINT_ZERO_IDENTITY",
    "POINT_ZERO_ROUTE",
    "POINT_ZERO_SCHEMA",
    "POINT_ZERO_WIRE",
    "SYSTEM_SCHEMA",
]
