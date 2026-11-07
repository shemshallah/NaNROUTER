# MTH full 256×256 adapter residual

Status: source-written and locally executed with the canonical NaN0S `nmk.awk` /
`nan_cli` toolchain on 2026-11-07 through the `.nan` text loader. The fixture
image is 67,346 NaN16 words (538,768 bytes), which exceeds the historical
512 KiB (65,536-word) guest. It targets the 1 MiB (131,072-word) guest budget;
canonical GLT 1 MiB page-limit execution and CI promotion are still pending.

## 1. Scope

`mth/nan16/mth_adapter_residual_256_full.nas` computes the complete dense
adapter residual in one leaf call:

```
y[i] = h[i] + beta * sum_{j=0..255} W[i,j] * u[j]     for i = 0..255
```

where `h` is the frozen base state, `u` is the bounded 256-float32 readout
state, `W` is a dense typed decode map, and `beta` is the residual scale. The
kernel computes the residual arithmetic only; it does not enable an adapter,
train anything, or claim an LM improvement.

This is the monolithic form of `mth_adapter_residual_256_block16`: the caller
makes one call with the full 65,536-word `W` matrix instead of 16 calls over
16×256 blocks. The whole matrix is resident, so this kernel is intended for the
1 MiB guest budget; the block form remains the bounded path for the old
512 KiB budget.

## 2. ABI

| Register | Meaning |
|---|---|
| `r1` | `W`, 65,536 float32, row-major 256 rows × 256 columns |
| `r2` | `h`, 256 float32 |
| `r3` | `u`, 256 float32 |
| `r4` | `beta`, one float32, passed by value |
| `r5` | `y`, 256 float32 output |
| `r13` | 1 |
| return | `r1=1` |
| clobbers | `r1`, `r2`, `r5`-`r12`, `r14` |
| preserves | `r3`, `r4`, `r13`, `r15` |

The kernel is a leaf: no `CALL`, no static slots, no `.org` data, and no
self-modification. It is reentrant for distinct spans. `W`, `h`, and `u` are
read-only; only `y` is written. The four spans must be distinct and
non-overlapping, and `r13` must be 1; both are caller preconditions. `beta`'s
`[0,1]` bound and finiteness are contract preconditions from the adapter
descriptor; this arithmetic kernel does not validate them, and does not
validate overlap, NaN, or Inf.

## 3. Arithmetic order

For each row `i = 0..255`, one accumulator is seeded with `h[i]`; then, for
increasing `j = 0..255`, the kernel performs:

```
t1  = beta * W[i,j]
t2  = t1 * u[j]
acc = acc + t2
```

which is the left-to-right evaluation of

```
h[i] + beta*W[i,0]*u[0] + beta*W[i,1]*u[1] + ...
```

There are exactly two `FMUL` and one `FADD` per term, no FMA, no reordering,
and no host math. Because `beta` is applied per term before accumulation, the
result is not in general bitwise identical to the algebraically equivalent
`h[i] + beta * (sum_j W[i,j]*u[j])`, which would apply `beta` after the sum.
The per-row term order and the 256-row order are both increasing.

## 4. Memory budget

| Object | NaN16 words | Bytes |
|---|---:|---:|
| `W` (256×256 float32) | 65,536 | 524,288 |
| `h` | 256 | 2,048 |
| `u` | 256 | 2,048 |
| `y` | 256 | 2,048 |
| **Kernel working set** | **66,304** | **530,432** |
| 1 MiB guest budget | 131,072 | 1,048,576 |
| Remaining for code/scratch | 64,768 | 518,144 |

The fixture image is 67,346 words (538,768 bytes), including code and the two
marker strings, and leaves 63,726 words of the 1 MiB budget. The historical
512 KiB budget is 65,536 words: the working set alone exceeds it by 768 words
and the fixture image by 1,810 words. Do not use this kernel on a 512 KiB
guest; use `mth_adapter_residual_256_block16` there.

## 5. Fixture

`mth/tests/mth_adapter_residual_256_full_test.nas` lays out:

| Label | Word address |
|---|---:|
| code, kernel, and puts helper | 0 |
| `W` | 1,024 |
| `h` | 66,560 |
| `u` | 66,816 |
| `y` | 67,072 |
| pass/fail strings | 67,328 |

The fixture builds `W = 2I` programmatically (zero all 65,536 words, then set
`W[i,i]=2.0`, stride 257), sets `h=1.0` (256 words) and `u=1.0` (256 words),
and checks every one of the 256 outputs for each of:

- `beta=0.5` → `y[i] = 1 + 0.5*2 = 2.0`;
- after poisoning all 256 outputs with `77.0`, `beta=0` rewrites every output
  to `h=1.0`;
- after zeroing all 65,536 `W` words again and re-poisoning `y` with `77.0`,
  `beta=0.5` with `W=0` rewrites every output to `y=h=1.0`.

The third case uses a nonzero `beta` so that it actually exercises the
`W*u` term rather than duplicating the `beta=0` path. Every check covers all
256 entries, not a sample.

## 6. Local evidence

Commands:

```
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=emit \
  mth/tests/mth_adapter_residual_256_full_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/adapter256full.nan
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=check \
  /data/data/com.termux/files/usr/tmp/opencode/adapter256full.nan
/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/adapter256full.nan \
  --steps 20000000 --serial
```

Observed:

```
words 67346
check: 0 mismatches

stdout:
MTH ADAPTER RESIDUAL 256 FULL PASS

stderr:
[nan_cli] nan-text: 2839172 steps, rc=3, pc=179, trap=''

exit=0
```

`rc=3` is `NAN_HALTED` (the fixture's `HALT`); the trap string is empty.
2,839,172 steps is under the 20,000,000-step run budget. The emitted `.nan`
text file is 2,213,169 bytes; the loaded guest image is 67,346 words
(538,768 bytes). The standalone kernel also assembles and check-decodes
cleanly (`words 25`, `check: 0 mismatches`). As a negative control, an
intermediate body that had `W` and `h` wired to the wrong argument registers
ran to the `FAIL` marker (1,055,823 steps), confirming that the fixture rejects
incorrect outputs rather than passing unconditionally.

The repository fixture runner also reports:

```
[PASS] adapter256full: PASS steps=2839172 marker=MTH ADAPTER RESIDUAL 256 FULL PASS
1/1 fixtures passed
```

The run used the `.nan` text loader (`nan_load_text`). The local floppy-image
loader (`nan_load_image`) still caps at 65,536 words, so this run is not
evidence of a GLT-enforced 1 MiB page limit. The source and fixture are written
for the announced 1 MiB (131,072-word) budget; 1 MiB GLT harness execution is
the outstanding deployment check.

## 7. Limitations

- Dense 256×256 float32 only: one call, 65,536 multiply-accumulate terms, and
  the full `W` resident. No sparsity, low-rank, transpose, or fusion path.
- Requires the 1 MiB guest budget. The historical 512 KiB guest cannot hold the
  66,304-word working set; use the 16-block kernel there.
- No `beta` range or finiteness validation; the `[0,1]` bound is a
  contract/caller precondition. No overlap, NaN, or Inf validation either.
- Serial accumulation with two `FMUL` plus one `FADD` per term, `beta` applied
  before accumulation. Results are not bitwise identical to FMA-based,
  reassociated, or `h + beta*(W u)`-ordered implementations.
- No training, ablation, held-out evaluation, or LM benefit is claimed; the
  adapter remains disabled by contract. This document only evidences the
  bounded residual arithmetic.
- Leaf kernel: no `CALL`, no static state, preserves `r13` and `r15`, and
  assumes `r13=1`.

## 8. Files

- `mth/nan16/mth_adapter_residual_256_full.nas` — the full 256×256 kernel.
- `mth/tests/mth_adapter_residual_256_full_test.nas` — the fixture above.
- `docs/MTH_ADAPTER_RESIDUAL_256_FULL_ABI.md` — this contract.
