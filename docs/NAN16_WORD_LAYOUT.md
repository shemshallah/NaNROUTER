# NaN16 word/class layout

Status: machine-readable contract in `spec/nan16-word-layout.json`; tests in
`tests/test_nan16_word_layout.py` (4 tests).

This freezes the logical layout used by the Stage 0 kernels without claiming a
new physical payload allocation:

- 64-bit word, two 32-bit faces (`near`, `far`).
- Ordered class nibble: `class = (near_face_class << 2) | far_face_class`.
- Face class: `face_class = (quiet << 1) | sign`.
- All 16 ordered class pairs are distinct.
- BSWAPM reverses all eight bytes, swaps faces, preserves the class nibble, and
  is an involution.
- BSWAPM is explicitly **not** the double-endian redundant pair codec.

The native source remains `mth/nan16/mth_core.nas`; the Stage 0 fixture is
`mth/tests/mth_stage0_test.nas`. The fixture currently fails locally and is not
CI-verified, so it must not be described as a passed gate.
