"""In-process Koyeb BS0:0 smoke contract for the public health endpoint.

This reproduces the credential-free assertions from
``.github/workflows/koyeb-container-smoke.yml`` and
``deploy/koyeb/README.md`` without Docker, provider credentials, external
network access, or a live Koyeb/NANNET0 deployment. The service is the real
``RiddleService`` bound to an ephemeral loopback port.

The missing-token case follows the documented operator requirement in
``deploy/koyeb/README.md`` (intake/worker tokens and the feedback key are each
at least 32 characters) and the fail-closed constructor check in
``runner_riddle/http_service.py``.
"""
import json
import os
import tempfile
import threading
import unittest
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.request import urlopen

from runner_riddle.http_service import (
    RiddleService,
    ServiceConfigError,
    make_handler,
)

TEST_BUILD_REVISION = "0123456789abcdef0123456789abcdef01234567"
INTAKE_TOKEN = "koyeb-smoke-intake-token-0000000001"
WORKER_TOKEN = "koyeb-smoke-worker-token-0000000002"
FEEDBACK_HMAC_KEY = "koyeb-smoke-feedback-key-0000000003"
ROOT_ADDRESS = "nan://GM0:0::SC0:0::MC0:0::BS0:0::HW0:0"

EXPECTED_HEALTH_KEYS = {
    "service",
    "address",
    "status",
    "build_revision",
    "runtime",
    "queue",
    "range_manifest_present",
    "route_cache_present",
    "volume_registry",
    "runner_ring",
    "live_route_commit",
    "hermes_delegated_lease_authority",
    "hermes_native_guest_configured",
    "hermes_n16t_dispatch_ready",
    "hermes_n16t_separate_guest_pool",
    "point_fabric",
}


def credential_free_env(data_dir):
    """Return only the smoke-test configuration, with no Koyeb bindings.

    ``TMPDIR`` is retained because the test process may run on a platform
    whose only writable temporary directory is supplied through it.
    """
    return {
        "TMPDIR": tempfile.gettempdir(),
        "RIDDLE_DATA_DIR": str(data_dir),
        "RIDDLE_BUILD_REVISION": TEST_BUILD_REVISION,
        "RIDDLE_INTAKE_TOKEN": INTAKE_TOKEN,
        "RIDDLE_WORKER_TOKEN": WORKER_TOKEN,
        "RIDDLE_FEEDBACK_HMAC_KEY": FEEDBACK_HMAC_KEY,
    }


@contextmanager
def running_service(data_dir):
    """Start one real service on an ephemeral loopback port and stop it cleanly."""
    with mock.patch.dict(os.environ, credential_free_env(data_dir), clear=True):
        service = RiddleService()
        server = None
        thread = None
        try:
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service))
            server.daemon_threads = True
            thread = threading.Thread(
                target=server.serve_forever,
                kwargs={"poll_interval": 0.01},
                name="riddle-koyeb-smoke",
                daemon=True,
            )
            thread.start()
            yield service, server
        finally:
            if server is not None:
                if thread is not None and thread.is_alive():
                    server.shutdown()
                    thread.join(timeout=5)
                server.server_close()
            service.close()


class KoyebSmokeContractTests(unittest.TestCase):
    def test_healthz_matches_credential_free_koyeb_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            with running_service(tmp) as (service, server):
                self.assertFalse(
                    any(key.startswith("KOYEB_") for key in os.environ)
                )
                self.assertFalse(os.environ.get("RIDDLE_VOLUME_HMAC_KEY"))
                self.assertFalse(os.environ.get("RIDDLE_VOLUME_REGISTRY_PATH"))
                self.assertEqual(service.volume_key, b"")
                self.assertEqual(
                    service.volume_registry_path,
                    Path(tmp) / "volume-registry.json",
                )
                self.assertFalse(service.volume_registry_path.exists())

                url = f"http://127.0.0.1:{server.server_port}/healthz"
                with urlopen(url, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertEqual(
                        response.headers.get_content_type(), "application/json"
                    )
                    self.assertEqual(
                        response.headers.get("Cache-Control"), "no-store"
                    )
                    raw = response.read()

                body = json.loads(raw.decode("utf-8"))

                self.assertEqual(set(body), EXPECTED_HEALTH_KEYS)
                self.assertEqual(body["service"], "Runner Riddle BS0:0")
                self.assertEqual(body["address"], ROOT_ADDRESS)
                self.assertEqual(body["status"], "ready")
                self.assertEqual(body["build_revision"], TEST_BUILD_REVISION)
                self.assertEqual(body["runtime"], {
                    "nan16_word_bits": 16,
                    "ring_slots": 6,
                    "active_slots": 1,
                    "n16t_guest_configured": False,
                })
                self.assertEqual(body["queue"], {
                    "queued": 0,
                    "leased": 0,
                    "acked": 0,
                    "deadletter": 0,
                })
                self.assertIs(body["range_manifest_present"], False)
                self.assertIs(body["route_cache_present"], False)
                self.assertEqual(body["volume_registry"], {
                    "health": "unknown",
                    "configured": False,
                })
                self.assertEqual(body["runner_ring"], {
                    "health": "unknown",
                    "configured": False,
                })
                self.assertIs(body["live_route_commit"], False)
                self.assertIs(body["hermes_delegated_lease_authority"], False)
                self.assertIs(body["hermes_native_guest_configured"], False)
                self.assertIs(body["hermes_n16t_dispatch_ready"], False)
                self.assertIs(body["hermes_n16t_separate_guest_pool"], False)
                self.assertTrue(body["point_fabric"]["enabled"])
                self.assertEqual(
                    body["point_fabric"]["schema"],
                    "nanrouter.zero-point-fabric.v1",
                )
                self.assertEqual(body["point_fabric"]["queued"], 0)
                self.assertEqual(body["point_fabric"]["pending"], 0)

                # The public health document must not echo any configured
                # bearer token, HMAC key, or authorization material.
                for secret in (INTAKE_TOKEN, WORKER_TOKEN, FEEDBACK_HMAC_KEY):
                    self.assertNotIn(secret.encode(), raw)
                lowered = raw.lower()
                self.assertNotIn(b"token", lowered)
                self.assertNotIn(b"authorization", lowered)
                self.assertNotIn(b"bearer", lowered)


class TokenConfigurationTests(unittest.TestCase):
    def test_missing_required_token_configuration_fails_closed(self):
        required = (
            "RIDDLE_INTAKE_TOKEN",
            "RIDDLE_WORKER_TOKEN",
            "RIDDLE_FEEDBACK_HMAC_KEY",
        )
        for missing in required:
            with self.subTest(missing=missing):
                with tempfile.TemporaryDirectory() as tmp:
                    env = credential_free_env(tmp)
                    del env[missing]
                    # Fabric startup is unrelated to credential validation;
                    # skipping it prevents a failed constructor from leaving
                    # an open journal handle behind.
                    env["RIDDLE_FABRIC_ENABLED"] = "0"
                    with mock.patch.dict(os.environ, env, clear=True):
                        with self.assertRaises(ServiceConfigError) as caught:
                            RiddleService()
                self.assertIn(missing, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
