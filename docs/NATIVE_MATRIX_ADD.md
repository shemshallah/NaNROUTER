# Native float32 matrix addition (256×256)

Status: source-written and locally executed with the canonical NaN0S toolchain
(`nan0s/tools/nmk.awk` and `nan0s/aarch64/android/nan_cli`) on 2026-11-07.
This is local native evidence only, **not a CI claim**. The two sources are not
registered in any manifest, spec, fixture list, or test harness by this change.

## 1. Scope

`mth/nan16/mth_matrix_add256_f32.nas` computes the dense elementwise sum of two
row-major 256×256 float32 matrices:

```
C[k] = A[k] + B[k]        for k = 0..65,535
```

The linear index `k` maps to row `k >> 8` and column `k & 255`. All three
matrices are 65,536 NaN16 words. Each float32 value is one IEEE binary32 bit
pattern stored in the 32-bit payload of one NaN16 word. The kernel executes only
NaN16 instructions: two `LD`s, one `FADD`, and one `ST` per element, in strictly
increasing `k` order. No host math, allocation, hidden conversion, fused
multiply-add, or reassociation is used.

The fixture is `mth/tests/mth_matrix_add256_f32_test.nas`.

## 2. ABI

| Register | Meaning |
|---|---|
| `r1` | input `A`, 65,536 float32 payloads, row-major 256×256 |
| `r2` | input `B`, 65,536 float32 payloads, row-major 256×256 |
| `r3` | output `C`, 65,536 float32 payloads, row-major 256×256 |
| `r13` | `1` (word stride) |
| return | `r1=1` |
| clobbers | `r4-r8` |
| preserved | `r1` is the return value; `r9-r12`, `r13-r15` are untouched |

The entry point is a leaf routine: no `CALL`, no static slots, no shared return
storage, and no workspace in the kernel image. The standalone kernel emits as
16 words.

Caller preconditions:

- `A` and `B` are readable and `C` is writable.
- All three spans are 65,536 contiguous words and row-major.
- Exact aliasing of `C` with `A` or `B` is safe because each element is loaded
  before its result is stored. Partial overlap between any two spans is unsafe.
- No address, alignment, length, NaN, Inf, denormal, or finite-result validation
  is performed.
- There is no failure return; the routine always returns `r1=1` after writing
  all 65,536 output words.

## 3. Traversal and budget

Iteration is one flat loop `k = 0..65,535`, not a nested row/column loop. Each
iteration loads `A[k]` and `B[k]`, executes exactly one `FADD`, stores `C[k]`,
and advances by one word (`r13`). The loop counter counts down from 65,536 to
zero, so there is no 16-bit immediate overflow.

Memory accounting uses 8-byte NaN16 guest words. The raw packed float32 payload
is 256 KiB per matrix, but the guest footprint is 512 KiB per matrix:

| Object | NaN16 words | Guest bytes | Raw float32 bytes |
|---|---:|---:|---:|
| `A` (256×256) | 65,536 | 524,288 (512 KiB) | 262,144 (256 KiB) |
| `B` (256×256) | 65,536 | 524,288 (512 KiB) | 262,144 (256 KiB) |
| `C` (256×256) | 65,536 | 524,288 (512 KiB) | 262,144 (256 KiB) |
| **Three matrices** | **196,608** | **1,572,864 (1.5 MiB)** | **786,432 (768 KiB)** |
| 2 MiB guest budget | 262,144 | 2,097,152 (2 MiB) | — |
| Remaining before code/data | 65,536 | 524,288 (512 KiB) | — |

The 2 MiB budget is the total guest budget, not a per-buffer budget. The three
256×256 buffers consume exactly 1.5 MiB, leaving 512 KiB for code, fixture
strings, case tables, and caller scratch.

The complete fixture image is 197,208 words = 1,577,664 bytes = 1.5046 MiB.
Beyond the three matrices it uses 600 words = 4,800 bytes: a 512-word code region
and 88 words of strings and case tables. The exact remaining headroom is:

```
262,144 - 197,208 = 64,936 words
64,936 × 8        = 519,488 bytes
519,488 / 1,024   = 507.3125 KiB
519,488 / 1,048,576 = 0.4954 MiB
```

A 512×512 matrix alone is 262,144 words = 2 MiB, so three 512×512 matrices
cannot fit this budget; that case would require tiling, paging, or a different
ABI. 256×256 is the largest power-of-two dense three-matrix operation that fits.

## 4. Fixture

`mth/tests/mth_matrix_add256_f32_test.nas` avoids a 65,536-line source. It zeros
`A` and `B` with runtime loops, then writes the sparse pattern with 256 runtime
row iterations:

```
A[i,i]                  = +(i+1)
A[i,(i+1) mod 256]      = -(i+1)
B[i,i]                  = +(i+1)
B[i,(i+2) mod 256]      = +(i+1)
A[r,c], B[r,c]          = +0.0 elsewhere
```

The positive values are produced in the guest by `CVTIF` from `i+1`; the
negative values are exact IEEE sign-bit flips (`BOOL.6` with `0x80000000`). For
rows `1..255`, the expected sum is:

```
C[i,i]                 = 2*(i+1)       (also produced with CVTIF)
C[i,(i+1) mod 256]     = -(i+1)
C[i,(i+2) mod 256]     = +(i+1)
C[i,j]                 = +0.0 elsewhere
```

Eight NaN/Inf/signed-zero pairs then overwrite `A[0,0..7]` and `B[0,0..7]`.
Their expected bits are the declared `FADD` rules already exercised by the
vector-add fixture:

| `A[0,k]` | `B[0,k]` | expected `C[0,k]` | rule |
|---|---|---|---|
| `0x7F800000` (`+inf`) | `0xFF800000` (`-inf`) | `0xFFC00000` | invalid result |
| `0xFF800000` (`-inf`) | `0xFF800000` (`-inf`) | `0xFF800000` | `-inf + -inf` |
| `0x00000000` (`+0`) | `0x80000000` (`-0`) | `0x00000000` | RNE signed zero |
| `0x80000000` (`-0`) | `0x80000000` (`-0`) | `0x80000000` | `-0 + -0` |
| `0x7F800001` (sNaN) | `0x3F800000` (`1.0`) | `0x7FC00001` | first NaN quieted |
| `0x3F800000` (`1.0`) | `0xFF800002` (sNaN) | `0xFFC00002` | second NaN quieted |
| `0x7FC00003` (qNaN) | `0xFFC00004` (qNaN) | `0x7FC00003` | first NaN wins |
| `0x7F800000` (`+inf`) | `0x3F800000` (`1.0`) | `0x7F800000` | finite plus infinity |

Checking covers all 65,536 output words:

- 8 special words `C[0..7]` against the hard-coded table above;
- 248 words `C[0,8..255]` against `+0.0`;
- 65,280 words in rows `1..255` against the sparse pattern.

No host-side arithmetic computes any input value or expected output. Values are
generated in the guest with `CVTIF`, integer masks, and sign-bit operations; the
fixture compares output bits with integer `CMP` instructions.

Fixture layout:

| Label | Word address | Extent |
|---|---:|---:|
| code and helpers | 0 | 512 words reserved |
| `A` | 512 | 65,536 words |
| `B` | 66,048 | 65,536 words |
| `C` | 131,584 | 65,536 words |
| PASS string | 197,120 | 7 words |
| FAIL string | 197,152 | 7 words |
| special-case `A` table | 197,184 | 8 words |
| special-case `B` table | 197,192 | 8 words |
| special-case expected table | 197,200 | 8 words |

## 5. Local evidence

Commands:

```
cd /data/data/com.termux/files/home/NaNROUTER
LC_ALL=C awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk \
  -v CMD=emit mth/tests/mth_matrix_add256_f32_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/mth_matrix_add256_f32_test.nan
LC_ALL=C awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk \
  -v CMD=check \
  /data/data/com.termux/files/usr/tmp/opencode/mth_matrix_add256_f32_test.nan
/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/mth_matrix_add256_f32_test.nan \
  --steps 4000000 --serial
```

Observed:

```
words 197208
check: 0 mismatches

stdout:
MTH MATRIX ADD256 F32 PASS

stderr:
[nan_cli] nan-text: 2500024 steps, rc=3, pc=57, trap=''

exit=0
```

`rc=3` is `NAN_HALTED` from the fixture's `HALT`; the trap string is empty.
2,500,024 steps is below the 4,000,000-step run budget and below a separate
20,000,000-step run that produced the same result. The emitted `.nan` text is
6,595,765 bytes; the loaded guest image is 197,208 words = 1,577,664 bytes.
`nmk.awk -v CMD=check` reports zero decode mismatches for both the standalone
kernel (16 words) and the fixture.

SHA-256 of the emitted fixture text image:

```text
e39520edf853744233202f16477079da905f9d4cb136dd68f67b56b06e7d996e  mth_matrix_add256_f32_test.nan
```

## 6. Limitations

- Dense 256×256 float32 only; all three spans are strictly row-major and
  contiguous. There is no strided, rectangular, tiled, or paged form.
- No partial overlap or in-place shifting layout. Exact `C==A` or `C==B` is
  safe, but partially overlapping spans are not.
- No overlap, alignment, length, NaN/Inf, denormal, or finite-result validation;
  those remain caller preconditions.
- The kernel writes the output in increasing linear order, so it is not
  transactional and has no rollback or partial-output status.
- It is not a matrix multiply or a cache-blocked operation; it is one leaf
  elementwise addition primitive.
- The 2 MiB figure is the current guest budget policy. Acceptance by this local
  text-loader run is not proof that a GLT page-limit harness enforces 2 MiB;
  that remains a separate deployment gate.
- No CI run is claimed or referenced. The fixture is executed directly with
  `nan_cli` and is not registered in `tools/run_mth_fixtures.py` by this change.
