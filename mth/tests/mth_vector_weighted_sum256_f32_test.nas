; MTH vector weighted-sum256 float32 fixture — NaN16 only.
;
; All input vectors and every expected scalar are generated in the guest at
; run time from literal IEEE binary32 payloads: 256-word spans are filled
; from a base payload or from sparse (index, payload) tables, and every check
; is a native integer CMP. No host arithmetic is used at build time or run
; time.
;
; The success phases check the exact output word for:
;   1. all 1.0 * 1.0 -> 256.0.
;   2. all 2.0 * 3.0 -> 1536.0.
;   3. all -2.0 * 3.0 -> -1536.0.
;   4. all 7.0 * +0.0 -> +0.0.
;   5. all 7.0 * -0.0 -> +0.0 (the accumulator starts at +0.0).
;   6. all 1.0 * 2^-8 -> 1.0 exactly.
;   7. order: x[0]=1.0, x[1..255]=2^-25, w=1.0. The increasing-order sum
;      absorbs every 2^-25 addend and stays 1.0; a reordered/tree sum would
;      reach 1+2^-17, so this phase pins the declared order.
;   8. RNE tie: 1.0 + 2^-24 rounds back to 1.0 (ties-to-even).
;   9. RNE carry: 1.0 + 3*2^-24 rounds to 1+2^-22.
;  10. product rounding: (1+2^-23)^2 rounds to 1+2^-22.
;  11. 256 * min-subnormal * 1.0 -> 0x00000100 (no FTZ/DAZ).
;  12. sparse +1 and -1 products cancel to +0.0.
;  13. the same sparse case with a final +1 product -> 1.0.
;  14. 2^-126 * 2^-2 underflows to subnormal 2^-128 and is preserved.
;
; Failure phases (r1=0, r9=cause, out=0xFFC0DEAD marker):
;  15. quiet NaN x at 17 -> cause 1.
;  16. +inf x at 200 -> cause 1.
;  17. -inf x at 3 -> cause 1.
;  18. quiet NaN w at 255 -> cause 2.
;  19. +inf w at 0 -> cause 2.
;  20. -inf w at 128 -> cause 2.
;  21. bad x and bad w together -> cause 1 (x preflight first).
;  22. +inf x where w=0 -> cause 1 (x is rejected before w=0 matters).
;  23. quiet NaN w where x=0 -> cause 2.
;  24. finite 2^127 * 2.0 overflows the product -> cause 3.
;  25. finite -2^127 * 2.0 overflows the product -> cause 3.
;  26. two finite 2^127 products overflow the accumulator -> cause 4.
;  27. two finite -2^127 products overflow the accumulator -> cause 4.
;  28. recovery: the phase-2 case succeeds again.
;
; out is pre-filled with 0xDEADBEEF before every failure phase, so each
; rejection is observed to replace it with the marker.

.org 0
JMP @mth_wsum_test_main
.include "../nan16/mth_vector_weighted_sum256_f32.nas"

mth_wsum_test_main:
  MOVI r13,1

  ; ---- Phase 1: 1.0 * 1.0 over 256 elements -> 256.0.
  MOVI r1,@mth_wsum_test_x
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x3F80
  CALL @mth_wsum_test_fill
  MOVI r1,@mth_wsum_test_w
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x3F80
  CALL @mth_wsum_test_fill
  CALL @mth_wsum_test_call
  MOVI r5,0
  MOVHI r5,0x4380            ; 256.0
  CALL @mth_wsum_test_check

  ; ---- Phase 2: 2.0 * 3.0 over 256 elements -> 1536.0.
  MOVI r1,@mth_wsum_test_x
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x4000
  CALL @mth_wsum_test_fill
  MOVI r1,@mth_wsum_test_w
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x4040
  CALL @mth_wsum_test_fill
  CALL @mth_wsum_test_call
  MOVI r5,0
  MOVHI r5,0x44C0            ; 1536.0
  CALL @mth_wsum_test_check

  ; ---- Phase 3: -2.0 * 3.0 over 256 elements -> -1536.0.
  MOVI r1,@mth_wsum_test_x
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0xC000
  CALL @mth_wsum_test_fill
  CALL @mth_wsum_test_call
  MOVI r5,0
  MOVHI r5,0xC4C0            ; -1536.0
  CALL @mth_wsum_test_check

  ; ---- Phase 4: 7.0 * +0.0 -> +0.0.
  MOVI r1,@mth_wsum_test_x
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x40E0            ; 7.0
  CALL @mth_wsum_test_fill
  MOVI r1,@mth_wsum_test_w
  MOVI r2,256
  MOVI r4,0                  ; +0.0
  CALL @mth_wsum_test_fill
  CALL @mth_wsum_test_call
  MOVI r5,0
  CALL @mth_wsum_test_check

  ; ---- Phase 5: 7.0 * -0.0 -> +0.0 (accumulator starts at +0.0).
  MOVI r1,@mth_wsum_test_w
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x8000            ; -0.0
  CALL @mth_wsum_test_fill
  CALL @mth_wsum_test_call
  MOVI r5,0
  CALL @mth_wsum_test_check

  ; ---- Phase 6: 1.0 * 2^-8 over 256 elements -> 1.0.
  MOVI r1,@mth_wsum_test_x
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x3F80
  CALL @mth_wsum_test_fill
  MOVI r1,@mth_wsum_test_w
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x3B80            ; 2^-8
  CALL @mth_wsum_test_fill
  CALL @mth_wsum_test_call
  MOVI r5,0
  MOVHI r5,0x3F80            ; 1.0
  CALL @mth_wsum_test_check

  ; ---- Phase 7: increasing-order absorption of 255 copies of 2^-25.
  MOVI r1,@mth_wsum_test_x
  MOVI r2,0
  MOVHI r2,0x3300            ; base 2^-25
  MOVI r3,@mth_wsum_test_x_p7
  MOVI r4,1
  CALL @mth_wsum_test_sparse
  MOVI r1,@mth_wsum_test_w
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x3F80
  CALL @mth_wsum_test_fill
  CALL @mth_wsum_test_call
  MOVI r5,0
  MOVHI r5,0x3F80            ; 1.0, not 1+2^-17
  CALL @mth_wsum_test_check

  ; ---- Phase 8: 1.0 + 2^-24 is an RNE tie that stays at 1.0.
  MOVI r1,@mth_wsum_test_x
  MOVI r2,0
  MOVI r3,@mth_wsum_test_x_two
  MOVI r4,2
  CALL @mth_wsum_test_sparse
  MOVI r1,@mth_wsum_test_w
  MOVI r2,0
  MOVI r3,@mth_wsum_test_w_tie
  MOVI r4,2
  CALL @mth_wsum_test_sparse
  CALL @mth_wsum_test_call
  MOVI r5,0
  MOVHI r5,0x3F80            ; 1.0
  CALL @mth_wsum_test_check

  ; ---- Phase 9: 1.0 + 3*2^-24 rounds up to 1+2^-22.
  MOVI r1,@mth_wsum_test_x
  MOVI r2,0
  MOVI r3,@mth_wsum_test_x_carry
  MOVI r4,2
  CALL @mth_wsum_test_sparse
  MOVI r1,@mth_wsum_test_w
  MOVI r2,0
  MOVI r3,@mth_wsum_test_w_tie
  MOVI r4,2
  CALL @mth_wsum_test_sparse
  CALL @mth_wsum_test_call
  MOVI r5,2                  ; 0x3F800002 = 1 + 2^-22
  MOVHI r5,0x3F80
  CALL @mth_wsum_test_check

  ; ---- Phase 10: (1+2^-23)^2 rounds to 1+2^-22.
  MOVI r1,@mth_wsum_test_x
  MOVI r2,0
  MOVI r3,@mth_wsum_test_x_round
  MOVI r4,1
  CALL @mth_wsum_test_sparse
  MOVI r1,@mth_wsum_test_w
  MOVI r2,0
  MOVI r3,@mth_wsum_test_w_round
  MOVI r4,1
  CALL @mth_wsum_test_sparse
  CALL @mth_wsum_test_call
  MOVI r5,2
  MOVHI r5,0x3F80
  CALL @mth_wsum_test_check

  ; ---- Phase 11: 256 min-subnormal products accumulate to 0x00000100.
  MOVI r1,@mth_wsum_test_x
  MOVI r2,256
  MOVI r4,1                  ; min positive subnormal
  CALL @mth_wsum_test_fill
  MOVI r1,@mth_wsum_test_w
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x3F80
  CALL @mth_wsum_test_fill
  CALL @mth_wsum_test_call
  MOVI r5,0x0100             ; 256 * 2^-149
  CALL @mth_wsum_test_check

  ; ---- Phase 12: +1 and -1 products cancel to +0.0.
  MOVI r1,@mth_wsum_test_x
  MOVI r2,0
  MOVHI r2,0x3F80            ; base 1.0
  MOVI r3,@mth_wsum_test_x_cancel
  MOVI r4,2
  CALL @mth_wsum_test_sparse
  MOVI r1,@mth_wsum_test_w
  MOVI r2,0                  ; base +0.0
  MOVI r3,@mth_wsum_test_w_cancel
  MOVI r4,2
  CALL @mth_wsum_test_sparse
  CALL @mth_wsum_test_call
  MOVI r5,0
  CALL @mth_wsum_test_check

  ; ---- Phase 13: the same sparse case plus a final +1 product -> 1.0.
  MOVI r1,@mth_wsum_test_x
  MOVI r2,0
  MOVHI r2,0x3F80
  MOVI r3,@mth_wsum_test_x_cancel3
  MOVI r4,3
  CALL @mth_wsum_test_sparse
  MOVI r1,@mth_wsum_test_w
  MOVI r2,0
  MOVI r3,@mth_wsum_test_w_cancel3
  MOVI r4,3
  CALL @mth_wsum_test_sparse
  CALL @mth_wsum_test_call
  MOVI r5,0
  MOVHI r5,0x3F80            ; 1.0
  CALL @mth_wsum_test_check

  ; ---- Phase 14: 2^-126 * 2^-2 underflows to 2^-128 and is preserved.
  MOVI r1,@mth_wsum_test_x
  MOVI r2,0
  MOVI r3,@mth_wsum_test_x_underflow
  MOVI r4,1
  CALL @mth_wsum_test_sparse
  MOVI r1,@mth_wsum_test_w
  MOVI r2,0
  MOVI r3,@mth_wsum_test_w_underflow
  MOVI r4,1
  CALL @mth_wsum_test_sparse
  CALL @mth_wsum_test_call
  MOVI r5,0
  MOVHI r5,0x0020            ; 2^-128 subnormal
  CALL @mth_wsum_test_check

  ; ---- Phase 15: quiet NaN x at 17, cause 1.
  MOVI r1,@mth_wsum_test_x
  MOVI r2,0
  MOVHI r2,0x3F80
  MOVI r3,@mth_wsum_test_x_bad_qnan
  MOVI r4,1
  CALL @mth_wsum_test_sparse
  MOVI r1,@mth_wsum_test_w
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x3F80
  CALL @mth_wsum_test_fill
  CALL @mth_wsum_test_sentinel
  CALL @mth_wsum_test_call
  MOVI r5,1
  CALL @mth_wsum_test_check_failure

  ; ---- Phase 16: +inf x at 200, cause 1.
  MOVI r1,@mth_wsum_test_x
  MOVI r2,0
  MOVHI r2,0x3F80
  MOVI r3,@mth_wsum_test_x_bad_pinf
  MOVI r4,1
  CALL @mth_wsum_test_sparse
  MOVI r1,@mth_wsum_test_w
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x3F80
  CALL @mth_wsum_test_fill
  CALL @mth_wsum_test_sentinel
  CALL @mth_wsum_test_call
  MOVI r5,1
  CALL @mth_wsum_test_check_failure

  ; ---- Phase 17: -inf x at 3, cause 1.
  MOVI r1,@mth_wsum_test_x
  MOVI r2,0
  MOVHI r2,0x3F80
  MOVI r3,@mth_wsum_test_x_bad_ninf
  MOVI r4,1
  CALL @mth_wsum_test_sparse
  MOVI r1,@mth_wsum_test_w
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x3F80
  CALL @mth_wsum_test_fill
  CALL @mth_wsum_test_sentinel
  CALL @mth_wsum_test_call
  MOVI r5,1
  CALL @mth_wsum_test_check_failure

  ; ---- Phase 18: quiet NaN w at 255, cause 2.
  MOVI r1,@mth_wsum_test_x
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x3F80
  CALL @mth_wsum_test_fill
  MOVI r1,@mth_wsum_test_w
  MOVI r2,0
  MOVHI r2,0x3F80
  MOVI r3,@mth_wsum_test_w_bad_qnan
  MOVI r4,1
  CALL @mth_wsum_test_sparse
  CALL @mth_wsum_test_sentinel
  CALL @mth_wsum_test_call
  MOVI r5,2
  CALL @mth_wsum_test_check_failure

  ; ---- Phase 19: +inf w at 0, cause 2.
  MOVI r1,@mth_wsum_test_x
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x3F80
  CALL @mth_wsum_test_fill
  MOVI r1,@mth_wsum_test_w
  MOVI r2,0
  MOVHI r2,0x3F80
  MOVI r3,@mth_wsum_test_w_bad_pinf
  MOVI r4,1
  CALL @mth_wsum_test_sparse
  CALL @mth_wsum_test_sentinel
  CALL @mth_wsum_test_call
  MOVI r5,2
  CALL @mth_wsum_test_check_failure

  ; ---- Phase 20: -inf w at 128, cause 2.
  MOVI r1,@mth_wsum_test_x
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x3F80
  CALL @mth_wsum_test_fill
  MOVI r1,@mth_wsum_test_w
  MOVI r2,0
  MOVHI r2,0x3F80
  MOVI r3,@mth_wsum_test_w_bad_ninf
  MOVI r4,1
  CALL @mth_wsum_test_sparse
  CALL @mth_wsum_test_sentinel
  CALL @mth_wsum_test_call
  MOVI r5,2
  CALL @mth_wsum_test_check_failure

  ; ---- Phase 21: bad x and bad w together report cause 1.
  MOVI r1,@mth_wsum_test_x
  MOVI r2,0
  MOVHI r2,0x3F80
  MOVI r3,@mth_wsum_test_x_both_bad
  MOVI r4,1
  CALL @mth_wsum_test_sparse
  MOVI r1,@mth_wsum_test_w
  MOVI r2,0
  MOVHI r2,0x3F80
  MOVI r3,@mth_wsum_test_w_both_bad
  MOVI r4,1
  CALL @mth_wsum_test_sparse
  CALL @mth_wsum_test_sentinel
  CALL @mth_wsum_test_call
  MOVI r5,1
  CALL @mth_wsum_test_check_failure

  ; ---- Phase 22: +inf x with w=+0.0 still rejects with cause 1.
  MOVI r1,@mth_wsum_test_x
  MOVI r2,0
  MOVHI r2,0x3F80
  MOVI r3,@mth_wsum_test_x_zero_w
  MOVI r4,1
  CALL @mth_wsum_test_sparse
  MOVI r1,@mth_wsum_test_w
  MOVI r2,256
  MOVI r4,0                  ; +0.0
  CALL @mth_wsum_test_fill
  CALL @mth_wsum_test_sentinel
  CALL @mth_wsum_test_call
  MOVI r5,1
  CALL @mth_wsum_test_check_failure

  ; ---- Phase 23: quiet NaN w with x=+0.0 rejects with cause 2.
  MOVI r1,@mth_wsum_test_x
  MOVI r2,256
  MOVI r4,0                  ; +0.0
  CALL @mth_wsum_test_fill
  MOVI r1,@mth_wsum_test_w
  MOVI r2,0
  MOVI r3,@mth_wsum_test_w_zero_x
  MOVI r4,1
  CALL @mth_wsum_test_sparse
  CALL @mth_wsum_test_sentinel
  CALL @mth_wsum_test_call
  MOVI r5,2
  CALL @mth_wsum_test_check_failure

  ; ---- Phase 24: +2^127 * 2.0 overflows the product, cause 3.
  MOVI r1,@mth_wsum_test_x
  MOVI r2,0
  MOVI r3,@mth_wsum_test_x_ovf
  MOVI r4,1
  CALL @mth_wsum_test_sparse
  MOVI r1,@mth_wsum_test_w
  MOVI r2,0
  MOVI r3,@mth_wsum_test_w_ovf
  MOVI r4,1
  CALL @mth_wsum_test_sparse
  CALL @mth_wsum_test_sentinel
  CALL @mth_wsum_test_call
  MOVI r5,3
  CALL @mth_wsum_test_check_failure

  ; ---- Phase 25: -2^127 * 2.0 overflows the product, cause 3.
  MOVI r1,@mth_wsum_test_x
  MOVI r2,0
  MOVI r3,@mth_wsum_test_x_negovf
  MOVI r4,1
  CALL @mth_wsum_test_sparse
  CALL @mth_wsum_test_sentinel
  CALL @mth_wsum_test_call
  MOVI r5,3
  CALL @mth_wsum_test_check_failure

  ; ---- Phase 26: two finite 2^127 products overflow the sum, cause 4.
  MOVI r1,@mth_wsum_test_x
  MOVI r2,0
  MOVI r3,@mth_wsum_test_x_sumovf
  MOVI r4,2
  CALL @mth_wsum_test_sparse
  MOVI r1,@mth_wsum_test_w
  MOVI r2,0
  MOVI r3,@mth_wsum_test_w_sumovf
  MOVI r4,2
  CALL @mth_wsum_test_sparse
  CALL @mth_wsum_test_sentinel
  CALL @mth_wsum_test_call
  MOVI r5,4
  CALL @mth_wsum_test_check_failure

  ; ---- Phase 27: two finite -2^127 products overflow the sum, cause 4.
  MOVI r1,@mth_wsum_test_x
  MOVI r2,0
  MOVI r3,@mth_wsum_test_x_sumnegovf
  MOVI r4,2
  CALL @mth_wsum_test_sparse
  MOVI r1,@mth_wsum_test_w
  MOVI r2,0
  MOVI r3,@mth_wsum_test_w_sumovf
  MOVI r4,2
  CALL @mth_wsum_test_sparse
  CALL @mth_wsum_test_sentinel
  CALL @mth_wsum_test_call
  MOVI r5,4
  CALL @mth_wsum_test_check_failure

  ; ---- Phase 28: recovery after all rejections.
  MOVI r1,@mth_wsum_test_x
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x4000
  CALL @mth_wsum_test_fill
  MOVI r1,@mth_wsum_test_w
  MOVI r2,256
  MOVI r4,0
  MOVHI r4,0x4040
  CALL @mth_wsum_test_fill
  CALL @mth_wsum_test_call
  MOVI r5,0
  MOVHI r5,0x44C0
  CALL @mth_wsum_test_check

  MOVI r1,@mth_wsum_test_pass
  CALL @mth_wsum_test_puts
  HALT

mth_wsum_test_fail:
  MOVI r1,@mth_wsum_test_bad
  CALL @mth_wsum_test_puts
  HALT

; Call the weighted-sum kernel on the fixture x/w/out spans and return r1.
; Saves the link register in r14; the kernel preserves r14.
mth_wsum_test_call:
  ADD r14,r15,r0
  MOVI r1,@mth_wsum_test_x
  MOVI r2,@mth_wsum_test_w
  MOVI r3,@mth_wsum_test_out
  CALL @mth_vector_weighted_sum256_f32
  ADD r15,r14,r0
  RET

; r1 = destination, r2 = count (positive), r4 = payload.
; Clobbers r1, r2.
mth_wsum_test_fill:
  ST r4,r1,0
  ADD r1,r1,r13
  SUB r2,r2,r13
  CMP r2,r0
  JMP[GT] @mth_wsum_test_fill
  RET

; r1 = destination, r2 = base payload, r3 = (index,payload) pairs,
; r4 = pair count. Fills 256 words with the base, then writes the pairs.
; Clobbers r1, r3, r4, r5, r7, r8, r9.
mth_wsum_test_sparse:
  ADD r7,r1,r0
  MOVI r5,256
mth_wsum_test_sparse_fill:
  ST r2,r1,0
  ADD r1,r1,r13
  SUB r5,r5,r13
  CMP r5,r0
  JMP[GT] @mth_wsum_test_sparse_fill
  CMP r4,r0
  JMP[EQ] @mth_wsum_test_sparse_done
mth_wsum_test_sparse_pairs:
  LD r8,r3,0
  ADD r3,r3,r13
  LD r9,r3,0
  ADD r3,r3,r13
  ADD r8,r7,r8
  ST r9,r8,0
  SUB r4,r4,r13
  CMP r4,r0
  JMP[GT] @mth_wsum_test_sparse_pairs
mth_wsum_test_sparse_done:
  RET

; r5 = expected payload. Requires r1=1, r9=0, out=r5.
; Clobbers r1, r6.
mth_wsum_test_check:
  CMP r1,r13
  JMP[NE] @mth_wsum_test_fail
  CMP r9,r0
  JMP[NE] @mth_wsum_test_fail
  MOVI r1,@mth_wsum_test_out
  LD r6,r1,0
  CMP r6,r5
  JMP[NE] @mth_wsum_test_fail
  RET

; r5 = expected cause. Requires r1=0, r9=r5, out=0xFFC0DEAD.
; Clobbers r1, r2, r6.
mth_wsum_test_check_failure:
  CMP r1,r0
  JMP[NE] @mth_wsum_test_fail
  CMP r9,r5
  JMP[NE] @mth_wsum_test_fail
  MOVI r1,@mth_wsum_test_out
  LD r2,r1,0
  MOVI r6,0xDEAD
  MOVHI r6,0xFFC0
  CMP r2,r6
  JMP[NE] @mth_wsum_test_fail
  RET

; Store 0xDEADBEEF into out. Clobbers r1, r4.
mth_wsum_test_sentinel:
  MOVI r1,@mth_wsum_test_out
  MOVI r4,0xBEEF
  MOVHI r4,0xDEAD
  ST r4,r1,0
  RET

mth_wsum_test_puts:
  MOVI r4,255
mth_wsum_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_wsum_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_wsum_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_wsum_test_puts_word

.org 1024
mth_wsum_test_x:
.word 0
.org 2048
mth_wsum_test_w:
.word 0
.org 3072
mth_wsum_test_out:
.word 0
.org 4096
mth_wsum_test_x_p7:
.word 0,0x3F800000        ; x[0] = 1.0
mth_wsum_test_x_two:
.word 0,0x3F800000        ; x[0] = 1.0
.word 1,0x3F800000        ; x[1] = 1.0
mth_wsum_test_x_carry:
.word 0,0x3F800000        ; x[0] = 1.0
.word 1,0x40400000        ; x[1] = 3.0
mth_wsum_test_x_round:
.word 0,0x3F800001        ; 1 + 2^-23
mth_wsum_test_x_cancel:
.word 0,0x40000000        ; x[0] = 2.0
.word 100,0xC0800000      ; x[100] = -4.0
mth_wsum_test_x_cancel3:
.word 0,0x40000000        ; x[0] = 2.0
.word 100,0xC0800000      ; x[100] = -4.0
.word 255,0x41000000      ; x[255] = 8.0
mth_wsum_test_x_underflow:
.word 0,0x00800000        ; 2^-126
mth_wsum_test_x_bad_qnan:
.word 17,0x7FC00123       ; quiet NaN
mth_wsum_test_x_bad_pinf:
.word 200,0x7F800000      ; +inf
mth_wsum_test_x_bad_ninf:
.word 3,0xFF800000        ; -inf
mth_wsum_test_x_both_bad:
.word 10,0x7FC00123       ; quiet NaN
mth_wsum_test_x_zero_w:
.word 40,0x7F800000       ; +inf where w[40] = +0.0
mth_wsum_test_x_ovf:
.word 0,0x7F000000        ; +2^127
mth_wsum_test_x_negovf:
.word 0,0xFF000000        ; -2^127
mth_wsum_test_x_sumovf:
.word 0,0x7F000000        ; +2^127
.word 1,0x7F000000        ; +2^127
mth_wsum_test_x_sumnegovf:
.word 0,0xFF000000        ; -2^127
.word 1,0xFF000000        ; -2^127
mth_wsum_test_w_tie:
.word 0,0x3F800000        ; w[0] = 1.0
.word 1,0x33800000        ; w[1] = 2^-24
mth_wsum_test_w_round:
.word 0,0x3F800001        ; 1 + 2^-23
mth_wsum_test_w_cancel:
.word 0,0x3F000000        ; w[0] = 0.5
.word 100,0x3E800000      ; w[100] = 0.25
mth_wsum_test_w_cancel3:
.word 0,0x3F000000        ; w[0] = 0.5
.word 100,0x3E800000      ; w[100] = 0.25
.word 255,0x3E000000      ; w[255] = 0.125
mth_wsum_test_w_underflow:
.word 0,0x3E800000        ; 2^-2
mth_wsum_test_w_bad_qnan:
.word 255,0x7FC00123      ; quiet NaN
mth_wsum_test_w_bad_pinf:
.word 0,0x7F800000        ; +inf
mth_wsum_test_w_bad_ninf:
.word 128,0xFF800000      ; -inf
mth_wsum_test_w_both_bad:
.word 20,0x7FC00123       ; quiet NaN
mth_wsum_test_w_zero_x:
.word 40,0x7FC00123       ; quiet NaN where x[40] = +0.0
mth_wsum_test_w_ovf:
.word 0,0x40000000        ; 2.0
mth_wsum_test_w_sumovf:
.word 0,0x3F800000        ; 1.0
.word 1,0x3F800000        ; 1.0
.org 8192
mth_wsum_test_pass:
.str "MTH VECTOR WEIGHTED SUM256 F32 PASS\n"
mth_wsum_test_bad:
.str "MTH VECTOR WEIGHTED SUM256 F32 FAIL\n"
