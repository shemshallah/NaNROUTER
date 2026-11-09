# R10 implementation evidence ledger

**Date:** 2026-11-08
**Guest update:** there is no page-size limit. The guest budget is 2 MiB and adjustable; the 1 MiB evidence below is the compatibility baseline. The 32 KiB page is only the logical unit of the 8 MiB universe layout. See `docs/GAME_PLAN_::.md` and `docs/IMPLEMENTATION_TODO.md`.
**Latest pair-tile CI:** run 218 (`42388101426`), two tile origins verified, 4,643,414 guest steps.
**Bounded K16 pair tile:** canonical NaN16 CI run 242, 283,436 guest steps, 1,542-word workspace.
**Toolchain:** canonical NaN0S source assembler (`nan0s/tools/nmk.awk`) and `aarch64/android/nan_cli`
**Result:** The registered native/graph fixtures passed locally (Stage 0, double-endian, vector, typed preflight, native dispatch, graph degree/pattern/filter, CSR Laplacian, RSS contract, vector arithmetic, matrix operations, arg reductions, normalize, inclusive prefix sum, xorshift64, and the exhaustive 8 MiB universe map); the full local Python suite is green (see the run block below). The four 2026-11-08 kernels are now `ci_verified=true` in canonical run `42539617226`; all 127 manifest kernels are CI-verified.
**CI:** canonical run `42405649076` passed all 132 steps for the 61-fixture set, including the operand-range alias regressions, native preflight, and composed admission. Canonical run `42539617226` then passed the 31-fixture remaining promotion set, including normalize, prefix sum, xorshift64, and the full 8 MiB universe map. Run `42542521347` re-passed that set on commit `0fdb60c`; run `42542521393` passed `mth-native-contract`; run `42542521540` passed the manifest contract; run `42542521266` passed the credential-free Koyeb container smoke check. Run `42546293200` passed the 41-fixture set with the ten vector/full-grid additions; run `42547371933` passed the 47-fixture set with exp/log/logsumexp/sigmoid/tanh/sequence; runs `42547914257` and `42549422834` re-passed `mth-native-contract` and the container smoke on the unified catalog. No page-size limit is enforced; the guest budget is adjustable and reports `page_limit_enforced=false`.

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
| 34 | K256 pair-space | `mth/tests/mth_k256_pair_space_v1_test.nas` | 2,300,455 | PASS (CI run 180; local recount) | yes |
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
| 64 | Boolean functions | `mth/tests/mth_bool2_test.nas` | 458 | PASS | yes (42539617226) |
| 65 | Bitwise/compare | `mth/tests/mth_bitwise_test.nas` | 312 | PASS | yes (42539617226) |
| 66 | Checked integer | `mth/tests/mth_integer_test.nas` | 245 | PASS | yes (42539617226) |
| 67 | Shift | `mth/tests/mth_shift_test.nas` | 338 | PASS | yes (42539617226) |
| 68 | Wide multiply | `mth/tests/mth_multiply_test.nas` | 1,578 | PASS | yes (42539617226) |
| 69 | Divide/mod | `mth/tests/mth_divide_test.nas` | 2,062 | PASS | yes (42539617226) |
| 70 | Negate 256 (composite) | `mth/tests/mth_ring_wave_energy_test.nas` | 86,374 | PASS | yes |
| 71 | Stage 0 word layout | `mth/tests/mth_stage0_test.nas` | 1,161 | PASS | yes (42539617226) |
| 72 | Double-endian pair codec | `mth/tests/mth_double_endian_test.nas` | 545 | PASS | yes (42539617226) |
| 73 | Vector span add | `mth/tests/mth_vector_test.nas` | 381 | PASS | yes (42539617226) |
| 74 | Typed preflight | `mth/tests/mth_preflight_test.nas` | 2,780 | PASS | yes (42539617226) |
| 75 | Native dispatch | `mth/tests/mth_linker_preflight_test.nas` | 16,047 | PASS | yes (42539617226) |
| 76 | Graph degree 256 | `mth/tests/mth_graph_degree_test.nas` | 48,117 | PASS | yes (42539617226) |
| 77 | Graph pattern 256 | `mth/tests/mth_graph_pattern_test.nas` | 56,063 | PASS | yes (42539617226) |
| 78 | Graph filter poly2 | `mth/tests/mth_graph_filter_test.nas` | 621,536 | PASS | yes (42539617226) |
| 79 | CSR Laplacian | `mth/tests/mth_graph_laplacian_csr_test.nas` | 197,118 | PASS | yes (42539617226) |
| 80 | RSS contract | `mth/tests/mth_rss_contract_test.nas` | 6,504 | PASS | yes (42539617226) |
| 81 | Vector add 256 f32 | `mth/tests/mth_vector_add256_f32_test.nas` | 10,436 | PASS | yes (42539617226) |
| 82 | Vector sub 256 f32 | `mth/tests/mth_vector_sub256_f32_test.nas` | 10,484 | PASS | yes (42539617226) |
| 83 | Vector mean 256 f32 | `mth/tests/mth_vector_mean256_f32_test.nas` | 15,969 | PASS | yes (42539617226) |
| 84 | Vector abs 256 f32 | `mth/tests/mth_vector_abs256_f32_test.nas` | 5,328 | PASS | yes (42539617226) |
| 85 | Vector relu 256 f32 | `mth/tests/mth_vector_relu256_f32_test.nas` | 6,615 | PASS | yes (42539617226) |
| 86 | Vector scale 256 f32 | `mth/tests/mth_vector_scale256_f32_test.nas` | 82,168 | PASS | yes (42539617226) |
| 87 | Matrix transpose 256 | `mth/tests/mth_matrix_transpose256_f32_test.nas` | 3,290,464 | PASS | yes (42539617226) |
| 88 | Matrix diagonal 256 | `mth/tests/mth_matrix_diagonal256_f32_test.nas` | 9,865 | PASS | yes (42539617226) |
| 89 | Matrix add 256 | `mth/tests/mth_matrix_add256_f32_test.nas` | 2,500,024 | PASS | yes (42539617226) |
| 90 | Vector argmax 256 | `mth/tests/mth_vector_argmax256_f32_test.nas` | 62,218 | PASS | yes (42539617226) |
| 91 | Vector argmin 256 | `mth/tests/mth_vector_argmin256_f32_test.nas` | 61,708 | PASS | yes (42539617226) |
| 92 | Vector normalize 256 f32 | `mth/tests/mth_vector_normalize256_f32_test.nas` | 118,131 | PASS | yes (42539617226) |
| 93 | Vector inclusive prefix sum 256 u32 | `mth/tests/mth_vector_prefix_sum256_u32_test.nas` | 49,559 | PASS | yes (42539617226) |
| 94 | Xorshift64 forward step | `mth/tests/mth_prng_xorshift64_test.nas` | 5,043 | PASS | yes (42539617226) |
| 95 | Full 8 MiB universe map | `mth/tests/mth_universe_map_test.nas` | 12,916,386 | PASS | yes (42539617226) |
| 96 | Contradiction-aware graph claim probe | `mth/tests/mth_graph_claim_probe_test.nas` | 1,605 | PASS | yes (42539739728) |
| 97 | Vector positive mask 256 | `mth/tests/mth_vector_mask256_f32_test.nas` | 209,763 | PASS | yes (42546293200) |
| 98 | Vector weighted sum 256 | `mth/tests/mth_vector_weighted_sum256_f32_test.nas` | 234,486 | PASS | yes (42546293200) |
| 99 | Vector stable softmax 256 | `mth/tests/mth_vector_softmax256_f32_test.nas` | 123,760 | PASS | yes (42546293200) |
| 100 | Vector sum 256 | `mth/tests/mth_vector_sum256_f32_test.nas` | 65,280 | PASS | yes (42546293200) |
| 101 | Vector max 256 | `mth/tests/mth_vector_max256_f32_test.nas` | 73,396 | PASS | yes (42546293200) |
| 102 | Vector min 256 | `mth/tests/mth_vector_min256_f32_test.nas` | 73,399 | PASS | yes (42546293200) |
| 103 | Vector head concat 256 | `mth/tests/mth_vector_head_concat256_f32_test.nas` | 90,048 | PASS | yes (42546293200) |
| 104 | Full 256-tile pair driver | `mth/tests/mth_graph_pair_full_grid_driver_f32_test.nas` | 570,321,519 | PASS | yes (42546293200) |
| 105 | Vector sqrt 256 | `mth/tests/mth_vector_sqrt256_f32_test.nas` | 187,909 | PASS | yes (42546293200) |
| 106 | Vector rsqrt 256 | `mth/tests/mth_vector_rsqrt256_f32_test.nas` | 196,418 | PASS | yes (42546293200) |
| 107 | Vector exp 256 | `mth/tests/mth_vector_exp256_f32_test.nas` | 417,686 | PASS | yes (42547371933) |
| 108 | Vector log 256 | `mth/tests/mth_vector_log256_f32_test.nas` | 111,700 | PASS | yes (42547371933) |
| 109 | Vector log-sum-exp 256 | `mth/tests/mth_vector_logsumexp256_f32_test.nas` | 101,452 | PASS | yes (42547371933) |
| 110 | Sequence step u32 | `mth/tests/mth_sequence_step_u32_test.nas` | 1,467 | PASS | yes (42547371933) |
| 111 | Vector sigmoid 256 | `mth/tests/mth_vector_sigmoid256_f32_test.nas` | 129,881 | PASS | yes (42547371933) |
| 112 | Vector tanh 256 | `mth/tests/mth_vector_tanh256_f32_test.nas` | 134,794 | PASS | yes (42547371933) |
| 113 | Mirror pair address map | `mth/tests/mth_mirror_pair_map_test.nas` | 2,156,539 | PASS | yes (42558900053) |
| 114 | Mirror cycle flux | `mth/tests/mth_mirror_cycle_flux_test.nas` | 108,730 | PASS | yes (42558900053) |
| 115 | Mirror root-step residual update | `mth/tests/mth_mirror_root_step_test.nas` | 7,445 | PASS | yes (42558900053) |
| 116 | Hyperedge strength step | `mth/tests/mth_hyperedge_strength_step_test.nas` | 4,265 | PASS | yes (42558900053) |
| 117 | Hyperedge strength batch | `mth/tests/mth_hyperedge_strength_batch_test.nas` | 5,462 | PASS | yes (42558900053) |
| 118 | Mirror bounds validator | `mth/tests/mth_mirror_bounds_check_test.nas` | 1,849 | PASS | yes (42558900053) |
| 119 | Mirror gauge check | `mth/tests/mth_mirror_gauge_check_test.nas` | 4,043 | PASS | yes (42558900053) |
| 120 | Relation operator apply | `mth/tests/mth_relation_operator_apply_test.nas` | 3,053 | PASS | yes (42558900053) |
| 121 | WordNet concept/head/pair map | `mth/tests/mth_wordnet_concept_map_test.nas` | 108,027 | PASS | yes (42558900053) |
| 122 | Mirror block FNV checksum | `mth/tests/mth_mirror_block_checksum_test.nas` | 796,382 | PASS | yes (42558900053) |
| 123 | Hyperedge incidence walk | `mth/tests/mth_hyperedge_incidence_walk_test.nas` | 5,647 | PASS | yes (42558900053) |
| 124 | Mirror head record I/O | `mth/tests/mth_mirror_head_record_io_test.nas` | 431,684 | PASS | yes (42558900053) |
| 125 | Hyperedge path score | `mth/tests/mth_hyperedge_path_score_test.nas` | 9,632 | PASS | yes (42558900053) |
| 126 | Mirror Hodge projection | `mth/tests/mth_mirror_hodge_projection_test.nas` | 20,130,891 | PASS | yes (42558900053) |
| 127 | Mirror pair lane I/O | `mth/tests/mth_mirror_pair_lane_io_test.nas` | 509,737 | PASS | yes (42558900053) |
| 128 | Retrieval top-1 over 12 candidates | `mth/tests/mth_retrieval_top1_test.nas` | 4,114 | PASS | yes (42563161981) |
| 129 | Byte fallback argmax | `mth/tests/mth_byte_fallback_argmax_test.nas` | 69,144 | PASS | yes (42563161981) |
| 130 | Exact 24-byte copy | `mth/tests/mth_byte_copy24_test.nas` | 15,808 | PASS | yes (42563161981) |
| 131 | Copy-vs-generate gate | `mth/tests/mth_copy_gate_test.nas` | 2,823 | PASS | yes (42563161981) |
| 132 | Definition slot I/O | `mth/tests/mth_definition_slot_io_test.nas` | 547,060 | PASS | yes (42563503457) |
| 133 | Gauge triangle recover | `mth/tests/mth_gauge_triangle_recover_test.nas` | 9,665 | PASS | yes (42563503457) |
| 134 | Round 037 mirror slot map | `mth/tests/mth_mirror_slot_map_test.nas` | 21,192,654 | PASS | yes (42565707985) |
| 135 | Relation writer class codec | `mth/tests/mth_relation_writer_class_test.nas` | 481 | PASS | yes (42565707985) |
| 136 | Trig sine/cosine | `mth/tests/mth_trig_sincos_test.nas` | 2,020 | PASS | yes (42569728986) |
| 137 | Trig plane rotation | `mth/tests/mth_trig_rotate_test.nas` | 1,246 | PASS | yes (42569728986) |
| 138 | Content-dependent cycle train step | `mth/tests/mth_mirror_cycle_train_test.nas` | 305,596 | PASS | yes (42569728986) |
| 139 | Cycle readout 16×16 | `mth/tests/mth_mirror_cycle_train_test.nas` | 305,596 | PASS | yes (42569728986) |
| 140 | Angular ring map | `mth/tests/mth_ring_angular_map_test.nas` | 4,757,984 | PASS | yes (42575195573) |
| 141 | Native twiddle256 | `mth/tests/mth_trig_twiddle256_test.nas` | 40,725 | PASS | yes (42575195573) |
| 142 | Oscillatory phase gate | `mth/tests/mth_mirror_cycle_phase_gate_test.nas` | 13,926 | PASS | yes (42575195573) |
| 143 | Gated cycle retention | `mth/tests/mth_mirror_cycle_retain_test.nas` | 104,103 | PASS | yes (42575195573) |
| 144 | Contradiction pair | `mth/tests/mth_mirror_cycle_contradiction_test.nas` | 785 | PASS | yes (42575195573) |
| 145 | Attention/value mix16 | `mth/tests/mth_attention_mix16_test.nas` | 34,231 | PASS | yes (42575195573) |
| 146 | Log-softmax 256 | `mth/tests/mth_vector_logsoftmax256_f32_test.nas` | 62,379 | PASS | yes (42641768677) |
| 147 | Cross-entropy 256 | `mth/tests/mth_lm_cross_entropy256_f32_test.nas` | 62,098 | PASS | yes (42641768677) |
| 148 | Two-lane evidence state | `mth/tests/mth_mirror_evidence_cycle_state_test.nas` | 1,413 | PASS | yes (42641768677) |
| 149 | Causal pair knockout/restore | `mth/tests/mth_mirror_pair_knockout_test.nas` | 6,617 | PASS | yes (42655735052) |
| 150 | 16→16 attention projection | `mth/tests/mth_attention_project16_test.nas` | 45,779 | PASS | yes (42655735052) |
| 151 | 3-byte reserve-row hash | `mth/tests/mth_byte_assoc3_reserve_test.nas` | 870,499 | PASS | yes (42655735052) |
| 152 | Byte memory interpolation | `mth/tests/mth_byte_memory_mix256_test.nas` | 52,100 | PASS | yes (42655735052) |
| 153 | Single-head attention | `mth/tests/mth_attention_head16_test.nas` | 135,441 | PASS | yes (42667242944) |

## Local phase-system integration fixture

`mth/tests/mth_phase_system_test.nas` composes native twiddle generation,
oscillatory gates, phase-gated cycle training, readout, attention mixing,
retention, contradiction preservation, and angular ring addressing in one
guest run. It passes locally in **288,659 steps** with marker
`MTH PHASE SYSTEM PASS`. It is an integration fixture, not a manifest kernel.
The separate `phase-system-integration` workflow assembles and runs it directly
with the pinned NaN0S toolchain; run `42638938887` passed. This is not a live
model or a deployment claim.

## Python tests

```
python3 -m unittest discover -s tests -q
Ran 1452 tests in 386.074s
OK (skipped=29)
```

The 29 skips include the upstream Ed25519 attestation class because the optional
`cryptography` package is not installed in this Termux environment; the
canonical workflow installs it. The test module now skips cleanly rather than
erroring when the optional package is absent.

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
104 runner fixture paths registered; 103 unique manifest fixtures
K256 pair-space, normalize, prefix-sum, xorshift64, and universe-map targeted set: 5/5 PASS
Full canonical runner against NaN0S f31143e (fe63617 differs only in a CI workflow): 145/145 PASS
```

Run it after any kernel change.

## Capability manifest

`spec/wave-capabilities.json` records 153 kernels (153 `ci_verified`, no local-only), source/fixture paths, markers, local step counts, precision, workspace, and CI status. `tools/register_wave_capabilities.py` hashes the source/fixture and registers operator/capability rows in MC0DB through `WaveStore`. A local dry run currently reports **153 kernels**; production registration remains gated on the deployed BS0DB/MC0DB.

## Unified MTH catalog and full-universe map

- `spec/universe-map.json` contains all 256 page descriptors and resolves 256
  fixed heads plus 32,640 mirror pairs (32,896 relation points) across the
  complete 8 MiB / 1,048,576-word guest address space.
- NANNET0 is one point with explicit aliases `head 0 = page 255 = ring 255 =
  HW0:0`. Real heads `1..255` map to pages `0..254`.
- `mth/nan16/mth_universe_map.nas` implements the map in NaN16; its fixture
  passes locally in 12,916,386 steps with no trap.
- `runner_riddle/mth_unified.py` builds a 106-kernel unified catalog with 5
  native-dispatch ABI entries and binds the control plane to the NaN0S,
  HERMES, Android, NaNLMind, NaNLM, and CLOCKED provider contracts.
- The provider audit prefers the local worktree and falls back to fetched
  `origin/main`; it does not fetch, checkout, reset, or modify sibling repos.
  Local dirty/behind worktrees are recorded as evidence only.
- `tools/mth_unified.py --check` is green. The catalog records
  `claims_ci_verified=false` and `claims_live_deployment=false`.

## What is not yet proven

- No long-run CFL/damping sweep with a paged graph operator and trace exists yet; the four-step C256 energy fixture is bounded.
- Full 256 matvec, SVD top pair, SVD top-2, ENCODE/DECODE, adapter residual, full 255 certificate, stable top-k, Lanczos, JAHS gate, avoided-crossing sweep, radial, DRIVE/CFL, colored noise, and K16 driver pass locally; no page-size limit is enforced.
- K256 closed-form 256×256 pair exists; the general 16×16 pair tile is native_verified in CI run 218; the Python 256-tile page-window/atomic-publication layer and 31 tests exist; the native full 256-tile pair driver is CI-verified in run `42546293200`; generic sparse-CSR pair action remains open.
- Wave and point-0 HTTP adapters exist; the offline live preflight/signed-volume gate exists; live Koyeb/NANNET0 deployment remains blocked on real credentials and network.
- Full 256 adapter residual and a frozen-base ablation harness exist, but no real LM/data ablation or held-out benefit exists; the adapter remains disabled.
- R7 protocol harness and native sweep exist; no real held-out LM/data experiment or creativity claim exists.
- P13 live/experiment gates remain blocked: no live Koyeb/NANNET0 deployment, signed volume-registry verification, production MC0DB registration, frozen-model LM ablation, R7 held-out result, capacity-vs-SNR measurement, or native numeric executor delivery has been produced.
- The P12 demo proves control-plane integration only; it does not compute a numeric dot product. Native numeric execution remains the external executor's responsibility.
- Native stable softmax/log-sum-exp and exp/log/sqrt/rsqrt/sigmoid/tanh are CI-verified; log-softmax and exhaustive numerical error proofs remain open.
- Normalize, inclusive prefix sum, xorshift64, and the full 8 MiB universe map are CI-verified in run `42539617226`; Koyeb bootstrap and container smoke readiness are not a live Koyeb/NANNET0 deployment, and no real provider IDs or mounted-volume health were observed.
- The unified catalog is a cross-repo source/contract audit, not proof that every provider is deployed, reachable, or executing the same build. It deliberately leaves CI and live claims false.
- Round 032 retrieval evidence is external C++: 50,268 facts, 250,000/250,000 exact lookups, 2,000/2,000 stored two-hop queries, and 1.01167 cycle invariance. The conventional hash index is ~4.3× faster (2.29752 ms vs 9.77183 ms); this is not decoder or generalization evidence. See `docs/ROUND_032_RETRIEVAL.md`.
- Round 033 episodic evidence is external C++/PyTorch: 886/900 exact 24-byte copies across three seeds, 118/120 native gauge-invariant exact copies, 94/2880 raw-byte recovery, and a tied free-form LM (3.67475 vs 3.67479 bits/byte). It is retrieval/copy evidence, not novel generation or a cycle-geometry LM advantage. See `docs/ROUND_033_GENERATIVE_RETRIEVAL.md`.
- Rounds 034–036 are external generation experiments: 99% router accept/abstain with 0.444% false answers but 61.89% under 6-character corruption; 120/120 native 3-hop composition with 60/120 raw-edge; 81,499-synset slot generator with 90/90 gauge-invariant native prompts but 0/300 contradiction abstentions and 0/150 four-hop before robust retraining. See `docs/ROUNDS_034_036_GENERATION.md`.
- No trusted proof checker exists, so production validity remains capped at V2 and proof candidates remain unchecked.
- No claim of intelligence, creativity, quantum tunneling, or consciousness.
