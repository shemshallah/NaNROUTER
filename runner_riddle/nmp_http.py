"""NMP-aware adapter over the durable WaveService job/lease plane.

This module deliberately adds no second job store.  Packet records live in the
existing wave_job.payload_json; job state and worker leases remain authoritative
in WaveStore.  Current admission/ruleset/capability/ring evidence is supplied by
a server-owned context provider and is never accepted from the HTTP caller.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Mapping

from .math_objects import digest_object
from .nmp import (
    EXECUTING,
    QUEUED,
    NmpPacket,
    validate_native_admission_receipt,
)
from .wave_service import WaveService

NMP_JOB_KIND = "nmp"
NMP_PAYLOAD_KEY = "nmp_packet"
# Keep admission aligned with the Android NaN16 worker and completion ABI.
NMP_WORKER_PROGRAM_IDS = frozenset({78, 79})
NMP_WORKER_FUNCTION_PROGRAMS = {
    "math.vector.add.v1": 78,
    "math.vector.dot.v1": 79,
}


class NmpHttpError(ValueError):
    """A rejected NMP transport operation."""


ContextProvider = Callable[..., Mapping[str, Any]]
WorkerIdentityProvider = Callable[[str, str], bool]


def _context(provider: ContextProvider, packet: NmpPacket, stage: str,
             *, job: Mapping[str, Any] | None = None,
             lease: Mapping[str, Any] | None = None) -> dict[str, Any]:
    value = provider(packet=packet, stage=stage, job=job, lease=lease)
    if not isinstance(value, Mapping):
        raise NmpHttpError("server admission context is unavailable")
    result = dict(value)
    forbidden = {"job", "lease", "tick", "now_tick", "gate"}
    if forbidden.intersection(result):
        raise NmpHttpError("context provider returned reserved gate fields")
    # Binary trust pins are completion-only; never leak them as kwargs into
    # the separate queue / execution-gate contract signatures.
    if stage != "complete":
        result.pop("expected_guest_image_digest", None)
        result.pop("expected_guest_source_digest", None)
    return result



def _require_server_program_binding(packet: NmpPacket, context: dict[str, Any]) -> int:
    """Bind the guest-echoed program ID to the server-owned function registry."""
    expected = context.pop("expected_program_id", None)
    if isinstance(expected, bool) or not isinstance(expected, int) or expected not in NMP_WORKER_PROGRAM_IDS:
        raise NmpHttpError("server admission context has no supported NaN16 worker program_id")
    canonical_program = NMP_WORKER_FUNCTION_PROGRAMS.get(packet.function_id)
    if canonical_program is None or expected != canonical_program:
        raise NmpHttpError("server registry program_id does not match the NaN16 worker function ABI")
    receipt = packet.admission_receipt
    if not isinstance(receipt, Mapping) or receipt.get("program_id") != expected:
        raise NmpHttpError("native receipt program_id does not match the server-owned function registry")
    return expected


def _validate_execution_evidence(
    evidence: Any, *, packet: NmpPacket, expected_program_id: int,
    result_digest: str, lease_epoch: int, lease_owner: str,
    expected_image_digest: str | None = None,
    expected_source_digest: str | None = None,
) -> dict[str, Any]:
    if not isinstance(evidence, Mapping):
        raise NmpHttpError("native kernel execution evidence is required")
    if evidence.get("schema") != "nanrouter.native-kernel-execution.v1":
        raise NmpHttpError("native kernel execution evidence schema is invalid")
    if evidence.get("packet_id") != packet.packet_id:
        raise NmpHttpError("kernel execution evidence is bound to another packet")
    if evidence.get("function_id") != packet.function_id:
        raise NmpHttpError("kernel execution evidence function does not match the packet")
    program_id = evidence.get("program_id")
    if isinstance(program_id, bool) or not isinstance(program_id, int) or program_id != expected_program_id:
        raise NmpHttpError("kernel execution program_id does not match the server-owned function registry")
    epoch = evidence.get("lease_epoch")
    if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch != lease_epoch:
        raise NmpHttpError("kernel execution evidence lease epoch mismatch")
    if evidence.get("lease_owner") != lease_owner:
        raise NmpHttpError("kernel execution evidence worker does not match the durable lease owner")
    guest_steps = evidence.get("guest_steps")
    if isinstance(guest_steps, bool) or not isinstance(guest_steps, int) or guest_steps < 1:
        raise NmpHttpError("kernel execution evidence must include positive guest_steps")
    dimension = evidence.get("dimension")
    if isinstance(dimension, bool) or not isinstance(dimension, int) or not 1 <= dimension <= 16:
        raise NmpHttpError("kernel execution dimension is outside the worker allowlist")
    output_kind = evidence.get("output_kind")
    output_count = evidence.get("output_count")
    expected_kind = {78: 4, 79: 3}.get(expected_program_id)
    expected_count = dimension if expected_program_id == 78 else 1
    if (
        isinstance(output_kind, bool) or not isinstance(output_kind, int)
        or output_kind != expected_kind
        or isinstance(output_count, bool) or not isinstance(output_count, int)
        or output_count != expected_count
    ):
        raise NmpHttpError("kernel execution output descriptor does not match the allowlisted program")
    for field in ("output_digest", "guest_image_digest", "guest_source_digest"):
        value = evidence.get(field)
        if not isinstance(value, str) or len(value) != 64:
            raise NmpHttpError(f"kernel execution evidence {field} must be SHA-256 hex")
        if any(char not in "0123456789abcdefABCDEF" for char in value):
            raise NmpHttpError(f"kernel execution evidence {field} must be SHA-256 hex")
    for field, expected_digest in (
        ("guest_image_digest", expected_image_digest),
        ("guest_source_digest", expected_source_digest),
    ):
        if expected_digest is not None:
            if not isinstance(expected_digest, str) or len(expected_digest) != 64:
                raise NmpHttpError(f"server-pinned {field} is invalid")
            if any(char not in "0123456789abcdefABCDEF" for char in expected_digest):
                raise NmpHttpError(f"server-pinned {field} is invalid")
            if evidence[field].lower() != expected_digest.lower():
                raise NmpHttpError(f"kernel execution {field} differs from server-pinned guest")
    if evidence["output_digest"].lower() != result_digest.lower():
        raise NmpHttpError("kernel execution output digest does not match result_digest")
    return {
        "schema": evidence["schema"],
        "packet_id": packet.packet_id,
        "function_id": packet.function_id,
        "program_id": program_id,
        "output_kind": output_kind,
        "dimension": dimension,
        "output_count": output_count,
        "output_digest": evidence["output_digest"].lower(),
        "guest_steps": guest_steps,
        "guest_image_digest": evidence["guest_image_digest"].lower(),
        "guest_source_digest": evidence["guest_source_digest"].lower(),
        "lease_epoch": lease_epoch,
        "lease_owner": lease_owner,
    }


def _native_packet(record: Any) -> NmpPacket:
    packet = NmpPacket.from_dict(record)
    if not packet.metadata.get("native_admission_required"):
        raise NmpHttpError("NMP transport requires native admission")
    if packet.admission_receipt is None:
        raise NmpHttpError("native admission receipt is required")
    validate_native_admission_receipt(packet.admission_receipt, packet)
    return packet


def _lease_from_job(job: Mapping[str, Any]) -> dict[str, Any]:
    # WaveStore returns the active lease binding on the leased job record.
    return {
        "job_id": job.get("job_id"),
        "lease_token": job.get("lease_token"),
        "lease_owner": job.get("lease_owner"),
        "lease_epoch": job.get("lease_epoch"),
        "deadline_tick": job.get("deadline_tick"),
        "state": "active",
    }


class WaveStoreNmpContextProvider:
    """Compose trusted external evidence with WaveStore's live operator/capability registry.

    Admission, preflight, ruleset, ring and cancellation snapshots remain
    explicit trusted callbacks because WaveStore does not own those registries.
    Operator identity, active lifecycle, verified capability digest, workspace,
    precision and runner ownership are resolved from the durable WaveStore.
    """

    def __init__(
        self,
        service: WaveService,
        *,
        admission_provider: ContextProvider,
        preflight_provider: ContextProvider,
        ruleset_provider: ContextProvider,
        ring_provider: ContextProvider,
        cancel_epoch_provider: ContextProvider,
        guest_binary_pin_provider: ContextProvider | None = None,
    ) -> None:
        if not hasattr(service, "store"):
            raise TypeError("service must expose its WaveStore")
        providers = {
            "admission_provider": admission_provider,
            "preflight_provider": preflight_provider,
            "ruleset_provider": ruleset_provider,
            "ring_provider": ring_provider,
            "cancel_epoch_provider": cancel_epoch_provider,
        }
        for name, provider in providers.items():
            if not callable(provider):
                raise TypeError(f"{name} must be callable")
        if guest_binary_pin_provider is not None and not callable(guest_binary_pin_provider):
            raise TypeError("guest_binary_pin_provider must be callable")
        self.service = service
        self._providers = providers
        self._guest_binary_pin_provider = guest_binary_pin_provider

    def _operator_capabilities(
        self, packet: NmpPacket, *, owner: str | None = None
    ) -> tuple[dict[str, Any], list[dict[str, Any]], int, str, dict[str, Any]]:
        store = self.service.store
        operator = store.get_operator(packet.function_id, packet.function_version)
        if not isinstance(operator, Mapping):
            raise NmpHttpError("native operator is not registered")
        if operator.get("status") != "active":
            raise NmpHttpError("native operator is not active")
        if operator.get("evidence_level") not in ("native_verified", "certified"):
            raise NmpHttpError("native operator lacks verified execution evidence")
        digest = operator.get("digest")
        precision = str(packet.numerical_policy.get("precision") or operator.get("precision") or "")
        if not precision or precision != operator.get("precision"):
            raise NmpHttpError("packet precision does not match the registered operator")
        workspace = max(int(packet.guest_words), int(operator.get("workspace") or 0))
        rows = store.dispatchable_capabilities(
            workspace=workspace,
            operator_digest=digest,
            precision=precision,
        )
        if owner is not None:
            rows = [row for row in rows if row.get("runner_id") == owner]
        if not rows:
            raise NmpHttpError("no native-verified runner capability matches this packet")
        required = {
            "required": packet.function_id,
            "verified_digest": digest,
            "workspace": workspace,
            "precision": precision,
        }
        return dict(operator), list(rows), workspace, precision, required

    def select_worker(
        self,
        packet: NmpPacket,
        owner: str,
        *,
        job: Mapping[str, Any] | None = None,
        now_tick: int | None = None,
    ) -> bool:
        """Run the full queued-state gate before a durable lease is acquired."""
        try:
            context = dict(self(
                packet=packet,
                stage="lease_candidate",
                job=job,
                lease=None,
            ))
            rows = context.get("capability")
            if not isinstance(rows, list):
                return False
            context["capability"] = [
                row for row in rows
                if isinstance(row, Mapping) and row.get("runner_id") == owner
            ]
            if not context["capability"]:
                return False
            # Reject an unsupported or receipt-mismatched NaN16 program before
            # acquiring any durable lease, not merely after reserving the job.
            _require_server_program_binding(packet, context)
            decision = packet.execution_gate(
                job=job,
                lease=None,
                now_tick=now_tick,
                **context,
            )
            return bool(decision.ok)
        except Exception:
            return False

    def __call__(
        self,
        *,
        packet: NmpPacket,
        stage: str,
        job: Mapping[str, Any] | None = None,
        lease: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        owner = None
        if stage in ("lease", "complete"):
            owner = lease.get("lease_owner") if isinstance(lease, Mapping) else None
            if not isinstance(owner, str) or not owner:
                raise NmpHttpError("active worker owner is unavailable")

        _, rows, workspace, _, required = self._operator_capabilities(
            packet, owner=owner
        )
        expected_program_id = NMP_WORKER_FUNCTION_PROGRAMS.get(packet.function_id)
        if expected_program_id is None:
            raise NmpHttpError("no supported NaN16 worker dispatch for registered function")
        evidence: dict[str, Any] = {}
        for key, provider in self._providers.items():
            try:
                evidence[key] = provider(
                    packet=packet, stage=stage, job=job, lease=lease
                )
            except Exception:
                raise NmpHttpError(f"trusted {key.removesuffix('_provider')} evidence is unavailable") from None

        admission = evidence["admission_provider"]
        preflight = evidence["preflight_provider"]
        ruleset = evidence["ruleset_provider"]
        ring = evidence["ring_provider"]
        cancel_epoch = evidence["cancel_epoch_provider"]
        if admission is None or preflight is None or ruleset is None:
            raise NmpHttpError("admission, preflight and ruleset evidence are required")
        if not isinstance(ring, Mapping):
            raise NmpHttpError("trusted ring evidence is unavailable")
        incarnation = ring.get("incarnation", ring.get("ring_incarnation"))
        epoch = ring.get("epoch", ring.get("ring_epoch"))
        if not isinstance(incarnation, str) or not incarnation:
            raise NmpHttpError("trusted ring incarnation is unavailable")
        if isinstance(epoch, bool) or not isinstance(epoch, int) or epoch < 1:
            raise NmpHttpError("trusted ring epoch is unavailable")
        if isinstance(cancel_epoch, bool) or not isinstance(cancel_epoch, int) or cancel_epoch < 0:
            raise NmpHttpError("trusted cancellation epoch is unavailable")

        result: dict[str, Any] = {
            "admission": admission,
            "preflight": preflight,
            "ruleset_snapshot": ruleset,
            "ring_incarnation": incarnation,
            "ring_epoch": epoch,
            "cancel_epoch": cancel_epoch,
            "capability": rows,
            "required_capability": required,
            "workspace": workspace,
            "expected_program_id": expected_program_id,
        }
        if owner is not None:
            result["expected_worker_owner"] = owner
        if stage == "complete" and self._guest_binary_pin_provider is not None:
            try:
                pins = self._guest_binary_pin_provider(
                    packet=packet, stage=stage, job=job, lease=lease
                )
            except Exception:
                raise NmpHttpError("trusted guest binary pins are unavailable") from None
            if not isinstance(pins, Mapping):
                raise NmpHttpError("trusted guest binary pins are unavailable")
            for key in ("expected_guest_image_digest", "expected_guest_source_digest"):
                value = pins.get(key)
                if (
                    not isinstance(value, str) or len(value) != 64
                    or any(ch not in "0123456789abcdefABCDEF" for ch in value)
                ):
                    raise NmpHttpError(f"trusted {key} must be a SHA-256 digest")
                result[key] = value.lower()
        return result


class NmpHttpAdapter:
    """NMP submit/lease/complete operations over an existing WaveService.

    The provider must read current admission, ruleset, capability and ring
    evidence from trusted server-side registries.  It must fail closed if any
    required evidence is unavailable.  The adapter never accepts those values
    from a packet's transport envelope as authoritative current state.
    """

    def __init__(self, service: WaveService,
                 context_provider: ContextProvider,
                 worker_identity_provider: WorkerIdentityProvider) -> None:
        if not hasattr(service, "submit_job") or not hasattr(service, "lease_job"):
            raise TypeError("service must implement the WaveService job/lease API")
        if not callable(context_provider):
            raise TypeError("context_provider must be callable")
        if not callable(worker_identity_provider):
            raise TypeError("worker_identity_provider must be callable")
        self.service = service
        self.context_provider = context_provider
        self.worker_identity_provider = worker_identity_provider

    def _verify_worker_identity(self, token: str, owner: str) -> None:
        try:
            verified = self.worker_identity_provider(token, owner)
        except Exception as exc:
            raise NmpHttpError("worker credential identity could not be verified") from exc
        if verified is not True:
            raise NmpHttpError("worker credential is not bound to the requested capability owner")

    def submit(self, token: str, packet_record: Mapping[str, Any],
               *, now_tick: int = 0) -> dict[str, Any]:
        packet = _native_packet(packet_record)
        if packet.state != "PREFLIGHTED":
            raise NmpHttpError("only PREFLIGHTED NMP packets may be submitted")
        gate_context = _context(self.context_provider, packet, "queue")
        _require_server_program_binding(packet, gate_context)
        queued = packet.queue(tick=now_tick, **gate_context)
        job_id = "nmp:" + packet.packet_id
        queued = replace(queued, job_id=job_id)
        operator_digest = digest_object({
            "packet_id": queued.packet_id,
            "packet": queued.to_dict(),
        })
        record = self.service.submit_job(
            token,
            job_id,
            queued.universe_id,
            operator_digest,
            queued.generation,
            {
                NMP_PAYLOAD_KEY: queued.to_dict(),
                "snapshot_id": queued.snapshot_id,
                "ruleset_snapshot_id": queued.ruleset_snapshot_id,
                "preflight_digest": queued.preflight_digest,
                "ring_incarnation": queued.ring_incarnation,
                "ring_epoch": queued.ring_epoch,
                "cancel_epoch": queued.cancel_epoch,
            },
            now_tick,
            kind=NMP_JOB_KIND,
            operator_id=queued.function_id,
            precision=str(queued.numerical_policy.get("precision", "NATIVE")),
            workspace=int(gate_context.get("workspace", 0)),
        )
        return {
            "schema": "nanrouter.nmp-submit.v1",
            "packet_id": queued.packet_id,
            "job": record,
            "packet": queued.to_dict(),
        }

    def lease(self, token: str, owner: str, *, now_tick: int,
              lease_ticks: int = 64, job_id: str | None = None,
              expected_generation: int | None = None,
              max_attempts: int = 8) -> dict[str, Any] | None:
        # Authenticate both the worker role and its concrete capability identity
        # before acquiring a durable lease. A role-only token must not let a
        # caller reserve work under another worker's owner string.
        self.service._authorize(token, ("worker",))
        self._verify_worker_identity(token, owner)
        # Providers that can preselect a runner do so before lease_job writes a
        # durable lease. A worker with no verified capability must not strand a
        # queued job in leased state.
        select_worker = getattr(self.context_provider, "select_worker", None)
        if callable(select_worker):
            self.service._authorize(token, ("worker",))
            if job_id is not None:
                candidate = self.service.store.get_job(job_id)
                candidates = [candidate] if isinstance(candidate, Mapping) else []
            else:
                candidates = self.service.store.list_jobs(state="queued", limit=1024)
            selected_id = None
            for candidate in candidates:
                if not isinstance(candidate, Mapping) or candidate.get("kind") != NMP_JOB_KIND:
                    continue
                payload = candidate.get("payload")
                record = payload.get(NMP_PAYLOAD_KEY) if isinstance(payload, Mapping) else None
                if not isinstance(record, Mapping):
                    continue
                try:
                    packet = _native_packet(record)
                except (NmpHttpError, ValueError):
                    continue
                if candidate.get("state") != "queued":
                    continue
                if select_worker(
                    packet, owner, job=candidate, now_tick=now_tick
                ):
                    selected_id = candidate.get("job_id")
                    break
            if selected_id is None:
                return None
            job_id = str(selected_id)

        job = self.service.lease_job(
            token, owner, now_tick, lease_ticks,
            expected_generation=expected_generation,
            max_attempts=max_attempts,
            job_id=job_id,
            kind=NMP_JOB_KIND,
        )
        if job is None:
            return None
        if job.get("kind") != NMP_JOB_KIND:
            raise NmpHttpError("leased job is not an NMP packet")
        payload = job.get("payload")
        if not isinstance(payload, Mapping) or not isinstance(payload.get(NMP_PAYLOAD_KEY), Mapping):
            raise NmpHttpError("leased NMP job has no canonical packet")
        packet = _native_packet(payload[NMP_PAYLOAD_KEY])
        if packet.state != QUEUED:
            raise NmpHttpError("durable NMP job does not contain a QUEUED packet")
        if packet.job_id != job.get("job_id"):
            raise NmpHttpError("packet/job identity mismatch")
        lease = _lease_from_job(job)
        gate_context = _context(
            self.context_provider, packet, "lease", job=job, lease=lease
        )
        _require_server_program_binding(packet, gate_context)
        expected_owner = gate_context.pop("expected_worker_owner", None)
        if not isinstance(expected_owner, str) or expected_owner != owner:
            raise NmpHttpError("worker owner is not bound to the current verified capability")
        executing = packet.start_execution(
            tick=now_tick, job=job, lease=lease, now_tick=now_tick, **gate_context
        )
        return {
            "schema": "nanrouter.nmp-lease.v1",
            "packet": executing.to_dict(),
            "job": job,
            "lease": {
                "owner": lease["lease_owner"],
                "epoch": lease["lease_epoch"],
                "token": lease["lease_token"],
            },
        }

    def complete(self, token: str, packet_record: Mapping[str, Any],
                 *, job_id: str, lease_token: str, lease_epoch: int,
                 result_digest: str, now_tick: int,
                 execution_evidence: Mapping[str, Any] | None = None,
                 result_generation: int | None = None,
                 lease_owner: str | None = None) -> dict[str, Any]:
        packet = _native_packet(packet_record)
        if packet.state != EXECUTING:
            raise NmpHttpError("only an EXECUTING NMP packet may complete")
        if packet.job_id != job_id or packet.lease_epoch != lease_epoch:
            raise NmpHttpError("completion does not match the packet's active lease")
        if not isinstance(result_digest, str) or len(result_digest) != 64:
            raise NmpHttpError("result_digest must be a SHA-256 hex digest")
        if any(char not in "0123456789abcdefABCDEF" for char in result_digest):
            raise NmpHttpError("result_digest must be a SHA-256 hex digest")

        # Re-evaluate the gate against the concrete current lease before the
        # durable completion write. Native packets additionally verify that
        # the receipt-derived lease binding in packet evidence is unchanged.
        self.service._authorize(token, ("worker",))
        job = self.service.store.get_job(job_id)
        if not isinstance(job, Mapping) or job.get("state") != "leased":
            raise NmpHttpError("completion job is not actively leased")
        lease = _lease_from_job(job)
        if (
            lease.get("lease_token") != lease_token
            or lease.get("lease_epoch") != lease_epoch
            or (lease_owner is not None and lease.get("lease_owner") != lease_owner)
        ):
            raise NmpHttpError("completion lease does not match the durable worker lease")
        lease_owner = lease.get("lease_owner")
        self._verify_worker_identity(token, str(lease_owner or ""))
        gate_context = _context(
            self.context_provider, packet, "complete", job=job, lease=lease
        )
        expected_program_id = _require_server_program_binding(packet, gate_context)
        # Optional trusted pins from server-side deployment context. Packet
        # metadata and worker-provided evidence are never digest authorities.
        expected_image_digest = gate_context.pop("expected_guest_image_digest", None)
        expected_source_digest = gate_context.pop("expected_guest_source_digest", None)
        native_execution = _validate_execution_evidence(
            execution_evidence, packet=packet, expected_program_id=expected_program_id,
            result_digest=result_digest, lease_epoch=lease_epoch,
            lease_owner=str(lease_owner or ""),
            expected_image_digest=expected_image_digest,
            expected_source_digest=expected_source_digest,
        )
        expected_owner = gate_context.pop("expected_worker_owner", None)
        if not isinstance(expected_owner, str) or expected_owner != lease_owner:
            raise NmpHttpError("completion worker is not bound to the current verified capability")
        decision = packet.execution_gate(
            job=job, lease=lease, now_tick=now_tick, **gate_context
        )
        if not decision.ok:
            raise NmpHttpError(f"execution gate refused completion: {decision.failure}")

        completed = packet.complete(
            result_digest,
            tick=now_tick,
            job_id=job_id,
            lease_epoch=lease_epoch,
            evidence={
                "completion_gate": decision.to_dict(),
                "native_kernel_execution": native_execution,
            },
        )
        job_record = self.service.complete_job(
            token, job_id, lease_token, lease_epoch, result_digest,
            now_tick, result_generation=result_generation,
            lease_owner=lease_owner,
        )
        return {
            "schema": "nanrouter.nmp-complete.v1",
            "packet": completed.to_dict(),
            "job": job_record,
        }


__all__ = ["NMP_JOB_KIND", "NMP_PAYLOAD_KEY", "NMP_WORKER_PROGRAM_IDS", "NmpHttpAdapter", "NmpHttpError", "WaveStoreNmpContextProvider"]
