"""One logical NANNET node per universe.

The NANNET node is the universe's single network endpoint/port. It is not a
head and does not compute wave mathematics. This module enforces the binding
rule; actual transport and authentication remain in the router/NANNET layer.
"""
from __future__ import annotations

from dataclasses import dataclass


class NannetNodeError(ValueError):
    pass


@dataclass(frozen=True)
class NannetNodeBinding:
    universe_id: str
    node_id: str
    node_point: int
    public_key_fingerprint: str
    generation: int = 0
    status: str = "declared"
    route: str = ""

    def validate(self) -> None:
        for name, value in (
            ("universe_id", self.universe_id),
            ("node_id", self.node_id),
        ):
            if not value or len(value) > 128:
                raise NannetNodeError(f"{name} must be 1..128 characters")
        if not 1 <= self.node_point <= 256:
            raise NannetNodeError("node_point must be in 1..256")
        if len(self.public_key_fingerprint) != 64 or any(
            c not in "0123456789abcdef" for c in self.public_key_fingerprint
        ):
            raise NannetNodeError(
                "public_key_fingerprint must be 64 lowercase hex characters"
            )
        if self.generation < 0:
            raise NannetNodeError("generation must be nonnegative")
        if self.status not in ("declared", "active", "degraded", "revoked"):
            raise NannetNodeError(f"unknown status: {self.status}")
        if self.status == "revoked" and self.route:
            raise NannetNodeError("revoked node must not advertise a route")

    def to_dict(self) -> dict:
        self.validate()
        return {
            "universe_id": self.universe_id,
            "node_id": self.node_id,
            "node_point": self.node_point,
            "public_key_fingerprint": self.public_key_fingerprint,
            "generation": self.generation,
            "status": self.status,
            "route": self.route,
        }


class NannetNodeRegistry:
    """In-memory binding registry enforcing one NANNET node per universe."""

    def __init__(self) -> None:
        self._by_universe: dict[str, NannetNodeBinding] = {}
        self._by_node: dict[str, str] = {}
        self._by_point: dict[int, str] = {}

    def register(self, binding: NannetNodeBinding) -> None:
        binding.validate()
        existing = self._by_universe.get(binding.universe_id)
        if existing is not None:
            if existing == binding:
                return
            raise NannetNodeError(
                f"universe {binding.universe_id} already has a NANNET node"
            )
        if binding.node_id in self._by_node:
            raise NannetNodeError(f"node_id {binding.node_id} is already bound")
        if binding.node_point in self._by_point:
            raise NannetNodeError(
                f"node_point {binding.node_point} is already bound"
            )
        self._by_universe[binding.universe_id] = binding
        self._by_node[binding.node_id] = binding.universe_id
        self._by_point[binding.node_point] = binding.node_id

    def get(self, universe_id: str) -> NannetNodeBinding | None:
        return self._by_universe.get(universe_id)

    def revoke(self, universe_id: str, *, generation: int) -> NannetNodeBinding:
        current = self._by_universe.get(universe_id)
        if current is None:
            raise NannetNodeError(f"universe {universe_id} has no NANNET node")
        if generation <= current.generation:
            raise NannetNodeError("revocation generation must advance")
        revoked = NannetNodeBinding(
            universe_id=current.universe_id,
            node_id=current.node_id,
            node_point=current.node_point,
            public_key_fingerprint=current.public_key_fingerprint,
            generation=generation,
            status="revoked",
            route="",
        )
        self._by_universe[universe_id] = revoked
        self._by_node.pop(current.node_id, None)
        self._by_point.pop(current.node_point, None)
        return revoked

    def count(self) -> int:
        return len(self._by_universe)
