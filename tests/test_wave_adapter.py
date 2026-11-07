import unittest

from runner_riddle.wave_adapter import WaveAdapterConfig, WaveAdapterError


class WaveAdapterTests(unittest.TestCase):
    def test_disabled_default_is_valid(self):
        config = WaveAdapterConfig("a1", "u1", "base")
        config.validate()
        self.assertFalse(config.enabled)

    def test_roundtrip_dict(self):
        config = WaveAdapterConfig(
            "a1", "u1", "base", readout_dim=255, residual_scale=0.1,
            mode="ring_readout", enabled=False, evidence_level="native_verified",
            ablations=("void_on_off", "ring_on_off"),
        )
        restored = WaveAdapterConfig.from_dict(config.to_dict())
        self.assertEqual(restored, config)

    def test_enable_requires_ablation_evidence(self):
        config = WaveAdapterConfig("a1", "u1", "base", residual_scale=0.1, enabled=True)
        with self.assertRaises(WaveAdapterError):
            config.validate()

    def test_enable_with_ablation_is_valid(self):
        config = WaveAdapterConfig(
            "a1", "u1", "base", residual_scale=0.1, enabled=True,
            evidence_level="ablation_passed", ablations=("void_on_off",),
        )
        config.validate()

    def test_beta_bounds(self):
        with self.assertRaises(WaveAdapterError):
            WaveAdapterConfig("a1", "u1", "base", residual_scale=1.5).validate()
        with self.assertRaises(WaveAdapterError):
            WaveAdapterConfig("a1", "u1", "base", residual_scale=-0.1).validate()

    def test_unknown_mode_rejected(self):
        with self.assertRaises(WaveAdapterError):
            WaveAdapterConfig("a1", "u1", "base", mode="magic").validate()

    def test_unknown_ablation_rejected(self):
        with self.assertRaises(WaveAdapterError):
            WaveAdapterConfig("a1", "u1", "base", ablations=("nope",)).validate()


if __name__ == "__main__":
    unittest.main()
