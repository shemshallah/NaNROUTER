"""Typed wave-adapter descriptor for the NaNLMind R9 boundary.

This module validates an adapter *contract*. It deliberately performs no model
mathematics and computes no residual. The actual bounded residual is a future
NaN16-composed operation; this module only prevents an invalid or unapproved
adapter from being enabled.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ADAPTER_MODES = (
    "spectral_filter",
    "ring_readout",
    "memory_match",
    "product_residual",
)
EVIDENCE_LEVELS = (
    "declared",
    "source_written",
    "assembled",
    "native_verified",
    "ablation_passed",
    "promoted",
    "rejected",
)
ABLATIONS = (
    "void_on_off",
    "ring_on_off",
    "product_on_off",
    "real_complex",
    "phase_magnitude",
    "fold_on_off",
)


class WaveAdapterError(ValueError):
    pass


@dataclass(frozen=True)
class WaveAdapterConfig:
    adapter_id: str
    universe_id: str
    base_model_id: str
    readout_dim: int = 256
    residual_scale: float = 0.0
    mode: str = "spectral_filter"
    enabled: bool = False
    evidence_level: str = "declared"
    ablations: tuple[str, ...] = field(default_factory=tuple)
    operator_digest: str | None = None
    notes: str = ""

    def validate(self) -> None:
        for name, value in (
            ("adapter_id", self.adapter_id),
            ("universe_id", self.universe_id),
            ("base_model_id", self.base_model_id),
        ):
            if not value or len(value) > 128:
                raise WaveAdapterError(f"{name} must be 1..128 characters")
        if not 1 <= self.readout_dim <= 256:
            raise WaveAdapterError("readout_dim must be in 1..256")
        if not 0.0 <= self.residual_scale <= 1.0:
            raise WaveAdapterError("residual_scale must be in [0,1]")
        if self.mode not in ADAPTER_MODES:
            raise WaveAdapterError(f"unknown adapter mode: {self.mode}")
        if self.evidence_level not in EVIDENCE_LEVELS:
            raise WaveAdapterError(f"unknown evidence level: {self.evidence_level}")
        unknown = set(self.ablations) - set(ABLATIONS)
        if unknown:
            raise WaveAdapterError(f"unknown ablations: {sorted(unknown)}")
        if self.operator_digest is not None:
            if len(self.operator_digest) != 64 or any(
                c not in "0123456789abcdef" for c in self.operator_digest
            ):
                raise WaveAdapterError("operator_digest must be 64 lowercase hex characters")
        if self.enabled and self.evidence_level != "ablation_passed":
            raise WaveAdapterError(
                "adapter cannot be enabled before an ablation_passed evidence level"
            )
        if self.enabled and self.residual_scale == 0.0:
            raise WaveAdapterError("enabled adapter must have a nonzero residual_scale")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": "nanrouter.wave-adapter.v1",
            "adapter_id": self.adapter_id,
            "universe_id": self.universe_id,
            "base_model_id": self.base_model_id,
            "readout_dim": self.readout_dim,
            "residual_scale": self.residual_scale,
            "mode": self.mode,
            "enabled": self.enabled,
            "evidence_level": self.evidence_level,
            "ablations": list(self.ablations),
            "operator_digest": self.operator_digest,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "WaveAdapterConfig":
        if value.get("schema") != "nanrouter.wave-adapter.v1":
            raise WaveAdapterError("unsupported adapter schema")
        try:
            config = cls(
                adapter_id=value["adapter_id"],
                universe_id=value["universe_id"],
                base_model_id=value["base_model_id"],
                readout_dim=value.get("readout_dim", 256),
                residual_scale=value.get("residual_scale", 0.0),
                mode=value.get("mode", "spectral_filter"),
                enabled=value.get("enabled", False),
                evidence_level=value.get("evidence_level", "declared"),
                ablations=tuple(value.get("ablations", ())),
                operator_digest=value.get("operator_digest"),
                notes=value.get("notes", ""),
            )
        except KeyError as exc:
            raise WaveAdapterError(f"missing field: {exc.args[0]}") from exc
        config.validate()
        return config
