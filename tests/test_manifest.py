import json
import pathlib
import tomllib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class ManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.points = tomllib.loads((ROOT / "spec/point-map.toml").read_text())
        cls.policy = tomllib.loads((ROOT / "spec/bin-policy.toml").read_text())

    def test_exact_permanent_point_assignments(self):
        points = {p["id"]: p for p in self.points["point"]}
        self.assertEqual(set(points), {0, 1, 2, 3, 4, 5, 6, 7, 8})
        self.assertEqual(points[0]["label"], "BSR1")
        self.assertEqual(points[0]["bsr_wire"], 0)
        self.assertEqual(points[4]["label"], "BSR2")
        self.assertEqual(points[4]["bsr_wire"], 1)
        self.assertEqual(points[5]["label"], "BSR3")
        self.assertEqual(points[5]["bsr_wire"], 2)
        self.assertEqual(points[6]["label"], "BSR4")
        self.assertEqual(points[6]["bsr_wire"], 3)
        self.assertEqual(points[7]["label"], "BSR5")
        self.assertEqual(points[7]["bsr_wire"], 4)
        self.assertEqual(points[8]["label"], "BSR6")
        self.assertEqual(points[8]["bsr_wire"], 5)
        self.assertEqual(points[1]["role"], "personal-phone")
        self.assertEqual(points[2]["role"], "hermes-demo")
        self.assertEqual(points[3]["role"], "clocked-demo")

    def test_registration_range_is_exact(self):
        registration = self.points["registration"]
        self.assertEqual(registration["available_points"], "9..255")
        self.assertEqual(self.points["registration_min"], 9)
        self.assertEqual(self.points["registration_max"], 255)
        self.assertEqual(255 - 9 + 1, 247)

    def test_head_inventory_has_250_boolean_learners(self):
        heads = self.points["head_namespace"]
        reserved = heads["reserved_bsr_heads"]
        self.assertEqual(reserved, [0, 4, 5, 6, 7, 8])
        self.assertEqual(heads["count"] - len(reserved), 250)
        self.assertEqual(heads["boolean_learning_head_count"], 250)
        self.assertTrue(heads["head_namespace_is_not_node_point_namespace"])

    def test_unknown_ranges_and_live_map_writes_are_denied(self):
        self.assertEqual(self.policy["default"], "deny")
        self.assertEqual(self.policy["unknown_ranges"], "deny")
        self.assertEqual(self.policy["raw_address_allocation"], "disabled-until-authority-manifest-imported")
        self.assertEqual(self.policy["permissions"]["runner_riddle_live_map_access"], "read-only")
        self.assertFalse(self.policy["permissions"]["permanent_identity_write"])
        self.assertFalse(self.policy["permissions"]["bsr_control_head_learning"])
        self.assertFalse(self.policy["permissions"]["code_self_modification"])

    def test_android_never_maps_overbootstrap(self):
        self.assertEqual(self.policy["universe"]["android_limit_bytes"], 8_388_608)
        self.assertFalse(self.policy["universe"]["android_may_map_overbootstrap"])

    def test_learning_trigger_requires_signature_and_expiry(self):
        schema = json.loads((ROOT / "spec/learning-trigger.schema.json").read_text())
        required = set(schema["required"])
        self.assertIn("signature", required)
        self.assertIn("expires_at_tick", required)
        self.assertIn("acl_digest", required)
        self.assertEqual(schema["properties"]["requested_stage"]["enum"],
                         ["OBSERVE", "LEARN_BOOLEAN", "LEARN_ROUTING", "LANGUAGE_DEMO"])

    def test_trace_schema_covers_ten_layers(self):
        schema = json.loads((ROOT / "spec/trace-envelope.schema.json").read_text())
        self.assertEqual(schema["properties"]["layer"]["minimum"], 0)
        self.assertEqual(schema["properties"]["layer"]["maximum"], 9)
        self.assertIn("acl_digest", schema["required"])
        self.assertIn("base_generation", schema["required"])

    def test_address_map_records_track_permanent_vs_ephemeral_identity(self):
        schema = json.loads((ROOT / "spec/map-record.schema.json").read_text())
        self.assertEqual(schema["properties"]["address"]["maximum"], 65535)
        self.assertEqual(schema["properties"]["head_index"]["maximum"], 255)
        self.assertEqual(schema["properties"]["permanence"]["enum"],
                         ["permanent", "ephemeral"])
        self.assertIn("evidence_digest", schema["required"])
        self.assertIn("acl_digest", schema["required"])


if __name__ == "__main__":
    unittest.main()
