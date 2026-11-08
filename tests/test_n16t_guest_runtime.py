import os
import sqlite3
import tempfile
import unittest
from http.server import ThreadingHTTPServer
from threading import Thread
from unittest.mock import patch
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from runner_riddle.n16t_guest import (
    N16TGuestPool,
    N16TGuestRuntimeError,
    N16TReplayError,
    N16TSessionCheckpoint,
    N16TSessionOwnershipError,
    N16TSessionStore,
    N16TSessionStoreError,
    N16TStoreCapacityError,
    REQUEST_BASE,
    RESPONSE_PAYLOAD_BASE,
    SESSION_BASE,
    _NaN16GuestVM,
)
from runner_riddle.n16t_http import N16THttpAdapter
from runner_riddle.wave_http import WaveHttpServer
from runner_riddle.wave_service import WaveService
from runner_riddle.wave_store import WaveStore
from runner_riddle.http_service import RiddleService, make_handler


_REQUIRED = ("NAN16_LIBRARY", "N16T_GUEST_IMAGE", "N16T_GUEST_LABELS")
_SKIP = not all(os.environ.get(name) for name in _REQUIRED)


def _frame(session_id, sequence, message_type=1, payload=b"\x01\x00"):
    if not isinstance(session_id, bytes) or len(session_id) != 16:
        raise ValueError("test session id must be 16 bytes")
    header = (
        b"N16T"
        + (1).to_bytes(2, "little")
        + int(message_type).to_bytes(2, "little")
        + session_id
        + int(sequence).to_bytes(4, "little")
        + len(payload).to_bytes(4, "little")
    )
    return header + payload + b"\x00\x00\x00\x00"


class _FakeGuestVM:
    """Deterministic stand-in for the native guest's replay/session checks."""

    def __init__(self, library_path, image_path, labels_path, *, max_steps=0):
        self.library_path = library_path
        self.image_path = image_path
        self.labels_path = labels_path
        self.max_steps = max_steps
        self.session_id = None
        self.last_sequence = 0
        self.state = 0
        self.session_closed = False
        self.closed = False

    def exchange(self, frame):
        if self.closed:
            raise N16TGuestRuntimeError("fake guest is closed")
        if not isinstance(frame, bytes) or len(frame) < 36:
            raise N16TGuestRuntimeError("fake guest received an invalid frame")
        session_id = frame[8:24]
        sequence = int.from_bytes(frame[24:28], "little")
        message_type = int.from_bytes(frame[6:8], "little")
        if self.session_id is not None and session_id != self.session_id:
            raise N16TGuestRuntimeError("fake guest rejected wrong session")
        if sequence <= self.last_sequence:
            raise N16TGuestRuntimeError("fake guest rejected replayed sequence")
        if message_type == 1:
            if self.state != 0:
                raise N16TGuestRuntimeError("fake guest rejected duplicate HELLO")
            self.state = 1
        elif message_type == 13:
            if self.state == 0:
                raise N16TGuestRuntimeError("fake guest rejected CLOSE while idle")
            self.state = 0
        else:
            raise N16TGuestRuntimeError("fake guest rejected unsupported type")
        self.session_id = session_id
        self.last_sequence = sequence
        self.session_closed = message_type == 13
        if self.session_closed:
            self.session_id = None
            self.last_sequence = 0
        return b"N16T" + bytes(32)

    def close(self):
        self.closed = True


def _make_fake_pool(store=None, *, max_sessions=4):
    return N16TGuestPool(
        "unused-library",
        "unused-image",
        "unused-labels",
        max_sessions=max_sessions,
        store=store,
        _vm_factory=_FakeGuestVM,
    )


class N16TSessionStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "n16t-sessions.sqlite3"
        self.session = bytes(range(1, 17))
        self.other_session = bytes(range(17, 33))

    def test_session_and_sequence_keyed_journal_survive_reopen(self):
        frame = _frame(self.session, 1)
        store = N16TSessionStore(self.path)
        try:
            store.record_exchange(self.session, 1, frame)
            self.assertEqual(store.count_sessions(), 1)
            self.assertEqual(store.count_replay_frames(self.session), 1)
            with self.assertRaises(N16TReplayError):
                store.record_exchange(self.session, 1, frame)
            checkpoint = store.load_session(self.session)
            self.assertIsNotNone(checkpoint)
            self.assertEqual(checkpoint.session_id, self.session)
            self.assertEqual(checkpoint.cursor, 1)
            self.assertEqual(checkpoint.frames, (frame,))
        finally:
            store.close()

        reopened = N16TSessionStore(self.path)
        try:
            checkpoint = reopened.load_session(self.session)
            self.assertIsNotNone(checkpoint)
            self.assertEqual(checkpoint.frames, (frame,))
            with self.assertRaises(N16TSessionOwnershipError):
                reopened.record_exchange(
                    self.session, 2, _frame(self.other_session, 2)
                )
            with self.assertRaises(N16TSessionStoreError):
                reopened.record_exchange(
                    self.session, 2, _frame(self.session, 3)
                )
        finally:
            reopened.close()

    def test_store_capacity_and_delete_cleanup(self):
        store = N16TSessionStore(self.path, max_sessions=1)
        try:
            store.record_exchange(self.session, 1, _frame(self.session, 1))
            with self.assertRaises(N16TStoreCapacityError):
                store.record_exchange(
                    self.other_session, 1, _frame(self.other_session, 1)
                )
            self.assertTrue(store.delete_session(self.session))
            self.assertEqual(store.count_sessions(), 0)
            self.assertEqual(store.count_replay_frames(), 0)
            store.record_exchange(
                self.other_session, 1, _frame(self.other_session, 1)
            )
            self.assertEqual(store.count_sessions(), 1)
        finally:
            store.close()

    def test_replay_journal_capacity_fails_closed_without_cursor_advance(self):
        store = N16TSessionStore(self.path, max_replay_frames=1)
        try:
            store.record_exchange(self.session, 1, _frame(self.session, 1))
            with self.assertRaises(N16TStoreCapacityError):
                store.record_exchange(self.session, 2, _frame(self.session, 2))
            checkpoint = store.load_session(self.session)
            self.assertIsNotNone(checkpoint)
            self.assertEqual(checkpoint.cursor, 1)
            self.assertEqual(len(checkpoint.frames), 1)
        finally:
            store.close()

    def test_ttl_cleanup_removes_abandoned_session_and_journal(self):
        now = [1000.0]
        store = N16TSessionStore(
            self.path, ttl_seconds=10, clock=lambda: now[0]
        )
        try:
            store.record_exchange(self.session, 1, _frame(self.session, 1))
            now[0] += 11
            self.assertEqual(store.cleanup_expired(), 1)
            self.assertIsNone(store.load_session(self.session))
            self.assertEqual(store.count_sessions(), 0)
            self.assertEqual(store.count_replay_frames(), 0)
        finally:
            store.close()

    def test_schema_uses_session_and_sequence_primary_key(self):
        store = N16TSessionStore(self.path)
        store.close()
        with sqlite3.connect(self.path) as db:
            session_columns = {
                row[1] for row in db.execute("PRAGMA table_info(n16t_sessions)")
            }
            replay_columns = {
                row[1] for row in db.execute("PRAGMA table_info(n16t_replay)")
            }
            primary_key = [
                row[1]
                for row in db.execute("PRAGMA table_info(n16t_replay)")
                if row[5]
            ]
        self.assertEqual(
            session_columns, {"session_id", "cursor", "state", "updated_at"}
        )
        self.assertEqual(
            replay_columns, {"session_id", "sequence", "frame"}
        )
        self.assertEqual(primary_key, ["session_id", "sequence"])


class N16TDurableSessionPoolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "n16t-sessions.sqlite3"
        self.session = bytes(range(1, 17))
        self.other_session = bytes(range(17, 33))

    def test_restart_survives_and_duplicate_sequence_is_rejected(self):
        hello = _frame(self.session, 1)
        store = N16TSessionStore(self.path, max_sessions=4)
        pool = _make_fake_pool(store)
        try:
            self.assertGreaterEqual(len(pool.exchange(hello)), 36)
        finally:
            pool.close()
        # The caller-owned store survives the pool and remains readable.
        self.assertEqual(store.count_sessions(), 1)
        checkpoint = store.load_session(self.session)
        self.assertIsNotNone(checkpoint)
        self.assertEqual(checkpoint.cursor, 1)
        store.close()

        restored_store = N16TSessionStore(self.path, max_sessions=4)
        restored = _make_fake_pool(restored_store)
        try:
            with self.assertRaises(N16TGuestRuntimeError):
                restored.exchange(hello)
            checkpoint = restored_store.load_session(self.session)
            self.assertIsNotNone(checkpoint)
            self.assertEqual(checkpoint.cursor, 1)
            self.assertEqual(len(checkpoint.frames), 1)
            close_frame = _frame(self.session, 2, 13, b"")
            self.assertGreaterEqual(len(restored.exchange(close_frame)), 36)
            self.assertEqual(restored_store.count_sessions(), 0)
            self.assertEqual(restored_store.count_replay_frames(), 0)
        finally:
            restored.close()
            restored_store.close()

    def test_wrong_session_cannot_consume_another_sessions_cursor(self):
        first_hello = _frame(self.session, 1)
        store = N16TSessionStore(self.path, max_sessions=4)
        pool = _make_fake_pool(store)
        try:
            pool.exchange(first_hello)
        finally:
            pool.close()
            store.close()

        restored_store = N16TSessionStore(self.path, max_sessions=4)
        restored = _make_fake_pool(restored_store)
        try:
            # A different opaque session id is a separate VM, not a replay of
            # the first session and not an ownership transfer.
            second_hello = _frame(self.other_session, 1)
            self.assertGreaterEqual(len(restored.exchange(second_hello)), 36)
            self.assertEqual(
                restored_store.load_session(self.session).cursor, 1
            )
            with self.assertRaises(N16TGuestRuntimeError):
                restored.exchange(first_hello)
            self.assertEqual(
                restored_store.load_session(self.other_session).cursor, 1
            )
        finally:
            restored.close()
            restored_store.close()

    def test_store_checkpoint_with_wrong_owner_is_rejected_before_guest(self):
        checkpoint = N16TSessionCheckpoint(
            self.session, 1, (_frame(self.session, 1),)
        )

        class SquattingStore:
            def __init__(self):
                self.records = []
                self.deleted = []

            def load_session(self, session_id):
                return checkpoint

            def record_exchange(self, session_id, sequence, frame):
                self.records.append((session_id, sequence, frame))

            def delete_session(self, session_id):
                self.deleted.append(session_id)

        store = SquattingStore()
        pool = _make_fake_pool(store)
        try:
            with self.assertRaises(N16TSessionOwnershipError):
                pool.exchange(_frame(self.other_session, 1))
            self.assertEqual(store.records, [])
            self.assertEqual(len(pool._sessions), 0)
        finally:
            pool.close()

    def test_checkpoint_with_foreign_session_frame_is_rejected_before_guest(self):
        foreign_frame = _frame(self.other_session, 1)
        checkpoint = N16TSessionCheckpoint(self.session, 1, (foreign_frame,))

        class ForeignFrameStore:
            def load_session(self, session_id):
                return checkpoint

            def record_exchange(self, session_id, sequence, frame):
                raise AssertionError("guest must not be exchanged")

            def delete_session(self, session_id):
                raise AssertionError("guest must not be exchanged")

        pool = _make_fake_pool(ForeignFrameStore())
        try:
            with self.assertRaises(N16TSessionOwnershipError):
                pool.exchange(_frame(self.session, 1))
            self.assertEqual(len(pool._sessions), 0)
        finally:
            pool.close()

    def test_durable_capacity_is_not_evaded_and_close_reclaims_slot(self):
        third_session = bytes(range(33, 49))
        store = N16TSessionStore(self.path, max_sessions=2)
        pool = _make_fake_pool(store, max_sessions=4)
        try:
            pool.exchange(_frame(self.session, 1))
            pool.exchange(_frame(self.other_session, 1))
            self.assertEqual(store.count_sessions(), 2)

            with self.assertRaises(N16TGuestRuntimeError):
                pool.exchange(_frame(third_session, 1))
            # A failed first checkpoint must not leave a live, unpersisted VM.
            self.assertNotIn(third_session, pool._sessions)
            self.assertEqual(store.count_sessions(), 2)

            pool.exchange(_frame(self.session, 2, 13, b""))
            self.assertEqual(store.count_sessions(), 1)
            self.assertGreaterEqual(
                len(pool.exchange(_frame(third_session, 1))), 36
            )
            self.assertEqual(store.count_sessions(), 2)
        finally:
            pool.close()
            store.close()

    def test_closed_session_is_not_resurrected_by_its_terminal_frame(self):
        hello = _frame(self.session, 1)
        close_frame = _frame(self.session, 2, 13, b"")
        store = N16TSessionStore(self.path, max_sessions=4)
        pool = _make_fake_pool(store)
        try:
            pool.exchange(hello)
            pool.exchange(close_frame)
            self.assertEqual(store.count_sessions(), 0)
        finally:
            pool.close()
            store.close()

        restored_store = N16TSessionStore(self.path, max_sessions=4)
        restored = _make_fake_pool(restored_store)
        try:
            # The terminal frame was not journaled; a fresh guest VM starts
            # idle, so replaying CLOSE is rejected just as after the in-memory
            # close destroyed the VM.
            with self.assertRaises(N16TGuestRuntimeError):
                restored.exchange(close_frame)
            self.assertGreaterEqual(len(restored.exchange(hello)), 36)
        finally:
            restored.close()
            restored_store.close()

    def test_no_store_keeps_process_local_legacy_behavior(self):
        hello = _frame(self.session, 1)
        first = _make_fake_pool()
        try:
            self.assertIsNone(first.store)
            self.assertGreaterEqual(len(first.exchange(hello)), 36)
            with self.assertRaises(N16TGuestRuntimeError):
                first.exchange(hello)
        finally:
            first.close()

        # Without a durable store, a new process starts with no replay cursor.
        second = _make_fake_pool()
        try:
            self.assertGreaterEqual(len(second.exchange(hello)), 36)
        finally:
            second.close()

    def test_from_env_uses_optional_session_store_path(self):
        env = {
            "NAN16_LIBRARY": "/unused/libnan16.so",
            "N16T_GUEST_IMAGE": "/unused/guest.nan",
            "N16T_GUEST_LABELS": "/unused/guest.labels",
            "RIDDLE_N16T_SESSION_STORE": str(self.path),
        }
        with patch.dict(os.environ, env):
            pool = N16TGuestPool.from_env(max_sessions=2)
        try:
            self.assertIsNotNone(pool.store)
            self.assertEqual(pool.store.path, str(self.path))
            self.assertTrue(self.path.exists())
        finally:
            pool.close()


@unittest.skipIf(_SKIP, "native NaN16 guest runtime artifacts are not configured")
class N16TGuestRuntimeTests(unittest.TestCase):
    def make_client(self, session_id):
        vm = _NaN16GuestVM(
            os.environ["NAN16_LIBRARY"],
            os.environ["N16T_GUEST_IMAGE"],
            os.environ["N16T_GUEST_LABELS"],
        )
        vm.write_bytes(SESSION_BASE, session_id)
        # HELLO payload selects the runner portal logical point 1.
        vm.write_bytes(RESPONSE_PAYLOAD_BASE, b"\x01\x00")
        return vm

    def send_hello(self, client):
        client.call(
            "n16_android_build",
            {
                1: REQUEST_BASE,
                2: 1,
                4: RESPONSE_PAYLOAD_BASE,
                5: 2,
                6: SESSION_BASE,
            },
        )
        self.assertEqual(client.reg(3), 0)
        self.assertEqual(client.reg(1), 38)
        request = client.read_bytes(REQUEST_BASE, client.reg(1))
        client.call("n16_android_advance")
        self.assertEqual(client.reg(3), 0)
        return request

    def test_guest_owned_hello_capabilities_crc_route_and_replay(self):
        pool = N16TGuestPool(
            os.environ["NAN16_LIBRARY"],
            os.environ["N16T_GUEST_IMAGE"],
            os.environ["N16T_GUEST_LABELS"],
        )
        client = self.make_client(bytes(range(1, 17)))
        try:
            request = self.send_hello(client)

            corrupt = bytearray(request)
            corrupt[-1] ^= 0x01
            with self.assertRaises(N16TGuestRuntimeError):
                pool.exchange(bytes(corrupt))

            response = pool.exchange(request)
            self.assertEqual(len(response), 44)

            client.write_bytes(REQUEST_BASE, response)
            client.call("n16_android_route", {1: REQUEST_BASE, 2: len(response)})
            self.assertEqual(client.reg(3), 2)
            self.assertEqual(client.reg(4), 0xA001)

            with self.assertRaises(N16TGuestRuntimeError):
                pool.exchange(request)
        finally:
            client.close()
            pool.close()

    def test_guest_close_resets_the_server_session(self):
        pool = N16TGuestPool(
            os.environ["NAN16_LIBRARY"],
            os.environ["N16T_GUEST_IMAGE"],
            os.environ["N16T_GUEST_LABELS"],
        )
        client = self.make_client(bytes(range(33, 49)))
        try:
            request = self.send_hello(client)
            response = pool.exchange(request)
            client.write_bytes(REQUEST_BASE, response)
            client.call("n16_android_route", {1: REQUEST_BASE, 2: len(response)})
            self.assertEqual(client.reg(3), 2)

            client.call(
                "n16_android_build",
                {
                    1: REQUEST_BASE,
                    2: 13,
                    4: RESPONSE_PAYLOAD_BASE,
                    5: 0,
                    6: SESSION_BASE,
                },
            )
            self.assertEqual(client.reg(3), 0)
            close_request = client.read_bytes(REQUEST_BASE, client.reg(1))
            client.call("n16_android_advance")
            self.assertEqual(client.reg(3), 0)

            close_response = pool.exchange(close_request)
            self.assertEqual(len(close_response), 36)
            self.assertEqual(close_response[:4], b"N16T")
        finally:
            client.close()
            pool.close()



    def test_live_sessions_are_not_evicted_and_guest_close_releases_capacity(self):
        pool = N16TGuestPool(
            os.environ["NAN16_LIBRARY"],
            os.environ["N16T_GUEST_IMAGE"],
            os.environ["N16T_GUEST_LABELS"],
            max_sessions=1,
        )
        first = self.make_client(bytes(range(1, 17)))
        second = self.make_client(bytes(range(17, 33)))
        try:
            first_request = self.send_hello(first)
            first_response = pool.exchange(first_request)
            first.write_bytes(REQUEST_BASE, first_response)
            first.call("n16_android_route", {1: REQUEST_BASE, 2: len(first_response)})
            self.assertEqual(first.reg(3), 2)

            second_request = self.send_hello(second)
            with self.assertRaises(N16TGuestRuntimeError):
                pool.exchange(second_request)

            # Capacity pressure must not reset the first session's replay cursor.
            with self.assertRaises(N16TGuestRuntimeError):
                pool.exchange(first_request)

            first.call(
                "n16_android_build",
                {
                    1: REQUEST_BASE,
                    2: 13,
                    4: RESPONSE_PAYLOAD_BASE,
                    5: 0,
                    6: SESSION_BASE,
                },
            )
            self.assertEqual(first.reg(3), 0)
            close_request = first.read_bytes(REQUEST_BASE, first.reg(1))
            first.call("n16_android_advance")
            self.assertEqual(first.reg(3), 0)

            close_response = pool.exchange(close_request)
            self.assertEqual(len(close_response), 36)
            self.assertEqual(len(pool._sessions), 0)

            second_response = pool.exchange(second_request)
            self.assertEqual(len(second_response), 44)
        finally:
            first.close()
            second.close()
            pool.close()

    def test_authenticated_http_route_uses_the_real_nan16_guest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = WaveStore(root / "bs0.sqlite3", root / "mc0.sqlite3")
            submit_token = "submit-token-real-n16t-000000"
            service = WaveService(
                store,
                submit_token,
                "worker-token-real-n16t-111111",
                "admin-token-real-n16t-222222",
            )
            pool = N16TGuestPool(
                os.environ["NAN16_LIBRARY"],
                os.environ["N16T_GUEST_IMAGE"],
                os.environ["N16T_GUEST_LABELS"],
            )
            server = WaveHttpServer(service, n16t_adapter=N16THttpAdapter(pool.exchange))
            server.start()
            client = self.make_client(bytes(range(65, 81)))
            try:
                request_frame = self.send_hello(client)
                unauthorized = Request(
                    server.base_url + "/n16t",
                    data=request_frame,
                    headers={"Content-Type": "application/x-n16t"},
                    method="POST",
                )
                with self.assertRaises(HTTPError) as caught:
                    urlopen(unauthorized, timeout=5)
                self.assertEqual(caught.exception.code, 401)
                caught.exception.close()

                authorized = Request(
                    server.base_url + "/n16t",
                    data=request_frame,
                    headers={
                        "Content-Type": "application/x-n16t",
                        "Authorization": "Bearer " + submit_token,
                    },
                    method="POST",
                )
                with urlopen(authorized, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.headers.get_content_type(), "application/x-n16t")
                    peer_frame = response.read()
                client.write_bytes(REQUEST_BASE, peer_frame)
                client.call("n16_android_route", {1: REQUEST_BASE, 2: len(peer_frame)})
                self.assertEqual(client.reg(3), 2)
                self.assertEqual(client.reg(4), 0xA001)
            finally:
                client.close()
                server.stop()
                pool.close()


    def test_primary_riddle_service_mounts_authenticated_n16t_peer(self):
        with tempfile.TemporaryDirectory() as directory:
            env = {
                "RIDDLE_DATA_DIR": directory,
                "RIDDLE_INTAKE_TOKEN": "intake-token-primary-n16t-000000",
                "RIDDLE_WORKER_TOKEN": "worker-token-primary-n16t-111111",
                "RIDDLE_FEEDBACK_HMAC_KEY": "feedback-key-primary-n16t-222222",
                "RIDDLE_N16T_SUBMIT_TOKEN": "submit-token-primary-n16t-333333",
                "NAN16_LIBRARY": os.environ["NAN16_LIBRARY"],
                "N16T_GUEST_IMAGE": os.environ["N16T_GUEST_IMAGE"],
                "N16T_GUEST_LABELS": os.environ["N16T_GUEST_LABELS"],
            }
            with patch.dict(os.environ, env):
                service = RiddleService()
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service))
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            client = self.make_client(bytes(range(97, 113)))
            try:
                request_frame = self.send_hello(client)
                base = f"http://127.0.0.1:{server.server_address[1]}/n16t"
                unauthorized = Request(
                    base,
                    data=request_frame,
                    headers={"Content-Type": "application/x-n16t"},
                    method="POST",
                )
                with self.assertRaises(HTTPError) as caught:
                    urlopen(unauthorized, timeout=5)
                self.assertEqual(caught.exception.code, 401)
                caught.exception.close()

                authorized = Request(
                    base,
                    data=request_frame,
                    headers={
                        "Content-Type": "application/x-n16t",
                        "Authorization": "Bearer " + env["RIDDLE_N16T_SUBMIT_TOKEN"],
                    },
                    method="POST",
                )
                with urlopen(authorized, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.headers.get_content_type(), "application/x-n16t")
                    peer_frame = response.read()
                client.write_bytes(REQUEST_BASE, peer_frame)
                client.call("n16_android_route", {1: REQUEST_BASE, 2: len(peer_frame)})
                self.assertEqual(client.reg(3), 2)
                self.assertEqual(client.reg(4), 0xA001)
            finally:
                client.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
                service.close()

    def test_opaque_session_affinity_keeps_guest_states_separate(self):
        pool = N16TGuestPool(
            os.environ["NAN16_LIBRARY"],
            os.environ["N16T_GUEST_IMAGE"],
            os.environ["N16T_GUEST_LABELS"],
            max_sessions=2,
        )
        first = self.make_client(bytes(range(1, 17)))
        second = self.make_client(bytes(range(17, 33)))
        try:
            first_response = pool.exchange(self.send_hello(first))
            second_response = pool.exchange(self.send_hello(second))
            self.assertEqual(len(first_response), 44)
            self.assertEqual(len(second_response), 44)
            self.assertEqual(len(pool._sessions), 2)
        finally:
            first.close()
            second.close()
            pool.close()

    def test_sqlite_checkpoint_restores_real_guest_replay_cursor(self):
        with tempfile.TemporaryDirectory() as directory:
            store_path = Path(directory) / "n16t-sessions.sqlite3"
            session_id = bytes(range(129, 145))
            client = self.make_client(session_id)
            try:
                hello_request = self.send_hello(client)
                pool = N16TGuestPool(
                    os.environ["NAN16_LIBRARY"],
                    os.environ["N16T_GUEST_IMAGE"],
                    os.environ["N16T_GUEST_LABELS"],
                    max_sessions=2,
                    store=store_path,
                )
                try:
                    self.assertEqual(len(pool.exchange(hello_request)), 44)
                finally:
                    pool.close()

                # Recreate the pool against the same SQLite store, simulating
                # a service restart with a fresh process-local VM inventory.
                store = N16TSessionStore(store_path, max_sessions=2)
                restored = N16TGuestPool(
                    os.environ["NAN16_LIBRARY"],
                    os.environ["N16T_GUEST_IMAGE"],
                    os.environ["N16T_GUEST_LABELS"],
                    max_sessions=2,
                    store=store,
                )
                try:
                    with self.assertRaises(N16TGuestRuntimeError):
                        restored.exchange(hello_request)

                    client.call(
                        "n16_android_build",
                        {
                            1: REQUEST_BASE,
                            2: 13,
                            4: RESPONSE_PAYLOAD_BASE,
                            5: 0,
                            6: SESSION_BASE,
                        },
                    )
                    self.assertEqual(client.reg(3), 0)
                    close_request = client.read_bytes(REQUEST_BASE, client.reg(1))
                    client.call("n16_android_advance")
                    self.assertEqual(client.reg(3), 0)

                    close_response = restored.exchange(close_request)
                    self.assertEqual(len(close_response), 36)
                    self.assertEqual(store.count_sessions(), 0)
                    self.assertEqual(store.count_replay_frames(), 0)
                finally:
                    restored.close()
                    store.close()
            finally:
                client.close()


if __name__ == "__main__":
    unittest.main()
