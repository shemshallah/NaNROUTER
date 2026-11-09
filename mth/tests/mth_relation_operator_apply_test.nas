; MTH bounded scalar relation-operator application fixture — native NaN16 only.
;
; In-guest coverage, no host arithmetic and no external oracle:
;   1. all eight operator codes 1..8 with exact binary32 score bits;
;   2. code 1/2 min/max equality boundaries and code 6/8 zero-gap boundaries;
;   3. code 6 and code 8 checked with both operand orders, so a mistaken
;      mapping to the directed code 3 or code 5 difference is detected;
;   4. confidence endpoints +0.0, -0.0, and +1.0, including IEEE signed-zero
;      output at zero confidence and an unclamped score above one;
;   5. unknown operator codes 0, 9, and 0xFFFFFFFF reject atomically;
;   6. non-finite left, right, and confidence (NaN and infinity) reject
;      atomically with the documented field cause;
;   7. confidence outside [0,1] rejects rather than clamping, including the
;      smallest negative subnormal and the first binary32 value above 1.0;
;   8. a finite-input score overflow rejects atomically, and zero confidence
;      does not mask an intermediate infinity (0 * Inf is an invalid result);
;   9. every success returns r1=1, r9=0; every rejection returns r1=0 with
;      the documented r9 cause and leaves the output sentinel unchanged.
;
; The output slot is one NaN16 payload word addressed by byte as label<<2.
; The kernel stores only its four little-endian f32 bytes after all checks.
;
; The fixture marker is "MTH RELATION OPERATOR APPLY PASS".

.org 0
JMP @mth_ro_test_main
.include "../nan16/mth_relation_operator_apply.nas"

mth_ro_test_main:
  MOVI r0,0
  MOVI r13,1

  ; ================= code 1: is_a = min(L,R) * C =================
  MOVI r7,1
  MOVI r8,0
  MOVHI r8,0x4060            ; L = +3.5
  MOVI r9,0
  MOVHI r9,0x3FA0            ; R = +1.25
  MOVI r10,0
  MOVHI r10,0x3F00           ; C = +0.5
  MOVI r11,0
  MOVHI r11,0x3F20           ; expected +0.625
  CALL @mth_ro_test_expect_ok
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_1

  ; min equality boundary: min(2,2) * 1 = 2.
  MOVI r7,1
  MOVI r8,0
  MOVHI r8,0x4000            ; L = +2.0
  MOVI r9,0
  MOVHI r9,0x4000            ; R = +2.0
  MOVI r10,0
  MOVHI r10,0x3F80           ; C = +1.0
  MOVI r11,0
  MOVHI r11,0x4000           ; expected +2.0
  CALL @mth_ro_test_expect_ok
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_1

  ; ================= code 2: part_of = max(L,R) * C =================
  MOVI r7,2
  MOVI r8,0
  MOVHI r8,0x4060            ; L = +3.5
  MOVI r9,0
  MOVHI r9,0x3FA0            ; R = +1.25
  MOVI r10,0
  MOVHI r10,0x3F00           ; C = +0.5
  MOVI r11,0
  MOVHI r11,0x3FE0           ; expected +1.75
  CALL @mth_ro_test_expect_ok
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_2

  ; max equality boundary: max(2,2) * 1 = 2.
  MOVI r7,2
  MOVI r8,0
  MOVHI r8,0x4000
  MOVI r9,0
  MOVHI r9,0x4000
  MOVI r10,0
  MOVHI r10,0x3F80
  MOVI r11,0
  MOVHI r11,0x4000
  CALL @mth_ro_test_expect_ok
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_2

  ; ================= code 3: causes = (L-R) * C =================
  MOVI r7,3
  MOVI r8,0
  MOVHI r8,0x4060            ; L = +3.5
  MOVI r9,0
  MOVHI r9,0x3FA0            ; R = +1.25
  MOVI r10,0
  MOVHI r10,0x3F00           ; C = +0.5
  MOVI r11,0
  MOVHI r11,0x3F90           ; expected +1.125
  CALL @mth_ro_test_expect_ok
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_3

  ; confidence +1.0: (3.5 - 1.25) * 1 = 2.25.
  MOVI r7,3
  MOVI r8,0
  MOVHI r8,0x4060
  MOVI r9,0
  MOVHI r9,0x3FA0
  MOVI r10,0
  MOVHI r10,0x3F80
  MOVI r11,0
  MOVHI r11,0x4010           ; expected +2.25
  CALL @mth_ro_test_expect_ok
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_3

  ; ================= code 4: supports = (L+R) * C =================
  MOVI r7,4
  MOVI r8,0
  MOVHI r8,0x4060            ; L = +3.5
  MOVI r9,0
  MOVHI r9,0x3FA0            ; R = +1.25
  MOVI r10,0
  MOVHI r10,0x3F00           ; C = +0.5
  MOVI r11,0
  MOVHI r11,0x4018           ; expected +2.375
  CALL @mth_ro_test_expect_ok
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_4

  ; No score clamp: (3 + 4) * 1 = 7.0 is published unchanged.
  MOVI r7,4
  MOVI r8,0
  MOVHI r8,0x4040            ; L = +3.0
  MOVI r9,0
  MOVHI r9,0x4080            ; R = +4.0
  MOVI r10,0
  MOVHI r10,0x3F80           ; C = +1.0
  MOVI r11,0
  MOVHI r11,0x40E0           ; expected +7.0
  CALL @mth_ro_test_expect_ok
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_4

  ; ================= code 5: refutes = (R-L) * C =================
  MOVI r7,5
  MOVI r8,0
  MOVHI r8,0x4060            ; L = +3.5
  MOVI r9,0
  MOVHI r9,0x3FA0            ; R = +1.25
  MOVI r10,0
  MOVHI r10,0x3F00           ; C = +0.5
  MOVI r11,0
  MOVHI r11,0xBF90           ; expected -1.125
  CALL @mth_ro_test_expect_ok
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_5

  ; ================= code 6: equivalent = (min-max) * C =================
  ; L > R: (1.25 - 3.5) * 0.5 = -1.125.
  MOVI r7,6
  MOVI r8,0
  MOVHI r8,0x4060            ; L = +3.5
  MOVI r9,0
  MOVHI r9,0x3FA0            ; R = +1.25
  MOVI r10,0
  MOVHI r10,0x3F00           ; C = +0.5
  MOVI r11,0
  MOVHI r11,0xBF90           ; expected -1.125
  CALL @mth_ro_test_expect_ok
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_6

  ; Swap operands: the symmetric gap must still be -1.125, not +1.125.
  MOVI r7,6
  MOVI r8,0
  MOVHI r8,0x3FA0            ; L = +1.25
  MOVI r9,0
  MOVHI r9,0x4060            ; R = +3.5
  MOVI r10,0
  MOVHI r10,0x3F00           ; C = +0.5
  MOVI r11,0
  MOVHI r11,0xBF90           ; expected -1.125
  CALL @mth_ro_test_expect_ok
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_6

  ; Zero-gap boundary: (2 - 2) * 1 = +0.0.
  MOVI r7,6
  MOVI r8,0
  MOVHI r8,0x4000
  MOVI r9,0
  MOVHI r9,0x4000
  MOVI r10,0
  MOVHI r10,0x3F80
  MOVI r11,0                  ; expected +0.0
  CALL @mth_ro_test_expect_ok
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_6

  ; ================= code 7: transforms = (L*R) * C =================
  MOVI r7,7
  MOVI r8,0
  MOVHI r8,0x4060            ; L = +3.5
  MOVI r9,0
  MOVHI r9,0x3FA0            ; R = +1.25
  MOVI r10,0
  MOVHI r10,0x3F00           ; C = +0.5
  MOVI r11,0
  MOVHI r11,0x400C           ; expected +2.1875
  CALL @mth_ro_test_expect_ok
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_7

  ; ================= code 8: observes = max(L-R,R-L) * C =================
  ; L > R: max(2.25,-2.25) * 0.5 = +1.125.
  MOVI r7,8
  MOVI r8,0
  MOVHI r8,0x4060            ; L = +3.5
  MOVI r9,0
  MOVHI r9,0x3FA0            ; R = +1.25
  MOVI r10,0
  MOVHI r10,0x3F00           ; C = +0.5
  MOVI r11,0
  MOVHI r11,0x3F90           ; expected +1.125
  CALL @mth_ro_test_expect_ok
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_8

  ; Swap operands: the magnitude must still be +1.125.
  MOVI r7,8
  MOVI r8,0
  MOVHI r8,0x3FA0            ; L = +1.25
  MOVI r9,0
  MOVHI r9,0x4060            ; R = +3.5
  MOVI r10,0
  MOVHI r10,0x3F00           ; C = +0.5
  MOVI r11,0
  MOVHI r11,0x3F90           ; expected +1.125
  CALL @mth_ro_test_expect_ok
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_8

  ; Zero-gap boundary: max(0,0) * 1 = +0.0.
  MOVI r7,8
  MOVI r8,0
  MOVHI r8,0x4000
  MOVI r9,0
  MOVHI r9,0x4000
  MOVI r10,0
  MOVHI r10,0x3F80
  MOVI r11,0                  ; expected +0.0
  CALL @mth_ro_test_expect_ok
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_8

  ; ================= confidence boundary policy =================
  ; +0.0 confidence is accepted and publishes +0.0 for a positive base.
  MOVI r7,1
  MOVI r8,0
  MOVHI r8,0x4060            ; L = +3.5
  MOVI r9,0
  MOVHI r9,0x3FA0            ; R = +1.25
  MOVI r10,0                  ; C = +0.0
  MOVI r11,0                  ; expected +0.0
  CALL @mth_ro_test_expect_ok
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_10

  ; -0.0 confidence is equal to 0.0 and is accepted. Positive base times
  ; -0.0 gives IEEE -0.0, not a rejection and not an implicit false.
  MOVI r7,1
  MOVI r8,0
  MOVHI r8,0x4060            ; L = +3.5
  MOVI r9,0
  MOVHI r9,0x3FA0            ; R = +1.25
  MOVI r10,0
  MOVHI r10,0x8000           ; C = -0.0
  MOVI r11,0
  MOVHI r11,0x8000           ; expected -0.0
  CALL @mth_ro_test_expect_ok
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_10

  ; ================= unknown operator codes =================
  ; code 0
  MOVI r7,0
  MOVI r8,0
  MOVHI r8,0x4060
  MOVI r9,0
  MOVHI r9,0x3FA0
  MOVI r10,0
  MOVHI r10,0x3F00
  MOVI r11,1                  ; cause 1
  CALL @mth_ro_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_11

  ; code 9
  MOVI r7,9
  MOVI r8,0
  MOVHI r8,0x4060
  MOVI r9,0
  MOVHI r9,0x3FA0
  MOVI r10,0
  MOVHI r10,0x3F00
  MOVI r11,1                  ; cause 1
  CALL @mth_ro_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_11

  ; code 0xFFFFFFFF exercises the unsigned code-1 wrap gate.
  MOVI r7,0xFFFF
  MOVHI r7,0xFFFF
  MOVI r8,0
  MOVHI r8,0x4060
  MOVI r9,0
  MOVHI r9,0x3FA0
  MOVI r10,0
  MOVHI r10,0x3F00
  MOVI r11,1                  ; cause 1
  CALL @mth_ro_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_11

  ; ================= non-finite inputs =================
  ; left NaN -> cause 2
  MOVI r7,1
  MOVI r8,0
  MOVHI r8,0x7FC0
  MOVI r9,0
  MOVHI r9,0x3FA0
  MOVI r10,0
  MOVHI r10,0x3F00
  MOVI r11,2
  CALL @mth_ro_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_12

  ; left +Inf -> cause 2
  MOVI r7,1
  MOVI r8,0
  MOVHI r8,0x7F80
  MOVI r9,0
  MOVHI r9,0x3FA0
  MOVI r10,0
  MOVHI r10,0x3F00
  MOVI r11,2
  CALL @mth_ro_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_12

  ; right NaN -> cause 3
  MOVI r7,1
  MOVI r8,0
  MOVHI r8,0x4060
  MOVI r9,0
  MOVHI r9,0x7FC0
  MOVI r10,0
  MOVHI r10,0x3F00
  MOVI r11,3
  CALL @mth_ro_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_13

  ; right -Inf -> cause 3
  MOVI r7,1
  MOVI r8,0
  MOVHI r8,0x4060
  MOVI r9,0
  MOVHI r9,0xFF80
  MOVI r10,0
  MOVHI r10,0x3F00
  MOVI r11,3
  CALL @mth_ro_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_13

  ; confidence NaN -> cause 4
  MOVI r7,1
  MOVI r8,0
  MOVHI r8,0x4060
  MOVI r9,0
  MOVHI r9,0x3FA0
  MOVI r10,0
  MOVHI r10,0x7FC0
  MOVI r11,4
  CALL @mth_ro_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_14

  ; confidence +Inf -> cause 4
  MOVI r7,1
  MOVI r8,0
  MOVHI r8,0x4060
  MOVI r9,0
  MOVHI r9,0x3FA0
  MOVI r10,0
  MOVHI r10,0x7F80
  MOVI r11,4
  CALL @mth_ro_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_14

  ; ================= confidence outside [0,1] =================
  ; C = -0.5 -> cause 5
  MOVI r7,1
  MOVI r8,0
  MOVHI r8,0x4060
  MOVI r9,0
  MOVHI r9,0x3FA0
  MOVI r10,0
  MOVHI r10,0xBF00
  MOVI r11,5
  CALL @mth_ro_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_15

  ; C = +1.5 -> cause 5
  MOVI r7,1
  MOVI r8,0
  MOVHI r8,0x4060
  MOVI r9,0
  MOVHI r9,0x3FA0
  MOVI r10,0
  MOVHI r10,0x3FC0
  MOVI r11,5
  CALL @mth_ro_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_15

  ; C = first binary32 above 1.0 (0x3F800001) -> cause 5
  MOVI r7,1
  MOVI r8,0
  MOVHI r8,0x4060
  MOVI r9,0
  MOVHI r9,0x3FA0
  MOVI r10,1
  MOVHI r10,0x3F80
  MOVI r11,5
  CALL @mth_ro_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_15

  ; C = smallest negative binary32 (0x80000001) -> cause 5, no clamp.
  MOVI r7,1
  MOVI r8,0
  MOVHI r8,0x4060
  MOVI r9,0
  MOVHI r9,0x3FA0
  MOVI r10,1
  MOVHI r10,0x8000
  MOVI r11,5
  CALL @mth_ro_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_15

  ; ================= finite-input overflow -> cause 6 =================
  ; supports(maxfinite, maxfinite) is +Inf before confidence.
  MOVI r7,4
  MOVI r8,0xFFFF
  MOVHI r8,0x7F7F           ; L = 0x7F7FFFFF, largest finite f32
  MOVI r9,0xFFFF
  MOVHI r9,0x7F7F           ; R = 0x7F7FFFFF
  MOVI r10,0
  MOVHI r10,0x3F80           ; C = +1.0
  MOVI r11,6
  CALL @mth_ro_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_16

  ; transforms(maxfinite, maxfinite) is +Inf before confidence.
  MOVI r7,7
  MOVI r8,0xFFFF
  MOVHI r8,0x7F7F
  MOVI r9,0xFFFF
  MOVHI r9,0x7F7F
  MOVI r10,0
  MOVHI r10,0x3F80
  MOVI r11,6
  CALL @mth_ro_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_16

  ; Zero confidence does not hide an intermediate infinity:
  ; (maxfinite + maxfinite) * 0.0 is Inf * 0.0, an invalid NaN result.
  MOVI r7,4
  MOVI r8,0xFFFF
  MOVHI r8,0x7F7F
  MOVI r9,0xFFFF
  MOVHI r9,0x7F7F
  MOVI r10,0                  ; C = +0.0
  MOVI r11,6
  CALL @mth_ro_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_ro_test_fail_16

  ; ================= success marker =================
  MOVI r1,@mth_ro_test_pass
  CALL @mth_ro_test_puts
  HALT

; ---- failure reporting: r6 is a 1..19 case number ----
mth_ro_test_fail_1:
  MOVI r6,1
  JMP @mth_ro_test_fail
mth_ro_test_fail_2:
  MOVI r6,2
  JMP @mth_ro_test_fail
mth_ro_test_fail_3:
  MOVI r6,3
  JMP @mth_ro_test_fail
mth_ro_test_fail_4:
  MOVI r6,4
  JMP @mth_ro_test_fail
mth_ro_test_fail_5:
  MOVI r6,5
  JMP @mth_ro_test_fail
mth_ro_test_fail_6:
  MOVI r6,6
  JMP @mth_ro_test_fail
mth_ro_test_fail_7:
  MOVI r6,7
  JMP @mth_ro_test_fail
mth_ro_test_fail_8:
  MOVI r6,8
  JMP @mth_ro_test_fail
mth_ro_test_fail_10:
  MOVI r6,10
  JMP @mth_ro_test_fail
mth_ro_test_fail_11:
  MOVI r6,11
  JMP @mth_ro_test_fail
mth_ro_test_fail_12:
  MOVI r6,12
  JMP @mth_ro_test_fail
mth_ro_test_fail_13:
  MOVI r6,13
  JMP @mth_ro_test_fail
mth_ro_test_fail_14:
  MOVI r6,14
  JMP @mth_ro_test_fail
mth_ro_test_fail_15:
  MOVI r6,15
  JMP @mth_ro_test_fail
mth_ro_test_fail_16:
  MOVI r6,16

mth_ro_test_fail:
  MOVI r1,@mth_ro_test_bad_prefix
  CALL @mth_ro_test_puts
  MOVI r2,10
  CMP r6,r2
  JMP[LT] @mth_ro_test_fail_one_digit
  SUB r6,r6,r2
  MOVI r2,49                 ; '1'
  PUTC r2
mth_ro_test_fail_one_digit:
  ADDI r6,r6,48
  PUTC r6
  MOVI r1,@mth_ro_test_nl
  CALL @mth_ro_test_puts
  HALT

; ---- helpers ----
; Write the 0xDEADBEEF sentinel into the one-word output slot.
mth_ro_test_sentinel:
  MOVI r1,@mth_ro_out
  MOVI r2,0xBEEF
  MOVHI r2,0xDEAD
  ST r2,r1,0
  RET

; r7=code, r8=left bits, r9=right bits, r10=confidence bits.
; Calls the kernel with the fixed test output slot.
mth_ro_test_call:
  ST r15,r0,@mth_ro_test_link
  ADD r1,r7,r0
  ADD r2,r8,r0
  ADD r3,r9,r0
  ADD r4,r10,r0
  MOVI r5,@mth_ro_out
  SHL r5,r5,2
  CALL @mth_relation_operator_apply
  LD r15,r0,@mth_ro_test_link
  RET

; r7..r10 inputs, r11 expected score bits.
; Returns r1=1 iff success, cause 0, and exact output bits.
mth_ro_test_expect_ok:
  ST r15,r0,@mth_ro_test_outer_link
  ST r11,r0,@mth_ro_test_expected
  CALL @mth_ro_test_sentinel
  CALL @mth_ro_test_call
  CMP r1,r13
  JMP[NE] @mth_ro_test_expect_ok_bad
  CMP r9,r0
  JMP[NE] @mth_ro_test_expect_ok_bad
  LD r2,r0,@mth_ro_out
  LD r3,r0,@mth_ro_test_expected
  CMP r2,r3
  JMP[NE] @mth_ro_test_expect_ok_bad
  MOVI r1,1
  LD r15,r0,@mth_ro_test_outer_link
  RET
mth_ro_test_expect_ok_bad:
  MOVI r1,0
  LD r15,r0,@mth_ro_test_outer_link
  RET

; r7..r10 inputs, r11 expected cause.
; Returns r1=1 iff rejection cause matches and the sentinel is unchanged.
mth_ro_test_expect_reject:
  ST r15,r0,@mth_ro_test_outer_link
  ST r11,r0,@mth_ro_test_expected
  CALL @mth_ro_test_sentinel
  CALL @mth_ro_test_call
  CMP r1,r0
  JMP[NE] @mth_ro_test_expect_reject_bad
  LD r2,r0,@mth_ro_test_expected
  CMP r9,r2
  JMP[NE] @mth_ro_test_expect_reject_bad
  LD r2,r0,@mth_ro_out
  MOVI r3,0xBEEF
  MOVHI r3,0xDEAD
  CMP r2,r3
  JMP[NE] @mth_ro_test_expect_reject_bad
  MOVI r1,1
  LD r15,r0,@mth_ro_test_outer_link
  RET
mth_ro_test_expect_reject_bad:
  MOVI r1,0
  LD r15,r0,@mth_ro_test_outer_link
  RET

; r1 = NUL-terminated string; writes bytes through PUTC.
mth_ro_test_puts:
  MOVI r4,255
mth_ro_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_ro_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_ro_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_ro_test_puts_word

; ---- data ----
.org 2048
mth_ro_out:
.word 0xDEADBEEF
mth_ro_test_expected:
.word 0
mth_ro_test_link:
.word 0
mth_ro_test_outer_link:
.word 0

mth_ro_test_pass:
.str "MTH RELATION OPERATOR APPLY PASS\n"
mth_ro_test_bad_prefix:
.str "MTH RELATION OPERATOR APPLY FAIL "
mth_ro_test_nl:
.str "\n"
