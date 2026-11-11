# Native NaN16 real-decoder loss integration (v1)

**Status (2026-11-11):** A genuine frozen HW0 unified decoder's causal
next-byte logits now feed a native NaN16 *full softmax cross-entropy* meta
feedback gate. The guest chooses candidate deltas using development
loss ONLY, then performs a separate, read-only held-out audit. An approved
native float32 word can be written by a strictly transport-only adapter into
the full **128 MiB external palindromic-mirror tensor candidate bank**. The
authoritative 8 MiB root and 64 MiB active tensor remain unchanged.

The follow-on 48M R25 hybrid's **28-symbol contextual spelling channel** has
a source adapter and native mask/fixture tests. Do not conflate this with a
verified improvement in the 48M hybrid's **whole-word** perplexity: that full
decoder integration is NOT complete.

## Source and files

- Guest CE engine: `mth/nan16/mth_lm_cross_entropy256_f32.nas`
- Guest candidate meta gate: `mth/nan16/mth_trihead_decoder_ce_feedback_f32.nas`
- Direction-preserving address geometry:
  `mth/nan16/mth_hypertensor256_mirror_arena_map.nas`
- Frozen real HW0 decoder trace:
  `tools/export_unified_decoder_nextbyte_logits.cpp`
- 6+6 distinct book bridge:
  `scripts/export_disjoint_gutenberg_decoder_traces.py`
- Both decoder trace families into one native fixture:
  `scripts/build_native_decoder_ce_fixture.py`
- Original frozen 48M R25 spelling-head adapter:
  `scripts/export_frozen_48m_hybrid_char_trace.py`
- CI-only journal replay:
  `scripts/apply_native_decoder_ce_journal_transport.py`
- Full tensor backing:
  `scripts/init_full128_mirror_tensor_storage.py`
- Production CI:
  `.github/workflows/nan16-native-real-decoder-ce-feedback.yml`
- Native masked alphabet tests:
  `.github/workflows/nan16-native-decoder-ce-masked.yml`

All actual candidate scoring and acceptance are executed by the NaN16 guest,
not by Python, C++ or JS. Source trace exporters calculate original frozen
model probabilities and serialize their logs; **they do not train the model**
or decide whether the tensor is beneficial.

## Original full tensor geometry (not compressed)

A complete rank-three tensor has 256³ = **16,777,216 float32 values**, or
64 MiB. The production experiment provisions TWO full tensors: active
(64 MiB) plus candidate (64 MiB) = **128 MiB**. For each head axis h,
the (a,b) plane is 256 diagonal palindromic fixed points plus 32,640
canonical unordered mirror pairs. Each pair has TWO independent f32
orientations, so (T[h,a,b]) and (T[h,b,a]) can differ. The two directions
are not forced equal or negative, and no signal is lost to a symmetric
compression assumption.

Semantic coordinate 255 remains void on all three axes, although physical
address capacity remains a full 256³. All eligible authorized triheads
0..254 may propose updates at any valid coordinate (not just their own
head plane). No untrusted head is granted an active-bank write. A trusted
feedback gate owns its candidate tile, current weight and epoch.

## Full real HW0 loss path

For a fixed two-byte prefix (e.g. raw bytes t=116 and h=104), the frozen
real model produces causal 255-way next-byte logits, with reserved byte255
exactly negative infinity. The candidate tensor value (T[116,104,101])
adds a logit residual to the class for the byte e=101. Before a proposed
change, the guest computes the full matched *development* cross-entropy
with the CURRENT candidate weight (not a zero-weight surrogate). It then
recomputes full softmax loss after the proposed change on those SAME rows.

Development moves use six precommitted signed deltas
`(+0.5,-0.25,+0.125,-0.0625,+0.03125,-0.015625)`, modulated by per-head
native EMA meta-credit, with a positive nonzero minimum influence.
Strictly lower aggregate native dev loss admits the new candidate value.
An independent read-only held-out evaluation follows; its labels do not
change any weight or credit.

The frozen HW0 root is SHA-pinned and preserved throughout. The approved
candidate weight is emitted in exact hexadecimal form by the guest;
transport verifies the canonical directed mirror address and writes the
unaltered raw float32 bits into only the external candidate bank. CI verifies
the updated 128 MiB file SHA-256 and checks that the active bank and original
root were not modified. This transport is not a host-language optimizer.

### Verified source-disjoint Gutenberg pilot

Gutenberg `corpora-sentences-0001` was SHA-256 verified before extracting
books. The existing deterministic native-inverse document split selects
6 development books and 6 held-out test books, all distinct from the local
frozen HW0 decoder's training fixture. Four causal 'th' contexts were read
from each book, giving 24 dev and 24 test examples. This is a strictly
**context-specific pilot**, not overall decoder CE or full text perplexity.

| CE (nats/byte; truncated native millinats) | frozen | dev-selected candidate |
|---|---:|---:|
| 6-book development, 24 positions | 2.175 | 2.105 |
| 6-book test, 24 positions | 2.090 | 2.020 |

Three of six native development moves were accepted. The final candidate
value for T[116,104,101] is f32 `0xBE94F074`. Its canonical 64 MiB
relative address is `0x01D28B1C`, and its 128 MiB candidate-bank absolute
byte offset is 97,684,252. Source-root SHA-256 is
`59d42b16a3491d0fa8263d8be13c7002cc3d22faa12fd7b8fcc17592d3e16455`.
No active-bank promotion took place.

Positive CI: https://github.com/shemshallah/NaNROUTER/actions/runs/42960909656

**Negative control matters:** An earlier much smaller synthetic-fixture
development split had 12 'th' examples and 18 held-out examples. A
dev-selected adjustment improved development loss, yet made held-out loss
worse (1.231 -> 1.298). This was not hidden or promoted. The 6-book pilot
corrected the source/evaluation setup, but with only 24 context positions
per split its positive signal is still preliminary. Repeat on additional
fresh books and multiple independent head/prefix features before claiming
generalization.

## Original 48M hybrid spelling-head boundary

The user's original frozen R26 research archive contains the unchanged
43M core checkpoint plus 5M R22 contextual-character observations,
for **48,000,000 training events**. The exact base SHA-256 is
`299a91daf65c8e66fe3489940371d262afef18dd2ef6fef61947ac14c62bb717`
and the overlay SHA-256 is
`62bf1e5defbb8224d795db16a8e6959cc9aa3d7fed8a63346c4cee205a1bea04`.

The original R25 selected `alpha=4`, `gamma=0.4` and
`pair_weight=0.1`, and keeps its exact 69,974-word explicit lexicon
and 205,073-node known-spelling trie. The source adapter imports the
original `DirectChar.step()` from this frozen research archive. It does
not invent a new character model or alter the trained state.

Crucial alphabet mapping:

- HW0 raw-byte residual for the sequence 'the':
  `T[116,104,101]` and class 101 among 255 byte classes.
- Frozen 48M character spelling residual for 'the':
  `T[19,7,4]` and class 4 among **28** character/EOS classes.
- `a..z` are classes 0..25, apostrophe=26, EOS=27, all
  unsupported class slots 28..255 are exact `-infinity`.
  Raw NaN16 semantic head 255 stays void.

The native 256-way logsumexp/CE kernel already accepts exact negative
infinity masks. Its new meta gate explicitly refuses nonfinite true
targets and accepts `-infinity` only as a class mask. Native regression:
https://github.com/shemshallah/NaNROUTER/actions/runs/42962093561

The 48M archived model was loaded locally with exact checkpoint SHA checks.
The resulting original `DirectChar.step('th',(1,1),...)` distribution
normalized to 1.0; its contextual count table had shape
`(2,1024,784,28)`. A separate read-only reservoir extraction found
145,632 naturally occurring 'th' prefixes in the historical development
file and 235,976 in the historical test file. 24 sample logit rows from
each split were exported, with no checkpoint changes. The **actual 48M
trace has not yet been scored by a native VM**; that qualification must
be carried to future continuations.

### Reproduce the exact 48M masked trace (offline)

Use a local copy of the ORIGINAL R26 archive, extracted so that
`experiment_archive/` contains the documented checkpoint filenames:

```sh
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
python3 scripts/export_frozen_48m_hybrid_char_trace.py \
  --archive-root /path/to/experiment_archive \
  --dev /path/to/experiment_archive/data/nanrouter_shortstories_new/dev.txt \
  --test /path/to/experiment_archive/data/nanrouter_shortstories_new/test.txt \
  --output-dir build/48m-traces \
  --manifest build/48m-traces/manifest.json \
  --prefix th --residual-class e --samples 24
python3 scripts/build_native_decoder_ce_fixture.py \
  --model-kind r25-48m-char --h 19 --a 7 --b 4 \
  --dev build/48m-traces/dev.trace \
  --test build/48m-traces/test.trace \
  --output mth/tests/mth_48m_char_generated.nas \
  --manifest build/48m-traces/native-manifest.json
awk -f nan0s/tools/nmk.awk -v CMD=emit \
  mth/tests/mth_48m_char_generated.nas > build/48m-traces/model.nan
nan0s/aarch64/android/nan_cli \
  --img build/48m-traces/model.nan --steps 200000000 --serial
```

This example uses **previously exposed historical heldouts** and should
only be treated as a functional integration test, NOT an independent
publishable 48M result. The archive remains under user control; no 110 MB
checkpoint is committed or uploaded to the public repository by this
integration.

## Remaining performance and publication gates

1. Native-evaluate the ORIGINAL 48M masked traces and verify the sample
   hashes/metadata and exact unchanged checkpoints.
2. Extend from conditional character CE to full **whole-word** NLL. This
   requires applying the candidate residual at each relevant character and
   EOS step AND recomputing the exact complement of the 69,974 known
   spellings through the frozen trie, without touching known token priors.
3. Use untouched entire new books, multiple contexts and seed repetitions.
   Compare against a parameter-matched control and check held-out regressions.
4. Implement authenticated persistent journal admission plus atomic
   candidate-to-active promotion/rollback. Until then the live decoder is
   never changed by meta-feedback.

The full 43M/48M hybrid's perplexity has **not** been demonstrated to
improve because of this new mirror tensor. No general fluency or
self-modifying live decoder claim is established by the current evidence.
