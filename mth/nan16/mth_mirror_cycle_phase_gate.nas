; MTH native oscillatory gate generator — NaN16 float32 only.
;
; Produces per-channel write gates for the content-gated cycle trainer:
;
;   gate[c] = clamp(0.5 * (1 + sin(position * frequency[c] + phase[c])), 0, 1)
;
; The gate is a content-independent oscillator. It is a testable hypothesis,
; not a claim that oscillation improves learning. The clamp is explicit so
; the result is always accepted by the cycle trainer's [0,1] gate domain.
;
; ABI (r13=1):
;   r1 = position, unsigned integer 0..4096
;   r2 = frequency[16], f32 word addresses
;   r3 = phase[16], f32 word addresses
;   r4 = out[16], f32 word addresses
;   r5 = caller scratch, 6 words
;   r13 = 1
; Success: r1=1, r9=0, out complete.
; Rejection:
;   cause 1: position > 4096
;   cause 2: a frequency or phase is non-finite
;   cause 3: an angle is outside the native sincos domain |angle| <= 128
;   r1=0, r9=cause, out untouched. A full angle preflight runs before the
;   first output store.
;
; Numeric order: angle = FMUL(position, frequency) then FADD(phase); gate =
; FMUL(sin,0.5) then FADD(0.5); clamps are exact 0.0/1.0 payload copies.
; No host sin/cos, no lookup table, no static storage.

mth_mirror_cycle_phase_gate16_f32:
  MOVI r0,0
  ADD r6,r5,r0               ; scratch, preserved by sincos
  ADDI r7,r6,5
  ST r15,r7,0                ; return link
  ST r4,r6,0                 ; out pointer
  ST r2,r6,1                 ; frequency pointer
  ST r3,r6,2                 ; phase pointer

  ; ---- position domain 0..4096 ----
  MOVI r7,4096
  CMP r7,r1
  JMP[LT] @mth_phase_gate_bad_position
  CVTIF r7,r1
  ST r7,r6,3                 ; position as float

  ; ---- preflight all angles: inputs finite, |angle| <= 128 ----
  MOVI r4,0
mth_phase_gate_preflight:
  LD r7,r6,3
  LD r8,r6,1
  ADD r8,r8,r4
  LD r8,r8,0                 ; frequency
  MOVI r9,0
  MOVHI r9,0x7F80
  BOOL.8 r10,r8,r9
  CMP r10,r9
  JMP[EQ] @mth_phase_gate_bad_input
  LD r10,r6,2
  ADD r10,r10,r4
  LD r10,r10,0               ; phase
  BOOL.8 r11,r10,r9
  CMP r11,r9
  JMP[EQ] @mth_phase_gate_bad_input
  FMUL r8,r7,r8
  FADD r8,r8,r10             ; angle
  BOOL.8 r11,r8,r9
  CMP r11,r9
  JMP[EQ] @mth_phase_gate_bad_input
  MOVI r9,0xFFFF
  MOVHI r9,0x7FFF
  BOOL.8 r8,r8,r9            ; |angle|
  MOVI r9,0
  MOVHI r9,0x4300            ; 128.0
  FCMP r8,r9
  JMP[GT] @mth_phase_gate_bad_angle
  ADDI r4,r4,1
  MOVI r8,16
  CMP r4,r8
  JMP[LT] @mth_phase_gate_preflight

  ; ---- generate gates ----
  MOVI r7,0
  ST r7,r6,4                 ; channel index
mth_phase_gate_c_loop:
  LD r7,r6,4
  MOVI r8,16
  CMP r7,r8
  JMP[GE] @mth_phase_gate_done

  LD r8,r6,1
  ADD r8,r8,r7
  LD r8,r8,0                 ; frequency
  LD r9,r6,2
  ADD r9,r9,r7
  LD r9,r9,0                 ; phase
  LD r1,r6,3
  FMUL r1,r1,r8
  FADD r1,r1,r9
  CALL @mth_trig_sincos_f32

  ; gate = sin*0.5 + 0.5
  MOVI r1,0
  MOVHI r1,0x3F00
  FMUL r2,r2,r1
  FADD r2,r2,r1

  ; clamp to [0,1]
  FCMP r2,r0
  JMP[GE] @mth_phase_gate_hi_check
  MOVI r2,0
  JMP @mth_phase_gate_store
mth_phase_gate_hi_check:
  MOVI r1,0
  MOVHI r1,0x3F80
  FCMP r2,r1
  JMP[LE] @mth_phase_gate_store
  ADD r2,r1,r0

mth_phase_gate_store:
  LD r7,r6,4
  LD r8,r6,0
  ADD r8,r8,r7
  ST r2,r8,0
  ADDI r7,r7,1
  ST r7,r6,4
  JMP @mth_phase_gate_c_loop

mth_phase_gate_done:
  ADDI r7,r6,5
  LD r15,r7,0
  MOVI r1,1
  MOVI r9,0
  RET

mth_phase_gate_bad_position:
  MOVI r9,1
  JMP @mth_phase_gate_reject
mth_phase_gate_bad_input:
  MOVI r9,2
  JMP @mth_phase_gate_reject
mth_phase_gate_bad_angle:
  MOVI r9,3
mth_phase_gate_reject:
  ADDI r7,r6,5
  LD r15,r7,0
  MOVI r1,0
  RET
