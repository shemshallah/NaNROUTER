"""Point-0 NaN16 <-> binary transport bridge and active-runner router.

Clients never address the six runner slots directly.  They submit a
:class:`NanFrame` to the stable point-0 ingress (:data:`POINT_ZERO_ADDRESS`,
wire identity :data:`POINT_ZERO_WIRE`).  :class:`Point0Bridge` translates the
frame to a bounded binary transport envelope.  :class:`Point0Router` asks the
single-active :class:`~runner_riddle.wave_ring_scheduler.WaveRingScheduler`
which slot is current, dispatches the binary request payload to that slot only,
then translates the binary result payload back to a ``NanFrame``.

The bridge is deliberately small and mechanical.  It packs and unpacks exact
64-bit words in network byte order.  It does not perform any host arithmetic on
the words beyond range validation, and it never chooses a runner slot.  Slot
selection and epoch validation belong to the router and scheduler.

Binary envelope v2 layout (all integers big-endian)::

    offset  size  field
    0       4     magic              b"N16B"
    4       1     version            2
    5       1     active_slot        0..5
    6       8     request_id         unsigned 64-bit
    14      8     epoch              unsigned 64-bit
    22      4     nan_word_count     number of 64-bit NaN16 words
    26      1     result_status      bounded status code (see RESULT_STATUSES)
    27      5     point_zero         b"BS0:0" stable ingress identity
    32      32    digest             SHA-256 over the header above + payload
    64      N     payload            N / 8 exact 64-bit words

Legacy v1 envelopes remain decodable for compatibility::

    offset  size  field
    0       4     magic              b"N16B"
    4       1     version            1
    5       1     active_slot        0..5
    6       8     request_id         unsigned 64-bit
    14      8     epoch              unsigned 64-bit
    22      4     length             payload bytes, unsigned 32-bit
    26      32    digest             SHA-256 over the header above + payload
    58      N     payload            N / 8 exact 64-bit words

The envelope digest binds every header field, including the slot, epoch, word
count, point-0 identity, and result status.  A router accepts an envelope only
when its slot and epoch equal the scheduler's current activation.  Point 0
remains the public address before and after a ring cycle; the active slot is
evidence, not an address component.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
import hashlib
import hmac
import struct
import threading
from typing import Any

from .wave_ring_scheduler import SLOT_COUNT, WaveRingScheduler

# Stable point-0 identity in the apex-layered v2 grammar.  BSR0 is the
# zero-based wire coordinate used by the existing bridge protocol; the
# human/display label for point 0 is BSR1.  The pre-v2 spelling is accepted
# only as a migration alias and is never emitted.
POINT_ZERO_ADDRESS = "nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0"
POINT_ZERO_LEGACY_ADDRESS = "nan://GM0:SC0:MC0:BS0:0:HW0:0"
POINT_ZERO_IDENTITY = "BS0:0"
POINT_ZERO_WIRE = "BSR0"
POINT_ZERO_LABEL = "point-0"

# Transport is always network byte order, independent of the host.
WIRE_ENDIAN = "big"
WORD_BITS = 64
WORD_BYTES = WORD_BITS // 8
# 2 MiB / 8-byte NaN16 word = 262,144 words.  Bridge instances may set a
# smaller per-frame limit; this is only the hard ceiling.
MAX_FRAME_WORDS = 262144
MAX_PAYLOAD_BYTES = MAX_FRAME_WORDS * WORD_BYTES

MAGIC = b"N16B"
LEGACY_VERSION = 1
VERSION = 2
SUPPORTED_VERSIONS = frozenset({LEGACY_VERSION, VERSION})

# Bounded result status vocabulary from DEEP_PLAN_CONT section 6.6.  A request
# envelope uses "ok" as its neutral default; a result envelope carries the
# executor's actual status.
RESULT_STATUS_OK = "ok"
RESULT_STATUSES = (
    "ok",
    "invalid_descriptor",
    "bad_domain",
    "overflow",
    "saturation",
    "nonconvergence",
    "insufficient_workspace",
    "stale_generation",
    "unauthorized",
    "cancelled",
    "budget_exhausted",
)
_RESULT_STATUS_CODES = {
    status: code for code, status in enumerate(RESULT_STATUSES)
}
_RESULT_STATUS_NAMES = {
    code: status for status, code in _RESULT_STATUS_CODES.items()
}
_RESULT_STATUS_ALIASES = {
    "success": "ok",
    "invalid": "invalid_descriptor",
    "stale": "stale_generation",
    "budget": "budget_exhausted",
}

_HEADER_V1 = struct.Struct(">4sBBQQI32s")
_HEADER_V2 = struct.Struct(">4sBBQQIB5s")
_HEADER_V1_SIZE = _HEADER_V1.size
_HEADER_V2_SIZE = _HEADER_V2.size
_MAX_UINT64 = (1 << 64) - 1
_DIGEST_SIZE = 32
_HEADER_V2_WIRE_SIZE = _HEADER_V2_SIZE + _DIGEST_SIZE
_POINT_ZERO_BYTES = POINT_ZERO_IDENTITY.encode("ascii")
_FORBIDDEN_ROUTE_MARKERS = ("/R", "NANROUTER-")


class Point0BridgeError(ValueError):
    """Base class for point-0 framing, routing, and scheduling errors."""


class FrameError(Point0BridgeError):
    """A NaN frame has an invalid word, request id, route, or metadata field."""


class FrameTooLargeError(FrameError):
    """A frame or binary payload exceeds the configured word/length bound."""


class EnvelopeFormatError(Point0BridgeError):
    """A binary envelope has bad magic, version, length, digest, or layout."""


class StaleEnvelopeError(Point0BridgeError):
    """An envelope's epoch (or the active heartbeat) is no longer current."""


class InactiveSlotError(Point0BridgeError):
    """An envelope names a slot that is not the one current active slot."""


class NoActiveSlotError(Point0BridgeError):
    """The scheduler is not started or does not expose exactly one active slot."""


class RouterBusyError(Point0BridgeError):
    """A point-0 dispatch is already in flight in this router."""


class ExecutorResultError(Point0BridgeError):
    """The caller-supplied executor did not return a valid binary payload."""


class ResultDigestMismatchError(EnvelopeFormatError):
    """A result digest does not match the caller's expected output digest."""


# Familiar aliases used in documentation and by callers.
Point0Error = Point0BridgeError
OversizedFrameError = FrameTooLargeError
StaleEpochError = StaleEnvelopeError
BinaryEnvelopeError = EnvelopeFormatError


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _require_uint(name: str, value: Any, *, maximum: int = _MAX_UINT64) -> int:
    if not _is_int(value):
        raise Point0BridgeError(f"{name} must be an integer")
    if not 0 <= value <= maximum:
        raise Point0BridgeError(f"{name} must be in 0..{maximum}")
    return value


def _require_active_slot(value: Any) -> int:
    if not _is_int(value):
        raise InactiveSlotError("active_slot must be an integer")
    if not 0 <= value < SLOT_COUNT:
        raise InactiveSlotError(f"active_slot must be in 0..{SLOT_COUNT - 1}")
    return value


def _canonical_route(route: Any) -> str:
    """Return the stable point-0 address or reject direct slot/foreign routes."""
    if route is None or route == "":
        return POINT_ZERO_ADDRESS
    if not isinstance(route, str):
        raise FrameError("route must be a string")
    route = route.strip()
    if not route:
        return POINT_ZERO_ADDRESS
    if route in (
        POINT_ZERO_ADDRESS,
        POINT_ZERO_LEGACY_ADDRESS,
        POINT_ZERO_WIRE,
    ):
        return POINT_ZERO_ADDRESS
    if any(marker in route for marker in _FORBIDDEN_ROUTE_MARKERS):
        raise FrameError("route must not address a runner slot directly")
    raise FrameError(
        f"route must use the stable point-0 address {POINT_ZERO_ADDRESS!r}"
    )


def _canonical_point_zero(value: Any) -> str:
    """Return the canonical point-0 identity or reject a foreign identity."""
    if isinstance(value, (bytes, bytearray, memoryview)):
        try:
            value = bytes(value).decode("ascii")
        except UnicodeDecodeError as exc:
            raise EnvelopeFormatError("point_zero must be ASCII") from exc
    if not isinstance(value, str):
        raise EnvelopeFormatError("point_zero must be a string")
    text = value.strip()
    if text in (POINT_ZERO_IDENTITY, POINT_ZERO_WIRE):
        return POINT_ZERO_IDENTITY
    raise EnvelopeFormatError(
        f"point_zero must be {POINT_ZERO_IDENTITY!r} (wire {POINT_ZERO_WIRE!r})"
    )


def _canonical_result_status(value: Any) -> str:
    """Normalize a bounded result status, rejecting unknown values."""
    if not isinstance(value, str) or not value.strip():
        raise EnvelopeFormatError("result_status must be a non-empty string")
    key = value.strip().lower()
    key = _RESULT_STATUS_ALIASES.get(key, key)
    if key not in RESULT_STATUSES:
        raise EnvelopeFormatError(
            "result_status must be one of: " + ", ".join(RESULT_STATUSES)
        )
    return key


def _result_status_code(value: Any) -> int:
    return _RESULT_STATUS_CODES[_canonical_result_status(value)]


def _result_status_name(code: Any) -> str:
    if not _is_int(code) or code not in _RESULT_STATUS_NAMES:
        raise EnvelopeFormatError(
            f"unsupported result_status code: {code!r}"
        )
    return _RESULT_STATUS_NAMES[code]


def _coerce_sha256(name: str, value: Any) -> bytes:
    """Accept a 32-byte digest or a 64-character hex digest."""
    if isinstance(value, str):
        if len(value) != 64 or any(
            ch not in "0123456789abcdefABCDEF" for ch in value
        ):
            raise Point0BridgeError(
                f"{name} must be a 64-character SHA-256 hex string"
            )
        return bytes.fromhex(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        if len(raw) != _DIGEST_SIZE:
            raise Point0BridgeError(f"{name} must be a 32-byte SHA-256 value")
        return raw
    raise Point0BridgeError(
        f"{name} must be a 32-byte SHA-256 value or a 64-character hex string"
    )


def _output_digest(payload: bytes) -> bytes:
    """SHA-256 over the exact binary result payload (the output words)."""
    return hashlib.sha256(bytes(payload)).digest()


def _freeze_words(words: Any) -> tuple[int, ...]:
    if isinstance(words, (str, bytes, bytearray, memoryview)):
        raise FrameError("words must be an iterable of unsigned 64-bit integers")
    try:
        values = tuple(words)
    except TypeError as exc:
        raise FrameError(
            "words must be an iterable of unsigned 64-bit integers"
        ) from exc
    checked: list[int] = []
    for index, value in enumerate(values):
        if not _is_int(value):
            raise FrameError(f"word {index} must be an integer")
        if not 0 <= value <= _MAX_UINT64:
            raise FrameError(f"word {index} must fit in an unsigned 64-bit integer")
        checked.append(value)
    return tuple(checked)


def _freeze_provenance(provenance: Any) -> tuple[tuple[str, str], ...]:
    if provenance is None:
        return ()
    if isinstance(provenance, Mapping):
        items: Iterable[Any] = provenance.items()
    else:
        try:
            items = tuple(provenance)
        except TypeError as exc:
            raise FrameError("provenance must be a mapping or iterable of pairs") from exc
    frozen: list[tuple[str, str]] = []
    for item in items:
        if (
            not isinstance(item, (tuple, list))
            or len(item) != 2
        ):
            raise FrameError("provenance entries must be (key, value) pairs")
        key, value = item
        if not isinstance(key, str) or not key:
            raise FrameError("provenance keys must be non-empty strings")
        if not isinstance(value, (str, int)) or isinstance(value, bool):
            raise FrameError("provenance values must be strings or integers")
        if len(key) > 128:
            raise FrameError("provenance keys must be <= 128 characters")
        text = value if isinstance(value, str) else str(value)
        if len(text) > 1024:
            raise FrameError("provenance values must be <= 1024 characters")
        frozen.append((key, text))
    return tuple(frozen)


@dataclass(frozen=True)
class NanFrame:
    """A NaN16 frame addressed through point 0.

    ``words`` are exact unsigned 64-bit values.  ``route`` is always canonical
    point 0: direct ``MC0:0/R*`` and ``NANROUTER-*`` routes are rejected.
    ``provenance`` is local evidence metadata and is intentionally excluded
    from equality; the binary envelope does not transport caller provenance.
    """

    words: tuple[int, ...]
    request_id: int
    route: str = POINT_ZERO_ADDRESS
    provenance: tuple[tuple[str, str], ...] = field(
        default=(), compare=False
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "words", _freeze_words(self.words))
        try:
            request_id = _require_uint("request_id", self.request_id)
        except Point0BridgeError as exc:
            raise FrameError(str(exc)) from exc
        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "route", _canonical_route(self.route))
        object.__setattr__(
            self, "provenance", _freeze_provenance(self.provenance)
        )

    @property
    def word_count(self) -> int:
        return len(self.words)

    @property
    def metadata(self) -> dict[str, str]:
        return dict(self.provenance)

    @property
    def address(self) -> str:
        return self.route


def _compute_digest_v1(
    magic: bytes,
    version: int,
    active_slot: int,
    request_id: int,
    epoch: int,
    length: int,
    payload: bytes,
) -> bytes:
    return hashlib.sha256(
        struct.pack(
            ">4sBBQQI",
            magic,
            version,
            active_slot,
            request_id,
            epoch,
            length,
        )
        + payload
    ).digest()


def _compute_digest_v2(
    magic: bytes,
    version: int,
    active_slot: int,
    request_id: int,
    epoch: int,
    nan_word_count: int,
    result_status: str,
    point_zero: str,
    payload: bytes,
) -> bytes:
    _canonical_point_zero(point_zero)
    return hashlib.sha256(
        struct.pack(
            ">4sBBQQIB5s",
            magic,
            version,
            active_slot,
            request_id,
            epoch,
            nan_word_count,
            _result_status_code(result_status),
            _POINT_ZERO_BYTES,
        )
        + payload
    ).digest()


@dataclass(frozen=True)
class BinaryEnvelope:
    """Point-0 binary transport envelope (v2; legacy v1 decoding supported)."""

    magic: bytes
    version: int
    request_id: int
    length: int
    payload: bytes
    digest: bytes
    active_slot: int
    epoch: int
    point_zero: str = POINT_ZERO_IDENTITY
    nan_word_count: int | None = None
    result_status: str = RESULT_STATUS_OK

    def __post_init__(self) -> None:
        object.__setattr__(self, "magic", bytes(self.magic))
        object.__setattr__(self, "payload", bytes(self.payload))
        object.__setattr__(self, "digest", bytes(self.digest))
        object.__setattr__(
            self, "point_zero", _canonical_point_zero(self.point_zero)
        )
        object.__setattr__(
            self, "result_status", _canonical_result_status(self.result_status)
        )
        count = self.nan_word_count
        if count is None:
            count = len(self.payload) // WORD_BYTES
        if not _is_int(count):
            raise EnvelopeFormatError(
                "nan_word_count must be a nonnegative integer"
            )
        object.__setattr__(self, "nan_word_count", count)

    @property
    def word_count(self) -> int:
        return int(self.nan_word_count)

    @property
    def output_digest(self) -> bytes:
        """SHA-256 over the exact binary payload (the NaN16 output words)."""
        return _output_digest(self.payload)

    @property
    def payload_digest(self) -> bytes:
        return self.output_digest

    @classmethod
    def create(
        cls,
        *,
        request_id: int,
        payload: bytes,
        active_slot: int,
        epoch: int,
        magic: bytes = MAGIC,
        version: int = VERSION,
        point_zero: str = POINT_ZERO_IDENTITY,
        nan_word_count: int | None = None,
        result_status: str = RESULT_STATUS_OK,
    ) -> "BinaryEnvelope":
        """Build an envelope and compute its digest from its exact bytes."""
        payload = bytes(payload)
        request_id = _require_uint("request_id", request_id)
        active_slot = _require_active_slot(active_slot)
        epoch = _require_uint("epoch", epoch)
        point_zero = _canonical_point_zero(point_zero)
        result_status = _canonical_result_status(result_status)
        if not isinstance(magic, (bytes, bytearray)) or len(magic) != 4:
            raise EnvelopeFormatError("magic must be exactly four bytes")
        if not _is_int(version) or version not in SUPPORTED_VERSIONS:
            raise EnvelopeFormatError(
                f"unsupported binary envelope version: {version!r}"
            )
        if len(payload) > MAX_PAYLOAD_BYTES:
            raise FrameTooLargeError(
                f"payload exceeds {MAX_PAYLOAD_BYTES} bytes"
            )
        if len(payload) % WORD_BYTES:
            raise EnvelopeFormatError(
                "payload length must be a multiple of eight bytes"
            )
        count = len(payload) // WORD_BYTES
        if nan_word_count is not None:
            if not _is_int(nan_word_count) or nan_word_count != count:
                raise EnvelopeFormatError(
                    "nan_word_count must equal the number of 64-bit words "
                    "in the payload"
                )
        if version == LEGACY_VERSION:
            if result_status != RESULT_STATUS_OK:
                raise EnvelopeFormatError(
                    "legacy v1 envelopes cannot carry a non-ok result_status"
                )
            digest = _compute_digest_v1(
                bytes(magic),
                version,
                active_slot,
                request_id,
                epoch,
                len(payload),
                payload,
            )
        else:
            digest = _compute_digest_v2(
                bytes(magic),
                version,
                active_slot,
                request_id,
                epoch,
                count,
                result_status,
                point_zero,
                payload,
            )
        return cls(
            magic=bytes(magic),
            version=version,
            request_id=request_id,
            length=len(payload),
            payload=payload,
            digest=digest,
            active_slot=active_slot,
            epoch=epoch,
            point_zero=point_zero,
            nan_word_count=count,
            result_status=result_status,
        )

    def to_bytes(self) -> bytes:
        """Serialize the envelope, including its stored digest."""
        try:
            if self.version == LEGACY_VERSION:
                header = _HEADER_V1.pack(
                    self.magic,
                    self.version,
                    self.active_slot,
                    self.request_id,
                    self.epoch,
                    self.length,
                    self.digest,
                )
            elif self.version == VERSION:
                prefix = _HEADER_V2.pack(
                    self.magic,
                    self.version,
                    self.active_slot,
                    self.request_id,
                    self.epoch,
                    int(self.nan_word_count),
                    _result_status_code(self.result_status),
                    self.point_zero.encode("ascii"),
                )
                return prefix + self.digest + self.payload
            else:
                raise EnvelopeFormatError(
                    f"unsupported binary envelope version: {self.version!r}"
                )
        except struct.error as exc:
            raise EnvelopeFormatError(
                "envelope fields do not fit the wire layout"
            ) from exc
        return header + self.payload

    @classmethod
    def from_bytes(cls, data: bytes) -> "BinaryEnvelope":
        """Parse and fully validate an envelope from its wire representation."""
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise EnvelopeFormatError("envelope must be bytes-like")
        raw = bytes(data)
        if len(raw) < 5:
            raise EnvelopeFormatError("binary envelope is shorter than its header")
        version = raw[4]
        if version == LEGACY_VERSION:
            if len(raw) < _HEADER_V1_SIZE:
                raise EnvelopeFormatError(
                    "binary envelope is shorter than its header"
                )
            (
                magic,
                version,
                active_slot,
                request_id,
                epoch,
                length,
                digest,
            ) = _HEADER_V1.unpack_from(raw, 0)
            payload = raw[_HEADER_V1_SIZE:]
            envelope = cls(
                magic=magic,
                version=version,
                request_id=request_id,
                length=length,
                payload=payload,
                digest=digest,
                active_slot=active_slot,
                epoch=epoch,
                nan_word_count=length // WORD_BYTES,
            )
        elif version == VERSION:
            if len(raw) < _HEADER_V2_WIRE_SIZE:
                raise EnvelopeFormatError(
                    "binary envelope is shorter than its header"
                )
            (
                magic,
                version,
                active_slot,
                request_id,
                epoch,
                nan_word_count,
                status_code,
                point_zero,
            ) = _HEADER_V2.unpack_from(raw, 0)
            try:
                point_zero_text = point_zero.decode("ascii")
            except UnicodeDecodeError as exc:
                raise EnvelopeFormatError(
                    "point_zero must be ASCII"
                ) from exc
            digest = raw[_HEADER_V2_SIZE:_HEADER_V2_WIRE_SIZE]
            payload = raw[_HEADER_V2_WIRE_SIZE:]
            envelope = cls(
                magic=magic,
                version=version,
                request_id=request_id,
                length=len(payload),
                payload=payload,
                digest=digest,
                active_slot=active_slot,
                epoch=epoch,
                point_zero=point_zero_text,
                nan_word_count=nan_word_count,
                result_status=_result_status_name(status_code),
            )
        else:
            raise EnvelopeFormatError(
                f"unsupported binary envelope version: {version!r}"
            )
        _validate_envelope(envelope, MAX_FRAME_WORDS)
        return envelope


def _validate_envelope(
    envelope: BinaryEnvelope, max_words: int = MAX_FRAME_WORDS
) -> None:
    """Validate every envelope field and recompute the SHA-256 digest."""
    if not isinstance(envelope, BinaryEnvelope):
        raise EnvelopeFormatError("envelope must be a BinaryEnvelope")
    if not _is_int(max_words) or not 0 <= max_words <= MAX_FRAME_WORDS:
        raise Point0BridgeError(
            f"max_words must be in 0..{MAX_FRAME_WORDS}"
        )
    if not isinstance(envelope.magic, (bytes, bytearray)) or bytes(envelope.magic) != MAGIC:
        raise EnvelopeFormatError("bad binary envelope magic")
    if not _is_int(envelope.version) or envelope.version not in SUPPORTED_VERSIONS:
        raise EnvelopeFormatError(
            f"unsupported binary envelope version: {envelope.version!r}"
        )
    if not _is_int(envelope.request_id) or not 0 <= envelope.request_id <= _MAX_UINT64:
        raise EnvelopeFormatError("request_id must be an unsigned 64-bit integer")
    if not _is_int(envelope.length) or envelope.length < 0:
        raise EnvelopeFormatError("length must be a nonnegative integer")
    if envelope.length != len(envelope.payload):
        raise EnvelopeFormatError(
            "declared length does not match the binary payload length"
        )
    max_bytes = max_words * WORD_BYTES
    if envelope.length > max_bytes:
        raise FrameTooLargeError(
            f"binary payload exceeds the {max_bytes}-byte frame bound"
        )
    if envelope.length % WORD_BYTES:
        raise EnvelopeFormatError(
            "binary payload length must be a multiple of eight bytes"
        )
    if not _is_int(envelope.active_slot) or not 0 <= envelope.active_slot < SLOT_COUNT:
        raise InactiveSlotError(
            f"active_slot must be in 0..{SLOT_COUNT - 1}"
        )
    if not _is_int(envelope.epoch) or not 0 <= envelope.epoch <= _MAX_UINT64:
        raise EnvelopeFormatError("epoch must be an unsigned 64-bit integer")
    if not isinstance(envelope.digest, (bytes, bytearray)) or len(envelope.digest) != _DIGEST_SIZE:
        raise EnvelopeFormatError("digest must be a 32-byte SHA-256 value")
    if envelope.point_zero != POINT_ZERO_IDENTITY:
        raise EnvelopeFormatError(
            f"point_zero must be {POINT_ZERO_IDENTITY!r}"
        )
    if (
        not _is_int(envelope.nan_word_count)
        or not 0 <= envelope.nan_word_count <= max_words
    ):
        raise FrameTooLargeError(
            f"nan_word_count must be in 0..{max_words}"
        )
    if envelope.nan_word_count != envelope.length // WORD_BYTES:
        raise EnvelopeFormatError(
            "nan_word_count does not match the binary payload length"
        )
    if envelope.version == LEGACY_VERSION:
        if envelope.result_status != RESULT_STATUS_OK:
            raise EnvelopeFormatError(
                "legacy v1 envelopes cannot carry a non-ok result_status"
            )
        expected = _compute_digest_v1(
            bytes(envelope.magic),
            envelope.version,
            envelope.active_slot,
            envelope.request_id,
            envelope.epoch,
            envelope.length,
            envelope.payload,
        )
    else:
        if envelope.result_status not in RESULT_STATUSES:
            raise EnvelopeFormatError(
                f"unsupported result_status: {envelope.result_status!r}"
            )
        expected = _compute_digest_v2(
            bytes(envelope.magic),
            envelope.version,
            envelope.active_slot,
            envelope.request_id,
            envelope.epoch,
            envelope.nan_word_count,
            envelope.result_status,
            envelope.point_zero,
            envelope.payload,
        )
    if not hmac.compare_digest(bytes(envelope.digest), expected):
        raise EnvelopeFormatError("binary envelope digest mismatch")


def _pack_words(words: tuple[int, ...]) -> bytes:
    if not words:
        return b""
    try:
        return struct.pack(f">{len(words)}Q", *words)
    except struct.error as exc:
        raise FrameError("frame words do not fit the 64-bit wire format") from exc


def _unpack_words(payload: bytes) -> tuple[int, ...]:
    if not payload:
        return ()
    count = len(payload) // WORD_BYTES
    try:
        return tuple(struct.unpack(f">{count}Q", payload))
    except struct.error as exc:
        raise EnvelopeFormatError("binary payload is not a whole number of 64-bit words") from exc


class Point0Bridge:
    """Translate point-0 ``NanFrame`` values to and from binary envelopes."""

    def __init__(self, *, max_words: int = MAX_FRAME_WORDS) -> None:
        if not _is_int(max_words) or not 0 <= max_words <= MAX_FRAME_WORDS:
            raise Point0BridgeError(
                f"max_words must be in 0..{MAX_FRAME_WORDS}"
            )
        self.max_words = max_words
        self.max_payload_bytes = max_words * WORD_BYTES

    def encode(
        self,
        frame: NanFrame,
        *,
        active_slot: int = 0,
        epoch: int = 0,
        result_status: str = RESULT_STATUS_OK,
        version: int = VERSION,
    ) -> BinaryEnvelope:
        """Encode a point-0 frame into one bounded binary envelope.

        ``active_slot`` and ``epoch`` are routing evidence supplied by the
        router, never by a client.  Standalone codec users get slot 0/epoch 0.
        ``result_status`` is normally set on a result envelope, not a request.
        """
        if not isinstance(frame, NanFrame):
            raise FrameError("frame must be a NanFrame")
        active_slot = _require_active_slot(active_slot)
        epoch = _require_uint("epoch", epoch)
        if len(frame.words) > self.max_words:
            raise FrameTooLargeError(
                f"frame has {len(frame.words)} words; limit is {self.max_words}"
            )
        payload = _pack_words(frame.words)
        if len(payload) > self.max_payload_bytes:
            raise FrameTooLargeError(
                f"frame payload exceeds {self.max_payload_bytes} bytes"
            )
        return BinaryEnvelope.create(
            request_id=frame.request_id,
            payload=payload,
            active_slot=active_slot,
            epoch=epoch,
            version=version,
            nan_word_count=len(frame.words),
            result_status=result_status,
        )

    def decode(
        self,
        envelope: BinaryEnvelope | bytes,
        *,
        expected_active_slot: int | None = None,
        expected_epoch: int | None = None,
        expected_request_id: int | None = None,
        expected_result_digest: bytes | str | None = None,
        expected_output_digest: bytes | str | None = None,
    ) -> NanFrame:
        """Validate and decode an envelope back to an exact point-0 frame.

        Passing the expected slot, epoch, request id, result digest, or output
        digest turns the codec into a binding check.  ``expected_result_digest``
        binds the full result envelope; ``expected_output_digest`` binds only
        the exact binary output payload.
        """
        if isinstance(envelope, (bytes, bytearray, memoryview)):
            envelope = BinaryEnvelope.from_bytes(envelope)
        elif not isinstance(envelope, BinaryEnvelope):
            raise EnvelopeFormatError("envelope must be a BinaryEnvelope or bytes")
        _validate_envelope(envelope, self.max_words)
        if expected_active_slot is not None:
            expected_slot = _require_active_slot(expected_active_slot)
            if envelope.active_slot != expected_slot:
                raise InactiveSlotError(
                    f"envelope targets slot {envelope.active_slot}, "
                    f"but slot {expected_slot} is active"
                )
        if expected_epoch is not None:
            expected = _require_uint("expected_epoch", expected_epoch)
            if envelope.epoch != expected:
                raise StaleEnvelopeError(
                    f"envelope epoch {envelope.epoch} is stale; "
                    f"current epoch is {expected}"
                )
        if expected_request_id is not None:
            expected_id = _require_uint(
                "expected_request_id", expected_request_id
            )
            if envelope.request_id != expected_id:
                raise EnvelopeFormatError(
                    "binary envelope request_id does not match the request frame"
                )
        if expected_result_digest is not None:
            expected = _coerce_sha256(
                "expected_result_digest", expected_result_digest
            )
            if not hmac.compare_digest(envelope.digest, expected):
                raise ResultDigestMismatchError(
                    "result digest does not match the expected result digest"
                )
        if expected_output_digest is not None:
            expected = _coerce_sha256(
                "expected_output_digest", expected_output_digest
            )
            if not hmac.compare_digest(envelope.output_digest, expected):
                raise ResultDigestMismatchError(
                    "result digest does not match the expected output digest"
                )
        words = _unpack_words(envelope.payload)
        provenance = (
            ("bridge", "point-0"),
            ("wire", POINT_ZERO_WIRE),
            ("point_zero", POINT_ZERO_IDENTITY),
            ("nan_word_count", str(envelope.nan_word_count)),
            ("result_status", envelope.result_status),
            ("active_slot", str(envelope.active_slot)),
            ("epoch", str(envelope.epoch)),
        )
        return NanFrame(
            words=words,
            request_id=envelope.request_id,
            route=POINT_ZERO_ADDRESS,
            provenance=provenance,
        )


@dataclass(frozen=True)
class Point0Result:
    """Decoded NaN16 result plus non-address routing and output evidence."""

    frame: NanFrame
    active_slot: int
    epoch: int
    request_digest: bytes = b""
    result_digest: bytes = b""
    result_status: str = RESULT_STATUS_OK
    output_digest: bytes = b""
    point_zero: str = POINT_ZERO_IDENTITY

    def __post_init__(self) -> None:
        if not isinstance(self.frame, NanFrame):
            raise Point0BridgeError("result frame must be a NanFrame")
        object.__setattr__(
            self, "active_slot", _require_active_slot(self.active_slot)
        )
        object.__setattr__(self, "epoch", _require_uint("epoch", self.epoch))
        request_digest = bytes(self.request_digest)
        result_digest = bytes(self.result_digest)
        output_digest = bytes(self.output_digest)
        for name, digest in (
            ("request_digest", request_digest),
            ("result_digest", result_digest),
            ("output_digest", output_digest),
        ):
            if digest and len(digest) != _DIGEST_SIZE:
                raise Point0BridgeError(
                    f"{name} must be a 32-byte SHA-256 value"
                )
        if not output_digest:
            output_digest = _output_digest(_pack_words(self.frame.words))
        object.__setattr__(self, "request_digest", request_digest)
        object.__setattr__(self, "result_digest", result_digest)
        object.__setattr__(self, "output_digest", output_digest)
        object.__setattr__(
            self, "result_status", _canonical_result_status(self.result_status)
        )
        object.__setattr__(
            self, "point_zero", _canonical_point_zero(self.point_zero)
        )

    @property
    def words(self) -> tuple[int, ...]:
        return self.frame.words

    @property
    def word_count(self) -> int:
        return len(self.frame.words)

    @property
    def nan_word_count(self) -> int:
        return len(self.frame.words)

    @property
    def request_id(self) -> int:
        return self.frame.request_id

    @property
    def route(self) -> str:
        return self.frame.route

    @property
    def address(self) -> str:
        return self.frame.route

    @property
    def slot(self) -> int:
        """Alias for the active slot evidence (never part of the route)."""
        return self.active_slot

    @property
    def provenance(self) -> tuple[tuple[str, str], ...]:
        return self.frame.provenance

    @property
    def metadata(self) -> dict[str, str]:
        return self.frame.metadata

    def verify_output(self, expected_output_digest: bytes | str) -> None:
        """Raise unless the output payload matches the expected digest."""
        expected = _coerce_sha256(
            "expected_output_digest", expected_output_digest
        )
        if not hmac.compare_digest(self.output_digest, expected):
            raise ResultDigestMismatchError(
                "result digest does not match the expected output digest"
            )

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-safe result evidence; the route never names a slot."""
        return {
            "route": self.route,
            "wire": POINT_ZERO_WIRE,
            "point_zero": self.point_zero,
            "request_id": self.request_id,
            "word_count": self.word_count,
            "nan_word_count": self.nan_word_count,
            "result_status": self.result_status,
            "active_slot": self.active_slot,
            "epoch": self.epoch,
            "request_digest": self.request_digest.hex(),
            "result_digest": self.result_digest.hex(),
            "output_digest": self.output_digest.hex(),
        }


@dataclass(frozen=True)
class Point0ExecutorResult:
    """Optional executor return type carrying a bounded result status."""

    payload: bytes
    result_status: str = RESULT_STATUS_OK

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", bytes(self.payload))
        object.__setattr__(
            self, "result_status", _canonical_result_status(self.result_status)
        )


# Familiar alias for callers that prefer the longer name.
Point0ExecutionResult = Point0ExecutorResult


@dataclass(frozen=True)
class _ActiveState:
    slot: int
    epoch: int


Executor = Callable[[int, int, bytes], bytes | Point0ExecutorResult]


class Point0Router:
    """Route point-0 frames only to the scheduler's current active slot.

    The executor callback receives ``(active_slot, epoch, binary_payload)`` and
    must return the binary result payload (a whole number of big-endian 64-bit
    words).  The router constructs and validates the result envelope itself, so
    the executor has no way to select a different slot or epoch.

    ``submit(frame)`` is the client-facing API.  ``dispatch(envelope)`` is the
    binary retry path for an envelope that already crossed point 0; it still
    refuses an envelope whose slot or epoch is not current, before invoking the
    executor.
    """

    def __init__(
        self,
        bridge: Point0Bridge | None = None,
        scheduler: WaveRingScheduler | None = None,
        executor: Executor | None = None,
    ) -> None:
        # Allow the convenient Point0Router(scheduler, executor) form as well as
        # the explicit Point0Router(bridge, scheduler, executor) form.
        if (
            bridge is not None
            and not isinstance(bridge, Point0Bridge)
            and callable(getattr(bridge, "snapshot", None))
            and scheduler is not None
            and callable(scheduler)
            and executor is None
        ):
            bridge, scheduler, executor = None, bridge, scheduler
        if bridge is None:
            bridge = Point0Bridge()
        if not isinstance(bridge, Point0Bridge):
            raise TypeError("bridge must be a Point0Bridge")
        if scheduler is None or not callable(getattr(scheduler, "snapshot", None)):
            raise TypeError("scheduler must expose snapshot()")
        if executor is None or not callable(executor):
            raise TypeError("executor must be callable")
        self.bridge = bridge
        self.scheduler = scheduler
        self._executor = executor
        self._lock = threading.RLock()
        self._in_flight = False

    @property
    def route(self) -> str:
        """The public address is always stable point 0."""
        return POINT_ZERO_ADDRESS

    def submit(
        self,
        frame: NanFrame,
        *,
        expected_result_digest: bytes | str | None = None,
        expected_output_digest: bytes | str | None = None,
    ) -> Point0Result:
        """Encode, route to the one active slot, execute, and decode."""
        if not isinstance(frame, NanFrame):
            raise FrameError("frame must be a NanFrame")
        if len(frame.words) > self.bridge.max_words:
            raise FrameTooLargeError(
                f"frame has {len(frame.words)} words; "
                f"limit is {self.bridge.max_words}"
            )
        if expected_result_digest is not None:
            _coerce_sha256("expected_result_digest", expected_result_digest)
        if expected_output_digest is not None:
            _coerce_sha256("expected_output_digest", expected_output_digest)
        with self._lock:
            state = self._active_state()
            envelope = self.bridge.encode(
                frame, active_slot=state.slot, epoch=state.epoch
            )
            result = self._dispatch_locked(envelope)
            self._verify_expected(
                result,
                expected_result_digest=expected_result_digest,
                expected_output_digest=expected_output_digest,
            )
            return result

    def dispatch(
        self,
        envelope: BinaryEnvelope | bytes,
        *,
        expected_result_digest: bytes | str | None = None,
        expected_output_digest: bytes | str | None = None,
    ) -> Point0Result:
        """Retry one already-encoded point-0 envelope if it is still current."""
        if expected_result_digest is not None:
            _coerce_sha256("expected_result_digest", expected_result_digest)
        if expected_output_digest is not None:
            _coerce_sha256("expected_output_digest", expected_output_digest)
        with self._lock:
            result = self._dispatch_locked(envelope)
            self._verify_expected(
                result,
                expected_result_digest=expected_result_digest,
                expected_output_digest=expected_output_digest,
            )
            return result

    def _verify_expected(
        self,
        result: Point0Result,
        *,
        expected_result_digest: bytes | str | None,
        expected_output_digest: bytes | str | None,
    ) -> None:
        if expected_result_digest is not None:
            expected = _coerce_sha256(
                "expected_result_digest", expected_result_digest
            )
            if not hmac.compare_digest(result.result_digest, expected):
                raise ResultDigestMismatchError(
                    "result digest does not match the expected result digest"
                )
        if expected_output_digest is not None:
            result.verify_output(expected_output_digest)

    def _dispatch_locked(
        self, envelope: BinaryEnvelope | bytes
    ) -> Point0Result:
        if self._in_flight:
            raise RouterBusyError("a point-0 dispatch is already in flight")
        if isinstance(envelope, (bytes, bytearray, memoryview)):
            envelope = BinaryEnvelope.from_bytes(envelope)
        elif not isinstance(envelope, BinaryEnvelope):
            raise EnvelopeFormatError("envelope must be a BinaryEnvelope or bytes")

        # Validate magic/version/length/digest before touching scheduler state.
        self.bridge.decode(envelope)
        state = self._active_state()
        self._require_binding(envelope, state)
        # Re-read immediately before the executor call.  This closes the window
        # in which the scheduler could have advanced during envelope validation.
        state = self._active_state()
        self._require_binding(envelope, state)

        self._in_flight = True
        try:
            executed = self._executor(
                state.slot, state.epoch, envelope.payload
            )
            if isinstance(executed, Point0ExecutorResult):
                result_payload = executed.payload
                result_status = executed.result_status
            else:
                result_payload = executed
                result_status = RESULT_STATUS_OK
            if not isinstance(result_payload, (bytes, bytearray, memoryview)):
                raise ExecutorResultError(
                    "executor must return binary bytes"
                )
            result_payload = bytes(result_payload)
            if len(result_payload) > self.bridge.max_payload_bytes:
                raise FrameTooLargeError(
                    "executor result exceeds the configured frame bound"
                )
            if len(result_payload) % WORD_BYTES:
                raise ExecutorResultError(
                    "executor result must be a whole number of 64-bit words"
                )
            final_state = self._active_state()
            self._require_binding(envelope, final_state)
        finally:
            self._in_flight = False

        result_envelope = BinaryEnvelope.create(
            request_id=envelope.request_id,
            payload=result_payload,
            active_slot=state.slot,
            epoch=state.epoch,
            nan_word_count=len(result_payload) // WORD_BYTES,
            result_status=result_status,
        )
        result_frame = self.bridge.decode(
            result_envelope,
            expected_active_slot=state.slot,
            expected_epoch=state.epoch,
            expected_request_id=envelope.request_id,
        )
        return Point0Result(
            frame=result_frame,
            active_slot=state.slot,
            epoch=state.epoch,
            request_digest=envelope.digest,
            result_digest=result_envelope.digest,
            result_status=result_status,
            output_digest=result_envelope.output_digest,
            point_zero=result_envelope.point_zero,
        )

    def _require_binding(
        self, envelope: BinaryEnvelope, state: _ActiveState
    ) -> None:
        if envelope.epoch != state.epoch:
            raise StaleEnvelopeError(
                f"envelope epoch {envelope.epoch} is stale; "
                f"current epoch is {state.epoch}"
            )
        if envelope.active_slot != state.slot:
            raise InactiveSlotError(
                f"envelope targets slot {envelope.active_slot}, "
                f"but slot {state.slot} is active"
            )

    def _active_state(self) -> _ActiveState:
        try:
            snapshot = self.scheduler.snapshot()
        except Exception as exc:  # scheduler must never fail open
            raise NoActiveSlotError(
                "scheduler snapshot is unavailable"
            ) from exc
        if not isinstance(snapshot, Mapping):
            raise NoActiveSlotError("scheduler snapshot must be a mapping")
        if not snapshot.get("started"):
            raise NoActiveSlotError("the runner ring has not been started")
        if snapshot.get("stale"):
            raise StaleEnvelopeError(
                "the active slot heartbeat is stale; refusing point-0 work"
            )
        jahs = snapshot.get("jahs")
        if not isinstance(jahs, Mapping) or jahs.get("seal") != "JAHS":
            raise NoActiveSlotError(
                "the runner ring handoff seal is missing; JAHS gate not satisfied"
            )
        slot = snapshot.get("active_slot")
        if not _is_int(slot) or not 0 <= slot < SLOT_COUNT:
            raise NoActiveSlotError("the runner ring has no active slot")
        epoch = snapshot.get("epoch")
        if not _is_int(epoch) or epoch < 1:
            raise StaleEnvelopeError("the runner ring has no live epoch")
        active_count = snapshot.get("active_count")
        if active_count is not None and active_count != 1:
            raise NoActiveSlotError(
                "the runner ring must expose exactly one active slot"
            )
        slots = snapshot.get("slots")
        if not isinstance(slots, (list, tuple)):
            raise NoActiveSlotError("scheduler snapshot has no slot inventory")
        active_entries = [
            entry
            for entry in slots
            if isinstance(entry, Mapping) and entry.get("status") == "active"
        ]
        if len(active_entries) != 1:
            raise NoActiveSlotError(
                "the runner ring must expose exactly one active slot"
            )
        entry = active_entries[0]
        entry_index = entry.get("index", entry.get("slot"))
        if entry_index != slot:
            raise NoActiveSlotError(
                "scheduler active slot and slot inventory disagree"
            )
        return _ActiveState(slot=slot, epoch=epoch)


__all__ = [
    "BinaryEnvelope",
    "BinaryEnvelopeError",
    "EnvelopeFormatError",
    "Executor",
    "ExecutorResultError",
    "FrameError",
    "FrameTooLargeError",
    "InactiveSlotError",
    "LEGACY_VERSION",
    "MAGIC",
    "MAX_FRAME_WORDS",
    "MAX_PAYLOAD_BYTES",
    "NanFrame",
    "NoActiveSlotError",
    "OversizedFrameError",
    "POINT_ZERO_ADDRESS",
    "POINT_ZERO_IDENTITY",
    "POINT_ZERO_LABEL",
    "POINT_ZERO_LEGACY_ADDRESS",
    "POINT_ZERO_WIRE",
    "Point0Bridge",
    "Point0BridgeError",
    "Point0Error",
    "Point0ExecutionResult",
    "Point0ExecutorResult",
    "Point0Result",
    "Point0Router",
    "RESULT_STATUSES",
    "RESULT_STATUS_OK",
    "ResultDigestMismatchError",
    "RouterBusyError",
    "StaleEnvelopeError",
    "StaleEpochError",
    "SUPPORTED_VERSIONS",
    "VERSION",
    "WIRE_ENDIAN",
    "WORD_BITS",
    "WORD_BYTES",
]
