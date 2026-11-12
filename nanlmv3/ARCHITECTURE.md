# nanlmv3 architecture — heads → triheads → fields → rails → curvature → fabric

This is the standalone design distilled from the supplied Python:

- `transformer_baseline_lm.py` — causal transformer baseline, 39-symbol alphabet.
- `c256_..._6gram_final.py` — 255 heads, 2 rails, 32,640 pairs, 3/4/5/6-gram
  counts, hierarchical backoff.
- `mirror.py` / `CHANGELOG` — palindromic head addresses, 85 triheads, head
  field, mirror-pair field, NaN/absence heads.
- `poincare_lm.py` — Poincaré disk, antipodal mirror pairs, hyperbolic trihead
  clustering, curvature/polarity storage, hotness, top-K routing, mirror loss,
  S+/S− heads.

No NaN* repository code is imported. NaNROUTER supplies corpus data only.

## 1. The address algebra

A head is a 16-bit palindrome:

```text
pal16(seed) = (seed << 8) | reverse8(seed)
```

There are 256 such words; 255 is the VOID/global head and 8 are NaN/absence
heads (`124..127`, `252..255`). The trainable head range is `0..254`.

A mirror pair is canonical `a < b`:

```text
pair_id(a,b) = 1 + a*(511-a)/2 + (b-a-1)
```

`C(256,2) = 32,640` pairs. Each pair has two 128-byte lanes, S− and S+.

A trihead is a triangle of three heads. There are `C(256,3) = 2,763,520`
possible triangles, but the working set is 85 triads (`255 = 3 × 85`). Each
triad emits a 3-bit member mask; `>= 2/3` accepts, `3/3` is hot. A 43/85 field
quorum is the design convention for a global decision.

## 2. The feature hierarchy

```text
255 head credits
  ├─ 85 triads: 2/3 votes, 3/3 hot, signed triad energy
  ├─ 255-head field: mean, std, norm, positive fraction
  ├─ 32,640-pair mirror field: exact bilinear mean/std in O(255)
  ├─ S+/S− rails: per-head side, per-triangle 3/3..0/3 class
  ├─ triangle → pair map: three pair ids, lane 0/1 per rail product
  ├─ triangle curvature: oriented wedge circulation
  └─ curvature codebook: (triad, bin, rail class) → fabric vector
```

The exact pair-field sums are computed without materializing 32,640 pairs:

```text
sum_{a<b} x_a x_b   = ((sum x)^2 - sum x^2) / 2
sum_{a<b} (x_a x_b)^2 = ((sum x^2)^2 - sum x^4) / 2
```

For a triangle `(a,b,c)` with oriented edge values `e_ab, e_bc, e_ca`:

```text
curl = e_ab + e_bc + e_ca
kappa = curl / (|e_ab| + |e_bc| + |e_ca| + eps)
```

The current implementation uses a learned wedge edge
`e_ab = u_a · v_b − u_b · v_a`, which cancels additive vertex gauge shifts
around a closed triangle. A bilinear product `x_a x_b` is also available as a
simpler energy.

## 3. Poincaré disk

The disk is a hierarchical address space, not a decoration:

- 127 antipodal mirror pairs plus center head 127.
- `u[254-a] = −u[a]`; mirror pairs have large hyperbolic distance.
- Radius = specificity: center is general, edge is specific.
- Triheads are clustered by hyperbolic distance from the center outward.
- Each triad has learnable curvature and S+/S− polarity.
- Hotness is a learned confidence gate; routing is top-K.
- A mirror contrastive loss keeps a triad and its mirror consistent.
- Re-clustering can run periodically as the disk moves.

Hyperbolic distance:

```text
d(u,v) = arcosh(1 + 2||u−v||² / ((1−||u||²)(1−||v||²)))
```

## 4. Why geometry as side features is not enough

Stage 0 measured this directly:

- Exact smoothed n-gram, 1.6M-char Gutenberg sample: 65.7% char, 3.17 bits/char.
- Hybrid with head geometry features, 2M sample: 65.4% char, 2.79 bits/char.
- Geometry features were neutral; the memory prior did the work.

The lesson: a feature vector does not force the model to use the geometry.
Geometry must **route** computation:

- **Radius → order/specificity.** High radius selects longer, more specific
  n-gram orders; center selects backoff.
- **Trihead → memory shard/expert.** Top-K triads select which memory buckets
  or experts are queried.
- **Curvature → confidence/backoff.** High |κ| means use the long order; low
  |κ| means interpolate/backoff.
- **Polarity → next/previous rail.** S+ drives the next-token head, S− drives
  the previous-token/reconstruction head.
- **Fabric code → retrieval key.** Curvature/polarity/hot codes index a
  codebook or a sparse memory store.

The current Stage 1 implementation starts with **order-routed memory**: the
order gate is initialized at full backoff and learns to shift among orders from
the geometry. The next step is trihead-routed expert memory.

## 5. Scaling ladder

| Stage | Model | Data | Hardware | Goal |
|---|---|---|---|---|
| 0 | n-gram + 10M MLP | 1–10M chars | CPU | ceiling and ablation |
| 1 | causal trunk + 10M mixer + routed memory | 20–100M chars | CPU / 1 GPU | in-distribution curves |
| 2 | 100M–1B backbone + trihead expert memory | 1B–100B tokens | 8–64 GPUs | competitive small model |
| 3 | 1B–7B hybrid | 100B–1T tokens | 64–1,000 GPUs | frontier-adjacent |
| 4 | 70B+ MoE + memory | 10T+ tokens | 1,000+ GPUs | frontier |

Compute rule of thumb: `FLOPs ≈ 6 × params × tokens`. A 10M model on 1B tokens
is ~6e16 FLOPs; on a CPU runner that is weeks. The CPU runner is for
architecture validation, not scale.

## 6. What “frontier” actually requires

- Data: 1T+ deduplicated tokens for a serious 1B–7B run; 10T+ for frontier.
- Compute: $1M–$10M for a 7B/1T run; $50M–$500M+ for 70B+.
- Memory: 100 GB–10 TB for the count/retrieval fabric.
- Team: 10–30 people for a 1B–7B hybrid; 50–200 for frontier.
- Time: 12–24 months for a credible 1B–7B hybrid; 2–5 years for frontier.

A pure count model has an n-gram ceiling. Frontier performance requires a
learned backbone; the geometry is the memory/router that differentiates the
hybrid.

## 7. Unified implementation (single code path)

`nanlmv3/unified.py` replaces the separate branch-curriculum and text models
with one `UnifiedHybridLM`:

```text
tokens -> embedding + positional
       -> causal trunk (optional)
       -> last token + attended context
       -> hyperbolic branch gate (N centroids)
       -> router
       -> 128 mirror-pair MoE, top-8, load balanced
          (geometry features bias the MoE gate)
       -> residual + LayerNorm
       -> tied token logits
       -> optional S- previous-token head
```

Modes:

- `--mode synthetic`: branches 1–4, word tokens, 90% gate.
- `--mode text`: BPE 32k, 100M corpus, bits/token / top-1 / top-5.

Measured unified branch gate (T4):

| Branches | Accuracy | Params |
|---:|---:|---:|
| 1 | 100.00% | 1,560,200 |
| 2 | 100.00% | 1,560,912 |
| 3 | 100.00% | 1,561,624 |
| 4 | 100.00% | 1,562,336 |

The 12.8M-parameter text configuration uses the same model path with
`d_model=224`, `d_hidden=64`, a 2-layer causal trunk, and BPE 32k.

## 8. Next concrete changes

1. **Trihead-routed experts.** Partition the n-gram memory into 8–85 shards;
   route with top-K triads. Measure bits/token against the global memory.
2. **Hashed count store.** Replace Python dicts with set-associative
   `c(256,3)` buckets and top-K continuations; scale beyond 10M tokens.
3. **Curvature fabric retrieval.** Use `(triad, bin, rail)` codes as keys into
   a learned codebook or a sparse retrieval store.
4. **Longer context + more data.** 512–2,048 token trunk, 100M–1B BPE tokens.
5. **GPU run.** The CPU runner has proven the pipeline; the next quality jump
   is a GPU with the same code.
