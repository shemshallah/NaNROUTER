; MTH 16-position attention mask — NaN16 float32 only.
;
; Applies a bit mask to 16 score words:
;
;   out[i] = score[i]  when bit i of mask is 1
;   out[i] = -inf       when bit i of mask is 0
;
; Bit 0 is position 0. A zero mask is rejected: an attention row with no
; allowed key has empty support. The kernel is mask transport only; it does
; not compute scores or softmax.
;
; ABI (r13=1):
;   r1 = scores[16], finite float32
;   r2 = mask, unsigned low 16 bits; zero rejected
;   r3 = out[16], may alias scores exactly
; Success: r1=1, r9=0.
; Rejection: r1=0, r9=1 non-finite score, r9=2 empty mask; out untouched.
; Clobbers r1-r8, flags; preserves r0, r9-r15.

mth_attention_mask16_f32:
  MOVI r0,0
  CMP r2,r0
  JMP[EQ] @mth_attn_mask_bad_mask

  ; preflight scores
  MOVI r6,0
  MOVI r8,0
  MOVHI r8,0x7F80
mth_attn_mask_gate:
  ADD r7,r1,r6
  LD r7,r7,0
  BOOL.8 r5,r7,r8
  CMP r5,r8
  JMP[EQ] @mth_attn_mask_bad_score
  ADDI r6,r6,1
  MOVI r7,16
  CMP r6,r7
  JMP[LT] @mth_attn_mask_gate

  ADD r5,r2,r0              ; mask working copy
  MOVI r6,0                  ; i
  MOVI r7,0
  MOVHI r7,0xFF80            ; -inf
  MOVI r8,1
mth_attn_mask_loop:
  BOOL.8 r10,r5,r8
  CMP r10,r0
  JMP[EQ] @mth_attn_mask_block
  ADD r10,r1,r6
  LD r10,r10,0
  JMP @mth_attn_mask_store
mth_attn_mask_block:
  ADD r10,r7,r0
mth_attn_mask_store:
  ADD r9,r3,r6
  ST r10,r9,0
  SHR r5,r5,1
  ADDI r6,r6,1
  MOVI r9,16
  CMP r6,r9
  JMP[LT] @mth_attn_mask_loop

  MOVI r1,1
  MOVI r9,0
  RET

mth_attn_mask_bad_score:
  MOVI r9,1
  JMP @mth_attn_mask_reject
mth_attn_mask_bad_mask:
  MOVI r9,2
mth_attn_mask_reject:
  MOVI r1,0
  RET
