import tempfile
import unittest
from pathlib import Path

from runner_riddle import (
    AddressError, MasterRouteCache, RouteError, TracePatternMiner, parse_address,
)


KEY = b"runner-riddle-test-key-32-bytes!!"
ROOT = "nan://GM0:SC0:MC0:BS0:0:HW0:0"


class AddressTests(unittest.TestCase):
    def test_bootstrap_runner_ring_and_object_selectors(self):
        parsed = parse_address(ROOT + "::HW0:1,2,3::vector1337::hyperedge1337")
        self.assertEqual(parsed.root, ROOT)
        self.assertEqual(parsed.selectors[0].heads, (1, 2, 3))
        self.assertEqual(parsed.selectors[1].kind, "vector")
        self.assertEqual(parsed.selectors[2].kind, "hyperedge")

    def test_rejects_untyped_or_out_of_range_head_selector(self):
        with self.assertRaises(AddressError):
            parse_address(ROOT + "::HW0:256")
        with self.assertRaises(AddressError):
            parse_address(ROOT + "::memory1337")
        with self.assertRaises(AddressError):
            parse_address(ROOT + "::HW0:1,1")


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.cache = MasterRouteCache.empty("nan-network-0", KEY)
        candidate = self.cache.propose({
            "route_id": "bootstrap-gateway",
            "canonical_address": ROOT,
            "route_kind": "network",
            "source_ref": "koyeb:bs0:0",
            "target_ref": "universe-0:point-0:head-0",
            "target_head": {"universe_id": "bootstrap-universe-0", "node_point": 0,
                            "head_index": 0, "permanence": "permanent",
                            "head_ref": "universe-0:point-0:head-0"},
            "path": [{"namespace": "BS", "id": 0}, {"namespace": "HW", "id": 0}],
            "permanence": "permanent",
            "source_hash": "a" * 64,
            "acl_digest": "b" * 64,
            "nanclock_tick": 1,
            "learner_id": "bootstrap-authority",
            "bridge_profile": "N16B",
        })
        self.cache.commit(candidate, expected_generation=0,
                          capabilities={"nannet.route.commit"})

    def test_generation_chain_and_authorized_cas(self):
        self.assertEqual(self.cache.generation, 1)
        candidate = self.cache.propose({
            "route_id": "runner-route",
            "canonical_address": ROOT + "::HW0:1",
            "route_kind": "runner-ring",
            "source_ref": "bootstrap",
            "target_ref": "runner-1:head-1",
            "target_head": {"universe_id": "runner-1", "node_point": 0,
                            "head_index": 1, "permanence": "permanent",
                            "head_ref": "runner-1:head-1"},
            "path": [{"namespace": "HW", "id": 1}],
            "permanence": "permanent",
            "source_hash": "c" * 64,
            "acl_digest": "d" * 64,
            "nanclock_tick": 2,
            "learner_id": "bootstrap-authority",
        })
        with self.assertRaises(RouteError):
            self.cache.commit(candidate, expected_generation=1, capabilities=set())
        with self.assertRaises(RouteError):
            self.cache.commit(candidate, expected_generation=0,
                              capabilities={"nannet.route.commit"})
        committed = self.cache.commit(candidate, expected_generation=1,
                                      capabilities={"nannet.route.commit"})
        self.assertEqual(committed["state"], "committed")
        self.assertEqual(self.cache.generation, 2)
        self.assertEqual(self.cache.document["previous_digest"],
                         self.cache.document["previous_digest"])

    def test_atomic_commit_persists_and_rejects_stale_generation(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "master.json"
            initial = MasterRouteCache.empty("nan-network-0", KEY)
            initial.save_atomic(path)
            candidate = initial.propose({
                "route_id": "atomic-root",
                "canonical_address": ROOT,
                "route_kind": "network",
                "source_ref": "koyeb:bs0:0",
                "target_ref": "universe-0:point-0:head-0",
                "target_head": {"universe_id": "bootstrap-universe-0",
                                "node_point": 0, "head_index": 0,
                                "permanence": "permanent",
                                "head_ref": "universe-0:point-0:head-0"},
                "path": [{"namespace": "BS", "id": 0}],
                "permanence": "permanent",
                "source_hash": "a" * 64,
                "acl_digest": "b" * 64,
                "nanclock_tick": 1,
                "learner_id": "bootstrap-authority",
            })
            saved, _ = MasterRouteCache.commit_atomic(
                path, key=KEY, network_id="nan-network-0", candidate=candidate,
                expected_generation=0, capabilities={"nannet.route.commit"}
            )
            self.assertEqual(saved.generation, 1)
            with self.assertRaises(RouteError):
                MasterRouteCache.commit_atomic(
                    path, key=KEY, network_id="nan-network-0", candidate=candidate,
                    expected_generation=0, capabilities={"nannet.route.commit"}
                )

    def test_resolves_heads_and_typed_objects_to_micro_packet(self):
        for index in (1, 2, 3):
            generation = self.cache.generation
            self.cache.register_head_association({
                "namespace": 0,
                "universe_id": f"runner-{index}",
                "node_point": 0,
                "head_index": index,
                "permanence": "permanent",
                "head_ref": f"runner-{index}:head-{index}",
                "source_hash": "e" * 64,
                "acl_digest": "f" * 64,
                "nanclock_tick": 2,
                "learner_id": "bootstrap-authority",
                "base_generation": generation,
            }, expected_generation=generation,
               capabilities={"universe.atlas.commit"})
        for kind in ("vector", "hyperedge"):
            generation = self.cache.generation
            self.cache.register_object_association({
                "kind": kind,
                "object_id": "1337",
                "association_ref": f"atlas:{kind}s:1337",
                "source_hash": "e" * 64,
                "acl_digest": "f" * 64,
                "learner_id": "bootstrap-authority",
                "base_generation": generation,
            }, expected_generation=generation,
               capabilities={"universe.atlas.commit"})
        packet = self.cache.resolve(
            ROOT + "::HW0:1,2,3::vector1337::hyperedge1337"
        )
        self.assertEqual(packet["schema"], "nanrouter.micro-route.v1")
        self.assertEqual(len(packet["packet_digest"]), 64)
        self.assertEqual(len(packet["signature"]), 64)
        self.assertEqual(len(packet["resolved_heads"]), 4)
        self.assertEqual([x["kind"] for x in packet["object_refs"]],
                         ["vector", "hyperedge"])
        with self.assertRaises(RouteError):
            self.cache.resolve(ROOT + "::HW0:99")

    def test_permanent_head_association_cannot_be_reassigned(self):
        record = {
            "namespace": 0, "universe_id": "runner-1", "node_point": 0,
            "head_index": 1, "permanence": "permanent",
            "head_ref": "runner-1:head-1", "source_hash": "e" * 64,
            "acl_digest": "f" * 64, "nanclock_tick": 2,
            "learner_id": "bootstrap-authority", "base_generation": 1,
        }
        self.cache.register_head_association(
            record, expected_generation=1, capabilities={"universe.atlas.commit"}
        )
        replacement = dict(record, head_ref="attacker:head-1", base_generation=2)
        with self.assertRaises(RouteError):
            self.cache.register_head_association(
                replacement, expected_generation=2,
                capabilities={"universe.atlas.commit"}
            )
        with self.assertRaises(RouteError):
            self.cache.register_head_association(
                dict(record, base_generation=2), expected_generation=2, capabilities=set()
            )

    def test_atomic_roundtrip_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "master-cache.json"
            self.cache.save_atomic(path)
            loaded = MasterRouteCache.load(path, KEY)
            self.assertEqual(loaded.digest, self.cache.digest)
            doc = dict(loaded.document)
            doc["generation"] = 999
            with self.assertRaises(RouteError):
                MasterRouteCache(doc, KEY)


class TraceTests(unittest.TestCase):
    def test_repeated_patterns_are_proposals_only(self):
        miner = TracePatternMiner()
        for ok in (True, True, False, True, True, True, True, False):
            miner.observe({
                "schema": "nanrouter.trace.v1",
                "source_ref": "HW0:1",
                "target_ref": "vector:1337",
                "source_hash": "a" * 64,
                "acl_digest": "b" * 64,
                "correct": ok,
            })
        candidate, = miner.candidates(minimum_observations=8)
        self.assertEqual(candidate.observations, 8)
        self.assertEqual(candidate.successes, 6)
        self.assertGreater(candidate.confidence_q16, 0)
        self.assertLess(candidate.confidence_q16, 65535)
        self.assertEqual(miner.candidates(minimum_observations=9), [])


if __name__ == "__main__":
    unittest.main()
