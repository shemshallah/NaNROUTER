; MTH 255-head field-gate reverse pass — NaN16 float32 only.
;
; For a softmax gate w = softmax(s), given d_w:
;
;   dot = sum_i w[i] * d_w[i]
;   d_s[i] = w[i] * (d_w[i] - dot)
;
; Exactly the 255 real heads are differentiated; NANNET0/ring 255 is not part
; of the gate.
;
; ABI (r13=1):
;   r1 = weight[255] (the forward softmax output)
;   r2 = d_weight[255]
;   r3 = d_score[255], written on success only
;   r13 = 1
; Success: r1=1, r9=0.
; Rejection: r1=0, r9=1 weight non-finite, r9=2 d_weight non-finite;
; d_score untouched.
;
; Numeric order: dot is the increasing-i sum of w[i]*d_w[i]; then one FSUB and
; one FMUL per d_score. No FMA or host math.

mth_field_gate255_backward_f32:
  MOVI r0,0
  MOVI r9,0
  MOVHI r9,0x7F80

  ; weight finite
  MOVI r6,0
mth_field_gate_bwd_w_gate:
  ADD r8,r1,r6
  LD r7,r8,0
  BOOL.8 r10,r7,r9
  CMP r10,r9
  JMP[EQ] @mth_field_gate_bwd_bad_w
  ADDI r6,r6,1
  MOVI r8,255
  CMP r6,r8
  JMP[LT] @mth_field_gate_bwd_w_gate

  ; d_weight finite
  MOVI r6,0
mth_field_gate_bwd_dw_gate:
  ADD r8,r2,r6
  LD r7,r8,0
  BOOL.8 r10,r7,r9
  CMP r10,r9
  JMP[EQ] @mth_field_gate_bwd_bad_dw
  ADDI r6,r6,1
  MOVI r8,255
  CMP r6,r8
  JMP[LT] @mth_field_gate_bwd_dw_gate

  ; dot
  MOVI r5,0
  MOVI r6,0
mth_field_gate_bwd_dot:
  ADD r8,r1,r6
  LD r7,r8,0
  ADD r8,r2,r6
  LD r8,r8,0
  FMUL r7,r7,r8
  FADD r5,r5,r7
  ADDI r6,r6,1
  MOVI r8,255
  CMP r6,r8
  JMP[LT] @mth_field_gate_bwd_dot

  ; d_score
  MOVI r6,0
mth_field_gate_bwd_out:
  ADD r8,r1,r6
  LD r7,r8,0                ; w
  ADD r8,r2,r6
  LD r8,r8,0                ; dw
  FSUB r8,r8,r5
  FMUL r7,r7,r8
  ADD r8,r3,r6
  ST r7,r8,0
  ADDI r6,r6,1
  MOVI r8,255
  CMP r6,r8
  JMP[LT] @mth_field_gate_bwd_out

  MOVI r1,1
  MOVI r9,0
  RET

mth_field_gate_bwd_bad_w:
  MOVI r9,1
  JMP @mth_field_gate_bwd_reject
mth_field_gate_bwd_bad_dw:
  MOVI r9,2
mth_field_gate_bwd_reject:
  MOVI r1,0
  RET
