; MTH exact 24-byte episodic copy — NaN16 only.
;
; This is the Round 033 episodic-copy primitive: copy one short byte string
; of 1..24 bytes between two byte addresses in the canonical 8 MiB payload
; byte space. The operation is exact; every payload bit is transported
; without numeric conversion, sign handling, or byte-order change.
;
; Canonical byte space
; --------------------
; The universe is 8,388,608 payload bytes, byte addresses [0, 0x800000).
; LDB/STB address the four little-endian payload bytes of one NaN16 word:
;
;   byte address a  ->  payload byte (a & 3) of word (a >> 2)
;
; The byte space is therefore the packed b2..b5 payload space of the first
; 2,097,152 NaN16 words. This routine performs no word-level class math.
; STB is the canonical byte-store operation: it read-modify-writes the
; selected payload byte and normalises that word's class nibble to the
; neutral +q/+q class (10). Every other payload byte of the word, and every
; byte outside the destination span, is preserved. Payload bits, which are
; this ABI's data, are copied exactly.
;
; ABI (r13 = 1)
; -------------
; Inputs:
;   r1 = source byte address
;   r2 = destination byte address
;   r3 = length, 1..24
;
; Success:
;   r1 = 1
;   r4 = bytes copied (equal to r3)
;   r9 = 0
;
; Exact alias (source == destination):
;   The call succeeds as a no-op: r1 = 1, r4 = r3, r9 = 0, and no STB is
;   issued. This is the only aliasing accepted.
;
; Rejection:
;   r1 = 0
;   r4 = 0
;   r9 = cause
;   No byte anywhere is written.
;
; Cause codes, in validation order:
;   1  length is zero
;   2  length is greater than 24
;   3  source range is not wholly inside [0, 0x800000): source+length
;      wraps the 32-bit byte address space, or the exclusive end exceeds
;      0x800000
;   4  destination range is not wholly inside [0, 0x800000):
;      destination+length wraps, or the exclusive end exceeds 0x800000
;   5  the two equal-length ranges partially overlap but source is not
;      exactly the destination (strict partial aliasing)
;
; The complete preflight runs before the first LDB/STB, so every rejection
; is atomic even when the ranges would partially overlap. Length 0 is
; rejected even when source == destination, because the accepted domain is
; 1..24.
;
; Overlap law for two ranges of the same positive length n:
;   [s, s+n) and [d, d+n) intersect  <=>  |d-s| < n.
; Here, after the wrap and canonical checks, that is:
;   s < d  and d < s+n  -> cause 5
;   d < s  and s < d+n  -> cause 5
; Adjacency (d == s+n or s == d+n) is not overlap and is accepted.
;
; Register and instruction contract
; ---------------------------------
; Clobbers r1, r2, r4, r5, r6, r7, r9, and flags.
; Preserves r0, r3, r8, r10-r15. The routine is a leaf: no CALL, no static
; scratch, no self-modification, and no host operation. It uses integer
; comparisons, LDB, STB, and branches only.

mth_byte_copy24:
  ; ---- length gate: 1..24 ----
  CMP r3,r0
  JMP[EQ] @mth_byte_copy24_bad_len0

  MOVI r5,24
  CMP r5,r3
  JMP[LT] @mth_byte_copy24_bad_len

  ; ---- source span gate ----
  MOVI r6,0
  MOVHI r6,0x0080            ; r6 = 0x00800000 = 8,388,608
  ADD r5,r1,r3               ; src_end = source + length
  CMP r5,r1
  JMP[LT] @mth_byte_copy24_bad_src   ; 32-bit wrap
  CMP r5,r6
  JMP[GT] @mth_byte_copy24_bad_src   ; src_end > 8 MiB

  ; ---- destination span gate ----
  ADD r7,r2,r3               ; dst_end = destination + length
  CMP r7,r2
  JMP[LT] @mth_byte_copy24_bad_dst   ; 32-bit wrap
  CMP r7,r6
  JMP[GT] @mth_byte_copy24_bad_dst   ; dst_end > 8 MiB

  ; ---- exact alias is the only accepted overlap ----
  CMP r1,r2
  JMP[EQ] @mth_byte_copy24_alias

  ; ---- reject strict partial overlap ----
  CMP r1,r2
  JMP[LT] @mth_byte_copy24_src_low
  ; destination < source: overlap iff source < dst_end
  CMP r1,r7
  JMP[LT] @mth_byte_copy24_bad_overlap
  JMP @mth_byte_copy24_copy

mth_byte_copy24_src_low:
  ; source < destination: overlap iff destination < src_end
  CMP r2,r5
  JMP[LT] @mth_byte_copy24_bad_overlap

mth_byte_copy24_copy:
  MOVI r4,0                  ; bytes copied
mth_byte_copy24_loop:
  LDB r5,r1,0                ; next exact payload byte
  STB r5,r2,0                ; store the same byte at the destination
  ADDI r1,r1,1
  ADDI r2,r2,1
  ADDI r4,r4,1
  CMP r4,r3
  JMP[LT] @mth_byte_copy24_loop

  ADD r1,r13,r0              ; success (r13 = 1)
  ADD r9,r0,r0
  RET

mth_byte_copy24_alias:
  ADD r4,r3,r0               ; no-op success still reports the byte count
  ADD r1,r13,r0
  ADD r9,r0,r0
  RET

mth_byte_copy24_bad_len0:
  MOVI r9,1
  JMP @mth_byte_copy24_reject
mth_byte_copy24_bad_len:
  MOVI r9,2
  JMP @mth_byte_copy24_reject
mth_byte_copy24_bad_src:
  MOVI r9,3
  JMP @mth_byte_copy24_reject
mth_byte_copy24_bad_dst:
  MOVI r9,4
  JMP @mth_byte_copy24_reject
mth_byte_copy24_bad_overlap:
  MOVI r9,5
mth_byte_copy24_reject:
  MOVI r1,0
  MOVI r4,0
  RET
