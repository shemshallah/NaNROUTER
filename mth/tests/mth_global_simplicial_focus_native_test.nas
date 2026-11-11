; NaN16 global hot/cold focal attention and 16-node spectral-scale fixture.
.org 0
JMP @mth_gs_main
.include "../nan16/mth_global_focus16_f32.nas"
.include "../nan16/mth_graph_wavelet16_f32.nas"

mth_gs_main:
  MOVI r0,0
  MOVI r13,1
  ; Score all zero. Only candidate 0 active -> output value0=2.
  MOVI r10,0
  MOVHI r10,0x4000          ; 2.0
  ST r10,r0,@mth_gs_values
  MOVI r10,0
  MOVHI r10,0x4080          ; 4.0
  MOVI r11,@mth_gs_values
  ADDI r11,r11,16
  ST r10,r11,0
  MOVI r1,@mth_gs_scores
  MOVI r2,1
  MOVI r3,@mth_gs_values
  MOVI r4,@mth_gs_focus_out
  MOVI r5,@mth_gs_focus_scratch
  CALL @mth_global_focus16_f32
  CMP r1,r13
  JMP[NE] @mth_gs_fail
  MOVI r10,0
  MOVHI r10,0x4000
  LD r11,r0,@mth_gs_focus_out
  CMP r11,r10
  JMP[NE] @mth_gs_fail
  ; Equal scores, first two active => mean of 2 and 4 = 3.
  MOVI r1,@mth_gs_scores
  MOVI r2,3
  MOVI r3,@mth_gs_values
  MOVI r4,@mth_gs_focus_out
  MOVI r5,@mth_gs_focus_scratch
  CALL @mth_global_focus16_f32
  CMP r1,r13
  JMP[NE] @mth_gs_fail
  MOVI r10,0
  MOVHI r10,0x4040
  LD r11,r0,@mth_gs_focus_out
  CMP r11,r10
  JMP[NE] @mth_gs_fail
  ; Zero support rejects and preserves 3.0.
  MOVI r1,@mth_gs_scores
  MOVI r2,0
  MOVI r3,@mth_gs_values
  MOVI r4,@mth_gs_focus_out
  MOVI r5,@mth_gs_focus_scratch
  CALL @mth_global_focus16_f32
  CMP r1,r0
  JMP[NE] @mth_gs_fail
  MOVI r10,2
  CMP r9,r10
  JMP[NE] @mth_gs_fail
  MOVI r10,0
  MOVHI r10,0x4040
  LD r11,r0,@mth_gs_focus_out
  CMP r11,r10
  JMP[NE] @mth_gs_fail

  ; 16-node weighted graph with exactly one undirected 0-1 edge.
  MOVI r10,0
  MOVHI r10,0x3F80
  MOVI r11,@mth_gs_weights
  ST r10,r11,1            ; W(0,1)
  ADDI r11,r11,16
  ST r10,r11,0            ; W(1,0)
  ST r10,r0,@mth_gs_signal
  ; tau=1/16 -> smooth0=15/16, smooth1=1/16.
  MOVI r1,@mth_gs_weights
  MOVI r2,@mth_gs_signal
  MOVI r3,0
  MOVHI r3,0x3D80
  MOVI r4,@mth_gs_wave_out
  MOVI r5,@mth_gs_wave_scratch
  CALL @mth_graph_wavelet16_f32
  CMP r1,r13
  JMP[NE] @mth_gs_fail
  MOVI r10,0
  MOVHI r10,0x3F70
  LD r11,r0,@mth_gs_wave_out
  CMP r11,r10
  JMP[NE] @mth_gs_fail
  MOVI r10,0
  MOVHI r10,0x3D80
  LD r11,r0,@mth_gs_wave_out+1
  CMP r11,r10
  JMP[NE] @mth_gs_fail
  LD r11,r0,@mth_gs_wave_out+16
  CMP r11,r10
  JMP[NE] @mth_gs_fail
  MOVI r10,0
  MOVHI r10,0xBD80
  LD r11,r0,@mth_gs_wave_out+17
  CMP r11,r10
  JMP[NE] @mth_gs_fail

  ; Reject asymmetric adjacency before any output writes.
  MOVI r10,@mth_gs_weights
  ADDI r10,r10,16
  ST r0,r10,0
  MOVI r1,@mth_gs_weights
  MOVI r2,@mth_gs_signal
  MOVI r3,0
  MOVHI r3,0x3D80
  MOVI r4,@mth_gs_wave_out
  MOVI r5,@mth_gs_wave_scratch
  CALL @mth_graph_wavelet16_f32
  CMP r1,r0
  JMP[NE] @mth_gs_fail
  MOVI r10,0
  MOVHI r10,0x3F70
  LD r11,r0,@mth_gs_wave_out
  CMP r11,r10
  JMP[NE] @mth_gs_fail

  MOVI r1,@mth_gs_pass
  CALL @mth_gs_puts
  HALT
mth_gs_fail:
  MOVI r1,@mth_gs_bad
  CALL @mth_gs_puts
  HALT
mth_gs_puts:
  MOVI r4,255
mth_gs_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_gs_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_gs_puts_byte
  ADD r1,r1,r13
  JMP @mth_gs_puts_word
mth_gs_pass:
.str "MTH GLOBAL SIMPLICIAL FOCUS PASS\n"
mth_gs_bad:
.str "MTH GLOBAL SIMPLICIAL FOCUS FAIL\n"

.org 8192
mth_gs_scores:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_gs_focus_out:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_gs_signal:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_gs_wave_out:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_gs_wave_scratch:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.org 9000
mth_gs_values:
.word 0
.org 10000
mth_gs_focus_scratch:
.word 0
.org 11000
mth_gs_weights:
.word 0
