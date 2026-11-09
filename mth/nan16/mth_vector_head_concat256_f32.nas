; MTH two-head float32 concatenation (128 + 128 -> 256) — NaN16 only.
;
; ABI:
;   r1  = head A, 128 float32 payloads (read-only)
;   r2  = head B, 128 float32 payloads (read-only)
;   r3  = out, 256 float32 payloads
;   r13 = 1
;   returns r1 = 1 on success, r1 = 0 on rejection
;   on success r9 = 0; on rejection r9 = cause code
;   clobbers r1, r4-r9 and the flags
;   preserves r0, r2, r3, r10-r15
;
; Result on success:
;   out[0..127]   = A[0..127]
;   out[128..255] = B[0..127]
;
; Every word is copied as its exact 32-bit payload in increasing i order.
; There is no arithmetic, no rounding, no reordering, no host math, and no
; recombination. The A/B boundary is the word pair out[127] / out[128].
;
; DOMAIN AND FAIL-CLOSED POLICY:
;   Every input word must be finite. A complete preflight over all 128 A
;   words runs first, then a complete preflight over all 128 B words. Each
;   test is
;
;     (payload & 0x7F800000) == 0x7F800000
;
;   which is exactly the binary32 exponent-all-ones class (NaN and both
;   infinities). No output store occurs until both preflights pass, so a
;   rejection is atomic: out[0..255] is left untouched. A NaN or infinity is
;   never copied into a result.
;
; STATUS CONVENTION:
;   success: r1 = 1, r9 = 0, out[0..255] = concatenated payloads.
;   failure: r1 = 0, r9 = cause, out[] unchanged.
;   cause 1: non-finite A element (NaN, +inf, or -inf).
;   cause 2: non-finite B element (NaN, +inf, or -inf).
;   The A preflight has priority because it completes before B is examined.
;
; COPY ORDER AND ALIASING:
;   B is copied to out[128..255] first, then A to out[0..127]. The order is
;   chosen so exact out == A and exact out == B are both safe:
;     - out == A: the B pass writes only the upper half; the A pass then
;       stores each A[i] to the same address it was loaded from.
;     - out == B: the B pass consumes B before the A pass overwrites the
;       lower half with A.
;   If A == B == out, the B pass reads the lower half and writes the upper
;   half, then the A pass stores the lower half to itself.
;
;   The caller must ensure that any input that is not an exact base alias of
;   out (that is, not the input at out[0..127]) is disjoint from the entire
;   256-word output span. In particular, partial overlap between an input
;   and out is not supported, and an input placed at out[128..255] is not a
;   promised alias even when that would happen to be a self-copy. No overlap
;   or length validation is performed.

mth_vector_head_concat256_f32:
  MOVI r4,0
  MOVHI r4,0x7F80            ; r4 = 0x7F800000 exponent mask

  ; Preflight all of A before examining B or writing out.
  MOVI r5,0
mth_hc256_a_preflight:
  ADD r6,r1,r5
  LD r7,r6,0
  BOOL.8 r7,r7,r4            ; exponent bits of A[i]
  CMP r7,r4
  JMP[EQ] @mth_hc256_nonfinite_a
  ADD r5,r5,r13
  MOVI r6,128
  CMP r5,r6
  JMP[LT] @mth_hc256_a_preflight

  ; Preflight all of B before the first output store.
  MOVI r5,0
mth_hc256_b_preflight:
  ADD r6,r2,r5
  LD r7,r6,0
  BOOL.8 r7,r7,r4            ; exponent bits of B[i]
  CMP r7,r4
  JMP[EQ] @mth_hc256_nonfinite_b
  ADD r5,r5,r13
  MOVI r6,128
  CMP r5,r6
  JMP[LT] @mth_hc256_b_preflight

  ; B first: out[128..255] = B[0..127].
  MOVI r5,0
mth_hc256_copy_b:
  ADD r6,r2,r5
  LD r7,r6,0                 ; B[i], exact payload
  ADD r6,r3,r5
  ADDI r6,r6,128             ; &out[128+i]
  ST r7,r6,0
  ADD r5,r5,r13
  MOVI r6,128
  CMP r5,r6
  JMP[LT] @mth_hc256_copy_b

  ; A second: out[0..127] = A[0..127].
  MOVI r5,0
mth_hc256_copy_a:
  ADD r6,r1,r5
  LD r7,r6,0                 ; A[i], exact payload
  ADD r6,r3,r5               ; &out[i]
  ST r7,r6,0
  ADD r5,r5,r13
  MOVI r6,128
  CMP r5,r6
  JMP[LT] @mth_hc256_copy_a

  MOVI r9,0
  MOVI r1,1
  RET

mth_hc256_nonfinite_a:
  MOVI r9,1
  MOVI r1,0
  RET

mth_hc256_nonfinite_b:
  MOVI r9,2
  MOVI r1,0
  RET
