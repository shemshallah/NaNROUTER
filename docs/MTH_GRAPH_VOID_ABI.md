# MTH regularized void-potential ABI (float32 v1)

Status: source-written and **locally native-verified** for the exact fixture in
this document by a NaN16 `nan_cli` run on 2026-11-06. This is local execution
evidence, not a CI claim.

## 1. Scope

- Kernel: `mth/nan16/mth_graph_void.nas`
- Entry point: `mth_graph_void_potential`
- Fixture: `mth/tests/mth_graph_void_test.nas`
- Transformation: `RSS.POT.CORE.v1`, regularized core-potential form

The kernel evaluates the regularized inverse-square core potential at exactly
256 radial positions:

\[
V(r_i)=\frac{\alpha}{r_i^2+\varepsilon^2},\qquad i=0,\ldots,255.
\]

This is the `alpha/(r*r + eps*eps)` regularization. It is not the
`alpha/(r + eps)^2` variant and it is not the centrifugal renormalization
`RSS.POT.VOID.v1`.

Every scalar is one IEEE-754 binary32 value stored in the 32-bit payload of
one NaN16 word. There is no Q16.16 scaling, saturation, table lookup, hidden
allocation, or host-side arithmetic. The only floating-point operations are
`FMUL`, `FADD`, and `FDIV` executed by the NaN16 float unit with IEEE
round-to-nearest-even behavior. There is no fused multiply-add and no
reassociation. Integer `ADD`, `SUB`, and `CMP` are used only for pointer
increments and loop control, never to compute a scalar value.

## 2. Register ABI

`r13` must contain `1` (the canonical increment). `r0` is the zero constant.

| Register | Meaning |
|---|---|
| `r1` | radius array, 256 float32 words (input) |
| `r2` | `alpha`, one float32 scalar (input) |
| `r3` | `epsilon`, one float32 scalar (input) |
| `r4` | output array, 256 float32 words (written only after full preflight) |
| `r13` | `1` |
| `r1` on return | `1` success, `0` invalid parameter or radius |

The kernel is leaf-only: no helper calls, no static scratch, no shared return
slot. It clobbers `r2-r12` conservatively and preserves `r13`. Input and
output spans must not overlap and each must contain 256 words. The kernel does
not check overlap or address-wrap; that is a caller precondition, as in the
other MTH graph kernels.

## 3. Validation

All validation completes before the first `ST` to the output span:

1. `alpha >= 0` and `alpha` is finite.
2. `epsilon > 0` and `epsilon` is finite.
3. For every `i` in `[0,255]`: `radius[i] >= 0` and `radius[i]` is finite.

The comparisons use `FCMP` only:

- `FCMP value, 0.0` followed by a `[LT]` guard rejects negative values.
- `FCMP value, +inf` followed by a `[LT]` guard accepts only values strictly
  less than positive infinity. Equality with `+inf` falls through to the
  invalid return.
- `FCMP` is unordered for NaN: the VM sets `(Z,L)=(1,1)`, which is the state
  no ordinary predicate matches. A NaN therefore skips both the `[LT]` accept
  branch and the `[LT]` reject branch and reaches the invalid return.
- Negative zero compares equal to `+0.0`, so `-0.0` is accepted as zero for
  `alpha` and radius. It is rejected for `epsilon` because `-0.0 > 0` is
  false.

Return values:

| `r1` | Meaning |
|---|---|
| `1` | success; all 256 output words written |
| `0` | invalid `alpha`, invalid `epsilon`, or at least one invalid radius |

On every invalid return the output span is unchanged. The complete radius
preflight and both scalar checks happen before the apply loop; the kernel does
not stream-write outputs while validating.

## 4. Float constants

All constants are raw binary32 bit patterns assembled from `MOVI` (low 16
bits) and `MOVHI` (high 16 bits). No decimal conversion occurs at run time.

| Value | Binary32 bits | Use |
|---|---|---|
| `0.0` | `0x00000000` | lower comparison bound |
| `+infinity` | `0x7F800000` | finite upper bound |
| `1.0` | `0x3F800000` | fixture `alpha`, `epsilon`, expected `V(0)` |
| `2.0` | `0x40000000` | fixture radius `r[2]` |
| `0.5` | `0x3F000000` | expected `V(1)` with `alpha=eps=1` |
| `0.2` | `0x3E4CCCCD` | expected `V(2)` with `alpha=eps=1` |

The expected `0.2` word is the correctly rounded binary32 result of
`1.0 / 5.0`, not a decimal approximation.

## 5. Numeric contract and limitations

For each position the kernel evaluates, in this order:

```text
r2      = FMUL(r, r)
denom   = FADD(r2, FMUL(eps, eps))
V       = FDIV(alpha, denom)
```

`eps*eps` is computed once per call. The exact result depends on the VM's
binary32 rounding, including subnormal and infinity behavior.

Limitations, stated explicitly:

- Output is not guaranteed finite for every input that passes validation. A
  legal positive `epsilon` whose square underflows to zero, or an extremely
  small denominator, can produce an infinity under IEEE-754 rules. A caller
  that requires finite outputs must bound `alpha`, `epsilon`, and radius.
- The kernel does not detect input/output overlap or address wrap.
- The kernel does not clamp, saturate, or canonicalize NaNs produced by
  arithmetic; it stores the float unit's result payload.
- This fixture covers the regularized core-potential formula only. It does
  not cover the centrifugal renormalization, radial eigensolve, Dirichlet or
  Robin boundary conditions, or wave evolution.
- This is local `nan_cli` evidence for the exact fixture below. It is not a CI
  result and does not extend to other parameter ranges.

## 6. Fixture coverage

`mth/tests/mth_graph_void_test.nas` uses fixed, non-overlapping regions:

- radii: words `512..767`
- output: words `768..1023`
- strings: from word `1024`

The fixture performs these checks:

1. With `alpha=1.0`, `epsilon=1.0`, and 256 radii where `r[0]=0.0`,
   `r[1]=1.0`, `r[2]=2.0`, and all others are `0.0`:
   - `output[0] == 0x3F800000` (`1.0`),
   - `output[1] == 0x3F000000` (`0.5`),
   - `output[2] == 0x3E4CCCCD` (`0.2`),
   - `output[3..255] == 0x3F800000` (`1.0`).
2. With `alpha=0.0`, all 256 outputs are exactly `0x00000000`.
3. With `epsilon=0.0`, the call returns `0` and all 256 output words retain a
   `0x12345678` sentinel written before the call.
4. With `radius[0]=-1.0`, the call returns `0` and all 256 output words retain
   the sentinel.
5. Additional rejection checks cover `radius=+inf`, `radius=NaN`,
   `alpha=+inf`, `alpha=NaN`, `alpha=-1.0`, `epsilon=+inf`, `epsilon=NaN`,
   and `epsilon=-1.0`. Each must return `0` and leave the sentinel intact.

## 7. Evidence

Canonical local commands, run from the repository root:

```sh
mkdir -p /data/data/com.termux/files/usr/tmp/opencode
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=emit mth/tests/mth_graph_void_test.nas > /data/data/com.termux/files/usr/tmp/opencode/void.nan
/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli --img /data/data/com.termux/files/usr/tmp/opencode/void.nan --steps 4000000 --serial
```

Observed output:

```text
words 1040
[nan-cli] nan-text: 20623 steps, rc=3, pc=221, trap=''
MTH GRAPH VOID POTENTIAL PASS
```

`rc=3` is the expected HALT status, and the serial output contains the
required `PASS` line. The assembler/disassembler consistency check also
reported no mismatches:

```sh
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=check /data/data/com.termux/files/usr/tmp/opencode/void.nan
# check: 0 mismatches
```

Kernel source SHA-256:

```text
b974e4aaacd61964edd81f9a697f0068a5d9c9ddbe6dfea47c4b028799262923  mth/nan16/mth_graph_void.nas
```

Fixture source SHA-256:

```text
699238587de502cf7bdb6c940e15aa5449f7b1098ce75415e1091c0a9fbcd914  mth/tests/mth_graph_void_test.nas
```
