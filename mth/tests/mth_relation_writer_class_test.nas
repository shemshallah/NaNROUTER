; MTH Round 037 writer-class codec fixture — NaN16 only.
.org 0
JMP @mth_writer_class_test_main
.include "../nan16/mth_relation_writer_class.nas"

mth_writer_class_test_main:
  MOVI r13,1

  ; decode 0 -> forward
  MOVI r1,0
  CALL @mth_relation_writer_decode
  CMP r1,r13
  JMP[NE] @mth_writer_class_fail
  MOVI r10,1
  CMP r3,r10
  JMP[NE] @mth_writer_class_fail
  CMP r4,r0
  JMP[NE] @mth_writer_class_fail
  CMP r5,r0
  JMP[NE] @mth_writer_class_fail

  ; decode 1 -> reverse
  MOVI r1,1
  CALL @mth_relation_writer_decode
  CMP r1,r13
  JMP[NE] @mth_writer_class_fail
  MOVI r10,2
  CMP r3,r10
  JMP[NE] @mth_writer_class_fail
  CMP r4,r0
  JMP[NE] @mth_writer_class_fail

  ; decode 2 -> negated forward
  MOVI r1,2
  CALL @mth_relation_writer_decode
  CMP r1,r13
  JMP[NE] @mth_writer_class_fail
  MOVI r10,1
  CMP r3,r10
  JMP[NE] @mth_writer_class_fail
  CMP r4,r13
  JMP[NE] @mth_writer_class_fail
  CMP r5,r0
  JMP[NE] @mth_writer_class_fail

  ; decode 3 -> uncertain
  MOVI r1,3
  CALL @mth_relation_writer_decode
  CMP r1,r13
  JMP[NE] @mth_writer_class_fail
  CMP r3,r0
  JMP[NE] @mth_writer_class_fail
  CMP r4,r0
  JMP[NE] @mth_writer_class_fail
  CMP r5,r13
  JMP[NE] @mth_writer_class_fail

  ; reject decode 4
  MOVI r1,4
  CALL @mth_relation_writer_decode
  CMP r1,r0
  JMP[NE] @mth_writer_class_fail

  ; encode forward
  MOVI r1,1
  MOVI r2,0
  MOVI r3,0
  CALL @mth_relation_writer_encode
  CMP r1,r13
  JMP[NE] @mth_writer_class_fail
  CMP r4,r0
  JMP[NE] @mth_writer_class_fail

  ; encode reverse
  MOVI r1,2
  CALL @mth_relation_writer_encode
  CMP r1,r13
  JMP[NE] @mth_writer_class_fail
  CMP r4,r13
  JMP[NE] @mth_writer_class_fail

  ; encode negated
  MOVI r1,1
  MOVI r2,1
  CALL @mth_relation_writer_encode
  CMP r1,r13
  JMP[NE] @mth_writer_class_fail
  MOVI r10,2
  CMP r4,r10
  JMP[NE] @mth_writer_class_fail

  ; encode uncertain
  MOVI r1,0
  MOVI r2,0
  MOVI r3,1
  CALL @mth_relation_writer_encode
  CMP r1,r13
  JMP[NE] @mth_writer_class_fail
  MOVI r10,3
  CMP r4,r10
  JMP[NE] @mth_writer_class_fail

  ; invalid encodings
  MOVI r1,1
  MOVI r2,0
  MOVI r3,1
  CALL @mth_relation_writer_encode
  CMP r1,r0
  JMP[NE] @mth_writer_class_fail
  MOVI r1,0
  MOVI r2,0
  MOVI r3,0
  CALL @mth_relation_writer_encode
  CMP r1,r0
  JMP[NE] @mth_writer_class_fail

  MOVI r1,@mth_writer_class_pass
  CALL @mth_writer_class_puts
  HALT

mth_writer_class_fail:
  MOVI r1,@mth_writer_class_bad
  CALL @mth_writer_class_puts
  HALT

mth_writer_class_puts:
  MOVI r4,255
mth_writer_class_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_writer_class_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_writer_class_puts_byte
  ADD r1,r1,r13
  JMP @mth_writer_class_puts_word

mth_writer_class_pass:
.str "MTH RELATION WRITER CLASS PASS\n"
mth_writer_class_bad:
.str "MTH RELATION WRITER CLASS FAIL\n"
