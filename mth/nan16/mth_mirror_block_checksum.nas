; MTH bounded mirror-root block checksum — NaN16 integer only.
;
; Computes 32-bit FNV-1a over a caller-supplied byte block that must lie
; wholly inside the canonical 8 MiB mirror root:
;
;   root byte space [0, 8388608)
;
; LDB/STB address the four payload bytes of a NaN16 word little-endian, so
; byte address a selects payload byte (a & 3) of word (a >> 2). The root is
; 8,388,608 payload bytes = 2,097,152 payload words.
;
; FNV-1a law (exact, modulo 2^32):
;
;   h = seed
;   for each byte b in increasing address order:
;     h = h XOR b
;     h = h * 0x01000193
;
; The seed is caller-supplied and initialises h directly. The standard FNV
; offset basis 0x811C9DC5 is therefore passed as seed, not assumed by the
; kernel. Multiplication uses the native 32-bit MUL low-word result.
;
; ABI (r13 = 1):
;   r1 = byte address of the block start
;   r2 = byte length, 0..65536
;   r3 = u32 seed (initial hash state)
;
; Success:
;   r1 = 1
;   r4 = 32-bit FNV-1a checksum
;   r5 = bytes processed (equal to r2)
;
; Rejection:
;   r1 = 0
;   r4 = 0
;   r5 = 0
;
; Validation order, before any load:
;   1. r2 == 0                       (zero length)
;   2. r2 > 65536                    (length bound)
;   3. end = r1 + r2 wraps mod 2^32  (end < r1)
;   4. end > 8388608                 (outside the 8 MiB root)
;
; These checks also reject an address at or beyond the root end, because a
; positive length then either exceeds 8388608 or wraps. The kernel is read-
; only: it performs no allocation, no store, no self-modification, and no
; host operation.
;
; Clobbers r1, r4-r8 and flags. Preserves r0, r2, r3, r9-r15.
; Leaf routine: no CALL, no static scratch, no return slot.

mth_mirror_block_checksum:
  ; ---- bounded domain preflight ----
  CMP r2,r0
  JMP[EQ] @mth_mirror_block_checksum_reject   ; zero length

  MOVI r5,0
  MOVHI r5,1                 ; r5 = 65536
  CMP r2,r5
  JMP[GT] @mth_mirror_block_checksum_reject   ; length > 65536

  MOVI r6,0
  MOVHI r6,0x0080            ; r6 = 8388608, the 8 MiB root size
  ADD r5,r1,r2               ; end = address + length (mod 2^32)
  CMP r5,r1
  JMP[LT] @mth_mirror_block_checksum_reject   ; 32-bit wrap/overflow
  CMP r5,r6
  JMP[GT] @mth_mirror_block_checksum_reject   ; end > 8388608

  ; ---- FNV-1a over [r1, r5) ----
  ADD r4,r3,r0               ; h = seed
  MOVI r7,0x0193
  MOVHI r7,0x0100            ; r7 = 0x01000193 FNV prime
mth_mirror_block_checksum_loop:
  LDB r8,r1,0                ; next payload byte, little-end first
  BOOL.6 r4,r4,r8            ; h = h XOR byte
  MUL r4,r4,r7               ; h = h * prime (low 32 bits)
  ADDI r1,r1,1               ; advance one byte address
  CMP r1,r5
  JMP[LT] @mth_mirror_block_checksum_loop

  MOVI r1,1
  ADD r5,r2,r0               ; bytes processed
  RET

mth_mirror_block_checksum_reject:
  MOVI r1,0
  MOVI r4,0
  MOVI r5,0
  RET
