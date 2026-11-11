; 16-triad global hot/cold reducer and spectrum-to-partition readout.
.org 0
JMP @mth_mc_main
.include "../nan16/mth_global_motif_reduce16.nas"
.include "../nan16/mth_spectral_cut16_f32.nas"
mth_mc_main:
  MOVI r0,0
  MOVI r13,1
  MOVI r10,@mth_mc_motifs
  MOVI r11,1
  ; t0 111
  ST r11,r10,0
  ST r11,r10,1
  ST r11,r10,2
  ; t1 110
  ST r11,r10,3
  ST r11,r10,4
  ; t3 100 (one hot, two known cold)
  ST r11,r10,9
  ; t4 ??? unknown, not cold
  MOVI r11,2
  ST r11,r10,12
  ST r11,r10,13
  ST r11,r10,14
  MOVI r1,@mth_mc_motifs
  MOVI r2,@mth_mc_flags
  MOVI r3,@mth_mc_summary
  MOVI r4,@mth_mc_scratch
  CALL @mth_global_motif_reduce16
  CMP r1,r13
  JMP[NE] @mth_mc_fail
  MOVI r10,1
  LD r11,r0,@mth_mc_summary
  CMP r11,r10
  JMP[NE] @mth_mc_fail
  MOVI r10,2
  LD r11,r0,@mth_mc_summary+1
  CMP r11,r10
  JMP[NE] @mth_mc_fail
  MOVI r10,12
  LD r11,r0,@mth_mc_summary+2
  CMP r11,r10
  JMP[NE] @mth_mc_fail
  MOVI r10,13
  LD r11,r0,@mth_mc_summary+3
  CMP r11,r10
  JMP[NE] @mth_mc_fail
  MOVI r10,1
  LD r11,r0,@mth_mc_summary+4
  CMP r11,r10
  JMP[NE] @mth_mc_fail
  MOVI r10,2
  LD r11,r0,@mth_mc_summary+5
  CMP r11,r10
  JMP[NE] @mth_mc_fail
  MOVI r10,3
  LD r11,r0,@mth_mc_flags
  CMP r11,r10
  JMP[NE] @mth_mc_fail
  MOVI r10,2
  LD r11,r0,@mth_mc_flags+1
  CMP r11,r10
  JMP[NE] @mth_mc_fail

  ; Invalid input rejects atomically; summary[0] remains 1.
  MOVI r10,3
  ST r10,r0,@mth_mc_motifs+12
  MOVI r1,@mth_mc_motifs
  MOVI r2,@mth_mc_flags
  MOVI r3,@mth_mc_summary
  MOVI r4,@mth_mc_scratch
  CALL @mth_global_motif_reduce16
  CMP r1,r0
  JMP[NE] @mth_mc_fail
  MOVI r10,1
  LD r11,r0,@mth_mc_summary
  CMP r11,r10
  JMP[NE] @mth_mc_fail

  ; Fiedler-column cut readout: one positive at vertex 1.
  MOVI r10,0
  MOVHI r10,0x3F80
  MOVI r11,@mth_mc_basis
  ADDI r11,r11,17       ; U[1,1]=1
  ST r10,r11,0
  MOVI r1,@mth_mc_basis
  MOVI r2,1
  MOVI r3,@mth_mc_labels
  MOVI r4,@mth_mc_cut_scratch
  MOVI r5,0             ; threshold=0
  CALL @mth_spectral_cut16_f32
  CMP r1,r13
  JMP[NE] @mth_mc_fail
  CMP r2,r13            ; one positive
  JMP[NE] @mth_mc_fail
  LD r10,r0,@mth_mc_labels+1
  CMP r10,r13
  JMP[NE] @mth_mc_fail
  LD r10,r0,@mth_mc_labels
  CMP r10,r0
  JMP[NE] @mth_mc_fail
  ; Column 2 is zero -> degenerate; output preserved.
  MOVI r1,@mth_mc_basis
  MOVI r2,2
  MOVI r3,@mth_mc_labels
  MOVI r4,@mth_mc_cut_scratch
  MOVI r5,0
  CALL @mth_spectral_cut16_f32
  CMP r1,r0
  JMP[NE] @mth_mc_fail
  MOVI r10,3
  CMP r9,r10
  JMP[NE] @mth_mc_fail
  LD r10,r0,@mth_mc_labels+1
  CMP r10,r13
  JMP[NE] @mth_mc_fail

  MOVI r1,@mth_mc_pass
  CALL @mth_mc_puts
  HALT
mth_mc_fail:
  MOVI r1,@mth_mc_bad
  CALL @mth_mc_puts
  HALT
mth_mc_puts:
  MOVI r4,255
mth_mc_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_mc_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_mc_puts_byte
  ADD r1,r1,r13
  JMP @mth_mc_puts_word
mth_mc_pass:
.str "MTH GLOBAL HOT COLD SPECTRAL PASS\n"
mth_mc_bad:
.str "MTH GLOBAL HOT COLD SPECTRAL FAIL\n"

.org 8192
mth_mc_motifs:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_mc_flags:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_mc_summary:
.word 0,0,0,0,0,0
mth_mc_scratch:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_mc_labels:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_mc_cut_scratch:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.org 9000
mth_mc_basis:
.word 0
