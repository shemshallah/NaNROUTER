# MTH 256×256 pair-space K16 streaming ABI v1

Status: SOURCE-WRITTEN; canonical execution pending.

## Purpose

The dense 256×256 U matrix occupies 65,536 NaN16 words. At 8 bytes per word, that alone is 512 KiB, leaving no room for code, L windows, accumulators, or output. The earlier full-U tile reference is mathematically verified but not dispatchable under the 512 KiB guest budget.

This K16 ABI is the bounded implementation. It never stages the full U matrix.

## Operation

For one 16×16 output tile, process the global K dimension in 16-wide slices, in increasing order:

    acc_LU[p,q] += Σ(k=0..15) L_IK[p,k] * U_KJ[k,q]
    acc_ULt[p,q] += Σ(k=0..15) U_IK[p,k] * L_JK[q,k]
    Ytile[p,q] = acc_LU[p,q] + acc_ULt[p,q]

The caller invokes the accumulator for K blocks 0,16,...,240, retaining the two independent partial-sum tiles between calls. The finalize entry point combines them only after all 16 K blocks have completed.

## Accumulator ABI

Entry point: mth_graph_pair_tile16_k16_accum_f32

| Register | Input |
|---|---|
| r1 | L_IK, 16×16 float32 |
| r2 | U_KJ, 16×16 float32 |
| r3 | U_IK, 16×16 float32 |
| r4 | L_JK, 16×16 float32 |
| r5 | acc_LU, 16×16 float32, updated in place |
| r6 | acc_ULt, 16×16 float32, updated in place |
| r7 | caller-owned 6-word scratch frame |
| r13 | constant 1 |

Each input is one 16×16 row-major block for the same output tile and K slice. The caller must pass K slices in strictly increasing order. The kernel does not reset accumulators.

## Finalize ABI

Entry point: mth_graph_pair_tile16_finalize_f32

- r1 = acc_LU, 256 words
- r2 = acc_ULt, 256 words
- r3 = output tile, 256 words
- r13 = constant 1
- returns r1=1

## Working set

Accumulator invocation:
- Four input blocks: 1,024 NaN16 words.
- Two persistent accumulators: 512 words.
- Scratch: 6 words.
- Total: 1,542 NaN16 words = 12,336 bytes.

Finalize invocation:
- Two accumulator blocks and one output block: 768 NaN16 words = 6,144 bytes.

Both are well below the 65,536-word / 512 KiB guest ceiling. U and L remain in external versioned pages; only the required four 16×16 windows are staged per K slice.

## Determinism and publication

Within each call, K=0..15 is accumulated in increasing order. The caller orders global K slices 0..240. The two terms retain separate accumulators, with one rounded FMUL and FADD per term and no FMA or reassociation. Finalization performs one FADD per output cell.

The caller writes output tiles to a candidate generation and publishes only after all 256 output tiles, all 16 K slices per tile, the immutable U/L digests, and the final page-set digest validate. A failed/cancelled generation is discarded; no partial result becomes canonical.

## Fixture

mth/tests/mth_graph_pair_tile16_k16_f32_test.nas uses two K slices for L=2I and U[17,34]=2. It verifies acc_LU=4 after the first slice, acc_ULt=4 after the second, and the complete output tile Y[1,2]=8 with all other cells zero.
