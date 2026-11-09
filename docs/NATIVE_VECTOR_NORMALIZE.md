# Native float32 vector normalization (256 elements)

Status: source-written, locally executed, and CI-verified in canonical run
`42539617226` with the pinned NaN0S toolchain. The source and fixture are
registered in `spec/wave-capabilities.json` with `ci_verified=true`.

## 1. Scope

This document defines one NaN16 leaf kernel:

| Source | Operation | Output shape |
|---|---|---|
| `mth/nan16/mth_vector_normalize256_f32.nas` | `out[i] = x[i] / sum(x[j])` | 256 float32 payloads |

Each float32 value is one IEEE binary32 bit pattern stored in the 32-bit
payload of one NaN16 word. The kernel executes only NaN16 instructions. There
is no host math, allocation, conversion, fused multiply-add, reciprocal
multiply, or reassociation.

The fixture is `mth/tests/mth_vector_normalize256_f32_test.nas`.

## 2. ABI and status convention

All addresses are NaN16 word indices. `r13` must be `1`; the kernel uses it as
the element stride.

| Register | Meaning |
|---|---|
| `r1` | `x`, 256 float32 payloads (read-only) |
| `r2` | `out`, 256 float32 payloads |
| `r13` | `1` |
| success return | `r1=1`, `r9=0` |
| failure return | `r1=0`, `r9=cause` |
| clobbers | `r1`, `r3-r11`, flags |
| preserves | `r0`, `r2`, `r12-r15` |

The success ABI return is `r1=1`. Fail-closed rejection returns `r1=0`; a
caller must check `r1` before consuming `out[]`.

On failure:

- `out[0]` is a status word `0xFFC0DEAC + cause`;
- `out[1..255]` is the canonical marker `0xFFC0DEAD`;
- `r9` carries the same cause code.

| Cause | `r9` | `out[0]` status | Meaning |
|---|---:|---|---|
| non-finite input | 1 | `0xFFC0DEAD` | some `x[i]` is NaN, `+inf`, or `-inf` |
| zero sum | 2 | `0xFFC0DEAE` | the sequential sum is `+0.0` or `-0.0` |
| non-finite sum | 3 | `0xFFC0DEAF` | the sum overflowed to `+inf` or `-inf` |
| non-finite quotient | 4 | `0xFFC0DEB0` | some `x[i] / sum` overflowed to `+inf` or `-inf` |

Every failure word is a diagnostic quiet-NaN-class payload, never an
arithmetic result. The all-256-word marker/status fill means a rejected call
does not leave a mixture of valid-looking quotients and garbage, even when a
quotient overflow is detected after earlier stores.

Exact `out == x` aliasing is safe because the complete sum pass finishes
before any store, and each `x[i]` is loaded before its quotient is stored at
the same index. Partial overlap of `out` with `x` is not safe. There is no
span, length, alignment, or alias validation.

## 3. Algorithm

```text
sum = +0.0
for i = 0..255:                 # one increasing-order pass
    if nonfinite(x[i]): reject(1)
    sum = sum + x[i]            # exactly one FADD per element

if nonfinite(sum): reject(3)
if sum == 0: reject(2)

for i = 0..255:                 # one increasing-order pass
    q = x[i] / sum              # exactly one FDIV per element
    if nonfinite(q): reject(4)  # overwrites any partial stores
    out[i] = q

return 1
```

The sum is the defined sequential 256-term sum, not a correctly rounded exact
sum of the inputs. The divisor is that exact sequential result. There is no
pairwise or compensated summation and no reordering. On success exactly one
`FADD` is executed per element and exactly one `FDIV` per element, both in
increasing index order. On failure the loop may stop early; the failure fill
then overwrites all 256 output words.

Integer instructions only compute addresses, loop counters, the constant
`256`, and the exponent-field tests.

## 4. Declared float32 policy

### 4.1 Non-finite inputs

The input domain is finite binary32 values only. The preflight is fused into
the sum pass and tests

```text
(payload & 0x7F800000) == 0x7F800000
```

which is exactly the exponent-all-ones class: NaN, `+inf`, and `-inf`. The
first such element rejects the call with cause 1 before any output store, so a
non-finite input is never propagated into an arithmetic result.

### 4.2 NaN policy

NaN inputs are rejected (cause 1). With all inputs finite, an `FADD` sum cannot
become NaN, and a finite nonzero divisor cannot produce a NaN quotient from a
finite dividend. Thus no success output is NaN, and there is no NaN-payload
propagation or priority rule to apply. The failure marker and status words are
NaN-class diagnostic payloads by design, not arithmetic results.

### 4.3 Infinity policy

Infinity inputs are rejected (cause 1). A finite-input sum that overflows to
`+inf` or `-inf` is rejected (cause 3). A quotient that overflows to `+inf` or
`-inf` is rejected (cause 4). No successful output is infinite, and infinity is
never propagated.

### 4.4 Zero-sum and signed-zero policy

A sequential sum of exactly `+0.0` or `-0.0` is rejected with cause 2; the
kernel never divides by zero. This includes an all-`+0.0` input, an all-`-0.0`
input (whose declared `+0.0` accumulator stays `+0.0`), and exact cancelation.

Signed-zero inputs are valid when the sum is nonzero. Quotients follow IEEE
sign XOR:

| Expression | Result |
|---|---|
| `+0 / positive finite` | `+0` |
| `-0 / positive finite` | `-0` |
| `+0 / negative finite` | `-0` |
| `-0 / negative finite` | `+0` |

A nonzero finite dividend divided by a nonzero finite sum cannot produce zero
except by underflow, which is allowed and rounds under RNE.

### 4.5 Overflow and underflow policy

Overflow is fail-closed:

- if the increasing sum overflows to `+inf` or `-inf`, reject with cause 3;
- if any quotient overflows to `+inf` or `-inf`, reject with cause 4, and all
  earlier quotient stores are overwritten by the marker.

There is no saturation to the largest finite magnitude. Underflow is not an
error: a quotient may round to a subnormal or to signed zero under RNE, with no
flush-to-zero and no denormals-are-zero.

### 4.6 Rounding

`FADD` for the sum and `FDIV` for each quotient use IEEE binary32
round-to-nearest, ties-to-even (RNE), with no FTZ/DAZ. Subnormal inputs, sums,
and quotients are preserved. There is no fused operation, no reciprocal
multiply, no reassociation, and no alternative rounding mode. The fixture
includes an exact subnormal case and an inexact `1/3` RNE case.

## 5. Fixture

The sparse inputs are generated in the guest at run time. A helper fills all
256 words with a base payload, then writes the listed `(index, payload)` pairs.
The expected output vector is generated the same way from literal IEEE
binary32 payloads. No host expected-value arithmetic is used at fixture build
time or run time.

Every success phase checks all 256 output words with integer `CMP`. Every
failure phase checks `r1=0`, the exact `r9` cause, `out[0]` equal to the exact
status word, and all 255 remaining words equal to `0xFFC0DEAD`.

| Phase | Runtime sparse input | Sum | Expected result |
|---:|---|---|---|
| 1 | `x[0]=2.0`, `x[64]=1.0`, `x[255]=1.0`, rest `+0` | `4.0` | `0.5` at 0, `0.25` at 64/255, `+0` elsewhere |
| 2 | `x[3]=-4.0`, `x[200]=-4.0`, rest `+0` | `-8.0` | `0.5` at 3/200, `-0` elsewhere |
| 3 | `x[0]=-0.0`, `x[1]=2.0`, rest `+0` | `2.0` | `-0` at 0, `1.0` at 1, `+0` elsewhere |
| 4 | `x[0]=x[1]=0x00000001`, rest `+0` | `0x00000002` | `0.5` at 0/1, `+0` elsewhere |
| 5 | `x[0..2]=1.0`, rest `+0` | `3.0` | `0x3EAAAAAB` (`1/3` RNE) at 0..2, `+0` elsewhere |
| 6 | `x[17]=0x7FC00123` (qNaN), rest `+0` | rejected | cause 1 |
| 7 | `x[200]=0x7F800000` (`+inf`), rest `+0` | rejected | cause 1 |
| 8 | `x[3]=0xFF800000` (`-inf`), rest `+0` | rejected | cause 1 |
| 9 | all `+0.0` | `+0.0` | cause 2 |
| 10 | all `-0.0` | `+0.0` | cause 2 |
| 11 | `x[0]=x[1]=0x7F7FFFFF` (`+max finite`) | `+inf` | cause 3 |
| 12 | `x[0]=x[1]=0xFF7FFFFF` (`-max finite`) | `-inf` | cause 3 |
| 13 | `x[0]=1.0`, `x[1]=2^127`, `x[2]=-2^127`, `x[3]=2^-100` | `2^-100` | `out[0]=2^100` is stored, then `x[1]/sum` overflows; cause 4 and all outputs become marker/status |
| 14 | phase-1 input with `out == x` | `4.0` | phase-1 quotients in all 256 aliased words |

Phase 4 is the no-FTZ/DAZ check: two minimum subnormals sum to the subnormal
`0x00000002`, and `0x00000001 / 0x00000002` is exactly `0.5`. Phase 5 is the
RNE check. Phase 13 deliberately causes a quotient overflow after one quotient
was already stored, proving that the failure path replaces the entire output.

## 6. Local execution evidence

Commands used from the repository root:

```sh
LC_ALL=C awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk \
  -v CMD=emit mth/tests/mth_vector_normalize256_f32_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/v_norm.nan
LC_ALL=C awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk \
  -v CMD=check /data/data/com.termux/files/usr/tmp/opencode/v_norm.nan

/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/v_norm.nan \
  --steps 2000000 --serial
```

Observed result on 2026-11-07:

```text
[nan_cli] nan-text: 118122 steps, rc=3, pc=271, trap=''
MTH VECTOR NORMALIZE256 F32 PASS
```

| Field | Value |
|---|---|
| Marker | `MTH VECTOR NORMALIZE256 F32 PASS` |
| Steps | `118122` |
| Guest status | `rc=3` (`NAN_HALTED` from the final `HALT`) |
| Host exit | `0` |
| PC | `271` |
| Trap | `''` (empty) |
| Emitted words | `8210` |
| `nmk -v CMD=check` | `0 mismatches` |
| SHA-256 of `v_norm.nan` | `f1446822b5b08fbf71e5bb70a6db5eed83f2bfe401f396af7cd7b117b31c5799` |

A budget of `118121` steps produces `rc=0` at `pc=270`, one instruction before
the `HALT`, while the serial marker has already been printed. The marker alone
therefore is not proof of completion under a truncated step budget; the exact
halt step count is. The expected-value checks themselves run inside the guest.

## 7. Limitations

- Canonical CI executed the registered fixture in run `42539617226`.
- The divisor is the defined sequential 256-term `FADD` sum, not a correctly
  rounded exact sum. Results are not guaranteed to equal a high-precision
  normalization, and changing the accumulation order would change results.
- No span, length, alignment, or type validation. Exact `out == x` aliasing is
  safe; partial overlap is not. Callers own the address and overlap contract.
- Failure is reported through `r1`, `r9`, and the output words. The marker and
  status words are diagnostic NaN payloads and are not a valid normalized
  vector; a caller that ignores `r1` can still read them as data.
- NaN payload propagation is not defined because any NaN input is rejected.
  There is no signaling/quieting policy for successful arithmetic.
- Subnormal preservation is declared and covered by one exact subnormal case,
  but the fixture does not exhaustively test subnormal `FADD`/`FDIV` rounding
  or underflow boundaries.
- Cause 3 is non-finite sum. With all non-finite inputs already rejected, it is
  reached only by finite-input overflow to `+inf` or `-inf`, not by a NaN sum.
- This is a scalar-instruction sequence, not a vectorized, fused, or
  compensated implementation, and no performance claim is made.
