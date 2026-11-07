# MTH 256x256 pair-space tile ABI v1

Status: NATIVE_VERIFIED for the stated tile ABI by canonical NaN16 CI run 201 (2,301,554 guest steps).

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

## Memory budget

- U: 65,536 float32 words = 256 KiB.
- L_I: 4,096 float32 words = 16 KiB.
- L_J: 4,096 float32 words = 16 KiB.
- Output tile: 256 float32 words = 1 KiB.
- Scratch: 6 words = 24 bytes.

Total declared payload is below 290 KiB, within the 512 KiB guest working-set ceiling. The L matrix itself remains in persistent pages; only two 16-row windows are staged into the guest.

## Preconditions and limits

- All spans are valid and pairwise disjoint.
- i_base and j_base are multiples of 16 in [0,240].
- L_I and L_J are the corresponding 16-row windows from the same immutable L digest and precision lane.
- U and L values are finite float32 values; NaN/Inf policy is caller-side until a checked numeric-domain descriptor is added.
- The operator is general dense real L; symmetry is not assumed.
- This v1 ABI does not provide cancellation or partial-output atomicity. A caller writes to a candidate output generation and publishes only after all 256 tiles and the digest check complete.

## Fixture

mth/tests/mth_graph_pair_tile16_f32_test.nas uses L=2I and a two-entry U. The exact oracle is Y=4U. It checks all 256 outputs in the first tile. Canonical NaN16 workflow run 201 assembled and executed the fixture successfully; output marker: MTH PAIR TILE16 F32 PASS. This verifies one 16×16 tile for the L=2I oracle, not full 256-tile orchestration or generic sparse-CSR integration.
