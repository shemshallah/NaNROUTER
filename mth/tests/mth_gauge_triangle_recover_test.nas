; MTH Round 033 gauge-invariant triangle read/recover fixture — NaN16 only.
;
; Kernel under test: nan16/mth_gauge_triangle_recover.nas
;
; Coverage:
;   1. clean positive, negative, fractional, and exact-cancellation triangles;
;   2. a non-trivial f32 payload transported through x_0a + 0 - 0, proving
;      the four little-endian destination bytes are written in order;
;   3. strong dyadic gauge shifts g = +2^20, +2^23, and -2^23 that preserve
;      the transported F bit-for-bit, plus two non-dyadic shifts whose
;      rounded sums still preserve F exactly;
;   4. a non-dyadic shift that drifts by exactly one binary32 ULP: the exact
;      0-ULP recover check must report mismatch, the declared 1-ULP window
;      must pass, and the 0-ULP window must fail;
;   5. raw-byte corruption at each of the four payload bytes, rejected by
;      both recover entry points;
;   6. non-finite rejection for NaN, +inf, and -inf in every input position,
;      rejection priority, arithmetic-overflow result rejection, and
;      destination atomicity (the sentinel word is never changed);
;   7. boundary values: both signed zeros, the smallest and largest
;      subnormals, FLT_MAX of both signs, exact FLT_MAX cancellation, and
;      one-ULP neighbours of FLT_MAX;
;   8. a byte-addressed unaligned destination at scratch+1, proving exactly
;      four bytes are written and the neighbouring bytes are preserved, plus
;      an unaligned rejected write that leaves all scratch bytes unchanged.
;
; Every expected value is a raw binary32 word. All arithmetic is performed by
; the guest kernel; this fixture does no host math. The step cap is 2,000,000.

.org 0
JMP @mth_gtr_test_main
.include "../nan16/mth_gauge_triangle_recover.nas"

mth_gtr_test_main:
  MOVI r0,0
  MOVI r13,1

  ; ---- transport: clean and payload-order cases ----
  LA r1,@mth_gtr_case_clean_pos
  CALL @mth_gtr_test_expect_ok
  LA r1,@mth_gtr_case_clean_neg
  CALL @mth_gtr_test_expect_ok
  LA r1,@mth_gtr_case_clean_payload
  CALL @mth_gtr_test_expect_ok
  LA r1,@mth_gtr_case_clean_payload_neg
  CALL @mth_gtr_test_expect_ok
  LA r1,@mth_gtr_case_cancel_pos
  CALL @mth_gtr_test_expect_ok
  LA r1,@mth_gtr_case_cancel_neg
  CALL @mth_gtr_test_expect_ok
  LA r1,@mth_gtr_case_frac_neg
  CALL @mth_gtr_test_expect_ok
  LA r1,@mth_gtr_case_order_sensitive
  CALL @mth_gtr_test_expect_ok

  ; ---- transport: zero, subnormal, and maximum-finite boundaries ----
  LA r1,@mth_gtr_case_all_zero
  CALL @mth_gtr_test_expect_ok
  LA r1,@mth_gtr_case_signed_zero_a
  CALL @mth_gtr_test_expect_ok
  LA r1,@mth_gtr_case_signed_zero_all_neg
  CALL @mth_gtr_test_expect_ok
  LA r1,@mth_gtr_case_subnormal_min
  CALL @mth_gtr_test_expect_ok
  LA r1,@mth_gtr_case_subnormal_sum
  CALL @mth_gtr_test_expect_ok
  LA r1,@mth_gtr_case_subnormal_max
  CALL @mth_gtr_test_expect_ok
  LA r1,@mth_gtr_case_max_finite
  CALL @mth_gtr_test_expect_ok
  LA r1,@mth_gtr_case_max_finite_neg
  CALL @mth_gtr_test_expect_ok
  LA r1,@mth_gtr_case_max_cancel
  CALL @mth_gtr_test_expect_ok
  LA r1,@mth_gtr_case_max_cancel_rev
  CALL @mth_gtr_test_expect_ok
  LA r1,@mth_gtr_case_max_sub_same
  CALL @mth_gtr_test_expect_ok

  ; ---- transport: non-finite inputs, priority, and overflow ----
  LA r1,@mth_gtr_case_reject_nan_a
  CALL @mth_gtr_test_expect_reject
  LA r1,@mth_gtr_case_reject_inf_a
  CALL @mth_gtr_test_expect_reject
  LA r1,@mth_gtr_case_reject_ninf_a
  CALL @mth_gtr_test_expect_reject
  LA r1,@mth_gtr_case_reject_nan_b
  CALL @mth_gtr_test_expect_reject
  LA r1,@mth_gtr_case_reject_inf_b
  CALL @mth_gtr_test_expect_reject
  LA r1,@mth_gtr_case_reject_ninf_b
  CALL @mth_gtr_test_expect_reject
  LA r1,@mth_gtr_case_reject_nan_c
  CALL @mth_gtr_test_expect_reject
  LA r1,@mth_gtr_case_reject_inf_c
  CALL @mth_gtr_test_expect_reject
  LA r1,@mth_gtr_case_reject_ninf_c
  CALL @mth_gtr_test_expect_reject
  LA r1,@mth_gtr_case_reject_priority_a
  CALL @mth_gtr_test_expect_reject
  LA r1,@mth_gtr_case_reject_priority_b
  CALL @mth_gtr_test_expect_reject
  LA r1,@mth_gtr_case_reject_preflight_c
  CALL @mth_gtr_test_expect_reject
  LA r1,@mth_gtr_case_reject_priority_overflow
  CALL @mth_gtr_test_expect_reject
  LA r1,@mth_gtr_case_reject_overflow_add
  CALL @mth_gtr_test_expect_reject
  LA r1,@mth_gtr_case_reject_overflow_sub
  CALL @mth_gtr_test_expect_reject
  LA r1,@mth_gtr_case_reject_overflow_neg
  CALL @mth_gtr_test_expect_reject

  ; ---- recover: exact payload identity ----
  LA r1,@mth_gtr_case_rec_pass_pos
  CALL @mth_gtr_test_expect_recover_pass
  LA r1,@mth_gtr_case_rec_pass_neg
  CALL @mth_gtr_test_expect_recover_pass
  LA r1,@mth_gtr_case_rec_pass_zero
  CALL @mth_gtr_test_expect_recover_pass
  LA r1,@mth_gtr_case_rec_pass_negzero
  CALL @mth_gtr_test_expect_recover_pass
  LA r1,@mth_gtr_case_rec_pass_max
  CALL @mth_gtr_test_expect_recover_pass
  LA r1,@mth_gtr_case_rec_pass_nmax
  CALL @mth_gtr_test_expect_recover_pass
  LA r1,@mth_gtr_case_rec_pass_submin
  CALL @mth_gtr_test_expect_recover_pass
  LA r1,@mth_gtr_case_rec_pass_payload
  CALL @mth_gtr_test_expect_recover_pass

  ; ---- recover: exact mismatches and non-finite rejection ----
  LA r1,@mth_gtr_case_rec_bad_1ulp
  CALL @mth_gtr_test_expect_recover_fail
  LA r1,@mth_gtr_case_rec_bad_sign
  CALL @mth_gtr_test_expect_recover_fail
  LA r1,@mth_gtr_case_rec_bad_neg_1ulp
  CALL @mth_gtr_test_expect_recover_fail
  LA r1,@mth_gtr_case_rec_bad_signed_zero
  CALL @mth_gtr_test_expect_recover_fail
  LA r1,@mth_gtr_case_rec_bad_sub_zero
  CALL @mth_gtr_test_expect_recover_fail
  LA r1,@mth_gtr_case_rec_bad_max_1ulp
  CALL @mth_gtr_test_expect_recover_fail
  LA r1,@mth_gtr_case_rec_bad_nan_pre
  CALL @mth_gtr_test_expect_recover_fail
  LA r1,@mth_gtr_case_rec_bad_inf_pre
  CALL @mth_gtr_test_expect_recover_fail
  LA r1,@mth_gtr_case_rec_bad_ninf_pre
  CALL @mth_gtr_test_expect_recover_fail
  LA r1,@mth_gtr_case_rec_bad_nan_post
  CALL @mth_gtr_test_expect_recover_fail
  LA r1,@mth_gtr_case_rec_bad_inf_post
  CALL @mth_gtr_test_expect_recover_fail
  LA r1,@mth_gtr_case_rec_bad_ninf_post
  CALL @mth_gtr_test_expect_recover_fail
  LA r1,@mth_gtr_case_rec_bad_both_nan
  CALL @mth_gtr_test_expect_recover_fail
  LA r1,@mth_gtr_case_rec_bad_priority_pre
  CALL @mth_gtr_test_expect_recover_fail

  ; ---- declared ULP window: passing distances ----
  LA r1,@mth_gtr_case_ulp_pass_1
  CALL @mth_gtr_test_expect_ulp_pass
  LA r1,@mth_gtr_case_ulp_pass_2
  CALL @mth_gtr_test_expect_ulp_pass
  LA r1,@mth_gtr_case_ulp_pass_signed_zero
  CALL @mth_gtr_test_expect_ulp_pass
  LA r1,@mth_gtr_case_ulp_pass_sub_to_zero
  CALL @mth_gtr_test_expect_ulp_pass
  LA r1,@mth_gtr_case_ulp_pass_max_adj
  CALL @mth_gtr_test_expect_ulp_pass
  LA r1,@mth_gtr_case_ulp_pass_neg_adj
  CALL @mth_gtr_test_expect_ulp_pass
  LA r1,@mth_gtr_case_ulp_pass_negzero_to_sub
  CALL @mth_gtr_test_expect_ulp_pass
  LA r1,@mth_gtr_case_ulp_pass_huge_window
  CALL @mth_gtr_test_expect_ulp_pass
  LA r1,@mth_gtr_case_ulp_pass_same
  CALL @mth_gtr_test_expect_ulp_pass

  ; ---- declared ULP window: distances above the window ----
  LA r1,@mth_gtr_case_ulp_fail_1
  CALL @mth_gtr_test_expect_ulp_fail
  LA r1,@mth_gtr_case_ulp_fail_2
  CALL @mth_gtr_test_expect_ulp_fail
  LA r1,@mth_gtr_case_ulp_fail_sub_zero
  CALL @mth_gtr_test_expect_ulp_fail
  LA r1,@mth_gtr_case_ulp_fail_max_adj
  CALL @mth_gtr_test_expect_ulp_fail
  LA r1,@mth_gtr_case_ulp_fail_far_sign
  CALL @mth_gtr_test_expect_ulp_fail
  LA r1,@mth_gtr_case_ulp_fail_max_to_nmax
  CALL @mth_gtr_test_expect_ulp_fail
  LA r1,@mth_gtr_case_ulp_fail_zero_to_sub
  CALL @mth_gtr_test_expect_ulp_fail
  LA r1,@mth_gtr_case_ulp_fail_one_to_signed
  CALL @mth_gtr_test_expect_ulp_fail

  ; ---- declared ULP window: non-finite rejection ----
  LA r1,@mth_gtr_case_ulp_bad_pre_nan
  CALL @mth_gtr_test_expect_ulp_fail
  LA r1,@mth_gtr_case_ulp_bad_post_inf
  CALL @mth_gtr_test_expect_ulp_fail
  LA r1,@mth_gtr_case_ulp_bad_both_inf
  CALL @mth_gtr_test_expect_ulp_fail

  ; ---- end-to-end gauge transport, exact preservation ----
  LA r1,@mth_gtr_case_gauge_dyadic_2p20
  CALL @mth_gtr_test_gauge_pair
  LA r1,@mth_gtr_case_gauge_dyadic_2p23
  CALL @mth_gtr_test_gauge_pair
  LA r1,@mth_gtr_case_gauge_neg_dyadic_2p23
  CALL @mth_gtr_test_gauge_pair
  LA r1,@mth_gtr_case_gauge_non_dyadic_a
  CALL @mth_gtr_test_gauge_pair
  LA r1,@mth_gtr_case_gauge_non_dyadic_b
  CALL @mth_gtr_test_gauge_pair
  LA r1,@mth_gtr_case_gauge_identity
  CALL @mth_gtr_test_gauge_pair

  ; ---- non-dyadic drift: exact 0-ULP rejects, declared 1-ULP passes ----
  LA r1,@mth_gtr_case_gauge_drift
  CALL @mth_gtr_test_gauge_drift

  ; ---- raw-byte corruption at every payload byte ----
  LA r1,@mth_gtr_case_corrupt_byte0
  CALL @mth_gtr_test_corrupt_byte
  LA r1,@mth_gtr_case_corrupt_byte1
  CALL @mth_gtr_test_corrupt_byte
  LA r1,@mth_gtr_case_corrupt_byte2
  CALL @mth_gtr_test_corrupt_byte
  LA r1,@mth_gtr_case_corrupt_byte3
  CALL @mth_gtr_test_corrupt_byte
  LA r1,@mth_gtr_case_corrupt_payload_byte1
  CALL @mth_gtr_test_corrupt_byte

  ; ---- unaligned byte destination ----
  LA r1,@mth_gtr_case_unaligned_ok
  CALL @mth_gtr_test_unaligned_ok
  LA r1,@mth_gtr_case_unaligned_reject
  CALL @mth_gtr_test_unaligned_reject

  LA r1,@mth_gtr_test_pass
  CALL @mth_gtr_test_puts
  HALT

; ---------------------------------------------------------------------------
; Helpers.
; ---------------------------------------------------------------------------

; r1 = row word address -> copy row words 0,1,2 into a,b,c.
mth_gtr_test_load3:
  LD r2,r1,0
  ST r2,r0,@mth_gtr_test_a
  LD r2,r1,1
  ST r2,r0,@mth_gtr_test_b
  LD r2,r1,2
  ST r2,r0,@mth_gtr_test_c
  RET

; r1 = row word address -> copy row words 0,1 into pre,post.
mth_gtr_test_load2:
  LD r2,r1,0
  ST r2,r0,@mth_gtr_test_pre
  LD r2,r1,1
  ST r2,r0,@mth_gtr_test_post
  RET

; Fill the destination with a sentinel that no expected result uses.
mth_gtr_test_fill_out:
  MOVI r2,0xBEEF
  MOVHI r2,0xDEAD
  ST r2,r0,@mth_gtr_test_out
  RET

; Call the transport on the current a,b,c slots and the aligned out slot.
mth_gtr_test_call_transport:
  ST r15,r0,@mth_gtr_test_ret_call_transport
  LA r1,@mth_gtr_test_a
  SHL r1,r1,2
  LA r2,@mth_gtr_test_b
  SHL r2,r2,2
  LA r3,@mth_gtr_test_c
  SHL r3,r3,2
  LA r4,@mth_gtr_test_out
  SHL r4,r4,2
  CALL @mth_gauge_triangle_transport
  LD r15,r0,@mth_gtr_test_ret_call_transport
  RET

; Call the exact recover check on the current pre,post slots.
mth_gtr_test_call_recover:
  ST r15,r0,@mth_gtr_test_ret_call_recover
  LA r1,@mth_gtr_test_pre
  SHL r1,r1,2
  LA r2,@mth_gtr_test_post
  SHL r2,r2,2
  CALL @mth_gauge_triangle_recover
  LD r15,r0,@mth_gtr_test_ret_call_recover
  RET

; Call the ULP-window recover check with the window in the window slot.
mth_gtr_test_call_recover_ulp:
  ST r15,r0,@mth_gtr_test_ret_call_ulp
  LA r1,@mth_gtr_test_pre
  SHL r1,r1,2
  LA r2,@mth_gtr_test_post
  SHL r2,r2,2
  LD r3,r0,@mth_gtr_test_window
  CALL @mth_gauge_triangle_recover_ulp
  LD r15,r0,@mth_gtr_test_ret_call_ulp
  RET

; r1 = [a,b,c,expected]. Requires transport success, payload in r10, and the
; output word to equal the expected word.
mth_gtr_test_expect_ok:
  ST r15,r0,@mth_gtr_test_ret_ok
  LD r2,r1,3
  ST r2,r0,@mth_gtr_test_expected
  CALL @mth_gtr_test_load3
  CALL @mth_gtr_test_fill_out
  CALL @mth_gtr_test_call_transport

  CMP r1,r13
  JMP[NE] @mth_gtr_test_fail
  CMP r9,r0
  JMP[NE] @mth_gtr_test_fail
  LD r2,r0,@mth_gtr_test_expected
  CMP r10,r2
  JMP[NE] @mth_gtr_test_fail
  LD r3,r0,@mth_gtr_test_out
  CMP r3,r2
  JMP[NE] @mth_gtr_test_fail

  LD r15,r0,@mth_gtr_test_ret_ok
  RET

; r1 = [a,b,c,cause]. Requires rejection, the documented cause, r10=0, and
; the sentinel destination word unchanged.
mth_gtr_test_expect_reject:
  ST r15,r0,@mth_gtr_test_ret_reject
  LD r2,r1,3
  ST r2,r0,@mth_gtr_test_cause
  CALL @mth_gtr_test_load3
  CALL @mth_gtr_test_fill_out
  CALL @mth_gtr_test_call_transport

  CMP r1,r0
  JMP[NE] @mth_gtr_test_fail
  LD r2,r0,@mth_gtr_test_cause
  CMP r9,r2
  JMP[NE] @mth_gtr_test_fail
  CMP r10,r0
  JMP[NE] @mth_gtr_test_fail
  LD r2,r0,@mth_gtr_test_out
  MOVI r3,0xBEEF
  MOVHI r3,0xDEAD
  CMP r2,r3
  JMP[NE] @mth_gtr_test_fail

  LD r15,r0,@mth_gtr_test_ret_reject
  RET

; r1 = [pre,post]. Requires exact recover pass and r10=pre.
mth_gtr_test_expect_recover_pass:
  ST r15,r0,@mth_gtr_test_ret_rec_pass
  LD r2,r1,0
  ST r2,r0,@mth_gtr_test_expected
  CALL @mth_gtr_test_load2
  CALL @mth_gtr_test_call_recover

  CMP r1,r13
  JMP[NE] @mth_gtr_test_fail
  CMP r9,r0
  JMP[NE] @mth_gtr_test_fail
  LD r2,r0,@mth_gtr_test_expected
  CMP r10,r2
  JMP[NE] @mth_gtr_test_fail

  LD r15,r0,@mth_gtr_test_ret_rec_pass
  RET

; r1 = [pre,post,cause]. Requires exact recover rejection/mismatch.
mth_gtr_test_expect_recover_fail:
  ST r15,r0,@mth_gtr_test_ret_rec_fail
  LD r2,r1,2
  ST r2,r0,@mth_gtr_test_cause
  CALL @mth_gtr_test_load2
  CALL @mth_gtr_test_call_recover

  CMP r1,r0
  JMP[NE] @mth_gtr_test_fail
  LD r2,r0,@mth_gtr_test_cause
  CMP r9,r2
  JMP[NE] @mth_gtr_test_fail
  CMP r10,r0
  JMP[NE] @mth_gtr_test_fail

  LD r15,r0,@mth_gtr_test_ret_rec_fail
  RET

; r1 = [pre,post,window]. Requires ULP-window pass and r10=pre.
mth_gtr_test_expect_ulp_pass:
  ST r15,r0,@mth_gtr_test_ret_ulp_pass
  LD r2,r1,0
  ST r2,r0,@mth_gtr_test_expected
  LD r2,r1,2
  ST r2,r0,@mth_gtr_test_window
  CALL @mth_gtr_test_load2
  CALL @mth_gtr_test_call_recover_ulp

  CMP r1,r13
  JMP[NE] @mth_gtr_test_fail
  CMP r9,r0
  JMP[NE] @mth_gtr_test_fail
  LD r2,r0,@mth_gtr_test_expected
  CMP r10,r2
  JMP[NE] @mth_gtr_test_fail

  LD r15,r0,@mth_gtr_test_ret_ulp_pass
  RET

; r1 = [pre,post,window]. Requires either a finite distance above the window
; (cause 3) or a non-finite input cause 1/2.
mth_gtr_test_expect_ulp_fail:
  ST r15,r0,@mth_gtr_test_ret_ulp_fail
  LD r2,r1,2
  ST r2,r0,@mth_gtr_test_window
  LD r2,r1,3
  ST r2,r0,@mth_gtr_test_cause
  CALL @mth_gtr_test_load2
  CALL @mth_gtr_test_call_recover_ulp

  CMP r1,r0
  JMP[NE] @mth_gtr_test_fail
  LD r2,r0,@mth_gtr_test_cause
  CMP r9,r2
  JMP[NE] @mth_gtr_test_fail
  CMP r10,r0
  JMP[NE] @mth_gtr_test_fail

  LD r15,r0,@mth_gtr_test_ret_ulp_fail
  RET

; r1 = [a,b,c,a',b',c',expected F]. Transports both triangles and requires
; exact recovery. r14 holds the row pointer; the kernel preserves r14.
mth_gtr_test_gauge_pair:
  ST r15,r0,@mth_gtr_test_ret_gauge_pair
  ADD r14,r1,r0
  LD r2,r14,6
  ST r2,r0,@mth_gtr_test_expected

  ; pre-gauge triangle
  LD r2,r14,0
  ST r2,r0,@mth_gtr_test_a
  LD r2,r14,1
  ST r2,r0,@mth_gtr_test_b
  LD r2,r14,2
  ST r2,r0,@mth_gtr_test_c
  CALL @mth_gtr_test_fill_out
  CALL @mth_gtr_test_call_transport

  CMP r1,r13
  JMP[NE] @mth_gtr_test_fail
  CMP r9,r0
  JMP[NE] @mth_gtr_test_fail
  LD r2,r0,@mth_gtr_test_expected
  CMP r10,r2
  JMP[NE] @mth_gtr_test_fail
  LD r3,r0,@mth_gtr_test_out
  CMP r3,r2
  JMP[NE] @mth_gtr_test_fail
  ST r3,r0,@mth_gtr_test_pre

  ; post-gauge triangle
  LD r2,r14,3
  ST r2,r0,@mth_gtr_test_a
  LD r2,r14,4
  ST r2,r0,@mth_gtr_test_b
  LD r2,r14,5
  ST r2,r0,@mth_gtr_test_c
  CALL @mth_gtr_test_fill_out
  CALL @mth_gtr_test_call_transport

  CMP r1,r13
  JMP[NE] @mth_gtr_test_fail
  CMP r9,r0
  JMP[NE] @mth_gtr_test_fail
  LD r2,r0,@mth_gtr_test_expected
  CMP r10,r2
  JMP[NE] @mth_gtr_test_fail
  LD r3,r0,@mth_gtr_test_out
  CMP r3,r2
  JMP[NE] @mth_gtr_test_fail
  ST r3,r0,@mth_gtr_test_post

  ; exact recover must pass
  CALL @mth_gtr_test_call_recover
  CMP r1,r13
  JMP[NE] @mth_gtr_test_fail
  CMP r9,r0
  JMP[NE] @mth_gtr_test_fail
  LD r2,r0,@mth_gtr_test_expected
  CMP r10,r2
  JMP[NE] @mth_gtr_test_fail

  LD r15,r0,@mth_gtr_test_ret_gauge_pair
  RET

; r1 = [a,b,c,a',b',c',F_pre,F_post,window]. Transports both triangles,
; requires exact F_pre/F_post, exact recover mismatch, ULP window pass, and
; ULP window 0 mismatch.
mth_gtr_test_gauge_drift:
  ST r15,r0,@mth_gtr_test_ret_gauge_drift
  ADD r14,r1,r0
  LD r2,r14,6
  ST r2,r0,@mth_gtr_test_expected_pre
  LD r2,r14,7
  ST r2,r0,@mth_gtr_test_expected_post
  LD r2,r14,8
  ST r2,r0,@mth_gtr_test_window

  ; pre-gauge triangle
  LD r2,r14,0
  ST r2,r0,@mth_gtr_test_a
  LD r2,r14,1
  ST r2,r0,@mth_gtr_test_b
  LD r2,r14,2
  ST r2,r0,@mth_gtr_test_c
  CALL @mth_gtr_test_fill_out
  CALL @mth_gtr_test_call_transport

  CMP r1,r13
  JMP[NE] @mth_gtr_test_fail
  CMP r9,r0
  JMP[NE] @mth_gtr_test_fail
  LD r2,r0,@mth_gtr_test_expected_pre
  CMP r10,r2
  JMP[NE] @mth_gtr_test_fail
  LD r3,r0,@mth_gtr_test_out
  CMP r3,r2
  JMP[NE] @mth_gtr_test_fail
  ST r3,r0,@mth_gtr_test_pre

  ; post-gauge triangle
  LD r2,r14,3
  ST r2,r0,@mth_gtr_test_a
  LD r2,r14,4
  ST r2,r0,@mth_gtr_test_b
  LD r2,r14,5
  ST r2,r0,@mth_gtr_test_c
  CALL @mth_gtr_test_fill_out
  CALL @mth_gtr_test_call_transport

  CMP r1,r13
  JMP[NE] @mth_gtr_test_fail
  CMP r9,r0
  JMP[NE] @mth_gtr_test_fail
  LD r2,r0,@mth_gtr_test_expected_post
  CMP r10,r2
  JMP[NE] @mth_gtr_test_fail
  LD r3,r0,@mth_gtr_test_out
  CMP r3,r2
  JMP[NE] @mth_gtr_test_fail
  ST r3,r0,@mth_gtr_test_post

  ; exact 0-ULP recover must reject the one-ULP drift
  CALL @mth_gtr_test_call_recover
  CMP r1,r0
  JMP[NE] @mth_gtr_test_fail
  MOVI r2,3
  CMP r9,r2
  JMP[NE] @mth_gtr_test_fail
  CMP r10,r0
  JMP[NE] @mth_gtr_test_fail

  ; declared window 1 must pass
  CALL @mth_gtr_test_call_recover_ulp
  CMP r1,r13
  JMP[NE] @mth_gtr_test_fail
  CMP r9,r0
  JMP[NE] @mth_gtr_test_fail
  LD r2,r0,@mth_gtr_test_expected_pre
  CMP r10,r2
  JMP[NE] @mth_gtr_test_fail

  ; declared window 0 must reject the same drift
  MOVI r2,0
  ST r2,r0,@mth_gtr_test_window
  CALL @mth_gtr_test_call_recover_ulp
  CMP r1,r0
  JMP[NE] @mth_gtr_test_fail
  MOVI r2,3
  CMP r9,r2
  JMP[NE] @mth_gtr_test_fail
  CMP r10,r0
  JMP[NE] @mth_gtr_test_fail

  LD r15,r0,@mth_gtr_test_ret_gauge_drift
  RET

; r1 = [pre,post,byte_index,xor_byte]. Flips one payload byte of post, then
; requires exact recover mismatch and ULP window 0 mismatch. r14 = row.
mth_gtr_test_corrupt_byte:
  ST r15,r0,@mth_gtr_test_ret_corrupt
  ADD r14,r1,r0
  CALL @mth_gtr_test_load2

  LD r4,r14,2
  LD r5,r14,3
  LA r3,@mth_gtr_test_post
  SHL r3,r3,2
  ADD r3,r3,r4
  LDB r6,r3,0
  BOOL.6 r6,r6,r5
  STB r6,r3,0

  ; exact payload comparison must reject
  CALL @mth_gtr_test_call_recover
  CMP r1,r0
  JMP[NE] @mth_gtr_test_fail
  MOVI r2,3
  CMP r9,r2
  JMP[NE] @mth_gtr_test_fail
  CMP r10,r0
  JMP[NE] @mth_gtr_test_fail

  ; the same finite pair must be outside a 0-ULP window
  MOVI r2,0
  ST r2,r0,@mth_gtr_test_window
  CALL @mth_gtr_test_call_recover_ulp
  CMP r1,r0
  JMP[NE] @mth_gtr_test_fail
  MOVI r2,3
  CMP r9,r2
  JMP[NE] @mth_gtr_test_fail
  CMP r10,r0
  JMP[NE] @mth_gtr_test_fail

  LD r15,r0,@mth_gtr_test_ret_corrupt
  RET

; r1 = [a,b,c,expected F]. Writes to scratch byte address +1 (unaligned) and
; checks that exactly four bytes changed.
mth_gtr_test_unaligned_ok:
  ST r15,r0,@mth_gtr_test_ret_unaligned_ok
  LD r2,r1,3
  ST r2,r0,@mth_gtr_test_expected
  CALL @mth_gtr_test_load3

  LA r2,@mth_gtr_test_scratch
  MOVI r3,0xA5A5
  MOVHI r3,0xA5A5
  ST r3,r2,0
  ST r3,r2,1
  ST r3,r2,2

  LA r1,@mth_gtr_test_a
  SHL r1,r1,2
  LA r2,@mth_gtr_test_b
  SHL r2,r2,2
  LA r3,@mth_gtr_test_c
  SHL r3,r3,2
  LA r4,@mth_gtr_test_scratch
  SHL r4,r4,2
  ADDI r4,r4,1
  CALL @mth_gauge_triangle_transport

  CMP r1,r13
  JMP[NE] @mth_gtr_test_fail
  CMP r9,r0
  JMP[NE] @mth_gtr_test_fail
  LD r2,r0,@mth_gtr_test_expected
  CMP r10,r2
  JMP[NE] @mth_gtr_test_fail

  ; F = 0x40200000 -> bytes 00 00 20 40 at scratch+1..+4.
  LD r2,r0,@mth_gtr_test_scratch
  MOVI r3,0x00A5
  MOVHI r3,0x2000
  CMP r2,r3
  JMP[NE] @mth_gtr_test_fail

  LA r2,@mth_gtr_test_scratch
  LD r3,r2,1
  MOVI r4,0xA540
  MOVHI r4,0xA5A5
  CMP r3,r4
  JMP[NE] @mth_gtr_test_fail

  LD r3,r2,2
  MOVI r4,0xA5A5
  MOVHI r4,0xA5A5
  CMP r3,r4
  JMP[NE] @mth_gtr_test_fail

  LD r15,r0,@mth_gtr_test_ret_unaligned_ok
  RET

; r1 = [a,b,c,cause]. Unaligned destination with a rejected input must leave
; all three scratch words unchanged.
mth_gtr_test_unaligned_reject:
  ST r15,r0,@mth_gtr_test_ret_unaligned_reject
  LD r2,r1,3
  ST r2,r0,@mth_gtr_test_cause
  CALL @mth_gtr_test_load3

  LA r2,@mth_gtr_test_scratch
  MOVI r3,0xA5A5
  MOVHI r3,0xA5A5
  ST r3,r2,0
  ST r3,r2,1
  ST r3,r2,2

  LA r1,@mth_gtr_test_a
  SHL r1,r1,2
  LA r2,@mth_gtr_test_b
  SHL r2,r2,2
  LA r3,@mth_gtr_test_c
  SHL r3,r3,2
  LA r4,@mth_gtr_test_scratch
  SHL r4,r4,2
  ADDI r4,r4,1
  CALL @mth_gauge_triangle_transport

  CMP r1,r0
  JMP[NE] @mth_gtr_test_fail
  LD r2,r0,@mth_gtr_test_cause
  CMP r9,r2
  JMP[NE] @mth_gtr_test_fail
  CMP r10,r0
  JMP[NE] @mth_gtr_test_fail

  LA r2,@mth_gtr_test_scratch
  MOVI r3,0xA5A5
  MOVHI r3,0xA5A5
  LD r4,r2,0
  CMP r4,r3
  JMP[NE] @mth_gtr_test_fail
  LD r4,r2,1
  CMP r4,r3
  JMP[NE] @mth_gtr_test_fail
  LD r4,r2,2
  CMP r4,r3
  JMP[NE] @mth_gtr_test_fail

  LD r15,r0,@mth_gtr_test_ret_unaligned_reject
  RET

; r1 = string word address; writes NUL-terminated bytes through PUTC.
mth_gtr_test_puts:
  MOVI r4,255
mth_gtr_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_gtr_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_gtr_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_gtr_test_puts_word

mth_gtr_test_fail:
  LA r1,@mth_gtr_test_bad
  CALL @mth_gtr_test_puts
  HALT

; ---------------------------------------------------------------------------
; Data.
; ---------------------------------------------------------------------------

.org 4096
mth_gtr_test_a:
.word 0
mth_gtr_test_b:
.word 0
mth_gtr_test_c:
.word 0
mth_gtr_test_out:
.word 0
mth_gtr_test_pre:
.word 0
mth_gtr_test_post:
.word 0
mth_gtr_test_expected:
.word 0
mth_gtr_test_expected_pre:
.word 0
mth_gtr_test_expected_post:
.word 0
mth_gtr_test_window:
.word 0
mth_gtr_test_cause:
.word 0

mth_gtr_test_ret_call_transport:
.word 0
mth_gtr_test_ret_call_recover:
.word 0
mth_gtr_test_ret_call_ulp:
.word 0
mth_gtr_test_ret_ok:
.word 0
mth_gtr_test_ret_reject:
.word 0
mth_gtr_test_ret_rec_pass:
.word 0
mth_gtr_test_ret_rec_fail:
.word 0
mth_gtr_test_ret_ulp_pass:
.word 0
mth_gtr_test_ret_ulp_fail:
.word 0
mth_gtr_test_ret_gauge_pair:
.word 0
mth_gtr_test_ret_gauge_drift:
.word 0
mth_gtr_test_ret_corrupt:
.word 0
mth_gtr_test_ret_unaligned_ok:
.word 0
mth_gtr_test_ret_unaligned_reject:
.word 0

mth_gtr_test_scratch:
.word 0xA5A5A5A5,0xA5A5A5A5,0xA5A5A5A5

; ---- transport success rows: x_0a, x_ab, x_0b, expected F ----
mth_gtr_case_clean_pos:
.word 0x3F800000,0x40000000,0x3F000000,0x40200000
mth_gtr_case_clean_neg:
.word 0x3FC00000,0xC0200000,0x3F000000,0xBFC00000
mth_gtr_case_clean_payload:
.word 0x3F9E0652,0x00000000,0x00000000,0x3F9E0652
mth_gtr_case_clean_payload_neg:
.word 0xBF9E0652,0x00000000,0x00000000,0xBF9E0652
mth_gtr_case_cancel_pos:
.word 0x3F800000,0x40000000,0x40400000,0x00000000
mth_gtr_case_cancel_neg:
.word 0xBF800000,0xC0000000,0xC0400000,0x00000000
mth_gtr_case_frac_neg:
.word 0x40100000,0x3FC00000,0x40E00000,0xC0500000
; (2^24 + 1) - 1 = 16777215, while (2^24 - 1) + 1 = 2^24:
; this row fails if FADD/FSUB are reordered or reassociated.
mth_gtr_case_order_sensitive:
.word 0x4B800000,0x3F800000,0x3F800000,0x4B7FFFFF

; ---- transport boundary rows ----
mth_gtr_case_all_zero:
.word 0x00000000,0x00000000,0x00000000,0x00000000
mth_gtr_case_signed_zero_a:
.word 0x80000000,0x00000000,0x00000000,0x00000000
mth_gtr_case_signed_zero_all_neg:
.word 0x80000000,0x80000000,0x80000000,0x00000000
mth_gtr_case_subnormal_min:
.word 0x00000001,0x00000000,0x00000000,0x00000001
mth_gtr_case_subnormal_sum:
.word 0x00000001,0x00000001,0x00000000,0x00000002
mth_gtr_case_subnormal_max:
.word 0x007FFFFF,0x00000000,0x00000000,0x007FFFFF
mth_gtr_case_max_finite:
.word 0x7F7FFFFF,0x00000000,0x00000000,0x7F7FFFFF
mth_gtr_case_max_finite_neg:
.word 0xFF7FFFFF,0x00000000,0x00000000,0xFF7FFFFF
mth_gtr_case_max_cancel:
.word 0x7F7FFFFF,0xFF7FFFFF,0x00000000,0x00000000
mth_gtr_case_max_cancel_rev:
.word 0xFF7FFFFF,0x7F7FFFFF,0x00000000,0x00000000
mth_gtr_case_max_sub_same:
.word 0x7F7FFFFF,0x00000000,0x7F7FFFFF,0x00000000

; ---- transport rejection rows: x_0a, x_ab, x_0b, cause ----
mth_gtr_case_reject_nan_a:
.word 0x7FC00000,0x3F800000,0x3F800000,1
mth_gtr_case_reject_inf_a:
.word 0x7F800000,0x3F800000,0x3F800000,1
mth_gtr_case_reject_ninf_a:
.word 0xFF800000,0x3F800000,0x3F800000,1
mth_gtr_case_reject_nan_b:
.word 0x3F800000,0x7FC00001,0x3F800000,2
mth_gtr_case_reject_inf_b:
.word 0x3F800000,0x7F800000,0x3F800000,2
mth_gtr_case_reject_ninf_b:
.word 0x3F800000,0xFF800000,0x3F800000,2
mth_gtr_case_reject_nan_c:
.word 0x3F800000,0x3F800000,0x7FC00002,3
mth_gtr_case_reject_inf_c:
.word 0x3F800000,0x3F800000,0x7F800000,3
mth_gtr_case_reject_ninf_c:
.word 0x3F800000,0x3F800000,0xFF800000,3
mth_gtr_case_reject_priority_a:
.word 0x7FC00000,0x7FC00001,0xFF800000,1
mth_gtr_case_reject_priority_b:
.word 0x3F800000,0x7F800000,0x7FC00000,2
mth_gtr_case_reject_preflight_c:
.word 0x7F7FFFFF,0x7F7FFFFF,0x7FC00000,3
mth_gtr_case_reject_priority_overflow:
.word 0x7FC00000,0x7F7FFFFF,0x7F7FFFFF,1
mth_gtr_case_reject_overflow_add:
.word 0x7F7FFFFF,0x7F7FFFFF,0x00000000,4
mth_gtr_case_reject_overflow_sub:
.word 0x7F7FFFFF,0x00000000,0xFF7FFFFF,4
mth_gtr_case_reject_overflow_neg:
.word 0xFF7FFFFF,0xFF7FFFFF,0x00000000,4

; ---- recover success rows: pre-F, post-F' ----
mth_gtr_case_rec_pass_pos:
.word 0x40200000,0x40200000
mth_gtr_case_rec_pass_neg:
.word 0xBFC00000,0xBFC00000
mth_gtr_case_rec_pass_zero:
.word 0x00000000,0x00000000
mth_gtr_case_rec_pass_negzero:
.word 0x80000000,0x80000000
mth_gtr_case_rec_pass_max:
.word 0x7F7FFFFF,0x7F7FFFFF
mth_gtr_case_rec_pass_nmax:
.word 0xFF7FFFFF,0xFF7FFFFF
mth_gtr_case_rec_pass_submin:
.word 0x00000001,0x00000001
mth_gtr_case_rec_pass_payload:
.word 0x3F9E0652,0x3F9E0652

; ---- recover failure rows: pre-F, post-F', cause ----
mth_gtr_case_rec_bad_1ulp:
.word 0x40200000,0x40200001,3
mth_gtr_case_rec_bad_sign:
.word 0x40200000,0xC0200000,3
mth_gtr_case_rec_bad_neg_1ulp:
.word 0xBF800000,0xBF800001,3
mth_gtr_case_rec_bad_signed_zero:
.word 0x00000000,0x80000000,3
mth_gtr_case_rec_bad_sub_zero:
.word 0x00000001,0x00000000,3
mth_gtr_case_rec_bad_max_1ulp:
.word 0x7F7FFFFF,0x7F7FFFFE,3
mth_gtr_case_rec_bad_nan_pre:
.word 0x7FC00000,0x3F800000,1
mth_gtr_case_rec_bad_inf_pre:
.word 0x7F800000,0x3F800000,1
mth_gtr_case_rec_bad_ninf_pre:
.word 0xFF800000,0x3F800000,1
mth_gtr_case_rec_bad_nan_post:
.word 0x3F800000,0x7FC00003,2
mth_gtr_case_rec_bad_inf_post:
.word 0x3F800000,0x7F800000,2
mth_gtr_case_rec_bad_ninf_post:
.word 0x3F800000,0xFF800000,2
mth_gtr_case_rec_bad_both_nan:
.word 0x7FC00000,0x7FC00001,1
mth_gtr_case_rec_bad_priority_pre:
.word 0xFF800000,0x7FC00000,1

; ---- ULP-window success rows: pre-F, post-F', window ----
mth_gtr_case_ulp_pass_1:
.word 0x40200000,0x40200001,1
mth_gtr_case_ulp_pass_2:
.word 0x40200000,0x40200002,2
mth_gtr_case_ulp_pass_signed_zero:
.word 0x00000000,0x80000000,0
mth_gtr_case_ulp_pass_sub_to_zero:
.word 0x00000001,0x00000000,1
mth_gtr_case_ulp_pass_max_adj:
.word 0x7F7FFFFF,0x7F7FFFFE,1
mth_gtr_case_ulp_pass_neg_adj:
.word 0xBF800000,0xBF800001,1
mth_gtr_case_ulp_pass_negzero_to_sub:
.word 0x80000000,0x80000001,1
mth_gtr_case_ulp_pass_huge_window:
.word 0x7F7FFFFF,0xFF7FFFFF,0xFFFFFFFF
mth_gtr_case_ulp_pass_same:
.word 0x3F9E0652,0x3F9E0652,0

; ---- ULP-window failure rows: pre-F, post-F', window, expected cause ----
mth_gtr_case_ulp_fail_1:
.word 0x40200000,0x40200001,0,3
mth_gtr_case_ulp_fail_2:
.word 0x40200000,0x40200002,1,3
mth_gtr_case_ulp_fail_sub_zero:
.word 0x00000001,0x00000000,0,3
mth_gtr_case_ulp_fail_max_adj:
.word 0x7F7FFFFF,0x7F7FFFFE,0,3
mth_gtr_case_ulp_fail_far_sign:
.word 0xBF800000,0x3F800000,1,3
mth_gtr_case_ulp_fail_max_to_nmax:
.word 0x7F7FFFFF,0xFF7FFFFF,1,3
mth_gtr_case_ulp_fail_zero_to_sub:
.word 0x00000000,0x00000001,0,3
mth_gtr_case_ulp_fail_one_to_signed:
.word 0x80000000,0x00000001,1,3
mth_gtr_case_ulp_bad_pre_nan:
.word 0x7FC00000,0x3F800000,0,1
mth_gtr_case_ulp_bad_post_inf:
.word 0x3F800000,0x7F800000,0,2
mth_gtr_case_ulp_bad_both_inf:
.word 0xFF800000,0x7F800000,0,1

; ---- gauge-pair rows: a,b,c,a',b',c',common F ----
mth_gtr_case_gauge_dyadic_2p20:
.word 0x3FC00000,0x40100000,0x3F400000,0x4980000C,0x40100000,0x49800006,0x40400000
mth_gtr_case_gauge_dyadic_2p23:
.word 0x3FC00000,0x40100000,0x3F400000,0x4B000002,0x40100000,0x4B000001,0x40400000
mth_gtr_case_gauge_neg_dyadic_2p23:
.word 0x3FC00000,0x40100000,0x3F400000,0xCAFFFFFD,0x40100000,0xCAFFFFFE,0x40400000
mth_gtr_case_gauge_non_dyadic_a:
.word 0x3F000000,0x3F400000,0x40200000,0x3FCC0C74,0x3F400000,0x4066063A,0xBFA00000
mth_gtr_case_gauge_non_dyadic_b:
.word 0x3FE00000,0x40400000,0x3E800000,0x406A3897,0x40400000,0x400A3897,0x40900000
mth_gtr_case_gauge_identity:
.word 0x3F800000,0x40000000,0x3F000000,0x3F800000,0x40000000,0x3F000000,0x40200000

; ---- non-dyadic drift: a,b,c,a',b',c',F_pre,F_post,window ----
mth_gtr_case_gauge_drift:
.word 0x3F000000,0x40400000,0x3F800000,0x3FFF8A82,0x40400000,0x401FC541,0x40200000,0x401FFFFF,1

; ---- raw-byte corruption rows: pre, post, byte index, xor byte ----
mth_gtr_case_corrupt_byte0:
.word 0x40200000,0x40200000,0,1
mth_gtr_case_corrupt_byte1:
.word 0x40200000,0x40200000,1,1
mth_gtr_case_corrupt_byte2:
.word 0x40200000,0x40200000,2,1
mth_gtr_case_corrupt_byte3:
.word 0x40200000,0x40200000,3,1
mth_gtr_case_corrupt_payload_byte1:
.word 0xBFA00000,0xBFA00000,1,1

; ---- unaligned destination rows ----
mth_gtr_case_unaligned_ok:
.word 0x3F800000,0x40000000,0x3F000000,0x40200000
mth_gtr_case_unaligned_reject:
.word 0x7FC00000,0x40000000,0x3F000000,1

.org 4608
mth_gtr_test_pass:
.str "MTH GAUGE TRIANGLE RECOVER PASS\n"
mth_gtr_test_bad:
.str "MTH GAUGE TRIANGLE RECOVER FAIL\n"
