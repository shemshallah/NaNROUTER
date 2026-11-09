; MTH gated residual memory conditioning — NaN16 float32 only.
;
;   out[i] = h[i] + gate[i] * memory[i]
;
; This is the decoder-side seam for injecting a native memory readout into a
; hidden state. It does not train the gate, choose a memory, or claim that the
; injection helps; the caller owns those policies.
;
; ABI (r13=1):
;   r1 = hidden h[16], float32
;   r2 = memory m[16], float32
;   r3 = gate[16], finite f32 in [0,1]
;   r4 = out[16], written on success only
;   r5 = caller scratch, 16 words
;   r13 = 1
; Success: r1=1, r9=0.
; Rejection:
;   cause 1: hidden non-finite
;   cause 2: memory non-finite
;   cause 3: gate non-finite
;   cause 4: gate outside [0,1]
;   cause 5: finite inputs overflow the residual addition
;   out untouched; results are accumulated in scratch before publication.
;
; Numeric order: one FMUL (gate*memory), then one FADD (h + term). No FMA,
; reassociation, host math, or static storage. Clobbers r1-r11, r14; preserves
; r0, r12, r13, r15.

mth_memory_condition16_f32:
  MOVI r0,0
  ADD r11,r5,r0              ; scratch

  ; hidden finite
  MOVI r9,0
  MOVHI r9,0x7F80
  MOVI r5,0
mth_memcond_h_gate:
  ADD r8,r1,r5
  LD r7,r8,0
  BOOL.8 r10,r7,r9
  CMP r10,r9
  JMP[EQ] @mth_memcond_bad_h
  ADDI r5,r5,1
  MOVI r8,16
  CMP r5,r8
  JMP[LT] @mth_memcond_h_gate

  ; memory finite
  MOVI r5,0
mth_memcond_m_gate:
  ADD r8,r2,r5
  LD r7,r8,0
  BOOL.8 r10,r7,r9
  CMP r10,r9
  JMP[EQ] @mth_memcond_bad_m
  ADDI r5,r5,1
  MOVI r8,16
  CMP r5,r8
  JMP[LT] @mth_memcond_m_gate

  ; gate finite and [0,1]
  MOVI r5,0
mth_memcond_g_gate:
  ADD r8,r3,r5
  LD r7,r8,0
  BOOL.8 r10,r7,r9
  CMP r10,r9
  JMP[EQ] @mth_memcond_bad_g
  FCMP r7,r0
  JMP[LT] @mth_memcond_range_g
  MOVI r8,0
  MOVHI r8,0x3F80
  FCMP r7,r8
  JMP[GT] @mth_memcond_range_g
  ADDI r5,r5,1
  MOVI r8,16
  CMP r5,r8
  JMP[LT] @mth_memcond_g_gate

  ; compute to scratch
  MOVI r5,0
mth_memcond_loop:
  ADD r8,r3,r5
  LD r7,r8,0                 ; gate
  ADD r8,r2,r5
  LD r8,r8,0                 ; memory
  FMUL r7,r7,r8
  ADD r8,r1,r5
  LD r8,r8,0                 ; hidden
  FADD r7,r7,r8
  BOOL.8 r10,r7,r9
  CMP r10,r9
  JMP[EQ] @mth_memcond_bad_result
  ADD r8,r11,r5
  ST r7,r8,0
  ADDI r5,r5,1
  MOVI r8,16
  CMP r5,r8
  JMP[LT] @mth_memcond_loop

  MOVI r5,0
mth_memcond_copy:
  ADD r8,r11,r5
  LD r7,r8,0
  ADD r8,r4,r5
  ST r7,r8,0
  ADDI r5,r5,1
  MOVI r8,16
  CMP r5,r8
  JMP[LT] @mth_memcond_copy

  MOVI r1,1
  MOVI r9,0
  RET

mth_memcond_bad_h:
  MOVI r9,1
  JMP @mth_memcond_reject
mth_memcond_bad_m:
  MOVI r9,2
  JMP @mth_memcond_reject
mth_memcond_bad_g:
  MOVI r9,3
  JMP @mth_memcond_reject
mth_memcond_range_g:
  MOVI r9,4
  JMP @mth_memcond_reject
mth_memcond_bad_result:
  MOVI r9,5
mth_memcond_reject:
  MOVI r1,0
  RET
