; MTH native float32 sine/cosine — NaN16 only.
;
; This is the first trigonometric primitive of the native mathematical layer.
; It is deliberately a leaf routine: no host sin/cos, no lookup table, no
; static scratch, and no CALL. The only arithmetic instructions are FMUL,
; FADD, FSUB, CVTFI and CVTIF on IEEE-754 binary32 payloads.
;
; ABI (r13 = 1):
;   r1 = angle in radians as a raw binary32 payload
;   success: r1 = 1, r2 = sin(angle), r3 = cos(angle)
;   rejection: r1 = 0, r9 = cause; r2 and r3 are unspecified
;     cause 1: angle is NaN, +Inf, or -Inf
;     cause 2: |angle| > 128.0
;
; Domain
; ------
; The reduction uses the binary32 constants 2/pi (0x3F22F983) and pi/2
; (0x3FC90FDB). Restricting |angle| <= 128 keeps the integer quadrant count
; below 82 and keeps the reduction error well below the declared tolerance.
; Larger angles require a caller-side modulo-2*pi reduction or a future
; argument-reduction kernel; they are rejected, never silently wrapped.
;
; Range reduction
; ---------------
;   y = angle * (2/pi)
;   q = trunc(y + 0.5) for y >= 0, trunc(y - 0.5) for y < 0
;   r = angle - q * (pi/2)
;   q4 = q & 3
;
; The rounding step makes |r| <= pi/4, so the polynomials below are evaluated
; on their intended interval. q is a signed integer, and q & 3 is the usual
; two's-complement modulo-4 quadrant for negative counts as well.
;
; Polynomials (Horner in r^2)
; ---------------------------
;   sin(r) = r * (1 + r^2*(-1/6 + r^2*(1/120 + r^2*(-1/5040
;                  + r^2*(1/362880)))))
;   cos(r) = 1 + r^2*(-1/2 + r^2*(1/24 + r^2*(-1/720
;                  + r^2*(1/40320 + r^2*(-1/3628800)))))
;
; The next omitted terms on |r| <= pi/4 are below 2e-9 (sine) and 1.2e-10
; (cosine); binary32 rounding dominates. The declared component tolerance is
; |error| <= 2e-5 for every accepted finite input. The fixture
; checks independent anchor values, quadrant/sign symmetry, domain rejection,
; and sin^2+cos^2.
;
; Quadrant application
; --------------------
;   q4=0: ( sin,  cos) = ( s,  c)
;   q4=1: ( sin,  cos) = ( c, -s)
;   q4=2: ( sin,  cos) = (-s, -c)
;   q4=3: ( sin,  cos) = (-c,  s)
;
; Sign changes are exact XOR operations on the binary32 sign bit; they are not
; floating-point multiplications by -1.
;
; Register effects: r0 is set to 0 and left at 0; r1-r5, r7-r12 and r14 are
; clobbered; r6, r13 and r15 are preserved, so ordinary CALL/RET works and a
; caller can carry one pointer/value in r6 across the call. This kernel
; performs no memory access.

mth_trig_sincos_f32:
  MOVI r0,0

  ; ---- finite preflight ----
  MOVI r4,0
  MOVHI r4,0x7F80             ; 0x7F800000 exponent-all-ones mask
  BOOL.8 r5,r1,r4
  CMP r5,r4
  JMP[EQ] @mth_trig_sincos_nonfinite

  ; ---- domain preflight: |angle| <= 128.0 ----
  MOVI r4,0xFFFF
  MOVHI r4,0x7FFF             ; 0x7FFFFFFF clear-sign mask
  BOOL.8 r5,r1,r4             ; |angle| bit pattern
  MOVI r4,0
  MOVHI r4,0x4300             ; 128.0 = 0x43000000
  FCMP r5,r4
  JMP[GT] @mth_trig_sincos_domain

  ; ---- y = angle * (2/pi) ----
  MOVI r5,0xF983
  MOVHI r5,0x3F22             ; 2/pi = 0x3F22F983
  FMUL r2,r1,r5

  ; ---- q = nearest integer (ties away from zero), then q4 = q & 3 ----
  MOVI r5,0
  MOVHI r5,0x3F00             ; 0.5
  FCMP r2,r0
  JMP[LT] @mth_trig_sincos_nearest_negative
  FADD r2,r2,r5
  JMP @mth_trig_sincos_round
mth_trig_sincos_nearest_negative:
  FSUB r2,r2,r5
mth_trig_sincos_round:
  CVTFI r2,r2                 ; signed quadrant count q
  MOVI r4,3
  BOOL.8 r7,r2,r4             ; q4 = q & 3

  ; ---- r = angle - q*(pi/2) ----
  CVTIF r8,r2
  MOVI r5,0x0FDB
  MOVHI r5,0x3FC9             ; pi/2 = 0x3FC90FDB
  FMUL r8,r8,r5
  FSUB r8,r1,r8               ; reduced angle r, |r| <= pi/4
  FMUL r9,r8,r8               ; r^2

  ; ---- sin(r) Horner ----
  MOVI r10,0xEF1D
  MOVHI r10,0x3638            ; 1/362880 = 0x3638EF1D
  MOVI r5,0x0D01
  MOVHI r5,0xB950             ; -1/5040 = 0xB9500D01
  FMUL r10,r10,r9
  FADD r10,r10,r5
  MOVI r5,0x8889
  MOVHI r5,0x3C08             ; 1/120 = 0x3C088889
  FMUL r10,r10,r9
  FADD r10,r10,r5
  MOVI r5,0xAAAB
  MOVHI r5,0xBE2A             ; -1/6 = 0xBE2AAAAB
  FMUL r10,r10,r9
  FADD r10,r10,r5
  MOVI r5,0
  MOVHI r5,0x3F80             ; 1.0
  FMUL r10,r10,r9
  FADD r10,r10,r5
  FMUL r10,r10,r8             ; s = r * p

  ; ---- cos(r) Horner ----
  MOVI r11,0xF27E
  MOVHI r11,0xB493            ; -1/3628800 = 0xB493F27E
  MOVI r5,0x0D01
  MOVHI r5,0x37D0             ; 1/40320 = 0x37D00D01
  FMUL r11,r11,r9
  FADD r11,r11,r5
  MOVI r5,0x0B61
  MOVHI r5,0xBAB6             ; -1/720 = 0xBAB60B61
  FMUL r11,r11,r9
  FADD r11,r11,r5
  MOVI r5,0xAAAB
  MOVHI r5,0x3D2A             ; 1/24 = 0x3D2AAAAB
  FMUL r11,r11,r9
  FADD r11,r11,r5
  MOVI r5,0
  MOVHI r5,0xBF00             ; -1/2
  FMUL r11,r11,r9
  FADD r11,r11,r5
  MOVI r5,0
  MOVHI r5,0x3F80             ; 1.0
  FMUL r11,r11,r9
  FADD r11,r11,r5             ; c = cos(r)

  ; ---- quadrant application ----
  MOVI r12,0
  MOVHI r12,0x8000            ; binary32 sign bit

  CMP r7,r0
  JMP[EQ] @mth_trig_sincos_q0
  MOVI r5,1
  CMP r7,r5
  JMP[EQ] @mth_trig_sincos_q1
  MOVI r5,2
  CMP r7,r5
  JMP[EQ] @mth_trig_sincos_q2

  ; q4=3: sin = -c, cos = s
  ADD r14,r10,r0              ; save s
  BOOL.6 r10,r11,r12          ; -c
  ADD r11,r14,r0              ; s
  JMP @mth_trig_sincos_publish

mth_trig_sincos_q1:
  ; q4=1: sin = c, cos = -s
  ADD r14,r10,r0              ; save s
  ADD r10,r11,r0              ; c
  BOOL.6 r11,r14,r12          ; -s
  JMP @mth_trig_sincos_publish

mth_trig_sincos_q2:
  ; q4=2: sin = -s, cos = -c
  BOOL.6 r10,r10,r12
  BOOL.6 r11,r11,r12
  JMP @mth_trig_sincos_publish

mth_trig_sincos_q0:
  ; q4=0: no change

mth_trig_sincos_publish:
  ADD r2,r10,r0
  ADD r3,r11,r0
  MOVI r1,1
  RET

mth_trig_sincos_nonfinite:
  MOVI r9,1
  MOVI r1,0
  RET

mth_trig_sincos_domain:
  MOVI r9,2
  MOVI r1,0
  RET
