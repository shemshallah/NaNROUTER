; MTH retrieval top-1 fixture — NaN16 only.
;
; Phases:
;   1. count=1, 7.5 at index 0; sNaN at index 1 lies beyond count and must be
;      ignored.
;   2. count=2 ascending 1.0, 2.0; +inf at index 2 lies beyond count.
;   3. count=2 descending 4.0, -1.0; -inf at index 2 lies beyond count.
;   4. count=12 ascending 0.0..11.0; index 11 wins.
;   5. count=12 descending 12.0..1.0; index 0 wins.
;   6. count=12 maximum tie at indices 3, 7, 10; index 3 wins.
;   7. count=12 all equal 3.25; index 0 wins.
;   8. count=12, -0.0 first at index 2 then +0.0 at 5; index 2 and the exact
;      -0.0 payload win.
;   9. count=12, +0.0 first at index 2 then -0.0 at 5; index 2 and the exact
;      +0.0 payload win.
;  10. sNaN at index 5: rejection, output registers untouched.
;  11. quiet negative NaN at index 11: rejection, outputs untouched.
;  12. +inf at index 0: rejection, outputs untouched.
;  13. -inf at index 11: rejection, outputs untouched.
;  14. count=0: rejection, outputs untouched.
;  15. count=13: rejection, outputs untouched.
;  16. count=0xFFFFFFFF: rejection, outputs untouched.
;  17. recovery after rejection: count=12 ascending returns index 11 again.
;
; Every expected value is an IEEE binary32 payload constant checked by native
; integer CMP. No host math is used. Output sentinels are distinct so a
; rejected call must leave both r3 and r4 exactly as the caller set them.

.org 0
JMP @mth_retrieval_top1_test_main
.include "../nan16/mth_retrieval_top1.nas"

mth_retrieval_top1_test_main:
  MOVI r13,1

  ; ---- Phase 1: one candidate; poison beyond count.
  MOVI r1,0
  MOVHI r1,0xC080            ; -4.0 baseline
  CALL @mth_retrieval_test_fill_all
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x40F0            ; 7.5
  CALL @mth_retrieval_test_set
  MOVI r1,1
  MOVI r2,1
  MOVHI r2,0x7F80            ; 0x7F800001 signaling NaN
  CALL @mth_retrieval_test_set
  MOVI r1,1                  ; count = 1
  CALL @mth_retrieval_test_call
  CMP r1,r13
  JMP[NE] @mth_retrieval_top1_test_fail
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x40F0            ; 7.5
  CALL @mth_retrieval_test_check_result

  ; ---- Phase 2: two candidates ascending; +inf beyond count.
  MOVI r1,0
  MOVHI r1,0xBF80            ; -1.0 baseline
  CALL @mth_retrieval_test_fill_all
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x3F80            ; 1.0
  CALL @mth_retrieval_test_set
  MOVI r1,1
  MOVI r2,0
  MOVHI r2,0x4000            ; 2.0
  CALL @mth_retrieval_test_set
  MOVI r1,2
  MOVI r2,0
  MOVHI r2,0x7F80            ; +inf beyond count
  CALL @mth_retrieval_test_set
  MOVI r1,2                  ; count = 2
  CALL @mth_retrieval_test_call
  CMP r1,r13
  JMP[NE] @mth_retrieval_top1_test_fail
  MOVI r1,1
  MOVI r2,0
  MOVHI r2,0x4000            ; 2.0
  CALL @mth_retrieval_test_check_result

  ; ---- Phase 3: two candidates descending; -inf beyond count.
  MOVI r1,0
  MOVHI r1,0xC000            ; -2.0 baseline
  CALL @mth_retrieval_test_fill_all
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x4080            ; 4.0
  CALL @mth_retrieval_test_set
  MOVI r1,1
  MOVI r2,0
  MOVHI r2,0xBF80            ; -1.0
  CALL @mth_retrieval_test_set
  MOVI r1,2
  MOVI r2,0
  MOVHI r2,0xFF80            ; -inf beyond count
  CALL @mth_retrieval_test_set
  MOVI r1,2                  ; count = 2
  CALL @mth_retrieval_test_call
  CMP r1,r13
  JMP[NE] @mth_retrieval_top1_test_fail
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x4080            ; 4.0
  CALL @mth_retrieval_test_check_result

  ; ---- Phase 4: all twelve candidates ascending; index 11 wins.
  CALL @mth_retrieval_test_fill_ascending
  MOVI r1,12
  CALL @mth_retrieval_test_call
  CMP r1,r13
  JMP[NE] @mth_retrieval_top1_test_fail
  MOVI r1,11
  MOVI r2,0
  MOVHI r2,0x4130            ; 11.0
  CALL @mth_retrieval_test_check_result

  ; ---- Phase 5: all twelve candidates descending; index 0 wins.
  CALL @mth_retrieval_test_fill_descending
  MOVI r1,12
  CALL @mth_retrieval_test_call
  CMP r1,r13
  JMP[NE] @mth_retrieval_top1_test_fail
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x4140            ; 12.0
  CALL @mth_retrieval_test_check_result

  ; ---- Phase 6: maximum tie at 3, 7, 10; first index wins.
  MOVI r1,0
  MOVHI r1,0xC000            ; -2.0 baseline
  CALL @mth_retrieval_test_fill_all
  MOVI r1,3
  MOVI r2,0
  MOVHI r2,0x40A0            ; 5.0
  CALL @mth_retrieval_test_set
  MOVI r1,7
  MOVI r2,0
  MOVHI r2,0x40A0            ; 5.0
  CALL @mth_retrieval_test_set
  MOVI r1,10
  MOVI r2,0
  MOVHI r2,0x40A0            ; 5.0
  CALL @mth_retrieval_test_set
  MOVI r1,12
  CALL @mth_retrieval_test_call
  CMP r1,r13
  JMP[NE] @mth_retrieval_top1_test_fail
  MOVI r1,3
  MOVI r2,0
  MOVHI r2,0x40A0            ; 5.0
  CALL @mth_retrieval_test_check_result

  ; ---- Phase 7: all equal; index 0 and its payload win.
  MOVI r1,0
  MOVHI r1,0x4050            ; 3.25
  CALL @mth_retrieval_test_fill_all
  MOVI r1,12
  CALL @mth_retrieval_test_call
  CMP r1,r13
  JMP[NE] @mth_retrieval_top1_test_fail
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x4050            ; 3.25
  CALL @mth_retrieval_test_check_result

  ; ---- Phase 8: -0.0 first at index 2, +0.0 at index 5.
  MOVI r1,0
  MOVHI r1,0xBF80            ; -1.0 baseline
  CALL @mth_retrieval_test_fill_all
  MOVI r1,2
  MOVI r2,0
  MOVHI r2,0x8000            ; -0.0
  CALL @mth_retrieval_test_set
  MOVI r1,5
  ADD r2,r0,r0               ; +0.0
  CALL @mth_retrieval_test_set
  MOVI r1,12
  CALL @mth_retrieval_test_call
  CMP r1,r13
  JMP[NE] @mth_retrieval_top1_test_fail
  MOVI r1,2
  MOVI r2,0
  MOVHI r2,0x8000            ; -0.0
  CALL @mth_retrieval_test_check_result

  ; ---- Phase 9: +0.0 first at index 2, -0.0 at index 5.
  MOVI r1,0
  MOVHI r1,0xBF80            ; -1.0 baseline
  CALL @mth_retrieval_test_fill_all
  MOVI r1,2
  ADD r2,r0,r0               ; +0.0
  CALL @mth_retrieval_test_set
  MOVI r1,5
  MOVI r2,0
  MOVHI r2,0x8000            ; -0.0
  CALL @mth_retrieval_test_set
  MOVI r1,12
  CALL @mth_retrieval_test_call
  CMP r1,r13
  JMP[NE] @mth_retrieval_top1_test_fail
  MOVI r1,2
  ADD r2,r0,r0               ; +0.0
  CALL @mth_retrieval_test_check_result

  ; ---- Phase 10: signaling NaN at index 5 rejects atomically.
  CALL @mth_retrieval_test_fill_ascending
  MOVI r1,5
  MOVI r2,1
  MOVHI r2,0x7F80            ; 0x7F800001 sNaN
  CALL @mth_retrieval_test_set
  MOVI r1,12
  CALL @mth_retrieval_test_call
  CALL @mth_retrieval_test_check_reject

  ; ---- Phase 11: quiet negative NaN at index 11 rejects atomically.
  CALL @mth_retrieval_test_fill_ascending
  MOVI r1,11
  MOVI r2,0
  MOVHI r2,0xFFC0            ; 0xFFC00000 qNaN
  CALL @mth_retrieval_test_set
  MOVI r1,12
  CALL @mth_retrieval_test_call
  CALL @mth_retrieval_test_check_reject

  ; ---- Phase 12: +inf at index 0 rejects atomically.
  CALL @mth_retrieval_test_fill_ascending
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x7F80            ; +inf
  CALL @mth_retrieval_test_set
  MOVI r1,12
  CALL @mth_retrieval_test_call
  CALL @mth_retrieval_test_check_reject

  ; ---- Phase 13: -inf at index 11 rejects atomically.
  CALL @mth_retrieval_test_fill_ascending
  MOVI r1,11
  MOVI r2,0
  MOVHI r2,0xFF80            ; -inf
  CALL @mth_retrieval_test_set
  MOVI r1,12
  CALL @mth_retrieval_test_call
  CALL @mth_retrieval_test_check_reject

  ; ---- Phase 14: count 0 rejects atomically.
  CALL @mth_retrieval_test_fill_ascending
  MOVI r1,0
  CALL @mth_retrieval_test_call
  CALL @mth_retrieval_test_check_reject

  ; ---- Phase 15: count 13 rejects atomically.
  CALL @mth_retrieval_test_fill_ascending
  MOVI r1,13
  CALL @mth_retrieval_test_call
  CALL @mth_retrieval_test_check_reject

  ; ---- Phase 16: count 0xFFFFFFFF rejects atomically.
  CALL @mth_retrieval_test_fill_ascending
  MOVI r1,0xFFFF
  MOVHI r1,0xFFFF
  CALL @mth_retrieval_test_call
  CALL @mth_retrieval_test_check_reject

  ; ---- Phase 17: recovery after all rejection cases.
  CALL @mth_retrieval_test_fill_ascending
  MOVI r1,12
  CALL @mth_retrieval_test_call
  CMP r1,r13
  JMP[NE] @mth_retrieval_top1_test_fail
  MOVI r1,11
  MOVI r2,0
  MOVHI r2,0x4130            ; 11.0
  CALL @mth_retrieval_test_check_result

  LA r1,@mth_retrieval_top1_test_pass
  CALL @mth_retrieval_test_puts
  HALT

mth_retrieval_top1_test_fail:
  LA r1,@mth_retrieval_top1_test_bad
  CALL @mth_retrieval_test_puts
  HALT

; ---- Helpers ------------------------------------------------------------

; Fill all twelve score slots with the payload in r1.
; Clobbers r1-r4 and flags.
mth_retrieval_test_fill_all:
  LA r2,@mth_retrieval_test_x
  MOVI r3,0
  MOVI r4,12
mth_retrieval_test_fill_all_loop:
  ST r1,r2,0
  ADD r2,r2,r13
  ADD r3,r3,r13
  CMP r3,r4
  JMP[LT] @mth_retrieval_test_fill_all_loop
  RET

; Fill x[i] = (float32)i for i = 0..11. Clobbers r1-r4 and flags.
mth_retrieval_test_fill_ascending:
  LA r1,@mth_retrieval_test_x
  MOVI r2,0
  MOVI r4,12
mth_retrieval_test_fill_ascending_loop:
  CVTIF r3,r2
  ST r3,r1,0
  ADD r1,r1,r13
  ADD r2,r2,r13
  CMP r2,r4
  JMP[LT] @mth_retrieval_test_fill_ascending_loop
  RET

; Fill x[i] = (float32)(12-i) for i = 0..11.
; Clobbers r1-r5 and flags.
mth_retrieval_test_fill_descending:
  LA r1,@mth_retrieval_test_x
  MOVI r2,0
  MOVI r4,12
  MOVI r5,12
mth_retrieval_test_fill_descending_loop:
  SUB r3,r5,r2
  CVTIF r3,r3
  ST r3,r1,0
  ADD r1,r1,r13
  ADD r2,r2,r13
  CMP r2,r4
  JMP[LT] @mth_retrieval_test_fill_descending_loop
  RET

; r1 = index, r2 = payload. Store x[r1] = r2. Clobbers r3 and flags.
mth_retrieval_test_set:
  LA r3,@mth_retrieval_test_x
  ADD r3,r3,r1
  ST r2,r3,0
  RET

; r1 = count. Point r1 at x, install distinct output sentinels in r3/r4,
; call the kernel, and return its r1 status. Clobbers r1-r4 and flags.
mth_retrieval_test_call:
  ADD r14,r15,r0
  ADD r2,r1,r0
  LA r1,@mth_retrieval_test_x
  MOVI r3,0xBEEF
  MOVHI r3,0xDEAD            ; r3 sentinel = 0xDEADBEEF
  MOVI r4,0xFACE
  MOVHI r4,0xFEED            ; r4 sentinel = 0xFEEDFACE
  CALL @mth_retrieval_top1_f32
  ADD r15,r14,r0
  RET

; r1 = expected index, r2 = expected score payload.
; Jumps to the fail label on mismatch. Clobbers flags only.
mth_retrieval_test_check_result:
  CMP r3,r1
  JMP[NE] @mth_retrieval_top1_test_fail
  CMP r4,r2
  JMP[NE] @mth_retrieval_top1_test_fail
  RET

; Require r1=0 and both output sentinels unchanged. Clobbers r5 and flags.
mth_retrieval_test_check_reject:
  CMP r1,r0
  JMP[NE] @mth_retrieval_top1_test_fail
  MOVI r5,0xBEEF
  MOVHI r5,0xDEAD
  CMP r3,r5
  JMP[NE] @mth_retrieval_top1_test_fail
  MOVI r5,0xFACE
  MOVHI r5,0xFEED
  CMP r4,r5
  JMP[NE] @mth_retrieval_top1_test_fail
  RET

mth_retrieval_test_puts:
  MOVI r4,255
mth_retrieval_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_retrieval_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_retrieval_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_retrieval_test_puts_word

.org 1024
mth_retrieval_test_x:
.word 0,0,0,0,0,0,0,0,0,0,0,0
.org 2048
mth_retrieval_top1_test_pass:
.str "MTH RETRIEVAL TOP1 PASS\n"
mth_retrieval_top1_test_bad:
.str "MTH RETRIEVAL TOP1 FAIL\n"
