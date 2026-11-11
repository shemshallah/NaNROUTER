; Guest-only proof of address geometry, mirror orientation and void255.
.org 0
JMP @mth_h256_test_main
.include "../nan16/mth_hypertensor256_mirror_arena_map.nas"

mth_h256_test_main:
  MOVI r0,0
  MOVI r13,1

  ; h=0, a=b=0 => fixed point 0 at byte 0.
  MOVI r1,0
  MOVI r2,0
  MOVI r3,0
  MOVI r8,0
  MOVI r9,0
  MOVI r10,0
  CALL @mth_h256_test_expect

  ; The same mirror cell has independent directed words.
  MOVI r1,0
  MOVI r2,0
  MOVI r3,1
  MOVI r8,256
  MOVI r9,0
  MOVI r10,1024
  CALL @mth_h256_test_expect

  MOVI r1,0
  MOVI r2,1
  MOVI r3,0
  MOVI r8,256
  MOVI r9,1
  MOVI r10,1028
  CALL @mth_h256_test_expect

  ; Canonical pair for (1,2) is 256; cell index 511.
  MOVI r1,0
  MOVI r2,1
  MOVI r3,2
  MOVI r8,511
  MOVI r9,0
  MOVI r10,3064
  CALL @mth_h256_test_expect

  ; One full bank later: 256 KiB.
  MOVI r1,1
  MOVI r2,0
  MOVI r3,1
  MOVI r8,256
  MOVI r9,0
  MOVI r10,1024
  MOVHI r10,4
  CALL @mth_h256_test_expect

  ; Boundary of last ACTIVE bank 254.
  MOVI r1,254
  MOVI r2,254
  MOVI r3,254
  MOVI r8,254
  MOVI r9,0
  MOVI r10,0x03F8
  MOVHI r10,0x03F8
  CALL @mth_h256_test_expect

  MOVI r1,254
  MOVI r2,253
  MOVI r3,254
  MOVI r8,32893
  MOVI r9,0
  MOVI r10,0xFFE8
  MOVHI r10,0x03FB
  CALL @mth_h256_test_expect

  MOVI r1,254
  MOVI r2,254
  MOVI r3,253
  MOVI r8,32893
  MOVI r9,1
  MOVI r10,0xFFEC
  MOVHI r10,0x03FB
  CALL @mth_h256_test_expect

  ; Semantic void 255 is NOT a trainable coordinate on any axis.
  MOVI r1,255
  MOVI r2,0
  MOVI r3,1
  CALL @mth_h256_test_reject
  MOVI r1,0
  MOVI r2,255
  MOVI r3,1
  CALL @mth_h256_test_reject
  MOVI r1,0
  MOVI r2,1
  MOVI r3,255
  CALL @mth_h256_test_reject
  MOVI r1,256
  MOVI r2,0
  MOVI r3,0
  CALL @mth_h256_test_reject
  MOVI r1,0
  MOVI r2,256
  MOVI r3,0
  CALL @mth_h256_test_reject
  MOVI r1,0
  MOVI r2,0
  MOVI r3,256
  CALL @mth_h256_test_reject
  MOVI r1,0xFFFF
  MOVHI r1,0xFFFF
  MOVI r2,0
  MOVI r3,0
  CALL @mth_h256_test_reject

  ; Exhaust every unordered pair among 0..254; each reversed lookup must
  ; yield the identical canonical identity, with the reverse f32 word +4.
  ; No host calculations or host-language opcode implementation.
  MOVI r8,0
mth_h256_test_row:
  ADD r9,r8,r13
mth_h256_test_col:
  MOVI r1,0
  ADD r2,r8,r0
  ADD r3,r9,r0
  CALL @mth_hypertensor256_mirror_arena_map
  CMP r1,r13
  JMP[NE] @mth_h256_test_fail
  CMP r5,r0
  JMP[NE] @mth_h256_test_fail
  ADD r11,r4,r0
  ADD r12,r6,r0
  MOVI r1,0
  ADD r2,r9,r0
  ADD r3,r8,r0
  CALL @mth_hypertensor256_mirror_arena_map
  CMP r1,r13
  JMP[NE] @mth_h256_test_fail
  CMP r4,r11
  JMP[NE] @mth_h256_test_fail
  CMP r5,r13
  JMP[NE] @mth_h256_test_fail
  ADDI r12,r12,4
  CMP r6,r12
  JMP[NE] @mth_h256_test_fail
  ADD r9,r9,r13
  MOVI r14,255
  CMP r9,r14
  JMP[LT] @mth_h256_test_col
  ADD r8,r8,r13
  MOVI r14,254
  CMP r8,r14
  JMP[LT] @mth_h256_test_row

  MOVI r1,@mth_h256_test_pass
  CALL @mth_h256_test_puts
  HALT

; Inputs: h,a,b in r1-r3, expected canonical cell/lane/byte in r8-r10.
mth_h256_test_expect:
  ADD r14,r15,r0
  CALL @mth_hypertensor256_mirror_arena_map
  CMP r1,r13
  JMP[NE] @mth_h256_test_fail
  CMP r4,r8
  JMP[NE] @mth_h256_test_fail
  CMP r5,r9
  JMP[NE] @mth_h256_test_fail
  CMP r6,r10
  JMP[NE] @mth_h256_test_fail
  ADD r15,r14,r0
  RET

; Inputs h,a,b in r1-r3. Rejections must not leak stale addresses.
mth_h256_test_reject:
  ADD r14,r15,r0
  CALL @mth_hypertensor256_mirror_arena_map
  CMP r1,r0
  JMP[NE] @mth_h256_test_fail
  CMP r4,r0
  JMP[NE] @mth_h256_test_fail
  CMP r5,r0
  JMP[NE] @mth_h256_test_fail
  CMP r6,r0
  JMP[NE] @mth_h256_test_fail
  ADD r15,r14,r0
  RET

mth_h256_test_fail:
  MOVI r1,@mth_h256_test_bad
  CALL @mth_h256_test_puts
  HALT

mth_h256_test_puts:
  MOVI r4,255
mth_h256_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_h256_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_h256_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_h256_test_puts_word

.org 1024
mth_h256_test_pass:
.str "MTH HYPERTENSOR256 MIRROR ARENA PASS\n"
mth_h256_test_bad:
.str "MTH HYPERTENSOR256 MIRROR ARENA FAIL\n"
