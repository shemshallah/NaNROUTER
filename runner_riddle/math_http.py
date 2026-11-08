"""Standard-library HTTP ingress for the math control plane.

The adapter is a thin transport around an existing
:class:`runner_riddle.math_runtime.MathRuntime` and an optional,
caller-supplied execution service.  It parses a bounded JSON request, requires
the JAHS handoff-seal header for link/execute, delegates bearer-token checks to
an existing ``WaveService``-compatible authorizer when one is configured, and
renders only token-free, bounded responses.

It never performs host arithmetic, never prepares an NMP packet, never leases a
runner slot, and never invents execution state.  ``/v1/math/link`` calls the
existing linker through ``MathRuntime.propose``.  ``/v1/math/execute`` delegates
to an optional service object.  :class:`PreparedMathExecutionService` is the
provided wrapper: it is constructed server-side with a
:class:`runner_riddle.math_execution.MathExecutionBridge` and a bounded registry
of already prepared leases, then exposes only opaque handle IDs plus result
metadata to HTTP callers.  Without such a service the route returns a typed
``UNAVAILABLE`` result instead of creating state.

The pure :meth:`MathHttpAdapter.handle` method is the injectable core used by
tests without opening a socket.  :class:`MathHttpServer` is an optional
loopback-only lifecycle wrapper.
"""
from __future__ import annotations

from collections.abc import Mapping
import copy
from dataclasses import dataclass
import hmac
import json
import math
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from .math_execution import (
    MathExecutionBindingError,
    MathExecutionBridge,
    MathExecutionConfigError,
    MathExecutionError,
    MathExecutionGateError,
    MathExecutionLease,
    MathExecutionPlanError,
    MathExecutionRingError,
    MathExecutionStateError,
)
from .math_linker import LinkBounds, LinkError, LinkQuery, parse_ref
from .math_runtime import MathRuntimeError
from .math_store import MathStoreError
from .wave_ring_scheduler import JAHS_SEAL
from .wave_service import WaveServiceAuthError

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 0
MIB = 1_048_576
MAX_BODY_BYTES = 2 * MIB
# Alias matching the other runner-riddle HTTP adapters' request-size naming.
MAX_REQUEST_BYTES = MAX_BODY_BYTES
MAX_ERROR_CHARS = 320
MAX_SNAPSHOT_ID_CHARS = 512
MAX_OPERANDS = 64
MAX_CANDIDATES = 256
MAX_LINK_DEPTH = 8
MAX_LINK_FANOUT = 256
MAX_LINK_FUEL = 65_536
MAX_PREPARED_HANDLES = 256
MAX_HANDLE_ID_CHARS = 128
MAX_RESULT_DIGEST_CHARS = 256
MAX_RESULT_STATUS_CHARS = 128
MAX_OUTPUT_LEAF_ID_CHARS = 512
MAX_EVIDENCE_BYTES = 16_384
MAX_NOW_TICK = 2**63 - 1
_MAX_DRAIN_BYTES = 65_536

HEALTH_PATH = "/v1/math/health"
LINK_PATH = "/v1/math/link"
EXECUTE_PATH = "/v1/math/execute"
SCHEMA = "nanrouter.math-http.v1"
ERROR_SCHEMA = "nanrouter.math-http-error.v1"
JAHS_HEADER = "X-NaN-JAHS"
JSON_CONTENT_TYPE = "application/json"

_ALL_ROLES = ("submit", "worker", "admin")
_DEFAULT_ROLE = "submit"
_WWW_AUTHENTICATE = 'Bearer realm="wave"'
_REDACTED = "[REDACTED]"
_SECRET_KEY_PARTS = (
    "bearer",
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "private_key",
)
_LINK_FIELDS = frozenset(
    {
        "allow_scratch",
        "bounds",
        "goal",
        "max_candidates",
        "mode",
        "objective",
        "operands",
        "query",
        "refs",
        "snapshot_id",
    }
)
_EXECUTE_FIELDS = frozenset(
    {
        "commit",
        "digest",
        "evidence",
        "handle",
        "handle_id",
        "leaf_id",
        "lease",
        "lease_id",
        "now_tick",
        "output",
        "output_digest",
        "output_leaf_id",
        "packet_id",
        "result_digest",
        "result_status",
        "status",
    }
)
_EXECUTE_HANDLE_FIELDS = (
    "handle_id",
    "handle",
    "lease_id",
    "lease",
    "packet_id",
)
_EXECUTE_DIGEST_FIELDS = ("result_digest", "digest", "output_digest")
_EXECUTE_STATUS_FIELDS = ("result_status", "status")
_EXECUTE_OUTPUT_FIELDS = ("output_leaf_id", "leaf_id", "output")
_RED_STATUSES = frozenset(
    {"red", "error", "failed", "unhealthy", "unavailable"}
)
_DEGRADED_STATUSES = frozenset(
    {"amber", "degraded", "idle", "warn", "warning"}
)
_GREEN_STATUSES = frozenset({"green", "healthy", "ok", "ready"})


class MathHttpError(Exception):
    """A bounded, typed error the adapter can render without internals."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        reason: str | None = None,
        headers: dict[str, str] | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.reason = reason
        self.headers = dict(headers or {})
        self.retryable = retryable


@dataclass(frozen=True)
class MathHttpResponse:
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


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


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


def _single_header(
    headers: Any, name: str, *, required: bool = False,
) -> str | None:
    values = _header_values(headers, name)
    if not values:
        if required:
            raise MathHttpError(400, "HEADER_REQUIRED", f"{name} is required")
        return None
    if len(values) != 1:
        raise MathHttpError(
            400, "DUPLICATE_HEADER",
            f"exactly one {name} header is required",
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
        raise MathHttpError(
            401, "UNAUTHORIZED", "bearer token is required",
            headers={"WWW-Authenticate": _WWW_AUTHENTICATE},
        )
    if len(values) != 1:
        raise MathHttpError(
            401, "UNAUTHORIZED", "invalid bearer token",
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
        raise MathHttpError(
            401, "UNAUTHORIZED", "invalid bearer token",
            headers={"WWW-Authenticate": _WWW_AUTHENTICATE},
        )
    return token


def _request_secrets(headers: Any) -> list[str]:
    """Collect caller credentials so they can never be echoed by a response."""
    secrets: list[str] = []
    for value in _header_values(headers, "authorization"):
        secrets.append(value)
        _scheme, separator, credentials = value.partition(" ")
        if separator and credentials.strip():
            secrets.append(credentials.strip())
    for name in ("x-nan-token", "x-math-token"):
        secrets.extend(_header_values(headers, name))
    unique: list[str] = []
    for secret in secrets:
        if secret and secret not in unique:
            unique.append(secret)
    return unique


def _is_secret_key(key: Any) -> bool:
    text = str(key).lower()
    if text.endswith("_digest"):
        # The execution bridge exposes deliberate one-way lease digests.
        return False
    return any(part in text for part in _SECRET_KEY_PARTS)


def _find_secret_key(value: Any) -> str | None:
    """Return the first token-like key found anywhere in a request."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _is_secret_key(key):
                return str(key)
            found = _find_secret_key(item)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for item in value:
            found = _find_secret_key(item)
            if found is not None:
                return found
    return None


def _valid_handle_id(value: Any) -> bool:
    """Accept a compact, non-whitespace prepared handle identifier."""
    return (
        isinstance(value, str)
        and 0 < len(value) <= MAX_HANDLE_ID_CHARS
        and all(
            char.isprintable() and not char.isspace()
            for char in value
        )
    )


def _redact(value: Any, secrets: list[str] | tuple[str, ...]) -> Any:
    """Recursively replace credentials and token-like fields."""
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if _is_secret_key(key):
                result[str(key)] = _REDACTED
            else:
                result[str(key)] = _redact(item, secrets)
        return result
    if isinstance(value, (list, tuple)):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, str):
        text = value
        for secret in secrets:
            if secret and secret in text:
                text = text.replace(secret, _REDACTED)
        return text
    return value


def _json_response(
    status: int,
    payload: Mapping[str, Any],
    secrets: list[str] | tuple[str, ...] = (),
    *,
    headers: dict[str, str] | None = None,
) -> MathHttpResponse:
    safe = _redact(payload, secrets)
    try:
        raw = json.dumps(
            safe,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MathHttpError(
            502,
            "SERVICE_RESULT_INVALID",
            "service result is not JSON-serializable",
        ) from exc
    response_headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "X-NaN-Math-Schema": SCHEMA,
    }
    response_headers.update(headers or {})
    return MathHttpResponse(status, response_headers, raw)


def _error_response(
    status: int,
    code: str,
    message: str,
    *,
    reason: str | None = None,
    headers: dict[str, str] | None = None,
    retryable: bool = False,
    secrets: list[str] | tuple[str, ...] = (),
) -> MathHttpResponse:
    error: dict[str, Any] = {
        "code": code,
        "message": _bounded_text(message),
    }
    if reason:
        error["reason"] = _bounded_text(reason, 128)
    if retryable:
        error["retryable"] = True
    return _json_response(
        status,
        {"schema": ERROR_SCHEMA, "error": error},
        secrets,
        headers=headers,
    )


def _text_field(
    body: Mapping[str, Any],
    name: str,
    *,
    default: Any = None,
    maximum: int = MAX_SNAPSHOT_ID_CHARS,
) -> str | None:
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, str) or not value.strip():
        raise MathHttpError(
            400, "INVALID_REQUEST", f"{name} must be a non-empty string"
        )
    if len(value) > maximum:
        raise MathHttpError(
            400, "INVALID_REQUEST", f"{name} exceeds {maximum} characters"
        )
    return value


def _bool_field(body: Mapping[str, Any], name: str, default: bool = False) -> bool:
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not isinstance(value, bool):
        raise MathHttpError(
            400, "INVALID_REQUEST", f"{name} must be a boolean"
        )
    return value


def _int_field(
    body: Mapping[str, Any],
    name: str,
    *,
    default: Any = None,
    minimum: int = 0,
    maximum: int,
) -> int | None:
    if name not in body or body[name] is None:
        return default
    value = body[name]
    if not _is_int(value):
        raise MathHttpError(
            400, "INVALID_REQUEST", f"{name} must be an integer"
        )
    if value < minimum or value > maximum:
        raise MathHttpError(
            400, "INVALID_REQUEST",
            f"{name} must be between {minimum} and {maximum}",
        )
    return value


def _alias_field(
    body: Mapping[str, Any],
    names: tuple[str, ...],
    label: str,
) -> str | None:
    present = [name for name in names if name in body]
    if len(present) > 1:
        raise MathHttpError(
            400,
            "INVALID_REQUEST",
            f"exactly one of {', '.join(names)} is allowed for {label}",
        )
    return present[0] if present else None


def _bounded_bounds(value: Any) -> LinkBounds:
    if value is not None and not isinstance(value, Mapping):
        raise MathHttpError(
            400, "INVALID_BOUNDS", "bounds must be an object"
        )
    try:
        bounds = LinkBounds.from_value(value)
    except LinkError as exc:
        raise MathHttpError(
            400, "INVALID_BOUNDS", str(exc), reason=exc.code,
        ) from exc
    if bounds.max_depth > MAX_LINK_DEPTH:
        raise MathHttpError(
            400, "INVALID_BOUNDS",
            f"bounds.max_depth exceeds {MAX_LINK_DEPTH}",
        )
    if bounds.max_fanout > MAX_LINK_FANOUT:
        raise MathHttpError(
            400, "INVALID_BOUNDS",
            f"bounds.max_fanout exceeds {MAX_LINK_FANOUT}",
        )
    if bounds.fuel > MAX_LINK_FUEL:
        raise MathHttpError(
            400, "INVALID_BOUNDS",
            f"bounds.fuel exceeds {MAX_LINK_FUEL}",
        )
    return bounds


def _component_status(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    status = value.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip().lower()
    healthy = value.get("healthy")
    if healthy is True:
        return "green"
    if healthy is False:
        return "red"
    return None


def _overall_status(components: Mapping[str, Any]) -> str:
    statuses = {
        status for status in (
            _component_status(value) for value in components.values()
        ) if status is not None
    }
    if statuses & _RED_STATUSES:
        return "red"
    if statuses & _DEGRADED_STATUSES:
        return "degraded"
    if statuses and statuses <= _GREEN_STATUSES:
        return "green"
    return "degraded" if statuses else "green"


class MathHttpAdapter:
    """Bounded math HTTP request handler independent of any live socket.

    ``runtime`` must expose ``propose(...)`` and ``functions.health()``.  The
    optional ``service`` owns any execute route state: it may expose
    ``health()`` and/or ``execute(request)``.  It must be a wrapper object, not
    a bare :class:`MathExecutionBridge`, because the adapter never prepares a
    packet or acquires a lease.  The optional ``auth`` object must expose the
    existing ``WaveService._authorize(token, roles)`` check.
    """

    def __init__(
        self,
        runtime: Any,
        service: Any = None,
        *,
        auth: Any = None,
        role: str = _DEFAULT_ROLE,
        max_body_bytes: int = MAX_BODY_BYTES,
        max_operands: int = MAX_OPERANDS,
    ) -> None:
        if not callable(getattr(runtime, "propose", None)):
            raise TypeError("runtime must expose propose(...)")
        functions = getattr(runtime, "functions", None)
        if functions is None or not callable(getattr(functions, "health", None)):
            raise TypeError("runtime must expose functions.health()")
        if isinstance(service, MathExecutionBridge):
            raise TypeError(
                "service must own a prepared packet/lease; "
                "pass a wrapper object, not a bare MathExecutionBridge"
            )
        if service is not None and not callable(service):
            if not callable(getattr(service, "execute", None)) and not callable(
                getattr(service, "health", None)
            ):
                raise TypeError(
                    "service must expose execute(request) and/or health()"
                )
        if auth is not None and not callable(getattr(auth, "_authorize", None)):
            raise TypeError("auth must expose WaveService _authorize(token, roles)")
        if not isinstance(role, str) or not role:
            raise ValueError("role must be a non-empty string")
        if not _is_int(max_body_bytes) or not 1 <= max_body_bytes <= MAX_BODY_BYTES:
            raise ValueError(
                f"max_body_bytes must be in 1..{MAX_BODY_BYTES}"
            )
        if not _is_int(max_operands) or not 1 <= max_operands <= 1024:
            raise ValueError("max_operands must be in 1..1024")

        self.runtime = runtime
        self.service = service
        self.auth = auth
        self.role = role
        self.max_body_bytes = max_body_bytes
        self.max_operands = max_operands

    def __repr__(self) -> str:
        return (
            f"MathHttpAdapter(role={self.role!r}, "
            f"max_body_bytes={self.max_body_bytes}, "
            f"execute={'yes' if self.execute_available else 'no'})"
        )

    # -- Injectable request entry point --------------------------------------

    def handle(
        self,
        method: str,
        path: str,
        headers: Any = None,
        body: bytes = b"",
    ) -> MathHttpResponse:
        """Handle one request and return a transport-neutral response."""
        secrets = _request_secrets(headers)
        try:
            return self._handle(method, path, headers, body, secrets)
        except MathHttpError as exc:
            return _error_response(
                exc.status,
                exc.code,
                exc.message,
                reason=exc.reason,
                headers=exc.headers,
                retryable=exc.retryable,
                secrets=secrets,
            )
        except LinkError as exc:
            status, code = _link_error_status(exc)
            return _error_response(
                status, code, str(exc), reason=exc.code, secrets=secrets,
            )
        except MathExecutionGateError as exc:
            status, code = _gate_error_status(exc)
            return _error_response(
                status, code, str(exc), reason=exc.failure, secrets=secrets,
            )
        except MathExecutionRingError as exc:
            return _error_response(
                503, "RING_UNAVAILABLE", str(exc), secrets=secrets,
            )
        except MathExecutionConfigError as exc:
            return _error_response(
                503, "UNAVAILABLE", str(exc), reason="execute_unavailable",
                secrets=secrets,
            )
        except MathExecutionPlanError as exc:
            return _error_response(
                409, "PLAN_REJECTED", str(exc), secrets=secrets,
            )
        except MathExecutionBindingError as exc:
            return _error_response(
                409, "BINDING_REJECTED", str(exc), secrets=secrets,
            )
        except MathExecutionStateError as exc:
            return _error_response(
                409, "STATE_REJECTED", str(exc), secrets=secrets,
            )
        except MathExecutionError as exc:
            return _error_response(
                409, "EXECUTION_REJECTED", str(exc), secrets=secrets,
            )
        except MathStoreError as exc:
            return _error_response(
                503, "STORE_UNAVAILABLE", str(exc), secrets=secrets,
            )
        except MathRuntimeError as exc:
            return _error_response(
                400, "RUNTIME_REJECTED", str(exc), secrets=secrets,
            )
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            return _error_response(
                400, "INVALID_REQUEST", str(exc), secrets=secrets,
            )
        except Exception:
            return _error_response(
                500, "INTERNAL_ERROR", "internal service error",
                secrets=secrets,
            )

    # -- Request pipeline ----------------------------------------------------

    def _handle(
        self,
        method: str,
        path: str,
        headers: Any,
        body: bytes,
        secrets: list[str],
    ) -> MathHttpResponse:
        target = str(path)
        route = urlsplit(target).path
        if route not in (HEALTH_PATH, LINK_PATH, EXECUTE_PATH):
            raise MathHttpError(404, "NOT_FOUND", "not found")
        verb = str(method).upper()

        if route == HEALTH_PATH:
            if verb not in ("GET", "HEAD"):
                raise MathHttpError(
                    405, "METHOD_NOT_ALLOWED", "method not allowed",
                    headers={"Allow": "GET"},
                )
            return self._health_response(secrets)

        if verb != "POST":
            raise MathHttpError(
                405, "METHOD_NOT_ALLOWED", "method not allowed",
                headers={"Allow": "POST"},
            )

        self._authenticate(headers, secrets)
        self._require_jahs(headers)
        if not isinstance(body, (bytes, bytearray, memoryview)):
            raise MathHttpError(
                400, "INVALID_REQUEST", "request body must be bytes"
            )
        body = bytes(body)
        length = self._body_length(headers, body)
        if _content_type(headers) != JSON_CONTENT_TYPE:
            raise MathHttpError(
                415, "UNSUPPORTED_MEDIA_TYPE",
                "Content-Type must be application/json",
            )
        document = self._json_body(body)
        if route == LINK_PATH:
            return self._handle_link(document, secrets)
        return self._handle_execute(document, secrets)

    def _authenticate(self, headers: Any, secrets: list[str]) -> None:
        if self.auth is None:
            return
        token = _bearer_token(headers)
        secrets.append(token)
        authorize = self.auth._authorize
        try:
            authorize(token, (self.role,))
            return
        except WaveServiceAuthError:
            pass
        try:
            authorize(token, _ALL_ROLES)
        except WaveServiceAuthError as exc:
            raise MathHttpError(
                401, "UNAUTHORIZED", "invalid bearer token",
                headers={"WWW-Authenticate": _WWW_AUTHENTICATE},
            ) from exc
        raise MathHttpError(
            403, "FORBIDDEN", "bearer token does not hold the required role"
        )

    def _require_jahs(self, headers: Any) -> None:
        values = _header_values(headers, JAHS_HEADER)
        if not values:
            raise MathHttpError(
                403, "JAHS_REQUIRED",
                f"{JAHS_HEADER}: {JAHS_SEAL} is required",
            )
        if len(values) != 1:
            raise MathHttpError(
                400, "INVALID_JAHS",
                f"exactly one {JAHS_HEADER} header is required",
            )
        if not hmac.compare_digest(values[0].strip(), JAHS_SEAL):
            raise MathHttpError(
                403, "JAHS_INVALID",
                f"{JAHS_HEADER} must be {JAHS_SEAL!r}",
            )

    def _body_length(self, headers: Any, body: bytes) -> int:
        if _has_header(headers, "transfer-encoding"):
            raise MathHttpError(
                400, "CHUNKED_UNSUPPORTED",
                "chunked request bodies are not supported",
            )
        encodings = _header_values(headers, "content-encoding")
        if len(encodings) > 1:
            raise MathHttpError(
                400, "UNSUPPORTED_ENCODING",
                "exactly one Content-Encoding is allowed",
            )
        if encodings and encodings[0].strip().lower() not in ("", "identity"):
            raise MathHttpError(
                400, "UNSUPPORTED_ENCODING",
                "Content-Encoding is not supported",
            )

        lengths = _header_values(headers, "content-length")
        if len(lengths) != 1:
            raise MathHttpError(
                400, "LENGTH_REQUIRED",
                "exactly one Content-Length is required",
            )
        raw_length = lengths[0].strip()
        if not raw_length.isascii() or not raw_length.isdigit():
            raise MathHttpError(400, "INVALID_LENGTH", "invalid Content-Length")
        length = int(raw_length)
        if length > self.max_body_bytes:
            raise MathHttpError(
                413, "BODY_TOO_LARGE",
                f"request body exceeds {self.max_body_bytes} bytes",
            )
        if length != len(body):
            raise MathHttpError(
                400, "LENGTH_MISMATCH",
                "request body length does not match Content-Length",
            )
        if length < 1:
            raise MathHttpError(400, "EMPTY_BODY", "request body is required")
        return length

    def _json_body(self, body: bytes) -> dict[str, Any]:
        try:
            text = body.decode("utf-8")
            value = json.loads(
                text,
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
                parse_float=_parse_json_float,
            )
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            raise MathHttpError(
                400, "INVALID_JSON", "request must be valid UTF-8 JSON"
            ) from exc
        if not isinstance(value, dict):
            raise MathHttpError(
                400, "INVALID_JSON", "request JSON must be an object"
            )
        if not value:
            raise MathHttpError(
                400, "INVALID_REQUEST", "request JSON must not be empty"
            )
        return value

    # -- Link ----------------------------------------------------------------

    def _handle_link(
        self, document: dict[str, Any], secrets: list[str],
    ) -> MathHttpResponse:
        if "execute" in document:
            raise MathHttpError(
                400, "EXECUTION_NOT_PERMITTED",
                "the link endpoint never executes; use /v1/math/execute",
            )
        unknown = set(document) - _LINK_FIELDS
        if unknown:
            raise MathHttpError(
                400, "UNSUPPORTED_FIELD",
                "unsupported field(s): " + ", ".join(sorted(unknown)),
            )

        sources = [
            name for name in ("query", "operands", "refs") if name in document
        ]
        if len(sources) != 1:
            raise MathHttpError(
                400, "INVALID_REQUEST",
                "exactly one of query, operands, or refs is required",
            )

        mode = _text_field(document, "mode", default="conjoin", maximum=32)
        objective = _text_field(
            document, "objective", default="association", maximum=128,
        )
        max_candidates = _int_field(
            document, "max_candidates", default=8,
            minimum=0, maximum=MAX_CANDIDATES,
        )
        snapshot_id = _text_field(document, "snapshot_id")
        allow_scratch = _bool_field(document, "allow_scratch")
        bounds = _bounded_bounds(document.get("bounds"))
        goal = document.get("goal")

        try:
            if sources[0] == "query":
                query_text = _text_field(
                    document, "query", maximum=self.max_body_bytes,
                )
                query = LinkQuery.parse(
                    query_text or "",
                    mode=document.get("mode"),
                    objective=objective or "association",
                    max_candidates=max_candidates if max_candidates is not None else 8,
                    goal=goal,
                    bounds=bounds,
                )
            else:
                raw = document[sources[0]]
                if not isinstance(raw, (list, tuple)):
                    raise MathHttpError(
                        400, "INVALID_REQUEST",
                        f"{sources[0]} must be an array of leaf references",
                    )
                if not raw:
                    raise MathHttpError(
                        400, "INVALID_REQUEST",
                        f"{sources[0]} must not be empty",
                    )
                if len(raw) > self.max_operands:
                    raise MathHttpError(
                        400, "INVALID_REQUEST",
                        f"{sources[0]} exceeds {self.max_operands} operands",
                    )
                for index, item in enumerate(raw):
                    if not isinstance(item, (str, Mapping)):
                        raise MathHttpError(
                            400, "INVALID_REQUEST",
                            f"{sources[0]}[{index}] must be a string or object",
                        )
                query = LinkQuery(
                    operands=tuple(raw),
                    mode=mode or "conjoin",
                    objective=objective or "association",
                    max_candidates=(
                        max_candidates if max_candidates is not None else 8
                    ),
                    goal=goal,
                    bounds=bounds,
                )
            # Resolve every operand through the runtime's existing leaf
            # resolver.  Passing the resolved leaves to the linker keeps
            # math:// and nml: references equivalent and prevents a client
            # from injecting leaf content that is absent from the authority.
            operands = self._resolve_operands(query.operands)
        except LinkError as exc:
            raise MathHttpError(
                400, _link_error_code(exc), str(exc), reason=exc.code,
            ) from exc
        except MathHttpError:
            raise
        except (ValueError, TypeError) as exc:
            raise MathHttpError(
                400, "INVALID_REQUEST", str(exc)
            ) from exc

        result = self.runtime.propose(
            operands,
            snapshot_id=snapshot_id,
            mode=query.mode,
            objective=query.objective,
            max_candidates=query.max_candidates,
            goal=query.goal,
            bounds=query.bounds,
            allow_scratch=allow_scratch,
        )
        if hasattr(result, "to_dict"):
            link = result.to_dict()
        elif isinstance(result, Mapping):
            link = dict(result)
        else:
            raise MathHttpError(
                502, "LINK_RESULT_INVALID",
                "linker returned no serializable result",
            )
        headers = {
            "X-NaN-Math-Route": LINK_PATH,
            "X-NaN-JAHS": JAHS_SEAL,
        }
        candidate_count = link.get("candidate_count")
        if _is_int(candidate_count):
            headers["X-NaN-Math-Candidate-Count"] = str(candidate_count)
        return _json_response(
            200,
            {"schema": SCHEMA, "route": LINK_PATH, "link": link},
            secrets,
            headers=headers,
        )

    def _resolve_operands(self, operands: Any) -> tuple[Any, ...]:
        resolved: list[Any] = []
        for operand in operands:
            reference = parse_ref(operand)
            try:
                leaf = self.runtime.leaf(
                    reference.leaf_id, reference.version,
                )
            except MathRuntimeError as exc:
                raise LinkError(
                    "unknown_leaf",
                    f"leaf not found: {reference.leaf_id}@v{reference.version}",
                ) from exc
            if (
                reference.content_digest is not None
                and leaf.content_digest != reference.content_digest
            ):
                raise LinkError(
                    "digest_mismatch",
                    "leaf content digest does not match the pinned reference",
                )
            resolved.append(leaf)
        return tuple(resolved)

    # -- Execute -------------------------------------------------------------

    @property
    def execute_available(self) -> bool:
        if self.service is None:
            return False
        if callable(self.service):
            return True
        return callable(getattr(self.service, "execute", None))

    def _execute_availability(self) -> dict[str, Any]:
        if self.service is None:
            return {
                "available": False,
                "reason": "execute_service_not_configured",
            }
        if callable(self.service) or callable(
            getattr(self.service, "execute", None)
        ):
            return {"available": True, "reason": None}
        return {
            "available": False,
            "reason": "execute_service_missing_execute",
        }

    def _handle_execute(
        self, document: dict[str, Any], secrets: list[str],
    ) -> MathHttpResponse:
        availability = self._execute_availability()
        if not availability["available"]:
            raise MathHttpError(
                503,
                "UNAVAILABLE",
                "math execute route is unavailable",
                reason=availability["reason"],
            )
        if callable(self.service):
            execute = self.service
        else:
            execute = self.service.execute
        try:
            result = execute(document)
        except MathHttpError:
            raise
        except WaveServiceAuthError as exc:
            raise MathHttpError(
                401, "UNAUTHORIZED", "invalid bearer token",
                headers={"WWW-Authenticate": _WWW_AUTHENTICATE},
            ) from exc
        except MathExecutionError:
            raise
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            raise MathHttpError(
                400, "EXECUTE_REJECTED", str(exc), reason=type(exc).__name__,
            ) from exc
        if result is None:
            execution: dict[str, Any] = {"status": "ACCEPTED"}
        elif isinstance(result, Mapping):
            execution = dict(result)
        else:
            raise MathHttpError(
                502, "EXECUTE_RESULT_INVALID",
                "execute service returned no serializable result",
            )
        headers = {
            "X-NaN-Math-Route": EXECUTE_PATH,
            "X-NaN-JAHS": JAHS_SEAL,
        }
        return _json_response(
            200,
            {"schema": SCHEMA, "route": EXECUTE_PATH, "execution": execution},
            secrets,
            headers=headers,
        )

    # -- Health --------------------------------------------------------------

    def _health_response(self, secrets: list[str]) -> MathHttpResponse:
        components: dict[str, Any] = {}
        issues: list[str] = []

        try:
            components["functions"] = dict(self.runtime.functions.health())
        except Exception as exc:
            components["functions"] = {
                "status": "unhealthy",
                "reason": type(exc).__name__,
            }
            issues.append("functions_health_failed")

        store = getattr(self.runtime, "store", None)
        if store is not None and callable(getattr(store, "math_health", None)):
            try:
                components["store"] = dict(store.math_health())
            except Exception as exc:
                components["store"] = {
                    "status": "unhealthy",
                    "reason": type(exc).__name__,
                }
                issues.append("store_health_failed")

        system = getattr(self.runtime, "system", None)
        if system is not None and callable(getattr(system, "health", None)):
            try:
                components["system"] = dict(system.health())
            except Exception as exc:
                components["system"] = {
                    "status": "unhealthy",
                    "reason": type(exc).__name__,
                }
                issues.append("system_health_failed")

        linker = getattr(self.runtime, "linker", None)
        if linker is not None and callable(getattr(linker, "health", None)):
            try:
                components["linker"] = dict(linker.health())
            except Exception as exc:
                components["linker"] = {
                    "status": "unhealthy",
                    "reason": type(exc).__name__,
                }
                issues.append("linker_health_failed")

        provider = getattr(self.runtime, "rule_provider", None)
        if provider is not None and callable(getattr(provider, "health", None)):
            try:
                components["rule_provider"] = dict(provider.health())
            except Exception as exc:
                components["rule_provider"] = {
                    "status": "unhealthy",
                    "reason": type(exc).__name__,
                }
                issues.append("rule_provider_health_failed")

        if self.service is not None and not callable(self.service):
            service_health = getattr(self.service, "health", None)
            if callable(service_health):
                try:
                    components["execute"] = dict(service_health())
                except Exception as exc:
                    components["execute"] = {
                        "status": "unhealthy",
                        "reason": type(exc).__name__,
                    }
                    issues.append("execute_health_failed")

        status = _overall_status(components)
        if issues and status == "green":
            status = "degraded"

        rule_snapshot_id = None
        if callable(getattr(self.runtime, "current_rule_snapshot_id", None)):
            try:
                rule_snapshot_id = self.runtime.current_rule_snapshot_id()
            except Exception as exc:
                issues.append("rule_snapshot_unavailable")
                components["rule_snapshot"] = {
                    "status": "unhealthy",
                    "reason": type(exc).__name__,
                }
                if status == "green":
                    status = "degraded"

        document = {
            "schema": SCHEMA,
            "route": HEALTH_PATH,
            "status": status,
            "healthy": status == "green",
            "issues": issues,
            "body_limit_bytes": self.max_body_bytes,
            "jahs_required": True,
            "execute": self._execute_availability(),
            "rule_snapshot_id": rule_snapshot_id,
            "components": components,
        }
        return _json_response(
            200,
            {"schema": SCHEMA, "route": HEALTH_PATH, "health": document},
            secrets,
            headers={"X-NaN-Math-Route": HEALTH_PATH},
        )


@dataclass(frozen=True)
class PreparedMathExecutionHandle:
    """One server-owned prepared packet/lease exposed by an opaque handle ID.

    ``executor`` is optional.  When it is absent, the request must carry a
    caller-supplied ``result_digest``; that digest is handed to
    :meth:`MathExecutionBridge.execute` as result metadata, never as a lease
    token.  ``deadline_tick`` defaults to the lease's own deadline.
    """

    handle_id: str
    lease: MathExecutionLease
    executor: Any = None
    deadline_tick: int | None = None
    owner: str | None = None

    def __post_init__(self) -> None:
        if not _valid_handle_id(self.handle_id):
            raise ValueError(
                "handle_id must be 1.."
                f"{MAX_HANDLE_ID_CHARS} printable non-whitespace characters"
            )
        if self.lease is None:
            raise TypeError("lease must be a prepared MathExecutionLease")
        if self.deadline_tick is not None:
            if (
                isinstance(self.deadline_tick, bool)
                or not isinstance(self.deadline_tick, int)
                or self.deadline_tick < 0
            ):
                raise ValueError("deadline_tick must be an integer >= 0")
        if self.owner is not None and (
            not isinstance(self.owner, str) or not self.owner
        ):
            raise ValueError("owner must be a non-empty string")


class PreparedMathExecutionService:
    """Bounded registry of prepared leases executed through one bridge.

    The service is the wrapper that ``/v1/math/execute`` is allowed to
    delegate to.  It never prepares packets, acquires leases, performs host
    arithmetic, or accepts raw worker/lease tokens from HTTP clients.  A
    handle is registered server-side with an already leased
    :class:`MathExecutionLease`; HTTP requests only name the handle and supply
    result metadata.  Handle IDs therefore behave as opaque capabilities and
    should be issued only to the caller that owns the lease.

    Successful terminal results are cached by handle ID so duplicate execute
    or commit requests return the same token-free result without invoking the
    executor or bridge a second time.
    """

    def __init__(
        self,
        bridge: MathExecutionBridge,
        handles: Any = None,
        *,
        executor: Any = None,
        max_handles: int = MAX_PREPARED_HANDLES,
        max_results: int | None = None,
    ) -> None:
        if not callable(getattr(bridge, "execute", None)):
            raise TypeError("bridge must expose execute(...)")
        if (
            isinstance(max_handles, bool)
            or not isinstance(max_handles, int)
            or not 1 <= max_handles <= MAX_PREPARED_HANDLES
        ):
            raise ValueError(
                f"max_handles must be in 1..{MAX_PREPARED_HANDLES}"
            )
        if max_results is None:
            max_results = max_handles
        if (
            isinstance(max_results, bool)
            or not isinstance(max_results, int)
            or not 1 <= max_results <= MAX_PREPARED_HANDLES
        ):
            raise ValueError(
                f"max_results must be in 1..{MAX_PREPARED_HANDLES}"
            )

        self.bridge = bridge
        self.max_handles = max_handles
        self.max_results = max_results
        self._default_executor = executor
        self._lock = threading.RLock()
        self._handles: dict[str, PreparedMathExecutionHandle] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._results: dict[str, dict[str, Any]] = {}

        if handles is not None:
            if isinstance(handles, Mapping):
                for handle_id, value in handles.items():
                    if isinstance(value, PreparedMathExecutionHandle):
                        if value.handle_id != handle_id:
                            raise ValueError(
                                "handle map key does not match handle_id"
                            )
                        self.register(value)
                    else:
                        self.register(handle_id, value)
            elif isinstance(handles, PreparedMathExecutionHandle):
                self.register(handles)
            else:
                try:
                    iterator = iter(handles)
                except TypeError as exc:
                    raise TypeError(
                        "handles must be a mapping or iterable of handles"
                    ) from exc
                for value in iterator:
                    if (
                        isinstance(value, tuple)
                        and len(value) == 2
                        and isinstance(value[0], str)
                    ):
                        self.register(value[0], value[1])
                    else:
                        self.register(value)

    def __repr__(self) -> str:
        return (
            "PreparedMathExecutionService("
            f"handles={len(self)}, capacity={self.max_handles}, "
            f"completed={len(self._results)})"
        )

    def __len__(self) -> int:
        with self._lock:
            return len(self._handles)

    def __contains__(self, handle_id: object) -> bool:
        with self._lock:
            return handle_id in self._handles

    @property
    def handle_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._handles)

    # -- registry ------------------------------------------------------------

    def register(
        self,
        handle_or_id: Any,
        lease: Any = None,
        *,
        executor: Any = None,
        deadline_tick: int | None = None,
        owner: str | None = None,
    ) -> PreparedMathExecutionHandle:
        """Register one prepared lease; duplicate IDs are never replaced."""
        if isinstance(handle_or_id, PreparedMathExecutionHandle):
            if (
                lease is not None
                or executor is not None
                or deadline_tick is not None
                or owner is not None
            ):
                raise TypeError(
                    "extra handle fields cannot accompany a typed handle"
                )
            handle = handle_or_id
        else:
            if not isinstance(handle_or_id, str):
                raise TypeError("handle_id must be a string")
            if isinstance(lease, PreparedMathExecutionHandle):
                if lease.handle_id != handle_or_id:
                    raise ValueError("handle map key does not match handle_id")
                handle = lease
            else:
                if isinstance(lease, Mapping):
                    spec = dict(lease)
                    unknown = set(spec) - {
                        "deadline_tick",
                        "executor",
                        "execution_lease",
                        "lease",
                        "owner",
                    }
                    if unknown:
                        raise ValueError(
                            "unsupported handle field(s): "
                            + ", ".join(sorted(unknown))
                        )
                    lease = spec.get("lease", spec.get("execution_lease"))
                    if "executor" in spec:
                        executor = spec["executor"]
                    if "deadline_tick" in spec:
                        deadline_tick = spec["deadline_tick"]
                    if "owner" in spec:
                        owner = spec["owner"]
                if lease is None:
                    raise TypeError("a prepared lease is required")
                if executor is None:
                    executor = self._default_executor
                handle = PreparedMathExecutionHandle(
                    handle_or_id,
                    lease,
                    executor=executor,
                    deadline_tick=deadline_tick,
                    owner=owner,
                )

        with self._lock:
            if handle.handle_id in self._handles:
                raise MathExecutionStateError(
                    f"prepared handle {handle.handle_id!r} is already registered"
                )
            if len(self._handles) >= self.max_handles:
                raise MathExecutionStateError(
                    "prepared handle registry is full"
                )
            self._handles[handle.handle_id] = handle
            self._locks[handle.handle_id] = threading.Lock()
        return handle

    def remove(self, handle_id: str) -> bool:
        """Revoke a handle and any cached result; returns ``True`` if removed."""
        with self._lock:
            self._results.pop(handle_id, None)
            self._locks.pop(handle_id, None)
            return self._handles.pop(handle_id, None) is not None

    revoke = remove
    unregister = remove
    add = register
    put = register

    def prune_expired(self, now_tick: int) -> tuple[str, ...]:
        """Drop handles whose lease deadline is at or before *now_tick*."""
        if isinstance(now_tick, bool) or not isinstance(now_tick, int):
            raise ValueError("now_tick must be an integer")
        removed: list[str] = []
        with self._lock:
            for handle_id, handle in tuple(self._handles.items()):
                deadline = self._deadline(handle)
                if deadline is not None and now_tick >= deadline:
                    self._handles.pop(handle_id, None)
                    self._locks.pop(handle_id, None)
                    self._results.pop(handle_id, None)
                    removed.append(handle_id)
        return tuple(removed)

    def health(self) -> dict[str, Any]:
        """Return token-free registry health for the math health route."""
        with self._lock:
            handles = len(self._handles)
            results = len(self._results)
        return {
            "status": "green",
            "available": True,
            "prepared_handles": handles,
            "capacity": self.max_handles,
            "completed_results": results,
        }

    # -- execution -----------------------------------------------------------

    def execute(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Execute one prepared handle named by a bounded, token-free request."""
        fields = self._validate_request(request)
        handle_id = fields["handle_id"]
        with self._lock:
            handle = self._handles.get(handle_id)
            if handle is None:
                raise MathHttpError(
                    404,
                    "HANDLE_NOT_FOUND",
                    "prepared execution handle was not found",
                    reason="unknown_handle",
                )
            handle_lock = self._locks.get(handle_id)
            if handle_lock is None:
                handle_lock = threading.Lock()
                self._locks[handle_id] = handle_lock

        # Serialize one handle so concurrent duplicates cannot execute twice.
        with handle_lock:
            with self._lock:
                handle = self._handles.get(handle_id)
                if handle is None:
                    raise MathHttpError(
                        404,
                        "HANDLE_NOT_FOUND",
                        "prepared execution handle was not found",
                        reason="unknown_handle",
                    )
                cached = self._results.get(handle_id)
            if cached is not None:
                return self._replay(handle, cached, fields)

            deadline = self._deadline(handle)
            if deadline is not None and fields["now_tick"] >= deadline:
                self.remove(handle_id)
                raise MathExecutionStateError(
                    "prepared lease deadline has expired"
                )

            if fields["result_digest"] is not None:
                digest = fields["result_digest"]

                def executor(_lease: Any) -> str:
                    return digest

            elif handle.executor is not None:
                executor = handle.executor
            else:
                raise MathHttpError(
                    400,
                    "RESULT_DIGEST_REQUIRED",
                    "result_digest is required when the handle has no executor",
                    reason="result_digest_required",
                )

            try:
                result = self.bridge.execute(
                    handle.lease,
                    executor,
                    now_tick=fields["now_tick"],
                    result_status=fields["result_status"],
                    output_leaf_id=fields["output_leaf_id"],
                    evidence=fields["evidence"],
                    commit=fields["commit"],
                )
            except MathExecutionError:
                raise
            except Exception as exc:
                # Executor errors can contain secrets; expose only the type.
                raise MathExecutionStateError(
                    f"prepared execution failed ({type(exc).__name__})"
                ) from None

            safe, metadata = self._finalize_result(
                handle, result, duplicate=False,
            )
            with self._lock:
                if handle_id in self._handles:
                    self._cache_result(handle_id, safe, metadata)
            return safe

    # -- internals -----------------------------------------------------------

    @staticmethod
    def _deadline(handle: PreparedMathExecutionHandle) -> int | None:
        if handle.deadline_tick is not None:
            return handle.deadline_tick
        deadline = getattr(handle.lease, "deadline_tick", None)
        if deadline is None:
            return None
        if isinstance(deadline, bool) or not isinstance(deadline, int):
            raise MathExecutionBindingError("lease deadline is malformed")
        return deadline

    def _secrets_for(self, handle: PreparedMathExecutionHandle) -> list[str]:
        secrets: list[str] = []
        for value in (
            getattr(handle.lease, "lease_token", None),
            getattr(self.bridge, "worker_token", None),
            getattr(self.bridge, "submit_token", None),
        ):
            if isinstance(value, str) and value and value not in secrets:
                secrets.append(value)
        return secrets

    def _validate_request(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(request, Mapping):
            raise MathHttpError(
                400, "INVALID_REQUEST", "execute request must be an object"
            )
        secret_key = _find_secret_key(request)
        if secret_key is not None:
            raise MathHttpError(
                400,
                "RAW_SECRET_NOT_PERMITTED",
                f"{secret_key} is not accepted; supply only a prepared handle",
                reason="raw_secret_not_permitted",
            )
        unknown = set(request) - _EXECUTE_FIELDS
        if unknown:
            raise MathHttpError(
                400,
                "UNSUPPORTED_FIELD",
                "unsupported field(s): " + ", ".join(sorted(unknown)),
            )
        present = [
            name for name in _EXECUTE_HANDLE_FIELDS if name in request
        ]
        if len(present) != 1:
            raise MathHttpError(
                400,
                "INVALID_REQUEST",
                "exactly one prepared handle field is required: "
                + ", ".join(_EXECUTE_HANDLE_FIELDS),
            )
        handle_id = request[present[0]]
        if not _valid_handle_id(handle_id):
            raise MathHttpError(
                400,
                "INVALID_REQUEST",
                "handle_id must be 1.."
                f"{MAX_HANDLE_ID_CHARS} printable non-whitespace characters",
            )
        digest_field = _alias_field(
            request, _EXECUTE_DIGEST_FIELDS, "result digest",
        )
        status_field = _alias_field(
            request, _EXECUTE_STATUS_FIELDS, "result status",
        )
        output_field = _alias_field(
            request, _EXECUTE_OUTPUT_FIELDS, "output leaf",
        )
        result_digest = (
            None if digest_field is None else _text_field(
                request, digest_field, maximum=MAX_RESULT_DIGEST_CHARS,
            )
        )
        result_status = (
            None if status_field is None else _text_field(
                request, status_field, maximum=MAX_RESULT_STATUS_CHARS,
            )
        )
        output_leaf_id = (
            None if output_field is None else _text_field(
                request, output_field, maximum=MAX_OUTPUT_LEAF_ID_CHARS,
            )
        )
        commit = _bool_field(request, "commit")
        now_tick = _int_field(
            request,
            "now_tick",
            default=0,
            minimum=0,
            maximum=MAX_NOW_TICK,
        )
        evidence = request.get("evidence")
        if evidence is not None:
            if not isinstance(evidence, Mapping):
                raise MathHttpError(
                    400, "INVALID_REQUEST", "evidence must be an object"
                )
            try:
                encoded = json.dumps(
                    evidence,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode("utf-8")
            except (TypeError, ValueError) as exc:
                raise MathHttpError(
                    400,
                    "INVALID_REQUEST",
                    "evidence must be JSON-serializable",
                ) from exc
            if len(encoded) > MAX_EVIDENCE_BYTES:
                raise MathHttpError(
                    400,
                    "INVALID_REQUEST",
                    f"evidence exceeds {MAX_EVIDENCE_BYTES} bytes",
                )
            evidence = dict(evidence)
        return {
            "handle_id": handle_id,
            "result_digest": result_digest,
            "result_status": result_status,
            "output_leaf_id": output_leaf_id,
            "commit": commit,
            "now_tick": now_tick if now_tick is not None else 0,
            "evidence": evidence,
        }

    def _finalize_result(
        self,
        handle: PreparedMathExecutionHandle,
        result: Any,
        *,
        duplicate: bool,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if isinstance(result, Mapping):
            raw = dict(result)
        elif callable(getattr(result, "to_dict", None)):
            raw = dict(result.to_dict())
        else:
            raise MathExecutionBindingError(
                "bridge returned no serializable execution result"
            )

        digest = raw.get("result_digest")
        status = raw.get("result_status")
        output = raw.get("output_leaf_id")
        outcome = raw.get("outcome")
        committed = bool(
            raw.get("committed")
            or raw.get("state") == "COMMITTED"
            or outcome == "COMMITTED"
        )
        raw.setdefault("schema", "nanrouter.math-execution-result.v1")
        raw["handle_id"] = handle.handle_id
        if outcome is not None:
            raw["status"] = outcome
        elif raw.get("status") is None:
            raw["status"] = raw.get("state") or (
                "COMMITTED" if committed else "COMPLETED"
            )
        raw["duplicate"] = bool(duplicate or raw.get("duplicate"))
        safe = _redact(raw, self._secrets_for(handle))
        if not isinstance(safe, dict):
            raise MathExecutionBindingError(
                "bridge returned no serializable execution result"
            )
        return safe, {
            "result_digest": digest if isinstance(digest, str) else None,
            "result_status": status if isinstance(status, str) else None,
            "output_leaf_id": output if isinstance(output, str) else None,
            "committed": committed,
        }

    def _cache_result(
        self,
        handle_id: str,
        result: Mapping[str, Any],
        metadata: Mapping[str, Any],
    ) -> None:
        self._results[handle_id] = {
            "result": copy.deepcopy(dict(result)),
            **dict(metadata),
        }
        while len(self._results) > self.max_results:
            oldest = next(iter(self._results))
            self._results.pop(oldest, None)
            # Never leave a handle executable after its idempotence record is
            # gone; a replay must fail closed instead of running twice.
            self._handles.pop(oldest, None)
            self._locks.pop(oldest, None)

    def _replay(
        self,
        handle: PreparedMathExecutionHandle,
        cached: Mapping[str, Any],
        fields: Mapping[str, Any],
    ) -> dict[str, Any]:
        requested_digest = fields["result_digest"]
        cached_digest = cached.get("result_digest")
        if (
            requested_digest is not None
            and cached_digest is not None
            and requested_digest != cached_digest
        ):
            raise MathExecutionBindingError(
                "result_digest does not match the completed execution"
            )
        requested_status = fields["result_status"]
        cached_status = cached.get("result_status")
        if (
            requested_status is not None
            and requested_status != cached_status
        ):
            raise MathExecutionBindingError(
                "result_status does not match the completed execution"
            )
        requested_output = fields["output_leaf_id"]
        cached_output = cached.get("output_leaf_id")
        if (
            requested_output is not None
            and requested_output != cached_output
        ):
            raise MathExecutionBindingError(
                "output_leaf_id does not match the completed execution"
            )

        if fields["commit"] and not cached.get("committed"):
            if not isinstance(cached_digest, str) or not cached_digest:
                raise MathExecutionConfigError(
                    "completed execution has no result digest to commit"
                )
            complete = getattr(self.bridge, "complete", None)
            if not callable(complete):
                raise MathExecutionConfigError(
                    "bridge cannot commit a completed execution"
                )
            result = complete(
                handle.lease,
                cached_digest,
                now_tick=fields["now_tick"],
                result_status=cached_status or "OK",
                output_leaf_id=cached_output,
                evidence=fields["evidence"],
                commit=True,
            )
            safe, metadata = self._finalize_result(
                handle, result, duplicate=True,
            )
            with self._lock:
                if handle.handle_id in self._handles:
                    self._cache_result(handle.handle_id, safe, metadata)
            return safe

        payload = copy.deepcopy(dict(cached["result"]))
        payload["duplicate"] = True
        return payload


def _link_error_code(exc: LinkError) -> str:
    if exc.code == "address_context_mismatch":
        return "ADDRESS_CONTEXT_MISMATCH"
    if exc.code == "execution_not_permitted":
        return "EXECUTION_NOT_PERMITTED"
    return "LINK_REJECTED"


def _link_error_status(exc: LinkError) -> tuple[int, str]:
    if exc.code in {"unavailable", "missing_registry"}:
        return 503, "LINK_UNAVAILABLE"
    return 400, _link_error_code(exc)


def _gate_error_status(exc: MathExecutionGateError) -> tuple[int, str]:
    failure = str(exc.failure or "REJECTED").upper()
    if failure == "UNAVAILABLE":
        return 503, "UNAVAILABLE"
    if failure == "UNAUTHORIZED":
        return 403, "UNAUTHORIZED"
    if failure == "STALE":
        return 409, "STALE"
    return 409, "GATE_REJECTED"


def make_math_handler(adapter: MathHttpAdapter, *,
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

    class MathRequestHandler(BaseHTTPRequestHandler):
        server_version = "NaNROUTER-Math/1"
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
            self._send(_error_response(
                int(code), "HTTP_ERROR", _bounded_text(text),
            ))

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
                raise MathHttpError(
                    400, "CHUNKED_UNSUPPORTED",
                    "chunked request bodies are not supported",
                )
            encodings = self.headers.get_all("Content-Encoding", [])
            if len(encodings) > 1:
                raise MathHttpError(
                    400, "UNSUPPORTED_ENCODING",
                    "exactly one Content-Encoding is allowed",
                )
            if (
                encodings
                and encodings[0].strip().lower() not in ("", "identity")
            ):
                raise MathHttpError(
                    400, "UNSUPPORTED_ENCODING",
                    "Content-Encoding is not supported",
                )

            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1:
                raise MathHttpError(
                    400, "LENGTH_REQUIRED",
                    "exactly one Content-Length is required",
                )
            raw_length = lengths[0].strip()
            if not raw_length.isascii() or not raw_length.isdigit():
                raise MathHttpError(400, "INVALID_LENGTH", "invalid Content-Length")
            length = int(raw_length)
            if length > handler_limit:
                if length <= handler_limit + _MAX_DRAIN_BYTES:
                    self._discard_body(length)
                raise MathHttpError(
                    413, "BODY_TOO_LARGE",
                    f"request body exceeds {handler_limit} bytes",
                )
            if length == 0:
                return b""
            try:
                raw = self.rfile.read(length)
            except (OSError, TimeoutError) as exc:
                raise MathHttpError(
                    400, "BODY_READ_FAILED",
                    "request body could not be read",
                ) from exc
            if len(raw) != length:
                raise MathHttpError(
                    400, "BODY_TRUNCATED", "request body is truncated"
                )
            return raw

        def _send(self, response: MathHttpResponse) -> None:
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
                path = urlsplit(self.path).path
                read_body = with_body and path in (LINK_PATH, EXECUTE_PATH)
                body = self._read_body() if read_body else b""
                response = adapter.handle(method, self.path, self.headers, body)
            except MathHttpError as exc:
                response = _error_response(
                    exc.status, exc.code, exc.message,
                    reason=exc.reason,
                    headers=exc.headers,
                    retryable=exc.retryable,
                )
            except Exception:
                response = _error_response(
                    500, "INTERNAL_ERROR", "internal service error",
                )
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

    return MathRequestHandler


class MathHttpServer:
    """Optional bounded lifecycle wrapper for the math HTTP adapter.

    The default listener is loopback on an ephemeral port.  The pure
    :meth:`MathHttpAdapter.handle` core does not need this class.
    """

    def __init__(self, adapter: MathHttpAdapter,
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
            f"MathHttpServer(host={self.host!r}, port={self.port}, "
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
            raise RuntimeError("math HTTP server is not running")
        host, port = self.address
        display_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
        return f"http://{display_host}:{port}"

    @property
    def url(self) -> str:
        return self.base_url

    def start(self, host: str | None = None,
              port: int | None = None) -> "MathHttpServer":
        """Bind and serve on a background daemon thread; returns ``self``."""
        with self._lock:
            if self._httpd is not None:
                raise RuntimeError("math HTTP server is already running")
            bind_host = self.host if host is None else host
            bind_port = self._requested_port if port is None else port
            httpd = ThreadingHTTPServer(
                (bind_host, bind_port),
                make_math_handler(
                    self.adapter, max_body_bytes=self.max_body_bytes
                ),
            )
            httpd.daemon_threads = True
            thread = threading.Thread(
                target=httpd.serve_forever,
                args=(0.05,),
                name=f"math-http-{httpd.server_port}",
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

    def __enter__(self) -> "MathHttpServer":
        return self.start()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        self.stop()
        return False


__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "ERROR_SCHEMA",
    "EXECUTE_PATH",
    "HEALTH_PATH",
    "JAHS_HEADER",
    "JSON_CONTENT_TYPE",
    "LINK_PATH",
    "MAX_BODY_BYTES",
    "MAX_CANDIDATES",
    "MAX_HANDLE_ID_CHARS",
    "MAX_LINK_DEPTH",
    "MAX_LINK_FANOUT",
    "MAX_LINK_FUEL",
    "MAX_OPERANDS",
    "MAX_PREPARED_HANDLES",
    "MAX_REQUEST_BYTES",
    "MathHttpAdapter",
    "MathHttpError",
    "MathHttpResponse",
    "MathHttpServer",
    "PreparedMathExecutionHandle",
    "PreparedMathExecutionService",
    "SCHEMA",
    "make_math_handler",
]
