; MTH hyperedge-incidence chain-walk fixture — NaN16 integer only.
;
; The kernel under test is the fixed five-record arena walk in
; ../nan16/mth_hyperedge_incidence_walk.nas. Arena word 2*i holds record i's
; next link and word 2*i+1 holds its hyperedge_id, so one record is eight
; payload bytes. The kernel receives arena and output addresses as payload
; byte addresses (label << 2), exactly as the fixture helpers do.
;
; Coverage:
;   1. a full five-node chain in increasing order (max_steps = 5 boundary);
;   2. a second five-node chain from head 2 with non-monotonic links,
;      including a valid link to index 0 (0 is not the null sentinel);
;   3. an empty chain (max_steps = 0): success, count 0, no output writes;
;   4. a one-node chain: success, count 1, and entries past count untouched;
;   5. invalid head bounds (5 and 0xFFFFFFFF) and invalid step bounds
;      (6 and 0xFFFFFFFF), each rejected atomically;
;   6. null (0xFFFFFFFF) and out-of-range (5) links, each rejected with the
;      output array still poisoned;
;   7. repeated-node cycle rejection for both a tail cycle (0->1->2->1) and
;      a self-loop (0->0);
;   8. arena span wrap (base + 40) rejection for two wrapping bases;
;   9. output span wrap (out + 4*max_steps) rejection for three wrapping
;      output bases.
;
; Every rejection is checked for r1 = 0, r5 = 0, the documented r9 cause, and
; an entirely untouched five-word output array plus its two guard words.
; Every success is checked for r1 = 1, r5 = count, r9 = 0, the exact id prefix,
; and poison/guard values past count. Case 1 runs again after all rejections
; as a recovery check.
;
; All data setup, expected-value generation, and checking are native NaN16
; integer operations. There are no host-computed expected arrays.

.org 0
JMP @mth_hew_test_main
.include "../nan16/mth_hyperedge_incidence_walk.nas"

mth_hew_test_main:
  MOVI r0,0
  MOVI r13,1

  CALL @mth_hew_test_case_1
  CALL @mth_hew_test_case_2
  CALL @mth_hew_test_case_3
  CALL @mth_hew_test_case_4
  CALL @mth_hew_test_case_5
  CALL @mth_hew_test_case_6
  CALL @mth_hew_test_case_7
  CALL @mth_hew_test_case_8
  CALL @mth_hew_test_case_9

  ; Recovery: the same kernel still succeeds after every rejection path.
  CALL @mth_hew_test_case_1

  MOVI r1,@mth_hew_test_pass
  CALL @mth_hew_test_puts
  HALT

; ================= Case 1: five-node increasing chain (max boundary) =======
mth_hew_test_case_1:
  ST r15,r0,@mth_hew_test_case_ret
  CALL @mth_hew_test_zero_arena

  MOVI r1,0
  MOVI r2,1
  MOVI r3,10
  CALL @mth_hew_test_set_record
  MOVI r1,1
  MOVI r2,2
  MOVI r3,11
  CALL @mth_hew_test_set_record
  MOVI r1,2
  MOVI r2,3
  MOVI r3,12
  CALL @mth_hew_test_set_record
  MOVI r1,3
  MOVI r2,4
  MOVI r3,13
  CALL @mth_hew_test_set_record
  MOVI r1,4
  MOVI r2,0xFFFF
  MOVHI r2,0xFFFF            ; terminal null is past the requested prefix
  MOVI r3,14
  CALL @mth_hew_test_set_record

  CALL @mth_hew_test_poison_out
  MOVI r1,0                  ; head = record 0
  MOVI r2,5                  ; max_steps = 5 = capacity boundary
  MOVI r3,@mth_hew_test_out
  SHL r3,r3,2
  CALL @mth_hew_test_call_walk

  CMP r1,r13
  JMP[NE] @mth_hew_test_fail_1
  MOVI r10,5
  CMP r5,r10
  JMP[NE] @mth_hew_test_fail_1
  CMP r9,r0
  JMP[NE] @mth_hew_test_fail_1
  MOVI r1,5
  MOVI r2,@mth_hew_test_exp_forward
  CALL @mth_hew_test_check_success
  CMP r1,r13
  JMP[NE] @mth_hew_test_fail_1

  LD r15,r0,@mth_hew_test_case_ret
  RET

; ================= Case 2: five-node wrapped chain from head 2 =============
mth_hew_test_case_2:
  ST r15,r0,@mth_hew_test_case_ret
  CALL @mth_hew_test_zero_arena

  MOVI r1,2
  MOVI r2,3
  MOVI r3,22
  CALL @mth_hew_test_set_record
  MOVI r1,3
  MOVI r2,4
  MOVI r3,23
  CALL @mth_hew_test_set_record
  MOVI r1,4
  MOVI r2,0
  MOVI r3,24
  CALL @mth_hew_test_set_record
  MOVI r1,0
  MOVI r2,1
  MOVI r3,20
  CALL @mth_hew_test_set_record
  MOVI r1,1
  MOVI r2,0xFFFF
  MOVHI r2,0xFFFF
  MOVI r3,21
  CALL @mth_hew_test_set_record

  CALL @mth_hew_test_poison_out
  MOVI r1,2
  MOVI r2,5
  MOVI r3,@mth_hew_test_out
  SHL r3,r3,2
  CALL @mth_hew_test_call_walk

  CMP r1,r13
  JMP[NE] @mth_hew_test_fail_2
  MOVI r10,5
  CMP r5,r10
  JMP[NE] @mth_hew_test_fail_2
  CMP r9,r0
  JMP[NE] @mth_hew_test_fail_2
  MOVI r1,5
  MOVI r2,@mth_hew_test_exp_wrapped
  CALL @mth_hew_test_check_success
  CMP r1,r13
  JMP[NE] @mth_hew_test_fail_2

  LD r15,r0,@mth_hew_test_case_ret
  RET

; ================= Case 3: empty chain =====================================
mth_hew_test_case_3:
  ST r15,r0,@mth_hew_test_case_ret
  CALL @mth_hew_test_zero_arena
  CALL @mth_hew_test_poison_out

  MOVI r1,4
  MOVI r2,0
  MOVI r3,@mth_hew_test_out
  SHL r3,r3,2
  CALL @mth_hew_test_call_walk

  CMP r1,r13
  JMP[NE] @mth_hew_test_fail_3
  CMP r5,r0
  JMP[NE] @mth_hew_test_fail_3
  CMP r9,r0
  JMP[NE] @mth_hew_test_fail_3
  MOVI r1,0
  MOVI r2,@mth_hew_test_dummy
  CALL @mth_hew_test_check_success
  CMP r1,r13
  JMP[NE] @mth_hew_test_fail_3

  LD r15,r0,@mth_hew_test_case_ret
  RET

; ================= Case 4: one node, no writes past count ==================
mth_hew_test_case_4:
  ST r15,r0,@mth_hew_test_case_ret
  CALL @mth_hew_test_zero_arena

  MOVI r1,4
  MOVI r2,0xFFFF
  MOVHI r2,0xFFFF            ; a null link after the one requested record
  MOVI r3,44
  CALL @mth_hew_test_set_record

  CALL @mth_hew_test_poison_out
  MOVI r1,4
  MOVI r2,1
  MOVI r3,@mth_hew_test_out
  SHL r3,r3,2
  CALL @mth_hew_test_call_walk

  CMP r1,r13
  JMP[NE] @mth_hew_test_fail_4
  MOVI r10,1
  CMP r5,r10
  JMP[NE] @mth_hew_test_fail_4
  CMP r9,r0
  JMP[NE] @mth_hew_test_fail_4
  MOVI r1,1
  MOVI r2,@mth_hew_test_exp_one
  CALL @mth_hew_test_check_success
  CMP r1,r13
  JMP[NE] @mth_hew_test_fail_4

  LD r15,r0,@mth_hew_test_case_ret
  RET

; ================= Case 5: invalid head and step bounds ====================
mth_hew_test_case_5:
  ST r15,r0,@mth_hew_test_case_ret
  CALL @mth_hew_test_zero_arena

  ; head = 5 (one past capacity) -> cause 1
  MOVI r1,1
  MOVI r2,5
  MOVI r3,1
  MOVI r4,@mth_hew_test_out
  SHL r4,r4,2
  CALL @mth_hew_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_hew_test_fail_5

  ; head = 0xFFFFFFFF is also invalid, even for an empty walk -> cause 1
  MOVI r1,1
  MOVI r2,0xFFFF
  MOVHI r2,0xFFFF
  MOVI r3,0
  MOVI r4,@mth_hew_test_out
  SHL r4,r4,2
  CALL @mth_hew_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_hew_test_fail_5

  ; max_steps = 6 (one past capacity) -> cause 2
  MOVI r1,2
  MOVI r2,0
  MOVI r3,6
  MOVI r4,@mth_hew_test_out
  SHL r4,r4,2
  CALL @mth_hew_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_hew_test_fail_5

  ; max_steps = 0xFFFFFFFF -> cause 2
  MOVI r1,2
  MOVI r2,0
  MOVI r3,0xFFFF
  MOVHI r3,0xFFFF
  MOVI r4,@mth_hew_test_out
  SHL r4,r4,2
  CALL @mth_hew_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_hew_test_fail_5

  LD r15,r0,@mth_hew_test_case_ret
  RET

; ================= Case 6: null and out-of-range links ====================
mth_hew_test_case_6:
  ST r15,r0,@mth_hew_test_case_ret
  CALL @mth_hew_test_zero_arena

  ; 0 -> 1 -> 2 -> 5 (out of range) -> cause 5
  MOVI r1,0
  MOVI r2,1
  MOVI r3,60
  CALL @mth_hew_test_set_record
  MOVI r1,1
  MOVI r2,2
  MOVI r3,61
  CALL @mth_hew_test_set_record
  MOVI r1,2
  MOVI r2,5
  MOVI r3,62
  CALL @mth_hew_test_set_record
  MOVI r1,5
  MOVI r2,0
  MOVI r3,5
  MOVI r4,@mth_hew_test_out
  SHL r4,r4,2
  CALL @mth_hew_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_hew_test_fail_6

  ; 0 -> 1 -> 2 -> null (0xFFFFFFFF) -> cause 5
  MOVI r1,2
  MOVI r2,0xFFFF
  MOVHI r2,0xFFFF
  MOVI r3,62
  CALL @mth_hew_test_set_record
  MOVI r1,5
  MOVI r2,0
  MOVI r3,5
  MOVI r4,@mth_hew_test_out
  SHL r4,r4,2
  CALL @mth_hew_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_hew_test_fail_6

  ; 0 -> 1 -> null before three records -> cause 5
  MOVI r1,1
  MOVI r2,0xFFFF
  MOVHI r2,0xFFFF
  MOVI r3,61
  CALL @mth_hew_test_set_record
  MOVI r1,5
  MOVI r2,0
  MOVI r3,3
  MOVI r4,@mth_hew_test_out
  SHL r4,r4,2
  CALL @mth_hew_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_hew_test_fail_6

  LD r15,r0,@mth_hew_test_case_ret
  RET

; ================= Case 7: cycle/repeat rejection =========================
mth_hew_test_case_7:
  ST r15,r0,@mth_hew_test_case_ret
  CALL @mth_hew_test_zero_arena

  ; 0 -> 1 -> 2 -> 1 is a repeated-node tail cycle -> cause 6
  MOVI r1,0
  MOVI r2,1
  MOVI r3,70
  CALL @mth_hew_test_set_record
  MOVI r1,1
  MOVI r2,2
  MOVI r3,71
  CALL @mth_hew_test_set_record
  MOVI r1,2
  MOVI r2,1
  MOVI r3,72
  CALL @mth_hew_test_set_record
  MOVI r1,6
  MOVI r2,0
  MOVI r3,5
  MOVI r4,@mth_hew_test_out
  SHL r4,r4,2
  CALL @mth_hew_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_hew_test_fail_7

  ; 0 -> 0 is an immediate self-loop -> cause 6
  CALL @mth_hew_test_zero_arena
  MOVI r1,0
  MOVI r2,0
  MOVI r3,73
  CALL @mth_hew_test_set_record
  MOVI r1,6
  MOVI r2,0
  MOVI r3,2
  MOVI r4,@mth_hew_test_out
  SHL r4,r4,2
  CALL @mth_hew_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_hew_test_fail_7

  LD r15,r0,@mth_hew_test_case_ret
  RET

; ================= Case 8: arena span wrap ================================
mth_hew_test_case_8:
  ST r15,r0,@mth_hew_test_case_ret
  CALL @mth_hew_test_zero_arena

  ; base = 0xFFFFFFD8; base + 40 = 0x00000000 -> cause 3
  MOVI r1,3
  MOVI r2,0xFFD8
  MOVHI r2,0xFFFF
  MOVI r3,0
  MOVI r4,1
  MOVI r5,@mth_hew_test_out
  SHL r5,r5,2
  CALL @mth_hew_test_expect_reject_raw
  CMP r1,r13
  JMP[NE] @mth_hew_test_fail_8

  ; base = 0xFFFFFFF8; base + 40 wraps to 0x00000020 -> cause 3
  MOVI r1,3
  MOVI r2,0xFFF8
  MOVHI r2,0xFFFF
  MOVI r3,0
  MOVI r4,1
  MOVI r5,@mth_hew_test_out
  SHL r5,r5,2
  CALL @mth_hew_test_expect_reject_raw
  CMP r1,r13
  JMP[NE] @mth_hew_test_fail_8

  LD r15,r0,@mth_hew_test_case_ret
  RET

; ================= Case 9: output span wrap ===============================
mth_hew_test_case_9:
  ST r15,r0,@mth_hew_test_case_ret
  CALL @mth_hew_test_zero_arena

  ; out = 0xFFFFFFFE; out + 4 = 0x00000002 -> cause 4
  MOVI r1,4
  MOVI r2,0
  MOVI r3,1
  MOVI r4,0xFFFE
  MOVHI r4,0xFFFF
  CALL @mth_hew_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_hew_test_fail_9

  ; out = 0xFFFFFFF0; out + 20 = 0x00000004 -> cause 4
  MOVI r1,4
  MOVI r2,0
  MOVI r3,5
  MOVI r4,0xFFF0
  MOVHI r4,0xFFFF
  CALL @mth_hew_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_hew_test_fail_9

  ; out = 0xFFFFFFFC; out + 4 = 0x00000000 -> cause 4
  MOVI r1,4
  MOVI r2,0
  MOVI r3,1
  MOVI r4,0xFFFC
  MOVHI r4,0xFFFF
  CALL @mth_hew_test_expect_reject
  CMP r1,r13
  JMP[NE] @mth_hew_test_fail_9

  LD r15,r0,@mth_hew_test_case_ret
  RET

; ================= failure reporting ======================================
mth_hew_test_fail_1:
  MOVI r6,1
  JMP @mth_hew_test_fail
mth_hew_test_fail_2:
  MOVI r6,2
  JMP @mth_hew_test_fail
mth_hew_test_fail_3:
  MOVI r6,3
  JMP @mth_hew_test_fail
mth_hew_test_fail_4:
  MOVI r6,4
  JMP @mth_hew_test_fail
mth_hew_test_fail_5:
  MOVI r6,5
  JMP @mth_hew_test_fail
mth_hew_test_fail_6:
  MOVI r6,6
  JMP @mth_hew_test_fail
mth_hew_test_fail_7:
  MOVI r6,7
  JMP @mth_hew_test_fail
mth_hew_test_fail_8:
  MOVI r6,8
  JMP @mth_hew_test_fail
mth_hew_test_fail_9:
  MOVI r6,9

mth_hew_test_fail:
  MOVI r1,@mth_hew_test_bad_prefix
  CALL @mth_hew_test_puts
  MOVI r1,48
  ADD r1,r1,r6
  PUTC r1
  MOVI r1,@mth_hew_test_nl
  CALL @mth_hew_test_puts
  HALT

; ================= helpers ================================================

; Zero all ten arena words (five eight-byte records).
mth_hew_test_zero_arena:
  MOVI r1,@mth_hew_test_arena
  MOVI r2,10
mth_hew_test_zero_loop:
  ST r0,r1,0
  ADDI r1,r1,1
  SUB r2,r2,r13
  JMP[GT] @mth_hew_test_zero_loop
  RET

; r1 = record index, r2 = next, r3 = hyperedge_id.
mth_hew_test_set_record:
  SHL r4,r1,1
  MOVI r5,@mth_hew_test_arena
  ADD r4,r4,r5
  ST r2,r4,0
  ST r3,r4,1
  RET

; Poison the five output words with 0xA5A5A5A5 and both guards with 0xDEADBEEF.
mth_hew_test_poison_out:
  MOVI r1,@mth_hew_test_out
  MOVI r2,0xA5A5
  MOVHI r2,0xA5A5
  MOVI r3,5
mth_hew_test_poison_loop:
  ST r2,r1,0
  ADDI r1,r1,1
  SUB r3,r3,r13
  JMP[GT] @mth_hew_test_poison_loop
  MOVI r1,@mth_hew_test_guard
  MOVI r2,0xBEEF
  MOVHI r2,0xDEAD
  ST r2,r1,0
  ST r2,r1,1
  RET

; r1 = head, r2 = max_steps, r3 = output byte address.
; Calls the kernel against the fixture arena.
mth_hew_test_call_walk:
  ST r15,r0,@mth_hew_test_call_ret
  ST r1,r0,@mth_hew_test_arg_head
  ST r2,r0,@mth_hew_test_arg_max
  ST r3,r0,@mth_hew_test_arg_out
  MOVI r1,@mth_hew_test_arena
  SHL r1,r1,2
  LD r2,r0,@mth_hew_test_arg_head
  LD r3,r0,@mth_hew_test_arg_max
  LD r4,r0,@mth_hew_test_arg_out
  CALL @mth_hyperedge_incidence_walk
  LD r15,r0,@mth_hew_test_call_ret
  RET

; r1 = base, r2 = head, r3 = max_steps, r4 = output byte address.
mth_hew_test_call_walk_raw:
  ST r15,r0,@mth_hew_test_call_ret
  CALL @mth_hyperedge_incidence_walk
  LD r15,r0,@mth_hew_test_call_ret
  RET

; r1 = expected cause, r2 = head, r3 = max_steps, r4 = output byte address.
; Runs the normal-arena rejection protocol and returns r1 = 1 on the expected
; atomic rejection, else r1 = 0.
mth_hew_test_expect_reject:
  ST r15,r0,@mth_hew_test_rej_ret
  ST r1,r0,@mth_hew_test_rej_cause
  ST r2,r0,@mth_hew_test_rej_head
  ST r3,r0,@mth_hew_test_rej_max
  ST r4,r0,@mth_hew_test_rej_out

  CALL @mth_hew_test_poison_out
  LD r1,r0,@mth_hew_test_rej_head
  LD r2,r0,@mth_hew_test_rej_max
  LD r3,r0,@mth_hew_test_rej_out
  CALL @mth_hew_test_call_walk

  CMP r1,r0
  JMP[NE] @mth_hew_test_rej_bad
  CMP r5,r0
  JMP[NE] @mth_hew_test_rej_bad
  LD r10,r0,@mth_hew_test_rej_cause
  CMP r9,r10
  JMP[NE] @mth_hew_test_rej_bad

  MOVI r1,0
  MOVI r2,@mth_hew_test_dummy
  CALL @mth_hew_test_check_success
  CMP r1,r13
  JMP[NE] @mth_hew_test_rej_bad

  MOVI r1,1
  LD r15,r0,@mth_hew_test_rej_ret
  RET
mth_hew_test_rej_bad:
  MOVI r1,0
  LD r15,r0,@mth_hew_test_rej_ret
  RET

; r1 = expected cause, r2 = base, r3 = head, r4 = max_steps,
; r5 = output byte address. Same protocol with an explicit arena base.
mth_hew_test_expect_reject_raw:
  ST r15,r0,@mth_hew_test_raw_ret
  ST r1,r0,@mth_hew_test_raw_cause
  ST r2,r0,@mth_hew_test_raw_base
  ST r3,r0,@mth_hew_test_raw_head
  ST r4,r0,@mth_hew_test_raw_max
  ST r5,r0,@mth_hew_test_raw_out

  CALL @mth_hew_test_poison_out
  LD r1,r0,@mth_hew_test_raw_base
  LD r2,r0,@mth_hew_test_raw_head
  LD r3,r0,@mth_hew_test_raw_max
  LD r4,r0,@mth_hew_test_raw_out
  CALL @mth_hew_test_call_walk_raw

  CMP r1,r0
  JMP[NE] @mth_hew_test_raw_bad
  CMP r5,r0
  JMP[NE] @mth_hew_test_raw_bad
  LD r10,r0,@mth_hew_test_raw_cause
  CMP r9,r10
  JMP[NE] @mth_hew_test_raw_bad

  MOVI r1,0
  MOVI r2,@mth_hew_test_dummy
  CALL @mth_hew_test_check_success
  CMP r1,r13
  JMP[NE] @mth_hew_test_raw_bad

  MOVI r1,1
  LD r15,r0,@mth_hew_test_raw_ret
  RET
mth_hew_test_raw_bad:
  MOVI r1,0
  LD r15,r0,@mth_hew_test_raw_ret
  RET

; r1 = count, r2 = expected id word array.
; Checks out[0,count) equals expected, out[count,5) is still poison, and both
; guard words are still 0xDEADBEEF. Returns r1 = 1 on success.
mth_hew_test_check_success:
  ADD r6,r1,r0               ; count
  ADD r7,r2,r0               ; expected pointer
  MOVI r8,@mth_hew_test_out
  MOVI r9,0
mth_hew_test_check_prefix:
  CMP r9,r6
  JMP[GE] @mth_hew_test_check_tail
  LD r10,r7,0
  LD r11,r8,0
  CMP r10,r11
  JMP[NE] @mth_hew_test_check_bad
  ADDI r7,r7,1
  ADDI r8,r8,1
  ADD r9,r9,r13
  JMP @mth_hew_test_check_prefix
mth_hew_test_check_tail:
  MOVI r10,5
  CMP r9,r10
  JMP[GE] @mth_hew_test_check_guard
  MOVI r11,0xA5A5
  MOVHI r11,0xA5A5
  LD r10,r8,0
  CMP r10,r11
  JMP[NE] @mth_hew_test_check_bad
  ADDI r8,r8,1
  ADD r9,r9,r13
  JMP @mth_hew_test_check_tail
mth_hew_test_check_guard:
  MOVI r8,@mth_hew_test_guard
  MOVI r11,0xBEEF
  MOVHI r11,0xDEAD
  LD r10,r8,0
  CMP r10,r11
  JMP[NE] @mth_hew_test_check_bad
  LD r10,r8,1
  CMP r10,r11
  JMP[NE] @mth_hew_test_check_bad
  MOVI r1,1
  RET
mth_hew_test_check_bad:
  MOVI r1,0
  RET

; r1 = NUL-terminated string word address; writes bytes through PUTC.
mth_hew_test_puts:
  MOVI r4,255
mth_hew_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_hew_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_hew_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_hew_test_puts_word

; ================= data ===================================================
.org 2048
mth_hew_test_arena:
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

mth_hew_test_out:
.word 0
.word 0
.word 0
.word 0
.word 0
mth_hew_test_guard:
.word 0
.word 0

mth_hew_test_exp_forward:
.word 10
.word 11
.word 12
.word 13
.word 14
mth_hew_test_exp_wrapped:
.word 22
.word 23
.word 24
.word 20
.word 21
mth_hew_test_exp_one:
.word 44
mth_hew_test_dummy:
.word 0

mth_hew_test_arg_head:
.word 0
mth_hew_test_arg_max:
.word 0
mth_hew_test_arg_out:
.word 0
mth_hew_test_call_ret:
.word 0

mth_hew_test_raw_ret:
.word 0
mth_hew_test_raw_cause:
.word 0
mth_hew_test_raw_base:
.word 0
mth_hew_test_raw_head:
.word 0
mth_hew_test_raw_max:
.word 0
mth_hew_test_raw_out:
.word 0

mth_hew_test_rej_ret:
.word 0
mth_hew_test_rej_cause:
.word 0
mth_hew_test_rej_head:
.word 0
mth_hew_test_rej_max:
.word 0
mth_hew_test_rej_out:
.word 0

mth_hew_test_case_ret:
.word 0

mth_hew_test_pass:
.str "MTH HYPEREDGE INCIDENCE WALK PASS\n"
mth_hew_test_bad_prefix:
.str "MTH HYPEREDGE INCIDENCE WALK FAIL "
mth_hew_test_nl:
.str "\n"
