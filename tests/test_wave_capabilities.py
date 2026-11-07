import json
import tempfile
import unittest
from pathlib import Path

from runner_riddle.wave_store import WaveStore
from tools.register_wave_capabilities import (
    DEFAULT_MANIFEST,
    load_manifest,
    register_manifest,
)


class WaveCapabilityTests(unittest.TestCase):
    def test_manifest_has_all_expected_kernels(self):
        manifest = load_manifest(DEFAULT_MANIFEST)
        ids = {kernel["kernel_id"] for kernel in manifest["kernels"]}
        self.assertIn("mth.k255.laplacian.u16", ids)
        self.assertIn("mth.ring255.port.f32", ids)
        self.assertIn("mth.graph.dft256.f32", ids)
        self.assertIn("mth.graph.couple128.f32", ids)
        self.assertIn("mth.graph.pair.tile16.f32", ids)
        self.assertIn("mth.graph.pair.full.128.f32", ids)
        self.assertEqual(len(ids), 35)

    def test_dry_run_does_not_need_a_store(self):
        manifest = load_manifest(DEFAULT_MANIFEST)
        rows = register_manifest(None, manifest, runner_id="MC0:0/R0", dry_run=True)
        self.assertEqual(len(rows), 35)
        self.assertTrue(all(len(row["source_digest"]) == 64 for row in rows))

    def test_register_manifest_into_mc0db(self):
        manifest = load_manifest(DEFAULT_MANIFEST)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = WaveStore(root / "bs0db.sqlite3", root / "mc0db.sqlite3")
            rows = register_manifest(
                store, manifest, runner_id="MC0:0/R0", epoch=1, nanclock_tick=7
            )
            self.assertEqual(len(rows), 35)
            for row in rows:
                capability = store.dispatchable_capabilities(
                    workspace=row["workspace_words"],
                    operator_digest=row["source_digest"],
                    precision=row["precision"],
                )
                self.assertTrue(capability, row["kernel_id"])
                self.assertIn(
                    row["kernel_id"],
                    {entry["kernel_id"] for entry in capability},
                )
            health = store.health()
            self.assertEqual(health["schema_version"], 1)

    def test_manifest_json_is_valid(self):
        document = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(document["schema"], "nanrouter.wave-capabilities.v1")


if __name__ == "__main__":
    unittest.main()
