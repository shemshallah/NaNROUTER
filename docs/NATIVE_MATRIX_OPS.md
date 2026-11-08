# Native float32 matrix transpose (256×256)

Status: source-written and locally executed with the canonical NaN0S toolchain
(`nan0s/tools/nmk.awk` and `nan0s/aarch64/android/nan_cli`) on 2026-11-07.
This is local native evidence only, **not a CI claim**. The two sources are not
registered in any manifest, spec, fixture list, or test harness by this change.

## 1. Scope

`mth/nan16/mth_matrix_transpose256_f32.nas` computes the dense transpose of a
row-major 256×256 float32 matrix:

```
B[j,i] = A[i,j]        for i = 0..255, j = 0..255
```

Both matrices are 65,536 NaN16 words (256×256). Each float32 value is one IEEE
binary32 bit pattern stored in the 32-bit payload of one NaN16 word. The kernel
executes only NaN16 instructions: one `LD` and one `ST` per element, with no
arithmetic, no host math, no FMA, and no reassociation.

The fixture is `mth/tests/mth_matrix_transpose256_f32_test.nas`.

## 2. ABI

| Register | Meaning |
|---|---|
| `r1` | input `A`, 65,536 float32 payloads, row-major 256×256 |
| `r2` | output `B`, 65,536 float32 payloads, row-major 256×256 |
| `r13` | `1` (word stride) |
| return | `r1=1` |
| clobbers | `r4-r10`, `r12` |
| preserved | `r1` is the return value; `r11`, `r13`, `r14` are untouched |

The entry point is a leaf routine: no `CALL`, no static slots, no shared return
storage, and no workspace in the kernel image.

Caller preconditions:

- `A` is readable and `B` is writable.
- `A` and `B` are distinct, non-overlapping 65,536-word spans.
- In-place transposition is not supported; the output overwrites words that a
  later input row still needs to read.
- No address, alignment, length, NaN, Inf, or denormal validation is performed.
- There is no failure return; the routine always returns `r1=1` after writing
  all 65,536 output words.

## 3. Traversal and budget

Iteration order is fixed: increasing input row `i`, then increasing input
column `j`. For each element the kernel loads `A[i,j]`, stores it to `B[j,i]`,
advances the input cursor by one word (`r13`) and the output cursor by 256
words. The outer step advances the input row by 256 words and the output column
by one word.

Memory accounting uses 8-byte NaN16 guest words. The raw packed float32 payload
is 256 KiB per matrix, but the guest footprint is 512 KiB per matrix:

| Object | NaN16 words | Guest bytes | Raw float32 bytes |
|---|---:|---:|---:|
| `A` (256×256) | 65,536 | 524,288 (512 KiB) | 262,144 (256 KiB) |
| `B` (256×256) | 65,536 | 524,288 (512 KiB) | 262,144 (256 KiB) |
| **Both buffers** | **131,072** | **1,048,576 (1 MiB)** | **524,288 (512 KiB)** |
| 2 MiB guest budget | 262,144 | 2,097,152 (2 MiB) | — |
| Remaining after both buffers | 131,072 | 1,048,576 (1 MiB) | — |

The 2 MiB budget is the total guest budget, not a per-buffer budget. The two
256×256 buffers together consume 1 MiB, so they fit with 1 MiB still available
for code, fixture strings, and caller scratch. The complete fixture image is
131,609 words = 1,052,872 bytes = 1.004 MiB, leaving 130,535 words = 1,044,280
bytes below the 2 MiB limit.

256×256 is the largest power-of-two matrix used by the MTH suite that fits this
two-buffer budget. A 512×512 matrix is 262,144 words = 2 MiB **for one buffer
alone**, so it cannot hold both input and output inside 2 MiB; a 512×512
transpose would require tiling, paging, or a different ABI.

## 4. Fixture

`mth/tests/mth_matrix_transpose256_f32_test.nas` avoids a 65,536-line source.
It zeroes both matrices with runtime loops and then writes the source pattern
with 256 runtime stores:

```
A[i,i]                  = -(i+1)
A[i,(i+1) mod 256]      = +(i+1)
A[r,c]                  = +0.0 elsewhere
```

Each row therefore has one diagonal nonzero and one off-diagonal nonzero. The
positive values are produced by `CVTIF` from `i+1`; the negative diagonal values
are exact IEEE sign-bit flips (`BOOL.6` with `0x80000000`). No host arithmetic
is used.

Phase 1 transposes `A` into `B` and scans all 65,536 words of `B`:

```
B[r,r]             = -(r+1)                       diagonal mapping
B[r,(r-1) mod 256] = ((r-1) mod 256) + 1          off-diagonal mapping
B[r,c]             = +0.0 elsewhere
```

Phase 2 transposes `B` back into `A` and scans all 65,536 words of `A` against
the original source pattern, checking the involution `T(T(A)) = A`. The
transposed-pattern and source-pattern checks are separate helper routines
because the off-diagonal image moves from `(i,i+1)` in `A` to `(i+1,i)` in `B`.

Fixture layout:

| Label | Word address | Extent |
|---|---:|---:|
| code and helpers | 0 | below 512 |
| `A` | 512 | 65,536 words |
| `B` | 66,048 | 65,536 words |
| PASS string | 131,584 | 9 words |
| FAIL string | 131,600 | 9 words |

## 5. Local evidence

Commands:

```
cd /data/data/com.termux/files/home/NaNROUTER
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=emit \
  mth/tests/mth_matrix_transpose256_f32_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/mth_matrix_transpose256_f32_test.nan
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=check \
  /data/data/com.termux/files/usr/tmp/opencode/mth_matrix_transpose256_f32_test.nan
/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/mth_matrix_transpose256_f32_test.nan \
  --steps 4000000 --serial
```

Observed:

```
words 131609
check: 0 mismatches

stdout:
MTH MATRIX TRANSPOSE256 F32 PASS

stderr:
[nan_cli] nan-text: 3290464 steps, rc=3, pc=55, trap=''

exit=0
```

`rc=3` is `NAN_HALTED` from the fixture's `HALT`; the trap string is empty.
3,290,464 steps is below the 4,000,000-step run budget (and below the earlier
20,000,000-step run that produced the same result). The emitted `.nan` text is
4,365,313 bytes; the loaded guest image is 131,609 words = 1,052,872 bytes.
`nmk.awk -v CMD=check` reports zero decode mismatches.

## 6. Limitations

- Dense 256×256 float32 only; the layout is strictly row-major and contiguous.
- No in-place transpose, partial overlap, strided layout, tiling, paging, or
  rectangular matrices.
- No overlap, alignment, NaN/Inf, denormal, or finite-result validation; those
  are caller preconditions.
- The kernel writes the output in increasing source-row order, so it is not
  transactional and has no rollback or partial-output status.
- This is not a matrix multiply, factorization, or cache-blocked transpose; it
  is one leaf data-movement primitive.
- The 2 MiB figure is the current adjustable guest budget. There is no page-size
  limit or page-size enforcement gate; the fixed 32 KiB page is only a logical
  universe layout unit.
- No CI run is claimed or referenced. The fixture is executed directly with
  `nan_cli` and is not registered in `tools/run_mth_fixtures.py` by this change.
