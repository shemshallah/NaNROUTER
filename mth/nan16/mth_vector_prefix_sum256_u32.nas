; MTH inclusive prefix sum over 256 unsigned 32-bit words — NaN16 only.
;
; ABI (r13=1):
;   r1  = x, 256 U32 input words
;   r2  = out, 256 U32 output words
;   r13 = 1 (element stride)
;   returns r1 = 1 on success, r1 = 0 on unsigned overflow
;   clobbers r1, r4-r8 and the condition flags
;   preserves r0, r2, r3, r9-r15
;
; Result on success:
;   out[0] = x[0]
;   out[i] = out[i-1] + x[i]        for i = 1..255, in increasing i
;
; Exactly one ADD is executed per defined output word after the seed. The
; carry test is the unsigned comparison sum < out[i-1], so a sum that wraps
; modulo 2^32 is detected rather than published.
;
; Overflow convention:
;   Let i be the first index in 1..255 whose exact sum exceeds UINT32_MAX.
;   On that event out[0..i-1] are the exact prefix sums already committed,
;   out[i..255] are filled with the canonical marker 0xFFFFFFFF, no further
;   input word is read, and the routine returns r1=0. Thus every one of the
;   256 output words is deterministic in both outcomes. The marker is a
;   sentinel only; r1 is the authoritative status because a legitimate prefix
;   sum can also equal 0xFFFFFFFF.
;
; Exact output aliasing with x is safe: x[i] is loaded before out[i] is
; stored, and out[i-1] is exactly the prefix state needed by the recurrence.
; On overflow with out==x, the prefix and marker stores overwrite x[0..255].
; Partial overlap between x and out is not safe. No span, length, alignment,
; or alias validation is performed; those are caller preconditions.

mth_vector_prefix_sum256_u32:
  LD r5,r1,0                 ; acc = x[0]
  ST r5,r2,0                 ; out[0] = acc
  MOVI r4,1                  ; i = 1
mth_vector_prefix_sum256_u32_loop:
  ADD r6,r1,r4
  LD r6,r6,0                 ; x[i] (read before any store to out[i])
  ADD r7,r5,r6               ; sum = acc + x[i]
  CMP r7,r5
  JMP[LT] @mth_vector_prefix_sum256_u32_overflow
  ADD r8,r2,r4
  ST r7,r8,0                 ; out[i] = sum
  ADD r5,r7,r0               ; acc = sum
  ADD r4,r4,r13
  MOVI r8,256
  CMP r4,r8
  JMP[LT] @mth_vector_prefix_sum256_u32_loop
  MOVI r1,1
  RET

; r4 is the first overflowing index. Fill out[i..255] with UINT32_MAX.
mth_vector_prefix_sum256_u32_overflow:
  MOVI r8,0xFFFF
  MOVHI r8,0xFFFF            ; marker = 0xFFFFFFFF
mth_vector_prefix_sum256_u32_mark:
  ADD r6,r2,r4
  ST r8,r6,0
  ADD r4,r4,r13
  MOVI r7,256
  CMP r4,r7
  JMP[LT] @mth_vector_prefix_sum256_u32_mark
  MOVI r1,0
  RET
