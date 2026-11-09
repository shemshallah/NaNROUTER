from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPEC = REPO / "spec" / "angular-ring-next-kernels.v1.json"


class AngularRingNextKernelTests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads(SPEC.read_text(encoding="utf-8"))

    def test_nannet0_stays_at_ring_255(self):
        ring = self.document["ring"]
        self.assertEqual(ring["real_lane_positions"], [0, 254])
        self.assertEqual(ring["real_lane_count"], 255)
        self.assertEqual(ring["rotation_modulus"], 255)
        self.assertEqual(ring["nannet0_ring_position"], 255)
        self.assertTrue(ring["nannet0_fixed"])
        self.assertFalse(ring["point0_is_ring_position"])
        self.assertIn("BS0:0/BSR0", ring["point0_namespace"])

    def test_six_next_kernels_are_declared(self):
        ids = {item["kernel_id"] for item in self.document["kernels"]}
        self.assertEqual(
            ids,
            {
                "mth.ring.angular_map.u32",
                "mth.trig.twiddle256.f32",
                "mth.mirror.cycle.phase_gate16.f32",
                "mth.mirror.cycle.retain.f32",
                "mth.mirror.cycle.contradiction.f32",
                "mth.attention.mix16.f32",
            },
        )
        for item in self.document["kernels"]:
            self.assertGreater(item["steps"], 0)
            self.assertTrue(item["source"].startswith("mth/nan16/"))
            self.assertTrue(item["fixture"].startswith("mth/tests/"))

    def test_rotation_never_targets_the_port(self):
        angular = next(
            item for item in self.document["kernels"]
            if item["kernel_id"] == "mth.ring.angular_map.u32"
        )
        self.assertIn("r4=255", angular["abi"])
        self.assertIn("real lane 0..254", angular["abi"])

    def test_contradiction_and_attention_do_not_force_collapse(self):
        text = " ".join(self.document["implemented_behaviors"])
        self.assertIn("contradiction pair preserving", text)
        self.assertIn("without forced top-1 selection", text)
        nonclaims = " ".join(self.document["non_claims"])
        self.assertIn("No truth collapse", nonclaims)
        self.assertIn("No top-1 forcing", nonclaims)

    def test_local_fixtures_are_not_promoted_or_live(self):
        text = " ".join(self.document["non_claims"])
        self.assertIn("No CI, live deployment, or production claim", text)
        self.assertIn("No host trigonometry", text)
        self.assertIn(
            "mth.trig.rotate.f32 is the native phase-bind primitive",
            self.document["phase_bind"],
        )


if __name__ == "__main__":
    unittest.main()
