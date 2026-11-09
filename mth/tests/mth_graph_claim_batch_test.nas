; Native NaN16 batch probe regression: 3/1/2/0 and reject atomicity.
.org 0
JMP @gcb_test_main
.include "../nan16/mth_graph_claim_batch.nas"

gcb_test_main:
  MOVI r13,1
  MOVI r1,@gcb_records
  MOVI r2,5
  MOVI r3,@gcb_queries
  MOVI r4,4
  MOVI r5,@gcb_out
  CALL @mth_graph_claim_batch
  CMP r1,r13
  JMP[NE] @gcb_test_fail
  MOVI r7,@gcb_out
  LD r8,r7,0
  MOVI r9,3
  CMP r8,r9
  JMP[NE] @gcb_test_fail
  LD r8,r7,1
  MOVI r9,1
  CMP r8,r9
  JMP[NE] @gcb_test_fail
  LD r8,r7,2
  MOVI r9,2
  CMP r8,r9
  JMP[NE] @gcb_test_fail
  LD r8,r7,3
  CMP r8,r0
  JMP[NE] @gcb_test_fail

  ; Give every output a sentinel and mutate only the final query.
  MOVI r7,@gcb_out
  MOVI r8,77
  ST r8,r7,0
  ST r8,r7,1
  ST r8,r7,2
  ST r8,r7,3
  MOVI r7,@gcb_queries
  MOVI r8,10
  ST r8,r7,11
  MOVI r1,@gcb_records
  MOVI r2,5
  MOVI r3,@gcb_queries
  MOVI r4,4
  MOVI r5,@gcb_out
  CALL @mth_graph_claim_batch
  CMP r1,r0
  JMP[NE] @gcb_test_fail
  CALL @gcb_check_sentinels
  CMP r1,r13
  JMP[NE] @gcb_test_fail

  ; Restore query, inject invalid code in an unrelated fifth record.
  MOVI r7,@gcb_queries
  MOVI r8,4
  ST r8,r7,11
  MOVI r7,@gcb_records
  MOVI r8,3
  ST r8,r7,19
  MOVI r1,@gcb_records
  MOVI r2,5
  MOVI r3,@gcb_queries
  MOVI r4,4
  MOVI r5,@gcb_out
  CALL @mth_graph_claim_batch
  CMP r1,r0
  JMP[NE] @gcb_test_fail
  CALL @gcb_check_sentinels
  CMP r1,r13
  JMP[NE] @gcb_test_fail

  ; Restore record, reject count exceeding 1024.
  MOVI r7,@gcb_records
  MOVI r8,1
  ST r8,r7,19
  MOVI r1,@gcb_records
  MOVI r2,1025
  MOVI r3,@gcb_queries
  MOVI r4,4
  MOVI r5,@gcb_out
  CALL @mth_graph_claim_batch
  CMP r1,r0
  JMP[NE] @gcb_test_fail
  CALL @gcb_check_sentinels
  CMP r1,r13
  JMP[NE] @gcb_test_fail

  ; Reject 17 queries without reading beyond the query input.
  MOVI r1,@gcb_records
  MOVI r2,5
  MOVI r3,@gcb_queries
  MOVI r4,17
  MOVI r5,@gcb_out
  CALL @mth_graph_claim_batch
  CMP r1,r0
  JMP[NE] @gcb_test_fail
  CALL @gcb_check_sentinels
  CMP r1,r13
  JMP[NE] @gcb_test_fail

  ; A valid EMPTY batch returns absent, never unsupported/refuted.
  MOVI r1,@gcb_records
  MOVI r2,0
  MOVI r3,@gcb_queries
  MOVI r4,4
  MOVI r5,@gcb_out
  CALL @mth_graph_claim_batch
  CMP r1,r13
  JMP[NE] @gcb_test_fail
  MOVI r7,@gcb_out
  LD r8,r7,0
  CMP r8,r0
  JMP[NE] @gcb_test_fail
  LD r8,r7,1
  CMP r8,r0
  JMP[NE] @gcb_test_fail
  LD r8,r7,2
  CMP r8,r0
  JMP[NE] @gcb_test_fail
  LD r8,r7,3
  CMP r8,r0
  JMP[NE] @gcb_test_fail

  MOVI r1,@gcb_pass
  CALL @gcb_puts
  HALT

; Return r1=1 if each output still 77, without other modifications.
gcb_check_sentinels:
  MOVI r7,@gcb_out
  MOVI r9,77
  LD r8,r7,0
  CMP r8,r9
  JMP[NE] @gcb_check_fail
  LD r8,r7,1
  CMP r8,r9
  JMP[NE] @gcb_check_fail
  LD r8,r7,2
  CMP r8,r9
  JMP[NE] @gcb_check_fail
  LD r8,r7,3
  CMP r8,r9
  JMP[NE] @gcb_check_fail
  MOVI r1,1
  RET
gcb_check_fail:
  MOVI r1,0
  RET

gcb_test_fail:
  MOVI r1,@gcb_fail
  CALL @gcb_puts
  HALT

gcb_puts:
  MOVI r4,255
gcb_puts_word:
  LD r2,r1,0
  MOVI r3,4
gcb_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @gcb_puts_byte
  ADD r1,r1,r13
  JMP @gcb_puts_word

gcb_pass:
.str "MTH GRAPH CLAIM BATCH PASS\n"
gcb_fail:
.str "MTH GRAPH CLAIM BATCH FAIL\n"

.org 4096
gcb_records:
.word 7,265,4,1
.word 7,265,4,2
.word 265,9,4,2
.word 7,265,5,1
.word 7,266,4,1
.org 4500
gcb_queries:
.word 7,265,4
.word 7,265,5
.word 265,9,4
.word 7,267,4
.org 5000
gcb_out:
.word 0,0,0,0
