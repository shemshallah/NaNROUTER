; NaN16 reverse-mode for 16-triad masked focal softmax and 16D value mix.
; Forward out[c]=sum_p weights[p]*V[p,c], where weights from
; mth_global_focus16_f32 are softmax of masked 16 logits and sum to 1.
; Backward:
;   dw[p] = sum_c upstream[c]*V[p,c]
;   mu = sum_p weights[p]*dw[p]
;   dscore[p] = weights[p]*(dw[p]-mu)
;   dV[p,c] = weights[p]*upstream[c].
; An exactly zero masked weight yields zero dscore and zero dV.
; ABI (r13=1): r1=weights16 f32, r2=V256 f32, r3=upstream16 f32,
; r4=dscore16 f32, r5=dV256 f32, r6=scratch288 f32.
; Scratch [0..15]=dw, [16..271]=dV, [272..287]=dscore.
; All arrays disjoint, finite source, weights nonnegative <=1,
; sum weights approximately 1 enforced by the caller's forward kernel.
; NaN or overflow rejects without touching output arrays.
; r1=1,r9=0 success; r1=0,r9=1 failure. All math NaN16 guest f32.
mth_global_focus16_backward_f32:
  MOVI r0,0
  MOVI r14,0
  MOVHI r14,0x7F80
  MOVI r7,0
mth_gfb_gate_w:
  ADD r8,r1,r7
  LD r8,r8,0
  BOOL.8 r9,r8,r14
  CMP r9,r14
  JMP[EQ] @mth_gfb_bad
  FCMP r8,r0
  JMP[LT] @mth_gfb_bad
  MOVI r9,0
  MOVHI r9,0x3F80
  FCMP r8,r9
  JMP[GT] @mth_gfb_bad
  ADD r8,r3,r7
  LD r8,r8,0
  BOOL.8 r9,r8,r14
  CMP r9,r14
  JMP[EQ] @mth_gfb_bad
  ADDI r7,r7,1
  MOVI r9,16
  CMP r7,r9
  JMP[LT] @mth_gfb_gate_w
  MOVI r7,0
mth_gfb_gate_v:
  ADD r8,r2,r7
  LD r8,r8,0
  BOOL.8 r9,r8,r14
  CMP r9,r14
  JMP[EQ] @mth_gfb_bad
  ADDI r7,r7,1
  MOVI r9,256
  CMP r7,r9
  JMP[LT] @mth_gfb_gate_v
  MOVI r7,0               ; p
mth_gfb_p:
  MOVI r8,0               ; c
  MOVI r9,0               ; dot accumulation dw[p]
mth_gfb_c:
  SHL r10,r7,4
  ADD r10,r10,r8
  ADD r11,r2,r10
  LD r11,r11,0            ; V[p,c]
  ADD r12,r3,r8
  LD r12,r12,0            ; grad[c]
  FMUL r11,r11,r12
  FADD r9,r9,r11
  ADD r11,r1,r7
  LD r11,r11,0            ; w[p]
  FMUL r11,r11,r12
  ADDI r10,r10,16
  ADD r10,r6,r10
  ST r11,r10,0            ; staged dV[p,c]
  ADDI r8,r8,1
  MOVI r10,16
  CMP r8,r10
  JMP[LT] @mth_gfb_c
  ADD r10,r6,r7
  ST r9,r10,0             ; staged dw[p]
  ADDI r7,r7,1
  MOVI r10,16
  CMP r7,r10
  JMP[LT] @mth_gfb_p

  ; mu = sum_p w[p]*dw[p]
  MOVI r7,0
  MOVI r8,0               ; mu
mth_gfb_mean:
  ADD r9,r1,r7
  LD r9,r9,0
  ADD r10,r6,r7
  LD r10,r10,0
  FMUL r9,r9,r10
  FADD r8,r8,r9
  ADDI r7,r7,1
  MOVI r9,16
  CMP r7,r9
  JMP[LT] @mth_gfb_mean

  MOVI r7,0
mth_gfb_ds:
  ADD r9,r6,r7
  LD r9,r9,0
  FSUB r9,r9,r8
  ADD r10,r1,r7
  LD r10,r10,0
  FMUL r9,r9,r10
  ; For a masked weight=+0.0, canonicalize -0.0 score gradient
  ; to +0.0 so exact transport / deterministic mask tests agree.
  FCMP r10,r0
  JMP[NE] @mth_gfb_ds_store
  MOVI r9,0
mth_gfb_ds_store:
  ADDI r10,r6,272
  ADD r10,r10,r7
  ST r9,r10,0
  ADDI r7,r7,1
  MOVI r9,16
  CMP r7,r9
  JMP[LT] @mth_gfb_ds

  ; No publication until every staged gradient passes finite check.
  MOVI r7,0
mth_gfb_check:
  ADD r8,r6,r7
  LD r8,r8,0
  BOOL.8 r9,r8,r14
  CMP r9,r14
  JMP[EQ] @mth_gfb_bad
  ADDI r7,r7,1
  MOVI r9,288
  CMP r7,r9
  JMP[LT] @mth_gfb_check
  MOVI r7,0
mth_gfb_publish:
  ADDI r8,r6,272
  ADD r8,r8,r7
  LD r8,r8,0
  ADD r9,r4,r7
  ST r8,r9,0
  MOVI r8,0
mth_gfb_publish_dv:
  SHL r9,r7,4
  ADD r9,r9,r8
  ADDI r10,r6,16
  ADD r10,r10,r9
  LD r10,r10,0
  ADD r11,r5,r9
  ST r10,r11,0
  ADDI r8,r8,1
  MOVI r10,16
  CMP r8,r10
  JMP[LT] @mth_gfb_publish_dv
  ADDI r7,r7,1
  MOVI r9,16
  CMP r7,r9
  JMP[LT] @mth_gfb_publish
  MOVI r1,1
  MOVI r9,0
  RET
mth_gfb_bad:
  MOVI r1,0
  MOVI r9,1
  RET
