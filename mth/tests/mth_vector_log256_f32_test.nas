; MTH vector log256 float32 fixture — NaN16 only.
;
; Inputs are generated in the guest; expected values come from an independent
; in-guest degree-24 ln(1+f) series with the same exponent split but a different
; polynomial form than the kernel's atanh series. No host-computed expected
; array is used. Comparisons operate on nonnegative float bit patterns as
; unsigned integers: |out-ref| <= 1e-7 + 2e-5*|ref|.
;
; Covered input classes: positive normals across 32 exponents, positive
; subnormals, max finite, values near 1, and the anchors 1, 1/2, 2, sqrt(2),
; e and 1/e. Rejection is checked atomically for +0, -0, negative, +inf and NaN.

.org 0
JMP @mth_log256_test_main
.include "../nan16/mth_vector_log256_f32.nas"

mth_log256_test_main:
  MOVI r13,1

  ; ---- deterministic positive inputs: exponent 110+(i&31), pseudo mantissa ----
  LA r11,@mth_log256_test_in
  MOVI r3,0
mth_log256_test_fill:
  ADD r4,r3,r0
  MOVI r5,31
  BOOL.8 r4,r4,r5
  MOVI r5,110
  ADD r4,r4,r5
  SHL r4,r4,23
  MOVI r5,0x79B1
  MOVHI r5,0x9E37
  MUL r5,r3,r5
  MOVI r6,0xFFFF
  MOVHI r6,0x007F
  BOOL.8 r5,r5,r6
  BOOL.14 r4,r4,r5
  ADD r6,r11,r3
  ST r4,r6,0
  ADD r3,r3,r13
  MOVI r6,256
  CMP r3,r6
  JMP[LT] @mth_log256_test_fill

  ; ---- anchor / edge overrides ----
  MOVI r5,0
  MOVHI r5,0x3F80             ; 1.0
  ST r5,r11,0
  MOVI r5,0
  MOVHI r5,0x3F00             ; 0.5
  ST r5,r11,1
  MOVI r5,0
  MOVHI r5,0x4000             ; 2.0
  ST r5,r11,2
  MOVI r5,0x04F3
  MOVHI r5,0x3FB5             ; sqrt(2)
  ST r5,r11,3
  MOVI r5,1
  MOVHI r5,0x3F80             ; 1+ulp
  ST r5,r11,4
  MOVI r5,0xFFFF
  MOVHI r5,0x3F7F             ; 1-ulp
  ST r5,r11,5
  MOVI r5,0
  MOVHI r5,0x0080             ; min normal
  ST r5,r11,6
  MOVI r5,1
  ST r5,r11,7                 ; min subnormal
  MOVI r5,0xFFFF
  MOVHI r5,0x007F             ; max subnormal
  ST r5,r11,8
  MOVI r5,0xFFFF
  MOVHI r5,0x7F7F             ; max finite
  ST r5,r11,9
  MOVI r5,0x4260
  MOVHI r5,0x0DA2             ; 1e-30
  ST r5,r11,10
  MOVI r5,0xF2CA
  MOVHI r5,0x7149             ; 1e+30
  ST r5,r11,11
  MOVI r5,0xF854
  MOVHI r5,0x402D             ; e
  ST r5,r11,12
  MOVI r5,0x5AB2
  MOVHI r5,0x3EBC             ; 1/e
  ST r5,r11,13
  MOVI r5,0x0347
  MOVHI r5,0x3F80             ; 1.0001
  ST r5,r11,14
  MOVI r5,0xF972
  MOVHI r5,0x3F7F             ; 0.9999
  ST r5,r11,15

  ; ---- in-guest reference ----
  LA r12,@mth_log256_test_ref
  MOVI r10,0
mth_log256_test_ref_loop:
  ADD r6,r11,r10
  LD r1,r6,0
  CALL @mth_log256_fixture_ref_scalar
  ADD r6,r12,r10
  ST r1,r6,0
  ADD r10,r10,r13
  MOVI r6,256
  CMP r10,r6
  JMP[LT] @mth_log256_test_ref_loop

  ; ---- kernel under test ----
  LA r1,@mth_log256_test_in
  LA r2,@mth_log256_test_out
  CALL @mth_vector_log256_f32
  CMP r1,r13
  JMP[NE] @mth_log256_test_fail

  ; ---- tolerance comparison by unsigned float bit patterns ----
  LA r4,@mth_log256_test_out
  LA r12,@mth_log256_test_ref
  MOVI r10,0
mth_log256_test_compare:
  ADD r6,r4,r10
  LD r5,r6,0
  ADD r6,r12,r10
  LD r6,r6,0
  FSUB r5,r5,r6
  MOVI r7,0xFFFF
  MOVHI r7,0x7FFF
  BOOL.8 r5,r5,r7             ; |out-ref|
  MOVI r7,0xFFFF
  MOVHI r7,0x7FFF
  BOOL.8 r6,r6,r7             ; |ref|
  MOVI r7,0xC5AC
  MOVHI r7,0x37A7             ; 2e-5
  FMUL r6,r6,r7
  MOVI r7,0xBF95
  MOVHI r7,0x33D6             ; 1e-7
  FADD r6,r6,r7
  CMP r5,r6
  JMP[GT] @mth_log256_test_fail
  ADD r10,r10,r13
  MOVI r6,256
  CMP r10,r6
  JMP[LT] @mth_log256_test_compare

  ; log(1) must be exactly +0.0; index 0 is 1.0.
  LA r4,@mth_log256_test_out
  LD r5,r4,0
  CMP r5,r0
  JMP[NE] @mth_log256_test_fail

  ; log(e) close to +1, absolute tolerance 1e-4; index 12 is e.
  LD r5,r4,12
  MOVI r6,0
  MOVHI r6,0x3F80
  FSUB r5,r5,r6
  MOVI r7,0xFFFF
  MOVHI r7,0x7FFF
  BOOL.8 r5,r5,r7
  MOVI r6,0xB717
  MOVHI r6,0x38D1
  CMP r5,r6
  JMP[GT] @mth_log256_test_fail

  ; log(1e30) + log(1e-30) = 0 within 1e-5; indices 11 and 10.
  LD r5,r4,11
  LD r6,r4,10
  FADD r5,r5,r6
  MOVI r7,0xFFFF
  MOVHI r7,0x7FFF
  BOOL.8 r5,r5,r7
  MOVI r6,0xC5AC
  MOVHI r6,0x37A7             ; 2e-5
  CMP r5,r6
  JMP[GT] @mth_log256_test_fail

  ; ---- atomic rejection of non-positive / non-finite inputs ----
  LA r4,@mth_log256_test_out
  MOVI r5,0xBEEF
  MOVHI r5,0xDEAD
  MOVI r3,0
mth_log256_test_fill_sentinel:
  ADD r6,r4,r3
  ST r5,r6,0
  ADD r3,r3,r13
  MOVI r6,256
  CMP r3,r6
  JMP[LT] @mth_log256_test_fill_sentinel

  LA r11,@mth_log256_test_in
  MOVI r5,0
  MOVHI r5,0x3F80
  MOVI r3,0
mth_log256_test_fill_ones:
  ADD r6,r11,r3
  ST r5,r6,0
  ADD r3,r3,r13
  MOVI r6,256
  CMP r3,r6
  JMP[LT] @mth_log256_test_fill_ones

  ; +0
  ST r0,r11,137
  LA r1,@mth_log256_test_in
  LA r2,@mth_log256_test_out
  CALL @mth_vector_log256_f32
  CMP r1,r0
  JMP[NE] @mth_log256_test_fail
  CALL @mth_log256_test_check_sentinel

  ; -0
  MOVI r5,0
  MOVHI r5,0x8000
  ST r5,r11,137
  LA r1,@mth_log256_test_in
  LA r2,@mth_log256_test_out
  CALL @mth_vector_log256_f32
  CMP r1,r0
  JMP[NE] @mth_log256_test_fail
  CALL @mth_log256_test_check_sentinel

  ; -1
  MOVI r5,0
  MOVHI r5,0xBF80
  ST r5,r11,137
  LA r1,@mth_log256_test_in
  LA r2,@mth_log256_test_out
  CALL @mth_vector_log256_f32
  CMP r1,r0
  JMP[NE] @mth_log256_test_fail
  CALL @mth_log256_test_check_sentinel

  ; +inf
  MOVI r5,0
  MOVHI r5,0x7F80
  ST r5,r11,137
  LA r1,@mth_log256_test_in
  LA r2,@mth_log256_test_out
  CALL @mth_vector_log256_f32
  CMP r1,r0
  JMP[NE] @mth_log256_test_fail
  CALL @mth_log256_test_check_sentinel

  ; NaN
  MOVI r5,0
  MOVHI r5,0x7FC0
  ST r5,r11,137
  LA r1,@mth_log256_test_in
  LA r2,@mth_log256_test_out
  CALL @mth_vector_log256_f32
  CMP r1,r0
  JMP[NE] @mth_log256_test_fail
  CALL @mth_log256_test_check_sentinel

  LA r1,@mth_log256_test_pass
  CALL @mth_log256_test_puts
  HALT

mth_log256_test_check_sentinel:
  LA r4,@mth_log256_test_out
  MOVI r5,0xBEEF
  MOVHI r5,0xDEAD
  MOVI r3,0
mth_log256_test_sentinel_loop:
  ADD r6,r4,r3
  LD r7,r6,0
  CMP r7,r5
  JMP[NE] @mth_log256_test_fail
  ADD r3,r3,r13
  MOVI r6,256
  CMP r3,r6
  JMP[LT] @mth_log256_test_sentinel_loop
  RET

mth_log256_test_fail:
  LA r1,@mth_log256_test_bad
  CALL @mth_log256_test_puts
  HALT

mth_log256_test_puts:
  MOVI r4,255
mth_log256_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_log256_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_log256_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_log256_test_puts_word

; Independent guest reference: r1 = positive finite nonzero x bits -> ln(x) bits.
; Uses the same exponent split but ln(1+f) with f=m-1 and the alternating
; degree-24 series, not the kernel's atanh form. Clobbers r2-r9, preserves r10-r14.
mth_log256_fixture_ref_scalar:
  ADD r2,r1,r0
  SHR r3,r2,23
  CMP r3,r0
  JMP[EQ] @mth_log256_ref_subnormal
  MOVI r4,0xFFFF
  MOVHI r4,0x007F
  BOOL.8 r5,r2,r4
  MOVI r4,127
  SUB r6,r3,r4
  JMP @mth_log256_ref_mantissa

mth_log256_ref_subnormal:
  MOVI r4,0xFFFF
  MOVHI r4,0x007F
  BOOL.8 r5,r2,r4
  MOVI r3,0
  MOVI r4,0
  MOVHI r4,0x0080
mth_log256_ref_sub_loop:
  BOOL.8 r7,r5,r4
  CMP r7,r0
  JMP[NE] @mth_log256_ref_sub_ready
  SHL r5,r5,1
  ADD r3,r3,r13
  JMP @mth_log256_ref_sub_loop
mth_log256_ref_sub_ready:
  MOVI r4,0xFFFF
  MOVHI r4,0x007F
  BOOL.8 r5,r5,r4
  MOVI r6,126
  ADD r6,r6,r3
  SUB r6,r0,r6

mth_log256_ref_mantissa:
  MOVI r4,0
  MOVHI r4,0x3F80
  BOOL.14 r5,r5,r4
  MOVI r4,0x04F3
  MOVHI r4,0x3FB5
  CMP r5,r4
  JMP[LE] @mth_log256_ref_m_ready
  MOVI r4,0
  MOVHI r4,0x0080
  SUB r5,r5,r4
  ADD r6,r6,r13
mth_log256_ref_m_ready:
  MOVI r4,0
  MOVHI r4,0x3F80
  FSUB r8,r5,r4               ; f = m-1

  ; ln(1+f) alternating series through f^24.
  MOVI r7,0xAAAB
  MOVHI r7,0xBD2A             ; -1/24
  MOVI r4,0x1643
  MOVHI r4,0x3D32             ; +1/23
  FMUL r7,r7,r8
  FADD r7,r7,r4
  MOVI r4,0x2E8C
  MOVHI r4,0xBD3A             ; -1/22
  FMUL r7,r7,r8
  FADD r7,r7,r4
  MOVI r4,0x0C31
  MOVHI r4,0x3D43             ; +1/21
  FMUL r7,r7,r8
  FADD r7,r7,r4
  MOVI r4,0xCCCD
  MOVHI r4,0xBD4C             ; -1/20
  FMUL r7,r7,r8
  FADD r7,r7,r4
  MOVI r4,0x9436
  MOVHI r4,0x3D57             ; +1/19
  FMUL r7,r7,r8
  FADD r7,r7,r4
  MOVI r4,0x8E39
  MOVHI r4,0xBD63             ; -1/18
  FMUL r7,r7,r8
  FADD r7,r7,r4
  MOVI r4,0xF0F1
  MOVHI r4,0x3D70             ; +1/17
  FMUL r7,r7,r8
  FADD r7,r7,r4
  MOVI r4,0
  MOVHI r4,0xBD80             ; -1/16
  FMUL r7,r7,r8
  FADD r7,r7,r4
  MOVI r4,0x8889
  MOVHI r4,0x3D88             ; +1/15
  FMUL r7,r7,r8
  FADD r7,r7,r4
  MOVI r4,0x4925
  MOVHI r4,0xBD92             ; -1/14
  FMUL r7,r7,r8
  FADD r7,r7,r4
  MOVI r4,0x89D9
  MOVHI r4,0x3D9D             ; +1/13
  FMUL r7,r7,r8
  FADD r7,r7,r4
  MOVI r4,0xAAAB
  MOVHI r4,0xBDAA             ; -1/12
  FMUL r7,r7,r8
  FADD r7,r7,r4
  MOVI r4,0x2E8C
  MOVHI r4,0x3DBA             ; +1/11
  FMUL r7,r7,r8
  FADD r7,r7,r4
  MOVI r4,0xCCCD
  MOVHI r4,0xBDCC             ; -1/10
  FMUL r7,r7,r8
  FADD r7,r7,r4
  MOVI r4,0x8E39
  MOVHI r4,0x3DE3             ; +1/9
  FMUL r7,r7,r8
  FADD r7,r7,r4
  MOVI r4,0
  MOVHI r4,0xBE00             ; -1/8
  FMUL r7,r7,r8
  FADD r7,r7,r4
  MOVI r4,0x4925
  MOVHI r4,0x3E12             ; +1/7
  FMUL r7,r7,r8
  FADD r7,r7,r4
  MOVI r4,0xAAAB
  MOVHI r4,0xBE2A             ; -1/6
  FMUL r7,r7,r8
  FADD r7,r7,r4
  MOVI r4,0xCCCD
  MOVHI r4,0x3E4C             ; +1/5
  FMUL r7,r7,r8
  FADD r7,r7,r4
  MOVI r4,0
  MOVHI r4,0xBE80             ; -1/4
  FMUL r7,r7,r8
  FADD r7,r7,r4
  MOVI r4,0xAAAB
  MOVHI r4,0x3EAA             ; +1/3
  FMUL r7,r7,r8
  FADD r7,r7,r4
  MOVI r4,0
  MOVHI r4,0xBF00             ; -1/2
  FMUL r7,r7,r8
  FADD r7,r7,r4
  MOVI r4,0
  MOVHI r4,0x3F80             ; +1
  FMUL r7,r7,r8
  FADD r7,r7,r4
  FMUL r8,r8,r7               ; ln(1+f)

  ; exact float(k) by binary decomposition
  ADD r2,r6,r0
  SHR r3,r2,31
  CMP r3,r0
  JMP[EQ] @mth_log256_ref_kabs_ready
  SUB r2,r0,r2
mth_log256_ref_kabs_ready:
  MOVI r7,0
  MOVI r9,128
  CMP r2,r9
  JMP[LT] @mth_log256_ref_k64
  SUB r2,r2,r9
  MOVI r7,0
  MOVHI r7,0x4300
mth_log256_ref_k64:
  MOVI r9,64
  CMP r2,r9
  JMP[LT] @mth_log256_ref_k32
  SUB r2,r2,r9
  MOVI r4,0
  MOVHI r4,0x4280
  FADD r7,r7,r4
mth_log256_ref_k32:
  MOVI r9,32
  CMP r2,r9
  JMP[LT] @mth_log256_ref_k16
  SUB r2,r2,r9
  MOVI r4,0
  MOVHI r4,0x4200
  FADD r7,r7,r4
mth_log256_ref_k16:
  MOVI r9,16
  CMP r2,r9
  JMP[LT] @mth_log256_ref_k8
  SUB r2,r2,r9
  MOVI r4,0
  MOVHI r4,0x4180
  FADD r7,r7,r4
mth_log256_ref_k8:
  MOVI r9,8
  CMP r2,r9
  JMP[LT] @mth_log256_ref_k4
  SUB r2,r2,r9
  MOVI r4,0
  MOVHI r4,0x4100
  FADD r7,r7,r4
mth_log256_ref_k4:
  MOVI r9,4
  CMP r2,r9
  JMP[LT] @mth_log256_ref_k2
  SUB r2,r2,r9
  MOVI r4,0
  MOVHI r4,0x4080
  FADD r7,r7,r4
mth_log256_ref_k2:
  MOVI r9,2
  CMP r2,r9
  JMP[LT] @mth_log256_ref_k1
  SUB r2,r2,r9
  MOVI r4,0
  MOVHI r4,0x4000
  FADD r7,r7,r4
mth_log256_ref_k1:
  MOVI r9,1
  CMP r2,r9
  JMP[LT] @mth_log256_ref_kf_sign
  MOVI r4,0
  MOVHI r4,0x3F80
  FADD r7,r7,r4
mth_log256_ref_kf_sign:
  CMP r3,r0
  JMP[EQ] @mth_log256_ref_kf_ready
  FSUB r7,r0,r7
mth_log256_ref_kf_ready:
  MOVI r9,0x7200
  MOVHI r9,0x3F31
  FMUL r9,r7,r9
  MOVI r4,0xBE8E
  MOVHI r4,0x35BF
  FMUL r4,r7,r4
  FADD r4,r8,r4
  FADD r1,r9,r4
  RET

.org 2048
mth_log256_test_in:
.word 0
.org 2304
mth_log256_test_ref:
.word 0
.org 2560
mth_log256_test_out:
.word 0
.org 2816
mth_log256_test_pass:
.str "MTH VECTOR LOG256 F32 PASS\n"
mth_log256_test_bad:
.str "MTH VECTOR LOG256 F32 FAIL\n"
