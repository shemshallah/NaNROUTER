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
  MOVI r1,r12
  CALL @mth_rot2_class

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
  CALL @mth_double_endian
  LD r2,r6,0
  LDN r3,r6,0
  CMP r2,r10
  JMP[NE] @mth_fail
  CMP r3,r11
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
mth_puts_byte:
  LD r2,r1,0
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  ADD r1,r1,r13
  JMP @mth_puts_byte

mth_word:
.word 0
mth_pass:
.str "MTH STAGE0 PASS\n"
mth_bad:
.str "MTH STAGE0 FAIL\n"
