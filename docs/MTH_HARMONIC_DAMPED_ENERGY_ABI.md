# MTH damped harmonic wave-energy fixture

Status: source-written and locally executed with the canonical NaN0S toolchain; CI promotion pending.

## 1. Scope

`mth/tests/mth_harmonic_damped_energy_test.nas` is the damped companion to the undamped harmonic fixture:

```
u(0)=1, v(0)=0, k=1, dt=0.1, gamma=0.1
four velocity-Verlet steps
```

The final total energy must be strictly below the initial `128.0` and remain positive.

## 2. Evidence

The fixture uses `mth_harmonic_accel_256.nas`, `mth_graph_wave.nas`, and `mth_graph_step_energy_256.nas`. It checks the positive-float bit order against `128.0` with an integer `CMP`, avoiding ambiguous mixed float predicate behavior in the harness.

Local canonical run:

```
MTH HARMONIC DAMPED ENERGY PASS
53,890 steps, rc=3/HALT
```

Observed final total energy: `0x42FF0DF8` (about `127.526`), below `128.0` and positive.

## 3. Limitations

- Diagonal harmonic `H`, not a graph Laplacian.
- One `gamma`/`dt`/step count; no damping sweep.
- Four steps only; no CFL or long-run claim.
