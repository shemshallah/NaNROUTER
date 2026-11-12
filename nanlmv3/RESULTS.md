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

- In progress at the time of writing.
- 20 chunks across the 100M corpus; 18 train + 2 interleaved held-out chunks.
- Same trunk/routed-memory architecture.
- Purpose: measure the same model with an in-distribution validation split.

## Honest reading

- The memory prior is the main driver at this scale.
- The geometry features are not yet beating the memory; they need to *route*
  memory/experts, not only decorate the mixer.
- 10M params on 4M BPE tokens for 5k CPU steps is a pipeline/ablation run, not
  a quality result. A real Stage 2 needs 100M–1B tokens and a GPU.
