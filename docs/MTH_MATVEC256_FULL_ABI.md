# MTH full 256×256 float32 matrix-vector product

Status: source-written and locally executed with the canonical NaN0S `nmk.awk` / `nan_cli`
toolchain on 2026-11-07 through the `.nan` text loader. The fixture image is 66,574
NaN16 words (532,592 bytes), which exceeds the historical 512 KiB (65,536-word)
guest. It targets the new 1 MiB (131,072-word) guest budget; canonical GLT 1 MiB
page-limit execution is still pending, but canonical CI run 42395520794 executed the fixture successfully.

## 1. Scope

`mth/nan16/mth_matvec256_full.nas` computes the complete dense product:

```
y[i] = sum_{j=0}^{255} A[i,j] * x[j]        for i = 0..255
```

for a row-major 256×256 float32 matrix in one leaf call. It is the monolithic
form of the paged `mth_matvec256_block16` kernel and requires the 1 MiB guest
budget to hold `A`, `x`, `y`, and code together.

## 2. ABI

| Register | Meaning |
|---|---|
| `r1` | A, 65,536 float32, row-major 256×256 |
| `r2` | x, 256 float32 |
| `r3` | y, 256 float32 output |
| `r13` | 1 |
| return | `r1=1` |
| clobbers | `r4`-`r12`, `r14` |

The kernel is a leaf: it contains no `CALL`. Accumulation is increasing `j`,
one `+0.0` accumulator per row, one rounded `FMUL` followed by one rounded
`FADD` per term. No FMA, reassociation, hidden precision, or host math.

Inputs are read-only; the three spans must be distinct and non-overlapping.
All values are caller-supplied float32; NaN/Inf domain policy is caller-side.

## 3. Memory budget

| Object | NaN16 words | Bytes |
|---|---:|---:|
| A (256×256 float32) | 65,536 | 524,288 |
| x | 256 | 2,048 |
| y | 256 | 2,048 |
| **Kernel working set** | **66,048** | **528,384** |
| 1 MiB guest budget | 131,072 | 1,048,576 |
| Remaining for code/scratch | 65,024 | 520,192 |

This is the key difference from `mth_matvec256_block16`: the whole matrix is
resident, so the caller performs one call instead of 16 block calls. The 16-block
form remains the bounded path for the old 512 KiB budget and for multi-tenant
plans larger than 1 MiB.

## 4. Fixture

`mth/tests/mth_matvec256_full_test.nas` lays out:

| Label | Word address |
|---|---:|
| code and puts helper | 0 |
| A | 512 |
| x | 66,048 |
| y | 66,304 |
| pass/fail strings | 66,560 |

The image is 66,574 words. It builds `A=2I` programmatically (zero all 65,536
words, then set `A[i,i]=2.0`, stride 257) and checks all 256 outputs for each of:

- `x=1.0` → `y[i]=2.0`;
- `x=-1.0` → `y[i]=-2.0`;
- `x=+0.0` → `y[i]=+0.0`;
- ramp `x[i]=float(i+1)` → `y[i]=2*x[i]`.

The final ramp is the alignment check: a uniform vector cannot detect a
row/column permutation, while the ramp gives every column a distinct value.
For the ramp, the expected products are computed in the guest with `FMUL` by
2.0; the kernel under test is the only code that traverses A.

## 5. Local evidence

Commands:

```
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=emit \
  mth/tests/mth_matvec256_full_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/matvec256full.nan
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=check \
  /data/data/com.termux/files/usr/tmp/opencode/matvec256full.nan
/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/matvec256full.nan \
  --steps 50000000 --serial
```

Observed:

```
words 66574
check: 0 mismatches

stdout:
MTH MATVEC256 FULL PASS

stderr:
[nan_cli] nan-text: 2978362 steps, rc=3, pc=190, trap=''

exit=0
```

`rc=3` is `NAN_HALTED` (the fixture's `HALT`); the trap string is empty.
2,978,362 steps is under the 50,000,000-step run budget. The emitted `.nan`
text file is 2,187,734 bytes; the loaded guest image is 66,574 words
(532,592 bytes). The repository fixture runner also reports:

```
[PASS] matvec256full: PASS steps=2978362 marker=MTH MATVEC256 FULL PASS
1/1 fixtures passed
```

## 6. Old 512 KiB limitation and 1 MiB validation

The fixture image is 66,574 words = 532,592 bytes. The historical guest budget
is 65,536 words = 524,288 bytes, so the image exceeds it by 1,038 words
(8,304 bytes) before any runtime allowance.

In the current local NaN0S checkout, the floppy-image loader
(`aarch64/android/core/nan_load.c`, `nan_load_image`) still caps the guest at
65,536 words and would truncate this image. The run above therefore used the
`.nan` text loader (`nan_load_text`); the core's source default is
`NAN_WORDS = 0x400000` (4M words), and it loaded all 66,574 words. That local
run is not evidence of a GLT-enforced 1 MiB page limit. The source and fixture
are written for the announced 1 MiB (131,072-word) budget, and the 1 MiB GLT
harness execution is the outstanding deployment check. Do not use this fixture
on a 512 KiB guest.

## 7. Limitations

- Dense 256×256 float32 only; no transpose, alpha/beta scaling, or in-place `x`.
- `r13` must be 1; the kernel clobbers `r4`-`r12` and `r14`.
- No overlap, alignment, NaN/Inf, or finite-result validation; spans are a caller
  precondition.
- Serial accumulation in increasing `j` with one accumulator, so results are
  not bitwise identical to reordered or FMA-based implementations.
- One matvec per call; power iteration, SVD, and Lanczos remain separate
  compositions.
