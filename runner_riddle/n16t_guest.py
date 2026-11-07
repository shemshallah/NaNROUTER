"""Persistent NaN16 N16T server guest runtime.

The host selects a VM by the opaque 128-bit session bytes only. It does not
parse, validate, route, sequence, or construct N16T frames. Every protocol
operation is performed by the loaded NaN16 guest through n16_server_exchange.
"""
from __future__ import annotations

import ctypes
import os
import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Mapping

MIN_FRAME_BYTES = 36
MAX_FRAME_BYTES = 65_572

# Byte-addressed scratch regions, deliberately outside the guest image/data.
REQUEST_BASE = 0x0010_0000
RESPONSE_BASE = 0x0012_0000
RESPONSE_PAYLOAD_BASE = 0x0013_0000
SESSION_BASE = 0x0013_1000

NAN_BUDGET = 0
NAN_HALTED = 3


class N16TGuestRuntimeError(RuntimeError):
    """The NaN16 guest rejected a request or failed to produce a peer frame."""


def _load_labels(path: Path) -> dict[str, int]:
    labels: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) != 2:
            continue
        name, raw_address = fields
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.$]*", name):
            continue
        try:
            address = int(raw_address, 10)
        except ValueError:
            continue
        if address < 0:
            raise ValueError(f"negative NaN16 label address for {name}")
        labels[name] = address
    return labels


class _NaN16GuestVM:
    """One persistent C-core VM executing a compiled NaN16 guest image."""

    def __init__(
        self,
        library_path: str | os.PathLike[str],
        image_path: str | os.PathLike[str],
        labels_path: str | os.PathLike[str],
        *,
        max_steps: int = 12_000_000,
        run_slice: int = 250_000,
    ) -> None:
        if max_steps < 1 or run_slice < 1:
            raise ValueError("NaN16 execution budgets must be positive")
        self._lock = threading.RLock()
        self._max_steps = max_steps
        self._run_slice = run_slice
        self._labels = _load_labels(Path(labels_path))
        if "n16_server_exchange" not in self._labels:
            raise ValueError("NaN16 image is missing n16_server_exchange")
        image = Path(image_path).read_bytes()
        if not image:
            raise ValueError("NaN16 guest image is empty")

        self._lib = ctypes.CDLL(os.fspath(library_path))
        self._bind_api()
        self._vm = self._lib.nan_create()
        if not self._vm:
            raise N16TGuestRuntimeError("could not allocate NaN16 guest VM")
        self._closed = False

        image_buffer = ctypes.create_string_buffer(image)
        image_kind = ctypes.c_char_p()
        rc = self._lib.nan_load_auto(
            self._vm,
            ctypes.cast(image_buffer, ctypes.POINTER(ctypes.c_uint8)),
            len(image),
            ctypes.byref(image_kind),
        )
        if rc != 0:
            self.close()
            raise N16TGuestRuntimeError("could not load NaN16 N16T guest image")
        if image_kind.value not in (b"nan-text", b"words"):
            self.close()
            raise N16TGuestRuntimeError("unexpected NaN16 guest image format")

    def _bind_api(self) -> None:
        lib = self._lib
        vm = ctypes.c_void_p
        byte_ptr = ctypes.POINTER(ctypes.c_uint8)
        lib.nan_create.argtypes = []
        lib.nan_create.restype = vm
        lib.nan_destroy.argtypes = [vm]
        lib.nan_destroy.restype = None
        lib.nan_load_auto.argtypes = [vm, byte_ptr, ctypes.c_size_t, ctypes.POINTER(ctypes.c_char_p)]
        lib.nan_load_auto.restype = ctypes.c_int
        lib.nan_write_bytes.argtypes = [vm, ctypes.c_uint32, byte_ptr, ctypes.c_size_t]
        lib.nan_write_bytes.restype = ctypes.c_int
        lib.nan_read_bytes.argtypes = [vm, ctypes.c_uint32, byte_ptr, ctypes.c_size_t]
        lib.nan_read_bytes.restype = ctypes.c_int
        lib.nan_set_reg.argtypes = [vm, ctypes.c_int, ctypes.c_uint32]
        lib.nan_set_reg.restype = None
        lib.nan_reg.argtypes = [vm, ctypes.c_int]
        lib.nan_reg.restype = ctypes.c_uint32
        lib.nan_set_pc.argtypes = [vm, ctypes.c_uint32]
        lib.nan_set_pc.restype = None
        lib.nan_run.argtypes = [vm, ctypes.c_uint32]
        lib.nan_run.restype = ctypes.c_int
        lib.nan_trap_text.argtypes = [vm]
        lib.nan_trap_text.restype = ctypes.c_char_p

    def write_bytes(self, address: int, data: bytes) -> None:
        if not data:
            return
        buffer = ctypes.create_string_buffer(data)
        rc = self._lib.nan_write_bytes(
            self._vm, address,
            ctypes.cast(buffer, ctypes.POINTER(ctypes.c_uint8)), len(data)
        )
        if rc != 0:
            raise N16TGuestRuntimeError("NaN16 guest memory write failed")

    def read_bytes(self, address: int, length: int) -> bytes:
        if length < 0:
            raise ValueError("negative NaN16 guest read length")
        if length == 0:
            return b""
        buffer = ctypes.create_string_buffer(length)
        rc = self._lib.nan_read_bytes(
            self._vm, address,
            ctypes.cast(buffer, ctypes.POINTER(ctypes.c_uint8)), length
        )
        if rc != 0:
            raise N16TGuestRuntimeError("NaN16 guest memory read failed")
        return buffer.raw[:length]

    def reg(self, index: int) -> int:
        return int(self._lib.nan_reg(self._vm, index))

    def call(self, entry: str, registers: Mapping[int, int] | None = None) -> None:
        with self._lock:
            if self._closed:
                raise N16TGuestRuntimeError("NaN16 guest VM is closed")
            if entry not in self._labels:
                raise N16TGuestRuntimeError(f"NaN16 guest entry is unavailable: {entry}")
            for index in range(1, 13):
                self._lib.nan_set_reg(self._vm, index, 0)
            self._lib.nan_set_reg(self._vm, 13, 1)
            for index, value in (registers or {}).items():
                if index < 0 or index > 15 or value < 0 or value > 0xFFFFFFFF:
                    raise ValueError("NaN16 register index/value is out of range")
                self._lib.nan_set_reg(self._vm, index, value)
            self._lib.nan_set_pc(self._vm, self._labels[entry])

            remaining = self._max_steps
            while remaining > 0:
                budget = min(self._run_slice, remaining)
                status = int(self._lib.nan_run(self._vm, budget))
                if status == NAN_HALTED:
                    trap = self._lib.nan_trap_text(self._vm)
                    if trap:
                        message = trap.decode("ascii", "replace")
                        if message:
                            raise N16TGuestRuntimeError(f"NaN16 guest trap: {message}")
                    return
                if status != NAN_BUDGET:
                    raise N16TGuestRuntimeError(f"NaN16 guest stopped with status {status}")
                remaining -= budget
            raise N16TGuestRuntimeError("NaN16 guest execution budget exhausted")

    def exchange(self, frame: bytes) -> bytes:
        if not isinstance(frame, bytes):
            raise TypeError("N16T frame must be bytes")
        if not MIN_FRAME_BYTES <= len(frame) <= MAX_FRAME_BYTES:
            raise ValueError("N16T frame is outside the guest transport bounds")
        with self._lock:
            self.write_bytes(REQUEST_BASE, frame)
            self.call(
                "n16_server_exchange",
                {
                    1: REQUEST_BASE,
                    2: len(frame),
                    4: RESPONSE_BASE,
                    5: RESPONSE_PAYLOAD_BASE,
                    6: SESSION_BASE,
                },
            )
            response_length = self.reg(1)
            detail = self.reg(2)
            status = self.reg(3)
            if status != 0:
                raise N16TGuestRuntimeError(
                    f"NaN16 N16T guest rejected frame (status={status}, detail={detail})"
                )
            if not MIN_FRAME_BYTES <= response_length <= MAX_FRAME_BYTES:
                raise N16TGuestRuntimeError("NaN16 N16T guest returned an invalid frame length")
            return self.read_bytes(RESPONSE_BASE, response_length)

    def close(self) -> None:
        with getattr(self, "_lock", threading.RLock()):
            if not getattr(self, "_closed", True):
                vm = getattr(self, "_vm", None)
                if vm:
                    self._lib.nan_destroy(vm)
                self._vm = None
                self._closed = True


class N16TGuestPool:
    """Bounded per-session pool of persistent NaN16 protocol VMs.

    The 16 bytes at the fixed session-ID offset are used only as an opaque VM
    affinity key. The guest independently validates CRC, session ownership,
    sequence, message type, route and transition before it changes state.
    """

    def __init__(
        self,
        library_path: str | os.PathLike[str],
        image_path: str | os.PathLike[str],
        labels_path: str | os.PathLike[str],
        *,
        max_sessions: int = 8,
        max_steps: int = 12_000_000,
    ) -> None:
        if max_sessions < 1 or max_sessions > 128:
            raise ValueError("max_sessions must be between 1 and 128")
        self._library_path = os.fspath(library_path)
        self._image_path = os.fspath(image_path)
        self._labels_path = os.fspath(labels_path)
        self._max_sessions = max_sessions
        self._max_steps = max_steps
        self._sessions: OrderedDict[bytes, _NaN16GuestVM] = OrderedDict()
        self._active: dict[bytes, int] = {}
        self._closing: set[bytes] = set()
        self._lock = threading.RLock()
        self._closed = False

    @classmethod
    def from_env(cls, *, max_sessions: int = 8) -> "N16TGuestPool":
        required = ("NAN16_LIBRARY", "N16T_GUEST_IMAGE", "N16T_GUEST_LABELS")
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            raise RuntimeError("missing N16T guest runtime configuration: " + ", ".join(missing))
        return cls(
            os.environ["NAN16_LIBRARY"],
            os.environ["N16T_GUEST_IMAGE"],
            os.environ["N16T_GUEST_LABELS"],
            max_sessions=max_sessions,
        )

    def exchange(self, frame: bytes) -> bytes:
        if not isinstance(frame, bytes):
            raise TypeError("N16T frame must be bytes")
        if not MIN_FRAME_BYTES <= len(frame) <= MAX_FRAME_BYTES:
            raise ValueError("N16T frame is outside the guest transport bounds")
        # This is only a session-affinity key; the guest performs all validation.
        session_key = frame[8:24]
        with self._lock:
            if self._closed:
                raise N16TGuestRuntimeError("NaN16 N16T guest pool is closed")
            vm = self._sessions.get(session_key)
            if vm is None:
                if len(self._sessions) >= self._max_sessions:
                    evict_key = next(
                        (key for key in self._sessions if self._active.get(key, 0) == 0),
                        None,
                    )
                    if evict_key is None:
                        raise N16TGuestRuntimeError("all NaN16 guest sessions are busy")
                    self._sessions.pop(evict_key).close()
                    self._active.pop(evict_key, None)
                vm = _NaN16GuestVM(
                    self._library_path,
                    self._image_path,
                    self._labels_path,
                    max_steps=self._max_steps,
                )
                self._sessions[session_key] = vm
            else:
                self._sessions.move_to_end(session_key)
            self._active[session_key] = self._active.get(session_key, 0) + 1

        try:
            return vm.exchange(frame)
        finally:
            with self._lock:
                remaining = self._active.get(session_key, 1) - 1
                if remaining > 0:
                    self._active[session_key] = remaining
                else:
                    self._active.pop(session_key, None)
                    if session_key in self._closing:
                        self._closing.discard(session_key)
                        closing_vm = self._sessions.pop(session_key, None)
                        if closing_vm is not None:
                            closing_vm.close()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for key, vm in list(self._sessions.items()):
                if self._active.get(key, 0) == 0:
                    self._sessions.pop(key, None)
                    vm.close()
                else:
                    self._closing.add(key)


__all__ = ["N16TGuestPool", "N16TGuestRuntimeError"]
