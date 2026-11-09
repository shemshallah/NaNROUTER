; MTH native 256-point complex twiddle table — NaN16 only.
;
; Fills the DFT convention used by the native spectral kernels:
;
;   cos_out[k] = cos(2*pi*k/256)
;   sin_out[k] = sin(2*pi*k/256)
;
; for k=0..255, using mth_trig_sincos_f32 for every entry. No host sin/cos,
; no static table, and no recurrence drift: each angle is generated from the
; integer k, the binary32 step 2*pi/256, and the native range-reduced sincos.
;
; ABI (r13=1):
;   r1 = cos_out, 256 f32 word addresses (written)
;   r2 = sin_out, 256 f32 word addresses (written)
;   r3 = caller scratch, 4 words (cos pointer, sin pointer, index, return link)
;   r13 = 1
; Success: r1=1, r9=0. There is no expected rejection: every generated angle
; is in [0, 2*pi) and inside the sincos domain.
; The kernel preserves r6 across the sincos call and clobbers r1-r5, r7-r12,
; r14; r15 is saved in scratch and restored.
;
; The table is a numerical primitive, not an authorization or a claim that a
; particular DFT implementation is correct. Callers own the output extents.

mth_trig_twiddle256_f32:
  MOVI r0,0
  ADD r6,r3,r0               ; scratch pointer, preserved by sincos
  ADDI r7,r6,3
  ST r15,r7,0                ; return link
  ST r1,r6,0                 ; cos pointer
  ST r2,r6,1                 ; sin pointer
  MOVI r7,0
  ST r7,r6,2                 ; index

mth_trig_twiddle256_loop:
  LD r7,r6,2
  MOVI r8,256
  CMP r7,r8
  JMP[GE] @mth_trig_twiddle256_done

  CVTIF r1,r7                 ; k as float
  MOVI r8,0x0FDB
  MOVHI r8,0x3CC9             ; 2*pi/256 = 0x3CC90FDB
  FMUL r1,r1,r8
  CALL @mth_trig_sincos_f32

  LD r7,r6,2
  LD r8,r6,0
  ADD r8,r8,r7
  ST r3,r8,0                  ; cosine
  LD r8,r6,1
  ADD r8,r8,r7
  ST r2,r8,0                  ; sine

  ADDI r7,r7,1
  ST r7,r6,2
  JMP @mth_trig_twiddle256_loop

mth_trig_twiddle256_done:
  ADDI r7,r6,3
  LD r15,r7,0
  MOVI r1,1
  MOVI r9,0
  RET
