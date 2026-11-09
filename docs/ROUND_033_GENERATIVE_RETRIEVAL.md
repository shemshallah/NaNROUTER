# Round 033 — episodic copy generation and cycle-memory limits

**Status:** external C++/PyTorch experiment, not native NaN16 production code.
Archive: `nan_recursive_round033.zip`
SHA-256: `3462d986769cf7f8182af00b104eb00300b86342e83841cc66999b2818b3d543`.
Machine-readable record: `spec/round033-generative-retrieval.v1.json`.

## What worked: exact episodic copy

The system identifies an unseen WordNet lemma from a query corrupted in two
character positions, retrieves its stored gloss, and emits the first 24 bytes.

| Seed | Correct 24-byte completions |
|---|---:|
| 17 | 300 / 300 |
| 29 | 296 / 300 |
| 41 | 290 / 300 |
| **Total** | **886 / 900 = 98.44%** |

This is exact retrieval-and-copy. The definition bytes are present in episodic
memory; the model selects the record. It does **not** generate novel prose.

## Native mirror-root test

120 held-out episodes, 12 records × 24 bytes written into anchored triangle
coordinates of one 8,388,608-byte C++ root, then a random vertex-gauge shift of
standard deviation 8:

| Metric | Result |
|---|---:|
| Key selected | 118 / 120 |
| Exact native copy, clean | 118 / 120 |
| Exact native copy, after gauge | 118 / 120 |
| Conventional indexed copy | 118 / 120 |
| Raw single-edge bytes after gauge | 94 / 2880 = 3.26% |
| Triangle-transported record bytes | exact for the 118 selected records |

The cycle invariant `F(0,a,b)=x0a+xab-x0b` is a gauge-independent transport.
It is exact algebraically; float residuals did not alter the copied bytes in
this test. A conventional index has the same selection accuracy.

## What did not work: free-form generation

Matched 24-channel byte LMs, 180 updates, 43,648 parameters:

| Seed | Plain bpb | Triangle bpb |
|---|---:|---:|
| 17 | 3.67070 | 3.67077 |
| 29 | 3.67881 | 3.67881 |

Mean: **3.67475 plain vs 3.67479 cycle** — effectively tied. Both produce
incoherent samples. Adding cycle coordinates as another weight matrix is not
enough. Scrambling the triangle assembly after training hurts, but that is a
mismatched ablation, not proof of a unique topology benefit.

## Correct architecture

The evidence supports a **copy-and-generate hybrid**:

1. a byte/subword decoder for grammar and free-form prediction;
2. a learned copy gate that decides when to use stored evidence;
3. native mirror lanes for directional state and gauge-invariant transport;
4. a recursive hyperedge arena for durable facts and provenance.

The geometry should be persistent episodic memory, not a replacement for every
operation in a conventional neural network.

## NaN-native primitives required

The host retrieval seam already exists in
`runner_riddle/mirror_retrieval_index.py`. The following native primitives are
being added and must pass fixtures before promotion:

- `mth.byte.copy24` — exact bounded 24-byte transport;
- `mth.definition.slot_io` — typed 24-byte definition slot in a pair record;
- `mth.gauge.triangle_recover` — gauge-invariant triangle read/compare;
- `mth.copy_gate` — deterministic copy-vs-generate gate;
- `mth.retrieval.top1` — first-index top-1 over 12 candidates;
- `mth.byte.fallback_argmax` — first-index byte fallback.

These are local native primitives. They do not make the C++/PyTorch experiment
a native result, and they do not train a copy gate.

## Non-claims

- No fluent language model.
- No novel-prose synthesis from the episodic path.
- No conventional-index advantage claim.
- No cycle-specific free-form LM gain.
- No NaN16 claim for the external experiment.
- No canonical merge or live deployment.
