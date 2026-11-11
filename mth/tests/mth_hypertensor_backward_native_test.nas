; Native reverse-mode hypertensor 16^3 backward fixture.
.org 0
JMP @mth_hb_main
.include "../nan16/mth_hypertensor16_backward_f32.nas"

mth_hb_main:
  MOVI r0,0
  MOVI r13,1
  MOVI r6,0
  MOVI r10,0
  MOVHI r10,0x3F80      ; a=1
  MOVI r11,0
  MOVHI r11,0x4000      ; b=2
  MOVI r12,0
  MOVHI r12,0x4040      ; c=3
mth_hb_set_vectors:
  MOVI r7,@mth_hb_a
  ADD r7,r7,r6
  ST r10,r7,0
  MOVI r7,@mth_hb_b
  ADD r7,r7,r6
  ST r11,r7,0
  MOVI r7,@mth_hb_c
  ADD r7,r7,r6
  ST r12,r7,0
  ADDI r6,r6,1
  MOVI r7,16
  CMP r6,r7
  JMP[LT] @mth_hb_set_vectors
  ; dT=1 for every entry.
  MOVI r6,0
  MOVI r10,0
  MOVHI r10,0x3F80
mth_hb_set_gradient:
  MOVI r7,@mth_hb_g
  ADD r7,r7,r6
  ST r10,r7,0
  ADDI r6,r6,1
  MOVI r7,4096
  CMP r6,r7
  JMP[LT] @mth_hb_set_gradient

  MOVI r1,@mth_hb_a
  MOVI r2,@mth_hb_b
  MOVI r3,@mth_hb_c
  MOVI r4,@mth_hb_g
  MOVI r5,@mth_hb_da
  MOVI r6,@mth_hb_db
  MOVI r7,@mth_hb_dc
  MOVI r8,@mth_hb_scratch
  CALL @mth_hypertensor16_backward_f32
  CMP r1,r13
  JMP[NE] @mth_hb_fail
  ; dA=16^2*2*3=1536, dB=16^2*1*3=768, dC=16^2*1*2=512.
  MOVI r10,0
  MOVHI r10,0x44C0
  LD r11,r0,@mth_hb_da
  CMP r11,r10
  JMP[NE] @mth_hb_fail
  LD r11,r0,@mth_hb_da+15
  CMP r11,r10
  JMP[NE] @mth_hb_fail
  MOVI r10,0
  MOVHI r10,0x4440
  LD r11,r0,@mth_hb_db
  CMP r11,r10
  JMP[NE] @mth_hb_fail
  MOVI r10,0
  MOVHI r10,0x4400
  LD r11,r0,@mth_hb_dc
  CMP r11,r10
  JMP[NE] @mth_hb_fail

  ; Inject NaN in the final G element; output must remain unchanged.
  MOVI r10,0
  MOVHI r10,0x7FC0
  MOVI r11,@mth_hb_g
  ADDI r11,r11,4095
  ST r10,r11,0
  MOVI r1,@mth_hb_a
  MOVI r2,@mth_hb_b
  MOVI r3,@mth_hb_c
  MOVI r4,@mth_hb_g
  MOVI r5,@mth_hb_da
  MOVI r6,@mth_hb_db
  MOVI r7,@mth_hb_dc
  MOVI r8,@mth_hb_scratch
  CALL @mth_hypertensor16_backward_f32
  CMP r1,r0
  JMP[NE] @mth_hb_fail
  MOVI r10,0
  MOVHI r10,0x44C0
  LD r11,r0,@mth_hb_da
  CMP r11,r10
  JMP[NE] @mth_hb_fail

  MOVI r1,@mth_hb_pass
  CALL @mth_hb_puts
  HALT
mth_hb_fail:
  MOVI r1,@mth_hb_bad
  CALL @mth_hb_puts
  HALT
mth_hb_puts:
  MOVI r4,255
mth_hb_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_hb_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_hb_puts_byte
  ADD r1,r1,r13
  JMP @mth_hb_puts_word
mth_hb_pass:
.str "MTH HYPERTENSOR BACKWARD PASS\n"
mth_hb_bad:
.str "MTH HYPERTENSOR BACKWARD FAIL\n"

.org 8192
mth_hb_a:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_hb_b:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_hb_c:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_hb_da:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_hb_db:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_hb_dc:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_hb_scratch:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.org 9000
mth_hb_g:
.word 0
