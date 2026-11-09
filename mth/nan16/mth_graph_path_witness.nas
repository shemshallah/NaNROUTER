; NaN16 native witness validation for bounded candidate paths.
;
; Verify the concrete directed route produced by HERMES graph navigation
; against EVERY active support/refute relation in a separately replay-verified
; graph snapshot. This does not discover a route, infer a theorem, or authorize
; model learning. Ed25519 and evidence audits are external preconditions.
;
; ABI (r0 = 0, r13 = 1):
; r1 = record U32[4 * n]: [src,dst,layer,relation] (relation 1 or 2)
; r2 = n, 0..1024
; r3 = witness U32[3 * hops]: [src,dst,layer] per directed hop
; r4 = hops, 1..8
; r5 = output U32[8] (no overlap with either input)
; returns r1=1 iff every hop has >=1 active candidate; r1=0 otherwise.
; Output on success is a mask per hop: 1 supports, 2 refutes, 3 contested.
; Every malformed record, invalid node/layer, broken witness chain, or
; absent candidate rejects without changing ANY output word. Output beyond
; the number of hops is untouched on success.
;
; This kernel validates the ENTIRE batch and witness before computing
; results, then scans twice, once to prove all hops exist and again to write
; outputs, ensuring reject atomicity without any caller scratch buffer.
; It does not treat an isa/support path as logical entailment.
; clobbers r1,r6-r12,r14 and flags; preserves r2-r5,r13,r15.
mth_graph_path_witness:
  CMP r2,r0
  JMP[LT] @mth_gpw_invalid
  MOVI r6,1024
  CMP r2,r6
  JMP[GT] @mth_gpw_invalid
  MOVI r6,1
  CMP r4,r6
  JMP[LT] @mth_gpw_invalid
  MOVI r6,8
  CMP r4,r6
  JMP[GT] @mth_gpw_invalid

  ; Phase 1: validate all graph records, including unrelated rows.
  ADD r6,r1,r0
  ADD r7,r2,r0
mth_gpw_record_next:
  CMP r7,r0
  JMP[EQ] @mth_gpw_record_validated
  LD r8,r6,0
  CMP r8,r0
  JMP[LT] @mth_gpw_invalid
  MOVI r9,32896
  CMP r8,r9
  JMP[GE] @mth_gpw_invalid
  LD r8,r6,1
  CMP r8,r0
  JMP[LT] @mth_gpw_invalid
  CMP r8,r9
  JMP[GE] @mth_gpw_invalid
  LD r8,r6,2
  CMP r8,r0
  JMP[LT] @mth_gpw_invalid
  MOVI r9,10
  CMP r8,r9
  JMP[GE] @mth_gpw_invalid
  LD r8,r6,3
  MOVI r9,1
  CMP r8,r9
  JMP[EQ] @mth_gpw_record_ok
  MOVI r9,2
  CMP r8,r9
  JMP[NE] @mth_gpw_invalid
mth_gpw_record_ok:
  ADDI r6,r6,4
  SUB r7,r7,r13
  JMP @mth_gpw_record_next

  ; Phase 2: validate every witness hop and exact chained endpoints.
mth_gpw_record_validated:
  ADD r6,r3,r0
  MOVI r7,0
  MOVI r11,0
mth_gpw_witness_next:
  CMP r7,r4
  JMP[GE] @mth_gpw_witness_validated
  LD r8,r6,0
  CMP r8,r0
  JMP[LT] @mth_gpw_invalid
  MOVI r9,32896
  CMP r8,r9
  JMP[GE] @mth_gpw_invalid
  CMP r7,r0
  JMP[EQ] @mth_gpw_chain_ok
  CMP r8,r11
  JMP[NE] @mth_gpw_invalid
mth_gpw_chain_ok:
  LD r11,r6,1
  CMP r11,r0
  JMP[LT] @mth_gpw_invalid
  CMP r11,r9
  JMP[GE] @mth_gpw_invalid
  LD r8,r6,2
  CMP r8,r0
  JMP[LT] @mth_gpw_invalid
  MOVI r9,10
  CMP r8,r9
  JMP[GE] @mth_gpw_invalid
  ADDI r6,r6,3
  ADD r7,r7,r13
  JMP @mth_gpw_witness_next

  ; Phase 3: every hop must have at least one exact active claim.
  ; Scan once WITHOUT output writes, then scan again to store masks.
mth_gpw_witness_validated:
  ADD r6,r3,r0
  ADD r7,r4,r0
mth_gpw_precheck_hop:
  CMP r7,r0
  JMP[EQ] @mth_gpw_all_hops_found
  ADD r8,r1,r0
  ADD r9,r2,r0
  MOVI r14,0
mth_gpw_precheck_record:
  CMP r9,r0
  JMP[EQ] @mth_gpw_precheck_done
  LD r10,r8,0
  LD r11,r6,0
  CMP r10,r11
  JMP[NE] @mth_gpw_precheck_advance
  LD r10,r8,1
  LD r11,r6,1
  CMP r10,r11
  JMP[NE] @mth_gpw_precheck_advance
  LD r10,r8,2
  LD r11,r6,2
  CMP r10,r11
  JMP[NE] @mth_gpw_precheck_advance
  LD r10,r8,3
  BOOL.14 r14,r14,r10
mth_gpw_precheck_advance:
  ADDI r8,r8,4
  SUB r9,r9,r13
  JMP @mth_gpw_precheck_record
mth_gpw_precheck_done:
  CMP r14,r0
  JMP[EQ] @mth_gpw_invalid
  ADDI r6,r6,3
  SUB r7,r7,r13
  JMP @mth_gpw_precheck_hop

  ; Phase 4: recompute exact masks and commit outputs after full validation.
mth_gpw_all_hops_found:
  ADD r6,r3,r0
  ADD r7,r4,r0
  ADD r12,r5,r0
mth_gpw_write_hop:
  CMP r7,r0
  JMP[EQ] @mth_gpw_success
  ADD r8,r1,r0
  ADD r9,r2,r0
  MOVI r14,0
mth_gpw_write_record:
  CMP r9,r0
  JMP[EQ] @mth_gpw_write_done
  LD r10,r8,0
  LD r11,r6,0
  CMP r10,r11
  JMP[NE] @mth_gpw_write_advance
  LD r10,r8,1
  LD r11,r6,1
  CMP r10,r11
  JMP[NE] @mth_gpw_write_advance
  LD r10,r8,2
  LD r11,r6,2
  CMP r10,r11
  JMP[NE] @mth_gpw_write_advance
  LD r10,r8,3
  BOOL.14 r14,r14,r10
mth_gpw_write_advance:
  ADDI r8,r8,4
  SUB r9,r9,r13
  JMP @mth_gpw_write_record
mth_gpw_write_done:
  ST r14,r12,0
  ADD r12,r12,r13
  ADDI r6,r6,3
  SUB r7,r7,r13
  JMP @mth_gpw_write_hop

mth_gpw_success:
  MOVI r1,1
  RET
mth_gpw_invalid:
  MOVI r1,0
  RET
