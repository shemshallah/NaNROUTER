; Native NaN16 reverse-mode gradient for rank-1 streamed 16^3 hypertensor.
; Forward T[i,j,k] = A[i]*B[j]*C[k].
; Given upstream gradient G[i,j,k]=dLoss/dT[i,j,k], compute:
;   dA[i] = sum_jk G[i,j,k]*B[j]*C[k]
;   dB[j] = sum_ik G[i,j,k]*A[i]*C[k]
;   dC[k] = sum_ij G[i,j,k]*A[i]*B[j]
; This provides differentiability to the vector-to-hypertensor representation.
; ABI r1=A16,r2=B16,r3=C16,r4=G4096,r5=dA16,r6=dB16,
;     r7=dC16,r8=scratch48 all word pointers (no overlap).
; r13=1. r1=1,r9=0 success; r1=0,r9=1 nonfinite source/arithmetic.
; Input read-only, accumulation scratch staged; all 48 output words
; published only after finite preflight. No host math and no static state.
; Return link r15 preserved, r13 preserved, r0 restored 0.
mth_hypertensor16_backward_f32:
  MOVI r0,0
  MOVI r14,0
  MOVHI r14,0x7F80
  MOVI r9,0
mth_htb_preflight_vectors:
  ADD r10,r1,r9
  LD r10,r10,0
  BOOL.8 r11,r10,r14
  CMP r11,r14
  JMP[EQ] @mth_htb_bad
  ADD r10,r2,r9
  LD r10,r10,0
  BOOL.8 r11,r10,r14
  CMP r11,r14
  JMP[EQ] @mth_htb_bad
  ADD r10,r3,r9
  LD r10,r10,0
  BOOL.8 r11,r10,r14
  CMP r11,r14
  JMP[EQ] @mth_htb_bad
  ADDI r9,r9,1
  MOVI r10,16
  CMP r9,r10
  JMP[LT] @mth_htb_preflight_vectors
  MOVI r9,0
mth_htb_preflight_grad:
  ADD r10,r4,r9
  LD r10,r10,0
  BOOL.8 r11,r10,r14
  CMP r11,r14
  JMP[EQ] @mth_htb_bad
  ADDI r9,r9,1
  MOVI r10,4096
  CMP r9,r10
  JMP[LT] @mth_htb_preflight_grad

  MOVI r9,0
mth_htb_zero:
  ADD r10,r8,r9
  ST r0,r10,0
  ADDI r9,r9,1
  MOVI r10,48
  CMP r9,r10
  JMP[LT] @mth_htb_zero

  MOVI r9,0             ; i
  MOVI r12,0            ; flattened tensor position
mth_htb_i:
  MOVI r10,0            ; j
mth_htb_j:
  MOVI r11,0            ; k
mth_htb_k:
  ; dA[i] += G[i,j,k]*B[j]*C[k]
  ADD r14,r4,r12
  LD r14,r14,0
  ADD r0,r2,r10
  LD r0,r0,0
  FMUL r14,r14,r0
  ADD r0,r3,r11
  LD r0,r0,0
  FMUL r14,r14,r0
  ADD r0,r8,r9
  LD r0,r0,0
  FADD r14,r14,r0
  ADD r0,r8,r9
  ST r14,r0,0

  ; dB[j] += G[i,j,k]*A[i]*C[k]
  ADD r14,r4,r12
  LD r14,r14,0
  ADD r0,r1,r9
  LD r0,r0,0
  FMUL r14,r14,r0
  ADD r0,r3,r11
  LD r0,r0,0
  FMUL r14,r14,r0
  ADDI r0,r8,16
  ADD r0,r0,r10
  LD r0,r0,0
  FADD r14,r14,r0
  ADDI r0,r8,16
  ADD r0,r0,r10
  ST r14,r0,0

  ; dC[k] += G[i,j,k]*A[i]*B[j]
  ADD r14,r4,r12
  LD r14,r14,0
  ADD r0,r1,r9
  LD r0,r0,0
  FMUL r14,r14,r0
  ADD r0,r2,r10
  LD r0,r0,0
  FMUL r14,r14,r0
  ADDI r0,r8,32
  ADD r0,r0,r11
  LD r0,r0,0
  FADD r14,r14,r0
  ADDI r0,r8,32
  ADD r0,r0,r11
  ST r14,r0,0

  ADDI r12,r12,1
  ADDI r11,r11,1
  MOVI r0,16
  CMP r11,r0
  JMP[LT] @mth_htb_k
  ADDI r10,r10,1
  MOVI r0,16
  CMP r10,r0
  JMP[LT] @mth_htb_j
  ADDI r9,r9,1
  MOVI r0,16
  CMP r9,r0
  JMP[LT] @mth_htb_i

  MOVI r14,0
  MOVHI r14,0x7F80
  MOVI r9,0
mth_htb_check:
  ADD r0,r8,r9
  LD r0,r0,0
  BOOL.8 r0,r0,r14
  CMP r0,r14
  JMP[EQ] @mth_htb_bad
  ADDI r9,r9,1
  MOVI r0,48
  CMP r9,r0
  JMP[LT] @mth_htb_check

  MOVI r9,0
mth_htb_publish:
  ADD r0,r8,r9
  LD r0,r0,0
  ADD r14,r5,r9
  ST r0,r14,0
  ADDI r0,r8,16
  ADD r0,r0,r9
  LD r0,r0,0
  ADD r14,r6,r9
  ST r0,r14,0
  ADDI r0,r8,32
  ADD r0,r0,r9
  LD r0,r0,0
  ADD r14,r7,r9
  ST r0,r14,0
  ADDI r9,r9,1
  MOVI r0,16
  CMP r9,r0
  JMP[LT] @mth_htb_publish
  MOVI r0,0
  MOVI r1,1
  MOVI r9,0
  RET
mth_htb_bad:
  MOVI r0,0
  MOVI r1,0
  MOVI r9,1
  RET
