; MTH 3-byte associative-memory reserved-row hash — NaN16 integer only.
;
; Round 043 reserves 128 native memory rows for online contexts. This kernel
; maps a 3-byte context to one deterministic row inside a caller-supplied
; 128-row reserve window:
;
;   context = b0 | b1<<8 | b2<<16
;   h       = (context * 0x9E3779B1) >> 16
;   slot    = reserve_base + (h & 127)
;
; Collisions are expected; the caller decides how to handle them. The hash is
; an address mapping, not a learned cache and not a claim of perfect hashing.
;
; ABI (r13=1):
;   r1 = b0, 0..255
;   r2 = b1, 0..255
;   r3 = b2, 0..255
;   r4 = reserve_base, 0..32257 so the 128-row window stays inside 32385 slots
; Success: r1=1, r9=0, r5=slot.
; Rejection: r1=0, r9=1 bad byte, r9=2 bad reserve window; r5=0.
;
; Clobbers r1-r6 and flags; preserves r0, r7-r15. No float, memory access,
; CALL, static storage, or host math.

mth_byte_assoc3_reserve_u32:
  MOVI r0,0

  MOVI r5,255
  CMP r5,r1
  JMP[LT] @mth_assoc3_bad_byte
  CMP r5,r2
  JMP[LT] @mth_assoc3_bad_byte
  CMP r5,r3
  JMP[LT] @mth_assoc3_bad_byte

  MOVI r5,32257
  CMP r5,r4
  JMP[LT] @mth_assoc3_bad_base

  ; context
  SHL r5,r2,8
  BOOL.14 r5,r5,r1
  SHL r6,r3,16
  BOOL.14 r5,r5,r6

  ; multiplicative mix, high 16 bits, low 7 bits
  MOVI r6,0x79B1
  MOVHI r6,0x9E37
  MUL r5,r5,r6
  SHR r5,r5,16
  MOVI r6,127
  BOOL.8 r5,r5,r6
  ADD r5,r5,r4

  MOVI r1,1
  MOVI r9,0
  RET

mth_assoc3_bad_byte:
  MOVI r9,1
  JMP @mth_assoc3_reject
mth_assoc3_bad_base:
  MOVI r9,2
mth_assoc3_reject:
  MOVI r5,0
  MOVI r1,0
  RET
