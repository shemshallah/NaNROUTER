; MTH 256-element float32 square root — NaN16 only.
;
; ABI:
;   r1  = x, 256 float32 payloads (read-only)
;   r2  = out, 256 float32 payloads
;   r13 = 1
;   returns r1 = 1 on success, r1 = 0 on rejection
;   on success r9 = 0; on rejection r9 = cause code
;   clobbers r1, r3-r12 and the flags
;   preserves r0, r2, r13-r15
;
; Result on success:
;   out[i] = sqrt_approx(x[i])
;
; DOMAIN AND FAIL-CLOSED POLICY:
;   A complete 256-word preflight runs before the first output store.
;   Accepted payloads are finite float32 values whose sign bit is clear.
;     * +0.0 (0x00000000) is accepted and maps exactly to +0.0.
;     * Positive subnormals are accepted; they are scaled by 2^24 inside the
;       kernel and the result is scaled back by 2^-12, so the subnormal
;       input is never used as a Newton denominator directly.
;     * -0.0 (0x80000000) is rejected: the declared domain is payloads with
;       a clear sign bit, so the signed zero is outside it.
;   Non-finite payloads (NaN, +inf, -inf) reject with cause 1. Finite
;   payloads with the sign bit set reject with cause 2. The non-finite test
;   runs first, so -inf is cause 1, not cause 2. On rejection out[0..255] is
;   left untouched: no status word and no marker are written.
;
; STATUS CONVENTION:
;   success: r1 = 1, r9 = 0, out[0..255] = approximations.
;   failure: r1 = 0, r9 = 1 (non-finite input) or r9 = 2 (negative input),
;            out[0..255] unchanged. A caller must test r1 before consuming
;            out[].
;
; APPROXIMATION (deterministic, in-guest, NaN16 instructions only):
;   For a normal positive x:
;     y0 = reinterpret((bits(x) >> 1) + 0x1FBD1DF5)
;     y_{n+1} = 0.5 * (y_n + x / y_n)              four times
;   The integer bit-hack estimate has relative error below 3.5% over the
;   normal range. The Newton step is quadratically convergent, so the
;   relative error after the second step is below about 2e-6 and after the
;   third step below 1e-11; four steps leave float32 rounding as the
;   dominant error. The result is therefore a deterministic approximation,
;   not a correctly rounded IEEE sqrt.
;
;   Subnormal positive x is first multiplied by the exact power of two
;   2^24 (0x4B800000). The same Newton core is run, then the result is
;   multiplied by the exact power of two 2^-12 (0x39800000). Multiplication
;   by a power of two is exact in the normal range, so this only adds the
;   final rounding of sqrt(x * 2^24).
;
; TOLERANCE:
;   The companion fixture compares generated results with generated exact
;   expectations (perfect squares, powers of two, min subnormal, FLT_MAX)
;   using an unsigned 32-bit payload distance of at most 32 ulps. This is a
;   test bound, not a formal error proof. No host math, no lookup table, no
;   FSQRT, and no CALL are used.
;
; Alias: exact out == x is safe because x[i] is loaded before out[i] is
; stored. Partial overlap is not safe. The output span must be writable for
; 256 words; there is no length or alignment validation.

mth_vector_sqrt256_f32:
  ; ---- Preflight: reject non-finite then negative before touching out[].
  MOVI r3,0
  MOVI r4,0
  MOVHI r4,0x7F80            ; r4 = 0x7F800000 exponent mask
mth_vsqrt256_preflight:
  ADD r5,r1,r3
  LD r6,r5,0
  BOOL.8 r7,r6,r4            ; exponent bits of x[i]
  CMP r7,r4
  JMP[EQ] @mth_vsqrt256_nonfinite
  SHR r7,r6,31               ; sign bit
  CMP r7,r0
  JMP[NE] @mth_vsqrt256_negative
  ADD r3,r3,r13
  MOVI r5,256
  CMP r3,r5
  JMP[LT] @mth_vsqrt256_preflight

  ; ---- Constants for the Newton core.
  MOVI r11,0
  MOVHI r11,0x3F00           ; r11 = 0.5
  MOVI r12,0x1DF5
  MOVHI r12,0x1FBD           ; r12 = 0x1FBD1DF5 sqrt bit-hack bias

  MOVI r3,0                  ; i = 0
mth_vsqrt256_loop:
  ADD r5,r1,r3
  LD r6,r5,0                 ; x[i]
  CMP r6,r0
  JMP[EQ] @mth_vsqrt256_store_zero

  MOVI r10,0                 ; scaled = 0
  BOOL.8 r7,r6,r4            ; exponent bits of x[i]
  CMP r7,r0
  JMP[NE] @mth_vsqrt256_estimate

  ; Positive subnormal: x = x * 2^24, exact power-of-two scaling.
  MOVI r8,0
  MOVHI r8,0x4B80            ; r8 = 2^24
  FMUL r6,r6,r8
  MOVI r10,1                 ; remember to scale the result back

mth_vsqrt256_estimate:
  SHR r7,r6,1
  ADD r7,r7,r12              ; y0 = (bits(x) >> 1) + bias

  ; Four Newton steps: y = 0.5 * (y + x/y).
  FDIV r8,r6,r7
  FADD r8,r7,r8
  FMUL r7,r8,r11
  FDIV r8,r6,r7
  FADD r8,r7,r8
  FMUL r7,r8,r11
  FDIV r8,r6,r7
  FADD r8,r7,r8
  FMUL r7,r8,r11
  FDIV r8,r6,r7
  FADD r8,r7,r8
  FMUL r7,r8,r11

  CMP r10,r0
  JMP[EQ] @mth_vsqrt256_store
  MOVI r8,0
  MOVHI r8,0x3980            ; r8 = 2^-12
  FMUL r7,r7,r8

  JMP @mth_vsqrt256_store

mth_vsqrt256_store_zero:
  MOVI r7,0                  ; sqrt(+0.0) = +0.0
mth_vsqrt256_store:
  ADD r5,r2,r3
  ST r7,r5,0
  ADD r3,r3,r13
  MOVI r5,256
  CMP r3,r5
  JMP[LT] @mth_vsqrt256_loop

  MOVI r9,0                  ; success has no failure cause
  MOVI r1,1
  RET

mth_vsqrt256_nonfinite:
  MOVI r9,1
  MOVI r1,0
  RET

mth_vsqrt256_negative:
  MOVI r9,2
  MOVI r1,0
  RET
