"""Offline integrity and coordinate tests for Gutenberg HW5:0."""
import json
import mmap
from pathlib import Path
import sqlite3
import struct
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from runner_riddle import hw5_gutenberg as hw

class HW5(unittest.TestCase):
    def test_pair_bijection(self):
        ids={hw.pair_index(a,b) for a in range(256) for b in range(a+1,256)}
        self.assertEqual(len(ids),32640)
        self.assertEqual(min(ids),1)
        self.assertEqual(max(ids),32640)
        self.assertEqual(hw.pair_index(254,255),32640)
        self.assertEqual(hw.HEADS*hw.HEAD_BYTES+hw.PAIRS*hw.PAIR_BYTES,8388608)
    def test_bad_source(self):
        for raw in (b"abc",b"*** START OF THE PROJECT GUTENBERG EBOOK X ***\nabc"):
            with self.assertRaises(ValueError): hw.clean(raw)
        body=b"abca"*600
        self.assertEqual(hw.clean(b"*** START OF THE PROJECT GUTENBERG EBOOK X ***\r\n"+body+
                                  b"\r\n*** END OF THE PROJECT GUTENBERG EBOOK X ***\n"),body+b"\n")
    def test_build_verify_and_readonly_contract(self):
        with TemporaryDirectory() as folder:
            root=Path(folder)
            src=root/"src"
            src.mkdir()
            entries=[]
            for i in range(12):
                id_=10000+i
                body=("xyxz " * 750 + "naive cafe " * 90 + str(i)).encode()
                raw=b"*** START OF THE PROJECT GUTENBERG EBOOK TEST ***\n"+body+b"\n*** END OF THE PROJECT GUTENBERG EBOOK TEST ***\n"
                text=hw.clean(raw)
                (src/f"pg{id_}.txt").write_bytes(raw)
                entries.append(dict(id=id_,title=f"Fixture {i}",author="Test",url="https://example.invalid",
                                    raw_sha256=hw.digest(raw),text_sha256=hw.digest(text),bytes=len(text)))
            (src/"source_manifest.json").write_text(json.dumps({
                "schema":"nanrouter.hw5-source-ledger.v1","books":entries,"corpus_bytes":sum(e["bytes"] for e in entries)}))
            store=root/"hw5"
            with patch.object(hw,"MIN_BYTES",10000), patch.object(hw,"MAX_BYTES",1000000):
                m=hw.build(src,store)
                self.assertEqual(hw.verify(store),m)
            self.assertEqual(m["mirror_pairs"],32640)
            self.assertEqual(m["canonical_cells"],32896)
            self.assertEqual(m["route"],hw.ROUTE)
            self.assertTrue(m["reference_only"])
            self.assertFalse(m["main_ring_writable"])
            self.assertEqual(m["projection"]["adjacent_transitions"],m["corpus_bytes"]-12)
            self.assertEqual(m["projection"]["triple_count"],m["corpus_bytes"]-24)
            gen=store/"generation-00000001"
            with sqlite3.connect("file:"+str((gen/"gutenberg-triples.sqlite3").resolve())+"?mode=ro&immutable=1",uri=True) as db:
                n=db.execute("SELECT n FROM triples WHERE a=120 AND b=121 AND c=120").fetchone()
                self.assertIsNotNone(n)
                self.assertGreater(n[0],0)
            with (gen/"gutenberg-c256.root").open("rb") as f:
                base=32768+(hw.pair_index(ord("x"),ord("y"))-1)*256
                f.seek(base)
                header=struct.unpack("<IIII",f.read(16))
                self.assertGreater(header[0],0)
                self.assertGreater(header[1],0)
                self.assertEqual(header[2]&1,1)
                f.seek(255*128)
                self.assertEqual(f.read(128),bytes(128))
            with (gen/"all.txt").open("ab") as f:f.write(b"corrupt")
            with self.assertRaisesRegex(ValueError,"artifact mismatch"):hw.verify(store)

if __name__=="__main__":unittest.main()
