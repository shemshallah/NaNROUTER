"""Crash-injection tests for the §9.7 cross-store commit protocol.

The protocol is intentionally not a distributed transaction.  MC0DB records a
commit intent, BS0DB appends idempotent evidence, and MC0DB finalizes with a
mapping CAS.  These tests inject a crash before evidence, after evidence but
before finalize, and after finalize, then prove that recovery either completes
the commit or fails it without a partial active mapping.
"""
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing

from runner_riddle.math_objects import (
    MathLeaf, canonical_json, sha256_text,
)
from runner_riddle.math_store import (
    MATH_SCHEMA_VERSION, MathCommitError, MathConflictError,
    MathReferenceError, MathStore, StaleGenerationError,
)
from runner_riddle.wave_store import WaveStore


class MathStoreCrossStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bs0_path = self.tmp.name + "/bs0db.sqlite3"
        self.mc0_path = self.tmp.name + "/mc0db.sqlite3"
        self.wave = WaveStore(self.bs0_path, self.mc0_path)
        self.wave.enqueue_job(
            "wave-job-cross", universe_id="universe-0", generation=1,
            operator_digest="a" * 64, payload={"step": 1}, nanclock_tick=5,
        )
        self.store = MathStore(self.bs0_path, self.mc0_path)
        self.leaf_id = "nml:test:cross:leaf"
        self.mapping_id = "leaf:" + self.leaf_id

    # -- helpers ------------------------------------------------------------

    def make_leaf(self, *, content=None, leaf_id=None):
        return MathLeaf(
            leaf_id=self.leaf_id if leaf_id is None else leaf_id,
            kind="scalar",
            content={"value": 1} if content is None else content,
            type={"kind": "scalar"},
            provenance={"producer": "cross-store-test"},
        )

    def evidence(self, marker="ok"):
        return {"kind": "cross-store-test", "marker": marker}

    @staticmethod
    def digest(value):
        return sha256_text(canonical_json(value))

    def begin(self, **kwargs):
        return self.store.begin_commit_intent(
            "leaf", self.leaf_id, **kwargs,
        )

    def scalar(self, path, sql, args=()):
        with closing(sqlite3.connect(path)) as db:
            return db.execute(sql, args).fetchone()[0]

    # -- schema -------------------------------------------------------------

    def test_commit_tables_are_additive_and_wave_schema_stays_one(self):
        expected = {
            self.mc0_path: {"math_commit_intent"},
            self.bs0_path: {"math_commit_evidence"},
        }
        for path, tables in expected.items():
            with closing(sqlite3.connect(path)) as db:
                found = {
                    row[0] for row in db.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
            self.assertTrue(tables.issubset(found), tables - found)

        for path, store in ((self.bs0_path, "BS0DB"),
                            (self.mc0_path, "MC0DB")):
            self.assertEqual(
                self.scalar(
                    path, "SELECT version FROM wave_schema WHERE store=?",
                    (store,),
                ),
                1,
            )
            self.assertEqual(
                self.scalar(
                    path, "SELECT version FROM math_schema WHERE store=?",
                    (store,),
                ),
                MATH_SCHEMA_VERSION,
            )
            self.assertEqual(
                self.scalar(path, "PRAGMA user_version"), 1,
            )

        health = self.store.math_health()
        self.assertEqual(health["status"], "green")
        self.assertEqual(health["wave_schema_versions"],
                         {"BS0DB": 1, "MC0DB": 1})
        self.assertEqual(health["counts"]["math_commit_intent"], 0)
        self.assertEqual(health["counts"]["math_commit_evidence"], 0)

    def test_spec_declares_the_commit_tables(self):
        from pathlib import Path

        spec_path = Path(__file__).resolve().parents[1] / "spec" / \
            "math-store.schema.json"
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        mc0 = spec["properties"]["stores"]["properties"]["MC0DB"][
            "properties"]["tables"]
        bs0 = spec["properties"]["stores"]["properties"]["BS0DB"][
            "properties"]["tables"]
        self.assertIn("math_commit_intent", mc0["required"])
        self.assertIn("math_commit_evidence", bs0["required"])
        intent_def = spec["$defs"]["math_commit_intent"]
        evidence_def = spec["$defs"]["math_commit_evidence"]
        self.assertEqual(
            intent_def["properties"]["status_enum"]["const"],
            ["pending", "finalized", "failed"],
        )
        self.assertTrue(
            evidence_def["properties"]["append_only"]["const"]
        )

    # -- intent and evidence idempotency ------------------------------------

    def test_begin_intent_is_idempotent_and_defaults_to_current_base(self):
        leaf = self.store.put_leaf(self.make_leaf())
        mapping = self.store.get_mapping(self.mapping_id)
        evidence = self.evidence("begin")
        intent = self.begin(
            target_version=1, target_digest=leaf.digest(),
            evidence_digest=self.digest(evidence),
            expected_version=1, expected_generation=1,
            expected_mapping_digest=mapping["target_digest"],
            intent_id="intent:begin", tick=10,
        )
        self.assertEqual(intent["state"], "pending")
        self.assertEqual(intent["base_version"], 1)
        self.assertEqual(intent["base_generation"], 1)
        self.assertEqual(intent["evidence_ref"], None)
        self.assertEqual(intent["finalized_tick"], None)

        replay = self.begin(
            target_version=1, target_digest=leaf.digest(),
            evidence_digest=self.digest(evidence),
            expected_version=1, expected_generation=1,
            expected_mapping_digest=mapping["target_digest"],
            intent_id="intent:begin", tick=99,
        )
        self.assertEqual(replay["created_tick"], 10)
        self.assertEqual(replay["state"], "pending")
        self.assertEqual(
            len(self.store.list_commit_intents()), 1,
        )

        with self.assertRaises(MathConflictError):
            self.begin(
                target_version=1, target_digest=leaf.digest(),
                evidence_digest="b" * 64,
                expected_version=1, expected_generation=1,
                intent_id="intent:begin",
            )

        defaulted = self.begin(
            target_version=1, target_digest=leaf.digest(),
            evidence_digest=self.digest(self.evidence("defaulted")),
            tick=11,
        )
        self.assertEqual(defaulted["base_version"], 1)
        self.assertEqual(defaulted["base_generation"], 1)
        self.assertEqual(defaulted["base_mapping_digest"],
                         mapping["target_digest"])
        self.assertNotEqual(defaulted["intent_id"], "intent:begin")

    def test_evidence_append_and_verify_are_idempotent(self):
        leaf = self.store.put_leaf(self.make_leaf())
        evidence = self.evidence("evidence")
        intent = self.begin(
            target_version=1, target_digest=leaf.digest(),
            evidence_digest=self.digest(evidence),
            expected_version=1, expected_generation=1,
            intent_id="intent:evidence", tick=10,
        )
        first = self.store.append_commit_evidence(
            intent["intent_id"], evidence, tick=11,
        )
        self.assertFalse(first["reused"])
        self.assertEqual(first["evidence"], evidence)
        replay = self.store.append_commit_evidence(
            intent["intent_id"], evidence, tick=12,
        )
        self.assertTrue(replay["reused"])
        self.assertEqual(replay["created_tick"], 11)
        self.assertEqual(
            len(self.store.list_commit_evidence()), 1,
        )
        self.assertTrue(self.store.verify_commit_evidence(
            intent["intent_id"]
        ))
        self.assertTrue(self.store.verify_commit_evidence(
            intent["intent_id"], evidence_digest=self.digest(evidence),
        ))

        with self.assertRaises(MathConflictError):
            self.store.append_commit_evidence(
                intent["intent_id"], self.evidence("different"),
            )
        self.assertTrue(self.store.verify_commit_evidence(
            intent["intent_id"]
        ))

        other = self.evidence("other")
        other_intent = self.begin(
            target_version=1, target_digest=leaf.digest(),
            evidence_digest=self.digest(other),
            expected_version=1, expected_generation=1,
            intent_id="intent:other-digest", tick=13,
        )
        with self.assertRaises(MathConflictError):
            self.store.append_commit_evidence(
                other_intent["intent_id"], self.evidence("not-other"),
            )
        with self.assertRaises(MathReferenceError):
            self.store.get_commit_evidence(other_intent["intent_id"])

    # -- crash injection ----------------------------------------------------

    def test_crash_before_evidence_fails_without_moving_the_mapping(self):
        leaf = self.store.put_leaf(self.make_leaf())
        mapping_before = self.store.get_mapping(self.mapping_id)
        self.begin(
            target_version=1, target_digest=leaf.digest(),
            evidence_digest=self.digest(self.evidence("never-written")),
            expected_version=1, expected_generation=1,
            expected_mapping_digest=mapping_before["target_digest"],
            intent_id="intent:before-evidence", tick=10,
        )

        # Process dies here.  A fresh store represents restart recovery.
        restarted = MathStore(self.bs0_path, self.mc0_path)
        outcomes = restarted.recover_pending_intents(tick=20)
        self.assertEqual(len(outcomes), 1)
        self.assertFalse(outcomes[0]["recovered"])
        self.assertEqual(outcomes[0]["state"], "failed")
        self.assertEqual(outcomes[0]["error_type"], "MathReferenceError")

        intent = restarted.get_commit_intent("intent:before-evidence")
        self.assertEqual(intent["state"], "failed")
        self.assertIn("evidence", intent["failure_reason"])
        self.assertEqual(intent["evidence_ref"], None)
        with self.assertRaises(MathReferenceError):
            restarted.get_commit_evidence("intent:before-evidence")
        with self.assertRaises(MathCommitError):
            restarted.finalize_commit_intent("intent:before-evidence")

        mapping = restarted.get_mapping(self.mapping_id)
        self.assertEqual(
            (mapping["current_version"], mapping["generation"],
             mapping["target_digest"], mapping["status"]),
            (mapping_before["current_version"],
             mapping_before["generation"],
             mapping_before["target_digest"], mapping_before["status"]),
        )
        self.assertEqual(restarted.recover_pending_intents(tick=21), [])

    def test_crash_after_evidence_before_finalize_recovery_completes(self):
        self.store.put_leaf(self.make_leaf(content={"value": 1}))
        self.store.put_version(
            self.leaf_id, {"value": 2}, expected_version=1,
            expected_generation=1, tick=2,
        )
        mapping_before = self.store.get_mapping(self.mapping_id)
        self.assertEqual(
            (mapping_before["current_version"],
             mapping_before["generation"]), (2, 2),
        )
        target_v1 = self.store.get_leaf(self.leaf_id, 1)
        evidence = self.evidence("recover-me")
        evidence_digest = self.digest(evidence)
        self.begin(
            target_version=1, target_digest=target_v1.digest(),
            evidence_digest=evidence_digest,
            expected_version=2, expected_generation=2,
            expected_mapping_digest=mapping_before["target_digest"],
            intent_id="intent:after-evidence", tick=10,
        )
        self.store.append_commit_evidence(
            "intent:after-evidence", evidence, tick=11,
        )

        # Process dies after BS0DB evidence, before MC0DB finalize.
        restarted = MathStore(self.bs0_path, self.mc0_path)
        outcomes = restarted.recover_pending_intents(tick=20)
        self.assertEqual(len(outcomes), 1)
        self.assertTrue(outcomes[0]["recovered"])
        self.assertEqual(outcomes[0]["state"], "finalized")

        intent = restarted.get_commit_intent("intent:after-evidence")
        self.assertEqual(intent["state"], "finalized")
        self.assertEqual(intent["evidence_ref"], evidence_digest)
        self.assertEqual(intent["finalized_tick"], 20)
        self.assertTrue(restarted.verify_commit_evidence(
            "intent:after-evidence"
        ))

        mapping = restarted.get_mapping(self.mapping_id)
        self.assertEqual(mapping["current_version"], 1)
        self.assertEqual(mapping["generation"], 3)
        self.assertEqual(mapping["target_digest"], target_v1.digest())
        self.assertEqual(mapping["status"], "active")
        self.assertEqual(
            restarted.resolve("map:" + self.mapping_id).content,
            {"value": 1},
        )
        # The immutable leaf head still retains the newer version.
        self.assertEqual(restarted.get_leaf(self.leaf_id).version, 2)

        # Recovery and finalize replays are idempotent.
        self.assertEqual(restarted.recover_pending_intents(tick=21), [])
        replay = restarted.finalize_commit_intent(
            "intent:after-evidence", tick=99,
        )
        self.assertEqual(replay["state"], "finalized")
        self.assertEqual(replay["finalized_tick"], 20)
        self.assertEqual(
            restarted.get_mapping(self.mapping_id)["generation"], 3,
        )
        self.assertEqual(len(restarted.list_commit_evidence()), 1)

    def test_crash_after_finalize_is_a_no_op(self):
        self.store.put_leaf(self.make_leaf(content={"value": 1}))
        self.store.put_version(
            self.leaf_id, {"value": 2}, expected_version=1,
            expected_generation=1, tick=2,
        )
        mapping_before = self.store.get_mapping(self.mapping_id)
        target_v1 = self.store.get_leaf(self.leaf_id, 1)
        evidence = self.evidence("already-final")
        self.begin(
            target_version=1, target_digest=target_v1.digest(),
            evidence_digest=self.digest(evidence),
            expected_version=2, expected_generation=2,
            expected_mapping_digest=mapping_before["target_digest"],
            intent_id="intent:after-finalize", tick=10,
        )
        self.store.append_commit_evidence(
            "intent:after-finalize", evidence, tick=11,
        )
        finalized = self.store.finalize_commit_intent(
            "intent:after-finalize", tick=12,
        )
        self.assertEqual(finalized["state"], "finalized")
        mapping_after = self.store.get_mapping(self.mapping_id)
        self.assertEqual(
            (mapping_after["current_version"], mapping_after["generation"],
             mapping_after["target_digest"]),
            (1, 3, target_v1.digest()),
        )

        # Process dies after the MC0DB commit.  Recovery sees no pending work.
        restarted = MathStore(self.bs0_path, self.mc0_path)
        self.assertEqual(restarted.recover_pending_intents(tick=20), [])
        replay = restarted.finalize_commit_intent(
            "intent:after-finalize", tick=21,
        )
        self.assertEqual(replay["finalized_tick"], 12)
        self.assertEqual(
            restarted.get_mapping(self.mapping_id)["generation"], 3,
        )
        self.assertEqual(len(restarted.list_commit_evidence()), 1)

    # -- failure paths ------------------------------------------------------

    def test_missing_evidence_fails_without_a_partial_mapping(self):
        leaf = self.store.put_leaf(self.make_leaf())
        mapping_before = self.store.get_mapping(self.mapping_id)
        self.begin(
            target_version=1, target_digest=leaf.digest(),
            evidence_digest=self.digest(self.evidence("missing")),
            expected_version=1, expected_generation=1,
            expected_mapping_digest=mapping_before["target_digest"],
            intent_id="intent:missing-evidence", tick=10,
        )
        with self.assertRaises(MathReferenceError):
            self.store.finalize_commit_intent(
                "intent:missing-evidence", tick=11,
            )
        intent = self.store.get_commit_intent("intent:missing-evidence")
        self.assertEqual(intent["state"], "failed")
        self.assertEqual(intent["evidence_ref"], None)
        mapping = self.store.get_mapping(self.mapping_id)
        self.assertEqual(
            (mapping["current_version"], mapping["generation"],
             mapping["target_digest"]),
            (mapping_before["current_version"],
             mapping_before["generation"],
             mapping_before["target_digest"]),
        )
        # The immutable version and its payload remain readable.
        self.assertEqual(self.store.get_leaf(self.leaf_id).content,
                         {"value": 1})

    def test_mismatched_evidence_digest_fails_closed(self):
        leaf = self.store.put_leaf(self.make_leaf())
        mapping_before = self.store.get_mapping(self.mapping_id)
        good = self.evidence("good")
        intent = self.begin(
            target_version=1, target_digest=leaf.digest(),
            evidence_digest=self.digest(good),
            expected_version=1, expected_generation=1,
            expected_mapping_digest=mapping_before["target_digest"],
            intent_id="intent:bad-evidence", tick=10,
        )
        # Simulate a writer that wrote evidence with the wrong digest.
        with closing(sqlite3.connect(self.bs0_path)) as db:
            db.execute(
                "INSERT INTO math_commit_evidence(intent_id, "
                "evidence_digest, mapping_id, object_type, object_id, "
                "target_version, target_digest, evidence_json, created_tick) "
                "VALUES (?, ?, ?, 'leaf', ?, 1, ?, ?, 5)",
                (intent["intent_id"], "b" * 64, self.mapping_id,
                 self.leaf_id, leaf.digest(),
                 canonical_json(self.evidence("bad"))),
            )
            db.commit()

        with self.assertRaises(MathConflictError):
            self.store.finalize_commit_intent(
                "intent:bad-evidence", tick=11,
            )
        self.assertEqual(
            self.store.get_commit_intent("intent:bad-evidence")["state"],
            "failed",
        )
        mapping = self.store.get_mapping(self.mapping_id)
        self.assertEqual(
            (mapping["current_version"], mapping["generation"],
             mapping["target_digest"]),
            (1, 1, mapping_before["target_digest"]),
        )
        with self.assertRaises(MathConflictError):
            self.store.verify_commit_evidence("intent:bad-evidence")

    def test_stale_generation_fails_without_clobbering_the_mapping(self):
        leaf = self.store.put_leaf(self.make_leaf(content={"value": 1}))
        mapping_before = self.store.get_mapping(self.mapping_id)
        evidence = self.evidence("stale")
        self.begin(
            target_version=1, target_digest=leaf.digest(),
            evidence_digest=self.digest(evidence),
            expected_version=1, expected_generation=1,
            expected_mapping_digest=mapping_before["target_digest"],
            intent_id="intent:stale", tick=10,
        )
        self.store.append_commit_evidence("intent:stale", evidence, tick=11)

        # Another writer advances the active mapping after the intent began.
        self.store.put_version(
            self.leaf_id, {"value": 2}, expected_version=1,
            expected_generation=1, tick=12,
        )
        with self.assertRaises(StaleGenerationError):
            self.store.finalize_commit_intent("intent:stale", tick=13)

        intent = self.store.get_commit_intent("intent:stale")
        self.assertEqual(intent["state"], "failed")
        self.assertIn("version", intent["failure_reason"])
        mapping = self.store.get_mapping(self.mapping_id)
        self.assertEqual(
            (mapping["current_version"], mapping["generation"]),
            (2, 2),
        )
        self.assertEqual(
            self.store.resolve("map:" + self.mapping_id).content,
            {"value": 2},
        )
        self.assertEqual(self.store.recover_pending_intents(tick=14), [])

    def test_target_digest_mismatch_never_publishes_the_mapping(self):
        leaf = self.store.put_leaf(self.make_leaf())
        mapping_before = self.store.get_mapping(self.mapping_id)
        evidence = self.evidence("target-mismatch")
        self.begin(
            target_version=1, target_digest="c" * 64,
            evidence_digest=self.digest(evidence),
            expected_version=1, expected_generation=1,
            expected_mapping_digest=mapping_before["target_digest"],
            intent_id="intent:target-mismatch", tick=10,
        )
        self.store.append_commit_evidence(
            "intent:target-mismatch", evidence, tick=11,
        )
        with self.assertRaises(MathCommitError):
            self.store.finalize_commit_intent(
                "intent:target-mismatch", tick=12,
            )
        self.assertEqual(
            self.store.get_commit_intent("intent:target-mismatch")["state"],
            "failed",
        )
        mapping = self.store.get_mapping(self.mapping_id)
        self.assertEqual(
            (mapping["current_version"], mapping["generation"],
             mapping["target_digest"]),
            (1, 1, mapping_before["target_digest"]),
        )
        self.assertEqual(self.store.get_leaf(self.leaf_id).digest(),
                         leaf.digest())

    def test_recovery_processes_each_pending_intent_independently(self):
        first = self.store.put_leaf(
            self.make_leaf(content={"value": 1},
                           leaf_id="nml:test:cross:first")
        )
        second = self.store.put_leaf(
            self.make_leaf(content={"value": 2},
                           leaf_id="nml:test:cross:second")
        )
        first_mapping_id = "leaf:" + first.leaf_id
        second_mapping_id = "leaf:" + second.leaf_id
        first_mapping = self.store.get_mapping(first_mapping_id)
        second_mapping = self.store.get_mapping(second_mapping_id)
        good = self.evidence("good-intent")
        self.store.begin_commit_intent(
            "leaf", first.leaf_id, target_version=1,
            target_digest=first.digest(), evidence_digest=self.digest(good),
            expected_version=1, expected_generation=1,
            expected_mapping_digest=first_mapping["target_digest"],
            intent_id="intent:good", tick=10,
        )
        self.store.append_commit_evidence("intent:good", good, tick=11)
        self.store.begin_commit_intent(
            "leaf", second.leaf_id, target_version=1,
            target_digest=second.digest(),
            evidence_digest=self.digest(self.evidence("missing-intent")),
            expected_version=1, expected_generation=1,
            expected_mapping_digest=second_mapping["target_digest"],
            intent_id="intent:missing", tick=12,
        )

        outcomes = self.store.recover_pending_intents(tick=20)
        self.assertEqual(len(outcomes), 2)
        by_id = {entry["intent_id"]: entry for entry in outcomes}
        self.assertTrue(by_id["intent:good"]["recovered"])
        self.assertEqual(by_id["intent:good"]["state"], "finalized")
        self.assertFalse(by_id["intent:missing"]["recovered"])
        self.assertEqual(by_id["intent:missing"]["state"], "failed")
        self.assertEqual(
            self.store.get_mapping(first_mapping_id)["generation"], 1,
        )
        self.assertEqual(
            self.store.get_mapping(second_mapping_id)["generation"], 1,
        )


if __name__ == "__main__":
    unittest.main()
