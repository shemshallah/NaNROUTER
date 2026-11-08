"""Actual pinned NaN0S execution of HERMES native lease and N16T guests."""
from __future__ import annotations

import hashlib
import os
import tempfile
import time
import unittest
from pathlib import Path

from runner_riddle.hermes_dispatch import HermesDispatchConflict, HermesDispatchJournal
from runner_riddle.hermes_leases import HermesLeaseRegistry, HermesLeaseError
from runner_riddle.hermes_native import HermesNativeError, HermesNativeLeaseRuntime
from runner_riddle.n16t_guest import (
    N16TGuestPool, N16TGuestRuntimeError, _NaN16GuestVM,
    REQUEST_BASE, RESPONSE_PAYLOAD_BASE, SESSION_BASE,
)

HAS_NATIVE = all(os.environ.get(k) for k in (
    "NAN16_LIBRARY", "HERMES_GUEST_IMAGE", "HERMES_GUEST_LABELS",
    "RIDDLE_HERMES_NATIVE_LIBRARY_SHA256", "RIDDLE_HERMES_NATIVE_IMAGE_SHA256",
    "N16T_GUEST_IMAGE", "N16T_GUEST_LABELS",
))


@unittest.skipUnless(HAS_NATIVE, "pinned NaN0S runtime artifacts are not configured")
class HermesRealNativeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.registry = HermesLeaseRegistry(Path(self.temp.name) / "leases.sqlite", b"K" * 48)
        self.native = HermesNativeLeaseRuntime.from_env()
        self.addCleanup(self.native.close)
        self.identity = "hermes-installed-native-00000001"

    def open(self, request, identity=None, node=3):
        return self.registry.open(
            installation_id=identity or self.identity,
            node_point=node, request_id=request, now=int(time.time()))

    def admit(self, receipt, head, identity=None):
        return self.native.admit(
            self.registry, installation_id=identity or self.identity,
            receipt=receipt, head_index=head, now=int(time.time()))

    def test_native_multiple_leases_same_node_and_generational_reuse(self):
        first = self.open("native-lease-request-alpha-00001")
        second = self.open("native-lease-request-beta-00002")
        result = self.admit(first, 254)
        self.assertTrue(result["native_guest_route_admitted"])
        self.assertEqual(result["native_guest_universe_id"], first["universe_id"])
        self.assertEqual(result["native_guest_node_point"], 3)
        self.assertEqual(self.admit(second, 0)["native_guest_universe_id"], second["universe_id"])
        with self.assertRaises((HermesLeaseError, HermesNativeError)):
            self.admit({**first, "owner_tag": first["owner_tag"] + 1}, 10)
        with self.assertRaises((HermesLeaseError, HermesNativeError)):
            self.admit(first, 255)
        renewed = self.registry.renew(
            installation_id=self.identity, receipt=first, now=int(time.time()))
        self.assertTrue(self.admit(renewed, 17)["native_guest_route_admitted"])
        with self.assertRaises((HermesLeaseError, HermesNativeError)):
            self.admit(first, 17)
        self.assertTrue(self.registry.release(
            installation_id=self.identity, receipt=renewed)["released"])
        third = self.open("native-lease-request-gamma-00003")
        self.assertEqual(third["slot"], first["slot"])
        self.assertGreater(third["generation"], first["generation"])
        self.assertTrue(self.admit(third, 5)["native_guest_route_admitted"])
        self.assertTrue(self.admit(second, 254)["native_guest_route_admitted"])
        with self.assertRaises((HermesLeaseError, HermesNativeError)):
            self.admit(renewed, 5)

    def test_isolation_per_installation_and_restart_from_ledger(self):
        first = self.open("native-lease-request-rest-00001")
        alternate = "hermes-other-installation-000002"
        second = self.open("native-lease-request-rest-00002", identity=alternate)
        self.assertEqual(first["slot"], second["slot"])
        self.assertTrue(self.admit(first, 0)["native_guest_route_admitted"])
        self.assertTrue(self.admit(second, 254, identity=alternate)["native_guest_route_admitted"])
        self.native.close()
        reopened = HermesNativeLeaseRuntime.from_env()
        self.native = reopened
        self.assertTrue(self.admit(first, 9)["native_guest_route_admitted"])
        self.assertTrue(self.admit(second, 8, identity=alternate)["native_guest_route_admitted"])

    def test_real_n16t_guest_dispatch_digest_ack_and_no_silent_replay(self):
        receipt = self.open("native-lease-request-protocol-001")
        assert self.admit(receipt, 9)["native_guest_route_admitted"]
        pool = N16TGuestPool.from_env(max_sessions=4)
        self.addCleanup(pool.close)
        client = _NaN16GuestVM(
            os.environ["NAN16_LIBRARY"],
            os.environ["N16T_GUEST_IMAGE"],
            os.environ["N16T_GUEST_LABELS"])
        self.addCleanup(client.close)
        client.write_bytes(SESSION_BASE, bytes(range(1, 17)))
        client.write_bytes(RESPONSE_PAYLOAD_BASE, b"\x01\x00")
        client.call("n16_android_build", {
            1: REQUEST_BASE, 2: 1, 4: RESPONSE_PAYLOAD_BASE, 5: 2, 6: SESSION_BASE})
        self.assertEqual(client.reg(3), 0)
        frame = client.read_bytes(REQUEST_BASE, client.reg(1))
        client.call("n16_android_advance")
        self.assertEqual(client.reg(3), 0)
        with self.registry._connect() as db:
            row = self.registry._live(db, receipt, self.identity, int(time.time()))
        journal = HermesDispatchJournal(Path(self.temp.name) / "dispatch.sqlite")
        parameters = {
            "row": row, "installation_id": self.identity, "head_index": 9,
            "dispatch_id": "native-opaque-dispatch-00001",
            "frame": frame, "native_exchange": pool.exchange,
        }
        result = journal.dispatch(**parameters)
        self.assertTrue(result["n16t_native_guest_exchange"])
        response = bytes.fromhex(result["response_frame_hex"])
        self.assertEqual(hashlib.sha256(response).hexdigest(), result["response_sha256"])
        self.assertFalse(result["model_training_committed"])
        replay = journal.dispatch(**parameters)
        self.assertTrue(replay["replayed_from_journal"])
        self.assertEqual(replay["response_sha256"], result["response_sha256"])
        with self.assertRaises(HermesDispatchConflict):
            journal.dispatch(**{**parameters, "frame": frame + b"\x00"})
        ack = journal.acknowledge(
            row=row, installation_id=self.identity, head_index=9,
            dispatch_id=parameters["dispatch_id"],
            response_sha256=result["response_sha256"])
        self.assertTrue(ack["acknowledged"])
        self.assertTrue(journal.dispatch(**parameters)["acknowledged"])
        with self.assertRaises(HermesDispatchConflict):
            journal.acknowledge(
                row=row, installation_id=self.identity, head_index=9,
                dispatch_id=parameters["dispatch_id"], response_sha256="0" * 64)
        with self.assertRaises(N16TGuestRuntimeError):
            journal.dispatch(**{**parameters, "dispatch_id": "native-opaque-dispatch-00002"})
        with self.assertRaises(HermesDispatchConflict):
            journal.dispatch(**{**parameters, "dispatch_id": "native-opaque-dispatch-00002"})

    def test_pinning_fails_closed_if_guest_digest_is_wrong(self):
        with self.assertRaises(HermesNativeError):
            HermesNativeLeaseRuntime(
                os.environ["NAN16_LIBRARY"], os.environ["HERMES_GUEST_IMAGE"],
                os.environ["HERMES_GUEST_LABELS"],
                library_sha256=os.environ["RIDDLE_HERMES_NATIVE_LIBRARY_SHA256"],
                image_sha256="0" * 64)


if __name__ == "__main__":
    unittest.main()
