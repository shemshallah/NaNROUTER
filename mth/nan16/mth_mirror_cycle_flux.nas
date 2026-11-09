; MTH Round 023 reference-cycle flux primitive — NaN16 float32 only.
;
; Canonical physical mirror root (byte-addressed profile):
;   8,388,608 bytes total
;   head region     [0, 32768)          256 x 128 B
;   pair region     [32768, 8388608)    32,640 x 256 B
;   pair record     lane 0 at +0, lane 1 at +128
;   cycle_flux      f32 at lane 0 + 116
;
; For the reference head 0 and a non-reference unordered pair (i,j), the
; root-0 fundamental circulation is
;
;   F_ij = x_0i + x_ij - x_0j
;
; evaluated as exactly two IEEE-754 binary32 operations in this order:
;
;   t = FADD(x_0i, x_ij)
;   F = FSUB(t, x_0j)
;
; There is no reassociation, no fused multiply-add, no host math, and no
; third float operation. The selected order matters: (x_0i + x_ij) - x_0j
; is not, in general, bit-identical to (x_0i - x_0j) + x_ij.
;
; ABI (r13 = 1):
;   r1 = x_0i address   (byte address of a 4-byte little-endian f32 field)
;   r2 = x_ij address   (byte address of a 4-byte little-endian f32 field)
;   r3 = x_0j address   (byte address of a 4-byte little-endian f32 field)
;   r4 = destination pair lane-0 address (byte address of the 128-byte lane)
;   r13 = 1
;
; Success:
;   r1 = 1, r9 = 0
;   bytes [r4+116, r4+120) = F_ij as IEEE-754 binary32 little-endian
;   no other byte of the pair record is written.
;
; Rejection:
;   r1 = 0, r9 = cause, destination bytes completely unchanged.
;   cause 1: x_0i is non-finite (NaN, +inf, or -inf)
;   cause 2: x_ij is non-finite (NaN, +inf, or -inf)
;   cause 3: x_0j is non-finite (NaN, +inf, or -inf)
;   cause 4: the finite inputs produce a non-finite result
;
; The three input preflights run in r1, r2, r3 order before either float
; operation. The first bad input wins. The result is checked before the first
; destination store, so a rejection is atomic.
;
; The physical profile is byte-addressed. LDB/STB address the four payload
; bytes of a NaN16 word little-endian; the kernel assembles and stores the
; binary32 payload explicitly. All arithmetic on addresses and field bytes is
; integer NaN16; only FADD and FSUB touch float payloads.
;
; Clobbers r1, r5-r11 and flags. Preserves r0, r2-r4, r12-r15.
; Leaf routine: no CALL, no static scratch, no return slot.

mth_mirror_cycle_flux_f32:
mth_mirror_cycle_flux:
  MOVI r11,0
  MOVHI r11,0x7F80           ; r11 = 0x7F800000 exponent-all-ones mask

  ; ---- x_0i: load four little-endian payload bytes ----
  LDB r5,r1,0
  LDB r10,r1,1
  SHL r10,r10,8
  BOOL.14 r5,r5,r10
  LDB r10,r1,2
  SHL r10,r10,16
  BOOL.14 r5,r5,r10
  LDB r10,r1,3
  SHL r10,r10,24
  BOOL.14 r5,r5,r10

  ; x_0i finite: exponent bits must not be all ones.
  BOOL.8 r10,r5,r11
  CMP r10,r11
  JMP[EQ] @mth_mirror_cycle_flux_nonfinite_a

  ; ---- x_ij ----
  LDB r6,r2,0
  LDB r10,r2,1
  SHL r10,r10,8
  BOOL.14 r6,r6,r10
  LDB r10,r2,2
  SHL r10,r10,16
  BOOL.14 r6,r6,r10
  LDB r10,r2,3
  SHL r10,r10,24
  BOOL.14 r6,r6,r10

  BOOL.8 r10,r6,r11
  CMP r10,r11
  JMP[EQ] @mth_mirror_cycle_flux_nonfinite_b

  ; ---- x_0j ----
  LDB r8,r3,0
  LDB r10,r3,1
  SHL r10,r10,8
  BOOL.14 r8,r8,r10
  LDB r10,r3,2
  SHL r10,r10,16
  BOOL.14 r8,r8,r10
  LDB r10,r3,3
  SHL r10,r10,24
  BOOL.14 r8,r8,r10

  BOOL.8 r10,r8,r11
  CMP r10,r11
  JMP[EQ] @mth_mirror_cycle_flux_nonfinite_c

  ; ---- exactly two float operations, required order ----
  FADD r7,r5,r6              ; t = x_0i + x_ij
  FSUB r7,r7,r8              ; F = t - x_0j

  ; Finite-result preflight before the first destination store.
  BOOL.8 r10,r7,r11
  CMP r10,r11
  JMP[EQ] @mth_mirror_cycle_flux_nonfinite_result

  ; ---- store f32 at lane0 + 116, little-endian, four bytes ----
  ADDI r10,r4,116
  STB r7,r10,0
  SHR r6,r7,8
  STB r6,r10,1
  SHR r6,r6,8
  STB r6,r10,2
  SHR r6,r6,8
  STB r6,r10,3

  MOVI r9,0                  ; success has no failure cause
  MOVI r1,1
  RET

mth_mirror_cycle_flux_nonfinite_a:
  MOVI r9,1
  JMP @mth_mirror_cycle_flux_reject
mth_mirror_cycle_flux_nonfinite_b:
  MOVI r9,2
  JMP @mth_mirror_cycle_flux_reject
mth_mirror_cycle_flux_nonfinite_c:
  MOVI r9,3
  JMP @mth_mirror_cycle_flux_reject
mth_mirror_cycle_flux_nonfinite_result:
  MOVI r9,4
mth_mirror_cycle_flux_reject:
  MOVI r1,0
  RET
