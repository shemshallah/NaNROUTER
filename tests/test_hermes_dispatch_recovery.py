"""N16T session-affinity isolation and crash/ACK reconciliation contracts."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from runner_riddle.hermes_dispatch import (
    HermesDispatchConflict, HermesDispatchJournal,
)

def row(lease=11, universe=201, generation=1):
    return {"lease_id": lease, "universe_id": universe, "generation": generation}

def wire(session_byte):
    # The journal only sees the pre-existing 16-byte opaque affinity key.
    # N16T CRC and handshake are the native guest's responsibility.
    return b"N16T" + bytes(4) + bytes([session_byte]) * 16 + bytes(12)


class N16TLeaseAffinityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "dispatch.sqlite"
        self.journal = HermesDispatchJournal(self.path)
        self.calls = []

    def request(self, *, lease=11, universe=201, generation=1, installation="alice-installed",
                head=0, dispatch_id="n16t-dispatch-00001", session_byte=4,
                exchange=None):
        def native_exchange(frame):
            self.calls.append(frame)
            return frame
        return {
            "row": row(lease, universe, generation),
            "installation_id": installation, "head_index": head,
            "dispatch_id": dispatch_id, "frame": wire(session_byte),
            "native_exchange": native_exchange if exchange is None else exchange,
        }

    def test_cross_universe_and_cross_head_session_reuse_is_rejected_before_guest(self):
        request = self.request()
        first = self.journal.dispatch(**request)
        self.assertTrue(first["n16t_native_guest_exchange"])
        self.assertEqual(len(self.calls), 1)
        for changed in (
            {"universe": 202, "lease": 12, "dispatch_id": "n16t-dispatch-00002"},
            {"installation": "bob-installed", "dispatch_id": "n16t-dispatch-00003"},
            {"head": 1, "dispatch_id": "n16t-dispatch-00004"},
            {"generation": 2, "dispatch_id": "n16t-dispatch-00005"},
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(HermesDispatchConflict):
                    self.journal.dispatch(**self.request(**changed))
        self.assertEqual(len(self.calls), 1)
        # Reopening the same SQLite journal must preserve affinity ownership.
        reopened = HermesDispatchJournal(self.path)
        with self.assertRaises(HermesDispatchConflict):
            reopened.dispatch(**self.request(
                lease=13, universe=220, dispatch_id="n16t-dispatch-00006"))
        self.assertEqual(len(self.calls), 1)
        # A different cryptographic session identifier may use another head.
        alternative = self.journal.dispatch(**self.request(
            dispatch_id="n16t-dispatch-00007", session_byte=5, head=1))
        self.assertTrue(alternative["n16t_native_guest_exchange"])
        self.assertEqual(len(self.calls), 2)

    def test_duplicate_id_recovers_previous_response_without_guest_execution(self):
        request = self.request()
        response = self.journal.dispatch(**request)
        same = HermesDispatchJournal(self.path).dispatch(**request)
        self.assertTrue(same["replayed_from_journal"])
        self.assertEqual(response["response_sha256"], same["response_sha256"])
        self.assertEqual(len(self.calls), 1)

    def test_inspection_unrecorded_completed_and_acknowledged(self):
        request = self.request()
        meta = {key: request[key] for key in (
            "row", "installation_id", "head_index", "dispatch_id")}
        self.assertEqual(self.journal.inspect(**meta)["state"], "not_recorded")
        sent = self.journal.dispatch(**request)
        completed = self.journal.inspect(**meta)
        self.assertEqual(completed["state"], "completed")
        self.assertEqual(completed["response_sha256"], sent["response_sha256"])
        with self.assertRaises(HermesDispatchConflict):
            self.journal.inspect(**{**meta, "head_index": 10})
        self.journal.acknowledge(**meta, response_sha256=sent["response_sha256"])
        self.assertEqual(HermesDispatchJournal(self.path).inspect(**meta)["state"], "acknowledged")
        self.assertEqual(len(self.calls), 1)

    def test_native_failure_is_ambiguous_and_never_silently_replayed(self):
        request = self.request(exchange=lambda _: (_ for _ in ()).throw(RuntimeError("guest lost power")))
        with self.assertRaises(RuntimeError):
            self.journal.dispatch(**request)
        meta = {key: request[key] for key in (
            "row", "installation_id", "head_index", "dispatch_id")}
        self.assertEqual(HermesDispatchJournal(self.path).inspect(**meta)["state"],
                         "pending_or_ambiguous")
        with self.assertRaises(HermesDispatchConflict):
            self.journal.dispatch(**self.request())
        self.assertEqual(self.calls, [])

    def test_corrupt_stored_response_is_never_acknowledged(self):
        request = self.request()
        sent = self.journal.dispatch(**request)
        with self.journal._db() as db:
            db.execute("UPDATE hermes_dispatch SET response=?",
                       (b"N16T" + bytes(32),))
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.journal.inspect(**{key: request[key] for key in (
                "row", "installation_id", "head_index", "dispatch_id")})
        # An ACK's reference digest must also be authenticated against the actual
        # stored response bytes, not only the digest label in a corrupted row.
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            self.journal.acknowledge(**{key: request[key] for key in (
                "row", "installation_id", "head_index", "dispatch_id")},
                response_sha256=sent["response_sha256"])


if __name__ == "__main__":
    unittest.main()
