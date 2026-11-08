# R10 implementation evidence ledger

**Date:** 2026-11-07
**Guest update:** owner reports GLT is now 2 MiB and adjustable; the 1 MiB evidence below is the compatibility baseline. The 2 MiB integration gate is tracked in `docs/GAME_PLAN_::.md` and `docs/IMPLEMENTATION_TODO.md`.
**Latest pair-tile CI:** run 218 (`42388101426`), two tile origins verified, 4,643,414 guest steps.
**Bounded K16 pair tile:** canonical NaN16 CI run 242, 283,436 guest steps, 1,542-word workspace.
**Toolchain:** canonical NaN0S source assembler (`nan0s/tools/nmk.awk`) and `aarch64/android/nan_cli`
**Result:** The newly registered native/graph fixtures passed locally (Stage 0, double-endian, vector, typed preflight, native dispatch, graph degree/pattern/filter, CSR Laplacian, RSS contract, vector arithmetic, matrix operations, and arg reductions); 66/66 prior local baseline; last canonical CI run 42405649076 predates the new registrations and passed 132 steps for 61 fixtures; 1074 Python tests passed (8 skipped).
**CI:** canonical run `42405649076` passed all 132 steps for the 61-fixture set, including the operand-range alias regressions, native preflight, and composed admission. GLT-enforced page-limit verification remains a separate pending gate.

## Native fixtures

| # | Kernel | Fixture | Steps | Local result | CI |
|---:|---|---|---:|---|---|
| 1 | K256 Laplacian | `mth/tests/mth_k256_laplacian_test.nas` | 5,391 | PASS | yes |
| 2 | K255 head-only Laplacian | `mth/tests/mth_k255_laplacian_test.nas` | 5,881 | PASS | yes |
| 3 | C255 head-ring Laplacian | `mth/tests/mth_ring255_laplacian_test.nas` | 12,485 | PASS | yes |
| 4 | 255+1 port assembly | `mth/tests/mth_ring255_port_test.nas` | 3,353 | PASS | yes |
| 5 | Sparse unweighted Laplacian | `mth/tests/mth_sparse_graph_laplacian_test.nas` | 20,743 | PASS | yes |
| 6 | Weighted sparse Laplacian v2 | `mth/tests/mth_sparse_weighted_graph_laplacian_v2_test.nas` | 41,253 | PASS | yes |
| 7 | Weighted graph energy | `mth/tests/mth_graph_energy_weighted_u8_q32_32_test.nas` | 60,569 | PASS | yes |
| 8 | Connected components | `mth/tests/mth_graph_components_256_test.nas` | 29,931 | PASS | yes |
| 9 | Fold/unfold vectors | `mth/tests/mth_graph_fold_test.nas` | 9,281 | PASS | yes |
| 10 | Float32 dot | `mth/tests/mth_dot256_test.nas` | 9,144 | PASS | yes |
| 11 | Float32 norm | `mth/tests/mth_norm256_test.nas` | 6,842 | PASS | yes |
| 12 | Float32 axpy | `mth/tests/mth_axpy256_test.nas` | 8,389 | PASS | yes |
| 13 | Void potential | `mth/tests/mth_graph_void_test.nas` | 20,623 | PASS | yes |
| 14 | Wave velocity-Verlet step | `mth/tests/mth_graph_wave_test.nas` | 65,088 | PASS | yes |
| 15 | Step energy metric | `mth/tests/mth_graph_step_energy_256_test.nas` | 7,956 | PASS | yes |
| 16 | Full 128×128 pair action | `mth/tests/mth_graph_pair_test.nas` | 68,195,822 | PASS | yes |
| 17 | Rank-1 128 pair action | `mth/tests/mth_graph_pair_rank1_128_test.nas` | 252,060 | PASS | yes |
| 18 | 256-point DFT reference | `mth/tests/mth_graph_dft256_test.nas` | 8,958,287 | PASS | yes |
| 19 | Two-region coupling | `mth/tests/mth_graph_couple_128_test.nas` | 8,637 | PASS | yes |
| 20 | Transmission metric | `mth/tests/mth_graph_transmission_128_test.nas` | 7,147 | PASS | yes |
| 21 | Harmonic wave energy | `mth/tests/mth_harmonic_wave_energy_test.nas` | 53,877 | PASS | yes |
| 22 | 128×128 matvec | `mth/tests/mth_matvec128_test.nas` | 249,914 | PASS | yes |
| 23 | 128×128 centrosymmetry | `mth/tests/mth_centrosymmetry_128_test.nas` | 676,252 | PASS | yes |
| 24 | 256-cosine match | `mth/tests/mth_cosine256_test.nas` | 17,189 | PASS | yes |
| 25 | Damped harmonic energy | `mth/tests/mth_harmonic_damped_energy_test.nas` | 53,890 | PASS | yes |
| 26 | C256 ring Laplacian | `mth/tests/mth_ring256_laplacian_test.nas` | 19,736 | PASS | yes |
| 27 | C256 graph-H energy | `mth/tests/mth_ring_wave_energy_test.nas` | 86,374 | PASS | yes |
| 28 | 255-point DFT | `mth/tests/mth_graph_dft255_test.nas` | 6,666,266 | PASS | yes |
| 29 | 128×128 power iteration | `mth/tests/mth_power_iter128_test.nas` | 758,847 | PASS | yes |
| 30 | Rank-1 low-rank add | `mth/tests/mth_lowrank_add_128_test.nas` | 1,056,470 | PASS | yes |
| 31 | 128 adapter residual | `mth/tests/mth_adapter_residual_128_test.nas` | 420,587 | PASS | yes |
| 32 | 256 block matvec | `mth/tests/mth_matvec256_block16_test.nas` | 148,561 | PASS | yes |
| 33 | 256 streaming certificate | `mth/tests/mth_centrosymmetry_block16_test.nas` | 337,623 | PASS | yes |
| 34 | K256 pair-space | `mth/tests/mth_k256_pair_space_v1_test.nas` | 2,300,711 | PASS (CI run 180) | yes |
| 35 | General dense 256 pair-space tile16 | `mth/tests/mth_graph_pair_tile16_f32_test.nas` | 4,643,414 | PASS (CI run 218) | yes |
| 36 | ENCODE 256→128 | `mth/tests/mth_encode_decode_test.nas` | 996,358 | PASS | yes |
| 37 | DECODE 128→256 | `mth/tests/mth_encode_decode_test.nas` | 996,358 | PASS | yes |
| 38 | 128×128 SVD top pair | `mth/tests/mth_svd_top128_test.nas` | 1,311,632 | PASS | yes |
| 39 | 255 odd certificate | `mth/tests/mth_centrosymmetry255_block15_test.nas` | 653,687 | PASS | yes |
| 40 | Bounded K16 streaming pair tile | `mth/tests/mth_graph_pair_tile16_k16_f32_test.nas` | 283,436 | PASS (CI run 242) | yes |
| 41 | Two-level spectrum | `mth/tests/mth_two_level_spectrum_test.nas` | 390 | PASS | yes |
| 42 | 128 phase coherence | `mth/tests/mth_phase_coherence_128_test.nas` | 11,381 | PASS | yes |
| 43 | 256-block adapter residual | `mth/tests/mth_adapter_residual_256_block16_test.nas` | 113,055 | PASS | yes |
| 44 | Full 256 matvec | `mth/tests/mth_matvec256_full_test.nas` | 2,978,362 | PASS | yes |
| 45 | Full 256 ENCODE | `mth/tests/mth_encode_decode256_test.nas` | 1,655,853 | PASS | yes |
| 46 | Full 256 DECODE | `mth/tests/mth_encode_decode256_test.nas` | 1,655,853 | PASS | yes |
| 47 | Full 256 SVD top pair | `mth/tests/mth_svd_top256_test.nas` | 11,002,235 | PASS | yes |
| 48 | JAHS handoff gate | `mth/tests/mth_jahs_gate_test.nas` | 201 | PASS | yes |
| 49 | Full 256 adapter residual | `mth/tests/mth_adapter_residual_256_full_test.nas` | 2,839,172 | PASS | yes |
| 50 | Avoided-crossing sweep | `mth/tests/mth_avoided_crossing_sweep_test.nas` | 11,651 | PASS | yes |
| 51 | Full 255 certificate | `mth/tests/mth_centrosymmetry_255_full_test.nas` | 2,700,726 | PASS | yes |
| 52 | Full 256 SVD top-2 | `mth/tests/mth_svd_top2_256_test.nas` | 40,216,927 | PASS | yes |
| 53 | Stable top-k 256 | `mth/tests/mth_topk_256_test.nas` | 1,158,106 | PASS | yes |
| 54 | DRIVE source 256 | `mth/tests/mth_drive_source_256_test.nas` | 13,092 | PASS | yes |
| 55 | CFL guard 256 | `mth/tests/mth_cfl_guard_256_test.nas` | 2,639,509 | PASS | yes |
| 56 | Radial tridiagonal | `mth/tests/mth_radial_tridiagonal_test.nas` | 42,518 | PASS | yes |
| 57 | Colored noise 256 | `mth/tests/mth_colored_noise_256_test.nas` | 72,318 | PASS | yes |
| 58 | Lanczos top-k 256 | `mth/tests/mth_lanczos_256_test.nas` | 133,628,629 | PASS | yes |
| 59 | K16 full-slice driver | `mth/tests/mth_graph_pair_tile16_k16_driver_f32_test.nas` | 4,449,894 | PASS | yes |
| 60 | Reachability 256 | `mth/tests/mth_reachability_256_test.nas` | 2,489,116 | PASS | yes |
| 61 | Radial energy/localization | `mth/tests/mth_radial_energy_test.nas` | 61,373 | PASS | yes |
| 62 | Native preflight gate | `mth/tests/mth_preflight_gate_test.nas` | 336 | PASS | yes |
| 63 | Composed admission | `mth/tests/mth_admission_test.nas` | 931 | PASS | yes |
| 64 | Boolean functions | `mth/tests/mth_bool2_test.nas` | 458 | PASS | local only |
| 65 | Bitwise/compare | `mth/tests/mth_bitwise_test.nas` | 312 | PASS | local only |
| 66 | Checked integer | `mth/tests/mth_integer_test.nas` | 245 | PASS | local only |
| 67 | Shift | `mth/tests/mth_shift_test.nas` | 338 | PASS | local only |
| 68 | Wide multiply | `mth/tests/mth_multiply_test.nas` | 1,578 | PASS | local only |
| 69 | Divide/mod | `mth/tests/mth_divide_test.nas` | 2,062 | PASS | local only |
| 70 | Negate 256 (composite) | `mth/tests/mth_ring_wave_energy_test.nas` | 86,374 | PASS | yes |
| 71 | Stage 0 word layout | `mth/tests/mth_stage0_test.nas` | 1,161 | PASS | local only |
| 72 | Double-endian pair codec | `mth/tests/mth_double_endian_test.nas` | 545 | PASS | local only |
| 73 | Vector span add | `mth/tests/mth_vector_test.nas` | 381 | PASS | local only |
| 74 | Typed preflight | `mth/tests/mth_preflight_test.nas` | 2,780 | PASS | local only |
| 75 | Native dispatch | `mth/tests/mth_linker_preflight_test.nas` | 16,047 | PASS | local only |
| 76 | Graph degree 256 | `mth/tests/mth_graph_degree_test.nas` | 48,117 | PASS | local only |
| 77 | Graph pattern 256 | `mth/tests/mth_graph_pattern_test.nas` | 56,063 | PASS | local only |
| 78 | Graph filter poly2 | `mth/tests/mth_graph_filter_test.nas` | 621,536 | PASS | local only |
| 79 | CSR Laplacian | `mth/tests/mth_graph_laplacian_csr_test.nas` | 197,118 | PASS | local only |
| 80 | RSS contract | `mth/tests/mth_rss_contract_test.nas` | 6,504 | PASS | local only |
| 81 | Vector add 256 f32 | `mth/tests/mth_vector_add256_f32_test.nas` | 10,436 | PASS | local only |
| 82 | Vector sub 256 f32 | `mth/tests/mth_vector_sub256_f32_test.nas` | 10,484 | PASS | local only |
| 83 | Vector mean 256 f32 | `mth/tests/mth_vector_mean256_f32_test.nas` | 15,969 | PASS | local only |
| 84 | Vector abs 256 f32 | `mth/tests/mth_vector_abs256_f32_test.nas` | 5,328 | PASS | local only |
| 85 | Vector relu 256 f32 | `mth/tests/mth_vector_relu256_f32_test.nas` | 6,615 | PASS | local only |
| 86 | Vector scale 256 f32 | `mth/tests/mth_vector_scale256_f32_test.nas` | 82,168 | PASS | local only |
| 87 | Matrix transpose 256 | `mth/tests/mth_matrix_transpose256_f32_test.nas` | 3,290,464 | PASS | local only |
| 88 | Matrix diagonal 256 | `mth/tests/mth_matrix_diagonal256_f32_test.nas` | 9,865 | PASS | local only |
| 89 | Matrix add 256 | `mth/tests/mth_matrix_add256_f32_test.nas` | 2,500,024 | PASS | local only |
| 90 | Vector argmax 256 | `mth/tests/mth_vector_argmax256_f32_test.nas` | 62,218 | PASS | local only |
| 91 | Vector argmin 256 | `mth/tests/mth_vector_argmin256_f32_test.nas` | 61,708 | PASS | local only |

## Python tests

```
python3 -m unittest discover -s tests -q
Ran 1074 tests in 142.986s
OK (skipped=1)
```

Covered:

- existing address/cache/trace/ring/volume/HTTP tests;
- `WaveStore` BS0DB/MC0DB lifecycle, leases, capability filtering, seals, signatures;
- 255-head C255 ring CSR/page map;
- per-universe NANNET node binding (8 tests);
- wave aperture descriptor/decomposition selector (9 tests);
- wave adapter contract (7 tests);
- authenticated WaveService submit/worker/admin facade (13 tests);
- MTH system registry/planner and peak-liveness admission (29 tests);
- single-active runner-ring scheduler with export/restore epoch recovery (30 tests);
- standalone authenticated Wave HTTP adapter (12 tests);
- point-0 NaN/binary bridge and active-slot router (35 tests);
- MthSystem runtime facade (16 tests);
- capability manifest registration into MC0DB (4 tests);
- mathematical objects/store/registry/validity/linker/runtime (P1–P4, P6);
- typed absence algebra (P7, 59 tests);
- relations/hyperedges (P8, 9 tests);
- rule-learning lifecycle with optional typed authorization enforcement (P9, 26 tests);
- retention/oscillation/pruning (P10, 10 tests);
- lane registry (P11, 18 tests);
- bounded work queues/stealing (P11, 8 tests);
- ring state/epoch export-restore (30 scheduler tests);
- Boolean-head experiment gate with leakage/control/shuffled checks (10 tests);
- NMP and native admission-receipt binding (P5, 60 tests);
- authority-hardened host execution bridge with candidate/snapshot/function-version/selected-kernel binding, rule-snapshot revalidation, durable-job reread, pre-dispatch lease/deadline validation, disabled direct runtime submit, and token redaction (P5, 12 tests);
- negative execution suite A06/A09–A12 (8 tests);
- cross-store math commit intent/finalize and crash recovery (P6, 12 tests);
- `NmpPlan` v2 context wrapper around the frozen `MthPlan` v1 (5 tests);
- bounded lane work queues and capability-safe stealing (P11, 8 tests);
- typed math authorization policy with separation-of-duty (P9/§15, 9 tests);
- standard-library `/v1/math/health|link|execute` ingress with 2 MiB bounds, prepared-lease execution, and token redaction (30 tests);
- NMP HTTP submit/lease/complete control plane and N16T binary worker handoff;
- durable N16T session/replay checkpointing with restart restore and replay rejection;
- plan handoff validation for shape/precision/layout/domain/alias/fuel/cancel (54 registry/system tests);
- optional principal ACL enforcement on all math-store reads/writes;
- worker token-digest binding and Class C policy-transition guard;
- oracle-strength T/A verification extra (10 tests);
- native graph degree, pattern, and degree-2 polynomial filter kernels, locally verified;
- file-backed 32 KiB page provider with digest/checksum/traversal validation (11 tests);
- semantic type descriptors with element/stride/layout/units/rank/context and composition handoff checks (12 tests);
- NMP packet/input/history/evidence bounds;
- synthetic capacity-vs-SNR harness with six R5 gates and explicit non-promotable synthetic-only status (14 tests);
- point-0 v2 envelope binding and NANNET0 MC0DB persistence;
- durable universe page records with generation CAS and page-map digest (12 tests);
- typed execution evidence beyond a result digest (5 tests);
- end-to-end control-plane demo with complete output-leaf provenance (P12, 2 tests).

## Math integration evidence (P0–P12)

- Peak-liveness admission: dependent plans are admitted by `MthRegistry.plan_workspace_peak`; undeclared-liveness plans keep the v1 sum. Exact-bound and bound-minus-one tests pass in `tests/test_mth_registry.py` and `tests/test_mth_system.py`.
- Authority/JAHS binding: `MathExecutionBridge` refuses inactive/stale/unsealed rings, missing capability coverage, tampered candidate/admission bindings, and stale generations; it leases only the active slot and releases ring resources exactly once.
- NMP validates native NaN16 admission receipts against packet candidate/rule/preflight digests, epoch, operands, capability snapshot, guest ALLOW status, and receipt digest, then binds the receipt to one live job/lease/ring/JAHS snapshot before execution. Receipt production remains the native `mth_admit` caller's responsibility.
- NMP packets bind admission candidates/snapshots/preflight digests and are projected back from WaveStore job/lease rows after restart.
- The runtime accepts optional rule/capability providers and binds them into preflight snapshots. The bridge revalidates the current rule snapshot at submit, lease, and pre-dispatch; a post-lease rule change blocks the executor.
- The math store implements a crash-consistent BS0DB/MC0DB intent/evidence/finalize protocol with idempotent recovery and no partial active mapping.
- `MathStore.health()` and `MathRuntime.health()` provide token-free schema/version/count/status projections; `MthSystem.health(math_health=...)` composes them.
- Scratch leaves are invisible to the linker unless explicitly allowed; quarantined/tombstoned/superseded leaves are never linkable.
- The demo runs leaf → `::` → preflight → NMP queue → lease → execute completion → commit → output feedback. Its output leaf carries parents, function/version, ruleset snapshot, plan digest, and JAHS/ring/job/runner provenance. Its executor callback returns an evidence digest, not a numeric dot product; the report labels this explicitly.

## Fixture runner

```
python3 tools/run_mth_fixtures.py
87 local fixtures registered; newly registered local-only fixtures passed locally
```

Run it after any kernel change.

## Capability manifest

`spec/wave-capabilities.json` records 91 kernels, source/fixture paths, markers, local step counts, precision, workspace, and CI status. `tools/register_wave_capabilities.py` hashes the source/fixture and registers operator/capability rows in MC0DB through `WaveStore`. A local dry run currently reports **91 kernels**; production registration remains gated on the deployed BS0DB/MC0DB.

## What is not yet proven

- No long-run CFL/damping sweep with a paged graph operator and trace exists yet; the four-step C256 energy fixture is bounded.
- Full 256 matvec, SVD top pair, SVD top-2, ENCODE/DECODE, adapter residual, full 255 certificate, stable top-k, Lanczos, JAHS gate, avoided-crossing sweep, radial, DRIVE/CFL, colored noise, and K16 driver pass locally; GLT page-limit enforcement remains open.
- K256 closed-form 256×256 pair exists; the general 16×16 pair tile is native_verified in CI run 218; the Python 256-tile page-window/atomic-publication layer and 31 tests exist; a native full-grid driver and generic sparse-CSR pair action remain open.
- Wave and point-0 HTTP adapters exist; the offline live preflight/signed-volume gate exists; live Koyeb/NANNET0 deployment remains blocked on real credentials and network.
- Full 256 adapter residual and a frozen-base ablation harness exist, but no real LM/data ablation or held-out benefit exists; the adapter remains disabled.
- R7 protocol harness and native sweep exist; no real held-out LM/data experiment or creativity claim exists.
- P13 live/experiment gates remain blocked: no live Koyeb/NANNET0 deployment, signed volume-registry verification, production MC0DB registration, frozen-model LM ablation, R7 held-out result, capacity-vs-SNR measurement, or native numeric executor delivery has been produced.
- The P12 demo proves control-plane integration only; it does not compute a numeric dot product. Native numeric execution remains the external executor's responsibility.
- No trusted proof checker exists, so production validity remains capped at V2 and proof candidates remain unchecked.
- No claim of intelligence, creativity, quantum tunneling, or consciousness.
