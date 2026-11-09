; Bounded NaN16 native multi-query graph claim batch.
; Candidate-only, read-only, no inference of mathematical entailment.
; A caller MUST provide a complete independently replay-verified immutable
; graph snapshot; no signature, provenance or lease is checked in this guest.
;
; ABI r0=0, r13=1:
; r1 records U32[4*n] [src,dst,layer,code], code 1 supports or 2 refutes
; r2 n = 0..1024
; r3 queries U32[3*q] [src,dst,layer]
; r4 q = 1..16
; r5 results U32[q] caller-owned, MUST NOT alias either input.
; returns r1=1 on success and U32 mask 0 absent/1 support/2 refute/3 both
; returns r1=0 for malformed records/queries/count, output untouched.
; Checks EVERY record AND query before writing any result, including
; unrelated records and the final query; caller must keep all inputs
; immutable throughout the operation.
; Clobbers r1,r6-r12,r14,flags; preserves r2-r5,r13,r15.
mth_graph_claim_batch:
  CMP r2,r0
  JMP[LT] @mth_gcb_invalid
  MOVI r6,1024
  CMP r2,r6
  JMP[GT] @mth_gcb_invalid
  MOVI r6,1
  CMP r4,r6
  JMP[LT] @mth_gcb_invalid
  MOVI r6,16
  CMP r4,r6
  JMP[GT] @mth_gcb_invalid

  ; Phase 1: all records validated, no output writes.
  ADD r6,r1,r0
  ADD r7,r2,r0
mth_gcb_record_next:
  CMP r7,r0
  JMP[EQ] @mth_gcb_records_valid
  LD r8,r6,0
  CMP r8,r0
  JMP[LT] @mth_gcb_invalid
  MOVI r9,32896
  CMP r8,r9
  JMP[GE] @mth_gcb_invalid
  LD r8,r6,1
  CMP r8,r0
  JMP[LT] @mth_gcb_invalid
  CMP r8,r9
  JMP[GE] @mth_gcb_invalid
  LD r8,r6,2
  CMP r8,r0
  JMP[LT] @mth_gcb_invalid
  MOVI r9,10
  CMP r8,r9
  JMP[GE] @mth_gcb_invalid
  LD r8,r6,3
  MOVI r9,1
  CMP r8,r9
  JMP[EQ] @mth_gcb_record_good
  MOVI r9,2
  CMP r8,r9
  JMP[NE] @mth_gcb_invalid
mth_gcb_record_good:
  ADDI r6,r6,4
  SUB r7,r7,r13
  JMP @mth_gcb_record_next

  ; Phase 2: validate all q queries before any output writes.
mth_gcb_records_valid:
  ADD r6,r3,r0
  ADD r7,r4,r0
mth_gcb_query_next:
  CMP r7,r0
  JMP[EQ] @mth_gcb_queries_valid
  LD r8,r6,0
  CMP r8,r0
  JMP[LT] @mth_gcb_invalid
  MOVI r9,32896
  CMP r8,r9
  JMP[GE] @mth_gcb_invalid
  LD r8,r6,1
  CMP r8,r0
  JMP[LT] @mth_gcb_invalid
  CMP r8,r9
  JMP[GE] @mth_gcb_invalid
  LD r8,r6,2
  CMP r8,r0
  JMP[LT] @mth_gcb_invalid
  MOVI r9,10
  CMP r8,r9
  JMP[GE] @mth_gcb_invalid
  ADDI r6,r6,3
  SUB r7,r7,r13
  JMP @mth_gcb_query_next

  ; Phase 3: exact matching directed tuples; only now write q masks.
mth_gcb_queries_valid:
  ADD r6,r3,r0
  ADD r7,r4,r0
  ADD r12,r5,r0
mth_gcb_eval_next:
  CMP r7,r0
  JMP[EQ] @mth_gcb_success
  ADD r8,r1,r0
  ADD r9,r2,r0
  MOVI r14,0
mth_gcb_eval_record:
  CMP r9,r0
  JMP[EQ] @mth_gcb_write
  LD r10,r8,0
  LD r11,r6,0
  CMP r10,r11
  JMP[NE] @mth_gcb_advance
  LD r10,r8,1
  LD r11,r6,1
  CMP r10,r11
  JMP[NE] @mth_gcb_advance
  LD r10,r8,2
  LD r11,r6,2
  CMP r10,r11
  JMP[NE] @mth_gcb_advance
  LD r10,r8,3
  BOOL.14 r14,r14,r10
mth_gcb_advance:
  ADDI r8,r8,4
  SUB r9,r9,r13
  JMP @mth_gcb_eval_record
mth_gcb_write:
  ST r14,r12,0
  ADD r12,r12,r13
  ADDI r6,r6,3
  SUB r7,r7,r13
  JMP @mth_gcb_eval_next

mth_gcb_success:
  MOVI r1,1
  RET
mth_gcb_invalid:
  MOVI r1,0
  RET
