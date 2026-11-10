"""HW4 reference is resident in NaNROUTER HTTP/fabric, never BS0 trainer."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zipfile import ZipFile

from runner_riddle.hw4_full_dict import install
from runner_riddle.http_service import RiddleService, ServiceConfigError, make_handler
from tests.test_hw4_full_dict import DATA


class HW4ResidentServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        source = base / "wn3.1.dict.zip"
        store = base / "mc0-wordnet"
        with ZipFile(source, "w") as z:
            for name, data in DATA.items():
                z.writestr("wn3.1.dict/dict/" + name, data)
        install(source, store)
        self.store = store
        self.environment = {
            "RIDDLE_DATA_DIR": str(base / "router-data"),
            "RIDDLE_HW4_STORE": str(store),
            "RIDDLE_HW4_RING": "NaNROUTER/MC0:0",
            "RIDDLE_FABRIC_ENABLED": "1",
            "RIDDLE_INTAKE_TOKEN": "i" * 40,
            "RIDDLE_WORKER_TOKEN": "w" * 40,
            "RIDDLE_FEEDBACK_HMAC_KEY": "f" * 40,
        }

    def test_mount_activates_fixed_hw4_in_router_fabric_and_get_is_auth_protected(self):
        with patch.dict(os.environ, self.environment):
            service = RiddleService()
            try:
                point = service.point_fabric.point(4).monitor()
                self.assertEqual(point["role"], "wordnet-universe")
                self.assertEqual(point["status"], "active")
                self.assertEqual(point["endpoint"], "HW4:0")
                self.assertEqual(service.hw4.status()["ring_owner"], "NaNROUTER/MC0:0")
                server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service))
                worker = threading.Thread(target=server.serve_forever, daemon=True)
                worker.start()
                try:
                    url = "http://127.0.0.1:" + str(server.server_port)
                    with self.assertRaises(HTTPError) as err:
                        urlopen(url + "/v1/riddle/hw4/status", timeout=5)
                    self.assertEqual(err.exception.code, 401)
                    def fetch(path):
                        request = Request(url + path, headers={
                            "Authorization": "Bearer " + "w"*40
                        })
                        with urlopen(request, timeout=5) as r:
                            return json.load(r)
                    status = fetch("/v1/riddle/hw4/status")
                    self.assertTrue(status["read_only"])
                    self.assertTrue(status["mounted"])
                    self.assertEqual(status["pair_count"], 32640)
                    matrix = fetch("/v1/riddle/hw4/pair?a=0&b=1")
                    self.assertEqual(matrix["pair_id"], 1)
                    exact = fetch("/v1/riddle/hw4/exact?synset=00001740-n")
                    self.assertTrue(exact["pointers"])
                    health = fetch("/healthz")
                    self.assertTrue(health["hw4_wordnet_reference"]["mounted"])
                    self.assertFalse(health["hw4_wordnet_reference"].get("main_ring_writable", False))
                finally:
                    server.shutdown()
                    worker.join(timeout=10)
                    server.server_close()
            finally:
                service.close()

    def test_main_ring_identity_is_refused_even_with_valid_reference(self):
        env = dict(self.environment, RIDDLE_HW4_RING="NaNLMind/BS0")
        with patch.dict(os.environ, env):
            with self.assertRaisesRegex(ServiceConfigError, "main runner ring"):
                RiddleService()

    def test_missing_or_corrupted_reference_refuses_router_startup(self):
        env = dict(self.environment, RIDDLE_HW4_STORE=str(self.store / "missing"))
        with patch.dict(os.environ, env):
            with self.assertRaisesRegex(ServiceConfigError, "failed closed"):
                RiddleService()


if __name__ == "__main__":
    unittest.main()
