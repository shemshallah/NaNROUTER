; MTH single-head 16-key attention — NaN16 float32 only.
;
;   score[p]  = dot(q[0..15], K[p][0..15])
;   weight[p] = softmax(score)[p]                 (16 finite scores)
;   out[c]    = sum(p=0..15) weight[p] * V[p][c]
;
; The score vector is padded to 256 positions with -inf and passed to the
; verified 256-way softmax kernel, so the attention weights use the native
; stable softmax rather than a host or ad-hoc normalization. This is one
; attention head, not a multi-head block and not a full transformer.
;
; ABI (r13=1):
;   r1 = q[16], float32 word addresses
;   r2 = K[16][16], row-major key vectors
;   r3 = V[16][16], row-major value vectors
;   r4 = out[16], written on success only
;   r5 = caller scratch, 277 words:
;        [0..255] score/weight workspace
;        [256..271] output temporary
;        [272] q pointer, [273] K, [274] V, [275] out, [276] return link
;   r13 = 1
; Success: r1=1, r9=0.
; Rejection:
;   cause 1: q non-finite
;   cause 2: K non-finite
;   cause 3: V non-finite
;   cause 4: softmax rejected (1 or 2; scores are finite in the accepted domain)
;   cause 5: a finite-input value mix overflowed to a non-finite result
;   out untouched.
;
; Numeric order: dot products in increasing d; softmax is the verified
; 256-way kernel on the first 16 scores with the remaining 240 set to -inf;
; value mix is increasing p, one FMUL then one FADD. No FMA, host math, or
; static storage.

.include "mth_vector_softmax256_f32.nas"

mth_attention_head16_f32:
  MOVI r0,0
  ADD r6,r5,r0               ; scratch
  ; save pointers
  ST r1,r6,272
  ST r2,r6,273
  ST r3,r6,274
  ST r4,r6,275
  ST r15,r6,276

  ; q finite
  MOVI r9,0
  MOVHI r9,0x7F80
  MOVI r7,0
mth_attn_head_q_gate:
  ADD r8,r1,r7
  LD r8,r8,0
  BOOL.8 r10,r8,r9
  CMP r10,r9
  JMP[EQ] @mth_attn_head_bad_q
  ADDI r7,r7,1
  MOVI r8,16
  CMP r7,r8
  JMP[LT] @mth_attn_head_q_gate

  ; K finite
  MOVI r7,0
mth_attn_head_k_gate:
  MOVI r8,273
  ADD r8,r6,r8
  LD r8,r8,0
  ADD r8,r8,r7
  LD r8,r8,0
  BOOL.8 r10,r8,r9
  CMP r10,r9
  JMP[EQ] @mth_attn_head_bad_k
  ADDI r7,r7,1
  MOVI r8,256
  CMP r7,r8
  JMP[LT] @mth_attn_head_k_gate

  ; V finite
  MOVI r7,0
mth_attn_head_v_gate:
  MOVI r8,274
  ADD r8,r6,r8
  LD r8,r8,0
  ADD r8,r8,r7
  LD r8,r8,0
  BOOL.8 r10,r8,r9
  CMP r10,r9
  JMP[EQ] @mth_attn_head_bad_v
  ADDI r7,r7,1
  MOVI r8,256
  CMP r7,r8
  JMP[LT] @mth_attn_head_v_gate

  ; scores[p] = dot(q, K[p])
  MOVI r7,0                  ; p
mth_attn_head_score_p:
  MOVI r10,0                 ; acc
  MOVI r8,0                  ; d
mth_attn_head_score_d:
  ADD r9,r1,r8
  LD r9,r9,0                 ; q[d]
  SHL r12,r7,4
  ADD r12,r12,r8
  ADD r11,r2,r12
  LD r11,r11,0               ; K[p][d]
  FMUL r11,r11,r9
  FADD r10,r10,r11
  ADDI r8,r8,1
  MOVI r11,16
  CMP r8,r11
  JMP[LT] @mth_attn_head_score_d
  ADD r8,r6,r7
  ST r10,r8,0
  ADDI r7,r7,1
  MOVI r8,16
  CMP r7,r8
  JMP[LT] @mth_attn_head_score_p

  ; scratch[16..255] = -inf
  MOVI r8,0
  MOVHI r8,0xFF80
  MOVI r7,16
mth_attn_head_fill_tail:
  ADD r10,r6,r7
  ST r8,r10,0
  ADDI r7,r7,1
  MOVI r10,256
  CMP r7,r10
  JMP[LT] @mth_attn_head_fill_tail

  ; softmax in place; r2 is preserved as scratch base by the ABI
  ADD r1,r6,r0
  ADD r2,r6,r0
  CALL @mth_vector_softmax256_f32
  ADD r6,r2,r0               ; recover scratch base
  CMP r1,r13
  JMP[NE] @mth_attn_head_bad_softmax

  ; value mix into scratch[256+c]
  MOVI r7,0                  ; c
mth_attn_head_mix_c:
  MOVI r10,0                 ; acc
  MOVI r8,0                  ; p
mth_attn_head_mix_p:
  ADD r9,r6,r8
  LD r9,r9,0                 ; weight
  SHL r12,r8,4
  ADD r12,r12,r7
  MOVI r11,274
  ADD r11,r6,r11
  LD r11,r11,0
  ADD r11,r11,r12
  LD r11,r11,0               ; V[p][c]
  FMUL r11,r11,r9
  FADD r10,r10,r11
  ADDI r8,r8,1
  MOVI r11,16
  CMP r8,r11
  JMP[LT] @mth_attn_head_mix_p

  ; finite before publish
  MOVI r11,0
  MOVHI r11,0x7F80
  BOOL.8 r9,r10,r11
  CMP r9,r11
  JMP[EQ] @mth_attn_head_bad_result
  ADDI r9,r6,256
  ADD r9,r9,r7
  ST r10,r9,0
  ADDI r7,r7,1
  MOVI r9,16
  CMP r7,r9
  JMP[LT] @mth_attn_head_mix_c

  ; copy temp to out
  MOVI r7,0
mth_attn_head_copy:
  ADDI r9,r6,256
  ADD r9,r9,r7
  LD r10,r9,0
  MOVI r9,275
  ADD r9,r6,r9
  LD r9,r9,0
  ADD r9,r9,r7
  ST r10,r9,0
  ADDI r7,r7,1
  MOVI r9,16
  CMP r7,r9
  JMP[LT] @mth_attn_head_copy

  LD r15,r6,276
  MOVI r1,1
  MOVI r9,0
  RET

mth_attn_head_bad_q:
  MOVI r9,1
  JMP @mth_attn_head_reject
mth_attn_head_bad_k:
  MOVI r9,2
  JMP @mth_attn_head_reject
mth_attn_head_bad_v:
  MOVI r9,3
  JMP @mth_attn_head_reject
mth_attn_head_bad_softmax:
  MOVI r9,4
  JMP @mth_attn_head_reject
mth_attn_head_bad_result:
  MOVI r9,5
mth_attn_head_reject:
  LD r15,r6,276
  MOVI r1,0
  RET
