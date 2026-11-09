; MTH 256-element float32 natural logarithm — NaN16 only.
;
; ABI:
;   r1 = input, 256 float32 payloads
;   r2 = output, 256 float32 payloads
;   r13 = 1
;   returns r1=1 on success
;           r1=0 when any input is <= 0 or non-finite; output is left untouched
;   clobbers r3-r12, r14
;
; Domain and policy:
;   * Accepted inputs are strictly positive finite float32 values, including
;     positive subnormals. +0, -0, every negative value, +inf, -inf and NaN
;     reject the whole call atomically with r1=0.
;   * x is split by integer exponent/mantissa masks into x = m*2^k with
;     m in [1,2). If m > sqrt(2) (0x3FB504F3) the reduction uses m/2 and
;     k+1, so the working m lies in [sqrt(1/2), sqrt(2)) and log(1) needs no
;     cancelling k*ln2 addition. Positive subnormals are normalized by shifting
;     the mantissa until its implicit bit is set.
;   * ln(m) uses z=(m-1)/(m+1) and
;         ln(m) = 2*z*(1 + z^2/3 + z^4/5 + ... + z^14/15),
;     evaluated by Horner. k is converted to an exact float by binary
;     decomposition and the result is k*ln2_hi + (ln(m) + k*ln2_lo), with
;     ln2_hi = 0x3F317200 and ln2_lo = 0x35BFBE8E.
;   * Float arithmetic is limited to FMUL, FADD, FSUB and FDIV. FCMP, host
;     math, table lookup, and conversion instructions are not used.
;
; Error policy (bounded, not a general logf claim):
;   The companion fixture compares this kernel with an independent in-guest
;   degree-24 ln(1+f) series reference over 256 deterministic positive inputs
;   spanning normal and subnormal values. It requires
;   |out-ref| <= 1e-7 + 2e-5*|ref| using integer bit comparisons of the
;   absolute difference and tolerance. The fixture also checks log(1)=+0
;   exactly, log(e) relative to +1, an exponent-symmetry identity, and atomic
;   rejection for 0, -0, negatives, infinities and NaN.

mth_vector_log256_f32:
  ADD r14,r15,r0
  ADD r11,r1,r0
  ADD r12,r2,r0

  ; Preflight: positive finite and nonzero only.
  MOVI r3,0
  MOVI r4,0
  MOVHI r4,0x7F80             ; 0x7F800000
mth_log256_vector_preflight:
  ADD r6,r11,r3
  LD r7,r6,0
  SHR r8,r7,31
  CMP r8,r0
  JMP[NE] @mth_log256_vector_reject
  CMP r7,r0
  JMP[EQ] @mth_log256_vector_reject
  CMP r7,r4
  JMP[GE] @mth_log256_vector_reject
  ADD r3,r3,r13
  MOVI r6,256
  CMP r3,r6
  JMP[LT] @mth_log256_vector_preflight

  MOVI r10,0
mth_log256_vector_loop:
  ADD r6,r11,r10
  LD r1,r6,0
  CALL @mth_log256_scalar
  ADD r6,r12,r10
  ST r1,r6,0
  ADD r10,r10,r13
  MOVI r6,256
  CMP r10,r6
  JMP[LT] @mth_log256_vector_loop

  ADD r15,r14,r0
  MOVI r1,1
  RET

mth_log256_vector_reject:
  ADD r15,r14,r0
  MOVI r1,0
  RET

; Scalar core: r1 = positive finite nonzero x bits -> r1 = ln(x) bits.
; Clobbers r2-r9. Preserves r10-r14.
mth_log256_scalar:
  ADD r2,r1,r0
  SHR r3,r2,23                ; exponent field
  CMP r3,r0
  JMP[EQ] @mth_log256_scalar_subnormal

  MOVI r4,0xFFFF
  MOVHI r4,0x007F
  BOOL.8 r5,r2,r4             ; mantissa
  MOVI r4,127
  SUB r6,r3,r4                ; k = e-127
  JMP @mth_log256_scalar_mantissa

mth_log256_scalar_subnormal:
  MOVI r4,0xFFFF
  MOVHI r4,0x007F
  BOOL.8 r5,r2,r4             ; mantissa bits
  MOVI r3,0                   ; shift count
  MOVI r4,0
  MOVHI r4,0x0080             ; implicit bit
mth_log256_scalar_sub_loop:
  BOOL.8 r7,r5,r4
  CMP r7,r0
  JMP[NE] @mth_log256_scalar_sub_ready
  SHL r5,r5,1
  ADD r3,r3,r13
  JMP @mth_log256_scalar_sub_loop
mth_log256_scalar_sub_ready:
  MOVI r4,0xFFFF
  MOVHI r4,0x007F
  BOOL.8 r5,r5,r4
  MOVI r6,126
  ADD r6,r6,r3
  SUB r6,r0,r6                ; k = -(126+shift)

mth_log256_scalar_mantissa:
  MOVI r4,0
  MOVHI r4,0x3F80
  BOOL.14 r5,r5,r4            ; m bits in [1,2)
  MOVI r4,0x04F3
  MOVHI r4,0x3FB5             ; sqrt(2)
  CMP r5,r4
  JMP[LE] @mth_log256_scalar_m_ready
  MOVI r4,0
  MOVHI r4,0x0080
  SUB r5,r5,r4                ; m = m/2
  ADD r6,r6,r13               ; k = k+1
mth_log256_scalar_m_ready:
  MOVI r4,0
  MOVHI r4,0x3F80             ; 1.0
  FSUB r8,r5,r4               ; m-1
  FADD r9,r5,r4               ; m+1
  FDIV r8,r8,r9               ; z
  FMUL r9,r8,r8               ; z^2

  ; 2*z*(1 + z^2/3 + ... + z^14/15), Horner from 1/15.
  MOVI r7,0x8889
  MOVHI r7,0x3D88             ; 1/15
  MOVI r4,0x89D9
  MOVHI r4,0x3D9D             ; 1/13
  FMUL r7,r7,r9
  FADD r7,r7,r4
  MOVI r4,0x2E8C
  MOVHI r4,0x3DBA             ; 1/11
  FMUL r7,r7,r9
  FADD r7,r7,r4
  MOVI r4,0x8E39
  MOVHI r4,0x3DE3             ; 1/9
  FMUL r7,r7,r9
  FADD r7,r7,r4
  MOVI r4,0x4925
  MOVHI r4,0x3E12             ; 1/7
  FMUL r7,r7,r9
  FADD r7,r7,r4
  MOVI r4,0xCCCD
  MOVHI r4,0x3E4C             ; 1/5
  FMUL r7,r7,r9
  FADD r7,r7,r4
  MOVI r4,0xAAAB
  MOVHI r4,0x3EAA             ; 1/3
  FMUL r7,r7,r9
  FADD r7,r7,r4
  MOVI r4,0
  MOVHI r4,0x3F80             ; 1
  FMUL r7,r7,r9
  FADD r7,r7,r4
  MOVI r4,0
  MOVHI r4,0x4000             ; 2.0
  FMUL r8,r8,r4               ; 2z
  FMUL r8,r8,r7               ; ln(m)

  ; Exact float(k) by binary decomposition of |k|.
  ADD r2,r6,r0
  SHR r3,r2,31
  CMP r3,r0
  JMP[EQ] @mth_log256_scalar_kabs_ready
  SUB r2,r0,r2
mth_log256_scalar_kabs_ready:
  MOVI r7,0
  MOVI r9,128
  CMP r2,r9
  JMP[LT] @mth_log256_scalar_k64
  SUB r2,r2,r9
  MOVI r7,0
  MOVHI r7,0x4300             ; 128.0
mth_log256_scalar_k64:
  MOVI r9,64
  CMP r2,r9
  JMP[LT] @mth_log256_scalar_k32
  SUB r2,r2,r9
  MOVI r4,0
  MOVHI r4,0x4280             ; 64.0
  FADD r7,r7,r4
mth_log256_scalar_k32:
  MOVI r9,32
  CMP r2,r9
  JMP[LT] @mth_log256_scalar_k16
  SUB r2,r2,r9
  MOVI r4,0
  MOVHI r4,0x4200             ; 32.0
  FADD r7,r7,r4
mth_log256_scalar_k16:
  MOVI r9,16
  CMP r2,r9
  JMP[LT] @mth_log256_scalar_k8
  SUB r2,r2,r9
  MOVI r4,0
  MOVHI r4,0x4180             ; 16.0
  FADD r7,r7,r4
mth_log256_scalar_k8:
  MOVI r9,8
  CMP r2,r9
  JMP[LT] @mth_log256_scalar_k4
  SUB r2,r2,r9
  MOVI r4,0
  MOVHI r4,0x4100             ; 8.0
  FADD r7,r7,r4
mth_log256_scalar_k4:
  MOVI r9,4
  CMP r2,r9
  JMP[LT] @mth_log256_scalar_k2
  SUB r2,r2,r9
  MOVI r4,0
  MOVHI r4,0x4080             ; 4.0
  FADD r7,r7,r4
mth_log256_scalar_k2:
  MOVI r9,2
  CMP r2,r9
  JMP[LT] @mth_log256_scalar_k1
  SUB r2,r2,r9
  MOVI r4,0
  MOVHI r4,0x4000             ; 2.0
  FADD r7,r7,r4
mth_log256_scalar_k1:
  MOVI r9,1
  CMP r2,r9
  JMP[LT] @mth_log256_scalar_kf_sign
  MOVI r4,0
  MOVHI r4,0x3F80             ; 1.0
  FADD r7,r7,r4
mth_log256_scalar_kf_sign:
  CMP r3,r0
  JMP[EQ] @mth_log256_scalar_kf_ready
  FSUB r7,r0,r7
mth_log256_scalar_kf_ready:
  MOVI r9,0x7200
  MOVHI r9,0x3F31             ; ln2_hi
  FMUL r9,r7,r9
  MOVI r4,0xBE8E
  MOVHI r4,0x35BF             ; ln2_lo
  FMUL r4,r7,r4
  FADD r4,r8,r4
  FADD r1,r9,r4
  RET
