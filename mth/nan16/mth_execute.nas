; Native NaN16 execution dispatcher.
;
; ABI:
;   r1 = candidate descriptor
;   r2 = authoritative rule descriptor
;   r3 = left typed leaf descriptor
;   r4 = right typed leaf descriptor
;   r5 = exact canonical 10-word MC0 contract pointer
;   r6 = available capability bits
;   r7 = output typed leaf descriptor
;   r8 = program ID returned by the canonical :: operator linker
;   r12 = caller scratch base (57 words)
;   r13 = constant 1 (set internally)
;
; Dispatch is allowlisted. Program 900 is the 256-element float32 dot ABI.
; Admission runs before the kernel; denial never reaches the numerical kernel.
; Unsupported program IDs are rejected before admission/output metadata writes.
; The wrapper returns 0 on success, passes through mth_admit denials,
; 64 for unsupported program IDs, and 80 for a kernel ABI failure.
;
; Scratch words 0..47 belong to mth_admit. This wrapper uses 48..56.
; r14 is used as the preserved scratch-base register and is clobbered.

mth_execute:
  MOVI r13,1
  MOVI r9,900
  CMP r8,r9
  JMP[NE] @mth_execute_unsupported
  ; Program 900 is bound only to canonical operator 77 (vector dot).
  LD r10,r1,1
  MOVI r9,77
  CMP r10,r9
  JMP[NE] @mth_execute_unsupported

  ADD r14,r12,r0
  ST r15,r14,56
  ST r1,r14,48
  ST r2,r14,49
  ST r3,r14,50
  ST r4,r14,51
  ST r5,r14,52
  ST r6,r14,53
  ST r7,r14,54
  ST r8,r14,55

  ; The exact registry-owned contract pointer and typed operands enter both gates.
  CALL @mth_admit
  ADD r12,r14,r0
  CMP r1,r0
  JMP[NE] @mth_execute_return

  ; Program 900: float32 dot256. Payload ranges and dimensions were admitted.
  LD r1,r12,50
  LD r1,r1,5
  LD r2,r12,51
  LD r2,r2,5
  LD r3,r12,54
  LD r3,r3,5
  CALL @mth_dot256_f32
  MOVI r9,1
  CMP r1,r9
  JMP[NE] @mth_execute_kernel_error
  MOVI r1,0
  JMP @mth_execute_return

mth_execute_unsupported:
  MOVI r1,64
  RET

mth_execute_kernel_error:
  MOVI r1,80

mth_execute_return:
  ADD r12,r14,r0
  LD r15,r12,56
  RET
