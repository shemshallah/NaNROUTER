"""Persistent BS0:0 Runner Riddle control-plane HTTP service."""
from __future__ import annotations

from dataclasses import asdict
import hmac
import json
import os
import signal
import threading
import re
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .inbox import InboxError, InboxFull, SQLiteSourceInbox
from .macro import BootstrapMacroPlanner, CurriculumState, PolicyError, SignedRangeManifest
from .cache import MasterRouteCache, RouteError
from .volume_registry import VolumeRegistry, VolumeRegistryError
from .ring import RunnerRing, RunnerRingError
from .hw4_full_dict import MountedHW4, RING_OWNER as HW4_RING_OWNER
from .hermes_leases import HermesLeaseRegistry, HermesLeaseError
from .hermes_native import HermesNativeLeaseRuntime, HermesNativeError
from .hermes_dispatch import HermesDispatchJournal, HermesDispatchError, HermesDispatchConflict
from .hermes_mth_tools import HermesMthTools, HermesMthToolError
from .mth_registry import MthRegistryError
from .n16t_guest import (
    MAX_FRAME_BYTES as N16T_MAX_FRAME_BYTES,
    MIN_FRAME_BYTES as N16T_MIN_FRAME_BYTES,
    N16TGuestPool,
    N16TGuestRuntimeError,
)
from .point_fabric import (
    CentralPointFabric,
    FabricCapacityError,
    FabricError,
    FabricFrameError,
    FabricRoutingError,
    PointFrame,
    frame_from_json,
    frames_to_json,
)
from urllib.parse import parse_qs, urlsplit

ROOT_ADDRESS = "nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0"
MAX_REQUEST_BYTES = 2_097_152


class ServiceConfigError(RuntimeError):
    pass


class RiddleService:
    def __init__(self):
        data_dir = Path(os.environ.get("RIDDLE_DATA_DIR", "/data"))
        data_dir.mkdir(parents=True, exist_ok=True)
        max_pending = int(os.environ.get("RIDDLE_MAX_PENDING_EVENTS", "4096"))
        self.inbox = SQLiteSourceInbox(
            data_dir / "runner-riddle.sqlite", max_pending_events=max_pending
        )
        self.range_manifest_path = data_dir / "allocator-range-manifest.json"
        self.route_cache_path = data_dir / "master-network-cache.json"
        self.volume_registry_path = Path(os.environ.get("RIDDLE_VOLUME_REGISTRY_PATH", str(data_dir / "volume-registry.json")))
        self.volume_key = os.environ.get("RIDDLE_VOLUME_HMAC_KEY", "").encode()
        self.runner_ring = RunnerRing(data_dir / "runner-ring.sqlite",
                                      stale_after_ticks=int(os.environ.get("RIDDLE_RING_STALE_TICKS", "256")))
        # HW4 is an immutable NaNROUTER-owned reference attachment. The
        # existing router ring owns access; no BS0 training ring membership.
        hw4_store = os.environ.get("RIDDLE_HW4_STORE", "")
        self.hw4 = None
        if hw4_store:
            if os.environ.get("RIDDLE_HW4_RING", HW4_RING_OWNER) != HW4_RING_OWNER:
                raise ServiceConfigError("HW4 reference cannot attach to the BS0 main runner ring")
            try:
                self.hw4 = MountedHW4(hw4_store)
            except (OSError, ValueError, KeyError) as exc:
                raise ServiceConfigError("HW4 reference failed closed: missing or corrupt generation") from exc
        self.intake_token = os.environ.get("RIDDLE_INTAKE_TOKEN", "")
        self.worker_token = os.environ.get("RIDDLE_WORKER_TOKEN", "")
        self.range_key = os.environ.get("RIDDLE_RANGE_HMAC_KEY", "").encode()
        self.route_key = os.environ.get("RIDDLE_ROUTE_HMAC_KEY", "").encode()
        self.feedback_key = os.environ.get("RIDDLE_FEEDBACK_HMAC_KEY", "").encode()
        self.hermes_delegate_token = os.environ.get("RIDDLE_HERMES_DELEGATION_TOKEN", "")
        hermes_signing_key = os.environ.get("RIDDLE_HERMES_RECEIPT_HMAC_KEY", "").encode()
        self.hermes_leases = None
        if self.hermes_delegate_token or hermes_signing_key:
            if len(self.hermes_delegate_token) < 32 or len(hermes_signing_key) < 32:
                raise ServiceConfigError("both HERMES portal delegation token and receipt key must be 32+ bytes")
            self.hermes_leases = HermesLeaseRegistry(data_dir / "hermes-universe-leases.sqlite", hermes_signing_key)
        self.hermes_lock = threading.RLock()
        self.hermes_mth = (HermesMthTools.from_checkout()
                           if self.hermes_leases is not None else None)
        self.hermes_native = None
        self.hermes_dispatches = (HermesDispatchJournal(data_dir / "hermes-dispatch.sqlite")
                                  if self.hermes_leases is not None else None)
        native_keys = ("NAN16_LIBRARY", "HERMES_GUEST_IMAGE", "HERMES_GUEST_LABELS",
                       "RIDDLE_HERMES_NATIVE_LIBRARY_SHA256", "RIDDLE_HERMES_NATIVE_IMAGE_SHA256")
        if any(os.environ.get(k) for k in native_keys if k != "NAN16_LIBRARY"):
            if self.hermes_leases is None:
                raise ServiceConfigError("native HERMES guest requires delegated lease authority")
            try:
                self.hermes_native = HermesNativeLeaseRuntime.from_env()
            except HermesNativeError as exc:
                raise ServiceConfigError("HERMES pinned native guest is not ready") from exc
        self.n16t_token = os.environ.get("RIDDLE_N16T_SUBMIT_TOKEN", "")
        self.build_revision = os.environ.get("RIDDLE_BUILD_REVISION", "unknown")
        self.n16t_guest_pool = None
        self.hermes_n16t_pool = None
        if len(self.intake_token) < 32 or len(self.worker_token) < 32:
            raise ServiceConfigError("RIDDLE_INTAKE_TOKEN and RIDDLE_WORKER_TOKEN must each be 32+ characters")
        if len(self.feedback_key) < 32:
            raise ServiceConfigError("RIDDLE_FEEDBACK_HMAC_KEY must be 32+ bytes")
        if self.n16t_token:
            if len(self.n16t_token) < 32:
                raise ServiceConfigError("RIDDLE_N16T_SUBMIT_TOKEN must be 32+ characters")
            try:
                # The generic /n16t submit service must NOT share a VM
                # session affinity key with a HERMES delegated universe.
                # Its own session store (optional) is independent.
                self.n16t_guest_pool = N16TGuestPool.from_env(max_sessions=8)
                if self.hermes_native is not None:
                    # HERMES always has a distinct durable native N16T pool.
                    # Reconstruct exactly the guest's accepted frame cursor
                    # on restart, never a fresh session under an old lease.
                    hermes_store = os.environ.get(
                        "RIDDLE_HERMES_N16T_SESSION_STORE",
                        str(data_dir / "hermes-n16t-sessions.sqlite"))
                    generic_store = (
                        os.environ.get("RIDDLE_N16T_SESSION_STORE")
                        or os.environ.get("N16T_SESSION_STORE")
                    )
                    if generic_store and (os.path.realpath(generic_store)
                                          == os.path.realpath(hermes_store)):
                        raise ServiceConfigError(
                            "generic N16T and delegated HERMES guest pools must use distinct stores")
                    self.hermes_n16t_pool = N16TGuestPool.from_env(
                        max_sessions=8, store=hermes_store)
            except Exception as exc:
                raise ServiceConfigError("N16T guest runtime configuration is incomplete or invalid") from exc

        # The zero-point fabric is always available as an in-process central
        # intake/monitor.  A durable journal is used in deployments with a
        # persistent data directory.  It never evaluates NaN words.
        self.fabric_token = os.environ.get("RIDDLE_FABRIC_TOKEN", "")
        self.point_fabric = None
        if os.environ.get("RIDDLE_FABRIC_ENABLED", "1").strip().lower() not in (
            "0", "false", "no", "off"
        ):
            fabric_database = os.environ.get(
                "RIDDLE_FABRIC_DB", str(data_dir / "point-fabric.sqlite")
            )
            self.point_fabric = CentralPointFabric(database=fabric_database)
            if self.hermes_leases is not None:
                # A delegated HERMES universe has an active HW2 endpoint.
                self.point_fabric.register(2, status="active")

    def close(self) -> None:
        if self.point_fabric is not None:
            self.point_fabric.close()
            self.point_fabric = None
        if self.hermes_n16t_pool is not None:
            self.hermes_n16t_pool.close()
            self.hermes_n16t_pool = None
        if self.hermes_native is not None:
            self.hermes_native.close()
            self.hermes_native = None
        if self.n16t_guest_pool is not None:
            self.n16t_guest_pool.close()
            self.n16t_guest_pool = None

    def volume_registry(self):
        if not self.volume_registry_path.exists() or len(self.volume_key) < 32:
            return None
        return VolumeRegistry.load(self.volume_registry_path, self.volume_key)

    def volume_registry_health(self):
        if not self.volume_registry_path.exists() or len(self.volume_key) < 32:
            return {"health": "unknown", "configured": False}
        try:
            return self.volume_registry().summary()
        except VolumeRegistryError:
            return {"health": "degraded", "configured": True, "valid": False}


def make_handler(service: RiddleService):
    class Handler(BaseHTTPRequestHandler):
        server_version = "NaNROUTER-BS0/1"

        def log_message(self, fmt: str, *args: Any) -> None:
            # Never log request bodies or authorization headers.
            super().log_message(fmt, *args)

        def _json(self, status: int, value: dict[str, Any]) -> None:
            raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def _body(self) -> dict[str, Any]:
            if self.headers.get_content_type() != "application/json":
                raise ValueError("Content-Type must be application/json")
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ValueError("invalid content length") from exc
            if length < 1 or length > MAX_REQUEST_BYTES:
                raise ValueError("request body is empty or exceeds 2 MiB")
            raw = self.rfile.read(length)
            try:
                value = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("request must be valid UTF-8 JSON") from exc
            if not isinstance(value, dict):
                raise ValueError("request JSON must be an object")
            return value

        def _optional_body(self) -> dict[str, Any]:
            """Read a bounded JSON body, treating an absent body as ``{}``."""
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
            except ValueError as exc:
                raise ValueError("invalid content length") from exc
            if length == 0:
                return {}
            return self._body()

        def _authorized(self, token: str) -> bool:
            supplied = self.headers.get("Authorization", "")
            expected = "Bearer " + token
            return hmac.compare_digest(supplied, expected)

        def _fabric_authorized(self, hw: int | None = None) -> bool:
            if service.point_fabric is None:
                return False
            if self._authorized(service.worker_token):
                return True
            if service.fabric_token and self._authorized(service.fabric_token):
                return True
            # The paired HERMES endpoint may use the existing portal
            # delegation bearer for its own HW2 in/out traffic.
            if (
                hw == 2
                and service.hermes_leases is not None
                and service.hermes_delegate_token
                and self._authorized(service.hermes_delegate_token)
            ):
                return True
            return False

        def _fabric_error(self, exc: FabricError) -> None:
            if isinstance(exc, FabricCapacityError):
                self._json(429, {"error": str(exc)[:200]})
            elif isinstance(exc, FabricRoutingError):
                self._json(409, {"error": str(exc)[:200]})
            else:
                self._json(400, {"error": str(exc)[:200]})

        def _fabric_point_path(self) -> tuple[int, str] | None:
            path = urlsplit(self.path).path
            match = re.fullmatch(r"/v1/fabric/points/(\d{1,3})(?:/(monitor|drain|register|heartbeat))?", path)
            if match is None:
                return None
            return int(match.group(1)), match.group(2) or "monitor"

        def _n16t_body(self) -> bytes:
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("chunked N16T request bodies are not supported")
            encoding = self.headers.get("Content-Encoding")
            if encoding and encoding.strip().lower() != "identity":
                raise ValueError("N16T Content-Encoding is not supported")
            if self.headers.get_content_type() not in (
                "application/x-n16t", "application/vnd.nan16.n16t"
            ):
                raise ValueError("Content-Type must identify an N16T frame")
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1:
                raise ValueError("exactly one Content-Length is required")
            raw_length = lengths[0].strip()
            if not raw_length.isascii() or not raw_length.isdigit():
                raise ValueError("invalid N16T Content-Length")
            length = int(raw_length)
            if length < N16T_MIN_FRAME_BYTES or length > min(
                MAX_REQUEST_BYTES, N16T_MAX_FRAME_BYTES
            ):
                raise ValueError("N16T frame is outside the transport bounds")
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError("N16T frame is truncated")
            return raw

        def _n16t_binary(self, status: int, frame: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/x-n16t")
            self.send_header("Content-Length", str(len(frame)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self.close_connection = True
            self.end_headers()
            self.wfile.write(frame)

        def _n16t(self) -> None:
            if service.n16t_guest_pool is None or len(service.n16t_token) < 32:
                self._json(503, {"error": "N16T guest peer is not configured"})
                return
            if not self._authorized(service.n16t_token):
                self._json(401, {"error": "N16T submit authorization required"})
                return
            try:
                request_frame = self._n16t_body()
                response_frame = service.n16t_guest_pool.exchange(request_frame)
                if not isinstance(response_frame, bytes) or not (
                    N16T_MIN_FRAME_BYTES <= len(response_frame) <= N16T_MAX_FRAME_BYTES
                ):
                    raise N16TGuestRuntimeError("NaN16 guest returned an invalid frame")
                self._n16t_binary(200, response_frame)
            except (TypeError, ValueError) as exc:
                self._json(400, {"error": str(exc)})
            except N16TGuestRuntimeError:
                self._json(502, {"error": "NaN16 N16T guest exchange failed"})
            except Exception:
                self._json(502, {"error": "NaN16 N16T guest exchange failed"})

        def _ring_health(self, service):
            try:
                registry = service.volume_registry()
                if registry is None:
                    return {"health": "unknown", "configured": False}
                query = parse_qs(urlsplit(self.path).query)
                tick = int(query.get("nanclock_tick", [str(int(time.time()))])[0])
                return service.runner_ring.snapshot(
                    expected_generation=registry.document["generation"],
                    expected_digest=registry.document["registry_digest"],
                    now_tick=tick,
                )
            except (ValueError, VolumeRegistryError, RunnerRingError):
                return {"health": "degraded", "configured": True, "valid": False}

        def do_GET(self):
            if self.path == "/healthz":
                fabric_summary = None
                if service.point_fabric is not None:
                    fabric_monitor = service.point_fabric.monitor()
                    fabric_summary = {
                        "enabled": True,
                        "schema": fabric_monitor["fabric"],
                        "registered": fabric_monitor["registered"],
                        "active": fabric_monitor["active"],
                        "queued": fabric_monitor["queued"],
                        "pending": fabric_monitor["pending"],
                    }
                self._json(200, {
                    "service": "Runner Riddle BS0:0",
                    "address": ROOT_ADDRESS,
                    "status": "ready",
                    "build_revision": service.build_revision,
                    "runtime": {
                        "nan16_word_bits": 16,
                        "ring_slots": 6,
                        "active_slots": 1,
                        "n16t_guest_configured": service.n16t_guest_pool is not None,
                    },
                    "queue": service.inbox.stats(),
                    "range_manifest_present": service.range_manifest_path.exists(),
                    "route_cache_present": service.route_cache_path.exists(),
                    "volume_registry": service.volume_registry_health(),
                    "runner_ring": self._ring_health(service),
                    "hw4_wordnet_reference": {"mounted": service.hw4 is not None, "ring_owner": HW4_RING_OWNER},
                    "live_route_commit": False,
                    "hermes_delegated_lease_authority": service.hermes_leases is not None,
                    "hermes_native_guest_configured": service.hermes_native is not None,
                    "hermes_n16t_dispatch_ready": (service.hermes_native is not None and service.hermes_n16t_pool is not None),
                    "hermes_n16t_separate_guest_pool": service.hermes_n16t_pool is not None,
                    "point_fabric": fabric_summary,
                })
                return
            if self.path == "/v1/riddle/feedback":
                if not self._authorized(service.worker_token):
                    self._json(401, {"error": "worker authorization required"})
                    return
                self._json(200, {"pending": service.inbox.list_feedback()})
                return
            # Authenticated, strictly read-only HW4 reference queries. The
            # matrix is pinned in this router process, not the BS0 trainer.
            hw4_path = urlsplit(self.path).path
            if hw4_path in ("/v1/riddle/hw4/status", "/v1/riddle/hw4/pair",
                            "/v1/riddle/hw4/exact"):
                if not self._authorized(service.worker_token):
                    self._json(401, {"error": "worker authorization required"})
                    return
                if service.hw4 is None:
                    self._json(503, {"error": "HW4 WordNet reference is not mounted"})
                    return
                try:
                    query = parse_qs(urlsplit(self.path).query)
                    if hw4_path.endswith("/status"):
                        result = service.hw4.status()
                    elif hw4_path.endswith("/pair"):
                        result = service.hw4.pair(int(query["a"][0]), int(query["b"][0]))
                    else:
                        result = {"synset": query["synset"][0],
                                  "pointers": service.hw4.exact(query["synset"][0],
                                    int(query.get("limit", ["32"])[0]))}
                    self._json(200, result)
                except (ValueError, KeyError, IndexError) as exc:
                    self._json(400, {"error": str(exc)[:200]})
                return
            if urlsplit(self.path).path == "/v1/riddle/ring":
                if not self._authorized(service.worker_token):
                    self._json(401, {"error": "worker authorization required"})
                    return
                try:
                    registry = service.volume_registry()
                    if registry is None:
                        self._json(503, {"error": "signed volume registry is not installed"})
                        return
                    query = parse_qs(urlsplit(self.path).query)
                    tick = int(query.get("nanclock_tick", [str(service.runner_ring.latest_tick())])[0])
                    snapshot = service.runner_ring.snapshot(
                        expected_generation=registry.document["generation"],
                        expected_digest=registry.document["registry_digest"],
                        now_tick=tick,
                    )
                    self._json(200, {"volume_registry": registry.summary(), "runner_ring": snapshot})
                except (ValueError, VolumeRegistryError, RunnerRingError) as exc:
                    self._json(400, {"error": str(exc)})
                return
            if self.path == "/v1/riddle/volumes":
                if not self._authorized(service.worker_token):
                    self._json(401, {"error": "worker authorization required"})
                    return
                try:
                    registry = service.volume_registry()
                except VolumeRegistryError:
                    self._json(503, {"error": "signed volume registry failed verification"})
                    return
                if registry is None:
                    self._json(503, {"error": "signed volume registry is not installed"})
                    return
                self._json(200, {"registry": registry.summary(), "volumes": registry.public_records()})
                return
            if self.path == "/v1/riddle/queue":
                if not self._authorized(service.worker_token):
                    self._json(401, {"error": "worker authorization required"})
                    return
                self._json(200, {"queue": service.inbox.stats()})
                return
            if urlsplit(self.path).path == "/v1/fabric/points":
                if service.point_fabric is None:
                    self._json(503, {"error": "zero-point fabric is disabled"})
                    return
                if not self._fabric_authorized():
                    self._json(401, {"error": "fabric authorization required"})
                    return
                self._json(200, service.point_fabric.monitor())
                return
            point_path = self._fabric_point_path()
            if point_path is not None and point_path[1] == "monitor":
                if service.point_fabric is None:
                    self._json(503, {"error": "zero-point fabric is disabled"})
                    return
                hw, _ = point_path
                if not self._fabric_authorized(hw):
                    self._json(401, {"error": "fabric authorization required"})
                    return
                try:
                    self._json(200, service.point_fabric.point_monitor(hw))
                except FabricRoutingError as exc:
                    self._json(404, {"error": str(exc)[:200]})
                return
            self._json(404, {"error": "not found"})

        def do_POST(self):
            path = urlsplit(self.path).path
            if path in ("/v1/fabric/intake", "/v1/fabric/route"):
                if service.point_fabric is None:
                    self._json(503, {"error": "zero-point fabric is disabled"})
                    return
                if not self._fabric_authorized():
                    self._json(401, {"error": "fabric authorization required"})
                    return
                try:
                    body = self._body()
                    if "frame_hex" in body:
                        raw = body["frame_hex"]
                        if not isinstance(raw, str) or len(raw) > 512 or len(raw) % 2:
                            raise FabricFrameError("frame_hex must be bounded even-length hexadecimal")
                        frame = PointFrame.decode(bytes.fromhex(raw))
                    elif "frame" in body:
                        frame = frame_from_json(body["frame"])
                    else:
                        frame = frame_from_json(body)
                    receipt = service.point_fabric.intake(frame)
                    self._json(200, receipt)
                except FabricError as exc:
                    self._fabric_error(exc)
                except (ValueError, TypeError) as exc:
                    self._json(400, {"error": str(exc)[:200]})
                return
            point_path = self._fabric_point_path()
            if point_path is not None:
                if service.point_fabric is None:
                    self._json(503, {"error": "zero-point fabric is disabled"})
                    return
                hw, action = point_path
                if not self._fabric_authorized(hw):
                    self._json(401, {"error": "fabric authorization required"})
                    return
                try:
                    body = self._optional_body()
                    if action == "drain":
                        frames = service.point_fabric.drain(hw, body.get("limit", 64))
                        self._json(200, {
                            "schema": "nanrouter.zero-point-drain.v1",
                            "endpoint": f"HW{hw}:0",
                            "count": len(frames),
                            "frames": frames_to_json(frames),
                        })
                    elif action == "register":
                        result = service.point_fabric.register(
                            hw,
                            role=body.get("role"),
                            status=body.get("status", "active"),
                        )
                        self._json(200, result)
                    elif action == "heartbeat":
                        result = service.point_fabric.heartbeat(
                            hw, status=body.get("status", "active")
                        )
                        self._json(200, result)
                    else:
                        self._json(405, {"error": "monitor is read-only; use GET"})
                except FabricError as exc:
                    self._fabric_error(exc)
                except (ValueError, TypeError) as exc:
                    self._json(400, {"error": str(exc)[:200]})
                return
            if self.path == "/n16t":
                self._n16t()
                return
            if self.path == "/v1/hermes/mth/call":
                # Same protected portal delegation and active universe receipt
                # as native head dispatch. Catalog/plan tools never execute math.
                if service.hermes_leases is None or service.hermes_mth is None:
                    self._json(503, {"error": "HERMES MTH catalog unavailable"})
                    return
                if not self._authorized(service.hermes_delegate_token):
                    self._json(401, {"error": "NANNET portal delegation required"})
                    return
                try:
                    body = self._body()
                    with service.hermes_lock:
                        route = service.hermes_leases.resolve(
                            installation_id=body["installation_id"],
                            receipt=body["receipt"],
                            head_index=body["head_index"])
                        arguments = body.get("arguments", {})
                        if body["tool"] == "mth.route" and isinstance(arguments, dict):
                            arguments = {**arguments, "head_index": route["head_index"]}
                        result = service.hermes_mth.invoke(body["tool"], arguments)
                    self._json(200, {
                        "route": {key: route[key] for key in
                                  ("lease_id", "universe_id", "head_index")},
                        "tool_result": result,
                        "native_execution_committed": False,
                    })
                except (KeyError, TypeError, ValueError, HermesMthToolError,
                        MthRegistryError) as exc:
                    self._json(400, {"error": str(exc)[:200]})
                return
            if self.path.startswith("/v1/hermes/leases/"):
                # This is a portal-to-router route, NOT a public guest API.
                # The portal must first validate its NANNET installation/HW
                # identity, scopes and revocation before delegating the call.
                if service.hermes_leases is None:
                    self._json(503, {"error": "HERMES delegated lease authority is not configured"})
                    return
                if not self._authorized(service.hermes_delegate_token):
                    self._json(401, {"error": "NANNET portal delegation required"})
                    return
                try:
                    body = self._body()
                    action = self.path.removeprefix("/v1/hermes/leases/")
                    if action not in ("open", "renew", "resolve", "release", "dispatch", "ack", "inspect"):
                        self._json(404, {"error": "not found"})
                        return
                    with service.hermes_lock:
                        identity = body["installation_id"]
                        if action == "open":
                            receipt = service.hermes_leases.open(
                                installation_id=identity,
                                node_point=body["node_point"], request_id=body["request_id"],
                                ttl_seconds=body.get("ttl_seconds", 900))
                            if service.hermes_native is not None:
                                # Ensure the guest actually accepts an initial
                                # head before publishing an activated receipt.
                                service.hermes_native.admit(
                                    service.hermes_leases, installation_id=identity,
                                    receipt=receipt, head_index=0)
                            self._json(200, {"receipt": receipt})
                        elif action == "renew":
                            receipt = service.hermes_leases.renew(
                                installation_id=identity, receipt=body["receipt"],
                                ttl_seconds=body.get("ttl_seconds", 900))
                            if service.hermes_native is not None:
                                service.hermes_native.admit(
                                    service.hermes_leases, installation_id=identity,
                                    receipt=receipt, head_index=0)
                            self._json(200, {"receipt": receipt})
                        elif action == "resolve":
                            resolved = service.hermes_leases.resolve(
                                installation_id=identity, receipt=body["receipt"],
                                head_index=body["head_index"])
                            if service.hermes_native is not None:
                                native = service.hermes_native.admit(
                                    service.hermes_leases, installation_id=identity,
                                    receipt=body["receipt"], head_index=body["head_index"])
                                resolved.update(native)
                                resolved["native_execution_committed"] = True
                            self._json(200, {"route": resolved})
                        elif action == "release":
                            result = service.hermes_leases.release(
                                installation_id=identity, receipt=body["receipt"])
                            self._json(200, result)
                        elif action in ("dispatch", "ack", "inspect"):
                            if action != "inspect" and (service.hermes_native is None or service.hermes_n16t_pool is None):
                                self._json(503, {"error": "pinned native HERMES and N16T guest runtimes are required"})
                                return
                            resolved = service.hermes_leases.resolve(
                                installation_id=identity, receipt=body["receipt"],
                                head_index=body["head_index"])
                            native = {}
                            if action != "inspect":
                                native = service.hermes_native.admit(
                                    service.hermes_leases, installation_id=identity,
                                    receipt=body["receipt"], head_index=body["head_index"])
                            with service.hermes_leases._connect() as db:
                                row = service.hermes_leases._live(
                                    db, body["receipt"], identity, int(time.time()))
                            if action == "dispatch":
                                frame_hex = body.get("frame_hex")
                                if (not isinstance(frame_hex, str)
                                        or len(frame_hex) % 2 != 0
                                        or len(frame_hex) > N16T_MAX_FRAME_BYTES * 2
                                        or re.fullmatch("[0-9a-fA-F]+", frame_hex) is None):
                                    raise HermesDispatchError("invalid bounded N16T hexadecimal frame")
                                result = service.hermes_dispatches.dispatch(
                                    row=row, installation_id=identity,
                                    head_index=body["head_index"],
                                    dispatch_id=body["dispatch_id"],
                                    frame=bytes.fromhex(frame_hex),
                                    native_exchange=service.hermes_n16t_pool.exchange)
                                result.update(native)
                                result.update({"lease_id": resolved["lease_id"],
                                               "universe_id": resolved["universe_id"],
                                               "head_index": resolved["head_index"]})
                                self._json(200, result)
                            elif action == "ack":
                                result = service.hermes_dispatches.acknowledge(
                                    row=row, installation_id=identity,
                                    head_index=body["head_index"],
                                    dispatch_id=body["dispatch_id"],
                                    response_sha256=body["response_sha256"])
                                self._json(200, result)
                            else:
                                result = service.hermes_dispatches.inspect(
                                    row=row, installation_id=identity,
                                    head_index=body["head_index"],
                                    dispatch_id=body["dispatch_id"])
                                result.update({"lease_id": resolved["lease_id"],
                                               "universe_id": resolved["universe_id"],
                                               "head_index": resolved["head_index"]})
                                self._json(200, result)
                except HermesDispatchConflict as exc:
                    self._json(409, {"error": str(exc)})
                except (HermesNativeError, N16TGuestRuntimeError) as exc:
                    self._json(503, {"error": "native HERMES/N16T execution failed closed"})
                except (KeyError, TypeError, ValueError) as exc:
                    self._json(400, {"error": str(exc)[:200]})
                except Exception:
                    self._json(500, {"error": "internal HERMES lease service error"})
                return
            try:
                body = self._body()
                if self.path == "/v1/riddle/intake":
                    if not self._authorized(service.intake_token):
                        self._json(401, {"error": "intake authorization required"})
                        return
                    payload_hex = body.get("payload_hex", "")
                    if not isinstance(payload_hex, str) or len(payload_hex) > MAX_REQUEST_BYTES * 2:
                        raise ValueError("payload_hex is invalid or too large")
                    try:
                        payload = bytes.fromhex(payload_hex)
                    except ValueError as exc:
                        raise ValueError("payload_hex must be even-length hexadecimal") from exc
                    event_id = service.inbox.enqueue(
                        universe_id=str(body["universe_id"]),
                        node_point=int(body["node_point"]),
                        head_index=int(body["head_index"]),
                        source_kind=str(body.get("source_kind", "nan-source")),
                        payload=payload,
                        acl_digest=str(body["acl_digest"]),
                        nanclock_tick=int(body["nanclock_tick"]),
                    )
                    self._json(202, {"event_id": event_id, "accepted": True})
                    return

                if not self._authorized(service.worker_token):
                    self._json(401, {"error": "worker authorization required"})
                    return

                if self.path == "/v1/riddle/ring/heartbeat":
                    registry = service.volume_registry()
                    if registry is None:
                        self._json(503, {"error": "signed volume registry is not installed"})
                        return
                    snapshot = service.runner_ring.heartbeat(
                        slot=int(body["slot"]),
                        runner_id=str(body["runner_id"]),
                        registry_generation=int(body["registry_generation"]),
                        registry_digest=str(body["registry_digest"]),
                        nanclock_tick=int(body["nanclock_tick"]),
                        expected_generation=int(registry.document["generation"]),
                        expected_digest=str(registry.document["registry_digest"]),
                    )
                    self._json(200, {"accepted": True, "runner_ring": snapshot})
                    return

                if self.path == "/v1/riddle/lease":
                    event = service.inbox.lease_next(
                        owner=str(body["owner"]),
                        now_tick=int(body["now_tick"]),
                        lease_ticks=int(body.get("lease_ticks", 64)),
                    )
                    if event is None:
                        self._json(200, {"event": None})
                        return
                    self._json(200, {
                        "event_id": event.event_id,
                        "universe_id": event.universe_id,
                        "node_point": event.node_point,
                        "head_index": event.head_index,
                        "source_kind": event.source_kind,
                        "source_hash": event.source_hash,
                        "payload_hex": event.payload.hex(),
                        "acl_digest": event.acl_digest,
                        "nanclock_tick": event.nanclock_tick,
                        "lease_owner": event.lease_owner,
                        "attempts": event.attempts,
                    })
                    return

                if self.path == "/v1/riddle/ack":
                    event = service.inbox.get_leased(str(body["event_id"]), str(body["owner"]))
                    ok = service.inbox.ack(
                        event,
                        result_digest=str(body["result_digest"]),
                        result_generation=int(body["result_generation"]),
                        trace=body["trace"],
                    )
                    self._json(200, {"acknowledged": ok, "event_id": event.event_id})
                    return

                if self.path == "/v1/riddle/retry":
                    event = service.inbox.get_leased(str(body["event_id"]), str(body["owner"]))
                    state = service.inbox.retry(event, max_attempts=int(body.get("max_attempts", 8)))
                    self._json(200, {"event_id": event.event_id, "state": state})
                    return

                if self.path == "/v1/riddle/feedback":
                    feedback = BootstrapMacroPlanner.feedback_envelope(
                        universe_id=str(body["universe_id"]),
                        stage=str(body["stage"]),
                        base_generation=int(body["base_generation"]),
                        completed_steps=int(body["completed_steps"]),
                        candidate_digest=str(body["candidate_digest"]),
                        acl_digest=str(body["acl_digest"]),
                        signing_key=service.feedback_key,
                        nanclock_tick=int(body.get("nanclock_tick", 0)),
                    )
                    feedback_id = service.inbox.record_feedback(feedback)
                    self._json(202, {"feedback_id": feedback_id, "accepted": True})
                    return

                if self.path == "/v1/riddle/feedback/ack":
                    ok = service.inbox.ack_feedback(str(body["feedback_id"]))
                    self._json(200, {"acknowledged": ok, "feedback_id": str(body["feedback_id"])})
                    return

                if self.path == "/v1/riddle/routes/resolve":
                    if not service.route_cache_path.exists() or len(service.route_key) < 32:
                        self._json(503, {"error": "signed master route cache is not installed"})
                        return
                    cache = MasterRouteCache.load(service.route_cache_path, service.route_key)
                    packet = cache.resolve(str(body["address"]), now_tick=int(body["nanclock_tick"]) if "nanclock_tick" in body else None)
                    self._json(200, {"packet": packet, "live_route_commit": False})
                    return

                if self.path == "/v1/riddle/plan":
                    if not service.range_manifest_path.exists() or len(service.range_key) < 32:
                        self._json(503, {"error": "verified allocator range manifest is not installed"})
                        return
                    manifest_doc = json.loads(service.range_manifest_path.read_text(encoding="utf-8"))
                    manifest = SignedRangeManifest(manifest_doc, service.range_key)
                    state_doc = body.get("state", {})
                    state = CurriculumState(
                        boolean_gate_passed=bool(state_doc.get("boolean_gate_passed", False)),
                        boolean_heads_verified=int(state_doc.get("boolean_heads_verified", 0)),
                        distinct_boolean_rules=int(state_doc.get("distinct_boolean_rules", 0)),
                        routing_gate_passed=bool(state_doc.get("routing_gate_passed", False)),
                        permanent_heads_mapped=int(state_doc.get("permanent_heads_mapped", 0)),
                        mapped_layers=tuple(int(x) for x in state_doc.get("mapped_layers", [])),
                        base_generation=int(state_doc.get("base_generation", 0)),
                    )
                    job = BootstrapMacroPlanner().next_job(state, manifest)
                    result = asdict(job)
                    self._json(200, {"job": result, "live_map_commit": False})
                    return

                self._json(404, {"error": "not found"})
            except InboxFull as exc:
                self._json(429, {"error": str(exc), "retryable": True})
            except (KeyError, TypeError, ValueError, InboxError, PolicyError, RouteError, VolumeRegistryError, RunnerRingError) as exc:
                self._json(400, {"error": str(exc)})
            except Exception:
                self._json(500, {"error": "internal service error"})

    return Handler


def install_stop_handlers(server: ThreadingHTTPServer) -> None:
    """Turn Koyeb's SIGTERM into a graceful serve_forever shutdown."""
    def stop(signum, frame) -> None:
        del signum, frame
        threading.Thread(target=server.shutdown, daemon=True).start()

    for name in ("SIGTERM", "SIGINT"):
        candidate = getattr(signal, name, None)
        if candidate is not None:
            signal.signal(candidate, stop)


def main() -> None:
    service = RiddleService()
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(service))
    server.daemon_threads = True
    install_stop_handlers(server)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        service.close()


if __name__ == "__main__":
    main()
