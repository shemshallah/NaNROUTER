from __future__ import annotations

import unittest

from runner_riddle.lane_work import (
    LaneWorkError,
    LaneWorkQueues,
    NotStealable,
    QueueFull,
    WorkConflict,
    WorkItem,
)


def item(packet="nmp:1", lane=1, *, priority=0, capabilities=(), epoch=0,
         role="execution", critical=False, tick=0):
    return WorkItem(
        packet_id=packet,
        lane_id=lane,
        snapshot_id="snp:" + "a" * 64,
        preflight_digest="b" * 64,
        capability_requirement=capabilities,
        capability_epoch=epoch,
        priority=priority,
        role=role,
        critical=critical,
        enqueued_tick=tick,
    )


class LaneWorkTests(unittest.TestCase):
    def test_enqueue_is_bounded_and_keeps_critical_reserve(self):
        queues = LaneWorkQueues(capacity=2, critical_reserve=1)
        queues.enqueue(item("nmp:1", lane=1))
        with self.assertRaises(QueueFull):
            queues.enqueue(item("nmp:2", lane=1))
        queues.enqueue(item("nmp:3", lane=1, critical=True, role="control"))
        self.assertEqual(queues.dequeue(1).packet_id, "nmp:3")

    def test_nannet0_and_duplicate_conflicts_are_rejected(self):
        queues = LaneWorkQueues()
        with self.assertRaises(LaneWorkError):
            queues.enqueue(item("bad", lane=255))
        queues.enqueue(item("nmp:1", lane=1, priority=2))
        with self.assertRaises(WorkConflict):
            queues.enqueue(item("nmp:1", lane=1, priority=3))
        self.assertEqual(queues.enqueue(item("nmp:1", lane=1, priority=2)).packet_id, "nmp:1")

    def test_priority_and_age_determine_dequeue_order(self):
        queues = LaneWorkQueues()
        queues.enqueue(item("old", lane=2, priority=0, tick=1))
        queues.enqueue(item("high", lane=2, priority=9, tick=5))
        queues.enqueue(item("new", lane=2, priority=0, tick=2))
        self.assertEqual(queues.dequeue(2).packet_id, "high")
        self.assertEqual(queues.dequeue(2).packet_id, "old")
        self.assertEqual(queues.dequeue(2).packet_id, "new")

    def test_steal_moves_only_queued_capability_compatible_work(self):
        queues = LaneWorkQueues()
        queues.enqueue(item("nmp:1", lane=1, capabilities=("vector.dot",)))
        queues.enqueue(item("nmp:2", lane=2, capabilities=("vector.add",)))
        stolen = queues.steal(
            7, capabilities=("vector.add",), capability_epoch=1,
        )
        self.assertEqual(stolen.packet_id, "nmp:2")
        self.assertEqual(stolen.lane_id, 7)
        self.assertEqual(queues.get("nmp:2").attempts, 1)

    def test_executing_packets_and_critical_work_are_never_stolen(self):
        queues = LaneWorkQueues()
        queues.enqueue(item("nmp:1", lane=1))
        queues.begin("nmp:1", job_id="job-1")
        queues.executing("nmp:1")
        self.assertIsNone(queues.steal(2, capabilities=("vector.dot",)))
        with self.assertRaises(NotStealable):
            queues.begin("nmp:1")

        queues.enqueue(item("nmp:2", lane=2, critical=True, role="control"))
        self.assertIsNone(queues.steal(3))

    def test_stale_capability_epoch_is_not_stolen(self):
        queues = LaneWorkQueues()
        queues.enqueue(item("nmp:1", lane=1, epoch=3))
        self.assertIsNone(
            queues.steal(2, capabilities=(), capability_epoch=2)
        )
        self.assertIsNotNone(
            queues.steal(2, capabilities=(), capability_epoch=3)
        )

    def test_terminal_work_leaves_the_active_queue(self):
        queues = LaneWorkQueues()
        queues.enqueue(item("nmp:1", lane=1))
        queues.begin("nmp:1")
        queues.executing("nmp:1")
        done = queues.finish("nmp:1")
        self.assertEqual(done.state, "completed")
        self.assertEqual(queues.stats()["executing"], 0)
        self.assertNotIn("1", queues.stats()["nonempty_lanes"])

    def test_stats_never_claim_more_than_one_active_runner(self):
        queues = LaneWorkQueues()
        for index in range(5):
            queues.enqueue(item(f"nmp:{index}", lane=index + 1))
        stats = queues.stats()
        self.assertEqual(stats["executing"], 0)
        self.assertEqual(stats["active_packets"], 5)
        self.assertNotIn("255", stats["nonempty_lanes"])

    def test_explicit_critical_flag_is_never_stolen(self):
        queues = LaneWorkQueues()
        queues.enqueue(item("nmp:1", lane=1, critical=True))
        self.assertIsNone(
            queues.steal(2, capabilities=("vector.dot",), capability_epoch=0)
        )
        with self.assertRaises(NotStealable):
            queues.steal_item("nmp:1", 2)

    def test_can_steal_is_side_effect_free_and_finish_accepts_failure_alias(self):
        queues = LaneWorkQueues()
        queues.enqueue(item("nmp:1", lane=1, capabilities=("vector.dot",)))
        self.assertTrue(
            queues.can_steal(
                "nmp:1", 2, capabilities=("vector.dot",), capability_epoch=0,
            )
        )
        self.assertEqual(queues.get("nmp:1").lane_id, 1)
        stolen = queues.steal_item(
            "nmp:1", 2, capabilities=("vector.dot",), capability_epoch=0,
        )
        self.assertEqual(stolen.lane_id, 2)
        queues.begin("nmp:1")
        self.assertEqual(queues.finish("nmp:1", state="failed").state, "rejected")


if __name__ == "__main__":
    unittest.main()
