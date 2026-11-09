"""HW4 frozen WordNet matrix: generation durability, exact identity, and tampering."""
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest
from runner_riddle.hw4_reference import (
    HEAD_COUNT, HW4_ROUTE, PAIR_COUNT, ROOT_BYTES,
    install, inspect_pairs, sha256, verify,
)
from runner_riddle.wordnet_mirror_adapter import head_for_key, pair_id

NOUNS = """  Test fixture
00001740 03 n 02 entity 0 existence 0 0 | something that exists
00001930 03 n 01 physical_entity 0 1 @ 00001740 n 0000 | an entity with physical existence
00002137 03 n 01 object 0 1 @ 00001930 n 0000 | a physical object
00002345 03 n 01 artifact 0 1 @ 00002137 n 0000 | something constructed
00002500 03 n 01 fiction 0 1 ! 00002345 n 0000 | imaginary thing
"""


class FrozenHW4Tests(unittest.TestCase):
    def test_persist_recover_exact_ids_and_immutable_generation(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td)
            source=base/"data.noun"
            source.write_text(NOUNS,encoding="utf-8")
            store=base/"hw4-reference"
            first=install(source,store)
            self.assertFalse(first["reused"])
            manifest=verify(store)
            self.assertEqual(manifest["root_bytes"],8388608)
            self.assertEqual(manifest["synsets"],5)
            self.assertEqual(manifest["relations"],4)
            self.assertEqual(manifest["route"],HW4_ROUTE)
            self.assertEqual(manifest["generation"],1)
            self.assertEqual(manifest["source_sha256"],sha256(source))
            root=store/"generation-00000001"/"wordnet-c256.root"
            db=store/"generation-00000001"/"wordnet-exact.sqlite3"
            self.assertEqual(root.stat().st_size,ROOT_BYTES)
            self.assertTrue(db.exists())
            with sqlite3.connect(db) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM lemmas").fetchone()[0],6)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM synsets").fetchone()[0],5)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0],4)
                self.assertEqual(conn.execute("SELECT gloss FROM synsets WHERE synset='00002345-n'").fetchone()[0],"something constructed")
            # Source-side SHA256 head code must agree with the route adapter.
            a=head_for_key("synset:00002345-n")
            b=head_for_key("synset:00002137-n")
            self.assertNotEqual(a,b)
            probe=inspect_pairs(store,a,b)
            self.assertEqual(probe["pair_id"],pair_id(a,b))
            self.assertGreaterEqual(probe["exact_relation_rows"],1)
            self.assertEqual(probe["signed_reference"],-probe["mirror_reference"])
            repeated=install(source,store)
            self.assertTrue(repeated["reused"])
            self.assertEqual(list(store.glob("generation-*")).__len__(),1)
            source.write_text(NOUNS.replace("something constructed",
                                          "something assembled"),encoding="utf-8")
            next_generation=install(source,store)
            self.assertFalse(next_generation["reused"])
            self.assertEqual(verify(store)["generation"],2)
            self.assertEqual(verify(store,generation_name="generation-00000001")["generation"],1)
            with sqlite3.connect(store/"generation-00000001"/"wordnet-exact.sqlite3") as conn:
                self.assertEqual(conn.execute("SELECT gloss FROM synsets WHERE synset='00002345-n'").fetchone()[0],"something constructed")
            with sqlite3.connect(store/"generation-00000002"/"wordnet-exact.sqlite3") as conn:
                self.assertEqual(conn.execute("SELECT gloss FROM synsets WHERE synset='00002345-n'").fetchone()[0],"something assembled")

    def test_detect_corrupted_root_and_current_pointer(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td)
            source=base/"data.noun"
            source.write_text(NOUNS,encoding="utf-8")
            store=base/"reference"
            install(source,store)
            pointer=store/"CURRENT.json"
            original=pointer.read_text()
            p=json.loads(original)
            p["manifest_sha256"]="0"*64
            pointer.write_text(json.dumps(p))
            with self.assertRaisesRegex(ValueError,"manifest tampering"):
                verify(store)
            pointer.write_text(original)
            root=store/"generation-00000001"/"wordnet-c256.root"
            with root.open("r+b") as f:
                f.seek(300)
                f.write(b"x")
            with self.assertRaisesRegex(ValueError,"artifact integrity"):
                verify(store)

    def test_zero_data_fails_without_publishing_current(self):
        with tempfile.TemporaryDirectory() as td:
            base=Path(td)
            src=base/"empty.noun"
            src.write_text("no content")
            store=base/"reference"
            with self.assertRaises(ValueError):
                install(src,store)
            self.assertFalse((store/"CURRENT.json").exists())


if __name__=="__main__":
    unittest.main()
