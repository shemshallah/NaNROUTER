; NaN16 graph-Fourier analysis and synthesis for 16 heads/triheads.
; Given an upstream validated orthonormal eigenbasis U of a chosen
; 16-node graph's Laplacian, compute:
; spectrum[k] = sum_i U[i,k]*x[i]
; recovered[i] = sum_k U[i,k]*spectrum[k].
; NO host projection, NO matrix manufactured from head vectors.
; This does not calculate U or verify it diagonalizes the selected L:
; eigenbasis provenance and eigenvalue ordering MUST be external contract.
; ABI r1=U[16][16] row-major float32, r2=x[16],
;     r3=spectrum[16], r4=reconstructed[16], r5=scratch[32]
; (scratch[0..15]=frequency, [16..31]=reconstructed).
; All arrays disjoint; all input and output elements finite or reject before
; publication. r13=1; r1=1/0, r9=0/1. No CALL/host math/physical root write.
mth_graph_fourier16_f32:
  MOVI r0,0
  MOVI r14,0
  MOVHI r14,0x7F80
  MOVI r6,0
mth_gft16_preflight:
  ADD r7,r1,r6
  LD r7,r7,0
  BOOL.8 r8,r7,r14
  CMP r8,r14
  JMP[EQ] @mth_gft16_bad
  ADDI r6,r6,1
  MOVI r8,256
  CMP r6,r8
  JMP[LT] @mth_gft16_preflight
  MOVI r6,0
mth_gft16_preflight_x:
  ADD r7,r2,r6
  LD r7,r7,0
  BOOL.8 r8,r7,r14
  CMP r8,r14
  JMP[EQ] @mth_gft16_bad
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_gft16_preflight_x
  MOVI r6,0                      ; freq k
mth_gft16_frequency:
  MOVI r7,0                     ; input i
  MOVI r8,0                     ; acc
mth_gft16_sample:
  SHL r9,r7,4
  ADD r9,r9,r6
  ADD r10,r1,r9
  LD r10,r10,0
  ADD r11,r2,r7
  LD r11,r11,0
  FMUL r10,r10,r11
  FADD r8,r8,r10
  ADDI r7,r7,1
  MOVI r9,16
  CMP r7,r9
  JMP[LT] @mth_gft16_sample
  ADD r10,r5,r6
  ST r8,r10,0
  ADDI r6,r6,1
  MOVI r9,16
  CMP r6,r9
  JMP[LT] @mth_gft16_frequency
  MOVI r6,0                      ; vertex i
mth_gft16_reconstruction:
  MOVI r7,0                     ; frequency k
  MOVI r8,0
mth_gft16_mix:
  SHL r9,r6,4
  ADD r9,r9,r7
  ADD r10,r1,r9
  LD r10,r10,0
  ADD r11,r5,r7
  LD r11,r11,0
  FMUL r10,r10,r11
  FADD r8,r8,r10
  ADDI r7,r7,1
  MOVI r9,16
  CMP r7,r9
  JMP[LT] @mth_gft16_mix
  ADDI r10,r5,16
  ADD r10,r10,r6
  ST r8,r10,0
  ADDI r6,r6,1
  MOVI r9,16
  CMP r6,r9
  JMP[LT] @mth_gft16_reconstruction
  MOVI r6,0
mth_gft16_gate:
  ADD r7,r5,r6
  LD r7,r7,0
  BOOL.8 r8,r7,r14
  CMP r8,r14
  JMP[EQ] @mth_gft16_bad
  ADDI r6,r6,1
  MOVI r8,32
  CMP r6,r8
  JMP[LT] @mth_gft16_gate
  MOVI r6,0
mth_gft16_publish:
  ADD r7,r5,r6
  LD r7,r7,0
  ADD r8,r3,r6
  ST r7,r8,0
  ADDI r7,r5,16
  ADD r7,r7,r6
  LD r7,r7,0
  ADD r8,r4,r6
  ST r7,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_gft16_publish
  MOVI r1,1
  MOVI r9,0
  RET
mth_gft16_bad:
  MOVI r1,0
  MOVI r9,1
  RET
