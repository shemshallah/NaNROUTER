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
`mth/tests/mth_stage0_test.nas`. As of 2026-11-07 the fixture assembles with
the canonical NaN0S `nmk.awk` and passes locally under `nan_cli` with marker
`MTH STAGE0 PASS` after 1,161 steps. The earlier PC 114 failure was a fixture
bug: the post-`BSWAPM` restoration check compared payload against the saved
class nibble and class against the saved payload. The fixture now compares
payload-to-payload and class-to-class.

The fixture is part of the canonical `mth-native-contract` workflow, but that
workflow has not yet been observed to run this revision. Status therefore
remains local native evidence, not CI-verified; `spec/wave-capabilities.json`
records `ci_verified: false` until canonical CI actually runs it.
