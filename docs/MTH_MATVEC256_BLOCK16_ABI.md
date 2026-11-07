# MTH paged 16×256 float32 matrix-vector block

Status: source-written and locally executed with the canonical NaN0S toolchain; CI promotion pending.

## 1. Scope

`mth/nan16/mth_matvec256_block16.nas` computes 16 output rows of a dense 256×256 float32 matrix-vector product:

```
y[k] = sum_{j=0}^{255} A[k,j] * x[j]    for k = 0..15
```

The caller supplies one 16-row block of the matrix. A complete 256×256 matvec is a caller-driven sequence of 16 calls, not one monolithic kernel. A full dense 256×256 float32 matrix is 65,536 words. Under the new 1 MiB target a full matvec A+x+y (~66,048 words) fits; this block form remains the bounded/paged path for multi-tenant and larger plans.

## 2. ABI

| Register | Meaning |
|---|---|
| `r1` | A block, 4,096 float32, row-major 16 rows × 256 columns |
| `r2` | x, 256 float32 |
| `r3` | y block, 16 float32 output |
| `r13` | 1 |
| return | `r1=1` |
| clobbers | `r4`-`r12`, `r14` |

Memory: 4,096 + 256 + 16 = 4,368 words for the block, plus code and any caller vectors. Inputs are read-only; the three spans must be distinct and non-overlapping (caller precondition). Accumulation is increasing `j` with one accumulator; no FMA, no host math, no reordering.

## 3. Paged composition

For block index `b = 0..15`:

```
A_block = A + b * 16 * 256   (words)
y_block = y + b * 16         (words)
r1 = A_block; r2 = x; r3 = y_block; r13 = 1
CALL mth_matvec256_block16
```

Block `b` computes output rows `16b .. 16b+15`, so the caller collects the 16 returned y blocks in order to form the full 256-element matvec result. `x` is the same 256-word vector on every call and is not modified. The caller owns address arithmetic for the block offset and must preserve `r13=1`.

## 4. Fixture

`mth/tests/mth_matvec256_block16_test.nas` builds a 16×256 block with `A[k,k]=2.0` for `k=0..15` and zero elsewhere. It checks all 16 outputs against:

- `x=1` for all 256 → `y[k]=2.0`;
- `x=-1` for all 256 → `y[k]=-2.0`;
- `x=+0` for all 256 → `y[k]=+0.0`.

Local canonical run:

```
words 5134
[nan_cli] nan-text: 148561 steps, rc=3, pc=131, trap=''
MTH MATVEC256 BLOCK16 PASS
```

The guest halts with `rc=3/HALT`; `nan_cli` exits 0. Total fixture step count is well under the 20,000,000-step budget.

## 5. Limitations

- One fixed block shape only: 16 rows × 256 columns per call. A full 256×256 result requires exactly 16 calls; the kernel does not loop over blocks or materialize the whole matrix.
- No full dense 256×256 materialization path; the guest cannot hold `A`, `x`, `y`, and code together at that size.
- No overlap, alignment, NaN, or Inf validation; spans are a caller precondition.
- No transpose, alpha/beta scaling, or in-place operation; `x` and the block of `A` are read-only and `y` is written.
- Serial accumulation in increasing `j` with one accumulator; results are not bitwise identical to reordered or FMA-based implementations.
- The kernel assumes `r13=1` and clobbers `r4`-`r12` and `r14`.
