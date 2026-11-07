# MTH native 128×128 top singular-pair kernel

Status: source-written and locally executed with the canonical NaN0S toolchain; CI promotion pending.

## 1. Scope

`mth/nan16/mth_svd_top128.nas` computes the dominant singular pair
`(sigma, u, v)` of a dense 128×128 float32 matrix using two-sided power
iteration, which is power iteration on `AᵀA`. It reuses the verified
`mth_matvec128_f32.nas` kernel for `A*v` and implements `Aᵀ*u` as a
private helper.

The iteration is:

```
v = x / ||x||
repeat `iterations` times:
  u = A v;      u = u / ||u||
  v = Aᵀ u;     v = v / ||v||
u = A v; sigma = ||u||; u = u / sigma
```

## 2. ABI

| Register | Meaning |
|---|---|
| `r1` | A, 16,384 float32, row-major 128×128 |
| `r2` | x, 128 float32 input direction |
| `r3` | iterations, integer 1..32 |
| `r4` | u output, 128 float32 (left singular direction) |
| `r5` | v output, 128 float32 (right singular direction) |
| `r6` | sigma output, one float32 |
| `r7` | scratch1, 128 float32 (`A*v` workspace) |
| `r8` | scratch2, 128 float32 (`Aᵀ*u` workspace) |
| `r13` | 1 |
| return | `r1=1` success; `r1=0` zero direction, iterations outside 1..32, or a zero-norm iterate |

The kernel clobbers `r1-r12` and `r14`. `r13` must be 1 and is preserved
across the nested calls. `sigma` is measured from the unnormalized final
`A*v`; `u` is normalized afterwards. For `A=2I` this makes `sigma`
bit-exactly `2.0`. On success `u` and `v` are unit-norm float32 vectors.
On failure before the final stage `sigma` is not written; a failure after
`u` or `v` has been partially updated may leave that output containing an
intermediate iterate.

## 3. Ordering and arithmetic

Only NaN16 float32 operations are used; there is no host math.

- `A*v` is the included `mth_matvec128_f32` kernel: each row accumulates
  over increasing column `j` with one accumulator, no FMA/reordering.
- `Aᵀ*u` is `mth_svd_top128_transpose`: for each output column `j` it
  accumulates `A[i,j]*u[i]` over increasing row `i` with one
  accumulator. The source pointer advances by 128 words per row.
- Vector norms use one accumulator over increasing index `i`, followed by
  `FSQRT`. Normalization divides each element in increasing index order.
- A zero input norm, zero `||A v||`, zero `||Aᵀ u||`, or zero final
  `||A v||` is rejected with `r1=0`.

## 4. Save frame and `r15` policy

The kernel saves the single `r15` link word before any nested call and
restores it on both the success and invalid paths. The private helper and
the included matvec are leaves, so this is the only `r15` save needed.

`mth_svd_top128_frame` is an eight-word static save frame:

| Word | Contents |
|---|---|
| 0 | A |
| 1 | x |
| 2 | remaining iteration counter |
| 3 | u output |
| 4 | v output |
| 5 | sigma output |
| 6 | scratch1 |
| 7 | scratch2 |

`mth_svd_top128_return` is the single static saved-`r15` word. Because
these are static slots, the kernel is **non-reentrant and
non-concurrent**; callers must serialize invocations. None of the static
words are initialized or used as persistent state across calls.

## 5. Fixture

`mth/tests/mth_svd_top128_test.nas` builds `A=2I` programmatically, sets
`x=1`, and runs 3 iterations. It checks:

- status `r1=1`;
- `sigma` is bit-exactly `2.0` (`0x40000000`);
- `u[0]==u[127]` and `v[0]==v[127]`;
- `sum u[i]^2` and `sum v[i]^2` are each within two float32 ulps of
  `1.0`;
- an all-zero `x` returns status `0` and leaves `sigma` untouched;
- `iterations=0` and `iterations=33` return status `0`.

Canonical local run:

```
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=emit \
  mth/tests/mth_svd_top128_test.nas > /data/data/com.termux/files/usr/tmp/opencode/svd128.nan
/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/svd128.nan \
  --steps 100000000 --serial
```

Output:

```
words 18188
[nan_cli] nan-text: 1311632 steps, rc=3, pc=378, trap=''
MTH SVD TOP128 PASS
```

`awk -f ... -v CMD=check` on the emitted image reports `check: 0 mismatches`.

## 6. Limitations

- Top singular pair only; no deflation, second pair, or rank-k SVD.
- Dense 128×128 only; 255/256 or rectangular matrices need a separate path.
- No convergence or residual threshold; the caller declares 1..32 iterations.
- No NaN/Inf, alias, or overlapping-span validation. Spans should be distinct.
- Static save frame and link word make the kernel non-reentrant and
  non-concurrent.
- `u` and `v` are outputs of the iterative estimate, not a certificate of
  singular-vector accuracy; use a residual check at the caller if needed.
