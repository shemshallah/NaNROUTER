# MTH pair-space K16 full-tile driver ABI

Status: LOCAL_NATIVE_VERIFIED (not yet CI-integrated). This is the repaired form
of the WIP driver on `origin/mth-pair-tile16-driver-v1` (commits
`0cee006..788b036`). The fixture assembles with the NaN0S NaN16 source assembler
and terminates after 4,449,894 guest steps under a 50,000,000-step budget
(`rc=3`, HALT).

## Purpose

This driver walks the complete K dimension for one 16x16 output tile of the
dense 256x256 pair-space action:

    Y[i,j] = sum(k=0..255) L[i,k] U[k,j] + sum(k=0..255) U[i,k] L[j,k]

It never materializes the full 256x256 U matrix. The caller stages four strip
buffers for the current output tile, and the driver invokes the bounded K16
accumulator once for each global K slice `0,16,...,240`, then finalizes once.

Entry point: `mth_graph_pair_tile16_k16_driver_f32`

The caller must also link `mth_graph_pair_tile16_k16_f32.nas`, which supplies:

- `mth_graph_pair_tile16_k16_accum_f32` (one K slice)
- `mth_graph_pair_tile16_finalize_f32` (Y = acc_LU + acc_ULt)

## Driver ABI

| Register | Input |
|---|---|
| r1 | `L_IK` strip base: 16 contiguous 16x16 float32 K blocks |
| r2 | `U_KJ` strip base: 16 contiguous 16x16 float32 K blocks |
| r3 | `U_IK` strip base: 16 contiguous 16x16 float32 K blocks |
| r4 | `L_JK` strip base: 16 contiguous 16x16 float32 K blocks |
| r5 | `acc_LU`, 256 words, updated in place |
| r6 | `acc_ULt`, 256 words, updated in place |
| r7 | caller-owned 6-word K16 scratch frame |
| r8 | output tile, 256 words |
| r13 | constant 1 |

Return: `r1=1` only after all sixteen accumulator calls and the single finalize
call succeed. `r1=0` on the first callee failure.

Each strip is laid out as sixteen contiguous 256-word blocks in increasing
global-K order. The block for local slice index `s` begins at
`strip_base + s*256`, and contains the 16x16 block for global K
`K = 16*s`. All four strips for one output tile are staged simultaneously;
strips for other output tiles are not required.

All pointer spans (four strips, both accumulators, scratch, output) must be
valid and pairwise disjoint, and none may overlap words 400..411 or the
driver's code.

Register effects: the driver clobbers `r1-r12`; it saves and restores `r14` and
`r15`; it leaves `r13=1`; `r0` remains the zero register. The driver performs
no arithmetic on matrix values itself.

## Loop and failure semantics

1. Save the four strip bases, both accumulator bases, scratch, output pointer,
   `r14`, and the caller's `r15` link in a private static frame.
2. For slice count `0..15`, build the four block pointers as
   `strip_base + slice_count*256`, call
   `mth_graph_pair_tile16_k16_accum_f32`, and require `r1=1`.
3. After the sixteenth successful slice, call
   `mth_graph_pair_tile16_finalize_f32` exactly once with
   `r1=acc_LU`, `r2=acc_ULt`, `r3=output tile`.
4. Restore `r14`/`r15` and return `r1=1` or `r1=0`.

The driver does not call finalize after an accumulator failure, so in that case
it leaves the output tile untouched. A failed finalize may have written a
partial output tile; callers should treat `r1=0` as an invalid tile.

## State and reentrancy

The driver is not reentrant. It owns a private 12-word static frame at guest
words 400..411. A caller embedding this driver must keep code and data out of
that range.

| Offset | Meaning |
|---|---|
| 0 | `L_IK` strip base |
| 1 | `U_KJ` strip base |
| 2 | `U_IK` strip base |
| 3 | `L_JK` strip base |
| 4 | `acc_LU` base |
| 5 | `acc_ULt` base |
| 6 | 6-word K16 scratch pointer |
| 7 | output tile base |
| 8 | current K word offset (0,256,...,3840) |
| 9 | completed slice count (0..16) |
| 10 | saved caller `r14` |
| 11 | saved caller `r15` |

In NaN16, `CALL` overwrites `r15` with the return address and `RET` jumps to
`r15`. The original WIP driver issued nested `CALL`s without preserving its own
link, so its final `RET` reused the return address left by the last nested call
and jumped back inside the driver instead of to its caller. The repaired driver
stores `r15` in the static frame on entry and restores it on both the success
and failure paths. `r12` is only a temporary frame pointer and is recomputed
after every callee call because the accumulator clobbers it.

## Memory budget

Per output tile, the driver touches:

- 4 strips x 4096 words = 16,384 words
- 2 accumulators x 256 words = 512 words
- output tile = 256 words
- K16 scratch = 6 words
- private state = 12 words
- total = 17,170 words = 137,360 bytes (8 bytes per NaN16 word)

This is about 134 KiB, below both the 512 KiB runner limit and the default
1 MiB MTH guest budget. The accumulator's own per-call working set remains
1,542 words as documented in `docs/MTH_GRAPH_PAIR_TILE16_K16_ABI_V1.md`.

## Determinism

Global K slices are visited in strictly increasing order `0,16,...,240`. Within
each slice, the accumulator visits local K `0..15` in increasing order, keeps
the two products in separate `+0.0` accumulators, and uses one rounded `FMUL`
followed by one rounded `FADD` per term. Finalization performs one rounded
`FADD` per output cell. There is no FMA, reassociation, parallel reduction, or
host math.

## Fixture

`mth/tests/mth_graph_pair_tile16_k16_driver_f32_test.nas` runs two tile
patterns through the whole driver:

- Pattern 1: slice 0 stages `L[1,3]=2`, `U[3,2]=2`, giving
  `acc_LU[1,2]=4`; slice 15 stages `U[1,5]=2`, `L[2,5]=2`, giving
  `acc_ULt[1,2]=4`. The finalized `Y1[1,2]` must be `8.0`.
- Pattern 2: slice 0 stages `L[2,4]=1`, `U[4,5]=2`, giving
  `acc_LU[2,5]=2`; slice 15 stages `U[2,7]=2`, `L[5,7]=3`, giving
  `acc_ULt[2,5]=6`. The finalized `Y2[2,5]` must be `8.0`.

Both patterns validate every other cell of the 16x16 output as zero. A
successful run prints:

    MTH PAIR K16 DRIVER PASS

## Verification

Using the canonical NaN0S toolchain:

    mkdir -p build/mth
    awk -f nan0s/tools/nmk.awk -v CMD=emit \
      mth/tests/mth_graph_pair_tile16_k16_driver_f32_test.nas \
      > build/mth/pair-tile16-k16-driver.nan
    nan0s/aarch64/android/nan_cli \
      --img build/mth/pair-tile16-k16-driver.nan \
      --steps 50000000 --serial \
      > build/mth/pair-tile16-k16-driver.out \
      2> build/mth/pair-tile16-k16-driver.err

Observed:

    stdout: MTH PAIR K16 DRIVER PASS
    stderr: [nan_cli] nan-text: 4449894 steps, rc=3, pc=582, trap=''

`rc=3` is `NAN_HALTED`, not budget exhaustion, so the driver terminates well
under the 50,000,000-step budget. The pre-fix WIP image at commit 788b036 with
the same fixture exhausted all 50,000,000 steps at `pc=155` after printing one
progress dot per accumulator call; that was the unpreserved `r15` return-link
loop described above.
