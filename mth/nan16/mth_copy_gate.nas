; MTH deterministic copy-vs-generate gate — NaN16 float32 only.
;
; Round 033 hybrid decision primitive. This is a fixed threshold/bias rule,
; not a trained gate and not evidence that copy/generate is learned.
;
; ABI:
;   r1  = retrieval score, one float32 payload (input; also return status)
;   r2  = threshold, one float32 payload
;   r3  = gate bias, one float32 payload
;   r13 = constant 1
;   r4  = mode output: 0 = generate, 1 = copy
;   r5  = confidence output, one float32 payload in [0,1]
;   r9  = 0 on success, or failure cause on rejection
;   returns r1 = 1 success, 0 rejection
;
; Exact decision law (IEEE-754 binary32, round-to-nearest-even):
;   s    = fl(score + bias)                 one FADD, left operand first
;   m    = fl(s - threshold)                one FSUB
;   a    = m with its sign bit cleared      exact |m|, no arithmetic
;   conf = 1.0 if a > 1.0 else a            clamp to [0,1]
;   mode = 1 (copy) iff s >= threshold, else 0 (generate)
;
; The comparison uses the rounded sum s, not an unbounded real sum. Equality,
; including -0.0 == +0.0, selects copy. The association is (score + bias) -
; threshold; it is not score + (bias - threshold). The confidence is the
; distance from the rounded boundary, capped at 1.0; it is not a probability
; and is not calibrated. Since a is nonnegative, the lower clamp is implied
; by the exact sign-bit clear.
;
; Validation, all before any output write:
;   score, threshold, and bias must be finite. A float32 word is finite iff
;   (bits & 0x7FFFFFFF) < 0x7F800000. This rejects every NaN payload and both
;   infinities exactly, without relying on FCMP unordered behavior. All three
;   finiteness checks run before the threshold domain check.
;   threshold must also satisfy 0 <= threshold <= 1. Both signed zeros are
;   accepted as the lower endpoint.
;
; Failure causes in r9, tested in this deterministic order:
;   1 = score is non-finite (NaN or +Inf or -Inf)
;   2 = threshold is non-finite
;   3 = bias is non-finite
;   4 = threshold is outside [0,1]
; A rejection returns r1 = 0 and leaves r4 and r5 untouched. r9 is written on
; every rejection. A success writes r1 = 1, r4, r5, and r9 = 0.
;
; Extreme finite inputs: finite operands never make FADD/FSUB produce NaN.
; They may overflow to +Inf or -Inf. Then m and a are the same infinity, the
; confidence clamps to 1.0, and the decision remains defined: +Inf copies and
; -Inf generates. Every accepted input therefore yields mode in {0,1} and a
; finite confidence in [0,1].
;
; Clobbers r1, r6, r7, r8, r9, r10, r11 and flags. Preserves r2, r3, r4, r5,
; r12, r13, r14, and r15 except for the documented output writes.
; Leaf routine: no CALL, no static scratch, no allocation, reentrant.
; Inputs and outputs are registers; there is no span, overlap, or wrap check.

mth_copy_gate:
  ; r6 = 0x7FFFFFFF magnitude mask, r8 = 0x7F800000 infinity boundary.
  MOVI r6,0xFFFF
  MOVHI r6,0x7FFF
  MOVI r8,0
  MOVHI r8,0x7F80

  ; Finite score.
  BOOL.8 r7,r1,r6
  CMP r7,r8
  JMP[GE] @mth_copy_gate_bad_score

  ; Finite threshold.
  BOOL.8 r7,r2,r6
  CMP r7,r8
  JMP[GE] @mth_copy_gate_bad_threshold

  ; Finite bias.
  BOOL.8 r7,r3,r6
  CMP r7,r8
  JMP[GE] @mth_copy_gate_bad_bias

  ; threshold >= 0. FCMP treats -0.0 == +0.0, so -0.0 is accepted here.
  FCMP r2,r0
  JMP[LT] @mth_copy_gate_bad_range
  ; threshold <= 1.0.
  MOVI r10,0
  MOVHI r10,0x3F80
  FCMP r2,r10
  JMP[GT] @mth_copy_gate_bad_range

  ; s = fl(score + bias). All validation is complete and no output is written.
  FADD r11,r1,r3

  ; mode = 1 iff s >= threshold. Equality and -0.0 == +0.0 select copy.
  MOVI r7,0
  FCMP r11,r2
  JMP[LT] @mth_copy_gate_mode_done
  MOVI r7,1
mth_copy_gate_mode_done:

  ; m = fl(s - threshold), a = exact |m| by clearing the sign bit.
  FSUB r10,r11,r2
  BOOL.8 r10,r10,r6

  ; conf = min(a, 1.0). a cannot be NaN for validated finite inputs.
  MOVI r8,0
  MOVHI r8,0x3F80
  FCMP r10,r8
  JMP[LE] @mth_copy_gate_confidence_done
  ADD r10,r8,r0
mth_copy_gate_confidence_done:

  MOVI r9,0
  MOVI r1,1
  ADD r4,r7,r0
  ADD r5,r10,r0
  RET

mth_copy_gate_bad_score:
  MOVI r9,1
  JMP @mth_copy_gate_reject
mth_copy_gate_bad_threshold:
  MOVI r9,2
  JMP @mth_copy_gate_reject
mth_copy_gate_bad_bias:
  MOVI r9,3
  JMP @mth_copy_gate_reject
mth_copy_gate_bad_range:
  MOVI r9,4
mth_copy_gate_reject:
  MOVI r1,0
  RET
