; MTH canonical mirror-memory head-record I/O fixture — NaN16 only.
;
; The fixture materializes the canonical 32,768-byte head region at a
; non-overlapping scratch base (1 MiB) so it can exercise the real byte
; layout without overwriting the loaded guest program. Every check is native
; NaN16 integer code; there is no host arithmetic and no external oracle.
;
; Coverage:
;   1. every one of the 256 heads is initialized with a per-head, per-word
;      reserved sentinel pattern and read back through the getter before any
;      field write;
;   2. all four fields of all 256 heads are set and read back exactly, and
;      each still-pristine record is checked in full before its own field
;      writes so no write may leak into a later head;
;   3. the canonical byte offsets 0, 4, 8, and 12 are verified independently
;      with LDB, and every reserved byte (record bytes 16..127) is checked
;      against its sentinel for all 256 heads;
;   4. head 0 is NANNET0: it is accepted, stored at the arena base, and is
;      independent of head 1;
;   5. head 255 and field 3 are the upper head/field boundaries; records end
;      at arena byte 32,767 and guard words on both sides stay untouched;
;   6. each field is mutated alone and the other three fields keep their
;      exact payloads, proving field non-overlap;
;   7. 0x00000000, 0xFFFFFFFF, -0.0, +0.0, the minimum/maximum finite f32,
;      and repeated writes round-trip as raw payloads;
;   8. invalid get/set requests are rejected atomically: head 256, head 257,
;      head 0xFFFFFFFF, field 4 (the first reserved selector), field 5, 31,
;      32, and field 0xFFFFFFFF; after the rejection sequence the complete
;      target record is still byte-for-byte the expected value.
;
; The reserved sentinels are deliberately non-zero (0xA5..., plus the head
; and word index) so any stray write into record bytes 16..127 is visible.
; They are not a claim that a fresh canonical root contains non-zero bytes.

.equ MTH_HDR_TEST_ARENA_BYTE 0x00100000
.equ MTH_HDR_TEST_ARENA_WORD 0x00040000
.equ MTH_HDR_TEST_GUARD_PRE 0x0003FFFF
.equ MTH_HDR_TEST_GUARD_POST 0x00042000

.org 0
JMP @mth_hdr_test_main
.include "../nan16/mth_mirror_head_record_io.nas"

mth_hdr_test_main:
  MOVI r0,0
  MOVI r13,1
  LA r11,#MTH_HDR_TEST_ARENA_BYTE
  LA r12,#MTH_HDR_TEST_ARENA_WORD

  ; Guard words immediately before and after the 32 KiB head arena.
  LA r1,#MTH_HDR_TEST_GUARD_PRE
  MOVI r2,0xBEEF
  MOVHI r2,0xDEAD
  ST r2,r1,0
  LA r1,#MTH_HDR_TEST_GUARD_POST
  MOVI r2,0xBABE
  MOVHI r2,0xCAFE
  ST r2,r1,0

  CALL @mth_hdr_test_fill
  CALL @mth_hdr_test_guards
  CALL @mth_hdr_test_check_initial
  CALL @mth_hdr_test_set_all
  CALL @mth_hdr_test_check_all
  CALL @mth_hdr_test_named_wrappers
  CALL @mth_hdr_test_field_isolation
  CALL @mth_hdr_test_nannet0
  CALL @mth_hdr_test_boundaries
  CALL @mth_hdr_test_invalid
  CALL @mth_hdr_test_final_integrity
  CALL @mth_hdr_test_guards

  LA r1,@mth_hdr_test_pass
  CALL @mth_hdr_test_puts
  HALT

; ---------------------------------------------------------------------------
; Arena setup and whole-record helpers
; ---------------------------------------------------------------------------

; Fill every payload word of the 256 records with a unique sentinel:
;   word w of head h = 0xA5000000 | (h << 8) | w,  w = 0..31.
; The first four words are later overwritten by field tests; words 4..31 are
; the reserved sentinels checked after every mutation.
mth_hdr_test_fill:
  ADD r5,r12,r0
  MOVI r7,0
mth_hdr_test_fill_head:
  SHL r6,r7,8
  MOVI r8,0
  MOVHI r8,0xA500
  ADD r6,r6,r8
  MOVI r8,0
mth_hdr_test_fill_word:
  ADD r9,r6,r8
  ST r9,r5,0
  ADD r5,r5,r13
  ADD r8,r8,r13
  MOVI r9,32
  CMP r8,r9
  JMP[LT] @mth_hdr_test_fill_word
  ADD r7,r7,r13
  MOVI r9,256
  CMP r7,r9
  JMP[LT] @mth_hdr_test_fill_head
  MOVI r1,1
  RET

mth_hdr_test_guards:
  LA r1,#MTH_HDR_TEST_GUARD_PRE
  LD r2,r1,0
  MOVI r3,0xBEEF
  MOVHI r3,0xDEAD
  CMP r2,r3
  JMP[NE] @mth_hdr_test_fail
  LA r1,#MTH_HDR_TEST_GUARD_POST
  LD r2,r1,0
  MOVI r3,0xBABE
  MOVHI r3,0xCAFE
  CMP r2,r3
  JMP[NE] @mth_hdr_test_fail
  MOVI r1,1
  RET

; r1 = head, r2 = field, r3 = expected payload.
mth_hdr_test_get_expect:
  ST r15,r0,@mth_hdr_test_get_ret
  ST r1,r0,@mth_hdr_test_get_head
  ST r2,r0,@mth_hdr_test_get_field
  ST r3,r0,@mth_hdr_test_get_value

  ADD r1,r11,r0
  LD r2,r0,@mth_hdr_test_get_head
  LD r3,r0,@mth_hdr_test_get_field
  CALL @mth_mirror_head_record_get
  CMP r1,r13
  JMP[NE] @mth_hdr_test_fail
  CMP r9,r0
  JMP[NE] @mth_hdr_test_fail
  LD r4,r0,@mth_hdr_test_get_value
  CMP r10,r4
  JMP[NE] @mth_hdr_test_fail
  CMP r2,r4
  JMP[NE] @mth_hdr_test_fail

  LD r15,r0,@mth_hdr_test_get_ret
  MOVI r1,1
  RET

; r1 = head, r2 = field, r3 = value.
mth_hdr_test_set:
  ST r15,r0,@mth_hdr_test_set_ret
  ST r1,r0,@mth_hdr_test_set_head
  ST r2,r0,@mth_hdr_test_set_field
  ST r3,r0,@mth_hdr_test_set_value

  ADD r1,r11,r0
  LD r2,r0,@mth_hdr_test_set_head
  LD r3,r0,@mth_hdr_test_set_field
  LD r4,r0,@mth_hdr_test_set_value
  CALL @mth_mirror_head_record_set
  CMP r1,r13
  JMP[NE] @mth_hdr_test_fail
  CMP r9,r0
  JMP[NE] @mth_hdr_test_fail

  LD r15,r0,@mth_hdr_test_set_ret
  MOVI r1,1
  RET

; Independent byte-level field check. r1 = head, r2 = field, r3 = payload.
; Uses LDB at base + head*128 + field*4 and requires all four little-endian
; bytes to equal the expected payload.
mth_hdr_test_bytes:
  SHL r5,r1,7
  ADD r5,r11,r5
  SHL r6,r2,2
  ADD r5,r5,r6
  ADD r6,r3,r0
  MOVI r7,0
mth_hdr_test_bytes_loop:
  LDB r8,r5,0
  MOVI r9,255
  BOOL.8 r8,r8,r9
  BOOL.8 r9,r6,r9
  CMP r8,r9
  JMP[NE] @mth_hdr_test_fail
  SHR r6,r6,8
  ADDI r5,r5,1
  ADDI r7,r7,1
  MOVI r9,4
  CMP r7,r9
  JMP[LT] @mth_hdr_test_bytes_loop
  MOVI r1,1
  RET

; Verify that all 32 payload words of head r1 are still the fill sentinel.
; Before a head is legitimately initialized, this detects any write that
; leaked forward into a later record.
mth_hdr_test_pristine:
  SHL r5,r1,5
  ADD r5,r12,r5
  SHL r6,r1,8
  MOVI r7,0
  MOVHI r7,0xA500
  ADD r6,r6,r7
  MOVI r7,0
mth_hdr_test_pristine_loop:
  LD r8,r5,0
  ADD r9,r6,r7
  CMP r8,r9
  JMP[NE] @mth_hdr_test_fail
  ADD r5,r5,r13
  ADD r7,r7,r13
  MOVI r9,32
  CMP r7,r9
  JMP[LT] @mth_hdr_test_pristine_loop
  MOVI r1,1
  RET

; Check all 28 reserved payload words (record bytes 16..127) of head r1
; against the fill sentinel. This reads every reserved byte as a word.
mth_hdr_test_reserved:
  SHL r5,r1,5
  ADD r5,r12,r5
  ADDI r5,r5,4
  SHL r6,r1,8
  MOVI r7,0
  MOVHI r7,0xA500
  ADD r6,r6,r7
  ADDI r6,r6,4
  MOVI r7,4
mth_hdr_test_reserved_loop:
  LD r8,r5,0
  CMP r8,r6
  JMP[NE] @mth_hdr_test_fail
  ADD r5,r5,r13
  ADD r6,r6,r13
  ADD r7,r7,r13
  MOVI r9,32
  CMP r7,r9
  JMP[LT] @mth_hdr_test_reserved_loop
  MOVI r1,1
  RET

; ---------------------------------------------------------------------------
; Per-head field set/check loops, using r14 as the current head.
; ---------------------------------------------------------------------------

mth_hdr_test_set_all_one:
  ST r15,r0,@mth_hdr_test_set_all_one_ret

  ; first_hyperedge = 0x11000000 + head
  ADD r1,r14,r0
  MOVI r2,0
  MOVI r3,0
  MOVHI r3,0x1100
  ADD r3,r3,r14
  CALL @mth_hdr_test_set

  ; state = 0x22000000 + head
  ADD r1,r14,r0
  MOVI r2,1
  MOVI r3,0
  MOVHI r3,0x2200
  ADD r3,r3,r14
  CALL @mth_hdr_test_set

  ; score = 1.0 + head*2^-23, a finite binary32 payload
  ADD r1,r14,r0
  MOVI r2,2
  MOVI r3,0
  MOVHI r3,0x3F80
  ADD r3,r3,r14
  CALL @mth_hdr_test_set

  ; generation = 0x44000000 + head
  ADD r1,r14,r0
  MOVI r2,3
  MOVI r3,0
  MOVHI r3,0x4400
  ADD r3,r3,r14
  CALL @mth_hdr_test_set

  LD r15,r0,@mth_hdr_test_set_all_one_ret
  MOVI r1,1
  RET

mth_hdr_test_set_all:
  ST r15,r0,@mth_hdr_test_set_all_ret
  MOVI r14,0
mth_hdr_test_set_all_loop:
  ADD r1,r14,r0
  CALL @mth_hdr_test_pristine
  CALL @mth_hdr_test_set_all_one
  ADD r14,r14,r13
  MOVI r5,256
  CMP r14,r5
  JMP[LT] @mth_hdr_test_set_all_loop
  LD r15,r0,@mth_hdr_test_set_all_ret
  MOVI r1,1
  RET

mth_hdr_test_check_all_one:
  ST r15,r0,@mth_hdr_test_check_all_one_ret

  ; field 0
  ADD r1,r14,r0
  MOVI r2,0
  MOVI r3,0
  MOVHI r3,0x1100
  ADD r3,r3,r14
  ST r3,r0,@mth_hdr_test_expected
  CALL @mth_hdr_test_get_expect
  ADD r1,r14,r0
  MOVI r2,0
  LD r3,r0,@mth_hdr_test_expected
  CALL @mth_hdr_test_bytes

  ; field 1
  ADD r1,r14,r0
  MOVI r2,1
  MOVI r3,0
  MOVHI r3,0x2200
  ADD r3,r3,r14
  ST r3,r0,@mth_hdr_test_expected
  CALL @mth_hdr_test_get_expect
  ADD r1,r14,r0
  MOVI r2,1
  LD r3,r0,@mth_hdr_test_expected
  CALL @mth_hdr_test_bytes

  ; field 2
  ADD r1,r14,r0
  MOVI r2,2
  MOVI r3,0
  MOVHI r3,0x3F80
  ADD r3,r3,r14
  ST r3,r0,@mth_hdr_test_expected
  CALL @mth_hdr_test_get_expect
  ADD r1,r14,r0
  MOVI r2,2
  LD r3,r0,@mth_hdr_test_expected
  CALL @mth_hdr_test_bytes

  ; field 3
  ADD r1,r14,r0
  MOVI r2,3
  MOVI r3,0
  MOVHI r3,0x4400
  ADD r3,r3,r14
  ST r3,r0,@mth_hdr_test_expected
  CALL @mth_hdr_test_get_expect
  ADD r1,r14,r0
  MOVI r2,3
  LD r3,r0,@mth_hdr_test_expected
  CALL @mth_hdr_test_bytes

  ADD r1,r14,r0
  CALL @mth_hdr_test_reserved

  LD r15,r0,@mth_hdr_test_check_all_one_ret
  MOVI r1,1
  RET

mth_hdr_test_check_all:
  ST r15,r0,@mth_hdr_test_check_all_ret
  MOVI r14,0
mth_hdr_test_check_all_loop:
  CALL @mth_hdr_test_check_all_one
  ADD r14,r14,r13
  MOVI r5,256
  CMP r14,r5
  JMP[LT] @mth_hdr_test_check_all_loop
  LD r15,r0,@mth_hdr_test_check_all_ret
  MOVI r1,1
  RET

; Before any field write, read all four fields of all 256 heads and require
; the fill sentinel for words 0..3.
mth_hdr_test_check_initial:
  ST r15,r0,@mth_hdr_test_check_initial_ret
  MOVI r14,0
mth_hdr_test_check_initial_loop:
  SHL r5,r14,8
  MOVI r6,0
  MOVHI r6,0xA500
  ADD r5,r5,r6
  ST r5,r0,@mth_hdr_test_pattern

  ADD r1,r14,r0
  MOVI r2,0
  LD r3,r0,@mth_hdr_test_pattern
  CALL @mth_hdr_test_get_expect

  ADD r1,r14,r0
  MOVI r2,1
  LD r3,r0,@mth_hdr_test_pattern
  ADDI r3,r3,1
  CALL @mth_hdr_test_get_expect

  ADD r1,r14,r0
  MOVI r2,2
  LD r3,r0,@mth_hdr_test_pattern
  ADDI r3,r3,2
  CALL @mth_hdr_test_get_expect

  ADD r1,r14,r0
  MOVI r2,3
  LD r3,r0,@mth_hdr_test_pattern
  ADDI r3,r3,3
  CALL @mth_hdr_test_get_expect

  ADD r14,r14,r13
  MOVI r5,256
  CMP r14,r5
  JMP[LT] @mth_hdr_test_check_initial_loop
  LD r15,r0,@mth_hdr_test_check_initial_ret
  MOVI r1,1
  RET

; ---------------------------------------------------------------------------
; Named per-field wrapper dispatch helpers and success-path coverage
; ---------------------------------------------------------------------------

; r1 = head, r2 = field, r3 = expected payload.
; Dispatches to the named getter so every public wrapper is executed.
mth_hdr_test_named_get_expect:
  ST r15,r0,@mth_hdr_test_named_get_wrap_ret
  ST r1,r0,@mth_hdr_test_named_get_wrap_head
  ST r2,r0,@mth_hdr_test_named_get_wrap_field
  ST r3,r0,@mth_hdr_test_named_get_wrap_value

  ADD r1,r11,r0
  LD r2,r0,@mth_hdr_test_named_get_wrap_head
  LD r5,r0,@mth_hdr_test_named_get_wrap_field
  MOVI r6,0
  CMP r5,r6
  JMP[EQ] @mth_hdr_test_named_get_expect_first
  MOVI r6,1
  CMP r5,r6
  JMP[EQ] @mth_hdr_test_named_get_expect_state
  MOVI r6,2
  CMP r5,r6
  JMP[EQ] @mth_hdr_test_named_get_expect_score
  CALL @mth_mirror_head_record_get_generation
  JMP @mth_hdr_test_named_get_expect_done

mth_hdr_test_named_get_expect_first:
  CALL @mth_mirror_head_record_get_first_hyperedge
  JMP @mth_hdr_test_named_get_expect_done
mth_hdr_test_named_get_expect_state:
  CALL @mth_mirror_head_record_get_state
  JMP @mth_hdr_test_named_get_expect_done
mth_hdr_test_named_get_expect_score:
  CALL @mth_mirror_head_record_get_score

mth_hdr_test_named_get_expect_done:
  CMP r1,r13
  JMP[NE] @mth_hdr_test_fail
  CMP r9,r0
  JMP[NE] @mth_hdr_test_fail
  LD r4,r0,@mth_hdr_test_named_get_wrap_value
  CMP r10,r4
  JMP[NE] @mth_hdr_test_fail
  CMP r2,r4
  JMP[NE] @mth_hdr_test_fail

  LD r15,r0,@mth_hdr_test_named_get_wrap_ret
  MOVI r1,1
  RET

; r1 = head, r2 = field, r3 = value.
; Dispatches to the named setter so every public wrapper is executed.
mth_hdr_test_named_set:
  ST r15,r0,@mth_hdr_test_named_set_wrap_ret
  ST r1,r0,@mth_hdr_test_named_set_wrap_head
  ST r2,r0,@mth_hdr_test_named_set_wrap_field
  ST r3,r0,@mth_hdr_test_named_set_wrap_value

  ADD r1,r11,r0
  LD r2,r0,@mth_hdr_test_named_set_wrap_head
  LD r3,r0,@mth_hdr_test_named_set_wrap_value
  LD r5,r0,@mth_hdr_test_named_set_wrap_field
  MOVI r6,0
  CMP r5,r6
  JMP[EQ] @mth_hdr_test_named_set_first
  MOVI r6,1
  CMP r5,r6
  JMP[EQ] @mth_hdr_test_named_set_state
  MOVI r6,2
  CMP r5,r6
  JMP[EQ] @mth_hdr_test_named_set_score
  CALL @mth_mirror_head_record_set_generation
  JMP @mth_hdr_test_named_set_done

mth_hdr_test_named_set_first:
  CALL @mth_mirror_head_record_set_first_hyperedge
  JMP @mth_hdr_test_named_set_done
mth_hdr_test_named_set_state:
  CALL @mth_mirror_head_record_set_state
  JMP @mth_hdr_test_named_set_done
mth_hdr_test_named_set_score:
  CALL @mth_mirror_head_record_set_score

mth_hdr_test_named_set_done:
  CMP r1,r13
  JMP[NE] @mth_hdr_test_fail
  CMP r9,r0
  JMP[NE] @mth_hdr_test_fail

  LD r15,r0,@mth_hdr_test_named_set_wrap_ret
  MOVI r1,1
  RET

mth_hdr_test_named_wrappers:
  ST r15,r0,@mth_hdr_test_named_wrappers_ret
  MOVI r14,9
  CALL @mth_hdr_test_set_all_one

  ; Write each field only through its named setter.
  ADD r1,r14,r0
  MOVI r2,0
  MOVI r3,0x0304
  MOVHI r3,0x0102
  CALL @mth_hdr_test_named_set

  ADD r1,r14,r0
  MOVI r2,1
  MOVI r3,0x1314
  MOVHI r3,0x1112
  CALL @mth_hdr_test_named_set

  ADD r1,r14,r0
  MOVI r2,2
  MOVI r3,1
  MOVHI r3,0x3F80
  CALL @mth_hdr_test_named_set

  ADD r1,r14,r0
  MOVI r2,3
  MOVI r3,0x2324
  MOVHI r3,0x2122
  CALL @mth_hdr_test_named_set

  ; Read each field only through its named getter.
  ADD r1,r14,r0
  MOVI r2,0
  MOVI r3,0x0304
  MOVHI r3,0x0102
  CALL @mth_hdr_test_named_get_expect

  ADD r1,r14,r0
  MOVI r2,1
  MOVI r3,0x1314
  MOVHI r3,0x1112
  CALL @mth_hdr_test_named_get_expect

  ADD r1,r14,r0
  MOVI r2,2
  MOVI r3,1
  MOVHI r3,0x3F80
  CALL @mth_hdr_test_named_get_expect

  ADD r1,r14,r0
  MOVI r2,3
  MOVI r3,0x2324
  MOVHI r3,0x2122
  CALL @mth_hdr_test_named_get_expect

  ; Independent byte checks and reserved sentinels after named writes.
  ADD r1,r14,r0
  MOVI r2,0
  MOVI r3,0x0304
  MOVHI r3,0x0102
  CALL @mth_hdr_test_bytes

  ADD r1,r14,r0
  MOVI r2,1
  MOVI r3,0x1314
  MOVHI r3,0x1112
  CALL @mth_hdr_test_bytes

  ADD r1,r14,r0
  MOVI r2,2
  MOVI r3,1
  MOVHI r3,0x3F80
  CALL @mth_hdr_test_bytes

  ADD r1,r14,r0
  MOVI r2,3
  MOVI r3,0x2324
  MOVHI r3,0x2122
  CALL @mth_hdr_test_bytes

  ADD r1,r14,r0
  CALL @mth_hdr_test_reserved

  LD r15,r0,@mth_hdr_test_named_wrappers_ret
  MOVI r1,1
  RET

; ---------------------------------------------------------------------------
; NANNET0, field non-overlap, boundaries, and invalid requests
; ---------------------------------------------------------------------------

mth_hdr_test_field_isolation:
  ST r15,r0,@mth_hdr_test_isolation_ret
  MOVI r14,42
  CALL @mth_hdr_test_set_all_one

  ; ---- write only field 0 ----
  ADD r1,r14,r0
  MOVI r2,0
  MOVI r3,0xAAAA
  MOVHI r3,0xAAAA
  CALL @mth_hdr_test_set

  ADD r1,r14,r0
  MOVI r2,0
  MOVI r3,0xAAAA
  MOVHI r3,0xAAAA
  CALL @mth_hdr_test_get_expect

  ADD r1,r14,r0
  MOVI r2,1
  MOVI r3,0
  MOVHI r3,0x2200
  ADD r3,r3,r14
  CALL @mth_hdr_test_get_expect

  ADD r1,r14,r0
  MOVI r2,2
  MOVI r3,0
  MOVHI r3,0x3F80
  ADD r3,r3,r14
  CALL @mth_hdr_test_get_expect

  ADD r1,r14,r0
  MOVI r2,3
  MOVI r3,0
  MOVHI r3,0x4400
  ADD r3,r3,r14
  CALL @mth_hdr_test_get_expect

  ; ---- write only field 1 ----
  ADD r1,r14,r0
  MOVI r2,1
  MOVI r3,0xBBBB
  MOVHI r3,0xBBBB
  CALL @mth_hdr_test_set

  ADD r1,r14,r0
  MOVI r2,0
  MOVI r3,0xAAAA
  MOVHI r3,0xAAAA
  CALL @mth_hdr_test_get_expect

  ADD r1,r14,r0
  MOVI r2,1
  MOVI r3,0xBBBB
  MOVHI r3,0xBBBB
  CALL @mth_hdr_test_get_expect

  ADD r1,r14,r0
  MOVI r2,2
  MOVI r3,0
  MOVHI r3,0x3F80
  ADD r3,r3,r14
  CALL @mth_hdr_test_get_expect

  ADD r1,r14,r0
  MOVI r2,3
  MOVI r3,0
  MOVHI r3,0x4400
  ADD r3,r3,r14
  CALL @mth_hdr_test_get_expect

  ; ---- write only field 2 ----
  ADD r1,r14,r0
  MOVI r2,2
  MOVI r3,0xCCCC
  MOVHI r3,0xCCCC
  CALL @mth_hdr_test_set

  ADD r1,r14,r0
  MOVI r2,0
  MOVI r3,0xAAAA
  MOVHI r3,0xAAAA
  CALL @mth_hdr_test_get_expect

  ADD r1,r14,r0
  MOVI r2,1
  MOVI r3,0xBBBB
  MOVHI r3,0xBBBB
  CALL @mth_hdr_test_get_expect

  ADD r1,r14,r0
  MOVI r2,2
  MOVI r3,0xCCCC
  MOVHI r3,0xCCCC
  CALL @mth_hdr_test_get_expect

  ADD r1,r14,r0
  MOVI r2,3
  MOVI r3,0
  MOVHI r3,0x4400
  ADD r3,r3,r14
  CALL @mth_hdr_test_get_expect

  ; ---- write only field 3 ----
  ADD r1,r14,r0
  MOVI r2,3
  MOVI r3,0xDDDD
  MOVHI r3,0xDDDD
  CALL @mth_hdr_test_set

  ADD r1,r14,r0
  MOVI r2,0
  MOVI r3,0xAAAA
  MOVHI r3,0xAAAA
  CALL @mth_hdr_test_get_expect

  ADD r1,r14,r0
  MOVI r2,1
  MOVI r3,0xBBBB
  MOVHI r3,0xBBBB
  CALL @mth_hdr_test_get_expect

  ADD r1,r14,r0
  MOVI r2,2
  MOVI r3,0xCCCC
  MOVHI r3,0xCCCC
  CALL @mth_hdr_test_get_expect

  ADD r1,r14,r0
  MOVI r2,3
  MOVI r3,0xDDDD
  MOVHI r3,0xDDDD
  CALL @mth_hdr_test_get_expect

  ; Byte-level confirmation of all four final field payloads.
  ADD r1,r14,r0
  MOVI r2,0
  MOVI r3,0xAAAA
  MOVHI r3,0xAAAA
  CALL @mth_hdr_test_bytes

  ADD r1,r14,r0
  MOVI r2,1
  MOVI r3,0xBBBB
  MOVHI r3,0xBBBB
  CALL @mth_hdr_test_bytes

  ADD r1,r14,r0
  MOVI r2,2
  MOVI r3,0xCCCC
  MOVHI r3,0xCCCC
  CALL @mth_hdr_test_bytes

  ADD r1,r14,r0
  MOVI r2,3
  MOVI r3,0xDDDD
  MOVHI r3,0xDDDD
  CALL @mth_hdr_test_bytes

  ADD r1,r14,r0
  CALL @mth_hdr_test_reserved

  LD r15,r0,@mth_hdr_test_isolation_ret
  MOVI r1,1
  RET

; Head 0 is the NANNET0/control head. Store distinctive values there and
; prove it is addressable at the arena base and independent of head 1.
mth_hdr_test_nannet0:
  ST r15,r0,@mth_hdr_test_nannet0_ret

  ; first_hyperedge = 0x4E414E30 ("NAN0")
  MOVI r1,0
  MOVI r2,0
  MOVI r3,0x4E30
  MOVHI r3,0x4E41
  CALL @mth_hdr_test_set

  ; state = 0
  MOVI r1,0
  MOVI r2,1
  MOVI r3,0
  CALL @mth_hdr_test_set

  ; score = 1.0
  MOVI r1,0
  MOVI r2,2
  MOVI r3,0
  MOVHI r3,0x3F80
  CALL @mth_hdr_test_set

  ; generation = 1
  MOVI r1,0
  MOVI r2,3
  MOVI r3,1
  CALL @mth_hdr_test_set

  MOVI r1,0
  MOVI r2,0
  MOVI r3,0x4E30
  MOVHI r3,0x4E41
  CALL @mth_hdr_test_get_expect
  MOVI r1,0
  MOVI r2,0
  MOVI r3,0x4E30
  MOVHI r3,0x4E41
  CALL @mth_hdr_test_bytes

  MOVI r1,0
  MOVI r2,1
  MOVI r3,0
  CALL @mth_hdr_test_get_expect
  MOVI r1,0
  MOVI r2,1
  MOVI r3,0
  CALL @mth_hdr_test_bytes

  MOVI r1,0
  MOVI r2,2
  MOVI r3,0
  MOVHI r3,0x3F80
  CALL @mth_hdr_test_get_expect
  MOVI r1,0
  MOVI r2,2
  MOVI r3,0
  MOVHI r3,0x3F80
  CALL @mth_hdr_test_bytes

  MOVI r1,0
  MOVI r2,3
  MOVI r3,1
  CALL @mth_hdr_test_get_expect
  MOVI r1,0
  MOVI r2,3
  MOVI r3,1
  CALL @mth_hdr_test_bytes

  MOVI r1,0
  CALL @mth_hdr_test_reserved

  ; Head 1 must still contain its set_all values.
  MOVI r1,1
  MOVI r2,0
  MOVI r3,0
  MOVHI r3,0x1100
  ADDI r3,r3,1
  CALL @mth_hdr_test_get_expect
  MOVI r1,1
  MOVI r2,1
  MOVI r3,0
  MOVHI r3,0x2200
  ADDI r3,r3,1
  CALL @mth_hdr_test_get_expect
  MOVI r1,1
  MOVI r2,2
  MOVI r3,0
  MOVHI r3,0x3F80
  ADDI r3,r3,1
  CALL @mth_hdr_test_get_expect
  MOVI r1,1
  MOVI r2,3
  MOVI r3,0
  MOVHI r3,0x4400
  ADDI r3,r3,1
  CALL @mth_hdr_test_get_expect

  ; Head 0 must not have touched head 1's reserved bytes either.
  MOVI r1,1
  CALL @mth_hdr_test_reserved

  LD r15,r0,@mth_hdr_test_nannet0_ret
  MOVI r1,1
  RET

; Head 255 is the last real head. Its record ends at arena byte 32,767.
; Exercise 0xFFFFFFFF, zero, and the finite f32 extrema, then leave the
; record at its second-pass values for the final integrity check.
mth_hdr_test_boundaries:
  ST r15,r0,@mth_hdr_test_boundaries_ret

  ; ---- first pass: low/high payload boundaries ----
  MOVI r1,255
  MOVI r2,0
  MOVI r3,0xFFFF
  MOVHI r3,0xFFFF
  CALL @mth_hdr_test_set
  MOVI r1,255
  MOVI r2,1
  MOVI r3,0
  CALL @mth_hdr_test_set
  MOVI r1,255
  MOVI r2,2
  MOVI r3,0xFFFF
  MOVHI r3,0xFF7F
  CALL @mth_hdr_test_set
  MOVI r1,255
  MOVI r2,3
  MOVI r3,0xFFFF
  MOVHI r3,0xFFFF
  CALL @mth_hdr_test_set

  MOVI r1,255
  MOVI r2,0
  MOVI r3,0xFFFF
  MOVHI r3,0xFFFF
  CALL @mth_hdr_test_get_expect
  MOVI r1,255
  MOVI r2,1
  MOVI r3,0
  CALL @mth_hdr_test_get_expect
  MOVI r1,255
  MOVI r2,2
  MOVI r3,0xFFFF
  MOVHI r3,0xFF7F
  CALL @mth_hdr_test_get_expect
  MOVI r1,255
  MOVI r2,3
  MOVI r3,0xFFFF
  MOVHI r3,0xFFFF
  CALL @mth_hdr_test_get_expect

  ; ---- score: -0.0 and +0.0 payloads ----
  MOVI r1,255
  MOVI r2,2
  MOVI r3,0
  MOVHI r3,0x8000
  CALL @mth_hdr_test_set
  MOVI r1,255
  MOVI r2,2
  MOVI r3,0
  MOVHI r3,0x8000
  CALL @mth_hdr_test_get_expect
  MOVI r1,255
  MOVI r2,2
  MOVI r3,0
  MOVHI r3,0x8000
  CALL @mth_hdr_test_bytes

  MOVI r1,255
  MOVI r2,2
  MOVI r3,0
  CALL @mth_hdr_test_set
  MOVI r1,255
  MOVI r2,2
  MOVI r3,0
  CALL @mth_hdr_test_get_expect
  MOVI r1,255
  MOVI r2,2
  MOVI r3,0
  CALL @mth_hdr_test_bytes

  ; ---- second pass: complementary boundary values ----
  MOVI r1,255
  MOVI r2,0
  MOVI r3,0
  CALL @mth_hdr_test_set
  MOVI r1,255
  MOVI r2,1
  MOVI r3,0xFFFF
  MOVHI r3,0xFFFF
  CALL @mth_hdr_test_set
  MOVI r1,255
  MOVI r2,2
  MOVI r3,0xFFFF
  MOVHI r3,0x7F7F
  CALL @mth_hdr_test_set
  MOVI r1,255
  MOVI r2,3
  MOVI r3,0
  CALL @mth_hdr_test_set

  MOVI r1,255
  MOVI r2,0
  MOVI r3,0
  CALL @mth_hdr_test_get_expect
  MOVI r1,255
  MOVI r2,1
  MOVI r3,0xFFFF
  MOVHI r3,0xFFFF
  CALL @mth_hdr_test_get_expect
  MOVI r1,255
  MOVI r2,2
  MOVI r3,0xFFFF
  MOVHI r3,0x7F7F
  CALL @mth_hdr_test_get_expect
  MOVI r1,255
  MOVI r2,3
  MOVI r3,0
  CALL @mth_hdr_test_get_expect

  ; Byte-level checks for all four fields at the final head.
  MOVI r1,255
  MOVI r2,0
  MOVI r3,0
  CALL @mth_hdr_test_bytes
  MOVI r1,255
  MOVI r2,1
  MOVI r3,0xFFFF
  MOVHI r3,0xFFFF
  CALL @mth_hdr_test_bytes
  MOVI r1,255
  MOVI r2,2
  MOVI r3,0xFFFF
  MOVHI r3,0x7F7F
  CALL @mth_hdr_test_bytes
  MOVI r1,255
  MOVI r2,3
  MOVI r3,0
  CALL @mth_hdr_test_bytes

  MOVI r1,255
  CALL @mth_hdr_test_reserved

  ; The last record must not spill into the guard word after the arena.
  CALL @mth_hdr_test_guards

  LD r15,r0,@mth_hdr_test_boundaries_ret
  MOVI r1,1
  RET

; r1 = head, r2 = field, r3 = expected cause. The getter must reject and
; clear its value output.
mth_hdr_test_reject_get:
  ST r15,r0,@mth_hdr_test_reject_get_ret
  ST r1,r0,@mth_hdr_test_reject_get_head
  ST r2,r0,@mth_hdr_test_reject_get_field
  ST r3,r0,@mth_hdr_test_reject_get_cause

  ADD r1,r11,r0
  LD r2,r0,@mth_hdr_test_reject_get_head
  LD r3,r0,@mth_hdr_test_reject_get_field
  CALL @mth_mirror_head_record_get
  CMP r1,r0
  JMP[NE] @mth_hdr_test_fail
  CMP r10,r0
  JMP[NE] @mth_hdr_test_fail
  CMP r2,r0
  JMP[NE] @mth_hdr_test_fail
  LD r4,r0,@mth_hdr_test_reject_get_cause
  CMP r9,r4
  JMP[NE] @mth_hdr_test_fail

  LD r15,r0,@mth_hdr_test_reject_get_ret
  MOVI r1,1
  RET

; r1 = head, r2 = field, r3 = value, r4 = expected cause.
mth_hdr_test_reject_set:
  ST r15,r0,@mth_hdr_test_reject_set_ret
  ST r1,r0,@mth_hdr_test_reject_set_head
  ST r2,r0,@mth_hdr_test_reject_set_field
  ST r3,r0,@mth_hdr_test_reject_set_value
  ST r4,r0,@mth_hdr_test_reject_set_cause

  ADD r1,r11,r0
  LD r2,r0,@mth_hdr_test_reject_set_head
  LD r3,r0,@mth_hdr_test_reject_set_field
  LD r4,r0,@mth_hdr_test_reject_set_value
  CALL @mth_mirror_head_record_set
  CMP r1,r0
  JMP[NE] @mth_hdr_test_fail
  LD r4,r0,@mth_hdr_test_reject_set_cause
  CMP r9,r4
  JMP[NE] @mth_hdr_test_fail

  LD r15,r0,@mth_hdr_test_reject_set_ret
  MOVI r1,1
  RET

; Named wrappers must validate the head just like the generic routines.
; r1 = head, r2 = expected cause.
mth_hdr_test_named_get_reject:
  ST r15,r0,@mth_hdr_test_named_get_ret
  ST r1,r0,@mth_hdr_test_named_get_head
  ST r2,r0,@mth_hdr_test_named_get_cause

  ADD r1,r11,r0
  LD r2,r0,@mth_hdr_test_named_get_head
  CALL @mth_mirror_head_record_get_first_hyperedge
  CMP r1,r0
  JMP[NE] @mth_hdr_test_fail
  CMP r10,r0
  JMP[NE] @mth_hdr_test_fail
  CMP r2,r0
  JMP[NE] @mth_hdr_test_fail
  LD r4,r0,@mth_hdr_test_named_get_cause
  CMP r9,r4
  JMP[NE] @mth_hdr_test_fail

  LD r15,r0,@mth_hdr_test_named_get_ret
  MOVI r1,1
  RET

; r1 = head, r2 = value, r3 = expected cause.
mth_hdr_test_named_set_reject:
  ST r15,r0,@mth_hdr_test_named_set_ret
  ST r1,r0,@mth_hdr_test_named_set_head
  ST r2,r0,@mth_hdr_test_named_set_value
  ST r3,r0,@mth_hdr_test_named_set_cause

  ADD r1,r11,r0
  LD r2,r0,@mth_hdr_test_named_set_head
  LD r3,r0,@mth_hdr_test_named_set_value
  CALL @mth_mirror_head_record_set_first_hyperedge
  CMP r1,r0
  JMP[NE] @mth_hdr_test_fail
  LD r4,r0,@mth_hdr_test_named_set_cause
  CMP r9,r4
  JMP[NE] @mth_hdr_test_fail

  LD r15,r0,@mth_hdr_test_named_set_ret
  MOVI r1,1
  RET

mth_hdr_test_invalid:
  ST r15,r0,@mth_hdr_test_invalid_ret

  ; Head 7 keeps the set_all values so every rejected call can be followed
  ; by a complete 128-byte record comparison.
  MOVI r14,7
  CALL @mth_hdr_test_set_all_one

  ; ---- get rejection: head limit and reserved field selectors ----
  MOVI r1,256
  MOVI r2,0
  MOVI r3,1
  CALL @mth_hdr_test_reject_get

  ; Head validation precedes field validation.
  MOVI r1,256
  MOVI r2,31
  MOVI r3,1
  CALL @mth_hdr_test_reject_get

  MOVI r1,257
  MOVI r2,3
  MOVI r3,1
  CALL @mth_hdr_test_reject_get

  MOVI r1,0xFFFF
  MOVHI r1,0xFFFF
  MOVI r2,0
  MOVI r3,1
  CALL @mth_hdr_test_reject_get

  MOVI r1,0
  MOVI r2,4
  MOVI r3,2
  CALL @mth_hdr_test_reject_get

  MOVI r1,255
  MOVI r2,5
  MOVI r3,2
  CALL @mth_hdr_test_reject_get

  MOVI r1,0
  MOVI r2,31
  MOVI r3,2
  CALL @mth_hdr_test_reject_get

  MOVI r1,0
  MOVI r2,0xFFFF
  MOVHI r2,0xFFFF
  MOVI r3,2
  CALL @mth_hdr_test_reject_get

  ; ---- set rejection: head limit ----
  MOVI r1,256
  MOVI r2,0
  MOVI r3,0
  MOVI r4,1
  CALL @mth_hdr_test_reject_set

  ; Head validation precedes field validation.
  MOVI r1,256
  MOVI r2,4
  MOVI r3,0
  MOVI r4,1
  CALL @mth_hdr_test_reject_set

  MOVI r1,257
  MOVI r2,3
  MOVI r3,0xFFFF
  MOVHI r3,0xFFFF
  MOVI r4,1
  CALL @mth_hdr_test_reject_set

  MOVI r1,0xFFFF
  MOVHI r1,0xFFFF
  MOVI r2,0
  MOVI r3,0
  MOVI r4,1
  CALL @mth_hdr_test_reject_set

  ; ---- set rejection: every reserved-tail selector is denied ----
  MOVI r1,7
  MOVI r2,4
  MOVI r3,0xFFFF
  MOVHI r3,0xFFFF
  MOVI r4,2
  CALL @mth_hdr_test_reject_set

  MOVI r1,7
  MOVI r2,5
  MOVI r3,0xFFFF
  MOVHI r3,0xFFFF
  MOVI r4,2
  CALL @mth_hdr_test_reject_set

  MOVI r1,7
  MOVI r2,31
  MOVI r3,0xFFFF
  MOVHI r3,0xFFFF
  MOVI r4,2
  CALL @mth_hdr_test_reject_set

  MOVI r1,7
  MOVI r2,32
  MOVI r3,0xFFFF
  MOVHI r3,0xFFFF
  MOVI r4,2
  CALL @mth_hdr_test_reject_set

  ; Field 32 would begin exactly at the byte after head 255's record.
  MOVI r1,255
  MOVI r2,32
  MOVI r3,0xFFFF
  MOVHI r3,0xFFFF
  MOVI r4,2
  CALL @mth_hdr_test_reject_set

  MOVI r1,7
  MOVI r2,0xFFFF
  MOVHI r2,0xFFFF
  MOVI r3,0xFFFF
  MOVHI r3,0xFFFF
  MOVI r4,2
  CALL @mth_hdr_test_reject_set

  ; A zero payload is still a reserved write and must be denied.
  MOVI r1,7
  MOVI r2,4
  MOVI r3,0
  MOVI r4,2
  CALL @mth_hdr_test_reject_set

  ; ---- named wrappers enforce the same head gate ----
  MOVI r1,256
  MOVI r2,1
  CALL @mth_hdr_test_named_get_reject

  MOVI r1,256
  MOVI r2,0xFFFF
  MOVHI r2,0xFFFF
  MOVI r3,1
  CALL @mth_hdr_test_named_set_reject

  ; All rejected calls must leave the target records byte-for-byte
  ; unchanged. Head 8 is the would-be spill target of head 7 + field 32.
  MOVI r14,7
  CALL @mth_hdr_test_check_all_one
  MOVI r14,8
  CALL @mth_hdr_test_check_all_one

  ; Field 32 on head 255 must not touch the guard after the arena.
  CALL @mth_hdr_test_guards

  LD r15,r0,@mth_hdr_test_invalid_ret
  MOVI r1,1
  RET

; Recheck the three special records after all invalid requests. Together the
; four field reads and the reserved-word scan cover all 32 payload words.
mth_hdr_test_final_integrity:
  ST r15,r0,@mth_hdr_test_final_ret

  ; head 7: unchanged set_all record
  MOVI r14,7
  CALL @mth_hdr_test_check_all_one

  ; head 0: NANNET0 values
  MOVI r1,0
  MOVI r2,0
  MOVI r3,0x4E30
  MOVHI r3,0x4E41
  CALL @mth_hdr_test_get_expect
  MOVI r1,0
  MOVI r2,1
  MOVI r3,0
  CALL @mth_hdr_test_get_expect
  MOVI r1,0
  MOVI r2,2
  MOVI r3,0
  MOVHI r3,0x3F80
  CALL @mth_hdr_test_get_expect
  MOVI r1,0
  MOVI r2,3
  MOVI r3,1
  CALL @mth_hdr_test_get_expect
  MOVI r1,0
  CALL @mth_hdr_test_reserved

  ; head 255: second-pass boundary values
  MOVI r1,255
  MOVI r2,0
  MOVI r3,0
  CALL @mth_hdr_test_get_expect
  MOVI r1,255
  MOVI r2,1
  MOVI r3,0xFFFF
  MOVHI r3,0xFFFF
  CALL @mth_hdr_test_get_expect
  MOVI r1,255
  MOVI r2,2
  MOVI r3,0xFFFF
  MOVHI r3,0x7F7F
  CALL @mth_hdr_test_get_expect
  MOVI r1,255
  MOVI r2,3
  MOVI r3,0
  CALL @mth_hdr_test_get_expect
  MOVI r1,255
  CALL @mth_hdr_test_reserved

  LD r15,r0,@mth_hdr_test_final_ret
  MOVI r1,1
  RET

; ---------------------------------------------------------------------------
; Marker helpers
; ---------------------------------------------------------------------------

mth_hdr_test_fail:
  LA r1,@mth_hdr_test_bad
  CALL @mth_hdr_test_puts
  HALT

; r1 = NUL-terminated string; writes bytes through PUTC.
mth_hdr_test_puts:
  MOVI r4,255
mth_hdr_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_hdr_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_hdr_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_hdr_test_puts_word

; ---------------------------------------------------------------------------
; Static scratch (all located outside the 32 KiB arena)
; ---------------------------------------------------------------------------
.org 2048
mth_hdr_test_get_ret:
.word 0
mth_hdr_test_get_head:
.word 0
mth_hdr_test_get_field:
.word 0
mth_hdr_test_get_value:
.word 0
mth_hdr_test_set_ret:
.word 0
mth_hdr_test_set_head:
.word 0
mth_hdr_test_set_field:
.word 0
mth_hdr_test_set_value:
.word 0
mth_hdr_test_reject_get_ret:
.word 0
mth_hdr_test_reject_get_head:
.word 0
mth_hdr_test_reject_get_field:
.word 0
mth_hdr_test_reject_get_cause:
.word 0
mth_hdr_test_reject_set_ret:
.word 0
mth_hdr_test_reject_set_head:
.word 0
mth_hdr_test_reject_set_field:
.word 0
mth_hdr_test_reject_set_value:
.word 0
mth_hdr_test_reject_set_cause:
.word 0
mth_hdr_test_named_get_ret:
.word 0
mth_hdr_test_named_get_head:
.word 0
mth_hdr_test_named_get_cause:
.word 0
mth_hdr_test_named_set_ret:
.word 0
mth_hdr_test_named_set_head:
.word 0
mth_hdr_test_named_set_value:
.word 0
mth_hdr_test_named_set_cause:
.word 0
mth_hdr_test_named_get_wrap_ret:
.word 0
mth_hdr_test_named_get_wrap_head:
.word 0
mth_hdr_test_named_get_wrap_field:
.word 0
mth_hdr_test_named_get_wrap_value:
.word 0
mth_hdr_test_named_set_wrap_ret:
.word 0
mth_hdr_test_named_set_wrap_head:
.word 0
mth_hdr_test_named_set_wrap_field:
.word 0
mth_hdr_test_named_set_wrap_value:
.word 0
mth_hdr_test_named_wrappers_ret:
.word 0
mth_hdr_test_set_all_ret:
.word 0
mth_hdr_test_set_all_one_ret:
.word 0
mth_hdr_test_check_all_ret:
.word 0
mth_hdr_test_check_all_one_ret:
.word 0
mth_hdr_test_check_initial_ret:
.word 0
mth_hdr_test_isolation_ret:
.word 0
mth_hdr_test_nannet0_ret:
.word 0
mth_hdr_test_boundaries_ret:
.word 0
mth_hdr_test_invalid_ret:
.word 0
mth_hdr_test_final_ret:
.word 0
mth_hdr_test_pattern:
.word 0
mth_hdr_test_expected:
.word 0

.org 4096
mth_hdr_test_pass:
.str "MTH MIRROR HEAD RECORD IO PASS\n"
mth_hdr_test_bad:
.str "MTH MIRROR HEAD RECORD IO FAIL\n"
