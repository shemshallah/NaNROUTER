; Three known/unknown undirected pair-states -> hot/cold simplicial flags.
; States: 0=observed cold, 1=observed hot, 2=unobserved/unknown.
; Input r1=word pointer to [ab,bc,ca]. r13=1. All other values reject.
; On success r1=1, r2=hot count, r3=cold count, r4=flags, r5=unknown count.
; flags bit0=111, bit1=at least 2 hot, bit2=000, bit3=at least 2 cold.
; NO unknown is ever recoded as cold. Edges are *relationships*, not
; head identities; candidates must come from versioned native mapping.
; Reject r1=0,r9=1. Does not mutate physical root.
mth_simplicial_motif3:
  MOVI r0,0
  MOVI r2,0
  MOVI r3,0
  MOVI r4,0
  MOVI r5,0
  MOVI r6,0
mth_sm3_loop:
  ADD r7,r1,r6
  LD r7,r7,0
  CMP r7,r0
  JMP[EQ] @mth_sm3_cold
  MOVI r8,1
  CMP r7,r8
  JMP[EQ] @mth_sm3_hot
  MOVI r8,2
  CMP r7,r8
  JMP[NE] @mth_sm3_bad
  ADDI r5,r5,1
  JMP @mth_sm3_next
mth_sm3_cold:
  ADDI r3,r3,1
  JMP @mth_sm3_next
mth_sm3_hot:
  ADDI r2,r2,1
mth_sm3_next:
  ADDI r6,r6,1
  MOVI r8,3
  CMP r6,r8
  JMP[LT] @mth_sm3_loop
  MOVI r8,2
  CMP r2,r8
  JMP[LT] @mth_sm3_not_hot2
  MOVI r4,2
mth_sm3_not_hot2:
  MOVI r8,3
  CMP r2,r8
  JMP[NE] @mth_sm3_not_hot3
  ADDI r4,r4,1
mth_sm3_not_hot3:
  MOVI r8,2
  CMP r3,r8
  JMP[LT] @mth_sm3_not_cold2
  ADDI r4,r4,8
mth_sm3_not_cold2:
  MOVI r8,3
  CMP r3,r8
  JMP[NE] @mth_sm3_done
  ADDI r4,r4,4
mth_sm3_done:
  MOVI r9,0
  MOVI r1,1
  RET
mth_sm3_bad:
  MOVI r9,1
  MOVI r1,0
  RET
