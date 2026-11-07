# MTH 256-element deterministic colored noise

Status: source-written and locally executed with the canonical NaN0S toolchain; CI promotion pending.

## 1. Scope

`mth/nan16/mth_colored_noise_256.nas` generates a fixed-size, seeded,
first-order colored sequence:

```
state_0 = seed
out[0]  = U(state_0)
for i = 1..255:
  state_i = (1664525 * state_{i-1} + 1013904223) mod 2^32
  out[i]  = alpha*out[i-1] + (1-alpha)*U(state_i)
```

This is the deterministic AR(1)/leaky-integrator noise source for the R5
capacity/SNR experiments: the seed and `alpha` are explicit, every run is
bit-reproducible, and no host randomness or host math is involved. It is not
an arbitrary spectral shaper; the pole at `alpha` gives a one-parameter
low-pass color.

## 2. ABI

| Register | Meaning |
|---|---|
| `r1` | seed, one 32-bit integer payload (all 2^32 values accepted) |
| `r2` | out, 256 float32 payloads |
| `r3` | alpha, one float32 payload in `[0,1)` |
| `r13` | 1 |
| return | `r1=1` |
| clobbers | `r2-r11`; `r12-r14` are not touched |

`alpha` is a caller precondition, not a validated argument. Values outside
`[0,1)` are not clamped and have no defined color. `out[0]` is written before
the loop; exactly 256 words are written, in increasing `i`. The generator
keeps no state between calls: each call restarts from the supplied seed.

## 3. Exact arithmetic

### 3.1 Integer LCG

The state is a 32-bit unsigned integer held in a register. The NaN16
`MUL` instruction produces the low 32 bits of the product and `ADD` wraps
modulo 2^32, so these two instructions implement the recurrence exactly:

| Constant | Decimal | Hex |
|---|---|---|
| multiplier | `1664525` | `0x0019660D` |
| increment | `1013904223` | `0x3C6EF35F` |
| modulus | `2^32` | implicit register width |

This is the Numerical Recipes 32-bit LCG. No floating-point arithmetic is
used for the state transition.

### 3.2 Exact state-to-float map

`U` uses the top 24 state bits so that both the integer and the fraction are
exact in binary32:

```
u24  = state >> 8                  ; logical shift, 0 .. 2^24-1
s24  = int32(u24 - 2^23)           ; -2^23 .. 2^23-1, exactly 24 bits
U(s) = CVTIF(s24) * 2^-23          ; exactly [-1, 1)
```

`CVTIF` converts the signed 24-bit integer exactly because every integer in
`[-2^23, 2^23-1]` is representable in binary32. Multiplication by the exact
power of two `2^-23` (`0x34000000`) is also exact. Thus `U(state)` has no
rounding error and lies in `[-1, 1)`; the low 8 LCG bits do not affect the
current sample but remain part of the next state transition.

### 3.3 Float combination

`beta = 1.0 - alpha` is computed once with one `FSUB`. Each sample evaluates:

```
t1 = FMUL(alpha, out[i-1])
t2 = FMUL(beta, U(state_i))
out[i] = FADD(t1, t2)
```

The two products are evaluated before the sum; there is no fused multiply-add,
no reassociation, and no clamping. All operations are IEEE-754 binary32
round-to-nearest-even as provided by NaN16. The sequence is written in
increasing `i`.

For valid inputs, every output is finite and in `[-1,1]`: `U` is in `[-1,1)`,
`out[0]` is therefore in `[-1,1)`, and an exact convex combination of values
in `[-1,1]` cannot exceed that interval. Correctly rounded binary32 addition
cannot leave the interval either, because `1+2^-24` and `-1-2^-24` are the
nearest rounding boundaries and an exact value in `[-1,1]` is strictly inside
them.

For a white input of variance `Var(U)`, the stationary variance of this
recurrence is `Var(U) * (1-alpha)/(1+alpha)`. The generator therefore does not
hold total energy constant as `alpha` changes; a caller that needs unit
variance must rescale the output. Total energy is also non-monotonic over a
finite 256-sample window, so the fixture uses normalized lag-1 correlation
and first-difference energy for the color monotonicity checks.

## 4. Fixture

`mth/tests/mth_colored_noise_256_test.nas` uses seed `0x12345678` and checks:

1. **Repeatability.** Two calls with seed `0x12345678` and `alpha=0.5` into
   separate buffers are compared word-for-word over all 256 outputs.
2. **White limit.** With `alpha=0`, `out[i] = U(LCG^i(seed))`. The fixture
   checks six hard-coded leading values and index 255:

   | Index | Expected bits | Value |
   |---|---|---|
   | 0 | `0xBF5B9754` | -0.8577778339 |
   | 1 | `0xBDABCD90` | -0.0838881731 |
   | 2 | `0x3F1A60BC` | 0.6030385494 |
   | 3 | `0xBF34480C` | -0.7042243481 |
   | 4 | `0xBED28DAC` | -0.4112371206 |
   | 5 | `0x3D1BC1C0` | 0.0380265713 |
   | 255 | `0x3DD3A330` | 0.1033385992 |

3. **Range and finiteness.** Every generated output is checked as
   `abs(bits) <= 0x3F800000` and `abs(bits) < 0x7F800000`, so infinities and
   NaNs fail explicitly.
4. **Color monotonicity.** A fixed-seed sweep over
   `alpha = 0, 0.5, 0.9, 0.99, 0.999` computes three metrics in NaN16
   float32, in increasing index order:
   - same-sign adjacent pairs (nondecreasing);
   - first-difference energy `sum (out[i]-out[i-1])^2` (strictly decreasing);
   - normalized lag-1 correlation
     `sum(out[i]*out[i-1]) / sqrt(sum(out[i-1]^2)*sum(out[i]^2))`
     (strictly increasing).
5. **Strong-correlation limit.** At `alpha=0.999`, all 255 adjacent pairs
   must share a sign and the normalized lag-1 correlation must exceed `0.9999`.

The fixture stores the sweep metrics at word addresses `4704` (sign), `4709`
(first-difference energy) and `4714` (correlation) so `nan_cli --peek` can
show them.

## 5. Local canonical run

From the repository root:

```
mkdir -p /data/data/com.termux/files/usr/tmp/opencode/mth-colored-noise
LC_ALL=C awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=emit \
  mth/tests/mth_colored_noise_256_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/mth-colored-noise/colored_noise.nan

/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/mth-colored-noise/colored_noise.nan \
  --steps 4000000 --serial --peek 4704:15
```

Observed assembler output: `words 4814`.

Observed run:

```
[nan_cli] nan-text: 72318 steps, rc=3, pc=158, trap=''
MTH COLORED NOISE 256 PASS
0000008E
000000AB
000000CC
000000FF
000000FF
43114CFD
41CDECBB
3F664A1E
3C420DBB
396F6D2F
3DD27003
3F1304FB
3F6F040D
3F7FF899
3F7FFFFD
```

The first five words are the sign counts; the next five are the
first-difference energies; the last five are the normalized lag-1
correlations. Decoded metrics:

| alpha | same-sign pairs / 255 | first-difference energy | normalized lag-1 correlation |
|---|---|---|---|
| 0.0 | 142 | `0x43114CFD` = 145.3007355 | `0x3DD27003` = 0.102752708 |
| 0.5 | 171 | `0x41CDECBB` = 25.7405910 | `0x3F1304FB` = 0.574294746 |
| 0.9 | 204 | `0x3F664A1E` = 0.899568439 | `0x3F6F040D` = 0.933655560 |
| 0.99 | 255 | `0x3C420DBB` = 0.0118440939 | `0x3F7FF899` = 0.999887049 |
| 0.999 | 255 | `0x396F6D2F` = 0.0002283349 | `0x3F7FFFFD` = 0.999999821 |

The assembled image is reproducible: two independent assemblies produced the
same SHA-256, `a53218539e1b13bc05c69461354cb2a57d63a5f10ac80101a955417c1dbadcdb`,
and two runs produced identical stdout/stderr.

As an auxiliary check outside the guest, all 256 words at `alpha=0.5` and
`alpha=0.999` were read back with `--peek` and matched a separate
integer-LCG/binary32 model exactly. This was verification only; the generator
and fixture do not use host math at runtime.

## 6. Limitations

- One fixed 256-element block. There is no continuation call, streaming
  cursor, or returned LCG state; every call restarts from `seed`.
- First-order AR(1) color only. `alpha` sets one real pole; the primitive does
  not realize an arbitrary target covariance or `1/f^beta` spectrum.
- Only 24 of the 32 state bits influence the current sample. The full state
  still advances, so the sequence remains a full-period 32-bit LCG, but each
  output has 24-bit quantization.
- `alpha=1` is excluded because the ABI requires `alpha < 1`; at `alpha=1`
  the recurrence would freeze `out[0]` forever.
- Output variance depends on `alpha` and is not normalized. No mean removal,
  unit-variance scaling, or spectral calibration is performed.
- The metric sweep is a fixed deterministic regression, not a statistical
  test over many seeds. It is intended to catch sign/order regressions, not to
  certify spectral accuracy.
- The fixture is not registered in `tools/run_mth_fixtures.py` or the CI
  workflow because those are shared files outside this task's ownership.
  Promotion requires adding it there after review.
