; Native 3-head simplicial triangle diffusion and one-scale detail.
; Input r1=x[3] vertex feature, r2=tau binary32 (0<=tau<=1/2),
; r3=out[6] [smooth3, detail3], r4=scratch[6] disjoint.
; K3 triangle Lx=3*x - sum(x); smooth=x-tau*Lx; detail=x-smooth.
; This is an explicit Euler diffusion/wavelet-detail primitive,
; NOT a full graph Fourier eigensolve or global spectral clustering.
; Finite-domain and output preflight, atomic publication.
; r13=1. r1=1,r9=0 success; r1=0,r9=1 reject.
mth_simplicial_wavelet3_f32:
  MOVI r0,0
  MOVI r14,0
  MOVHI r14,0x7F80
  BOOL.8 r5,r2,r14
  CMP r5,r14
  JMP[EQ] @mth_sw3_bad
  FCMP r2,r0
  JMP[LT] @mth_sw3_bad
  MOVI r5,0
  MOVHI r5,0x3F00       ; 1/2
  FCMP r2,r5
  JMP[GT] @mth_sw3_bad
  MOVI r6,0
  MOVI r5,0
mth_sw3_sum:
  ADD r7,r1,r6
  LD r7,r7,0
  BOOL.8 r8,r7,r14
  CMP r8,r14
  JMP[EQ] @mth_sw3_bad
  FADD r5,r5,r7
  ADDI r6,r6,1
  MOVI r8,3
  CMP r6,r8
  JMP[LT] @mth_sw3_sum
  MOVI r6,0
  MOVI r9,0
  MOVHI r9,0x4040       ; 3.0
mth_sw3_compute:
  ADD r7,r1,r6
  LD r7,r7,0
  FMUL r8,r7,r9
  FSUB r8,r8,r5        ; Lx[i]
  FMUL r10,r2,r8
  FSUB r11,r7,r10     ; smooth
  FSUB r12,r7,r11     ; detail
  ADD r8,r4,r6
  ST r11,r8,0
  ADDI r8,r8,3
  ST r12,r8,0
  ADDI r6,r6,1
  MOVI r8,3
  CMP r6,r8
  JMP[LT] @mth_sw3_compute
  MOVI r6,0
mth_sw3_check:
  ADD r7,r4,r6
  LD r7,r7,0
  BOOL.8 r8,r7,r14
  CMP r8,r14
  JMP[EQ] @mth_sw3_bad
  ADDI r6,r6,1
  MOVI r8,6
  CMP r6,r8
  JMP[LT] @mth_sw3_check
  MOVI r6,0
mth_sw3_publish:
  ADD r7,r4,r6
  LD r7,r7,0
  ADD r8,r3,r6
  ST r7,r8,0
  ADDI r6,r6,1
  MOVI r8,6
  CMP r6,r8
  JMP[LT] @mth_sw3_publish
  MOVI r9,0
  MOVI r1,1
  RET
mth_sw3_bad:
  MOVI r9,1
  MOVI r1,0
  RET
