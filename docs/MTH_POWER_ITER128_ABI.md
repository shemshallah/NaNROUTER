# MTH 128×128 power iteration

Status: source-written, locally executed, and CI promotion pending.

## 1. Scope

`mth/nan16/mth_power_iter128.nas` computes the dominant eigenpair of a dense symmetric 128×128 float32 matrix using bounded power iteration. It reuses `mth_matvec128_f32.nas`.

## 2. ABI

| Register | Meaning |
|---|---|
| `r1` | A, 16,384 float32, row-major 128×128 symmetric |
| `r2` | x, 128 float32 input direction |
| `r3` | iterations, integer 1..64 |
| `r4` | lambda output, one float32 |
| `r5` | v output, 128 float32 |
| `r6` | scratch, 128 float32 |
| `r13` | 1 |
| return | `r1=1` success, `r1=0` invalid zero vector/iteration count/degenerate iterate |

The input direction is normalized first, then `v ← A v / ||A v||` for the declared number of iterations. The final `lambda` is the Rayleigh quotient `vᵀAv / vᵀv`, accumulated in increasing index order.

## 3. Return-address frame

The kernel calls `mth_matvec128_f32`, which clobbers the single `r15` link register. The kernel saves `r15` before any nested call and restores it before both success and invalid returns. It also uses a private seven-word save frame, so it is **non-reentrant and non-concurrent**.

## 4. Fixture

`mth/tests/mth_power_iter128_test.nas` builds `A=2I`, sets `x=1`, runs 3 iterations, and checks:

- `lambda` is bit-exactly `2.0` (`0x40000000`);
- `v[0]=v[127]`;
- `sum v[i]^2` is within two float32 ulps of `1.0`;
- an all-zero input rejects with status `0` and leaves `lambda` untouched;
- `iterations=0` and `iterations=65` reject with status `0`.

Local canonical run:

```
MTH POWER_ITER128 PASS
758,847 steps, rc=3/HALT
```

## 5. Limitations

- Symmetric 128×128 only; no deflation/top-k.
- Static save frame; not reentrant.
- No convergence/residual threshold; iteration count is caller-declared.
- No NaN/Inf or overlap validation.
- Not a full SVD; general rectangular/non-normal apertures need a separate path.
