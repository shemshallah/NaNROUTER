; NaN16 full-grid driver for the dense 256x256 pair-space action.
;
; Iterates all 256 row-major 16x16 output tiles (tile index t = 16*i + j,
; i,j in 0..15), stages the four strips required by the existing one-tile
; driver, calls mth_graph_pair_tile16_k16_driver_f32 once per tile, and
; scatters the finalized 16x16 tile into the full row-major output Y.
;
; Y[i,j] = sum(k=0..255) L[i,k]*U[k,j] + sum(k=0..255) U[i,k]*L[j,k]
;
; The caller must link:
;   mth_graph_pair_tile16_k16_f32.nas       (accumulator + finalizer)
;   mth_graph_pair_tile16_k16_driver_f32.nas (one-tile 16-slice driver)
; into the same image. The one-tile driver owns words 400..411; this driver
; owns words 2048..2059. Keep code and data out of both ranges.
;
; ABI:
;   r1 = L full matrix base, 256x256 row-major float32, 65,536 words
;   r2 = U full matrix base, 256x256 row-major float32, 65,536 words
;   r3 = Y full output base, 256x256 row-major float32, 65,536 words
;   r4 = workspace base, at least 17,414 words (layout below)
;   r13 = 1
;
; Returns r1=1 only after all 256 tile invocations and scatters succeed.
; Returns r1=0 on the first tile failure, without invoking any later tile.
; A failed tile is not scattered into Y; tiles completed before it remain
; written. Callers must treat r1=0 as an invalid output.
;
; The four strip pointers passed to the one-tile driver keep that driver's
; exact ABI and strip layout: each strip is sixteen contiguous 256-word
; 16x16 K blocks in increasing global-K order.
;
; Workspace layout (word offsets from r4):
;   0..4095       L_IK packed strip
;   4096..8191    U_KJ packed strip
;   8192..12287   U_IK packed strip
;   12288..16383  L_JK packed strip
;   16384..16639  acc_LU
;   16640..16895  acc_ULt
;   16896..16901  K16 scratch (6 words)
;   16902..17157  output tile staging (256 words)
;   17158..17413  per-tile status words, status[t] = r1 of tile t
;
; Register effects: r1-r12 are clobbered; r14 and r15 are saved/restored;
; r13 remains 1; r0 remains the zero register.
;
; Floor plan per tile (t = 16*i + j):
;   L_IK  = L rows 16*i..16*i+15, all 256 K columns, packed into K blocks
;   U_KJ  = U all 256 K rows, columns 16*j..16*j+15, already K-major
;   U_IK  = U rows 16*i..16*i+15, all 256 K columns, packed into K blocks
;   L_JK  = L rows 16*j..16*j+15, all 256 K columns, packed into K blocks
; Packing is a pure fixed-stride word copy; no arithmetic touches values.

mth_graph_pair_full_grid_driver_f32:
  LA r12,@mth_full_grid_state
  ST r1,r12,0              ; L full base
  ST r2,r12,1              ; U full base
  ST r3,r12,2              ; Y full base
  ST r4,r12,3              ; workspace base
  ST r0,r12,4              ; tile index 0..255
  ST r14,r12,5
  ST r15,r12,6             ; caller return link

mth_full_grid_tile:
  LA r12,@mth_full_grid_state
  LD r1,r12,4
  MOVI r2,256
  CMP r1,r2
  JMP[GE] @mth_full_grid_success

  ; i = tile >> 4, j = tile & 15
  SHR r2,r1,4
  ST r2,r12,7
  MOVI r3,15
  BOOL.8 r4,r1,r3
  ST r4,r12,8

  ; L_IK strip -> workspace + 0
  LA r12,@mth_full_grid_state
  LD r1,r12,0
  LD r2,r12,7
  SHL r2,r2,12
  ADD r1,r1,r2
  LD r2,r12,3
  CALL @mth_full_grid_pack_row

  ; U_IK strip -> workspace + 8192
  LA r12,@mth_full_grid_state
  LD r1,r12,1
  LD r2,r12,7
  SHL r2,r2,12
  ADD r1,r1,r2
  LD r2,r12,3
  MOVI r3,8192
  ADD r2,r2,r3
  CALL @mth_full_grid_pack_row

  ; L_JK strip -> workspace + 12288
  LA r12,@mth_full_grid_state
  LD r1,r12,0
  LD r2,r12,8
  SHL r2,r2,12
  ADD r1,r1,r2
  LD r2,r12,3
  MOVI r3,12288
  ADD r2,r2,r3
  CALL @mth_full_grid_pack_row

  ; U_KJ strip -> workspace + 4096 (column window, K-major blocks)
  LA r12,@mth_full_grid_state
  LD r1,r12,1
  LD r2,r12,8
  SHL r2,r2,4
  ADD r1,r1,r2
  LD r2,r12,3
  MOVI r3,4096
  ADD r2,r2,r3
  CALL @mth_full_grid_pack_col

  ; Fresh +0 accumulators for this tile.
  LA r12,@mth_full_grid_state
  LD r1,r12,3
  MOVI r2,16384
  ADD r1,r1,r2
  MOVI r2,0
  MOVI r3,512
  BFILL r1,r2,r3

  ; Invoke the existing one-tile driver with its unchanged ABI.
  LA r12,@mth_full_grid_state
  LD r1,r12,3              ; L_IK
  LD r2,r12,3
  MOVI r3,4096
  ADD r2,r2,r3             ; U_KJ
  LD r3,r12,3
  MOVI r4,8192
  ADD r3,r3,r4             ; U_IK
  LD r4,r12,3
  MOVI r5,12288
  ADD r4,r4,r5             ; L_JK
  LD r5,r12,3
  MOVI r6,16384
  ADD r5,r5,r6             ; acc_LU
  LD r6,r12,3
  MOVI r7,16640
  ADD r6,r6,r7             ; acc_ULt
  LD r7,r12,3
  MOVI r8,16896
  ADD r7,r7,r8             ; K16 scratch
  LD r8,r12,3
  MOVI r9,16902
  ADD r8,r8,r9             ; output tile staging
  MOVI r13,1
  CALL @mth_graph_pair_tile16_k16_driver_f32

  ; Record status[t], then fail closed on the first non-success.
  LA r12,@mth_full_grid_state
  LD r2,r12,3
  MOVI r3,17158
  ADD r2,r2,r3
  LD r3,r12,4
  ADD r2,r2,r3
  ST r1,r2,0
  MOVI r2,1
  CMP r1,r2
  JMP[NE] @mth_full_grid_fail

  ; Scatter the 16x16 tile into Y rows 16*i..16*i+15, columns 16*j..16*j+15.
  LA r12,@mth_full_grid_state
  LD r1,r12,2
  LD r2,r12,7
  SHL r2,r2,12
  ADD r1,r1,r2
  LD r2,r12,8
  SHL r2,r2,4
  ADD r1,r1,r2
  LD r2,r12,3
  MOVI r3,16902
  ADD r2,r2,r3
  CALL @mth_full_grid_scatter_tile

  LA r12,@mth_full_grid_state
  LD r1,r12,4
  ADDI r1,r1,1
  ST r1,r12,4
  JMP @mth_full_grid_tile

mth_full_grid_success:
  MOVI r1,1
  JMP @mth_full_grid_return

mth_full_grid_fail:
  MOVI r1,0

mth_full_grid_return:
  LA r12,@mth_full_grid_state
  LD r14,r12,5
  LD r15,r12,6
  RET

; Pack a 16x256 row-major window into sixteen contiguous 16x16 K blocks.
; ABI: r1=source row-window base, r2=destination strip base, r13=1.
; dst[s*256 + p*16 + q] = src[p*256 + s*16 + q], s,p,q in 0..15.
mth_full_grid_pack_row:
  MOVI r3,0                ; K block s
  MOVI r9,16
  MOVI r7,16               ; words per 16x16 row
mth_full_grid_pack_row_s:
  MOVI r4,0                ; row p
  SHL r5,r3,4              ; s*16
  ADD r5,r1,r5
  SHL r6,r3,8              ; s*256
  ADD r6,r2,r6
mth_full_grid_pack_row_p:
  BCOPY r6,r5,r7
  ADDI r5,r5,256
  ADDI r6,r6,16
  ADDI r4,r4,1
  CMP r4,r9
  JMP[LT] @mth_full_grid_pack_row_p
  ADDI r3,r3,1
  CMP r3,r9
  JMP[LT] @mth_full_grid_pack_row_s
  MOVI r1,1
  RET

; Pack a 256x16 column window (K rows, 16 output columns) into K blocks.
; ABI: r1=source column-window base, r2=destination strip base, r13=1.
; dst[s*256 + p*16 + q] = src[s*4096 + p*256 + q], s,p,q in 0..15.
mth_full_grid_pack_col:
  MOVI r3,0                ; K block s
  MOVI r9,16
  MOVI r7,16               ; words per 16x16 row
mth_full_grid_pack_col_s:
  MOVI r4,0                ; row p inside block
  SHL r5,r3,12             ; s*4096
  ADD r5,r1,r5
  SHL r6,r3,8              ; s*256
  ADD r6,r2,r6
mth_full_grid_pack_col_p:
  BCOPY r6,r5,r7
  ADDI r5,r5,256
  ADDI r6,r6,16
  ADDI r4,r4,1
  CMP r4,r9
  JMP[LT] @mth_full_grid_pack_col_p
  ADDI r3,r3,1
  CMP r3,r9
  JMP[LT] @mth_full_grid_pack_col_s
  MOVI r1,1
  RET

; Copy one 16x16 tile row by row into the full row-major output.
; ABI: r1=Y tile origin, r2=staged tile base, r13=1.
mth_full_grid_scatter_tile:
  MOVI r3,16
  MOVI r4,0
mth_full_grid_scatter_loop:
  BCOPY r1,r2,r3
  ADDI r1,r1,256
  ADDI r2,r2,16
  ADDI r4,r4,1
  CMP r4,r3
  JMP[LT] @mth_full_grid_scatter_loop
  MOVI r1,1
  RET

; Private 12-word frame. r12 is recomputed after every nested call.
; 0..3 full-matrix/workspace bases, 4 tile index, 5..6 saved r14/r15,
; 7 tile row i, 8 tile column j, 9..11 reserved.
.org 2048
mth_full_grid_state:
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
