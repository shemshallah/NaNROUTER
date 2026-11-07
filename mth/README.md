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
- `tests/mth_stage0_test.nas`: rotation-table and double-`BSWAPM` smoke test.
- `tests/mth_bool2_test.nas`: checks all 16 two-input truth-table classes against the expected lane pattern.
- `tests/mth_double_endian_test.nas`: checks pair round-trip and rejects a deliberately corrupted member.
- `tests/mth_integer_test.nas`: checks exact addition/subtraction and explicit overflow/underflow outcomes.
- `tests/mth_bitwise_test.nas`: checks bitwise transforms, unsigned min/max, and comparison results.
- `tests/mth_shift_test.nas`: checks variable shifts, boundary count 31, and rejection of count 32.
- `tests/mth_multiply_test.nas`: checks 3×7 and two full-width overflow-boundary products.
- `tests/mth_divide_test.nas`: checks quotient/remainder, a full-width dividend, and divide-by-zero.
- `tests/mth_vector_test.nas`: checks vector results, overflow atomicity, and zero-length behavior.

The double-endian codec now uses caller-owned frames in `r12` and no shared static return/operand slots. The updated fixture uses independent frames for separate calls. The vector span routine is a low-level contiguous U32 primitive, not yet the typed vector-descriptor layer.

The tests are intentionally fixtures, not exhaustive proof. They must be assembled and run with the canonical NaN16 toolchain before their gates are marked passed.

Important distinction:
- `BSWAPM` is the existing NaN16 full eight-byte reversal: it swaps both NaN faces and reverses the 32-bit payload byte order. Its class transform is `rot2(n)`.
- The existing double-endian pair codec is separate: it emits a big-endian member and a byte-swapped little-endian member, then validates agreement on decode. This redundant pair-voting representation is not the same operation as BSWAPM.

The pair codec is adapted from `NaN0S/src/lib/n16de.nas` (blob `47d64c3446d57669160317228258c35d2184ad17`). Its original inherited static return slots have been replaced by caller-owned frames in the current MTH source. This removes shared static state, but the new ABI remains unverified until the canonical NaN16 toolchain executes the updated fixture. The smoke test is committed but has not yet been assembled or executed in the canonical runtime.
