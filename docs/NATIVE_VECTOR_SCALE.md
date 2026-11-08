# Native float32 vector scale (256 elements)

Status: source-written and executed locally with the canonical NaN0S toolchain
(`nan0s/tools/nmk.awk` and `nan0s/aarch64/android/nan_cli`) on 2026-11-07.
This is local native evidence only, not a CI claim. The source and fixture are
not registered in any manifest, fixture list, or capability registry by this
change.

## 1. Scope

This document defines one NaN16 leaf kernel:

| Source | Operation | Output shape |
|---|---|---|
| `mth/nan16/mth_vector_scale256_f32.nas` | `out[i] = x[i] * scalar` | 256 float32 payloads |

Each float32 value is one IEEE binary32 bit pattern stored in the 32-bit
payload of one NaN16 word. The kernel executes only NaN16 instructions. There
is no host math, allocation, conversion, fused multiply-add, or reassociation.

The fixture is `mth/tests/mth_vector_scale256_f32_test.nas`.

## 2. ABI

All addresses are NaN16 word indices. `r13` must be `1`; the kernel uses it as
the element stride.

| Register | Meaning |
|---|---|
| `r1` | `x`, 256 float32 payloads |
| `r2` | `scalar`, address of one float32 payload |
| `r3` | output, 256 float32 payloads |
| `r13` | `1` |
| return | `r1=1` |
| clobbers | `r4-r7` |

```text
s = scalar[0]
for i = 0..255:
    out[i] = x[i] * s
```

The scalar payload is loaded once before the loop. Exactly one `FMUL` is
executed per element, in increasing element order. Integer instructions only
compute addresses, the loop counter, and the constant `256`.

The caller supplies a readable 256-word input span, a readable one-word scalar
payload, and a writable 256-word output span. Exact output aliasing with `x` is
safe because each element is loaded before its result is stored. Partial overlap
with `x` is not safe. Since the scalar is read before the first store, the output
may also overlap the scalar word. There is no span, length, alignment, alias, or
type validation, and no failure return.

## 3. Exact float32 rules

These are the NaN16 scalar float32 rules for `FMUL` (opcode `0x32`), as
implemented by the canonical core and recorded in
`nan0s/aarch64/android/core/OPS.md`.

### 3.1 NaN propagation and priority

For `FMUL` with operands `A` (first) and `B` (second), where `A=x[i]` and
`B=scalar`:

1. If `A` is a NaN, the result is `A | 0x00400000`.
2. Else if `B` is a NaN, the result is `B | 0x00400000`.
3. Else compute the IEEE binary32 multiplication.
4. If that result is a NaN (for example `0 * inf`), replace it with the
   canonical invalid-result NaN `0xFFC00000`.

A NaN is detected as exponent bits all ones with a nonzero 23-bit mantissa.
The first-operand rule means an `x[i]` NaN wins over a scalar NaN. The
second-operand rule quieted a scalar sNaN by setting bit 22 while preserving
its sign and remaining payload bits. Already-quiet NaNs are unchanged by the
OR.

### 3.2 Rounding and signed zero

Non-NaN finite products round to nearest, ties to even (RNE), with no
flush-to-zero and no denormals-are-zero mode. Signed zero follows IEEE sign
XOR. For nonzero finite `x`:

| Expression | Result |
|---|---|
| `+0 * +x` | `+0` |
| `-0 * +x` | `-0` |
| `+0 * -x` | `-0` |
| `-0 * -x` | `+0` |

A zero operand multiplied by an infinity is invalid and produces the canonical
`0xFFC00000`, regardless of the zero's sign.

### 3.3 Infinity policy

Infinity follows IEEE sign XOR combined with the finite infinity rules:

- `+inf * +inf = +inf`, `+inf * -inf = -inf`;
- `-inf * -inf = +inf`, `-inf * +inf = -inf`;
- a finite nonzero value times an infinity is an infinity with the XOR sign;
- a NaN operand takes priority according to section 3.1 and is never
  converted to an infinity.

These are the same NaN16 float32 rules used by the add, subtract, and mean
kernels, with `A=x[i]` and `B=scalar`.

## 4. Fixture

All expected outputs are literal binary32 payloads. The guest compares payload
words with integer `CMP`; no host math is used.

All-element phases check all 256 output words:

| Phase | `x[i]` | `scalar` | expected `out[i]` |
|---|---|---|---|
| 1 | `0x40000000` (`2.0`) | `0x40400000` (`3.0`) | `0x40C00000` (`6.0`) |
| 2 | `0x40000000` (`2.0`) | `0xC0400000` (`-3.0`) | `0xC0C00000` (`-6.0`) |
| 3 | `0x40000000` (`2.0`) | `0x00000000` (`+0`) | `0x00000000` (`+0`) |
| 4 | `0x40000000` (`2.0`) | `0x80000000` (`-0`) | `0x80000000` (`-0`) |
| 5 | `0xC0000000` (`-2.0`) | `0x00000000` (`+0`) | `0x80000000` (`-0`) |
| 6 | `0xC0000000` (`-2.0`) | `0x80000000` (`-0`) | `0x00000000` (`+0`) |
| 7a | `0x7F800000` (`+inf`) | `0x40000000` (`2.0`) | `0x7F800000` (`+inf`) |
| 7b | `0xFF800000` (`-inf`) | `0x40000000` (`2.0`) | `0xFF800000` (`-inf`) |
| 8a | `0x00000000` (`+0`) | `0x7F800000` (`+inf`) | `0xFFC00000` (invalid) |
| 8b | `0x80000000` (`-0`) | `0x7F800000` (`+inf`) | `0xFFC00000` (invalid) |
| 9a | `0x7FC00123` (qNaN) | `0x40000000` (`2.0`) | `0x7FC00123` (preserved) |
| 9b | `0x40000000` (`2.0`) | `0x7F800001` (sNaN) | `0x7FC00001` (quieted) |
| 11 | `0x3F800001` (`1+2^-23`) | `0x3F800001` (`1+2^-23`) | `0x3F800002` (`1+2^-22`) |

Phase 11 is the targeted RNE case:
`(1+2^-23)^2 = 1 + 2^-22 + 2^-46`, and the `2^-46` term is far below the
half-ulp threshold, so the product rounds down to `1+2^-22`.

Phase 10 uses these eight `x` policy cases:

| Case | `x` |
|---|---|
| 0 | `0x7F800001` (positive signalling NaN) |
| 1 | `0xFF800002` (negative signalling NaN) |
| 2 | `0x7FC00003` (positive quiet NaN) |
| 3 | `0xFFC00004` (negative quiet NaN) |
| 4 | `0x7F800000` (`+inf`) |
| 5 | `0xFF800000` (`-inf`) |
| 6 | `0x3F800001` (`1+2^-23`) |
| 7 | `0x80000000` (`-0`) |

Each of the seven scalar scenarios below is applied to all eight cases, and all
eight expected payloads are checked:

| `x` case | `+2.0` | `+sNaN` | `-sNaN` | `+inf` | `-inf` | `+0` | `-0` |
|---|---|---|---|---|---|---|---|
| `0x7F800001` | `0x7FC00001` | `0x7FC00001` | `0x7FC00001` | `0x7FC00001` | `0x7FC00001` | `0x7FC00001` | `0x7FC00001` |
| `0xFF800002` | `0xFFC00002` | `0xFFC00002` | `0xFFC00002` | `0xFFC00002` | `0xFFC00002` | `0xFFC00002` | `0xFFC00002` |
| `0x7FC00003` | `0x7FC00003` | `0x7FC00003` | `0x7FC00003` | `0x7FC00003` | `0x7FC00003` | `0x7FC00003` | `0x7FC00003` |
| `0xFFC00004` | `0xFFC00004` | `0xFFC00004` | `0xFFC00004` | `0xFFC00004` | `0xFFC00004` | `0xFFC00004` | `0xFFC00004` |
| `0x7F800000` | `0x7F800000` | `0x7FC00001` | `0xFFC00002` | `0x7F800000` | `0xFF800000` | `0xFFC00000` | `0xFFC00000` |
| `0xFF800000` | `0xFF800000` | `0x7FC00001` | `0xFFC00002` | `0xFF800000` | `0x7F800000` | `0xFFC00000` | `0xFFC00000` |
| `0x3F800001` | `0x40000001` | `0x7FC00001` | `0xFFC00002` | `0x7F800000` | `0xFF800000` | `0x00000000` | `0x80000000` |
| `0x80000000` | `0x80000000` | `0x7FC00001` | `0xFFC00002` | `0xFFC00000` | `0xFFC00000` | `0x80000000` | `0x00000000` |

The `+sNaN` scalar is `0x7F800001`; the `-sNaN` scalar is `0xFF800002`. The
table exercises x-NaN priority, scalar-NaN quieting with sign preservation,
quiet-NaN bit preservation, signed infinities, all four signed-zero sign
combinations, and both signed-zero times infinity invalid cases.

## 5. Local execution evidence

Commands used from the repository root:

```sh
LC_ALL=C awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk \
  -v CMD=emit mth/tests/mth_vector_scale256_f32_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/v_scale.nan
LC_ALL=C awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk \
  -v CMD=check /data/data/com.termux/files/usr/tmp/opencode/v_scale.nan

/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/v_scale.nan \
  --steps 2000000 --serial
```

Observed result on 2026-11-07:

```text
[nan_cli] nan-text: 82168 steps, rc=3, pc=270, trap=''
MTH VECTOR SCALE256 F32 PASS
```

| Field | Value |
|---|---|
| Marker | `MTH VECTOR SCALE256 F32 PASS` |
| Steps | `82168` |
| Guest status | `rc=3` (`NAN_HALTED` from the final `HALT`) |
| Host exit | `0` |
| PC | `270` |
| Trap | `''` (empty) |
| Emitted words | `4624` |
| `nmk -v CMD=check` | `0 mismatches` |
| SHA-256 of `v_scale.nan` | `7bbbabd6012dac51128a453adccfa75dadb7ada33cdbbdb2306c77b58c83b283` |

A budget of `82167` steps produces `rc=0` at `pc=269`, one instruction before
the `HALT`; the exact halt step count is `82168`. The fixture's expected-value
checks are performed inside the guest, and the marker alone is not treated as
proof when a truncated step budget is used.

## 6. Limitations

- Local `nan_cli` execution only. No CI run has been observed for this source
  or fixture, so this is not CI-verified.
- The source and fixture are not registered in any manifest, fixture list, or
  capability registry by this change.
- No span, length, alignment, alias, or type validation. There is no error
  return and no partial-result reporting.
- Exact output aliasing with `x` is safe; partial overlap is not. The caller
  owns all address and overlap contracts.
- The scalar argument is an address, not an immediate payload. It must point
  to a readable word.
- RNE, no FTZ/DAZ is the declared platform rule. The fixture exercises one
  inexact finite product but does not target subnormal products or underflow.
- `0 * inf` is declared invalid and canonicalized to `0xFFC00000`; it is not a
  signed zero and not a NaN payload derived from either operand.
- This is a sequence of scalar `FMUL`s, not a fused multiply-add and not a
  compensated or vectorized approximation.
