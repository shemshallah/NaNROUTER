"""Embedded six-slot runner-ring node inside the single Koyeb portal service.

The portal is the only Koyeb service.  It owns the atomic runner-ring authority
and runs one embedded ring slot.  The public ring ingress
``https://nannet.apps.mistral.run/v1/ring/*`` handles requests locally while the
embedded slot is active, and proxies to the current active runner endpoint when
an external non-Koyeb slot holds the lease.

This module imports the canonical ``point_fabric`` copied into the portal image
from NaNROUTER.  It never mints an issuer and never duplicates the portal's
authority database.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .point_fabric import (
    CentralPointFabric,
    FabricRoutingError,
    frame_from_json,
    frames_to_json,
)
from .runner_ring_authority import RunnerRingAuthError, RunnerRingAuthority

RING_SCHEMA = "nanrouter.portal-runner-ring.v1"
DEFAULT_SLOT = 0
RING_ENDPOINT = "HW5:0"


class PortalRingError(RuntimeError):
    pass


class PortalRingNode:
    def __init__(
        self,
        authority: RunnerRingAuthority,
        *,
        token: str,
        slot: int = DEFAULT_SLOT,
        endpoint: str,
        database: str,
        ttl_seconds: int = 30,
        poll_seconds: float = 2.0,
        checkpoint_seconds: float = 5.0,
    ):
        if not 0 <= slot < 6:
            raise PortalRingError("embedded slot must be 0..5")
        if not token or len(token) < 32:
            raise PortalRingError("runner ring token is required")
        self.authority = authority
        self.token = token
        self.slot = slot
        self.endpoint = endpoint.rstrip("/")
        self.ttl_seconds = ttl_seconds
        self.poll_seconds = poll_seconds
        self.checkpoint_seconds = checkpoint_seconds
        self.fabric = CentralPointFabric(database=database)
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._lease: dict[str, Any] | None = None
        self._thread: threading.Thread | None = None
        self._last_tick = 0
        self._last_checkpoint = 0
        self._errors = 0
        self._last_error: str | None = None
        self._handoffs = 0

    @property
    def active(self) -> bool:
        with self._lock:
            return self._lease is not None

    def start(self) -> "PortalRingNode":
        if self._thread is not None and self._thread.is_alive():
            return self
        self._thread = threading.Thread(
            target=self._run, name="portal-runner-ring", daemon=True
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        with self._lock:
            if self._lease is not None:
                self._checkpoint_locked()
                try:
                    self.authority.release(
                        slot=self.slot, lease_id=self._lease["lease_id"])
                except Exception:
                    pass
                self._lease = None
            self.fabric.close()

    def _error(self, exc: BaseException) -> None:
        with self._lock:
            self._errors += 1
            self._last_error = f"{exc.__class__.__name__}: {str(exc)[:200]}"

    def _checkpoint_locked(self) -> None:
        if self._lease is None:
            return
        state = self.fabric.export_state()
        self.authority.checkpoint(
            slot=self.slot, lease_id=self._lease["lease_id"],
            state=state, nanclock_tick=self._last_tick,
        )
        self._last_checkpoint = time.monotonic()

    def _activate_locked(self, lease: dict[str, Any]) -> None:
        checkpoint = self.authority.read_checkpoint()
        if checkpoint and isinstance(checkpoint.get("state"), dict):
            try:
                self.fabric.import_state(checkpoint["state"])
            except Exception as exc:
                self._error(exc)
        for hw in (0, 2, 5):
            try:
                self.fabric.point(hw)
            except FabricRoutingError:
                self.fabric.register(hw, status="active")
            else:
                self.fabric.heartbeat(hw, status="active")
        self._lease = lease
        self._handoffs += 1
        self._last_checkpoint = time.monotonic()

    def _step_down_locked(self, reason: str) -> None:
        lease = self._lease
        if lease is None:
            return
        try:
            self._checkpoint_locked()
        except Exception as exc:
            self._error(exc)
        try:
            self.authority.release(slot=self.slot, lease_id=lease["lease_id"])
        except Exception as exc:
            self._error(exc)
        try:
            self.fabric.heartbeat(5, status="degraded")
        except Exception:
            pass
        self._lease = None
        self._last_error = reason

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                clock = self.authority.clock()
                tick = int(clock["nanclock_tick"])
                with self._lock:
                    self._last_tick = max(self._last_tick, tick)
                    if self._lease is not None:
                        renewed = self.authority.renew(
                            slot=self.slot, lease_id=self._lease["lease_id"],
                            ttl_seconds=self.ttl_seconds)
                        self._lease.update(renewed)
                        if time.monotonic() - self._last_checkpoint >= self.checkpoint_seconds:
                            self._checkpoint_locked()
                    else:
                        lease = self.authority.lease(
                            slot=self.slot,
                            base_epoch=self._lease["epoch"] if self._lease else 0,
                            endpoint=self.endpoint,
                            ttl_seconds=self.ttl_seconds,
                        )
                        if lease.get("acquired"):
                            self._activate_locked(lease)
            except (RunnerRingAuthError, Exception) as exc:  # noqa: BLE001
                self._error(exc)
            self._stop.wait(self.poll_seconds)

    # -- local/proxy operations ------------------------------------------
    def _proxy(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        status = self.authority.status()
        endpoint = status.get("endpoint")
        if not status.get("active") or not endpoint:
            raise PortalRingError("no active runner ring owner")
        if endpoint.rstrip("/") == self.endpoint:
            raise PortalRingError("active runner endpoint points at the portal itself")
        raw = None if body is None else json.dumps(body, sort_keys=True).encode()
        headers = {"Authorization": "Bearer " + self.token}
        if raw is not None:
            headers["Content-Type"] = "application/json"
        request = Request(endpoint.rstrip("/") + path, data=raw, headers=headers,
                          method=method)
        try:
            with urlopen(request, timeout=10) as response:
                payload = response.read(2_097_153)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise PortalRingError(f"active runner unavailable: {exc.__class__.__name__}") from None
        if len(payload) > 2_097_152:
            raise PortalRingError("active runner response exceeds 2 MiB")
        try:
            value = json.loads(payload) if payload else {}
        except json.JSONDecodeError as exc:
            raise PortalRingError("active runner returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise PortalRingError("active runner response must be an object")
        return value

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "schema": RING_SCHEMA,
                "slot": self.slot,
                "endpoint": self.endpoint,
                "ring_endpoint": RING_ENDPOINT,
                "active": self._lease is not None,
                "phase": "active" if self._lease is not None else "standby",
                "epoch": int(self._lease["epoch"]) if self._lease else 0,
                "nanclock_tick": self._last_tick,
                "handoffs": self._handoffs,
                "errors": self._errors,
                "last_error": self._last_error,
                "fabric": self.fabric.monitor(),
            }

    def points(self) -> dict[str, Any]:
        if self.active:
            monitor = self.fabric.monitor()
            return {
                "schema": RING_SCHEMA,
                "active": True,
                "ring_endpoint": RING_ENDPOINT,
                "fabric": monitor,
                "registered": monitor["registered"],
                "queued": monitor["queued"],
                "pending": monitor["pending"],
            }
        return self._proxy("GET", "/v1/ring/points")

    def submit(self, body: dict[str, Any]) -> dict[str, Any]:
        if self.active:
            frame = frame_from_json(body.get("frame", body))
            return self.fabric.intake(frame)
        return self._proxy("POST", "/v1/ring/submit", body)

    def drain(self, body: dict[str, Any]) -> dict[str, Any]:
        if self.active:
            hw = int(body.get("hw", 5))
            limit = int(body.get("limit", 64))
            frames = self.fabric.drain(hw, limit)
            return {"schema": "nanrouter.zero-point-drain.v1",
                    "endpoint": f"HW{hw}:0", "count": len(frames),
                    "frames": frames_to_json(frames)}
        return self._proxy("POST", "/v1/ring/drain", body)

    def register(self, body: dict[str, Any]) -> dict[str, Any]:
        if self.active:
            return self.fabric.register(
                int(body["hw"]), role=body.get("role"),
                status=body.get("status", "active"))
        return self._proxy("POST", "/v1/ring/register", body)

    def checkpoint(self) -> dict[str, Any]:
        if self.active:
            with self._lock:
                self._checkpoint_locked()
            return self.status()
        return self._proxy("POST", "/v1/ring/checkpoint", {})

    def handoff(self) -> dict[str, Any]:
        if self.active:
            with self._lock:
                self._step_down_locked("explicit-handoff")
            return self.status()
        return self._proxy("POST", "/v1/ring/handoff", {})


__all__ = [
    "PortalRingError",
    "PortalRingNode",
    "RING_ENDPOINT",
    "RING_SCHEMA",
]
