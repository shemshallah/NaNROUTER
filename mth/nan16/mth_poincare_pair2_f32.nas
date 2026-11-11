; Poincare disk (curvature -1) native 2D pair affinity.
; Inputs r1=point x[2], r2=point y[2] float32; both ||x||,||y||<1.
; r3=out[2] disjoint from input. Output [cosh(d), 1/cosh(d)].
; cosh(d)=1 + 2||x-y||^2/((1-||x||^2)(1-||y||^2)).
; Monotone affinity, NOT the actual acosh geodesic distance.
; Directional mirror lanes are separate from symmetric distance.
; Reject nonfinite/boundary/overflow atomically: r1=0,r9=1.
; r13=1. Preserves r2,r3,r13,r15. Only NaN16 binary32 ops.
mth_poincare_pair2_f32:
  MOVI r0,0
  MOVI r10,0
  MOVHI r10,0x7F80
  MOVI r4,0
mth_pp2_gate:
  ADD r5,r1,r4
  LD r5,r5,0
  BOOL.8 r11,r5,r10
  CMP r11,r10
  JMP[EQ] @mth_pp2_bad
  ADD r5,r2,r4
  LD r5,r5,0
  BOOL.8 r11,r5,r10
  CMP r11,r10
  JMP[EQ] @mth_pp2_bad
  ADDI r4,r4,1
  MOVI r11,2
  CMP r4,r11
  JMP[LT] @mth_pp2_gate
  LD r5,r1,0
  LD r6,r1,1
  LD r7,r2,0
  LD r8,r2,1
  MOVI r9,0
  MOVHI r9,0x3F80        ; 1.0
  FMUL r11,r5,r5
  FMUL r12,r6,r6
  FADD r11,r11,r12       ; ||x||^2
  FCMP r11,r9
  JMP[GE] @mth_pp2_bad
  FMUL r12,r7,r7
  FMUL r14,r8,r8
  FADD r12,r12,r14       ; ||y||^2
  FCMP r12,r9
  JMP[GE] @mth_pp2_bad
  FSUB r11,r9,r11
  FSUB r12,r9,r12
  FMUL r12,r11,r12       ; positive denominator
  FCMP r12,r0
  JMP[LE] @mth_pp2_bad
  FSUB r4,r5,r7
  FMUL r4,r4,r4
  FSUB r14,r6,r8
  FMUL r14,r14,r14
  FADD r4,r4,r14         ; squared euclidean gap
  MOVI r14,0
  MOVHI r14,0x4000       ; 2.0
  FMUL r4,r4,r14
  FDIV r4,r4,r12
  FADD r4,r4,r9          ; cosh distance
  FDIV r12,r9,r4         ; reciprocal affinity
  BOOL.8 r11,r4,r10
  CMP r11,r10
  JMP[EQ] @mth_pp2_bad
  BOOL.8 r11,r12,r10
  CMP r11,r10
  JMP[EQ] @mth_pp2_bad
  ST r4,r3,0
  ST r12,r3,1
  MOVI r9,0
  MOVI r1,1
  RET
mth_pp2_bad:
  MOVI r9,1
  MOVI r1,0
  RET
