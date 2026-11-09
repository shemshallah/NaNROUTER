# Round 032 — sparse mirror-pair / typed hyperedge retrieval

**Status:** external native C++ experiment, not a trained language decoder and
not a native NaN16 production kernel.

Archive: `nan_recursive_round032.zip`
SHA-256: `19572e59a5038200b38f7e7ad063b2850458236de18ab58d83871ae46ccb11be`.
Machine-readable record: `spec/round032-retrieval.v1.json`.

## Measured results

| Metric | Result |
|---|---:|
| WordNet facts ingested | 50,268 |
| Root size | 8,388,608 bytes |
| Root mlock (Linux) | succeeded |
| Membership links | 50,268 |
| Ingest time | 31.4373 ms |
| Lookup queries | 250,000 |
| Posting-list found | 250,000 |
| Hash-index found | 250,000 |
| Posting-list time | 9.77183 ms |
| Hash-index time | 2.29752 ms |
| Two-hop queries | 2,000 |
| Two-hop found | 2,000 |
| Cycle before update | 0.0116667 |
| Cycle after update | 1.01167 |
| Cycle after gauge shift | 1.01167 |
| Long-context queries | 1,000 |
| Short-context correct | 0 |
| Pair-index correct | 1,000 |
| Hash-index correct | 1,000 |

The conventional hash index is about **4.3× faster** in this microbenchmark.
The mirror geometry is retained for directional state, local geometric
operations, and reference-cycle invariance — not because it wins every lookup.

## Architecture

- Root: 256 head cells × 128 B + 32,640 pair cells × 256 B = exactly 8 MiB.
- Pair cell: two independent 128-byte directional lanes.
- Hyperedge arena: append-only typed facts outside the root; stable IDs.
- Concept IDs are hashed to an anchored pair; the pair owns an inverted posting
  list. Collisions are resolved by comparing the actual source/relation IDs.
- Two-hop traversal follows typed directed hypernym edges.
- Triangle `x[0,a] + x[a,b] - x[0,b]` is read from root memory; a gauge change
  leaves the learned triangle value intact to float32 precision.

## Correct interpretation

- The 2,000 two-hop queries are sampled from **already stored links**, not
  unseen-word inference.
- The long-context test shows indexed retrieval survives 512 distractors.
  A short-window-only control cannot see the original fact; both indexed
  implementations can.
- The root's float lanes receive a demonstrative triangle update, not
  next-token training.
- There is no trained decoder, no neural generation, no unique mirror-specific
  advantage, no WAL, and no concurrent writer.

## Integration decision

Keep the responsibilities split:

| Concern | Owner |
|---|---|
| Fast concept identity lookup | conventional hash index (host/control) |
| Directional state and local geometry | mirror-pair lanes |
| Durable typed relationships | hyperedge arena |
| Reference-cycle invariant signals | triangle lanes |
| Language decoding | Round 031 native next-token work, still separate |

`runner_riddle/mirror_retrieval_index.py` is the host-only adapter for the
posting/exact lookup seam. It performs no numerical math, no training, and no
canonical merge. The production MTH path remains NaN16-native.

## Next gate

Connect the Round 031 native decoder to retrieved mirror-pair/hyperedge states
and compare against a matched conventional-memory baseline on questions whose
facts are outside the recurrent context. Until that comparison exists, Round
032 is memory infrastructure evidence, not a language-learning result.
