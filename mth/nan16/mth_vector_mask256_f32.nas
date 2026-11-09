; MTH 256-element float32 positive-mask select — NaN16 only.
;
; ABI:
;   r1  = x, 256 float32 payloads (read-only)
;   r2  = mask, 256 float32 payloads (read-only)
;   r3  = out, 256 float32 payloads
;   r13 = 1
;   returns r1 = 1 on success, r1 = 0 on rejection
;   on rejection r9 = cause code and out[] holds status/marker words
;   clobbers r1, r4-r11 and the flags
;   preserves r0, r2, r3, r12-r15
;
; Result on success:
;   out[i] = x[i]   if mask[i] > +0.0
;   out[i] = +0.0   if mask[i] <= +0.0
;   A selected element is copied as its exact 32-bit payload. An unselected
;   element is the bit pattern 0x00000000 (+0.0), never -0.0.
;
; STATUS CONVENTION:
;   success: r1 = 1, r9 = 0, out[0..255] = selected values.
;   failure: r1 = 0, r9 = cause, out[0] = status word,
;            out[1..255] = 0xFFC0DEAD (canonical marker).
;   cause 1: non-finite x element (NaN, +inf, or -inf)
;            status = 0xFFC0DEAD
;   cause 2: non-finite mask element (NaN, +inf, or -inf)
;            status = 0xFFC0DEAE
;   The status in out[0] is 0xFFC0DEAC + cause. Every failure word is a
;   diagnostic quiet-NaN-class payload, never a select result. A caller must
;   check r1 before consuming out[].
;
; DOMAIN AND FAIL-CLOSED POLICY:
;   Every x[i] and every mask[i] must be finite. A preflight tests
;
;     (payload & 0x7F800000) == 0x7F800000
;
;   which is exactly the binary32 exponent-all-ones class (NaN and both
;   infinities). The complete x preflight runs first and then the complete
;   mask preflight, all before the first output store. A non-finite value is
;   therefore never used as a select predicate and never copied into a
;   result. x is rejected even at indices whose mask[i] <= 0.
;
;   After the preflight the select test is exactly one ordered float32
;   FCMP mask[i] > +0.0 per element in increasing i. All masks are finite at
;   that point, so the comparison is ordered. -0.0 compares equal to +0.0
;   and does not select; any positive subnormal does select. Selection is a
;   bit copy: there is no host math, no rounding, and no recombination.
;
; Alias: exact out == x is safe on success because x[i] is loaded before
; out[i] is stored; exact out == mask is safe on success because mask[i] is
; loaded before out[i] is stored. Partial overlap is not safe. On rejection
; out[] is overwritten with the status/marker regardless of aliasing. The
; three spans must each hold 256 readable/writable words; there is no length
; or alignment validation.

mth_vector_mask256_f32:
  MOVI r4,0
  MOVHI r4,0x7F80            ; r4 = 0x7F800000 exponent mask

  ; Preflight x completely before looking at mask or writing out.
  MOVI r5,0
mth_vmask256_x_preflight:
  ADD r6,r1,r5
  LD r7,r6,0
  BOOL.8 r7,r7,r4            ; exponent bits of x[i]
  CMP r7,r4
  JMP[EQ] @mth_vmask256_nonfinite_x
  ADD r5,r5,r13
  MOVI r6,256
  CMP r5,r6
  JMP[LT] @mth_vmask256_x_preflight

  ; Preflight mask completely before the first output store.
  MOVI r5,0
mth_vmask256_mask_preflight:
  ADD r6,r2,r5
  LD r7,r6,0
  BOOL.8 r7,r7,r4            ; exponent bits of mask[i]
  CMP r7,r4
  JMP[EQ] @mth_vmask256_nonfinite_mask
  ADD r5,r5,r13
  MOVI r6,256
  CMP r5,r6
  JMP[LT] @mth_vmask256_mask_preflight

  ; Select in increasing i. Both inputs are finite, so FCMP is ordered.
  MOVI r5,0
mth_vmask256_select_loop:
  ADD r6,r2,r5
  LD r7,r6,0                 ; mask[i]
  FCMP r7,r0
  JMP[GT] @mth_vmask256_take
  MOVI r7,0                  ; mask[i] <= +0.0 -> +0.0
  JMP @mth_vmask256_store
mth_vmask256_take:
  ADD r6,r1,r5
  LD r7,r6,0                 ; x[i], exact payload copy
mth_vmask256_store:
  ADD r6,r3,r5
  ST r7,r6,0
  ADD r5,r5,r13
  MOVI r6,256
  CMP r5,r6
  JMP[LT] @mth_vmask256_select_loop

  MOVI r9,0
  MOVI r1,1
  RET

mth_vmask256_nonfinite_x:
  MOVI r9,1
  JMP @mth_vmask256_fail
mth_vmask256_nonfinite_mask:
  MOVI r9,2
  JMP @mth_vmask256_fail

mth_vmask256_fail:
  MOVI r10,0xDEAC
  MOVHI r10,0xFFC0           ; r10 = 0xFFC0DEAC status base
  ADD r10,r10,r9             ; status = 0xFFC0DEAC + cause
  ST r10,r3,0                ; out[0] = status
  MOVI r11,0xDEAD
  MOVHI r11,0xFFC0           ; r11 = 0xFFC0DEAD marker
  MOVI r5,1
mth_vmask256_fail_fill:
  ADD r6,r3,r5
  ST r11,r6,0
  ADD r5,r5,r13
  MOVI r6,256
  CMP r5,r6
  JMP[LT] @mth_vmask256_fail_fill
  MOVI r1,0
  RET
