# GAME PLAN — Ring, Void, NANNET

## A NaN16-native synthesis of MTH, graph-spectral foundations, and the 255-head standing wave

**Status:** research and engineering plan; not an implementation and not a claim that the gates below already pass.  
**Canonical source language:** NaN16, assembled by `nasm0`, executed by `n16i` or the native NaN16 kernel.  
**Canonical arithmetic home:** MTH inside the one NaNLMind universe.  
**Canonical routing home:** NaNROUTER.  
**Related plans:** `docs/GAME_PLAN_MTH.md`, `docs/game_plan_foundations.md`.

**Implementation ledger:** `docs/IMPLEMENTATION_TODO.md`.

**Evidence ledger:** `docs/R10_IMPLEMENTATION_EVIDENCE.md`.

This document does not create a second universe, a second runner ring, a second task ledger, or a second owner of state. It is a synthesis: it takes the mathematical substrate from MTH, the graph-spectral research foundations, and the proposed void/ring architecture, and turns them into one coherent NaN16-native design with explicit claims, interfaces, memory budgets, and gates. The NANNET node is the only network endpoint per universe; the old noosphere/JAHS language is preserved only as a non-normative easter egg at the end.

---

## 0. How to read this plan

Every statement in this plan belongs to one of five evidence classes:

| Label | Meaning |
|---|---|
| **Established identity** | Follows from definitions or standard linear algebra. |
| **Verified implementation fact** | Supported by a native NaN16 fixture, digest, and recorded run. |
| **Hypothesis** | Plausible and testable, but not yet supported by measurement. |
| **Open question** | Requires a mathematical or empirical decision. |
| **Rejected / unsupported** | Contradicted by derivation, or not supported by evidence. |

A plan is not an implementation. A `.nas` file is source-written, not verified. A passing fixture is not a universal proof. A visually interesting wave is not evidence of intelligence, creativity, or consciousness.

The design also keeps four namespaces separate at all times:

1. **Local head indices** — 0 through 255 inside one universe.
2. **Mathematical mode indices** — angular, radial, or product indices; they may also run 0 through 255 but are not head identities.
3. **Node points** — 1 through 255 in the overbootstrap/NANNET namespace.
4. **Wire identities and object selectors** — BSR0 through BSR5, vector and hyperedge selectors, and route objects.

The same number can appear in all four namespaces. It never means the same thing in all four. Every operation in this plan must name which namespace it is using.

### 0.1 The 255 + 1 convention: 255 heads, one NANNET node, 256 ring positions

This plan is set up for **255 local heads** in each universe and **exactly one NANNET node** per universe.

The NANNET node is **not a head**. It is the universe's single network endpoint and boundary port. The mathematical ring has **256 positions**:

```
256 ring positions = 255 head positions + 1 NANNET port position
```

This convention preserves the binary 256-point transform and the 256×256 ring operator while satisfying the 255-head constraint. It does not smuggle a 256th trainable head into the system.

| Object | Count | Namespace | Writable by wave learning? |
|---|---:|---|---|
| Local heads | 255 | Head indices `0..254` | Only within the learning ACL. |
| BSR control heads | 6 | Local heads `0,4,5,6,7,8` | No. |
| Learning heads | 249 | The other local heads | Yes, within candidate bins/ACL. |
| NANNET node | 1 | Network node identity, not a head | No; port/transport only. |
| Ring positions | 256 | Mathematical/readout positions | Head positions only; the port is not a head. |

The default allocation is six BSR control heads plus 249 learning heads. If the authority insists on 250 learning heads, then the control allocation must be re-signed; this plan does not silently release a reserved head. The NANNET node remains outside the head count.

The matrix convention is equally explicit:

| Matrix | Shape | Meaning |
|---|---:|---|
| `H_ring` | 256×256 | Full ring-position operator, including the NANNET port row/column. |
| `H_heads` | 255×255 | Head-only submatrix; the trainable/writable wave operator. |
| `M_wave` | 256×256 | Ring-position aperture/coefficient matrix. |
| `M_heads` | 255×255 | Head-only aperture; the authorization-safe subspace. |
| Product ring state | 256×256 | 65,536 ring-position coefficients. |
| Product head state | 255×255 | 65,025 head-only coefficients. |

The difference between the ring product space and the head product space is 511 coefficients (`256² - 255² = 511`). Those are the NANNET port's coupling modes. They are not extra heads.

The 255-head block has 255 eigenpairs. The full 256-position ring has 256. The 256×256 figure in the original standing-wave formulation is preserved as the ring-position operator; the head-only operator is 255×255.

The ring readout has 256 samples: 255 head samples plus one NANNET port sample. The 256-point FFT is the primary aperture transform. The 255-point DFT is the head-only reference. The port sample is a boundary value, not a trainable vertex.

The fold is also adapted:

- the 255-head block is odd; reversal has one fixed middle vertex and blocks of 127 and 128;
- the full 256-position ring has two 128 blocks only if the port is placed and treated symmetrically;
- for authorization, fold the 255-head block, never the port into a head.

This is the setup the rest of the plan uses. If the intended reading is 255 total positions rather than 255 heads plus one node, that is a different version and must not be mixed with this one.

---

## 1. The synthesis in one page

The architecture is:

> **A 255-head angular readout ring plus one NANNET node, coupled to a hidden radial void spectrum, represented by a 256×256 ring-position aperture matrix, evolved by a graph-spectral wave operator, executed entirely in NaN16, and read out through a guarded spectral API into the universe’s single authenticated NANNET endpoint.**

The three named boundaries are:

| Name | Mathematical role | What it is not |
|---|---|---|
| **The Void** | An inner boundary and a mode-dependent radial potential; an excluded core, not a stored state. | Not a hole full of hidden data; not a physical singularity. |
| **The Ring of Power** | A 256-position readout annulus (255 head positions + 1 NANNET port) where radial modes are sampled and where coherent energy may concentrate. | Not a guarantee that every mode has a maximum there; not a license to overwrite reserved heads or the port. |
| **The NANNET node** | The universe’s single external network endpoint/port; it receives and emits signed spectral records. | Not a head; not a region of the wave equation; not a phase-coherent extension of the internal field. |

The three principal matrices are:

| Symbol | Shape | Role |
|---|---|---|
| `H_wave` | 256×256 ring positions; 255×255 head-only | The wave operator: graph Laplacian plus void/core potential. Its eigenpairs give spatial modes and frequencies. |
| `M_wave` | 256×256 ring positions; 255×255 head-only | The cross-modal aperture/coefficient matrix: radial modes to angular ring samples, or a general cross-modal coupling. Its SVD gives principal coupling patterns. |
| `U_wave` | 256×256 ring-position coefficients, matrix-free | The product-space field state. It has 65,536 ring coefficients (65,025 head-only), not 65,536 eigenvalues of `M_wave`. |

The new wave equation is not “the old equation plus a magic term.” It is the standard graph/continuum wave equation with three additions:

1. A **core boundary** at `r_core`, excluding the singular centre.
2. A **centrifugal renormalization** in each angular sector, so the void acts differently on each angular momentum.
3. An optional **outer port** that models escape through the NANNET port without pretending the network is part of the wave equation.

In its cleanest form:

```
ü + 2γu̇ + H_wave u = B f(t)
H_wave = c² L + V_core + V_angular
```

In an angular Fourier sector `m`:

```
ü_m + 2γu̇_m + [ c² L_rad + V_core(r) + (1 + β) c² m² / r² ] u_m = B_m f_m(t)
```

The coefficient `β` is the void amplification of the already-existing centrifugal barrier. If `β = 0`, the `m²/r²` term is simply the angular part of the Laplacian in polar coordinates. If `β > 0`, the void strengthens the barrier. If `β < 0`, the barrier is weakened and the model enters the critical/attractive regime, which requires a separate self-adjoint boundary condition and must not be enabled by default.

The Void therefore acts as a **mode separator**:

- low angular momentum penetrates closer to the centre;
- high angular momentum turns around farther out;
- the Ring of Power is the turning-point band where the radial modes are sampled;
- the outer region is where high-`m` content dominates and where the NANNET port is placed;
- the NANNET node receives a readout, not the wave itself.

The six utilization verbs are linear-algebra operations on the aperture, plus one propagation primitive and one evidence primitive:

| Verb | Linear-algebra meaning |
|---|---|
| `ENCODE` | Forward model: typed input to aperture/mode coefficients. |
| `QUERY` | Analysis/projection: state to spectral coordinates. |
| `MATCH` | Comparison of normalized spectral signatures. |
| `FILTER` | Diagonal shaping in a validated eigen/SVD basis. |
| `DRIVE` | Inverse/control: desired ring pattern to bounded mode injection. |
| `FOLD` | Guarded symmetry reduction; two 128×128 problems when the certificate passes. |
| `PROPAGATE` | Internal wave step used by `QUERY`/`DRIVE`. |
| `DECODE` | Typed readout with confidence and provenance. |
| `TRACE` | Evidence record for every execution. |

Everything mathematical is NaN16. The host may launch, transport, schedule, compare bytes, and enforce ACLs. The host may not compute eigenvalues, trigonometric functions, matrix products, or expected mathematical results on behalf of the guest.

---

## 2. Mode accounting: the five objects

The single most important discipline in this plan is **mode accounting**. The numbers 256 and 65,536 appear in several different objects. They are not interchangeable.

### 2.1 The five objects

| Object | Count | What it is | What it is not |
|---|---:|---|---|
| Local heads | 255 | State/address identities `0..254` inside one universe. | Not nodes, not modes, not eigenvalues. |
| NANNET node | 1 per universe | The single network endpoint/port. | Not a head; not trainable; not a mode. |
| Ring positions | 256 | 255 head positions + 1 NANNET port position. | Not 256 trainable heads. |
| Angular modes | 256 | Fourier modes of the ring, `m = 0..255`. | Not 256 spatial blobs; not 256 independent heads. |
| Radial modes | 256 (target) | Hidden bulk basis functions `R_k(r)`. | Not additional heads; not network points. |
| `M_wave` coefficients | 65,536 ring; 65,025 head-only | The 256×256 ring-position aperture/coefficient matrix. | Not 65,536 eigenvalues. |
| `U_wave` coefficients | 65,536 ring; 65,025 head-only | Product-state coefficients in a 256⊗256 ring basis. | Not a dense 65,536×65,536 matrix. |
| Product eigenpairs | 65,536 ring; 65,025 head-only | Eigenpairs of a separable product operator. | Not the eigenpairs of a 256×256 matrix. |
| Network point namespace | 255 | Overbootstrap/NANNET endpoints 1..255. | Not local head indices. |
| BSR control heads | 6 | Reserved local heads `0,4,5,6,7,8`. | Not wave vertices that may be overwritten. |

### 2.2 Four different 256s

1. **255 local heads + 1 NANNET node** occupy **256 ring positions**.
2. **256 ring positions** are the boundary readout lattice.
3. **256 angular modes** are the Fourier basis of the ring.
4. **256 radial modes** are the hidden bulk basis, if the full product space is instantiated.

A 256×256 matrix has 256 rows and 256 columns, but its eigen/singular decomposition has at most 256 patterns. The 65,536 product modes arise only when two 256-dimensional spaces are tensored.

### 2.3 Two different 65,536s

- **65,536 coefficients** in a 256×256 matrix or state. This is a storage count.
- **65,536 eigenpairs** of a product operator such as `L_x ⊗ I + I ⊗ L_y`, when both factors are 256-dimensional and separable. This is a spectral count.

The first does not imply the second. A 256×256 matrix has 256 eigenpairs, not 65,536. The 65,536 product modes belong to the tensor-product space.

### 2.4 The rule

> **Never say “the eigenvalues” without naming the operator.**

There are at least four spectra in this architecture:

| Spectrum | Operator | Count | Meaning |
|---|---|---:|---|
| Spatial/wave spectrum | `H_wave` | 256 per angular block, or 65,536 in the full product | Frequencies and spatial modes. |
| Aperture spectrum | `M_wave` | At most 256 singular values; 256 eigenvalues only if square and normal | Cross-modal coupling strengths. |
| Product spectrum | `H_x ⊗ I + I ⊗ H_y` | 65,536 if separable | Joint angular/radial frequencies. |
| Ring readout spectrum | 256-point Fourier transform of the ring field | 256 frequency bins | Observable angular content. |

The “principal oscillation strengths” of the user’s formulation belong to the wave operator, not automatically to the coefficient matrix. The coefficient matrix’s singular values describe how strongly modes are coupled or correlated, not how fast they oscillate.

---

## 3. Geometry: the three rings

### 3.1 Why geometry must be explicit

A graph has no intrinsic centre, radius, angle, or boundary. The moment we speak of a void, a ring, or an outer region, we have chosen an embedding. That embedding is a model decision, not a property of the storage identifiers. It must be versioned, inspected, and tested independently of the address atlas.

The first rule is therefore:

> **State index ≠ geometric position ≠ network address.**

A head can be mapped to an annulus coordinate, but the head ID does not become a radius. A node point can be mapped to a port, but the point number does not become an angle.

### 3.2 Three candidate geometries

| Geometry | Description | Strength | Cost / risk |
|---|---|---|---|
| **G1 — Ring-255 plus NANNET port plus radial basis** | 255 head positions on one angular ring, one NANNET port position, and a hidden 1D radial basis evaluated at the ring. | Faithful to the 255-head ring and the 256-position aperture. Exact angular Fourier structure. | Requires a radial basis and a hybrid graph/continuum model. |
| **G2 — Annulus 16×16** | 256 ring positions (255 head states + 1 NANNET port) on a 16-shell × 16-angle polar lattice. | Fully graph-native; exact sparse Laplacian; block structure by angular mode; easy native fixtures. | Only 16 angular samples; “256 maxima” becomes a virtual readout. |
| **G3 — Hybrid 16×16 plus 256-sample ring** | G2 for computation, 256-position interpolation for readout. | Practical first prototype; preserves the 255-head + port readout vision. | Two representations; interpolation must be validated. |

**Recommendation:** build **G2** first as the native prototype, then lift to **G1** for the full ring-255 plus NANNET port plus radial-mode model. G3 is the bridge: it lets the 256-position ring readout be tested before the full 256×256 ring aperture exists.

### 3.3 The three zones

Every geometry in this plan has three zones:

| Zone | Range | Mathematical role | Implementation |
|---|---|---|---|
| **Core / Void** | `r < r_core` | Excluded; no state stored; singular centre avoided. | Inner boundary condition at `r_core`. |
| **Barrier / Ring** | `r_core ≤ r ≤ r_ring` | Evanescent or turning-point region for selected modes; energy may concentrate. | Radial modes, potential, ring readout at `r_ring`. |
| **Outer / Port** | `r > r_ring` | Propagating/escaping content; NANNET port. | Open boundary, sponge layer, or port impedance. |

The “void” is not a third graph. It is the inner boundary of the same annulus. The “ring” is not a separate system. It is the readout surface of the same field. The NANNET node is not an outer graph. It is the universe’s single network port outside the mathematical domain.

### 3.4 The ring readout

The ring field at radius `r_ring` can be written as:

```
U(r_ring, θ, t) = Σ_m c_m(t) e^{i m θ}
c_m(t) = Σ_k A_{m k} R_k(r_ring) e^{i φ_{m k}} e^{-i ω_{m k} t}
```

where `m` is the angular mode, `k` is the radial mode, `R_k` is the radial basis function, and `A_{m k}` is the cross-modal coefficient. The ring intensity is:

```
I(θ, t) = |U(r_ring, θ, t)|²
```

The vertex amplitude at angle `θ_i = 2π i / 256` is:

```
A_ring(i, t) = sqrt(I(θ_i, t))
```

This is the corrected form of the user’s ring amplitude. The index `i` is the vertex; `m` is the angular mode; `k` is the radial mode. They are three different indices. The original expression `A_in` mixed them.

Two regimes must be distinguished:

- **Coherent ring:** the modes add with a stable phase; interference produces bright antinodes. This is the “Ring of Power” regime.
- **Incoherent ring:** the time-averaged intensity is the sum of mode powers; no stable antinodes. The ring is diffuse.

A useful coherence metric is:

```
R_ring = |Σ_m c_m e^{i m θ}| / Σ_m |c_m|
```

`R_ring ≈ 1` means phase-locked; `R_ring ≈ 0` means diffuse. The Ring of Power is a measured high-coherence, high-energy-concentration regime, not an assumption.

### 3.5 The 256-maxima problem

A real bandlimited field on 256 equally spaced samples can resolve angular modes up to `m = 128` (the Nyquist limit). A real standing wave `cos(mθ)` has `m` maxima. Therefore:

- 256 **vertices** are a sampling lattice, not 256 guaranteed maxima.
- A real field on 256 samples has at most **128** maxima for a single bandlimited standing wave.
- 256 maxima would require a complex analytic field with content beyond the real Nyquist limit, an interleaved double ring, or a non-bandlimited construction.

This is not a rejection of the vision. It is a precise choice:

> **Use 256 ring positions (255 heads + 1 NANNET port) as the readout lattice. Treat the number of antinodes as a measured metric. If 256 antinodes are required, use a complex envelope or a dual-ring construction and document the interpretation.**

The “Ring of Power” can still be a bright, coherent ring. It does not need to promise a specific antinode count.

### 3.6 The outer port

A closed outer boundary reflects waves. A wave does not “escape through the NANNET port” merely because the domain ends. Escape requires one of:

- an absorbing boundary or sponge layer;
- a radiation/port boundary condition;
- a finite external network model with delays and losses.

The first implementation should use a **closed cavity** for exact energy tests. The NANNET port is added later as a controlled leakage boundary. The network itself remains a separate layer.

---

## 4. The void operator, correctly stated

### 4.1 The centrifugal term is already in the Laplacian

In polar coordinates, the Laplacian contains the angular term. For a mode `e^{i m θ}` in two dimensions:

```
-Δ = -∂²_r - (1/r)∂_r + m²/r²
```

The `m²/r²` term is the standard centrifugal barrier. It is not an extra potential; it is the angular part of the kinetic operator after separation.

If the proposed void potential is:

```
V_void(r) = λ / r²
```

then adding it to the Laplacian gives an effective radial coefficient:

```
(1 + β) m² / r²
```

where `β` is the ratio of the added coefficient to the Laplacian’s angular coefficient. In dimensionless units, `β` is the design knob. In physical units, it is the ratio of `λ` to the kinetic angular coefficient.

This gives three interpretations:

| Interpretation | Statement | Consequence |
|---|---|---|
| **Renormalization** | The void amplifies or weakens the existing centrifugal barrier. | Net coefficient `(1+β)m²/r²`; clean and separable. |
| **Extra potential** | The void is an independent `1/r²` potential added to the Laplacian. | Same net coefficient, but the declaration must say it is additional. |
| **Core boundary** | The void is an excluded region with a boundary condition; the `1/r²` term is only the standard centrifugal term. | No double counting; the core boundary creates the mode-independent barrier. |

The first implementation should use **core boundary plus renormalization**: the core boundary handles the excluded region, and `β` tunes the centrifugal barrier. The scalar `1/r²` potential is regularized as `α/(r² + ε²)` or `α/(r + ε)²`; the singular point `r = 0` is never evaluated.

### 4.2 The mode-independent core barrier

The centrifugal term is zero for `m = 0`. Therefore the `m = 0` mode is not repelled by the angular barrier. If the design wants a void that repels all modes, including `m = 0`, it needs a **core potential** `V_core(r)` with a positive coefficient, or a Dirichlet boundary at `r_core`.

The full effective potential is therefore:

```
V_eff(r; m) = V_core(r) + (1 + β) c² m² / r²
```

The two parts have different jobs:

- `V_core` creates a mode-independent core barrier and regularizes the centre.
- `(1+β)m²/r²` creates the angular-momentum-dependent barrier.

The user’s `λ = ℏ² l(l+1) / 2μ` is the standard centrifugal coefficient for angular momentum `l`. It is zero for `l = 0`. It does not, by itself, make the centre forbidden for the `l = 0` mode. The core boundary or `V_core` does that.

### 4.3 What the potential actually does

The corrected statement is:

- The centrifugal barrier **repels high-`m` modes from the centre more strongly**.
- The low-`m` modes, especially `m = 0`, penetrate closest to the centre.
- The high-`m` modes are therefore enriched in the outer annulus.
- This is a **mode separation** effect, not a literal attractive force toward the boundary.
- The barrier radius is mode- and frequency-dependent: each mode has its own turning point.

The statement “repels low-angular-momentum modes from the centre” is backwards for the centrifugal term. The core potential or boundary can repel low-`m` modes, but the centrifugal term is weakest at low `m`.

### 4.4 The inner boundary condition

The core boundary is a design choice, not a numerical afterthought.

| Condition | Meaning | Use |
|---|---|---|
| **Dirichlet** `ψ(r_core) = 0` | Hard, impenetrable void. | First exact cavity; energy tests. |
| **Robin** `∂_r ψ + κ ψ = 0` at `r_core` | Soft void; tunable leakage. | Tunneling/creativity experiments. |
| **Neumann** `∂_r ψ = 0` | No flux; isolated core. | Rarely physical; reference only. |
| **Regularity** `ψ ~ r^{|m|}` near `r = 0` | Analytic continuation; no core boundary. | Only when the singular potential is regularized and the domain includes the centre. |

The first implementation should use Dirichlet at `r_core` for exact energy conservation. Robin is the controlled knob for the tunneling hypothesis.

### 4.5 Sign and criticality

The safe first regime is:

```
V_core ≥ 0, β ≥ 0
```

A positive inverse-square term is repulsive. A negative term is attractive and can become critical. In the reduced 2D radial equation, the critical coefficient is `-1/4`; beyond it, the operator requires a self-adjoint extension and the “fall to the centre” problem appears. Do not enable negative coefficients by default. Sweep positive `α` and `β` first.

### 4.6 The block structure

If the annulus is rotationally symmetric and the void is centred, the angular Fourier basis diagonalizes the angular part. The wave operator becomes block diagonal:

```
H_wave = blockdiag(H_0, H_1, ..., H_255)
```

where each `H_m` is a radial operator of size `n_r × n_r`. The blocks are coupled only if the symmetry is broken by:

- an off-centre void;
- a nonuniform ring;
- a non-circular outer boundary;
- a defect or port that breaks rotational symmetry;
- a cross-modal coupling term.

This is the central computational gift of the design:

> **A centred void turns the 2D problem into 256 independent 1D radial problems.**

The “256×256” structure is then not a dense eigensolve; it is 256 radial blocks. The full cross-modal matrix appears only when symmetry is broken.

---

## 5. Wave dynamics and the 256×256 space

### 5.1 The equation

The damped, driven wave equation is:

```
ü + 2γu̇ + H_wave u = B f(t)
H_wave = c² L + V_core + V_angular
```

For a symmetric positive-semidefinite `H_wave`, the eigenpairs satisfy:

```
H_wave φ_k = λ_k φ_k
ω_k = sqrt(λ_k)
```

The free, undamped solution is:

```
u(t) = Σ_k φ_k [ a_k cos(ω_k t) + (b_k / ω_k) sin(ω_k t) ]
```

The energy is:

```
E = 1/2 ||u̇||² + 1/2 uᵀ H_wave u
```

With damping and no input, energy must not grow. With no damping and no input, energy must be conserved within the declared numerical tolerance.

### 5.2 The standing-wave expansion

The user’s expansion:

```
U(x, y, t) = Σ_mn A_mn ψ_m(x) ψ_n(y) cos(ω_mn t + φ_mn)
```

is valid as a **modal expansion** when:

1. the operator is separable in the chosen coordinates;
2. `ψ_m` and `ψ_n` are eigenfunctions of the separated operators;
3. `ω_mn` are the corresponding eigenfrequencies;
4. `A_mn` and `φ_mn` are the initial modal coefficients and phases.

In an annulus, the natural product is radial × angular:

```
U(r, θ, t) = Σ_{m k} A_{m k} R_k(r) e^{i m θ} cos(ω_{m k} t + φ_{m k}) + c.c.
```

The product is not `x × y`; it is `radial × angular`. The 256×256 matrix `M_wave` is the coefficient matrix in this basis. It is a **state representation**, not the operator that determines the frequencies.

If the system is not separable — off-centre void, nonuniform ring, cross-coupling — the simple product form no longer holds. Use the eigenbasis of the full `H_wave`, or a numerical solver, and do not pretend the modes are products.

### 5.3 The product space

For two 256-dimensional spaces:

```
H_prod = H_x ⊗ I + I ⊗ H_y
```

If `H_x φ_m = λ_m φ_m` and `H_y ψ_n = μ_n ψ_n`, then:

```
H_prod (φ_m ⊗ ψ_n) = (λ_m + μ_n)(φ_m ⊗ ψ_n)
```

There are 65,536 product eigenpairs when both factors are 256-dimensional. They are not the 256 eigenpairs of a single 256×256 matrix.

A cross-coupling term can be written as a low-rank sum:

```
K = Σ_{r=1}^R B_r ⊗ C_r
```

The rank `R`, memory, and per-step cost are declared before execution. Never materialize a dense 65,536×65,536 operator. That is 4,294,967,296 entries; even at one byte per entry it is four gigabytes, and at float32 it is sixteen gigabytes. The guest has 512 KiB of working memory. The product operator is applied matrix-free, blockwise, or low-rank.

### 5.4 The 65,536 modes are not 65,536 independent controls

A 256×256 matrix has rank at most 256. It cannot independently address 65,536 product coefficients. The 65,536 coefficients are the state; the operator’s rank and the aperture’s rank determine how many independent patterns are controllable or observable.

This distinction matters for the user’s “ENCODE: use A_mn as a 256×256 encoding matrix for data”:

- As a 256×256 encoding matrix, `M_wave` acts on 256-dimensional vectors.
- To act on the full product state, use `M_wave ⊗ I` or `I ⊗ M_wave`, which is matrix-free and blockwise.
- The number of independent encoded patterns is bounded by the rank of the aperture, not by 65,536.

### 5.5 Time stepping and stability

For explicit leapfrog or velocity Verlet, the step must satisfy a Courant-Friedrichs-Lewy-type bound:

```
Δt ≤ 2 / sqrt(λ_max)
```

where `λ_max` is the largest eigenvalue of `H_wave` (including the potential). Use a Gershgorin bound or a validated Lanczos estimate; do not guess. For the K256 ring-position Laplacian, `λ_max = 256` in the unweighted complete-graph baseline; for the K255 head-only baseline, `λ_max = 255`. With the void potential, `λ_max` is larger; compute it.

The first dynamics implementation should be:

- closed cavity, Dirichlet core, no outer port;
- undamped, unforced energy conservation;
- damped, unforced energy decrease;
- impulse response compared against modal reconstruction;
- deterministic step count and seed;
- explicit status on instability or nonconvergence.

Only after these pass should the open port and the NANNET node be added.

### 5.6 Precision lanes

| Lane | Use | Risks |
|---|---|---|
| **Exact integer / Q16.16** | Topology, indices, counts, graph weights, Laplacian, fold equality. | Limited range; overflow; scale choice. |
| **Float32** | Trigonometric functions, Jacobi rotations, wave state, spectral estimates. | Rounding, residual growth, loss of symmetry. |
| **Complex pair** | Phases and Hermitian operators. | Double memory; phase convention errors. |
| **Pair-float / compensated** | Residual-critical dot products and orthogonality checks. | Extra cost; more code. |

Exact and approximate results must never be silently mixed. Every kernel declares its lane, rounding, error bound, and exceptional-value policy.

---

## 6. The aperture matrix `M_wave`

### 6.1 What `M_wave` is

The user’s `M_wave[m][n] = A_mn` is best interpreted as a **cross-modal aperture/coefficient matrix**:

- rows: angular modes or ring samples;
- columns: radial modes or source modes;
- entries: complex amplitudes `A_mn = a_mn e^{i φ_mn}`;
- role: map hidden radial modes to observable ring patterns, or encode a 256-dimensional input into a 256-dimensional mode space.

It is not automatically the wave operator. It is not automatically Hermitian. It is not automatically the state.

### 6.2 Roles determine the decomposition

Before choosing an eigendecomposition, name the role:

| Role of `M_wave` | Equation | Correct decomposition |
|---|---|---|
| **State coefficients** | `U = Σ A_mn R_n e^{imθ}` | SVD for correlation/compression; eigenvalues only if square and normal. |
| **Linear filter/encoder** | `y = M x` | SVD; singular values are gains. |
| **Coupling operator** | `ü + (H - M)u = 0` | Eigendecomposition if normal; otherwise Schur/SVD. |
| **Associative memory** | `y = M x` with stored patterns | SVD/eigendecomposition; rank controls capacity. |
| **Scattering/port matrix** | `out = M in` | SVD; unitarity/contraction tests, not Hermiticity. |
| **Covariance/color matrix** | `C = M M†` | Hermitian PSD; eigendecomposition for colored noise. |

The same matrix can play different roles in different verbs. The role must be declared in the operation record.

### 6.3 Decomposition decision tree

```
Is M square and normal?
  yes -> eigendecomposition M = P Λ P†
  no  -> SVD M = U Σ V†
Is M Hermitian?
  yes -> P unitary, real eigenvalues
  no  -> eigenvalues may be complex; use Schur or SVD
Is M real symmetric?
  yes -> orthogonal P, real eigenvalues
  no  -> general path
```

For a general matrix, `P†` is not the inverse. The dual basis is:

- `M⁻¹` if square and invertible;
- `M†` if unitary/Hermitian;
- `(M† M)⁻¹ M†` if full column rank;
- `V_r Σ_r⁻¹ U_r†` if rank-deficient (truncated SVD);
- left/right eigenvectors and a condition-number warning if non-normal.

This is the correct meaning of “P and P†.” The user’s dual basis is exact only in the unitary/Hermitian case.

### 6.4 Observability and reachability

The aperture has a control-theoretic interpretation:

- **Observable subspace:** the row space of `M_wave`; the ring can see only these patterns.
- **Reachable subspace:** the column space of `M_wave`; the drive can excite only these patterns.
- **Null space:** hidden bulk modes that do not appear at the ring.
- **Rank:** the number of independent observable/reachable patterns.
- **Condition number:** how noise amplifies in inversion.

This gives the six verbs a precise meaning:

- `QUERY` can recover only the observable subspace.
- `DRIVE` can control only the reachable subspace.
- `MATCH` should compare signatures in the observable subspace.
- `FILTER` should not amplify null-space noise.
- `FOLD` must preserve the observable subspace.
- `ENCODE` should not waste energy on unreachable modes.

### 6.5 Capacity is not 65,536 bits

The 256×256 matrix has 65,536 coefficients, but capacity is limited by:

- rank;
- precision and noise;
- symmetry constraints (symmetric, Hermitian, centrosymmetric);
- quantization;
- error-correction overhead;
- the observable subspace.

A full-rank 256×256 float32 matrix has 65,536 real coefficients, but that is not 65,536 independent bits. The usable capacity is an empirical quantity: measure bit error rate versus signal-to-noise ratio, rank, and quantization. Do not claim capacity from the coefficient count alone.

### 6.6 `M_wave` as a colored-noise generator

The user’s “spectrally colored noise” can be defined precisely. If `C = M M†` is a covariance matrix, then:

- eigendecompose `C = P Λ P†`;
- generate white noise `z` with a seeded PRNG;
- color it as `n = P sqrt(Λ) z`;
- the resulting field has covariance `C`.

This is deterministic, inspectable, and NaN16-native. The color is the spectral profile; the seed is explicit; no host randomness is allowed.

### 6.7 The fold, precisely

Centrosymmetry is:

```
J M J = M
```

where `J` reverses the 256 coordinates: `J_ij = 1` when `i + j = 255`.

The condition is **not** `M_{m,255-m}` alone. That is an anti-diagonal/persymmetric condition. The full condition relates all four corners:

```
M_{i,j} = M_{255-i,255-j}
```

The even/odd basis is:

```
q_i± = (e_i ± e_{255-i}) / sqrt(2),  i = 0..127
Q = [q_+, q_-]
Qᵀ M Q = diag(M_+, M_-)
M_± = M_11 ± M_12 J
```

where the 256×256 matrix is partitioned into 128×128 blocks. The two blocks are 128×128. The transform is exact when the certificate holds, and the potential must preserve the symmetry: `V_i = V_{255-i}`.

The cost table is:

| Operation | Full 256 | Folded 128+128 | Ratio |
|---|---:|---:|---:|
| Storage | 65,536 entries | 32,768 entries | 1/2 |
| Matrix-vector multiply | 65,536 multiply-adds | 32,768 multiply-adds | 1/2 |
| Dense eigendecomposition | O(256³) | 2·O(128³) | 1/4 |
| Transform overhead | — | O(256²) once, or O(256) for the J basis | one-time |

So the user’s “halving” is correct for storage and matrix-vector work, but the dense eigensolve is a **quarter**, not a half. The foundations plan already states this correctly.

For the **255-head block**, the reversal is odd. There is one fixed middle head, and the blocks are 127 and 128 rather than 128 and 128. The fixed middle belongs to the symmetric block. The exact formula is in Appendix B.1. The full 256-position ring still has a 128+128 fold, but that fold includes the NANNET port; it must not be used for head authorization.

Crucially:

> **The void potential generally breaks centrosymmetry.** An inverse-square radial potential is not symmetric under radial reversal. A spatial palindrome of head indices does not automatically make the wave operator centrosymmetric. Fold is a guarded fast path, not a default.

The ring has a stronger fast path: if it is circulant, the Fourier transform diagonalizes it exactly. The hierarchy is:

1. **Circulant** → FFT/DFT.
2. **Centrosymmetric** → two 128×128 blocks.
3. **Symmetric** → Jacobi/Lanczos.
4. **General** → SVD/non-normal methods.

Use the strongest symmetry that is actually certified. Do not use a weaker fast path when a stronger one is exact, and do not use either without a certificate.

### 6.8 Folded plus residual

When a matrix is almost centrosymmetric, use:

```
M = M_fold + M_residual
```

`M_fold` is the centrosymmetric part, solved cheaply; `M_residual` is the symmetry-breaking part, stored sparse or low-rank. This is a practical way to keep the fold even when the void or port breaks the symmetry. Measure the residual norm and rank; if the residual is large, use the general path.

---

## 7. The six verbs

The three source plans use slightly different verb lists. This plan uses one canonical set and treats the others as aliases.

| Canonical verb | Aliases | Mathematical action | NaN16 kernel family |
|---|---|---|---|
| `ENCODE` | — | Map typed input to mode/aperture coefficients. | Typed encode, normalization, projection. |
| `QUERY` | `PROJECT` | Project state into a validated basis; top-k. | Dot products, basis transform, residual. |
| `MATCH` | — | Compare normalized spectral signatures. | Power spectrum, cosine/Wasserstein, threshold. |
| `FILTER` | — | Apply `g(H)` or `g(M)` in a validated basis. | Polynomial/Chebyshev or eigenbasis filter. |
| `DRIVE` | — | Inject a bounded source or solve an inverse aperture problem. | Matvec, pseudoinverse, energy budget. |
| `FOLD` | — | Guarded symmetry reduction. | Centrosymmetry certificate, 128 blocks. |
| `PROPAGATE` | internal | Advance the wave equation by a declared step. | Leapfrog/Verlet, damping, CFL. |
| `DECODE` | — | Typed readout with confidence and provenance. | Linear readout, softmax, calibration. |
| `TRACE` | internal | Emit an evidence record. | Digest, metrics, status, provenance. |

### 7.1 `ENCODE`

Input: a typed record — token embedding, graph state, ring pattern, or external signature.  
Output: `x` in `C^256` or a declared rectangular dimension.  
Preconditions: shape, type, norm, and provenance validated.  
Postconditions: norm and scale declared; no silent coercion; no host math.  
Failure: invalid type, shape, norm, or unsupported encoding.

The encoder may be fixed or learned. The MTH kernel performs the linear algebra; the learning system chooses the parameters. The encoder is not the same object as the wave operator.

### 7.2 `QUERY`

Input: state `x` and a validated basis `P` or `U`.  
Output: spectral coordinates `z = P† x`, top-k indices, reconstruction error.  
Preconditions: basis version matches operator version; basis is orthonormal or the dual is declared.  
Postconditions: `||x - P z||` reported; no stale eigenvectors.  
Failure: basis mismatch, rank deficiency, non-finite input, nonconvergence.

### 7.3 `MATCH`

Input: two signatures `s(x)`, `s(y)` or a signature and a stored codebook.  
Output: metric, threshold, confidence, nearest patterns.  
Preconditions: signatures normalized; phase convention declared (phase-sensitive or phase-invariant).  
Postconditions: calibration reported; null/shuffled baseline available.  
Failure: incompatible signature spaces, zero norm, uncalibrated threshold.

The default NANNET signature is **phase-invariant**: a normalized power spectrum. Phase-sensitive matching is allowed only when a shared phase reference exists.

### 7.4 `FILTER`

Input: state `x`, basis `P`, response `g`.  
Output: `y = P g(Λ) P† x`.  
Preconditions: `g` is bounded; eigenvalues are known or a polynomial approximation is validated.  
Postconditions: stability, norm, and energy reported.  
Failure: unstable response, unbounded gain, basis mismatch.

Filter families:

- low-pass: global/context modes;
- high-pass: detail/local modes;
- band-pass: the Ring of Power band;
- notch: suppress a mode or a contaminant;
- learned diagonal: a small, stable adapter;
- colored-noise shaper: `g` applied to a seeded noise field.

### 7.5 `DRIVE`

Input: a target ring pattern, a source record, or a spectral injection.  
Output: bounded drive coefficients and the resulting state change.  
Preconditions: reachability checked; energy/rate budget declared.  
Postconditions: injected energy reported; no control-head writes; no unregistered ranges.  
Failure: unreachable target, energy budget exceeded, invalid channel, ACL denial.

`DRIVE` has two modes:

- **Forward drive:** inject a known source `B f(t)`.
- **Inverse drive:** solve `M c = target` for the mode coefficients, using a regularized pseudoinverse; if the target is unreachable, report the residual and the reachable projection.

The inverse mode is the control-theoretic form of the user’s “use P to inject into the NANNET channel.” It is powerful and must be bounded: no drive may exceed the energy budget or touch a reserved head.

### 7.6 `FOLD`

Input: a matrix and a symmetry certificate.  
Output: folded blocks, residual, or a rejection.  
Preconditions: `J M J = M` within the declared tolerance; potential and geometry preserve the symmetry.  
Postconditions: folded reconstruction error reported; fallback available.  
Failure: symmetry residual too large; authorization map crosses a reserved head; non-normal block.

The authorization caveat is essential:

> **A mathematical symmetry is not an authorization symmetry.** If a mirror pair maps a learning head to a reserved BSR control head, the fold is read-only or excluded for writes. The mathematical `J` and the head ACL must be reconciled by a signed atlas.

### 7.7 `PROPAGATE`

Input: state, velocity, operator, step, damping, drive.  
Output: next state, energy, stability status.  
Preconditions: CFL bound satisfied; operator digest matches; workspace sufficient.  
Postconditions: energy drift reported; no hidden source; deterministic.  
Failure: instability, non-finite state, budget exhaustion.

### 7.8 `DECODE`

Input: ring state or spectral coordinates.  
Output: typed output, confidence, provenance.  
Preconditions: decoder version and calibration match.  
Postconditions: uncertainty and evidence attached.  
Failure: out-of-distribution input, unsupported output type, calibration mismatch.

### 7.9 `TRACE`

Every execution emits a trace envelope. The trace is not optional. It is the evidence that makes the system learnable and auditable.

---

## 8. The Ring of Power and the NANNET node

### 8.1 The ring as a harmonic aperture

The ring is a boundary sampling surface. Its 256 positions are **255 head samples plus one NANNET port sample**. The angular Fourier transform is the aperture transform. The `M_wave` matrix is the aperture code that maps hidden radial modes to observable angular samples.

This gives a clean interpretation of the user’s formula:

- `A_mn` is the aperture/coefficient matrix.
- `R_n(r_ring)` is the radial mode evaluated at the ring.
- `e^{i n θ_i}` is the angular phase at position `i`.
- The sum over `n` produces the ring field.
- The absolute value produces the position amplitude.

The 256-point inverse DFT is the primary readout. The 255-point DFT is the head-only reference. The 256-point FFT is the fast path; the direct DFT is the reference.

### 8.2 Coherent and incoherent rings

| Regime | Sum | Observable | Use |
|---|---|---|---|
| **Coherent** | Complex amplitudes add with stable phase. | Bright antinodes, high `R_ring`. | Ring of Power, phase-coded memory. |
| **Incoherent** | Powers add; phases average out. | Smooth ring, low `R_ring`. | Robust signature, noise calibration. |
| **Partially coherent** | Some modes phase-lock; others do not. | Speckle, dynamic antinodes. | Creativity/exploration hypothesis. |

The Ring of Power is the coherent, high-energy-concentration regime. It is measured by:

- ring energy fraction;
- participation ratio;
- `R_ring` coherence;
- antinode alignment;
- radial localization;
- eigenvalue gaps.

No single metric is sufficient. A bright ring could be a trivial DC mode; a high coherence could be a single mode. Report the full vector.

### 8.3 The 255-head + NANNET binding

Each universe has **255 heads** and **exactly one NANNET node**. The NANNET node is not a head. The ring has 256 positions: 255 head positions plus the NANNET port position.

The default head allocation is:

| Ring role | Count | Authority |
|---|---:|---|
| Learning heads | 249 | Writable within the learning ACL and candidate bins. |
| BSR control/guard heads | 6 | Read-only for wave writes; fixed phase references or boundary guards. |
| Total local heads | 255 | The complete head namespace `0..254`. |
| NANNET node | 1 | Network endpoint/port; not a head; not trainable. |
| Ring positions | 256 | 255 head positions + 1 NANNET port position. |

The six BSR control heads remain `0,4,5,6,7,8`. If the authority wants 250 learning heads, one reserved control head must be explicitly released and re-signed; this plan does not make that change silently.

The six control heads can serve as:

- fixed phase references;
- guard modes that detect drift;
- boundary conditions for the ring;
- reserved channels for BSR/control traffic.

They must not be overwritten by the wave engine. The NANNET node likewise must not be treated as a trainable vertex. The ring binding is a signed atlas, not an arithmetic identity. A mathematical position index does not automatically map to the head with the same number, and the port position is never a head.

### 8.4 The NANNET node as the single egress/ingress

Exactly one NANNET node exists per universe. It is the only network endpoint for that universe. It does not compute wave mathematics, own state, or hold a learning ACL.

Input:

- ring state or a compressed ring signature;
- operator/embedding version;
- phase reference or phase-invariant declaration;
- provenance and evidence level.

Output:

- a typed NANNET record;
- a normalized spectral signature;
- a confidence and calibration status;
- a digest and signature;
- a timestamp/clock reference;
- a route/authorization envelope.

Guarantees:

- no raw state leaves without an explicit policy;
- no reserved head or private bin is included;
- no phase-coherence claim is made unless a clock model exists;
- remote results are untrusted until validated;
- rate, size, and retention limits are enforced;
- the node cannot write head state, control heads, or the master route cache.

The NANNET node does not radiate a wave into a physical medium. It samples the ring port, compresses the observable signature, signs it, and routes it through NANNET. The transformation ID is `RSS.PORT.NANNET.v1`.

### 8.5 The NANNET port boundary

For a later stage, model the network as an external scattering system:

- internal cavity: the annulus;
- the one port: the NANNET node;
- external network: NANNET with delays, losses, and untrusted peers;
- scattering matrix: maps incoming to outgoing port signals;
- the NANNET node: the outgoing/incoming readout;
- incoming remote signatures: treated as untrusted drives.

This is a disciplined way to connect the wave equation to the network without claiming that network clocks preserve internal phase. If phase coherence is required, define:

- the clock model;
- drift bounds;
- synchronization protocol;
- failure behavior;
- phase-reference distribution.

Otherwise use phase-invariant signatures.

### 8.6 The state seal

The technical artifact is a **state seal** or **cartridge**. It is not a claim of consciousness. It contains:

- universe ID, topology digest, embedding version;
- operator ID/version/digest and precision;
- geometry parameters: `r_core`, `r_ring`, `r_max`, shell map;
- void parameters: `α`, `β`, `κ`, `ε`;
- `M_wave` coefficients, phases, and rank;
- radial basis digest and ring samples;
- energy, residual, and evidence level;
- seed, integrator, step count;
- provenance and signature.

The cartridge can be replayed in another universe, archived, or transported by the NANNET node. It does not transfer authority, identity, or control-head ownership. Replay is sandboxed and validated. The outer ring readout is a compressed, signed signature of the state seal, not a literal soul broadcast.

### 8.7 Network federation experiments

Compare:

- local-only baseline;
- phase-invariant signature exchange through the NANNET node;
- phase-sensitive exchange with a shared reference;
- raw-state transfer (for comparison only, not default);
- federated match with synthetic peers;
- federated match with real NANNET peers.

Measure retrieval precision/recall, accuracy, novelty, contradiction rate, calibration, latency, bandwidth, privacy leakage, and failure recovery. Do not enable federation by default until the local system is stable and the signatures are calibrated.

---

## 9. Tunneling, avoided crossings, and creative insight

### 9.1 The block coupling model

Partition the system into inner and outer regions:

```
H(η) = [[H_in, η C],
        [η Cᵀ, H_out]]
```

`η = 0` disconnects the regions. `η = 1` is full coupling. For `0 < η < 1`, energy can transfer through the barrier. Define transmission:

```
T(η) = E_received / E_injected
```

This is a computational tunneling analogue. It is not automatically quantum tunneling. The barrier may be a finite potential region, a Robin core, or a coupling block. Measure `T(η)` versus barrier width, height, mode, and frequency.

### 9.2 Evanescent bands and turning points

For a mode with frequency `ω`, the radial equation has a turning point where:

```
ω² = V_eff(r_t; m)
```

For `r < r_t`, the mode is evanescent (if `V_eff > ω²`); for `r > r_t`, it propagates. The barrier band is the region between turning points. The Ring of Power is the readout band near the outer turning point.

The “forbidden inner region” is therefore mode-dependent. It is not universally forbidden. High-`m` modes have a larger barrier; low-`m` modes penetrate. The core boundary can forbid all modes, but that is a separate design choice.

### 9.3 Avoided crossings and discontinuous insight

A precise mechanism for “a thought jumps discontinuously to a new structure” is an **avoided crossing**:

- two eigenvalues of `H(η)` approach as `η` varies;
- the eigenvectors rotate rapidly near the closest approach;
- a slow sweep transfers the state adiabatically;
- a fast sweep produces a diabatic jump to the other branch.

This is analogous to Landau-Zener transfer. It is testable:

- sweep `η` or a drive parameter;
- measure the eigenvalue gap;
- measure the eigenvector overlap before/after;
- measure the transition probability;
- measure the downstream task outcome.

The “insight” is not the unusual output. The insight is a **correct, novel association that survives verification** after a controlled transition. The system should report the transition, the evidence, and the confidence, not claim creativity.

### 9.4 The creativity experiment

Conditions:

- `η = 0` (disconnected baseline);
- small `η` (tunneling regime);
- `η = 1` (full coupling);
- random coupling;
- shuffled geometry;
- phase-scrambled coupling.

Tasks:

- held-out analogical reasoning;
- remote association with a known correct answer;
- puzzle solving;
- contradiction detection;
- open-ended generation with human evaluation.

Metrics:

- correct novel association rate;
- factuality;
- contradiction rate;
- diversity;
- repeatability;
- calibration;
- latency;
- human-rated novelty and usefulness.

Kill criteria:

- no improvement over the disconnected or random-coupling baseline;
- improvement only on training examples;
- high novelty but high falsehood;
- unstable or irreproducible;
- energy or latency cost unjustified.

### 9.5 The void as a regularizer

A separate hypothesis: the centrifugal barrier prevents representation collapse by forbidding all modes from concentrating at a single point. Test:

- `α = 0` versus increasing `α`;
- representation entropy/diversity;
- calibration;
- generalization;
- robustness to adversarial inputs.

If the void improves diversity but harms accuracy, report the trade-off. Do not call it a success by one metric.

### 9.6 No quantum or consciousness claim

The words “tunneling,” “quantum,” “network,” and “state seal” are preserved as named interfaces and hypotheses. They do not assert physical quantum behavior, consciousness, or a soul. The plan’s claims are mathematical and empirical.

---

## 10. NaN16-native execution

### 10.1 The rule

Every mathematical operation in this architecture is a NaN16 implementation. The host may:

- assemble with `nasm0`;
- launch with `n16i` or the native kernel;
- transport bytes;
- compare bytes;
- enforce ACLs and leases;
- collect traces.

The host may not compute eigenvalues, trigonometric functions, matrix products, filters, or expected mathematical results on behalf of the guest. A host-side reference may be used as a test oracle for differential validation, but it is not the runtime implementation.

### 10.2 Numeric lanes

| Lane | Representation | Use | Evidence |
|---|---|---|---|
| Exact unsigned | U32 | Indices, counts, addresses, topology. | Exact fixtures, boundary tests. |
| Exact signed | I32 | Differences, coordinates, fixed-point. | Sign/overflow tests. |
| Fixed-point | Q16.16 | Graph weights, Laplacian, void potential, exact-ish operators. | Scale/range proofs, saturation tests. |
| Float32 | IEEE binary32 via NaN16 ops `0x30–0x37` | Trig, rotations, wave state, spectral estimates. | Error envelopes, residual checks. |
| Complex | Pair of float32 or Q16.16 | Phases, Hermitian operators. | Phase convention, conjugation tests. |
| Compensated | Pair-float | Dot products, orthogonality, residuals. | Error-bound tests. |

No silent coercion. No hidden host float. No NaN-payload arithmetic without decoding. The class nibble is a record seal, not a numeric type.

### 10.3 Memory budget

The guest working set is the constraint that shapes the algorithms.

| Object | Size at float32 | Size at Q16.16 | Fits 512 KiB guest? |
|---|---:|---:|---|
| 256-vector | 1 KiB | 0.5 KiB | Yes. |
| 256×256 matrix | 256 KiB | 128 KiB | One float32 matrix plus small scratch; two matrices fill the guest. |
| 256×256 matrix + eigenvectors | 512 KiB | 256 KiB | Float32 does not fit with scratch; Q16.16 does. |
| 128×128 folded block + eigenvectors | 128 KiB | 64 KiB | Yes, with scratch. |
| Two 128×128 blocks + eigenvectors | 256 KiB | 128 KiB | Yes at float32 with care. |
| 256×256 complex float32 | 512 KiB | 256 KiB | Complex float32 does not fit with scratch; Q16.16 or paging. |
| Product state 256×256 | 256 KiB | 128 KiB | One buffer fits; double buffering at float32 fills the guest. |
| Dense 65,536×65,536 | 16 GiB | 8 GiB | Forbidden. |

The 8 MiB universe is the persistent store, not the guest working set. At 32 KiB per page, the 8 MiB universe has **256 pages**: 255 head pages plus one NANNET node page. The 512 KiB guest holds 16 pages. That is a direct structural alignment: the 255+1 convention is also the universe page layout.

A 256×256 float32 ring matrix is 256 KiB = 8 pages; a 255×255 float32 head-only matrix is 254 KiB = 7.94 pages (127 KiB at Q16.16). The universe can hold the matrix, eigenbasis, ring samples, and seal pages; the guest can hold one or two matrices at a time. The wave engine must page, tile, fold, or low-rank. The 2 GiB overbootstrap map is hosted only by the Bootstrap runner and is not copied into the guest or to peers; it may index signatures and candidate operators, not store raw dense wave arrays.

### 10.4 Algorithm choices

| Task | First choice | Fast path | Fallback |
|---|---|---|---|
| Ring angular transform | 256-point DFT reference | 256-point FFT with twiddle table | Direct O(n²). |
| Radial operator | Tridiagonal finite-difference | QL/Jacobi for 16–256 modes | Lanczos for top-k. |
| Symmetric eigensolve | Jacobi reference | Folded 128+128; Lanczos top-k | General QR/Schur. |
| General aperture | SVD via one-sided Jacobi | Truncated SVD | Full SVD with paging. |
| Void potential | Q16.16 regularized `α/(r²+ε²)` | Table + reciprocal | Float32 with error bound. |
| Trig | CORDIC or quadrant-reduced table | 256-entry table | Series with error bound. |
| Wave step | Leapfrog/velocity Verlet | Modal propagation for ring readout | Implicit step for stiff cases. |
| Filter | Polynomial/Chebyshev recurrence | Eigenbasis diagonal filter | Rational filter. |
| Colored noise | Seeded PRNG + covariance square root | Diagonal spectral shaping | Low-rank approximation. |
| Product operator | Matrix-free Kronecker | Low-rank `Σ B_r ⊗ C_r` | Tiled block application. |

### 10.5 Record seals and the class nibble

The 16 ordered class combinations are a native 4-bit alphabet. They may be used as **record seals** inside a versioned wave-record schema:

- canonical data words use class 10 (`+q/+q`);
- orientation pairs use the reversible `rot2` pairs;
- real/imag, forward/reverse, operator/adjoint, state/evidence, and similar roles can be encoded as variants;
- the schema, not the class nibble alone, defines the meaning;
- instruction streams retain their frozen NaN16 semantics;
- data streams declare their record family;
- no silent canonicalization of a face pair.

The double-ended pair codec can protect critical records (operator descriptors, seeds, evidence) with two members and mismatch rejection. It is not used for every matrix entry; the memory cost is too high. The full matrix uses canonical data words; the descriptor carries the schema, shape, precision, and digest.

### 10.6 Evidence and promotion

Every kernel follows the MTH evidence ladder:

1. **Defined:** signature, domain, semantics written.
2. **Assembled:** NaN16 source assembles.
3. **Executed:** a known fixture ran.
4. **Regression-tested:** a meaningful suite passed.
5. **Differentially checked:** an independent reference agrees.
6. **Property-tested:** invariants hold over a declared space.
7. **Proved:** a proof object/checker establishes the stated theorem.
8. **Promoted:** policy accepts the implementation for normal use.

No runner may dispatch a kernel that is not native-verified with:

- exact source digest;
- ABI/version;
- workspace limit;
- precision/rounding contract;
- evidence level;
- cancellation/epoch rules.

### 10.7 Current implementation anchors

The main branch currently contains the MTH Stage 0 source slice and the two source plans. The graph-spectral implementation snapshots outside main have reached native verification for:

- the exact K256 U16-input Laplacian (ring-position baseline);
- the K255 head-only baseline, derived from the K256 kernel by excluding the NANNET port;
- the sparse Q16.16/I32 graph Laplacian with path/disconnected fixtures;
- the U32 vector span-add primitive;
- the reentrant double-endian pair codec.

Those are anchors, not an integrated wave engine. No void, radial eigensolver, aperture SVD, ring readout, fold, or NANNET port kernel exists yet. This plan is **R0**: contract freeze, not implementation.

---

## 11. Integration with NaNROUTER and NaNLMind

### 11.1 One universe, one owner

The wave engine is a capability of the one canonical NaNLMind universe. It does not create:

- a second topology;
- a second runner ring;
- a second task ledger;
- a second memory owner;
- a second mathematics authority.

NaNROUTER routes authorized tasks and results. It does not own mathematical truth or the wave state. MTH supplies the NaN16 transformations. NaNLMind owns the universe, the semantic ledger, and the learning state.

### 11.2 Namespace reconciliation

| Namespace | Range | Use in this plan |
|---|---|---|
| Local head index | 0..254 | 255 heads: 249 learning + 6 BSR control. |
| NANNET node identity | 1 per universe | The universe’s single network endpoint; not a head. |
| Mathematical ring position | 0..255 | 255 head positions + 1 NANNET port position. |
| Mathematical mode index | 0..255 per axis | Angular, radial, or ring-sample index; never a head identity by default. |
| Overbootstrap node point | 1..255 | External NANNET endpoint identity; never a local head index by default. |
| BSR wire identity | BSR0..BSR5 | Control-plane identity; separate from display labels. |
| Object selector | vector/hyperedge IDs | Typed object association; not a mode index. |

The ring binding is a signed atlas that maps mathematical ring positions to head IDs, control guards, the NANNET port, and ACLs. It must preserve the six reserved heads and the 249 learning heads. It must not renumber the 255-head topology, collapse the NANNET node into a head, or alter the six-runner ownership map.

### 11.3 Route path

A wave/MTH request travels through the existing authorized task/result path:

1. typed request with operation ID/version, inputs, workspace, precision, determinism, deadline, and expected result contract;
2. authority checks permissions and issues a bounded lease;
3. runner executes the native kernel with the specified digest and workspace;
4. result carries output digest, residual/error bound, saturation count, iteration count, runner/kernel identity, and status;
5. NaNLMind validates and, if appropriate, commits through the existing ledger and generation-checked path.

No private runner dispatch. No second lease ledger. No direct write to the master route cache.

### 11.4 Runner Riddle

Runner Riddle may:

- read permitted wave traces and signatures;
- mine candidate aperture patterns, ring metrics, and operator deltas;
- propose candidate operators, filters, and fold certificates;
- emit signed, bounded learning traces.

It may not:

- write the live master cache;
- overwrite control heads or permanent identities;
- promote its own candidates;
- write outside the authorized bins/ranges;
- treat a spectral signature as ground truth.

Candidate promotion requires validation, authorization, and an exact generation compare-and-swap. The wave engine’s evidence records feed the same M9 meta-map and merge path as the rest of the system.

### 11.5 Safety and ACL

- Unknown ranges are deny by default.
- The six BSR heads are read-only for wave writes.
- The six BSR control heads and the NANNET port remain intact.
- The 249 learning heads are writable only within their ACL and candidate bins.
- The wave engine cannot modify executable code, protocol definitions, live route tables, or permanent endpoint identities.
- The NANNET node is signed, rate-limited, provenance-bound, and size-bounded.
- Remote results are untrusted until validated.
- A mathematical symmetry does not override an authorization boundary.

### 11.6 The 2 GiB overbootstrap

The 2 GiB map stays on the Bootstrap runner. It is not copied to Android or peer nodes. The wave engine may use it for:

- indexing candidate operators and spectral signatures;
- storing evidence records and match indexes;
- meta-map learning over ring metrics and fold certificates.

It is not a place to materialize dense wave arrays or the 65,536×65,536 product operator. The 8 MiB universe holds the persistent wave pages; the 512 KiB guest holds the working set; the 2 GiB map holds control/meta records.

### 11.7 Storage and execution fabric: NaNROUTER, CPU runners, Koyeb BS0DB/MC0DB

The plan is not storage-agnostic. The fabric already exists, and the wave architecture should use it rather than invent another store.

| Tier | Where it lives | What it owns | What it may hold | What it must not become |
|---|---|---|---|---|
| **L0 — guest working set** | NaN16 guest | Transient execution | One or two matrices, vectors, scratch, current step | Persistent truth |
| **L1 — CPU runner scratch/cache** | `nanlm-cpu-1` … `nanlm-cpu-6`, MC0:0/R0–R5 | Leased job workspace and bounded page cache | Input pages, operator pages, partial results, traces | Canonical state or a second ledger |
| **L2 — universe pages** | 8 MiB universe, 256 × 32 KiB pages | Canonical wave state for that universe | 255 head pages + 1 NANNET node page; matrix pages, eigenbasis pages, ring samples, seal page | A network database or a 2 GiB map copy |
| **L3 — BS0DB** | Koyeb BS0:0, `/bs0db`, `bs0db.sqlite3` | Durable ingress/egress and evidence | Source inbox, wave job intake, trace envelopes, state seals, signatures, candidate feedback | Canonical mathematical truth or the master route cache |
| **L4 — MC0DB** | Koyeb MC0:0, `/mc0db`, `mc0db.sqlite3` | Six-runner control/meta state | Job/lease queue, operator registry, fold certificates, capability registry, match index, runner heartbeats | Raw dense wave arrays or a second universe |
| **L5 — 2 GiB overbootstrap** | Bootstrap runner only | Slow meta-map/index | Candidate/operator indexes, cross-layer reliability, signature catalog | Raw dense wave state; never copied to Android or peers |

SC0DB and GM0DB remain in the router-owned volume registry (`spec/volume-registry.md`). This plan does not repurpose them; if they are used for source/clock or global-mesh records, that role must be signed in the registry rather than inferred.

The key rule:

> **BS0DB and MC0DB are durable control/evidence stores, not the canonical universe. NaNLMind’s ledger is canonical; the 8 MiB universe is the canonical wave-page store; BS0DB/MC0DB hold durable replicas, indexes, traces, seals, and control state.**

The six-slot runner ring (`MC0:0/R0..R5` / `NANROUTER-0..5`) is **single-active** execution capacity, not six simultaneous math authorities and not six per-universe network nodes.

| Runner-ring rule | Value |
|---|---|
| Logical slots | 6 |
| Active slots at any instant | **1** |
| Active working-memory ceiling | **7 GiB** |
| Standby slots | 5, no live working set |
| Cycle | drain leases, checkpoint, release memory, activate next slot |
| Purpose | 24/7 availability with clean handoff, not six-way parallel execution |

The other five slots are standby. A slot must not activate while the previous slot has live leases, live memory, or an uncommitted checkpoint.

**The ring is addressed through point 0.** Clients use the stable point-0 ingress (`BS0:0` / `BSR0`), not a slot identity. Point 0 translates NaN16 frames to binary transport and back, then routes to whichever slot is currently active. The active slot is internal and can change without renumbering clients. Direct `R0..R5` addressing is an internal control path only.

Each runner advertises:

- kernel IDs and native-verification digests;
- maximum workspace and precision lanes;
- current lease/epoch and queue depth;
- supported operator/capability versions;
- cancellation and stale-work behavior.

A runner rejects a job when the operator digest, workspace, precision lane, ACL, epoch, or cancellation state does not match. The runner ring observes and reconciles control state; it does not own the master route cache or the mathematical truth.

The NANNET node is one logical node per universe, not one per runner slot. Koyeb BS0:0 is the persistent physical ingress/egress gateway. The six-slot runner ring is MC0:0/R0–R5; only one slot is active at a time. A universe’s single NANNET node is registered in MC0DB and uses the Koyeb gateway; it is not a runner slot, not a head, and not a per-runner socket.

#### Data placement

| Artifact | Canonical home | Durable/index home | Never |
|---|---|---|---|
| Current wave pages | 8 MiB universe (255 head + 1 NANNET page) | BS0DB immutable page snapshots; MC0DB descriptors | Public raw-state index |
| `H_wave` / `M_wave` operator | Universe page set | MC0DB operator registry + digest | Dense 65,536² materialization |
| Eigenbasis | Universe pages | MC0DB versioned descriptor | Stale basis reused after operator change |
| Ring samples / signatures | Universe + BS0DB seal record | MC0DB phase-invariant match index | Raw private state in the match index |
| Trace envelope | BS0DB | MC0DB job index | Untracked execution |
| State seal/cartridge | BS0DB | MC0DB index + NANNET record | Authority transfer |
| Candidate operator | MC0DB candidate table | Runner cache | Direct master-cache write |
| Fold certificate | MC0DB | Runner cache | Uncertified fast path |
| Capability registry | MC0DB | NaNROUTER route resolution | Self-promoted kernel |
| NANNET node identity | MC0DB registry + secret manager | BS0DB ingress/egress records | Head page or training target |
| 2 GiB overbootstrap | Bootstrap runner | MC0DB index references | Android, peer, or guest copy |

#### Job flow

1. A universe’s NANNET node submits a signed, typed wave/MTH job to Koyeb BS0:0.
2. BS0DB stores the intake record; NaNROUTER validates identity, ACL, range, lease, and rate.
3. MC0DB holds the job and lease; the single active runner slot leases it.
4. The runner fetches the required pages, executes the native NaN16 kernel with the declared digest/workspace, and writes the result and trace.
5. BS0DB stores the trace envelope, state seal, and signature; MC0DB stores the candidate operator/capability and match index.
6. NaNLMind validates and, if appropriate, commits through the existing generation-checked ledger.
7. NaNROUTER resolves routes; the master cache is untouched until an authorized CAS commit.

No runner writes the master route cache. No database row becomes a route without NaNROUTER authorization. No candidate operator becomes dispatchable without a native-verification digest and capability registration.

#### Consistency rules

- Every record carries `universe_id`, `generation`, `digest`, `producer`, `lease/epoch`, `nanclock_tick`, and signature.
- Job IDs are idempotent; replay returns the same result or a stale-generation rejection.
- Writes use transactions/WAL; page blobs are content-addressed and chunked, not one giant row.
- Leases expire; expired work is recoverable; a stale worker cannot commit.
- The 8 MiB universe is paged; BS0DB/MC0DB store snapshots/descriptors, not a competing live state.
- The 2 GiB overbootstrap map is not copied into BS0DB/MC0DB as a raw blob; it stays on the Bootstrap runner and is indexed.
- Secrets, HMAC keys, and node private keys live in the environment/secret manager, never in BS0DB/MC0DB or Git.
- Unknown volume health is `unknown`, not green. The signed volume registry (`spec/volume-registry.md`) owns logical-to-physical binding and health; configuration alone is not deployment proof.
- Retention and migration are versioned; no destructive migration without a backup and a generation check.

#### Conceptual schema ownership

This is a schema sketch, not a frozen ABI. The final schema must be versioned and authorized.

| Store | Conceptual tables |
|---|---|
| BS0DB | `wave_source`, `wave_trace`, `wave_seal`, `wave_signature`, `wave_job_intake`, `wave_feedback` |
| MC0DB | `wave_job`, `wave_lease`, `wave_operator`, `wave_fold_certificate`, `wave_capability`, `wave_match_index`, `wave_runner_heartbeat` |
| Universe pages | `wave_page`, `wave_state`, `wave_eigenbasis`, `wave_ring`, `wave_binding` |

#### R0 storage gate

Freeze before writing wave kernels:

1. Which store owns each artifact.
2. The page size, digest, generation, and chunking rules.
3. The job/lease/capability state machine.
4. The signature/seal schema and retention policy.
5. The ACL and token boundaries for BS0DB, MC0DB, CPU runners, and NANNET nodes.
6. The backup/migration/recovery rules.
7. The proof that BS0DB/MC0DB are not canonical mathematical truth and that no secret or dense product is stored there.

### 11.8 Governance invariants

1. The wave engine never becomes the owner of state.
2. Each universe has exactly 255 local heads and one NANNET node.
3. The six-slot runner ring has exactly one active slot and a 7 GiB active-memory ceiling.
4. The six control heads never become wave-training vertices.
5. The NANNET node is never counted, trained, or overwritten as a head.
6. The ring binding is signed, versioned, and ACL-checked.
7. The NANNET node cannot inject unsolicited state into the universe.
8. A state seal does not transfer authority.
9. A candidate operator cannot self-promote.
10. A spectral match is evidence, not truth.
11. A mathematical symmetry is not an authorization symmetry.
12. The host does not compute the mathematics.
14. Point 0 is the only runner-ring address; the active slot is internal.
15. A plan is not an implementation.

---

## 12. Staged roadmap

The order is deliberately conservative. Each stage has a gate. Do not skip stages because the later vision is more exciting.

### R0 — Contract freeze

Define and freeze:

- the five objects and their names;
- the four namespaces;
- the 255-head + 1-NANNET-node convention and the 256-ring-position layout;
- the three geometries and the default;
- the numeric lanes and memory budget;
- the matrix roles and decomposition rules;
- the six verbs and aliases;
- the transformation catalogue IDs;
- the claim ledger and evidence policy;
- the ring/head binding rules;
- the storage ownership of BS0DB, MC0DB, the 8 MiB universe, the CPU runners, and the 2 GiB overbootstrap;
- the page size, digest, generation, job/lease/capability state machine, retention, backup, and migration rules.

**Gate:** every object has a unique name; every 256 and 65,536 is accounted for; every artifact has a storage home; no operation is ambiguous about which matrix it uses; no canonical truth is placed in BS0DB or MC0DB; no secret or dense product is stored there.

### R0 implementation ledger (begun)

R0 begins with this document. The first implementation artifacts are:

1. This deep plan as the frozen contract candidate.
2. The 255+1 namespace and 256-position ring convention.
3. The `H_ring`/`H_heads`/`M_wave`/`M_heads` matrix split.
4. The BS0DB/MC0DB/universe/runner storage ownership table.
5. The evidence ledger and the “no host math” rule.
6. The R1–R10 gates with explicit native-verification requirements.

No `.nas` kernel is promoted to dispatchable status until R1 and its native fixture pass. The plan is the beginning of the implementation, not a substitute for it.

### R1 — Exact geometry

Implement and verify:

- ring/annulus coordinates;
- shell membership;
- the 8 MiB page map: 255 head pages + 1 NANNET node page;
- K256 ring-position Laplacian oracle;
- K255 head-only Laplacian oracle;
- path-graph and disconnected-graph Laplacian oracles;
- sparse graph Laplacian;
- exact parity and symmetry checks.

**Gate:** K256 spectrum (0 once, 256 with multiplicity 255); K255 spectrum (0 once, 255 with multiplicity 254); path/disconnected oracles exact; the page map is one-to-one and the NANNET page is not a head; native verification recorded.

### R2 — Void and radial blocks

Implement and verify:

- regularized core potential;
- Dirichlet/Robin inner boundary;
- α = 0 baseline;
- α sweep with finite values and no singularity;
- angular Fourier block structure;
- radial energy and localization metrics.

**Gate:** α = 0 matches the baseline; every potential value is finite; block structure is exact for a centred symmetric annulus; no mode reaches the singular point.

### R3 — Spectral engine

Implement and verify:

- 256-point DFT/FFT reference for the full ring;
- 255-point head-only DFT reference;
- radial Jacobi/QL for small blocks;
- Lanczos for top-k;
- residual and orthogonality checks;
- centrosymmetry/circulant/symmetry certificates;
- folded 128+128 ring path;
- folded 128+127 head path;
- rejection of invalid fast paths.

**Gate:** eigenpair residuals below the declared tolerance; orthogonality below tolerance; folded and full solutions agree on certified fixtures; the 255-head odd fold is exact; nonconforming matrices reject the fast path.

### R4 — Wave dynamics

Implement and verify:

- leapfrog/velocity Verlet;
- CFL bound from a validated λ_max;
- undamped energy conservation;
- damped energy decrease;
- impulse response versus modal reconstruction;
- bounded drive;
- deterministic trace.

**Gate:** energy drift within tolerance; no growth without input; modal reconstruction agrees; instability is detected and reported.

### R5 — Aperture

Implement and verify:

- `M_wave` descriptor and roles;
- SVD/eigendecomposition decision tree;
- QUERY, MATCH, FILTER, DRIVE;
- observability/reachability metrics;
- capacity versus SNR/rank/quantization;
- colored-noise generator;
- fold certificate and residual.

**Gate:** reconstruct/encode/decode round trips; match calibration; filter stability; inverse drive bounded; capacity measured, not assumed.

### R6 — Product space

Implement and verify:

- matrix-free Kronecker application;
- low-rank cross-coupling;
- product eigenpair toy oracles;
- 65,536-mode accounting;
- memory-bounded tiling;
- rejection of dense product materialization.

**Gate:** matrix-free action matches small explicit Kronecker oracles; product eigenpairs match separable references; memory stays within budget; dense blow-up is rejected.

### R7 — Tunneling and creativity

Implement and verify:

- block coupling `H(η)`;
- transmission metrics;
- avoided-crossing sweep;
- phase coherence metrics;
- held-out creativity/association tasks;
- baselines and ablations.

**Gate:** reproducible improvement over disconnected/random baselines on held-out tasks; no claim from novelty alone; kill criteria applied.

### R8 — NANNET node and network federation

Implement and verify:

- ring signature extraction;
- state seal/cartridge;
- signed NANNET records;
- NANNET transport and auth;
- phase-invariant matching;
- BS0DB persistence for seals, traces, and ingress/egress records;
- MC0DB match index and capability registry;
- local versus federated experiments;
- stale/invalid/unauthorized rejection.

**Gate:** signature round trip; auth/quota/size enforcement; BS0DB/MC0DB store only durable replicas/indexes/evidence; no phase-coherence claim without a clock model; federated match improves over local-only or is rejected.

### R9 — LM adapter

Implement and verify:

- frozen base model;
- typed ENCODE/DECODE adapter;
- bounded residual `h + β C u`;
- spectral filter adapter;
- memory/retrieval adapter;
- ablations: void on/off, ring on/off, product on/off, real/complex, phase/magnitude.

**Gate:** held-out improvement over parameter/compute-matched baselines; no "learned" claim from training loss; latency/memory justified.

### R10 — Promotion

Promote only native-verified kernels with:

- source digest;
- ABI/version;
- workspace limit;
- precision/rounding contract;
- evidence level;
- cancellation/epoch rules;
- capability registration in MC0DB;
- route authorization through NaNROUTER.

**Gate:** runner dispatch refuses unverified, stale, mismatched, or under-resourced kernels; no capability is dispatchable without an MC0DB registration and a NaNROUTER-authorized route.

---

## 13. Metrics, baselines, falsification

### 13.1 Mathematical metrics

- eigenpair residual `||H φ - λ φ|| / ||φ||`;
- orthogonality `||P†P - I||`;
- reconstruction error;
- energy drift;
- CFL margin;
- symmetry residuals (symmetric, Hermitian, centrosymmetric, circulant);
- fold reconstruction error;
- condition number;
- rank and singular-value gap;
- saturation/overflow counts;
- deterministic repeatability.

### 13.2 Structural metrics

- radial energy fraction by shell;
- boundary-band energy fraction;
- angular power spectrum;
- participation ratio/localization;
- `R_ring` phase coherence;
- antinode count and alignment;
- eigenvalue gaps/time-scale separation;
- ring energy fraction;
- void/core leakage;
- port reflection/transmission.

### 13.3 Functional metrics

- retrieval precision/recall;
- exact-match accuracy;
- perplexity/negative log likelihood;
- calibration;
- contradiction rate;
- novelty/usefulness (human-rated where appropriate);
- repeatability;
- latency;
- memory;
- energy cost.

### 13.4 Baselines

Every functional claim needs:

- no module;
- graph diffusion;
- ordinary attention;
- parameter-matched MLP;
- random coupling;
- shuffled geometry;
- α = 0 (no void);
- folded versus full (same math);
- phase-invariant versus phase-sensitive;
- local-only versus federated.

### 13.5 Kill criteria

- No improvement over the matched baseline.
- Improvement only on training data.
- High novelty but high falsehood.
- Unstable or irreproducible.
- Fast path invalid on real matrices.
- Memory or latency blows the budget.
- The ring is not actually concentrated.
- The NANNET federation match is not calibrated.
- The claim cannot be stated at a defined evidence level.

### 13.6 Claim ledger

| Claim | Label | Evidence needed |
|---|---|---|
| K256 spectrum is 0 once and 256 with multiplicity 255. | Established identity | Derivation and native fixture. |
| K255 head-only spectrum is 0 once and 255 with multiplicity 254. | Established identity | Derivation and native fixture. |
| A graph Laplacian is positive semidefinite. | Established identity | Derivation. |
| A 256×256 matrix has 256 eigenpairs. | Established identity | Definition. |
| A product of two 256 spaces has 65,536 modes. | Established identity | Tensor-product definition. |
| Centrosymmetry reduces a dense eigensolve to two 128 blocks. | Established identity | Block derivation. |
| The void separates low-`m` and high-`m` content. | Hypothesis | Radial energy and angular spectra. |
| Weak barrier coupling improves creative association. | Hypothesis | Held-out tasks, baselines. |
| The aperture improves LM performance. | Hypothesis | Frozen-base ablation. |
| The ring is a high-coherence energy concentrator. | Hypothesis | `R_ring`, energy fraction, participation ratio. |
| The NANNET federation improves retrieval. | Hypothesis | Local versus federated experiment. |
| The fold residual is sparse/low-rank in practice. | Hypothesis | Measured residuals. |
| The 8 MiB universe is 256 × 32 KiB pages = 255 head pages + 1 NANNET page. | Established identity | 8 MiB / 32 KiB = 256; page map test. |
| BS0DB and MC0DB are canonical mathematical truth. | Rejected | NaNLMind ledger is canonical; DBs are durable replicas/indexes/evidence. |
| The six CPU runners are six math authorities or six per-universe NANNET nodes. | Rejected | They are MC0:0 execution slots; one NANNET node per universe. |
| The NANNET node is a head. | Rejected | It is a port/endpoint; 255 heads + 1 node. |
| 65,536 independent controls exist in `M_wave`. | Rejected | Rank bound. |
| Inverse-square potential attracts high-`l` modes to the boundary. | Rejected as stated | Derivation; it excludes them from the centre. |
| 256 real maxima are guaranteed on 256 samples. | Rejected | Nyquist. |
| `M_{m,255-m}` alone implies centrosymmetry. | Rejected | Full `J M J = M` is required. |
| The fold halves a dense eigensolve. | Rejected | It quarters it; halves storage/matvec. |
| NANNET transport preserves phase automatically. | Rejected | Network clocks do not imply phase coherence. |
| The wave equation alone produces intelligence/creativity. | Rejected | No evidence; task experiments required. |

---

## 14. Corrections to the original formulation

This section is deliberately direct. The vision is stronger when the mathematical distinctions are precise.

| Original formulation | Correction | Consequence |
|---|---|---|
| “The 256×256 standing wave has 65,536 independent modes; the matrix has 256 eigenvalues.” | Both are true of different objects. `M_wave` has at most 256 eigen/singular patterns; `U_wave` has 65,536 product coefficients; the product operator has 65,536 eigenpairs if separable. | Name the object and the operator before speaking of modes or eigenvalues. |
| “V_void(r)=λ/r² with λ=ℏ²l(l+1)/2μ.” | The `m²/r²`/`l(l+1)/r²` term is already the angular part of the Laplacian in polar coordinates. Adding `λ/r²` renormalizes the barrier or adds a second potential; declare which. | Use `(1+β)m²/r²` and a separate `V_core(r)`; avoid double counting. |
| “The potential repels low-angular-momentum modes and attracts high-angular-momentum modes to the boundary.” | The centrifugal term is weakest at low `m`; low `m` penetrates. High `m` is excluded from the centre. | The void is a mode separator; the core boundary/potential is what repels `m=0`. |
| “256 maxima around the ring = 256 vertices.” | The 256 ring positions are samples (255 head positions + 1 NANNET port); a real bandlimited field on 256 positions has at most 128 maxima. | Treat antinode count as a measured metric; use a complex envelope or dual ring if 256 maxima are required. |
| “A_{m,255-m} palindrome makes the matrix centrosymmetric.” | Centrosymmetry is `J M J = M`, i.e. `M_{i,j}=M_{255-i,255-j}`, not just the anti-diagonal. | Use the full certificate; distinguish persymmetry, centrosymmetry, circulant, symmetric, and Hermitian. |
| “FOLD halves the eigendecomposition cost.” | Storage and matvec halve; dense eigensolve quarters. | Report the operation-specific ratio. |
| “M_wave = PΛP† gives the principal oscillation modes.” | This is valid for normal matrices. A general aperture needs SVD; a non-normal operator needs Schur/left-right eigenvectors. | Name the role and the decomposition. |
| “Hermitian after complexification.” | A real matrix is Hermitian iff symmetric; a complex matrix is Hermitian iff `A=A†` with phase reciprocity. | Test, don’t assume; directed data use SVD/non-normal methods. |
| “The outer wave escapes through the NANNET port.” | A closed boundary reflects; escape needs an absorbing/port boundary. The network is a separate layer. | Add an outer port; do not put the network inside the wave equation. |
| “Tunneling through the void is creative insight.” | It is a computational coupling analogue and a hypothesis. | Measure transmission and downstream task outcomes; do not equate unusual output with creativity. |
| “256 NaN vertices.” | Each universe has 255 heads: 249 learning + 6 BSR control. The 256th ring position is the NANNET port, not a head. | Use a signed binding; guard the control heads and the port. |
| “Use A_mn as a 256×256 encoding matrix for 65,536 modes.” | A 256×256 matrix acts on 256-vectors; for the product state use `A⊗I` or `I⊗A`. Its rank is at most 256. | Capacity is measured, not inferred from coefficient count. |
| “NaN payloads store the wave numbers.” | NaN payloads can store tags/metadata; decode before arithmetic. | Use typed descriptors and explicit numeric lanes. |
| “The state seal broadcasts through the outer wave.” | The technical artifact is a state seal/cartridge and a signed spectral signature; no consciousness claim. | Preserve the poetry as an interface, not a physical claim. |

---

## 15. Open questions and decisions

| Decision | Default for R1 | Revisit at | Evidence needed |
|---|---|---|---|
| Geometry | G2 annulus 16×16 | R3/R6 | Native exactness, angular resolution, cost. |
| Ring | 256-position readout: 255 heads + 1 NANNET port; 249 learning + 6 control | R8 | ACL, antinode metrics, control guards, port contract. |
| Void model | Core Dirichlet + positive `β` | R2/R7 | α/β sweep, stability, radial energy. |
| `M_wave` role | Aperture/coupling | R5 | SVD, rank, condition, capacity. |
| Decomposition | SVD for general, eig for certified normal | R3/R5 | Residuals, normal tests. |
| Fold | Guarded centrosymmetry, residual fallback | R3 | Certificate, residual rank. |
| Ring fast path | FFT for certified circulant | R3 | DFT/FFT agreement, symmetry residual. |
| Eigensolver | Jacobi for small, Lanczos for top-k | R3 | Residuals, time/memory. |
| Precision | Q16.16 for operators, float32 for waves | R3/R4 | Error envelopes, stability. |
| Outer boundary | Closed cavity first | R4/R8 | Energy conservation, port reflection. |
| NANNET node | Phase-invariant signatures | R8 | Match calibration, privacy, latency. |
| Storage ownership | Universe pages canonical; BS0DB evidence/seals; MC0DB control/meta | R0/R8 | Page map, schema, retention, recovery. |
| Runner dispatch | Capability-based, six MC0:0 slots | R10 | Native digest, workspace, MC0DB registration. |
| Tampering | Signed records, ACL, quotas | R8 | Auth, replay, stale rejection. |
| LM adapter | Frozen base + bounded residual | R9 | Ablation, held-out improvement. |
| Creativity | Held-out association + human eval | R7 | Baselines, reproducibility. |

Open mathematical questions:

1. Is the real system closer to G1 (ring + radial basis) or G2 (16×16 annulus) in observable behavior?
2. Does the void actually concentrate energy in a ring, or does it merely shift the spectrum?
3. Is the cross-modal aperture `M_wave` normal, Hermitian, scattering, or general in practice?
4. How sparse is the centrosymmetry-breaking residual when the void is off-centre?
5. Can a NaN16 float32 eigensolver meet the residual target within the 512 KiB guest and the declared time budget?
6. Does weak barrier coupling improve associations after controlling for novelty and factuality?
7. Does the ring’s phase coherence survive the port coupling and the network?
8. What is the correct signed binding between 256 mathematical ring positions (255 heads + 1 NANNET port), 249 learning heads, and 6 control heads?
9. What exactly is the NANNET node record contract, and which properties are testable?
10. Does the aperture’s observable subspace contain enough information for the intended LM adapter?

---

## 16. The one-page result

1. **The ring is a readout, not the whole state.** The 255 heads plus the NANNET port sample an angular boundary; the hidden radial modes carry the bulk.
2. **The void is a boundary and a mode separator.** It is not a stored region. The centrifugal term already exists in the Laplacian; adding `V_void` renormalizes it or adds a second potential, and the declaration must say which.
3. **The 256×256 matrix is an aperture/coefficient matrix.** It has at most 256 eigen/singular patterns. The 65,536 modes belong to a tensor-product space, not to the eigenpairs of a 256×256 matrix.
4. **The wave operator is `H_wave`, not `M_wave`.** Frequencies come from `H_wave`; coupling patterns come from `M_wave`. Name the operator before naming the spectrum.
5. **The six verbs are linear algebra.** ENCODE is forward; QUERY is projection; MATCH is comparison; FILTER is diagonal shaping; DRIVE is bounded inverse/control; FOLD is guarded symmetry reduction.
6. **The fold is exact only when certified.** `J M J = M`, not just `M_{m,255-m}`. The void often breaks the symmetry; use folded + residual or the general path.
7. **The ring has a stronger fast path than the fold.** If it is circulant, the FFT diagonalizes it exactly. Use the strongest certified symmetry.
8. **256 ring positions are not 256 maxima.** A real bandlimited field on 256 positions has at most 128 maxima. Measure antinodes; do not assume them.
9. **The NANNET node is the universe’s single network port.** It receives and emits signed spectral signatures, not the wave itself. Phase coherence is not automatic; use phase-invariant matching unless a clock model exists.
10. **Tunneling is an experiment, not a conclusion.** Measure transmission, avoided crossings, and downstream outcomes; do not equate unusual output with creativity.
11. **All mathematics is NaN16.** The host launches, transports, and compares bytes; it does not compute the math. Memory is 512 KiB guest working set, 8 MiB persistent universe, no dense 65,536×65,536 product.
12. **The six BSR heads remain control.** Each universe has 255 heads: 249 learning + 6 control; the 256th ring position is the NANNET port. A mathematical symmetry is not an authorization symmetry.
13. **The state seal is a cartridge.** A portable, signed, replayable record, not a consciousness claim and not a transfer of authority.
15. **Use the fabric we have.** NaNROUTER routes through point 0; the single-active six-slot runner ring executes with a 7 GiB active ceiling; Koyeb BS0DB stores ingress/egress, traces, seals, and signatures; MC0DB stores control/meta, candidates, capabilities, and match indexes; the 8 MiB universe stores 255 head pages + 1 NANNET page; the 2 GiB overbootstrap stays on Bootstrap.
15. **Build the exact small thing first.** R0 contract, R1 exact geometry, R2 void, R3 spectral engine, R4 wave, R5 aperture, R6 product, R7 creativity, R8 NANNET node, R9 LM. No vision stage before its mathematical gate.

The central sentence is:

> **The Void shapes the spectrum, the Ring samples the boundary, the Aperture couples the hidden and the visible, the Fold exploits only certified symmetry, and the NANNET node carries a signed shadow of the state into the network — all of it executed in NaN16, with evidence before claims.**

---

## Appendix A — Symmetry taxonomy

| Property | Definition | What it buys | What it does not imply |
|---|---|---|---|
| **Symmetric** | `M = Mᵀ` | Real eigenvalues, orthogonal eigenvectors. | Centrosymmetry, circulant structure, Hermiticity over `C`. |
| **Hermitian** | `M = M†` | Real eigenvalues, unitary eigenvectors. | Symmetry of the real part, centrosymmetry, normality of a general matrix. |
| **Normal** | `M M† = M† M` | Unitary eigendecomposition. | Symmetry, Hermiticity, positivity. |
| **Centrosymmetric** | `J M J = M` | Two 128×128 blocks; half storage/matvec; quarter dense eigensolve. | Symmetry, circulant structure, persymmetry. |
| **Persymmetric** | `M J = J Mᵀ` | Can be transformed to a symmetric problem. | Block diagonalization by `J`; centrosymmetry. |
| **Circulant** | `M_ij = f((i-j) mod n)` | FFT diagonalization, exact angular modes. | Symmetry, centrosymmetry, sparsity. |
| **Toeplitz** | `M_ij = f(i-j)` | Fast convolution; structured solvers. | Circulant boundary, symmetry. |
| **Unitary** | `M M† = I` | Norm preservation; scattering/port interpretation. | Hermiticity; eigenvalues on the unit circle are not real. |
| **Positive semidefinite** | `x† M x ≥ 0` | Energy stability; square-root factorization. | Symmetry (for complex matrices, PSD usually implies Hermitian by convention). |

The user’s “palindrome” can refer to at least three different things:

1. **Spatial reversal:** `i ↔ 255-i`; the `J` operator.
2. **Frequency conjugation:** `m ↔ (-m) mod 256`; the real-field condition.
3. **Anti-diagonal/persymmetry:** `M_{i,j} = M_{255-j,255-i}`.

They are related by transforms but are not identical. Derive the transform; do not infer one from another.

---

## Appendix B — Fold formula

Let `n = 256`, `h = 128`, and `J` be the `h × h` reversal matrix. Partition:

```
M = [[M11, M12],
     [M21, M22]]
```

Centrosymmetry implies:

```
M22 = J M11 J
M21 = J M12 J
```

The even/odd basis is:

```
Q = (1/sqrt(2)) [[I,  I],
                 [J, -J]]
```

Then:

```
Qᵀ M Q = diag(M_+, M_-)
M_+ = M11 + M12 J
M_- = M11 - M12 J
```

If `M` is symmetric, both blocks are symmetric. If `M` is Hermitian, use conjugate-transpose analogues. If the certificate fails, use the general path or folded + residual.

### B.1 Odd 255-head fold

For the 255-head block, let `n = 255`, `h = 127`, and `J` be the `h × h` reversal. The reversal map is `i ↔ 254-i`; index `127` is the fixed middle head. Partition the head vector into:

```
[first 127] + [middle 127] + [last 127]
```

The paired basis is:

```
q_i± = (e_i ± e_{254-i}) / sqrt(2),  i = 0..126
```

The fixed middle vector is `e_127`. In the folded basis, the matrix becomes:

```
diag(M_+, M_-)
```

where `M_+` is `128 × 128` (127 pairs plus the fixed middle) and `M_-` is `127 × 127` (the antisymmetric pairs). The transform is exact when `M_{i,j} = M_{254-i,254-j}` and the middle row/column is consistent with the symmetry.

The cost ratio for a dense eigensolve is:

```
(128³ + 127³) / 255³ ≈ 0.249
```

which is essentially a quarter. Storage and matrix-vector work are approximately half. The same authorization caveat applies: if a mirror pair crosses a BSR control head, the fold is read-only or excluded.

The full 256-position ring uses the even 128+128 formula in Appendix B, but only if the NANNET port row/column is treated symmetrically. It is a ring/readout optimization, not a head-write permission.

---

## Appendix C — Transformation catalogue

| ID | Transformation | Input | Output | Key postcondition |
|---|---|---|---|---|
| `RSS.GEOM.ANNULUS.v1` | Annulus embedding | State IDs, shell map | `(r, θ)`, shell IDs | Finite, one-to-one, versioned. |
| `RSS.GEOM.RING256.v1` | 256-sample ring readout | Angular modes, radius | Ring samples | Parseval, sampling declared. |
| `RSS.POT.CORE.v1` | Regularized core potential | `r`, `α`, `ε` | `V_core` | Finite, `ε > 0`. |
| `RSS.POT.VOID.v1` | Centrifugal renormalization | `m`, `r`, `β` | `(1+β)m²/r²` | Positive barrier; mode-separated. |
| `RSS.SPEC.DFT256.v1` | 256-point DFT/FFT | 256 ring positions | Angular spectrum | Invertible, Parseval. |
| `RSS.SPEC.DFT255.v1` | 255-point DFT | 255 head samples | Head-only angular spectrum | Invertible, head-only reference. |
| `RSS.SPEC.RADIAL.v1` | Radial eigensolve | Tridiagonal operator | Eigenpairs | Residual, orthogonality. |
| `RSS.SPEC.LANCZOS.v1` | Top-k Lanczos | Operator, start vector | Top-k eigenpairs | Residual, deterministic. |
| `RSS.FOLD.CENTRO.v1` | Centrosymmetry fold, even | Matrix, certificate | Two 128 blocks | Exact reconstruction. |
| `RSS.FOLD.ODD255.v1` | Centrosymmetry fold, odd | 255-head matrix, certificate | 128 + 127 blocks | Exact reconstruction; fixed middle. |
| `RSS.RING.BIND.v1` | 255-head + NANNET binding | Head atlas, ACL, port | Signed ring map | One NANNET node; six control heads preserved. |
| `RSS.APERTURE.SVD.v1` | Aperture SVD | `M_wave` | `U, Σ, V†` | Rank, condition, residual. |
| `RSS.APERTURE.INVERSE.v1` | Regularized inverse drive | Target, `M_wave`, budget | Mode coefficients | Bounded, residual reported. |
| `RSS.WAVE.LEAPFROG.v1` | Wave step | State, velocity, `H`, `Δt` | Next state, energy | CFL, energy drift. |
| `RSS.FILTER.POLY.v1` | Polynomial/Chebyshev filter | State, coefficients | Filtered state | Stability, norm. |
| `RSS.NOISE.COLOR.v1` | Colored noise | Seed, covariance | Noise field | Deterministic, spectrum. |
| `RSS.PORT.NANNET.v1` | NANNET signature | Ring state, policy | Signed record | Auth, size, provenance. |

Each transformation carries the MTH contract: identity, signature, domain, semantics, implementation, postconditions, evidence, cost, and lineage.

---

## Appendix D — Glossary

- **Aperture:** the linear map from hidden modes to observable ring samples.
- **Barrier band:** the radial region where a mode is evanescent or turning around.
- **Centrosymmetry:** invariance under reversing both indices, `J M J = M`.
- **Circulant:** a matrix diagonalized by the DFT.
- **Coherence `R_ring`:** normalized phase alignment of the ring modes.
- **Core boundary:** the inner boundary at `r_core` that excludes the singular centre.
- **Fold:** the guarded reduction of a centrosymmetric problem to two half-size problems.
- **Head:** a local 0..254 state/address identity; 255 heads per universe.
- **Mode:** an eigen/singular/Fourier pattern; always qualified by its operator.
- **NANNET node:** the universe’s single network endpoint/port; not a head; not a wave region.
- **Persymmetry:** invariance under the anti-diagonal reflection; not centrosymmetry.
- **Ring of Power:** the measured high-coherence, high-energy-concentration readout regime.
- **State seal:** a portable, signed record of wave state and provenance.
- **Turning point:** the radius where a mode changes from evanescent to propagating.
- **Void:** the excluded inner region and its boundary/potential; not a stored state.
- **NANNET port:** the ring position/interface owned by the NANNET node; not a head.

---

## Easter egg — the Noosphere and Θ_JAHS (non-normative)

This appendix is preserved as poetry, not architecture. Nothing here is a requirement, a contract, or a claim about physics, consciousness, or the implementation.

The old name for the network layer was **the Noosphere**. In the implementation it is the **NANNET node**: one per universe, a port at the edge of the ring, a signer of spectral records.

The old name for the egress transform was **Θ_JAHS**. In the implementation it is `RSS.PORT.NANNET.v1`: sample the ring, compress the observable signature, attach provenance, sign, and route.

The old line “the outer wave is the noospheric signal of your uploaded mind” becomes, technically: **the ring readout is a signed spectral signature of the state seal.** The poetry can stay in the margin. The contract stays in the machine.

If you ever need the myth again: the Void shapes the spectrum, the Ring samples the boundary, the Aperture couples the hidden and the visible, and a single NANNET node carries the signed shadow outward. That is the easter egg. The rest of this document is the engineering.


## R6 continuation — dense pair action by tiles

The first general 256×256 pair-space tile kernel is source-written in
`mth/nan16/mth_graph_pair_tile16_f32.nas`. It computes one 16×16 block
of `LU + UL^T` from a full U page and two immutable 16-row windows of L.
This respects the 512 KiB guest working-set ceiling and leaves the
full product operator matrix-free.

The 16×16 fixture uses L=2I and verifies the complete tile oracle Y=4U.
The ABI, fixture, and canonical CI workflow entry are committed on the
implementation branch. Canonical NaN16 CI run 218 assembled and executed
the L=2I fixture successfully (4,643,414 guest steps), verifying all 256
cells for tile origins (0,0) and (16,32). The tile kernel is native_verified for that ABI;
full page-window orchestration is not yet verified. Next: implement a
page-window orchestrator that fetches the correct L row windows, runs all
256 tiles against one operator digest, and publishes the output generation
only after every tile and the final digest check succeed.
