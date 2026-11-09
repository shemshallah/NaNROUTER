"""Host-only append-only hyperedge arena: chains, incidence, and JSON replay."""
import hashlib
import json
import unittest

from runner_riddle.mirror_hyperedge_arena import (
    DEFAULT_LIMIT, MAX_DEPTH, MAX_LIMIT, NULL_HYPEREDGE_ID, PAIR_ID_MAX,
    PAIR_ID_MIN, SCHEMA, VERSION, HyperedgeArena, HyperedgeArenaError,
    MirrorHyperedgeArena, clamp_pair_id,
)


def record_digest(records):
    payload = {"schema": SCHEMA, "version": VERSION, "records": records}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


class StableIdentityTests(unittest.TestCase):
    def setUp(self):
        self.arena = MirrorHyperedgeArena()

    def test_null_zero_and_stable_contiguous_ids(self):
        self.assertEqual(len(self.arena), 0)
        self.assertIsNone(self.arena.get(0))
        self.assertIsNone(self.arena.get(1))
        self.assertEqual(self.arena.pair_head(1), 0)
        status = self.arena.status()
        self.assertEqual(status["record_count"], 0)
        self.assertEqual(status["next_id"], 1)
        self.assertEqual(status["digest"], record_digest([]))
        self.assertTrue(status["append_only"])
        self.assertTrue(status["host_only"])
        self.assertFalse(status["sqlite"])
        self.assertFalse(status["host_math"])
        self.assertFalse(status["native_execution"])
        self.assertFalse(status["canonical_merge"])

        first = self.arena.add_hyperedge(1, 10, 1, 0.5)
        second = self.arena.add_hyperedge(2, 11, 2, 0.75)
        third = self.arena.add_hyperedge(1, 12, 3, 1.0)
        self.assertEqual([first["id"], second["id"], third["id"]], [1, 2, 3])
        self.assertEqual(self.arena.get(1), first)
        self.assertEqual(self.arena.get(2), second)
        self.assertEqual(self.arena.get(3), third)
        self.assertEqual(self.arena.status()["next_id"], 4)

        # Callers receive copies, never the arena's internal record slots.
        first["concept_id"] = 999
        self.assertEqual(self.arena.get(1)["concept_id"], 10)

    def test_f32_normalization_and_optional_parent(self):
        record = self.arena.add_hyperedge(
            pair_id=1, concept_id=2, relation_type=3, strength=0.1)
        self.assertEqual(record["strength"], 0.10000000149011612)
        parent = self.arena.add_hyperedge(
            1, 2, 4, 1, record["id"])
        self.assertEqual(parent["parent_hyperedge_id"], 1)
        null_parent = self.arena.add_hyperedge(
            1, 3, 5, 1, parent_hyperedge_id=0)
        self.assertIsNone(null_parent["parent_hyperedge_id"])

    def test_u32_and_pair_boundaries_are_accepted(self):
        record = self.arena.add_hyperedge(
            PAIR_ID_MAX, 0xFFFFFFFF, 0xFFFFFFFF, 3.4028234663852886e38)
        self.assertEqual(record["pair_id"], PAIR_ID_MAX)
        self.assertEqual(record["concept_id"], 0xFFFFFFFF)
        self.assertEqual(record["relation_type"], 0xFFFFFFFF)
        self.assertEqual(self.arena.pair_head(PAIR_ID_MAX), record["id"])


class PairRangeTests(unittest.TestCase):
    def setUp(self):
        self.arena = MirrorHyperedgeArena()

    def test_pair_clamp_and_strict_validation(self):
        self.assertEqual(clamp_pair_id(-50), PAIR_ID_MIN)
        self.assertEqual(clamp_pair_id(0), PAIR_ID_MIN)
        self.assertEqual(clamp_pair_id(PAIR_ID_MAX), PAIR_ID_MAX)
        self.assertEqual(clamp_pair_id(PAIR_ID_MAX + 1), PAIR_ID_MAX)
        with self.assertRaises(HyperedgeArenaError):
            clamp_pair_id(True)

        low = self.arena.add_hyperedge(
            pair_id=0, concept_id=1, relation_type=1, clamp_pair=True)
        high = self.arena.add_hyperedge(
            pair_id=999999, concept_id=2, relation_type=2, clamp_pair=True)
        self.assertEqual((low["pair_id"], high["pair_id"]),
                         (PAIR_ID_MIN, PAIR_ID_MAX))
        self.assertEqual(self.arena.pair_head(0, clamp=True), low["id"])
        self.assertEqual(self.arena.pair_head(999999, clamp=True), high["id"])

        for bad in (None, 0, PAIR_ID_MAX + 1, -1, 1.0, True, "1"):
            with self.subTest(bad=bad), self.assertRaises(HyperedgeArenaError):
                self.arena.add_hyperedge(bad, 1, 1)
            with self.subTest(bad=bad), self.assertRaises(HyperedgeArenaError):
                self.arena.pair_head(bad)

    def test_explicit_arena_clamp_mode(self):
        arena = MirrorHyperedgeArena(clamp_pairs=True)
        record = arena.add_hyperedge(PAIR_ID_MAX + 100, 1, 1)
        self.assertEqual(record["pair_id"], PAIR_ID_MAX)
        with self.assertRaises(HyperedgeArenaError):
            MirrorHyperedgeArena(clamp_pairs=1)


class PairChainTests(unittest.TestCase):
    def setUp(self):
        self.arena = MirrorHyperedgeArena()
        self.ids = [
            self.arena.add_hyperedge(7, 100, 1, 0.1)["id"],
            self.arena.add_hyperedge(7, 101, 2, 0.2)["id"],
            self.arena.add_hyperedge(7, 102, 3, 0.3)["id"],
        ]

    def test_pair_head_and_next_chain(self):
        self.assertEqual(self.arena.pair_head(7), self.ids[2])
        self.assertEqual(self.arena.pair_head(8), 0)
        self.assertEqual(self.arena.get(self.ids[2])["next"], self.ids[1])
        self.assertEqual(self.arena.get(self.ids[1])["next"], self.ids[0])
        self.assertEqual(self.arena.get(self.ids[0])["next"], NULL_HYPEREDGE_ID)

        full = self.arena.traverse(self.ids[2], max_depth=2, limit=10)
        self.assertEqual(full["ids"], [3, 2, 1])
        self.assertEqual(full["count"], 3)
        self.assertFalse(full["truncated"])
        self.assertEqual(full["terminated"], "end")

    def test_depth_and_limit_bounds(self):
        depth_zero = self.arena.traverse(self.ids[2], max_depth=0, limit=10)
        self.assertEqual(depth_zero["ids"], [3])
        self.assertTrue(depth_zero["truncated"])
        self.assertEqual(depth_zero["terminated"], "depth")

        depth_one = self.arena.traverse(self.ids[2], max_depth=1, limit=10)
        self.assertEqual(depth_one["ids"], [3, 2])
        self.assertTrue(depth_one["truncated"])

        limited = self.arena.traverse(self.ids[2], max_depth=10, limit=2)
        self.assertEqual(limited["ids"], [3, 2])
        self.assertTrue(limited["truncated"])
        self.assertEqual(limited["terminated"], "limit")

        self.assertEqual(self.arena.traverse(self.ids[0], 5, 4)["ids"], [1])
        empty = self.arena.traverse(0)
        self.assertEqual(empty["ids"], [])
        self.assertEqual(empty["terminated"], "null")
        missing = self.arena.traverse(999)
        self.assertEqual(missing["ids"], [])


class IncidenceTests(unittest.TestCase):
    def setUp(self):
        self.arena = MirrorHyperedgeArena()
        self.ids = [
            self.arena.add_hyperedge(1, 9, 1)["id"],
            self.arena.add_hyperedge(2, 9, 2)["id"],
            self.arena.add_hyperedge(1, 10, 3)["id"],
            self.arena.add_hyperedge(1, 9, 4)["id"],
        ]

    def test_concept_incidence_is_newest_first_and_bounded(self):
        page = self.arena.incident_hyperedges(concept=9, limit=2)
        self.assertEqual(page["ids"], [4, 2])
        self.assertEqual(page["total"], 3)
        self.assertTrue(page["truncated"])
        self.assertEqual([r["id"] for r in page["records"]], [4, 2])
        self.assertEqual(
            self.arena.incident_hyperedges(concept_id=10)["ids"], [3])
        self.assertEqual(
            self.arena.incident_hyperedges(concept=77)["ids"], [])

    def test_pair_and_joint_incidence(self):
        self.assertEqual(
            self.arena.incident_hyperedges(pair=1)["ids"], [4, 3, 1])
        joint = self.arena.incident_hyperedges(pair=1, concept=9)
        self.assertEqual(joint["ids"], [4, 1])
        self.assertEqual(joint["total"], 2)
        with self.assertRaises(HyperedgeArenaError):
            self.arena.incident_hyperedges()
        with self.assertRaises(HyperedgeArenaError):
            self.arena.incident_hyperedges(pair=1, pair_id=1)


class DuplicateMembershipTests(unittest.TestCase):
    def test_duplicate_payload_appends_new_id_and_membership(self):
        arena = MirrorHyperedgeArena()
        first = arena.add_hyperedge(5, 6, 7, 0.25)
        digest_before = arena.digest
        second = arena.add_hyperedge(5, 6, 7, 0.25)
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(second["next"], first["id"])
        self.assertEqual(arena.pair_head(5), second["id"])
        self.assertNotEqual(arena.digest, digest_before)
        self.assertEqual(arena.incident_hyperedges(pair=5)["ids"],
                         [second["id"], first["id"]])
        self.assertEqual(arena.incident_hyperedges(concept=6)["ids"],
                         [second["id"], first["id"]])
        status = arena.status()
        self.assertEqual(status["pair_count"], 1)
        self.assertEqual(status["concept_count"], 1)
        self.assertEqual(status["membership_count"], 2)
        self.assertEqual(status["record_count"], 2)


class SerializationTests(unittest.TestCase):
    def setUp(self):
        self.arena = MirrorHyperedgeArena()
        self.arena.add_hyperedge(1, 10, 1, 0.1)
        self.arena.add_hyperedge(1, 11, 2, 0.2, parent_hyperedge_id=1)
        self.arena.add_hyperedge(2, 10, 3, 1.5)

    def test_roundtrip_schema_version_digest_and_json(self):
        data = self.arena.to_dict()
        self.assertEqual(data["schema"], SCHEMA)
        self.assertEqual(data["version"], VERSION)
        self.assertEqual(data["record_count"], 3)
        self.assertEqual(data["next_id"], 4)
        self.assertEqual(data["digest"], record_digest(data["records"]))
        self.assertEqual(len(data["digest"]), 64)

        clone = MirrorHyperedgeArena.from_dict(data)
        self.assertEqual(clone.to_dict(), data)
        self.assertEqual(clone.digest, self.arena.digest)
        self.assertEqual(clone.status()["digest"], self.arena.digest)
        clone.add_hyperedge(3, 12, 4, 2.0)
        self.assertEqual(self.arena.status()["record_count"], 3)

        text = self.arena.to_json()
        self.assertEqual(MirrorHyperedgeArena.from_json(text).to_dict(), data)
        self.assertEqual(
            MirrorHyperedgeArena.from_dict(text).to_dict(), data)

    def test_tampering_and_structural_replay_are_rejected(self):
        data = self.arena.to_dict()
        for mutate in (
                lambda d: d.update(schema="other"),
                lambda d: d.update(version=VERSION + 1),
                lambda d: d.update(digest="0" * 64),
                lambda d: d["records"][0].update(strength=99.0),
                lambda d: d["records"][2].update(id=9),
                lambda d: d["pair_heads"].update({"1": 1}),
                lambda d: d["concept_incidence"].update({"10": [2]}),
                lambda d: d.pop("digest")):
            tampered = json.loads(json.dumps(data))
            mutate(tampered)
            with self.subTest(mutate=mutate), self.assertRaises(
                    HyperedgeArenaError):
                MirrorHyperedgeArena.from_dict(tampered)

        # A structurally impossible chain is rejected even when its digest is
        # recomputed, so a malicious reserialization cannot forge membership.
        broken = json.loads(json.dumps(data))
        broken["records"][1]["next"] = 0
        broken["digest"] = record_digest(broken["records"])
        with self.assertRaises(HyperedgeArenaError):
            MirrorHyperedgeArena.from_dict(broken)

        # Missing derived views are optional; the append history still rules.
        minimal = json.loads(json.dumps(data))
        minimal.pop("pair_heads")
        minimal.pop("concept_incidence")
        self.assertEqual(MirrorHyperedgeArena.from_dict(minimal).to_dict(),
                         data)


class BoundsAndInvalidInputTests(unittest.TestCase):
    def setUp(self):
        self.arena = MirrorHyperedgeArena()
        self.arena.add_hyperedge(1, 1, 1, 1.0)

    def test_bounded_limits_fail_closed(self):
        for limit in (0, -1, MAX_LIMIT + 1, 1.0, True, None):
            with self.subTest(limit=limit), self.assertRaises(
                    HyperedgeArenaError):
                self.arena.incident_hyperedges(pair=1, limit=limit)
            with self.subTest(limit=limit), self.assertRaises(
                    HyperedgeArenaError):
                self.arena.traverse(1, limit=limit)
        for depth in (-1, MAX_DEPTH + 1, 1.0, True, None, "1"):
            with self.subTest(depth=depth), self.assertRaises(
                    HyperedgeArenaError):
                self.arena.traverse(1, max_depth=depth)
        self.assertEqual(
            len(self.arena.incident_hyperedges(
                pair=1, limit=DEFAULT_LIMIT)["ids"]), 1)

    def test_invalid_fields_do_not_mutate_append_history(self):
        before = self.arena.to_dict()
        invalids = (
            dict(pair_id=1, concept_id=-1, relation_type=1),
            dict(pair_id=1, concept_id=2 ** 32, relation_type=1),
            dict(pair_id=1, concept_id=1.0, relation_type=1),
            dict(pair_id=1, concept_id=True, relation_type=1),
            dict(pair_id=1, concept_id=1, relation_type=-1),
            dict(pair_id=1, concept_id=1, relation_type=2 ** 32),
            dict(pair_id=1, concept_id=1, relation_type=1, strength=float("nan")),
            dict(pair_id=1, concept_id=1, relation_type=1, strength=float("inf")),
            dict(pair_id=1, concept_id=1, relation_type=1, strength="1"),
            dict(pair_id=1, concept_id=1, relation_type=1, strength=True),
            dict(pair_id=1, concept_id=1, relation_type=1,
                 parent_hyperedge_id=2),
            dict(pair_id=1, concept_id=1, relation_type=1,
                 parent_hyperedge_id=-1),
            dict(pair_id=1, concept_id=1, relation_type=1,
                 parent_hyperedge_id=1.0),
            dict(pair_id=1, concept_id=1, relation_type=1,
                 parent_hyperedge_id=True),
        )
        for fields in invalids:
            with self.subTest(fields=fields), self.assertRaises(
                    HyperedgeArenaError):
                self.arena.add_hyperedge(**fields)
            self.assertEqual(self.arena.to_dict(), before)

        with self.assertRaises(HyperedgeArenaError):
            self.arena.add_hyperedge(1, 1, 1, clamp_pair="yes")
        with self.assertRaises(HyperedgeArenaError):
            self.arena.add_hyperedge(1, 1, 1, pair=1)
        with self.assertRaises(HyperedgeArenaError):
            self.arena.add_hyperedge(pair=1, concept=1, relation=1,
                                     relation_type=1)
        self.assertEqual(self.arena.to_dict(), before)
        self.assertEqual(self.arena.add_hyperedge(1, 1, 1)["id"], 2)

    def test_get_and_traverse_reject_non_integer_ids(self):
        for bad in (-1, 2 ** 32, 1.0, True, "1", None):
            with self.subTest(bad=bad), self.assertRaises(
                    HyperedgeArenaError):
                self.arena.get(bad)
            with self.subTest(bad=bad), self.assertRaises(
                    HyperedgeArenaError):
                self.arena.traverse(bad)

    def test_short_alias_and_record_shape(self):
        arena = HyperedgeArena()
        record = arena.add_hyperedge(1, 2, 3, 0.5)
        self.assertEqual(set(record), {
            "id", "pair_id", "concept_id", "relation_type", "strength",
            "next", "parent_hyperedge_id",
        })
        self.assertEqual(arena.digest, record_digest([record]))


if __name__ == "__main__":
    unittest.main()
