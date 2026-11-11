# 256³ hypertensor over the canonical palindromic mirror topology (v1)

Status: **native 128 MiB dual-bank address map, full logical external file
provisioning, and recurrent all-trihead candidate feedback are implemented and
CI-verified**. The persistent NaN16-to-external-arena writer, transactional
promotion, checkpoint-loading into head recurrence, and full-language-model
training are **not yet wired**.

References:
- Native guest: `mth/nan16/mth_hypertensor256_mirror_arena_map.nas`
- Full dual-bank resolver: `mth/nan16/mth_hypertensor256_mirror_dual_map.nas`
- Native recurrent trihead feedback: `mth/nan16/mth_trihead_meta_feedback_f32.nas`
- Full storage initializer: `scripts/init_full128_mirror_tensor_storage.py`
- Feedback native regression: `mth/tests/mth_trihead_meta_feedback_native_test.nas`
- Guest regression: `mth/tests/mth_hypertensor256_mirror_arena_native_test.nas`
- CI: `.github/workflows/nan16-native-hypertensor256-mirror-arena.yml`
- Canonical 8 MiB root contract: `docs/MIRROR_MEMORY_LAYOUT.md`
- Trained **feature tensor** (not physical head axes):
  `docs/MTH_NATIVE_INVERSE_TRIGRAM_TRAINING_V1.md`

## 1. Exact dense memory cost

For an arbitrary three-axis 256×256×256 tensor, there are **16,777,216
independent scalar positions**, including positions with a semantic void index
that must never be trained.

| Scalar encoding | Bytes | MiB |
| --- | ---: | ---: |
| bitset (1 bit/cell) | 2,097,152 | 2 |
| int8/quantized | 16,777,216 | 16 |
| binary16/bfloat16 | 33,554,432 | 32 |
| binary32 | 67,108,864 | 64 |
| binary64 | 134,217,728 | 128 |

The canonical 8 MiB root is **fully occupied** by 256 head records of 128
bytes and 32,640 unordered-pair records of 256 bytes. There is no spare
persistent space in that root; tensor parameters MUST use a separately
admitted arena or a new versioned storage profile. Do not overwrite,
reinterpret, or resize the canonical root for this tensor.

A 128 MiB **dual-bank external tensor file** can now be provisioned and
SHA-256-verified through the included *storage-only* initializer. Each complete
64 MiB bank has eight 8 MiB logical segments of 32 head-banks each, at
256 KiB/bank. They are **external tensor banks**, not 16 new NaN universes or
roots. They may be sparsely allocated by the filesystem without changing the
independent dense logical address capacity. The same NaN root remains the
authority for admission and writes. A guest-driven persistent arena writer and
transactional bank promotion are still required.

Training increases working memory: weight-only online SGD can use one 64 MiB
tensor plus scratch; dense binary32 gradients add another 64 MiB; Adam with
two dense moment arrays uses **192 MiB** for weights and moments alone.

## 2. Canonical addressing without losing directional information

Let `h` select the first axis and `a,b` select the mirror plane.

There are **256 diagonal fixed-point cells** and **32,640 unordered pairs**
per plane. Each unordered pair has two independent directed f32 values,
one for `a→b` and one for `b→a`. A fixed point needs only one value:

```
head_bank_size   = 256 * 256 * 4 = 262,144 B
bank_base        = h * 262,144
diag_size        = 256 * 4 = 1,024 B

if a == b:
    canonical_cell = a
    direction      = 0
    byte_offset    = bank_base + 4*a
else:
    lo,hi          = min(a,b), max(a,b)
    pair_ordinal   = lo*(511-lo)/2 + (hi-lo-1)   # 0..32639
    canonical_cell = 256 + pair_ordinal
    direction      = 0 if a < b else 1
    byte_offset    = bank_base + 1,024 + 8*pair_ordinal + 4*direction
```

This is **not mathematical compression** of a general tensor. It replaces
two separate pair identities by one canonical identity containing two
independently addressable words. The scalar count remains 65,536 per plane.

The canonical root's v1 **mirror residual** invariant is
`lane1.residual[j] = -lane0.residual[j]`. That invariant does **not** imply
that a freely trained inverse-hypertensor must have antisymmetric weights:
`T[h,a,b]` and `T[h,b,a]` can both be independent values. External tensor
lanes must therefore not be silently stored as canonical root residuals.

## 3. Semantic void protection and physical identity

The physical topology still has 256 points, but **semantic head 255 is
reserved zero/void**. Native address resolution rejects **any** requested
coordinate equal to 255 (and all out-of-range coordinates) before giving an
address. It does not alias 255 to 254. Head zero continues to obey the
existing NANNET/control permissions. Those permissions are not weakened by
the new mapper.

For simple power-of-two banks the storage layout retains the 256th
bank, and the per-bank 256th diagonal/off-diagonal slots are *physically
reserved*, not trainable. If packed densely without reserved slots, 255³
learnable float32 cells would occupy 66,325,500 B (~63.253 MiB); that
packing requires a distinct address ABI and cannot be inferred from this map.

The existing trained 26³ Gutenberg tensor has **character feature indices**,
not these 256 physical head IDs. Integrating it requires an explicit
feature→head projection and a learned or frozen routing policy; simply
embedding its 26³ weights at head addresses 0..25 would conflate different
semantic spaces.

## 4. Optional parameter reduction: measure, do not assume

| Constraint | Independent positions | float32 MiB | Tradeoff |
| --- | ---: | ---: | --- |
| Unconstrained, directed | 16,777,216 | 64 | Preserves arbitrary forward/inverse weights |
| Pair-symmetric for every h, `T[h,a,b]=T[h,b,a]` | 8,421,376 | 32.125 | Removes directional distinction |
| Symmetric under all three permutations | 2,829,056 | ~10.792 | Removes ordering information |
| TT rank 16 (three 256-wide cores) | 73,728 | 0.28125 | Approximation; effective rank must be tested |
| TT rank 32 (three 256-wide cores) | 278,528 | 1.0625 | Approximation; more operations per lookup |

TT counts assume ranks `(1,r,r,1)`, a real-valued rank-3 tensor, no extra
optimizer states or routing metadata. These factorizations do not produce
free information capacity: benchmark actual forward/inverse held-out accuracy
and probability calibration versus the dense native tensor. A low-rank
factorized **trainable representation** is preferable to assuming tensor
symmetry where directional inverse learning matters.

## 5. Verified native scope and next integration

The address mapper returns the canonical mirror identity, orientation, and
64 MiB-relative byte offset. Regression tests cover known exact addresses,
semantic void rejection, all **32,385** unordered pairs among live indices
0..254 (both directions), and relative address consistency. The fixture
uses guest NaN16 integer arithmetic rather than host-side implementation.

This does NOT assert that 64 MiB can be directly addressed with the existing
8 MiB root's LDB/STW primitives. A versioned external arena paging and I/O
ABI is necessary before physical data access.

The next meaningful training boundary is to admit the existing SHA-verified
26³ checkpoint, test a feature→head embedding in a shadow arena, route
trained signals through the existing global attention, and compare the
**frozen full language decoder** against a zero-gated control on locked,
fresh held-out books. No published result yet supports a 43M decoder
perplexity gain from the new 256³ address geometry.


## 6. Implemented 128 MiB active/candidate and meta feedback (native)

Both tensor banks are **full**, containing all (256^3 = 16,777,216)
independent f32 coordinates. Bank 0 (active) is bytes
`[0,67,108,864)`; bank 1 (candidate) is
`[67,108,864,134,217,728)`. One mirror pair stores two directed f32
words, not an imposed negative/equal pair. The canonical *8 MiB root*
remains unchanged.

Native trihead feedback accepts a proposal
`[proposer, h, a, b, delta, trusted_tile_slot]`. Every authorized
proposer **0 through 254** can propose an update to **any** valid tensor
coordinate; there is no plane ownership restriction. Only the trusted
meta tile owns the current value, feedback target, relative mirror byte
offset and epoch. A proposer cannot supply their own favorable feedback.

For proposer (p), persistent native meta-credit (c_p\in[0,1]),
and proposed delta (d):

```text
effective_delta = d * (0.25 + 0.75 * credit[p])
old_loss = (weight - trusted_target)^2
new_loss = (weight + effective_delta - trusted_target)^2
accepted = new_loss < old_loss
if accepted: candidate_tile.weight += effective_delta
credit[p] += 0.125 * (float(accepted) - credit[p])
```

This is a real *bounded native feedback loop*. All authorized heads retain
a minimum update multiplier of 0.25 even if their meta-credit approaches
zero. Rejection decreases future proposal influence; success increases it.
Every submitted candidate must also pass permissions, head/coordinate
range, strict void-255 exclusion, trusted tile-offset matching, epoch
freshness and finite/bounded-value checks. Malformed batches fail before
any candidate-tile or trust mutation.

The trusted feedback objective in the current kernel is **scalar squared
error on a native tile**, not language-model perplexity, and this gate is
not itself a fully learned autonomous meta-objective. We can replace the
trusted target with genuinely held-out next-token feedback when the
full decoder's native evaluation adapter is connected.

CI evidence:
- [All 255 proposers + meta-credit learning native pass](https://github.com/shemshallah/NaNROUTER/actions/runs/42957115646)
- [Both full 64 MiB banks, native map, physical file provisioning](https://github.com/shemshallah/NaNROUTER/actions/runs/42956642489)

**Current trust boundary:** the test kernel modifies *guest-owned shadow
candidate tiles*. It does not yet apply approved sparse deltas to the
persistent 128 MiB file, and it does not promote candidate bank 1 to
active bank 0. Those operations require a versioned native journal,
authoritative root admission and atomic checkpoint promotion, before
end-to-end persistent self-modification can be claimed.
