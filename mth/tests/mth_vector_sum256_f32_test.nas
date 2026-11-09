; MTH vector sum256 float32 fixture — NaN16 only.
;
; All 256 input words are generated in the guest at run time by fill helpers;
; expected results are literal IEEE binary32 payload constants. Every check
; is a native integer CMP of 32-bit words.
;
; Success phases:
;   1. all 2.0 -> 512.0.
;   2. x[i] = (float32)i -> 32640.0 (exact increasing-order integer sum).
;   3. all -0.0 -> +0.0 (the accumulator starts at +0.0).
;   4. (+1.0) + (-1.0) with zeros elsewhere -> +0.0.
;   5. boundary cancellation: +FLT_MAX + (-FLT_MAX) + min positive
;      subnormal -> 0x00000001; then the subnormal is negated -> 0x80000001.
;   6. all 256 inputs = min positive subnormal 0x00000001 -> 0x00000100.
;   7. single +FLT_MAX input -> 0x7F7FFFFF.
;   8. single -FLT_MAX input -> 0xFF7FFFFF.
;
; Failure phases (each leaves out = 0xDEADDEAD):
;   9. signaling NaN at the last index.
;  10. negative quiet NaN at index 0.
;  11. +inf at index 42.
;  12. -inf at index 128.
;  13. recovery: the iota vector succeeds again after the rejections.

.org 0
JMP @mth_sum256_test_main
.include "../nan16/mth_vector_sum256_f32.nas"

mth_sum256_test_main:
  MOVI r13,1

  ; Phase 1: all 2.0 -> 512.0.
  MOVI r1,0
  MOVHI r1,0x4000            ; 2.0
  CALL @mth_sum256_test_fill_value
  CALL @mth_sum256_test_call
  CMP r1,r13
  JMP[NE] @mth_sum256_test_fail
  MOVI r1,0
  MOVHI r1,0x4400            ; 512.0
  CALL @mth_sum256_test_check_value

  ; Phase 2: x[i] = (float32)i, sum = 32640.0.
  CALL @mth_sum256_test_fill_iota
  CALL @mth_sum256_test_call
  CMP r1,r13
  JMP[NE] @mth_sum256_test_fail
  MOVI r1,0
  MOVHI r1,0x46FF            ; 32640.0
  CALL @mth_sum256_test_check_value

  ; Phase 3: all -0.0 -> +0.0.
  MOVI r1,0
  MOVHI r1,0x8000            ; -0.0
  CALL @mth_sum256_test_fill_value
  CALL @mth_sum256_test_call
  CMP r1,r13
  JMP[NE] @mth_sum256_test_fail
  MOVI r1,0                  ; +0.0
  CALL @mth_sum256_test_check_value

  ; Phase 4: +1.0 then -1.0 -> +0.0.
  MOVI r1,0
  CALL @mth_sum256_test_fill_value
  LA r5,@mth_sum256_test_x
  MOVI r6,0
  MOVHI r6,0x3F80            ; +1.0
  ST r6,r5,0
  MOVI r6,0
  MOVHI r6,0xBF80            ; -1.0
  ST r6,r5,1
  CALL @mth_sum256_test_call
  CMP r1,r13
  JMP[NE] @mth_sum256_test_fail
  MOVI r1,0                  ; +0.0
  CALL @mth_sum256_test_check_value

  ; Phase 5: +FLT_MAX, -FLT_MAX, min positive subnormal -> 0x00000001.
  MOVI r1,0
  CALL @mth_sum256_test_fill_value
  LA r5,@mth_sum256_test_x
  MOVI r6,0xFFFF
  MOVHI r6,0x7F7F            ; +FLT_MAX 0x7F7FFFFF
  ST r6,r5,0
  MOVI r6,0xFFFF
  MOVHI r6,0xFF7F            ; -FLT_MAX 0xFF7FFFFF
  ST r6,r5,1
  MOVI r6,1                  ; min positive subnormal
  ST r6,r5,2
  CALL @mth_sum256_test_call
  CMP r1,r13
  JMP[NE] @mth_sum256_test_fail
  MOVI r1,1                  ; 0x00000001
  CALL @mth_sum256_test_check_value

  ; Phase 5b: same boundary terms with the min negative subnormal.
  LA r5,@mth_sum256_test_x
  MOVI r6,1
  MOVHI r6,0x8000            ; 0x80000001
  ST r6,r5,2
  CALL @mth_sum256_test_call
  CMP r1,r13
  JMP[NE] @mth_sum256_test_fail
  MOVI r1,1
  MOVHI r1,0x8000            ; -min subnormal
  CALL @mth_sum256_test_check_value

  ; Phase 6: 256 copies of the min positive subnormal -> 0x00000100.
  MOVI r1,1
  CALL @mth_sum256_test_fill_value
  CALL @mth_sum256_test_call
  CMP r1,r13
  JMP[NE] @mth_sum256_test_fail
  MOVI r1,0x0100             ; 256 * 2^-149 = 2^-141
  CALL @mth_sum256_test_check_value

  ; Phase 7: a single +FLT_MAX input is returned exactly.
  MOVI r1,0
  CALL @mth_sum256_test_fill_value
  LA r5,@mth_sum256_test_x
  MOVI r6,0xFFFF
  MOVHI r6,0x7F7F            ; +FLT_MAX
  ST r6,r5,0
  CALL @mth_sum256_test_call
  CMP r1,r13
  JMP[NE] @mth_sum256_test_fail
  MOVI r1,0xFFFF
  MOVHI r1,0x7F7F            ; +FLT_MAX
  CALL @mth_sum256_test_check_value

  ; Phase 8: a single -FLT_MAX input is returned exactly.
  MOVI r1,0
  CALL @mth_sum256_test_fill_value
  LA r5,@mth_sum256_test_x
  MOVI r6,0xFFFF
  MOVHI r6,0xFF7F            ; -FLT_MAX
  ST r6,r5,0
  CALL @mth_sum256_test_call
  CMP r1,r13
  JMP[NE] @mth_sum256_test_fail
  MOVI r1,0xFFFF
  MOVHI r1,0xFF7F            ; -FLT_MAX
  CALL @mth_sum256_test_check_value

  ; Phase 9: signaling NaN at the last index. Reject atomically.
  CALL @mth_sum256_test_fill_iota
  CALL @mth_sum256_test_fill_sentinel
  LA r5,@mth_sum256_test_x
  MOVI r6,1
  MOVHI r6,0x7F80            ; 0x7F800001 sNaN
  ST r6,r5,255
  CALL @mth_sum256_test_call
  CMP r1,r0
  JMP[NE] @mth_sum256_test_fail
  CALL @mth_sum256_test_check_sentinel

  ; Phase 10: negative quiet NaN at index 0. Reject atomically.
  CALL @mth_sum256_test_fill_iota
  CALL @mth_sum256_test_fill_sentinel
  LA r5,@mth_sum256_test_x
  MOVI r6,0
  MOVHI r6,0xFFC0            ; 0xFFC00000 qNaN
  ST r6,r5,0
  CALL @mth_sum256_test_call
  CMP r1,r0
  JMP[NE] @mth_sum256_test_fail
  CALL @mth_sum256_test_check_sentinel

  ; Phase 11: +inf at index 42. Reject atomically.
  CALL @mth_sum256_test_fill_iota
  CALL @mth_sum256_test_fill_sentinel
  LA r5,@mth_sum256_test_x
  MOVI r6,0
  MOVHI r6,0x7F80            ; +inf
  ST r6,r5,42
  CALL @mth_sum256_test_call
  CMP r1,r0
  JMP[NE] @mth_sum256_test_fail
  CALL @mth_sum256_test_check_sentinel

  ; Phase 12: -inf at index 128. Reject atomically.
  CALL @mth_sum256_test_fill_iota
  CALL @mth_sum256_test_fill_sentinel
  LA r5,@mth_sum256_test_x
  MOVI r6,0
  MOVHI r6,0xFF80            ; -inf
  ST r6,r5,128
  CALL @mth_sum256_test_call
  CMP r1,r0
  JMP[NE] @mth_sum256_test_fail
  CALL @mth_sum256_test_check_sentinel

  ; Phase 13: recovery after rejection.
  CALL @mth_sum256_test_fill_iota
  CALL @mth_sum256_test_call
  CMP r1,r13
  JMP[NE] @mth_sum256_test_fail
  MOVI r1,0
  MOVHI r1,0x46FF            ; 32640.0
  CALL @mth_sum256_test_check_value

  LA r1,@mth_sum256_test_pass
  CALL @mth_sum256_test_puts
  HALT

mth_sum256_test_fail:
  LA r1,@mth_sum256_test_bad
  CALL @mth_sum256_test_puts
  HALT

; Call the sum kernel on the fixture x/out spans and return its r1 status.
; Saves and restores the link register through r14; the kernel preserves r14.
; Clobbers r1-r2, r14 and the flags.
mth_sum256_test_call:
  ADD r14,r15,r0
  LA r1,@mth_sum256_test_x
  LA r2,@mth_sum256_test_out
  CALL @mth_vector_sum256_f32
  ADD r15,r14,r0
  RET

; r1 = expected output payload. Jumps to the fail label on mismatch.
; Clobbers r4-r5 and the flags.
mth_sum256_test_check_value:
  LA r4,@mth_sum256_test_out
  LD r5,r4,0
  CMP r5,r1
  JMP[NE] @mth_sum256_test_fail
  RET

; Fill x[0..255] with the payload in r1. Preserves r1; clobbers r2-r4.
mth_sum256_test_fill_value:
  LA r2,@mth_sum256_test_x
  MOVI r3,0
  MOVI r4,256
mth_sum256_test_fill_value_loop:
  ST r1,r2,0
  ADD r2,r2,r13
  ADD r3,r3,r13
  CMP r3,r4
  JMP[LT] @mth_sum256_test_fill_value_loop
  RET

; Fill x[i] = (float32)i for i=0..255. Clobbers r1-r4.
mth_sum256_test_fill_iota:
  LA r1,@mth_sum256_test_x
  MOVI r2,0
mth_sum256_test_fill_iota_loop:
  CVTIF r4,r2
  ST r4,r1,0
  ADD r1,r1,r13
  ADD r2,r2,r13
  MOVI r3,256
  CMP r2,r3
  JMP[LT] @mth_sum256_test_fill_iota_loop
  RET

; Set out = 0xDEADDEAD. Clobbers r5-r6.
mth_sum256_test_fill_sentinel:
  MOVI r5,0xDEAD
  MOVHI r5,0xDEAD
  LA r6,@mth_sum256_test_out
  ST r5,r6,0
  RET

; Require out to remain 0xDEADDEAD. Clobbers r5-r7.
mth_sum256_test_check_sentinel:
  MOVI r5,0xDEAD
  MOVHI r5,0xDEAD
  LA r6,@mth_sum256_test_out
  LD r7,r6,0
  CMP r7,r5
  JMP[NE] @mth_sum256_test_fail
  RET

mth_sum256_test_puts:
  MOVI r4,255
mth_sum256_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_sum256_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_sum256_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_sum256_test_puts_word

.org 1024
mth_sum256_test_x:
.word 0
.org 2048
mth_sum256_test_out:
.word 0xDEADBEEF
.org 2560
mth_sum256_test_pass:
.str "MTH VECTOR SUM256 F32 PASS\n"
mth_sum256_test_bad:
.str "MTH VECTOR SUM256 F32 FAIL\n"
