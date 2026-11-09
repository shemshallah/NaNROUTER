import json
import tempfile
import unittest
from pathlib import Path

from runner_riddle.wave_store import WaveStore
from runner_riddle.wave_ring_scheduler import MC0_SLOTS
from tools.register_wave_capabilities import (
    DEFAULT_GUEST_WORKSPACE_WORDS,
    DEFAULT_MANIFEST,
    WORDS_PER_MIB,
    load_manifest,
    parse_args,
    register_manifest,
    resolve_guest_workspace_words,
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
        self.assertIn("mth.graph.degree.256.u32", ids)
        self.assertIn("mth.graph.pattern.256.u32", ids)
        self.assertIn("mth.graph.filter.poly2.q16.16", ids)
        self.assertIn("mth.jahs.gate.u64", ids)
        self.assertIn("mth.matvec256.full.f32", ids)
        self.assertIn("mth.svd.top2.256.f32", ids)
        self.assertIn("mth.topk.256.f32", ids)
        self.assertIn("mth.stage0.word_layout.u32", ids)
        self.assertIn("mth.double_endian.pair.u32", ids)
        self.assertIn("mth.vector.span_add.checked.u32", ids)
        self.assertIn("mth.preflight.typed.u32", ids)
        self.assertIn("mth.execute.native_dispatch.f32", ids)
        self.assertIn("mth.vector.normalize256.f32", ids)
        self.assertIn("mth.vector.prefix_sum256.u32", ids)
        self.assertIn("mth.prng.xorshift64.u64", ids)
        self.assertEqual(len(ids), 96)

    def test_dry_run_does_not_need_a_store(self):
        manifest = load_manifest(DEFAULT_MANIFEST)
        rows = register_manifest(None, manifest, runner_id="MC0:0/R0", dry_run=True)
        self.assertEqual(len(rows), 96)
        self.assertTrue(all(len(row["source_digest"]) == 64 for row in rows))

    def test_register_manifest_into_mc0db(self):
        manifest = load_manifest(DEFAULT_MANIFEST)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = WaveStore(root / "bs0db.sqlite3", root / "mc0db.sqlite3")
            rows = register_manifest(
                store, manifest, runner_id="MC0:0/R0", epoch=1, nanclock_tick=7
            )
            self.assertEqual(len(rows), 96)
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


    def test_all_six_slots_register_at_2_mib_and_legacy_rejects_196608_words(self):
        manifest = load_manifest(DEFAULT_MANIFEST)
        target = next(
            kernel for kernel in manifest["kernels"]
            if kernel["kernel_id"] == "mth.graph.pair.tile16.f32"
        )
        dry_rows = register_manifest(
            None, manifest, runner_id="dry", dry_run=True
        )
        digest = next(
            row["source_digest"] for row in dry_rows
            if row["kernel_id"] == target["kernel_id"]
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = WaveStore(root / "bs0.sqlite3", root / "mc0.sqlite3")
            for slot in MC0_SLOTS:
                register_manifest(
                    store, manifest, runner_id=slot, epoch=2,
                    guest_workspace_words=262_144,
                )
            rows = store.dispatchable_capabilities(
                workspace=target["workspace_words"],
                operator_digest=digest,
                precision=target["precision"],
            )
            self.assertEqual(
                {row["runner_id"] for row in rows}, set(MC0_SLOTS)
            )

            legacy = WaveStore(
                root / "legacy-bs.sqlite3", root / "legacy-mc.sqlite3"
            )
            register_manifest(
                legacy, manifest, runner_id=MC0_SLOTS[0], epoch=1,
                guest_workspace_words=131_072,
            )
            self.assertEqual(
                legacy.dispatchable_capabilities(
                    workspace=196_608,
                    operator_digest=digest,
                    precision=target["precision"],
                ),
                [],
            )

    def test_guest_budget_gates_full_u_reference(self):
        manifest = load_manifest(DEFAULT_MANIFEST)
        target = next(
            kernel for kernel in manifest["kernels"]
            if kernel["kernel_id"] == "mth.graph.pair.tile16.f32"
        )
        required = target["workspace_words"]
        self.assertEqual(required, 73990)
        dry_rows = register_manifest(
            None, manifest, runner_id="dry", dry_run=True
        )
        digest = next(
            row["source_digest"] for row in dry_rows
            if row["kernel_id"] == target["kernel_id"]
        )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            small = WaveStore(root / "small-bs.sqlite3", root / "small-mc.sqlite3")
            register_manifest(
                small, manifest, runner_id="MC0:0/R512",
                guest_workspace_words=65_536,
            )
            rejected = small.dispatchable_capabilities(
                workspace=required, operator_digest=digest,
                precision=target["precision"],
            )
            self.assertEqual(rejected, [])

            large = WaveStore(root / "large-bs.sqlite3", root / "large-mc.sqlite3")
            register_manifest(
                large, manifest, runner_id="MC0:0/R1M",
                guest_workspace_words=131_072,
            )
            accepted = large.dispatchable_capabilities(
                workspace=required, operator_digest=digest,
                precision=target["precision"],
            )
            self.assertEqual([row["runner_id"] for row in accepted], ["MC0:0/R1M"])

            bigger = WaveStore(root / "big-bs.sqlite3", root / "big-mc.sqlite3")
            register_manifest(
                bigger, manifest, runner_id="MC0:0/R2M",
                guest_workspace_words=262_144,
            )
            admitted = bigger.dispatchable_capabilities(
                workspace=required, operator_digest=digest,
                precision=target["precision"],
            )
            self.assertEqual([row["runner_id"] for row in admitted], ["MC0:0/R2M"])

    def test_guest_workspace_mib_uses_131072_words_per_mib(self):
        self.assertEqual(WORDS_PER_MIB, 131_072)
        self.assertEqual(DEFAULT_GUEST_WORKSPACE_WORDS, 262_144)
        self.assertEqual(
            resolve_guest_workspace_words(mib=1), 131_072
        )
        self.assertEqual(
            resolve_guest_workspace_words(mib=2), 262_144
        )
        self.assertEqual(
            resolve_guest_workspace_words(words=131_072), 131_072
        )
        self.assertEqual(
            resolve_guest_workspace_words(), DEFAULT_GUEST_WORKSPACE_WORDS
        )
        with self.assertRaises(ValueError):
            resolve_guest_workspace_words(words=131_072, mib=1)
        with self.assertRaises(ValueError):
            resolve_guest_workspace_words(mib=-1)

    def test_guest_workspace_mib_selection_resolves_through_cli_parse(self):
        for mib, expected_words in ((1, 131_072), (2, 262_144)):
            with self.subTest(mib=mib):
                args = parse_args(["--guest-workspace-mib", str(mib)])
                self.assertIsNone(args.guest_workspace_words)
                self.assertEqual(args.guest_workspace_mib, mib)
                self.assertEqual(
                    resolve_guest_workspace_words(
                        args.guest_workspace_words, args.guest_workspace_mib
                    ),
                    expected_words,
                )

    def test_manifest_json_is_valid(self):
        document = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(document["schema"], "nanrouter.wave-capabilities.v1")

    def test_graph_core_kernels_are_native_and_ci_verified(self):
        manifest = load_manifest(DEFAULT_MANIFEST)
        by_id = {kernel["kernel_id"]: kernel for kernel in manifest["kernels"]}
        for kernel_id in (
            "mth.graph.degree.256.u32",
            "mth.graph.pattern.256.u32",
            "mth.graph.filter.poly2.q16.16",
        ):
            with self.subTest(kernel_id=kernel_id):
                kernel = by_id[kernel_id]
                self.assertEqual(kernel["status"], "native_verified")
                self.assertTrue(kernel["ci_verified"])
                self.assertLessEqual(kernel["workspace_words"], WORDS_PER_MIB * 2)
        self.assertEqual(
            by_id["mth.graph.filter.poly2.q16.16"]["workspace_words"], 528
        )
        self.assertEqual(
            by_id["mth.graph.filter.poly2.q16.16"]["precision"], "q16.16"
        )


if __name__ == "__main__":
    unittest.main()
