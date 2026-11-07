# MTH NaN16 source

This directory is the first native MTH source slice. Mathematical code here is NaN16; no host-language math implementation is permitted.

- `nan16/mth_core.nas`: class-nibble face rotation and the explicit wrapper around the existing `BSWAPM` primitive.
- `nan16/mth_bool.nas`: generic two-input Boolean transformation. It patches the frozen NaN16 `BOOL.n` class into a code slot and executes it natively.
- `tests/mth_stage0_test.nas`: rotation-table and double-`BSWAPM` smoke test.
- `tests/mth_bool2_test.nas`: checks all 16 two-input truth-table classes against the expected lane pattern.

The test is intentionally a smoke test, not exhaustive proof. It must be assembled and run with the canonical NaN16 toolchain before this gate is marked passed.

Important distinction:
- `BSWAPM` is the existing NaN16 full eight-byte reversal: it swaps both NaN faces and reverses the 32-bit payload byte order. Its class transform is `rot2(n)`.
- The existing double-endian pair codec is separate: it emits a big-endian member and a byte-swapped little-endian member, then validates agreement on decode. This redundant pair-voting representation is not the same operation as BSWAPM.

The next implementation step is to import the canonical pair-codec source into this repository only if its current path and ABI are confirmed, then add exhaustive class-pair and corruption/resynchronization tests.
