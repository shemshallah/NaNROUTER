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

    def test_retract_preserves_evidence_and_history_and_can_reactivate(self):
        self.proposal(tick=3)
        tombstone = self.graph.retract(
            edge_id="e1",source_head=7,expected_generation=1,tick=4)
        self.assertEqual(tombstone["status"],"retracted")
        self.assertEqual(tombstone["generation"],2)
        self.assertFalse(tombstone["native_executed"])
        self.assertEqual(self.graph.neighbors(kind="head",ordinal=7)["total"],0)
        with self.store._connect(self.store.mc0_path) as db:
            self.assertEqual(db.execute(
                "SELECT count(*) FROM nan_layer_edge_history").fetchone()[0],2)
        with self.assertRaises(StaleGenerationError):
            self.graph.retract(edge_id="e1",source_head=7,expected_generation=1,tick=5)
        with self.assertRaises(NanGraphError):
            self.graph.retract(edge_id="e1",source_head=7,expected_generation=2,tick=5)
        replay = self.proposal(expected_generation=2,tick=5)
        self.assertEqual((replay["generation"], replay["status"]),(3,"candidate"))
        self.assertEqual(self.graph.neighbors(kind="head",ordinal=7)["total"],1)

    def test_rewrite_authority_and_tick_are_immutable(self):
        self.proposal(tick=8)
        for invalid in (
            dict(source_head=10),
            dict(src_id=8,source_head=8),
            dict(dst_id=11),
            dict(tick=7),
        ):
            with self.subTest(invalid=invalid),self.assertRaises(NanGraphError):
                self.proposal(expected_generation=1,**invalid)
        for invalid in (dict(source_head=10),dict(tick=7)):
            with self.subTest(invalid=invalid),self.assertRaises(NanGraphError):
                self.graph.retract(edge_id="e1",expected_generation=1,**invalid)

    def test_master_commitment_stable_between_pages_and_parent_bound(self):
        parent="a"*64
        blank=self.graph.master_graph_page(
            parent_root_sha256=parent,chart_generation=5)
        self.assertEqual(blank["total_edges"],0)
        self.assertTrue(blank["snapshot_consistent"])
        self.proposal(tick=2)
        self.proposal(edge_id="e2",expected_generation=0,tick=2,layer=9)
        first=self.graph.master_graph_page(
            parent_root_sha256=parent,chart_generation=5,limit=1)
        second=self.graph.master_graph_page(
            parent_root_sha256=parent,chart_generation=5,offset=1,limit=1)
        self.assertEqual(first["total_edges"],2)
        self.assertEqual(first["next_offset"],1)
        self.assertEqual(second["next_offset"],None)
        self.assertEqual(first["graph_commitment_sha256"],
                         second["graph_commitment_sha256"])
        self.assertNotEqual(blank["state_sha256"],first["state_sha256"])
        alternate=self.graph.master_graph_page(
            parent_root_sha256="b"*64,chart_generation=5,limit=1)
        self.assertEqual(alternate["state_sha256"],first["state_sha256"])
        self.assertNotEqual(alternate["graph_commitment_sha256"],
                            first["graph_commitment_sha256"])
        self.graph.retract(edge_id="e1",source_head=7,
                           expected_generation=1,tick=3)
        tomb=self.graph.master_graph_page(
            parent_root_sha256=parent,chart_generation=5)
        self.assertEqual((tomb["candidate_edges"],tomb["retracted_edges"]),(1,1))
        self.assertNotEqual(tomb["history_sha256"],first["history_sha256"])
        self.assertFalse(tomb["signed_by_router"])
        self.assertFalse(tomb["native_mth_receipt"])

    def test_detects_history_and_state_corruption(self):
        self.proposal()
        parent="c"*64
        with self.store._write(self.store.mc0_path) as db:
            db.execute("UPDATE nan_layer_edge SET relation='refutes' "
                       "WHERE edge_id='e1'")
        with self.assertRaises(NanGraphError):
            self.graph.master_graph_page(
                parent_root_sha256=parent,chart_generation=0)

    def test_invalid_projection_parameters_fail_closed(self):
        for kw in (dict(parent_root_sha256="bad"),
                   dict(chart_generation=-1),
                   dict(limit=101),dict(limit=0),
                   dict(offset=-1),dict(chart_generation=True)):
            args=dict(parent_root_sha256="a"*64,chart_generation=0)
            args.update(kw)
            with self.subTest(args=args),self.assertRaises(NanGraphError):
                self.graph.master_graph_page(**args)
