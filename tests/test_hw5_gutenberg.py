"""Offline integrity and coordinate tests for Gutenberg HW5:0."""
import json
import os
import tarfile
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch
from runner_riddle.hw5_release_bootstrap import bootstrap
from runner_riddle.http_service import RiddleService, ServiceConfigError, make_handler
import mmap
from pathlib import Path
import sqlite3
import struct
from tempfile import TemporaryDirectory
import unittest
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
            with hw.MountedHW5(store) as mounted:
                status=mounted.status()
                self.assertEqual(status["route"],hw.ROUTE)
                self.assertEqual(status["unique_ordered_triples"],m["projection"]["unique_triples"])
                p=mounted.pair(ord("x"),ord("y"))
                inverse=mounted.pair(ord("y"),ord("x"))
                self.assertEqual(p["physical_offset"],inverse["physical_offset"])
                self.assertEqual(p["logical_address"],inverse["mirror_address"])
                self.assertGreater(p["adjacent_count"],0)
                self.assertEqual(mounted.pair(255,255)["adjacent_count"],0)
                query=mounted.triple(ord("x"),ord("y"),ord("x"))
                self.assertGreater(query["count"],0)
                self.assertEqual(len(query["legs"]),3)
                self.assertEqual(mounted.triple(255,254,253)["count"],0)
                with self.assertRaises(ValueError):mounted.triple(256,0,1)
            archive=root/"synthetic-hw5.tar.gz"
            with tarfile.open(archive,"w:gz") as tar:
                tar.add(store,arcname="hw5-gutenberg-reference")
            import runner_riddle.hw5_release_bootstrap as boot
            with patch.object(boot,"ARCHIVE_SHA256",hw.sha(archive)):
                installed=boot.bootstrap(root/"mounted-hw5",archive_path=archive)
                self.assertFalse(installed["reused"])
                self.assertTrue(boot.bootstrap(root/"mounted-hw5",archive_path=archive)["reused"])
            env={"RIDDLE_DATA_DIR":str(root/"router-data"),
                 "RIDDLE_HW5_STORE":str(store),
                 "RIDDLE_HW5_RING":"NaNROUTER/MC0:0",
                 "RIDDLE_FABRIC_ENABLED":"1",
                 "RIDDLE_INTAKE_TOKEN":"i"*40,
                 "RIDDLE_WORKER_TOKEN":"w"*40,
                 "RIDDLE_FEEDBACK_HMAC_KEY":"f"*40}
            with patch.dict(os.environ,env):
                service=RiddleService()
                try:
                    self.assertIsNotNone(service.hw5)
                    self.assertEqual(service.hw5.status()["books"],12)
                    self.assertEqual(service.point_fabric.point(5).monitor()["endpoint"],"HW5:0")
                    server=ThreadingHTTPServer(("127.0.0.1",0),make_handler(service))
                    worker=threading.Thread(target=server.serve_forever,daemon=True)
                    worker.start()
                    try:
                        url=f"http://127.0.0.1:{server.server_port}"
                        with self.assertRaises(HTTPError) as unauthorized:
                            urlopen(url+"/v1/riddle/hw5/status",timeout=5)
                        self.assertEqual(unauthorized.exception.code,401)
                        def query(path):
                            request=Request(url+path,headers={"Authorization":"Bearer "+"w"*40})
                            with urlopen(request,timeout=5) as reply:return json.load(reply)
                        self.assertEqual(query("/v1/riddle/hw5/status")["route"],hw.ROUTE)
                        p=query("/v1/riddle/hw5/pair?a=120&b=121")
                        self.assertEqual(p["pair_id"],hw.pair_index(120,121))
                        self.assertGreater(query("/v1/riddle/hw5/triple?a=120&b=121&c=120")["count"],0)
                        with self.assertRaises(HTTPError) as invalid:
                            query("/v1/riddle/hw5/pair?a=256&b=0")
                        self.assertEqual(invalid.exception.code,400)
                    finally:
                        server.shutdown()
                        worker.join(timeout=5)
                        server.server_close()
                finally:
                    service.close()
            with patch.dict(os.environ,dict(env,RIDDLE_HW5_RING="NaNLMind/BS0")):
                with self.assertRaisesRegex(ServiceConfigError,"main runner ring"):
                    RiddleService()
            with (gen/"all.txt").open("ab") as f:f.write(b"corrupt")
            with self.assertRaisesRegex(ValueError,"artifact mismatch"):hw.verify(store)

if __name__=="__main__":unittest.main()
