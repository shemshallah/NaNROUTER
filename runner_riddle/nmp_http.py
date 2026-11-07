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
        try:
            int(value, 16)
        except ValueError as exc:
            raise NmpHttpError(f"kernel execution evidence {field} must be SHA-256 hex") from exc
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
        try:
            int(result_digest, 16)
        except ValueError as exc:
            raise NmpHttpError("result_digest must be a SHA-256 hex digest") from exc

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
        native_execution = _validate_execution_evidence(
            execution_evidence, packet=packet, expected_program_id=expected_program_id,
            result_digest=result_digest, lease_epoch=lease_epoch,
            lease_owner=str(lease_owner or ""),
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


__all__ = ["NMP_JOB_KIND", "NMP_PAYLOAD_KEY", "NMP_WORKER_PROGRAM_IDS", "NmpHttpAdapter", "NmpHttpError"]
