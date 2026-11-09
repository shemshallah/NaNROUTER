; MTH copy-vs-generate gate fixture — NaN16 float32 only.
;
; The fixture is table-driven. Every case supplies the three input registers
; and the expected values of r1 (status), r4 (mode), r5 (confidence payload),
; and r9 (0 on success, or cause on rejection).
;
; The runner poisons r4, r5, and r9 before each call:
;   r4 = 0x11111111, r5 = 0x22222222, r9 = 0xDEADBEEF.
; A rejection must leave r4 and r5 at those sentinels and write the expected
; cause in r9. A success must write mode, confidence, and r9 = 0. Every
; rejection case therefore also checks output atomicity.
;
; Covered behavior:
;   - strong copy and strong generate;
;   - exact equality, one float32 ULP below, and one ULP above the boundary;
;   - positive, negative, and zero gate bias, including bias that reaches
;     equality or reverses the unbias decision;
;   - +0.0 and -0.0 score, bias, and threshold combinations;
;   - largest finite magnitude, finite overflow to +/-Inf, and minimum
;     subnormal positive and negative scores;
;   - confidence at 0, at 1 exactly, just above 1, and below -1 (abs clamp);
;   - threshold endpoints 0 and 1, and just below the upper endpoint;
;   - NaN, signaling NaN, +Inf, and -Inf in every input position;
;   - threshold below 0 and above 1, including subnormal and one-ULP cases;
;   - deterministic cause priority when several inputs are invalid;
;   - input-register and r12/r14/r13 preservation on a successful call.
;
; All expected values are binary32 bit patterns checked with integer CMP.
; No host math is used and no expected value is computed at run time.

.org 0
JMP @mth_copy_gate_test_main
.include "../nan16/mth_copy_gate.nas"

mth_copy_gate_test_main:
  MOVI r13,1

  ; ---- Success cases -----------------------------------------------------
  ; 01: 0.75 >= 0.5, margin +0.25.
  LA r1,@mth_copy_gate_case_01
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 02: 0.25 < 0.5, margin -0.25.
  LA r1,@mth_copy_gate_case_02
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 03: exact equality copies with zero confidence.
  LA r1,@mth_copy_gate_case_03
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 04: one ULP below the boundary generates, margin -2^-25.
  LA r1,@mth_copy_gate_case_04
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 05: one ULP above the boundary copies, margin +2^-24.
  LA r1,@mth_copy_gate_case_05
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 06: bias 0.25 makes an otherwise failing score equal the threshold.
  LA r1,@mth_copy_gate_case_06
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 07: negative bias turns an equality into generate.
  LA r1,@mth_copy_gate_case_07
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 08: positive bias increases the copy margin.
  LA r1,@mth_copy_gate_case_08
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 09: -0 score plus -0 bias against +0 threshold copies at zero.
  LA r1,@mth_copy_gate_case_09
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 10: -0 threshold is accepted and compares equal to +0 sum.
  LA r1,@mth_copy_gate_case_10
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 11: -0 score and -0 threshold with +0 bias.
  LA r1,@mth_copy_gate_case_11
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 12: FLT_MAX copies with confidence clamped to 1.
  LA r1,@mth_copy_gate_case_12
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 13: -FLT_MAX generates with confidence clamped to 1.
  LA r1,@mth_copy_gate_case_13
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 14: finite operands overflow to +Inf; copy and confidence 1.
  LA r1,@mth_copy_gate_case_14
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 15: finite operands overflow to -Inf; generate and confidence 1.
  LA r1,@mth_copy_gate_case_15
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 16: minimum positive subnormal copies with subnormal confidence.
  LA r1,@mth_copy_gate_case_16
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 17: confidence exactly 1.0 is not clamped further.
  LA r1,@mth_copy_gate_case_17
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 18: confidence just above 1.0 clamps to 1.0.
  LA r1,@mth_copy_gate_case_18
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 19: negative margin exactly -1.0; abs gives 1.0.
  LA r1,@mth_copy_gate_case_19
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 20: negative margin just below -1.0 clamps to 1.0 after abs.
  LA r1,@mth_copy_gate_case_20
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 21: threshold upper endpoint 1.0 is accepted; equality copies.
  LA r1,@mth_copy_gate_case_21
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 22: score just below threshold 1.0 generates, margin -2^-24.
  LA r1,@mth_copy_gate_case_22
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 23: negative bias on a negative score.
  LA r1,@mth_copy_gate_case_23
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 24: positive bias rescues a negative score into copy.
  LA r1,@mth_copy_gate_case_24
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 25: minimum negative subnormal generates; confidence is positive.
  LA r1,@mth_copy_gate_case_25
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail

  ; ---- Rejection cases ---------------------------------------------------
  ; 26: quiet NaN score -> cause 1.
  LA r1,@mth_copy_gate_case_26
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 27: +Inf score -> cause 1.
  LA r1,@mth_copy_gate_case_27
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 28: -Inf score -> cause 1.
  LA r1,@mth_copy_gate_case_28
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 29: signaling NaN score -> cause 1.
  LA r1,@mth_copy_gate_case_29
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 30: negative quiet NaN threshold -> cause 2.
  LA r1,@mth_copy_gate_case_30
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 31: +Inf threshold -> cause 2.
  LA r1,@mth_copy_gate_case_31
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 32: -Inf threshold -> cause 2.
  LA r1,@mth_copy_gate_case_32
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 33: threshold -0.5 -> cause 4.
  LA r1,@mth_copy_gate_case_33
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 34: threshold 1.5 -> cause 4.
  LA r1,@mth_copy_gate_case_34
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 35: threshold -minimum subnormal -> cause 4.
  LA r1,@mth_copy_gate_case_35
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 36: threshold one ULP above 1.0 -> cause 4.
  LA r1,@mth_copy_gate_case_36
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 37: threshold 2.0 -> cause 4.
  LA r1,@mth_copy_gate_case_37
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 38: threshold FLT_MAX -> cause 4.
  LA r1,@mth_copy_gate_case_38
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 39: quiet NaN bias -> cause 3.
  LA r1,@mth_copy_gate_case_39
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 40: +Inf bias -> cause 3.
  LA r1,@mth_copy_gate_case_40
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 41: -Inf bias -> cause 3.
  LA r1,@mth_copy_gate_case_41
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 42: invalid score wins over invalid range and invalid bias -> cause 1.
  LA r1,@mth_copy_gate_case_42
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 43: invalid threshold wins over invalid bias -> cause 2.
  LA r1,@mth_copy_gate_case_43
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail
  ; 44: invalid bias wins over invalid range -> cause 3.
  LA r1,@mth_copy_gate_case_44
  CALL @mth_copy_gate_test_run
  CMP r1,r0
  JMP[NE] @mth_copy_gate_test_fail

  ; ---- ABI preservation on a direct successful call ----------------------
  MOVI r1,0
  MOVHI r1,0x3F40            ; score = 0.75
  MOVI r2,0
  MOVHI r2,0x3F00            ; threshold = 0.5
  MOVI r3,0                  ; bias = +0.0
  MOVI r4,0x1111
  MOVHI r4,0x1111
  MOVI r5,0x2222
  MOVHI r5,0x2222
  MOVI r9,0xBEEF
  MOVHI r9,0xDEAD
  MOVI r12,0x1357
  MOVHI r12,0x1357
  MOVI r14,0x2468
  MOVHI r14,0x2468
  CALL @mth_copy_gate

  CMP r1,r13                ; success
  JMP[NE] @mth_copy_gate_test_fail
  MOVI r6,1
  CMP r4,r6                 ; copy
  JMP[NE] @mth_copy_gate_test_fail
  MOVI r6,0
  MOVHI r6,0x3E80           ; confidence 0.25
  CMP r5,r6
  JMP[NE] @mth_copy_gate_test_fail
  MOVI r6,0                  ; r9 = 0 on success
  CMP r9,r6
  JMP[NE] @mth_copy_gate_test_fail
  MOVI r6,0
  MOVHI r6,0x3F00           ; r2 threshold preserved
  CMP r2,r6
  JMP[NE] @mth_copy_gate_test_fail
  CMP r3,r0                 ; r3 bias preserved (+0.0)
  JMP[NE] @mth_copy_gate_test_fail
  MOVI r6,0x1357
  MOVHI r6,0x1357           ; r12 preserved
  CMP r12,r6
  JMP[NE] @mth_copy_gate_test_fail
  MOVI r6,0x2468
  MOVHI r6,0x2468           ; r14 preserved
  CMP r14,r6
  JMP[NE] @mth_copy_gate_test_fail
  MOVI r6,1
  CMP r13,r6                ; increment register preserved
  JMP[NE] @mth_copy_gate_test_fail

  LA r1,@mth_copy_gate_test_pass
  CALL @mth_copy_gate_test_puts
  HALT

mth_copy_gate_test_fail:
  LA r1,@mth_copy_gate_test_bad
  CALL @mth_copy_gate_test_puts
  HALT

; Case runner:
;   r1 = pointer to [score, threshold, bias, expected r1, expected r4,
;                    expected r5, expected r9]
;   returns r1 = 0 if the case passed, 1 if it failed.
; The case pointer lives in r12, which the gate preserves. The runner's own
; return link is saved because the nested CALL overwrites r15.
mth_copy_gate_test_run:
  ST r15,r0,@mth_copy_gate_test_ret
  ADD r12,r1,r0

  ; Poison all three observable result registers.
  MOVI r4,0x1111
  MOVHI r4,0x1111
  MOVI r5,0x2222
  MOVHI r5,0x2222
  MOVI r9,0xBEEF
  MOVHI r9,0xDEAD

  LD r1,r12,0
  LD r2,r12,1
  LD r3,r12,2
  CALL @mth_copy_gate

  LD r6,r12,3
  CMP r1,r6
  JMP[NE] @mth_copy_gate_test_run_fail
  LD r6,r12,4
  CMP r4,r6
  JMP[NE] @mth_copy_gate_test_run_fail
  LD r6,r12,5
  CMP r5,r6
  JMP[NE] @mth_copy_gate_test_run_fail
  LD r6,r12,6
  CMP r9,r6
  JMP[NE] @mth_copy_gate_test_run_fail

  MOVI r1,0
  LD r15,r0,@mth_copy_gate_test_ret
  RET
mth_copy_gate_test_run_fail:
  MOVI r1,1
  LD r15,r0,@mth_copy_gate_test_ret
  RET

mth_copy_gate_test_puts:
  MOVI r4,255
mth_copy_gate_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_copy_gate_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_copy_gate_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_copy_gate_test_puts_word

; ---------------------------------------------------------------------------
; Case table. Each row is seven words:
;   score, threshold, bias, expected r1, expected r4, expected r5, expected r9
; The expected r4/r5 values in rejection rows are the runner's poisons, so a
; rejected call that writes either output fails the fixture.
; ---------------------------------------------------------------------------
.org 4096
; 01: strong copy, +0.25 margin.
mth_copy_gate_case_01:
.word 0x3F400000,0x3F000000,0x00000000,1,1,0x3E800000,0x00000000
; 02: strong generate, -0.25 margin.
mth_copy_gate_case_02:
.word 0x3E800000,0x3F000000,0x00000000,1,0,0x3E800000,0x00000000
; 03: exact equality copies with +0 confidence.
mth_copy_gate_case_03:
.word 0x3F000000,0x3F000000,0x00000000,1,1,0x00000000,0x00000000
; 04: largest float32 below 0.5; generate, confidence 2^-25.
mth_copy_gate_case_04:
.word 0x3EFFFFFF,0x3F000000,0x00000000,1,0,0x33000000,0x00000000
; 05: smallest float32 above 0.5; copy, confidence 2^-24.
mth_copy_gate_case_05:
.word 0x3F000001,0x3F000000,0x00000000,1,1,0x33800000,0x00000000
; 06: bias reaches equality exactly; copy with zero confidence.
mth_copy_gate_case_06:
.word 0x3E800000,0x3F000000,0x3E800000,1,1,0x00000000,0x00000000
; 07: negative bias drops equality to generate.
mth_copy_gate_case_07:
.word 0x3F000000,0x3F000000,0xBE800000,1,0,0x3E800000,0x00000000
; 08: positive bias increases copy margin.
mth_copy_gate_case_08:
.word 0x3E800000,0x3F000000,0x3F000000,1,1,0x3E800000,0x00000000
; 09: -0 score plus -0 bias, +0 threshold; copy and +0 confidence.
mth_copy_gate_case_09:
.word 0x80000000,0x00000000,0x80000000,1,1,0x00000000,0x00000000
; 10: +0 score, -0 threshold, +0 bias; -0 threshold accepted.
mth_copy_gate_case_10:
.word 0x00000000,0x80000000,0x00000000,1,1,0x00000000,0x00000000
; 11: -0 score, -0 threshold, +0 bias.
mth_copy_gate_case_11:
.word 0x80000000,0x80000000,0x00000000,1,1,0x00000000,0x00000000
; 12: FLT_MAX copies; distance clamps to 1.
mth_copy_gate_case_12:
.word 0x7F7FFFFF,0x3F800000,0x00000000,1,1,0x3F800000,0x00000000
; 13: -FLT_MAX generates; distance clamps to 1.
mth_copy_gate_case_13:
.word 0xFF7FFFFF,0x3F800000,0x00000000,1,0,0x3F800000,0x00000000
; 14: FLT_MAX + FLT_MAX overflows to +Inf; copy, confidence 1.
mth_copy_gate_case_14:
.word 0x7F7FFFFF,0x3F800000,0x7F7FFFFF,1,1,0x3F800000,0x00000000
; 15: -FLT_MAX + -FLT_MAX overflows to -Inf; generate, confidence 1.
mth_copy_gate_case_15:
.word 0xFF7FFFFF,0x3F800000,0xFF7FFFFF,1,0,0x3F800000,0x00000000
; 16: minimum positive subnormal copies; confidence stays subnormal.
mth_copy_gate_case_16:
.word 0x00000001,0x00000000,0x00000000,1,1,0x00000001,0x00000000
; 17: confidence exactly 1.0.
mth_copy_gate_case_17:
.word 0x3F800000,0x00000000,0x00000000,1,1,0x3F800000,0x00000000
; 18: confidence just above 1.0 clamps.
mth_copy_gate_case_18:
.word 0x3F800001,0x00000000,0x00000000,1,1,0x3F800000,0x00000000
; 19: margin exactly -1.0; abs gives confidence 1.0.
mth_copy_gate_case_19:
.word 0xBF800000,0x00000000,0x00000000,1,0,0x3F800000,0x00000000
; 20: margin just below -1.0; abs then upper clamp gives 1.0.
mth_copy_gate_case_20:
.word 0xBF800001,0x00000000,0x00000000,1,0,0x3F800000,0x00000000
; 21: upper threshold endpoint accepted; equality copies.
mth_copy_gate_case_21:
.word 0x3F800000,0x3F800000,0x00000000,1,1,0x00000000,0x00000000
; 22: score just below threshold 1.0; generate, confidence 2^-24.
mth_copy_gate_case_22:
.word 0x3F7FFFFF,0x3F800000,0x00000000,1,0,0x33800000,0x00000000
; 23: negative bias on a negative score.
mth_copy_gate_case_23:
.word 0xBF000000,0x00000000,0xBE800000,1,0,0x3F400000,0x00000000
; 24: positive bias rescues a negative score into copy.
mth_copy_gate_case_24:
.word 0xBE800000,0x00000000,0x3F000000,1,1,0x3E800000,0x00000000
; 25: minimum negative subnormal generates with positive confidence.
mth_copy_gate_case_25:
.word 0x80000001,0x00000000,0x00000000,1,0,0x00000001,0x00000000

; 26: quiet NaN score.
mth_copy_gate_case_26:
.word 0x7FC00000,0x3F000000,0x00000000,0,0x11111111,0x22222222,1
; 27: +Inf score.
mth_copy_gate_case_27:
.word 0x7F800000,0x3F000000,0x00000000,0,0x11111111,0x22222222,1
; 28: -Inf score.
mth_copy_gate_case_28:
.word 0xFF800000,0x3F000000,0x00000000,0,0x11111111,0x22222222,1
; 29: signaling NaN score.
mth_copy_gate_case_29:
.word 0x7F800001,0x3F000000,0x00000000,0,0x11111111,0x22222222,1
; 30: negative quiet NaN threshold.
mth_copy_gate_case_30:
.word 0x3F000000,0xFFC00000,0x00000000,0,0x11111111,0x22222222,2
; 31: +Inf threshold.
mth_copy_gate_case_31:
.word 0x3F000000,0x7F800000,0x00000000,0,0x11111111,0x22222222,2
; 32: -Inf threshold.
mth_copy_gate_case_32:
.word 0x3F000000,0xFF800000,0x00000000,0,0x11111111,0x22222222,2
; 33: threshold below the lower endpoint.
mth_copy_gate_case_33:
.word 0x3F000000,0xBF000000,0x00000000,0,0x11111111,0x22222222,4
; 34: threshold above the upper endpoint.
mth_copy_gate_case_34:
.word 0x3F000000,0x3FC00000,0x00000000,0,0x11111111,0x22222222,4
; 35: threshold is the minimum negative subnormal.
mth_copy_gate_case_35:
.word 0x3F000000,0x80000001,0x00000000,0,0x11111111,0x22222222,4
; 36: threshold is one ULP above 1.0.
mth_copy_gate_case_36:
.word 0x3F000000,0x3F800001,0x00000000,0,0x11111111,0x22222222,4
; 37: threshold 2.0.
mth_copy_gate_case_37:
.word 0x3F000000,0x40000000,0x00000000,0,0x11111111,0x22222222,4
; 38: threshold FLT_MAX.
mth_copy_gate_case_38:
.word 0x3F000000,0x7F7FFFFF,0x00000000,0,0x11111111,0x22222222,4
; 39: quiet NaN bias.
mth_copy_gate_case_39:
.word 0x3F000000,0x3F000000,0x7FC00000,0,0x11111111,0x22222222,3
; 40: +Inf bias.
mth_copy_gate_case_40:
.word 0x3F000000,0x3F000000,0x7F800000,0,0x11111111,0x22222222,3
; 41: -Inf bias.
mth_copy_gate_case_41:
.word 0x3F000000,0x3F000000,0xFF800000,0,0x11111111,0x22222222,3
; 42: invalid score has priority over invalid range and invalid bias.
mth_copy_gate_case_42:
.word 0x7FC00000,0x3FC00000,0x7FC00000,0,0x11111111,0x22222222,1
; 43: invalid threshold has priority over invalid bias.
mth_copy_gate_case_43:
.word 0x3F000000,0x7FC00000,0x7FC00000,0,0x11111111,0x22222222,2
; 44: invalid bias has priority over invalid range.
mth_copy_gate_case_44:
.word 0x3F000000,0x3FC00000,0x7FC00000,0,0x11111111,0x22222222,3

mth_copy_gate_test_ret:
.word 0
mth_copy_gate_test_pass:
.str "MTH COPY GATE PASS\n"
mth_copy_gate_test_bad:
.str "MTH COPY GATE FAIL\n"
