# Round 028 — shared semantic composition over WordNet

**Status:** external neural experiment, not native NaN16 production math.
Archive: `nan_recursive_round028.zip`
SHA-256: `c4372934651ee5b7673ac7939df2b289cbf72b68e8e1517f78bee11b9a0288bd`.
Machine-readable record: `spec/round028-semantic-learning.v1.json`.

## What improved over Round 027

Round 027 learned individual hyperedge strengths and reached 100% on trained
paths but 50% on untouched paths. Round 028 adds **shared ordered relation
composition**:

```text
A (child gloss) -> R1 -> conditioning by B (middle gloss) -> R2 -> compare C
```

The two 48×48 transforms are trained across child synsets, so the model can
score previously unseen child concepts. This is the first controlled evidence
that reusable relational parameters can transfer beyond the exact stored path.

## Measured result

Three seeds (28, 29, 30), 3,400 child synsets per seed, 70/15/15 child-disjoint
split, test evaluated once per model:

| Model | Accuracy | ROC AUC | BCE |
|---|---:|---:|---:|
| Lexical | 74.22% | 0.81910 | 0.52673 |
| Wide lexical (matched) | 74.58% | 0.82743 | 0.52276 |
| Shared composition | **74.93%** | **0.82775** | **0.51457** |
| Composition + native residual | 74.93% | 0.82773 | 0.51458 |

The composed model reduces mean BCE by about **1.57%** relative to the wider
lexical control. The AUC difference is small. The result is a controlled
WordNet link-plausibility improvement, not a new language-model capability.

Disabling the trained composition branch reduced seed-28 AUC from 0.82671 to
0.79513. That shows the branch is used, but it is not a retrained ablation and
does not by itself prove the geometry's causal advantage.

## Native memory result

Native hyperedge strengths were updated in the live 8 MiB root and the root plus
arena snapshot restored successfully. However:

- mean absolute training strength ≈ **0.007**;
- held-out strengths remain exactly **0.0**;
- held-out AUC/BCE do not improve over shared composition without native
  strengths.

This is a working online native-memory update interface, not evidence of
transfer through the mirror geometry.

## Serious caveats

1. The SVD gloss encoder is fit on all selected glosses, including held-out
   glosses. This is **transductive**, not strictly inductive.
2. Child synsets are disjoint, but candidate and middle synsets may recur.
3. The task is two-hop hypernym plausibility, not free-form generation.
4. Pair addresses are hashed; collisions are possible and are not semantic
   topology.
5. The 256 NaN class labels and the 32,385 reference-cycle projection are not
   used as learned features.
6. The native snapshot is same-platform and not crash-safe.
7. No transformer/GNN/retrieval baseline is included; no geometry-specific
   advantage is established.

## Integration with the unified system

- The shared composition is **external experiment evidence**, not a native MTH
  kernel. Host numerical libraries remain off the production path.
- `runner_riddle/mirror_relation_ops.py` is the host-only typed operator seam;
  operators without native NaN16 implementations return typed `UNAVAILABLE`.
- The physical mirror layout is `spec/mirror-memory.v1.json`: 32 KiB of 256
  heads plus 8,160 KiB of 32,640 pair records, exactly 8 MiB.
- The next gate is a strictly inductive, source-disjoint experiment plus native
  typed operator composition inside the mirror layout. Until then, the result
  is promising but not a geometry-specific claim.

## Non-claims

- No live Koyeb/NANNET0 deployment.
- No canonical model merge.
- No native NaN16 claim for the PyTorch/C++ experiment.
- No general language competence or transfer to arbitrary concepts.
