# MTH native 256×256 top singular-pair kernel

Status: source-written and locally executed PASS with the canonical NaN0S
`nan_cli` as a `nan-text` image (67,597 NaN16 words; 11,002,235 guest
steps). The image is larger than the historical 65,536-word / 512 KiB
declared guest budget, so plan-level promotion is **pending the 1 MiB
GLT guest** (131,072 NaN16 words). The local text loader accepted the
full image; see §6.

## 1. Scope

`mth/nan16/mth_svd_top256.nas` computes the dominant singular pair
`(sigma, u, v)` of a dense 256×256 float32 matrix using two-sided power
iteration, which is power iteration on `AᵀA`. `A*v` and `Aᵀ*u` are
private leaf helpers in the same source file; no other kernel is
included and no host math is used.

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
| `r1` | A, 65,536 float32, row-major 256×256 |
| `r2` | x, 256 float32 input direction |
| `r3` | iterations, integer 1..32 |
| `r4` | u output, 256 float32 (left singular direction) |
| `r5` | v output, 256 float32 (right singular direction) |
| `r6` | sigma output, one float32 |
| `r7` | scratch, 256 float32 (`A*v` / `Aᵀ*u` workspace) |
| `r13` | 1 |
| return | `r1=1` success; `r1=0` zero input direction, iterations outside 1..32, or a zero-norm iterate |

The kernel clobbers `r1-r12` and `r14`. `r13` must be 1 and is never
written. `sigma` is measured from the unnormalized final `A*v` and `u`
is normalized afterwards, so for `A=2I` `sigma` is bit-exactly `2.0`.
On success `u` and `v` are unit-norm float32 vectors. On failure before
the final stage `sigma` is not written; a failure after `u` or `v` has
been partially updated may leave that output containing an intermediate
iterate. A and x are not modified.

## 3. Ordering and arithmetic

Only NaN16 float32 operations are used; there is no host math.

- `A*v` is `mth_svd_top256_matvec`: for each output row `i` it
  accumulates `A[i,j]*v[j]` over increasing column `j` with one
  accumulator. The row pointer advances one word at a time and ends each
  row at the start of the next 256-word row.
- `Aᵀ*u` is `mth_svd_top256_transpose`: for each output column `j` it
  accumulates `A[i,j]*u[i]` over increasing row `i` with one
  accumulator. The source pointer advances by 256 words per row.
- Vector norms use one accumulator over increasing index `i`, followed
  by `FSQRT`. Normalization divides each element in increasing index
  order.
- A zero input norm, zero `||A v||`, zero `||Aᵀ u||`, or zero final
  `||A v||` is rejected with `r1=0`.
- No FMA, no reassociation, and no tree reduction are used.

## 4. Save frame and `r15` policy

The kernel saves the single `r15` link word before any nested call and
restores it on both the success and invalid paths. Both private helpers
are leaves, so the one saved link remains valid across every `CALL`; the
helpers do not save `r15` themselves.

`mth_svd_top256_frame` is a seven-word static save frame:

| Word | Contents |
|---|---|
| 0 | A |
| 1 | x |
| 2 | remaining iteration counter |
| 3 | u output |
| 4 | v output |
| 5 | sigma output |
| 6 | scratch |

`mth_svd_top256_return` is the single static saved-`r15` word. Because
these are static slots, the kernel is **non-reentrant and
non-concurrent**; callers must serialize invocations. The static words
are overwritten on every call and are not used as persistent state
across calls.

## 5. Memory budget

Kernel working set:

| Object | NaN16 words | Bytes |
|---|---:|---:|
| A (256×256 float32) | 65,536 | 524,288 |
| u | 256 | 2,048 |
| v | 256 | 2,048 |
| sigma | 1 | 8 |
| scratch | 256 | 2,048 |
| **Kernel total** | **66,305** | **530,440** |

The test fixture additionally allocates x (256 words), code, padding,
and the pass/fail strings, for an emitted image of **67,597 words =
540,776 bytes**. The historical 512 KiB budget is 65,536 words =
524,288 bytes, so the fixture exceeds it by 2,061 words / 16,488 bytes.
The new 1 MiB target is 131,072 words = 1,048,576 bytes and leaves
63,475 words / 507,800 bytes of headroom.

The fixture places A at word 1024; all code, static slots, and the
fixture logic fit below that address. x, u, v, sigma, and scratch
follow A at words 66,560, 66,816, 67,072, 67,328, and 67,329. All
pointers above 65,535 are formed with `LA` (`MOVI` low half plus
`MOVHI` high half).

## 6. Fixture

`mth/tests/mth_svd_top256_test.nas` checks:

1. `A=2I`, `x=1`, `iterations=3`: status `r1=1`; `sigma` bit-exactly
   `2.0` (`0x40000000`); `u[0]==u[255]`; `v[0]==v[255]`; `sum u[i]^2`
   and `sum v[i]^2` each within two float32 ulps of `1.0`.
2. `A=2*e0*e1ᵀ` (only `A[0,1]=2`), `x=1`, `iterations=3`: exact
   singular pair `sigma=2`, `u=e0`, `v=e1`; the fixture checks
   `u[0]=1`, `u[1]=0`, `v[0]=0`, `v[1]=1`. This asymmetric rank-one
   case forces `Aᵀ*u` to differ from `A*v`.
3. All-zero `x` returns status `0` and leaves `sigma` untouched.
4. `A=0` is degenerate: it returns status `0` and leaves `sigma`
   untouched.
5. `iterations=0` and `iterations=33` return status `0`.

Canonical local run:

```
LC_ALL=C awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=emit \
  mth/tests/mth_svd_top256_test.nas > /data/data/com.termux/files/usr/tmp/opencode/svd256.nan
/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/svd256.nan \
  --steps 150000000 --serial
```

Observed:

```
words 67597
[nan_cli] nan-text: 11002235 steps, rc=3, pc=484, trap=''
MTH SVD TOP256 PASS
```

`awk -f ... -v CMD=check` on the emitted image reports `check: 0
mismatches`.

The local `nan_cli` accepts this image through its `nan-text` loader,
which uses the 4M-word VM and is not capped at the historical 65,536
words. This local run verifies the source and fixture under the current
local VM; it does not by itself verify the GLT page-limit increase. The
declared MthSystem guest budget is still 512 KiB until GLT raises it, so
this fixture must not be scheduled under a 512 KiB plan; it is a 1 MiB
target fixture pending GLT/plan promotion. No CI workflow entry was
added in this change because the workflow is outside the owned file set.

## 7. Limitations

- Top singular pair only; no deflation, second pair, or rank-k SVD.
- Dense 256×256 only; 255/256 rectangular matrices or paged/streamed
  matrices need a separate path.
- No convergence, residual, or iteration-count adaptation; the caller
  declares 1..32 iterations.
- No NaN/Inf, alias, or overlapping-span validation. A, x, u, v, sigma,
  and scratch should be distinct spans; scratch must not alias v or u.
- Static save frame and link word make the kernel non-reentrant and
  non-concurrent.
- `u` and `v` are outputs of the iterative estimate, not a certificate
  of singular-vector accuracy; use a residual check at the caller if
  needed.
- The image exceeds the old 512 KiB guest budget and is pending the
  1 MiB GLT limit at the scheduling/policy layer.
