# MTH full 255×255 centrosymmetry certificate

Status: source-written and locally executed PASS with the canonical NaN0S
`nmk.awk` / `nan_cli` toolchain on 2026-11-07 through the `.nan` text loader.
The fixture image is **65,555 NaN16 words** (524,440 bytes), 19 words above the
historical 65,536-word / 512 KiB guest. It targets the new **1 MiB
(131,072 NaN16 words)** guest budget; GLT-enforced 1 MiB page-limit execution
and GLT page-limit enforcement are still pending. Canonical CI run 42395520794 executed the fixture; the local loader accepted the complete
image, as recorded in §7 and §8.

## 1. Scope

`mth/nan16/mth_centrosymmetry_255_full.nas` certifies the complete dense
255×255 float32 matrix:

```
A[i,j] == A[254-i,254-j]   for every i,j in 0..254
```

One leaf call covers all 65,025 matrix entries. The kernel scans A in place,
writes no output array, and returns a boolean certificate:

- `r1 = 1` after all 65,025 directed comparisons match;
- `r1 = 0` at the first mismatching pair.

This is the monolithic form of `mth/nan16/mth_centrosymmetry255_block15.nas`,
which checks one 15×255 strip per call. The full form requires the matrix, code,
and fixture data to be resident together, so it is a 1 MiB-target kernel.

The 255-head reversal is odd: index 127 is fixed. Row 127 maps to itself and
column 127 maps to itself. There is no padding to 256 and no reuse of the even
256×256 block16 kernel. This is a head-only certificate; it does not authorize
the 256-position ring or the NANNET port.

## 2. ABI

| Register | Meaning |
|---|---|
| `r1` | A, 65,025 float32 payloads, row-major 255 rows × 255 columns |
| `r13` | 1 |
| return `r1` | 1 iff every `A[i,j]` is bitwise equal to `A[254-i,254-j]`; 0 on the first mismatch |
| clobbers | `r2`–`r12` |
| preserves | `r13`, `r14`, `r15` |

Memory per call: 65,025 payload words for A. A is read-only; the kernel
allocates no output and writes no guest memory. The routine is a leaf: no
`CALL`, no static slots, no stack.

Caller preconditions:

- A is readable for 65,025 words starting at `r1`;
- the layout is row-major with stride 255 and natural column order 0..254;
- `r13 = 1`;
- the caller owns A and any surrounding image/scratch.

No alignment check, overlap check, digest, or provenance check is performed.
Only one contiguous span is read, so there is no aliasing question inside the
kernel; the caller must still supply the intended matrix.

## 3. Memory budget

| Object | NaN16 words | Bytes |
|---|---:|---:|
| A (255×255 float32) | 65,025 | 520,200 |
| Complete fixture image | 65,555 | 524,440 |
| 1 MiB guest budget | 131,072 | 1,048,576 |
| Remaining 1 MiB headroom vs fixture | 65,517 | 524,136 |
| Historical 512 KiB guest | 65,536 | 524,288 |
| Fixture over historical guest | 19 | 152 |

The matrix alone leaves 511 words under the old 65,536-word ceiling, but the
complete image does not: code, the direct-check helper, and the pass/fail
strings push it 19 words past 512 KiB. This fixture therefore cannot be loaded
by a guest capped at 65,536 words; it is intentionally a 1 MiB-target image.

Fixture address map:

| Region | Word range | Words |
|---|---|---:|
| Code, kernel, helpers | 0..511 (used portion 0..260) | 261 |
| A | 512..65,536 | 65,025 |
| Pass/fail strings | 65,537..65,554 | 18 |

The final string word is index 65,554, so the emitted image is 65,555 words.

## 4. Scan order and the odd 255 case

The scan is increasing row-major over the A side:

```
for i = 0, 1, ..., 254:
    for j = 0, 1, ..., 254:
        compare A[i,j] with A[254-i,254-j]
```

The mirror pointer starts at column 254 of the corresponding mirror row and
decrements by one per step. Comparison k of the scan is exactly
`A[i,j]` against `A[254-i,254-j]`.

The scan stops at the first failing comparison. On a pass all 65,025 directed
comparisons are made; on a failure the kernel returns 0 without examining the
remaining pairs. The ordering is a deterministic, increasing scan of the A
side, not a count of unique mismatch orbits.

The reversal has 32,513 orbits:

- 32,512 two-cell orbits, each compared twice by the full directed scan;
- one one-cell orbit, the centre `(127,127)`, compared once.

The fixed lines need no special branch:

- **Fixed row 127.** When `i = 127`, the mirror row is also row 127. The loop
  compares `A[127,j]` with `A[127,254-j]`, a column-palindrome test.
- **Fixed column 127.** For every `i`, `j = 127` compares
  `A[i,127]` with `A[254-i,127]`. At `i = 127` this is the centre cell,
  compared against itself.
- **Centre cell.** `(127,127)` is self-mirror. A coherent matrix cannot make
  it asymmetric with itself; the comparison still participates in the scan.

## 5. Comparison semantics

Comparison is a 32-bit integer `CMP` on the stored payload. This is bitwise
equality, not host float equality:

- bitwise-equal finite values pass;
- `+0.0` and `-0.0` fail because their payloads differ;
- equal NaN payloads pass; any NaN payload difference (quiet/signalling or
  mantissa payload) fails;
- no tolerance, epsilon, canonicalization, rounding, or host FPU operation is
  involved.

The certificate answers "are these two stored payloads identical?", not "are
these numbers close?".

## 6. Fixture

`mth/tests/mth_centrosymmetry_255_full_test.nas` builds a non-trivial
centrosymmetric matrix entirely in the guest, without host math:

1. zero all 65,025 words;
2. for the 127 upper-half row pairs `i` / `254-i`, fill every `j = 0..254`
   orbit with one deterministic payload in both cells;
3. fill the fixed row 127 as palindrome pairs `j` / `254-j` for `j = 0..126`;
4. write the centre `(127,127)` last.

Payload `k` is `0x3F800001 + k`. Every orbit gets a distinct, finite, non-zero
value, so a zero-filled or permuted matrix cannot pass by accident. The fill
covers `127×255 + 127 + 1 = 32,513` orbits, exactly 65,025 cells.

Direct guest word checks before any kernel call pin down generic, fixed-row,
fixed-column, and centre coverage:

| Cell(s) | Expected payload | Purpose |
|---|---|---|
| `A[0,0]`, `A[254,254]` | `0x3F800001` | corner orbit |
| `A[0,254]`, `A[254,0]` | `0x3F8000FF` | last-column/first-row orbit |
| `A[3,17]`, `A[251,237]` | `0x3F80030F` | generic interior orbit |
| `A[127,126]`, `A[127,128]` | `0x3F807F00` | fixed-row palindrome pair (deepest scan point) |
| `A[20,127]`, `A[234,127]` | `0x3F80146C` | fixed-column pair |
| `A[127,127]` | `0x3F807F01` | centre cell |

Checks performed, in order:

1. exact matrix → kernel returns 1;
2. change exactly one generic word, `A[3,17]` (offset 782) → kernel returns 0;
3. restore that word → kernel returns 1;
4. change exactly one fixed-row word, `A[127,126]` (offset 32,511) → 0;
5. restore, change exactly one fixed-column word, `A[20,127]` (offset 5,227)
   → 0;
6. restore, change exactly one far-corner word, `A[254,0]` (offset 64,770)
   → 0;
7. restore, final exact-matrix call → 1;
8. print `MTH CENTROSYMMETRY 255 FULL PASS`.

Every rejection perturbs exactly one 32-bit payload word by +1, leaving its
mirror partner untouched; the restore subtracts 1 from the same word. The
fixed-row case at `(127,126)` is the deepest possible single-mismatch detection
point: the next comparison is the self-mirror centre. The fixed-column and
far-corner cases cover the odd middle column and the first-row/last-column
boundary, not only the first comparison.

The fixture also uses the kernel three times as a whole-matrix pass (initial,
after the first restore, and final), so a kernel that always returned 1 or
always returned 0 could not reach the pass marker.

## 7. Local evidence

Commands:

```sh
awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=emit \
  mth/tests/mth_centrosymmetry_255_full_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/centro255full.nan

awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=check \
  /data/data/com.termux/files/usr/tmp/opencode/centro255full.nan

/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/centro255full.nan \
  --steps 20000000 --serial
```

Observed:

```text
words 65555
check: 0 mismatches
[nan_cli] nan-text: 2700726 steps, rc=3, pc=241, trap=''

stdout:
MTH CENTROSYMMETRY 255 FULL PASS
```

`rc=3` is the native `HALT` return in this harness; the trap string is empty.
The 20,000,000-step budget was not approached. The 2,700,726 steps cover
matrix fill, direct word checks, and seven whole-matrix certificate calls
(three passing, four rejecting); this is not a per-call step count.

The emitted `.nan` text is about 2.1 MB; the loaded guest image is 65,555
words = 524,440 bytes.

As an additional independent data check, the final image was sampled with
`nan_cli --peek` at offsets spanning the matrix (including 0, 782, 5227,
32511, 32512, 32513, 59797, 64242, 64770, 65024). All sampled payloads matched
the fixture's deterministic fill sequence, and paired offsets matched each
other. This confirms the guest fill produced the intended non-trivial matrix,
not a zero field.

The repository fixture-runner function was also invoked directly with a
temporary `Fixture` record (no shared-file edit) and reported:

```text
[PASS] centro255full: PASS steps=2700726 marker=MTH CENTROSYMMETRY 255 FULL PASS
```

Negative controls were run in a temporary tree with stub kernels that always
returned 1 or always returned 0. Both printed
`MTH CENTROSYMMETRY 255 FULL FAIL`, so the fixture's pass/fail marker is
sensitive to a kernel that ignores the matrix or always rejects it.

## 8. Toolchain loading above 65,536 words

The canonical local `nan_cli` loaded the complete 65,555-word `.nan` text
image, 19 words above the historical 65,536-word ceiling. This is directly
observable in the run: the pass string begins at word 65,537 and was printed,
and the kernel read matrix words through index 65,536.

The local core source default is `NAN_WORDS = 0x400000` (4M words), and this
image uses the `nan-text` loader. The run therefore proves that the canonical
assembler plus local loader executes an image larger than 65,536 words. It does
**not** prove a GLT-enforced 1 MiB page limit; that deployment check remains
pending. A build that caps guest images at 65,536 words must reject this
fixture at load time rather than being treated as a pass.

## 9. Limitations

- 255×255 dense float32 only. No 256×256 ring, no transpose, no alpha/beta
  scaling, and no in-place output.
- One boolean per call. On failure the kernel stops at the first mismatch; it
  does not return a mismatch count. Use the block15 kernel or a diagnostic
  variant if a count or full failing-pair list is needed.
- Bitwise equality is stricter than numerical equality: `+0.0` versus `-0.0`
  and differing NaN payloads are mismatches. There is no tolerance parameter.
- No alias, alignment, digest, seal, signature, or provenance binding. The
  kernel checks only the 65,025 words it is given; the caller owns matrix
  identity and image provenance.
- No fold, solve, eigenvector, matrix-vector, or authorization operation is
  performed. This is a certificate only.
- A mathematical symmetry is not an authorization symmetry. A mirror pair can
  still cross a reserved BSR control head (the documented set is
  `0,4,5,6,7,8`) or map a learning head onto a reserved write target. The
  signed head atlas, reserved-head policy, and write ACL remain separate.
- The local run is a 1 MiB-target text-loader run, not a GLT 1 MiB
  page-limit run; canonical CI execution passed in run 42395520794 and GLT enforcement is pending that harness.
- No throughput claim is made. The reported step count includes fixture
  construction and direct checks, not only the certificate scans.

## 10. Owned files

- `mth/nan16/mth_centrosymmetry_255_full.nas`
- `mth/tests/mth_centrosymmetry_255_full_test.nas`
- `docs/MTH_CENTROSYMMETRY_255_FULL_ABI.md` (this document)

SHA-256 at the time of the recorded run:

```text
6389b0e849fdb87c7476255976f78158fb13f0d4dceb83b657c51a8a9600a81e  mth/nan16/mth_centrosymmetry_255_full.nas
a7a3fa8646d1db08fe6a3a612ef91ce08e5802c2019861bde8e2665a35c6941e  mth/tests/mth_centrosymmetry_255_full_test.nas
```

No shared file was edited and no git commit was made.
