; MTH NaN16 core — first native kernel
; This file contains mathematical code only in NaN16.
; ABI: r13 = 1. mth_rot2_class: r1=n -> r1=rot2(n).
; mth_bswapm64: r1=address -> BSWAPM the word at that address in place.
; BSWAPM is the existing NaN16 full eight-byte reversal: it swaps both
; NaN faces and reverses the 32-bit payload byte order. It is distinct from
; the redundant double-endian pair-voting codec in n16de.nas.

mth_rot2_class:
  MOVI r2,3
  BOOL.8 r2,r1,r2
  SHL r2,r2,2
  SHR r3,r1,2
  MOVI r4,3
  BOOL.8 r3,r3,r4
  BOOL.14 r1,r2,r3
  RET

; Explicit wrapper around the frozen NaN16 face-swap operation.
; Caller supplies a writable word address in r1.
mth_double_endian:
  BSWAPM r1,0
  RET
