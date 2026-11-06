import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from runner_riddle.cache import MasterRouteCache
from runner_riddle.macro import verify_feedback_signature
from runner_riddle.http_service import RiddleService, make_handler


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {
            "RIDDLE_DATA_DIR": self.tmp.name,
            "RIDDLE_INTAKE_TOKEN": "i" * 40,
            "RIDDLE_WORKER_TOKEN": "w" * 40,
            "RIDDLE_FEEDBACK_HMAC_KEY": "f" * 40,
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.service = RiddleService()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.service))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def request(self, path, body=None, token=None):
        raw = None if body is None else json.dumps(body).encode()
        headers = {}
        if raw is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = "Bearer " + token
        req = Request(self.base + path, data=raw, headers=headers,
                      method="GET" if body is None else "POST")
        with urlopen(req, timeout=3) as response:
            payload = response.read()
            return response.status, json.loads(payload) if payload else {}

    def test_health_identifies_bs0_gateway_and_queue(self):
        status, body = self.request("/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(body["address"], "nan://GM0:SC0:MC0:BS0:0:HW0:0")
        self.assertFalse(body["live_route_commit"])

    def test_intake_requires_auth_and_worker_can_lease_and_ack(self):
        payload = b"NaN16 source"
        body = {
            "universe_id": "training-universe-0",
            "node_point": 9,
            "head_index": 17,
            "source_kind": "nan-source",
            "payload_hex": payload.hex(),
            "acl_digest": "b" * 64,
            "nanclock_tick": 12,
        }
        with self.assertRaises(HTTPError) as err:
            self.request("/v1/riddle/intake", body)
        self.assertEqual(err.exception.code, 401)

        _, accepted = self.request("/v1/riddle/intake", body, "i" * 40)
        self.assertTrue(accepted["accepted"])
        _, leased = self.request("/v1/riddle/lease",
                                 {"owner": "runner-0", "now_tick": 13}, "w" * 40)
        self.assertEqual(bytes.fromhex(leased["payload_hex"]), payload)
        trace = {
            "schema": "nanrouter.trace.v1",
            "universe_id": leased["universe_id"],
            "source_hash": leased["source_hash"],
            "acl_digest": leased["acl_digest"],
            "source_ref": "point:9:head:17",
            "target_ref": "vector:1337",
            "nanclock_tick": 14,
        }
        _, ack = self.request("/v1/riddle/ack", {
            "event_id": leased["event_id"],
            "owner": "runner-0",
            "result_digest": "c" * 64,
            "result_generation": 0,
            "trace": trace,
        }, "w" * 40)
        self.assertTrue(ack["acknowledged"])
        _, queue = self.request("/v1/riddle/queue", token="w" * 40)
        self.assertEqual(queue["queue"]["acked"], 1)

    def test_route_resolution_fails_closed_without_signed_master_cache(self):
        with self.assertRaises(HTTPError) as err:
            self.request("/v1/riddle/routes/resolve", {"address": "nan://GM0:SC0:MC0:BS0:0:HW0:0"}, "w" * 40)
        self.assertEqual(err.exception.code, 503)

    def test_route_resolve_uses_signed_master_cache(self):
        key = b"route-cache-service-test-key-32bytes"
        cache = MasterRouteCache.empty("nan-network-0", key)
        candidate = cache.propose({
            "route_id": "bs0-root",
            "canonical_address": "nan://GM0:SC0:MC0:BS0:0:HW0:0",
            "route_kind": "network",
            "source_ref": "koyeb:bs0:0",
            "target_ref": "bootstrap:point0:head0",
            "target_head": {"namespace": 0, "universe_id": "bootstrap-0", "node_point": 0,
                            "head_index": 0, "permanence": "permanent",
                            "head_ref": "bootstrap:point0:head0"},
            "path": [{"namespace": "BS", "id": 0}],
            "permanence": "permanent",
            "source_hash": "a" * 64,
            "acl_digest": "b" * 64,
            "nanclock_tick": 1,
            "learner_id": "bootstrap-authority",
        })
        cache.commit(candidate, expected_generation=0,
                     capabilities={"nannet.route.commit"})
        cache.save_atomic(self.service.route_cache_path)
        self.service.route_key = key
        _, result = self.request(
            "/v1/riddle/routes/resolve",
            {"address": "nan://GM0:SC0:MC0:BS0:0:HW0:0"}, "w" * 40
        )
        self.assertEqual(result["packet"]["schema"], "nanrouter.micro-route.v1")
        self.assertFalse(result["live_route_commit"])

    def test_candidate_feedback_returns_to_bootstrap_in_durable_queue(self):
        _, accepted = self.request("/v1/riddle/feedback", {
            "universe_id": "overbootstrap-mc0",
            "stage": "LEARN_ROUTING",
            "base_generation": 7,
            "completed_steps": 64,
            "candidate_digest": "c" * 64,
            "acl_digest": "d" * 64,
            "nanclock_tick": 99,
        }, "w" * 40)
        self.assertTrue(accepted["accepted"])
        _, pending = self.request("/v1/riddle/feedback", token="w" * 40)
        item = pending["pending"][0]
        self.assertEqual(item["feedback"]["macrocluster"], "MC0:0")
        self.assertEqual(len(item["feedback"]["signature"]), 64)
        self.assertTrue(verify_feedback_signature(item["feedback"], b"f" * 40))
        self.assertFalse(item["feedback"]["live_map_commit"])
        _, ack = self.request("/v1/riddle/feedback/ack", {
            "feedback_id": item["feedback_id"]
        }, "w" * 40)
        self.assertTrue(ack["acknowledged"])
        _, empty = self.request("/v1/riddle/feedback", token="w" * 40)
        self.assertEqual(empty["pending"], [])

    def test_macro_plan_fails_closed_without_signed_allocator_manifest(self):
        with self.assertRaises(HTTPError) as err:
            self.request("/v1/riddle/plan", {"state": {}}, "w" * 40)
        self.assertEqual(err.exception.code, 503)


if __name__ == "__main__":
    unittest.main()
