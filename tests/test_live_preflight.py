import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runner_riddle.live_preflight import (
    ACTIVE_SLOT_POLICY,
    DeploymentConfig,
    LivePreflight,
    LivePreflightError,
    preflight_report,
    verify_signed_registry,
)
from runner_riddle.point0_bridge import POINT_ZERO_ADDRESS
from runner_riddle.volume_registry import (
    CANONICAL,
    VolumeRegistry,
    write_koyeb_registry,
)


KEY = b"nanrouter-live-preflight-test-key-32b"
BS0_TOKEN = "bs0-live-token-value"
MC0_TOKEN = "mc0-live-token-value"


def volume_records(*, health="green", verified=True, generation=1):
    roots = {"BS0": "/bs0db", "MC0": "/mc0db", "SC0": "/sc0db", "GM0": "/gm0db"}
    return [
        {
            "tier": tier,
            "logical_address": address,
            "shard": 0,
            "provider": "koyeb",
            "provider_volume_id": "koyeb-volume-" + tier.lower(),
            "mount_root": roots[tier],
            "database_file": database_file,
            "region": "was",
            "health": health,
            "mount_verified": verified,
            "observed_at_tick": 100,
            "generation": generation,
        }
        for tier, (address, database_file) in CANONICAL.items()
    ]


def write_registry(
    directory,
    *,
    generation=1,
    health="green",
    verified=True,
    previous_digest=None,
):
    registry = VolumeRegistry.build_signed(
        network_id="nan-global",
        generation=generation,
        previous_digest=previous_digest,
        volumes=volume_records(
            health=health, verified=verified, generation=generation
        ),
        key=KEY,
    )
    path = Path(directory) / "volume-registry.json"
    write_koyeb_registry(path, registry)
    return path, registry


def deployment_env(registry_path, **overrides):
    env = {
        "KOYEB_BS0DB_URL": "https://bs0.example.test/db",
        "KOYEB_BS0DB_TOKEN": BS0_TOKEN,
        "KOYEB_MC0DB_URL": "https://mc0.example.test/db?sslmode=require",
        "KOYEB_MC0DB_TOKEN": MC0_TOKEN,
        "NANNET0_ENDPOINT": "https://nannet0.example.test",
        "RIDDLE_VOLUME_REGISTRY_PATH": str(registry_path),
        "RIDDLE_VOLUME_HMAC_KEY": KEY.decode(),
        "NANROUTER_UNIVERSE_PAGES": "256",
        "NANROUTER_PAGE_BYTES": "32768",
        "NANROUTER_GUEST_BUDGET_BYTES": "1048576",
        "RIDDLE_RING_ACTIVE_SLOT_POLICY": ACTIVE_SLOT_POLICY,
        "NANROUTER_POINT0_ROUTE": POINT_ZERO_ADDRESS,
    }
    env.update(overrides)
    return env


def check_by_id(report, check_id):
    matches = [check for check in report["checks"] if check["id"] == check_id]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one {check_id!r} check")
    return matches[0]


class LivePreflightMissingInputTests(unittest.TestCase):
    def test_missing_env_is_explicitly_blocked_without_network(self):
        report = preflight_report({})

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["mode"], "offline")
        self.assertEqual(report["schema"], "nanrouter.live-preflight.v1")
        failed = {
            check["id"] for check in report["checks"] if check["status"] == "fail"
        }
        self.assertTrue({
            "koyeb.bs0db.url",
            "koyeb.bs0db.token",
            "koyeb.mc0db.url",
            "koyeb.mc0db.token",
            "nannet0.endpoint",
            "volume.registry.key",
            "volume.registry.path",
            "universe.pages",
            "universe.page_bytes",
            "universe.guest_budget",
            "runner_ring.active_slot_policy",
            "point0.route",
        }.issubset(failed))
        for check_id in ("probe.koyeb.bs0db", "probe.koyeb.mc0db", "probe.nannet0"):
            self.assertEqual(check_by_id(report, check_id)["status"], "skip")
            self.assertFalse(check_by_id(report, check_id)["evidence"]["network"])
        # JSON-safe is part of the public contract.
        self.assertEqual(json.loads(json.dumps(report)), report)

    def test_invalid_values_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = write_registry(tmp)
            env = deployment_env(
                path,
                KOYEB_BS0DB_URL="ftp://bs0.example.test",
                KOYEB_MC0DB_URL="https://user:pass@mc0.example.test",
                RIDDLE_VOLUME_HMAC_KEY="short",
                NANROUTER_UNIVERSE_PAGES="255",
                NANROUTER_PAGE_BYTES="4096",
                NANROUTER_GUEST_BUDGET_BYTES="524288",
                RIDDLE_RING_ACTIVE_SLOT_POLICY="multi-active",
                NANROUTER_POINT0_ROUTE="MC0:0/R0",
            )
            report = preflight_report(env)

        self.assertEqual(report["status"], "blocked")
        for check_id in (
            "koyeb.bs0db.url",
            "koyeb.mc0db.url",
            "volume.registry.key",
            "universe.pages",
            "universe.page_bytes",
            "universe.guest_budget",
            "runner_ring.active_slot_policy",
            "point0.route",
        ):
            self.assertEqual(check_by_id(report, check_id)["status"], "fail")

    def test_conflicting_env_aliases_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = write_registry(tmp)
            env = deployment_env(
                path,
                BS0DB_URL="https://other-bs0.example.test",
            )
            report = preflight_report(env)

        self.assertEqual(report["status"], "blocked")
        check = check_by_id(report, "koyeb.bs0db.url")
        self.assertEqual(check["status"], "fail")
        self.assertIn("conflicting", check["message"])


class LivePreflightValidOfflineTests(unittest.TestCase):
    def test_valid_registry_produces_deterministic_green_offline_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, registry = write_registry(tmp)
            env = deployment_env(path)
            first = preflight_report(env)
            second = preflight_report(env)

        self.assertEqual(first, second)
        self.assertEqual(first["status"], "green")
        self.assertEqual(first["summary"]["failed"], 0)
        self.assertEqual(first["mode"], "offline")
        self.assertEqual(
            check_by_id(first, "volume.registry.signature")["evidence"][
                "registry_digest"
            ],
            registry.document["registry_digest"],
        )
        self.assertEqual(
            check_by_id(first, "volume.registry.health")["evidence"]["health"],
            "green",
        )
        self.assertEqual(
            first["evidence"]["runtime"]["guest_budget_bytes"], 1048576
        )
        self.assertEqual(first["evidence"]["runtime"]["guest_pages"], 32)
        self.assertEqual(first["evidence"]["runtime"]["universe_bytes"], 8 * 1024 * 1024)
        self.assertEqual(json.loads(json.dumps(first)), first)
        self.assertEqual(len(first["evidence"]["config_digest"]), 64)

    def test_injected_probe_transport_is_bounded_and_green(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = write_registry(tmp)
            env = deployment_env(path)
            calls = []

            def transport(url, headers, timeout, max_bytes):
                calls.append((url, dict(headers), timeout, max_bytes))
                return 200, b'{"health":"green"}', "application/json"

            report = preflight_report(
                env, probe=True, timeout=1.5, probe_transport=transport
            )

        self.assertEqual(report["status"], "green")
        self.assertEqual(report["mode"], "probe")
        self.assertEqual(len(calls), 3)
        for url, headers, timeout, max_bytes in calls:
            self.assertEqual(timeout, 1.5)
            self.assertTrue(url.endswith("/healthz"))
            self.assertEqual(headers["User-Agent"], "NaNROUTER-live-preflight/1")
            self.assertLessEqual(max_bytes, 65536)
        self.assertEqual(calls[0][1]["Authorization"], "Bearer " + BS0_TOKEN)
        self.assertEqual(calls[1][1]["Authorization"], "Bearer " + MC0_TOKEN)
        self.assertNotIn("Authorization", calls[2][1])
        dumped = json.dumps(report, sort_keys=True)
        self.assertNotIn(BS0_TOKEN, dumped)
        self.assertNotIn(MC0_TOKEN, dumped)

    def test_probe_failure_is_bounded_and_redacted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = write_registry(tmp)
            env = deployment_env(path)

            def transport(url, headers, timeout, max_bytes):
                return 503, b'{"health":"unavailable"}', "application/json"

            report = preflight_report(
                env, probe=True, timeout=1.0, probe_transport=transport
            )

        self.assertEqual(report["status"], "blocked")
        for check_id in ("probe.koyeb.bs0db", "probe.koyeb.mc0db", "probe.nannet0"):
            check = check_by_id(report, check_id)
            self.assertEqual(check["status"], "fail")
            self.assertEqual(check["evidence"]["http_status"], 503)
        self.assertNotIn(BS0_TOKEN, json.dumps(report, sort_keys=True))


class LivePreflightNoNetworkTests(unittest.TestCase):
    def test_default_report_never_calls_the_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = write_registry(tmp)
            env = deployment_env(path)
            with mock.patch(
                "runner_riddle.live_preflight.urllib.request.urlopen",
                side_effect=AssertionError("network must not be used"),
            ) as urlopen:
                report = preflight_report(env)

        self.assertEqual(report["status"], "green")
        self.assertEqual(report["mode"], "offline")
        urlopen.assert_not_called()
        self.assertFalse(report["evidence"]["runtime"]["network_used"])

    def test_offline_registry_verification_does_not_need_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, registry = write_registry(tmp)
            with mock.patch(
                "runner_riddle.live_preflight.urllib.request.urlopen",
                side_effect=AssertionError("network must not be used"),
            ) as urlopen:
                loaded = verify_signed_registry(path, KEY, expected_generation=1)

        self.assertEqual(
            loaded.document["registry_digest"], registry.document["registry_digest"]
        )
        urlopen.assert_not_called()


class LivePreflightRegistryGateTests(unittest.TestCase):
    def test_unsigned_registry_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, registry = write_registry(tmp)
            document = dict(registry.document)
            document.pop("signature")
            path.write_text(json.dumps(document), encoding="utf-8")

            report = preflight_report(deployment_env(path))
            with self.assertRaises(LivePreflightError) as caught:
                verify_signed_registry(path, KEY)

        self.assertEqual(report["status"], "blocked")
        check = check_by_id(report, "volume.registry.signature")
        self.assertEqual(check["status"], "fail")
        self.assertEqual(check["evidence"]["code"], "unsigned_registry")
        self.assertEqual(caught.exception.code, "unsigned_registry")

    def test_wrong_registry_digest_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, registry = write_registry(tmp)
            document = dict(registry.document)
            document["registry_digest"] = "0" * 64
            path.write_text(json.dumps(document), encoding="utf-8")

            report = preflight_report(deployment_env(path))
            with self.assertRaises(LivePreflightError) as caught:
                verify_signed_registry(path, KEY)

        self.assertEqual(report["status"], "blocked")
        check = check_by_id(report, "volume.registry.signature")
        self.assertEqual(check["status"], "fail")
        self.assertEqual(check["evidence"]["code"], "digest_mismatch")
        self.assertEqual(caught.exception.code, "digest_mismatch")

    def test_tampered_volume_record_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, registry = write_registry(tmp)
            document = json.loads(path.read_text(encoding="utf-8"))
            document["volumes"][0]["health"] = "unavailable"
            path.write_text(json.dumps(document), encoding="utf-8")

            report = preflight_report(deployment_env(path))
            with self.assertRaises(LivePreflightError) as caught:
                verify_signed_registry(path, KEY)

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(
            check_by_id(report, "volume.registry.signature")["evidence"]["code"],
            "digest_mismatch",
        )
        self.assertEqual(caught.exception.code, "digest_mismatch")

    def test_stale_registry_epoch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = write_registry(tmp, generation=1)
            report = preflight_report(
                deployment_env(path), expected_generation=2
            )
            with self.assertRaises(LivePreflightError) as caught:
                verify_signed_registry(path, KEY, expected_generation=2)

        self.assertEqual(report["status"], "blocked")
        check = check_by_id(report, "volume.registry.generation")
        self.assertEqual(check["status"], "fail")
        self.assertEqual(check["evidence"]["code"], "stale_generation")
        self.assertIn("stale", check["message"])
        self.assertEqual(caught.exception.code, "stale_generation")

    def test_minimum_generation_and_observation_age_are_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = write_registry(tmp, generation=1)
            stale_generation = preflight_report(
                deployment_env(path), minimum_generation=2
            )
            stale_observation = preflight_report(
                deployment_env(path),
                minimum_generation=1,
                now_tick=200,
                max_observation_age_ticks=10,
            )

        self.assertEqual(stale_generation["status"], "blocked")
        self.assertEqual(
            check_by_id(stale_generation, "volume.registry.generation")[
                "evidence"
            ]["code"],
            "stale_generation",
        )
        self.assertEqual(stale_observation["status"], "blocked")
        self.assertEqual(
            check_by_id(stale_observation, "volume.registry.generation")[
                "evidence"
            ]["code"],
            "stale_observation",
        )

    def test_degraded_registry_health_blocks_the_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = write_registry(tmp, health="degraded", verified=False)
            report = preflight_report(deployment_env(path))

        self.assertEqual(report["status"], "blocked")
        check = check_by_id(report, "volume.registry.health")
        self.assertEqual(check["status"], "fail")
        self.assertEqual(check["evidence"]["health"], "degraded")


class LivePreflightRedactionTests(unittest.TestCase):
    def test_secrets_are_absent_from_report_dump_and_reprs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = write_registry(tmp)
            env = deployment_env(path)
            report = LivePreflight(
                env,
                bs0db_token="repr-bs0-secret-value",
                mc0db_token="repr-mc0-secret-value",
            ).report()
            live_repr = repr(LivePreflight(
                env,
                bs0db_token="repr-bs0-secret-value",
                mc0db_token="repr-mc0-secret-value",
            ))
            config_repr = repr(DeploymentConfig(
                bs0db_token="repr-bs0-secret-value",
                mc0db_token="repr-mc0-secret-value",
                volume_hmac_key=b"repr-volume-secret-value-32-bytes",
            ))

        dumped = json.dumps(report, sort_keys=True)
        self.assertNotIn(BS0_TOKEN, dumped)
        self.assertNotIn(MC0_TOKEN, dumped)
        self.assertNotIn(KEY.decode(), dumped)
        self.assertNotIn("repr-bs0-secret-value", dumped)
        self.assertNotIn("repr-mc0-secret-value", dumped)
        self.assertNotIn("repr-bs0-secret-value", live_repr)
        self.assertNotIn("repr-mc0-secret-value", live_repr)
        self.assertNotIn("repr-bs0-secret-value", config_repr)
        self.assertNotIn("repr-mc0-secret-value", config_repr)
        self.assertNotIn("repr-volume-secret-value-32-bytes", config_repr)
        self.assertIn("<redacted>", live_repr)
        self.assertIn("<redacted>", config_repr)

    def test_registry_key_is_not_echoed_in_failure_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = write_registry(tmp)
            env = deployment_env(path, RIDDLE_VOLUME_HMAC_KEY="wrong-key-" + "x" * 32)
            report = preflight_report(env)

        self.assertEqual(report["status"], "blocked")
        dumped = json.dumps(report, sort_keys=True)
        self.assertNotIn("wrong-key-" + "x" * 32, dumped)


if __name__ == "__main__":
    unittest.main()
