; NaN16 global motif reducer: 16 candidate triheads, 3 tri-state edges each.
; Edge values 0=OBSERVED COLD,1=OBSERVED HOT,2=UNKNOWN.
; Hot/cold thresholds are >=2/3, not endpoint head-vote counts.
; ABI r1=motifs[16][3] U32, r2=flags_out[16] U32,
; r3=summary_out[6] U32, r4=scratch[22] U32, all disjoint.
; Summary: [hot111,hot_ge2,cold000,cold_ge2,has_unknown,has_mixed].
; Includes full counts (111 also counts as ge2), not disjoint bins.
; Invalid edge (>2) rejects atomically r1=0,r9=1; success r1=1,r9=0.
; This forms a GLOBAL hot/cold readout from the simplicial candidate list,
; without conflating "zero relationship" with unknown or writing root cells.
mth_global_motif_reduce16:
  MOVI r0,0
  MOVI r5,0
mth_gmr16_clear:
  ADDI r6,r4,16
  ADD r6,r6,r5
  ST r0,r6,0
  ADDI r5,r5,1
  MOVI r6,6
  CMP r5,r6
  JMP[LT] @mth_gmr16_clear
  MOVI r5,0
mth_gmr16_triangle:
  MOVI r6,0
  MOVI r7,0
  MOVI r8,0
  MOVI r9,0
mth_gmr16_edge:
  MOVI r10,3
  MUL r10,r5,r10
  ADD r10,r10,r6
  ADD r10,r1,r10
  LD r11,r10,0
  CMP r11,r0
  JMP[EQ] @mth_gmr16_is_cold
  MOVI r10,1
  CMP r11,r10
  JMP[EQ] @mth_gmr16_is_hot
  MOVI r10,2
  CMP r11,r10
  JMP[NE] @mth_gmr16_bad
  ADDI r9,r9,1
  JMP @mth_gmr16_edge_next
mth_gmr16_is_cold:
  ADDI r8,r8,1
  JMP @mth_gmr16_edge_next
mth_gmr16_is_hot:
  ADDI r7,r7,1
mth_gmr16_edge_next:
  ADDI r6,r6,1
  MOVI r10,3
  CMP r6,r10
  JMP[LT] @mth_gmr16_edge
  MOVI r12,0             ; output bit flags
  MOVI r10,2
  CMP r7,r10
  JMP[LT] @mth_gmr16_no_hot2
  ADDI r12,r12,2
  LD r10,r4,17
  ADDI r10,r10,1
  ST r10,r4,17
mth_gmr16_no_hot2:
  MOVI r10,3
  CMP r7,r10
  JMP[NE] @mth_gmr16_no_hot3
  ADDI r12,r12,1
  LD r10,r4,16
  ADDI r10,r10,1
  ST r10,r4,16
mth_gmr16_no_hot3:
  MOVI r10,2
  CMP r8,r10
  JMP[LT] @mth_gmr16_no_cold2
  ADDI r12,r12,8
  LD r10,r4,19
  ADDI r10,r10,1
  ST r10,r4,19
mth_gmr16_no_cold2:
  MOVI r10,3
  CMP r8,r10
  JMP[NE] @mth_gmr16_no_cold3
  ADDI r12,r12,4
  LD r10,r4,18
  ADDI r10,r10,1
  ST r10,r4,18
mth_gmr16_no_cold3:
  CMP r9,r0
  JMP[EQ] @mth_gmr16_no_unknown
  LD r10,r4,20
  ADDI r10,r10,1
  ST r10,r4,20
mth_gmr16_no_unknown:
  CMP r7,r0
  JMP[EQ] @mth_gmr16_no_mixed
  CMP r8,r0
  JMP[EQ] @mth_gmr16_no_mixed
  LD r10,r4,21
  ADDI r10,r10,1
  ST r10,r4,21
mth_gmr16_no_mixed:
  ADD r10,r4,r5
  ST r12,r10,0
  ADDI r5,r5,1
  MOVI r10,16
  CMP r5,r10
  JMP[LT] @mth_gmr16_triangle
  MOVI r5,0
mth_gmr16_publish_flags:
  ADD r6,r4,r5
  LD r7,r6,0
  ADD r6,r2,r5
  ST r7,r6,0
  ADDI r5,r5,1
  MOVI r6,16
  CMP r5,r6
  JMP[LT] @mth_gmr16_publish_flags
  MOVI r5,0
mth_gmr16_publish_sums:
  ADDI r6,r4,16
  ADD r6,r6,r5
  LD r7,r6,0
  ADD r6,r3,r5
  ST r7,r6,0
  ADDI r5,r5,1
  MOVI r6,6
  CMP r5,r6
  JMP[LT] @mth_gmr16_publish_sums
  MOVI r1,1
  MOVI r9,0
  RET
mth_gmr16_bad:
  MOVI r1,0
  MOVI r9,1
  RET
