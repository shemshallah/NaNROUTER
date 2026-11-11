# Native hypertensor → simplicial → geometric global primitives, stage 1

Status: **native NaN16 mathematics verified by canonical guest CI**, not yet trained with or integrated into the 43M language decoder.

This is a deliberate replacement of the earlier provisional attention flow:
  streamed head vectors → third-order hypertensor → tri-state 2-simplex
  → local edge-Hodge features / one-scale simplicial spectral detail
  → Poincaré geometry-compatible similarity → attention softmax / global
  → recurrent attention feedback into the existing hybrid decoder.

The real **meta** layer belongs to Overbootstrap MC0 and is **not implemented by these kernels**. This PR makes no MC0 behavioral or authority changes.

## Kernel inventory (native `.nas` instructions, no new host arithmetic)

| Kernel | ABI | Mathematical purpose |
|---|---|---|
| `mth_hypertensor16_f32` | three x16 float32 head vectors -> 16x16x16 = 4096 tensor | streamed outer product, not a matrix and not merely a feature-wise triple dot |
| `mth_simplicial_motif3` | three tri-state edges, known-cold=0, hot=1, unknown=2 | distinguish 111, 2+ hot, 000, 2+ cold, partial/unknown |
| `mth_triangle_hodge3_f32` | three oriented edge flows -> gradient/curl/divergence (3+3+3) | exact local K3 one-form decomposition modulo float32 rounding; harmonic sector zero for filled isolated triangle |
| `mth_poincare_pair2_f32` | two 2D points norm<1 -> cosh(distance), 1/cosh(distance) | hyperbolic geometry score; not an acosh distance, logarithm map or directed parallel transport |
| `mth_simplicial_wavelet3_f32` | triangle vertex signal, bounded tau -> 3 smoothed + 3 detail | one stable explicit K3 diffusion scale / high-pass detail, not full multi-resolution spectral clustering |

Existing reusable NaN16 math: `mth_mirror_hodge_projection.nas` (complete graph), `mth_graph_dft256.nas` (periodic DFT, **not** arbitrary graph Fourier), `mth_sparse_weighted_graph_laplacian_v2.nas`, `mth_lanczos_256.nas`, `mth_vector_softmax256_f32.nas`, `mth_attention_head16_f32.nas`, `mth_attention_mask16_f32.nas`. Existing outputs remain separate until their native composition is implemented.

## Geometric and physical boundaries

The NaN16 physical 8 MiB canonical root stays unchanged: 256 fixed heads, 32,640 unordered pairs. The tensor is **ephemeral working memory** in guest-owned address space; do not try to pack 4096 float32 words into the canonical pair-record layout. A tensor feature T[i,j,k] has no unique canonical root address until an admitted versioned projection is defined. Every symmetric hyperbolic pair affinity must retain optional **separate directed lane data**—distance alone cannot reconstruct NaN16 lane direction or signed curl. Do not identify absent pair activity with negative evidence.

A hot or cold motif is a property of three valid observed pair states, not of a triangle's raw address. For Hodge, edge-flow sign must follow the explicit orientation A→B, B→C, C→A. Hodge curl on an isolated triangle is not global harmonic circulation. Global gradient and spectral measurements require composing local incidence into a consistent graph/complex and respecting unknown-edge masks.

## Global and attention future implementation (remaining)

1. Use authenticated stream descriptors to project sparse tensor features onto canonical triads and allowed nonlocal hyperedges. Bind all tensor consumers to a snapshot epoch and immutable three-head IDs.
2. Assemble sparse signed hot/cold simplicial incidence (B1, B2), with separate known/unknown masks and directed lane flows. Aggregate per-triad and per-head divergence/curl features; compare with the already-native complete-root Hodge path.
3. Build graph Fourier eigenbasis over a learned weighted graph (the current DFT kernel is **not** a substitute); develop spectral clustering/eigenvector sorting, multiscale graph/simplicial wavelets and diffusion across multiple triads.
4. Implement Poincaré embeddings learned from training targets; add exact/controlled acosh, log/exp map and orientation-aware sheet transport and geodesic hyperedge termination at tensor anchors. The present 2D monotone affinity is a real native building block, not an embedding learner.
5. Connect the resulting global hot/cold/gradient/curl features to bounded causal NaN16 attention softmax and its output into the frozen 43M decoder. Train Q/K/V, hypertensor contraction, attentional routing and output gates; prove nonzero gradient and language gain.
6. Defer genuine MC0/Overbootstrap meta semantics, training and global coordination to a separately authorized release.

## Acceptance tests

The included NaN16 guest fixture checks exact stream tensor entries and failure atomicity, 2/3 hot and cold/unknown classes, triangle Hodge identities, hyperbolic zero and nonzero distance affinities with unit-boundary rejection, and one-scale diffusion/wavelet outputs. The GitHub Actions workflow builds the pinned canonical NaN0S CLI, runs the assembled guest, and requires a unique PASS marker. This is a *unit-level mathematical package*, not an end-to-end trained model or measured Transformer parity.

## Verification update — November 10, 2026 (native PR #119)

All nine current fixtures assembled and executed in the pinned canonical NaN0S toolchain, with real guest arithmetic, in [GitHub Actions run #42945427159](https://github.com/shemshallah/NaNROUTER/actions/runs/42945427159).

| NaN16 fixture | Guest steps | Outcome |
|---|---:|---|
| Native streamed 16³ hypertensor, hot/cold motifs, Hodge, Poincaré and simplex wavelet | 109,701 | PASS |
| 16-candidate global masked attention and symmetric 16-node graph wavelet | 46,103 | PASS |
| Directional Poincaré-weighted sheaf restrictions, supplied-basis graph Fourier | 28,925 | PASS |
| Global hot/cold 16-triad reducer, spectral-cut readout | 2,886 | PASS |
| Connected Poincaré → sheaf → rank-3 tensor → motif/Hodge → global masked softmax → next-step head residual | 137,293 | PASS |
| Rank-3 tensor reverse-mode backward into A/B/C streams | 302,523 | PASS |
| Native diffusion-derived approximate Fiedler mode and two-cluster spectral partition | 211,773 | PASS |
| Native masked global softmax backward into candidate scores and value features | 13,710 | PASS |
| Global all-256-head B1 divergence plus oriented selected B2 face curl, canonical 32,640 pair flow input | 1,945,232 | PASS |
| **Total** | **2,798,146** | **9/9 PASS** |

### The 15 added NaN16 kernels

1. `mth_hypertensor16_f32.nas`: full rank-3 streamed tensor construction.
2. `mth_simplicial_motif3.nas`: tri-state complete/2-of-3 hot/cold masks.
3. `mth_triangle_hodge3_f32.nas`: oriented local gradient/curl/divergence.
4. `mth_poincare_pair2_f32.nas`: 2D disk cosh-distance and reciprocal affinity.
5. `mth_simplicial_wavelet3_f32.nas`: K3 heat-step spectral detail.
6. `mth_global_focus16_f32.nas`: native masked softmax over 16 triads.
7. `mth_graph_wavelet16_f32.nas`: weighted 16-vertex graph heat-scale/detail.
8. `mth_hyperbolic_sheaf16_f32.nas`: independently directed sheaf restriction discrepancy, gated by hyperbolic affinity.
9. `mth_graph_fourier16_f32.nas`: analysis/synthesis using caller-provided graph Laplacian eigenbasis.
10. `mth_global_motif_reduce16.nas`: 16-triad hot/cold/global counts, unknowns distinct.
11. `mth_spectral_cut16_f32.nas`: binary partition from caller-selected spectral mode.
12. `mth_hypertensor16_backward_f32.nas`: gradients into all streamed inputs from rank-3 upstream gradient.
13. `mth_fiedler16_f32.nas`: approximate Fiedler mode extracted **in the guest** from a real weighted graph using centered normalized diffusion (not a complete eigensolver or certified convergence).
14. `mth_global_focus16_backward_f32.nas`: gradients through 16-candidate softmax and values; canonical masked score zeros.
15. `mth_global_hodge256_f32.nas`: compute genuine B1 divergence on all 256 head vertices and B2^T oriented curl on up to 16 admitted triangle faces, directly from 32,640 canonical pair flows.

### What this does and does not prove

- Verified: native `.nas` mathematical execution, basic numeric oracles, reject atomicity, local and global 256-head gradient/curl incidence and hotspot operations, graph spectral scale, graph-based spectral cluster on a planted connected two-community graph, gradient availability at the **rank-3 tensor and global softmax seams**, and a **forward** global-to-next-head residual connection.
- Not yet verified: multi-chart NANNET deployment, canonical 8 MiB root writes/epoch transactions for these new kernels, an entire compiled trained head→trihead→global model, backpropagation through the Poincaré embedding and sheaf maps or the complete temporal attention loop, a global graph/simplicial multiscale Fourier/Hodge decomposition, a learned hyperbolic embedding of all 256 heads, and measurable language loss gain over the frozen 43M hybrid.
- The 256-head global Hodge kernel takes *canonical pair flows*, not a head-vector matrix; only explicitly admitted faces are treated as triangles. A 2-of-3 hot/cold candidate is not silently promoted to a filled simplex. The 16×16 relationship graph, directed 16×16 restriction maps and Laplacian eigenbasis are separate **mathematical operator descriptors**, NOT a matrix made from streamed vectors. The streamed head input is transformed directly into a 16×16×16 hypertensor; it does not become a vector-covariance matrix first.
- The Poincaré kernel returns a monotone reciprocal cosh-distance affinity, not exact geodesic coordinates or Riemannian parallel transport. The sheaf restriction operator is not a full geodesic sheet connection. The 3- and 16-node heat detail are single-scale rather than multiscale wavelet banks. Graph Fourier analysis accepts a supplied eigenbasis; the separate native Fiedler estimator computes an approximate *single* mode for a weighted graph.
- Real **META** is reserved to **Overbootstrap MC0** for a later release. The global attention feedback into the next head is not an implementation of MC0 meta or a claim of consciousness/understanding.

### Remaining integration priorities

1. Produce versioned canonical 256-head/tensor/simplicial mapping and enforce native admitted root write permissions and temporal snapshots, with true directed lanes and explicit unknown evidence.
2. Extend the now-verified 256-vertex B1 divergence plus selected 16-face B2^T curl into fully admitted weighted/sparse simplicial complexes, full edge Hodge gradient/curl/harmonic separation, and multiscale graph/simplicial spectral transforms on a learned graph.
3. Train Poincaré embeddings and hyperedge-to-hypertensor sheet connection, including hyperbolic gradient/parallel transport if tests show benefit.
4. Join tensor and global-attention backward with native Q/K/V, sheaf, spectral and head projections; plug resulting gated residual into the **existing** 43M model without retraining a separate model. Verify gradients from next-word cross-entropy and exact zero-gate identity regression.
5. Benchmark an entirely new document-held-out split against an equally trained small causal Transformer with comparable byte-level evaluation (bits per byte, exact word/OOV, context recall and generation). No transformer superiority claim until shown.
