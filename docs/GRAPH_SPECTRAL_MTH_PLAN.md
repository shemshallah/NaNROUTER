# MTH Graph-Spectral Implementation Plan

Status: implementation contract and ordered kernel plan. The research-level source of truth is [game_plan_foundations.md](game_plan_foundations.md); the system-level translation is NaNLMind/docs/GRAPH_SPECTRAL_FOUNDATION.md. This document translates those foundations into MTH-native NaN16 work. No host-language math implementation is permitted.

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

The first geometry experiment follows `docs/game_plan_foundations.md`: a versioned annular embedding with explicit radial shells and angular positions, excluding r<r_min as the central void. A graph has no intrinsic radius; graph-distance or topology-shell radii remain alternate, separately versioned experiments. V_i=α/(r_i²+ε²) with ε>0. This is the canonical formula implemented by `mth_graph_void.nas`; it is not the `(r+ε)²` variant. The wave operator is H=c²L+V and the equation is ü+Hu=f. The sign convention, fixed-point scales and source bounds must be frozen before implementation.

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

## 6. Six RSS operations and the foundation API

The runner-facing RSS verbs are:

- ENCODE: preserve directed relation writes and provenance.
- QUERY: apply graph operator or project into a validated basis.
- MATCH: compare normalized spectral signatures; report metric and threshold.
- FILTER: apply g(H) through validated eigensystem or polynomial recurrence.
- DRIVE: bounded source injection with energy and ledger policy.
- FOLD: symmetry reduction only after exact invariant checks.

The research foundation's computational API names lower-level stages as ENCODE, DRIVE, PROPAGATE, PROJECT, FILTER/MATCH, and DECODE. These are compatible layers, not competing verb lists: PROPAGATE is the native wave-step primitive called by QUERY/DRIVE workflows; PROJECT is a basis transform used by QUERY/MATCH/FILTER; DECODE is the typed readout/consumer boundary; FOLD is a guarded optimization. Preserve this mapping in runner schemas and avoid adding duplicate top-level operations for internal primitives.

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

Current gate: the K256 U16-input Laplacian is native_verified by the canonical
NaN16 toolchain. Existing MTH also has checked U32 arithmetic, shifts,
multiplication/division, and a raw U32 span-add primitive. The signed
fixed-point ABI for wave/void/filter kernels remains unfrozen. The next
implementation step is a sparse weighted-graph Lx kernel with explicit
symmetric-edge input and a small exact path-graph oracle; do not jump to
Lanczos or wave evolution yet.


## 10. First native kernel: K256 Laplacian over U16 payloads

A first exact integer kernel is now source-written in
`mth/nan16/mth_k256_laplacian.nas`, with fixture
`mth/tests/mth_k256_laplacian_test.nas`.

For K256, the matrix-free identity is:

```
(Lx)[i] = 256*x[i] - sum(x)
```

The first ABI deliberately avoids prematurely choosing the signed Q format
for wave evolution. It accepts 256 unsigned 16-bit integer payloads and
writes 256 signed two's-complement 32-bit results. Since
`0 <= sum(x) <= 256*65535`, every output is bounded by
±16,776,960; the kernel is exact with no rounding or saturation. It checks
all inputs before writing, so an out-of-range payload leaves output
unchanged. Input and output spans must not overlap.

The fixture checks the impulse oracle `[1,0,...,0] -> [255,-1,...,-1]`
and invalid-input atomicity. A new GitHub Actions workflow checks out the
canonical NaN0S source assembler and execution harness, assembles this
fixture, and runs it. The workflow passed on 2026-11-07 (run #9): the canonical source assembler
assembled the fixture, and the NaN0S execution harness produced
`MTH K256 LAPLACIAN PASS` after 5,391 guest steps (rc=3/HALT). The kernel
is therefore **native_verified** for this exact U16-input K256 operator.

This does not yet establish the signed fixed-point ABI for graph waves,
void potentials or spectral iteration. It is a narrow exact K256 baseline
that can be executed before those wider contracts are frozen.


## 11. Sparse graph Laplacian v1 implementation update

The signed fixed-point ABI is now frozen in `docs/MTH_SPARSE_GRAPH_ABI.md`. The first sparse native slice is intentionally an exact unweighted symmetric simple-graph CSR operator with Q16.16/I32 input and output. The input state is bounded to [-64,+64], so each edge difference is bounded by 2^23 raw units and a maximum-degree-255 row sum remains below signed-I32 overflow. No rounding or saturation is used.

Source: `mth/nan16/mth_sparse_graph_laplacian.nas`. Fixtures: `mth/tests/mth_sparse_graph_laplacian_test.nas` (path graph, disconnected graph, and invalid-input atomicity). The fixture has been added to the canonical NaN16 CI workflow. Its evidence status is now **native_verified**: canonical NaN16 CI run #58 assembled and executed the path, disconnected, and invalid-input atomicity fixtures successfully (20,737 guest steps). Kernel SHA-256: `013048435c1026643554fb20e3434934cf059dd47cf2857577cac13ed5be6b8f`. The NaNLMind capability can be promoted only with this exact digest, Q format, and workspace contract. Weighted CSR is a separately versioned follow-on, not an implicit extension of this ABI.


## 12. Weighted sparse CSR v2 native verification

The first weighted operator is now implemented in `mth/nan16/mth_sparse_weighted_graph_laplacian_v2.nas` with ABI `docs/MTH_WEIGHTED_CSR_ABI_V2.md`. It accepts Q16.16/I32 state in [-64,+64], U8 integer edge weights 1..255, and emits signed I64 Q16.16 outputs. The 16-word caller scratch frame and register ABI are explicit. Per-edge products fit signed I32; each row is accumulated exactly in signed I64 under the proved <2^40 bound.

Canonical NaN16 CI run #107 assembled and executed two weighted path oracles (weights [2,3,5] and [1,7,2]) plus zero-weight rejection/output atomicity successfully: 41,253 guest steps, expected HALT. Kernel SHA-256: `8958bf432cd4052576d9b950d9e50c1853bc96d90bc3c50680bf9013ab36d613`.

This verifies the exact U8 integer-weight v2 operator only. Fractional weights, weighted energy, connected components/nullity, pair-space, void potential, spectral filters, Lanczos, and wave evolution remain unverified. Next gate is independent graph energy and component/nullity kernels with symmetry/reciprocal-weight validation fixtures.

## 13. Ring / void / NANNET implementation update (2026-11-06)

The deep plan (`docs/game_plan_deep.md`) and ledger (`docs/IMPLEMENTATION_TODO.md`) now have a first native slice. All evidence below is local canonical `nan_cli` execution unless explicitly marked as prior CI.

| Kernel | File | Status |
|---|---|---|
| K255 head-only Laplacian | `mth/nan16/mth_k255_laplacian.nas` | local PASS |
| C255 head-ring Laplacian | `mth/nan16/mth_ring255_laplacian.nas` | local PASS |
| 255+1 port assembly | `mth/nan16/mth_ring255_port.nas` | local PASS |
| Weighted graph energy | `mth/nan16/mth_graph_energy_weighted_u8_q32_32.nas` | local PASS |
| Connected components | `mth/nan16/mth_graph_components_256.nas` | local PASS |
| Fold/unfold vectors | `mth/nan16/mth_graph_fold.nas` | local PASS |
| Void potential | `mth/nan16/mth_graph_void.nas` | local PASS |
| Wave velocity-Verlet step | `mth/nan16/mth_graph_wave.nas` | local PASS |
| Step energy metric | `mth/nan16/mth_graph_step_energy_256.nas` | local PASS |
| Harmonic wave energy | `mth/nan16/mth_harmonic_accel_256.nas` + fixture | local PASS |
| 128×128 matvec | `mth/nan16/mth_matvec128_f32.nas` | local PASS |
| 128×128 centrosymmetry | `mth/nan16/mth_centrosymmetry_128.nas` | local PASS |
| 256-cosine match | `mth/nan16/mth_cosine256_f32.nas` | local PASS |
| Damped harmonic energy | `mth/nan16/mth_harmonic_accel_256.nas` + fixture | local PASS |
| C256 ring Laplacian | `mth/nan16/mth_ring256_laplacian.nas` | local PASS |
| C256 graph-H energy | `mth/nan16/mth_ring256_laplacian.nas` + fixture | local PASS |
| 255-point DFT | `mth/nan16/mth_graph_dft255.nas` | local PASS |
| 128×128 power iteration | `mth/nan16/mth_power_iter128.nas` | local PASS |
| Rank-1 low-rank add | `mth/nan16/mth_lowrank_add_128.nas` | local PASS |
| 128 adapter residual | `mth/nan16/mth_adapter_residual_128.nas` | local PASS |
| Dense 128×128 pair action | `mth/nan16/mth_graph_pair.nas` | local PASS |
| Rank-1 128 pair action | `mth/nan16/mth_graph_pair_rank1_128.nas` | local PASS |
| 256-point DFT reference | `mth/nan16/mth_graph_dft256.nas` | local PASS |
| Two-region coupling | `mth/nan16/mth_graph_couple_128.nas` | local PASS |
| Transmission metric | `mth/nan16/mth_graph_transmission_128.nas` | local PASS |
| Float32 dot/norm/axpy | `mth/nan16/mth_dot256_f32.nas`, `mth_norm256_f32.nas`, `mth_axpy256_f32.nas` | local PASS |

The 255+1 ring/page descriptor is `spec/ring-255.json`, generated by `tools/gen_ring_csr.py`. The storage/control plane is `runner_riddle/wave_store.py` with BS0DB/MC0DB schemas and 12 tests. The capability manifest is `spec/wave-capabilities.json`; `tools/register_wave_capabilities.py` registers 95 kernels into MC0DB.

Local gate:

```
python3 tools/run_mth_fixtures.py
93 runner fixture paths registered; 92 unique manifest fixtures
K256 pair-space, normalize, prefix-sum, xorshift64, and universe-map targeted set: 5/5 PASS

python3 -m unittest discover -s tests -q
Ran 1217 tests
OK (skipped=16)
```

The expanded workflow passed canonical run `42405649076` (132 steps, 61 fixtures); there is no page-size limit, and the 2 MiB guest budget is adjustable. The 256-tile page-window/atomic-publication orchestrator, stable top-k, and point-0 HTTP ingress are implemented; a native full 256-tile grid loop, live NANNET deployment, and real LM ablations remain open gates (Lanczos and the one-tile K16 driver are now local PASS).


## K256 closed-form pair-space v1 — native verified

Kernel: `mth/nan16/mth_k256_pair_space_v1.nas`; ABI: `docs/MTH_K256_PAIR_SPACE_ABI_V1.md`; fixture: `mth/tests/mth_k256_pair_space_v1_test.nas`.

For the exact K256 baseline `L=256I-J`, the kernel applies `L_pair(U)=LU+UL^T=512U-colsum(U)-rowsum(U)` with two 256-word work vectors and three linear passes over the 65,536-cell U matrix. It does not materialize the 65,536×65,536 Kronecker matrix. Q16.16 input is bounded to ±2^20 raw, giving a proved signed-I32 output bound of ±2^30.

Canonical NaN16 CI workflow run 180 passed the assembler and runtime fixture. The fixture checks the exact E00 response (510 at [0,0], −1 at [0,1] and [1,0], zero at [1,1]) and row/column sums of 1.

Scope boundary: this verifies the K256 closed-form special case only. It does not establish generic sparse-CSR pair-space support for arbitrary L.

## 14. General dense pair-space tiled action v1

A general dense real-matrix action is now native_verified for the stated tile ABI as
`mth/nan16/mth_graph_pair_tile16_f32.nas`, with ABI
`docs/MTH_GRAPH_PAIR_TILE16_ABI_V1.md` and fixture
`mth/tests/mth_graph_pair_tile16_f32_test.nas`.

For each 16×16 output tile, the kernel computes
`Y[i,j] = sum_k L[i,k]U[k,j] + sum_k U[i,k]L[j,k]`.
It stages the full 256×256 U matrix and two 16×256 row windows of L.
The full-U reference uses 73,990 NaN16 words (591,920 bytes). It is rejected by 512 KiB runners and admitted by the default 1 MiB MTH guest budget (131,072 words). The full 65,536×65,536 Kronecker operator is never formed.

The two sums use separate accumulators and increasing-k order, with an
explicit final FADD. The caller supplies row windows from one immutable L
digest and invokes 256 tiles to complete Y. The L=2I fixture checks every cell in two tiles against Y=4U, at global origins (0,0) and (16,32).

**Evidence status: NATIVE_VERIFIED for two tile origins.** Canonical NaN16 CI run
218 assembled and executed the L=2I fixture (4,643,414 guest steps); all 256 output cells matched Y=4U at both tile origins (0,0) and (16,32). This does not yet verify full 256-tile paged orchestration, cancellation, cross-tile publication atomicity, or a
generic sparse-CSR pair action.


## 15. Bounded K16 streaming pair action v1

Native NaN16 kernel: mth/nan16/mth_graph_pair_tile16_k16_f32.nas.
ABI: docs/MTH_GRAPH_PAIR_TILE16_K16_ABI_V1.md.
Fixture: mth/tests/mth_graph_pair_tile16_k16_f32_test.nas.

Each call stages four 16×16 blocks and updates two independent 16×16
partial sums. K slices are processed in increasing order, then finalized.
Workspace is 1,542 NaN16 words (12,336 bytes), below the 65,536-word guest
ceiling. Canonical CI run 242 passed the two-slice L=2I oracle in 283,436
guest steps. Full 16-slice orchestration, page retrieval, and atomic
publication remain open. The full-U tile reference is over budget.
