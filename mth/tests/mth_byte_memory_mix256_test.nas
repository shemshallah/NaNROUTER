; MTH byte memory interpolation fixture — NaN16 only.
;
; Checks midpoint, weight 0, weight 1, invalid weights, non-finite base/memory,
; output atomicity, and recovery.

.org 0
JMP @mth_mix_test_main
.include "../nan16/mth_byte_memory_mix256_f32.nas"

mth_mix_test_main:
  MOVI r0,0
  MOVI r13,1
  CALL @mth_mix_test_init

  ; 0.5*(0.2)+0.5*(0.8)=0.5
  MOVI r3,0
  MOVHI r3,0x3F00
  CALL @mth_mix_test_run
  MOVI r1,@mth_mix_test_out
  LD r1,r1,0
  MOVI r2,0
  MOVHI r2,0x3F00
  MOVI r3,0
  MOVHI r3,0x3586
  CALL @mth_mix_test_near
  CMP r1,r13
  JMP[NE] @mth_mix_test_fail

  ; weight 0 -> base 0.2
  MOVI r3,0
  CALL @mth_mix_test_run
  MOVI r1,@mth_mix_test_out
  LD r1,r1,0
  MOVI r2,0xCCCD
  MOVHI r2,0x3E4C            ; 0.2
  MOVI r3,0
  MOVHI r3,0x3586
  CALL @mth_mix_test_near
  CMP r1,r13
  JMP[NE] @mth_mix_test_fail

  ; weight 1 -> memory 0.8
  MOVI r3,0
  MOVHI r3,0x3F80
  CALL @mth_mix_test_run
  MOVI r1,@mth_mix_test_out
  LD r1,r1,0
  MOVI r2,0xCCCD
  MOVHI r2,0x3F4C            ; 0.8
  MOVI r3,0
  MOVHI r3,0x3586
  CALL @mth_mix_test_near
  CMP r1,r13
  JMP[NE] @mth_mix_test_fail

  ; invalid weights
  CALL @mth_mix_test_sentinel
  MOVI r3,0
  MOVHI r3,0xBF80
  CALL @mth_mix_test_call
  CMP r1,r0
  JMP[NE] @mth_mix_test_fail
  MOVI r8,1
  CMP r9,r8
  JMP[NE] @mth_mix_test_fail
  CALL @mth_mix_test_check_sentinel

  CALL @mth_mix_test_sentinel
  MOVI r3,0
  MOVHI r3,0x3F8C            ; 1.1
  CALL @mth_mix_test_call
  CMP r1,r0
  JMP[NE] @mth_mix_test_fail
  MOVI r8,1
  CMP r9,r8
  JMP[NE] @mth_mix_test_fail
  CALL @mth_mix_test_check_sentinel

  ; base NaN cause 2
  CALL @mth_mix_test_init
  CALL @mth_mix_test_sentinel
  MOVI r1,0
  MOVHI r1,0x7FC0
  ST r1,r0,@mth_mix_test_base
  MOVI r3,0
  MOVHI r3,0x3F00
  CALL @mth_mix_test_call
  CMP r1,r0
  JMP[NE] @mth_mix_test_fail
  MOVI r8,2
  CMP r9,r8
  JMP[NE] @mth_mix_test_fail
  CALL @mth_mix_test_check_sentinel

  ; memory NaN cause 3
  CALL @mth_mix_test_init
  CALL @mth_mix_test_sentinel
  MOVI r1,0
  MOVHI r1,0x7FC0
  ST r1,r0,@mth_mix_test_mem
  MOVI r3,0
  MOVHI r3,0x3F00
  CALL @mth_mix_test_call
  CMP r1,r0
  JMP[NE] @mth_mix_test_fail
  MOVI r8,3
  CMP r9,r8
  JMP[NE] @mth_mix_test_fail
  CALL @mth_mix_test_check_sentinel

  ; recovery
  CALL @mth_mix_test_init
  MOVI r3,0
  MOVHI r3,0x3F00
  CALL @mth_mix_test_run
  MOVI r1,@mth_mix_test_out
  LD r1,r1,0
  MOVI r2,0
  MOVHI r2,0x3F00
  MOVI r3,0
  MOVHI r3,0x3586
  CALL @mth_mix_test_near
  CMP r1,r13
  JMP[NE] @mth_mix_test_fail

  MOVI r1,@mth_mix_test_pass
  CALL @mth_mix_test_puts
  HALT

mth_mix_test_init:
  MOVI r6,0
mth_mix_test_init_loop:
  MOVI r1,0xCCCD
  MOVHI r1,0x3E4C            ; 0.2
  MOVI r8,@mth_mix_test_base
  ADD r8,r8,r6
  ST r1,r8,0
  MOVI r1,0xCCCD
  MOVHI r1,0x3F4C            ; 0.8
  MOVI r8,@mth_mix_test_mem
  ADD r8,r8,r6
  ST r1,r8,0
  MOVI r8,@mth_mix_test_out
  ADD r8,r8,r6
  ST r0,r8,0
  ADDI r6,r6,1
  MOVI r8,256
  CMP r6,r8
  JMP[LT] @mth_mix_test_init_loop
  RET

mth_mix_test_call:
  ST r15,r0,@mth_mix_test_call_ret
  MOVI r1,@mth_mix_test_base
  MOVI r2,@mth_mix_test_mem
  MOVI r4,@mth_mix_test_out
  CALL @mth_byte_memory_mix256_f32
  LD r15,r0,@mth_mix_test_call_ret
  RET

mth_mix_test_run:
  ST r15,r0,@mth_mix_test_run_ret
  CALL @mth_mix_test_call
  CMP r1,r13
  JMP[NE] @mth_mix_test_fail
  CMP r9,r0
  JMP[NE] @mth_mix_test_fail
  LD r15,r0,@mth_mix_test_run_ret
  RET

mth_mix_test_sentinel:
  MOVI r1,0xBEEF
  MOVHI r1,0xDEAD
  ST r1,r0,@mth_mix_test_out
  RET

mth_mix_test_check_sentinel:
  LD r1,r0,@mth_mix_test_out
  MOVI r2,0xBEEF
  MOVHI r2,0xDEAD
  CMP r1,r2
  JMP[NE] @mth_mix_test_fail
  RET

mth_mix_test_near:
  MOVI r4,0
  MOVHI r4,0x7FFF
  FSUB r5,r1,r2
  BOOL.8 r5,r5,r4
  FCMP r5,r3
  JMP[GT] @mth_mix_test_near_fail
  MOVI r1,1
  RET
mth_mix_test_near_fail:
  MOVI r1,0
  RET

mth_mix_test_fail:
  MOVI r1,@mth_mix_test_bad
  CALL @mth_mix_test_puts
  HALT

mth_mix_test_puts:
  MOVI r4,255
mth_mix_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_mix_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_mix_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_mix_test_puts_word

mth_mix_test_pass:
.str "MTH BYTE MEMORY MIX PASS\n"
mth_mix_test_bad:
.str "MTH BYTE MEMORY MIX FAIL\n"

.org 4096
mth_mix_test_call_ret:
.word 0
mth_mix_test_run_ret:
.word 0
mth_mix_test_base:
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
mth_mix_test_mem:
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
mth_mix_test_out:
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
