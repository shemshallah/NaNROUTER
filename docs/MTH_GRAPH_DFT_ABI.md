# MTH 256-point direct DFT (NaN16 float32 reference)

Files:

- `mth/nan16/mth_graph_dft256.nas` — the kernel.
- `mth/tests/mth_graph_dft256_test.nas` — the executable fixture.

This is a direct O(256²) complex DFT reference, not an FFT. It is pure
NaN16: all arithmetic is `FADD`/`FSUB`/`FMUL` on float32 payloads. The
kernel never calls host `sin`/`cos` and never builds a twiddle table.

## ABI

Call with `r13=1`:

| Register | Meaning |
| --- | --- |
| `r1` | real input `x_re[256]`, float32 |
| `r2` | imaginary input `x_im[256]`, float32 |
| `r3` | twiddle real `W_re[256]`, float32 |
| `r4` | twiddle imaginary `W_im[256]`, float32 |
| `r5` | real output `X_re[256]`, float32 |
| `r6` | imaginary output `X_im[256]`, float32 |

All six arrays must be distinct and pairwise non-overlapping. Inputs are
not modified. Outputs need not be initialized: every `X[k]` is written.
There is no scratch argument and no malformed-input status. The caller
owns the extents.

Return: `r1=1`. There are no failure returns.

Register effects: `r1`–`r12` and `r14` are clobbered; `r13` remains 1;
`r15` is preserved so ordinary `CALL`/`RET` works. `r0` is used as a
temporary and restored to 0 before return. The kernel uses no static
state and no `CALL`, so separate invocations are independent as long as
their arrays are disjoint.

## Transform and twiddle convention

For `N=256`:

```text
W        = exp(-2*pi*i/256)
W_re[k]  = cos(2*pi*k/256)
W_im[k]  = -sin(2*pi*k/256)
X[k]     = sum(n=0..255) x[n] * (W^k)^n
```

The caller supplies all 256 powers `W^k`, `k=0..255`. The kernel does
not index the table by `k*n mod 256`; it reads only `W^k` for the current
bin and advances the runtime power by repeated complex multiplication.

For exact DC/Nyquist behaviour the caller must supply these entries
exactly:

```text
W^0   = ( 1,  0)
W^64  = ( 0, -1)
W^128 = (-1,  0)
W^192 = ( 0,  1)
```

Generic entries may be correctly rounded float32 approximations. The
kernel treats the supplied table as authoritative: twiddle error is not
corrected or renormalized.

## Recurrence and accumulation order

For each `k` independently:

```text
acc_re = +0.0f
acc_im = +0.0f
w_re   = +1.0f
w_im   = +0.0f

for n = 0..255:
    acc_re = acc_re + x_re[n]*w_re
    acc_re = acc_re - x_im[n]*w_im
    acc_im = acc_im + x_re[n]*w_im
    acc_im = acc_im + x_im[n]*w_re

    new_w_re = w_re*W_re[k] - w_im*W_im[k]
    new_w_im = w_re*W_im[k] + w_im*W_re[k]
    w_re = new_w_re
    w_im = new_w_im

X_re[k] = acc_re
X_im[k] = acc_im
```

Each line is one rounded float32 operation. The real accumulator gets
two separate additions per sample (one add, one subtract); the imaginary
accumulator gets two separate additions. There is no FMA, no compensated
summation, no extended precision, and no periodic renormalization of
`w`. Accumulation is in increasing `n`; bins are independent.

The recurrence means the effective power at step `n` is the product of
`n` float32-rounded complex multiplications, not a freshly rounded
`W^(k*n)`. Its error grows with `n`. An offline float32 simulation of the
same recurrence and fixture table predicts zero-bin magnitudes below
`7.7e-4`; the fixture enforces a `0.01` tolerance for non-exact bins.
This is a reference kernel, not a guaranteed-accuracy numerical library.

Implementation note: during each recurrence step the kernel temporarily
stores `new_w_re` in `X_re[k]`, then loads it back. The final `X[k]` is
stored after the `n` loop, so the output array must be writable and must
not overlap inputs or twiddles.

## Cost

Per call: 65,536 complex accumulation terms plus 65,536 complex power
updates. The fixture performs four kernel calls and measured **8,958,287
guest steps**, well below the 50,000,000-step run budget.

## Fixture and tested bins

Fixture: `mth/tests/mth_graph_dft256_test.nas`.

Command:

```sh
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk \
  -v CMD=emit mth/tests/mth_graph_dft256_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/dft.nan
/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/dft.nan \
  --steps 50000000 --serial
```

Observed output:

```text
[nan_cli] nan-text: 8958287 steps, rc=3, pc=225, trap=''
MTH GRAPH DFT256 PASS
```

`rc=3` is `NAN_HALTED`; `trap=''`.

The fixture generates `W^k` in-guest by the same complex recurrence,
starting from `W^1` with float32 bits:

```text
W^1 = 0x3F7FEC43 + i 0xBCC90AB0
```

It then forces the four exact quarter-turn entries listed above. Tests:

1. **Impulse at n=0** — all 256 bins must be exactly `1+0i`
   (bit-for-bit `0x3F800000`, `0x00000000`).
2. **Impulse at n=1** — all 256 bins must be bit-for-bit equal to the
   caller-supplied `W^k` table. This checks every output index and the
   table read path.
3. **DC**, `x_re[n]=1`, `x_im[n]=0` — `X[0]=256+0i` exactly;
   `X[64]`, `X[128]`, `X[192]` exactly zero; all other bins
   `|Re|,|Im| <= 0.01`.
4. **Nyquist**, `x_re[n]=(-1)^n`, `x_im[n]=0` — `X[128]=256+0i`
   exactly; `X[0]`, `X[64]`, `X[192]` exactly zero; all other bins
   `|Re|,|Im| <= 0.01`.

## Evidence status and limitations

- **Verified:** the fixture above assembles and runs to `PASS` on the
  stated toolchain and budget.
- **Verified:** exact special-bin behaviour for DC/Nyquist when the four
  quarter-turn twiddles are exact.
- **Verified:** all-bin impulse responses, including bit-exact agreement
  with the supplied twiddle table at `n=1`.
- **Not independently verified:** general complex-input DFT accuracy
  against a host/offline float64 or float32 reference. Only structured
  DC, Nyquist, and impulse inputs are tested.
- **Not independently verified:** twiddle-table generation accuracy. The
  fixture builds the table with the same recurrence the kernel uses;
  it does not embed an independently rounded `cos`/`sin` table.
- **Not covered:** NaN/Inf input policy (NaN16 FP propagation applies but
  is not tested), array-overlap detection, thread/concurrency stress, and
  performance beyond the fixture's step count.
- Generic bins are tolerance-tested, not exactness-tested. A future
  fixture should embed an independently generated 256-entry table and
  compare a nontrivial complex input against an offline reference.
