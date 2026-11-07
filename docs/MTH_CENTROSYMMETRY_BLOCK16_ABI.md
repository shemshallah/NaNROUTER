# MTH 16×256 block centrosymmetry certificate for a 256×256 matrix

Status: source-written and locally executed with the canonical NaN0S toolchain; CI promotion pending.

## 1. Scope

`mth/nan16/mth_centrosymmetry_block16.nas` certifies one 16-row strip of a
256×256 float32 matrix:

```
M[i,j] == M[255-i,255-j]   for i,j in 0..255
```

A full dense 256×256 float32 matrix is 65,536 NaN16 words. That fills the
declared 512 KiB guest working set before code, vectors, or scratch are added.
This kernel therefore never materializes the full matrix. It compares one
16×256 A block against one 16×256 mirror block, 4,096 payload words each, and
the caller repeats the call for 16 blocks.

## 2. ABI

| Register | Meaning |
|---|---|
| `r1` | A block, 4,096 float32 payloads, row-major 16 rows × 256 columns |
| `r2` | mirror block, 4,096 float32 payloads, row-major 16 rows × 256 columns |
| `r13` | 1 |
| return `r1` | 1 |
| return `r2` | mismatch count |

Memory: 4,096 + 4,096 = 8,192 words per call. Both blocks are read-only; the
kernel allocates no output and writes no guest memory. It is a leaf routine:
no `CALL`, no static slots. It clobbers `r1-r12` and preserves `r13`; it does
not touch `r14` or `r15`.

Caller preconditions:

- both blocks are readable for 4,096 words;
- A row `k` is global row `base+k`;
- mirror row `k` is global row `255-(base+k)`;
- both blocks use row-major, natural column order (column 0 through 255);
- the two spans are distinct unless the caller deliberately accepts a
  self-comparison that is not a certificate.

The routine has no failure path and always returns `r1=1`.

## 3. Mirror orientation

For a call at `base`, block row `k` is global row `i = base+k`. The caller
supplies mirror row `k` as global row `255-i`:

```
A[k,j]      = M[base+k, j]
mirror[k,c] = M[255-(base+k), c]       c = 0..255
```

The kernel compares every `k=0..15` and `j=0..255`:

```
A[k,j] == mirror[k,255-j]
```

Equivalently:

```
M[base+k, j] == M[255-(base+k), 255-j]
```

The mirror block's rows are ordered by `k`, not by increasing global row. For
`base=0` the mirror rows are global `255,254,...,240`; for `base=240` they are
global `15,14,...,0`. Within each mirror row the columns are stored in natural
order; the kernel performs the `255-j` column reversal itself by starting at
column 255 and decrementing the mirror column pointer.

Comparison is integer `CMP` on the raw 32-bit payload. This is bitwise
equality, not host float equality:

- equal NaN payloads pass and differing NaN payloads fail;
- `+0.0` and `-0.0` fail because their payloads differ;
- no ULP tolerance, rounding, or host math is applied.

## 4. Streaming composition

The caller walks the 16 block bases in order:

```
total_mismatches = 0
for base in 0, 16, 32, ..., 240:
    A      = rows base..base+15
    mirror = rows 255-base .. 255-(base+15), in that k order
    call mth_centrosymmetry_block16
    total_mismatches += r2
```

Each call performs 4,096 comparisons, so the full sweep performs 65,536
comparisons. Because the matrix dimension is even, every unordered entry pair
is visited twice: once from the block containing `i`, and once from the block
containing `255-i`.

Therefore:

- an exact centrosymmetric matrix produces 0 mismatches over the full sweep;
- one asymmetric entry produces 2 mismatches over the full sweep, even though
  a single call containing that entry reports 1.

The fixture exercises both orientations explicitly: after perturbing one
mirror payload, the forward call returns 1 and the reversed call returns 1,
and the checked total is 2. Because the two fixture blocks are exact mirrors
of each other, `(A, mirror)` and `(mirror, A)` stand in for a block at `base`
and its opposite block at `255-base`.

A certificate is only as good as the block correspondence supplied by the
caller. The kernel checks the supplied 8,192 words; it cannot detect that a
caller passed the wrong global rows, reversed the mirror rows, or reused a
block.

## 5. 255-head odd caveat

This kernel is for the even 256-position ring, including the NANNET port
position 255. Its reversal is `i -> 255-i`, with no fixed index.

The 255-head-only aperture is odd. Its reversal is:

```
M[i,j] == M[254-i,254-j]   for i,j in 0..254
```

Row and column 127 are fixed by the reversal, and the fold is 127+128 rather
than 128+128. Certifying that aperture needs different pairing logic: the
fixed middle row must be checked as a column palindrome, the fixed middle
column as a row palindrome, and the remaining 127 pairs must use `254-i`.
This block16 kernel does not implement that case. Do not pad a 255-head matrix
with the NANNET port and reuse this kernel as a head certificate: the port is
not a head, and a 256-position symmetry result does not authorize 255-head
writes.

## 6. Fixture and local run

`mth/tests/mth_centrosymmetry_block16_test.nas` allocates 4,096 words for A and
4,096 words for the mirror block, then checks:

1. Both blocks zeroed: 0 mismatches.
2. Exact mirror image with nonzeros on several rows and columns:
   `A[0,0]=1.0`, `A[3,17]=2.5`, `A[8,100]=0x40490FDB`, `A[15,255]=-2.0`,
   and `A[12,64]=0x7FC00001` (a NaN payload), each mirrored as
   `mirror[k,255-j]`: 0 mismatches. The equal NaN payload also proves the
   comparison is bitwise rather than a float compare.
3. Perturb `mirror[3,238]` to `0x40200001`, one payload bit away from the 2.5
   at `A[3,17]`: forward call = 1, reversed call = 1, total = 2.
4. Repair the entry: both orientations return 0.
5. Perturb `mirror[12,191]` from NaN payload `0x7FC00001` to `0x7FC00002`:
   forward = 1, reversed = 1, total = 2. This catches implementations that
   treat NaN payload differences as equal or that use floating comparison.
6. Restore the NaN payload: 0 mismatches.

Commands and observed output:

```sh
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=emit \
  mth/tests/mth_centrosymmetry_block16_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/centro256b.nan

/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/centro256b.nan \
  --steps 20000000 --serial
```

```text
words 8786
[nan_cli] nan-text: 337623 steps, rc=3, pc=174, trap=''
MTH CENTROSYMMETRY BLOCK16 PASS
```

`rc=3` is the native `HALT` return in this harness; there is no trap.
`nmk.awk -v CMD=check` on the emitted image reports `check: 0 mismatches`.

Owned files:

- `mth/nan16/mth_centrosymmetry_block16.nas`
  SHA-256 `149e4df1933d9df4ae5813ded9efd5c80a19801d9a0a9e46c42a304b872d1a9d`
- `mth/tests/mth_centrosymmetry_block16_test.nas`
  SHA-256 `9d598cef68cf1e401ec3fc56b5e9429688b08fbf609724c39067aeb515ab28fa`

## 7. Limitations

- The caller must supply the correct mirror rows in the correct `k` order.
  The kernel cannot detect a wrong base, swapped rows, pre-reversed columns,
  or a stale block.
- One 16×256 tile shape only. Block heights other than 16 and matrix widths
  other than 256 are not supported by this entry point.
- Even 256×256 only. The 255×255 odd head-only aperture needs a separate
  pairing kernel and fixed-middle checks.
- The per-call mismatch count counts failed comparisons, not unique matrix
  pairs. A full symmetric sweep double-counts each unordered entry pair.
- Bitwise equality is stricter than numerical equality: `+0.0` vs `-0.0` and
  different NaN payloads are mismatches. There is no tolerance parameter.
- No alias/overlap check. Passing overlapping spans produces a comparison
  result, not a trustworthy certificate.
- No digest, seal, signature, or attestation binding. The kernel only checks
  the words it is given; the caller owns block identity and provenance.
- This is a certificate building block only. It does not apply the
  centrosymmetric fold, solve a system, or produce eigenvectors.
- No authorization semantics. A mathematical symmetry is not a write
  authorization; the signed head atlas and reserved-head policy remain
  separate.
- The kernel is read-only and allocates nothing, but the caller still needs
  8,192 words for the two blocks plus accumulator, pointers, code, and
  scratch. The full matrix is never resident.
- No throughput claim is made. The reported step count includes fixture
  initialization and eight kernel invocations, not one call in isolation.
