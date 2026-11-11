# 256³ hypertensor over the canonical palindromic mirror topology (v1)

Status: **native address mapper implemented and verified**, but the external
64 MiB tensor arena, transactional runtime writer, parameter-loading bridge,
and full 43M decoder training are **not** implemented by this document.

References:
- Native guest: `mth/nan16/mth_hypertensor256_mirror_arena_map.nas`
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

The native map uses eight 8 MiB **external storage segments** of 32 head-banks
each, 256 KiB/bank. This is **logical external tensor storage**, not eight new
NaN universes or eight roots. The same root remains the only authority for
admission and writes. An external arena backing controller is still needed.

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
