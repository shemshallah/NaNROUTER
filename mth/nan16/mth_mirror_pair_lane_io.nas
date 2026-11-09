; MTH canonical mirror-pair lane field I/O — native NaN16 only.
;
; Canonical physical layout (docs/MIRROR_MEMORY_LAYOUT.md, mirror-memory/v1):
;
;   universe            8,388,608 bytes, byte addresses [0, 0x800000)
;   pair region         [32,768, 8,388,608)
;   pair records        32,640 records x 256 bytes
;   pair id             1..32,640; id 0 is the void sentinel
;   record base        32768 + (id-1)*256
;   lane 0             record base + 0
;   lane 1             record base + 128
;
; Typed field map inside one record (all fields are exactly 4 bytes):
;
;   field id   lane 0 offset   lane 1 offset   type   name
;   --------   -------------   -------------   ----   -----------------
;   0..25      0..100         128..228        f32    residual[0..25]
;   26         104             reserved        u32    relation_type
;   27         108             reserved        f32    confidence
;   28         112             reserved        u32    hyperedge_head
;   29         116             reserved        f32    cycle_flux
;   30         120             reserved        u32    generation
;   31         124             reserved        u32    flags
;
; lane 1 bytes 232..255 (field ids 26..31 in lane 1) are reserved in v1
; and are never read or written as fields. Lane 0 has no reserved bytes in
; the field block: its 32 four-byte words tile [0,128) exactly.
;
; The physical profile is byte-addressed through NaN16 LDB/STB byte space.
; A field is one four-byte guest payload word: byte address
;
;   addr = 32768 + (id-1)*256 + lane*128 + field*4
;
; is always a multiple of four, so the whole field is one payload word and
; never straddles a word or a record boundary.
;
; ABI (r13 = 1)
; -------------
;   mth_mirror_pair_lane_get
;     r1 = pair id          (u32, 1..32,640)
;     r2 = lane             (u32, 0 or 1)
;     r3 = field id         (u32, 0..31, lane-1 reserved fields rejected)
;     success: r1 = 1, r2 = the exact 32-bit field payload, r9 = 0
;              r10 mirrors the same payload for parity with the canonical
;              head-record I/O ABI
;     reject : r1 = 0, r2 = 0, r10 = 0, r9 = cause (below)
;
;   mth_mirror_pair_lane_set
;     r1 = pair id          (u32, 1..32,640)
;     r2 = lane             (u32, 0 or 1)
;     r3 = field id         (u32, 0..31, lane-1 reserved fields rejected)
;     r4 = exact 32-bit field payload to store
;     success: r1 = 1, r9 = 0
;     reject : r1 = 0, r9 = cause; no byte anywhere is changed
;
; Rejection causes, in validation order:
;   1  pair id is 0 or greater than 32,640
;   2  lane is greater than 1
;   3  field is greater than 31, or field 26..31 on lane 1 (reserved bytes)
;   4  the computed field span is outside the 8 MiB universe, wraps the
;      32-bit byte address space, or starts inside the 32 KiB head region
;   5  set only: the destination word does not carry a valid NaN16 class
;      nibble (LDN returns 0xFFFFFFFF), so a class-preserving write is not
;      possible
;
; Cause 1 is checked before cause 2, cause 2 before cause 3, cause 3 before
; cause 4, and cause 5 only after the other gates have passed. A valid id and
; field always address inside the pair region, so cause 4 is a defensive
; profile guard rather than a reachable state for the documented domain.
;
; Class and field preservation
; ----------------------------
; Reads use LDB over the four little-endian payload bytes; they never write.
; Writes use LDN to capture the destination word's class nibble and STW to
; replace only that word's 32-bit payload while restoring the same nibble.
; Consequently:
;   - the field's exact 32-bit payload round-trips, including any f32 bit
;     pattern (this transport makes no numeric conversion and no finite
;     test; finiteness is a schema invariant owned by callers);
;   - all other bytes of the destination word keep the same NaN faces;
;   - every other field word in the 256-byte record is byte-for-byte
;     unchanged;
;   - the 24 reserved lane-1 bytes are never written.
; A destination word with invalid NaN heads is rejected rather than having
; its unreadable class silently replaced.
;
; Register contract
; -----------------
; Both entry points set r0 = 0 and leave it at 0. They clobber r1, r2,
; r5-r10 and flags. They preserve r3, r4, r11-r15. No floating-point
; instruction, no static scratch, no self-modification, and no host
; arithmetic are used.

.equ MTH_PAIR_LANE_RESIDUAL_FIRST 0
.equ MTH_PAIR_LANE_RESIDUAL_LAST  25
.equ MTH_PAIR_LANE_RELATION_TYPE  26
.equ MTH_PAIR_LANE_CONFIDENCE     27
.equ MTH_PAIR_LANE_HYPEREDGE_HEAD 28
.equ MTH_PAIR_LANE_CYCLE_FLUX     29
.equ MTH_PAIR_LANE_GENERATION     30
.equ MTH_PAIR_LANE_FLAGS          31
.equ MTH_PAIR_LANE_FIELD_LAST     31

mth_mirror_pair_lane_get:
  ADD r10,r15,r0              ; preserve the caller's return link
  MOVI r0,0
  CALL @mth_mirror_pair_lane__addr
  CMP r1,r0
  JMP[EQ] @mth_mirror_pair_lane_get_reject

  ; Assemble the little-endian payload word from four addressable bytes.
  LDB r2,r5,0
  LDB r6,r5,1
  SHL r6,r6,8
  BOOL.14 r2,r2,r6
  LDB r6,r5,2
  SHL r6,r6,16
  BOOL.14 r2,r2,r6
  LDB r6,r5,3
  SHL r6,r6,24
  BOOL.14 r2,r2,r6

  MOVI r1,1
  MOVI r9,0
  ADD r15,r10,r0
  ADD r10,r2,r0              ; mirror the payload in the head-I/O result slot
  RET

mth_mirror_pair_lane_get_reject:
  MOVI r1,0
  MOVI r2,0
  ADD r15,r10,r0
  MOVI r10,0
  RET

mth_mirror_pair_lane_set:
  ADD r10,r15,r0              ; preserve the caller's return link
  MOVI r0,0
  CALL @mth_mirror_pair_lane__addr
  CMP r1,r0
  JMP[EQ] @mth_mirror_pair_lane_set_reject

  ; One field is exactly one payload word. Capture its class nibble first.
  ADD r6,r5,r0
  SHR r6,r6,2
  LDN r7,r6,0
  MOVI r8,0xFFFF
  MOVHI r8,0xFFFF             ; r8 = 0xFFFFFFFF: invalid-head sentinel
  CMP r7,r8
  JMP[EQ] @mth_mirror_pair_lane_set_bad_class

  ; Replace the payload, restore the same class nibble, write nothing else.
  STW r4,r6,r7
  MOVI r1,1
  MOVI r9,0
  ADD r15,r10,r0
  RET

mth_mirror_pair_lane_set_bad_class:
  MOVI r1,0
  MOVI r9,5
  ADD r15,r10,r0
  RET

mth_mirror_pair_lane_set_reject:
  MOVI r1,0
  ADD r15,r10,r0
  RET

; Internal resolver.
;   in:  r1 = id, r2 = lane, r3 = field
;   out: r1 = 1, r5 = absolute byte address, r9 = 0 on success
;        r1 = 0, r5 = 0, r9 = cause on rejection
; Clobbers r6-r8; preserves r2-r4 and r10-r15 (r15 is the CALL link).
mth_mirror_pair_lane__addr:
  ; ---- pair id: unsigned 1..32640 ----
  MOVI r6,32640
  CMP r6,r1
  JMP[LT] @mth_mirror_pair_lane_bad_id
  CMP r1,r0
  JMP[EQ] @mth_mirror_pair_lane_bad_id

  ; ---- lane: unsigned 0..1 ----
  MOVI r6,1
  CMP r6,r2
  JMP[LT] @mth_mirror_pair_lane_bad_lane

  ; ---- field: unsigned 0..31 ----
  MOVI r6,#MTH_PAIR_LANE_FIELD_LAST
  CMP r6,r3
  JMP[LT] @mth_mirror_pair_lane_bad_field

  ; Lane 1 has residuals only; 26..31 are the reserved 24-byte tail.
  CMP r2,r0
  JMP[EQ] @mth_mirror_pair_lane_addr_compute
  MOVI r6,#MTH_PAIR_LANE_RESIDUAL_LAST
  CMP r6,r3
  JMP[LT] @mth_mirror_pair_lane_bad_field

mth_mirror_pair_lane_addr_compute:
  ; addr = 32768 + (id-1)*256 + lane*128 + field*4
  ADDI r6,r1,-1
  SHL r6,r6,8
  MOVI r7,32768
  ADD r6,r6,r7
  SHL r7,r2,7
  ADD r6,r6,r7
  SHL r7,r3,2
  ADD r5,r6,r7

  ; Span guard: no 32-bit wrap and end <= 0x800000 (end is exclusive).
  ADDI r6,r5,4
  CMP r6,r5
  JMP[LT] @mth_mirror_pair_lane_bad_universe
  MOVI r7,0
  MOVHI r7,0x0080            ; r7 = 0x00800000 = 8,388,608
  CMP r7,r6
  JMP[LT] @mth_mirror_pair_lane_bad_universe

  ; A field may never begin in the 32 KiB head region.
  MOVI r7,32768
  CMP r5,r7
  JMP[LT] @mth_mirror_pair_lane_bad_universe

  MOVI r1,1
  MOVI r9,0
  RET

mth_mirror_pair_lane_bad_id:
  MOVI r9,1
  JMP @mth_mirror_pair_lane_bad
mth_mirror_pair_lane_bad_lane:
  MOVI r9,2
  JMP @mth_mirror_pair_lane_bad
mth_mirror_pair_lane_bad_field:
  MOVI r9,3
  JMP @mth_mirror_pair_lane_bad
mth_mirror_pair_lane_bad_universe:
  MOVI r9,4
mth_mirror_pair_lane_bad:
  MOVI r1,0
  MOVI r5,0
  RET
