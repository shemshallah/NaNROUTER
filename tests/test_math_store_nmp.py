"""Durable NMP packet/transition evidence in the additive MC0 math schema.

These tests cover GAME_PLAN_:: §9.2/§9.6 and the Agent B gap: packets and their
transitions are canonical, digest-bound, idempotent, append-only, chained from
the stored current state, and free of bearer credentials.
"""
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from runner_riddle import nmp
from runner_riddle.math_objects import canonical_json, sha256_text
from runner_riddle.math_store import (
    MATH_SCHEMA_VERSION, MathConflictError, MathReferenceError, MathStore,
    MathStoreError,
)
from runner_riddle.wave_store import WaveStore


class MathStoreNmpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bs0_path = self.tmp.name + "/bs0db.sqlite3"
        self.mc0_path = self.tmp.name + "/mc0db.sqlite3"
        self.wave = WaveStore(self.bs0_path, self.mc0_path)
        self.store = MathStore(self.bs0_path, self.mc0_path)

    # -- helpers ------------------------------------------------------------

    def make_packet(self, *, state=nmp.CREATED, packet_id="",
                    **overrides):
        fields = {
            "snapshot_id": "snapshot-1",
            "base_generation": 7,
            "lane_id": 3,
            "universe_id": "U0",
            "function_id": "math.vector.dot.v1",
            "function_version": 1,
            "candidate_id": "cnd:test-1",
            "inputs": (
                {"leaf_id": "nml:U0:vector:1", "version": 1,
                 "digest": "a" * 64},
            ),
            "admission_id": "adm:test-1",
            "admission_verdict": "VALID",
            "preflight_digest": "b" * 64,
            "preflight_result": "VALID",
            "ruleset_id": "math.rules.core.v1",
            "ruleset_version": 1,
            "ruleset_snapshot_id": "rules-snapshot-1",
            "capability_set": (
                {"required": "vector.dot", "workspace": 256},
            ),
            "capability_epoch": 1,
            "guest_words": 256,
            "ring_incarnation": "ring-inc-1",
            "ring_epoch": 1,
            "jahs": nmp.JAHS_SEAL,
            "state": state,
            "metadata": {"request_tag": "nmp-store-test"},
        }
        fields.update(overrides)
        if packet_id:
            fields["packet_id"] = packet_id
        return nmp.NmpPacket(**fields)

    def scalar(self, path, sql, args=()):
        with closing(sqlite3.connect(path)) as db:
            return db.execute(sql, args).fetchone()[0]

    def table_columns(self, path, table):
        with closing(sqlite3.connect(path)) as db:
            return {
                column[1]: column[2]
                for column in db.execute(f"PRAGMA table_info({table})")
            }

    # -- roundtrip and identity --------------------------------------------

    def test_packet_roundtrip_by_object_and_mapping(self):
        packet = self.make_packet()
        record = self.store.put_nmp_packet(packet, tick=5)
        self.assertEqual(record["packet_id"], packet.packet_id)
        self.assertEqual(record["state"], nmp.CREATED)
        self.assertEqual(record["packet"], packet.to_dict())
        self.assertEqual(record["packet_digest"], packet.digest())
        self.assertEqual(record["snapshot_id"], "snapshot-1")
        self.assertEqual(record["candidate_id"], "cnd:test-1")
        self.assertEqual(record["admission_id"], "adm:test-1")
        self.assertEqual(record["created_tick"], 5)

        stored = self.store.get_nmp_packet(packet.packet_id)
        self.assertEqual(stored["packet"], packet.to_dict())
        self.assertEqual(stored["packet_digest"], packet.digest())
        self.assertEqual(stored["state"], nmp.CREATED)
        self.assertEqual(self.store.list_nmp_transitions(packet.packet_id), [])
        self.assertIsNone(self.store.latest_nmp_transition(packet.packet_id))
        self.assertEqual(
            [item["packet_id"] for item in self.store.list_nmp_packets()],
            [packet.packet_id],
        )

        mapped = self.make_packet(packet_id="nmp:mapping-path",
                                  candidate_id="cnd:mapping-path")
        mapped_record = self.store.put_nmp_packet(mapped.to_dict(), tick=6)
        self.assertEqual(mapped_record["packet_id"], "nmp:mapping-path")
        self.assertEqual(
            self.store.get_nmp_packet("nmp:mapping-path")["packet"],
            mapped.to_dict(),
        )
        with self.assertRaises(MathStoreError):
            self.store.put_nmp_packet(
                {"packet_id": "nmp:invalid", "snapshot_id": "snapshot-1"}
            )

    def test_packet_replay_is_idempotent(self):
        packet = self.make_packet(packet_id="nmp:replay")
        first = self.store.put_nmp_packet(packet, tick=10)
        second = self.store.put_nmp_packet(packet, tick=99)
        third = self.store.put_nmp_packet(packet.to_dict(), tick=100)
        self.assertFalse(first["reused"])
        self.assertTrue(second["reused"])
        self.assertTrue(third["reused"])
        self.assertEqual(second["created_tick"], 10)
        self.assertEqual(third["created_tick"], 10)
        self.assertEqual(len(self.store.list_nmp_packets()), 1)

    def test_packet_conflict_on_same_packet_id(self):
        packet = self.make_packet(packet_id="nmp:conflict",
                                  candidate_id="cnd:first")
        self.store.put_nmp_packet(packet)
        changed = self.make_packet(packet_id="nmp:conflict",
                                   candidate_id="cnd:second")
        with self.assertRaises(MathConflictError):
            self.store.put_nmp_packet(changed)
        self.assertEqual(
            self.store.get_nmp_packet("nmp:conflict")["candidate_id"],
            "cnd:first",
        )

    # -- transitions --------------------------------------------------------

    def test_transition_chain_advances_current_state(self):
        packet = self.make_packet(packet_id="nmp:chain")
        self.store.put_nmp_packet(packet, tick=1)
        evidence = {"reason": "inputs resolved", "job_id": "job-1"}
        first = self.store.append_nmp_transition(
            packet.packet_id, nmp.CREATED, nmp.RESOLVED,
            tick=10, evidence=evidence,
        )
        self.assertEqual(first["transition_seq"], 1)
        self.assertEqual(first["from_state"], nmp.CREATED)
        self.assertEqual(first["to_state"], nmp.RESOLVED)
        self.assertEqual(
            first["evidence_digest"],
            sha256_text(canonical_json(evidence)),
        )
        self.assertEqual(first["transition"]["evidence"], evidence)

        second = self.store.append_nmp_transition(
            packet.packet_id, nmp.RESOLVED, nmp.CLASSIFIED, tick=11,
        )
        self.assertEqual(second["transition_seq"], 2)
        self.assertIsNone(second["evidence_digest"])
        self.assertIsNone(second["transition"]["evidence"])

        current = self.store.get_nmp_packet(packet.packet_id)
        self.assertEqual(current["state"], nmp.CLASSIFIED)
        # The packet_json remains the immutable creation record.
        self.assertEqual(current["packet"]["state"], nmp.CREATED)
        self.assertEqual(current["updated_tick"], 11)

        transitions = self.store.list_nmp_transitions(packet.packet_id)
        self.assertEqual(
            [(item["from_state"], item["to_state"]) for item in transitions],
            [(nmp.CREATED, nmp.RESOLVED), (nmp.RESOLVED, nmp.CLASSIFIED)],
        )
        self.assertEqual(
            self.store.latest_nmp_transition(packet.packet_id)[
                "transition_seq"],
            2,
        )
        self.assertEqual(
            [item["packet_id"] for item in self.store.list_nmp_packets(
                state=nmp.CLASSIFIED)],
            [packet.packet_id],
        )
        self.assertEqual(
            self.store.list_nmp_packets(state=nmp.CREATED), []
        )

    def test_transition_rejects_skips_and_illegal_edges(self):
        packet = self.make_packet(packet_id="nmp:reject")
        self.store.put_nmp_packet(packet)
        with self.assertRaises(MathStoreError):
            self.store.append_nmp_transition(
                packet.packet_id, nmp.RESOLVED, nmp.CLASSIFIED, tick=10,
            )
        with self.assertRaises(MathStoreError):
            self.store.append_nmp_transition(
                packet.packet_id, nmp.CREATED, nmp.EXECUTING, tick=11,
            )
        self.assertEqual(
            self.store.list_nmp_transitions(packet.packet_id), []
        )
        self.assertEqual(
            self.store.get_nmp_packet(packet.packet_id)["state"], nmp.CREATED
        )

    def test_seeded_transition_bootstraps_only_the_first_edge(self):
        packet = self.make_packet(packet_id="nmp:seed")
        self.store.put_nmp_packet(packet)
        seeded = self.store.append_nmp_transition(
            packet.packet_id, nmp.EXECUTING, nmp.COMPLETED,
            tick=20, evidence={"imported": True}, seed=True,
        )
        self.assertEqual(seeded["from_state"], nmp.EXECUTING)
        self.assertEqual(
            self.store.get_nmp_packet(packet.packet_id)["state"],
            nmp.COMPLETED,
        )
        with self.assertRaises(MathStoreError):
            self.store.append_nmp_transition(
                packet.packet_id, nmp.COMPLETED, nmp.COMMITTED,
                tick=21, seed=True,
            )
        self.assertEqual(
            len(self.store.list_nmp_transitions(packet.packet_id)), 1
        )

    def test_packet_and_transition_tables_are_append_only(self):
        packet = self.make_packet(packet_id="nmp:append-only")
        self.store.put_nmp_packet(packet)
        self.store.append_nmp_transition(
            packet.packet_id, nmp.CREATED, nmp.RESOLVED, tick=10,
        )
        with closing(sqlite3.connect(self.mc0_path)) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    "UPDATE math_nmp_transition SET to_state='COMMITTED' "
                    "WHERE transition_seq=1"
                )
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    "DELETE FROM math_nmp_transition WHERE transition_seq=1"
                )
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    "UPDATE math_nmp_packet SET packet_json='{}' "
                    "WHERE packet_id=?", (packet.packet_id,)
                )
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute(
                    "DELETE FROM math_nmp_packet WHERE packet_id=?",
                    (packet.packet_id,),
                )
        self.assertEqual(
            self.store.get_nmp_packet(packet.packet_id)["state"],
            nmp.RESOLVED,
        )

    # -- security and integrity --------------------------------------------

    def test_secret_like_keys_are_rejected(self):
        allowed = self.make_packet(
            packet_id="nmp:digest-name-ok",
            metadata={"token_digest": "c" * 64},
        )
        self.store.put_nmp_packet(allowed)

        for index, metadata in enumerate((
            {"access_token": "bearer-value"},
            {"password": "hunter2"},
            {"client_secret": "shh"},
            {"api_key": "key-value"},
            {"credentials": {"user": "u", "pass": "p"}},
        )):
            bad = self.make_packet(
                packet_id=f"nmp:secret-{index}", metadata=metadata,
            )
            with self.assertRaises(MathStoreError):
                self.store.put_nmp_packet(bad)

        mapping = self.make_packet(
            packet_id="nmp:extra-secret-field",
        ).to_dict()
        mapping["signing_key"] = "top-secret"
        with self.assertRaises(MathStoreError):
            self.store.put_nmp_packet(mapping)

        packet = self.make_packet(packet_id="nmp:transition-secret")
        self.store.put_nmp_packet(packet)
        with self.assertRaises(MathStoreError):
            self.store.append_nmp_transition(
                packet.packet_id, nmp.CREATED, nmp.RESOLVED, tick=10,
                evidence={"lease_token": "secret-bearer-token"},
            )
        self.assertEqual(
            self.store.list_nmp_transitions(packet.packet_id), []
        )

    def test_unknown_packets_and_corruption_are_reference_errors(self):
        for call in (
            lambda: self.store.get_nmp_packet("nmp:missing"),
            lambda: self.store.list_nmp_transitions("nmp:missing"),
            lambda: self.store.latest_nmp_transition("nmp:missing"),
            lambda: self.store.append_nmp_transition(
                "nmp:missing", nmp.CREATED, nmp.RESOLVED, tick=1,
            ),
        ):
            with self.assertRaises(MathReferenceError):
                call()

        packet = self.make_packet(packet_id="nmp:corrupt-packet")
        self.store.put_nmp_packet(packet)
        with closing(sqlite3.connect(self.mc0_path)) as db:
            db.execute("DROP TRIGGER math_nmp_packet_identity_immutable")
            db.execute(
                "UPDATE math_nmp_packet SET packet_json='{}' "
                "WHERE packet_id=?", (packet.packet_id,)
            )
            db.commit()
        with self.assertRaises(MathReferenceError):
            self.store.get_nmp_packet(packet.packet_id)

        transitioned = self.make_packet(packet_id="nmp:corrupt-transition")
        self.store.put_nmp_packet(transitioned)
        self.store.append_nmp_transition(
            transitioned.packet_id, nmp.CREATED, nmp.RESOLVED, tick=2,
            evidence={"ok": True},
        )
        with closing(sqlite3.connect(self.mc0_path)) as db:
            db.execute("DROP TRIGGER math_nmp_transition_no_update")
            db.execute(
                "UPDATE math_nmp_transition SET transition_json='{}' "
                "WHERE packet_id=?", (transitioned.packet_id,)
            )
            db.commit()
        with self.assertRaises(MathReferenceError):
            self.store.list_nmp_transitions(transitioned.packet_id)

    # -- schema and spec ----------------------------------------------------

    def test_health_includes_nmp_ledger_counts(self):
        packet = self.make_packet()
        self.store.put_nmp_packet(packet, tick=1)
        self.store.append_nmp_transition(
            packet.packet_id, nmp.CREATED, nmp.RESOLVED, tick=2,
            seed=True,
        )
        health = self.store.health()
        self.assertEqual(health["counts"]["nmp_packets"], 1)
        self.assertEqual(health["counts"]["nmp_transitions"], 1)

    def test_schema_and_spec_cover_nmp_tables(self):
        expected = {"math_nmp_packet", "math_nmp_transition"}
        with closing(sqlite3.connect(self.mc0_path)) as db:
            found = {
                row[0] for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        self.assertTrue(expected.issubset(found), expected - found)

        spec_path = Path(__file__).resolve().parents[1] / "spec" / \
            "math-store.schema.json"
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        self.assertEqual(spec["properties"]["schema"]["const"],
                         "nanrouter.math-store.v1")
        self.assertEqual(spec["properties"]["version"]["const"], 1)
        self.assertEqual(
            spec["properties"]["wave_schema_compatibility"]["const"], 1
        )
        tables = spec["properties"]["stores"]["properties"]["MC0DB"][
            "properties"]["tables"]
        for table in expected:
            self.assertIn(table, tables["required"])
            self.assertIn(table, tables["properties"])
            definition = spec["$defs"][table]
            self.assertEqual(
                definition["properties"]["columns"]["const"],
                self.table_columns(self.mc0_path, table),
            )
            self.assertTrue(
                set(definition["properties"]["required_fields"]["const"])
                <= set(definition["properties"]["columns"]["const"])
            )
        self.assertTrue(
            spec["$defs"]["math_nmp_transition"][
                "properties"]["append_only"]["const"]
        )
        self.assertEqual(
            set(spec["properties"]["status_enums"]["properties"][
                "nmp_state"]["const"]),
            set(nmp.ALL_STATES),
        )
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

        packet = self.make_packet(packet_id="nmp:health")
        self.store.put_nmp_packet(packet, tick=3)
        self.store.append_nmp_transition(
            packet.packet_id, nmp.CREATED, nmp.RESOLVED, tick=4,
        )
        health = self.store.math_health()
        self.assertEqual(health["status"], "green")
        self.assertEqual(health["counts"]["math_nmp_packet"], 1)
        self.assertEqual(health["counts"]["math_nmp_transition"], 1)
        self.assertTrue(health["wave_schema_untouched"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
