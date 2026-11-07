# Math relations and hypergraphs (P8)

Status: implemented in `runner_riddle/math_relation.py`; tests in
`tests/test_math_relation.py` (9 tests).

Relations are typed, immutable incidence records. A relation is a hyperedge,
not a bag or an untyped link list. The module persists nothing by itself; the
caller may serialize `to_dict()` into the existing mathematical store.

## Records

- `RoleSpec(role, min_count=0, max_count=None, required=False)`
- `RelationSchema(schema_id, version=1, ordered=True, duplicate_policy="forbid",
  directed=True, weight_domain="none", roles=(), min_arity=1, max_arity=256,
  constraints=(), allow_unroled=False, provenance={})`
- `RelationMember(leaf_id, version=1, role=None)`
- `RelationRecord(relation_id, schema, version=1, members=(), weights=(),
  provenance={})`
- `Hypergraph(hypergraph_id, version=1, relations=(), schema=None, limits=None,
  provenance={})`

`RelationRecord` enforces the schema's arity, role counts, duplicate policy,
member kind, weights, and ordering/direction metadata. `digest()` is canonical
and stable; unordered relations canonicalize member order before hashing.
Relations can contain relation identifiers as members, making nested
hypergraphs possible without a second graph authority.

## Hypergraph API

- `members(relation_id, version=None)` — direct members of one relation.
- `incidence(leaf_id)` — relations that contain a leaf.
- `children(relation)` / `traverse(start, max_depth=..., max_fanout=...)` —
  deterministic bounded traversal. A cycle on the current path is rejected as
  a cycle; a shared DAG node is visited once.
- `relations_for(relation_id)` — all immutable versions of one relation.
- `with_relation(relation, version=None)` — append a relation version,
  preserving prior versions and rejecting identity conflicts.
- `from_relations(...)` — construct a validated hypergraph.

Traversal returns relation records. To obtain leaves, use `members()` and
classify them through the linker/function registry; relation traversal never
executes mathematics.

## Tests

The tests cover schema/role/arity enforcement, duplicate policy, unordered
canonicalization, digest stability, incidence, nested traversal, bounded depth,
cycle rejection, versioned append, and rejection of untyped member bags.
