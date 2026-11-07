from __future__ import annotations

import unittest

from runner_riddle.math_discovery import (
    DISCOVERY_ID,
    MECHANISMS,
    DiscoveryBounds,
    DiscoveryError,
    DiscoveryRequest,
    MathDiscovery,
    propose,
    propose_all,
    propose_derivational,
    propose_operational,
    propose_relational,
    propose_structural,
    propose_transformational,
)
from runner_riddle.math_objects import MathFunction, MathLeaf
from runner_riddle.math_relation import RelationRecord, RelationSchema, RoleSpec


SNAPSHOT_ID = "snp:" + "a" * 64
_DIGITS = "0123456789abcdef"


def vector_leaf(index: int, *, shape=(4,), domain: str = "real",
                layout: str = "row_major", precision: str = "float32",
                status: str = "committed",
                relation_schema: str | None = None) -> MathLeaf:
    type_record = {
        "name": "vector",
        "domain": domain,
        "shape": list(shape),
        "layout": layout,
        "precision": precision,
        "element": precision,
    }
    if relation_schema is not None:
        type_record["relation_schema"] = relation_schema
    return MathLeaf(
        leaf_id=f"nml:U0:vector:{index}",
        kind="vector",
        type=type_record,
        content={"digest": _DIGITS[index % len(_DIGITS)] * 64},
        status=status,
    )


def endpoint(kind: str, *, domain: str = "real",
             shape=None) -> dict:
    value = {"kind": kind, "domain": domain}
    if shape is not None:
        value["shape"] = list(shape)
    return value


def make_function(function_id: str, inputs, output, *, version: int = 1,
                  status: str = "active", proof_status: str = "tested",
                  implementations=(), policy=None) -> MathFunction:
    if policy is None:
        policy = {"precision": "float32", "deterministic": True}
    return MathFunction(
        function_id=function_id,
        version=version,
        signature={"inputs": list(inputs), "output": output},
        numerical_policy=policy,
        implementations=tuple(implementations),
        proof_status=proof_status,
        status=status,
    )


def _all_keys(value):
    keys = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(key)
            keys.update(_all_keys(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            keys.update(_all_keys(item))
    return keys


class DiscoveryRecordTests(unittest.TestCase):
    def test_request_normalizes_bounds_and_snapshot_is_order_independent(self):
        leaves = (vector_leaf(1), vector_leaf(2))
        request = DiscoveryRequest(
            mechanism="STRUCTURAL",
            leaves=leaves,
            bounds={
                "max_proposals": 4,
                "max_fanout": 4,
                "max_depth": 1,
                "fuel": 16,
            },
        )
        self.assertEqual(request.mechanism, "structural")
        self.assertIsInstance(request.bounds, DiscoveryBounds)

        forward = propose_structural(request)
        reverse = propose_structural(DiscoveryRequest(
            mechanism="structural",
            leaves=tuple(reversed(leaves)),
            bounds=request.bounds,
        ))
        self.assertEqual(forward.derived_snapshot_id, reverse.derived_snapshot_id)
        self.assertEqual(forward.digest(), reverse.digest())
        self.assertEqual(forward.requested_mechanism, "structural")
        self.assertEqual(forward.mechanisms, ("structural",))

        pinned = propose_structural(DiscoveryRequest(
            leaves=leaves,
            snapshot_id=SNAPSHOT_ID,
            bounds=request.bounds,
        ))
        self.assertEqual(pinned.snapshot_id, SNAPSHOT_ID)
        self.assertGreater(pinned.proposal_count, 0)
        for proposal in pinned.proposals:
            self.assertEqual(proposal.snapshot_id, SNAPSHOT_ID)

        with self.assertRaises(DiscoveryError):
            DiscoveryRequest(mechanism="unknown")
        with self.assertRaises(DiscoveryError):
            DiscoveryRequest(bounds={"fuel": -1})
        with self.assertRaises(DiscoveryError):
            DiscoveryRequest(leaves=("nml:U0:vector:1",))


class StructuralDiscoveryTests(unittest.TestCase):
    def test_structural_groups_and_pairs_share_static_key(self):
        leaves = (
            vector_leaf(1),
            vector_leaf(2),
            vector_leaf(3),
            vector_leaf(4, shape=(8,)),
        )
        result = propose_structural(DiscoveryRequest(
            leaves=leaves,
            bounds={"max_depth": 1, "max_fanout": 10, "fuel": 64},
        ))
        kinds = [proposal.kind for proposal in result.proposals]
        self.assertEqual(kinds.count("structural_group"), 1)
        self.assertEqual(kinds.count("structural_pair"), 3)

        group = next(
            proposal for proposal in result.proposals
            if proposal.kind == "structural_group"
        )
        self.assertEqual(group.evidence["member_count"], 3)
        self.assertEqual(group.evidence["group_key"]["shape"], [4])
        self.assertEqual(
            [ref["leaf_id"] for ref in group.refs],
            ["nml:U0:vector:1", "nml:U0:vector:2", "nml:U0:vector:3"],
        )
        self.assertEqual(
            [proposal.rank for proposal in result.proposals],
            list(range(1, result.proposal_count + 1)),
        )

    def test_layout_variant_requires_depth_two(self):
        leaves = (
            vector_leaf(1, layout="row_major"),
            vector_leaf(2, layout="col_major"),
        )
        shallow = propose_structural(DiscoveryRequest(
            leaves=leaves,
            bounds={"max_depth": 1, "fuel": 32},
        ))
        self.assertEqual(shallow.proposal_count, 0)

        deep = propose_structural(DiscoveryRequest(
            leaves=leaves,
            bounds={"max_depth": 2, "fuel": 32},
        ))
        variant = next(
            proposal for proposal in deep.proposals
            if proposal.kind == "structural_layout_variant"
        )
        self.assertEqual(variant.evidence["left_layout"], "row_major")
        self.assertEqual(variant.evidence["right_layout"], "col_major")
        self.assertEqual(variant.evidence["kind"], "vector")


class TransformationalDiscoveryTests(unittest.TestCase):
    def test_transform_goals_come_only_from_compatible_inputs(self):
        dot = make_function(
            "math.vector.dot",
            (endpoint("vector", shape=(4,)), endpoint("vector", shape=(4,))),
            endpoint("scalar", shape=()),
        )
        trace = make_function(
            "math.matrix.trace",
            (endpoint("matrix", shape=(4, 4)),),
            endpoint("scalar", shape=()),
        )
        result = propose_transformational(DiscoveryRequest(
            leaves=(vector_leaf(1), vector_leaf(2)),
            functions=(dot, trace),
            bounds={"fuel": 64},
        ))
        self.assertEqual(result.proposal_count, 2)
        for proposal in result.proposals:
            function_ids = {
                ref["function_id"] for ref in proposal.refs
                if ref.get("ref_type") == "function"
            }
            self.assertEqual(function_ids, {"math.vector.dot"})
            self.assertEqual(proposal.evidence["target"]["kind"], "scalar")
            self.assertEqual(proposal.evidence["matched_input_count"], 2)
            self.assertEqual(proposal.evidence["required_input_count"], 2)
            self.assertEqual(
                proposal.evidence["source"]["leaf_id"],
                next(
                    ref["leaf_id"] for ref in proposal.refs
                    if ref.get("ref_type") == "leaf"
                ),
            )


class DerivationalDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.total = make_function(
            "math.vector.total",
            (endpoint("vector", shape=(4,)),),
            endpoint("scalar", shape=()),
        )
        self.broadcast = make_function(
            "math.scalar.broadcast",
            (endpoint("scalar", shape=()),),
            endpoint("vector", shape=(4,)),
        )
        self.count = make_function(
            "math.vector.count",
            (endpoint("vector", shape=(4,)),),
            endpoint("scalar", shape=()),
        )
        self.functions = (self.total, self.broadcast, self.count)

    def test_composition_pairs_are_generated_at_depth_one(self):
        result = propose_derivational(DiscoveryRequest(
            functions=self.functions,
            bounds={"max_depth": 1, "fuel": 64},
        ))
        chains = [
            [component["function_id"] for component in proposal.evidence["components"]]
            for proposal in result.proposals
        ]
        self.assertIn(
            ["math.vector.total", "math.scalar.broadcast"], chains,
        )
        self.assertIn(
            ["math.scalar.broadcast", "math.vector.count"], chains,
        )
        self.assertTrue(all(len(chain) == 2 for chain in chains))

    def test_composition_depth_two_adds_a_bounded_chain(self):
        result = propose_derivational(DiscoveryRequest(
            functions=self.functions,
            bounds={"max_depth": 2, "fuel": 128},
        ))
        triples = [
            [component["function_id"] for component in proposal.evidence["components"]]
            for proposal in result.proposals
            if len(proposal.evidence["components"]) == 3
        ]
        expected = [
            "math.vector.total",
            "math.scalar.broadcast",
            "math.vector.count",
        ]
        self.assertIn(expected, triples)
        self.assertTrue(all(len(chain) == 3 for chain in triples))
        triple = next(
            proposal for proposal in result.proposals
            if [
                component["function_id"]
                for component in proposal.evidence["components"]
            ] == expected
        )
        self.assertEqual(triple.evidence["depth"], 2)
        self.assertEqual(len(triple.evidence["steps"]), 2)
        self.assertEqual(len(triple.refs), 3)


class RelationalDiscoveryTests(unittest.TestCase):
    def test_relation_candidate_contains_a_valid_schema_and_member_set(self):
        result = propose_relational(DiscoveryRequest(
            leaves=(vector_leaf(1), vector_leaf(2), vector_leaf(3)),
            bounds={"fuel": 32},
        ))
        self.assertEqual(result.proposal_count, 1)
        proposal = result.proposals[0]
        self.assertEqual(proposal.kind, "relation_candidate")
        record = RelationRecord.from_dict(proposal.evidence["relation"])
        self.assertEqual(record.arity, 3)
        self.assertEqual(
            [member.leaf_id for member in record.members],
            ["nml:U0:vector:1", "nml:U0:vector:2", "nml:U0:vector:3"],
        )
        self.assertEqual(record.digest(), proposal.evidence["relation_digest"])
        self.assertEqual(
            record.schema.schema_id, proposal.evidence["schema"]["schema_id"],
        )
        self.assertEqual(
            record.schema.digest(), proposal.evidence["schema_digest"],
        )

        declared = RelationSchema(
            schema_id="math.relation.discovery.demo",
            version=2,
            ordered=True,
            directed=False,
            roles=(RoleSpec("member", min_count=2, required=True),),
            min_arity=2,
            max_arity=8,
            constraints=("unique_leaf_ids",),
            provenance={"owner": "test"},
        )
        declared_result = propose_relational(DiscoveryRequest(
            leaves=(
                vector_leaf(11, relation_schema=declared.schema_id),
                vector_leaf(12, relation_schema=declared.schema_id),
            ),
            relations=(declared,),
            bounds={"fuel": 32},
        ))
        declared_record = RelationRecord.from_dict(
            declared_result.proposals[0].evidence["relation"],
        )
        self.assertEqual(
            declared_record.schema.schema_id, declared.schema_id,
        )
        self.assertEqual(declared_record.schema.version, 2)


class OperationalDiscoveryTests(unittest.TestCase):
    def test_operational_policy_is_built_from_function_metadata(self):
        slow = {
            "kernel_id": "mth.vector.dot.slow",
            "version": 1,
            "precision": "float32",
            "shape": [4],
            "workspace_words": 200,
            "capability_class": "vector.dot",
            "implementation_digest": "b" * 64,
        }
        fast = {
            "kernel_id": "mth.vector.dot.fast",
            "version": 1,
            "precision": "float32",
            "shape": [4],
            "workspace_words": 100,
            "capability_class": "vector.dot",
            "implementation_digest": "c" * 64,
        }
        function = make_function(
            "math.vector.dot",
            (endpoint("vector", shape=(4,)), endpoint("vector", shape=(4,))),
            endpoint("scalar", shape=()),
            implementations=(slow, fast),
            policy={
                "precision": "float32",
                "deterministic": True,
                "rounding": "nearest",
            },
        )
        result = propose_operational(DiscoveryRequest(
            functions=(function,),
            bounds={"max_fanout": 8, "fuel": 16},
        ))
        proposal = result.proposals[0]
        self.assertEqual(proposal.kind, "operational_policy")
        self.assertEqual(
            proposal.evidence["preferred_implementation"]["kernel_id"],
            "mth.vector.dot.fast",
        )
        self.assertEqual(
            [row["kernel_id"] for row in proposal.evidence["implementations"]],
            ["mth.vector.dot.fast", "mth.vector.dot.slow"],
        )
        self.assertEqual(
            proposal.evidence["workspace_policy"]["workspace_words"], 100,
        )
        self.assertEqual(proposal.evidence["cache_policy"], "cache_eligible")
        self.assertEqual(proposal.evidence["capability_classes"], ["vector.dot"])
        self.assertEqual(
            proposal.evidence["kernel_ids"],
            ["mth.vector.dot.fast", "mth.vector.dot.slow"],
        )

        nondeterministic = make_function(
            "math.vector.dot",
            (endpoint("vector", shape=(4,)), endpoint("vector", shape=(4,))),
            endpoint("scalar", shape=()),
            implementations=(fast,),
            policy={"precision": "float32", "deterministic": False},
        )
        other = propose_operational(DiscoveryRequest(
            functions=(nondeterministic,),
            bounds={"fuel": 16},
        ))
        self.assertEqual(
            other.proposals[0].evidence["cache_policy"], "recompute_only",
        )


class BoundedDiscoveryTests(unittest.TestCase):
    def test_fanout_truncates_group_membership(self):
        leaves = tuple(vector_leaf(index) for index in range(1, 6))
        result = propose_structural(DiscoveryRequest(
            leaves=leaves,
            bounds={
                "max_proposals": 32,
                "max_fanout": 2,
                "max_depth": 1,
                "fuel": 128,
            },
        ))
        group = next(
            proposal for proposal in result.proposals
            if proposal.kind == "structural_group"
        )
        self.assertEqual(group.evidence["member_count"], 2)
        self.assertEqual(group.evidence["total_member_count"], 5)
        self.assertTrue(group.evidence["truncated"])
        self.assertEqual(
            [proposal.kind for proposal in result.proposals].count(
                "structural_pair"
            ),
            1,
        )
        self.assertIn("fanout_limit", result.incomplete_reasons)

    def test_fuel_exhaustion_is_reported_without_false_fanout(self):
        leaves = tuple(vector_leaf(index) for index in range(1, 5))
        result = propose_structural(DiscoveryRequest(
            leaves=leaves,
            bounds={
                "max_proposals": 32,
                "max_fanout": 32,
                "max_depth": 1,
                "fuel": 2,
            },
        ))
        self.assertEqual(result.fuel_used, 2)
        self.assertEqual(result.proposal_count, 2)
        self.assertIn("fuel_exhausted", result.incomplete_reasons)
        self.assertNotIn("fanout_limit", result.incomplete_reasons)

    def test_proposal_limit_is_bounded_and_deterministic(self):
        leaves = tuple(vector_leaf(index) for index in range(1, 5))
        request = DiscoveryRequest(
            leaves=leaves,
            bounds={
                "max_proposals": 1,
                "max_fanout": 32,
                "max_depth": 1,
                "fuel": 64,
            },
        )
        result = propose_structural(request)
        self.assertEqual(result.proposal_count, 1)
        self.assertEqual(result.proposals[0].rank, 1)
        self.assertEqual(result.omitted_proposal_count, 6)
        self.assertIn("proposal_limit", result.incomplete_reasons)
        self.assertEqual(result.digest(), propose_structural(request).digest())


class AuthorityAndDedupeTests(unittest.TestCase):
    def _mixed_request(self):
        total = make_function(
            "math.vector.total",
            (endpoint("vector", shape=(4,)),),
            endpoint("scalar", shape=()),
        )
        broadcast = make_function(
            "math.scalar.broadcast",
            (endpoint("scalar", shape=()),),
            endpoint("vector", shape=(4,)),
        )
        count = make_function(
            "math.vector.count",
            (endpoint("vector", shape=(4,)),),
            endpoint("scalar", shape=()),
        )
        return DiscoveryRequest(
            leaves=(vector_leaf(1), vector_leaf(2), vector_leaf(3)),
            functions=(total, broadcast, count),
            bounds={
                "max_proposals": 64,
                "max_fanout": 8,
                "max_depth": 2,
                "fuel": 512,
            },
        )

    def test_propose_all_covers_every_mechanism_without_duplicates(self):
        request = self._mixed_request()
        result = propose_all(request)
        self.assertEqual(result.mechanisms, MECHANISMS)
        self.assertEqual(
            {proposal.mechanism for proposal in result.proposals},
            set(MECHANISMS),
        )
        self.assertEqual(
            len(result.proposal_ids), len(set(result.proposal_ids)),
        )
        self.assertEqual(
            len(result.proposals),
            len({proposal.content_key for proposal in result.proposals}),
        )
        self.assertEqual(
            [proposal.rank for proposal in result.proposals],
            list(range(1, result.proposal_count + 1)),
        )
        self.assertEqual(result.requested_mechanism, "all")
        self.assertEqual(result.digest(), propose_all(request).digest())

    def test_proposals_are_explicitly_non_authoritative(self):
        result = propose_structural(DiscoveryRequest(
            leaves=(vector_leaf(1), vector_leaf(2)),
            bounds={"fuel": 16},
        ))
        proposal = result.proposals[0]
        self.assertTrue(proposal.non_authoritative)
        self.assertFalse(proposal.executable)
        self.assertFalse(proposal.promotable)
        with self.assertRaises(DiscoveryError):
            proposal.execute()
        with self.assertRaises(DiscoveryError):
            proposal.promote()

        self.assertTrue(result.non_authoritative)
        self.assertFalse(result.executable)
        self.assertFalse(result.promotable)
        with self.assertRaises(DiscoveryError):
            result.execute()
        with self.assertRaises(DiscoveryError):
            result.promote()

        banned = {
            "validity", "truth", "proof", "proof_status",
            "authorized", "authorization",
        }
        for document in (proposal.to_dict(), result.to_dict()):
            self.assertTrue(document["non_authoritative"])
            self.assertEqual(document["execution"], "not_performed")
            self.assertEqual(document["promotion"], "not_permitted")
            self.assertFalse(_all_keys(document) & banned)
            self.assertEqual(document["discoverer_id"], DISCOVERY_ID)


class FacadeTests(unittest.TestCase):
    def test_every_mechanism_is_callable_directly_and_through_the_facade(self):
        request = DiscoveryRequest(
            leaves=(vector_leaf(1), vector_leaf(2)),
            functions=(
                make_function(
                    "math.vector.total",
                    (endpoint("vector", shape=(4,)),),
                    endpoint("scalar", shape=()),
                ),
            ),
            bounds={"fuel": 64},
        )
        facade = MathDiscovery(request)
        calls = (
            ("structural", propose_structural, facade.structural),
            ("transformational", propose_transformational,
             facade.transformational),
            ("derivational", propose_derivational, facade.derivational),
            ("relational", propose_relational, facade.relational),
            ("operational", propose_operational, facade.operational),
            ("all", propose_all, facade.propose_all),
        )
        for name, direct, through_facade in calls:
            with self.subTest(mechanism=name):
                expected = direct(request)
                self.assertEqual(through_facade().digest(), expected.digest())
                if name != "all":
                    self.assertEqual(
                        propose(name, request).digest(), expected.digest(),
                    )
                    self.assertEqual(expected.mechanisms, (name,))
                else:
                    self.assertEqual(
                        propose(request).digest(), expected.digest(),
                    )
                    self.assertEqual(
                        facade.propose().digest(), expected.digest(),
                    )


if __name__ == "__main__":
    unittest.main()
