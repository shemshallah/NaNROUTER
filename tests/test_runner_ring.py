import tempfile
import unittest

from runner_riddle.ring import RING_SLOTS, RunnerRing, RunnerRingError


class RunnerRingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ring = RunnerRing(self.tmp.name + "/ring.sqlite3", stale_after_ticks=10)
        self.digest = "a" * 64

    def test_six_slots_converge_on_one_registry_generation(self):
        for slot, runner_id in enumerate(RING_SLOTS):
            snapshot = self.ring.heartbeat(
                slot=slot, runner_id=runner_id, registry_generation=3,
                registry_digest=self.digest, nanclock_tick=100 + slot,
                expected_generation=3, expected_digest=self.digest,
            )
        self.assertEqual(snapshot["health"], "green")
        self.assertEqual(snapshot["in_sync"], 6)

    def test_missing_runner_keeps_ring_degraded(self):
        snapshot = self.ring.heartbeat(
            slot=0, runner_id=RING_SLOTS[0], registry_generation=3,
            registry_digest=self.digest, nanclock_tick=100,
            expected_generation=3, expected_digest=self.digest,
        )
        self.assertEqual(snapshot["health"], "degraded")
        self.assertEqual(snapshot["slots"][1]["state"], "waiting")

    def test_runner_must_ack_current_registry(self):
        with self.assertRaises(RunnerRingError):
            self.ring.heartbeat(
                slot=0, runner_id=RING_SLOTS[0], registry_generation=2,
                registry_digest=self.digest, nanclock_tick=100,
                expected_generation=3, expected_digest=self.digest,
            )

    def test_runner_identity_is_bound_to_slot(self):
        with self.assertRaises(RunnerRingError):
            self.ring.heartbeat(
                slot=0, runner_id=RING_SLOTS[1], registry_generation=3,
                registry_digest=self.digest, nanclock_tick=100,
                expected_generation=3, expected_digest=self.digest,
            )

    def test_stale_runner_is_not_green(self):
        self.ring.heartbeat(
            slot=0, runner_id=RING_SLOTS[0], registry_generation=3,
            registry_digest=self.digest, nanclock_tick=100,
            expected_generation=3, expected_digest=self.digest,
        )
        snapshot = self.ring.snapshot(
            expected_generation=3, expected_digest=self.digest, now_tick=111,
        )
        self.assertEqual(snapshot["slots"][0]["state"], "stale")
        self.assertEqual(snapshot["health"], "degraded")

    def test_runner_cannot_move_nanclock_backwards(self):
        self.ring.heartbeat(
            slot=0, runner_id=RING_SLOTS[0], registry_generation=3,
            registry_digest=self.digest, nanclock_tick=100,
            expected_generation=3, expected_digest=self.digest,
        )
        with self.assertRaises(RunnerRingError):
            self.ring.heartbeat(
                slot=0, runner_id=RING_SLOTS[0], registry_generation=3,
                registry_digest=self.digest, nanclock_tick=99,
                expected_generation=3, expected_digest=self.digest,
            )


if __name__ == "__main__":
    unittest.main()
