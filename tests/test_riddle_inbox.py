import hashlib
import tempfile
import unittest

from runner_riddle import InboxError, RunnerRiddleWorker, SQLiteSourceInbox


ACL = "b" * 64


class InboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.inbox = SQLiteSourceInbox(self.tmp.name + "/riddle.sqlite")

    def enqueue(self):
        payload = b"NaN16DE source stream: bit/head mapping"
        event_id = self.inbox.enqueue(
            universe_id="training-universe-0", node_point=9, head_index=17,
            source_kind="nan-source", payload=payload, acl_digest=ACL,
            nanclock_tick=5,
        )
        return event_id, hashlib.sha256(payload).hexdigest()

    def test_idempotent_enqueue_and_worker_ack(self):
        event_id, source_hash = self.enqueue()
        duplicate, _ = self.enqueue()
        self.assertEqual(event_id, duplicate)
        self.assertEqual(self.inbox.stats()["queued"], 1)

        def learn(event):
            self.assertEqual(event.source_hash, source_hash)
            return {
                "schema": "nanrouter.trace.v1",
                "universe_id": event.universe_id,
                "node_point": event.node_point,
                "layer": 0,
                "step": 1,
                "nanclock_tick": 6,
                "source_hash": event.source_hash,
                "source_ref": f"point:{event.node_point}:head:{event.head_index}",
                "target_ref": "vector:1337",
                "input_hash": "a" * 64,
                "output_hash": "c" * 64,
                "active_heads": [event.head_index],
                "confidence_q16": 50000,
                "correct": True,
                "delta_digest": "d" * 64,
                "base_generation": 0,
                "acl_digest": event.acl_digest,
                "learner_id": "riddle-worker-0",
            }

        worker = RunnerRiddleWorker(self.inbox, learn, "worker-0")
        self.assertTrue(worker.run_once(now_tick=10, base_generation=0))
        self.assertEqual(self.inbox.stats()["acked"], 1)
        self.assertFalse(worker.run_once(now_tick=11, base_generation=0))

    def test_expired_lease_can_be_recovered(self):
        self.enqueue()
        first = self.inbox.lease_next(owner="worker-a", now_tick=10, lease_ticks=4)
        self.assertEqual(first.attempts, 1)
        second = self.inbox.lease_next(owner="worker-b", now_tick=14, lease_ticks=4)
        self.assertEqual(second.attempts, 2)
        self.assertEqual(second.lease_owner, "worker-b")

    def test_ack_requires_matching_owner_and_source_provenance(self):
        self.enqueue()
        event = self.inbox.lease_next(owner="worker-a", now_tick=10)
        trace = {"source_hash": "0" * 64, "acl_digest": ACL}
        with self.assertRaises(InboxError):
            self.inbox.ack(event, result_digest="e" * 64,
                           result_generation=0, trace=trace)

    def test_payload_and_acl_bounds(self):
        with self.assertRaises(InboxError):
            self.inbox.enqueue(
                universe_id="u", node_point=0, head_index=0,
                source_kind="nan", payload=b"", acl_digest=ACL, nanclock_tick=0
            )
        with self.assertRaises(InboxError):
            self.inbox.enqueue(
                universe_id="u", node_point=0, head_index=0,
                source_kind="nan", payload=b"x", acl_digest="bad", nanclock_tick=0
            )


if __name__ == "__main__":
    unittest.main()
