import hmac as stdlib_hmac
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

from runner_riddle.wave_service import (
    MIN_TOKEN_LENGTH,
    WaveService,
    WaveServiceAuthError,
    WaveServiceConfigError,
)
from runner_riddle.wave_store import WaveStore


class WaveServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bs0_path = self.root / "bs0db.sqlite3"
        self.mc0_path = self.root / "mc0db.sqlite3"
        self.store = WaveStore(self.bs0_path, self.mc0_path)
        self.submit_token = "submit-token-0000000000000000"
        self.worker_token = "worker-token-1111111111111111"
        self.admin_token = "admin-token-22222222222222222"
        self.wrong_token = "wrong-token-999999999999999999"
        self.digest = "a" * 64
        self.result_digest = "d" * 64
        self.signature = "c" * 64
        self.service = self.make_service()

    def make_service(self, **overrides):
        values = {
            "submit_token": self.submit_token,
            "worker_token": self.worker_token,
            "admin_token": self.admin_token,
        }
        values.update(overrides)
        return WaveService(self.store, **values)

    def submit(self, job_id="job-1", *, tick=100, payload=None):
        return self.service.submit_job(
            self.submit_token,
            job_id,
            "universe-0",
            self.digest,
            7,
            {"step": 1} if payload is None else payload,
            tick,
            kind="wave",
            operator_id="wave.laplacian",
            precision="Q16.16",
            workspace=4096,
        )

    # -- Configuration --------------------------------------------------------

    def test_constructor_rejects_missing_weak_and_reused_tokens(self):
        valid = {
            "submit_token": self.submit_token,
            "worker_token": self.worker_token,
            "admin_token": self.admin_token,
        }
        cases = [
            ("missing submit", {"submit_token": ""}),
            ("missing worker", {"worker_token": None}),
            ("missing admin", {"admin_token": ""}),
            ("short submit", {"submit_token": "short"}),
            ("short admin", {"admin_token": "x" * (MIN_TOKEN_LENGTH - 1)}),
            ("blank admin", {"admin_token": " " * MIN_TOKEN_LENGTH}),
            ("reused submit/worker", {"worker_token": self.submit_token}),
            ("reused worker/admin", {"admin_token": self.worker_token}),
            ("reused submit/admin", {"admin_token": self.submit_token}),
        ]
        for label, override in cases:
            with self.subTest(label):
                values = dict(valid)
                values.update(override)
                with self.assertRaises(WaveServiceConfigError) as caught:
                    WaveService(self.store, **values)
                self.assertNotIn(self.submit_token, str(caught.exception))
                self.assertNotIn(self.worker_token, str(caught.exception))
                self.assertNotIn(self.admin_token, str(caught.exception))

    def test_constructor_accepts_minimum_length_and_positional_tokens(self):
        service = WaveService(
            self.store, "a" * MIN_TOKEN_LENGTH, "b" * MIN_TOKEN_LENGTH,
            "c" * MIN_TOKEN_LENGTH,
        )
        self.assertIs(service.store, self.store)

    # -- Authentication -------------------------------------------------------

    def test_wrong_and_missing_tokens_are_rejected_without_mutation(self):
        calls = [
            lambda token: self.service.submit_job(
                token, "job-x", "universe-0", self.digest, 7, {}, 100,
            ),
            lambda token: self.service.lease_job(token, "MC0:0/R0", 100, 32),
            lambda token: self.service.complete_job(
                token, "job-x", "lease-x", 1, self.result_digest, 100,
            ),
            lambda token: self.service.fail_job(
                token, "job-x", "lease-x", 1, 100, "boom",
            ),
            lambda token: self.service.register_capability(
                token, "kernel", "MC0:0/R0", self.digest, 4096, "Q16.16",
            ),
            lambda token: self.service.store_trace(
                token, "universe-0", 7, self.digest, "runner", 100,
                self.signature, payload={"trace": 1},
            ),
            lambda token: self.service.store_seal(
                token, "universe-0", 7, self.digest, "runner", 100,
                self.signature, payload={"seal": 1},
            ),
            lambda token: self.service.store_signature(
                token, "universe-0", 7, "ring", self.digest, "runner", 100,
                self.signature, payload={"signature": 1},
            ),
        ]
        for call in calls:
            with self.subTest(call=call):
                with self.assertRaises(WaveServiceAuthError):
                    call(self.wrong_token)
                with self.assertRaises(WaveServiceAuthError):
                    call(None)
        self.assertEqual(self.store.stats()["jobs"]["queued"], 0)
        self.assertEqual(self.store.stats()["bs0"]["wave_trace"], 0)
        self.assertEqual(self.store.stats()["bs0"]["wave_seal"], 0)
        self.assertEqual(self.store.stats()["bs0"]["wave_signature"], 0)

    def test_roles_are_not_interchangeable(self):
        with self.assertRaises(WaveServiceAuthError):
            self.service.submit_job(
                self.worker_token, "job-x", "universe-0", self.digest, 7, {}, 100,
            )
        with self.assertRaises(WaveServiceAuthError):
            self.service.submit_job(
                self.admin_token, "job-x", "universe-0", self.digest, 7, {}, 100,
            )
        with self.assertRaises(WaveServiceAuthError):
            self.service.lease_job(self.submit_token, "MC0:0/R0", 100, 32)
        with self.assertRaises(WaveServiceAuthError):
            self.service.store_trace(
                self.worker_token, "universe-0", 7, self.digest, "runner", 100,
                self.signature, payload={"trace": 1},
            )
        with self.assertRaises(WaveServiceAuthError):
            self.service.register_capability(
                self.submit_token, "kernel", "MC0:0/R0", self.digest, 4096,
                "Q16.16",
            )
        with self.assertRaises(WaveServiceAuthError):
            self.service.register_capability(
                self.worker_token, "kernel", "MC0:0/R0", self.digest, 4096,
                "Q16.16",
            )
        self.assertEqual(self.store.stats()["jobs"]["queued"], 0)

    def test_constant_time_comparison_is_used_for_every_auth_check(self):
        with mock.patch(
            "runner_riddle.wave_service.hmac.compare_digest",
            wraps=stdlib_hmac.compare_digest,
        ) as compare:
            with self.assertRaises(WaveServiceAuthError):
                self.service.submit_job(
                    self.wrong_token, "job-x", "universe-0", self.digest, 7,
                    {}, 100,
                )
            self.assertGreaterEqual(compare.call_count, 3)
            compare.reset_mock()
            self.submit()
            self.assertGreaterEqual(compare.call_count, 3)

    # -- Jobs and leases ------------------------------------------------------

    def test_submit_lease_complete_happy_path(self):
        job = self.submit()
        self.assertEqual(job["job_id"], "job-1")
        self.assertEqual(job["state"], "queued")
        self.assertEqual(job["generation"], 7)
        self.assertEqual(job["payload"], {"step": 1})
        self.assertEqual(job["created_tick"], 100)
        self.assertEqual(job["kind"], "wave")
        self.assertEqual(job["operator_id"], "wave.laplacian")
        self.assertEqual(job["precision"], "Q16.16")
        self.assertEqual(job["workspace"], 4096)

        leased = self.service.lease_job(
            self.worker_token, "MC0:0/R0", 110, 32, expected_generation=7,
        )
        self.assertIsNotNone(leased)
        self.assertEqual(leased["job_id"], "job-1")
        self.assertEqual(leased["state"], "leased")
        self.assertEqual(leased["lease_owner"], "MC0:0/R0")
        self.assertEqual(leased["lease_epoch"], 1)
        self.assertEqual(leased["deadline_tick"], 142)
        self.assertEqual(len(leased["lease_token"]), 64)

        done = self.service.complete_job(
            self.worker_token,
            "job-1",
            leased["lease_token"],
            leased["lease_epoch"],
            self.result_digest,
            120,
            result_generation=8,
            lease_owner="MC0:0/R0",
        )
        self.assertEqual(done["state"], "done")
        self.assertEqual(done["result_digest"], self.result_digest)
        self.assertEqual(done["result_generation"], 8)
        self.assertIsNone(
            self.service.lease_job(self.worker_token, "MC0:0/R0", 121, 32)
        )
        self.assertEqual(self.service.health()["jobs"]["done"], 1)

    def test_fail_job_uses_worker_token(self):
        self.submit()
        leased = self.service.lease_job(self.worker_token, "MC0:0/R0", 110, 32)
        with self.assertRaises(WaveServiceAuthError):
            self.service.fail_job(
                self.submit_token, "job-1", leased["lease_token"],
                leased["lease_epoch"], 111, "kernel rejected input",
            )
        failed = self.service.fail_job(
            self.worker_token, "job-1", leased["lease_token"],
            leased["lease_epoch"], 111, "kernel rejected input",
            lease_owner="MC0:0/R0",
        )
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["error"], "kernel rejected input")
        self.assertEqual(self.service.health()["jobs"]["failed"], 1)

    def test_lease_requires_worker_even_when_no_job_is_ready(self):
        with self.assertRaises(WaveServiceAuthError):
            self.service.lease_job(self.submit_token, "MC0:0/R0", 100, 32)
        self.assertIsNone(
            self.service.lease_job(self.worker_token, "MC0:0/R0", 100, 32)
        )

    # -- Capabilities ---------------------------------------------------------

    def test_capability_registration_is_admin_only(self):
        with self.assertRaises(WaveServiceAuthError):
            self.service.register_capability(
                self.submit_token, "mth.k255.laplacian.u16", "MC0:0/R0",
                self.digest, 4096, "Q16.16",
            )
        with self.assertRaises(WaveServiceAuthError):
            self.service.register_capability(
                self.worker_token, "mth.k255.laplacian.u16", "MC0:0/R0",
                self.digest, 4096, "Q16.16",
            )
        self.assertEqual(self.store.health()["native_verified_capabilities"], 0)

        capability = self.service.register_capability(
            self.admin_token, "mth.k255.laplacian.u16", "MC0:0/R0",
            self.digest, 4096, "Q16.16", status="native_verified", epoch=1,
            nanclock_tick=7,
        )
        self.assertEqual(capability["status"], "native_verified")
        self.assertEqual(capability["verified_digest"], self.digest)
        dispatchable = self.store.dispatchable_capabilities(
            workspace=4096, operator_digest=self.digest, precision="Q16.16",
        )
        self.assertEqual([row["kernel_id"] for row in dispatchable],
                         ["mth.k255.laplacian.u16"])
        self.assertEqual(self.store.health()["native_verified_capabilities"], 1)

    # -- Evidence -------------------------------------------------------------

    def test_evidence_writes_accept_submit_or_admin_but_not_worker(self):
        trace = self.service.store_trace(
            self.submit_token, "universe-0", 7, self.digest, "MC0:0/R0", 100,
            self.signature, payload={"kind": "trace"}, job_id="job-1",
        )
        seal = self.service.store_seal(
            self.admin_token, "universe-0", 7, self.digest, "MC0:0/R0", 101,
            self.signature, payload={"kind": "seal"}, job_id="job-1",
        )
        signature = self.service.store_signature(
            self.submit_token, "universe-0", 7, "ring", self.digest,
            "MC0:0/R0", 102, self.signature, payload={"kind": "signature"},
        )
        self.assertEqual(trace["payload"], {"kind": "trace"})
        self.assertEqual(seal["payload"], {"kind": "seal"})
        self.assertEqual(signature["payload"], {"kind": "signature"})

        for method, args in (
            (self.service.store_trace,
             ("universe-0", 7, self.digest, "MC0:0/R0", 103, self.signature)),
            (self.service.store_seal,
             ("universe-0", 7, self.digest, "MC0:0/R0", 103, self.signature)),
            (self.service.store_signature,
             ("universe-0", 7, "ring", self.digest, "MC0:0/R0", 103,
              self.signature)),
        ):
            with self.subTest(method=method.__name__):
                with self.assertRaises(WaveServiceAuthError):
                    method(self.worker_token, *args, payload={"rejected": True})

        with closing(sqlite3.connect(self.bs0_path)) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM wave_trace").fetchone()[0], 1
            )
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM wave_seal").fetchone()[0], 1
            )
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM wave_signature").fetchone()[0],
                1,
            )

    # -- Safety ---------------------------------------------------------------

    def test_health_is_token_free_and_available_without_auth(self):
        self.submit()
        health = self.service.health()
        self.assertEqual(health, self.store.health())
        self.assertEqual(health["schema"], "nanrouter.wave-store-health.v1")
        self.assertEqual(health["schema_version"], 1)
        self.assertEqual(health["jobs"]["queued"], 1)
        rendered = json.dumps(health, sort_keys=True)
        for token in (self.submit_token, self.worker_token, self.admin_token):
            self.assertNotIn(token, rendered)
            self.assertNotIn(token, repr(self.service))

    def test_plaintext_tokens_are_not_written_to_any_database_file(self):
        self.submit()
        leased = self.service.lease_job(self.worker_token, "MC0:0/R0", 110, 32)
        self.service.complete_job(
            self.worker_token, "job-1", leased["lease_token"],
            leased["lease_epoch"], self.result_digest, 120,
        )
        self.service.register_capability(
            self.admin_token, "kernel", "MC0:0/R0", self.digest, 4096,
            "Q16.16", status="native_verified",
        )
        self.service.store_trace(
            self.submit_token, "universe-0", 7, self.digest, "MC0:0/R0", 100,
            self.signature, payload={"trace": 1},
        )
        self.service.store_seal(
            self.admin_token, "universe-0", 7, self.digest, "MC0:0/R0", 101,
            self.signature, payload={"seal": 1},
        )
        self.service.store_signature(
            self.submit_token, "universe-0", 7, "ring", self.digest,
            "MC0:0/R0", 102, self.signature, payload={"signature": 1},
        )

        files = [path for path in self.root.rglob("*") if path.is_file()]
        self.assertTrue(files)
        blobs = b"".join(path.read_bytes() for path in files)
        for token in (self.submit_token, self.worker_token, self.admin_token):
            self.assertNotIn(token.encode("utf-8"), blobs)

    def test_auth_errors_do_not_echo_the_supplied_token(self):
        with self.assertRaises(WaveServiceAuthError) as caught:
            self.service.lease_job(self.wrong_token, "MC0:0/R0", 100, 32)
        self.assertNotIn(self.wrong_token, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
