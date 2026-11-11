; NaN16 exact checkpoint-resume admission verifier for 26^3 tensor.
; Inputs: r1=T[17576] f32 bits; r2=expected uint32 sum of raw words;
; r3=expected uint32 weighted sum of (word*(i+1)); r4=void255[1].
; r13=1. No memory writes, no host arithmetic or root modification.
; SHA-256 of the original checkpoint is verified upstream BEFORE
; image construction; these two independent native checks verify that the
; VM actually loaded that same binary and the void head remains zero.
; r1=1,r9=0 success; r1=0,r9=1 reject.
mth_inverse_trigram26_resume_verify:
  MOVI r0,0
  LD r5,r4,0
  CMP r5,r0
  JMP[NE] @mth_trv_fail
  MOVI r5,0                  ; index
  MOVI r6,0                  ; raw sum
  MOVI r7,0                  ; weighted sum
  MOVI r14,0
  MOVHI r14,0x7F80           ; float exponent
mth_trv_step:
  ADD r8,r1,r5
  LD r8,r8,0
  BOOL.8 r9,r8,r14
  CMP r9,r14
  JMP[EQ] @mth_trv_fail     ; finite only, reject NaN or Inf
  ADD r6,r6,r8
  ADDI r10,r5,1
  MUL r11,r8,r10
  ADD r7,r7,r11
  ADDI r5,r5,1
  MOVI r10,17576
  CMP r5,r10
  JMP[LT] @mth_trv_step
  CMP r6,r2
  JMP[NE] @mth_trv_fail
  CMP r7,r3
  JMP[NE] @mth_trv_fail
  MOVI r1,1
  MOVI r9,0
  RET
mth_trv_fail:
  MOVI r1,0
  MOVI r9,1
  RET
