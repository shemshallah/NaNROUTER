import os
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


if __name__ == "__main__":
    unittest.main()
