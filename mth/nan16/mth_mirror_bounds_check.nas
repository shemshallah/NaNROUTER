; MTH canonical mirror-memory address validator — native NaN16 kernel.
;
; Canonical physical layout (8,388,608 bytes total):
;   head region   0 .. 32,767        256 records x 128 bytes
;   pair region   32,768 .. 8,388,607
;                                    32,640 records x 256 bytes
;   pair record   base = 32,768 + (pair_id-1)*256
;   lane 0        base + 0   .. base + 127
;   lane 1        base + 128 .. base + 255
;   field byte    lane_base + field, field in 0..127
;
; ABI:
;   r1 = kind
;          0 = head
;          1 = pair record
;          2 = lane (pair record + 128-byte lane)
;          3 = field byte (lane + byte offset)
;   r2 = a
;          kind 0: head index 0..255
;          kind 1: pair id 1..32640
;          kind 2: pair id 1..32640
;          kind 3: pair id 1..32640
;   r3 = b
;          kind 2: lane 0 or 1
;          kind 3: lane 0 or 1
;   r4 = c
;          kind 3: field byte offset 0..127
;
; Return (all valid kinds):
;   r1 = 1, r3 = start byte, r4 = end byte (exclusive)
; Return (any rejection):
;   r1 = 0, r3 = 0, r4 = 0
;
; Extents:
;   head   [128*h, 128*h+128)              last: [32640, 32768)
;   pair   [32768+256*(id-1), +256)        last: [8388352, 8388608)
;   lane   [pair_base+128*lane, +128)      last: [8388480, 8388608)
;   field  [lane_base+field, +1)           last: [8388607, 8388608)
;
; Rejection classes:
;   - kind other than 0..3 (unsigned)
;   - head index above 255, including 0x80000000/0xFFFFFFFF
;   - pair id 0 or above 32640, including values whose record arithmetic
;     would wrap a 32-bit address
;   - lane other than 0 or 1, including 0x80000000/0xFFFFFFFF
;   - field offset above 127, including 0x80000000/0xFFFFFFFF
;   - an end address that is not greater than its start, or an end above
;     8,388,608 (defence against shifted-address wrap)
;
; Arguments not used by a kind are ignored. Output r3/r4 overwrite the
; caller's b/c registers, so callers read the returned extents only after
; testing r1.
;
; Register effects: r0-r6 and flags are clobbered; r7-r15 are preserved,
; so ordinary CALL/RET works and callers may keep loop state in r7-r14.
; r0 is set to 0 on entry and left at 0 on every return path.
;
; The kernel only validates and computes addresses. It performs no LD/ST to
; the 8 MiB region, so the layout does not have to be materialized in the
; 65,536-word guest for this check to be exact.
;
; Instructions used: MOVI, MOVHI, CMP, JMP, ADD, ADDI, SHL, RET.
; No floating-point instruction and no host arithmetic is used.

mth_mirror_bounds_check:
  MOVI r0,0

  ; ---- kind gate: kind must be 0..3 (unsigned) ----
  MOVI r5,3
  CMP r5,r1
  JMP[LT] @mth_mirror_bounds_reject       ; 3 < kind

  MOVI r5,0
  CMP r1,r5
  JMP[EQ] @mth_mirror_bounds_head
  MOVI r5,1
  CMP r1,r5
  JMP[EQ] @mth_mirror_bounds_pair
  MOVI r5,2
  CMP r1,r5
  JMP[EQ] @mth_mirror_bounds_lane
  JMP @mth_mirror_bounds_field            ; kind == 3

; ---- kind 0: head h in 0..255; [128*h, 128*h+128) ----
mth_mirror_bounds_head:
  MOVI r5,255
  CMP r5,r2
  JMP[LT] @mth_mirror_bounds_reject       ; 255 < h

  SHL r3,r2,7                             ; start = h*128
  MOVI r4,128
  ADD r4,r3,r4                            ; end = start+128

  ; Reject a wrapped or empty extent independently of the shift gate.
  CMP r4,r3
  JMP[LE] @mth_mirror_bounds_reject

  ; end must be <= 32768; this is also the head-region boundary.
  MOVI r5,32768
  CMP r5,r4
  JMP[LT] @mth_mirror_bounds_reject

  MOVI r0,0
  MOVI r1,1
  RET

; ---- kind 1: pair id in 1..32640; [32768+256*(id-1), +256) ----
mth_mirror_bounds_pair:
  MOVI r5,1
  CMP r2,r5
  JMP[LT] @mth_mirror_bounds_reject       ; id < 1
  MOVI r5,32640
  CMP r5,r2
  JMP[LT] @mth_mirror_bounds_reject       ; 32640 < id

  ADDI r5,r2,-1                           ; id-1
  SHL r5,r5,8                             ; (id-1)*256
  MOVI r6,32768
  ADD r5,r5,r6                            ; pair record base

  ADD r3,r5,r0                            ; start
  MOVI r6,256
  ADD r4,r3,r6                            ; end = start+256
  JMP @mth_mirror_bounds_commit

; ---- kind 2: pair id in 1..32640, lane in {0,1} ----
mth_mirror_bounds_lane:
  MOVI r5,1
  CMP r2,r5
  JMP[LT] @mth_mirror_bounds_reject       ; id < 1
  MOVI r5,32640
  CMP r5,r2
  JMP[LT] @mth_mirror_bounds_reject       ; 32640 < id

  MOVI r5,1
  CMP r5,r3
  JMP[LT] @mth_mirror_bounds_reject       ; 1 < lane

  ADDI r5,r2,-1                           ; id-1
  SHL r5,r5,8                             ; (id-1)*256
  MOVI r6,32768
  ADD r5,r5,r6                            ; pair record base

  SHL r6,r3,7                             ; lane*128
  ADD r3,r5,r6                            ; start = pair base + lane*128
  MOVI r6,128
  ADD r4,r3,r6                            ; end = start+128
  JMP @mth_mirror_bounds_commit

; ---- kind 3: pair id in 1..32640, lane in {0,1}, field in 0..127 ----
mth_mirror_bounds_field:
  MOVI r5,1
  CMP r2,r5
  JMP[LT] @mth_mirror_bounds_reject       ; id < 1
  MOVI r5,32640
  CMP r5,r2
  JMP[LT] @mth_mirror_bounds_reject       ; 32640 < id

  MOVI r5,1
  CMP r5,r3
  JMP[LT] @mth_mirror_bounds_reject       ; 1 < lane

  MOVI r5,127
  CMP r5,r4
  JMP[LT] @mth_mirror_bounds_reject       ; 127 < field

  ADDI r5,r2,-1                           ; id-1
  SHL r5,r5,8                             ; (id-1)*256
  MOVI r6,32768
  ADD r5,r5,r6                            ; pair record base

  SHL r6,r3,7                             ; lane*128
  ADD r5,r5,r6                            ; lane base
  ADD r3,r5,r4                            ; start = lane base + field
  ADDI r4,r3,1                            ; end = start+1
  JMP @mth_mirror_bounds_commit

; ---- shared final range check ----
mth_mirror_bounds_commit:
  ; Reject a wrapped or empty extent: end must be strictly greater than
  ; start under unsigned comparison.
  CMP r4,r3
  JMP[LE] @mth_mirror_bounds_reject

  ; Reject an end beyond the 8 MiB root (unsigned compare).
  MOVI r0,0
  MOVHI r0,0x80                           ; 8,388,608
  CMP r0,r4
  JMP[LT] @mth_mirror_bounds_reject       ; 8,388,608 < end

  MOVI r0,0
  MOVI r1,1
  RET

mth_mirror_bounds_reject:
  MOVI r3,0
  MOVI r4,0
  MOVI r1,0
  MOVI r0,0
  RET
