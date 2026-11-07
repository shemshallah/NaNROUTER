# MTH K255 and C255 ring ABI

Status: source-written and locally executed with the canonical NaN0S toolchain; CI promotion pending.

## 1. K255 head-only baseline

`mth/nan16/mth_k255_laplacian.nas` implements the exact complete graph on the 255 local heads:

```
L = 255 I - J
(Lx)[i] = 255*x[i] - sum(x)
```

### ABI

| Register | Meaning |
|---|---|
| `r1` | input: 255 unsigned 16-bit payloads |
| `r2` | output: 255 signed two's-complement 32-bit payloads |
| `r13` | constant 1 |
| return | `r1=1` success, `r1=0` invalid input |

The kernel validates all 255 inputs before writing output. Input and output spans must not overlap. Every input payload must be in `[0,65535]`.

### Range proof

```
0 <= sum(x) <= 255*65535 = 16,711,425
0 <= 255*x[i] <= 16,711,425
|Lx[i]| <= 16,711,425 < 2^31
```

No rounding, saturation, floating point, or host arithmetic is used.

### Fixture

`mth/tests/mth_k255_laplacian_test.nas` checks the impulse oracle:

```
[1,0,...,0] -> [254,-1,...,-1]
```

and invalid-input atomicity. Local canonical run:

```
awk -f nan0s/tools/nmk.awk -v CMD=emit mth/tests/mth_k255_laplacian_test.nas > k255.nan
nan_cli --img k255.nan --steps 4000000 --serial
MTH K255 LAPLACIAN PASS
5,881 steps, rc=3/HALT
```

## 2. C255 head-ring Laplacian

`mth/nan16/mth_ring255_laplacian.nas` implements the undirected cycle over the 255 local heads:

```
(Lx)[i] = 2*x[i] - x[(i-1) mod 255] - x[(i+1) mod 255]
```

### ABI

| Register | Meaning |
|---|---|
| `r1` | input: 255 float32 payloads |
| `r2` | output: 255 float32 payloads |
| `r13` | constant 1 |
| return | `r1=1` success |

Input and output spans must not overlap. The kernel is a leaf routine and uses only native float32 operations.

### Fixture

`mth/tests/mth_ring255_laplacian_test.nas` checks:

```
impulse at 0 -> [2,-1,0,...,0,-1]
constant state -> 0
```

Local canonical run:

```
awk -f nan0s/tools/nmk.awk -v CMD=emit mth/tests/mth_ring255_laplacian_test.nas > ring255.nan
nan_cli --img ring255.nan --steps 4000000 --serial
MTH RING255 LAPLACIAN PASS
12,485 steps, rc=3/HALT
```

## 3. 255 + 1 ring layout

The head-only graph is C255. The NANNET node is mathematical ring position 255 and is not a head. The full ring has 256 readout positions:

```
positions 0..254 = heads
position 255     = NANNET port
```

The port attachment policy is versioned in `spec/ring-255.json` (digest `24f580ee4d4653b25c5bfd57221bcf111f6d339ef7704947d4d182d4bfe307dc`). The head-only C255 graph and the 256-position readout ring are separate objects; do not treat the port as a 256th head.

### 3.1 Port assembly

`mth/nan16/mth_ring255_port.nas` maps a 255-head float32 state plus one NANNET port scalar into 256 readout positions:

| Register | Meaning |
|---|---|
| `r1` | 255 head float32 values |
| `r2` | one NANNET port float32 value |
| `r3` | 256 ring readout float32 positions |
| `r13` | constant 1 |
| return | `r1=1` success |

`ring[0..254] = head[0..254]`; `ring[255] = port`. This is layout assembly only. Graph/port coupling is a separate versioned operator.

Fixture: `mth/tests/mth_ring255_port_test.nas` checks all-ones heads plus port `7.0`, then checks positions 0, 254, and 255. Local canonical run:

```
MTH RING255 PORT ASSEMBLE PASS
3,353 steps, rc=3/HALT
```

## 4. Next gates

1. Add these fixtures to `.github/workflows/mth-native-contract.yml`.
2. Add K255/C255 kernel digests to the capability registry.
3. Add a native port-coupling action that maps the 255-head state and the port scalar into the 256-position readout.
4. Keep the K256 ring-position baseline and the K255 head-only baseline distinct in all reports.
