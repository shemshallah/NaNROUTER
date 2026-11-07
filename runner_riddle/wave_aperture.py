"""Typed aperture descriptor for the R5 wave subsystem.

The descriptor names the role of a 256x256 (or 255x255 head-only) aperture and
selects the required decomposition family. It does not compute an SVD or
eigendecomposition; those are NaN16 kernels.
"""
from __future__ import annotations

from dataclasses import dataclass


class ApertureError(ValueError):
    pass


ROLES = ("state", "filter", "coupling", "scattering", "memory", "covariance")
STATUSES = ("specified", "source_written", "native_verified", "promoted", "rejected")


@dataclass(frozen=True)
class ApertureDescriptor:
    aperture_id: str
    universe_id: str
    rows: int = 256
    cols: int = 256
    role: str = "filter"
    precision: str = "float32"
    hermitian: bool = False
    centrosymmetric: bool = False
    rank: int | None = None
    operator_digest: str | None = None
    status: str = "specified"

    def validate(self) -> None:
        for name, value in (
            ("aperture_id", self.aperture_id),
            ("universe_id", self.universe_id),
        ):
            if not value or len(value) > 128:
                raise ApertureError(f"{name} must be 1..128 characters")
        if self.rows not in (255, 256) or self.cols not in (255, 256):
            raise ApertureError("aperture dimensions must be 255 or 256")
        if self.role not in ROLES:
            raise ApertureError(f"unknown aperture role: {self.role}")
        if self.precision not in ("float32", "complex-float32", "q16.16"):
            raise ApertureError(f"unsupported aperture precision: {self.precision}")
        if self.rank is not None and not 0 <= self.rank <= min(self.rows, self.cols):
            raise ApertureError("rank must be within the aperture dimensions")
        if self.operator_digest is not None:
            if len(self.operator_digest) != 64 or any(
                c not in "0123456789abcdef" for c in self.operator_digest
            ):
                raise ApertureError("operator_digest must be 64 lowercase hex characters")
        if self.status not in STATUSES:
            raise ApertureError(f"unknown status: {self.status}")

    def decomposition(self) -> str:
        """Return the required decomposition family for this role."""
        self.validate()
        if self.role in ("filter", "memory", "state") and self.hermitian:
            return "eigendecomposition"
        if self.role == "covariance":
            return "eigendecomposition"
        if self.role in ("filter", "memory", "state"):
            return "svd"
        if self.role == "scattering":
            return "svd"
        if self.role == "coupling":
            return "eigendecomposition" if self.hermitian else "schur_or_svd"
        raise ApertureError(f"no decomposition for role {self.role}")

    def to_dict(self) -> dict:
        self.validate()
        return {
            "schema": "nanrouter.wave-aperture.v1",
            "aperture_id": self.aperture_id,
            "universe_id": self.universe_id,
            "rows": self.rows,
            "cols": self.cols,
            "role": self.role,
            "precision": self.precision,
            "hermitian": self.hermitian,
            "centrosymmetric": self.centrosymmetric,
            "rank": self.rank,
            "operator_digest": self.operator_digest,
            "status": self.status,
            "decomposition": self.decomposition(),
        }
