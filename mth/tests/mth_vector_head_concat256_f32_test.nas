; MTH two-head float32 concatenation fixture — NaN16 only.
;
; All input vectors are generated in the guest at run time. Every one of the
; 256 output positions is checked by a native integer CMP on the raw 32-bit
; payload; no host arithmetic is used at build time or run time.
;
; Success phases:
;   1. A[i] = (float32)(i + 1), B[i] = (float32)(i + 1001), i = 0..127.
;      Checks all 256 outputs against the runtime-generated expectations and
;      explicitly checks the head boundary out[127] = 128.0 and
;      out[128] = 1001.0.
;   2. A and B are filled from finite edge-payload tables (signed zero,
;      signed min subnormal, signed max finite, min normal, and ordinary
;      values). Checks exact payload preservation at all 256 positions.
;   3. Exact out == A aliasing: a 256-word buffer whose lower half is the A
;      pattern and whose upper half starts as 0xDEADBEEF. B first fills the
;      upper half, then A is stored to itself. All 256 words are checked.
;   4. Exact out == B aliasing: the lower half starts as the B pattern and
;      the upper half as 0xDEADBEEF. The B pass consumes the lower half
;      before A overwrites it. All 256 words are checked.
;   5. Exact out == A == B aliasing: one 256-word buffer, lower half pattern,
;      upper half sentinel. Both halves must become the pattern.
;
; Failure phases (out is pre-filled with 0xDEADBEEF before each call):
;   6. quiet NaN in A[127] -> r1=0, cause 1, all 256 output words untouched.
;   7. +inf in B[0] -> r1=0, cause 2, all 256 output words untouched.
;   8. -inf in A[0] -> r1=0, cause 1, all 256 output words untouched.
;   9. signaling NaN in B[127] -> r1=0, cause 2, all 256 untouched.
;  10. bad A[0] and bad B[127] together -> cause 1 (A preflight priority).
;  11. recovery: the phase-1 vectors succeed again after all rejections.

.org 0
JMP @mth_hc_test_main
.include "../nan16/mth_vector_head_concat256_f32.nas"

mth_hc_test_main:
  MOVI r13,1

  ; ---- Phase 1: runtime-generated iota vectors, every position checked.
  LA r1,@mth_hc_test_a
  MOVI r2,1
  CALL @mth_hc_test_fill_iota
  LA r1,@mth_hc_test_b
  MOVI r2,1001
  CALL @mth_hc_test_fill_iota
  LA r1,@mth_hc_test_a
  LA r2,@mth_hc_test_b
  LA r3,@mth_hc_test_out
  CALL @mth_vector_head_concat256_f32
  CMP r1,r13
  JMP[NE] @mth_hc_test_fail
  CMP r9,r0
  JMP[NE] @mth_hc_test_fail
  LA r1,@mth_hc_test_out
  CALL @mth_hc_test_check_iota

  ; Explicit 127/128 boundary for the unique iota inputs.
  LA r4,@mth_hc_test_out
  LD r5,r4,127
  MOVI r6,128
  CVTIF r6,r6                ; 128.0, the last A element
  CMP r5,r6
  JMP[NE] @mth_hc_test_fail
  LD r5,r4,128
  MOVI r6,1001
  CVTIF r6,r6                ; 1001.0, the first B element
  CMP r5,r6
  JMP[NE] @mth_hc_test_fail

  ; ---- Phase 2: finite edge payloads, exact copy at all 256 positions.
  LA r1,@mth_hc_test_a
  LA r2,@mth_hc_test_pattern_a
  CALL @mth_hc_test_fill_pattern128
  LA r1,@mth_hc_test_b
  LA r2,@mth_hc_test_pattern_b
  CALL @mth_hc_test_fill_pattern128
  LA r1,@mth_hc_test_out
  MOVI r2,256
  MOVI r3,0xBEEF
  MOVHI r3,0xDEAD
  CALL @mth_hc_test_fill_words
  LA r1,@mth_hc_test_a
  LA r2,@mth_hc_test_b
  LA r3,@mth_hc_test_out
  CALL @mth_vector_head_concat256_f32
  CMP r1,r13
  JMP[NE] @mth_hc_test_fail
  CMP r9,r0
  JMP[NE] @mth_hc_test_fail
  LA r1,@mth_hc_test_a
  LA r2,@mth_hc_test_b
  LA r3,@mth_hc_test_out
  CALL @mth_hc_test_check_halves

  ; Re-check the exact boundary payloads of the edge pattern.
  LA r4,@mth_hc_test_out
  LA r5,@mth_hc_test_a
  LD r6,r5,127
  LD r7,r4,127
  CMP r7,r6
  JMP[NE] @mth_hc_test_fail
  LA r5,@mth_hc_test_b
  LD r6,r5,0
  LD r7,r4,128
  CMP r7,r6
  JMP[NE] @mth_hc_test_fail

  ; ---- Phase 3: exact out == A aliasing.
  LA r1,@mth_hc_test_alias_a
  MOVI r2,256
  MOVI r3,0xBEEF
  MOVHI r3,0xDEAD
  CALL @mth_hc_test_fill_words
  LA r1,@mth_hc_test_alias_a
  LA r2,@mth_hc_test_pattern_a
  CALL @mth_hc_test_fill_pattern128
  LA r1,@mth_hc_test_alias_a
  LA r2,@mth_hc_test_b
  LA r3,@mth_hc_test_alias_a
  CALL @mth_vector_head_concat256_f32
  CMP r1,r13
  JMP[NE] @mth_hc_test_fail
  CMP r9,r0
  JMP[NE] @mth_hc_test_fail
  LA r1,@mth_hc_test_a
  LA r2,@mth_hc_test_b
  LA r3,@mth_hc_test_alias_a
  CALL @mth_hc_test_check_halves

  ; ---- Phase 4: exact out == B aliasing.
  LA r1,@mth_hc_test_alias_b
  MOVI r2,256
  MOVI r3,0xBEEF
  MOVHI r3,0xDEAD
  CALL @mth_hc_test_fill_words
  LA r1,@mth_hc_test_alias_b
  LA r2,@mth_hc_test_pattern_b
  CALL @mth_hc_test_fill_pattern128
  LA r1,@mth_hc_test_a
  LA r2,@mth_hc_test_alias_b
  LA r3,@mth_hc_test_alias_b
  CALL @mth_vector_head_concat256_f32
  CMP r1,r13
  JMP[NE] @mth_hc_test_fail
  CMP r9,r0
  JMP[NE] @mth_hc_test_fail
  LA r1,@mth_hc_test_a
  LA r2,@mth_hc_test_b
  LA r3,@mth_hc_test_alias_b
  CALL @mth_hc_test_check_halves

  ; ---- Phase 5: exact out == A == B aliasing.
  LA r1,@mth_hc_test_alias_both
  MOVI r2,256
  MOVI r3,0xBEEF
  MOVHI r3,0xDEAD
  CALL @mth_hc_test_fill_words
  LA r1,@mth_hc_test_alias_both
  LA r2,@mth_hc_test_pattern_a
  CALL @mth_hc_test_fill_pattern128
  LA r1,@mth_hc_test_alias_both
  LA r2,@mth_hc_test_alias_both
  LA r3,@mth_hc_test_alias_both
  CALL @mth_vector_head_concat256_f32
  CMP r1,r13
  JMP[NE] @mth_hc_test_fail
  CMP r9,r0
  JMP[NE] @mth_hc_test_fail
  LA r1,@mth_hc_test_a
  LA r2,@mth_hc_test_a
  LA r3,@mth_hc_test_alias_both
  CALL @mth_hc_test_check_halves

  ; ---- Phase 6: quiet NaN in the last A position; atomic cause 1.
  LA r1,@mth_hc_test_a
  MOVI r2,1
  CALL @mth_hc_test_fill_iota
  LA r1,@mth_hc_test_b
  MOVI r2,1001
  CALL @mth_hc_test_fill_iota
  LA r1,@mth_hc_test_out
  MOVI r2,256
  MOVI r3,0xBEEF
  MOVHI r3,0xDEAD
  CALL @mth_hc_test_fill_words
  LA r6,@mth_hc_test_a
  MOVI r7,0x0123
  MOVHI r7,0x7FC0            ; quiet NaN 0x7FC00123
  ST r7,r6,127
  LA r1,@mth_hc_test_a
  LA r2,@mth_hc_test_b
  LA r3,@mth_hc_test_out
  CALL @mth_vector_head_concat256_f32
  MOVI r5,1
  CALL @mth_hc_test_expect_failure

  ; ---- Phase 7: +inf in the first B position; atomic cause 2.
  LA r1,@mth_hc_test_a
  MOVI r2,1
  CALL @mth_hc_test_fill_iota
  LA r1,@mth_hc_test_b
  MOVI r2,1001
  CALL @mth_hc_test_fill_iota
  LA r1,@mth_hc_test_out
  MOVI r2,256
  MOVI r3,0xBEEF
  MOVHI r3,0xDEAD
  CALL @mth_hc_test_fill_words
  LA r6,@mth_hc_test_b
  MOVI r7,0
  MOVHI r7,0x7F80            ; +inf 0x7F800000
  ST r7,r6,0
  LA r1,@mth_hc_test_a
  LA r2,@mth_hc_test_b
  LA r3,@mth_hc_test_out
  CALL @mth_vector_head_concat256_f32
  MOVI r5,2
  CALL @mth_hc_test_expect_failure

  ; ---- Phase 8: -inf in the first A position; atomic cause 1.
  LA r1,@mth_hc_test_a
  MOVI r2,1
  CALL @mth_hc_test_fill_iota
  LA r1,@mth_hc_test_b
  MOVI r2,1001
  CALL @mth_hc_test_fill_iota
  LA r1,@mth_hc_test_out
  MOVI r2,256
  MOVI r3,0xBEEF
  MOVHI r3,0xDEAD
  CALL @mth_hc_test_fill_words
  LA r6,@mth_hc_test_a
  MOVI r7,0
  MOVHI r7,0xFF80            ; -inf 0xFF800000
  ST r7,r6,0
  LA r1,@mth_hc_test_a
  LA r2,@mth_hc_test_b
  LA r3,@mth_hc_test_out
  CALL @mth_vector_head_concat256_f32
  MOVI r5,1
  CALL @mth_hc_test_expect_failure

  ; ---- Phase 9: signaling NaN in the last B position; atomic cause 2.
  LA r1,@mth_hc_test_a
  MOVI r2,1
  CALL @mth_hc_test_fill_iota
  LA r1,@mth_hc_test_b
  MOVI r2,1001
  CALL @mth_hc_test_fill_iota
  LA r1,@mth_hc_test_out
  MOVI r2,256
  MOVI r3,0xBEEF
  MOVHI r3,0xDEAD
  CALL @mth_hc_test_fill_words
  LA r6,@mth_hc_test_b
  MOVI r7,1
  MOVHI r7,0x7F80            ; signaling NaN 0x7F800001
  ST r7,r6,127
  LA r1,@mth_hc_test_a
  LA r2,@mth_hc_test_b
  LA r3,@mth_hc_test_out
  CALL @mth_vector_head_concat256_f32
  MOVI r5,2
  CALL @mth_hc_test_expect_failure

  ; ---- Phase 10: both halves bad; the A preflight has priority.
  LA r1,@mth_hc_test_a
  MOVI r2,1
  CALL @mth_hc_test_fill_iota
  LA r1,@mth_hc_test_b
  MOVI r2,1001
  CALL @mth_hc_test_fill_iota
  LA r1,@mth_hc_test_out
  MOVI r2,256
  MOVI r3,0xBEEF
  MOVHI r3,0xDEAD
  CALL @mth_hc_test_fill_words
  LA r6,@mth_hc_test_a
  MOVI r7,0x0001
  MOVHI r7,0x7F80            ; signaling NaN 0x7F800001
  ST r7,r6,0
  LA r6,@mth_hc_test_b
  MOVI r7,0
  MOVHI r7,0x7F80            ; +inf 0x7F800000
  ST r7,r6,127
  LA r1,@mth_hc_test_a
  LA r2,@mth_hc_test_b
  LA r3,@mth_hc_test_out
  CALL @mth_vector_head_concat256_f32
  MOVI r5,1
  CALL @mth_hc_test_expect_failure

  ; ---- Phase 11: recovery after rejection is bit-exact.
  LA r1,@mth_hc_test_a
  MOVI r2,1
  CALL @mth_hc_test_fill_iota
  LA r1,@mth_hc_test_b
  MOVI r2,1001
  CALL @mth_hc_test_fill_iota
  LA r1,@mth_hc_test_a
  LA r2,@mth_hc_test_b
  LA r3,@mth_hc_test_out
  CALL @mth_vector_head_concat256_f32
  CMP r1,r13
  JMP[NE] @mth_hc_test_fail
  CMP r9,r0
  JMP[NE] @mth_hc_test_fail
  LA r1,@mth_hc_test_out
  CALL @mth_hc_test_check_iota

  LA r1,@mth_hc_test_pass
  CALL @mth_hc_test_puts
  HALT

mth_hc_test_fail:
  LA r1,@mth_hc_test_bad
  CALL @mth_hc_test_puts
  HALT

; r1 = destination, r2 = signed integer start. Writes 128 words with
; CVTIF(i + r2). Clobbers r1, r3, r4.
mth_hc_test_fill_iota:
  MOVI r3,0
mth_hc_test_fill_iota_loop:
  ADD r4,r3,r2
  CVTIF r4,r4
  ST r4,r1,0
  ADD r1,r1,r13
  ADD r3,r3,r13
  MOVI r4,128
  CMP r3,r4
  JMP[LT] @mth_hc_test_fill_iota_loop
  RET

; r1 = destination, r2 = 8-word pattern table. Writes 128 words with
; pattern[i & 7]. Clobbers r1-r5.
mth_hc_test_fill_pattern128:
  MOVI r3,0
  MOVI r4,7
mth_hc_test_fill_pattern128_loop:
  BOOL.8 r5,r3,r4            ; i & 7
  ADD r5,r2,r5
  LD r5,r5,0
  ST r5,r1,0
  ADD r1,r1,r13
  ADD r3,r3,r13
  MOVI r5,128
  CMP r3,r5
  JMP[LT] @mth_hc_test_fill_pattern128_loop
  RET

; r1 = destination, r2 = positive word count, r3 = payload.
; Clobbers r1, r2.
mth_hc_test_fill_words:
  ST r3,r1,0
  ADD r1,r1,r13
  SUB r2,r2,r13
  CMP r2,r0
  JMP[GT] @mth_hc_test_fill_words
  RET

; r1 = out. Check out[i] = CVTIF(i + 1) for i < 128 and
; out[i] = CVTIF(i + 873) for i >= 128. Clobbers r1, r4-r7.
mth_hc_test_check_iota:
  MOVI r4,0
mth_hc_test_check_iota_loop:
  MOVI r5,128
  CMP r4,r5
  JMP[GE] @mth_hc_test_check_iota_second
  ADD r6,r4,r13              ; i + 1
  JMP @mth_hc_test_check_iota_convert
mth_hc_test_check_iota_second:
  MOVI r6,873
  ADD r6,r6,r4               ; i + 873 = (i - 128) + 1001
mth_hc_test_check_iota_convert:
  CVTIF r6,r6
  ADD r7,r1,r4
  LD r7,r7,0
  CMP r7,r6
  JMP[NE] @mth_hc_test_fail
  ADD r4,r4,r13
  MOVI r5,256
  CMP r4,r5
  JMP[LT] @mth_hc_test_check_iota_loop
  RET

; r1 = expected lower half, r2 = expected upper half, r3 = actual out.
; Checks out[i] = r1[i] and out[128+i] = r2[i] for i = 0..127.
; Clobbers r5-r7.
mth_hc_test_check_halves:
  MOVI r5,0
mth_hc_test_check_halves_loop:
  ADD r6,r1,r5
  LD r6,r6,0
  ADD r7,r3,r5
  LD r7,r7,0
  CMP r7,r6
  JMP[NE] @mth_hc_test_fail
  ADD r6,r2,r5
  LD r6,r6,0
  ADD r7,r3,r5
  ADDI r7,r7,128
  LD r7,r7,0
  CMP r7,r6
  JMP[NE] @mth_hc_test_fail
  ADD r5,r5,r13
  MOVI r6,128
  CMP r5,r6
  JMP[LT] @mth_hc_test_check_halves_loop
  RET

; Requires r1 = 0, r9 = r5, and all 256 words of out = 0xDEADBEEF.
; Clobbers r4, r6-r8.
mth_hc_test_expect_failure:
  CMP r1,r0
  JMP[NE] @mth_hc_test_fail
  CMP r9,r5
  JMP[NE] @mth_hc_test_fail
  LA r4,@mth_hc_test_out
  MOVI r6,0
  MOVI r7,0xBEEF
  MOVHI r7,0xDEAD
mth_hc_test_expect_failure_loop:
  LD r8,r4,0
  CMP r8,r7
  JMP[NE] @mth_hc_test_fail
  ADD r4,r4,r13
  ADD r6,r6,r13
  MOVI r8,256
  CMP r6,r8
  JMP[LT] @mth_hc_test_expect_failure_loop
  RET

mth_hc_test_puts:
  MOVI r4,255
mth_hc_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_hc_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_hc_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_hc_test_puts_word

.org 1024
mth_hc_test_a:
.word 0
.org 2048
mth_hc_test_b:
.word 0
.org 3072
mth_hc_test_out:
.word 0
.org 4096
mth_hc_test_alias_a:
.word 0
.org 5120
mth_hc_test_alias_b:
.word 0
.org 6144
mth_hc_test_alias_both:
.word 0
.org 7168
mth_hc_test_pattern_a:
.word 0x00000000          ; +0.0
.word 0x80000000          ; -0.0
.word 0x3F800000          ; +1.0
.word 0xBF800000          ; -1.0
.word 0x7F7FFFFF          ; +max finite
.word 0xFF7FFFFF          ; -max finite
.word 0x00000001          ; +min subnormal
.word 0x80000001          ; -min subnormal
mth_hc_test_pattern_b:
.word 0x40200000          ; +2.5
.word 0xC0500000          ; -3.25
.word 0x3F800001          ; 1 + 2^-23
.word 0xC0800000          ; -4.0
.word 0x00800000          ; +min normal
.word 0x80800000          ; -min normal
.word 0x40490FDB          ; pi approximation payload
.word 0xBF000000          ; -0.5
.org 8192
mth_hc_test_pass:
.str "MTH VECTOR HEAD CONCAT256 F32 PASS\n"
mth_hc_test_bad:
.str "MTH VECTOR HEAD CONCAT256 F32 FAIL\n"
