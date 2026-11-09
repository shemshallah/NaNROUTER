; MTH Round 023 in-place Hodge projection — NaN16 float32 only.
;
; Canonical physical mirror root (byte-addressed profile):
;   8,388,608 bytes total
;   head region     [0, 32768)          256 x 128 B
;   pair region     [32768, 8388608)    32,640 x 256 B
;   pair record     lane 0 at +0, lane 1 at +128
;   first f32       at each lane start (lane0 +0, lane1 +128)
;
; This is the complete 256-vertex graph: every unordered pair (a,b),
; 0 <= a < b <= 255, is present.  Pair(a,b) id is
;
;   pair_id(a,b) = 1 + a*(511-a)/2 + (b-a-1)
;
; and its canonical record begins at byte 32768 + 256*(pair_id-1).
;
; Let x = lane0(a,b) and y = lane1(b,a).  The antisymmetric edge field is
;
;   anti(a,b) = (x - y) / 2
;
; and the vertex divergence is
;
;   d[a] =  sum_{b>a} anti(a,b) - sum_{b<a} anti(b,a).
;
; The Round 023 projection preserves the symmetric part s = (x+y)/2 and
; removes the gradient component of the antisymmetric part:
;
;   s'    = s
;   anti' = anti - (d[a] - d[b]) / 256
;   x'    = s' + anti'
;   y'    = s' - anti'
;
; Both lane-start f32 values are rewritten in place.  The remaining 124
; bytes of each lane are not read or written.  No other pair field, head
; record, or byte of the 8 MiB root is touched.
;
; Why one subtraction is the exact Hodge projection here: on the complete
; graph with N = 256 vertices the unnormalised Laplacian is L = 256*I - J.
; The proposed gradient edge h(a,b) = (d[a]-d[b])/256 has divergence
;
;   sum_b h(a,b) = d[a] - (sum_b d[b])/256 = d[a],
;
; because the complete-graph divergence sums to zero.  Hence anti - h is
; divergence-free, and h is exactly the gradient component.  This is a
; closed-form complete-graph solve, not an iterative approximation.  It is
; also the same operator as Round 023 `hodge_in_place`, expressed with
; binary32 intermediates instead of the C++ prototype's binary64 staging.
;
; ABI (r13 = 1):
;   r1 = pair-region byte base, canonically 32768 (must be divisible by 4)
;   r2 = caller-owned divergence scratch, 256 f32 words
;   returns r1 = 1, r9 = 0 on success
;           r1 = 0, r9 = 1 if any lane-start f32 is non-finite
;
; On success the scratch holds the 256 pre-projection divergences d[0..255]
; in vertex order.  They are useful for auditing; the pair lanes already
; hold the projected values.
;
; On rejection the first bad lane word (lane0 before lane1, increasing pair
; id) wins.  A complete finite-domain preflight runs before the divergence
; scratch is written and before any pair lane is written, so a rejection is
; atomic with respect to the root and the scratch.
;
; Domain rule: binary32 exponent bits all ones (NaN, +inf, -inf) are
; rejected.  This is exactly ((payload & 0x7F800000) == 0x7F800000).
;
; Numeric policy: every value operation is a binary32 FADD, FSUB, or FMUL.
; The constants are exact binary32 values: 1/2 (0x3F000000) and 1/256
; (0x3B800000).  There is no FMA, no reassociation, no double promotion,
; no host math, and no hidden accumulation in a wider format.  Divergence
; accumulation order is increasing b inside increasing a, with d[a] added
; before and d[b] subtracted after for each pair.  The projection scan uses
; the same a,b order.
;
; Working set: the 8 MiB root plus 256 caller-owned scratch words.  Time is
; O(256^2) = 32,640 pair visits per pass and O(256) memory.  The pair
; region is never copied or materialised into a second full-field buffer.
;
; Clobbers r0-r12 and r14; sets r0 = 0 and preserves r13 and r15.  Leaf
; routine: no CALL, no static return slot, no static scratch.

mth_mirror_hodge_projection:
  MOVI r0,0
  ; r3 = pair-region word base
  SHR r3,r1,2

  ; r12 = exact binary32 1/2
  MOVI r12,0
  MOVHI r12,0x3F00
  ; r14 = exact binary32 1/256
  MOVI r14,0
  MOVHI r14,0x3B80
  ; r10 = binary32 exponent-all-ones test mask
  MOVI r10,0
  MOVHI r10,0x7F80

  ; ---- finite-domain preflight over both lane starts of all 32,640 pairs ----
  MOVI r4,0                    ; a = 0
mth_hodge_preflight_a:
  MOVI r6,511
  SUB r6,r6,r4                 ; 511 - a
  MUL r6,r4,r6                 ; a*(511-a)
  SHR r6,r6,1                  ; /2, exact by parity
  SHL r6,r6,6                  ; *64 words = *256 bytes
  ADD r6,r6,r3                 ; first record word for this a
  ADD r5,r4,r13                ; b = a + 1
mth_hodge_preflight_b:
  MOVI r7,256
  CMP r5,r7
  JMP[GE] @mth_hodge_preflight_next_a

  LD r7,r6,0                   ; lane0 f32
  BOOL.8 r7,r7,r10
  CMP r7,r10
  JMP[EQ] @mth_hodge_reject

  LD r7,r6,32                  ; lane1 f32 (128 bytes = 32 words)
  BOOL.8 r7,r7,r10
  CMP r7,r10
  JMP[EQ] @mth_hodge_reject

  ADDI r6,r6,64                 ; next pair record
  ADD r5,r5,r13
  JMP @mth_hodge_preflight_b

mth_hodge_preflight_next_a:
  ADD r4,r4,r13
  MOVI r7,256
  CMP r4,r7
  JMP[LT] @mth_hodge_preflight_a

  ; ---- zero the 256-word divergence scratch ----
  MOVI r4,0
  ADD r6,r2,r0
mth_hodge_zero_divergence:
  ST r0,r6,0
  ADD r6,r6,r13
  ADD r4,r4,r13
  MOVI r7,256
  CMP r4,r7
  JMP[LT] @mth_hodge_zero_divergence

  ; ---- divergence pass: d[a] += anti, d[b] -= anti ----
  MOVI r4,0                    ; a = 0
mth_hodge_divergence_a:
  MOVI r6,511
  SUB r6,r6,r4
  MUL r6,r4,r6
  SHR r6,r6,1
  SHL r6,r6,6
  ADD r6,r6,r3
  ADD r5,r4,r13                ; b = a + 1
mth_hodge_divergence_b:
  MOVI r7,256
  CMP r5,r7
  JMP[GE] @mth_hodge_divergence_next_a

  LD r7,r6,0                   ; x
  LD r8,r6,32                  ; y
  FSUB r7,r7,r8                ; x - y
  FMUL r7,r7,r12               ; anti = (x-y)/2

  ADD r8,r2,r4                 ; &d[a]
  LD r9,r8,0
  FADD r9,r9,r7
  ST r9,r8,0

  ADD r8,r2,r5                 ; &d[b]
  LD r9,r8,0
  FSUB r9,r9,r7
  ST r9,r8,0

  ADDI r6,r6,64
  ADD r5,r5,r13
  JMP @mth_hodge_divergence_b

mth_hodge_divergence_next_a:
  ADD r4,r4,r13
  MOVI r7,256
  CMP r4,r7
  JMP[LT] @mth_hodge_divergence_a

  ; ---- in-place projection pass ----
  MOVI r4,0                    ; a = 0
mth_hodge_project_a:
  MOVI r6,511
  SUB r6,r6,r4
  MUL r6,r4,r6
  SHR r6,r6,1
  SHL r6,r6,6
  ADD r6,r6,r3
  ADD r11,r2,r4                ; &d[a]
  LD r11,r11,0                 ; da
  ADD r5,r4,r13                ; b = a + 1
mth_hodge_project_b:
  MOVI r7,256
  CMP r5,r7
  JMP[GE] @mth_hodge_project_next_a

  LD r7,r6,0                   ; x
  LD r8,r6,32                  ; y

  FADD r9,r7,r8                ; x + y
  FMUL r9,r9,r12               ; s = (x+y)/2

  FSUB r7,r7,r8                ; x - y
  FMUL r7,r7,r12               ; anti = (x-y)/2

  ADD r8,r2,r5                 ; &d[b]
  LD r10,r8,0                  ; db
  FSUB r8,r11,r10              ; da - db
  FMUL r8,r8,r14               ; gradient = (da-db)/256
  FSUB r7,r7,r8                ; anti' = anti - gradient

  FADD r8,r9,r7                ; x' = s + anti'
  FSUB r10,r9,r7               ; y' = s - anti'
  ST r8,r6,0
  ST r10,r6,32

  ADDI r6,r6,64
  ADD r5,r5,r13
  JMP @mth_hodge_project_b

mth_hodge_project_next_a:
  ADD r4,r4,r13
  MOVI r7,256
  CMP r4,r7
  JMP[LT] @mth_hodge_project_a

  MOVI r9,0
  MOVI r1,1
  RET

mth_hodge_reject:
  MOVI r9,1
  MOVI r1,0
  RET
