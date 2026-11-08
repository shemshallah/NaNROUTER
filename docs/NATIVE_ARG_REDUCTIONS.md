# Native argmax and argmin for 256 float32 values

Status: source-written and locally executed PASS with the canonical NaN0S
`nmk.awk` assembler and `nan_cli` on 2026-11-07. This is local native
evidence only, not a CI claim. The two sources and two fixtures are not
registered in `tools/run_mth_fixtures.py`, any manifest, or any capability
registry by this change; those files are outside this change's owned set.

## 1. Scope

This document defines two stateless NaN16 leaf kernels:

| Source | Operation | Outputs |
|---|---|---|
| `mth/nan16/mth_vector_argmax256_f32.nas` | index of the maximum | one index word, one float32 payload |
| `mth/nan16/mth_vector_argmin256_f32.nas` | index of the minimum | one index word, one float32 payload |

Each float32 value is one IEEE binary32 bit pattern stored in the 32-bit
payload of one NaN16 word. The kernels execute only NaN16 instructions.
There is no host math, allocation, hidden conversion, fused multiply-add,
reassociation, or arithmetic approximation.

The fixtures are:

- `mth/tests/mth_vector_argmax256_f32_test.nas`
- `mth/tests/mth_vector_argmin256_f32_test.nas`

## 2. ABI

Both entry points use the same two-output ABI:

| Register | Meaning |
|---|---|
| `r1` | `x`, 256 float32 payloads (read-only) |
| `r2` | `index_out`, one word: selected index `0..255` |
| `r3` | `value_out`, one float32 payload: exact `x[index_out]` bits |
| `r13` | must be `1` (element stride) |
| return `r1` | `1` on success; `0` on rejection |
| clobbers | `r1`, `r4`-`r8`, flags |
| preserves | `r0`, `r2`, `r3`, `r9`-`r15` |

`r0` is the zero constant. The kernels are leaf routines: they contain no
`CALL`, do not write `r15`, and have no static storage.

The result is:

```text
index_out = the first i in 0..255 that attains the maximum (argmax)
            or the minimum (argmin) of x[0..255]
value_out = x[index_out] with its original 32-bit payload
```

On success both output words are written exactly once, after the complete
input has been validated and scanned. On rejection `r1=0` and neither output
word is written. `r2` and `r3` must point to distinct writable words; if they
are the same word the second store replaces the first and the documented
two-word result is not available. The input span is read-only. Because all
input reads finish before the two final stores, the output words may alias
elements of the input span as long as the two output words are distinct.

## 3. Domain, rejection, ties, and signed zero

### 3.1 Finite-only fail-closed domain

The kernels accept only finite binary32 values: no NaN and no `+inf` or
`-inf`. Before the first output store, a preflight visits all 256 words and
tests

```text
(payload & 0x7F800000) == 0x7F800000
```

The mask exposes exactly the binary32 exponent field. An all-ones exponent
is the NaN and infinity class, so the test rejects every NaN payload
(quiet or signaling, either sign) and both infinities. The first such word
rejects the call with `r1=0`. A single status code covers the whole
non-finite class; the kernel does not distinguish NaN from infinity.

This is a deliberate finite-domain contract. The kernel does not attempt
IEEE `maxNum`/`minNum`, NaN ignoring, NaN propagation, or infinity ordering.
It never reports a valid index or value for a non-finite input, and the
rejection is atomic with respect to both output words. Finite denormals,
large finite magnitudes, and both zero signs are accepted.

### 3.2 Tie handling: first index

The scan visits indices in increasing order. The running best is replaced
only by a strict comparison:

```text
argmax: candidate > best -> take candidate
argmin: candidate < best -> take candidate
```

An equal candidate never replaces the current best. Therefore the first
index among equal extreme values wins. For an all-equal input the result is
`index_out=0` and `value_out=x[0]`.

### 3.3 Signed zero

`FCMP` treats `-0.0` and `+0.0` as equal. They are therefore one tie group:
the earlier index wins, and `value_out` preserves that occurrence's exact
payload. Examples:

| Input pattern | argmax result | argmin result |
|---|---|---|
| `x[3]=-0.0`, `x[100]=+0.0`, all others a negative finite value | index 3, value `0x80000000` | index 3, value `0x80000000` |
| `x[3]=+0.0`, `x[100]=-0.0`, all others a positive finite value | index 3, value `0x00000000` | index 3, value `0x00000000` |
| all 256 elements `-0.0` | index 0, value `0x80000000` | index 0, value `0x80000000` |

The kernels compare and copy payloads; they never canonicalize a zero or
perform arithmetic on it.

## 4. Algorithm and cost

Each kernel performs:

1. one preflight load, exponent mask, compare, and branch per input word
   (256 visits);
2. one seed `best = x[0]`, `best_index = 0`;
3. one load, one `FCMP`, one strict-predicate branch, and one loop branch
   per remaining index (255 visits);
4. two output stores after the scan.

For an accepted input the work is fixed and value-independent: 256
preflight visits, one seed load, and 255 scan visits. A rejected input
stops the preflight at the first non-finite word, so rejection work is at
most one full preflight and never reaches the scan or the output stores.
There is no value-dependent branch count in the accepted path, recursion,
sorting, or allocation. The kernels are reentrant and safe to run
concurrently on distinct inputs and outputs because they have no mutable
static state.

No float arithmetic other than `FCMP` is executed. The only float
operations are exact binary32 ordering comparisons; the selected value is
copied bit-for-bit.

## 5. Memory budget

| Object | NaN16 words | Bytes |
|---|---:|---:|
| `x` (input, read-only) | 256 | 2,048 |
| `index_out` (caller) | 1 | 8 |
| `value_out` (caller) | 1 | 8 |
| **Caller-visible working set** | **258** | **2,064** |

There is no private storage. Each kernel text image is 32 words. Each
committed fixture image is 1,552 words = 12,416 bytes, below both the
historical 65,536-word / 512 KiB ceiling and the 131,072-word / 1 MiB guest
target.

## 6. Fixtures

Every expected value below is an IEEE binary32 payload constant embedded in
the fixture. All checks use native integer `CMP`; no host-side expected
value is consulted while the guest runs. Rejection checks first fill both
output words with the sentinel `0xDEADBEEF`, call the kernel, require
`r1=0`, and then require both sentinel words to be unchanged.

### 6.1 Argmax fixture

`mth/tests/mth_vector_argmax256_f32_test.nas` covers:

| Case | Input | Expected |
|---|---|---|
| distinct maximum | `x[i] = (float)(i-128)` | index 255, `127.0` = `0x42FE0000` |
| maximum tie | `5.0` at 10, 77, 200; `4.0` at 255; `-1.0` elsewhere | index 10, `0x40A00000` |
| negative maximum tie | `-2.0` at 3, 8, 100; `-3.0` at 200; `-9.0` elsewhere | index 3, `0xC0000000` |
| all equal positive | all `3.25` | index 0, `0x40500000` |
| all equal negative | all `-2.5` | index 0, `0xC0200000` |
| signed zero, `-0.0` first | `-0.0` at 3, `+0.0` at 100, `-1.0` elsewhere | index 3, `0x80000000` |
| signed zero, `+0.0` first | `+0.0` at 3, `-0.0` at 100, `-1.0` elsewhere | index 3, `0x00000000` |
| signaling NaN at last index | `0x7F800001` at 255 | reject, outputs untouched |
| negative NaN at first index | `0xFFC00000` at 0 | reject, outputs untouched |
| positive infinity | `0x7F800000` at 42 | reject, outputs untouched |
| negative infinity | `0xFF800000` at 128 | reject, outputs untouched |
| recovery | restore `x[i] = (float)(i-128)` | index 255, `0x42FE0000` |

The two signed-zero cases prove that equality keeps the earlier index and
that the earlier occurrence's exact zero-sign payload is returned. The
signaling-NaN case at index 255 and the quiet-NaN case at index 0 cover
both NaN classes and prove that the preflight covers the whole span and
that no output is written on rejection.

### 6.2 Argmin fixture

`mth/tests/mth_vector_argmin256_f32_test.nas` covers:

| Case | Input | Expected |
|---|---|---|
| distinct minimum | `x[i] = (float)(i-128)` | index 0, `-128.0` = `0xC3000000` |
| minimum tie | `-5.0` at 10, 77, 200; `-4.0` at 255; `1.0` elsewhere | index 10, `0xC0A00000` |
| positive minimum tie | `2.0` at 3, 8, 100; `3.0` at 200; `9.0` elsewhere | index 3, `0x40000000` |
| all equal positive | all `3.25` | index 0, `0x40500000` |
| all equal negative | all `-2.5` | index 0, `0xC0200000` |
| signed zero, `-0.0` first | `-0.0` at 3, `+0.0` at 100, `1.0` elsewhere | index 3, `0x80000000` |
| signed zero, `+0.0` first | `+0.0` at 3, `-0.0` at 100, `1.0` elsewhere | index 3, `0x00000000` |
| signaling NaN at last index | `0x7F800001` at 255 | reject, outputs untouched |
| negative NaN at first index | `0xFFC00000` at 0 | reject, outputs untouched |
| positive infinity | `0x7F800000` at 42 | reject, outputs untouched |
| negative infinity | `0xFF800000` at 128 | reject, outputs untouched |
| recovery | restore `x[i] = (float)(i-128)` | index 0, `0xC3000000` |

The argmin fixture mirrors the argmax fixture so the tie, signed-zero, and
rejection rules are checked for both comparison directions.

## 7. Local canonical run

From the repository root:

```sh
LC_ALL=C awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk \
  -v CMD=emit mth/tests/mth_vector_argmax256_f32_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/argmax256_test.nan
LC_ALL=C awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk \
  -v CMD=check /data/data/com.termux/files/usr/tmp/opencode/argmax256_test.nan

/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/argmax256_test.nan \
  --steps 2000000 --serial
```

The same commands were run for `argmin256_test.nan`, and kernel-only
assembly checks were run for both `mth/nan16/` sources.

Observed results on 2026-11-07:

| Image | Marker | Steps | `nan_cli` status | Emitted words | `nmk -v CMD=check` |
|---|---|---:|---|---:|---|
| argmax fixture | `MTH VECTOR ARGMAX256 F32 PASS` | 62,218 | `rc=3`, `pc=186`, `trap=''` | 1,552 | 0 mismatches |
| argmin fixture | `MTH VECTOR ARGMIN256 F32 PASS` | 61,708 | `rc=3`, `pc=186`, `trap=''` | 1,552 | 0 mismatches |
| argmax kernel | — | — | — | 32 | 0 mismatches |
| argmin kernel | — | — | — | 32 | 0 mismatches |

`rc=3` is `NAN_HALTED` from the fixture's final `HALT`; `trap=''` means no
gate or opcode trap. A budget one step smaller (`62,217` for argmax and
`61,707` for argmin) produces `rc=0` at `pc=185`; the PASS marker still
appears because it is printed immediately before the `HALT`, so the full
step count is the evidence that the halt was reached. The step counts are
the exact `nan_cli` counters at the halt.

SHA-256 of the emitted text images:

```text
15a7aa91c32e8b8d87401e222dacdf7ba3bfd25d4e83a2220fc5c8bcad934c8f  argmax256_test.nan
429584104bdb4aee1cbb7cfd23877d4b101edcbfda8d5752bffafe88de9e82aa  argmin256_test.nan
ed0870b5a7dc3079a8870443fd461e402b38af50078c214f3161455f46eee727  argmax256_kernel.nan
05779e5494a30b277983fdac46657afd56f91b0e10a9e7b25dd82cf994d6eb63  argmin256_kernel.nan
```

As a supplementary, uncommitted local check, a temporary seeded 256-value
fixture containing duplicates, both zero signs, negatives, and several
exponent ranges ran both kernels and printed `TMP ARG CROSS PASS` after
9,429 steps (`rc=3`, `trap=''`, 1,546 emitted words, 0 check mismatches).
Its expected index and value were fixed fixture data derived outside the
guest; it is not part of this change.

The fixtures were also run against temporary mutated kernels: changing
argmax `GT` to `GE`, changing argmin `LT` to `LE`, and zeroing either
kernel's exponent-mask preflight each produced the corresponding `FAIL`
marker. Those mutated sources were not committed; the checks confirm that
the tie and rejection phases are sensitive to real defects.

## 8. Limitations

- Exactly 256 input words. There is no length parameter or shorter-span
  variant.
- Finite binary32 inputs only. NaN and both infinities are rejected with
  the single status `r1=0`; there is no NaN-versus-infinity distinction and
  no NaN ordering policy. Callers that need non-finite inputs must
  preprocess them before calling.
- The ABI returns the index and value through `r2` and `r3`. There is no
  register-return variant. The two output words must be distinct.
- No pointer, span, alignment, or type validation. The caller must supply a
  readable 256-word input and two writable, distinct output words. Output
  words may overlap the input because all reads finish before the stores,
  but the two output words must not overlap each other.
- The kernels are stateless and reentrant, but they do not guard against
  concurrent writers to the same output words or input span.
- Local `nan_cli` execution only. No CI run has been observed for these
  kernels or fixtures, and they are not registered in the fixture runner,
  manifest, or capability registry. This document does not claim CI
  verification.
