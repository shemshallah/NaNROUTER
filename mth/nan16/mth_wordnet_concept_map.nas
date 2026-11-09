; MTH WordNet concept coordinate map — native NaN16 integer kernel.
;
; THIS IS DETERMINISTIC HASHING, NOT A SEMANTIC MAP.
; The result says only where a caller may place a WordNet concept/relation in
; the 256-head mirror coordinate space. It does not encode synonymy, taxonomy,
; similarity, or any learned meaning. Different concepts are expected to share
; a head, and some distinct ordinals collapse to exactly the same coordinates.
;
; Mapping for a u32 concept ordinal n:
;
;   head  h = ((n * 2654435761) >> 24) & 255
;             2654435761 = 0x9E3779B1 (the 32-bit golden-ratio odd multiplier)
;             MUL keeps the low 32 bits of the product.
;   peer  p = (h + 1 + ((n >> 8) & 255)) & 255
;
;   reject if p == h; otherwise canonicalize the unordered endpoints
;   a = min(h,p), b = max(h,p) and use the canonical mirror pair formula:
;
;   pair_id = 1 + a*(511-a)/2 + (b-a-1)         1..32,640
;   offset  = 32,768 + (pair_id-1)*256           32,768..8,388,352
;
; a*(511-a) is always even, so SHR #1 is exact. Pair id 0 is the void sentinel
; and is never returned on success; it is returned only by the rejection path.
;
; Ordinal validation
; ------------------
; The ABI carries a u32 register, so every value 0..4,294,967,295 is in the
; declared concept-ordinal domain. This matches the integration source, whose
; concept ids are full 32-bit hashes. The kernel therefore does not invent a
; narrower WordNet maximum. It validates the derived endpoint relation: a
; derived p == h has no unordered pair and is rejected.
;
; Collision behavior (intentional, not an error)
; ----------------------------------------------
; The head is only the top byte of a 32-bit product, so at most 256 heads
; exist. The peer depends on ordinal bits 8..15 only. Thus all 2^32 ordinals
; can produce at most 256*256 = 65,536 coordinate outcomes, of which 256*255 =
; 65,280 are accepted; the other 256 (d = (n>>8)&255 == 255) all reject.
; For uniformly distributed ordinals the rejection rate is exactly 1/256.
;
; Examples of collisions:
;   n = 0x00000004 and n = 0x00000094 both give head 120, peer 121,
;   pair_id 23,461, offset 6,038,528 — identical coordinates.
;   n = 0x00000000 and n = 0x000001D2 both give head 0, but peer 1 vs 2 and
;   pair_id 1 vs 2 — same head, different pair.
; Pair_id is injective over unordered endpoint pairs; equal pair ids mean the
; same (head, peer) pair. Ordinal-level collisions are expected and callers
; that need concept identity must keep the ordinal/key alongside the pair.
;
; ABI (r13 = 1, r0 = 0):
;   r1 = ordinal n (u32)
;   returns r1 = 1 on success
;           r3 = head h (0..255)
;           r4 = pair_id (1..32,640)
;           r5 = record byte offset = 32,768 + (pair_id-1)*256
;           r6 = peer p (0..255), p != h
;
;   returns r1 = 0 on rejection (derived p == h)
;           r3 = r4 = r5 = r6 = 0
;
; Register effects: r0-r6 and flags are clobbered; r7-r15 are preserved.
; r0 is never written. Leaf routine: no CALL, no memory access.
;
; Arithmetic is NaN16 ADD, MUL, SHR, and BOOL.8 (the AND truth table) only.
; Subtraction is performed as addition of a two's-complement value obtained
; with MUL by 0xFFFFFFFF; no subtract opcode, left shift, divide, float, table,
; or host arithmetic is used. MOVI/MOVHI load constants; CMP/JMP control the
; two exits.

mth_wordnet_concept_map:
  ; ---- head h = ((n * 0x9E3779B1) >> 24) & 255 ----
  MOVI r3,0x79B1
  MOVHI r3,0x9E37
  MUL r3,r1,r3                          ; low 32 bits of product
  SHR r3,r3,24
  MOVI r5,0x00FF
  BOOL.8 r3,r3,r5                       ; r3 = h
  ADD r5,r3,r0                          ; save h

  ; ---- peer p = (h + 1 + ((n >> 8) & 255)) & 255 ----
  SHR r4,r1,8
  MOVI r6,0x00FF
  BOOL.8 r4,r4,r6                       ; d = bits 8..15
  ADD r4,r4,r5                          ; h + d
  MOVI r6,1
  ADD r4,r4,r6                          ; h + d + 1
  MOVI r6,0x00FF
  BOOL.8 r4,r4,r6                       ; r4 = p
  ADD r6,r4,r0                          ; save p

  ; ---- equal endpoints have no unordered pair: pair id 0 / void ----
  CMP r5,r6
  JMP[EQ] @mth_wordnet_concept_map_reject

  ; ---- canonicalize a = min(h,p), b = max(h,p) into r3,r4 ----
  ADD r3,r5,r0
  ADD r4,r6,r0
  CMP r3,r4
  JMP[LE] @mth_wordnet_concept_map_ordered
  ADD r2,r3,r0
  ADD r3,r4,r0
  ADD r4,r2,r0
mth_wordnet_concept_map_ordered:
  ; r3 = a, r4 = b, r5 = h, r6 = p
  ; ---- -a = a * 0xFFFFFFFF (mod 2^32) ----
  MOVI r2,0xFFFF
  MOVHI r2,0xFFFF
  MUL r2,r3,r2                          ; r2 = -a

  ; ---- pair_id = 1 + a*(511-a)/2 + (b-a-1) ----
  MOVI r1,511
  ADD r1,r1,r2                          ; 511 - a
  MUL r1,r3,r1                          ; a*(511-a)
  SHR r1,r1,1                           ; exact /2
  MOVI r3,1
  ADD r1,r1,r3                          ; 1 + half
  ADD r4,r4,r2                          ; b - a
  MOVI r3,0xFFFF
  MOVHI r3,0xFFFF                       ; -1
  ADD r4,r4,r3                          ; b - a - 1
  ADD r1,r1,r4                          ; r1 = pair_id

  ; ---- offset = 32,768 + (pair_id-1)*256 ----
  ADD r4,r1,r3                          ; pair_id - 1
  MOVI r3,256
  MUL r4,r4,r3                          ; (pair_id-1)*256
  MOVI r3,32768
  ADD r4,r4,r3                          ; r4 = offset

  ; ---- publish: r3=head, r4=pair_id, r5=offset, r6=peer ----
  ADD r3,r5,r0
  ADD r5,r4,r0
  ADD r4,r1,r0
  MOVI r1,1
  MOVHI r1,0
  RET

mth_wordnet_concept_map_reject:
  ; Equal derived endpoints: no pair, no record; canonical void outputs.
  MOVI r3,0
  MOVI r4,0
  MOVI r5,0
  MOVI r6,0
  MOVI r1,0
  MOVHI r1,0
  RET
