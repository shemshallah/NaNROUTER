"""HW4 reference belongs to the real embedded NaNROUTER portal ring."""
import importlib
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from runner_riddle import hw4_full_dict, point_fabric
from tests.test_hw4_full_dict import DATA


def portal_module():
    # Reproduce Dockerfile's /app/runner module-relative imports without
    # packaging a second deployable portal or importing pinned upstream code.
    base = "deploy.portal"
    stub = types.ModuleType(base + ".runner_ring_authority")
    stub.RunnerRingAuthError = type("RunnerRingAuthError", (ValueError,), {})
    stub.RunnerRingAuthority = type("RunnerRingAuthority", (), {})
    with patch.dict(sys.modules, {
        base + ".runner_ring_authority": stub,
        base + ".point_fabric": point_fabric,
        base + ".hw4_full_dict": hw4_full_dict,
    }):
        sys.modules.pop(base + ".portal_ring", None)
        return importlib.import_module(base + ".portal_ring")


class Authority:
    def __init__(self):
        self.checkpoints = 0
        self.releases = 0

    def read_checkpoint(self):
        return None

    def checkpoint(self, **kwargs):
        self.checkpoints += 1
        return {}

    def release(self, **kwargs):
        self.releases += 1
        return {}

    def clock(self):
        return {"nanclock_tick": 17}


class HW4PortalResidentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        folder = Path(self.temp.name)
        source = folder / "wn3.1.dict.zip"
        self.store = folder / "hw4-wordnet31"
        with ZipFile(source, "w") as z:
            for name, body in DATA.items():
                z.writestr("wn3.1.dict/dict/" + name, body)
        hw4_full_dict.install(source, self.store)
        self.env = {
            "RIDDLE_HW4_STORE": str(self.store),
            "RIDDLE_HW4_RING": "NaNROUTER/MC0:0",
        }

    def test_existing_six_slot_ring_activates_hw4_and_retains_reference_across_handoff(self):
        portal = portal_module()
        with patch.dict(os.environ, self.env):
            authority = Authority()
            node = portal.PortalRingNode(
                authority, token="w"*40, endpoint="http://127.0.0.1:10000",
                database=str(Path(self.temp.name) / "fabric.sqlite"),
            )
            try:
                status = node.status()["hw4_wordnet_reference"]
                self.assertTrue(status["mounted"])
                self.assertEqual(status["ring_owner"], "NaNROUTER/MC0:0")
                self.assertFalse(status["main_ring_writable"])
                self.assertTrue(status["read_only"])
                self.assertEqual(status["pair_count"], 32640)
                self.assertTrue(node.hw4.exact("00001740-n"))
                with node._lock:
                    node._activate_locked({"epoch": 17, "lease_id": "first"})
                point = node.fabric.point(4).monitor()
                self.assertEqual(point["endpoint"], "HW4:0")
                self.assertEqual(point["role"], "wordnet-universe")
                self.assertEqual(point["status"], "active")
                with node._lock:
                    node._step_down_locked("test-handoff")
                self.assertIsNotNone(node.hw4)
                self.assertTrue(node.status()["hw4_wordnet_reference"]["mounted"])
                with node._lock:
                    node._activate_locked({"epoch": 18, "lease_id": "second"})
                self.assertTrue(node.hw4.exact("00001930-n"))
                self.assertEqual(node.status()["epoch"], 18)
                self.assertEqual(node.fabric.point(4).monitor()["status"], "active")
            finally:
                node.stop()
            self.assertEqual(authority.releases, 2)
            self.assertGreaterEqual(authority.checkpoints, 2)

    def test_refuse_bs0_owner(self):
        portal = portal_module()
        env = dict(self.env, RIDDLE_HW4_RING="NaNLMind/BS0")
        with patch.dict(os.environ, env):
            with self.assertRaisesRegex(portal.PortalRingError, "main BS0"):
                portal.PortalRingNode(
                    Authority(), token="w"*40, endpoint="http://127.0.0.1",
                    database=str(Path(self.temp.name) / "wrong.sqlite")
                )

    def test_empty_config_keeps_reserved_hw4(self):
        portal = portal_module()
        with patch.dict(os.environ, self.env, clear=False):
            with patch.dict(os.environ, {"RIDDLE_HW4_STORE": ""}):
                node = portal.PortalRingNode(
                    Authority(), token="w"*40, endpoint="http://127.0.0.1",
                    database=str(Path(self.temp.name) / "empty.sqlite")
                )
                try:
                    self.assertFalse(node.status()["hw4_wordnet_reference"]["mounted"])
                    self.assertEqual(node.fabric.point(4).monitor()["status"], "reserved")
                finally:
                    node.stop()


if __name__ == "__main__":
    unittest.main()
