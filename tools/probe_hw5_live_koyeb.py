#!/usr/bin/env python3
"""Read-only live NANNET Koyeb HW5:0 portal probe.

This intentionally does NOT submit frames or mutate corpus state. It reports
real remote HTTP status and ring identity, not a CI simulation.
"""
from __future__ import annotations
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = "https://nannet.apps.mistral.run"
PATHS = ("/healthz", "/v1/issuer", "/v1/ring/status", "/v1/ring/points")


def one(path: str) -> dict:
    req = Request(BASE + path, headers={"Accept": "application/json",
                                        "User-Agent": "nanrouter-hw5-live-probe/1.0"})
    token = os.environ.get("NANROUTER_RING_TOKEN", "")
    if token and path.startswith("/v1/ring/"):
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urlopen(req, timeout=15) as res:
            code = res.status
            raw = res.read(524289)
        if len(raw) > 524288:
            return {"path": path, "http": code, "error": "oversized_response"}
        obj = json.loads(raw)
    except HTTPError as err:
        return {"path": path, "http": err.code, "error": "http_denied_or_failed"}
    except (URLError, TimeoutError, ValueError, OSError) as err:
        return {"path": path, "error": err.__class__.__name__}
    if not isinstance(obj, dict):
        return {"path": path, "http": code, "error": "invalid_json_object"}
    allowed = {
        "/healthz": ("status", "nannet_authority", "bsr_registered", "runner_ring_node"),
        "/v1/issuer": ("schema", "issuer_public_key"),
        "/v1/ring/status": ("schema", "ring_endpoint", "active", "phase", "slot", "epoch", "errors"),
        "/v1/ring/points": ("schema", "ring_endpoint", "active", "registered", "queued", "pending"),
    }
    answer = {"path": path, "http": code}
    for k in allowed[path]:
        if k in obj:
            v = obj[k]
            if k == "issuer_public_key":
                # Do not expose issuer fingerprint in a separate log.
                answer["issuer_public_key_present"] = bool(v)
            elif isinstance(v, (str, bool, int, float)) and len(str(v)) < 200:
                answer[k] = v
    if path == "/v1/ring/status" and isinstance(obj.get("fabric"), dict):
        fab = obj["fabric"]
        for k in ("registered", "queued", "pending", "received", "delivered", "rejected"):
            if isinstance(fab.get(k), int):
                answer["fabric_" + k] = fab[k]
    if path == "/v1/ring/points" and isinstance(obj.get("fabric"), dict):
        fab = obj["fabric"]
        for k in ("registered", "queued", "pending", "received", "delivered", "rejected"):
            if isinstance(fab.get(k), int):
                answer["fabric_" + k] = fab[k]
    return answer


if __name__ == "__main__":
    reports = [one(p) for p in PATHS]
    for r in reports:
        print("HW5_LIVE_PORTAL_PROBE", json.dumps(r, sort_keys=True), flush=True)
    healthy = reports[0].get("http") == 200
    ring_live = reports[2].get("http") == 200 and reports[2].get("ring_endpoint") == "HW5:0"
    print("HW5_LIVE_PROBE_SUMMARY", json.dumps({
        "portal_http_ready": healthy,
        "hw5_ring_identity_verified": ring_live,
        "ring_auth_configured_in_runner": bool(os.environ.get("NANROUTER_RING_TOKEN")),
        "read_only": True, "corpus_uploaded": False,
    }, sort_keys=True), flush=True)
    raise SystemExit(0 if healthy and ring_live else 2)
