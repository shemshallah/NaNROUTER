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
- `nan16/mth_vector.nas`: checked contiguous U32 span addition with a preflight pass; overflow leaves output unchanged.\n- `nan16/mth_k256_laplacian.nas`: exact matrix-free K256 Laplacian over U16 inputs, producing signed I32 outputs with preflight validation; canonical NaN16 execution verified.
- `tests/mth_stage0_test.nas`: rotation-table and double-`BSWAPM` smoke test.
- `tests/mth_bool2_test.nas`: checks all 16 two-input truth-table classes against the expected lane pattern.
- `tests/mth_double_endian_test.nas`: checks pair round-trip and rejects a deliberately corrupted member.
- `tests/mth_integer_test.nas`: checks exact addition/subtraction and explicit overflow/underflow outcomes.
- `tests/mth_bitwise_test.nas`: checks bitwise transforms, unsigned min/max, and comparison results.
- `tests/mth_shift_test.nas`: checks variable shifts, boundary count 31, and rejection of count 32.
- `tests/mth_multiply_test.nas`: checks 3×7 and two full-width overflow-boundary products.
- `tests/mth_divide_test.nas`: checks quotient/remainder, a full-width dividend, and divide-by-zero.
- `tests/mth_vector_test.nas`: checks vector results, overflow atomicity, and zero-length behavior.\n- `tests/mth_k256_laplacian_test.nas`: checks the K256 impulse response and invalid-input atomicity; canonical execution PASS.

The double-endian codec now uses caller-owned frames in `r12` and no shared static return/operand slots. The updated fixture uses independent frames for separate calls. The vector span routine is a low-level contiguous U32 primitive, not yet the typed vector-descriptor layer.

The tests are intentionally fixtures, not exhaustive proof. They must be assembled and run with the canonical NaN16 toolchain before their gates are marked passed.

Important distinction:
- `BSWAPM` is the existing NaN16 full eight-byte reversal: it swaps both NaN faces and reverses the 32-bit payload byte order. Its class transform is `rot2(n)`.
- The existing double-endian pair codec is separate: it emits a big-endian member and a byte-swapped little-endian member, then validates agreement on decode. This redundant pair-voting representation is not the same operation as BSWAPM.

The pair codec is adapted from `NaN0S/src/lib/n16de.nas` (blob `47d64c3446d57669160317228258c35d2184ad17`). Its original inherited static return slots have been replaced by caller-owned frames in the current MTH source. This removes shared static state, but the new ABI remains unverified until the canonical NaN16 toolchain executes the updated fixture. The smoke test is committed but has not yet been assembled or executed in the canonical runtime.


## Relational-spectral subsystem

The shared 8 MiB universe-bin graph-spectral architecture is specified in `docs/game_plan_foundations.md`, `docs/GRAPH_SPECTRAL_MTH_PLAN.md`, and NaNLMind's `docs/GRAPH_SPECTRAL_FOUNDATION.md`. The exact U16-input K256 Laplacian is the first graph-spectral `.nas` kernel and is native_verified by canonical execution. Sparse weighted graphs, signed fixed-point wave ABI, void potential, eigensolvers, filters, and pair-space application remain future kernels.


A canonical execution workflow is defined at `.github/workflows/mth-native-contract.yml`.
It builds the NaN0S CLI harness, assembles the MTH fixture with the NaN0S
NaN16 source assembler, and executes the emitted image. The K256 U16-input kernel is marked native_verified after workflow run #17
assembled and executed its fixture successfully (5,399 guest steps; HALT). The NaNLMind RSS worker still advertises the capability as source-written/not dispatchable until the verified kernel is registered with its digest and workspace contract.
