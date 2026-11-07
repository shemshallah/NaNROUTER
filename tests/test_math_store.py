"""Tests for the additive math persistence layer.

These tests intentionally run MathStore beside WaveStore in the same SQLite
files.  They cover the P1/P6 storage contract: schema coexistence, immutable
content and versions, content-addressed payloads, compare-and-swap current
pointers, rollback events, reference errors for missing/corrupt payloads,
append-only evidence, disposable-cache reload, and 2 MiB chunking.
"""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from runner_riddle.math_objects import (
    MathAdmission, MathCandidate, MathFunction, MathLeaf, MathRule,
    candidate_id_for,
)
from runner_riddle.math_store import (
    DEFAULT_CHUNK_BYTES, MATH_SCHEMA_VERSION, MathConflictError,
    MathReferenceError, MathSchemaError, MathStore, MathStoreError,
    StaleGenerationError,
)
from runner_riddle.wave_store import WaveStore


class MathStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bs0_path = self.tmp.name + "/bs0db.sqlite3"
        self.mc0_path = self.tmp.name + "/mc0db.sqlite3"
        # Create the wave stores first: the math layer must be additive to an
        # existing, already-owned BS0DB/MC0DB pair.
        self.wave = WaveStore(self.bs0_path, self.mc0_path)
        self.wave.enqueue_job(
            "wave-job-1", universe_id="universe-0", generation=1,
            operator_digest="a" * 64, payload={"step": 1}, nanclock_tick=5,
        )
        self.store = MathStore(self.bs0_path, self.mc0_path)
        self.leaf_id = "nml:test:leaf:1"

    # -- helpers ------------------------------------------------------------

    def make_leaf(self, *, leaf_id=None, content=None, provenance=None,
                  kind="scalar"):
        return MathLeaf(
            leaf_id=self.leaf_id if leaf_id is None else leaf_id,
            kind=kind,
            content={"value": 7} if content is None else content,
            type={"kind": kind},
            provenance=(
                {"producer": "test"} if provenance is None else provenance
            ),
        )

    def make_function(self, *, version=1, signature=None, **kwargs):
        return MathFunction(
            function_id="math.vector.dot.v1",
            version=version,
            signature=(
                {"inputs": ["vector", "vector"], "output": "scalar"}
                if signature is None else signature
            ),
            semantics={"operation": "dot"},
            proof_status="stated",
            **kwargs,
        )

    def make_rule(self, *, version=1, contract=None, status="proposed",
                  **kwargs):
        return MathRule(
            rule_id="math.rule.assoc.1",
            version=version,
            level=1,
            contract={"claim": "associative"} if contract is None else contract,
            status=status,
            **kwargs,
        )

    def make_candidate(self, *, candidate_id=None, inputs=None, **kwargs):
        input_items = (
            ({"leaf": self.leaf_id},) if inputs is None else tuple(inputs)
        )
        if candidate_id is None:
            candidate_id = candidate_id_for(
                "snapshot-1", input_items, "math.vector.dot.v1", 1
            )
        return MathCandidate(
            candidate_id=candidate_id,
            inputs=input_items,
            function_id="math.vector.dot.v1",
            function_version=1,
            snapshot_id="snapshot-1",
            **kwargs,
        )

    def make_admission(self, *, admission_id="adm:test-1", verdict="VALID",
                       **kwargs):
        return MathAdmission(
            admission_id=admission_id,
            candidate_id="cnd:test-1",
            verdict=verdict,
            snapshot_id="snapshot-1",
            preflight_digest="b" * 64,
            **kwargs,
        )

    def payload_ref(self, leaf_id, version=None):
        query = ("SELECT payload_ref, content_digest FROM math_leaf_version "
                 "WHERE leaf_id=?")
        args = [leaf_id]
        if version is not None:
            query += " AND version=?"
            args.append(version)
        else:
            query += " ORDER BY version DESC LIMIT 1"
        with closing(sqlite3.connect(self.mc0_path)) as db:
            return db.execute(query, args).fetchone()

    def scalar(self, sql, args=()):
        with closing(sqlite3.connect(self.bs0_path)) as db:
            return db.execute(sql, args).fetchone()[0]

    def scalar_mc0(self, sql, args=()):
        with closing(sqlite3.connect(self.mc0_path)) as db:
            return db.execute(sql, args).fetchone()[0]

    # -- schema coexistence ------------------------------------------------

    def test_schema_is_additive_and_wave_schema_stays_one(self):
        mc0_tables = {
            "wave_schema", "wave_job", "wave_lease", "wave_operator",
            "wave_capability", "math_schema", "math_leaf",
            "math_leaf_version", "math_function", "math_function_version",
            "math_rule", "math_rule_version", "math_relation",
            "math_relation_version", "math_candidate", "math_admission",
            "math_mapping", "math_preflight_cache",
        }
        bs0_tables = {
            "wave_schema", "wave_trace", "wave_seal", "wave_signature",
            "wave_feedback", "math_schema", "math_payload", "math_event",
            "math_certificate",
        }
        for path, expected in ((self.mc0_path, mc0_tables),
                               (self.bs0_path, bs0_tables)):
            with closing(sqlite3.connect(path)) as db:
                found = {
                    row[0] for row in db.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
            self.assertTrue(expected.issubset(found), expected - found)

        with closing(sqlite3.connect(self.mc0_path)) as db:
            wave_version = db.execute(
                "SELECT version FROM wave_schema WHERE store='MC0DB'"
            ).fetchone()[0]
            math_version = db.execute(
                "SELECT version FROM math_schema WHERE store='MC0DB'"
            ).fetchone()[0]
            user_version = db.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(wave_version, 1)
        self.assertEqual(math_version, MATH_SCHEMA_VERSION)
        self.assertEqual(user_version, 1)

        with closing(sqlite3.connect(self.bs0_path)) as db:
            self.assertEqual(db.execute(
                "SELECT version FROM wave_schema WHERE store='BS0DB'"
            ).fetchone()[0], 1)
            self.assertEqual(db.execute(
                "SELECT version FROM math_schema WHERE store='BS0DB'"
            ).fetchone()[0], MATH_SCHEMA_VERSION)

        # The math layer never rewrites WaveStore state; wave operations still
        # work after MathStore initialization and the math health is green.
        job = self.wave.enqueue_job(
            "wave-job-2", universe_id="universe-0", generation=1,
            operator_digest="a" * 64, payload={"step": 2}, nanclock_tick=6,
        )
        self.assertEqual(job["state"], "queued")
        self.assertEqual(self.wave.stats()["schema_version"], 1)
        health = self.store.math_health()
        self.assertEqual(health["status"], "green")
        self.assertEqual(health["wave_schema_versions"],
                         {"BS0DB": 1, "MC0DB": 1})
        self.assertTrue(health["wave_schema_untouched"])

    def test_math_store_can_initialize_before_wave_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            bs0_path = tmp + "/bs0.sqlite3"
            mc0_path = tmp + "/mc0.sqlite3"
            math = MathStore(bs0_path, mc0_path)
            leaf = math.put_leaf(self.make_leaf())
            # WaveStore is free to initialize afterward; it owns wave_schema.
            wave = WaveStore(bs0_path, mc0_path)
            wave.enqueue_job(
                "wave-job-after", universe_id="universe-0", generation=1,
                operator_digest="a" * 64, payload={"ok": True},
            )
            self.assertEqual(math.get_leaf(leaf.leaf_id).digest(), leaf.digest())
            with closing(sqlite3.connect(mc0_path)) as db:
                self.assertEqual(db.execute(
                    "SELECT version FROM wave_schema WHERE store='MC0DB'"
                ).fetchone()[0], 1)
                self.assertEqual(db.execute(
                    "SELECT version FROM math_schema WHERE store='MC0DB'"
                ).fetchone()[0], MATH_SCHEMA_VERSION)

    def test_unsupported_math_schema_version_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            bs0_path = tmp + "/bs0.sqlite3"
            mc0_path = tmp + "/mc0.sqlite3"
            for path, store in ((bs0_path, "BS0DB"), (mc0_path, "MC0DB")):
                with closing(sqlite3.connect(path)) as db:
                    db.execute("""
                        CREATE TABLE math_schema (
                            store TEXT PRIMARY KEY,
                            version INTEGER NOT NULL,
                            applied_tick INTEGER NOT NULL DEFAULT 0
                        )
                    """)
                    db.execute(
                        "INSERT INTO math_schema(store, version, applied_tick) "
                        "VALUES (?, 2, 0)", (store,),
                    )
                    db.commit()
            with self.assertRaises(MathSchemaError):
                MathStore(bs0_path, mc0_path)

    def test_mapping_recovery_uses_immutable_version_rows(self):
        self.store.put_leaf(self.make_leaf(content={"value": 1}))
        self.store.put_version(
            self.leaf_id, {"value": 2}, expected_version=1,
            expected_generation=1,
        )
        mapping_id = "leaf:" + self.leaf_id
        with closing(sqlite3.connect(self.mc0_path)) as db:
            db.execute("DELETE FROM math_mapping WHERE mapping_id=?",
                       (mapping_id,))
            db.commit()
        with self.assertRaises(MathReferenceError):
            self.store.get_mapping(mapping_id)

        latest = self.store.list_versions(self.leaf_id)[-1]
        recovered = self.store.set_mapping(
            mapping_id, object_type="leaf", object_id=self.leaf_id,
            version=latest["version"], digest=latest["leaf_digest"],
            expected_version=0, expected_generation=0, tick=30,
        )
        self.assertEqual(recovered["current_version"], latest["version"])
        self.assertEqual(recovered["generation"], 1)
        self.assertEqual(self.store.resolve("map:" + mapping_id).content,
                         {"value": 2})

    def test_spec_matches_implemented_table_contract(self):
        spec_path = Path(__file__).resolve().parents[1] / "spec" / \
            "math-store.schema.json"
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        self.assertEqual(spec["properties"]["schema"]["const"],
                         "nanrouter.math-store.v1")
        self.assertEqual(spec["properties"]["version"]["const"], 1)
        self.assertEqual(
            spec["properties"]["wave_schema_compatibility"]["const"], 1
        )
        chunking = spec["properties"]["payload_chunking"]
        self.assertEqual(chunking["properties"]["chunk_bytes"]["const"],
                         DEFAULT_CHUNK_BYTES)
        self.assertEqual(chunking["properties"]["max_payload_bytes"]["const"],
                         2 * 1024 * 1024)
        for store, path in (("BS0DB", self.bs0_path),
                            ("MC0DB", self.mc0_path)):
            table_refs = spec["properties"]["stores"]["properties"][store][
                "properties"]["tables"]["properties"
            ]
            with closing(sqlite3.connect(path)) as db:
                actual = {
                    row[0]: {
                        column[1]: column[2]
                        for column in db.execute(f"PRAGMA table_info({row[0]})")
                    }
                    for row in db.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
            for table_name, ref in table_refs.items():
                definition = spec["$defs"][ref["$ref"].split("/")[-1]]
                columns = definition["properties"]["columns"]["const"]
                required_fields = definition["properties"][
                    "required_fields"
                ]["const"]
                self.assertIn(table_name, actual)
                self.assertEqual(columns, actual[table_name])
                self.assertTrue(set(required_fields) <= set(columns))

    # -- immutable leaves and content addressing ---------------------------

    def test_leaf_versions_are_immutable_and_old_versions_recoverable(self):
        leaf = self.make_leaf(content={"value": 1})
        stored = self.store.put_leaf(leaf)
        self.assertEqual(stored.version, 1)
        self.assertEqual(stored.content, {"value": 1})

        version_two = self.store.put_version(
            leaf.leaf_id, {"value": 2},
            expected_version=1, expected_generation=1, tick=10,
        )
        self.assertEqual(version_two.version, 2)
        self.assertEqual(version_two.content, {"value": 2})
        self.assertEqual(self.store.get_leaf(leaf.leaf_id).version, 2)
        self.assertEqual(
            self.store.get_leaf(leaf.leaf_id, 1).content, {"value": 1}
        )
        self.assertEqual(
            self.store.resolve(leaf.leaf_id, required_version=1).content,
            {"value": 1},
        )
        self.assertEqual(
            self.store.resolve(leaf.leaf_id + "@1").content, {"value": 1}
        )

        versions = self.store.list_versions(leaf.leaf_id)
        self.assertEqual([entry["version"] for entry in versions], [1, 2])
        self.assertEqual([entry["current"] for entry in versions],
                         [False, True])
        self.assertEqual(versions[0]["leaf_digest"], leaf.digest())

        # Version rows are immutable even through raw SQL.
        with closing(sqlite3.connect(self.mc0_path)) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    "UPDATE math_leaf_version SET leaf_json='{}' "
                    "WHERE leaf_id=? AND version=1", (leaf.leaf_id,)
                )
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    "DELETE FROM math_leaf_version "
                    "WHERE leaf_id=? AND version=1", (leaf.leaf_id,)
                )

        # Re-putting a different version-1 document is a conflict.
        with self.assertRaises(MathConflictError):
            self.store.put_leaf(self.make_leaf(content={"value": 99}))

    def test_same_content_different_leaves_share_content_payload(self):
        first = self.make_leaf(
            leaf_id="nml:test:leaf:a", content={"vector": [1, 2, 3]},
            provenance={"producer": "producer-a"},
        )
        second = self.make_leaf(
            leaf_id="nml:test:leaf:b", content={"vector": [1, 2, 3]},
            provenance={"producer": "producer-b"},
        )
        stored_a = self.store.put_leaf(first)
        stored_b = self.store.put_leaf(second)
        self.assertNotEqual(stored_a.digest(), stored_b.digest())

        ref_a = self.payload_ref("nml:test:leaf:a")[0]
        ref_b = self.payload_ref("nml:test:leaf:b")[0]
        self.assertEqual(ref_a, ref_b)
        with closing(sqlite3.connect(self.bs0_path)) as db:
            rows = db.execute(
                "SELECT COUNT(*) FROM math_payload WHERE digest=?", (ref_a,)
            ).fetchone()[0]
        self.assertEqual(rows, 1)
        self.assertEqual(self.store.get_leaf("nml:test:leaf:a").content,
                         self.store.get_leaf("nml:test:leaf:b").content)

    def test_cas_rejects_stale_version_and_generation(self):
        self.store.put_leaf(self.make_leaf(content={"value": 1}))
        self.store.put_version(
            self.leaf_id, {"value": 2}, expected_version=1,
            expected_generation=1,
        )

        with self.assertRaises(StaleGenerationError):
            self.store.put_version(
                self.leaf_id, {"value": 3}, expected_version=1,
                expected_generation=1,
            )
        with self.assertRaises(StaleGenerationError):
            self.store.put_version(
                self.leaf_id, {"value": 3}, expected_version=2,
                expected_generation=1,
            )
        self.assertEqual(
            [entry["version"] for entry in self.store.list_versions(self.leaf_id)],
            [1, 2],
        )
        head = self.store.get_leaf_meta(self.leaf_id)
        self.assertEqual((head["current_version"], head["generation"]), (2, 2))

        third = self.store.put_version(
            self.leaf_id, {"value": 3}, expected_version=2,
            expected_generation=2,
        )
        self.assertEqual(third.version, 3)
        self.assertEqual(self.store.get_leaf_meta(self.leaf_id)["generation"], 3)

        # A new leaf cannot claim a non-zero base generation.
        with self.assertRaises(StaleGenerationError):
            self.store.put_leaf(
                self.make_leaf(leaf_id="nml:test:leaf:new"),
                expected_generation=4,
            )

    # -- mapping rollback ---------------------------------------------------

    def test_rollback_is_a_new_mapping_event_and_is_recoverable(self):
        self.store.put_leaf(self.make_leaf(content={"value": 1}))
        self.store.put_version(
            self.leaf_id, {"value": 2}, expected_version=1,
            expected_generation=1,
        )
        mapping_id = "leaf:" + self.leaf_id
        mapping = self.store.get_mapping(mapping_id)
        self.assertEqual((mapping["current_version"], mapping["generation"]),
                         (2, 2))
        event_count = len(self.store.list_events())

        rolled_back = self.store.rollback_mapping(
            mapping_id, 1, expected_version=2, expected_generation=2, tick=20,
        )
        self.assertEqual(rolled_back["current_version"], 1)
        self.assertEqual(rolled_back["generation"], 3)
        self.assertEqual(rolled_back["status"], "rolled_back")
        self.assertEqual(
            self.store.resolve("map:" + mapping_id).version, 1
        )
        # The leaf head itself is not destructively rewritten.
        self.assertEqual(self.store.get_leaf(self.leaf_id).version, 2)
        self.assertEqual(self.store.get_leaf(self.leaf_id, 2).content,
                         {"value": 2})

        events = self.store.list_events()
        self.assertEqual(len(events), event_count + 1)
        rollback_event = events[-1]
        self.assertEqual(rollback_event["event_type"], "rollback")
        self.assertEqual(rollback_event["object_type"], "mapping")
        self.assertEqual(rollback_event["object_id"], mapping_id)
        self.assertEqual(rollback_event["version"], 1)
        self.assertEqual(rollback_event["generation"], 3)
        self.assertEqual(rollback_event["payload"]["previous_version"], 2)
        self.assertEqual(rollback_event["payload"]["target_version"], 1)

        # Repeating the same rollback is idempotent and does not add evidence.
        replay = self.store.rollback_mapping(
            mapping_id, 1, expected_version=1, expected_generation=3,
        )
        self.assertEqual(replay["generation"], 3)
        self.assertEqual(len(self.store.list_events()), event_count + 1)

        with self.assertRaises(StaleGenerationError):
            self.store.rollback_mapping(
                mapping_id, 2, expected_version=2, expected_generation=2,
            )

        republished = self.store.set_mapping(
            mapping_id, object_type="leaf", object_id=self.leaf_id,
            version=2, digest=self.store.get_leaf(self.leaf_id, 2).digest(),
            expected_version=1, expected_generation=3,
        )
        self.assertEqual((republished["current_version"],
                          republished["generation"]), (2, 4))
        self.assertEqual(self.store.resolve("map:" + mapping_id).version, 2)

    # -- reference and digest errors ---------------------------------------

    def test_missing_payload_is_a_reference_error_not_null(self):
        leaf = self.store.put_leaf(self.make_leaf(content={"value": 11}))
        payload_ref, _ = self.payload_ref(leaf.leaf_id)
        with closing(sqlite3.connect(self.bs0_path)) as db:
            db.execute("DROP TRIGGER math_payload_no_delete")
            db.execute("DELETE FROM math_payload WHERE digest=?", (payload_ref,))
            db.commit()

        with self.assertRaises(MathReferenceError):
            self.store.get_leaf(leaf.leaf_id)
        with self.assertRaises(MathReferenceError):
            self.store.get_payload(payload_ref)
        health = self.store.math_health()
        self.assertEqual(health["status"], "red")
        self.assertIn(payload_ref, health["missing_payload_refs"])

    def test_corrupt_payload_is_a_reference_error_not_zero(self):
        leaf = self.store.put_leaf(self.make_leaf(content={"value": 12}))
        payload_ref, _ = self.payload_ref(leaf.leaf_id)
        with closing(sqlite3.connect(self.bs0_path)) as db:
            row = db.execute(
                "SELECT blob FROM math_payload WHERE digest=? AND chunk_index=0",
                (payload_ref,),
            ).fetchone()
            corrupted = bytes(row[0])
            corrupted = bytes([corrupted[0] ^ 0xFF]) + corrupted[1:]
            db.execute("DROP TRIGGER math_payload_no_update")
            db.execute(
                "UPDATE math_payload SET blob=? WHERE digest=? AND chunk_index=0",
                (corrupted, payload_ref),
            )
            db.commit()

        with self.assertRaises(MathReferenceError):
            self.store.get_leaf(leaf.leaf_id)
        with self.assertRaises(MathReferenceError):
            self.store.get_payload(payload_ref)
        health = self.store.math_health()
        self.assertEqual(health["status"], "red")
        self.assertIn(payload_ref, health["corrupt_payloads"])

    def test_tampered_version_row_fails_digest_verification(self):
        leaf = self.store.put_leaf(self.make_leaf(content={"value": 13}))
        with closing(sqlite3.connect(self.mc0_path)) as db:
            db.execute("DROP TRIGGER math_leaf_version_no_update")
            db.execute(
                "UPDATE math_leaf_version SET leaf_digest=? "
                "WHERE leaf_id=? AND version=1",
                ("f" * 64, leaf.leaf_id),
            )
            db.commit()
        with self.assertRaises(MathReferenceError):
            self.store.get_leaf(leaf.leaf_id)
        with self.assertRaises(MathReferenceError):
            self.store.list_versions(leaf.leaf_id)

    # -- append-only evidence ----------------------------------------------

    def test_events_and_payloads_are_append_only(self):
        propose = self.store.append_event(
            "propose", "candidate", "cnd:event-test", version=1,
            digest="a" * 64, payload={"snapshot_id": "snapshot-1"}, tick=10,
        )
        commit = self.store.append_event(
            "commit", "leaf", self.leaf_id, version=1, generation=1,
            digest="b" * 64, tick=11,
        )
        self.assertNotEqual(propose["event_id"], commit["event_id"])
        commits = self.store.list_events(event_type="commit")
        self.assertEqual(len(commits), 1)
        self.assertEqual(commits[0]["payload"], {})
        proposed = self.store.list_events(object_type="candidate")
        self.assertEqual(proposed[0]["payload"], {"snapshot_id": "snapshot-1"})

        with closing(sqlite3.connect(self.bs0_path)) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    "UPDATE math_event SET payload_json='{}' WHERE event_seq=?",
                    (commit["event_seq"],),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    "DELETE FROM math_event WHERE event_seq=?",
                    (commit["event_seq"],),
                )

        payload = self.store.put_payload(b"append-only", encoding="binary")
        with closing(sqlite3.connect(self.bs0_path)) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    "UPDATE math_payload SET blob=? WHERE digest=?",
                    (b"changed", payload["digest"]),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    "DELETE FROM math_payload WHERE digest=?",
                    (payload["digest"],),
                )

    # -- cache reload and leaf recovery ------------------------------------

    def test_cache_reload_and_invalidation(self):
        candidate = self.store.put_candidate(self.make_candidate())
        cache_key = "preflight:" + candidate.candidate_id
        self.store.put_preflight_cache(
            cache_key, snapshot_id="snapshot-1",
            candidate_id=candidate.candidate_id, verdict="VALID",
            result={"verdict": "VALID", "checks": 3},
            invalidation_digest="c" * 64, expires_tick=100, tick=10,
        )

        reloaded = MathStore(self.bs0_path, self.mc0_path)
        hit = reloaded.get_preflight_cache(
            cache_key, invalidation_digest="c" * 64, now_tick=50,
        )
        self.assertIsNotNone(hit)
        self.assertTrue(hit["hit"])
        self.assertEqual(hit["result"], {"verdict": "VALID", "checks": 3})
        self.assertIsNone(reloaded.get_preflight_cache(
            cache_key, invalidation_digest="d" * 64, now_tick=50,
        ))
        self.assertIsNone(reloaded.get_preflight_cache(
            cache_key, invalidation_digest="c" * 64, now_tick=101,
        ))

        updated = reloaded.put_preflight_cache(
            cache_key, snapshot_id="snapshot-1",
            candidate_id=candidate.candidate_id, verdict="INVALID",
            result={"verdict": "INVALID", "reason": "dimension"},
            invalidation_digest="e" * 64, tick=20,
        )
        self.assertEqual(updated["generation"], 2)
        self.assertEqual(
            reloaded.get_preflight_cache(cache_key)["result"]["verdict"],
            "INVALID",
        )

        self.assertTrue(reloaded.invalidate_preflight_cache(cache_key))
        self.assertIsNone(reloaded.get_preflight_cache(cache_key))
        self.assertFalse(reloaded.invalidate_preflight_cache(cache_key))

        # A canonical leaf is not a cache: reopen still resolves its payload.
        leaf = self.store.put_leaf(self.make_leaf(content={"value": 21}))
        reopened = MathStore(self.bs0_path, self.mc0_path)
        self.assertEqual(reopened.get_leaf(leaf.leaf_id).content, {"value": 21})

    # -- 2 MiB chunks -------------------------------------------------------

    def test_two_mib_payload_is_chunked_and_verified(self):
        data = b"m" * (2 * 1024 * 1024)
        stored = self.store.put_payload(data, encoding="binary", tick=5)
        self.assertEqual(stored["digest"], hashlib.sha256(data).hexdigest())
        self.assertEqual(stored["chunk_count"], 2)
        chunks = self.store.list_payload_chunks(stored["digest"])
        self.assertEqual(len(chunks), 2)
        self.assertEqual([chunk["chunk_index"] for chunk in chunks], [0, 1])
        self.assertEqual(chunks[0]["chunk_length"], DEFAULT_CHUNK_BYTES)
        self.assertEqual(chunks[1]["chunk_length"], DEFAULT_CHUNK_BYTES)
        self.assertEqual(self.store.get_payload(stored["digest"]), data)
        record = self.store.get_payload_record(stored["digest"])
        self.assertEqual(record["total_length"], 2 * 1024 * 1024)
        self.assertEqual(len(record["chunks"]), 2)

        # The same chunking path applies to an ordinary large leaf content.
        content = {"matrix": "z" * (1_500_000)}
        leaf = self.store.put_leaf(
            self.make_leaf(leaf_id="nml:test:leaf:large", content=content,
                           kind="matrix"),
        )
        payload_ref, content_digest = self.payload_ref("nml:test:leaf:large")
        self.assertEqual(payload_ref, content_digest)
        with closing(sqlite3.connect(self.bs0_path)) as db:
            chunk_count = db.execute(
                "SELECT MAX(chunk_count) FROM math_payload WHERE digest=?",
                (payload_ref,),
            ).fetchone()[0]
        self.assertEqual(chunk_count, 2)
        self.assertEqual(self.store.get_leaf(leaf.leaf_id).content, content)

        with self.assertRaises(MathStoreError):
            self.store.put_payload(b"x" * (2 * 1024 * 1024 + 1))

    # -- functions, rules, candidates, admissions --------------------------

    def test_function_and_rule_versions_roundtrip_with_cas(self):
        function_v1 = self.store.put_function(self.make_function())
        self.assertEqual(function_v1.version, 1)
        self.assertEqual(function_v1.digest(),
                         self.store.get_function(function_v1.function_id).digest())

        function_v2 = self.make_function(
            version=2, signature={"inputs": ["tensor", "tensor"],
                                  "output": "scalar"},
        )
        stored_v2 = self.store.put_function(
            function_v2, expected_version=1, expected_generation=1,
        )
        self.assertEqual(stored_v2.version, 2)
        self.assertEqual(
            self.store.get_function(function_v2.function_id, 1).version, 1
        )
        with self.assertRaises(StaleGenerationError):
            self.store.put_function(
                self.make_function(version=3),
                expected_version=1, expected_generation=1,
            )
        with self.assertRaises(MathStoreError):
            self.store.put_function(self.make_function(
                version=1, contract_digest="f" * 64,
            ))

        rule_v1 = self.store.put_rule(self.make_rule())
        self.assertEqual(rule_v1.version, 1)
        self.assertEqual(self.store.get_rule(rule_v1.rule_id).level, 1)
        rule_v2 = self.make_rule(version=2, contract={"claim": "updated"},
                                 status="validated")
        self.store.put_rule(rule_v2, expected_version=1,
                            expected_generation=1)
        self.assertEqual(self.store.get_rule(rule_v2.rule_id).version, 2)
        with self.assertRaises(StaleGenerationError):
            self.store.put_rule(
                self.make_rule(version=3), expected_version=1,
                expected_generation=1,
            )

        health = self.store.math_health()
        self.assertEqual(health["status"], "green")
        self.assertEqual(health["counts"]["math_function_version"], 2)
        self.assertEqual(health["counts"]["math_rule_version"], 2)

    def test_candidate_and_admission_are_immutable_roundtrips(self):
        candidate = self.make_candidate(candidate_id="cnd:test-1")
        stored = self.store.put_candidate(candidate)
        self.assertEqual(stored.to_dict(), candidate.to_dict())
        replay = self.store.put_candidate(candidate)
        self.assertEqual(replay.to_dict(), candidate.to_dict())
        with self.assertRaises(MathConflictError):
            self.store.put_candidate(self.make_candidate(
                candidate_id="cnd:test-1",
                inputs=({"leaf": "nml:test:leaf:other"},),
            ))

        admission = self.make_admission()
        stored_admission = self.store.put_admission(admission)
        self.assertEqual(stored_admission.verdict, "VALID")
        self.assertEqual(
            self.store.get_admission(admission.admission_id).to_dict(),
            admission.to_dict(),
        )
        with self.assertRaises(MathConflictError):
            self.store.put_admission(self.make_admission(verdict="INVALID"))

        with closing(sqlite3.connect(self.mc0_path)) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    "UPDATE math_candidate SET rank=99 WHERE candidate_id=?",
                    (candidate.candidate_id,),
                )

        health = self.store.math_health()
        self.assertEqual(health["status"], "green")
        self.assertEqual(health["counts"]["math_candidate"], 1)
        self.assertEqual(health["counts"]["math_admission"], 1)


if __name__ == "__main__":
    unittest.main()
