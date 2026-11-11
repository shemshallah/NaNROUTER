; Native 256-slot exhaustive BS0 admission test: HW5=Gutenberg.
.org 0
JMP @hw5_test_main
.include "../nan16/mth_hw5_gutenberg_slot_guard.nas"
hw5_test_main:
  MOVI r0,0
  MOVI r13,1
  MOVI r9,0
hw5_test_each_public:
  ADD r1,r9,r0
  MOVI r2,0
  MOVI r3,1
  CALL @mth_hw5_gutenberg_slot_guard
  MOVI r10,9
  CMP r9,r10
  JMP[LT] @hw5_test_expected_deny
  CMP r1,r13
  JMP[NE] @hw5_test_fail
  CMP r2,r0
  JMP[NE] @hw5_test_fail
  ADD r10,r9,r13
  CMP r3,r10
  JMP[NE] @hw5_test_fail
  JMP @hw5_test_next
hw5_test_expected_deny:
  CMP r1,r0
  JMP[NE] @hw5_test_fail
  MOVI r10,3
  CMP r2,r10
  JMP[NE] @hw5_test_fail
  CMP r3,r0
  JMP[NE] @hw5_test_fail
hw5_test_next:
  ADDI r9,r9,1
  MOVI r10,256
  CMP r9,r10
  JMP[LT] @hw5_test_each_public

  ; HW5/operation 1 allows ONLY Gutenberg, HW4/operation 2 ONLY WordNet.
  MOVI r1,5
  MOVI r2,1
  MOVI r3,1
  CALL @mth_hw5_gutenberg_slot_guard
  CMP r1,r13
  JMP[NE] @hw5_test_fail
  MOVI r10,6
  CMP r3,r10
  JMP[NE] @hw5_test_fail
  MOVI r1,4
  MOVI r2,1
  MOVI r3,1
  CALL @mth_hw5_gutenberg_slot_guard
  CMP r1,r0
  JMP[NE] @hw5_test_fail
  MOVI r1,4
  MOVI r2,2
  MOVI r3,1
  CALL @mth_hw5_gutenberg_slot_guard
  CMP r1,r13
  JMP[NE] @hw5_test_fail
  MOVI r1,5
  MOVI r2,2
  MOVI r3,1
  CALL @mth_hw5_gutenberg_slot_guard
  CMP r1,r0
  JMP[NE] @hw5_test_fail

  ; A BSR control worker cannot reclassify HW5 as ordinary control HW.
  MOVI r1,5
  MOVI r2,3
  MOVI r3,1
  CALL @mth_hw5_gutenberg_slot_guard
  CMP r1,r0
  JMP[NE] @hw5_test_fail
  MOVI r1,6
  MOVI r2,3
  MOVI r3,1
  CALL @mth_hw5_gutenberg_slot_guard
  CMP r1,r13
  JMP[NE] @hw5_test_fail
  ; Invalid revision and invalid 32-bit coordinate fail closed.
  MOVI r1,5
  MOVI r2,1
  MOVI r3,2
  CALL @mth_hw5_gutenberg_slot_guard
  CMP r1,r0
  JMP[NE] @hw5_test_fail
  MOVI r10,4
  CMP r2,r10
  JMP[NE] @hw5_test_fail
  MOVI r1,256
  MOVI r2,0
  MOVI r3,1
  CALL @mth_hw5_gutenberg_slot_guard
  CMP r1,r0
  JMP[NE] @hw5_test_fail
  MOVI r10,1
  CMP r2,r10
  JMP[NE] @hw5_test_fail
  MOVI r1,@hw5_test_pass
  CALL @hw5_test_puts
  HALT
hw5_test_fail:
  MOVI r1,@hw5_test_bad
  CALL @hw5_test_puts
  HALT
hw5_test_puts:
  MOVI r4,255
hw5_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
hw5_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @hw5_test_puts_byte
  ADD r1,r1,r13
  JMP @hw5_test_puts_word
hw5_test_pass:
.str "MTH HW5 GUTENBERG SLOT GUARD PASS\n"
hw5_test_bad:
.str "MTH HW5 GUTENBERG SLOT GUARD FAIL\n"
