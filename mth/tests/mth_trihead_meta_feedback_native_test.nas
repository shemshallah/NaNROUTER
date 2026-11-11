; All 255 eligible heads participate in native shared-tensor candidate feedback.
.org 0
JMP @mth_tm_test_main
.include "../nan16/mth_hypertensor256_mirror_arena_map.nas"
.include "../nan16/mth_trihead_meta_feedback_f32.nas"

mth_tm_test_main:
  MOVI r0,0
  MOVI r13,1
  ; Grant a permission snapshot for every non-void head, including head 0
  ; under this explicitly authorized test-only control-plane fixture.
  ; Build 255 proposals from all 0..254, targeting the SAME tensor triple:
  ; T[1,2,3], delta=1/256, meta feedback target=1.0.
  MOVI r8,0
mth_tm_test_build:
  MOVI r9,@mth_tm_test_permissions
  ADD r9,r9,r8
  ST r13,r9,0
  MOVI r10,6
  MUL r10,r10,r8
  MOVI r9,@mth_tm_test_proposals
  ADD r10,r9,r10
  ST r8,r10,0                  ; proposer ID
  ST r13,r10,1                 ; h = 1
  MOVI r11,2
  ST r11,r10,2                 ; a = 2
  MOVI r11,3
  ST r11,r10,3                 ; b = 3
  MOVI r11,0
  MOVHI r11,0x3B80             ; delta 1/256
  ST r11,r10,4
  ST r0,r10,5                  ; trusted tile slot 0
  ADDI r8,r8,1
  MOVI r11,255
  CMP r8,r11
  JMP[LT] @mth_tm_test_build

  MOVI r1,@mth_tm_test_proposals
  MOVI r2,255
  MOVI r3,@mth_tm_test_permissions
  MOVI r4,@mth_tm_test_tiles
  MOVI r5,7
  MOVI r6,@mth_tm_test_stats
  MOVI r12,@mth_tm_test_frame
  CALL @mth_trihead_meta_feedback_f32
  CMP r1,r13
  JMP[NE] @mth_tm_test_fail
  LD r9,r0,@mth_tm_test_stats
  MOVI r10,255
  CMP r9,r10
  JMP[NE] @mth_tm_test_fail
  LD r9,r0,@mth_tm_test_stats+1
  CMP r9,r0
  JMP[NE] @mth_tm_test_fail
  LD r9,r0,@mth_tm_test_stats+3
  CMP r9,r10
  JMP[NE] @mth_tm_test_fail
  LD r9,r0,@mth_tm_test_tiles+1
  MOVI r10,0
  MOVHI r10,0x3F7F             ; 255/256
  CMP r9,r10
  JMP[NE] @mth_tm_test_fail

  ; Malicious proposer 255 rejected before ANY weight or stats mutation.
  MOVI r11,255
  ST r11,r0,@mth_tm_test_proposals
  MOVI r11,777
  ST r11,r0,@mth_tm_test_stats
  CALL @mth_tm_test_single
  CMP r1,r0
  JMP[NE] @mth_tm_test_fail
  LD r9,r0,@mth_tm_test_tiles+1
  MOVI r10,0
  MOVHI r10,0x3F7F
  CMP r9,r10
  JMP[NE] @mth_tm_test_fail
  LD r9,r0,@mth_tm_test_stats
  MOVI r10,777
  CMP r9,r10
  JMP[NE] @mth_tm_test_fail

  ; A valid head without an actual permission cannot self-write.
  MOVI r11,17
  ST r11,r0,@mth_tm_test_proposals
  MOVI r9,@mth_tm_test_permissions
  ADDI r9,r9,17
  ST r0,r9,0
  CALL @mth_tm_test_single
  CMP r1,r0
  JMP[NE] @mth_tm_test_fail
  MOVI r9,@mth_tm_test_permissions
  ADDI r9,r9,17
  ST r13,r9,0                 ; restore permission
  MOVI r11,0
  ST r11,r0,@mth_tm_test_proposals

  ; Reject a stale epoch.
  MOVI r1,@mth_tm_test_proposals
  MOVI r2,1
  MOVI r3,@mth_tm_test_permissions
  MOVI r4,@mth_tm_test_tiles
  MOVI r5,8
  MOVI r6,@mth_tm_test_stats
  MOVI r12,@mth_tm_test_frame
  CALL @mth_trihead_meta_feedback_f32
  CMP r1,r0
  JMP[NE] @mth_tm_test_fail

  ; Native independent feedback vetoes an actively harmful delta.
  MOVI r11,0
  MOVHI r11,0xBF00             ; -0.5
  ST r11,r0,@mth_tm_test_proposals+4
  CALL @mth_tm_test_single
  CMP r1,r13
  JMP[NE] @mth_tm_test_fail
  LD r9,r0,@mth_tm_test_stats
  CMP r9,r0
  JMP[NE] @mth_tm_test_fail
  LD r9,r0,@mth_tm_test_stats+1
  CMP r9,r13
  JMP[NE] @mth_tm_test_fail
  LD r9,r0,@mth_tm_test_tiles+1
  MOVI r10,0
  MOVHI r10,0x3F7F
  CMP r9,r10
  JMP[NE] @mth_tm_test_fail

  ; A small beneficial delta reaches the independent feedback target.
  MOVI r11,0
  MOVHI r11,0x3B80
  ST r11,r0,@mth_tm_test_proposals+4
  CALL @mth_tm_test_single
  CMP r1,r13
  JMP[NE] @mth_tm_test_fail
  LD r9,r0,@mth_tm_test_stats
  CMP r9,r13
  JMP[NE] @mth_tm_test_fail
  LD r9,r0,@mth_tm_test_tiles+1
  MOVI r10,0
  MOVHI r10,0x3F80             ; exactly 1.0
  CMP r9,r10
  JMP[NE] @mth_tm_test_fail

  ; Reversed mirror direction is a DISTINCT trainable scalar in the
  ; SAME canonical mirror cell, with an offset exactly +4 bytes.
  MOVI r11,3
  ST r11,r0,@mth_tm_test_proposals+2
  MOVI r11,2
  ST r11,r0,@mth_tm_test_proposals+3
  MOVI r11,1
  ST r11,r0,@mth_tm_test_proposals+5
  MOVI r11,0
  MOVHI r11,0x3F00             ; +0.5
  ST r11,r0,@mth_tm_test_proposals+4
  CALL @mth_tm_test_single
  CMP r1,r13
  JMP[NE] @mth_tm_test_fail
  LD r9,r0,@mth_tm_test_tiles+5
  MOVI r10,0
  MOVHI r10,0x3F00
  CMP r9,r10
  JMP[NE] @mth_tm_test_fail
  LD r9,r0,@mth_tm_test_tiles+1
  MOVI r10,0
  MOVHI r10,0x3F80
  CMP r9,r10
  JMP[NE] @mth_tm_test_fail

  ; Invalid semantic head coordinate 255 must never be repaired by aliasing.
  MOVI r11,255
  ST r11,r0,@mth_tm_test_proposals+1
  CALL @mth_tm_test_single
  CMP r1,r0
  JMP[NE] @mth_tm_test_fail

  MOVI r1,@mth_tm_test_pass
  CALL @mth_tm_test_puts
  HALT

mth_tm_test_single:
  ; Store caller return link in non-aliasing static test-only slot.
  ; Meta kernel deliberately clobbers r14 during preflight.
  ST r15,r0,@mth_tm_test_single_link
  MOVI r1,@mth_tm_test_proposals
  MOVI r2,1
  MOVI r3,@mth_tm_test_permissions
  MOVI r4,@mth_tm_test_tiles
  MOVI r5,7
  MOVI r6,@mth_tm_test_stats
  MOVI r12,@mth_tm_test_frame
  CALL @mth_trihead_meta_feedback_f32
  LD r15,r0,@mth_tm_test_single_link
  RET

mth_tm_test_fail:
  MOVI r1,@mth_tm_test_bad
  CALL @mth_tm_test_puts
  HALT
mth_tm_test_puts:
  MOVI r4,255
mth_tm_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_tm_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_tm_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_tm_test_puts_word

.org 40000
mth_tm_test_permissions:
.word 0
.org 40512
mth_tm_test_tiles:
.word 267240,0,0x3F800000,7
.word 267244,0,0x3F800000,7
mth_tm_test_stats:
.word 0,0,0,0
mth_tm_test_frame:
.word 0,0,0,0,0,0,0,0,0,0,0,0
mth_tm_test_single_link:
.word 0
mth_tm_test_pass:
.str "MTH TRIHEAD META FEEDBACK PASS\n"
mth_tm_test_bad:
.str "MTH TRIHEAD META FEEDBACK FAIL\n"
.org 42000
mth_tm_test_proposals:
.word 0
