"""Unit checks for the bounded HW5:0 NaNNet pinned Gutenberg stream.

No live Koyeb credentials or network calls are used here. The streaming
receiver is tested against an independent small fake archive installer;
the real release's root/trigram geometry is tested in test_hw5_gutenberg.
"""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zlib

from runner_riddle.hw5_portal_stream import (
    CHUNK_BYTES, KIND, SCHEMA, SEAL_REQUEST, SEAL_WORD,
    HW5PortalStream, HW5StreamError,
)
from runner_riddle.point_fabric import Nan16DEWord, PointFrame


def make_frame(request_id: int, payload: int, *, source=0, destination=5,
               kind=KIND, far=0x7FF8, near=0xFFF8):
    return PointFrame(
        request_id=request_id, source_hw=source, destination_hw=destination,
        nanclock_tick=12, kind=kind,
        acl_digest="f" * 64,
        word=Nan16DEWord(far, near, payload),
    )


class TestHW5KoyebStream(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.blob = bytes(i % 251 for i in range(CHUNK_BYTES * 2 + 17))
        self.digest = hashlib.sha256(self.blob).hexdigest()
        self.sealed = []
        def installer(store, *, archive_path):
            self.assertEqual(Path(archive_path).read_bytes(), self.blob)
            self.sealed.append(str(store))
            return {"manifest": {
                "root_bytes": 8388608,
                "mirror_pairs": 32640,
                "corpus_bytes": 20597424,
                "books": [{"id": 11}, {"id": 84}],
                "artifacts": {
                    "gutenberg-c256.root": {"sha256": "a" * 64},
                    "all.txt": {"sha256": "b" * 64},
                },
            }}
        self.installer = installer
        self.receiver = self._new()

    def _new(self):
        return HW5PortalStream(
            self.root / "upload", self.root / "immutable",
            archive_sha256=self.digest, installer=self.installer)

    def env(self, operation, **kwargs):
        return {"schema": SCHEMA, "archive_sha256": self.digest,
                "operation": operation, **kwargs}

    def begin(self):
        return self.receiver.receive(make_frame(0, len(self.blob)),
                                     self.env("begin", size=len(self.blob)))

    def chunk(self, offset, data, *, req_id=None):
        return self.receiver.receive(
            make_frame(1 + offset // CHUNK_BYTES if req_id is None else req_id,
                       zlib.crc32(data)),
            self.env("chunk", offset=offset,
                     chunk_b64=base64.b64encode(data).decode("ascii"),
                     chunk_sha256=hashlib.sha256(data).hexdigest()))

    def test_resumption_handoff_replay_and_verified_remote_seal(self):
        self.assertEqual(self.begin()["received_bytes"], 0)
        a, b, c = (self.blob[:CHUNK_BYTES],
                   self.blob[CHUNK_BYTES:CHUNK_BYTES*2],
                   self.blob[CHUNK_BYTES*2:])
        self.assertEqual(self.chunk(0, a)["received_bytes"], CHUNK_BYTES)
        self.assertEqual(self.chunk(0, a)["result"], "duplicate")
        self.receiver = self._new()
        self.assertEqual(self.begin()["received_bytes"], CHUNK_BYTES)
        self.assertEqual(self.chunk(CHUNK_BYTES, b)["result"], "accepted")
        self.assertEqual(self.chunk(CHUNK_BYTES*2, c)["received_bytes"],
                         len(self.blob))
        result = self.receiver.receive(
            make_frame(SEAL_REQUEST, SEAL_WORD), self.env("seal"))
        self.assertEqual(result["result"], "sealed")
        self.assertTrue(result["remote_verified"])
        self.assertEqual(result["root_bytes"], 8388608)
        self.assertEqual(result["root_sha256"], "a" * 64)
        self.assertEqual(self.receiver.status()["corpus_sha256"], "b" * 64)
        self.assertEqual(len(self.sealed), 1)
        self.assertEqual(
            self.receiver.receive(make_frame(SEAL_REQUEST, SEAL_WORD),
                                  self.env("seal"))["result"], "already_sealed")
        self.assertEqual(len(self.sealed), 1)
        with self.assertRaisesRegex(HW5StreamError, "immutable"):
            self.chunk(0, a)
        self.assertEqual(len(self.sealed), 1)

    def test_wrong_route_word_and_corruption_fail_closed(self):
        for f in (make_frame(0, len(self.blob), source=1),
                  make_frame(0, len(self.blob), destination=4),
                  make_frame(0, len(self.blob), kind="other"),
                  make_frame(0, len(self.blob), far=0x7FF1),
                  make_frame(0, len(self.blob), near=0xFFF1)):
            with self.assertRaises(HW5StreamError):
                self.receiver.receive(f, self.env("begin", size=len(self.blob)))
        self.begin()
        chunk = self.blob[:CHUNK_BYTES]
        with self.assertRaises(HW5StreamError):
            self.receiver.receive(make_frame(1, 0),
                                  self.env("chunk", offset=0,
                                           chunk_b64=base64.b64encode(chunk).decode(),
                                           chunk_sha256=hashlib.sha256(chunk).hexdigest()))
        with self.assertRaises(HW5StreamError):
            self.chunk(CHUNK_BYTES, chunk)
        with self.assertRaises(HW5StreamError):
            self.receiver.receive(make_frame(SEAL_REQUEST, SEAL_WORD), self.env("seal"))
        self.chunk(0, chunk)
        with self.assertRaises(HW5StreamError):
            self.chunk(0, bytes(reversed(chunk)))
        # A physically truncated partially uploaded archive is not recovered
        # by inventing zeroed bytes or accepting an unverified seal.
        self.receiver.payload.write_bytes(b"")
        with self.assertRaises(HW5StreamError):
            self.receiver.status()

    def test_bounds_digest_and_orphan_rejections(self):
        with self.assertRaises(HW5StreamError):
            self.receiver.receive(make_frame(0, 0), self.env("begin", size=0))
        with self.assertRaises(HW5StreamError):
            self.receiver.receive(make_frame(0, len(self.blob)), {
                **self.env("begin", size=len(self.blob)), "extra": 1})
        self.begin()
        # A non-final data chunk cannot be short, even with a correct SHA
        # and word CRC: it would irreversibly misalign the resume cursor.
        with self.assertRaises(HW5StreamError):
            self.chunk(0, self.blob[:777])
        self.assertEqual(self.receiver.status()["received_bytes"], 0)
        with self.assertRaises(HW5StreamError):
            self.receiver.receive(make_frame(1, 0),
                                  self.env("chunk", offset=0,
                                           chunk_b64="*invalid*", chunk_sha256="0"*64))
        with self.assertRaises(HW5StreamError):
            self.receiver.receive(make_frame(1, 0),
                                  dict(self.env("chunk", offset=0,
                                                chunk_b64="", chunk_sha256="0"*64),
                                       archive_sha256="0"*64))
        with self.assertRaises(HW5StreamError):
            self.chunk(0, self.blob[:CHUNK_BYTES], req_id=5)

    def test_reject_cross_owner_spool(self):
        with self.assertRaises(HW5StreamError):
            HW5PortalStream(self.root / "bs0db" / "upload",
                            self.root / "immutable",
                            archive_sha256=self.digest)
        with self.assertRaises(HW5StreamError):
            HW5PortalStream(self.root / "shared",
                            self.root / "shared" / "store",
                            archive_sha256=self.digest)


if __name__ == "__main__":
    unittest.main()
