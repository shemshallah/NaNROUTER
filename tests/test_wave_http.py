import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from runner_riddle.wave_http import MAX_BODY_BYTES, WaveHttpServer
from runner_riddle.wave_service import WaveService
from runner_riddle.wave_store import WaveStore


class WaveHttpAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = WaveStore(root / "bs0db.sqlite3", root / "mc0db.sqlite3")
        self.submit_token = "submit-token-http-000000000"
        self.worker_token = "worker-token-http-111111111"
        self.admin_token = "admin-token-http-2222222222"
        self.wrong_token = "wrong-token-http-99999999999"
        self.digest = "a" * 64
        self.result_digest = "d" * 64
        self.service = WaveService(
            self.store, self.submit_token, self.worker_token,
            self.admin_token,
        )
        self.server = WaveHttpServer(self.service)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.base = self.server.base_url

    def call(self, method, path, *, body=None, raw=None, token=None,
             content_type="application/json", headers=None):
        if raw is None and body is not None:
            raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
        request_headers = dict(headers or {})
        if raw is not None:
            request_headers.setdefault("Content-Type", content_type)
        if token is not None:
            request_headers["Authorization"] = "Bearer " + token
        request = Request(
            self.base + path, data=raw, headers=request_headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=10) as response:
                status = response.status
                response_headers = dict(response.headers)
                payload = response.read()
        except HTTPError as exc:
            status = exc.code
            response_headers = dict(exc.headers)
            payload = exc.read()
        decoded = json.loads(payload) if payload else None
        return status, decoded, payload, response_headers

    def submit(self, job_id="job-http-1", generation=7, tick=100):
        return self.call(
            "POST", "/v1/wave/jobs",
            body={
                "job_id": job_id,
                "universe_id": "universe-0",
                "operator_digest": self.digest,
                "generation": generation,
                "payload": {"step": 1},
                "now_tick": tick,
                "precision": "Q16.16",
                "workspace": 4096,
            },
            token=self.submit_token,
        )

    # -- Health ---------------------------------------------------------------

    def test_health_needs_no_auth_and_contains_no_tokens(self):
        status, body, raw, headers = self.call("GET", "/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(body["schema"], "nanrouter.wave-store-health.v1")
        self.assertEqual(body["status"], "green")
        self.assertEqual(body["jobs"]["queued"], 0)
        self.assertEqual(headers["Content-Type"], "application/json")
        for token in (self.submit_token, self.worker_token, self.admin_token):
            self.assertNotIn(token.encode("utf-8"), raw)
            self.assertNotIn(token, json.dumps(body, sort_keys=True))

    # -- Authentication and authorization ------------------------------------

    def test_submit_with_wrong_token_is_rejected_without_mutation(self):
        job_body = {
            "job_id": "rejected-job",
            "universe_id": "universe-0",
            "operator_digest": self.digest,
            "generation": 7,
            "payload": {"step": 1},
            "now_tick": 100,
        }
        status, body, raw, headers = self.call(
            "POST", "/v1/wave/jobs", body=job_body,
        )
        self.assertEqual(status, 401)
        self.assertEqual(headers["WWW-Authenticate"], 'Bearer realm="wave"')
        self.assertIn("error", body)

        status, body, raw, headers = self.call(
            "POST", "/v1/wave/jobs", body=job_body, token=self.wrong_token,
        )
        self.assertEqual(status, 401)
        self.assertIn("error", body)
        self.assertEqual(headers["WWW-Authenticate"], 'Bearer realm="wave"')
        self.assertNotIn(self.wrong_token.encode("utf-8"), raw)
        self.assertEqual(self.store.stats()["jobs"]["queued"], 0)

    def test_valid_token_without_the_required_role_is_forbidden(self):
        status, body, raw, _ = self.call(
            "POST", "/v1/wave/jobs",
            body={
                "job_id": "wrong-role-job",
                "universe_id": "universe-0",
                "operator_digest": self.digest,
                "generation": 7,
                "payload": {},
                "now_tick": 100,
            },
            token=self.worker_token,
        )
        self.assertEqual(status, 403)
        self.assertIn("role", body["error"])
        self.assertNotIn(self.worker_token.encode("utf-8"), raw)
        self.assertEqual(self.store.stats()["jobs"]["queued"], 0)

        status, _, _, _ = self.call(
            "POST", "/v1/wave/lease",
            body={"owner": "MC0:0/R0", "now_tick": 100, "lease_ticks": 32},
            token=self.submit_token,
        )
        self.assertEqual(status, 403)

    # -- Jobs and leases ------------------------------------------------------

    def test_submit_lease_complete_happy_path(self):
        status, body, _, _ = self.submit()
        self.assertEqual(status, 200)
        job = body["job"]
        self.assertEqual(job["job_id"], "job-http-1")
        self.assertEqual(job["state"], "queued")
        self.assertEqual(job["generation"], 7)
        self.assertEqual(job["payload"], {"step": 1})
        self.assertEqual(job["precision"], "Q16.16")

        status, body, _, _ = self.call(
            "POST", "/v1/wave/lease",
            body={"owner": "MC0:0/R0", "now_tick": 110, "lease_ticks": 32},
            token=self.worker_token,
        )
        self.assertEqual(status, 200)
        leased = body["job"]
        self.assertIsNotNone(leased)
        self.assertEqual(leased["state"], "leased")
        self.assertEqual(leased["lease_owner"], "MC0:0/R0")
        self.assertEqual(leased["lease_epoch"], 1)
        self.assertEqual(leased["deadline_tick"], 142)
        self.assertEqual(len(leased["lease_token"]), 64)

        status, body, _, _ = self.call(
            "POST", "/v1/wave/complete",
            body={
                "job_id": leased["job_id"],
                "lease_token": leased["lease_token"],
                "lease_epoch": leased["lease_epoch"],
                "result_digest": self.result_digest,
                "now_tick": 120,
                "result_generation": 8,
                "lease_owner": "MC0:0/R0",
            },
            token=self.worker_token,
        )
        self.assertEqual(status, 200)
        done = body["job"]
        self.assertEqual(done["state"], "done")
        self.assertEqual(done["result_digest"], self.result_digest)
        self.assertEqual(done["result_generation"], 8)

        status, body, _, _ = self.call(
            "POST", "/v1/wave/lease",
            body={"owner": "MC0:0/R0", "now_tick": 121, "lease_ticks": 32},
            token=self.worker_token,
        )
        self.assertEqual(status, 200)
        self.assertIsNone(body["job"])
        self.assertEqual(self.store.health()["jobs"]["done"], 1)

    # -- Capabilities ---------------------------------------------------------

    def test_admin_capability_registration(self):
        body = {
            "kernel_id": "mth.k255.laplacian.u16",
            "runner_id": "MC0:0/R0",
            "verified_digest": self.digest,
            "workspace": 4096,
            "precision": "Q16.16",
            "epoch": 1,
            "status": "native_verified",
            "nanclock_tick": 7,
        }
        status, response, _, _ = self.call(
            "POST", "/v1/wave/capabilities", body=body,
            token=self.admin_token,
        )
        self.assertEqual(status, 200)
        capability = response["capability"]
        self.assertEqual(capability["kernel_id"], body["kernel_id"])
        self.assertEqual(capability["status"], "native_verified")
        self.assertEqual(capability["verified_digest"], self.digest)
        self.assertEqual(self.store.health()["native_verified_capabilities"], 1)

        for token in (self.submit_token, self.worker_token):
            status, _, _, _ = self.call(
                "POST", "/v1/wave/capabilities", body=body, token=token,
            )
            self.assertEqual(status, 403)

    # -- Request limits and parsing ------------------------------------------

    def test_oversized_body_is_rejected_with_a_bounded_error(self):
        raw_body = b'{"padding":"' + b"x" * MAX_BODY_BYTES + b'"}'
        status, body, raw, _ = self.call(
            "POST", "/v1/wave/jobs", raw=raw_body, token=self.submit_token,
        )
        self.assertEqual(status, 400)
        self.assertIn("exceeds", body["error"])
        self.assertLess(len(raw), 1024)
        self.assertNotIn(self.submit_token.encode("utf-8"), raw)

    def test_content_type_and_json_validation(self):
        valid = {
            "job_id": "job-http-1",
            "universe_id": "universe-0",
            "operator_digest": self.digest,
            "generation": 7,
            "payload": {},
            "now_tick": 100,
        }
        cases = [
            ("wrong content type", dict(body=valid, content_type="text/plain")),
            ("malformed json", dict(raw=b"{", content_type="application/json")),
            ("not an object", dict(raw=b"[]", content_type="application/json")),
            ("duplicate key", dict(
                raw=b'{"job_id":"a","job_id":"b"}',
                content_type="application/json",
            )),
            ("empty body", dict(raw=b"", content_type="application/json")),
        ]
        for label, kwargs in cases:
            with self.subTest(label):
                status, body, raw, _ = self.call(
                    "POST", "/v1/wave/jobs", token=self.submit_token, **kwargs
                )
                self.assertEqual(status, 400)
                self.assertIn("error", body)
                self.assertLess(len(raw), 1024)

    def test_unknown_route_returns_404_and_wrong_method_returns_405(self):
        status, body, _, _ = self.call("GET", "/v1/wave/unknown")
        self.assertEqual(status, 404)
        self.assertIn("not found", body["error"])

        status, _, _, _ = self.call(
            "POST", "/v1/wave/unknown", body={"anything": 1},
            token=self.submit_token,
        )
        self.assertEqual(status, 404)

        status, body, _, headers = self.call("GET", "/v1/wave/jobs")
        self.assertEqual(status, 405)
        self.assertEqual(headers["Allow"], "POST")
        self.assertIn("method", body["error"])

        status, _, _, _ = self.call("POST", "/healthz", body={})
        self.assertEqual(status, 405)

    # -- Error mapping --------------------------------------------------------

    def test_conflict_and_stale_generation_map_to_409(self):
        status, _, _, _ = self.submit()
        self.assertEqual(status, 200)
        status, body, _, _ = self.call(
            "POST", "/v1/wave/jobs",
            body={
                "job_id": "job-http-1",
                "universe_id": "universe-0",
                "operator_digest": self.digest,
                "generation": 8,
                "payload": {"step": 1},
                "now_tick": 101,
            },
            token=self.submit_token,
        )
        self.assertEqual(status, 409)
        self.assertIn("generation", body["error"])

    def test_store_busy_maps_to_429(self):
        with mock.patch.object(
            self.service, "lease_job",
            side_effect=sqlite3.OperationalError("database is locked"),
        ):
            status, body, _, headers = self.call(
                "POST", "/v1/wave/lease",
                body={"owner": "MC0:0/R0", "now_tick": 100, "lease_ticks": 32},
                token=self.worker_token,
            )
        self.assertEqual(status, 429)
        self.assertTrue(body["retryable"])
        self.assertEqual(headers["Retry-After"], "1")

    def test_unexpected_error_maps_to_generic_500_without_leakage(self):
        with mock.patch.object(
            self.service, "submit_job",
            side_effect=RuntimeError(f"boom {self.submit_token}"),
        ):
            status, body, raw, _ = self.call(
                "POST", "/v1/wave/jobs",
                body={
                    "job_id": "job-http-1",
                    "universe_id": "universe-0",
                    "operator_digest": self.digest,
                    "generation": 7,
                    "payload": {},
                    "now_tick": 100,
                },
                token=self.submit_token,
            )
        self.assertEqual(status, 500)
        self.assertEqual(body["error"], "internal service error")
        self.assertNotIn(b"boom", raw)
        self.assertNotIn(b"Traceback", raw)
        self.assertNotIn(self.submit_token.encode("utf-8"), raw)

    # -- Token hygiene --------------------------------------------------------

    def test_no_service_token_leaks_through_responses_health_or_logs(self):
        responses = []
        log = io.StringIO()
        with contextlib.redirect_stderr(log):
            responses.append(self.call("GET", "/healthz")[2])
            responses.append(self.call(
                "POST", "/v1/wave/jobs",
                body={
                    "job_id": "job-http-1",
                    "universe_id": "universe-0",
                    "operator_digest": self.digest,
                    "generation": 7,
                    "payload": {},
                    "now_tick": 100,
                },
                token=self.wrong_token,
            )[2])
            responses.append(self.call(
                "POST", "/v1/wave/jobs",
                body={
                    "job_id": "job-http-1",
                    "universe_id": "universe-0",
                    "operator_digest": self.digest,
                    "generation": 7,
                    "payload": {},
                    "now_tick": 100,
                },
                token=self.worker_token,
            )[2])
            responses.append(self.call(
                "POST", "/v1/wave/jobs",
                raw=b"{" + b"x" * MAX_BODY_BYTES + b"}",
                token=self.submit_token,
            )[2])
        for token in (
            self.submit_token, self.worker_token, self.admin_token,
            self.wrong_token,
        ):
            self.assertNotIn(token, log.getvalue())
            for response in responses:
                self.assertNotIn(token.encode("utf-8"), response)
        self.assertEqual(log.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
