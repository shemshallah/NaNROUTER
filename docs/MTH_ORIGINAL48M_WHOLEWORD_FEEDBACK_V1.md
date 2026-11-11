# Original frozen 48M hybrid → native NaN16 whole-word feedback

Status (2026-11-10 PST): **Real source-model integration and candidate-only storage verified. No active promotion and no independently replicated perplexity improvement.**

## Concrete source continuity

The original R27 research archive was recovered from the user's Library, with
the 43M base checkpoint + R22 5M overlay, exactly **48,000,000 events**.
The full original 69,974-type known spelling vocabulary, its 205,073-node trie,
and original R25 decoder settings (alpha=4, gamma=0.4, eta=0.75, pair=0.1)
were retained. Checkpoint SHA-256:

- Base: `299a91daf65c8e66fe3489940371d262afef18dd2ef6fef61947ac14c62bb717`
- Overlay: `62bf1e5defbb8224d795db16a8e6959cc9aa3d7fed8a63346c4cee205a1bea04`

The Python bridge `scripts/mirror_word_feedback_v28.py` subclasses the
original R25 `PairTrie` rather than creating or training a new language model.
It reads a verified native-approved float32 candidate from the full 128 MiB
tensor candidate bank. The original checkpoint and active tensor remain frozen.

## Exact whole-word normalization

For native tensor coordinate `T[19,7,4]` (the local character context
`th` and next-character `e`), add `theta=-0.125` to the `e` logit
every time the original decoder sees the same causal character context.

The probability of every character, including EOS, is re-normalized.
The exact trie DP re-weights **every** known spelling including its EOS,
yielding the exact new known-vocabulary mass. A proposed OOV spelling is
then normalized by `1 - known_vocab_mass(theta)`.
Original exact **known-word token probabilities and total UNK mass remain
unchanged**. The full R25 token/spelling mixture is retained.
This is not a character-only CE proxy.

## Genuine 48M model through native guest

128 sampled genuine whole-word probability pairs were exported from the
frozen original model on each of historical dev/test. Their immutable SHA
are pinned in
`tests/fixtures/r28_frozen48m_wholeword_pairs.b64` and re-checked in CI.

| Split | Native original sum -ln P(word) | Native candidate sum -ln P(word) | Gate |
| --- | ---: | ---: | --- |
| Historical development, 128 tokens | 857.234 | 857.217 | Accepted |
| Historical test, 128 tokens | 772.133 | 772.134 | Read-only, slight regression |

The actual native NaN16 kernel
`mth/nan16/mth_trihead_wholeword_nll_feedback_f32.nas` computes
`-ln P(word)` for the *original frozen whole-word probability* vs
the tilted decoder's *true whole-word probability* using existing
native `mth_log256_scalar`. The host supplies immutable f32 true-word
inference readouts; it never selects updates, computes the training
loss, modifies the checkpoint, or acts as an optimizer.

**Native real model CI:** https://github.com/shemshallah/NaNROUTER/actions/runs/42966575280

The native guest emitted:
`MTH_WHOLEWORD_ACCEPTED_HEX 00000001 00000013 00000007 00000004 004C23C4 BE000000`

The strict CI-only transport accepted this only after pinned source
trace SHA checks, native PASS and dev NLL improvement. It wrote the raw
float32 `0xBE000000` at byte **72,098,756** in candidate bank1 of the
**complete 128 MiB** dual f32 256³ mirror arena. The active bank and
original 8MiB root were unchanged; the arena's resulting SHA-256 was
`f0363446a552ef238185197917683280d6a4200a527cd5b5460ee8fc20cccf1e`.

**Verified native candidate-only transport:** https://github.com/shemshallah/NaNROUTER/actions/runs/42967247980

The native control CI independently checks accept and reject paths,
and verifies that held-out loss cannot alter credit or weights:
https://github.com/shemshallah/NaNROUTER/actions/runs/42966575415

## Diagnostic source-disjoint books (already examined in R27)

A separate local original R25 model evaluation compared a **fixed**
theta = -0.125 candidate on 250 historical dev tokens, and 450 tokens
in each of four previously screened Gutenberg books. Mean whole-word
NLL differences (candidate minus original, nats/word) were:

| Source | Δ NLL |
|---|---:|
| Historical development | -0.000313999 |
| Gutenberg PG35 | -0.000216118 |
| Gutenberg PG120 | -0.000232127 |
| Gutenberg PG158 | **+0.000012768** |
| Gutenberg PG219 | -0.000111923 |

One book regressed. More importantly, these texts were *already consulted*
in earlier analyses and may not be called an untouched independent validation.
The originally considered positive theta (+0.125) worsened dev and two
screened books; it was rejected and never promoted.

## Boundaries, security, next criteria

This completes the engineering path from **original 48M decoder →
whole-word probabilities with exact lexical normalization →
native NaN16 NLL/meta gate → six-word native journal → full 128MiB
candidate bank → read-only candidate decoder**.

This is **not** equivalent to demonstrated full next-word perplexity
generalization or deployed autonomous self-modification:

- The original model's trained state was **not** updated, and no tensor
  candidate was promoted to the live active bank. This is intentional
  because held-out regression was observed.
- The CI journal is currently an unsigned log from a pinned runner. Do
  not accept arbitrary network-supplied logs as production authority.
- Before a legitimate active promotion, run full unconsulted books,
  multiple head coordinates, trials/seeds and both matched controls.
  Require no meaningful regressions and an independent improvement.
- Construct authenticated, crash-safe candidate admission and active
  promotion/rollback before using the tensor in a production service.

The user's original cumulative Round 27 archive plus Round 28 scripts,
traces, logs, evidence and claims were packaged separately as a new
cumulative Round 28 archive; no original checkpoint was committed to GitHub.
