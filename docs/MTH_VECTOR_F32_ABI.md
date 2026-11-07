# MTH float32 vector primitives

Status: source-written and locally executed with the canonical NaN0S toolchain; CI promotion pending.

## 1. Dot product

`mth/nan16/mth_dot256_f32.nas` computes:

```
dot = sum_{i=0}^{255} x[i] * y[i]
```

### ABI

| Register | Meaning |
|---|---|
| `r1` | x, 256 float32 payloads |
| `r2` | y, 256 float32 payloads |
| `r3` | output, one float32 payload |
| `r13` | constant 1 |
| return | `r1=1` success |

Accumulation order is increasing `i`; no reordering, fused multiply-add, or host math. The caller supplies non-overlapping or safely readable spans.

Fixture: `mth/tests/mth_dot256_test.nas` checks all-2 · all-3 = 1536.0 and zero-vector = 0. Local run: `MTH DOT256 PASS`, 9,144 steps.

## 2. Euclidean norm

`mth/nan16/mth_norm256_f32.nas` computes:

```
norm = sqrt(sum_{i=0}^{255} x[i] * x[i])
```

### ABI

| Register | Meaning |
|---|---|
| `r1` | x, 256 float32 payloads |
| `r2` | output, one float32 payload |
| `r13` | constant 1 |
| return | `r1=1` success |

Accumulation order is increasing `i`; `FSQRT` is the native NaN16 float32 square root. No host math.

Fixture: `mth/tests/mth_norm256_test.nas` checks all-3 norm = 48.0 and zero-vector = 0. Local run: `MTH NORM256 PASS`, 6,842 steps.

## 3. Axpy

`mth/nan16/mth_axpy256_f32.nas` computes:

```
y[i] = y[i] + alpha * x[i]
```

### ABI

| Register | Meaning |
|---|---|
| `r1` | x, 256 float32 payloads |
| `r2` | y, 256 float32 payloads, updated in place |
| `r3` | alpha, one float32 payload |
| `r13` | constant 1 |
| return | `r1=1` success |

Accumulation order is increasing `i`; no reordering, fused multiply-add, or host math. The caller supplies readable/writable spans. Fixture: `mth/tests/mth_axpy256_test.nas` checks `1 + 0.5*2 = 2` and `alpha=0` identity. Local run: `MTH AXPY256 PASS`, 8,389 steps.

## 4. Use

These are reference primitives for `QUERY`, `MATCH`, normalization, `DRIVE`, and residual checks. They are not a full vector-descriptor layer: shape, stride, type, and ownership remain the caller's contract. A fused or pairwise-compensated implementation may be added later only after it matches the reference order within the declared error bound.

## 5. Next gates

1. Add all three fixtures to native CI.
2. Add a stable top-k / cosine similarity composition.
3. Add a typed vector descriptor with shape/stride/precision.
4. Keep exact U32/Q16.16 primitives separate; do not silently mix lanes.
