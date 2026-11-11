; Native 16-trihead global masked focal softmax + value mixing, NaN16 f32.
; Scores can be assembled from hot/cold, Hodge, hyperbolic and spectral
; feature channels by earlier native stages. This kernel never invents them.
; ABI (r13=1): r1=scores[16] finite, r2=nonzero 16-bit support mask,
;   r3=values[16][16] finite, r4=out[16], r5=scratch[277] disjoint.
; scratch[0..255]=score/weight, [256..271]=output temp,
; [272]=scores ptr [273]=mask [274]=values ptr [275]=out ptr [276]=saved r15.
; Output atomic, mask excludes cold/unknown only WHEN the caller chooses to
; mask them; cold observations themselves remain valid candidates.
; Returns r1=1,r9=0 or r1=0,r9=1 finite error,2 empty mask,
; 3 softmax reject,4 nonfinite mix. No host arithmetic or writes to root.
.include "mth_vector_softmax256_f32.nas"
mth_global_focus16_f32:
  MOVI r0,0
  ADD r6,r5,r0
  ST r1,r6,272
  ST r2,r6,273
  ST r3,r6,274
  ST r4,r6,275
  ST r15,r6,276
  CMP r2,r0
  JMP[EQ] @mth_gf16_empty
  ; Reject invalid scores (including masked positions) or values before output.
  MOVI r9,0
  MOVHI r9,0x7F80
  MOVI r7,0
mth_gf16_score_gate:
  ADD r8,r1,r7
  LD r8,r8,0
  BOOL.8 r10,r8,r9
  CMP r10,r9
  JMP[EQ] @mth_gf16_bad
  ADDI r7,r7,1
  MOVI r8,16
  CMP r7,r8
  JMP[LT] @mth_gf16_score_gate
  MOVI r7,0
mth_gf16_value_gate:
  ADD r8,r3,r7
  LD r8,r8,0
  BOOL.8 r10,r8,r9
  CMP r10,r9
  JMP[EQ] @mth_gf16_bad
  ADDI r7,r7,1
  MOVI r8,256
  CMP r7,r8
  JMP[LT] @mth_gf16_value_gate

  MOVI r7,0
  MOVI r12,1            ; rolling permitted-position bit
  MOVI r14,0
  MOVHI r14,0xFF80        ; -inf
mth_gf16_mask_scores:
  BOOL.8 r9,r12,r2
  CMP r9,r0
  JMP[EQ] @mth_gf16_masked
  ADD r8,r1,r7
  LD r8,r8,0
  JMP @mth_gf16_store_score
mth_gf16_masked:
  ADD r8,r14,r0
mth_gf16_store_score:
  ADD r9,r6,r7
  ST r8,r9,0
  SHL r12,r12,1
  ADDI r7,r7,1
  MOVI r9,16
  CMP r7,r9
  JMP[LT] @mth_gf16_mask_scores
mth_gf16_tail:
  ADD r9,r6,r7
  ST r14,r9,0
  ADDI r7,r7,1
  MOVI r9,256
  CMP r7,r9
  JMP[LT] @mth_gf16_tail

  ADD r1,r6,r0
  ADD r2,r6,r0
  CALL @mth_vector_softmax256_f32
  ADD r6,r2,r0            ; softmax preserves its second argument
  CMP r1,r13
  JMP[NE] @mth_gf16_bad_softmax

  MOVI r7,0
mth_gf16_component:
  MOVI r10,0
  MOVI r8,0
mth_gf16_weighted:
  ADD r9,r6,r8
  LD r9,r9,0
  SHL r12,r8,4
  ADD r12,r12,r7
  LD r11,r6,274
  ADD r11,r11,r12
  LD r11,r11,0
  FMUL r11,r11,r9
  FADD r10,r10,r11
  ADDI r8,r8,1
  MOVI r11,16
  CMP r8,r11
  JMP[LT] @mth_gf16_weighted
  MOVI r11,0
  MOVHI r11,0x7F80
  BOOL.8 r9,r10,r11
  CMP r9,r11
  JMP[EQ] @mth_gf16_bad_mix
  ADDI r9,r6,256
  ADD r9,r9,r7
  ST r10,r9,0
  ADDI r7,r7,1
  MOVI r9,16
  CMP r7,r9
  JMP[LT] @mth_gf16_component
  MOVI r7,0
mth_gf16_publish:
  ADDI r9,r6,256
  ADD r9,r9,r7
  LD r10,r9,0
  LD r9,r6,275
  ADD r9,r9,r7
  ST r10,r9,0
  ADDI r7,r7,1
  MOVI r9,16
  CMP r7,r9
  JMP[LT] @mth_gf16_publish
  LD r15,r6,276
  MOVI r9,0
  MOVI r1,1
  RET
mth_gf16_empty:
  MOVI r9,2
  JMP @mth_gf16_reject
mth_gf16_bad:
  MOVI r9,1
  JMP @mth_gf16_reject
mth_gf16_bad_softmax:
  MOVI r9,3
  JMP @mth_gf16_reject
mth_gf16_bad_mix:
  MOVI r9,4
mth_gf16_reject:
  LD r15,r6,276
  MOVI r1,0
  RET
