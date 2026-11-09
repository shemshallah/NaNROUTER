; MTH vector mask256 float32 fixture — NaN16 only.
;
; All input and expected vectors are generated in the guest at run time: the
; fixture fills 256-word spans from literal IEEE binary32 payloads, writes
; sparse (index, payload) pairs, and for the alternating phases selects one
; payload for even indices and one for odd indices. Every check is a native
; integer CMP; no host arithmetic is used at build time or run time.
;
; Success phases (all 256 output words checked):
;   1. x=2.0; mask=+1.0 even, -1.0 odd -> out=2.0 even, +0.0 odd.
;   2. x=-5.0; mask=+0.0 even, -0.0 odd -> all out=+0.0. -0.0 does not
;      select and the unselected result is +0.0, never -0.0.
;   3. x=3.0; mask=-2.0 even, -0.5 odd -> all out=+0.0.
;   4. x=1.0; mask=+min-subnormal even, -min-subnormal odd -> out=1.0 even,
;      +0.0 odd. Positive subnormal masks select; negative ones do not.
;   5. x is an 8-payload finite pattern repeated 32 times and mask=+1.0
;      everywhere -> out is a bit-for-bit copy of x, including -0.0,
;      +max-finite, and both signed min-subnormals.
;   6. x=4.0; sparse positive mask at 0, 17, 128, 255 (including
;      +min-subnormal and 2^-127) -> out=4.0 only at those indices.
;   7. exact out == x aliasing with the phase-1 pattern.
;   8. exact out == mask aliasing with the phase-1 pattern.
;
; Failure phases (r1=0, r9=cause, out[0]=status, out[1..255]=marker):
;   9. quiet NaN x at index 17 -> cause 1.
;  10. +inf x at index 200 -> cause 1.
;  11. -inf x at index 3 -> cause 1.
;  12. quiet NaN mask at index 255 -> cause 2.
;  13. +inf mask at index 0 -> cause 2.
;  14. -inf mask at index 128 -> cause 2.
;  15. +inf x at index 200 with a non-selecting (all -1.0) mask -> cause 1:
;      x is rejected regardless of the mask predicate.
;  16. bad x at index 10 and bad mask at index 20 -> cause 1: the complete x
;      preflight has priority over the mask preflight.
;  17. recovery: the phase-1 pattern succeeds again after all rejections.
;
; The output span is pre-filled with the 0xDEADBEEF sentinel before every
; failure phase, so each rejection is observed to overwrite all 256 words.

.org 0
JMP @mth_vmask_test_main
.include "../nan16/mth_vector_mask256_f32.nas"

mth_vmask_test_main:
  MOVI r13,1

  ; ---- Phase 1: positive even mask, negative odd mask.
  MOVI r1,@mth_vmask_test_x
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x4000            ; 2.0
  CALL @mth_vmask_test_fill
  MOVI r1,@mth_vmask_test_mask
  MOVI r2,0
  MOVHI r2,0x3F80            ; even +1.0
  MOVI r3,0
  MOVHI r3,0xBF80            ; odd -1.0
  MOVI r4,256
  CALL @mth_vmask_test_alternate
  MOVI r1,@mth_vmask_test_exp
  MOVI r2,0
  MOVHI r2,0x4000            ; even 2.0
  MOVI r3,0                  ; odd +0.0
  MOVI r4,256
  CALL @mth_vmask_test_alternate
  CALL @mth_vmask_test_call
  CMP r1,r13
  JMP[NE] @mth_vmask_test_fail
  CMP r9,r0
  JMP[NE] @mth_vmask_test_fail
  MOVI r1,@mth_vmask_test_out
  MOVI r2,@mth_vmask_test_exp
  MOVI r4,256
  CALL @mth_vmask_test_check256

  ; ---- Phase 2: +0.0 and -0.0 masks never select; result is +0.0.
  MOVI r1,@mth_vmask_test_x
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0xC0A0            ; -5.0
  CALL @mth_vmask_test_fill
  MOVI r1,@mth_vmask_test_mask
  MOVI r2,0                  ; even +0.0
  MOVI r3,0
  MOVHI r3,0x8000            ; odd -0.0
  MOVI r4,256
  CALL @mth_vmask_test_alternate
  MOVI r1,@mth_vmask_test_exp
  MOVI r2,256
  MOVI r4,0                  ; +0.0 everywhere
  CALL @mth_vmask_test_fill
  CALL @mth_vmask_test_call
  CMP r1,r13
  JMP[NE] @mth_vmask_test_fail
  CMP r9,r0
  JMP[NE] @mth_vmask_test_fail
  MOVI r1,@mth_vmask_test_out
  MOVI r2,@mth_vmask_test_exp
  MOVI r4,256
  CALL @mth_vmask_test_check256

  ; ---- Phase 3: negative finite masks never select.
  MOVI r1,@mth_vmask_test_x
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x4040            ; 3.0
  CALL @mth_vmask_test_fill
  MOVI r1,@mth_vmask_test_mask
  MOVI r2,0
  MOVHI r2,0xC000            ; even -2.0
  MOVI r3,0
  MOVHI r3,0xBF00            ; odd -0.5
  MOVI r4,256
  CALL @mth_vmask_test_alternate
  MOVI r1,@mth_vmask_test_exp
  MOVI r2,256
  MOVI r4,0
  CALL @mth_vmask_test_fill
  CALL @mth_vmask_test_call
  CMP r1,r13
  JMP[NE] @mth_vmask_test_fail
  CMP r9,r0
  JMP[NE] @mth_vmask_test_fail
  MOVI r1,@mth_vmask_test_out
  MOVI r2,@mth_vmask_test_exp
  MOVI r4,256
  CALL @mth_vmask_test_check256

  ; ---- Phase 4: positive subnormal selects, negative subnormal does not.
  MOVI r1,@mth_vmask_test_x
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x3F80            ; 1.0
  CALL @mth_vmask_test_fill
  MOVI r1,@mth_vmask_test_mask
  MOVI r2,1                  ; even +min subnormal
  MOVI r3,1
  MOVHI r3,0x8000            ; odd -min subnormal
  MOVI r4,256
  CALL @mth_vmask_test_alternate
  MOVI r1,@mth_vmask_test_exp
  MOVI r2,0
  MOVHI r2,0x3F80            ; even 1.0
  MOVI r3,0                  ; odd +0.0
  MOVI r4,256
  CALL @mth_vmask_test_alternate
  CALL @mth_vmask_test_call
  CMP r1,r13
  JMP[NE] @mth_vmask_test_fail
  CMP r9,r0
  JMP[NE] @mth_vmask_test_fail
  MOVI r1,@mth_vmask_test_out
  MOVI r2,@mth_vmask_test_exp
  MOVI r4,256
  CALL @mth_vmask_test_check256

  ; ---- Phase 5: all-positive mask copies every finite payload exactly.
  MOVI r8,@mth_vmask_test_pattern
  MOVI r1,@mth_vmask_test_x
  MOVI r2,256
  MOVI r7,7
  CALL @mth_vmask_test_copy_pattern
  MOVI r1,@mth_vmask_test_mask
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x3F80
  CALL @mth_vmask_test_fill
  CALL @mth_vmask_test_call
  CMP r1,r13
  JMP[NE] @mth_vmask_test_fail
  CMP r9,r0
  JMP[NE] @mth_vmask_test_fail
  MOVI r1,@mth_vmask_test_out
  MOVI r2,@mth_vmask_test_x
  MOVI r4,256
  CALL @mth_vmask_test_check256

  ; ---- Phase 6: sparse positive mask at 0, 17, 128, 255.
  MOVI r1,@mth_vmask_test_x
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x4080            ; 4.0
  CALL @mth_vmask_test_fill
  MOVI r1,@mth_vmask_test_mask
  MOVI r2,0
  MOVHI r2,0xBF80            ; non-selecting base -1.0
  MOVI r3,@mth_vmask_test_sel_pairs
  MOVI r4,4
  CALL @mth_vmask_test_sparse
  MOVI r1,@mth_vmask_test_exp
  MOVI r2,0                  ; +0.0 base
  MOVI r3,@mth_vmask_test_sel_exp
  MOVI r4,4
  CALL @mth_vmask_test_sparse
  CALL @mth_vmask_test_call
  CMP r1,r13
  JMP[NE] @mth_vmask_test_fail
  CMP r9,r0
  JMP[NE] @mth_vmask_test_fail
  MOVI r1,@mth_vmask_test_out
  MOVI r2,@mth_vmask_test_exp
  MOVI r4,256
  CALL @mth_vmask_test_check256

  ; ---- Phase 7: exact out == x aliasing succeeds.
  MOVI r1,@mth_vmask_test_x
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x4000
  CALL @mth_vmask_test_fill
  MOVI r1,@mth_vmask_test_mask
  MOVI r2,0
  MOVHI r2,0x3F80
  MOVI r3,0
  MOVHI r3,0xBF80
  MOVI r4,256
  CALL @mth_vmask_test_alternate
  MOVI r1,@mth_vmask_test_exp
  MOVI r2,0
  MOVHI r2,0x4000
  MOVI r3,0
  MOVI r4,256
  CALL @mth_vmask_test_alternate
  MOVI r1,@mth_vmask_test_x
  MOVI r2,@mth_vmask_test_mask
  MOVI r3,@mth_vmask_test_x
  CALL @mth_vector_mask256_f32
  CMP r1,r13
  JMP[NE] @mth_vmask_test_fail
  CMP r9,r0
  JMP[NE] @mth_vmask_test_fail
  MOVI r1,@mth_vmask_test_x
  MOVI r2,@mth_vmask_test_exp
  MOVI r4,256
  CALL @mth_vmask_test_check256

  ; ---- Phase 8: exact out == mask aliasing succeeds.
  MOVI r1,@mth_vmask_test_x
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x4000
  CALL @mth_vmask_test_fill
  MOVI r1,@mth_vmask_test_mask
  MOVI r2,0
  MOVHI r2,0x3F80
  MOVI r3,0
  MOVHI r3,0xBF80
  MOVI r4,256
  CALL @mth_vmask_test_alternate
  MOVI r1,@mth_vmask_test_exp
  MOVI r2,0
  MOVHI r2,0x4000
  MOVI r3,0
  MOVI r4,256
  CALL @mth_vmask_test_alternate
  MOVI r1,@mth_vmask_test_x
  MOVI r2,@mth_vmask_test_mask
  MOVI r3,@mth_vmask_test_mask
  CALL @mth_vector_mask256_f32
  CMP r1,r13
  JMP[NE] @mth_vmask_test_fail
  CMP r9,r0
  JMP[NE] @mth_vmask_test_fail
  MOVI r1,@mth_vmask_test_mask
  MOVI r2,@mth_vmask_test_exp
  MOVI r4,256
  CALL @mth_vmask_test_check256

  ; ---- Phase 9: quiet NaN x at index 17, cause 1.
  MOVI r1,@mth_vmask_test_x
  MOVI r2,0
  MOVHI r2,0x3F80
  MOVI r3,@mth_vmask_test_bad_x_qnan
  MOVI r4,1
  CALL @mth_vmask_test_sparse
  MOVI r1,@mth_vmask_test_mask
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x3F80
  CALL @mth_vmask_test_fill
  CALL @mth_vmask_test_sentinel
  CALL @mth_vmask_test_call
  MOVI r5,1
  CALL @mth_vmask_test_check_failure

  ; ---- Phase 10: +inf x at index 200, cause 1.
  MOVI r1,@mth_vmask_test_x
  MOVI r2,0
  MOVHI r2,0x3F80
  MOVI r3,@mth_vmask_test_bad_x_pinf
  MOVI r4,1
  CALL @mth_vmask_test_sparse
  MOVI r1,@mth_vmask_test_mask
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x3F80
  CALL @mth_vmask_test_fill
  CALL @mth_vmask_test_sentinel
  CALL @mth_vmask_test_call
  MOVI r5,1
  CALL @mth_vmask_test_check_failure

  ; ---- Phase 11: -inf x at index 3, cause 1.
  MOVI r1,@mth_vmask_test_x
  MOVI r2,0
  MOVHI r2,0x3F80
  MOVI r3,@mth_vmask_test_bad_x_ninf
  MOVI r4,1
  CALL @mth_vmask_test_sparse
  MOVI r1,@mth_vmask_test_mask
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x3F80
  CALL @mth_vmask_test_fill
  CALL @mth_vmask_test_sentinel
  CALL @mth_vmask_test_call
  MOVI r5,1
  CALL @mth_vmask_test_check_failure

  ; ---- Phase 12: quiet NaN mask at index 255, cause 2.
  MOVI r1,@mth_vmask_test_x
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x3F80
  CALL @mth_vmask_test_fill
  MOVI r1,@mth_vmask_test_mask
  MOVI r2,0
  MOVHI r2,0x3F80
  MOVI r3,@mth_vmask_test_bad_mask_qnan
  MOVI r4,1
  CALL @mth_vmask_test_sparse
  CALL @mth_vmask_test_sentinel
  CALL @mth_vmask_test_call
  MOVI r5,2
  CALL @mth_vmask_test_check_failure

  ; ---- Phase 13: +inf mask at index 0, cause 2.
  MOVI r1,@mth_vmask_test_x
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x3F80
  CALL @mth_vmask_test_fill
  MOVI r1,@mth_vmask_test_mask
  MOVI r2,0
  MOVHI r2,0x3F80
  MOVI r3,@mth_vmask_test_bad_mask_pinf
  MOVI r4,1
  CALL @mth_vmask_test_sparse
  CALL @mth_vmask_test_sentinel
  CALL @mth_vmask_test_call
  MOVI r5,2
  CALL @mth_vmask_test_check_failure

  ; ---- Phase 14: -inf mask at index 128, cause 2.
  MOVI r1,@mth_vmask_test_x
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x3F80
  CALL @mth_vmask_test_fill
  MOVI r1,@mth_vmask_test_mask
  MOVI r2,0
  MOVHI r2,0x3F80
  MOVI r3,@mth_vmask_test_bad_mask_ninf
  MOVI r4,1
  CALL @mth_vmask_test_sparse
  CALL @mth_vmask_test_sentinel
  CALL @mth_vmask_test_call
  MOVI r5,2
  CALL @mth_vmask_test_check_failure

  ; ---- Phase 15: non-finite x is rejected even where mask <= 0.
  MOVI r1,@mth_vmask_test_x
  MOVI r2,0
  MOVHI r2,0x3F80
  MOVI r3,@mth_vmask_test_bad_x_pinf
  MOVI r4,1
  CALL @mth_vmask_test_sparse
  MOVI r1,@mth_vmask_test_mask
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0xBF80            ; all -1.0, nothing selects
  CALL @mth_vmask_test_fill
  CALL @mth_vmask_test_sentinel
  CALL @mth_vmask_test_call
  MOVI r5,1
  CALL @mth_vmask_test_check_failure

  ; ---- Phase 16: bad x and bad mask together report the x cause first.
  MOVI r1,@mth_vmask_test_x
  MOVI r2,0
  MOVHI r2,0x3F80
  MOVI r3,@mth_vmask_test_bad_both_x
  MOVI r4,1
  CALL @mth_vmask_test_sparse
  MOVI r1,@mth_vmask_test_mask
  MOVI r2,0
  MOVHI r2,0x3F80
  MOVI r3,@mth_vmask_test_bad_both_mask
  MOVI r4,1
  CALL @mth_vmask_test_sparse
  CALL @mth_vmask_test_sentinel
  CALL @mth_vmask_test_call
  MOVI r5,1
  CALL @mth_vmask_test_check_failure

  ; ---- Phase 17: recovery after rejection.
  MOVI r1,@mth_vmask_test_x
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x4000
  CALL @mth_vmask_test_fill
  MOVI r1,@mth_vmask_test_mask
  MOVI r2,0
  MOVHI r2,0x3F80
  MOVI r3,0
  MOVHI r3,0xBF80
  MOVI r4,256
  CALL @mth_vmask_test_alternate
  MOVI r1,@mth_vmask_test_exp
  MOVI r2,0
  MOVHI r2,0x4000
  MOVI r3,0
  MOVI r4,256
  CALL @mth_vmask_test_alternate
  CALL @mth_vmask_test_call
  CMP r1,r13
  JMP[NE] @mth_vmask_test_fail
  CMP r9,r0
  JMP[NE] @mth_vmask_test_fail
  MOVI r1,@mth_vmask_test_out
  MOVI r2,@mth_vmask_test_exp
  MOVI r4,256
  CALL @mth_vmask_test_check256

  MOVI r1,@mth_vmask_test_pass
  CALL @mth_vmask_test_puts
  HALT

mth_vmask_test_fail:
  MOVI r1,@mth_vmask_test_bad
  CALL @mth_vmask_test_puts
  HALT

; Call the mask kernel on the fixture x/mask/out spans and return its r1.
; Saves the link register in r14; the kernel preserves r14.
mth_vmask_test_call:
  ADD r14,r15,r0
  MOVI r1,@mth_vmask_test_x
  MOVI r2,@mth_vmask_test_mask
  MOVI r3,@mth_vmask_test_out
  CALL @mth_vector_mask256_f32
  ADD r15,r14,r0
  RET

; r1 = destination, r2 = count (positive), r4 = payload.
; Clobbers r1, r2.
mth_vmask_test_fill:
  ST r4,r1,0
  ADD r1,r1,r13
  SUB r2,r2,r13
  CMP r2,r0
  JMP[GT] @mth_vmask_test_fill
  RET

; r1 = destination, r2 = even payload, r3 = odd payload, r4 = count.
; Clobbers r1, r5, r6.
mth_vmask_test_alternate:
  MOVI r5,0
mth_vmask_test_alternate_loop:
  BOOL.8 r6,r5,r13           ; r5 & 1
  CMP r6,r0
  JMP[NE] @mth_vmask_test_alternate_odd
  ST r2,r1,0
  JMP @mth_vmask_test_alternate_next
mth_vmask_test_alternate_odd:
  ST r3,r1,0
mth_vmask_test_alternate_next:
  ADD r1,r1,r13
  ADD r5,r5,r13
  CMP r5,r4
  JMP[LT] @mth_vmask_test_alternate_loop
  RET

; r1 = destination, r2 = base payload, r3 = (index,payload) pairs,
; r4 = pair count. Fills 256 words with the base, then writes the pairs.
; Clobbers r1, r3, r4, r5, r7, r8, r9.
mth_vmask_test_sparse:
  ADD r7,r1,r0               ; save destination
  MOVI r5,256
mth_vmask_test_sparse_fill:
  ST r2,r1,0
  ADD r1,r1,r13
  SUB r5,r5,r13
  CMP r5,r0
  JMP[GT] @mth_vmask_test_sparse_fill
  CMP r4,r0
  JMP[EQ] @mth_vmask_test_sparse_done
mth_vmask_test_sparse_pairs:
  LD r8,r3,0
  ADD r3,r3,r13
  LD r9,r3,0
  ADD r3,r3,r13
  ADD r8,r7,r8
  ST r9,r8,0
  SUB r4,r4,r13
  CMP r4,r0
  JMP[GT] @mth_vmask_test_sparse_pairs
mth_vmask_test_sparse_done:
  RET

; r1 = destination, r8 = 8-word pattern table, r2 = count, r7 must be 7.
; Writes pattern[i & 7] for i = 0..count-1. Clobbers r1, r2, r5, r6.
mth_vmask_test_copy_pattern:
  MOVI r5,0
mth_vmask_test_copy_pattern_loop:
  BOOL.8 r6,r5,r7            ; i & 7
  ADD r6,r8,r6
  LD r6,r6,0
  ST r6,r1,0
  ADD r1,r1,r13
  ADD r5,r5,r13
  SUB r2,r2,r13
  CMP r2,r0
  JMP[GT] @mth_vmask_test_copy_pattern_loop
  RET

; Fill out[0..255] with 0xDEADBEEF. Clobbers r1, r2, r4.
mth_vmask_test_sentinel:
  MOVI r1,@mth_vmask_test_out
  MOVI r2,256
  MOVI r4,0xBEEF
  MOVHI r4,0xDEAD
mth_vmask_test_sentinel_loop:
  ST r4,r1,0
  ADD r1,r1,r13
  SUB r2,r2,r13
  CMP r2,r0
  JMP[GT] @mth_vmask_test_sentinel_loop
  RET

; r1 = actual, r2 = expected, r4 = count. Clobbers r1, r2, r4-r6.
mth_vmask_test_check256:
  LD r5,r1,0
  LD r6,r2,0
  CMP r5,r6
  JMP[NE] @mth_vmask_test_fail
  ADD r1,r1,r13
  ADD r2,r2,r13
  SUB r4,r4,r13
  CMP r4,r0
  JMP[GT] @mth_vmask_test_check256
  RET

; r1 = kernel status, r9 = kernel cause, r5 = expected cause.
; Requires out[0]=0xFFC0DEAC+cause and out[1..255]=0xFFC0DEAD.
; Clobbers r1, r2, r4, r6, r7.
mth_vmask_test_check_failure:
  CMP r1,r0
  JMP[NE] @mth_vmask_test_fail
  CMP r9,r5
  JMP[NE] @mth_vmask_test_fail
  MOVI r1,@mth_vmask_test_out
  MOVI r2,0xDEAC
  MOVHI r2,0xFFC0
  ADD r2,r2,r9
  LD r6,r1,0
  CMP r6,r2
  JMP[NE] @mth_vmask_test_fail
  MOVI r7,0xDEAD
  MOVHI r7,0xFFC0
  MOVI r4,1
mth_vmask_test_check_failure_fill:
  ADD r6,r1,r4
  LD r6,r6,0
  CMP r6,r7
  JMP[NE] @mth_vmask_test_fail
  ADD r4,r4,r13
  MOVI r6,256
  CMP r4,r6
  JMP[LT] @mth_vmask_test_check_failure_fill
  RET

mth_vmask_test_puts:
  MOVI r4,255
mth_vmask_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_vmask_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_vmask_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_vmask_test_puts_word

.org 1024
mth_vmask_test_x:
.word 0
.org 2048
mth_vmask_test_mask:
.word 0
.org 3072
mth_vmask_test_out:
.word 0
.org 4096
mth_vmask_test_exp:
.word 0
.org 5120
mth_vmask_test_pattern:
.word 0x80000000          ; -0.0
.word 0x00000000          ; +0.0
.word 0xBF800000          ; -1.0
.word 0x7F7FFFFF          ; +max finite
.word 0x00000001          ; +min subnormal
.word 0x80000001          ; -min subnormal
.word 0x3F800001          ; 1 + 2^-23
.word 0xC0800000          ; -4.0
.org 6144
mth_vmask_test_sel_pairs:
.word 0,0x00000001        ; +min subnormal selects
.word 17,0x3F800000       ; +1.0 selects
.word 128,0x7F7FFFFF      ; +max finite selects
.word 255,0x00400000      ; 2^-127 subnormal selects
mth_vmask_test_sel_exp:
.word 0,0x40800000        ; 4.0
.word 17,0x40800000
.word 128,0x40800000
.word 255,0x40800000
.org 7168
mth_vmask_test_bad_x_qnan:
.word 17,0x7FC00123       ; quiet NaN
mth_vmask_test_bad_x_pinf:
.word 200,0x7F800000      ; +inf
mth_vmask_test_bad_x_ninf:
.word 3,0xFF800000        ; -inf
mth_vmask_test_bad_mask_qnan:
.word 255,0x7FC00123      ; quiet NaN
mth_vmask_test_bad_mask_pinf:
.word 0,0x7F800000        ; +inf
mth_vmask_test_bad_mask_ninf:
.word 128,0xFF800000      ; -inf
mth_vmask_test_bad_both_x:
.word 10,0x7FC00123       ; quiet NaN
mth_vmask_test_bad_both_mask:
.word 20,0x7F800000       ; +inf
.org 8192
mth_vmask_test_pass:
.str "MTH VECTOR MASK256 F32 PASS\n"
mth_vmask_test_bad:
.str "MTH VECTOR MASK256 F32 FAIL\n"
