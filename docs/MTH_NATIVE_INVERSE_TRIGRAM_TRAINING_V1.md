# Native NaN16 inverse character training: matched pair vs rank-three hypertensor

Status: **implemented, real Gutenberg corpus training executed, native VM checked**, reproducible preliminary experimental result. The hybrid 43M language decoder and canonical 8 MiB root were not altered.

## Architecture, addressing and scope

- There are 256 physical NaN16 fixed points. Semantic/mathematical index **255 is reserved zero/void**, with 0..254 eligible for mathematical participation **subject to existing native NANNET/BSR authorizations**. The old head-0 root/control reservation is not a migration target.
- The experiment's learned `26x26x26` tensor is an **ephemeral feature association tensor** tied to streamed one-hot character triples; its tensor coordinates are **NOT physical head numbers**, and the 17,576 tensor entries do not replace the `C(256,2)` pair topology.
- The tensor is updated by **NaN16 guest arithmetic**, not a Python/JS/C++ optimizer. The intake script only selects and encodes public-domain corpus triples and splits by whole Gutenberg documents.
- Native global 16-candidate softmax and native gated residual consume trained tensor score/feature windows and feed the next-step head buffer; this does not train the complete hypertensor-simplicial-sheaf/256-head pipeline or the frozen 43M decoder. MC0 real meta remains deferred.

## Exact inverse and forward objective

For streamed alphabetic character triple `(a,b,c)` with symbols `0..25`, a single learned third-order tensor `T[a,b,c]` provides:

- **Forward**: `P(c|a,b)=softmax_k(T[a,b,k])`, target `c`
- **Inverse**: `P(a|b,c)=softmax_k(T[k,b,c])`, target `a`

Every native stochastic-gradient step uses `T[index] -= lr*(P(k)-1[k=target])` with `lr=0.1`. The same tensor is shared by forward and inverse; it is **not a second inverse-only model**. The guest computes stable 26-class softmax via the existing 256-class NaN16 kernel with the other 230 logits masked to `-inf`, exact top-1 hit counts and average target probabilities.

The paired **one-context** control uses the same sampled triples, ordered examples, epochs, target classes and documents, but only one neighboring character and a single learned `26x26` relation operator `W`:

- Forward baseline: `P(c|b)=softmax_k(W[b,k])`
- Inverse baseline: `P(a|b)=softmax_k(W[k,b])`

This isolates the effect of using a longer context **under these unmatched parameter budgets**, rather than confounding the comparison with different sampled positions. T has 17,576 values; W has 676 (26x fewer parameters for the control). The comparison is neither parameter-matched nor compute-matched; it does not establish hyperbolic/Hodge geometry advantage.

## Real corpus and training protocol

- Source: `shemshallah/NaNROUTER/corpora/sentences` GitHub Release `corpora-sentences-0001`, Project Gutenberg public-domain sentence extracts; release SHA256 checked by the workflow.
- Document split: **20 train / 6 development / 6 held-out test** distinct Gutenberg books; exact-duplicate content rejected, partition keyed to stable source identifiers. This is *the same document split family as the 26-letter adjacent-pair pilot*, so do not call it an entirely new untouched test corpus.
- Samples: **3,840 training examples per epoch**, split equally forward/inverse; **768 dev**, **768 test** (384 inverse, 384 forward) from naturally sampled contiguous word-internal character triples, fixed deterministic reservoir sampling. No dev/test SGD.
- Training: **8 epochs**, i.e. **30,720 directed native sample updates**, single tied tensor or single tied pair operator per arm.
- Host intake and exports handle corpus validation, sampling, manifest/provenance and bit-exact checkpoint decoding only. All model logits, probabilities and updates are NaN16 guest calculations.

## Matched experimental results

| Held-out or dev metric | 26x26 pair control | 26x26x26 trigram hypertensor |
| --- | ---: | ---: |
| TEST inverse correct / 384 | 86 (22.40%) | **110 (28.65%)** |
| TEST forward correct / 384 | 92 (23.96%) | **125 (32.55%)** |
| TEST combined correct / 768 | 178 (23.18%) | **235 (30.60%)** |
| TEST mean target probability, native truncated per-mille | 136 | **186** |
| DEV correct / 768 | 182 (23.70%) | **222 (28.91%)** |
| Native guest steps | 453,128,369 | 467,609,286 |

Thus the third-order model achieves **+24/384 (=6.25 percentage points)** on inverse-only, **+33/384 (=8.59 points)** on forward-only, and **+57/768 (=7.42 points)** on total correct character classes on the exact same test sample positions. This is *not* full-word accuracy or the 43M model's cross-entropy.

### Public verification

- Native trigram training (first verification): [GitHub Actions #42950199141](https://github.com/shemshallah/NaNROUTER/actions/runs/42950199141)
- Native **matched-position pair control**: [GitHub Actions #42950538105](https://github.com/shemshallah/NaNROUTER/actions/runs/42950538105)
- Native trigram **checkpoint export verified**: [GitHub Actions #42950787457](https://github.com/shemshallah/NaNROUTER/actions/runs/42950787457)
- Eight-pass 26x26 prior adjacent-pair pilot (**different sample positions**): [GitHub Actions #42949555937](https://github.com/shemshallah/NaNROUTER/actions/runs/42949555937)

### Exact trained checkpoint

The native trigram guest serializes each learned float32 bit pattern in low-nibble-first hexadecimal; the host only verifies and losslessly decodes 17,576 words into a **70,304-byte** tensor.

- Artifact `nan16-26cubed-inverse-trigram-results` on [run #42950787457](https://github.com/shemshallah/NaNROUTER/actions/runs/42950787457) includes `inverse_trigram26.tensor.f32le.bin`, a JSON checkpoint manifest, raw guest hex, `SHA256SUMS`, corpus split manifests and log.
- Verified SHA-256 **`c43ab50b88da8b6fb3d1bb7a060a40a73ebeb95cea3494b1ee53c246e7881afa`**.
- The checkpoint is a real **trained tensor adapter snapshot**, but the live 8 MiB root and the existing 43M hybrid weights are unchanged. Future continuation must explicitly import this tensor state via a versioned, validated native guest loader; it is **not automatically loaded by the training workflow or NANNET**.

## Status / next experiment

The matched held-out improvement is real within this fixed corpus split and native experimental setup. It is still exploratory; the test documents have been consulted during adjacent-pair and trigram pilot rounds. Do not promote to a publishable superiority claim without a *fresh*, locked corpus, multiple training seeds and matched parameter/compute controls.

The next essential work is training the actual 255-participant head→streamed-hypertensor→simplicial→global recurrence against next-token loss, including prefix/suffix and word-completion tasks, with exact zero-gate 43M regression protection. The 26^3 tensor alone is only a local character-context training seam. True meta will be implemented separately in Overbootstrap MC0.
