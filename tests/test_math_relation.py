from __future__ import annotations

import unittest

from runner_riddle.math_relation import (
    Hypergraph, RelationError, RelationMember, RelationRecord, RelationSchema,
    RoleSpec,
)


def schema(**overrides):
    values = dict(
        schema_id="math.relation.membership.v1",
        ordered=False,
        duplicate_policy="forbid",
        directed=False,
        min_arity=1,
        max_arity=8,
        roles=(RoleSpec("member", min_count=1, required=True),),
        allow_unroled=False,
    )
    values.update(overrides)
    return RelationSchema(**values)


def member(leaf_id, role="member", version=1):
    return RelationMember(leaf_id, version=version, role=role)


def relation(relation_id="nml:U0:relation:1", members=None, sch=None):
    members = members or (member("nml:U0:vector:1"),)
    return RelationRecord(relation_id, sch or schema(), 1, tuple(members))


class RelationTests(unittest.TestCase):
    def test_schema_and_relation_are_typed_and_digest_stable(self):
        rel = relation()
        self.assertEqual(rel.digest(), rel.digest())
        self.assertEqual(rel.schema.digest(), rel.schema.digest())
        self.assertEqual(rel.leaf_ids, ("nml:U0:vector:1",))
        self.assertEqual(rel.to_dict()["schema"], "nanrouter.math-relation.v1")

    def test_duplicate_members_rejected_or_allowed(self):
        members = (member("nml:U0:vector:1"),
                   member("nml:U0:vector:1", role="member"))
        with self.assertRaises(RelationError):
            relation(members=members)
        rel = relation(members=members, sch=schema(duplicate_policy="allow"))
        self.assertEqual(len(rel.members), 2)

    def test_arity_and_roles_are_enforced(self):
        with self.assertRaises(RelationError):
            relation(sch=schema(min_arity=2))
        with self.assertRaises(RelationError):
            relation(members=(member("nml:U0:vector:1", role="unknown"),),
                     sch=schema(roles=(RoleSpec("member", required=True),
                                       RoleSpec("target", required=True))))
        with self.assertRaises(RelationError):
            relation(sch=schema(roles=(RoleSpec("target", required=True),)))

    def test_ordered_and_directed_metadata_are_preserved(self):
        rel = relation(sch=schema(ordered=True, directed=True))
        self.assertTrue(rel.schema.ordered)
        self.assertTrue(rel.schema.directed)
        self.assertEqual(rel.ordering, "ordered")
        self.assertEqual(rel.direction, "directed")

    def test_unordered_relation_canonicalizes_member_order(self):
        a = relation(members=(member("b"), member("a")),
                     sch=schema(ordered=False))
        b = relation(members=(member("a"), member("b")),
                     sch=schema(ordered=False))
        self.assertEqual(a.digest(), b.digest())
        self.assertTrue(a.same_content(b))

    def test_hyperedge_membership_and_hypergraph_traversal(self):
        r1 = relation("nml:U0:relation:1", (
            member("nml:U0:vector:1"), member("nml:U0:vector:2"),
        ))
        r2 = relation("nml:U0:relation:2", (
            member("nml:U0:vector:2"), member("nml:U0:vector:3"),
        ))
        hg = Hypergraph("nml:U0:hypergraph:1", relations=(r1, r2))
        self.assertEqual(hg.members(r1.relation_id), r1.members)
        self.assertEqual(
            [item.relation_id for item in hg.incidence("nml:U0:vector:2")],
            [r1.relation_id, r2.relation_id],
        )
        nested = relation(
            "nml:U0:relation:nested",
            (member(r1.relation_id), member("nml:U0:vector:4")),
        )
        hg2 = Hypergraph("nml:U0:hypergraph:nested", relations=(r1, nested))
        traversed = hg2.traverse(nested.relation_id, max_depth=4)
        self.assertEqual([item.relation_id for item in traversed],
                         [nested.relation_id, r1.relation_id])

    def test_hypergraph_rejects_identity_conflicts_and_versions(self):
        hg = Hypergraph("nml:U0:hypergraph:1", relations=(relation(),))
        with self.assertRaises(RelationError):
            hg.with_relation(relation(members=(member("nml:U0:vector:9"),)))
        versioned = relation().next_version(
            members=(member("nml:U0:vector:2"),), version=2,
        )
        hg2 = hg.with_relation(versioned)
        self.assertEqual(len(hg2.relations_for(versioned.relation_id)), 2)

    def test_traversal_depth_and_fanout_are_bounded(self):
        r1 = relation("r1", (member("v1"), member("v2")))
        r2 = relation("r2", (member("r1"), member("v3")))
        hg = Hypergraph("hg", relations=(r1, r2))
        result = hg.traverse("r2", max_depth=1)
        self.assertEqual([item.relation_id for item in result], ["r2", "r1"])
        with self.assertRaises(RelationError):
            hg.traverse("r2", max_depth=0)

    def test_relations_do_not_accept_arbitrary_bags(self):
        with self.assertRaises(RelationError):
            relation(members=({"leaf_id": "x"},))
        with self.assertRaises(RelationError):
            RelationRecord("r", schema(), 1, (("x",),))


if __name__ == "__main__":
    unittest.main()
