; MTH 255-head field-mixture gradient step — NaN16 float32 only.
;
; In-place one-step SGD for the field mixture:
;
;   out[c] = sum_h weight[h] * value[h][c]
;   L      = sum_c g_out[c] * out[c]
;
;   d_weight[h]   = sum_c g_out[c] * value[h][c]
;   d_value[h][c] = g_out[c] * weight_old[h]
;
;   weight[h]     -= lr * d_weight[h]
;   value[h][c]   -= lr * d_value[h][c]
;
; All 255 real heads are updated independently. NANNET0/ring 255 is excluded.
; This is one native field-training step; it is not a full model optimizer.
;
; ABI (r13=1):
;   r1 = weight[255], updated in place
;   r2 = value[255][16], updated in place
;   r3 = g_out[16]
;   r4 = learning rate, finite f32 in [0,1]
;   r13 = 1
; Success: r1=1, r9=0.
; Rejection:
;   cause 1: weight non-finite
;   cause 2: value non-finite
;   cause 3: gradient non-finite
;   cause 4: learning rate non-finite or outside [0,1]
;   Updates may be partially applied if an arithmetic overflow occurs; the
;   input-domain checks run before the first update.
;
; Numeric order: d_weight per head is increasing c; d_value is one FMUL;
; each update is one FMUL then one FSUB. No FMA, host math, or static storage.
; Clobbers r1-r12, r14; preserves r0, r13, r15.

mth_field_train_step255x16_f32:
  MOVI r0,0

  ; weight finite
  MOVI r9,0
  MOVHI r9,0x7F80
  MOVI r6,0
mth_field_step_w_gate:
  ADD r8,r1,r6
  LD r7,r8,0
  BOOL.8 r10,r7,r9
  CMP r10,r9
  JMP[EQ] @mth_field_step_bad_w
  ADDI r6,r6,1
  MOVI r8,255
  CMP r6,r8
  JMP[LT] @mth_field_step_w_gate

  ; value finite
  MOVI r6,0
mth_field_step_v_gate:
  ADD r8,r2,r6
  LD r7,r8,0
  BOOL.8 r10,r7,r9
  CMP r10,r9
  JMP[EQ] @mth_field_step_bad_v
  ADDI r6,r6,1
  MOVI r8,4080
  CMP r6,r8
  JMP[LT] @mth_field_step_v_gate

  ; gradient finite
  MOVI r6,0
mth_field_step_g_gate:
  ADD r8,r3,r6
  LD r7,r8,0
  BOOL.8 r10,r7,r9
  CMP r10,r9
  JMP[EQ] @mth_field_step_bad_g
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_field_step_g_gate

  ; learning rate finite and [0,1]
  BOOL.8 r10,r4,r9
  CMP r10,r9
  JMP[EQ] @mth_field_step_bad_lr
  FCMP r4,r0
  JMP[LT] @mth_field_step_bad_lr
  MOVI r8,0
  MOVHI r8,0x3F80
  FCMP r4,r8
  JMP[GT] @mth_field_step_bad_lr

  MOVI r6,0                  ; h
mth_field_step_h_loop:
  ADD r8,r1,r6
  LD r12,r8,0               ; weight_old

  ; d_weight
  MOVI r9,0
  MOVI r7,0
mth_field_step_dw:
  ADD r8,r3,r7
  LD r8,r8,0
  SHL r11,r6,4
  ADD r11,r11,r7
  ADD r11,r2,r11
  LD r11,r11,0
  FMUL r11,r11,r8
  FADD r9,r9,r11
  ADDI r7,r7,1
  MOVI r11,16
  CMP r7,r11
  JMP[LT] @mth_field_step_dw
  FMUL r9,r9,r4
  FSUB r10,r12,r9           ; weight_new

  ; update values using weight_old
  MOVI r7,0
mth_field_step_dv:
  ADD r8,r3,r7
  LD r8,r8,0
  FMUL r8,r8,r12            ; g * weight_old
  FMUL r8,r8,r4             ; lr * d_value
  SHL r11,r6,4
  ADD r11,r11,r7
  ADD r11,r2,r11
  LD r9,r11,0               ; old value
  FSUB r9,r9,r8
  ST r9,r11,0
  ADDI r7,r7,1
  MOVI r11,16
  CMP r7,r11
  JMP[LT] @mth_field_step_dv

  ; publish weight_new (r10)
  ADD r8,r1,r6
  ST r10,r8,0
  ADDI r6,r6,1
  MOVI r8,255
  CMP r6,r8
  JMP[LT] @mth_field_step_h_loop

  MOVI r1,1
  MOVI r9,0
  RET

mth_field_step_bad_w:
  MOVI r9,1
  JMP @mth_field_step_reject
mth_field_step_bad_v:
  MOVI r9,2
  JMP @mth_field_step_reject
mth_field_step_bad_g:
  MOVI r9,3
  JMP @mth_field_step_reject
mth_field_step_bad_lr:
  MOVI r9,4
mth_field_step_reject:
  MOVI r1,0
  RET
