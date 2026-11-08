# Native xorshift64 forward step

Status: source-written and executed locally with the canonical NaN0S toolchain
(`nan0s/tools/nmk.awk` and `nan0s/aarch64/android/nan_cli`) on 2026-11-08.
This is local native evidence only, not a CI claim. The manifest entry remains
`ci_verified=false` until the canonical workflow executes it.

## Scope

| Source | Operation | Output |
|---|---|---|
| `mth/nan16/mth_prng_xorshift64.nas` | Marsaglia xorshift64 forward step | two-word 64-bit state and value |

The kernel executes only NaN16 integer instructions. It performs no host
random-number generation, floating-point conversion, allocation, or fallback.
The fixture is `mth/tests/mth_prng_xorshift64_test.nas`.

## Representation and ABI

A 64-bit value is two consecutive class-10 (`+q/+q`) NaN16 payload words:

- word 0: bits 31..0
- word 1: bits 63..32

All addresses are NaN16 word indices. `r13` must be `1`.

| Register | Meaning |
|---|---|
| `r1` | input state address (2 words, read-only) |
| `r2` | output state address (2 words) |
| `r3` | output value address (2 words) |
| success | `r1=1`, outputs written |
| rejection | `r1=0`, outputs set to `0xFFFFFFFF_FFFFFFFF` |

The output spans may alias the input span or each other. Partial overlap is not
supported. Input halves are loaded before any output word is stored. The
all-zero state is rejected because it is a fixed point; the input words are not
modified on rejection.

## Algorithm

```
x ^= x << 13
x ^= x >> 7
x ^= x << 17
```

The implementation carries the high half into the low half (and vice versa)
with 32-bit shifts, masks, and `BOOL` operations. No 64-bit host operation is
used.

## Local evidence

Canonical seed `0x0123456789ABCDEF`:

| Step | Value |
|---|---|
| x0 | `0x0123456789ABCDEF` |
| x1 | `0x3F2800D6569E01B4` |
| x2 | `0x606F949A3CEBD0B7` |

Fixture coverage:

1. all-zero rejection and canonical marker;
2. known-answer sequence for the canonical seed;
3. independent one-bit-at-a-time reference over four seeds and three steps;
4. separate, in-place, and fully aliased output spans;
5. output-state/value consistency and class-10 framing.

Local command:

```sh
awk -f nan0s/tools/nmk.awk -v CMD=emit \
    mth/tests/mth_prng_xorshift64_test.nas > /tmp/prng.nan
nan0s/aarch64/android/nan_cli --img /tmp/prng.nan --steps 20000 --serial
```

Observed:

```
[nan_cli] nan-text: 5043 steps, rc=3, pc=222, trap=''
MTH PRNG XORSHIFT64 PASS
```

The canonical runner registers the fixture with a 20,000-step budget.

## Boundary

Seeded sampling, entropy estimation, and distribution conversion remain
separate operations. Host controllers must return typed `UNAVAILABLE` when a
required native sampling or PRNG kernel is not registered; they must not call
Python `random`, `secrets`, NumPy, or platform RNG as a substitute.
