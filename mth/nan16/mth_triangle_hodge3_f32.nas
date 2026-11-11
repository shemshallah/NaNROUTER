; Local oriented simplicial 1-form Hodge on one filled triangle A->B->C->A.
; f=(f_ab,f_bc,f_ca) binary32. Decompose f = grad + curl:
;   curl_e = (f_ab+f_bc+f_ca)/3 for each edge,
;   grad_e = f_e - curl_e;
;   divergence_v=(f_ab-f_ca, f_bc-f_ab, f_ca-f_bc).
; For one filled K3 triangle the harmonic 1-form is identically zero.
; ABI r1=flow[3] r2=out[9] r3=scratch[9], all disjoint word arrays.
; out[0..2]=gradient, [3..5]=triangle curl, [6..8]=divergence.
; Preserves r2,r3,r13,r15, r13=1, returns r1=1/0 r9=0/1.
; Preflight and scratch-based finite check leave output atomic.
mth_triangle_hodge3_f32:
  MOVI r0,0
  MOVI r14,0
  MOVHI r14,0x7F80
  MOVI r4,0
mth_th3_gate:
  ADD r5,r1,r4
  LD r5,r5,0
  BOOL.8 r10,r5,r14
  CMP r10,r14
  JMP[EQ] @mth_th3_bad
  ADDI r4,r4,1
  MOVI r10,3
  CMP r4,r10
  JMP[LT] @mth_th3_gate
  LD r6,r1,0
  LD r7,r1,1
  LD r8,r1,2
  FADD r9,r6,r7
  FADD r9,r9,r8
  MOVI r10,0xAAAB
  MOVHI r10,0x3EAA
  FMUL r9,r9,r10
  FSUB r11,r6,r9
  ST r11,r3,0
  FSUB r11,r7,r9
  ST r11,r3,1
  FSUB r11,r8,r9
  ST r11,r3,2
  ST r9,r3,3
  ST r9,r3,4
  ST r9,r3,5
  FSUB r11,r6,r8
  ST r11,r3,6
  FSUB r11,r7,r6
  ST r11,r3,7
  FSUB r11,r8,r7
  ST r11,r3,8
  MOVI r4,0
mth_th3_scratch_gate:
  ADD r5,r3,r4
  LD r5,r5,0
  BOOL.8 r10,r5,r14
  CMP r10,r14
  JMP[EQ] @mth_th3_bad
  ADDI r4,r4,1
  MOVI r10,9
  CMP r4,r10
  JMP[LT] @mth_th3_scratch_gate
  MOVI r4,0
mth_th3_publish:
  ADD r5,r3,r4
  LD r5,r5,0
  ADD r10,r2,r4
  ST r5,r10,0
  ADDI r4,r4,1
  MOVI r10,9
  CMP r4,r10
  JMP[LT] @mth_th3_publish
  MOVI r9,0
  MOVI r1,1
  RET
mth_th3_bad:
  MOVI r9,1
  MOVI r1,0
  RET
