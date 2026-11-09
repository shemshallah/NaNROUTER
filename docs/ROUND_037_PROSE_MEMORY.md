# Round 037 — prose-to-memory, compositional queries, retention

**Status:** external C++/PyTorch experiment. Not native NaN16 production math
and not a full natural-language model.
Archive SHA-256: `d28e1886ec0d9dde16c6b68d9d788c5349ec042b0e5e8989a22c29acc2d84c53`.
Machine-readable record: `spec/round037-prose-memory.v1.json`.

## Pipeline

```text
prose paraphrase
  -> bidirectional GRU relation writer (4 classes)
  -> native 8 MiB mirror triangle storage
  -> deterministic 2/3-hop traversal
  -> trained autoregressive decoder
```

The writer learns forward subtype, reverse subtype, negated subtype, and
uncertain subtype from 10 authored patterns; 2 held-out patterns are tested.
Entity boundaries and identities are supplied. This is controlled predicate
classification, not unrestricted prose understanding.

## Measured results

Across seeds 17/29/43, 200 previously unseen concept chains each:

| Stage | Geometry | Conventional | Total |
|---|---:|---:|---:|
| Before gauge | 400/400 | 400/400 | 400 |
| After gauge | 400/400 | 400/400 | 400 |
| After writer adaptation | 400/400 | 400/400 | 400 |
| Old queries after new writes | 400/400 | 400/400 | 400 |
| New chains acquired | 80/80 | 80/80 | 80 |

Writer template accuracy: **10/10 seen**, **2/2 held-out** per seed.
Raw single-edge retrieval after gauge averages **64.92%**, vs 100% for the
gauge-invariant triangle path.

Native geometry audit: 600 values, max absolute gauge error
**1.81 × 10⁻⁵**, exact snapshot restoration of the 8 MiB root.

Generation audit: 90 held-out episodes; native cycle source recovery
**90/90**, raw source recovery **0/90**, outputs unchanged after gauge
**90/90**, semantic correctness **90/90**, conventional index **90/90**.
The decoder checkpoint is Round 036 `robust_29.pt`; it uses restricted
entity-slot vocabulary and is not retrained jointly with the writer.

## Native integration added

- `mth.mirror.slot_map.u32` — exhaustive 32,385 lexical reference slots to
  `(a,b)`, canonical pair id, and pair-record offset; native fixture walks all
  slots.
- `mth.relation.writer_class.u32` — native encode/decode of the four writer
  classes to forward/reverse/negated/uncertain flags.
- `runner_riddle/mirror_slot_index.py` — host-only slot index with exhaustive
  inverse/coverage tests.

Existing native seams used by the pipeline: hyperedge path score, gauge
triangle recovery, definition slot I/O, copy gate, and byte copy.

## Non-claims

- No unrestricted prose extraction.
- No learned arbitrary-depth reasoning.
- No catastrophic-forgetting proof from explicit-fact retention.
- No geometry or NaN-specific advantage over conventional indexed memory.
- No joint writer/geometry/decoder optimization.
- No native NaN16 claim for the C++/PyTorch experiment.
- No canonical merge or live deployment.

## Next gate

Train matched geometric and conventional graph memories on natural,
unnormalized prose, with model-produced entity extraction, a jointly trained
copy gate/decoder, adversarial false premises, 2–5-hop reasoning, and 500+
token intervening noise. Gauge perturbation is a stress dimension, not the
only success condition.
