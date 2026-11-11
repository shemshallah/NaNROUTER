# Round 29 — ten timed original-48M hybrid head epochs (candidate-only)

**Status:** Real local ten-epoch training completed. Exact whole-word development gate **rejected every epoch**. No checkpoint or active tensor promotion.

## Provenance

The original Round 28 archive was recovered from ChatGPT Library. Original 43M checkpoint SHA-256: 299a91daf65c8e66fe3489940371d262afef18dd2ef6fef61947ac14c62bb717. The 5M R22 overlay SHA-256: 62bf1e5defbb8224d795db16a8e6959cc9aa3d7fed8a63346c4cee205a1bea04.

Corpus source: shemshallah/NaNROUTER/corpora/short_stories, release corpora-short-stories, archived TRAIN SHA-256 1f9eccda30366f40944a29dfc4ef073c77334526e773276e98ae21625ded4daf. The frozen DEV and TEST corpus checksums were also verified before training.

Exactly 10 complete passes through a fixed **40,000-occurrence ordered slice** of real short-story TRAIN text; **not** the full 260-book corpus. Original R22 previous-word and pair-word character count heads updated from all forward/reverse characters and EOS per word; R13 hierarchy, original 48M base/overlay, token vocabulary, 8 MiB native root and 128 MiB active mirror tensor remained unchanged. Original R22 originally sampled one character per event, so this full-word update is a changed continuation rule.

Each epoch: 410,822 bidirectional character targets / 821,644 original R22 head count increments. Ten epochs: 4,108,220 character targets / 8,216,440 increments.

## Measured timing and loss

Times are local container perf-counter wall times, NOT GitHub Actions timings. Character diagnostic sampled 28 development OOV words; exact full-word R25 used 128 natural sample positions from DEV (17 OOV).

| Epoch | Head training seconds | Dev character NLL | Exact original R25 whole-word DEV NLL |
| ---: | ---: | ---: | ---: |
| 0 | — | 15.764059 | **6.988146** |
| 1 | 0.394805 | 15.568550 | 6.988423 |
| 2 | 0.404171 | 15.540289 | 6.989398 |
| 3 | 0.409876 | 15.529831 | 6.990606 |
| 4 | 0.392052 | **15.526927** | 6.991872 |
| 5 | 0.384452 | 15.527885 | 6.993123 |
| 6 | 0.375112 | 15.530985 | 6.994329 |
| 7 | 0.380141 | 15.535314 | 6.995475 |
| 8 | 0.414927 | 15.540351 | 6.996558 |
| 9 | 0.382813 | 15.545784 | 6.997578 |
| 10 | 0.400963 | 15.551415 | 6.998538 |

Sum training wall: **3.939312 s**. Full first experiment: **23.572505 s**, including loading, training, exact fullword DEV/TEST audit, and candidate serialization. Independent fullword per-epoch audit: **20.962410 s**.

The exact 205,073-node trie / known-vocabulary conditional normalization and the original R25 token/OOV mixture were retained.

| State | DEV mean whole-word NLL | DEV PPL | historical TEST mean whole-word NLL | TEST PPL |
| --- | ---: | ---: | ---: | ---: |
| Frozen original 48M | 6.988146 | 1083.711 | 6.059459 | 428.144 |
| DEV-best trained epoch 1 | 6.988423 | 1084.010 | 6.056426 | approx. 426.85 |
| Epoch 10 | 6.998538 | 1095.031 | 6.054045 | 425.832 |

At each epoch, DEV whole-word NLL became worse than the original. The positive historical TEST differences cannot override DEV or authorize promotion. Even epoch 1 failed DEV. This is a **negative full-word validation** despite character-loss improvement.

## Reproducibility and scope

The user's cumulative Round 29 Library ZIP includes scripts train_r29_10epochs.py and audit_r29_epoch_curve.py, the verified Round28 model, original NaNROUTER short-story split, raw logs, two candidate-only R22 count snapshots, per-epoch CSV, JSON report, manifest and SHA-256 checksums. Extract ZIP with its directory layout and run the scripts under Python + NumPy. No source weights were committed to GitHub.

This does **not** train the 48M base model, 128 MiB mirror tensor, or the native NaN16 whole-word gate. No independent held-out generalization or live promotion is claimed.


## Full 260-book corpus extension (after the 40,000-token pilot)

A second and larger experiment scanned **the entire** archived NaNROUTER corpora-short-stories TRAIN split of 260 books (source SHA-256 above). It contained **10,793,992 valid word positions** and **10,302,349 unprotected eligible training word occurrences**. Applying all forward/reverse characters plus EOS yielded **105,552,266 character targets and 211,104,532 two-head count increments per epoch**, or **1,055,522,660 targets and 2,111,045,320 head increments across ten epochs**.

**Timing contract:** R22 heads are additive counts. Training data were read once to accumulate exact sufficient statistics (125.371006 seconds), then those counts were sequentially added to a copied original head table ten times (0.189104 seconds combined). This is mathematically identical to ten corpus passes for these count heads, **not ten literal filesystem rereads**. The entire local experiment including model loading, evaluation and candidate state serialization was 150.332686 seconds.

| Full-corpus epoch | Exact count update seconds | DEV exact whole-word NLL | DEV PPL |
|---:|---:|---:|---:|
| 0 | — | 6.988146387 | 1083.711 |
| 1 | 0.011519 | 6.967179354 | 1061.225 |
| 2 | 0.037391 | 6.967252757 | 1061.303 |
| 3 | 0.011309 | 6.967209222 | 1061.257 |
| 4 | 0.010947 | 6.967163254 | 1061.208 |
| 5 | 0.012638 | 6.967125330 | 1061.168 |
| 6 | 0.033839 | 6.967094942 | 1061.136 |
| 7 | 0.037259 | 6.967070438 | 1061.110 |
| 8 | 0.012218 | 6.967050403 | 1061.088 |
| 9 | 0.011501 | 6.967033777 | 1061.071 |
| 10 | 0.010483 | **6.967019787** | **1061.056** |

With the **same original exact R25 full-word known-vocabulary normalization**, 128 sampled word positions (17 OOV) on DEV improved in mean NLL from 6.988146388 to 6.967019787. However the 128-position historically exposed TEST worsened from 6.059459185 to 6.061260008 (PPL from 428.14 to 428.92). Thus **no candidate promotion**, no independent generalization claim, and no claim of native NaN16 training.

The user's **updated cumulative Round 29 ZIP** in ChatGPT Library includes both local experiments, authentic R28 base/overlay and corpus, the full-corpus script train_r29_full_corpus.py, result report.json, epochs.csv, raw training log, candidate-only NPZs, manifest, and SHA-256 checksums. Source weights/tensor remain frozen.
