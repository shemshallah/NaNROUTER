; MTH 256-way language cross-entropy — NaN16 only.
;
;   loss = logsumexp(logits) - logits[target]
;
; ABI (r13=1):
;   r1 = logits, 256 float32 payloads (read-only)
;   r2 = target class, unsigned 0..255
;   r3 = out, one float32 word address (written on success only)
;   r4 = caller scratch, 5 words: logits, out, target, lse, return link
;   r13 = 1
; Success: r1=1, r9=0, out = loss.
; Rejection:
;   cause 1/2: logsumexp rejection (NaN/+inf, or empty support)
;   cause 3: target outside 0..255
;   r1=0, r9=cause, out untouched.
;
; The target check runs before the logsumexp call. The loss is exactly one
; FSUB after the stable logsumexp. No host math, table, static storage, or
; allocation. Clobbers r1-r12, r14; preserves r0, r13, r15.

.include "mth_vector_logsumexp256_f32.nas"

mth_lm_cross_entropy256_f32:
  MOVI r0,0
  ADD r6,r4,r0               ; scratch
  ST r1,r6,0                 ; logits
  ST r3,r6,1                 ; out
  ST r2,r6,2                 ; target
  ADDI r7,r6,4
  ST r15,r7,0                ; return

  ; target domain 0..255
  MOVI r8,256
  CMP r2,r8
  JMP[GE] @mth_lm_ce_bad_target

  LD r1,r6,0
  ADDI r2,r6,3
  CALL @mth_vector_logsumexp256_f32
  ADDI r6,r2,-3              ; logsumexp preserves r2 = scratch+3
  CMP r1,r13
  JMP[NE] @mth_lm_ce_reject

  LD r2,r6,2                 ; target
  LD r1,r6,0                 ; logits
  ADD r1,r1,r2
  LD r1,r1,0                 ; logits[target]
  LD r3,r6,3                 ; lse
  FSUB r3,r3,r1
  LD r2,r6,1                 ; out
  ST r3,r2,0

  ADDI r7,r6,4
  LD r15,r7,0
  MOVI r1,1
  MOVI r9,0
  RET

mth_lm_ce_bad_target:
  MOVI r9,3
  JMP @mth_lm_ce_reject
mth_lm_ce_reject:
  ADDI r7,r6,4
  LD r15,r7,0
  MOVI r1,0
  RET
