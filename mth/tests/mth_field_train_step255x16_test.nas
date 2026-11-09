; MTH 255-head field training-step fixture — NaN16 only.
;
; weight0=1, value row0=2, g=1, lr=0.001:
;   d_weight0=32 -> weight0=0.968
;   d_value0c=1  -> value0c=1.999
; Checks in-place updates, lr=0 no-op, invalid domains, and recovery.

.org 0
JMP @mth_step_test_main
.include "../nan16/mth_field_train_step255x16_f32.nas"

mth_step_test_main:
  MOVI r0,0
  MOVI r13,1
  CALL @mth_step_test_init
  MOVI r4,0
  MOVHI r4,0x3A83            ; 0.001
  CALL @mth_step_test_call
  CMP r1,r13
  JMP[NE] @mth_step_test_fail

  MOVI r8,@mth_step_test_weights
  LD r1,r8,0
  MOVI r2,0xCED9
  MOVHI r2,0x3F77            ; 0.968
  CALL @mth_step_test_near
  CMP r1,r13
  JMP[NE] @mth_step_test_fail
  MOVI r8,@mth_step_test_values
  LD r1,r8,0
  MOVI r2,0xDF3B
  MOVHI r2,0x3FFF            ; 1.999
  CALL @mth_step_test_near
  CMP r1,r13
  JMP[NE] @mth_step_test_fail
  MOVI r8,@mth_step_test_values
  ADDI r8,r8,15
  LD r1,r8,0
  MOVI r2,0xDF3B
  MOVHI r2,0x3FFF
  CALL @mth_step_test_near
  CMP r1,r13
  JMP[NE] @mth_step_test_fail
  MOVI r8,@mth_step_test_weights
  ADDI r8,r8,1
  LD r1,r8,0
  CALL @mth_step_test_zero
  CMP r1,r13
  JMP[NE] @mth_step_test_fail

  ; lr=0 no-op
  CALL @mth_step_test_init
  MOVI r4,0
  CALL @mth_step_test_call
  CMP r1,r13
  JMP[NE] @mth_step_test_fail
  MOVI r8,@mth_step_test_weights
  LD r1,r8,0
  MOVI r2,0
  MOVHI r2,0x3F80
  CALL @mth_step_test_near
  CMP r1,r13
  JMP[NE] @mth_step_test_fail

  ; invalid lr -0.1
  CALL @mth_step_test_init
  MOVI r4,0
  MOVHI r4,0xBDCC
  CALL @mth_step_test_call
  CMP r1,r0
  JMP[NE] @mth_step_test_fail
  MOVI r8,4
  CMP r9,r8
  JMP[NE] @mth_step_test_fail

  ; invalid lr 1.1
  CALL @mth_step_test_init
  MOVI r4,0
  MOVHI r4,0x3F8C
  CALL @mth_step_test_call
  CMP r1,r0
  JMP[NE] @mth_step_test_fail
  MOVI r8,4
  CMP r9,r8
  JMP[NE] @mth_step_test_fail

  ; NaN value cause 2
  CALL @mth_step_test_init
  MOVI r1,0
  MOVHI r1,0x7FC0
  ST r1,r0,@mth_step_test_values
  MOVI r4,0
  MOVHI r4,0x3A83
  CALL @mth_step_test_call
  CMP r1,r0
  JMP[NE] @mth_step_test_fail
  MOVI r8,2
  CMP r9,r8
  JMP[NE] @mth_step_test_fail

  ; NaN gradient cause 3
  CALL @mth_step_test_init
  MOVI r1,0
  MOVHI r1,0x7FC0
  ST r1,r0,@mth_step_test_grad
  MOVI r4,0
  MOVHI r4,0x3A83
  CALL @mth_step_test_call
  CMP r1,r0
  JMP[NE] @mth_step_test_fail
  MOVI r8,3
  CMP r9,r8
  JMP[NE] @mth_step_test_fail

  ; recovery
  CALL @mth_step_test_init
  MOVI r4,0
  MOVHI r4,0x3A83
  CALL @mth_step_test_call
  CMP r1,r13
  JMP[NE] @mth_step_test_fail

  MOVI r1,@mth_step_test_pass
  CALL @mth_step_test_puts
  HALT

mth_step_test_init:
  MOVI r6,0
mth_step_test_w_zero:
  MOVI r8,@mth_step_test_weights
  ADD r8,r8,r6
  ST r0,r8,0
  ADDI r6,r6,1
  MOVI r8,255
  CMP r6,r8
  JMP[LT] @mth_step_test_w_zero
  MOVI r6,0
mth_step_test_v_zero:
  MOVI r8,@mth_step_test_values
  ADD r8,r8,r6
  ST r0,r8,0
  ADDI r6,r6,1
  MOVI r8,4080
  CMP r6,r8
  JMP[LT] @mth_step_test_v_zero
  MOVI r6,0
mth_step_test_g_fill:
  MOVI r8,@mth_step_test_grad
  ADD r8,r8,r6
  MOVI r1,0
  MOVHI r1,0x3F80
  ST r1,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_step_test_g_fill

  MOVI r8,@mth_step_test_weights
  MOVI r1,0
  MOVHI r1,0x3F80
  ST r1,r8,0
  MOVI r6,0
  MOVI r1,0
  MOVHI r1,0x4000
mth_step_test_v_row0:
  MOVI r8,@mth_step_test_values
  ADD r8,r8,r6
  ST r1,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_step_test_v_row0
  RET

mth_step_test_call:
  ST r15,r0,@mth_step_test_ret
  MOVI r1,@mth_step_test_weights
  MOVI r2,@mth_step_test_values
  MOVI r3,@mth_step_test_grad
  CALL @mth_field_train_step255x16_f32
  LD r15,r0,@mth_step_test_ret
  RET

mth_step_test_near:
  MOVI r4,0
  MOVHI r4,0x7FFF
  FSUB r5,r1,r2
  BOOL.8 r5,r5,r4
  MOVI r3,0
  MOVHI r3,0x38D1            ; 1e-4
  FCMP r5,r3
  JMP[GT] @mth_step_test_near_fail
  MOVI r1,1
  RET
mth_step_test_near_fail:
  MOVI r1,0
  RET

mth_step_test_zero:
  CMP r1,r0
  JMP[NE] @mth_step_test_fail
  MOVI r1,1
  RET

mth_step_test_fail:
  MOVI r1,@mth_step_test_bad
  CALL @mth_step_test_puts
  HALT

mth_step_test_puts:
  MOVI r4,255
mth_step_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_step_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_step_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_step_test_puts_word

mth_step_test_pass:
.str "MTH FIELD TRAIN STEP PASS\n"
mth_step_test_bad:
.str "MTH FIELD TRAIN STEP FAIL\n"

.org 4096
mth_step_test_weights:
.word 0
.org 4352
mth_step_test_values:
.word 0
.org 8448
mth_step_test_grad:
.word 0
.org 8464
mth_step_test_ret:
.word 0
