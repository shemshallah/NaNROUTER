; MTH 256-element float32 stable softmax — NaN16 only.
;
; ABI:
;   r1  = x, 256 float32 payloads (read-only)
;   r2  = out, 256 float32 payloads
;   r13 = 1
;   returns r1 = 1 on success, r1 = 0 on rejection
;   on success r9 = 0; on rejection r9 = cause code
;   clobbers r1, r3-r12, r14 and the flags
;   preserves r0, r2, r13, r15
;
; Result on success:
;   m      = max over the finite input elements
;   d[i]   = x[i] - m                      (finite elements)
;   e[i]   = approx_exp(d[i])              (0 when d[i] < -20)
;   S      = ((((0.0 + e[0]) + e[1]) + ...) + e[255])
;   out[i] = e[i] / S
;
; The maximum is subtracted before exponentiation, so the largest exponent
; argument is exactly 0 and no term can overflow. The sum S is always
; positive: at least one finite element has d = 0 and e = 1.
;
; INPUT DOMAIN AND FAIL-CLOSED POLICY:
;   A full preflight over all 256 words runs before any output store.
;   A payload in the binary32 exponent-all-ones class is accepted only when
;   it is exactly -inf (0xFF800000). NaN and +inf reject the call.
;   -inf is a legal "empty position": it is excluded from the maximum and
;   its output is exactly +0.0.
;   If every element is -inf there is no finite maximum and the support is
;   empty; that case is rejected rather than dividing by zero.
;
; STATUS CONVENTION:
;   success: r1 = 1, r9 = 0, out[0..255] = normalized exponentials.
;   failure: r1 = 0, r9 = cause, out[0..255] are left untouched.
;   cause 1: NaN or +inf input.
;   cause 2: empty support, meaning all 256 inputs are -inf.
;   The kernel never publishes partial output on failure. A caller must test
;   r1 before consuming out[].
;
; EXP APPROXIMATION (deterministic, in-guest, NaN16 instructions only):
;   For d >= -20:
;     n = CVTFI(d * log2(e))                 ; truncation toward zero
;     r = d - CVTIF(n) * ln(2)               ; r in (-ln2, 0]
;                                                  for d <= 0
;     p(r) = c7*r^7 + c6*r^6 + ... + c0      ; c_k = 1/k!, Horner order
;     e = p(r) * 2^n                         ; 2^n built as exponent bits
;   For d < -20 the term is set to +0.0. Its true exp(d) is below 2.061e-9,
;   so all 256 discarded tails together are below 5.3e-7.
;
;   The degree-7 Taylor remainder on |r| <= ln2 is at most
;   ln2^8 / 8! = 1.33e-6 absolute; for exp(r) >= 0.5 that is at most
;   2.7e-6 relative. The range-reduction multiply/subtract and the final
;   float32 rounding add a few ulps. The fixture's integer payload check
;   requires the increasing-order output sum to lie in
;   [1 - 2^-12, 1 + 2^-12], a conservative bound for that error.
;
; No host math, no lookup table, no static storage, and no CALL. Exact
; out == x aliasing is safe because each x[i] is consumed before out[i] is
; stored and the maximum scan is complete. Partial overlap is not safe.

mth_vector_softmax256_f32:
  ; ---- Preflight: reject NaN and +inf before touching out[].
  MOVI r5,0
  MOVHI r5,0x7F80            ; r5 = 0x7F800000 exponent mask
  MOVI r4,0
  MOVHI r4,0xFF80            ; r4 = 0xFF800000, the only accepted -inf
  MOVI r6,0                  ; i = 0
mth_vsm256_preflight:
  ADD r7,r1,r6
  LD r7,r7,0
  BOOL.8 r8,r7,r5            ; exponent bits only
  CMP r8,r5
  JMP[NE] @mth_vsm256_preflight_next
  CMP r7,r4                  ; exponent-all-ones: allow only exact -inf
  JMP[NE] @mth_vsm256_invalid
mth_vsm256_preflight_next:
  ADD r6,r6,r13
  MOVI r8,256
  CMP r6,r8
  JMP[LT] @mth_vsm256_preflight

  ; ---- Maximum over finite elements. Seeding with -inf also detects the
  ; ---- empty-support case: if the running maximum stays -inf, every
  ; ---- input was -inf.
  ADD r3,r4,r0               ; best = -inf
  MOVI r6,0                  ; i = 0
mth_vsm256_max_loop:
  ADD r7,r1,r6
  LD r8,r7,0
  FCMP r8,r3
  JMP[LE] @mth_vsm256_max_next
  ADD r3,r8,r0               ; best = candidate
mth_vsm256_max_next:
  ADD r6,r6,r13
  MOVI r7,256
  CMP r6,r7
  JMP[LT] @mth_vsm256_max_loop
  CMP r3,r4
  JMP[EQ] @mth_vsm256_empty

  ; ---- Exponentials and the increasing-order sum.
  MOVI r4,0                  ; sum = +0.0
  MOVI r7,0xAA3B
  MOVHI r7,0x3FB8            ; log2(e) = 0x3FB8AA3B
  MOVI r8,0x7218
  MOVHI r8,0x3F31            ; ln(2)   = 0x3F317218
  MOVI r9,0
  MOVHI r9,0xC1A0            ; -20.0   = 0xC1A00000
  MOVI r6,0                  ; i = 0
mth_vsm256_exp_loop:
  ADD r14,r1,r6
  LD r10,r14,0               ; x[i]
  FSUB r10,r10,r3            ; d = x[i] - max
  FCMP r10,r9
  JMP[LT] @mth_vsm256_store_zero

  ; n = trunc(d * log2(e)); r = d - n*ln(2)
  FMUL r11,r10,r7
  CVTFI r11,r11
  CVTIF r5,r11
  FMUL r5,r5,r8
  FSUB r10,r10,r5            ; r in (-ln2, 0]

  ; p = c7
  MOVI r12,0x0D01
  MOVHI r12,0x3950           ; 1/5040 = 0x39500D01
  ; p = p*r + c6
  MOVI r5,0x0B61
  MOVHI r5,0x3AB6            ; 1/720  = 0x3AB60B61
  FMUL r12,r12,r10
  FADD r12,r12,r5
  ; p = p*r + c5
  MOVI r5,0x8889
  MOVHI r5,0x3C08            ; 1/120  = 0x3C088889
  FMUL r12,r12,r10
  FADD r12,r12,r5
  ; p = p*r + c4
  MOVI r5,0xAAAB
  MOVHI r5,0x3D2A            ; 1/24   = 0x3D2AAAAB
  FMUL r12,r12,r10
  FADD r12,r12,r5
  ; p = p*r + c3
  MOVI r5,0xAAAB
  MOVHI r5,0x3E2A            ; 1/6    = 0x3E2AAAAB
  FMUL r12,r12,r10
  FADD r12,r12,r5
  ; p = p*r + c2
  MOVI r5,0
  MOVHI r5,0x3F00            ; 1/2    = 0x3F000000
  FMUL r12,r12,r10
  FADD r12,r12,r5
  ; p = p*r + c1
  MOVI r5,0
  MOVHI r5,0x3F80            ; 1.0    = 0x3F800000
  FMUL r12,r12,r10
  FADD r12,r12,r5
  ; p = p*r + c0 (r5 is still 1.0)
  FMUL r12,r12,r10
  FADD r12,r12,r5

  ; Scale by 2^n. n is in [-29, 0] here, so n+127 is a valid exponent.
  MOVI r5,127
  ADD r5,r11,r5
  SHL r5,r5,23
  FMUL r12,r12,r5

  FADD r4,r4,r12             ; sum += e[i]
  ADD r14,r2,r6
  ST r12,r14,0               ; out[i] = e[i]
  JMP @mth_vsm256_exp_next

mth_vsm256_store_zero:
  ADD r14,r2,r6
  ST r0,r14,0                ; tail below -20 contributes +0.0

mth_vsm256_exp_next:
  ADD r6,r6,r13
  MOVI r5,256
  CMP r6,r5
  JMP[LT] @mth_vsm256_exp_loop

  ; ---- Normalize in place. S >= 1, so this cannot divide by zero.
  MOVI r6,0                  ; i = 0
mth_vsm256_div_loop:
  ADD r14,r2,r6
  LD r10,r14,0
  FDIV r10,r10,r4
  ST r10,r14,0
  ADD r6,r6,r13
  MOVI r5,256
  CMP r6,r5
  JMP[LT] @mth_vsm256_div_loop

  MOVI r9,0                  ; success has no failure cause
  MOVI r1,1
  RET

mth_vsm256_invalid:
  MOVI r9,1
  MOVI r1,0
  RET

mth_vsm256_empty:
  MOVI r9,2
  MOVI r1,0
  RET
