; MTH angular ring address map — NaN16 integer kernel.
;
; The real-head ring is the 255 positions 0..254. NANNET0 is a FIXED port at
; ring position 255 and is never rotated, remapped, or returned as a real lane.
;
; ABI (r13=1):
;   r1 = real lane, integer 0..254
;   r2 = signed angular offset in lanes
; Success:
;   r1 = 1, r9 = 0
;   r3 = mapped real lane in 0..254
;   r4 = 255, the invariant NANNET0 ring position
;   r5 = 1, a flag distinguishing a real mapped lane from the fixed port
; Rejection:
;   r1 = 0, r9 = 1 if lane is outside 0..254 (including 255)
;   r3 = 0, r4 = 255, r5 = 1
;
; The offset is reduced modulo 255 and applied cyclically over the real lanes
; only. NANNET0 therefore cannot be reached by an angular rotation.
;
; Register effects: r0-r5 and flags clobbered; r6-r15 preserved. No float
; instruction, memory access, call, or host arithmetic is used.

mth_ring_angular_map_u32:
  MOVI r0,0

  ; ---- real-lane domain: 0..254 ----
  MOVI r3,254
  CMP r3,r1
  JMP[LT] @mth_ring_angular_bad_lane

  ; ---- signed offset modulo 255 ----
  MOVI r3,255
  MOD r4,r2,r3               ; r4 in -254..254
  ADD r4,r4,r1               ; lane + offset

  ; Normalize into 0..254. At most one add and one subtract are needed.
  CMPS r4,r0
  JMP[GE] @mth_ring_angular_high
  ADD r4,r4,r3
mth_ring_angular_high:
  CMPS r4,r3
  JMP[LT] @mth_ring_angular_publish
  SUB r4,r4,r3

mth_ring_angular_publish:
  ADD r3,r4,r0               ; mapped real lane
  MOVI r4,255                ; fixed NANNET0 port
  MOVI r5,1
  MOVI r1,1
  MOVI r9,0
  RET

mth_ring_angular_bad_lane:
  MOVI r3,0
  MOVI r4,255
  MOVI r5,1
  MOVI r1,0
  MOVI r9,1
  RET
