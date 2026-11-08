; MTH vector normalize256 float32 fixture — NaN16 only.
;
; The sparse input vectors are generated in the guest at run time: each phase
; fills all 256 words with one base payload, then writes the listed (index,
; payload) pairs. The 256 expected output words are generated the same way
; from literal IEEE binary32 payloads. No host expected-value arithmetic is
; used at fixture build time or run time.
;
; Every success phase checks all 256 output words with integer CMP. Every
; failure phase checks the return status, the cause register, all 256 output
; words (out[0] status, out[1..255] marker).
;
; Success phases:
;   1. sparse positive: x[0]=2, x[64]=1, x[255]=1; sum=4;
;      out=0.5, 0.25, 0.25, zeros elsewhere.
;   2. negative sum: x[3]=-4, x[200]=-4; sum=-8;
;      out=0.5 at 3/200 and -0.0 for every zero dividend.
;   3. signed-zero dividend: x[0]=-0, x[1]=2; sum=2;
;      out[0]=-0, out[1]=1, +0 elsewhere.
;   4. subnormal exact: x[0]=x[1]=0x00000001; sum=0x00000002;
;      out[0]=out[1]=0.5, zeros elsewhere (no FTZ/DAZ).
;   5. RNE rounding: x[0..2]=1; sum=3; out[0..2]=0x3EAAAAAB (1/3 RNE).
;
; Failure phases:
;   6. quiet NaN input at index 17 -> cause 1.
;   7. +inf input at index 200 -> cause 1.
;   8. -inf input at index 3 -> cause 1.
;   9. all +0 input -> zero sum, cause 2.
;  10. all -0 input -> zero sum, cause 2.
;  11. two +max-finite inputs -> sum +inf, cause 3.
;  12. two -max-finite inputs -> sum -inf, cause 3.
;  13. finite partial-storage quotient overflow: x[0]=1, x[1]=2^127,
;      x[2]=-2^127, x[3]=2^-100; the increasing sum is 2^-100, out[0]
;      is stored as 2^100, then x[1]/sum overflows -> cause 4 and all
;      output words are overwritten by the failure marker.
;  14. exact out == x aliasing: the phase-1 sparse case with out=x checks
;      that all 256 aliased words hold the expected quotients.

.org 0
JMP @mth_vnorm_test_main
.include "../nan16/mth_vector_normalize256_f32.nas"

mth_vnorm_test_main:
  MOVI r13,1

  ; ---- Phase 1: sparse positive exact quotients.
  MOVI r1,@mth_vnorm_test_x
  MOVI r2,0
  MOVI r3,@mth_vnorm_test_x_p1
  MOVI r4,3
  CALL @mth_vnorm_test_sparse
  MOVI r1,@mth_vnorm_test_exp
  MOVI r2,0
  MOVI r3,@mth_vnorm_test_e_p1
  MOVI r4,3
  CALL @mth_vnorm_test_sparse
  MOVI r1,@mth_vnorm_test_x
  MOVI r2,@mth_vnorm_test_out
  CALL @mth_vector_normalize256_f32
  CMP r1,r13
  JMP[NE] @mth_vnorm_test_fail
  CMP r9,r0
  JMP[NE] @mth_vnorm_test_fail
  MOVI r1,@mth_vnorm_test_out
  MOVI r2,@mth_vnorm_test_exp
  MOVI r4,256
  CALL @mth_vnorm_test_check256

  ; ---- Phase 2: negative sum, zero dividends become -0.0.
  MOVI r1,@mth_vnorm_test_x
  MOVI r2,0
  MOVI r3,@mth_vnorm_test_x_p2
  MOVI r4,2
  CALL @mth_vnorm_test_sparse
  MOVI r1,@mth_vnorm_test_exp
  MOVI r2,0
  MOVHI r2,0x8000          ; -0.0 base
  MOVI r3,@mth_vnorm_test_e_p2
  MOVI r4,2
  CALL @mth_vnorm_test_sparse
  MOVI r1,@mth_vnorm_test_x
  MOVI r2,@mth_vnorm_test_out
  CALL @mth_vector_normalize256_f32
  CMP r1,r13
  JMP[NE] @mth_vnorm_test_fail
  CMP r9,r0
  JMP[NE] @mth_vnorm_test_fail
  MOVI r1,@mth_vnorm_test_out
  MOVI r2,@mth_vnorm_test_exp
  MOVI r4,256
  CALL @mth_vnorm_test_check256

  ; ---- Phase 3: -0.0 dividend divided by +2.0 stays -0.0.
  MOVI r1,@mth_vnorm_test_x
  MOVI r2,0
  MOVI r3,@mth_vnorm_test_x_p3
  MOVI r4,2
  CALL @mth_vnorm_test_sparse
  MOVI r1,@mth_vnorm_test_exp
  MOVI r2,0
  MOVI r3,@mth_vnorm_test_e_p3
  MOVI r4,2
  CALL @mth_vnorm_test_sparse
  MOVI r1,@mth_vnorm_test_x
  MOVI r2,@mth_vnorm_test_out
  CALL @mth_vector_normalize256_f32
  CMP r1,r13
  JMP[NE] @mth_vnorm_test_fail
  CMP r9,r0
  JMP[NE] @mth_vnorm_test_fail
  MOVI r1,@mth_vnorm_test_out
  MOVI r2,@mth_vnorm_test_exp
  MOVI r4,256
  CALL @mth_vnorm_test_check256

  ; ---- Phase 4: subnormal sum and inputs are not flushed.
  MOVI r1,@mth_vnorm_test_x
  MOVI r2,0
  MOVI r3,@mth_vnorm_test_x_p4
  MOVI r4,2
  CALL @mth_vnorm_test_sparse
  MOVI r1,@mth_vnorm_test_exp
  MOVI r2,0
  MOVI r3,@mth_vnorm_test_e_p4
  MOVI r4,2
  CALL @mth_vnorm_test_sparse
  MOVI r1,@mth_vnorm_test_x
  MOVI r2,@mth_vnorm_test_out
  CALL @mth_vector_normalize256_f32
  CMP r1,r13
  JMP[NE] @mth_vnorm_test_fail
  CMP r9,r0
  JMP[NE] @mth_vnorm_test_fail
  MOVI r1,@mth_vnorm_test_out
  MOVI r2,@mth_vnorm_test_exp
  MOVI r4,256
  CALL @mth_vnorm_test_check256

  ; ---- Phase 5: 1/3 rounds to nearest even.
  MOVI r1,@mth_vnorm_test_x
  MOVI r2,0
  MOVI r3,@mth_vnorm_test_x_p5
  MOVI r4,3
  CALL @mth_vnorm_test_sparse
  MOVI r1,@mth_vnorm_test_exp
  MOVI r2,0
  MOVI r3,@mth_vnorm_test_e_p5
  MOVI r4,3
  CALL @mth_vnorm_test_sparse
  MOVI r1,@mth_vnorm_test_x
  MOVI r2,@mth_vnorm_test_out
  CALL @mth_vector_normalize256_f32
  CMP r1,r13
  JMP[NE] @mth_vnorm_test_fail
  CMP r9,r0
  JMP[NE] @mth_vnorm_test_fail
  MOVI r1,@mth_vnorm_test_out
  MOVI r2,@mth_vnorm_test_exp
  MOVI r4,256
  CALL @mth_vnorm_test_check256

  ; ---- Phase 6: quiet NaN input rejects with cause 1.
  MOVI r1,@mth_vnorm_test_x
  MOVI r2,0
  MOVI r3,@mth_vnorm_test_x_p6
  MOVI r4,1
  CALL @mth_vnorm_test_sparse
  MOVI r1,@mth_vnorm_test_x
  MOVI r2,@mth_vnorm_test_out
  CALL @mth_vector_normalize256_f32
  MOVI r5,1
  CALL @mth_vnorm_test_check_failure

  ; ---- Phase 7: +inf input rejects with cause 1.
  MOVI r1,@mth_vnorm_test_x
  MOVI r2,0
  MOVI r3,@mth_vnorm_test_x_p7
  MOVI r4,1
  CALL @mth_vnorm_test_sparse
  MOVI r1,@mth_vnorm_test_x
  MOVI r2,@mth_vnorm_test_out
  CALL @mth_vector_normalize256_f32
  MOVI r5,1
  CALL @mth_vnorm_test_check_failure

  ; ---- Phase 8: -inf input rejects with cause 1.
  MOVI r1,@mth_vnorm_test_x
  MOVI r2,0
  MOVI r3,@mth_vnorm_test_x_p8
  MOVI r4,1
  CALL @mth_vnorm_test_sparse
  MOVI r1,@mth_vnorm_test_x
  MOVI r2,@mth_vnorm_test_out
  CALL @mth_vector_normalize256_f32
  MOVI r5,1
  CALL @mth_vnorm_test_check_failure

  ; ---- Phase 9: all +0.0 input has zero sum, cause 2.
  MOVI r1,@mth_vnorm_test_x
  MOVI r2,0
  MOVI r3,@mth_vnorm_test_p_empty
  MOVI r4,0
  CALL @mth_vnorm_test_sparse
  MOVI r1,@mth_vnorm_test_x
  MOVI r2,@mth_vnorm_test_out
  CALL @mth_vector_normalize256_f32
  MOVI r5,2
  CALL @mth_vnorm_test_check_failure

  ; ---- Phase 10: all -0.0 input has zero sum, cause 2.
  MOVI r1,@mth_vnorm_test_x
  MOVI r2,0
  MOVHI r2,0x8000          ; -0.0 base
  MOVI r3,@mth_vnorm_test_p_empty
  MOVI r4,0
  CALL @mth_vnorm_test_sparse
  MOVI r1,@mth_vnorm_test_x
  MOVI r2,@mth_vnorm_test_out
  CALL @mth_vector_normalize256_f32
  MOVI r5,2
  CALL @mth_vnorm_test_check_failure

  ; ---- Phase 11: +max-finite + +max-finite overflows the sum, cause 3.
  MOVI r1,@mth_vnorm_test_x
  MOVI r2,0
  MOVI r3,@mth_vnorm_test_x_p11
  MOVI r4,2
  CALL @mth_vnorm_test_sparse
  MOVI r1,@mth_vnorm_test_x
  MOVI r2,@mth_vnorm_test_out
  CALL @mth_vector_normalize256_f32
  MOVI r5,3
  CALL @mth_vnorm_test_check_failure

  ; ---- Phase 12: -max-finite + -max-finite overflows the sum, cause 3.
  MOVI r1,@mth_vnorm_test_x
  MOVI r2,0
  MOVI r3,@mth_vnorm_test_x_p12
  MOVI r4,2
  CALL @mth_vnorm_test_sparse
  MOVI r1,@mth_vnorm_test_x
  MOVI r2,@mth_vnorm_test_out
  CALL @mth_vector_normalize256_f32
  MOVI r5,3
  CALL @mth_vnorm_test_check_failure

  ; ---- Phase 13: quotient overflow after a partial store, cause 4.
  MOVI r1,@mth_vnorm_test_x
  MOVI r2,0
  MOVI r3,@mth_vnorm_test_x_p13
  MOVI r4,4
  CALL @mth_vnorm_test_sparse
  MOVI r1,@mth_vnorm_test_x
  MOVI r2,@mth_vnorm_test_out
  CALL @mth_vector_normalize256_f32
  MOVI r5,4
  CALL @mth_vnorm_test_check_failure

  ; ---- Phase 14: exact out == x aliasing is safe.
  MOVI r1,@mth_vnorm_test_x
  MOVI r2,0
  MOVI r3,@mth_vnorm_test_x_p1
  MOVI r4,3
  CALL @mth_vnorm_test_sparse
  MOVI r1,@mth_vnorm_test_exp
  MOVI r2,0
  MOVI r3,@mth_vnorm_test_e_p1
  MOVI r4,3
  CALL @mth_vnorm_test_sparse
  MOVI r1,@mth_vnorm_test_x
  MOVI r2,@mth_vnorm_test_x
  CALL @mth_vector_normalize256_f32
  CMP r1,r13
  JMP[NE] @mth_vnorm_test_fail
  CMP r9,r0
  JMP[NE] @mth_vnorm_test_fail
  MOVI r1,@mth_vnorm_test_x
  MOVI r2,@mth_vnorm_test_exp
  MOVI r4,256
  CALL @mth_vnorm_test_check256

  MOVI r1,@mth_vnorm_test_pass
  CALL @mth_vnorm_test_puts
  HALT

mth_vnorm_test_fail:
  MOVI r1,@mth_vnorm_test_bad
  CALL @mth_vnorm_test_puts
  HALT

; r1 = out, r5 = expected cause. Checks r1=0, r9=cause, out[0]=status,
; and out[1..255]=0xFFC0DEAD. Clobbers r1-r3, r5-r7.
mth_vnorm_test_check_failure:
  CMP r1,r0
  JMP[NE] @mth_vnorm_test_fail
  CMP r9,r5
  JMP[NE] @mth_vnorm_test_fail
  MOVI r1,@mth_vnorm_test_out
  MOVI r2,0xDEAC
  MOVHI r2,0xFFC0
  ADD r2,r2,r9             ; status = 0xFFC0DEAC + cause
  MOVI r4,0
  ADD r6,r1,r4
  LD r6,r6,0
  CMP r6,r2
  JMP[NE] @mth_vnorm_test_fail
  MOVI r7,0xDEAD
  MOVHI r7,0xFFC0          ; marker
  MOVI r4,1
mth_vnorm_test_check_failure_fill:
  ADD r6,r1,r4
  LD r6,r6,0
  CMP r6,r7
  JMP[NE] @mth_vnorm_test_fail
  ADD r4,r4,r13
  MOVI r6,256
  CMP r4,r6
  JMP[LT] @mth_vnorm_test_check_failure_fill
  RET

; r1 = destination, r2 = base payload, r3 = (index,payload) pairs,
; r4 = pair count. Fills 256 words with base, then writes the pairs.
; Clobbers r1, r5-r9.
mth_vnorm_test_sparse:
  ADD r7,r1,r0             ; save destination
  MOVI r5,256
mth_vnorm_test_sparse_fill:
  ST r2,r1,0
  ADD r1,r1,r13
  SUB r5,r5,r13
  CMP r5,r0
  JMP[GT] @mth_vnorm_test_sparse_fill
  CMP r4,r0
  JMP[EQ] @mth_vnorm_test_sparse_done
mth_vnorm_test_sparse_pairs:
  LD r8,r3,0
  ADD r3,r3,r13
  LD r9,r3,0
  ADD r3,r3,r13
  ADD r8,r7,r8
  ST r9,r8,0
  SUB r4,r4,r13
  CMP r4,r0
  JMP[GT] @mth_vnorm_test_sparse_pairs
mth_vnorm_test_sparse_done:
  RET

; r1 = actual, r2 = expected, r4 = count. Clobbers r1, r2, r4-r6.
mth_vnorm_test_check256:
  LD r5,r1,0
  LD r6,r2,0
  CMP r5,r6
  JMP[NE] @mth_vnorm_test_fail
  ADD r1,r1,r13
  ADD r2,r2,r13
  SUB r4,r4,r13
  CMP r4,r0
  JMP[GT] @mth_vnorm_test_check256
  RET

mth_vnorm_test_puts:
  MOVI r4,255
mth_vnorm_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_vnorm_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_vnorm_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_vnorm_test_puts_word

.org 1024
mth_vnorm_test_x:
.word 0
.org 2048
mth_vnorm_test_out:
.word 0
.org 3072
mth_vnorm_test_exp:
.word 0
.org 4096
mth_vnorm_test_x_p1:
.word 0,0x40000000          ; 2.0
.word 64,0x3F800000         ; 1.0
.word 255,0x3F800000        ; 1.0
mth_vnorm_test_e_p1:
.word 0,0x3F000000          ; 0.5
.word 64,0x3E800000         ; 0.25
.word 255,0x3E800000        ; 0.25
mth_vnorm_test_x_p2:
.word 3,0xC0800000          ; -4.0
.word 200,0xC0800000        ; -4.0
mth_vnorm_test_e_p2:
.word 3,0x3F000000          ; 0.5
.word 200,0x3F000000        ; 0.5
mth_vnorm_test_x_p3:
.word 0,0x80000000          ; -0.0
.word 1,0x40000000          ; 2.0
mth_vnorm_test_e_p3:
.word 0,0x80000000          ; -0.0
.word 1,0x3F800000          ; 1.0
mth_vnorm_test_x_p4:
.word 0,0x00000001          ; min subnormal
.word 1,0x00000001          ; min subnormal
mth_vnorm_test_e_p4:
.word 0,0x3F000000          ; 0.5
.word 1,0x3F000000          ; 0.5
mth_vnorm_test_x_p5:
.word 0,0x3F800000          ; 1.0
.word 1,0x3F800000          ; 1.0
.word 2,0x3F800000          ; 1.0
mth_vnorm_test_e_p5:
.word 0,0x3EAAAAAB          ; 1/3 RNE
.word 1,0x3EAAAAAB
.word 2,0x3EAAAAAB
mth_vnorm_test_x_p6:
.word 17,0x7FC00123         ; quiet NaN
mth_vnorm_test_x_p7:
.word 200,0x7F800000        ; +inf
mth_vnorm_test_x_p8:
.word 3,0xFF800000          ; -inf
mth_vnorm_test_x_p11:
.word 0,0x7F7FFFFF          ; +max finite
.word 1,0x7F7FFFFF
mth_vnorm_test_x_p12:
.word 0,0xFF7FFFFF          ; -max finite
.word 1,0xFF7FFFFF
mth_vnorm_test_x_p13:
.word 0,0x3F800000          ; 1.0
.word 1,0x7F000000          ; 2^127
.word 2,0xFF000000          ; -2^127
.word 3,0x0D800000          ; 2^-100
mth_vnorm_test_p_empty:
.word 0
.org 8192
mth_vnorm_test_pass:
.str "MTH VECTOR NORMALIZE256 F32 PASS\n"
mth_vnorm_test_bad:
.str "MTH VECTOR NORMALIZE256 F32 FAIL\n"
