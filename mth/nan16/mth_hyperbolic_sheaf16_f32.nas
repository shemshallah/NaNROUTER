; NaN16 oriented sheaf-edge discrepancy, scaled by Poincare pair affinity.
; This is a linear sheaf restriction-map coboundary with two independent
; directed lanes. It is NOT exact Levi-Civita parallel transport.
; out[i] = alpha*( sum_j R_ab[i,j]*x_a[j] - sum_j R_ba[i,j]*x_b[j] ).
; alpha is a binary32 score in [0,1], e.g. mth_poincare_pair2_f32 output[1].
; ABI r1=x_a[16], r2=x_b[16], r3=R_ab[256], r4=R_ba[256],
;     r5=alpha f32 bits, r6=out[16], r7=scratch[16] word addresses.
; No overlap among arrays. r13=1; r1=1/0,r9=0/1 success/reject.
; Finite preflight + staged outputs for atomic reject; no root mutation.
mth_hyperbolic_sheaf16_f32:
  MOVI r0,0
  MOVI r14,0
  MOVHI r14,0x7F80
  BOOL.8 r8,r5,r14
  CMP r8,r14
  JMP[EQ] @mth_hs16_bad
  FCMP r5,r0
  JMP[LT] @mth_hs16_bad
  MOVI r8,0
  MOVHI r8,0x3F80
  FCMP r5,r8
  JMP[GT] @mth_hs16_bad
  MOVI r8,0
mth_hs16_preflight_x:
  ADD r9,r1,r8
  LD r9,r9,0
  BOOL.8 r10,r9,r14
  CMP r10,r14
  JMP[EQ] @mth_hs16_bad
  ADD r9,r2,r8
  LD r9,r9,0
  BOOL.8 r10,r9,r14
  CMP r10,r14
  JMP[EQ] @mth_hs16_bad
  ADDI r8,r8,1
  MOVI r9,16
  CMP r8,r9
  JMP[LT] @mth_hs16_preflight_x
  MOVI r8,0
mth_hs16_preflight_maps:
  ADD r9,r3,r8
  LD r9,r9,0
  BOOL.8 r10,r9,r14
  CMP r10,r14
  JMP[EQ] @mth_hs16_bad
  ADD r9,r4,r8
  LD r9,r9,0
  BOOL.8 r10,r9,r14
  CMP r10,r14
  JMP[EQ] @mth_hs16_bad
  ADDI r8,r8,1
  MOVI r9,256
  CMP r8,r9
  JMP[LT] @mth_hs16_preflight_maps

  MOVI r8,0                   ; row i
mth_hs16_row:
  MOVI r10,0                  ; sum_ab
  MOVI r11,0                  ; sum_ba
  MOVI r9,0                   ; col j
mth_hs16_col:
  SHL r12,r8,4
  ADD r12,r12,r9
  ADD r14,r3,r12
  LD r14,r14,0
  ADD r12,r1,r9
  LD r12,r12,0
  FMUL r14,r14,r12
  FADD r10,r10,r14
  SHL r12,r8,4
  ADD r12,r12,r9
  ADD r14,r4,r12
  LD r14,r14,0
  ADD r12,r2,r9
  LD r12,r12,0
  FMUL r14,r14,r12
  FADD r11,r11,r14
  ADDI r9,r9,1
  MOVI r12,16
  CMP r9,r12
  JMP[LT] @mth_hs16_col
  FSUB r12,r10,r11
  FMUL r12,r12,r5
  ADD r14,r7,r8
  ST r12,r14,0
  ADDI r8,r8,1
  MOVI r12,16
  CMP r8,r12
  JMP[LT] @mth_hs16_row

  MOVI r14,0
  MOVHI r14,0x7F80
  MOVI r8,0
mth_hs16_check:
  ADD r9,r7,r8
  LD r9,r9,0
  BOOL.8 r10,r9,r14
  CMP r10,r14
  JMP[EQ] @mth_hs16_bad
  ADDI r8,r8,1
  MOVI r9,16
  CMP r8,r9
  JMP[LT] @mth_hs16_check
  MOVI r8,0
mth_hs16_publish:
  ADD r9,r7,r8
  LD r9,r9,0
  ADD r10,r6,r8
  ST r9,r10,0
  ADDI r8,r8,1
  MOVI r9,16
  CMP r8,r9
  JMP[LT] @mth_hs16_publish
  MOVI r1,1
  MOVI r9,0
  RET
mth_hs16_bad:
  MOVI r1,0
  MOVI r9,1
  RET
