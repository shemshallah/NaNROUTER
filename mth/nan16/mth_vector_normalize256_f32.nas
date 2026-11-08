; MTH 256-element float32 vector normalization — NaN16 only.
;
; ABI:
;   r1  = x, 256 float32 payloads (read-only)
;   r2  = out, 256 float32 payloads
;   r13 = 1
;   returns r1 = 1 on success, r1 = 0 on rejection
;   on rejection r9 = cause code and out[] holds marker/status words
;   clobbers r1, r3-r11 and the flags
;   preserves r0, r2, r12-r15
;
; Result on success:
;   sum = ((((0.0 + x[0]) + x[1]) + ...) + x[255])
;   out[i] = x[i] / sum
;
; The sum is exactly one increasing-order FADD pass. Division is exactly one
; increasing-order FDIV per element. There is no reordering, no pairwise sum,
; no fused multiply-add, and no reciprocal-multiply substitution. The
; sequential sum is the divisor; this is not a correctly rounded exact
; normalization.
;
; STATUS CONVENTION:
;   success: r1 = 1, r9 = 0, out[0..255] = quotients.
;   failure: r1 = 0, r9 = cause, out[0] = status word,
;            out[1..255] = 0xFFC0DEAD (canonical marker).
;   cause 1: non-finite input (NaN, +inf, or -inf)
;            status = 0xFFC0DEAD
;   cause 2: zero sum (+0.0 or -0.0)
;            status = 0xFFC0DEAE
;   cause 3: non-finite sum (overflow to +inf or -inf; NaN is unreachable
;            after the input rejection)
;            status = 0xFFC0DEAF
;   cause 4: non-finite quotient (division overflow to +inf or -inf)
;            status = 0xFFC0DEB0
;   The status in out[0] is 0xFFC0DEAC + cause. Every failure word is a
;   diagnostic quiet-NaN-class payload, never an arithmetic result. A caller
;   must check r1 before consuming out[].
;
; DOMAIN AND FAIL-CLOSED POLICY:
;   Every input element must be finite. A preflight inside the increasing sum
;   pass tests (payload & 0x7F800000) == 0x7F800000, which is exactly the
;   binary32 exponent-all-ones class (NaN and both infinities). The first such
;   element rejects the call before any output store, so a NaN or infinity is
;   never propagated into a result.
;
;   Signed zero is a valid input. A zero sum (all-zero input, or cancelation to
;   exactly +0 or -0) is rejected; the kernel never divides by zero. On
;   success, x[i] = +0 or -0 divided by a nonzero finite sum produces the IEEE
;   signed zero selected by sign XOR.
;
;   Overflow is fail-closed. If the increasing sum overflows to +inf or -inf,
;   the call is rejected with cause 3. If any quotient overflows to +inf or
;   -inf, the call is rejected with cause 4, and any earlier quotient stores
;   are overwritten by the failure marker. There is no saturation to the
;   largest finite value. Underflow to subnormal or zero is allowed.
;
;   FADD (sum) and FDIV (quotient) use IEEE binary32 round-to-nearest,
;   ties-to-even, with no flush-to-zero and no denormals-are-zero. Subnormal
;   inputs, sums, and quotients are preserved. The declared rounding is RNE
;   with no FTZ/DAZ.
;
; Alias: exact out == x is safe because each x[i] is loaded before its result
; is stored at the same index. Partial overlap of out with x is not safe. The
; output span must be writable for 256 words; there is no length or alignment
; validation.

mth_vector_normalize256_f32:
  MOVI r3,0                  ; sum = +0.0
  MOVI r4,0
  MOVHI r4,0x7F80            ; r4 = 0x7F800000 exponent mask
  MOVI r5,0                  ; i = 0
mth_vnorm256_sum_loop:
  ADD r6,r1,r5
  LD r7,r6,0                 ; x[i]
  BOOL.8 r8,r7,r4            ; exponent bits of x[i]
  CMP r8,r4
  JMP[EQ] @mth_vnorm256_nonfinite_input
  FADD r3,r3,r7              ; one increasing-order sum step
  ADD r5,r5,r13
  MOVI r6,256
  CMP r5,r6
  JMP[LT] @mth_vnorm256_sum_loop

  ; Validate the completed sum before any quotient is stored.
  BOOL.8 r8,r3,r4            ; exponent bits of sum
  CMP r8,r4
  JMP[EQ] @mth_vnorm256_nonfinite_sum
  SHL r8,r3,1                ; discard sign; zero only for +0 or -0
  CMP r8,r0
  JMP[EQ] @mth_vnorm256_zero_sum

  MOVI r5,0                  ; i = 0
mth_vnorm256_div_loop:
  ADD r6,r1,r5
  LD r7,r6,0                 ; x[i]
  FDIV r7,r7,r3              ; one increasing-order quotient
  BOOL.8 r8,r7,r4            ; exponent bits of quotient
  CMP r8,r4
  JMP[EQ] @mth_vnorm256_nonfinite_quotient
  ADD r6,r2,r5
  ST r7,r6,0
  ADD r5,r5,r13
  MOVI r6,256
  CMP r5,r6
  JMP[LT] @mth_vnorm256_div_loop

  MOVI r9,0                  ; success has no failure cause
  MOVI r1,1
  RET

mth_vnorm256_nonfinite_input:
  MOVI r9,1
  JMP @mth_vnorm256_fail
mth_vnorm256_zero_sum:
  MOVI r9,2
  JMP @mth_vnorm256_fail
mth_vnorm256_nonfinite_sum:
  MOVI r9,3
  JMP @mth_vnorm256_fail
mth_vnorm256_nonfinite_quotient:
  MOVI r9,4
  JMP @mth_vnorm256_fail

mth_vnorm256_fail:
  MOVI r10,0xDEAC
  MOVHI r10,0xFFC0           ; r10 = 0xFFC0DEAC status base
  ADD r10,r10,r9             ; status = 0xFFC0DEAC + cause
  ST r10,r2,0                ; out[0] = status
  MOVI r11,0xDEAD
  MOVHI r11,0xFFC0           ; r11 = 0xFFC0DEAD marker
  MOVI r5,1
mth_vnorm256_fail_fill:
  ADD r6,r2,r5
  ST r11,r6,0
  ADD r5,r5,r13
  MOVI r6,256
  CMP r5,r6
  JMP[LT] @mth_vnorm256_fail_fill
  MOVI r1,0
  RET
