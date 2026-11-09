; MTH vector exp256 float32 fixture — NaN16 only.
;
; All 256 inputs are generated in the guest. The reference exp is an
; independent in-guest degree-18 Taylor evaluation with a loop-based integer
; range reduction and loop-based power-of-two scaling. No expected array is
; computed on the host. The comparison uses nonnegative float bit patterns as
; unsigned integers, so NaN differences cannot pass as "small".
;
; Main comparison range: x in [-80, 79.375] plus a few anchor points.
; Tolerance: |out-ref| <= 2e-5*|ref| (pure relative; ref is never zero here).

.org 0
JMP @mth_exp256_test_main
.include "../nan16/mth_vector_exp256_f32.nas"

mth_exp256_test_main:
  MOVI r13,1

  ; ---- x[i] = (i-128)*0.625 ----
  LA r11,@mth_exp256_test_in
  MOVI r3,0
mth_exp256_test_fill:
  ADD r4,r3,r0
  MOVI r5,128
  SUB r4,r4,r5
  CVTIF r5,r4
  MOVI r6,0
  MOVHI r6,0x3F20             ; 0.625
  FMUL r5,r5,r6
  ADD r6,r11,r3
  ST r5,r6,0
  ADD r3,r3,r13
  MOVI r6,256
  CMP r3,r6
  JMP[LT] @mth_exp256_test_fill

  ; ---- anchor / edge overrides, still written by the guest ----
  MOVI r5,0
  MOVHI r5,0x3F80             ; 1.0
  ST r5,r11,0
  MOVI r5,0
  MOVHI r5,0xBF80             ; -1.0
  ST r5,r11,1
  MOVI r5,0
  MOVHI r5,0x3F00             ; 0.5
  ST r5,r11,2
  MOVI r5,0
  MOVHI r5,0xBF00             ; -0.5
  ST r5,r11,3
  MOVI r5,0
  MOVHI r5,0x3A80             ; 1/1024
  ST r5,r11,4
  MOVI r5,0
  MOVHI r5,0xBA80             ; -1/1024
  ST r5,r11,5
  MOVI r5,0x7218
  MOVHI r5,0x3F31             ; ln(2)
  ST r5,r11,6
  MOVI r5,0x7218
  MOVHI r5,0xBF31             ; -ln(2)
  ST r5,r11,7
  MOVI r5,0
  MOVHI r5,0x4120             ; 10.0
  ST r5,r11,8
  MOVI r5,0
  MOVHI r5,0xC120             ; -10.0
  ST r5,r11,9
  MOVI r5,0
  MOVHI r5,0x4220             ; 40.0
  ST r5,r11,10
  MOVI r5,0
  MOVHI r5,0xC220             ; -40.0
  ST r5,r11,11
  MOVI r5,0
  MOVHI r5,0x429E             ; 79.375
  ST r5,r11,12
  MOVI r5,0
  MOVHI r5,0xC2A0             ; -80.0
  ST r5,r11,13
  MOVI r5,0x126F
  MOVHI r5,0x3A83             ; 0.001
  ST r5,r11,14
  MOVI r5,0x126F
  MOVHI r5,0xBA83             ; -0.001
  ST r5,r11,15
  MOVI r5,0xF854
  MOVHI r5,0x402D             ; e
  ST r5,r11,16
  MOVI r5,0xF854
  MOVHI r5,0xC02D             ; -e
  ST r5,r11,17
  MOVI r5,0
  MOVHI r5,0x42B0             ; 88.0
  ST r5,r11,18
  MOVI r5,0
  MOVHI r5,0xC2B0             ; -88.0
  ST r5,r11,19

  ; ---- in-guest reference array ----
  LA r12,@mth_exp256_test_ref
  MOVI r10,0
mth_exp256_test_ref_loop:
  ADD r6,r11,r10
  LD r1,r6,0
  CALL @mth_exp256_fixture_ref_scalar
  ADD r6,r12,r10
  ST r1,r6,0
  ADD r10,r10,r13
  MOVI r6,256
  CMP r10,r6
  JMP[LT] @mth_exp256_test_ref_loop

  ; ---- kernel under test ----
  LA r1,@mth_exp256_test_in
  LA r2,@mth_exp256_test_out
  CALL @mth_vector_exp256_f32
  CMP r1,r13
  JMP[NE] @mth_exp256_test_fail

  ; ---- tolerant comparison by unsigned float bit patterns ----
  LA r4,@mth_exp256_test_out
  LA r12,@mth_exp256_test_ref
  MOVI r10,0
mth_exp256_test_compare:
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
  FMUL r6,r6,r7               ; tolerance
  CMP r5,r6
  JMP[GT] @mth_exp256_test_fail
  ADD r10,r10,r13
  MOVI r6,256
  CMP r10,r6
  JMP[LT] @mth_exp256_test_compare

  ; exp(+0) must be exactly +1.0; index 128 is the generated zero.
  LA r4,@mth_exp256_test_out
  LD r5,r4,128
  MOVI r6,0
  MOVHI r6,0x3F80
  CMP r5,r6
  JMP[NE] @mth_exp256_test_fail

  ; exp(1) against the float constant e, absolute tolerance 1e-4.
  LD r5,r4,0
  MOVI r6,0xF854
  MOVHI r6,0x402D
  FSUB r5,r5,r6
  MOVI r7,0xFFFF
  MOVHI r7,0x7FFF
  BOOL.8 r5,r5,r7
  MOVI r6,0xB717
  MOVHI r6,0x38D1             ; 1e-4
  CMP r5,r6
  JMP[GT] @mth_exp256_test_fail

  ; exp(1)*exp(-1) = 1 within 2e-5.
  LD r5,r4,0
  LD r6,r4,1
  FMUL r5,r5,r6
  MOVI r6,0
  MOVHI r6,0x3F80
  FSUB r5,r5,r6
  MOVI r7,0xFFFF
  MOVHI r7,0x7FFF
  BOOL.8 r5,r5,r7
  MOVI r6,0xC5AC
  MOVHI r6,0x37A7
  CMP r5,r6
  JMP[GT] @mth_exp256_test_fail

  ; ---- finite saturation endpoints ----
  ; input all +1.0
  LA r11,@mth_exp256_test_in
  MOVI r5,0
  MOVHI r5,0x3F80
  MOVI r3,0
mth_exp256_test_fill_ones:
  ADD r6,r11,r3
  ST r5,r6,0
  ADD r3,r3,r13
  MOVI r6,256
  CMP r3,r6
  JMP[LT] @mth_exp256_test_fill_ones
  MOVI r5,0xFFFF
  MOVHI r5,0x7F7F             ; +FLT_MAX
  ST r5,r11,0
  MOVI r5,0xFFFF
  MOVHI r5,0xFF7F             ; -FLT_MAX
  ST r5,r11,1

  LA r1,@mth_exp256_test_in
  LA r2,@mth_exp256_test_out
  CALL @mth_vector_exp256_f32
  CMP r1,r13
  JMP[NE] @mth_exp256_test_fail
  LA r4,@mth_exp256_test_out
  LD r5,r4,0
  MOVI r6,0
  MOVHI r6,0x7F80             ; +inf
  CMP r5,r6
  JMP[NE] @mth_exp256_test_fail
  LD r5,r4,1
  CMP r5,r0
  JMP[NE] @mth_exp256_test_fail
  LD r5,r4,2
  MOVI r6,0xF854
  MOVHI r6,0x402D
  FSUB r5,r5,r6
  MOVI r7,0xFFFF
  MOVHI r7,0x7FFF
  BOOL.8 r5,r5,r7
  MOVI r6,0xB717
  MOVHI r6,0x38D1
  CMP r5,r6
  JMP[GT] @mth_exp256_test_fail

  ; ---- atomic rejection of non-finite inputs ----
  ; output sentinel = 0xDEADBEEF
  LA r4,@mth_exp256_test_out
  MOVI r5,0xBEEF
  MOVHI r5,0xDEAD
  MOVI r3,0
mth_exp256_test_fill_sentinel:
  ADD r6,r4,r3
  ST r5,r6,0
  ADD r3,r3,r13
  MOVI r6,256
  CMP r3,r6
  JMP[LT] @mth_exp256_test_fill_sentinel

  ; NaN at index 137
  LA r11,@mth_exp256_test_in
  MOVI r5,0
  MOVHI r5,0x7FC0
  ST r5,r11,137
  LA r1,@mth_exp256_test_in
  LA r2,@mth_exp256_test_out
  CALL @mth_vector_exp256_f32
  CMP r1,r0
  JMP[NE] @mth_exp256_test_fail
  CALL @mth_exp256_test_check_sentinel

  ; +inf at index 137
  LA r11,@mth_exp256_test_in
  MOVI r5,0
  MOVHI r5,0x7F80
  ST r5,r11,137
  LA r1,@mth_exp256_test_in
  LA r2,@mth_exp256_test_out
  CALL @mth_vector_exp256_f32
  CMP r1,r0
  JMP[NE] @mth_exp256_test_fail
  CALL @mth_exp256_test_check_sentinel

  ; -inf at index 137
  LA r11,@mth_exp256_test_in
  MOVI r5,0
  MOVHI r5,0xFF80
  ST r5,r11,137
  LA r1,@mth_exp256_test_in
  LA r2,@mth_exp256_test_out
  CALL @mth_vector_exp256_f32
  CMP r1,r0
  JMP[NE] @mth_exp256_test_fail
  CALL @mth_exp256_test_check_sentinel

  ; ---- whole-array output sentinel check ----
  LA r1,@mth_exp256_test_pass
  CALL @mth_exp256_test_puts
  HALT

mth_exp256_test_check_sentinel:
  LA r4,@mth_exp256_test_out
  MOVI r5,0xBEEF
  MOVHI r5,0xDEAD
  MOVI r3,0
mth_exp256_test_sentinel_loop:
  ADD r6,r4,r3
  LD r7,r6,0
  CMP r7,r5
  JMP[NE] @mth_exp256_test_fail
  ADD r3,r3,r13
  MOVI r6,256
  CMP r3,r6
  JMP[LT] @mth_exp256_test_sentinel_loop
  RET

mth_exp256_test_fail:
  LA r1,@mth_exp256_test_bad
  CALL @mth_exp256_test_puts
  HALT

mth_exp256_test_puts:
  MOVI r4,255
mth_exp256_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_exp256_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_exp256_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_exp256_test_puts_word

; Independent guest reference: r1 = finite x bits -> r1 = exp(x) bits.
; Degree-18 Taylor after loop-based trunc(x*log2(e)) reduction, with scaling
; by repeated exact doubling/halving. Clobbers r2-r9. Preserves r10-r14.
mth_exp256_fixture_ref_scalar:
  MOVI r2,0xAA3B
  MOVHI r2,0x3FB8             ; log2(e)
  FMUL r2,r1,r2
  MOVI r3,0                   ; kf = 0.0
  MOVI r4,0                   ; k = 0
  MOVI r5,0
  MOVHI r5,0x3F80             ; 1.0
mth_exp256_ref_pos_loop:
  ADD r6,r2,r0
  SHR r6,r6,31
  CMP r6,r0
  JMP[NE] @mth_exp256_ref_neg_loop
  CMP r2,r5
  JMP[LT] @mth_exp256_ref_reduced
  FSUB r2,r2,r5
  FADD r3,r3,r5
  ADD r4,r4,r13
  JMP @mth_exp256_ref_pos_loop
mth_exp256_ref_neg_loop:
  ADD r6,r2,r0
  MOVI r7,0xFFFF
  MOVHI r7,0x7FFF
  BOOL.8 r6,r6,r7
  CMP r6,r5
  JMP[LT] @mth_exp256_ref_reduced
  FADD r2,r2,r5
  FSUB r3,r3,r5
  SUB r4,r4,r13
  JMP @mth_exp256_ref_pos_loop

mth_exp256_ref_reduced:
  MOVI r6,0x7200
  MOVHI r6,0x3F31
  FMUL r6,r3,r6
  FSUB r6,r1,r6
  MOVI r7,0xBE8E
  MOVHI r7,0x35BF
  FMUL r7,r3,r7
  FSUB r8,r6,r7               ; r

  ; degree-18 Taylor, Horner from 1/18!
  MOVI r9,0x13C3
  MOVHI r9,0x2534
  MOVI r5,0x963C
  MOVHI r5,0x274A
  FMUL r9,r9,r8
  FADD r9,r9,r5
  MOVI r5,0x3F9F
  MOVHI r5,0x2957
  FMUL r9,r9,r8
  FADD r9,r9,r5
  MOVI r5,0x3F9F
  MOVHI r5,0x2B57
  FMUL r9,r9,r8
  FADD r9,r9,r5
  MOVI r5,0xCBA5
  MOVHI r5,0x2D49
  FMUL r9,r9,r8
  FADD r9,r9,r5
  MOVI r5,0x9231
  MOVHI r5,0x2F30
  FMUL r9,r9,r8
  FADD r9,r9,r5
  MOVI r5,0x76C7
  MOVHI r5,0x310F
  FMUL r9,r9,r8
  FADD r9,r9,r5
  MOVI r5,0x322B
  MOVHI r5,0x32D7
  FMUL r9,r9,r8
  FADD r9,r9,r5
  MOVI r5,0xF27E
  MOVHI r5,0x3493
  FMUL r9,r9,r8
  FADD r9,r9,r5
  MOVI r5,0xEF1D
  MOVHI r5,0x3638
  FMUL r9,r9,r8
  FADD r9,r9,r5
  MOVI r5,0x0D01
  MOVHI r5,0x37D0
  FMUL r9,r9,r8
  FADD r9,r9,r5
  MOVI r5,0x0D01
  MOVHI r5,0x3950
  FMUL r9,r9,r8
  FADD r9,r9,r5
  MOVI r5,0x0B61
  MOVHI r5,0x3AB6
  FMUL r9,r9,r8
  FADD r9,r9,r5
  MOVI r5,0x8889
  MOVHI r5,0x3C08
  FMUL r9,r9,r8
  FADD r9,r9,r5
  MOVI r5,0xAAAB
  MOVHI r5,0x3D2A
  FMUL r9,r9,r8
  FADD r9,r9,r5
  MOVI r5,0xAAAB
  MOVHI r5,0x3E2A
  FMUL r9,r9,r8
  FADD r9,r9,r5
  MOVI r5,0
  MOVHI r5,0x3F00
  FMUL r9,r9,r8
  FADD r9,r9,r5
  MOVI r5,0
  MOVHI r5,0x3F80
  FMUL r9,r9,r8
  FADD r9,r9,r5
  MOVI r5,0
  MOVHI r5,0x3F80
  FMUL r9,r9,r8
  FADD r9,r9,r5

  ; scale = 2^k by repeated exact doubling / halving
  MOVI r6,0
  MOVHI r6,0x3F80
  SHR r7,r4,31
  CMP r7,r0
  JMP[NE] @mth_exp256_ref_scale_neg
  ADD r7,r4,r0
mth_exp256_ref_double_loop:
  CMP r7,r0
  JMP[EQ] @mth_exp256_ref_scale_done
  FADD r6,r6,r6
  SUB r7,r7,r13
  JMP @mth_exp256_ref_double_loop
mth_exp256_ref_scale_neg:
  SUB r7,r0,r4
mth_exp256_ref_half_loop:
  CMP r7,r0
  JMP[EQ] @mth_exp256_ref_scale_done
  MOVI r5,0
  MOVHI r5,0x3F00
  FMUL r6,r6,r5
  SUB r7,r7,r13
  JMP @mth_exp256_ref_half_loop
mth_exp256_ref_scale_done:
  FMUL r9,r9,r6
  ADD r1,r9,r0
  RET

.org 2048
mth_exp256_test_in:
.word 0
.org 2304
mth_exp256_test_ref:
.word 0
.org 2560
mth_exp256_test_out:
.word 0
.org 2816
mth_exp256_test_pass:
.str "MTH VECTOR EXP256 F32 PASS\n"
mth_exp256_test_bad:
.str "MTH VECTOR EXP256 F32 FAIL\n"
