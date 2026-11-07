# MTH two-level avoided-crossing spectrum ABI

Status: source-written and locally executed with the canonical NaN0S toolchain.
The fixture prints `MTH TWO LEVEL SPECTRUM PASS` (390 guest steps).

## 1. Kernel

`mth/nan16/mth_two_level_spectrum.nas` computes the exact two-level spectrum
of the real symmetric 2x2 Hamiltonian

```
H(eta) = [[ a,       eta*c ],
          [ eta*c,   b     ]]
```

using only NaN16 float32 `FADD`, `FSUB`, `FMUL`, and `FSQRT`. There is no host
math, no table lookup, no fused multiply-add, and no square-root approximation.

## 2. Formula and operation order

The implementation order is fixed:

```
mean   = (a + b) * 0.5
half   = (a - b) * 0.5
ec     = eta * c
rad    = sqrt(half*half + ec*ec)
E_low  = mean - rad
E_high = mean + rad
gap    = E_high - E_low
```

The scalar expression is evaluated as:

1. load `a`, `b`, `c`, and `eta`, one float32 payload each;
2. `a+b`, then multiply by exactly representable `0.5f` (`0x3F000000`);
3. `a-b`, then multiply by the same `0.5f`;
4. multiply `eta*c`;
5. square `half`, square `eta*c`, add the two squares;
6. apply native `FSQRT` to the nonnegative sum;
7. subtract `rad` from `mean` for `E_low`;
8. add `rad` to `mean` for `E_high`;
9. subtract `E_low` from `E_high` for `gap`;
10. store `E_low`, `E_high`, and `gap`, in that order.

Division by two is multiplication by `0.5f`; this is exact for normal float32
values. Operands are not reordered. The last step is the literal definition
`gap = E_high - E_low`, not a separate `2*rad` shortcut. All arithmetic is
IEEE-754 binary32 round-to-nearest-even as implemented by the NaN16 float
unit.

`eta` may be any real float32 value. Because only `(eta*c)*(eta*c)` enters,
the spectrum is invariant under `eta -> -eta`. For finite inputs the radicand
is nonnegative and `E_low <= E_high`; at `eta*c = 0` and `a = b` the gap is
zero. With `eta=0` the off-diagonal coupling vanishes and the outputs are the
diagonal pair `{a,b}` scaled through `mean`/`half` exactly (the `a=1,b=3`
fixture gives `E_low=1`, `E_high=3`).

## 3. ABI

| Register | Meaning |
|---|---|
| `r1` | pointer to `a`, one float32 payload |
| `r2` | pointer to `b`, one float32 payload |
| `r3` | pointer to `c`, one float32 payload |
| `r4` | pointer to `eta`, one float32 payload |
| `r5` | `E_low` output, one float32 payload |
| `r6` | `E_high` output, one float32 payload |
| `r7` | `gap` output, one float32 payload |
| `r13` | constant `1` |
| return | `r1=1` success |

The routine is a leaf: it performs no `CALL`, uses no static scratch slots, and
does not use `r15`. It clobbers `r8`-`r12` and `r14`. It does not modify the
caller's `r2`-`r7` pointers.

Inputs and outputs must not overlap. The caller owns all storage. Outputs are
written only after all arithmetic has completed.

## 4. Fixture and tolerance

`mth/tests/mth_two_level_spectrum_test.nas` uses fixed `.org` arrays:

- `a = 1.0` (`0x3F800000`), `b = 3.0` (`0x40400000`),
  `c = 1.0` (`0x3F800000`), `eta = 0.0`.

  Required and checked exactly by bit equality:

  | Output | Value | Bits |
  |---|---|---|
  | `E_low` | `1.0` | `0x3F800000` |
  | `E_high` | `3.0` | `0x40400000` |
  | `gap` | `2.0` | `0x40000000` |

- `eta = 1.0`. The fixture checks each output within `1e-5`
  (`0x3727C5AC`) of the float32 nearest values:

  | Output | Expected | Bits | Observed |
  |---|---|---|---|
  | `E_low` | `2-sqrt(2)` ~= `0.5857864618301392` | `0x3F15F61A` | `0x3F15F61A` |
  | `E_high` | `2+sqrt(2)` ~= `3.4142136573791504` | `0x405A827A` | `0x405A827A` |
  | `gap` | `2*sqrt(2)` ~= `2.8284270763397217` | `0x403504F3` | `0x403504F4` |

  The observed `gap` differs from the rounded mathematical value by one
  float32 ulp (`2.38e-7`), inside the `1e-5` tolerance. The fixture also
  checks `E_low + E_high = 4` within the same tolerance; the observed sum is
  exactly `4.0` (`0x40800000`).

The tolerance comparison is itself native: subtract, take the absolute value
with an ordered `FCMP`/`FSUB` branch, then compare against `1e-5`. No host
arithmetic participates.

## 5. Build and run

```
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=emit \
  mth/tests/mth_two_level_spectrum_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/twolevel.nan
/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/twolevel.nan \
  --steps 1000000 --serial
```

Observed output:

```
[nan_cli] nan-text: 390 steps, rc=3, pc=109, trap=''
MTH TWO LEVEL SPECTRUM PASS
```

The step budget is 1,000,000; the fixture finishes far below it.

## 6. Limitations

- Only the 2x2 real symmetric case is implemented. It is not a general
  eigensolver and does not extend to N-level or complex Hamiltonians.
- Finite float32 inputs are assumed. The kernel does not validate for NaN,
  infinity, negative/overflowing radicands, or denormals, and it writes all
  three outputs regardless of input class.
- Input and output spans must be non-overlapping; the kernel does not check
  aliasing.
- Single-precision arithmetic is used throughout. If `rad` is very small
  relative to `|mean|`, `E_high - E_low` can suffer cancellation and `gap` can
  lose relative accuracy even though the eigenvalues themselves are computed
  in fixed order.
- Large `half` or `eta*c` can overflow the squared terms to infinity, and
  extremely small terms can underflow to zero under IEEE-754 rules.
- The routine is stateless and leaf, but it is not a caller-register-preserving
  full function; callers must respect the clobber list above.
