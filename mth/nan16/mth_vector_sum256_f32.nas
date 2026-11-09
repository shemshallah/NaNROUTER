; MTH 256-element float32 sum — NaN16 only.
;
; ABI:
;   r1  = x, 256 float32 payloads (read-only)
;   r2  = out, one float32 payload (written on success only)
;   r13 = 1
;   returns r1 = 1 on success, r1 = 0 on rejection
;   clobbers r1, r4-r6 and the flags
;   preserves r0, r2, r3, r7-r15
;
; Result:
;   out = ((((0.0 + x[0]) + x[1]) + ...) + x[255])
;
; The accumulator starts at +0.0 and each element is added exactly once in
; increasing i order by one FADD. There is no reordering, pairwise sum,
; compensation, fused multiply-add, or host math. FADD follows the NaN16
; IEEE-754 binary32 round-to-nearest-even rules with no FTZ/DAZ.
;
; DOMAIN AND FAIL-CLOSED POLICY:
;   Every input element must be finite: neither NaN nor +inf nor -inf.
;   A preflight over all 256 words tests
;
;     (payload & 0x7F800000) == 0x7F800000
;
;   which is exactly the binary32 exponent-all-ones class (NaN and both
;   infinities). The first such element rejects the call with r1=0. The whole
;   preflight finishes before the FADD pass and before the output store, so
;   on rejection out is untouched. This is a finite-domain contract and the
;   kernel never performs arithmetic on a non-finite input.
;
; SIGNED ZERO:
;   +0.0 and -0.0 are legal finite inputs. Because the accumulator starts at
;   +0.0, an all-zero input (any mix of zero signs) produces +0.0: IEEE-754
;   FADD gives +0.0 + (-0.0) = +0.0. An exact nonzero cancellation, such as
;   (+1.0) + (-1.0), also produces +0.0. The returned zero sign is therefore
;   the ordinary increasing-order FADD result, not a normalized sign.
;
; OVERFLOW:
;   Finite inputs are not range-limited. If the increasing sum overflows the
;   binary32 range, FADD produces +inf or -inf and that payload is stored.
;   Overflow is output behavior, not an input-domain rejection; callers that
;   require a finite sum must bound their inputs. Underflow to subnormal or
;   zero is preserved.
;
; The output store is the only write. Exact out == x aliasing is safe because
; every input word is read before that store. No static storage, no CALL, and
; no allocation are used.

mth_vector_sum256_f32:
  ; Preflight: reject any non-finite payload before any arithmetic or write.
  MOVI r5,0
  MOVHI r5,0x7F80            ; r5 = 0x7F800000 exponent mask
  MOVI r4,0                  ; i = 0
mth_vector_sum256_preflight:
  ADD r6,r1,r4
  LD r6,r6,0
  BOOL.8 r6,r6,r5            ; exponent bits only
  CMP r6,r5
  JMP[EQ] @mth_vector_sum256_invalid
  ADD r4,r4,r13
  MOVI r6,256
  CMP r4,r6
  JMP[LT] @mth_vector_sum256_preflight

  ; One increasing-order FADD pass from +0.0.
  MOVI r4,0                  ; accumulator = +0.0
  MOVI r5,0                  ; i = 0
mth_vector_sum256_loop:
  ADD r6,r1,r5
  LD r6,r6,0                 ; x[i]
  FADD r4,r4,r6              ; one increasing-order sum step
  ADD r5,r5,r13
  MOVI r6,256
  CMP r5,r6
  JMP[LT] @mth_vector_sum256_loop

  ST r4,r2,0                 ; publish only after the complete pass
  MOVI r1,1
  RET

mth_vector_sum256_invalid:
  MOVI r1,0
  RET
