# nanlmv3 results ledger

All runs are GitHub Actions runs in `shemshallah/NaNROUTER`. These are CPU
runner results, not GPU-scale claims.

## Architecture

- 255 palindromic head addresses → 85 triheads (2/3 and 3/3 votes).
- Head field + 32,640-pair mirror field.
- S+/S− rails, triangle → pair mapping, oriented wedge curvature.
- Curvature codebook (“global fabric”) features.
- Poincaré disk: 127 antipodal mirror pairs + center, hyperbolic trihead
  clustering, learnable curvature/polarity/hotness, top-K routing, mirror
  contrastive loss.
- Causal attention trunk + ~10M MLP mixer.
- Geometry-routed order memory: the order gate starts at full backoff and can
  shift between n-gram orders from the geometry features.
- Next-token head plus an auxiliary S− previous-token head.

## Runs

### 43128751982 — BPE 32k

- 49.6M chars, 32,000 vocab, 31,740 merges
- 2.2 MB tokenizer artifact
- 27 s

### 43129164435 — BPE + 10M, no trunk

- 1,105,866 BPE train tokens
- 10,730,871 params
- 500 steps
- 8.19 bits/token, 15.62% top-1
- Memory-only 15.62%; previous-token 6.25%

This was a pipeline smoke test: 500 steps is far too short and there was no
sequence encoder.

### 43130577419 — 100M corpus, trunk + routed memory, 2000 steps

- 10 MB model sample → 2,438,651 BPE tokens
- 9,584,551 params
- Causal trunk 2×4, routed-order memory
- 12.08 bits/token, 12.5% top-1
- Memory-only 12.5%; previous-token 0%

The order gate was initialized uniformly over orders, which weakened the memory
prior. Fixed by initializing it at full backoff.

### 43131495724 — 20 MB head sample, 5000 steps

- 4,723,629 BPE tokens
- 9,584,551 params
- Train loss ≈ 4 bits; validation 8.575 bits/token
- 18.75% top-1; memory-only 21.88%; previous-token 3.125%

The validation split came from later books because the model sample was taken
with `head -c 20MB`. This was an out-of-distribution split, not a training
crash.

### 43133825859 — chunk-disjoint 20 MB, 5000 steps

- 4,668,494 BPE tokens; 4,201,644 train tokens
- 20 chunks across the 100M corpus; 18 train + 2 interleaved held-out chunks
- 9,584,555 params; trunk 2×4; routed-order memory
- Validation: **7.29 bits/token**, 18.75% top-1
- Memory-only: 21.88% top-1
- Train loss: **~1.5–2.3 bits**
- Order gate settled at `[~0, ~0, ~0, 1.0]` (full backoff)

This is the real limiter: a 9.6M model memorizes the 4.2M-token training sample
and does not generalize. The chunk-disjoint split fixed the earlier
out-of-distribution artifact (8.57 → 7.29 bits), but the train/validation gap
is still huge. More CPU steps will not fix it; the next run needs a GPU and a
larger token budget.

## GPU hybrid scaling — controlled 90% gate

Kaggle T4, `nanlmv3/hybrid_poincare.py`.

| Branches | Sentences | Centroids | Params | Test acc | Target | Time |
|---:|---:|---:|---:|---:|---|---:|
| 4 | 1000 | 4 | 2,587,022 | **100.00%** | met | 50 s |
| 16 | 2000 | 16 | 2,603,366 | **100.00%** | met | 90 s |
| 32 | 4000 | 32 | 2,625,158 | **100.00%** | met | 179 s |

Each run is a separate Kaggle kernel:
- https://www.kaggle.com/code/shem42/nanlmv3-hybrid-poincare
- https://www.kaggle.com/code/shem42/nanlmv3-hybrid-b32

The 90% gate is a controlled branching-curriculum gate. It is not a natural
text claim. The point is that the hybrid keeps the gate as branch factor grows.

## 100M hybrid backbone — measured real-text metrics

Kaggle T4 kernel: https://www.kaggle.com/code/shem42/nanlmv3-hybrid-100m

| Metric | Value |
|---|---:|
| Corpus | 100M chars |
| BPE vocab | 32,000 |
| BPE tokens | 23,341,783 |
| Train / val tokens | 22,174,693 / 1,167,090 |
| Parameters | 9,479,127 |
| Steps | 20,000 |
| Batch / context | 16 / 128 |
| Final val loss | 6.3821 |
| Final bits/token | **9.207** |
| Top-1 | **14.65%** |
| S− previous-token | 5.66% |
| Train time | 602 s |

Validation loss improved from 10.20 bits/token at step 1,000 to 9.21 at step
20,000. The run is a real baseline, not a finished model: 22M train tokens for
a 9.5M model is far below a compute-optimal token budget, and this run
deliberately used no exact n-gram memory.

This backbone includes the causal trunk, 255-head / 85-trihead / field / rail /
curvature stack, the Poincaré trihead branch, and the S− head. It does **not**
include the 128-pair MoE from the branch-gate job or the n-gram memory.

## Unified model — one code path

`nanlmv3/unified.py` is the single model for both modes:

- `--mode synthetic`: branches 1–4, word tokens, 90% gate
- `--mode text`: BPE 32k, 100M corpus, real bits/token / top-1 / top-5

### Unified branch gate — measured

Kernel: https://www.kaggle.com/code/shem42/nanlmv3-unified-branches

| Branches | Test accuracy | Params | Target |
|---:|---:|---:|---|
| 1 | 100.00% | 1,560,200 | met |
| 2 | 100.00% | 1,560,912 | met |
| 3 | 100.00% | 1,561,624 | met |
| 4 | 100.00% | 1,562,336 | met |

2000 sentences, 50 epochs, one `UnifiedHybridLM`, ~411 s total on T4.

### Unified 100M — measured

Kernel: https://www.kaggle.com/code/shem42/nanlmv3-unified-100m

- 100M chars, BPE 32k, 23,341,783 tokens (22,174,693 train / 1,167,090 val)
- 12,795,744 params
- 20,000 steps, batch 16, context 128, AMP
- Training time: **606.8 s = 10.1 min**
- End-to-end: **~12.4 min** (including corpus download, BPE, encode)
- Throughput: **~67,500 tokens/s**

| Checkpoint | Step | Val loss | Bits/token | Top-1 | Top-5 | Prev |
|---|---:|---:|---:|---:|---:|---:|
| Best | 9,000 | 6.6324 | 9.569 | 14.84% | 26.37% | 4.69% |
| Final | 20,000 | 6.7377 | 9.720 | 12.50% | 26.76% | 6.25% |

Version 1 failed on `out_proj` shape (`16x224` vs `64x224`); fixed in
`66b36c7`. Version 2 is the measured run above. The best checkpoint is at
step 9,000, not the final step.

Planning extrapolation at ~67,500 tokens/s:

| Steps | Tokens | Training time |
|---:|---:|---:|
| 20k | 41M | 10.1 min |
| 100k | 205M | 50.6 min |
| 1M | 2.05B | 8.4 h |
| — | 1B | 4.1 h |
| — | 10B | 41.2 h (multi-session) |

## v2 10-minute learning smoke — measured

Kernel: https://www.kaggle.com/code/shem42/nanlmv3-v2-smoke

- 20M-char corpus, BPE 32k, ctx 256, batch 8
- 84,859,523 params
- 7,010 steps in 540 s = 14.36M tokens
- Throughput: ~26,600 tokens/s
- Hard stop at 540 s

| Step | Bits/token | Top-1 | Top-5 |
|---:|---:|---:|---:|
| 100 | 13.457 | 3.12% | 23.44% |
| 500 | 10.486 | 7.81% | 25.00% |
| 3,000 | 9.988 | 7.81% | 29.69% |
| 5,700 | **9.111** | **10.94%** | **29.69%** |
| 7,010 | 10.802 | 9.38% | 28.13% |

The loss curve falls from 13.46 to 9.11 bits/token at the best checkpoint, so
v2 is learning. It is noisy and the final step is worse than the best step;
the best checkpoint is retained.

Geometry movement:

- centroid delta: **0.3099**
- curvature: **-1.0129**
- branch temperature: **0.9815**
- memory alpha: **0.204** (initialized 0.1)

At smoke throughput, the 204.8M-token long run is roughly 2.1 hours of
training before context-512 attention overhead; expect 2.5–4 hours.

## Why the first smoke showed a peak

The peak at step 5,700 was not a clean real optimum:

- **Changing validation set:** every eval sampled 64 new random tokens from
  the shared training RNG. Top-1 resolution was 1/64 = 1.56%.
- **Constant LR:** cosine was scheduled over 100,000 steps, but the smoke
  stopped at 7,010. LR stayed ~3e-4, so late training was still noisy.
- **Batch noise:** batch 8 = 2,048 tokens per step; step losses ranged 5.6–11.3.
- **Memory alpha growth:** 0.1 → 0.204 while the memory bias was still being
  applied to held-out contexts.
- **Contiguous validation:** the last 5% of a 20MB slice, not chunk-disjoint.

Smoke2 fixes all five: fixed 256-token validation set, LR 1.5e-4 cosine over
7,000 steps, chunk-disjoint 20MB sample, and alpha clamped to [0, 0.5].
Kernel: https://www.kaggle.com/code/shem42/nanlmv3-v2-smoke2

## Honest reading

- The memory prior is the main driver at this scale.
- The geometry features are not yet beating the memory; they need to *route*
  memory/experts, not only decorate the mixer.
- The order gate stayed at full backoff because the geometry features are too
  weak/constant to move it; the hidden-state path should also feed the gate.
- 10M params on 4M BPE tokens for 5k CPU steps is a pipeline/ablation run, not
  a quality result. A real Stage 2 needs 100M–1B tokens and a GPU.
