; MTH bounded sequence transition fixture — NaN16 only.
;
; In-guest checks, no host arithmetic:
;   1. the canonical initial state (q=0, t=0, n=0);
;   2. a normal transition with nonzero state, token, and step;
;   3. the inclusive maximum state/step boundary, then rejection of state 16,
;      state 0xFFFFFFFF, step 1,048,576, and step 0xFFFFFFFF with the canonical
;      0xFFFFFFFF closed marker and no committed transition;
;   4. a five-step chained known-answer sequence run twice, with every step
;      compared to fixed expected states/tokens and the two final results
;      compared for repeatability.
;
; All arithmetic and comparisons are native NaN16 integer instructions.

.org 0
JMP @mth_sequence_test_main
.include "../nan16/mth_sequence_step_u32.nas"

mth_sequence_test_main:
  MOVI r13,1

  ; ---- Case 1: canonical initial state ----
  MOVI r1,0
  MOVI r2,0
  MOVI r3,0
  MOVI r4,@mth_sequence_test_initial_state
  MOVI r5,@mth_sequence_test_initial_token
  CALL @mth_sequence_step_u32
  CMP r1,r13
  JMP[NE] @mth_sequence_test_fail_1

  MOVI r1,@mth_sequence_test_initial_state
  LD r6,r1,0
  MOVI r7,1
  CMP r6,r7
  JMP[NE] @mth_sequence_test_fail_1
  MOVI r1,@mth_sequence_test_initial_token
  LD r6,r1,0
  MOVI r7,0x0100
  CMP r6,r7
  JMP[NE] @mth_sequence_test_fail_1

  MOVI r1,@mth_sequence_test_initial_state
  CALL @mth_sequence_test_check_class
  CMP r1,r13
  JMP[NE] @mth_sequence_test_fail_1
  MOVI r1,@mth_sequence_test_initial_token
  CALL @mth_sequence_test_check_class
  CMP r1,r13
  JMP[NE] @mth_sequence_test_fail_1

  ; ---- Case 2: normal transition ----
  ; q=3, t=0x12345678, n=5 -> q'=4, m=0x1234524D.
  MOVI r1,3
  MOVI r2,0x5678
  MOVHI r2,0x1234
  MOVI r3,5
  MOVI r4,@mth_sequence_test_normal_state
  MOVI r5,@mth_sequence_test_normal_token
  CALL @mth_sequence_step_u32
  CMP r1,r13
  JMP[NE] @mth_sequence_test_fail_2

  MOVI r1,@mth_sequence_test_normal_state
  LD r6,r1,0
  MOVI r7,4
  CMP r6,r7
  JMP[NE] @mth_sequence_test_fail_2
  MOVI r1,@mth_sequence_test_normal_token
  LD r6,r1,0
  MOVI r7,0x524D
  MOVHI r7,0x1234
  CMP r6,r7
  JMP[NE] @mth_sequence_test_fail_2

  MOVI r1,@mth_sequence_test_normal_state
  CALL @mth_sequence_test_check_class
  CMP r1,r13
  JMP[NE] @mth_sequence_test_fail_2
  MOVI r1,@mth_sequence_test_normal_token
  CALL @mth_sequence_test_check_class
  CMP r1,r13
  JMP[NE] @mth_sequence_test_fail_2

  ; ---- Case 3: boundaries ----
  ; Maximum valid q=15 and n=0x000FFFFF are inclusive and must be accepted.
  ; q=15, t=0xFFFFFFFF, n=0x000FFFFF -> q'=10, m=0xFFFFF500.
  MOVI r1,15
  MOVI r2,0xFFFF
  MOVHI r2,0xFFFF
  MOVI r3,0xFFFF
  MOVHI r3,0x000F
  MOVI r4,@mth_sequence_test_max_state
  MOVI r5,@mth_sequence_test_max_token
  CALL @mth_sequence_step_u32
  CMP r1,r13
  JMP[NE] @mth_sequence_test_fail_3

  MOVI r1,@mth_sequence_test_max_state
  LD r6,r1,0
  MOVI r7,10
  CMP r6,r7
  JMP[NE] @mth_sequence_test_fail_3
  MOVI r1,@mth_sequence_test_max_token
  LD r6,r1,0
  MOVI r7,0xF500
  MOVHI r7,0xFFFF
  CMP r6,r7
  JMP[NE] @mth_sequence_test_fail_3

  ; State 16 is one past the state bound.
  MOVI r1,16
  MOVI r2,0x1234
  MOVI r3,0
  CALL @mth_sequence_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_sequence_test_fail_3

  ; 0xFFFFFFFF is far past the state bound.
  MOVI r1,0xFFFF
  MOVHI r1,0xFFFF
  MOVI r2,0
  MOVI r3,0xFFFF
  MOVHI r3,0x000F
  CALL @mth_sequence_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_sequence_test_fail_3

  ; Step 1,048,576 (0x00100000) is one past the step bound.
  MOVI r1,0
  MOVI r2,0xFFFF
  MOVHI r2,0xFFFF
  MOVI r3,0
  MOVHI r3,0x0010
  CALL @mth_sequence_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_sequence_test_fail_3

  ; 0xFFFFFFFF is far past the step bound.
  MOVI r1,15
  MOVI r2,0
  MOVI r3,0xFFFF
  MOVHI r3,0xFFFF
  CALL @mth_sequence_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_sequence_test_fail_3

  ; ---- Case 4: repeatability over a chained known-answer sequence ----
  ; Poison the two result slots so stale memory cannot satisfy the checks.
  MOVI r2,0xAAAA
  MOVHI r2,0xAAAA
  MOVI r1,@mth_sequence_test_chain_state_a
  ST r2,r1,0
  MOVI r1,@mth_sequence_test_chain_token_a
  ST r2,r1,0
  MOVI r2,0x5555
  MOVHI r2,0x5555
  MOVI r1,@mth_sequence_test_chain_state_b
  ST r2,r1,0
  MOVI r1,@mth_sequence_test_chain_token_b
  ST r2,r1,0

  MOVI r1,@mth_sequence_test_chain_state_a
  CALL @mth_sequence_test_chain
  CMP r1,r13
  JMP[NE] @mth_sequence_test_fail_4

  MOVI r1,@mth_sequence_test_chain_state_b
  CALL @mth_sequence_test_chain
  CMP r1,r13
  JMP[NE] @mth_sequence_test_fail_4

  MOVI r1,@mth_sequence_test_chain_state_a
  MOVI r2,@mth_sequence_test_chain_state_b
  CALL @mth_sequence_test_cmp_word
  CMP r1,r13
  JMP[NE] @mth_sequence_test_fail_4
  MOVI r1,@mth_sequence_test_chain_token_a
  MOVI r2,@mth_sequence_test_chain_token_b
  CALL @mth_sequence_test_cmp_word
  CMP r1,r13
  JMP[NE] @mth_sequence_test_fail_4

  MOVI r1,@mth_sequence_test_chain_state_a
  CALL @mth_sequence_test_check_class
  CMP r1,r13
  JMP[NE] @mth_sequence_test_fail_4
  MOVI r1,@mth_sequence_test_chain_token_a
  CALL @mth_sequence_test_check_class
  CMP r1,r13
  JMP[NE] @mth_sequence_test_fail_4

  MOVI r1,@mth_sequence_test_pass
  CALL @mth_sequence_test_puts
  HALT

; ---- failure reporting ----
mth_sequence_test_fail_1:
  MOVI r2,1
  JMP @mth_sequence_test_fail
mth_sequence_test_fail_2:
  MOVI r2,2
  JMP @mth_sequence_test_fail
mth_sequence_test_fail_3:
  MOVI r2,3
  JMP @mth_sequence_test_fail
mth_sequence_test_fail_4:
  MOVI r2,4

mth_sequence_test_fail:
  ADD r6,r2,r0
  MOVI r1,@mth_sequence_test_bad_prefix
  CALL @mth_sequence_test_puts
  MOVI r1,48
  ADD r1,r1,r6
  PUTC r1
  MOVI r1,@mth_sequence_test_nl
  CALL @mth_sequence_test_puts
  HALT

; ---- helpers ----
; r1 = state output scratch; the token scratch is the following word.
; Runs steps n=0..4 from q=0 and compares every result with fixed KATs.
; Returns r1=1 on success, r1=0 on any mismatch.
mth_sequence_test_chain:
  ST r15,r0,@mth_sequence_test_chain_ret
  ADD r14,r1,r0              ; scratch pair base
  MOVI r11,0                 ; q = 0
  MOVI r12,0                 ; n = 0
mth_sequence_test_chain_loop:
  MOVI r2,@mth_sequence_test_chain_tokens
  ADD r2,r2,r12
  LD r2,r2,0
  ADD r1,r11,r0
  ADD r3,r12,r0
  ADD r4,r14,r0
  ADD r5,r14,r13
  CALL @mth_sequence_step_u32
  CMP r1,r13
  JMP[NE] @mth_sequence_test_chain_fail

  MOVI r6,@mth_sequence_test_chain_expected_states
  ADD r6,r6,r12
  LD r7,r6,0
  LD r8,r14,0
  CMP r8,r7
  JMP[NE] @mth_sequence_test_chain_fail

  MOVI r6,@mth_sequence_test_chain_expected_tokens
  ADD r6,r6,r12
  LD r7,r6,0
  ADD r6,r14,r13
  LD r8,r6,0
  CMP r8,r7
  JMP[NE] @mth_sequence_test_chain_fail

  LD r11,r14,0
  ADD r12,r12,r13
  MOVI r6,5
  CMP r12,r6
  JMP[LT] @mth_sequence_test_chain_loop
  MOVI r1,1
  LD r15,r0,@mth_sequence_test_chain_ret
  RET
mth_sequence_test_chain_fail:
  MOVI r1,0
  LD r15,r0,@mth_sequence_test_chain_ret
  RET

; r1 = input state, r2 = token, r3 = step.
; Returns r1=1 iff the call is rejected and both outputs are 0xFFFFFFFF.
mth_sequence_test_expect_reject:
  ST r15,r0,@mth_sequence_test_reject_ret
  MOVI r4,@mth_sequence_test_reject_state
  MOVI r5,@mth_sequence_test_reject_token
  MOVI r6,0xAAAA
  MOVHI r6,0xAAAA
  ST r6,r4,0
  ST r6,r5,0
  CALL @mth_sequence_step_u32
  CMP r1,r0
  JMP[NE] @mth_sequence_test_reject_fail

  MOVI r6,0xFFFF
  MOVHI r6,0xFFFF
  LD r7,r4,0
  CMP r7,r6
  JMP[NE] @mth_sequence_test_reject_fail
  LD r7,r5,0
  CMP r7,r6
  JMP[NE] @mth_sequence_test_reject_fail
  MOVI r1,1
  LD r15,r0,@mth_sequence_test_reject_ret
  RET
mth_sequence_test_reject_fail:
  MOVI r1,0
  LD r15,r0,@mth_sequence_test_reject_ret
  RET

; r1=first word address, r2=second word address -> r1=1 iff payloads match.
mth_sequence_test_cmp_word:
  LD r3,r1,0
  LD r4,r2,0
  CMP r3,r4
  MOVI r1,0
  RET[NE]
  MOVI r1,1
  RET

; r1=address -> r1=1 iff both words have class nibble 10.
mth_sequence_test_check_class:
  LDN r3,r1,0
  MOVI r4,10
  CMP r3,r4
  JMP[NE] @mth_sequence_test_class_bad
  LDN r3,r1,1
  CMP r3,r4
  JMP[EQ] @mth_sequence_test_class_ok
mth_sequence_test_class_bad:
  MOVI r1,0
  RET
mth_sequence_test_class_ok:
  MOVI r1,1
  RET

; r1=string address; writes NUL-terminated bytes through PUTC.
mth_sequence_test_puts:
  MOVI r4,255
mth_sequence_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_sequence_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_sequence_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_sequence_test_puts_word

; ---- data ----
mth_sequence_test_initial_state:
.word 0
mth_sequence_test_initial_token:
.word 0
mth_sequence_test_normal_state:
.word 0
mth_sequence_test_normal_token:
.word 0
mth_sequence_test_max_state:
.word 0
mth_sequence_test_max_token:
.word 0
mth_sequence_test_reject_state:
.word 0
mth_sequence_test_reject_token:
.word 0
mth_sequence_test_chain_state_a:
.word 0
mth_sequence_test_chain_token_a:
.word 0
mth_sequence_test_chain_state_b:
.word 0
mth_sequence_test_chain_token_b:
.word 0
mth_sequence_test_chain_ret:
.word 0
mth_sequence_test_reject_ret:
.word 0

; Five-step chain from q=0. The expected outputs are fixed KATs for the law:
; q' = (5q + 3*fold4(t) + ((t>>4)&15) + fold4(n) + 1) & 15
; m  = t ^ (q'<<8) ^ (q<<4) ^ fold4(n)
mth_sequence_test_chain_tokens:
.word 0x00000000
.word 0x00000001
.word 0x12345678
.word 0xFFFFFFFF
.word 0xA5A5A5A5
mth_sequence_test_chain_expected_states:
.word 1
.word 10
.word 4
.word 7
.word 2
mth_sequence_test_chain_expected_tokens:
.word 0x00000100
.word 0x00000A10
.word 0x123452DA
.word 0xFFFFF8BC
.word 0xA5A5A7D1

mth_sequence_test_pass:
.str "MTH SEQUENCE STEP U32 PASS\n"
mth_sequence_test_bad_prefix:
.str "MTH SEQUENCE STEP U32 FAIL "
mth_sequence_test_nl:
.str "\n"
