# MTH native 256×256 top-two singular-pair kernel

Status: source-written and locally executed PASS with the canonical NaN0S
`nan_cli` as a `nan-text` image (68,878 NaN16 words; 40,216,927 guest
steps; marker `MTH SVD TOP2 256 PASS`). The image exceeds the historical
65,536-word / 512 KiB declared guest budget but is well inside the 1 MiB
target (131,072 NaN16 words). It is a 1 MiB-target fixture; canonical CI run 42395520794 executed it;
GLT/plan promotion; the shared fixture harness and workflow were not
edited by this change.

## 1. Scope

`mth/nan16/mth_svd_top2_256.nas` computes the two dominant singular
pairs of a dense 256×256 float32 matrix without modifying `A`:

```
(sigma1, u1, v1) = dominant singular pair of A
(sigma2, u2, v2) = dominant singular pair of P_u1 A P_v1
```

where `P_z = I - z zᵀ`. The second pair is obtained by two-sided power
iteration with projection/deflation against the first `u1`/`v1`; it is
not a rank-k SVD and it does not use a host-language implementation.
`A*v` and `Aᵀ*u` are private leaf helpers in the same source file.

The first pair is the same two-sided iteration used by
`mth_svd_top256`:

```
v1 = x / ||x||
repeat `iterations` times:
  u1 = A v1;      u1 = u1 / ||u1||
  v1 = Aᵀ u1;     v1 = v1 / ||v1||
u1 = A v1; sigma1 = ||u1||; u1 = u1 / sigma1
```

The second pair starts from the projection of `x` onto `v1⊥` and then
repeats the same two-sided iteration on the deflated operator:

```
v2 = P_v1 x / ||P_v1 x||
repeat `iterations` times:
  u2 = P_u1 (A v2);      u2 = u2 / ||u2||
  v2 = P_v1 (Aᵀ u2);     v2 = v2 / ||v2||
u2 = P_u1 (A v2); sigma2 = ||P_u1 (A v2)||; u2 = u2 / sigma2
```

The projection is applied after each matvec and before renormalization:
`A*v2` has its component along `u1` removed, and `Aᵀ*u2` has its
component along `v1` removed. This is the left/right-space-correct
deflation of the first singular pair.

If `P_v1 x` has zero norm (for example `x = e0` and `v1 = e0`), the
kernel uses a deterministic fallback seed `e_k`, where `k` is the first
index with the smallest `v1[k]²`. The seed is projected against `v1`
before iteration, so the fallback still starts in `v1⊥`. This keeps the
second pair computable when the caller's initial direction has no
component outside the first right singular direction. The fallback is
an initialization rule only; the second pair is still produced by the
same projected power iteration.

The iteration counter is restored from a saved initial copy before the
second pair, so both pairs receive the declared 1..32 iteration count.

## 2. ABI

| Register | Meaning |
|---|---|
| `r1` | A, 65,536 float32, row-major 256×256 |
| `r2` | x, 256 float32 initial direction |
| `r3` | iterations, integer 1..32 |
| `r4` | u1 output, 256 float32 (pair-1 left singular direction) |
| `r5` | v1 output, 256 float32 (pair-1 right singular direction) |
| `r6` | sigma1 output, one float32 |
| `r7` | u2 output, 256 float32 (pair-2 left singular direction) |
| `r8` | v2 output, 256 float32 (pair-2 right singular direction) |
| `r9` | sigma2 output, one float32 |
| `r10` | scratch, at least 1,024 float32 (the kernel uses the first 256) |
| `r13` | 1 |
| return | `r1=1` success; `r1=0` zero input direction, iterations outside 1..32, a zero-norm iterate, or a zero second singular value after deflation |

The kernel clobbers `r1-r12` and `r14`. `r13` must be 1 and is never
written. `A` and `x` are not modified. On success both `u`/`v` pairs are
unit-norm float32 vectors and `u1 ⟂ u2`, `v1 ⟂ v2` up to float32
rounding.

On failure before the final stage of a pair, that pair's sigma is not
written. Failure in the first pair happens before `sigma1` is stored;
failure in the second pair happens before `sigma2` is stored, but
`sigma1` and the first pair may already have been written. The reject
path does not promise atomicity of the intermediate direction outputs.
`A` and `x` remain unmodified on both success and failure.

## 3. Ordering and arithmetic

Only NaN16 float32 operations are used; there is no host math, no FMA,
and no reassociation.

- `A*v` is `mth_svd_top2_256_matvec`: for each output row `i` it
  accumulates `A[i,j]*v[j]` over increasing column `j` with one
  accumulator. The source pointer walks the 65,536-word matrix row-major.
- `Aᵀ*u` is `mth_svd_top2_256_transpose`: for each output column `j` it
  accumulates `A[i,j]*u[i]` over increasing row `i` with one
  accumulator. The source pointer advances by 256 words per row.
- `mth_svd_top2_256_normalize` computes `sqrt(sum v[i]²)` in increasing
  index order with one accumulator, then divides each element in
  increasing index order. It returns the pre-division norm in `r2`.
- `mth_svd_top2_256_project_norm` computes one dot product
  `sum ref[i]*base[i]` in increasing index order with one accumulator,
  then performs `out[i] = base[i] - dot*ref[i]` and accumulates the new
  squared norm in a second increasing-index pass, then divides in a
  third increasing-index pass. `base` and `out` may be the same span;
  `ref` must be distinct from `out`.
- A zero input norm, zero `||A v||`, zero projected norm, or zero final
  `||A v||` is rejected with `r1=0`.

The second sigma is measured from the unnormalized deflated final
`A*v2`, so for `A=diag(3,2,0,...)` and `x=e0` the outputs are
bit-exactly `sigma1=3.0`, `sigma2=2.0`, `u1=v1=e0`, and `u2=v2=e1`.

## 4. Save frame and `r15` policy

The entry saves the single `r15` link word before any nested call and
restores it on both success and invalid paths. All four private helpers
are leaves, so the one saved link remains valid across every `CALL`; the
helpers do not save `r15` themselves.

`mth_svd_top2_256_frame` is an eleven-word static save frame:

| Word | Contents |
|---|---|
| 0 | A |
| 1 | x |
| 2 | remaining iteration counter |
| 3 | u1 output |
| 4 | v1 output |
| 5 | sigma1 output |
| 6 | u2 output |
| 7 | v2 output |
| 8 | sigma2 output |
| 9 | scratch |
| 10 | initial iteration count, reloaded for the second pair |

`mth_svd_top2_256_return` is the single static saved-`r15` word. Because
these are static slots, the kernel is **non-reentrant and
non-concurrent**; callers must serialize invocations. The static words
are overwritten on every call and are not persistent state across calls.

## 5. Memory budget

Kernel working set:

| Object | NaN16 words | Bytes |
|---|---:|---:|
| A (256×256 float32) | 65,536 | 524,288 |
| x | 256 | 2,048 |
| u1 | 256 | 2,048 |
| v1 | 256 | 2,048 |
| u2 | 256 | 2,048 |
| v2 | 256 | 2,048 |
| sigma1 | 1 | 8 |
| sigma2 | 1 | 8 |
| scratch (minimum 1,024 words) | 1,024 | 8,192 |
| **Kernel total** | **67,842** | **542,736** |

The test fixture adds the code, static frames, strings, and padding. Its
emitted image is **68,878 words = 551,024 bytes**. The 1 MiB target is
131,072 words = 1,048,576 bytes, leaving 62,194 words / 497,552 bytes
of headroom.

The fixture places A at word 1024. x, u1, v1, sigma1, u2, v2, sigma2,
and the 1,024-word scratch span follow at words 66,560, 66,816, 67,072,
67,328, 67,329, 67,585, 67,841, and 67,842. All pointers above 65,535
are formed with `LA` (`MOVI` low half plus `MOVHI` high half).

## 6. Fixture

`mth/tests/mth_svd_top2_256_test.nas` checks:

1. `A=diag(3,2,0,...)`, `x=e0`, `iterations=3`: status `r1=1`;
   `sigma1` bit-exactly `3.0`; `sigma2` bit-exactly `2.0`;
   `u1=v1=e0`; `u2=v2=e1`; all four directions satisfy the fixture's
   unit-norm tolerance `|sum(v[i]²)-1| <= 0.001`; `u1·u2=0` and
   `v1·v2=0` exactly; `A` and `x` are unchanged. The `x=e0` case also
   exercises the `P_v1 x = 0` fallback seed.
2. The same diagonal matrix with `x=1` and `iterations=8`: status
   `r1=1`; `sigma1≈3` and `sigma2≈2` within `0.01`; unit norms within
   `0.001` of `1.0`; near-orthogonality within `0.001`. This exercises
   the ordinary projected seed `P_v1 x`.
3. All-zero `x` returns status `0` and leaves `sigma1` and `sigma2`
   untouched.
4. `iterations=0` returns status `0` and leaves both sigmas untouched.
5. `iterations=33` returns status `0`.
6. `A=0` is degenerate: status `0`, both sigmas untouched.
7. `A=2*e0*e1ᵀ` (only `A[0,1]=2`) is rank one: the first pair is
   `sigma1=2`, `u1=e0`, `v1=e1`, but the deflated second pair has zero
   norm. The call returns status `0`; `sigma1` is written and `sigma2`
   is untouched.

Canonical local run:

```
LC_ALL=C awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk \
  -v CMD=emit mth/tests/mth_svd_top2_256_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/svd_top2_256.nan

/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/svd_top2_256.nan \
  --steps 150000000 --serial
```

Observed:

```
words 68878
check: 0 mismatches
[nan_cli] nan-text: 40216927 steps, rc=3, pc=683, trap=''
MTH SVD TOP2 256 PASS
```

The local `nan_cli` accepts this image through its `nan-text` loader,
which uses the 4M-word VM and is not capped at the historical 65,536
words. This local run verifies the source and fixture under the current
local VM; it does not by itself verify a GLT page-limit increase. The
shared fixture harness and CI workflow were not edited by this change
because they are outside this change's owned file set, so this fixture
is not yet scheduled by the combined harness.

## 7. Limitations

- Top two singular pairs only; no rank-k SVD, convergence certificate,
  residual, or adaptive iteration count. The caller declares 1..32
  iterations for both pairs.
- Dense 256×256 only; rectangular, paged, or streamed matrices need a
  separate path.
- The second pair is a deflated iterative estimate, not a certificate of
  singular-vector accuracy. Use a caller-side residual check if needed.
- A rank-one or lower-rank matrix has no nonzero second singular value.
  The kernel detects this when the projected second iterate rounds to
  zero norm and then returns `0` after writing the first pair and before
  writing `sigma2`; near-rank-deficient inputs can leave a tiny nonzero
  estimate instead.
- No NaN/Inf, alias, or overlapping-span validation. A, x, u1, v1,
  sigma1, u2, v2, sigma2, and scratch should be distinct spans; scratch
  must not alias any output or input.
- The static save frame and link word make the kernel non-reentrant and
  non-concurrent.
- The fixture and kernel are a 1 MiB-target artifact. Scheduling them
  under the historical 512 KiB declared budget requires the GLT
  limit increase.
