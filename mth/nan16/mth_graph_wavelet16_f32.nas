; 16-node weighted-graph explicit diffusion and one-scale wavelet detail.
; A symmetric nonnegative 16x16 graph W with weights in [0,1],
; zero diagonal. No matrix is formed from vectors: W is a separate
; existing *relationship* descriptor, input to a spectral operator.
; Lx[i] = sum_j W_ij*(x_i-x_j), y=x-tau*Lx, detail=x-y.
; For max degree <=15 and tau<=1/16, explicit Euler step is
; nonnegative row-stochastic (all row coefficients nonnegative).
; ABI: r1=W[256] row-major, r2=x[16], r3=tau bits binary32,
;   r4=out[32] [smooth[16],detail[16]], r5=scratch[32],
;   all spans disjoint; r13=1.
; Source finite, W symmetric, diagonal zero and 0<=W<=1 required.
; Nonfinite arithmetic rejects before publication. r1=1/0, r9=0/1.
; This is a graph wavelet *scale* and NOT a graph Fourier eigenbasis
; or a spectral clustering algorithm.
mth_graph_wavelet16_f32:
  MOVI r0,0
  MOVI r14,0
  MOVHI r14,0x7F80
  BOOL.8 r6,r3,r14
  CMP r6,r14
  JMP[EQ] @mth_gw16_bad
  FCMP r3,r0
  JMP[LT] @mth_gw16_bad
  MOVI r7,0
  MOVHI r7,0x3D80       ; tau<=1/16
  FCMP r3,r7
  JMP[GT] @mth_gw16_bad
  MOVI r6,0
  MOVI r7,0
  MOVHI r7,0x3F80       ; 1.0
mth_gw16_gate_x:
  ADD r8,r2,r6
  LD r8,r8,0
  BOOL.8 r9,r8,r14
  CMP r9,r14
  JMP[EQ] @mth_gw16_bad
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_gw16_gate_x
  MOVI r6,0              ; i
mth_gw16_gate_row:
  MOVI r8,0              ; j
mth_gw16_gate_col:
  SHL r9,r6,4
  ADD r9,r9,r8
  ADD r10,r1,r9
  LD r10,r10,0
  BOOL.8 r11,r10,r14
  CMP r11,r14
  JMP[EQ] @mth_gw16_bad
  FCMP r10,r0
  JMP[LT] @mth_gw16_bad
  FCMP r10,r7
  JMP[GT] @mth_gw16_bad
  CMP r6,r8
  JMP[NE] @mth_gw16_check_sym
  FCMP r10,r0
  JMP[NE] @mth_gw16_bad
mth_gw16_check_sym:
  SHL r11,r8,4
  ADD r11,r11,r6
  ADD r11,r1,r11
  LD r11,r11,0
  CMP r10,r11             ; exact bitwise symmetry
  JMP[NE] @mth_gw16_bad
  ADDI r8,r8,1
  MOVI r9,16
  CMP r8,r9
  JMP[LT] @mth_gw16_gate_col
  ADDI r6,r6,1
  MOVI r9,16
  CMP r6,r9
  JMP[LT] @mth_gw16_gate_row

  MOVI r6,0
mth_gw16_row:
  ADD r7,r2,r6
  LD r7,r7,0               ; x_i
  MOVI r8,0                ; j
  MOVI r9,0                ; Laplace accumulator
mth_gw16_edge:
  SHL r10,r6,4
  ADD r10,r10,r8
  ADD r10,r1,r10
  LD r10,r10,0             ; weight
  ADD r11,r2,r8
  LD r11,r11,0
  FSUB r11,r7,r11
  FMUL r11,r11,r10
  FADD r9,r9,r11
  ADDI r8,r8,1
  MOVI r10,16
  CMP r8,r10
  JMP[LT] @mth_gw16_edge
  FMUL r10,r3,r9
  FSUB r11,r7,r10          ; smoothed
  FSUB r12,r7,r11          ; detail
  ADD r10,r5,r6
  ST r11,r10,0
  ADDI r10,r10,16
  ST r12,r10,0
  ADDI r6,r6,1
  MOVI r10,16
  CMP r6,r10
  JMP[LT] @mth_gw16_row
  MOVI r6,0
mth_gw16_gate_output:
  ADD r8,r5,r6
  LD r8,r8,0
  BOOL.8 r9,r8,r14
  CMP r9,r14
  JMP[EQ] @mth_gw16_bad
  ADDI r6,r6,1
  MOVI r10,32
  CMP r6,r10
  JMP[LT] @mth_gw16_gate_output
  MOVI r6,0
mth_gw16_publish:
  ADD r7,r5,r6
  LD r7,r7,0
  ADD r8,r4,r6
  ST r7,r8,0
  ADDI r6,r6,1
  MOVI r10,32
  CMP r6,r10
  JMP[LT] @mth_gw16_publish
  MOVI r1,1
  MOVI r9,0
  RET
mth_gw16_bad:
  MOVI r1,0
  MOVI r9,1
  RET
