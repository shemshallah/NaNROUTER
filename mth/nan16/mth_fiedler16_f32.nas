; NaN16 approximate Fiedler feature extraction from a 16-vertex
; symmetric, nonnegative weighted graph W (no host eigensolver).
; Matrix W is a *relationship graph descriptor*, not an alternative
; representation of streamed head vectors. Physical pair root unchanged.
;
; Iteration: x0 centered to zero mean; repeat N steps:
;   y = (I - L/16)x, L=D-W, 0<=W<=1, zero diagonal;
;   center y, normalize by max_i |y_i|, x <- y/maxabs.
; With a connected graph, nonzero projection onto the second Laplacian
; eigenmode, an appropriate spectral gap and enough iterations, this
; converges toward a Fiedler direction. It is an approximation and DOES NOT
; certify convergence or handle degenerate/repeated zero eigenvalues.
; ABI (r13=1):
;   r1=W[256] float32, symmetric, diagonal zero, each weight in [0,1].
;   r2=x0[16] finite float32, preferably mean-zero contrast seed.
;   r3=iterations [1,64]; r4=out[16] float32; r5=scratch[32].
; Disjoint arrays; output atomic. r1=1/r9=0 success, else r1=0/r9=1.
; Caller then places the returned feature into its selected Laplacian
; eigenbasis column before mth_spectral_cut16_f32 if needed.
mth_fiedler16_f32:
  MOVI r0,0
  CMP r3,r0
  JMP[LE] @mth_f16_bad
  MOVI r6,64
  CMP r3,r6
  JMP[GT] @mth_f16_bad
  MOVI r14,0
  MOVHI r14,0x7F80
  MOVI r6,0
mth_f16_gate_x:
  ADD r7,r2,r6
  LD r7,r7,0
  BOOL.8 r8,r7,r14
  CMP r8,r14
  JMP[EQ] @mth_f16_bad
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_f16_gate_x
  MOVI r6,0
mth_f16_gate_row:
  MOVI r7,0
mth_f16_gate_col:
  SHL r8,r6,4
  ADD r8,r8,r7
  ADD r9,r1,r8
  LD r9,r9,0
  BOOL.8 r10,r9,r14
  CMP r10,r14
  JMP[EQ] @mth_f16_bad
  FCMP r9,r0
  JMP[LT] @mth_f16_bad
  MOVI r10,0
  MOVHI r10,0x3F80
  FCMP r9,r10
  JMP[GT] @mth_f16_bad
  CMP r6,r7
  JMP[NE] @mth_f16_sym
  FCMP r9,r0
  JMP[NE] @mth_f16_bad
mth_f16_sym:
  SHL r8,r7,4
  ADD r8,r8,r6
  ADD r10,r1,r8
  LD r10,r10,0
  CMP r9,r10
  JMP[NE] @mth_f16_bad
  ADDI r7,r7,1
  MOVI r8,16
  CMP r7,r8
  JMP[LT] @mth_f16_gate_col
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_f16_gate_row

  ; Center original input to eliminate the constant Laplacian eigenvector.
  MOVI r6,0
  MOVI r8,0
mth_f16_mean_input:
  ADD r7,r2,r6
  LD r7,r7,0
  FADD r8,r8,r7
  ADDI r6,r6,1
  MOVI r7,16
  CMP r6,r7
  JMP[LT] @mth_f16_mean_input
  MOVI r14,0
  MOVHI r14,0x3D80      ; tau=1/16
  FMUL r8,r8,r14
  MOVI r6,0
mth_f16_center_input:
  ADD r7,r2,r6
  LD r7,r7,0
  FSUB r7,r7,r8
  ADD r9,r5,r6
  ST r7,r9,0
  ADDI r6,r6,1
  MOVI r7,16
  CMP r6,r7
  JMP[LT] @mth_f16_center_input

  MOVI r6,0             ; iter
mth_f16_iteration:
  MOVI r7,0             ; i
  MOVI r14,0
  MOVHI r14,0x3D80      ; 1/16
mth_f16_row:
  ADD r9,r5,r7
  LD r9,r9,0            ; x_i
  MOVI r10,0            ; sum_j w_ij (x_i-x_j)
  MOVI r8,0             ; j
mth_f16_edge:
  SHL r11,r7,4
  ADD r11,r11,r8
  ADD r11,r1,r11
  LD r11,r11,0
  ADD r12,r5,r8
  LD r12,r12,0
  FSUB r12,r9,r12
  FMUL r12,r12,r11
  FADD r10,r10,r12
  ADDI r8,r8,1
  MOVI r11,16
  CMP r8,r11
  JMP[LT] @mth_f16_edge
  FMUL r10,r10,r14
  FSUB r9,r9,r10
  ADDI r12,r5,16
  ADD r12,r12,r7
  ST r9,r12,0
  ADDI r7,r7,1
  MOVI r11,16
  CMP r7,r11
  JMP[LT] @mth_f16_row

  ; Average y and check every intermediate for finiteness.
  MOVI r7,0
  MOVI r8,0
  MOVI r14,0
  MOVHI r14,0x7F80
mth_f16_mean_y:
  ADDI r11,r5,16
  ADD r11,r11,r7
  LD r11,r11,0
  BOOL.8 r12,r11,r14
  CMP r12,r14
  JMP[EQ] @mth_f16_bad
  FADD r8,r8,r11
  ADDI r7,r7,1
  MOVI r11,16
  CMP r7,r11
  JMP[LT] @mth_f16_mean_y
  MOVI r11,0
  MOVHI r11,0x3D80
  FMUL r8,r8,r11

  MOVI r7,0
  MOVI r9,0              ; maxabs
mth_f16_maxabs:
  ADDI r12,r5,16
  ADD r12,r12,r7
  LD r11,r12,0
  FSUB r11,r11,r8        ; remove residual constant mode
  ST r11,r12,0
  ADD r12,r11,r0
  FCMP r12,r0
  JMP[GE] @mth_f16_abs_ready
  FSUB r12,r0,r12
mth_f16_abs_ready:
  FCMP r12,r9
  JMP[LE] @mth_f16_max_next
  ADD r9,r12,r0
mth_f16_max_next:
  ADDI r7,r7,1
  MOVI r11,16
  CMP r7,r11
  JMP[LT] @mth_f16_maxabs
  FCMP r9,r0
  JMP[LE] @mth_f16_bad
  MOVI r7,0
mth_f16_normalize:
  ADDI r11,r5,16
  ADD r11,r11,r7
  LD r11,r11,0
  FDIV r11,r11,r9
  BOOL.8 r12,r11,r14
  CMP r12,r14
  JMP[EQ] @mth_f16_bad
  ADD r12,r5,r7
  ST r11,r12,0
  ADDI r7,r7,1
  MOVI r11,16
  CMP r7,r11
  JMP[LT] @mth_f16_normalize

  ADDI r6,r6,1
  CMP r6,r3
  JMP[LT] @mth_f16_iteration

  ; Public output only after all iterations have succeeded.
  MOVI r7,0
mth_f16_publish:
  ADD r8,r5,r7
  LD r8,r8,0
  ADD r9,r4,r7
  ST r8,r9,0
  ADDI r7,r7,1
  MOVI r8,16
  CMP r7,r8
  JMP[LT] @mth_f16_publish
  MOVI r1,1
  MOVI r9,0
  RET
mth_f16_bad:
  MOVI r1,0
  MOVI r9,1
  RET
