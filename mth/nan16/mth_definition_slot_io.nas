; MTH 24-byte definition-slot I/O — native NaN16 only.
;
; Canonical physical profile (docs/MIRROR_MEMORY_LAYOUT.md, mirror-memory/v1):
;
;   universe            8,388,608 bytes, byte addresses [0, 0x800000)
;   pair region         [32,768, 8,388,608)
;   pair records        32,640 records x 256 bytes
;   pair id             1..32,640; id 0 is the void sentinel
;   record base        32768 + (id-1)*256
;   lane 0             record base + 0
;   lane 1             record base + 128
;
; Chosen definition slot (definition-slot/v1)
; -------------------------------------------
; The slot is the otherwise reserved 24-byte tail of lane 1:
;
;   lane 1 offset       104..127 inclusive (24 bytes)
;   record offset       232..255 inclusive (24 bytes)
;   absolute            base+232 .. base+255 inclusive
;   half-open span      [base+232, base+256)
;
; Equivalently, with B(id) = 32768 + (id-1)*256:
;
;   slot(id) = [B(id)+232, B(id)+256)  =  [B(id)+256-24, B(id+1))
;
; The start is four-byte aligned and the span is exactly six 32-bit guest
; payload words. The interval is the canonical lane-1 `reserved` field. This
; module deliberately uses it as a definition slot, so on success those 24
; bytes are no longer zero and the strict mirror-memory/v1 "reserved must be
; zero" invariant no longer holds for the selected pair. That is a recorded
; extension, not a new profile file and not a canonical-layout change.
;
; Fields that are preserved
; -------------------------
; The slot does not overlap any canonical field. In particular the module
; never writes:
;
;   lane 0 + 116  cycle_flux  f32
;   lane 0 + 120  generation  u32
;   lane 0 + 124  flags       u32
;   lane 1 bytes 128..231     residual[26]
;   any byte outside [base+232, base+256)
;
; Guard
; -----
; The canonical lane-0 generation word at record offset 120 is used as a
; read-only 32-bit generation guard. It is the only non-overlapping u32
; field available for this purpose in a v1 pair record. The caller passes
; the expected generation in r4; store and load succeed only when it equals
; the current little-endian u32 at base+120. The guard is compared, never
; advanced or rewritten. A separate persisted magic word would have to
; overlap a canonical field, so none is introduced: the generation word is
; the magic/version guard.
;
; The slot payload itself is opaque bytes. There is no finite, numeric,
; encoding, or textual test: any 24 byte values, including 0x00 and 0xFF,
; transport exactly. The count is not variable; every success moves exactly
; 24 bytes.
;
; ABI (r13 = 1, r0 = 0)
; --------------------
;   mth_definition_slot_store
;     r1 = pair id              (u32, 1..32,640)
;     r2 = source byte address  (24 readable bytes within the 8 MiB universe)
;     r3 = byte count           (must be exactly 24)
;     r4 = expected generation  (u32 guard, equals u32 at record base+120)
;     success: r1 = 1, r9 = 0, r10 = 0
;     reject : r1 = 0, r9 = cause, r10 = 0; no byte anywhere is changed
;
;   mth_definition_slot_load
;     r1 = pair id              (u32, 1..32,640)
;     r2 = destination address  (24 writable bytes within the 8 MiB universe)
;     r3 = byte count           (must be exactly 24)
;     r4 = expected generation  (u32 guard, equals u32 at record base+120)
;     success: r1 = 1, r9 = 0, r10 = 0
;     reject : r1 = 0, r9 = cause, r10 = 0; the destination is untouched
;
; Rejection causes, in validation order:
;   1  pair id is 0 or greater than 32,640
;   2  byte count is not exactly 24
;   3  expected generation does not equal the u32 at record base+120
;   4  the computed slot span is outside [32,768, 8,388,608), wraps the
;      32-bit byte address space, or starts inside the head region
;   5  the source/destination span wraps the 32-bit byte address space or
;      is not wholly inside [0, 8,388,608)
;
; Causes 1 and 2 are checked before any address is formed. Cause 3 is checked
; before the slot address is returned. For a valid id and length, cause 4 is
; a defensive profile guard rather than a reachable state. All checks finish
; before the first store, so a rejected store/load mutates no byte. Because the
; slot is at the end of the record, a successful store touches exactly its
; 24 payload bytes; the following pair's record begins at the exclusive end.
;
; Byte and class behavior
; -----------------------
; Both routines move bytes with LDB/STB. The six slot payload words therefore
; take NaN16 class nibble 10 (the STB word-write rule), and load applies the
; same normalization to the caller-owned destination words it touches. The
; 24 payload bytes themselves round-trip exactly. No byte outside the slot is
; written; class nibbles outside the six slot words are not modified.
;
; Register contract
; -----------------
; Both entry points set r0 = 0 and leave it at 0. They preserve r2, r3, r4,
; r11-r15 and clobber r1, r5-r10 and flags. No floating-point instruction,
; no static scratch, no self-modification, and no host arithmetic is used.
;
; This is a storage transport only. It does not select a pair, enforce the
; mirror residual invariant, validate definition contents, advance a
; generation, reserve adjacent slots, or synchronize concurrent writers.
; Source state must be at least 24 readable bytes; destination state must be
; at least 24 writable bytes; neither may overlap the slot if a caller
; expects an overlap-safe copy.

.equ MTH_DEF_SLOT_BYTES          24
.equ MTH_DEF_SLOT_LANE1_OFFSET   104
.equ MTH_DEF_SLOT_RECORD_OFFSET  232
.equ MTH_DEF_SLOT_PAIR_MAX       32640
.equ MTH_DEF_SLOT_GENERATION_OFF 120
.equ MTH_DEF_SLOT_PAIR_BASE      32768
.equ MTH_DEF_SLOT_UNIVERSE       8388608

mth_definition_slot_store:
  ADD r10,r15,r0              ; preserve the caller's return link
  MOVI r0,0
  CALL @mth_definition_slot__resolve
  CMP r1,r0
  JMP[EQ] @mth_definition_slot_store_reject

  ADD r7,r5,r0                ; r7 = slot byte cursor
  ADD r8,r2,r0                ; r8 = source byte cursor
  MOVI r9,#MTH_DEF_SLOT_BYTES
mth_definition_slot_store_loop:
  LDB r6,r8,0
  STB r6,r7,0
  ADDI r8,r8,1
  ADDI r7,r7,1
  ADDI r9,r9,-1
  JMP[NE] @mth_definition_slot_store_loop

  MOVI r1,1
  MOVI r9,0
  ADD r15,r10,r0
  MOVI r10,0
  RET

mth_definition_slot_store_reject:
  MOVI r1,0
  ADD r15,r10,r0
  MOVI r10,0
  RET

mth_definition_slot_load:
  ADD r10,r15,r0              ; preserve the caller's return link
  MOVI r0,0
  CALL @mth_definition_slot__resolve
  CMP r1,r0
  JMP[EQ] @mth_definition_slot_load_reject

  ADD r7,r5,r0                ; r7 = slot byte cursor
  ADD r8,r2,r0                ; r8 = destination byte cursor
  MOVI r9,#MTH_DEF_SLOT_BYTES
mth_definition_slot_load_loop:
  LDB r6,r7,0
  STB r6,r8,0
  ADDI r7,r7,1
  ADDI r8,r8,1
  ADDI r9,r9,-1
  JMP[NE] @mth_definition_slot_load_loop

  MOVI r1,1
  MOVI r9,0
  ADD r15,r10,r0
  MOVI r10,0
  RET

mth_definition_slot_load_reject:
  MOVI r1,0
  ADD r15,r10,r0
  MOVI r10,0
  RET

; Internal resolver.
;   in:  r1 = id, r2 = buffer byte address, r3 = count, r4 = expected gen
;   out: r1 = 1, r5 = slot byte address, r9 = 0 on success
;        r1 = 0, r5 = 0, r9 = cause on rejection
; Clobbers r6-r8 and flags; preserves r2-r4 and r10-r15.
mth_definition_slot__resolve:
  ; ---- pair id: unsigned 1..32640 ----
  MOVI r6,#MTH_DEF_SLOT_PAIR_MAX
  CMP r6,r1
  JMP[LT] @mth_definition_slot_bad_id
  CMP r1,r0
  JMP[EQ] @mth_definition_slot_bad_id

  ; ---- exact count: 24 ----
  MOVI r6,#MTH_DEF_SLOT_BYTES
  CMP r3,r6
  JMP[NE] @mth_definition_slot_bad_count

  ; ---- record base = 32768 + (id-1)*256 ----
  ADDI r6,r1,-1
  SHL r6,r6,8
  MOVI r7,#MTH_DEF_SLOT_PAIR_BASE
  ADD r6,r6,r7
  ADD r5,r6,r0

  ; ---- read-only generation guard at record base+120 ----
  ADDI r7,r5,#MTH_DEF_SLOT_GENERATION_OFF
  SHR r7,r7,2
  LD r7,r7,0
  CMP r7,r4
  JMP[NE] @mth_definition_slot_bad_generation

  ; ---- slot = base+232, exactly 24 bytes, ends at base+256 ----
  ADDI r5,r5,#MTH_DEF_SLOT_RECORD_OFFSET
  ADDI r7,r5,#MTH_DEF_SLOT_BYTES
  CMP r7,r5
  JMP[LT] @mth_definition_slot_bad_slot_bounds
  MOVI r8,0
  MOVHI r8,0x0080             ; r8 = 0x00800000 = 8,388,608
  CMP r8,r7
  JMP[LT] @mth_definition_slot_bad_slot_bounds
  MOVI r8,#MTH_DEF_SLOT_PAIR_BASE
  CMP r5,r8
  JMP[LT] @mth_definition_slot_bad_slot_bounds

  ; ---- source/destination span: no 32-bit wrap and end <= 8 MiB ----
  ADDI r7,r2,#MTH_DEF_SLOT_BYTES
  CMP r7,r2
  JMP[LT] @mth_definition_slot_bad_buffer
  MOVI r8,0
  MOVHI r8,0x0080
  CMP r8,r7
  JMP[LT] @mth_definition_slot_bad_buffer

  MOVI r1,1
  MOVI r9,0
  RET

mth_definition_slot_bad_id:
  MOVI r9,1
  JMP @mth_definition_slot_bad
mth_definition_slot_bad_count:
  MOVI r9,2
  JMP @mth_definition_slot_bad
mth_definition_slot_bad_generation:
  MOVI r9,3
  JMP @mth_definition_slot_bad
mth_definition_slot_bad_slot_bounds:
  MOVI r9,4
  JMP @mth_definition_slot_bad
mth_definition_slot_bad_buffer:
  MOVI r9,5
mth_definition_slot_bad:
  MOVI r1,0
  MOVI r5,0
  RET
