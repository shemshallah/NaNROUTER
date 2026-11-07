from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runner_riddle.math_objects import (
    MathCandidate,
    MathLeaf,
    MathRule,
    candidate_id_for,
)
from runner_riddle.math_registry import MathFunctionRegistry
from runner_riddle.math_runtime import (
    MathRuntime,
    MathRuntimeConfigError,
    MathRuntimePlanError,
)
from runner_riddle.math_store import MathStore
from runner_riddle.mth_registry import MthRegistry
from runner_riddle.mth_system import MthSystem
from runner_riddle.wave_ring_scheduler import WaveRingScheduler
from runner_riddle.wave_service import WaveService
from runner_riddle.wave_store import WaveStore

REPO = Path(__file__).resolve().parents[1]


def make_leaf(index: int, digest: str, shape=(256,), kind="vector"):
    return MathLeaf(
        leaf_id=f"nml:U0:{kind}:{index}",
        kind=kind,
        type={
            "element": "float32",
            "shape": list(shape),
            "layout": "row_major",
            "domain": "real",
        },
        content={"digest": digest * 64, "word_count": max(1, int(shape[0]))},
    )


class MathEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.native = MthRegistry.load(REPO / "spec" / "wave-capabilities.json")
        cls.functions = MathFunctionRegistry.load(
            REPO / "spec" / "math-functions.v1.json",
            implementations=cls.native,
        )

    def make_runtime(self, a=None, b=None, **kwargs):
        a = a or make_leaf(1, "a")
        b = b or make_leaf(2, "b")
        return (
            MathRuntime(
                self.functions,
                leaves={a.leaf_id: a, b.leaf_id: b},
                **kwargs,
            ),
            a,
            b,
        )

    def test_link_preflight_compile_vertical_slice(self):
        runtime, a, b = self.make_runtime()
        result = runtime.propose(
            [f"{a.leaf_id}@v1", f"{b.leaf_id}@v1"],
            snapshot_id="snp:" + "c" * 64,
            max_candidates=8,
        )
        self.assertIn("math.vector.dot", [item.function_id for item in result.items])
        candidate = next(
            item for item in result.items if item.function_id == "math.vector.dot"
        )
        admission = runtime.preflight(candidate)
        self.assertEqual(admission.verdict, "VALID")
        compiled = runtime.compile(candidate, admission)
        self.assertEqual(compiled.plan.kernel_ids, ("mth.vector.dot256.f32",))
        self.assertEqual(compiled.workspace_words, 0)
        self.assertEqual(compiled.admission.candidate_id, candidate.candidate_id)
        packet = runtime.prepare_packet(compiled)
        self.assertEqual(packet.state, "PREFLIGHTED")
        self.assertEqual(packet.admission_verdict, "VALID")
        self.assertEqual(packet.candidate_id, candidate.candidate_id)
        self.assertEqual(packet.jahs, "JAHS")

    def test_non_valid_admission_cannot_compile(self):
        runtime, a, b = self.make_runtime()
        result = runtime.propose(
            [f"{a.leaf_id}@v1", f"{b.leaf_id}@v1"],
            snapshot_id="snp:" + "d" * 64,
        )
        candidate = result.items[0]
        admission = runtime.preflight(candidate)
        if admission.verdict == "VALID":
            self.skipTest("selected candidate is valid; negative path covered elsewhere")
        with self.assertRaises(MathRuntimePlanError):
            runtime.compile(candidate, admission)

    def test_wrong_shape_does_not_produce_dot_candidate(self):
        runtime, a, b = self.make_runtime(
            a=make_leaf(1, "a", shape=(256,)),
            b=make_leaf(2, "b", shape=(128,)),
        )
        result = runtime.propose(
            [f"{a.leaf_id}@v1", f"{b.leaf_id}@v1"],
            snapshot_id="snp:" + "e" * 64,
        )
        self.assertNotIn("math.vector.dot", [item.function_id for item in result.items])

    def test_rule_provider_binds_active_rules_into_preflight_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            math_store = MathStore(root / "bs0.sqlite3", root / "mc0.sqlite3")
            a = math_store.put_leaf(make_leaf(1, "a"))
            b = math_store.put_leaf(make_leaf(2, "b"))
            rule = MathRule(
                rule_id="math.rule.runtime.test",
                version=1,
                level=1,
                contract={"claims": {}},
                proof_status="verified",
                status="active",
                scope={"function_ids": ["math.vector.dot"]},
            )

            class Provider:
                @staticmethod
                def active_rules(*, include_isolated=False):
                    return (rule,) if not include_isolated else (rule,)

            runtime = MathRuntime(
                self.functions, store=math_store, rule_provider=Provider(),
            )
            result = runtime.propose(
                [f"{a.leaf_id}@v1", f"{b.leaf_id}@v1"],
                snapshot_id="snp:" + "e" * 64,
                max_candidates=8,
            )
            candidate = next(
                item for item in result.items
                if item.function_id == "math.vector.dot"
            )
            snap = runtime.snapshot_for(candidate)
            self.assertEqual(snap.rules, (rule,))
            admission = runtime.preflight(candidate)
            self.assertEqual(admission.rule_snapshot_id, snap.rule_snapshot_id)

    def test_capability_provider_is_bound_into_preflight_snapshot(self):
        class Provider:
            @staticmethod
            def capabilities():
                return ({
                    "kernel_id": "mth.vector.dot256.f32",
                    "status": "native_verified",
                    "workspace": 1,
                },)

        runtime = MathRuntime(
            self.functions, capability_provider=Provider(),
        )
        leaf_a = make_leaf(1, "a")
        leaf_b = make_leaf(2, "b")
        runtime._leaves[leaf_a.leaf_id] = leaf_a
        runtime._leaves[leaf_b.leaf_id] = leaf_b
        inputs = (
            {"leaf_id": leaf_a.leaf_id, "version": 1,
             "content_digest": leaf_a.content_digest},
            {"leaf_id": leaf_b.leaf_id, "version": 1,
             "content_digest": leaf_b.content_digest},
        )
        dot = next(
            item for item in self.functions.functions
            if item.function_id == "math.vector.dot"
        )
        cand = MathCandidate(
            candidate_id_for("snp:" + "f" * 64, inputs,
                             dot.function_id, dot.version),
            inputs,
            dot.function_id,
            dot.version,
            snapshot_id="snp:" + "f" * 64,
        )
        snap = runtime.snapshot_for(cand)
        self.assertEqual(snap.capabilities, (
            {"kernel_id": "mth.vector.dot256.f32",
             "status": "native_verified", "workspace": 1},
        ))

    def test_runtime_can_use_disposable_cache_without_losing_canonical_leaf(self):
        from runner_riddle.math_cache import MathCache
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            math_store = MathStore(root / "bs0.sqlite3", root / "mc0.sqlite3")
            cache = MathCache(math_store, max_entries=1)
            runtime = MathRuntime(self.functions, store=math_store, cache=cache)
            stored = runtime.add_leaf(make_leaf(1, "a"))
            first = runtime.leaf(stored.leaf_id)
            second = runtime.leaf(stored.leaf_id)
            self.assertEqual(first.leaf_id, second.leaf_id)
            self.assertEqual(cache.stats()["hits"], 1)
            self.assertEqual(runtime.health()["cache"]["entries"], 1)
            cache.evict(1)
            reloaded = runtime.leaf(stored.leaf_id)
            self.assertEqual(reloaded.content_digest, stored.content_digest)

    def test_store_backed_runtime_and_submit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            math_store = MathStore(root / "bs0.sqlite3", root / "mc0.sqlite3")
            a = math_store.put_leaf(make_leaf(1, "a"))
            b = math_store.put_leaf(make_leaf(2, "b"))
            wave_store = WaveStore(root / "wave-bs.sqlite3", root / "wave-mc.sqlite3")
            service = WaveService(
                wave_store,
                "submit-token-0000000000000000",
                "worker-token-1111111111111111",
                "admin-token-22222222222222222",
            )
            scheduler = WaveRingScheduler(cycle_ticks=10, now_tick=0)
            scheduler.start(0)
            system = MthSystem(
                self.native, wave_store, service, scheduler,
            )
            runtime = MathRuntime(
                self.functions, store=math_store, system=system,
            )
            health = runtime.health()
            self.assertEqual(health["status"], "green")
            self.assertEqual(health["store"]["status"], "green")
            self.assertFalse(health["rule_provider"])
            result = runtime.propose(
                [f"{a.leaf_id}@v1", f"{b.leaf_id}@v1"],
                snapshot_id="snp:" + "f" * 64,
                max_candidates=8,
            )
            candidate = next(
                item for item in result.items
                if item.function_id == "math.vector.dot"
            )
            admission = runtime.preflight(candidate)
            self.assertEqual(admission.verdict, "VALID")
            compiled = runtime.compile(candidate, admission)
            with self.assertRaises(MathRuntimeConfigError):
                runtime.submit(
                    compiled,
                    "submit-token-0000000000000000",
                    "job-math-dot",
                    "U0",
                    1,
                    now_tick=0,
                )
            self.assertIsNone(wave_store.get_job("job-math-dot"))


if __name__ == "__main__":
    unittest.main()
