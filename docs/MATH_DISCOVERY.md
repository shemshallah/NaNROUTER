# Math discovery proposals (GAME_PLAN_:: §13.1)

Status: implemented in `runner_riddle/math_discovery.py`; tests in
`tests/test_math_discovery.py` (14 tests).

This module adds the proposal half of the five learning mechanisms. It reads
already-classified leaves, function contracts, and function metadata and emits
bounded, deterministic discovery candidates. It does not add a second
authority path.

## Non-authority contract

- Every record is explicitly `non_authoritative=True`.
- Proposals have no validity, truth, proof, or authorization field.
- `proposal.execute()` and `proposal.promote()` raise `DiscoveryError`;
  `result.execute()` and `result.promote()` do the same.
- `executable` and `promotable` are always `False`.
- Serialized records carry `"execution": "not_performed"` and
  `"promotion": "not_permitted"`.
- Nothing is persisted, executed, promoted, or written to the linker/runtime
  snapshot.

A proposal is input to a separate review/validation/linkage pipeline. It is not
an admission, candidate, lease, or execution permit. In particular, the module
never calls the linker, validity engine, runtime, bridge, or store.

## Records

`DiscoveryRequest`

```python
DiscoveryRequest(
    mechanism="all",              # all | structural | transformational |
                                  # derivational | relational | operational
    leaves=(MathLeaf, ...),
    functions=(MathFunction, ...),
    relations=(RelationSchema | RelationRecord, ...),
    objective="discovery",
    bounds=DiscoveryBounds(...),  # or a mapping
    snapshot_id=None,             # None => derived snapshot id
    allow_scratch=False,
)
```

`DiscoveryBounds`

```python
DiscoveryBounds(
    max_proposals=32,
    max_fanout=32,
    max_depth=2,
    fuel=1024,
)
```

`DiscoveryProposal`

- `proposal_id` — `dsc:` plus a digest of snapshot, mechanism, and content.
- `content_key` — mechanism-independent content digest used for dedupe.
- `mechanism`, `kind`, `refs`, `evidence`, `rank`, `snapshot_id`.
- `non_authoritative` (fixed true).

`DiscoveryResult`

- `requested_mechanism`, `mechanisms`, `snapshot_id`,
  `derived_snapshot_id`, `objective`.
- `proposals` ranked from `1` to `N`.
- `bounds`, `incomplete`, `incomplete_reasons`, `fuel_used`,
  `considered`, `omitted_proposal_count`, `search`.
- `proposal_ids`, `proposal_count`, `digest()`, `result_id`.
- `non_authoritative` (fixed true).

All records are frozen dataclasses. Digests use canonical JSON and reject host
floats.

## Mechanisms

### Structural

Groups leaves by exact `(kind, domain, shape, layout)` and proposes:

- `structural_group` for each group with at least two leaves;
- `structural_pair` for pairs within the group (bounded by `max_fanout`);
- `structural_layout_variant` for same kind/domain/shape leaves with different
  layouts when `max_depth >= 2`.

### Transformational

For each active/proposed function and leaf, checks whether the leaf statically
satisfies one or more declared input endpoints. A match proposes
`transform_goal` with the matched endpoint positions and the function's output
contract as the target. Matrix inputs never match vector leaves merely because
both are numeric.

### Derivational

Builds bounded left-to-right composition chains. A consumer must have exactly
one input, matching the linker's composition rule. `max_depth=1` yields direct
pairs; `max_depth=2` also yields three-function chains. Chains never repeat a
function object and are deduplicated by their ordered component refs.

### Relational

For each structural group with at least two leaves, builds and validates a
`RelationSchema` plus a `RelationRecord` member set. The evidence includes the
schema, schema digest, members, relation record, and relation digest. A
declared schema is reused when every leaf names it and it accepts the
`member` role; otherwise a deterministic discovery schema is created. Invalid
relation candidates are skipped and reported in `search`/incomplete evidence.

### Operational

For each function with implementation or numerical-policy metadata, proposes
`operational_policy` containing:

- implementation descriptors sorted by workspace then kernel id;
- a preferred implementation derived from that ordering;
- workspace policy, capability classes, kernel ids, precision;
- declared determinism and a cache policy
  (`cache_eligible` / `recompute_only` / `policy_undeclared`).

The cache policy is operational guidance only. It never sets validity, truth,
or proof.

## Bounds and determinism

- `max_proposals` caps the returned proposals. Per-mechanism calls and
  `propose_all` both enforce it; `propose_all` applies one global cap after
  merging.
- `max_fanout` caps group members, pair variants, matches per function,
  composition alternatives per source, and implementation rows.
- `max_depth` controls structural layout variants and composition chain length.
- `fuel` is shared across all mechanisms in `propose_all`; each direct
  mechanism call starts a fresh fuel budget.
- Exhausting a bound adds `depth_limit`, `fuel_exhausted`, `fanout_limit`, or
  `proposal_limit` to `incomplete_reasons`.
- Proposal ordering is `(mechanism, kind, refs, evidence)`; ranks are assigned
  afterward. Duplicate `proposal_id` and `content_key` values are rejected.
- `propose_all` removes cross-mechanism duplicates by `content_key` before
  ranking. The count is reported in `search["cross_mechanism_duplicates"]`.
- Leaf/function inputs are sorted before snapshot derivation, so request order
  does not change the derived snapshot or result digest.

## API

Module functions:

```python
propose_structural(request)
propose_transformational(request)
propose_derivational(request)
propose_relational(request)
propose_operational(request)
propose_all(request)
propose("structural", request)      # dispatch; "all" is supported
propose(request)                    # uses request.mechanism
```

Facade:

```python
discovery = MathDiscovery(request)
discovery.structural()
discovery.transformational()
discovery.derivational()
discovery.relational()
discovery.operational()
discovery.propose_all()
```

## Tests

`tests/test_math_discovery.py` covers record validation, order-independent
snapshots, all five mechanisms, bounded fanout/fuel/proposal limits,
deterministic digests, cross-mechanism dedupe, relation schema/member validity,
metadata-only operational policy, and explicit non-authority.

Run:

```sh
python3 -m unittest tests.test_math_discovery -q
```

## Limitations

- No mathematical evaluation, ranking by utility, truth, proof, or validity.
- No persistence; proposals are only returned to the caller.
- No runtime/linker/validity wiring or automatic candidate promotion.
- No LM/R7 experiment integration or Boolean-head decisions.
- Structural/relational grouping is static metadata grouping, not graph
  topology discovery.
- Composition only models contracts; it does not create a function leaf or
  choose an implementation.
- Operational policy is derived from declared metadata only; it does not
  benchmark kernels or infer performance.
- Relation candidates are not written to a hypergraph or store.
