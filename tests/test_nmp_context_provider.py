from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runner_riddle import nmp
from runner_riddle.nmp_http import NmpHttpAdapter, WaveStoreNmpContextProvider
from runner_riddle.wave_service import WaveService
from runner_riddle.wave_store import WaveStore

from test_nmp_http_adapter import (
    FUNCTION,
    PREFLIGHT,
    RULES,
    admission,
    preflighted_packet,
    execution_evidence,
)


def make_context_provider(service, guest_binary_pin_provider=None):
    return WaveStoreNmpContextProvider(
        service,
        admission_provider=lambda **_: admission(),
        preflight_provider=lambda **_: {
            "result": "VALID",
            "digest": PREFLIGHT,
            "rule_snapshot_id": RULES,
        },
        ruleset_provider=lambda **_: RULES,
        ring_provider=lambda **_: {"incarnation": "ring-inc-1", "epoch": 1},
        cancel_epoch_provider=lambda **_: 0,
        guest_binary_pin_provider=guest_binary_pin_provider,
    )


class NmpServerContextProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = WaveStore(root / "bs0.sqlite3", root / "mc0.sqlite3")
        self.submit_token = "submit-token-context-provider-000"
        self.worker_token = "worker-token-context-provider-111"
        self.admin_token = "admin-token-context-provider-222"
        self.service = WaveService(
            self.store, self.submit_token, self.worker_token, self.admin_token
        )
        self.store.register_operator(
            operator_id=FUNCTION,
            version=1,
            digest="f" * 64,
            shape={"rank": 1, "dimension": 256},
            precision="float32",
            evidence_level="native_verified",
            workspace=256,
            status="active",
        )
        self.store.register_capability(
            kernel_id="vector.dot",
            runner_id="worker-A",
            verified_digest="f" * 64,
            workspace=1024,
            precision="float32",
            status="native_verified",
            epoch=1,
        )
        self.provider = make_context_provider(self.service)
        self.adapter = NmpHttpAdapter(
            self.service, self.provider,
            lambda token, owner: token == self.worker_token and owner == "worker-A",
        )

    def submit(self):
        packet = preflighted_packet()
        result = self.adapter.submit(self.submit_token, packet.to_dict(), now_tick=100)
        return packet, result["job"]["job_id"]

    def test_wave_store_context_drives_queue_lease_and_completion(self):
        packet, job_id = self.submit()
        self.assertEqual(self.store.get_job(job_id)["state"], "queued")

        leased = self.adapter.lease(
            self.worker_token,
            "worker-A",
            now_tick=110,
            lease_ticks=64,
            job_id=job_id,
        )
        self.assertIsNotNone(leased)
        self.assertEqual(leased["packet"]["state"], nmp.EXECUTING)

        completed = self.adapter.complete(
            self.worker_token,
            leased["packet"],
            job_id=job_id,
            lease_token=leased["lease"]["token"],
            lease_epoch=leased["lease"]["epoch"],
            lease_owner="worker-A",
            result_digest="e" * 64,
            now_tick=120,
            result_generation=8,
            execution_evidence=execution_evidence(
                packet, lease_epoch=leased["lease"]["epoch"],
                lease_owner="worker-A",
            ),
        )
        self.assertEqual(completed["packet"]["state"], nmp.COMPLETED)
        self.assertEqual(completed["job"]["state"], "done")

    def test_unqualified_worker_cannot_consume_or_strand_queued_job(self):
        _, job_id = self.submit()
        with self.assertRaisesRegex(Exception, "credential is not bound"):
            self.adapter.lease(
                self.worker_token,
                "worker-B",
                now_tick=110,
                lease_ticks=64,
                job_id=job_id,
            )
        queued = self.store.get_job(job_id)
        self.assertEqual(queued["state"], "queued")
        self.assertIsNone(queued.get("lease_owner"))

        allowed = self.adapter.lease(
            self.worker_token,
            "worker-A",
            now_tick=111,
            lease_ticks=64,
            job_id=job_id,
        )
        self.assertIsNotNone(allowed)
        self.assertEqual(allowed["lease"]["owner"], "worker-A")

    def test_unverified_capability_is_not_leaseable(self):
        _, job_id = self.submit()
        self.store.register_capability(
            kernel_id="vector.dot",
            runner_id="worker-A",
            verified_digest="f" * 64,
            workspace=1024,
            precision="float32",
            status="declared",
            epoch=2,
        )
        result = self.adapter.lease(
            self.worker_token,
            "worker-A",
            now_tick=110,
            lease_ticks=64,
            job_id=job_id,
        )
        self.assertIsNone(result)
        self.assertEqual(self.store.get_job(job_id)["state"], "queued")


    def test_server_owned_pins_are_enforced_at_completion(self):
        packet, job_id = self.submit()
        provider = make_context_provider(
            self.service,
            lambda **_: {
                "expected_guest_image_digest": "a" * 64,
                "expected_guest_source_digest": "c" * 64,
            },
        )
        adapter = NmpHttpAdapter(
            self.service, provider,
            lambda token, owner: token == self.worker_token and owner == "worker-A",
        )
        leased = adapter.lease(
            self.worker_token, "worker-A", now_tick=110,
            lease_ticks=64, job_id=job_id,
        )
        with self.assertRaisesRegex(Exception, "differs from server-pinned guest"):
            adapter.complete(
                self.worker_token, leased["packet"],
                job_id=job_id,
                lease_token=leased["lease"]["token"],
                lease_epoch=leased["lease"]["epoch"],
                lease_owner="worker-A", result_digest="e" * 64, now_tick=120,
                execution_evidence=execution_evidence(
                    packet, lease_epoch=leased["lease"]["epoch"],
                    lease_owner="worker-A",
                ),
            )
        self.assertEqual(self.store.get_job(job_id)["state"], "leased")

    def test_server_owned_matching_pins_allow_completion(self):
        packet, job_id = self.submit()
        provider = make_context_provider(
            self.service,
            lambda **_: {
                "expected_guest_image_digest": "b" * 64,
                "expected_guest_source_digest": "c" * 64,
            },
        )
        adapter = NmpHttpAdapter(
            self.service, provider,
            lambda token, owner: token == self.worker_token and owner == "worker-A",
        )
        leased = adapter.lease(
            self.worker_token, "worker-A", now_tick=110,
            lease_ticks=64, job_id=job_id,
        )
        completed = adapter.complete(
            self.worker_token, leased["packet"], job_id=job_id,
            lease_token=leased["lease"]["token"],
            lease_epoch=leased["lease"]["epoch"],
            lease_owner="worker-A", result_digest="e" * 64, now_tick=120,
            execution_evidence=execution_evidence(
                packet, lease_epoch=leased["lease"]["epoch"],
                lease_owner="worker-A",
            ),
        )
        self.assertEqual(completed["packet"]["state"], nmp.COMPLETED)

    def test_invalid_trusted_binary_pin_does_not_complete_job(self):
        packet, job_id = self.submit()
        provider = make_context_provider(
            self.service,
            lambda **_: {
                "expected_guest_image_digest": "not-a-digest",
                "expected_guest_source_digest": "c" * 64,
            },
        )
        adapter = NmpHttpAdapter(
            self.service, provider,
            lambda token, owner: token == self.worker_token and owner == "worker-A",
        )
        leased = adapter.lease(
            self.worker_token, "worker-A", now_tick=110,
            lease_ticks=64, job_id=job_id,
        )
        with self.assertRaisesRegex(Exception, "must be a SHA-256 digest"):
            adapter.complete(
                self.worker_token, leased["packet"], job_id=job_id,
                lease_token=leased["lease"]["token"],
                lease_epoch=leased["lease"]["epoch"],
                lease_owner="worker-A", result_digest="e" * 64, now_tick=120,
                execution_evidence=execution_evidence(
                    packet, lease_epoch=leased["lease"]["epoch"],
                    lease_owner="worker-A",
                ),
            )
        self.assertEqual(self.store.get_job(job_id)["state"], "leased")



if __name__ == "__main__":
    unittest.main()
