; Native NaN16 claim lookup: same edge has both supports and refutes.
; Test all 4 result masks, full-batch reject atomicity and query bounds.
.org 0
JMP @gcp_test_main
.include "../nan16/mth_graph_claim_probe.nas"

gcp_test_main:
  MOVI r13,1

  ; Exact opposing claims: a support filter must not hide a refutation.
  MOVI r1,@gcp_records
  MOVI r2,5
  MOVI r3,7
  MOVI r4,265
  MOVI r5,4
  MOVI r6,@gcp_out
  CALL @mth_graph_claim_probe
  CMP r1,r13
  JMP[NE] @gcp_test_fail
  MOVI r6,@gcp_out
  LD r8,r6,0
  MOVI r9,3
  CMP r8,r9
  JMP[NE] @gcp_test_fail

  ; Same pair, different layer: supports only.
  MOVI r1,@gcp_records
  MOVI r2,5
  MOVI r3,7
  MOVI r4,265
  MOVI r5,5
  MOVI r6,@gcp_out
  CALL @mth_graph_claim_probe
  CMP r1,r13
  JMP[NE] @gcp_test_fail
  MOVI r6,@gcp_out
  LD r8,r6,0
  MOVI r9,1
  CMP r8,r9
  JMP[NE] @gcp_test_fail

  ; Another directed pair: refutes only.
  MOVI r1,@gcp_records
  MOVI r2,5
  MOVI r3,265
  MOVI r4,9
  MOVI r5,4
  MOVI r6,@gcp_out
  CALL @mth_graph_claim_probe
  CMP r1,r13
  JMP[NE] @gcp_test_fail
  MOVI r6,@gcp_out
  LD r8,r6,0
  MOVI r9,2
  CMP r8,r9
  JMP[NE] @gcp_test_fail

  ; Unseen pair: absent, not false.
  MOVI r1,@gcp_records
  MOVI r2,5
  MOVI r3,7
  MOVI r4,266
  MOVI r5,4
  MOVI r6,@gcp_out
  CALL @mth_graph_claim_probe
  CMP r1,r13
  JMP[NE] @gcp_test_fail
  MOVI r6,@gcp_out
  LD r8,r6,0
  CMP r8,r0
  JMP[NE] @gcp_test_fail

  ; Invalid relation on a DIFFERENT record fails without writing result.
  MOVI r7,@gcp_records
  MOVI r8,3
  ST r8,r7,19
  MOVI r7,@gcp_out
  MOVI r8,77
  ST r8,r7,0
  MOVI r1,@gcp_records
  MOVI r2,5
  MOVI r3,7
  MOVI r4,265
  MOVI r5,4
  MOVI r6,@gcp_out
  CALL @mth_graph_claim_probe
  CMP r1,r0
  JMP[NE] @gcp_test_fail
  MOVI r7,@gcp_out
  LD r8,r7,0
  MOVI r9,77
  CMP r8,r9
  JMP[NE] @gcp_test_fail

  ; Restore record, then invalid src (32896) rejects atomically.
  MOVI r7,@gcp_records
  MOVI r8,1
  ST r8,r7,19
  MOVI r1,@gcp_records
  MOVI r2,5
  MOVI r3,32896
  MOVI r4,265
  MOVI r5,4
  MOVI r6,@gcp_out
  CALL @mth_graph_claim_probe
  CMP r1,r0
  JMP[NE] @gcp_test_fail
  MOVI r7,@gcp_out
  LD r8,r7,0
  MOVI r9,77
  CMP r8,r9
  JMP[NE] @gcp_test_fail

  ; Count beyond 1024 rejected before any record read/output write.
  MOVI r1,@gcp_records
  MOVI r2,1025
  MOVI r3,7
  MOVI r4,265
  MOVI r5,4
  MOVI r6,@gcp_out
  CALL @mth_graph_claim_probe
  CMP r1,r0
  JMP[NE] @gcp_test_fail
  MOVI r7,@gcp_out
  LD r8,r7,0
  MOVI r9,77
  CMP r8,r9
  JMP[NE] @gcp_test_fail

  ; Invalid L10 layer rejected (only L0-L9 exist).
  MOVI r1,@gcp_records
  MOVI r2,5
  MOVI r3,7
  MOVI r4,265
  MOVI r5,10
  MOVI r6,@gcp_out
  CALL @mth_graph_claim_probe
  CMP r1,r0
  JMP[NE] @gcp_test_fail
  MOVI r7,@gcp_out
  LD r8,r7,0
  MOVI r9,77
  CMP r8,r9
  JMP[NE] @gcp_test_fail

  ; Even a non-matching row with illegal canonical node must reject.
  MOVI r7,@gcp_records
  MOVI r8,32896
  ST r8,r7,16
  MOVI r1,@gcp_records
  MOVI r2,5
  MOVI r3,7
  MOVI r4,265
  MOVI r5,4
  MOVI r6,@gcp_out
  CALL @mth_graph_claim_probe
  CMP r1,r0
  JMP[NE] @gcp_test_fail
  MOVI r7,@gcp_out
  LD r8,r7,0
  MOVI r9,77
  CMP r8,r9
  JMP[NE] @gcp_test_fail

  MOVI r1,@gcp_pass
  CALL @gcp_puts
  HALT

gcp_test_fail:
  MOVI r1,@gcp_fail
  CALL @gcp_puts
  HALT

gcp_puts:
  MOVI r4,255
gcp_puts_word:
  LD r2,r1,0
  MOVI r3,4
gcp_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @gcp_puts_byte
  ADD r1,r1,r13
  JMP @gcp_puts_word

gcp_pass:
.str "MTH GRAPH CLAIM PROBE PASS\n"
gcp_fail:
.str "MTH GRAPH CLAIM PROBE FAIL\n"

.org 4096
gcp_records:
.word 7,265,4,1
.word 7,265,4,2
.word 265,9,4,2
.word 7,265,5,1
.word 7,265,4,1
.org 5000
gcp_out:
.word 0
