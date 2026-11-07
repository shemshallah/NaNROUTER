; MTH Stage 0 smoke test — NaN16 only
; Checks the 16 ordered truth-table class rotations and BSWAPM involution.
; ABI: r0=0, r13=1. Prints PASS/FAIL through the existing COM1 PUTC path.

.org 0
JMP @mth_test_main
.include "../nan16/mth_core.nas"

mth_test_main:
  MOVI r13,1
  MOVI r12,0
  MOVI r14,0

mth_rot_loop:
  ADD r1,r12,r0
  CALL @mth_rot2_class
  LD r4,r12,@mth_rot_expected
  CMP r1,r4
  JMP[NE] @mth_fail

  ; Apply the rotation twice; it must return the original four-bit class.
  CALL @mth_rot2_class
  CMP r1,r12
  JMP[NE] @mth_fail
  ADD r12,r12,r13
  MOVI r4,16
  CMP r12,r4
  JMP[LT] @mth_rot_loop

  ; A single BSWAPM followed by a second BSWAPM must restore the word.
  MOVI r6,@mth_word
  MOVI r7,2
  MOVHI r7,0x0031
  MOVI r3,6
  STW r7,r6,r3
  LD r10,r6,0
  LDN r11,r6,0
  MOVI r1,@mth_word
  CALL @mth_double_endian
  LDN r12,r6,0
  MOVI r8,9
  CMP r12,r8
  JMP[NE] @mth_fail
  LD r14,r6,0
  MOVI r8,0x3100
  MOVHI r8,0x0200
  CMP r14,r8
  JMP[NE] @mth_fail
  CALL @mth_double_endian
  LD r2,r6,0
  LDN r3,r6,0
  CMP r2,r11
  JMP[NE] @mth_fail
  CMP r3,r10
  JMP[NE] @mth_fail

  MOVI r1,@mth_pass
  CALL @mth_puts
  HALT

mth_fail:
  MOVI r1,@mth_bad
  CALL @mth_puts
  HALT

mth_puts:
  MOVI r4,255
mth_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_puts_byte
  ADD r1,r1,r13
  JMP @mth_puts_word

mth_rot_expected:
.word 0
.word 4
.word 8
.word 12
.word 1
.word 5
.word 9
.word 13
.word 2
.word 6
.word 10
.word 14
.word 3
.word 7
.word 11
.word 15
mth_word:
.word 0
mth_pass:
.str "MTH STAGE0 PASS\n"
mth_bad:
.str "MTH STAGE0 FAIL\n"
