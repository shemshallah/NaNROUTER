; MTH vector softmax256 float32 fixture — NaN16 only.
;
; All input vectors and all expected sentinels are generated in the guest at
; run time. No host arithmetic produces an expected value. Every structural
; check is an integer CMP on raw 32-bit payloads; the only float operation in
; the checks is the increasing-order FADD used to form the output sum, whose
; payload is then compared against exact binary32 bounds as an integer.
;
; Success phases:
;   1. x[i] = (float)(i - 128), strictly increasing. The lower tail is far
;      below the documented -20 cutoff and correctly underflows to +0.0.
;      Checks:
;      - return status and cause,
;      - every output is nonnegative and finite,
;      - the maximum-index output (the largest logit) is positive,
;      - output payloads are nondecreasing (positive binary32 ordering),
;      - the top three outputs are strictly ordered (the exp is not flat),
;      - increasing-order output sum in [1 - 2^-12, 1 + 2^-12].
;   2. x[i] = (float)(i + 896), the phase-1 vector plus the exact constant
;      1024. Checks the same sum bound and requires all 256 output payloads
;      to be bit-identical to phase 1 (max-shift stability).
;   3. x[i] = 3.25 for every i. The exact result is 1/256 = 0x3B800000 for
;      every element; checks all 256 payloads and the sum.
;   4. Sorted vector with -inf at indices 0 and 1. Checks that -inf outputs
;      are exactly +0.0, that the remaining outputs stay monotonic, and that
;      the sum bound still holds.
;
; Failure phases (out_fail is pre-filled with 0xDEADBEEF):
;   5. All 256 inputs are -inf: empty support, return 0, cause 2.
;   6. Quiet NaN at index 17: return 0, cause 1.
;   7. +inf at index 200: return 0, cause 1.
;   8. Signaling NaN at index 255: return 0, cause 1.
;   Every failure phase checks r1=0, the exact cause, and that all 256 output
;   words remain 0xDEADBEEF, i.e. the rejection is atomic.
;
; Recovery phase:
;   9. Rebuild the phase-1 input and rerun. Every output payload must match
;      the phase-1 reference exactly.

.org 0
JMP @mth_sm_test_main
.include "../nan16/mth_vector_softmax256_f32.nas"

mth_sm_test_main:
  MOVI r13,1

  ; ---- Phase 1: strictly increasing input.
  LA r1,@mth_sm_test_x
  MOVI r2,0xFF80
  MOVHI r2,0xFFFF            ; offset -128
  CALL @mth_sm_test_fill_iota
  LA r1,@mth_sm_test_x
  LA r2,@mth_sm_test_out
  CALL @mth_vector_softmax256_f32
  CMP r1,r13
  JMP[NE] @mth_sm_test_fail
  CMP r9,r0
  JMP[NE] @mth_sm_test_fail
  LA r1,@mth_sm_test_out
  CALL @mth_sm_test_check_outputs
  LA r1,@mth_sm_test_out
  CALL @mth_sm_test_check_monotonic
  LA r5,@mth_sm_test_out
  LD r6,r5,254
  LD r7,r5,255
  CMP r6,r7
  JMP[GE] @mth_sm_test_fail
  LD r6,r5,253
  LD r7,r5,254
  CMP r6,r7
  JMP[GE] @mth_sm_test_fail
  LA r1,@mth_sm_test_out
  CALL @mth_sm_test_check_sum

  ; ---- Phase 2: exact +1024 max shift, outputs must be bit-identical.
  LA r1,@mth_sm_test_x_shift
  MOVI r2,896
  CALL @mth_sm_test_fill_iota
  LA r1,@mth_sm_test_x_shift
  LA r2,@mth_sm_test_out_shift
  CALL @mth_vector_softmax256_f32
  CMP r1,r13
  JMP[NE] @mth_sm_test_fail
  CMP r9,r0
  JMP[NE] @mth_sm_test_fail
  LA r1,@mth_sm_test_out
  LA r2,@mth_sm_test_out_shift
  CALL @mth_sm_test_compare256
  LA r1,@mth_sm_test_out_shift
  CALL @mth_sm_test_check_monotonic
  LA r1,@mth_sm_test_out_shift
  CALL @mth_sm_test_check_sum

  ; ---- Phase 3: all-equal input; exact uniform output 1/256.
  LA r1,@mth_sm_test_x
  MOVI r2,0
  MOVHI r2,0x4050            ; 3.25 = 0x40500000
  CALL @mth_sm_test_fill_value
  LA r1,@mth_sm_test_x
  LA r2,@mth_sm_test_out_shift
  CALL @mth_vector_softmax256_f32
  CMP r1,r13
  JMP[NE] @mth_sm_test_fail
  CMP r9,r0
  JMP[NE] @mth_sm_test_fail
  LA r1,@mth_sm_test_out_shift
  MOVI r2,0
  MOVHI r2,0x3B80            ; 1/256 = 0x3B800000
  CALL @mth_sm_test_check_all_value
  LA r1,@mth_sm_test_out_shift
  CALL @mth_sm_test_check_sum

  ; ---- Phase 4: legal -inf positions at the head of a sorted vector.
  LA r1,@mth_sm_test_x
  MOVI r2,0xFF80
  MOVHI r2,0xFFFF            ; offset -128
  CALL @mth_sm_test_fill_iota
  LA r5,@mth_sm_test_x
  MOVI r6,0
  MOVHI r6,0xFF80            ; -inf = 0xFF800000
  ST r6,r5,0
  ST r6,r5,1
  LA r1,@mth_sm_test_x
  LA r2,@mth_sm_test_out_shift
  CALL @mth_vector_softmax256_f32
  CMP r1,r13
  JMP[NE] @mth_sm_test_fail
  CMP r9,r0
  JMP[NE] @mth_sm_test_fail
  LA r5,@mth_sm_test_out_shift
  LD r6,r5,0
  CMP r6,r0
  JMP[NE] @mth_sm_test_fail
  LD r6,r5,1
  CMP r6,r0
  JMP[NE] @mth_sm_test_fail
  LA r1,@mth_sm_test_out_shift
  CALL @mth_sm_test_check_monotonic
  LA r1,@mth_sm_test_out_shift
  CALL @mth_sm_test_check_sum

  ; ---- Phase 5: all -inf is empty support, cause 2, atomic failure.
  CALL @mth_sm_test_fill_sentinel
  LA r1,@mth_sm_test_x
  MOVI r2,0
  MOVHI r2,0xFF80            ; -inf = 0xFF800000
  CALL @mth_sm_test_fill_value
  LA r1,@mth_sm_test_x
  LA r2,@mth_sm_test_out_fail
  CALL @mth_vector_softmax256_f32
  MOVI r2,2
  CALL @mth_sm_test_expect_failure

  ; ---- Phase 6: quiet NaN rejects with cause 1.
  CALL @mth_sm_test_fill_sentinel
  LA r1,@mth_sm_test_x
  MOVI r2,0xFF80
  MOVHI r2,0xFFFF            ; offset -128
  CALL @mth_sm_test_fill_iota
  LA r5,@mth_sm_test_x
  MOVI r6,0
  MOVHI r6,0x7FC0            ; quiet NaN = 0x7FC00000
  ST r6,r5,17
  LA r1,@mth_sm_test_x
  LA r2,@mth_sm_test_out_fail
  CALL @mth_vector_softmax256_f32
  MOVI r2,1
  CALL @mth_sm_test_expect_failure

  ; ---- Phase 7: +inf rejects with cause 1.
  CALL @mth_sm_test_fill_sentinel
  LA r1,@mth_sm_test_x
  MOVI r2,0xFF80
  MOVHI r2,0xFFFF            ; offset -128
  CALL @mth_sm_test_fill_iota
  LA r5,@mth_sm_test_x
  MOVI r6,0
  MOVHI r6,0x7F80            ; +inf = 0x7F800000
  ST r6,r5,200
  LA r1,@mth_sm_test_x
  LA r2,@mth_sm_test_out_fail
  CALL @mth_vector_softmax256_f32
  MOVI r2,1
  CALL @mth_sm_test_expect_failure

  ; ---- Phase 8: signaling NaN at the last index, cause 1.
  CALL @mth_sm_test_fill_sentinel
  LA r1,@mth_sm_test_x
  MOVI r2,0xFF80
  MOVHI r2,0xFFFF            ; offset -128
  CALL @mth_sm_test_fill_iota
  LA r5,@mth_sm_test_x
  MOVI r6,1
  MOVHI r6,0x7F80            ; signaling NaN = 0x7F800001
  ST r6,r5,255
  LA r1,@mth_sm_test_x
  LA r2,@mth_sm_test_out_fail
  CALL @mth_vector_softmax256_f32
  MOVI r2,1
  CALL @mth_sm_test_expect_failure

  ; ---- Phase 9: recovery after rejected calls is bit-exact.
  LA r1,@mth_sm_test_x
  MOVI r2,0xFF80
  MOVHI r2,0xFFFF            ; offset -128
  CALL @mth_sm_test_fill_iota
  LA r1,@mth_sm_test_x
  LA r2,@mth_sm_test_out_shift
  CALL @mth_vector_softmax256_f32
  CMP r1,r13
  JMP[NE] @mth_sm_test_fail
  CMP r9,r0
  JMP[NE] @mth_sm_test_fail
  LA r1,@mth_sm_test_out_shift
  LA r2,@mth_sm_test_out
  CALL @mth_sm_test_compare256

  LA r1,@mth_sm_test_pass
  CALL @mth_sm_test_puts
  HALT

mth_sm_test_fail:
  LA r1,@mth_sm_test_bad
  CALL @mth_sm_test_puts
  HALT

; Fill 256 words at r1 with CVTIF(i + r2), where r2 is a signed 32-bit
; integer offset. Clobbers r1, r3-r5.
mth_sm_test_fill_iota:
  MOVI r3,0
  MOVI r5,256
mth_sm_test_fill_iota_loop:
  ADD r4,r3,r2
  CVTIF r4,r4
  ST r4,r1,0
  ADD r1,r1,r13
  ADD r3,r3,r13
  CMP r3,r5
  JMP[LT] @mth_sm_test_fill_iota_loop
  RET

; Fill 256 words at r1 with the payload in r2. Clobbers r1, r3-r5.
mth_sm_test_fill_value:
  MOVI r3,0
  MOVI r5,256
mth_sm_test_fill_value_loop:
  ST r2,r1,0
  ADD r1,r1,r13
  ADD r3,r3,r13
  CMP r3,r5
  JMP[LT] @mth_sm_test_fill_value_loop
  RET

; Fill out_fail[0..255] with 0xDEADBEEF.
mth_sm_test_fill_sentinel:
  LA r1,@mth_sm_test_out_fail
  MOVI r2,0xDEAD
  MOVHI r2,0xDEAD            ; 0xDEADBEEF
  MOVI r3,0
  MOVI r5,256
mth_sm_test_fill_sentinel_loop:
  ST r2,r1,0
  ADD r1,r1,r13
  ADD r3,r3,r13
  CMP r3,r5
  JMP[LT] @mth_sm_test_fill_sentinel_loop
  RET

; r1 = return status, r9 = cause, r2 = expected cause. Requires r1=0,
; r9=r2, and every out_fail word still 0xDEADBEEF. Clobbers r1, r3-r6.
mth_sm_test_expect_failure:
  CMP r1,r0
  JMP[NE] @mth_sm_test_fail
  CMP r9,r2
  JMP[NE] @mth_sm_test_fail
  LA r1,@mth_sm_test_out_fail
  MOVI r3,0xDEAD
  MOVHI r3,0xDEAD            ; 0xDEADBEEF
  MOVI r4,0
  MOVI r5,256
mth_sm_test_expect_failure_loop:
  LD r6,r1,0
  CMP r6,r3
  JMP[NE] @mth_sm_test_fail
  ADD r1,r1,r13
  ADD r4,r4,r13
  CMP r4,r5
  JMP[LT] @mth_sm_test_expect_failure_loop
  RET

; r1 = out pointer. Every payload must have sign 0 and must not be in the
; exponent-all-ones class; +0.0 is allowed for the documented tail cutoff.
; The last element (the maximum logit in the phase-1 vector) must be nonzero.
; Clobbers r1-r6.
mth_sm_test_check_outputs:
  MOVI r4,0
  MOVHI r4,0x7F80            ; exponent mask
  MOVI r2,0
  MOVI r3,256
mth_sm_test_check_outputs_loop:
  LD r5,r1,0
  SHR r6,r5,31
  CMP r6,r0
  JMP[NE] @mth_sm_test_fail
  BOOL.8 r6,r5,r4
  CMP r6,r4
  JMP[EQ] @mth_sm_test_fail
  ADD r1,r1,r13
  ADD r2,r2,r13
  CMP r2,r3
  JMP[LT] @mth_sm_test_check_outputs_loop
  SUB r1,r1,r13
  LD r5,r1,0
  CMP r5,r0
  JMP[EQ] @mth_sm_test_fail
  RET

; r1 = out pointer. Requires every payload to be nonnegative and finite,
; and requires payload[i] <= payload[i+1] as an unsigned integer. All legal
; outputs are nonnegative binary32 values, so their raw payload order is the
; numeric order. Clobbers r1-r8.
mth_sm_test_check_monotonic:
  MOVI r7,0
  MOVHI r7,0x7F80            ; exponent mask
  LD r5,r1,0
  SHR r6,r5,31
  CMP r6,r0
  JMP[NE] @mth_sm_test_fail
  BOOL.8 r8,r5,r7
  CMP r8,r7
  JMP[EQ] @mth_sm_test_fail
  MOVI r2,1
  MOVI r3,256
mth_sm_test_check_monotonic_loop:
  ADD r1,r1,r13
  LD r6,r1,0
  SHR r8,r6,31
  CMP r8,r0
  JMP[NE] @mth_sm_test_fail
  BOOL.8 r8,r6,r7
  CMP r8,r7
  JMP[EQ] @mth_sm_test_fail
  CMP r6,r5
  JMP[LT] @mth_sm_test_fail
  ADD r5,r6,r0
  ADD r2,r2,r13
  CMP r2,r3
  JMP[LT] @mth_sm_test_check_monotonic_loop
  RET

; r1 = out pointer. Sums all 256 payloads in increasing index order with
; FADD, then requires the sum payload to lie in [1-2^-12, 1+2^-12] using
; integer CMP. Clobbers r1-r5.
mth_sm_test_check_sum:
  MOVI r2,0                  ; +0.0
  MOVI r3,0
  MOVI r4,256
mth_sm_test_check_sum_loop:
  LD r5,r1,0
  FADD r2,r2,r5
  ADD r1,r1,r13
  ADD r3,r3,r13
  CMP r3,r4
  JMP[LT] @mth_sm_test_check_sum_loop
  MOVI r5,0xF000
  MOVHI r5,0x3F7F            ; 1 - 2^-12 = 0x3F7FF000
  CMP r2,r5
  JMP[LT] @mth_sm_test_fail
  MOVI r5,0x0800
  MOVHI r5,0x3F80            ; 1 + 2^-12 = 0x3F800800
  CMP r2,r5
  JMP[GT] @mth_sm_test_fail
  RET

; r1 = actual pointer, r2 = expected pointer. Requires 256 equal payloads.
; Clobbers r1-r6.
mth_sm_test_compare256:
  MOVI r3,0
  MOVI r6,256
mth_sm_test_compare256_loop:
  LD r4,r1,0
  LD r5,r2,0
  CMP r4,r5
  JMP[NE] @mth_sm_test_fail
  ADD r1,r1,r13
  ADD r2,r2,r13
  ADD r3,r3,r13
  CMP r3,r6
  JMP[LT] @mth_sm_test_compare256_loop
  RET

; r1 = pointer, r2 = required payload. Requires 256 equal payloads.
; Clobbers r1, r3-r5.
mth_sm_test_check_all_value:
  MOVI r3,0
  MOVI r4,256
mth_sm_test_check_all_value_loop:
  LD r5,r1,0
  CMP r5,r2
  JMP[NE] @mth_sm_test_fail
  ADD r1,r1,r13
  ADD r3,r3,r13
  CMP r3,r4
  JMP[LT] @mth_sm_test_check_all_value_loop
  RET

mth_sm_test_puts:
  MOVI r4,255
mth_sm_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_sm_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_sm_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_sm_test_puts_word

.org 1024
mth_sm_test_x:
.word 0
.org 2048
mth_sm_test_out:
.word 0
.org 3072
mth_sm_test_x_shift:
.word 0
.org 4096
mth_sm_test_out_shift:
.word 0
.org 5120
mth_sm_test_out_fail:
.word 0
.org 6144
mth_sm_test_pass:
.str "MTH VECTOR SOFTMAX256 F32 PASS\n"
mth_sm_test_bad:
.str "MTH VECTOR SOFTMAX256 F32 FAIL\n"
