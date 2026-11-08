import tempfile
import unittest
from pathlib import Path

from runner_riddle.point_fabric import (
    CentralPointFabric,
    FabricCapacityError,
    FabricFrameError,
    FabricRoutingError,
    Nan16DEWord,
    PointFrame,
    PointTranslationModule,
    frame_from_json,
    frames_to_json,
)

ACL = "a" * 64
WORD = Nan16DEWord.make(0x7FF1, 0xFFF8, 0x12345678)


def frame(source=5, destination=2, request_id=1, tick=7, kind="vector"):
    return PointFrame(
        request_id=request_id,
        source_hw=source,
        destination_hw=destination,
        nanclock_tick=tick,
        kind=kind,
        acl_digest=ACL,
        word=WORD,
    )


class Nan16DEWordTests(unittest.TestCase):
    def test_round_trip_preserves_exact_byte_order(self):
        raw = bytes.fromhex("7ff178563412f8ff")
        word = Nan16DEWord.parse(raw)
        self.assertEqual(word.far, 0x7FF1)
        self.assertEqual(word.payload, 0x12345678)
        self.assertEqual(word.near, 0xFFF8)
        self.assertEqual(word.pack(), raw)

    def test_rejects_illegal_heads_and_payload(self):
        for raw in (
            bytes.fromhex("0000000000000000"),
            bytes.fromhex("7ff1000000000000"),
            bytes.fromhex("7ff1000000007ff1")[:7],
        ):
            with self.subTest(raw=raw), self.assertRaises(FabricFrameError):
                Nan16DEWord.parse(raw)
        with self.assertRaises(FabricFrameError):
            Nan16DEWord.make(0x7FF1, 0x7FF8, 1 << 32)


class PointFrameTests(unittest.TestCase):
    def test_frame_round_trip_and_digest(self):
        original = frame()
        encoded = original.encode()
        decoded = PointFrame.decode(encoded)
        self.assertEqual(decoded, original)
        self.assertEqual(decoded.frame_id, original.frame_id)
        self.assertEqual(decoded.word.pack(), WORD.pack())

    def test_frame_tamper_is_rejected(self):
        encoded = bytearray(frame().encode())
        encoded[24] ^= 1
        with self.assertRaises(FabricFrameError):
            PointFrame.decode(encoded)
        with self.assertRaises(FabricFrameError):
            PointFrame.decode(encoded[:-1])
        with self.assertRaises(FabricFrameError):
            PointFrame.decode(b"XXXX" + bytes(encoded[4:]))

    def test_frame_bounds(self):
        with self.assertRaises(FabricFrameError):
            frame(source=256)
        with self.assertRaises(FabricFrameError):
            frame(destination=-1)
        with self.assertRaises(FabricFrameError):
            frame(kind="")
        with self.assertRaises(FabricFrameError):
            frame(kind="bad kind")
        with self.assertRaises(FabricFrameError):
            PointFrame(
                request_id=1, source_hw=5, destination_hw=2,
                nanclock_tick=0, kind="vector", acl_digest="A" * 64,
                word=WORD,
            )

    def test_json_frame_adapter(self):
        parsed = frame_from_json({
            "request_id": 3,
            "source_hw": 5,
            "destination_hw": 2,
            "nanclock_tick": 9,
            "kind": "hermes.nan",
            "acl_digest": ACL,
            "word_hex": WORD.pack().hex(),
        })
        self.assertEqual(parsed.request_id, 3)
        self.assertEqual(parsed.word.pack(), WORD.pack())
        rendered = frames_to_json((parsed,))
        self.assertEqual(rendered[0]["frame_hex"], parsed.encode().hex())
        with self.assertRaises(FabricFrameError):
            frame_from_json({"word_hex": "00"})


class PointTranslationModuleTests(unittest.TestCase):
    def test_accept_and_drain(self):
        module = PointTranslationModule(2, "hermes-hardware-node", "active", inbox_limit=2)
        receipt = module.accept(frame())
        self.assertEqual(receipt["queued"], 1)
        self.assertEqual(module.monitor()["received"], 1)
        frames = module.drain(1)
        self.assertEqual(frames, (frame(),))
        self.assertEqual(module.drain(1), ())
        self.assertEqual(module.monitor()["delivered"], 1)

    def test_capacity_and_wrong_destination(self):
        module = PointTranslationModule(2, "hermes-hardware-node", "active", inbox_limit=1)
        module.accept(frame())
        with self.assertRaises(FabricCapacityError):
            module.accept(frame(request_id=2))
        with self.assertRaises(FabricRoutingError):
            module.accept(frame(destination=3))

    def test_inactive_module_rejects(self):
        module = PointTranslationModule(2, "hermes-hardware-node", "paired-device-only")
        with self.assertRaises(FabricRoutingError):
            module.accept(frame())


class CentralPointFabricTests(unittest.TestCase):
    def setUp(self):
        self.fabric = CentralPointFabric()

    def tearDown(self):
        self.fabric.close()

    def test_hw5_to_hermes_hw2_delivery(self):
        self.fabric.register(5)
        self.fabric.register(2, status="active")
        receipt = self.fabric.intake(frame(source=5, destination=2))
        self.assertEqual(receipt["status"], "queued")
        self.assertEqual(receipt["central_status"], "delivered")
        drained = self.fabric.drain(2, 1)
        self.assertEqual(drained[0].source_hw, 5)
        self.assertEqual(drained[0].destination_hw, 2)

    def test_hermes_outbound_to_network_port_hw0(self):
        self.fabric.register(2, status="active")
        receipt = self.fabric.intake(frame(source=2, destination=0, kind="hermes.out"))
        self.assertEqual(receipt["central_status"], "delivered")
        drained = self.fabric.drain(0, 1)
        self.assertEqual(drained[0].destination_hw, 0)
        self.assertEqual(drained[0].kind, "hermes.out")

    def test_unregistered_point_is_pending_then_delivered(self):
        self.fabric.register(5)
        self.fabric.register(2, status="active")
        receipt = self.fabric.intake(frame(source=5, destination=9))
        self.assertEqual(receipt["central_status"], "pending")
        self.assertEqual(self.fabric.monitor()["pending"], 1)
        registered = self.fabric.register(9)
        self.assertEqual(registered["pending_delivered"], 1)
        self.assertEqual(self.fabric.monitor()["pending"], 0)
        self.assertEqual(self.fabric.drain(9, 1)[0].destination_hw, 9)

    def test_reserved_and_unregistered_sources_fail_closed(self):
        with self.assertRaises(FabricRoutingError):
            self.fabric.intake(frame(source=5, destination=2))
        self.fabric.register(5)
        with self.assertRaises(FabricRoutingError):
            self.fabric.intake(frame(source=5, destination=4))

    def test_pending_capacity(self):
        fabric = CentralPointFabric(pending_limit=1)
        fabric.register(2, status="active")
        fabric.intake(frame(source=2, destination=9))
        with self.assertRaises(FabricCapacityError):
            fabric.intake(frame(source=2, destination=10))
        fabric.close()

    def test_monitor_reports_all_zero_points_and_recent_routes(self):
        self.fabric.register(5)
        self.fabric.register(2, status="active")
        self.fabric.intake(frame(source=5, destination=2))
        monitor = self.fabric.monitor()
        self.assertEqual(monitor["fabric"], "nanrouter.zero-point-fabric.v1")
        self.assertGreaterEqual(monitor["registered"], 6)
        self.assertEqual(monitor["points"][2]["endpoint"], "HW2:0")
        self.assertEqual(monitor["points"][0]["role"], "bootstrap-hardware-node")
        self.assertEqual(monitor["recent_routes"][-1]["status"], "delivered")


class FabricJournalTests(unittest.TestCase):
    def test_pending_frame_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "fabric.sqlite"
            first = CentralPointFabric(database=database)
            first.register(2, status="active")
            first.intake(frame(source=2, destination=9))
            first.close()

            second = CentralPointFabric(database=database)
            self.assertEqual(second.monitor()["pending"], 1)
            second.register(9)
            self.assertEqual(second.monitor()["pending"], 0)
            self.assertEqual(second.drain(9, 1)[0].destination_hw, 9)
            second.close()


if __name__ == "__main__":
    unittest.main()
