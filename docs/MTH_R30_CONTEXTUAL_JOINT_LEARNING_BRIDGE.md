# R30 — Restored contextual joint learning on the original 48M hybrid

**Implementation:** `scripts/train_r30_contextual_joint_candidate.py` on existing NaNROUTER PR #119. This is a measured host-side candidate learning bridge, **not** yet native NaN16 training or full tensor self-modification. It does not create a replacement language model.

## Source recovery and the 75% reference

The available original archives establish genuine contextual learning in R17/R20 (ordered word unigram/bigram/trigram updates) and R22 (forward/inverse word-conditioned character heads). R14 reports 51.40% held-out news-word completion on a specific completion task. The author-referenced earlier **75%** benchmark has **not** yet been recovered with an exact test protocol; do not misrepresent these different tasks as 75% top-1 next-word accuracy. R24–R28 exact lexical normalization is retained, including all 69,974 known spellings in a 205,073-node trie.

## What has been implemented and measured

The same real train-only causal observation `(previous_word_2, previous_word_1, target_word)` updates:
1. The **existing** R20 known/OOV token unigram, bigram and trigram count tables via `ordered_gutenberg_v17.update_token_counts`.
2. The **existing** R22 previous-word and hashed word-pair forward/reverse character-context tables, for every observed character and EOS.
3. Evaluation with the **same** exact R25 whole-word probability including the original OOV spelling model and vocabulary-exclusion trie normalization.
4. Matched three-arm ablation with character-only, token-only and joint updates at each epoch, allowing independent component credit instead of a forced inseparable update.
5. Candidate admission selection on development text only; historical test is read once after development selection. All source SHA-256 pins are verified before and after. Original 43M base, R22 5M overlay, 8 MiB NaN0S root and active 128 MiB mirrored tensor remain frozen.

The computed meta **diagnostic**, not a trainable native meta gradient, uses exact two-factor Shapley attribution:

```text
C_char = 1/2 * [(L_base-L_char) + (L_token-L_joint)]
C_token = 1/2 * [(L_base-L_token) + (L_char-L_joint)]
C_char + C_token = L_base - L_joint
```

Unlike a raw character loss gate, this can tell meta when a token update helps full-word loss but character updates hurt it. Per-context and trihead attribution, trust-region optimizer, tensor updates and authenticated native journal remain unimplemented.

### Three actual local candidate epochs

40,000 real unprotected ordered word occurrences per epoch, same early historical TRAIN slice; 128 DEV next-word positions, 17 true OOVs; exact whole-word likelihood, not byte accuracy.

| Arm | Epoch 1 DEV NLL | Epoch 2 DEV NLL | Epoch 3 DEV NLL |
|---|---:|---:|---:|
| Frozen original (epoch 0) | 6.988146 | 6.988146 | 6.988146 |
| Character-only | 6.988423 | 6.989398 | 6.990606 |
| Token-only | 6.987799 | 6.987765 | **6.987763** |
| Joint updates | 6.988075 | 6.989017 | 6.990223 |

Best development-selected arm: **token-only, epoch 3**; historical TEST is **worse**, from 6.059459 to 6.060108 NLL on the same 128 positions. It must **not be promoted**. This is a small, previously examined Gutenberg split; no fresh-author confirmatory claim.

At epoch 3, full-word development credit is `C_char=-0.002459330` nats and `C_token=+0.000382964` nats. The net joint change is a regression, confirming that blindly updating both is a wrong admission policy.

## Required native integration to make learning fully end-to-end

1. **Stable typed address mapping:** R22 has 1,024 virtual word-context slots, **not 1,024 NaN16 physical heads**. Do not alias them to heads 0–254 by simple modulo. Define a versioned virtual-context-to-head routing namespace and preserve head 255 as void/reserved.
2. **Causal NaN16 training:** Guest kernels must compute/update word-conditioned character, word-token and mirrored 256^3 tensor representations from the *same* event. Python currently forms count sufficient statistics; it is a reference implementation, not a native optimizer.
3. **Exact whole-word objective:** Let `p_tok(w|a,b)` be the smoothed word probability and `Q(w|a,b,OOV)=S(w|a,b)/(1-M_known(a,b))` the exact normalized novel spelling channel. For known words, use `-log p_tok(w|a,b)`; for OOV, use `-log p_tok(UNK|a,b)-log Q(w|a,b,OOV)`. Correct candidate gradients must include the derivative of the exact known-vocabulary mass: `grad log Q=grad log S+grad M_known/(1-M_known)`.
4. **Local → trihead → global feedback:** 255 participating heads, 85 three-head groups, persistent directional mirror lanes in the 64 MiB active + 64 MiB candidate full tensor. A trihead may *propose* edits to any authorized candidate cell, subject to provenance/permissions; do not mutate active weights during evaluation. Group/meta credit requires actual per-context/per-cell evidence, not just the two global Shapley numbers.
5. **Multi-step credit and optimizer:** Add recurrent/sequence credit (real truncated BPTT or mathematically audited alternative), optimizer state per candidate tensor update, counterfactual ablations, damping/trust region, and rollback. Simple count replay is not differentiable sequence learning.
6. **Training/evaluation and promotion:** Train on documents from `shemshallah/NaNROUTER/corpora/*` with explicit corpus provenance, document disjoint splits and deduplication. Meta accepts or rejects using exact native whole-word development loss and other protected invariants. Held-out test has no admission authority. Require new independent books, more than 128 positions and matched baseline controls before any active promotion. Native journal must be authenticated, crash-safe and rerunnable, preserving 8 MiB root. No production promotion exists yet.

## Reproduce the implemented candidate

Extract the cumulative Round 29 archive containing `train_r29_10epochs.py` and its `experiment_archive/` original checkpoint/corpus. The R30 script reuses these exact source readers and pin lists:

```bash
R29_ARCHIVE_ROOT=/path/to/extracted/r29work OPENBLAS_NUM_THREADS=1 \
  python3 scripts/train_r30_contextual_joint_candidate.py \
  --train-words 40000 --epochs 3 \
  --output /tmp/r30_contextual
```

Results are `report.json` and an **unpromoted** `devselected_contextual_candidate.npz`, with original checkpoint digests included. The cumulative Round 30 archive holds the complete original checkpoint and sources privately in ChatGPT Library. Never add model weights or the full training corpus to GitHub.
