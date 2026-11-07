# MTH Graph-Spectral Implementation Plan

Status: implementation contract and ordered kernel plan. The mathematical foundation is specified in NaNLMind/docs/GRAPH_SPECTRAL_FOUNDATION.md. This document translates it into MTH-native NaN16 work. No host-language math implementation is permitted.

## 1. Scope

MTH will become the numerical substrate for the Relational-Spectral Subsystem (RSS) shared by each 8 MiB universe-bin. It must expose graph, pair-space, spectral, potential, wave, and pattern-analysis kernels. NaNNet runners schedule and transport jobs; they do not reimplement mathematics. NaNLMind consumes validated outputs and retains the canonical semantic ledger.

## 2. Fixed mathematical contracts

### 2.1 K256 exact baseline

For the unweighted complete graph:
- A=J-I;
- D=255I;
- L=256I-J;
- Lx=256x-(Σ_i x_i)1;
- spectrum: 0 once and 256 with multiplicity 255.

This is the first native oracle. It tests the entire 256-vector path without requiring dense matrix storage.

### 2.2 General sparse graph

Given symmetric nonnegative edge weights A_ij:
- degree d_i=Σ_j A_ij;
- (Lx)_i=d_i x_i-Σ_j A_ij x_j;
- quadratic energy xᵀLx=(1/2)Σ_ij A_ij(x_i-x_j)²≥0.

The canonical directed relation rails remain untouched. The symmetric coupling is an explicit derived view with named policy and digest. A and L are not aliases for directed W.

### 2.3 Pair-space graph

For U indexed by ordered Head pairs:
- L_pair=L⊗I+I⊗L;
- matrix action: L_pair vec(U)=vec(LU+ULᵀ), with layout convention explicitly fixed;
- never materialize a 65,536×65,536 matrix.

### 2.4 Potential and wave

V_i=α/(r_i+ε)² with ε>0 and a versioned radius policy. The wave operator is H=c²L+V and the equation is ü+Hu=f. The sign convention, fixed-point scales and source bounds must be frozen before implementation.

## 3. Native MTH module inventory

Create modules under mth/nan16 and fixtures under mth/tests:

1. mth_rss_contract.nas — version, status codes, descriptor checks, safe bounds.
2. mth_graph_degree.nas — deterministic sparse degree accumulation.
3. mth_graph_laplacian.nas — sparse Lx and K256 baseline Lx.
4. mth_graph_pair.nas — matrix-free pair-space operator.
5. mth_graph_energy.nas — quadratic energy and nonnegative/overflow checks.
6. mth_graph_void.nas — radius lookup, ε guard, inverse-square fixed-point potential.
7. mth_graph_filter.nas — Chebyshev recurrence / polynomial filter.
8. mth_graph_lanczos.nas — deterministic symmetric Lanczos with bounded iterations and residual.
9. mth_graph_wave.nas — leapfrog/symplectic update and bounded DRIVE source.
10. mth_graph_fold.nas — verified transpose/centrosymmetry and even/odd block transforms.
11. mth_graph_pattern.nas — degree/motif/neighborhood/spectral signature primitives.

All mathematics above is implemented in NaN16 source. Host code is limited to transport, scheduling, file I/O, job validation, and test harness orchestration.

## 4. ABI and representation decisions required before kernel coding

- NaN16 register and memory ABI; caller-owned scratch frames only.
- Signed fixed-point representation for wave state and operator outputs.
- Q format per field, intermediate width, rounding and saturation policy.
- Sparse edge record format: endpoints, symmetric weight, flags, epoch, provenance ref.
- Matrix layout for pair-space U and its transpose.
- Input/output aliasing and overlap rules.
- Maximum edge count and scratch budget per runner.
- Status codes: success, invalid descriptor, bad topology digest, overflow, saturation, insufficient workspace, cancellation, nonconvergence, invalid symmetry.
- All writes preflighted when a failure must leave output unchanged.
- Every operator is deterministic for identical input pages, operator digest and version.

Do not select signedness or Q format implicitly from existing unsigned vector helpers. The graph-wave state requires signed values; this must be a separately documented ABI.

## 5. Runner and NaNNet integration contract

The NaNLMind runner protocol is NAN-RSS-1, defined in runner/relational_spectral.py. It validates envelopes only; it is not a math implementation.

Each runner publishes capability states:
- specified;
- source_written;
- native_verified.

Only native_verified kernels are dispatchable. Native verification requires the canonical NaN16 assembler/interpreter fixture, kernel digest, workspace limit, and version. A runner must reject unknown operator versions, stale cancellation epochs, mismatched topology/operator digests, insufficient workspace, and aliased input/output refs.

NaNNet transfers immutable/versioned page refs. It does not transmit dense matrix copies by default. Results carry output digest, residual/error bound, saturation count, iteration count, runner/kernel identity, and completion status. Semantic updates return through NaNLMind's existing validation and ledger path.

## 6. Six RSS operations

- ENCODE: preserve directed relation writes and provenance.
- QUERY: apply graph operator or project into a validated basis.
- MATCH: compare normalized spectral signatures; report metric and threshold.
- FILTER: apply g(H) through validated eigensystem or polynomial recurrence.
- DRIVE: bounded source injection with energy and ledger policy.
- FOLD: symmetry reduction only after exact invariant checks.

## 7. Pattern analysis

Pattern analysis is part of RSS's reusable API, not a separate model or semantic ledger. Native primitives should support:
- neighborhood fingerprints;
- directed motif counts;
- degree and shell profiles;
- connected components;
- local subgraph signatures;
- spectral signature extraction;
- epoch-to-epoch operator deltas;
- candidate matching and confidence metadata.

A spectral signature is lossy. It must point back to exact source relations and never replace provenance or semantic validation. A dedicated MC0 pattern-analysis application is deferred; it will consume the same MTH/RSS API later.

## 8. Test sequence and exact oracles

1. K256 degree: every Head has degree 255.
2. K256 Laplacian: all-ones vector maps to zero.
3. K256 basis: for any vector x with Σx_i=0, Lx=256x.
4. K256 spectrum: one zero mode, 255 modes at 256.
5. Sparse path graph: compare degree and Lx against hand-computed exact vectors.
6. Disconnected graph: nullity equals component count.
7. Product graph: compare matrix-free action against a small explicit Kronecker oracle.
8. Void: α=0 matches baseline; ε>0 bounds center; radius policy is deterministic.
9. Energy: xᵀLx is nonnegative within fixed-point error.
10. Wave: unforced/undamped energy drift stays within declared error.
11. Lanczos: eigenpair residual and orthogonality thresholds.
12. FOLD: exact centrosymmetric fixture reduces; one-cell perturbation rejects reduction.
13. Runner: only native_verified capabilities dispatch; digest, epoch and workspace failures reject.
14. NANNET: page refs round-trip, stale result rejected, output digest checked.
15. NaNLMind: read-only query and validated commit preserve the one global ledger.

## 9. Evidence policy

A .nas file is source-written, not verified. A fixture is source-written, not passed, until the canonical toolchain assembles and executes it. Python/C++ tests may validate descriptors, routing, or independent small reference expectations, but they cannot be reported as validation of NaN16 mathematical kernels.

Current gate: architecture specified. Existing MTH has checked U32 arithmetic, shifts, multiplication/division, and a raw U32 span-add primitive, but the native spectral ABI is not yet frozen. The immediate next step is to establish signed fixed-point/vector ABI and canonical assembler availability, then implement K256 degree/Lx before any eigensolver or void/wave kernel.
