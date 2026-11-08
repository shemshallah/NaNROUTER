"""HERMES universe lease / NANNET portal delegation regression suite."""
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from runner_riddle.hermes_leases import HermesLeaseError, HermesLeaseRegistry
from runner_riddle.http_service import RiddleService, make_handler


IDENTITY = "hermes-installation-abcdef0123456789"
OTHER = "other-installation-abcdef0123456789"
TOKEN = "p" * 48
KEY = "k" * 48


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = os.path.join(self.temp.name, "hermes.sqlite")
        self.registry = HermesLeaseRegistry(self.db, KEY.encode())

    def open(self, **kw):
        return self.registry.open(
            installation_id=IDENTITY, node_point=3,
            request_id="request-hermes-0000001", now=100, **kw)

    def test_open_idempotency_persistence_and_independent_universes(self):
        first = self.open()
        self.assertEqual(first["network_port"], "BS0:0")
        self.assertEqual(first["hardware_root"], "HW0:0")
        self.assertEqual(first["node_point"], 3)
        self.assertEqual(first["nannet_port_head"], 255)
        self.assertEqual(first["generation"], 1)
        self.assertEqual(first, self.open())
        second = self.registry.open(
            installation_id=IDENTITY, node_point=3,
            request_id="request-hermes-0000002", now=100)
        self.assertNotEqual(first["universe_id"], second["universe_id"])
        self.assertNotEqual(first["lease_id"], second["lease_id"])
        reopened = HermesLeaseRegistry(self.db, KEY.encode())
        self.assertEqual(reopened.resolve(
            installation_id=IDENTITY, receipt=first, head_index=254, now=101
        )["head_index"], 254)
        self.assertEqual(reopened.resolve(
            installation_id=IDENTITY, receipt=second, head_index=0, now=101
        )["node_point"], 3)

    def test_replay_tamper_identity_and_port_protection(self):
        first = self.open()
        for changed in (
            {**first, "node_point": 4},
            {**first, "universe_id": first["universe_id"] + 1},
            {**first, "owner_tag": 1},
            {**first, "receipt_mac": "0" * 64},
            {**first, "unexpected": True},
        ):
            with self.assertRaises(HermesLeaseError):
                self.registry.resolve(
                    installation_id=IDENTITY, receipt=changed, head_index=1, now=101)
        for head in (-1, 255, 256, True, 1.5):
            with self.assertRaises(HermesLeaseError):
                self.registry.resolve(
                    installation_id=IDENTITY, receipt=first, head_index=head, now=101)
        with self.assertRaises(HermesLeaseError):
            self.registry.resolve(
                installation_id=OTHER, receipt=first, head_index=0, now=101)
        with self.assertRaises(HermesLeaseError):
            self.registry.resolve(
                installation_id=IDENTITY, receipt=first, head_index=0,
                now=first["expires_at"])

    def test_revision_renewal_revocation_and_no_replay(self):
        first = self.open()
        new = self.registry.renew(
            installation_id=IDENTITY, receipt=first, now=105)
        self.assertEqual(new["generation"], 1)
        self.assertEqual(new["revision"], 2)
        self.assertGreater(new["expires_at"], first["expires_at"])
        with self.assertRaises(HermesLeaseError):
            self.registry.resolve(
                installation_id=IDENTITY, receipt=first, head_index=0, now=106)
        self.assertTrue(self.registry.release(
            installation_id=IDENTITY, receipt=new, now=110)["released"])
        for action in (
            lambda: self.registry.release(installation_id=IDENTITY, receipt=new, now=111),
            lambda: self.registry.renew(installation_id=IDENTITY, receipt=new, now=111),
            lambda: self.registry.resolve(installation_id=IDENTITY, receipt=new, head_index=0, now=111),
            lambda: self.open(),
        ):
            with self.assertRaises(HermesLeaseError):
                action()

    def test_invalid_values_rejected(self):
        for bad in (0, -1, 257, True, 1.0):
            with self.assertRaises(HermesLeaseError):
                self.registry.open(installation_id=IDENTITY, node_point=bad,
                                   request_id="request-hermes-newone", now=100)
        with self.assertRaises(HermesLeaseError):
            self.registry.open(installation_id=IDENTITY, node_point=3,
                               request_id="bad", now=100)
        with self.assertRaises(HermesLeaseError):
            self.open(ttl_seconds=60.0)


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {
            "RIDDLE_DATA_DIR": self.temp.name,
            "RIDDLE_INTAKE_TOKEN": "i" * 40,
            "RIDDLE_WORKER_TOKEN": "w" * 40,
            "RIDDLE_FEEDBACK_HMAC_KEY": "f" * 40,
            "RIDDLE_HERMES_DELEGATION_TOKEN": TOKEN,
            "RIDDLE_HERMES_RECEIPT_HMAC_KEY": KEY,
            # Explicit isolated test-only compatibility path; never enabled by
            # the native Koyeb runtime or a real paired HERMES installation.
            "RIDDLE_HERMES_UNPAIRED_TEST_ONLY": "1",
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

    def request(self, action, body, token=TOKEN):
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        req = Request(self.base + "/v1/hermes/leases/" + action,
                      data=json.dumps(body).encode(), headers=headers, method="POST")
        with urlopen(req, timeout=3) as res:
            return res.status, json.loads(res.read())

    def test_authenticated_end_to_end_and_scope_separation(self):
        request = {"installation_id": IDENTITY, "node_point": 3,
                   "request_id": "remote-request-0000001"}
        with self.assertRaises(HTTPError) as ex:
            self.request("open", request, token="w" * 40)
        self.assertEqual(ex.exception.code, 401)
        _, opened = self.request("open", request)
        receipt = opened["receipt"]
        _, route = self.request("resolve", {
            "installation_id": IDENTITY, "receipt": receipt, "head_index": 254})
        self.assertTrue(route["route"]["admitted"])
        self.assertFalse(route["route"]["native_execution_committed"])
        _, renewed = self.request("renew", {
            "installation_id": IDENTITY, "receipt": receipt})
        with self.assertRaises(HTTPError) as ex:
            self.request("resolve", {
                "installation_id": IDENTITY, "receipt": receipt, "head_index": 0})
        self.assertEqual(ex.exception.code, 400)
        _, released = self.request("release", {
            "installation_id": IDENTITY, "receipt": renewed["receipt"]})
        self.assertTrue(released["released"])
        with self.assertRaises(HTTPError) as ex:
            self.request("resolve", {
                "installation_id": IDENTITY, "receipt": renewed["receipt"],
                "head_index": 0})
        self.assertEqual(ex.exception.code, 400)
