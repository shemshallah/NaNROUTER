; NaN16 bounded 3-hop candidate witness and reject-atomicity fixture.
.org 0
JMP @gpw_test_main
.include "../nan16/mth_graph_path_witness.nas"

gpw_test_main:
  MOVI r13,1

  ; Three verified candidate hops, first contested (both sides retained).
  MOVI r1,@gpw_records
  MOVI r2,5
  MOVI r3,@gpw_witness
  MOVI r4,3
  MOVI r5,@gpw_output
  CALL @mth_graph_path_witness
  CMP r1,r13
  JMP[NE] @gpw_test_fail
  MOVI r6,@gpw_output
  LD r7,r6,0
  MOVI r8,3
  CMP r7,r8
  JMP[NE] @gpw_test_fail
  LD r7,r6,1
  MOVI r8,1
  CMP r7,r8
  JMP[NE] @gpw_test_fail
  LD r7,r6,2
  MOVI r8,2
  CMP r7,r8
  JMP[NE] @gpw_test_fail
  LD r7,r6,3
  MOVI r8,99
  CMP r7,r8
  JMP[NE] @gpw_test_fail

  ; Broken chain: second hop source != first hop destination.
  MOVI r6,@gpw_output
  MOVI r8,77
  ST r8,r6,0
  ST r8,r6,1
  ST r8,r6,2
  MOVI r6,@gpw_witness
  MOVI r7,7
  ST r7,r6,3
  MOVI r1,@gpw_records
  MOVI r2,5
  MOVI r3,@gpw_witness
  MOVI r4,3
  MOVI r5,@gpw_output
  CALL @mth_graph_path_witness
  CMP r1,r0
  JMP[NE] @gpw_test_fail
  CALL @gpw_check_untouched
  MOVI r6,@gpw_witness
  MOVI r7,265
  ST r7,r6,3

  ; Chained, but third hop absent from all candidate records.
  MOVI r6,@gpw_witness
  MOVI r7,268
  ST r7,r6,7
  MOVI r1,@gpw_records
  MOVI r2,5
  MOVI r3,@gpw_witness
  MOVI r4,3
  MOVI r5,@gpw_output
  CALL @mth_graph_path_witness
  CMP r1,r0
  JMP[NE] @gpw_test_fail
  CALL @gpw_check_untouched
  MOVI r6,@gpw_witness
  MOVI r7,267
  ST r7,r6,7

  ; Bad unrelated relation must invalidate the ENTIRE batch.
  MOVI r6,@gpw_records
  MOVI r7,3
  ST r7,r6,19
  MOVI r1,@gpw_records
  MOVI r2,5
  MOVI r3,@gpw_witness
  MOVI r4,3
  MOVI r5,@gpw_output
  CALL @mth_graph_path_witness
  CMP r1,r0
  JMP[NE] @gpw_test_fail
  CALL @gpw_check_untouched
  MOVI r6,@gpw_records
  MOVI r7,2
  ST r7,r6,19

  ; Illegal canonical endpoint and L10 witness rejected.
  MOVI r6,@gpw_witness
  MOVI r7,32896
  ST r7,r6,0
  MOVI r1,@gpw_records
  MOVI r2,5
  MOVI r3,@gpw_witness
  MOVI r4,3
  MOVI r5,@gpw_output
  CALL @mth_graph_path_witness
  CMP r1,r0
  JMP[NE] @gpw_test_fail
  CALL @gpw_check_untouched
  MOVI r6,@gpw_witness
  MOVI r7,7
  ST r7,r6,0

  MOVI r6,@gpw_witness
  MOVI r7,10
  ST r7,r6,2
  MOVI r1,@gpw_records
  MOVI r2,5
  MOVI r3,@gpw_witness
  MOVI r4,3
  MOVI r5,@gpw_output
  CALL @mth_graph_path_witness
  CMP r1,r0
  JMP[NE] @gpw_test_fail
  CALL @gpw_check_untouched
  MOVI r6,@gpw_witness
  MOVI r7,4
  ST r7,r6,2

  ; Hop limit and record limit must fail before reading payloads.
  MOVI r1,@gpw_records
  MOVI r2,5
  MOVI r3,@gpw_witness
  MOVI r4,9
  MOVI r5,@gpw_output
  CALL @mth_graph_path_witness
  CMP r1,r0
  JMP[NE] @gpw_test_fail
  CALL @gpw_check_untouched

  MOVI r1,@gpw_records
  MOVI r2,1025
  MOVI r3,@gpw_witness
  MOVI r4,3
  MOVI r5,@gpw_output
  CALL @mth_graph_path_witness
  CMP r1,r0
  JMP[NE] @gpw_test_fail
  CALL @gpw_check_untouched

  MOVI r1,@gpw_pass
  CALL @gpw_puts
  HALT

gpw_check_untouched:
  MOVI r6,@gpw_output
  MOVI r8,77
  LD r7,r6,0
  CMP r7,r8
  JMP[NE] @gpw_test_fail
  LD r7,r6,1
  CMP r7,r8
  JMP[NE] @gpw_test_fail
  LD r7,r6,2
  CMP r7,r8
  JMP[NE] @gpw_test_fail
  RET

gpw_test_fail:
  MOVI r1,@gpw_fail
  CALL @gpw_puts
  HALT

gpw_puts:
  MOVI r4,255
gpw_puts_word:
  LD r2,r1,0
  MOVI r3,4
gpw_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @gpw_puts_byte
  ADD r1,r1,r13
  JMP @gpw_puts_word

gpw_pass:
.str "MTH GRAPH PATH WITNESS PASS\n"
gpw_fail:
.str "MTH GRAPH PATH WITNESS FAIL\n"

.org 4096
gpw_records:
.word 7,265,4,1
.word 7,265,4,2
.word 265,9,5,1
.word 9,267,8,2
.word 40,41,9,2

.org 5000
gpw_witness:
.word 7,265,4
.word 265,9,5
.word 9,267,8

.org 6000
gpw_output:
.word 99,99,99,99,99,99,99,99
