; MTH retrieval top-1 over up to 12 float32 score words — NaN16 only.
;
; ABI:
;   r1  = scores, count float32 payloads (read-only), count <= 12
;   r2  = count, unsigned integer 1..12
;   r13 = 1
;   returns r1 = 1 on success; r3 = winning index 0..11;
;           r4 = winning score payload (exact 32-bit copy)
;   returns r1 = 0 on rejection; r3 and r4 are unchanged
;   clobbers r1, r5-r12 and the flags
;   preserves r0, r2, r3, r4, r13-r15
;
; Selection:
;   The scan seeds the winner with index 0 and visits 1..count-1 in
;   increasing order. The running winner is replaced only when
;   candidate > best (strictly greater). An equal value never replaces the
;   current winner, so the first index among equal maxima wins. Because
;   -0.0 and +0.0 compare equal under float32 FCMP, the first zero wins a
;   zero tie and r4 keeps that occurrence's exact payload bits.
;
; Domain and fail-closed policy:
;   count must be 1..12. A count of 0, or any unsigned value above 12, is
;   rejected before the score array is read. Every score in 0..count-1 must
;   be finite: neither NaN nor +inf nor -inf. The preflight tests
;
;     (payload & 0x7F800000) == 0x7F800000
;
;   which is exactly the binary32 exponent-all-ones class, and rejects the
;   call with r1=0. The count check and the complete score preflight finish
;   before r3 or r4 is written, so a rejected call leaves both outputs
;   untouched. This is a finite-domain contract: the kernel never returns a
;   result for a non-finite input and does not attempt NaN ordering or IEEE
;   maxNum/minNum semantics.
;
; No host math, no CALL, no static storage, and no allocation. The kernel
; uses only integer address arithmetic, the exponent mask, one exact float32
; FCMP per scanned element after preflight, and bit copies.

mth_retrieval_top1_f32:
mth_retrieval_top1:
  ; Count domain: reject 0 and every unsigned count above 12 before any
  ; score-word load or output write.
  CMP r2,r0
  JMP[EQ] @mth_retrieval_top1_reject
  MOVI r12,12
  CMP r2,r12
  JMP[GT] @mth_retrieval_top1_reject

  ; Preflight every in-range score before touching either output register.
  MOVI r5,0
  MOVHI r5,0x7F80            ; r5 = 0x7F800000 exponent mask
  MOVI r10,0                 ; i = 0
mth_retrieval_top1_preflight:
  CMP r10,r2
  JMP[GE] @mth_retrieval_top1_preflight_done
  ADD r9,r1,r10
  LD r8,r9,0                 ; candidate payload
  BOOL.8 r8,r8,r5            ; exponent bits only
  CMP r8,r5
  JMP[EQ] @mth_retrieval_top1_reject
  ADD r10,r10,r13
  JMP @mth_retrieval_top1_preflight
mth_retrieval_top1_preflight_done:

  ; Seed with index 0. The preflight proved every in-range score finite, so
  ; each later FCMP is ordered.
  LD r6,r1,0                 ; best score payload
  MOVI r7,0                  ; best index
  MOVI r10,1                 ; i = 1
mth_retrieval_top1_scan:
  CMP r10,r2
  JMP[GE] @mth_retrieval_top1_publish
  ADD r9,r1,r10
  LD r8,r9,0                 ; candidate score payload
  FCMP r8,r6
  JMP[GT] @mth_retrieval_top1_take
  JMP @mth_retrieval_top1_next
mth_retrieval_top1_take:
  ADD r6,r8,r0               ; best = candidate (exact payload copy)
  ADD r7,r10,r0              ; best index = i
mth_retrieval_top1_next:
  ADD r10,r10,r13
  JMP @mth_retrieval_top1_scan

mth_retrieval_top1_publish:
  ADD r3,r7,r0               ; publish index only after the full scan
  ADD r4,r6,r0               ; publish score payload (exact copy)
  ADD r1,r0,r13              ; r1 = 1, full 32-bit result
  RET

mth_retrieval_top1_reject:
  ADD r1,r0,r0               ; r1 = 0; r3 and r4 remain untouched
  RET
