; MTH phase-system integration fixture — NaN16 only.
;
; Composes the native primitives in one guest run:
;   twiddle256 -> phase_gate16 -> cycle_train_step (8 steps)
;   -> cycle_predict16 -> attention_mix16 -> cycle_retain -> predict
;   -> contradiction pair -> angular ring map.
;
; It is an integration fixture, not a new mathematical authority. It checks
; that the individual typed kernels compose without host trigonometry.

.org 0
JMP @mth_phase_system_main
.include "../nan16/mth_trig_sincos_f32.nas"
.include "../nan16/mth_trig_twiddle256_f32.nas"
.include "../nan16/mth_mirror_cycle_phase_gate.nas"
.include "../nan16/mth_mirror_cycle_train_step_f32.nas"
.include "../nan16/mth_mirror_cycle_predict16_f32.nas"
.include "../nan16/mth_attention_mix16_f32.nas"
.include "../nan16/mth_mirror_cycle_retain.nas"
.include "../nan16/mth_mirror_cycle_contradiction.nas"
.include "../nan16/mth_ring_angular_map.nas"

mth_phase_system_main:
  MOVI r0,0
  MOVI r13,1
  CALL @mth_phase_system_init

  ; ---- native twiddle table ----
  CALL @mth_phase_system_twiddle
  CMP r1,r13
  JMP[NE] @mth_phase_system_fail
  LD r1,r0,@mth_phase_system_cos
  MOVI r2,0
  MOVHI r2,0x3F80
  MOVI r3,0
  MOVHI r3,0x3586
  CALL @mth_phase_system_near
  CMP r1,r13
  JMP[NE] @mth_phase_system_fail
  MOVI r1,@mth_phase_system_sin
  LD r1,r1,0
  MOVI r2,0
  MOVI r3,0
  MOVHI r3,0x3586
  CALL @mth_phase_system_near
  CMP r1,r13
  JMP[NE] @mth_phase_system_fail
  MOVI r1,@mth_phase_system_cos
  ADDI r1,r1,128
  LD r1,r1,0
  MOVI r2,0
  MOVHI r2,0xBF80
  MOVI r3,0
  MOVHI r3,0x3586
  CALL @mth_phase_system_near
  CMP r1,r13
  JMP[NE] @mth_phase_system_fail

  ; ---- oscillatory gate ----
  CALL @mth_phase_system_make_gate
  CMP r1,r13
  JMP[NE] @mth_phase_system_fail
  LD r1,r0,@mth_phase_system_gate
  MOVI r2,0xB552
  MOVHI r2,0x3F6B            ; 0.9207355
  MOVI r3,0
  MOVHI r3,0x3606
  CALL @mth_phase_system_near
  CMP r1,r13
  JMP[NE] @mth_phase_system_fail

  ; ---- eight phase-gated training steps, strict SSE decrease ----
  MOVI r1,0
  MOVHI r1,0x7F7F
  ST r1,r0,@mth_phase_system_prev_sse
  ST r0,r0,@mth_phase_system_count
mth_phase_system_train_loop:
  CALL @mth_phase_system_train
  CMP r1,r13
  JMP[NE] @mth_phase_system_fail
  ST r7,r0,@mth_phase_system_sse
  LD r2,r0,@mth_phase_system_prev_sse
  FCMP r7,r2
  JMP[GE] @mth_phase_system_fail
  ST r7,r0,@mth_phase_system_prev_sse
  LD r2,r0,@mth_phase_system_count
  ADDI r2,r2,1
  ST r2,r0,@mth_phase_system_count
  MOVI r3,8
  CMP r2,r3
  JMP[LT] @mth_phase_system_train_loop

  ; ---- cycle readout ----
  CALL @mth_phase_system_predict
  CMP r1,r13
  JMP[NE] @mth_phase_system_fail
  MOVI r1,@mth_phase_system_pred
  MOVI r2,@mth_phase_system_pred_before
  CALL @mth_phase_system_copy16
  LD r1,r0,@mth_phase_system_pred
  MOVI r2,0
  MOVHI r2,0x3F00            ; > 0.5
  FCMP r1,r2
  JMP[LE] @mth_phase_system_fail

  ; ---- attention/value mix: 0.75*row0 + 0.25*row1 ----
  CALL @mth_phase_system_mix_candidates
  CMP r1,r13
  JMP[NE] @mth_phase_system_fail
  LD r1,r0,@mth_phase_system_mix
  MOVI r2,0
  MOVHI r2,0x3F00            ; > 0.5
  FCMP r1,r2
  JMP[LE] @mth_phase_system_fail

  ; ---- retain toward a zero source bank ----
  CALL @mth_phase_system_retain
  CMP r1,r13
  JMP[NE] @mth_phase_system_fail
  CALL @mth_phase_system_predict
  CMP r1,r13
  JMP[NE] @mth_phase_system_fail
  LD r1,r0,@mth_phase_system_pred
  LD r2,r0,@mth_phase_system_pred_before
  MOVI r3,0
  MOVHI r3,0x3F00            ; half
  FMUL r2,r2,r3
  MOVI r3,0
  MOVHI r3,0x3606            ; 2e-5
  CALL @mth_phase_system_near
  CMP r1,r13
  JMP[NE] @mth_phase_system_fail

  ; ---- contradiction pair ----
  MOVI r1,0
  MOVHI r1,0x4020            ; 2.5
  MOVI r2,0
  MOVHI r2,0x3F00            ; 0.5
  CALL @mth_mirror_cycle_contradiction_f32
  CMP r1,r13
  JMP[NE] @mth_phase_system_fail
  MOVI r8,0
  MOVHI r8,0x3F00
  CMP r2,r8
  JMP[NE] @mth_phase_system_fail
  MOVI r8,0
  MOVHI r8,0x4000            ; balance 2.0
  CMP r3,r8
  JMP[NE] @mth_phase_system_fail

  ; ---- angular ring address: 17 lanes counter-clockwise = lane 0 ----
  MOVI r1,17
  MOVI r2,0xFFEF
  MOVHI r2,0xFFFF            ; -17
  CALL @mth_ring_angular_map_u32
  CMP r1,r13
  JMP[NE] @mth_phase_system_fail
  CMP r3,r0
  JMP[NE] @mth_phase_system_fail
  MOVI r8,255
  CMP r4,r8
  JMP[NE] @mth_phase_system_fail

  MOVI r1,@mth_phase_system_pass
  CALL @mth_phase_system_puts
  HALT

mth_phase_system_init:
  ST r15,r0,@mth_phase_system_init_ret
  ; x[0]=1, target=1, frequency=1, phase=0, weights=0.75/0.25
  MOVI r1,0
  MOVHI r1,0x3F80
  ST r1,r0,@mth_phase_system_x
  MOVI r6,0
mth_phase_system_init_loop:
  MOVI r8,@mth_phase_system_target
  ADD r8,r8,r6
  ST r1,r8,0
  MOVI r8,@mth_phase_system_freq
  ADD r8,r8,r6
  ST r1,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_phase_system_init_loop
  MOVI r1,0
  MOVHI r1,0x3F40            ; 0.75
  ST r1,r0,@mth_phase_system_weights
  MOVI r1,0
  MOVHI r1,0x3E80            ; 0.25
  MOVI r8,@mth_phase_system_weights
  ADDI r8,r8,1
  ST r1,r8,0
  LD r15,r0,@mth_phase_system_init_ret
  RET

mth_phase_system_twiddle:
  ST r15,r0,@mth_phase_system_twiddle_ret
  MOVI r1,@mth_phase_system_cos
  MOVI r2,@mth_phase_system_sin
  MOVI r3,@mth_phase_system_twiddle_scratch
  CALL @mth_trig_twiddle256_f32
  LD r15,r0,@mth_phase_system_twiddle_ret
  RET

mth_phase_system_make_gate:
  ST r15,r0,@mth_phase_system_gate_ret
  MOVI r1,1
  MOVI r2,@mth_phase_system_freq
  MOVI r3,@mth_phase_system_phase
  MOVI r4,@mth_phase_system_gate
  MOVI r5,@mth_phase_system_gate_scratch
  CALL @mth_mirror_cycle_phase_gate16_f32
  LD r15,r0,@mth_phase_system_gate_ret
  RET

mth_phase_system_train:
  ST r15,r0,@mth_phase_system_train_ret
  MOVI r1,@mth_phase_system_x
  MOVI r2,@mth_phase_system_target
  MOVI r3,@mth_phase_system_gate
  MOVI r4,0
  MOVHI r4,0x3E80            ; lr 0.25
  MOVI r5,1
  MOVI r6,@mth_phase_system_error
  CALL @mth_mirror_cycle_train_step_f32
  LD r15,r0,@mth_phase_system_train_ret
  RET

mth_phase_system_predict:
  ST r15,r0,@mth_phase_system_pred_ret
  MOVI r1,@mth_phase_system_x
  MOVI r2,@mth_phase_system_pred
  MOVI r3,1
  CALL @mth_mirror_cycle_predict16_f32
  LD r15,r0,@mth_phase_system_pred_ret
  RET

mth_phase_system_mix_candidates:
  ST r15,r0,@mth_phase_system_mix_ret
  ; values row 0 = prediction, row 1 = zero
  MOVI r1,@mth_phase_system_pred
  MOVI r2,@mth_phase_system_values
  CALL @mth_phase_system_copy16
  MOVI r1,@mth_phase_system_weights
  MOVI r2,@mth_phase_system_values
  MOVI r3,@mth_phase_system_mix
  CALL @mth_attention_mix16_f32
  LD r15,r0,@mth_phase_system_mix_ret
  RET

mth_phase_system_retain:
  ST r15,r0,@mth_phase_system_retain_ret
  MOVI r1,1
  MOVI r2,65
  MOVI r3,0
  MOVHI r3,0x3F00            ; gain 0.5
  CALL @mth_mirror_cycle_retain_f32
  LD r15,r0,@mth_phase_system_retain_ret
  RET

; r1=src, r2=dst, 16 words
mth_phase_system_copy16:
  MOVI r6,0
mth_phase_system_copy_loop:
  ADD r7,r1,r6
  LD r8,r7,0
  ADD r7,r2,r6
  ST r8,r7,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_phase_system_copy_loop
  RET

; |r1-r2| <= r3, preserving r6-r15
mth_phase_system_near:
  MOVI r4,0
  MOVHI r4,0x7FFF
  FSUB r5,r1,r2
  BOOL.8 r5,r5,r4
  FCMP r5,r3
  JMP[GT] @mth_phase_system_near_fail
  MOVI r1,1
  RET
mth_phase_system_near_fail:
  MOVI r1,0
  RET

mth_phase_system_fail:
  MOVI r1,@mth_phase_system_bad
  CALL @mth_phase_system_puts
  HALT

mth_phase_system_puts:
  MOVI r4,255
mth_phase_system_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_phase_system_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_phase_system_puts_byte
  ADD r1,r1,r13
  JMP @mth_phase_system_puts_word

mth_phase_system_pass:
.str "MTH PHASE SYSTEM PASS\n"
mth_phase_system_bad:
.str "MTH PHASE SYSTEM FAIL\n"

.org 4096
mth_phase_system_cos:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_phase_system_sin:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_phase_system_twiddle_scratch:
.word 0,0,0,0
mth_phase_system_x:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_phase_system_target:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_phase_system_freq:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_phase_system_phase:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_phase_system_gate:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_phase_system_error:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_phase_system_gate_scratch:
.word 0,0,0,0,0,0
mth_phase_system_pred:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_phase_system_pred_before:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_phase_system_values:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_phase_system_weights:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_phase_system_mix:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_phase_system_prev_sse:
.word 0
mth_phase_system_sse:
.word 0
mth_phase_system_count:
.word 0
mth_phase_system_init_ret:
.word 0
mth_phase_system_twiddle_ret:
.word 0
mth_phase_system_gate_ret:
.word 0
mth_phase_system_train_ret:
.word 0
mth_phase_system_pred_ret:
.word 0
mth_phase_system_mix_ret:
.word 0
mth_phase_system_retain_ret:
.word 0
