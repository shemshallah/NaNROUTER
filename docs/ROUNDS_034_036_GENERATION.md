# Rounds 034–036 — copy gate, recursive composition, multi-source generation

**Status:** external C++/PyTorch experiments. Not native NaN16 production math,
not a fluent language model, and not a unique NaN-geometry advantage.
Machine-readable record: `spec/rounds-034-036.v1.json`.

## Round 034 — open-set copy-or-abstain router

A learned router decides whether to copy a stored 24-byte gloss or abstain.
Across seeds 17/29/41, 600 balanced queries per seed:

| Metric | Mean |
|---|---:|
| Accept/abstain accuracy | 99.0% |
| False-answer rate | 0.444% |
| Exact grounded completion | 48.94% |

Under an untrained **6-character corruption** shift, accept/abstain drops to
**61.89%** and positive acceptance to **23.78%**. This is a real failure mode.

Native audit: 89 accepted present-record queries, **89/89 exact** after gauge
shift through the C++ 8 MiB cycle memory; conventional index **89/89**; raw
single-edge **0/89**.

LM-only held-out bits/byte was **3.60–3.66**; the copy mixture reached
**0.18–0.45** because the correct bytes were already stored. The conventional
index ties exactly. This is not synthesis.

## Round 035 — recursive typed composition

A 13-feature gate decides whether two stored typed relations compose. The
two-hop gate reached **100% test accuracy** with tiny BCE, but it receives
explicit equality indicators; that is not evidence of autonomous language
understanding.

The separate 3-hop native test used 60 real WordNet chains and 60 broken paths:
**120/120 exact** answers/abstentions through cycle memory after a large gauge
change; raw single-edge reading recovered **60/120**; conventional composition
also matched. This is a deterministic typed-path interpreter, not a trained
3-hop neural generalizer.

## Round 036 — neural multi-source generation

An encoder-attention-autoregressive GRU decoder was trained on **81,499**
WordNet synsets (17,986 train / 2,998 validation / 2,998 test), 38,268
parameters, 145 steps per seed.

- Seed 17: **50.00%** semantic accuracy, collapsed to constant abstention.
- Seed 29: **100%** semantic accuracy on the restricted, role-normalized test;
  exact surface match **67.01%** because multiple phrasings are accepted.
- Native audit: **90/90** prompts decoded exactly after a gauge shift of
  standard deviation 80; **90/90** neural answers unchanged; raw single-edge
  **0/90**; conventional index **90/90**.
- Stress before adversarial retraining: in-distribution **300/300**;
  contradictory `opposes` premises **0/300** correct abstentions; unseen
  four-hop **0/150**.
- Robust retraining with `opposes`: **1,499/1,499** connected,
  **1,499/1,499** disconnected, **1,499/1,499** relation-conflict examples.

The model uses normalized entity slots `e0,e1,...` and synthetic grammar
variations. It is not an open-domain prose model.

## What the geometry contributes

Additive vertex-gauge changes preserve the anchored triangle value:

```text
F(0,a,b) = e(0,a) + e(a,b) - e(0,b)
```

This is exact algebraically and robust in the native tests, but an ordinary
implementation of the same invariant graph algorithm shares the property.
The evidence supports **gauge-invariant episodic transport**, not a universal
language-model advantage.

## Integration

The external experiments map onto existing native primitives:

- `mth.copy_gate.f32` — copy/abstain decision seam;
- `mth.retrieval.top1.f32` — candidate selection;
- `mth.byte.copy24.u32` — exact answer transport;
- `mth.definition.slot_io.u32` — stored definition bytes;
- `mth.gauge.triangle_recover.f32` — gauge-invariant triangle reads;
- `mth.hyperedge.path_score.f32` and `mth.relation.operator_apply.f32` —
  typed composition scoring.

Host seams remain `mirror_retrieval_index`, `mirror_relation_ops`, and
`mirror_hyperedge_arena`.

## Next gate

Jointly train the copy gate with the byte decoder, use real unnormalized prose,
and compare against matched conventional memory and attention baselines on
held-out bits per byte, exact facts, latency, and memory. Until then, these are
controlled retrieval/composition experiments, not a generative language-model
claim.
