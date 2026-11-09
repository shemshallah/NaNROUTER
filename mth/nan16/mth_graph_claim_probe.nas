; MTH native contradiction-preserving claim probe — NaN16 only.
;
; Inbound claims MUST already come from a separately verified HERMES
; history/state snapshot. This primitive checks an in-guest bounded edge
; batch and answers a single directed L0-L9 support/refute question.
; It never authenticates a sender, proves a fact, promotes evidence,
; executes a learning update, or writes any universe/chart state.
;
; ABI (r0=0; r13=1):
;   r1 = records, count * 4 U32 words: [src,dst,layer,relation]
;   r2 = number of records, 0..1024
;   r3 = query src, 0..32895 (head 0..255, MP 256..32895)
;   r4 = query dst, 0..32895
;   r5 = query layer, 0..9
;   r6 = one-word output pointer (must not alias records)
;   returns r1=1 on success; r1=0 on invalid query or record.
;   On success output: 0 absent, 1 supports, 2 refutes, 3 BOTH.
;   On rejection output is not touched. No other memory is written.
;
; Each input record is a currently active, candidate relation:
;   relation=1 supports, relation=2 refutes. Anything else is rejected.
; No implicit transitivity, default inheritance, or logical entailment.
; The caller must bind all records to the authenticated graph history and
; its digest separately. The guest checks the ENTIRE batch before writing
; output, including records that do not match the requested tuple.
;
; Caller owns valid/non-aliasing pointer spans. Clobbers r1,r7-r12,r14;
; preserves r2-r6,r13,r15. Does not use static storage.
mth_graph_claim_probe:
  ; Validate bounded query before reading a record or writing output.
  CMP r2,r0
  JMP[LT] @mth_gcp_invalid
  MOVI r7,1024
  CMP r2,r7
  JMP[GT] @mth_gcp_invalid
  CMP r3,r0
  JMP[LT] @mth_gcp_invalid
  MOVI r7,32896
  CMP r3,r7
  JMP[GE] @mth_gcp_invalid
  CMP r4,r0
  JMP[LT] @mth_gcp_invalid
  CMP r4,r7
  JMP[GE] @mth_gcp_invalid
  CMP r5,r0
  JMP[LT] @mth_gcp_invalid
  MOVI r7,10
  CMP r5,r7
  JMP[GE] @mth_gcp_invalid

  ; Phase 1: validate EVERY source, destination, layer, relation.
  ADD r7,r1,r0
  ADD r8,r2,r0
mth_gcp_validate_next:
  CMP r8,r0
  JMP[EQ] @mth_gcp_validated
  LD r9,r7,0
  CMP r9,r0
  JMP[LT] @mth_gcp_invalid
  MOVI r10,32896
  CMP r9,r10
  JMP[GE] @mth_gcp_invalid
  LD r9,r7,1
  CMP r9,r0
  JMP[LT] @mth_gcp_invalid
  CMP r9,r10
  JMP[GE] @mth_gcp_invalid
  LD r9,r7,2
  CMP r9,r0
  JMP[LT] @mth_gcp_invalid
  MOVI r10,10
  CMP r9,r10
  JMP[GE] @mth_gcp_invalid
  LD r9,r7,3
  MOVI r10,1
  CMP r9,r10
  JMP[EQ] @mth_gcp_valid_record
  MOVI r10,2
  CMP r9,r10
  JMP[NE] @mth_gcp_invalid
mth_gcp_valid_record:
  ADDI r7,r7,4
  SUB r8,r8,r13
  JMP @mth_gcp_validate_next

  ; Phase 2: exact tuple equality with OR of both opposing claims.
mth_gcp_validated:
  ADD r7,r1,r0
  ADD r8,r2,r0
  MOVI r14,0
mth_gcp_scan_next:
  CMP r8,r0
  JMP[EQ] @mth_gcp_success
  LD r9,r7,0
  CMP r9,r3
  JMP[NE] @mth_gcp_scan_advance
  LD r9,r7,1
  CMP r9,r4
  JMP[NE] @mth_gcp_scan_advance
  LD r9,r7,2
  CMP r9,r5
  JMP[NE] @mth_gcp_scan_advance
  LD r9,r7,3
  BOOL.14 r14,r14,r9
mth_gcp_scan_advance:
  ADDI r7,r7,4
  SUB r8,r8,r13
  JMP @mth_gcp_scan_next

mth_gcp_success:
  ST r14,r6,0
  MOVI r1,1
  RET
mth_gcp_invalid:
  MOVI r1,0
  RET
