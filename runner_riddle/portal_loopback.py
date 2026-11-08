"""NaNROUTER public BS0:0 ingress -> private same-container NANNET portal.

Only transport headers and raw bytes cross this boundary. Ed25519 tokens,
nonce checks, issuer continuity and pairing remain inside the original
NANNET portal, which is now a loopback-only *component of NaNROUTER's*
Koyeb image. There is no second public issuer or network ingress.
"""
from __future__ import annotations

import http.client
import re
from urllib.parse import urlsplit

MAX_PORTAL_REQUEST = 2_097_152
MAX_PORTAL_RESPONSE = 2_097_152
_ALLOWED_HEADERS = frozenset({
    "authorization", "content-type", "accept", "idempotency-key",
    "x-nannet-timestamp", "x-nannet-nonce", "x-nannet-body-sha256",
    "x-nannet-signature", "cache-control", "x-nanclock-tick",
})
# These routes already belong to the outer NaNROUTER and must never be
# redirected into the legacy portal's own router proxy.
_ROOT_OWNED = (
    "/v1/riddle", "/v1/hermes/leases", "/v1/hierarchy", "/n16t",
    "/healthz", "/v1/point0",
)


class PortalProxyError(ValueError):
    pass


def is_portal_path(path):
    if not isinstance(path, str) or len(path) > 1024:
        return False
    split = urlsplit(path)
    target = split.path
    if (split.scheme or split.netloc or split.fragment or "\x00" in path
            or "\\" in path or path.startswith("//")
            or not target.startswith("/v1/") or "//" in target):
        return False
    return not any(target == base or target.startswith(base + "/")
                   for base in _ROOT_OWNED)


class PortalLoopbackProxy:
    def __init__(self, port=18085):
        if type(port) is not int or not 1024 <= port <= 65535:
            raise PortalProxyError("invalid internal loopback port")
        self.port = port

    def request(self, method, path, headers, body=b""):
        if method not in ("GET", "POST") or not is_portal_path(path):
            raise PortalProxyError("target is not a public NANNET portal path")
        if not isinstance(body, bytes) or len(body) > MAX_PORTAL_REQUEST:
            raise PortalProxyError("request exceeds bounded router ingress")
        if not isinstance(headers, dict):
            raise PortalProxyError("request headers must be a mapping")
        forwarded = {}
        for key, value in headers.items():
            name = str(key).lower()
            if name in _ALLOWED_HEADERS:
                if not isinstance(value, str) or "\r" in value or "\n" in value:
                    raise PortalProxyError("invalid forwarded header value")
                forwarded[key] = value
        forwarded["Content-Length"] = str(len(body))
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
        try:
            connection.request(method, path, body=body, headers=forwarded)
            response = connection.getresponse()
            data = response.read(MAX_PORTAL_RESPONSE + 1)
            if len(data) > MAX_PORTAL_RESPONSE:
                raise PortalProxyError("private NANNET portal response is too large")
            content_type = response.getheader("Content-Type", "application/json")
            if len(content_type) > 128 or "\r" in content_type or "\n" in content_type:
                raise PortalProxyError("invalid NANNET portal response type")
            return response.status, content_type, data
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            raise PortalProxyError("private NANNET portal is not available") from exc
        finally:
            connection.close()
