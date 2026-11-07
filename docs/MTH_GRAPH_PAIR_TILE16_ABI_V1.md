# MTH 256x256 pair-space tile ABI v1

Status: NATIVE_VERIFIED by canonical NaN16 CI run 218 (4,643,414 guest steps); dispatchable when the runner is configured with the default 1 MiB MTH guest budget and rejected by a 512 KiB runner.

## Operation

For a real dense 256x256 matrix L and product-state matrix U:

    Y = L U + U L^T
    Y[i,j] = sum(k=0..255) L[i,k] U[k,j] + sum(k=0..255) U[i,k] L[j,k]

This ABI computes one 16x16 output tile. It never materializes the 65,536x65,536 Kronecker operator.

## Native entry point

mth_graph_pair_tile16_f32

| Register | Input |
|---|---|
| r1 | U, full 256x256 row-major float32 (65,536 words) |
| r2 | L_I, 16x256 row-major float32 rows beginning at global i_base |
| r3 | L_J, 16x256 row-major float32 rows beginning at global j_base |
| r4 | output tile, 16x16 row-major float32 |
| r5 | i_base, multiple of 16 in [0,240] |
| r6 | j_base, multiple of 16 in [0,240] |
| r7 | caller-owned 6-word scratch frame |
| r13 | constant 1 |

Return: r1=1. The caller supplies the two immutable L row windows from one operator version and invokes all 16x16 tile positions (256 calls) for a complete 256x256 output.

## Determinism

For each output cell, the first sum and second sum use separate +0.0 accumulators. Each executes k=0..255 in increasing order, with one rounded FMUL followed by one rounded FADD per term. The final result is one FADD of the two completed sums. No FMA, parallel reduction, reassociation, or hidden precision is permitted.

## Memory budget and dispatch status

The complete guest working set is 65,536 + 4,096 + 4,096 + 256 + 6 = 73,990 NaN16 words (591,920 bytes). The MTH guest budget is configurable and defaults to 131,072 words (1 MiB), so this reference fits with 57,082 words (456,656 bytes) of headroom. A runner with only 65,536 words (512 KiB) must reject it. The K16 streaming ABI remains the preferred bounded path when minimizing guest memory is more important than avoiding page-window staging.

## Preconditions and limits

- All spans are valid and pairwise disjoint.
- i_base and j_base are multiples of 16 in [0,240].
- L_I and L_J are the corresponding 16-row windows from the same immutable L digest and precision lane.
- U and L values are finite float32 values; NaN/Inf policy is caller-side until a checked numeric-domain descriptor is added.
- The operator is general dense real L; symmetry is not assumed.
- This v1 ABI does not provide cancellation or partial-output atomicity. A caller writes to a candidate output generation and publishes only after all 256 tiles and the digest check complete.

## Fixture

mth/tests/mth_graph_pair_tile16_f32_test.nas uses L=2I and a three-entry U. The exact oracle is Y=4U. It checks all 256 outputs in the two tiles. Canonical NaN16 workflow run 218 assembled and executed the fixture successfully; output marker: MTH PAIR TILE16 F32 PASS. This verifies two 16×16 tiles for the L=2I oracle at global origins (0,0) and (16,32), not full 256-tile orchestration or generic sparse-CSR integration.
