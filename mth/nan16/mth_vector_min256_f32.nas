; MTH 256-element float32 minimum — NaN16 only.
;
; ABI:
;   r1  = x, 256 float32 payloads (read-only)
;   r2  = out, one float32 payload (written on success only)
;   r13 = 1
;   returns r1 = 1 on success, r1 = 0 on rejection
;   clobbers r1, r4-r8 and the flags
;   preserves r0, r2, r3, r9-r15
;
; Result:
;   out = the exact 32-bit payload of x[i] for the smallest index i whose
;   value is the minimum of x[0..255].
;
; DOMAIN AND FAIL-CLOSED POLICY:
;   Every input element must be finite: neither NaN nor +inf nor -inf.
;   A preflight over all 256 words tests
;
;     (payload & 0x7F800000) == 0x7F800000
;
;   which is exactly the binary32 exponent-all-ones class (NaN and both
;   infinities). The first such element rejects the call with r1=0. The whole
;   preflight finishes before the scan and before the output store, so on
;   rejection out is untouched. The kernel never attempts NaN ordering or
;   IEEE maxNum/minNum semantics.
;
; FIRST-INDEX TIE RULE:
;   The scan starts with x[0] as the running best and visits i = 1..255 in
;   increasing order. The running best is replaced only when candidate <
;   best (strictly less), so an equal value never replaces the current best.
;   The first index among equal minima wins. This matters for the signed
;   zeros: -0.0 and +0.0 compare equal under float32 FCMP, so out is the
;   exact payload of the first zero encountered when the minimum is zero.
;   With all 256 values equal, the result is exactly the payload of x[0].
;
; No host math, no CALL, no static storage, and no allocation. The kernel
; uses integer address arithmetic, one exact float32 FCMP per scanned element
; after the preflight, and bit copies.

mth_vector_min256_f32:
  ; Preflight: reject any non-finite payload before touching the output.
  MOVI r5,0
  MOVHI r5,0x7F80            ; r5 = 0x7F800000 exponent mask
  MOVI r4,0                  ; i = 0
mth_vector_min256_preflight:
  ADD r6,r1,r4
  LD r6,r6,0
  BOOL.8 r6,r6,r5            ; exponent bits only
  CMP r6,r5
  JMP[EQ] @mth_vector_min256_invalid
  ADD r4,r4,r13
  MOVI r6,256
  CMP r4,r6
  JMP[LT] @mth_vector_min256_preflight

  ; Seed with x[0]. The preflight proved it finite, so every later FCMP is
  ; ordered and the strict-predicate scan is total.
  LD r6,r1,0                 ; best value payload
  MOVI r4,1                  ; i = 1
mth_vector_min256_scan:
  ADD r5,r1,r4
  LD r8,r5,0                 ; candidate
  FCMP r8,r6
  JMP[LT] @mth_vector_min256_take
  JMP @mth_vector_min256_next
mth_vector_min256_take:
  ADD r6,r8,r0               ; best = candidate (exact payload copy)
mth_vector_min256_next:
  ADD r4,r4,r13
  MOVI r5,256
  CMP r4,r5
  JMP[LT] @mth_vector_min256_scan

  ST r6,r2,0                 ; publish only after the complete scan
  MOVI r1,1
  RET

mth_vector_min256_invalid:
  MOVI r1,0
  RET
