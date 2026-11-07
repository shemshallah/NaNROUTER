# R10 implementation evidence ledger

**Date:** 2026-11-06
**Toolchain:** canonical NaN0S source assembler (`nan0s/tools/nmk.awk`) and `aarch64/android/nan_cli`
**Result:** 21/21 native MTH fixtures passed locally and in GitHub Actions run `42352593144`; 111 Python tests passed.
**CI:** the expanded `mth-native-contract` workflow passed all 43 steps on `main` for commit `bbc9d10`.

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
| 21 | Harmonic wave energy | `mth/tests/mth_harmonic_wave_energy_test.nas` | 53,877 | PASS | pending |

## Python tests

```
python3 -m unittest discover -s tests -v
Ran 111 tests
OK
```

Covered:

- existing address/cache/trace/ring/volume/HTTP tests;
- `WaveStore` BS0DB/MC0DB lifecycle, leases, capability filtering, seals, signatures;
- 255-head C255 ring CSR/page map;
- per-universe NANNET node binding (8 tests);
- wave aperture descriptor/decomposition selector (9 tests);
- wave adapter contract (7 tests);
- capability manifest registration into MC0DB (4 tests).

## Fixture runner

```
python3 tools/run_mth_fixtures.py
21/21 fixtures passed
```

Run it after any kernel change.

## Capability manifest

`spec/wave-capabilities.json` records 21 kernels, source/fixture paths, markers, local step counts, precision, workspace, and CI status. `tools/register_wave_capabilities.py` hashes the source/fixture and registers operator/capability rows in MC0DB through `WaveStore`.

## What is not yet proven

- No full wave run with repeated `H` application, CFL guard, damping sweep, and energy-conservation trace exists yet.
- No aperture SVD/power iteration, Lanczos, or QUERY/MATCH/FILTER/DRIVE composition exists yet.
- No full 256×256 pair space; only the bounded 128×128 prototype.
- No NANNET HTTP node integration beyond the ring port descriptor and storage plane.
- No LM adapter residual or ablation result; only the adapter contract.
- No claim of intelligence, creativity, quantum tunneling, or consciousness.
