"""Live Koyeb/NANNET0 deployment preflight and signed-registry gate.

The preflight is deliberately read-only.  By default it performs **no network
I/O**: it validates deployment inputs from the environment, verifies the signed
volume registry with :mod:`runner_riddle.volume_registry`, and reports a
deterministic JSON-safe result.  ``probe=True`` (or ``--probe``) additionally
performs a small number of bounded ``GET /healthz`` requests with an explicit
timeout.

Secrets are never written to the report or to a ``repr``.  Evidence contains
only lengths and one-way fingerprints, never raw tokens or HMAC key material.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit, urlunsplit

from .address import AddressError, parse_address
from .budget import (
    DEFAULT_GUEST_BUDGET_BYTES,
    GuestBudget,
    LEGACY_GUEST_BUDGET_BYTES,
    PAGE_BYTES,
    WORD_BYTES,
    from_bytes as guest_budget_from_bytes,
    from_words as guest_budget_from_words,
)
from .point0_bridge import (
    MAX_FRAME_WORDS,
    MAX_PAYLOAD_BYTES,
    POINT_ZERO_ADDRESS,
    POINT_ZERO_WIRE,
)
from .volume_registry import VolumeRegistry, VolumeRegistryError
from .wave_ring_scheduler import MAX_ACTIVE_MEMORY_BYTES, MC0_SLOTS, SLOT_COUNT

SCHEMA = "nanrouter.live-preflight.v1"
DEFAULT_PROBE_TIMEOUT = 2.0
DEFAULT_TIMEOUT = DEFAULT_PROBE_TIMEOUT
MIN_PROBE_TIMEOUT = 0.1
MAX_PROBE_TIMEOUT = 10.0
MAX_PROBE_BYTES = 65_536
MAX_URL_CHARS = 2_048
MIN_SECRET_BYTES = 32
MAX_SECRET_BYTES = 4_096
MAX_REGISTRY_BYTES = 16 * 1024 * 1024

UNIVERSE_PAGES = 256
UNIVERSE_BYTES = UNIVERSE_PAGES * PAGE_BYTES  # 8 MiB
GUEST_BUDGET_BYTES = DEFAULT_GUEST_BUDGET_BYTES  # 2 MiB default
GUEST_PAGES = GUEST_BUDGET_BYTES // PAGE_BYTES  # 64
# A live deployment must still hold the legacy 1 MiB working set; the budget is
# adjustable upward from that floor up to the 8 MiB universe.
MIN_GUEST_BUDGET_BYTES = LEGACY_GUEST_BUDGET_BYTES
MAX_GUEST_BUDGET_BYTES = UNIVERSE_BYTES
ACTIVE_SLOT_POLICY = "single-active"

_HTTP_SCHEMES = frozenset(("http", "https"))
_HEALTH_OK = frozenset(("green", "ok", "healthy", "up", "pass", "ready"))
_HEALTH_BAD = frozenset(
    ("degraded", "unavailable", "down", "failed", "error", "red", "blocked")
)

# Primary names first; aliases exist so a deployment does not fail merely
# because a neighbouring document used the short form.
_ENV_ALIASES: dict[str, tuple[str, ...]] = {
    "bs0db_url": (
        "KOYEB_BS0DB_URL", "BS0DB_URL", "KOYEB_BS0_URL", "BS0_URL",
        "RIDDLE_BS0DB_URL",
    ),
    "bs0db_token": (
        "KOYEB_BS0DB_TOKEN", "BS0DB_TOKEN", "KOYEB_BS0_TOKEN", "BS0_TOKEN",
        "RIDDLE_BS0DB_TOKEN",
    ),
    "mc0db_url": (
        "KOYEB_MC0DB_URL", "MC0DB_URL", "KOYEB_MC0_URL", "MC0_URL",
        "RIDDLE_MC0DB_URL",
    ),
    "mc0db_token": (
        "KOYEB_MC0DB_TOKEN", "MC0DB_TOKEN", "KOYEB_MC0_TOKEN", "MC0_TOKEN",
        "RIDDLE_MC0DB_TOKEN",
    ),
    "nannet0_endpoint": (
        "NANNET0_ENDPOINT", "NANNET_ENDPOINT", "NANNET0_URL", "NANNET_URL",
        "NANNET0_HTTP_ENDPOINT",
    ),
    "volume_registry_path": (
        "RIDDLE_VOLUME_REGISTRY_PATH", "VOLUME_REGISTRY_PATH",
        "RIDDLE_VOLUME_REGISTRY",
    ),
    "volume_hmac_key": (
        "RIDDLE_VOLUME_HMAC_KEY", "VOLUME_REGISTRY_HMAC_KEY",
        "VOLUME_REGISTRY_KEY", "NANROUTER_VOLUME_HMAC_KEY",
    ),
    "volume_key_id": (
        "RIDDLE_VOLUME_KEY_ID", "VOLUME_REGISTRY_KEY_ID",
        "RIDDLE_VOLUME_SIGNING_KEY_ID",
    ),
    "universe_pages": (
        "NANROUTER_UNIVERSE_PAGES", "UNIVERSE_PAGES", "RIDDLE_UNIVERSE_PAGES",
    ),
    "page_bytes": (
        "NANROUTER_PAGE_BYTES", "PAGE_BYTES", "RIDDLE_PAGE_BYTES",
    ),
    "guest_budget_bytes": (
        "NANROUTER_GUEST_BUDGET_BYTES", "GUEST_BUDGET_BYTES",
        "NANROUTER_GUEST_BYTES", "NANROUTER_GUEST_BUDGET",
        "RIDDLE_GUEST_BUDGET_BYTES",
    ),
    "guest_budget_words": (
        "NANROUTER_GUEST_BUDGET_WORDS", "GUEST_BUDGET_WORDS",
        "NANROUTER_GUEST_WORDS", "RIDDLE_GUEST_BUDGET_WORDS",
    ),
    "ring_active_slot_policy": (
        "RIDDLE_RING_ACTIVE_SLOT_POLICY", "RUNNER_RING_ACTIVE_SLOT_POLICY",
        "NANROUTER_ACTIVE_SLOT_POLICY", "RIDDLE_RING_POLICY",
    ),
    "ring_active_slots": (
        "RIDDLE_RING_ACTIVE_SLOTS", "NANROUTER_ACTIVE_SLOTS",
    ),
    "point0_route": (
        "NANROUTER_POINT0_ROUTE", "POINT0_ROUTE", "RIDDLE_POINT0_ROUTE",
        "POINT_ZERO_ROUTE",
    ),
    "expected_generation": (
        "RIDDLE_VOLUME_EXPECTED_GENERATION",
        "VOLUME_REGISTRY_EXPECTED_GENERATION",
    ),
    "minimum_generation": (
        "RIDDLE_VOLUME_MIN_GENERATION", "VOLUME_REGISTRY_MIN_GENERATION",
    ),
    "max_observation_age_ticks": (
        "RIDDLE_VOLUME_MAX_AGE_TICKS", "VOLUME_REGISTRY_MAX_AGE_TICKS",
    ),
    "now_tick": ("NANCLOCK_TICK", "RIDDLE_NANCLOCK_TICK"),
}

ProbeTransport = Callable[
    [str, Mapping[str, str], float, int],
    tuple[int, bytes, str],
]


class LivePreflightError(ValueError):
    """A deployment input or signed-registry gate failed closed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class DeploymentConfig:
    """Validated deployment inputs.

    Secret fields use ``repr=False``; :meth:`__repr__` is explicit about the
    redaction so debugging a config object cannot print a token or HMAC key.
    """

    bs0db_url: str = ""
    bs0db_token: str = field(default="", repr=False)
    mc0db_url: str = ""
    mc0db_token: str = field(default="", repr=False)
    nannet0_endpoint: str = ""
    volume_registry_path: str = ""
    volume_hmac_key: bytes = field(default=b"", repr=False)
    volume_key_id: str = ""
    universe_pages: int = UNIVERSE_PAGES
    page_bytes: int = PAGE_BYTES
    guest_budget_bytes: int = GUEST_BUDGET_BYTES
    guest_budget_words: int | None = None
    ring_active_slot_policy: str = ACTIVE_SLOT_POLICY
    point0_route: str = POINT_ZERO_ADDRESS
    expected_generation: int | None = None
    minimum_generation: int | None = None
    max_observation_age_ticks: int | None = None
    now_tick: int | None = None

    def __repr__(self) -> str:
        return (
            "DeploymentConfig("
            f"bs0db_url={self.bs0db_url!r}, bs0db_token=<redacted>, "
            f"mc0db_url={self.mc0db_url!r}, mc0db_token=<redacted>, "
            f"nannet0_endpoint={self.nannet0_endpoint!r}, "
            f"volume_registry_path={self.volume_registry_path!r}, "
            "volume_hmac_key=<redacted>, "
            f"volume_key_id={self.volume_key_id!r}, "
            f"universe_pages={self.universe_pages}, "
            f"page_bytes={self.page_bytes}, "
            f"guest_budget_bytes={self.guest_budget_bytes}, "
            f"guest_budget_words={self.guest_budget_words}, "
            f"ring_active_slot_policy={self.ring_active_slot_policy!r}, "
            f"point0_route={self.point0_route!r}, "
            f"expected_generation={self.expected_generation}, "
            f"minimum_generation={self.minimum_generation}, "
            f"max_observation_age_ticks={self.max_observation_age_ticks}, "
            f"now_tick={self.now_tick})"
        )


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _digest_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _digest_secret(value: bytes) -> str:
    """One-way evidence for a secret; the raw value never reaches the report."""
    return hashlib.sha256(
        b"nanrouter.live-preflight.secret.v1\x00" + value
    ).hexdigest()


def _bounded(value: Any, limit: int = 240) -> str:
    text = " ".join(str(value).split())
    return text[: max(1, limit - 3)] + "..." if len(text) > limit else text


def _check(
    check_id: str,
    status: str,
    message: str,
    **evidence: Any,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": status,
        "message": _bounded(message),
        "evidence": evidence,
    }


def _env_pick(
    environ: Mapping[str, str], field_name: str, *, strip: bool = True
) -> tuple[str | None, str | None, str | None]:
    """Return (value, source_name, conflict_message) for one logical field."""
    values: list[tuple[str, str]] = []
    for name in _ENV_ALIASES[field_name]:
        if name not in environ or environ[name] is None:
            continue
        raw = environ[name]
        if not isinstance(raw, str):
            raw = str(raw)
        text = raw.strip() if strip else raw
        if text:
            values.append((name, text))
    if not values:
        return None, None, None
    source, value = values[0]
    for other_name, other_value in values[1:]:
        if other_value != value:
            return value, source, (
                f"conflicting values for {source} and {other_name}"
            )
    return value, source, None


def _collect_inputs(
    environ: Mapping[str, str], overrides: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, str], dict[str, str | None]]:
    raw: dict[str, Any] = {}
    issues: dict[str, str] = {}
    sources: dict[str, str | None] = {}
    for field_name in _ENV_ALIASES:
        strip = field_name not in ("volume_hmac_key", "bs0db_token", "mc0db_token")
        if overrides.get(field_name) is not None:
            raw[field_name] = overrides[field_name]
            sources[field_name] = "argument"
            continue
        value, source, conflict = _env_pick(
            environ, field_name, strip=strip
        )
        raw[field_name] = value
        sources[field_name] = source
        if conflict is not None:
            issues[field_name] = conflict
    return raw, issues, sources


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _as_int(value: Any) -> int:
    if _is_int(value):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    raise LivePreflightError(
        "invalid_integer", "value must be a nonnegative base-10 integer"
    )


def _optional_int(
    value: Any,
    name: str,
    *,
    minimum: int = 0,
) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = _as_int(value)
    except LivePreflightError as exc:
        raise LivePreflightError(
            "invalid_integer", f"{name} must be a nonnegative integer"
        ) from exc
    if number < minimum:
        raise LivePreflightError(
            "invalid_integer", f"{name} must be at least {minimum}"
        )
    return number


def _resolve_guest_budget(
    raw: Mapping[str, Any],
) -> tuple[GuestBudget | None, str | None, str | None]:
    """Resolve the deployment guest budget through the shared budget model.

    Returns ``(budget, error_code, error_message)``.  A valid budget is positive,
    word aligned, at least the legacy 1 MiB floor, and no larger than the 8 MiB
    universe.  Words and bytes may be supplied together only when they agree.
    """
    words_raw = raw.get("guest_budget_words")
    bytes_raw = raw.get("guest_budget_bytes")
    words_given = words_raw not in (None, "")
    bytes_given = bytes_raw not in (None, "")
    if not words_given and not bytes_given:
        return None, "guest_budget_required", (
            "guest budget is required "
            f"({_ENV_ALIASES['guest_budget_bytes'][0]} or "
            f"{_ENV_ALIASES['guest_budget_words'][0]})"
        )
    try:
        words = (
            _optional_int(words_raw, "guest_budget_words", minimum=1)
            if words_given else None
        )
        size = (
            _optional_int(bytes_raw, "guest_budget_bytes", minimum=1)
            if bytes_given else None
        )
    except LivePreflightError as exc:
        return None, "invalid_guest_budget", exc.message
    try:
        if words is not None and size is not None:
            if words * WORD_BYTES != size:
                return None, "guest_budget_mismatch", (
                    f"guest_budget_words ({words}) and "
                    f"guest_budget_bytes ({size}) disagree"
                )
            budget = guest_budget_from_words(words)
        elif words is not None:
            budget = guest_budget_from_words(words)
        elif size is not None:
            budget = guest_budget_from_bytes(size)
        else:  # pragma: no cover - guarded by the required-input check
            return None, "guest_budget_required", "guest budget is required"
    except ValueError as exc:
        return None, "invalid_guest_budget", f"guest budget: {exc}"
    if budget.bytes < MIN_GUEST_BUDGET_BYTES:
        return None, "guest_budget_below_legacy_floor", (
            f"guest_budget_bytes must be at least {MIN_GUEST_BUDGET_BYTES} "
            f"(legacy 1 MiB floor); got {budget.bytes}"
        )
    if budget.bytes > MAX_GUEST_BUDGET_BYTES:
        return None, "guest_budget_exceeds_universe", (
            f"guest_budget_bytes must be at most {MAX_GUEST_BUDGET_BYTES} "
            f"(8 MiB universe); got {budget.bytes}"
        )
    return budget, None, None


def _validate_http_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return "a non-empty HTTP(S) URL is required"
    text = value.strip()
    if len(text) > MAX_URL_CHARS:
        return f"URL must be at most {MAX_URL_CHARS} characters"
    if any(char.isspace() or ord(char) < 0x20 for char in text):
        return "URL must not contain whitespace or control characters"
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        return "URL has an invalid port"
    if parts.scheme.lower() not in _HTTP_SCHEMES:
        return "URL scheme must be http or https"
    if not parts.hostname:
        return "URL must include a host"
    if parts.username or parts.password:
        return "URL must not embed credentials; use the token variable"
    if port is not None and not 1 <= port <= 65535:
        return "URL port must be in 1..65535"
    return None


def _redact_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parts = urlsplit(text)
        host = parts.hostname or ""
        port = parts.port
    except ValueError:
        return "<invalid-url>"
    if not host:
        return "<invalid-url>"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host + (f":{port}" if port is not None else "")
    segments = []
    for segment in parts.path.split("/"):
        if len(segment) > 48:
            segment = "<redacted>"
        segments.append(segment)
    path = "/".join(segments)
    return urlunsplit((parts.scheme.lower(), netloc, path, "", ""))


def _secret_evidence(value: Any) -> dict[str, Any]:
    if value is None:
        return {"configured": False, "length": 0, "digest": None}
    if isinstance(value, bytes):
        raw = value
    elif isinstance(value, str):
        raw = value.encode("utf-8")
    else:
        raw = b""
    return {
        "configured": bool(raw),
        "length": len(raw),
        "digest": _digest_secret(raw) if raw else None,
    }


def _validate_secret(
    value: Any, label: str, *, minimum: int = MIN_SECRET_BYTES
) -> str | None:
    if value is None or value == "":
        return f"{label} is required"
    if isinstance(value, bytes):
        raw = value
        text = None
    elif isinstance(value, str):
        raw = value.encode("utf-8")
        text = value
    else:
        return f"{label} must be a string or bytes"
    if len(raw) < minimum:
        return f"{label} must be at least {minimum} bytes"
    if len(raw) > MAX_SECRET_BYTES:
        return f"{label} must be at most {MAX_SECRET_BYTES} bytes"
    if text is not None and any(
        char.isspace() or ord(char) < 0x20 for char in text
    ):
        return f"{label} must not contain whitespace or control characters"
    return None


def _validate_key_id(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        return "volume registry key reference must be a string"
    if len(value) > 128:
        return "volume registry key reference must be at most 128 characters"
    if any(
        not (char.isalnum() or char in "._:-")
        for char in value
    ):
        return "volume registry key reference contains unsupported characters"
    return None


def _validate_route(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return "point-0 route is required"
    text = value.strip()
    if text == POINT_ZERO_WIRE:
        return None
    if text != POINT_ZERO_ADDRESS:
        return f"route must be {POINT_ZERO_ADDRESS!r} (or wire {POINT_ZERO_WIRE!r})"
    try:
        parsed = parse_address(text)
    except AddressError:
        return "route is not a valid NaN address"
    if parsed.root != POINT_ZERO_ADDRESS or text != parsed.root:
        return "route must be the canonical point-0 root without selectors"
    return None


def _normalise_slot_policy(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().lower().replace("_", "-")
    return "-".join(text.split())


def _read_registry_document(path: str | Path) -> dict[str, Any] | None:
    try:
        target = Path(path)
        if target.stat().st_size > MAX_REGISTRY_BYTES:
            return None
        document = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        return None
    return document if isinstance(document, dict) else None


def _classify_registry_failure(
    exc: BaseException,
    path: str | Path | None,
    *,
    document: Mapping[str, Any] | None = None,
) -> LivePreflightError:
    if document is None:
        document = _read_registry_document(path) if path is not None else None
    if document is None:
        return LivePreflightError(
            "registry_unavailable",
            "volume registry is missing, unreadable, or invalid JSON",
        )
    if not document.get("signature"):
        return LivePreflightError(
            "unsigned_registry", "unsigned volume registry is rejected"
        )
    if not document.get("registry_digest"):
        return LivePreflightError(
            "missing_registry_digest", "volume registry digest is missing"
        )
    text = str(exc)
    if "digest mismatch" in text:
        return LivePreflightError(
            "digest_mismatch", "wrong volume registry digest is rejected"
        )
    if "signature mismatch" in text:
        return LivePreflightError(
            "signature_mismatch", "invalid volume registry signature is rejected"
        )
    return LivePreflightError(
        "invalid_registry",
        f"invalid volume registry: {_bounded(text, 180)}",
    )


def load_signed_registry(
    path: str | Path, key: str | bytes
) -> VolumeRegistry:
    """Verify a registry digest/signature offline using the existing authority.

    No network, filesystem write, mount, or provider call is performed.
    """
    if isinstance(key, str):
        key_bytes = key.encode("utf-8")
    elif isinstance(key, bytes):
        key_bytes = key
    else:
        raise LivePreflightError(
            "invalid_key", "volume registry key must be bytes or text"
        )
    if len(key_bytes) < MIN_SECRET_BYTES:
        raise LivePreflightError(
            "invalid_key",
            f"volume registry key must be at least {MIN_SECRET_BYTES} bytes",
        )
    try:
        return VolumeRegistry.load(path, key_bytes)
    except (VolumeRegistryError, OSError, TypeError, ValueError) as exc:
        raise _classify_registry_failure(exc, path) from exc


def _assert_registry_epoch(
    registry: VolumeRegistry,
    *,
    expected_generation: int | None = None,
    minimum_generation: int | None = None,
    now_tick: int | None = None,
    max_observation_age_ticks: int | None = None,
) -> None:
    document = registry.document
    generation = int(document["generation"])
    if expected_generation is not None and generation != expected_generation:
        raise LivePreflightError(
            "stale_generation",
            (
                f"stale volume registry epoch: generation {generation} does not "
                f"match required generation {expected_generation}"
            ),
        )
    if minimum_generation is not None and generation < minimum_generation:
        raise LivePreflightError(
            "stale_generation",
            (
                f"stale volume registry epoch: generation {generation} is older "
                f"than required minimum {minimum_generation}"
            ),
        )
    if max_observation_age_ticks is not None:
        if now_tick is None:
            raise LivePreflightError(
                "missing_clock",
                "now_tick is required when a maximum observation age is set",
            )
        for item in document["volumes"]:
            observed = int(item["observed_at_tick"])
            age = now_tick - observed
            if age < 0:
                raise LivePreflightError(
                    "clock_regression",
                    (
                        f"volume {item['tier']}:{item['shard']} observation is "
                        "newer than the supplied clock"
                    ),
                )
            if age > max_observation_age_ticks:
                raise LivePreflightError(
                    "stale_observation",
                    (
                        f"stale volume observation: {item['tier']}:{item['shard']} "
                        f"age {age} exceeds {max_observation_age_ticks} ticks"
                    ),
                )


def verify_signed_registry(
    path: str | Path,
    key: str | bytes,
    *,
    expected_generation: int | None = None,
    minimum_generation: int | None = None,
    now_tick: int | None = None,
    max_observation_age_ticks: int | None = None,
) -> VolumeRegistry:
    """Load and verify a registry, then enforce the configured epoch floor.

    The registry is rejected before any staleness decision if its digest or
    signature is invalid.
    """
    registry = load_signed_registry(path, key)
    _assert_registry_epoch(
        registry,
        expected_generation=expected_generation,
        minimum_generation=minimum_generation,
        now_tick=now_tick,
        max_observation_age_ticks=max_observation_age_ticks,
    )
    return registry


def _health_url(base_url: str) -> str:
    parts = urlsplit(base_url)
    path = parts.path.rstrip("/")
    if not path.endswith("/healthz"):
        path = f"{path}/healthz"
    return urlunsplit((parts.scheme, parts.netloc, path or "/healthz", "", ""))


def _default_probe_transport(
    url: str, headers: Mapping[str, str], timeout: float, max_bytes: int
) -> tuple[int, bytes, str]:
    request = urllib.request.Request(
        url, headers=dict(headers), method="GET"
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        status = int(getattr(response, "status", 0) or response.getcode())
        body = response.read(max_bytes + 1)
        content_type = ""
        if response.headers is not None:
            content_type = response.headers.get("Content-Type", "")
    return status, body, content_type


def _probe_health(body: bytes, content_type: str) -> str | None:
    if not body:
        return None
    looks_json = "json" in content_type.lower() or body.lstrip().startswith(b"{")
    if not looks_json:
        return None
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    for name in ("health", "status", "state"):
        candidate = value.get(name)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip().lower()
    return None


def _probe_check(
    check_id: str,
    endpoint: str,
    headers: Mapping[str, str],
    *,
    timeout: float,
    transport: ProbeTransport,
) -> dict[str, Any]:
    target = _health_url(endpoint)
    evidence: dict[str, Any] = {
        "endpoint": _redact_url(target),
        "method": "GET",
        "timeout_seconds": timeout,
        "max_body_bytes": MAX_PROBE_BYTES,
    }
    try:
        result = transport(target, headers, timeout, MAX_PROBE_BYTES)
        if not isinstance(result, tuple) or len(result) != 3:
            return _check(
                check_id, "fail", "probe transport returned an invalid result",
                **evidence,
            )
        status, body, content_type = result
        if not _is_int(status):
            return _check(
                check_id, "fail", "probe returned an invalid status", **evidence
            )
        if not isinstance(body, (bytes, bytearray)):
            return _check(
                check_id, "fail", "probe returned an invalid body", **evidence
            )
        body = bytes(body)
        evidence.update({
            "http_status": status,
            "body_bytes": len(body),
            "body_digest": hashlib.sha256(body).hexdigest(),
            "content_type": _bounded(str(content_type), 80),
        })
        if len(body) > MAX_PROBE_BYTES:
            return _check(
                check_id, "fail",
                f"probe response exceeds {MAX_PROBE_BYTES} bytes",
                **evidence,
            )
        if not 200 <= status <= 299:
            return _check(
                check_id, "fail", f"probe returned HTTP {status}", **evidence
            )
        health = _probe_health(body, str(content_type))
        evidence["health"] = health
        if health in _HEALTH_BAD:
            return _check(
                check_id, "fail", f"probe reported health={health}", **evidence
            )
        if health is not None and health not in _HEALTH_OK:
            return _check(
                check_id, "fail", f"probe reported unknown health={health}",
                **evidence,
            )
        return _check(check_id, "pass", "bounded health probe passed", **evidence)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError) as exc:
        evidence["error_type"] = type(exc).__name__
        status = getattr(exc, "code", None)
        if _is_int(status):
            evidence["http_status"] = status
        return _check(
            check_id, "fail", "bounded health probe failed", **evidence
        )
    except Exception as exc:  # pragma: no cover - defensive transport boundary
        evidence["error_type"] = type(exc).__name__
        return _check(
            check_id, "fail", "bounded health probe failed", **evidence
        )


def _report_status(checks: list[dict[str, Any]]) -> str:
    return "blocked" if any(c["status"] == "fail" for c in checks) else "green"


def _summary(checks: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(checks),
        "passed": sum(c["status"] == "pass" for c in checks),
        "failed": sum(c["status"] == "fail" for c in checks),
        "skipped": sum(c["status"] == "skip" for c in checks),
    }


def preflight_report(
    environ: Mapping[str, str] | None = None,
    *,
    probe: bool = False,
    timeout: float = DEFAULT_PROBE_TIMEOUT,
    bs0db_url: str | None = None,
    bs0db_token: str | None = None,
    mc0db_url: str | None = None,
    mc0db_token: str | None = None,
    nannet0_endpoint: str | None = None,
    volume_registry_path: str | os.PathLike[str] | None = None,
    volume_hmac_key: str | bytes | None = None,
    registry_path: str | os.PathLike[str] | None = None,
    registry_key: str | bytes | None = None,
    volume_key_id: str | None = None,
    universe_pages: int | str | None = None,
    page_bytes: int | str | None = None,
    guest_budget_bytes: int | str | None = None,
    guest_budget_words: int | str | None = None,
    ring_active_slot_policy: str | None = None,
    ring_active_slots: int | str | None = None,
    point0_route: str | None = None,
    expected_generation: int | str | None = None,
    minimum_generation: int | str | None = None,
    max_observation_age_ticks: int | str | None = None,
    now_tick: int | str | None = None,
    registry: VolumeRegistry | Mapping[str, Any] | None = None,
    probe_transport: ProbeTransport | None = None,
) -> dict[str, Any]:
    """Return a deterministic, JSON-safe deployment preflight report.

    Missing or invalid required inputs produce ``status="blocked"`` with one
    explicit failed check per input.  The registry is verified offline with the
    existing :class:`~runner_riddle.volume_registry.VolumeRegistry` authority.
    ``probe=False`` (the default) performs no network I/O at all.
    """
    if volume_registry_path is None:
        volume_registry_path = registry_path
    if volume_hmac_key is None:
        volume_hmac_key = registry_key
    env = dict(os.environ if environ is None else environ)
    overrides = {
        "bs0db_url": bs0db_url,
        "bs0db_token": bs0db_token,
        "mc0db_url": mc0db_url,
        "mc0db_token": mc0db_token,
        "nannet0_endpoint": nannet0_endpoint,
        "volume_registry_path": volume_registry_path,
        "volume_hmac_key": volume_hmac_key,
        "volume_key_id": volume_key_id,
        "universe_pages": universe_pages,
        "page_bytes": page_bytes,
        "guest_budget_bytes": guest_budget_bytes,
        "guest_budget_words": guest_budget_words,
        "ring_active_slot_policy": ring_active_slot_policy,
        "ring_active_slots": ring_active_slots,
        "point0_route": point0_route,
        "expected_generation": expected_generation,
        "minimum_generation": minimum_generation,
        "max_observation_age_ticks": max_observation_age_ticks,
        "now_tick": now_tick,
    }
    raw, issues, sources = _collect_inputs(env, overrides)

    checks: list[dict[str, Any]] = []
    url_ok: dict[str, bool] = {}
    token_ok: dict[str, bool] = {}

    def add_required_source(check_id: str, field_name: str, label: str) -> bool:
        if field_name in issues:
            checks.append(_check(
                check_id, "fail", issues[field_name],
                source=sources.get(field_name), configured=False,
            ))
            return False
        if raw.get(field_name) is None:
            names = _ENV_ALIASES[field_name]
            checks.append(_check(
                check_id, "fail",
                f"{label} is required ({names[0]})",
                source=None, configured=False,
            ))
            return False
        return True

    def add_url(check_id: str, field_name: str, label: str) -> bool:
        if not add_required_source(check_id, field_name, label):
            url_ok[field_name] = False
            return False
        value = raw.get(field_name)
        error = _validate_http_url(value)
        ok = error is None
        url_ok[field_name] = ok
        if error is not None:
            checks.append(_check(
                check_id, "fail", f"{label}: {error}",
                source=sources.get(field_name),
                configured=bool(value),
            ))
        else:
            checks.append(_check(
                check_id, "pass", f"{label} is configured",
                source=sources.get(field_name),
                url=_redact_url(value),
                url_digest=_digest_text(_redact_url(value) or ""),
            ))
        return ok

    def add_secret(check_id: str, field_name: str, label: str) -> bool:
        if not add_required_source(check_id, field_name, label):
            token_ok[field_name] = False
            return False
        value = raw.get(field_name)
        error = _validate_secret(value, label, minimum=1)
        ok = error is None
        token_ok[field_name] = ok
        if error is not None:
            checks.append(_check(
                check_id, "fail", error,
                source=sources.get(field_name),
                configured=bool(value),
            ))
        else:
            checks.append(_check(
                check_id, "pass", f"{label} is configured and well formed",
                source=sources.get(field_name),
                **_secret_evidence(value),
            ))
        return ok

    # -- Koyeb ingress databases -------------------------------------------
    add_url("koyeb.bs0db.url", "bs0db_url", "Koyeb BS0DB URL")
    add_secret("koyeb.bs0db.token", "bs0db_token", "Koyeb BS0DB token")
    add_url("koyeb.mc0db.url", "mc0db_url", "Koyeb MC0DB URL")
    add_secret("koyeb.mc0db.token", "mc0db_token", "Koyeb MC0DB token")
    add_url("nannet0.endpoint", "nannet0_endpoint", "NANNET0 endpoint")

    # -- Volume registry key -------------------------------------------------
    key_source_ok = add_required_source(
        "volume.registry.key", "volume_hmac_key", "Volume registry HMAC key"
    )
    key_bytes = b""
    key_ok = False
    if not key_source_ok:
        key_ok = False
    else:
        key_value = raw.get("volume_hmac_key")
        key_error = _validate_secret(key_value, "Volume registry HMAC key")
        if isinstance(key_value, bytes):
            key_bytes = key_value
        elif isinstance(key_value, str):
            key_bytes = key_value.encode("utf-8")
        key_ok = key_error is None
        key_id = raw.get("volume_key_id")
        key_id_error = _validate_key_id(key_id)
        if key_error is not None:
            checks.append(_check(
                "volume.registry.key", "fail", key_error,
                source=sources.get("volume_hmac_key"),
                configured=bool(key_value),
            ))
        elif key_id_error is not None:
            checks.append(_check(
                "volume.registry.key", "fail", key_id_error,
                source=sources.get("volume_key_id"), configured=True,
            ))
        else:
            fingerprint = _digest_secret(key_bytes)
            checks.append(_check(
                "volume.registry.key", "pass",
                "volume registry signing key is configured",
                source=sources.get("volume_hmac_key"),
                authority="hmac-sha256",
                key_reference=(
                    key_id if key_id else f"hmac-sha256:{fingerprint[:16]}"
                ),
                key_fingerprint=fingerprint,
                **_secret_evidence(key_value),
            ))

    # -- Registry path -------------------------------------------------------
    registry_path = raw.get("volume_registry_path")
    path_ok = False
    if registry is not None:
        path_ok = True
        checks.append(_check(
            "volume.registry.path", "pass",
            "in-memory registry supplied",
            source="argument", injected=True,
        ))
    elif "volume_registry_path" in issues:
        checks.append(_check(
            "volume.registry.path", "fail", issues["volume_registry_path"],
            source=sources.get("volume_registry_path"), configured=False,
        ))
    elif registry_path is None:
        checks.append(_check(
            "volume.registry.path", "fail",
            f"volume registry path is required ({_ENV_ALIASES['volume_registry_path'][0]})",
            source=None, configured=False,
        ))
    else:
        try:
            target = Path(str(registry_path))
            exists = target.exists() and target.is_file()
            size = target.stat().st_size if exists else 0
        except (OSError, TypeError, ValueError):
            target = None
            exists = False
            size = 0
        if target is None or not target.is_absolute():
            checks.append(_check(
                "volume.registry.path", "fail",
                "volume registry path must be an absolute path",
                source=sources.get("volume_registry_path"),
                configured=True,
            ))
        elif not exists:
            checks.append(_check(
                "volume.registry.path", "fail",
                "volume registry file does not exist",
                source=sources.get("volume_registry_path"),
                configured=True,
            ))
        elif size > MAX_REGISTRY_BYTES:
            checks.append(_check(
                "volume.registry.path", "fail",
                f"volume registry exceeds {MAX_REGISTRY_BYTES} bytes",
                source=sources.get("volume_registry_path"),
                configured=True,
            ))
        else:
            path_ok = True
            checks.append(_check(
                "volume.registry.path", "pass",
                "volume registry path is readable",
                source=sources.get("volume_registry_path"),
                configured=True,
                path_digest=_digest_text(str(target)),
            ))

    # -- Registry signature and epoch ---------------------------------------
    expected = None
    minimum = None
    max_age = None
    tick = None
    epoch_config_error = None
    try:
        expected = _optional_int(raw.get("expected_generation"), "expected_generation")
        minimum = _optional_int(raw.get("minimum_generation"), "minimum_generation")
        max_age = _optional_int(
            raw.get("max_observation_age_ticks"), "max_observation_age_ticks"
        )
        tick = _optional_int(raw.get("now_tick"), "now_tick")
    except LivePreflightError as exc:
        epoch_config_error = exc.message

    registry_obj: VolumeRegistry | None = None
    signature_ok = False
    if epoch_config_error is not None:
        checks.append(_check(
            "volume.registry.signature", "skip",
            "registry signature not evaluated: invalid epoch configuration",
            reason=epoch_config_error,
        ))
    elif not key_ok:
        checks.append(_check(
            "volume.registry.signature", "skip",
            "registry signature not evaluated: signing key is invalid",
        ))
    elif not path_ok:
        checks.append(_check(
            "volume.registry.signature", "skip",
            "registry signature not evaluated: registry path is invalid",
        ))
    else:
        document_in: Mapping[str, Any] | None = None
        try:
            if registry is not None:
                if not key_bytes:
                    raise LivePreflightError(
                        "invalid_key", "volume registry key is required"
                    )
                if isinstance(registry, VolumeRegistry):
                    document_in = registry.document
                elif isinstance(registry, Mapping):
                    document_in = dict(registry)
                else:
                    raise LivePreflightError(
                        "invalid_registry",
                        "in-memory registry must be a VolumeRegistry or mapping",
                    )
                registry_obj = VolumeRegistry(dict(document_in), key_bytes)
                source = "argument"
            else:
                registry_obj = load_signed_registry(str(registry_path), key_bytes)
                source = "file"
            signature_ok = True
            document = registry_obj.document
            checks.append(_check(
                "volume.registry.signature", "pass",
                "volume registry digest and signature are valid",
                source=source,
                signature_authority="hmac-sha256",
                registry_digest=document["registry_digest"],
                network_id=document["network_id"],
                generation=document["generation"],
            ))
        except LivePreflightError as exc:
            checks.append(_check(
                "volume.registry.signature", "fail", exc.message,
                code=exc.code,
            ))
        except VolumeRegistryError as exc:
            classified = _classify_registry_failure(
                exc, registry_path, document=document_in
            ) if document_in is not None else None
            checks.append(_check(
                "volume.registry.signature", "fail",
                (
                    classified.message if classified is not None
                    else f"invalid volume registry: {_bounded(str(exc), 180)}"
                ),
                code=(
                    classified.code if classified is not None
                    else "invalid_registry"
                ),
            ))

    if epoch_config_error is not None:
        checks.append(_check(
            "volume.registry.generation", "fail", epoch_config_error,
            code="invalid_integer",
        ))
    elif not signature_ok or registry_obj is None:
        checks.append(_check(
            "volume.registry.generation", "skip",
            "registry epoch not evaluated: signature is not valid",
        ))
    else:
        try:
            _assert_registry_epoch(
                registry_obj,
                expected_generation=expected,
                minimum_generation=minimum,
                now_tick=tick,
                max_observation_age_ticks=max_age,
            )
            checks.append(_check(
                "volume.registry.generation", "pass",
                "volume registry epoch is current",
                generation=registry_obj.document["generation"],
                expected_generation=expected,
                minimum_generation=minimum,
                max_observation_age_ticks=max_age,
                now_tick=tick,
            ))
        except LivePreflightError as exc:
            checks.append(_check(
                "volume.registry.generation", "fail", exc.message,
                code=exc.code,
                generation=registry_obj.document["generation"],
                expected_generation=expected,
                minimum_generation=minimum,
                max_observation_age_ticks=max_age,
                now_tick=tick,
            ))

    if not signature_ok or registry_obj is None:
        checks.append(_check(
            "volume.registry.health", "skip",
            "registry health not evaluated: signature is not valid",
        ))
    else:
        health = registry_obj.health
        if health == "green":
            checks.append(_check(
                "volume.registry.health", "pass",
                "all canonical tier volumes are green and mount-verified",
                health=health,
            ))
        else:
            checks.append(_check(
                "volume.registry.health", "fail",
                f"volume registry health is {health}, not green",
                health=health,
            ))

    # -- Universe / page budget ---------------------------------------------
    pages_ok = False
    try:
        pages = _as_int(raw.get("universe_pages"))
        pages_ok = pages == UNIVERSE_PAGES
        message = (
            "universe page count matches the 256-page / 8 MiB design"
            if pages_ok
            else f"universe_pages must be {UNIVERSE_PAGES}"
        )
        checks.append(_check(
            "universe.pages", "pass" if pages_ok else "fail", message,
            value=pages, required=UNIVERSE_PAGES,
            source=sources.get("universe_pages"),
        ))
    except LivePreflightError as exc:
        checks.append(_check(
            "universe.pages", "fail", f"universe_pages: {exc.message}",
            required=UNIVERSE_PAGES, source=sources.get("universe_pages"),
        ))

    page_bytes_ok = False
    try:
        page_size = _as_int(raw.get("page_bytes"))
        page_bytes_ok = page_size == PAGE_BYTES
        message = (
            "page size matches the 32 KiB NaN16 page"
            if page_bytes_ok
            else f"page_bytes must be {PAGE_BYTES}"
        )
        checks.append(_check(
            "universe.page_bytes", "pass" if page_bytes_ok else "fail", message,
            value=page_size, required=PAGE_BYTES,
            source=sources.get("page_bytes"),
        ))
    except LivePreflightError as exc:
        checks.append(_check(
            "universe.page_bytes", "fail", f"page_bytes: {exc.message}",
            required=PAGE_BYTES, source=sources.get("page_bytes"),
        ))

    guest_budget, guest_error_code, guest_error_message = _resolve_guest_budget(raw)
    guest_ok = guest_budget is not None
    runtime_guest_bytes = (
        guest_budget.bytes if guest_budget is not None else GUEST_BUDGET_BYTES
    )
    guest_source = (
        sources.get("guest_budget_words")
        if raw.get("guest_budget_words") not in (None, "")
        else sources.get("guest_budget_bytes")
    )
    if guest_budget is not None:
        checks.append(_check(
            "universe.guest_budget", "pass",
            (
                f"guest budget is {guest_budget.bytes} bytes / "
                f"{guest_budget.words} NaN16 words / {guest_budget.pages} pages"
            ),
            value=guest_budget.bytes,
            required=GUEST_BUDGET_BYTES,
            minimum_bytes=MIN_GUEST_BUDGET_BYTES,
            maximum_bytes=MAX_GUEST_BUDGET_BYTES,
            word_bytes=WORD_BYTES,
            guest_words=guest_budget.words,
            guest_pages=guest_budget.pages,
            guest_slack_words=guest_budget.slack_words,
            source=guest_source,
        ))
    else:
        checks.append(_check(
            "universe.guest_budget", "fail",
            guest_error_message or "guest budget is invalid",
            code=guest_error_code,
            value=(
                raw.get("guest_budget_words")
                if raw.get("guest_budget_words") not in (None, "")
                else raw.get("guest_budget_bytes")
            ),
            required=GUEST_BUDGET_BYTES,
            minimum_bytes=MIN_GUEST_BUDGET_BYTES,
            maximum_bytes=MAX_GUEST_BUDGET_BYTES,
            word_bytes=WORD_BYTES,
            source=guest_source,
        ))

    if pages_ok and page_bytes_ok and guest_budget is not None:
        universe_bytes = pages * page_size
        budget_consistent = (
            universe_bytes == UNIVERSE_BYTES
            and guest_budget.bytes <= universe_bytes
            and guest_budget.pages <= pages
        )
        checks.append(_check(
            "universe.budget_consistency",
            "pass" if budget_consistent else "fail",
            (
                "universe/page/guest budget is internally consistent"
                if budget_consistent
                else "universe/page/guest budget is inconsistent"
            ),
            universe_bytes=universe_bytes,
            guest_bytes=guest_budget.bytes,
            guest_words=guest_budget.words,
            guest_pages=guest_budget.pages,
            guest_slack_words=guest_budget.slack_words,
            expected_universe_bytes=UNIVERSE_BYTES,
            max_guest_pages=UNIVERSE_PAGES,
        ))
    else:
        checks.append(_check(
            "universe.budget_consistency", "skip",
            "budget consistency not evaluated: a budget input is invalid",
        ))

    # -- Runner-ring active-slot policy -------------------------------------
    policy_value = raw.get("ring_active_slot_policy")
    policy = _normalise_slot_policy(policy_value)
    active_slots = None
    active_slots_error = None
    if raw.get("ring_active_slots") is not None:
        try:
            active_slots = _as_int(raw.get("ring_active_slots"))
        except LivePreflightError as exc:
            active_slots_error = exc.message
    policy_ok = policy == ACTIVE_SLOT_POLICY
    if policy is None and active_slots == 1:
        # A deployment may state the policy as an active-slot count instead.
        policy_ok = True
    if active_slots_error is not None:
        policy_ok = False
    elif active_slots is not None and active_slots != 1:
        policy_ok = False
    checks.append(_check(
        "runner_ring.active_slot_policy",
        "pass" if policy_ok else "fail",
        (
            "runner ring policy is single-active"
            if policy_ok
            else (
                active_slots_error
                or f"ring_active_slot_policy must be {ACTIVE_SLOT_POLICY!r}"
            )
        ),
        value=policy,
        required=ACTIVE_SLOT_POLICY,
        active_slots=active_slots,
        source=(
            sources.get("ring_active_slot_policy")
            if policy is not None else sources.get("ring_active_slots")
        ),
    ))

    inventory_ok = (
        SLOT_COUNT == 6
        and len(MC0_SLOTS) == 6
        and tuple(MC0_SLOTS) == tuple(f"MC0:0/R{i}" for i in range(6))
    )
    checks.append(_check(
        "runner_ring.slot_inventory",
        "pass" if inventory_ok else "fail",
        (
            "runner ring exposes exactly MC0:0/R0..R5"
            if inventory_ok
            else "runner ring slot inventory is not MC0:0/R0..R5"
        ),
        slot_count=SLOT_COUNT,
        slots=list(MC0_SLOTS),
        active_memory_ceiling_bytes=MAX_ACTIVE_MEMORY_BYTES,
    ))

    # -- Point-0 route -------------------------------------------------------
    route_value = raw.get("point0_route")
    route_error = _validate_route(route_value)
    route_ok = route_error is None
    if route_error is not None:
        checks.append(_check(
            "point0.route", "fail", route_error,
            source=sources.get("point0_route"), configured=bool(route_value),
        ))
    else:
        checks.append(_check(
            "point0.route", "pass",
            "point-0 route is the stable canonical ingress",
            route=POINT_ZERO_ADDRESS,
            wire=POINT_ZERO_WIRE,
            active_slot_in_route=False,
            frame_bound_words=MAX_FRAME_WORDS,
            frame_bound_bytes=MAX_PAYLOAD_BYTES,
            source=sources.get("point0_route"),
        ))

    # -- Optional bounded probes --------------------------------------------
    probe_ok = True
    network_used = False
    if probe:
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not MIN_PROBE_TIMEOUT <= float(timeout) <= MAX_PROBE_TIMEOUT
        ):
            probe_ok = False
            checks.append(_check(
                "probe.timeout", "fail",
                (
                    "probe timeout must be between "
                    f"{MIN_PROBE_TIMEOUT} and {MAX_PROBE_TIMEOUT} seconds"
                ),
                value=timeout,
            ))
        else:
            _ = float(timeout)

        transport: ProbeTransport = (
            _default_probe_transport if probe_transport is None else probe_transport
        )
        probe_specs = (
            (
                "probe.koyeb.bs0db", "bs0db_url", "bs0db_token",
                "Koyeb BS0DB",
            ),
            (
                "probe.koyeb.mc0db", "mc0db_url", "mc0db_token",
                "Koyeb MC0DB",
            ),
            ("probe.nannet0", "nannet0_endpoint", None, "NANNET0"),
        )
        for check_id, url_field, token_field, label in probe_specs:
            if not probe_ok:
                checks.append(_check(
                    check_id, "skip",
                    "probe not attempted: timeout configuration is invalid",
                ))
                continue
            if not url_ok.get(url_field):
                checks.append(_check(
                    check_id, "skip",
                    f"{label} probe not attempted: endpoint is invalid",
                ))
                continue
            if token_field is not None and not token_ok.get(token_field):
                checks.append(_check(
                    check_id, "skip",
                    f"{label} probe not attempted: token is invalid",
                ))
                continue
            endpoint = str(raw[url_field]).strip()
            headers = {
                "Accept": "application/json",
                "User-Agent": "NaNROUTER-live-preflight/1",
            }
            if token_field is not None:
                headers["Authorization"] = f"Bearer {raw[token_field]}"
            network_used = True
            checks.append(_probe_check(
                check_id, endpoint, headers,
                timeout=float(timeout), transport=transport,
            ))
    else:
        for check_id, label in (
            ("probe.koyeb.bs0db", "Koyeb BS0DB"),
            ("probe.koyeb.mc0db", "Koyeb MC0DB"),
            ("probe.nannet0", "NANNET0"),
        ):
            checks.append(_check(
                check_id, "skip",
                f"{label} probe disabled; offline preflight performed no network I/O",
                network=False,
            ))

    # -- Safe evidence and deterministic report -----------------------------
    safe_config = {
        "koyeb": {
            "bs0db": {
                "url": _redact_url(raw.get("bs0db_url")),
                "token": _secret_evidence(raw.get("bs0db_token")),
            },
            "mc0db": {
                "url": _redact_url(raw.get("mc0db_url")),
                "token": _secret_evidence(raw.get("mc0db_token")),
            },
        },
        "nannet0": {
            "endpoint": _redact_url(raw.get("nannet0_endpoint")),
        },
        "volume_registry": {
            "path_digest": (
                _digest_text(str(raw.get("volume_registry_path")))
                if raw.get("volume_registry_path") is not None else None
            ),
            "key_id": (
                raw.get("volume_key_id")
                if isinstance(raw.get("volume_key_id"), str)
                and len(raw.get("volume_key_id")) <= 128
                else None
            ),
            "key_fingerprint": (
                _digest_secret(key_bytes) if key_bytes else None
            ),
            "key": _secret_evidence(raw.get("volume_hmac_key")),
        },
        "universe": {
            "pages": raw.get("universe_pages"),
            "page_bytes": raw.get("page_bytes"),
            "guest_budget_bytes": raw.get("guest_budget_bytes"),
            "guest_budget_words": raw.get("guest_budget_words"),
        },
        "runner_ring": {
            "active_slot_policy": raw.get("ring_active_slot_policy"),
            "active_slots": raw.get("ring_active_slots"),
            "slot_count": SLOT_COUNT,
            "slots": list(MC0_SLOTS),
        },
        "point0": {
            "route": POINT_ZERO_ADDRESS,
            "wire": POINT_ZERO_WIRE,
        },
    }
    registry_evidence = None
    if registry_obj is not None:
        summary = registry_obj.summary()
        registry_evidence = {
            "schema": summary["schema"],
            "network_id": summary["network_id"],
            "generation": summary["generation"],
            "registry_digest": summary["registry_digest"],
            "health": summary["health"],
            "canonical_tiers": summary["canonical_tiers"],
        }

    report = {
        "schema": SCHEMA,
        "status": _report_status(checks),
        "mode": "probe" if probe else "offline",
        "checks": checks,
        "summary": _summary(checks),
        "evidence": {
            "config_digest": _digest_json(safe_config),
            "config": safe_config,
            "volume_registry": registry_evidence,
            "runtime": {
                "universe_pages": UNIVERSE_PAGES,
                "page_bytes": PAGE_BYTES,
                "universe_bytes": UNIVERSE_BYTES,
                "guest_budget_bytes": runtime_guest_bytes,
                "guest_budget_words": runtime_guest_bytes // WORD_BYTES,
                "guest_pages": (
                    runtime_guest_bytes + PAGE_BYTES - 1
                ) // PAGE_BYTES,
                "guest_words": runtime_guest_bytes // WORD_BYTES,
                "guest_slack_words": (
                    ((runtime_guest_bytes + PAGE_BYTES - 1) // PAGE_BYTES)
                    * (PAGE_BYTES // WORD_BYTES)
                    - runtime_guest_bytes // WORD_BYTES
                ),
                "requested_guest_budget_bytes": raw.get("guest_budget_bytes"),
                "requested_guest_budget_words": raw.get("guest_budget_words"),
                "ring_slot_count": SLOT_COUNT,
                "ring_slots": list(MC0_SLOTS),
                "active_memory_ceiling_bytes": MAX_ACTIVE_MEMORY_BYTES,
                "point0_route": POINT_ZERO_ADDRESS,
                "point0_wire": POINT_ZERO_WIRE,
                "network_used": network_used,
            },
        },
    }
    # The report is built only from redacted URLs, lengths, and one-way
    # fingerprints; raw tokens and HMAC key material are never placed in it.
    return report


class LivePreflight:
    """Convenience wrapper that keeps a redacted deployment configuration."""

    def __init__(
        self,
        environ: Mapping[str, str] | None = None,
        *,
        probe: bool = False,
        timeout: float = DEFAULT_PROBE_TIMEOUT,
        probe_transport: ProbeTransport | None = None,
        **overrides: Any,
    ) -> None:
        self._environ = dict(os.environ if environ is None else environ)
        self.probe = bool(probe)
        self.timeout = timeout
        self._probe_transport = probe_transport
        self._overrides = dict(overrides)

    def report(self) -> dict[str, Any]:
        return preflight_report(
            self._environ,
            probe=self.probe,
            timeout=self.timeout,
            probe_transport=self._probe_transport,
            **self._overrides,
        )

    def run(self) -> dict[str, Any]:
        """Alias for :meth:`report`."""
        return self.report()

    def __repr__(self) -> str:
        safe = {
            key: ("<redacted>" if any(
                marker in key.lower() for marker in ("token", "key", "secret")
            ) else value)
            for key, value in self._overrides.items()
        }
        return (
            f"LivePreflight(probe={self.probe}, timeout={self.timeout}, "
            f"overrides={safe!r})"
        )


# Intuitive alias for callers that name the object rather than the signature.
verify_volume_registry = verify_signed_registry


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate live Koyeb/NANNET0 deployment inputs and the signed "
            "volume registry without network I/O unless --probe is supplied"
        )
    )
    parser.add_argument(
        "--probe", action="store_true",
        help="bounded GET /healthz probes (default: offline, no network)",
    )
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_PROBE_TIMEOUT,
        help=f"probe timeout in seconds (default {DEFAULT_PROBE_TIMEOUT})",
    )
    parser.add_argument("--registry", default=None,
                        help="override RIDDLE_VOLUME_REGISTRY_PATH")
    parser.add_argument("--expected-generation", type=int, default=None,
                        help="require this exact signed registry generation")
    parser.add_argument("--minimum-generation", type=int, default=None,
                        help="require at least this signed registry generation")
    parser.add_argument("--now-tick", type=int, default=None,
                        help="NaN clock tick for observation-age checks")
    parser.add_argument("--max-observation-age-ticks", type=int, default=None,
                        help="reject volume observations older than this")
    parser.add_argument("--pretty", action="store_true",
                        help="indent the JSON report")
    args = parser.parse_args(argv)
    report = preflight_report(
        probe=args.probe,
        timeout=args.timeout,
        volume_registry_path=args.registry,
        expected_generation=args.expected_generation,
        minimum_generation=args.minimum_generation,
        now_tick=args.now_tick,
        max_observation_age_ticks=args.max_observation_age_ticks,
    )
    print(json.dumps(
        report, sort_keys=True, indent=2 if args.pretty else None,
        separators=None if args.pretty else (",", ":"),
    ))
    return 0 if report["status"] == "green" else 2


__all__ = [
    "ACTIVE_SLOT_POLICY",
    "DEFAULT_PROBE_TIMEOUT",
    "DEFAULT_TIMEOUT",
    "DeploymentConfig",
    "GUEST_BUDGET_BYTES",
    "GUEST_PAGES",
    "LivePreflight",
    "LivePreflightError",
    "MAX_GUEST_BUDGET_BYTES",
    "MAX_PROBE_BYTES",
    "MAX_PROBE_TIMEOUT",
    "MIN_GUEST_BUDGET_BYTES",
    "MIN_PROBE_TIMEOUT",
    "PAGE_BYTES",
    "SCHEMA",
    "UNIVERSE_BYTES",
    "UNIVERSE_PAGES",
    "WORD_BYTES",
    "load_signed_registry",
    "preflight_report",
    "verify_signed_registry",
    "verify_volume_registry",
]


if __name__ == "__main__":
    raise SystemExit(main())
