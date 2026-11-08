import unittest

from runner_riddle.wave_node import (
    NannetNodeBinding,
    NannetNodeError,
    NannetNodeRegistry,
)


def binding(universe: str = "u1", node: str = "n1", point: int = 1) -> NannetNodeBinding:
    return NannetNodeBinding(
        universe_id=universe,
        node_id=node,
        node_point=point,
        public_key_fingerprint="a" * 64,
        generation=1,
        status="active",
        route="nan://GM0:SC0:MC0:BS0:0:HW0:0",
    )


class NannetNodeTests(unittest.TestCase):
    def test_one_node_per_universe(self):
        registry = NannetNodeRegistry()
        registry.register(binding())
        with self.assertRaises(NannetNodeError):
            registry.register(binding(node="n2", point=2))
        self.assertEqual(registry.count(), 1)

    def test_idempotent_identical_binding(self):
        registry = NannetNodeRegistry()
        first = binding()
        registry.register(first)
        registry.register(first)
        self.assertEqual(registry.count(), 1)

    def test_node_point_bounds(self):
        with self.assertRaises(NannetNodeError):
            binding(point=0).validate()
        with self.assertRaises(NannetNodeError):
            binding(point=257).validate()

    def test_hw255_translates_to_last_native_node_point(self):
        value=binding("bs0hw255", "node256", 256)
        value.validate()
        self.assertEqual(value.to_dict()["node_point"], 256)

    def test_duplicate_node_id_rejected(self):
        registry = NannetNodeRegistry()
        registry.register(binding("u1", "n1", 1))
        with self.assertRaises(NannetNodeError):
            registry.register(binding("u2", "n1", 2))

    def test_duplicate_node_point_rejected(self):
        registry = NannetNodeRegistry()
        registry.register(binding("u1", "n1", 1))
        with self.assertRaises(NannetNodeError):
            registry.register(binding("u2", "n2", 1))

    def test_revoke_advances_generation_and_clears_route(self):
        registry = NannetNodeRegistry()
        registry.register(binding())
        revoked = registry.revoke("u1", generation=2)
        self.assertEqual(revoked.status, "revoked")
        self.assertEqual(revoked.route, "")
        with self.assertRaises(NannetNodeError):
            registry.revoke("u1", generation=2)

    def test_fingerprint_format(self):
        with self.assertRaises(NannetNodeError):
            NannetNodeBinding("u1", "n1", 1, "short").validate()

    def test_schema_fields_roundtrip(self):
        value = binding().to_dict()
        self.assertEqual(value["universe_id"], "u1")
        self.assertEqual(value["node_point"], 1)

    def test_unknown_node_lookup_returns_none(self):
        registry = NannetNodeRegistry()
        self.assertIsNone(registry.get("missing"))
        self.assertEqual(registry.count(), 0)

    def test_binding_contains_no_secret_material(self):
        value = binding().to_dict()
        self.assertNotIn("secret", value)
        self.assertNotIn("private_key", value)
        self.assertNotIn("token", value)
        self.assertIn("public_key_fingerprint", value)

    def test_generation_must_advance_on_revoke(self):
        registry = NannetNodeRegistry()
        registry.register(binding())
        with self.assertRaises(NannetNodeError):
            registry.revoke("u1", generation=1)
        with self.assertRaises(NannetNodeError):
            registry.revoke("missing", generation=2)


if __name__ == "__main__":
    unittest.main()
