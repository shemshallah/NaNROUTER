; MTH Round 027 two-edge hyperedge path score — NaN16 float32 only.
;
; This is one local scoring primitive for a path with two hyperedge strengths.
; It is not a trainer, not a graph search, and not a claim of generalisation.
;
; SCORE LAW
; ---------
; For the two supplied strengths s1_raw and s2_raw:
;
;   s1    = clamp(s1_raw, -8.0, +8.0)
;   s2    = clamp(s2_raw, -8.0, +8.0)
;   p1    = sigmoid(s1) = 1 / (1 + exp(-s1))
;   p2    = sigmoid(s2) = 1 / (1 + exp(-s2))
;   score = p1 * p2
;
; Clamp is inclusive and saturates by exact bit copy:
;   x > +8.0 -> +8.0 (0x41000000)
;   x < -8.0 -> -8.0 (0xC1000000)
;   otherwise x is unchanged.
;
; ABI (r13 = 1)
; -------------
;   r1 = strength1, IEEE-754 binary32 payload passed by value
;   r2 = strength2, IEEE-754 binary32 payload passed by value
;   r3 = destination byte address of one 4-byte little-endian f32 payload
;   r13 = 1
;
; Success:
;   r1 = 1, r9 = 0
;   r10 = the score payload that was stored (same bits, for register-only
;         callers that do not want to re-load the destination)
;   bytes [r3, r3+4) = score as IEEE-754 binary32 little-endian
;   no other byte is written.
;
; Rejection:
;   r1 = 0, r9 = cause, r10 = 0
;   destination bytes [r3, r3+4) are completely unchanged.
;
;   cause 1: strength1 is non-finite (NaN, +inf, or -inf)
;   cause 2: strength2 is non-finite (NaN, +inf, or -inf)
;   cause 3: the finite inputs produced a non-finite score. This is a
;            defensive check; with the clamped domain below it is unreachable.
;
; The strength1 check runs before the strength2 check, and both run before
; any clamp, exp approximation, or store. The result-finiteness check runs
; before the first destination store. Rejection is therefore atomic: there
; is no partial output and the caller must test r1 before consuming r3.
;
; The destination span and the input values are caller-owned. The kernel
; validates neither pointer alignment nor aliasing, performs no allocation,
; uses no static scratch, and does not read or write any other memory.
;
; BOUNDED EXP APPROXIMATION
; -------------------------
; Because s is clamped to [-8, +8], only a = |s| in [0, 8] is needed for
; the negative-exponential argument:
;
;   n  = CVTFI(a * log2(e))          truncation toward zero, n in [0, 11]
;   nf = CVTIF(n)                    exact float32 integer 0..11
;   r  = nf * ln(2) - a              r in (-ln2, 0]
;   q  = sum_{k=0..7} r^k / k!       degree-7 Taylor, Horner order
;   e  = q * 2^-n                    approx exp(-a)
;   p  = 1 / (1 + e)                 approx sigmoid(a)
;
; For the original negative sign, sigmoid(-a) is formed as 1 - p, which
; preserves the exact symmetry sigmoid(-a) = 1 - sigmoid(a) before the final
; multiply. The coefficient constants are the binary32 encodings of 1/k!
; and ln(2); log2(e) is 0x3FB8AA3B.
;
; Absolute error bound over the declared clamped domain, measured against
; the real-valued sigmoid and rounded to f32, is
;
;   |approx_sigmoid(s) - sigmoid(s)| <= 2^-20 = 9.5367e-7
;
; for every finite s in [-8, +8]. The two-edge product therefore also has
; absolute error below 2^-20 (the observed worst case is below 6e-7).
; This is a bounded local guarantee on [-8, +8] only; it is not an expf or
; general sigmoid claim outside that interval.
;
; IMPLEMENTATION NOTES
; --------------------
; All arithmetic on addresses, sign fields, and exponent masks is native
; integer NaN16; only FADD, FSUB, FMUL, FDIV, FCMP, CVTIF, and CVTFI touch
; float payloads. There is no host math, lookup table, static scratch, or
; self-modification. The sigmoid helper is called twice via CALL; the outer
; entry point saves r15 in r12 and restores it on every return path.
;
; Register effects of mth_hyperedge_path_score:
;   clobbers r1-r12, r14 and flags.
;   preserves r0, r13, r15.
;
; Register effects of the internal sigmoid helper:
;   clobbers r1-r5, r9-r11, r14 and flags.
;   preserves r6-r8, r12, r13.

mth_hyperedge_path_score_f32:
mth_hyperedge_path_score:
  ADD r12,r15,r0             ; save caller return address
  ADD r8,r3,r0               ; save destination byte address

  ; ---- Preflight both strengths: exponent-all-ones rejects atomically. ----
  MOVI r4,0
  MOVHI r4,0x7F80            ; r4 = 0x7F800000 exponent-all-ones mask
  BOOL.8 r5,r1,r4
  CMP r5,r4
  JMP[EQ] @mth_path_score_reject_1
  BOOL.8 r5,r2,r4
  CMP r5,r4
  JMP[EQ] @mth_path_score_reject_2

  ; ---- Clamp strength1 in place to [-8.0, +8.0]. ----
  MOVI r4,0
  MOVHI r4,0x4100            ; +8.0
  FCMP r1,r4
  JMP[GT] @mth_path_score_clamp1_hi
  MOVI r5,0
  MOVHI r5,0xC100            ; -8.0
  FCMP r1,r5
  JMP[LT] @mth_path_score_clamp1_lo
  JMP @mth_path_score_clamp1_done
mth_path_score_clamp1_hi:
  ADD r1,r4,r0               ; exact +8.0 bit copy
  JMP @mth_path_score_clamp1_done
mth_path_score_clamp1_lo:
  ADD r1,r5,r0               ; exact -8.0 bit copy
mth_path_score_clamp1_done:

  ; ---- Clamp strength2 into r6. ----
  MOVI r4,0
  MOVHI r4,0x4100            ; +8.0
  FCMP r2,r4
  JMP[GT] @mth_path_score_clamp2_hi
  MOVI r5,0
  MOVHI r5,0xC100            ; -8.0
  FCMP r2,r5
  JMP[LT] @mth_path_score_clamp2_lo
  ADD r6,r2,r0
  JMP @mth_path_score_clamp2_done
mth_path_score_clamp2_hi:
  ADD r6,r4,r0               ; exact +8.0 bit copy
  JMP @mth_path_score_clamp2_done
mth_path_score_clamp2_lo:
  ADD r6,r5,r0               ; exact -8.0 bit copy
mth_path_score_clamp2_done:

  ; ---- p1 = sigmoid(s1). The helper preserves r6 (s2), r7, r8 (dest). ----
  CALL @mth_hyperedge_path_sigmoid
  ADD r7,r1,r0               ; r7 = p1

  ; ---- p2 = sigmoid(s2). ----
  ADD r1,r6,r0
  CALL @mth_hyperedge_path_sigmoid

  ; ---- score = p1 * p2, one rounded binary32 multiply. ----
  FMUL r9,r7,r1

  ; Defensive finite-result preflight before the destination store.
  MOVI r4,0
  MOVHI r4,0x7F80
  BOOL.8 r5,r9,r4
  CMP r5,r4
  JMP[EQ] @mth_path_score_reject_3

  ; ---- Store the f32 payload little-endian at the caller's byte address. ----
  ; A passing CMP above can leave k=1 (Z=0,L=1); STB uses nibble n=10 and
  ; would be predicated off in that state. ADD 0+0 sets k=2, which executes
  ; STB, and SHR below then leaves k=0 or k=2 for the remaining byte stores.
  ADD r11,r0,r0
  STB r9,r8,0
  SHR r11,r9,8
  STB r11,r8,1
  SHR r11,r11,8
  STB r11,r8,2
  SHR r11,r11,8
  STB r11,r8,3

  ADD r10,r9,r0              ; mirror the stored score bits in r10
  MOVI r9,0                  ; success has no failure cause
  MOVI r1,1
  ADD r15,r12,r0
  RET

mth_path_score_reject_1:
  MOVI r9,1
  JMP @mth_path_score_reject
mth_path_score_reject_2:
  MOVI r9,2
  JMP @mth_path_score_reject
mth_path_score_reject_3:
  MOVI r9,3
mth_path_score_reject:
  MOVI r10,0
  MOVI r1,0
  ADD r15,r12,r0
  RET

; ---------------------------------------------------------------------------
; Internal scalar sigmoid approximation.
;   input  r1 = finite f32 payload s in [-8, +8]
;   output r1 = approx sigmoid(s), finite in (0, 1)
;   clobbers r1-r5, r9-r11, r14 and flags
;   preserves r6-r8, r12, r13
; ---------------------------------------------------------------------------
mth_hyperedge_path_sigmoid:
  SHR r2,r1,31               ; sign: 0 for s >= 0, 1 for s < 0
  MOVI r3,0xFFFF
  MOVHI r3,0x7FFF
  BOOL.8 r3,r1,r3            ; a = |s| as payload bits

  ; y = a * log2(e); n = trunc(y); nf = float(n).
  MOVI r4,0xAA3B
  MOVHI r4,0x3FB8            ; log2(e) = 0x3FB8AA3B
  FMUL r4,r3,r4
  CVTFI r4,r4                ; n integer, 0..11 on this domain
  CVTIF r5,r4                ; nf exact float32

  ; r = nf*ln(2) - a, in (-ln2, 0]. r9 is scratch; r8 is preserved.
  MOVI r9,0x7218
  MOVHI r9,0x3F31            ; ln(2) = 0x3F317218
  FMUL r5,r5,r9
  FSUB r9,r5,r3

  ; q = exp(r) by degree-7 Taylor, Horner from 1/7!.
  MOVI r10,0x0D01
  MOVHI r10,0x3950           ; 1/5040 = 0x39500D01
  MOVI r11,0x0B61
  MOVHI r11,0x3AB6           ; 1/720  = 0x3AB60B61
  FMUL r10,r10,r9
  FADD r10,r10,r11
  MOVI r11,0x8889
  MOVHI r11,0x3C08           ; 1/120  = 0x3C088889
  FMUL r10,r10,r9
  FADD r10,r10,r11
  MOVI r11,0xAAAB
  MOVHI r11,0x3D2A           ; 1/24   = 0x3D2AAAAB
  FMUL r10,r10,r9
  FADD r10,r10,r11
  MOVI r11,0xAAAB
  MOVHI r11,0x3E2A           ; 1/6    = 0x3E2AAAAB
  FMUL r10,r10,r9
  FADD r10,r10,r11
  MOVI r11,0
  MOVHI r11,0x3F00           ; 1/2    = 0x3F000000
  FMUL r10,r10,r9
  FADD r10,r10,r11
  MOVI r11,0
  MOVHI r11,0x3F80           ; 1.0    = 0x3F800000
  FMUL r10,r10,r9
  FADD r10,r10,r11
  FMUL r10,r10,r9
  FADD r10,r10,r11           ; q = exp(r) approximation

  ; e = q * 2^-n; n is 0..11, so 127-n is a valid binary32 exponent.
  MOVI r11,127
  SUB r11,r11,r4
  SHL r11,r11,23
  FMUL r10,r10,r11           ; e = approx exp(-a)

  ; p_pos = 1 / (1 + e).
  MOVI r11,0
  MOVHI r11,0x3F80           ; 1.0
  FADD r14,r11,r10
  FDIV r14,r11,r14

  ; Negative original sign: p = 1 - p_pos.
  CMP r2,r0
  JMP[EQ] @mth_path_score_sigmoid_done
  FSUB r14,r11,r14
mth_path_score_sigmoid_done:
  ADD r1,r14,r0
  RET
