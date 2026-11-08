"""Typed native execution evidence beyond a bare result digest.

This is host-control evidence. It records what the trusted executor claims to
have run and which bounds it reports; it does not perform mathematics, verify a
numeric result, or grant validity/truth.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Mapping

SCHEMA = "nanrouter.execution-evidence.v1"
NATIVE_SCHEMA = "nanrouter.native-kernel-execution.v1"
_SECRET_KEYS = frozenset({
    "token", "lease_token", "worker_token", "submit_token", "password",
    "secret", "credential", "api_key", "authorization",
})


class ExecutionEvidenceError(ValueError):
    """Malformed or inconsistent execution evidence."""


def _text(value: Any, name: str, *, maximum: int = 512,
          allow_empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum or (
        not allow_empty and not value
    ):
        raise ExecutionEvidenceError(f"{name} must be a string <= {maximum}")
    return value


def _digest(value: Any, name: str, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or len(value) != 64 or any(
        ch not in "0123456789abcdef" for ch in value
    ):
        raise ExecutionEvidenceError(f"{name} must be lowercase SHA-256 hex")
    return value


def _int(value: Any, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ExecutionEvidenceError(f"{name} must be an integer >= {minimum}")
    return value


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ExecutionEvidenceError("value is not canonical JSON") from exc


def _digest_object(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _reject_secret_keys(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in _SECRET_KEYS:
                raise ExecutionEvidenceError("execution evidence contains a secret key")
            _reject_secret_keys(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_secret_keys(item)


@dataclass(frozen=True)
class ExecutionEvidence:
    packet_id: str
    job_id: str
    kernel_id: str
    runner_id: str
    result_digest: str
    precision: str = ""
    output_leaf_id: str | None = None
    output_digest: str | None = None
    residual: int | None = None
    error_bound: int | None = None
    saturation: int | None = None
    iterations: int | None = None
    guest_source_digest: str | None = None
    guest_image_digest: str | None = None
    lease_epoch: int | None = None
    ring_incarnation: str | None = None
    ring_epoch: int | None = None
    jahs: str | None = None
    numerical_policy: Mapping[str, Any] = field(default_factory=dict)
    provenance: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("packet_id", "job_id", "kernel_id", "runner_id"):
            object.__setattr__(
                self, name, _text(getattr(self, name), name, allow_empty=False)
            )
        object.__setattr__(
            self, "result_digest", _digest(self.result_digest, "result_digest")
        )
        object.__setattr__(self, "precision", _text(
            self.precision, "precision", maximum=64, allow_empty=True,
        ))
        object.__setattr__(self, "output_leaf_id", None if self.output_leaf_id is None else _text(
            self.output_leaf_id, "output_leaf_id",
        ))
        for name in ("output_digest", "guest_source_digest", "guest_image_digest"):
            object.__setattr__(
                self, name, _digest(getattr(self, name), name, allow_none=True)
            )
        for name in ("residual", "error_bound", "saturation", "iterations"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _int(value, name))
        for name in ("lease_epoch", "ring_epoch"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _int(value, name, minimum=1))
        object.__setattr__(self, "ring_incarnation", None if self.ring_incarnation is None else _text(
            self.ring_incarnation, "ring_incarnation",
        ))
        object.__setattr__(self, "jahs", None if self.jahs is None else _text(
            self.jahs, "jahs", maximum=64,
        ))
        object.__setattr__(self, "numerical_policy", dict(self.numerical_policy or {}))
        object.__setattr__(self, "provenance", dict(self.provenance or {}))
        _reject_secret_keys(self.numerical_policy)
        _reject_secret_keys(self.provenance)

    @classmethod
    def from_native_mapping(cls, value: Mapping[str, Any]) -> "ExecutionEvidence":
        if not isinstance(value, Mapping):
            raise ExecutionEvidenceError("native evidence must be an object")
        if value.get("schema") != NATIVE_SCHEMA:
            raise ExecutionEvidenceError("unsupported native evidence schema")
        return cls(
            packet_id=value.get("packet_id"),
            job_id=value.get("job_id"),
            kernel_id=value.get("function_id", value.get("kernel_id")),
            runner_id=value.get("lease_owner", value.get("runner_id")),
            result_digest=value.get("result_digest", value.get("output_digest")),
            precision=value.get("precision", ""),
            output_leaf_id=value.get("output_leaf_id"),
            output_digest=value.get("output_digest"),
            residual=value.get("residual"),
            error_bound=value.get("error_bound"),
            saturation=value.get("saturation"),
            iterations=value.get("iterations", value.get("guest_steps")),
            guest_source_digest=value.get("guest_source_digest"),
            guest_image_digest=value.get("guest_image_digest"),
            lease_epoch=value.get("lease_epoch"),
            ring_incarnation=value.get("ring_incarnation"),
            ring_epoch=value.get("ring_epoch"),
            jahs=value.get("jahs"),
            numerical_policy=value.get("numerical_policy", {}),
            provenance={
                "program_id": value.get("program_id"),
                "output_kind": value.get("output_kind"),
                "dimension": value.get("dimension"),
                "output_count": value.get("output_count"),
            },
        )

    def validate_binding(self, *, packet_id: str | None = None,
                         job_id: str | None = None,
                         kernel_id: str | None = None,
                         lease_epoch: int | None = None) -> None:
        for name, expected in (
            ("packet_id", packet_id), ("job_id", job_id),
            ("kernel_id", kernel_id), ("lease_epoch", lease_epoch),
        ):
            if expected is not None and getattr(self, name) != expected:
                raise ExecutionEvidenceError(
                    f"{name} does not match the execution binding"
                )

    def digest(self) -> str:
        return _digest_object(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "packet_id": self.packet_id,
            "job_id": self.job_id,
            "kernel_id": self.kernel_id,
            "runner_id": self.runner_id,
            "precision": self.precision,
            "result_digest": self.result_digest,
            "output_leaf_id": self.output_leaf_id,
            "output_digest": self.output_digest,
            "residual": self.residual,
            "error_bound": self.error_bound,
            "saturation": self.saturation,
            "iterations": self.iterations,
            "guest_source_digest": self.guest_source_digest,
            "guest_image_digest": self.guest_image_digest,
            "lease_epoch": self.lease_epoch,
            "ring_incarnation": self.ring_incarnation,
            "ring_epoch": self.ring_epoch,
            "jahs": self.jahs,
            "numerical_policy": dict(self.numerical_policy),
            "provenance": dict(self.provenance),
        }


__all__ = ["ExecutionEvidence", "ExecutionEvidenceError", "NATIVE_SCHEMA", "SCHEMA"]
