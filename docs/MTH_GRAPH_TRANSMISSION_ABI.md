# MTH two-region transmission metric

Status: source-written and locally executed with the canonical NaN0S toolchain; CI promotion pending.

## 1. Scope

`mth/nan16/mth_graph_transmission_128.nas` computes the energy-ratio analogue used by the R7 coupling experiment:

```
E_in  = sum_{i=0}^{127} inner[i]^2
E_out = sum_{i=0}^{127} outer[i]^2
T     = E_out / (E_in + E_out), or 0 when the denominator is zero.
```

This is a computational transmission metric, not a physical tunneling probability.

## 2. ABI

| Register | Meaning |
|---|---|
| `r1` | inner, 128 float32 |
| `r2` | outer, 128 float32 |
| `r3` | output, three float32: `E_in`, `E_out`, `T` |
| `r13` | 1 |
| return | `r1=1` |

Accumulation is in increasing index order; one accumulator per region. No host math.

## 3. Fixture

`mth/tests/mth_graph_transmission_128_test.nas` checks:

- `inner=outer=1` -> `E_in=E_out=128`, `T=0.5`;
- `outer=0` -> `T=0`;
- both zero -> `T=0`.

Local canonical run:

```
MTH GRAPH TRANSMISSION 128 PASS
7,147 steps, rc=3/HALT
```

## 4. Limitations

- 128 positions only.
- Energy is the unnormalized sum of squares; no mass, stiffness, or potential term.
- No finite/NaN validation of region values.
- `T` is an analogue metric, not a claim about quantum tunneling.
