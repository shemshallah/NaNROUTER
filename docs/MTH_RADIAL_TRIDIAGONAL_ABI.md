# MTH radial symmetric tridiagonal action (float32 v1)

Status: source-written and **locally native-verified** for the exact fixture in
this document with the canonical NaN0S `nmk.awk` / `nan_cli` toolchain on
2026-11-07. This is local execution evidence, not a CI claim.

## 1. Scope

- Kernel: `mth/nan16/mth_radial_tridiagonal.nas`
- Entry point: `mth_radial_tridiagonal`
- Fixture: `mth/tests/mth_radial_tridiagonal_test.nas`
- Stage: R2 radial block, tridiagonal layout
- Operation: symmetric tridiagonal matrix-vector product `y = T x`

The kernel implements exactly one operator family:

```text
y[0]   = diag[0]*x[0] + offdiag[0]*x[1]
y[i]   = offdiag[i-1]*x[i-1] + diag[i]*x[i] + offdiag[i]*x[i+1],
         1 <= i <= 254
y[255] = offdiag[254]*x[254] + diag[255]*x[255]
```

It is the native action for a 256-position radial block. It is not an
eigensolver, not an inverse, not the radial energy/localization fixture, and
not a second boundary-condition operator. Boundary rows are ordinary
tridiagonal rows whose coefficients the caller has already encoded; section 4
defines that convention.

## 2. ABI

| Register | Meaning |
|---|---|
| `r1` | `diag`, 256 float32 words (input) |
| `r2` | `offdiag`, 255 float32 words (input); `offdiag[i]` couples `x[i]` and `x[i+1]` |
| `r3` | `x`, 256 float32 words (input) |
| `r4` | `y`, 256 float32 words (output) |
| `r13` | `1` (canonical increment) |
| `r1` on return | `1` (success) |
| clobbers | `r1` (return value) and `r5`-`r12` |
| preserved | `r0`, `r2`-`r4`, `r13`-`r15` |

`r0` is the zero constant and `r13` must be `1`.

The kernel is leaf-only: it contains no `CALL`, no helper, no static scratch,
and no return slot. `r15` is not modified. Inputs are read-only; the four
spans must be distinct and non-overlapping, each with the stated length. The
kernel does not check overlap or address wrap; those are caller preconditions,
as in the other MTH graph kernels.

All arithmetic is IEEE-754 binary32 in NaN16 `FMUL` / `FADD`. Integer `ADD`,
`SUB`, `CMP`, and `JMP` are used only for pointer movement and loop control.
There is no discrete/tabulated approximation, Q-format scaling, saturation,
or host-side arithmetic.

## 3. Numeric contract

Accumulation is in increasing row index `i`. Each row uses one accumulator;
the first product initializes it and every later term contributes one rounded
`FADD`. Terms are added in increasing column order:

| Row | Term order |
|---|---|
| `0` | `FMUL(diag[0],x[0])`, `FMUL(offdiag[0],x[1])`, then one `FADD` |
| `1..254` | `FMUL(offdiag[i-1],x[i-1])`, add `FMUL(diag[i],x[i])`, add `FMUL(offdiag[i],x[i+1])` |
| `255` | `FMUL(offdiag[254],x[254])`, add `FMUL(diag[255],x[255])` |

Each product is one rounded `FMUL`; each later product contributes exactly one
rounded `FADD`. There is no fused multiply-add, reassociation, hidden
precision, or reordering. Results are therefore deterministic for a given
input bit pattern but are not bitwise identical to an FMA-based or differently
ordered implementation.

`r13` must be `1`. `diag`, `offdiag`, and `x` are read-only. `y` may not alias
any input. NaN/Inf input policy is caller-side: the kernel propagates whatever
the float unit produces and does not validate or canonicalize results.

## 4. Inner Dirichlet/Robin boundary contract

This is a **descriptor-level convention, not a second operator.** The
execution kernel never receives a boundary-kind field, never branches on one,
and never adds a term that is not in section 1. A radial block descriptor may
carry the inner and outer boundary kind and coefficients for construction,
validation, audit, and digest purposes, but before dispatch those fields must
be reduced into the caller-supplied `diag` and `offdiag` spans.

Write a representative symmetric conservative radial row as

```text
y[i] = -a[i]*x[i-1] + (a[i] + a[i+1] + V[i])*x[i] - a[i+1]*x[i+1]
```

for `0 <= i <= 255`, where `a[i] > 0` is the face coefficient below position
`i`, `a[i+1]` is the face coefficient above it, and `V[i]` is the on-site
potential. The kernel's encoding is `diag[i] = a[i] + a[i+1] + V[i]` and
`offdiag[i] = -a[i+1]` for interior rows.

### Inner edge (`i = 0`)

Let the inner boundary face have coefficient `a[0]` and let the boundary
relation supply a ghost value `x[-1] = sigma * x[0]`, where

- homogeneous Dirichlet: `sigma = 0`,
- homogeneous Neumann: `sigma = 1`,
- homogeneous Robin: `sigma = 1 - kappa*h` for the caller's convention
  `(x[0] - x[-1])/h = kappa*x[0]` (equivalently `a[0]*sigma` folds the
  boundary flux into the diagonal).

Then row 0 of the same operator is

```text
y[0] = (a[0]*(1 - sigma) + a[1] + V[0])*x[0] - a[1]*x[1]
```

so the caller dispatches

```text
diag[0]    = a[0]*(1 - sigma) + a[1] + V[0]
offdiag[0] = -a[1]
```

For Dirichlet this is `diag[0] = a[0] + a[1] + V[0]`; the `a[0]` boundary
penalty is inside `diag[0]`, not a separate term. For Neumann it is
`diag[0] = a[1] + V[0]`. No kernel change is involved; these are different
caller-supplied coefficient words.

### Outer edge (`i = 255`)

With outer face coefficient `a[256]` and `x[256] = tau*x[255]`:

```text
y[255] = -a[255]*x[254] + (a[255] + a[256]*(1 - tau) + V[255])*x[255]
diag[255]    = a[255] + a[256]*(1 - tau) + V[255]
offdiag[254] = -a[255]
```

The same rule applies: the outer boundary penalty is folded into
`diag[255]`. The descriptor's boundary kind is metadata; the executed
operator is always `T(diag, offdiag)`.

Consequences:

- A descriptor with inner Dirichlet and one with inner Robin are two
  coefficient sets for the same kernel, not two kernels.
- Inhomogeneous boundary data (`g != 0`) produces a source term and cannot be
  represented by this operator-only ABI; the caller must pre-adjust the
  right-hand side.
- If the caller passes raw interior coefficients without folding the boundary
  face, the result is a different operator. The descriptor-to-coefficient
  conversion is the only place where the boundary type is interpreted.

## 5. Memory budget

| Object | NaN16 words | Bytes |
|---|---:|---:|
| `diag` | 256 | 2,048 |
| `offdiag` | 255 | 2,040 |
| `x` | 256 | 2,048 |
| `y` | 256 | 2,048 |
| **Working set** | **1,023** | **8,184** |

The fixture image is 1,552 words (12,416 bytes), including code and strings.
It fits both the historical 512 KiB (65,536-word) guest budget and the current
1 MiB guest budget with no special paging.

## 6. Fixture coverage

`mth/tests/mth_radial_tridiagonal_test.nas` uses fixed, non-overlapping
regions:

| Label | Word address |
|---|---:|
| code and helpers | 0 |
| `diag` | 512 |
| `offdiag` | 768 |
| `x` | 1,024 |
| `y` | 1,280 |
| pass/fail strings | 1,536 |

Each of the following cases checks the kernel return value (`r1 == 1`) and
then every one of the 256 output words:

1. **Constant analytic tridiagonal, unit state.**
   `diag[i] = 2.0`, `offdiag[i] = -1.0`, `x[i] = 1.0`.
   Expected `y[0] = 1.0`, `y[1..254] = 0.0`, `y[255] = 1.0`.
   This checks both boundary rows and the interior cancellation.
2. **Linear ramp.**
   Same operator, `x[i] = float(i+1)`.
   Expected `y[0] = 0.0`, `y[1..254] = 0.0`, `y[255] = 257.0`.
   A linear ramp has zero second difference in the interior, while the
   boundary rows produce distinct exact values.
3. **Alternating state.**
   Same operator, `x[i] = +1.0` for even `i` and `-1.0` for odd `i`.
   Expected `y[0] = 3.0`, `y[i] = 4.0*x[i]` for `1 <= i <= 254`, and
   `y[255] = -3.0`. This is the nonuniform interior alignment and sign check:
   a shifted or reversed interior off-diagonal produces a different pattern.
4. **Zero off-diagonal (diagonal operator).**
   `offdiag[i] = 0.0`, `diag[i] = float(i+2)`, `x[i] = float(i+1)`.
   Expected `y[i] = float(i+2)*float(i+1)` for all 256 entries.
   The non-constant diagonal makes a one-word pointer error visible, unlike a
   constant diagonal; the zero coupling removes the interior stencil.

Expected values are computed in the guest fixture with `CVTIF` / `FADD` /
`FMUL`; the host does not calculate any checked result. All values used are
exact binary32 integers (`max |y| = 65,792` in case 4), so equality checks are
payload comparisons, not tolerances.

The required success marker is:

```text
MTH RADIAL TRIDIAGONAL PASS
```

## 7. Local evidence

Commands, run from the repository root:

```sh
mkdir -p /data/data/com.termux/files/usr/tmp/opencode
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=emit \
  mth/tests/mth_radial_tridiagonal_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/radial_tridiagonal.nan
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=check \
  /data/data/com.termux/files/usr/tmp/opencode/radial_tridiagonal.nan
/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/radial_tridiagonal.nan \
  --steps 10000000 --serial
```

Observed output (streams shown separately):

```text
emit stderr:  words 1552
check stderr: check: 0 mismatches
run stdout:   MTH RADIAL TRIDIAGONAL PASS
run stderr:   [nan-cli] nan-text: 42518 steps, rc=3, pc=259, trap=''
```

`rc=3` is `NAN_HALTED` from the fixture's `HALT`; the trap string is empty and
the shell exit status is `0`. The emitted `.nan` text file is 51,154 bytes; the
loaded guest image is 1,552 words (12,416 bytes).

Kernel source SHA-256:

```text
99650eb8c4e777679d672b91b0f1c806d0b01431834b154dd1a4462bd6285275  mth/nan16/mth_radial_tridiagonal.nas
```

Fixture source SHA-256:

```text
0fb0defb1bc6c6b86c1a55656081d98a3f7fbdc34f8c42230820f188094d5354  mth/tests/mth_radial_tridiagonal_test.nas
```

In the current working tree the shared fixture runner also contains an entry
for `radial_tridiagonal`; that file is maintained outside this task and was
not edited here. The runner path confirms the same result:

```sh
python3 tools/run_mth_fixtures.py --only radial_tridiagonal
# [PASS] radial_tridiagonal: PASS steps=42518 marker=MTH RADIAL TRIDIAGONAL PASS
# 1/1 fixtures passed
```

This task did not modify shared files. The evidence above is local
`nmk.awk` / `nan_cli` execution, not a CI result.

As an independent review check outside the execution path, a host-side NumPy
float32 model reproduced all four analytic expectations and a random
integer-coefficient tridiagonal case exactly. That model was used only to
audit the fixture mathematics; it is not part of the kernel, fixture, oracle,
or guest execution.

## 8. Limitations

- Operator action only. No eigensolve, inverse, deflation, radial energy,
  localization metric, or radial source term is included.
- No boundary-descriptor struct is parsed or stored. Section 4 defines the
  convention by which a descriptor's boundary fields become `diag`/`offdiag`;
  descriptor encoding and validation remain a separate, caller-side concern.
- No overlap, alignment, length, NaN/Inf, or finite-result validation. Those
  are caller preconditions. The kernel does not canonicalize a NaN result.
- `r13` must be `1`; a different value changes pointer arithmetic and loop
  counts.
- One serial accumulator per row in increasing row and column order, so
  results are not bitwise identical to FMA or reordered implementations.
- Local evidence only; CI promotion and a fixture-runner registration remain
  pending. The R2 radial energy/localization fixture is still open.
