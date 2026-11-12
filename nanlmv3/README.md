# nanlmv3

Standalone frontier-trajectory language model built **only** from the Python
files supplied by the user:

- `transformer_baseline_lm.py` — alphabet, normalization, embedded text, causal
  transformer baseline shape.
- `c256_..._6gram_final.py` — 255 heads, two rails, 32,640 mirror pairs,
  variable-order n-gram baseline.
- `mirror.py` / `CHANGELOG` — palindromic head addresses, triheads, head field,
  mirror-pair field, NaN/absence heads.
- `poincare_lm.py` — Poincaré disk registers, antipodal mirror pairs,
  hyperbolic trihead clustering, curvature/polarity storage, hotness,
  top-K trihead routing, mirror contrastive loss, S+/S- next/prev heads.

It does **not** import or depend on any NaN* repository code. The only thing
taken from `NaNROUTER` is corpus data under `corpora/` (or a release asset),
as explicitly allowed.

## Files

| File | Role |
|---|---|
| `frontier_model.py` | Stage 0 LM: smoothed n-gram memory, 255-head → trihead/field/rail/curvature geometry, ~10M MLP, next + S− prev heads |
| `head_geometry.py` | Palindromic heads, 85 triheads, 2/3 and 3/3 votes, head field, 32,640-pair field, rails, curvature, fabric codebook |
| `poincare_geometry.py` | Poincaré disk, antipodal mirror pairs, hyperbolic trihead clustering, curvature/polarity/hot routing, mirror loss |
| `train_bpe.py` | 32k byte-level BPE trainer using `tokenizers` |

## Quick start

```sh
# Stage 0 exact smoothed n-gram baseline
python nanlmv3/frontier_model.py --mode ngram \
  --supplied /path/to/transformer_baseline_lm.py \
  --orders 8 --summary ngram.json

# Hybrid: memory + geometry + 10M mixer
python nanlmv3/frontier_model.py --mode hybrid \
  --corpus /path/to/corpus.txt \
  --params 10m --steps 10000 --summary hybrid.json

# 32k BPE (host with a prebuilt `tokenizers` wheel)
pip install tokenizers
python nanlmv3/train_bpe.py --corpus /path/to/corpus.txt \
  --vocab-size 32000 --output bpe32k.json
```

`frontier_model.py --tokenizer bpe --bpe-model bpe32k.json` consumes the
trained tokenizer.

## Current status

Stage 0 is implemented and measured:

- 1.6M-char Gutenberg sample, exact smoothed n-gram, orders 1–8:
  **65.7% char accuracy, 3.17 bits/char**.
- 2M-char hybrid, ~0.9M mixer: **65.4% accuracy, 2.79 bits/char**.
  Memory is the main driver; geometry features are neutral at this scale.
- 10.68M-parameter mixer verified (3-step and 100-step smokes).
- Poincaré disk + hyperbolic triheads + S− prev head integrated.

The next architectural step is **geometry-routed memory**, not more geometry
side-features: radius = specificity/order, triheads = memory shards/experts,
curvature = backoff/confidence, polarity = next/previous rail. That is the
path that can scale.
