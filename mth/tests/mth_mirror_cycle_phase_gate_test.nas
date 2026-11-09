; MTH oscillatory gate fixture — NaN16 only.
;
; Tests constant phase, quarter-turn phase, a nonzero frequency, range
; clamping, domain rejection, and output atomicity.

.org 0
JMP @mth_phase_gate_test_main
.include "../nan16/mth_trig_sincos_f32.nas"
.include "../nan16/mth_mirror_cycle_phase_gate.nas"

mth_phase_gate_test_main:
  MOVI r0,0
  MOVI r13,1
  CALL @mth_phase_gate_test_init

  ; position 0, zero frequency/phase -> 0.5 everywhere
  MOVI r1,0
  CALL @mth_phase_gate_test_set_position
  CALL @mth_phase_gate_test_zero_freq
  CALL @mth_phase_gate_test_zero_phase
  MOVI r1,0
  MOVHI r1,0x3F00
  CALL @mth_phase_gate_test_fill_expected
  CALL @mth_phase_gate_test_run
  CALL @mth_phase_gate_test_check

  ; phase pattern 0, pi/2, pi, -pi/2 -> 0.5,1,0.5,0
  CALL @mth_phase_gate_test_pattern_phase
  CALL @mth_phase_gate_test_pattern_expected
  CALL @mth_phase_gate_test_run
  CALL @mth_phase_gate_test_check

  ; position 1, frequency 1, phase 0 -> 0.5*(1+sin(1))
  CALL @mth_phase_gate_test_zero_phase
  MOVI r6,0
mth_phase_gate_test_one_freq:
  MOVI r8,@mth_phase_gate_test_freq
  ADD r8,r8,r6
  MOVI r7,0
  MOVHI r7,0x3F80            ; 1.0
  ST r7,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_phase_gate_test_one_freq
  MOVI r1,1
  CALL @mth_phase_gate_test_set_position
  MOVI r1,0xB552
  MOVHI r1,0x3F6B            ; 0.9207355
  CALL @mth_phase_gate_test_fill_expected
  CALL @mth_phase_gate_test_run
  CALL @mth_phase_gate_test_check

  ; Reject position 4097.
  CALL @mth_phase_gate_test_sentinel
  MOVI r1,4097
  CALL @mth_phase_gate_test_set_position
  CALL @mth_phase_gate_test_call
  CMP r1,r0
  JMP[NE] @mth_phase_gate_test_fail
  MOVI r8,1
  CMP r9,r8
  JMP[NE] @mth_phase_gate_test_fail
  CALL @mth_phase_gate_test_check_sentinel

  ; Reject non-finite frequency.
  CALL @mth_phase_gate_test_sentinel
  MOVI r1,0
  CALL @mth_phase_gate_test_set_position
  MOVI r8,@mth_phase_gate_test_freq
  MOVI r7,0
  MOVHI r7,0x7F80
  ST r7,r8,0
  CALL @mth_phase_gate_test_call
  CMP r1,r0
  JMP[NE] @mth_phase_gate_test_fail
  MOVI r8,2
  CMP r9,r8
  JMP[NE] @mth_phase_gate_test_fail
  CALL @mth_phase_gate_test_check_sentinel

  ; Reject angle outside |128|: position 2, frequency 100.
  CALL @mth_phase_gate_test_sentinel
  MOVI r1,2
  CALL @mth_phase_gate_test_set_position
  MOVI r8,@mth_phase_gate_test_freq
  MOVI r7,0
  MOVHI r7,0x42C8            ; 100.0
  ST r7,r8,0
  CALL @mth_phase_gate_test_call
  CMP r1,r0
  JMP[NE] @mth_phase_gate_test_fail
  MOVI r8,3
  CMP r9,r8
  JMP[NE] @mth_phase_gate_test_fail
  CALL @mth_phase_gate_test_check_sentinel

  ; Recovery: zero frequency and phase, position 0.
  MOVI r1,0
  CALL @mth_phase_gate_test_set_position
  CALL @mth_phase_gate_test_zero_freq
  CALL @mth_phase_gate_test_zero_phase
  MOVI r1,0
  MOVHI r1,0x3F00
  CALL @mth_phase_gate_test_fill_expected
  CALL @mth_phase_gate_test_run
  CALL @mth_phase_gate_test_check

  MOVI r1,@mth_phase_gate_test_pass
  CALL @mth_phase_gate_test_puts
  HALT

mth_phase_gate_test_init:
  ST r15,r0,@mth_phase_gate_test_ret
  CALL @mth_phase_gate_test_zero_freq
  CALL @mth_phase_gate_test_zero_phase
  MOVI r1,0
  CALL @mth_phase_gate_test_set_position
  LD r15,r0,@mth_phase_gate_test_ret
  RET

mth_phase_gate_test_zero_freq:
  MOVI r6,0
mth_phase_gate_test_zf_loop:
  MOVI r8,@mth_phase_gate_test_freq
  ADD r8,r8,r6
  ST r0,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_phase_gate_test_zf_loop
  RET

mth_phase_gate_test_zero_phase:
  MOVI r6,0
mth_phase_gate_test_zp_loop:
  MOVI r8,@mth_phase_gate_test_phase
  ADD r8,r8,r6
  ST r0,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_phase_gate_test_zp_loop
  RET

mth_phase_gate_test_pattern_phase:
  ST r15,r0,@mth_phase_gate_test_ret
  MOVI r6,0
  MOVI r7,0
  MOVHI r7,0x3F00            ; 0.5 pi? use pi/2 = 0x3FC90FDB below
mth_phase_gate_test_pp_loop:
  MOVI r8,@mth_phase_gate_test_phase
  ADD r8,r8,r6
  ; c mod 4 pattern; use integer index
  MOVI r9,0x0FDB
  MOVHI r9,0x3FC9            ; pi/2
  MOVI r10,0x0FDB
  MOVHI r10,0x4049           ; pi
  MOVI r11,0x0FDB
  MOVHI r11,0xBFC9           ; -pi/2
  MOVI r12,4
  MOD r12,r6,r12
  CMP r12,r0
  JMP[EQ] @mth_phase_gate_test_pp_zero
  MOVI r14,1
  CMP r12,r14
  JMP[EQ] @mth_phase_gate_test_pp_half
  MOVI r14,2
  CMP r12,r14
  JMP[EQ] @mth_phase_gate_test_pp_pi
  ADD r9,r11,r0
  JMP @mth_phase_gate_test_pp_store
mth_phase_gate_test_pp_zero:
  MOVI r9,0
  JMP @mth_phase_gate_test_pp_store
mth_phase_gate_test_pp_half:
  ADD r9,r9,r0
  JMP @mth_phase_gate_test_pp_store
mth_phase_gate_test_pp_pi:
  ADD r9,r10,r0
mth_phase_gate_test_pp_store:
  ST r9,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_phase_gate_test_pp_loop
  LD r15,r0,@mth_phase_gate_test_ret
  RET

mth_phase_gate_test_pattern_expected:
  ST r15,r0,@mth_phase_gate_test_ret
  MOVI r6,0
mth_phase_gate_test_pe_loop:
  MOVI r8,@mth_phase_gate_test_expected
  ADD r8,r8,r6
  MOVI r9,4
  MOD r9,r6,r9
  CMP r9,r0
  JMP[EQ] @mth_phase_gate_test_pe_half
  MOVI r10,1
  CMP r9,r10
  JMP[EQ] @mth_phase_gate_test_pe_one
  MOVI r10,2
  CMP r9,r10
  JMP[EQ] @mth_phase_gate_test_pe_half
  MOVI r7,0
  JMP @mth_phase_gate_test_pe_store
mth_phase_gate_test_pe_half:
  MOVI r7,0
  MOVHI r7,0x3F00
  JMP @mth_phase_gate_test_pe_store
mth_phase_gate_test_pe_one:
  MOVI r7,0
  MOVHI r7,0x3F80
mth_phase_gate_test_pe_store:
  ST r7,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_phase_gate_test_pe_loop
  LD r15,r0,@mth_phase_gate_test_ret
  RET

mth_phase_gate_test_set_position:
  ST r1,r0,@mth_phase_gate_test_position
  RET

mth_phase_gate_test_fill_expected:
  ST r15,r0,@mth_phase_gate_test_ret
  MOVI r6,0
mth_phase_gate_test_fe_loop:
  MOVI r8,@mth_phase_gate_test_expected
  ADD r8,r8,r6
  ST r1,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_phase_gate_test_fe_loop
  LD r15,r0,@mth_phase_gate_test_ret
  RET

mth_phase_gate_test_run:
  ST r15,r0,@mth_phase_gate_test_ret
  CALL @mth_phase_gate_test_call
  CMP r1,r13
  JMP[NE] @mth_phase_gate_test_fail
  CMP r9,r0
  JMP[NE] @mth_phase_gate_test_fail
  LD r15,r0,@mth_phase_gate_test_ret
  RET

mth_phase_gate_test_call:
  ST r15,r0,@mth_phase_gate_test_call_ret
  MOVI r1,@mth_phase_gate_test_position
  LD r1,r1,0
  MOVI r2,@mth_phase_gate_test_freq
  MOVI r3,@mth_phase_gate_test_phase
  MOVI r4,@mth_phase_gate_test_out
  MOVI r5,@mth_phase_gate_test_scratch
  CALL @mth_mirror_cycle_phase_gate16_f32
  LD r15,r0,@mth_phase_gate_test_call_ret
  RET

mth_phase_gate_test_check:
  ST r15,r0,@mth_phase_gate_test_ret
  MOVI r6,0
mth_phase_gate_test_check_loop:
  MOVI r8,@mth_phase_gate_test_out
  ADD r8,r8,r6
  LD r1,r8,0
  MOVI r8,@mth_phase_gate_test_expected
  ADD r8,r8,r6
  LD r2,r8,0
  MOVI r3,0
  MOVHI r3,0x3606            ; 2e-5
  CALL @mth_phase_gate_test_near
  CMP r1,r13
  JMP[NE] @mth_phase_gate_test_fail
  ; range [0,1]
  MOVI r8,@mth_phase_gate_test_out
  ADD r8,r8,r6
  LD r1,r8,0
  FCMP r1,r0
  JMP[LT] @mth_phase_gate_test_fail
  MOVI r2,0
  MOVHI r2,0x3F80
  FCMP r1,r2
  JMP[GT] @mth_phase_gate_test_fail
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_phase_gate_test_check_loop
  LD r15,r0,@mth_phase_gate_test_ret
  RET

mth_phase_gate_test_sentinel:
  MOVI r1,0xBEEF
  MOVHI r1,0xDEAD
  ST r1,r0,@mth_phase_gate_test_out
  RET

mth_phase_gate_test_check_sentinel:
  LD r1,r0,@mth_phase_gate_test_out
  MOVI r2,0xBEEF
  MOVHI r2,0xDEAD
  CMP r1,r2
  JMP[NE] @mth_phase_gate_test_fail
  RET

mth_phase_gate_test_near:
  MOVI r4,0
  MOVHI r4,0x7FFF
  FSUB r5,r1,r2
  BOOL.8 r5,r5,r4
  FCMP r5,r3
  JMP[GT] @mth_phase_gate_test_near_fail
  MOVI r1,1
  RET
mth_phase_gate_test_near_fail:
  MOVI r1,0
  RET

mth_phase_gate_test_fail:
  MOVI r1,@mth_phase_gate_test_bad
  CALL @mth_phase_gate_test_puts
  HALT

mth_phase_gate_test_puts:
  MOVI r4,255
mth_phase_gate_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_phase_gate_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_phase_gate_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_phase_gate_test_puts_word

mth_phase_gate_test_pass:
.str "MTH CYCLE PHASE GATE PASS\n"
mth_phase_gate_test_bad:
.str "MTH CYCLE PHASE GATE FAIL\n"

.org 4096
mth_phase_gate_test_ret:
.word 0
mth_phase_gate_test_call_ret:
.word 0
mth_phase_gate_test_position:
.word 0
mth_phase_gate_test_freq:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_phase_gate_test_phase:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_phase_gate_test_expected:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_phase_gate_test_out:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_phase_gate_test_scratch:
.word 0,0,0,0,0,0
