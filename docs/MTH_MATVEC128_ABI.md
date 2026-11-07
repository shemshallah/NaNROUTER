# MTH 128×128 float32 matrix-vector product

Status: source-written and locally executed with the canonical NaN0S toolchain; CI promotion pending.

## 1. Scope

`mth/nan16/mth_matvec128_f32.nas` computes:

```
y[i] = sum_{j=0}^{127} A[i,j] * x[j]
```

for a dense row-major 128×128 float32 matrix. This is a foundational aperture/spectral primitive; it does not compute an eigendecomposition or power iteration by itself.

## 2. ABI

| Register | Meaning |
|---|---|
| `r1` | A, 16,384 float32, row-major 128×128 |
| `r2` | x, 128 float32 |
| `r3` | y, 128 float32 output |
| `r13` | 1 |
| return | `r1=1` |

Memory: 16,384 + 128 + 128 = 16,640 words. Inputs are read-only; spans must be distinct and non-overlapping (caller precondition). Accumulation is increasing `j`, one accumulator, no FMA/reordering.

## 3. Fixture

`mth/tests/mth_matvec128_test.nas` builds `A=2I` programmatically, `x=1`, and checks all 128 outputs equal `2.0`.

Local canonical run:

```
MTH MATVEC128 PASS
249,914 steps, rc=3/HALT
```

## 4. Limitations

- Dense 128×128 only; 255/256 matrices need a paged/tiled path.
- No overlap or NaN/Inf validation.
- One matvec only; power iteration, SVD, and Lanczos are separate compositions.
