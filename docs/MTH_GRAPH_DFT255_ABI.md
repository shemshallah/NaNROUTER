# MTH 255-point direct DFT (NaN16 float32 reference)

Files:

- `mth/nan16/mth_graph_dft255.nas` — the kernel.
- `mth/tests/mth_graph_dft255_test.nas` — the executable fixture.

This is a direct O(255²) complex DFT reference, not an FFT. It is pure
NaN16: all arithmetic is `FADD`/`FSUB`/`FMUL` on float32 payloads. The
kernel never calls host `sin`/`cos` and never builds a twiddle table.
It is adapted from the verified 256-point reference; the only structural
changes are `N=255`, the end/cursor constants `255`, and the fixture's
twiddle construction for an odd length.

## ABI

Call with `r13=1`:

| Register | Meaning |
| --- | --- |
| `r1` | real input `x_re[255]`, float32 |
| `r2` | imaginary input `x_im[255]`, float32 |
| `r3` | twiddle real `W_re[255]`, float32 |
| `r4` | twiddle imaginary `W_im[255]`, float32 |
| `r5` | real output `X_re[255]`, float32 |
| `r6` | imaginary output `X_im[255]`, float32 |

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

For `N=255`:

```text
W        = exp(-2*pi*i/255)
W_re[k]  = cos(2*pi*k/255)
W_im[k]  = -sin(2*pi*k/255)
X[k]     = sum(n=0..254) x[n] * (W^k)^n
```

The caller supplies all 255 powers `W^k`, `k=0..254`. The kernel does
not index the table by `k*n mod 255`; it reads only `W^k` for the current
bin and advances the runtime power by repeated complex multiplication.

`W^0=(1,0)` is the only exactly representable special entry. Because
255 is odd, the table has no exact quarter turns (no `±i` entries) and
no exact Nyquist bin. Generic entries may be correctly rounded float32
approximations. The kernel treats the supplied table as authoritative:
twiddle error is not corrected or renormalized.

For the fixture, `W^1` is embedded as the correctly rounded float32
constant:

```text
W^1 = 0x3F7FEC1B + i 0xBCC9D47A
```

The fixture builds `k=1..127` in-guest by complex recurrence from that
constant, then fills `k=128..254` by the exact conjugate symmetry
`W^k = conj(W^(255-k))`. It performs no host math at runtime.

## Recurrence and accumulation order

For each `k` independently:

```text
acc_re = +0.0f
acc_im = +0.0f
w_re   = +1.0f
w_im   = +0.0f

for n = 0..254:
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
`w`. Accumulation is in increasing `n`; bins are independent. The power
advance is four `FMUL`, one `FSUB`, and one `FADD` per sample.

The recurrence means the effective power at step `n` is the product of
`n` float32-rounded complex multiplications, not a freshly rounded
`W^(k*n)`. Its error grows with `n`. An offline float32 simulation of the
same mirrored fixture table and the same accumulation order predicts a
maximum table component error of about `2.0e-6` versus float64 and a
maximum non-DC component of about `2.5e-4` for unit DC input. The fixture
enforces `0.01` for non-exact bins. This is a reference kernel, not a
guaranteed-accuracy numerical library.

Implementation note: during each recurrence step the kernel temporarily
stores `new_w_re` in `X_re[k]`, then loads it back. The final `X[k]` is
stored after the `n` loop, so the output array must be writable and must
not overlap inputs or twiddles.

## Cost

Per call: 65,025 complex accumulation terms plus 65,025 complex power
updates. The fixture performs three kernel calls (impulse at `n=0`,
impulse at `n=1`, and DC) and measured **6,666,266 guest steps**, below
the 40,000,000-step run budget.

## Fixture and tested bins

Fixture: `mth/tests/mth_graph_dft255_test.nas`. It allocates six adjacent
255-word float32 arrays at fixed `.org` regions starting at word 4096:
twiddle real/imag, input real/imag, output real/imag.

Command:

```sh
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk \
  -v CMD=emit mth/tests/mth_graph_dft255_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/dft255.nan
/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/dft255.nan \
  --steps 40000000 --serial
```

Observed output:

```text
[nan_cli] nan-text: 6666266 steps, rc=3, pc=161, trap=''
MTH GRAPH DFT255 PASS
```

`rc=3` is `NAN_HALTED`; `trap=''`.

Tests:

1. **Impulse at n=0** — all 255 bins must be exactly `1+0i`
   (bit-for-bit `0x3F800000`, `0x00000000`). This is independent of the
   twiddle values because `w=1` on the only nonzero sample.
2. **Impulse at n=1** — all 255 bins must be bit-for-bit equal to the
   caller-supplied `W^k` table. This checks every output index, the
   table read path, and the first recurrence step.
3. **DC**, `x_re[n]=1`, `x_im[n]=0` — `X[0]=255+0i` bit-for-bit;
   all bins `k=1..254` must satisfy `|Re|,|Im| <= 0.01`. The exact
   `X[0]` result follows from `W^0=(1,0)` and 255 exact unit additions.

## Evidence status and limitations

- **Verified:** the fixture above assembles and runs to `PASS` on the
  stated toolchain and step budget.
- **Verified:** exact all-bin impulse responses at `n=0`; bit-exact
  agreement with the supplied twiddle table at `n=1`; exact DC bin
  `X[0]=255`.
- **Verified by offline float32 simulation (not by a second in-guest
  reference):** the mirrored table's component error and the DC residual
  quoted above.
- **Not independently verified:** general complex-input DFT accuracy
  against a host/offline float64 or float32 reference. Only structured
  impulse and DC inputs are tested.
- **Not independently verified:** twiddle-table generation accuracy. The
  fixture builds the table in-guest from the same recurrence the kernel
  uses, plus conjugate symmetry; it does not embed an independently
  rounded 255-entry `cos`/`sin` table.
- **Not covered:** NaN/Inf input policy, array-overlap detection,
  thread/concurrency stress, and performance beyond the fixture's step
  count.
- Because `N=255` has no exact quarter turns, all zero bins except the
  structural `W^0` DC case are tolerance-tested, not exactness-tested.
  A future fixture should embed an independently generated 255-entry
  table and compare a nontrivial complex input against an offline
  reference.
