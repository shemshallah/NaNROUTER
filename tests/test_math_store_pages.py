"""Tests for durable MC0 universe page records.

The page table is additive to the existing ``math_schema=1`` contract and uses
the fixed 256-position universe layout: pages 0..254 are head pages and page
255 is the single NANNET0 node page, not a lane, head index, or runner slot.
"""
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from runner_riddle.math_objects import MathLeaf, canonical_json, sha256_text
from runner_riddle.math_store import (
    HEAD_PAGE_COUNT, MATH_SCHEMA_VERSION, NANNET0_PAGE_ID, PAGE_COUNT,
    PAGE_MAP_SCHEMA, PAGE_RECORD_SCHEMA, MathPageBoundsError,
    MathPageConflictError, MathPageError, MathPageUnderflowError, MathStore,
    MathStoreError, StaleGenerationError,
)
from runner_riddle.wave_store import WaveStore


class MathStorePageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bs0_path = self.tmp.name + "/bs0db.sqlite3"
        self.mc0_path = self.tmp.name + "/mc0db.sqlite3"
        self.wave = WaveStore(self.bs0_path, self.mc0_path)
        self.store = MathStore(self.bs0_path, self.mc0_path)
        self.leaf = self.make_leaf("nml:test:page:1", 1)

    def make_leaf(self, leaf_id, value):
        return self.store.put_leaf(MathLeaf(
            leaf_id=leaf_id,
            kind="scalar",
            content={"value": value},
            type={"kind": "scalar"},
            provenance={"producer": "page-test"},
        ))

    def mc0(self):
        return closing(sqlite3.connect(self.mc0_path))

    def scalar(self, sql, args=()):
        with self.mc0() as db:
            return db.execute(sql, args).fetchone()[0]

    def scalar_bs0(self, sql, args=()):
        with closing(sqlite3.connect(self.bs0_path)) as db:
            return db.execute(sql, args).fetchone()[0]

    def page_version_count(self, page_id):
        return self.scalar(
            "SELECT COUNT(*) FROM math_page_version WHERE page_id=?",
            (page_id,),
        )

    # -- pin/get/release ----------------------------------------------------

    def test_pin_get_release_roundtrip_preserves_history(self):
        page = self.store.pin_page(
            0, "runner-0", self.leaf, self.leaf.digest(), 1, tick=10,
        )
        self.assertEqual(page["page_id"], 0)
        self.assertEqual(page["page_key"], "page:000")
        self.assertEqual(page["kind"], "head")
        self.assertEqual(page["role"], "head")
        self.assertEqual(page["lane_id"], 0)
        self.assertEqual(page["leaf_id"], self.leaf.leaf_id)
        self.assertEqual(page["leaf_version"], 1)
        self.assertEqual(page["leaf_digest"], self.leaf.digest())
        self.assertEqual(page["leaf_ref"], self.leaf.leaf_id + "@v1")
        self.assertEqual(page["generation"], 1)
        self.assertEqual(page["pin_count"], 1)
        self.assertEqual(page["state"], "pinned")
        self.assertEqual(page["owner"], "runner-0")
        self.assertFalse(page["historical"])

        fetched = self.store.get_page(0)
        self.assertEqual(fetched["page_digest"], page["page_digest"])
        self.assertEqual(self.store.page_key(255), "page:255")

        historical = self.store.get_page(0, generation=1)
        self.assertTrue(historical["historical"])
        self.assertEqual(historical["pin_count"], 1)

        released = self.store.release_page(0, expected_generation=1, tick=11)
        self.assertEqual(released["generation"], 2)
        self.assertEqual(released["pin_count"], 0)
        self.assertEqual(released["state"], "released")
        self.assertEqual(released["leaf_digest"], self.leaf.digest())
        self.assertEqual(self.page_version_count(0), 2)
        self.assertEqual(
            self.store.get_page(0, generation=2)["state"], "released",
        )

    def test_pin_again_increments_count_and_stale_cas_is_rejected(self):
        self.store.pin_page(0, "runner-0", self.leaf, tick=10)
        second = self.store.pin_page(
            0, "runner-1", self.leaf, expected_generation=1, tick=11,
        )
        self.assertEqual(second["generation"], 2)
        self.assertEqual(second["pin_count"], 2)
        self.assertEqual(second["owner"], "runner-1")

        with self.assertRaises(StaleGenerationError):
            self.store.pin_page(
                0, "runner-2", self.leaf, expected_generation=1, tick=12,
            )
        current = self.store.get_page(0)
        self.assertEqual(current["generation"], 2)
        self.assertEqual(current["pin_count"], 2)
        self.assertEqual(current["owner"], "runner-1")
        self.assertEqual(self.page_version_count(0), 2)

    def test_release_underflow_does_not_mutate_or_add_a_version(self):
        self.store.pin_page(0, "runner-0", self.leaf, tick=10)
        released = self.store.release_page(0, 1, tick=11)
        self.assertEqual(released["pin_count"], 0)
        self.assertEqual(released["generation"], 2)
        with self.assertRaises(MathPageUnderflowError):
            self.store.release_page(0, 2, tick=12)
        current = self.store.get_page(0)
        self.assertEqual(current["generation"], 2)
        self.assertEqual(current["pin_count"], 0)
        self.assertEqual(current["state"], "released")
        self.assertEqual(self.page_version_count(0), 2)

    # -- bounds and NANNET0 identity ---------------------------------------

    def test_out_of_range_and_nannet0_page_roles(self):
        for bad in (-1, PAGE_COUNT, True, "0", 1.5, None):
            with self.assertRaises(MathPageBoundsError):
                self.store.get_page(bad)
            with self.assertRaises(MathPageBoundsError):
                self.store.page_key(bad)

        head = self.store.pin_page(
            254, "runner-0", self.leaf, tick=10,
        )
        self.assertEqual(head["kind"], "head")
        self.assertEqual(head["lane_id"], 254)
        self.assertEqual(head["head"], 254)
        self.assertFalse(head["nannet0"])

        nannet = self.store.pin_page(
            NANNET0_PAGE_ID, "node-0", self.leaf, tick=11,
        )
        self.assertEqual(nannet["kind"], "nannet0")
        self.assertEqual(nannet["role"], "nannet0")
        self.assertIsNone(nannet["lane_id"])
        self.assertIsNone(nannet["head"])
        self.assertTrue(nannet["nannet0"])
        self.assertEqual(nannet["page_key"], "page:255")
        self.assertEqual(self.store.page_kind(255), "nannet0")
        self.assertEqual(HEAD_PAGE_COUNT, 255)

    # -- immutable binding / atomic publication -----------------------------

    def test_leaf_binding_is_immutable_across_versions_and_digests(self):
        self.store.pin_page(2, "runner-0", self.leaf, tick=10)
        self.store.put_version(
            self.leaf.leaf_id, {"value": 2}, expected_version=1,
            expected_generation=1, tick=11,
        )

        with self.assertRaises(MathPageConflictError):
            self.store.pin_page(
                2, "runner-0", self.leaf.leaf_id + "@v2",
                expected_generation=1, tick=12,
            )
        with self.assertRaises(MathPageConflictError):
            self.store.pin_page(
                2, "runner-0", self.leaf, "f" * 64,
                expected_generation=1, tick=12,
            )
        current = self.store.get_page(2)
        self.assertEqual(current["leaf_version"], 1)
        self.assertEqual(current["leaf_digest"], self.leaf.digest())
        self.assertEqual(current["generation"], 1)
        self.assertEqual(self.page_version_count(2), 1)

    def test_wrong_digest_or_unknown_leaf_publishes_nothing(self):
        with self.assertRaises(MathPageConflictError):
            self.store.pin_page(
                9, "runner-0", self.leaf, "0" * 64, generation=0, tick=10,
            )
        with self.assertRaises(MathPageConflictError):
            self.store.pin_page(9, "runner-0", self.leaf, generation=0,
                                tick=10, digest="a" * 64)
        with self.assertRaises(MathStoreError):
            self.store.pin_page(
                10, "runner-0", "nml:missing:page:1@v1", generation=0,
                tick=10,
            )
        for page_id in (9, 10):
            with self.assertRaises(MathStoreError):
                self.store.get_page(page_id)
            self.assertEqual(self.page_version_count(page_id), 0)

    def test_atomic_publication_rolls_back_head_when_version_insert_fails(self):
        with self.mc0() as db:
            db.execute("""
                CREATE TRIGGER fail_page_version
                BEFORE INSERT ON math_page_version
                WHEN NEW.page_id = 7
                BEGIN SELECT RAISE(ABORT, 'injected page version failure'); END
            """)
            db.commit()

        with self.assertRaises(sqlite3.IntegrityError):
            self.store.pin_page(7, "runner-0", self.leaf, tick=10)
        with self.assertRaises(MathStoreError):
            self.store.get_page(7)
        self.assertEqual(self.scalar(
            "SELECT COUNT(*) FROM math_page WHERE page_id=7"
        ), 0)
        self.assertEqual(self.page_version_count(7), 0)
        # A failed publication never appends a page event either.
        self.assertEqual(self.scalar_bs0(
            "SELECT COUNT(*) FROM math_event WHERE event_type='page'"
        ), 0)

    # -- page-map digest ----------------------------------------------------

    def test_page_map_digest_is_deterministic_and_content_scoped(self):
        above = self.make_leaf("nml:test:page:2", 2)
        self.store.pin_page(5, "runner-0", self.leaf, tick=10)
        self.store.pin_page(0, "runner-0", self.leaf, tick=11)
        baseline = self.store.page_map_digest()
        self.assertEqual(baseline, self.store.page_map_digest())

        document = self.store.page_map()
        self.assertEqual(document["schema"], PAGE_MAP_SCHEMA)
        self.assertEqual(document["page_count"], PAGE_COUNT)
        self.assertEqual(document["head_page_count"], HEAD_PAGE_COUNT)
        self.assertEqual(document["nannet0_page"], NANNET0_PAGE_ID)
        self.assertEqual(len(document["pages"]), PAGE_COUNT)
        self.assertIsNone(document["pages"][1])
        self.assertEqual(document["pages"][0]["leaf_id"], self.leaf.leaf_id)
        without_digest = {
            key: value for key, value in document.items() if key != "digest"
        }
        self.assertEqual(
            document["digest"], sha256_text(canonical_json(without_digest)),
        )
        self.assertEqual(document["digest"], baseline)

        # Operational churn does not invalidate the content-bound digest.
        self.store.release_page(5, 1, tick=12)
        self.store.pin_page(
            5, "runner-1", self.leaf, expected_generation=2, tick=13,
        )
        self.store.update_page_state(
            0, "sealed", expected_generation=1, tick=14,
        )
        self.assertEqual(self.store.page_map_digest(), baseline)

        # Binding new content does.
        self.store.pin_page(1, "runner-0", above, tick=15)
        self.assertNotEqual(self.store.page_map_digest(), baseline)

        # Insertion order does not affect the map or its digest.
        with tempfile.TemporaryDirectory() as tmp:
            second = MathStore(tmp + "/bs0.sqlite3", tmp + "/mc0.sqlite3")
            second_above = second.put_leaf(MathLeaf(
                leaf_id=above.leaf_id, kind="scalar",
                content={"value": 2}, type={"kind": "scalar"},
                provenance={"producer": "page-test"},
            ))
            second_leaf = second.put_leaf(MathLeaf(
                leaf_id=self.leaf.leaf_id, kind="scalar",
                content={"value": 1}, type={"kind": "scalar"},
                provenance={"producer": "page-test"},
            ))
            second.pin_page(0, "runner-0", second_leaf, tick=10)
            second.pin_page(5, "runner-0", second_leaf, tick=11)
            second_baseline = second.page_map_digest()
            second.pin_page(1, "runner-0", second_above, tick=15)
            self.assertEqual(second.page_map_digest(),
                             self.store.page_map_digest())

    def test_page_map_digest_tracks_operator_version_not_pin_churn(self):
        first = self.store.pin_page(
            0, "runner-0", self.leaf, tick=10,
            operator_id="op:wave", operator_version=1,
            operator_digest="a" * 64,
        )
        self.assertEqual(first["operator_id"], "op:wave")
        self.assertEqual(first["operator_version"], 1)
        self.assertEqual(first["operator_digest"], "a" * 64)
        baseline = self.store.page_map_digest()

        self.store.release_page(0, 1, tick=11)
        repinned = self.store.pin_page(
            0, "runner-1", self.leaf, expected_generation=2, tick=12,
        )
        self.assertEqual(repinned["operator_id"], "op:wave")
        self.assertEqual(repinned["operator_version"], 1)
        self.assertEqual(repinned["operator_digest"], "a" * 64)
        self.assertEqual(self.store.page_map_digest(), baseline)

        self.store.pin_page(
            1, "runner-0", self.leaf, tick=13,
            operator_id="op:wave", operator_version=2,
            operator_digest="b" * 64,
        )
        self.assertNotEqual(self.store.page_map_digest(), baseline)
        with self.assertRaises(MathPageConflictError):
            self.store.pin_page(
                0, "runner-0", self.leaf, expected_generation=3, tick=14,
                operator_id="op:wave", operator_version=2,
                operator_digest="b" * 64,
            )

    # -- lifecycle state and restart ---------------------------------------

    def test_update_page_state_uses_cas_and_preserves_old_generation(self):
        self.store.pin_page(3, "runner-0", self.leaf, tick=10)
        sealed = self.store.update_page_state(
            3, "sealed", expected_generation=1, tick=11,
        )
        self.assertEqual(sealed["generation"], 2)
        self.assertEqual(sealed["state"], "sealed")
        self.assertEqual(sealed["pin_count"], 1)

        with self.assertRaises(StaleGenerationError):
            self.store.update_page_state(
                3, "evicted", expected_generation=1, tick=12,
            )
        with self.assertRaises(MathPageError):
            self.store.update_page_state(
                3, "released", expected_generation=2, tick=12,
            )
        current = self.store.get_page(3)
        self.assertEqual(current["state"], "sealed")
        self.assertEqual(current["generation"], 2)
        self.assertEqual(
            self.store.get_page(3, generation=1)["state"], "pinned",
        )
        self.assertEqual(self.page_version_count(3), 2)

    def test_pages_survive_reopen_and_list_filters_are_ordered(self):
        second_leaf = self.make_leaf("nml:test:page:3", 3)
        self.store.pin_page(4, "runner-b", self.leaf, tick=10)
        self.store.pin_page(1, "runner-a", second_leaf, tick=11)
        self.store.pin_page(2, "runner-a", self.leaf, tick=12)
        self.store.update_page_state(
            2, "sealed", expected_generation=1, tick=13,
        )

        reopened = MathStore(self.bs0_path, self.mc0_path)
        pages = reopened.list_pages()
        self.assertEqual([page["page_id"] for page in pages], [1, 2, 4])
        self.assertEqual(
            [page["page_id"] for page in reopened.list_pages(owner="runner-a")],
            [1, 2],
        )
        self.assertEqual(
            [page["page_id"] for page in reopened.list_pages(state="sealed")],
            [2],
        )
        self.assertEqual(
            [page["page_id"]
             for page in reopened.list_pages(leaf_id=self.leaf.leaf_id)],
            [2, 4],
        )
        self.assertEqual(reopened.get_page(1)["pin_count"], 1)
        self.assertEqual(reopened.get_page(1)["state"], "pinned")
        self.assertEqual(reopened.get_page(2)["state"], "sealed")

    # -- schema/spec coverage ----------------------------------------------

    def test_schema_and_spec_cover_page_records_and_keep_versions_one(self):
        spec_path = Path(__file__).resolve().parents[1] / "spec" / \
            "math-store.schema.json"
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        self.assertEqual(spec["properties"]["version"]["const"], 1)
        self.assertEqual(
            spec["properties"]["wave_schema_compatibility"]["const"], 1,
        )
        page_records = spec["properties"]["page_records"]["properties"]
        self.assertEqual(page_records["page_count"]["const"], PAGE_COUNT)
        self.assertEqual(
            page_records["head_page_count"]["const"], HEAD_PAGE_COUNT,
        )
        self.assertEqual(
            page_records["nannet0_page"]["const"], NANNET0_PAGE_ID,
        )
        self.assertEqual(
            page_records["page_map_schema"]["const"], PAGE_MAP_SCHEMA,
        )
        self.assertIn(
            "page",
            spec["properties"]["status_enums"]["properties"]["event_type"][
                "const"
            ],
        )

        table_refs = spec["properties"]["stores"]["properties"]["MC0DB"][
            "properties"]["tables"]["properties"
        ]
        self.store.pin_page(0, "runner-0", self.leaf, tick=10)
        with self.mc0() as db:
            actual = {
                name: {
                    column[1]: column[2]
                    for column in db.execute(f"PRAGMA table_info({name})")
                }
                for name in ("math_page", "math_page_version")
            }
            wave_version = db.execute(
                "SELECT version FROM wave_schema WHERE store='MC0DB'"
            ).fetchone()[0]
            math_version = db.execute(
                "SELECT version FROM math_schema WHERE store='MC0DB'"
            ).fetchone()[0]
            triggers = {
                row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger' "
                    "AND tbl_name='math_page_version'"
                )
            }
        self.assertEqual(wave_version, 1)
        self.assertEqual(math_version, MATH_SCHEMA_VERSION)
        self.assertIn("math_page_version_no_update", triggers)
        self.assertIn("math_page_version_no_delete", triggers)
        for table_name in ("math_page", "math_page_version"):
            definition = spec["$defs"][
                table_refs[table_name]["$ref"].split("/")[-1]
            ]
            self.assertEqual(
                definition["properties"]["columns"]["const"],
                actual[table_name],
            )
        self.assertEqual(
            self.store.page_map()["schema"], PAGE_MAP_SCHEMA,
        )
        self.assertEqual(PAGE_RECORD_SCHEMA,
                         "nanrouter.math-page-record.v1")

        with self.assertRaises(sqlite3.IntegrityError):
            with self.mc0() as db:
                db.execute(
                    "DELETE FROM math_page_version WHERE page_id=?",
                    (0,),
                )


if __name__ == "__main__":
    unittest.main()
