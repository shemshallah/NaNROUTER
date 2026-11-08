from __future__ import annotations

from types import SimpleNamespace
import unittest

from runner_riddle.lane_work import (
    CapabilityMismatch,
    LaneWorkAdapter,
    LaneWorkBridgeAdapter,
    LaneWorkError,
    LaneWorkQueues,
    NotStealable,
    QueueFull,
    WorkConflict,
    WorkItem,
)


PREFLIGHT_LANE = 64      # lane_registry: critical preflight role
EXECUTION_LANE = 96      # lane_registry: non-critical execution role
THIEF_LANE = 200


def fake_packet(
    packet_id="nmp:1",
    lane=EXECUTION_LANE,
    *,
    snapshot="a",
    preflight="b",
    capabilities=("vector.dot",),
    epoch=1,
    fuel=10,
    priority=0,
    state="QUEUED",
    job_id=None,
    critical=None,
    tick=0,
):
    packet = SimpleNamespace(
        packet_id=packet_id,
        lane_id=lane,
        snapshot_id="snp:" + snapshot * 64,
        preflight_digest=preflight * 64,
        capability_set=tuple(
            {"required": capability} for capability in capabilities
        ),
        capability_epoch=epoch,
        fuel=fuel,
        priority=priority,
        state=state,
        job_id=job_id,
        enqueued_tick=tick,
    )
    if critical is not None:
        packet.critical = critical
    return packet


def fake_submission(packet=None, *, job_id="job:1"):
    packet = packet if packet is not None else fake_packet(job_id=job_id)
    return SimpleNamespace(packet=packet, job_id=job_id)


def fake_lease(
    packet=None,
    *,
    job_id="job:1",
    lease_id="lease:1",
    lease_epoch=1,
    token="worker-lease-token",
    owner="NANROUTER-0",
    state="EXECUTING",
    deadline_tick=64,
):
    packet = packet if packet is not None else fake_packet(
        state=state, job_id=job_id,
    )
    return SimpleNamespace(
        packet=packet,
        job_id=job_id,
        lease_id=lease_id,
        lease_epoch=lease_epoch,
        lease_token=token,
        owner=owner,
        state=state,
        deadline_tick=deadline_tick,
    )


class FakeBridge:
    """Delegation-only fake; it has no job/lease ledger of its own."""

    def __init__(self, submission=None, lease=None, result=None):
        self.submission = submission
        self.lease_record = lease
        self.result = result or SimpleNamespace(
            packet_id="nmp:1", outcome="completed", ok=True,
        )
        self.calls = []
        self.executor_calls = 0

    def submit(self, *args, **kwargs):
        self.calls.append("submit")
        return self.submission

    def submit_batch(self, *args, **kwargs):
        self.calls.append("submit_batch")
        return SimpleNamespace(children=(self.submission,))

    def lease(self, *args, **kwargs):
        self.calls.append("lease")
        return self.lease_record

    def execute(self, *args, **kwargs):
        self.calls.append("execute")
        self.executor_calls += 1
        return self.result


class LaneWorkIntegrationTests(unittest.TestCase):
    def test_submission_is_projected_without_bridge_or_executor(self):
        bridge = FakeBridge()
        adapter = LaneWorkAdapter(bridge=bridge)
        submission = fake_submission()

        item = adapter.enqueue_submission(submission)

        self.assertIsInstance(item, WorkItem)
        self.assertEqual(item.packet_id, "nmp:1")
        self.assertEqual(item.lane_id, EXECUTION_LANE)
        self.assertEqual(item.snapshot_id, "snp:" + "a" * 64)
        self.assertEqual(item.preflight_digest, "b" * 64)
        self.assertEqual(item.capability_requirement, ("vector.dot",))
        self.assertEqual(item.capability_epoch, 1)
        self.assertEqual(item.job_id, "job:1")
        self.assertEqual(item.state, "queued")
        self.assertEqual(bridge.calls, [])
        self.assertEqual(bridge.executor_calls, 0)

    def test_begin_executing_finish_transitions_and_executing_is_not_stealable(self):
        adapter = LaneWorkAdapter()
        adapter.enqueue_submission(fake_submission())

        leased = adapter.begin(
            "nmp:1",
            job_id="job:1",
            lease_id="lease:1",
            lease_epoch=2,
            lease_owner="NANROUTER-0",
            deadline_tick=32,
        )
        self.assertEqual(leased.state, "leased")
        self.assertEqual(leased.lease_epoch, 2)
        self.assertEqual(leased.deadline_tick, 32)

        executing = adapter.executing("nmp:1")
        self.assertEqual(executing.state, "executing")
        self.assertFalse(executing.stealable)
        self.assertIsNone(
            adapter.steal(
                THIEF_LANE,
                capabilities=("vector.dot",),
                capability_epoch=2,
            )
        )
        with self.assertRaises(NotStealable):
            adapter.steal_item(
                "nmp:1",
                THIEF_LANE,
                capabilities=("vector.dot",),
                capability_epoch=2,
            )

        done = adapter.finish("nmp:1", job_id="job:1", lease_epoch=2)
        self.assertEqual(done.state, "completed")
        self.assertEqual(adapter.stats()["executing"], 0)
        self.assertEqual(adapter.stats()["active_packets"], 1)

    def test_lease_identity_is_mirrored_and_never_becomes_a_second_ledger(self):
        adapter = LaneWorkAdapter()
        lease = fake_lease(
            fake_packet("nmp:2", lane=97, state="EXECUTING"),
            job_id="job:2",
            lease_id="lease:2",
            lease_epoch=4,
            token="super-secret-token",
        )

        item = adapter.enqueue_lease(lease)

        self.assertEqual(item.state, "executing")
        self.assertEqual(item.job_id, "job:2")
        self.assertEqual(item.lease_id, "lease:2")
        self.assertEqual(item.lease_epoch, 4)
        self.assertEqual(item.lease_owner, "NANROUTER-0")
        payload = item.to_dict()
        self.assertNotIn("super-secret-token", repr(payload))
        self.assertNotEqual(item.lease_token_digest, "super-secret-token")
        self.assertEqual(len(item.lease_token_digest), 64)
        # No adapter-owned job/lease/result table exists.
        self.assertFalse(hasattr(adapter, "_jobs"))
        self.assertFalse(hasattr(adapter, "_leases"))
        self.assertFalse(hasattr(adapter, "_results"))

    def test_duplicate_packet_ids_conflict_but_identical_mirror_is_idempotent(self):
        adapter = LaneWorkAdapter()
        adapter.enqueue_submission(fake_submission())
        adapter.begin(
            "nmp:1", job_id="job:1", lease_epoch=1,
            lease_token_digest="c" * 64,
        )

        with self.assertRaises(WorkConflict):
            adapter.enqueue_submission(
                fake_submission(fake_packet(priority=9, job_id="job:1"))
            )
        with self.assertRaises(WorkConflict):
            adapter.enqueue_submission(
                fake_submission(fake_packet(lane=EXECUTION_LANE + 1, job_id="job:1"))
            )
        with self.assertRaises(WorkConflict):
            adapter.enqueue_submission(
                fake_submission(
                    fake_packet(job_id="job:other"), job_id="job:other",
                )
            )

        same = adapter.enqueue_submission(fake_submission())
        self.assertEqual(same.packet_id, "nmp:1")
        self.assertEqual(adapter.stats()["active_packets"], 1)

    def test_duplicate_lease_ids_epochs_and_jobs_conflict(self):
        adapter = LaneWorkAdapter()
        packet = fake_packet("nmp:3", state="EXECUTING")
        adapter.enqueue_lease(fake_lease(packet, job_id="job:3", lease_epoch=2))

        with self.assertRaises(WorkConflict):
            adapter.enqueue_lease(
                fake_lease(
                    fake_packet("nmp:3", state="EXECUTING"),
                    job_id="job:3",
                    lease_id="lease:other",
                    lease_epoch=2,
                )
            )
        with self.assertRaises(WorkConflict):
            adapter.enqueue_lease(
                fake_lease(
                    fake_packet("nmp:3", state="EXECUTING"),
                    job_id="job:3",
                    lease_id="lease:3",
                    lease_epoch=3,
                )
            )
        with self.assertRaises(WorkConflict):
            adapter.enqueue_lease(
                fake_lease(
                    fake_packet("nmp:3", state="EXECUTING"),
                    job_id="job:other",
                    lease_id="lease:3",
                    lease_epoch=2,
                )
            )

    def test_critical_work_is_reserved_and_never_stolen(self):
        adapter = LaneWorkAdapter(capacity=2, critical_reserve=1)
        critical = fake_packet(
            "nmp:critical",
            lane=PREFLIGHT_LANE,
            capabilities=("constraint.preflight",),
            priority=0,
        )
        normal_one = fake_packet(
            "nmp:normal-1", capabilities=("math.execute",), priority=0,
        )
        normal_two = fake_packet(
            "nmp:normal-2", capabilities=("math.execute",), priority=0,
        )

        critical_item = adapter.enqueue_submission(fake_submission(critical))
        self.assertTrue(critical_item.critical)
        self.assertEqual(critical_item.role, "preflight")
        adapter.enqueue_submission(fake_submission(normal_one))
        with self.assertRaises(QueueFull):
            adapter.enqueue_submission(fake_submission(normal_two))

        self.assertIsNone(
            adapter.steal(
                THIEF_LANE,
                capabilities=("constraint.preflight",),
                capability_epoch=1,
            )
        )
        with self.assertRaises(NotStealable):
            adapter.steal_item(
                "nmp:critical",
                THIEF_LANE,
                capabilities=("constraint.preflight",),
                capability_epoch=1,
            )
        self.assertEqual(adapter.dequeue(PREFLIGHT_LANE).packet_id, "nmp:critical")

    def test_capability_and_epoch_checks_are_deterministic(self):
        adapter = LaneWorkAdapter()
        adapter.enqueue_submission(fake_submission(fake_packet(
            "nmp:dot", lane=EXECUTION_LANE,
            capabilities=("vector.dot",), epoch=1, priority=5,
        )))
        adapter.enqueue_submission(fake_submission(fake_packet(
            "nmp:add", lane=EXECUTION_LANE + 1,
            capabilities=("vector.add",), epoch=3, priority=5,
        )))

        with self.assertRaises(CapabilityMismatch):
            adapter.steal_item(
                "nmp:dot",
                THIEF_LANE,
                capabilities=("vector.add",),
                capability_epoch=3,
            )
        with self.assertRaises(CapabilityMismatch):
            adapter.steal_item(
                "nmp:add",
                THIEF_LANE,
                capabilities=("vector.add",),
                capability_epoch=2,
            )
        self.assertFalse(adapter.can_steal(
            "nmp:add",
            THIEF_LANE,
            capabilities=("vector.add",),
            capability_epoch=2,
        ))
        self.assertTrue(adapter.can_steal(
            "nmp:add",
            THIEF_LANE,
            capabilities=("vector.add",),
            capability_epoch=3,
        ))

        stolen = adapter.steal(
            THIEF_LANE,
            capabilities=("vector.add",),
            capability_epoch=3,
        )
        self.assertEqual(stolen.packet_id, "nmp:add")
        self.assertEqual(stolen.lane_id, THIEF_LANE)
        self.assertEqual(stolen.attempts, 1)
        self.assertEqual(stolen.snapshot_id, "snp:" + "a" * 64)
        self.assertEqual(stolen.preflight_digest, "b" * 64)
        self.assertEqual(stolen.capability_requirement, ("vector.add",))
        self.assertEqual(stolen.capability_epoch, 3)
        self.assertEqual(stolen.fuel, 10)

    def test_steal_selection_is_deterministic_across_lane_and_packet_id(self):
        adapter = LaneWorkAdapter()
        adapter.enqueue_submission(fake_submission(fake_packet(
            "nmp:b", lane=EXECUTION_LANE + 2, capabilities=(), tick=7,
        )))
        adapter.enqueue_submission(fake_submission(fake_packet(
            "nmp:a", lane=EXECUTION_LANE + 1, capabilities=(), tick=7,
        )))

        first = adapter.steal(THIEF_LANE, capability_epoch=1)
        second = adapter.steal(THIEF_LANE + 1, capability_epoch=1)

        self.assertEqual(first.packet_id, "nmp:a")
        self.assertEqual(second.packet_id, "nmp:b")

    def test_queue_operations_never_call_bridge_or_executor(self):
        bridge = FakeBridge()
        adapter = LaneWorkAdapter(bridge=bridge)
        adapter.enqueue_submission(fake_submission(fake_packet(
            "nmp:1", capabilities=("vector.dot",), epoch=2,
        )))
        adapter.enqueue_submission(fake_submission(fake_packet(
            "nmp:2", lane=EXECUTION_LANE + 1,
            capabilities=("vector.add",), epoch=2,
        )))
        adapter.enqueue_lease(fake_lease(
            fake_packet("nmp:3", lane=EXECUTION_LANE + 2, epoch=2),
            job_id="job:3",
        ))

        adapter.begin("nmp:1", job_id="job:1", lease_epoch=1)
        adapter.executing("nmp:1")
        adapter.can_steal(
            "nmp:2", THIEF_LANE,
            capabilities=("vector.add",), capability_epoch=2,
        )
        adapter.steal(
            THIEF_LANE,
            capabilities=("vector.add",),
            capability_epoch=2,
        )
        adapter.dequeue(THIEF_LANE)
        adapter.finish("nmp:1")
        adapter.reject("nmp:3")
        adapter.stats()

        self.assertEqual(bridge.calls, [])
        self.assertEqual(bridge.executor_calls, 0)

    def test_explicit_bridge_wrappers_delegate_once_without_owning_a_bridge(self):
        submission = fake_submission(
            fake_packet("nmp:9", state="QUEUED", job_id="job:9"),
            job_id="job:9",
        )
        lease = fake_lease(
            fake_packet("nmp:9", state="EXECUTING"),
            job_id="job:9",
        )
        result = SimpleNamespace(
            packet_id="nmp:9", outcome="completed", ok=True,
        )
        bridge = FakeBridge(submission=submission, lease=lease, result=result)
        adapter = LaneWorkBridgeAdapter(bridge=bridge)

        mirrored = adapter.submit("packet", "compiled")
        self.assertIs(mirrored, submission)
        self.assertEqual(adapter.get("nmp:9").state, "queued")

        acquired = adapter.lease(submission)
        self.assertIs(acquired, lease)
        self.assertEqual(adapter.get("nmp:9").state, "executing")

        completed = adapter.execute(lease, lambda _lease: "d" * 64)
        self.assertIs(completed, result)
        self.assertEqual(adapter.get("nmp:9").state, "completed")
        self.assertEqual(bridge.calls, ["submit", "lease", "execute"])
        self.assertEqual(bridge.executor_calls, 1)

    def test_adapter_is_optional_and_queues_remain_backward_compatible(self):
        queues = LaneWorkQueues()
        item = WorkItem(
            packet_id="nmp:legacy",
            lane_id=1,
            snapshot_id="snp:" + "e" * 64,
        )
        self.assertEqual(queues.enqueue(item).packet_id, "nmp:legacy")
        self.assertEqual(queues.dequeue(1), item)

        adapter = queues.adapter()
        self.assertIs(adapter.queues, queues)
        self.assertIsNone(adapter.bridge)
        self.assertEqual(adapter.stats()["active_packets"], 0)
        with self.assertRaises(LaneWorkError):
            adapter.submit("packet")


if __name__ == "__main__":
    unittest.main()
