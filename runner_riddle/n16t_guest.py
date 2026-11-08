"""Persistent NaN16 N16T server guest runtime.

The host selects a VM by the opaque 128-bit session bytes only. An optional
durable store copies the fixed session/sequence indexes and opaque frame bytes
so a restart can replay guest-validated exchanges. The host does not parse,
validate, route, sequence, or construct N16T frames; every protocol operation
is performed by the loaded NaN16 guest through n16_server_exchange.
"""
from __future__ import annotations

import ctypes
import os
import re
import sqlite3
import struct
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

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


class N16TSessionStoreError(N16TGuestRuntimeError):
    """The durable N16T session store is unavailable, corrupt, or inconsistent."""


class N16TSessionOwnershipError(N16TSessionStoreError):
    """A stored session record does not belong to the frame's session id."""


class N16TReplayError(N16TSessionStoreError):
    """A durable session already consumed the supplied replay sequence."""


class N16TStoreCapacityError(N16TSessionStoreError):
    """The durable session store cannot admit another session or replay frame."""


_STATE_MAGIC = b"N16S"
_STATE_VERSION = 1
_STATE_STRUCT = struct.Struct("<4sHII")


def _frame_session_id(frame: bytes) -> bytes:
    return frame[8:24]


def _frame_sequence(frame: bytes) -> int:
    # Storage index only. The NaN16 guest remains the sole sequence validator.
    return int.from_bytes(frame[24:28], "little")


def _require_session_id(value: Any) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise N16TSessionStoreError("N16T session id must be bytes")
    session_id = bytes(value)
    if len(session_id) != 16:
        raise N16TSessionStoreError("N16T session id must be exactly 16 bytes")
    return session_id


def _require_frame(value: Any) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise N16TSessionStoreError("N16T replay frame must be bytes")
    frame = bytes(value)
    if not MIN_FRAME_BYTES <= len(frame) <= MAX_FRAME_BYTES:
        raise N16TSessionStoreError(
            "N16T replay frame is outside the guest transport bounds"
        )
    return frame


def _require_sequence(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise N16TSessionStoreError("N16T replay sequence must be an integer")
    if not 0 <= value <= 0xFFFFFFFF:
        raise N16TSessionStoreError("N16T replay sequence is outside u32 range")
    return value


def _encode_state(cursor: int, frame_count: int) -> bytes:
    return _STATE_STRUCT.pack(_STATE_MAGIC, _STATE_VERSION, cursor, frame_count)


def _decode_state(value: bytes) -> tuple[int, int]:
    if len(value) != _STATE_STRUCT.size:
        raise N16TSessionStoreError("N16T session checkpoint state is malformed")
    magic, version, cursor, frame_count = _STATE_STRUCT.unpack(value)
    if magic != _STATE_MAGIC or version != _STATE_VERSION:
        raise N16TSessionStoreError("N16T session checkpoint state version is unsupported")
    return cursor, frame_count


@dataclass(frozen=True)
class N16TSessionCheckpoint:
    """Opaque durable state for one N16T session.

    ``frames`` is the ordered journal of request frames that the NaN16 guest
    validated. The host never interprets them. On restore a fresh guest VM
    replays them in order, which reconstructs the guest-owned transition state
    and replay cursor exactly as they existed before the restart. ``cursor`` is
    the last guest-validated wire sequence and is used only for store indexing
    and consistency checks.
    """

    session_id: bytes
    cursor: int
    frames: tuple[bytes, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "session_id", _require_session_id(self.session_id))
        if isinstance(self.cursor, bool) or not isinstance(self.cursor, int):
            raise N16TSessionStoreError("N16T session cursor must be an integer")
        if not 0 <= self.cursor <= 0xFFFFFFFF:
            raise N16TSessionStoreError("N16T session cursor is outside u32 range")
        try:
            raw_frames = tuple(self.frames)
        except TypeError as exc:
            raise N16TSessionStoreError("N16T session frames must be iterable") from exc
        frames: list[bytes] = []
        previous = -1
        for value in raw_frames:
            frame = _require_frame(value)
            sequence = _frame_sequence(frame)
            if sequence <= previous:
                raise N16TSessionStoreError(
                    "N16T session replay journal is not strictly ordered"
                )
            previous = sequence
            frames.append(frame)
        if frames:
            if previous != self.cursor:
                raise N16TSessionStoreError(
                    "N16T session cursor does not match its replay journal"
                )
        elif self.cursor != 0:
            raise N16TSessionStoreError(
                "N16T session cursor is set without a replay journal"
            )
        object.__setattr__(self, "frames", tuple(frames))

    @property
    def sequence(self) -> int:
        """Alias for the durable replay cursor."""
        return self.cursor

    @property
    def state(self) -> bytes:
        """Versioned opaque checkpoint descriptor suitable for storage."""
        return _encode_state(self.cursor, len(self.frames))


_SESSION_SCHEMA = """
CREATE TABLE IF NOT EXISTS n16t_sessions (
    session_id BLOB PRIMARY KEY CHECK (length(session_id) = 16),
    cursor INTEGER NOT NULL CHECK (cursor >= 0),
    state BLOB NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS n16t_replay (
    session_id BLOB NOT NULL,
    sequence INTEGER NOT NULL CHECK (sequence >= 0),
    frame BLOB NOT NULL,
    PRIMARY KEY (session_id, sequence),
    FOREIGN KEY (session_id) REFERENCES n16t_sessions(session_id)
        ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS n16t_sessions_updated_at
    ON n16t_sessions(updated_at);
"""


class N16TSessionStore:
    """SQLite-backed durable N16T session and replay store.

    The store is deliberately protocol-opaque: it persists 16-byte session ids,
    wire sequence indexes, and accepted request frames. It never parses a
    payload, routes work, or authenticates a peer. A supplied store can be
    replaced by any object exposing ``load_session(session_id)``,
    ``record_exchange(session_id, sequence, frame)`` and
    ``delete_session(session_id)``.

    The table ``n16t_sessions`` owns one row per session: the replay cursor, a
    versioned opaque checkpoint descriptor, and the last-use timestamp. The
    table ``n16t_replay`` owns the accepted-frame journal keyed by
    ``(session_id, sequence)``. Replaying that journal through a fresh guest VM
    restores the guest state and cursor; the primary key also rejects a
    replayed sequence without changing the cursor.

    Use ``max_sessions`` to bound distinct durable sessions,
    ``max_replay_frames`` to bound one session's journal, and ``ttl_seconds``
    to expire abandoned sessions. Expiry removes whole sessions only; live
    sessions are never evicted by the in-memory pool.
    """

    SCHEMA_VERSION = 1

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        max_sessions: int | None = None,
        max_replay_frames: int | None = None,
        ttl_seconds: float | None = None,
        clock: Any = time.time,
        timeout: float = 30.0,
    ) -> None:
        if max_sessions is not None and (
            isinstance(max_sessions, bool)
            or not isinstance(max_sessions, int)
            or max_sessions < 1
        ):
            raise ValueError("max_sessions must be a positive integer or None")
        if max_replay_frames is not None and (
            isinstance(max_replay_frames, bool)
            or not isinstance(max_replay_frames, int)
            or max_replay_frames < 1
        ):
            raise ValueError("max_replay_frames must be a positive integer or None")
        if ttl_seconds is not None and (
            isinstance(ttl_seconds, bool)
            or not isinstance(ttl_seconds, (int, float))
            or ttl_seconds <= 0
        ):
            raise ValueError("ttl_seconds must be a positive number or None")
        if not callable(clock):
            raise TypeError("clock must be callable")
        if timeout <= 0:
            raise ValueError("timeout must be positive")

        raw_path = os.fspath(path)
        if isinstance(raw_path, bytes):
            raw_path = os.fsdecode(raw_path)
        if not raw_path:
            raise ValueError("N16T session store path must not be empty")
        self.path = raw_path
        self.max_sessions = max_sessions
        self.max_replay_frames = max_replay_frames
        self.ttl_seconds = float(ttl_seconds) if ttl_seconds is not None else None
        self._clock = clock
        self._lock = threading.RLock()
        self._db: sqlite3.Connection | None = None

        if raw_path != ":memory:":
            Path(raw_path).parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(
            raw_path,
            timeout=timeout,
            isolation_level=None,
            check_same_thread=False,
        )
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=30000")
        if raw_path != ":memory:":
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
        version = int(db.execute("PRAGMA user_version").fetchone()[0])
        if version not in (0, self.SCHEMA_VERSION):
            db.close()
            raise N16TSessionStoreError(
                f"N16T session store schema {version} is not supported"
            )
        try:
            db.executescript(_SESSION_SCHEMA)
            db.execute(f"PRAGMA user_version={self.SCHEMA_VERSION}")
            self._db = db
            self.cleanup_expired()
        except Exception:
            self._db = None
            db.close()
            raise

    @property
    def closed(self) -> bool:
        return self._db is None

    def _require_open(self) -> sqlite3.Connection:
        if self._db is None:
            raise N16TSessionStoreError("N16T session store is closed")
        return self._db

    def _rollback(self) -> None:
        if self._db is None:
            return
        try:
            self._db.execute("ROLLBACK")
        except sqlite3.Error:
            pass

    def _cleanup_expired_locked(self, now: float) -> int:
        if self._db is None or self.ttl_seconds is None:
            return 0
        cutoff = now - self.ttl_seconds
        cursor = self._db.execute(
            "DELETE FROM n16t_sessions WHERE updated_at < ?", (cutoff,)
        )
        return int(cursor.rowcount)

    def cleanup_expired(
        self, *, ttl_seconds: float | None = None, now: float | None = None
    ) -> int:
        """Delete abandoned sessions older than the configured TTL."""
        ttl = self.ttl_seconds if ttl_seconds is None else float(ttl_seconds)
        with self._lock:
            db = self._require_open()
            if ttl is None:
                return 0
            if ttl <= 0:
                raise ValueError("ttl_seconds must be positive")
            current = float(self._clock() if now is None else now)
            try:
                db.execute("BEGIN IMMEDIATE")
                cutoff = current - ttl
                cursor = db.execute(
                    "DELETE FROM n16t_sessions WHERE updated_at < ?", (cutoff,)
                )
                db.execute("COMMIT")
                return int(cursor.rowcount)
            except sqlite3.Error:
                self._rollback()
                raise N16TSessionStoreError(
                    "N16T session store cleanup failed"
                ) from None

    def load_session(self, session_id: Any) -> N16TSessionCheckpoint | None:
        """Load and validate one durable session checkpoint."""
        sid = _require_session_id(session_id)
        with self._lock:
            db = self._require_open()
            now = float(self._clock())
            try:
                self._cleanup_expired_locked(now)
                row = db.execute(
                    "SELECT cursor, state FROM n16t_sessions WHERE session_id=?",
                    (sid,),
                ).fetchone()
                if row is None:
                    return None
                cursor = int(row["cursor"])
                state_cursor, frame_count = _decode_state(bytes(row["state"]))
                if state_cursor != cursor:
                    raise N16TSessionStoreError(
                        "N16T session checkpoint cursor is inconsistent"
                    )
                journal = db.execute(
                    "SELECT sequence, frame FROM n16t_replay "
                    "WHERE session_id=? ORDER BY sequence",
                    (sid,),
                ).fetchall()
                frames: list[bytes] = []
                previous: int | None = None
                for entry in journal:
                    sequence = int(entry["sequence"])
                    frame = bytes(entry["frame"])
                    if _frame_session_id(frame) != sid:
                        raise N16TSessionOwnershipError(
                            "N16T replay journal contains another session's frame"
                        )
                    if _frame_sequence(frame) != sequence:
                        raise N16TSessionStoreError(
                            "N16T replay journal sequence is inconsistent"
                        )
                    previous = sequence
                    frames.append(frame)
                if len(frames) != frame_count:
                    raise N16TSessionStoreError(
                        "N16T replay journal length is inconsistent"
                    )
                if frames:
                    if previous != cursor:
                        raise N16TSessionStoreError(
                            "N16T replay journal cursor is inconsistent"
                        )
                elif cursor != 0:
                    raise N16TSessionStoreError(
                        "N16T session cursor is set without a replay journal"
                    )
                db.execute(
                    "UPDATE n16t_sessions SET updated_at=? WHERE session_id=?",
                    (now, sid),
                )
                return N16TSessionCheckpoint(sid, cursor, tuple(frames))
            except N16TSessionStoreError:
                raise
            except sqlite3.Error:
                raise N16TSessionStoreError(
                    "N16T session store read failed"
                ) from None

    def record_exchange(
        self, session_id: Any, sequence: Any, frame: Any
    ) -> None:
        """Persist one guest-validated exchange, keyed by session and sequence."""
        sid = _require_session_id(session_id)
        seq = _require_sequence(sequence)
        raw = _require_frame(frame)
        if _frame_session_id(raw) != sid:
            raise N16TSessionOwnershipError(
                "N16T replay frame belongs to a different session"
            )
        if _frame_sequence(raw) != seq:
            raise N16TSessionStoreError(
                "N16T replay frame sequence does not match the store key"
            )
        with self._lock:
            db = self._require_open()
            now = float(self._clock())
            try:
                db.execute("BEGIN IMMEDIATE")
                self._cleanup_expired_locked(now)
                row = db.execute(
                    "SELECT cursor FROM n16t_sessions WHERE session_id=?",
                    (sid,),
                ).fetchone()
                if row is None:
                    if self.max_sessions is not None:
                        count = int(
                            db.execute(
                                "SELECT COUNT(*) FROM n16t_sessions"
                            ).fetchone()[0]
                        )
                        if count >= self.max_sessions:
                            raise N16TStoreCapacityError(
                                "N16T durable session capacity reached"
                            )
                    frame_count = 1
                    db.execute(
                        "INSERT INTO n16t_sessions"
                        "(session_id, cursor, state, updated_at) VALUES (?,?,?,?)",
                        (sid, seq, _encode_state(seq, frame_count), now),
                    )
                else:
                    cursor = int(row["cursor"])
                    if seq <= cursor:
                        raise N16TReplayError(
                            "N16T session replay sequence was already consumed"
                        )
                    count = int(
                        db.execute(
                            "SELECT COUNT(*) FROM n16t_replay WHERE session_id=?",
                            (sid,),
                        ).fetchone()[0]
                    )
                    if (
                        self.max_replay_frames is not None
                        and count >= self.max_replay_frames
                    ):
                        raise N16TStoreCapacityError(
                            "N16T durable replay journal capacity reached"
                        )
                    frame_count = count + 1
                db.execute(
                    "INSERT INTO n16t_replay(session_id, sequence, frame) "
                    "VALUES (?,?,?)",
                    (sid, seq, raw),
                )
                if row is not None:
                    db.execute(
                        "UPDATE n16t_sessions SET cursor=?, state=?, updated_at=? "
                        "WHERE session_id=?",
                        (seq, _encode_state(seq, frame_count), now, sid),
                    )
                db.execute("COMMIT")
            except sqlite3.IntegrityError:
                self._rollback()
                raise N16TReplayError(
                    "N16T session replay sequence was already consumed"
                ) from None
            except N16TSessionStoreError:
                self._rollback()
                raise
            except sqlite3.Error:
                self._rollback()
                raise N16TSessionStoreError(
                    "N16T session store write failed"
                ) from None

    def delete_session(self, session_id: Any) -> bool:
        """Remove one durable session and its complete replay journal."""
        sid = _require_session_id(session_id)
        with self._lock:
            db = self._require_open()
            try:
                db.execute("BEGIN IMMEDIATE")
                cursor = db.execute(
                    "DELETE FROM n16t_sessions WHERE session_id=?", (sid,)
                )
                db.execute("COMMIT")
                return bool(cursor.rowcount)
            except sqlite3.Error:
                self._rollback()
                raise N16TSessionStoreError(
                    "N16T session store delete failed"
                ) from None

    def count_sessions(self) -> int:
        """Return the number of durable sessions."""
        with self._lock:
            db = self._require_open()
            try:
                return int(
                    db.execute("SELECT COUNT(*) FROM n16t_sessions").fetchone()[0]
                )
            except sqlite3.Error:
                raise N16TSessionStoreError(
                    "N16T session store read failed"
                ) from None

    def count_replay_frames(self, session_id: Any | None = None) -> int:
        """Return the number of durable accepted frames, optionally per session."""
        with self._lock:
            db = self._require_open()
            try:
                if session_id is None:
                    return int(
                        db.execute("SELECT COUNT(*) FROM n16t_replay").fetchone()[0]
                    )
                sid = _require_session_id(session_id)
                return int(
                    db.execute(
                        "SELECT COUNT(*) FROM n16t_replay WHERE session_id=?",
                        (sid,),
                    ).fetchone()[0]
                )
            except N16TSessionStoreError:
                raise
            except sqlite3.Error:
                raise N16TSessionStoreError(
                    "N16T session store read failed"
                ) from None

    def close(self) -> None:
        """Close the SQLite connection. Safe to call more than once."""
        with self._lock:
            db = self._db
            self._db = None
            if db is not None:
                db.close()

    def __enter__(self) -> "N16TSessionStore":
        self._require_open()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


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
        self.session_closed = False

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
            action = self.reg(4)
            self.session_closed = action == 2
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

    An optional ``store`` adds durable restore. The store keeps the accepted
    request journal and replay cursor for each opaque session. A fresh VM
    replays that journal through the same guest before serving new traffic, so
    the guest's own transition and replay checks still decide whether a frame
    is a duplicate or belongs to another session. Without a store the pool is
    process-local exactly as before.
    """

    def __init__(
        self,
        library_path: str | os.PathLike[str],
        image_path: str | os.PathLike[str],
        labels_path: str | os.PathLike[str],
        *,
        max_sessions: int = 8,
        max_steps: int = 12_000_000,
        store: Any = None,
        _vm_factory: Any = None,
    ) -> None:
        if max_sessions < 1 or max_sessions > 32:
            raise ValueError("max_sessions must be between 1 and 32")
        if _vm_factory is not None and not callable(_vm_factory):
            raise TypeError("_vm_factory must be callable")
        self._library_path = os.fspath(library_path)
        self._image_path = os.fspath(image_path)
        self._labels_path = os.fspath(labels_path)
        self._max_sessions = max_sessions
        self._max_steps = max_steps
        self._vm_factory = _vm_factory or _NaN16GuestVM
        self._sessions: OrderedDict[bytes, _NaN16GuestVM] = OrderedDict()
        self._active: dict[bytes, int] = {}
        self._closing: set[bytes] = set()
        self._failed: set[bytes] = set()
        self._durable: set[bytes] = set()
        self._lock = threading.RLock()
        self._closed = False
        self._owns_store = False
        self._store_close_pending = False

        if store is not None and isinstance(store, (str, bytes, os.PathLike)):
            store = N16TSessionStore(store, max_sessions=max_sessions)
            self._owns_store = True
        elif store is not None:
            for name in ("load_session", "record_exchange", "delete_session"):
                if not callable(getattr(store, name, None)):
                    raise TypeError(f"N16T session store must expose {name}()")
        self._store = store

    @property
    def store(self) -> Any:
        """The configured durable store, or None for process-local sessions."""
        return self._store

    @classmethod
    def from_env(
        cls, *, max_sessions: int = 8, store: Any = None
    ) -> "N16TGuestPool":
        required = ("NAN16_LIBRARY", "N16T_GUEST_IMAGE", "N16T_GUEST_LABELS")
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            raise RuntimeError("missing N16T guest runtime configuration: " + ", ".join(missing))
        if store is None:
            store = (
                os.environ.get("RIDDLE_N16T_SESSION_STORE")
                or os.environ.get("N16T_SESSION_STORE")
                or None
            )
        return cls(
            os.environ["NAN16_LIBRARY"],
            os.environ["N16T_GUEST_IMAGE"],
            os.environ["N16T_GUEST_LABELS"],
            max_sessions=max_sessions,
            store=store,
        )

    def _create_vm(self) -> _NaN16GuestVM:
        return self._vm_factory(
            self._library_path,
            self._image_path,
            self._labels_path,
            max_steps=self._max_steps,
        )

    def _restore_vm(
        self, session_key: bytes, checkpoint: N16TSessionCheckpoint
    ) -> _NaN16GuestVM:
        if not isinstance(checkpoint, N16TSessionCheckpoint):
            raise N16TSessionStoreError(
                "N16T session store returned an invalid checkpoint"
            )
        if checkpoint.session_id != session_key:
            raise N16TSessionOwnershipError(
                "N16T session checkpoint belongs to a different session"
            )
        frames = tuple(checkpoint.frames)
        if frames:
            if _frame_sequence(frames[-1]) != checkpoint.cursor:
                raise N16TSessionStoreError(
                    "N16T session checkpoint cursor does not match its journal"
                )
        elif checkpoint.cursor != 0:
            raise N16TSessionStoreError(
                "N16T session checkpoint has a cursor without a journal"
            )
        vm = self._create_vm()
        try:
            for frame in frames:
                if _frame_session_id(frame) != session_key:
                    raise N16TSessionOwnershipError(
                        "N16T replay journal contains another session's frame"
                    )
                vm.exchange(frame)
            if getattr(vm, "session_closed", False):
                raise N16TSessionStoreError(
                    "N16T durable checkpoint contains a closed session"
                )
            return vm
        except Exception:
            vm.close()
            raise

    def _close_owned_store_locked(self) -> None:
        if not self._owns_store or self._store is None:
            return
        store = self._store
        self._store = None
        self._store_close_pending = False
        try:
            store.close()
        except Exception:
            pass

    def exchange(self, frame: bytes) -> bytes:
        if not isinstance(frame, bytes):
            raise TypeError("N16T frame must be bytes")
        if not MIN_FRAME_BYTES <= len(frame) <= MAX_FRAME_BYTES:
            raise ValueError("N16T frame is outside the guest transport bounds")
        # This is only a session-affinity and storage key; the guest performs
        # all protocol validation, including replay and session ownership.
        session_key = frame[8:24]
        sequence = _frame_sequence(frame)
        with self._lock:
            if self._closed:
                raise N16TGuestRuntimeError("NaN16 N16T guest pool is closed")
            if session_key in self._closing:
                raise N16TGuestRuntimeError("N16T session is closing")
            if session_key in self._failed:
                raise N16TGuestRuntimeError(
                    "N16T session checkpoint is unavailable"
                )
            vm = self._sessions.get(session_key)
            if vm is None:
                if len(self._sessions) >= self._max_sessions:
                    # Never evict a live protocol state: doing so would erase
                    # its replay cursor and permit an old frame to start anew.
                    raise N16TGuestRuntimeError("N16T guest session capacity reached")
                checkpoint = None
                if self._store is not None:
                    checkpoint = self._store.load_session(session_key)
                if checkpoint is not None:
                    vm = self._restore_vm(session_key, checkpoint)
                    self._durable.add(session_key)
                else:
                    vm = self._create_vm()
                self._sessions[session_key] = vm
            else:
                self._sessions.move_to_end(session_key)
            self._active[session_key] = self._active.get(session_key, 0) + 1

        try:
            response = vm.exchange(frame)
            if vm.session_closed:
                with self._lock:
                    self._closing.add(session_key)
            if self._store is not None:
                try:
                    if vm.session_closed:
                        self._store.delete_session(session_key)
                        with self._lock:
                            self._durable.discard(session_key)
                    else:
                        self._store.record_exchange(session_key, sequence, frame)
                        with self._lock:
                            self._durable.add(session_key)
                except N16TSessionStoreError:
                    with self._lock:
                        if vm.session_closed or session_key not in self._durable:
                            self._closing.add(session_key)
                        else:
                            # The guest already consumed this sequence but the
                            # durable cursor is older. Refuse this session until
                            # a restart instead of silently accepting a replay.
                            self._failed.add(session_key)
                    raise
                except Exception:
                    with self._lock:
                        if vm.session_closed or session_key not in self._durable:
                            self._closing.add(session_key)
                        else:
                            self._failed.add(session_key)
                    raise N16TGuestRuntimeError(
                        "N16T session checkpoint commit failed"
                    ) from None
            return response
        finally:
            with self._lock:
                remaining = self._active.get(session_key, 1) - 1
                if remaining > 0:
                    self._active[session_key] = remaining
                else:
                    self._active.pop(session_key, None)
                    if session_key in self._closing:
                        self._closing.discard(session_key)
                        self._failed.discard(session_key)
                        self._durable.discard(session_key)
                        closing_vm = self._sessions.pop(session_key, None)
                        if closing_vm is not None:
                            closing_vm.close()
                    if (
                        self._closed
                        and self._store_close_pending
                        and not self._active
                    ):
                        self._close_owned_store_locked()

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
            self._failed.clear()
            self._durable.clear()
            if self._owns_store:
                if self._active:
                    self._store_close_pending = True
                else:
                    self._close_owned_store_locked()


__all__ = [
    "N16TGuestPool",
    "N16TGuestRuntimeError",
    "N16TReplayError",
    "N16TSessionCheckpoint",
    "N16TSessionOwnershipError",
    "N16TSessionStore",
    "N16TSessionStoreError",
    "N16TStoreCapacityError",
]
