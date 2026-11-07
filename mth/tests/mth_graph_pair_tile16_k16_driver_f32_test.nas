.org 0
JMP @mth_pair_driver_test_main
.include "../nan16/mth_graph_pair_tile16_k16_f32.nas"
.include "../nan16/mth_graph_pair_tile16_k16_driver_f32.nas"

mth_pair_driver_test_main:
  MOVI r13,1
  ; Two products in different slices exercise the entire 16-call driver:
  ; first term at K-slice 0, second term at K-slice 15.
  MOVI r5,0
  MOVHI r5,0x4000
  LA r4,@mth_driver_li
  MOVI r6,19
  ADD r4,r4,r6
  ST r5,r4,0
  LA r4,@mth_driver_ukj
  MOVI r6,50
  ADD r4,r4,r6
  ST r5,r4,0

  ; Verify the staged source strip contains the expected float32 payload.
  LA r4,@mth_driver_li
  MOVI r6,19
  ADD r4,r4,r6
  LD r7,r4,0
  MOVI r8,0
  MOVHI r8,0x4000
  CMP r7,r8
  JMP[NE] @mth_pair_driver_test_fail

  LA r1,@mth_driver_li
  LA r2,@mth_driver_ukj
  LA r3,@mth_driver_uik
  LA r4,@mth_driver_ljk
  LA r5,@mth_driver_acc_lu
  LA r6,@mth_driver_acc_ult
  LA r7,@mth_driver_scratch
  CALL @mth_graph_pair_tile16_k16_driver_f32
  MOVI r2,1
  CMP r1,r2
  JMP[NE] @mth_pair_driver_test_fail

  ; Verify both independent accumulators after all sixteen K slices.
  LA r4,@mth_driver_acc_lu
  MOVI r6,18
  ADD r4,r4,r6
  LD r7,r4,0
  MOVI r8,0
  MOVHI r8,0x4080
  CMP r7,r8
  JMP[NE] @mth_pair_driver_test_fail
  LA r4,@mth_driver_acc_ult
  MOVI r6,18
  ADD r4,r4,r6
  LD r7,r4,0
  CMP r7,r8
  JMP[NE] @mth_pair_driver_test_fail

  ; Finalize in the fixture after the driver returns.
  LA r1,@mth_driver_acc_lu
  LA r2,@mth_driver_acc_ult
  LA r3,@mth_driver_y
  MOVI r13,1
  CALL @mth_graph_pair_tile16_finalize_f32
  MOVI r2,1
  CMP r1,r2
  JMP[NE] @mth_pair_driver_test_fail

  ; Only Y[1,2] is nonzero, and it must be 4 + 4 = 8.
  LA r4,@mth_driver_y
  MOVI r5,0
mth_pair_driver_check:
  LD r6,r4,0
  MOVI r7,18
  CMP r5,r7
  JMP[EQ] @mth_pair_driver_expect_eight
  CMP r6,r0
  JMP[NE] @mth_pair_driver_test_fail
  JMP @mth_pair_driver_check_next
mth_pair_driver_expect_eight:
  MOVI r7,0
  MOVHI r7,0x4100
  CMP r6,r7
  JMP[NE] @mth_pair_driver_test_fail
mth_pair_driver_check_next:
  ADD r4,r4,r13
  ADD r5,r5,r13
  MOVI r7,256
  CMP r5,r7
  JMP[LT] @mth_pair_driver_check

  LA r1,@mth_pair_driver_pass
  CALL @mth_pair_driver_puts
  HALT
mth_pair_driver_test_fail:
  LA r1,@mth_pair_driver_bad
  CALL @mth_pair_driver_puts
  HALT
mth_pair_driver_puts:
  MOVI r4,255
mth_pair_driver_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_pair_driver_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_pair_driver_puts_byte
  ADD r1,r1,r13
  JMP @mth_pair_driver_puts_word

; Four 16-slice strips = 4 * 4096 words.
.org 1024
mth_driver_li:
.org 1043
.word 0x40000000
.org 5120
mth_driver_ukj:
.org 5170
.word 0x40000000
.org 9216
mth_driver_uik:
.org 13077
.word 0x40000000
.org 13312
mth_driver_ljk:
.org 17189
.word 0x40000000
.org 17408
mth_driver_acc_lu:
.word 0
.org 17664
mth_driver_acc_ult:
.word 0
.org 17920
mth_driver_y:
.word 0
.org 18176
mth_driver_scratch:
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.org 18512
mth_pair_driver_pass:
.str "MTH PAIR TILE16 K16 DRIVER PASS\\n"
mth_pair_driver_bad:
.str "MTH PAIR TILE16 K16 DRIVER FAIL\\n"
