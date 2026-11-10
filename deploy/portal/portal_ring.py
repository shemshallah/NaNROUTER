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
from .hw4_full_dict import MountedHW4, RING_OWNER as HW4_RING_OWNER
from .hw5_gutenberg import MountedHW5, OWNER as HW5_RING_OWNER
from .hw5_portal_stream import (
    HW5PortalStream, KIND as HW5_STREAM_KIND,
    QUERY_KIND as HW5_QUERY_KIND,
)
import os

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
        # Full HW4 WordNet reference lives at one immutable pinned path in
        # the *portal* image. Its read-only mmap stays open for the lifetime
        # of the existing ring node (including slot handoffs).
        hw4_store = os.environ.get("RIDDLE_HW4_STORE", "")
        if hw4_store and os.environ.get("RIDDLE_HW4_RING", HW4_RING_OWNER) != HW4_RING_OWNER:
            raise PortalRingError("HW4 cannot attach to the main BS0 runner ring")
        self.hw4 = MountedHW4(hw4_store) if hw4_store else None
        # The HW5 receiver lives on the SAME persistent Koyeb /data writer
        # as the ring authority, never on a second independently owned VM.
        hw5_store = os.environ.get("RIDDLE_HW5_STORE", "")
        hw5_upload = os.environ.get("RIDDLE_HW5_STREAM_DIR", "")
        if bool(hw5_store) != bool(hw5_upload):
            raise PortalRingError("HW5 store and stream directory must be configured together")
        if hw5_store and os.environ.get("RIDDLE_HW5_RING", HW5_RING_OWNER) != HW5_RING_OWNER:
            raise PortalRingError("HW5 cannot attach to BS0 writer ownership")
        self.hw5_store = hw5_store
        self.hw5_stream = (HW5PortalStream(hw5_upload, hw5_store)
                           if hw5_store else None)
        self.hw5 = (MountedHW5(hw5_store)
                    if hw5_store and os.path.exists(hw5_store) else None)
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
            if self.hw4 is not None:
                self.hw4.close()
                self.hw4 = None
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
        if self.hw4 is not None:
            # HW4's original fixed role is reserved until the image hashes
            # were verified. Activation is part of the same portal fabric,
            # never a new runner or a writable training chart.
            try:
                self.fabric.point(4)
            except FabricRoutingError:
                self.fabric.register(4, status="active")
            else:
                self.fabric.heartbeat(4, status="active")
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
                "hw4_wordnet_reference": (
                    self.hw4.status() if self.hw4 is not None else
                    {"mounted": False, "read_only": True,
                     "ring_owner": HW4_RING_OWNER}
                ),
                "hw5_gutenberg_reference": (
                    dict(self.hw5.status(), mounted=True, read_only=True)
                    if self.hw5 is not None else
                    {"mounted": False, "read_only": True,
                     "ring_owner": HW5_RING_OWNER}
                ),
                "hw5_corpus_stream": (
                    self.hw5_stream.status() if self.hw5_stream is not None
                    else {"configured": False, "sealed": False}
                ),
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
            if frame.kind == HW5_QUERY_KIND:
                # A native NaN16DE word holds the exact queried byte triple:
                # [reserved high byte][a][b][c]. request_id=1 asks for a
                # pair; request_id=2 asks for a true ordered triple. The
                # immutable HW5 root and triple ledger provide the answer.
                if "hw5_corpus" in body:
                    raise PortalRingError("readback queries cannot carry archive data")
                with self._lock:
                    if (self._lease is None or self.hw5 is None or
                            frame.source_hw != 0 or frame.destination_hw != 5 or
                            frame.origin != "zero-point" or
                            frame.request_id not in (1, 2) or
                            frame.word.payload >> 24 != 0 or
                            not self.fabric.point(5).active):
                        raise PortalRingError("HW5 readback requires the sealed active point")
                    payload = frame.word.payload
                    a, b, d = (payload >> 16) & 255, (payload >> 8) & 255, payload & 255
                    result = (self.hw5.pair(a, b) if frame.request_id == 1
                              else self.hw5.triple(a, b, d))
                    return {
                        "schema": "nanrouter.hw5-gutenberg-readback.v1",
                        "endpoint": "HW5:0",
                        "query": "pair" if frame.request_id == 1 else "triple",
                        "root_sha256": self.hw5.manifest["artifacts"]["gutenberg-c256.root"]["sha256"],
                        "result": result,
                        "remote_verified": True,
                    }
            if frame.kind == HW5_STREAM_KIND:
                with self._lock:
                    if self._lease is None:
                        raise PortalRingError("HW5 corpus import requires an active ring lease")
                    if self.hw5_stream is None:
                        raise PortalRingError("HW5 corpus import is disabled on this portal")
                    if not self.fabric.point(5).active:
                        raise PortalRingError("HW5 point is not active")
                    result = self.hw5_stream.receive(frame, body.get("hw5_corpus"))
                    if result.get("remote_verified") and self.hw5 is None:
                        self.hw5 = MountedHW5(self.hw5_store)
                    # Stream claims are consumed by the HW5:0 object receiver,
                    # not left in the generic NaN16DE inbox as fake corpus.
                    return dict(result, endpoint="HW5:0",
                                central_status="hw5_object_consumed")
            if "hw5_corpus" in body:
                raise PortalRingError("corpus payload requires the HW5 stream frame kind")
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
