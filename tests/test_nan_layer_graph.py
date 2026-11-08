import tempfile
import unittest
from runner_riddle.math_objects import MathLeaf
from runner_riddle.math_store import MathStore, StaleGenerationError
from runner_riddle.wave_store import WaveStore
from runner_riddle.nan_layer_graph import NanLayerGraph, NanGraphError, cell, cell_route


class NanLayerGraphTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bs,mc=tmp.name+"/bs.sqlite",tmp.name+"/mc.sqlite"
        WaveStore(bs,mc)
        self.store=MathStore(bs,mc)
        self.graph=NanLayerGraph(self.store)
        self.leaf=self.store.put_leaf(MathLeaf(
            leaf_id="nml:evidence:1",kind="scalar",type={"kind":"scalar"},
            content={"value":7},provenance={"producer":"test"}))

    def proposal(self, **updates):
        params=dict(edge_id="e1",src_kind="head",src_id=7,
                    dst_kind="mp",dst_id=9,layer=4,relation="supports",
                    source_head=7,evidence_id=self.leaf.leaf_id,
                    evidence_version=1,evidence_digest=self.leaf.digest())
        params.update(updates)
        return self.graph.propose(**params)

    def test_l0_l9_address_matrix_and_immutable_evidence(self):
        self.assertEqual(cell("head",255),255)
        self.assertEqual(cell("mp",32639),32895)
        self.assertEqual(cell_route(32895),"HW0:MP32639")
        self.assertEqual(self.graph.neighbors(kind="head",ordinal=7)["total"],0)
        result=self.proposal()
        self.assertEqual(result["generation"],1)
        self.assertFalse(result["mathematical_truth_promoted"])
        self.assertEqual(self.graph.neighbors(kind="head",ordinal=7,layer=4)["total"],1)
        self.assertEqual(self.graph.neighbors(kind="mp",ordinal=9)["total"],1)
        self.assertEqual(self.graph.neighbors(kind="head",ordinal=7,layer=3)["total"],0)
        self.assertEqual(self.proposal(expected_generation=1,layer=9)["generation"],2)
        self.assertEqual(self.graph.neighbors(kind="head",ordinal=7,layer=9)["total"],1)
        with self.store._connect(self.store.mc0_path) as db:
            self.assertEqual(db.execute(
                "SELECT count(*) FROM nan_layer_edge_history").fetchone()[0],2)

    def test_fail_closed_stale_acl_digest_and_layer(self):
        for updates in (dict(source_head=0),dict(source_head=99),
                        dict(layer=10),dict(layer=-1),
                        dict(evidence_digest="0"*64),
                        dict(expected_generation=1),
                        dict(relation="invented")):
            with self.subTest(updates=updates),self.assertRaises(
                    (NanGraphError,StaleGenerationError)):
                self.proposal(**updates)
        self.assertEqual(self.graph.neighbors(kind="head",ordinal=7)["total"],0)
        self.proposal()
        with self.assertRaises(StaleGenerationError):
            self.proposal()
        with self.assertRaises(NanGraphError):
            self.graph.neighbors(kind="head",ordinal=7,limit=101)
