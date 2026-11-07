; MTH connected components / Laplacian nullity v1 — NaN16 only.
; Synchronous minimum-label propagation over caller-validated symmetric CSR.
; ABI: r1=offsets[257], r2=neighbors, r3=edge_count,
; r4=labels_out[256], r5=labels_tmp[256], r6=component_count_out,
; r7=16-word scratch, r13=1.
; Returns 1 success, 0 bad count, 2 bad offsets, 3 bad endpoint, 5 no convergence.
; CSR symmetry, sorted unique rows, no self loops and digest are caller preconditions.
; For undirected graphs, minimum vertex ID propagates one edge per round;
; at most 255 rounds for 256 vertices. Count of label[v]==v equals nullity(L).
; Spans must not overlap. Outputs are committed only after convergence.

mth_graph_components_nullity_v1:
  ADD r11,r7,r0
  ST r1,r11,0
  ST r2,r11,1
  ST r3,r11,2
  ST r4,r11,3
  ST r5,r11,4
  ST r6,r11,5
  ST r4,r11,12
  CMP r3,r0
  JMP[LT] @mth_comp_bad_count
  MOVI r8,65280
  CMP r3,r8
  JMP[GT] @mth_comp_bad_count

  ; Validate offsets and max degree.
  LD r8,r11,0
  LD r9,r8,0
  CMP r9,r0
  JMP[NE] @mth_comp_bad_offsets
  MOVI r10,257
  MOVI r12,0
mth_comp_validate_offsets:
  LD r9,r8,0
  CMP r9,r12
  JMP[LT] @mth_comp_bad_offsets
  LD r1,r11,2
  CMP r9,r1
  JMP[GT] @mth_comp_bad_offsets
  SUB r1,r9,r12
  MOVI r2,255
  CMP r1,r2
  JMP[GT] @mth_comp_bad_offsets
  ADD r12,r9,r0
  ADD r8,r8,r13
  SUB r10,r10,r13
  CMP r10,r0
  JMP[GT] @mth_comp_validate_offsets
  LD r1,r11,2
  CMP r12,r1
  JMP[NE] @mth_comp_bad_offsets

  ; Validate neighbor U8 encoding and range.
  LD r8,r11,1
  LD r9,r11,2
mth_comp_validate_neighbors:
  CMP r9,r0
  JMP[EQ] @mth_comp_initialize
  LD r10,r8,0
  SHR r12,r10,8
  CMP r12,r0
  JMP[NE] @mth_comp_bad_neighbors
  MOVI r1,256
  CMP r10,r1
  JMP[LT] @mth_comp_neighbor_ok
  JMP @mth_comp_bad_neighbors
mth_comp_neighbor_ok:
  ADD r8,r8,r13
  SUB r9,r9,r13
  JMP @mth_comp_validate_neighbors

mth_comp_initialize:
  LD r8,r11,3
  MOVI r9,0
  MOVI r10,256
mth_comp_init_loop:
  ST r9,r8,0
  ADD r8,r8,r13
  ADD r9,r9,r13
  SUB r10,r10,r13
  CMP r10,r0
  JMP[GT] @mth_comp_init_loop
  MOVI r8,0
  ST r8,r11,6
  ST r8,r11,11

mth_comp_round:
  LD r8,r11,6
  MOVI r9,255
  CMP r8,r9
  JMP[GE] @mth_comp_no_converge

  ; Copy active labels into next buffer.
  LD r8,r11,3
  LD r9,r11,4
  MOVI r10,256
mth_comp_copy:
  LD r12,r8,0
  ST r12,r9,0
  ADD r8,r8,r13
  ADD r9,r9,r13
  SUB r10,r10,r13
  CMP r10,r0
  JMP[GT] @mth_comp_copy

  MOVI r8,0
  ST r8,r11,7
  ST r8,r11,11

mth_comp_row:
  LD r8,r11,7
  MOVI r9,256
  CMP r8,r9
  JMP[GE] @mth_comp_round_done
  LD r9,r11,0
  ADD r9,r9,r8
  LD r10,r9,0
  ADD r9,r9,r13
  LD r12,r9,0
  ST r10,r11,8
  ST r12,r11,9
  LD r9,r11,3
  ADD r9,r9,r8
  LD r10,r9,0
  ST r10,r11,10

mth_comp_edge:
  LD r9,r11,8
  LD r10,r11,9
  CMP r9,r10
  JMP[GE] @mth_comp_store
  LD r12,r11,1
  ADD r12,r12,r9
  LD r12,r12,0
  LD r1,r11,3
  ADD r1,r1,r12
  LD r1,r1,0
  LD r2,r11,10
  CMP r1,r2
  JMP[GE] @mth_comp_edge_next
  ST r1,r11,10
mth_comp_edge_next:
  LD r9,r11,8
  ADD r9,r9,r13
  ST r9,r11,8
  JMP @mth_comp_edge

mth_comp_store:
  LD r8,r11,7
  LD r9,r11,4
  ADD r9,r9,r8
  LD r10,r11,10
  ST r10,r9,0
  LD r1,r11,3
  ADD r1,r1,r8
  LD r2,r1,0
  CMP r2,r10
  JMP[EQ] @mth_comp_row_next
  MOVI r1,1
  ST r1,r11,11
mth_comp_row_next:
  LD r8,r11,7
  ADD r8,r8,r13
  ST r8,r11,7
  JMP @mth_comp_row

mth_comp_round_done:
  LD r8,r11,11
  CMP r8,r0
  JMP[EQ] @mth_comp_converged
  ; Swap active and next label buffers.
  LD r8,r11,3
  LD r9,r11,4
  ST r9,r11,3
  ST r8,r11,4
  LD r8,r11,6
  ADD r8,r8,r13
  ST r8,r11,6
  JMP @mth_comp_round

mth_comp_converged:
  ; Count fixed-point labels in the active buffer.
  MOVI r8,0
  ST r8,r11,7
  ST r8,r11,8
mth_comp_count:
  LD r8,r11,7
  MOVI r9,256
  CMP r8,r9
  JMP[GE] @mth_comp_count_done
  LD r10,r11,3
  ADD r10,r10,r8
  LD r10,r10,0
  CMP r10,r8
  JMP[NE] @mth_comp_count_next
  LD r9,r11,8
  ADD r9,r9,r13
  ST r9,r11,8
mth_comp_count_next:
  LD r8,r11,7
  ADD r8,r8,r13
  ST r8,r11,7
  JMP @mth_comp_count

mth_comp_count_done:
  ; Copy converged labels to public output if active buffer is tmp.
  LD r8,r11,3
  LD r9,r11,12
  CMP r8,r9
  JMP[EQ] @mth_comp_commit_count
  LD r10,r11,3
  MOVI r12,256
mth_comp_copy_final:
  LD r1,r10,0
  ST r1,r9,0
  ADD r10,r10,r13
  ADD r9,r9,r13
  SUB r12,r12,r13
  CMP r12,r0
  JMP[GT] @mth_comp_copy_final
mth_comp_commit_count:
  LD r1,r11,5
  LD r2,r11,8
  ST r2,r1,0
  MOVI r1,1
  RET

mth_comp_bad_count:
  MOVI r1,0
  RET
mth_comp_bad_offsets:
  MOVI r1,2
  RET
mth_comp_bad_neighbors:
  MOVI r1,3
  RET
mth_comp_no_converge:
  MOVI r1,5
  RET
