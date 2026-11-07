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

Binary envelope v1 layout (all integers big-endian)::

    offset  size  field
    0       4     magic              b"N16B"
    4       1     version            1
    5       1     active_slot        0..5
    6       8     request_id         unsigned 64-bit
    14      8     epoch              unsigned 64-bit
    22      4     length             payload bytes, unsigned 32-bit
    26      32    digest             SHA-256 over the header above + payload
    58      N     payload            N / 8 exact 64-bit words

The envelope digest binds every header field, including the slot and epoch.
A router accepts an envelope only when its slot and epoch equal the scheduler's
current activation.  Point 0 remains the public address before and after a ring
cycle; the active slot is evidence, not an address component.
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

# Stable point-0 identity.  BSR0 is the zero-based wire coordinate used by the
# existing bridge protocol; the human/display label for point 0 is BSR1.
POINT_ZERO_ADDRESS = "nan://GM0:SC0:MC0:BS0:0:HW0:0"
POINT_ZERO_WIRE = "BSR0"
POINT_ZERO_LABEL = "point-0"

# Transport is always network byte order, independent of the host.
WIRE_ENDIAN = "big"
WORD_BITS = 64
WORD_BYTES = WORD_BITS // 8
# 1 MiB / 8-byte NaN16 word = 131,072 words.  Bridge instances may set a
# smaller per-frame limit; this is only the hard ceiling.
MAX_FRAME_WORDS = 262144
MAX_PAYLOAD_BYTES = MAX_FRAME_WORDS * WORD_BYTES

MAGIC = b"N16B"
VERSION = 1
SUPPORTED_VERSIONS = frozenset({VERSION})

_HEADER = struct.Struct(">4sBBQQI32s")
_HEADER_SIZE = _HEADER.size
_MAX_UINT64 = (1 << 64) - 1
_DIGEST_SIZE = 32
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
    if route in (POINT_ZERO_ADDRESS, POINT_ZERO_WIRE):
        return POINT_ZERO_ADDRESS
    if any(marker in route for marker in _FORBIDDEN_ROUTE_MARKERS):
        raise FrameError("route must not address a runner slot directly")
    raise FrameError(
        f"route must use the stable point-0 address {POINT_ZERO_ADDRESS!r}"
    )


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


def _digest_material(
    magic: bytes,
    version: int,
    active_slot: int,
    request_id: int,
    epoch: int,
    length: int,
    payload: bytes,
) -> bytes:
    return (
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
    )


def _compute_digest(
    magic: bytes,
    version: int,
    active_slot: int,
    request_id: int,
    epoch: int,
    length: int,
    payload: bytes,
) -> bytes:
    return hashlib.sha256(
        _digest_material(
            magic, version, active_slot, request_id, epoch, length, payload
        )
    ).digest()


@dataclass(frozen=True)
class BinaryEnvelope:
    """Point-0 binary transport envelope (v1, network byte order)."""

    magic: bytes
    version: int
    request_id: int
    length: int
    payload: bytes
    digest: bytes
    active_slot: int
    epoch: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "magic", bytes(self.magic))
        object.__setattr__(self, "payload", bytes(self.payload))
        object.__setattr__(self, "digest", bytes(self.digest))

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
    ) -> "BinaryEnvelope":
        """Build an envelope and compute its digest from its exact bytes."""
        payload = bytes(payload)
        request_id = _require_uint("request_id", request_id)
        active_slot = _require_active_slot(active_slot)
        epoch = _require_uint("epoch", epoch)
        if not isinstance(magic, (bytes, bytearray)) or len(magic) != 4:
            raise EnvelopeFormatError("magic must be exactly four bytes")
        if not _is_int(version) or not 0 <= version <= 255:
            raise EnvelopeFormatError("version must be an unsigned byte")
        if len(payload) > MAX_PAYLOAD_BYTES:
            raise FrameTooLargeError(
                f"payload exceeds {MAX_PAYLOAD_BYTES} bytes"
            )
        if len(payload) % WORD_BYTES:
            raise EnvelopeFormatError(
                "payload length must be a multiple of eight bytes"
            )
        length = len(payload)
        digest = _compute_digest(
            bytes(magic),
            version,
            active_slot,
            request_id,
            epoch,
            length,
            payload,
        )
        return cls(
            magic=bytes(magic),
            version=version,
            request_id=request_id,
            length=length,
            payload=payload,
            digest=digest,
            active_slot=active_slot,
            epoch=epoch,
        )

    def to_bytes(self) -> bytes:
        """Serialize the envelope, including its stored digest."""
        try:
            header = _HEADER.pack(
                self.magic,
                self.version,
                self.active_slot,
                self.request_id,
                self.epoch,
                self.length,
                self.digest,
            )
        except struct.error as exc:
            raise EnvelopeFormatError("envelope fields do not fit the v1 wire layout") from exc
        return header + self.payload

    @classmethod
    def from_bytes(cls, data: bytes) -> "BinaryEnvelope":
        """Parse and fully validate an envelope from its wire representation."""
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise EnvelopeFormatError("envelope must be bytes-like")
        raw = bytes(data)
        if len(raw) < _HEADER_SIZE:
            raise EnvelopeFormatError("binary envelope is shorter than its header")
        (
            magic,
            version,
            active_slot,
            request_id,
            epoch,
            length,
            digest,
        ) = _HEADER.unpack_from(raw, 0)
        payload = raw[_HEADER_SIZE:]
        envelope = cls(
            magic=magic,
            version=version,
            request_id=request_id,
            length=length,
            payload=payload,
            digest=digest,
            active_slot=active_slot,
            epoch=epoch,
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
    expected = _compute_digest(
        bytes(envelope.magic),
        envelope.version,
        envelope.active_slot,
        envelope.request_id,
        envelope.epoch,
        envelope.length,
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
    ) -> BinaryEnvelope:
        """Encode a point-0 frame into one bounded binary envelope.

        ``active_slot`` and ``epoch`` are routing evidence supplied by the
        router, never by a client.  Standalone codec users get slot 0/epoch 0.
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
        )

    def decode(
        self,
        envelope: BinaryEnvelope | bytes,
        *,
        expected_active_slot: int | None = None,
        expected_epoch: int | None = None,
        expected_request_id: int | None = None,
    ) -> NanFrame:
        """Validate and decode an envelope back to an exact point-0 frame.

        Passing the expected slot, epoch, or request id turns the codec into a
        binding check: a stale epoch or an inactive slot is rejected instead of
        being silently decoded.
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
        words = _unpack_words(envelope.payload)
        provenance = (
            ("bridge", "point-0"),
            ("wire", POINT_ZERO_WIRE),
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
    """Decoded NaN16 result plus non-address routing evidence."""

    frame: NanFrame
    active_slot: int
    epoch: int
    request_digest: bytes = b""
    result_digest: bytes = b""

    def __post_init__(self) -> None:
        if not isinstance(self.frame, NanFrame):
            raise Point0BridgeError("result frame must be a NanFrame")
        object.__setattr__(
            self, "active_slot", _require_active_slot(self.active_slot)
        )
        object.__setattr__(self, "epoch", _require_uint("epoch", self.epoch))
        object.__setattr__(self, "request_digest", bytes(self.request_digest))
        object.__setattr__(self, "result_digest", bytes(self.result_digest))

    @property
    def words(self) -> tuple[int, ...]:
        return self.frame.words

    @property
    def word_count(self) -> int:
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

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-safe result evidence; the route never names a slot."""
        return {
            "route": self.route,
            "wire": POINT_ZERO_WIRE,
            "request_id": self.request_id,
            "word_count": len(self.words),
            "active_slot": self.active_slot,
            "epoch": self.epoch,
            "request_digest": self.request_digest.hex(),
            "result_digest": self.result_digest.hex(),
        }


@dataclass(frozen=True)
class _ActiveState:
    slot: int
    epoch: int


Executor = Callable[[int, int, bytes], bytes]


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

    def submit(self, frame: NanFrame) -> Point0Result:
        """Encode, route to the one active slot, execute, and decode."""
        if not isinstance(frame, NanFrame):
            raise FrameError("frame must be a NanFrame")
        if len(frame.words) > self.bridge.max_words:
            raise FrameTooLargeError(
                f"frame has {len(frame.words)} words; "
                f"limit is {self.bridge.max_words}"
            )
        with self._lock:
            state = self._active_state()
            envelope = self.bridge.encode(
                frame, active_slot=state.slot, epoch=state.epoch
            )
            return self._dispatch_locked(envelope)

    def dispatch(self, envelope: BinaryEnvelope | bytes) -> Point0Result:
        """Retry one already-encoded point-0 envelope if it is still current."""
        with self._lock:
            return self._dispatch_locked(envelope)

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
            result_payload = self._executor(
                state.slot, state.epoch, envelope.payload
            )
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
    "MAGIC",
    "MAX_FRAME_WORDS",
    "MAX_PAYLOAD_BYTES",
    "NanFrame",
    "NoActiveSlotError",
    "OversizedFrameError",
    "POINT_ZERO_ADDRESS",
    "POINT_ZERO_LABEL",
    "POINT_ZERO_WIRE",
    "Point0Bridge",
    "Point0BridgeError",
    "Point0Error",
    "Point0Result",
    "Point0Router",
    "RouterBusyError",
    "StaleEnvelopeError",
    "StaleEpochError",
    "SUPPORTED_VERSIONS",
    "VERSION",
    "WIRE_ENDIAN",
    "WORD_BITS",
    "WORD_BYTES",
]
