# MTH 128-element complex phase-coherence metric

Status: source-written and locally executed with the canonical NaN0S toolchain; CI promotion pending.

## 1. Scope

`mth/nan16/mth_phase_coherence_128.nas` computes the phase-coherence ratio of 128 complex float32 samples `z_i = re[i] + i*im[i]`:

```
sum_re  = sum_i re[i]
sum_im  = sum_i im[i]
mag_sum = sum_i sqrt(re[i]^2 + im[i]^2)

R = sqrt(sum_re^2 + sum_im^2) / mag_sum,   or 0 when mag_sum == 0
```

`R` is the normalized length of the vector sum: `R = 1` means the samples add with a common phase, `R = 0` means the phasors cancel or the total magnitude is zero. This is a fixed-size float32 kernel for the phase-coherence metric family; it is not a spectral estimate and does not use host math.

## 2. ABI

| Register | Meaning |
|---|---|
| `r1` | `re`, 128 float32 payloads |
| `r2` | `im`, 128 float32 payloads |
| `r3` | output, one float32 payload (receives `R`) |
| `r13` | 1 |
| return `r1` | 1 success |
| clobbers | `r4-r12` |

Inputs are read-only. `r3` is written once, after all 128 pairs have been read.

## 3. Arithmetic policy

- Complex components are treated as independent float32 values; there is no complex type or packing.
- `|z_i|` is computed as `FSQRT(FADD(FMUL(re,re), FMUL(im,im)))`, not with a scaled `hypot`.
- All three accumulators (`sum_re`, `sum_im`, `mag_sum`) add in increasing index order `i = 0..127`.
- The vector magnitude is `FSQRT(FADD(FMUL(sum_re,sum_re), FMUL(sum_im,sum_im)))`.
- The final ratio is one `FDIV`.
- Only `FADD`, `FSUB`, `FMUL`, `FSQRT`, and `FDIV` are used for float arithmetic. No host math, no reordering, no fused multiply-add, and no clamping.
- Rounding is IEEE-754 binary32 round-to-nearest-even, as provided by NaN16.

### Zero and scalar policy

- The only special case is `mag_sum == 0` (tested with float `FCMP`): the kernel stores `+0.0` and still returns `r1=1`. There is no separate error return.
- A single zero sample contributes zero to all three sums and does not change `R`.
- Because `mag_sum` is a sum of nonnegative square roots, an all-zero input yields `+0.0` and takes the zero branch.
- The result is not clamped to `[0,1]`; in exact arithmetic `R` lies in that interval, but float32 rounding can in principle put a measured value a few ulps outside it.

## 4. Fixture

`mth/tests/mth_phase_coherence_128_test.nas` checks exact bit patterns (`CMP` on the stored word):

- all `z = 1 + 0i` -> `R = 1.0` (`0x3F800000`), because `sum_re = 128` and `mag_sum = 128` are exact;
- 64 samples `z = 1 + 0i` followed by 64 samples `z = -1 + 0i` -> vector sum `0`, `mag_sum = 128`, `R = 0.0`;
- all `z = 0 + 1i` -> `R = 1.0`, exercising the imaginary accumulator and the `im^2` term;
- all `z = 0 + 0i` -> `mag_sum = 0`, zero policy stores `0.0`.

The exact `1.0` and `0.0` comparisons are valid because both fixtures produce exactly representable intermediate sums and magnitudes.

## 5. Local canonical run

From the repository root:

```
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=emit \
  mth/tests/mth_phase_coherence_128_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/phasecoh.nan
/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/phasecoh.nan \
  --steps 4000000 --serial
```

Observed output:

```
words 3152
[nan_cli] nan-text: 11381 steps, rc=3, pc=135, trap=''
MTH PHASE COHERENCE 128 PASS
```

`rc=3` is `HALT`; the run completed well inside the 4,000,000-step budget.

## 6. Limitations

- Fixed at exactly 128 complex samples; larger or streaming inputs need tiling or a separate kernel.
- `re` and `im` must be two non-overlapping 128-word float32 spans. No stride or offset parameter exists.
- Plain `re^2 + im^2` can overflow to `+inf` for large components and underflow to `0` for tiny components; there is no scaling or `hypot` guard. Overflow can propagate to `inf`, and an `inf/inf` vector/magnitude pair can produce `NaN`.
- Input `NaN` propagates into the sums. `FCMP` is unordered for `NaN`, so the zero branch is skipped and the output becomes `NaN`; there is no NaN rejection or canonicalization.
- Sequential float32 accumulation is not compensated. On adversarial data it can differ by a few ulps from a higher-precision reference, and it is not intended as a numerically robust estimator for near-cancellation cases.
- The scalar metric ignores per-sample weighting and any time ordering; it reports only the phase-coherence ratio of the supplied 128 pairs.
- `R` alone cannot distinguish "no signal" from "perfect cancellation": the all-zero fixtures use the explicit zero policy, and a nonzero `mag_sum` with `R = 0` means cancellation.
