from __future__ import annotations

from dataclasses import replace
import tempfile
import unittest
from pathlib import Path

from runner_riddle import nmp
from runner_riddle.math_objects import MathAdmission, admission_id_for, digest_object
from runner_riddle.nmp_http import NmpHttpAdapter, NmpHttpError
from runner_riddle.wave_service import WaveService
from runner_riddle.wave_store import WaveStore

SNAP = "snp:" + "a" * 64
RULES = "rs:" + "c" * 64
PREFLIGHT = "d" * 64
FUNCTION = "math.vector.dot.v1"
INPUTS = (
    {"leaf_id": "nml:U0:vector:1", "version": 1, "digest": "1" * 64},
    {"leaf_id": "nml:U0:vector:2", "version": 1, "digest": "2" * 64},
)
CANDIDATE = "cnd:" + "b" * 64


def admission():
    return MathAdmission(
        admission_id=admission_id_for(CANDIDATE, SNAP, "VALID", RULES),
        candidate_id=CANDIDATE,
        verdict="VALID",
        snapshot_id=SNAP,
        rule_snapshot_id=RULES,
        preflight_digest=PREFLIGHT,
    )


def capability():
    return {
        "kernel_id": "vector.dot",
        "runner_id": "MC0:0/R0",
        "verified_digest": "f" * 64,
        "workspace": 1024,
        "precision": "float32",
        "status": "native_verified",
        "epoch": 1,
    }


def make_packet(*, metadata=None):
    return nmp.NmpPacket(
        snapshot_id=SNAP,
        base_generation=7,
        lane_id=3,
        universe_id="U0",
        function_id=FUNCTION,
        function_version=1,
        candidate_id=CANDIDATE,
        inputs=INPUTS,
        admission_id=admission().admission_id,
        admission_verdict="VALID",
        preflight_digest=PREFLIGHT,
        preflight_result="VALID",
        ruleset_id="math.rules.core.v1",
        ruleset_version=1,
        ruleset_snapshot_id=RULES,
        capability_set=({
            "required": "vector.dot",
            "workspace": 256,
            "precision": "float32",
        },),
        capability_epoch=1,
        guest_words=256,
        ring_incarnation="ring-inc-1",
        ring_epoch=1,
        jahs=nmp.JAHS_SEAL,
        state=nmp.PROPOSED,
        metadata=metadata or {},
    )


def native_receipt(packet):
    body = {
        "schema": nmp.NATIVE_ADMISSION_RECEIPT_SCHEMA,
        "packet_id": packet.packet_id,
        "candidate_digest": digest_object({
            "candidate_id": packet.candidate_id,
            "function_id": packet.function_id,
            "function_version": packet.function_version,
        }),
        "snapshot_id": packet.snapshot_id,
        "ruleset_snapshot_id": packet.ruleset_snapshot_id,
        "rule_epoch": 7,
        "rule_digest": "a" * 64,
        "input_digest": digest_object([nmp._input_identity(item) for item in packet.inputs]),
        "capability_digest": packet.capability_set_digest,
        "preflight_digest": packet.preflight_digest,
        "generation": packet.generation,
        "program_id": 79,
        "guest_status": 0,
        "producer": "nan16_guest",
    }
    return {**body, "receipt_digest": digest_object(body)}


def preflighted_packet():
    packet = make_packet(metadata={"native_admission_required": True})
    return packet.mark_preflight(
        result="VALID",
        digest=PREFLIGHT,
        admission_receipt=native_receipt(packet),
    )



def execution_evidence(packet, *, lease_epoch, lease_owner, result_digest="e" * 64,
                       program_id=79, output_digest=None):
    return {
        "schema": "nanrouter.native-kernel-execution.v1",
        "packet_id": packet.packet_id,
        "function_id": packet.function_id,
        "program_id": program_id,
        "output_kind": 3,
        "dimension": 4,
        "output_count": 1,
        "output_digest": output_digest or result_digest,
        "guest_steps": 4096,
        "guest_image_digest": "b" * 64,
        "guest_source_digest": "c" * 64,
        "lease_epoch": lease_epoch,
        "lease_owner": lease_owner,
    }

def gate_context(*, packet, stage, job, lease):
    context = {
        "admission": admission(),
        "preflight": {
            "result": "VALID",
            "digest": PREFLIGHT,
            "rule_snapshot_id": RULES,
        },
        "capability": capability(),
        "ruleset_snapshot": RULES,
        "ring_incarnation": "ring-inc-1",
        "ring_epoch": 1,
        "workspace": 256,
        "expected_program_id": 79,
    }
    if stage in {"lease", "complete"}:
        context["expected_worker_owner"] = lease["lease_owner"]
    return context


class NmpHttpAdapterIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = WaveStore(root / "bs0.sqlite3", root / "mc0.sqlite3")
        self.submit_token = "submit-token-nmp-adapter-000000"
        self.worker_token = "worker-token-nmp-adapter-111111"
        self.admin_token = "admin-token-nmp-adapter-222222"
        self.service = WaveService(
            self.store, self.submit_token, self.worker_token, self.admin_token
        )
        self.adapter = NmpHttpAdapter(
            self.service,
            gate_context,
            lambda token, owner: token == self.worker_token and owner == "worker-A",
        )

    def test_native_packet_runs_queue_lease_gate_and_completion(self):
        packet = preflighted_packet()
        submitted = self.adapter.submit(
            self.submit_token, packet.to_dict(), now_tick=100
        )
        self.assertEqual(submitted["packet"]["state"], nmp.QUEUED)
        job_id = submitted["job"]["job_id"]
        self.assertEqual(submitted["job"]["kind"], "nmp")
        self.assertEqual(submitted["packet"]["evidence"]["job_id"], job_id)

        leased = self.adapter.lease(
            self.worker_token, "worker-A", now_tick=110,
            lease_ticks=64, job_id=job_id,
        )
        self.assertEqual(leased["packet"]["state"], nmp.EXECUTING)
        self.assertIn(
            "native_admission_lease",
            leased["packet"]["evidence"],
        )

        completed = self.adapter.complete(
            self.worker_token,
            leased["packet"],
            job_id=job_id,
            lease_token=leased["lease"]["token"],
            lease_epoch=leased["lease"]["epoch"],
            lease_owner="worker-A",
            result_digest="e" * 64,
            now_tick=120,
            execution_evidence=execution_evidence(
                packet, lease_epoch=leased["lease"]["epoch"],
                lease_owner="worker-A", result_digest="e" * 64,
            ),
            result_generation=8,
        )
        self.assertEqual(completed["packet"]["state"], nmp.COMPLETED)
        self.assertEqual(completed["job"]["state"], "done")
        self.assertEqual(completed["job"]["result_digest"], "e" * 64)
        native_execution = completed["packet"]["evidence"]["native_kernel_execution"]
        self.assertEqual(native_execution["program_id"], 79)
        self.assertEqual(native_execution["guest_steps"], 4096)
        self.assertEqual(native_execution["output_digest"], "e" * 64)


    def test_completion_rejects_execution_evidence_for_another_program(self):
        packet = preflighted_packet()
        submitted = self.adapter.submit(self.submit_token, packet.to_dict(), now_tick=100)
        job_id = submitted["job"]["job_id"]
        leased = self.adapter.lease(self.worker_token, "worker-A", now_tick=110,
                                    lease_ticks=64, job_id=job_id)
        evidence = execution_evidence(
            packet, lease_epoch=leased["lease"]["epoch"], lease_owner="worker-A",
            program_id=78,
        )
        with self.assertRaisesRegex(NmpHttpError, "program_id"):
            self.adapter.complete(
                self.worker_token, leased["packet"], job_id=job_id,
                lease_token=leased["lease"]["token"], lease_epoch=leased["lease"]["epoch"],
                lease_owner="worker-A", result_digest="e" * 64, now_tick=120,
                execution_evidence=evidence,
            )
        self.assertEqual(self.store.get_job(job_id)["state"], "leased")

    def test_completion_rejects_execution_output_digest_mismatch(self):
        packet = preflighted_packet()
        submitted = self.adapter.submit(self.submit_token, packet.to_dict(), now_tick=100)
        job_id = submitted["job"]["job_id"]
        leased = self.adapter.lease(self.worker_token, "worker-A", now_tick=110,
                                    lease_ticks=64, job_id=job_id)
        evidence = execution_evidence(
            packet, lease_epoch=leased["lease"]["epoch"], lease_owner="worker-A",
            result_digest="e" * 64, output_digest="f" * 64,
        )
        with self.assertRaisesRegex(NmpHttpError, "does not match result_digest"):
            self.adapter.complete(
                self.worker_token, leased["packet"], job_id=job_id,
                lease_token=leased["lease"]["token"], lease_epoch=leased["lease"]["epoch"],
                lease_owner="worker-A", result_digest="e" * 64, now_tick=120,
                execution_evidence=evidence,
            )
        self.assertEqual(self.store.get_job(job_id)["state"], "leased")

    def test_submission_rejects_guest_echoed_program_id_not_in_server_registry(self):
        packet = preflighted_packet()
        def wrong_program_context(**kwargs):
            context = gate_context(**kwargs)
            context["expected_program_id"] = 901
            return context
        adapter = NmpHttpAdapter(
            self.service, wrong_program_context,
            lambda token, owner: token == self.worker_token and owner == "worker-A",
        )
        with self.assertRaises(NmpHttpError):
            adapter.submit(self.submit_token, packet.to_dict(), now_tick=100)
        self.assertEqual(self.store.stats()["jobs"]["queued"], 0)

    def test_submission_rejects_packet_without_native_receipt(self):
        packet = make_packet(metadata={"native_admission_required": True})
        preflighted_without_receipt = replace(packet, state=nmp.PREFLIGHTED)
        with self.assertRaises(NmpHttpError):
            self.adapter.submit(
                self.submit_token, preflighted_without_receipt.to_dict(), now_tick=100
            )
        self.assertEqual(self.store.stats()["jobs"]["queued"], 0)

    def test_unbound_worker_cannot_reserve_an_nmp_lease(self):
        packet = preflighted_packet()
        submitted = self.adapter.submit(
            self.submit_token, packet.to_dict(), now_tick=100
        )
        job_id = submitted["job"]["job_id"]
        with self.assertRaises(NmpHttpError):
            self.adapter.lease(
                self.worker_token, "worker-B", now_tick=110,
                lease_ticks=64, job_id=job_id,
            )
        self.assertEqual(self.store.get_job(job_id)["state"], "queued")

    def test_nmp_lease_never_consumes_generic_wave_job(self):
        self.service.submit_job(
            self.submit_token, "generic-job", "U0", "a" * 64, 7,
            {"not": "nmp"}, 100,
        )
        self.assertIsNone(
            self.adapter.lease(self.worker_token, "worker-A", now_tick=110)
        )
        self.assertEqual(self.store.get_job("generic-job")["state"], "queued")


if __name__ == "__main__":
    unittest.main()
