# R10 implementation evidence ledger

**Date:** 2026-11-07
**Latest pair-tile CI:** run 218 (`42388101426`), two tile origins verified, 4,643,414 guest steps.
**Bounded K16 pair tile:** canonical NaN16 CI run 242, 283,436 guest steps, 1,542-word workspace.
**Toolchain:** canonical NaN0S source assembler (`nan0s/tools/nmk.awk`) and `aarch64/android/nan_cli`
**Result:** 56/56 locally runnable fixtures passed; 57/57 total including CI-only K256 pair; 342 Python tests passed.
**CI:** the expanded workflow last passed 87 steps on `main` for the historical 42-fixture set; the current 57-fixture/117-step run is pending (local 1 MiB text-loader execution passed).

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
| 44 | Full 256 matvec | `mth/tests/mth_matvec256_full_test.nas` | 2,978,362 | PASS | pending |
| 45 | Full 256 ENCODE | `mth/tests/mth_encode_decode256_test.nas` | 1,655,853 | PASS | pending |
| 46 | Full 256 DECODE | `mth/tests/mth_encode_decode256_test.nas` | 1,655,853 | PASS | pending |
| 47 | Full 256 SVD top pair | `mth/tests/mth_svd_top256_test.nas` | 11,002,235 | PASS | pending |
| 48 | JAHS handoff gate | `mth/tests/mth_jahs_gate_test.nas` | 201 | PASS | pending |
| 49 | Full 256 adapter residual | `mth/tests/mth_adapter_residual_256_full_test.nas` | 2,839,172 | PASS | pending |
| 50 | Avoided-crossing sweep | `mth/tests/mth_avoided_crossing_sweep_test.nas` | 11,651 | PASS | pending |
| 51 | Full 255 certificate | `mth/tests/mth_centrosymmetry_255_full_test.nas` | 2,700,726 | PASS | pending |
| 52 | Full 256 SVD top-2 | `mth/tests/mth_svd_top2_256_test.nas` | 40,216,927 | PASS | pending |
| 53 | Stable top-k 256 | `mth/tests/mth_topk_256_test.nas` | 1,158,106 | PASS | pending |
| 54 | DRIVE source 256 | `mth/tests/mth_drive_source_256_test.nas` | 13,092 | PASS | pending |
| 55 | CFL guard 256 | `mth/tests/mth_cfl_guard_256_test.nas` | 2,639,509 | PASS | pending |
| 56 | Radial tridiagonal | `mth/tests/mth_radial_tridiagonal_test.nas` | 42,518 | PASS | pending |
| 57 | Colored noise 256 | `mth/tests/mth_colored_noise_256_test.nas` | 72,318 | PASS | pending |
| 58 | Lanczos top-k 256 | `mth/tests/mth_lanczos_256_test.nas` | 133,498,079 | PASS | pending |
| 59 | K16 full-slice driver | `mth/tests/mth_graph_pair_tile16_k16_driver_f32_test.nas` | 4,449,894 | PASS | pending |

## Python tests

```
python3 -m unittest discover -s tests -v
Ran 235 tests
OK
```

Covered:

- existing address/cache/trace/ring/volume/HTTP tests;
- `WaveStore` BS0DB/MC0DB lifecycle, leases, capability filtering, seals, signatures;
- 255-head C255 ring CSR/page map;
- per-universe NANNET node binding (8 tests);
- wave aperture descriptor/decomposition selector (9 tests);
- wave adapter contract (7 tests);
- authenticated WaveService submit/worker/admin facade (13 tests);
- MTH system registry/planner (26 tests);
- single-active runner-ring scheduler (27 tests);
- standalone authenticated Wave HTTP adapter (12 tests);
- point-0 NaN/binary bridge and active-slot router (35 tests);
- MthSystem runtime facade (11 tests);
- capability manifest registration into MC0DB (4 tests).

## Fixture runner

```
python3 tools/run_mth_fixtures.py
56/56 local fixtures passed; 57/57 total
```

Run it after any kernel change.

## Capability manifest

`spec/wave-capabilities.json` records 59 kernels, source/fixture paths, markers, local step counts, precision, workspace, and CI status. `tools/register_wave_capabilities.py` hashes the source/fixture and registers operator/capability rows in MC0DB through `WaveStore`. A local dry run currently reports **59 kernels**; production registration remains gated on the deployed BS0DB/MC0DB.

## What is not yet proven

- No long-run CFL/damping sweep with a paged graph operator and trace exists yet; the four-step C256 energy fixture is bounded.
- Full 256 matvec, SVD top pair, SVD top-2, ENCODE/DECODE, adapter residual, full 255 certificate, stable top-k, JAHS gate, and avoided-crossing sweep pass locally; canonical 1 MiB CI and Lanczos remain open.
- K256 closed-form 256×256 pair exists; the general 16×16 pair tile is native_verified in CI run 218; the Python 256-tile page-window/atomic-publication layer and 31 tests exist; a native full-grid driver and generic sparse-CSR pair action remain open.
- Wave and point-0 HTTP adapters exist; the offline live preflight/signed-volume gate exists; live Koyeb/NANNET0 deployment remains blocked on real credentials and network.
- Full 256 adapter residual and a frozen-base ablation harness exist, but no real LM/data ablation or held-out benefit exists; the adapter remains disabled.
- R7 protocol harness and native sweep exist; no real held-out LM/data experiment or creativity claim exists.
- No claim of intelligence, creativity, quantum tunneling, or consciousness.
