# MTH 128×128 float32 rank-1 additive coupling

Status: source-written and locally executed with the canonical NaN0S toolchain; CI promotion pending.

## 1. Scope

`mth/nan16/mth_lowrank_add_128.nas` applies one rank-1 additive update to a dense row-major 128×128 float32 matrix:

```
U[i,j] = U[i,j] + alpha * b[i] * c[j]
```

for `i,j` in `0..127`. This is a bounded 128×128 primitive for low-rank coupling terms. It does not factor, threshold, or decompose a matrix, and it does not perform a rank-R update in one call.

## 2. ABI

| Register | Meaning |
|---|---|
| `r1` | `U`, 16,384 float32 words, row-major 128×128, updated in place |
| `r2` | `b`, 128 float32 |
| `r3` | `c`, 128 float32 |
| `r4` | `alpha`, one float32 word |
| `r13` | 1 |
| return | `r1=1` |

Memory: 16,384 + 128 + 128 + 1 = 16,641 words, plus whatever the caller uses for fixture state. The kernel is a leaf routine: no `CALL`, no static slots, no shared return storage. It clobbers `r2-r12` and `r14`; it preserves `r13`.

Caller preconditions:

- `U` is writable.
- `U` is disjoint from `b` and `c`; no aliasing is checked.
- `b`, `c`, and `alpha` are readable float32 payloads.
- No NaN/Inf/denormal validation is performed.

The routine has no failure path and always returns `r1=1`.

## 3. Accumulation and rounding

Iteration order is fixed: increasing `i` (outer), then increasing `j` (inner).

For each row `i`:

```
s   = fl(alpha * b[i])          one FMUL, reused for all 128 columns
t_j = fl(s * c[j])              one FMUL per element
U[i,j] = fl(U[i,j] + t_j)       one FADD per element
```

Thus each call performs 128 + 16,384 = 16,512 FMULs and 16,384 FADDs. There is no FMA, no reassociation, and no partial-sum reordering. The expression tree is exactly `U + ((alpha*b[i])*c[j])`, with float32 rounding after each operation.

## 4. Fixture

`mth/tests/mth_lowrank_add_128_test.nas` checks:

1. Zero `U`, `b=c=1`, `alpha=2`: sample positions `U[0,0]`, `U[0,127]`, `U[63,64]`, `U[127,0]`, `U[127,127]` equal `2.0`.
2. `alpha=-1`: all 16,384 elements equal `1.0` after one additive negative update.
3. `alpha=-1` again: all 16,384 elements return to `0.0`.

The two negative updates are required by the additive contract: from `U=2`, one `alpha=-1` call gives `2 + (-1) = 1`, and the second gives `1 + (-1) = 0`. A single `alpha=-1` call cannot produce zero from two, so the requested final zero state is checked after complete cancellation rather than after one call.

4. Zero `U`, `b[i]=i+1`, `c[j]=j+1`, `alpha=1`: check the nontrivial products `U[0,0]=1`, `U[0,127]=128`, `U[127,0]=128`, `U[10,20]=231`, `U[63,64]=4160`, `U[127,127]=16384`. This verifies that `i` selects the row (`b`) and `j` selects the column (`c`) and that the outer product is applied elementwise.

Local canonical run:

```
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=emit \
  mth/tests/mth_lowrank_add_128_test.nas > /data/data/com.termux/files/usr/tmp/opencode/lowrank.nan
/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/lowrank.nan --steps 20000000 --serial
```

Output:

```
[nan_cli] nan-text: 1056470 steps, rc=3, pc=163, trap=''
MTH LOWRANK ADD 128 PASS
```

`nmk.awk -v CMD=check` on the emitted image reports `0 mismatches`.

## 5. Limitations

- One rank-1 term per call. A rank-R update `U += Σ_r alpha_r b_r c_rᵀ` is `R` calls; the caller owns the loop, the per-term factors, and the accumulation order. Each call re-reads and re-walks the full matrix.
- Dense 128×128 only (16,384 float32 words). A 256×256 matrix is four times larger and needs paging, tiling, or a different ABI.
- No overlap, aliasing, NaN, Inf, or denormal handling. `U` must be writable and disjoint from `b` and `c`; violating this is caller error and produces undefined results.
- No error status, no transactional rollback, and no partial-update atomicity: the kernel writes `U` in place as it walks.
- Not a rank-R/blocked implementation and not a factorization. It is only the additive apply step for a factor triple supplied by the caller.
- Strided, transposed, or tiled layouts are not supported; the matrix is strictly row-major with contiguous vectors.
