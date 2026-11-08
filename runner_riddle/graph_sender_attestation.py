"""Detached Ed25519 sender attestation for a committed graph revision.

This module only prepares/signs a previously computed read projection. The
private key is injected by a trusted router owner; it is never loaded from
request data, logged or persisted here. This is not native MTH execution,
evidence validity, anti-replay admission, or canonical learning promotion.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import time

SCHEMA = "nanrouter.graph-sender-attestation/1"
_DOMAIN = b"nanrouter.graph-sender-ed25519/1\0"
_COMMIT_DOMAIN = b"nanrouter.nan-layer-commitment/1\0"
_HEADER = (
    "schema", "topology_sha256", "parent_root_sha256",
    "chart_generation", "total_edges", "candidate_edges",
    "retracted_edges", "layer_counts", "state_sha256", "history_sha256",
)
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_NONCE = re.compile(r"[0-9a-f]{32}\Z")
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,160}\Z")


class GraphSenderAttestationError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sign_graph_attestation(page, *, router_id, key_id, private_key,
                           nonce=None, issued_at=None):
    """Sign the full state+history commitment with a configured Ed25519 key.

    The consumer must independently verify the actual pages and pin the
    public key to a known router identity. A signed header alone is not
    evidence that any graph edge or MTH kernel was valid.
    """
    if (type(page) is not dict
            or any(k not in page for k in _HEADER)
            or page.get("schema") != "nanrouter.nan-layer-master-commitment/1"
            or page.get("snapshot_consistent") is not True
            or page.get("signed_by_router") is not False
            or page.get("native_mth_receipt") is not False
            or page.get("mathematical_truth_promoted") is not False
            or type(page.get("chart_generation")) is not int
            or page["chart_generation"] < 0
            or not all(type(page.get(k)) is str and _SHA.fullmatch(page[k])
                       for k in ("topology_sha256", "parent_root_sha256",
                                 "state_sha256", "history_sha256",
                                 "graph_commitment_sha256"))):
        raise GraphSenderAttestationError("invalid or overclaimed graph commitment")
    header = {k: page[k] for k in _HEADER}
    try:
        checksum = hashlib.sha256(_COMMIT_DOMAIN + canonical(header)).hexdigest()
    except (TypeError, ValueError) as exc:
        raise GraphSenderAttestationError("invalid graph header encoding") from exc
    if checksum != page["graph_commitment_sha256"]:
        raise GraphSenderAttestationError("graph commitment checksum mismatch")
    if (type(router_id) is not str or _ID.fullmatch(router_id) is None
            or type(key_id) is not str or _ID.fullmatch(key_id) is None):
        raise GraphSenderAttestationError("invalid sender or key identity")
    if nonce is None:
        nonce = secrets.token_hex(16)
    if issued_at is None:
        issued_at = int(time.time())
    if (type(nonce) is not str or _NONCE.fullmatch(nonce) is None
            or type(issued_at) is not int or issued_at < 1):
        raise GraphSenderAttestationError("invalid nonce or issue timestamp")
    if not callable(getattr(private_key, "sign", None)):
        raise GraphSenderAttestationError("trusted Ed25519 signer required")
    body = dict(schema=SCHEMA, router_id=router_id, key_id=key_id,
                graph_commitment_sha256=checksum,
                topology_sha256=page["topology_sha256"],
                parent_root_sha256=page["parent_root_sha256"],
                chart_generation=page["chart_generation"],
                history_sha256=page["history_sha256"],
                nonce=nonce, issued_at=issued_at)
    signature = private_key.sign(_DOMAIN + canonical(body))
    if type(signature) is not bytes or len(signature) != 64:
        raise GraphSenderAttestationError("Ed25519 signer returned invalid signature")
    return {**body, "signature_hex": signature.hex(),
            "signed_by_router": True, "native_mth_receipt": False,
            "mathematical_truth_promoted": False}


__all__ = ("GraphSenderAttestationError", "sign_graph_attestation", "SCHEMA")
