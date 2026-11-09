; MTH 256-element float32 weighted sum — NaN16 only.
;
; ABI:
;   r1  = x, 256 float32 payloads (read-only)
;   r2  = w, 256 float32 payloads (read-only)
;   r3  = out, one float32 payload
;   r13 = 1
;   returns r1 = 1 on success, r1 = 0 on rejection
;   on rejection r9 = cause code and out = 0xFFC0DEAD marker
;   clobbers r1, r4-r11 and the flags
;   preserves r0, r2, r3, r12-r15
;
; Result on success:
;   acc = +0.0
;   for i = 0..255 in increasing order:
;     p   = FMUL(x[i], w[i])
;     acc = FADD(acc, p)
;   out = acc
;   Exactly one FMUL and one FADD per element. There is no fused
;   multiply-add, no reordering, no pairwise/tree reduction, no reciprocal
;   substitution, and no compensation. FMUL and FADD use IEEE binary32
;   round-to-nearest, ties-to-even, with no flush-to-zero and no
;   denormals-are-zero. Signed zero follows the NaN16 float32 rules. The
;   accumulator starts at +0.0, so an all -0.0 product stream still yields
;   +0.0 (+0.0 + -0.0 = +0.0).
;
; STATUS CONVENTION:
;   success: r1 = 1, r9 = 0, out = the single float32 accumulator payload.
;   failure: r1 = 0, r9 = cause, out = 0xFFC0DEAD marker. No partial sum is
;   stored. A caller must check r1 before consuming out.
;   cause 1: non-finite x element (NaN, +inf, or -inf)
;   cause 2: non-finite w element (NaN, +inf, or -inf)
;   cause 3: non-finite product (overflow to +inf or -inf)
;   cause 4: non-finite accumulator (overflow to +inf or -inf)
;   A NaN product or NaN accumulator is unreachable: the finite-input
;   preflight excludes 0*inf and inf*0, and the accumulator only adds
;   products that were just tested finite.
;
; DOMAIN AND FAIL-CLOSED POLICY:
;   Every x[i] and every w[i] must be finite. A preflight tests
;
;     (payload & 0x7F800000) == 0x7F800000
;
;   over x first and then w, before any FMUL or FADD. A non-finite x element
;   rejects with cause 1 before w is examined; only an all-finite x permits
;   the w preflight, so a call with both arrays bad always reports cause 1.
;   Signed zero is a valid input.
;
;   The kernel is also fail-closed for finite inputs that overflow. After
;   each FMUL the product exponent is tested; a non-finite product rejects
;   with cause 3 before the FADD. After each FADD the accumulator exponent is
;   tested; a non-finite accumulator rejects with cause 4. The call ends at
;   the first offending element, so a rejected call may have executed fewer
;   than 256 product/sum pairs. Underflow to subnormal or zero is allowed and
;   preserved.
;
; Alias: out must not overlap x or w. x and w may be the same span; partial
; overlap between x and w is not required to work. x and w must each hold 256
; readable words and out one writable word; there is no length or alignment
; validation.

mth_vector_weighted_sum256_f32:
  MOVI r4,0
  MOVHI r4,0x7F80            ; r4 = 0x7F800000 exponent mask

  ; Preflight x completely before examining w or doing arithmetic.
  MOVI r10,0
mth_vwsum256_x_preflight:
  ADD r11,r1,r10
  LD r7,r11,0
  BOOL.8 r7,r7,r4            ; exponent bits of x[i]
  CMP r7,r4
  JMP[EQ] @mth_vwsum256_nonfinite_x
  ADD r10,r10,r13
  MOVI r11,256
  CMP r10,r11
  JMP[LT] @mth_vwsum256_x_preflight

  ; Preflight w completely before any FMUL.
  MOVI r10,0
mth_vwsum256_w_preflight:
  ADD r11,r2,r10
  LD r7,r11,0
  BOOL.8 r7,r7,r4            ; exponent bits of w[i]
  CMP r7,r4
  JMP[EQ] @mth_vwsum256_nonfinite_w
  ADD r10,r10,r13
  MOVI r11,256
  CMP r10,r11
  JMP[LT] @mth_vwsum256_w_preflight

  ; One FMUL and one FADD per element, increasing i, with passive fail-closed
  ; exponent checks around them.
  MOVI r5,0                  ; acc = +0.0
  MOVI r10,0
mth_vwsum256_loop:
  ADD r11,r1,r10
  LD r7,r11,0                ; x[i]
  ADD r11,r2,r10
  LD r8,r11,0                ; w[i]
  FMUL r6,r7,r8              ; exactly one product
  BOOL.8 r7,r6,r4
  CMP r7,r4
  JMP[EQ] @mth_vwsum256_nonfinite_product
  FADD r5,r5,r6              ; exactly one increasing-order sum step
  BOOL.8 r7,r5,r4
  CMP r7,r4
  JMP[EQ] @mth_vwsum256_nonfinite_sum
  ADD r10,r10,r13
  MOVI r11,256
  CMP r10,r11
  JMP[LT] @mth_vwsum256_loop

  ST r5,r3,0                 ; single float32 scalar
  MOVI r9,0
  MOVI r1,1
  RET

mth_vwsum256_nonfinite_x:
  MOVI r9,1
  JMP @mth_vwsum256_fail
mth_vwsum256_nonfinite_w:
  MOVI r9,2
  JMP @mth_vwsum256_fail
mth_vwsum256_nonfinite_product:
  MOVI r9,3
  JMP @mth_vwsum256_fail
mth_vwsum256_nonfinite_sum:
  MOVI r9,4
  JMP @mth_vwsum256_fail

mth_vwsum256_fail:
  MOVI r10,0xDEAD
  MOVHI r10,0xFFC0           ; r10 = 0xFFC0DEAD marker
  ST r10,r3,0
  MOVI r1,0
  RET
