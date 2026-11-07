import unittest

from runner_riddle.point0_bridge import (
    BinaryEnvelope,
    BinaryEnvelopeError,
    FrameError,
    NanFrame,
    Point0Bridge,
    Point0BridgeError,
    Point0Router,
    POINT_ZERO_ADDRESS,
)
from runner_riddle.wave_ring_scheduler import WaveRingScheduler


class Point0BridgeTests(unittest.TestCase):
    def setUp(self):
        self.bridge = Point0Bridge()

    def test_exact_word_roundtrip(self):
        frame = NanFrame((0, 1, 0xFFFFFFFFFFFFFFFF, 0x0123456789ABCDEF), 42)
        envelope = self.bridge.encode(frame, active_slot=0, epoch=1)
        self.assertEqual(self.bridge.decode(envelope), frame)

    def test_empty_and_large_frames(self):
        for count in (0, 1, 65536):
            frame = NanFrame(tuple(range(count)), count + 1)
            envelope = self.bridge.encode(frame, active_slot=0, epoch=1)
            self.assertEqual(len(self.bridge.decode(envelope).words), count)

    def test_binary_envelope_wire_roundtrip(self):
        frame = NanFrame((7, 8, 9), 7)
        envelope = self.bridge.encode(frame, active_slot=2, epoch=3)
        raw = envelope.to_bytes()
        parsed = BinaryEnvelope.from_bytes(raw)
        self.assertEqual(parsed.request_id, 7)
        self.assertEqual(parsed.active_slot, 2)
        self.assertEqual(self.bridge.decode(parsed), frame)

    def test_corrupt_binary_envelope_rejected(self):
        frame = NanFrame((1, 2, 3), 9)
        raw = bytearray(self.bridge.encode(frame, active_slot=0, epoch=1).to_bytes())
        raw[0] ^= 0xFF
        with self.assertRaises(BinaryEnvelopeError):
            BinaryEnvelope.from_bytes(bytes(raw))

    def test_public_route_is_point_zero(self):
        frame = NanFrame((1,), 1)
        self.assertEqual(frame.route, POINT_ZERO_ADDRESS)
        with self.assertRaises(Point0BridgeError):
            NanFrame((1,), 1, route="MC0:0/R2")

    def test_invalid_words_rejected(self):
        with self.assertRaises(FrameError):
            NanFrame((1 << 64,), 1)
        with self.assertRaises(FrameError):
            NanFrame((-1,), 1)

    def test_router_uses_active_slot(self):
        scheduler = WaveRingScheduler(now_tick=0)
        scheduler.start(0)
        calls = []

        def executor(slot_id, epoch, payload):
            calls.append((slot_id, epoch, payload))
            return (7).to_bytes(8, "big")

        router = Point0Router(self.bridge, scheduler, executor)
        result = router.submit(NanFrame((1, 2, 3), 11))
        self.assertEqual(calls[0][0], 0)
        self.assertEqual(calls[0][1], 1)
        self.assertEqual(result.words, (7,))
        self.assertEqual(result.active_slot, 0)
        self.assertEqual(router.route, POINT_ZERO_ADDRESS)

    def test_router_follows_cycle(self):
        scheduler = WaveRingScheduler(now_tick=0)
        scheduler.start(0)
        scheduler.heartbeat(1)
        scheduler.cycle(2)
        calls = []

        def executor(slot_id, epoch, payload):
            calls.append((slot_id, epoch))
            return b""

        router = Point0Router(self.bridge, scheduler, executor)
        result = router.submit(NanFrame((), 12))
        self.assertEqual(calls[0][0], 1)
        self.assertEqual(result.active_slot, 1)
        self.assertEqual(result.epoch, 2)

    def test_no_active_slot_rejected(self):
        scheduler = WaveRingScheduler(now_tick=0)
        router = Point0Router(self.bridge, scheduler, lambda *_: b"")
        with self.assertRaises(Point0BridgeError):
            router.submit(NanFrame((1,), 1))

    def test_bad_executor_result_rejected(self):
        scheduler = WaveRingScheduler(now_tick=0)
        scheduler.start(0)
        router = Point0Router(self.bridge, scheduler, lambda *_: b"bad")
        with self.assertRaises(Point0BridgeError):
            router.submit(NanFrame((1,), 1))


if __name__ == "__main__":
    unittest.main()
