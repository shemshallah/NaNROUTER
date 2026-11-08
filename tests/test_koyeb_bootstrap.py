import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runner_riddle.koyeb_bootstrap import (
    KoyebBootstrapError,
    bootstrap_koyeb,
    ensure_tier_database,
    mount_root,
)
from runner_riddle.volume_registry import (
    CANONICAL,
    DEFAULT_MOUNT_ROOTS,
    VolumeRegistry,
)

KEY = "nanrouter-koyeb-bootstrap-test-key-32+"


def configured_env(root: Path) -> dict[str, str]:
    env = {
        "RIDDLE_VOLUME_HMAC_KEY": KEY,
        "KOYEB_REGION": "was",
        "RIDDLE_DATA_DIR": str(root / "data"),
        "RIDDLE_VOLUME_REGISTRY_PATH": str(root / "data" / "volume-registry.json"),
    }
    for tier in CANONICAL:
        env[f"KOYEB_VOLUME_ID_{tier}"] = f"real-koyeb-volume-{tier.lower()}"
        env[f"KOYEB_MOUNT_ROOT_{tier}"] = str(root / tier.lower())
    return env


class KoyebBootstrapTests(unittest.TestCase):
    def test_default_mount_roots_are_physical_paths_not_logical_addresses(self):
        self.assertEqual(
            DEFAULT_MOUNT_ROOTS,
            {"BS0": "/bs0db", "MC0": "/mc0db", "SC0": "/sc0db", "GM0": "/gm0db"},
        )
        for tier, root in DEFAULT_MOUNT_ROOTS.items():
            self.assertTrue(root.startswith("/"))
            self.assertNotIn("0x", root, tier)

    def test_no_volume_config_starts_cleanly_and_writes_no_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {
                "RIDDLE_DATA_DIR": str(root / "data"),
                **{
                    f"KOYEB_MOUNT_ROOT_{tier}": str(root / tier.lower())
                    for tier in CANONICAL
                },
            }
            report = bootstrap_koyeb(env, now_tick=7)
            self.assertTrue(report["ok"])
            self.assertEqual(report["registry"]["status"], "not_configured")
            self.assertFalse(report["registry"]["configured"])
            self.assertFalse((root / "data" / "volume-registry.json").exists())
            for tier in CANONICAL:
                self.assertEqual(report["databases"][tier]["status"], "ready")
                database = Path(report["databases"][tier]["database"])
                self.assertTrue(database.is_file())
                self.assertEqual(database.name, CANONICAL[tier][1])

    def test_complete_config_writes_signed_green_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = configured_env(root)
            report = bootstrap_koyeb(
                env, mount_probe=lambda path: True, now_tick=11, write_registry=True
            )
            self.assertTrue(report["ok"])
            self.assertEqual(report["registry"]["status"], "green")
            self.assertTrue(report["registry"]["written"])
            path = Path(env["RIDDLE_VOLUME_REGISTRY_PATH"])
            registry = VolumeRegistry.load(path, KEY.encode())
            self.assertEqual(registry.health, "green")
            self.assertEqual(registry.document["generation"], 1)
            self.assertEqual(
                report["registry"]["registry_digest"],
                registry.document["registry_digest"],
            )

    def test_partial_config_is_invalid_but_does_not_invent_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {
                "RIDDLE_VOLUME_HMAC_KEY": KEY,
                "RIDDLE_DATA_DIR": str(root / "data"),
                **{
                    f"KOYEB_MOUNT_ROOT_{tier}": str(root / tier.lower())
                    for tier in CANONICAL
                },
            }
            report = bootstrap_koyeb(env, mount_probe=lambda path: True, now_tick=12)
            self.assertFalse(report["ok"])
            self.assertEqual(report["registry"]["status"], "invalid")
            self.assertIn("KOYEB_REGION", report["registry"]["missing"])
            self.assertFalse((root / "data" / "volume-registry.json").exists())

    def test_strict_mode_rejects_missing_and_degraded_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = {
                "RIDDLE_DATA_DIR": str(root / "data"),
                "RIDDLE_REQUIRE_VOLUME_REGISTRY": "1",
                **{
                    f"KOYEB_MOUNT_ROOT_{tier}": str(root / tier.lower())
                    for tier in CANONICAL
                },
            }
            with self.assertRaises(KoyebBootstrapError):
                bootstrap_koyeb(env, now_tick=13)

            configured = configured_env(root)
            configured["RIDDLE_REQUIRE_VOLUME_REGISTRY"] = "1"
            with self.assertRaises(KoyebBootstrapError):
                bootstrap_koyeb(
                    configured,
                    mount_probe=lambda path: False,
                    now_tick=14,
                )

    def test_generation_chains_from_existing_valid_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = configured_env(root)
            first = bootstrap_koyeb(env, mount_probe=lambda path: True, now_tick=15)
            second = bootstrap_koyeb(env, mount_probe=lambda path: True, now_tick=16)
            self.assertTrue(second["ok"])
            self.assertEqual(second["registry"]["status"], "green")
            path = Path(env["RIDDLE_VOLUME_REGISTRY_PATH"])
            registry = VolumeRegistry.load(path, KEY.encode())
            self.assertEqual(registry.document["generation"], 2)
            self.assertEqual(
                registry.document["previous_digest"],
                first["registry"]["registry_digest"],
            )

    def test_mount_root_rejects_unknown_tier(self):
        with self.assertRaises(KoyebBootstrapError):
            mount_root({}, "NOPE")

    def test_database_initialization_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "bs0"
            first = ensure_tier_database(root, "BS0")
            second = ensure_tier_database(root, "BS0")
            self.assertEqual(first, second)
            self.assertTrue(first.is_file())


if __name__ == "__main__":
    unittest.main()
