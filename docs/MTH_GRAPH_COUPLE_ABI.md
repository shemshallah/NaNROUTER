# MTH two-region coupling primitive

Status: source-written and locally executed with the canonical NaN0S toolchain; CI promotion pending.

## 1. Scope

`mth/nan16/mth_graph_couple_128.nas` implements a symmetric convex coupling of two 128-position regions:

```
inner_next[i] = (1 - eta) * inner[i] + eta * outer[i]
outer_next[i] = eta * inner[i] + (1 - eta) * outer[i]
```

This is the R7 block-coupling primitive for tunneling/avoided-crossing experiments. `eta` is a computational mixing coefficient, not a physical tunneling probability. The actual transmission metric is a separate experiment.

## 2. ABI

All scalars are float32. `r13=1`.

| Register | Meaning |
|---|---|
| `r1` | inner, 128 float32 |
| `r2` | outer, 128 float32 |
| `r3` | eta, one float32 in [0,1] |
| `r4` | inner_next, 128 float32 |
| `r5` | outer_next, 128 float32 |
| `r13` | 1 |
| return | `r1=1` success, `r1=0` invalid eta/layout |

Preflight checks `eta` is finite and in `[0,1]`, and rejects overlapping spans before writing output. `eta` is passed by value, not by pointer. No host math, no `CALL`, no static slots.

## 3. Fixture

`mth/tests/mth_graph_couple_128_test.nas` checks:

- `inner=1`, `outer=3`, `eta=0.5` -> both `2`;
- `eta=0` -> `inner=1`, `outer=3`;
- `eta=1` -> `inner=3`, `outer=1`;
- `eta=1.5` -> status `0`, output sentinel preserved.

Local canonical run:

```
MTH GRAPH COUPLE 128 PASS
8,637 steps, rc=3/HALT
```

## 4. Limitations

- This is a state-mixing primitive, not the full Hamiltonian block `H(eta)`.
- No phase, energy, or transmission metric is computed here.
- 128 positions only; 255/256-region coupling is a later version.
- No NaN/Inf input validation for the region values; `eta` is validated.
