; Native NaN16 connected pathway: hyperbolic geodesic affinity -> sheaf
; directional restriction -> streamed rank-3 hypertensor -> hot simplex
; and Hodge curl -> score -> masked global attention with tensor value.
; Demonstrates value propagation, not learned representations/gradients.
.org 0
JMP @mth_chain_main
.include "../nan16/mth_poincare_pair2_f32.nas"
.include "../nan16/mth_hyperbolic_sheaf16_f32.nas"
.include "../nan16/mth_hypertensor16_f32.nas"
.include "../nan16/mth_simplicial_motif3.nas"
.include "../nan16/mth_triangle_hodge3_f32.nas"
.include "../nan16/mth_global_focus16_f32.nas"
mth_chain_main:
  MOVI r0,0
  MOVI r13,1
  MOVI r10,0
  MOVHI r10,0x3F00       ; 0.5
  ST r10,r0,@mth_chain_ycoord
  MOVI r10,0
  MOVHI r10,0x3F80       ; 1.0
  MOVI r7,0
mth_chain_init_vec:
  MOVI r11,@mth_chain_x
  ADD r11,r11,r7
  ST r10,r11,0
  MOVI r11,@mth_chain_b
  ADD r11,r11,r7
  ST r10,r11,0
  MOVI r11,@mth_chain_c
  ADD r11,r11,r7
  ST r10,r11,0
  SHL r12,r7,4
  ADD r12,r12,r7
  MOVI r11,@mth_chain_ra
  ADD r11,r11,r12
  ST r10,r11,0
  MOVI r11,@mth_chain_rb
  ADD r11,r11,r12
  ST r10,r11,0
  ADDI r7,r7,1
  MOVI r11,16
  CMP r7,r11
  JMP[LT] @mth_chain_init_vec

  ; Poincare origin to (.5,0): alpha=1/cosh(d)=0.6
  MOVI r1,@mth_chain_xcoord
  MOVI r2,@mth_chain_ycoord
  MOVI r3,@mth_chain_geo
  CALL @mth_poincare_pair2_f32
  CMP r1,r13
  JMP[NE] @mth_chain_fail
  LD r5,r0,@mth_chain_geo+1
  MOVI r1,@mth_chain_x
  MOVI r2,@mth_chain_y
  MOVI r3,@mth_chain_ra
  MOVI r4,@mth_chain_rb
  MOVI r6,@mth_chain_a
  MOVI r7,@mth_chain_scratch
  CALL @mth_hyperbolic_sheaf16_f32
  CMP r1,r13
  JMP[NE] @mth_chain_fail

  ; T_ijk=A_i B_j C_k -> T_000=alpha (since B=C=1).
  MOVI r1,@mth_chain_a
  MOVI r2,@mth_chain_b
  MOVI r3,@mth_chain_c
  MOVI r4,@mth_chain_tensor
  MOVI r5,@mth_chain_tscratch
  CALL @mth_hypertensor16_f32
  CMP r1,r13
  JMP[NE] @mth_chain_fail
  LD r10,r0,@mth_chain_geo+1
  LD r11,r0,@mth_chain_tensor
  CMP r10,r11
  JMP[NE] @mth_chain_fail

  ; Three observed hot edges make a complete positive simplex.
  MOVI r10,1
  ST r10,r0,@mth_chain_edges
  ST r10,r0,@mth_chain_edges+1
  ST r10,r0,@mth_chain_edges+2
  MOVI r1,@mth_chain_edges
  CALL @mth_simplicial_motif3
  CMP r1,r13
  JMP[NE] @mth_chain_fail
  MOVI r10,3
  CMP r4,r10
  JMP[NE] @mth_chain_fail

  ; Oriented constant cycle -> local curl=1, gradient=0.
  MOVI r10,0
  MOVHI r10,0x3F80
  ST r10,r0,@mth_chain_flow
  ST r10,r0,@mth_chain_flow+1
  ST r10,r0,@mth_chain_flow+2
  MOVI r1,@mth_chain_flow
  MOVI r2,@mth_chain_hodge
  MOVI r3,@mth_chain_hscratch
  CALL @mth_triangle_hodge3_f32
  CMP r1,r13
  JMP[NE] @mth_chain_fail

  ; Form a global score in guest: motif flag 3 + curl 1 = float32 4.
  MOVI r10,3
  CVTIF r10,r10
  LD r11,r0,@mth_chain_hodge+3
  FADD r10,r10,r11
  ST r10,r0,@mth_chain_scores
  ; Embed the actual hypertensor feature as V[0,0].
  LD r10,r0,@mth_chain_tensor
  ST r10,r0,@mth_chain_values
  ; Focus on valid first triad: its value must survive exactly.
  MOVI r1,@mth_chain_scores
  MOVI r2,1
  MOVI r3,@mth_chain_values
  MOVI r4,@mth_chain_out
  MOVI r5,@mth_chain_fscratch
  CALL @mth_global_focus16_f32
  CMP r1,r13
  JMP[NE] @mth_chain_fail
  LD r10,r0,@mth_chain_geo+1
  LD r11,r0,@mth_chain_out
  CMP r10,r11
  JMP[NE] @mth_chain_fail

  MOVI r1,@mth_chain_pass
  CALL @mth_chain_puts
  HALT
mth_chain_fail:
  MOVI r1,@mth_chain_bad
  CALL @mth_chain_puts
  HALT
mth_chain_puts:
  MOVI r4,255
mth_chain_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_chain_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_chain_puts_byte
  ADD r1,r1,r13
  JMP @mth_chain_puts_word
mth_chain_pass:
.str "MTH CONNECTED HYPERTENSOR FOCUS PASS\n"
mth_chain_bad:
.str "MTH CONNECTED HYPERTENSOR FOCUS FAIL\n"

.org 8192
mth_chain_xcoord:
.word 0,0
mth_chain_ycoord:
.word 0,0
mth_chain_geo:
.word 0,0
mth_chain_x:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_chain_y:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_chain_a:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_chain_b:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_chain_c:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_chain_scratch:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_chain_edges:
.word 0,0,0
mth_chain_flow:
.word 0,0,0
mth_chain_hodge:
.word 0,0,0,0,0,0,0,0,0
mth_chain_hscratch:
.word 0,0,0,0,0,0,0,0,0
mth_chain_scores:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_chain_out:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0

.org 9000
mth_chain_ra:
.word 0
.org 10000
mth_chain_rb:
.word 0
.org 11000
mth_chain_values:
.word 0
.org 12000
mth_chain_fscratch:
.word 0
.org 16000
mth_chain_tensor:
.word 0
.org 21000
mth_chain_tscratch:
.word 0
