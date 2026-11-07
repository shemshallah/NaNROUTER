# MTH bounded 256×256 symmetric top-k kernel

Status: source-written and locally executed PASS with the canonical NaN0S
`nan_cli` as a `nan-text` image (72,980 NaN16 words; 133,733,039 guest
steps). The image is inside the 131,072-word / 1 MiB guest target and
above the historical 65,536-word / 512 KiB budget. The owned file set for
this change is the kernel, its fixture, and this document. A concurrent
integration commit added shared workflow, harness, and README entries
outside this owned set; those entries use a 200,000,000-step cap, which the
fixture satisfies (133,733,039 steps).

## 1. Scope

`mth/nan16/mth_lanczos_256.nas` computes up to eight dominant eigenpairs
(Ritz values and Ritz vectors) of a dense symmetric 256×256 float32 matrix.
It is a bounded, deterministic, NaN16-only kernel. `A` and `q0` are
read-only inputs; `values_out` and `vectors_out` are caller-owned outputs;
the only workspace is the caller-supplied scratch span.

The ABI fixes the stored basis at `k` vectors (at most 8×256 words) and
gives a bounded `iterations per vector` count. A growing three-term
Lanczos recurrence would need up to `iterations + 1` basis vectors (33×256
words for the maximum budget) and would not fit the declared `k*256`
basis. This kernel therefore uses the task's explicitly allowed
**bounded power-iteration extraction path**: a Lanczos-style orthogonal
(deflated) power iteration with full reorthogonalization against the
stored basis. It does not form a tridiagonal matrix, and it does not run a
dense Jacobi eigendecomposition on a `(k+1)×(k+1)` tridiagonal. The
extraction is the simplest correct option that fits the stated ABI and
workspace: each stored column is a converged power iterate, its Rayleigh
quotient is the Ritz value, and the pairs are selection-sorted in
descending value order.

## 2. ABI

| Register | Meaning |
|---|---|
| `r1` | `A`, 65,536 float32, row-major 256×256 symmetric |
| `r2` | `q0`, 256 float32 start direction (not modified) |
| `r3` | `k`, integer 1..8 |
| `r4` | iterations per vector, integer 1..32 |
| `r5` | `values_out`, `k` float32, descending Ritz values |
| `r6` | `vectors_out`, `k*256` float32, contiguous columns; vector `j` starts at `vectors_out + j*256` |
| `r7` | scratch, at least 1024 float32; the kernel uses the first 256 |
| `r13` | 1 |
| return | `r1=1` success; `r1=0` invalid or degenerate |

The kernel clobbers `r1-r12` and `r14`; it preserves `r13` and saves /
restores `r15`. On success, `values_out[0..k-1]` is non-increasing and
`vectors_out` holds `k` unit-norm vectors, mutually orthogonal to working
precision.

Rejected calls (`r1=0`):

- `k < 1` or `k > 8`;
- `iterations < 1` or `iterations > 32`;
- `q0` has exactly zero norm;
- a deflated power iterate has exactly zero norm after projecting out the
  locked columns (for example `A = 0`, or a rank-deficient operator with no
  remaining direction);
- the deterministic fallback cannot find any coordinate axis with a
  nonzero residual against the existing columns.

On rejection, `values_out` is untouched because it is written only after
every column has been computed. `vectors_out` may contain partial
intermediate columns. `A` and `q0` are never written.

## 3. Algorithm and ordering

### 3.1 Initial orthonormal basis

1. `V_0 = q0 / ||q0||`. A zero norm rejects the call.
2. For `j = 1..k-1`:
   - copy `q0` into `V_j`;
   - project out `V_0..V_{j-1}` with two full reorthogonalization passes;
   - normalize `V_j` in place.
3. If `V_j` is exactly zero after the projection (for example `q0 = e0`
   with `j = 1`), scan the coordinate axes `e_p` for `p = 0,1,...,255`.
   For each `p`, write `e_p` into `V_j`, project out `V_0..V_{j-1}` with two
   passes, and normalize. The first axis with a nonzero residual is used.
   If no axis works, return 0. The scan is deterministic and bounded.

The fallback is what lets the fixture's `q0 = e0` case produce the exact
second eigenvector `e1` instead of breaking down after one Krylov step.

### 3.2 Bounded deflated power iteration

For each column `j = 0..k-1`, run exactly `iterations` steps:

```
w = A * V_j
w = w - sum_{i=0}^{j-1} (V_i . w) V_i        (two complete passes)
if ||w|| == 0: return 0
V_j = w / ||w||
```

Only the already locked columns `0..j-1` are projected out. The current
column is deliberately not projected out of its own iterate; doing so would
remove its dominant component and converge to the wrong eigenpair. Later
columns are re-projected when their own turn arrives, so the final basis
is mutually orthonormal.

Each `V_i . w` reduction is an increasing-index, one-accumulator sum. The
subtraction is a second increasing-index pass. Normalization is a third
pass. There is no reordering, no tree reduction, no FMA, and no host math.

### 3.3 Ritz extraction

For each `j`, compute the Rayleigh quotient

```
lambda_j = V_j^T A V_j
```

with another `A * V_j` matvec and one increasing-index dot product. The
`(lambda_j, V_j)` pairs are selection-sorted by decreasing `lambda_j`; when
a swap is needed, the corresponding 256-word vector columns are swapped
through the first 256 words of scratch. The sorted values are the output
Ritz values; the sorted orthonormal columns are the output Ritz vectors.

This is the bounded power-iteration extraction option. It produces true
Ritz values of the one-dimensional subspaces spanned by the orthonormal
columns. It is not the optimal Rayleigh–Ritz extraction from the full
k-dimensional span, and it is not a three-term Lanczos tridiagonal solve.
With enough iterations the columns converge to the dominant eigenvectors
and the two interpretations agree to float32 working precision.

## 4. Determinism and arithmetic

- All floating-point operations are NaN16 `FADD`, `FSUB`, `FMUL`, `FDIV`,
  `FSQRT`, and `FCMP` on IEEE float32 payloads.
- Every reduction is `sum_{i=0}^{255}` in increasing index order with one
  accumulator. No reassociation, pairwise summation, FMA, or tree
  reduction is used.
- The algorithm has no random seed, no data-dependent early exit, no
  adaptive tolerance, and no host math. Identical inputs and spans produce
  bit-identical outputs.
- The only data-dependent control flow is the deterministic coordinate-axis
  fallback scan and the degenerate zero-norm rejection.

## 5. Save frame and `r15` policy

The kernel saves the single `r15` link word in
`mth_lanczos_256_return` before any nested `CALL` and restores it on both
the success and invalid paths. Every private helper is a leaf, so the one
saved link remains valid across all nested calls; the helpers do not save
`r15` themselves.

`mth_lanczos_256_frame` is a fourteen-word static save frame:

| Word | Contents |
|---|---|
| 0 | `A` |
| 1 | `q0` |
| 2 | `k` |
| 3 | iterations per vector |
| 4 | `values_out` |
| 5 | `vectors_out` |
| 6 | scratch base |
| 7 | current column index `j` |
| 8 | remaining iterations for the current column |
| 9 | unused |
| 10 | unused |
| 11 | `w` workspace pointer (`scratch`) |
| 12 | unused |
| 13 | fallback axis scan index `p` |

Because the frame and link word are static, the kernel is **non-reentrant
and non-concurrent**; callers must serialize invocations. The static words
are overwritten on every call and are not persistent state.

Private helpers:

| Helper | Role |
|---|---|
| `mth_lanczos_256_matvec` | leaf `A*v`; advances the A row pointer and output pointer per row; increasing column index, one accumulator |
| `mth_lanczos_256_normalize` | leaf in-place 256-word normalization; returns 0 on exact zero norm |
| `mth_lanczos_256_orth` | leaf two-pass projection against locked columns |
| `mth_lanczos_256_dot` | leaf 256-word dot product, increasing index, one accumulator |

## 6. Memory budget

Caller spans for the maximum `k = 8`:

| Object | NaN16 words | Bytes |
|---|---:|---:|
| `A` (256×256 float32) | 65,536 | 524,288 |
| `vectors_out` (8×256) | 2,048 | 16,384 |
| `scratch` (contract minimum) | 1,024 | 8,192 |
| `q0` | 256 | 2,048 |
| `values_out` | 8 | 64 |
| **Caller working set** | **68,872** | **550,976** |

The kernel itself touches only the first 256 words of `scratch` (`w`); the
remaining 768 words are reserved by the ABI for callers and future
variants. The emitted fixture image is **72,980 words = 583,840 bytes**:
code and static frame fit below word 4,096, `A` starts at word 4,096,
`q0` at 69,632, `values_out` at 69,888, `vectors_out` at 69,896, and
`scratch` at 71,944.

The 1 MiB target is 131,072 words = 1,048,576 bytes. The fixture leaves
58,092 words / 464,736 bytes of headroom. The historical 512 KiB budget is
65,536 words = 524,288 bytes; the caller working set exceeds it by 3,336
words / 26,688 bytes, and the fixture image exceeds it by 7,444 words /
59,552 bytes. This is therefore a 1 MiB-target fixture, not a 512 KiB one.

## 7. Fixture and native evidence

`mth/tests/mth_lanczos_256_test.nas` checks:

1. **Required diagonal case**: `A = diag(3,2,1,0,...)`, `q0 = 1`,
   `k = 2`, `iterations = 16`. Status 1; values within `1e-3` of 3 and 2;
   both vectors unit-norm and mutually orthogonal within `1e-3`;
   `V0[0]^2 > 0.98` and `V1[1]^2 > 0.98`; `A` and `q0` unchanged. A direct
   probe of this case observed values `0x403FFFF5` (2.9999974) and
   `0x4000000B` (2.0000007), with `V0 = [0x3F7FFFEC, ...]` and
   `V1 = [..., 0xBF7FFFEE, ...]` (the second vector is `-e1`, a legal
   eigenvector sign).
2. **Breakdown fallback**: the same `A`, `q0 = e0`, `k = 2`,
   `iterations = 4`. Status 1; values bit-exactly `3.0` and `2.0`;
   `V0[0]^2 == 1`, `V0[1] == 0`, `V1[0] == 0`, `V1[1]^2 == 1`. This
   exercises the exactly exhausted second seed and the coordinate-axis
   fallback.
3. **Non-diagonal block**: `A = [[2,1],[1,2]]` in the leading block, zero
   elsewhere, `q0 = 1`, `k = 2`, `iterations = 16`. Status 1; values 3
   and 1 within `1e-3`; unit and orthogonal vectors; the top vector has
   same-sign leading components and the second vector has opposite-sign
   leading components.
4. **Zero operator**: `A = 0` returns status 0 and leaves both
   `values_out` slots at the `0xDEAD5A5A` sentinel.
5. **Bounds**: `k = 0`, `k = 9`, `iterations = 0`, `iterations = 33`, and
   zero `q0` each return status 0 with `values_out` untouched.
6. **`k = 1`**: `A = diag(3,2,1,0,...)`, `q0 = 1`, `iterations = 16`;
   value 3 and one unit-norm vector.
7. **`k = 4`**: `A = diag(8,6,4,2,0,...)`, `q0 = 1`,
   `iterations = 16`; values 8, 6, 4, 2 within `1e-3`; four unit-norm
   mutually orthogonal vectors.
8. **`k = 8` fallback chain**: `A = diag(8,7,6,5,4,3,2,1,0,...)`,
   `q0 = e0`, `k = 8`, `iterations = 1`. The initial column is `e0`; each
   later column is supplied by the coordinate-axis fallback (`e1` through
   `e7`). Values are bit-exactly 8,7,6,5,4,3,2,1 and all eight vectors are
   unit-norm and mutually orthogonal.
9. **Sort swap**: `A = diag(3,2,1,0,...)`, `q0 = e1`, `k = 2`,
   `iterations = 4`. The extraction order is 2 then 3; the values are
   bit-exactly 3 then 2 and the vector columns are swapped, checking the
   descending selection-sort path.

Canonical local commands:

```
LC_ALL=C awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk \
  -v CMD=emit mth/nan16/mth_lanczos_256.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/kernel_only.nan
```

The kernel source alone assembles to **422 words** with `check: 0 mismatches`.
The full fixture is assembled and executed with:

```
LC_ALL=C awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk \
  -v CMD=emit mth/tests/mth_lanczos_256_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/lanczos256.nan

LC_ALL=C awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk \
  -v CMD=check /data/data/com.termux/files/usr/tmp/opencode/lanczos256.nan

/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/lanczos256.nan \
  --steps 150000000 --serial
```

Observed:

```
words 72980
check: 0 mismatches
[nan_cli] nan-text: 133733039 steps, rc=3, pc=941, trap=''
MTH LANCZOS 256 PASS
```

The step count is for the whole fixture, including all success and
rejection cases. A single successful `k=2`, 16-iteration call uses 34
matvecs and probes at 22,802,185 steps.

## 8. Limitations

- This is a deflated orthogonal power iteration, not a growing three-term
  Lanczos recurrence. It does not build or diagonalize a tridiagonal
  matrix; it uses the allowed bounded power-iteration Ritz extraction.
- Convergence is controlled only by the caller's `iterations` value. There
  is no residual output, no adaptive stopping, and no certificate of
  eigenpair accuracy. Use a caller-side residual check if required.
- The deterministic fallback axes are the coordinate axes. For a
  contrived matrix whose next extremal eigenvector is orthogonal to every
  tried axis in a pathological floating-point configuration, the scan can
  return 0 or converge to a lower Ritz pair. The fixture's diagonal and
  block cases do not hit that corner.
- Only dense symmetric 256×256 float32 is supported. Rectangular, paged,
  sparse, 128/255-sized, or non-symmetric operators need a separate path.
- No NaN, Inf, alias, or overlap validation. `A`, `q0`, `values_out`,
  `vectors_out`, and `scratch` must be distinct, non-overlapping spans.
  `A` is read as symmetric; the kernel does not verify `A[i,j] == A[j,i]`.
- Static save frame and link word make the kernel non-reentrant and
  non-concurrent. Callers must serialize invocations.
- Eigenvector signs are not canonicalized. A vector and its negation are
  both valid outputs; the fixture checks unit norm, orthogonality, and
  squared dominant components rather than a fixed sign where the sign is
  not forced by the input.
- The caller working set and fixture exceed the historical 512 KiB guest
  budget; they are inside the 1 MiB target only. Do not schedule this
  fixture under a 512 KiB plan.
- No `.github/workflows` entry, README ledger entry, or harness registry
  entry was edited here because those files are outside this change's owned
  file set. Concurrent integration entries exist and use a 200,000,000-step
  cap; this fixture uses 133,733,039 steps.
