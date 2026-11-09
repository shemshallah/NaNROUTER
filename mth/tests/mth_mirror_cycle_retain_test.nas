; MTH cycle-bank retention fixture — NaN16 only.
;
; Current bank: base 1. Source bank: base 65. Tests exact midpoint blending,
; gain 0 (no change), gain 1 (copy), mirror-lane signs, and base/overlap/gain
; rejection.

.org 0
JMP @mth_retain_test_main
.include "../nan16/mth_mirror_cycle_retain.nas"

mth_retain_test_main:
  MOVI r0,0
  MOVI r13,1
  CALL @mth_retain_test_seed

  ; gain 0.5 -> midpoint
  MOVI r1,1
  MOVI r2,65
  MOVI r3,0
  MOVHI r3,0x3F00            ; 0.5
  CALL @mth_mirror_cycle_retain_f32
  CMP r1,r13
  JMP[NE] @mth_retain_test_fail
  CALL @mth_retain_test_expect_midpoint

  ; gain 0 -> unchanged
  MOVI r1,1
  MOVI r2,65
  MOVI r3,0
  CALL @mth_mirror_cycle_retain_f32
  CMP r1,r13
  JMP[NE] @mth_retain_test_fail
  CALL @mth_retain_test_expect_midpoint

  ; gain 1 -> copy source
  MOVI r1,1
  MOVI r2,65
  MOVI r3,0
  MOVHI r3,0x3F80            ; 1.0
  CALL @mth_mirror_cycle_retain_f32
  CMP r1,r13
  JMP[NE] @mth_retain_test_fail
  CALL @mth_retain_test_expect_source

  ; restore current, run midpoint again
  CALL @mth_retain_test_restore_current
  MOVI r1,1
  MOVI r2,65
  MOVI r3,0
  MOVHI r3,0x3F00
  CALL @mth_mirror_cycle_retain_f32
  CMP r1,r13
  JMP[NE] @mth_retain_test_fail
  CALL @mth_retain_test_expect_midpoint

  ; rejection: current base 0
  MOVI r1,0
  MOVI r2,65
  MOVI r3,0
  MOVHI r3,0x3F00
  MOVI r4,1
  CALL @mth_retain_test_reject
  ; source base 225
  MOVI r1,1
  MOVI r2,225
  MOVI r3,0
  MOVHI r3,0x3F00
  MOVI r4,2
  CALL @mth_retain_test_reject
  ; overlap: 1 and 17
  MOVI r1,1
  MOVI r2,17
  MOVI r3,0
  MOVHI r3,0x3F00
  MOVI r4,3
  CALL @mth_retain_test_reject
  ; negative gain
  MOVI r1,1
  MOVI r2,65
  MOVI r3,0
  MOVHI r3,0xBF80
  MOVI r4,4
  CALL @mth_retain_test_reject
  ; gain > 1
  MOVI r1,1
  MOVI r2,65
  MOVI r3,0
  MOVHI r3,0x4000
  MOVI r4,4
  CALL @mth_retain_test_reject

  ; Recovery: restore current and midpoint
  CALL @mth_retain_test_restore_current
  MOVI r1,1
  MOVI r2,65
  MOVI r3,0
  MOVHI r3,0x3F00
  CALL @mth_mirror_cycle_retain_f32
  CMP r1,r13
  JMP[NE] @mth_retain_test_fail
  CALL @mth_retain_test_expect_midpoint

  MOVI r1,@mth_retain_test_pass
  CALL @mth_retain_test_puts
  HALT

mth_retain_test_seed:
  ST r15,r0,@mth_retain_test_ret
  ; current (0,1) c0 lane0=1, lane1=-1
  MOVI r1,1
  MOVI r2,0
  MOVI r3,0
  MOVI r4,0
  MOVHI r4,0x3F80
  CALL @mth_retain_test_set
  MOVI r1,1
  MOVI r2,0
  MOVI r3,1
  MOVI r4,0
  MOVHI r4,0xBF80
  CALL @mth_retain_test_set
  ; source (0,65) c0 lane0=3, lane1=-3
  MOVI r1,65
  MOVI r2,0
  MOVI r3,0
  MOVI r4,0
  MOVHI r4,0x4040
  CALL @mth_retain_test_set
  MOVI r1,65
  MOVI r2,0
  MOVI r3,1
  MOVI r4,0
  MOVHI r4,0xC040
  CALL @mth_retain_test_set
  ; current (1,2) c1 lane0=2, lane1=-2
  MOVI r1,256
  MOVI r2,1
  MOVI r3,0
  MOVI r4,0
  MOVHI r4,0x4000
  CALL @mth_retain_test_set
  MOVI r1,256
  MOVI r2,1
  MOVI r3,1
  MOVI r4,0
  MOVHI r4,0xC000
  CALL @mth_retain_test_set
  ; source (65,66) c1 lane0=6, lane1=-6
  MOVI r1,14496
  MOVI r2,1
  MOVI r3,0
  MOVI r4,0
  MOVHI r4,0x40C0
  CALL @mth_retain_test_set
  MOVI r1,14496
  MOVI r2,1
  MOVI r3,1
  MOVI r4,0
  MOVHI r4,0xC0C0
  CALL @mth_retain_test_set
  ; current (0,2) c2 lane0=4, lane1=-4
  MOVI r1,2
  MOVI r2,2
  MOVI r3,0
  MOVI r4,0
  MOVHI r4,0x4080
  CALL @mth_retain_test_set
  MOVI r1,2
  MOVI r2,2
  MOVI r3,1
  MOVI r4,0
  MOVHI r4,0xC080
  CALL @mth_retain_test_set
  ; source (0,66) c2 lane0=8, lane1=-8
  MOVI r1,66
  MOVI r2,2
  MOVI r3,0
  MOVI r4,0
  MOVHI r4,0x4100
  CALL @mth_retain_test_set
  MOVI r1,66
  MOVI r2,2
  MOVI r3,1
  MOVI r4,0
  MOVHI r4,0xC100
  CALL @mth_retain_test_set
  LD r15,r0,@mth_retain_test_ret
  RET

mth_retain_test_restore_current:
  ST r15,r0,@mth_retain_test_ret
  MOVI r1,1
  MOVI r2,0
  MOVI r3,0
  MOVI r4,0
  MOVHI r4,0x3F80
  CALL @mth_retain_test_set
  MOVI r1,1
  MOVI r2,0
  MOVI r3,1
  MOVI r4,0
  MOVHI r4,0xBF80
  CALL @mth_retain_test_set
  MOVI r1,256
  MOVI r2,1
  MOVI r3,0
  MOVI r4,0
  MOVHI r4,0x4000
  CALL @mth_retain_test_set
  MOVI r1,256
  MOVI r2,1
  MOVI r3,1
  MOVI r4,0
  MOVHI r4,0xC000
  CALL @mth_retain_test_set
  MOVI r1,2
  MOVI r2,2
  MOVI r3,0
  MOVI r4,0
  MOVHI r4,0x4080
  CALL @mth_retain_test_set
  MOVI r1,2
  MOVI r2,2
  MOVI r3,1
  MOVI r4,0
  MOVHI r4,0xC080
  CALL @mth_retain_test_set
  LD r15,r0,@mth_retain_test_ret
  RET

mth_retain_test_expect_midpoint:
  ST r15,r0,@mth_retain_test_ret
  MOVI r1,1
  MOVI r2,0
  MOVI r3,0
  MOVI r4,0
  MOVHI r4,0x4000            ; 2.0
  CALL @mth_retain_test_expect
  MOVI r1,1
  MOVI r2,0
  MOVI r3,1
  MOVI r4,0
  MOVHI r4,0xC000            ; -2.0
  CALL @mth_retain_test_expect
  MOVI r1,256
  MOVI r2,1
  MOVI r3,0
  MOVI r4,0
  MOVHI r4,0x4080            ; 4.0
  CALL @mth_retain_test_expect
  MOVI r1,2
  MOVI r2,2
  MOVI r3,0
  MOVI r4,0
  MOVHI r4,0x40C0            ; 6.0
  CALL @mth_retain_test_expect
  LD r15,r0,@mth_retain_test_ret
  RET

mth_retain_test_expect_source:
  ST r15,r0,@mth_retain_test_ret
  MOVI r1,1
  MOVI r2,0
  MOVI r3,0
  MOVI r4,0
  MOVHI r4,0x4040            ; 3.0
  CALL @mth_retain_test_expect
  MOVI r1,1
  MOVI r2,0
  MOVI r3,1
  MOVI r4,0
  MOVHI r4,0xC040
  CALL @mth_retain_test_expect
  MOVI r1,256
  MOVI r2,1
  MOVI r3,0
  MOVI r4,0
  MOVHI r4,0x40C0            ; 6.0
  CALL @mth_retain_test_expect
  MOVI r1,2
  MOVI r2,2
  MOVI r3,0
  MOVI r4,0
  MOVHI r4,0x4100            ; 8.0
  CALL @mth_retain_test_expect
  LD r15,r0,@mth_retain_test_ret
  RET

; r1=pair id, r2=channel, r3=lane, r4=value
mth_retain_test_set:
  ADDI r6,r1,-1
  SHL r6,r6,6
  ADDI r6,r6,8192
  ADD r6,r6,r2
  SHL r7,r3,5
  ADD r6,r6,r7
  ST r4,r6,0
  RET

; r1=pair id, r2=channel, r3=lane, r4=expected
mth_retain_test_expect:
  ADDI r6,r1,-1
  SHL r6,r6,6
  ADDI r6,r6,8192
  ADD r6,r6,r2
  SHL r7,r3,5
  ADD r6,r6,r7
  LD r7,r6,0
  CMP r7,r4
  JMP[NE] @mth_retain_test_fail
  RET

; r1=current base, r2=source base, r3=gain, r4=expected cause
mth_retain_test_reject:
  ST r15,r0,@mth_retain_test_ret
  MOVI r8,@mth_retain_test_cause
  ST r4,r8,0
  CALL @mth_mirror_cycle_retain_f32
  CMP r1,r0
  JMP[NE] @mth_retain_test_fail
  LD r8,r0,@mth_retain_test_cause
  CMP r9,r8
  JMP[NE] @mth_retain_test_fail
  LD r15,r0,@mth_retain_test_ret
  RET

mth_retain_test_fail:
  MOVI r1,@mth_retain_test_bad
  CALL @mth_retain_test_puts
  HALT

mth_retain_test_puts:
  MOVI r4,255
mth_retain_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_retain_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_retain_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_retain_test_puts_word

mth_retain_test_pass:
.str "MTH CYCLE RETAIN PASS\n"
mth_retain_test_bad:
.str "MTH CYCLE RETAIN FAIL\n"

.org 4096
mth_retain_test_ret:
.word 0
mth_retain_test_cause:
.word 0
