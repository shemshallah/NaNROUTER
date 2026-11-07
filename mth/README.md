# MTH NaN16 source

This directory is the first native MTH source slice. Mathematical code here is NaN16; no host-language math implementation is permitted.

- `nan16/mth_core.nas`: class-nibble rotation, near/far face extraction and packing, sign/quiet-bit extraction for all four legal NaN face types, and the explicit `BSWAPM` wrapper.
- `nan16/mth_bool.nas`: generic two-input Boolean transformation. It patches the frozen NaN16 `BOOL.n` class into a code slot and executes it natively.
- `nan16/mth_double_endian.nas`: native double-endian pair codec with tagged big-endian/little-endian members and mismatch rejection.
- `nan16/mth_integer.nas`: checked unsigned 32-bit addition and subtraction with explicit overflow/underflow status.
- `tests/mth_stage0_test.nas`: rotation-table and double-`BSWAPM` smoke test.
- `tests/mth_bool2_test.nas`: checks all 16 two-input truth-table classes against the expected lane pattern.
- `tests/mth_double_endian_test.nas`: checks pair round-trip and rejects a deliberately corrupted member.
- `tests/mth_integer_test.nas`: checks exact addition/subtraction and explicit overflow/underflow outcomes.

The test is intentionally a smoke test, not exhaustive proof. It must be assembled and run with the canonical NaN16 toolchain before this gate is marked passed.

Important distinction:
- `BSWAPM` is the existing NaN16 full eight-byte reversal: it swaps both NaN faces and reverses the 32-bit payload byte order. Its class transform is `rot2(n)`.
- The existing double-endian pair codec is separate: it emits a big-endian member and a byte-swapped little-endian member, then validates agreement on decode. This redundant pair-voting representation is not the same operation as BSWAPM.

The pair codec is adapted from `NaN0S/src/lib/n16de.nas` (blob `47d64c3446d57669160317228258c35d2184ad17`). Its inherited static return slots make it non-reentrant; this is a temporary limitation that must be removed before concurrent multi-runner use. The smoke test is committed but has not yet been assembled or executed in the canonical runtime.
