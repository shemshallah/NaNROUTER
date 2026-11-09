; MTH 255-head field gate — NaN16 float32 only.
;
; Softmax over exactly the 255 real heads, excluding NANNET0/ring 255:
;
;   score[255] = -inf padding sentinel
;   weight = softmax(score[0..254])
;
; ABI (r13=1):
;   r1 = score[255]
;   r2 = weight[255], written on success only
;   r3 = caller scratch, 258 words:
;        [0..255] padded softmax workspace, [256] out pointer, [257] return
;   r13 = 1
; Success: r1=1, r9=0.
; Rejection: r1=0, r9 is the 256-way softmax cause (1 NaN/+inf, 2 empty
; support). The output is untouched.

.include "mth_vector_softmax256_f32.nas"

mth_field_gate255_f32:
  MOVI r0,0
  ADD r6,r3,r0
  ST r2,r6,256
  ST r15,r6,257

  ; copy 255 scores and pad
  MOVI r7,0
mth_field_gate255_copy:
  ADD r8,r1,r7
  LD r8,r8,0
  ADD r9,r6,r7
  ST r8,r9,0
  ADDI r7,r7,1
  MOVI r8,255
  CMP r7,r8
  JMP[LT] @mth_field_gate255_copy
  MOVI r8,0
  MOVHI r8,0xFF80
  ST r8,r6,255

  ADD r1,r6,r0
  ADD r2,r6,r0
  CALL @mth_vector_softmax256_f32
  ADD r6,r2,r0               ; softmax preserves r2 as scratch base
  CMP r1,r13
  JMP[NE] @mth_field_gate255_reject

  LD r2,r6,256
  MOVI r7,0
mth_field_gate255_publish:
  ADD r8,r6,r7
  LD r9,r8,0
  ADD r8,r2,r7
  ST r9,r8,0
  ADDI r7,r7,1
  MOVI r8,255
  CMP r7,r8
  JMP[LT] @mth_field_gate255_publish

  LD r15,r6,257
  MOVI r1,1
  MOVI r9,0
  RET

mth_field_gate255_reject:
  LD r15,r6,257
  MOVI r1,0
  RET
