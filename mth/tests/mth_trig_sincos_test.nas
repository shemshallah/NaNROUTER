; MTH native sine/cosine fixture — NaN16 only.
;
; The expected binary32 anchors below are a test oracle only. They were
; generated offline with a float64 reference and rounded to binary32; the
; guest kernel does not read them as runtime constants or call host math.
;
; Coverage:
;   * 0, pi/6, pi/4, pi/3, pi/2, 2pi/3, pi, negative quadrants, 1.0, -2.5,
;     and a large accepted angle (100.0);
;   * sine/cosine component tolerance 2^-18;
;   * sin(-x) = -sin(x) and cos(-x) = cos(x);
;   * sin^2+cos^2 = 1;
;   * |angle| > 128 and non-finite rejection with distinct causes.

.org 0
JMP @mth_trig_test_main
.include "../nan16/mth_trig_sincos_f32.nas"

mth_trig_test_main:
  MOVI r0,0
  MOVI r13,1

  ; angle, expected sin, expected cos
  MOVI r1,0
  MOVI r2,0
  MOVI r3,0
  MOVHI r3,0x3F80            ; 1.0
  CALL @mth_trig_test_case

  MOVI r1,0x0A92
  MOVHI r1,0x3F06            ; pi/6
  MOVI r2,0
  MOVHI r2,0x3F00            ; 0.5
  MOVI r3,0xB3D7
  MOVHI r3,0x3F5D            ; sqrt(3)/2
  CALL @mth_trig_test_case

  MOVI r1,0x0FDB
  MOVHI r1,0x3F49            ; pi/4
  MOVI r2,0x04F3
  MOVHI r2,0x3F35            ; sqrt(2)/2
  MOVI r3,0x04F3
  MOVHI r3,0x3F35
  CALL @mth_trig_test_case

  MOVI r1,0x0A92
  MOVHI r1,0x3F86            ; pi/3
  MOVI r2,0xB3D7
  MOVHI r2,0x3F5D
  MOVI r3,0
  MOVHI r3,0x3F00
  CALL @mth_trig_test_case

  MOVI r1,0x0FDB
  MOVHI r1,0x3FC9            ; pi/2
  MOVI r2,0
  MOVHI r2,0x3F80            ; 1.0
  MOVI r3,0
  CALL @mth_trig_test_case

  MOVI r1,0x0A92
  MOVHI r1,0x4006            ; 2pi/3
  MOVI r2,0xB3D7
  MOVHI r2,0x3F5D
  MOVI r3,0
  MOVHI r3,0xBF00            ; -0.5
  CALL @mth_trig_test_case

  MOVI r1,0x0FDB
  MOVHI r1,0x4049            ; pi
  MOVI r2,0
  MOVI r3,0
  MOVHI r3,0xBF80            ; -1.0
  CALL @mth_trig_test_case

  MOVI r1,0x0A92
  MOVHI r1,0xBF06            ; -pi/6
  MOVI r2,0
  MOVHI r2,0xBF00            ; -0.5
  MOVI r3,0xB3D7
  MOVHI r3,0x3F5D
  CALL @mth_trig_test_case

  MOVI r1,0
  MOVHI r1,0x3F80            ; 1.0
  MOVI r2,0x6AA4
  MOVHI r2,0x3F57            ; sin(1)
  MOVI r3,0x5140
  MOVHI r3,0x3F0A            ; cos(1)
  CALL @mth_trig_test_case

  MOVI r1,0
  MOVHI r1,0xC020            ; -2.5
  MOVI r2,0x3578
  MOVHI r2,0xBF19            ; sin(-2.5)
  MOVI r3,0x17BF
  MOVHI r3,0xBF4D            ; cos(-2.5)
  CALL @mth_trig_test_case

  MOVI r1,0
  MOVHI r1,0x42C8            ; 100.0
  MOVI r2,0xA12E
  MOVHI r2,0xBF01            ; sin(100)
  MOVI r3,0xC0EE
  MOVHI r3,0x3F5C            ; cos(100)
  CALL @mth_trig_test_large

  ; ---- symmetry: sin(-1) = -sin(1), cos(-1) = cos(1) ----
  MOVI r1,0
  MOVHI r1,0x3F80
  CALL @mth_trig_sincos_f32
  CMP r1,r13
  JMP[NE] @mth_trig_test_fail
  ST r2,r0,@mth_trig_test_save_sin
  ST r3,r0,@mth_trig_test_save_cos

  MOVI r1,0
  MOVHI r1,0xBF80
  CALL @mth_trig_sincos_f32
  CMP r1,r13
  JMP[NE] @mth_trig_test_fail
  ST r2,r0,@mth_trig_test_act_sin
  ST r3,r0,@mth_trig_test_act_cos
  LD r4,r0,@mth_trig_test_save_sin
  MOVI r5,0
  MOVHI r5,0x8000
  BOOL.6 r4,r4,r5            ; -sin(1)
  LD r1,r0,@mth_trig_test_act_sin
  ADD r2,r4,r0
  MOVI r3,0x37BD
  MOVHI r3,0x3586            ; 1e-6
  CALL @mth_trig_test_near
  CMP r1,r13
  JMP[NE] @mth_trig_test_fail
  LD r4,r0,@mth_trig_test_save_cos
  LD r1,r0,@mth_trig_test_act_cos
  ADD r2,r4,r0
  MOVI r3,0x37BD
  MOVHI r3,0x3586
  CALL @mth_trig_test_near
  CMP r1,r13
  JMP[NE] @mth_trig_test_fail

  ; ---- identity: sin^2(1)+cos^2(1) = 1 ----
  MOVI r1,0
  MOVHI r1,0x3F80
  CALL @mth_trig_sincos_f32
  CMP r1,r13
  JMP[NE] @mth_trig_test_fail
  ST r2,r0,@mth_trig_test_save_sin
  ST r3,r0,@mth_trig_test_save_cos
  LD r1,r0,@mth_trig_test_save_sin
  LD r2,r0,@mth_trig_test_save_cos
  FMUL r1,r1,r1
  FMUL r2,r2,r2
  FADD r1,r1,r2
  MOVI r2,0
  MOVHI r2,0x3F80            ; 1.0
  MOVI r3,0x37BD
  MOVHI r3,0x3686            ; 2e-6
  CALL @mth_trig_test_near
  CMP r1,r13
  JMP[NE] @mth_trig_test_fail

  ; ---- rejection: non-finite ----
  MOVI r1,0
  MOVHI r1,0x7F80             ; +inf
  CALL @mth_trig_sincos_f32
  CMP r1,r0
  JMP[NE] @mth_trig_test_fail
  MOVI r4,1
  CMP r9,r4
  JMP[NE] @mth_trig_test_fail

  MOVI r1,0
  MOVHI r1,0x7FC0             ; quiet NaN
  CALL @mth_trig_sincos_f32
  CMP r1,r0
  JMP[NE] @mth_trig_test_fail
  MOVI r4,1
  CMP r9,r4
  JMP[NE] @mth_trig_test_fail

  ; ---- rejection: domain ----
  MOVI r1,0
  MOVHI r1,0x4301             ; 129.0
  CALL @mth_trig_sincos_f32
  CMP r1,r0
  JMP[NE] @mth_trig_test_fail
  MOVI r4,2
  CMP r9,r4
  JMP[NE] @mth_trig_test_fail

  MOVI r1,@mth_trig_test_pass
  CALL @mth_trig_test_puts
  HALT

; r1=angle, r2=expected sin, r3=expected cos. Tolerance 2e-6.
mth_trig_test_case:
  ST r15,r0,@mth_trig_test_case_ret
  ST r2,r0,@mth_trig_test_exp_sin
  ST r3,r0,@mth_trig_test_exp_cos
  CALL @mth_trig_sincos_f32
  CMP r1,r13
  JMP[NE] @mth_trig_test_fail
  ST r2,r0,@mth_trig_test_act_sin
  ST r3,r0,@mth_trig_test_act_cos

  LD r1,r0,@mth_trig_test_act_sin
  LD r2,r0,@mth_trig_test_exp_sin
  MOVI r3,0x37BD
  MOVHI r3,0x3606             ; 2e-6
  CALL @mth_trig_test_near
  CMP r1,r13
  JMP[NE] @mth_trig_test_fail

  LD r1,r0,@mth_trig_test_act_cos
  LD r2,r0,@mth_trig_test_exp_cos
  MOVI r3,0x37BD
  MOVHI r3,0x3606
  CALL @mth_trig_test_near
  CMP r1,r13
  JMP[NE] @mth_trig_test_fail

  LD r15,r0,@mth_trig_test_case_ret
  RET

; Large-angle case uses a wider 8e-6 window because the binary32 reduction
; constant accumulates over q ~= 64.
mth_trig_test_large:
  ST r15,r0,@mth_trig_test_case_ret
  ST r2,r0,@mth_trig_test_exp_sin
  ST r3,r0,@mth_trig_test_exp_cos
  CALL @mth_trig_sincos_f32
  CMP r1,r13
  JMP[NE] @mth_trig_test_fail
  ST r2,r0,@mth_trig_test_act_sin
  ST r3,r0,@mth_trig_test_act_cos

  LD r1,r0,@mth_trig_test_act_sin
  LD r2,r0,@mth_trig_test_exp_sin
  MOVI r3,0x37BD
  MOVHI r3,0x3706             ; 8e-6
  CALL @mth_trig_test_near
  CMP r1,r13
  JMP[NE] @mth_trig_test_fail

  LD r1,r0,@mth_trig_test_act_cos
  LD r2,r0,@mth_trig_test_exp_cos
  MOVI r3,0x37BD
  MOVHI r3,0x3706
  CALL @mth_trig_test_near
  CMP r1,r13
  JMP[NE] @mth_trig_test_fail

  LD r15,r0,@mth_trig_test_case_ret
  RET

; |r1-r2| <= r3, all raw binary32 payloads.
mth_trig_test_near:
  MOVI r4,0
  MOVHI r4,0x7FFF             ; clear-sign mask
  FSUB r5,r1,r2
  BOOL.8 r5,r5,r4
  FCMP r5,r3
  JMP[GT] @mth_trig_test_near_fail
  MOVI r1,1
  RET
mth_trig_test_near_fail:
  MOVI r1,0
  RET

mth_trig_test_fail:
  MOVI r1,@mth_trig_test_bad
  CALL @mth_trig_test_puts
  HALT

mth_trig_test_puts:
  MOVI r4,255
mth_trig_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_trig_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_trig_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_trig_test_puts_word

mth_trig_test_pass:
.str "MTH TRIG SINCOS PASS\n"
mth_trig_test_bad:
.str "MTH TRIG SINCOS FAIL\n"

.org 4096
mth_trig_test_case_ret:
.word 0
mth_trig_test_exp_sin:
.word 0
mth_trig_test_exp_cos:
.word 0
mth_trig_test_act_sin:
.word 0
mth_trig_test_act_cos:
.word 0
mth_trig_test_save_sin:
.word 0
mth_trig_test_save_cos:
.word 0
