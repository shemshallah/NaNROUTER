; End-to-end native NaN16 smoke/regression fixture.
; No host calculations: every tensor, motif, Hodge, geometry, and wavelet
; numeric result is computed by the included NaN16 guest routines.
.org 0
JMP @mth_hs_main
.include "../nan16/mth_hypertensor16_f32.nas"
.include "../nan16/mth_simplicial_motif3.nas"
.include "../nan16/mth_triangle_hodge3_f32.nas"
.include "../nan16/mth_poincare_pair2_f32.nas"
.include "../nan16/mth_simplicial_wavelet3_f32.nas"

mth_hs_main:
  MOVI r0,0
  MOVI r13,1
  ; Initialize A=1 B=2 C=3 for 16 features.
  MOVI r6,0
  MOVI r7,0
  MOVHI r7,0x3F80      ; 1.0
  MOVI r8,0
  MOVHI r8,0x4000      ; 2.0
  MOVI r9,0
  MOVHI r9,0x4040      ; 3.0
mth_hs_init_vec:
  MOVI r10,@mth_hs_a
  ADD r10,r10,r6
  ST r7,r10,0
  MOVI r10,@mth_hs_b
  ADD r10,r10,r6
  ST r8,r10,0
  MOVI r10,@mth_hs_c
  ADD r10,r10,r6
  ST r9,r10,0
  ADDI r6,r6,1
  MOVI r10,16
  CMP r6,r10
  JMP[LT] @mth_hs_init_vec

  ; Hypertensor has 4096 entries, not a 16x16 matrix.
  MOVI r1,@mth_hs_a
  MOVI r2,@mth_hs_b
  MOVI r3,@mth_hs_c
  MOVI r4,@mth_hs_tensor_out
  MOVI r5,@mth_hs_tensor_scratch
  CALL @mth_hypertensor16_f32
  CMP r1,r13
  JMP[NE] @mth_hs_fail
  MOVI r10,0
  MOVHI r10,0x40C0     ; 6.0
  LD r11,r0,@mth_hs_tensor_out
  CMP r11,r10
  JMP[NE] @mth_hs_fail
  MOVI r12,@mth_hs_tensor_out
  ADDI r12,r12,4095
  LD r11,r12,0
  CMP r11,r10
  JMP[NE] @mth_hs_fail

  ; NaN rejects atomically and does not mutate an existing tensor.
  MOVI r10,0
  MOVHI r10,0x7FC0
  ST r10,r0,@mth_hs_a
  MOVI r1,@mth_hs_a
  MOVI r2,@mth_hs_b
  MOVI r3,@mth_hs_c
  MOVI r4,@mth_hs_tensor_out
  MOVI r5,@mth_hs_tensor_scratch
  CALL @mth_hypertensor16_f32
  CMP r1,r0
  JMP[NE] @mth_hs_fail
  MOVI r10,1
  CMP r9,r10
  JMP[NE] @mth_hs_fail
  MOVI r10,0
  MOVHI r10,0x40C0
  LD r11,r0,@mth_hs_tensor_out
  CMP r11,r10
  JMP[NE] @mth_hs_fail
  MOVI r10,0
  MOVHI r10,0x3F80
  ST r10,r0,@mth_hs_a

  ; 2 hot + 1 cold is a supported two-of-three hotspot.
  MOVI r10,@mth_hs_edges
  MOVI r11,1
  ST r11,r10,0
  ST r11,r10,1
  ST r0,r10,2
  MOVI r1,@mth_hs_edges
  CALL @mth_simplicial_motif3
  CMP r1,r13
  JMP[NE] @mth_hs_fail
  MOVI r10,2
  CMP r2,r10
  JMP[NE] @mth_hs_fail
  CMP r3,r13
  JMP[NE] @mth_hs_fail
  CMP r4,r10
  JMP[NE] @mth_hs_fail

  ; 000 exactly: cold count 3, flags = (cold3|cold2)=12.
  MOVI r10,@mth_hs_edges
  ST r0,r10,0
  ST r0,r10,1
  ST r0,r10,2
  MOVI r1,@mth_hs_edges
  CALL @mth_simplicial_motif3
  MOVI r10,12
  CMP r4,r10
  JMP[NE] @mth_hs_fail

  ; 111 exactly: hot count 3, flags=3.
  MOVI r10,@mth_hs_edges
  ST r13,r10,0
  ST r13,r10,1
  ST r13,r10,2
  MOVI r1,@mth_hs_edges
  CALL @mth_simplicial_motif3
  MOVI r10,3
  CMP r4,r10
  JMP[NE] @mth_hs_fail

  ; Unknown is distinct from observed cold.
  MOVI r10,@mth_hs_edges
  MOVI r11,2
  ST r11,r10,2
  MOVI r1,@mth_hs_edges
  CALL @mth_simplicial_motif3
  CMP r2,r11
  JMP[NE] @mth_hs_fail
  CMP r3,r0
  JMP[NE] @mth_hs_fail
  CMP r4,r11
  JMP[NE] @mth_hs_fail
  CMP r5,r13
  JMP[NE] @mth_hs_fail

  ; Three constant oriented edge flows: curl=1, grad=0, div=0.
  MOVI r10,0
  MOVHI r10,0x3F80
  MOVI r11,@mth_hs_flow
  ST r10,r11,0
  ST r10,r11,1
  ST r10,r11,2
  MOVI r1,@mth_hs_flow
  MOVI r2,@mth_hs_hodge_out
  MOVI r3,@mth_hs_hodge_scratch
  CALL @mth_triangle_hodge3_f32
  CMP r1,r13
  JMP[NE] @mth_hs_fail
  LD r10,r0,@mth_hs_hodge_out
  CMP r10,r0
  JMP[NE] @mth_hs_fail
  LD r10,r0,@mth_hs_hodge_out+3
  MOVI r11,0
  MOVHI r11,0x3F80
  CMP r10,r11
  JMP[NE] @mth_hs_fail
  LD r10,r0,@mth_hs_hodge_out+6
  CMP r10,r0
  JMP[NE] @mth_hs_fail

  ; Poincare x=y=0 => cosh distance=1, affinity=1.
  MOVI r1,@mth_hs_disk_x
  MOVI r2,@mth_hs_disk_y
  MOVI r3,@mth_hs_disk_out
  CALL @mth_poincare_pair2_f32
  CMP r1,r13
  JMP[NE] @mth_hs_fail
  MOVI r10,0
  MOVHI r10,0x3F80
  LD r11,r0,@mth_hs_disk_out
  CMP r11,r10
  JMP[NE] @mth_hs_fail
  LD r11,r0,@mth_hs_disk_out+1
  CMP r11,r10
  JMP[NE] @mth_hs_fail

  ; Poincare (0,0)->(.5,0): cosh(d) in (1,2), affinity in (.5,1).
  MOVI r10,0
  MOVHI r10,0x3F00
  ST r10,r0,@mth_hs_disk_y
  MOVI r1,@mth_hs_disk_x
  MOVI r2,@mth_hs_disk_y
  MOVI r3,@mth_hs_disk_out
  CALL @mth_poincare_pair2_f32
  CMP r1,r13
  JMP[NE] @mth_hs_fail
  MOVI r10,0
  MOVHI r10,0x3F80
  LD r11,r0,@mth_hs_disk_out
  FCMP r11,r10
  JMP[LE] @mth_hs_fail
  MOVI r10,0
  MOVHI r10,0x4000
  FCMP r11,r10
  JMP[GE] @mth_hs_fail
  LD r11,r0,@mth_hs_disk_out+1
  MOVI r10,0
  MOVHI r10,0x3F00
  FCMP r11,r10
  JMP[LE] @mth_hs_fail
  MOVI r10,0
  MOVHI r10,0x3F80
  FCMP r11,r10
  JMP[GE] @mth_hs_fail

  ; Boundary ||y||=1 must reject without touching outputs.
  MOVI r10,0
  MOVHI r10,0x3F80
  ST r10,r0,@mth_hs_disk_y
  MOVI r1,@mth_hs_disk_x
  MOVI r2,@mth_hs_disk_y
  MOVI r3,@mth_hs_disk_out
  CALL @mth_poincare_pair2_f32
  CMP r1,r0
  JMP[NE] @mth_hs_fail
  MOVI r10,0
  MOVHI r10,0x3F00
  LD r11,r0,@mth_hs_disk_out+1
  FCMP r11,r10
  JMP[LE] @mth_hs_fail

  ; K3 diffusion: x=(1,0,0), tau=.25 => smooth=(.5,.25,.25)
  MOVI r10,0
  MOVHI r10,0x3F80
  ST r10,r0,@mth_hs_signal
  MOVI r1,@mth_hs_signal
  MOVI r2,0
  MOVHI r2,0x3E80
  MOVI r3,@mth_hs_wave_out
  MOVI r4,@mth_hs_wave_scratch
  CALL @mth_simplicial_wavelet3_f32
  CMP r1,r13
  JMP[NE] @mth_hs_fail
  MOVI r10,0
  MOVHI r10,0x3F00
  LD r11,r0,@mth_hs_wave_out
  CMP r11,r10
  JMP[NE] @mth_hs_fail
  LD r11,r0,@mth_hs_wave_out+3
  CMP r11,r10
  JMP[NE] @mth_hs_fail
  MOVI r10,0
  MOVHI r10,0x3E80
  LD r11,r0,@mth_hs_wave_out+1
  CMP r11,r10
  JMP[NE] @mth_hs_fail
  MOVI r10,0
  MOVHI r10,0xBE80
  LD r11,r0,@mth_hs_wave_out+4
  CMP r11,r10
  JMP[NE] @mth_hs_fail

  MOVI r1,@mth_hs_pass
  CALL @mth_hs_puts
  HALT
mth_hs_fail:
  MOVI r1,@mth_hs_bad
  CALL @mth_hs_puts
  HALT
mth_hs_puts:
  MOVI r4,255
mth_hs_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_hs_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_hs_puts_byte
  ADD r1,r1,r13
  JMP @mth_hs_puts_word

mth_hs_pass:
.str "MTH HYPERTENSOR SIMPLICIAL PASS\n"
mth_hs_bad:
.str "MTH HYPERTENSOR SIMPLICIAL FAIL\n"

.org 8192
mth_hs_a: .word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_hs_b: .word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_hs_c: .word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_hs_edges: .word 0,0,0
mth_hs_flow: .word 0,0,0
mth_hs_hodge_out: .word 0,0,0,0,0,0,0,0,0
mth_hs_hodge_scratch: .word 0,0,0,0,0,0,0,0,0
mth_hs_disk_x: .word 0,0
mth_hs_disk_y: .word 0,0
mth_hs_disk_out: .word 0,0
mth_hs_signal: .word 0,0,0
mth_hs_wave_out: .word 0,0,0,0,0,0
mth_hs_wave_scratch: .word 0,0,0,0,0,0

.org 12000
mth_hs_tensor_out: .word 0
.org 17000
mth_hs_tensor_scratch: .word 0
