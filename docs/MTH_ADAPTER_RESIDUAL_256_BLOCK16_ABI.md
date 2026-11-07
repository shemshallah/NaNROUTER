# MTH blockwise 256-dimensional adapter residual (16-row blocks)

Status: source-written and locally executed with the canonical NaN0S toolchain; CI promotion pending.

## 1. Scope

`mth/nan16/mth_adapter_residual_256_block16.nas` computes 16 rows of the
256-dimensional adapter residual:

```
out[k] = h[k] + beta * sum_{j=0..255} C[k,j] * u[j]     for k = 0..15
```

`h` is the frozen base-state block, `u` is the bounded 256-float32 readout
state, `C` is one 16x256 row-major block of a dense typed decode map, and
`beta` is the residual scale. The kernel computes the residual arithmetic only;
it does not enable an adapter, train anything, or claim an LM improvement.

The block shape is fixed at 16 rows x 256 columns. A full 256x256 residual is
composed by the caller as 16 invocations, so the full 65,536-word `C` matrix is
never resident; only one 4,096-word row block is.

## 2. ABI

| Register | Meaning |
|---|---|
| `r1` | `h` block, 16 float32 |
| `r2` | `C` block, 4,096 float32, row-major 16 rows x 256 columns |
| `r3` | `u`, 256 float32 |
| `r4` | `beta`, one float32, passed by value |
| `r5` | `out` block, 16 float32 |
| `r13` | 1 |
| return | `r1=1` |
| clobbers | `r6`-`r12`, `r14`; preserves `r13` and `r15` |

Memory: 4,096 (`C` block) + 256 (`u`) + 16 (`h`) + 16 (`out`) = 4,384 words,
plus code and any caller data. There is no scratch buffer and no static slot:
the kernel is a leaf with no `CALL`, no `.org` data, and no self-modification,
so it is reentrant for distinct spans. `C`, `u`, and `h` are read-only; only
`out` is written. The four spans must be distinct and non-overlapping; this is
a caller precondition.

## 3. Arithmetic order

For each row `k = 0..15`, one accumulator is seeded with `h[k]`; then for
increasing `j = 0..255` the kernel performs:

```
t1  = beta * C[k,j]
t2  = t1 * u[j]
acc = acc + t2
```

which is the left-to-right evaluation of

```
h[k] + beta*C[k,0]*u[0] + beta*C[k,1]*u[1] + ...
```

There are exactly two `FMUL` and one `FADD` per term, no FMA, no reordering,
and no host math. Because `beta` is applied per term before accumulation, the
result is not in general bitwise identical to the algebraically equivalent
`h[k] + beta * (sum_j C[k,j]*u[j])`, which would apply `beta` after the sum.
The per-row term order and the 16-row order are both increasing.

## 4. Paged composition

For block index `b = 0..15`:

```
C_block = C + b * 16 * 256   (word offset 4,096 * b)
h_block = h + b * 16         (word offset 16 * b)
out     = out + b * 16       (word offset 16 * b)
r1 = h_block; r2 = C_block; r3 = u; r4 = beta; r5 = out_block; r13 = 1
CALL mth_adapter_residual_256_block16
```

Each call produces output rows `16b .. 16b+15`. `u` and `beta` are identical
on every call and are not modified. The caller owns the block address
arithmetic and must preserve `r13=1`. A full 256-element residual is the
ordered concatenation of the 16 returned `out` blocks.

## 5. Fixture and local evidence

`mth/tests/mth_adapter_residual_256_block16_test.nas` builds the first `C`
block as `C = 2I` on its 16 rows (`C[k,k]=2.0` at word offset `257k`, all other
4,096 block words zero), sets `h=1.0` (16 words) and `u=1.0` (256 words), and
checks:

- with `beta=0.5`, all 16 outputs equal `2.0` (`1 + 0.5*2`);
- after poisoning all 16 outputs with `77.0`, `beta=0` rewrites every output
  to `h=1.0`.

Both checks cover every output entry, not just a sample. The fixture arrays
start at word 1024 and occupy the declared 4,384-word working set; the image
assembles to 5,428 words.

Canonical local run:

```
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=emit mth/tests/mth_adapter_residual_256_block16_test.nas > /data/data/com.termux/files/usr/tmp/opencode/adapter256b.nan
/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli --img /data/data/com.termux/files/usr/tmp/opencode/adapter256b.nan --steps 20000000 --serial
```

Observed output:

```
words 5428
[nan_cli] nan-text: 113055 steps, rc=3, pc=117, trap=''
MTH ADAPTER RESIDUAL 256 BLOCK16 PASS
```

The guest halts with `rc=3/HALT`; `nan_cli` exits 0. The 113,055-step run is
well below the 20,000,000-step budget. The same source passes
`nmk.awk -v CMD=check` with `0 mismatches`.

## 6. Limitations

- Fixed block shape only: 16 rows x 256 columns per call. The kernel does not
  loop over blocks or materialize the full 256x256 matrix; the caller must
  issue exactly 16 calls for a full residual.
- Dense only: 4,096 multiply-accumulate terms per invocation and 65,536 per
  full 256-dimensional residual. No sparsity, low-rank, or fusion path.
- No `beta` range or finiteness validation; the `[0,1]` bound is a
  contract/caller precondition from the adapter descriptor. No overlap, NaN,
  or Inf validation either.
- Serial accumulation with two `FMUL` plus one `FADD` per term. Results are
  not bitwise identical to FMA-based, reassociated, or
  `h + beta*(C u)`-ordered implementations.
- The kernel itself keeps only one `C` block resident, but the caller remains
  responsible for proving that the chosen storage strategy actually avoids a
  full 65,536-word resident matrix.
- No training, ablation, held-out evaluation, or LM benefit is claimed; the
  adapter remains disabled by contract. This document only evidences the
  bounded residual arithmetic.
- Leaf kernel: no `CALL`, no static state, preserves `r13` and `r15`, and
  assumes `r13=1`.

## 7. Files

- `mth/nan16/mth_adapter_residual_256_block16.nas` — the blockwise kernel.
- `mth/tests/mth_adapter_residual_256_block16_test.nas` — the fixture above.
- `docs/MTH_ADAPTER_RESIDUAL_256_BLOCK16_ABI.md` — this contract.
