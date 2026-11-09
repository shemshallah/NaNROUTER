# Trigonometry in the native 0xNaN system

**Status:** native NaN16 primitives implemented and locally verified. This
document records the useful roles of trigonometry, the exact native kernels,
and the boundary between implemented evidence and proposed experiments.

## Why trigonometry belongs here

The mirror universe is a relational object, but many of its strongest
operations are phase operations:

- a pair circulation is a directed quantity that can be read in either
  orientation;
- a ring lane is cyclic, so a rotation is the natural address change;
- a graph Fourier mode is a complex phase;
- a wave state is an oscillator;
- a relative position in a token sequence can be encoded as a rotation;
- a memory write can be gated by an oscillatory eligibility trace;
- a gauge change is additive, while a *phase closure* test is trigonometric.

The native layer already had caller-supplied DFT twiddles and wave kernels.
The missing piece was in-guest sine/cosine: without it the host had to supply
twiddles or phases, which violates the no-host-math rule. The new
`mth.trig.sincos.f32` closes that gap.

## Implemented native primitives

### `mth.trig.sincos.f32`

ABI: `r1 = angle`; success `r1=1, r2=sin, r3=cos`; rejection `r1=0, r9=1`
(non-finite) or `r9=2` (`|angle| > 128`).

Implementation:

- binary32 range reduction by `2/pi` and `pi/2`;
- nearest-quadrant reduction, so the polynomials see `|r| <= pi/4`;
- degree-9 odd sine and degree-10 even cosine Horner forms;
- exact sign-bit quadrant application;
- no host sin/cos, no lookup table, no static storage, no CALL.

Declared component tolerance: **2e-5** on the accepted domain. Measured
worst-case offline float32 simulation near `|angle|=128` is about
`1.04e-5`; small angles are much tighter. The fixture checks anchors,
quadrants, symmetry, the Pythagorean identity, and rejection.

### `mth.trig.rotate.f32`

Applies `exp(i*a)` to a two-component vector:

```text
x' = x*cos(a) - y*sin(a)
y' = x*sin(a) + y*cos(a)
```

It uses `mth.trig.sincos.f32`, preserves norm up to binary32 roundoff, and
writes outputs only after a successful sincos call. The fixture checks quarter
turns, `pi/4`, norm preservation, inverse rotation, and atomic rejection.

### How these connect to existing kernels

| Existing surface | Trigonometric use |
|---|---|
| `mth.graph.dft256/255` | Caller can now generate twiddles in-guest with `sincos`, instead of embedding a host table. |
| `mth.phase_coherence` | Phase differences and closures can be formed from native sin/cos pairs. |
| `mth.graph.wave`, ring wave | Harmonic oscillator steps can use exact rotations for the undamped mode. |
| `mth.mirror.cycle.train_step` | A future phase-gated eligibility trace can modulate the per-channel write gate. |
| `mth.mirror.cycle.predict16` | A future complex readout can rotate each circulation into a shared phase frame before summation. |
| `mth.retrieval.top1` | A future phase-bind/retrieve path can score by real part or phase alignment. |
| 255-lane ring / NANNET0 | A ring rotation is an angular address change; phase-coded lane schedules can be generated without host math. |

## The deep design space

### 1. Rotary positional phase

For each pair of channels `(2i, 2i+1)`, rotate a query/key by

```text
theta(i, position) = position / base^(2i/d)
```

using `mth.trig.rotate.f32`. The dot product of two rotated vectors depends on
their relative position, not their absolute positions. This is the standard
RoPE idea, but the rotation happens in the native guest rather than in host
PyTorch. It is a natural fit for a sequence controller because it is exactly a
norm-preserving plane rotation.

Open work: implement a batched `mth.trig.rope16.f32` kernel and compare it
against a conventional learned absolute-position baseline of matched size.

### 2. Complex-valued mirror cycles

A circulation can be represented as a complex number `F = |F| exp(i phi)`.
Writing a phase rotates the stored evidence; reading accumulates the real part
after phase alignment. This gives interference and superposition without
changing the physical triangle layout. The danger is that a complex pair uses
two channels, so the 16×16 adapter becomes an 8×8 complex adapter unless the
channel budget grows.

Open work: a `mth.mirror.cycle.phase_bind.f32` kernel, with the same triangle
address geometry and a phase scratch array.

### 3. Native twiddle generation

`mth.graph.dft256` currently takes a prebuilt twiddle table. With sincos, a
guest can fill `W_re[k]=cos(2*pi*k/256)`, `W_im[k]=-sin(2*pi*k/256)` directly.
This removes the last host-supplied numerical table from the spectral path.
The table should be generated once into a caller-owned 512-word span, not
recomputed inside the DFT inner loop.

Open work: `mth.trig.twiddle256.f32` with a caller-supplied table and an
optional recurrence mode.

### 4. Oscillatory eligibility traces

A content-dependent write can be gated by

```text
gate(t, c) = 0.5 * (1 + sin(omega_c * t + phi_c))
```

so different channels have different write windows. This is not proven to
improve learning; it is a testable hypothesis. The native train step already
accepts a per-channel gate, so the only missing piece is a native gate
generator. The gate must remain in `[0,1]`; the train step rejects otherwise.

### 5. Phase-closure evidence

For a directed triangle, gauge changes cancel in the circulation. For a
quadrilateral or longer cycle, the sum of phases around a closed loop is a
geometric invariant. Trigonometry gives a way to test phase closure that is
different from raw edge matching:

```text
closure = |sum_edges angle(edge)| mod 2*pi
```

This could distinguish consistent evidence from contradictory cycles without
forcing every cycle to zero. It is a proposed experiment, not a current claim.

### 6. Spectral graph memory

The mirror graph has 256 heads and 32,640 pairs. A native graph Fourier
transform can rotate evidence into a spectral basis, filter it, and rotate it
back. The existing DFT/laplacian/filter kernels are the arithmetic base; sincos
supplies the phases. The key discipline is to keep the transform in the guest
and to compare against a matched spatial baseline, not to assume spectral is
better.

### 7. Ring addressing and NANNET routing

The 255 real lanes plus NANNET0 form a cyclic address space. An angular offset
can implement a deterministic lane rotation without a host lookup table. This
is useful for fair scheduling, but it must not break the fixed NANNET0 ring
position. The native route map remains the authority; trig only generates an
offset.

## The learning synthesis

The Round 039 result rules out "make the fixed cycle adapter bigger." The
useful synthesis is a state transition:

```text
prediction[c] = sum_d x[d] * CycleFlux(d,c)
error[c]      = target[c] - prediction[c]
delta(d,c)    = lr * gate[c] * error[c] * x[d]
Write:  edge(0,a,c)  += delta/3
        edge(a,b,c)  += delta/3
        edge(0,b,c)  -= delta/3
Read:   h(t+1) = Reason(h(t), prediction)
```

`mth.mirror.cycle.train_step.f32` and `mth.mirror.cycle.predict16.f32`
implement the Write and CycleRead halves in NaN16. The native fixture trains a
one-hot mapping for nine steps, requires strictly decreasing squared error,
checks predictions above 0.8, and verifies the mirror lane invariant. This is
a real native learning primitive, not a claim of open-domain intelligence.

The next fair experiment must give the conventional baseline the same episode
memory, the same copied evidence, and the same gauge-invariant feature
treatment. Otherwise a win would only show that one model got more information.

## Guardrails

- No host sin/cos, twiddle, rotation, or expected numerical result at runtime.
- A host reference may be used only as a test oracle.
- Reject non-finite angles and angles outside the declared reduction domain;
  never silently wrap.
- Keep phase operations norm-preserving where the theory requires it.
- Keep gauge transport and phase closure as separate tests.
- Treat every trig-gated learning idea as an experiment with a matched
  baseline, not as a proven advantage.
- Preserve the one 8 MiB universe, 255 lanes plus NANNET0, six ring slots,
  one active runner, and the 7 GiB ceiling.

## Evidence status

| Item | Status |
|---|---|
| `mth.trig.sincos.f32` | native source + fixture locally verified |
| `mth.trig.rotate.f32` | native source + fixture locally verified |
| `mth.mirror.cycle.train_step.f32` | native source + fixture locally verified |
| `mth.mirror.cycle.predict16.f32` | native source + fixture locally verified |
| RoPE/attention integration | proposed |
| complex mirror cycles | proposed |
| native twiddle table generation | implemented: `mth.trig.twiddle256.f32` |
| oscillatory gates | implemented: `mth.mirror.cycle.phase_gate16.f32` |
| phase closure / complex mirror cycles | proposed |
| fair geometric-vs-conventional learning comparison | not yet run |
