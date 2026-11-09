; MTH 255-head field gate fixture — NaN16 only.
;
; Checks uniform and peaked softmax gates, the softmax reverse invariant for a
; constant upstream gradient, a one-hot upstream gradient, and rejection.

.org 0
JMP @mth_gate_test_main
.include "../nan16/mth_field_gate255_f32.nas"
.include "../nan16/mth_field_gate255_backward_f32.nas"

mth_gate_test_main:
  MOVI r0,0
  MOVI r13,1

  ; uniform scores -> weight 1/255
  CALL @mth_gate_test_zero_scores
  CALL @mth_gate_test_forward
  CMP r1,r13
  JMP[NE] @mth_gate_test_fail
  MOVI r8,@mth_gate_test_weights
  LD r1,r8,0
  MOVI r2,0x8081
  MOVHI r2,0x3B80            ; 1/255
  MOVI r3,0
  MOVHI r3,0x3586
  CALL @mth_gate_test_near
  CMP r1,r13
  JMP[NE] @mth_gate_test_fail
  MOVI r8,@mth_gate_test_weights
  ADDI r8,r8,254
  LD r1,r8,0
  MOVI r2,0x8081
  MOVHI r2,0x3B80
  MOVI r3,0
  MOVHI r3,0x3586
  CALL @mth_gate_test_near
  CMP r1,r13
  JMP[NE] @mth_gate_test_fail

  ; peaked score 0
  CALL @mth_gate_test_zero_scores
  MOVI r1,0
  MOVHI r1,0x42C8            ; 100
  ST r1,r0,@mth_gate_test_scores
  CALL @mth_gate_test_forward
  CMP r1,r13
  JMP[NE] @mth_gate_test_fail
  MOVI r8,@mth_gate_test_weights
  LD r1,r8,0
  MOVI r2,0
  MOVHI r2,0x3F80
  MOVI r3,0
  MOVHI r3,0x3586
  CALL @mth_gate_test_near
  CMP r1,r13
  JMP[NE] @mth_gate_test_fail

  ; uniform weights, constant d_weight -> zero d_score
  CALL @mth_gate_test_zero_scores
  CALL @mth_gate_test_forward
  CMP r1,r13
  JMP[NE] @mth_gate_test_fail
  CALL @mth_gate_test_fill_dw_one
  CALL @mth_gate_test_backward
  CMP r1,r13
  JMP[NE] @mth_gate_test_fail
  MOVI r6,0
mth_gate_test_zero_check:
  MOVI r8,@mth_gate_test_dscores
  ADD r8,r8,r6
  LD r1,r8,0
  CALL @mth_gate_test_zero
  CMP r1,r13
  JMP[NE] @mth_gate_test_fail
  ADDI r6,r6,1
  MOVI r8,255
  CMP r6,r8
  JMP[LT] @mth_gate_test_zero_check

  ; one-hot d_weight at 7
  CALL @mth_gate_test_zero_scores
  CALL @mth_gate_test_forward
  CALL @mth_gate_test_zero_dw
  MOVI r8,@mth_gate_test_dweights
  ADDI r8,r8,7
  MOVI r1,0
  MOVHI r1,0x3F80
  ST r1,r8,0
  CALL @mth_gate_test_backward
  CMP r1,r13
  JMP[NE] @mth_gate_test_fail
  MOVI r8,@mth_gate_test_dscores
  ADDI r8,r8,7
  LD r1,r8,0
  MOVI r2,0x0080
  MOVHI r2,0x3B80            ; 254/255^2
  MOVI r3,0
  MOVHI r3,0x3586
  CALL @mth_gate_test_near
  CMP r1,r13
  JMP[NE] @mth_gate_test_fail

  ; reject NaN weight
  MOVI r1,0
  MOVHI r1,0x7FC0
  ST r1,r0,@mth_gate_test_weights
  CALL @mth_gate_test_backward
  CMP r1,r0
  JMP[NE] @mth_gate_test_fail
  MOVI r8,1
  CMP r9,r8
  JMP[NE] @mth_gate_test_fail

  ; reject NaN d_weight
  CALL @mth_gate_test_zero_scores
  CALL @mth_gate_test_forward
  MOVI r1,0
  MOVHI r1,0x7FC0
  ST r1,r0,@mth_gate_test_dweights
  CALL @mth_gate_test_backward
  CMP r1,r0
  JMP[NE] @mth_gate_test_fail
  MOVI r8,2
  CMP r9,r8
  JMP[NE] @mth_gate_test_fail

  ; recovery
  CALL @mth_gate_test_zero_scores
  CALL @mth_gate_test_forward
  CMP r1,r13
  JMP[NE] @mth_gate_test_fail

  MOVI r1,@mth_gate_test_pass
  CALL @mth_gate_test_puts
  HALT

mth_gate_test_zero_scores:
  MOVI r6,0
mth_gate_test_zs:
  MOVI r8,@mth_gate_test_scores
  ADD r8,r8,r6
  ST r0,r8,0
  ADDI r6,r6,1
  MOVI r8,255
  CMP r6,r8
  JMP[LT] @mth_gate_test_zs
  RET

mth_gate_test_zero_dw:
  MOVI r6,0
mth_gate_test_zdw:
  MOVI r8,@mth_gate_test_dweights
  ADD r8,r8,r6
  ST r0,r8,0
  ADDI r6,r6,1
  MOVI r8,255
  CMP r6,r8
  JMP[LT] @mth_gate_test_zdw
  RET

mth_gate_test_fill_dw_one:
  MOVI r6,0
  MOVI r7,0
  MOVHI r7,0x3F80
mth_gate_test_fd:
  MOVI r8,@mth_gate_test_dweights
  ADD r8,r8,r6
  ST r7,r8,0
  ADDI r6,r6,1
  MOVI r8,255
  CMP r6,r8
  JMP[LT] @mth_gate_test_fd
  RET

mth_gate_test_forward:
  ST r15,r0,@mth_gate_test_fwd_ret
  MOVI r1,@mth_gate_test_scores
  MOVI r2,@mth_gate_test_weights
  MOVI r3,@mth_gate_test_scratch
  CALL @mth_field_gate255_f32
  LD r15,r0,@mth_gate_test_fwd_ret
  RET

mth_gate_test_backward:
  ST r15,r0,@mth_gate_test_bwd_ret
  MOVI r1,@mth_gate_test_weights
  MOVI r2,@mth_gate_test_dweights
  MOVI r3,@mth_gate_test_dscores
  CALL @mth_field_gate255_backward_f32
  LD r15,r0,@mth_gate_test_bwd_ret
  RET

mth_gate_test_zero:
  CMP r1,r0
  JMP[NE] @mth_gate_test_fail
  MOVI r1,1
  RET

mth_gate_test_near:
  MOVI r4,0
  MOVHI r4,0x7FFF
  FSUB r5,r1,r2
  BOOL.8 r5,r5,r4
  FCMP r5,r3
  JMP[GT] @mth_gate_test_near_fail
  MOVI r1,1
  RET
mth_gate_test_near_fail:
  MOVI r1,0
  RET

mth_gate_test_fail:
  MOVI r1,@mth_gate_test_bad
  CALL @mth_gate_test_puts
  HALT

mth_gate_test_puts:
  MOVI r4,255
mth_gate_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_gate_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_gate_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_gate_test_puts_word

mth_gate_test_pass:
.str "MTH FIELD GATE255 PASS\n"
mth_gate_test_bad:
.str "MTH FIELD GATE255 FAIL\n"

.org 4096
mth_gate_test_scores:
.word 0
.org 4352
mth_gate_test_weights:
.word 0
.org 4608
mth_gate_test_scratch:
.word 0
.org 4866
mth_gate_test_dweights:
.word 0
.org 5121
mth_gate_test_dscores:
.word 0
.org 5376
mth_gate_test_fwd_ret:
.word 0
mth_gate_test_bwd_ret:
.word 0
