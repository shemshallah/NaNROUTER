# MTH / NaN: Foundations and Game Plan for the 256-Mode Standing-Wave Architecture

**Status:** Research and engineering plan. Mathematical identities, hypotheses, and experiments are distinguished throughout.

## 1. Purpose and principles

This plan defines a testable computational architecture around a 256-state relational system, spectral propagation, an annular central-void potential, and a tensor-product extension. It does not assume that a wave equation automatically produces intelligence, creativity, or physical quantum behavior. Those are hypotheses to test.

Principles:
1. Separate mathematical state space, storage encoding, and network address.
2. Preserve directed relationships; derive symmetric operators only where justified.
3. Treat the void as an explicit geometry/potential construction.
4. Distinguish a 256-dimensional eigensystem from a 65,536-dimensional product space.
5. Keep numeric computation separate from NaN payload encoding.
6. Build a reference implementation and validate it before optimization or LM integration.

## 2. Count and define the objects

| Object | Size | Meaning |
|---|---:|---|
| Base states | 256 | Computational states / heads |
| Unordered off-diagonal pairs | 32,640 | Edges in complete undirected graph K256 |
| Directed off-diagonal relations | 65,280 | Ordered pairs with distinct endpoints |
| Self-relations | 256 | Diagonal entries |
| Relation matrix | 256 × 256 = 65,536 cells | One coefficient per ordered pair |
| Ordinary eigensystem | 256 eigenpairs | Eigenvalues/eigenvectors of a 256 × 256 operator |
| Tensor-product basis | 65,536 modes | Joint indices from two 256-state spaces |

A 256 × 256 matrix has 65,536 coefficients but only 256 eigenvalues/eigenvectors in its ordinary eigendecomposition. The 65,536 modes belong to a 256 ⊗ 256 product space.

For a directed relation matrix W, preserve directionality and optionally derive:
`W_s=(W+W^T)/2`, `W_a=(W-W^T)/2`.
Then `W=W_s+W_a`; the symmetric part can define an undirected energy operator, while the antisymmetric part remains available for directional transport or separate analysis.

For the unweighted complete graph:
`L=256I-J`,
where J is the all-ones matrix. Its spectrum is 0 (multiplicity 1) and 256 (multiplicity 255). This degenerate baseline demonstrates that useful differentiated modes require nonuniform weights, geometry, potential, or boundary conditions.

## 3. Geometry and central void

A graph has no intrinsic center, radius, angle, or boundary. Those require an explicit embedding and must remain separate from storage identifiers.

Candidate embeddings:
- **Single circular ring:** simple angular coordinates, but constant radius means an inverse-square radial potential is constant and creates no radial differentiation.
- **Annulus:** multiple radial shells and angular positions; recommended first experiment.
- **Disk / hyperbolic disk:** useful later for non-Euclidean distance and boundary concentration, but harder to validate.
- **Learned embedding:** defer until fixed geometries have been tested.

For the first prototype, assign each state polar coordinates `(r_i, theta_i)` with `r_min <= r_i <= r_max`. The void is the excluded region `r < r_min`. A computational radial penalty may be:
`V_ii = alpha / (r_i + epsilon)^2`,
with alpha >= 0 and epsilon > 0. This is a design analogue, not a claim that a physical singularity has been recreated.

## 4. Graph Laplacian and wave dynamics

Start with a nonnegative symmetric adjacency A:
`D_ii = sum_j A_ij`, `L = D - A`.
For any real x:
`x^T L x = (1/2) sum_(i,j) A_ij (x_i-x_j)^2 >= 0`.
Thus L is positive semidefinite.

Basic graph wave:
`u_ddot + c^2 L u = 0`.
With potential and input:
`u_ddot + H u = B f(t)`, where `H=c^2 L+V`.
Here u(t) is the 256-state displacement, B maps input channels, and f(t) is the drive. A readout is `y=Cu`. Optional damping:
`u_ddot + 2 gamma u_dot + H u = B f(t)`.

For symmetric positive-semidefinite H:
`H phi_k = lambda_k phi_k`.
Modal frequencies are `omega_k=sqrt(lambda_k)` when H includes all scale factors. The time-domain solver must be checked against modal reconstruction. In the undamped/unforced case, verify energy conservation; with positive damping and no input, verify energy does not grow. Select time steps using the integrator's stability constraints, not visual inspection.

## 5. What the inverse-square term means

In physical central-force problems, angular momentum contributes a centrifugal term proportional in 3D to:
`hbar^2 l(l+1)/(2 mu r^2)`,
and in 2D to:
`hbar^2 m^2/(2 mu r^2)`.
It penalizes nonzero angular-momentum modes near small radius. It does not attract modes to the outer boundary or guarantee a ring antinode.

In the computational model, V is an analogous radial penalty. Normalize units consistently with c²L, or declare the system dimensionless and sweep alpha. Measure:
- energy by radial shell;
- angular power spectrum;
- energy fraction in a predefined boundary band;
- localization / participation ratio;
- eigenvalue gaps and degeneracies;
- sensitivity to alpha, shell spacing, graph weights, and boundary conditions.

Define metrics before experiments. A boundary ring is an observed result only if the measurements support it.

## 6. Barrier coupling and tunneling analogy

Partition states into inner and outer regions:
`H(eta) = [[H_in, eta C], [eta C^T, H_out]]`,
where 0 <= eta <= 1 controls cross-region coupling. Inject a known signal into one region and measure energy received by the other:
`T = E_received / E_injected`.

This is a computational tunneling analogue, not automatically quantum tunneling. In LM experiments, ask whether weak cross-region coupling enables useful associations missed by disconnected/local baselines. Measure task accuracy, retrieval precision, novelty, contradiction rate, and latency. Do not equate unusual output with creativity.

## 7. Spectral relation operator

Let `M in C^(256x256)` encode pairwise strength and phase:
`M_mn = A_mn exp(i phi_mn)`.
For a Hermitian operator require `M=M†`; then `M=P Lambda P†`. For real symmetric matrices use an orthogonal decomposition. For genuinely directed or non-normal operators, do not force a Hermitian eigendecomposition; use SVD or an appropriate non-Hermitian method while preserving directionality.

Spectral coordinates:
`z=P†x`, reconstruction `x=Pz`.
Spectral filter:
`x'=P g(Lambda) P† x`.
The response g can implement low-, high-, or band-pass filtering, or learned gating. Compare it with graph diffusion, normalized adjacency propagation, and ordinary attention.

Low-rank approximation:
`M approximately U_r Sigma_r V_r†`.
Select rank based on reconstruction error and downstream task results.

## 8. Foundational operations

Expose a small, auditable API:
1. **ENCODE:** map typed input/context into the 256-state representation, retaining provenance.
2. **DRIVE:** inject an impulse or time-varying signal through Bf(t).
3. **PROPAGATE:** advance the damped/undamped dynamics by a specified interval.
4. **PROJECT:** transform state into spectral coordinates.
5. **FILTER / MATCH:** apply a defined spectral response or compare against stored patterns.
6. **DECODE:** map state/readout into typed outputs with confidence and provenance.

Record operator version, embedding version, parameters, precision, normalization, and seed for reproducibility.

## 9. Symmetry, folding, and fast paths

These properties are distinct and must be detected independently.

### 9.1 Centrosymmetry

Let J reverse the 256 coordinates: J_ij=1 when i+j=255. Then J²=I. M is centrosymmetric when:
`J M J = M`, equivalently `MJ=JM`.
The reversal eigenspaces have dimension 128 each, with basis vectors:
`q_i+ = (e_i+e_(255-i))/sqrt(2)`,
`q_i- = (e_i-e_(255-i))/sqrt(2)`.
In this basis:
`Q^T M Q = diag(M_plus, M_minus)`.
A dense eigensolve can become two 128 × 128 solves. Leading cubic work is approximately 2(128³), one quarter of 256³, before overhead. This is valid only if the operator actually has the symmetry. A potential must preserve it too, e.g. V_i=V_(255-i).

### 9.2 Bit reversal and transpose

An address convention such as:
`addr(a,b)=(a<<8) | rev8(b)`
is a storage mapping. A transpose-related pairing does not prove centrosymmetry, matrix symmetry, or physical reflection symmetry. Test each independently.

### 9.3 Circulant structure

A circulant matrix has `M_ij=f((i-j) mod 256)` and is diagonalized by the DFT. Symmetric ring couplings can provide a circulant baseline. Circulant, symmetric, and centrosymmetric are not interchangeable.

### 9.4 Fast-path policy

At operator creation/update, measure symmetry/Hermitian residual, centrosymmetry residual, circulant residual, sparsity, bandwidth, rank estimate, and PSD status where required. Select an optimized path only when preconditions pass a documented tolerance. Keep a general reference implementation.

## 10. The 65,536-dimensional product-wave system

Let two base spaces each have dimension 256:
`H = H_x tensor H_y`, with dimension 65,536.
If `L_x phi_m=lambda_m^x phi_m` and `L_y psi_n=lambda_n^y psi_n`, then:
`L_prod = L_x tensor I + I tensor L_y`.
Product eigenvectors are `phi_m tensor psi_n`; eigenvalues are `lambda_m^x+lambda_n^y`.

A product wave equation:
`U_ddot + (c_x² L_x tensor I + c_y² I tensor L_y + V_joint) U = F(t)`.
A separable potential is `V_x tensor I + I tensor V_y`. More expressive interactions can use:
`K = sum_(k=1)^r B_k tensor C_k`.

Do not allocate an unrestricted dense 65,536 × 65,536 matrix (>4.29 billion entries). Use matrix-free Kronecker application, separable operators, sparse coupling, low-rank decompositions, and blockwise updates. Declare memory and compute budgets before increasing rank/state count. Give each product axis a stable semantic meaning, such as context-position × concept-state or query-feature × memory-feature.

## 11. Standing-wave expansion and mode accounting

A two-coordinate standing-wave expansion is:
`U(x,y,t)=sum_mn A_mn psi_m(x) psi_n(y) cos(omega_mn t + phi_mn)`.
With separable operators, omega_mn follows from sums of component eigenvalues (plus separable potentials). Joint coupling requires solving or approximating the coupled product operator.

There may be 65,536 product coefficients when both indices span 0..255. This does not mean all modes are independent, equally useful, or need dense storage. Use sparse activation, thresholding, low-rank factorization, or adaptive mode selection only after validation.

## 12. Language-model integration hypotheses

Treat these as experiments, not established capabilities.

- **Context propagation:** encode selected token/context features, drive the operator, and read out propagated context. Compare against no module, graph message passing, adjacency diffusion, parameter-matched MLP, and ordinary attention.
- **Associative memory:** store key/value traces as typed state patterns or low-rank spectral records. Test exact/semantic retrieval, collisions, updates, and forgetting; include adversarial near-neighbor keys.
- **Multi-path reasoning:** represent alternative hypotheses as separate drives/channels. Measure answer accuracy and calibrated uncertainty, not just candidate count.
- **Contradiction/interference:** competing patterns may flag conflicts, but interference is not a truth oracle. Preserve evidence and source provenance.
- **Controlled novelty:** sweep eta and compare associations with disconnected baselines. Score relevance, novelty, factuality, and repeatability separately.
- **Dynamic attention / generation:** a possible bounded residual is `h_combined=h_base+beta C u`. Begin with a frozen base model and small beta. Train end-to-end only after ablations show contribution.

## 13. External propagation and network layer

The external “noosphere” / mesh belongs in a network layer, not inside the wave equation. Nodes should serialize typed records; authenticate peers; authorize resource access; attach provenance/version/integrity metadata; route independently of internal geometry; enforce quotas, timeouts, and message-size limits; and treat remote results as untrusted until validated.

Atomic-time synchronization can order distributed events but does not make independent simulations phase-coherent. If phase synchronization is needed, define clock model, drift bounds, synchronization protocol, and failure behavior. Measure network delay/jitter separately from internal propagation time.

## 14. Numeric representation and NaN encoding boundary

NaN payloads can store tags/metadata, but IEEE NaNs are not ordinary arithmetic operands. Arithmetic may propagate or canonicalize NaNs and alter payloads.

Use a strict boundary:
1. Decode the NaN-encoded word into a typed internal representation.
2. Validate tag, type, width, and payload.
3. Convert numeric fields into supported numeric formats.
4. Perform arithmetic on ordinary numeric values.
5. Encode results back into the tagged representation.

Use FP64 as a reference, FP32 where adequate, and fixed-point/quantized formats only after error analysis. Represent complex values as explicit real/imaginary pairs or a documented complex type. Specify NaN-native bit layouts, tag allocation, payload widths, endianness, validity rules, and unknown-tag behavior. Endian conversion must be explicit and reversible; never infer semantic byte order from host architecture.

## 15. Reference implementation architecture

**A — Topology and embedding**
- 256 stable state IDs;
- sparse weighted adjacency;
- annular coordinates and shell membership;
- explicit state-ID ↔ storage-address mapping.

**B — Operators**
- symmetric graph Laplacian;
- directed relations retained separately;
- diagonal void potential;
- block/low-rank coupling;
- property checks for symmetry, centrosymmetry, circulant structure, and PSD.

**C — Spectral solver**
- dense symmetric 256-state reference solver;
- appropriate path for directed/non-Hermitian experiments;
- eigenpair residual and orthogonality checks;
- optional 128+128 centrosymmetric and FFT circulant paths.

**D — Dynamics**
- impulse/continuous drive;
- damped/undamped integration;
- energy accounting;
- deterministic seeds and parameter snapshots.

**E — Product space**
- matrix-free Kronecker application;
- separable potentials;
- low-rank cross-coupling;
- memory-bounded tiled execution.

**F — LM adapter**
- typed encode/decode;
- input projection/readout;
- bounded auxiliary residual;
- logging and ablation controls.

Keep a clear reference implementation after optimized paths are added. Compare every optimized kernel against deterministic fixtures.

## 16. Initial data structures

Conceptual schema, not a fixed binary ABI:

```text
Topology256
    state_count: 256
    state_ids[256]
    coordinates[256]          // r, theta, or chosen embedding
    shell_id[256]
    adjacency                 // sparse weighted graph
    directed_relations        // optional, preserved independently

WaveOperator
    laplacian                 // symmetric PSD operator
    potential[256]            // diagonal values
    coupling_blocks           // optional sparse/low-rank terms
    damping
    scale_parameters
    property_flags            // verified symmetry/centrosymmetry/circulant

SpectralModel
    eigenvalues[256]
    eigenvectors[256,256]     // optional dense reference storage
    solver_kind
    residual_norm
    operator_version

WaveState
    displacement[256]
    velocity[256]
    time
    energy
    drive_state

ProductWaveState
    dimensions: 256 x 256
    coefficients              // sparse, tiled, or low-rank
    factorization_metadata
    active_mode_set

ExperimentRecord
    seed
    topology_version
    operator_parameters
    numeric_precision
    integrator_and_step
    input_output_hashes
    metrics
    result_status
```

Production structures need explicit integer widths, alignment, ownership, bounds checks, and serialization rules. Avoid duplicate derived matrices unless measured performance justifies them. Tie eigensystem cache invalidation to operator version so stale eigenvectors cannot be applied after topology changes.

## 17. Validation plan and acceptance gates

**Stage 1 — Mathematical fixtures**
- Verify K256 counts.
- Verify Laplacian symmetry and row sums.
- Verify xᵀLx >= 0 on random vectors.
- Verify complete-graph spectrum: 0 once, 256 with multiplicity 255.
- Verify eigenpair residuals and orthogonality.

**Stage 2 — Geometry and void**
- Verify annular coordinates and shell counts.
- Verify potential finiteness and formula.
- Compare alpha=0 with increasing alpha.
- Report radial energy and boundary-band metrics.
- Test sensitivity to embedding and shell resolution.

**Stage 3 — Dynamics**
- Verify undamped/unforced energy conservation within tolerance.
- Verify damped energy does not grow without input.
- Compare integration with modal reconstruction.
- Test stability across time steps and operator scales.

**Stage 4 — Structural optimizations**
- Compare 128+128 fold with full solution for verified centrosymmetric cases.
- Compare FFT and direct multiplication for verified circulant cases.
- Confirm nonconforming matrices fall back to general path.
- Benchmark speed, memory, and numerical error.

**Stage 5 — Product space**
- Compare matrix-free Kronecker operations with small explicit toy matrices.
- Verify product eigenpairs for separable operators.
- Measure memory scaling and low-rank approximation error.
- Reject configurations exceeding resource budgets.

**Stage 6 — LM utility**
- Freeze base model initially.
- Use held-out data and fixed prompts.
- Compare with parameter/compute-matched baselines.
- Report accuracy, retrieval precision/recall, calibration, contradiction rate, latency, memory, and failures.
- Ablate void potential, phase, damping, coupling, filtering, and product-space paths.
- Require reproducible improvement before enabling by default.

## 18. Risks and failure modes

- **Degenerate baseline:** complete graph alone has a simple spectrum.
- **Geometry over-interpretation:** embedding is a model choice, not proof of physical geometry.
- **False ring claims:** inverse-square penalties do not guarantee boundary localization.
- **Mode confusion:** 65,536 product coefficients are not 65,536 eigenvalues of a 256 × 256 matrix.
- **Invalid fast paths:** bit reversal does not imply centrosymmetry; test preconditions.
- **Numerical instability:** poor integration steps or scaling can create artificial growth.
- **Dense product blow-up:** never materialize the full 65,536-square operator without a compelling bounded use case.
- **NaN arithmetic hazards:** payload encodings must be decoded before numeric operations.
- **Unproven LM benefit:** novelty or visually interesting waves are not evidence of better reasoning.
- **Network conflation:** distributed clocks and transport do not automatically synchronize internal phase.

## 19. Immediate build sequence

1. Implement the 256-state topology and annular embedding.
2. Implement sparse A, L, V, and the general reference H operator.
3. Add dense 256-state eigensolve and eigenpair validation.
4. Add a stable damped wave integrator and energy metrics.
5. Add deterministic impulse experiments and radial/angular diagnostics.
6. Add centrosymmetry and circulant detectors, then their guarded fast paths.
7. Add matrix-free product-space operators and low-rank coupling.
8. Build an LM adapter behind a feature flag and run matched ablations.
9. Only after measured benefit, optimize memory layout and NaN-native instruction/data encoding.

## 20. Research claims ledger

Use explicit labels in all reports:

- **Established identity:** follows directly from definitions or standard linear algebra (e.g. K256 counts, Laplacian PSD, tensor-product dimension).
- **Verified implementation fact:** supported by tests and reproducible measurements.
- **Hypothesis:** plausible application awaiting experiment (e.g. weak coupling improves associative novelty).
- **Open question:** needs mathematical or empirical resolution.
- **Rejected / unsupported claim:** contradicted by derivation or not supported by evidence.

The architecture succeeds only if its mathematical invariants hold, its implementation matches the reference, and its downstream LM experiments outperform meaningful baselines. The central void, spectral structure, and product-wave modes are tools to investigate—not conclusions to assume.


## Product-space implementation update — tiled pair action

The general dense pair action now has a source-written NaN16 tile kernel:
`Y = LU + UL^T`, one 16×16 output tile per invocation. It stages U plus
two 16-row windows of L, rather than materializing the 65,536×65,536
Kronecker matrix. The bounded K16 L=2I fixture passed canonical NaN16 CI run 242 (283,436 guest
steps) using 1,542 NaN16 words. The full-U tile reference remains useful for
mathematical comparison and requires 73,990 words (591,920 bytes); it fits the new 1 MiB MTH guest budget but not a 512 KiB runner
guest ceiling. The K16 kernel is the dispatchable path; page-window
orchestration remains open. This is not a claim that all 65,536 product
modes are independently controllable.
