; Full-grid 256-tile pair-space driver fixture.
;
; L = 2I. For every tile, Y = L*U + U*L^T = 4U exactly. U is zero except
; for a small deterministic set of cells spread across tile boundaries. The
; fixture runs the full 16x16 tile grid, requires all 256 per-tile status
; words to be 1, and checks known nonzero and zero cells of the final Y.
;
; The oracle is integer-exact in float32: every staged U value is a small
; binary fraction, multiplied by 2 and added twice, so Y = 4U has no rounding
; ambiguity.
;
; Canonical run (nan0s worktree, nmk.awk CMD=emit):
;   nan_cli --img ... --steps 1000000000 --serial
; Observed: "MTH FULL GRID 256 TILE DRIVER PASS", 570,321,519 steps, rc=3
; (NAN_HALTED), pc=2180, trap=''. The image is 230,706 words, below the
; canonical 4,194,304-word VM. The older 50,000,000-step per-fixture budget
; is not sufficient: it stops at rc=0, pc=52, before the full grid completes.
; A 10,000,000-step cap stops even earlier, at rc=0, pc=49.

.org 0
JMP @mth_full_grid_test_main
.include "../nan16/mth_graph_pair_tile16_k16_f32.nas"
.include "../nan16/mth_graph_pair_tile16_k16_driver_f32.nas"
.include "../nan16/mth_graph_pair_full_grid_driver_f32.nas"

mth_full_grid_test_main:
  MOVI r13,1

  ; ---- L = 2I ----
  LA r1,@mth_full_grid_l
  MOVI r2,256
  MOVI r3,0
  MOVI r4,0
  MOVHI r4,0x4000          ; 2.0
  MOVI r5,257              ; next diagonal word: row stride 256 + 1
mth_full_grid_diag_loop:
  ST r4,r1,0
  ADD r1,r1,r5
  ADDI r3,r3,1
  CMP r3,r2
  JMP[LT] @mth_full_grid_diag_loop

  ; ---- U sparse deterministic cells ----
  ; [0,0] = 1.0
  LA r1,@mth_full_grid_u
  MOVI r2,0
  MOVI r3,0
  MOVHI r3,0x3F80
  CALL @mth_full_grid_store_word

  ; [1,2] = 2.5
  LA r1,@mth_full_grid_u
  MOVI r2,258
  MOVI r3,0
  MOVHI r3,0x4020
  CALL @mth_full_grid_store_word

  ; [15,15] = 0.5
  LA r1,@mth_full_grid_u
  MOVI r2,3855
  MOVI r3,0
  MOVHI r3,0x3F00
  CALL @mth_full_grid_store_word

  ; [16,16] = 1.5
  LA r1,@mth_full_grid_u
  MOVI r2,4112
  MOVI r3,0
  MOVHI r3,0x3FC0
  CALL @mth_full_grid_store_word

  ; [17,33] = 3.0
  LA r1,@mth_full_grid_u
  MOVI r2,4385
  MOVI r3,0
  MOVHI r3,0x4040
  CALL @mth_full_grid_store_word

  ; [31,47] = -2.0
  LA r1,@mth_full_grid_u
  MOVI r2,7983
  MOVI r3,0
  MOVHI r3,0xC000
  CALL @mth_full_grid_store_word

  ; [34,200] = 2.0
  LA r1,@mth_full_grid_u
  MOVI r2,8904
  MOVI r3,0
  MOVHI r3,0x4000
  CALL @mth_full_grid_store_word

  ; [128,7] = 0.25
  LA r1,@mth_full_grid_u
  MOVI r2,32775
  MOVI r3,0
  MOVHI r3,0x3E80
  CALL @mth_full_grid_store_word

  ; [200,201] = 4.0
  LA r1,@mth_full_grid_u
  MOVI r2,51401
  MOVI r3,0
  MOVHI r3,0x4080
  CALL @mth_full_grid_store_word

  ; [255,255] = 5.0
  LA r1,@mth_full_grid_u
  MOVI r2,65535
  MOVI r3,0
  MOVHI r3,0x40A0
  CALL @mth_full_grid_store_word

  ; ---- Run all 256 tiles ----
  LA r1,@mth_full_grid_l
  LA r2,@mth_full_grid_u
  LA r3,@mth_full_grid_y
  LA r4,@mth_full_grid_ws
  MOVI r13,1
  CALL @mth_graph_pair_full_grid_driver_f32
  MOVI r2,1
  CMP r1,r2
  JMP[NE] @mth_full_grid_test_fail

  ; ---- Every one of the 256 tile invocations must have returned 1 ----
  LA r1,@mth_full_grid_ws
  MOVI r2,17158
  ADD r1,r1,r2
  MOVI r2,256
  MOVI r3,0
mth_full_grid_status_loop:
  LD r4,r1,0
  MOVI r5,1
  CMP r4,r5
  JMP[NE] @mth_full_grid_test_fail
  ADD r1,r1,r13
  ADDI r3,r3,1
  CMP r3,r2
  JMP[LT] @mth_full_grid_status_loop

  ; ---- Check known output cells against Y = 4U ----
  LA r1,@mth_full_grid_cells
  MOVI r2,16
  MOVI r3,0
mth_full_grid_cell_loop:
  LD r4,r1,0               ; expected word index
  LD r5,r1,1               ; expected float bits
  LA r6,@mth_full_grid_y
  ADD r6,r6,r4
  LD r7,r6,0
  CMP r7,r5
  JMP[NE] @mth_full_grid_test_fail
  ADDI r1,r1,2
  ADDI r3,r3,1
  CMP r3,r2
  JMP[LT] @mth_full_grid_cell_loop

  LA r1,@mth_full_grid_test_pass
  CALL @mth_full_grid_test_puts
  HALT

mth_full_grid_test_fail:
  LA r1,@mth_full_grid_test_bad
  CALL @mth_full_grid_test_puts
  HALT

; Store one float word: r1=base, r2=word index, r3=value.
mth_full_grid_store_word:
  ADD r1,r1,r2
  ST r3,r1,0
  RET

mth_full_grid_test_puts:
  MOVI r4,255
mth_full_grid_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_full_grid_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_full_grid_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_full_grid_test_puts_word

; Full matrices and workspace. L, U, Y are 65,536 words each; the workspace
; is 17,414 words (status ends at workspace + 17,413).
.org 16384
mth_full_grid_l:
.org 81920
mth_full_grid_u:
.org 147456
mth_full_grid_y:
.org 212992
mth_full_grid_ws:
.org 230656
mth_full_grid_cells:
.word 0
.word 0x40800000           ; Y[0,0]   = 4.0
.word 258
.word 0x41200000           ; Y[1,2]   = 10.0
.word 3855
.word 0x40000000           ; Y[15,15] = 2.0
.word 4112
.word 0x40C00000           ; Y[16,16] = 6.0
.word 4385
.word 0x41400000           ; Y[17,33] = 12.0
.word 7983
.word 0xC1000000           ; Y[31,47] = -8.0
.word 8904
.word 0x41000000           ; Y[34,200] = 8.0
.word 32775
.word 0x3F800000           ; Y[128,7] = 1.0
.word 51401
.word 0x41800000           ; Y[200,201] = 16.0
.word 65535
.word 0x41A00000           ; Y[255,255] = 20.0
.word 1
.word 0                    ; Y[0,1] zero
.word 4096
.word 0                    ; Y[16,0] zero
.word 4113
.word 0                    ; Y[16,17] zero
.word 32776
.word 0                    ; Y[128,8] zero
.word 51400
.word 0                    ; Y[200,200] zero
.word 65534
.word 0                    ; Y[255,254] zero
.org 230688
mth_full_grid_test_pass:
.str "MTH FULL GRID 256 TILE DRIVER PASS\n"
mth_full_grid_test_bad:
.str "MTH FULL GRID 256 TILE DRIVER FAIL\n"
