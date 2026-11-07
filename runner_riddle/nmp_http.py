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
    NmpPacket,
    validate_native_admission_receipt,
)
from .wave_service import WaveService

NMP_JOB_KIND = "nmp"
NMP_PAYLOAD_KEY = "nmp_packet"


class NmpHttpError(ValueError):
    """A rejected NMP transport operation."""


ContextProvider = Callable[..., Mapping[str, Any]]


def _context(provider: ContextProvider, packet: NmpPacket, stage: str,
             *, job: Mapping[str, Any] | None = None,
             lease: Mapping[str, Any] | None = None) -> dict[str, Any]:
    value = provider(packet=packet, stage=stage, job=job, lease=lease)
    if not isinstance(value, Mapping):
        raise NmpHttpError("server admission context is unavailable")
    result = dict(value)
    forbidden = {"job", "lease", "tick", "gate"}
    if forbidden.intersection(result):
        raise NmpHttpError("context provider returned reserved gate fields")
    return result


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
                 context_provider: ContextProvider) -> None:
        if not hasattr(service, "submit_job") or not hasattr(service, "lease_job"):
            raise TypeError("service must implement the WaveService job/lease API")
        if not callable(context_provider):
            raise TypeError("context_provider must be callable")
        self.service = service
        self.context_provider = context_provider

    def submit(self, token: str, packet_record: Mapping[str, Any],
               *, now_tick: int = 0) -> dict[str, Any]:
        packet = _native_packet(packet_record)
        if packet.state != "PREFLIGHTED":
            raise NmpHttpError("only PREFLIGHTED NMP packets may be submitted")
        gate_context = _context(self.context_provider, packet, "queue")
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
            {NMP_PAYLOAD_KEY: queued.to_dict()},
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
        if packet.job_id != job.get("job_id"):
            raise NmpHttpError("packet/job identity mismatch")
        lease = _lease_from_job(job)
        gate_context = _context(
            self.context_provider, packet, "lease", job=job, lease=lease
        )
        executing = packet.start_execution(
            tick=now_tick, job=job, lease=lease, **gate_context
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
        lease = {
            "job_id": job_id,
            "lease_token": lease_token,
            "lease_owner": lease_owner,
            "lease_epoch": lease_epoch,
            "state": "active",
        }
        job = {
            "job_id": job_id,
            "state": "leased",
            "lease_token": lease_token,
            "lease_owner": lease_owner,
            "lease_epoch": lease_epoch,
        }
        gate_context = _context(
            self.context_provider, packet, "complete", job=job, lease=lease
        )
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
            evidence={"completion_gate": decision.to_dict()},
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


__all__ = ["NMP_JOB_KIND", "NMP_PAYLOAD_KEY", "NmpHttpAdapter", "NmpHttpError"]
