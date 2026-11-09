; MTH 256-element float32 reciprocal square root — NaN16 only.
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
;   out[i] = rsqrt_approx(x[i]) = 1 / sqrt(x[i])
;
; DOMAIN AND FAIL-CLOSED POLICY:
;   A complete 256-word preflight runs before the first output store.
;   Accepted payloads are finite float32 values with a clear sign bit and a
;   nonzero magnitude. Both +0.0 and -0.0 are rejected, as are all finite
;   negative values. Negative infinity and every NaN are rejected by the
;   non-finite test. Positive subnormals are accepted: they are scaled by
;   2^24 inside the kernel and the result is scaled by 2^12.
;   Non-finite payloads (NaN, +inf, -inf) reject with cause 1. Finite
;   payloads with the sign bit set or with magnitude zero reject with
;   cause 2. The non-finite test runs first, so -inf is cause 1.
;   On rejection out[0..255] is left untouched: no status word and no
;   marker are written.
;
; STATUS CONVENTION:
;   success: r1 = 1, r9 = 0, out[0..255] = approximations.
;   failure: r1 = 0, r9 = 1 (non-finite input) or r9 = 2 (non-positive
;            finite input), out[0..255] unchanged. A caller must test r1
;            before consuming out[].
;
; APPROXIMATION (deterministic, in-guest, NaN16 instructions only):
;   For a normal positive x:
;     y0 = reinterpret(0x5F3759DF - (bits(x) >> 1))
;     t  = ((x * y_n) * y_n) * 0.5
;     y_{n+1} = y_n * (1.5 - t)                    four times
;   The integer bit-hack estimate is the classic float32 reciprocal-square-
;   root seed with relative error below about 3.5% over the normal range.
;   The Newton step is quadratically convergent, so the relative error
;   after the second step is below about 2e-6 and after the third step below
;   1e-11; four steps leave float32 rounding as the dominant error. The
;   product is grouped as (x*y)*y so an intermediate y*y cannot overflow
;   for the largest finite input or the smallest positive subnormal.
;
;   The result is a deterministic approximation, not a correctly rounded
;   IEEE reciprocal square root.
;
;   Subnormal positive x is first multiplied by the exact power of two
;   2^24 (0x4B800000). The same Newton core is run, then the result is
;   multiplied by the exact power of two 2^12 (0x45800000), because
;   rsqrt(x * 2^24) = rsqrt(x) * 2^-12.
;
; TOLERANCE:
;   The companion fixture compares generated results with generated
;   references (perfect-square inputs against an in-guest FDIV reciprocal,
;   powers of two, min subnormal, FLT_MAX) using an unsigned 32-bit payload
;   distance of at most 32 ulps. This is a test bound, not a formal error
;   proof. No host math, no lookup table, no FSQRT, and no CALL are used.
;
; Alias: exact out == x is safe because x[i] is loaded before out[i] is
; stored. Partial overlap is not safe. The output span must be writable for
; 256 words; there is no length or alignment validation.

mth_vector_rsqrt256_f32:
  ; ---- Preflight: reject non-finite then non-positive before touching out[].
  MOVI r3,0
  MOVI r4,0
  MOVHI r4,0x7F80            ; r4 = 0x7F800000 exponent mask
mth_vrsqrt256_preflight:
  ADD r5,r1,r3
  LD r6,r5,0
  BOOL.8 r7,r6,r4            ; exponent bits of x[i]
  CMP r7,r4
  JMP[EQ] @mth_vrsqrt256_nonfinite
  SHR r7,r6,31               ; sign bit
  CMP r7,r0
  JMP[NE] @mth_vrsqrt256_nonpositive
  CMP r6,r0                  ; +0.0 is non-positive
  JMP[EQ] @mth_vrsqrt256_nonpositive
  ADD r3,r3,r13
  MOVI r5,256
  CMP r3,r5
  JMP[LT] @mth_vrsqrt256_preflight

  ; ---- Constants for the Newton core.
  MOVI r11,0
  MOVHI r11,0x3F00           ; r11 = 0.5
  MOVI r12,0
  MOVHI r12,0x3FC0           ; r12 = 1.5
  MOVI r8,0x59DF
  MOVHI r8,0x5F37            ; r8 = 0x5F3759DF rsqrt bit-hack magic

  MOVI r3,0                  ; i = 0
mth_vrsqrt256_loop:
  ADD r5,r1,r3
  LD r6,r5,0                 ; x[i]
  MOVI r10,0                 ; scaled = 0
  BOOL.8 r7,r6,r4            ; exponent bits of x[i]
  CMP r7,r0
  JMP[NE] @mth_vrsqrt256_estimate

  ; Positive subnormal: x = x * 2^24, exact power-of-two scaling.
  MOVI r7,0
  MOVHI r7,0x4B80            ; r7 = 2^24
  FMUL r6,r6,r7
  MOVI r10,1                 ; remember to scale the result back

mth_vrsqrt256_estimate:
  SHR r7,r6,1
  SUB r7,r8,r7               ; y0 = magic - (bits(x) >> 1)

  ; Four Newton steps: y = y * (1.5 - 0.5 * (x*y)*y).
  FMUL r9,r6,r7
  FMUL r9,r9,r7
  FMUL r9,r9,r11
  FSUB r9,r12,r9
  FMUL r7,r7,r9
  FMUL r9,r6,r7
  FMUL r9,r9,r7
  FMUL r9,r9,r11
  FSUB r9,r12,r9
  FMUL r7,r7,r9
  FMUL r9,r6,r7
  FMUL r9,r9,r7
  FMUL r9,r9,r11
  FSUB r9,r12,r9
  FMUL r7,r7,r9
  FMUL r9,r6,r7
  FMUL r9,r9,r7
  FMUL r9,r9,r11
  FSUB r9,r12,r9
  FMUL r7,r7,r9

  CMP r10,r0
  JMP[EQ] @mth_vrsqrt256_store
  MOVI r9,0
  MOVHI r9,0x4580            ; r9 = 2^12
  FMUL r7,r7,r9

mth_vrsqrt256_store:
  ADD r5,r2,r3
  ST r7,r5,0
  ADD r3,r3,r13
  MOVI r5,256
  CMP r3,r5
  JMP[LT] @mth_vrsqrt256_loop

  MOVI r9,0                  ; success has no failure cause
  MOVI r1,1
  RET

mth_vrsqrt256_nonfinite:
  MOVI r9,1
  MOVI r1,0
  RET

mth_vrsqrt256_nonpositive:
  MOVI r9,2
  MOVI r1,0
  RET
