; NaN16 native inverse/forward 26-symbol streaming trigram hypertensor SGD.
; Tensor T[a,b,c] is 26^3 = 17576 float32 learnable association cells.
; It receives one-hot rank-3 streaming character triples e_a⊗e_b⊗e_c.
; This is a true third-order tensor of associations, not a matrix of
; vector observations, not a new standalone language model.
;
; Forward: p(c|a,b) via logits[k] = T[a,b,k]
; Inverse: p(a|b,c) via logits[k] = T[k,b,c]
; The SAME tensor and SGD update rule serve both directions:
; T[index(k)] -= lr*(softmax(logits)[k] - 1{k=target}).
;
; ABI r1=T[17576] f32, r2=training sample[4]*count U32,
;     r3=count [1..4096], r4=lr finite f32 in [0,1/4],
;     r5=scratch[270] words, r6=metrics[3] words.
; sample=[a,b,c,direction] with a,b,c in [0,25], dir0/1.
; Metrics [integer correct, f32 sum target probabilities, int examples].
; Fully native softmax, gradient, SGD and evaluation. Same data path with
; learning rate zero performs read-only held-out scoring.
; PRECHECK validates all tensor values and inputs before training begins,
; but this in-place experiment is NOT a transactional root update; a
; nonfinite arithmetic result after an update may partially modify tensor.
; Caller must use ephemeral guest scratch and keep 43M root read-only.
; Semantic head 255 remains reserved void, physically unchanged.
.include "mth_global_focus16_f32.nas"

mth_inverse_trigram26_batch_f32:
  MOVI r0,0
  MOVI r8,0
  MOVHI r8,0x7F80
  BOOL.8 r7,r4,r8
  CMP r7,r8
  JMP[EQ] @mth_it26_invalid
  FCMP r4,r0
  JMP[LT] @mth_it26_invalid
  MOVI r7,0
  MOVHI r7,0x3E80
  FCMP r4,r7
  JMP[GT] @mth_it26_invalid
  CMP r3,r0
  JMP[LE] @mth_it26_invalid
  MOVI r7,4096
  CMP r3,r7
  JMP[GT] @mth_it26_invalid

  MOVI r7,0
mth_it26_preflight_t:
  ADD r10,r1,r7
  LD r10,r10,0
  BOOL.8 r11,r10,r8
  CMP r11,r8
  JMP[EQ] @mth_it26_invalid
  ADDI r7,r7,1
  MOVI r10,17576
  CMP r7,r10
  JMP[LT] @mth_it26_preflight_t

  MOVI r7,0
mth_it26_preflight_samples:
  MOVI r10,4
  MUL r10,r7,r10
  ADD r10,r2,r10
  MOVI r11,0
mth_it26_check_char:
  ADD r12,r10,r11
  LD r12,r12,0
  SHR r14,r12,5
  CMP r14,r0
  JMP[NE] @mth_it26_invalid
  MOVI r14,26
  CMP r12,r14
  JMP[GE] @mth_it26_invalid
  ADDI r11,r11,1
  MOVI r14,3
  CMP r11,r14
  JMP[LT] @mth_it26_check_char
  LD r12,r10,3
  MOVI r14,1
  CMP r12,r14
  JMP[GT] @mth_it26_invalid
  ADDI r7,r7,1
  CMP r7,r3
  JMP[LT] @mth_it26_preflight_samples

  ST r1,r5,256           ; tensor base
  ST r2,r5,257           ; samples
  ST r3,r5,258           ; count
  ST r4,r5,259           ; lr
  ST r6,r5,260           ; metrics
  ST r15,r5,261          ; return link
  ST r0,r5,262           ; sample index
  ST r0,r5,268           ; count correct
  ST r0,r5,269           ; sum target p

mth_it26_sample:
  LD r7,r5,262
  LD r8,r5,257
  MOVI r9,4
  MUL r9,r7,r9
  ADD r8,r8,r9
  LD r9,r8,0
  ST r9,r5,263           ; a
  LD r9,r8,1
  ST r9,r5,264           ; b
  LD r9,r8,2
  ST r9,r5,265           ; c
  LD r9,r8,3
  ST r9,r5,266           ; direction
  CMP r9,r0
  JMP[NE] @mth_it26_target_inverse
  LD r9,r5,265
  JMP @mth_it26_target_ready
mth_it26_target_inverse:
  LD r9,r5,263
mth_it26_target_ready:
  ST r9,r5,267

  MOVI r7,0
mth_it26_logits:
  LD r8,r5,266
  CMP r8,r0
  JMP[NE] @mth_it26_logit_inverse
  ; T[a,b,k] = a*676 + b*26 + k.
  LD r8,r5,263
  MOVI r9,676
  MUL r11,r8,r9
  LD r8,r5,264
  MOVI r9,26
  MUL r12,r8,r9
  ADD r11,r11,r12
  ADD r11,r11,r7
  JMP @mth_it26_load_logit
mth_it26_logit_inverse:
  ; T[k,b,c] = k*676 + b*26 + c.
  MOVI r9,676
  MUL r11,r7,r9
  LD r8,r5,264
  MOVI r9,26
  MUL r12,r8,r9
  ADD r11,r11,r12
  LD r8,r5,265
  ADD r11,r11,r8
mth_it26_load_logit:
  LD r12,r5,256
  ADD r12,r12,r11
  LD r12,r12,0
  ADD r14,r5,r7
  ST r12,r14,0
  ADDI r7,r7,1
  MOVI r11,26
  CMP r7,r11
  JMP[LT] @mth_it26_logits
  MOVI r8,0
  MOVHI r8,0xFF80       ; -inf tail for stable 256 softmax
mth_it26_tail:
  ADD r9,r5,r7
  ST r8,r9,0
  ADDI r7,r7,1
  MOVI r9,256
  CMP r7,r9
  JMP[LT] @mth_it26_tail

  ADD r1,r5,r0
  ADD r2,r5,r0
  CALL @mth_vector_softmax256_f32
  ADD r5,r2,r0
  CMP r1,r13
  JMP[NE] @mth_it26_failure

  LD r7,r5,267
  ADD r8,r5,r7
  LD r8,r8,0
  LD r9,r5,269
  FADD r9,r9,r8
  ST r9,r5,269
  MOVI r7,0
  MOVI r8,0                ; argmax index
  MOVI r9,0                ; argmax score
mth_it26_argmax:
  ADD r10,r5,r7
  LD r10,r10,0
  FCMP r10,r9
  JMP[LE] @mth_it26_argmax_next
  ADD r8,r7,r0
  ADD r9,r10,r0
mth_it26_argmax_next:
  ADDI r7,r7,1
  MOVI r10,26
  CMP r7,r10
  JMP[LT] @mth_it26_argmax
  LD r10,r5,267
  CMP r8,r10
  JMP[NE] @mth_it26_no_hit
  LD r10,r5,268
  ADDI r10,r10,1
  ST r10,r5,268
mth_it26_no_hit:
  LD r8,r5,259
  FCMP r8,r0
  JMP[EQ] @mth_it26_next
  MOVI r7,0
mth_it26_sgd:
  ADD r10,r5,r7
  LD r10,r10,0          ; softmax p[k]
  LD r11,r5,267
  CMP r7,r11
  JMP[NE] @mth_it26_no_teacher
  MOVI r12,0
  MOVHI r12,0x3F80
  FSUB r10,r10,r12      ; p[k]-1
mth_it26_no_teacher:
  FMUL r10,r10,r8       ; lr * gradient

  LD r12,r5,266
  CMP r12,r0
  JMP[NE] @mth_it26_sgd_inverse
  LD r11,r5,263
  MOVI r12,676
  MUL r11,r11,r12
  LD r12,r5,264
  MOVI r14,26
  MUL r12,r12,r14
  ADD r11,r11,r12
  ADD r11,r11,r7
  JMP @mth_it26_apply_sgd
mth_it26_sgd_inverse:
  MOVI r12,676
  MUL r11,r7,r12
  LD r12,r5,264
  MOVI r14,26
  MUL r12,r12,r14
  ADD r11,r11,r12
  LD r12,r5,265
  ADD r11,r11,r12
mth_it26_apply_sgd:
  LD r12,r5,256
  ADD r11,r12,r11
  LD r12,r11,0
  FSUB r12,r12,r10
  ST r12,r11,0
  ADDI r7,r7,1
  MOVI r10,26
  CMP r7,r10
  JMP[LT] @mth_it26_sgd

mth_it26_next:
  LD r7,r5,262
  ADDI r7,r7,1
  ST r7,r5,262
  LD r8,r5,258
  CMP r7,r8
  JMP[LT] @mth_it26_sample

  LD r6,r5,260
  LD r7,r5,268
  ST r7,r6,0
  LD r7,r5,269
  ST r7,r6,1
  LD r7,r5,258
  ST r7,r6,2
  LD r15,r5,261
  MOVI r1,1
  MOVI r9,0
  RET
mth_it26_failure:
  LD r15,r5,261
mth_it26_invalid:
  MOVI r1,0
  MOVI r9,1
  RET
