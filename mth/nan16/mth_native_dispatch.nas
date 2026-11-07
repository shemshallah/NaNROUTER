; Native allowlisted MTH program dispatch — NaN16 only.
;
; ABI:
;   r1 = immutable program ID from the canonical operator registry
;   r2 = left payload pointer
;   r3 = right payload pointer
;   r4 = output payload pointer
;   r5 = caller-owned 11-word scratch frame
;   r6 = dimension (must be exactly 256 for this initial allowlist)
;   r13 = 1
; Returns r1=0 success, 1 unknown program, 2 unsupported dimension,
;         3 kernel reported failure.
;
; Program IDs in this first dispatch table:
;   900 -> mth.vector.dot256.f32
;   901 -> mth.vector.cosine256.f32
;
; The caller must run mth_admit first. This routine is deliberately a
; dispatcher only: it does not authorize, allocate, resolve, or commit.
; Scratch layout: [0] return, [1..5] saved args, [6..9] cosine scratch,
; [10] saved r14. Caller owns the complete frame; no shared static state.

.include "mth_dot256_f32.nas"
.include "mth_cosine256_f32.nas"

mth_native_dispatch:
  CMP r5,r0
  JMP[EQ] @mth_dispatch_bad_frame
  CMP r13,r0
  JMP[EQ] @mth_dispatch_bad_frame
  ST r15,r5,0
  ST r1,r5,1
  ST r2,r5,2
  ST r3,r5,3
  ST r4,r5,4
  ST r6,r5,5
  ST r14,r5,10
  ADD r14,r5,r0

  MOVI r7,256
  CMP r6,r7
  JMP[NE] @mth_dispatch_bad_dimension

  MOVI r7,900
  CMP r1,r7
  JMP[EQ] @mth_dispatch_dot
  MOVI r7,901
  CMP r1,r7
  JMP[EQ] @mth_dispatch_cosine
  MOVI r1,1
  JMP @mth_dispatch_return

mth_dispatch_dot:
  LD r1,r14,2
  LD r2,r14,3
  LD r3,r14,4
  CALL @mth_dot256_f32
  JMP @mth_dispatch_kernel_status

mth_dispatch_cosine:
  LD r1,r14,2
  LD r2,r14,3
  LD r3,r14,4
  MOVI r4,6
  ADD r4,r14,r4
  CALL @mth_cosine256_f32

mth_dispatch_kernel_status:
  MOVI r7,1
  CMP r1,r7
  JMP[NE] @mth_dispatch_kernel_failed
  MOVI r1,0
  JMP @mth_dispatch_return

mth_dispatch_bad_dimension:
  MOVI r1,2
  JMP @mth_dispatch_return

mth_dispatch_kernel_failed:
  MOVI r1,3
  JMP @mth_dispatch_return

mth_dispatch_bad_frame:
  MOVI r1,4
  RET

mth_dispatch_return:
  LD r15,r14,0
  LD r7,r14,10
  ADD r14,r7,r0
  RET
