# MTH radial energy and localization

Status: source-written and locally executed PASS (39,276 steps); CI/1 MiB
promotion pending.

## 1. Scope

Computes the quadratic energy and localization of a 256-vector for the
symmetric tridiagonal radial operator. It complements
`mth_radial_tridiagonal.nas`; the caller still owns boundary encoding in
`diag`/`offdiag`.

## 2. ABI

| Register | Meaning |
|---|---|
| `r1` | diag, 256 float32 |
| `r2` | offdiag, 255 float32 |
| `r3` | x, 256 float32 |
| `r4` | energy output, one float32 |
| `r5` | localization output, one float32 |
| `r13` | 1 |
| return | `r1=1` |

```text
energy       = sum_i diag[i]*x[i]^2
             + 2 * sum_{i=0}^{254} offdiag[i]*x[i]*x[i+1]
localization = max_i x[i]^2 / sum_i x[i]^2   (0 when x is zero)
```

Increasing index, single accumulator per sum, NaN16 float32 only, leaf, no host
math.

## 3. Fixture

`mth/tests/mth_radial_energy_test.nas` uses `diag=2`, `offdiag=-1` and checks:

- `x=1`: energy `2.0`, localization `1/256` (0x3B800000);
- zero `x`: energy `0`, localization `0`;
- `x=e0`: energy `2.0`, localization `1.0`;
- `x=e128`: energy `2.0`, localization `1.0`.

Local canonical run:

```
MTH RADIAL ENERGY PASS
39,276 steps, rc=3/HALT
```

## 4. Limitations

- Symmetric tridiagonal operator only; no full radial PDE solve.
- Boundary convention is the caller's `diag`/`offdiag`; there is no boundary
  branch in this kernel.
- No NaN/Inf/alias validation.
