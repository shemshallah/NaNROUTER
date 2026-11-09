; MTH 16-candidate attention/value mix fixture — NaN16 only.
;
; Rows 0, 1, 2 hold constant values 2.0, 4.0, 8.0. Tests one-hot selection,
; uniform mixing, weighted mixing, zero weights, output atomicity, and
; rejection of negative or non-finite weights and non-finite values.

.org 0
JMP @mth_attention_test_main
.include "../nan16/mth_attention_mix16_f32.nas"

mth_attention_test_main:
  MOVI r0,0
  MOVI r13,1
  CALL @mth_attention_test_init

  ; One-hot row 2 -> 8.0 on every channel.
  CALL @mth_attention_test_zero_weights
  MOVI r8,@mth_attention_test_weights
  ADDI r8,r8,2
  MOVI r9,0
  MOVHI r9,0x3F80            ; 1.0
  ST r9,r8,0
  MOVI r1,0
  MOVHI r1,0x4100            ; 8.0
  CALL @mth_attention_test_expect

  ; 0.5*row0 + 0.5*row1 -> 3.0.
  CALL @mth_attention_test_zero_weights
  MOVI r1,0
  MOVHI r1,0x3F00            ; 0.5
  MOVI r8,@mth_attention_test_weights
  ST r1,r8,0
  ADDI r8,r8,1
  ST r1,r8,0
  MOVI r1,0
  MOVHI r1,0x4040            ; 3.0
  CALL @mth_attention_test_expect

  ; 0.75*row0 + 0.25*row2 -> 3.5.
  CALL @mth_attention_test_zero_weights
  MOVI r1,0
  MOVHI r1,0x3F40            ; 0.75
  MOVI r8,@mth_attention_test_weights
  ST r1,r8,0
  MOVI r1,0
  MOVHI r1,0x3E80            ; 0.25
  ADDI r8,r8,2
  ST r1,r8,0
  MOVI r1,0
  MOVHI r1,0x4060            ; 3.5
  CALL @mth_attention_test_expect

  ; All-zero weights -> 0.
  CALL @mth_attention_test_zero_weights
  MOVI r1,0
  CALL @mth_attention_test_expect

  ; Negative weight rejects and leaves output sentinel untouched.
  CALL @mth_attention_test_zero_weights
  MOVI r1,0
  MOVHI r1,0xBF80            ; -1.0
  MOVI r8,@mth_attention_test_weights
  ST r1,r8,0
  MOVI r1,0xBEEF
  MOVHI r1,0xDEAD
  ST r1,r0,@mth_attention_test_out
  CALL @mth_attention_test_call
  CMP r1,r0
  JMP[NE] @mth_attention_test_fail
  MOVI r8,2
  CMP r9,r8
  JMP[NE] @mth_attention_test_fail
  LD r8,r0,@mth_attention_test_out
  MOVI r9,0xBEEF
  MOVHI r9,0xDEAD
  CMP r8,r9
  JMP[NE] @mth_attention_test_fail

  ; NaN weight rejects with cause 1.
  CALL @mth_attention_test_zero_weights
  MOVI r1,0
  MOVHI r1,0x7FC0
  MOVI r8,@mth_attention_test_weights
  ST r1,r8,0
  CALL @mth_attention_test_call
  CMP r1,r0
  JMP[NE] @mth_attention_test_fail
  MOVI r8,1
  CMP r9,r8
  JMP[NE] @mth_attention_test_fail

  ; Non-finite value rejects with cause 3.
  CALL @mth_attention_test_zero_weights
  MOVI r1,0
  MOVHI r1,0x7F80            ; +inf value
  MOVI r8,@mth_attention_test_values
  ST r1,r8,0
  CALL @mth_attention_test_call
  CMP r1,r0
  JMP[NE] @mth_attention_test_fail
  MOVI r8,3
  CMP r9,r8
  JMP[NE] @mth_attention_test_fail

  ; Restore row0 and recover.
  MOVI r1,0
  MOVHI r1,0x4000            ; 2.0
  MOVI r8,@mth_attention_test_values
  ST r1,r8,0
  CALL @mth_attention_test_zero_weights
  MOVI r8,@mth_attention_test_weights
  MOVI r9,0
  MOVHI r9,0x3F80            ; 1.0
  ST r9,r8,0
  MOVI r1,0
  MOVHI r1,0x4000            ; 2.0
  CALL @mth_attention_test_expect

  MOVI r1,@mth_attention_test_pass
  CALL @mth_attention_test_puts
  HALT

mth_attention_test_init:
  ST r15,r0,@mth_attention_test_init_ret
  ; Zero 16 weights and 256 values.
  MOVI r6,0
mth_attention_test_zero_w:
  MOVI r8,@mth_attention_test_weights
  ADD r8,r8,r6
  ST r0,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_attention_test_zero_w
  MOVI r6,0
mth_attention_test_zero_v:
  MOVI r8,@mth_attention_test_values
  ADD r8,r8,r6
  ST r0,r8,0
  ADDI r6,r6,1
  MOVI r8,256
  CMP r6,r8
  JMP[LT] @mth_attention_test_zero_v

  ; Row 0 = 2.0, row 1 = 4.0, row 2 = 8.0.
  MOVI r6,0
  MOVI r7,0
  MOVHI r7,0x4000
mth_attention_test_row0:
  MOVI r8,@mth_attention_test_values
  ADD r8,r8,r6
  ST r7,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_attention_test_row0
  MOVI r7,0
  MOVHI r7,0x4080            ; 4.0
mth_attention_test_row1:
  MOVI r8,@mth_attention_test_values
  ADD r8,r8,r6
  ST r7,r8,0
  ADDI r6,r6,1
  MOVI r8,32
  CMP r6,r8
  JMP[LT] @mth_attention_test_row1
  MOVI r7,0
  MOVHI r7,0x4100            ; 8.0
mth_attention_test_row2:
  MOVI r8,@mth_attention_test_values
  ADD r8,r8,r6
  ST r7,r8,0
  ADDI r6,r6,1
  MOVI r8,48
  CMP r6,r8
  JMP[LT] @mth_attention_test_row2

  LD r15,r0,@mth_attention_test_init_ret
  RET

mth_attention_test_zero_weights:
  MOVI r6,0
mth_attention_test_zw_loop:
  MOVI r8,@mth_attention_test_weights
  ADD r8,r8,r6
  ST r0,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_attention_test_zw_loop
  RET

mth_attention_test_call:
  ST r15,r0,@mth_attention_test_call_ret
  MOVI r1,@mth_attention_test_weights
  MOVI r2,@mth_attention_test_values
  MOVI r3,@mth_attention_test_out
  CALL @mth_attention_mix16_f32
  LD r15,r0,@mth_attention_test_call_ret
  RET

; r1 = expected scalar on every output channel.
mth_attention_test_expect:
  ST r15,r0,@mth_attention_test_expect_ret
  ST r1,r0,@mth_attention_test_exp
  CALL @mth_attention_test_call
  CMP r1,r13
  JMP[NE] @mth_attention_test_fail
  CMP r9,r0
  JMP[NE] @mth_attention_test_fail
  MOVI r6,0
mth_attention_test_expect_loop:
  ADD r7,r6,r0
  ST r6,r0,@mth_attention_test_index
  ADD r1,r0,r6
  ; load output[c]
  MOVI r8,@mth_attention_test_out
  ADD r8,r8,r1
  LD r1,r8,0
  LD r2,r0,@mth_attention_test_exp
  MOVI r3,0
  MOVHI r3,0x3586            ; 1e-6
  CALL @mth_attention_test_near
  CMP r1,r13
  JMP[NE] @mth_attention_test_fail
  LD r6,r0,@mth_attention_test_index
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_attention_test_expect_loop
  LD r15,r0,@mth_attention_test_expect_ret
  RET

; |r1-r2| <= r3, preserving r6-r15.
mth_attention_test_near:
  MOVI r4,0
  MOVHI r4,0x7FFF
  FSUB r5,r1,r2
  BOOL.8 r5,r5,r4
  FCMP r5,r3
  JMP[GT] @mth_attention_test_near_fail
  MOVI r1,1
  RET
mth_attention_test_near_fail:
  MOVI r1,0
  RET

mth_attention_test_fail:
  MOVI r1,@mth_attention_test_bad
  CALL @mth_attention_test_puts
  HALT

mth_attention_test_puts:
  MOVI r4,255
mth_attention_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_attention_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_attention_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_attention_test_puts_word

mth_attention_test_pass:
.str "MTH ATTENTION MIX16 PASS\n"
mth_attention_test_bad:
.str "MTH ATTENTION MIX16 FAIL\n"

.org 4096
mth_attention_test_init_ret:
.word 0
mth_attention_test_call_ret:
.word 0
mth_attention_test_expect_ret:
.word 0
mth_attention_test_exp:
.word 0
mth_attention_test_index:
.word 0
mth_attention_test_weights:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_attention_test_out:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_attention_test_values:
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
