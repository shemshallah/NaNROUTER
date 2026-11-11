; NaN16 tied 26x26 inverse/forward corpus transition learning adapter.
; This kernel performs all forward softmax, cross-entropy gradients and
; in-guest SGD. Python is permitted only to select, validate, hash/split,
; and encode public-domain text into (left,right,direction) training records.
; This is an ADAPTER TRAINING EXPERIMENT for existing global/head channels,
; not a replacement language model or a training update to the 43M core.
;
; Semantic head index 255 (void) is NEVER a trainable row: this table is a
; separate 26x26 feature-to-feature relationship descriptor, not the head array.
; The native 255x16 head update remains separately available. No root writes.
;
; For sample [left,right,direction]:
;   forward d=0: logits[k]=W[left,k], teacher=right
;   inverse d=1: logits[k]=W[k,right], teacher=left
; P=softmax26(logits) through established native softmax256 padded with -inf.
; W[index] -= lr*(P[k]-one_hot(teacher)[k]).
; Inverse uses exact shared W in transpose direction, not new parameters.
; Both directions see natural-frequency corpus examples.
;
; ABI: r1=W[676] f32 in-guest, r2=samples[count][3] U32,
; r3=count U32 1..4096, r4=lr f32 [0,0.25],
; r5=scratch[269] words, r6=metrics[3] words
;   metrics[0]=correct argmax predictions (integer)
;   metrics[1]=sum(target probabilities) binary32
;   metrics[2]=count (integer).
; scratch[0..255]=logits+softmax; [256..268] persistent frame.
; r13=1; r1=1,r9=0 success, r1=0,r9=1 input/format reject.
; Only source W and metrics touched on success. Source arrays must not alias.
; Preflight entire sample batch, 256 W values, and lr before SGD starts.
; No model is claimed to learn exact words from 16-bin byte features.
.include "mth_global_focus16_f32.nas"

mth_inverse_dual_batch26_f32:
  MOVI r0,0
  MOVI r8,0
  MOVHI r8,0x7F80
  BOOL.8 r7,r4,r8
  CMP r7,r8
  JMP[EQ] @mth_inv26_invalid
  FCMP r4,r0
  JMP[LT] @mth_inv26_invalid
  MOVI r7,0
  MOVHI r7,0x3E80      ; lr <= 1/4
  FCMP r4,r7
  JMP[GT] @mth_inv26_invalid
  CMP r3,r0
  JMP[LE] @mth_inv26_invalid
  MOVI r7,4096
  CMP r3,r7
  JMP[GT] @mth_inv26_invalid
  MOVI r7,0
mth_inv26_gate_weight:
  ADD r10,r1,r7
  LD r10,r10,0
  BOOL.8 r11,r10,r8
  CMP r11,r8
  JMP[EQ] @mth_inv26_invalid
  ADDI r7,r7,1
  MOVI r10,676
  CMP r7,r10
  JMP[LT] @mth_inv26_gate_weight
  MOVI r7,0
mth_inv26_gate_samples:
  MOVI r10,3
  MUL r10,r7,r10
  ADD r10,r2,r10
  LD r11,r10,0
  MOVI r12,26
  CMP r11,r12
  JMP[GE] @mth_inv26_invalid
  LD r11,r10,1
  MOVI r12,26
  CMP r11,r12
  JMP[GE] @mth_inv26_invalid
  LD r11,r10,2
  MOVI r12,1
  CMP r11,r12
  JMP[GT] @mth_inv26_invalid
  ADDI r7,r7,1
  CMP r7,r3
  JMP[LT] @mth_inv26_gate_samples

  ST r1,r5,256              ; W
  ST r2,r5,257              ; samples
  ST r3,r5,258              ; count
  ST r4,r5,259              ; lr
  ST r6,r5,260              ; metrics
  ST r15,r5,261             ; return link
  ST r0,r5,262              ; example index
  ST r0,r5,266              ; correct
  ST r0,r5,267              ; probability sum +0.0

mth_inv26_sample:
  LD r7,r5,262
  LD r8,r5,257
  MOVI r9,3
  MUL r9,r7,r9
  ADD r8,r8,r9
  LD r9,r8,0                ; left
  LD r10,r8,1               ; right
  LD r11,r8,2               ; direction
  ST r11,r5,265
  CMP r11,r0
  JMP[NE] @mth_inv26_inverse
  ST r9,r5,263              ; input left
  ST r10,r5,264             ; target right
  JMP @mth_inv26_logits
mth_inv26_inverse:
  ST r10,r5,263             ; input right
  ST r9,r5,264              ; target left

mth_inv26_logits:
  MOVI r7,0
  LD r8,r5,263
  LD r9,r5,265
  LD r10,r5,256
mth_inv26_logits_loop:
  CMP r9,r0
  JMP[NE] @mth_inv26_transpose
  MOVI r12,26
  MUL r11,r8,r12
  ADD r11,r11,r7
  JMP @mth_inv26_load_logit
mth_inv26_transpose:
  MOVI r12,26
  MUL r11,r7,r12
  ADD r11,r11,r8
mth_inv26_load_logit:
  ADD r12,r10,r11
  LD r12,r12,0
  ADD r14,r5,r7
  ST r12,r14,0
  ADDI r7,r7,1
  MOVI r11,26
  CMP r7,r11
  JMP[LT] @mth_inv26_logits_loop
  MOVI r8,0
  MOVHI r8,0xFF80       ; all masked tail logits = -inf
mth_inv26_tail:
  ADD r9,r5,r7
  ST r8,r9,0
  ADDI r7,r7,1
  MOVI r9,256
  CMP r7,r9
  JMP[LT] @mth_inv26_tail

  ADD r1,r5,r0
  ADD r2,r5,r0
  CALL @mth_vector_softmax256_f32
  ADD r5,r2,r0            ; softmax preserves r2
  CMP r1,r13
  JMP[NE] @mth_inv26_failure

  ; Record target probability and top-1 correct, before any SGD update.
  LD r7,r5,264
  ADD r8,r5,r7
  LD r8,r8,0
  LD r9,r5,267
  FADD r9,r9,r8
  ST r9,r5,267
  MOVI r7,0
  MOVI r8,0               ; deterministic first-argmax index
  MOVI r9,0               ; max prob, valid since >0
mth_inv26_argmax:
  ADD r10,r5,r7
  LD r10,r10,0
  FCMP r10,r9
  JMP[LE] @mth_inv26_argmax_next
  ADD r8,r7,r0
  ADD r9,r10,r0
mth_inv26_argmax_next:
  ADDI r7,r7,1
  MOVI r10,26
  CMP r7,r10
  JMP[LT] @mth_inv26_argmax
  LD r10,r5,264
  CMP r8,r10
  JMP[NE] @mth_inv26_nohit
  LD r10,r5,266
  ADDI r10,r10,1
  ST r10,r5,266
mth_inv26_nohit:
  LD r8,r5,259
  FCMP r8,r0
  JMP[EQ] @mth_inv26_next
  MOVI r7,0
mth_inv26_update:
  ADD r10,r5,r7
  LD r10,r10,0             ; P[k]
  LD r11,r5,264
  CMP r7,r11
  JMP[NE] @mth_inv26_not_teacher
  MOVI r12,0
  MOVHI r12,0x3F80
  FSUB r10,r10,r12         ; P[k]-1
mth_inv26_not_teacher:
  FMUL r10,r10,r8          ; lr * gradient
  LD r11,r5,263
  LD r12,r5,265
  CMP r12,r0
  JMP[NE] @mth_inv26_update_inverse
  MOVI r12,26
  MUL r11,r11,r12
  ADD r11,r11,r7
  JMP @mth_inv26_apply
mth_inv26_update_inverse:
  MOVI r12,26
  MUL r12,r7,r12
  ADD r11,r12,r11
mth_inv26_apply:
  LD r12,r5,256
  ADD r11,r12,r11
  LD r12,r11,0
  FSUB r12,r12,r10
  ST r12,r11,0
  ADDI r7,r7,1
  MOVI r10,26
  CMP r7,r10
  JMP[LT] @mth_inv26_update

mth_inv26_next:
  LD r7,r5,262
  ADDI r7,r7,1
  ST r7,r5,262
  LD r8,r5,258
  CMP r7,r8
  JMP[LT] @mth_inv26_sample

  LD r6,r5,260
  LD r7,r5,266
  ST r7,r6,0
  LD r7,r5,267
  ST r7,r6,1
  LD r7,r5,258
  ST r7,r6,2
  LD r15,r5,261
  MOVI r1,1
  MOVI r9,0
  RET
mth_inv26_failure:
  LD r15,r5,261
mth_inv26_invalid:
  MOVI r1,0
  MOVI r9,1
  RET
