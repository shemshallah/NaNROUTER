import hashlib
import hmac
import json
import unittest

from runner_riddle import (
    BootstrapMacroPlanner, CurriculumState, PolicyError, SignedRangeManifest,
)

KEY = b"runner-riddle-test-key-32-bytes!!"


def signed_manifest():
    doc = {
        "schema": "nanrouter.range-manifest.v1",
        "authority": "nanlmind-canonical-allocator",
        "verified": True,
        "platform": "android",
        "address_limit_bytes": 8_388_608,
        "ranges": [
            {"bin_name": "BOOTSTRAP_BOOLEAN_TRAINING_BIN", "start": 0,
             "end_exclusive": 1024,
             "permissions": ["bootstrap.boolean.read", "bootstrap.boolean.candidate-write"]},
            {"bin_name": "NANNET_ROUTE_BIN", "start": 2048,
             "end_exclusive": 3072,
             "permissions": ["nannet.route.read", "nannet.route.candidate-write"]},
        ],
    }
    doc["signature"] = hmac.new(
        KEY, json.dumps(doc, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256
    ).hexdigest()
    return doc


class MacroPlannerTests(unittest.TestCase):
    def test_logic_first_then_ten_layer_routing(self):
        manifest = SignedRangeManifest(signed_manifest(), KEY)
        planner = BootstrapMacroPlanner()
        boolean = planner.next_job(CurriculumState(), manifest)
        self.assertEqual(boolean.stage, "LEARN_BOOLEAN")
        self.assertEqual(len(boolean.learner_heads), 250)
        self.assertFalse(set(boolean.learner_heads) & {0, 4, 5, 6, 7, 8})
        self.assertTrue(boolean.input_ranges)
        self.assertTrue(boolean.candidate_ranges)
        routing = planner.next_job(CurriculumState(
            boolean_gate_passed=True, boolean_heads_verified=250,
            distinct_boolean_rules=16, base_generation=4
        ), manifest)
        self.assertEqual(routing.stage, "LEARN_ROUTING")
        self.assertEqual(routing.mapping_layers, tuple(range(10)))
        self.assertFalse(routing.writes_live_map)
        feedback = planner.feedback(routing, completed_steps=64,
                                    candidate_digest="a" * 64, acl_digest="b" * 64)
        self.assertFalse(feedback["live_map_commit"])
        self.assertEqual(feedback["base_generation"], 4)

    def test_language_stage_stays_locked_without_own_bin(self):
        manifest = SignedRangeManifest(signed_manifest(), KEY)
        state = CurriculumState(
            boolean_gate_passed=True, boolean_heads_verified=250,
            distinct_boolean_rules=16, routing_gate_passed=True,
            permanent_heads_mapped=6, mapped_layers=tuple(range(10))
        )
        with self.assertRaises(PolicyError):
            BootstrapMacroPlanner().next_job(state, manifest)

    def test_android_range_ceiling_and_overlap_are_enforced(self):
        doc = signed_manifest()
        doc["address_limit_bytes"] = 8_388_609
        doc["signature"] = hmac.new(
            KEY, json.dumps({k: v for k, v in doc.items() if k != "signature"},
                            sort_keys=True, separators=(",", ":")).encode(),
            hashlib.sha256
        ).hexdigest()
        with self.assertRaises(PolicyError):
            SignedRangeManifest(doc, KEY)
        doc = signed_manifest()
        doc["ranges"][1]["start"] = 512
        doc["signature"] = hmac.new(
            KEY, json.dumps({k: v for k, v in doc.items() if k != "signature"},
                            sort_keys=True, separators=(",", ":")).encode(),
            hashlib.sha256
        ).hexdigest()
        with self.assertRaises(PolicyError):
            SignedRangeManifest(doc, KEY)


if __name__ == "__main__":
    unittest.main()
