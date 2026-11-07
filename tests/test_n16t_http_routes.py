import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from runner_riddle.n16t_http import N16THttpAdapter
from runner_riddle.wave_http import WaveHttpServer
from runner_riddle.wave_service import WaveService
from runner_riddle.wave_store import WaveStore


class N16THttpRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = WaveStore(root / "bs0.sqlite3", root / "mc0.sqlite3")
        self.submit_token = "submit-token-n16t-http-000000"
        self.worker_token = "worker-token-n16t-http-111111"
        self.admin_token = "admin-token-n16t-http-222222"
        self.service = WaveService(
            self.store, self.submit_token, self.worker_token, self.admin_token
        )
        self.request_frame = b"N16T" + bytes(range(32))
        self.response_frame = b"N16T" + bytes(reversed(range(32)))
        self.calls = []
        self.adapter = N16THttpAdapter(
            lambda frame: self.calls.append(frame) or self.response_frame
        )
        self.server = WaveHttpServer(self.service, n16t_adapter=self.adapter)
        self.server.start()
        self.addCleanup(self.server.stop)

    def request(self, frame, token, content_type="application/x-n16t"):
        request = Request(
            self.server.base_url + "/n16t",
            data=frame,
            headers={
                "Content-Type": content_type,
                "Authorization": "Bearer " + token,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, response.headers.get("Content-Type"), response.read()
        except HTTPError as exc:
            return exc.code, exc.headers.get("Content-Type"), exc.read()

    def test_submit_role_hands_exact_binary_frame_to_worker(self):
        status, content_type, body = self.request(self.request_frame, self.submit_token)
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/x-n16t")
        self.assertEqual(body, self.response_frame)
        self.assertEqual(self.calls, [self.request_frame])

    def test_worker_and_admin_tokens_cannot_submit_n16t(self):
        for token in (self.worker_token, self.admin_token):
            status, _, _ = self.request(self.request_frame, token)
            self.assertEqual(status, 403)
        self.assertEqual(self.calls, [])

    def test_wrong_media_type_and_short_frames_never_reach_worker(self):
        status, _, _ = self.request(self.request_frame, self.submit_token, "application/json")
        self.assertEqual(status, 400)
        status, _, _ = self.request(b"N16T" + bytes(31), self.submit_token)
        self.assertEqual(status, 400)
        self.assertEqual(self.calls, [])

    def test_route_fails_closed_without_configured_worker(self):
        server = WaveHttpServer(self.service)
        server.start()
        self.addCleanup(server.stop)
        request = Request(
            server.base_url + "/n16t",
            data=self.request_frame,
            headers={
                "Content-Type": "application/x-n16t",
                "Authorization": "Bearer " + self.submit_token,
            },
            method="POST",
        )
        with self.assertRaises(HTTPError) as caught:
            urlopen(request, timeout=5)
        self.assertEqual(caught.exception.code, 503)


if __name__ == "__main__":
    unittest.main()
