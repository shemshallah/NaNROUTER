# NaN0S CLI bridge for MTH pair tiles

Status: adapter source and codec tests added. No end-to-end page-backed 256-tile run is claimed yet.

`runner_riddle/mth_pair_nan0s_guest.py` implements the native guest protocol by assembling and launching isolated NaN16 images. Host code only stages words and retrieves output; matrix arithmetic remains in the guest.

K16 image layout: four 4,096-word K-slice-major strips at 1024, 5120, 9216, 13312; accumulators at 17408 and 17664; output at 17920; six-word scratch at 18432; status at 18440.

Full-U reference layout: U at 1024 (65,536 words); L_I at 66560; L_J at 70656; output at 74752; scratch at 75008; status at 75014. The full-U reference is serial; K16 guest processes use separate VM processes. U and L row strips are cached by immutable operator digest during the generation.

NaN16 words are 64-bit double-ended words. Their 32-bit payload occupies bits 16..47. Guest ST writes canonical n=10 words; `--peek` emits the payload, and the adapter restores the n=10 framing before returning the output page.

Required tools: `nan0s/tools/nmk.awk` and `nan0s/aarch64/android/nan_cli`. Set `nan0s_root` when the toolchain is not at the repository's `nan0s/` path.

The executor's workspace calculation remains admission accounting, not a physical VM memory fence. Production supervisors should separately enforce process memory and time limits.
