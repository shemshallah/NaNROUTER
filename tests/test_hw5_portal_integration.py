"""Exercise the actual embedded portal ring route into the HW5 archive consumer."""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import os
from unittest.mock import patch
import unittest
import zlib

from runner_riddle.hw5_portal_stream import (
    HW5PortalStream, HW5StreamError, KIND, QUERY_KIND, SCHEMA, SEAL_WORD, SEAL_REQUEST
)
from runner_riddle.point_fabric import Nan16DEWord, PointFrame
from tests.test_hw4_portal_resident import portal_module, Authority


def frame(i, word, *, kind=KIND):
    p = PointFrame(
        request_id=i, source_hw=0, destination_hw=5, nanclock_tick=17,
        kind=kind, acl_digest="c" * 64,
        word=Nan16DEWord(0x7FF8, 0xFFF8, word),
    )
    return dict(
        request_id=p.request_id, source_hw=p.source_hw,
        destination_hw=p.destination_hw, nanclock_tick=p.nanclock_tick,
        kind=p.kind, acl_digest=p.acl_digest, word_hex=p.word.pack().hex())


class FakeMountedHW5:
    def __init__(self, path):
        self.path = path
        self.manifest = {"artifacts": {"gutenberg-c256.root": {"sha256": "a"*64}}}
    def status(self):
        return {"root_bytes": 8388608, "source_sha256": "b"*64}
    def pair(self, a, b):
        return {"a": a, "b": b, "adjacent_count": 777, "reference_only": True}
    def triple(self, a, b, c):
        return {"a": a, "b": b, "c": c, "count": 456,
                "exact_ordered": True, "reference_only": True}
    def close(self):
        pass


class TestPortalHW5Route(unittest.TestCase):
    def test_portal_hw5_route_consumes_and_seals_without_fake_fabric_ack(self):
        with TemporaryDirectory() as root:
            folder = Path(root)
            corpus = b"gutenberg route - " * 100
            digest = hashlib.sha256(corpus).hexdigest()
            count = []
            def install(store, *, archive_path):
                self.assertEqual(Path(archive_path).read_bytes(), corpus)
                count.append(1)
                return {"manifest": {
                    "root_bytes": 8388608, "mirror_pairs": 32640,
                    "corpus_bytes": 20597424, "books": [{"id":11}],
                    "artifacts": {
                        "gutenberg-c256.root": {"sha256": "a"*64},
                        "all.txt": {"sha256": "b"*64},
                    },
                }}
            portal = portal_module()
            env = {"RIDDLE_HW5_STORE": str(folder/"store"),
                   "RIDDLE_HW5_STREAM_DIR": str(folder/"incoming")}
            with patch.dict(os.environ, env), patch.object(
                    portal, "MountedHW5", FakeMountedHW5):
                node = portal.PortalRingNode(
                    Authority(), token="f"*40, endpoint="http://127.0.0.1:1",
                    database=str(folder/"ring.sqlite"))
                # Inject exact independent test release digest and fake installer.
                node.hw5_stream = HW5PortalStream(
                    folder/"incoming", folder/"store",
                    archive_sha256=digest, installer=install)
                with node._lock:
                    node._activate_locked({"lease_id": "test", "epoch": 1})
                self.assertEqual(node.status()["ring_endpoint"], "HW5:0")
                self.assertTrue(node.status()["active"])
                common = {"schema": SCHEMA, "archive_sha256": digest}
                begin = node.submit({
                    "frame": frame(0,len(corpus)),
                    "hw5_corpus": dict(common, operation="begin", size=len(corpus)),
                })
                self.assertEqual(begin["endpoint"], "HW5:0")
                self.assertEqual(begin["central_status"], "hw5_object_consumed")
                self.assertFalse(begin["remote_verified"])
                self.assertEqual(node.fabric.monitor()["queued"], 0)
                chunk = node.submit({
                    "frame": frame(1,zlib.crc32(corpus)),
                    "hw5_corpus": dict(
                        common, operation="chunk", offset=0,
                        chunk_b64=base64.b64encode(corpus).decode("ascii"),
                        chunk_sha256=hashlib.sha256(corpus).hexdigest()),
                })
                self.assertEqual(chunk["received_bytes"], len(corpus))
                seal = node.submit({
                    "frame": frame(SEAL_REQUEST,SEAL_WORD),
                    "hw5_corpus": dict(common, operation="seal"),
                })
                self.assertTrue(seal["remote_verified"])
                self.assertEqual(seal["root_sha256"], "a"*64)
                self.assertEqual(node.status()["hw5_corpus_stream"]["root_sha256"], "a"*64)
                self.assertTrue(node.status()["hw5_gutenberg_reference"]["mounted"])
                self.assertEqual(count,[1])
                self.assertEqual(node.fabric.monitor()["queued"],0)
                # Read back the actual head bytes using only the 32-bit
                # NaN16DE word on the same authenticated point route.
                result = node.submit({
                    "frame": frame(2,(ord("t") << 16) | (ord("h") << 8) | ord("e"),
                                   kind=QUERY_KIND)
                })
                self.assertEqual(result["query"], "triple")
                self.assertEqual(result["result"]["count"], 456)
                self.assertTrue(result["result"]["exact_ordered"])
                self.assertEqual(result["root_sha256"], "a"*64)
                pair_result = node.submit({
                    "frame": frame(1,(ord("t") << 16) | (ord("h") << 8),
                                   kind=QUERY_KIND)
                })
                self.assertEqual(pair_result["result"]["adjacent_count"], 777)
                self.assertEqual(node.fabric.monitor()["queued"],0)
                # An unrelated frame must never smuggle a corpus sidecar.
                with self.assertRaises(portal.PortalRingError):
                    node.submit({
                        "frame": frame(55,123,kind="ordinary"),
                        "hw5_corpus": dict(common, operation="seal"),
                    })

    def test_no_import_without_active_ring_or_mounted_store(self):
        with TemporaryDirectory() as root:
            portal = portal_module()
            folder = Path(root)
            with patch.dict(os.environ, {}, clear=True):
                node = portal.PortalRingNode(
                    Authority(), token="a"*40,
                    endpoint="http://127.0.0.1:1",
                    database=str(folder/"ring.sqlite"))
                self.assertFalse(node.status()["hw5_corpus_stream"]["configured"])
                self.assertFalse(node.status()["hw5_gutenberg_reference"]["mounted"])
                # No destination bypass: the read-only unconfigured status
                # must never claim the corpus arrived at HW5:0.


if __name__ == "__main__":
    unittest.main()
