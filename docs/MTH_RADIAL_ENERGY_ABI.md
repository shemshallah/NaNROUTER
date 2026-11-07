# MTH radial energy and localization (float32 v1)

Status: source-written and **locally native-verified** for the exact
working-tree fixture in this document with the canonical NaN0S `nmk.awk` /
`nan_cli` toolchain on 2026-11-07. The current fixture passes in 61,373 guest
steps. Canonical CI run `42395520794` (head `4b823e5`) executed the previous
fixture revision (61,355 steps, fixture SHA-256 `b089d0...`) successfully; the
ABI-preservation revision documented here is local-only and awaits the next CI
run. GLT page-limit enforcement remains separate.

## 1. Scope

- Kernel: `mth/nan16/mth_radial_energy.nas`
- Entry point: `mth_radial_energy`
- Fixture: `mth/tests/mth_radial_energy_test.nas`
- Stage: R2 radial block, scalar energy/localization companion to the
  tridiagonal action kernel
- Operation: quadratic energy and peak localization of a 256-vector for the
  symmetric tridiagonal `T(diag, offdiag)`

The kernel evaluates exactly:

```text
energy       = sum_{i=0}^{255} diag[i]*x[i]^2
             + 2 * sum_{i=0}^{254} offdiag[i]*x[i]*x[i+1]
localization = max_{0<=i<=255} x[i]^2 / sum_{i=0}^{255} x[i]^2
```

with `localization = +0.0` when the denominator is zero.

This is not `y = T x`, not an eigensolver, not an inverse, and not a radial
source term. It complements `mth/nan16/mth_radial_tridiagonal.nas`: both
kernel families read the same `diag` (256 words), `offdiag` (255 words), and
`x` (256 words) layout and inherit the same caller-folded boundary convention
(section 4). The energy kernel does not call the action kernel and does not
need a `y` span.

## 2. ABI

| Register | Meaning |
|---|---|
| `r1` | `diag`, 256 float32 words (input) |
| `r2` | `offdiag`, 255 float32 words (input); `offdiag[i]` couples `x[i]` and `x[i+1]` |
| `r3` | `x`, 256 float32 words (input) |
| `r4` | `energy_out`, one float32 word (output) |
| `r5` | `localization_out`, one float32 word (output) |
| `r13` | `1` (canonical increment) |
| `r1` on return | `1` (success) |
| clobbers | `r1` (return value), `r6`-`r12`, `r14` |
| preserved | `r0`, `r2`-`r5`, `r13`, `r15` |

`r0` is the zero constant and `r13` must be `1`.

The kernel is leaf-only: it contains no `CALL`, no helper, no static scratch,
and no return slot. `r15` is not modified. Inputs are read-only; the five
spans must be distinct and non-overlapping, each with the stated length. The
kernel does not check overlap, length, or address wrap; those are caller
preconditions, as in the other MTH graph kernels.

All arithmetic is IEEE-754 binary32 in NaN16 `FMUL` / `FADD` / `FDIV`.
Integer `ADD`, `SUB`, `CMP`, and `JMP` are used only for pointer movement and
loop control. There is no discrete/tabulated approximation, Q-format scaling,
saturation, or host-side arithmetic.

## 3. Numeric contract

Accumulation is deterministic and uses the same energy accumulator for both
passes:

| Pass | Index order | Per-index operations |
|---|---|---|
| 1 | `i = 0..255` | `xi2 = FMUL(x[i],x[i])`; `sumsq = FADD(sumsq,xi2)`; max update by `FCMP(xi2,max)` + ordered `GT` branch; `term = FMUL(diag[i],xi2)`; `energy = FADD(energy,term)` |
| 2 | `i = 0..254` | `term = FMUL(offdiag[i],x[i])`; `term = FMUL(term,x[i+1])`; `doubled = FADD(term,term)`; `energy = FADD(energy,doubled)` |

The diagonal sum is therefore accumulated first and the coupling sum second,
each in increasing index order. One energy accumulator and one sum-of-squares
accumulator are used; the running maximum is one scalar. `FADD(term,term)` is
an exact doubling in binary32 (except overflow), not a multiply by a rounded
literal.

Each product is one rounded `FMUL`; each accumulation is one rounded `FADD`;
the final localization is one rounded `FDIV`. There is no fused
multiply-add, reassociation, hidden precision, or reordering. Results are
deterministic for a given input bit pattern but are not bitwise identical to
an FMA-based, interleaved, or differently ordered implementation.

Tie handling for the maximum is deterministic: the first index that attains
the largest `x[i]^2` remains the maximum. The ratio itself is unaffected by
which tied index supplied the numerator.

If `sumsq` is exactly `+0.0`, the kernel stores `+0.0` in `localization_out`
and does not divide. Floating-point underflow can make nonzero subnormal
inputs square to zero, so an all-subnormal vector reaches the same branch; the
kernel reports the float32 result rather than a higher-precision one.

NaN/Inf input policy is caller-side: the kernel propagates whatever the float
unit produces and does not validate or canonicalize inputs. In particular, a
NaN `sumsq` follows the divide path and produces a NaN localization.

## 4. Boundary convention and the constant-vector case

This kernel inherits the descriptor-level convention of
`MTH_RADIAL_TRIDIAGONAL_ABI.md`: the caller folds the inner boundary into
`diag[0]` and `offdiag[0]`, and the outer boundary into `diag[255]` and
`offdiag[254]`, before dispatch. The kernel adds no boundary term of its own
and branches on no boundary kind.

For the path operator `diag[i] = 2.0`, `offdiag[i] = -1.0`, every interior
row `1 <= i <= 254` contributes zero to `x^T T x` for `x[i] = 1.0`, but the
two boundary rows contribute one each:

```text
(T x)[0]   = 2*1 + (-1)*1             = 1
(T x)[i]   = (-1)*1 + 2*1 + (-1)*1    = 0,  1 <= i <= 254
(T x)[255] = (-1)*1 + 2*1             = 1
x^T T x    = sum_i x[i]*(T x)[i]      = 1 + 0 + ... + 0 + 1 = 2
```

Equivalently, the diagonal terms sum to `256*2 = 512` and the doubled
off-diagonal terms sum to `2*255*(-1) = -510`, giving `512 - 510 = 2`.

Therefore the correct quadratic energy for this 255-coupling path fixture is
`2.0`, not `0.0`. An energy of zero would require a periodic ring with a
256th coupling `offdiag[255] = -1`, which this ABI cannot represent. The
fixture asserts `2.0`; the interior cancellation is also exercised by the
linear-ramp case in section 6, whose interior rows are exactly zero and whose
energy is the boundary-only value `256*257 = 65,792`.

## 5. Memory budget

| Object | NaN16 words | Bytes |
|---|---:|---:|
| `diag` | 256 | 2,048 |
| `offdiag` | 255 | 2,040 |
| `x` | 256 | 2,048 |
| `energy_out` | 1 | 8 |
| `localization_out` | 1 | 8 |
| **Working set** | **769** | **6,152** |

The fixture image is 2,060 words (16,480 bytes), including code, helpers,
data, and strings. It fits both the historical 512 KiB (65,536-word) guest
budget and the current 1 MiB guest budget with no special paging.

## 6. Fixture coverage

`mth/tests/mth_radial_energy_test.nas` uses fixed, non-overlapping regions:

| Label | Word address |
|---|---:|
| code and helpers | 0 |
| `diag` | 1,024 |
| `offdiag` | 1,280 |
| `x` | 1,536 |
| `energy_out` | 1,792 |
| `localization_out` | 1,793 |
| pass/fail strings | 2,048 |

Each case checks the kernel return value (`r1 == 1`) and both scalar outputs.
Expected values are derived from closed forms; the fixture computes them with
native `CVTIF` / `FADD` / `FMUL` / `FDIV` and does not use host math.

| # | Input | Expected energy | Expected localization | Check |
|---|---|---:|---:|---|
| 1 | `diag=2`, `offdiag=-1`, `x=1` | `2.0` | `1/256` | exact payloads |
| 2 | same operator, `x=e0` | `2.0` | `1.0` | exact payloads |
| 3 | same operator, `x=e128` | `2.0` | `1.0` | exact payloads |
| 4 | same operator, `x=0` | `0.0` | `0.0` | exact payloads; zero-denominator path |
| 5 | same operator, `x[i]=(i mod 7)-3` | `1524.0` | `9/1022` | energy exact; ratio tolerance `2^-20` |
| 6 | same operator, `x[i]=i+1` | `65,792.0` | `65536/5625216` | energy exact; ratio tolerance `2^-20` |
| 7 | `diag[i]=i+1`, `offdiag[i]=-1/-2` alternating, `x=1` | `32,132.0` | `1/256` | exact payloads |

Closed forms:

- Case 1: interior rows cancel; two boundary rows contribute 1 each.
- Case 5: `sum x^2 = 1022`, `max x^2 = 9`, `sum x[i]*x[i+1] = 260`, so
  `energy = 2*1022 + 2*(-1)*260 = 1524`; `localization = 9/1022`.
- Case 6: `y[0]=0`, `y[255]=257`, interior `y=0`; `energy = 256*257`.
  `sum x^2 = sum_{k=1}^{256} k^2 = 5,625,216`, `max x^2 = 65,536`.
- Case 7: `sum diag = 256*257/2 = 32,896`; `sum offdiag = 128*(-1) +
  127*(-2) = -382`; `energy = 32,896 + 2*(-382) = 32,132`.
- Cases 1, 2, 3, 6, and 7 have exactly representable integer expectations;
  cases 5 and 6 use the native tolerance helper for their non-power-of-two
  localization ratios.
- After case 1 the fixture also checks ABI preservation: `r2`-`r5` still hold
  the `offdiag`, `x`, `energy_out`, and `localization_out` pointers, and
  `r13` is still `1`.

The required success marker is:

```text
MTH RADIAL ENERGY PASS
```

## 7. Local evidence

Commands, run from the repository root:

```sh
mkdir -p /data/data/com.termux/files/usr/tmp/opencode
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=emit \
  mth/tests/mth_radial_energy_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/radial_energy.nan
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=check \
  /data/data/com.termux/files/usr/tmp/opencode/radial_energy.nan
/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/radial_energy.nan \
  --steps 5000000 --serial
```

Observed output (streams shown separately):

```text
emit stderr:  words 2060
check stderr: check: 0 mismatches
run stdout:   MTH RADIAL ENERGY PASS
run stderr:   [nan-cli] nan-text: 61373 steps, rc=3, pc=396, trap=''
```

`rc=3` is `NAN_HALTED` from the fixture's `HALT`; the trap string is empty and
the shell exit status is `0`. The emitted `.nan` text file is 68,419 bytes;
the loaded guest image is 2,060 words (16,480 bytes).

Kernel source SHA-256:

```text
a5199fc91d0d3e2eaa7283dc987fa4a3d0a7399a17fc7e917cf38642fedd6f36  mth/nan16/mth_radial_energy.nas
```

Fixture source SHA-256:

```text
8e719a5fb0fe8fcce6aed24023dd1b17641069575fa553ea11c8ce5a728d9739  mth/tests/mth_radial_energy_test.nas
```

The shared fixture runner (maintained outside this task and not edited here)
also contains an entry for `radial_energy`; it confirms the same result:

```sh
python3 tools/run_mth_fixtures.py --only radial_energy
# [PASS] radial_energy: PASS steps=61373 marker=MTH RADIAL ENERGY PASS
# 1/1 fixtures passed
```

As an independent review check outside the execution path, a host-side Python
`struct` float32 model reproduced all seven expected energies exactly and
reproduced the two tolerance-checked localization ratios bit-for-bit. That
model was used only to audit the fixture mathematics; it is not part of the
kernel, fixture, oracle, or guest execution.

The shared `.github/workflows/mth-native-contract.yml` already contains
assemble/execute steps for this fixture (maintained outside this task and not
edited here). Canonical CI run `42395520794` (head `4b823e5`, 2026-11-07)
executed the previous committed fixture revision at 61,355 steps; its fixture
SHA-256 was
`b089d0044762e3b3616b848d52d8431819ea2d1fcfbbf6298fb0a18cd1e008ba`. The current
revision adds the `r2`-`r5`/`r13` preservation checks and is local-only at
61,373 steps, pending the next CI run. GLT page-limit enforcement remains
separate. This task did not modify shared files; the evidence above is local
`nmk.awk` / `nan_cli` execution plus the cited CI run for the prior revision.

## 8. Limitations

- Symmetric tridiagonal path operator only: 256 diagonal words and 255
  couplings. There is no ring wrap, eigensolve, inverse, deflation, radial PDE
  solve, or source term.
- Boundary convention is the caller's `diag`/`offdiag`; this kernel parses no
  boundary descriptor and adds no boundary term of its own.
- No overlap, alignment, length, NaN/Inf, underflow, or finite-result
  validation. Those are caller preconditions. The kernel does not
  canonicalize a NaN result.
- `r13` must be `1`; a different value changes pointer arithmetic and loop
  counts.
- One serial accumulator for the whole energy (diagonal pass first, coupling
  pass second), so results are not bitwise identical to FMA, interleaved, or
  reordered implementations.
- `localization` here is the specified peak fraction `max x[i]^2 / sum
  x[i]^2`, not a participation ratio or inverse participation ratio.
- A zero denominator means exactly `+0.0` after float32 accumulation
  (including underflow to zero), not a symbolic "x is exactly zero" test.
- The constant-vector path fixture has energy `2.0`, not `0.0`; section 4
  records why. A zero-energy constant mode requires a periodic ring
  representation that is outside this ABI.
- Local evidence for the current revision; canonical CI run 42395520794
  covered the prior fixture revision (`b089d0...`). GLT 1 MiB page-limit
  enforcement remains pending.
