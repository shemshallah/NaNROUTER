# MTH graph invariants ABI

Status: connected-component kernel source-written; canonical native execution pending. Weighted CSR Laplacian v2 is native_verified separately.

## 1. Connected components

Input is canonical symmetric simple CSR over exactly 256 vertices:
- row_offsets: 257 U32 values, offset[0]=0, final offset=edge_count, monotone, degree <=255;
- neighbors: edge_count U32 words, canonical U8 endpoint values;
- each row is strictly increasing, has no self-loop, and has no duplicate endpoint;
- symmetry is a caller/runner digest-bound precondition; reciprocal edge presence is checked before dispatch.

The NaN16 routine `mth_graph_components_256` uses a caller-owned 256-word parent array and emits 256 deterministic representative labels. It unions each undirected edge once (j>i). Return is `r1=1` success and `r2=component_count`; malformed CSR returns `r1=0` before writing labels or scratch. Labels are the final union-find roots; their numeric value is an implementation-defined deterministic representative, not a semantic Head ID.

Native fixture oracles:
- path 0--1--2--3 with 252 isolated vertices: 253 components;
- disjoint edges (0--1) and (2--3), plus 252 isolates: 254 components;
- offset[0] != 0: reject and preserve output.

For symmetric nonnegative weighted graphs with strictly positive weights on every represented edge, component count equals the nullity of the weighted graph Laplacian. This component kernel alone does not compute eigenvalues or prove numerical nullity; that correspondence is a mathematical invariant to test with a separately verified spectral/nullspace fixture.

## 2. Energy ABI next

For weighted CSR v2, the exact energy is:

\[
E(x)=x^T L_w x=\sum_{\{i,j\}\in E}w_{ij}(x_i-x_j)^2\ge0.
\]

A separate bounded energy kernel is required. The initial energy ABI will constrain the Q16.16 input to [-1,+1], retain U8 weights [1,255], count each undirected edge once, and return an unsigned U64 Q32.32 scalar. The bound is:

\[
E_{raw}\le {256\choose2}\cdot255\cdot(2^{17})^2
=142,? 
\]

The exact integer bound must be recomputed and frozen before implementation; no energy source may be marked native_verified until this bound and all intermediate widths are proved. The energy kernel must preflight all inputs and return exact nonnegative integer arithmetic without rounding.

## 3. Required invariant fixtures before pair-space

1. Constant vector maps to exact zero under weighted L.
2. Component count matches the exact nullity on small fixtures with independently verified nullspace basis.
3. Energy equals the edge-sum oracle and is nonnegative.
4. Reciprocal weight mismatch, self-loop, duplicate, unsorted row, invalid endpoint and malformed offsets reject before output writes.
5. The graph digest binds symmetry, strict row order, weight equality, weight range and numeric ABI.

Pair-space action remains gated behind native weighted L, energy, component/nullity, and symmetry validation. Void potential, filters, Lanczos and wave evolution remain later gates.
