# NaN16 inverse corpus training + 255 active semantic heads / void-255 boundary

## Verified state (2026-11-10)

The physical NaN16 topology remains **256 canonical fixed points** and
**32,640 unordered mirror pairs**. For the *new hypertensor/simplicial/global
mathematical layer*, **head ID 255 is zero/void and not a trainable head**.
Active mathematical head IDs are **0..254 (255 positions)**, *subject to*
existing read/write permissions. In particular, existing `HW0:0` /
NANNET root and internal BSR control roles remain valid and protected; the
new void convention does not silently migrate permissions, reinterpret the
topological point-0 root, or grant writing privileges. The void-255
restriction is an additional **mathematical participation rule**, not a
replacement for `runner_riddle/head_role_contract.py`.

New global Hodge NaN16 kernel `mth_global_hodge256_f32.nas` preserves
all physical addresses but **rejects nonzero edge-flow values incident on
head 255** and **rejects all admitted triangle faces containing 255**,
without publishing partial outputs. All 0..254 mathematical vertices
remain eligible for observed hot/cold/partial trihead analysis once
existing control-plane authorization checks pass.

The canonical native math workflow
[run #42947826455](https://github.com/shemshallah/NaNROUTER/actions/runs/42947826455)
passed all **9/9 mathematical integration fixtures**, including explicit
void-edge and void-simplex rejection. The expanded global Hodge fixture
took 2,732,150 NaN16 guest steps; the combined nine fixtures took
**3,585,064 NaN16 guest steps**.

## Public-domain intake

The corpus text comes from this repository's own
`corpora/sentences/` release family; large payloads are *release assets*,
not checked-in text. The GitHub runner downloads
`corpora-sentences-0001/sentences-0001.tar.zst`, verifies the release
SHA-256 checksum, and extracts text.

`scripts/build_native_inverse_corpus_fixture.py` implements ONLY
corpus intake, UTF-8 validation, exact-duplicate removal, stable
document-level partitioning, bounded natural-frequency sampling of
adjacent *word-internal alphabetic letters*, and transcription into a
NaN16 `.nas` guest fixture. It never performs an ML weight update or
computes logits, softmax, loss gradients or learned metrics. Each
letter maps into 16 bins using `(ord(lowercase_ascii_letter)-97)%16`.
This is a **lossy 16-feature learning experiment**—not full byte modeling,
a whole-word model, language comprehension or next-token perplexity.

Stable splits:

| Set | Distinct Gutenberg documents | Directed examples |
| --- | ---: | ---: |
| Training | 12 | 3,072 |
| Development | 4 | 512 |
| Held-out test | 4 | 512 |

Each naturally sampled letter adjacency contributes one forward
`(left → right)` and one exact inverse `(right → left)` training record.
The same **single 16×16 relationship descriptor `W`** is shared in both
directions. No second inverse-only model is created; `W` is not a matrix
formed from streaming vector features. Its 256 entries are distinct from
the **physical head index 255**, which remains reserved void.

The kernel `mth_inverse_dual_batch16_f32.nas` executes actual native
cross-entropy SGD through the existing stable softmax kernel for **two
passes** of the training examples, learning rate `0.1`, with no
development/test weight updates. Forward logit is `W[left,k]`; inverse
logit is `W[k,right]`. Native `softmax` creates the class probabilities,
and native `W -= learning_rate*(P - one_hot(target))` updates parameters.
It records exact test top-1 hit counts and the mean target probability
as a parts-per-thousand score.

The trained operator is then read through **the existing native global
16-candidate masked attention kernel** in both row and column
orientations, and is gated into a **next-step head buffer** by the native
memory-conditioning residual. The 43M hybrid remains frozen; no root
writes, checkpoint replacement, or MC0/Overbootstrap meta changes.

## Measured actual outcome

The first independent training run:
[GitHub Actions #42947406971](https://github.com/shemshallah/NaNROUTER/actions/runs/42947406971).

The repeated run with the integrated global-attention/head bridge:
[GitHub Actions #42947839695](https://github.com/shemshallah/NaNROUTER/actions/runs/42947839695).

| Held-out measure | Before any updates | After 2 passes |
| --- | ---: | ---: |
| Correct top-1 classes / 512 | 41 | 116 |
| Top-1 class accuracy | 8.01% | 22.66% |
| Mean correct-class probability, native per-mille (truncated) | 62 | 137 |

Independent development after training: **129/512 correct**, target
probability **150 per mille**. The integrated run produced
**95,752,329 actual NaN16 guest steps** and the log marker
`MTH INVERSE GLOBAL HEAD BRIDGE PASS`. The generated native program
and the corpus document manifest/checksums are emitted in CI; the
workflow uploads the compact provenance, not the hundreds-of-megabytes
corpus or a rewritten model.

This is **measured native learning on real public-domain text** with
disjoint held-out documents. It is **not** a test of 43M
language cross-entropy, full token-level accuracy, a learned Poincaré
hyperbolic embedding, all-255-head recurrent convergence, or competitive
performance against a Transformer. In particular, the 16-category
inverse experiment has substantial category collisions.

## Next integration gates

1. Versioned active-head 0..254 read/write routing with existing NANNET
   permissions; persist only admitted reversible snapshots, keep 255 void.
2. Train inverse reconstruction loss through the actual streamed
   third-order hypertensor, signed simplicial incidence and global sheaf
   projection, rather than only the compact 16-bin adapter.
3. Route loss gradients through full native global attention to the
   protected 43M readout and use independently held-out original words,
   prefixes/suffixes and next-token loss for realistic quality evaluation.
4. Repeat on independent sentence/paragraph/short-story release batches
   with strict Gutenberg-ID deduplication, no overlap between train/dev/test,
   and explicit gradient/rollback provenance. Real META remains
   deferred to **Overbootstrap MC0**.

Do not represent this training adapter as a replacement model.
