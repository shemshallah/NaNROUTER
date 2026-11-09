; MTH 24-byte definition-slot I/O fixture — NaN16 only.
;
; Exercises mth_definition_slot_store / mth_definition_slot_load over the
; canonical mirror-memory/v1 pair records:
;
;   pair id 1..32,640; base = 32768 + (id-1)*256;
;   lane 0 at +0, lane 1 at +128;
;   slot = lane 1 bytes 104..127 = record bytes 232..255
;        = absolute [base+232, base+256);
;   guard = lane-0 generation u32 at record byte 120 (read-only).
;
; Coverage:
;   1. First pair (id 1), its neighbour (id 2), the penultimate pair
;      (id 32,639), and the last pair (id 32,640). The last slot ends exactly
;      at byte 8,388,607 and the next record begins at byte 8,388,608.
;   2. Two exact 24-byte payloads per pair: bytes 0x00..0x17 and bytes
;      0xE8..0xFF. Store/load must round-trip all 24 bytes and no more.
;   3. Poison isolation: every record is filled with a deterministic byte
;      pattern before each operation. A successful store may change only
;      record bytes 232..255; store must leave lane-0 cycle_flux (116..119),
;      generation (120..123), flags (124..127), lane-1 residuals (128..231),
;      and the whole following pair record intact. Load must change only the
;      first 24 destination bytes.
;   4. Guard: the u32 at record byte 120 must equal the caller's expected
;      generation. Wrong guards reject with cause 3 and mutate nothing. A
;      generation rotation then checks that the slot persists, the old guard
;      is refused, and the new guard is accepted; the guard word is never
;      rewritten by store or load.
;   5. Invalid ids (0, 32,641, 0xFFFFFFFF), lengths (0, 23, 25, 0xFFFFFFFF),
;      wrong guards, wrapped/out-of-universe source or destination spans, and
;      validation-priority combinations. Every rejection must leave the
;      record, the slot, the destination, and the following record untouched.
;   6. Recovery: the full boundary/payload set runs again after all negative
;      cases.
;
; The fixture uses only guest-generated values. There is no host-computed
; expected array and no floating-point arithmetic; the slot is opaque bytes.
; The byte pattern helper computes each expected value in-guest, so a wrong
; surrounding byte or a cross-record write fails the fixture.
;
; Limitations: this is a fixture, not a proof. It deliberately writes the
; canonical v1 lane-1 reserved tail, so those records no longer satisfy the
; strict v1 "reserved must be zero" invariant. It also relies on STB's class
; normalization (class 10) and does not test concurrent writers.

.org 0
JMP @mth_def_test_main
.include "../nan16/mth_definition_slot_io.nas"

.equ MTH_DEF_TEST_INVALID_COUNT 14
.equ MTH_DEF_TEST_PAIR1_BASE     32768
.equ MTH_DEF_TEST_PAIR1_GEN_WORD 32888
.equ MTH_DEF_TEST_GEN1_LOW       0x3344
.equ MTH_DEF_TEST_GEN1_HIGH      0x1122
.equ MTH_DEF_TEST_GEN2_LOW       0xBBCC
.equ MTH_DEF_TEST_GEN2_HIGH      0x99AA

mth_def_test_main:
  MOVI r0,0
  MOVI r13,1
  MOVI r1,0x30
  ST r1,r0,@mth_def_test_stage

  LA r1,@mth_def_test_src
  SHL r1,r1,2
  ST r1,r0,@mth_def_test_src_addr
  LA r1,@mth_def_test_dst
  SHL r1,r1,2
  ST r1,r0,@mth_def_test_dst_addr

  MOVI r1,0x31
  ST r1,r0,@mth_def_test_stage
  CALL @mth_def_test_boundaries
  MOVI r1,0x32
  ST r1,r0,@mth_def_test_stage
  CALL @mth_def_test_guard_rotation
  MOVI r1,0x33
  ST r1,r0,@mth_def_test_stage
  CALL @mth_def_test_invalid
  MOVI r1,0x34
  ST r1,r0,@mth_def_test_stage
  CALL @mth_def_test_boundaries       ; recovery after every negative case
  MOVI r1,0x35
  ST r1,r0,@mth_def_test_stage

  LA r1,@mth_def_test_pass
  CALL @mth_def_test_puts
  HALT

; ---- canonical first/second/penultimate/last pair boundaries ----

mth_def_test_boundaries:
  ST r15,r0,@mth_def_test_bound_ret

  ; id 1, base 32,768, gen 0x11223344, next record present
  MOVI r1,1
  MOVI r2,32768
  MOVI r3,#MTH_DEF_TEST_GEN1_LOW
  MOVHI r3,#MTH_DEF_TEST_GEN1_HIGH
  MOVI r4,1
  CALL @mth_def_test_one_pair

  ; id 2, base 33,024, gen 0x22334455, next record present
  MOVI r1,2
  MOVI r2,0x8100
  MOVI r3,0x4455
  MOVHI r3,0x2233
  MOVI r4,1
  CALL @mth_def_test_one_pair

  ; id 32,639, base 0x007FFE00, gen 0x33445566, next is the last pair
  MOVI r1,32639
  MOVI r2,0xFE00
  MOVHI r2,0x007F
  MOVI r3,0x5566
  MOVHI r3,0x3344
  MOVI r4,1
  CALL @mth_def_test_one_pair

  ; id 32,640, base 0x007FFF00, gen 0x44556677, slot ends at 0x00800000
  MOVI r1,32640
  MOVI r2,0xFF00
  MOVHI r2,0x007F
  MOVI r3,0x6677
  MOVHI r3,0x4455
  MOVI r4,0
  CALL @mth_def_test_one_pair

  LD r15,r0,@mth_def_test_bound_ret
  RET

; r1=id, r2=canonical base, r3=guard generation, r4=1 if the next record is
; in-universe. Fills this record and (optionally) the next record with poison,
; then exercises store/load of both 24-byte payloads.
mth_def_test_one_pair:
  ST r15,r0,@mth_def_test_op_ret
  ST r1,r0,@mth_def_test_op_id
  ST r2,r0,@mth_def_test_op_base
  ST r3,r0,@mth_def_test_op_gen
  ST r4,r0,@mth_def_test_op_next
  MOVI r1,0x41
  ST r1,r0,@mth_def_test_stage

  ; Poison the whole 256-byte record.
  LD r1,r0,@mth_def_test_op_base
  MOVI r2,0
  MOVI r3,256
  CALL @mth_def_test_fill_poison_range

  ; Poison the whole following record when it exists.
  LD r4,r0,@mth_def_test_op_next
  CMP r4,r0
  JMP[EQ] @mth_def_test_op_no_next
  LD r1,r0,@mth_def_test_op_base
  MOVI r2,256
  MOVI r3,256
  CALL @mth_def_test_fill_poison_range
mth_def_test_op_no_next:

  ; Install the canonical generation guard word.
  LD r1,r0,@mth_def_test_op_base
  ADDI r1,r1,120
  LD r2,r0,@mth_def_test_op_gen
  MOVI r3,10
  CALL @mth_def_test_put_word
  MOVI r1,0x42
  ST r1,r0,@mth_def_test_stage

  ; ---- payload A: bytes 0x00..0x17 ----
  LD r1,r0,@mth_def_test_src_addr
  MOVI r2,0
  CALL @mth_def_test_fill_payload

  LD r1,r0,@mth_def_test_op_id
  LD r2,r0,@mth_def_test_src_addr
  MOVI r3,24
  LD r4,r0,@mth_def_test_op_gen
  CALL @mth_definition_slot_store
  CMP r1,r13
  JMP[NE] @mth_def_test_fail
  CMP r9,r0
  JMP[NE] @mth_def_test_fail
  CMP r10,r0
  JMP[NE] @mth_def_test_fail
  MOVI r1,0x43
  ST r1,r0,@mth_def_test_stage

  LD r1,r0,@mth_def_test_op_base
  LD r2,r0,@mth_def_test_src_addr
  LD r3,r0,@mth_def_test_op_gen
  LD r4,r0,@mth_def_test_op_next
  CALL @mth_def_test_verify_record
  CMP r1,r13
  JMP[NE] @mth_def_test_fail
  MOVI r1,0x44
  ST r1,r0,@mth_def_test_stage

  ; Poison destination, load payload A, verify exactly 24 bytes landed.
  LD r1,r0,@mth_def_test_dst_addr
  MOVI r2,0
  MOVI r3,64
  CALL @mth_def_test_fill_poison_range
  LD r1,r0,@mth_def_test_op_id
  LD r2,r0,@mth_def_test_dst_addr
  MOVI r3,24
  LD r4,r0,@mth_def_test_op_gen
  CALL @mth_definition_slot_load
  CMP r1,r13
  JMP[NE] @mth_def_test_fail
  CMP r9,r0
  JMP[NE] @mth_def_test_fail
  CMP r10,r0
  JMP[NE] @mth_def_test_fail
  CALL @mth_def_test_verify_load
  CMP r1,r13
  JMP[NE] @mth_def_test_fail
  MOVI r1,0x45
  ST r1,r0,@mth_def_test_stage

  ; ---- payload B: bytes 0xE8..0xFF ----
  LD r1,r0,@mth_def_test_src_addr
  MOVI r2,0xE8
  CALL @mth_def_test_fill_payload
  MOVI r1,0x46
  ST r1,r0,@mth_def_test_stage

  LD r1,r0,@mth_def_test_op_id
  LD r2,r0,@mth_def_test_src_addr
  MOVI r3,24
  LD r4,r0,@mth_def_test_op_gen
  CALL @mth_definition_slot_store
  CMP r1,r13
  JMP[NE] @mth_def_test_fail
  CMP r9,r0
  JMP[NE] @mth_def_test_fail
  CMP r10,r0
  JMP[NE] @mth_def_test_fail
  MOVI r1,0x47
  ST r1,r0,@mth_def_test_stage

  LD r1,r0,@mth_def_test_op_base
  LD r2,r0,@mth_def_test_src_addr
  LD r3,r0,@mth_def_test_op_gen
  LD r4,r0,@mth_def_test_op_next
  CALL @mth_def_test_verify_record
  CMP r1,r13
  JMP[NE] @mth_def_test_fail
  MOVI r1,0x48
  ST r1,r0,@mth_def_test_stage

  LD r1,r0,@mth_def_test_dst_addr
  MOVI r2,0
  MOVI r3,64
  CALL @mth_def_test_fill_poison_range
  LD r1,r0,@mth_def_test_op_id
  LD r2,r0,@mth_def_test_dst_addr
  MOVI r3,24
  LD r4,r0,@mth_def_test_op_gen
  CALL @mth_definition_slot_load
  CMP r1,r13
  JMP[NE] @mth_def_test_fail
  CMP r9,r0
  JMP[NE] @mth_def_test_fail
  CMP r10,r0
  JMP[NE] @mth_def_test_fail
  CALL @mth_def_test_verify_load
  CMP r1,r13
  JMP[NE] @mth_def_test_fail
  MOVI r1,0x49
  ST r1,r0,@mth_def_test_stage

  LD r15,r0,@mth_def_test_op_ret
  RET

; ---- generation guard is read-only and rotates without erasing the slot ----

mth_def_test_guard_rotation:
  ST r15,r0,@mth_def_test_guard_ret
  MOVI r1,0x4A
  ST r1,r0,@mth_def_test_stage

  MOVI r1,#MTH_DEF_TEST_PAIR1_BASE
  MOVI r2,0
  MOVI r3,256
  CALL @mth_def_test_fill_poison_range

  ; gen A = 0x11223344
  MOVI r1,#MTH_DEF_TEST_PAIR1_GEN_WORD
  MOVI r2,#MTH_DEF_TEST_GEN1_LOW
  MOVHI r2,#MTH_DEF_TEST_GEN1_HIGH
  MOVI r3,10
  CALL @mth_def_test_put_word

  ; payload C = bytes 0x40..0x57
  LD r1,r0,@mth_def_test_src_addr
  MOVI r2,0x40
  CALL @mth_def_test_fill_payload

  MOVI r1,1
  LD r2,r0,@mth_def_test_src_addr
  MOVI r3,24
  MOVI r4,#MTH_DEF_TEST_GEN1_LOW
  MOVHI r4,#MTH_DEF_TEST_GEN1_HIGH
  CALL @mth_definition_slot_store
  CMP r1,r13
  JMP[NE] @mth_def_test_fail
  CMP r9,r0
  JMP[NE] @mth_def_test_fail
  MOVI r1,0x4B
  ST r1,r0,@mth_def_test_stage

  ; Rotate the canonical generation to gen B = 0x99AABBCC.
  MOVI r1,#MTH_DEF_TEST_PAIR1_GEN_WORD
  MOVI r2,#MTH_DEF_TEST_GEN2_LOW
  MOVHI r2,#MTH_DEF_TEST_GEN2_HIGH
  MOVI r3,10
  CALL @mth_def_test_put_word

  ; Old guard A must now reject with cause 3 and leave the destination alone.
  LD r1,r0,@mth_def_test_dst_addr
  MOVI r2,0
  MOVI r3,64
  CALL @mth_def_test_fill_poison_range
  MOVI r1,1
  LD r2,r0,@mth_def_test_dst_addr
  MOVI r3,24
  MOVI r4,#MTH_DEF_TEST_GEN1_LOW
  MOVHI r4,#MTH_DEF_TEST_GEN1_HIGH
  CALL @mth_definition_slot_load
  CMP r1,r0
  JMP[NE] @mth_def_test_fail
  MOVI r5,3
  CMP r9,r5
  JMP[NE] @mth_def_test_fail
  CMP r10,r0
  JMP[NE] @mth_def_test_fail
  LD r1,r0,@mth_def_test_dst_addr
  MOVI r2,0
  MOVI r3,64
  CALL @mth_def_test_check_poison_range
  CMP r1,r13
  JMP[NE] @mth_def_test_fail
  MOVI r1,0x4C
  ST r1,r0,@mth_def_test_stage

  ; New guard B must accept and return the persisted payload C.
  MOVI r1,1
  LD r2,r0,@mth_def_test_dst_addr
  MOVI r3,24
  MOVI r4,#MTH_DEF_TEST_GEN2_LOW
  MOVHI r4,#MTH_DEF_TEST_GEN2_HIGH
  CALL @mth_definition_slot_load
  CMP r1,r13
  JMP[NE] @mth_def_test_fail
  CMP r9,r0
  JMP[NE] @mth_def_test_fail
  CALL @mth_def_test_verify_load
  CMP r1,r13
  JMP[NE] @mth_def_test_fail
  MOVI r1,0x4D
  ST r1,r0,@mth_def_test_stage

  ; The rotated generation word is still exactly gen B.
  MOVI r1,#MTH_DEF_TEST_PAIR1_BASE
  MOVI r2,#MTH_DEF_TEST_GEN2_LOW
  MOVHI r2,#MTH_DEF_TEST_GEN2_HIGH
  CALL @mth_def_test_check_generation_word
  CMP r1,r13
  JMP[NE] @mth_def_test_fail
  MOVI r1,0x4E
  ST r1,r0,@mth_def_test_stage

  ; Old guard A must also reject a store, leaving the slot alone.
  LD r1,r0,@mth_def_test_src_addr
  MOVI r2,0xE8
  CALL @mth_def_test_fill_payload
  MOVI r1,1
  LD r2,r0,@mth_def_test_src_addr
  MOVI r3,24
  MOVI r4,#MTH_DEF_TEST_GEN1_LOW
  MOVHI r4,#MTH_DEF_TEST_GEN1_HIGH
  CALL @mth_definition_slot_store
  CMP r1,r0
  JMP[NE] @mth_def_test_fail
  MOVI r5,3
  CMP r9,r5
  JMP[NE] @mth_def_test_fail
  CMP r10,r0
  JMP[NE] @mth_def_test_fail
  MOVI r1,0x4F
  ST r1,r0,@mth_def_test_stage

  ; Restore payload C in the source and verify the slot still holds it.
  LD r1,r0,@mth_def_test_src_addr
  MOVI r2,0x40
  CALL @mth_def_test_fill_payload
  MOVI r1,#MTH_DEF_TEST_PAIR1_BASE
  ADDI r1,r1,232
  LD r2,r0,@mth_def_test_src_addr
  MOVI r3,24
  CALL @mth_def_test_compare_buffers
  CMP r1,r13
  JMP[NE] @mth_def_test_fail

  ; Cycle flux and flags must still be poison; generation must be gen B.
  MOVI r1,#MTH_DEF_TEST_PAIR1_BASE
  MOVI r2,116
  MOVI r3,4
  CALL @mth_def_test_check_poison_range
  CMP r1,r13
  JMP[NE] @mth_def_test_fail
  MOVI r1,#MTH_DEF_TEST_PAIR1_BASE
  MOVI r2,124
  MOVI r3,108
  CALL @mth_def_test_check_poison_range
  CMP r1,r13
  JMP[NE] @mth_def_test_fail
  MOVI r1,#MTH_DEF_TEST_PAIR1_BASE
  MOVI r2,#MTH_DEF_TEST_GEN2_LOW
  MOVHI r2,#MTH_DEF_TEST_GEN2_HIGH
  CALL @mth_def_test_check_generation_word
  CMP r1,r13
  JMP[NE] @mth_def_test_fail
  MOVI r1,0x50
  ST r1,r0,@mth_def_test_stage

  LD r15,r0,@mth_def_test_guard_ret
  RET

; ---- invalid ids, lengths, guards, buffer spans, and non-mutation ----

mth_def_test_invalid:
  ST r15,r0,@mth_def_test_inv_ret
  LA r6,@mth_def_test_invalid_cases
  ST r6,r0,@mth_def_test_inv_ptr
  MOVI r14,0
  ST r14,r0,@mth_def_test_inv_i

mth_def_test_inv_loop:
  LD r14,r0,@mth_def_test_inv_i
  MOVI r1,0x61
  ADD r1,r1,r14
  ST r1,r0,@mth_def_test_stage

  ; Fresh pair-1 record and following record, both fully poisoned.
  MOVI r1,#MTH_DEF_TEST_PAIR1_BASE
  MOVI r2,0
  MOVI r3,256
  CALL @mth_def_test_fill_poison_range
  MOVI r1,#MTH_DEF_TEST_PAIR1_BASE
  MOVI r2,256
  MOVI r3,256
  CALL @mth_def_test_fill_poison_range

  ; Install gen A at pair 1.
  MOVI r1,#MTH_DEF_TEST_PAIR1_GEN_WORD
  MOVI r2,#MTH_DEF_TEST_GEN1_LOW
  MOVHI r2,#MTH_DEF_TEST_GEN1_HIGH
  MOVI r3,10
  CALL @mth_def_test_put_word

  ; Fresh source and destination buffers.
  LD r1,r0,@mth_def_test_src_addr
  MOVI r2,0
  CALL @mth_def_test_fill_payload
  LD r1,r0,@mth_def_test_dst_addr
  MOVI r2,0
  MOVI r3,64
  CALL @mth_def_test_fill_poison_range

  ; ---- store rejection ----
  LD r6,r0,@mth_def_test_inv_ptr
  LD r1,r6,0
  LD r2,r6,3
  LD r3,r6,1
  LD r4,r6,2
  LD r5,r6,4
  ST r5,r0,@mth_def_test_inv_cause
  CMP r2,r0
  JMP[NE] @mth_def_test_inv_store_go
  LD r2,r0,@mth_def_test_src_addr
mth_def_test_inv_store_go:
  CALL @mth_definition_slot_store
  CMP r1,r0
  JMP[NE] @mth_def_test_fail
  LD r5,r0,@mth_def_test_inv_cause
  CMP r9,r5
  JMP[NE] @mth_def_test_fail
  CMP r10,r0
  JMP[NE] @mth_def_test_fail
  MOVI r1,0x53
  ST r1,r0,@mth_def_test_stage

  MOVI r1,#MTH_DEF_TEST_PAIR1_BASE
  MOVI r2,#MTH_DEF_TEST_GEN1_LOW
  MOVHI r2,#MTH_DEF_TEST_GEN1_HIGH
  CALL @mth_def_test_verify_poisoned_record
  CMP r1,r13
  JMP[NE] @mth_def_test_fail
  MOVI r1,0x54
  ST r1,r0,@mth_def_test_stage
  LD r1,r0,@mth_def_test_dst_addr
  MOVI r2,0
  MOVI r3,64
  CALL @mth_def_test_check_poison_range
  CMP r1,r13
  JMP[NE] @mth_def_test_fail
  MOVI r1,0x55
  ST r1,r0,@mth_def_test_stage

  ; ---- load rejection ----
  LD r6,r0,@mth_def_test_inv_ptr
  LD r1,r6,0
  LD r2,r6,3
  LD r3,r6,1
  LD r4,r6,2
  LD r5,r6,4
  ST r5,r0,@mth_def_test_inv_cause
  CMP r2,r0
  JMP[NE] @mth_def_test_inv_load_go
  LD r2,r0,@mth_def_test_dst_addr
mth_def_test_inv_load_go:
  CALL @mth_definition_slot_load
  CMP r1,r0
  JMP[NE] @mth_def_test_fail
  LD r5,r0,@mth_def_test_inv_cause
  CMP r9,r5
  JMP[NE] @mth_def_test_fail
  CMP r10,r0
  JMP[NE] @mth_def_test_fail
  MOVI r1,0x56
  ST r1,r0,@mth_def_test_stage

  LD r1,r0,@mth_def_test_dst_addr
  MOVI r2,0
  MOVI r3,64
  CALL @mth_def_test_check_poison_range
  CMP r1,r13
  JMP[NE] @mth_def_test_fail
  MOVI r1,0x57
  ST r1,r0,@mth_def_test_stage
  MOVI r1,#MTH_DEF_TEST_PAIR1_BASE
  MOVI r2,#MTH_DEF_TEST_GEN1_LOW
  MOVHI r2,#MTH_DEF_TEST_GEN1_HIGH
  CALL @mth_def_test_verify_poisoned_record
  CMP r1,r13
  JMP[NE] @mth_def_test_fail
  MOVI r1,0x58
  ST r1,r0,@mth_def_test_stage

  LD r6,r0,@mth_def_test_inv_ptr
  ADDI r6,r6,5
  ST r6,r0,@mth_def_test_inv_ptr
  LD r14,r0,@mth_def_test_inv_i
  ADD r14,r14,r13
  ST r14,r0,@mth_def_test_inv_i
  MOVI r5,#MTH_DEF_TEST_INVALID_COUNT
  CMP r14,r5
  JMP[LT] @mth_def_test_inv_loop

  LD r15,r0,@mth_def_test_inv_ret
  RET

; ---- verification helpers ----

; r1=base, r2=src byte address, r3=gen, r4=next-record flag -> r1=1/0.
mth_def_test_verify_record:
  ST r15,r0,@mth_def_test_vr_ret
  ST r1,r0,@mth_def_test_vr_base
  ST r2,r0,@mth_def_test_vr_src
  ST r3,r0,@mth_def_test_vr_gen
  ST r4,r0,@mth_def_test_vr_next

  ; [0,120) poison: lane-0 residuals, relation_type, confidence,
  ; hyperedge_head, cycle_flux.
  LD r1,r0,@mth_def_test_vr_base
  MOVI r2,0
  MOVI r3,120
  CALL @mth_def_test_check_poison_range
  CMP r1,r13
  JMP[NE] @mth_def_test_vr_bad

  ; Generation guard word unchanged.
  LD r1,r0,@mth_def_test_vr_base
  LD r2,r0,@mth_def_test_vr_gen
  CALL @mth_def_test_check_generation_word
  CMP r1,r13
  JMP[NE] @mth_def_test_vr_bad

  ; [124,232) poison: flags and every lane-1 residual byte.
  LD r1,r0,@mth_def_test_vr_base
  MOVI r2,124
  MOVI r3,108
  CALL @mth_def_test_check_poison_range
  CMP r1,r13
  JMP[NE] @mth_def_test_vr_bad

  ; [232,256) exactly the source payload.
  LD r1,r0,@mth_def_test_vr_base
  ADDI r1,r1,232
  LD r2,r0,@mth_def_test_vr_src
  MOVI r3,24
  CALL @mth_def_test_compare_buffers
  CMP r1,r13
  JMP[NE] @mth_def_test_vr_bad

  ; Whole following record still poison, when present.
  LD r4,r0,@mth_def_test_vr_next
  CMP r4,r0
  JMP[EQ] @mth_def_test_vr_good
  LD r1,r0,@mth_def_test_vr_base
  MOVI r2,256
  MOVI r3,256
  CALL @mth_def_test_check_poison_range
  CMP r1,r13
  JMP[NE] @mth_def_test_vr_bad

mth_def_test_vr_good:
  MOVI r1,1
  JMP @mth_def_test_vr_done
mth_def_test_vr_bad:
  MOVI r1,0
mth_def_test_vr_done:
  LD r15,r0,@mth_def_test_vr_ret
  RET

; Destination must equal src[0..23] and dst[24..63] must still be poison.
mth_def_test_verify_load:
  ST r15,r0,@mth_def_test_vl_ret

  LD r1,r0,@mth_def_test_dst_addr
  LD r2,r0,@mth_def_test_src_addr
  MOVI r3,24
  CALL @mth_def_test_compare_buffers
  CMP r1,r13
  JMP[NE] @mth_def_test_vl_bad

  LD r1,r0,@mth_def_test_dst_addr
  MOVI r2,24
  MOVI r3,40
  CALL @mth_def_test_check_poison_range
  CMP r1,r13
  JMP[NE] @mth_def_test_vl_bad

  MOVI r1,1
  JMP @mth_def_test_vl_done
mth_def_test_vl_bad:
  MOVI r1,0
mth_def_test_vl_done:
  LD r15,r0,@mth_def_test_vl_ret
  RET

; r1=base, r2=gen -> r1=1/0. Slot bytes [232,256) must still be poison, all
; canonical non-generation bytes and the whole following record must be poison.
mth_def_test_verify_poisoned_record:
  ST r15,r0,@mth_def_test_vpr_ret
  ST r1,r0,@mth_def_test_vpr_base
  ST r2,r0,@mth_def_test_vpr_gen

  LD r1,r0,@mth_def_test_vpr_base
  MOVI r2,0
  MOVI r3,120
  CALL @mth_def_test_check_poison_range
  CMP r1,r13
  JMP[NE] @mth_def_test_vpr_bad

  LD r1,r0,@mth_def_test_vpr_base
  LD r2,r0,@mth_def_test_vpr_gen
  CALL @mth_def_test_check_generation_word
  CMP r1,r13
  JMP[NE] @mth_def_test_vpr_bad

  LD r1,r0,@mth_def_test_vpr_base
  MOVI r2,124
  MOVI r3,108
  CALL @mth_def_test_check_poison_range
  CMP r1,r13
  JMP[NE] @mth_def_test_vpr_bad

  ; The 24 slot bytes must not have been touched by a rejection.
  LD r1,r0,@mth_def_test_vpr_base
  MOVI r2,232
  MOVI r3,24
  CALL @mth_def_test_check_poison_range
  CMP r1,r13
  JMP[NE] @mth_def_test_vpr_bad

  ; Following record untouched.
  LD r1,r0,@mth_def_test_vpr_base
  MOVI r2,256
  MOVI r3,256
  CALL @mth_def_test_check_poison_range
  CMP r1,r13
  JMP[NE] @mth_def_test_vpr_bad

  MOVI r1,1
  JMP @mth_def_test_vpr_done
mth_def_test_vpr_bad:
  MOVI r1,0
mth_def_test_vpr_done:
  LD r15,r0,@mth_def_test_vpr_ret
  RET

; r1=base, r2=expected generation -> r1=1/0.
mth_def_test_check_generation_word:
  ST r15,r0,@mth_def_test_cg_ret
  ADDI r1,r1,120
  CALL @mth_def_test_get_word
  CMP r1,r2
  JMP[NE] @mth_def_test_cg_bad
  MOVI r1,1
  JMP @mth_def_test_cg_done
mth_def_test_cg_bad:
  MOVI r1,0
mth_def_test_cg_done:
  LD r15,r0,@mth_def_test_cg_ret
  RET

; ---- byte-pattern helpers ----

; r1=base, r2=start offset, r3=count. Byte at offset start+i is
; ((start+i) XOR 0xA5) & 0xFF.
mth_def_test_fill_poison_range:
  ST r15,r0,@mth_def_test_fp_ret
  ST r12,r0,@mth_def_test_fp_save12
  ST r14,r0,@mth_def_test_fp_save14
  ADD r12,r1,r2
  ADD r10,r2,r0
  ADD r11,r3,r0
  MOVI r14,0
mth_def_test_fp_loop:
  ADD r1,r12,r14
  ADD r2,r10,r14
  MOVI r9,0xA5
  BOOL.6 r2,r2,r9
  MOVI r9,0xFF
  BOOL.8 r2,r2,r9
  CALL @mth_def_test_put_byte
  ADD r14,r14,r13
  CMP r14,r11
  JMP[LT] @mth_def_test_fp_loop
  LD r12,r0,@mth_def_test_fp_save12
  LD r14,r0,@mth_def_test_fp_save14
  LD r15,r0,@mth_def_test_fp_ret
  RET

; r1=base, r2=start offset, r3=count -> r1=1/0.
mth_def_test_check_poison_range:
  ST r15,r0,@mth_def_test_cp_ret
  ST r12,r0,@mth_def_test_cp_save12
  ST r14,r0,@mth_def_test_cp_save14
  ADD r12,r1,r2
  ADD r10,r2,r0
  ADD r11,r3,r0
  MOVI r14,0
mth_def_test_cp_loop:
  ADD r1,r12,r14
  CALL @mth_def_test_get_byte
  ADD r8,r1,r0
  ADD r2,r10,r14
  MOVI r9,0xA5
  BOOL.6 r2,r2,r9
  MOVI r9,0xFF
  BOOL.8 r2,r2,r9
  CMP r8,r2
  JMP[NE] @mth_def_test_cp_bad
  ADD r14,r14,r13
  CMP r14,r11
  JMP[LT] @mth_def_test_cp_loop
  MOVI r1,1
  JMP @mth_def_test_cp_done
mth_def_test_cp_bad:
  MOVI r1,0
mth_def_test_cp_done:
  LD r12,r0,@mth_def_test_cp_save12
  LD r14,r0,@mth_def_test_cp_save14
  LD r15,r0,@mth_def_test_cp_ret
  RET

; r1=destination byte address, r2=seed. Writes 24 bytes (seed+i)&0xFF.
mth_def_test_fill_payload:
  ST r15,r0,@mth_def_test_pl_ret
  ST r12,r0,@mth_def_test_pl_save12
  ST r14,r0,@mth_def_test_pl_save14
  ADD r12,r1,r0
  ADD r10,r2,r0
  MOVI r14,0
mth_def_test_pl_loop:
  ADD r1,r12,r14
  ADD r2,r10,r14
  MOVI r9,0xFF
  BOOL.8 r2,r2,r9
  CALL @mth_def_test_put_byte
  ADD r14,r14,r13
  MOVI r9,24
  CMP r14,r9
  JMP[LT] @mth_def_test_pl_loop
  LD r12,r0,@mth_def_test_pl_save12
  LD r14,r0,@mth_def_test_pl_save14
  LD r15,r0,@mth_def_test_pl_ret
  RET

; r1=a, r2=b, r3=count -> r1=1 if all bytes equal, else 0.
mth_def_test_compare_buffers:
  ST r15,r0,@mth_def_test_cmp_ret
  ST r12,r0,@mth_def_test_cmp_save12
  ST r14,r0,@mth_def_test_cmp_save14
  ADD r12,r1,r0
  ADD r10,r2,r0
  ADD r11,r3,r0
  MOVI r14,0
mth_def_test_cmp_loop:
  ADD r1,r12,r14
  CALL @mth_def_test_get_byte
  ADD r9,r1,r0
  ADD r1,r10,r14
  CALL @mth_def_test_get_byte
  CMP r1,r9
  JMP[NE] @mth_def_test_cmp_bad
  ADD r14,r14,r13
  CMP r14,r11
  JMP[LT] @mth_def_test_cmp_loop
  MOVI r1,1
  JMP @mth_def_test_cmp_done
mth_def_test_cmp_bad:
  MOVI r1,0
mth_def_test_cmp_done:
  LD r12,r0,@mth_def_test_cmp_save12
  LD r14,r0,@mth_def_test_cmp_save14
  LD r15,r0,@mth_def_test_cmp_ret
  RET

; ---- raw word and byte accessors ----

; r1=byte address, r2=payload, r3=class nibble.
mth_def_test_put_word:
  SHR r1,r1,2
  STW r2,r1,r3
  RET

; r1=byte address -> r1=payload.
mth_def_test_get_word:
  SHR r1,r1,2
  LD r1,r1,0
  RET

; r1=byte address, r2=byte value.
mth_def_test_put_byte:
  STB r2,r1,0
  RET

; r1=byte address -> r1=byte value.
mth_def_test_get_byte:
  LDB r1,r1,0
  RET

; ---- string output ----

mth_def_test_puts:
  MOVI r4,255
mth_def_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_def_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_def_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_def_test_puts_word

mth_def_test_fail:
  LA r1,@mth_def_test_bad
  CALL @mth_def_test_puts
  LD r1,r0,@mth_def_test_stage
  PUTC r1
  MOVI r1,10
  PUTC r1
  HALT

; ---- static slots ----

.org 4096
mth_def_test_stage:
.word 0
mth_def_test_src_addr:
.word 0
mth_def_test_dst_addr:
.word 0
mth_def_test_bound_ret:
.word 0
mth_def_test_op_ret:
.word 0
mth_def_test_op_id:
.word 0
mth_def_test_op_base:
.word 0
mth_def_test_op_gen:
.word 0
mth_def_test_op_next:
.word 0
mth_def_test_guard_ret:
.word 0
mth_def_test_inv_ret:
.word 0
mth_def_test_inv_ptr:
.word 0
mth_def_test_inv_i:
.word 0
mth_def_test_inv_cause:
.word 0
mth_def_test_vr_ret:
.word 0
mth_def_test_vr_base:
.word 0
mth_def_test_vr_src:
.word 0
mth_def_test_vr_gen:
.word 0
mth_def_test_vr_next:
.word 0
mth_def_test_vl_ret:
.word 0
mth_def_test_vpr_ret:
.word 0
mth_def_test_vpr_base:
.word 0
mth_def_test_vpr_gen:
.word 0
mth_def_test_cg_ret:
.word 0
mth_def_test_fp_ret:
.word 0
mth_def_test_fp_save12:
.word 0
mth_def_test_fp_save14:
.word 0
mth_def_test_cp_ret:
.word 0
mth_def_test_cp_save12:
.word 0
mth_def_test_cp_save14:
.word 0
mth_def_test_pl_ret:
.word 0
mth_def_test_pl_save12:
.word 0
mth_def_test_pl_save14:
.word 0
mth_def_test_cmp_ret:
.word 0
mth_def_test_cmp_save12:
.word 0
mth_def_test_cmp_save14:
.word 0

; 24-byte source and 64-byte destination/poison buffers.
.org 4300
mth_def_test_src:
.word 0,0,0,0,0,0
mth_def_test_dst:
.word 0,0,0,0,0,0,0,0
.word 0,0,0,0,0,0,0,0

; [id, count, guard, buffer byte address or 0 for src/dst, expected cause]
mth_def_test_invalid_cases:
.word 0,24,0x11223344,0,1
.word 32641,24,0x11223344,0,1
.word 0xFFFFFFFF,24,0x11223344,0,1
.word 1,0,0x11223344,0,2
.word 1,23,0x11223344,0,2
.word 1,25,0x11223344,0,2
.word 1,0xFFFFFFFF,0x11223344,0,2
.word 1,24,0xDEADBEEF,0,3
.word 1,24,0,0,3
.word 1,24,0x11223344,0xFFFFFFF8,5
.word 1,24,0x11223344,0x7FFFFC,5
.word 0,23,0xDEADBEEF,0xFFFFFFF8,1
.word 1,23,0xDEADBEEF,0xFFFFFFF8,2
.word 1,24,0xDEADBEEF,0xFFFFFFF8,3

.org 4700
mth_def_test_pass:
.str "MTH DEFINITION SLOT IO PASS\n"
mth_def_test_bad:
.str "MTH DEFINITION SLOT IO FAIL\n"
