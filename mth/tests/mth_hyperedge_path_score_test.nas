; MTH Round 027 two-edge hyperedge path-score fixture — NaN16 only.
;
; In-guest coverage, no host arithmetic:
;   1. anchor path scores at strengths -8, -1, 0, 1, 8 on both edges,
;      plus mixed-sign and zero/positive cross pairs;
;   2. the exact (0,0) result 0.25, checked as an integer word;
;   3. finite clamp saturation: +-100 and +-8.5 give the same score bits
;      as the corresponding +-8 endpoint;
;   4. monotonicity and product range on two nine-point sweeps:
;      s2 fixed at 0 with s1 in {-8,-4,-2,-1,0,1,2,4,8}, and s1 fixed at
;      -1 with s2 over the same set;
;   5. failure atomicity for NaN, +inf, and -inf in either strength:
;      r1=0, the documented r9 cause, r10=0, the destination word still
;      holds its sentinel, and both guard words are untouched;
;   6. strength1-before-strength2 rejection priority when both are bad;
;   7. every success returns r1=1, r9=0, r10 equal to the stored score.
;
; Tolerant checks use integer binary32 bit distance (ULP distance) for the
; positive finite score, with a 64-ULP window against the expected word.
; Exact checks use CMP on the raw integer payload. All expected words are
; compile-time fixture constants; the guest computes every actual score.
; The anchor words are f32 regression anchors for this bounded
; implementation (each is within the documented 2^-19 product bound of the
; real-valued sigmoid product); the 64-ULP window is a tighter regression
; check, not a re-derivation of the real-valued tolerance.
;
; The destination sits between two guard words, so a success may change only
; the one destination word and a rejection may change nothing.

.org 0
JMP @mth_path_test_main
.include "../nan16/mth_hyperedge_path_score.nas"

mth_path_test_main:
  MOVI r13,1

  ; ================= Case 1: anchor and cross-pair scores =================
  MOVI r4,0
  ST r4,r0,@mth_path_test_i
mth_path_test_anchor_loop:
  LD r6,r0,@mth_path_test_i
  MOVI r7,16
  CMP r6,r7
  JMP[GE] @mth_path_test_anchor_done

  ; Load strengths from case entry i: three words per entry.
  MOVI r8,@mth_path_anchor_cases
  ADD r9,r6,r6
  ADD r9,r9,r6
  ADD r8,r8,r9
  LD r1,r8,0
  LD r2,r8,1
  CALL @mth_path_test_call

  ; Reload the expected word after the kernel clobbered the scratch registers.
  LD r6,r0,@mth_path_test_i
  MOVI r8,@mth_path_anchor_cases
  ADD r9,r6,r6
  ADD r9,r9,r6
  ADD r8,r8,r9
  LD r1,r8,2
  CALL @mth_path_test_check_score
  CMP r1,r13
  JMP[NE] @mth_path_test_fail_1

  LD r6,r0,@mth_path_test_i
  ADDI r6,r6,1
  ST r6,r0,@mth_path_test_i
  JMP @mth_path_test_anchor_loop
mth_path_test_anchor_done:

  ; ================= Case 2: exact (0,0) score 0.25 =================
  MOVI r1,0
  MOVI r2,0
  CALL @mth_path_test_call
  MOVI r1,0
  MOVHI r1,0x3E80            ; 0.25 = 0x3E800000
  CALL @mth_path_test_check_exact
  CMP r1,r13
  JMP[NE] @mth_path_test_fail_1

  ; ================= Case 3: finite clamp saturation =================
  ; (+100, 0) must equal (8, 0) exactly.
  MOVI r1,0
  MOVHI r1,0x42C8            ; +100.0
  MOVI r2,0
  CALL @mth_path_test_call
  MOVI r1,0xEA06
  MOVHI r1,0x3EFF            ; score(8,0) = 0x3EFFEA06
  CALL @mth_path_test_check_exact
  CMP r1,r13
  JMP[NE] @mth_path_test_fail_1

  ; (-100, 0) must equal (-8, 0) exactly.
  MOVI r1,0
  MOVHI r1,0xC2C8            ; -100.0
  MOVI r2,0
  CALL @mth_path_test_call
  MOVI r1,0xD000
  MOVHI r1,0x392F            ; score(-8,0) = 0x392FD000
  CALL @mth_path_test_check_exact
  CMP r1,r13
  JMP[NE] @mth_path_test_fail_1

  ; (+100, +100) must equal (8, 8) exactly.
  MOVI r1,0
  MOVHI r1,0x42C8
  MOVI r2,0
  MOVHI r2,0x42C8
  CALL @mth_path_test_call
  MOVI r1,0xD40E
  MOVHI r1,0x3F7F            ; score(8,8) = 0x3F7FD40E
  CALL @mth_path_test_check_exact
  CMP r1,r13
  JMP[NE] @mth_path_test_fail_1

  ; (-100, -100) must equal (-8, -8) exactly.
  MOVI r1,0
  MOVHI r1,0xC2C8
  MOVI r2,0
  MOVHI r2,0xC2C8
  CALL @mth_path_test_call
  MOVI r1,0x7C12
  MOVHI r1,0x33F1            ; score(-8,-8) = 0x33F17C12
  CALL @mth_path_test_check_exact
  CMP r1,r13
  JMP[NE] @mth_path_test_fail_1

  ; (+8.5, -8.5) must equal (8, -8) exactly.
  MOVI r1,0
  MOVHI r1,0x4108            ; +8.5
  MOVI r2,0
  MOVHI r2,0xC108            ; -8.5
  CALL @mth_path_test_call
  MOVI r1,0xC0E8
  MOVHI r1,0x39AF            ; score(8,-8) = 0x39AFC0E8
  CALL @mth_path_test_check_exact
  CMP r1,r13
  JMP[NE] @mth_path_test_fail_1

  ; ================= Case 4: s1 sweep with s2 = 0 =================
  MOVI r4,0
  ST r4,r0,@mth_path_test_prev
  ST r4,r0,@mth_path_test_i
mth_path_test_mono1_loop:
  LD r6,r0,@mth_path_test_i
  MOVI r7,9
  CMP r6,r7
  JMP[GE] @mth_path_test_mono1_done
  MOVI r8,@mth_path_mono_values
  ADD r8,r8,r6
  LD r1,r8,0
  MOVI r2,0
  CALL @mth_path_test_call
  CALL @mth_path_test_check_range_mono
  CMP r1,r13
  JMP[NE] @mth_path_test_fail_2
  LD r6,r0,@mth_path_test_i
  ADDI r6,r6,1
  ST r6,r0,@mth_path_test_i
  JMP @mth_path_test_mono1_loop
mth_path_test_mono1_done:

  ; ================= Case 5: s2 sweep with s1 = -1 =================
  MOVI r4,0
  ST r4,r0,@mth_path_test_prev
  ST r4,r0,@mth_path_test_i
mth_path_test_mono2_loop:
  LD r6,r0,@mth_path_test_i
  MOVI r7,9
  CMP r6,r7
  JMP[GE] @mth_path_test_mono2_done
  MOVI r1,0
  MOVHI r1,0xBF80            ; s1 = -1.0
  MOVI r8,@mth_path_mono_values
  ADD r8,r8,r6
  LD r2,r8,0
  CALL @mth_path_test_call
  CALL @mth_path_test_check_range_mono
  CMP r1,r13
  JMP[NE] @mth_path_test_fail_2
  LD r6,r0,@mth_path_test_i
  ADDI r6,r6,1
  ST r6,r0,@mth_path_test_i
  JMP @mth_path_test_mono2_loop
mth_path_test_mono2_done:

  ; ================= Case 6: failure atomicity =================
  ; NaN in strength1.
  MOVI r1,0
  MOVHI r1,0x7FC0
  MOVI r2,0
  CALL @mth_path_test_call
  MOVI r1,1
  CALL @mth_path_test_check_failure
  CMP r1,r13
  JMP[NE] @mth_path_test_fail_3

  ; +inf in strength1.
  MOVI r1,0
  MOVHI r1,0x7F80
  MOVI r2,0
  CALL @mth_path_test_call
  MOVI r1,1
  CALL @mth_path_test_check_failure
  CMP r1,r13
  JMP[NE] @mth_path_test_fail_3

  ; -inf in strength1.
  MOVI r1,0
  MOVHI r1,0xFF80
  MOVI r2,0
  CALL @mth_path_test_call
  MOVI r1,1
  CALL @mth_path_test_check_failure
  CMP r1,r13
  JMP[NE] @mth_path_test_fail_3

  ; NaN in strength2.
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x7FC0
  CALL @mth_path_test_call
  MOVI r1,2
  CALL @mth_path_test_check_failure
  CMP r1,r13
  JMP[NE] @mth_path_test_fail_3

  ; +inf in strength2.
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x7F80
  CALL @mth_path_test_call
  MOVI r1,2
  CALL @mth_path_test_check_failure
  CMP r1,r13
  JMP[NE] @mth_path_test_fail_3

  ; -inf in strength2.
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0xFF80
  CALL @mth_path_test_call
  MOVI r1,2
  CALL @mth_path_test_check_failure
  CMP r1,r13
  JMP[NE] @mth_path_test_fail_3

  ; Both strengths bad: strength1 wins, cause 1.
  MOVI r1,0
  MOVHI r1,0x7FC0
  MOVI r2,0
  MOVHI r2,0x7FC0
  CALL @mth_path_test_call
  MOVI r1,1
  CALL @mth_path_test_check_failure
  CMP r1,r13
  JMP[NE] @mth_path_test_fail_3

  MOVI r1,@mth_path_test_pass
  CALL @mth_path_test_puts
  HALT

; ---- failure reporting ----
mth_path_test_fail_1:
  MOVI r6,1
  JMP @mth_path_test_fail
mth_path_test_fail_2:
  MOVI r6,2
  JMP @mth_path_test_fail
mth_path_test_fail_3:
  MOVI r6,3
mth_path_test_fail:
  MOVI r1,@mth_path_test_bad_prefix
  CALL @mth_path_test_puts
  MOVI r1,48
  ADD r1,r1,r6
  PUTC r1
  MOVI r1,@mth_path_test_nl
  CALL @mth_path_test_puts
  HALT

; ---- helpers ----
; r1 = strength1 bits, r2 = strength2 bits.
; Writes the sentinel to the destination word, calls the kernel with
; r3 = destination byte address, and saves r1/r9/r10 in memory.
mth_path_test_call:
  ADDI r5,r0,1               ; set k=0 so the ST below cannot be skipped
  ST r15,r0,@mth_path_test_link
  MOVI r3,@mth_path_out
  MOVI r4,0xBEEF
  MOVHI r4,0xDEAD            ; sentinel 0xDEADBEEF
  ST r4,r3,0
  SHL r3,r3,2                ; destination byte address
  CALL @mth_hyperedge_path_score
  ST r1,r0,@mth_path_test_ret1
  ST r9,r0,@mth_path_test_ret9
  ST r10,r0,@mth_path_test_ret10
  LD r15,r0,@mth_path_test_link
  RET

; r1 = expected score bits. Returns r1=1 iff:
;   success r1=1, r9=0, r10 equals the stored word, the stored word is
;   positive and within 64 ULP of the expected word, and both guards hold.
mth_path_test_check_score:
  ADD r6,r1,r0               ; expected bits
  LD r7,r0,@mth_path_test_ret1
  CMP r7,r13
  JMP[NE] @mth_path_test_score_bad
  LD r7,r0,@mth_path_test_ret9
  CMP r7,r0
  JMP[NE] @mth_path_test_score_bad
  LD r7,r0,@mth_path_test_ret10
  MOVI r8,@mth_path_out
  LD r8,r8,0
  CMP r7,r8
  JMP[NE] @mth_path_test_score_bad

  SHR r9,r8,31
  CMP r9,r0
  JMP[NE] @mth_path_test_score_bad

  ; |actual_bits - expected_bits| <= 64.
  CMP r8,r6
  JMP[GE] @mth_path_test_score_ordered
  ADD r9,r8,r0
  ADD r8,r6,r0
  ADD r6,r9,r0
mth_path_test_score_ordered:
  SUB r9,r8,r6
  MOVI r10,64
  CMP r10,r9
  JMP[LT] @mth_path_test_score_bad

  ST r15,r0,@mth_path_test_link2
  CALL @mth_path_test_check_guards
  LD r15,r0,@mth_path_test_link2
  CMP r1,r13
  JMP[NE] @mth_path_test_score_bad
  MOVI r1,1
  RET
mth_path_test_score_bad:
  MOVI r1,0
  RET

; r1 = expected score bits. Exact integer comparison, no ULP window.
mth_path_test_check_exact:
  ADD r6,r1,r0
  LD r7,r0,@mth_path_test_ret1
  CMP r7,r13
  JMP[NE] @mth_path_test_exact_bad
  LD r7,r0,@mth_path_test_ret9
  CMP r7,r0
  JMP[NE] @mth_path_test_exact_bad
  LD r7,r0,@mth_path_test_ret10
  MOVI r8,@mth_path_out
  LD r8,r8,0
  CMP r7,r8
  JMP[NE] @mth_path_test_exact_bad
  CMP r8,r6
  JMP[NE] @mth_path_test_exact_bad
  ST r15,r0,@mth_path_test_link2
  CALL @mth_path_test_check_guards
  LD r15,r0,@mth_path_test_link2
  CMP r1,r13
  JMP[NE] @mth_path_test_exact_bad
  MOVI r1,1
  RET
mth_path_test_exact_bad:
  MOVI r1,0
  RET

; Requires a successful call result. Checks 0 <= out <= 1, checks
; out >= previous, then stores out as the new previous.
mth_path_test_check_range_mono:
  LD r6,r0,@mth_path_test_ret1
  CMP r6,r13
  JMP[NE] @mth_path_test_range_bad
  LD r6,r0,@mth_path_test_ret9
  CMP r6,r0
  JMP[NE] @mth_path_test_range_bad
  MOVI r6,@mth_path_out
  LD r7,r6,0
  SHR r8,r7,31
  CMP r8,r0
  JMP[NE] @mth_path_test_range_bad
  MOVI r8,0
  MOVHI r8,0x3F80            ; 1.0
  CMP r8,r7
  JMP[LT] @mth_path_test_range_bad
  LD r8,r0,@mth_path_test_prev
  CMP r7,r8
  JMP[LT] @mth_path_test_range_bad
  ST r7,r0,@mth_path_test_prev
  MOVI r1,1
  RET
mth_path_test_range_bad:
  MOVI r1,0
  RET

; r1 = expected cause. Returns r1=1 iff r1=0, r9=cause, r10=0, the
; destination still holds the sentinel, and both guards are unchanged.
mth_path_test_check_failure:
  ADD r6,r1,r0
  LD r7,r0,@mth_path_test_ret1
  CMP r7,r0
  JMP[NE] @mth_path_test_failure_bad
  LD r7,r0,@mth_path_test_ret9
  CMP r7,r6
  JMP[NE] @mth_path_test_failure_bad
  LD r7,r0,@mth_path_test_ret10
  CMP r7,r0
  JMP[NE] @mth_path_test_failure_bad
  MOVI r7,@mth_path_out
  LD r7,r7,0
  MOVI r8,0xBEEF
  MOVHI r8,0xDEAD
  CMP r7,r8
  JMP[NE] @mth_path_test_failure_bad
  ST r15,r0,@mth_path_test_link2
  CALL @mth_path_test_check_guards
  LD r15,r0,@mth_path_test_link2
  CMP r1,r13
  JMP[NE] @mth_path_test_failure_bad
  MOVI r1,1
  RET
mth_path_test_failure_bad:
  MOVI r1,0
  RET

; Returns r1=1 iff guard_a is 0xAAAAAAAA and guard_b is 0x55555555.
mth_path_test_check_guards:
  MOVI r4,@mth_path_guard_a
  LD r4,r4,0
  MOVI r5,0xAAAA
  MOVHI r5,0xAAAA
  CMP r4,r5
  JMP[NE] @mth_path_test_guards_bad
  MOVI r4,@mth_path_guard_b
  LD r4,r4,0
  MOVI r5,0x5555
  MOVHI r5,0x5555
  CMP r4,r5
  JMP[NE] @mth_path_test_guards_bad
  MOVI r1,1
  RET
mth_path_test_guards_bad:
  MOVI r1,0
  RET

; r1 = NUL-terminated string; writes bytes through PUTC.
mth_path_test_puts:
  MOVI r4,255
mth_path_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_path_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_path_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_path_test_puts_word

; ---- data ----
.org 2048
mth_path_guard_a:
.word 0xAAAAAAAA
mth_path_out:
.word 0xDEADBEEF
mth_path_guard_b:
.word 0x55555555

mth_path_test_link:
.word 0
mth_path_test_link2:
.word 0
mth_path_test_ret1:
.word 0
mth_path_test_ret9:
.word 0
mth_path_test_ret10:
.word 0
mth_path_test_i:
.word 0
mth_path_test_prev:
.word 0

; Each entry: strength1 bits, strength2 bits, expected score bits.
; Diagonal anchors -8, -1, 0, 1, 8 and mixed-sign cross pairs.
mth_path_anchor_cases:
.word 0xC1000000, 0xC1000000, 0x33F17C12   ; (-8,-8)
.word 0xBF800000, 0xBF800000, 0x3D94217A   ; (-1,-1)
.word 0x00000000, 0x00000000, 0x3E800000   ; ( 0, 0)
.word 0x3F800000, 0x3F800000, 0x3F08D17F   ; ( 1, 1)
.word 0x41000000, 0x41000000, 0x3F7FD40E   ; ( 8, 8)
.word 0xC1000000, 0x41000000, 0x39AFC0E8   ; (-8, 8)
.word 0xBF800000, 0x3F800000, 0x3E4954A3   ; (-1, 1)
.word 0x41000000, 0xC1000000, 0x39AFC0E8   ; ( 8,-8)
.word 0x00000000, 0x41000000, 0x3EFFEA06   ; ( 0, 8)
.word 0x41000000, 0x00000000, 0x3EFFEA06   ; ( 8, 0)
.word 0xC1000000, 0x00000000, 0x392FD000   ; (-8, 0)
.word 0x00000000, 0xBF800000, 0x3E09B2B0   ; ( 0,-1)
.word 0xBF800000, 0x41000000, 0x3E89A6DE   ; (-1, 8)
.word 0x3F800000, 0xC1000000, 0x3980877C   ; ( 1,-8)
.word 0xC1000000, 0xBF800000, 0x38BD220F   ; (-8,-1)
.word 0x41000000, 0x3F800000, 0x3F3B1697   ; ( 8, 1)

; Monotonic sweep strengths: -8, -4, -2, -1, 0, 1, 2, 4, 8.
mth_path_mono_values:
.word 0xC1000000
.word 0xC0800000
.word 0xC0000000
.word 0xBF800000
.word 0x00000000
.word 0x3F800000
.word 0x40000000
.word 0x40800000
.word 0x41000000

mth_path_test_pass:
.str "MTH HYPEREDGE PATH SCORE PASS\n"
mth_path_test_bad_prefix:
.str "MTH HYPEREDGE PATH SCORE FAIL "
mth_path_test_nl:
.str "\n"
