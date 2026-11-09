; MTH two-lane evidence state fixture — NaN16 only.
;
; Physical triangle (0,1,2): pair ids 1, 256, 2. Tests support-only,
; refute-only, both, unknown, negative-evidence, invalid heads, non-finite
; lanes, atomic state clearing, and recovery.

.org 0
JMP @mth_evidence_test_main
.include "../nan16/mth_mirror_evidence_cycle_state.nas"

mth_evidence_test_main:
  MOVI r0,0
  MOVI r13,1

  ; support only
  CALL @mth_evidence_test_zero
  MOVI r1,1
  MOVI r2,0
  MOVI r3,0
  MOVHI r3,0x3F80
  CALL @mth_evidence_test_set
  MOVI r3,0
  MOVHI r3,0x3F80            ; expected support 1
  MOVI r4,0
  MOVI r5,1
  CALL @mth_evidence_test_expect

  ; refute only
  CALL @mth_evidence_test_zero
  MOVI r1,256
  MOVI r2,1
  MOVI r3,0
  MOVHI r3,0x3F80
  CALL @mth_evidence_test_set
  MOVI r3,0
  MOVI r4,0
  MOVHI r4,0x3F80
  MOVI r5,2
  CALL @mth_evidence_test_expect

  ; both
  CALL @mth_evidence_test_zero
  MOVI r1,1
  MOVI r2,0
  MOVI r3,0
  MOVHI r3,0x3F80
  CALL @mth_evidence_test_set
  MOVI r1,256
  MOVI r2,1
  MOVI r3,0
  MOVHI r3,0x3F80
  CALL @mth_evidence_test_set
  MOVI r3,0
  MOVHI r3,0x3F80
  MOVI r4,0
  MOVHI r4,0x3F80
  MOVI r5,3
  CALL @mth_evidence_test_expect

  ; unknown
  CALL @mth_evidence_test_zero
  MOVI r3,0
  MOVI r4,0
  MOVI r5,0
  CALL @mth_evidence_test_expect

  ; negative support is not positive support
  CALL @mth_evidence_test_zero
  MOVI r1,1
  MOVI r2,0
  MOVI r3,0
  MOVHI r3,0xBF80
  CALL @mth_evidence_test_set
  MOVI r3,0
  MOVHI r3,0xBF80
  MOVI r4,0
  MOVI r5,0
  CALL @mth_evidence_test_expect

  ; invalid heads
  MOVI r1,0
  MOVI r2,2
  MOVI r6,1
  CALL @mth_evidence_test_reject
  MOVI r1,255
  MOVI r2,255
  MOVI r6,1
  CALL @mth_evidence_test_reject
  MOVI r1,1
  MOVI r2,256
  MOVI r6,1
  CALL @mth_evidence_test_reject

  ; non-finite lane
  MOVI r1,1
  MOVI r2,0
  MOVI r3,0
  MOVHI r3,0x7F80
  CALL @mth_evidence_test_set
  MOVI r1,1
  MOVI r2,2
  MOVI r6,2
  CALL @mth_evidence_test_reject

  ; recovery
  CALL @mth_evidence_test_zero
  MOVI r3,0
  MOVI r4,0
  MOVI r5,0
  CALL @mth_evidence_test_expect

  MOVI r1,@mth_evidence_test_pass
  CALL @mth_evidence_test_puts
  HALT

; r1=id, r2=channel, r3=value
mth_evidence_test_set:
  ADDI r7,r1,-1
  SHL r7,r7,6
  ADDI r7,r7,8192
  ADD r7,r7,r2
  ST r3,r7,0
  RET

; zero triangle ids 1,256,2 channels 0 and 1
mth_evidence_test_zero:
  ST r15,r0,@mth_evidence_test_zero_ret
  MOVI r1,1
  MOVI r2,0
  MOVI r3,0
  CALL @mth_evidence_test_set
  MOVI r1,256
  MOVI r2,0
  MOVI r3,0
  CALL @mth_evidence_test_set
  MOVI r1,2
  MOVI r2,0
  MOVI r3,0
  CALL @mth_evidence_test_set
  MOVI r1,1
  MOVI r2,1
  MOVI r3,0
  CALL @mth_evidence_test_set
  MOVI r1,256
  MOVI r2,1
  MOVI r3,0
  CALL @mth_evidence_test_set
  MOVI r1,2
  MOVI r2,1
  MOVI r3,0
  CALL @mth_evidence_test_set
  LD r15,r0,@mth_evidence_test_zero_ret
  RET

; r3=expected support, r4=expected refute, r5=expected state; a=1,b=2
mth_evidence_test_expect:
  ST r15,r0,@mth_evidence_test_exp_ret
  ST r3,r0,@mth_evidence_test_es
  ST r4,r0,@mth_evidence_test_er
  ST r5,r0,@mth_evidence_test_estate
  MOVI r1,1
  MOVI r2,2
  CALL @mth_mirror_evidence_cycle_state_f32
  CMP r1,r13
  JMP[NE] @mth_evidence_test_fail
  CMP r9,r0
  JMP[NE] @mth_evidence_test_fail
  LD r8,r0,@mth_evidence_test_es
  CMP r3,r8
  JMP[NE] @mth_evidence_test_fail
  LD r8,r0,@mth_evidence_test_er
  CMP r4,r8
  JMP[NE] @mth_evidence_test_fail
  LD r8,r0,@mth_evidence_test_estate
  CMP r5,r8
  JMP[NE] @mth_evidence_test_fail
  LD r15,r0,@mth_evidence_test_exp_ret
  RET

; r1=a, r2=b, r6=expected cause
mth_evidence_test_reject:
  ST r15,r0,@mth_evidence_test_rej_ret
  ST r6,r0,@mth_evidence_test_cause
  CALL @mth_mirror_evidence_cycle_state_f32
  CMP r1,r0
  JMP[NE] @mth_evidence_test_fail
  LD r8,r0,@mth_evidence_test_cause
  CMP r9,r8
  JMP[NE] @mth_evidence_test_fail
  CMP r3,r0
  JMP[NE] @mth_evidence_test_fail
  CMP r4,r0
  JMP[NE] @mth_evidence_test_fail
  CMP r5,r0
  JMP[NE] @mth_evidence_test_fail
  LD r15,r0,@mth_evidence_test_rej_ret
  RET

mth_evidence_test_fail:
  MOVI r1,@mth_evidence_test_bad
  CALL @mth_evidence_test_puts
  HALT

mth_evidence_test_puts:
  MOVI r4,255
mth_evidence_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_evidence_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_evidence_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_evidence_test_puts_word

mth_evidence_test_pass:
.str "MTH EVIDENCE CYCLE STATE PASS\n"
mth_evidence_test_bad:
.str "MTH EVIDENCE CYCLE STATE FAIL\n"

.org 4096
mth_evidence_test_zero_ret:
.word 0
mth_evidence_test_exp_ret:
.word 0
mth_evidence_test_rej_ret:
.word 0
mth_evidence_test_es:
.word 0
mth_evidence_test_er:
.word 0
mth_evidence_test_estate:
.word 0
mth_evidence_test_cause:
.word 0
