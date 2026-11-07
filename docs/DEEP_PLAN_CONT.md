# DEEP PLAN CONTINUATION — MTH System v1 and the 255 + 1 + NANNET0 Architecture

**Status:** continuation and integration plan; the implementation catalog below is verified as of 2026-11-07.
**Parent plans:** `docs/game_plan_deep.md`, `docs/game_plan_foundations.md`, `docs/GAME_PLAN_MTH.md`.
**Implementation ledger:** `docs/IMPLEMENTATION_TODO.md`.
**Evidence ledger:** `docs/R10_IMPLEMENTATION_EVIDENCE.md`.
**Mathematical linker plan:** `docs/GAME_PLAN_::.md` (NaN Mathematical Linker, validity engine, leaves, NMP, 2 MiB integration).
**Guest-budget update:** GLT is now 2 MiB and adjustable; the checked-in default is 2 MiB, with 1 MiB/512 KiB compatibility modes. GLT page-limit enforcement remains separate.
**Canonical language:** NaN16, assembled by `nasm0`, executed by `n16i` or the native NaN16 kernel.
**Canonical math owner:** MTH inside the one NaNLMind universe.
**Canonical routing/control owner:** NaNROUTER.
**Runtime constraint:** the `NANROUTER-0..5` / `MC0:0/R0..R5` runner ring has a **7 GiB active-memory ceiling**, runs **exactly one active slot at a time**, and cycles slots to keep the service alive 24/7. One logical `NANNET0` node per universe remains separate.

This document is not a claim that the system is finished. It catalogues what is actually implemented, synthesises the three parent plans into one continuation architecture, and defines the next integration work packets. It does not create a second universe, a second runner ring, a second task ledger, or a second owner of state.

---

## 0. Executive synthesis

The project has crossed an important boundary: it is no longer only a plan. There are **63 native MTH kernels with fixtures**: 60 pass in the local harness and all 61 fixtures pass canonical CI run 42405010545 (124 steps). The 1 MiB text-loader execution is CI-verified; GLT page-limit enforcement remains a separate pending gate. There is also a working BS0DB/MC0DB control/evidence plane and 540 Python tests.

What exists is a strong **mathematical kernel collection**. What does not yet exist is a complete **MTH system**: one registry that names every operator, one planner that composes them, one executor contract that routes them through the single-active runner ring, one paged-memory model that lets 256×256 and 255×255 operators live across durable pages without pretending they are one flat array, and one end-to-end evidence path from a plan to a result to a promotion decision.

The continuation architecture is therefore:

> **MTH System v1 = Registry + Plan + Executor + Evidence + Paged Memory + NANNET0 + LM Adapter.**

The 33 existing kernels are the arithmetic core. The next work is integration, not another catalogue explosion.

The central memory correction is:

> **A dense 256×256 float32 matrix is only 256 KiB. It fits. A dense 65,536×65,536 product operator is 16 GiB and does not fit. The 7 GiB is the active runner ceiling for versioned pages, caches, checkpoints, and experiment corpora — not a flat product workspace, and not six simultaneous 7 GiB runners.**

The 255 + 1 rule remains:

```
256 ring positions = 255 head positions + 1 NANNET0 port
8 MiB universe     = 255 head pages + 1 NANNET0 page
```

`NANNET0` is the universe’s single network node/port. It is not a head. `NANROUTER-0..5` are six **runner slots**, not six shards, not six nodes, and not six simultaneous 7 GiB processes. Only one slot is active at a time.

---

## 1. Current implementation catalogue

### 1.1 Native kernels

| Family | Implemented | Evidence |
|---|---|---|
| NaN word / Boolean / integer | Boolean transforms, class rotation, bitwise, shifts, multiply, divide, double-endian codec, U32 vector add | Stage 0 and arithmetic fixtures |
| Complete graph | K256 U16 Laplacian, K255 head-only Laplacian | Native + CI |
| Ring geometry | C255 head ring, C256 ring, 255+1 port assembly | Native + CI |
| Sparse graph | unweighted Q16.16 Laplacian, weighted CSR v2, energy, components | Native + CI |
| Void | regularized inverse-square float32 potential | Native + CI |
| Fold / symmetry | 256/255 fold vectors, 128×128 certificate, 16×256 streaming 256 certificate, 15×255 streaming 255 certificate | Native + CI |
| Spectral | 256/255-point DFT, 128×128 power iteration, 128/256 SVD top pair, 128/256 matvec, 16×256 block matvec, 16×256 streaming certificate | Native + CI (1 MiB full 256 pending) |
| Wave | velocity-Verlet step, step energy, harmonic energy, damped energy, C256 graph-H energy | Native + CI |
| Coupling / creativity primitive | two-region coupling, transmission metric, two-level avoided-crossing spectrum, 128 phase coherence | Native + CI (new two-level/phase pending CI) |
| Pair / product | K256 closed-form 256×256 pair, full 128×128 pair, rank-1 pair, rank-1 low-rank add, native-verified 16×16 dense pair-tile reference, bounded K16 streaming pair-tile accumulator | Native + CI |
| Vector / match | dot, norm, axpy, cosine similarity | Native + CI |
| Adapter | 128/256-dimensional `h + beta*C*u` residual, 256↔128 ENCODE/DECODE | Native + CI (256-block pending CI) |

### 1.2 System/control plane

| Component | Status |
|---|---|
| `runner_riddle/wave_store.py` | BS0DB/MC0DB jobs, leases, operator/capability registry, traces, seals, signatures; 12 tests |
| `runner_riddle/wave_service.py` | authenticated submit/worker/admin facade; 13 tests |
| `runner_riddle/wave_http.py` | standalone authenticated HTTP adapter; 12 tests |
| `runner_riddle/mth_registry.py` | MTH descriptor registry/planner; 26 tests |
| `runner_riddle/wave_ring_scheduler.py` | single-active six-slot runner ring, 7 GiB ceiling, cycle/handoff; 27 tests |
| `runner_riddle/point0_bridge.py` | point-0 NaN16↔binary↔NaN16 bridge and active-slot router; 35 tests |
| `runner_riddle/mth_system.py` | MthSystem runtime facade over registry/store/service/scheduler; 11 tests |
| `runner_riddle/wave_node.py` | one NANNET node per universe; 8 tests |
| `runner_riddle/wave_aperture.py` | aperture role/decomposition descriptor; 9 tests |
| `runner_riddle/wave_adapter.py` | R9 adapter contract; 7 tests |
| `tools/register_wave_capabilities.py` | registers 63 kernels into MC0DB |
| `spec/wave-capabilities.json` | 61-kernel capability manifest |
| `spec/ring-255.json` | C255 CSR, port policy, 255+1 page map |
| `.github/workflows/mth-native-contract.yml` | 124 steps, 61 fixtures; canonical CI PASS (1 MiB page-limit enforcement pending) |

### 1.3 Evidence baseline

```
60/60 locally runnable fixtures pass
60/60 local fixtures pass; 61/61 total fixtures pass canonical CI run 42405010545 (124 steps); 540/540 Python tests pass
GLT-enforced 1 MiB page-limit verification remains pending
```

### 1.4 Open gates, verbatim from the ledger

| Area | Open item |
|---|---|
| R2 | radial tridiagonal layout, descriptor-level inner Dirichlet/Robin boundary convention, and radial energy/localization native PASS |
| R3 | 256 SVD top pair/top-2, stable top-k, and bounded Lanczos native PASS; residual/orthogonality covered by fixtures; 128/255/256 certificates done |
| R4 | bounded DRIVE source and CFL/λ_max guard native PASS; long-run paged graph trace remains open |
| R5 | full aperture SVD/top-k, reachability, and colored noise native PASS; QUERY/MATCH/FILTER/DRIVE composition and capacity-vs-SNR experiment remain open |
| R6 | bounded K16 pair-tile native_verified; 256-tile page-window/atomic-publication orchestrator implemented with 31 tests; default MTH guest budget 1 MiB; native full-grid driver still open; K256 closed form done |
| R7 | two-level spectrum, phase metric, native avoided-crossing sweep, and held-out protocol harness with explicit gates done; real-model experiment remains gated |
| R8 | Point-0 HTTP ingress, offline live preflight, and signed-volume gate done; live Koyeb/NANNET0 deployment blocked on credentials |
| R9 | full 256×256 ENCODE/DECODE and adapter residual done; frozen-base ablation harness done; real LM/data ablation blocked |
| R10 | production digest registration, capability promotion |

---

## 2. What “complete MTH system” means

“Complete” does not mean every mathematical theorem, every operator, or every model. It means a closed, reliable, composable core plus a mechanism for safe extension. MTH System v1 is complete when:

1. **Every operation is representable** by a typed descriptor with a stable identity and version.
2. **Every operation is executable** by a native NaN16 implementation with explicit inputs, outputs, precision, workspace, and status.
3. **Every operation is composable** into a validated directed acyclic plan.
4. **Every operation has a domain** and rejects invalid shapes, ranges, precisions, and aliasing.
5. **Every result has evidence**: digest, residual/error bound, step count, runner/kernel identity, and status.
6. **Every execution is bounded** by fuel, workspace, lease/epoch, and cancellation rules.
7. **Every optimization is a candidate** that must pass the same semantics and evidence gates.
8. **No host language implements MTH mathematics.** The host only schedules, transports, pages, hashes, and validates.

### 2.1 MTH System v1 layers

| Layer | Responsibility | Existing anchor |
|---|---|---|
| L0 | NaN16 machine, gated word/instruction contract | NaN0S |
| L1 | MTH descriptor/registry/evidence | implemented (`mth_registry`, 26 tests) |
| L2 | exact scalar/bit/integer/vector | existing kernels |
| L3 | graph, ring, void, energy, components | existing kernels |
| L4 | spectral, DFT, fold, certificate, power iteration | existing kernels |
| L5 | wave dynamics, energy, damping, drive | existing kernels |
| L6 | aperture, pair, low-rank, adapter | existing kernels |
| L7 | BS0DB/MC0DB, jobs, leases, capabilities, NANNET node | implemented (`WaveStore/WaveService/WaveNode`) |
| L8 | HTTP/NANNET transport and federation | HTTP adapter built; live federation to build |
| L9 | LM adapter and held-out evaluation | adapter contract + 128 residual; ablations to build |

### 2.2 The operator model

Every MTH operation becomes an `MthKernelDescriptor`:

| Field | Meaning |
|---|---|
| `kernel_id` | Stable name, e.g. `mth.ring256.laplacian.f32` |
| `version` | Semantics version |
| `source_digest` / `fixture_digest` | SHA-256 of the NaN16 source and fixture |
| `precision` | exact/float32/Q16.16/complex |
| `shape` | Typed input/output shape |
| `workspace_words` | Bounded caller/runner workspace |
| `status` | specified → source_written → native_verified → promoted |
| `ci_verified` | Whether the canonical workflow ran |
| `steps` | Measured fixture step count |
| `tags` | graph, wave, spectral, fold, aperture, adapter, etc. |

A plan is a `MthPlan`:

```
typed inputs
  -> step 1: kernel A
  -> step 2: kernel B (depends on A)
  -> step 3: kernel C
  -> typed result + evidence
```

The plan validator checks:

- every kernel exists;
- every kernel is verified at the required evidence level;
- workspace is within the runner/guest budget;
- dependency order is respected;
- no duplicate step names;
- precision/shape handoff is compatible;
- no candidate self-promotes.

### 2.3 The execution path

```
NANNET0 / universe
  -> point 0 (BS0:0 / BSR0) stable ingress
  -> NaN16 -> binary -> NaN16 bridge
  -> active MC0:0/R0..R5 slot (one at a time)
  -> WaveService / NaNROUTER authorization
  -> MC0DB job + lease
  -> native NaN16 kernel / plan step
  -> BS0DB trace/seal/signature
  -> NaNLMind validation / ledger
  -> promotion candidate
```

No private runner dispatch. No second lease ledger. No direct master-cache write. No host math.

---

## 3. Unified mathematical object model

### 3.1 The five matrices must stay distinct

| Symbol | Shape | Meaning | Do not confuse with |
|---|---|---|---|
| `W_rel` | 256×256 | Directed relation matrix | Symmetric Laplacian |
| `L_graph` | 256×256 | Symmetric graph Laplacian | `W_rel` |
| `H_wave` | 256×256 ring; 255×255 head-only | `c²L + V_core + V_angular` | `M_wave` |
| `M_wave` | 256×256 ring; 255×255 head-only | aperture/coefficient/coupling matrix | wave operator |
| `U_wave` | 256×256 coefficients; matrix-free | product-space state | 256×256 eigenproblem |
| `A_ring` | 256 samples | boundary readout | head identity |
| `A_cross` | 256×256 | radial-to-angular aperture | 65,536 eigenpairs |

A 256×256 matrix has 256 eigen/singular patterns. The 65,536 product modes belong to the tensor-product state, not to the matrix’s eigenpairs.

### 3.2 Shape and storage accounting

| Object | Guest words (8 B) | Raw packed f32 | Guest pages (32 KiB) | 2 MiB fit |
|---|---:|---:|---:|---|
| 255-vector | 255 | ~1.0 KiB | 1 | yes |
| 256-vector | 256 | 1 KiB | 1 | yes |
| 255×255 head matrix | 65,025 | 254 KiB | 16 | yes, with scratch |
| 256×256 ring matrix | 65,536 | 256 KiB | 16 | yes, with scratch |
| 256×256 matrix + eigenvectors | 131,072 | 512 KiB | 32 | yes, 1 MiB scratch |
| 256×256 complex float32 | 131,072 | 512 KiB | 32 | yes, 1 MiB scratch |
| 256×256 Q16.16 | 65,536 | 128 KiB | 16 | yes |
| 128×128 pair state | 16,384 | 64 KiB | 4 | yes |
| product state 256×256 | 65,536 | 256 KiB | 16 | yes; double buffer =32 pages |
| full 256 pair U+L+output | 196,608 | 768 KiB | 48 | yes, 16 pages spare |
| full product operator | 65,536² = 4,294,967,296 | 16 GiB | 1,048,576 | **never dense** |

Admission uses **8-byte guest words**, not raw packed float32 bytes. The raw column is payload size only. The 7 GiB active-runner ceiling does not change the last row: a 65,536² operator is 16 GiB of raw float32 payload and **32 GiB in guest words**, so it is never dense. It must remain matrix-free, low-rank, block-sparse, or tensor-network.

### 3.3 The wave equation, in the continuation language

```
ü + 2γu̇ + H_wave u = B f(t)
H_wave = c² L_graph + V_core + V_angular
V_angular = (1 + β) c² m² / r²      (2D angular sector m)
```

The void is a **core boundary plus a mode-dependent centrifugal renormalization**, not a second graph. The ring is the readout surface. The NANNET0 node is the network port.

### 3.4 The aperture

```
M_wave = U Σ V†                  (general)
M_wave = P Λ P†                  (normal/Hermitian)
y = M_wave x                     (filter/encode)
z = P† x                         (query)
match = cosine(s(x), s(y))       (phase-invariant)
drive = regularized inverse      (bounded)
fold = guarded symmetry          (certified)
```

The aperture’s role determines the decomposition. Do not force a Hermitian eigendecomposition onto a directed/scattering aperture.

---

## 4. Memory architecture: single-active NaNROUTER-0..5, NANNET0, and paged 256×256

### 4.0 Guest budget update: 1 MiB baseline, 2 MiB owner target

The 1 MiB implementation baseline is:

```
1 MiB = 131,072 NaN16 words = 32 pages of 32 KiB
```

**Owner update (2026-11-07):** GLT is now reported at **2 MiB, adjustable for
guest words**. The target is `2 MiB = 262,144 words = 64 pages of 32 KiB`.
The checked-in default is 2 MiB; 1 MiB and 512 KiB remain compatibility test modes. See `docs/GAME_PLAN_::.md` §2 and §16. At 2 MiB,
the full 256 `U+L+output` pair (196,608 words) becomes guest-feasible, while
the 65,536² dense product remains forbidden (32 GiB at 8-byte NaN words).

The 1 MiB design target and its consequences:

```
1 MiB = 131,072 NaN16 words = 32 pages of 32 KiB
```

The old 512 KiB / 65,536-word evidence remains historical. Kernels and fixtures that exceed the old limit are marked **pending 1 MiB toolchain** until the canonical NaN16 harness executes them. The active-runner 7 GiB ceiling and durable-page model are unchanged.

Immediate consequences:

| Object | Old 512 KiB | New 1 MiB |
|---|---|---|
| 256×256 float32 matrix | fits alone | fits with vectors/scratch |
| 256×256 matrix + eigenvectors | tight/over | 1 MiB guest; fits at 2 MiB with ~1 MiB scratch |
| 256×256 complex float32 | full 1 MiB guest | fits at 2 MiB with ~1 MiB scratch |
| full 256 matvec A+x+y | would not fit with code | 66,048 words, fits |
| full-U pair-tile reference (73,990 words) | not dispatchable | **fits** |
| U+L+output full pair (196,608 words) | over | still over at 1 MiB; **fits at 2 MiB** |
| 65,536² dense product | 16 GiB | still forbidden |


### 4.1 What NANROUTER-0..5 is: a single-active runner ring

`NANROUTER-0..5` / `NR0..NR5` and `MC0:0/R0..R5` name the same six-slot runner ring. It is **not** six shards and **not** six parallel runners.

| Property | Policy |
|---|---|
| Slots | six logical identities, `R0..R5` / `NR0..NR5` |
| Active slots | **exactly one** at any instant |
| Standby slots | five, no live working set |
| Active memory ceiling | **7 GiB at any instant** |
| Cycle | active slot drains leases, checkpoints, releases memory, then the next slot activates |
| Purpose | 24/7 availability with a clean handoff, not six-way parallel execution |
| Persistent state | 8 MiB universe + BS0DB/MC0DB + optional signed durable pages |
| NANNET0 | one logical network node per universe, separate from the ring |

Clients do not address `R0..R5`. They address the stable **point 0** ingress (`BS0:0` / `BSR0`). Point 0 translates NaN16 frames to binary transport and back, then routes to whatever slot is currently active. The active slot is an internal detail.

The six slots are not six math authorities. They are one service with a rotating execution identity.

The scheduler is implemented in `runner_riddle/wave_ring_scheduler.py` (27 tests). The handoff sequence is mandatory:

```
active slot
  -> stop accepting new leases
  -> finish or release current leases
  -> write checkpoint + trace digest
  -> release active memory and page cache
  -> mark standby
  -> next slot activates with a new epoch
```

A slot must not activate while the previous slot has live leases, live memory, or an uncommitted checkpoint. A standby slot must not hold a dense matrix, a live page cache, or a private copy of canonical state.

`NANNET0` is separate:

- exactly one logical NANNET node per universe;
- not a runner slot;
- not a shard;
- not a head;
- the only ingress/egress port;
- registered in MC0DB and bound to ring position 255.

The six slots are not NANNET0 nodes. The six slots are not six heads. The six slots are not six storage shards.

### 4.2 What the 7 GiB ceiling actually buys

A 256×256 float32 matrix is only 256 KiB. The 7 GiB active ceiling is useful for:

- the active runner’s page cache and operator version cache;
- checkpoint and replay buffers;
- 255×255 head-only and 256×256 ring variants;
- float32, Q16.16, and complex-split representations;
- trace/seal/signature staging before durable commit;
- paged 256×256 power/SVD iterations;
- tiled 256×256 pair actions;
- LM ablation checkpoints and source packs.

It is **not** a reason to materialize a 65,536² product operator. It is also not six times 7 GiB; the other five slots are standby.

A rough capacity analogy, ignoring overhead and version metadata:

| Object | Size | 7 GiB active budget equivalent |
|---|---:|---:|
| dense 256×256 float32 | 256 KiB | ~28,600 versions |
| dense 255×255 float32 | 254 KiB | ~28,900 versions |
| dense 256×256 complex float32 | 1 MiB guest | ~7,150 versions at a 7 GiB ceiling (raw 512 KiB) |
| dense 65,536² float32 | 16 GiB | **less than half of one copy** |

This is why the product space must be matrix-free or low-rank. The 7 GiB ceiling buys versioning, caching, and experiments, not a dense product operator.

### 4.3 Page and tile model

| Unit | Size | Use |
|---|---:|---|
| Universe page | 32 KiB | 255 head pages + 1 NANNET page; 8 MiB per universe |
| 16×256 block | 4,096 words | 256 matvec row-block, 256 certificate mirror-block |
| 16×16 tile | 256 words | matrix tiling, block SVD, cache-friendly products |
| 128×128 block | 16,384 words | pair/power prototypes |
| 256×256 matrix | 65,536 words | one dense matrix only, no full product |
| 65,536² operator | forbidden dense | matrix-free/low-rank/tensor |

The 256×256 matvec is **16 block calls**, not one 65,536-word kernel:

```
for block b in 0..15:
    A_b = rows 16b .. 16b+15 of A       (16×256)
    y[16b:16b+16] = A_b x
```

The 256×256 centrosymmetry certificate is likewise **16 streaming block calls**:

```
for block b in 0..15:
    A_b      = rows 16b .. 16b+15 of A
    mirror_b = rows 255-16b .. 240-16b in reverse order
    mismatch += compare(A_b[k,j], mirror_b[k,255-j])
```

The 255-head case is odd: one fixed middle head and 127/128 blocks. It must not be forced into the even 128+128 fold.

### 4.4 What to keep dense, what to page, what to factor

| Object | Policy |
|---|---|
| 255×255 head operator | dense is 254 KiB; keep dense for reference, page for versions |
| 256×256 ring operator | dense is 256 KiB; keep dense for reference, block/paged for large plans |
| complex 256×256 | fits under 1 MiB with scratch; split/paged for large plans |
| 256×256 power/SVD | block matvec; keep basis vectors and top-k, not full dense workspace |
| 256×256 pair state | block/tile; do not materialize the 256²×256² operator |
| 65,536 product state | one 256 KiB buffer; double buffer tight; use Q16.16 or paging |
| 65,536² operator | never dense; matrix-free Kron / low-rank / tiled |
| eigenbasis versions | durable pages (BS0DB/MC0DB/optional signed volume), content-addressed, generation-checked |

### 4.5 Page and runner-ring lifecycle

Every page record needs:

- `universe_id`, `page_id`, `kind`, `shape`, `precision`;
- content digest and source/operator digest;
- generation and previous digest;
- producer/runner and lease/epoch;
- ACL and retention class;
- optional signature.

Rules:

- a page is immutable once committed;
- a new version gets a new digest;
- stale generations are rejected;
- a runner cache is not canonical;
- BS0DB/MC0DB are durable control/evidence, not the universe;
- only the active runner holds live pages; standby caches are sealed or evicted;
- handoff requires checkpoint digest, lease drain, and memory release;
- every handoff also carries the mandatory **JAHS** ("Just A Handoff Seal") domain separator and passes the native `mth_jahs_gate` seal check; `MthSystem.lease` rejects a snapshot without it;
- no secrets, no dense 65,536², no 2 GiB map copies on Android/peers.

### 4.6 NANNET0 binding

One logical NANNET0 node per universe:

| Field | Meaning |
|---|---|
| `universe_id` | The one universe owning the node |
| `node_id` | Stable endpoint identity |
| `node_point` | 1..255 NANNET namespace; never a head index |
| `public_key_fingerprint` | 64 lowercase hex |
| `generation` | Monotonic binding generation |
| `status` | declared / active / degraded / revoked |
| `route` | Signed route envelope; empty when revoked |

Rules:

- exactly one NANNET0 per universe;
- no NANNET0 is a head, storage shard, or runner slot;
- NANNET0 is bound to ring position 255;
- NANNET0 never receives a learning ACL;
- the six-slot runner ring is `MC0:0/R0..R5`, with one active slot, not six NANNET0 nodes.


### 4.7 Point 0: the stable ring ingress

The runner ring is not addressed slot-by-slot. It is addressed through **point 0**:

```
client NaN16 frame
  -> point 0 / BS0:0 / BSR0
  -> NaN16 -> binary transport envelope
  -> active runner slot (R0..R5)
  -> NaN16 execution
  -> binary result envelope
  -> point 0
  -> NaN16 result
```

Rules:

- the public address is stable; it does not contain the active slot;
- the resolver asks the single-active scheduler for the current slot and epoch;
- the active slot can change behind point 0 without renumbering clients;
- a stale slot/epoch envelope is rejected;
- point 0 is the only ring ingress/egress; direct R0..R5 addressing is an internal control path only;
- point 0 does not compute mathematics; it frames, translates, authenticates, and routes;
- `NANNET0` is the universe node; point 0 is the runner-ring ingress used by that node;
- no two slots receive point-0 work at once.

The point-0 bridge is implemented in `runner_riddle/point0_bridge.py` (10 tests). The scheduler chooses the active slot; the bridge only encodes/decodes and enforces the epoch.

| Object | Identity | Role |
|---|---|---|
| Point 0 | `BS0:0` / wire `BSR0` | Stable runner-ring ingress/translation |
| Active runner slot | `MC0:0/R0..R5` | Internal execution identity |
| NANNET0 | one logical node per universe | Universe network endpoint |
| Head | local 0..254 | Wave/state identity |
| Durable page | content digest | Versioned storage, not an address |

Point 0 is not NANNET0, not a runner slot, and not a head. NANNET0 may use point 0 as its ring ingress; the active slot remains internal.



---

## 5. The 256×256 / 255×255 + NANNET0 integration

### 5.1 The exact convention

```
255 heads + 1 NANNET0 node = 256 ring positions
256×256 ring operator = 255 head block + port row/column
255×255 head-only operator = the authorization-safe block
product ring state = 65,536 coefficients
product head state = 65,025 coefficients
```

The 511 difference is the NANNET0 port coupling modes, not extra heads.

### 5.2 Dense 256×256 is allowed

The user’s instinct to “leave some detail out if the 256×256 dense” is half right and half unnecessary:

- **256×256 dense is small** and should be kept exact when it fits: 256 KiB = 8 pages.
- **255×255 dense** is 254 KiB and also fits.
- **256×256 complex float32** is 1 MiB in guest words (raw payload 512 KiB); it fills a 1 MiB guest and fits at 2 MiB with ~1 MiB scratch; it can still be split/paged for large plans.
- **65,536² dense** is the object that must never be materialized.

So: keep the 256×256 aperture/wave operator dense for reference and small experiments; use block/tiled/paged paths for larger plans; use matrix-free/low-rank for the product space. Do not degrade the 256×256 correctness just to save memory.

### 5.3 256×256 block matvec

New block kernel:

```
mth_matvec256_block16(A_block, x, y_block)
A_block: 16×256 float32
x:       256 float32
y_block: 16 float32
```

Sixteen calls with the same `x` and successive row blocks produce the full 256×256 matvec. A full 256×256 matvec also fits the 1 MiB target (A+x+y ≈ 66,048 words); the 16-block form remains the bounded/paged path for multi-tenant and >1 MiB plans.

### 5.4 256×256 streaming certificate

New block kernel:

```
mth_centrosymmetry_block16(A_block, mirror_block)
A_block:    16×256
mirror:     16×256, reversed mirror rows
returns:    mismatch count
```

Sixteen calls certify the full 256 ring matrix. The head-only 255 certificate needs a separate odd path.

### 5.5 256×256 aperture and power/SVD

Top-k power iteration on the aperture:

```
v ← normalize(M v)          (or M†M v for singular vectors)
λ ← Rayleigh quotient
```

The 128×128 power kernel is the prototype. The 256×256 version is a **block loop** over 16 row blocks, with two matvecs per iteration for `M†M`; it does not need a dense 65,536² workspace.

A full dense eigensolve is a separate, paged QR/Jacobi project. It is not required for the first LM adapter; top-k is enough.

### 5.6 255×255 + NANNET0

- Head-only operator: 255×255, odd fold 127+128.
- Full ring operator: 256×256 with a port row/column.
- Ring readout: 256 positions, 255 head samples + 1 port sample.
- NANNET0 node: one per universe, signed binding, not trainable.
- The port coupling is a boundary, not a head.

---

## 6. MTH System v1 API and execution contract

### 6.1 Registry

Implemented in `runner_riddle/mth_registry.py` (26 tests):

```
load(manifest)                  -> validated descriptors
lookup(kernel_id)               -> descriptor
require(kernel_id)              -> descriptor or error
resolve(tags, workspace, ci)    -> stable descriptor list
compose(plan_spec)              -> validated MthPlan
validate_plan(plan)             -> dependency/workspace/evidence checks
health()                        -> counts by status/precision/CI
```

It does not execute math. It names, validates, and plans.

### 6.2 Descriptor fields

Every kernel descriptor carries identity, version, precision, shape, workspace, source digest, fixture digest, evidence level, CI status, and tags.

### 6.3 Plan contract

A plan step declares:

- step name;
- kernel ID/version;
- typed inputs and outputs;
- dependencies;
- workspace/fuel budget;
- determinism/precision mode;
- expected result contract.

The plan validator rejects unknown/stale/unverified kernels, unsafe workspace, dependency cycles, shape/precision mismatches, and candidate self-promotion.

### 6.4 Executor contract

The runtime facade is `runner_riddle/mth_system.py` (`MthSystem`, 11 tests). The executor:

1. validates the plan against the registry;
2. submits a bounded job through WaveService/NaNROUTER;
3. leases it to the single active MC0:0/R0–R5 slot;
4. pages required inputs from durable pages into the active runner;
5. executes native kernels;
6. writes result, residual/error bound, step count, digest, and trace;
7. returns a typed result;
8. sends candidates through validation/promotion, never directly to the master cache.

### 6.5 Result contract

Every result carries:

- plan/kernel/version/digest;
- precision and rounding;
- input/output shapes;
- residual, error bound, saturation count, iterations;
- step count and runner identity;
- trace/seal/signature digest;
- status: success/invalid/overflow/nonconvergence/cancelled/budget exhausted;
- provenance.

### 6.6 Error taxonomy

| Status | Meaning |
|---|---|
| `ok` | Complete result |
| `invalid_descriptor` | Shape/type/precision mismatch |
| `bad_domain` | Domain/precondition failure |
| `overflow` | Explicit range failure |
| `saturation` | Saturation count > 0 |
| `nonconvergence` | Bounded iteration failed |
| `insufficient_workspace` | Page/scratch budget exceeded |
| `stale_generation` | Version/epoch mismatch |
| `unauthorized` | ACL/token/lease failure |
| `cancelled` | Cancellation epoch |
| `budget_exhausted` | Fuel/step limit |

---

### 6.7 Canonical plan examples

**Ring wave step plan**

```text
input u[256], v[256], dt, gamma
  -> mth.ring256.laplacian.f32 : Lu
  -> mth.negate256_f32         : a = -Lu
  -> mth.graph.wave_step.f32   : u_next, v_next
  -> mth.graph.step_energy.256 : kinetic, potential, total
output u_next, v_next, energy, trace
```

**Aperture query plan**

```text
input x[256], validated basis page
  -> mth.vector.dot256.f32     : projection scores
  -> mth.vector.norm256.f32    : normalization
  -> mth.vector.cosine256.f32  : phase-invariant match
output scores, match, confidence, residual
```

**LM adapter plan**

```text
input h[128], C[128x128], u[128], beta
  -> mth.adapter.residual.128.f32 : h + beta*C*u
  -> mth.vector.norm256.f32       : residual norm (padded/declared)
output adapter residual, evidence, ablation label
```

These are plan shapes, not implementations. The registry resolves each kernel, checks workspace/evidence, and the executor returns a typed result. No host math is allowed.


### 6.8 Point-0 bridge contract

The bridge envelope should carry:

| Field | Meaning |
|---|---|
| `magic` / `version` | Fixed framing identity |
| `request_id` | Idempotent request key |
| `nan_word_count` | Number of 64-bit NaN16 words |
| `payload_bytes` | Binary transport body |
| `payload_digest` | SHA-256 of the binary body |
| `point_zero` | Stable ingress identity (`BS0:0` / `BSR0`) |
| `active_slot` / `epoch` | Internal evidence, not part of the public address |
| `result_status` | Success / invalid / stale / unauthorized / budget |

The bridge must reject corrupt magic/version, length overflow, digest mismatch, stale epoch, no-active-slot, and direct-slot addressing. It must not decode a frame as a different type just because the bytes fit.

The public route remains point 0. The active slot is an internal scheduling detail.


## 7. Further integrations from completion points

### 7.1 From R1 ring geometry

- Add 256×256 block matvec and streaming certificate (in flight).
- Add port-aware 256 ring operator and 255 head-only submatrix.
- Add 255 odd fold + 256 even fold to the same certificate path.
- Add page-map digest to every operator descriptor.

### 7.2 From R2 void

- Add radial block descriptor and tridiagonal layout.
- Add inner Dirichlet/Robin boundary descriptor.
- Add radial energy/localization fixture.
- Add α/β sweep experiment with ring-energy metrics.

### 7.3 From R3 spectral

- Add streaming 255/256 certificate.
- Add Lanczos/top-k deflation.
- Add residual/orthogonality fixture for C256 and a non-circulant graph.
- Add 256×256 block power/SVD.

### 7.4 From R4 wave

- Add CFL/λ_max guard fixture.
- Add long-run paged C256/C255 graph trace.
- Add bounded DRIVE source and energy budget.
- Add damping sweep and phase-coherence trace.

### 7.5 From R5 aperture

- Add 256×256 block aperture SVD/top-k.
- Compose QUERY/MATCH/FILTER/DRIVE from matvec/dot/norm/cosine/axpy.
- Add observability/reachability metric.
- Add capacity-vs-SNR plan and colored-noise generator.

### 7.6 From R6 product

- Add 256×256 block pair action.
- Add rank-R low-rank coupling.
- Add matrix-free Kronecker product action.
- Add 65,536-mode accounting test.
- Keep dense 65,536² forbidden.

### 7.7 From R7 creativity

- Add avoided-crossing sweep fixture.
- Add phase-coherence metric kernel.
- Run held-out association/creativity experiment.
- Record supported/rejected/inconclusive.

### 7.8 From R8 NANNET

- Point-0 HTTP, offline live preflight, and signed-volume gate implemented; live Koyeb deployment remains blocked on credentials.
- Persist NANNET0 bindings in MC0DB.
- Run signed Koyeb volume-registry check.
- Add phase-invariant signature exchange.
- Keep one NANNET0 per universe.

### 7.9 From R9 LM adapter

- Full 256-dimensional residual and ENCODE/DECODE implemented.
- Frozen-base ablation harness implemented with paired controls; real-model/data ablation remains blocked.
- Enable only after measured held-out benefit.

### 7.10 From R10 promotion

- Register all 35+ kernels in production MC0DB.
- Add registry/plan evidence.
- Add capability promotion gate.
- Do not promote source-only or stale kernels.

---

## 8. Parallel work packets (development parallelism, serialized runtime)

| Packet | Scope | Depends on | Gate |
|---|---|---|---|
| P0 | Single-active runner-ring scheduler | WaveStore/leases | one active, 7 GiB, cycle/handoff |
| P1 | MTH registry/planner | manifest | load 34, resolve/plan tests |
| P2 | 256 block matvec | R1 | 16-block full matvec oracle |
| P3 | 256 streaming certificate | R3/fold | 16-block certificate + perturbation |
| P4 | wave HTTP adapter — implemented | WaveService | auth/lease/complete HTTP tests |
| P5 | 256 block pair / low-rank | P2 | 256 paged pair oracle |
| P6 | 256 aperture SVD/top-k | P2/P5 | full top pair, deflated top-2, and stable top-k local PASS; Lanczos in progress |
| P7 | 255/256 dense/paged eigenbasis | P2/P6 | versioned page/eigenbasis test |
| P8 | NANNET0 persistence + Koyeb | P4 | signed volume registry |
| P9 | LM ablation | P6/P8 | harness implemented; real held-out benefit or rejection still needed |
| P10 | R7 avoided crossing/phase | coupling kernel | native sweep PASS; held-out protocol harness in progress |
| P11 | Point-0 NaN→binary→NaN bridge/router — implemented | scheduler + address grammar | stable ingress, active-slot routing, stale epoch rejection |

**Runtime rule:** these work packets may be developed in parallel by agents, but execution is serialized by the single-active runner ring. Two packets may not hold live leases or active memory on two slots at the same time. A packet that needs more than the 7 GiB active ceiling must be paged, split, or rejected.

### 8.1 First parallel batch (in flight)

- Single-active runner-ring scheduler (implemented).
- MTH registry/planner (implemented).
- 256 block matvec (implemented).
- 256 streaming certificate (implemented).
- Wave HTTP adapter (implemented).
- MthSystem runtime facade (implemented).

### 8.2 Second parallel batch

- 256 block pair / low-rank.
- 256 aperture SVD/top-k.
- 255/256 paged eigenbasis and page cache.
- NANNET0 persistence/live Koyeb.

### 8.3 Third batch

- Frozen-base LM ablations with the new ENCODE/DECODE kernels.
- R7 avoided-crossing/phase-coherence experiment.
- Production MC0DB registration and promotion.

---

## 9. Numerical quality and memory policy

### 9.1 Lanes

| Lane | Use | Rule |
|---|---|---|
| exact U32/I32/Q16.16 | topology, indices, graph weights, fold equality | exact arithmetic; explicit overflow |
| float32 | trig, rotations, wave, spectral | declared error bound; residual checks |
| complex pair | phases/Hermitian | explicit real/imag; never implicit |
| pair-float/compensated | dot/orthogonality/residual | only after reference agreement |

No silent exact→approximate coercion. No NaN payload arithmetic without decode. No host math.

### 9.2 Block accumulation

- one accumulator per dot/matvec row unless a compensated variant is declared;
- increasing-index order;
- no FMA/reassociation;
- residual/error bound reported;
- stable tie-breaking for top-k.

### 9.3 Shard/cache quality

- content-addressed pages;
- generation/previous digest;
- signed registry;
- no mutable canonical page;
- cache eviction is not deletion of truth;
- 8 MiB universe pages remain canonical for the universe;
- BS0DB/MC0DB are evidence/control, not the universe.

---

## 10. Validation and completion gates

### 10.1 Mathematical gates

- exact oracles for every kernel;
- residual/orthogonality for spectral;
- energy drift for wave;
- block equivalence for 256×256;
- certificate perturbation rejection;
- plan composition equivalence to reference;
- paged vs dense equivalence.

### 10.2 System gates

- registry loads 35+ kernels;
- plan validation rejects stale/unverified/over-budget;
- executor dispatch refuses unverified kernels;
- BS0DB/MC0DB lease/idempotency/stale rejection;
- HTTP auth/quota/size;
- runner-ring one-active/7 GiB/handoff checks;
- page round-trip and generation check;
- no host math in execution path.

### 10.3 LM gates

- frozen base model;
- parameter/compute-matched baselines;
- held-out tasks;
- void/ring/product/real-complex/phase ablations;
- no default enable without measured benefit.

### 10.4 Definition of done

MTH System v1 is done when the system can:

1. ask for a typed mathematical operation or plan;
2. resolve it to verified native kernels;
3. page the required 255/256 state through the active runner and durable stores;
4. execute entirely in NaN16 on the CPU runners;
5. return a typed result with residual/error/evidence;
6. reject invalid, stale, unauthorized, over-budget, or unverified work;
7. promote only after reproducible evidence;
8. reproduce the same result from the plan digest and page digests.

It does not mean every mathematical theorem is implemented.

---

## 11. Risks and corrections

| Risk | Correction |
|---|---|
| “7 GB gives us a flat 256×256/65,536 workspace.” | 7 GiB is the active-runner ceiling, not a flat product workspace and not six × 7 GiB. 256×256 dense is 256 KiB; 65,536² dense is 16 GiB and remains forbidden. |
| “We can leave out some 256×256 values.” | 256×256 dense is small enough to keep exact; the object to compress is the product operator. |
| “255/256 are interchangeable.” | 255 heads + 1 NANNET0 node; odd fold 127+128; port is not a head. |
| “NANNET0 is a head/shard/runner.” | NANNET0 is the one network endpoint per universe; heads, runner slots, and durable pages are distinct. |
| “The aperture is Hermitian.” | Only if certified; otherwise SVD/Schur/left-right. |
| “The ring is automatically a maximum.” | Measure ring energy/coherence/antinodes; do not assume. |
| “Clients address R0..R5 directly.” | The stable address is point 0; the active slot is internal and changes behind it. |
| “The noosphere preserves phase.” | Network clocks do not imply phase coherence; use phase-invariant signatures unless a clock model exists. |
| “A candidate can self-promote.” | Candidate operators pass validation, authorization, and generation CAS. |
| “A host can compute the math.” | Host only orchestrates; NaN16 implements. |
| “The wave equation produces intelligence/creativity.” | Hypotheses only; held-out experiments required. |

---

## 12. The one-page continuation

1. **Keep the 36 CI-verified kernels as the arithmetic core.** Do not rewrite them to chase a new architecture.
2. **Build MTH System v1**: registry, plan, executor, evidence, capability.
3. **Use 256×256 dense only where it fits** (256 KiB); use 16×256 blocks for full matvec/certificate; use matrix-free/low-rank for the 65,536 product.
4. **Use NANROUTER-0..5 as a single-active runner ring with a 7 GiB active ceiling**, not six parallel runners; use NANNET0 as the one node per universe.
5. **Keep point 0 as the only ring address**; route to the active slot behind it.
6. **Finish the 256×256 block path**, then 256 aperture SVD/top-k, then 256 block pair/low-rank.
7. **Finish the HTTP/NANNET0 path** and production MC0DB registration.
8. **Finish the 255/256 streaming certificate** and odd head-only fold.
9. **Compose QUERY/MATCH/FILTER/DRIVE** from verified primitives; do not add a second math service.
10. **Run the LM adapter only behind a frozen-base ablation**; default disabled.
11. **Run R7 as an experiment**, not a claim: avoided crossings, phase coherence, held-out association, kill criteria.
12. **Promote only native-verified, CI-verified, digest-bound kernels** with explicit workspace/lease/evidence.
13. **The next document after this one should be an evidence ledger, not another manifesto.**

The shortest correct sentence is:

> **MTH System v1 turns the verified NaN16 kernels into a registry-driven, paged, evidence-bound mathematical service for the 255 + 1 + NANNET0 universe — with 256×256 dense where it fits, 16×256 blocks where it does not, and a matrix-free product space that is never materialized dense.**


## 13. Decision log

| ID | Decision | Status | Revisit |
|---|---|---|---|
| D1 | Keep dense 256×256/255×255 reference matrices; they are 256/254 KiB | accepted | if guest budget or precision changes |
| D2 | Use 16×256 blocks as the paged 256 matvec/certificate unit | accepted by prototype | if 32×256 is faster and fits |
| D3 | NANROUTER-0..5 is a six-slot, single-active runner ring with a 7 GiB active ceiling | implemented | after live Koyeb integration |
| D4 | NANNET0 is one node per universe, never a head/shard | accepted | none |
| D5 | Product operator 65,536² stays matrix-free/low-rank | accepted | only with a proven bounded dense use case |
| D6 | Top-k power/SVD before full dense eigensolve | accepted | when LM adapter needs full spectrum |
| D7 | HTTP adapter is a separate module over WaveService | implemented | after auth/rate-limit review |
| D8 | LM adapter default disabled until held-out ablation | accepted | after P9 evidence |
| D9 | 255-head odd fold is 127+128, not 128+128 | accepted | none |
| D10 | Every promoted kernel carries source/fixture digest, workspace, CI/evidence | accepted | none |
| D11 | Point 0 is the only ring address; NaN16↔binary↔NaN16 routing selects the active slot | implemented | after live gateway integration |
| D12 | MthSystem is the one runtime facade over registry/store/service/scheduler | implemented | after live executor integration |






















## Appendix A — Current native kernel catalog

Machine-readable source: `spec/wave-capabilities.json`. The catalog has 63 kernels; canonical CI run 42405010545 passed 124 steps. GLT 1 MiB page-limit enforcement remains a separate pending gate.

| Kernel | Precision | Fixture steps | CI |
|---|---|---:|---|
| `mth.k256.laplacian.u16` | `u16->i32` | 5,391 | yes |
| `mth.k256.pair_space.q16.16` | `q16.16` | 2,300,711 | yes |
| `mth.k255.laplacian.u16` | `u16->i32` | 5,881 | yes |
| `mth.ring255.laplacian.f32` | `float32` | 12,485 | yes |
| `mth.ring255.port.f32` | `float32` | 3,353 | yes |
| `mth.ring256.wave_energy.f32` | `float32` | 86,374 | yes |
| `mth.ring256.laplacian.f32` | `float32` | 19,736 | yes |
| `mth.sparse.laplacian.q16.16` | `q16.16` | 20,743 | yes |
| `mth.weighted_sparse.laplacian.q16.16` | `q16.16` | 41,253 | yes |
| `mth.graph.energy.q32.32` | `q32.32` | 60,569 | yes |
| `mth.graph.components.256` | `u32` | 29,931 | yes |
| `mth.graph.fold.f32` | `float32` | 9,281 | yes |
| `mth.centrosymmetry.128.f32` | `float32` | 676,252 | yes |
| `mth.centrosymmetry256.block16.f32` | `float32` | 337,623 | yes |
| `mth.centrosymmetry255.block15.f32` | `float32` | 653,687 | yes |
| `mth.vector.dot256.f32` | `float32` | 9,144 | yes |
| `mth.vector.norm256.f32` | `float32` | 6,842 | yes |
| `mth.vector.axpy256.f32` | `float32` | 8,389 | yes |
| `mth.vector.cosine256.f32` | `float32` | 17,189 | yes |
| `mth.graph.void.f32` | `float32` | 20,623 | yes |
| `mth.graph.wave_step.f32` | `float32` | 65,088 | yes |
| `mth.graph.step_energy.256.f32` | `float32` | 7,956 | yes |
| `mth.harmonic.wave_energy.f32` | `float32` | 53,877 | yes |
| `mth.harmonic.damped_energy.f32` | `float32` | 53,890 | yes |
| `mth.matvec.128.f32` | `float32` | 249,914 | yes |
| `mth.matvec256.block16.f32` | `float32` | 148,561 | yes |
| `mth.matvec256.full.f32` | `float32` | 2,978,362 | yes |
| `mth.power_iter.128.f32` | `float32` | 758,847 | yes |
| `mth.svd.top128.f32` | `float32` | 1,311,632 | yes |
| `mth.svd.top256.f32` | `float32` | 11,002,235 | yes |
| `mth.adapter.residual.128.f32` | `float32` | 420,587 | yes |
| `mth.adapter.residual.256.block16.f32` | `float32` | 113,055 | yes |
| `mth.phase.coherence.128.f32` | `float32` | 11,381 | yes |
| `mth.two_level.spectrum.f32` | `float32` | 390 | yes |
| `mth.decode.128_256.f32` | `float32` | 996,358 | yes |
| `mth.encode.256_128.f32` | `float32` | 996,358 | yes |
| `mth.decode.256.full.f32` | `float32` | 1,655,853 | yes |
| `mth.encode.256.full.f32` | `float32` | 1,655,853 | yes |
| `mth.graph.pair.full.128.f32` | `float32` | 68,195,822 | yes |
| `mth.graph.pair.rank1.128.f32` | `float32` | 252,060 | yes |
| `mth.lowrank.add.128.f32` | `float32` | 1,056,470 | yes |
| `mth.graph.dft256.f32` | `float32` | 8,958,287 | yes |
| `mth.graph.dft255.f32` | `float32` | 6,666,266 | yes |
| `mth.graph.couple128.f32` | `float32` | 8,637 | yes |
| `mth.graph.transmission.128.f32` | `float32` | 7,147 | yes |
| `mth.graph.pair.tile16.f32` | `float32` | 4,643,414 | yes |
| `mth.graph.pair.tile16.k16.f32` | `float32` | 283,436 | yes |
| `mth.jahs.gate.u64` | `u32` | 201 | yes |
| `mth.adapter.residual.256.full.f32` | `float32` | 2,839,172 | yes |
| `mth.graph.avoided_crossing_sweep.f32` | `float32` | 11,651 | yes |
| `mth.centrosymmetry255.full.f32` | `float32` | 2,700,726 | yes |
| `mth.svd.top2.256.f32` | `float32` | 40,216,927 | yes |
| `mth.topk.256.f32` | `float32` | 1,158,106 | yes |
| `mth.drive.source.256.f32` | `float32` | 13,092 | yes |
| `mth.cfl.guard.256.f32` | `float32` | 2,639,509 | yes |
| `mth.radial.tridiagonal.256.f32` | `float32` | 42,518 | yes |
| `mth.noise.colored.256.f32` | `float32` | 72,318 | yes |
| `mth.lanczos.topk.256.f32` | `float32` | 133,628,629 | yes |
| `mth.graph.pair.tile16.k16.driver.f32` | `float32` | 4,449,894 | yes |
| `mth.reachability.256.f32` | `float32` | 2,489,116 | yes |
| `mth.radial.energy.256.f32` | `float32` | 61,373 | yes |
