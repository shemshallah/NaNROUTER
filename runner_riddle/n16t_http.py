"""Authenticated opaque N16T handoff to a persistent NaN16 worker guest.

The adapter is deliberately not an N16T parser. It bounds the byte frame and
hands the exact bytes to the configured worker, which must own frame validation,
CRC, session sequencing, transition semantics, and response construction in
NaN16. No Python fallback or NMP/point-0 reinterpretation exists here.
"""
from __future__ import annotations

from collections.abc import Callable

MIN_FRAME_BYTES = 36
MAX_FRAME_BYTES = 65_572


class N16TWorkerError(RuntimeError):
    """The configured NaN16 worker failed to complete an opaque frame exchange."""


class N16THttpAdapter:
    """Bounded byte handoff to a persistent NaN16 N16T peer.

    `worker_exchange` is the worker boundary: it receives one complete N16T
    frame and must return one complete peer frame. It must be backed by the
    persistent NaN16 protocol guest, not a host-side protocol reimplementation.
    """

    def __init__(self, worker_exchange: Callable[[bytes], bytes]) -> None:
        if not callable(worker_exchange):
            raise TypeError("worker_exchange must be callable")
        self._worker_exchange = worker_exchange

    def exchange(self, frame: bytes) -> bytes:
        if not isinstance(frame, bytes):
            raise TypeError("N16T frame must be bytes")
        if not MIN_FRAME_BYTES <= len(frame) <= MAX_FRAME_BYTES:
            raise ValueError(
                f"N16T frame must be {MIN_FRAME_BYTES}..{MAX_FRAME_BYTES} bytes"
            )
        try:
            response = self._worker_exchange(frame)
        except Exception:
            raise N16TWorkerError("NaN16 N16T worker exchange failed") from None
        if not isinstance(response, bytes):
            raise N16TWorkerError("NaN16 N16T worker returned a non-byte response")
        if not MIN_FRAME_BYTES <= len(response) <= MAX_FRAME_BYTES:
            raise N16TWorkerError("NaN16 N16T worker returned an invalid frame size")
        return response


__all__ = [
    "MAX_FRAME_BYTES",
    "MIN_FRAME_BYTES",
    "N16THttpAdapter",
    "N16TWorkerError",
]
