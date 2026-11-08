"""True single-container Koyeb smoke: one public NaNROUTER BS0:0 entrypoint.

Runs *inside* disposable router-owned image; source and keys are ephemeral.
Never execute against an existing production NANNET issuer or persistent DB.
"""
import base64
import json
import os
import secrets
import sys
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from nanlmind_nannet.auth import _unb64, sign_request
from nanlmind_nannet.crypto_compat import Ed25519PrivateKey, serialization
from nanlmind_nannet.pairing import PairingAuthority

BASE = "http://127.0.0.1:8080"


def post(path, body, token=None, private=None, expected=200):
    raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if private:
        signed = sign_request(private, "POST", path, raw)
        headers.update({
            "X-NANNET-Timestamp": str(signed["timestamp"]),
            "X-NANNET-Nonce": signed["nonce"],
            "X-NANNET-Body-SHA256": signed["body_sha256"],
            "X-NANNET-Signature": signed["signature"],
        })
    req = Request(BASE + path, data=raw, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=10) as response:
            status, payload = response.status, json.loads(response.read(2097153))
    except HTTPError as err:
        status, payload = err.code, json.loads(err.read(2097153))
    assert status == expected, (path, status, expected, payload)
    return payload


def pair(authority):
    code = authority.create_pairing_code(["hermes:lease", "universe:read"], role="guest")
    installation_id = str(uuid.uuid4())
    private = Ed25519PrivateKey.generate()
    key = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    public = base64.urlsafe_b64encode(key).decode().rstrip("=")
    result = post("/v1/pair", {"pairing_code": code["pairing_code"],
                              "installation_id": installation_id,
                              "public_key": public})
    assert result["installation_id"] == installation_id
    return private, result["token"]


def main():
    with urlopen(BASE + "/healthz", timeout=5) as reply:
        health = json.load(reply)
    assert health["nannet_single_issuer_portal_hosted_by_nanrouter"] is True
    assert health["address"].startswith("nan://")
    assert health["hermes_native_guest_configured"] is True
    assert health["hermes_n16t_separate_guest_pool"] is True
    authority = PairingAuthority(
        Path(os.environ["NANNET_AUTHORITY_DB"]),
        _unb64(os.environ["NANNET_AUTHORITY_MASTER_KEY"]))

    first_priv, first_token = pair(authority)
    opened = post("/v1/hermes/leases/open",
                  {"request_id": "router-koyeb-smoke-open-0001"},
                  token=first_token, private=first_priv)["receipt"]
    assert opened["network_port"] == "BS0:0"
    assert opened["node_point"] == 3, opened
    routed = post("/v1/hermes/leases/resolve",
                  {"receipt": opened, "head_index": 254},
                  token=first_token, private=first_priv)["route"]
    assert routed["native_guest_route_admitted"] is True

    answer = post("/v1/hermes/leases/math", {
        "receipt": opened, "head_index": 254,
        "kernel_id": "mth.u32.add_checked", "a": 7, "b": 9,
    }, token=first_token, private=first_priv)
    assert answer["value_u32"] == 16 and answer["exact"] is True
    assert answer["native_nan16_execution"] is True
    assert answer["model_training_committed"] is False
    assert post("/v1/hermes/leases/resolve",
                {"receipt": opened, "head_index": 255},
                token=first_token, private=first_priv, expected=400)

    second_priv, second_token = pair(authority)
    second = post("/v1/hermes/leases/open",
                  {"request_id": "router-koyeb-smoke-open-0002"},
                  token=second_token, private=second_priv)["receipt"]
    assert second["node_point"] == 6, second
    assert second["universe_id"] != opened["universe_id"]
    answer = post("/v1/hermes/leases/math", {
        "receipt": second, "head_index": 0,
        "kernel_id": "mth.u32.sub_checked", "a": 9, "b": 12,
    }, token=second_token, private=second_priv)
    assert answer["value_u32"] == 0 and answer["exact"] is False
    assert post("/v1/hermes/leases/release",
                {"receipt": second}, token=second_token,
                private=second_priv)["released"]
    assert post("/v1/hermes/leases/release",
                {"receipt": opened}, token=first_token,
                private=first_priv)["released"]

    root = post("/v1/hierarchy/future", {"mc": 0, "bs": 1},
                token=os.environ["RIDDLE_HIERARCHY_ADMIN_TOKEN"])
    assert root["reservation"]["runner_instantiated"] is False
    future = post("/v1/hierarchy/resolve", {
        "address": "nan://GM0:SC0:MC0:BS1:0"
    }, token=os.environ["RIDDLE_HERMES_DELEGATION_TOKEN"])
    assert future["route"]["state"] == "future"
    assert future["route"]["transport_active"] is False
    print("SINGLE PUBLIC NANROUTER KOYEB GUEST + HW2/HW5 + NATIVE MTH + FUTURE BS1 PASS")


if __name__ == "__main__":
    main()
