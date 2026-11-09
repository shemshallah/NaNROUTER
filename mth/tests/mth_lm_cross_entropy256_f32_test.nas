; MTH 256-way cross-entropy fixture — NaN16 only.
;
; Checks uniform loss, two-support target loss, target bounds, NaN/empty
; rejection, output atomicity, and recovery.

.org 0
JMP @mth_ce_test_main
.include "../nan16/mth_lm_cross_entropy256_f32.nas"

mth_ce_test_main:
  MOVI r0,0
  MOVI r13,1
  CALL @mth_ce_test_init

  ; Uniform logits, target 0 -> ln(256).
  MOVI r1,0
  CALL @mth_ce_test_fill_x
  MOVI r2,0
  CALL @mth_ce_test_run
  LD r1,r0,@mth_ce_test_out
  MOVI r2,0x7218
  MOVHI r2,0x40B1            ; 5.545177
  MOVI r3,0
  MOVHI r3,0x38D1            ; 1e-4
  CALL @mth_ce_test_near
  CMP r1,r13
  JMP[NE] @mth_ce_test_fail

  ; x0=1,x1=2, rest -inf.
  MOVI r1,0
  MOVHI r1,0xFF80
  CALL @mth_ce_test_fill_x
  MOVI r1,0
  MOVHI r1,0x3F80
  ST r1,r0,@mth_ce_test_x
  MOVI r1,0
  MOVHI r1,0x4000
  MOVI r8,@mth_ce_test_x
  ADDI r8,r8,1
  ST r1,r8,0

  ; target 1 -> 2+ln(1+e^-1)-2 = ln(1+e^-1).
  MOVI r2,1
  CALL @mth_ce_test_run
  LD r1,r0,@mth_ce_test_out
  MOVI r2,0x63D6
  MOVHI r2,0x3EA0            ; 0.3132617
  MOVI r3,0
  MOVHI r3,0x38D1
  CALL @mth_ce_test_near
  CMP r1,r13
  JMP[NE] @mth_ce_test_fail

  ; target 0 -> 1+ln(1+e^-1).
  MOVI r2,0
  CALL @mth_ce_test_run
  LD r1,r0,@mth_ce_test_out
  MOVI r2,0x18F5
  MOVHI r2,0x3FA8            ; 1.3132617
  MOVI r3,0
  MOVHI r3,0x38D1
  CALL @mth_ce_test_near
  CMP r1,r13
  JMP[NE] @mth_ce_test_fail

  ; Target 256 rejects.
  MOVI r1,0xBEEF
  MOVHI r1,0xDEAD
  ST r1,r0,@mth_ce_test_out
  MOVI r2,256
  CALL @mth_ce_test_call
  CMP r1,r0
  JMP[NE] @mth_ce_test_fail
  MOVI r8,3
  CMP r9,r8
  JMP[NE] @mth_ce_test_fail
  LD r1,r0,@mth_ce_test_out
  MOVI r2,0xBEEF
  MOVHI r2,0xDEAD
  CMP r1,r2
  JMP[NE] @mth_ce_test_fail

  ; NaN logits reject with cause 1.
  MOVI r1,0
  MOVHI r1,0x7FC0
  ST r1,r0,@mth_ce_test_x
  MOVI r2,0
  CALL @mth_ce_test_call
  CMP r1,r0
  JMP[NE] @mth_ce_test_fail
  MOVI r8,1
  CMP r9,r8
  JMP[NE] @mth_ce_test_fail

  ; All -inf rejects with cause 2.
  MOVI r1,0
  MOVHI r1,0xFF80
  CALL @mth_ce_test_fill_x
  MOVI r2,0
  CALL @mth_ce_test_call
  CMP r1,r0
  JMP[NE] @mth_ce_test_fail
  MOVI r8,2
  CMP r9,r8
  JMP[NE] @mth_ce_test_fail

  ; Recovery.
  MOVI r1,0
  CALL @mth_ce_test_fill_x
  MOVI r2,0
  CALL @mth_ce_test_run
  LD r1,r0,@mth_ce_test_out
  MOVI r2,0x7218
  MOVHI r2,0x40B1
  MOVI r3,0
  MOVHI r3,0x38D1
  CALL @mth_ce_test_near
  CMP r1,r13
  JMP[NE] @mth_ce_test_fail

  MOVI r1,@mth_ce_test_pass
  CALL @mth_ce_test_puts
  HALT

mth_ce_test_init:
  MOVI r6,0
mth_ce_test_init_loop:
  MOVI r8,@mth_ce_test_x
  ADD r8,r8,r6
  ST r0,r8,0
  ADDI r6,r6,1
  MOVI r8,256
  CMP r6,r8
  JMP[LT] @mth_ce_test_init_loop
  ST r0,r0,@mth_ce_test_out
  RET

; r1 = fill value for all 256 logits
mth_ce_test_fill_x:
  MOVI r6,0
mth_ce_test_fill_loop:
  MOVI r8,@mth_ce_test_x
  ADD r8,r8,r6
  ST r1,r8,0
  ADDI r6,r6,1
  MOVI r8,256
  CMP r6,r8
  JMP[LT] @mth_ce_test_fill_loop
  RET

mth_ce_test_call:
  ST r15,r0,@mth_ce_test_call_ret
  MOVI r1,@mth_ce_test_x
  MOVI r3,@mth_ce_test_out
  MOVI r4,@mth_ce_test_scratch
  CALL @mth_lm_cross_entropy256_f32
  LD r15,r0,@mth_ce_test_call_ret
  RET

mth_ce_test_run:
  ST r15,r0,@mth_ce_test_run_ret
  CALL @mth_ce_test_call
  CMP r1,r13
  JMP[NE] @mth_ce_test_fail
  CMP r9,r0
  JMP[NE] @mth_ce_test_fail
  LD r15,r0,@mth_ce_test_run_ret
  RET

mth_ce_test_near:
  MOVI r4,0
  MOVHI r4,0x7FFF
  FSUB r5,r1,r2
  BOOL.8 r5,r5,r4
  FCMP r5,r3
  JMP[GT] @mth_ce_test_near_fail
  MOVI r1,1
  RET
mth_ce_test_near_fail:
  MOVI r1,0
  RET

mth_ce_test_fail:
  MOVI r1,@mth_ce_test_bad
  CALL @mth_ce_test_puts
  HALT

mth_ce_test_puts:
  MOVI r4,255
mth_ce_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_ce_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_ce_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_ce_test_puts_word

mth_ce_test_pass:
.str "MTH CROSS ENTROPY256 PASS\n"
mth_ce_test_bad:
.str "MTH CROSS ENTROPY256 FAIL\n"

.org 4096
mth_ce_test_x:
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
mth_ce_test_out:
.word 0
mth_ce_test_scratch:
.word 0,0,0,0,0
mth_ce_test_call_ret:
.word 0
mth_ce_test_run_ret:
.word 0
