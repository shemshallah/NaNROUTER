# Weighted graph energy ABI v1

Status: source-written; native verification pending.

## Operator

For a canonical undirected weighted edge list:

\[
E(x)=\sum_{\{u,v\}\in E}w_{uv}(x_u-x_v)^2.
\]

This is computed directly from edge differences, independently of the sparse Laplacian output. It is therefore an independent positivity/energy oracle.

## ABI

| Field | Contract |
|---|---|
| Vertices | exactly 256 |
| Edge list | one record per undirected edge |
| edge_u, edge_v | U32 words with canonical U8 endpoint in low byte |
| Endpoint order | u < v |
| List order | strictly increasing lexicographic (u,v); no duplicates |
| Weight | U32 storage, low U8 in [1,255], upper bits zero |
| State | signed I32 Q16.16, raw range [-65536,+65536] |
| Output | unsigned I64 Q32.32, low U32 then high U32 |
| Maximum edges | 32,640 |
| Workspace | caller-owned 16-word U32 scratch |
| Rounding | none |
| Input/output aliasing | prohibited |

The edge list is the canonical undirected representation. It does not contain reciprocal CSR entries, so reciprocal-weight disagreement is unrepresentable at this kernel boundary. Any CSR-to-edge-list adapter must first validate that every directed entry has exactly one reciprocal entry with the same weight; the adapter is not part of this kernel.

## Exact range proof

The state bound gives |x_u-x_v| <= 2^17 raw Q16.16 units. Thus:

- squared difference <= 2^34;
- weighted edge contribution <= 255*2^34 < 2^42;
- total over at most 32,640 edges < 2^57.

The total therefore fits unsigned I64 exactly. Since each state is Q16.16, the squared quantity is Q32.32; the output is the raw sum with no rounding, saturation, or wrap.

## Native entry point

`mth_graph_energy_weighted_q16_16_u64_v1`

Inputs: r1=edge_u, r2=edge_v, r3=weights, r4=x, r5=output, r6=edge_count, r7=caller-owned 16-word scratch, r13=1.

Returns: 1 success, 0 invalid count/state, 2 invalid/noncanonical endpoint list, 3 invalid weight encoding. Validation is complete before output writes.

## Fixture gates

1. Weighted path with weights [2,3,5] and state [0,1,4,9] is not within this ABI's [-1,+1] bound; scale the state by 1/9 or use a separate exact oracle.
2. Two-edge fixture u-v with state [0,1/2,1] and weights [2,3] has exact raw energy 2*(1/2)^2 + 3*(1/2)^2 = 5/4; expected Q32.32 output is 5*2^30.
3. Constant state produces zero energy.
4. Invalid endpoint order, duplicate edge, zero/high-bit weight and out-of-range state preserve output.
