; NaN16 native masked softmax + value mix backward regression.
.org 0
JMP @mth_gb_main
.include "../nan16/mth_global_focus16_backward_f32.nas"
mth_gb_main:
  MOVI r0,0
  MOVI r13,1
  MOVI r10,0
  MOVHI r10,0x3F00       ; weights[0]=weights[1]=0.5
  ST r10,r0,@mth_gb_weights
  ST r10,r0,@mth_gb_weights+1
  MOVI r10,0
  MOVHI r10,0x4000       ; V[0,0]=2
  ST r10,r0,@mth_gb_values
  MOVI r10,0
  MOVHI r10,0x4080       ; V[1,0]=4
  MOVI r11,@mth_gb_values
  ADDI r11,r11,16
  ST r10,r11,0
  MOVI r10,0
  MOVHI r10,0x3F80       ; grad_out[0]=1
  ST r10,r0,@mth_gb_upstream

  MOVI r1,@mth_gb_weights
  MOVI r2,@mth_gb_values
  MOVI r3,@mth_gb_upstream
  MOVI r4,@mth_gb_ds
  MOVI r5,@mth_gb_dv
  MOVI r6,@mth_gb_scratch
  CALL @mth_global_focus16_backward_f32
  MOVI r14,65 ; A
  CMP r1,r13
  JMP[NE] @mth_gb_fail
  ; dscore=[-0.5,+0.5,0...], dV[0,0]=dV[1,0]=.5.
  MOVI r10,0
  MOVHI r10,0xBF00       ; -0.5
  MOVI r14,66 ; B
  LD r11,r0,@mth_gb_ds
  CMP r11,r10
  JMP[NE] @mth_gb_fail
  MOVI r10,0
  MOVHI r10,0x3F00
  MOVI r14,67 ; C
  LD r11,r0,@mth_gb_ds+1
  CMP r11,r10
  JMP[NE] @mth_gb_fail
  MOVI r14,68 ; D
  LD r11,r0,@mth_gb_dv
  CMP r11,r10
  JMP[NE] @mth_gb_fail
  MOVI r14,69 ; E
  MOVI r12,@mth_gb_dv
  ADDI r12,r12,16
  LD r11,r12,0
  CMP r11,r10
  JMP[NE] @mth_gb_fail
  MOVI r14,70 ; F
  LD r11,r0,@mth_gb_ds+15
  CMP r11,r0
  JMP[NE] @mth_gb_fail
  ; No upstream gradient in other channels, all other components zero.
  MOVI r14,71 ; G
  LD r11,r0,@mth_gb_dv+1
  CMP r11,r0
  JMP[NE] @mth_gb_fail

  ; Reject nonfinite upstream and preserve existing gradient outputs.
  MOVI r10,0
  MOVHI r10,0x7FC0
  ST r10,r0,@mth_gb_upstream
  MOVI r1,@mth_gb_weights
  MOVI r2,@mth_gb_values
  MOVI r3,@mth_gb_upstream
  MOVI r4,@mth_gb_ds
  MOVI r5,@mth_gb_dv
  MOVI r6,@mth_gb_scratch
  CALL @mth_global_focus16_backward_f32
  MOVI r14,72 ; H
  CMP r1,r0
  JMP[NE] @mth_gb_fail
  MOVI r14,73 ; I
  MOVI r10,0
  MOVHI r10,0xBF00
  LD r11,r0,@mth_gb_ds
  CMP r11,r10
  JMP[NE] @mth_gb_fail

  MOVI r1,@mth_gb_pass
  CALL @mth_gb_puts
  HALT
mth_gb_fail:
  PUTC r14
  MOVI r1,@mth_gb_bad
  CALL @mth_gb_puts
  HALT
mth_gb_puts:
  MOVI r4,255
mth_gb_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_gb_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_gb_puts_byte
  ADD r1,r1,r13
  JMP @mth_gb_puts_word
mth_gb_pass:
.str "MTH GLOBAL FOCUS BACKWARD PASS\n"
mth_gb_bad:
.str "MTH GLOBAL FOCUS BACKWARD FAIL\n"

.org 8192
mth_gb_weights:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_gb_upstream:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_gb_ds:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.org 10000
mth_gb_values:
.word 0
.org 11000
mth_gb_dv:
.word 0
.org 12000
mth_gb_scratch:
.word 0
