"""Persistent BS0:0 Runner Riddle control-plane HTTP service."""
from __future__ import annotations

from dataclasses import asdict
import hmac
import json
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .inbox import InboxError, SQLiteSourceInbox
from .macro import BootstrapMacroPlanner, CurriculumState, PolicyError, SignedRangeManifest
from .cache import MasterRouteCache, RouteError

ROOT_ADDRESS = "nan://GM0:SC0:MC0:BS0:0:HW0:0"
MAX_REQUEST_BYTES = 2_097_152


class ServiceConfigError(RuntimeError):
    pass


class RiddleService:
    def __init__(self):
        data_dir = Path(os.environ.get("RIDDLE_DATA_DIR", "/data"))
        data_dir.mkdir(parents=True, exist_ok=True)
        self.inbox = SQLiteSourceInbox(data_dir / "runner-riddle.sqlite")
        self.range_manifest_path = data_dir / "allocator-range-manifest.json"
        self.route_cache_path = data_dir / "master-network-cache.json"
        self.intake_token = os.environ.get("RIDDLE_INTAKE_TOKEN", "")
        self.worker_token = os.environ.get("RIDDLE_WORKER_TOKEN", "")
        self.range_key = os.environ.get("RIDDLE_RANGE_HMAC_KEY", "").encode()
        self.route_key = os.environ.get("RIDDLE_ROUTE_HMAC_KEY", "").encode()
        if len(self.intake_token) < 32 or len(self.worker_token) < 32:
            raise ServiceConfigError("RIDDLE_INTAKE_TOKEN and RIDDLE_WORKER_TOKEN must each be 32+ characters")


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

        def do_GET(self):
            if self.path == "/healthz":
                self._json(200, {
                    "service": "Runner Riddle BS0:0",
                    "address": ROOT_ADDRESS,
                    "status": "ready",
                    "queue": service.inbox.stats(),
                    "range_manifest_present": service.range_manifest_path.exists(),
                    "route_cache_present": service.route_cache_path.exists(),
                    "live_route_commit": False,
                })
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

                if self.path == "/v1/riddle/routes/resolve":
                    if not service.route_cache_path.exists() or len(service.route_key) < 32:
                        self._json(503, {"error": "signed master route cache is not installed"})
                        return
                    cache = MasterRouteCache.load(service.route_cache_path, service.route_key)
                    packet = cache.resolve(str(body["address"]))
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
            except (KeyError, TypeError, ValueError, InboxError, PolicyError, RouteError) as exc:
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
