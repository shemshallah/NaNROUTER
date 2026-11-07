# MTH NaN16 source

This directory is the first native MTH source slice. Mathematical code here is NaN16; no host-language math implementation is permitted.

- `nan16/mth_core.nas`: class-nibble rotation, near/far face extraction and packing, sign/quiet-bit extraction for all four legal NaN face types, and the explicit `BSWAPM` wrapper.
- `nan16/mth_bool.nas`: generic two-input Boolean transformation. It patches the frozen NaN16 `BOOL.n` class into a code slot and executes it natively.
- `nan16/mth_double_endian.nas`: native double-endian pair codec with tagged big-endian/little-endian members and mismatch rejection.
- `nan16/mth_integer.nas`: checked unsigned 32-bit addition and subtraction with explicit overflow/underflow status.
- `nan16/mth_bitwise.nas`: native bitwise functions, unsigned min/max, and comparison predicates.
- `nan16/mth_shift.nas`: checked variable-count logical left/right shifts (0–31) built from NaN16 shift instructions.
- `nan16/mth_multiply.nas`: full-width unsigned 32×32→64 multiplication using a native shift-and-add algorithm.
- `nan16/mth_divide.nas`: unsigned 32-bit divmod using a 32-step restoring algorithm; divide-by-zero is an explicit status.
- `nan16/mth_vector.nas`: checked contiguous U32 span addition with a preflight pass; overflow leaves output unchanged.
- `nan16/mth_k256_laplacian.nas`: exact matrix-free K256 Laplacian over U16 inputs, producing signed I32 outputs with preflight validation; canonical NaN16 execution verified.
- `nan16/mth_k255_laplacian.nas`: exact K255 head-only Laplacian over U16 inputs, producing signed I32 outputs with preflight validation; local canonical execution PASS.
- `nan16/mth_ring255_laplacian.nas`: C255 head-ring float32 Laplacian; local canonical execution PASS.
- `nan16/mth_ring255_port.nas`: 255-head + NANNET-port readout assembly; local canonical execution PASS.
- `nan16/mth_graph_fold.nas`: 256/255 fold vectors and 256 unfold; local canonical execution PASS.
- `nan16/mth_dot256_f32.nas`, `nan16/mth_norm256_f32.nas`, `nan16/mth_axpy256_f32.nas`: float32 dot, norm, and axpy primitives; local canonical execution PASS.
- `nan16/mth_graph_void.nas`: regularized inverse-square float32 void potential; local canonical execution PASS.
- `nan16/mth_graph_wave.nas`: damped velocity-Verlet float32 wave step; local canonical execution PASS.
- `nan16/mth_graph_step_energy_256.nas`: kinetic/potential/total step energy metric; local canonical execution PASS.
- `nan16/mth_graph_pair.nas`: dense 128×128 pair-space action `LU + ULᵀ`; local canonical execution PASS.
- `nan16/mth_graph_pair_rank1_128.nas`: rank-1 128 pair-space prototype; local canonical execution PASS.
- `nan16/mth_graph_dft256.nas`: 256-point complex float32 DFT reference with caller-supplied twiddle table; local canonical execution PASS.
- `nan16/mth_graph_couple_128.nas`: two-region coupling primitive; local canonical execution PASS.
- `nan16/mth_graph_transmission_128.nas`: two-region energy/transmission metric; local canonical execution PASS.
- `runner_riddle/wave_store.py`: BS0DB/MC0DB wave job, lease, capability, seal, signature, and trace store; 12 tests pass.
- `spec/ring-255.json`: deterministic C255 head-ring CSR and 255+1 page map.
- `tests/mth_stage0_test.nas`: rotation-table and double-`BSWAPM` smoke test.
- `tests/mth_bool2_test.nas`: checks all 16 two-input truth-table classes against the expected lane pattern.
- `tests/mth_double_endian_test.nas`: checks pair round-trip and rejects a deliberately corrupted member.
- `tests/mth_integer_test.nas`: checks exact addition/subtraction and explicit overflow/underflow outcomes.
- `tests/mth_bitwise_test.nas`: checks bitwise transforms, unsigned min/max, and comparison results.
- `tests/mth_shift_test.nas`: checks variable shifts, boundary count 31, and rejection of count 32.
- `tests/mth_multiply_test.nas`: checks 3×7 and two full-width overflow-boundary products.
- `tests/mth_divide_test.nas`: checks quotient/remainder, a full-width dividend, and divide-by-zero.
- `tests/mth_vector_test.nas`: checks vector results, overflow atomicity, and zero-length behavior.
- `tests/mth_k256_laplacian_test.nas`: checks the K256 impulse response and invalid-input atomicity; canonical execution PASS.
- `tests/mth_k255_laplacian_test.nas`: checks the K255 impulse response and invalid-input atomicity.
- `tests/mth_ring255_laplacian_test.nas`: checks the C255 impulse and constant-state nullspace.
- `tests/mth_ring255_port_test.nas`: checks 255 head + 1 NANNET port readout layout.
- `tests/mth_graph_fold_test.nas`: checks even/odd fold and even unfold.
- `tests/mth_dot256_test.nas`, `tests/mth_norm256_test.nas`, `tests/mth_axpy256_test.nas`: float32 vector primitive fixtures.
- `tests/mth_graph_void_test.nas`: void-potential formula, alpha=0, and invalid-parameter atomicity.
- `tests/mth_graph_wave_test.nas`: velocity-Verlet kinematics, damping, and rejection atomicity.
- `tests/mth_graph_step_energy_256_test.nas`: kinetic/potential/total energy oracle.
- `tests/mth_graph_pair_test.nas`: dense 128×128 pair action with `L=2I` and zero-state checks.
- `tests/mth_graph_pair_rank1_128_test.nas`: rank-1 128 pair action.
- `tests/mth_graph_dft256_test.nas`: impulse, DC, and Nyquist DFT checks.
- `tests/mth_graph_couple_128_test.nas`: eta=0/0.5/1 coupling and invalid-eta atomicity.
- `tests/mth_graph_transmission_128_test.nas`: energy ratio and zero-denominator checks.
- `tests/test_wave_store.py`, `tests/test_ring_csr.py`, `tests/test_wave_capabilities.py`, `tests/test_wave_adapter.py`: Python storage, ring, capability, and adapter contracts.

The double-endian codec now uses caller-owned frames in `r12` and no shared static return/operand slots. The updated fixture uses independent frames for separate calls. The vector span routine is a low-level contiguous U32 primitive, not yet the typed vector-descriptor layer.

The tests are intentionally fixtures, not exhaustive proof. They must be assembled and run with the canonical NaN16 toolchain before their gates are marked passed.

Important distinction:
- `BSWAPM` is the existing NaN16 full eight-byte reversal: it swaps both NaN faces and reverses the 32-bit payload byte order. Its class transform is `rot2(n)`.
- The existing double-endian pair codec is separate: it emits a big-endian member and a byte-swapped little-endian member, then validates agreement on decode. This redundant pair-voting representation is not the same operation as BSWAPM.

The pair codec is adapted from `NaN0S/src/lib/n16de.nas` (blob `47d64c3446d57669160317228258c35d2184ad17`). Its original inherited static return slots have been replaced by caller-owned frames in the current MTH source. This removes shared static state, but the new ABI remains unverified until the canonical NaN16 toolchain executes the updated fixture. The smoke test is committed but has not yet been assembled or executed in the canonical runtime.


## Relational-spectral subsystem

The shared 8 MiB universe-bin graph-spectral architecture is specified in `docs/game_plan_foundations.md`, `docs/GRAPH_SPECTRAL_MTH_PLAN.md`, and NaNLMind's `docs/GRAPH_SPECTRAL_FOUNDATION.md`. The exact U16-input K256 Laplacian was the first graph-spectral `.nas` kernel; the native slice now also includes K255/C255 ring geometry, port assembly, sparse/weighted Laplacians, energy, components, void potential, wave step, step energy, fold, dot/norm/axpy, 256-point DFT, 128×128 pair actions, coupling, and transmission. Aperture SVD/power iteration, Lanczos, repeated-step energy conservation, full 256×256 pair action, and LM ablations remain open gates.


A canonical execution workflow is defined at `.github/workflows/mth-native-contract.yml`.
It builds the NaN0S CLI harness, assembles the MTH fixture with the NaN0S
NaN16 source assembler, and executes the emitted image. The K256 U16-input kernel is marked native_verified after workflow run #17
assembled and executed its fixture successfully (5,399 guest steps; HALT). The NaNLMind RSS worker still advertises the capability as source-written/not dispatchable until the verified kernel is registered with its digest and workspace contract.


## Sparse graph Laplacian v1

- `nan16/mth_sparse_graph_laplacian.nas`: exact symmetric simple-graph CSR Laplacian, Q16.16/I32 v1, bounded input range, complete preflight, no static scratch.
- `tests/mth_sparse_graph_laplacian_test.nas`: path, disconnected graph, and invalid-input atomicity fixtures.
- Full ABI and range proof: `docs/MTH_SPARSE_GRAPH_ABI.md`.

The sparse kernel is native-verified by canonical NaN16 CI run #58 (path, disconnected, and invalid-input atomicity fixtures; 20,737 guest steps). Weighted CSR v2 is native-verified by canonical NaN16 CI run #107 (two weighted path oracles and invalid-zero-weight atomicity; 41,253 guest steps). Kernel SHA-256: `8958bf432cd4052576d9b950d9e50c1853bc96d90bc3c50680bf9013ab36d613`.


The sparse graph fixture emits stage markers to distinguish preflight, path-oracle, and disconnected-oracle failures during initial native bring-up.


## Weighted sparse graph Laplacian v2

- Contract: `docs/MTH_WEIGHTED_CSR_ABI_V2.md`.
- Kernel: `nan16/mth_sparse_weighted_graph_laplacian_v2.nas`.
- Fixture: `tests/mth_sparse_weighted_graph_laplacian_v2_test.nas`.
- State: Q16.16/I32 input in [-64,+64]; U8 integer edge weights 1..255; signed I64 Q16.16 output.
- The caller supplies a 16-word scratch frame. The row accumulator is widened to I64; each edge product is exact signed I32.
- Exact weighted-path and invalid-zero-weight atomicity fixtures are wired into the canonical NaN16 workflow. Canonical NaN16 CI run #107 passed the weighted path and invalid-zero-weight atomicity fixture (41,253 guest steps). Kernel SHA-256: `8958bf432cd4052576d9b950d9e50c1853bc96d90bc3c50680bf9013ab36d613`. This is native_verified only for the stated v2 contract.

## Ring / void / NANNET native slice

- Contract: `docs/game_plan_deep.md`.
- Implementation ledger: `docs/IMPLEMENTATION_TODO.md`.
- 255 local heads + 1 NANNET node = 256 ring positions; 8 MiB = 255 head pages + 1 NANNET page.
- Ring CSR/page map: `spec/ring-255.json`, generated by `tools/gen_ring_csr.py`.
- K255/C255/port ABI: `docs/MTH_K255_RING_ABI.md`.
- Fold ABI: `docs/MTH_GRAPH_FOLD_ABI.md`.
- Float32 vector ABI: `docs/MTH_VECTOR_F32_ABI.md`.
- Graph energy/components ABI: `docs/MTH_GRAPH_INVARIANTS_ABI.md`.

The K255, C255, port, fold, dot, norm, axpy, energy, component, void, wave, step-energy, pair, DFT, coupling, and transmission fixtures passed local `nan_cli` and GitHub Actions run `42352593144`. The CI workflow includes all 20 fixtures.
