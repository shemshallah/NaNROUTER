; MTH reference-cycle gauge-invariance check — NaN16 float32 only.
;
; A reference triangle (0,i,j) has the root-0 circulation
;
;   F = x_0i + x_ij - x_0j
;
; Under a gauge shift of the reference head, x_0i and x_0j both move by the
; same finite scalar g while x_ij is unchanged. The shifted circulation is
;
;   F' = (x_0i + g) + x_ij - (x_0j + g)
;
; and gauge invariance requires F' to equal F. This kernel evaluates both
; forms with exactly the IEEE-754 binary32 operations below, in this order:
;
;   base    = FSUB(FADD(x_0i, x_ij), x_0j)
;   shifted = FSUB(FADD(FADD(x_0i, g), x_ij), FADD(x_0j, g))
;   drift   = FSUB(shifted, base)
;
; and reports PASS when |drift| is at most the declared absolute tolerance
;
;   GAUGE_TOLERANCE = 2^-16 = 1.52587890625e-5 = 0x37800000
;
; The comparison is exact integer work: the sign bit of the finite drift word
; is cleared with 0x7FFFFFFF, and the resulting magnitude bit pattern is
; compared as an unsigned 32-bit integer with 0x37800000. For finite
; nonnegative binary32 words, unsigned bit order is numeric order, so this is
; the same predicate as a float compare without any FCMP tolerance rounding.
;
; ABI (r13 = 1):
;   r1 = x_0i address (byte address of a 4-byte little-endian f32 field)
;   r2 = x_ij address (byte address of a 4-byte little-endian f32 field)
;   r3 = x_0j address (byte address of a 4-byte little-endian f32 field)
;   r4 = g address    (byte address of a 4-byte little-endian f32 field)
;   r13 = 1
;
; Result:
;   r1 = 1, r9 = 0   pass: all inputs finite, all computed words finite, and
;                    |F' - F| <= 2^-16.
;   r1 = 0, r9 = 6   fail: the gauge drift is finite but exceeds 2^-16.
;   r1 = 0, r9 = cause for a rejected input or computation:
;     1: x_0i is non-finite (NaN, +inf, or -inf)
;     2: x_ij is non-finite
;     3: x_0j is non-finite
;     4: g is non-finite
;     5: a finite input produced a non-finite base, shifted value, or drift
;   A caller must test r1 before treating the triangle as gauge-consistent.
;
; DOMAIN POLICY:
;   The four input preflights run in r1, r2, r3, r4 order before the first
;   float operation, so the first bad input wins and arithmetic overflow can
;   never mask a bad operand. The exponent-all-ones test
;
;     (payload & 0x7F800000) == 0x7F800000
;
;   accepts every finite binary32 word, including subnormals, both zeros, and
;   the maximum finite magnitude 0x7F7FFFFF. The base, shifted value, and
;   drift are each checked for the same non-finite class before use. There is
;   no store, no scratch memory, and no partial result: the check is a leaf
;   predicate with r1/r9 as its only result.
;
; NUMERIC POLICY:
;   The kernel performs exactly four FADD and three FSUB operations for a
;   successful pass/fail decision: one FADD plus one FSUB for the base, three
;   FADD plus one FSUB for the shifted value, one FSUB for the drift, and one
;   integer AND for the magnitude. There is no reassociation, no fused
;   operation, no host math, and no static constant pool. A large g can
;   legitimately produce drift because each addition rounds independently;
;   the declared tolerance decides whether that drift is acceptable.
;
; Clobbers r1, r5-r12 and flags. Preserves r0, r2-r4, r13-r15. Leaf routine:
; no CALL, no static scratch, no return slot.

mth_mirror_gauge_check_f32:
mth_mirror_gauge_check:
  MOVI r11,0
  MOVHI r11,0x7F80           ; r11 = 0x7F800000 exponent-all-ones mask

  ; ---- x_0i: load four little-endian payload bytes ----
  LDB r5,r1,0
  LDB r9,r1,1
  SHL r9,r9,8
  BOOL.14 r5,r5,r9
  LDB r9,r1,2
  SHL r9,r9,16
  BOOL.14 r5,r5,r9
  LDB r9,r1,3
  SHL r9,r9,24
  BOOL.14 r5,r5,r9

  BOOL.8 r9,r5,r11
  CMP r9,r11
  JMP[EQ] @mth_mirror_gauge_check_nonfinite_a

  ; ---- x_ij ----
  LDB r6,r2,0
  LDB r9,r2,1
  SHL r9,r9,8
  BOOL.14 r6,r6,r9
  LDB r9,r2,2
  SHL r9,r9,16
  BOOL.14 r6,r6,r9
  LDB r9,r2,3
  SHL r9,r9,24
  BOOL.14 r6,r6,r9

  BOOL.8 r9,r6,r11
  CMP r9,r11
  JMP[EQ] @mth_mirror_gauge_check_nonfinite_b

  ; ---- x_0j ----
  LDB r8,r3,0
  LDB r9,r3,1
  SHL r9,r9,8
  BOOL.14 r8,r8,r9
  LDB r9,r3,2
  SHL r9,r9,16
  BOOL.14 r8,r8,r9
  LDB r9,r3,3
  SHL r9,r9,24
  BOOL.14 r8,r8,r9

  BOOL.8 r9,r8,r11
  CMP r9,r11
  JMP[EQ] @mth_mirror_gauge_check_nonfinite_c

  ; ---- g ----
  LDB r10,r4,0
  LDB r9,r4,1
  SHL r9,r9,8
  BOOL.14 r10,r10,r9
  LDB r9,r4,2
  SHL r9,r9,16
  BOOL.14 r10,r10,r9
  LDB r9,r4,3
  SHL r9,r9,24
  BOOL.14 r10,r10,r9

  BOOL.8 r9,r10,r11
  CMP r9,r11
  JMP[EQ] @mth_mirror_gauge_check_nonfinite_g

  ; ---- base = (x_0i + x_ij) - x_0j, required order ----
  FADD r7,r5,r6
  FSUB r7,r7,r8

  BOOL.8 r9,r7,r11
  CMP r9,r11
  JMP[EQ] @mth_mirror_gauge_check_nonfinite_result

  ; ---- shifted = ((x_0i + g) + x_ij) - (x_0j + g) ----
  FADD r12,r5,r10           ; x_0i + g
  FADD r12,r12,r6           ; (x_0i + g) + x_ij
  FADD r1,r8,r10            ; x_0j + g
  FSUB r12,r12,r1           ; shifted

  BOOL.8 r9,r12,r11
  CMP r9,r11
  JMP[EQ] @mth_mirror_gauge_check_nonfinite_result

  ; ---- drift = shifted - base ----
  FSUB r12,r12,r7

  BOOL.8 r9,r12,r11
  CMP r9,r11
  JMP[EQ] @mth_mirror_gauge_check_nonfinite_result

  ; ---- |drift| <= 2^-16 by unsigned integer bit comparison ----
  MOVI r5,0xFFFF
  MOVHI r5,0x7FFF            ; r5 = 0x7FFFFFFF sign-bit mask
  BOOL.8 r12,r12,r5          ; magnitude word in [0, 0x7F7FFFFF]

  MOVI r6,0
  MOVHI r6,0x3780            ; r6 = 2^-16 = 0x37800000
  CMP r12,r6
  JMP[GT] @mth_mirror_gauge_check_drift

  MOVI r9,0                  ; pass has no failure cause
  MOVI r1,1
  RET

mth_mirror_gauge_check_nonfinite_a:
  MOVI r9,1
  JMP @mth_mirror_gauge_check_reject
mth_mirror_gauge_check_nonfinite_b:
  MOVI r9,2
  JMP @mth_mirror_gauge_check_reject
mth_mirror_gauge_check_nonfinite_c:
  MOVI r9,3
  JMP @mth_mirror_gauge_check_reject
mth_mirror_gauge_check_nonfinite_g:
  MOVI r9,4
  JMP @mth_mirror_gauge_check_reject
mth_mirror_gauge_check_nonfinite_result:
  MOVI r9,5
  JMP @mth_mirror_gauge_check_reject
mth_mirror_gauge_check_drift:
  MOVI r9,6
mth_mirror_gauge_check_reject:
  MOVI r1,0
  RET
