"""Signed Koyeb volume registry owned by the NaNROUTER control plane.

Logical NaN addresses are stable identities. Provider IDs and mount roots are
deployment bindings and must never be used as substitutes for those identities.
This module only verifies/readies a supplied registry; it never mounts, formats,
moves, or writes to provider volumes.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from pathlib import Path
from typing import Any

class VolumeRegistryError(ValueError):
    pass

CANONICAL = {
    "BS0": ("0x7FF14E1100E8F17F", "bs0db.sqlite3"),
    "MC0": ("0x7FF14E1200D7F17F", "mc0db.sqlite3"),
    "SC0": ("0x7FF14E1300C2F17F", "sc0db.sqlite3"),
    "GM0": ("0x7FF14E1400A9F17F", "gm0db.sqlite3"),
}
_TIERS = frozenset(CANONICAL)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _signature(value: Any, key: bytes) -> str:
    return hmac.new(key, _canonical(value), hashlib.sha256).hexdigest()


def _crc8_atm(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def logical_address(tier: str, shard: int) -> str:
    if tier not in CANONICAL or not isinstance(shard, int) or not 0 <= shard <= 255:
        raise VolumeRegistryError("unknown tier or shard outside 0..255")
    tier_code = {"BS0": 1, "MC0": 2, "SC0": 3, "GM0": 4}[tier]
    prefix = bytes((0x4E, 0x10 | tier_code, shard))
    payload = (int.from_bytes(prefix, "big") << 8) | _crc8_atm(prefix)
    return f"0x7FF1{payload:08X}F17F"


class VolumeRegistry:
    """Read-only verifier for a generation-chained, HMAC-authenticated registry."""

    def __init__(self, document: dict[str, Any], key: bytes):
        if len(key) < 32:
            raise VolumeRegistryError("volume registry key must be at least 32 bytes")
        self.document = document
        self.key = key
        self.verify()

    @classmethod
    def load(cls, path: str | Path, key: bytes) -> "VolumeRegistry":
        try:
            document = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise VolumeRegistryError("volume registry is unavailable or invalid JSON") from exc
        if not isinstance(document, dict):
            raise VolumeRegistryError("volume registry must be a JSON object")
        return cls(document, key)

    @classmethod
    def build_signed(cls, *, network_id: str, generation: int,
                     previous_digest: str | None, volumes: list[dict[str, Any]],
                     key: bytes) -> "VolumeRegistry":
        core = {
            "schema": "nanrouter.volume-registry.v1",
            "network_id": network_id,
            "generation": generation,
            "previous_digest": previous_digest,
            "volumes": volumes,
        }
        doc = {**core, "registry_digest": _digest(core), "signature": _signature(core, key)}
        return cls(doc, key)

    def verify(self) -> None:
        doc = self.document
        if doc.get("schema") != "nanrouter.volume-registry.v1":
            raise VolumeRegistryError("unsupported volume registry schema")
        if not isinstance(doc.get("network_id"), str) or not doc["network_id"]:
            raise VolumeRegistryError("network_id is required")
        if not isinstance(doc.get("generation"), int) or doc["generation"] < 1:
            raise VolumeRegistryError("registry generation must be positive")
        previous = doc.get("previous_digest")
        if previous is not None and not _HEX64.fullmatch(str(previous)):
            raise VolumeRegistryError("previous_digest must be SHA-256 hex or null")
        core = {k: v for k, v in doc.items() if k not in ("registry_digest", "signature")}
        if not hmac.compare_digest(str(doc.get("registry_digest", "")), _digest(core)):
            raise VolumeRegistryError("volume registry digest mismatch")
        if not hmac.compare_digest(str(doc.get("signature", "")), _signature(core, self.key)):
            raise VolumeRegistryError("volume registry signature mismatch")
        volumes = doc.get("volumes")
        if not isinstance(volumes, list) or len(volumes) < len(_TIERS):
            raise VolumeRegistryError("registry must include all four canonical tier volumes")

        seen_addresses: set[str] = set()
        seen_provider_ids: set[str] = set()
        seen_mounts: set[str] = set()
        canonical_tiers: set[str] = set()
        for item in volumes:
            if not isinstance(item, dict):
                raise VolumeRegistryError("each volume entry must be an object")
            tier = item.get("tier")
            if tier not in _TIERS:
                raise VolumeRegistryError("unknown volume tier")
            shard = item.get("shard")
            if not isinstance(shard, int) or not 0 <= shard <= 255:
                raise VolumeRegistryError("shard must be in 0..255")
            _, expected_db = CANONICAL[tier]
            address = item.get("logical_address")
            if address != logical_address(tier, shard):
                raise VolumeRegistryError("logical address does not match tier/shard identity or CRC")
            if shard == 0:
                canonical_tiers.add(tier)
            provider = item.get("provider")
            provider_id = item.get("provider_volume_id")
            if provider != "koyeb" or not isinstance(provider_id, str) or not provider_id.strip():
                raise VolumeRegistryError("Koyeb provider and real provider_volume_id are required")
            if provider_id.startswith("<") or "placeholder" in provider_id.lower():
                raise VolumeRegistryError("placeholder provider volume IDs are forbidden")
            mount_root = item.get("mount_root")
            if (not isinstance(mount_root, str) or not mount_root.startswith("/")
                    or mount_root == "/" or "\\\\" in mount_root
                    or any(part in ("", ".", "..") for part in mount_root.split("/")[1:])):
                raise VolumeRegistryError("mount_root must be a normalized absolute Koyeb mount path")
            if item.get("database_file") != expected_db:
                raise VolumeRegistryError("database filename does not match its tier")
            if item.get("health") not in ("green", "degraded", "unavailable", "unknown"):
                raise VolumeRegistryError("invalid volume health state")
            if not isinstance(item.get("mount_verified"), bool):
                raise VolumeRegistryError("mount_verified must be boolean")
            if not isinstance(item.get("observed_at_tick"), int) or item["observed_at_tick"] < 0:
                raise VolumeRegistryError("observed_at_tick must be nonnegative")
            if not isinstance(item.get("generation"), int) or not 1 <= item["generation"] <= doc["generation"]:
                raise VolumeRegistryError("volume generation must be positive and no newer than registry")
            if not isinstance(item.get("region"), str) or not item["region"]:
                raise VolumeRegistryError("Koyeb region is required")
            for field, value in (("logical_address", address), ("provider_volume_id", provider_id),
                                 ("mount_root", mount_root)):
                if value in (seen_addresses if field == "logical_address" else
                             seen_provider_ids if field == "provider_volume_id" else seen_mounts):
                    raise VolumeRegistryError(f"duplicate {field}")
            seen_addresses.add(address)
            seen_provider_ids.add(provider_id)
            seen_mounts.add(mount_root)
        if canonical_tiers != _TIERS:
            raise VolumeRegistryError("one shard-0 canonical volume is required for every tier")

    @property
    def health(self) -> str:
        canonical = [v for v in self.document["volumes"] if v["shard"] == 0]
        if len(canonical) != 4:
            return "degraded"
        if all(v["health"] == "green" and v["mount_verified"] for v in canonical):
            return "green"
        if any(v["health"] == "unavailable" for v in canonical):
            return "unavailable"
        return "degraded"

    def summary(self) -> dict[str, Any]:
        return {
            "schema": self.document["schema"],
            "network_id": self.document["network_id"],
            "generation": self.document["generation"],
            "registry_digest": self.document["registry_digest"],
            "health": self.health,
            "canonical_tiers": {
                tier: {
                    "logical_address": address,
                    "database_file": database_file,
                    "health": next(v["health"] for v in self.document["volumes"]
                                   if v["tier"] == tier and v["shard"] == 0),
                    "mount_verified": next(v["mount_verified"] for v in self.document["volumes"]
                                           if v["tier"] == tier and v["shard"] == 0),
                }
                for tier, (address, database_file) in CANONICAL.items()
            },
        }

    def public_records(self) -> list[dict[str, Any]]:
        """Return operational fields without exposing secrets (the signature key is never stored)."""
        return [dict(item) for item in self.document["volumes"]]
