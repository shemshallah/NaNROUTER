; Third-order streamed rank-1 hypertensor OUT[i,j,k]=A[i]*B[j]*C[k].
; Native NaN16 binary32, true 16x16x16 tensor (not 16x16 matrix).
; ABI r1=A[16] r2=B[16] r3=C[16] r4=OUT[4096] r5=SCRATCH[4096] word addresses.
; Inputs, scratch and out MUST be disjoint, in-bounds, non-overlapping.
; r13=1. r1=1,r9=0 success; r1=0,r9=1 bad source or 2 arithmetic overflow.
; Atomic output: entire scratch validated before a single OUT store.
; All arithmetic is NaN16 FMUL, no host fallback, no global static state.
; Clobbers r0,r6-r12,r14, preserves r2-r5,r13,r15.
mth_hypertensor16_f32:
  MOVI r0,0
  MOVI r14,0
  MOVHI r14,0x7F80
  MOVI r6,0
mth_htensor_preflight:
  ADD r7,r1,r6
  LD r7,r7,0
  BOOL.8 r8,r7,r14
  CMP r8,r14
  JMP[EQ] @mth_htensor_bad_input
  ADD r7,r2,r6
  LD r7,r7,0
  BOOL.8 r8,r7,r14
  CMP r8,r14
  JMP[EQ] @mth_htensor_bad_input
  ADD r7,r3,r6
  LD r7,r7,0
  BOOL.8 r8,r7,r14
  CMP r8,r14
  JMP[EQ] @mth_htensor_bad_input
  ADDI r6,r6,1
  MOVI r7,16
  CMP r6,r7
  JMP[LT] @mth_htensor_preflight
  MOVI r6,0
  MOVI r9,0
mth_htensor_i:
  MOVI r7,0
mth_htensor_j:
  MOVI r8,0
mth_htensor_k:
  ADD r10,r1,r6
  LD r10,r10,0
  ADD r11,r2,r7
  LD r11,r11,0
  FMUL r10,r10,r11
  ADD r12,r3,r8
  LD r12,r12,0
  FMUL r10,r10,r12
  BOOL.8 r11,r10,r14
  CMP r11,r14
  JMP[EQ] @mth_htensor_bad_arithmetic
  ADD r12,r5,r9
  ST r10,r12,0
  ADDI r9,r9,1
  ADDI r8,r8,1
  MOVI r11,16
  CMP r8,r11
  JMP[LT] @mth_htensor_k
  ADDI r7,r7,1
  MOVI r11,16
  CMP r7,r11
  JMP[LT] @mth_htensor_j
  ADDI r6,r6,1
  MOVI r11,16
  CMP r6,r11
  JMP[LT] @mth_htensor_i

  MOVI r6,0
mth_htensor_publish:
  ADD r7,r5,r6
  LD r8,r7,0
  ADD r7,r4,r6
  ST r8,r7,0
  ADDI r6,r6,1
  MOVI r7,4096
  CMP r6,r7
  JMP[LT] @mth_htensor_publish
  MOVI r9,0
  MOVI r1,1
  RET
mth_htensor_bad_input:
  MOVI r9,1
  MOVI r1,0
  RET
mth_htensor_bad_arithmetic:
  MOVI r9,2
  MOVI r1,0
  RET
