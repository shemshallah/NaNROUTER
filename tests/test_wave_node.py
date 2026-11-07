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
            binding(point=256).validate()

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


if __name__ == "__main__":
    unittest.main()
