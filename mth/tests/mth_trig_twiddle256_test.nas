; MTH native twiddle256 fixture — NaN16 only.
;
; Checks independent binary32 anchors, the full 256-entry Pythagorean
; identity, conjugate symmetry, and boundary entries. Expected values are an
; offline test oracle, not runtime constants.

.org 0
JMP @mth_twiddle_test_main
.include "../nan16/mth_trig_sincos_f32.nas"
.include "../nan16/mth_trig_twiddle256_f32.nas"

mth_twiddle_test_main:
  MOVI r0,0
  MOVI r13,1
  MOVI r1,@mth_twiddle_test_cos
  MOVI r2,@mth_twiddle_test_sin
  MOVI r3,@mth_twiddle_test_scratch
  CALL @mth_trig_twiddle256_f32
  CMP r1,r13
  JMP[NE] @mth_twiddle_test_fail

  ; k=0: (1,0)
  MOVI r1,@mth_twiddle_test_cos
  LD r2,r1,0
  MOVI r3,0
  MOVHI r3,0x3F80
  CALL @mth_twiddle_test_anchor
  MOVI r1,@mth_twiddle_test_sin
  LD r2,r1,0
  MOVI r3,0
  CALL @mth_twiddle_test_anchor

  ; k=32: (sqrt2/2,sqrt2/2)
  MOVI r1,@mth_twiddle_test_cos
  ADDI r1,r1,32
  LD r2,r1,0
  MOVI r3,0x04F3
  MOVHI r3,0x3F35
  CALL @mth_twiddle_test_anchor
  MOVI r1,@mth_twiddle_test_sin
  ADDI r1,r1,32
  LD r2,r1,0
  MOVI r3,0x04F3
  MOVHI r3,0x3F35
  CALL @mth_twiddle_test_anchor

  ; k=64: (0,1)
  MOVI r1,@mth_twiddle_test_cos
  ADDI r1,r1,64
  LD r2,r1,0
  MOVI r3,0
  CALL @mth_twiddle_test_anchor
  MOVI r1,@mth_twiddle_test_sin
  ADDI r1,r1,64
  LD r2,r1,0
  MOVI r3,0
  MOVHI r3,0x3F80
  CALL @mth_twiddle_test_anchor

  ; k=96: (-sqrt2/2,sqrt2/2)
  MOVI r1,@mth_twiddle_test_cos
  ADDI r1,r1,96
  LD r2,r1,0
  MOVI r3,0x04F3
  MOVHI r3,0xBF35
  CALL @mth_twiddle_test_anchor
  MOVI r1,@mth_twiddle_test_sin
  ADDI r1,r1,96
  LD r2,r1,0
  MOVI r3,0x04F3
  MOVHI r3,0x3F35
  CALL @mth_twiddle_test_anchor

  ; k=128: (-1,0)
  MOVI r1,@mth_twiddle_test_cos
  ADDI r1,r1,128
  LD r2,r1,0
  MOVI r3,0
  MOVHI r3,0xBF80
  CALL @mth_twiddle_test_anchor
  MOVI r1,@mth_twiddle_test_sin
  ADDI r1,r1,128
  LD r2,r1,0
  MOVI r3,0
  CALL @mth_twiddle_test_anchor

  ; k=192: (0,-1)
  MOVI r1,@mth_twiddle_test_cos
  ADDI r1,r1,192
  LD r2,r1,0
  MOVI r3,0
  CALL @mth_twiddle_test_anchor
  MOVI r1,@mth_twiddle_test_sin
  ADDI r1,r1,192
  LD r2,r1,0
  MOVI r3,0
  MOVHI r3,0xBF80
  CALL @mth_twiddle_test_anchor

  ; k=255 anchor
  MOVI r1,@mth_twiddle_test_cos
  ADDI r1,r1,255
  LD r2,r1,0
  MOVI r3,0xEC43
  MOVHI r3,0x3F7F
  CALL @mth_twiddle_test_anchor
  MOVI r1,@mth_twiddle_test_sin
  ADDI r1,r1,255
  LD r2,r1,0
  MOVI r3,0x0AB0
  MOVHI r3,0xBCC9
  CALL @mth_twiddle_test_anchor

  ; Full identity cos^2 + sin^2 = 1.
  MOVI r6,0
mth_twiddle_test_identity:
  MOVI r7,@mth_twiddle_test_cos
  ADD r7,r7,r6
  LD r1,r7,0
  MOVI r7,@mth_twiddle_test_sin
  ADD r7,r7,r6
  LD r2,r7,0
  FMUL r1,r1,r1
  FMUL r2,r2,r2
  FADD r1,r1,r2
  MOVI r2,0
  MOVHI r2,0x3F80
  MOVI r3,0
  MOVHI r3,0x3806             ; 4e-5
  CALL @mth_twiddle_test_near
  CMP r1,r13
  JMP[NE] @mth_twiddle_test_fail
  ADDI r6,r6,1
  MOVI r8,256
  CMP r6,r8
  JMP[LT] @mth_twiddle_test_identity

  ; Conjugate symmetry for all k=1..127.
  MOVI r6,1
mth_twiddle_test_symmetry:
  MOVI r7,@mth_twiddle_test_cos
  ADD r7,r7,r6
  LD r1,r7,0
  MOVI r8,256
  SUB r8,r8,r6
  MOVI r7,@mth_twiddle_test_cos
  ADD r7,r7,r8
  LD r2,r7,0
  MOVI r3,0
  MOVHI r3,0x3606             ; 2e-5
  CALL @mth_twiddle_test_near
  CMP r1,r13
  JMP[NE] @mth_twiddle_test_fail

  MOVI r7,@mth_twiddle_test_sin
  ADD r7,r7,r6
  LD r1,r7,0
  MOVI r7,@mth_twiddle_test_sin
  ADD r7,r7,r8
  LD r2,r7,0
  MOVI r8,0
  MOVHI r8,0x8000
  BOOL.6 r2,r2,r8             ; -sin(256-k)
  MOVI r3,0
  MOVHI r3,0x3606
  CALL @mth_twiddle_test_near
  CMP r1,r13
  JMP[NE] @mth_twiddle_test_fail

  ADDI r6,r6,1
  MOVI r8,128
  CMP r6,r8
  JMP[LT] @mth_twiddle_test_symmetry

  MOVI r1,@mth_twiddle_test_pass
  CALL @mth_twiddle_test_puts
  HALT

; r2=actual, r3=expected, tolerance 2e-5
mth_twiddle_test_anchor:
  ST r15,r0,@mth_twiddle_test_anchor_ret
  MOVI r4,0
  MOVHI r4,0x3606             ; 2e-5
  ADD r1,r2,r0
  ADD r2,r3,r0
  ADD r3,r4,r0
  CALL @mth_twiddle_test_near
  CMP r1,r13
  JMP[NE] @mth_twiddle_test_fail
  LD r15,r0,@mth_twiddle_test_anchor_ret
  RET

; |r1-r2| <= r3
mth_twiddle_test_near:
  MOVI r4,0
  MOVHI r4,0x7FFF
  FSUB r5,r1,r2
  BOOL.8 r5,r5,r4
  FCMP r5,r3
  JMP[GT] @mth_twiddle_test_near_fail
  MOVI r1,1
  RET
mth_twiddle_test_near_fail:
  MOVI r1,0
  RET

mth_twiddle_test_fail:
  MOVI r1,@mth_twiddle_test_bad
  CALL @mth_twiddle_test_puts
  HALT

mth_twiddle_test_puts:
  MOVI r4,255
mth_twiddle_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_twiddle_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_twiddle_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_twiddle_test_puts_word

mth_twiddle_test_pass:
.str "MTH TRIG TWIDDLE256 PASS\n"
mth_twiddle_test_bad:
.str "MTH TRIG TWIDDLE256 FAIL\n"

.org 4096
mth_twiddle_test_cos:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_twiddle_test_sin:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_twiddle_test_scratch:
.word 0,0,0,0
mth_twiddle_test_anchor_ret:
.word 0
