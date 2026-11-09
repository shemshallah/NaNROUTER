; MTH 255-head field-mixture reverse fixture — NaN16 only.
;
; Checks d_weight/d_value formulas, one native finite-difference weight and
; value check, non-finite input rejection, and recovery.

.org 0
JMP @mth_fbwd_test_main
.include "../nan16/mth_field_mix255x16_f32.nas"
.include "../nan16/mth_field_mix255x16_backward_f32.nas"

mth_fbwd_test_main:
  MOVI r0,0
  MOVI r13,1
  CALL @mth_fbwd_test_init

  ; forward out[0] = 5
  CALL @mth_fbwd_test_forward
  MOVI r1,0
  MOVHI r1,0x40A0            ; 5
  MOVI r8,@mth_fbwd_test_out
  LD r2,r8,0
  MOVI r3,0
  MOVHI r3,0x3586
  CALL @mth_fbwd_test_near
  CMP r1,r13
  JMP[NE] @mth_fbwd_test_fail

  ; reverse
  CALL @mth_fbwd_test_backward
  CMP r1,r13
  JMP[NE] @mth_fbwd_test_fail
  MOVI r8,@mth_fbwd_test_dw
  LD r1,r8,0
  MOVI r2,0
  MOVHI r2,0x4200            ; 32
  CALL @mth_fbwd_test_near_abs
  CMP r1,r13
  JMP[NE] @mth_fbwd_test_fail
  MOVI r8,@mth_fbwd_test_dw
  ADDI r8,r8,1
  LD r1,r8,0
  MOVI r2,0
  MOVHI r2,0x4240            ; 48
  CALL @mth_fbwd_test_near_abs
  CMP r1,r13
  JMP[NE] @mth_fbwd_test_fail
  MOVI r8,@mth_fbwd_test_dw
  ADDI r8,r8,2
  LD r1,r8,0
  CALL @mth_fbwd_test_zero
  CMP r1,r13
  JMP[NE] @mth_fbwd_test_fail
  MOVI r8,@mth_fbwd_test_dv
  LD r1,r8,0
  MOVI r2,0
  MOVHI r2,0x3F80            ; 1
  CALL @mth_fbwd_test_near_abs
  CMP r1,r13
  JMP[NE] @mth_fbwd_test_fail

  ; finite difference dL/dw0 = 32
  CALL @mth_fbwd_test_fd_weight
  MOVI r3,0
  MOVHI r3,0x3F80            ; tolerance 1
  CALL @mth_fbwd_test_fd_check_dw
  CMP r1,r13
  JMP[NE] @mth_fbwd_test_fail

  ; finite difference dL/dv[0,0] = 1
  CALL @mth_fbwd_test_fd_value
  MOVI r3,0
  MOVHI r3,0x3C23            ; tolerance 0.01
  CALL @mth_fbwd_test_fd_check_dv
  CMP r1,r13
  JMP[NE] @mth_fbwd_test_fail

  ; reject NaN weight
  MOVI r1,0
  MOVHI r1,0x7FC0
  ST r1,r0,@mth_fbwd_test_weights
  CALL @mth_fbwd_test_backward
  CMP r1,r0
  JMP[NE] @mth_fbwd_test_fail
  MOVI r8,1
  CMP r9,r8
  JMP[NE] @mth_fbwd_test_fail

  ; reject NaN value
  CALL @mth_fbwd_test_init
  MOVI r1,0
  MOVHI r1,0x7FC0
  ST r1,r0,@mth_fbwd_test_values
  CALL @mth_fbwd_test_backward
  CMP r1,r0
  JMP[NE] @mth_fbwd_test_fail
  MOVI r8,2
  CMP r9,r8
  JMP[NE] @mth_fbwd_test_fail

  ; reject NaN gradient
  CALL @mth_fbwd_test_init
  MOVI r1,0
  MOVHI r1,0x7FC0
  ST r1,r0,@mth_fbwd_test_grad
  CALL @mth_fbwd_test_backward
  CMP r1,r0
  JMP[NE] @mth_fbwd_test_fail
  MOVI r8,3
  CMP r9,r8
  JMP[NE] @mth_fbwd_test_fail

  ; recovery
  CALL @mth_fbwd_test_init
  CALL @mth_fbwd_test_backward
  CMP r1,r13
  JMP[NE] @mth_fbwd_test_fail

  MOVI r1,@mth_fbwd_test_pass
  CALL @mth_fbwd_test_puts
  HALT

mth_fbwd_test_init:
  ; zero weights, values, grad, dw, dv
  MOVI r6,0
mth_fbwd_test_zero_w:
  MOVI r8,@mth_fbwd_test_weights
  ADD r8,r8,r6
  ST r0,r8,0
  MOVI r8,@mth_fbwd_test_dw
  ADD r8,r8,r6
  ST r0,r8,0
  ADDI r6,r6,1
  MOVI r8,255
  CMP r6,r8
  JMP[LT] @mth_fbwd_test_zero_w
  MOVI r6,0
mth_fbwd_test_zero_v:
  MOVI r8,@mth_fbwd_test_values
  ADD r8,r8,r6
  ST r0,r8,0
  MOVI r8,@mth_fbwd_test_dv
  ADD r8,r8,r6
  ST r0,r8,0
  ADDI r6,r6,1
  MOVI r8,4080
  CMP r6,r8
  JMP[LT] @mth_fbwd_test_zero_v
  MOVI r6,0
mth_fbwd_test_fill_grad:
  MOVI r8,@mth_fbwd_test_grad
  ADD r8,r8,r6
  MOVI r1,0
  MOVHI r1,0x3F80
  ST r1,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_fbwd_test_fill_grad

  ; weights 0 and 1 = 1; values rows 0=2,1=3
  MOVI r8,@mth_fbwd_test_weights
  MOVI r1,0
  MOVHI r1,0x3F80
  ST r1,r8,0
  ADDI r8,r8,1
  ST r1,r8,0
  MOVI r6,0
mth_fbwd_test_row0:
  MOVI r8,@mth_fbwd_test_values
  ADD r8,r8,r6
  MOVI r1,0
  MOVHI r1,0x4000
  ST r1,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_fbwd_test_row0
mth_fbwd_test_row1:
  MOVI r8,@mth_fbwd_test_values
  ADD r8,r8,r6
  MOVI r1,0
  MOVHI r1,0x4040
  ST r1,r8,0
  ADDI r6,r6,1
  MOVI r8,32
  CMP r6,r8
  JMP[LT] @mth_fbwd_test_row1
  RET

mth_fbwd_test_forward:
  ST r15,r0,@mth_fbwd_test_forward_ret
  MOVI r1,@mth_fbwd_test_weights
  MOVI r2,@mth_fbwd_test_values
  MOVI r3,@mth_fbwd_test_out
  MOVI r4,@mth_fbwd_test_scratch
  CALL @mth_field_mix255x16_f32
  LD r15,r0,@mth_fbwd_test_forward_ret
  RET

mth_fbwd_test_backward:
  ST r15,r0,@mth_fbwd_test_backward_ret
  MOVI r1,@mth_fbwd_test_weights
  MOVI r2,@mth_fbwd_test_values
  MOVI r3,@mth_fbwd_test_grad
  MOVI r4,@mth_fbwd_test_dw
  MOVI r5,@mth_fbwd_test_dv
  CALL @mth_field_mix255x16_backward_f32
  LD r15,r0,@mth_fbwd_test_backward_ret
  RET

mth_fbwd_test_sum_out:
  MOVI r6,0
  MOVI r7,0
mth_fbwd_test_sum_loop:
  MOVI r8,@mth_fbwd_test_out
  ADD r8,r8,r6
  LD r8,r8,0
  FADD r7,r7,r8
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_fbwd_test_sum_loop
  ADD r1,r7,r0
  RET

mth_fbwd_test_fd_weight:
  ST r15,r0,@mth_fbwd_test_ret
  MOVI r8,@mth_fbwd_test_weights
  LD r9,r8,0
  ST r9,r0,@mth_fbwd_test_saved
  ; plus 0.01
  MOVI r10,0
  MOVHI r10,0x3C23
  FADD r10,r9,r10
  ST r10,r8,0
  CALL @mth_fbwd_test_forward
  CALL @mth_fbwd_test_sum_out
  ST r1,r0,@mth_fbwd_test_lplus
  ; minus 0.01
  LD r9,r0,@mth_fbwd_test_saved
  MOVI r10,0
  MOVHI r10,0x3C23
  FSUB r10,r9,r10
  MOVI r8,@mth_fbwd_test_weights
  ST r10,r8,0
  CALL @mth_fbwd_test_forward
  CALL @mth_fbwd_test_sum_out
  ST r1,r0,@mth_fbwd_test_lminus
  LD r9,r0,@mth_fbwd_test_saved
  MOVI r8,@mth_fbwd_test_weights
  ST r9,r8,0
  LD r1,r0,@mth_fbwd_test_lplus
  LD r2,r0,@mth_fbwd_test_lminus
  FSUB r1,r1,r2
  MOVI r2,0
  MOVHI r2,0x3CA3            ; 0.02
  FDIV r1,r1,r2
  ST r1,r0,@mth_fbwd_test_numeric
  LD r15,r0,@mth_fbwd_test_ret
  RET

mth_fbwd_test_fd_value:
  ST r15,r0,@mth_fbwd_test_ret
  MOVI r8,@mth_fbwd_test_values
  LD r9,r8,0
  ST r9,r0,@mth_fbwd_test_saved
  MOVI r10,0
  MOVHI r10,0x3A83            ; 0.001
  FADD r10,r9,r10
  ST r10,r8,0
  CALL @mth_fbwd_test_forward
  CALL @mth_fbwd_test_sum_out
  ST r1,r0,@mth_fbwd_test_lplus
  LD r9,r0,@mth_fbwd_test_saved
  MOVI r10,0
  MOVHI r10,0x3A83
  FSUB r10,r9,r10
  MOVI r8,@mth_fbwd_test_values
  ST r10,r8,0
  CALL @mth_fbwd_test_forward
  CALL @mth_fbwd_test_sum_out
  ST r1,r0,@mth_fbwd_test_lminus
  LD r9,r0,@mth_fbwd_test_saved
  MOVI r8,@mth_fbwd_test_values
  ST r9,r8,0
  LD r1,r0,@mth_fbwd_test_lplus
  LD r2,r0,@mth_fbwd_test_lminus
  FSUB r1,r1,r2
  MOVI r2,0
  MOVHI r2,0x3B03            ; 0.002
  FDIV r1,r1,r2
  ST r1,r0,@mth_fbwd_test_numeric
  LD r15,r0,@mth_fbwd_test_ret
  RET

mth_fbwd_test_fd_check_dw:
  ST r15,r0,@mth_fbwd_test_ret
  ST r3,r0,@mth_fbwd_test_tol
  LD r1,r0,@mth_fbwd_test_numeric
  LD r2,r0,@mth_fbwd_test_dw
  LD r3,r0,@mth_fbwd_test_tol
  CALL @mth_fbwd_test_near
  CMP r1,r13
  JMP[NE] @mth_fbwd_test_fail
  LD r15,r0,@mth_fbwd_test_ret
  RET

mth_fbwd_test_fd_check_dv:
  ST r15,r0,@mth_fbwd_test_ret
  ST r3,r0,@mth_fbwd_test_tol
  LD r1,r0,@mth_fbwd_test_numeric
  LD r2,r0,@mth_fbwd_test_dv
  LD r3,r0,@mth_fbwd_test_tol
  CALL @mth_fbwd_test_near
  CMP r1,r13
  JMP[NE] @mth_fbwd_test_fail
  LD r15,r0,@mth_fbwd_test_ret
  RET

mth_fbwd_test_near:
  MOVI r4,0
  MOVHI r4,0x7FFF
  FSUB r5,r1,r2
  BOOL.8 r5,r5,r4
  FCMP r5,r3
  JMP[GT] @mth_fbwd_test_near_fail
  MOVI r1,1
  RET
mth_fbwd_test_near_fail:
  MOVI r1,0
  RET

mth_fbwd_test_near_abs:
  MOVI r4,0
  MOVHI r4,0x7FFF
  FSUB r5,r1,r2
  BOOL.8 r5,r5,r4
  MOVI r3,0
  MOVHI r3,0x3586
  FCMP r5,r3
  JMP[GT] @mth_fbwd_test_near_fail
  MOVI r1,1
  RET

mth_fbwd_test_zero:
  CMP r1,r0
  JMP[NE] @mth_fbwd_test_fail
  MOVI r1,1
  RET

mth_fbwd_test_fail:
  MOVI r1,@mth_fbwd_test_bad
  CALL @mth_fbwd_test_puts
  HALT

mth_fbwd_test_puts:
  MOVI r4,255
mth_fbwd_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_fbwd_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_fbwd_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_fbwd_test_puts_word

mth_fbwd_test_pass:
.str "MTH FIELD MIX BACKWARD PASS\n"
mth_fbwd_test_bad:
.str "MTH FIELD MIX BACKWARD FAIL\n"

.org 4096
mth_fbwd_test_weights:
.word 0
.org 4352
mth_fbwd_test_values:
.word 0
.org 8448
mth_fbwd_test_grad:
.word 0
.org 8464
mth_fbwd_test_dw:
.word 0
.org 8720
mth_fbwd_test_dv:
.word 0
.org 12800
mth_fbwd_test_out:
.word 0
.org 12816
mth_fbwd_test_scratch:
.word 0
.org 12832
mth_fbwd_test_ret:
.word 0
mth_fbwd_test_forward_ret:
.word 0
mth_fbwd_test_backward_ret:
.word 0
mth_fbwd_test_saved:
.word 0
mth_fbwd_test_lplus:
.word 0
mth_fbwd_test_lminus:
.word 0
mth_fbwd_test_numeric:
.word 0
mth_fbwd_test_tol:
.word 0
