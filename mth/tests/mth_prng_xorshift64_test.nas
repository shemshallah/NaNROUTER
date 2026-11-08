; MTH native xorshift64 forward-step fixture — NaN16 only.
;
; The checks are deterministic and self-contained:
;   1. all-zero state rejection and the canonical 0xFFFFFFFF_FFFFFFFF marker;
;   2. a canonical known-answer sequence for 0x0123456789ABCDEF;
;   3. an independent in-guest reference that performs each 64-bit shift one
;      bit at a time, over four seeds and three steps per seed;
;   4. in-place (r1 == r2), fully aliased (r1 == r2 == r3), and separate
;      output-state/value calls;
;   5. output/state consistency and class-10 output framing.
;
; No host arithmetic is used. The reference sequence uses only NaN16 integer
; instructions and is compared against the native step in guest memory.

.org 0
JMP @mth_prng_test_main
.include "../nan16/mth_prng_xorshift64.nas"

mth_prng_test_main:
  MOVI r13,1

  ; ---- Case 1: all-zero state is rejected with the canonical marker ----
  ; Pre-fill the outputs with a different value so every marker word is visible.
  MOVI r4,0xAAAA
  MOVHI r4,0xAAAA
  MOVI r1,@mth_prng_test_zero_out_state
  ST r4,r1,0
  ST r4,r1,1
  MOVI r1,@mth_prng_test_zero_out_value
  ST r4,r1,0
  ST r4,r1,1

  MOVI r1,@mth_prng_test_zero_state
  MOVI r2,@mth_prng_test_zero_out_state
  MOVI r3,@mth_prng_test_zero_out_value
  CALL @mth_prng_xorshift64_step
  CMP r1,r0
  JMP[NE] @mth_prng_test_fail_1

  MOVI r4,0xFFFF
  MOVHI r4,0xFFFF
  MOVI r1,@mth_prng_test_zero_out_state
  LD r5,r1,0
  CMP r5,r4
  JMP[NE] @mth_prng_test_fail_1
  LD r5,r1,1
  CMP r5,r4
  JMP[NE] @mth_prng_test_fail_1
  MOVI r1,@mth_prng_test_zero_out_value
  LD r5,r1,0
  CMP r5,r4
  JMP[NE] @mth_prng_test_fail_1
  LD r5,r1,1
  CMP r5,r4
  JMP[NE] @mth_prng_test_fail_1

  ; The zero input state must not be written by the reject path.
  MOVI r1,@mth_prng_test_zero_state
  LD r5,r1,0
  CMP r5,r0
  JMP[NE] @mth_prng_test_fail_1
  LD r5,r1,1
  CMP r5,r0
  JMP[NE] @mth_prng_test_fail_1

  ; The marker must remain canonical class-10 (+q/+q) words.
  MOVI r1,@mth_prng_test_zero_out_state
  CALL @mth_prng_test_check_class
  CMP r1,r13
  JMP[NE] @mth_prng_test_fail_1
  MOVI r1,@mth_prng_test_zero_out_value
  CALL @mth_prng_test_check_class
  CMP r1,r13
  JMP[NE] @mth_prng_test_fail_1

  ; ---- Case 2: canonical known-answer sequence ----
  ; seed x0 = 0x0123456789ABCDEF
  ; x1 = 0x3F2800D6569E01B4
  ; x2 = 0x606F949A3CEBD0B7
  MOVI r1,@mth_prng_test_kat_seed
  MOVI r2,@mth_prng_test_kat_out
  MOVI r3,@mth_prng_test_kat_value
  CALL @mth_prng_xorshift64_step
  CMP r1,r13
  JMP[NE] @mth_prng_test_fail_2

  ; x1 low half = 0x569E01B4
  MOVI r4,0x01B4
  MOVHI r4,0x569E
  MOVI r1,@mth_prng_test_kat_out
  LD r5,r1,0
  CMP r5,r4
  JMP[NE] @mth_prng_test_fail_2
  ; x1 high half = 0x3F2800D6
  MOVI r4,0x00D6
  MOVHI r4,0x3F28
  LD r5,r1,1
  CMP r5,r4
  JMP[NE] @mth_prng_test_fail_2

  ; The output value span must equal the output state span.
  MOVI r1,@mth_prng_test_kat_value
  MOVI r2,@mth_prng_test_kat_out
  CALL @mth_prng_test_cmp64
  CMP r1,r13
  JMP[NE] @mth_prng_test_fail_2

  ; Both spans must be canonical class-10 words.
  MOVI r1,@mth_prng_test_kat_out
  CALL @mth_prng_test_check_class
  CMP r1,r13
  JMP[NE] @mth_prng_test_fail_2
  MOVI r1,@mth_prng_test_kat_value
  CALL @mth_prng_test_check_class
  CMP r1,r13
  JMP[NE] @mth_prng_test_fail_2

  ; Progression: x1 must differ from x0.
  MOVI r1,@mth_prng_test_kat_out
  MOVI r2,@mth_prng_test_kat_seed
  CALL @mth_prng_test_cmp64
  CMP r1,r0
  JMP[NE] @mth_prng_test_fail_2

  ; Second step, output state aliases the input state.
  MOVI r1,@mth_prng_test_kat_out
  MOVI r2,@mth_prng_test_kat_out
  MOVI r3,@mth_prng_test_kat_value
  CALL @mth_prng_xorshift64_step
  CMP r1,r13
  JMP[NE] @mth_prng_test_fail_2

  ; x2 low half = 0x3CEBD0B7
  MOVI r4,0xD0B7
  MOVHI r4,0x3CEB
  MOVI r1,@mth_prng_test_kat_out
  LD r5,r1,0
  CMP r5,r4
  JMP[NE] @mth_prng_test_fail_2
  ; x2 high half = 0x606F949A
  MOVI r4,0x949A
  MOVHI r4,0x606F
  LD r5,r1,1
  CMP r5,r4
  JMP[NE] @mth_prng_test_fail_2
  MOVI r1,@mth_prng_test_kat_value
  MOVI r2,@mth_prng_test_kat_out
  CALL @mth_prng_test_cmp64
  CMP r1,r13
  JMP[NE] @mth_prng_test_fail_2

  ; Fully aliased r1 == r2 == r3: the original seed must become x1 in place.
  MOVI r1,@mth_prng_test_kat_seed
  MOVI r2,@mth_prng_test_kat_seed
  MOVI r3,@mth_prng_test_kat_seed
  CALL @mth_prng_xorshift64_step
  CMP r1,r13
  JMP[NE] @mth_prng_test_fail_2
  MOVI r1,@mth_prng_test_kat_seed
  MOVI r4,0x01B4
  MOVHI r4,0x569E
  LD r5,r1,0
  CMP r5,r4
  JMP[NE] @mth_prng_test_fail_2
  MOVI r4,0x00D6
  MOVHI r4,0x3F28
  LD r5,r1,1
  CMP r5,r4
  JMP[NE] @mth_prng_test_fail_2

  ; ---- Case 3: independent bitwise reference over four seeds ----
  MOVI r10,@mth_prng_test_seeds
  MOVI r11,4

mth_prng_test_seed_loop:
  MOVI r1,@mth_prng_test_state
  ADD r2,r10,r0
  CALL @mth_prng_test_copy64
  MOVI r1,@mth_prng_test_ref
  ADD r2,r10,r0
  CALL @mth_prng_test_copy64

  MOVI r12,3
mth_prng_test_step_loop:
  ; 3 = state -> next (separate output state)
  ; 2 = next  -> next (in-place output state)
  ; 1 = next  -> state (separate output state, third step)
  MOVI r6,3
  CMP r12,r6
  JMP[EQ] @mth_prng_test_mode_out1
  MOVI r6,2
  CMP r12,r6
  JMP[EQ] @mth_prng_test_mode_inplace
  MOVI r1,@mth_prng_test_next
  MOVI r2,@mth_prng_test_state
  JMP @mth_prng_test_mode_go

mth_prng_test_mode_inplace:
  MOVI r1,@mth_prng_test_next
  MOVI r2,@mth_prng_test_next
  JMP @mth_prng_test_mode_go

mth_prng_test_mode_out1:
  MOVI r1,@mth_prng_test_state
  MOVI r2,@mth_prng_test_next

mth_prng_test_mode_go:
  ST r2,r0,@mth_prng_test_saved_dst
  MOVI r3,@mth_prng_test_value
  CALL @mth_prng_xorshift64_step
  CMP r1,r13
  JMP[NE] @mth_prng_test_fail_3

  ; Advance the independent bitwise reference by exactly one step.
  MOVI r1,@mth_prng_test_ref
  CALL @mth_prng_test_ref_step

  ; The native output state must equal the reference state.
  LD r1,r0,@mth_prng_test_saved_dst
  MOVI r2,@mth_prng_test_ref
  CALL @mth_prng_test_cmp64
  CMP r1,r13
  JMP[NE] @mth_prng_test_fail_3

  ; The output value must equal the output state.
  LD r1,r0,@mth_prng_test_saved_dst
  MOVI r2,@mth_prng_test_value
  CALL @mth_prng_test_cmp64
  CMP r1,r13
  JMP[NE] @mth_prng_test_fail_4

  ; A nonzero xorshift64 orbit can never reach zero.
  LD r1,r0,@mth_prng_test_saved_dst
  MOVI r2,@mth_prng_test_zero_state
  CALL @mth_prng_test_cmp64
  CMP r1,r13
  JMP[EQ] @mth_prng_test_fail_5

  ; Both output spans must be class-10 words.
  LD r1,r0,@mth_prng_test_saved_dst
  CALL @mth_prng_test_check_class
  CMP r1,r13
  JMP[NE] @mth_prng_test_fail_3
  MOVI r1,@mth_prng_test_value
  CALL @mth_prng_test_check_class
  CMP r1,r13
  JMP[NE] @mth_prng_test_fail_4

  SUB r12,r12,r13
  JMP[NE] @mth_prng_test_step_loop

  ADD r10,r10,r13
  ADD r10,r10,r13
  SUB r11,r11,r13
  JMP[NE] @mth_prng_test_seed_loop

  MOVI r1,@mth_prng_test_pass
  CALL @mth_prng_test_puts
  HALT

; ---- failure reporting ----
mth_prng_test_fail_1:
  MOVI r2,1
  JMP @mth_prng_test_fail
mth_prng_test_fail_2:
  MOVI r2,2
  JMP @mth_prng_test_fail
mth_prng_test_fail_3:
  MOVI r2,3
  JMP @mth_prng_test_fail
mth_prng_test_fail_4:
  MOVI r2,4
  JMP @mth_prng_test_fail
mth_prng_test_fail_5:
  MOVI r2,5

mth_prng_test_fail:
  ADD r6,r2,r0
  MOVI r1,@mth_prng_test_bad_prefix
  CALL @mth_prng_test_puts
  MOVI r1,48
  ADD r1,r1,r6
  PUTC r1
  MOVI r1,@mth_prng_test_nl
  CALL @mth_prng_test_puts
  HALT

; ---- helpers ----
; r1=destination, r2=source; copies two payload words. Clobbers r3.
mth_prng_test_copy64:
  LD r3,r2,0
  ST r3,r1,0
  LD r3,r2,1
  ST r3,r1,1
  RET

; r1=first pair, r2=second pair -> r1=1 iff both payload words match.
; Clobbers r3,r4 and flags.
mth_prng_test_cmp64:
  LD r3,r1,0
  LD r4,r2,0
  CMP r3,r4
  JMP[NE] @mth_prng_test_cmp_bad
  LD r3,r1,1
  LD r4,r2,1
  CMP r3,r4
  JMP[EQ] @mth_prng_test_cmp_ok
mth_prng_test_cmp_bad:
  MOVI r1,0
  RET
mth_prng_test_cmp_ok:
  MOVI r1,1
  RET

; r1=address -> r1=1 iff both words have class nibble 10; else r1=0.
; Clobbers r3,r4 and flags.
mth_prng_test_check_class:
  LDN r3,r1,0
  MOVI r4,10
  CMP r3,r4
  JMP[NE] @mth_prng_test_class_bad
  LDN r3,r1,1
  CMP r3,r4
  JMP[EQ] @mth_prng_test_class_ok
mth_prng_test_class_bad:
  MOVI r1,0
  RET
mth_prng_test_class_ok:
  MOVI r1,1
  RET

; Independent reference step: r1=state address, updated in place.
; Performs x ^= x << 13; x ^= x >> 7; x ^= x << 17 by shifting one bit at a
; time, so it does not share the native kernel's 32-bit cross-half formulas.
; Clobbers r2-r7. Preserves r8-r15.
mth_prng_test_ref_step:
  LD r2,r1,0
  LD r3,r1,1

  ; x ^= x << 13
  ADD r4,r2,r0
  ADD r5,r3,r0
  MOVI r6,13
mth_prng_test_ref_l13:
  SHR r7,r4,31
  SHL r4,r4,1
  SHL r5,r5,1
  BOOL.14 r5,r5,r7
  SUB r6,r6,r13
  JMP[NE] @mth_prng_test_ref_l13
  BOOL.6 r2,r2,r4
  BOOL.6 r3,r3,r5

  ; x ^= x >> 7
  ADD r4,r2,r0
  ADD r5,r3,r0
  MOVI r6,7
mth_prng_test_ref_r7:
  MOVI r7,1
  BOOL.8 r7,r5,r7
  SHR r5,r5,1
  SHR r4,r4,1
  SHL r7,r7,31
  BOOL.14 r4,r4,r7
  SUB r6,r6,r13
  JMP[NE] @mth_prng_test_ref_r7
  BOOL.6 r2,r2,r4
  BOOL.6 r3,r3,r5

  ; x ^= x << 17
  ADD r4,r2,r0
  ADD r5,r3,r0
  MOVI r6,17
mth_prng_test_ref_l17:
  SHR r7,r4,31
  SHL r4,r4,1
  SHL r5,r5,1
  BOOL.14 r5,r5,r7
  SUB r6,r6,r13
  JMP[NE] @mth_prng_test_ref_l17
  BOOL.6 r2,r2,r4
  BOOL.6 r3,r3,r5

  ST r2,r1,0
  ST r3,r1,1
  RET

; r1=string address; writes NUL-terminated bytes through PUTC.
mth_prng_test_puts:
  MOVI r4,255
mth_prng_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_prng_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_prng_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_prng_test_puts_word

; ---- data ----
mth_prng_test_zero_state:
.word 0
.word 0
mth_prng_test_zero_out_state:
.word 0
.word 0
mth_prng_test_zero_out_value:
.word 0
.word 0

mth_prng_test_kat_seed:
.word 0x89ABCDEF
.word 0x01234567
mth_prng_test_kat_out:
.word 0
.word 0
mth_prng_test_kat_value:
.word 0
.word 0

mth_prng_test_seeds:
.word 0x00000001
.word 0x00000000
.word 0xFFFFFFFF
.word 0xFFFFFFFF
.word 0x00000000
.word 0x80000000
.word 0x89ABCDEF
.word 0x01234567

mth_prng_test_state:
.word 0
.word 0
mth_prng_test_next:
.word 0
.word 0
mth_prng_test_ref:
.word 0
.word 0
mth_prng_test_value:
.word 0
.word 0
mth_prng_test_saved_dst:
.word 0

mth_prng_test_pass:
.str "MTH PRNG XORSHIFT64 PASS\n"
mth_prng_test_bad_prefix:
.str "MTH PRNG XORSHIFT64 FAIL "
mth_prng_test_nl:
.str "\n"
