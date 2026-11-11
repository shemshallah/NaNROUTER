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
  ; Initial meta-credit is 1.0 for every eligible proposer.
  MOVI r9,@mth_tm_test_credit
  ADD r9,r9,r8
  MOVI r11,0
  MOVHI r11,0x3F80
  ST r11,r9,0
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
  MOVI r7,@mth_tm_test_credit
  MOVI r11,@mth_tm_test_journal
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

  ; Every one of 255 proposer decisions is recorded by the native guest.
  ; Check final accepted journal entry (head 254, T[1,2,3]).
  MOVI r9,@mth_tm_test_journal
  MOVI r10,1270              ; entry 254 x 5 words
  ADD r9,r9,r10
  LD r10,r9,0
  MOVI r11,254
  CMP r10,r11
  JMP[NE] @mth_tm_test_fail
  LD r10,r9,1
  MOVI r11,0x13E8
  MOVHI r11,4                ; offset = 267240 = 0x000413E8
  CMP r10,r11
  JMP[NE] @mth_tm_test_fail
  LD r10,r9,2
  CMP r10,r13               ; accepted
  JMP[NE] @mth_tm_test_fail
  LD r10,r9,3
  MOVI r11,0
  MOVHI r11,0x3F7F
  CMP r10,r11
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
  MOVI r7,@mth_tm_test_credit
  MOVI r11,@mth_tm_test_journal
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

  ; Rejection teaches meta to downweight head 0 on the next proposal.
  LD r9,r0,@mth_tm_test_credit
  MOVI r10,0
  MOVHI r10,0x3F60           ; 7/8 = .875 credit
  CMP r9,r10
  JMP[NE] @mth_tm_test_fail
  ; Restore full credit to isolate the next exact-math acceptance check.
  MOVI r10,0
  MOVHI r10,0x3F80
  ST r10,r0,@mth_tm_test_credit

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

  ; Learned meta-credit modifies subsequent update magnitude without ever
  ; removing candidate access (minimum scalar multiplier 1/4).
  MOVI r11,0
  MOVHI r11,0x3F00           ; credit 0.5
  ST r11,r0,@mth_tm_test_credit
  CALL @mth_tm_test_single      ; another +.5 request to reverse lane
  CMP r1,r13
  JMP[NE] @mth_tm_test_fail
  LD r9,r0,@mth_tm_test_tiles+5
  MOVI r10,0
  MOVHI r10,0x3F50           ; .5 + (.5 * .625) = .8125
  CMP r9,r10
  JMP[NE] @mth_tm_test_fail
  LD r9,r0,@mth_tm_test_credit
  MOVI r10,0
  MOVHI r10,0x3F10           ; EMA .5 -> .5625
  CMP r9,r10
  JMP[NE] @mth_tm_test_fail

  ; Invalid semantic head coordinate 255 must never be repaired by aliasing.
  MOVI r11,255
  ST r11,r0,@mth_tm_test_proposals+1
  CALL @mth_tm_test_single
  CMP r1,r0
  JMP[NE] @mth_tm_test_fail

  ; Emit one *native-authored* verified admitted journal entry for the
  ; external storage transport CI. All numbers emitted are raw U32 hex,
  ; not host-computed model values. The preceding test verified acceptance.
  MOVI r1,@mth_tm_test_journal_prefix
  CALL @mth_tm_test_puts
  LD r1,r0,@mth_tm_test_proposals
  CALL @mth_tm_test_hex32
  MOVI r1,32
  PUTC r1
  LD r1,r0,@mth_tm_test_proposals+1
  CALL @mth_tm_test_hex32
  MOVI r1,32
  PUTC r1
  LD r1,r0,@mth_tm_test_proposals+2
  CALL @mth_tm_test_hex32
  MOVI r1,32
  PUTC r1
  LD r1,r0,@mth_tm_test_proposals+3
  CALL @mth_tm_test_hex32
  MOVI r1,32
  PUTC r1
  LD r1,r0,@mth_tm_test_journal+1
  CALL @mth_tm_test_hex32
  MOVI r1,32
  PUTC r1
  LD r1,r0,@mth_tm_test_journal+3
  CALL @mth_tm_test_hex32
  MOVI r1,10
  PUTC r1

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
  MOVI r7,@mth_tm_test_credit
  MOVI r11,@mth_tm_test_journal
  MOVI r12,@mth_tm_test_frame
  CALL @mth_trihead_meta_feedback_f32
  LD r15,r0,@mth_tm_test_single_link
  RET

; Native U32 -> exact eight capital hex digit printer, no host formatters.
mth_tm_test_hex32:
  MOVI r3,28
mth_tm_test_hex_nibble:
  SHR r2,r1,r3
  MOVI r4,15
  BOOL.8 r2,r2,r4
  MOVI r4,10
  CMP r2,r4
  JMP[LT] @mth_tm_test_hex_decimal
  ADDI r2,r2,55
  JMP @mth_tm_test_hex_emit
mth_tm_test_hex_decimal:
  ADDI r2,r2,48
mth_tm_test_hex_emit:
  PUTC r2
  ADDI r3,r3,-4
  CMP r3,r0
  JMP[GE] @mth_tm_test_hex_nibble
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
.word 0,0,0,0,0,0,0,0,0,0,0,0,0
mth_tm_test_single_link:
.word 0
mth_tm_test_journal_prefix:
.str "MTH_META_ACCEPTED_HEX "
mth_tm_test_pass:
.str "MTH TRIHEAD META FEEDBACK PASS\n"
mth_tm_test_bad:
.str "MTH TRIHEAD META FEEDBACK FAIL\n"
.org 40960
mth_tm_test_credit:
.word 0
.org 42000
mth_tm_test_proposals:
.word 0
.org 45000
mth_tm_test_journal:
.word 0
