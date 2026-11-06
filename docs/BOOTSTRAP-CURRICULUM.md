# Bootstrap logic-first curriculum

## Objective

Bootstrap first learns the *formal substrate* it needs to map and route a NaN16 universe. It does not begin as a natural-language model. The initial curriculum is bit identity, Boolean truth, NaN16 word structure, address algebra, permanent-head mapping, route constraints, and merge correctness. Language is a later, gated stage.

## 24/7 learning loop

Runner Riddle is intended to be a persistent listener:

1. Subscribe to authorized NaN source feeds, source repositories, and NANNET mapping events.
2. Validate source framing, provenance, NaN16DE word structure, and the source's ACL.
3. Read only permitted register bins and permanent-head metadata.
4. Generate deterministic exercises and held-out tests.
5. Train the 250 Boolean-learning heads; never train or reassign the six BSR control heads.
6. Build candidate bit/head/address maps, then byte/word maps.
7. Build vector-bin references, temporal links, hyperedges, logic rules, and route candidates.
8. Emit compact trace envelopes and candidate deltas to the overbootstrap MC0/meta-map.
9. Receive bounded policy feedback; never accept direct overwrite instructions from the meta-layer.
10. Persist checkpoint, source digest, nanclock tick, ACL digest, and curriculum gate state.

The process should run as a persistent Koyeb/runner service with health checks, leases, checkpoint recovery, and graceful backpressure. GitHub Actions may test or package it; a scheduled workflow is not a substitute for a continuously connected listener.

## Curriculum order

| Stage | Material | Required gate |
|---|---|---|
| C0 | bit identity, bit order, NaN16DE layout | exact round-trip and endian tests |
| C1 | all 16 two-input Boolean functions | every truth row held out by permutation; all 1,024 checks |
| C2 | NaN16 classes and legal heads | class decode/encode exhaustive |
| C3 | 16-bit address reversal and canonical pairs | exhaustive 65,536-address mapping |
| C4 | 256 permanent heads and 250 Boolean learners | exact head inventory; BSR heads unchanged |
| C5 | 8 MiB register and authorized bins | every read/write checked against ACL |
| C6 | NANNET/BSR route grammar and binary bridges | route round-trip and unauthorized-route rejection |
| C7 | route graph and hyperedges | reachability, cycle and provenance checks |
| C8 | merge/overbootstrap MC0 | idempotent replay, stale-generation rejection, bounded feedback |
| C9 | vectors, temporal relations, logic and cross-layer map | held-out mapping accuracy and consistency gates |
| C10 | language demonstrations | disabled until C0–C9 pass and explicitly enabled |

C1 must not reuse the same truth rows as both training and test examples. Use per-head permutations, hide targets in the example stream, and require all 1,024 row checks.

## Ten mathematical mapping layers in one universe

These are mapping dimensions, not separate processes or separate minds:

- M0 Boolean/bit algebra
- M1 byte/word composition
- M2 head/address atlas
- M3 vector and bin correspondence
- M4 temporal/past-future mapping
- M5 hyperedge and relation mapping
- M6 formal logic and exception mapping
- M7 NANNET route and bridge mapping
- M8 merge, generation, provenance and consensus mapping
- M9 overbootstrap meta-map, policy and cross-layer consistency

A layer may use a different exact algorithm, but every layer references the same universe ID, canonical address algebra, head inventory, and global digest.

## Auto-learning trigger

The learning controller exposes explicit states:

- `OFF`: no intake or training.
- `OBSERVE`: listen and validate; no candidate updates.
- `LEARN_BOOLEAN`: train C0–C4 in isolated candidate bins.
- `LEARN_ROUTING`: train C5–C9 and emit route/map deltas.
- `LANGUAGE_DEMO`: optional later stage, only after logic/routing gates pass.

A trigger request is a signed control event with:
`learner_id`, `requested_stage`, `source_scope`, `universe_id`,
`base_generation`, `nanclock_tick`, `acl_digest`, and expiry.
The authority checks permissions and issues a bounded lease. Restart recovery
resumes from the last committed checkpoint; it does not replay uncommitted
writes as if they were committed.

## Self-modifying mapping, safely

The learner can improve its *mapping model* by proposing:
- head-to-address correspondences;
- point-to-bin references;
- vector prototypes and hyperedges;
- route weights and route alternatives;
- layer policies and memory-placement hints.

Proposals are written to a candidate generation. They are evaluated against
held-out truth tables, exhaustive address invariants, route conformance, ACL
checks, and merge replay. Only an authority-approved compare-and-swap promotes
a candidate. No learner directly edits executable source, wire formats,
permanent identities, or live control routes.

## Overbootstrap MC0

MC0 receives trace envelopes and candidate deltas from the bootstrap universe.
It learns cross-layer reliability and mapping consistency. It may return
bounded priors (for example route score, top-k, learning stride, or layer
budget), but it cannot overwrite local Boolean keys, permanent head IDs, or
the runner's live route table. It is the slow meta-map; Bootstrap remains the
fast local learner.

## Evaluation

No "learned" claim is made from training loss alone. Every stage records:
- held-out exact accuracy;
- shuffled/null baseline;
- address-map coverage and collision count;
- unauthorized access attempts (must be zero successful);
- route success/failure and hop count;
- delta size and deterministic digest;
- checkpoint/restart replay equivalence;
- merge idempotency and stale-base rejection.
