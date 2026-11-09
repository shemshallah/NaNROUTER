; MTH causal pair knockout/restore fixture — NaN16 only.
;
; Seeds both lanes and metadata, saves/zeros, restores, checks exact transport,
; metadata locality, boundary pair 32640, and invalid id/mode atomicity.

.org 0
JMP @mth_knockout_test_main
.include "../nan16/mth_mirror_pair_knockout.nas"

mth_knockout_test_main:
  MOVI r0,0
  MOVI r13,1
  CALL @mth_knockout_test_seed

  ; save + zero
  MOVI r1,1
  MOVI r2,@mth_knockout_test_backup
  MOVI r3,0
  CALL @mth_mirror_pair_knockout_f32
  CMP r1,r13
  JMP[NE] @mth_knockout_test_fail
  CALL @mth_knockout_test_check_saved
  CALL @mth_knockout_test_check_zero

  ; restore
  MOVI r1,1
  MOVI r2,@mth_knockout_test_backup
  MOVI r3,1
  CALL @mth_mirror_pair_knockout_f32
  CMP r1,r13
  JMP[NE] @mth_knockout_test_fail
  CALL @mth_knockout_test_check_restored

  ; invalid id 0
  MOVI r1,0xBEEF
  MOVHI r1,0xDEAD
  ST r1,r0,@mth_knockout_test_backup
  MOVI r1,1
  MOVHI r1,0xCAFE
  ST r1,r0,8192
  MOVI r1,0
  MOVI r2,@mth_knockout_test_backup
  MOVI r3,0
  CALL @mth_mirror_pair_knockout_f32
  CMP r1,r0
  JMP[NE] @mth_knockout_test_fail
  MOVI r8,1
  CMP r9,r8
  JMP[NE] @mth_knockout_test_fail
  LD r1,r0,@mth_knockout_test_backup
  MOVI r2,0xBEEF
  MOVHI r2,0xDEAD
  CMP r1,r2
  JMP[NE] @mth_knockout_test_fail
  LD r1,r0,8192
  MOVI r2,1
  MOVHI r2,0xCAFE
  CMP r1,r2
  JMP[NE] @mth_knockout_test_fail

  ; invalid id 32641
  MOVI r1,32641
  MOVI r2,@mth_knockout_test_backup
  MOVI r3,0
  CALL @mth_mirror_pair_knockout_f32
  CMP r1,r0
  JMP[NE] @mth_knockout_test_fail
  MOVI r8,1
  CMP r9,r8
  JMP[NE] @mth_knockout_test_fail

  ; invalid mode 2
  MOVI r1,1
  MOVI r2,@mth_knockout_test_backup
  MOVI r3,2
  CALL @mth_mirror_pair_knockout_f32
  CMP r1,r0
  JMP[NE] @mth_knockout_test_fail
  MOVI r8,2
  CMP r9,r8
  JMP[NE] @mth_knockout_test_fail

  ; boundary pair 32640
  CALL @mth_knockout_test_boundary

  ; recovery
  CALL @mth_knockout_test_seed
  MOVI r1,1
  MOVI r2,@mth_knockout_test_backup
  MOVI r3,0
  CALL @mth_mirror_pair_knockout_f32
  CMP r1,r13
  JMP[NE] @mth_knockout_test_fail
  MOVI r1,1
  MOVI r2,@mth_knockout_test_backup
  MOVI r3,1
  CALL @mth_mirror_pair_knockout_f32
  CMP r1,r13
  JMP[NE] @mth_knockout_test_fail
  CALL @mth_knockout_test_check_restored

  MOVI r1,@mth_knockout_test_pass
  CALL @mth_knockout_test_puts
  HALT

mth_knockout_test_seed:
  ST r15,r0,@mth_knockout_test_ret
  MOVI r6,0
mth_knockout_test_seed_loop:
  MOVI r1,0
  MOVHI r1,0x3F80
  ADD r1,r1,r6
  ADD r7,r6,r0
  MOVI r8,8192
  ADD r8,r8,r7
  ST r1,r8,0
  MOVI r1,0
  MOVHI r1,0xBF80
  SUB r1,r1,r6
  ADDI r8,r8,32
  ST r1,r8,0
  ADDI r6,r6,1
  MOVI r8,26
  CMP r6,r8
  JMP[LT] @mth_knockout_test_seed_loop

  ; metadata words 26..31
  MOVI r6,0
mth_knockout_test_meta:
  MOVI r1,0xA5A5
  MOVHI r1,0xA5A5
  ADD r1,r1,r6
  ADDI r8,r6,8192
  ADDI r8,r8,26
  ST r1,r8,0
  ADDI r6,r6,1
  MOVI r8,6
  CMP r6,r8
  JMP[LT] @mth_knockout_test_meta
  LD r15,r0,@mth_knockout_test_ret
  RET

mth_knockout_test_check_saved:
  ST r15,r0,@mth_knockout_test_ret
  MOVI r6,0
mth_knockout_test_saved_loop:
  MOVI r1,0
  MOVHI r1,0x3F80
  ADD r1,r1,r6
  ADD r8,r6,r0
  MOVI r9,@mth_knockout_test_backup
  ADD r8,r9,r8
  LD r2,r8,0
  CMP r1,r2
  JMP[NE] @mth_knockout_test_fail
  MOVI r1,0
  MOVHI r1,0xBF80
  SUB r1,r1,r6
  ADDI r8,r6,26
  ADD r8,r9,r8
  LD r2,r8,0
  CMP r1,r2
  JMP[NE] @mth_knockout_test_fail
  ADDI r6,r6,1
  MOVI r8,26
  CMP r6,r8
  JMP[LT] @mth_knockout_test_saved_loop
  LD r15,r0,@mth_knockout_test_ret
  RET

mth_knockout_test_check_zero:
  MOVI r6,0
mth_knockout_test_zero_loop:
  ADD r8,r6,r0
  MOVI r9,8192
  ADD r8,r9,r8
  LD r1,r8,0
  CMP r1,r0
  JMP[NE] @mth_knockout_test_fail
  ADDI r8,r8,32
  LD r1,r8,0
  CMP r1,r0
  JMP[NE] @mth_knockout_test_fail
  ADDI r6,r6,1
  MOVI r8,26
  CMP r6,r8
  JMP[LT] @mth_knockout_test_zero_loop
  ; metadata still A5A5...
  MOVI r6,0
mth_knockout_test_meta_check:
  MOVI r1,0xA5A5
  MOVHI r1,0xA5A5
  ADD r1,r1,r6
  ADDI r8,r6,8192
  ADDI r8,r8,26
  LD r2,r8,0
  CMP r1,r2
  JMP[NE] @mth_knockout_test_fail
  ADDI r6,r6,1
  MOVI r8,6
  CMP r6,r8
  JMP[LT] @mth_knockout_test_meta_check
  RET

mth_knockout_test_check_restored:
  MOVI r6,0
mth_knockout_test_restored_loop:
  MOVI r1,0
  MOVHI r1,0x3F80
  ADD r1,r1,r6
  ADD r8,r6,r0
  MOVI r9,8192
  ADD r8,r9,r8
  LD r2,r8,0
  CMP r1,r2
  JMP[NE] @mth_knockout_test_fail
  MOVI r1,0
  MOVHI r1,0xBF80
  SUB r1,r1,r6
  ADDI r8,r8,32
  LD r2,r8,0
  CMP r1,r2
  JMP[NE] @mth_knockout_test_fail
  ADDI r6,r6,1
  MOVI r8,26
  CMP r6,r8
  JMP[LT] @mth_knockout_test_restored_loop
  RET

mth_knockout_test_boundary:
  ST r15,r0,@mth_knockout_test_ret
  ; pair 32640 base = 8192 + 32639*64 = 2,097,088
  MOVI r1,0x1234
  MOVHI r1,0x5678
  MOVI r8,0xFFC0
  MOVHI r8,0x001F
  ST r1,r8,0
  MOVI r1,32640
  MOVI r2,@mth_knockout_test_backup
  MOVI r3,0
  CALL @mth_mirror_pair_knockout_f32
  CMP r1,r13
  JMP[NE] @mth_knockout_test_fail
  MOVI r8,0xFFC0
  MOVHI r8,0x001F
  LD r1,r8,0
  CMP r1,r0
  JMP[NE] @mth_knockout_test_fail
  MOVI r1,32640
  MOVI r2,@mth_knockout_test_backup
  MOVI r3,1
  CALL @mth_mirror_pair_knockout_f32
  CMP r1,r13
  JMP[NE] @mth_knockout_test_fail
  MOVI r8,0xFFC0
  MOVHI r8,0x001F
  LD r1,r8,0
  MOVI r2,0x1234
  MOVHI r2,0x5678
  CMP r1,r2
  JMP[NE] @mth_knockout_test_fail
  LD r15,r0,@mth_knockout_test_ret
  RET

mth_knockout_test_fail:
  MOVI r1,@mth_knockout_test_bad
  CALL @mth_knockout_test_puts
  HALT

mth_knockout_test_puts:
  MOVI r4,255
mth_knockout_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_knockout_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_knockout_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_knockout_test_puts_word

mth_knockout_test_pass:
.str "MTH PAIR KNOCKOUT PASS\n"
mth_knockout_test_bad:
.str "MTH PAIR KNOCKOUT FAIL\n"

.org 4096
mth_knockout_test_ret:
.word 0
mth_knockout_test_backup:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
