; MTH byte-fallback argmax fixture — NaN16 only.
;
; Phases:
;   1. all-zero scores: index 0, payload +0.0.
;   2. ramp x[i] = (float)(i - 128): distinct maximum at index 255 (127.0).
;   3. maximum at index 0 (5.0) over a -1.0 field.
;   4. maximum at index 255 (9.0) over a -1.0 field.
;   5. maximum tie at 10, 77, 200 (5.0): first index 10 wins.
;   6. maximum tie at both endpoints 0 and 255 (7.0): index 0 wins.
;   7. signed-zero tie, -0.0 first at index 3, +0.0 at 100: index 3 and
;      the exact -0.0 payload win.
;   8. signed-zero tie, +0.0 first at index 3, -0.0 at 100: index 3 and
;      the exact +0.0 payload win.
;   9. quiet NaN at index 0: atomic rejection with cause 1.
;  10. signaling NaN at index 255: atomic rejection with cause 1.
;  11. +inf at index 0: atomic rejection with cause 1.
;  12. -inf at index 255: atomic rejection with cause 1.
;  13. recovery ramp after all rejections: index 255 (127.0) again.
;
; Every call poisons the output word with 0x3CC35AA5. On success only byte 0
; may change (to the selected index); bytes 1..3 must remain 0x5A, 0xC3,
; 0x3C. On rejection the whole word must remain 0x3CC35AA5, and r3/r4 must
; keep their pre-call sentinels. All expected values are native IEEE binary32
; payload integers; no host math is used.

.org 0
JMP @mth_bfa_test_main
.include "../nan16/mth_byte_fallback_argmax.nas"

mth_bfa_test_main:
  MOVI r13,1

  ; Phase 1: all scores +0.0; index 0 and payload +0.0 win.
  MOVI r1,0
  CALL @mth_bfa_test_fill_value
  CALL @mth_bfa_test_poison
  CALL @mth_bfa_test_call
  CMP r1,r13
  JMP[NE] @mth_bfa_test_fail
  MOVI r1,0
  MOVI r2,0
  CALL @mth_bfa_test_check_result

  ; Phase 2: ramp with distinct maximum at index 255, value 127.0.
  CALL @mth_bfa_test_fill_iota
  CALL @mth_bfa_test_poison
  CALL @mth_bfa_test_call
  CMP r1,r13
  JMP[NE] @mth_bfa_test_fail
  MOVI r1,255
  MOVI r2,0
  MOVHI r2,0x42FE            ; 127.0
  CALL @mth_bfa_test_check_result

  ; Phase 3: -1.0 field with maximum 5.0 at index 0.
  MOVI r1,0
  MOVHI r1,0xBF80            ; -1.0 baseline
  CALL @mth_bfa_test_fill_value
  LA r5,@mth_bfa_test_x
  MOVI r6,0
  MOVHI r6,0x40A0            ; 5.0
  ST r6,r5,0
  CALL @mth_bfa_test_poison
  CALL @mth_bfa_test_call
  CMP r1,r13
  JMP[NE] @mth_bfa_test_fail
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x40A0            ; 5.0
  CALL @mth_bfa_test_check_result

  ; Phase 4: -1.0 field with maximum 9.0 at index 255.
  MOVI r1,0
  MOVHI r1,0xBF80            ; -1.0 baseline
  CALL @mth_bfa_test_fill_value
  LA r5,@mth_bfa_test_x
  MOVI r6,0
  MOVHI r6,0x4110            ; 9.0
  ST r6,r5,255
  CALL @mth_bfa_test_poison
  CALL @mth_bfa_test_call
  CMP r1,r13
  JMP[NE] @mth_bfa_test_fail
  MOVI r1,255
  MOVI r2,0
  MOVHI r2,0x4110            ; 9.0
  CALL @mth_bfa_test_check_result

  ; Phase 5: maximum tie at 10, 77, 200 (5.0); first index 10 wins.
  MOVI r1,0
  MOVHI r1,0xBF80            ; -1.0 baseline
  CALL @mth_bfa_test_fill_value
  LA r5,@mth_bfa_test_x
  MOVI r6,0
  MOVHI r6,0x40A0            ; 5.0
  ST r6,r5,10
  ST r6,r5,77
  ST r6,r5,200
  MOVI r6,0
  MOVHI r6,0x4080            ; 4.0, below the tie
  ST r6,r5,255
  CALL @mth_bfa_test_poison
  CALL @mth_bfa_test_call
  CMP r1,r13
  JMP[NE] @mth_bfa_test_fail
  MOVI r1,10
  MOVI r2,0
  MOVHI r2,0x40A0            ; 5.0
  CALL @mth_bfa_test_check_result

  ; Phase 6: endpoints tie at 7.0; index 0 wins.
  MOVI r1,0
  MOVHI r1,0xC000            ; -2.0 baseline
  CALL @mth_bfa_test_fill_value
  LA r5,@mth_bfa_test_x
  MOVI r6,0
  MOVHI r6,0x40E0            ; 7.0
  ST r6,r5,0
  ST r6,r5,255
  CALL @mth_bfa_test_poison
  CALL @mth_bfa_test_call
  CMP r1,r13
  JMP[NE] @mth_bfa_test_fail
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x40E0            ; 7.0
  CALL @mth_bfa_test_check_result

  ; Phase 7: -0.0 at 3 and +0.0 at 100, both above -1.0. They tie, so
  ; index 3 wins and the exact -0.0 payload (0x80000000) is returned.
  MOVI r1,0
  MOVHI r1,0xBF80            ; -1.0 baseline
  CALL @mth_bfa_test_fill_value
  LA r5,@mth_bfa_test_x
  MOVI r6,0
  MOVHI r6,0x8000            ; -0.0
  ST r6,r5,3
  ST r0,r5,100               ; +0.0
  CALL @mth_bfa_test_poison
  CALL @mth_bfa_test_call
  CMP r1,r13
  JMP[NE] @mth_bfa_test_fail
  MOVI r1,3
  MOVI r2,0
  MOVHI r2,0x8000            ; -0.0
  CALL @mth_bfa_test_check_result

  ; Phase 8: swap the zero signs. +0.0 at 3 is still first, wins the tie,
  ; and its exact +0.0 payload (0x00000000) is returned.
  LA r5,@mth_bfa_test_x
  ST r0,r5,3                 ; +0.0
  MOVI r6,0
  MOVHI r6,0x8000            ; -0.0
  ST r6,r5,100
  CALL @mth_bfa_test_poison
  CALL @mth_bfa_test_call
  CMP r1,r13
  JMP[NE] @mth_bfa_test_fail
  MOVI r1,3
  MOVI r2,0
  CALL @mth_bfa_test_check_result

  ; Phase 9: quiet NaN at the first index. Atomic rejection.
  CALL @mth_bfa_test_fill_iota
  LA r5,@mth_bfa_test_x
  MOVI r6,0
  MOVHI r6,0x7FC0            ; 0x7FC00000 qNaN
  ST r6,r5,0
  CALL @mth_bfa_test_poison
  CALL @mth_bfa_test_call
  CALL @mth_bfa_test_check_reject

  ; Phase 10: signaling NaN at the last index. Atomic rejection.
  CALL @mth_bfa_test_fill_iota
  LA r5,@mth_bfa_test_x
  MOVI r6,1
  MOVHI r6,0x7F80            ; 0x7F800001 sNaN
  ST r6,r5,255
  CALL @mth_bfa_test_poison
  CALL @mth_bfa_test_call
  CALL @mth_bfa_test_check_reject

  ; Phase 11: +inf at the first index. Atomic rejection.
  CALL @mth_bfa_test_fill_iota
  LA r5,@mth_bfa_test_x
  MOVI r6,0
  MOVHI r6,0x7F80            ; +inf
  ST r6,r5,0
  CALL @mth_bfa_test_poison
  CALL @mth_bfa_test_call
  CALL @mth_bfa_test_check_reject

  ; Phase 12: -inf at the last index. Atomic rejection.
  CALL @mth_bfa_test_fill_iota
  LA r5,@mth_bfa_test_x
  MOVI r6,0
  MOVHI r6,0xFF80            ; -inf
  ST r6,r5,255
  CALL @mth_bfa_test_poison
  CALL @mth_bfa_test_call
  CALL @mth_bfa_test_check_reject

  ; Phase 13: recovery after all rejections.
  CALL @mth_bfa_test_fill_iota
  CALL @mth_bfa_test_poison
  CALL @mth_bfa_test_call
  CMP r1,r13
  JMP[NE] @mth_bfa_test_fail
  MOVI r1,255
  MOVI r2,0
  MOVHI r2,0x42FE            ; 127.0
  CALL @mth_bfa_test_check_result

  LA r1,@mth_bfa_test_pass
  CALL @mth_bfa_test_puts
  HALT

mth_bfa_test_fail:
  LA r1,@mth_bfa_test_bad
  CALL @mth_bfa_test_puts
  HALT

; Call the kernel on the fixture score span and output byte. Preloads r3, r4,
; and r9 with sentinels so success must overwrite them and rejection must not.
; Preserves no caller state except the link register via r14. Clobbers
; r1-r4, r9, r14 and the flags.
mth_bfa_test_call:
  ADD r14,r15,r0
  LA r1,@mth_bfa_test_x
  MOVI r2,@mth_bfa_test_out
  SHL r2,r2,2                ; payload byte address
  MOVI r3,0x1111
  MOVHI r3,0x1111            ; 0x11111111 sentinel
  MOVI r4,0x2222
  MOVHI r4,0x2222            ; 0x22222222 sentinel
  MOVI r9,0xDEAD             ; sentinel; kernel must publish 0 or 1
  CALL @mth_byte_fallback_argmax
  ADD r15,r14,r0
  RET

; r1 = expected index, r2 = expected score payload. Requires r1(status)=1,
; r3/r4 from the kernel, r9=0, byte 0 equal to the index, and guard bytes
; 1..3 still 0x5A/0xC3/0x3C from the 0x3CC35AA5 poison word. Jumps to fail on
; any mismatch. Clobbers r5-r7 and the flags.
mth_bfa_test_check_result:
  CMP r3,r1
  JMP[NE] @mth_bfa_test_fail
  CMP r4,r2
  JMP[NE] @mth_bfa_test_fail
  CMP r9,r0
  JMP[NE] @mth_bfa_test_fail
  MOVI r5,@mth_bfa_test_out
  SHL r5,r5,2                ; payload byte address
  LDB r6,r5,0
  CMP r6,r1
  JMP[NE] @mth_bfa_test_fail
  MOVI r7,0x5A
  LDB r6,r5,1
  CMP r6,r7
  JMP[NE] @mth_bfa_test_fail
  MOVI r7,0xC3
  LDB r6,r5,2
  CMP r6,r7
  JMP[NE] @mth_bfa_test_fail
  MOVI r7,0x3C
  LDB r6,r5,3
  CMP r6,r7
  JMP[NE] @mth_bfa_test_fail
  RET

; Requires an atomic rejection: status 0, cause 1, r3/r4 sentinels unchanged,
; and the whole poisoned output word unchanged. Jumps to fail on mismatch.
; Clobbers r5-r7 and the flags.
mth_bfa_test_check_reject:
  CMP r1,r0
  JMP[NE] @mth_bfa_test_fail
  CMP r9,r13
  JMP[NE] @mth_bfa_test_fail
  MOVI r5,0x1111
  MOVHI r5,0x1111
  CMP r3,r5
  JMP[NE] @mth_bfa_test_fail
  MOVI r5,0x2222
  MOVHI r5,0x2222
  CMP r4,r5
  JMP[NE] @mth_bfa_test_fail
  MOVI r5,@mth_bfa_test_out
  LD r6,r5,0
  MOVI r7,0x5AA5
  MOVHI r7,0x3CC3            ; 0x3CC35AA5 poison word
  CMP r6,r7
  JMP[NE] @mth_bfa_test_fail
  RET

; Fill scores[0..255] with the payload in r1. Preserves r1; clobbers r2-r4.
mth_bfa_test_fill_value:
  LA r2,@mth_bfa_test_x
  MOVI r3,0
  MOVI r4,256
mth_bfa_test_fill_value_loop:
  ST r1,r2,0
  ADD r2,r2,r13
  ADD r3,r3,r13
  CMP r3,r4
  JMP[LT] @mth_bfa_test_fill_value_loop
  RET

; Fill scores[i] = (float32)(i - 128) for i=0..255. Clobbers r1-r4.
mth_bfa_test_fill_iota:
  LA r1,@mth_bfa_test_x
  MOVI r2,0
mth_bfa_test_fill_iota_loop:
  MOVI r3,128
  SUB r4,r2,r3
  CVTIF r4,r4
  ST r4,r1,0
  ADD r1,r1,r13
  ADD r2,r2,r13
  MOVI r3,256
  CMP r2,r3
  JMP[LT] @mth_bfa_test_fill_iota_loop
  RET

; Poison the output word with 0x3CC35AA5 (bytes A5,5A,C3,3C). Clobbers r5-r6.
mth_bfa_test_poison:
  MOVI r5,0x5AA5
  MOVHI r5,0x3CC3
  MOVI r6,@mth_bfa_test_out
  ST r5,r6,0
  RET

mth_bfa_test_puts:
  MOVI r4,255
mth_bfa_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_bfa_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_bfa_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_bfa_test_puts_word

.org 1024
mth_bfa_test_x:
.word 0

.org 1280
mth_bfa_test_out:
.word 0

.org 1536
mth_bfa_test_pass:
.str "MTH BYTE FALLBACK ARGMAX PASS\n"
mth_bfa_test_bad:
.str "MTH BYTE FALLBACK ARGMAX FAIL\n"
