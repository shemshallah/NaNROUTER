# MTH R4 DRIVE source and CFL / lambda_max guard

Status: source-written and locally executed with the canonical NaN0S `nmk.awk` /
`nan_cli` toolchain on 2026-11-07. Both fixtures print their PASS marker through
the `.nan` text loader. CI promotion and the 1 MiB GLT page-limit run are not
claimed here.

This change owns only:

- `mth/nan16/mth_drive_source_256.nas`
- `mth/tests/mth_drive_source_256_test.nas`
- `mth/nan16/mth_cfl_guard_256.nas`
- `mth/tests/mth_cfl_guard_256_test.nas`
- `docs/MTH_DRIVE_CFL_ABI.md`

No shared registry, runner, workflow, or fixture-runner file is modified.

## 1. Scope

The two kernels close the R4 wave-dynamics gates from
`docs/IMPLEMENTATION_TODO.md` and `docs/DEEP_PLAN_CONT.md`:

1. **Bounded DRIVE source**: a fixed 256-element forward source update,
   `out[i] = state[i] + dt*source[i]`.
2. **CFL / lambda_max guard**: the row-sum infinity norm of a dense 256x256
   float32 operator, plus the inclusive leapfrog/Verlet stability test
   `dt*lambda <= 2.0`.

Both kernels are leaf routines with fixed trip counts. They use only NaN16
float32 `FADD`, `FSUB`, `FMUL`, and `FCMP`, plus integer control flow and the
NaN16 `BOOL.8` bitwise AND. There is no host math, no FMA, no reassociation, no
lookup table, and no 256-element host-side intermediate.

## 2. DRIVE source kernel

Kernel: `mth/nan16/mth_drive_source_256.nas`

```
out[i] = state[i] + dt * source[i]        for i = 0..255
```

`i` increases by one. Each element performs one rounded `FMUL` followed by one
rounded `FADD`. `dt` is loaded once from its scalar word. `state` is not
modified.

### ABI

| Register | Meaning |
|---|---|
| `r1` | `state`, 256 float32 payloads |
| `r2` | `source`, 256 float32 payloads |
| `r3` | pointer to `dt`, one float32 payload |
| `r4` | `out`, 256 float32 payloads |
| `r13` | constant `1` |
| return `r1` | `1` success |
| clobbers | `r1`, `r5`-`r9`, flags |
| preserves | `r2`-`r4`, `r10`-`r15` |

The kernel is a leaf: it contains no `CALL`, uses no static scratch, and does
not use `r15`. Inputs and output must be readable/writable as declared. The
`source` span must not overlap `out`; `state` may be reused as `out` because
element `i` is read before it is written. The caller owns the energy, rate, and
ACL budget; this kernel only performs the bounded forward update.

### Memory

| Object | NaN16 words |
|---|---:|
| state | 256 |
| source | 256 |
| dt | 1 |
| out | 256 |
| **Kernel working set** | **769** |

## 3. CFL / lambda_max guard kernel

Kernel: `mth/nan16/mth_cfl_guard_256.nas`

For a row-major 256x256 float32 matrix `A`:

```
lambda = max_i sum_{j=0}^{255} |A[i,j]|
p      = dt * lambda
return 1 iff p <= 2.0, else 0
```

Rows execute in increasing `i` and columns in increasing `j`. There is exactly
one row accumulator (`+0.0` at row start) and no materialized row-sum array.
The maximum starts at `+0.0`; after each row, `FCMP row_sum, lambda` followed by
`JMP[GT]` replaces the maximum with the row sum by a register bit copy.

### Absolute value without FABS

NaN16 has no `FABS` instruction. The implementation clears the float32 sign bit
with the native bitwise AND:

```
mask = 0x7FFFFFFF          ; MOVI 0, MOVHI 0x7FFF
v    = v & mask            ; BOOL.8 v,v,mask
```

`BOOL.8` is the NaN16 AND class used by `mth_u32_and` in `mth_bitwise.nas`.
This is an exact payload transform for every float32 bit pattern, including
signed zero and NaN payloads; no arithmetic or host operation is involved. For
finite inputs the row sum is nonnegative, so initializing the maximum to
`+0.0` is exact.

### Inclusive boundary and unordered values

After `p = dt*lambda` (one rounded `FMUL`), the kernel executes `FCMP p,2.0`.
NaN16 predicates map `k = 2Z + L` as follows: `LT` accepts `k=1`, `EQ` accepts
`k=2`, and `LE` accepts `k=1` or `k=2`. Therefore:

- `p < 2.0` accepts;
- `p == 2.0` accepts exactly, including the `dt*lambda = 2.0` boundary;
- `p > 2.0` rejects;
- an unordered (NaN) comparison has `k=3` and rejects.

`lambda_out` is written on both the accept and reject paths. `dt` and `lambda`
are pointers to one float32 word each.

### ABI

| Register | Meaning |
|---|---|
| `r1` | `A`, 65,536 float32, row-major 256x256 |
| `r2` | pointer to `dt`, one float32 payload |
| `r3` | pointer to `lambda_out`, one float32 payload |
| `r13` | constant `1` |
| return `r1` | `1` iff `dt*lambda <= 2.0`, else `0` |
| clobbers | `r1`, `r4`-`r12`, `r14`, flags |
| preserves | `r2`, `r3`, `r13`, `r15` |

The kernel is a leaf: no `CALL`, no static scratch, no `r15` use. `A` is
read-only and must not overlap the two scalar words. Finite inputs are assumed;
NaN/Inf domain policy and the decision to dispatch are caller-side.

### Memory budget

| Object | NaN16 words | Bytes |
|---|---:|---:|
| `A` (256x256 float32) | 65,536 | 524,288 |
| `dt` | 1 | 8 |
| `lambda_out` | 1 | 8 |
| **Kernel working set** | **65,538** | **524,304** |
| 1 MiB guest budget | 131,072 | 1,048,576 |
| Remaining for code/scratch | 65,534 | 524,272 |

This fits the 1 MiB budget with the whole matrix resident. It does not fit the
historical 512 KiB (65,536-word) guest because the matrix alone fills that
budget.

## 4. Fixtures

### DRIVE fixture

`mth/tests/mth_drive_source_256_test.nas` lays out:

| Label | Word address |
|---|---:|
| code and puts helper | 0 |
| state | 512 |
| source | 1,024 |
| dt | 1,536 |
| out | 1,537 |
| pass/fail strings | 2,048 |

Checks:

1. `state[i]=1.0`, `source[i]=2.0`, `dt=0.5`; every one of the 256 outputs must
   be exactly `2.0` (`0x40000000`).
2. `dt=0`; every one of the 256 outputs must be exactly `1.0`
   (`0x3F800000`), i.e. `out == state`.
3. `state[0]` and `source[0]` remain unchanged after both calls.

Success marker:

```
MTH DRIVE SOURCE 256 PASS
```

### CFL fixture

`mth/tests/mth_cfl_guard_256_test.nas` lays out:

| Label | Word address |
|---|---:|
| code and puts helper | 0 |
| `A` | 512 |
| dt | 66,048 |
| lambda_out | 66,049 |
| pass/fail strings | 66,050 |

Checks:

1. `A = diag(2)`, `dt=0.5`; `lambda` must be exactly `2.0` and the guard must
   accept (`dt*lambda = 1.0`).
2. `A = diag(2)`, `dt=1.5`; the guard must reject (`dt*lambda = 3.0`).
   `lambda_out` is poisoned to `0.0` before the call, so the reject path must
   rewrite it to exactly `2.0`.
3. Exact boundary: `A = diag(2)`, `dt=1.0`; `dt*lambda = 2.0` must accept.
4. Non-uniform last row/column: `A = diag(2)` except `A[255,255]=6.0`;
   `lambda` must be exactly `6.0` and `dt=0.5` must reject. This fails if the
   row or column bound stops at 255 elements.
5. Zero `A`; `lambda` must be exactly `+0.0` and the guard must accept.
   `lambda_out` is poisoned to `2.0` before the call.

Success marker:

```
MTH CFL GUARD 256 PASS
```

## 5. Local canonical run

From the repository root:

```
LC_ALL=C awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=emit \
  mth/tests/mth_drive_source_256_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/mth_drive_source_256.nan
LC_ALL=C awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=check \
  /data/data/com.termux/files/usr/tmp/opencode/mth_drive_source_256.nan
/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/mth_drive_source_256.nan \
  --steps 1000000 --serial

LC_ALL=C awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=emit \
  mth/tests/mth_cfl_guard_256_test.nas \
  > /data/data/com.termux/files/usr/tmp/opencode/mth_cfl_guard_256.nan
LC_ALL=C awk -f /data/data/com.termux/files/home/nan0s/tools/nmk.awk -v CMD=check \
  /data/data/com.termux/files/usr/tmp/opencode/mth_cfl_guard_256.nan
/data/data/com.termux/files/home/nan0s/aarch64/android/nan_cli \
  --img /data/data/com.termux/files/usr/tmp/opencode/mth_cfl_guard_256.nan \
  --steps 20000000 --serial
```

Observed DRIVE run:

```
words 2062
check: 0 mismatches
MTH DRIVE SOURCE 256 PASS
[nan_cli] nan-text: 13092 steps, rc=3, pc=114, trap=''
exit=0
```

Observed CFL run:

```
words 66062
check: 0 mismatches
MTH CFL GUARD 256 PASS
[nan_cli] nan-text: 2639509 steps, rc=3, pc=195, trap=''
exit=0
```

`rc=3` is `NAN_HALTED`; the trap string is empty and `nan_cli` exits `0`.
The DRIVE image is 2,062 NaN16 words (16,496 bytes; emitted `.nan` text is
66,168 bytes). The CFL image is 66,062 NaN16 words (528,496 bytes; emitted
`.nan` text is 2,170,824 bytes), under the 1 MiB (131,072-word) target.

A post-halt `--peek` of the DRIVE output at word 1,537 reported `3F800000`
(`1.0`), matching the final `dt=0` case. A `--peek 66048:3` of the CFL image
reported `3F000000 00000000 ...`: final `dt=0.5`, final zero-`A` `lambda=+0.0`,
then the start of the PASS string.

### Fixture sensitivity checks

Temporary copies (not the owned files) were mutated and assembled to confirm
the fixtures detect real defects:

| Mutation | Result |
|---|---|
| DRIVE `FADD` -> `FSUB` | `MTH DRIVE SOURCE 256 FAIL` |
| CFL boundary `JMP[LE]` -> `JMP[LT]` | `MTH CFL GUARD 256 FAIL` at the exact `2.0` case |
| CFL bound `MOVI r14,256` -> `255` | `MTH CFL GUARD 256 FAIL` at the `A[255,255]=6` case |

These are fixture self-checks, not additional canonical kernels.

## 6. Limitations

- Fixed sizes only: 256-element DRIVE and 256x256 dense CFL. There is no partial
  tile, stride, transpose, or batch mode.
- CFL uses the row-sum infinity norm, a sufficient but not necessary stability
  bound. It does not compute the spectral radius, eigenvalues, condition
  number, or a full stability region for a different integrator.
- CFL accumulates one row in increasing `j` with float32 rounding. It is a
  reference order, not a compensated or extended-precision sum.
- Finite inputs are assumed. NaN/Inf rows are not rejected by the kernel; an
  unordered max comparison skips the row, and an unordered final product
  rejects. Callers must validate the domain if that is not acceptable.
- DRIVE performs no energy, rate, or ACL enforcement; those remain runner
  policy. It is a forward source update, not an inverse DRIVE/pseudoinverse.
- Local `nan_cli` execution is through the `.nan` text loader. The current
  floppy-image loader still caps at 65,536 words, so the 66,062-word CFL image
  is not evidence of a GLT-enforced 1 MiB page-limit execution.
- No CI registration or workflow edit is part of this change.

## 7. R4 integration contract

A wave-step caller should:

1. validate that the operator digest and basis version match the intended
   `A`;
2. call `mth_cfl_guard_256` with the proposed `dt`;
3. dispatch the wave step only when `r1 == 1`;
4. apply `mth_drive_source_256` for the bounded forward source term;
5. keep the energy, rate, and ACL ledger outside these kernels.

A rejected CFL guard must not silently clamp `dt`; the caller decides whether to
reduce `dt`, reject the job, or stop the trace. `lambda_out` is available for
that decision either way.
