# Native float32 vector add, subtract, and mean

Status: source-written and executed locally with the canonical NaN0S toolchain
(`nan0s/tools/nmk.awk` and `nan0s/aarch64/android/nan_cli`) on 2026-11-07.
This is local native evidence only, not a CI claim. The three sources are not
registered in any manifest or fixture list by this change.

## 1. Scope

This document defines three NaN16 kernels:

| Source | Operation | Output shape |
|---|---|---|
| `mth/nan16/mth_vector_add256_f32.nas` | `out[i] = x[i] + y[i]` | 256 float32 payloads |
| `mth/nan16/mth_vector_sub256_f32.nas` | `out[i] = x[i] - y[i]` | 256 float32 payloads |
| `mth/nan16/mth_vector_mean256_f32.nas` | `out = (sum x[i]) / 256` | 1 float32 payload |

Each float32 value is one IEEE binary32 bit pattern stored in the 32-bit
payload of one NaN16 word. The kernels execute only NaN16 instructions. There
is no host math, no allocation, no hidden conversion, no fused multiply-add, and
no reassociation.

The fixtures are:

- `mth/tests/mth_vector_add256_f32_test.nas`
- `mth/tests/mth_vector_sub256_f32_test.nas`
- `mth/tests/mth_vector_mean256_f32_test.nas`

## 2. Common ABI contract

All addresses are NaN16 word indices. `r13` must be `1`; the kernels use it as
the element stride. On success each entry point returns `r1=1`. There is no
failure return.

The caller supplies readable input spans and writable output spans. The
kernels do not validate addresses, lengths, alignment, aliasing, NaNs, or
infinities. For add/sub, output may alias exactly one input span because each
element is loaded before its result is stored; partial overlap with an input is
unsafe. The mean output is written only after all 256 inputs have been read, so
it may overlap the input span.

All NaN16 arithmetic here is scalar float32 in the payload. The integer
instructions only compute addresses, loop counters, and the constant `256`.

## 3. Entry points

### 3.1 `mth_vector_add256_f32`

| Register | Meaning |
|---|---|
| `r1` | `x`, 256 float32 payloads |
| `r2` | `y`, 256 float32 payloads |
| `r3` | output, 256 float32 payloads |
| `r13` | `1` |
| return | `r1=1` |
| clobbers | `r4-r8` |

```text
for i = 0..255:
    out[i] = x[i] + y[i]
```

Exactly one `FADD` is executed per element, in increasing element order.

### 3.2 `mth_vector_sub256_f32`

Same ABI as add, with `r2` as the subtrahend:

| Register | Meaning |
|---|---|
| `r1` | `x`, 256 float32 payloads |
| `r2` | `y`, 256 float32 payloads |
| `r3` | output, 256 float32 payloads |
| `r13` | `1` |
| return | `r1=1` |
| clobbers | `r4-r8` |

```text
for i = 0..255:
    out[i] = x[i] - y[i]
```

Exactly one `FSUB` is executed per element, in increasing element order.

### 3.3 `mth_vector_mean256_f32`

| Register | Meaning |
|---|---|
| `r1` | `x`, 256 float32 payloads |
| `r2` | output, one float32 payload |
| `r13` | `1` |
| return | `r1=1` |
| clobbers | `r3-r6` |

```text
sum = +0.0
for i = 0..255:
    sum = sum + x[i]
out = sum / 256.0
```

The accumulator starts at `+0.0`. Exactly one `FADD` is executed per element
in increasing order, followed by exactly one `FDIV` by the float32 constant
`256.0` (`0x43800000`). The division is not a multiplication by `1/256`.

The result is the result of this exact sequential computation, not a
correctly rounded exact average of all 256 inputs. The fixture includes a case
where early terms are absorbed by later round-to-nearest-even additions.

## 4. Exact float32 bit and rounding rules

These rules are the NaN16 scalar float32 rules (opcodes `FADD=0x30`,
`FSUB=0x31`, `FDIV=0x33`), as implemented by the canonical core and recorded in
`nan0s/aarch64/android/core/OPS.md`.

### 4.1 NaN propagation

For `FADD` and `FSUB`, with operands `A` (first) and `B` (second):

1. If `A` is a NaN, the result is `A | 0x00400000`.
2. Else if `B` is a NaN, the result is `B | 0x00400000`.
3. Else compute the IEEE binary32 operation.
4. If that result is a NaN (for example `+inf + -inf` or `inf - inf`), replace
   it with the canonical invalid-result NaN `0xFFC00000`.

A NaN is detected as exponent bits all ones with a nonzero 23-bit mantissa.
Step 1 means a NaN in the first operand wins over a NaN in the second operand.
Step 2 preserves the bit pattern and sign of a second-operand NaN while setting
the quiet bit. Already-quiet NaNs are unchanged by the OR.

For add, `A=x[i]`, `B=y[i]`. For subtract, `A=x[i]`, `B=y[i]`. For mean,
`A` is the running accumulator and `B` is `x[i]`; the first NaN produced or
encountered in increasing index order therefore becomes the accumulator NaN
and is preserved (quieted) through the remaining additions and the final
division.

### 4.2 Rounding and signed zero

For non-NaN operands, `FADD`, `FSUB`, and `FDIV` round to nearest, ties to even
(RNE), with no flush-to-zero or denormals-are-zero mode. Results follow IEEE
binary32 for signed zero:

| Expression | Result |
|---|---|
| `+0 + -0` | `+0` |
| `-0 + -0` | `-0` |
| `+0 - +0` | `+0` |
| `+0 - -0` | `+0` |
| `-0 - +0` | `-0` |
| `-0 - -0` | `+0` |

Because the mean accumulator starts at `+0.0`, an all-`-0.0` input vector
produces `+0.0`, not `-0.0`.

For the mean, division by `256.0` is exact whenever the finite accumulated sum
is normal, because 256 is a power of two. A subnormal accumulated sum can be
rounded by the final `FDIV` under RNE; that edge is not exercised by the
fixture. The mean fixture's non-exact case is caused by `FADD` absorption
during accumulation, not by the division. The `FDIV` zero-divisor special case
cannot occur because the divisor is always `256.0`.

### 4.3 Infinity policy

Infinity follows the same rules:

- `+inf + +inf = +inf`, `-inf + -inf = -inf`;
- `+inf + -inf` is invalid and becomes `0xFFC00000`;
- a finite value plus an infinity is that infinity;
- an all-`+inf` mean input produces `+inf`;
- any NaN operand or invalid infinity combination follows section 4.1 and is
  not converted to an infinity.

## 5. Fixtures and hand-checkable values

### 5.1 Add fixture

Phase 1: all 256 `x[i]=2.0` (`0x40000000`) and all 256 `y[i]=3.0`
(`0x40400000`). Every one of the 256 outputs is checked for exactly `5.0`
(`0x40A00000`).

Phase 2: eight independent element cases are checked at indices `0..7`:

| `x` | `y` | expected `out` | rule |
|---|---|---|---|
| `0x7F800000` (`+inf`) | `0xFF800000` (`-inf`) | `0xFFC00000` | invalid result |
| `0xFF800000` (`-inf`) | `0xFF800000` (`-inf`) | `0xFF800000` | `-inf + -inf` |
| `0x00000000` (`+0`) | `0x80000000` (`-0`) | `0x00000000` | RNE signed zero |
| `0x80000000` (`-0`) | `0x80000000` (`-0`) | `0x80000000` | `-0 + -0` |
| `0x7F800001` (sNaN) | `0x3F800000` (`1.0`) | `0x7FC00001` | first NaN quieted |
| `0x3F800000` (`1.0`) | `0xFF800002` (sNaN) | `0xFFC00002` | second NaN quieted |
| `0x7FC00003` (qNaN) | `0xFFC00004` (qNaN) | `0x7FC00003` | first NaN wins |
| `0x7F800000` (`+inf`) | `0x3F800000` (`1.0`) | `0x7F800000` | finite plus infinity |

### 5.2 Subtract fixture

Phase 1: all 256 `x[i]=5.0` (`0x40A00000`) and all 256 `y[i]=1.5`
(`0x3FC00000`). Every one of the 256 outputs is checked for exactly `3.5`
(`0x40600000`).

Phase 2: ten independent element cases are checked at indices `0..9`:

| `x` | `y` | expected `out` | rule |
|---|---|---|---|
| `0x7F800000` (`+inf`) | `0x7F800000` (`+inf`) | `0xFFC00000` | invalid result |
| `0x7F800000` (`+inf`) | `0x3F800000` (`1.0`) | `0x7F800000` | infinity minus finite |
| `0x00000000` (`+0`) | `0x00000000` (`+0`) | `0x00000000` | `+0 - +0` |
| `0x00000000` (`+0`) | `0x80000000` (`-0`) | `0x00000000` | `+0 - -0` |
| `0x80000000` (`-0`) | `0x00000000` (`+0`) | `0x80000000` | `-0 - +0` |
| `0x80000000` (`-0`) | `0x80000000` (`-0`) | `0x00000000` | `-0 - -0` |
| `0x7F800001` (sNaN) | `0x40000000` (`2.0`) | `0x7FC00001` | first NaN quieted |
| `0x40400000` (`3.0`) | `0xFF800002` (sNaN) | `0xFFC00002` | second NaN quieted |
| `0x7FC00003` (qNaN) | `0xFFC00004` (qNaN) | `0x7FC00003` | first NaN wins |
| `0xFF800000` (`-inf`) | `0x3F800000` (`1.0`) | `0xFF800000` | infinity minus finite |

### 5.3 Mean fixture

1. `x[i] = float32(i)` for `i=0..255`, produced natively with `CVTIF`. The
   exact sum is `32640`, so the exact mean is `127.5` (`0x42FF0000`).
2. `x[0]=1.0`, `x[1..255]=2^-25` (`0x33000000`). Each later addition is a
   quarter of the `1.0` ulp and rounds back to `1.0` under RNE. The sequential
   sum is `1.0` and the division result is `2^-8` (`0x3B800000`).
3. All 256 elements are `-0.0` (`0x80000000`). The declared `+0.0` accumulator
   makes the result `+0.0` (`0x00000000`).
4. All 256 elements are `+inf` (`0x7F800000`). The result is `+inf`.
5. `x[0]=0x7FC00123` (quiet NaN), all other elements `+0.0`. The first NaN is
   quieted and preserved, so the result is exactly `0x7FC00123`.

## 6. Local execution evidence

Commands used from the repository root:

```sh
LC_ALL=C awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk \
  -v CMD=emit mth/tests/mth_vector_add256_f32_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/v_add.nan
LC_ALL=C awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk \
  -v CMD=check /data/data/com.termux/files/usr/tmp/opencode/v_add.nan

/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/v_add.nan \
  --steps 2000000 --serial
```

The same commands were run for `v_sub.nan` and `v_mean.nan`.

Observed results on 2026-11-07:

| Fixture | Marker | Steps | `nan_cli` status | Emitted words | `nmk -v CMD=check` |
|---|---|---:|---|---:|---|
| add | `MTH VECTOR ADD256 F32 PASS` | 10,436 | `rc=3`, `pc=90`, `trap=''` | 4,622 | 0 mismatches |
| sub | `MTH VECTOR SUB256 F32 PASS` | 10,484 | `rc=3`, `pc=90`, `trap=''` | 4,622 | 0 mismatches |
| mean | `MTH VECTOR MEAN256 F32 PASS` | 15,969 | `rc=3`, `pc=124`, `trap=''` | 2,576 | 0 mismatches |

`rc=3` is `NAN_HALTED` from the fixture's final `HALT`; `trap=''` means no gate
or opcode trap. The step counts are the exact `nan_cli` counters at halt. A
budget of one fewer step produces `rc=0` one instruction before the `HALT`
(`pc=89` for add/sub, `pc=123` for mean), so the marker is not by itself
evidence of reaching the halt when a truncated budget is used; the step count
is.

SHA-256 of the emitted text images:

```text
b103ca1d10c53f6c5b6bd9d8220a0e22b602f87cdf3db183942642b49fb2c892  v_add.nan
6c0144056aa3ee50a998fdac1b686ad81ff0a058ce55a09768abcb4ef5d161ba  v_sub.nan
b4c486534c0999fb8be50646094f27fa0edbcd79c2f3eb2963681f25a215f154  v_mean.nan
```

These fixtures self-check output bits inside the guest with integer `CMP`
instructions. No host-side expected-value calculation is used by the kernels
or the fixtures.

## 7. Limitations

- Canonical CI executed these fixtures in run `42539617226`.
- Add/sub/mean plus abs/relu are registered with `ci_verified=true`; the
  additional abs/relu fixtures pass at 5,328 and 6,615 steps respectively.
- Abs is an exact sign-bit clear; ReLU is a sign-only rule (negative NaN
  becomes +0.0) and is documented as such.
- No span, alias, length, or type validation. Exact-alias safety is limited to
  the cases described in section 2; callers own the contract.
- No error return and no partial-result reporting.
- The mean is a defined sequential 256-term sum followed by division by 256.
  It is not compensated, pairwise, or guaranteed to be the correctly rounded
  exact mean.
- Subnormal `FDIV` rounding is declared as RNE by the platform rules but is not
  covered by a targeted fixture case.
- The add/sub semantics are not ambiguous for this toolchain: the exact NaN
  priority, quieting, canonical-invalid, signed-zero, and RNE rules are stated
  in section 4 and exercised by the fixtures. A different NaN16 implementation
  that does not match those bit rules would fail the fixtures.
