# MTH sparse graph Laplacian ABI v1

Status: **frozen implementation contract; native_verified** by canonical NaN16 CI run #58.

## Scope

The first sparse operator is the exact unweighted symmetric simple-graph Laplacian over the existing 256 Heads. This is a deliberate first subset of the weighted coupling model. It does not rewrite directed relationship rails and does not infer symmetry from address reversal.

For each vertex i:

\[
(Lx)_i=\sum_{j\in N(i)}(x_i-x_j)=d_i x_i-\sum_{j\in N(i)}x_j.
\]

The graph is represented as canonical CSR with both directions of every undirected edge present.

## Numeric ABI: Q16.16/I32 v1

| Field | Representation |
|---|---|
| Input state x | signed two's-complement I32, Q16.16 |
| Input raw range | [-2^22, +2^22], corresponding to [-64, +64] |
| Output Lx | signed two's-complement I32, Q16.16 |
| Rounding | none; exact integer arithmetic |
| Saturation/wrap | neither; preconditions prove no overflow |
| Maximum vertices | 256 |
| Maximum degree | 255 |
| Maximum directed CSR entries | 65,280 |
| Workspace | caller-owned input/output pages; no static scratch |

For every edge, the largest possible difference is 2^23 raw units. A row has at most 255 neighbors, so:

\[
|(Lx)_i|\le255\cdot2^{23}=2,139,095,040<2^{31}.
\]

Thus every intermediate row sum and final output fits signed I32. The kernel performs no floating-point operation, rounding, saturation, or host-side math.

This bounded range is intentional for v1. A later weighted operator will receive a separately versioned ABI with explicit weight scale and wider accumulation; it must not silently reuse this contract.

## CSR contract

- `row_offsets`: 257 U32 words; first offset 0, final offset equals edge_count, monotone nondecreasing.
- `neighbors`: edge_count U32 words; each value is a Head index 0..255.
- `edge_count`: 0..65,280; every row degree <=255.
- Graph is simple, undirected, symmetric, and has no self-loops.
- Each row is sorted and contains no duplicate endpoint.
- The immutable graph page reference is bound to a validated graph digest. The caller/runner verifies symmetry, sorting, uniqueness, and no-self-loop policy before dispatch. The native kernel preflights offset monotonicity, final edge count, endpoint range, degree bound, and all state values.
- Input and output spans must not overlap.

The kernel does not alter W, W_s, W_a, the semantic ledger, or hyperedges. The CSR is an explicitly derived operator view.

## Native entry point

`mth_sparse_graph_laplacian_q16_16`

Registers:
- `r1`: row_offsets
- `r2`: neighbors
- `r3`: x
- `r4`: output
- `r5`: edge_count
- `r13`: constant 1

Return:
- `r1=1`: success
- `r1=0`: invalid edge count, CSR offset/endpoint/degree, or input state

The kernel is leaf-only, uses no shared static return slots, and completes all validation before the first output write. The caller supplies non-overlapping immutable input pages and an output page.

## Exact fixtures

1. Path graph 0--1--2--3 with x=[0,1,4,9] tests negative and positive row results.
2. Disconnected graph (0--1) + (2--3), with vertices 4..255 isolated, tests component-local action and zero rows.
3. Out-of-range Q16.16 input tests failure atomicity: output remains unchanged.

The fixtures are assembled and executed only by the canonical NaN16 source assembler and NaN0S guest harness. Source presence alone is not a pass. The sparse kernel is **native_verified** for this exact unweighted Q16.16/I32 v1 contract. CI run #58 assembled the fixture and executed the path, disconnected, and invalid-input atomicity checks successfully (20,737 guest steps; expected HALT). Kernel SHA-256: `013048435c1026643554fb20e3434934cf059dd47cf2857577cac13ed5be6b8f`. This evidence does not extend to weighted CSR or wave evolution.

## Next

After this exact unweighted baseline passes:
1. Add a weighted CSR ABI with explicit UQ weight scale and signed wide accumulation.
2. Add symmetry/energy and connected-component fixtures.
3. Register the exact kernel digest and workspace in NAN-RSS-1 only after native verification.
4. Proceed to pair-space action; keep void, Lanczos, filters, and wave stepping behind the sparse-kernel gate.
