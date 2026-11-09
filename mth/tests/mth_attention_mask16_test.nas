; MTH 16-position attention mask fixture — NaN16 only.
;
; Checks full mask, low causal prefix, high single bit, exact aliasing, empty
; mask rejection, non-finite score rejection, output atomicity, and recovery.

.org 0
JMP @mth_mask_test_main
.include "../nan16/mth_attention_mask16_f32.nas"

mth_mask_test_main:
  MOVI r0,0
  MOVI r13,1
  CALL @mth_mask_test_init

  ; full mask: out == scores
  MOVI r1,@mth_mask_test_scores
  MOVI r2,0xFFFF
  MOVI r3,@mth_mask_test_out
  CALL @mth_attention_mask16_f32
  CMP r1,r13
  JMP[NE] @mth_mask_test_fail
  MOVI r6,0
mth_mask_test_full:
  MOVI r8,@mth_mask_test_scores
  ADD r8,r8,r6
  LD r1,r8,0
  MOVI r8,@mth_mask_test_out
  ADD r8,r8,r6
  LD r2,r8,0
  CMP r1,r2
  JMP[NE] @mth_mask_test_fail
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_mask_test_full

  ; low four allowed
  MOVI r2,0x000F
  MOVI r3,@mth_mask_test_out
  MOVI r1,@mth_mask_test_scores
  CALL @mth_attention_mask16_f32
  CMP r1,r13
  JMP[NE] @mth_mask_test_fail
  MOVI r6,0
mth_mask_test_low:
  MOVI r8,@mth_mask_test_scores
  ADD r8,r8,r6
  LD r1,r8,0
  MOVI r8,@mth_mask_test_out
  ADD r8,r8,r6
  LD r2,r8,0
  CMP r1,r2
  JMP[NE] @mth_mask_test_fail
  ADDI r6,r6,1
  MOVI r8,4
  CMP r6,r8
  JMP[LT] @mth_mask_test_low
  MOVI r7,0
  MOVHI r7,0xFF80
mth_mask_test_low_blocked:
  MOVI r8,@mth_mask_test_out
  ADD r8,r8,r6
  LD r1,r8,0
  CMP r1,r7
  JMP[NE] @mth_mask_test_fail
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_mask_test_low_blocked

  ; single high bit
  MOVI r2,0x8000
  MOVI r1,@mth_mask_test_scores
  MOVI r3,@mth_mask_test_out
  CALL @mth_attention_mask16_f32
  CMP r1,r13
  JMP[NE] @mth_mask_test_fail
  MOVI r7,0
  MOVHI r7,0xFF80
  MOVI r6,0
mth_mask_test_high:
  MOVI r8,@mth_mask_test_out
  ADD r8,r8,r6
  LD r1,r8,0
  MOVI r9,15
  CMP r6,r9
  JMP[EQ] @mth_mask_test_high_allowed
  CMP r1,r7
  JMP[NE] @mth_mask_test_fail
  JMP @mth_mask_test_high_next
mth_mask_test_high_allowed:
  MOVI r8,@mth_mask_test_scores
  ADDI r8,r8,15
  LD r2,r8,0
  CMP r1,r2
  JMP[NE] @mth_mask_test_fail
mth_mask_test_high_next:
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_mask_test_high

  ; exact aliasing: out == scores
  CALL @mth_mask_test_init
  MOVI r1,@mth_mask_test_scores
  MOVI r2,0x000F
  ADD r3,r1,r0
  CALL @mth_attention_mask16_f32
  CMP r1,r13
  JMP[NE] @mth_mask_test_fail
  MOVI r6,4
  MOVI r7,0
  MOVHI r7,0xFF80
mth_mask_test_alias:
  MOVI r8,@mth_mask_test_scores
  ADD r8,r8,r6
  LD r1,r8,0
  CMP r1,r7
  JMP[NE] @mth_mask_test_fail
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_mask_test_alias

  ; zero mask rejects
  CALL @mth_mask_test_sentinel
  MOVI r1,@mth_mask_test_scores
  MOVI r2,0
  MOVI r3,@mth_mask_test_out
  CALL @mth_attention_mask16_f32
  CMP r1,r0
  JMP[NE] @mth_mask_test_fail
  MOVI r8,2
  CMP r9,r8
  JMP[NE] @mth_mask_test_fail
  CALL @mth_mask_test_check_sentinel

  ; NaN score rejects
  CALL @mth_mask_test_init
  CALL @mth_mask_test_sentinel
  MOVI r1,0
  MOVHI r1,0x7FC0
  ST r1,r0,@mth_mask_test_scores
  MOVI r1,@mth_mask_test_scores
  MOVI r2,0xFFFF
  MOVI r3,@mth_mask_test_out
  CALL @mth_attention_mask16_f32
  CMP r1,r0
  JMP[NE] @mth_mask_test_fail
  MOVI r8,1
  CMP r9,r8
  JMP[NE] @mth_mask_test_fail
  CALL @mth_mask_test_check_sentinel

  ; recovery
  CALL @mth_mask_test_init
  MOVI r1,@mth_mask_test_scores
  MOVI r2,0xFFFF
  MOVI r3,@mth_mask_test_out
  CALL @mth_attention_mask16_f32
  CMP r1,r13
  JMP[NE] @mth_mask_test_fail

  MOVI r1,@mth_mask_test_pass
  CALL @mth_mask_test_puts
  HALT

mth_mask_test_init:
  MOVI r6,0
mth_mask_test_init_loop:
  MOVI r1,0
  MOVHI r1,0x3F80
  ADD r1,r1,r6
  MOVI r8,@mth_mask_test_scores
  ADD r8,r8,r6
  ST r1,r8,0
  MOVI r8,@mth_mask_test_out
  ADD r8,r8,r6
  ST r0,r8,0
  ADDI r6,r6,1
  MOVI r8,16
  CMP r6,r8
  JMP[LT] @mth_mask_test_init_loop
  RET

mth_mask_test_sentinel:
  MOVI r1,0xBEEF
  MOVHI r1,0xDEAD
  ST r1,r0,@mth_mask_test_out
  RET

mth_mask_test_check_sentinel:
  LD r1,r0,@mth_mask_test_out
  MOVI r2,0xBEEF
  MOVHI r2,0xDEAD
  CMP r1,r2
  JMP[NE] @mth_mask_test_fail
  RET

mth_mask_test_fail:
  MOVI r1,@mth_mask_test_bad
  CALL @mth_mask_test_puts
  HALT

mth_mask_test_puts:
  MOVI r4,255
mth_mask_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_mask_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_mask_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_mask_test_puts_word

mth_mask_test_pass:
.str "MTH ATTENTION MASK16 PASS\n"
mth_mask_test_bad:
.str "MTH ATTENTION MASK16 FAIL\n"

.org 4096
mth_mask_test_scores:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_mask_test_out:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
