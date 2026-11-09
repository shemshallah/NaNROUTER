; MTH Round 033 gauge-invariant triangle read/write transport — NaN16 float32.
;
; Primitive name in the Round 033 integration ledger:
;   mth.gauge.triangle_recover
;
; The reference triangle (0,a,b) carries the root-0 circulation
;
;   F = x_0a + x_ab - x_0b
;
; evaluated with exactly the IEEE-754 binary32 operations below, in this
; order and with no reassociation or fusion:
;
;   FADD t, x_0a, x_ab
;   FSUB F, t,    x_0b
;
; A gauge shift of the reference head adds the same finite scalar g to x_0a
; and x_0b while leaving x_ab unchanged. For a dyadic g, or for any g whose
; two rounded sums move together, the transported F is the same binary32
; payload before and after the shift. The recover entry points compare the
; pre-gauge and post-gauge F payloads.
;
; This file is a self-contained leaf library. It performs no allocation, has
; no static scratch or return slot, and does not call the host. All operand
; and destination addresses are byte addresses of four-byte little-endian
; f32 fields. A field may be unaligned: every read and write is four explicit
; LDB/STB byte operations. The final store begins only after every input and
; the computed result have passed the finite gate, so a rejected transport
; leaves all four destination bytes untouched. If the destination aliases an
; input field, the transport is still safe because all three inputs are read
; before the first destination byte is written.
;
; ABI (r13 = 1, r0 = 0)
; --------------------
; mth_gauge_triangle_transport   (aliases: mth_gauge_triangle_read,
;                                           mth_gauge_triangle_read_write)
;   r1 = x_0a byte address (4-byte little-endian f32)
;   r2 = x_ab byte address
;   r3 = x_0b byte address
;   r4 = destination F byte address
;   success: r1 = 1, r9 = 0, r10 = the exact 32-bit F payload, and the four
;            destination bytes hold that little-endian payload
;   rejection: r1 = 0, r9 = cause, r10 = 0, and no destination byte changed
;     cause 1: x_0a is non-finite (NaN, +inf, or -inf)
;     cause 2: x_ab is non-finite
;     cause 3: x_0b is non-finite
;     cause 4: the computed F is non-finite (finite inputs overflowed)
;
; mth_gauge_triangle_recover
;   r1 = pre-gauge  F byte address
;   r2 = post-gauge F' byte address
;   pass    : r1 = 1, r9 = 0, r10 = the pre-gauge payload
;   mismatch: r1 = 0, r9 = 3, r10 = 0
;   rejection: r1 = 0, r9 = cause, r10 = 0
;     cause 1: pre-gauge F is non-finite
;     cause 2: post-gauge F' is non-finite
;     cause 3: both are finite but the exact 32-bit payloads differ
;
;   The comparison is exact payload identity: the declared window is 0 ULP
;   (MTH_GAUGE_TRIANGLE_ULP_WINDOW = 0). In particular +0.0 and -0.0 are
;   different payloads and therefore mismatch. There is no output field, so
;   a recover rejection or mismatch writes nothing.
;
; mth_gauge_triangle_recover_ulp
;   r1 = pre-gauge  F byte address
;   r2 = post-gauge F' byte address
;   r3 = inclusive ULP window (u32; 0 means exact ordered-value distance)
;   pass    : r1 = 1, r9 = 0, r10 = the pre-gauge payload
;   mismatch: r1 = 0, r9 = 3, r10 = 0 (finite distance is greater than r3)
;   rejection: r1 = 0, r9 = cause, r10 = 0
;     cause 1: pre-gauge F is non-finite
;     cause 2: post-gauge F' is non-finite
;
;   Distance is measured over the standard monotone integer mapping of the
;   finite binary32 range:
;
;     key(x) = ~bits(x)                      when the sign bit is set
;     key(x) =  bits(x) + 0x80000000         otherwise
;     distance = |key(pre) - key(post)|
;
;   Adjacent finite values differ by one, and the mapping is continuous
;   across zero. The two signed zeros are identified and report distance 0,
;   unlike the exact payload entry point. The window is inclusive: distance
;   equal to r3 passes. This entry point is the declared non-zero-window
;   tolerance path; the exact entry point remains the Round 033 0-ULP form.
;
; Validation order is always x_0a/pre, then x_ab/post, then x_0b/result.
; A complete input preflight is performed before arithmetic, so a bad input
; wins over an arithmetic overflow and a later bad input cannot mask an
; earlier one. The finite test is
;
;   (payload & 0x7F800000) == 0x7F800000
;
; which accepts every finite binary32 word, including subnormals, both
; zeros, and the maximum finite magnitude 0x7F7FFFFF.
;
; Register effects:
;   transport clobbers r1, r5-r12 and flags; preserves r0, r2-r4, r13-r15.
;   recover   clobbers r1, r5, r6, r9-r11 and flags; preserves r0, r2-r4,
;             r7, r8, r12-r15.
;   recover_ulp clobbers r1, r5-r12 and flags; preserves r0, r2-r4, r13-r15
;             (including the caller's window in r3).
;
; No host-language math, no static constant pool, no self-modification.

.equ MTH_GAUGE_TRIANGLE_ULP_WINDOW 0

; ---------------------------------------------------------------------------
; Read/compute/write transport.
; ---------------------------------------------------------------------------
mth_gauge_triangle_transport:
mth_gauge_triangle_read:
mth_gauge_triangle_read_write:
  MOVI r11,0
  MOVHI r11,0x7F80           ; r11 = 0x7F800000 exponent-all-ones mask

  ; ---- x_0a: load four little-endian payload bytes ----
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
  JMP[EQ] @mth_gauge_triangle_transport_nonfinite_a

  ; ---- x_ab ----
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
  JMP[EQ] @mth_gauge_triangle_transport_nonfinite_b

  ; ---- x_0b ----
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
  JMP[EQ] @mth_gauge_triangle_transport_nonfinite_c

  ; ---- F = (x_0a + x_ab) - x_0b, required order ----
  FADD r7,r5,r6
  FSUB r7,r7,r8

  BOOL.8 r9,r7,r11
  CMP r9,r11
  JMP[EQ] @mth_gauge_triangle_transport_nonfinite_result

  ; ---- commit exactly four little-endian payload bytes ----
  STB r7,r4,0
  SHR r9,r7,8
  STB r9,r4,1
  SHR r9,r9,8
  STB r9,r4,2
  SHR r9,r9,8
  STB r9,r4,3

  ADD r10,r7,r0             ; exact F payload
  MOVI r9,0
  MOVI r1,1
  RET

mth_gauge_triangle_transport_nonfinite_a:
  MOVI r9,1
  JMP @mth_gauge_triangle_transport_reject
mth_gauge_triangle_transport_nonfinite_b:
  MOVI r9,2
  JMP @mth_gauge_triangle_transport_reject
mth_gauge_triangle_transport_nonfinite_c:
  MOVI r9,3
  JMP @mth_gauge_triangle_transport_reject
mth_gauge_triangle_transport_nonfinite_result:
  MOVI r9,4
mth_gauge_triangle_transport_reject:
  MOVI r1,0
  MOVI r10,0
  RET

; ---------------------------------------------------------------------------
; Exact 0-ULP recover check: raw 32-bit payload identity.
; ---------------------------------------------------------------------------
mth_gauge_triangle_recover:
  MOVI r11,0
  MOVHI r11,0x7F80           ; r11 = 0x7F800000

  ; ---- pre-gauge F ----
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
  JMP[EQ] @mth_gauge_triangle_recover_nonfinite_pre

  ; ---- post-gauge F' ----
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
  JMP[EQ] @mth_gauge_triangle_recover_nonfinite_post

  ; ---- exact payload identity, window = 0 ULP ----
  CMP r5,r6
  JMP[NE] @mth_gauge_triangle_recover_mismatch

  ADD r10,r5,r0
  MOVI r9,0
  MOVI r1,1
  RET

mth_gauge_triangle_recover_mismatch:
  MOVI r9,3
  JMP @mth_gauge_triangle_recover_reject
mth_gauge_triangle_recover_nonfinite_pre:
  MOVI r9,1
  JMP @mth_gauge_triangle_recover_reject
mth_gauge_triangle_recover_nonfinite_post:
  MOVI r9,2
mth_gauge_triangle_recover_reject:
  MOVI r1,0
  MOVI r10,0
  RET

; ---------------------------------------------------------------------------
; Declared ULP-window recover check.
; ---------------------------------------------------------------------------
mth_gauge_triangle_recover_ulp:
  MOVI r11,0
  MOVHI r11,0x7F80           ; r11 = 0x7F800000

  ; ---- pre-gauge F ----
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
  JMP[EQ] @mth_gauge_triangle_recover_ulp_nonfinite_pre

  ; ---- post-gauge F' ----
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
  JMP[EQ] @mth_gauge_triangle_recover_ulp_nonfinite_post

  ; ---- identical payloads are distance zero ----
  CMP r5,r6
  JMP[EQ] @mth_gauge_triangle_recover_ulp_pass

  MOVI r12,0xFFFF
  MOVHI r12,0x7FFF           ; r12 = 0x7FFFFFFF sign-bit mask

  ; ---- the two signed zeros are the same finite value ----
  BOOL.8 r7,r5,r12
  BOOL.8 r8,r6,r12
  BOOL.14 r7,r7,r8
  CMP r7,r0
  JMP[EQ] @mth_gauge_triangle_recover_ulp_pass

  MOVI r11,0xFFFF
  MOVHI r11,0xFFFF           ; r11 = 0xFFFFFFFF all-ones mask

  ; ---- monotone key for pre-gauge F ----
  CMP r5,r12
  JMP[GT] @mth_gauge_triangle_recover_ulp_key_pre_neg
  MOVI r7,0
  MOVHI r7,0x8000
  ADD r7,r7,r5               ; positive: bits + 0x80000000
  JMP @mth_gauge_triangle_recover_ulp_key_pre_done
mth_gauge_triangle_recover_ulp_key_pre_neg:
  BOOL.6 r7,r5,r11           ; negative: bitwise NOT
mth_gauge_triangle_recover_ulp_key_pre_done:

  ; ---- monotone key for post-gauge F' ----
  CMP r6,r12
  JMP[GT] @mth_gauge_triangle_recover_ulp_key_post_neg
  MOVI r8,0
  MOVHI r8,0x8000
  ADD r8,r8,r6
  JMP @mth_gauge_triangle_recover_ulp_key_post_done
mth_gauge_triangle_recover_ulp_key_post_neg:
  BOOL.6 r8,r6,r11
mth_gauge_triangle_recover_ulp_key_post_done:

  ; ---- unsigned absolute distance between the keys ----
  CMP r7,r8
  JMP[LT] @mth_gauge_triangle_recover_ulp_dist_reverse
  SUB r9,r7,r8
  JMP @mth_gauge_triangle_recover_ulp_dist_done
mth_gauge_triangle_recover_ulp_dist_reverse:
  SUB r9,r8,r7
mth_gauge_triangle_recover_ulp_dist_done:

  CMP r9,r3
  JMP[GT] @mth_gauge_triangle_recover_ulp_mismatch

mth_gauge_triangle_recover_ulp_pass:
  ADD r10,r5,r0
  MOVI r9,0
  MOVI r1,1
  RET

mth_gauge_triangle_recover_ulp_mismatch:
  MOVI r9,3
  JMP @mth_gauge_triangle_recover_ulp_reject
mth_gauge_triangle_recover_ulp_nonfinite_pre:
  MOVI r9,1
  JMP @mth_gauge_triangle_recover_ulp_reject
mth_gauge_triangle_recover_ulp_nonfinite_post:
  MOVI r9,2
mth_gauge_triangle_recover_ulp_reject:
  MOVI r1,0
  MOVI r10,0
  RET
