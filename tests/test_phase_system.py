from __future__ import annotations

import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "mth" / "tests" / "mth_phase_system_test.nas"
RUNNER = REPO / "tools" / "run_mth_fixtures.py"


class PhaseSystemIntegrationTests(unittest.TestCase):
    def test_fixture_exists_and_has_marker(self):
        self.assertTrue(FIXTURE.exists())
        text = FIXTURE.read_text(encoding="utf-8")
        self.assertIn("MTH PHASE SYSTEM PASS", text)
        self.assertIn("MTH PHASE SYSTEM FAIL", text)

    def test_fixture_composes_the_new_trusted_kernels(self):
        text = FIXTURE.read_text(encoding="utf-8")
        for kernel in (
            "mth_trig_twiddle256_f32.nas",
            "mth_mirror_cycle_phase_gate.nas",
            "mth_mirror_cycle_train_step_f32.nas",
            "mth_mirror_cycle_predict16_f32.nas",
            "mth_attention_mix16_f32.nas",
            "mth_mirror_cycle_retain.nas",
            "mth_mirror_cycle_contradiction.nas",
            "mth_ring_angular_map.nas",
        ):
            self.assertIn(kernel, text)

    def test_fixture_is_documented_as_local_integration_evidence(self):
        docs = (REPO / "docs" / "ANGULAR_RING_NEXT_KERNELS.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("mth/tests/mth_phase_system_test.nas", docs)
        self.assertIn("MTH PHASE SYSTEM PASS", docs)
        self.assertIn("local integration fixture", docs.lower())


if __name__ == "__main__":
    unittest.main()
