"""Persistent BS0:0 Runner Riddle control-plane HTTP service."""
from __future__ import annotations

from dataclasses import asdict
import hmac
import json
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .inbox import InboxError, InboxFull, SQLiteSourceInbox
from .macro import BootstrapMacroPlanner, CurriculumState, PolicyError, SignedRangeManifest
from .cache import MasterRouteCache, RouteError
from .volume_registry import VolumeRegistry, VolumeRegistryError
from .ring import RunnerRing, RunnerRingError
from urllib.parse import parse_qs, urlsplit

ROOT_ADDRESS = "nan://GM0:SC0:MC0:BS0:0:HW0:0"
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
        self.intake_token = os.environ.get("RIDDLE_INTAKE_TOKEN", "")
        self.worker_token = os.environ.get("RIDDLE_WORKER_TOKEN", "")
        self.range_key = os.environ.get("RIDDLE_RANGE_HMAC_KEY", "").encode()
        self.route_key = os.environ.get("RIDDLE_ROUTE_HMAC_KEY", "").encode()
        self.feedback_key = os.environ.get("RIDDLE_FEEDBACK_HMAC_KEY", "").encode()
        if len(self.intake_token) < 32 or len(self.worker_token) < 32:
            raise ServiceConfigError("RIDDLE_INTAKE_TOKEN and RIDDLE_WORKER_TOKEN must each be 32+ characters")
        if len(self.feedback_key) < 32:
            raise ServiceConfigError("RIDDLE_FEEDBACK_HMAC_KEY must be 32+ bytes")

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

        def _authorized(self, token: str) -> bool:
            supplied = self.headers.get("Authorization", "")
            expected = "Bearer " + token
            return hmac.compare_digest(supplied, expected)

        def _ring_health(self, service):
            try:
                registry = service.volume_registry()
                if registry is None:
                    return {"health": "unknown", "configured": False}
                query = parse_qs(urlsplit(self.path).query)
                tick = int(query.get("nanclock_tick", [str(service.runner_ring.latest_tick())])[0])
                return service.runner_ring.snapshot(
                    expected_generation=registry.document["generation"],
                    expected_digest=registry.document["registry_digest"],
                    now_tick=tick,
                )
            except (ValueError, VolumeRegistryError, RunnerRingError):
                return {"health": "degraded", "configured": True, "valid": False}

        def do_GET(self):
            if self.path == "/healthz":
                self._json(200, {
                    "service": "Runner Riddle BS0:0",
                    "address": ROOT_ADDRESS,
                    "status": "ready",
                    "queue": service.inbox.stats(),
                    "range_manifest_present": service.range_manifest_path.exists(),
                    "route_cache_present": service.route_cache_path.exists(),
                    "volume_registry": service.volume_registry_health(),
                    "runner_ring": self._ring_health(service),
                    "live_route_commit": False,
                })
                return
            if self.path == "/v1/riddle/feedback":
                if not self._authorized(service.worker_token):
                    self._json(401, {"error": "worker authorization required"})
                    return
                self._json(200, {"pending": service.inbox.list_feedback()})
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
            self._json(404, {"error": "not found"})

        def do_POST(self):
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


def main() -> None:
    service = RiddleService()
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), make_handler(service))
    server.daemon_threads = True
    server.serve_forever()


if __name__ == "__main__":
    main()
