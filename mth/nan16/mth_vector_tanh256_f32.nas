; MTH 256-element float32 tanh — NaN16 only.
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
;   a      = |x[i]|
;   e      = approx_exp(-2*a)             (exactly 0 when a >= 10)
;   t      = (1 - e) / (1 + e)            (t >= 0, t <= 1)
;   out[i] = t          when x[i] >= 0
;   out[i] = -t         when x[i] <  0
;
; INPUT DOMAIN AND FAIL-CLOSED POLICY:
;   Every finite binary32 payload is accepted. A payload in the
;   exponent-all-ones class (NaN, +inf, -inf) rejects the whole call.
;   A full preflight over all 256 words runs before any output store, so
;   rejection is atomic: out[0..255] are left untouched.
;
; STATUS CONVENTION:
;   success: r1 = 1, r9 = 0, out[0..255] = tanh approximations in [-1,1].
;   failure: r1 = 0, r9 = 1, out[0..255] are left untouched.
;   cause 1: NaN or infinity in x.
;   A caller must test r1 before consuming out[].
;
; SATURATION:
;   For a >= 10 the exponent argument is below the representable tanh
;   tail, so e is set to exactly +0.0. Hence x >= 10 stores exactly +1.0
;   and x <= -10 stores exactly -1.0. The clipped tail error is at most
;   1 - tanh(10) = 4.1358e-9.
;
; APPROXIMATION (deterministic, in-guest, NaN16 instructions only):
;   For 0 <= a < 10, with L = log2(e) and ln2 = ln(2):
;     n = CVTFI(2*a * L)                     ; truncation toward zero, 0..28
;     r = CVTIF(n) * ln2 - 2*a               ; r in (-ln2, 0]
;     p(r) = c7*r^7 + c6*r^6 + ... + c0      ; c_k = 1/k!, Horner order
;     e = p(r) * 2^-n                        ; 2^-n built as exponent bits
;   The degree-7 Taylor remainder on |r| <= ln2 is below 1.4e-6 absolute,
;   about 3e-6 relative to exp(r) >= 0.5, and the float32 range reduction
;   adds a few ulps. tanh = (1-e)/(1+e) has |d tanh/de| <= 2, while the
;   absolute error of e is proportional to e; the unclipped absolute error
;   is therefore below 1.6e-6.
;
; DECLARED TOLERANCE:
;   |out[i] - tanh(x[i])| <= 2^-17 = 7.6294e-6 for every finite input,
;   including the saturation tails above. Applying the sign after the
;   magnitude computation makes out(-x) == -out(x) bit-exact, including
;   the signed-zero cases.
;
; No host math, no lookup table, no static storage, and no CALL. Exact
; out == x aliasing is safe because each x[i] is consumed before out[i] is
; stored; partial overlap is not safe.

mth_vector_tanh256_f32:
  ; ---- Preflight: reject every NaN and infinity before touching out[].
  MOVI r5,0
  MOVHI r5,0x7F80            ; r5 = 0x7F800000 exponent mask
  MOVI r6,0                  ; i = 0
mth_vtanh256_preflight:
  ADD r7,r1,r6
  LD r7,r7,0
  BOOL.8 r8,r7,r5            ; exponent bits only
  CMP r8,r5
  JMP[NE] @mth_vtanh256_preflight_next
  JMP @mth_vtanh256_invalid
mth_vtanh256_preflight_next:
  ADD r6,r6,r13
  MOVI r8,256
  CMP r6,r8
  JMP[LT] @mth_vtanh256_preflight

  MOVI r5,0xFFFF
  MOVHI r5,0x7FFF            ; r5 = 0x7FFFFFFF, clear-sign mask
  MOVI r7,0xAA3B
  MOVHI r7,0x3FB8            ; log2(e) = 0x3FB8AA3B
  MOVI r8,0x7218
  MOVHI r8,0x3F31            ; ln(2)   = 0x3F317218
  MOVI r9,0
  MOVHI r9,0x4120            ; 10.0    = 0x41200000
  MOVI r6,0                  ; i = 0
mth_vtanh256_loop:
  ADD r10,r1,r6
  LD r10,r10,0               ; x[i]
  SHR r11,r10,31             ; sign = 0 for x >= 0, 1 for x < 0
  BOOL.8 r10,r10,r5          ; a = |x[i]| (AND clears only the sign bit)
  FCMP r10,r9
  JMP[GE] @mth_vtanh256_zero_e ; a >= 10 saturates

  ; d = 2*a (exact for a < 10).
  FADD r10,r10,r10
  ; n = trunc(d * log2(e)); r = n*ln2 - d in (-ln2, 0].
  FMUL r3,r10,r7
  CVTFI r3,r3
  CVTIF r12,r3
  FMUL r12,r12,r8
  FSUB r4,r12,r10

  ; p = c7
  MOVI r14,0x0D01
  MOVHI r14,0x3950           ; 1/5040 = 0x39500D01
  ; p = p*r + c6
  MOVI r12,0x0B61
  MOVHI r12,0x3AB6           ; 1/720  = 0x3AB60B61
  FMUL r14,r14,r4
  FADD r14,r14,r12
  ; p = p*r + c5
  MOVI r12,0x8889
  MOVHI r12,0x3C08           ; 1/120  = 0x3C088889
  FMUL r14,r14,r4
  FADD r14,r14,r12
  ; p = p*r + c4
  MOVI r12,0xAAAB
  MOVHI r12,0x3D2A           ; 1/24   = 0x3D2AAAAB
  FMUL r14,r14,r4
  FADD r14,r14,r12
  ; p = p*r + c3
  MOVI r12,0xAAAB
  MOVHI r12,0x3E2A           ; 1/6    = 0x3E2AAAAB
  FMUL r14,r14,r4
  FADD r14,r14,r12
  ; p = p*r + c2
  MOVI r12,0
  MOVHI r12,0x3F00           ; 1/2    = 0x3F000000
  FMUL r14,r14,r4
  FADD r14,r14,r12
  ; p = p*r + c1
  MOVI r12,0
  MOVHI r12,0x3F80           ; 1.0    = 0x3F800000
  FMUL r14,r14,r4
  FADD r14,r14,r12
  ; p = p*r + c0 (r12 is still 1.0)
  FMUL r14,r14,r4
  FADD r14,r14,r12

  ; Scale by 2^-n; n is in [0,28], so 127-n is a valid exponent.
  MOVI r12,127
  SUB r12,r12,r3
  SHL r12,r12,23
  FMUL r14,r14,r12           ; e = approx_exp(-2*a)
  JMP @mth_vtanh256_ratio

mth_vtanh256_zero_e:
  MOVI r14,0                 ; e = +0.0 for the saturated tail

mth_vtanh256_ratio:
  MOVI r3,0
  MOVHI r3,0x3F80            ; 1.0
  FADD r4,r3,r14             ; 1 + e
  FSUB r12,r3,r14            ; 1 - e
  FDIV r14,r12,r4            ; t = (1-e)/(1+e)
  CMP r11,r0
  JMP[EQ] @mth_vtanh256_store
  MOVI r3,0
  MOVHI r3,0x8000            ; 0x80000000
  BOOL.6 r14,r14,r3          ; negative x: exact sign flip, -t

mth_vtanh256_store:
  ADD r4,r2,r6
  ST r14,r4,0
  ADD r6,r6,r13
  MOVI r3,256
  CMP r6,r3
  JMP[LT] @mth_vtanh256_loop

  MOVI r9,0                  ; success has no failure cause
  MOVI r1,1
  RET

mth_vtanh256_invalid:
  MOVI r9,1
  MOVI r1,0
  RET
