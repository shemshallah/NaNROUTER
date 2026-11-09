; MTH native plane-rotation fixture — NaN16 only.
;
; Expected binary32 anchors are an offline test oracle, not runtime constants.
; The guest kernel uses only mth_trig_sincos_f32 and native FMUL/FADD/FSUB.

.org 0
JMP @mth_rotate_test_main
.include "../nan16/mth_trig_sincos_f32.nas"
.include "../nan16/mth_trig_rotate_f32.nas"

mth_rotate_test_main:
  MOVI r0,0
  MOVI r13,1

  ; (1,0) rotated by 0 -> (1,0)
  MOVI r1,0
  MOVHI r1,0x3F80
  ST r1,r0,@mth_rotate_test_x
  ST r0,r0,@mth_rotate_test_y
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x3F80
  MOVI r3,0
  CALL @mth_rotate_test_case

  ; (1,0) rotated by pi/2 -> (0,1)
  MOVI r1,0
  MOVHI r1,0x3F80
  ST r1,r0,@mth_rotate_test_x
  ST r0,r0,@mth_rotate_test_y
  MOVI r1,0x0FDB
  MOVHI r1,0x3FC9
  MOVI r2,0
  MOVI r3,0
  MOVHI r3,0x3F80            ; 1.0
  CALL @mth_rotate_test_case

  ; (1,0) rotated by pi/4 -> (sqrt2/2,sqrt2/2)
  MOVI r1,0
  MOVHI r1,0x3F80
  ST r1,r0,@mth_rotate_test_x
  ST r0,r0,@mth_rotate_test_y
  MOVI r1,0x0FDB
  MOVHI r1,0x3F49
  MOVI r2,0x04F3
  MOVHI r2,0x3F35
  MOVI r3,0x04F3
  MOVHI r3,0x3F35
  CALL @mth_rotate_test_case

  ; (0,1) rotated by -pi/2 -> (1,0)
  ST r0,r0,@mth_rotate_test_x
  MOVI r1,0
  MOVHI r1,0x3F80
  ST r1,r0,@mth_rotate_test_y
  MOVI r1,0x0FDB
  MOVHI r1,0xBFC9
  MOVI r2,0
  MOVHI r2,0x3F80
  MOVI r3,0
  CALL @mth_rotate_test_case

  ; Norm preservation: (3,4) has norm 5, so x^2+y^2 = 25 after any rotation.
  MOVI r1,0
  MOVHI r1,0x4040            ; 3.0
  ST r1,r0,@mth_rotate_test_x
  MOVI r1,0
  MOVHI r1,0x4080            ; 4.0
  ST r1,r0,@mth_rotate_test_y
  MOVI r1,0x6666
  MOVHI r1,0x3F33            ; 0.7
  ST r1,r0,@mth_rotate_test_angle
  CALL @mth_rotate_test_run
  CMP r1,r13
  JMP[NE] @mth_rotate_test_fail
  LD r1,r0,@mth_rotate_test_outx
  LD r2,r0,@mth_rotate_test_outy
  FMUL r1,r1,r1
  FMUL r2,r2,r2
  FADD r1,r1,r2
  MOVI r2,0
  MOVHI r2,0x41C8            ; 25.0
  MOVI r3,0x37BD
  MOVHI r3,0x3727            ; 1e-4
  CALL @mth_rotate_test_near
  CMP r1,r13
  JMP[NE] @mth_rotate_test_fail

  ; Inverse rotation: R(-0.7) R(0.7) (3,4) = (3,4).
  LD r1,r0,@mth_rotate_test_outx
  ST r1,r0,@mth_rotate_test_x
  LD r1,r0,@mth_rotate_test_outy
  ST r1,r0,@mth_rotate_test_y
  MOVI r1,0x6666
  MOVHI r1,0xBF33            ; -0.7
  ST r1,r0,@mth_rotate_test_angle
  CALL @mth_rotate_test_run
  CMP r1,r13
  JMP[NE] @mth_rotate_test_fail
  LD r1,r0,@mth_rotate_test_outx
  MOVI r2,0
  MOVHI r2,0x4040            ; 3.0
  MOVI r3,0x37BD
  MOVHI r3,0x3727            ; 1e-4
  CALL @mth_rotate_test_near
  CMP r1,r13
  JMP[NE] @mth_rotate_test_fail
  LD r1,r0,@mth_rotate_test_outy
  MOVI r2,0
  MOVHI r2,0x4080            ; 4.0
  MOVI r3,0x37BD
  MOVHI r3,0x3727
  CALL @mth_rotate_test_near
  CMP r1,r13
  JMP[NE] @mth_rotate_test_fail

  ; Rejection leaves both outputs untouched.
  MOVI r1,0xBEEF
  MOVHI r1,0xDEAD
  ST r1,r0,@mth_rotate_test_outx
  ST r1,r0,@mth_rotate_test_outy
  MOVI r1,0
  MOVHI r1,0x7F80            ; +inf angle
  ST r1,r0,@mth_rotate_test_angle
  CALL @mth_rotate_test_run
  CMP r1,r0
  JMP[NE] @mth_rotate_test_fail
  MOVI r2,1
  CMP r9,r2
  JMP[NE] @mth_rotate_test_fail
  LD r1,r0,@mth_rotate_test_outx
  MOVI r2,0xBEEF
  MOVHI r2,0xDEAD
  CMP r1,r2
  JMP[NE] @mth_rotate_test_fail
  LD r1,r0,@mth_rotate_test_outy
  CMP r1,r2
  JMP[NE] @mth_rotate_test_fail

  MOVI r1,@mth_rotate_test_pass
  CALL @mth_rotate_test_puts
  HALT

; r1=angle, r2=expected x, r3=expected y. Uses the current fixture x/y.
mth_rotate_test_case:
  ST r15,r0,@mth_rotate_test_ret
  ST r2,r0,@mth_rotate_test_expx
  ST r3,r0,@mth_rotate_test_expy
  ST r1,r0,@mth_rotate_test_angle
  CALL @mth_rotate_test_run
  CMP r1,r13
  JMP[NE] @mth_rotate_test_fail
  LD r1,r0,@mth_rotate_test_outx
  LD r2,r0,@mth_rotate_test_expx
  MOVI r3,0
  MOVHI r3,0x3586            ; 1e-6
  CALL @mth_rotate_test_near
  CMP r1,r13
  JMP[NE] @mth_rotate_test_fail
  LD r1,r0,@mth_rotate_test_outy
  LD r2,r0,@mth_rotate_test_expy
  MOVI r3,0
  MOVHI r3,0x3586
  CALL @mth_rotate_test_near
  CMP r1,r13
  JMP[NE] @mth_rotate_test_fail
  LD r15,r0,@mth_rotate_test_ret
  RET

mth_rotate_test_run:
  ST r15,r0,@mth_rotate_test_run_ret
  MOVI r1,@mth_rotate_test_x
  MOVI r2,@mth_rotate_test_y
  LD r3,r0,@mth_rotate_test_angle
  MOVI r4,@mth_rotate_test_outx
  MOVI r5,@mth_rotate_test_outy
  MOVI r6,@mth_rotate_test_scratch
  CALL @mth_trig_rotate_f32
  LD r15,r0,@mth_rotate_test_run_ret
  RET

; |r1-r2| <= r3.
mth_rotate_test_near:
  MOVI r4,0
  MOVHI r4,0x7FFF
  FSUB r5,r1,r2
  BOOL.8 r5,r5,r4
  FCMP r5,r3
  JMP[GT] @mth_rotate_test_near_fail
  MOVI r1,1
  RET
mth_rotate_test_near_fail:
  MOVI r1,0
  RET

mth_rotate_test_fail:
  MOVI r1,@mth_rotate_test_bad
  CALL @mth_rotate_test_puts
  HALT

mth_rotate_test_puts:
  MOVI r4,255
mth_rotate_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_rotate_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_rotate_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_rotate_test_puts_word

mth_rotate_test_pass:
.str "MTH TRIG ROTATE PASS\n"
mth_rotate_test_bad:
.str "MTH TRIG ROTATE FAIL\n"

.org 4096
mth_rotate_test_ret:
.word 0
mth_rotate_test_run_ret:
.word 0
mth_rotate_test_angle:
.word 0
mth_rotate_test_expx:
.word 0
mth_rotate_test_expy:
.word 0
mth_rotate_test_x:
.word 0
mth_rotate_test_y:
.word 0
mth_rotate_test_outx:
.word 0
mth_rotate_test_outy:
.word 0
mth_rotate_test_scratch:
.word 0,0,0,0,0
