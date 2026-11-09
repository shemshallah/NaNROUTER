; MTH 16→16 affine projection fixture — NaN16 only.
;
; Checks identity, bias, a non-identity row, non-finite operands, overflow
; rejection, output atomicity, and recovery.

.org 0
JMP @mth_project_test_main
.include "../nan16/mth_attention_project16_f32.nas"

mth_project_test_main:
  MOVI r0,0
  MOVI r13,1
  CALL @mth_project_test_init

  ; identity x + 0 -> x
  CALL @mth_project_test_run
  CMP r1,r13
  JMP[NE] @mth_project_test_fail
  MOVI r6,0
mth_project_test_identity_check:
  MOVI r8,@mth_project_test_x
  ADD r8,r8,r6
  LD r1,r8,0
  MOVI r8,@mth_project_test_out
  ADD r8,r8,r6
  LD r2,r8,0
  CMP r1,r2
  JMP[NE] @mth_project_test_fail
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_project_test_identity_check

  ; bias 0.5 everywhere -> x + 0.5
  MOVI r6,0
  MOVI r7,0
  MOVHI r7,0x3F00
mth_project_test_bias_fill:
  MOVI r8,@mth_project_test_b
  ADD r8,r8,r6
  ST r7,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_project_test_bias_fill
  CALL @mth_project_test_run
  CMP r1,r13
  JMP[NE] @mth_project_test_fail
  MOVI r8,@mth_project_test_x
  LD r1,r8,0
  MOVI r2,0
  MOVHI r2,0x3F00
  FADD r1,r1,r2
  MOVI r8,@mth_project_test_out
  LD r2,r8,0
  CMP r1,r2
  JMP[NE] @mth_project_test_fail

  ; reset bias, make row 0 select x[15]
  MOVI r1,0
  CALL @mth_project_test_zero_b
  MOVI r6,0
  MOVI r7,0
mth_project_test_w_zero:
  MOVI r8,@mth_project_test_w
  ADD r8,r8,r6
  ST r7,r8,0
  ADDI r6,r6,1
  MOVI r8,256
  CMP r6,r8
  JMP[LT] @mth_project_test_w_zero
  MOVI r1,0
  MOVHI r1,0x3F80
  MOVI r8,@mth_project_test_w
  ADDI r8,r8,15
  ST r1,r8,0
  CALL @mth_project_test_run
  CMP r1,r13
  JMP[NE] @mth_project_test_fail
  MOVI r8,@mth_project_test_out
  LD r1,r8,0
  MOVI r8,@mth_project_test_x
  ADDI r8,r8,15
  LD r2,r8,0
  CMP r1,r2
  JMP[NE] @mth_project_test_fail

  ; restore identity
  CALL @mth_project_test_init

  ; NaN x rejects cause 1
  MOVI r1,0xBEEF
  MOVHI r1,0xDEAD
  ST r1,r0,@mth_project_test_out
  MOVI r1,0
  MOVHI r1,0x7FC0
  ST r1,r0,@mth_project_test_x
  CALL @mth_project_test_call
  CMP r1,r0
  JMP[NE] @mth_project_test_fail
  MOVI r8,1
  CMP r9,r8
  JMP[NE] @mth_project_test_fail
  CALL @mth_project_test_sentinel

  ; NaN W rejects cause 2
  CALL @mth_project_test_init
  MOVI r1,0
  MOVHI r1,0x7FC0
  ST r1,r0,@mth_project_test_w
  CALL @mth_project_test_set_sentinel
  CALL @mth_project_test_call
  CMP r1,r0
  JMP[NE] @mth_project_test_fail
  MOVI r8,2
  CMP r9,r8
  JMP[NE] @mth_project_test_fail
  CALL @mth_project_test_sentinel

  ; NaN bias rejects cause 3
  CALL @mth_project_test_init
  MOVI r1,0
  MOVHI r1,0x7FC0
  ST r1,r0,@mth_project_test_b
  CALL @mth_project_test_set_sentinel
  CALL @mth_project_test_call
  CMP r1,r0
  JMP[NE] @mth_project_test_fail
  MOVI r8,3
  CMP r9,r8
  JMP[NE] @mth_project_test_fail
  CALL @mth_project_test_sentinel

  ; overflow rejects cause 4
  CALL @mth_project_test_init
  MOVI r1,0
  MOVHI r1,0x4000            ; x[0]=2
  ST r1,r0,@mth_project_test_x
  MOVI r1,0xFFFF
  MOVHI r1,0x7F7F            ; max finite
  ST r1,r0,@mth_project_test_w
  CALL @mth_project_test_set_sentinel
  CALL @mth_project_test_call
  CMP r1,r0
  JMP[NE] @mth_project_test_fail
  MOVI r8,4
  CMP r9,r8
  JMP[NE] @mth_project_test_fail
  CALL @mth_project_test_sentinel

  ; recovery
  CALL @mth_project_test_init
  CALL @mth_project_test_run
  CMP r1,r13
  JMP[NE] @mth_project_test_fail

  MOVI r1,@mth_project_test_pass
  CALL @mth_project_test_puts
  HALT

mth_project_test_init:
  ST r15,r0,@mth_project_test_ret
  ; x[d]=d+1, b=0, W=I, out=0, scratch=0
  MOVI r6,0
mth_project_test_init_loop:
  MOVI r1,0
  MOVHI r1,0x3F80
  ADD r1,r1,r6
  MOVI r8,@mth_project_test_x
  ADD r8,r8,r6
  ST r1,r8,0
  MOVI r8,@mth_project_test_b
  ADD r8,r8,r6
  ST r0,r8,0
  MOVI r8,@mth_project_test_out
  ADD r8,r8,r6
  ST r0,r8,0
  MOVI r8,@mth_project_test_scratch
  ADD r8,r8,r6
  ST r0,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_project_test_init_loop

  MOVI r6,0
mth_project_test_w_init:
  MOVI r8,@mth_project_test_w
  ADD r8,r8,r6
  ST r0,r8,0
  ADDI r6,r6,1
  MOVI r8,256
  CMP r6,r8
  JMP[LT] @mth_project_test_w_init
  MOVI r6,0
mth_project_test_w_diag:
  MOVI r8,@mth_project_test_w
  SHL r7,r6,4
  ADD r8,r8,r7
  ADD r8,r8,r6
  MOVI r7,0
  MOVHI r7,0x3F80
  ST r7,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_project_test_w_diag
  LD r15,r0,@mth_project_test_ret
  RET

mth_project_test_zero_b:
  MOVI r6,0
mth_project_test_zb_loop:
  MOVI r8,@mth_project_test_b
  ADD r8,r8,r6
  ST r0,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_project_test_zb_loop
  RET

mth_project_test_call:
  ST r15,r0,@mth_project_test_call_ret
  MOVI r1,@mth_project_test_x
  MOVI r2,@mth_project_test_w
  MOVI r3,@mth_project_test_b
  MOVI r4,@mth_project_test_out
  MOVI r5,@mth_project_test_scratch
  CALL @mth_attention_project16_f32
  LD r15,r0,@mth_project_test_call_ret
  RET

mth_project_test_run:
  ST r15,r0,@mth_project_test_run_ret
  CALL @mth_project_test_call
  CMP r1,r13
  JMP[NE] @mth_project_test_fail
  CMP r9,r0
  JMP[NE] @mth_project_test_fail
  LD r15,r0,@mth_project_test_run_ret
  RET

mth_project_test_set_sentinel:
  MOVI r1,0xBEEF
  MOVHI r1,0xDEAD
  ST r1,r0,@mth_project_test_out
  RET

mth_project_test_sentinel:
  LD r1,r0,@mth_project_test_out
  MOVI r2,0xBEEF
  MOVHI r2,0xDEAD
  CMP r1,r2
  JMP[NE] @mth_project_test_fail
  RET

mth_project_test_fail:
  MOVI r1,@mth_project_test_bad
  CALL @mth_project_test_puts
  HALT

mth_project_test_puts:
  MOVI r4,255
mth_project_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_project_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_project_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_project_test_puts_word

mth_project_test_pass:
.str "MTH ATTENTION PROJECT16 PASS\n"
mth_project_test_bad:
.str "MTH ATTENTION PROJECT16 FAIL\n"

.org 4096
mth_project_test_ret:
.word 0
mth_project_test_call_ret:
.word 0
mth_project_test_run_ret:
.word 0
mth_project_test_x:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_project_test_b:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_project_test_out:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_project_test_scratch:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_project_test_w:
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
