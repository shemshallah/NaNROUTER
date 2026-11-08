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

    def test_bs0_fixed_hardware_nodes_and_reserved_wordnet(self):
        points = {p["id"]: p for p in self.points["point"]}
        self.assertEqual(set(points), {0, 1, 2, 3, 4})
        self.assertEqual(points[0]["label"], "HW0")
        self.assertEqual(points[1]["role"], "personal-phone")
        self.assertEqual(points[2]["role"], "hermes-hardware-node")
        self.assertEqual(points[3]["role"], "clocked-hardware-node")
        self.assertEqual(points[4]["role"], "wordnet-universe")
        self.assertEqual(points[4]["registration"], "reserved")
        self.assertTrue(all(p["permanent"] for p in points.values()))
        self.assertNotIn(5, points)

    def test_local_bsr_head_indices_are_not_hardware_node_addresses(self):
        bindings = self.points["head_namespace"]["bsr_binding"]
        self.assertEqual(
            [(b["head_index"], b["runner_ring_port"], b["bsr_wire"]) for b in bindings],
            [(0, "BS0:0", 0), (4, "BS0:0", 1), (5, "BS0:0", 2),
             (6, "BS0:0", 3), (7, "BS0:0", 4), (8, "BS0:0", 5)],
        )
        # The numerical BSR head indices are not reservations on HW5-HW8.
        self.assertTrue(self.points["registration"]["per_bootstrap_hardware_namespace"])

    def test_master_cache_contains_committed_head_and_object_atlases(self):
        schema = json.loads((ROOT / "spec/master-network-cache.schema.json").read_text())
        self.assertIn("head_associations", schema["required"])
        self.assertIn("object_associations", schema["required"])
        head = json.loads((ROOT / "spec/head-association.schema.json").read_text())
        obj = json.loads((ROOT / "spec/object-association.schema.json").read_text())
        self.assertIn("permanence", head["required"])
        self.assertIn("association_ref", obj["required"])
        self.assertIn("universe_atlas_commit", self.policy["required_capabilities"])

    def test_bootstrap_feedback_is_candidate_only(self):
        schema = json.loads((ROOT / "spec/bootstrap-feedback.schema.json").read_text())
        self.assertEqual(schema["properties"]["macrocluster"]["const"], "MC0:0")
        self.assertFalse(schema["properties"]["live_map_commit"]["const"])
        self.assertIn("candidate_digest", schema["required"])
        self.assertIn("acl_digest", schema["required"])
        self.assertIn("signature", schema["required"])

    def test_range_manifest_is_allocator_signed_and_bounded(self):
        schema = json.loads((ROOT / "spec/range-manifest.schema.json").read_text())
        self.assertEqual(schema["properties"]["authority"]["const"],
                         "nanlmind-canonical-allocator")
        self.assertEqual(schema["properties"]["address_limit_bytes"]["maximum"], 2147483648)
        self.assertIn("signature", schema["required"])

    def test_registration_range_is_exact(self):
        registration = self.points["registration"]
        self.assertEqual(registration["available_points"], "5..255")
        self.assertEqual(self.points["registration_min"], 5)
        self.assertEqual(self.points["registration_max"], 255)
        self.assertEqual(registration["reserved_hw_slots"], [0, 1, 2, 3, 4])
        self.assertEqual(registration["wordnet_hw"], 4)
        self.assertEqual(255 - 5 + 1, 251)

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

    def test_router_merge_and_training_have_separate_bins(self):
        bins = self.policy["bin_classes"]
        self.assertEqual(set(bins), {"router", "merge", "training", "universe_map"})
        self.assertEqual(bins["router"]["live_commit_scope"], "nannet.route.commit")
        self.assertTrue(bins["merge"]["idempotency_required"])
        self.assertFalse(bins["training"]["live_map_commit"])
        self.assertFalse(self.policy["range_import"]["router_merge_training_ranges_enabled"])

    def test_android_never_maps_overbootstrap(self):
        self.assertEqual(self.policy["universe"]["android_limit_bytes"], 8_388_608)
        self.assertFalse(self.policy["universe"]["android_may_map_overbootstrap"])

    def test_koyeb_gateway_and_six_unit_mc0_are_distinct(self):
        gateway = self.points["network_gateway"]
        cluster = self.points["macrocluster"]
        self.assertEqual(gateway["bootstrap_service_class"], 0)
        self.assertEqual(gateway["bootstrap_node"], 0)
        self.assertEqual(gateway["hosting"], "Koyeb")
        self.assertTrue(gateway["availability_role"].startswith("persistent-24x7"))
        self.assertFalse(gateway["owns_runner_heads"])
        self.assertFalse(gateway["owns_master_route_cache"])
        self.assertEqual(cluster["runner_units"], 6)
        self.assertEqual(cluster["runner_wire_bsr"], [0, 1, 2, 3, 4, 5])
        self.assertEqual(gateway["nannet_port"], "BS0:0")
        self.assertFalse(gateway["port_is_hardware_node"])
        self.assertTrue(gateway["attached_hardware_root"].endswith("HW0:0"))

    def test_master_cache_and_micro_route_contracts(self):
        route = json.loads((ROOT / "spec/route-record.schema.json").read_text())
        cache = json.loads((ROOT / "spec/master-network-cache.schema.json").read_text())
        packet = json.loads((ROOT / "spec/micro-route-packet.schema.json").read_text())
        self.assertIn("generation", cache["required"])
        self.assertIn("previous_digest", cache["required"])
        self.assertEqual(route["properties"]["permanence"]["enum"], ["permanent", "ephemeral"])
        self.assertEqual(packet["properties"]["resolved_heads"]["maxItems"], 256)
        self.assertIn("acl_digest", packet["required"])

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
