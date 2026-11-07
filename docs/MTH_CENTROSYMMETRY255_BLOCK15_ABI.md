# MTH 255-head odd centrosymmetry certificate (15×255 block)

Status: source-written and locally executed with the canonical NaN0S toolchain; CI promotion pending.

## 1. Scope

`mth/nan16/mth_centrosymmetry255_block15.nas` certifies one 15-row strip of a
255×255 float32 head-only matrix:

```
M[i,j] == M[254-i,254-j]   for i,j in 0..254
```

The 255-head aperture is odd. The reversal `i <-> 254-i` has one fixed index,
127, so row 127 and column 127 map to themselves. There is no 128+128 even
fold here; the centre is one fixed line in each direction.

A full dense 255×255 float32 matrix is 65,025 NaN16 words. This kernel never
materializes it. One call compares a 15×255 A block against a 15×255 mirror
block, 3,825 payload words each. Because `255 = 17 × 15` exactly, the caller
tiles the matrix with 17 calls and no padding row.

## 2. ABI

| Register | Meaning |
|---|---|
| `r1` | A block, 3,825 float32 payloads, row-major 15 rows × 255 columns |
| `r2` | mirror block, 3,825 float32 payloads, row-major 15 rows × 255 columns |
| `r13` | 1 |
| return `r1` | 1 |
| return `r2` | mismatch count |

Memory per call: 3,825 + 3,825 = 7,650 payload words. Both blocks are
read-only; the kernel allocates no output and writes no guest memory. It is a
leaf routine: no `CALL`, no static slots. It clobbers `r1-r12`, preserves
`r13`, and does not touch `r14` or `r15`.

Caller preconditions:

- both blocks are readable for 3,825 words;
- A row `k` is global row `base+k`;
- mirror row `k` is global row `254-(base+k)`;
- both blocks use row-major, natural column order (column 0 through 254);
- the two spans are distinct unless the caller deliberately accepts a
  self-comparison that is not a certificate;
- the mismatch accumulator and the block pointers belong to the caller.

The routine has no failure path and always returns `r1=1`.

## 3. Mirror orientation

For a call at `base`, block row `k` is global row `i = base+k`. The caller
supplies mirror row `k` as global row `254-i`, in natural column order:

```
A[k,j]      = M[base+k, j]
mirror[k,c] = M[254-(base+k), c]        c = 0..254
```

The kernel compares every `k=0..14` and `j=0..254`:

```
A[k,j] == mirror[k,254-j]
```

Equivalently:

```
M[base+k, j] == M[254-(base+k), 254-j]
```

The mirror block's rows are ordered by `k`, not by increasing global row. For
`base=0` the mirror rows are global `254,253,...,240`; for `base=240` they are
`14,13,...,0`. Within each mirror row the columns are stored in natural order;
the kernel performs the `254-j` column reversal itself by starting at column
254 and decrementing the mirror column pointer.

Comparison is integer `CMP` on the raw 32-bit payload. This is bitwise
equality, not host float equality:

- equal NaN payloads pass and differing NaN payloads fail;
- `+0.0` and `-0.0` fail because their payloads differ;
- no ULP tolerance, rounding, or host math is applied.

## 4. The odd 255 case: fixed row 127 and fixed column 127

The kernel has no special branch for the fixed middle. The caller-supplied
mirror block makes the generic loop cover both fixed lines:

- **Fixed row 127.** Row 127 lies in the `base=120` block (global rows
  120..134) at block row 7. The caller must supply global row 127 again as
  mirror row 7, in natural column order. The kernel then compares
  `A[7,j]` with `mirror[7,254-j]`, i.e. it checks the fixed middle row for a
  column palindrome. If the caller supplies a different row as mirror row 7,
  the result is not a certificate for row 127.
- **Fixed column 127.** For every `k`, column `j=127` is compared with
  `mirror[k,254-127] = mirror[k,127]`. That checks
  `M[base+k,127]` against `M[254-(base+k),127]` for every paired row. At
  `base=120, k=7` this is the centre cell `(127,127)`, compared against its
  duplicate in the mirror block.
- **Centre cell.** `(127,127)` is the only one-cell reversal orbit. In the
  full sweep it is compared once, not twice. A coherent matrix cannot make
  the centre asymmetric with itself; a caller-side disagreement between the
  two copies of row 127 can still be reported, but only once at the centre
  cell. The fixed row's other column pairs and the fixed column's row pairs
  are ordinary two-cell orbits and are compared twice.

Do not pad a 255-head matrix to 256 and reuse the even block16 kernel. The
NANNET port is not a head, and the 256-position result does not authorize
255-head writes.

## 5. Streaming composition

The caller walks the 17 block bases in order:

```
total_mismatches = 0
for base in 0, 15, 30, ..., 240:
    A      = rows base..base+14
    mirror = row k = global 254-(base+k), for k = 0..14
    call mth_centrosymmetry255_block15
    total_mismatches += r2
```

Each call performs 3,825 comparisons, so the full sweep performs
`17 × 3,825 = 65,025` comparisons, exactly `255²`.

The reversal has 32,513 orbits: 32,512 two-cell orbits and the one-cell
centre `(127,127)`. Every two-cell orbit is visited twice (65,024 directed
comparisons), and the centre is visited once (1 comparison). Therefore:

- an exact centrosymmetric matrix produces 0 mismatches over the full sweep;
- one asymmetric off-centre entry produces 2 mismatches over the full sweep;
- a coherent matrix cannot be asymmetric at the centre; an inconsistent
  duplicate of the centre cell can produce 1 mismatch.

For `base` and `base' = 240-base`, the two calls are opposite orientations.
When `base=120`, `base'=120`: the block contains both sides of every orbit in
its row range, so a true asymmetric pair produces 2 mismatches inside that
single call. A discrepancy introduced into only one copy of a cell in the
self-opposite block is a different condition: one call reports it once (and
the fixture's reversed probe reports it once more).

A certificate is only as good as the block correspondence supplied by the
caller. The kernel checks the supplied 7,650 words; it cannot detect that a
caller passed the wrong global rows, reversed the mirror rows, pre-reversed
the columns, or reused a stale block.

## 6. Comparison semantics

The comparison is a 32-bit integer `CMP` on the stored payload, not a floating
comparison. Consequences:

- bitwise-equal finite values pass;
- `+0.0` and `-0.0` mismatch;
- equal NaN payloads pass; any payload difference, including a quiet/signalling
  or mantissa-payload difference, fails;
- no tolerance, epsilon, canonicalization, or host FPU operation is involved.

This is intentional: the certificate answers "are these two stored payloads
identical?", not "are these numbers close?".

## 7. Fixture and local run

`mth/tests/mth_centrosymmetry255_block15_test.nas` uses `base=120`, so the
block is global rows 120..134 and the fixed middle row 127 is A row 7 and
mirror row 7. The exact mirror block is built in-guest by the row reversal

```
mirror[k,c] = A[14-k,c].
```

The fixture sets these A nonzeros (all other entries zero):

| Cell(s) | Payload | Purpose |
|---|---|---|
| `A[0,0]`, `A[14,254]` | `0x3F800000` (1.0) | ordinary corner orbit |
| `A[3,17]`, `A[11,237]` | `0x40200000` (2.5) | generic two-cell orbit |
| `A[7,20]`, `A[7,234]` | `0x40490FDB` | fixed middle row palindrome |
| `A[3,127]`, `A[11,127]` | `0xC0000000` (-2.0) | fixed middle column pair |
| `A[7,127]` | `0x7FC00001` | centre cell, NaN payload |
| `A[2,64]`, `A[12,190]` | `0x7FC00002` | ordinary pair, second NaN payload |

Before certifying, the fixture directly checks representative words in both
blocks, including `A[7,20]`, `mirror[7,234]`, `A[3,127]`, `mirror[11,127]`,
the centre payload, and a generic mirror pair. This prevents a zero-field
pass from being mistaken for the intended middle-row/column coverage.

Checks performed:

1. Exact block, forward orientation: 0 mismatches. Reverse orientation: 0.
2. One coherent asymmetric matrix entry in the self-opposite `base=120`
   block: set the global cell `M[131,237]` to `0x40400000` (3.0) in both of
   its copies, while its partner `M[123,17]` stays 2.5. The single
   `base=120` call reports exactly 2 mismatches.
3. Restore that cell: forward returns 0.
4. Perturb only `mirror[3,237]` to `0x40200001`, one payload bit away from
   the 2.5 at `A[3,17]`: forward = 1, reverse = 1, checked sum = 2.
5. Repair the payload: forward = 0.
6. Perturb the fixed middle row at `mirror[7,234]` to `0x40490FDC`:
   forward = 1, reverse = 1, sum = 2. Restore: forward = 0.
7. Perturb the fixed middle column at `mirror[11,127]` to `0xC0000001`:
   forward = 1, reverse = 1, sum = 2. Restore: forward = 0.
8. Perturb the NaN pair at `mirror[2,190]` from `0x7FC00002` to
   `0x7FC00003`: forward = 1, reverse = 1, sum = 2. Restore: forward = 0.
9. Final forward and reverse orientation calls: 0 mismatches.

The reverse call is a second-orientation probe on the same self-opposite
`base=120` block, not a second call in the 17-call sweep. It confirms the
kernel's directional logic and gives the requested one-mirror-payload check
total of 2. The sweep-faithful double count for a coherent matrix is step 2,
where one asymmetric entry yields 2 mismatches inside the single `base=120`
call.

Commands and observed output:

```sh
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=emit \
  mth/tests/mth_centrosymmetry255_block15_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/centro255b.nan

awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=check \
  /data/data/com.termux/files/usr/tmp/opencode/centro255b.nan

/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/centro255b.nan \
  --steps 20000000 --serial
```

```text
words 8788
check: 0 mismatches
[nan_cli] nan-text: 653767 steps, rc=3, pc=328, trap=''
MTH CENTROSYMMETRY 255 BLOCK15 PASS
```

`rc=3` is the native `HALT` return in this harness; there is no trap. The
reported 653,767 steps cover fixture initialization, direct word checks, and
17 kernel invocations, not one isolated call. The 20,000,000-step budget was
not approached.

Owned files and SHA-256 at the time of this run:

- `mth/nan16/mth_centrosymmetry255_block15.nas`
  `b1408d0332bc152423074a633f446cbbb0fe8f1c56829f2ebc72998f1f8efa4f`
- `mth/tests/mth_centrosymmetry255_block15_test.nas`
  `2fde958e58b89adf85030e64ac0cdb07ea104ce7b3539c01f9fe3eb1dccd3322`

## 8. Authorization caveat

The 255×255 head-only matrix is the authorization-safe head block: it excludes
NANNET0 / ring position 255. A symmetry result here says nothing about the
port row or column, and it does not authorize the 256-position ring.

A mathematical symmetry is not an authorization symmetry. A mirror pair can
still cross a reserved BSR control head (the documented set is `0,4,5,6,7,8`)
or map a learning head onto a reserved write target. The signed head atlas,
the reserved-head policy, and the write ACL remain separate from this kernel.
This routine only proves payload equality along the reversal it is given; it
does not prove that the matrix is the authorized operator, that the caller may
write the paired heads, or that a fold should be applied.

## 9. Limitations

- One tile shape only: 15×255. Block heights other than 15 and matrix widths
  other than 255 are not supported by this entry point.
- Odd 255×255 head-only only. The even 256×256 ring has a separate block16
  kernel; do not pad or reuse across the port boundary.
- The caller must supply the correct mirror rows in the correct `k` order.
  The kernel cannot detect a wrong `base`, swapped rows, pre-reversed columns,
  a stale block, or a wrong duplicate of row 127.
- Fixed row 127 and fixed column 127 have no special kernel path; they are only
  certified if the caller constructs the mirror block correctly.
- The per-call count counts failed comparisons, not unique matrix pairs. A
  full sweep double-counts every two-cell orbit and counts the centre once.
- Bitwise equality is stricter than numerical equality: `+0.0` versus `-0.0`,
  and different NaN payloads, are mismatches. There is no tolerance parameter.
- No alias or overlap check. Passing overlapping spans produces a comparison
  result, not a trustworthy certificate.
- No digest, seal, signature, or attestation binding. The kernel checks only
  the words it is given; the caller owns block identity and provenance.
- No fold, solve, eigenvector, or matrix-vector operation is performed. This is
  a certificate building block only.
- No authorization semantics, as described in section 8.
- The kernel is read-only and allocates nothing, but the caller still needs
  7,650 words for the two blocks plus accumulator, pointers, code, and scratch.
  The full 255×255 matrix is never resident.
- No throughput claim is made. The reported step count includes fixture setup,
  direct word checks, and 17 invocations.
