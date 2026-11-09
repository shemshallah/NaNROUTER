; MTH vector rsqrt256 float32 fixture — NaN16 only.
;
; All 256-word input and expected-reference arrays are generated in the guest
; at run time; no expected array is computed on the host. The general-case
; reference is an in-guest FDIV reciprocal of the generated integer n.
; Every success check is an unsigned 32-bit payload-distance check with a
; 32-ulp bound. Every failure check verifies the return status, the cause
; register, and that all 256 output words are still 0xDEADDEAD.
;
; Success phases:
;   1. x[i] = (i+1)^2, expected 1/(i+1) from in-guest FDIV.
;   2. x[i] = 2^(2k), k = i mod 64, expected 2^(-k).
;   3. x[i] = 2^(-2k), k = i mod 64, expected 2^k.
;   4. x[i] = 2^-128 (0x00200000) subnormal, expected 2^64.
;   5. x[i] = 2^-149 (0x00000001) min subnormal, expected 0x64B504F3.
;   6. x[i] = FLT_MAX, expected 0x1F800000.
;   7. phase-1 input with out == x: exact aliasing is safe.
;
; Failure phases:
;   8. +0.0 at index 0 -> non-positive finite, cause 2.
;   9. -0.0 at index 1 -> non-positive finite, cause 2.
;  10. -4.0 at index 2 -> non-positive finite, cause 2.
;  11. quiet NaN at index 100 -> non-finite, cause 1.
;  12. +inf at index 4 -> non-finite, cause 1.
;  13. -inf at index 200 -> non-finite (tested before sign), cause 1.
;  14. recovery: phase 1 succeeds again after the rejections.

.org 0
JMP @mth_vrsqrt_test_main
.include "../nan16/mth_vector_rsqrt256_f32.nas"

mth_vrsqrt_test_main:
  MOVI r13,1

  ; ---- Phase 1: generated perfect squares against in-guest FDIV reciprocal.
  MOVI r1,@mth_vrsqrt_test_x
  MOVI r2,@mth_vrsqrt_test_exp
  CALL @mth_vrsqrt_test_fill_squares
  CALL @mth_vrsqrt_test_call
  CMP r1,r13
  JMP[NE] @mth_vrsqrt_test_fail
  CMP r9,r0
  JMP[NE] @mth_vrsqrt_test_fail
  MOVI r1,@mth_vrsqrt_test_out
  MOVI r2,@mth_vrsqrt_test_exp
  MOVI r4,32
  CALL @mth_vrsqrt_test_check_ulp

  ; ---- Phase 2: x = 2^(2k), expected 2^(-k).
  MOVI r11,0
  MOVI r1,@mth_vrsqrt_test_x
  MOVI r2,@mth_vrsqrt_test_exp
  CALL @mth_vrsqrt_test_fill_pow2
  CALL @mth_vrsqrt_test_call
  CMP r1,r13
  JMP[NE] @mth_vrsqrt_test_fail
  CMP r9,r0
  JMP[NE] @mth_vrsqrt_test_fail
  MOVI r1,@mth_vrsqrt_test_out
  MOVI r2,@mth_vrsqrt_test_exp
  MOVI r4,32
  CALL @mth_vrsqrt_test_check_ulp

  ; ---- Phase 3: x = 2^(-2k), expected 2^k.
  MOVI r11,1
  MOVI r1,@mth_vrsqrt_test_x
  MOVI r2,@mth_vrsqrt_test_exp
  CALL @mth_vrsqrt_test_fill_pow2
  CALL @mth_vrsqrt_test_call
  CMP r1,r13
  JMP[NE] @mth_vrsqrt_test_fail
  CMP r9,r0
  JMP[NE] @mth_vrsqrt_test_fail
  MOVI r1,@mth_vrsqrt_test_out
  MOVI r2,@mth_vrsqrt_test_exp
  MOVI r4,32
  CALL @mth_vrsqrt_test_check_ulp

  ; ---- Phase 4: 2^-128 subnormal input, rsqrt = 2^64.
  MOVI r1,@mth_vrsqrt_test_x
  MOVI r2,0
  MOVHI r2,0x0020            ; 0x00200000 = 2^-128
  CALL @mth_vrsqrt_test_fill_const
  MOVI r1,@mth_vrsqrt_test_exp
  MOVI r2,0
  MOVHI r2,0x5F80            ; 0x5F800000 = 2^64
  CALL @mth_vrsqrt_test_fill_const
  CALL @mth_vrsqrt_test_call
  CMP r1,r13
  JMP[NE] @mth_vrsqrt_test_fail
  CMP r9,r0
  JMP[NE] @mth_vrsqrt_test_fail
  MOVI r1,@mth_vrsqrt_test_out
  MOVI r2,@mth_vrsqrt_test_exp
  MOVI r4,32
  CALL @mth_vrsqrt_test_check_ulp

  ; ---- Phase 5: minimum positive subnormal input.
  MOVI r1,@mth_vrsqrt_test_x
  MOVI r2,1                  ; 0x00000001 = 2^-149
  CALL @mth_vrsqrt_test_fill_const
  MOVI r1,@mth_vrsqrt_test_exp
  MOVI r2,0x04F3
  MOVHI r2,0x64B5            ; 0x64B504F3 = rsqrt(2^-149)
  CALL @mth_vrsqrt_test_fill_const
  CALL @mth_vrsqrt_test_call
  CMP r1,r13
  JMP[NE] @mth_vrsqrt_test_fail
  CMP r9,r0
  JMP[NE] @mth_vrsqrt_test_fail
  MOVI r1,@mth_vrsqrt_test_out
  MOVI r2,@mth_vrsqrt_test_exp
  MOVI r4,32
  CALL @mth_vrsqrt_test_check_ulp

  ; ---- Phase 6: maximum finite input.
  MOVI r1,@mth_vrsqrt_test_x
  MOVI r2,0xFFFF
  MOVHI r2,0x7F7F            ; FLT_MAX
  CALL @mth_vrsqrt_test_fill_const
  MOVI r1,@mth_vrsqrt_test_exp
  MOVI r2,0
  MOVHI r2,0x1F80            ; 0x1F800000 = rsqrt(FLT_MAX)
  CALL @mth_vrsqrt_test_fill_const
  CALL @mth_vrsqrt_test_call
  CMP r1,r13
  JMP[NE] @mth_vrsqrt_test_fail
  CMP r9,r0
  JMP[NE] @mth_vrsqrt_test_fail
  MOVI r1,@mth_vrsqrt_test_out
  MOVI r2,@mth_vrsqrt_test_exp
  MOVI r4,32
  CALL @mth_vrsqrt_test_check_ulp

  ; ---- Phase 7: exact out == x aliasing.
  MOVI r1,@mth_vrsqrt_test_x
  MOVI r2,@mth_vrsqrt_test_exp
  CALL @mth_vrsqrt_test_fill_squares
  MOVI r1,@mth_vrsqrt_test_x
  MOVI r2,@mth_vrsqrt_test_x
  CALL @mth_vector_rsqrt256_f32
  CMP r1,r13
  JMP[NE] @mth_vrsqrt_test_fail
  CMP r9,r0
  JMP[NE] @mth_vrsqrt_test_fail
  MOVI r1,@mth_vrsqrt_test_x
  MOVI r2,@mth_vrsqrt_test_exp
  MOVI r4,32
  CALL @mth_vrsqrt_test_check_ulp

  ; ---- Phase 8: +0.0 rejects with cause 2.
  MOVI r1,@mth_vrsqrt_test_x
  MOVI r2,0
  MOVHI r2,0x3F80            ; base 1.0
  CALL @mth_vrsqrt_test_fill_const
  MOVI r1,@mth_vrsqrt_test_x
  MOVI r2,0
  MOVI r3,0                  ; +0.0
  CALL @mth_vrsqrt_test_set_one
  CALL @mth_vrsqrt_test_sentinel
  CALL @mth_vrsqrt_test_call
  MOVI r5,2
  CALL @mth_vrsqrt_test_check_failure

  ; ---- Phase 9: -0.0 rejects with cause 2.
  MOVI r1,@mth_vrsqrt_test_x
  MOVI r2,0
  MOVHI r2,0x3F80
  CALL @mth_vrsqrt_test_fill_const
  MOVI r1,@mth_vrsqrt_test_x
  MOVI r2,1
  MOVI r3,0
  MOVHI r3,0x8000            ; -0.0
  CALL @mth_vrsqrt_test_set_one
  CALL @mth_vrsqrt_test_sentinel
  CALL @mth_vrsqrt_test_call
  MOVI r5,2
  CALL @mth_vrsqrt_test_check_failure

  ; ---- Phase 10: finite negative rejects with cause 2.
  MOVI r1,@mth_vrsqrt_test_x
  MOVI r2,0
  MOVHI r2,0x3F80
  CALL @mth_vrsqrt_test_fill_const
  MOVI r1,@mth_vrsqrt_test_x
  MOVI r2,2
  MOVI r3,0
  MOVHI r3,0xC080            ; -4.0
  CALL @mth_vrsqrt_test_set_one
  CALL @mth_vrsqrt_test_sentinel
  CALL @mth_vrsqrt_test_call
  MOVI r5,2
  CALL @mth_vrsqrt_test_check_failure

  ; ---- Phase 11: quiet NaN rejects with cause 1.
  MOVI r1,@mth_vrsqrt_test_x
  MOVI r2,0
  MOVHI r2,0x3F80
  CALL @mth_vrsqrt_test_fill_const
  MOVI r1,@mth_vrsqrt_test_x
  MOVI r2,100
  MOVI r3,0x0123
  MOVHI r3,0x7FC0            ; quiet NaN
  CALL @mth_vrsqrt_test_set_one
  CALL @mth_vrsqrt_test_sentinel
  CALL @mth_vrsqrt_test_call
  MOVI r5,1
  CALL @mth_vrsqrt_test_check_failure

  ; ---- Phase 12: +inf rejects with cause 1.
  MOVI r1,@mth_vrsqrt_test_x
  MOVI r2,0
  MOVHI r2,0x3F80
  CALL @mth_vrsqrt_test_fill_const
  MOVI r1,@mth_vrsqrt_test_x
  MOVI r2,4
  MOVI r3,0
  MOVHI r3,0x7F80            ; +inf
  CALL @mth_vrsqrt_test_set_one
  CALL @mth_vrsqrt_test_sentinel
  CALL @mth_vrsqrt_test_call
  MOVI r5,1
  CALL @mth_vrsqrt_test_check_failure

  ; ---- Phase 13: -inf rejects with cause 1 (non-finite before sign).
  MOVI r1,@mth_vrsqrt_test_x
  MOVI r2,0
  MOVHI r2,0x3F80
  CALL @mth_vrsqrt_test_fill_const
  MOVI r1,@mth_vrsqrt_test_x
  MOVI r2,200
  MOVI r3,0
  MOVHI r3,0xFF80            ; -inf
  CALL @mth_vrsqrt_test_set_one
  CALL @mth_vrsqrt_test_sentinel
  CALL @mth_vrsqrt_test_call
  MOVI r5,1
  CALL @mth_vrsqrt_test_check_failure

  ; ---- Phase 14: recovery after rejection.
  MOVI r1,@mth_vrsqrt_test_x
  MOVI r2,@mth_vrsqrt_test_exp
  CALL @mth_vrsqrt_test_fill_squares
  CALL @mth_vrsqrt_test_call
  CMP r1,r13
  JMP[NE] @mth_vrsqrt_test_fail
  CMP r9,r0
  JMP[NE] @mth_vrsqrt_test_fail
  MOVI r1,@mth_vrsqrt_test_out
  MOVI r2,@mth_vrsqrt_test_exp
  MOVI r4,32
  CALL @mth_vrsqrt_test_check_ulp

  MOVI r1,@mth_vrsqrt_test_pass
  CALL @mth_vrsqrt_test_puts
  HALT

mth_vrsqrt_test_fail:
  MOVI r1,@mth_vrsqrt_test_bad
  CALL @mth_vrsqrt_test_puts
  HALT

; Call the kernel on the fixture x/out spans. Preserves the caller link in
; r14 (the kernel preserves r14). Returns the kernel status in r1/r9.
mth_vrsqrt_test_call:
  ADD r14,r15,r0
  MOVI r1,@mth_vrsqrt_test_x
  MOVI r2,@mth_vrsqrt_test_out
  CALL @mth_vector_rsqrt256_f32
  ADD r15,r14,r0
  RET

; r1 = x base, r2 = expected base. Fills x[i] = (i+1)^2 and
; exp[i] = 1.0/(i+1) with one FDIV per element. Clobbers r3-r9.
mth_vrsqrt_test_fill_squares:
  MOVI r3,0
  MOVI r4,1
  MOVI r9,0
  MOVHI r9,0x3F80            ; 1.0
mth_vrsqrt_test_fill_squares_loop:
  CVTIF r5,r4
  FMUL r6,r5,r5
  ADD r7,r1,r3
  ST r6,r7,0
  FDIV r6,r9,r5
  ADD r7,r2,r3
  ST r6,r7,0
  ADD r3,r3,r13
  ADD r4,r4,r13
  MOVI r7,256
  CMP r3,r7
  JMP[LT] @mth_vrsqrt_test_fill_squares_loop
  RET

; r1 = x base, r2 = expected base, r11 = mode.
; mode 0: x = 2^(2k), expected = 2^(-k). mode 1: x = 2^(-2k), expected = 2^k.
; k = i mod 64. Clobbers r3-r8.
mth_vrsqrt_test_fill_pow2:
  MOVI r3,0
  MOVI r4,63
  MOVI r5,127
mth_vrsqrt_test_fill_pow2_loop:
  BOOL.8 r6,r3,r4
  CMP r11,r0
  JMP[NE] @mth_vrsqrt_test_fill_pow2_neg
  SHL r7,r6,1
  ADD r7,r5,r7
  SHL r7,r7,23
  SUB r8,r5,r6
  SHL r8,r8,23
  JMP @mth_vrsqrt_test_fill_pow2_store
mth_vrsqrt_test_fill_pow2_neg:
  SHL r7,r6,1
  SUB r7,r5,r7
  SHL r7,r7,23
  ADD r8,r5,r6
  SHL r8,r8,23
mth_vrsqrt_test_fill_pow2_store:
  ADD r6,r1,r3
  ST r7,r6,0
  ADD r6,r2,r3
  ST r8,r6,0
  ADD r3,r3,r13
  MOVI r7,256
  CMP r3,r7
  JMP[LT] @mth_vrsqrt_test_fill_pow2_loop
  RET

; r1 = destination, r2 = payload. Fills 256 words. Clobbers r3-r4.
mth_vrsqrt_test_fill_const:
  MOVI r3,0
mth_vrsqrt_test_fill_const_loop:
  ADD r4,r1,r3
  ST r2,r4,0
  ADD r3,r3,r13
  MOVI r4,256
  CMP r3,r4
  JMP[LT] @mth_vrsqrt_test_fill_const_loop
  RET

; r1 = base, r2 = index, r3 = payload. Clobbers r4.
mth_vrsqrt_test_set_one:
  ADD r4,r1,r2
  ST r3,r4,0
  RET

; r1 = actual base, r2 = expected base, r4 = maximum unsigned payload
; distance. Jumps to fail when any |actual-expected| > r4.
; Clobbers r5-r8.
mth_vrsqrt_test_check_ulp:
  MOVI r5,0
mth_vrsqrt_test_check_ulp_loop:
  ADD r6,r1,r5
  LD r6,r6,0
  ADD r7,r2,r5
  LD r7,r7,0
  CMP r6,r7
  JMP[LT] @mth_vrsqrt_test_check_ulp_below
  SUB r8,r6,r7
  JMP @mth_vrsqrt_test_check_ulp_cmp
mth_vrsqrt_test_check_ulp_below:
  SUB r8,r7,r6
mth_vrsqrt_test_check_ulp_cmp:
  CMP r8,r4
  JMP[GT] @mth_vrsqrt_test_fail
  ADD r5,r5,r13
  MOVI r8,256
  CMP r5,r8
  JMP[LT] @mth_vrsqrt_test_check_ulp_loop
  RET

; Fill out[0..255] with 0xDEADDEAD. Clobbers r6-r9.
mth_vrsqrt_test_sentinel:
  MOVI r6,@mth_vrsqrt_test_out
  MOVI r7,0xDEAD
  MOVHI r7,0xDEAD
  MOVI r8,0
mth_vrsqrt_test_sentinel_loop:
  ADD r9,r6,r8
  ST r7,r9,0
  ADD r8,r8,r13
  MOVI r9,256
  CMP r8,r9
  JMP[LT] @mth_vrsqrt_test_sentinel_loop
  RET

; r5 = expected cause. Requires r1 = 0, r9 = cause, and all 256 output
; words still 0xDEADDEAD. Clobbers r6-r9.
mth_vrsqrt_test_check_failure:
  CMP r1,r0
  JMP[NE] @mth_vrsqrt_test_fail
  CMP r9,r5
  JMP[NE] @mth_vrsqrt_test_fail
  MOVI r6,@mth_vrsqrt_test_out
  MOVI r7,0
  MOVI r8,0xDEAD
  MOVHI r8,0xDEAD
mth_vrsqrt_test_check_failure_loop:
  ADD r9,r6,r7
  LD r9,r9,0
  CMP r9,r8
  JMP[NE] @mth_vrsqrt_test_fail
  ADD r7,r7,r13
  MOVI r9,256
  CMP r7,r9
  JMP[LT] @mth_vrsqrt_test_check_failure_loop
  RET

mth_vrsqrt_test_puts:
  MOVI r4,255
mth_vrsqrt_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_vrsqrt_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_vrsqrt_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_vrsqrt_test_puts_word

.org 1024
mth_vrsqrt_test_x:
.word 0
.org 2048
mth_vrsqrt_test_out:
.word 0
.org 3072
mth_vrsqrt_test_exp:
.word 0

.org 8192
mth_vrsqrt_test_pass:
.str "MTH VECTOR RSQRT256 F32 PASS\n"
mth_vrsqrt_test_bad:
.str "MTH VECTOR RSQRT256 F32 FAIL\n"
