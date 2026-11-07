.org 0
JMP @mth_pf_test_main
.include "../nan16/mth_preflight.nas"

mth_pf_test_main:
  MOVI r13,1
  MOVI r12,@mth_pf_scratch

  ; Valid VECTOR[3] dot VECTOR[3] -> SCALAR.
  MOVI r1,@mth_pf_left
  MOVI r2,@mth_pf_right
  MOVI r3,@mth_pf_dot_contract
  MOVI r4,1
  MOVI r5,@mth_pf_output
  CALL @mth_preflight
  CMP r1,r0
  JMP[NE] @mth_pf_fail
  LD r6,r5,0
  MOVI r7,3
  CMP r6,r7
  JMP[NE] @mth_pf_fail
  LD r6,r5,1
  CMP r6,r0
  JMP[NE] @mth_pf_fail
  LD r6,r5,4
  MOVI r7,1
  CMP r6,r7
  JMP[NE] @mth_pf_fail
  LD r6,r5,5
  MOVI r7,@mth_pf_output_payload
  CMP r6,r7
  JMP[NE] @mth_pf_fail

  ; Dimension mismatch must reject and leave output metadata untouched.
  MOVI r6,@mth_pf_right
  MOVI r7,2
  ST r7,r6,2
  MOVI r6,@mth_pf_output
  MOVI r7,99
  ST r7,r6,0
  ST r7,r6,1
  MOVI r1,@mth_pf_left
  MOVI r2,@mth_pf_right
  MOVI r3,@mth_pf_dot_contract
  MOVI r4,1
  MOVI r5,@mth_pf_output
  CALL @mth_preflight
  MOVI r7,6
  CMP r1,r7
  JMP[NE] @mth_pf_fail
  LD r6,r5,0
  MOVI r7,99
  CMP r6,r7
  JMP[NE] @mth_pf_fail

  ; Restore shape. A missing capability is not a mathematical null.
  MOVI r6,@mth_pf_right
  MOVI r7,3
  ST r7,r6,2
  MOVI r1,@mth_pf_left
  MOVI r2,@mth_pf_right
  MOVI r3,@mth_pf_dot_contract
  MOVI r4,0
  MOVI r5,@mth_pf_output
  CALL @mth_preflight
  MOVI r7,7
  CMP r1,r7
  JMP[NE] @mth_pf_fail

  ; A zero divisor fails a declared precondition before output publication.
  MOVI r6,@mth_pf_scalar_right
  ST r0,r6,0
  MOVI r6,@mth_pf_scalar_output
  MOVI r7,55
  ST r7,r6,0
  MOVI r1,@mth_pf_scalar_left
  MOVI r2,@mth_pf_scalar_right
  MOVI r3,@mth_pf_scalar_contract
  MOVI r4,1
  MOVI r5,@mth_pf_scalar_output
  CALL @mth_preflight
  MOVI r7,8
  CMP r1,r7
  JMP[NE] @mth_pf_fail
  LD r6,r5,0
  MOVI r7,55
  CMP r6,r7
  JMP[NE] @mth_pf_fail

  ; A nonzero divisor passes the same contract and publishes scalar metadata.
  MOVI r6,@mth_pf_scalar_right
  MOVI r7,5
  ST r7,r6,0
  MOVI r1,@mth_pf_scalar_left
  MOVI r2,@mth_pf_scalar_right
  MOVI r3,@mth_pf_scalar_contract
  MOVI r4,1
  MOVI r5,@mth_pf_scalar_output
  CALL @mth_preflight
  CMP r1,r0
  JMP[NE] @mth_pf_fail
  LD r6,r5,0
  MOVI r7,3
  CMP r6,r7
  JMP[NE] @mth_pf_fail

  ; Output capacity is a separate rejection and remains atomic.
  MOVI r6,@mth_pf_output
  MOVI r7,0
  ST r7,r6,6
  MOVI r1,@mth_pf_left
  MOVI r2,@mth_pf_right
  MOVI r3,@mth_pf_dot_contract
  MOVI r4,1
  MOVI r5,@mth_pf_output
  CALL @mth_preflight
  MOVI r7,9
  CMP r1,r7
  JMP[NE] @mth_pf_fail

  MOVI r1,@mth_pf_pass
  CALL @mth_pf_puts
  HALT

mth_pf_fail:
  MOVI r1,@mth_pf_bad
  CALL @mth_pf_puts
  HALT

mth_pf_puts:
  MOVI r4,255
mth_pf_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_pf_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_pf_puts_byte
  ADD r1,r1,r13
  JMP @mth_pf_puts_word

.org 256
mth_pf_left:
.word 4,1,3,1,1,@mth_pf_left_payload,3,1
mth_pf_right:
.word 4,1,3,1,1,@mth_pf_right_payload,3,1
mth_pf_dot_contract:
.word 4,4,3,1,1,0,1,1,1,0
mth_pf_output:
.word 0,0,0,0,0,@mth_pf_output_payload,1,0
mth_pf_scalar_left:
.word 3,0,1,1,1,@mth_pf_scalar_left_payload,1,1
mth_pf_scalar_right:
.word 3,0,1,1,1,@mth_pf_scalar_right_payload,1,1
mth_pf_scalar_contract:
.word 3,3,3,0,0,0,1,4,1,1
mth_pf_scalar_output:
.word 0,0,0,0,0,@mth_pf_scalar_output_payload,1,0

.org 512
mth_pf_left_payload:
.word 1,2,3
mth_pf_right_payload:
.word 4,5,6
mth_pf_output_payload:
.word 0
mth_pf_scalar_left_payload:
.word 9
mth_pf_scalar_right_payload:
.word 0
mth_pf_scalar_output_payload:
.word 0
mth_pf_scratch:
\n.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
mth_pf_pass:
.str "MTH TYPED PREFLIGHT PASS\n"
mth_pf_bad:
.str "MTH TYPED PREFLIGHT FAIL\n"
