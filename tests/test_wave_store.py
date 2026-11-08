import sqlite3
import tempfile
import unittest
from contextlib import closing

from runner_riddle.wave_store import (
    CapabilityConflictError, JobConflictError, LeaseError,
    NannetNodeConflictError, NannetNodeNotFoundError, OperatorConflictError,
    StaleGenerationError, WaveStore, WaveStoreError,
)


class WaveStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bs0_path = self.tmp.name + "/bs0db.sqlite3"
        self.mc0_path = self.tmp.name + "/mc0db.sqlite3"
        self.store = WaveStore(self.bs0_path, self.mc0_path)
        self.digest = "a" * 64
        self.other_digest = "b" * 64
        self.result_digest = "d" * 64
        self.signature = "c" * 64

    def enqueue(self, job_id="job-1", *, generation=7, tick=100,
                digest=None, payload=None):
        return self.store.enqueue_job(
            job_id, universe_id="universe-0", generation=generation,
            operator_digest=self.digest if digest is None else digest,
            payload={"step": 1} if payload is None else payload,
            operator_id="wave.laplacian", precision="Q16.16",
            workspace=4096, nanclock_tick=tick,
        )

    def test_enqueue_lease_and_complete(self):
        job = self.enqueue(tick=100)
        self.assertEqual(job["state"], "queued")
        self.assertEqual(job["generation"], 7)
        self.assertEqual(job["payload"], {"step": 1})

        leased = self.store.lease_job(
            owner="MC0:0/R0", now_tick=110, lease_ticks=32,
            expected_generation=7,
        )
        self.assertIsNotNone(leased)
        self.assertEqual(leased["job_id"], "job-1")
        self.assertEqual(leased["state"], "leased")
        self.assertEqual(leased["attempts"], 1)
        self.assertEqual(leased["lease_owner"], "MC0:0/R0")
        self.assertEqual(leased["lease_epoch"], 1)
        self.assertEqual(leased["deadline_tick"], 142)
        self.assertEqual(len(leased["lease_token"]), 64)

        done = self.store.complete_job(
            "job-1", lease_token=leased["lease_token"], lease_epoch=1,
            lease_owner="MC0:0/R0", result_digest=self.result_digest,
            result_generation=8, now_tick=120,
        )
        self.assertEqual(done["state"], "done")
        self.assertEqual(done["result_digest"], self.result_digest)
        self.assertEqual(done["result_generation"], 8)
        self.assertIsNone(self.store.lease_job(owner="MC0:0/R0", now_tick=121))

    def test_idempotent_job_and_completion_replay(self):
        first = self.enqueue()
        replay = self.enqueue()
        self.assertEqual(first["job_id"], replay["job_id"])
        self.assertEqual(first["created_tick"], replay["created_tick"])
        self.assertEqual(self.store.stats()["jobs"]["queued"], 1)

        leased = self.store.lease_job(owner="MC0:0/R0", now_tick=105)
        result = self.store.complete_job(
            "job-1", lease_token=leased["lease_token"], lease_epoch=1,
            result_digest=self.result_digest, result_generation=7,
            now_tick=110,
        )
        replay_result = self.store.complete_job(
            "job-1", lease_token=leased["lease_token"], lease_epoch=1,
            result_digest=self.result_digest, result_generation=7,
            now_tick=111,
        )
        self.assertEqual(result["state"], "done")
        self.assertEqual(replay_result["result_digest"], self.result_digest)
        self.assertEqual(self.store.stats()["jobs"]["done"], 1)

        replay_after_done = self.enqueue()
        self.assertEqual(replay_after_done["state"], "done")
        self.assertEqual(self.store.stats()["jobs"]["done"], 1)

        with self.assertRaises(JobConflictError):
            self.enqueue(payload={"step": 2})

    def test_stale_generation_is_rejected(self):
        self.enqueue(generation=7)
        leased = self.store.lease_job(owner="MC0:0/R0", now_tick=105)
        with self.assertRaises(StaleGenerationError):
            self.store.complete_job(
                "job-1", lease_token=leased["lease_token"], lease_epoch=1,
                result_digest=self.result_digest, result_generation=6,
                now_tick=110,
            )
        self.assertEqual(self.store.get_job("job-1")["state"], "leased")
        with self.assertRaises(StaleGenerationError):
            self.enqueue(generation=6)

    def test_lease_expiry_and_stale_worker_rejection(self):
        self.enqueue(tick=100)
        old = self.store.lease_job(owner="MC0:0/R0", now_tick=100, lease_ticks=10)
        self.assertEqual(old["deadline_tick"], 110)

        with self.assertRaises(LeaseError):
            self.store.complete_job(
                "job-1", lease_token=old["lease_token"], lease_epoch=1,
                result_digest=self.result_digest, now_tick=110,
            )
        expired = self.store.expire_leases(now_tick=110)
        self.assertEqual(expired[0]["job_id"], "job-1")
        self.assertEqual(expired[0]["state"], "queued")
        queued = self.store.get_job("job-1")
        self.assertEqual(queued["state"], "queued")
        self.assertIsNone(queued["lease_token"])

        with self.assertRaises(LeaseError):
            self.store.complete_job(
                "job-1", lease_token=old["lease_token"], lease_epoch=1,
                result_digest=self.result_digest, now_tick=111,
            )

        new = self.store.lease_job(owner="MC0:0/R1", now_tick=111, lease_ticks=10)
        self.assertEqual(new["lease_epoch"], 2)
        with self.assertRaises(LeaseError):
            self.store.complete_job(
                "job-1", lease_token=old["lease_token"], lease_epoch=1,
                result_digest=self.result_digest, now_tick=112,
            )
        done = self.store.complete_job(
            "job-1", lease_token=new["lease_token"], lease_epoch=2,
            result_digest=self.result_digest, now_tick=115,
        )
        self.assertEqual(done["state"], "done")

        self.enqueue("job-dead", tick=200)
        dead_lease = self.store.lease_job(
            owner="MC0:0/R2", now_tick=200, lease_ticks=5, max_attempts=1,
        )
        self.assertEqual(dead_lease["attempts"], 1)
        dead = self.store.expire_leases(now_tick=205, max_attempts=1)
        self.assertEqual(dead[0]["state"], "dead")
        self.assertEqual(self.store.get_job("job-dead")["state"], "dead")
        self.assertIsNone(self.store.lease_job(owner="MC0:0/R2", now_tick=206))

    def test_fail_job_requires_current_unexpired_lease(self):
        self.enqueue(tick=100)
        leased = self.store.lease_job(owner="MC0:0/R0", now_tick=100, lease_ticks=10)
        with self.assertRaises(LeaseError):
            self.store.fail_job(
                "job-1", lease_token=leased["lease_token"], lease_epoch=2,
                now_tick=105, error="bad epoch",
            )
        self.assertEqual(self.store.get_job("job-1")["state"], "leased")
        failed = self.store.fail_job(
            "job-1", lease_token=leased["lease_token"], lease_epoch=1,
            now_tick=105, error="runner rejected the operator digest",
        )
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["error"], "runner rejected the operator digest")
        replay = self.store.fail_job(
            "job-1", lease_token=leased["lease_token"], lease_epoch=1,
            now_tick=106, error="runner rejected the operator digest",
        )
        self.assertEqual(replay["state"], "failed")
        self.assertIsNone(self.store.lease_job(owner="MC0:0/R0", now_tick=107))

    def test_deterministic_lease_order(self):
        self.enqueue("job-b", tick=20)
        self.enqueue("job-a", tick=10)
        self.enqueue("job-c", tick=10)
        leased = self.store.lease_job(owner="MC0:0/R0", now_tick=100)
        self.assertEqual(leased["job_id"], "job-a")
        self.store.complete_job(
            "job-a", lease_token=leased["lease_token"], lease_epoch=1,
            result_digest=self.result_digest, now_tick=105,
        )
        leased = self.store.lease_job(owner="MC0:0/R0", now_tick=106)
        self.assertEqual(leased["job_id"], "job-c")
        self.store.complete_job(
            "job-c", lease_token=leased["lease_token"], lease_epoch=1,
            result_digest=self.result_digest, now_tick=107,
        )
        self.assertEqual(
            self.store.lease_job(owner="MC0:0/R0", now_tick=108)["job_id"],
            "job-b",
        )

    def test_operator_conflict_rejection(self):
        registered = self.store.register_operator(
            operator_id="wave.laplacian", version=1, digest=self.digest,
            shape={"heads": 255, "nan_net": 1}, precision="Q16.16",
            evidence_level="native_verified", workspace=8192,
            status="active", nanclock_tick=50,
        )
        self.assertEqual(registered["shape"], {"heads": 255, "nan_net": 1})
        replay = self.store.register_operator(
            operator_id="wave.laplacian", version=1, digest=self.digest,
            shape={"heads": 255, "nan_net": 1}, precision="Q16.16",
            evidence_level="native_verified", workspace=8192,
            status="active", nanclock_tick=51,
        )
        self.assertEqual(replay["digest"], self.digest)
        self.assertEqual(self.store.stats()["mc0"]["wave_operator"], 1)

        with self.assertRaises(OperatorConflictError):
            self.store.register_operator(
                operator_id="wave.laplacian", version=1,
                digest=self.other_digest, shape={"heads": 255, "nan_net": 1},
                precision="Q16.16", evidence_level="native_verified",
                workspace=8192, status="active",
            )
        with self.assertRaises(OperatorConflictError):
            self.store.register_operator(
                operator_id="wave.laplacian", version=2, digest=self.digest,
                shape={"heads": 255, "nan_net": 1}, precision="Q16.16",
                evidence_level="native_verified", workspace=8192,
                status="active",
            )
        with self.assertRaises(WaveStoreError):
            self.store.register_operator(
                operator_id="wave.laplacian", version=3,
                digest=self.other_digest, shape={"heads": 255, "nan_net": 1},
                precision="Q16.16", evidence_level="native_verified",
                workspace=8192, status="not-a-status",
            )

    def test_capability_dispatch_filtering(self):
        def register(runner, *, digest=None, workspace=4096,
                     status="native_verified", epoch=1, precision="Q16.16"):
            return self.store.register_capability(
                kernel_id="graph.laplacian", runner_id=runner,
                verified_digest=self.digest if digest is None else digest,
                workspace=workspace, precision=precision, status=status,
                epoch=epoch, nanclock_tick=100,
            )

        register("MC0:0/R0", workspace=4096)
        register("MC0:0/R1", workspace=2048)
        register("MC0:0/R2", workspace=8192, status="declared")
        register("MC0:0/R3", digest=self.other_digest, workspace=8192)
        register("MC0:0/R4", workspace=8192, epoch=2)
        replay = self.store.register_capability(
            kernel_id="graph.laplacian", runner_id="MC0:0/R0",
            verified_digest=self.digest, workspace=4096,
            precision="Q16.16", status="native_verified", epoch=1,
            nanclock_tick=101,
        )
        self.assertEqual(replay["epoch"], 1)

        found = self.store.dispatchable_capabilities(
            operator_digest=self.digest, workspace=4096,
        )
        self.assertEqual({item["runner_id"] for item in found},
                         {"MC0:0/R0", "MC0:0/R4"})
        found = self.store.dispatchable_capabilities(
            digest=self.digest, workspace=8192, precision="Q16.16",
        )
        self.assertEqual([item["runner_id"] for item in found], ["MC0:0/R4"])

        with self.assertRaises(CapabilityConflictError):
            register("MC0:0/R0", workspace=4096, status="degraded", epoch=1)
        promoted = register("MC0:0/R0", workspace=8192, epoch=3)
        self.assertEqual(promoted["epoch"], 3)
        with self.assertRaises(CapabilityConflictError):
            register("MC0:0/R0", workspace=8192, epoch=2)

    def test_trace_seal_signature_append_and_search(self):
        trace = self.store.append_trace(
            universe_id="universe-0", generation=1, digest=self.digest,
            producer="MC0:0/R0", nanclock_tick=10,
            signature=self.signature, payload={"step": 1}, job_id="job-1",
        )
        replay = self.store.append_trace(
            universe_id="universe-0", generation=1, digest=self.digest,
            producer="MC0:0/R0", nanclock_tick=10,
            signature=self.signature, payload={"step": 1}, job_id="job-1",
        )
        self.assertEqual(trace["trace_id"], replay["trace_id"])
        self.assertEqual(self.store.stats()["bs0"]["wave_trace"], 1)

        blob_trace = self.store.append_trace(
            universe_id="universe-0", generation=1, digest=self.other_digest,
            producer="MC0:0/R0", nanclock_tick=30,
            signature=self.signature, payload_blob=b"bounded-page",
        )
        self.assertEqual(blob_trace["payload_blob"], b"bounded-page")
        self.assertIsNone(blob_trace["payload_json"])

        seal = self.store.append_seal(
            universe_id="universe-0", generation=1, digest=self.digest,
            producer="MC0:0/R0", nanclock_tick=20,
            signature=self.signature, payload={"state_root": "root-1"},
        )
        self.assertEqual(seal["payload"], {"state_root": "root-1"})

        first = self.store.append_signature(
            universe_id="universe-0", generation=1, kind="ring", digest=self.digest,
            producer="MC0:0/R0", nanclock_tick=10,
            signature=self.signature, payload={"phase": "ring"},
        )
        newest = self.store.append_signature(
            universe_id="universe-0", generation=1, kind="ring", digest=self.other_digest,
            producer="MC0:0/R0", nanclock_tick=30,
            signature=self.signature, payload={"phase": "ring"},
        )
        self.store.append_signature(
            universe_id="universe-0", generation=1, kind="fold", digest=self.digest,
            producer="MC0:0/R1", nanclock_tick=20,
            signature=self.signature, payload={"phase": "fold"},
        )
        other_universe = self.store.append_signature(
            universe_id="universe-1", generation=1, kind="ring", digest=self.digest,
            producer="MC0:0/R0", nanclock_tick=40,
            signature=self.signature, payload={"phase": "ring"},
        )
        replay_signature = self.store.append_signature(
            universe_id="universe-0", generation=1, kind="ring", digest=self.digest,
            producer="MC0:0/R0", nanclock_tick=10,
            signature=self.signature, payload={"phase": "ring"},
        )
        self.assertEqual(first["signature_id"], replay_signature["signature_id"])
        self.assertEqual(self.store.stats()["bs0"]["wave_signature"], 4)

        ring = self.store.search_signatures(
            universe_id="universe-0", kind="ring", limit=1,
        )
        self.assertEqual([item["signature_id"] for item in ring],
                         [newest["signature_id"]])
        recent = self.store.search_signatures(universe_id="universe-0",
                                              since_tick=15)
        self.assertEqual([item["nanclock_tick"] for item in recent], [30, 20])
        self.assertEqual(
            len(self.store.search_signatures(universe_id="universe-0",
                                             generation=1)),
            3,
        )
        self.assertEqual(
            self.store.search_signatures(universe_id="universe-0",
                                         generation=2),
            [],
        )
        top = self.store.search_signatures(limit=2)
        self.assertEqual([item["signature_id"] for item in top],
                         [other_universe["signature_id"],
                          newest["signature_id"]])

    def test_stats_health_and_auxiliary_evidence(self):
        empty = self.store.stats()
        self.assertEqual(empty["schema_version"], 1)
        self.assertEqual(empty["bs0"]["schema_version"], 1)
        self.assertEqual(empty["mc0"]["schema_version"], 1)
        self.assertEqual(empty["jobs"],
                         {"queued": 0, "leased": 0, "done": 0,
                          "failed": 0, "dead": 0})
        self.assertEqual(self.store.health()["status"], "green")

        self.enqueue(tick=100)
        self.enqueue("job-2", tick=101)
        leased = self.store.lease_job(owner="MC0:0/R0", now_tick=110)
        self.store.complete_job(
            "job-1", lease_token=leased["lease_token"], lease_epoch=1,
            result_digest=self.result_digest, now_tick=115,
        )
        self.store.register_operator(
            operator_id="wave.laplacian", version=1, digest=self.digest,
            shape={"heads": 255, "nan_net": 1}, precision="Q16.16",
            evidence_level="native_verified", workspace=8192,
        )
        self.store.register_capability(
            kernel_id="graph.laplacian", runner_id="MC0:0/R0",
            verified_digest=self.digest, workspace=8192,
            precision="Q16.16", status="native_verified", epoch=1,
        )
        self.store.append_trace(
            universe_id="universe-0", generation=1, digest=self.digest,
            producer="MC0:0/R0", nanclock_tick=115,
            signature=self.signature, payload={"step": 1},
        )
        self.store.append_seal(
            universe_id="universe-0", generation=1, digest=self.digest,
            producer="MC0:0/R0", nanclock_tick=115,
            signature=self.signature, payload={"state_root": "root-1"},
        )
        self.store.append_signature(
            universe_id="universe-0", generation=1, kind="ring", digest=self.digest,
            producer="MC0:0/R0", nanclock_tick=115,
            signature=self.signature, payload={"phase": "ring"},
        )
        self.store.append_fold_certificate(
            universe_id="universe-0", generation=1,
            operator_digest=self.digest, basis_digest=self.other_digest,
            producer="MC0:0/R0", nanclock_tick=115,
            signature=self.signature, payload={"residual": 0},
        )
        self.store.index_match(
            universe_id="universe-0", kind="ring", signature_id="sig-1",
            digest=self.digest, producer="MC0:0/R0", nanclock_tick=115,
            score_q16=65535, payload={"phase": "ring"},
        )
        feedback = self.store.append_feedback(
            universe_id="universe-0", generation=1,
            candidate_digest=self.digest, producer="MC0:0/R0",
            nanclock_tick=115, signature=self.signature,
            payload={"stage": "LEARN_BOOLEAN"},
        )
        acked = self.store.ack_feedback(feedback["feedback_id"], now_tick=120)
        self.assertEqual(acked["state"], "acked")

        stats = self.store.stats()
        self.assertEqual(stats["jobs"],
                         {"queued": 1, "leased": 0, "done": 1,
                          "failed": 0, "dead": 0})
        self.assertEqual(stats["leases"]["completed"], 1)
        self.assertEqual(stats["mc0"]["wave_job"], 2)
        self.assertEqual(stats["mc0"]["wave_operator"], 1)
        self.assertEqual(stats["mc0"]["wave_capability"], 1)
        self.assertEqual(stats["mc0"]["wave_fold_certificate"], 1)
        self.assertEqual(stats["mc0"]["wave_match_index"], 1)
        self.assertEqual(stats["bs0"]["wave_trace"], 1)
        self.assertEqual(stats["bs0"]["wave_seal"], 1)
        self.assertEqual(stats["bs0"]["wave_signature"], 1)
        self.assertEqual(stats["bs0"]["wave_feedback"], 1)
        health = self.store.health()
        self.assertEqual(health["status"], "green")
        self.assertEqual(health["native_verified_capabilities"], 1)

        self.store.lease_job(owner="MC0:0/R1", now_tick=120, lease_ticks=5,
                             max_attempts=1)
        self.store.expire_leases(now_tick=125, max_attempts=1)
        self.assertEqual(self.store.stats()["jobs"]["dead"], 1)
        self.assertEqual(self.store.health()["status"], "degraded")

    def register_node(self, *, universe="universe-0", node="node-1",
                      point=17, generation=1, status="active",
                      route="nan://GM0:SC0:MC0:BS0:0:HW0:0",
                      signature=None, route_digest=None, tick=100):
        return self.store.register_nannet_node(
            universe_id=universe,
            node_id=node,
            node_point=point,
            public_key_fingerprint=self.digest,
            generation=generation,
            status=status,
            route=route,
            signature=self.signature if signature is None else signature,
            route_digest=route_digest,
            nanclock_tick=tick,
        )

    def test_nannet_node_registration_lookup_and_versioning(self):
        first = self.register_node(
            route_digest=self.other_digest, tick=10,
        )
        self.assertEqual(first["universe_id"], "universe-0")
        self.assertEqual(first["node_id"], "node-1")
        self.assertEqual(first["node_point"], 17)
        self.assertEqual(first["generation"], 1)
        self.assertEqual(first["status"], "active")
        self.assertEqual(first["signature"], self.signature)
        self.assertEqual(first["route_digest"], self.other_digest)
        self.assertEqual(first["registered_tick"], 10)
        self.assertIn("updated_tick", first)

        self.assertEqual(
            self.store.get_nannet_node("universe-0"), first
        )
        self.assertEqual(
            self.store.get_nannet_node_by_node_id("node-1"), first
        )
        self.assertEqual(
            self.store.require_nannet_node("universe-0"), first
        )

        replay = self.register_node(
            route_digest=self.other_digest, tick=11,
        )
        self.assertEqual(replay["generation"], 1)
        self.assertEqual(replay["updated_tick"], 10)
        self.assertEqual(len(self.store.nannet_node_history("universe-0")), 1)

        second = self.register_node(
            generation=2, status="degraded", route="nan://GM0:SC0:MC0:BS0:1:HW0:0",
            signature=self.other_digest, tick=20,
        )
        self.assertEqual(second["generation"], 2)
        self.assertEqual(second["status"], "degraded")
        self.assertEqual(second["signature"], self.other_digest)
        self.assertEqual(second["registered_tick"], 10)
        self.assertEqual(second["updated_tick"], 20)
        self.assertEqual(self.store.get_nannet_node("universe-0"), second)

        version_one = self.store.get_nannet_node("universe-0", generation=1)
        self.assertEqual(version_one["status"], "active")
        self.assertEqual(version_one["signature"], self.signature)
        self.assertEqual(version_one["nanclock_tick"], 10)
        history = self.store.nannet_node_history("universe-0")
        self.assertEqual([row["generation"] for row in history], [2, 1])

        with self.assertRaises(NannetNodeConflictError):
            self.register_node(generation=1, tick=30)
        with self.assertRaises(NannetNodeConflictError):
            self.register_node(
                generation=2, status="active", tick=30,
            )
        self.assertEqual(
            self.store.get_nannet_node("universe-0")["generation"], 2
        )

    def test_nannet_node_revoke_frees_node_and_point(self):
        self.register_node(tick=10)
        revoked = self.store.revoke_nannet_node(
            "universe-0", generation=2, signature=self.other_digest,
            route_digest=self.digest, nanclock_tick=20,
        )
        self.assertEqual(revoked["status"], "revoked")
        self.assertEqual(revoked["route"], "")
        self.assertEqual(revoked["generation"], 2)
        with self.assertRaises(NannetNodeConflictError):
            self.store.revoke_nannet_node("universe-0", generation=2,
                                          nanclock_tick=21)
        with self.assertRaises(NannetNodeConflictError):
            self.register_node(generation=1, tick=21)

        rebound = self.register_node(
            universe="universe-1", generation=1, tick=30,
        )
        self.assertEqual(rebound["node_id"], "node-1")
        self.assertEqual(rebound["node_point"], 17)
        self.assertEqual(
            self.store.get_nannet_node("universe-0")["status"], "revoked"
        )
        self.assertEqual(
            self.store.get_nannet_node("universe-1")["status"], "active"
        )
        third = self.register_node(
            universe="universe-2", node="node-2", point=18,
            generation=1, tick=31,
        )
        self.assertEqual(third["status"], "active")
        self.assertEqual(len(self.store.list_nannet_nodes()), 3)
        self.assertEqual(
            len(self.store.list_nannet_nodes(status="revoked")), 1
        )

    def test_nannet_node_unknown_and_validation(self):
        self.assertIsNone(self.store.get_nannet_node("missing"))
        self.assertIsNone(
            self.store.get_nannet_node("missing", generation=3)
        )
        self.assertIsNone(
            self.store.get_nannet_node_by_node_id("missing")
        )
        self.assertEqual(
            self.store.nannet_node_history("missing"), []
        )
        with self.assertRaises(NannetNodeNotFoundError):
            self.store.require_nannet_node("missing")
        with self.assertRaises(NannetNodeNotFoundError):
            self.store.require_nannet_node("missing", generation=2)

        invalid = (
            {"node_point": 0},
            {"node_point": 256},
            {"public_key_fingerprint": "short"},
            {"status": "unknown"},
            {"status": "revoked", "route": "nan://still-routed"},
            {"generation": -1},
            {"signature": "not-a-digest"},
            {"route_digest": "not-a-digest"},
        )
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs):
                args = {
                    "universe_id": "u-invalid",
                    "node_id": "n-invalid",
                    "node_point": 33,
                    "public_key_fingerprint": self.digest,
                    "generation": 1,
                    "status": "active",
                    "route": "nan://route",
                    "nanclock_tick": 1,
                }
                args.update(kwargs)
                with self.assertRaises(WaveStoreError):
                    self.store.register_nannet_node(**args)

        self.register_node(universe="u1", node="n1", point=1, tick=1)
        with self.assertRaises(NannetNodeConflictError):
            self.register_node(universe="u2", node="n1", point=2, tick=2)
        with self.assertRaises(NannetNodeConflictError):
            self.register_node(universe="u2", node="n2", point=1, tick=3)

    def test_nannet_node_persistence_is_not_a_routing_or_lease_authority(self):
        self.register_node(tick=10)
        stats = self.store.stats()
        self.assertEqual(stats["mc0"]["wave_nannet_node"], 1)
        self.assertEqual(stats["mc0"]["wave_nannet_node_version"], 1)
        self.assertEqual(stats["jobs"], {
            "queued": 0, "leased": 0, "done": 0, "failed": 0, "dead": 0,
        })
        self.assertEqual(stats["leases"], {
            "active": 0, "expired": 0, "completed": 0, "failed": 0,
        })
        self.assertIsNone(
            self.store.lease_job(owner="MC0:0/R0", now_tick=11)
        )
        self.assertEqual(
            self.store.dispatchable_capabilities(
                operator_digest=self.digest, workspace=0
            ),
            [],
        )

    def test_nannet_node_stores_no_secret_material(self):
        with self.assertRaises(TypeError):
            self.store.register_nannet_node(
                universe_id="u1", node_id="n1", node_point=1,
                public_key_fingerprint=self.digest,
                secret_key="do-not-store-this",
            )
        self.register_node(universe="u1", node="n1", point=1, tick=1)
        with closing(sqlite3.connect(self.mc0_path)) as db:
            columns = {
                row[1] for row in db.execute(
                    "PRAGMA table_info(wave_nannet_node)"
                )
            }
            version_columns = {
                row[1] for row in db.execute(
                    "PRAGMA table_info(wave_nannet_node_version)"
                )
            }
            current = db.execute(
                "SELECT * FROM wave_nannet_node"
            ).fetchone()
        forbidden = {"secret", "secret_key", "private_key", "token",
                     "raw_token", "password"}
        self.assertFalse(columns & forbidden)
        self.assertFalse(version_columns & forbidden)
        self.assertNotIn("do-not-store-this", str(current))
        self.assertIn("public_key_fingerprint", columns)
        self.assertIn("signature", columns)
        self.assertIn("route_digest", columns)

    def test_required_control_and_evidence_tables_exist(self):
        expected = {
            self.mc0_path: {
                "wave_job", "wave_lease", "wave_operator", "wave_capability",
                "wave_nannet_node", "wave_nannet_node_version",
                "wave_fold_certificate", "wave_match_index", "wave_schema",
            },
            self.bs0_path: {
                "wave_trace", "wave_seal", "wave_signature", "wave_feedback",
                "wave_schema",
            },
        }
        for path, tables in expected.items():
            with closing(sqlite3.connect(path)) as db:
                found = {
                    row[0] for row in db.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
            self.assertTrue(tables.issubset(found), tables - found)

    def test_schema_versions_are_recorded_and_mismatches_rejected(self):
        for path, store in ((self.bs0_path, "BS0DB"),
                            (self.mc0_path, "MC0DB")):
            with closing(sqlite3.connect(path)) as db:
                row = db.execute(
                    "SELECT version FROM wave_schema WHERE store=?", (store,)
                ).fetchone()
                user_version = db.execute("PRAGMA user_version").fetchone()[0]
            self.assertEqual(row[0], 1)
            self.assertEqual(user_version, 1)

        with closing(sqlite3.connect(self.mc0_path)) as db:
            db.execute(
                "UPDATE wave_schema SET version=99 WHERE store='MC0DB'"
            )
            db.commit()
        with self.assertRaises(WaveStoreError):
            WaveStore(self.bs0_path, self.mc0_path)


if __name__ == "__main__":
    unittest.main()
