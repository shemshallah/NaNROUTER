; MTH 255-head × 16-channel decoder-field mixture — NaN16 float32 only.
;
;   out[c] = sum(h=0..254) weight[h] * vector[h][c]
;
; NANNET0/ring position 255 is intentionally excluded: the real field has
; exactly 255 nameable heads. This kernel mixes the head outputs into one
; field vector; it does not compute per-head logits or train the weights.
;
; ABI (r13=1):
;   r1 = weight[255], finite nonnegative float32
;   r2 = vector[255][16], row-major
;   r3 = out[16], written on success only
;   r4 = caller scratch, 16 float32 words
;   r13 = 1
; Success: r1=1, r9=0.
; Rejection:
;   cause 1: weight non-finite or negative
;   cause 2: vector non-finite
;   cause 3: a finite-input mixture overflowed
;   out untouched; outputs are accumulated in scratch before publication.
;
; Numeric order: h increasing, one FMUL then one FADD per term. No FMA,
; reassociation, host math, or static storage. Clobbers r1-r11, r14; preserves
; r0, r12, r13, r15.

mth_field_mix255x16_f32:
  MOVI r0,0
  ADD r11,r4,r0              ; scratch

  ; weights finite and nonnegative
  MOVI r9,0
  MOVHI r9,0x7F80
  MOVI r5,0
mth_field_mix255_w_gate:
  ADD r8,r1,r5
  LD r7,r8,0
  BOOL.8 r10,r7,r9
  CMP r10,r9
  JMP[EQ] @mth_field_mix255_bad_w
  FCMP r7,r0
  JMP[LT] @mth_field_mix255_bad_w
  ADDI r5,r5,1
  MOVI r8,255
  CMP r5,r8
  JMP[LT] @mth_field_mix255_w_gate

  ; vectors finite
  MOVI r5,0
mth_field_mix255_v_gate:
  ADD r8,r2,r5
  LD r7,r8,0
  BOOL.8 r10,r7,r9
  CMP r10,r9
  JMP[EQ] @mth_field_mix255_bad_v
  ADDI r5,r5,1
  MOVI r8,4080
  CMP r5,r8
  JMP[LT] @mth_field_mix255_v_gate

  ; per-channel mixture
  MOVI r6,0                  ; c
mth_field_mix255_c_loop:
  MOVI r7,0                  ; acc
  MOVI r5,0                  ; h
mth_field_mix255_h_loop:
  ADD r8,r1,r5
  LD r8,r8,0                 ; weight
  SHL r10,r5,4
  ADD r10,r10,r6
  ADD r10,r2,r10
  LD r10,r10,0               ; vector[h][c]
  FMUL r8,r8,r10
  FADD r7,r7,r8
  ADDI r5,r5,1
  MOVI r8,255
  CMP r5,r8
  JMP[LT] @mth_field_mix255_h_loop

  BOOL.8 r8,r7,r9
  CMP r8,r9
  JMP[EQ] @mth_field_mix255_bad_result
  ADD r8,r11,r6
  ST r7,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_field_mix255_c_loop

  ; publish
  MOVI r6,0
mth_field_mix255_copy:
  ADD r8,r11,r6
  LD r7,r8,0
  ADD r8,r3,r6
  ST r7,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_field_mix255_copy

  MOVI r1,1
  MOVI r9,0
  RET

mth_field_mix255_bad_w:
  MOVI r9,1
  JMP @mth_field_mix255_reject
mth_field_mix255_bad_v:
  MOVI r9,2
  JMP @mth_field_mix255_reject
mth_field_mix255_bad_result:
  MOVI r9,3
mth_field_mix255_reject:
  MOVI r1,0
  RET
