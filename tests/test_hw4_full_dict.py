"""Full WordNet ZIP -> HW4 dense pair image, exact ledger, ring-owned mount."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest
from zipfile import ZipFile

from runner_riddle.hw4_full_dict import (
    HEADS, PAIRS, ROOT_BYTES, RING_OWNER, ROUTE, MountedHW4, install, verify,
)
from runner_riddle.wordnet_mirror_adapter import head_for_key, pair_id

DATA = {
    "data.noun": (
        "00001740 03 n 02 entity 0 existence 0 001 ~ 00001930 n 0000 "
        "| something that exists\n"
        "00001930 03 n 01 physical_entity 0 001 @ 00001740 n 0000 "
        "| an entity with physical existence\n"
    ),
    "data.verb": (
        "00001740 29 v 01 breathe 0 001 + 00001740 n 0101 "
        "| draw air\n"
    ),
    "data.adj": (
        "00001740 00 a 01 able 0 001 ! 00002137 a 0000 "
        "| having skill\n"
        "00002137 00 a 01 unable 0 001 ! 00001740 a 0000 "
        "| not able\n"
    ),
    "data.adv": (
        "00001740 02 r 01 ably 0 001 \\ 00001740 a 0000 "
        "| skillfully\n"
    ),
    "index.sense": (
        "entity%1:03:00:: 00001740 1 9\n"
        "physical_entity%1:03:00:: 00001930 1 2\n"
        "breathe%2:29:00:: 00001740 1 3\n"
        "able%3:00:00:: 00001740 1 4\n"
        "unable%3:00:00:: 00002137 1 3\n"
        "ably%4:02:00:: 00001740 1 0\n"
    ),
}


class FullWordNetHW4Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.source = self.base / "wn3.1.dict.zip"
        self.store = self.base / "hw4"
        with ZipFile(self.source, "w") as z:
            for name, text in DATA.items():
                z.writestr("wn3.1.dict/dict/" + name, text)

    def test_complete_build_identity_and_readonly_router_mount(self):
        first = install(self.source, self.store)
        self.assertFalse(first["reused"])
        mf = verify(self.store)
        self.assertEqual(mf["root_bytes"], ROOT_BYTES)
        self.assertEqual(ROOT_BYTES, 256 * 128 + 32640 * 256)
        self.assertEqual(mf["heads"], HEADS)
        self.assertEqual(mf["pair_count"], PAIRS)
        self.assertEqual(mf["synsets"], 6)
        self.assertEqual(mf["senses"], 6)
        self.assertEqual(mf["pointers"], 6)
        self.assertEqual(mf["unresolved_pointers"], 0)
        self.assertEqual(mf["route"], ROUTE)
        self.assertEqual(mf["ring_owner"], RING_OWNER)
        self.assertIs(mf["main_ring_writable"], False)
        with MountedHW4(self.store) as mounted:
            self.assertEqual(mounted.status()["ring_owner"], "NaNROUTER/MC0:0")
            self.assertTrue(mounted.status()["read_only"])
            self.assertEqual(mounted.status()["pair_count"], 32640)
            a = head_for_key("synset:00001740-n")
            b = head_for_key("synset:00001930-n")
            self.assertNotEqual(a, b)
            edge = mounted.pair(a, b)
            self.assertEqual(edge["pair_id"], pair_id(a, b))
            self.assertEqual(edge["forward_count"] + edge["reverse_count"], 2)
            self.assertTrue(mounted.exact("00001740-n"))
            with self.assertRaises(ValueError):
                mounted.pair(0, 0)
            with self.assertRaises(ValueError):
                mounted.exact("../secret")
        self.assertTrue(install(self.source, self.store)["reused"])

        db = self.store / mf["generation_name"] / "wordnet-exact.sqlite3"
        with sqlite3.connect(db) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM synsets").fetchone()[0], 6)
            self.assertEqual(conn.execute("SELECT count(*) FROM senses").fetchone()[0], 6)
            self.assertEqual(conn.execute("SELECT count(*) FROM pointers").fetchone()[0], 6)
            self.assertEqual(conn.execute(
                "SELECT count(*) FROM pointers WHERE symbol='!'").fetchone()[0], 2)
            self.assertEqual(conn.execute(
                "SELECT gloss FROM synsets WHERE synset='00001740-r'").fetchone()[0],
                "skillfully")
            self.assertEqual(conn.execute(
                "SELECT sense_key FROM senses WHERE synset='00001740-v'").fetchone()[0],
                "breathe%2:29:00::")

    def test_corruption_and_missing_dictionary_fail_closed(self):
        install(self.source, self.store)
        manifest = verify(self.store)
        root = self.store / manifest["generation_name"] / "wordnet-c256.root"
        with root.open("r+b") as f:
            f.seek(100000)
            f.write(b"\x7f")
        with self.assertRaisesRegex(ValueError, "integrity failure"):
            verify(self.store)
        with self.assertRaisesRegex(ValueError, "integrity failure"):
            MountedHW4(self.store)
        broken = self.base / "missing.zip"
        with ZipFile(broken, "w") as z:
            z.writestr("wn3.1.dict/dict/data.noun", DATA["data.noun"])
        with self.assertRaisesRegex(ValueError, "missing WordNet"):
            install(broken, self.base / "other")

if __name__ == "__main__":
    unittest.main()
