; Canonical NaN16 native approximate graph Fiedler mode and spectral-cut fixture.
; Two 8-node cliques connected by a weak undirected bridge (7,8).
; The graph is weighted and connected, so the slowest nonconstant mode
; separates the two communities. No host eigensolver provides U.
.org 0
JMP @mth_fi_main
.include "../nan16/mth_fiedler16_f32.nas"
.include "../nan16/mth_spectral_cut16_f32.nas"

mth_fi_main:
  MOVI r0,0
  MOVI r13,1
  MOVI r6,0                ; row i
  MOVI r10,0
  MOVHI r10,0x3F80         ; 1.0
  MOVI r11,0
  MOVHI r11,0xBF80         ; -1.0
mth_fi_seed:
  MOVI r12,8
  CMP r6,r12
  JMP[LT] @mth_fi_seed_left
  MOVI r12,@mth_fi_x
  ADD r12,r12,r6
  ST r11,r12,0
  JMP @mth_fi_seed_next
mth_fi_seed_left:
  MOVI r12,@mth_fi_x
  ADD r12,r12,r6
  ST r10,r12,0
mth_fi_seed_next:
  ADDI r6,r6,1
  MOVI r12,16
  CMP r6,r12
  JMP[LT] @mth_fi_seed
  ; W(i,j)=1 in each 8-clique, zero diagonal, zero across groups.
  MOVI r6,0
mth_fi_build_rows:
  MOVI r7,0
mth_fi_build_cols:
  CMP r6,r7
  JMP[EQ] @mth_fi_next_col
  MOVI r8,8
  CMP r6,r8
  JMP[LT] @mth_fi_i_first
  CMP r7,r8
  JMP[GE] @mth_fi_write
  JMP @mth_fi_next_col
mth_fi_i_first:
  CMP r7,r8
  JMP[GE] @mth_fi_next_col
mth_fi_write:
  SHL r9,r6,4
  ADD r9,r9,r7
  MOVI r12,@mth_fi_W
  ADD r12,r12,r9
  ST r10,r12,0
mth_fi_next_col:
  ADDI r7,r7,1
  MOVI r9,16
  CMP r7,r9
  JMP[LT] @mth_fi_build_cols
  ADDI r6,r6,1
  MOVI r9,16
  CMP r6,r9
  JMP[LT] @mth_fi_build_rows
  ; Weak symmetric bridge W(7,8)=W(8,7)=1/8
  MOVI r10,0
  MOVHI r10,0x3E00
  MOVI r11,@mth_fi_W
  ADDI r11,r11,120
  ST r10,r11,0
  MOVI r11,@mth_fi_W
  ADDI r11,r11,135
  ST r10,r11,0

  MOVI r1,@mth_fi_W
  MOVI r2,@mth_fi_x
  MOVI r3,48
  MOVI r4,@mth_fi_mode
  MOVI r5,@mth_fi_scratch
  CALL @mth_fiedler16_f32
  CMP r1,r13
  JMP[NE] @mth_fi_fail
  ; Community A positive, community B negative.
  LD r10,r0,@mth_fi_mode
  FCMP r10,r0
  JMP[LE] @mth_fi_fail
  LD r10,r0,@mth_fi_mode+15
  FCMP r10,r0
  JMP[GE] @mth_fi_fail

  ; Insert the calculated native mode in column 1 of the basis descriptor.
  MOVI r6,0
mth_fi_place_mode:
  MOVI r10,@mth_fi_mode
  ADD r10,r10,r6
  LD r10,r10,0
  SHL r11,r6,4
  ADDI r11,r11,1
  MOVI r12,@mth_fi_U
  ADD r12,r12,r11
  ST r10,r12,0
  ADDI r6,r6,1
  MOVI r10,16
  CMP r6,r10
  JMP[LT] @mth_fi_place_mode

  MOVI r1,@mth_fi_U
  MOVI r2,1
  MOVI r3,@mth_fi_labels
  MOVI r4,@mth_fi_cut_scratch
  MOVI r5,0
  CALL @mth_spectral_cut16_f32
  CMP r1,r13
  JMP[NE] @mth_fi_fail
  MOVI r10,8
  CMP r2,r10
  JMP[NE] @mth_fi_fail
  LD r10,r0,@mth_fi_labels
  CMP r10,r13
  JMP[NE] @mth_fi_fail
  LD r10,r0,@mth_fi_labels+15
  CMP r10,r0
  JMP[NE] @mth_fi_fail

  ; Invalid iterations must not change previous output mode.
  MOVI r1,@mth_fi_W
  MOVI r2,@mth_fi_x
  MOVI r3,0
  MOVI r4,@mth_fi_mode
  MOVI r5,@mth_fi_scratch
  CALL @mth_fiedler16_f32
  CMP r1,r0
  JMP[NE] @mth_fi_fail
  LD r10,r0,@mth_fi_mode
  FCMP r10,r0
  JMP[LE] @mth_fi_fail

  MOVI r1,@mth_fi_pass
  CALL @mth_fi_puts
  HALT
mth_fi_fail:
  MOVI r1,@mth_fi_bad
  CALL @mth_fi_puts
  HALT
mth_fi_puts:
  MOVI r4,255
mth_fi_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_fi_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_fi_puts_byte
  ADD r1,r1,r13
  JMP @mth_fi_puts_word
mth_fi_pass:
.str "MTH FIEDLER16 NATIVE PASS\n"
mth_fi_bad:
.str "MTH FIEDLER16 NATIVE FAIL\n"

.org 8192
mth_fi_x:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_fi_mode:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_fi_scratch:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_fi_labels:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_fi_cut_scratch:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.org 10000
mth_fi_W:
.word 0
.org 11000
mth_fi_U:
.word 0
