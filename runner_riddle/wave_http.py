"""Standard-library HTTP transport for the authenticated wave control plane.

The adapter is deliberately thin.  It parses a bounded JSON request, reads a
bearer token, delegates the role check to
:class:`runner_riddle.wave_service.WaveService`, and returns the record produced
by the existing facade/store.  It performs no wave mathematics, owns no
persistence, and never stores or logs credentials.
"""
from __future__ import annotations

import json
import math
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterable
from urllib.parse import urlsplit

from .wave_service import WaveService, WaveServiceAuthError
from .wave_store import (
    CapabilityConflictError,
    JobConflictError,
    LeaseError,
    OperatorConflictError,
    StaleGenerationError,
    WaveStore,
    WaveStoreError,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 0
MAX_BODY_BYTES = 1_048_576
# Alias matching the older runner-riddle HTTP service naming.
MAX_REQUEST_BYTES = MAX_BODY_BYTES
MAX_ERROR_CHARS = 320
MAX_INTEGER = 2**63 - 1
# A small overshoot is drained so an honest client receives the 400 instead of
# seeing a connection reset while it is still writing the rejected body.
_MAX_DRAIN_BYTES = 65_536

_ALL_ROLES = ("submit", "worker", "admin")
_SUBMIT_ROLE = ("submit",)
_WORKER_ROLE = ("worker",)
_ADMIN_ROLE = ("admin",)
_WWW_AUTHENTICATE = 'Bearer realm="wave"'

_GET_ROUTES = ("/healthz",)
_POST_ROUTES = (
    "/v1/nmp/packets",
    "/v1/nmp/lease",
    "/v1/nmp/complete",
    "/v1/wave/jobs",
    "/v1/wave/lease",
    "/v1/wave/complete",
    "/v1/wave/capabilities",
)

_MISSING = object()


class _HttpError(Exception):
    """A bounded response the adapter can send without inspecting internals."""

    def __init__(self, status: int, message: str, *,
                 headers: dict[str, str] | None = None,
                 retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.headers = dict(headers or {})
        self.retryable = retryable


def _bounded_text(value: Any, limit: int = MAX_ERROR_CHARS) -> str:
    """Collapse and truncate text so error responses have a fixed upper bound."""
    text = " ".join(str(value).split())
    if len(text) > limit:
        text = text[: max(1, limit - 3)] + "..."
    return text or "request failed"


def _store_busy_error(exc: BaseException) -> bool:
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    text = str(exc).lower()
    return "locked" in text or "busy" in text


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


def _text_field(body: dict[str, Any], name: str, *,
                default: Any = _MISSING) -> str | None:
    if name not in body or body[name] is None:
        if default is _MISSING:
            raise _HttpError(400, f"{name} is required")
        return default
    value = body[name]
    if not isinstance(value, str) or not value.strip():
        raise _HttpError(400, f"{name} must be a non-empty string")
    return value


def _int_field(body: dict[str, Any], name: str, *,
               default: Any = _MISSING, minimum: int = 0) -> int:
    if name not in body or body[name] is None:
        if default is _MISSING:
            raise _HttpError(400, f"{name} is required")
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise _HttpError(400, f"{name} must be an integer")
    if value < minimum or value > MAX_INTEGER:
        raise _HttpError(
            400, f"{name} must be an integer between {minimum} and {MAX_INTEGER}"
        )
    return value


def make_wave_handler(service: WaveService, *,
                      max_body_bytes: int = MAX_BODY_BYTES,
                      nmp_adapter: Any = None):
    """Build a request handler bound to *service*.

    The handler never echoes the ``Authorization`` header, request body, or an
    unexpected exception message.  Request logging is intentionally disabled so
    a credential can never reach the process log through this adapter.
    """
    if isinstance(max_body_bytes, bool) or not isinstance(max_body_bytes, int) \
            or max_body_bytes < 1:
        raise ValueError("max_body_bytes must be a positive integer")

    class WaveRequestHandler(BaseHTTPRequestHandler):
        server_version = "NaNROUTER-Wave/1"
        sys_version = ""
        protocol_version = "HTTP/1.1"

        # -- Transport helpers -------------------------------------------------

        def log_message(self, fmt: str, *args: Any) -> None:
            # Deliberately empty: request lines and headers may contain
            # credentials, so this adapter emits no access log at all.
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
            # BaseHTTPRequestHandler emits an HTML page by default.  Keep every
            # parser-level failure in the same bounded JSON envelope, and use
            # only the standard reason phrase: the default message echoes the
            # raw request line, which could contain credential material.
            text = self.responses.get(int(code), ("request failed",))[0]
            self._safe_error(_HttpError(int(code), _bounded_text(text)))

        def _send_json(self, status: int, value: Any, *,
                       headers: dict[str, str] | None = None) -> None:
            try:
                raw = json.dumps(
                    value, sort_keys=True, separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            except (TypeError, ValueError):
                status = 500
                raw = b'{"error":"internal service error"}'
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            for name, header_value in (headers or {}).items():
                self.send_header(name, header_value)
            self.close_connection = True
            self.end_headers()
            if getattr(self, "command", None) == "HEAD":
                return
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True

        def _safe_error(self, exc: BaseException) -> None:
            try:
                self._send_exception(exc)
            except Exception:
                # The peer disappeared or the socket was already closed.  Do
                # not leak a traceback or make a second response attempt.
                self.close_connection = True

        def _send_exception(self, exc: BaseException) -> None:
            headers: dict[str, str] = {}
            retryable = False
            if isinstance(exc, _HttpError):
                status = exc.status
                message = _bounded_text(exc.message)
                headers.update(exc.headers)
                retryable = exc.retryable
            elif isinstance(exc, WaveServiceAuthError):
                status = 401
                message = "authorization required"
                headers["WWW-Authenticate"] = _WWW_AUTHENTICATE
            elif isinstance(exc, (
                JobConflictError,
                StaleGenerationError,
                LeaseError,
                OperatorConflictError,
                CapabilityConflictError,
            )):
                status = 409
                message = _bounded_text(str(exc))
            elif _store_busy_error(exc):
                status = 429
                message = "wave store is busy; retry later"
                headers["Retry-After"] = "1"
                retryable = True
            elif isinstance(exc, sqlite3.IntegrityError):
                status = 409
                message = "wave store constraint conflict"
            elif isinstance(exc, (
                WaveStoreError, ValueError, TypeError, KeyError, OverflowError,
            )):
                status = 400
                message = _bounded_text(str(exc))
            else:
                status = 500
                message = "internal service error"

            payload: dict[str, Any] = {"error": message}
            if retryable:
                payload["retryable"] = True
            self._send_json(status, payload, headers=headers)

        # -- Request parsing ---------------------------------------------------

        def _bearer_token(self) -> str:
            header = self.headers.get("Authorization")
            if not header:
                raise _HttpError(
                    401, "bearer token is required",
                    headers={"WWW-Authenticate": _WWW_AUTHENTICATE},
                )
            scheme, separator, credentials = header.partition(" ")
            token = credentials.strip()
            if (not separator or scheme.lower() != "bearer" or not token
                    or len(token) > 4096
                    or any(char.isspace() for char in token)):
                raise _HttpError(
                    401, "invalid bearer token",
                    headers={"WWW-Authenticate": _WWW_AUTHENTICATE},
                )
            return token

        def _token_is_known(self, token: str) -> bool:
            try:
                # WaveService intentionally exposes no token-introspection API.
                # Asking it to authorize "any role" reuses its constant-time
                # role comparisons without touching the stored digests.
                service._authorize(token, _ALL_ROLES)
                return True
            except WaveServiceAuthError:
                return False

        def _authorize(self, token: str,
                       roles: Iterable[str]) -> None:
            try:
                service._authorize(token, roles)
            except WaveServiceAuthError:
                if self._token_is_known(token):
                    raise _HttpError(
                        403, "bearer token does not hold the required role"
                    ) from None
                raise _HttpError(
                    401, "invalid bearer token",
                    headers={"WWW-Authenticate": _WWW_AUTHENTICATE},
                ) from None

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

        def _json_body(self) -> dict[str, Any]:
            if self.headers.get("Transfer-Encoding"):
                raise _HttpError(400, "chunked request bodies are not supported")
            encoding = self.headers.get("Content-Encoding")
            if encoding and encoding.strip().lower() != "identity":
                raise _HttpError(400, "Content-Encoding is not supported")
            if self.headers.get_content_type() != "application/json":
                raise _HttpError(
                    400, "Content-Type must be application/json"
                )

            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1:
                raise _HttpError(400, "exactly one Content-Length is required")
            raw_length = lengths[0].strip()
            if not raw_length.isascii() or not raw_length.isdigit():
                raise _HttpError(400, "invalid Content-Length")
            length = int(raw_length)
            if length < 1:
                raise _HttpError(400, "request body is required")
            if length > max_body_bytes:
                if length <= max_body_bytes + _MAX_DRAIN_BYTES:
                    self._discard_body(length)
                raise _HttpError(
                    400, f"request body exceeds {max_body_bytes} bytes"
                )

            try:
                raw = self.rfile.read(length)
            except (OSError, TimeoutError) as exc:
                raise _HttpError(400, "request body could not be read") from exc
            if len(raw) != length:
                raise _HttpError(400, "request body is truncated")
            try:
                text = raw.decode("utf-8")
                value = json.loads(
                    text,
                    object_pairs_hook=_unique_json_object,
                    parse_constant=_reject_json_constant,
                    parse_float=_parse_json_float,
                )
            except (UnicodeDecodeError, ValueError, RecursionError) as exc:
                raise _HttpError(
                    400, "request must be valid UTF-8 JSON"
                ) from exc
            if not isinstance(value, dict):
                raise _HttpError(400, "request JSON must be an object")
            return value

        # -- Endpoint bodies ---------------------------------------------------

        def _post_jobs(self, token: str, body: dict[str, Any]) -> None:
            job_id = _text_field(body, "job_id")
            universe_id = _text_field(body, "universe_id")
            operator_digest = _text_field(body, "operator_digest")
            generation = _int_field(body, "generation")
            now_tick = _int_field(body, "now_tick", default=0)
            kind = _text_field(body, "kind", default="wave")
            operator_id = _text_field(body, "operator_id", default=None)
            precision = _text_field(body, "precision", default=None)
            workspace = _int_field(body, "workspace", default=0)
            record = service.submit_job(
                token, job_id, universe_id, operator_digest, generation,
                body.get("payload"), now_tick, kind=kind,
                operator_id=operator_id, precision=precision,
                workspace=workspace,
            )
            self._send_json(200, {"job": record})

        def _post_lease(self, token: str, body: dict[str, Any]) -> None:
            owner = _text_field(body, "owner")
            now_tick = _int_field(body, "now_tick", default=0)
            lease_ticks = _int_field(body, "lease_ticks", default=64, minimum=1)
            expected_generation = _int_field(
                body, "expected_generation", default=None
            )
            max_attempts = _int_field(
                body, "max_attempts", default=8, minimum=1
            )
            job_id = _text_field(body, "job_id", default=None)
            record = service.lease_job(
                token, owner, now_tick, lease_ticks,
                expected_generation=expected_generation,
                max_attempts=max_attempts, job_id=job_id,
            )
            self._send_json(200, {"job": record})

        def _post_complete(self, token: str, body: dict[str, Any]) -> None:
            job_id = _text_field(body, "job_id")
            lease_token = _text_field(body, "lease_token")
            lease_epoch = _int_field(body, "lease_epoch", minimum=1)
            result_digest = _text_field(body, "result_digest")
            now_tick = _int_field(body, "now_tick", default=0)
            result_generation = _int_field(
                body, "result_generation", default=None
            )
            lease_owner = _text_field(body, "lease_owner", default=None)
            record = service.complete_job(
                token, job_id, lease_token, lease_epoch, result_digest,
                now_tick, result_generation=result_generation,
                lease_owner=lease_owner,
            )
            self._send_json(200, {"job": record})

        def _post_capabilities(self, token: str, body: dict[str, Any]) -> None:
            kernel_id = _text_field(body, "kernel_id")
            runner_id = _text_field(body, "runner_id")
            verified_digest = _text_field(body, "verified_digest")
            workspace = _int_field(body, "workspace", default=0)
            precision = _text_field(body, "precision")
            epoch = _int_field(body, "epoch", default=1, minimum=1)
            status = _text_field(body, "status", default="declared")
            nanclock_tick = _int_field(body, "nanclock_tick", default=0)
            record = service.register_capability(
                token, kernel_id, runner_id, verified_digest, workspace,
                precision, status=status, epoch=epoch,
                nanclock_tick=nanclock_tick,
            )
            self._send_json(200, {"capability": record})

        def _post_nmp_packet(self, token: str, body: dict[str, Any]) -> None:
            if nmp_adapter is None:
                raise _HttpError(503, "NMP service is not configured")
            packet = body.get("packet")
            if not isinstance(packet, dict):
                raise _HttpError(400, "packet must be an object")
            result = nmp_adapter.submit(
                token, packet, now_tick=_int_field(body, "now_tick", default=0)
            )
            self._send_json(200, result)

        def _post_nmp_lease(self, token: str, body: dict[str, Any]) -> None:
            if nmp_adapter is None:
                raise _HttpError(503, "NMP service is not configured")
            result = nmp_adapter.lease(
                token,
                _text_field(body, "owner"),
                now_tick=_int_field(body, "now_tick"),
                lease_ticks=_int_field(body, "lease_ticks", default=64, minimum=1),
                expected_generation=_int_field(body, "expected_generation", default=None),
                max_attempts=_int_field(body, "max_attempts", default=8, minimum=1),
                job_id=_text_field(body, "job_id", default=None),
            )
            self._send_json(200, {"lease": result})

        def _post_nmp_complete(self, token: str, body: dict[str, Any]) -> None:
            if nmp_adapter is None:
                raise _HttpError(503, "NMP service is not configured")
            packet = body.get("packet")
            if not isinstance(packet, dict):
                raise _HttpError(400, "packet must be an object")
            result = nmp_adapter.complete(
                token, packet,
                job_id=_text_field(body, "job_id"),
                lease_token=_text_field(body, "lease_token"),
                lease_epoch=_int_field(body, "lease_epoch", minimum=1),
                result_digest=_text_field(body, "result_digest"),
                now_tick=_int_field(body, "now_tick"),
                execution_evidence=body.get("execution_evidence"),
                result_generation=_int_field(body, "result_generation", default=None),
                lease_owner=_text_field(body, "lease_owner", default=None),
            )
            self._send_json(200, result)

        # -- Routing -----------------------------------------------------------

        def _path(self) -> str:
            return urlsplit(self.path).path

        def _method_not_allowed(self) -> None:
            path = self._path()
            if path in _GET_ROUTES:
                allow = "GET"
            elif path in _POST_ROUTES:
                allow = "POST"
            else:
                self._safe_error(_HttpError(404, "not found"))
                return
            self._safe_error(_HttpError(
                405, "method not allowed", headers={"Allow": allow}
            ))

        def _do_head(self) -> None:
            try:
                path = self._path()
                if path == "/healthz":
                    self._send_json(200, service.health())
                elif path in _POST_ROUTES:
                    raise _HttpError(
                        405, "method not allowed", headers={"Allow": "POST"}
                    )
                else:
                    raise _HttpError(404, "not found")
            except Exception as exc:
                self._safe_error(exc)

        def do_GET(self) -> None:
            try:
                path = self._path()
                if path == "/healthz":
                    self._send_json(200, service.health())
                    return
                if path in _POST_ROUTES:
                    raise _HttpError(
                        405, "method not allowed", headers={"Allow": "POST"}
                    )
                raise _HttpError(404, "not found")
            except Exception as exc:
                self._safe_error(exc)

        def do_HEAD(self) -> None:
            self._do_head()

        def do_POST(self) -> None:
            try:
                path = self._path()
                if path == "/v1/nmp/packets":
                    token = self._bearer_token()
                    self._authorize(token, _SUBMIT_ROLE)
                    self._post_nmp_packet(token, self._json_body())
                    return
                if path == "/v1/nmp/lease":
                    token = self._bearer_token()
                    self._authorize(token, _WORKER_ROLE)
                    self._post_nmp_lease(token, self._json_body())
                    return
                if path == "/v1/nmp/complete":
                    token = self._bearer_token()
                    self._authorize(token, _WORKER_ROLE)
                    self._post_nmp_complete(token, self._json_body())
                    return
                if path == "/v1/wave/jobs":
                    token = self._bearer_token()
                    self._authorize(token, _SUBMIT_ROLE)
                    self._post_jobs(token, self._json_body())
                    return
                if path == "/v1/wave/lease":
                    token = self._bearer_token()
                    self._authorize(token, _WORKER_ROLE)
                    self._post_lease(token, self._json_body())
                    return
                if path == "/v1/wave/complete":
                    token = self._bearer_token()
                    self._authorize(token, _WORKER_ROLE)
                    self._post_complete(token, self._json_body())
                    return
                if path == "/v1/wave/capabilities":
                    token = self._bearer_token()
                    self._authorize(token, _ADMIN_ROLE)
                    self._post_capabilities(token, self._json_body())
                    return
                if path == "/healthz":
                    raise _HttpError(
                        405, "method not allowed", headers={"Allow": "GET"}
                    )
                raise _HttpError(404, "not found")
            except Exception as exc:
                self._safe_error(exc)

        def do_PUT(self) -> None:
            self._method_not_allowed()

        def do_PATCH(self) -> None:
            self._method_not_allowed()

        def do_DELETE(self) -> None:
            self._method_not_allowed()

        def do_OPTIONS(self) -> None:
            self._method_not_allowed()

    return WaveRequestHandler


class WaveHttpServer:
    """Lifecycle wrapper around a threaded HTTP server for a ``WaveService``.

    By default the listener binds loopback on an ephemeral port, which makes
    ``start()``/``stop()`` convenient for tests.  Use an explicit host/port and
    a TLS-terminating reverse proxy for a real deployment.
    """

    def __init__(self, service: WaveService, host: str = DEFAULT_HOST,
                 port: int = DEFAULT_PORT, *,
                 store: WaveStore | None = None,
                 max_body_bytes: int = MAX_BODY_BYTES,
                 nmp_adapter: Any = None) -> None:
        # Accept ``WaveHttpServer(service, store)`` as a convenience while
        # keeping the usual ``(service, host, port)`` form.
        if isinstance(host, WaveStore):
            if store is not None:
                raise TypeError("store was supplied twice")
            store = host
            host = DEFAULT_HOST
        if not hasattr(service, "store"):
            raise TypeError("service must be a WaveService-like object with .store")
        if (isinstance(max_body_bytes, bool)
                or not isinstance(max_body_bytes, int) or max_body_bytes < 1):
            raise ValueError("max_body_bytes must be a positive integer")
        if nmp_adapter is not None and getattr(nmp_adapter, "service", None) is not service:
            raise ValueError("NMP adapter must share the WaveHttpServer WaveService instance")
        self.service = service
        self.store: WaveStore = service.store if store is None else store
        self.host = host
        self._requested_port = port
        self.max_body_bytes = max_body_bytes
        self.nmp_adapter = nmp_adapter
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()

    def __repr__(self) -> str:
        return (
            f"WaveHttpServer(host={self.host!r}, port={self.port}, "
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
            raise RuntimeError("wave HTTP server is not running")
        host, port = self.address
        display_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
        return f"http://{display_host}:{port}"

    @property
    def url(self) -> str:
        return self.base_url

    def start(self, host: str | None = None,
              port: int | None = None) -> "WaveHttpServer":
        """Bind and serve on a background daemon thread; returns ``self``."""
        with self._lock:
            if self._httpd is not None:
                raise RuntimeError("wave HTTP server is already running")
            bind_host = self.host if host is None else host
            bind_port = self._requested_port if port is None else port
            httpd = ThreadingHTTPServer(
                (bind_host, bind_port),
                make_wave_handler(
                    self.service, max_body_bytes=self.max_body_bytes,
                    nmp_adapter=self.nmp_adapter,
                ),
            )
            httpd.daemon_threads = True
            thread = threading.Thread(
                target=httpd.serve_forever,
                args=(0.05,),
                name=f"wave-http-{httpd.server_port}",
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

    def __enter__(self) -> "WaveHttpServer":
        return self.start()

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        self.stop()
        return False


__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "MAX_BODY_BYTES",
    "MAX_REQUEST_BYTES",
    "WaveHttpServer",
    "make_wave_handler",
]
