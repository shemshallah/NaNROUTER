; MTH 256-element float32 natural exponential — NaN16 only.
;
; ABI:
;   r1 = input, 256 float32 payloads
;   r2 = output, 256 float32 payloads
;   r13 = 1
;   returns r1=1 on success
;           r1=0 when any input is NaN or +-inf; output is left untouched
;   clobbers r3-r12, r14
;
; Domain and policy:
;   * Only finite float32 inputs are accepted. A non-finite input rejects the
;     whole call atomically with r1=0 and an unchanged output array.
;   * For finite x > 88.72 (0x42B170A4) the result saturates to +inf.
;   * For finite x < -103.90 (magnitude 0x42CFCCCD) the result saturates to +0.
;   * Otherwise range reduction uses k = trunc(x*log2(e)) and
;         r = (x - k*ln2_hi) - k*ln2_lo,   |r| < ln2,
;     where ln2_hi is the 9-bit float constant 0x3F317200 and ln2_lo is the
;     float residual 0x35BFBE8E. k is obtained from integer exponent/mantissa
;     masks; k is converted back to an exact float by binary decomposition.
;   * exp(r) is a degree-10 Taylor polynomial evaluated by Horner, and 2^k is
;     assembled with integer exponent/subnormal-mantissa masks.
;   * Float arithmetic is limited to FMUL, FADD and FSUB. FCMP, host math,
;     table lookup, and conversion instructions are not used.
;
; Error policy (bounded, not a general expf claim):
;   The companion fixture compares this kernel with an independent in-guest
;   degree-18 Taylor reference over 256 deterministic finite inputs spanning
;   [-80, 79.375]. It requires |out-ref| <= 2e-5*|ref| using integer bit
;   comparisons of the absolute difference and tolerance. The fixture also
;   checks exp(0)=+1 exactly, exp(1) against the float constant e, reciprocal
;   identities, finite saturation endpoints, and atomic non-finite rejection.

mth_vector_exp256_f32:
  ADD r14,r15,r0
  ADD r11,r1,r0
  ADD r12,r2,r0

  ; Preflight: reject NaN and +-inf before touching output.
  MOVI r3,0
  MOVI r4,0xFFFF
  MOVHI r4,0x7FFF             ; 0x7FFFFFFF magnitude mask
  MOVI r5,0
  MOVHI r5,0x7F80             ; 0x7F800000
mth_exp256_vector_preflight:
  ADD r6,r11,r3
  LD r7,r6,0
  BOOL.8 r7,r7,r4             ; |x| bits
  CMP r7,r5
  JMP[GE] @mth_exp256_vector_reject
  ADD r3,r3,r13
  MOVI r6,256
  CMP r3,r6
  JMP[LT] @mth_exp256_vector_preflight

  MOVI r10,0
mth_exp256_vector_loop:
  ADD r6,r11,r10
  LD r1,r6,0
  CALL @mth_exp256_scalar
  ADD r6,r12,r10
  ST r1,r6,0
  ADD r10,r10,r13
  MOVI r6,256
  CMP r10,r6
  JMP[LT] @mth_exp256_vector_loop

  ADD r15,r14,r0
  MOVI r1,1
  RET

mth_exp256_vector_reject:
  ADD r15,r14,r0
  MOVI r1,0
  RET

; Scalar core: r1 = finite x bits -> r1 = exp(x) bits.
; Clobbers r2-r9. Preserves r10-r14.
mth_exp256_scalar:
  ADD r2,r1,r0
  MOVI r3,0xFFFF
  MOVHI r3,0x7FFF             ; 0x7FFFFFFF
  BOOL.8 r3,r2,r3             ; |x| bits
  SHR r4,r2,31                ; sign
  CMP r4,r0
  JMP[NE] @mth_exp256_scalar_negative
  MOVI r5,0x70A4
  MOVHI r5,0x42B1             ; +88.72
  CMP r3,r5
  JMP[GT] @mth_exp256_scalar_inf
  JMP @mth_exp256_scalar_reduce
mth_exp256_scalar_negative:
  MOVI r5,0xCCCD
  MOVHI r5,0x42CF             ; 103.90
  CMP r3,r5
  JMP[GT] @mth_exp256_scalar_zero

mth_exp256_scalar_reduce:
  MOVI r5,0xAA3B
  MOVHI r5,0x3FB8             ; log2(e)
  FMUL r5,r1,r5               ; y = x*log2(e)
  ADD r2,r5,r0
  SHR r4,r2,31                ; sign(y)
  MOVI r3,0xFFFF
  MOVHI r3,0x7FFF
  BOOL.8 r2,r2,r3             ; |y| bits
  SHR r3,r2,23                ; exponent
  MOVI r9,127
  CMP r3,r9
  JMP[LT] @mth_exp256_scalar_k_zero
  SUB r3,r3,r9                ; e-127
  MOVI r9,0xFFFF
  MOVHI r9,0x007F
  BOOL.8 r2,r2,r9             ; mantissa
  MOVI r9,0
  MOVHI r9,0x0080
  BOOL.14 r2,r2,r9            ; implicit integer bit
  MOVI r9,23
  SUB r9,r9,r3                ; right-shift count
mth_exp256_scalar_shr_loop:
  CMP r9,r0
  JMP[EQ] @mth_exp256_scalar_shr_done
  SHR r2,r2,1
  SUB r9,r9,r13
  JMP @mth_exp256_scalar_shr_loop
mth_exp256_scalar_shr_done:
  CMP r4,r0
  JMP[EQ] @mth_exp256_scalar_k_ready
  SUB r2,r0,r2                ; k = -trunc(|y|)
  JMP @mth_exp256_scalar_k_ready
mth_exp256_scalar_k_zero:
  MOVI r2,0
mth_exp256_scalar_k_ready:
  ADD r6,r2,r0                ; k integer

  ; Exact float(k) by binary decomposition of |k|.
  ADD r3,r6,r0
  SHR r4,r3,31
  CMP r4,r0
  JMP[EQ] @mth_exp256_scalar_kabs_ready
  SUB r3,r0,r3
mth_exp256_scalar_kabs_ready:
  MOVI r7,0
  MOVI r9,128
  CMP r3,r9
  JMP[LT] @mth_exp256_scalar_k64
  SUB r3,r3,r9
  MOVI r7,0
  MOVHI r7,0x4300             ; 128.0
mth_exp256_scalar_k64:
  MOVI r9,64
  CMP r3,r9
  JMP[LT] @mth_exp256_scalar_k32
  SUB r3,r3,r9
  MOVI r5,0
  MOVHI r5,0x4280             ; 64.0
  FADD r7,r7,r5
mth_exp256_scalar_k32:
  MOVI r9,32
  CMP r3,r9
  JMP[LT] @mth_exp256_scalar_k16
  SUB r3,r3,r9
  MOVI r5,0
  MOVHI r5,0x4200             ; 32.0
  FADD r7,r7,r5
mth_exp256_scalar_k16:
  MOVI r9,16
  CMP r3,r9
  JMP[LT] @mth_exp256_scalar_k8
  SUB r3,r3,r9
  MOVI r5,0
  MOVHI r5,0x4180             ; 16.0
  FADD r7,r7,r5
mth_exp256_scalar_k8:
  MOVI r9,8
  CMP r3,r9
  JMP[LT] @mth_exp256_scalar_k4
  SUB r3,r3,r9
  MOVI r5,0
  MOVHI r5,0x4100             ; 8.0
  FADD r7,r7,r5
mth_exp256_scalar_k4:
  MOVI r9,4
  CMP r3,r9
  JMP[LT] @mth_exp256_scalar_k2
  SUB r3,r3,r9
  MOVI r5,0
  MOVHI r5,0x4080             ; 4.0
  FADD r7,r7,r5
mth_exp256_scalar_k2:
  MOVI r9,2
  CMP r3,r9
  JMP[LT] @mth_exp256_scalar_k1
  SUB r3,r3,r9
  MOVI r5,0
  MOVHI r5,0x4000             ; 2.0
  FADD r7,r7,r5
mth_exp256_scalar_k1:
  MOVI r9,1
  CMP r3,r9
  JMP[LT] @mth_exp256_scalar_kf_sign
  MOVI r5,0
  MOVHI r5,0x3F80             ; 1.0
  FADD r7,r7,r5
mth_exp256_scalar_kf_sign:
  CMP r4,r0
  JMP[EQ] @mth_exp256_scalar_kf_ready
  FSUB r7,r0,r7               ; -0.0 - kf
mth_exp256_scalar_kf_ready:
  ; r = (x - kf*ln2_hi) - kf*ln2_lo
  MOVI r8,0x7200
  MOVHI r8,0x3F31             ; ln2_hi
  FMUL r8,r7,r8
  FSUB r8,r1,r8
  MOVI r9,0xBE8E
  MOVHI r9,0x35BF             ; ln2_lo
  FMUL r9,r7,r9
  FSUB r8,r8,r9               ; r

  ; exp(r) = sum_{n=0..10} r^n/n!, Horner from 1/10!.
  MOVI r9,0xF27E
  MOVHI r9,0x3493             ; 1/10!
  MOVI r5,0xEF1D
  MOVHI r5,0x3638             ; 1/9!
  FMUL r9,r9,r8
  FADD r9,r9,r5
  MOVI r5,0x0D01
  MOVHI r5,0x37D0             ; 1/8!
  FMUL r9,r9,r8
  FADD r9,r9,r5
  MOVI r5,0x0D01
  MOVHI r5,0x3950             ; 1/7!
  FMUL r9,r9,r8
  FADD r9,r9,r5
  MOVI r5,0x0B61
  MOVHI r5,0x3AB6             ; 1/6!
  FMUL r9,r9,r8
  FADD r9,r9,r5
  MOVI r5,0x8889
  MOVHI r5,0x3C08             ; 1/5!
  FMUL r9,r9,r8
  FADD r9,r9,r5
  MOVI r5,0xAAAB
  MOVHI r5,0x3D2A             ; 1/4!
  FMUL r9,r9,r8
  FADD r9,r9,r5
  MOVI r5,0xAAAB
  MOVHI r5,0x3E2A             ; 1/3!
  FMUL r9,r9,r8
  FADD r9,r9,r5
  MOVI r5,0
  MOVHI r5,0x3F00             ; 1/2!
  FMUL r9,r9,r8
  FADD r9,r9,r5
  MOVI r5,0
  MOVHI r5,0x3F80             ; 1
  FMUL r9,r9,r8
  FADD r9,r9,r5
  MOVI r5,0
  MOVHI r5,0x3F80             ; 1
  FMUL r9,r9,r8
  FADD r9,r9,r5               ; exp(r)

  ; Assemble 2^k from the signed integer k.
  MOVI r4,0                   ; extra doubling flag
  ADD r2,r6,r0
  SHR r3,r2,31
  CMP r3,r0
  JMP[NE] @mth_exp256_scalar_scale_neg
  MOVI r5,128
  CMP r6,r5
  JMP[GT] @mth_exp256_scalar_inf
  JMP[EQ] @mth_exp256_scalar_scale_128
  MOVI r2,127
  ADD r2,r2,r6
  SHL r2,r2,23
  JMP @mth_exp256_scalar_scale_ready
mth_exp256_scalar_scale_128:
  MOVI r2,254
  SHL r2,r2,23                ; 2^127, followed by one doubling
  MOVI r4,1
  JMP @mth_exp256_scalar_scale_ready
mth_exp256_scalar_scale_neg:
  SUB r3,r0,r2                ; |k|
  MOVI r5,149
  CMP r3,r5
  JMP[GT] @mth_exp256_scalar_zero
  MOVI r5,126
  CMP r3,r5
  JMP[GT] @mth_exp256_scalar_scale_sub
  MOVI r2,127
  SUB r2,r2,r3
  SHL r2,r2,23
  JMP @mth_exp256_scalar_scale_ready
mth_exp256_scalar_scale_sub:
  MOVI r2,149
  SUB r2,r2,r3                ; 0..22
  MOVI r5,1
mth_exp256_scalar_scale_sub_loop:
  CMP r2,r0
  JMP[EQ] @mth_exp256_scalar_scale_sub_done
  SHL r5,r5,1
  SUB r2,r2,r13
  JMP @mth_exp256_scalar_scale_sub_loop
mth_exp256_scalar_scale_sub_done:
  ADD r2,r5,r0
mth_exp256_scalar_scale_ready:
  FMUL r9,r9,r2
  CMP r4,r0
  JMP[EQ] @mth_exp256_scalar_done
  FADD r9,r9,r9
mth_exp256_scalar_done:
  ADD r1,r9,r0
  RET

mth_exp256_scalar_inf:
  MOVI r1,0
  MOVHI r1,0x7F80
  RET
mth_exp256_scalar_zero:
  ADD r1,r0,r0
  RET
