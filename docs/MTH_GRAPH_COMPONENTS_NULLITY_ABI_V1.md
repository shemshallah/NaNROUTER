# Connected components and Laplacian nullity ABI v1

Status: source-written; native verification pending.

For an undirected graph, the multiplicity of zero in its combinatorial Laplacian equals the number of connected components. This kernel independently computes components by synchronous minimum-label propagation.

Initialize label[v]=v and iterate:

\[
label_{next}(u)=\min\bigl(label(u),\{label(v):v\in N(u)\}\bigr).
\]

The minimum vertex ID in each connected component propagates at least one edge per round. A 256-vertex graph converges in at most 255 rounds. The number of final labels equal to their own vertex ID is the component count and therefore nullity(L).

## ABI

- 256 vertices; U32 word-addressed CSR offsets[257] and neighbors.
- r1=offsets, r2=neighbors, r3=edge_count (0..65,280).
- r4=labels_out[256], r5=labels_tmp[256], r6=component_count_out[1].
- r7=caller-owned 16-word scratch; r13=1.
- Return: 1 success, 0 invalid count, 2 invalid offsets, 3 invalid endpoint, 5 convergence bound exceeded.
- CSR symmetry, sorted unique rows, no self-loops, and graph digest are caller preconditions. Kernel checks offsets, degree bound, and endpoint encoding/range; it does not prove reciprocity.
- Input/output/workspace spans must not overlap. Labels and count are committed only after convergence.

This is a combinatorial component count, not a numerical eigenvalue solver and not an estimate of small nonzero eigenvalues.
