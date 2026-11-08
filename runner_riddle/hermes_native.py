"""Trusted HERMES receipt -> real NaN16 lease/route guest execution.

No Python implementation of nhl_open/renew/release/nannet_route exists here.
The adapter selects *only* the authenticated router lease SQL rows, loads
the pinned canonical NaN0S C VM with a NaN16 guest image, and verifies
guest output coordinates. Per-installation VMs isolate each 16-slot registry.

The durable router SQLite ledger remains authoritative on restart. A fresh
guest is reconstructed by replaying only live, verified SQL leases; old
generations remain blocked by receipt MAC + SQL revision and slot epochs.
This is not a model training engine.
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .n16t_guest import _NaN16GuestVM, N16TGuestRuntimeError


class HermesNativeError(RuntimeError):
    pass


def _pinned_file(path, digest, label):
    if not path or not digest or not re.fullmatch("[0-9a-f]{64}", digest):
        raise HermesNativeError(f"{label} requires an exact pinned SHA-256")
    file = Path(path)
    if not file.is_file():
        raise HermesNativeError(f"{label} is not a regular file")
    if hashlib.sha256(file.read_bytes()).hexdigest() != digest:
        raise HermesNativeError(f"{label} SHA-256 does not match pinned image")
    return str(file)


@dataclass
class _Installed:
    generation: int
    lease_id: int
    universe_id: int
    owner_tag: int
    node_point: int
    expires_at: int


class HermesNativeLeaseRuntime:
    """Bounded VM pool; register and route decisions happen in real NaN16."""

    def __init__(self, library_path, image_path, labels_path, *,
                 library_sha256, image_sha256, max_installations=32,
                 vm_factory=_NaN16GuestVM):
        if not 1 <= max_installations <= 256:
            raise HermesNativeError("invalid native installation bound")
        self.library = _pinned_file(library_path, library_sha256, "NaN16 library")
        self.image = _pinned_file(image_path, image_sha256, "HERMES NaN16 guest")
        self.labels = str(labels_path)
        if not Path(self.labels).is_file():
            raise HermesNativeError("HERMES NaN16 label map missing")
        labels = Path(self.labels).read_text(encoding="utf-8")
        for name in ("n16_server_exchange", "nhl_open", "nhl_renew",
                     "nhl_release", "nhl_nannet_route", "nhr_hw_admit"):
            if not re.search(r"(?m)^" + name + r"\s+\d+\s*$", labels):
                raise HermesNativeError("HERMES guest missing required native entry " + name)
        self._vm_factory = vm_factory
        self._max = max_installations
        self._lock = threading.RLock()
        self._instances = {}  # installation -> (guest VM, installed slots)
        self._closed = False

    @classmethod
    def from_env(cls):
        return cls(
            os.environ.get("NAN16_LIBRARY", ""),
            os.environ.get("HERMES_GUEST_IMAGE", ""),
            os.environ.get("HERMES_GUEST_LABELS", ""),
            library_sha256=os.environ.get("RIDDLE_HERMES_NATIVE_LIBRARY_SHA256", ""),
            image_sha256=os.environ.get("RIDDLE_HERMES_NATIVE_IMAGE_SHA256", ""),
        )

    def _invoke(self, vm, label, registers):
        try:
            vm.call(label, registers)
            status = vm.reg(3)
        except (OSError, ValueError, N16TGuestRuntimeError) as exc:
            raise HermesNativeError("HERMES NaN16 guest invocation failed: " + label) from exc
        if status != 0:
            raise HermesNativeError(f"HERMES NaN16 {label} rejected request (native code {status})")

    @staticmethod
    def _entry(row):
        return _Installed(
            row["generation"], row["lease_id"], row["universe_id"],
            row["owner_tag"], row["node_point"], row["expires_at"])

    def _open(self, vm, slot, record, now):
        self._invoke(vm, "nhl_open", {
            1: slot, 2: record.generation, 3: record.lease_id,
            4: record.universe_id, 5: record.owner_tag, 6: record.node_point,
            7: record.expires_at, 8: now,
        })

    def _release(self, vm, slot, record):
        self._invoke(vm, "nhl_release", {
            1: slot, 2: record.generation, 3: record.lease_id,
            4: record.owner_tag,
        })

    def admit_hardware(self, installation_id, hw, node_point):
        """Check authoritative bound HW identity INSIDE pinned native NaN16.

        The SQL authority has already bound the Ed25519 key to this installation;
        node_point is always the server-computed HW index + 1.
        """
        if type(hw) is not int or not 1 <= hw <= 255 or node_point != hw + 1:
            raise HermesNativeError("incorrect authenticated hardware point")
        with self._lock:
            vm, _installed = self._guest(installation_id)
            binding = 1 if hw < 5 else 2
            self._invoke(vm, "nhr_hw_admit", {1: hw, 2: binding})
            if vm.reg(1) != node_point or vm.reg(2) != (0 if hw < 5 else 1):
                raise HermesNativeError("native hardware classification differs from signed key binding")
            return {"native_hardware_admitted": True,
                    "native_hardware_entry": "nhr_hw_admit",
                    "node_point": node_point, "hw": hw}

    def _guest(self, installation_id):
        if self._closed:
            raise HermesNativeError("HERMES native runtime closed")
        if installation_id not in self._instances:
            if len(self._instances) >= self._max:
                raise HermesNativeError("HERMES native installation capacity reached")
            try:
                vm = self._vm_factory(self.library, self.image, self.labels)
            except Exception as exc:
                raise HermesNativeError("could not load pinned NaN16 HERMES guest") from exc
            self._instances[installation_id] = (vm, {})
        return self._instances[installation_id]

    def _refresh(self, installation_id, rows, now):
        vm, installed = self._guest(installation_id)
        live = {}
        for row in rows:
            slot = row["slot"]
            if slot in live or not 0 <= slot < 16:
                raise HermesNativeError("conflicting authoritative per-installation lease slots")
            if row["expires_at"] <= now:
                continue
            live[slot] = self._entry(row)

        # Discard no longer live leases before admitting reused slots.
        for slot, current in list(installed.items()):
            replacement = live.get(slot)
            if replacement and (replacement.generation == current.generation
                                and replacement.lease_id == current.lease_id):
                continue
            if current.expires_at > now:
                self._release(vm, slot, current)
            installed.pop(slot)

        for slot, record in sorted(live.items()):
            current = installed.get(slot)
            if current is None:
                self._open(vm, slot, record, now)
                installed[slot] = record
            elif current != record:
                if (
                    current.generation != record.generation
                    or current.lease_id != record.lease_id
                    or current.universe_id != record.universe_id
                    or current.owner_tag != record.owner_tag
                    or current.node_point != record.node_point
                    or record.expires_at <= current.expires_at
                ):
                    raise HermesNativeError("HERMES native slot changed without a new generation")
                self._invoke(vm, "nhl_renew", {
                    1: slot, 2: record.generation, 3: record.lease_id,
                    4: record.owner_tag, 5: record.expires_at, 6: now,
                })
                installed[slot] = record
        return vm

    def admit(self, registry, *, installation_id, receipt, head_index, now=None):
        """Reverify signed live receipt and run native guest point/owner gate."""
        now = int(time.time()) if now is None else now
        if type(now) is not int or not 1 <= now <= 0x7fffffff:
            raise HermesNativeError("invalid monotone router tick")
        if type(head_index) is not int or not 0 <= head_index <= 254:
            raise HermesNativeError("head 255 is reserved for NANNET")
        with self._lock:
            with registry._connect() as db:
                row = registry._live(db, receipt, installation_id, now)
                active = db.execute(
                    "SELECT * FROM hermes_universe_leases WHERE installation_id=? "
                    "AND revoked_at IS NULL AND expires_at>? ORDER BY slot",
                    (installation_id, now)).fetchall()
            vm = self._refresh(installation_id, active, now)
            self._invoke(vm, "nhl_nannet_route", {
                1: row["slot"], 2: row["lease_id"], 3: row["universe_id"],
                4: row["generation"], 5: row["owner_tag"], 6: head_index,
                7: now, 8: row["node_point"],  # trusted from signed DB record
            })
            if (vm.reg(1) != row["universe_id"] or vm.reg(2) != head_index
                    or vm.reg(4) != row["node_point"]
                    or vm.reg(5) != row["generation"]):
                raise HermesNativeError("NaN16 guest route coordinates mismatch authoritative lease")
            return {
                "native_guest_route_admitted": True,
                "native_guest_entry": "nhl_nannet_route",
                "native_guest_slot": row["slot"],
                "native_guest_generation": row["generation"],
                "native_guest_head_index": head_index,
                "native_guest_universe_id": row["universe_id"],
                "native_guest_node_point": row["node_point"],
            }

    def close(self):
        with self._lock:
            self._closed = True
            for vm, _ in self._instances.values():
                vm.close()
            self._instances.clear()
