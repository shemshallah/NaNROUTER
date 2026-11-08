# Master completion TODO — all game plans

**Date:** 2026-11-08
**Baseline:** 1217 Python tests, 16 skipped, OK; 95 manifest kernels (91 `ci_verified`, 4 local-only); 93 canonical runner fixture paths and 92 unique manifest fixtures; static NaN-native boundary audit green. `main` includes the execution, storage, discovery, HTTP, authorization, ring, N16T worker, NMP HTTP, graph degree/pattern, page-record, point-0, Koyeb bootstrap, sequence controller, and capacity-harness work.
**Rule:** an item is checked only when code, a test or explicit blocked record, and evidence text agree. A locally source-written kernel is not CI-verified. An external gate is never marked green without real evidence.

Status: `DONE` = code + test/evidence; `PARTIAL` = implemented but missing a named acceptance condition; `OPEN` = no implementation; `BLOCKED` = requires unavailable external evidence/credentials/hardware.

---

## 0. Baseline already landed

- [x] 2 MiB / 262,144-word default with 1 MiB and 512 KiB compatibility profiles.
- [x] Single-active six-slot ring, JAHS, 7 GiB ceiling, lane/NANNET0 mapping.
- [x] Native 95-kernel manifest (91 CI-verified, 4 local-only), 93 registered runner fixtures, and credential-free canonical native CI workflows.
- [x] Full 8 MiB guest map and 32,896-point NANNET relation coverage (`runner_riddle/universe_map.py`, `spec/universe-map.json`, `mth.universe.map.u32`); workspace budget remains a separate 2 MiB adjustable policy bound.
- [x] Unified cross-repo MTH catalog and provider audit (`runner_riddle/mth_unified.py`, `tools/mth_unified.py`, `spec/mth-unified-system.v1.json`).
- [x] Static NaN-native boundary audit (`spec/nan-native-boundary.json`, `tools/audit_nan_native.py`) covering every registered MTH source, fixture, runner entry, CI workflow, and host numeric import boundary.
- [x] `math_objects`, `math_store`, `math_registry`, `math_validity`, `math_linker`, NMP, execution bridge, demo.
- [x] Typed absence algebra, relations/hypergraphs, rule lifecycle, retention/pruning.
- [x] Cross-store commit intent/evidence/finalize recovery.
- [x] Durable NMP packet/transition ledger store layer.
- [x] Five discovery mechanisms (proposal layer).
- [x] Typed authorization and Boolean-head gate.
- [x] Math HTTP health/link/execute seam.
- [x] Work queues/stealing contract and ring epoch export/restore.
- [x] A06/A09–A12/A20 and extended A/T negative tests.
- [x] P13 blocked gate ledger.

---

# A. `GAME_PLAN_::` completion

## A1. Evidence/vocabulary freeze

- [x] `A-01` Freeze authority, validity, truth, proof, lifecycle, capability, and utility as separate axes. Keep production validity capped at V2.
- [x] `A-02` Explicit blocked P13 ledger (`spec/p13-gates.json`, `docs/P13_GATES.md`).
- [x] `A-03` Enumerate A01–A20 formally in `docs/MASTER_COMPLETION_TODO.md` and `docs/VERIFICATION_MATRIX.md`; tests cover A01–A16/A18–A20 and A17 restart/commit.
- [x] `A-04` Enumerate T01–T20 oracle expectations in `docs/VERIFICATION_MATRIX.md` and mark each test ID done/partial/missing.
- [ ] `A-05` Resolve T12 vocabulary: unknown function currently yields `UNSUPPORTED` before NMP maps it to `REJECTED`; freeze whether the preflight verdict is `UNSUPPORTED` and gate failure is `REJECTED`.
- [x] `A-06` Freeze the void/potential formula: canonical `α/(r²+ε²)` implemented by `mth_graph_void.nas`; plan prose corrected.
- [ ] `A-07` Decide/defer the MOA 65,536-cell bit layout and XFSC365 function-reference resolver.
- [ ] `A-08` Unify evidence ladders or explicitly map MTH §10 8 levels, wave_adapter 7, wave_store 5, and math V0–V3.

## A2. Admission/execution spine

- [x] `A-10` Candidate/snapshot/function-version/selected-kernel admission binding.
- [x] `A-11` Direct `MathRuntime.submit()` disabled; bridge is the path.
- [x] `A-12` Fail-closed numeric certificates.
- [x] `A-13` Pre-dispatch lease/deadline/cancel/job/rule revalidation.
- [x] `A-14` Worker-token authentication before executor.
- [x] `A-15` Bearer-token redaction from serialized evidence.
- [x] `A-16` Stale lease replay cannot re-execute/re-commit.
- [x] `A-17` Negative suite A06/A09–A12/A20 and extended A01–A05/A13–A16/T07/T08/T19.
- [x] `A-18` Wire durable NMP packet/transition rows into `MathExecutionBridge` submit/lease/complete/cancel/fail.
- [ ] `A-19` Revalidate the complete admission object at lease/complete (current rule-snapshot and lease checks are not a full `require_admission`).
- [ ] `A-20` Add an end-to-end rejection test for a rule/capability/auth change between submit and complete.
- [x] `A-21` Make math admission binding mandatory for direct `MthSystem.submit_plan` in math mode (`require_math_admission=True`); default remains off for legacy wave jobs.
- [x] `A-22` Typed execution evidence beyond a digest: kernel/runner identity, residual/error bounds, saturation/iterations, guest pins, lease/JAHS/ring binding, numerical policy, and bounded provenance (`ExecutionEvidence`, 5 tests).
- [ ] `A-23` **PARTIAL:** native NaN16 dispatch is implemented for canonical program/operator pairs 900/77 and 901/78 (`mth_execute.nas`), and N16T worker execution evidence is integrated with NMP pre-lease/completion pins. Native admission-receipt production remains external.
- [ ] `A-24` Make the demo use the real native executor when the NaN0S toolchain is available, while retaining the evidence-digest fallback.

## A3. Identity/storage

- [x] `A-30` Deep-frozen leaf/function/rule objects.
- [x] `A-31` Opt-in strict declared content-digest equality.
- [x] `A-32` Optional `metadata_version` and result provenance checks.
- [x] `A-33` Cross-store intent/finalize/recovery.
- [x] `A-34` Disposable canonical-backed cache.
- [x] `A-35` Durable NMP packet/transition ledger.
- [x] `A-36` Add `math_nmp_packet`/transition counts to health; runtime/bridge transitions now write the durable ledger.
- [ ] `A-37` Enforce content-digest equality by default for all new versioned records (legacy compatibility clearly fenced).
- [ ] `A-38` Enforce full result provenance: input IDs/versions/digests, function/rule snapshot, candidate/linker, runner/lease, native source/fixture digest, numerical policy, output digest, signature.
- [x] `A-39` Durable universe page records with 0..255 bounds, head/NANNET0 mapping, immutable versions, generation CAS, pin/release, page-map digest, atomic MC0DB publication, and a 32 KiB file-backed page provider with digest/checksum/traversal validation. Cross-database page events and full 256-file transactions remain open.
- [ ] `A-40` Add missing/corrupt/evicted cache generation tests and audit-digest-set preservation.
- [ ] `A-41` Add durable alias record/schema/ACL (HW0 aliases currently caller-supplied).

## A4. Linker/registry/validity

- [x] `A-50` Linker rejects nan:// context, unbound HW refs, raw offsets; router rejects math:// with `route_context_mismatch`.
- [x] `A-51` Scratch/quarantined/tombstoned/superseded leaf isolation.
- [x] `A-52` Typed null metadata includes failure class, linker ID, rule snapshot, candidate count.
- [x] `A-53` Linker 27 tests; runtime rule/capability providers.
- [x] `A-54` Optional contract digest on candidates/packets/dedupe keys; linker recomputes canonical contract digests and rejects mismatches; validity mapping preserves the field.
- [ ] `A-55` Add rule catalog/schema (`spec/math-rule.schema.json`) with pre/postconditions, invariants, undefined conditions, numerical policy, test/certificate refs.
- [ ] `A-56` Implement a real compatibility index keyed by types/domains/shape class with versioned invalidation.
- [ ] `A-57` Make composition create a function leaf and preserve composition provenance.
- [ ] `A-58` Add relation shared-domain/cross-domain permission and rule-snapshot fields; hypergraph leaf kind.
- [ ] `A-59` Add XFSC365 resolver or explicit deferral.
- [ ] `A-60` Fix preflight order/resource verdict ambiguity (`WORKSPACE_EXCEEDED` vs capacity/unavailable).
- [ ] `A-61` Add native certificate verifier or explicitly return `UNKNOWN`/`UNSUPPORTED` for all numeric predicates without one.
- [ ] `A-62` Add `NmpPlan` integration into bridge/submission evidence (wrapper exists and tests pass).
- [ ] `A-63` Add authorization context to preflight/admission identity; include preflight/auth/capability context in `admission_id_for`.
- [ ] `A-64` Restore/re-verify persisted admissions after restart; `_issued` is process-local.

## A5. NMP/ring/lanes

- [x] `A-70` Core NMP states/transitions/dedupe/batch/receipt validation.
- [x] `A-71` Ring/JAHS/epoch lease binding and restart projection.
- [x] `A-72` 255 lane registry, pass schedule, page budget.
- [x] `A-73` Work queues/stealing contract.
- [x] `A-74` Ring epoch export/restore.
- [x] `A-75` Wire NMP durable ledger into bridge transitions (submit/lease/complete/commit/cancel/fail).
- [x] `A-76` Lane work queues/stealing integrated as an optional projection adapter; authoritative bridge/WaveStore leases remain the only ledger, and queue operations never invoke an executor.
- [ ] `A-77` Implement durable ring incarnation/epoch recovery in the bridge path.
- [ ] `A-78` Add remote worker/peer protocol with selected-step-only payloads, quotas, timeouts.
- [x] `A-79` NMP packet/input/history/evidence total size bounds (64 inputs, 4,096 history entries, 1 MiB evidence, 2 MiB packet fields).
- [ ] `A-80` Add network/clock drift model and phase/delay/jitter behavior.

## A6. Learning/retention/security

- [x] `A-90` Five discovery mechanisms (proposal layer).
- [x] `A-91` Learning authorization fail-closed enforcement.
- [x] `A-92` Boolean-head 1,024/1,024 + leakage/control/shuffled gate.
- [x] `A-93` Retention/pruning/shadow/rollback/oscillation.
- [x] `A-94` Deep immutability/content digest.
- [ ] `A-95` **PARTIAL:** discovery results can be persisted as non-authoritative `propose` events via `MathStore.append_discovery_result`; linker/validity/lifecycle wiring of accepted proposals remains open.
- [x] `A-96` Wire Boolean-head gate results into `MathLearningService.record_boolean_head_experiment` as utility-only evidence with an explicit authority check.
- [ ] `A-97` **PARTIAL:** typed `ClassCPolicyTransition` with separate signed policy digests, policy roles/capability, distinct proposer/approver, and no-signature-verification marker is implemented (2 tests). Wiring it into every checker/schema/ACL/control-head mutation remains open.
- [ ] `A-98` Add `rule.activate`/`rule.prune` capabilities to all learning mutators (policy exists; wiring exists for learning; verify store/retention paths).
- [x] `A-99` Optional authenticated principal/ACL enforcement on all `MathStore` reads and mutations; legacy no-authorizer behavior preserved; denial occurs before SQL.
- [ ] `A-100` Add durable denied-operation audit rows for validity/execution denials.
- [ ] `A-101` Add refutation/counterexample retention and audit-digest protection.
- [ ] `A-102` Add subsumption-aware negative memory.
- [ ] `A-103` Add scratch lifecycle/budget/compaction/visibility/promotion gate.
- [ ] `A-104` Add full oscillation OBSERVE→…→EVALUATE cycle integration.
- [ ] `A-105` Implement learned retention weights rather than static defaults.
- [ ] `A-106` Add cross-store crash-injection through the bridge/learning path.

## A7. HTTP/demo/observability

- [x] `A-120` 2 MiB point-0 frames and bounded HTTP bodies.
- [x] `A-121` `/v1/math/health|link|execute` seam with JAHS/auth/token redaction.
- [x] `A-122` Math health in `MthSystem.health(math_health=...)` and `MathRuntime.health()`.
- [x] `A-123` Demo output provenance and hypergraph relation.
- [x] `A-124` `/v1/math/execute` now resolves a server-owned prepared handle and calls `MathExecutionBridge.execute`; clients cannot submit raw tokens. Handle/result registry remains process-local.
- [ ] `A-125` Add math HTTP submit/lease/complete routes or explicitly document point-0-only ingress.
- [ ] `A-126` Add path-wide no-host-math runtime audit.
- [ ] `A-127` Add demo negative-suite orchestration (mismatch/stale/unavailable/unauthorized together).
- [ ] `A-128` Add complete math health probes for store/cache/linker/validity/executor.

## A8. Native worker and NMP HTTP

- [x] `A-130` N16T binary HTTP worker handoff (`POST /n16t`) with guest-owned HELLO/CAPABILITIES/CLOSE and bounded frames.
- [x] `A-131` NMP HTTP submit/lease/complete routes with durable job payloads.
- [x] `A-132` NMP native execution evidence: pre-lease gate and completion bound to trusted guest binary pins.
- [x] `A-133` Durable N16T session/replay checkpointing (`N16TSessionStore`) with restart restore, duplicate replay rejection, session ownership checks, bounded journals, TTL cleanup, and no-store legacy behavior. Checkpoints are replay journals, not raw VM snapshots.
- [ ] `A-134` **PARTIAL:** `WorkerIdentityBinder` provides token-digest-to-owner binding and an NMP HTTP verifier callback without raw-token storage; deployment still must supply the trusted token source and bind handle IDs to callers.
- [x] `A-135` Guest-backed native admission receipt builder/validator integrated with N16T execution metadata; content-binding evidence, not cryptographic attestation.
- [ ] `A-136` N16T message types beyond HELLO/CAPABILITIES/CLOSE; corpus/training/candidate/merge capabilities remain unimplemented.
- [ ] `A-137` Durable prepared-handle/idempotence registry for `/v1/math/execute` (currently process-local).
- [ ] `A-138` Bind opaque execution handle IDs to authenticated callers in deployment.


---

# B. `GAME_PLAN_MTH.md` completion

## B1. Stage 0/1 native substrate

- [x] `B-01` Machine-readable NaN16 word/class layout (`spec/nan16-word-layout.json`, 4 tests, `docs/NAN16_WORD_LAYOUT.md`).
- [x] `B-02` Stage 0, double-endian, vector, typed-preflight, and native-dispatch fixtures are registered and carry `ci_verified=true` in the 91-entry canonical set; the four 2026-11-08 additions remain local-only pending CI.
- [ ] `B-03` Exhaustive 16 Boolean functions, all 16 class pairs, illegal-pair/resync fixtures in CI.
- [x] `B-04` All MTH sources are registered in the 95-entry manifest (91 `ci_verified`, 4 local-only); 93 runner fixture paths are wired to canonical native workflows. The normalize/prefix-sum/PRNG/universe-map fixtures pass locally, but are not described as CI-verified until canonical CI runs.
- [ ] `B-05` Signed, unsigned, checked, saturating, wrapping, unbounded, multiword integer arithmetic.
- [ ] `B-06` Carry/borrow/overflow/divide-by-zero boundary fixtures.
- [ ] `B-07` Bitwise/rotations/popcount/CLZ/CTZ/select/min/max/clamp/abs/sign and reductions.
- [ ] `B-08` Rational/gcd/lcm/exact-root/finite-field/fixed-point scalar layer.
- [x] `B-09` Typed scalar/array descriptor: element type, stride, layout, units, rank, shape, domain, context; optional fields preserve legacy digests; function composition rejects declared descriptor conflicts.
- [ ] `B-10` Pair codec regressions: byte/face/payload/inverse/missing-member/corruption.
- [ ] `B-11` Resolve `mth_negate256_f32` registration so `DEEP_PLAN_CONT` ring-wave plan resolves.
- [x] `B-12` Full 8 MiB guest map over 256 pages and 1,048,576 words; 256 fixed heads, 32,640 mirror pairs, 32,896 canonical relation points; NANNET0 aliases `head 0 = page 255 = ring 255 = HW0:0`. Host map and native `mth.universe.map.u32` fixture pass locally (12,916,386 steps). `spec/universe-map.json` records all page descriptors.
- [x] `B-13` Unified cross-repo MTH catalog and provider drift audit (`runner_riddle/mth_unified.py`, `spec/mth-unified-system.v1.json`). It binds 95 kernels to NaN0S execution, HERMES/Android contracts, and the control plane, with worktree-first and fetched `origin/main` fallback. It never fetches or modifies sibling worktrees and never claims CI or a live deployment.

## B2. Tier 2–3 numeric/array operations

- [ ] `B-20` Vector create/index/slice/concat/gather/scatter.
- [ ] `B-21` **PARTIAL:** native float32 add/sub/mean/scale/abs/relu are implemented and locally verified; broadcast, distance, and normalization remain open.
- [ ] `B-22` **PARTIAL:** native finite-domain argmax/argmin with first-index ties and fail-closed NaN/Inf are locally verified; native inclusive prefix sum is also local-only. Masks, permutation, and CI promotion remain open.
- [ ] `B-23` **PARTIAL:** native 256×256 transpose, diagonal extraction, and elementwise add are locally verified; reshape/multiply/axis reductions/identity/zero/normalization remain open.
- [ ] `B-24` Determinant/inverse/triangular and tensor contraction.
- [ ] `B-25` Implement `math.matrix.multiply` currently `proposed` with no implementation.
- [ ] `B-26` General sparse-CSR pair action and full-grid 256-tile native execution.
- [x] `B-27` Add typed shape/precision/layout/domain/alias handoff checks and optional fuel/cancel bounds in `MthPlan`; legacy v1 plans remain serializable.

## B3. Tier 4–5 stable numerics/ML

- [ ] `B-30` Stable softmax/log-softmax/log-sum-exp.
- [ ] `B-31` exp/log/sqrt/rsqrt/sigmoid/tanh/ReLU.
- [ ] `B-32` Entropy/cross-entropy/KL/CDF/inverse-CDF.
- [ ] `B-33` **PARTIAL:** native xorshift64 forward step with known-answer, reference, aliasing, class, and zero-state rejection fixtures passes locally (`ci_verified=false`); seeded sampling, entropy conversion, and categorical sampling remain open.
- [ ] `B-34` **PARTIAL:** host-only attention plan controller composes qk_dot/scale/mask/softmax/weighted_sum/head_concat/projection and returns typed UNAVAILABLE until native mask/softmax/weighted-sum/concat kernels exist. No host math or execution.
- [ ] `B-35` **PARTIAL:** host-only loss/gradient/optimizer plan controller composes loss→gradient_accumulate→clip→moving_average→update and returns typed UNAVAILABLE until native kernels exist. Hyperparameter records and finite-difference fixtures remain open.
- [ ] `B-36` **PARTIAL:** host-only `SequenceController` composes embedding_gather→position_add→slice_window→mask_apply→ngram_build with optional head_concat as a validated `MthPlan`, returning typed `UNAVAILABLE` for all missing declared kernels. 13 controller tests pass; native token/sequence kernels remain open.
- [ ] `B-37` **PARTIAL:** host-only sampling/output controller composes logit scale/temperature/penalties/top-k/top-p/normalize/sample or greedy tie-break; missing native kernels return typed UNAVAILABLE.

## B4. Semantics/evidence/layers

- [ ] `B-40` Exact/approximate/warning/resource-exhaustion status model.
- [ ] `B-41` Transformation record with evidence list, measured cost, hardware, lineage.
- [ ] `B-42` Shared-subexpression/incremental-recompute dependency graph.
- [ ] `B-43` Unified evidence ladder per operation (Defined→…→Promoted).
- [ ] `B-44` **PARTIAL:** `spec/nan-native-boundary.json` and `tools/audit_nan_native.py` statically cover L0–L7 kernel assignment, every registered MTH source/fixture/runner/CI path, explicit HERMES-guest exclusions, and forbidden host numeric imports. The audit is green but is static coverage, not a formal numerical-equivalence proof.
- [ ] `B-45` Stage 2–6 gates and typed descriptors.
- [ ] `B-46` Tier 6 expression algebra/SAT/polynomial/proof checker.
- [ ] `B-47` Data-word allocation gate and unknown-pattern behavior.

---

# C. `game_plan_foundations.md` completion

- [ ] `C-01` Directed relation matrix `W`, symmetric/antisymmetric split.
- [ ] `C-02` K256 spectrum/multiplicity/eigenpair oracles and random PSD tests.
- [ ] `C-03` Annular embedding: `(r,θ)`, shells, `r_min/r_max`, boundary-band metric.
- [x] `C-04` Freeze void formula and add alpha/shell sweep. **PARTIAL:** canonical `α/(r²+ε²)` is frozen in the plan; alpha/shell sweep remains open.
- [ ] `C-05` Dense/symmetric 256 eigensolver with residual/orthogonality certificates.
- [ ] `C-06` Modal reconstruction and long-run/multi-dt/scale stability tests.
- [ ] `C-07` Centrosymmetry folded eigensolve and 128+128 basis.
- [ ] `C-08` Bit-reversal address mapping and transpose convention.
- [ ] `C-09` Circulant detector/FFT path and guarded fallback.
- [ ] `C-10` Product-space separable potential `V_x⊗I+I⊗V_y`.
- [ ] `C-11` General Kronecker oracle and product eigenpair tests.
- [ ] `C-12` Standing-wave expansion/mode accounting/adaptive selection.
- [ ] `C-13` Topology256/WaveOperator/SpectralModel/WaveState/ProductWaveState records.
- [ ] `C-14` ExperimentRecord with embedding version, parameters, precision, normalization, seed.
- [ ] `C-15` Network peer auth, quotas/timeouts, provenance, untrusted-result validation.
- [ ] `C-16` Clock/drift/phase/delay model.
- [ ] `C-17` NaN payload/tag codec and FP64 reference.
- [ ] `C-18` LM adapter real integration; FILTER/spectral response; context/memory/multi-path/contradiction/novelty modules.

---

# D. `GRAPH_SPECTRAL_MTH_PLAN.md` completion

- [x] `D-01` Graph core modules: degree, CSR Laplacian (unweighted Q16.16), and RSS contract checker are implemented and locally verified.
- [ ] `D-02` **PARTIAL:** bounded degree-2 Q16.16 graph filter `y=c0*x+c1*Lx+c2*L²x` over canonical CSR is locally verified; Chebyshev recurrence, adaptive coefficients, and dense/eigensystem filtering remain open.
- [ ] `D-03` **PARTIAL:** `mth_graph_pattern.nas` implements degree/shell/neighborhood signatures; motifs, components, deltas, spectral signatures, and confidence metadata remain open.
- [x] `D-04` Host-only RSS verb controller composes ENCODE/QUERY/MATCH/FILTER/DRIVE/PROPAGATE/FOLD/DECODE into validated `MthPlan`s; FILTER remains typed UNAVAILABLE until a dispatchable CI-verified kernel exists. Controller does not execute.
- [ ] `D-05` K256 degree/all-ones/sum-zero/spectrum oracle tests.
- [ ] `D-06` Explicit small-Kronecker oracle tests.
- [ ] `D-07` C256/non-circulant Lanczos Ritz residual/orthogonality.
- [ ] `D-08` Plan-composition equivalence and paged-vs-dense equivalence.
- [ ] `D-09` Native full 256-tile grid and atomic publication.
- [ ] `D-10` Radial descriptor/ABI artifact and α/β sweep.
- [ ] `D-11` NANNET0 persistence/signature exchange/page refs/output-digest check.
- [ ] `D-12` Full-grid guest/reference equality on all 256 tiles.
- [ ] `D-13` Update stale step counts/digests, kernel count (63), and 1 MiB references.

---

# E. `DEEP_PLAN_CONT.md` completion

- [x] `E-01` Page-record table with owner/pin/digest/version/generation/atomic publication and a file-backed 32 KiB page provider.
- [ ] `E-02` Executor paging + native dispatch + evidence capture.
- [ ] `E-03` Result/evidence contract beyond digest.
- [x] `E-04` Plan validator shape/precision/layout/alias/domain/fuel/cancel checks (executor enforcement of fuel/cancel remains open).
- [x] `E-05` Point-0 v2 envelope fields (`point_zero`, `nan_word_count`, `result_status`), strict validation, legacy v1 compatibility, and expected result/output digest verification.
- [ ] `E-06` Page-map digest and page-map digest in descriptor.
- [x] `E-07` NANNET0 MC0DB persistence, generation history, duplicate/point constraints, revocation, and digest/signature metadata (cryptographic signature verification remains external).
- [ ] `E-08` Capacity-vs-SNR synthetic harness with six gate conditions; real measurement blocked.
- [ ] `E-09` Complete Appendix A to 63 rows (missing preflight/admission).
- [ ] `E-10` Fix stale kernel/test counts and 1 MiB references.

---

# F. `R5_CAPACITY_SNR_PLAN.md` completion

- [x] `F-01` Define SNR/seed manifest and sweep configuration.
- [x] `F-02` Build deterministic synthetic frozen-model stub harness.
- [x] `F-03` Implement matched control, coupled candidate, zero/random coupling, shuffled memory, matched-variance noise.
- [x] `F-04` Implement capacity-at-SNR, paired delta CI, false-match rate, steps/memory metrics.
- [x] `F-05` Enforce all six `supported` gate conditions; report remains synthetic-only and non-promotable.
- [ ] `F-06` Real frozen-model/data measurement — **BLOCKED** until model/data available.
- [ ] `F-07` Live Koyeb/NANNET0 — **BLOCKED** on real deployment credentials. The root image now has a SIGTERM handler, Docker `HEALTHCHECK`, credential-free `/healthz` runtime declaration, and a container smoke workflow; none of that is a live deployment claim.
- [ ] `F-08` Signed volume registry — **BLOCKED** on real provider IDs and mounted volumes. `runner_riddle/koyeb_bootstrap.py` initializes tier databases, chains registry generations, refuses partial configuration, and supports strict fail-closed mode; a missing registry reports `unknown`, never green.
- [ ] `F-09` Production MC0DB — **BLOCKED**.
- [x] `F-10` No page-size limit — the guest budget is adjustable and reports `page_limit_enforced=false`; 32 KiB is only the logical 8 MiB-universe page unit. No runtime page-size gate exists.

---

# G. Immediate execution order

## Batch 1 — native substrate truth
1. `B-04` register all existing native kernels (including `mth_negate256`).
2. `B-01` machine-readable Stage 0 layout.
3. `B-02` add Stage 0/double-endian/vector/arithmetic fixtures to CI.
4. `B-20`–`B-22` typed vector operations or explicitly freeze a smaller v1.
5. `A-03`/`A-04` enumerate A/T tests and freeze vocabulary.

## Batch 2 — execution/storage closure
1. `A-18`/`A-75` wire NMP ledger into bridge.
2. `A-19`/`A-20` full admission and rule/auth revalidation tests.
3. `A-21` alternate submit-path guard.
4. `A-36` ledger health/evidence.
5. `A-39`/`E-01` page records.
6. `A-54` contract digest/dedupe.

## Batch 3 — graph/spectral foundations
1. `C-01`–`C-04` directed/annulus/void.
2. `C-05`–`C-07` eigensolver/fold/residual.
3. `D-01`–`D-04` graph core/filter/pattern/RSS controller.
4. `D-05`–`D-09` oracles/equivalence/native grid.

## Batch 4 — learning/security
1. `A-95` discovery persistence/wiring.
2. `A-96` Boolean-head learning integration.
3. `A-97`–`A-105` Class C/ACL/scratch/audit/refutation.
4. `A-124` real execute HTTP service.

## Batch 5 — blocked/external
1. `F-06`–`F-10`, `A-23`, `D-11` only with real evidence.
2. Keep `spec/p13-gates.json` blocked until then.

---

## Definition of done

- Every unchecked item either has passing code/tests or an explicit blocked record with required evidence.
- No source-only kernel is described as CI/native-verified.
- No host arithmetic or alternate execution path bypasses NMP/admission/ring/JAHS.
- Full suite green; native fixtures and canonical CI status reflected accurately.
- Docs, counts, and evidence ladders agree with the code.
