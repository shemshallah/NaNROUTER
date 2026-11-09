; MTH 256-element float32 log-softmax — NaN16 only.
;
;   out[i] = x[i] - logsumexp(x)
;
; ABI (r13=1):
;   r1 = x, 256 float32 payloads (read-only)
;   r2 = out, 256 float32 payloads (written on success only)
;   r3 = caller scratch, 4 words: x pointer, out pointer, lse, return link
;   r13 = 1
; Success: r1=1, r9=0, out complete.
; Rejection: r1=0, r9 is the logsumexp cause (1 NaN/+inf, 2 empty support);
; out is untouched because logsumexp completes before the first subtraction
; and the caller's out pointer is only used after success.
;
; The kernel calls the verified logsumexp leaf, then performs exactly one FSUB
; per output element in increasing order. No host math, no table, no static
; storage. Preserves r0, r13-r15; clobbers r1-r12, r14.

.include "mth_vector_logsumexp256_f32.nas"

mth_vector_logsoftmax256_f32:
  MOVI r0,0
  ADD r6,r3,r0               ; scratch
  ST r1,r6,0                 ; x pointer
  ST r2,r6,1                 ; out pointer
  ADDI r7,r6,3
  ST r15,r7,0                ; return link

  LD r1,r6,0
  ADDI r2,r6,2
  CALL @mth_vector_logsumexp256_f32
  ADDI r6,r2,-2              ; logsumexp preserves r2 = scratch+2
  CMP r1,r13
  JMP[NE] @mth_vlsm256_reject

  LD r1,r6,0                 ; x
  LD r2,r6,1                 ; out
  LD r7,r6,2                 ; lse
  MOVI r4,0                  ; i
mth_vlsm256_loop:
  ADD r8,r1,r4
  LD r9,r8,0
  FSUB r9,r9,r7
  ADD r8,r2,r4
  ST r9,r8,0
  ADDI r4,r4,1
  MOVI r8,256
  CMP r4,r8
  JMP[LT] @mth_vlsm256_loop

  ADDI r7,r6,3
  LD r15,r7,0
  MOVI r1,1
  MOVI r9,0
  RET

mth_vlsm256_reject:
  ADDI r7,r6,3
  LD r15,r7,0
  MOVI r1,0
  RET
