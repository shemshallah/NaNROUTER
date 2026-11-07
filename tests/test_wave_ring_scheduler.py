import json
import unittest

from runner_riddle.wave_ring_scheduler import (
    DEFAULT_MAX_ACTIVE_MEMORY_BYTES,
    MC0_SLOTS,
    NANROUTER_ALIASES,
    RING_SLOTS,
    SLOT_ALIASES,
    SLOT_COUNT,
    RingBusyError,
    RingCapacityError,
    RingCheckpointError,
    RingStateError,
    WaveRingScheduler,
    WaveRingSchedulerError,
    resolve_slot,
)


class WaveRingSchedulerTests(unittest.TestCase):
    def make(self, **kwargs):
        kwargs.setdefault("cycle_ticks", 10)
        return WaveRingScheduler(now_tick=0, **kwargs)

    def assert_one_active(self, snapshot):
        self.assertEqual(
            [slot["index"] for slot in snapshot["slots"] if slot["status"] == "active"],
            [snapshot["active_slot"]],
        )
        self.assertEqual(snapshot["active_count"], 1)

    def test_six_slots_and_aliases_are_the_same_six_slots(self):
        self.assertEqual(SLOT_COUNT, 6)
        self.assertEqual(RING_SLOTS, MC0_SLOTS)
        self.assertEqual(
            MC0_SLOTS,
            tuple(f"MC0:0/R{i}" for i in range(6)),
        )
        self.assertEqual(
            NANROUTER_ALIASES,
            tuple(f"NANROUTER-{i}" for i in range(6)),
        )
        self.assertEqual(len(set(MC0_SLOTS)), 6)
        self.assertEqual(len(SLOT_ALIASES), 12)
        for index in range(6):
            self.assertEqual(resolve_slot(index), index)
            self.assertEqual(resolve_slot(MC0_SLOTS[index]), index)
            self.assertEqual(resolve_slot(NANROUTER_ALIASES[index]), index)

    def test_invalid_slot_labels_are_rejected(self):
        for value in (-1, 6, "MC0:0/R6", "NANROUTER-6", "R0", None, True):
            with self.subTest(value=value):
                with self.assertRaises(WaveRingSchedulerError):
                    resolve_slot(value)
        for value in (True, 1.5, None):
            with self.subTest(value=value):
                with self.assertRaises(WaveRingSchedulerError):
                    resolve_slot(value)

    def test_start_activates_exactly_one_slot(self):
        scheduler = self.make()
        snapshot = scheduler.start(0)
        self.assertEqual(snapshot["epoch"], 1)
        self.assertEqual(snapshot["active_slot"], 0)
        self.assertEqual(snapshot["active_slot_id"], "MC0:0/R0")
        self.assertEqual(snapshot["active_alias"], "NANROUTER-0")
        self.assertEqual(snapshot["health"], "green")
        self.assert_one_active(snapshot)
        for slot in snapshot["slots"][1:]:
            self.assertEqual(slot["status"], "standby")
            self.assertEqual(slot["memory_reserved_bytes"], 0)
            self.assertEqual(slot["lease_count"], 0)
            self.assertIsNone(slot["heartbeat_tick"])

    def test_start_can_skip_a_revoked_first_slot(self):
        scheduler = self.make()
        scheduler.revoke_slot("NANROUTER-0")
        snapshot = scheduler.start(0)
        self.assertEqual(snapshot["active_slot"], 1)
        self.assertEqual(snapshot["slots"][0]["status"], "revoked")
        self.assert_one_active(snapshot)

    def test_cannot_start_twice(self):
        scheduler = self.make()
        scheduler.start(0)
        with self.assertRaises(RingStateError):
            scheduler.start(1)

    def test_constructor_validation(self):
        with self.assertRaises(WaveRingSchedulerError):
            WaveRingScheduler(cycle_ticks=0)
        with self.assertRaises(WaveRingSchedulerError):
            WaveRingScheduler(cycle_ticks=True)
        with self.assertRaises(WaveRingSchedulerError):
            WaveRingScheduler(max_active_memory_bytes=0)
        with self.assertRaises(WaveRingSchedulerError):
            WaveRingScheduler(now_tick=-1)
        with self.assertRaises(WaveRingSchedulerError):
            WaveRingScheduler(checkpoint_store="not-callable")

    def test_default_ceiling_is_seven_gib(self):
        self.assertEqual(DEFAULT_MAX_ACTIVE_MEMORY_BYTES, 7 * 1024 ** 3)
        scheduler = self.make()
        self.assertEqual(scheduler.max_active_memory_bytes, 7 * 1024 ** 3)

    def test_reserve_memory_enforces_hard_ceiling(self):
        scheduler = self.make(max_active_memory_bytes=100)
        scheduler.start(0)
        scheduler.reserve_memory(60)
        with self.assertRaises(RingCapacityError):
            scheduler.reserve_memory(41)
        snapshot = scheduler.snapshot()
        self.assertEqual(snapshot["active_memory_bytes"], 60)
        scheduler.reserve_memory(40)
        snapshot = scheduler.snapshot()
        self.assertEqual(snapshot["active_memory_bytes"], 100)

    def test_release_memory_cannot_underflow(self):
        scheduler = self.make(max_active_memory_bytes=100)
        scheduler.start(0)
        scheduler.reserve_memory(40)
        with self.assertRaises(RingStateError):
            scheduler.release_memory(41)
        snapshot = scheduler.release_memory(40)
        self.assertEqual(snapshot["active_memory_bytes"], 0)

    def test_memory_amounts_are_validated(self):
        scheduler = self.make()
        scheduler.start(0)
        for value in (-1, True, 1.5, "1"):
            with self.subTest(value=value):
                with self.assertRaises(WaveRingSchedulerError):
                    scheduler.reserve_memory(value)
        with self.assertRaises(WaveRingSchedulerError):
            scheduler.release_memory(-1)

    def test_lease_registration_and_release(self):
        scheduler = self.make()
        scheduler.start(0)
        snapshot = scheduler.register_lease()
        self.assertEqual(snapshot["active_lease_count"], 1)
        snapshot = scheduler.register_lease(2)
        self.assertEqual(snapshot["active_lease_count"], 3)
        with self.assertRaises(RingStateError):
            scheduler.release_lease(4)
        snapshot = scheduler.release_lease(3)
        self.assertEqual(snapshot["active_lease_count"], 0)
        for value in (0, -1, True):
            with self.subTest(value=value):
                with self.assertRaises(WaveRingSchedulerError):
                    scheduler.register_lease(value)

    def test_cannot_cycle_with_live_leases(self):
        scheduler = self.make()
        scheduler.start(0)
        scheduler.register_lease()
        with self.assertRaises(RingBusyError):
            scheduler.cycle(1)
        snapshot = scheduler.snapshot()
        self.assertEqual(snapshot["active_slot"], 0)
        self.assertEqual(snapshot["epoch"], 1)
        self.assertEqual(snapshot["slots"][0]["status"], "draining")
        with self.assertRaises(RingStateError):
            scheduler.register_lease()
        scheduler.release_lease()
        snapshot = scheduler.cycle(2)
        self.assertEqual(snapshot["active_slot"], 1)
        self.assertEqual(snapshot["epoch"], 2)
        self.assertEqual(snapshot["slots"][0]["status"], "standby")
        self.assertEqual(snapshot["slots"][0]["lease_count"], 0)
        self.assert_one_active(snapshot)

    def test_cannot_cycle_with_active_memory(self):
        scheduler = self.make()
        scheduler.start(0)
        scheduler.reserve_memory(1024)
        with self.assertRaises(RingBusyError):
            scheduler.cycle(1)
        snapshot = scheduler.snapshot()
        self.assertEqual(snapshot["active_slot"], 0)
        self.assertEqual(snapshot["epoch"], 1)
        self.assertEqual(snapshot["active_memory_bytes"], 1024)
        scheduler.release_memory(1024)
        snapshot = scheduler.cycle(2)
        self.assertEqual(snapshot["active_slot"], 1)
        self.assertEqual(snapshot["epoch"], 2)
        self.assertEqual(snapshot["active_memory_bytes"], 0)

    def test_successful_cycle_checkpoints_and_empties_old_slot(self):
        saved = []
        scheduler = self.make(checkpoint_store=saved.append)
        scheduler.start(0)
        snapshot = scheduler.cycle(1)
        self.assertEqual(len(saved), 1)
        self.assertEqual(len(saved[0]), 64)
        self.assertEqual(saved[0], snapshot["last_checkpoint"]["digest"])
        self.assertEqual(
            snapshot["slots"][0]["checkpoint_digest"],
            snapshot["last_checkpoint"]["digest"],
        )
        self.assertEqual(snapshot["slots"][0]["status"], "standby")
        self.assertEqual(snapshot["slots"][0]["memory_reserved_bytes"], 0)
        self.assertEqual(snapshot["slots"][0]["lease_count"], 0)
        self.assertIsNone(snapshot["slots"][0]["heartbeat_tick"])
        self.assertEqual(snapshot["active_slot"], 1)
        self.assertEqual(snapshot["epoch"], 2)
        self.assertEqual(snapshot["health"], "green")
        self.assert_one_active(snapshot)

    def test_standby_slots_hold_no_working_set(self):
        scheduler = self.make()
        scheduler.start(0)
        scheduler.reserve_memory(2048)
        scheduler.register_lease()
        scheduler.release_memory(2048)
        scheduler.release_lease()
        snapshot = scheduler.cycle(1)
        for slot in snapshot["slots"]:
            if slot["status"] != "active":
                self.assertEqual(slot["memory_reserved_bytes"], 0)
                self.assertEqual(slot["lease_count"], 0)

    def test_six_slots_cycle_and_epoch_is_monotonic(self):
        scheduler = self.make()
        scheduler.start(0)
        active = []
        epochs = []
        for tick in range(1, 7):
            snapshot = scheduler.cycle(tick)
            active.append(snapshot["active_slot"])
            epochs.append(snapshot["epoch"])
            self.assert_one_active(snapshot)
        self.assertEqual(active, [1, 2, 3, 4, 5, 0])
        self.assertEqual(epochs, [2, 3, 4, 5, 6, 7])
        self.assertEqual(snapshot["slots"][0]["status"], "active")

    def test_revoked_slots_are_skipped_and_can_be_restored(self):
        scheduler = self.make()
        scheduler.revoke_slot("NANROUTER-2")
        scheduler.start(0)
        snapshot = scheduler.cycle(1)
        self.assertEqual(snapshot["active_slot"], 1)
        snapshot = scheduler.cycle(2)
        self.assertEqual(snapshot["active_slot"], 3)
        self.assertEqual(snapshot["slots"][2]["status"], "revoked")
        scheduler.restore_slot("MC0:0/R2")
        self.assertEqual(scheduler.snapshot()["slots"][2]["status"], "standby")

    def test_active_slot_cannot_be_revoked(self):
        scheduler = self.make()
        scheduler.start(0)
        with self.assertRaises(RingStateError):
            scheduler.revoke_slot(0)
        with self.assertRaises(RingStateError):
            scheduler.restore_slot(1)

    def test_heartbeat_and_stale_detection(self):
        scheduler = self.make(cycle_ticks=10)
        scheduler.start(100)
        scheduler.heartbeat(105)
        self.assertFalse(scheduler.is_stale(115))
        self.assertFalse(scheduler.snapshot(115)["stale"])
        self.assertTrue(scheduler.is_stale(116))
        self.assertTrue(scheduler.snapshot(116)["stale"])
        self.assertEqual(scheduler.snapshot(116)["health"], "stale")
        self.assertEqual(scheduler.stale_slots(116), (0,))
        fresh = scheduler.heartbeat(116)
        self.assertFalse(fresh["stale"])
        self.assertEqual(fresh["health"], "green")

    def test_heartbeat_tick_cannot_move_backwards(self):
        scheduler = self.make()
        scheduler.start(10)
        with self.assertRaises(WaveRingSchedulerError):
            scheduler.heartbeat(9)
        with self.assertRaises(WaveRingSchedulerError):
            scheduler.cycle(9)
        with self.assertRaises(WaveRingSchedulerError):
            scheduler.force_failover(9, "bad clock")

    def test_force_failover_requires_released_resources(self):
        scheduler = self.make()
        scheduler.start(0)
        scheduler.reserve_memory(10)
        scheduler.register_lease()
        with self.assertRaises(RingBusyError):
            scheduler.force_failover(1, "stale heartbeat")
        snapshot = scheduler.snapshot()
        self.assertEqual(snapshot["active_slot"], 0)
        self.assertEqual(snapshot["epoch"], 1)
        self.assertEqual(snapshot["slots"][0]["status"], "draining")
        scheduler.release_memory(10)
        scheduler.release_lease()
        snapshot = scheduler.force_failover(2, "stale heartbeat")
        self.assertEqual(snapshot["active_slot"], 1)
        self.assertEqual(snapshot["epoch"], 2)
        self.assertEqual(snapshot["slots"][0]["status"], "degraded")
        self.assertEqual(snapshot["last_failover_reason"], "stale heartbeat")
        self.assertEqual(snapshot["last_failover_tick"], 2)
        self.assert_one_active(snapshot)

    def test_force_failover_checkpoints_old_slot(self):
        saved = []
        scheduler = self.make(checkpoint_store=saved.append)
        scheduler.start(0)
        snapshot = scheduler.force_failover(1, "runner lost")
        self.assertEqual(saved, [snapshot["last_checkpoint"]["digest"]])
        self.assertEqual(
            snapshot["slots"][0]["checkpoint_digest"],
            snapshot["last_checkpoint"]["digest"],
        )
        self.assertEqual(snapshot["slots"][0]["lease_count"], 0)
        self.assertEqual(snapshot["slots"][0]["memory_reserved_bytes"], 0)

    def test_force_failover_requires_a_reason(self):
        scheduler = self.make()
        scheduler.start(0)
        for reason in ("", "   ", None, 7, "bad\nreason", "x" * 257):
            with self.subTest(reason=reason):
                with self.assertRaises(WaveRingSchedulerError):
                    scheduler.force_failover(1, reason)
        self.assertEqual(scheduler.snapshot()["active_slot"], 0)

    def test_checkpoint_failure_does_not_advance_activation(self):
        state = {"fail": True}
        saved = []

        def store(digest):
            if state["fail"]:
                raise RuntimeError("checkpoint medium unavailable")
            saved.append(digest)

        scheduler = self.make(checkpoint_store=store)
        scheduler.start(0)
        with self.assertRaises(RingCheckpointError):
            scheduler.cycle(1)
        snapshot = scheduler.snapshot()
        self.assertEqual(snapshot["active_slot"], 0)
        self.assertEqual(snapshot["epoch"], 1)
        self.assertEqual(snapshot["slots"][0]["status"], "degraded")
        self.assertIsNone(snapshot["slots"][0]["checkpoint_digest"])
        self.assertIsNone(snapshot["last_checkpoint"])
        state["fail"] = False
        snapshot = scheduler.cycle(2)
        self.assertEqual(snapshot["active_slot"], 1)
        self.assertEqual(snapshot["epoch"], 2)
        self.assertEqual(len(saved), 1)
        self.assertEqual(snapshot["slots"][0]["status"], "standby")

    def test_operations_before_start_are_rejected(self):
        scheduler = self.make()
        for operation in (
            lambda: scheduler.reserve_memory(1),
            lambda: scheduler.release_memory(0),
            scheduler.register_lease,
            scheduler.release_lease,
            scheduler.heartbeat,
            scheduler.cycle,
            lambda: scheduler.force_failover(0, "not started"),
        ):
            with self.subTest(operation=operation):
                with self.assertRaises(RingStateError):
                    operation()
        self.assertFalse(scheduler.snapshot()["started"])
        self.assertEqual(scheduler.snapshot()["health"], "idle")

    def test_snapshot_is_detached_plain_data_and_has_no_callback(self):
        class SecretStore:
            def __init__(self):
                self.secret = "do-not-leak"

            def __call__(self, digest):
                return digest

        store = SecretStore()
        scheduler = self.make(checkpoint_store=store)
        scheduler.start(0)
        scheduler.register_lease()
        snapshot = scheduler.snapshot(5)
        self.assertNotIn("do-not-leak", json.dumps(snapshot))
        self.assertNotIn("SecretStore", json.dumps(snapshot))
        snapshot["slots"][0]["status"] = "revoked"
        snapshot["last_checkpoint"] = {"tampered": True}
        fresh = scheduler.snapshot()
        self.assertEqual(fresh["slots"][0]["status"], "active")
        self.assertIsNone(fresh["last_checkpoint"])

    def test_cycle_requires_an_eligible_next_slot(self):
        scheduler = self.make()
        scheduler.start(0)
        for slot in range(1, 6):
            scheduler.revoke_slot(slot)
        with self.assertRaises(RingStateError):
            scheduler.cycle(1)
        snapshot = scheduler.snapshot()
        self.assertEqual(snapshot["active_slot"], 0)
        self.assertEqual(snapshot["epoch"], 1)


if __name__ == "__main__":
    unittest.main()
