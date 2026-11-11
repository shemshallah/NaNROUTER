; Native 128 MiB two-full-tensor address proof with mirror-pair identity.
.org 0
JMP @mth_td_main
.include "../nan16/mth_hypertensor256_mirror_arena_map.nas"
.include "../nan16/mth_hypertensor256_mirror_dual_map.nas"

mth_td_main:
  MOVI r0,0
  MOVI r13,1

  ; Exhaust every trainable h bank (0..254), and compare active/candidate
  ; addresses for exactly the same canonical pair and orientation.
  MOVI r12,0
mth_td_head_loop:
  ADD r1,r12,r0
  MOVI r2,2
  MOVI r3,3
  MOVI r8,0
  CALL @mth_hypertensor256_mirror_dual_map
  CMP r1,r13
  JMP[NE] @mth_td_fail
  MOVI r9,765                ; canonical pair id of (2,3): 256+509
  CMP r4,r9
  JMP[NE] @mth_td_fail
  CMP r5,r0
  JMP[NE] @mth_td_fail
  ADD r10,r6,r0              ; active offset

  ADD r1,r12,r0
  MOVI r2,2
  MOVI r3,3
  MOVI r8,1
  CALL @mth_hypertensor256_mirror_dual_map
  CMP r1,r13
  JMP[NE] @mth_td_fail
  MOVI r9,765
  CMP r4,r9
  JMP[NE] @mth_td_fail
  CMP r5,r0
  JMP[NE] @mth_td_fail
  MOVI r9,0
  MOVHI r9,0x0400             ; offset between complete banks = 64 MiB
  ADD r10,r10,r9
  CMP r6,r10
  JMP[NE] @mth_td_fail

  ; The reversed pair is the independent +4 byte member of SAME mirror.
  ADD r1,r12,r0
  MOVI r2,3
  MOVI r3,2
  MOVI r8,1
  CALL @mth_hypertensor256_mirror_dual_map
  CMP r1,r13
  JMP[NE] @mth_td_fail
  MOVI r9,765
  CMP r4,r9
  JMP[NE] @mth_td_fail
  CMP r5,r13
  JMP[NE] @mth_td_fail
  ADDI r10,r10,4
  CMP r6,r10
  JMP[NE] @mth_td_fail

  ADDI r12,r12,1
  MOVI r9,255
  CMP r12,r9
  JMP[LT] @mth_td_head_loop

  ; Last possible physical byte of candidate tensor is < 128 MiB.
  ; The semantic-255 coordinates remain intentionally void and cannot
  ; be used as a writable way to reach reserved physical capacity.
  MOVI r1,254
  MOVI r2,254
  MOVI r3,254
  MOVI r8,1
  CALL @mth_hypertensor256_mirror_dual_map
  CMP r1,r13
  JMP[NE] @mth_td_fail
  MOVI r9,0
  MOVHI r9,0x0400
  CMP r6,r9
  JMP[LT] @mth_td_fail
  MOVI r9,0
  MOVHI r9,0x0800
  CMP r6,r9
  JMP[GE] @mth_td_fail

  MOVI r1,255
  MOVI r2,0
  MOVI r3,1
  MOVI r8,1
  CALL @mth_hypertensor256_mirror_dual_map
  CMP r1,r0
  JMP[NE] @mth_td_fail
  MOVI r1,1
  MOVI r2,0
  MOVI r3,255
  MOVI r8,1
  CALL @mth_hypertensor256_mirror_dual_map
  CMP r1,r0
  JMP[NE] @mth_td_fail

  ; Invalid bank 2 is rejected, not wrapped into the active tensor.
  MOVI r1,1
  MOVI r2,2
  MOVI r3,3
  MOVI r8,2
  CALL @mth_hypertensor256_mirror_dual_map
  CMP r1,r0
  JMP[NE] @mth_td_fail
  CMP r6,r0
  JMP[NE] @mth_td_fail

  MOVI r1,@mth_td_pass
  CALL @mth_td_puts
  HALT
mth_td_fail:
  MOVI r1,@mth_td_bad
  CALL @mth_td_puts
  HALT
mth_td_puts:
  MOVI r4,255
mth_td_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_td_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_td_puts_byte
  ADD r1,r1,r13
  JMP @mth_td_puts_word
.org 1024
mth_td_pass:
.str "MTH FULL 128M MIRROR DUAL BANK PASS\n"
mth_td_bad:
.str "MTH FULL 128M MIRROR DUAL BANK FAIL\n"
