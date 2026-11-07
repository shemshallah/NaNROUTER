"""Immutable identity binding for native NaN16 preflight results.

This module hashes receipt metadata only. It does not evaluate mathematics,
verify a theorem, or claim that a caller-supplied receipt is a cryptographic
attestation of guest execution.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping

from .math_objects import digest_object

RECEIPT_SCHEMA = "nanrouter.native-preflight-receipt.v1"
LEASE_BINDING_SCHEMA = "nanrouter.native-preflight-lease-binding.v1"


class NativePreflightReceiptError(ValueError):
    """A native preflight receipt is malformed, stale, or bound to other work."""


def _required_text(value: Any, name: str, *, max_length: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise NativePreflightReceiptError(f"{name} must be non-empty text")
    return value


def _digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise NativePreflightReceiptError(f"{name} must be a 256-bit hex digest")
    try:
        bytes.fromhex(value)
    except ValueError as exc:
        raise NativePreflightReceiptError(f"{name} must be hexadecimal") from exc
    return value.lower()


def _integer(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise NativePreflightReceiptError(f"{name} must be an integer >= {minimum}")
    return value


def _packet_inputs_digest(packet: Any) -> str:
    return digest_object([dict(item) for item in packet.inputs])


@dataclass(frozen=True)
class NativePreflightReceipt:
    """Content-bound record of a successful NaN16 admission guest call."""

    packet_id: str
    candidate_id: str
    snapshot_id: str
    base_generation: int
    generation: int
    function_id: str
    function_version: int
    inputs_digest: str
    ruleset_snapshot_id: str
    rule_epoch: int
    rule_digest: str
    capability_set_digest: str
    capability_epoch: int
    output_generation: int
    output_descriptor_digest: str
    guest_source_digest: str
    guest_image_digest: str
    guest_status: int = 0
    result: str = "VALID"
    receipt_digest: str = ""

    def __post_init__(self) -> None:
        for name in ("packet_id", "candidate_id", "snapshot_id", "function_id",
                     "ruleset_snapshot_id"):
            _required_text(getattr(self, name), name)
        for name in ("inputs_digest", "rule_digest", "capability_set_digest",
                     "output_descriptor_digest", "guest_source_digest",
                     "guest_image_digest"):
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        for name in ("base_generation", "generation", "rule_epoch",
                     "capability_epoch", "output_generation", "function_version"):
            _integer(getattr(self, name), name, minimum=1 if name in {
                "rule_epoch", "function_version"
            } else 0)
        _integer(self.guest_status, "guest_status")
        if self.guest_status != 0 or self.result != "VALID":
            raise NativePreflightReceiptError("only a zero-status VALID guest result can issue a receipt")
        if self.output_generation != self.generation + 1:
            raise NativePreflightReceiptError("output_generation must be exactly input generation + 1")
        expected = digest_object(self._payload())
        if self.receipt_digest:
            supplied = _digest(self.receipt_digest, "receipt_digest")
            if supplied != expected:
                raise NativePreflightReceiptError("receipt_digest does not match receipt contents")
        else:
            object.__setattr__(self, "receipt_digest", expected)

    def _payload(self) -> dict[str, Any]:
        return {
            "schema": RECEIPT_SCHEMA,
            "packet_id": self.packet_id,
            "candidate_id": self.candidate_id,
            "snapshot_id": self.snapshot_id,
            "base_generation": self.base_generation,
            "generation": self.generation,
            "function_id": self.function_id,
            "function_version": self.function_version,
            "inputs_digest": self.inputs_digest,
            "ruleset_snapshot_id": self.ruleset_snapshot_id,
            "rule_epoch": self.rule_epoch,
            "rule_digest": self.rule_digest,
            "capability_set_digest": self.capability_set_digest,
            "capability_epoch": self.capability_epoch,
            "output_generation": self.output_generation,
            "output_descriptor_digest": self.output_descriptor_digest,
            "guest_source_digest": self.guest_source_digest,
            "guest_image_digest": self.guest_image_digest,
            "guest_status": self.guest_status,
            "result": self.result,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "receipt_digest": self.receipt_digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "NativePreflightReceipt":
        if not isinstance(value, Mapping) or value.get("schema") != RECEIPT_SCHEMA:
            raise NativePreflightReceiptError("unknown native preflight receipt schema")
        fields = dict(value)
        fields.pop("schema", None)
        return cls(**fields)

    @classmethod
    def from_guest_result(
        cls,
        packet: Any,
        guest_result: Any,
        *,
        guest_source_digest: str,
        guest_image_digest: str,
    ) -> "NativePreflightReceipt":
        """Bind a normalized Android/NaN16 decision to one immutable NMP packet.

        guest_result must expose: status, rule_epoch, rule_digest_words, and
        output_descriptor. This function hashes identity/evidence fields only;
        all semantic admission checks must already have run in the NaN16 guest.
        """
        def field(name: str) -> Any:
            return guest_result.get(name) if isinstance(guest_result, Mapping) else getattr(
                guest_result, name, None
            )

        status = _integer(field("status"), "guest status")
        if status != 0:
            raise NativePreflightReceiptError("denied guest result cannot issue a VALID receipt")
        words = field("rule_digest_words")
        if not isinstance(words, (list, tuple)) or len(words) != 8:
            raise NativePreflightReceiptError("guest must return all eight 256-bit rule digest words")
        try:
            rule_digest = "".join(f"{_integer(word, 'rule digest word') & 0xffffffff:08x}" for word in words)
        except (TypeError, ValueError) as exc:
            raise NativePreflightReceiptError("malformed rule digest words") from exc
        output = field("output_descriptor")
        if not isinstance(output, (list, tuple)) or len(output) != 8:
            raise NativePreflightReceiptError("guest must return the complete 8-word output descriptor")
        output_words = []
        for word in output:
            if isinstance(word, bool) or not isinstance(word, int):
                raise NativePreflightReceiptError("output descriptor words must be integers")
            output_words.append(word & 0xffffffff)
        if not packet.ruleset_snapshot_id:
            raise NativePreflightReceiptError("packet must bind a ruleset snapshot before native preflight")
        return cls(
            packet_id=packet.packet_id,
            candidate_id=packet.candidate_id,
            snapshot_id=packet.snapshot_id,
            base_generation=packet.base_generation,
            generation=packet.generation,
            function_id=packet.function_id,
            function_version=packet.function_version,
            inputs_digest=_packet_inputs_digest(packet),
            ruleset_snapshot_id=packet.ruleset_snapshot_id,
            rule_epoch=_integer(field("rule_epoch"), "rule_epoch", minimum=1),
            rule_digest=rule_digest,
            capability_set_digest=packet.capability_set_digest,
            capability_epoch=packet.capability_epoch,
            output_generation=packet.generation + 1,
            output_descriptor_digest=digest_object(output_words),
            guest_source_digest=guest_source_digest,
            guest_image_digest=guest_image_digest,
            guest_status=status,
        )

    def verify_packet(self, packet: Any) -> None:
        expected = {
            "packet_id": packet.packet_id,
            "candidate_id": packet.candidate_id,
            "snapshot_id": packet.snapshot_id,
            "base_generation": packet.base_generation,
            "generation": packet.generation,
            "function_id": packet.function_id,
            "function_version": packet.function_version,
            "inputs_digest": _packet_inputs_digest(packet),
            "ruleset_snapshot_id": packet.ruleset_snapshot_id,
            "capability_set_digest": packet.capability_set_digest,
            "capability_epoch": packet.capability_epoch,
        }
        for name, value in expected.items():
            if getattr(self, name) != value:
                raise NativePreflightReceiptError(f"receipt {name} no longer matches the packet")
        if self.output_generation != packet.generation + 1:
            raise NativePreflightReceiptError("receipt output generation is stale")


@dataclass(frozen=True)
class NativePreflightLeaseBinding:
    """Bind one native receipt to one concrete worker lease and ring epoch."""

    receipt_digest: str
    packet_id: str
    candidate_id: str
    job_id: str
    lease_epoch: int
    lease_owner: str
    lease_token_digest: str
    ring_incarnation: str
    ring_epoch: int
    output_generation: int
    binding_digest: str = ""

    def __post_init__(self) -> None:
        for name in ("packet_id", "candidate_id", "job_id", "lease_owner", "ring_incarnation"):
            _required_text(getattr(self, name), name)
        for name in ("receipt_digest", "lease_token_digest"):
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        for name in ("lease_epoch", "ring_epoch", "output_generation"):
            _integer(getattr(self, name), name, minimum=1)
        expected = digest_object(self._payload())
        if self.binding_digest:
            if _digest(self.binding_digest, "binding_digest") != expected:
                raise NativePreflightReceiptError("binding_digest does not match binding contents")
        else:
            object.__setattr__(self, "binding_digest", expected)

    def _payload(self) -> dict[str, Any]:
        return {
            "schema": LEASE_BINDING_SCHEMA,
            "receipt_digest": self.receipt_digest,
            "packet_id": self.packet_id,
            "candidate_id": self.candidate_id,
            "job_id": self.job_id,
            "lease_epoch": self.lease_epoch,
            "lease_owner": self.lease_owner,
            "lease_token_digest": self.lease_token_digest,
            "ring_incarnation": self.ring_incarnation,
            "ring_epoch": self.ring_epoch,
            "output_generation": self.output_generation,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "binding_digest": self.binding_digest}

    @classmethod
    def from_live_lease(
        cls,
        packet: Any,
        receipt: NativePreflightReceipt,
        job: Mapping[str, Any],
        lease: Mapping[str, Any],
        ring_snapshot: Mapping[str, Any],
        *,
        ring_incarnation: str,
    ) -> "NativePreflightLeaseBinding":
        receipt.verify_packet(packet)
        if packet.state not in ("QUEUED", "EXECUTING"):
            raise NativePreflightReceiptError("packet must be queued before lease binding")
        if not isinstance(job, Mapping) or not isinstance(lease, Mapping) or not isinstance(ring_snapshot, Mapping):
            raise NativePreflightReceiptError("job, lease, and ring snapshot must be mappings")
        job_id = _required_text(job.get("job_id") or packet.job_id, "job_id")
        if packet.job_id is not None and packet.job_id != job_id:
            raise NativePreflightReceiptError("job does not match packet")
        lease_job_id = lease.get("job_id")
        if lease_job_id is not None and lease_job_id != job_id:
            raise NativePreflightReceiptError("lease belongs to another job")
        if str(lease.get("state", "")).lower() != "active":
            raise NativePreflightReceiptError("worker lease is not active")
        lease_epoch = _integer(lease.get("lease_epoch"), "lease_epoch", minimum=1)
        lease_owner = _required_text(lease.get("lease_owner") or lease.get("owner"), "lease_owner")
        lease_token = _required_text(lease.get("lease_token"), "lease_token")
        ring_epoch = _integer(ring_snapshot.get("epoch"), "ring_epoch", minimum=1)
        if ring_snapshot.get("started") is not True or ring_snapshot.get("health") != "green":
            raise NativePreflightReceiptError("runner ring is not started and healthy")
        jahs = ring_snapshot.get("jahs")
        if not isinstance(jahs, Mapping) or jahs.get("seal") != "JAHS-1":
            raise NativePreflightReceiptError("runner ring handoff seal is missing")
        if packet.ring_epoch is not None and packet.ring_epoch != ring_epoch:
            raise NativePreflightReceiptError("packet ring epoch is stale")
        if packet.ring_incarnation is not None and packet.ring_incarnation != ring_incarnation:
            raise NativePreflightReceiptError("packet ring incarnation is stale")
        active_aliases = {
            ring_snapshot.get("active_slot_id"),
            ring_snapshot.get("active_alias"),
        }
        if lease_owner not in active_aliases:
            raise NativePreflightReceiptError("lease owner is not the active ring slot or alias")
        return cls(
            receipt_digest=receipt.receipt_digest,
            packet_id=packet.packet_id,
            candidate_id=packet.candidate_id,
            job_id=job_id,
            lease_epoch=lease_epoch,
            lease_owner=lease_owner,
            lease_token_digest=sha256(lease_token.encode("utf-8")).hexdigest(),
            ring_incarnation=_required_text(ring_incarnation, "ring_incarnation"),
            ring_epoch=ring_epoch,
            output_generation=receipt.output_generation,
        )


__all__ = [
    "LEASE_BINDING_SCHEMA",
    "RECEIPT_SCHEMA",
    "NativePreflightLeaseBinding",
    "NativePreflightReceipt",
    "NativePreflightReceiptError",
]
