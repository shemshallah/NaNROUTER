# MTH NaN16 source

This directory is the first native MTH source slice. Mathematical code here is NaN16; no host-language math implementation is permitted.

- `nan16/mth_core.nas`: class-nibble face rotation and the explicit wrapper around the existing `BSWAPM` primitive.
- `tests/mth_stage0_test.nas`: rotation-involution and double-`BSWAPM` smoke test.

The test is intentionally a smoke test, not exhaustive proof. It must be assembled and run with the canonical NaN16 toolchain before this gate is marked passed.

Important distinction:
- `BSWAPM` is the existing NaN16 memory face-swap primitive. Do not assume it reverses all eight bytes.
- The existing double-endian pair codec is a separate operation: it emits a big-endian member and a byte-swapped little-endian member, then validates agreement on decode. MTH will wrap and test that codec separately rather than silently conflating the two.

The next implementation step is to import the canonical pair-codec source into this repository only if its current path and ABI are confirmed, then add exhaustive class-pair and corruption/resynchronization tests.
