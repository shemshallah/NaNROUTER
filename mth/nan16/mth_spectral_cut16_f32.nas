; NaN16 binary spectral clustering readout from caller-provided Fiedler mode.
; Requires a sorted eigenbasis U of the exact weighted graph Laplacian;
; this routine does not solve the eigenproblem. A disconnected graph requires
; a multiplicity-aware policy upstream, not blindly selecting column 1.
; ABI r1=U[16][16] row major f32, r2=mode_index in [1,15],
; r3=labels[16] output u32, r4=scratch[16], r5=threshold f32 bits;
; source and output arrays disjoint, r13=1.
; labels[i]=(U[i,mode] > threshold ? 1:0); requires both partitions present.
; return r1=1, r2=count_positive, r9=0 or r1=0, r9=1 invalid index,
; 2 nonfinite coordinate/threshold, 3 degenerate partition.
; All label writes staged, atomic output. Does not rewrite the graph.
mth_spectral_cut16_f32:
  MOVI r0,0
  CMP r2,r0
  JMP[LE] @mth_sc16_bad_index
  MOVI r6,16
  CMP r2,r6
  JMP[GE] @mth_sc16_bad_index
  MOVI r14,0
  MOVHI r14,0x7F80
  BOOL.8 r6,r5,r14
  CMP r6,r14
  JMP[EQ] @mth_sc16_bad_value
  MOVI r6,0              ; row i
  MOVI r7,0              ; positives
mth_sc16_label:
  SHL r8,r6,4
  ADD r8,r8,r2
  ADD r9,r1,r8
  LD r9,r9,0
  BOOL.8 r10,r9,r14
  CMP r10,r14
  JMP[EQ] @mth_sc16_bad_value
  FCMP r9,r5
  MOVI r10,0
  JMP[LE] @mth_sc16_store_label
  MOVI r10,1
  ADDI r7,r7,1
mth_sc16_store_label:
  ADD r8,r4,r6
  ST r10,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_sc16_label
  CMP r7,r0
  JMP[EQ] @mth_sc16_degenerate
  MOVI r8,16
  CMP r7,r8
  JMP[EQ] @mth_sc16_degenerate
  MOVI r6,0
mth_sc16_publish:
  ADD r8,r4,r6
  LD r9,r8,0
  ADD r8,r3,r6
  ST r9,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_sc16_publish
  ADD r2,r7,r0
  MOVI r1,1
  MOVI r9,0
  RET
mth_sc16_bad_index:
  MOVI r9,1
  JMP @mth_sc16_reject
mth_sc16_bad_value:
  MOVI r9,2
  JMP @mth_sc16_reject
mth_sc16_degenerate:
  MOVI r9,3
mth_sc16_reject:
  MOVI r1,0
  RET
