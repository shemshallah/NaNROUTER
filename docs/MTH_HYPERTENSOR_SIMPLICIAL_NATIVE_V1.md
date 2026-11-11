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

## Verification update — 2026-11-10 (native PR #119)

All six current fixtures were **assembled and executed** with pinned canonical NaN0S toolchain in [GitHub Actions run #42943352111](https://github.com/shemshallah/NaNROUTER/actions/runs/42943352111):

| Fixture | NaN16 guest steps | Result |
|---|---:|---|
| Native hypertensor, motif, local Hodge, Poincaré and simplex wavelet | 109701 | PASS |
| Masked global focus plus symmetric 16-node graph wavelet | 46103 | PASS |
| Directed hyperbolic sheaf plus supplied-basis graph Fourier | 28925 | PASS |
| 16-triad hot/cold global counts plus spectral-cut readout | 2886 | PASS |
| Connected Poincaré → sheaf → hypertensor → hot motif/Hodge → focal softmax | 136226 | PASS |
| Reverse-mode gradient from 4096 tensor components into all three source vectors | 302523 | PASS |
| **Total** | **626364** | **6/6 PASS** |

No new Python or C++ mathematical opcode handler is involved. The current routines operate in the NaN16 guest with caller-owned scratch and make no modifications to the canonical 8 MiB root. The tensor is a full rank-3 16×16×16 outer product; its reverse-mode gradient is now implemented, but there is not yet a native trainable global softmax backward pass or a measured decrease in held-out text loss from this architecture.

Additional kernels introduced after the initial stage: `mth_global_focus16_f32`, `mth_graph_wavelet16_f32`, `mth_hyperbolic_sheaf16_f32`, `mth_graph_fourier16_f32`, `mth_global_motif_reduce16`, `mth_spectral_cut16_f32`, and `mth_hypertensor16_backward_f32`. Together with the initial five these make **12 new native NaN16 kernels**.

Spectral semantics: `mth_graph_fourier16_f32` projects using a caller-provided graph eigenbasis (eigenbasis generation/validation is not done in that kernel); `mth_spectral_cut16_f32` partitions from a supplied Fiedler mode (not an eigen-solver). The 3-node and 16-node heat-detail operators are single-scale wavelets, not yet a multiscale spectral bank. The Poincaré pair kernel computes `cosh(d)` and its inverse as an affinity; it is not an exact geodesic or tangent log map. The directed sheaf operator is linear restriction-map discrepancy, not Riemannian parallel transport. The local Hodge triangle has no harmonic 1-form; full-root Hodge remains a distinct existing kernel.

The genuine meta layer is **Overbootstrap MC0**, which is deliberately deferred. The native global attention readout is not labeled a trained meta layer.

Before claiming an end-to-end language-model improvement: build a native graph Laplacian eigenbasis for the actual learned graph (rather than injecting one), train global masked Q/K/V and the hypertensor projection with a causal next-token objective, connect to the frozen 43M decoder through a rollback-gated residual, and evaluate with independent document-level held-out bits per byte and exact-word metrics against a matched small Transformer. No improvement is asserted until those measurements exist.
