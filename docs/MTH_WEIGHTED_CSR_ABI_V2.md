# MTH weighted CSR Laplacian ABI v2

Status: **specified; not source-written or native-verified**. This contract is separate from the frozen unweighted Q16.16/I32 v1 operator.

## 1. Mathematical operator

For a symmetric, nonnegative, weighted simple graph represented by canonical CSR:

\[
(L_w x)_i=\sum_{j\in N(i)} w_{ij}(x_i-x_j).
\]

Every undirected edge appears in both directions and reciprocal entries carry exactly equal weights. The directed semantic relation rails are not rewritten; this CSR is a named, immutable derived coupling view with its own digest and policy.

## 2. Numeric ABI

| Field | Representation |
|---|---|
| State x | signed two's-complement I32, Q16.16 |
| State raw range | [-2^22,+2^22] = [-64,+64] |
| Edge weight | U8 integer, range [1,255], scale exactly 1 |
| Degree | at most 255 |
| Output | signed two's-complement I64, Q16.16 |
| Rounding | none |
| Saturation/wrap | neither |
| Vertices | exactly 256 |
| Directed CSR entries | 0..65,280 |
| Output layout | two U32 words per vertex: low word, then high word (two's-complement I64) |
| Workspace | caller-owned; exact scratch-frame size is a source implementation gate |

Weights are dimensionless integer multipliers, not Q0.8 values. This deliberately avoids an implicit rescaling or rounding step. A future fractional-weight operator must receive another ABI version.

For all valid states:

\[
|x_i-x_j|\le 2^{23}.
\]

For one edge:

\[
|w_{ij}(x_i-x_j)|\le255\cdot2^{23}=2,139,095,040<2^{31}.
\]

For one row, with at most 255 neighbors:

\[
|(L_wx)_i|\le255^2\cdot2^{23}
=545,469,235,200<2^{40}<2^{63}.
\]

Thus a signed 64-bit accumulator is sufficient with substantial headroom. Each per-edge product also fits signed I32, but row accumulation does not; the implementation must sign-extend each exact per-edge product into the I64 accumulator. No rounding or saturation is permitted.

## 3. CSR descriptor

- `row_offsets`: 257 U32 values; first 0, final exactly `edge_count`, monotone nondecreasing.
- `neighbors`: `edge_count` U32 values; each endpoint is 0..255.
- `weights`: `edge_count` U32 storage words; only low 8 bits are used and all upper 24 bits must be zero; low byte must be nonzero.
- `edge_count`: 0..65,280; each row degree <=255.
- No self-loops, sorted unique neighbors, symmetric reciprocal endpoints, and exactly equal reciprocal weights.
- Input state, offsets, neighbors, weights and output spans must obey the non-overlap contract.
- The immutable graph descriptor is bound to a digest. The caller/runner validates sorted uniqueness, no self-loops, symmetry and reciprocal weight equality before native dispatch. The kernel independently preflights count, offsets, degree, endpoint encoding/range, weight encoding/nonzero, and all state bounds before writing output.

## 4. Native entry point (planned)

`mth_sparse_weighted_graph_laplacian_q16_16_i64_v2`

Planned inputs:
- `r1`: row_offsets
- `r2`: neighbors
- `r3`: weights
- `r4`: x
- `r5`: output (512 U32 words)
- `r6`: edge_count
- `r7`: caller-owned 16-word U32 scratch frame (indices 0..14 used)
- `r13`: constant 1

Return status must distinguish success, invalid state/count, invalid offsets, invalid endpoints, and invalid weights. All descriptor and numeric validation must finish before the first output write. Output must be deterministic and exact.

The register/scratch ABI is now specified: the routine saves all long-lived pointers and row state in the 16-word caller frame, retaining its base in r11 across the wide-multiply helper. The source is written but remains **unverified** until canonical CI passes. Do not dispatch this operator or advertise it as source-written/native-verified until both exist and canonical NaN16 CI passes.

## 5. Exact native fixtures required

1. **Weighted path:** 0--1--2--3, weights [2,3,5], state [0,1,4,9]. Expected real outputs [-2,-7,-16,25], represented as raw Q16.16 values multiplied by 65,536. This distinguishes weighted action from v1.
2. **Unequal edge weights:** same topology with weights [1,7,2], independently computed exact output [-1,-20,11,10].
3. **Disconnected weighted graph:** two weighted components plus isolated vertices; each component's row sums are zero.
4. **Zero state / constant state:** exact zero output for both.
5. **Invalid weight word:** nonzero high 24 bits rejects without changing any output word.
6. **Zero weight:** rejects without changing output.
7. **Out-of-range state and malformed CSR:** reject before any output write.
8. **Symmetry validation:** reciprocal weight mismatch is rejected by descriptor validation and must never be passed to the kernel.

## 6. Graph invariants required before pair-space

For a validated symmetric nonnegative weighted graph:

\[
\mathbf{1}^{T}L_w=0,\qquad L_w\mathbf{1}=0,
\]

and

\[
x^T L_w x=\sum_{\{i,j\}\in E}w_{ij}(x_i-x_j)^2\ge0.
\]

The native test suite must verify exact row-sum/nullspace behavior on fixtures and compute the energy using a separately bounded wide-accumulator routine. Connected-component count must match Laplacian nullity on small exact fixtures. Do not claim these properties from a single path-vector oracle.

## 7. Evidence boundary and next gates

- v1 remains the only native-verified sparse graph Laplacian.
- v2 is a specified ABI only.
- Next: freeze scratch/call ABI, implement the NaN16 weighted kernel and fixture, add it to the canonical assembler/guest workflow, then record the exact source digest and execution evidence.
- Only after v2 native verification: add energy and component/nullity kernels; then pair-space action. Void potential, Lanczos, filters and wave evolution remain behind those gates.
