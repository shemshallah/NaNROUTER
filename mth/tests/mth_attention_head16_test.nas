; MTH single-head 16-key attention fixture — NaN16 only.
;
; K is the 16x16 identity. V row p has constant value p+1. Checks uniform
; attention, a peaked first-key distribution, non-finite operands, output
; atomicity, and recovery.

.org 0
JMP @mth_head_test_main
.include "../nan16/mth_attention_head16_f32.nas"

mth_head_test_main:
  MOVI r0,0
  MOVI r13,1
  CALL @mth_head_test_init

  ; uniform scores -> average of V rows = 8.5
  CALL @mth_head_test_run
  MOVI r1,0
  MOVHI r1,0x4108            ; 8.5
  MOVI r3,0
  MOVHI r3,0x3B03            ; 5e-3
  CALL @mth_head_test_expect

  ; q=1 at key 0 -> expected 7.7727
  MOVI r1,0
  MOVHI r1,0x3F80
  ST r1,r0,@mth_head_test_q
  CALL @mth_head_test_run
  MOVI r1,0xB9B0
  MOVHI r1,0x40F8            ; 7.7727
  MOVI r3,0
  MOVHI r3,0x3B03
  CALL @mth_head_test_expect

  ; q=10 at key 0 -> expected 1.00544
  MOVI r1,0
  MOVHI r1,0x4120            ; 10
  ST r1,r0,@mth_head_test_q
  CALL @mth_head_test_run
  MOVI r1,0xB266
  MOVHI r1,0x3F80            ; 1.00544
  MOVI r3,0
  MOVHI r3,0x3C23            ; 1e-2
  CALL @mth_head_test_expect

  ; NaN q rejects cause 1
  CALL @mth_head_test_init
  CALL @mth_head_test_sentinel
  MOVI r1,0
  MOVHI r1,0x7FC0
  ST r1,r0,@mth_head_test_q
  CALL @mth_head_test_call
  CMP r1,r0
  JMP[NE] @mth_head_test_fail
  MOVI r8,1
  CMP r9,r8
  JMP[NE] @mth_head_test_fail
  CALL @mth_head_test_check_sentinel

  ; NaN K rejects cause 2
  CALL @mth_head_test_init
  CALL @mth_head_test_sentinel
  MOVI r1,0
  MOVHI r1,0x7FC0
  ST r1,r0,@mth_head_test_k
  CALL @mth_head_test_call
  CMP r1,r0
  JMP[NE] @mth_head_test_fail
  MOVI r8,2
  CMP r9,r8
  JMP[NE] @mth_head_test_fail
  CALL @mth_head_test_check_sentinel

  ; NaN V rejects cause 3
  CALL @mth_head_test_init
  CALL @mth_head_test_sentinel
  MOVI r1,0
  MOVHI r1,0x7FC0
  ST r1,r0,@mth_head_test_v
  CALL @mth_head_test_call
  CMP r1,r0
  JMP[NE] @mth_head_test_fail
  MOVI r8,3
  CMP r9,r8
  JMP[NE] @mth_head_test_fail
  CALL @mth_head_test_check_sentinel

  ; recovery
  CALL @mth_head_test_init
  CALL @mth_head_test_run
  MOVI r1,0
  MOVHI r1,0x4108
  MOVI r3,0
  MOVHI r3,0x3B03
  CALL @mth_head_test_expect

  MOVI r1,@mth_head_test_pass
  CALL @mth_head_test_puts
  HALT

mth_head_test_init:
  MOVI r6,0
mth_head_test_init_loop:
  MOVI r8,@mth_head_test_q
  ADD r8,r8,r6
  ST r0,r8,0
  MOVI r8,@mth_head_test_out
  ADD r8,r8,r6
  ST r0,r8,0
  MOVI r8,@mth_head_test_v
  ADD r8,r8,r6
  ST r0,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_head_test_init_loop

  MOVI r6,0
mth_head_test_k_zero:
  MOVI r8,@mth_head_test_k
  ADD r8,r8,r6
  ST r0,r8,0
  ADDI r6,r6,1
  MOVI r8,256
  CMP r6,r8
  JMP[LT] @mth_head_test_k_zero
  MOVI r6,0
mth_head_test_k_diag:
  MOVI r8,@mth_head_test_k
  SHL r7,r6,4
  ADD r8,r8,r7
  ADD r8,r8,r6
  MOVI r7,0
  MOVHI r7,0x3F80
  ST r7,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_head_test_k_diag

  MOVI r6,0
mth_head_test_v_fill:
  CVTIF r1,r6
  MOVI r7,0
  MOVHI r7,0x3F80
  FADD r1,r1,r7
  MOVI r8,@mth_head_test_v
  SHL r7,r6,4
  ADD r8,r8,r7
  MOVI r7,0
mth_head_test_v_row:
  ADD r9,r8,r7
  ST r1,r9,0
  ADDI r7,r7,1
  MOVI r9,16
  CMP r7,r9
  JMP[LT] @mth_head_test_v_row
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_head_test_v_fill

  MOVI r6,0
mth_head_test_scratch_zero:
  MOVI r8,@mth_head_test_scratch
  ADD r8,r8,r6
  ST r0,r8,0
  ADDI r6,r6,1
  MOVI r8,277
  CMP r6,r8
  JMP[LT] @mth_head_test_scratch_zero
  RET

mth_head_test_call:
  ST r15,r0,@mth_head_test_call_ret
  MOVI r1,@mth_head_test_q
  MOVI r2,@mth_head_test_k
  MOVI r3,@mth_head_test_v
  MOVI r4,@mth_head_test_out
  MOVI r5,@mth_head_test_scratch
  CALL @mth_attention_head16_f32
  LD r15,r0,@mth_head_test_call_ret
  RET

mth_head_test_run:
  ST r15,r0,@mth_head_test_run_ret
  CALL @mth_head_test_call
  CMP r1,r13
  JMP[NE] @mth_head_test_fail
  CMP r9,r0
  JMP[NE] @mth_head_test_fail
  LD r15,r0,@mth_head_test_run_ret
  RET

; r1=expected, r3=tolerance; checks out[0] and out[15]
mth_head_test_expect:
  ST r15,r0,@mth_head_test_exp_ret
  ST r1,r0,@mth_head_test_expected
  ST r3,r0,@mth_head_test_tolerance
  LD r1,r0,@mth_head_test_out
  LD r2,r0,@mth_head_test_expected
  LD r3,r0,@mth_head_test_tolerance
  CALL @mth_head_test_near
  CMP r1,r13
  JMP[NE] @mth_head_test_fail
  MOVI r8,@mth_head_test_out
  ADDI r8,r8,15
  LD r1,r8,0
  LD r2,r0,@mth_head_test_expected
  LD r3,r0,@mth_head_test_tolerance
  CALL @mth_head_test_near
  CMP r1,r13
  JMP[NE] @mth_head_test_fail
  LD r15,r0,@mth_head_test_exp_ret
  RET

mth_head_test_sentinel:
  MOVI r1,0xBEEF
  MOVHI r1,0xDEAD
  ST r1,r0,@mth_head_test_out
  RET

mth_head_test_check_sentinel:
  LD r1,r0,@mth_head_test_out
  MOVI r2,0xBEEF
  MOVHI r2,0xDEAD
  CMP r1,r2
  JMP[NE] @mth_head_test_fail
  RET

mth_head_test_near:
  MOVI r4,0
  MOVHI r4,0x7FFF
  FSUB r5,r1,r2
  BOOL.8 r5,r5,r4
  FCMP r5,r3
  JMP[GT] @mth_head_test_near_fail
  MOVI r1,1
  RET
mth_head_test_near_fail:
  MOVI r1,0
  RET

mth_head_test_fail:
  MOVI r1,@mth_head_test_bad
  CALL @mth_head_test_puts
  HALT

mth_head_test_puts:
  MOVI r4,255
mth_head_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_head_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_head_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_head_test_puts_word

mth_head_test_pass:
.str "MTH ATTENTION HEAD16 PASS\n"
mth_head_test_bad:
.str "MTH ATTENTION HEAD16 FAIL\n"

.org 4096
mth_head_test_call_ret:
.word 0
mth_head_test_run_ret:
.word 0
mth_head_test_exp_ret:
.word 0
mth_head_test_expected:
.word 0
mth_head_test_tolerance:
.word 0
mth_head_test_q:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_head_test_out:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_head_test_k:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_head_test_v:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_head_test_scratch:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
