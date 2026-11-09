; MTH 256-element float32 byte-fallback argmax — NaN16 only.
;
; ABI:
;   r1  = scores, 256 float32 payloads (word address, read-only)
;   r2  = byte_out, one payload byte address
;   r13 = 1
;   success: r1 = 1, r3 = index (0..255)
;            r4 = exact 32-bit score payload of scores[index]
;            r9 = 0, and byte_out receives one byte equal to index
;   rejection: r1 = 0, r9 = cause, r3/r4 unchanged, byte_out untouched
;   clobbers r1, r5-r9 and the flags
;   preserves r0, r2, r3/r4 on rejection, r10-r15
;
; Result law:
;   index = smallest i in 0..255 maximizing scores[i].
;   The output byte is the low byte of index; because index is already
;   0..255, it is exactly the selected index. The score return is the raw
;   payload bits of the selected element, not a recomputed float.
;
; TIE RULE:
;   The scan visits i = 0..255 in increasing order and replaces the running
;   best only when candidate > best (strict float32 FCMP). An equal value
;   never replaces the current best, so the first index among equal maxima
;   wins. +0.0 and -0.0 compare equal, so the first zero in that tie wins
;   and r4 preserves that occurrence's exact sign bit.
;
; DOMAIN AND FAIL-CLOSED POLICY:
;   Every score must be finite. A complete preflight before the scan tests
;
;     (payload & 0x7F800000) == 0x7F800000
;
;   which is exactly the binary32 exponent-all-ones class (NaN and both
;   infinities). The first such element rejects the call with r1 = 0 and
;   cause code 1 in r9. No byte is written on rejection, and r3/r4 are left
;   unchanged. After the preflight every FCMP is ordered, so NaN ordering
;   is never attempted.
;
; The kernel is a leaf: no CALL, no static storage, no allocation, and no
; host math. Only integer address arithmetic, one exact float32 FCMP per
; scanned element, a bit copy, and one STB on success.

mth_byte_fallback_argmax:
  ; Preflight every score before the scan and before any output write.
  MOVI r5,0
  MOVHI r5,0x7F80            ; r5 = 0x7F800000 exponent mask
  MOVI r6,0
mth_bfa_preflight:
  ADD r7,r1,r6
  LD r7,r7,0
  BOOL.8 r7,r7,r5            ; exponent bits only
  CMP r7,r5
  JMP[EQ] @mth_bfa_nonfinite
  ADD r6,r6,r13
  MOVI r7,256
  CMP r6,r7
  JMP[LT] @mth_bfa_preflight

  ; Seed with scores[0]. The preflight proved it finite, so every later
  ; FCMP is ordered and the strict-predicate scan is total.
  LD r7,r1,0                 ; best value payload
  MOVI r8,0                  ; best index
  MOVI r6,1                  ; i = 1
mth_bfa_scan:
  ADD r5,r1,r6
  LD r5,r5,0                 ; candidate
  FCMP r5,r7
  JMP[GT] @mth_bfa_take
  JMP @mth_bfa_next
mth_bfa_take:
  ADD r7,r5,r0               ; best = candidate (exact payload copy)
  ADD r8,r6,r0               ; best index = i
mth_bfa_next:
  ADD r6,r6,r13
  MOVI r5,256
  CMP r6,r5
  JMP[LT] @mth_bfa_scan

  ; Publish only after every element was validated and scanned.
  STB r8,r2,0                ; one byte: selected index
  ADD r3,r8,r0
  ADD r4,r7,r0
  MOVI r9,0
  MOVI r1,1
  RET

mth_bfa_nonfinite:
  MOVI r9,1                  ; cause 1: non-finite score
  MOVI r1,0
  RET
