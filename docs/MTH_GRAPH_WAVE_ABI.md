# MTH graph wave step ABI (float32 velocity Verlet)

Status: source-written and **native_verified** for the exact fixture described
below by a local NaN16 `nan_cli` run on 2026-11-06. This is local execution
evidence, not a CI claim. See sections 7 and 8.

## 1. Scope

This document freezes the ABI of the native NaN16 graph-wave step:

- Kernel: `mth/nan16/mth_graph_wave.nas`
- Entry point: `mth_graph_wave_step_f32`
- Fixture: `mth/tests/mth_graph_wave_test.nas`

The entry point performs one velocity-Verlet step for 256 graph positions. It
does not apply the graph operator, compute an acceleration, compute an energy,
or advance a clock. The caller supplies the acceleration `a = -H u` for the
**old** position `u`. A complete wave engine alternates this kernel with an
operator application that produces `a_next = -H u_next`.

Every scalar is one IEEE binary32 value stored in the 32-bit payload of one
NaN16 word. There is no Q16.16 scaling, saturation, hidden allocation, or
host-side arithmetic. The only floating-point operations are `FADD`, `FSUB`,
and `FMUL` executed by the NaN16 float unit, with normal IEEE
round-to-nearest-even behavior. There is no fused multiply-add and no
reordering.

## 2. Register ABI

`r13` must contain `1` (the canonical increment).

| Register | Meaning |
|---|---|
| `r1` | `u`, 256 float32 words (input) |
| `r2` | `v`, 256 float32 words (input) |
| `r3` | `a`, 256 float32 words, already equal to `-H u` (input) |
| `r4` | `u_next`, 256 float32 words (output) |
| `r5` | `v_next`, 256 float32 words (output) |
| `r6` | `dt`, one float32 scalar |
| `r7` | `gamma`, one float32 scalar |
| `r13` | `1` |
| `r1` on return | status: `1`, `0`, or `2` |

Return codes:

| `r1` | Meaning |
|---|---|
| `1` | success; both output spans written |
| `0` | invalid scalar parameter: `dt`, `gamma`, or the damping factor |
| `2` | invalid layout: a span cannot hold 256 words without wrapping, or two spans overlap |

The kernel clobbers `r1-r12` and `r14`; it preserves `r13` and does not use
`r15` as a data register. It is leaf-only: no helper calls, no static scratch,
no shared return slot.

## 3. Update equations

For `i = 0..255`, in increasing index order:

```text
half_dt = 0.5 * dt
t       = half_dt * a[i]
v_half  = v[i] + t
u_next  = u[i] + dt * v_half
v_next  = (v_half + t) * (1 - gamma*dt)
```

`half_dt` is computed once. `t` is computed once per element and reused for
both half-kicks. Reuse is bit-identical to evaluating `0.5*dt*a[i]` twice,
because the operands and operation order are identical. `u_next` is written
before `v_next`; this is safe because overlap is rejected in preflight.

The constants used by the kernel are the exact binary32 bit patterns:

| Value | Bits |
|---|---|
| `0.5` | `0x3F000000` |
| `1.0` | `0x3F800000` |

## 4. Preflight and atomicity

All checks below complete before the first `u_next` or `v_next` write:

1. **Span range.** Each base address must satisfy `base <= 0x003FFF00`, so
   `base + 255 <= 0x003FFFFF` and the 256-word span cannot wrap around the
   NaN16 address space.
2. **Disjointness.** The five spans are pairwise disjoint. Two inclusive spans
   `[A, A+255]` and `[B, B+255]` are rejected when they overlap. This also
   rejects output/output aliasing and input/output aliasing.
3. **Finiteness.** `dt` and `gamma` must have a finite binary32 exponent. The
   kernel shifts out the sign bit, extracts the eight exponent bits, and
   rejects exponent `0xFF` (infinity or NaN).
4. **Sign/domain.** `dt > 0` and `gamma >= 0`, tested with `FCMP`.
5. **Damping factor.** `d = 1 - gamma*dt` must be `>= 0`. Because `gamma >= 0`
   and `dt > 0`, the product cannot be negative; an overflow to `+inf` makes
   `d = -inf` and is rejected.

A rejected call therefore leaves both output spans, and every input span,
unchanged. The fixture checks sentinel words at representative indices
(including 0, 200, and 255) after the parameter and layout failures.

`gamma = -0.0` compares equal to zero and is accepted; its damping factor is
exactly `1.0`. `dt = -0.0` compares equal to zero and is rejected by the
`dt > 0` test. `d = +0.0` (exactly `gamma*dt = 1`) is accepted and kills the
velocity for that step.

## 5. Damping policy

A damping factor `d < 0` is **rejected**, not clamped. The same policy applies
to `gamma < 0`. Clamping would silently change the energy path and hide a bad
caller time step or coefficient; returning `0` with untouched outputs keeps
the failure explicit and atomic.

The discrete multiplier is exactly `d = 1 - gamma*dt`. This means the `gamma`
accepted by this ABI is the coefficient of the **discrete velocity scaling**.
If a caller is implementing the game-plan equation
`u'' + 2*gamma_ode*u' + H u = 0` with the common velocity-scaling velocity
Verlet variant, the mapping is `gamma_ABI = 2*gamma_ode`. The kernel does not
perform that mapping; it applies the ABI value literally.

Stability also depends on the operator: undamped velocity Verlet requires a
time step small enough relative to the largest eigenvalue of `H`. The kernel
never sees `H` or its spectrum and cannot check that condition. The caller must
choose a stable `dt`; this ABI only enforces `dt > 0` and `0 <= d <= 1`.

## 6. Energy semantics

The continuous wave energy for the game plan is:

```text
E(u, v) = 0.5*||v||^2 + 0.5*u^T H u
```

This kernel does **not** compute `E`, `H`, or `a_next`. It only performs the
kinematic step. The caller can compute the potential term from `u_next` only
after an operator pass supplies `a_next = -H u_next`.

- With `gamma = 0`, velocity Verlet is symplectic for a fixed symmetric `H`.
  It conserves a shadow energy to second order; finite float32 precision can
  still produce measured drift. This fixture does not measure a long-run energy
  residual.
- With `gamma > 0`, `d` lies in `[0, 1]`, so the final velocity scaling cannot
  increase the kinetic term at that instant. Total discrete energy over a run
  is not proven non-increasing by this kernel or this fixture; that requires a
  full operator plus integration test with a declared tolerance.
- If the supplied `a` is not `-H u` for the same `u`, the step is still a
  well-defined kinematic update but is not the stated wave equation. The kernel
  trusts `a` and does not validate it.

## 7. Exact fixtures

The fixture uses five fixed, pairwise-disjoint 256-word regions at word
addresses 2048, 2304, 2560, 2816, and 3072. `u` and `a` are initialized to
`1.0`, `v` to `0.0`, and the output regions to the integer sentinel `77`.
Runtime fills reset outputs and mutated inputs between cases.

| Case | Inputs | Assertion |
|---|---|---|
| A | `u=1, v=0, a=1, dt=1, gamma=0` | `u_next=1.5`, `v_next=1.0` at indices 0, 200, 255 |
| B | same, `gamma=0.5` | `v_next=0.5` at 0, 200, 255; `u_next=1.5` |
| C | `u=0, v=0, a=1, dt=1, gamma=0` | `u_next=0.5`, `v_next=1.0` |
| J | index 200: `u=2, v=1, a=2`; others uniform as case A | `u_next=4.0`, `v_next=3.0` at 200; index 0 stays `1.5/1.0` |
| K | index 0: `u=2, v=1, a=2`, `dt=0.5`, `gamma=0.25` | `u_next=2.75`, `v_next=1.75`; index 200 uniformly gives `1.125/0.4375` |
| L | `dt=1`, `gamma=1` | `d=0` accepted; `u_next=1.5`, `v_next=0` |
| D | `dt=0`, valid `gamma=0` | `r1=0`; outputs remain `77` |
| E | `dt=1`, `gamma=-0.5` | `r1=0`; outputs remain `88` |
| F | `dt=1`, `gamma=2.0` | `d=-1`; `r1=0`; outputs remain `99` |
| G1 | `dt=+inf` | `r1=0`; outputs remain `111` |
| G2 | `gamma=+inf` | `r1=0`; outputs remain `112` |
| H | `u_next` aliases `u`, valid scalars | `r1=2`; outputs and `u` unchanged |
| I | `u_next=0x003FFFFF`, valid scalars | `r1=2`; `v_next` unchanged |

### Note on the requested 1.5 oracle

The task statement said `u=0, v=0, a=1, dt=1, gamma=0` should produce
`u_next=1.5`. That is inconsistent with the specified equations:

```text
v_half = 0 + 0.5*1*1 = 0.5
u_next = 0 + 1*0.5   = 0.5
```

The exact `1.5` result corresponds to `u=1`:

```text
v_half = 0 + 0.5*1*1 = 0.5
u_next = 1 + 1*0.5   = 1.5
v_next = (0.5 + 0.5)*1 = 1.0
```

The fixture uses `u=1` for the requested `1.5/1.0` pair (case A) and adds
case C to pin the mathematically consistent `u=0` result at `0.5`. The kernel
was not changed to match the inconsistent oracle.

All case-A/B/C/J/K/L values are exactly representable in binary32, and the
sequence of operations above produces those bits with no rounding. Case J is a
non-uniform field: it proves that element 200 is read from and written to the
correct word rather than a constant broadcast of element 0. Case K exercises a
non-unit `dt` and `gamma`, and pins the resulting damping factor `0.875`. Case L
pins the accepted boundary `d=0`.

## 8. Evidence

Files and digests:

| File | SHA-256 |
|---|---|
| `mth/nan16/mth_graph_wave.nas` | `982d72402eadc1cbfcb05e9f0d17986089c627736c1f1629cb94eae82b2e56cc` |
| `mth/tests/mth_graph_wave_test.nas` | `a9d1e888b5a66c29e402b88de88fb9ab69023c577aacc859dc713a578c7293c4` |
| emitted image (`/data/data/com.termux/files/usr/tmp/opencode/wave.nan`) | `0f09310320acc5a9a3bcfa490bc593b3aa3ec716ff1b644fb7677bb964957fec` |

Assembly and execution command:

```sh
cd /data/data/com.termux/files/home/NaNROUTER
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=emit \
  mth/tests/mth_graph_wave_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/wave.nan
/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/wave.nan \
  --steps 4000000 --serial
```

Assembler output: `words 3342`. `CMD=check` reported `check: 0 mismatches`.

Observed execution output:

```text
[nan_cli] nan-text: 65088 steps, rc=3, pc=606, trap=''
MTH GRAPH WAVE STEP PASS
```

`rc=3` is the harness HALT result used by the existing MTH fixtures; the process
exit status was `0`, and the serial output contains `PASS`. No trap was
reported. This evidence covers only the exact fixture above.

## 9. Limitations

- One step only. No graph operator application, no `a_next`, no energy
  computation, no long-run conservation or damping test.
- `a` is trusted. Non-finite or NaN values in `a` propagate through IEEE
  arithmetic; they are not validated and output spans may then contain
  non-finite values.
- Fixed length 256, contiguous, word-index spans. No stride, tiling, paging, or
  variable vertex count.
- All five spans must be pairwise disjoint, including input/input pairs. The
  kernel rejects input alias pairs even though reading the same input twice
  would be numerically harmless; this keeps one simple layout contract.
- The fixture is exact-case, not randomized or differential. It does not
  establish rounding-error envelopes for arbitrary states.
- Local `nan_cli` evidence only. No CI run, digest registration, workspace
  binding, or dispatch claim is made here.
- The test image's data regions are below 64 KiB because the fixture loads
  label addresses with `MOVI`. The kernel itself accepts any in-range 22-bit
  word address in `r1-r5`.
