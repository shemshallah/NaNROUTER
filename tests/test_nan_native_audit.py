"""Static NaN-native boundary audit regression tests."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.audit_nan_native import (
    REPO_ROOT,
    SPEC_PATH,
    _layer_for,
    _workflow_fixture_mentions,
    audit,
)


class NanNativeAuditTests(unittest.TestCase):
    def test_audit_is_green_and_covers_registered_native_sources(self):
        report = audit()
        self.assertEqual(report["status"], "green", report["errors"])
        self.assertEqual(report["kernel_count"], 159)
        self.assertEqual(report["native_source_count"], 157)
        self.assertEqual(report["unique_fixture_count"], 154)
        self.assertEqual(report["runner_fixture_count"], 155)
        self.assertEqual(sum(report["layer_counts"].values()), 159)
        self.assertEqual(report["layer_counts"]["L1"], 6)
        self.assertEqual(report["layer_counts"]["L2"], 7)
        self.assertEqual(report["layer_counts"]["L3"], 42)
        self.assertEqual(report["layer_counts"]["L4"], 87)
        self.assertEqual(report["layer_counts"]["L5"], 11)

    def test_graph_claim_probe_is_catalogued_but_separately_gated(self):
        """A tracked candidate query is not a math proof or native promotion."""
        spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        name = "mth/nan16/mth_graph_claim_probe.nas"
        manifest = json.loads(
            (REPO_ROOT / spec["manifest"]).read_text(encoding="utf-8")
        )
        candidates = [
            k for k in manifest["kernels"]
            if k.get("source") == name
        ]
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["kernel_id"], "mth.graph.claim_probe.u32")
        self.assertEqual(
            candidates[0]["fixture"], "mth/tests/mth_graph_claim_probe_test.nas"
        )
        self.assertNotIn(name, spec["excluded_native_sources"])
        self.assertTrue((REPO_ROOT / name).is_file())
        workflow = (
            REPO_ROOT / ".github/workflows/native-graph-claim-probe.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("mth_graph_claim_probe_test.nas", workflow)
        self.assertEqual(audit()["status"], "green")

    def test_unregistered_graph_path_witness_has_independent_ci_not_math_authority(self):
        spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        name = "mth/nan16/mth_graph_path_witness.nas"
        self.assertIn(name, spec["excluded_native_sources"])
        self.assertIn("not an authorized numerical MTH kernel",
                      spec["excluded_native_sources"][name])
        self.assertTrue((REPO_ROOT / name).is_file())
        self.assertTrue(
            (REPO_ROOT / "mth/tests/mth_graph_path_witness_test.nas").is_file()
        )
        workflow = (
            REPO_ROOT / ".github/workflows/native-graph-path-witness.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("mth_graph_path_witness_test.nas", workflow)
        self.assertEqual(audit()["status"], "green")

    def test_graph_claim_batch_has_independent_native_ci_and_no_promotion(self):
        spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        source = "mth/nan16/mth_graph_claim_batch.nas"
        self.assertIn(source, spec["excluded_native_sources"])
        self.assertIn("not an authorized numerical MTH kernel",
                      spec["excluded_native_sources"][source])
        self.assertTrue((REPO_ROOT / source).is_file())
        fixture = "mth/tests/mth_graph_claim_batch_test.nas"
        self.assertTrue((REPO_ROOT / fixture).is_file())
        workflow = (REPO_ROOT / ".github/workflows/native-graph-claim-batch.yml"
                    ).read_text(encoding="utf-8")
        self.assertIn(fixture, workflow)
        self.assertEqual(audit()["status"], "green")

    def test_new_kernels_receive_the_expected_layer(self):
        spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            _layer_for("mth.vector.normalize256.f32", spec["layers"]), "L3"
        )
        self.assertEqual(
            _layer_for("mth.vector.prefix_sum256.u32", spec["layers"]), "L3"
        )
        self.assertEqual(
            _layer_for("mth.prng.xorshift64.u64", spec["layers"]), "L2"
        )
        self.assertEqual(
            _layer_for("mth.universe.map.u32", spec["layers"]), "L1"
        )

    def test_all_declared_workflows_are_scanned(self):
        spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        paths = [REPO_ROOT / item for item in spec["ci_workflows"]]
        stems, names, _ = _workflow_fixture_mentions(paths)
        self.assertIn("mth_k256_pair_space_v1_test", stems)
        self.assertIn("vector_normalize256_f32", names)
        self.assertIn("vector_prefix_sum256_u32", names)
        self.assertIn("prng_xorshift64", names)

    def test_unregistered_native_kernel_fails_closed(self):
        document = json.loads(
            (REPO_ROOT / "spec" / "wave-capabilities.json").read_text(encoding="utf-8")
        )
        document["kernels"].append({
            "kernel_id": "mth.vector.missing.f32",
            "source": "mth/nan16/mth_vector_missing_f32.nas",
            "fixture": "mth/tests/mth_vector_missing_f32_test.nas",
            "marker": "MTH VECTOR MISSING PASS",
            "steps": 1,
            "precision": "float32",
            "workspace_words": 0,
            "shape": [256],
            "status": "native_verified",
            "ci_verified": False,
        })
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(document, handle)
            path = Path(handle.name)
        self.addCleanup(path.unlink)
        report = audit(manifest_path=path)
        self.assertEqual(report["status"], "blocked")
        self.assertTrue(any(
            "missing native source" in error for error in report["errors"]
        ))


if __name__ == "__main__":
    unittest.main()
