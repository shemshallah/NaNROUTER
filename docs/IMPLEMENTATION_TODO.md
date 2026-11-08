# Implementation TODO — Ring / Void / NANNET

**Status:** active implementation ledger.
**Canonical plan:** `docs/game_plan_deep.md`.
**Evidence ledger:** `docs/R10_IMPLEMENTATION_EVIDENCE.md`.
**Continuation plan:** `docs/DEEP_PLAN_CONT.md`.
**Mathematical linker plan:** `docs/GAME_PLAN_::.md`.
**Rule:** math kernels are NaN16; host code is transport/scheduling/storage only. A source file is not CI-verified until the canonical GitHub Actions workflow runs.

## Current baseline

- [x] K256 U16 Laplacian — native_verified.
- [x] Sparse unweighted Q16.16 Laplacian — native_verified.
- [x] Weighted CSR v2 Q16.16/I64 Laplacian — native_verified.
- [x] Weighted graph energy Q32.32 — local native_verified.
- [x] Connected-components 256 — local native_verified.
- [x] 255 heads + 1 NANNET node convention frozen.
- [x] Storage/execution fabric documented: NaNROUTER, single-active six-slot runner ring with 7 GiB active ceiling, Koyeb BS0DB/MC0DB, 8 MiB universe, 2 GiB overbootstrap.
- [x] 1 MiB baseline implemented (131,072 NaN16 words); old 512 KiB evidence is historical.
- [x] 2 MiB adjustable guest-word default checked in (262,144 words / 64 pages); 1 MiB/512 KiB compatibility modes implemented.
- [ ] Verify GLT-enforced 2 MiB page-limit loading (CI text-loader execution is green; GLT enforcement is separate).
- [x] JAHS ("Just A Handoff Seal") is mandatory in scheduler snapshots/checkpoint digests and `MthSystem.lease`; native gate/fixture CI PASS.
- [x] Add single-active runner-ring scheduler and handoff tests (27 tests).
- [x] 60/60 local native fixtures pass with `nan_cli`; K256 pair is CI-only locally due guest image size.
- [x] 909 Python tests pass (8 skipped).
- [x] Canonical workflow `42405649076` passed 132 steps for the 61-fixture set, including both operand-range alias regressions, native preflight, and composed admission.

## GAME PLAN `::` integration queue (P0–P13)

**Full architecture, schemas, authority rules, and the complete verification matrix:** `docs/GAME_PLAN_::.md`.
**Ordering rule:** do not start a later phase by bypassing a failed earlier gate. The ordered tests are in `docs/GAME_PLAN_::.md` §19–20.

- [x] **P0 — Freeze 2 MiB + authority contract.** Merge GPT's adjustable 2 MiB `guest_words`/`guest_bytes`, point-0 frame ceiling, health pages, and registration defaults; preserve 1 MiB/512 KiB modes; freeze the authority table and `::`/address context split. GLT 2 MiB page-limit loading remains the separate pending gate above.
  - [x] P0.1 Words-primary budget object: 2 MiB/262,144 words/64 pages; 1 MiB legacy; ceil pages/slack (`runner_riddle/budget.py`).
  - [x] P0.2 Re-register all six slot capabilities at 262,144 words via `--all-slots`; 1 MiB capability rejects a 196,608-word job; MiB conversion fixed to 131,072 words/MiB and all-six-slot tests added.
  - [x] P0.3 Point-0/HTTP 2 MiB frame + envelope/body limits; 131,072-word legacy frames still accepted.
  - [x] P0.4 Peak-liveness admission wired through `MthRegistry.validate_plan` and `MthSystem.submit_plan`; dependent plans admit by peak live workspace, undeclared-liveness plans keep the conservative sum; exact/-1 tests added.
  - [x] P0.5 Keep `wave_schema=1`; add `math_*` + separate `math_schema`; no unversioned bump (`math_store`).
  - [x] P0.6 Authority/`::` context rules frozen; `MathExecutionBridge` binds admission, NMP packet, active-ring incarnation/epoch, JAHS seal, capability, and one MthSystem lease (7 tests + restart projection).
- [x] **P1 — Mathematical leaf/identity/storage.** `math_objects`/`math-leaf` schema, canonical serialization, deep-frozen content/versioned mapping, provenance, null/void/undefined fields; additive math tables in `math_store` with opt-in strict content-digest enforcement (8 object tests + 17 store tests). MOA/cell-pair binding remains deferred.
- [x] **P2 — Semantic function registry.** `math_registry` + `spec/math-functions.v1.json`; 19 contracts/8 implementation bindings; composition tests (17).
- [x] **P3 — Validity engine.** `math_validity` levels 0–3, typed verdicts, cache, certificates, contradiction/preflight tests (23); native NaN16 rule and typed-object admission gates are integrated, capability-to-lease admission is wired through P5, and unverified numeric certificates now fail closed (`UNKNOWN`/`CERTIFICATE_NOT_PINNED`). Authorization/ACL remains a separate orthogonal verdict by design.
- [x] **P4 — `::` linker.** `math_linker` resolve/classify/propose/rank/bounded candidates/address-context rejection; 27 tests; does not execute. Scratch is invisible unless explicitly allowed; quarantined/tombstoned/superseded leaves are rejected; typed null metadata carries failure class, linker ID, rule snapshot, and candidate count.
- [ ] **P5 — NMP + execution bridge.** Host control plane is implemented; native receipt production, native operator dispatch, and numeric end-to-end execution remain external gates.
  - [x] P5.a Native NaN16 rule gate + typed operand preflight; exact epoch, signature, domain, shape, capability subset, proof level, enabled state, and 256-bit rule digest.
  - [x] P5.b Canonical NaN0S `::op:` expression resolution returns the authoritative MC0 contract pointer; NaNROUTER consumes that exact pointer (no reconstructed contract).
  - [x] P5.c Output/input payload non-aliasing uses half-open ranges and rejects partial overlap and address-plus-capacity wrap; left/right overlap and output atomicity are native-tested.
  - [x] P5.d NMP validates immutable native-admission receipts (candidate/rule/preflight digests, epoch, operands, guest ALLOW, receipt digest) and binds them to one live job/lease/ring/JAHS snapshot; 3 dedicated tests. Receipt production remains the native `mth_admit` caller's responsibility.
  - [x] P5.e Add admission-gated NaN16 dispatch for canonical program/operator pairs 900/77 (dot256) and 901/78 (cosine256); native linker fixture verifies outputs, tolerance, stale-epoch preservation, mismatches and unknown IDs. Atomic result commit remains P5.g.
  - [x] P5.f Host bridge binds packet/admission/active-ring incarnation/epoch/JAHS/capability/durable job/one lease and denies stale generation, replay, duplicate, cancellation, and restart violations before executor or commit. Point-0 HTTP remains a transport ingress, not a second execution authority.
  - [x] P5.g Host control-plane execution, immutable result commit, provenance, and output feedback are implemented in `MathExecutionBridge` and the P12 demo. Admission is candidate/snapshot/function-version/selected-kernel-bound, direct `MathRuntime.submit()` is disabled, executor dispatch is pre-validated against the active lease/cancel/deadline, re-reads the durable job row, revalidates the rule snapshot, and redacts bearer tokens from serialized evidence. Negative tests A06/A09–A12 are green. Native numeric execution remains external.
- [x] **P6 — Meta-mapping/store.** `math_store` additive schema, CAS/rollback, payload references/recovery/chunking; 17 tests. Crash-consistent cross-store intent/finalize and recovery are implemented (12 tests, `docs/MATH_STORE_CROSS.md`).
- [x] **P7 — Null/void/undefined algebra.** Typed `ZERO/NULL/VOID/EMPTY/UNDEFINED/INFINITY/UNKNOWN/ERROR/CANCELLED` states, explicit conjunction semantics, missing-reference dominance; 59 tests (`docs/MATH_ABSENCE_ALGEBRA.md`).
- [x] **P8 — Relations/hyperedges/hypergraphs.** Typed schema/roles/arity/duplicate policy, immutable relation versions, incidence, bounded nested traversal, digest stability; 9 tests (`docs/MATH_RELATIONS_HYPERGRAPHS.md`).
- [x] **P9 — Learning/rule discovery.** Five orthogonal axes, isolated proposals, independent approval, trusted-checker-only V3/proof, transactional promotion, negative memory, audit chain, Boolean-head utility-only governance; 20 tests (`docs/MATH_RULE_LIFECYCLE.md`). Typed principal/role/capability policy with separation-of-duty checks is implemented in `math_auth` (9 tests, `docs/MATH_AUTHORIZATION.md`) and optionally enforced by `MathLearningService` (26 learning tests, fail-closed before store writes). Boolean-head 1,024/1,024 + leakage/control/shuffled gate is implemented (`math_boolean`, 10 tests, `docs/MATH_BOOLEAN_HEADS.md`). The five discovery mechanisms remain open.
- [x] **P10 — Scratch/oscillation/pruning.** Typed retention features/scoring, tier policy, deterministic plans, protected proof objects, shadow/apply/rollback/restore, oscillation budgets, duplicate and rewrite-cycle stops; 10 tests (`docs/MATH_RETENTION_AND_OSCILLATION.md`). Disposable canonical-backed cache eviction/reload is implemented in `math_cache` (5 tests, `docs/MATH_CACHE.md`); full cache-key eviction and scratch lifecycle integration remain open.
- [x] **P11 — Logical lanes/ring mapping.** `lane_registry` 255 lanes/17×15, NANNET0 rejection, capabilities/FP/page budget; 18 tests; live ring binding is enforced by P5. Bounded work queues and capability-safe work stealing are implemented in `lane_work` (8 tests, `docs/LANE_WORK_QUEUES.md`); ring state/epoch export-restore recovery is implemented in `WaveRingScheduler.export_state`/`restore_state` (30 scheduler tests, `docs/RING_EPOCH_RECOVERY.md`). Remote/process stealing remains open.
- [x] **P12 — End-to-end demo.** `tools/run_math_demo.py` exercises leaf → `::` → preflight → NMP → active-ring lease → execute → commit → output feedback; 2 tests. The output leaf carries input parents, function/version, ruleset snapshot, plan digest, JAHS/ring/job/runner provenance, and a typed input/input/output hypergraph relation; the report labels its digest as evidence, not a numeric dot product (`docs/MATH_DEMO.md`).
- [ ] **P13 — Real experiments/live gates.** Frozen-model LM ablations, R7 held-out, capacity-vs-SNR, live Koyeb/NANNET0, production MC0DB, native numeric executor delivery; blocked pending real model/data/credentials/guest runtime. Machine-readable blocked ledger: `spec/p13-gates.json`; explanation: `docs/P13_GATES.md`. No fabricated claims.

## R0 — Contract and storage freeze

- [x] Freeze 255 heads + 1 NANNET node = 256 ring positions.
- [x] Freeze 8 MiB = 255 head pages + 1 NANNET page.
- [x] Freeze BS0DB/MC0DB/universe/runner ownership.
- [x] Add machine-readable wave-store schema (`spec/wave-store.schema.json`).
- [x] Add `runner_riddle/wave_store.py` with BS0DB/MC0DB tables, idempotent jobs, leases, seals, signatures, capabilities.
- [x] Add storage tests (12 tests).
- [x] Add page-map / ring-binding descriptor (`spec/ring-255.json`).
- [x] Add R0 evidence ledger entry.

## R1 — Geometry and page map

- [x] Define C255 head ring + NANNET port attachment policy.
- [x] Generate canonical C255 CSR (head-only ring).
- [x] Generate port coupling vector / port row.
- [x] Add K255 exact oracle.
- [x] Add C255 ring Laplacian fixture.
- [x] Add 256-position readout layout descriptor.
- [x] Add page map: 255 head pages + 1 NANNET page.
- [x] Native verification of K255, C255, and port-assembly fixtures.
- [x] Add dot/norm/axpy float32 primitives.

## R2 — Void and radial blocks

- [x] Import weighted graph energy and connected components.
- [x] Add native regularized inverse-square void potential kernel.
- [x] Add α = 0 and α > 0 fixtures.
- [ ] Add radial block descriptor / tridiagonal layout.
- [ ] Add inner Dirichlet/Robin boundary contract as a native descriptor.
- [ ] Add radial energy/localization fixture.

## R3 — Spectral engine

- [x] Add 256-point complex float32 DFT reference with caller-supplied twiddle table.
- [x] Add a separate 255-point head-only DFT reference.
- [x] Add even 256-position fold vector kernel.
- [x] Add odd 255-head fold vector kernel.
- [x] Add 128×128, 16×256, and 15×255 certificates.
- [x] Add 16×256 and 15×255 streaming certificates.
- [x] Add 128×128 power-iteration kernel.
- [x] Add deterministic 256-tile page-window orchestration and atomic publication (`wave_tile_orchestrator`, 31 tests).
- [ ] Add Lanczos/top-k deflation (SVD top-2, stable top-k, and Lanczos 256 local PASS).
- [ ] Add residual/orthogonality fixture for a real operator.

## R4 — Wave dynamics

- [x] Add float32 velocity-Verlet wave-step kernel.
- [x] Add step-energy metric kernel.
- [x] Add invalid dt/gamma/layout rejection atomicity.
- [x] Add four-step harmonic-H energy-conservation fixture (diagonal H) — local PASS.
- [x] Add repeated-step energy conservation with a real C256 graph Laplacian `H`.
- [x] Add four-step harmonic damped-energy-decrease fixture.
- [ ] Add bounded DRIVE source fixture.
- [ ] Add CFL / λ_max guard fixture.
- [x] Add deterministic trace fields in storage schema.

## R5 — Aperture

- [x] Add float32 dot, norm, axpy, and cosine primitives.
- [x] Add 128×128 dense matvec primitive.
- [x] Add aperture descriptor and decomposition selector (`runner_riddle/wave_aperture.py`; 9 tests).
- [x] Add 128×128 power-iteration kernel.
- [ ] Add full QUERY / MATCH / FILTER / DRIVE controller composition (primitive set complete).
- [x] Add observability/reachability metric kernel (native BFS, 2,489,116 steps).
- [x] Add capacity-vs-SNR test plan (`docs/R5_CAPACITY_SNR_PLAN.md`).
- [x] Add colored-noise generator kernel (72,318 steps).

## R6 — Product space

- [x] Add K256 closed-form 256×256 pair-space action.
- [x] Add dense 128×128 pair-space action `LU + ULᵀ`.
- [x] Add rank-1 128 pair-space prototype.
- [x] Add small explicit fixture (L=2I) and zero-state fixture.
- [x] Add rank-1 low-rank coupling kernel (callable R times).
- [x] Add 65,536-mode accounting in the plan.
- [x] Reject dense 65,536² materialization in the plan and memory budget.
- [x] Add 256×256 tiled dense product action — bounded 16×16 K16 NaN16 accumulator/finalizer native_verified in CI run 242 (1,542 words, 12,336 bytes); page-window orchestration and atomic publication remain open. The full-U reference requires 73,990 words and fits the default 1 MiB MTH guest budget; 512 KiB runners reject it.

## R7 — Tunneling and creativity

- [x] Add block-coupling `eta` primitive.
- [x] Add transmission metric primitive.
- [x] Add experiment protocol with conditions, metrics, baselines, kill criteria.
- [x] Add two-level avoided-crossing spectrum kernel and native coupling sweep (11,651 steps).
- [x] Add 128-element phase-coherence metric kernel.
- [x] Add held-out creativity/association protocol harness with leakage/duplicate/control gates (21 tests).
- [ ] Run the held-out experiment against real frozen model/data (blocked; no result claimed).
- [ ] Record supported/rejected/inconclusive result.

## R8 — NANNET node and storage

- [x] Add BS0DB/MC0DB storage with one-NANNET-node ring binding.
- [x] Add per-universe NANNET node binding registry (`runner_riddle/wave_node.py`; 8 tests).
- [x] Persist ingress/egress, traces, seals, signatures in BS0DB.
- [x] Add phase-invariant signature record.
- [x] Add state-seal/cartridge schema.
- [x] Add job/lease/capability state machine.
- [x] Add stale/unauthorized/replay rejection tests.
- [x] Add authenticated WaveService facade over BS0DB/MC0DB.
- [x] Add point-0 stable ingress and active-slot routing.
- [x] Add standalone Wave HTTP adapter over WaveService.
- [x] Add point-0 NaN↔binary↔NaN bridge/router to the active slot (10 tests).
- [x] Add point-0 HTTP ingress with bounded 1 MiB frames, stable route, active-slot/epoch evidence, and JAHS seal.
- [x] Add offline live-preflight and signed-volume-registry gate (no network by default).
- [ ] Add live NANNET0/Koyeb integration and production signed volume-registry check (blocked on real credentials).

## R9 — LM adapter

- [x] Freeze adapter descriptor `h + β C u`.
- [x] Add adapter mode and ablation descriptor.
- [x] Add frozen-base ablation labels and safety gate.
- [x] Add 128-dimensional NaN16 adapter residual composition.
- [x] Add 256→128 ENCODE and 128→256 DECODE kernels.
- [x] Add full 256×256 ENCODE/DECODE and full 256 adapter residual kernels.
- [x] Add frozen-base ablation harness with paired controls and hard evidence gate.
- [ ] Run retrieval/memory adapter and frozen-base ablations against a real frozen model/data set (blocked on model harness).
- [ ] Enable only after measured held-out benefit.

## R10 — Promotion

- [x] Add capability manifest with 58 kernels (`spec/wave-capabilities.json`).
- [x] Add `tools/register_wave_capabilities.py` and MC0DB registration tests.
- [x] Expand native CI workflow for 20 fixtures.
- [x] Add `mth/README.md` inventory updates.
- [x] Add `docs/GRAPH_SPECTRAL_MTH_PLAN.md` implementation update.
- [x] Add `docs/R10_IMPLEMENTATION_EVIDENCE.md`.
- [x] Run the 34-fixture CI workflow on GitHub Actions.
- [ ] Register final CI digests in the production MC0DB.

## Agent dispatch board

| Agent | Scope | Files | Status |
|---|---|---|---|
| A1 | Storage/control plane | `runner_riddle/wave_store.py`, `spec/wave-store.schema.json`, `tests/test_wave_store.py` | done — 12/12 tests |
| A2 | Void potential | `mth/nan16/mth_graph_void.nas`, fixture, ABI | done — native PASS |
| A3 | Fold | `mth/nan16/mth_graph_fold.nas`, fixture, ABI | done — native PASS |
| A4 | Wave step | `mth/nan16/mth_graph_wave.nas`, fixture, ABI | done — native PASS |
| A5 | Pair space | `mth/nan16/mth_graph_pair.nas`, fixture, ABI | done — full 128×128 PASS |
| A6 | DFT | `mth/nan16/mth_graph_dft256.nas`, fixture, ABI | done — native PASS |
| A7 | Ring/page map | `tools/gen_ring_csr.py`, `spec/ring-255.json`, tests | done — 9/9 tests |
| A8 | CI/capability | workflow, `tools/register_wave_capabilities.py`, tests | done locally |

## Final local evidence

```
python3 tools/run_mth_fixtures.py
60/60 local fixtures passed; 61/61 total (K256 pair CI-only)

python3 -m unittest discover -s tests -q
Ran 909 tests
OK (skipped=1)
```

CI: `42405649076` — 132/132 steps for the 61-fixture set. GLT 2 MiB page-limit enforcement remains pending. See `docs/R10_IMPLEMENTATION_EVIDENCE.md` for the fixture table and the explicit not-yet-proven list.

## Parallel batch 2 (2026-11-07)

| Agent | Scope | Status |
|---|---|---|
| A9 | 255-point DFT | done — native PASS |
| A10 | 128×128 power iteration | done — native PASS |
| A11 | C256 ring + graph-H energy | done — both native PASS |
| A12 | Rank-1 low-rank add | done — native PASS |
| A13 | 128 adapter residual | done — native PASS |
| A14 | Authenticated wave service facade | done — 13 tests |

## Parallel batch 3 (2026-11-07)

| Agent | Scope | Status |
|---|---|---|
| A15 | MTH system registry/planner | done — 26 tests |
| A16 | 256×256 block matvec | done — native PASS |
| A17 | 256×256 streaming certificate | done — native PASS |
| A18 | Wave HTTP adapter | done — 12 tests |
| A19 | Single-active runner-ring scheduler | done — 27 tests |
| A20 | Point-0 NaN/binary bridge/router | done — 35 tests (implemented during integration) |
| A21 | MthSystem runtime facade | done — 11 tests |
| A22 | 256×256 pair-space tile reference | `mth_graph_pair_tile16_f32.nas`, fixture, ABI, CI | done — native_verified; fits 1 MiB target |
| A23 | Bounded K16 pair tile | `mth_graph_pair_tile16_k16_f32.nas`, fixture, ABI, CI | done — native_verified, CI run 242; 1,542 words |
