# MTH avoided-crossing sweep ABI

Status: source-written and locally executed with the canonical NaN0S toolchain.
The fixture prints `MTH AVOIDED CROSSING SWEEP PASS` (11,651 guest steps).
This is the R7 avoided-crossing sweep primitive; it is a spectral calculation,
not a physical tunneling or creativity claim.

## 1. Kernel

`mth/nan16/mth_avoided_crossing_sweep.nas` sweeps a real coupling vector and
computes the lower eigenvalue, upper eigenvalue, and gap of each 2x2 real
symmetric Hamiltonian

```
H[i] = [[ a,       c[i] ],
        [ c[i],    b     ]]
```

for `i = 0, 1, ..., n-1` in increasing index order. It uses only NaN16 float32
`FADD`, `FSUB`, `FMUL`, and `FSQRT`. There is no host math, no table lookup, no
fused multiply-add, and no square-root approximation.

The per-element formula and operation order are the same stable formula as
`mth/nan16/mth_two_level_spectrum.nas` with `eta = 1`:

```
mean   = (a + b) * 0.5
half   = (a - b) * 0.5
rad    = sqrt(half*half + c*c)
lower  = mean - rad
upper  = mean + rad
gap    = upper - lower
```

`mean` and `half` depend only on the diagonals, so they are computed once
before the loop. Inside the loop the operations are performed in this fixed
order:

1. load `c = couplings[i]`;
2. square `c`;
3. square `half`;
4. add the two squares;
5. apply native `FSQRT` to the nonnegative radicand;
6. subtract `rad` from `mean` for `lower`;
7. add `rad` to `mean` for `upper`;
8. subtract `lower` from `upper` for `gap`;
9. store `lower`, `upper`, and `gap`;
10. advance the index and continue while `i < n`.

Division by two is multiplication by the exactly representable `0.5f`
(`0x3F000000`). Operands are not reordered. The last step is the literal
definition `gap = upper - lower`, not a separate `2*rad` shortcut. All
arithmetic is IEEE-754 binary32 round-to-nearest-even as implemented by the
NaN16 float unit.

For finite inputs the radicand is nonnegative and `lower <= upper`. When
`a = b`, `half` is zero and the gap is `2*|c|`, exactly representable for the
fixture's exact-square couplings. When `c = 0`, the pair decouples and the
outputs are the diagonal pair `{a,b}`.

## 2. ABI

| Register | Meaning |
|---|---|
| `r1` | pointer to `a`, one float32 payload (diagonal A) |
| `r2` | pointer to `b`, one float32 payload (diagonal B) |
| `r3` | pointer to `n` float32 couplings, increasing index order |
| `r4` | `n`, integer count in `1..256` |
| `r5` | `gap` output, `n` float32 |
| `r6` | `lower` output, `n` float32 |
| `r7` | `upper` output, `n` float32 |
| `r13` | constant `1` |
| return | `r1=1` success |

The routine is a leaf: it performs no `CALL`, uses no static scratch slots,
and does not use `r15`. It clobbers `r8`-`r12` and `r14`, and uses `r1` as an
address temporary before setting it to the success value. It preserves the
caller's `r2`-`r7` pointers and `r13`.

Inputs and outputs must not overlap. The caller owns all storage and must
provide at least `n` readable coupling words and at least `n` writable words
in each output span. `n` is assumed to be in `1..256`; it is not range-checked.
Outputs for an index are written only after that index's arithmetic has
completed.

## 3. Fixture and tolerance

`mth/tests/mth_avoided_crossing_sweep_test.nas` uses fixed `.org` arrays and
three cases.

### Case 1: `a=1`, `b=3`, couplings `[0, 1, 2]`, `n=3`

`c=0` is checked exactly:

| Output | Value | Bits |
|---|---|---|
| `lower[0]` | `1.0` | `0x3F800000` |
| `upper[0]` | `3.0` | `0x40400000` |
| `gap[0]` | `2.0` | `0x40000000` |

For `c=1` and `c=2`, each output is checked within `1e-5` (`0x3727C5AC`) of
the float32 nearest mathematical value:

| Index | Output | Expected (float32 nearest) | Bits |
|---|---|---|---|
| `1` | `lower` | `2-sqrt(2)` ~= `0.5857864618301392` | `0x3F15F61A` |
| `1` | `upper` | `2+sqrt(2)` ~= `3.4142136573791504` | `0x405A827A` |
| `1` | `gap` | `2*sqrt(2)` ~= `2.8284270763397217` | `0x403504F3` |
| `2` | `lower` | `2-sqrt(5)` ~= `-0.2360679805278778` | `0xBE71BBCE` |
| `2` | `upper` | `2+sqrt(5)` ~= `4.236067771911621` | `0x40878DDE` |
| `2` | `gap` | `2*sqrt(5)` ~= `4.4721360206604` | `0x408F1BBD` |

An instrumented stop-after-case-1 run of the same kernel and fixture observed:

```
gap   = 0x40000000 0x403504F4 0x408F1BBC
lower = 0x3F800000 0x3F15F61A 0xBE71BBD0
upper = 0x40400000 0x405A827A 0x40878DDE
```

The `c=1` gap is one float32 ulp above the rounded mathematical value
(`0x403504F4` versus `0x403504F3`); the `c=2` gap is one ulp below
(`0x408F1BBC` versus `0x408F1BBD`). Both are inside the `1e-5` tolerance.
This mirrors the one-ulp `gap` cancellation already documented for the
two-level kernel.

### Case 2: `a=b=2`, couplings `[0, 0.5, 1, 2]`, `n=4`

Zero coupling gives `lower[0] = upper[0] = 2` and `gap[0] = 0` exactly.
For `c>0`, `gap = 2c` exactly:

| Index | Coupling | `lower` | `upper` | `gap` |
|---|---|---|---|---|
| `0` | `0.0` | `2.0` | `2.0` | `0.0` |
| `1` | `0.5` | `1.5` | `2.5` | `1.0` |
| `2` | `1.0` | `1.0` | `3.0` | `2.0` |
| `3` | `2.0` | `0.0` | `4.0` | `4.0` |

All values in this case are checked by exact bit equality. The observed arrays
were exactly these values.

### Case 3: maximum sweep `n=256`

`a=b=2`, couplings `c[i] = i` for `i = 0..255`. Every `i` and `i*i` is an
exact float32 integer, so `rad = i` and the fixture checks every index by
exact equality:

```
lower[i] = 2 - i
upper[i] = 2 + i
gap[i]   = 2*i
```

The tolerance comparison in Case 1 is itself native: subtract, take the
absolute value with an ordered `FCMP`/`FSUB` branch, then compare against
`1e-5`. No host arithmetic participates in the fixture.

## 4. Build and run

```
LC_ALL=C awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=emit \
  mth/tests/mth_avoided_crossing_sweep_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/avoided_crossing.nan
LC_ALL=C awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=check \
  /data/data/com.termux/files/usr/tmp/opencode/avoided_crossing.nan
/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/avoided_crossing.nan \
  --steps 1000000 --serial
```

Observed assembly and execution:

```
words 3602
check: 0 mismatches
[nan_cli] nan-text: 11651 steps, rc=3, pc=232, trap=''
MTH AVOIDED CROSSING SWEEP PASS
```

The step budget is 1,000,000; the full fixture finishes far below it.

## 5. Limitations

- Implements only the real symmetric 2x2 case per coupling. It is not a
  general eigensolver and does not extend to N-level or complex Hamiltonians.
- Finite float32 inputs are assumed. The kernel does not validate for NaN,
  infinity, negative/overflowing radicands, denormals, or `n` outside `1..256`.
- Input and output spans must be non-overlapping; the kernel does not check
  aliasing.
- Single-precision arithmetic is used throughout. If `rad` is very small
  relative to `|mean|`, `upper - lower` can suffer cancellation and `gap` can
  lose relative accuracy even though the eigenvalues themselves are computed
  in fixed order.
- Large `half` or `c` can overflow the squared terms to infinity, and
  extremely small terms can underflow to zero under IEEE-754 rules.
- The routine is stateless and leaf, but it is not a caller-register-preserving
  full function; callers must respect the clobber list above.
