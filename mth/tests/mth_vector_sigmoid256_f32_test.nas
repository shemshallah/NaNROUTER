; MTH vector sigmoid256 float32 fixture — NaN16 only.
;
; All input vectors are generated in the guest at run time. Every check is
; an integer CMP on raw 32-bit payloads, or an FADD/FSUB followed by a
; sign-bit clear and an integer CMP against a declared float32 tolerance.
; No host arithmetic produces an expected value.
;
; Success phases:
;   1. x[i] = (float)(i - 128) * 0.15625, strictly increasing on
;      [-20, 19.84375]. Checks status, output range [0,1], weak
;      monotonicity on raw nonnegative payloads, the exact zero head for
;      x <= -16 (indices 0..25), the exact one tail for x >= 16 (indices
;      231..255), and the exact midpoint sigmoid(0) = 0.5 at index 128.
;   2. neg[i] = -x[i] (exact sign flip). Checks the symmetry
;      sigmoid(-x) + sigmoid(x) = 1 with absolute tolerance 2^-16.
;   3. x[i] = +0.0 for all i. The exact output is 0.5 for every element.
;   4. x[i] = +16.0 and then x[i] = -16.0. The documented saturation
;      boundary must store exactly +1.0 and exactly +0.0.
;
; Failure phases (out_fail is pre-filled with 0xDEADBEEF):
;   5. quiet NaN at index 17: return 0, cause 1.
;   6. signaling NaN at index 255: return 0, cause 1.
;   7. +inf at index 200: return 0, cause 1.
;   8. -inf at index 0: return 0, cause 1.
;   Every failure phase also checks that all 256 output words remain
;   0xDEADBEEF, i.e. the rejection is atomic.
;
; Recovery phase:
;   9. Rebuild the phase-1 input and rerun into a fresh buffer. Every output
;      payload must match the phase-1 reference bit for bit.

.org 0
JMP @mth_sg_test_main
.include "../nan16/mth_vector_sigmoid256_f32.nas"

mth_sg_test_main:
  MOVI r13,1

  ; ---- Phase 1: strictly increasing input, saturation and midpoint.
  CALL @mth_sg_test_prepare_sorted
  LA r1,@mth_sg_test_x
  LA r2,@mth_sg_test_out
  CALL @mth_vector_sigmoid256_f32
  CMP r1,r13
  JMP[NE] @mth_sg_test_fail
  CMP r9,r0
  JMP[NE] @mth_sg_test_fail
  LA r1,@mth_sg_test_out
  CALL @mth_sg_test_check_unit_range
  LA r1,@mth_sg_test_out
  CALL @mth_sg_test_check_monotonic

  LA r1,@mth_sg_test_out
  MOVI r2,0
  MOVI r3,26                ; x[0..25] <= -16.09375
  CALL @mth_sg_test_check_run_value

  LA r1,@mth_sg_test_out
  MOVI r3,231
  ADD r1,r1,r3
  MOVI r2,0
  MOVHI r2,0x3F80           ; 1.0
  MOVI r3,25                ; x[231..255] >= 16.09375
  CALL @mth_sg_test_check_run_value

  LA r1,@mth_sg_test_out
  MOVI r3,128               ; x[128] = +0.0
  ADD r1,r1,r3
  LD r2,r1,0
  MOVI r3,0
  MOVHI r3,0x3F00           ; 0.5
  CMP r2,r3
  JMP[NE] @mth_sg_test_fail

  ; ---- Phase 2: point symmetry on the same sorted vector.
  CALL @mth_sg_test_prepare_sorted
  LA r1,@mth_sg_test_x
  LA r2,@mth_sg_test_neg
  CALL @mth_sg_test_negate256
  LA r1,@mth_sg_test_neg
  LA r2,@mth_sg_test_out_neg
  CALL @mth_vector_sigmoid256_f32
  CMP r1,r13
  JMP[NE] @mth_sg_test_fail
  CMP r9,r0
  JMP[NE] @mth_sg_test_fail
  LA r1,@mth_sg_test_out
  LA r2,@mth_sg_test_out_neg
  MOVI r3,0
  MOVHI r3,0x3780           ; 2^-16 = 1.5259e-5
  CALL @mth_sg_test_check_symmetry

  ; ---- Phase 3: all-zero input gives exactly 0.5.
  LA r1,@mth_sg_test_x
  MOVI r2,0
  CALL @mth_sg_test_fill_value
  LA r1,@mth_sg_test_x
  LA r2,@mth_sg_test_out_neg
  CALL @mth_vector_sigmoid256_f32
  CMP r1,r13
  JMP[NE] @mth_sg_test_fail
  CMP r9,r0
  JMP[NE] @mth_sg_test_fail
  LA r1,@mth_sg_test_out_neg
  MOVI r2,0
  MOVHI r2,0x3F00           ; 0.5
  MOVI r3,256
  CALL @mth_sg_test_check_run_value

  ; ---- Phase 4a: the +16.0 saturation boundary gives exactly 1.0.
  LA r1,@mth_sg_test_x
  MOVI r2,0
  MOVHI r2,0x4180           ; +16.0
  CALL @mth_sg_test_fill_value
  LA r1,@mth_sg_test_x
  LA r2,@mth_sg_test_out_neg
  CALL @mth_vector_sigmoid256_f32
  CMP r1,r13
  JMP[NE] @mth_sg_test_fail
  CMP r9,r0
  JMP[NE] @mth_sg_test_fail
  LA r1,@mth_sg_test_out_neg
  MOVI r2,0
  MOVHI r2,0x3F80           ; 1.0
  MOVI r3,256
  CALL @mth_sg_test_check_run_value

  ; ---- Phase 4b: the -16.0 saturation boundary gives exactly 0.0.
  LA r1,@mth_sg_test_x
  MOVI r2,0
  MOVHI r2,0xC180           ; -16.0
  CALL @mth_sg_test_fill_value
  LA r1,@mth_sg_test_x
  LA r2,@mth_sg_test_out_neg
  CALL @mth_vector_sigmoid256_f32
  CMP r1,r13
  JMP[NE] @mth_sg_test_fail
  CMP r9,r0
  JMP[NE] @mth_sg_test_fail
  LA r1,@mth_sg_test_out_neg
  MOVI r2,0
  MOVI r3,256
  CALL @mth_sg_test_check_run_value

  ; ---- Phase 5: quiet NaN at index 17 rejects atomically.
  CALL @mth_sg_test_fill_sentinel
  CALL @mth_sg_test_prepare_sorted
  LA r5,@mth_sg_test_x
  MOVI r6,0
  MOVHI r6,0x7FC0           ; quiet NaN = 0x7FC00000
  ST r6,r5,17
  LA r1,@mth_sg_test_x
  LA r2,@mth_sg_test_out_fail
  CALL @mth_vector_sigmoid256_f32
  MOVI r2,1
  CALL @mth_sg_test_expect_failure

  ; ---- Phase 6: signaling NaN at the last index rejects atomically.
  CALL @mth_sg_test_fill_sentinel
  CALL @mth_sg_test_prepare_sorted
  LA r5,@mth_sg_test_x
  MOVI r6,1
  MOVHI r6,0x7F80           ; signaling NaN = 0x7F800001
  ST r6,r5,255
  LA r1,@mth_sg_test_x
  LA r2,@mth_sg_test_out_fail
  CALL @mth_vector_sigmoid256_f32
  MOVI r2,1
  CALL @mth_sg_test_expect_failure

  ; ---- Phase 7: +inf at index 200 rejects atomically.
  CALL @mth_sg_test_fill_sentinel
  CALL @mth_sg_test_prepare_sorted
  LA r5,@mth_sg_test_x
  MOVI r6,0
  MOVHI r6,0x7F80           ; +inf = 0x7F800000
  ST r6,r5,200
  LA r1,@mth_sg_test_x
  LA r2,@mth_sg_test_out_fail
  CALL @mth_vector_sigmoid256_f32
  MOVI r2,1
  CALL @mth_sg_test_expect_failure

  ; ---- Phase 8: -inf at index 0 rejects atomically.
  CALL @mth_sg_test_fill_sentinel
  CALL @mth_sg_test_prepare_sorted
  LA r5,@mth_sg_test_x
  MOVI r6,0
  MOVHI r6,0xFF80           ; -inf = 0xFF800000
  ST r6,r5,0
  LA r1,@mth_sg_test_x
  LA r2,@mth_sg_test_out_fail
  CALL @mth_vector_sigmoid256_f32
  MOVI r2,1
  CALL @mth_sg_test_expect_failure

  ; ---- Phase 9: recovery after rejected calls is bit-exact.
  CALL @mth_sg_test_prepare_sorted
  LA r1,@mth_sg_test_x
  LA r2,@mth_sg_test_out_neg
  CALL @mth_vector_sigmoid256_f32
  CMP r1,r13
  JMP[NE] @mth_sg_test_fail
  CMP r9,r0
  JMP[NE] @mth_sg_test_fail
  LA r1,@mth_sg_test_out_neg
  LA r2,@mth_sg_test_out
  CALL @mth_sg_test_compare256

  LA r1,@mth_sg_test_pass
  CALL @mth_sg_test_puts
  HALT

mth_sg_test_fail:
  LA r1,@mth_sg_test_bad
  CALL @mth_sg_test_puts
  HALT

; Fill x[0..255] with (float)(i - 128) * 0.15625. Tail-calls the filler so
; the single r15 link register still points at the original caller.
mth_sg_test_prepare_sorted:
  LA r1,@mth_sg_test_x
  MOVI r2,0xFF80
  MOVHI r2,0xFFFF           ; signed offset -128
  MOVI r3,0
  MOVHI r3,0x3E20           ; 0.15625 = 0x3E200000
  JMP @mth_sg_test_fill_iota_scaled

; r1 = destination, r2 = signed int32 offset, r3 = float32 scale.
; Stores CVTIF(i + offset) * scale for i = 0..255. Clobbers r1, r4-r6.
mth_sg_test_fill_iota_scaled:
  MOVI r4,0
  MOVI r5,256
mth_sg_test_fill_iota_scaled_loop:
  ADD r6,r4,r2
  CVTIF r6,r6
  FMUL r6,r6,r3
  ST r6,r1,0
  ADD r1,r1,r13
  ADD r4,r4,r13
  CMP r4,r5
  JMP[LT] @mth_sg_test_fill_iota_scaled_loop
  RET

; r1 = destination, r2 = payload. Fills all 256 words. Clobbers r1, r4, r5.
mth_sg_test_fill_value:
  MOVI r4,0
  MOVI r5,256
mth_sg_test_fill_value_loop:
  ST r2,r1,0
  ADD r1,r1,r13
  ADD r4,r4,r13
  CMP r4,r5
  JMP[LT] @mth_sg_test_fill_value_loop
  RET

; r1 = source, r2 = destination. dst[i] = src[i] XOR 0x80000000.
; Clobbers r1-r6.
mth_sg_test_negate256:
  MOVI r3,0
  MOVHI r3,0x8000           ; sign mask
  MOVI r4,0
  MOVI r6,256
mth_sg_test_negate256_loop:
  LD r5,r1,0
  BOOL.6 r5,r5,r3
  ST r5,r2,0
  ADD r1,r1,r13
  ADD r2,r2,r13
  ADD r4,r4,r13
  CMP r4,r6
  JMP[LT] @mth_sg_test_negate256_loop
  RET

; Fill out_fail[0..255] with 0xDEADBEEF. Clobbers r1, r2, r3, r5.
mth_sg_test_fill_sentinel:
  LA r1,@mth_sg_test_out_fail
  MOVI r2,0xBEEF
  MOVHI r2,0xDEAD           ; 0xDEADBEEF
  MOVI r3,0
  MOVI r5,256
mth_sg_test_fill_sentinel_loop:
  ST r2,r1,0
  ADD r1,r1,r13
  ADD r3,r3,r13
  CMP r3,r5
  JMP[LT] @mth_sg_test_fill_sentinel_loop
  RET

; r1 = return status, r9 = cause, r2 = expected cause. Requires r1=0,
; r9=r2, and every out_fail word still 0xDEADBEEF. Clobbers r1, r3-r6.
mth_sg_test_expect_failure:
  CMP r1,r0
  JMP[NE] @mth_sg_test_fail
  CMP r9,r2
  JMP[NE] @mth_sg_test_fail
  LA r1,@mth_sg_test_out_fail
  MOVI r3,0xBEEF
  MOVHI r3,0xDEAD           ; 0xDEADBEEF
  MOVI r4,0
  MOVI r5,256
mth_sg_test_expect_failure_loop:
  LD r6,r1,0
  CMP r6,r3
  JMP[NE] @mth_sg_test_fail
  ADD r1,r1,r13
  ADD r4,r4,r13
  CMP r4,r5
  JMP[LT] @mth_sg_test_expect_failure_loop
  RET

; r1 = out pointer. Requires every payload to have sign 0 and to be at most
; 1.0 (0x3F800000), which also excludes NaN and infinity. Clobbers r1-r6.
mth_sg_test_check_unit_range:
  MOVI r2,0
  MOVI r3,256
  MOVI r5,0
  MOVHI r5,0x3F80           ; 1.0
mth_sg_test_check_unit_range_loop:
  LD r4,r1,0
  SHR r6,r4,31
  CMP r6,r0
  JMP[NE] @mth_sg_test_fail
  CMP r4,r5
  JMP[GT] @mth_sg_test_fail
  ADD r1,r1,r13
  ADD r2,r2,r13
  CMP r2,r3
  JMP[LT] @mth_sg_test_check_unit_range_loop
  RET

; r1 = out pointer. Requires nonnegative payloads and payload[i] <=
; payload[i+1] as unsigned integers. Clobbers r1-r6.
mth_sg_test_check_monotonic:
  LD r2,r1,0
  SHR r5,r2,31
  CMP r5,r0
  JMP[NE] @mth_sg_test_fail
  MOVI r3,1
  MOVI r4,256
mth_sg_test_check_monotonic_loop:
  ADD r1,r1,r13
  LD r5,r1,0
  SHR r6,r5,31
  CMP r6,r0
  JMP[NE] @mth_sg_test_fail
  CMP r5,r2
  JMP[LT] @mth_sg_test_fail
  ADD r2,r5,r0
  ADD r3,r3,r13
  CMP r3,r4
  JMP[LT] @mth_sg_test_check_monotonic_loop
  RET

; r1 = sigmoid(x) pointer, r2 = sigmoid(-x) pointer, r3 = tolerance payload.
; Requires |out[i] + out_neg[i] - 1| <= tolerance using FADD/FSUB and an
; exact sign-bit clear, then an unsigned integer CMP. Clobbers r1, r2, r4-r9.
mth_sg_test_check_symmetry:
  MOVI r4,0
  MOVI r5,256
  MOVI r6,0
  MOVHI r6,0x3F80           ; 1.0
  MOVI r9,0xFFFF
  MOVHI r9,0x7FFF           ; 0x7FFFFFFF
mth_sg_test_check_symmetry_loop:
  LD r7,r1,0
  LD r8,r2,0
  FADD r7,r7,r8
  FSUB r7,r7,r6             ; sum - 1
  BOOL.8 r7,r7,r9           ; |sum - 1| (AND clears only the sign bit)
  CMP r7,r3
  JMP[GT] @mth_sg_test_fail
  ADD r1,r1,r13
  ADD r2,r2,r13
  ADD r4,r4,r13
  CMP r4,r5
  JMP[LT] @mth_sg_test_check_symmetry_loop
  RET

; r1 = pointer, r2 = value, r3 = count. Requires r3 equal payloads.
; Clobbers r1, r4, r5.
mth_sg_test_check_run_value:
  MOVI r4,0
mth_sg_test_check_run_value_loop:
  LD r5,r1,0
  CMP r5,r2
  JMP[NE] @mth_sg_test_fail
  ADD r1,r1,r13
  ADD r4,r4,r13
  CMP r4,r3
  JMP[LT] @mth_sg_test_check_run_value_loop
  RET

; r1 = actual pointer, r2 = expected pointer. Requires 256 equal payloads.
; Clobbers r1-r6.
mth_sg_test_compare256:
  MOVI r3,0
  MOVI r6,256
mth_sg_test_compare256_loop:
  LD r4,r1,0
  LD r5,r2,0
  CMP r4,r5
  JMP[NE] @mth_sg_test_fail
  ADD r1,r1,r13
  ADD r2,r2,r13
  ADD r3,r3,r13
  CMP r3,r6
  JMP[LT] @mth_sg_test_compare256_loop
  RET

mth_sg_test_puts:
  MOVI r4,255
mth_sg_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_sg_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_sg_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_sg_test_puts_word

.org 4096
mth_sg_test_x:
.word 0
.org 4352
mth_sg_test_neg:
.word 0
.org 4608
mth_sg_test_out:
.word 0
.org 4864
mth_sg_test_out_neg:
.word 0
.org 5120
mth_sg_test_out_fail:
.word 0
.org 5376
mth_sg_test_pass:
.str "MTH VECTOR SIGMOID256 F32 PASS\n"
mth_sg_test_bad:
.str "MTH VECTOR SIGMOID256 F32 FAIL\n"
