# MTH harmonic wave-energy fixture

Status: source-written and locally executed with the canonical NaN0S toolchain; CI promotion pending.

## 1. Scope

`mth/nan16/mth_harmonic_accel_256.nas` supplies a diagonal harmonic acceleration:

```
a[i] = -k * u[i]
```

The fixture `mth/tests/mth_harmonic_wave_energy_test.nas` composes it with the verified velocity-Verlet wave step and step-energy metric for four steps:

```
u(0)=1, v(0)=0, k=1, dt=0.1, gamma=0
```

The total energy must stay within `0.1` of `128.0`.

This is the first repeated-step energy fixture. It uses a diagonal harmonic `H`, not a graph Laplacian yet; graph-`H` integration remains a separate gate.

## 2. ABI — harmonic acceleration

| Register | Meaning |
|---|---|
| `r1` | u, 256 float32 |
| `r2` | k, one float32 |
| `r3` | a, 256 float32 output |
| `r13` | 1 |
| return | `r1=1` |

`a[i] = -k*u[i]`, in increasing index order. Leaf routine; no host math.

## 3. Evidence

```
awk -f nan0s/tools/nmk.awk -v CMD=emit mth/tests/mth_harmonic_wave_energy_test.nas > harmonic.nan
nan_cli --img harmonic.nan --steps 10000000 --serial
MTH HARMONIC WAVE ENERGY PASS
53,877 steps, rc=3/HALT
```

The fixture checks the energy tolerance through the native `FCMP` path; it does not compute the energy on the host.

## 4. Limitations

- Diagonal harmonic `H`, not a graph Laplacian.
- Four steps, one fixed `dt`/`k`; no CFL sweep.
- No damping sweep or DRIVE source.
- No claim of universal energy conservation; float32 drift is measured only at this fixture.
