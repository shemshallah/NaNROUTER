; NaN16 full 16-slice driver for one 16x16 pair-space output tile.
; ABI:
;   r1..r4 = four strip bases, each 16 K-slices x 256 words
;   r5=acc_LU (256), r6=acc_ULt (256), r7=6-word K16 scratch
;   r8=output tile (256)
; r13 must contain 1. Driver state is private static guest scratch.
; Each strip is laid out as 16 contiguous 16x16 blocks in increasing K order.
; Driver executes all K=0,16,...,240 and finalizes the output tile.
; Host staging is limited to these four strips for the current output tile.

mth_graph_pair_tile16_k16_driver_f32:
  LA r12,@mth_pair_driver_state
  ST r1,r12,0
  ST r2,r12,1
  ST r3,r12,2
  ST r4,r12,3
  ST r5,r12,4
  ST r6,r12,5
  ST r7,r12,6
  ST r8,r12,7
  ST r0,r12,8
  ST r0,r12,9

mth_pair_driver_slice:
  ; Build the four input pointers for the current 256-word K block.
  LA r12,@mth_pair_driver_state
  LD r1,r12,0
  LD r2,r12,8
  ADD r1,r1,r2
  LA r12,@mth_pair_driver_state
  LD r2,r12,1
  LD r3,r12,8
  ADD r2,r2,r3
  LA r12,@mth_pair_driver_state
  LD r3,r12,2
  LD r4,r12,8
  ADD r3,r3,r4
  LA r12,@mth_pair_driver_state
  LD r4,r12,3
  LD r9,r12,8
  ADD r4,r4,r9
  LA r12,@mth_pair_driver_state
  LD r5,r12,4
  LD r6,r12,5
  LD r7,r12,6
  MOVI r13,1
  CALL @mth_graph_pair_tile16_k16_accum_f32
  MOVI r10,1
  CMP r1,r10
  JMP[NE] @mth_pair_driver_fail

  ; Advance to the next K slice. There are exactly sixteen.
  LA r12,@mth_pair_driver_state
  LD r1,r12,8
  MOVI r2,256
  ADD r1,r1,r2
  ST r1,r12,8
  LD r1,r12,9
  ADD r1,r1,r13
  ST r1,r12,9
  MOVI r11,48
  ADD r11,r11,r1
  PUTC r11
  MOVI r2,16
  CMP r1,r2
  JMP[LT] @mth_pair_driver_slice

  ; Finalize only after all sixteen slices have returned successfully.
  MOVI r11,70
  PUTC r11
  MOVI r11,48
  ADD r11,r11,r13
  PUTC r11
  LA r12,@mth_pair_driver_state
  LD r1,r12,4
  LD r2,r12,5
  LD r3,r12,7
  MOVI r13,1
  CALL @mth_graph_pair_tile16_finalize_f32
  MOVI r11,71
  PUTC r11
  MOVI r2,1
  CMP r1,r2
  JMP[NE] @mth_pair_driver_fail
  MOVI r11,72
  PUTC r11
  MOVI r1,1
  RET

mth_pair_driver_fail:
  MOVI r1,0
  RET

; Private 10-word frame; r12 is recomputed after each callee call.
.org 400
mth_pair_driver_state:
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

