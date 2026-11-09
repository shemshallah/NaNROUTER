; MTH native float32 plane rotation / phasor application — NaN16 only.
;
; Rotates a two-component vector by an angle:
;
;   x' = x*cos(a) - y*sin(a)
;   y' = x*sin(a) + y*cos(a)
;
; using the native mth_trig_sincos_f32 primitive. This is the phase-coded
; memory seam: it can apply a positional phase, a spectral twiddle, or an
; oscillator step without host trigonometry. It is exactly a complex multiply
; by exp(i*a), so it preserves the Euclidean norm apart from float32 roundoff.
;
; ABI (r13=1):
;   r1 = x, one float32 payload at a word address (read-only)
;   r2 = y, one float32 payload at a word address (read-only)
;   r3 = angle, one raw float32 payload
;   r4 = out_x, one float32 word address (written on success only)
;   r5 = out_y, one float32 word address (written on success only)
;   r6 = caller scratch, five float32/u32 words
;   r13 = 1
;
; Success: r1=1, r9=0, out_x/out_y written.
; Rejection: r1=0, r9 is the sincos cause (1 non-finite angle, 2 domain),
; and neither output word is written.
;
; Order:
;   x' = (x*cos) - (y*sin)
;   y' = (x*sin) + (y*cos)
; No FMA, no reassociation, no host math. Outputs may alias inputs because the
; kernel loads both inputs before either output store. Partial overlap between
; the two outputs or with scratch is not supported.
;
; Register effects: r0=0; r1-r14 clobbered; r15 preserved. The scratch words
; are overwritten; no static storage and no allocation are used.

mth_trig_rotate_f32:
  MOVI r0,0

  ; Preserve the return link and the five pointers in caller scratch before
  ; sincos reuses the argument registers.
  ADDI r7,r6,4
  ST r15,r7,0
  ST r4,r6,0
  ST r5,r6,1
  ST r1,r6,2
  ST r2,r6,3

  ADD r1,r3,r0
  CALL @mth_trig_sincos_f32
  CMP r1,r13
  JMP[NE] @mth_trig_rotate_reject

  ; r2 = sin(a), r3 = cos(a)
  LD r4,r6,0                  ; out_x
  LD r5,r6,1                  ; out_y
  LD r7,r6,2                  ; x pointer
  LD r8,r6,3                  ; y pointer
  LD r9,r7,0                  ; x
  LD r10,r8,0                 ; y

  ; x' = x*cos - y*sin
  FMUL r11,r9,r3
  FMUL r12,r10,r2
  FSUB r11,r11,r12
  ST r11,r4,0

  ; y' = x*sin + y*cos
  FMUL r9,r9,r2
  FMUL r10,r10,r3
  FADD r9,r9,r10
  ST r9,r5,0

  ADDI r7,r6,4
  LD r15,r7,0
  MOVI r1,1
  MOVI r9,0
  RET

mth_trig_rotate_reject:
  ADDI r7,r6,4
  LD r15,r7,0
  MOVI r1,0
  RET
