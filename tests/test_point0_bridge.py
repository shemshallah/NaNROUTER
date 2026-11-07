import hashlib
import inspect
import struct
import unittest
from dataclasses import replace
from unittest import mock

from runner_riddle.address import parse_address
from runner_riddle.point0_bridge import (
    BinaryEnvelope,
    EnvelopeFormatError,
    ExecutorResultError,
    FrameError,
    FrameTooLargeError,
    InactiveSlotError,
    MAGIC,
    MAX_FRAME_WORDS,
    MAX_PAYLOAD_BYTES,
    NanFrame,
    NoActiveSlotError,
    POINT_ZERO_ADDRESS,
    POINT_ZERO_LABEL,
    POINT_ZERO_WIRE,
    Point0Bridge,
    Point0BridgeError,
    Point0Result,
    Point0Router,
    RouterBusyError,
    StaleEnvelopeError,
    VERSION,
    WORD_BYTES,
    WIRE_ENDIAN,
)
from runner_riddle.wave_ring_scheduler import WaveRingScheduler


UINT64_MAX = (1 << 64) - 1


def sample_words(count):
    return tuple(
        (index * 0x9E3779B97F4A7C15 + 0x0123456789ABCDEF) & UINT64_MAX
        for index in range(count)
    )


def make_scheduler(**kwargs):
    kwargs.setdefault("cycle_ticks", 10)
    return WaveRingScheduler(now_tick=0, **kwargs)


class RecordingExecutor:
    def __init__(self, transform=None):
        self.calls = []
        self.transform = transform

    def __call__(self, active_slot, epoch, binary_payload):
        self.calls.append((active_slot, epoch, binary_payload))
        if self.transform is not None:
            return self.transform(binary_payload)
        return binary_payload


class PointZeroIdentityTests(unittest.TestCase):
    def test_point_zero_constants_are_stable_and_parseable(self):
        self.assertEqual(POINT_ZERO_ADDRESS, "nan://GM0:SC0:MC0:BS0:0:HW0:0")
        self.assertEqual(POINT_ZERO_WIRE, "BSR0")
        self.assertEqual(POINT_ZERO_LABEL, "point-0")
        self.assertEqual(parse_address(POINT_ZERO_ADDRESS).root, POINT_ZERO_ADDRESS)

    def test_point_zero_route_is_canonical_for_wire_and_address_forms(self):
        for route in (None, "", POINT_ZERO_ADDRESS, POINT_ZERO_WIRE):
            with self.subTest(route=route):
                frame = NanFrame(words=(1,), request_id=1, route=route)
                self.assertEqual(frame.route, POINT_ZERO_ADDRESS)
                self.assertEqual(frame.address, POINT_ZERO_ADDRESS)

    def test_direct_runner_slot_routes_are_rejected(self):
        for route in (
            "MC0:0/R0",
            "MC0:0/R5",
            "NANROUTER-0",
            "NANROUTER-5",
            "nan://GM1:SC0:MC0:BS0:0:HW0:0",
            "nan://GM0:SC0:MC0:BS0:1:HW0:0",
        ):
            with self.subTest(route=route):
                with self.assertRaises(FrameError):
                    NanFrame(words=(), request_id=1, route=route)

    def test_nan_frame_preserves_uint64_words_and_metadata(self):
        words = (0, 1, UINT64_MAX)
        frame = NanFrame(
            words=list(words),
            request_id=UINT64_MAX,
            provenance={"source": "test", "attempt": 2},
        )
        self.assertEqual(frame.words, words)
        self.assertEqual(frame.request_id, UINT64_MAX)
        self.assertEqual(frame.word_count, 3)
        self.assertEqual(frame.metadata, {"source": "test", "attempt": "2"})

    def test_nan_frame_rejects_non_uint64_values(self):
        for words in ((-1,), (UINT64_MAX + 1,), (1.5,), (True,)):
            with self.subTest(words=words):
                with self.assertRaises(Point0BridgeError):
                    NanFrame(words=words, request_id=1)
        for request_id in (-1, UINT64_MAX + 1, True, 1.5):
            with self.subTest(request_id=request_id):
                with self.assertRaises(FrameError):
                    NanFrame(words=(), request_id=request_id)


class Point0BridgeRoundTripTests(unittest.TestCase):
    def setUp(self):
        self.bridge = Point0Bridge()

    def test_exact_word_roundtrip_across_required_lengths(self):
        for word_count in (0, 1, 2, 255, 256, 4096, 65535, MAX_FRAME_WORDS):
            with self.subTest(word_count=word_count):
                words = sample_words(word_count)
                frame = NanFrame(words=words, request_id=word_count + 7)
                envelope = self.bridge.encode(frame, active_slot=3, epoch=9)
                self.assertEqual(envelope.length, word_count * WORD_BYTES)
                self.assertEqual(envelope.active_slot, 3)
                self.assertEqual(envelope.epoch, 9)
                decoded = self.bridge.decode(envelope)
                self.assertEqual(decoded.words, words)
                self.assertEqual(decoded.request_id, frame.request_id)
                self.assertEqual(decoded.route, POINT_ZERO_ADDRESS)

    def test_boundary_lengths_and_oversized_frames_are_rejected(self):
        at_limit = NanFrame(words=sample_words(MAX_FRAME_WORDS), request_id=1)
        envelope = self.bridge.encode(at_limit)
        self.assertEqual(envelope.length, MAX_PAYLOAD_BYTES)
        self.assertEqual(len(self.bridge.decode(envelope).words), MAX_FRAME_WORDS)

        over_limit = NanFrame(words=sample_words(MAX_FRAME_WORDS + 1), request_id=1)
        with self.assertRaises(FrameTooLargeError):
            self.bridge.encode(over_limit)

        empty = NanFrame((), 0)
        small = Point0Bridge(max_words=2)
        self.assertEqual(small.decode(small.encode(empty)).words, ())
        self.assertEqual(len(small.decode(small.encode(NanFrame((1, 2), 2))).words), 2)
        with self.assertRaises(FrameTooLargeError):
            small.encode(NanFrame((1, 2, 3), 3))

    def test_word_endianness_is_explicit_big_endian(self):
        word = 0x0102030405060708
        envelope = self.bridge.encode(
            NanFrame((word,), 0x1122334455667788),
            active_slot=5,
            epoch=0x0102030405060708,
        )
        self.assertEqual(WIRE_ENDIAN, "big")
        self.assertEqual(envelope.payload, bytes.fromhex("0102030405060708"))
        wire = envelope.to_bytes()
        self.assertEqual(wire[0:4], MAGIC)
        self.assertEqual(wire[4], VERSION)
        self.assertEqual(wire[5], 5)
        self.assertEqual(wire[6:14], bytes.fromhex("1122334455667788"))
        self.assertEqual(wire[14:22], bytes.fromhex("0102030405060708"))
        self.assertEqual(wire[22:26], struct.pack(">I", 8))
        self.assertEqual(wire[26:58], envelope.digest)
        self.assertEqual(wire[58:], bytes.fromhex("0102030405060708"))
        self.assertEqual(self.bridge.decode(wire).words, (word,))

    def test_request_id_zero_and_maximum_are_preserved(self):
        for request_id in (0, 1, UINT64_MAX):
            with self.subTest(request_id=request_id):
                frame = NanFrame((UINT64_MAX,), request_id)
                decoded = self.bridge.decode(self.bridge.encode(frame))
                self.assertEqual(decoded.request_id, request_id)

    def test_decode_accepts_wire_bytes_and_reports_metadata(self):
        frame = NanFrame((1, 2, 3), 77)
        envelope = self.bridge.encode(frame, active_slot=4, epoch=12)
        decoded = self.bridge.decode(envelope.to_bytes())
        self.assertEqual(decoded.words, frame.words)
        self.assertEqual(decoded.request_id, 77)
        self.assertEqual(decoded.route, POINT_ZERO_ADDRESS)
        self.assertEqual(decoded.metadata["wire"], POINT_ZERO_WIRE)
        self.assertEqual(decoded.metadata["active_slot"], "4")
        self.assertEqual(decoded.metadata["epoch"], "12")

    def test_digest_binds_header_and_payload(self):
        envelope = self.bridge.encode(NanFrame((1,), 9), active_slot=2, epoch=3)
        expected = hashlib.sha256(
            struct.pack(
                ">4sBBQQI",
                envelope.magic,
                envelope.version,
                envelope.active_slot,
                envelope.request_id,
                envelope.epoch,
                envelope.length,
            )
            + envelope.payload
        ).digest()
        self.assertEqual(envelope.digest, expected)
        self.assertEqual(len(envelope.digest), 32)


class BinaryEnvelopeValidationTests(unittest.TestCase):
    def setUp(self):
        self.bridge = Point0Bridge()
        self.envelope = self.bridge.encode(
            NanFrame((0, UINT64_MAX), 123), active_slot=1, epoch=4
        )

    def assert_decode_rejected(self, envelope, error=Point0BridgeError):
        with self.assertRaises(error):
            self.bridge.decode(envelope)
        with self.assertRaises(error):
            BinaryEnvelope.from_bytes(envelope.to_bytes())

    def test_bad_magic_is_rejected(self):
        self.assert_decode_rejected(
            replace(self.envelope, magic=b"BAD!"), EnvelopeFormatError
        )

    def test_bad_version_is_rejected(self):
        self.assert_decode_rejected(
            replace(self.envelope, version=VERSION + 1), EnvelopeFormatError
        )

    def test_bad_digest_is_rejected(self):
        self.assert_decode_rejected(
            replace(self.envelope, digest=b"\x00" * 32), EnvelopeFormatError
        )

    def test_bad_length_is_rejected(self):
        for length in (
            self.envelope.length + WORD_BYTES,
            max(0, self.envelope.length - WORD_BYTES),
            1,
            MAX_PAYLOAD_BYTES + WORD_BYTES,
        ):
            with self.subTest(length=length):
                self.assert_decode_rejected(
                    replace(self.envelope, length=length), Point0BridgeError
                )

    def test_payload_length_must_match_and_be_whole_words(self):
        with self.assertRaises(EnvelopeFormatError):
            self.bridge.decode(
                replace(self.envelope, payload=self.envelope.payload[:-1])
            )
        with self.assertRaises(EnvelopeFormatError):
            self.bridge.decode(
                replace(
                    self.envelope,
                    payload=self.envelope.payload + b"\x00",
                    length=self.envelope.length + 1,
                )
            )
        with self.assertRaises(EnvelopeFormatError):
            BinaryEnvelope.create(
                request_id=1, payload=b"\x00", active_slot=0, epoch=1
            )

    def test_truncated_and_trailing_wire_data_is_rejected(self):
        wire = self.envelope.to_bytes()
        for value in (b"", wire[:10], wire[:-1], wire + b"\x00"):
            with self.subTest(size=len(value)):
                with self.assertRaises(EnvelopeFormatError):
                    BinaryEnvelope.from_bytes(value)

    def test_expected_slot_epoch_and_request_id_are_enforced(self):
        with self.assertRaises(InactiveSlotError):
            self.bridge.decode(self.envelope, expected_active_slot=0)
        with self.assertRaises(StaleEnvelopeError):
            self.bridge.decode(self.envelope, expected_epoch=5)
        with self.assertRaises(EnvelopeFormatError):
            self.bridge.decode(self.envelope, expected_request_id=124)

    def test_create_rejects_bad_slot_epoch_and_payload_size(self):
        for slot in (-1, 6, True, 1.5):
            with self.subTest(slot=slot):
                with self.assertRaises(Point0BridgeError):
                    BinaryEnvelope.create(
                        request_id=1, payload=b"", active_slot=slot, epoch=1
                    )
        for epoch in (-1, UINT64_MAX + 1, True):
            with self.subTest(epoch=epoch):
                with self.assertRaises(Point0BridgeError):
                    BinaryEnvelope.create(
                        request_id=1, payload=b"", active_slot=0, epoch=epoch
                    )
        with self.assertRaises(FrameTooLargeError):
            BinaryEnvelope.create(
                request_id=1,
                payload=b"\x00" * (MAX_PAYLOAD_BYTES + WORD_BYTES),
                active_slot=0,
                epoch=1,
            )

    def test_wire_roundtrip_is_exact(self):
        self.assertEqual(BinaryEnvelope.from_bytes(self.envelope.to_bytes()), self.envelope)


class Point0RouterTests(unittest.TestCase):
    def make_router(self, scheduler=None, executor=None, bridge=None):
        if scheduler is None:
            scheduler = make_scheduler()
        if executor is None:
            executor = RecordingExecutor()
        if bridge is None:
            router = Point0Router(scheduler, executor)
        else:
            router = Point0Router(bridge, scheduler, executor)
        return router, scheduler, executor

    def test_no_active_slot_is_rejected_without_calling_executor(self):
        scheduler = make_scheduler()
        executor = RecordingExecutor()
        router, _, _ = self.make_router(scheduler, executor)
        with self.assertRaises(NoActiveSlotError):
            router.submit(NanFrame((1,), 1))
        self.assertEqual(executor.calls, [])

    def test_oversized_frame_is_rejected_before_scheduler_or_executor(self):
        scheduler = make_scheduler()
        executor = RecordingExecutor()
        router, _, _ = self.make_router(scheduler, executor)
        frame = NanFrame(sample_words(MAX_FRAME_WORDS + 1), 1)
        with self.assertRaises(FrameTooLargeError):
            router.submit(frame)
        self.assertEqual(executor.calls, [])

    def test_route_uses_the_one_active_slot_and_preserves_request_id(self):
        scheduler = make_scheduler()
        scheduler.start(0)
        executor = RecordingExecutor()
        router, _, _ = self.make_router(scheduler, executor)
        frame = NanFrame((1, 2, 3), 42, route=POINT_ZERO_WIRE)

        result = router.submit(frame)

        expected_payload = Point0Bridge().encode(
            frame, active_slot=0, epoch=1
        ).payload
        self.assertEqual(executor.calls, [(0, 1, expected_payload)])
        self.assertIsInstance(result, Point0Result)
        self.assertEqual(result.words, frame.words)
        self.assertEqual(result.request_id, 42)
        self.assertEqual(result.route, POINT_ZERO_ADDRESS)
        self.assertEqual(result.active_slot, 0)
        self.assertEqual(result.slot, 0)
        self.assertEqual(result.epoch, 1)
        self.assertNotIn("/R", result.route)
        self.assertNotIn("NANROUTER", result.route)
        self.assertEqual(result.to_dict()["route"], POINT_ZERO_ADDRESS)
        self.assertEqual(result.to_dict()["active_slot"], 0)

    def test_after_cycle_same_point_zero_address_reaches_new_active_slot(self):
        scheduler = make_scheduler()
        scheduler.start(0)
        executor = RecordingExecutor()
        router, _, _ = self.make_router(scheduler, executor)
        frame = NanFrame((7, 8), 99)

        first = router.submit(frame)
        self.assertEqual((first.active_slot, first.epoch), (0, 1))
        scheduler.cycle(1)
        second = router.submit(frame)

        self.assertEqual((second.active_slot, second.epoch), (1, 2))
        self.assertEqual(first.route, second.route)
        self.assertEqual(second.route, POINT_ZERO_ADDRESS)
        self.assertEqual(
            [(slot, epoch) for slot, epoch, _ in executor.calls],
            [(0, 1), (1, 2)],
        )
        self.assertEqual([call[0] for call in executor.calls].count(0), 1)

    def test_dispatch_rejects_stale_epoch_before_executor(self):
        scheduler = make_scheduler()
        scheduler.start(0)
        executor = RecordingExecutor()
        router, _, _ = self.make_router(scheduler, executor)
        frame = NanFrame((1,), 1)
        stale = Point0Bridge().encode(frame, active_slot=0, epoch=1)

        scheduler.cycle(2)
        with self.assertRaises(StaleEnvelopeError):
            router.dispatch(stale)
        self.assertEqual(executor.calls, [])

        fresh = Point0Bridge().encode(frame, active_slot=1, epoch=2)
        result = router.dispatch(fresh.to_bytes())
        self.assertEqual((result.active_slot, result.epoch), (1, 2))
        self.assertEqual(
            [(slot, epoch) for slot, epoch, _ in executor.calls], [(1, 2)]
        )

    def test_dispatch_rejects_inactive_slot_before_executor(self):
        scheduler = make_scheduler()
        scheduler.start(0)
        executor = RecordingExecutor()
        router, _, _ = self.make_router(scheduler, executor)
        frame = NanFrame((1,), 1)
        wrong_slot = Point0Bridge().encode(frame, active_slot=3, epoch=1)

        with self.assertRaises(InactiveSlotError):
            router.dispatch(wrong_slot)
        self.assertEqual(executor.calls, [])

    def test_submit_does_not_call_executor_when_encode_advances_scheduler(self):
        scheduler = make_scheduler()
        scheduler.start(0)
        executor = RecordingExecutor()

        class CyclingBridge(Point0Bridge):
            def encode(self, frame, *, active_slot=0, epoch=0):
                envelope = super().encode(
                    frame, active_slot=active_slot, epoch=epoch
                )
                scheduler.cycle(1)
                return envelope

        router = Point0Router(CyclingBridge(), scheduler, executor)
        with self.assertRaises(StaleEnvelopeError):
            router.submit(NanFrame((1,), 1))
        self.assertEqual(executor.calls, [])

    def test_missing_or_duplicate_active_slot_is_rejected_before_executor(self):
        scheduler = make_scheduler()
        scheduler.start(0)
        executor = RecordingExecutor()
        router, _, _ = self.make_router(scheduler, executor)
        snapshot = scheduler.snapshot()

        no_active = dict(snapshot)
        no_active["slots"] = [
            dict(slot, status="standby") for slot in snapshot["slots"]
        ]
        with mock.patch.object(scheduler, "snapshot", return_value=no_active):
            with self.assertRaises(NoActiveSlotError):
                router.submit(NanFrame((1,), 1))

        duplicate = dict(snapshot)
        duplicate["active_count"] = 2
        with mock.patch.object(scheduler, "snapshot", return_value=duplicate):
            with self.assertRaises(NoActiveSlotError):
                router.submit(NanFrame((1,), 1))

        stale = dict(snapshot)
        stale["stale"] = True
        with mock.patch.object(scheduler, "snapshot", return_value=stale):
            with self.assertRaises(StaleEnvelopeError):
                router.submit(NanFrame((1,), 1))

        self.assertEqual(executor.calls, [])

    def test_executor_result_is_decoded_and_validated(self):
        scheduler = make_scheduler()
        scheduler.start(0)

        def swap_first_two_words(payload):
            return payload[8:16] + payload[0:8] + payload[16:]

        executor = RecordingExecutor(swap_first_two_words)
        router, _, _ = self.make_router(scheduler, executor)
        result = router.submit(NanFrame((10, 20, 30), 5))
        self.assertEqual(result.words, (20, 10, 30))
        self.assertEqual(result.request_id, 5)

    def test_bad_executor_results_are_rejected_and_router_recovers(self):
        scheduler = make_scheduler()
        scheduler.start(0)
        failures = [
            (lambda payload: "not-bytes", ExecutorResultError),
            (lambda payload: payload + b"\x00", ExecutorResultError),
            (
                lambda payload: b"\x00" * (MAX_PAYLOAD_BYTES + WORD_BYTES),
                FrameTooLargeError,
            ),
        ]
        for transform, error in failures:
            with self.subTest(error=error):
                executor = RecordingExecutor(transform)
                router, _, _ = self.make_router(scheduler, executor)
                with self.assertRaises(error):
                    router.submit(NanFrame((1,), 1))
                self.assertEqual(len(executor.calls), 1)

                good = RecordingExecutor()
                recover, _, _ = self.make_router(scheduler, good)
                self.assertEqual(recover.submit(NanFrame((1,), 1)).words, (1,))
                self.assertEqual(len(good.calls), 1)

    def test_executor_exception_propagates_and_router_recovers(self):
        scheduler = make_scheduler()
        scheduler.start(0)
        calls = []

        def exploding(slot, epoch, payload):
            calls.append((slot, epoch))
            raise RuntimeError("runner lost")

        router = Point0Router(scheduler, exploding)
        with self.assertRaises(RuntimeError):
            router.submit(NanFrame((1,), 1))

        executor = RecordingExecutor()
        router._executor = executor
        result = router.submit(NanFrame((2,), 2))
        self.assertEqual(result.words, (2,))
        self.assertEqual(calls, [(0, 1)])
        self.assertEqual(
            [(slot, epoch) for slot, epoch, _ in executor.calls], [(0, 1)]
        )

    def test_submit_never_accepts_a_caller_supplied_slot(self):
        parameters = list(inspect.signature(Point0Router.submit).parameters)
        self.assertEqual(parameters, ["self", "frame"])
        for method in ("submit", "dispatch"):
            self.assertTrue(hasattr(Point0Router, method))

    def test_router_constructor_requires_a_bridge_scheduler_and_executor(self):
        scheduler = make_scheduler()
        executor = RecordingExecutor()
        router = Point0Router(Point0Bridge(), scheduler, executor)
        self.assertIs(router.scheduler, scheduler)
        router = Point0Router(scheduler, executor)
        self.assertIs(router.scheduler, scheduler)
        with self.assertRaises(TypeError):
            Point0Router(Point0Bridge(), scheduler, None)
        with self.assertRaises(TypeError):
            Point0Router(Point0Bridge(), None, executor)

    def test_public_result_does_not_leak_slot_into_route(self):
        scheduler = make_scheduler()
        scheduler.start(0)
        router, _, _ = self.make_router(scheduler, RecordingExecutor())
        result = router.submit(NanFrame((1,), 1))
        evidence = result.to_dict()
        self.assertEqual(evidence["route"], POINT_ZERO_ADDRESS)
        self.assertEqual(evidence["wire"], POINT_ZERO_WIRE)
        self.assertEqual(evidence["active_slot"], 0)
        self.assertEqual(evidence["epoch"], 1)
        self.assertNotIn("MC0:0/R", evidence["route"])
        self.assertNotIn("NANROUTER", evidence["route"])

    def test_router_busy_guard_rejects_nested_dispatch(self):
        scheduler = make_scheduler()
        scheduler.start(0)
        router = None

        def nesting(slot, epoch, payload):
            with self.assertRaises(RouterBusyError):
                router.submit(NanFrame((2,), 2))
            return payload

        router = Point0Router(scheduler, nesting)
        result = router.submit(NanFrame((1,), 1))
        self.assertEqual(result.words, (1,))
        self.assertEqual((result.active_slot, result.epoch), (0, 1))


if __name__ == "__main__":
    unittest.main()
