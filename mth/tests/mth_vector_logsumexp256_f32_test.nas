; MTH vector log-sum-exp256 float32 fixture — NaN16 only.
;
; All input vectors are generated in the guest at run time. Every structural
; check is an integer CMP or an FCMP on 32-bit payloads; the only float
; operations in the checks are FSUB to form a difference and FCMP to test a
; bound against documented constants. No host arithmetic produces an
; expected value.
;
; Success phases:
;   1. x[i] = (float)(i - 128), strictly increasing. Checks return status,
;      cause, result finiteness, and the analytic bounds
;      max = 127 <= LSE <= 127 + ln(256) + 2^-12. Saves the result as the
;      phase-1 reference.
;   2. The same vector plus the exact constant 16.0. Checks that
;      LSE(x + 16) - LSE(x) - 16 is within 2^-12 of zero (shift invariance).
;   3. x[i] = 3.25 for every i. Checks LSE - 3.25 against 8*ln(2) = ln(256)
;      within 2^-12 (all-equal input).
;   4. x[0] = 7.5 and x[1..255] = -100.0. Every non-max term is below the
;      documented -20 cutoff, so S = 1 and the result must be exactly 7.5
;      (dominated element with finite tail).
;   5. x[100] = -100.0 and all other elements = -inf. The -inf positions are
;      legal empty positions and contribute exactly nothing, so the result
;      must be exactly -100.0 (dominated element with empty tail).
;   6. The phase-1 vector with x[0] replaced by -inf. Index 0 was already
;      below the exp cutoff, so the result must be bit-identical to phase 1.
;
; Failure phases (out_fail is pre-filled with 0xDEADBEEF):
;   7. All 256 inputs are -inf: empty support, return 0, cause 2.
;   8. Quiet NaN at index 17: return 0, cause 1.
;   9. +inf at index 200: return 0, cause 1.
;  10. Signaling NaN at index 255: return 0, cause 1.
;  Every failure phase checks r1=0, the exact cause, and that all 256 output
;  words remain 0xDEADBEEF, i.e. the rejection is atomic.
;
; Recovery phase:
;  11. Rebuild the phase-1 input and rerun. The result must match the saved
;      phase-1 reference payload exactly.

.org 0
JMP @mth_lse_test_main
.include "../nan16/mth_vector_logsumexp256_f32.nas"

mth_lse_test_main:
  MOVI r13,1

  ; ---- Phase 1: strictly increasing input and analytic bounds.
  LA r1,@mth_lse_test_x
  MOVI r2,0xFF80
  MOVHI r2,0xFFFF            ; offset -128
  CALL @mth_lse_test_fill_iota
  LA r1,@mth_lse_test_x
  LA r2,@mth_lse_test_out_a
  CALL @mth_vector_logsumexp256_f32
  CMP r1,r13
  JMP[NE] @mth_lse_test_fail
  CMP r9,r0
  JMP[NE] @mth_lse_test_fail
  LA r5,@mth_lse_test_out_a
  LD r6,r5,0
  MOVI r7,0
  MOVHI r7,0x7F80            ; exponent mask
  BOOL.8 r8,r6,r7
  CMP r8,r7
  JMP[EQ] @mth_lse_test_fail ; NaN or infinity
  MOVI r7,0
  MOVHI r7,0x42FE            ; 127.0
  FCMP r6,r7
  JMP[LT] @mth_lse_test_fail
  MOVI r7,0x8BA1
  MOVHI r7,0x4304            ; 127 + ln(256) + 2^-12
  FCMP r6,r7
  JMP[GT] @mth_lse_test_fail
  LA r5,@mth_lse_test_ref
  ST r6,r5,0                 ; save phase-1 reference

  ; ---- Phase 2: exact +16 shift, result must shift by 16.
  LA r1,@mth_lse_test_x
  MOVI r2,0xFF90
  MOVHI r2,0xFFFF            ; offset -112 = -128 + 16
  CALL @mth_lse_test_fill_iota
  LA r1,@mth_lse_test_x
  LA r2,@mth_lse_test_out_b
  CALL @mth_vector_logsumexp256_f32
  CMP r1,r13
  JMP[NE] @mth_lse_test_fail
  CMP r9,r0
  JMP[NE] @mth_lse_test_fail
  LA r5,@mth_lse_test_out_b
  LD r6,r5,0
  LA r5,@mth_lse_test_ref
  LD r7,r5,0
  FSUB r6,r6,r7              ; shifted result - reference
  MOVI r7,0
  MOVHI r7,0x4180            ; 16.0
  FSUB r1,r6,r7              ; must be close to zero
  MOVI r2,0
  MOVI r3,0
  MOVHI r3,0x3980            ; 2^-12
  CALL @mth_lse_test_check_close

  ; ---- Phase 3: all-equal input; LSE - 3.25 = ln(256).
  LA r1,@mth_lse_test_x
  MOVI r2,0
  MOVHI r2,0x4050            ; 3.25
  CALL @mth_lse_test_fill_value
  LA r1,@mth_lse_test_x
  LA r2,@mth_lse_test_out_b
  CALL @mth_vector_logsumexp256_f32
  CMP r1,r13
  JMP[NE] @mth_lse_test_fail
  CMP r9,r0
  JMP[NE] @mth_lse_test_fail
  LA r5,@mth_lse_test_out_b
  LD r1,r5,0
  MOVI r2,0
  MOVHI r2,0x4050            ; 3.25
  FSUB r1,r1,r2
  MOVI r2,0x7218
  MOVHI r2,0x40B1            ; 8*ln(2) = 0x40B17218
  MOVI r3,0
  MOVHI r3,0x3980            ; 2^-12
  CALL @mth_lse_test_check_close

  ; ---- Phase 4: one dominant element, finite tail below the cutoff.
  LA r1,@mth_lse_test_x
  MOVI r2,0
  MOVHI r2,0xC2C8            ; -100.0
  CALL @mth_lse_test_fill_value
  LA r5,@mth_lse_test_x
  MOVI r6,0
  MOVHI r6,0x40F0            ; 7.5
  ST r6,r5,0
  LA r1,@mth_lse_test_x
  LA r2,@mth_lse_test_out_b
  CALL @mth_vector_logsumexp256_f32
  CMP r1,r13
  JMP[NE] @mth_lse_test_fail
  CMP r9,r0
  JMP[NE] @mth_lse_test_fail
  LA r5,@mth_lse_test_out_b
  LD r1,r5,0
  MOVI r2,0
  MOVHI r2,0x40F0            ; exact 7.5
  CALL @mth_lse_test_check_equal

  ; ---- Phase 5: one dominant element, empty (-inf) tail.
  LA r1,@mth_lse_test_x
  MOVI r2,0
  MOVHI r2,0xFF80            ; -inf
  CALL @mth_lse_test_fill_value
  LA r5,@mth_lse_test_x
  MOVI r6,0
  MOVHI r6,0xC2C8            ; -100.0
  ST r6,r5,100
  LA r1,@mth_lse_test_x
  LA r2,@mth_lse_test_out_b
  CALL @mth_vector_logsumexp256_f32
  CMP r1,r13
  JMP[NE] @mth_lse_test_fail
  CMP r9,r0
  JMP[NE] @mth_lse_test_fail
  LA r5,@mth_lse_test_out_b
  LD r1,r5,0
  MOVI r2,0
  MOVHI r2,0xC2C8            ; exact -100.0
  CALL @mth_lse_test_check_equal

  ; ---- Phase 6: -inf at an index already below the exp cutoff is neutral.
  LA r1,@mth_lse_test_x
  MOVI r2,0xFF80
  MOVHI r2,0xFFFF            ; offset -128
  CALL @mth_lse_test_fill_iota
  LA r5,@mth_lse_test_x
  MOVI r6,0
  MOVHI r6,0xFF80            ; -inf = 0xFF800000
  ST r6,r5,0
  LA r1,@mth_lse_test_x
  LA r2,@mth_lse_test_out_b
  CALL @mth_vector_logsumexp256_f32
  CMP r1,r13
  JMP[NE] @mth_lse_test_fail
  CMP r9,r0
  JMP[NE] @mth_lse_test_fail
  LA r5,@mth_lse_test_out_b
  LD r1,r5,0
  LA r5,@mth_lse_test_ref
  LD r2,r5,0
  CALL @mth_lse_test_check_equal

  ; ---- Phase 7: all -inf is empty support, cause 2, atomic failure.
  CALL @mth_lse_test_fill_sentinel
  LA r1,@mth_lse_test_x
  MOVI r2,0
  MOVHI r2,0xFF80            ; -inf
  CALL @mth_lse_test_fill_value
  LA r1,@mth_lse_test_x
  LA r2,@mth_lse_test_out_fail
  CALL @mth_vector_logsumexp256_f32
  MOVI r2,2
  CALL @mth_lse_test_expect_failure

  ; ---- Phase 8: quiet NaN rejects with cause 1.
  CALL @mth_lse_test_fill_sentinel
  LA r1,@mth_lse_test_x
  MOVI r2,0xFF80
  MOVHI r2,0xFFFF            ; offset -128
  CALL @mth_lse_test_fill_iota
  LA r5,@mth_lse_test_x
  MOVI r6,0
  MOVHI r6,0x7FC0            ; quiet NaN = 0x7FC00000
  ST r6,r5,17
  LA r1,@mth_lse_test_x
  LA r2,@mth_lse_test_out_fail
  CALL @mth_vector_logsumexp256_f32
  MOVI r2,1
  CALL @mth_lse_test_expect_failure

  ; ---- Phase 9: +inf rejects with cause 1.
  CALL @mth_lse_test_fill_sentinel
  LA r1,@mth_lse_test_x
  MOVI r2,0xFF80
  MOVHI r2,0xFFFF            ; offset -128
  CALL @mth_lse_test_fill_iota
  LA r5,@mth_lse_test_x
  MOVI r6,0
  MOVHI r6,0x7F80            ; +inf = 0x7F800000
  ST r6,r5,200
  LA r1,@mth_lse_test_x
  LA r2,@mth_lse_test_out_fail
  CALL @mth_vector_logsumexp256_f32
  MOVI r2,1
  CALL @mth_lse_test_expect_failure

  ; ---- Phase 10: signaling NaN at the last index, cause 1.
  CALL @mth_lse_test_fill_sentinel
  LA r1,@mth_lse_test_x
  MOVI r2,0xFF80
  MOVHI r2,0xFFFF            ; offset -128
  CALL @mth_lse_test_fill_iota
  LA r5,@mth_lse_test_x
  MOVI r6,1
  MOVHI r6,0x7F80            ; signaling NaN = 0x7F800001
  ST r6,r5,255
  LA r1,@mth_lse_test_x
  LA r2,@mth_lse_test_out_fail
  CALL @mth_vector_logsumexp256_f32
  MOVI r2,1
  CALL @mth_lse_test_expect_failure

  ; ---- Phase 11: recovery after rejected calls is bit-exact.
  LA r1,@mth_lse_test_x
  MOVI r2,0xFF80
  MOVHI r2,0xFFFF            ; offset -128
  CALL @mth_lse_test_fill_iota
  LA r1,@mth_lse_test_x
  LA r2,@mth_lse_test_out_b
  CALL @mth_vector_logsumexp256_f32
  CMP r1,r13
  JMP[NE] @mth_lse_test_fail
  CMP r9,r0
  JMP[NE] @mth_lse_test_fail
  LA r5,@mth_lse_test_out_b
  LD r1,r5,0
  LA r5,@mth_lse_test_ref
  LD r2,r5,0
  CALL @mth_lse_test_check_equal

  LA r1,@mth_lse_test_pass
  CALL @mth_lse_test_puts
  HALT

mth_lse_test_fail:
  LA r1,@mth_lse_test_bad
  CALL @mth_lse_test_puts
  HALT

; Fill 256 words at r1 with CVTIF(i + r2), where r2 is a signed 32-bit
; integer offset. Clobbers r1, r3-r5.
mth_lse_test_fill_iota:
  MOVI r3,0
  MOVI r5,256
mth_lse_test_fill_iota_loop:
  ADD r4,r3,r2
  CVTIF r4,r4
  ST r4,r1,0
  ADD r1,r1,r13
  ADD r3,r3,r13
  CMP r3,r5
  JMP[LT] @mth_lse_test_fill_iota_loop
  RET

; Fill 256 words at r1 with the payload in r2. Clobbers r1, r3-r5.
mth_lse_test_fill_value:
  MOVI r3,0
  MOVI r5,256
mth_lse_test_fill_value_loop:
  ST r2,r1,0
  ADD r1,r1,r13
  ADD r3,r3,r13
  CMP r3,r5
  JMP[LT] @mth_lse_test_fill_value_loop
  RET

; Fill out_fail[0..255] with 0xDEADBEEF.
mth_lse_test_fill_sentinel:
  LA r1,@mth_lse_test_out_fail
  MOVI r2,0xDEAD
  MOVHI r2,0xDEAD            ; 0xDEADBEEF
  MOVI r3,0
  MOVI r5,256
mth_lse_test_fill_sentinel_loop:
  ST r2,r1,0
  ADD r1,r1,r13
  ADD r3,r3,r13
  CMP r3,r5
  JMP[LT] @mth_lse_test_fill_sentinel_loop
  RET

; r1 = return status, r9 = cause, r2 = expected cause. Requires r1=0,
; r9=r2, and every out_fail word still 0xDEADBEEF. Clobbers r1, r3-r6.
mth_lse_test_expect_failure:
  CMP r1,r0
  JMP[NE] @mth_lse_test_fail
  CMP r9,r2
  JMP[NE] @mth_lse_test_fail
  LA r1,@mth_lse_test_out_fail
  MOVI r3,0xDEAD
  MOVHI r3,0xDEAD            ; 0xDEADBEEF
  MOVI r4,0
  MOVI r5,256
mth_lse_test_expect_failure_loop:
  LD r6,r1,0
  CMP r6,r3
  JMP[NE] @mth_lse_test_fail
  ADD r1,r1,r13
  ADD r4,r4,r13
  CMP r4,r5
  JMP[LT] @mth_lse_test_expect_failure_loop
  RET

; r1 = actual payload, r2 = expected payload, r3 = tolerance.
; Requires actual to be finite and |actual - expected| <= tolerance.
; Clobbers r1, r4-r7.
mth_lse_test_check_close:
  MOVI r6,0
  MOVHI r6,0x7F80            ; exponent mask
  BOOL.8 r7,r1,r6
  CMP r7,r6
  JMP[EQ] @mth_lse_test_fail ; reject NaN and infinities
  FSUB r4,r1,r2
  FCMP r4,r3
  JMP[GT] @mth_lse_test_fail
  FSUB r5,r0,r3              ; -tolerance
  FCMP r4,r5
  JMP[LT] @mth_lse_test_fail
  RET

; r1 = actual payload, r2 = expected payload. Requires exact equality.
mth_lse_test_check_equal:
  CMP r1,r2
  JMP[NE] @mth_lse_test_fail
  RET

mth_lse_test_puts:
  MOVI r4,255
mth_lse_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_lse_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_lse_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_lse_test_puts_word

.org 1024
mth_lse_test_x:
.word 0
.org 1536
mth_lse_test_out_a:
.word 0
.org 1664
mth_lse_test_out_b:
.word 0
.org 1792
mth_lse_test_ref:
.word 0
.org 2048
mth_lse_test_out_fail:
.word 0
.org 3072
mth_lse_test_pass:
.str "MTH VECTOR LOGSUMEXP256 F32 PASS\n"
mth_lse_test_bad:
.str "MTH VECTOR LOGSUMEXP256 F32 FAIL\n"
