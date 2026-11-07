"""Standard-library HTTP ingress for the stable point-0 runner route.

The adapter is a thin transport around :class:`runner_riddle.point0_bridge.Point0Router`.
It parses a bounded JSON frame or a bounded binary word payload, authenticates
the caller through the existing :class:`runner_riddle.wave_service.WaveService`
bearer-token style, submits the frame through the router, and renders the
result with the stable point-0 route plus non-address evidence.

It never accepts a runner slot or epoch from a client, never performs host
mathematics, and never duplicates the bridge's framing or the scheduler's
active-slot decision.  The pure :meth:`Point0HttpAdapter.handle` method is the
injectable core used by tests without opening a socket.  :class:`Point0HttpServer`
is an optional loopback-only lifecycle wrapper.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import math
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from .point0_bridge import (
    BinaryEnvelope,
    ExecutorResultError,
    InactiveSlotError,
    MAX_FRAME_WORDS,
    NanFrame,
    NoActiveSlotError,
    POINT_ZERO_ADDRESS,
    POINT_ZERO_WIRE,
    Point0Bridge,
    Point0BridgeError,
    RouterBusyError,
    StaleEnvelopeError,
    WORD_BYTES,
)
from .wave_ring_scheduler import JAHS_NAME, JAHS_SEAL
from .wave_service import WaveServiceAuthError

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 0
MAX_BODY_BYTES = 1_048_576
# Alias matching the wave HTTP adapter's request-size naming.
MAX_REQUEST_BYTES = MAX_BODY_BYTES
MAX_WORDS = MAX_FRAME_WORDS
MAX_PAYLOAD_BYTES = MAX_WORDS * WORD_BYTES
MAX_ERROR_CHARS = 320
MAX_NAME_CHARS = 128

POINT0_PATH = "/v1/point0"
POINT_ZERO_IDENTITY = "BS0:0"
SCHEMA = "nanrouter.point0-http.v1"

JSON_CONTENT_TYPE = "application/json"
BINARY_CONTENT_TYPE = "application/octet-stream"
_BINARY_CONTENT_TYPES = frozenset(
    {
        BINARY_CONTENT_TYPE,
        "application/vnd.nan16.words",
        "application/x-nan16",
    }
)
_WWW_AUTHENTICATE = 'Bearer realm="wave"'
_ALL_ROLES = ("submit", "worker", "admin")
_DEFAULT_ROLE = "submit"
_MAX_DRAIN_BYTES = 65_536
_MAX_UINT64 = (1 << 64) - 1

# Direct slot routes are never part of the point-0 ingress.  These markers are
# only used for early HTTP path/target rejection; body routes are normalized
# and rejected by NanFrame itself.
_FORBIDDEN_ROUTE_MARKERS = ("/R", "NANROUTER-")
_ALLOWED_JSON_FIELDS = frozenset({"route", "request_id", "words"})
_FORBIDDEN_CLIENT_FIELDS = frozenset(
    {
        "active_slot",
        "alias",
        "epoch",
        "runner",
        "runner_id",
        "slot",
        "slot_id",
    }
)
_FORBIDDEN_CLIENT_HEADERS = (
    "x-nan-active-slot",
    "x-nan-alias",
    "x-nan-epoch",
    "x-nan-runner",
    "x-nan-slot",
)


class Point0HttpError(Exception):
    """A bounded error the adapter can render without exposing internals."""

    def __init__(self, status: int, message: str, *,
                 headers: dict[str, str] | None = None,
                 retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.headers = dict(headers or {})
        self.retryable = retryable


@dataclass(frozen=True)
class Point0HttpResponse:
    """A transport-neutral response produced by the injectable adapter core."""

    status: int
    headers: dict[str, str]
    body: bytes

    def header(self, name: str, default: Any = None) -> Any:
        lower = str(name).lower()
        for key, value in self.headers.items():
            if str(key).lower() == lower:
                return value
        return default

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))


def _bounded_text(value: Any, limit: int = MAX_ERROR_CHARS) -> str:
    """Collapse and truncate text so every rendered error has a fixed bound."""
    text = " ".join(str(value).split())
    if len(text) > limit:
        text = text[: max(1, limit - 3)] + "..."
    return text or "request failed"


def _reject_json_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON number is not supported: {value}")


def _parse_json_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite JSON number is not supported")
    return result


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _header_values(headers: Any, name: str) -> list[str]:
    """Return every value for *name* from a mapping, message, or pair list."""
    if headers is None:
        return []
    lower = name.lower()
    if hasattr(headers, "get_all"):
        try:
            values = headers.get_all(name)
        except (KeyError, AttributeError):
            values = None
        if values is None:
            value = headers.get(name)
            return [] if value is None else [str(value)]
        return [str(value) for value in values]
    if isinstance(headers, Mapping):
        values: list[str] = []
        for key, value in headers.items():
            if str(key).lower() != lower:
                continue
            if isinstance(value, (list, tuple)):
                values.extend(str(item) for item in value)
            else:
                values.append(str(value))
        return values
    try:
        return [
            str(value)
            for key, value in headers
            if str(key).lower() == lower
        ]
    except (TypeError, ValueError):
        return []


def _has_header(headers: Any, name: str) -> bool:
    return bool(_header_values(headers, name))


def _single_header(headers: Any, name: str, *,
                   required: bool = False) -> str | None:
    values = _header_values(headers, name)
    if not values:
        if required:
            raise Point0HttpError(400, f"{name} is required")
        return None
    if len(values) != 1:
        raise Point0HttpError(
            400, f"exactly one {name} header is required"
        )
    return values[0]


def _content_type(headers: Any) -> str:
    value = _single_header(headers, "content-type")
    if value is None:
        return ""
    return value.split(";", 1)[0].strip().lower()


def _bearer_token(headers: Any) -> str:
    values = _header_values(headers, "authorization")
    if not values:
        raise Point0HttpError(
            401, "bearer token is required",
            headers={"WWW-Authenticate": _WWW_AUTHENTICATE},
        )
    if len(values) != 1:
        raise Point0HttpError(
            401, "invalid bearer token",
            headers={"WWW-Authenticate": _WWW_AUTHENTICATE},
        )
    header = values[0]
    scheme, separator, credentials = header.partition(" ")
    token = credentials.strip()
    if (
        not separator
        or scheme.lower() != "bearer"
        or not token
        or len(token) > 4096
        or any(char.isspace() for char in token)
    ):
        raise Point0HttpError(
            401, "invalid bearer token",
            headers={"WWW-Authenticate": _WWW_AUTHENTICATE},
        )
    return token


def _jahs_evidence(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Copy only the safe JAHS seal fields out of a scheduler snapshot."""
    jahs = snapshot.get("jahs")
    if not isinstance(jahs, Mapping) or jahs.get("seal") != JAHS_SEAL:
        raise Point0HttpError(
            503,
            "runner ring handoff seal is missing; JAHS gate not satisfied",
        )
    name = jahs.get("name")
    if not isinstance(name, str) or not name.strip():
        name = JAHS_NAME
    epoch = jahs.get("epoch")
    if not _is_int(epoch):
        epoch = snapshot.get("epoch")
    return {
        "seal": JAHS_SEAL,
        "name": _bounded_text(name, MAX_NAME_CHARS),
        "epoch": epoch if _is_int(epoch) else None,
    }


def _error_response(status: int, message: str, *,
                    headers: dict[str, str] | None = None,
                    retryable: bool = False) -> Point0HttpResponse:
    payload: dict[str, Any] = {"error": _bounded_text(message)}
    if retryable:
        payload["retryable"] = True
    raw = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    response_headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }
    response_headers.update(headers or {})
    return Point0HttpResponse(status, response_headers, raw)


class Point0HttpAdapter:
    """Bounded point-0 HTTP request handler independent of any live socket.

    ``router`` must be a :class:`~runner_riddle.point0_bridge.Point0Router` or a
    compatible object exposing ``submit(frame)`` and ``scheduler.snapshot()``.
    ``service`` supplies the existing ``WaveService._authorize`` bearer-token
    check; the adapter keeps no copy of the configured tokens.
    """

    def __init__(
        self,
        router: Any,
        service: Any,
        *,
        role: str = _DEFAULT_ROLE,
        max_body_bytes: int = MAX_BODY_BYTES,
        max_words: int = MAX_WORDS,
        bridge: Point0Bridge | None = None,
    ) -> None:
        if not callable(getattr(router, "submit", None)):
            raise TypeError("router must expose submit(frame)")
        scheduler = getattr(router, "scheduler", None)
        if scheduler is None or not callable(getattr(scheduler, "snapshot", None)):
            raise TypeError("router must expose scheduler.snapshot()")
        if not callable(getattr(service, "_authorize", None)):
            raise TypeError("service must expose the WaveService _authorize check")
        if role not in _ALL_ROLES:
            raise ValueError(f"role must be one of {_ALL_ROLES}")
        if not _is_int(max_body_bytes) or not 1 <= max_body_bytes <= MAX_BODY_BYTES:
            raise ValueError(
                f"max_body_bytes must be in 1..{MAX_BODY_BYTES}"
            )
        if not _is_int(max_words) or not 0 <= max_words <= MAX_WORDS:
            raise ValueError(f"max_words must be in 0..{MAX_WORDS}")

        if bridge is None:
            bridge = getattr(router, "bridge", None)
        if bridge is None:
            bridge = Point0Bridge(max_words=max_words)
        if not isinstance(bridge, Point0Bridge):
            raise TypeError("bridge must be a Point0Bridge")
        if max_words > bridge.max_words:
            raise ValueError(
                "max_words must not exceed the router bridge's max_words"
            )

        self.router = router
        self.service = service
        self.scheduler = scheduler
        self.role = role
        self.max_body_bytes = max_body_bytes
        self.max_words = max_words
        self.max_payload_bytes = max_words * WORD_BYTES
        self.bridge = bridge

    def __repr__(self) -> str:
        return (
            f"Point0HttpAdapter(route={POINT_ZERO_ADDRESS!r}, "
            f"role={self.role!r}, max_body_bytes={self.max_body_bytes}, "
            f"max_words={self.max_words})"
        )

    # -- Injectable request entry point --------------------------------------

    def handle(
        self,
        method: str,
        path: str,
        headers: Any = None,
        body: bytes = b"",
    ) -> Point0HttpResponse:
        """Handle one request and return a transport-neutral response."""
        try:
            return self._handle(method, path, headers, body)
        except Point0HttpError as exc:
            return _error_response(
                exc.status, exc.message,
                headers=exc.headers, retryable=exc.retryable,
            )
        except StaleEnvelopeError as exc:
            return _error_response(409, _bounded_text(str(exc)))
        except InactiveSlotError as exc:
            return _error_response(409, _bounded_text(str(exc)))
        except NoActiveSlotError as exc:
            return _error_response(503, _bounded_text(str(exc)))
        except RouterBusyError as exc:
            return _error_response(
                429, _bounded_text(str(exc)),
                headers={"Retry-After": "1"}, retryable=True,
            )
        except ExecutorResultError:
            return _error_response(
                502, "active runner returned an invalid result"
            )
        except Point0BridgeError as exc:
            return _error_response(400, _bounded_text(str(exc)))
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            return _error_response(400, _bounded_text(str(exc)))
        except Exception:
            return _error_response(500, "internal service error")

    # -- Request pipeline ----------------------------------------------------

    def _handle(
        self,
        method: str,
        path: str,
        headers: Any,
        body: bytes,
    ) -> Point0HttpResponse:
        target = str(path)
        if any(marker in target for marker in _FORBIDDEN_ROUTE_MARKERS):
            raise Point0HttpError(
                400,
                "direct runner-slot routes are not accepted; "
                f"use the stable point-0 route {POINT_ZERO_ADDRESS!r}",
            )
        if urlsplit(target).path != POINT0_PATH:
            raise Point0HttpError(404, "not found")
        if str(method).upper() != "POST":
            raise Point0HttpError(
                405, "method not allowed", headers={"Allow": "POST"}
            )

        token = _bearer_token(headers)
        self._authenticate(token)
        if not isinstance(body, (bytes, bytearray, memoryview)):
            raise Point0HttpError(400, "request body must be bytes")
        body = bytes(body)
        length = self._body_length(headers, body)
        frame, binary = self._request_frame(headers, body, length)
        result = self.router.submit(frame)
        jahs = self._response_evidence(result)
        if binary:
            return self._binary_response(result, jahs)
        return self._json_response(result, jahs)

    def _authenticate(self, token: str) -> None:
        try:
            self.service._authorize(token, (self.role,))
            return
        except WaveServiceAuthError:
            pass
        if self._token_is_known(token):
            raise Point0HttpError(
                403, "bearer token does not hold the required role"
            )
        raise Point0HttpError(
            401, "invalid bearer token",
            headers={"WWW-Authenticate": _WWW_AUTHENTICATE},
        )

    def _token_is_known(self, token: str) -> bool:
        try:
            # Reuse the facade's constant-time role comparisons without
            # keeping a second copy of any token or digest.
            self.service._authorize(token, _ALL_ROLES)
            return True
        except WaveServiceAuthError:
            return False

    def _body_length(self, headers: Any, body: bytes) -> int:
        if _has_header(headers, "transfer-encoding"):
            raise Point0HttpError(
                400, "chunked request bodies are not supported"
            )
        encodings = _header_values(headers, "content-encoding")
        if len(encodings) > 1:
            raise Point0HttpError(
                400, "exactly one Content-Encoding is allowed"
            )
        if encodings and encodings[0].strip().lower() not in ("", "identity"):
            raise Point0HttpError(400, "Content-Encoding is not supported")

        lengths = _header_values(headers, "content-length")
        if len(lengths) != 1:
            raise Point0HttpError(
                400, "exactly one Content-Length is required"
            )
        raw_length = lengths[0].strip()
        if not raw_length.isascii() or not raw_length.isdigit():
            raise Point0HttpError(400, "invalid Content-Length")
        length = int(raw_length)
        if length > self.max_body_bytes:
            raise Point0HttpError(
                400, f"request body exceeds {self.max_body_bytes} bytes"
            )
        if length != len(body):
            raise Point0HttpError(
                400, "request body length does not match Content-Length"
            )
        return length

    def _request_frame(
        self,
        headers: Any,
        body: bytes,
        length: int,
    ) -> tuple[NanFrame, bool]:
        content_type = _content_type(headers)
        if content_type == JSON_CONTENT_TYPE:
            if length < 1:
                raise Point0HttpError(400, "request body is required")
            return self._json_frame(body), False
        if content_type in _BINARY_CONTENT_TYPES:
            return self._binary_frame(headers, body, length), True
        raise Point0HttpError(
            400,
            "Content-Type must be application/json or "
            "application/octet-stream",
        )

    def _json_frame(self, body: bytes) -> NanFrame:
        try:
            text = body.decode("utf-8")
            value = json.loads(
                text,
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
                parse_float=_parse_json_float,
            )
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            raise Point0HttpError(
                400, "request must be valid UTF-8 JSON"
            ) from exc
        if not isinstance(value, dict):
            raise Point0HttpError(400, "request JSON must be an object")

        if any(name in value for name in _FORBIDDEN_CLIENT_FIELDS):
            raise Point0HttpError(
                400,
                "client-supplied routing evidence is not accepted; "
                "point-0 selects the active slot",
            )
        if set(value) - _ALLOWED_JSON_FIELDS:
            raise Point0HttpError(400, "request contains unsupported fields")
        if "request_id" not in value:
            raise Point0HttpError(400, "request_id is required")
        if "words" not in value:
            raise Point0HttpError(400, "words is required")

        words = value["words"]
        if not isinstance(words, list):
            raise Point0HttpError(
                400, "words must be an array of unsigned 64-bit integers"
            )
        if len(words) > self.max_words:
            raise Point0HttpError(
                400,
                f"frame has {len(words)} words; limit is {self.max_words}",
            )
        route = value.get("route", POINT_ZERO_ADDRESS)
        try:
            return NanFrame(
                words=words,
                request_id=value["request_id"],
                route=route,
            )
        except Point0BridgeError as exc:
            raise Point0HttpError(400, _bounded_text(str(exc))) from exc

    def _binary_frame(
        self,
        headers: Any,
        body: bytes,
        length: int,
    ) -> NanFrame:
        if any(_has_header(headers, name) for name in _FORBIDDEN_CLIENT_HEADERS):
            raise Point0HttpError(
                400,
                "client-supplied routing evidence is not accepted; "
                "point-0 selects the active slot",
            )
        if length % WORD_BYTES:
            raise Point0HttpError(
                400,
                "binary payload must be a whole number of 64-bit words",
            )
        if length > self.max_payload_bytes:
            raise Point0HttpError(
                400,
                f"binary payload exceeds {self.max_payload_bytes} bytes "
                f"({self.max_words} words)",
            )

        request_id = self._uint64_header(headers, "x-nan-request-id")
        route = _single_header(headers, "x-nan-route")
        if route is None or not route.strip():
            route = POINT_ZERO_ADDRESS
        if length:
            try:
                envelope = BinaryEnvelope.create(
                    request_id=request_id,
                    payload=body,
                    active_slot=0,
                    epoch=0,
                )
                words = self.bridge.decode(envelope).words
            except Point0BridgeError as exc:
                raise Point0HttpError(
                    400, _bounded_text(str(exc))
                ) from exc
        else:
            words = ()
        try:
            return NanFrame(
                words=words,
                request_id=request_id,
                route=route,
            )
        except Point0BridgeError as exc:
            raise Point0HttpError(400, _bounded_text(str(exc))) from exc

    def _uint64_header(self, headers: Any, name: str) -> int:
        value = _single_header(headers, name, required=True)
        text = (value or "").strip()
        if not text.isascii() or not text.isdigit():
            raise Point0HttpError(
                400, f"{name} must be an unsigned 64-bit integer"
            )
        number = int(text)
        if number > _MAX_UINT64:
            raise Point0HttpError(
                400, f"{name} must be an unsigned 64-bit integer"
            )
        return number

    # -- Evidence and response rendering ------------------------------------

    def _response_evidence(self, result: Any) -> dict[str, Any]:
        if result.word_count > self.max_words:
            raise Point0HttpError(
                502,
                "active runner result exceeds the configured word bound",
            )
        scheduler = getattr(self.router, "scheduler", self.scheduler)
        try:
            snapshot = scheduler.snapshot()
        except Exception as exc:
            raise Point0HttpError(
                503, "scheduler snapshot is unavailable"
            ) from exc
        if not isinstance(snapshot, Mapping):
            raise Point0HttpError(503, "scheduler snapshot is unavailable")
        jahs = _jahs_evidence(snapshot)
        if snapshot.get("stale"):
            raise Point0HttpError(
                409, "runner ring heartbeat is stale; retry"
            )
        if (
            snapshot.get("epoch") != result.epoch
            or snapshot.get("active_slot") != result.active_slot
        ):
            raise Point0HttpError(
                409, "runner ring advanced during the request; retry"
            )
        return jahs

    def _json_response(
        self,
        result: Any,
        jahs: dict[str, Any],
    ) -> Point0HttpResponse:
        payload = {
            "schema": SCHEMA,
            "route": POINT_ZERO_ADDRESS,
            "point_zero": POINT_ZERO_IDENTITY,
            "wire": POINT_ZERO_WIRE,
            "request_id": result.request_id,
            "words": list(result.words),
            "word_count": result.word_count,
            "active_slot": result.active_slot,
            "epoch": result.epoch,
            "jahs": jahs,
            "request_digest": result.request_digest.hex(),
            "result_digest": result.result_digest.hex(),
        }
        raw = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-NaN-Route": POINT_ZERO_ADDRESS,
            "X-NaN-Wire": POINT_ZERO_WIRE,
            "X-NaN-Request-Id": str(result.request_id),
            "X-NaN-Word-Count": str(result.word_count),
            "X-NaN-Active-Slot": str(result.active_slot),
            "X-NaN-Epoch": str(result.epoch),
            "X-NaN-JAHS": jahs["seal"],
        }
        return Point0HttpResponse(200, headers, raw)

    def _binary_response(
        self,
        result: Any,
        jahs: dict[str, Any],
    ) -> Point0HttpResponse:
        try:
            payload = self.bridge.encode(
                result.frame,
                active_slot=result.active_slot,
                epoch=result.epoch,
            ).payload
        except Point0BridgeError as exc:
            raise Point0HttpError(
                502, f"result is not point-0 binary transport: {exc}"
            ) from exc
        headers = {
            "Content-Type": BINARY_CONTENT_TYPE,
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-NaN-Route": POINT_ZERO_ADDRESS,
            "X-NaN-Wire": POINT_ZERO_WIRE,
            "X-NaN-Request-Id": str(result.request_id),
            "X-NaN-Word-Count": str(result.word_count),
            "X-NaN-Active-Slot": str(result.active_slot),
            "X-NaN-Epoch": str(result.epoch),
            "X-NaN-JAHS": jahs["seal"],
            "X-NaN-Request-Digest": result.request_digest.hex(),
            "X-NaN-Result-Digest": result.result_digest.hex(),
        }
        return Point0HttpResponse(200, headers, payload)


def make_point0_handler(adapter: Point0HttpAdapter, *,
                        max_body_bytes: int | None = None):
    """Build a bounded ``BaseHTTPRequestHandler`` class bound to *adapter*."""
    if not callable(getattr(adapter, "handle", None)):
        raise TypeError("adapter must expose handle()")
    if max_body_bytes is None:
        max_body_bytes = getattr(adapter, "max_body_bytes", MAX_BODY_BYTES)
    if (
        not _is_int(max_body_bytes)
        or not 1 <= max_body_bytes <= MAX_BODY_BYTES
    ):
        raise ValueError(
            f"max_body_bytes must be in 1..{MAX_BODY_BYTES}"
        )
    adapter_limit = getattr(adapter, "max_body_bytes", max_body_bytes)
    handler_limit = min(max_body_bytes, adapter_limit)

    class Point0RequestHandler(BaseHTTPRequestHandler):
        server_version = "NaNROUTER-Point0/1"
        sys_version = ""
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            # Request lines and headers can contain credentials; emit nothing.
            return

        def log_error(self, fmt: str, *args: Any) -> None:
            return

        def setup(self) -> None:
            super().setup()
            try:
                self.connection.settimeout(15.0)
            except OSError:
                pass

        def send_error(self, code: int, message: str | None = None,
                       explain: str | None = None) -> None:
            # Never let the default HTML page echo the raw request line.
            text = self.responses.get(int(code), ("request failed",))[0]
            self._send(_error_response(int(code), _bounded_text(text)))

        def _discard_body(self, length: int) -> None:
            remaining = length
            while remaining > 0:
                try:
                    chunk = self.rfile.read(min(65_536, remaining))
                except (OSError, TimeoutError):
                    return
                if not chunk:
                    return
                remaining -= len(chunk)

        def _read_body(self) -> bytes:
            if self.headers.get_all("Transfer-Encoding", []):
                raise Point0HttpError(
                    400, "chunked request bodies are not supported"
                )
            encodings = self.headers.get_all("Content-Encoding", [])
            if len(encodings) > 1:
                raise Point0HttpError(
                    400, "exactly one Content-Encoding is allowed"
                )
            if (
                encodings
                and encodings[0].strip().lower() not in ("", "identity")
            ):
                raise Point0HttpError(
                    400, "Content-Encoding is not supported"
                )

            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1:
                raise Point0HttpError(
                    400, "exactly one Content-Length is required"
                )
            raw_length = lengths[0].strip()
            if not raw_length.isascii() or not raw_length.isdigit():
                raise Point0HttpError(400, "invalid Content-Length")
            length = int(raw_length)
            if length > handler_limit:
                if length <= handler_limit + _MAX_DRAIN_BYTES:
                    self._discard_body(length)
                raise Point0HttpError(
                    400, f"request body exceeds {handler_limit} bytes"
                )
            if length == 0:
                return b""
            try:
                raw = self.rfile.read(length)
            except (OSError, TimeoutError) as exc:
                raise Point0HttpError(
                    400, "request body could not be read"
                ) from exc
            if len(raw) != length:
                raise Point0HttpError(400, "request body is truncated")
            return raw

        def _send(self, response: Point0HttpResponse) -> None:
            try:
                self.send_response(response.status)
                for name, value in response.headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(response.body)))
                self.send_header("Connection", "close")
                self.close_connection = True
                self.end_headers()
                if getattr(self, "command", None) == "HEAD":
                    return
                try:
                    self.wfile.write(response.body)
                except (BrokenPipeError, ConnectionResetError):
                    self.close_connection = True
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True

        def _dispatch(self, method: str, *, with_body: bool) -> None:
            try:
                body = self._read_body() if with_body else b""
                response = adapter.handle(method, self.path, self.headers, body)
            except Point0HttpError as exc:
                response = _error_response(
                    exc.status, exc.message,
                    headers=exc.headers, retryable=exc.retryable,
                )
            except Exception:
                response = _error_response(500, "internal service error")
            self._send(response)

        def do_GET(self) -> None:
            self._dispatch("GET", with_body=False)

        def do_HEAD(self) -> None:
            self._dispatch("HEAD", with_body=False)

        def do_POST(self) -> None:
            self._dispatch("POST", with_body=True)

        def do_PUT(self) -> None:
            self._dispatch("PUT", with_body=False)

        def do_PATCH(self) -> None:
            self._dispatch("PATCH", with_body=False)

        def do_DELETE(self) -> None:
            self._dispatch("DELETE", with_body=False)

        def do_OPTIONS(self) -> None:
            self._dispatch("OPTIONS", with_body=False)

    return Point0RequestHandler


class Point0HttpServer:
    """Optional bounded lifecycle wrapper for the point-0 HTTP adapter.

    The default listener is loopback on an ephemeral port.  The pure
    :meth:`Point0HttpAdapter.handle` core does not need this class.
    """

    def __init__(self, adapter: Point0HttpAdapter,
                 host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, *,
                 max_body_bytes: int | None = None) -> None:
        if not callable(getattr(adapter, "handle", None)):
            raise TypeError("adapter must expose handle()")
        if max_body_bytes is None:
            max_body_bytes = getattr(adapter, "max_body_bytes", MAX_BODY_BYTES)
        if (
            not _is_int(max_body_bytes)
            or not 1 <= max_body_bytes <= MAX_BODY_BYTES
        ):
            raise ValueError(
                f"max_body_bytes must be in 1..{MAX_BODY_BYTES}"
            )
        self.adapter = adapter
        self.host = host
        self._requested_port = port
        self.max_body_bytes = min(
            max_body_bytes,
            getattr(adapter, "max_body_bytes", max_body_bytes),
        )
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()

    def __repr__(self) -> str:
        return (
            f"Point0HttpServer(host={self.host!r}, port={self.port}, "
            f"running={self.running})"
        )

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def httpd(self) -> ThreadingHTTPServer | None:
        return self._httpd

    @property
    def server(self) -> ThreadingHTTPServer | None:
        return self._httpd

    @property
    def thread(self) -> threading.Thread | None:
        return self._thread

    @property
    def port(self) -> int:
        if self._httpd is not None:
            return int(self._httpd.server_port)
        return self._requested_port

    @property
    def address(self) -> tuple[str, int]:
        if self._httpd is not None:
            host, port = self._httpd.server_address[:2]
            return str(host), int(port)
        return self.host, self._requested_port

    @property
    def server_address(self) -> tuple[str, int]:
        return self.address

    @property
    def base_url(self) -> str:
        if self._httpd is None:
            raise RuntimeError("point-0 HTTP server is not running")
        host, port = self.address
        display_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
        return f"http://{display_host}:{port}"

    @property
    def url(self) -> str:
        return self.base_url

    def start(self, host: str | None = None,
              port: int | None = None) -> "Point0HttpServer":
        """Bind and serve on a background daemon thread; returns ``self``."""
        with self._lock:
            if self._httpd is not None:
                raise RuntimeError("point-0 HTTP server is already running")
            bind_host = self.host if host is None else host
            bind_port = self._requested_port if port is None else port
            httpd = ThreadingHTTPServer(
                (bind_host, bind_port),
                make_point0_handler(
                    self.adapter, max_body_bytes=self.max_body_bytes
                ),
            )
            httpd.daemon_threads = True
            thread = threading.Thread(
                target=httpd.serve_forever,
                args=(0.05,),
                name=f"point0-http-{httpd.server_port}",
                daemon=True,
            )
            try:
                thread.start()
            except Exception:
                httpd.server_close()
                raise
            self.host = bind_host
            self._httpd = httpd
            self._thread = thread
            return self

    def stop(self) -> None:
        """Stop serving, close the listener, and join the worker thread."""
        with self._lock:
            httpd = self._httpd
            thread = self._thread
            self._httpd = None
            self._thread = None
        if httpd is None:
            return
        if thread is not None and thread.is_alive():
            httpd.shutdown()
        httpd.server_close()
        if thread is not None:
            thread.join(timeout=5)

    def __enter__(self) -> "Point0HttpServer":
        return self.start()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        self.stop()
        return False


__all__ = [
    "BINARY_CONTENT_TYPE",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "JAHS_SEAL",
    "JSON_CONTENT_TYPE",
    "MAX_BODY_BYTES",
    "MAX_FRAME_WORDS",
    "MAX_PAYLOAD_BYTES",
    "MAX_REQUEST_BYTES",
    "MAX_WORDS",
    "POINT0_PATH",
    "POINT_ZERO_ADDRESS",
    "POINT_ZERO_IDENTITY",
    "POINT_ZERO_WIRE",
    "Point0HttpAdapter",
    "Point0HttpError",
    "Point0HttpResponse",
    "Point0HttpServer",
    "SCHEMA",
    "WORD_BYTES",
    "make_point0_handler",
]
