; MTH 255-head × 16-channel field-mixture reverse pass — NaN16 float32.
;
; Forward:
;   out[c] = sum_h weight[h] * value[h][c]
;
; Reverse, given upstream gradient g_out[c]:
;   d_weight[h] = sum_c g_out[c] * value[h][c]
;   d_value[h][c] = g_out[c] * weight[h]
;
; This is the complete reverse pass for the field mixture, and it produces an
; independent gradient for every one of the 255 real heads. NANNET0/ring 255
; is outside the trainable field.
;
; ABI (r13=1):
;   r1 = weight[255]
;   r2 = value[255][16]
;   r3 = g_out[16]
;   r4 = d_weight[255], written
;   r5 = d_value[255][16], written
;   r13 = 1
; Success: r1=1, r9=0.
; Rejection:
;   cause 1: weight non-finite
;   cause 2: value non-finite
;   cause 3: upstream gradient non-finite
;   r1=0, r9=cause; outputs are unspecified on rejection.
;
; Numeric order: increasing c for d_weight; increasing h/c for d_value. One
; FMUL and one FADD per d_weight term. No FMA, host math, or static storage.
; Clobbers r1-r11, r14; preserves r0, r12, r13, r15.

mth_field_mix255x16_backward_f32:
  MOVI r0,0

  ; weight finite
  MOVI r9,0
  MOVHI r9,0x7F80
  MOVI r6,0
mth_field_mix_bwd_w_gate:
  ADD r8,r1,r6
  LD r7,r8,0
  BOOL.8 r10,r7,r9
  CMP r10,r9
  JMP[EQ] @mth_field_mix_bwd_bad_w
  ADDI r6,r6,1
  MOVI r8,255
  CMP r6,r8
  JMP[LT] @mth_field_mix_bwd_w_gate

  ; value finite
  MOVI r6,0
mth_field_mix_bwd_v_gate:
  ADD r8,r2,r6
  LD r7,r8,0
  BOOL.8 r10,r7,r9
  CMP r10,r9
  JMP[EQ] @mth_field_mix_bwd_bad_v
  ADDI r6,r6,1
  MOVI r8,4080
  CMP r6,r8
  JMP[LT] @mth_field_mix_bwd_v_gate

  ; upstream gradient finite
  MOVI r6,0
mth_field_mix_bwd_g_gate:
  ADD r8,r3,r6
  LD r7,r8,0
  BOOL.8 r10,r7,r9
  CMP r10,r9
  JMP[EQ] @mth_field_mix_bwd_bad_g
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_field_mix_bwd_g_gate

  ; d_weight[h]
  MOVI r6,0
mth_field_mix_bwd_dw_h:
  MOVI r8,0                 ; acc
  MOVI r7,0                 ; c
mth_field_mix_bwd_dw_c:
  ADD r10,r3,r7
  LD r10,r10,0              ; g[c]
  SHL r11,r6,4
  ADD r11,r11,r7
  ADD r11,r2,r11
  LD r11,r11,0              ; value[h][c]
  FMUL r11,r11,r10
  FADD r8,r8,r11
  ADDI r7,r7,1
  MOVI r11,16
  CMP r7,r11
  JMP[LT] @mth_field_mix_bwd_dw_c
  ADD r10,r4,r6
  ST r8,r10,0
  ADDI r6,r6,1
  MOVI r8,255
  CMP r6,r8
  JMP[LT] @mth_field_mix_bwd_dw_h

  ; d_value[h][c] = weight[h] * g[c]
  MOVI r6,0
mth_field_mix_bwd_dv_h:
  ADD r8,r1,r6
  LD r8,r8,0                ; weight
  MOVI r7,0
mth_field_mix_bwd_dv_c:
  ADD r9,r3,r7
  LD r9,r9,0                ; g[c]
  FMUL r9,r9,r8
  SHL r10,r6,4
  ADD r10,r10,r7
  ADD r10,r5,r10
  ST r9,r10,0
  ADDI r7,r7,1
  MOVI r10,16
  CMP r7,r10
  JMP[LT] @mth_field_mix_bwd_dv_c
  ADDI r6,r6,1
  MOVI r8,255
  CMP r6,r8
  JMP[LT] @mth_field_mix_bwd_dv_h

  MOVI r1,1
  MOVI r9,0
  RET

mth_field_mix_bwd_bad_w:
  MOVI r9,1
  JMP @mth_field_mix_bwd_reject
mth_field_mix_bwd_bad_v:
  MOVI r9,2
  JMP @mth_field_mix_bwd_reject
mth_field_mix_bwd_bad_g:
  MOVI r9,3
mth_field_mix_bwd_reject:
  MOVI r1,0
  RET
