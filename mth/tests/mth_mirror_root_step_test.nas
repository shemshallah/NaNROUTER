; MTH Round 026 pair-lane mirror-root step fixture — NaN16 only.
;
; Checks, with exact integer word comparisons:
;   * positive and negative gradients,
;   * clamping to +0.05 and -0.05,
;   * opposite-sign lane updates (lane0 -= delta, lane1 += delta),
;   * atomic rejection of NaN / +inf / -inf at the first and last slot,
;   * the exact 26-word boundary: slot 25 updated, slot 26 sentinel intact.
;
; All lane and delta values are generated inside the guest. The fixture does
; not use host-supplied expected arrays; it checks the exact binary32 words.

.org 0
JMP @mth_mirror_test_main
.include "../nan16/mth_mirror_root_step.nas"

mth_mirror_test_main:
  MOVI r13,1

  ; ---- Case A: zero lanes, patterned gradients.
  ; lane0 = 0 - delta, lane1 = 0 + delta, so every expected word is an exact
  ; sign image of the clamped gradient.
  CALL @mth_mirror_test_zero_lanes
  CALL @mth_mirror_test_fill_delta

  MOVI r4,@mth_mirror_test_delta
  MOVI r6,0
  MOVHI r6,0x3D00            ; delta[0] = +0.03125
  ST r6,r4,0
  MOVI r6,0
  MOVHI r6,0xBC80            ; delta[1] = -0.015625
  ST r6,r4,1
  MOVI r6,0
  MOVHI r6,0x42C8            ; delta[2] = +100.0 -> clamp +0.05
  ST r6,r4,2
  MOVI r6,0
  MOVHI r6,0xC2C8            ; delta[3] = -100.0 -> clamp -0.05
  ST r6,r4,3
  MOVI r6,0
  MOVHI r6,0x3C80            ; delta[25] = +0.015625 (last slot)
  ST r6,r4,25

  MOVI r1,@mth_mirror_test_lane0
  MOVI r2,@mth_mirror_test_lane1
  MOVI r3,@mth_mirror_test_delta
  CALL @mth_mirror_root_step
  CMP r1,r13
  JMP[NE] @mth_mirror_test_fail
  CMP r9,r0
  JMP[NE] @mth_mirror_test_fail

  ; Slots 4..24 retain the default +0.0078125 gradient.
  MOVI r6,4
  MOVI r7,25
  MOVI r8,@mth_mirror_test_lane0
  MOVI r9,@mth_mirror_test_lane1
  MOVI r10,0
  MOVHI r10,0xBC00           ; lane0 = -0.0078125
  MOVI r11,0
  MOVHI r11,0x3C00           ; lane1 = +0.0078125
mth_mirror_test_case_a_loop:
  ADD r12,r8,r6
  LD r12,r12,0
  CMP r12,r10
  JMP[NE] @mth_mirror_test_fail
  ADD r12,r9,r6
  LD r12,r12,0
  CMP r12,r11
  JMP[NE] @mth_mirror_test_fail
  ADD r6,r6,r13
  CMP r6,r7
  JMP[LT] @mth_mirror_test_case_a_loop

  ; delta[0]=+0.03125 -> lane0=-0.03125, lane1=+0.03125.
  MOVI r6,0
  MOVI r7,0
  MOVHI r7,0xBD00
  MOVI r8,0
  MOVHI r8,0x3D00
  CALL @mth_mirror_test_check_pair

  ; delta[1]=-0.015625 -> lane0=+0.015625, lane1=-0.015625.
  MOVI r6,1
  MOVI r7,0
  MOVHI r7,0x3C80
  MOVI r8,0
  MOVHI r8,0xBC80
  CALL @mth_mirror_test_check_pair

  ; delta[2]=+100 -> clamp +0.05 -> lane0=-0.05, lane1=+0.05.
  MOVI r6,2
  MOVI r7,0xCCCD
  MOVHI r7,0xBD4C
  MOVI r8,0xCCCD
  MOVHI r8,0x3D4C
  CALL @mth_mirror_test_check_pair

  ; delta[3]=-100 -> clamp -0.05 -> lane0=+0.05, lane1=-0.05.
  MOVI r6,3
  MOVI r7,0xCCCD
  MOVHI r7,0x3D4C
  MOVI r8,0xCCCD
  MOVHI r8,0xBD4C
  CALL @mth_mirror_test_check_pair

  ; delta[25]=+0.015625 -> lane0=-0.015625, lane1=+0.015625.
  MOVI r6,25
  MOVI r7,0
  MOVHI r7,0xBC80
  MOVI r8,0
  MOVHI r8,0x3C80
  CALL @mth_mirror_test_check_pair

  ; Word 25 was updated above; word 26 must remain the sentinel.
  CALL @mth_mirror_test_check_sentinels

  ; ---- Case B: non-zero lanes, exact finite gradients.
  ; lane0 = 1.0, lane1 = 2.0; delta[0]=+0.03125, delta[1]=-0.015625,
  ; delta[25]=+0.015625; all other gradients are +0.0.
  CALL @mth_mirror_test_fill_lanes
  CALL @mth_mirror_test_zero_delta

  MOVI r4,@mth_mirror_test_delta
  MOVI r6,0
  MOVHI r6,0x3D00
  ST r6,r4,0
  MOVI r6,0
  MOVHI r6,0xBC80
  ST r6,r4,1
  MOVI r6,0
  MOVHI r6,0x3C80
  ST r6,r4,25

  MOVI r1,@mth_mirror_test_lane0
  MOVI r2,@mth_mirror_test_lane1
  MOVI r3,@mth_mirror_test_delta
  CALL @mth_mirror_root_step
  CMP r1,r13
  JMP[NE] @mth_mirror_test_fail
  CMP r9,r0
  JMP[NE] @mth_mirror_test_fail

  ; 1.0 - 0.03125 = 0.96875; 2.0 + 0.03125 = 2.03125.
  MOVI r6,0
  MOVI r7,0
  MOVHI r7,0x3F78
  MOVI r8,0
  MOVHI r8,0x4002
  CALL @mth_mirror_test_check_pair

  ; 1.0 + 0.015625 = 1.015625; 2.0 - 0.015625 = 1.984375.
  MOVI r6,1
  MOVI r7,0
  MOVHI r7,0x3F82
  MOVI r8,0
  MOVHI r8,0x3FFE
  CALL @mth_mirror_test_check_pair

  ; 1.0 - 0.015625 = 0.984375; 2.0 + 0.015625 = 2.015625.
  MOVI r6,25
  MOVI r7,0
  MOVHI r7,0x3F7C
  MOVI r8,0
  MOVHI r8,0x4001
  CALL @mth_mirror_test_check_pair

  ; Zero gradient leaves a middle slot at 1.0 / 2.0.
  MOVI r6,2
  MOVI r7,0
  MOVHI r7,0x3F80
  MOVI r8,0
  MOVHI r8,0x4000
  CALL @mth_mirror_test_check_pair

  ; And the far middle slot also stays at 1.0 / 2.0.
  MOVI r6,24
  MOVI r7,0
  MOVHI r7,0x3F80
  MOVI r8,0
  MOVHI r8,0x4000
  CALL @mth_mirror_test_check_pair

  CALL @mth_mirror_test_check_sentinels

  ; ---- Atomic rejection: NaN, +inf, -inf at slot 0 and slot 25.
  MOVI r4,0
  MOVHI r4,0x7FC0           ; NaN
  MOVI r5,0
  CALL @mth_mirror_test_reject_case

  MOVI r4,0
  MOVHI r4,0x7F80           ; +inf
  MOVI r5,0
  CALL @mth_mirror_test_reject_case

  MOVI r4,0
  MOVHI r4,0xFF80           ; -inf
  MOVI r5,0
  CALL @mth_mirror_test_reject_case

  MOVI r4,0
  MOVHI r4,0x7FC0           ; NaN at the last slot
  MOVI r5,25
  CALL @mth_mirror_test_reject_case

  MOVI r4,0
  MOVHI r4,0x7F80           ; +inf at the last slot
  MOVI r5,25
  CALL @mth_mirror_test_reject_case

  MOVI r4,0
  MOVHI r4,0xFF80           ; -inf at the last slot
  MOVI r5,25
  CALL @mth_mirror_test_reject_case

  MOVI r1,@mth_mirror_test_pass
  CALL @mth_mirror_test_puts
  HALT

mth_mirror_test_fail:
  MOVI r1,@mth_mirror_test_bad
  CALL @mth_mirror_test_puts
  HALT

; ---- Helpers ------------------------------------------------------------

; Fill lane0 0..25 with +0.0 and lane1 0..25 with +0.0; set word 26 sentinels.
mth_mirror_test_zero_lanes:
  MOVI r6,0
  MOVI r7,26
  MOVI r8,@mth_mirror_test_lane0
  MOVI r9,@mth_mirror_test_lane1
mth_mirror_test_zero_lanes_loop:
  ADD r10,r8,r6
  ST r0,r10,0
  ADD r10,r9,r6
  ST r0,r10,0
  ADD r6,r6,r13
  CMP r6,r7
  JMP[LT] @mth_mirror_test_zero_lanes_loop
  MOVI r10,0xBEEF
  MOVHI r10,0xDEAD           ; lane0[26] = 0xDEADBEEF
  ST r10,r8,26
  MOVI r10,0xDEAD
  MOVHI r10,0xBEEF           ; lane1[26] = 0xBEEFDEAD
  ST r10,r9,26
  RET

; Fill lane0 0..25 with 1.0 and lane1 0..25 with 2.0; set word 26 sentinels.
mth_mirror_test_fill_lanes:
  MOVI r6,0
  MOVI r7,26
  MOVI r8,@mth_mirror_test_lane0
  MOVI r9,@mth_mirror_test_lane1
  MOVI r10,0
  MOVHI r10,0x3F80           ; +1.0
  MOVI r11,0
  MOVHI r11,0x4000           ; +2.0
mth_mirror_test_fill_lanes_loop:
  ADD r12,r8,r6
  ST r10,r12,0
  ADD r12,r9,r6
  ST r11,r12,0
  ADD r6,r6,r13
  CMP r6,r7
  JMP[LT] @mth_mirror_test_fill_lanes_loop
  MOVI r12,0xBEEF
  MOVHI r12,0xDEAD           ; lane0[26] = 0xDEADBEEF
  ST r12,r8,26
  MOVI r12,0xDEAD
  MOVHI r12,0xBEEF           ; lane1[26] = 0xBEEFDEAD
  ST r12,r9,26
  RET

; Fill delta 0..25 with +0.0078125; set word 26 sentinel.
mth_mirror_test_fill_delta:
  MOVI r6,0
  MOVI r7,26
  MOVI r8,@mth_mirror_test_delta
  MOVI r9,0
  MOVHI r9,0x3C00            ; +0.0078125
mth_mirror_test_fill_delta_loop:
  ADD r10,r8,r6
  ST r9,r10,0
  ADD r6,r6,r13
  CMP r6,r7
  JMP[LT] @mth_mirror_test_fill_delta_loop
  MOVI r10,0x5A5A
  MOVHI r10,0x5A5A           ; delta[26] = 0x5A5A5A5A
  ST r10,r8,26
  RET

; Fill delta 0..25 with +0.0; set word 26 sentinel.
mth_mirror_test_zero_delta:
  MOVI r6,0
  MOVI r7,26
  MOVI r8,@mth_mirror_test_delta
mth_mirror_test_zero_delta_loop:
  ADD r9,r8,r6
  ST r0,r9,0
  ADD r6,r6,r13
  CMP r6,r7
  JMP[LT] @mth_mirror_test_zero_delta_loop
  MOVI r9,0x5A5A
  MOVHI r9,0x5A5A            ; delta[26] = 0x5A5A5A5A
  ST r9,r8,26
  RET

; Check lane0[0..25] == 1.0 and lane1[0..25] == 2.0.
mth_mirror_test_check_pristine:
  MOVI r6,0
  MOVI r7,26
  MOVI r8,0
  MOVHI r8,0x3F80
  MOVI r9,0
  MOVHI r9,0x4000
  MOVI r10,@mth_mirror_test_lane0
  MOVI r11,@mth_mirror_test_lane1
mth_mirror_test_check_pristine_loop:
  ADD r12,r10,r6
  LD r12,r12,0
  CMP r12,r8
  JMP[NE] @mth_mirror_test_fail
  ADD r12,r11,r6
  LD r12,r12,0
  CMP r12,r9
  JMP[NE] @mth_mirror_test_fail
  ADD r6,r6,r13
  CMP r6,r7
  JMP[LT] @mth_mirror_test_check_pristine_loop
  RET

; r6 = index, r7 = expected lane0 word, r8 = expected lane1 word.
mth_mirror_test_check_pair:
  MOVI r9,@mth_mirror_test_lane0
  ADD r9,r9,r6
  LD r9,r9,0
  CMP r9,r7
  JMP[NE] @mth_mirror_test_fail
  MOVI r9,@mth_mirror_test_lane1
  ADD r9,r9,r6
  LD r9,r9,0
  CMP r9,r8
  JMP[NE] @mth_mirror_test_fail
  RET

; Check the sentinel at word 26 of both lanes and of delta.
mth_mirror_test_check_sentinels:
  MOVI r6,@mth_mirror_test_lane0
  LD r7,r6,26
  MOVI r8,0xBEEF
  MOVHI r8,0xDEAD
  CMP r7,r8
  JMP[NE] @mth_mirror_test_fail
  MOVI r6,@mth_mirror_test_lane1
  LD r7,r6,26
  MOVI r8,0xDEAD
  MOVHI r8,0xBEEF
  CMP r7,r8
  JMP[NE] @mth_mirror_test_fail
  MOVI r6,@mth_mirror_test_delta
  LD r7,r6,26
  MOVI r8,0x5A5A
  MOVHI r8,0x5A5A
  CMP r7,r8
  JMP[NE] @mth_mirror_test_fail
  RET

; Atomic rejection case. Inputs r4 = non-finite word, r5 = slot 0 or 25.
; Resets both lanes to 1.0 / 2.0, zeros all 26 deltas, installs the bad word,
; calls the kernel, requires r1=0 and r9=1, and proves all 26 lane words are
; unchanged. Saves the outer return link because this helper calls others.
mth_mirror_test_reject_case:
  ST r15,r0,@mth_mirror_test_save_ret
  CALL @mth_mirror_test_fill_lanes
  CALL @mth_mirror_test_zero_delta
  MOVI r6,@mth_mirror_test_delta
  ADD r6,r6,r5
  ST r4,r6,0
  MOVI r1,@mth_mirror_test_lane0
  MOVI r2,@mth_mirror_test_lane1
  MOVI r3,@mth_mirror_test_delta
  CALL @mth_mirror_root_step
  CMP r1,r0
  JMP[NE] @mth_mirror_test_fail
  CMP r9,r13
  JMP[NE] @mth_mirror_test_fail
  CALL @mth_mirror_test_check_pristine
  CALL @mth_mirror_test_check_sentinels
  LD r15,r0,@mth_mirror_test_save_ret
  RET

mth_mirror_test_puts:
  MOVI r4,255
mth_mirror_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_mirror_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_mirror_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_mirror_test_puts_word

.org 512
mth_mirror_test_save_ret:
.word 0
.org 1024
mth_mirror_test_lane0:
.word 0
.org 2048
mth_mirror_test_lane1:
.word 0
.org 3072
mth_mirror_test_delta:
.word 0
.org 3584
mth_mirror_test_pass:
.str "MTH MIRROR ROOT STEP PASS\n"
mth_mirror_test_bad:
.str "MTH MIRROR ROOT STEP FAIL\n"
