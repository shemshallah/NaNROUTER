"""No-network tests for the protected live HW5 client and nanclock binding."""
from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from runner_riddle.hw5_portal_stream import SCHEMA
from runner_riddle.hw5_release_bootstrap import ARCHIVE_SHA256
from runner_riddle.point_fabric import Nan16DEWord
from tools import hw5_live_gutenberg_stream as client


class LiveHW5ClientTests(unittest.TestCase):
    TOKEN = "x" * 48

    def test_requests_real_monotone_nanclock_before_any_HW5_frame(self):
        calls = []
        def mocked(base, token, path, body=None):
            self.assertEqual(base, client.PORTAL)
            self.assertEqual(token, self.TOKEN)
            calls.append((path, body))
            if path == "/v1/ring/clock":
                return {"schema": "nanrouter.runner-ring.v1",
                        "nanclock_tick": 4917, "active": True}
            if path == "/v1/ring/submit":
                return {"schema": SCHEMA, "endpoint": "HW5:0",
                        "archive_sha256": ARCHIVE_SHA256,
                        "received_bytes": 0, "result": "begun"}
            raise AssertionError("unexpected network endpoint")
        envelope = {"schema": SCHEMA, "archive_sha256": ARCHIVE_SHA256,
                    "operation": "begin", "size": 500}
        with patch.object(client, "_get_json", side_effect=mocked):
            receipt = client._submit(self.TOKEN, envelope, 0, 500)
        self.assertEqual(receipt["result"], "begun")
        self.assertEqual([row[0] for row in calls],
                         ["/v1/ring/clock", "/v1/ring/submit"])
        frame = calls[-1][1]["frame"]
        self.assertEqual(frame["nanclock_tick"], 4917)
        self.assertEqual(frame["source_hw"], 0)
        self.assertEqual(frame["destination_hw"], 5)
        self.assertEqual(Nan16DEWord.parse(bytes.fromhex(
            frame["word_hex"])).payload, 500)
        self.assertEqual(frame["request_id"], 0)

    def test_never_invents_local_wall_clock_tick_when_authority_denies(self):
        for payload in ({"nanclock_tick": 1, "active": False},
                        {"nanclock_tick": True, "active": True},
                        {"nanclock_tick": -1, "active": True},
                        {"nanclock_tick": 1 << 64, "active": True},
                        {"active": True},
                        {"nanclock_tick": "12", "active": True}):
            with self.subTest(payload=payload), patch.object(
                    client, "_get_json", return_value=payload):
                with self.assertRaises(client.HW5UploadError):
                    client._clock(self.TOKEN)

    def test_rejects_redirects_before_reusing_ring_credentials(self):
        redirect = client._NeverRedirectCredentials()
        with self.assertRaises(client.HW5UploadError):
            redirect.redirect_request(
                object(), None, 302, "found",
                {"Location": "https://untrusted.invalid"},
                "https://untrusted.invalid")

    def test_live_success_requires_independent_pinned_root_commitments(self):
        self.assertEqual(len(client.EXPECTED_ROOT_SHA256), 64)
        self.assertEqual(len(client.EXPECTED_CORPUS_SHA256), 64)
        self.assertEqual(client.EXPECTED_THE_TRIPLES, 245592)
        self.assertEqual(client.EXPECTED_TH_ADJACENT, 391106)
        self.assertEqual(client.EXPECTED_HT_ADJACENT, 26403)
        with TemporaryDirectory() as folder:
            archive = Path(folder) / "archive.tar.gz"
            archive.write_bytes(b"x" * 17)
            ready = {"ring_endpoint": "HW5:0", "active": True,
                     "hw5_corpus_stream": {"configured": True}}
            forged = {"remote_verified": True, "root_bytes": 8388608,
                      "mirror_pairs": 32640, "corpus_bytes": client.CORPUS_BYTES,
                      "root_sha256": "0"*64,
                      "corpus_sha256": client.EXPECTED_CORPUS_SHA256}
            with patch.object(client, "_get_json", return_value=ready), patch.object(
                    client, "_submit", side_effect=[
                        {"received_bytes": 17}, forged]):
                with self.assertRaisesRegex(client.HW5UploadError,
                                            "full integrity"):
                    client.upload(archive, token=self.TOKEN, archive_size=17)

    def test_rejects_fake_transport_delivered_response(self):
        calls = []
        def mocked(base, token, path, body=None):
            calls.append(path)
            if path == "/v1/ring/clock":
                return {"nanclock_tick": 43, "active": True}
            return {"central_status": "delivered", "endpoint": "HW5:0"}
        with patch.object(client, "_get_json", side_effect=mocked):
            with self.assertRaises(client.HW5UploadError):
                client._submit(self.TOKEN,
                               {"schema": SCHEMA,
                                "archive_sha256": ARCHIVE_SHA256,
                                "operation": "seal"},
                               0xffffffff, 0xc2560001)
        self.assertEqual(calls, ["/v1/ring/clock", "/v1/ring/submit"])


if __name__ == "__main__":
    unittest.main()
