; MTH contradiction-preserving evidence fixture — NaN16 only.
;
; Checks exact min/balance/support/oppose behavior, symmetry, preservation of
; both sides, negative/NaN/infinity rejection, and recovery.

.org 0
JMP @mth_contradiction_test_main
.include "../nan16/mth_mirror_cycle_contradiction.nas"

mth_contradiction_test_main:
  MOVI r0,0
  MOVI r13,1

  ; (support, oppose, expected conflict, expected balance)
  MOVI r1,0
  MOVI r2,0
  MOVI r3,0
  MOVI r4,0
  CALL @mth_contradiction_test_case

  MOVI r1,0
  MOVHI r1,0x3F80            ; 1.0
  MOVI r2,0
  MOVI r3,0
  MOVI r4,0
  MOVHI r4,0x3F80            ; 1.0
  CALL @mth_contradiction_test_case

  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x3F80            ; oppose 1.0
  MOVI r3,0
  MOVI r4,0
  MOVHI r4,0xBF80            ; -1.0
  CALL @mth_contradiction_test_case

  MOVI r1,0
  MOVHI r1,0x4020            ; 2.5
  MOVI r2,0
  MOVHI r2,0x3F00            ; 0.5
  MOVI r3,0
  MOVHI r3,0x3F00            ; conflict 0.5
  MOVI r4,0
  MOVHI r4,0x4000            ; balance 2.0
  CALL @mth_contradiction_test_case

  ; Symmetric case: same conflict, negated balance.
  MOVI r1,0
  MOVHI r1,0x3F00            ; 0.5
  MOVI r2,0
  MOVHI r2,0x4020            ; 2.5
  MOVI r3,0
  MOVHI r3,0x3F00            ; conflict 0.5
  MOVI r4,0
  MOVHI r4,0xC000            ; balance -2.0
  CALL @mth_contradiction_test_case

  ; Both sides present: conflict remains nonzero.
  MOVI r1,0
  MOVHI r1,0x4040            ; 3.0
  MOVI r2,0
  MOVHI r2,0x4040            ; 3.0
  MOVI r3,0
  MOVHI r3,0x4040            ; conflict 3.0
  MOVI r4,0
  MOVI r4,0                  ; balance 0
  CALL @mth_contradiction_test_case

  ; Rejections.
  MOVI r1,0
  MOVHI r1,0xBF80            ; -1.0
  MOVI r2,0
  MOVI r3,3
  CALL @mth_contradiction_test_reject
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0xBF80            ; -1.0
  MOVI r3,4
  CALL @mth_contradiction_test_reject
  MOVI r1,0
  MOVHI r1,0x7F80            ; +inf
  MOVI r2,0
  MOVI r3,1
  CALL @mth_contradiction_test_reject
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x7FC0            ; quiet NaN
  MOVI r3,2
  CALL @mth_contradiction_test_reject

  ; Recovery.
  MOVI r1,0
  MOVHI r1,0x3F80
  MOVI r2,0
  MOVHI r2,0x3F00
  MOVI r3,0
  MOVHI r3,0x3F00
  MOVI r4,0
  MOVHI r4,0x3F00
  CALL @mth_contradiction_test_case

  MOVI r1,@mth_contradiction_test_pass
  CALL @mth_contradiction_test_puts
  HALT

; r1=support, r2=oppose, r3=expected conflict, r4=expected balance.
mth_contradiction_test_case:
  ST r15,r0,@mth_contradiction_test_ret
  MOVI r8,@mth_contradiction_test_s
  ST r1,r8,0
  MOVI r8,@mth_contradiction_test_o
  ST r2,r8,0
  MOVI r8,@mth_contradiction_test_ec
  ST r3,r8,0
  MOVI r8,@mth_contradiction_test_eb
  ST r4,r8,0

  CALL @mth_mirror_cycle_contradiction_f32
  CMP r1,r13
  JMP[NE] @mth_contradiction_test_fail
  CMP r9,r0
  JMP[NE] @mth_contradiction_test_fail

  LD r8,r0,@mth_contradiction_test_ec
  CMP r2,r8
  JMP[NE] @mth_contradiction_test_fail
  LD r8,r0,@mth_contradiction_test_eb
  CMP r3,r8
  JMP[NE] @mth_contradiction_test_fail
  LD r8,r0,@mth_contradiction_test_s
  CMP r4,r8
  JMP[NE] @mth_contradiction_test_fail
  LD r8,r0,@mth_contradiction_test_o
  CMP r5,r8
  JMP[NE] @mth_contradiction_test_fail

  LD r15,r0,@mth_contradiction_test_ret
  RET

; r1=support, r2=oppose, r3=expected cause.
mth_contradiction_test_reject:
  ST r15,r0,@mth_contradiction_test_ret
  MOVI r8,@mth_contradiction_test_ec
  ST r3,r8,0
  CALL @mth_mirror_cycle_contradiction_f32
  CMP r1,r0
  JMP[NE] @mth_contradiction_test_fail
  LD r8,r0,@mth_contradiction_test_ec
  CMP r9,r8
  JMP[NE] @mth_contradiction_test_fail
  LD r15,r0,@mth_contradiction_test_ret
  RET

mth_contradiction_test_fail:
  MOVI r1,@mth_contradiction_test_bad
  CALL @mth_contradiction_test_puts
  HALT

mth_contradiction_test_puts:
  MOVI r4,255
mth_contradiction_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_contradiction_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_contradiction_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_contradiction_test_puts_word

mth_contradiction_test_pass:
.str "MTH CONTRADICTION PAIR PASS\n"
mth_contradiction_test_bad:
.str "MTH CONTRADICTION PAIR FAIL\n"

.org 4096
mth_contradiction_test_ret:
.word 0
mth_contradiction_test_s:
.word 0
mth_contradiction_test_o:
.word 0
mth_contradiction_test_ec:
.word 0
mth_contradiction_test_eb:
.word 0
