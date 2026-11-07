import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from runner_riddle.wave_http import WaveHttpServer
from runner_riddle.wave_service import WaveService
from runner_riddle.wave_store import WaveStore


class FakeNmpAdapter:
    def __init__(self):
        self.calls = []

    def submit(self, token, packet, *, now_tick):
        self.calls.append(("submit", token, packet, now_tick))
        return {"schema": "nanrouter.nmp-submit.v1", "packet_id": packet["packet_id"]}

    def lease(self, token, owner, **kwargs):
        self.calls.append(("lease", token, owner, kwargs))
        return {"schema": "nanrouter.nmp-lease.v1", "packet": {"state": "EXECUTING"}}

    def complete(self, token, packet, **kwargs):
        self.calls.append(("complete", token, packet, kwargs))
        return {"schema": "nanrouter.nmp-complete.v1", "packet": {"state": "COMPLETED"}}


class NmpHttpRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = WaveStore(root / "bs0.sqlite3", root / "mc0.sqlite3")
        self.submit_token = "submit-token-nmp-http-000000"
        self.worker_token = "worker-token-nmp-http-111111"
        self.admin_token = "admin-token-nmp-http-222222"
        self.service = WaveService(
            self.store, self.submit_token, self.worker_token, self.admin_token
        )
        self.adapter = FakeNmpAdapter()
        self.adapter.service = self.service
        self.server = WaveHttpServer(self.service, nmp_adapter=self.adapter)
        self.server.start()
        self.addCleanup(self.server.stop)

    def request(self, path, body, token):
        raw = json.dumps(body).encode("utf-8")
        request = Request(
            self.server.base_url + path,
            data=raw,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + token,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_submit_route_is_submit_role_only(self):
        packet = {"packet_id": "packet-1"}
        status, body = self.request(
            "/v1/nmp/packets",
            {"packet": packet, "now_tick": 42},
            self.submit_token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["packet_id"], "packet-1")
        self.assertEqual(self.adapter.calls[0], ("submit", self.submit_token, packet, 42))

        status, _ = self.request(
            "/v1/nmp/packets", {"packet": packet}, self.worker_token
        )
        self.assertEqual(status, 403)

    def test_lease_and_complete_routes_are_worker_role_only(self):
        status, body = self.request(
            "/v1/nmp/lease",
            {"owner": "worker-A", "now_tick": 50, "lease_ticks": 32},
            self.worker_token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["lease"]["packet"]["state"], "EXECUTING")

        status, _ = self.request(
            "/v1/nmp/lease",
            {"owner": "worker-A", "now_tick": 50},
            self.submit_token,
        )
        self.assertEqual(status, 403)

        packet = {"packet_id": "packet-1", "state": "EXECUTING"}
        status, body = self.request(
            "/v1/nmp/complete",
            {
                "packet": packet,
                "job_id": "nmp:packet-1",
                "lease_token": "lease-token-000000000000",
                "lease_epoch": 1,
                "lease_owner": "worker-A",
                "result_digest": "a" * 64,
                "now_tick": 60,
            },
            self.worker_token,
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["packet"]["state"], "COMPLETED")

    def test_wave_service_can_lease_only_nmp_jobs(self):
        digest = "a" * 64
        self.service.submit_job(
            self.submit_token, "generic-job", "U0", digest, 1,
            {"kind": "generic"}, 1,
        )
        self.service.submit_job(
            self.submit_token, "nmp-job", "U0", digest, 1,
            {"kind": "nmp"}, 1, kind="nmp",
        )
        leased = self.service.lease_job(
            self.worker_token, "worker-A", 2, kind="nmp"
        )
        self.assertEqual(leased["job_id"], "nmp-job")
        self.assertEqual(leased["kind"], "nmp")
        self.assertEqual(self.store.get_job("generic-job")["state"], "queued")

    def test_routes_fail_closed_when_adapter_is_not_configured(self):
        server = WaveHttpServer(self.service)
        server.start()
        self.addCleanup(server.stop)
        raw = json.dumps({"packet": {"packet_id": "p"}}).encode("utf-8")
        request = Request(
            server.base_url + "/v1/nmp/packets",
            data=raw,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.submit_token,
            },
            method="POST",
        )
        with self.assertRaises(HTTPError) as caught:
            urlopen(request, timeout=5)
        self.assertEqual(caught.exception.code, 503)


if __name__ == "__main__":
    unittest.main()
