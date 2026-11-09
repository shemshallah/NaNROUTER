; MTH reference-cycle gauge-invariance fixture — NaN16 only.
;
; The kernel under test is a leaf predicate over four byte-addressed f32
; fields: x_0i, x_ij, x_0j, and the gauge scalar g. Every case loads four
; exact binary32 words into the fixture slots, calls the kernel, and requires
; the documented r1/r9 status. Values and expected statuses are generated
; in-guest from a table of binary32 bit patterns; no host math is used.
;
; Coverage:
;   1. exact positive, negative, and fractional values with drift zero;
;   2. +0.0 and -0.0 gauge shifts, plus an all-zero triangle;
;   3. exact cancellation of the reference circulation, positive and negative;
;   4. positive large g = +2^24 with equal rounding of x_0i+g and x_0j+g
;      (pass, drift zero), and a vector where those additions round the
;      opposite way (fail, drift 2 > 2^-16, cause 6);
;   5. negative large g = -2^24 with the mirror of both rounding outcomes;
;   6. the declared tolerance boundary: drift exactly 2^-16 passes, drift
;      2^-16 - 2^-23 passes, drift 2^-16 + 2^-23 fails with cause 6;
;   7. non-finite rejection for NaN, +inf, and -inf in each of the four input
;      positions, with causes 1-4 and priority checks proving the complete
;      input preflight wins over arithmetic overflow;
;   8. non-finite computed-value rejection (cause 5) for base overflow,
;      x_0i+g overflow, and x_0j+g overflow;
;   9. maximum-finite boundary: g = +FLT_MAX and g = -FLT_MAX pass when the
;      rounded sums cancel, maximum-finite operands cancel exactly with g=0,
;      and FLT_MAX+FLT_MAX overflows are rejected with cause 5.
;
; No output memory is written by the kernel, so the fixture checks status
; only. The step cap is 1,000,000.

.org 0
JMP @mth_gc_test_main
.include "../nan16/mth_mirror_gauge_check.nas"

mth_gc_test_main:
  MOVI r0,0
  MOVI r13,1

  ; ---- exact values ----
  LA r1,@mth_gc_test_case_exact_pos
  CALL @mth_gc_test_load_case
  CALL @mth_gc_test_expect_pass

  LA r1,@mth_gc_test_case_exact_neg
  CALL @mth_gc_test_load_case
  CALL @mth_gc_test_expect_pass

  LA r1,@mth_gc_test_case_exact_fractional
  CALL @mth_gc_test_load_case
  CALL @mth_gc_test_expect_pass

  ; ---- zero gauge shift and all-zero triangle ----
  LA r1,@mth_gc_test_case_zero_g_pos
  CALL @mth_gc_test_load_case
  CALL @mth_gc_test_expect_pass

  LA r1,@mth_gc_test_case_zero_g_neg
  CALL @mth_gc_test_load_case
  CALL @mth_gc_test_expect_pass

  LA r1,@mth_gc_test_case_all_zero
  CALL @mth_gc_test_load_case
  CALL @mth_gc_test_expect_pass

  ; ---- exact cancellation of the reference circulation ----
  LA r1,@mth_gc_test_case_cancel_pos
  CALL @mth_gc_test_load_case
  CALL @mth_gc_test_expect_pass

  LA r1,@mth_gc_test_case_cancel_neg
  CALL @mth_gc_test_load_case
  CALL @mth_gc_test_expect_pass

  ; ---- positive large g = +2^24, with rounding ----
  LA r1,@mth_gc_test_case_large_pos_pass
  CALL @mth_gc_test_load_case
  CALL @mth_gc_test_expect_pass

  LA r1,@mth_gc_test_case_large_pos_fail
  CALL @mth_gc_test_load_case
  MOVI r1,6
  CALL @mth_gc_test_expect_fail

  ; ---- negative large g = -2^24, with rounding ----
  LA r1,@mth_gc_test_case_large_neg_pass
  CALL @mth_gc_test_load_case
  CALL @mth_gc_test_expect_pass

  LA r1,@mth_gc_test_case_large_neg_fail
  CALL @mth_gc_test_load_case
  MOVI r1,6
  CALL @mth_gc_test_expect_fail

  ; ---- declared tolerance boundary, |drift| against 2^-16 ----
  LA r1,@mth_gc_test_case_tol_equal
  CALL @mth_gc_test_load_case
  CALL @mth_gc_test_expect_pass

  LA r1,@mth_gc_test_case_tol_below
  CALL @mth_gc_test_load_case
  CALL @mth_gc_test_expect_pass

  LA r1,@mth_gc_test_case_tol_above
  CALL @mth_gc_test_load_case
  MOVI r1,6
  CALL @mth_gc_test_expect_fail

  ; ---- maximum-finite boundary ----
  LA r1,@mth_gc_test_case_max_g_pos
  CALL @mth_gc_test_load_case
  CALL @mth_gc_test_expect_pass

  LA r1,@mth_gc_test_case_max_g_neg
  CALL @mth_gc_test_load_case
  CALL @mth_gc_test_expect_pass

  LA r1,@mth_gc_test_case_max_cancel
  CALL @mth_gc_test_load_case
  CALL @mth_gc_test_expect_pass

  ; ---- non-finite computed values -> cause 5 ----
  LA r1,@mth_gc_test_case_g_add_overflow
  CALL @mth_gc_test_load_case
  MOVI r1,5
  CALL @mth_gc_test_expect_fail

  LA r1,@mth_gc_test_case_base_overflow
  CALL @mth_gc_test_load_case
  MOVI r1,5
  CALL @mth_gc_test_expect_fail

  LA r1,@mth_gc_test_case_cg_overflow
  CALL @mth_gc_test_load_case
  MOVI r1,5
  CALL @mth_gc_test_expect_fail

  ; ---- NaN in x_0i -> cause 1 ----
  LA r1,@mth_gc_test_case_base_normal
  CALL @mth_gc_test_load_case
  LA r1,@mth_gc_test_a
  MOVI r2,0x0123
  MOVHI r2,0x7FC0
  ST r2,r1,0
  MOVI r1,1
  CALL @mth_gc_test_expect_fail

  ; ---- +inf in x_0i -> cause 1 ----
  LA r1,@mth_gc_test_case_base_normal
  CALL @mth_gc_test_load_case
  LA r1,@mth_gc_test_a
  MOVI r2,0
  MOVHI r2,0x7F80
  ST r2,r1,0
  MOVI r1,1
  CALL @mth_gc_test_expect_fail

  ; ---- -inf in x_0i -> cause 1 ----
  LA r1,@mth_gc_test_case_base_normal
  CALL @mth_gc_test_load_case
  LA r1,@mth_gc_test_a
  MOVI r2,0
  MOVHI r2,0xFF80
  ST r2,r1,0
  MOVI r1,1
  CALL @mth_gc_test_expect_fail

  ; ---- NaN in x_ij -> cause 2 ----
  LA r1,@mth_gc_test_case_base_normal
  CALL @mth_gc_test_load_case
  LA r1,@mth_gc_test_b
  MOVI r2,0x0456
  MOVHI r2,0x7FC0
  ST r2,r1,0
  MOVI r1,2
  CALL @mth_gc_test_expect_fail

  ; ---- +inf in x_ij -> cause 2 ----
  LA r1,@mth_gc_test_case_base_normal
  CALL @mth_gc_test_load_case
  LA r1,@mth_gc_test_b
  MOVI r2,0
  MOVHI r2,0x7F80
  ST r2,r1,0
  MOVI r1,2
  CALL @mth_gc_test_expect_fail

  ; ---- -inf in x_ij -> cause 2 ----
  LA r1,@mth_gc_test_case_base_normal
  CALL @mth_gc_test_load_case
  LA r1,@mth_gc_test_b
  MOVI r2,0
  MOVHI r2,0xFF80
  ST r2,r1,0
  MOVI r1,2
  CALL @mth_gc_test_expect_fail

  ; ---- NaN in x_0j -> cause 3 ----
  LA r1,@mth_gc_test_case_base_normal
  CALL @mth_gc_test_load_case
  LA r1,@mth_gc_test_c
  MOVI r2,0x0789
  MOVHI r2,0x7FC0
  ST r2,r1,0
  MOVI r1,3
  CALL @mth_gc_test_expect_fail

  ; ---- +inf in x_0j -> cause 3 ----
  LA r1,@mth_gc_test_case_base_normal
  CALL @mth_gc_test_load_case
  LA r1,@mth_gc_test_c
  MOVI r2,0
  MOVHI r2,0x7F80
  ST r2,r1,0
  MOVI r1,3
  CALL @mth_gc_test_expect_fail

  ; ---- -inf in x_0j -> cause 3 ----
  LA r1,@mth_gc_test_case_base_normal
  CALL @mth_gc_test_load_case
  LA r1,@mth_gc_test_c
  MOVI r2,0
  MOVHI r2,0xFF80
  ST r2,r1,0
  MOVI r1,3
  CALL @mth_gc_test_expect_fail

  ; ---- NaN in g -> cause 4 ----
  LA r1,@mth_gc_test_case_base_normal
  CALL @mth_gc_test_load_case
  LA r1,@mth_gc_test_g
  MOVI r2,0x0ABC
  MOVHI r2,0x7FC0
  ST r2,r1,0
  MOVI r1,4
  CALL @mth_gc_test_expect_fail

  ; ---- +inf in g -> cause 4 ----
  LA r1,@mth_gc_test_case_base_normal
  CALL @mth_gc_test_load_case
  LA r1,@mth_gc_test_g
  MOVI r2,0
  MOVHI r2,0x7F80
  ST r2,r1,0
  MOVI r1,4
  CALL @mth_gc_test_expect_fail

  ; ---- -inf in g -> cause 4 ----
  LA r1,@mth_gc_test_case_base_normal
  CALL @mth_gc_test_load_case
  LA r1,@mth_gc_test_g
  MOVI r2,0
  MOVHI r2,0xFF80
  ST r2,r1,0
  MOVI r1,4
  CALL @mth_gc_test_expect_fail

  ; ---- preflight priority: all four bad -> x_0i wins ----
  LA r1,@mth_gc_test_case_base_normal
  CALL @mth_gc_test_load_case
  LA r1,@mth_gc_test_a
  MOVI r2,0
  MOVHI r2,0x7FC0
  ST r2,r1,0
  LA r1,@mth_gc_test_b
  MOVI r2,0
  MOVHI r2,0x7F80
  ST r2,r1,0
  LA r1,@mth_gc_test_c
  MOVI r2,0
  MOVHI r2,0x7FC0
  ST r2,r1,0
  LA r1,@mth_gc_test_g
  MOVI r2,0
  MOVHI r2,0xFF80
  ST r2,r1,0
  MOVI r1,1
  CALL @mth_gc_test_expect_fail

  ; ---- preflight priority: x_ij wins over x_0j and g ----
  LA r1,@mth_gc_test_case_base_normal
  CALL @mth_gc_test_load_case
  LA r1,@mth_gc_test_b
  MOVI r2,0
  MOVHI r2,0x7F80
  ST r2,r1,0
  LA r1,@mth_gc_test_c
  MOVI r2,0
  MOVHI r2,0x7FC0
  ST r2,r1,0
  LA r1,@mth_gc_test_g
  MOVI r2,0
  MOVHI r2,0xFF80
  ST r2,r1,0
  MOVI r1,2
  CALL @mth_gc_test_expect_fail

  ; ---- preflight priority: x_0j wins over g ----
  LA r1,@mth_gc_test_case_base_normal
  CALL @mth_gc_test_load_case
  LA r1,@mth_gc_test_c
  MOVI r2,0
  MOVHI r2,0x7FC0
  ST r2,r1,0
  LA r1,@mth_gc_test_g
  MOVI r2,0
  MOVHI r2,0xFF80
  ST r2,r1,0
  MOVI r1,3
  CALL @mth_gc_test_expect_fail

  ; ---- complete preflight wins over arithmetic overflow: bad x_ij ----
  LA r1,@mth_gc_test_case_g_add_overflow
  CALL @mth_gc_test_load_case
  LA r1,@mth_gc_test_b
  MOVI r2,0
  MOVHI r2,0x7FC0
  ST r2,r1,0
  MOVI r1,2
  CALL @mth_gc_test_expect_fail

  ; ---- complete preflight wins over arithmetic overflow: bad x_0j ----
  LA r1,@mth_gc_test_case_g_add_overflow
  CALL @mth_gc_test_load_case
  LA r1,@mth_gc_test_c
  MOVI r2,0
  MOVHI r2,0x7FC0
  ST r2,r1,0
  MOVI r1,3
  CALL @mth_gc_test_expect_fail

  ; ---- recovery after rejection ----
  LA r1,@mth_gc_test_case_exact_pos
  CALL @mth_gc_test_load_case
  CALL @mth_gc_test_expect_pass

  LA r1,@mth_gc_test_pass
  CALL @mth_gc_test_puts
  HALT

; ---- helpers ----

; r1 = table row word address. Copies four binary32 words into the slots.
mth_gc_test_load_case:
  LD r2,r1,0
  ST r2,r0,@mth_gc_test_a
  LD r2,r1,1
  ST r2,r0,@mth_gc_test_b
  LD r2,r1,2
  ST r2,r0,@mth_gc_test_c
  LD r2,r1,3
  ST r2,r0,@mth_gc_test_g
  RET

; Calls the kernel on the current slots. Requires r1=1, r9=0.
mth_gc_test_expect_pass:
  ST r15,r0,@mth_gc_test_pass_ret
  LA r1,@mth_gc_test_a
  SHL r1,r1,2
  LA r2,@mth_gc_test_b
  SHL r2,r2,2
  LA r3,@mth_gc_test_c
  SHL r3,r3,2
  LA r4,@mth_gc_test_g
  SHL r4,r4,2
  CALL @mth_mirror_gauge_check

  CMP r1,r13
  JMP[NE] @mth_gc_test_fail
  CMP r9,r0
  JMP[NE] @mth_gc_test_fail

  LD r15,r0,@mth_gc_test_pass_ret
  RET

; Calls the kernel on the current slots. Requires r1=0, r9=cause.
; r1 = expected cause on entry.
mth_gc_test_expect_fail:
  ST r15,r0,@mth_gc_test_reject_ret
  ADD r14,r1,r0
  LA r1,@mth_gc_test_a
  SHL r1,r1,2
  LA r2,@mth_gc_test_b
  SHL r2,r2,2
  LA r3,@mth_gc_test_c
  SHL r3,r3,2
  LA r4,@mth_gc_test_g
  SHL r4,r4,2
  CALL @mth_mirror_gauge_check

  CMP r1,r0
  JMP[NE] @mth_gc_test_fail
  CMP r9,r14
  JMP[NE] @mth_gc_test_fail

  LD r15,r0,@mth_gc_test_reject_ret
  RET

; r1=string word address; writes NUL-terminated bytes through PUTC.
mth_gc_test_puts:
  MOVI r4,255
mth_gc_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_gc_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_gc_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_gc_test_puts_word

mth_gc_test_fail:
  LA r1,@mth_gc_test_bad
  CALL @mth_gc_test_puts
  HALT

; ---- data ----

.org 4096
mth_gc_test_a:
.word 0
mth_gc_test_b:
.word 0
mth_gc_test_c:
.word 0
mth_gc_test_g:
.word 0

; Each row: x_0i, x_ij, x_0j, g as raw binary32 words.
mth_gc_test_case_exact_pos:
.word 0x3F800000,0x40000000,0x3F000000,0x41000000
mth_gc_test_case_exact_neg:
.word 0xBFC00000,0x3F400000,0x40100000,0xC0800000
mth_gc_test_case_exact_fractional:
.word 0x40880000,0xBFA00000,0x40400000,0x3F000000
mth_gc_test_case_zero_g_pos:
.word 0x3FC00000,0xC0000000,0x3F000000,0x00000000
mth_gc_test_case_zero_g_neg:
.word 0x3FC00000,0xC0000000,0x3F000000,0x80000000
mth_gc_test_case_all_zero:
.word 0x00000000,0x00000000,0x00000000,0x00000000
mth_gc_test_case_cancel_pos:
.word 0x3F800000,0x40000000,0x40400000,0x41000000
mth_gc_test_case_cancel_neg:
.word 0xC0200000,0x40200000,0x00000000,0xC1000000
mth_gc_test_case_large_pos_pass:
.word 0x40400000,0x40000000,0x40400000,0x4B800000
mth_gc_test_case_large_pos_fail:
.word 0x3F800000,0x40000000,0x40400000,0x4B800000
mth_gc_test_case_large_neg_pass:
.word 0xC0400000,0x40000000,0xC0400000,0xCB800000
mth_gc_test_case_large_neg_fail:
.word 0xBF800000,0x40000000,0xC0400000,0xCB800000
mth_gc_test_case_tol_equal:
.word 0x37800000,0x00000000,0x00000000,0x4B800000
mth_gc_test_case_tol_below:
.word 0x377E0000,0x00000000,0x00000000,0x4B800000
mth_gc_test_case_tol_above:
.word 0x37810000,0x00000000,0x00000000,0x4B800000
mth_gc_test_case_max_g_pos:
.word 0x3F800000,0x40000000,0x40400000,0x7F7FFFFF
mth_gc_test_case_max_g_neg:
.word 0xBF800000,0x40000000,0x3F800000,0xFF7FFFFF
mth_gc_test_case_max_cancel:
.word 0x7F7FFFFF,0xFF7FFFFF,0x00000000,0x00000000
mth_gc_test_case_g_add_overflow:
.word 0x7F7FFFFF,0x00000000,0x00000000,0x7F7FFFFF
mth_gc_test_case_base_overflow:
.word 0x7F7FFFFF,0x7F7FFFFF,0x00000000,0x00000000
mth_gc_test_case_cg_overflow:
.word 0x00000000,0x00000000,0x7F7FFFFF,0x7F7FFFFF
mth_gc_test_case_base_normal:
.word 0x3F800000,0x40000000,0x40400000,0x41000000

mth_gc_test_pass_ret:
.word 0
mth_gc_test_reject_ret:
.word 0

.org 4608
mth_gc_test_pass:
.str "MTH MIRROR GAUGE CHECK PASS\n"
mth_gc_test_bad:
.str "MTH MIRROR GAUGE CHECK FAIL\n"
