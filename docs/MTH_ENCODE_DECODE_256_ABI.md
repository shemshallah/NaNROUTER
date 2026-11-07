# MTH full 256×256 ENCODE / DECODE linear kernels

Status: source-written and locally executed with the canonical NaN0S assembler
and `nan_cli` text loader. Canonical CI run 42395520794 executed the fixture; GLT/MthSystem 1 MiB dispatch enforcement is pending;
the old 512 KiB evidence remains historical.

## 1. Scope

This slice adds the two full square dense linear maps needed by an R9 adapter
projection pair:

```
mth_encode256_full_f32:  y[i] = b[i] + sum_{j=0}^{255} W[i,j] * x[j]   (256 -> 256)
mth_decode256_full_f32:  y[i] = b[i] + sum_{j=0}^{255} W[i,j] * z[j]   (256 -> 256)
```

Both kernels use a full 256×256 row-major float32 matrix, 65,536 NaN16 words.
They are leaf NaN16 float32 kernels: no `CALL`, no host math, no training, and
no composition with the residual/readout adapter contract.

The earlier prototypes are separate contracts and remain unchanged:

- `mth_encode256_128_f32` is a 256 -> 128 rectangular map (`docs/MTH_ENCODE_DECODE_ABI.md`).
- `mth_decode128_256_f32` is a 128 -> 256 rectangular map (same document).

The full decode kernel is a separate 256×256 square map. It does not replace,
compose with, or tie weights to either rectangular prototype.

Files:

- `mth/nan16/mth_encode256_full.nas`
- `mth/nan16/mth_decode256_full.nas`
- `mth/tests/mth_encode_decode256_test.nas`

## 2. ABI

Both kernels use the same register contract.

| Register | Meaning |
|---|---|
| `r1` | `W`, 65,536 float32, row-major 256 × 256 |
| `r2` | `x` or `z`, 256 float32 input vector |
| `r3` | `b`, 256 float32 bias |
| `r4` | `y`, 256 float32 output |
| `r13` | 1 |
| return | `r1 = 1` |
| clobbers | `r1`-`r12`, `r14`; preserves `r13` and `r15` |

Arithmetic order is identical for both kernels: rows are visited in increasing
`i` and columns in increasing `j`. One accumulator per row is seeded with
`b[i]`, then each column performs one rounded `FMUL` followed by one rounded
`FADD`:

```
b[i] + W[i,0]*v[0] + W[i,1]*v[1] + ... + W[i,255]*v[255]
```

There is no FMA, no reassociation, and no specialization for sparsity. The
kernels always return `r1=1`; there is no failure path or validation.

Caller preconditions: `r13=1`; `W`, the input vector, the bias, and the output
must be distinct non-overlapping spans; `W` is read-only. Overlap, alignment,
NaN, Inf, and denormal behavior are unspecified.

## 3. Working set and the 1 MiB budget

Per-kernel working set:

```
W      65,536 words
input     256 words
bias      256 words
output    256 words
---------------------
total  66,304 words = 530,432 bytes
```

The assembled fixture adds code and strings, for 66,830 words = 534,640 bytes.

| Budget | Words | Bytes | Result |
|---|---:|---:|---|
| Old 512 KiB ceiling | 65,536 | 524,288 | Exceeded by 1,294 words / 10,352 bytes |
| New 1 MiB target | 131,072 | 1,048,576 | Fits with 64,242 words / 513,936 bytes spare |

1 MiB is 32 pages of 32 KiB, or 131,072 NaN16 words.

## 4. Fixture

`mth/tests/mth_encode_decode256_test.nas` assembles both kernels into one
image and reuses one 65,536-word `W` buffer for both cases.

Encode case:

- `W = 2I`: `W[i,i]=2.0` for all 256, zero elsewhere (row stride 256,
  diagonal stride 257);
- `x=1` for all 256 and `b=1` for all 256;
- expected `y[i] = 1 + 2*1 = 3.0` for all 256.

Decode case (second bias case):

- the same `W = 2I` and `z=1`;
- `y` is cleared first, then `b=2` for all 256;
- expected `y[i] = 2 + 2*1 = 4.0` for all 256.

Clearing `y` before decode prevents a decode that fails to write from
inheriting the encode result. Both result sweeps are exhaustive over
`i = 0..255`, including the endpoint positions 0 and 255.

Fixture layout:

| Symbol | Word range | Size |
|---|---:|---:|
| `W` | 512..66,047 | 65,536 |
| input vector | 66,048..66,303 | 256 |
| bias | 66,304..66,559 | 256 |
| output | 66,560..66,815 | 256 |
| strings | 66,816.. | 2 strings |

The image is emitted as text (`.nan`), not as a 1.44 MB floppy image.

## 5. Local evidence

Assemble and check:

```
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=emit \
  mth/tests/mth_encode_decode256_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/encode256.nan

awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=check \
  /data/data/com.termux/files/usr/tmp/opencode/encode256.nan
```

Observed assembler/check output:

```
words 66830
check: 0 mismatches
```

Run:

```
/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/encode256.nan \
  --steps 30000000 --serial
```

Observed output:

```
[nan_cli] nan-text: 1655853 steps, rc=3, pc=174, trap=''
MTH ENCODE DECODE 256 PASS
```

`rc=3` is `HALT`; `nan_cli` exits 0. The 1,655,853 guest steps are well under
the 30,000,000-step budget.

Toolchain note: the local `nan_cli` text loader on this checkout accepts text
images up to `NAN_WORDS` (4,194,304 words), so it executed this 66,830-word
image even though the fixture exceeds 65,536 words. That local text path is
not itself proof that the 1 MiB page limit is enforced. The legacy floppy-image
path in `core/nan_load.c` still clamps to 65,536 words, and
`docs/MTH_SYSTEM_RUNTIME.md` still shows an explicit
`guest_budget_bytes=512 * 1024`. Registering or dispatching this fixture
through a 512 KiB MthSystem plan will therefore reject it; canonical 1 MiB
canonical CI run 42395520794 passed; GLT enforcement remains pending.

## 6. Limitations

- **Dense full-matrix only.** Both kernels read all 65,536 matrix words on
  every call. There is no sparse, low-rank, quantized, tiled, or paged path.
- **Fixed square shape only.** Both are exactly 256 -> 256 with a 256×256
  matrix. The 256 -> 128 and 128 -> 256 prototypes are separate contracts.
- **No training.** Forward inference only; no gradients, updates, optimizer,
  initialization, or weight tying. The fixture builds `W=2I` in guest code
  solely as an oracle.
- **No validation.** Overlap, aliasing, alignment, NaN, Inf, denormal, and
  range checks are caller preconditions. Behavior for aliased spans is
  unspecified.
- **Accumulation order.** Serial in increasing `j` with one accumulator per
  row; results need not be bitwise identical to BLAS, FMA, pairwise, or
  otherwise reordered implementations.
- **Register contract.** Callers must set `r13=1`; both kernels clobber
  `r1`-`r12` and `r14` and preserve `r15`. They contain no `CALL`.
- **Budget status.** The source and fixture target 1 MiB and exceed the old
  512 KiB ceiling. Local text-mode execution passed; canonical 1 MiB
  MthSystem/GLT page-limit dispatch is not yet claimed; canonical CI execution passed in run 42395520794.
