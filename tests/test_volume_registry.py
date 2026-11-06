import unittest

from runner_riddle.volume_registry import (
    CANONICAL, VolumeRegistry, VolumeRegistryError, logical_address,
    build_koyeb_registry, write_koyeb_registry,
)


KEY = b"nanrouter-volume-registry-test-key-32-bytes"


def records(health="green", verified=True):
    out = []
    for tier, (address, database_file) in CANONICAL.items():
        out.append({
            "tier": tier,
            "logical_address": address,
            "shard": 0,
            "provider": "koyeb",
            "provider_volume_id": "koyeb-volume-" + tier.lower(),
            "mount_root": { "BS0": "/bs0db", "MC0": "/mc0db", "SC0": "/sc0db", "GM0": "/gm0db" }[tier],
            "database_file": database_file,
            "region": "was",
            "health": health,
            "mount_verified": verified,
            "observed_at_tick": 100,
            "generation": 1,
        })
    return out


class VolumeRegistryTests(unittest.TestCase):
    def test_all_four_green_mount_verified_volumes_aggregate_green(self):
        registry = VolumeRegistry.build_signed(
            network_id="nan-global", generation=1, previous_digest=None,
            volumes=records(), key=KEY,
        )
        self.assertEqual(registry.health, "green")
        summary = registry.summary()
        self.assertEqual(set(summary["canonical_tiers"]), {"BS0", "MC0", "SC0", "GM0"})

    def test_green_without_verified_mount_is_not_green(self):
        registry = VolumeRegistry.build_signed(
            network_id="nan-global", generation=1, previous_digest=None,
            volumes=records(verified=False), key=KEY,
        )
        self.assertEqual(registry.health, "degraded")

    def test_missing_tier_is_rejected(self):
        with self.assertRaises(VolumeRegistryError):
            VolumeRegistry.build_signed(
                network_id="nan-global", generation=1, previous_digest=None,
                volumes=records()[:-1], key=KEY,
            )

    def test_tier_address_and_database_filename_are_bound(self):
        bad = records()
        bad[0]["logical_address"] = CANONICAL["MC0"][0]
        with self.assertRaises(VolumeRegistryError):
            VolumeRegistry.build_signed(
                network_id="nan-global", generation=1, previous_digest=None,
                volumes=bad, key=KEY,
            )

    def test_nonzero_shards_have_distinct_crc_checked_addresses(self):
        self.assertEqual(logical_address("BS0", 0), CANONICAL["BS0"][0])
        self.assertNotEqual(logical_address("BS0", 1), CANONICAL["BS0"][0])
        self.assertNotEqual(logical_address("BS0", 1), logical_address("MC0", 1))
        extra = records()
        extra.append({
            "tier": "BS0", "logical_address": logical_address("BS0", 1),
            "shard": 1, "provider": "koyeb", "provider_volume_id": "koyeb-volume-bs0-shard-1",
            "mount_root": "/bs0db-shard-1", "database_file": "bs0db.sqlite3",
            "region": "was", "health": "green", "mount_verified": True,
            "observed_at_tick": 101, "generation": 1,
        })
        registry = VolumeRegistry.build_signed(
            network_id="nan-global", generation=1, previous_digest=None,
            volumes=extra, key=KEY,
        )
        self.assertEqual(registry.health, "green")

    def test_mount_root_must_be_normalized_absolute_physical_path(self):
        bad = records()
        bad[0]["mount_root"] = "/../bs0db"
        with self.assertRaises(VolumeRegistryError):
            VolumeRegistry.build_signed(
                network_id="nan-global", generation=1, previous_digest=None,
                volumes=bad, key=KEY,
            )

    def test_provider_placeholders_and_duplicate_ids_are_rejected(self):
        bad = records()
        bad[0]["provider_volume_id"] = "<actual Koyeb volume ID>"
        with self.assertRaises(VolumeRegistryError):
            VolumeRegistry.build_signed(
                network_id="nan-global", generation=1, previous_digest=None,
                volumes=bad, key=KEY,
            )
        bad = records()
        bad[1]["provider_volume_id"] = bad[0]["provider_volume_id"]
        with self.assertRaises(VolumeRegistryError):
            VolumeRegistry.build_signed(
                network_id="nan-global", generation=1, previous_digest=None,
                volumes=bad, key=KEY,
            )

    def test_koyeb_bootstrap_requires_real_ids_and_verified_mounts(self):
        import os
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            env = {
                "RIDDLE_VOLUME_HMAC_KEY": KEY.decode(),
                "KOYEB_REGION": "was",
            }
            roots = {}
            for tier, (_, database_file) in CANONICAL.items():
                root = Path(tmp) / tier.lower()
                root.mkdir()
                (root / database_file).write_bytes(b"sqlite-placeholder-for-mount-probe")
                roots[tier] = str(root)
                env["KOYEB_VOLUME_ID_" + tier] = "real-provider-id-" + tier.lower()
                env["KOYEB_MOUNT_ROOT_" + tier] = str(root)
            registry = build_koyeb_registry(
                env, mount_probe=lambda root: True, now_tick=123,
            )
            self.assertEqual(registry.health, "green")
            self.assertTrue(all(v["mount_verified"] for v in registry.document["volumes"]))
            path = Path(tmp) / "registry.json"
            write_koyeb_registry(path, registry)
            loaded = VolumeRegistry.load(path, KEY)
            self.assertEqual(loaded.document["registry_digest"], registry.document["registry_digest"])

            degraded = build_koyeb_registry(
                env, mount_probe=lambda root: False, now_tick=124,
            )
            self.assertEqual(degraded.health, "degraded")
            self.assertFalse(any(v["mount_verified"] for v in degraded.document["volumes"]))

            missing = dict(env)
            missing.pop("KOYEB_VOLUME_ID_GM0")
            with self.assertRaises(VolumeRegistryError):
                build_koyeb_registry(missing, mount_probe=lambda root: True, now_tick=125)

    def test_tampering_is_detected(self):
        registry = VolumeRegistry.build_signed(
            network_id="nan-global", generation=1, previous_digest=None,
            volumes=records(), key=KEY,
        )
        document = dict(registry.document)
        document["volumes"] = [dict(v) for v in document["volumes"]]
        document["volumes"][0]["health"] = "unavailable"
        with self.assertRaises(VolumeRegistryError):
            VolumeRegistry(document, KEY)

    def test_registry_signature_requires_independent_long_key(self):
        with self.assertRaises(VolumeRegistryError):
            VolumeRegistry.build_signed(
                network_id="nan-global", generation=1, previous_digest=None,
                volumes=records(), key=b"short",
            )


if __name__ == "__main__":
    unittest.main()
