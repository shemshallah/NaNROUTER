# Native float32 matrix diagonal extraction (256×256)

Status: source-written and locally executed with the canonical NaN0S toolchain
(`nan0s/tools/nmk.awk` and `nan0s/aarch64/android/nan_cli`) on 2026-11-07.
This is local native evidence only, **not a CI claim**. The two sources are not
registered in any manifest, spec, fixture list, or test harness by this change.

## 1. Scope

`mth/nan16/mth_matrix_diagonal256_f32.nas` extracts the 256-element diagonal of
a row-major 256×256 float32 matrix:

```
D[i] = A[i,i]          for i = 0..255
```

The input is 65,536 NaN16 words (256×256) and the output is 256 NaN16 words.
Each float32 value is one IEEE binary32 bit pattern stored in the 32-bit
payload of one NaN16 word. The kernel executes only NaN16 instructions: one
`LD` and one `ST` per diagonal element, with no arithmetic on the payload, no
host math, no FMA, and no reordering.

The fixture is `mth/tests/mth_matrix_diagonal256_f32_test.nas`.

## 2. ABI

| Register | Meaning |
|---|---|
| `r1` | input `A`, 65,536 float32 payloads, row-major 256×256 |
| `r2` | output `D`, 256 float32 payloads |
| `r13` | `1` (word stride) |
| return | `r1=1` |
| clobbers | `r4-r8`, `r12` |
| preserved | `r2`, `r3`, `r9-r11`, `r13`, `r14`; `r1` becomes the return value |

The entry point is a leaf routine: no `CALL`, no static slots, no shared return
storage, and no workspace in the kernel image.

Caller preconditions:

- `A` is readable and `D` is writable.
- `D` is a distinct, non-overlapping 256-word span. In particular, `D` must not
  overlap any part of `A` that has not yet been read; otherwise a store could
  overwrite a later diagonal element.
- No address, alignment, length, NaN, Inf, or denormal validation is performed.
  Payloads are copied bit-exactly, including non-finite payloads.
- There is no failure return; the routine always returns `r1=1` after writing
  all 256 output words.

## 3. Traversal and budget

The input cursor starts at `A[0,0]` and advances by 257 words for each next
diagonal element: one 256-word row plus one column. The output cursor advances
by one word (`r13`). The loop runs exactly 256 times.

Memory accounting uses 8-byte NaN16 guest words:

| Object | NaN16 words | Guest bytes | Raw float32 bytes |
|---|---:|---:|---:|
| `A` (256×256) | 65,536 | 524,288 (512 KiB) | 262,144 (256 KiB) |
| `D` (256) | 256 | 2,048 (2 KiB) | 1,024 (1 KiB) |
| **Both buffers** | **65,792** | **526,336 (514 KiB)** | **263,168 (257 KiB)** |
| 2 MiB guest budget | 262,144 | 2,097,152 (2 MiB) | — |
| Remaining after both buffers | 196,352 | 1,570,816 (1.498 MiB) | — |

The complete fixture image is 66,346 words = 530,768 bytes = 518.3 KiB,
leaving 195,798 words = 1,566,384 bytes below the 2 MiB guest limit.

## 4. Fixture

`mth/tests/mth_matrix_diagonal256_f32_test.nas` avoids a 65,536-line source.
It pre-fills the output with `0xDEAD0000`, builds the diagonal with 256 runtime
stores, and writes 11 off-diagonal negative sentinels with runtime stores:

```
A[i,i]                  = +(i+1)                  for i = 0..255
A[r,c]                  = -(r+1)                  at the 11 positions below
A[r,c]                  = +0.0                    elsewhere (assembler padding)
```

The selected off-diagonals are:

| Position | Value | Position | Value |
|---|---:|---|---:|
| `(0,1)` | -1 | `(0,255)` | -1 |
| `(1,0)` | -2 | `(1,2)` | -2 |
| `(127,126)` | -128 | `(127,128)` | -128 |
| `(128,127)` | -129 | `(128,129)` | -129 |
| `(254,255)` | -255 | `(255,0)` | -256 |
| `(255,254)` | -256 | | |

This covers both sides of the diagonal, the first and last rows and columns,
and the middle of the matrix. Positive values are produced by `CVTIF` from
`i+1`; negative sentinels are exact IEEE sign-bit flips (`BOOL.6` with
`0x80000000`). No host arithmetic is used.

The fixture has three phases:

1. Pre-check every off-diagonal table entry in `A`, proving the negative
   sentinels are actually present before the kernel runs.
2. Call the kernel, then scan all 256 output words and require
   `D[r] = +(r+1)` exactly.
3. Scan all 256 output words and require the sign bit to be clear, proving that
   none of the negative off-diagonal sentinels was selected.

The table drives both the fill and the pre-check, so the same positions are
written and verified.

Fixture layout:

| Label | Word address | Extent |
|---|---:|---:|
| code and helpers | 0 | below 512 |
| `A` | 512 | 65,536 words |
| `D` | 66,048 | 256 words |
| PASS string | 66,304 | 9 words |
| FAIL string | 66,313 | 9 words |
| off-diagonal table | 66,322 | 24 words |

## 5. Local evidence

Commands:

```
cd /data/data/com.termux/files/home/NaNROUTER
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=emit \
  mth/tests/mth_matrix_diagonal256_f32_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/mth_matrix_diagonal256_f32_test.nan
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=check \
  /data/data/com.termux/files/usr/tmp/opencode/mth_matrix_diagonal256_f32_test.nan
/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/mth_matrix_diagonal256_f32_test.nan \
  --steps 200000 --serial
```

Observed:

```
words 66346
check: 0 mismatches

stdout:
MTH MATRIX DIAGONAL256 F32 PASS

stderr:
[nan_cli] nan-text: 9865 steps, rc=3, pc=49, trap=''

exit=0
```

`rc=3` is `NAN_HALTED` from the fixture's `HALT`; the trap string is empty.
9,865 steps is far below the 200,000-step run budget. The emitted `.nan` text
is 2,179,828 bytes; the loaded guest image is 66,346 words = 530,768 bytes.
`nmk.awk -v CMD=check` reports zero decode mismatches.

## 6. Limitations

- Dense 256×256 float32 only; the layout is strictly row-major and contiguous.
- No in-place extraction, partial overlap, strided input, submatrix selection,
  tiling, or rectangular matrices.
- No overlap, alignment, length, NaN/Inf, denormal, or finite-result
  validation; those are caller preconditions.
- No failure return. The kernel writes all 256 outputs in increasing row order,
  so it is not transactional and has no rollback or partial-output status.
- This is one leaf data-movement primitive, not diagonal-matrix construction,
  trace, matrix multiplication, or a cache-blocked operation.
- The 2 MiB figure is the current guest budget policy. This local text-loader
  run is not proof that a GLT page-limit harness enforces 2 MiB; that remains a
  separate deployment gate.
- No CI run is claimed or referenced. The fixture is executed directly with
  `nan_cli` and is not registered in `tools/run_mth_fixtures.py` by this change.
