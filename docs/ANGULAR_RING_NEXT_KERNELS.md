# Angular ring addressing and the next native kernels

**Status:** native NaN16 sources and fixtures verified locally. The six new
kernels are registered in `spec/wave-capabilities.json`; CI promotion is the
next step after the local batch. This document is the ABI and non-claim record.

## 1. Angular ring addressing

The ring has:

```text
real lanes       0..254
NANNET0 position 255
rotation modulus 255
```

`mth.ring.angular_map.u32`:

| Register | Meaning |
|---|---|
| `r1` | real lane, `0..254` |
| `r2` | signed angular offset |
| `r3` | mapped real lane, `0..254` |
| `r4` | `255`, the invariant NANNET0 position |
| `r5` | `1`, real-lane result flag |

The offset is reduced modulo 255 and applied only over real lanes. NANNET0 is
never returned as a rotated lane. A request for lane 255 rejects; it does not
rotate the port.

This is a coordinate operation, not a route authorization. Point 0
(`BS0:0`/`BSR0`) remains the transport ingress and is not a ring position.

The fixture exhaustively covers all 255 real lanes with offsets `-255..255`,
checks known wraps, checks that NANNET0 is always returned as 255, and rejects
255/256/`0xFFFFFFFF`.

## 2. Native twiddle table

`mth.trig.twiddle256.f32`:

```text
cos_out[k] = cos(2*pi*k/256)
sin_out[k] = sin(2*pi*k/256)
```

Inputs: `r1=cos[256]`, `r2=sin[256]`, `r3=scratch[4]`. Each angle is generated
from the integer `k` and the binary32 step `0x3CC90FDB`; it calls the native
sincos routine. The fixture checks independent anchors, all 256 Pythagorean
identities, conjugate symmetry, and k=255.

This removes a caller-supplied host twiddle table from the spectral path.

## 3. Oscillatory write gates

`mth.mirror.cycle.phase_gate16.f32`:

```text
gate[c] = clamp(0.5*(1 + sin(position*frequency[c] + phase[c])), 0, 1)
```

Inputs: `r1=position` (0..4096), `r2=frequency[16]`, `r3=phase[16]`,
`r4=out[16]`, `r5=scratch[6]`. All angles are preflighted before any output
store. The output is clamped to exactly `[0,1]`, so it is directly accepted by
the cycle trainer's gate argument.

The gate is a testable oscillator, not proof that oscillation helps.

## 4. Cycle-bank retention

`mth.mirror.cycle.retain.f32` blends a live bank toward a retained source bank:

```text
current_edge = current_edge + gain * (source_edge - current_edge)
```

for all 16×16 channels, all three triangle edges, and both lanes.

Inputs: `r1=current base`, `r2=source base`, `r3=gain in [0,1]`. The two
32-head bank spans must be disjoint; bases are 1..224. `gain=0` leaves the
current bank unchanged, `gain=1` copies the source bank, and intermediate
values retain a mixture. Both lanes are blended with the same operation, so a
mirrored source and a mirrored current remain mirrored.

The fixture checks midpoint, no-op, copy, mirror signs, and rejection of bad
bases, overlap, negative gain, and gain above one.

## 5. Contradiction-preserving evidence

`mth.mirror.cycle.contradiction.f32` takes nonnegative support and oppose
strengths and returns:

```text
conflict = min(support, oppose)
balance  = support - oppose
support  and oppose preserved as exact payload copies
```

It does not send the losing side to zero and does not convert either number to
a truth value. `conflict` is high only when both sides are present. The fixture
checks exact values, symmetry, non-collapse, negative/non-finite rejection, and
recovery.

## 6. Attention/value mixing

`mth.attention.mix16.f32` computes:

```text
out[c] = sum(p=0..15) weight[p] * values[p*16+c]
```

Inputs: `r1=weights[16]` (finite, nonnegative), `r2=values[16][16]`,
`r3=out[16]`. The weights are caller-supplied; the kernel does not normalize
or force a single winner. That preserves multiple candidates until the caller
chooses.

This is the readout half of candidate competition, **not** a full Q/K/V
projection or transformer attention block. The fixture checks one-hot
selection, uniform and weighted mixing, zero weights, range rejection, and
output atomicity.

## 7. Phase binding

`mth.trig.rotate.f32` remains the native phase-bind primitive:

```text
x' = x*cos(a) - y*sin(a)
y' = x*sin(a) + y*cos(a)
```

A bank-level bind is a composition of rotate with cycle read/write; it is not a
second geometry authority.

## 8. Evidence status

| Kernel | Fixture | Steps |
|---|---|---:|
| `mth.ring.angular_map.u32` | PASS | 4,757,984 |
| `mth.trig.twiddle256.f32` | PASS | 40,725 |
| `mth.mirror.cycle.phase_gate16.f32` | PASS | 13,926 |
| `mth.mirror.cycle.retain.f32` | PASS | 104,103 |
| `mth.mirror.cycle.contradiction.f32` | PASS | 785 |
| `mth.attention.mix16.f32` | PASS | 34,231 |

## 9. Native phase-system integration fixture

`mth/tests/mth_phase_system_test.nas` is a **local integration fixture**, not
a new kernel or a manifest entry. It composes the new primitives in one guest
run:

```text
twiddle256 -> phase_gate16 -> cycle_train_step x8
           -> cycle_predict16 -> attention_mix16
           -> cycle_retain -> predict
           -> contradiction pair -> angular ring map
```

It checks that the native twiddle table, oscillatory gates, phase-gated cycle
training, readout, candidate mixing, retention, contradiction pair, and
NANNET-preserving angular map compose without host trigonometry. Observed
local marker:

```text
MTH PHASE SYSTEM PASS
288,659 guest steps
```

This fixture is deliberately outside the canonical 142-fixture runner and
kernel manifest so the manifest remains a kernel registry rather than treating
a composition test as a new mathematical authority. A separate
`.github/workflows/phase-system-integration.yml` workflow assembles and runs
it directly with the pinned NaN0S toolchain; run `42638938887` passed.

## 10. Non-claims


- NANNET0 is not rotated and not replaced by point 0.
- Oscillatory gates are not proven to improve learning.
- Retention is a numerical consolidation primitive, not semantic truth.
- Contradiction output is not a calibrated probability.
- Attention mixing is not full attention or a language model.
- Twiddle generation is not a proof that a DFT implementation is correct.
- Local fixtures are not CI verification; CI is not a live deployment.
