; MTH Round 023 reference-cycle flux fixture — NaN16 only.
;
; The kernel is exercised over the canonical byte-addressed mirror profile:
; LDB/STB address the four payload bytes of a NaN16 word little-endian, and
; every f32 operand is one 4-byte field at an explicit byte address.
;
; Coverage:
;   1. positive flux  F = (1 + 2) - 0.5 = 2.5
;   2. negative flux  F = (1 + -2) - 0.5 = -1.5
;   3. zero flux      F = (1.5 + 2.25) - 3.75 = +0.0
;   4. operation order: x_0i=1, x_ij=2^-24, x_0j=2^-24 gives
;        required  (x_0i + x_ij) - x_0j = 0x3F7FFFFF
;        alternate (x_0i - x_0j) + x_ij = 0x3F800000
;      The fixture proves the two orders differ, then requires the kernel's
;      cached field to equal the required-order result.
;   5. gauge-shift invariance over three pairs sharing head 0:
;        x01=1, x02=-2.5, x03=4.25, x12=0.75, x13=-1.5, x23=2
;      Shifting x01,x02,x03 by the same finite dyadic +8 leaves all three
;      fluxes bit-identical. A second shift by the non-dyadic +0.1 is checked
;      with an absolute tolerance.
;   6. non-finite input rejection for NaN, +inf, and -inf in each of the three
;      operand positions, including cause-priority cases.
;   7. non-finite result rejection for overflow in the FADD and FSUB positions
;      (both signs), with finite but huge operands.
;   8. rejection atomicity: before every rejection the entire 256-byte pair
;      record is poisoned with 0xA5; after rejection every byte must still be
;      0xA5 and the field at lane0+116 must remain untouched.
;   9. success locality: every success checks that bytes [0,116) and [120,256)
;      are still 0xA5 and only the four cycle_flux bytes changed.
;  10. recovery: the positive case runs again after all rejections.
;
; Values and expected results are generated in-guest. The only fixed expected
; words are scalar binary32 anchors for the four directed cases; there are no
; host-computed expected arrays. Checks use integer CMP, except the explicitly
; tolerant non-dyadic gauge check.

.org 0
JMP @mth_flux_test_main
.include "../nan16/mth_mirror_cycle_flux.nas"

mth_flux_test_main:
  MOVI r0,0
  MOVI r13,1

  CALL @mth_flux_test_case_positive
  CALL @mth_flux_test_case_negative
  CALL @mth_flux_test_case_zero
  CALL @mth_flux_test_case_order
  CALL @mth_flux_test_case_gauge_exact
  CALL @mth_flux_test_case_gauge_tolerant
  CALL @mth_flux_test_case_nonfinite_inputs
  CALL @mth_flux_test_case_nonfinite_result
  CALL @mth_flux_test_case_huge_finite
  CALL @mth_flux_test_case_positive

  LA r1,@mth_flux_test_pass
  CALL @mth_flux_test_puts
  HALT

; ---- directed cases ----

mth_flux_test_case_positive:
  ST r15,r0,@mth_flux_test_case_ret
  LA r1,@mth_flux_test_x0i
  SHL r1,r1,2
  MOVI r2,1
  MOVI r3,1
  CALL @mth_flux_test_set_ratio
  LA r1,@mth_flux_test_xij
  SHL r1,r1,2
  MOVI r2,2
  MOVI r3,1
  CALL @mth_flux_test_set_ratio
  LA r1,@mth_flux_test_x0j
  SHL r1,r1,2
  MOVI r2,1
  MOVI r3,2
  CALL @mth_flux_test_set_ratio

  CALL @mth_flux_test_run_success
  MOVI r2,0
  MOVHI r2,0x4020            ; 2.5
  CMP r1,r2
  JMP[NE] @mth_flux_test_fail
  LD r15,r0,@mth_flux_test_case_ret
  RET

mth_flux_test_case_negative:
  ST r15,r0,@mth_flux_test_case_ret
  LA r1,@mth_flux_test_x0i
  SHL r1,r1,2
  MOVI r2,1
  MOVI r3,1
  CALL @mth_flux_test_set_ratio
  LA r1,@mth_flux_test_xij
  SHL r1,r1,2
  MOVI r2,2
  SUB r2,r0,r2               ; numerator -2
  MOVI r3,1
  CALL @mth_flux_test_set_ratio
  LA r1,@mth_flux_test_x0j
  SHL r1,r1,2
  MOVI r2,1
  MOVI r3,2
  CALL @mth_flux_test_set_ratio

  CALL @mth_flux_test_run_success
  MOVI r2,0
  MOVHI r2,0xBFC0            ; -1.5
  CMP r1,r2
  JMP[NE] @mth_flux_test_fail
  LD r15,r0,@mth_flux_test_case_ret
  RET

mth_flux_test_case_zero:
  ST r15,r0,@mth_flux_test_case_ret
  LA r1,@mth_flux_test_x0i
  SHL r1,r1,2
  MOVI r2,3
  MOVI r3,2
  CALL @mth_flux_test_set_ratio
  LA r1,@mth_flux_test_xij
  SHL r1,r1,2
  MOVI r2,9
  MOVI r3,4
  CALL @mth_flux_test_set_ratio
  LA r1,@mth_flux_test_x0j
  SHL r1,r1,2
  MOVI r2,15
  MOVI r3,4
  CALL @mth_flux_test_set_ratio

  CALL @mth_flux_test_run_success
  CMP r1,r0                  ; +0.0 has payload zero
  JMP[NE] @mth_flux_test_fail
  LD r15,r0,@mth_flux_test_case_ret
  RET

mth_flux_test_case_order:
  ST r15,r0,@mth_flux_test_case_ret
  ; x_0i = 1.0
  LA r1,@mth_flux_test_x0i
  SHL r1,r1,2
  MOVI r2,1
  MOVI r3,1
  CALL @mth_flux_test_set_ratio
  ; x_ij = 2^-24 = 1 / 16777216
  LA r1,@mth_flux_test_xij
  SHL r1,r1,2
  MOVI r2,1
  MOVI r3,0
  MOVHI r3,0x0100            ; r3 = 16777216
  CALL @mth_flux_test_set_ratio
  ; x_0j = 2^-24
  LA r1,@mth_flux_test_x0j
  SHL r1,r1,2
  MOVI r2,1
  MOVI r3,0
  MOVHI r3,0x0100
  CALL @mth_flux_test_set_ratio

  ; Required order in-guest.
  LA r1,@mth_flux_test_x0i
  SHL r1,r1,2
  LA r2,@mth_flux_test_xij
  SHL r2,r2,2
  LA r3,@mth_flux_test_x0j
  SHL r3,r3,2
  CALL @mth_flux_test_expected_required
  ST r1,r0,@mth_flux_test_order_required

  ; Alternate order in-guest: (x_0i - x_0j) + x_ij.
  LA r1,@mth_flux_test_x0i
  SHL r1,r1,2
  LA r2,@mth_flux_test_xij
  SHL r2,r2,2
  LA r3,@mth_flux_test_x0j
  SHL r3,r3,2
  CALL @mth_flux_test_expected_alternate
  ST r1,r0,@mth_flux_test_order_alternate

  ; The two orders must differ for this test vector.
  MOVI r2,0xFFFF
  MOVHI r2,0x3F7F            ; r2 = 0x3F7FFFFF
  LD r3,r0,@mth_flux_test_order_required
  CMP r3,r2
  JMP[NE] @mth_flux_test_fail
  MOVI r2,0
  MOVHI r2,0x3F80            ; r2 = 1.0
  LD r3,r0,@mth_flux_test_order_alternate
  CMP r3,r2
  JMP[NE] @mth_flux_test_fail
  LD r3,r0,@mth_flux_test_order_required
  LD r4,r0,@mth_flux_test_order_alternate
  CMP r3,r4
  JMP[EQ] @mth_flux_test_fail

  ; The kernel must return the required-order word, not the alternate word.
  CALL @mth_flux_test_run_success
  LD r2,r0,@mth_flux_test_order_required
  CMP r1,r2
  JMP[NE] @mth_flux_test_fail
  LD r2,r0,@mth_flux_test_order_alternate
  CMP r1,r2
  JMP[EQ] @mth_flux_test_fail
  LD r15,r0,@mth_flux_test_case_ret
  RET

; ---- gauge-shift invariance ----

mth_flux_test_case_gauge_exact:
  ST r15,r0,@mth_flux_test_case_ret

  ; Shared head-0 values and the three non-reference pair values.
  LA r1,@mth_flux_test_g01
  SHL r1,r1,2
  MOVI r2,1
  MOVI r3,1
  CALL @mth_flux_test_set_ratio
  LA r1,@mth_flux_test_g02
  SHL r1,r1,2
  MOVI r2,5
  SUB r2,r0,r2
  MOVI r3,2
  CALL @mth_flux_test_set_ratio
  LA r1,@mth_flux_test_g03
  SHL r1,r1,2
  MOVI r2,17
  MOVI r3,4
  CALL @mth_flux_test_set_ratio
  LA r1,@mth_flux_test_g12
  SHL r1,r1,2
  MOVI r2,3
  MOVI r3,4
  CALL @mth_flux_test_set_ratio
  LA r1,@mth_flux_test_g13
  SHL r1,r1,2
  MOVI r2,3
  SUB r2,r0,r2
  MOVI r3,2
  CALL @mth_flux_test_set_ratio
  LA r1,@mth_flux_test_g23
  SHL r1,r1,2
  MOVI r2,2
  MOVI r3,1
  CALL @mth_flux_test_set_ratio

  ; Pair (1,2).
  LA r1,@mth_flux_test_g01
  SHL r1,r1,2
  LA r2,@mth_flux_test_x0i
  SHL r2,r2,2
  CALL @mth_flux_test_copy_slot
  LA r1,@mth_flux_test_g12
  SHL r1,r1,2
  LA r2,@mth_flux_test_xij
  SHL r2,r2,2
  CALL @mth_flux_test_copy_slot
  LA r1,@mth_flux_test_g02
  SHL r1,r1,2
  LA r2,@mth_flux_test_x0j
  SHL r2,r2,2
  CALL @mth_flux_test_copy_slot
  CALL @mth_flux_test_run_success
  ST r1,r0,@mth_flux_test_flux12
  MOVI r2,0
  MOVHI r2,0x4088            ; 4.25
  CMP r1,r2
  JMP[NE] @mth_flux_test_fail

  ; Pair (1,3).
  LA r1,@mth_flux_test_g01
  SHL r1,r1,2
  LA r2,@mth_flux_test_x0i
  SHL r2,r2,2
  CALL @mth_flux_test_copy_slot
  LA r1,@mth_flux_test_g13
  SHL r1,r1,2
  LA r2,@mth_flux_test_xij
  SHL r2,r2,2
  CALL @mth_flux_test_copy_slot
  LA r1,@mth_flux_test_g03
  SHL r1,r1,2
  LA r2,@mth_flux_test_x0j
  SHL r2,r2,2
  CALL @mth_flux_test_copy_slot
  CALL @mth_flux_test_run_success
  ST r1,r0,@mth_flux_test_flux13
  MOVI r2,0
  MOVHI r2,0xC098            ; -4.75
  CMP r1,r2
  JMP[NE] @mth_flux_test_fail

  ; Pair (2,3).
  LA r1,@mth_flux_test_g02
  SHL r1,r1,2
  LA r2,@mth_flux_test_x0i
  SHL r2,r2,2
  CALL @mth_flux_test_copy_slot
  LA r1,@mth_flux_test_g23
  SHL r1,r1,2
  LA r2,@mth_flux_test_xij
  SHL r2,r2,2
  CALL @mth_flux_test_copy_slot
  LA r1,@mth_flux_test_g03
  SHL r1,r1,2
  LA r2,@mth_flux_test_x0j
  SHL r2,r2,2
  CALL @mth_flux_test_copy_slot
  CALL @mth_flux_test_run_success
  ST r1,r0,@mth_flux_test_flux23
  MOVI r2,0
  MOVHI r2,0xC098            ; -4.75
  CMP r1,r2
  JMP[NE] @mth_flux_test_fail

  ; Gauge shift: every head-0 operand moves by the same finite +8.
  MOVI r2,0
  MOVHI r2,0x4100            ; 8.0
  ST r2,r0,@mth_flux_test_gauge
  LA r1,@mth_flux_test_g01
  SHL r1,r1,2
  LD r2,r0,@mth_flux_test_gauge
  CALL @mth_flux_test_shift_slot
  LA r1,@mth_flux_test_g02
  SHL r1,r1,2
  LD r2,r0,@mth_flux_test_gauge
  CALL @mth_flux_test_shift_slot
  LA r1,@mth_flux_test_g03
  SHL r1,r1,2
  LD r2,r0,@mth_flux_test_gauge
  CALL @mth_flux_test_shift_slot

  ; The shifted values must really be 9.0, 5.5, 12.25.
  LA r1,@mth_flux_test_g01
  SHL r1,r1,2
  CALL @mth_flux_test_load_f32
  MOVI r2,0
  MOVHI r2,0x4110            ; 9.0
  CMP r1,r2
  JMP[NE] @mth_flux_test_fail
  LA r1,@mth_flux_test_g02
  SHL r1,r1,2
  CALL @mth_flux_test_load_f32
  MOVI r2,0
  MOVHI r2,0x40B0            ; 5.5
  CMP r1,r2
  JMP[NE] @mth_flux_test_fail
  LA r1,@mth_flux_test_g03
  SHL r1,r1,2
  CALL @mth_flux_test_load_f32
  MOVI r2,0
  MOVHI r2,0x4144            ; 12.25
  CMP r1,r2
  JMP[NE] @mth_flux_test_fail

  ; Pair (1,2) again; flux must be bit-identical to the pre-shift value.
  LA r1,@mth_flux_test_g01
  SHL r1,r1,2
  LA r2,@mth_flux_test_x0i
  SHL r2,r2,2
  CALL @mth_flux_test_copy_slot
  LA r1,@mth_flux_test_g12
  SHL r1,r1,2
  LA r2,@mth_flux_test_xij
  SHL r2,r2,2
  CALL @mth_flux_test_copy_slot
  LA r1,@mth_flux_test_g02
  SHL r1,r1,2
  LA r2,@mth_flux_test_x0j
  SHL r2,r2,2
  CALL @mth_flux_test_copy_slot
  CALL @mth_flux_test_run_success
  LD r2,r0,@mth_flux_test_flux12
  CMP r1,r2
  JMP[NE] @mth_flux_test_fail

  ; Pair (1,3) again.
  LA r1,@mth_flux_test_g01
  SHL r1,r1,2
  LA r2,@mth_flux_test_x0i
  SHL r2,r2,2
  CALL @mth_flux_test_copy_slot
  LA r1,@mth_flux_test_g13
  SHL r1,r1,2
  LA r2,@mth_flux_test_xij
  SHL r2,r2,2
  CALL @mth_flux_test_copy_slot
  LA r1,@mth_flux_test_g03
  SHL r1,r1,2
  LA r2,@mth_flux_test_x0j
  SHL r2,r2,2
  CALL @mth_flux_test_copy_slot
  CALL @mth_flux_test_run_success
  LD r2,r0,@mth_flux_test_flux13
  CMP r1,r2
  JMP[NE] @mth_flux_test_fail

  ; Pair (2,3) again.
  LA r1,@mth_flux_test_g02
  SHL r1,r1,2
  LA r2,@mth_flux_test_x0i
  SHL r2,r2,2
  CALL @mth_flux_test_copy_slot
  LA r1,@mth_flux_test_g23
  SHL r1,r1,2
  LA r2,@mth_flux_test_xij
  SHL r2,r2,2
  CALL @mth_flux_test_copy_slot
  LA r1,@mth_flux_test_g03
  SHL r1,r1,2
  LA r2,@mth_flux_test_x0j
  SHL r2,r2,2
  CALL @mth_flux_test_copy_slot
  CALL @mth_flux_test_run_success
  LD r2,r0,@mth_flux_test_flux23
  CMP r1,r2
  JMP[NE] @mth_flux_test_fail

  LD r15,r0,@mth_flux_test_case_ret
  RET

mth_flux_test_case_gauge_tolerant:
  ST r15,r0,@mth_flux_test_case_ret

  ; Restore the head-0 values to the original dyadic pattern.
  LA r1,@mth_flux_test_g01
  SHL r1,r1,2
  MOVI r2,1
  MOVI r3,1
  CALL @mth_flux_test_set_ratio
  LA r1,@mth_flux_test_g02
  SHL r1,r1,2
  MOVI r2,5
  SUB r2,r0,r2
  MOVI r3,2
  CALL @mth_flux_test_set_ratio
  LA r1,@mth_flux_test_g03
  SHL r1,r1,2
  MOVI r2,17
  MOVI r3,4
  CALL @mth_flux_test_set_ratio

  ; Shift every head-0 value by the same finite +0.1 (rounded binary32).
  LA r1,@mth_flux_test_gshift
  SHL r1,r1,2
  MOVI r2,1
  MOVI r3,10
  CALL @mth_flux_test_set_ratio
  LA r1,@mth_flux_test_gshift
  SHL r1,r1,2
  CALL @mth_flux_test_load_f32
  ST r1,r0,@mth_flux_test_gauge

  LA r1,@mth_flux_test_g01
  SHL r1,r1,2
  LD r2,r0,@mth_flux_test_gauge
  CALL @mth_flux_test_shift_slot
  LA r1,@mth_flux_test_g02
  SHL r1,r1,2
  LD r2,r0,@mth_flux_test_gauge
  CALL @mth_flux_test_shift_slot
  LA r1,@mth_flux_test_g03
  SHL r1,r1,2
  LD r2,r0,@mth_flux_test_gauge
  CALL @mth_flux_test_shift_slot

  ; Recompute pair (1,2).
  LA r1,@mth_flux_test_g01
  SHL r1,r1,2
  LA r2,@mth_flux_test_x0i
  SHL r2,r2,2
  CALL @mth_flux_test_copy_slot
  LA r1,@mth_flux_test_g12
  SHL r1,r1,2
  LA r2,@mth_flux_test_xij
  SHL r2,r2,2
  CALL @mth_flux_test_copy_slot
  LA r1,@mth_flux_test_g02
  SHL r1,r1,2
  LA r2,@mth_flux_test_x0j
  SHL r2,r2,2
  CALL @mth_flux_test_copy_slot
  CALL @mth_flux_test_run_success

  ; |F_after - F_before| <= 2^-16.
  LD r2,r0,@mth_flux_test_flux12
  MOVI r3,0
  MOVHI r3,0x3780            ; 2^-16
  CALL @mth_flux_test_close_bits
  CMP r1,r13
  JMP[NE] @mth_flux_test_fail

  LD r15,r0,@mth_flux_test_case_ret
  RET

; ---- non-finite input rejection ----

mth_flux_test_case_nonfinite_inputs:
  ST r15,r0,@mth_flux_test_case_ret

  ; NaN in x_0i -> cause 1.
  CALL @mth_flux_test_set_base
  LA r1,@mth_flux_test_x0i
  SHL r1,r1,2
  MOVI r2,0x0123
  MOVHI r2,0x7FC0
  CALL @mth_flux_test_set_bits
  MOVI r1,1
  CALL @mth_flux_test_expect_reject

  ; +inf in x_0i -> cause 1.
  CALL @mth_flux_test_set_base
  LA r1,@mth_flux_test_x0i
  SHL r1,r1,2
  MOVI r2,0
  MOVHI r2,0x7F80
  CALL @mth_flux_test_set_bits
  MOVI r1,1
  CALL @mth_flux_test_expect_reject

  ; -inf in x_0i -> cause 1.
  CALL @mth_flux_test_set_base
  LA r1,@mth_flux_test_x0i
  SHL r1,r1,2
  MOVI r2,0
  MOVHI r2,0xFF80
  CALL @mth_flux_test_set_bits
  MOVI r1,1
  CALL @mth_flux_test_expect_reject

  ; NaN in x_ij -> cause 2.
  CALL @mth_flux_test_set_base
  LA r1,@mth_flux_test_xij
  SHL r1,r1,2
  MOVI r2,0x0456
  MOVHI r2,0x7FC0
  CALL @mth_flux_test_set_bits
  MOVI r1,2
  CALL @mth_flux_test_expect_reject

  ; +inf in x_ij -> cause 2.
  CALL @mth_flux_test_set_base
  LA r1,@mth_flux_test_xij
  SHL r1,r1,2
  MOVI r2,0
  MOVHI r2,0x7F80
  CALL @mth_flux_test_set_bits
  MOVI r1,2
  CALL @mth_flux_test_expect_reject

  ; -inf in x_ij -> cause 2.
  CALL @mth_flux_test_set_base
  LA r1,@mth_flux_test_xij
  SHL r1,r1,2
  MOVI r2,0
  MOVHI r2,0xFF80
  CALL @mth_flux_test_set_bits
  MOVI r1,2
  CALL @mth_flux_test_expect_reject

  ; NaN in x_0j -> cause 3.
  CALL @mth_flux_test_set_base
  LA r1,@mth_flux_test_x0j
  SHL r1,r1,2
  MOVI r2,0x0789
  MOVHI r2,0x7FC0
  CALL @mth_flux_test_set_bits
  MOVI r1,3
  CALL @mth_flux_test_expect_reject

  ; +inf in x_0j -> cause 3.
  CALL @mth_flux_test_set_base
  LA r1,@mth_flux_test_x0j
  SHL r1,r1,2
  MOVI r2,0
  MOVHI r2,0x7F80
  CALL @mth_flux_test_set_bits
  MOVI r1,3
  CALL @mth_flux_test_expect_reject

  ; -inf in x_0j -> cause 3.
  CALL @mth_flux_test_set_base
  LA r1,@mth_flux_test_x0j
  SHL r1,r1,2
  MOVI r2,0
  MOVHI r2,0xFF80
  CALL @mth_flux_test_set_bits
  MOVI r1,3
  CALL @mth_flux_test_expect_reject

  ; Priority: bad x_0i wins over bad x_ij and bad x_0j.
  CALL @mth_flux_test_set_base
  LA r1,@mth_flux_test_x0i
  SHL r1,r1,2
  MOVI r2,0
  MOVHI r2,0x7FC0
  CALL @mth_flux_test_set_bits
  LA r1,@mth_flux_test_xij
  SHL r1,r1,2
  MOVI r2,0
  MOVHI r2,0x7F80
  CALL @mth_flux_test_set_bits
  LA r1,@mth_flux_test_x0j
  SHL r1,r1,2
  MOVI r2,0
  MOVHI r2,0x7FC0
  CALL @mth_flux_test_set_bits
  MOVI r1,1
  CALL @mth_flux_test_expect_reject

  ; Priority: bad x_ij wins over bad x_0j when x_0i is finite.
  CALL @mth_flux_test_set_base
  LA r1,@mth_flux_test_xij
  SHL r1,r1,2
  MOVI r2,0
  MOVHI r2,0x7F80
  CALL @mth_flux_test_set_bits
  LA r1,@mth_flux_test_x0j
  SHL r1,r1,2
  MOVI r2,0
  MOVHI r2,0x7FC0
  CALL @mth_flux_test_set_bits
  MOVI r1,2
  CALL @mth_flux_test_expect_reject

  LD r15,r0,@mth_flux_test_case_ret
  RET

; ---- non-finite result rejection ----

mth_flux_test_case_nonfinite_result:
  ST r15,r0,@mth_flux_test_case_ret

  ; FADD overflow: 2^127 + 2^127 -> +inf.
  CALL @mth_flux_test_set_base
  LA r1,@mth_flux_test_x0i
  SHL r1,r1,2
  MOVI r2,0
  MOVHI r2,0x7F00            ; 2^127
  CALL @mth_flux_test_set_bits
  LA r1,@mth_flux_test_xij
  SHL r1,r1,2
  MOVI r2,0
  MOVHI r2,0x7F00
  CALL @mth_flux_test_set_bits
  LA r1,@mth_flux_test_x0j
  SHL r1,r1,2
  MOVI r2,0
  CALL @mth_flux_test_set_bits
  MOVI r1,4
  CALL @mth_flux_test_expect_reject

  ; FADD overflow in the negative direction: -2^127 + -2^127 -> -inf.
  CALL @mth_flux_test_set_base
  LA r1,@mth_flux_test_x0i
  SHL r1,r1,2
  MOVI r2,0
  MOVHI r2,0xFF00
  CALL @mth_flux_test_set_bits
  LA r1,@mth_flux_test_xij
  SHL r1,r1,2
  MOVI r2,0
  MOVHI r2,0xFF00
  CALL @mth_flux_test_set_bits
  LA r1,@mth_flux_test_x0j
  SHL r1,r1,2
  MOVI r2,0
  CALL @mth_flux_test_set_bits
  MOVI r1,4
  CALL @mth_flux_test_expect_reject

  ; FSUB overflow: (2^127 + 0) - (-2^127) -> +inf.
  CALL @mth_flux_test_set_base
  LA r1,@mth_flux_test_x0i
  SHL r1,r1,2
  MOVI r2,0
  MOVHI r2,0x7F00
  CALL @mth_flux_test_set_bits
  LA r1,@mth_flux_test_xij
  SHL r1,r1,2
  MOVI r2,0
  CALL @mth_flux_test_set_bits
  LA r1,@mth_flux_test_x0j
  SHL r1,r1,2
  MOVI r2,0
  MOVHI r2,0xFF00
  CALL @mth_flux_test_set_bits
  MOVI r1,4
  CALL @mth_flux_test_expect_reject

  LD r15,r0,@mth_flux_test_case_ret
  RET

; ---- finite huge values that cancel must still succeed ----

mth_flux_test_case_huge_finite:
  ST r15,r0,@mth_flux_test_case_ret
  CALL @mth_flux_test_set_base
  LA r1,@mth_flux_test_x0i
  SHL r1,r1,2
  MOVI r2,0
  MOVHI r2,0x7F00            ; 2^127
  CALL @mth_flux_test_set_bits
  LA r1,@mth_flux_test_xij
  SHL r1,r1,2
  MOVI r2,0
  MOVHI r2,0x7F00
  CALL @mth_flux_test_set_bits
  ; Change the sign of x_ij so the sum cancels exactly.
  LA r1,@mth_flux_test_xij
  SHL r1,r1,2
  CALL @mth_flux_test_load_f32
  MOVI r2,0
  MOVHI r2,0x8000            ; sign mask
  BOOL.6 r1,r1,r2            ; XOR sign bit
  ADD r2,r1,r0
  LA r1,@mth_flux_test_xij
  SHL r1,r1,2
  CALL @mth_flux_test_set_bits
  LA r1,@mth_flux_test_x0j
  SHL r1,r1,2
  MOVI r2,0
  CALL @mth_flux_test_set_bits

  CALL @mth_flux_test_run_success
  CMP r1,r0
  JMP[NE] @mth_flux_test_fail
  LD r15,r0,@mth_flux_test_case_ret
  RET

; ---- generic success runner ----

; Preconditions: x0i, xij, x0j hold finite f32 payloads.
; Computes the required-order expectation in-guest, poisons the record,
; calls the kernel, verifies status, the field word, and success locality.
; Returns r1 = the binary32 flux word.
mth_flux_test_run_success:
  ST r15,r0,@mth_flux_test_run_ret

  LA r1,@mth_flux_test_x0i
  SHL r1,r1,2
  LA r2,@mth_flux_test_xij
  SHL r2,r2,2
  LA r3,@mth_flux_test_x0j
  SHL r3,r3,2
  CALL @mth_flux_test_expected_required
  ST r1,r0,@mth_flux_test_expected

  LA r1,@mth_flux_test_record
  SHL r1,r1,2
  MOVI r2,256
  MOVI r3,0xA5
  CALL @mth_flux_test_fill_bytes

  LA r1,@mth_flux_test_x0i
  SHL r1,r1,2
  LA r2,@mth_flux_test_xij
  SHL r2,r2,2
  LA r3,@mth_flux_test_x0j
  SHL r3,r3,2
  LA r4,@mth_flux_test_record
  SHL r4,r4,2
  CALL @mth_mirror_cycle_flux

  CMP r1,r13
  JMP[NE] @mth_flux_test_fail
  CMP r9,r0
  JMP[NE] @mth_flux_test_fail

  LA r1,@mth_flux_test_record
  SHL r1,r1,2
  ADDI r1,r1,116
  CALL @mth_flux_test_load_f32
  LD r2,r0,@mth_flux_test_expected
  CMP r1,r2
  JMP[NE] @mth_flux_test_fail
  ST r1,r0,@mth_flux_test_last_field

  LA r1,@mth_flux_test_record
  SHL r1,r1,2
  LD r2,r0,@mth_flux_test_expected
  CALL @mth_flux_test_check_only_field
  CMP r1,r13
  JMP[NE] @mth_flux_test_fail

  LD r1,r0,@mth_flux_test_last_field
  LD r15,r0,@mth_flux_test_run_ret
  RET

; ---- rejection runner ----

; Preconditions: x0i, xij, x0j hold the test payloads.
; r1 = expected cause. Poisons the whole record, calls the kernel, and
; requires r1=0, r9=cause, and every record byte still 0xA5.
mth_flux_test_expect_reject:
  ST r15,r0,@mth_flux_test_reject_ret
  ADD r12,r1,r0

  LA r1,@mth_flux_test_record
  SHL r1,r1,2
  MOVI r2,256
  MOVI r3,0xA5
  CALL @mth_flux_test_fill_bytes

  LA r1,@mth_flux_test_x0i
  SHL r1,r1,2
  LA r2,@mth_flux_test_xij
  SHL r2,r2,2
  LA r3,@mth_flux_test_x0j
  SHL r3,r3,2
  LA r4,@mth_flux_test_record
  SHL r4,r4,2
  CALL @mth_mirror_cycle_flux

  CMP r1,r0
  JMP[NE] @mth_flux_test_fail
  CMP r9,r12
  JMP[NE] @mth_flux_test_fail

  LA r1,@mth_flux_test_record
  SHL r1,r1,2
  MOVI r2,256
  MOVI r3,0xA5
  CALL @mth_flux_test_check_poison
  CMP r1,r13
  JMP[NE] @mth_flux_test_fail

  LD r15,r0,@mth_flux_test_reject_ret
  RET

; ---- in-guest expected orders ----

; r1=x0i byte addr, r2=xij byte addr, r3=x0j byte addr
; returns r1 = (x0i + xij) - x0j
mth_flux_test_expected_required:
  ST r15,r0,@mth_flux_test_exp_ret
  ADD r14,r3,r0
  ADD r12,r2,r0
  CALL @mth_flux_test_load_f32
  ADD r5,r1,r0
  ADD r1,r12,r0
  CALL @mth_flux_test_load_f32
  ADD r6,r1,r0
  ADD r1,r14,r0
  CALL @mth_flux_test_load_f32
  ADD r8,r1,r0
  FADD r7,r5,r6
  FSUB r7,r7,r8
  ADD r1,r7,r0
  LD r15,r0,@mth_flux_test_exp_ret
  RET

; r1=x0i byte addr, r2=xij byte addr, r3=x0j byte addr
; returns r1 = (x0i - x0j) + xij
mth_flux_test_expected_alternate:
  ST r15,r0,@mth_flux_test_exp_ret
  ADD r14,r3,r0
  ADD r12,r2,r0
  CALL @mth_flux_test_load_f32
  ADD r5,r1,r0
  ADD r1,r12,r0
  CALL @mth_flux_test_load_f32
  ADD r6,r1,r0
  ADD r1,r14,r0
  CALL @mth_flux_test_load_f32
  ADD r8,r1,r0
  FSUB r7,r5,r8
  FADD r7,r7,r6
  ADD r1,r7,r0
  LD r15,r0,@mth_flux_test_exp_ret
  RET

; ---- in-guest field generation and checks ----

; r1 = byte address, r2 = integer numerator, r3 = integer denominator.
; Stores the rounded binary32 quotient numerator/denominator.
mth_flux_test_set_ratio:
  ST r15,r0,@mth_flux_test_ratio_ret
  CVTIF r4,r2
  CVTIF r5,r3
  FDIV r6,r4,r5
  ADD r2,r6,r0
  CALL @mth_flux_test_store_f32
  LD r15,r0,@mth_flux_test_ratio_ret
  RET

; r1 = byte address, r2 = raw binary32 payload bits.
mth_flux_test_set_bits:
  JMP @mth_flux_test_store_f32

; r1 = source byte address, r2 = destination byte address.
mth_flux_test_copy_slot:
  ST r15,r0,@mth_flux_test_copy_ret
  ADD r12,r2,r0
  CALL @mth_flux_test_load_f32
  ADD r2,r1,r0
  ADD r1,r12,r0
  CALL @mth_flux_test_store_f32
  LD r15,r0,@mth_flux_test_copy_ret
  RET

; r1 = byte address, r2 = finite binary32 shift. slot += shift.
mth_flux_test_shift_slot:
  ST r15,r0,@mth_flux_test_shift_ret
  ADD r14,r1,r0
  ADD r12,r2,r0
  CALL @mth_flux_test_load_f32
  FADD r1,r1,r12
  ADD r2,r1,r0
  ADD r1,r14,r0
  CALL @mth_flux_test_store_f32
  LD r15,r0,@mth_flux_test_shift_ret
  RET

; r1 = byte address, r2 = payload bits. Writes four little-endian bytes.
mth_flux_test_store_f32:
  STB r2,r1,0
  SHR r3,r2,8
  STB r3,r1,1
  SHR r3,r3,8
  STB r3,r1,2
  SHR r3,r3,8
  STB r3,r1,3
  RET

; r1 = byte address -> r1 = payload bits.
mth_flux_test_load_f32:
  ADD r2,r1,r0
  LDB r1,r2,0
  LDB r3,r2,1
  SHL r3,r3,8
  BOOL.14 r1,r1,r3
  LDB r3,r2,2
  SHL r3,r3,16
  BOOL.14 r1,r1,r3
  LDB r3,r2,3
  SHL r3,r3,24
  BOOL.14 r1,r1,r3
  RET

; r1 = byte base, r2 = byte count, r3 = byte value.
mth_flux_test_fill_bytes:
  MOVI r4,0
mth_flux_test_fill_loop:
  ADD r5,r1,r4
  STB r3,r5,0
  ADD r4,r4,r13
  CMP r4,r2
  JMP[LT] @mth_flux_test_fill_loop
  RET

; r1 = byte base, r2 = byte count, r3 = expected byte.
; returns r1=1 iff every byte matches, else r1=0.
mth_flux_test_check_poison:
  MOVI r4,0
mth_flux_test_poison_loop:
  ADD r5,r1,r4
  LDB r5,r5,0
  CMP r5,r3
  JMP[NE] @mth_flux_test_poison_bad
  ADD r4,r4,r13
  CMP r4,r2
  JMP[LT] @mth_flux_test_poison_loop
  MOVI r1,1
  RET
mth_flux_test_poison_bad:
  MOVI r1,0
  RET

; r1 = record byte base, r2 = expected flux bits.
; Requires bytes [0,116) and [120,256) = 0xA5 and bytes [116,120) = r2.
; returns r1=1 on success.
mth_flux_test_check_only_field:
  ST r15,r0,@mth_flux_test_field_ret
  ADD r14,r1,r0
  ADD r12,r2,r0
  MOVI r4,0
  MOVI r3,0xA5
mth_flux_test_field_loop:
  MOVI r6,116
  CMP r4,r6
  JMP[LT] @mth_flux_test_field_check
  MOVI r6,120
  CMP r4,r6
  JMP[LT] @mth_flux_test_field_skip
mth_flux_test_field_check:
  ADD r5,r14,r4
  LDB r5,r5,0
  CMP r5,r3
  JMP[NE] @mth_flux_test_field_bad
mth_flux_test_field_skip:
  ADD r4,r4,r13
  MOVI r6,256
  CMP r4,r6
  JMP[LT] @mth_flux_test_field_loop
  ADDI r1,r14,116
  CALL @mth_flux_test_load_f32
  CMP r1,r12
  JMP[NE] @mth_flux_test_field_bad
  MOVI r1,1
  LD r15,r0,@mth_flux_test_field_ret
  RET
mth_flux_test_field_bad:
  MOVI r1,0
  LD r15,r0,@mth_flux_test_field_ret
  RET

; r1=a bits, r2=b bits, r3=tolerance bits.
; returns r1=1 iff |a-b| <= tolerance and the difference is finite.
mth_flux_test_close_bits:
  FSUB r4,r1,r2
  MOVI r5,0xFFFF
  MOVHI r5,0x7FFF            ; abs mask 0x7FFFFFFF
  BOOL.8 r4,r4,r5
  MOVI r6,0
  MOVHI r6,0x7F80            ; exponent mask
  BOOL.8 r7,r4,r6
  CMP r7,r6
  JMP[EQ] @mth_flux_test_close_bad
  FCMP r4,r3
  MOVI r1,0
  RET[GT]
  MOVI r1,1
  RET
mth_flux_test_close_bad:
  MOVI r1,0
  RET

; ---- base payloads for rejection cases ----

mth_flux_test_set_base:
  ST r15,r0,@mth_flux_test_base_ret
  LA r1,@mth_flux_test_x0i
  SHL r1,r1,2
  MOVI r2,1
  MOVI r3,1
  CALL @mth_flux_test_set_ratio
  LA r1,@mth_flux_test_xij
  SHL r1,r1,2
  MOVI r2,2
  MOVI r3,1
  CALL @mth_flux_test_set_ratio
  LA r1,@mth_flux_test_x0j
  SHL r1,r1,2
  MOVI r2,1
  MOVI r3,2
  CALL @mth_flux_test_set_ratio
  LD r15,r0,@mth_flux_test_base_ret
  RET

; ---- string output ----

; r1=string word address; writes NUL-terminated bytes through PUTC.
mth_flux_test_puts:
  MOVI r4,255
mth_flux_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_flux_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_flux_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_flux_test_puts_word

mth_flux_test_fail:
  LA r1,@mth_flux_test_bad
  CALL @mth_flux_test_puts
  HALT

; ---- data ----

.org 4096
mth_flux_test_x0i:
.word 0
mth_flux_test_xij:
.word 0
mth_flux_test_x0j:
.word 0
mth_flux_test_g01:
.word 0
mth_flux_test_g02:
.word 0
mth_flux_test_g03:
.word 0
mth_flux_test_g12:
.word 0
mth_flux_test_g13:
.word 0
mth_flux_test_g23:
.word 0
mth_flux_test_gshift:
.word 0
mth_flux_test_flux12:
.word 0
mth_flux_test_flux13:
.word 0
mth_flux_test_flux23:
.word 0
mth_flux_test_order_required:
.word 0
mth_flux_test_order_alternate:
.word 0
mth_flux_test_expected:
.word 0
mth_flux_test_last_field:
.word 0
mth_flux_test_gauge:
.word 0
mth_flux_test_case_ret:
.word 0
mth_flux_test_run_ret:
.word 0
mth_flux_test_reject_ret:
.word 0
mth_flux_test_exp_ret:
.word 0
mth_flux_test_ratio_ret:
.word 0
mth_flux_test_copy_ret:
.word 0
mth_flux_test_shift_ret:
.word 0
mth_flux_test_field_ret:
.word 0
mth_flux_test_base_ret:
.word 0

; 256-byte pair record: lane 0 [0,128), lane 1 [128,256).
.org 4200
mth_flux_test_record:
.org 4264

mth_flux_test_pass:
.str "MTH MIRROR CYCLE FLUX PASS\n"
mth_flux_test_bad:
.str "MTH MIRROR CYCLE FLUX FAIL\n"
