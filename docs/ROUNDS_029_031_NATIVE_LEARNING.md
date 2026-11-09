# Rounds 029–031 — gauge advantage, native-root classifier, resident byte LM

**Status:** external C++20/PyTorch experiments. They are the evidence base for
gauge invariance and native-root training, but they are not NaN16 production
math and they do not establish a general language-model advantage.
Machine-readable record: `spec/rounds-029-031-native-learning.v1.json`.

Archives:

| Round | SHA-256 |
|---|---|
| 029 | `cf6f526e361affcd85010f61a75c2a8815c2168862bfd51c27acae0827043bc3` |
| 030 | `8fc5399dbbb5c8c7477f0d1b1ef38be52765be963be298fcb0794279abf12591` |
| 031 | `87bffecf6912297162921ef48c588b757b0c8dbd3dd57f2f688d9214b2b3f080` |

## Round 029 — cycle invariance is real; it is not unique to NaN

Controlled WordNet 3.1 gloss classification, 48 triangle dimensions, three
seeds, 1,152 held-out synsets per seed, artificial vertex-gauge shift.

| Readout | Accuracy | Cross-entropy |
|---|---:|---:|
| True cycle triangle | **52.691%** | 1.63859 |
| Raw directed pair | 10.966% | 11.67543 |
| Wrong triangle indexing | 10.706% | 11.62996 |
| Conventional correct triangle | **52.691%** | 1.63859 |
| Learned all-edge control | 26.823% | 2.65367 |

The exact cycle observable cancels additive vertex gauge:
`c^T x = c^T z` for every cycle vector `c` with `Bc=0`. The correct
conventional implementation ties the native cycle readout exactly. The result
is a real invariance effect; it is not a NaN encoding, quantum, or general
language advantage.

Native 8 MiB checks: max gauge error **1.86e-6**, exact reverse antisymmetry,
finite-difference error **6.02e-5**, synthetic loss **0.0658 → 0.0322** after
one local step. 500,000 reads took **1.407 ms** on that Linux host; this is not
portable Android throughput. `mlock` was not active.

## Round 030 — the root itself trains, but the conventional control is strong

Native-root-trained noun-category classifier, 16 classes, 24 external TF-IDF/
SVD dimensions, 384 effective cycle weights, 560 held-out synsets per seed.

| Measurement | Result |
|---|---:|
| Mean cycle accuracy after gauge shift | **42.0833%** |
| Mean raw directed-pair accuracy | 8.2143% |
| Conventional no-intercept logistic | **42.3214%** |
| Native gradient error | 1.86e-9 |
| Max effective coefficient error | 4.17e-7 |
| Max logit change after 101 shifts | 2.84e-4 |
| 1,000 ctypes predictions | 7.74 ms |
| Mirror antisymmetry / snapshot restore | pass / bitwise pass |

The native classifier learns through cross-entropy gradients written into the
triangle edges, and gauge changes leave its predictions intact. The text
encoder is external. The clean-input conventional classifier is equal or
better, so this is evidence of a working native training path, not of superior
semantic learning.

## Round 031 — resident byte LM: real coupling, worse bits per byte

Byte-level recurrent WordNet language model with a 16×16 native root adapter.
100 updates, 13,200 held-out WordNet bytes per model.

| Seed | Ordinary | Native cycle |
|---|---:|---:|
| 17 | **3.89467** | 4.00756 |
| 29 | **3.78293** | 3.84761 |

The ordinary tensor wins in both seeds. Native memory ablation worsens loss but
does not consistently lower accuracy. The archived audit reports maximum gauge
difference **1.2293e-6**, mirror integrity pass, and exact snapshot restore.
The README's “below 8e-7” claim is superseded by the archived `audit.json`
number in this record.

Important limits: 1,800 noun glosses per split were selected in corpus order,
not randomly; training used short-text wraparound; the GRU encoder/decoder is
external; native updates used SGD while the neural parameters used AdamW. The
WordNet graph check verified 1,500 two-hop chains with no direct parent edge,
but that is symbolic lookup, not learned composition.

## What these rounds actually contribute

1. A precise, testable gauge-invariance law.
2. A native 8 MiB root that can be trained, snapshotted, and audited.
3. A strong warning: a correct conventional implementation ties the invariant,
   and a matched dense adapter wins when the geometry is only a fixed weight
   store.
4. The motivation for Round 038–039's unrestricted generation test and for the
   content-gated write path added in this integration.

## Non-claims

- No NaN-encoding advantage over the same conventional triangle observable.
- No quantum effect.
- No general language-model or semantic-comprehension win.
- No claim that the external TF-IDF/SVD encoder or GRU is native.
- No claim that artificial gauge shifts equal natural distribution shift.
- No production optimizer, deployment, fluent generation, or mlock guarantee.
