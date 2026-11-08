"""Sparse L0-L9 mirror relation matrix: one parent, one graph, no proof bypass."""
import hashlib
import tempfile
import unittest

from runner_riddle.address import AddressError, LayerSelector, parse_address
from runner_riddle.math_store import MathStore, StaleGenerationError
from runner_riddle.mirror_point_register import pair_number
from runner_riddle.mirror_layer_matrix import (
    ROOT_ROUTE, SCHEMA, LayerMatrixError, NanLayerMatrix,
)
from runner_riddle.wave_store import WaveStore


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


class LayerAddressTests(unittest.TestCase):
    def test_l0_l9_roundtrips_head_mp_and_head_prefixed_mp(self):
        for path in ("::HW0:1::L0", "::HW0:255::L9",
                     "::HW0:MP0::L0", "::HW0:MP32639::L9",
                     "::HW0:7::HW0:MP100::L5"):
            parsed = parse_address(ROOT_ROUTE + path)
            self.assertEqual(parsed.canonical_with_selectors(), ROOT_ROUTE + path)
            self.assertEqual(len(parsed.layer_selectors), 1)
            self.assertIsInstance(parsed.layer_selectors[0], LayerSelector)
        for wrong in ("::L1", "::HW0:MP1::L10", "::HW0:MP1::L0::L1",
                      "::HW0:MP1::vector#x::L3", "::HW0:MP1::L-1"):
            with self.subTest(wrong=wrong), self.assertRaises(AddressError):
                parse_address(ROOT_ROUTE + wrong)
        self.assertEqual(parse_address(ROOT_ROUTE + "::HW0:MP1").layer_selectors, ())


class LearnedLayerMatrixTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        bs, mc = temp.name + "/bs0.db", temp.name + "/mc0.db"
        WaveStore(bs, mc)
        self.store = MathStore(bs, mc)
        self.root = sha("canonical 8MiB chart")
        self.matrix = NanLayerMatrix(self.store, canonical_parent_sha256=self.root)

    def propose(self, **overrides):
        mp = pair_number(7, 200)
        info = dict(source_kind="mp", source_id=mp, source_layer=3,
                    target_kind="head", target_id=9, target_layer=3,
                    relation="related", polarity=1, strength_q16=32768,
                    evidence_sha256=sha("lesson A"), source_head=7,
                    expected_generation=0, tick=11)
        info.update(overrides)
        return self.matrix.propose(**info)

    def test_read_only_unbound_routes_and_structural_algebra(self):
        mp = pair_number(7, 200)
        before = self.matrix.route(ROOT_ROUTE + f"::HW0:7::HW0:MP{mp}::L3")
        self.assertFalse(before["coordinate"]["bound"])
        self.assertEqual(before["resolution"], "L3")
        self.assertEqual(before["structural"]["total"], 2)
        self.assertEqual([x["id"] for x in before["structural"]["neighbors"]], [7, 200])
        head = self.matrix.route(ROOT_ROUTE + "::HW0:7::L0", limit=8)
        self.assertEqual(head["structural"]["total"], 255)
        self.assertEqual(len(head["structural"]["neighbors"]), 8)
        self.assertEqual(head["learned"]["relations"], [])
        self.assertEqual(self.matrix.structural(kind="head", ordinal=0)["total"], 255)
        with self.store._connect(self.store.mc0_path) as db:
            self.assertFalse(db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='nan_layer_relation'"
            ).fetchone())

    def test_sparse_edge_cas_history_and_recovery(self):
        first = self.propose()
        self.assertEqual(first["generation"], 1)
        self.assertFalse(first["native_execution_verified"])
        self.assertFalse(first["math_rule_promoted"])
        mp = pair_number(7, 200)
        rows = self.matrix.neighbors(kind="mp", ordinal=mp, layer=3)["relations"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["strength_q16"], 32768)
        self.assertEqual(rows[0]["target_id"], 9)
        self.assertEqual(self.propose(expected_generation=1)["generation"], 1)
        second = self.propose(expected_generation=1, polarity=-1,
                              evidence_sha256=sha("counterevidence"), tick=12)
        self.assertEqual(second["generation"], 2)
        new = self.matrix.neighbors(kind="mp", ordinal=mp, layer=3)["relations"][0]
        self.assertEqual(new["polarity"], -1)
        with self.store._connect(self.store.mc0_path) as db:
            history = db.execute(
                "SELECT generation,polarity FROM nan_layer_relation_history "
                "WHERE edge_id=? ORDER BY generation",
                (first["edge_id"],)).fetchall()
        self.assertEqual([(x["generation"],x["polarity"]) for x in history],
                         [(1, 1), (2, -1)])
        with self.assertRaises(StaleGenerationError):
            self.propose(expected_generation=1, polarity=0)
        self.assertEqual(self.matrix.neighbors(
            kind="mp", ordinal=mp, layer=3)["relations"][0]["generation"], 2)
        reopened = NanLayerMatrix(self.store, canonical_parent_sha256=self.root)
        self.assertEqual(reopened.neighbors(
            kind="mp", ordinal=mp, layer=3)["relations"][0]["generation"], 2)

    def test_parent_root_isolation_and_candidate_not_truth(self):
        self.propose()
        other = NanLayerMatrix(self.store, canonical_parent_sha256=sha("second universe"))
        mp = pair_number(7, 200)
        self.assertEqual(other.neighbors(kind="mp", ordinal=mp, layer=3)["relations"], [])
        self.assertEqual(self.matrix.neighbors(kind="mp", ordinal=mp, layer=3)
                         ["relations"][0]["topology_digest"],
                         other.neighbors(kind="mp", ordinal=mp, layer=3)["topology_sha256"])
        with self.assertRaises(LayerMatrixError):
            NanLayerMatrix(self.store, canonical_parent_sha256="invalid")

    def test_abstraction_and_refinement_are_exactly_adjacent(self):
        mp = pair_number(7, 200)
        first = self.propose(target_kind="mp",target_id=pair_number(9, 10),
                             target_layer=4,relation="abstracts_to")
        self.assertEqual(first["generation"], 1)
        self.assertEqual(self.matrix.neighbors(
            kind="mp",ordinal=mp,layer=3)["relations"][0]["target_layer"], 4)
        second = self.matrix.propose(
            source_kind="mp",source_id=pair_number(9,10),source_layer=4,
            target_kind="mp",target_id=mp,target_layer=3,relation="refines",
            polarity=1,strength_q16=20000,evidence_sha256=sha("lesson B"),
            source_head=9,expected_generation=0)
        self.assertEqual(second["generation"], 1)
        walked = self.matrix.walk(kind="mp",ordinal=mp,layer=3,
                                  depth=2,max_nodes=8)
        self.assertIn(["mp",pair_number(9,10),4], walked["nodes"])
        self.assertEqual(len(walked["edges"]), 2)
        with self.assertRaises(LayerMatrixError):
            self.propose(relation="abstracts_to",target_layer=5)
        with self.assertRaises(LayerMatrixError):
            self.propose(relation="related",target_layer=4)

    def test_bounded_scratch_and_denials(self):
        self.propose()
        mp = pair_number(7, 200)
        for params in (
                {"source_head": 0}, {"source_head": 8},
                {"source_layer": 10}, {"source_layer": True},
                {"target_layer": -1}, {"target_kind": "head", "target_id": 0},
                {"relation": "arbitrary_native_op"},
                {"polarity": 2}, {"polarity": True},
                {"strength_q16": 100000},
                {"expected_generation": True}, {"evidence_sha256": "a"},
                {"target_kind": "nonexistent"}):
            with self.subTest(params=params), self.assertRaises(LayerMatrixError):
                self.propose(**params)
        for bad in (
                ROOT_ROUTE+"::HW0:MP0-32639::L5",
                ROOT_ROUTE+"::HW0:MP3::L4::vector#9",
                ROOT_ROUTE.replace("GM0:0", "GM2:0")+"::HW0:MP3::L1"):
            with self.subTest(bad=bad), self.assertRaises(LayerMatrixError):
                self.matrix.route(bad)
        with self.assertRaises(LayerMatrixError):
            self.matrix.neighbors(kind="mp", ordinal=mp, layer=3, limit=65)
        with self.assertRaises(LayerMatrixError):
            self.matrix.walk(kind="mp",ordinal=mp,layer=3,depth=5)
        self.assertEqual(self.matrix.walk(kind="mp",ordinal=mp,layer=3,
                                          depth=0)["edges"], [])


if __name__ == "__main__":
    unittest.main()
