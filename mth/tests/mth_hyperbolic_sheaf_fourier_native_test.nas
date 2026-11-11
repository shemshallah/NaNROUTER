; Native NaN16 hyperbolically gated sheaf and graph-Fourier fixture.
.org 0
JMP @mth_hf_main
.include "../nan16/mth_hyperbolic_sheaf16_f32.nas"
.include "../nan16/mth_graph_fourier16_f32.nas"
mth_hf_main:
  MOVI r0,0
  MOVI r13,1
  MOVI r6,0
  MOVI r10,0
  MOVHI r10,0x3F80       ; 1.0
mth_hf_init_vectors:
  MOVI r11,@mth_hf_x
  ADD r11,r11,r6
  ST r10,r11,0
  ADDI r6,r6,1
  MOVI r12,16
  CMP r6,r12
  JMP[LT] @mth_hf_init_vectors
  ; Identity sheaf maps and orthonormal eigenbasis (edgeless graph).
  MOVI r6,0
mth_hf_init_basis:
  SHL r7,r6,4
  ADD r7,r7,r6
  MOVI r11,@mth_hf_ra
  ADD r11,r11,r7
  ST r10,r11,0
  MOVI r11,@mth_hf_rb
  ADD r11,r11,r7
  ST r10,r11,0
  MOVI r11,@mth_hf_U
  ADD r11,r11,r7
  ST r10,r11,0
  ADDI r6,r6,1
  MOVI r12,16
  CMP r6,r12
  JMP[LT] @mth_hf_init_basis
  ; x=1, y=0, alpha=1/2: sheaf discrepancy vector is 1/2.
  MOVI r1,@mth_hf_x
  MOVI r2,@mth_hf_y
  MOVI r3,@mth_hf_ra
  MOVI r4,@mth_hf_rb
  MOVI r5,0
  MOVHI r5,0x3F00
  MOVI r6,@mth_hf_sheaf_out
  MOVI r7,@mth_hf_sheaf_scratch
  CALL @mth_hyperbolic_sheaf16_f32
  CMP r1,r13
  JMP[NE] @mth_hf_fail
  MOVI r10,0
  MOVHI r10,0x3F00
  LD r11,r0,@mth_hf_sheaf_out
  CMP r11,r10
  JMP[NE] @mth_hf_fail
  LD r11,r0,@mth_hf_sheaf_out+15
  CMP r11,r10
  JMP[NE] @mth_hf_fail

  ; Directed restriction: y0=1, R_ba[0,0]=2 -> first result -1/2,
  ; other features still +1/2.
  MOVI r10,0
  MOVHI r10,0x3F80
  ST r10,r0,@mth_hf_y
  MOVI r10,0
  MOVHI r10,0x4000
  ST r10,r0,@mth_hf_rb
  MOVI r1,@mth_hf_x
  MOVI r2,@mth_hf_y
  MOVI r3,@mth_hf_ra
  MOVI r4,@mth_hf_rb
  MOVI r5,0
  MOVHI r5,0x3F00
  MOVI r6,@mth_hf_sheaf_out
  MOVI r7,@mth_hf_sheaf_scratch
  CALL @mth_hyperbolic_sheaf16_f32
  CMP r1,r13
  JMP[NE] @mth_hf_fail
  MOVI r10,0
  MOVHI r10,0xBF00
  LD r11,r0,@mth_hf_sheaf_out
  CMP r11,r10
  JMP[NE] @mth_hf_fail

  ; Alpha > 1 rejected; saved directional output remains negative.
  MOVI r1,@mth_hf_x
  MOVI r2,@mth_hf_y
  MOVI r3,@mth_hf_ra
  MOVI r4,@mth_hf_rb
  MOVI r5,0
  MOVHI r5,0x4000
  MOVI r6,@mth_hf_sheaf_out
  MOVI r7,@mth_hf_sheaf_scratch
  CALL @mth_hyperbolic_sheaf16_f32
  CMP r1,r0
  JMP[NE] @mth_hf_fail
  MOVI r10,0
  MOVHI r10,0xBF00
  LD r11,r0,@mth_hf_sheaf_out
  CMP r11,r10
  JMP[NE] @mth_hf_fail

  ; U=I is a valid eigenbasis for zero graph Laplacian.
  ; Graph Fourier of all-ones is all-ones, inverse exact.
  MOVI r1,@mth_hf_U
  MOVI r2,@mth_hf_x
  MOVI r3,@mth_hf_spectrum
  MOVI r4,@mth_hf_recon
  MOVI r5,@mth_hf_fourier_scratch
  CALL @mth_graph_fourier16_f32
  CMP r1,r13
  JMP[NE] @mth_hf_fail
  MOVI r10,0
  MOVHI r10,0x3F80
  LD r11,r0,@mth_hf_spectrum
  CMP r11,r10
  JMP[NE] @mth_hf_fail
  LD r11,r0,@mth_hf_spectrum+15
  CMP r11,r10
  JMP[NE] @mth_hf_fail
  LD r11,r0,@mth_hf_recon
  CMP r11,r10
  JMP[NE] @mth_hf_fail

  ; Nonfinite basis preflight rejects without changing output spectrum.
  MOVI r10,0
  MOVHI r10,0x7FC0
  ST r10,r0,@mth_hf_U
  MOVI r1,@mth_hf_U
  MOVI r2,@mth_hf_x
  MOVI r3,@mth_hf_spectrum
  MOVI r4,@mth_hf_recon
  MOVI r5,@mth_hf_fourier_scratch
  CALL @mth_graph_fourier16_f32
  CMP r1,r0
  JMP[NE] @mth_hf_fail
  MOVI r10,0
  MOVHI r10,0x3F80
  LD r11,r0,@mth_hf_spectrum
  CMP r11,r10
  JMP[NE] @mth_hf_fail

  MOVI r1,@mth_hf_pass
  CALL @mth_hf_puts
  HALT
mth_hf_fail:
  MOVI r1,@mth_hf_bad
  CALL @mth_hf_puts
  HALT
mth_hf_puts:
  MOVI r4,255
mth_hf_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_hf_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_hf_puts_byte
  ADD r1,r1,r13
  JMP @mth_hf_puts_word
mth_hf_pass:
.str "MTH HYPERBOLIC SHEAF FOURIER PASS\n"
mth_hf_bad:
.str "MTH HYPERBOLIC SHEAF FOURIER FAIL\n"

.org 8192
mth_hf_x:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_hf_y:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_hf_sheaf_out:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_hf_sheaf_scratch:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_hf_spectrum:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_hf_recon:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_hf_fourier_scratch:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.org 9000
mth_hf_ra:
.word 0
.org 10000
mth_hf_rb:
.word 0
.org 11000
mth_hf_U:
.word 0
