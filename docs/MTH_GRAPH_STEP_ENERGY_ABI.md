# MTH step energy metric

Status: source-written and locally executed with the canonical NaN0S toolchain; CI promotion pending.

## 1. Scope

`mth/nan16/mth_graph_step_energy_256.nas` computes the discrete quadratic energy of one wave step from `u`, `v`, and the supplied acceleration `a = -H u`:

```
kinetic   = 0.5 * sum_i v[i]^2
potential = 0.5 * sum_i u[i] * (-a[i])
total     = kinetic + potential
```

This is the energy analogue used to inspect wave runs. It does not prove a full-run conservation law by itself.

## 2. ABI

| Register | Meaning |
|---|---|
| `r1` | u, 256 float32 |
| `r2` | v, 256 float32 |
| `r3` | a, 256 float32, already `-H u` |
| `r4` | output, three float32: kinetic, potential, total |
| `r13` | 1 |
| return | `r1=1` |

Accumulation is in increasing index order. No host math.

## 3. Fixture

`mth/tests/mth_graph_step_energy_256_test.nas` checks `u=1`, `v=2`, `a=-3` for all 256:

```
kinetic=512, potential=384, total=896
```

Local canonical run:

```
MTH GRAPH STEP ENERGY PASS
7,956 steps, rc=3/HALT
```

## 4. Limitations

- `a` is trusted; the kernel does not apply `H`.
- Unnormalized quadratic form; mass/stiffness scales are the caller’s contract.
- 256 positions only.
- No NaN/Inf validation of state values.
