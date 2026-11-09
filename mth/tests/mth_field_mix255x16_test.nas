; MTH 255-head field mixture fixture — NaN16 only.
;
; All 255 rows have value 1; row 1 has value 3. Checks one-hot, two-head,
; uniform, negative weight, non-finite vector, output atomicity, recovery.

.org 0
JMP @mth_field_test_main
.include "../nan16/mth_field_mix255x16_f32.nas"

mth_field_test_main:
  MOVI r0,0
  MOVI r13,1
  CALL @mth_field_test_init

  ; one-hot head 1 -> 3
  MOVI r8,@mth_field_test_weights
  ADDI r8,r8,1
  MOVI r7,0
  MOVHI r7,0x3F80
  ST r7,r8,0
  CALL @mth_field_test_run
  MOVI r1,0
  MOVHI r1,0x4040            ; 3
  CALL @mth_field_test_expect

  ; heads 1 and 2, 0.5 each -> 2
  CALL @mth_field_test_zero_weights
  MOVI r8,@mth_field_test_weights
  MOVI r7,0
  MOVHI r7,0x3F00
  ST r7,r8,0
  ADDI r8,r8,1
  ST r7,r8,0
  CALL @mth_field_test_run
  MOVI r1,0
  MOVHI r1,0x4000            ; 2
  CALL @mth_field_test_expect

  ; uniform 1/255 -> 257/255
  CALL @mth_field_test_zero_weights
  MOVI r6,0
mth_field_test_uniform_fill:
  MOVI r8,@mth_field_test_weights
  ADD r8,r8,r6
  MOVI r7,0x8081
  MOVHI r7,0x3B80            ; 1/255
  ST r7,r8,0
  ADDI r6,r6,1
  MOVI r8,255
  CMP r6,r8
  JMP[LT] @mth_field_test_uniform_fill
  CALL @mth_field_test_run
  MOVI r1,0x0101
  MOVHI r1,0x3F81            ; 257/255
  CALL @mth_field_test_expect

  ; negative weight rejects
  CALL @mth_field_test_init
  CALL @mth_field_test_sentinel
  MOVI r8,@mth_field_test_weights
  MOVI r7,0
  MOVHI r7,0xBF80
  ST r7,r8,0
  CALL @mth_field_test_call
  CMP r1,r0
  JMP[NE] @mth_field_test_fail
  MOVI r8,1
  CMP r9,r8
  JMP[NE] @mth_field_test_fail
  CALL @mth_field_test_check_sentinel

  ; NaN vector rejects cause 2
  CALL @mth_field_test_init
  CALL @mth_field_test_sentinel
  MOVI r1,0
  MOVHI r1,0x7FC0
  ST r1,r0,@mth_field_test_vectors
  CALL @mth_field_test_call
  CMP r1,r0
  JMP[NE] @mth_field_test_fail
  MOVI r8,2
  CMP r9,r8
  JMP[NE] @mth_field_test_fail
  CALL @mth_field_test_check_sentinel

  ; recovery
  CALL @mth_field_test_init
  MOVI r8,@mth_field_test_weights
  ADDI r8,r8,1
  MOVI r7,0
  MOVHI r7,0x3F80
  ST r7,r8,0
  CALL @mth_field_test_run
  MOVI r1,0
  MOVHI r1,0x4040
  CALL @mth_field_test_expect

  MOVI r1,@mth_field_test_pass
  CALL @mth_field_test_puts
  HALT

mth_field_test_init:
  MOVI r6,0
mth_field_test_w_zero:
  MOVI r8,@mth_field_test_weights
  ADD r8,r8,r6
  ST r0,r8,0
  ADDI r6,r6,1
  MOVI r8,255
  CMP r6,r8
  JMP[LT] @mth_field_test_w_zero

  MOVI r6,0
  MOVI r7,0
  MOVHI r7,0x3F80
mth_field_test_v_fill:
  MOVI r8,@mth_field_test_vectors
  ADD r8,r8,r6
  ST r7,r8,0
  ADDI r6,r6,1
  MOVI r8,4080
  CMP r6,r8
  JMP[LT] @mth_field_test_v_fill

  ; row 1 = 3
  MOVI r6,0
  MOVI r7,0
  MOVHI r7,0x4040
mth_field_test_v_row1:
  MOVI r8,@mth_field_test_vectors
  ADDI r8,r8,16
  ADD r8,r8,r6
  ST r7,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_field_test_v_row1

  MOVI r6,0
mth_field_test_scratch_zero:
  MOVI r8,@mth_field_test_scratch
  ADD r8,r8,r6
  ST r0,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_field_test_scratch_zero
  RET

mth_field_test_zero_weights:
  MOVI r6,0
mth_field_test_zw:
  MOVI r8,@mth_field_test_weights
  ADD r8,r8,r6
  ST r0,r8,0
  ADDI r6,r6,1
  MOVI r8,255
  CMP r6,r8
  JMP[LT] @mth_field_test_zw
  RET

mth_field_test_call:
  ST r15,r0,@mth_field_test_call_ret
  MOVI r1,@mth_field_test_weights
  MOVI r2,@mth_field_test_vectors
  MOVI r3,@mth_field_test_out
  MOVI r4,@mth_field_test_scratch
  CALL @mth_field_mix255x16_f32
  LD r15,r0,@mth_field_test_call_ret
  RET

mth_field_test_run:
  ST r15,r0,@mth_field_test_run_ret
  CALL @mth_field_test_call
  CMP r1,r13
  JMP[NE] @mth_field_test_fail
  CMP r9,r0
  JMP[NE] @mth_field_test_fail
  LD r15,r0,@mth_field_test_run_ret
  RET

mth_field_test_expect:
  ST r15,r0,@mth_field_test_expect_ret
  MOVI r8,@mth_field_test_expected
  ST r1,r8,0
  MOVI r8,@mth_field_test_out
  LD r2,r8,0
  LD r1,r0,@mth_field_test_expected
  MOVI r3,0
  MOVHI r3,0x3727            ; 1e-4
  CALL @mth_field_test_near
  CMP r1,r13
  JMP[NE] @mth_field_test_fail
  MOVI r8,@mth_field_test_out
  ADDI r8,r8,15
  LD r2,r8,0
  LD r1,r0,@mth_field_test_expected
  MOVI r3,0
  MOVHI r3,0x3727
  CALL @mth_field_test_near
  CMP r1,r13
  JMP[NE] @mth_field_test_fail
  LD r15,r0,@mth_field_test_expect_ret
  RET

mth_field_test_sentinel:
  MOVI r1,0xBEEF
  MOVHI r1,0xDEAD
  ST r1,r0,@mth_field_test_out
  RET

mth_field_test_check_sentinel:
  LD r1,r0,@mth_field_test_out
  MOVI r2,0xBEEF
  MOVHI r2,0xDEAD
  CMP r1,r2
  JMP[NE] @mth_field_test_fail
  RET

mth_field_test_near:
  MOVI r4,0
  MOVHI r4,0x7FFF
  FSUB r5,r1,r2
  BOOL.8 r5,r5,r4
  FCMP r5,r3
  JMP[GT] @mth_field_test_near_fail
  MOVI r1,1
  RET
mth_field_test_near_fail:
  MOVI r1,0
  RET

mth_field_test_fail:
  MOVI r1,@mth_field_test_bad
  CALL @mth_field_test_puts
  HALT

mth_field_test_puts:
  MOVI r4,255
mth_field_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_field_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_field_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_field_test_puts_word

mth_field_test_pass:
.str "MTH FIELD MIX255X16 PASS\n"
mth_field_test_bad:
.str "MTH FIELD MIX255X16 FAIL\n"

.org 4096
mth_field_test_weights:
.word 0
.org 4352
mth_field_test_vectors:
.word 0
.org 8448
mth_field_test_out:
.word 0
.org 8464
mth_field_test_scratch:
.word 0
.org 8480
mth_field_test_call_ret:
.word 0
mth_field_test_run_ret:
.word 0
mth_field_test_expected:
.word 0
mth_field_test_expect_ret:
.word 0
