# MTH R9 bounded adapter residual (128-dim)

Status: source-written and locally executed with the canonical NaN0S toolchain; CI promotion pending.

## 1. Scope

`mth/nan16/mth_adapter_residual_128.nas` implements the arithmetic side of the
R9 adapter residual from `docs/MTH_LM_ADAPTER_ABI.md`:

```
scratch = C u
out[i]  = h[i] + beta * scratch[i]        for i = 0..127
```

`h` is the frozen base state, `u` is the bounded readout state, `C` is a dense
typed decode map, and `beta` is the residual scale. The composition computes
the residual only; it does not enable an adapter, train anything, or claim an
LM improvement.

The matrix-vector product is the verified `mth_matvec128_f32.nas` kernel,
included and called unchanged.

## 2. ABI

| Register | Meaning |
|---|---|
| `r1` | `h`, 128 float32 base state |
| `r2` | `C`, 16,384 float32, row-major 128x128 decode map |
| `r3` | `u`, 128 float32 readout state |
| `r4` | `beta`, one float32, passed by value |
| `r5` | `out`, 128 float32 output |
| `r6` | `scratch`, 128 float32 caller-owned workspace |
| `r13` | 1 |
| return | `r1=1` success; `r1=0` if the matvec primitive reports failure |

Memory: `C` 16,384 + `h`/`u`/`out` 384 + `scratch` 128 = 16,896 words. The
five static-slot words described below are outside those ABI spans. `h`, `u`,
`C`, `out`, and `scratch` must be distinct, non-overlapping spans; this is a
caller precondition. Inputs are read-only except `out` and `scratch`.

The kernel clobbers `r1-r12` and `r14`; it preserves `r13` and `r15`, so it is
safe to call with ordinary `CALL`/`RET`. It saves `r15` and the arguments that
the matvec clobbers in words 768..772 (`mth_adapter_residual_save_ret` through
`mth_adapter_residual_save_scratch`). A caller embedding this kernel must keep
code and data out of that five-word range. Because those slots are static, the
kernel is not reentrant and concurrent or nested use requires separate images.

## 3. Arithmetic order

1. `scratch = C u` via `mth_matvec128_f32` (increasing `j`, one accumulator,
   no FMA or reordering).
2. For increasing `i = 0..127`: load `h[i]`, load `scratch[i]`, one `FMUL` by
   `beta`, one `FADD`, store `out[i]`.

There is no host math, no FMA, no vector reassociation, and no hidden temporary
outside the declared memory. `beta`'s `[0,1]` bound and finiteness are
contract/caller preconditions from the R9 adapter descriptor; this arithmetic
kernel does not validate them and does not validate overlap, NaN, or Inf.

## 4. Fixture and local evidence

`mth/tests/mth_adapter_residual_128_test.nas` builds `C=2I` programmatically,
sets `h=1` and `u=1`, and checks:

- `scratch` equals `2.0` at indices 0, 64, and 127;
- `out` equals `2.0` for all 128 entries with `beta=0.5`;
- after poisoning `out` with `77.0`, `beta=0` rewrites all 128 entries to
  `h=1.0`.

The all-entry checks include the sample and endpoint indices. Fixture arrays
start at word 1024, after the kernel's reserved static-slot range; the data
spans total 16,896 words as declared above.

Canonical local run:

```
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=emit mth/tests/mth_adapter_residual_128_test.nas > /data/data/com.termux/files/usr/tmp/opencode/adapter.nan
/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli --img /data/data/com.termux/files/usr/tmp/opencode/adapter.nan --steps 30000000 --serial
```

The assembler reports `words 18064`; the run output is:

```
[nan_cli] nan-text: 420587 steps, rc=3, pc=881, trap=''
MTH ADAPTER RESIDUAL 128 PASS
```

Step count 420,587 is well below the 30,000,000-step budget, and the emitted
image passes `nmk.awk -v CMD=check` with 0 mismatches.

## 5. Limitations

- 128-dimensional prototype only. Larger readout or hidden widths need a
  paged/tiled composition.
- `C` is dense 128x128 float32: 16,384 words of storage and 16,384
  multiply-accumulate terms per invocation. No sparsity, low-rank, or paging
  path is implemented.
- No training, ablation, held-out evaluation, or LM benefit is claimed; the
  R9 adapter remains disabled by contract. This document only evidences the
  bounded residual arithmetic.
- No overlap, NaN/Inf, or `beta` range validation. Malformed spans or
  non-finite values are caller errors.
- Static slots make the kernel non-reentrant; words 768..772 are reserved.
- One residual invocation per call. Batching and fusion into surrounding
  kernels are separate work.

## 6. Files

- `mth/nan16/mth_adapter_residual_128.nas` — the composition kernel.
- `mth/tests/mth_adapter_residual_128_test.nas` — the fixture above.
- `docs/MTH_ADAPTER_RESIDUAL_128_ABI.md` — this contract.
