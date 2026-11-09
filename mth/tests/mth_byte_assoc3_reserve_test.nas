; MTH 3-byte reserve-row hash fixture — NaN16 only.
;
; Checks known slots, deterministic range over 10,000 contexts, reserve-window
; boundaries, and invalid byte/base rejection.

.org 0
JMP @mth_assoc3_test_main
.include "../nan16/mth_byte_assoc3_reserve.nas"

mth_assoc3_test_main:
  MOVI r0,0
  MOVI r13,1

  ; known: (0,0,0)->3968
  MOVI r1,0
  MOVI r2,0
  MOVI r3,0
  MOVI r4,3968
  CALL @mth_byte_assoc3_reserve_u32
  CMP r1,r13
  JMP[NE] @mth_assoc3_test_fail
  MOVI r8,3968
  CMP r5,r8
  JMP[NE] @mth_assoc3_test_fail

  ; known: (1,0,0)->4023
  MOVI r1,1
  MOVI r2,0
  MOVI r3,0
  MOVI r4,3968
  CALL @mth_byte_assoc3_reserve_u32
  CMP r1,r13
  JMP[NE] @mth_assoc3_test_fail
  MOVI r8,4023
  CMP r5,r8
  JMP[NE] @mth_assoc3_test_fail

  ; known: (0,1,0)->4089
  MOVI r1,0
  MOVI r2,1
  MOVI r3,0
  MOVI r4,3968
  CALL @mth_byte_assoc3_reserve_u32
  CMP r1,r13
  JMP[NE] @mth_assoc3_test_fail
  MOVI r8,4089
  CMP r5,r8
  JMP[NE] @mth_assoc3_test_fail

  ; known: (32,101,97)->3971
  MOVI r1,32
  MOVI r2,101
  MOVI r3,97
  MOVI r4,3968
  CALL @mth_byte_assoc3_reserve_u32
  CMP r1,r13
  JMP[NE] @mth_assoc3_test_fail
  MOVI r8,3971
  CMP r5,r8
  JMP[NE] @mth_assoc3_test_fail

  ; exhaustive 10,000 contexts, deterministic and in window
  MOVI r7,0
mth_assoc3_test_loop:
  MOVI r1,255
  BOOL.8 r1,r7,r1
  MOVI r2,0
  SHR r2,r7,8
  MOVI r9,255
  BOOL.8 r2,r2,r9
  MOVI r3,0
  SHR r3,r7,16
  MOVI r4,3968
  CALL @mth_byte_assoc3_reserve_u32
  CMP r1,r13
  JMP[NE] @mth_assoc3_test_fail
  MOVI r8,3968
  CMP r5,r8
  JMP[LT] @mth_assoc3_test_fail
  MOVI r8,4095
  CMP r8,r5
  JMP[LT] @mth_assoc3_test_fail
  MOVI r9,@mth_assoc3_test_last
  ST r5,r9,0
  ; replay same context
  MOVI r1,255
  BOOL.8 r1,r7,r1
  MOVI r2,0
  SHR r2,r7,8
  MOVI r9,255
  BOOL.8 r2,r2,r9
  MOVI r3,0
  SHR r3,r7,16
  MOVI r4,3968
  CALL @mth_byte_assoc3_reserve_u32
  LD r9,r0,@mth_assoc3_test_last
  CMP r5,r9
  JMP[NE] @mth_assoc3_test_fail
  ADDI r7,r7,1
  MOVI r9,10000
  CMP r7,r9
  JMP[LT] @mth_assoc3_test_loop

  ; base boundaries: 0 and 32257
  MOVI r1,255
  MOVI r2,255
  MOVI r3,255
  MOVI r4,0
  CALL @mth_byte_assoc3_reserve_u32
  CMP r1,r13
  JMP[NE] @mth_assoc3_test_fail
  MOVI r8,127
  CMP r8,r5
  JMP[LT] @mth_assoc3_test_fail
  MOVI r1,255
  MOVI r2,255
  MOVI r3,255
  MOVI r4,32257
  CALL @mth_byte_assoc3_reserve_u32
  CMP r1,r13
  JMP[NE] @mth_assoc3_test_fail
  MOVI r8,32257
  CMP r5,r8
  JMP[LT] @mth_assoc3_test_fail
  MOVI r8,32384
  CMP r8,r5
  JMP[LT] @mth_assoc3_test_fail

  ; invalid byte
  MOVI r1,256
  MOVI r2,0
  MOVI r3,0
  MOVI r4,0
  CALL @mth_byte_assoc3_reserve_u32
  CMP r1,r0
  JMP[NE] @mth_assoc3_test_fail
  MOVI r8,1
  CMP r9,r8
  JMP[NE] @mth_assoc3_test_fail
  CMP r5,r0
  JMP[NE] @mth_assoc3_test_fail

  ; invalid reserve base
  MOVI r1,0
  MOVI r2,0
  MOVI r3,0
  MOVI r4,32258
  CALL @mth_byte_assoc3_reserve_u32
  CMP r1,r0
  JMP[NE] @mth_assoc3_test_fail
  MOVI r8,2
  CMP r9,r8
  JMP[NE] @mth_assoc3_test_fail

  ; recovery
  MOVI r1,0
  MOVI r2,0
  MOVI r3,0
  MOVI r4,3968
  CALL @mth_byte_assoc3_reserve_u32
  CMP r1,r13
  JMP[NE] @mth_assoc3_test_fail
  MOVI r8,3968
  CMP r5,r8
  JMP[NE] @mth_assoc3_test_fail

  MOVI r1,@mth_assoc3_test_pass
  CALL @mth_assoc3_test_puts
  HALT

mth_assoc3_test_fail:
  MOVI r1,@mth_assoc3_test_bad
  CALL @mth_assoc3_test_puts
  HALT

mth_assoc3_test_puts:
  MOVI r4,255
mth_assoc3_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_assoc3_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_assoc3_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_assoc3_test_puts_word

mth_assoc3_test_pass:
.str "MTH ASSOC3 RESERVE PASS\n"
mth_assoc3_test_bad:
.str "MTH ASSOC3 RESERVE FAIL\n"

.org 4096
mth_assoc3_test_last:
.word 0
