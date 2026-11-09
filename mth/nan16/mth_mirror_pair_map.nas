; MTH canonical mirror-memory pair map — native NaN16 integer kernel.
;
; Canonical layout (byte addresses):
;   total            8,388,608 bytes
;   head region      0 .. 32,767
;   pair region      32,768 .. 8,388,607
;   records          32,640 records x 256 bytes
;   pair record id   1 .. 32,640; id 0 is the void sentinel
;
; For canonical a < b:
;   pair_id = 1 + a*(511-a)/2 + (b-a-1)
;   record  = 32,768 + (pair_id-1)*256
;
; a*(511-a) is always even: if a is even the product is even, and if a is
; odd then 511-a is even. The divide-by-two below is therefore the exact
; integer shift SHR #1, not a rounded operation.
;
; ABI (r13=1):
;   r1 = a (0..255)
;   r2 = b (0..255), a != b
;   returns r1 = 1 on success
;           r3 = pair_id (1..32,640)
;           r4 = record byte offset = 32,768 + (pair_id-1)*256
;           r5 = lane0 byte address = r4
;           r6 = lane1 byte address = r4 + 128
;
; If a > b the two endpoints are canonicalized (swapped) so that lane0 is
; always the lower endpoint and lane1 the higher endpoint. The unordered
; pair map is therefore valid for every in-range a != b.
;
; Rejection (r1 = 0 on return):
;   - a == b (void / no unordered pair)
;   - a or b is outside 0..255 (unsigned compare)
; On rejection r3, r4, r5, and r6 are all cleared to 0.
;
; Register effects: r0-r6 and flags are clobbered; r7-r15 are preserved,
; so ordinary CALL/RET works and callers may keep loop state in r7-r14.
; r0 is set to 0 on entry and left at 0 on every return path.
;
; The kernel only computes addresses. It performs no LD/ST to the pair
; region, so the 8 MiB layout does not have to be materialized in the
; 65,536-word guest for this mapping to be exact.
;
; Instructions used: MOVI, CMP, JMP, ADD, SUB, MUL, SHR, SHL, ADDI, RET.
; No floating-point instruction and no host arithmetic is used.

mth_mirror_pair_map:
  MOVI r0,0

  ; ---- unsigned range gate: a <= 255 and b <= 255 ----
  MOVI r3,255
  CMP r3,r1
  JMP[LT] @mth_mirror_pair_reject       ; 255 < a
  CMP r3,r2
  JMP[LT] @mth_mirror_pair_reject       ; 255 < b

  ; ---- reject the degenerate a == b (void sentinel, never a record) ----
  CMP r1,r2
  JMP[EQ] @mth_mirror_pair_reject

  ; ---- canonicalize endpoints: swap iff b < a ----
  CMP r2,r1
  JMP[GE] @mth_mirror_pair_ordered
  ADD r3,r1,r0
  ADD r1,r2,r0
  ADD r2,r3,r0

mth_mirror_pair_ordered:
  ; ---- pair_id = 1 + a*(511-a)/2 + (b-a-1) ----
  MOVI r3,511
  SUB r3,r3,r1                          ; 511-a
  MUL r3,r1,r3                          ; a*(511-a), exact in 32 bits
  SHR r3,r3,1                           ; /2, exact by parity argument
  ADDI r3,r3,1                          ; 1 + half
  SUB r4,r2,r1                          ; b-a
  ADDI r4,r4,-1                         ; b-a-1
  ADD r3,r3,r4                          ; r3 = pair_id

  ; ---- byte offset = 32,768 + (pair_id-1)*256 ----
  ADDI r4,r3,-1
  SHL r4,r4,8                           ; (pair_id-1)*256
  MOVI r5,32768
  ADD r4,r4,r5

  ; ---- lane addresses: lane0 at record start, lane1 128 bytes later ----
  ADD r5,r4,r0                          ; lane0
  MOVI r6,128
  ADD r6,r4,r6                          ; lane1 = record + 128

  MOVI r1,1
  RET

mth_mirror_pair_reject:
  MOVI r3,0
  MOVI r4,0
  MOVI r5,0
  MOVI r6,0
  MOVI r1,0
  MOVI r0,0
  RET
