; MTH canonical mirror-pair lane field I/O fixture — NaN16 only.
;
; Exercises mth_mirror_pair_lane_get / mth_mirror_pair_lane_set over the
; canonical physical profile documented in docs/MIRROR_MEMORY_LAYOUT.md:
;
;   pair id 1..32,640; base = 32768 + (id-1)*256;
;   lane 0 at +0 and lane 1 at +128;
;   lane 0 fields 0..25 residual f32, 26 relation_type u32,
;   27 confidence f32, 28 hyperedge_head u32, 29 cycle_flux f32,
;   30 generation u32, 31 flags u32;
;   lane 1 fields 0..25 residual f32; lane 1 bytes 232..255 reserved.
;
; Coverage:
;   1. Roundtrip of every typed field (26 residual slots on both lanes and
;      all six lane-0 metadata fields), with get returning the exact word.
;   2. Field non-overlap: before each set the whole 256-byte record is filled
;      with a deterministic payload + class-nibble pattern; after the set
;      every one of the 64 payload words and every class nibble is checked,
;      allowing a change only at the addressed field word.
;   3. Both lanes are exercised independently; lane-0 metadata is not readable
;      or writable through lane 1.
;   4. Reserved-byte sentinels: lane 1 bytes 232..255 are poisoned with 0xA5;
;      lane-1 fields 26..31 must reject and leave them intact, and a valid
;      lane-1 residual write must not touch them.
;   5. Boundary pair ids 1 and 32,640 are tested at their real canonical byte
;      addresses, including the last valid residual word and the 24 reserved
;      bytes that end exactly at byte 8,388,607.
;   6. Invalid ids, lanes and fields, including unsigned 0xFFFFFFFF values
;      and validation-priority combinations, reject with the documented cause
;      and mutate no byte of the record.
;   7. Class-word preservation: the record pattern assigns every class nibble
;      0..15; every successful set must retain the destination word's original
;      nibble, and every other word's nibble, unchanged.
;   8. Recovery: the complete typed-field roundtrip runs again after all
;      negative cases.
;
; The documented id/lane/field domain cannot reach the defensive cause 4
; (span overflow) or cause 5 (invalid destination class), so the fixture
; instead drives the last valid lane-1 residual at the exact end of pair
; 32,640 and verifies that the universe's final 24 reserved bytes are intact.
; Cause 4 and cause 5 remain implementation guards, not claimed test coverage.
;
; Every value is generated in-guest. There are no host-computed expected
; arrays and no floating-point arithmetic: f32 slots are transported as exact
; 32-bit payloads, which is the module's declared read/write contract.

.org 0
JMP @mth_lane_test_main
.include "../nan16/mth_mirror_pair_lane_io.nas"

.equ MTH_LANE_TEST_INVALID_COUNT 14
.equ MTH_LANE_TEST_FIELD_LIST_COUNT 11

mth_lane_test_main:
  MOVI r0,0
  MOVI r13,1

  CALL @mth_lane_test_all_fields
  CALL @mth_lane_test_reserved
  CALL @mth_lane_test_invalid
  CALL @mth_lane_test_boundary
  CALL @mth_lane_test_all_fields      ; recovery after every negative case

  LA r1,@mth_lane_test_pass
  CALL @mth_lane_test_puts
  HALT

; ---- every valid typed field, both lanes, locality and class checks ----

mth_lane_test_all_fields:
  ST r15,r0,@mth_lane_test_all_ret

  MOVI r14,0
mth_lane_test_all_lane0:
  MOVI r1,1
  MOVI r2,0
  ADD r3,r14,r0
  MOVI r4,32768
  CALL @mth_lane_test_one_field
  ADD r14,r14,r13
  MOVI r5,32
  CMP r14,r5
  JMP[LT] @mth_lane_test_all_lane0

  MOVI r14,0
mth_lane_test_all_lane1:
  MOVI r1,1
  MOVI r2,1
  ADD r3,r14,r0
  MOVI r4,32768
  CALL @mth_lane_test_one_field
  ADD r14,r14,r13
  MOVI r5,26
  CMP r14,r5
  JMP[LT] @mth_lane_test_all_lane1

  LD r15,r0,@mth_lane_test_all_ret
  RET

; r1=id, r2=lane, r3=field, r4=byte base.
; Fills the record pattern, sets a unique payload, reads it back, and scans
; all 64 words for locality + class-nibble preservation.
mth_lane_test_one_field:
  ST r15,r0,@mth_lane_test_one_ret
  ST r12,r0,@mth_lane_test_one_save12
  ST r14,r0,@mth_lane_test_one_save14
  ST r1,r0,@mth_lane_test_one_id
  ST r4,r0,@mth_lane_test_one_base
  ADD r12,r2,r0                    ; lane
  ADD r14,r3,r0                    ; field

  LD r1,r0,@mth_lane_test_one_base
  CALL @mth_lane_test_fill_pattern

  ; Read the pre-existing pattern through the getter before any set.
  MOVI r6,0
  MOVHI r6,0xA5A5
  SHL r7,r12,5
  ADD r6,r6,r7
  ADD r6,r6,r14
  ST r6,r0,@mth_lane_test_one_pre
  LD r1,r0,@mth_lane_test_one_id
  ADD r2,r12,r0
  ADD r3,r14,r0
  CALL @mth_mirror_pair_lane_get
  CMP r1,r13
  JMP[NE] @mth_lane_test_fail
  CMP r9,r0
  JMP[NE] @mth_lane_test_fail
  LD r4,r0,@mth_lane_test_one_pre
  CMP r2,r4
  JMP[NE] @mth_lane_test_fail
  CMP r10,r4
  JMP[NE] @mth_lane_test_fail

  ; payload = 0x5A5A0000 + lane*32 + field
  MOVI r4,0
  MOVHI r4,0x5A5A
  SHL r5,r12,5
  ADD r4,r4,r5
  ADD r4,r4,r14
  ST r4,r0,@mth_lane_test_one_value

  LD r1,r0,@mth_lane_test_one_id
  ADD r2,r12,r0
  ADD r3,r14,r0
  CALL @mth_mirror_pair_lane_set
  CMP r1,r13
  JMP[NE] @mth_lane_test_fail
  CMP r9,r0
  JMP[NE] @mth_lane_test_fail

  LD r1,r0,@mth_lane_test_one_id
  ADD r2,r12,r0
  ADD r3,r14,r0
  CALL @mth_mirror_pair_lane_get
  CMP r1,r13
  JMP[NE] @mth_lane_test_fail
  CMP r9,r0
  JMP[NE] @mth_lane_test_fail
  LD r4,r0,@mth_lane_test_one_value
  CMP r2,r4
  JMP[NE] @mth_lane_test_fail
  CMP r10,r4
  JMP[NE] @mth_lane_test_fail

  LD r1,r0,@mth_lane_test_one_base
  MOVI r2,64
  SHL r3,r12,5
  ADD r3,r3,r14
  LD r4,r0,@mth_lane_test_one_value
  CALL @mth_lane_test_check_words
  CMP r1,r13
  JMP[NE] @mth_lane_test_fail

  LD r12,r0,@mth_lane_test_one_save12
  LD r14,r0,@mth_lane_test_one_save14
  LD r15,r0,@mth_lane_test_one_ret
  RET

; ---- reserved lane-1 bytes and lane-1 metadata rejection ----

mth_lane_test_reserved:
  ST r15,r0,@mth_lane_test_res_ret

  MOVI r1,32768
  CALL @mth_lane_test_fill_pattern

  ; Poison the 24 reserved lane-1 bytes [232,256) with 0xA5.
  MOVI r1,33000                    ; 32768 + 232
  MOVI r2,24
  MOVI r3,0xA5
  CALL @mth_lane_test_fill_bytes

  CALL @mth_lane_test_reserved_expect_pattern

  ; Lane-1 field ids 26..31 must reject as reserved and never write.
  MOVI r14,26
mth_lane_test_reserved_loop:
  MOVI r1,1
  MOVI r2,1
  ADD r3,r14,r0
  MOVI r4,0xBEEF
  MOVHI r4,0xDEAD
  CALL @mth_mirror_pair_lane_set
  CMP r1,r0
  JMP[NE] @mth_lane_test_fail
  MOVI r5,3
  CMP r9,r5
  JMP[NE] @mth_lane_test_fail

  MOVI r1,1
  MOVI r2,1
  ADD r3,r14,r0
  CALL @mth_mirror_pair_lane_get
  CMP r1,r0
  JMP[NE] @mth_lane_test_fail
  MOVI r5,3
  CMP r9,r5
  JMP[NE] @mth_lane_test_fail
  CMP r2,r0
  JMP[NE] @mth_lane_test_fail
  CMP r10,r0
  JMP[NE] @mth_lane_test_fail

  ADD r14,r14,r13
  MOVI r5,32
  CMP r14,r5
  JMP[LT] @mth_lane_test_reserved_loop

  CALL @mth_lane_test_reserved_expect_pattern

  ; A valid lane-1 residual write next to the reserved tail must stay local.
  MOVI r1,1
  MOVI r2,1
  MOVI r3,25
  MOVI r4,0x5678
  MOVHI r4,0x1234
  CALL @mth_mirror_pair_lane_set
  CMP r1,r13
  JMP[NE] @mth_lane_test_fail
  CMP r9,r0
  JMP[NE] @mth_lane_test_fail

  MOVI r1,1
  MOVI r2,1
  MOVI r3,25
  CALL @mth_mirror_pair_lane_get
  CMP r1,r13
  JMP[NE] @mth_lane_test_fail
  MOVI r5,0x5678
  MOVHI r5,0x1234
  CMP r2,r5
  JMP[NE] @mth_lane_test_fail
  CMP r10,r5
  JMP[NE] @mth_lane_test_fail

  ; Words 0..57: target word 57 holds the new payload, all others pattern.
  MOVI r1,32768
  MOVI r2,58
  MOVI r3,57
  MOVI r4,0x5678
  MOVHI r4,0x1234
  CALL @mth_lane_test_check_words
  CMP r1,r13
  JMP[NE] @mth_lane_test_fail

  ; Reserved sentinels still 0xA5.
  MOVI r1,33000
  MOVI r2,24
  MOVI r3,0xA5
  CALL @mth_lane_test_check_bytes
  CMP r1,r13
  JMP[NE] @mth_lane_test_fail

  LD r15,r0,@mth_lane_test_res_ret
  RET

; Requires words 0..57 at pair 1 still match the pattern and the 24 reserved
; bytes remain 0xA5.
mth_lane_test_reserved_expect_pattern:
  ST r15,r0,@mth_lane_test_resexp_ret

  MOVI r1,32768
  MOVI r2,58
  MOVI r3,0xFFFF                   ; no target exception
  MOVI r4,0
  CALL @mth_lane_test_check_words
  CMP r1,r13
  JMP[NE] @mth_lane_test_fail

  MOVI r1,33000
  MOVI r2,24
  MOVI r3,0xA5
  CALL @mth_lane_test_check_bytes
  CMP r1,r13
  JMP[NE] @mth_lane_test_fail

  LD r15,r0,@mth_lane_test_resexp_ret
  RET

; ---- invalid ids, lanes, fields, priorities, and non-mutation ----

mth_lane_test_invalid:
  ST r15,r0,@mth_lane_test_inv_ret
  LA r6,@mth_lane_test_invalid_cases
  ST r6,r0,@mth_lane_test_inv_ptr
  MOVI r14,0
  ST r14,r0,@mth_lane_test_inv_i

mth_lane_test_inv_loop:
  LD r6,r0,@mth_lane_test_inv_ptr
  LD r1,r6,0
  LD r2,r6,1
  LD r3,r6,2
  LD r4,r6,3
  ST r4,r0,@mth_lane_test_inv_cause

  ; A fresh, fully class-bearing record before every rejection case.
  MOVI r1,32768
  CALL @mth_lane_test_fill_pattern

  LD r6,r0,@mth_lane_test_inv_ptr
  LD r1,r6,0
  LD r2,r6,1
  LD r3,r6,2
  MOVI r4,0xBEEF
  MOVHI r4,0xDEAD
  CALL @mth_mirror_pair_lane_set
  CMP r1,r0
  JMP[NE] @mth_lane_test_fail
  LD r5,r0,@mth_lane_test_inv_cause
  CMP r9,r5
  JMP[NE] @mth_lane_test_fail

  LD r6,r0,@mth_lane_test_inv_ptr
  LD r1,r6,0
  LD r2,r6,1
  LD r3,r6,2
  CALL @mth_mirror_pair_lane_get
  CMP r1,r0
  JMP[NE] @mth_lane_test_fail
  LD r5,r0,@mth_lane_test_inv_cause
  CMP r9,r5
  JMP[NE] @mth_lane_test_fail
  CMP r2,r0
  JMP[NE] @mth_lane_test_fail
  CMP r10,r0
  JMP[NE] @mth_lane_test_fail

  ; Rejection must leave all 64 payload words and class nibbles untouched.
  MOVI r1,32768
  MOVI r2,64
  MOVI r3,0xFFFF
  MOVI r4,0
  CALL @mth_lane_test_check_words
  CMP r1,r13
  JMP[NE] @mth_lane_test_fail

  LD r6,r0,@mth_lane_test_inv_ptr
  ADDI r6,r6,4
  ST r6,r0,@mth_lane_test_inv_ptr
  LD r14,r0,@mth_lane_test_inv_i
  ADD r14,r14,r13
  ST r14,r0,@mth_lane_test_inv_i
  MOVI r5,#MTH_LANE_TEST_INVALID_COUNT
  CMP r14,r5
  JMP[LT] @mth_lane_test_inv_loop

  LD r15,r0,@mth_lane_test_inv_ret
  RET

; ---- boundary ids 1 and 32,640 at their canonical addresses ----

mth_lane_test_boundary:
  ST r15,r0,@mth_lane_test_bound_ret

  MOVI r1,1
  MOVI r2,32768
  CALL @mth_lane_test_boundary_pair

  MOVI r1,32640
  MOVI r2,0xFF00
  MOVHI r2,0x007F                  ; 8,388,352 = 0x007FFF00
  CALL @mth_lane_test_boundary_pair

  LD r15,r0,@mth_lane_test_bound_ret
  RET

; r1=id, r2=canonical byte base.
mth_lane_test_boundary_pair:
  ST r15,r0,@mth_lane_test_bp_ret
  ST r12,r0,@mth_lane_test_bp_save12
  ST r14,r0,@mth_lane_test_bp_save14
  ST r1,r0,@mth_lane_test_bp_id
  ST r2,r0,@mth_lane_test_bp_base

  LA r6,@mth_lane_test_field_list
  ST r6,r0,@mth_lane_test_bp_ptr
  MOVI r14,0
  ST r14,r0,@mth_lane_test_bp_i

mth_lane_test_bp_loop:
  LD r6,r0,@mth_lane_test_bp_ptr
  LD r2,r6,0                       ; lane
  LD r3,r6,1                       ; field
  LD r1,r0,@mth_lane_test_bp_id
  LD r4,r0,@mth_lane_test_bp_base
  CALL @mth_lane_test_one_field

  LD r6,r0,@mth_lane_test_bp_ptr
  ADDI r6,r6,2
  ST r6,r0,@mth_lane_test_bp_ptr
  LD r14,r0,@mth_lane_test_bp_i
  ADD r14,r14,r13
  ST r14,r0,@mth_lane_test_bp_i
  MOVI r5,#MTH_LANE_TEST_FIELD_LIST_COUNT
  CMP r14,r5
  JMP[LT] @mth_lane_test_bp_loop

  ; Refill, then verify the reserved tail at the actual canonical base.
  LD r1,r0,@mth_lane_test_bp_base
  CALL @mth_lane_test_fill_pattern
  LD r1,r0,@mth_lane_test_bp_base
  ADDI r1,r1,232
  MOVI r2,24
  MOVI r3,0xA5
  CALL @mth_lane_test_fill_bytes

  CALL @mth_lane_test_bp_expect_tail

  ; Lane-1 field ids 26..31 are reserved at both boundaries.
  MOVI r14,26
mth_lane_test_bp_res_loop:
  LD r1,r0,@mth_lane_test_bp_id
  MOVI r2,1
  ADD r3,r14,r0
  MOVI r4,0xBEEF
  MOVHI r4,0xDEAD
  CALL @mth_mirror_pair_lane_set
  CMP r1,r0
  JMP[NE] @mth_lane_test_fail
  MOVI r5,3
  CMP r9,r5
  JMP[NE] @mth_lane_test_fail

  LD r1,r0,@mth_lane_test_bp_id
  MOVI r2,1
  ADD r3,r14,r0
  CALL @mth_mirror_pair_lane_get
  CMP r1,r0
  JMP[NE] @mth_lane_test_fail
  MOVI r5,3
  CMP r9,r5
  JMP[NE] @mth_lane_test_fail
  CMP r2,r0
  JMP[NE] @mth_lane_test_fail
  CMP r10,r0
  JMP[NE] @mth_lane_test_fail

  ADD r14,r14,r13
  MOVI r5,32
  CMP r14,r5
  JMP[LT] @mth_lane_test_bp_res_loop

  CALL @mth_lane_test_bp_expect_tail

  ; Last valid lane-1 residual (field 25, word 57) at this boundary.
  LD r1,r0,@mth_lane_test_bp_id
  MOVI r2,1
  MOVI r3,25
  MOVI r4,0x9ABC
  MOVHI r4,0xDEF0
  CALL @mth_mirror_pair_lane_set
  CMP r1,r13
  JMP[NE] @mth_lane_test_fail
  CMP r9,r0
  JMP[NE] @mth_lane_test_fail

  LD r1,r0,@mth_lane_test_bp_id
  MOVI r2,1
  MOVI r3,25
  CALL @mth_mirror_pair_lane_get
  CMP r1,r13
  JMP[NE] @mth_lane_test_fail
  MOVI r5,0x9ABC
  MOVHI r5,0xDEF0
  CMP r2,r5
  JMP[NE] @mth_lane_test_fail
  CMP r10,r5
  JMP[NE] @mth_lane_test_fail

  LD r1,r0,@mth_lane_test_bp_base
  MOVI r2,58
  MOVI r3,57
  MOVI r4,0x9ABC
  MOVHI r4,0xDEF0
  CALL @mth_lane_test_check_words
  CMP r1,r13
  JMP[NE] @mth_lane_test_fail

  LD r1,r0,@mth_lane_test_bp_base
  ADDI r1,r1,232
  MOVI r2,24
  MOVI r3,0xA5
  CALL @mth_lane_test_check_bytes
  CMP r1,r13
  JMP[NE] @mth_lane_test_fail

  LD r12,r0,@mth_lane_test_bp_save12
  LD r14,r0,@mth_lane_test_bp_save14
  LD r15,r0,@mth_lane_test_bp_ret
  RET

; Words 0..57 match the pattern and reserved bytes at base+232 are 0xA5.
mth_lane_test_bp_expect_tail:
  ST r15,r0,@mth_lane_test_bpt_ret

  LD r1,r0,@mth_lane_test_bp_base
  MOVI r2,58
  MOVI r3,0xFFFF
  MOVI r4,0
  CALL @mth_lane_test_check_words
  CMP r1,r13
  JMP[NE] @mth_lane_test_fail

  LD r1,r0,@mth_lane_test_bp_base
  ADDI r1,r1,232
  MOVI r2,24
  MOVI r3,0xA5
  CALL @mth_lane_test_check_bytes
  CMP r1,r13
  JMP[NE] @mth_lane_test_fail

  LD r15,r0,@mth_lane_test_bpt_ret
  RET

; ---- record pattern helpers ----

; Fill 64 words: payload 0xA5A50000+i, class nibble i&15.
; r1 = byte base.
mth_lane_test_fill_pattern:
  ST r15,r0,@mth_lane_test_fill_ret
  ST r12,r0,@mth_lane_test_fill_save12
  ST r14,r0,@mth_lane_test_fill_save14
  ADD r12,r1,r0
  MOVI r14,0
mth_lane_test_fill_loop:
  SHL r1,r14,2
  ADD r1,r1,r12
  MOVI r2,0
  MOVHI r2,0xA5A5
  ADD r2,r2,r14
  MOVI r3,15
  BOOL.8 r3,r14,r3
  CALL @mth_lane_test_put_word
  ADD r14,r14,r13
  MOVI r3,64
  CMP r14,r3
  JMP[LT] @mth_lane_test_fill_loop
  LD r12,r0,@mth_lane_test_fill_save12
  LD r14,r0,@mth_lane_test_fill_save14
  LD r15,r0,@mth_lane_test_fill_ret
  RET

; Check `count` words against the pattern, except optional target word.
; r1=byte base, r2=word count, r3=target word index or 0xFFFF,
; r4=payload expected at the target word. Returns r1=1/0.
mth_lane_test_check_words:
  ST r15,r0,@mth_lane_test_check_ret
  ST r12,r0,@mth_lane_test_check_save12
  ST r14,r0,@mth_lane_test_check_save14
  ADD r12,r1,r0
  ST r2,r0,@mth_lane_test_check_count
  ST r3,r0,@mth_lane_test_check_target
  ST r4,r0,@mth_lane_test_check_value
  MOVI r14,0
mth_lane_test_check_loop:
  SHL r1,r14,2
  ADD r1,r1,r12
  CALL @mth_lane_test_get_word
  ADD r5,r1,r0

  LD r6,r0,@mth_lane_test_check_target
  CMP r14,r6
  JMP[EQ] @mth_lane_test_check_target_word
  MOVI r2,0
  MOVHI r2,0xA5A5
  ADD r2,r2,r14
  JMP @mth_lane_test_check_payload
mth_lane_test_check_target_word:
  LD r2,r0,@mth_lane_test_check_value
mth_lane_test_check_payload:
  CMP r5,r2
  JMP[NE] @mth_lane_test_check_bad

  SHL r1,r14,2
  ADD r1,r1,r12
  CALL @mth_lane_test_get_nibble
  MOVI r3,15
  BOOL.8 r3,r14,r3
  CMP r1,r3
  JMP[NE] @mth_lane_test_check_bad

  ADD r14,r14,r13
  LD r3,r0,@mth_lane_test_check_count
  CMP r14,r3
  JMP[LT] @mth_lane_test_check_loop
  MOVI r1,1
  JMP @mth_lane_test_check_done
mth_lane_test_check_bad:
  MOVI r1,0
mth_lane_test_check_done:
  LD r12,r0,@mth_lane_test_check_save12
  LD r14,r0,@mth_lane_test_check_save14
  LD r15,r0,@mth_lane_test_check_ret
  RET

; ---- word and byte accessors ----

; r1=byte address, r2=payload, r3=class nibble.
mth_lane_test_put_word:
  SHR r1,r1,2
  STW r2,r1,r3
  RET

; r1=byte address -> r1=payload.
mth_lane_test_get_word:
  ADD r2,r1,r0
  SHR r2,r2,2
  LD r1,r2,0
  RET

; r1=byte address -> r1=class nibble or 0xFFFFFFFF.
mth_lane_test_get_nibble:
  ADD r2,r1,r0
  SHR r2,r2,2
  LDN r1,r2,0
  RET

; r1=byte address, r2=byte value.
mth_lane_test_put_byte:
  STB r2,r1,0
  RET

; r1=byte address -> r1=byte value.
mth_lane_test_get_byte:
  LDB r1,r1,0
  RET

; r1=byte base, r2=byte count, r3=value.
mth_lane_test_fill_bytes:
  ST r15,r0,@mth_lane_test_fb_ret
  ST r12,r0,@mth_lane_test_fb_save12
  ST r14,r0,@mth_lane_test_fb_save14
  ADD r12,r1,r0
  ADD r11,r2,r0                   ; byte count
  MOVI r14,0
mth_lane_test_fb_loop:
  ADD r1,r12,r14
  ADD r2,r3,r0
  CALL @mth_lane_test_put_byte
  ADD r14,r14,r13
  CMP r14,r11
  JMP[LT] @mth_lane_test_fb_loop
  LD r12,r0,@mth_lane_test_fb_save12
  LD r14,r0,@mth_lane_test_fb_save14
  LD r15,r0,@mth_lane_test_fb_ret
  RET

; r1=byte base, r2=byte count, r3=expected value. Returns r1=1/0.
mth_lane_test_check_bytes:
  ST r15,r0,@mth_lane_test_cb_ret
  ST r12,r0,@mth_lane_test_cb_save12
  ST r14,r0,@mth_lane_test_cb_save14
  ADD r12,r1,r0
  ST r2,r0,@mth_lane_test_cb_count
  ST r3,r0,@mth_lane_test_cb_value
  MOVI r14,0
mth_lane_test_cb_loop:
  ADD r1,r12,r14
  CALL @mth_lane_test_get_byte
  LD r2,r0,@mth_lane_test_cb_value
  CMP r1,r2
  JMP[NE] @mth_lane_test_cb_bad
  ADD r14,r14,r13
  LD r2,r0,@mth_lane_test_cb_count
  CMP r14,r2
  JMP[LT] @mth_lane_test_cb_loop
  MOVI r1,1
  JMP @mth_lane_test_cb_done
mth_lane_test_cb_bad:
  MOVI r1,0
mth_lane_test_cb_done:
  LD r12,r0,@mth_lane_test_cb_save12
  LD r14,r0,@mth_lane_test_cb_save14
  LD r15,r0,@mth_lane_test_cb_ret
  RET

; ---- string output ----

mth_lane_test_puts:
  MOVI r4,255
mth_lane_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_lane_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_lane_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_lane_test_puts_word

mth_lane_test_fail:
  LA r1,@mth_lane_test_bad
  CALL @mth_lane_test_puts
  HALT

; ---- static slots ----

.org 4096
mth_lane_test_all_ret:
.word 0
mth_lane_test_one_ret:
.word 0
mth_lane_test_one_save12:
.word 0
mth_lane_test_one_save14:
.word 0
mth_lane_test_one_id:
.word 0
mth_lane_test_one_base:
.word 0
mth_lane_test_one_value:
.word 0
mth_lane_test_one_pre:
.word 0
mth_lane_test_res_ret:
.word 0
mth_lane_test_resexp_ret:
.word 0
mth_lane_test_inv_ret:
.word 0
mth_lane_test_inv_ptr:
.word 0
mth_lane_test_inv_i:
.word 0
mth_lane_test_inv_cause:
.word 0
mth_lane_test_bound_ret:
.word 0
mth_lane_test_bp_ret:
.word 0
mth_lane_test_bp_save12:
.word 0
mth_lane_test_bp_save14:
.word 0
mth_lane_test_bp_id:
.word 0
mth_lane_test_bp_base:
.word 0
mth_lane_test_bp_ptr:
.word 0
mth_lane_test_bp_i:
.word 0
mth_lane_test_bpt_ret:
.word 0
mth_lane_test_fill_ret:
.word 0
mth_lane_test_fill_save12:
.word 0
mth_lane_test_fill_save14:
.word 0
mth_lane_test_check_ret:
.word 0
mth_lane_test_check_save12:
.word 0
mth_lane_test_check_save14:
.word 0
mth_lane_test_check_count:
.word 0
mth_lane_test_check_target:
.word 0
mth_lane_test_check_value:
.word 0
mth_lane_test_fb_ret:
.word 0
mth_lane_test_fb_save12:
.word 0
mth_lane_test_fb_save14:
.word 0
mth_lane_test_cb_ret:
.word 0
mth_lane_test_cb_save12:
.word 0
mth_lane_test_cb_save14:
.word 0
mth_lane_test_cb_count:
.word 0
mth_lane_test_cb_value:
.word 0

; [id, lane, field, expected cause]
mth_lane_test_invalid_cases:
.word 0,0,0,1
.word 32641,0,0,1
.word 0xFFFFFFFF,0,0,1
.word 1,2,0,2
.word 1,0xFFFFFFFF,0,2
.word 1,0,32,3
.word 1,0,0xFFFFFFFF,3
.word 1,1,26,3
.word 1,1,31,3
.word 0,9,99,1
.word 1,9,99,2
.word 1,1,99,3
.word 0xFFFFFFFF,0xFFFFFFFF,0xFFFFFFFF,1
.word 1,2,99,2

; [lane, field] representatives for both boundary records
mth_lane_test_field_list:
.word 0,0
.word 0,1
.word 0,25
.word 0,26
.word 0,27
.word 0,28
.word 0,29
.word 0,30
.word 0,31
.word 1,0
.word 1,25

.org 4700
mth_lane_test_pass:
.str "MTH MIRROR PAIR LANE IO PASS\n"
mth_lane_test_bad:
.str "MTH MIRROR PAIR LANE IO FAIL\n"
