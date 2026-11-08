"""Revision pages are a read-only projection, not a signed learning receipt."""
import hashlib
import json
import tempfile
import unittest

from runner_riddle.math_objects import MathLeaf
from runner_riddle.math_store import MathStore
from runner_riddle.nan_layer_graph import NanLayerGraph, NanGraphError
from runner_riddle.wave_store import WaveStore


class GraphHistoryProjectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        bs, mc = temporary.name + "/bs.sqlite", temporary.name + "/mc.sqlite"
        WaveStore(bs, mc)
        self.store = MathStore(bs, mc)
        self.graph = NanLayerGraph(self.store)
        self.leaf = self.store.put_leaf(MathLeaf(
            leaf_id="nml:evidence:history", kind="scalar",
            type={"kind": "scalar"}, content={"value": 7},
            provenance={"producer": "history-test"},
        ))
        self.evidence = dict(evidence_id=self.leaf.leaf_id,
                             evidence_version=1,
                             evidence_digest=self.leaf.digest())

    def project(self, history_offset=None, history_limit=1):
        return self.graph.master_graph_page(
            parent_root_sha256="a" * 64, chart_generation=7,
            limit=1, history_offset=history_offset,
            history_limit=history_limit,
        )

    def test_history_pages_bind_full_digest_and_preserve_tombstones(self):
        self.graph.propose(edge_id="a", src_kind="head", src_id=7,
                           dst_kind="mp", dst_id=9, layer=4,
                           relation="supports", source_head=7,
                           tick=3, **self.evidence)
        self.graph.retract(edge_id="a", source_head=7,
                           expected_generation=1, tick=4)
        self.graph.propose(edge_id="b", src_kind="head", src_id=7,
                           dst_kind="mp", dst_id=9, layer=5,
                           relation="refutes", source_head=7,
                           tick=5, **self.evidence)
        pages = [self.project(i) for i in range(3)]
        baseline = pages[0]
        self.assertEqual([p["history_offset"] for p in pages], [0, 1, 2])
        self.assertEqual([p["history_next_offset"] for p in pages],
                         [1, 2, None])
        self.assertEqual([p["history_total"] for p in pages], [3] * 3)
        self.assertEqual([p["graph_commitment_sha256"] for p in pages],
                         [baseline["graph_commitment_sha256"]] * 3)
        revisions = [p["history_entries"][0] for p in pages]
        self.assertEqual([(r["edge_id"], r["generation"]) for r in revisions],
                         [("a", 1), ("a", 2), ("b", 1)])
        self.assertEqual(json.loads(revisions[1]["payload"])["status"],
                         "retracted")
        history = hashlib.sha256(b"nanrouter.nan-layer-history/1\0")
        for entry in revisions:
            raw = json.dumps([entry["edge_id"], entry["generation"],
                              entry["payload"]], sort_keys=True,
                             separators=(",", ":")).encode()
            history.update(len(raw).to_bytes(8, "big") + raw)
        self.assertEqual(history.hexdigest(), baseline["history_sha256"])
        legacy = self.project()
        self.assertNotIn("history_entries", legacy)
        self.assertFalse(baseline["signed_by_router"])
        self.assertFalse(baseline["native_mth_receipt"])

    def test_invalid_history_cursors_fail_closed(self):
        for changes in ({"history_offset": -1},
                        {"history_offset": True},
                        {"history_offset": 0, "history_limit": 0},
                        {"history_offset": 0, "history_limit": 101},
                        {"history_offset": 0, "history_limit": True}):
            with self.subTest(changes=changes), self.assertRaises(NanGraphError):
                self.project(**changes)

    def test_concurrent_graph_revision_changes_commitment(self):
        self.graph.propose(edge_id="a", src_kind="head", src_id=7,
                           dst_kind="mp", dst_id=9, layer=4,
                           relation="supports", source_head=7,
                           tick=1, **self.evidence)
        first = self.project(0)
        self.graph.retract(edge_id="a", source_head=7,
                           expected_generation=1, tick=2)
        second = self.project(1)
        self.assertNotEqual(first["graph_commitment_sha256"],
                            second["graph_commitment_sha256"])
        self.assertNotEqual(first["history_sha256"], second["history_sha256"])


if __name__ == "__main__":
    unittest.main()
