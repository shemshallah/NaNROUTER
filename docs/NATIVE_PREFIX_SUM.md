# Native inclusive prefix sum over 256 unsigned 32-bit words

Status: source-written, locally executed, and CI-verified in canonical run
`42539617226` with the pinned NaN0S toolchain. The source and fixture are
registered in `spec/wave-capabilities.json` with `ci_verified=true`.

## 1. Scope

This document defines one NaN16 leaf kernel:

| Source | Operation | Output shape |
|---|---|---|
| `mth/nan16/mth_vector_prefix_sum256_u32.nas` | inclusive prefix sum | 256 unsigned 32-bit words |

Each value is one unsigned 32-bit payload stored in a NaN16 word. The kernel
executes only NaN16 integer instructions. There is no host math, allocation,
conversion, reassociation, saturation, or hidden widening to 64 bits.

The fixture is `mth/tests/mth_vector_prefix_sum256_u32_test.nas`.

## 2. ABI

All addresses are NaN16 word indices. `r13` must be `1`; the kernel uses it as
the element stride.

| Register | Meaning |
|---|---|
| `r1` | `x`, 256 U32 input words |
| `r2` | `out`, 256 U32 output words |
| `r13` | `1` (element stride) |
| return `r1` | `1` on success, `0` on unsigned overflow |
| clobbers | `r1`, `r4`-`r8`, condition flags |
| preserves | `r0`, `r2`, `r3`, `r9`-`r15` |

`r0` is the zero constant. The entry point is a leaf routine: it contains no
`CALL`, does not write `r15`, and has no static storage or workspace.

The caller supplies a readable 256-word input span and a writable 256-word
output span. There is no span, length, alignment, alias, or type validation;
those are caller preconditions.

## 3. Operation and overflow convention

On success:

```text
out[0] = x[0]
out[i] = out[i-1] + x[i]        for i = 1..255, in increasing i
```

The seed copies `x[0]` with one load and one store. Each remaining element
loads `x[i]`, adds it to the running accumulator with exactly one 32-bit `ADD`,
and stores the sum. No addition is reordered, reassociated, split, or widened.

Unsigned overflow is detected as the carry out of that addition:

```text
sum = acc + x[i]
if sum < acc: overflow
```

`CMP` is unsigned on this core, so `sum < acc` is exactly the carry condition
for adding two non-negative 32-bit values. The kernel never publishes a wrapped
sum as a valid result.

Let `i` be the first index in `1..255` whose exact sum exceeds `UINT32_MAX`
(`0xFFFFFFFF`). Overflow cannot occur at `i=0` because that output is the seed
copy, not an addition. On that event the kernel:

1. keeps `out[0..i-1]` as the exact inclusive prefix sums already committed;
2. stops reading `x` and stops adding;
3. fills `out[i..255]` with the canonical marker `0xFFFFFFFF`
   (`UINT32_MAX`);
4. returns `r1=0`.

Thus the complete 256-word output span is deterministic in both outcomes:

| Outcome | `out[0..i-1]` | `out[i..255]` | return |
|---|---|---|---|
| success (all 256 sums fit) | exact prefix sums | exact prefix sums | `r1=1` |
| overflow at `i` | exact prefix sums | `0xFFFFFFFF` marker | `r1=0` |

The marker is a sentinel only. A legitimate prefix sum can also equal
`0xFFFFFFFF`, so `r1` is the authoritative status; the output words alone do
not distinguish a marker from a valid sum. The operation is not atomic: on
overflow the caller observes the committed prefix and the marker suffix, and
there is no rollback.

The marker fill writes every remaining output word and uses no input read and
no arithmetic on the marker. An overflowing call therefore performs the seed,
`i` addition steps, and at most `256-i` marker stores.

## 4. Aliasing and memory

Exact output aliasing, `out == x`, is safe on both outcomes:

- `x[i]` is loaded before `out[i]` is stored;
- the recurrence reads `out[i-1]` as its accumulator state, which is exactly
  the prefix value the in-place algorithm needs.

On success with `out == x`, the input span becomes the prefix sums. On overflow
with `out == x`, the committed prefix and the marker fill overwrite all 256
input words, so the original input is not recoverable from the span. Partial
overlap between `x` and `out` is not safe.

The kernel has no private storage. Its caller-visible working set is the two
256-word spans, and the fixture image is described in section 6.

## 5. Fixture coverage

`mth/tests/mth_vector_prefix_sum256_u32_test.nas` generates every input at
runtime. All 256 output words are checked inside the guest with integer
`CMP`; no host-side expected-value arithmetic is used and there is no static
expected-output table.

| Phase | Input generated in the guest | Expected result | Checks |
|---|---|---|---|
| 1 | `x[i] = i+1` | `out[i] = (i+1)(i+2)/2` | all 256 words |
| 2 | all `x[i] = 0` | all `out[i] = 0` | all 256 words |
| 3 | `x[0] = 0xFFFFFFFF`, `x[1..255] = 0` | all `out[i] = 0xFFFFFFFF` | all 256 words |
| 4 | all `x[i] = 0xFFFFFFFF` | overflow at `i=1`; seed `out[0] = 0xFFFFFFFF`, marker `out[1..255] = 0xFFFFFFFF` | all 256 words; `r1=0` |
| 5 | `x[0] = 0xFFFFFF80`, `x[1..255] = 1` | overflow at `i=128`; `out[0..127] = 0xFFFFFF80+k`, `out[128..255] = 0xFFFFFFFF` | all 256 words; `r1=0` |
| 6 | `x[i] = i+1`, exact alias `out==x` | same triangular results as phase 1 | all 256 words |
| 7 | phase-5 input, exact alias `out==x` | same prefix/marker result as phase 5 | all 256 words; `r1=0` |

Phase 1 computes the expected triangular numbers independently with
`n(n+1)/2` (`MUL` then `SHR` by one), not with a second running prefix sum.
Phases 1-5 pre-fill `out` with `0xDEADBEEF`, so an unwritten output word cannot
pass by inheriting a previous phase's value. Phase 4 exercises the earliest
possible overflow (the second word of an all-maximum input). Phase 5 proves
the marker fill actually wrote all 128 suffix words. Phase 7 proves the
documented in-place overflow behaviour after the input span has been
overwritten.

Fixture layout:

| Label | Word address | Extent |
|---|---:|---:|
| code and helpers | 0 | below 1024 |
| `x` | 1024 | 256 words |
| `out` | 2048 | 256 words |
| PASS and FAIL strings | 4096 | 18 words |
| emitted image | — | 4,114 words |

## 6. Local execution evidence

Commands used from the repository root on 2026-11-07:

```sh
cd /data/data/com.termux/files/home/NaNROUTER
LC_ALL=C awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk \
  -v CMD=emit mth/tests/mth_vector_prefix_sum256_u32_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/mth_vector_prefix_sum256_u32_test.nan
LC_ALL=C awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk \
  -v CMD=check \
  /data/data/com.termux/files/usr/tmp/opencode/mth_vector_prefix_sum256_u32_test.nan
/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/mth_vector_prefix_sum256_u32_test.nan \
  --steps 2000000 --serial
```

Observed output:

```text
words 4114
check: 0 mismatches
[nan_cli] nan-text: 49559 steps, rc=3, pc=157, trap=''
MTH VECTOR PREFIX SUM256 U32 PASS
exit=0
```

| Field | Value |
|---|---|
| Marker | `MTH VECTOR PREFIX SUM256 U32 PASS` |
| Exact halt step | `49559` |
| Guest status | `rc=3` (`NAN_HALTED` from the final `HALT`) |
| Host exit | `0` |
| PC | `157` |
| Trap | `''` (empty) |
| Emitted words | `4114` |
| Emitted text size | `132609` bytes |
| `nmk -v CMD=check` | `0 mismatches` |
| SHA-256 of the `.nan` image | `c13766496229012f5f0276178f46c3f5ca4684c10ea47e0a861e97963d97a407` |

A run with a budget of `49558` steps stops at `rc=0`, `pc=156`, one
instruction before the `HALT`; the PASS marker is still present in the serial
buffer at that point. The exact halt step count is `49559`, and the marker
alone is not treated as proof when a truncated budget is used.

## 7. Limitations

- Canonical CI executed the registered fixture in run `42539617226`.
- One fixed 256-word block only. There is no arbitrary length, segmented scan,
  carry chaining between blocks, scaled prefix sum, or parallel/reassociated
  implementation.
- `r13` must be exactly `1`; the kernel does not validate or repair it.
- No span, length, alignment, alias, or overlap validation. Exact `out==x` is
  safe; partial overlap is not.
- Overflow handling is not atomic and has no rollback. The committed prefix
  remains visible and the suffix is replaced by `0xFFFFFFFF`.
- The marker `0xFFFFFFFF` is indistinguishable from a legitimate prefix sum
  of the same value. The return register `r1` is the only status signal.
- On overflow with `out==x`, the whole input span is overwritten by the prefix
  and marker and cannot be reused as the original input.
- The overflow test is an unsigned 32-bit carry test. There is no signed
  overflow interpretation, saturation, floating-point prefix sum, or 64-bit
  accumulator.
- The kernel performs no input validation, no fault handling, and no
  capability/admission check; those belong to the caller or a higher layer.
