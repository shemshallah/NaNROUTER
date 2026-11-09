; MTH 16→16 affine projection — NaN16 float32 only.
;
;   out[p] = bias[p] + sum(d=0..15) W[p*16+d] * x[d]
;
; This is the reusable Q/K/V projection seam: call it three times with
; different weight/bias sets. It is not a full attention block and does not
; compute attention scores.
;
; ABI (r13=1):
;   r1 = x[16], float32 word addresses (read-only)
;   r2 = W[16][16], row-major: output p, input d
;   r3 = bias[16], float32
;   r4 = out[16], written on success only
;   r5 = caller scratch, 16 float32 words
;   r13 = 1
; Success: r1=1, r9=0, out complete.
; Rejection:
;   cause 1: x non-finite
;   cause 2: W non-finite
;   cause 3: bias non-finite
;   cause 4: a finite-input projection overflowed to a non-finite value
;   r1=0, r9=cause, out untouched. Outputs are accumulated in scratch and only
;   copied to out after all 16 projections are finite.
;
; Numeric order: bias first, then d increasing, one FMUL then one FADD per
; term. No FMA, reassociation, or host math. Clobbers r1-r11, r14; preserves
; r0, r12, r13, r15.

mth_attention_project16_f32:
  MOVI r0,0
  ADD r11,r5,r0              ; scratch base

  ; x finite
  MOVI r5,0
  MOVI r9,0
  MOVHI r9,0x7F80
mth_attention_project16_x_gate:
  ADD r8,r1,r5
  LD r7,r8,0
  BOOL.8 r10,r7,r9
  CMP r10,r9
  JMP[EQ] @mth_attention_project16_bad_x
  ADDI r5,r5,1
  MOVI r8,16
  CMP r5,r8
  JMP[LT] @mth_attention_project16_x_gate

  ; W finite
  MOVI r5,0
mth_attention_project16_w_gate:
  ADD r8,r2,r5
  LD r7,r8,0
  BOOL.8 r10,r7,r9
  CMP r10,r9
  JMP[EQ] @mth_attention_project16_bad_w
  ADDI r5,r5,1
  MOVI r8,256
  CMP r5,r8
  JMP[LT] @mth_attention_project16_w_gate

  ; bias finite
  MOVI r5,0
mth_attention_project16_b_gate:
  ADD r8,r3,r5
  LD r7,r8,0
  BOOL.8 r10,r7,r9
  CMP r10,r9
  JMP[EQ] @mth_attention_project16_bad_b
  ADDI r5,r5,1
  MOVI r8,16
  CMP r5,r8
  JMP[LT] @mth_attention_project16_b_gate

  ; project into scratch
  MOVI r5,0                  ; p
mth_attention_project16_p_loop:
  ADD r8,r3,r5
  LD r7,r8,0                 ; acc = bias[p]
  MOVI r6,0                  ; d
mth_attention_project16_d_loop:
  SHL r8,r5,4
  ADD r8,r8,r6
  ADD r8,r2,r8
  LD r8,r8,0                 ; W[p*16+d]
  ADD r10,r1,r6
  LD r10,r10,0               ; x[d]
  FMUL r8,r8,r10
  FADD r7,r7,r8
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_attention_project16_d_loop

  ; finite result before publishing anything
  BOOL.8 r8,r7,r9
  CMP r8,r9
  JMP[EQ] @mth_attention_project16_bad_result
  ADD r8,r11,r5
  ST r7,r8,0
  ADDI r5,r5,1
  MOVI r8,16
  CMP r5,r8
  JMP[LT] @mth_attention_project16_p_loop

  ; copy scratch to out
  MOVI r5,0
mth_attention_project16_copy:
  ADD r8,r11,r5
  LD r7,r8,0
  ADD r8,r4,r5
  ST r7,r8,0
  ADDI r5,r5,1
  MOVI r8,16
  CMP r5,r8
  JMP[LT] @mth_attention_project16_copy

  MOVI r1,1
  MOVI r9,0
  RET

mth_attention_project16_bad_x:
  MOVI r9,1
  JMP @mth_attention_project16_reject
mth_attention_project16_bad_w:
  MOVI r9,2
  JMP @mth_attention_project16_reject
mth_attention_project16_bad_b:
  MOVI r9,3
  JMP @mth_attention_project16_reject
mth_attention_project16_bad_result:
  MOVI r9,4
mth_attention_project16_reject:
  MOVI r1,0
  RET
