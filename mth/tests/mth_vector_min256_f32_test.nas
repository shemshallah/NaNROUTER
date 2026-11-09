; MTH vector min256 float32 fixture — NaN16 only.
;
; All 256 input words are generated in the guest at run time by fill helpers;
; expected results are literal IEEE binary32 payload constants. Every check
; is a native integer CMP of 32-bit words.
;
; Success phases:
;   1. x[i] = (float32)(i - 128), minimum -128.0 at index 0.
;   2. minimum tie at indices 10, 77, 200 (-5.0); index 10 wins the tie.
;   3. positive minimum tie at 3, 8, 100 (2.0); index 3 wins the tie.
;   4. all elements 3.25 -> 3.25.
;   5. all elements -2.5 -> -2.5.
;   6. -0.0 first at index 3 and +0.0 at 100 -> the exact -0.0 payload wins.
;   7. +0.0 first at index 3 and -0.0 at 100 -> the exact +0.0 payload wins.
;   8. boundary: all +FLT_MAX, min positive subnormal at 0, -FLT_MAX at 255
;      -> -FLT_MAX 0xFF7FFFFF; all +FLT_MAX with min positive subnormal at
;      200 -> 0x00000001.
;
; Failure phases (each leaves out = 0xDEADDEAD):
;   9. signaling NaN at the last index.
;  10. negative quiet NaN at index 0.
;  11. +inf at index 42.
;  12. -inf at index 128.
;  13. recovery: the iota vector succeeds again after the rejections.

.org 0
JMP @mth_min256_test_main
.include "../nan16/mth_vector_min256_f32.nas"

mth_min256_test_main:
  MOVI r13,1

  ; Phase 1: distinct minimum at index 0, value -128.0.
  CALL @mth_min256_test_fill_iota
  CALL @mth_min256_test_call
  CMP r1,r13
  JMP[NE] @mth_min256_test_fail
  MOVI r1,0
  MOVHI r1,0xC300            ; -128.0
  CALL @mth_min256_test_check_value

  ; Phase 2: three-way minimum tie at 10, 77, 200; first index wins.
  MOVI r1,0
  MOVHI r1,0x3F80            ; 1.0 baseline
  CALL @mth_min256_test_fill_value
  LA r5,@mth_min256_test_x
  MOVI r6,0
  MOVHI r6,0xC0A0            ; -5.0
  ST r6,r5,10
  ST r6,r5,77
  ST r6,r5,200
  MOVI r6,0
  MOVHI r6,0xC080            ; -4.0, above the tie
  ST r6,r5,255
  CALL @mth_min256_test_call
  CMP r1,r13
  JMP[NE] @mth_min256_test_fail
  MOVI r1,0
  MOVHI r1,0xC0A0            ; -5.0
  CALL @mth_min256_test_check_value

  ; Phase 3: positive minimum tie at 3, 8, 100; first index wins.
  MOVI r1,0
  MOVHI r1,0x4110            ; 9.0 baseline
  CALL @mth_min256_test_fill_value
  LA r5,@mth_min256_test_x
  MOVI r6,0
  MOVHI r6,0x4000            ; 2.0
  ST r6,r5,3
  ST r6,r5,8
  ST r6,r5,100
  MOVI r6,0
  MOVHI r6,0x4040            ; 3.0, above the tie
  ST r6,r5,200
  CALL @mth_min256_test_call
  CMP r1,r13
  JMP[NE] @mth_min256_test_fail
  MOVI r1,0
  MOVHI r1,0x4000            ; 2.0
  CALL @mth_min256_test_check_value

  ; Phase 4: all elements 3.25; x[0] is the first minimum.
  MOVI r1,0
  MOVHI r1,0x4050            ; 3.25
  CALL @mth_min256_test_fill_value
  CALL @mth_min256_test_call
  CMP r1,r13
  JMP[NE] @mth_min256_test_fail
  MOVI r1,0
  MOVHI r1,0x4050            ; 3.25
  CALL @mth_min256_test_check_value

  ; Phase 5: all elements -2.5; x[0] is the first minimum.
  MOVI r1,0
  MOVHI r1,0xC020            ; -2.5
  CALL @mth_min256_test_fill_value
  CALL @mth_min256_test_call
  CMP r1,r13
  JMP[NE] @mth_min256_test_fail
  MOVI r1,0
  MOVHI r1,0xC020            ; -2.5
  CALL @mth_min256_test_check_value

  ; Phase 6: +1.0 baseline, -0.0 at 3 and +0.0 at 100. The zeros are equal
  ; and less than +1.0, so the first zero wins and its -0.0 payload is
  ; returned.
  MOVI r1,0
  MOVHI r1,0x3F80            ; +1.0 baseline
  CALL @mth_min256_test_fill_value
  LA r5,@mth_min256_test_x
  MOVI r6,0
  MOVHI r6,0x8000            ; -0.0
  ST r6,r5,3
  ST r0,r5,100               ; +0.0
  CALL @mth_min256_test_call
  CMP r1,r13
  JMP[NE] @mth_min256_test_fail
  MOVI r1,0
  MOVHI r1,0x8000            ; -0.0
  CALL @mth_min256_test_check_value

  ; Phase 7: swap the zero signs. +0.0 at 3 is the first zero and wins; its
  ; +0.0 payload is returned.
  LA r5,@mth_min256_test_x
  ST r0,r5,3                 ; +0.0
  MOVI r6,0
  MOVHI r6,0x8000            ; -0.0
  ST r6,r5,100
  CALL @mth_min256_test_call
  CMP r1,r13
  JMP[NE] @mth_min256_test_fail
  MOVI r1,0                  ; +0.0
  CALL @mth_min256_test_check_value

  ; Phase 8: boundary. All +FLT_MAX except min positive subnormal at 0 and
  ; -FLT_MAX at 255 -> -FLT_MAX.
  MOVI r1,0xFFFF
  MOVHI r1,0x7F7F            ; +FLT_MAX
  CALL @mth_min256_test_fill_value
  LA r5,@mth_min256_test_x
  MOVI r6,1                  ; min positive subnormal
  ST r6,r5,0
  MOVI r6,0xFFFF
  MOVHI r6,0xFF7F            ; -FLT_MAX
  ST r6,r5,255
  CALL @mth_min256_test_call
  CMP r1,r13
  JMP[NE] @mth_min256_test_fail
  MOVI r1,0xFFFF
  MOVHI r1,0xFF7F            ; -FLT_MAX
  CALL @mth_min256_test_check_value

  ; Phase 8b: all +FLT_MAX except min positive subnormal at 200 -> 0x1.
  MOVI r1,0xFFFF
  MOVHI r1,0x7F7F            ; +FLT_MAX
  CALL @mth_min256_test_fill_value
  LA r5,@mth_min256_test_x
  MOVI r6,1                  ; min positive subnormal
  ST r6,r5,200
  CALL @mth_min256_test_call
  CMP r1,r13
  JMP[NE] @mth_min256_test_fail
  MOVI r1,1                  ; 0x00000001
  CALL @mth_min256_test_check_value

  ; Phase 9: signaling NaN at the last index. Reject atomically.
  CALL @mth_min256_test_fill_iota
  CALL @mth_min256_test_fill_sentinel
  LA r5,@mth_min256_test_x
  MOVI r6,1
  MOVHI r6,0x7F80            ; 0x7F800001 sNaN
  ST r6,r5,255
  CALL @mth_min256_test_call
  CMP r1,r0
  JMP[NE] @mth_min256_test_fail
  CALL @mth_min256_test_check_sentinel

  ; Phase 10: negative quiet NaN at index 0. Reject atomically.
  CALL @mth_min256_test_fill_iota
  CALL @mth_min256_test_fill_sentinel
  LA r5,@mth_min256_test_x
  MOVI r6,0
  MOVHI r6,0xFFC0            ; 0xFFC00000 qNaN
  ST r6,r5,0
  CALL @mth_min256_test_call
  CMP r1,r0
  JMP[NE] @mth_min256_test_fail
  CALL @mth_min256_test_check_sentinel

  ; Phase 11: +inf at index 42. Reject atomically.
  CALL @mth_min256_test_fill_iota
  CALL @mth_min256_test_fill_sentinel
  LA r5,@mth_min256_test_x
  MOVI r6,0
  MOVHI r6,0x7F80            ; +inf
  ST r6,r5,42
  CALL @mth_min256_test_call
  CMP r1,r0
  JMP[NE] @mth_min256_test_fail
  CALL @mth_min256_test_check_sentinel

  ; Phase 12: -inf at index 128. Reject atomically.
  CALL @mth_min256_test_fill_iota
  CALL @mth_min256_test_fill_sentinel
  LA r5,@mth_min256_test_x
  MOVI r6,0
  MOVHI r6,0xFF80            ; -inf
  ST r6,r5,128
  CALL @mth_min256_test_call
  CMP r1,r0
  JMP[NE] @mth_min256_test_fail
  CALL @mth_min256_test_check_sentinel

  ; Phase 13: recovery after rejection.
  CALL @mth_min256_test_fill_iota
  CALL @mth_min256_test_call
  CMP r1,r13
  JMP[NE] @mth_min256_test_fail
  MOVI r1,0
  MOVHI r1,0xC300            ; -128.0
  CALL @mth_min256_test_check_value

  LA r1,@mth_min256_test_pass
  CALL @mth_min256_test_puts
  HALT

mth_min256_test_fail:
  LA r1,@mth_min256_test_bad
  CALL @mth_min256_test_puts
  HALT

; Call the min kernel on the fixture x/out spans and return its r1 status.
; Saves and restores the link register through r14; the kernel preserves r14.
; Clobbers r1-r2, r14 and the flags.
mth_min256_test_call:
  ADD r14,r15,r0
  LA r1,@mth_min256_test_x
  LA r2,@mth_min256_test_out
  CALL @mth_vector_min256_f32
  ADD r15,r14,r0
  RET

; r1 = expected output payload. Jumps to the fail label on mismatch.
; Clobbers r4-r5 and the flags.
mth_min256_test_check_value:
  LA r4,@mth_min256_test_out
  LD r5,r4,0
  CMP r5,r1
  JMP[NE] @mth_min256_test_fail
  RET

; Fill x[0..255] with the payload in r1. Preserves r1; clobbers r2-r4.
mth_min256_test_fill_value:
  LA r2,@mth_min256_test_x
  MOVI r3,0
  MOVI r4,256
mth_min256_test_fill_value_loop:
  ST r1,r2,0
  ADD r2,r2,r13
  ADD r3,r3,r13
  CMP r3,r4
  JMP[LT] @mth_min256_test_fill_value_loop
  RET

; Fill x[i] = (float32)(i - 128) for i=0..255. Clobbers r1-r4.
mth_min256_test_fill_iota:
  LA r1,@mth_min256_test_x
  MOVI r2,0
mth_min256_test_fill_iota_loop:
  MOVI r3,128
  SUB r4,r2,r3
  CVTIF r4,r4
  ST r4,r1,0
  ADD r1,r1,r13
  ADD r2,r2,r13
  MOVI r3,256
  CMP r2,r3
  JMP[LT] @mth_min256_test_fill_iota_loop
  RET

; Set out = 0xDEADDEAD. Clobbers r5-r6.
mth_min256_test_fill_sentinel:
  MOVI r5,0xDEAD
  MOVHI r5,0xDEAD
  LA r6,@mth_min256_test_out
  ST r5,r6,0
  RET

; Require out to remain 0xDEADDEAD. Clobbers r5-r7.
mth_min256_test_check_sentinel:
  MOVI r5,0xDEAD
  MOVHI r5,0xDEAD
  LA r6,@mth_min256_test_out
  LD r7,r6,0
  CMP r7,r5
  JMP[NE] @mth_min256_test_fail
  RET

mth_min256_test_puts:
  MOVI r4,255
mth_min256_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_min256_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_min256_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_min256_test_puts_word

.org 1024
mth_min256_test_x:
.word 0
.org 2048
mth_min256_test_out:
.word 0xDEADBEEF
.org 2560
mth_min256_test_pass:
.str "MTH VECTOR MIN256 F32 PASS\n"
mth_min256_test_bad:
.str "MTH VECTOR MIN256 F32 FAIL\n"
