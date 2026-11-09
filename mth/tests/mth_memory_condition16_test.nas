; MTH gated residual memory conditioning fixture — NaN16 only.
;
; h=2, m=4 constants. Checks gate 0, 0.5, 1, invalid gates, non-finite
; operands, overflow rejection, output atomicity, and recovery.

.org 0
JMP @mth_cond_test_main
.include "../nan16/mth_memory_condition16_f32.nas"

mth_cond_test_main:
  MOVI r0,0
  MOVI r13,1
  CALL @mth_cond_test_init

  ; gate 0 -> 2
  CALL @mth_cond_test_zero_gate
  CALL @mth_cond_test_run
  MOVI r1,0
  MOVHI r1,0x4000
  CALL @mth_cond_test_expect

  ; gate 0.5 -> 4
  CALL @mth_cond_test_half_gate
  CALL @mth_cond_test_run
  MOVI r1,0
  MOVHI r1,0x4080
  CALL @mth_cond_test_expect

  ; gate 1 -> 6
  CALL @mth_cond_test_one_gate
  CALL @mth_cond_test_run
  MOVI r1,0
  MOVHI r1,0x40C0
  CALL @mth_cond_test_expect

  ; negative gate
  CALL @mth_cond_test_sentinel
  MOVI r6,0
mth_cond_test_neg_fill:
  MOVI r8,@mth_cond_test_gate
  ADD r8,r8,r6
  MOVI r7,0
  MOVHI r7,0xBF80
  ST r7,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_cond_test_neg_fill
  CALL @mth_cond_test_call
  CMP r1,r0
  JMP[NE] @mth_cond_test_fail
  MOVI r8,4
  CMP r9,r8
  JMP[NE] @mth_cond_test_fail
  CALL @mth_cond_test_check_sentinel

  ; gate >1
  CALL @mth_cond_test_sentinel
  MOVI r6,0
mth_cond_test_big_fill:
  MOVI r8,@mth_cond_test_gate
  ADD r8,r8,r6
  MOVI r7,0
  MOVHI r7,0x3F8C
  ST r7,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_cond_test_big_fill
  CALL @mth_cond_test_call
  CMP r1,r0
  JMP[NE] @mth_cond_test_fail
  MOVI r8,4
  CMP r9,r8
  JMP[NE] @mth_cond_test_fail
  CALL @mth_cond_test_check_sentinel

  ; NaN hidden cause 1
  CALL @mth_cond_test_init
  CALL @mth_cond_test_one_gate
  CALL @mth_cond_test_sentinel
  MOVI r1,0
  MOVHI r1,0x7FC0
  ST r1,r0,@mth_cond_test_h
  CALL @mth_cond_test_call
  CMP r1,r0
  JMP[NE] @mth_cond_test_fail
  MOVI r8,1
  CMP r9,r8
  JMP[NE] @mth_cond_test_fail
  CALL @mth_cond_test_check_sentinel

  ; NaN memory cause 2
  CALL @mth_cond_test_init
  CALL @mth_cond_test_one_gate
  CALL @mth_cond_test_sentinel
  MOVI r1,0
  MOVHI r1,0x7FC0
  ST r1,r0,@mth_cond_test_m
  CALL @mth_cond_test_call
  CMP r1,r0
  JMP[NE] @mth_cond_test_fail
  MOVI r8,2
  CMP r9,r8
  JMP[NE] @mth_cond_test_fail
  CALL @mth_cond_test_check_sentinel

  ; overflow cause 5
  CALL @mth_cond_test_init
  CALL @mth_cond_test_one_gate
  CALL @mth_cond_test_sentinel
  MOVI r1,0xFFFF
  MOVHI r1,0x7F7F
  ST r1,r0,@mth_cond_test_h
  ST r1,r0,@mth_cond_test_m
  CALL @mth_cond_test_call
  CMP r1,r0
  JMP[NE] @mth_cond_test_fail
  MOVI r8,5
  CMP r9,r8
  JMP[NE] @mth_cond_test_fail
  CALL @mth_cond_test_check_sentinel

  ; recovery
  CALL @mth_cond_test_init
  CALL @mth_cond_test_quarter_gate
  CALL @mth_cond_test_run
  MOVI r1,0
  MOVHI r1,0x4040            ; 3
  CALL @mth_cond_test_expect

  MOVI r1,@mth_cond_test_pass
  CALL @mth_cond_test_puts
  HALT

mth_cond_test_init:
  MOVI r6,0
mth_cond_test_init_loop:
  MOVI r1,0
  MOVHI r1,0x4000            ; h=2
  MOVI r8,@mth_cond_test_h
  ADD r8,r8,r6
  ST r1,r8,0
  MOVI r1,0
  MOVHI r1,0x4080            ; m=4
  MOVI r8,@mth_cond_test_m
  ADD r8,r8,r6
  ST r1,r8,0
  MOVI r8,@mth_cond_test_out
  ADD r8,r8,r6
  ST r0,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_cond_test_init_loop
  RET

mth_cond_test_zero_gate:
  MOVI r6,0
mth_cond_test_zg:
  MOVI r8,@mth_cond_test_gate
  ADD r8,r8,r6
  ST r0,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_cond_test_zg
  RET

mth_cond_test_half_gate:
  MOVI r6,0
mth_cond_test_hg:
  MOVI r8,@mth_cond_test_gate
  ADD r8,r8,r6
  MOVI r7,0
  MOVHI r7,0x3F00
  ST r7,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_cond_test_hg
  RET

mth_cond_test_one_gate:
  MOVI r6,0
mth_cond_test_og:
  MOVI r8,@mth_cond_test_gate
  ADD r8,r8,r6
  MOVI r7,0
  MOVHI r7,0x3F80
  ST r7,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_cond_test_og
  RET

mth_cond_test_quarter_gate:
  MOVI r6,0
mth_cond_test_qg:
  MOVI r8,@mth_cond_test_gate
  ADD r8,r8,r6
  MOVI r7,0
  MOVHI r7,0x3E80
  ST r7,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_cond_test_qg
  RET

mth_cond_test_call:
  ST r15,r0,@mth_cond_test_call_ret
  MOVI r1,@mth_cond_test_h
  MOVI r2,@mth_cond_test_m
  MOVI r3,@mth_cond_test_gate
  MOVI r4,@mth_cond_test_out
  MOVI r5,@mth_cond_test_scratch
  CALL @mth_memory_condition16_f32
  LD r15,r0,@mth_cond_test_call_ret
  RET

mth_cond_test_run:
  ST r15,r0,@mth_cond_test_run_ret
  CALL @mth_cond_test_call
  CMP r1,r13
  JMP[NE] @mth_cond_test_fail
  CMP r9,r0
  JMP[NE] @mth_cond_test_fail
  LD r15,r0,@mth_cond_test_run_ret
  RET

mth_cond_test_expect:
  ST r15,r0,@mth_cond_test_expect_ret
  MOVI r8,@mth_cond_test_expected
  ST r1,r8,0
  MOVI r8,@mth_cond_test_out
  LD r2,r8,0
  LD r1,r0,@mth_cond_test_expected
  MOVI r3,0
  MOVHI r3,0x3586
  CALL @mth_cond_test_near
  CMP r1,r13
  JMP[NE] @mth_cond_test_fail
  MOVI r8,@mth_cond_test_out
  ADDI r8,r8,15
  LD r2,r8,0
  LD r1,r0,@mth_cond_test_expected
  MOVI r3,0
  MOVHI r3,0x3586
  CALL @mth_cond_test_near
  CMP r1,r13
  JMP[NE] @mth_cond_test_fail
  LD r15,r0,@mth_cond_test_expect_ret
  RET

mth_cond_test_sentinel:
  MOVI r1,0xBEEF
  MOVHI r1,0xDEAD
  ST r1,r0,@mth_cond_test_out
  RET

mth_cond_test_check_sentinel:
  LD r1,r0,@mth_cond_test_out
  MOVI r2,0xBEEF
  MOVHI r2,0xDEAD
  CMP r1,r2
  JMP[NE] @mth_cond_test_fail
  RET

mth_cond_test_near:
  MOVI r4,0
  MOVHI r4,0x7FFF
  FSUB r5,r1,r2
  BOOL.8 r5,r5,r4
  FCMP r5,r3
  JMP[GT] @mth_cond_test_near_fail
  MOVI r1,1
  RET
mth_cond_test_near_fail:
  MOVI r1,0
  RET

mth_cond_test_fail:
  MOVI r1,@mth_cond_test_bad
  CALL @mth_cond_test_puts
  HALT

mth_cond_test_puts:
  MOVI r4,255
mth_cond_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_cond_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_cond_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_cond_test_puts_word

mth_cond_test_pass:
.str "MTH MEMORY CONDITION PASS\n"
mth_cond_test_bad:
.str "MTH MEMORY CONDITION FAIL\n"

.org 4096
mth_cond_test_call_ret:
.word 0
mth_cond_test_run_ret:
.word 0
mth_cond_test_expected:
.word 0
mth_cond_test_expect_ret:
.word 0
mth_cond_test_h:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_cond_test_m:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_cond_test_gate:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_cond_test_out:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_cond_test_scratch:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
