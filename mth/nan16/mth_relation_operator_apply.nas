; MTH bounded scalar relation-operator application — NaN16 float32 only.
;
; This is the native scalar seam for the host-side typed relation registry.
; It applies ONE already-resolved relation operator to two caller-supplied
; scalar activations and a confidence gain. It does not resolve, search,
; compose, chain, learn, or validate a relation claim. In particular this is
; not learned shared-matrix composition and it promotes no implicit truth.
;
; Operator table (code -> name -> finite score law)
; -------------------------------------------------
; The numeric order matches the eight declared Round 027 relation operators
; in runner_riddle/mirror_relation_ops.py:
;
;   code  name         base expression                   score
;   ----  -----------  --------------------------------  ----------------
;     1   is_a         min(L, R)                         C * base
;     2   part_of      max(L, R)                         C * base
;     3   causes       L - R                             C * base
;     4   supports     L + R                             C * base
;     5   refutes      R - L                             C * base
;     6   equivalent   min(L, R) - max(L, R)             C * base
;     7   transforms   L * R                             C * base
;     8   observes     max(L - R, R - L)                 C * base
;
; "base" is the parenthesized expression evaluated first; the final line is
; the only confidence application. Every expression uses only add, multiply,
; min/max, and difference (subtraction). No comparison result is treated as
; truth, no sign is treated as polarity, and no score is clamped or rounded
; to a probability. Codes 6 and 8 are symmetric in L and R; codes 3 and 5
; are the two directed differences, not truth values.
;
; Evaluation order is exact and observable:
;   code 1: base = min(L,R);             score = base * C
;   code 2: base = max(L,R);             score = base * C
;   code 3: base = L - R;                score = base * C
;   code 4: base = L + R;                score = base * C
;   code 5: base = R - L;                score = base * C
;   code 6: base = min(L,R) - max(L,R);  score = base * C
;   code 7: base = L * R;                score = base * C
;   code 8: base = max(L-R, R-L);        score = base * C
;
; Each subtraction and each multiplication is one IEEE-754 binary32
; instruction. Code 7 performs exactly two FMULs in the order (L * R) * C;
; it is not reassociated. Code 8 performs L - R and R - L before selecting
; the maximum. No FMA and no host arithmetic are used.
;
; ABI (r13 = 1)
; -------------
;   r1  = operator code (u32, exactly 1..8)
;   r2  = left scalar (raw IEEE-754 binary32 payload, passed by value)
;   r3  = right scalar (raw IEEE-754 binary32 payload, passed by value)
;   r4  = confidence (raw IEEE-754 binary32 payload, passed by value)
;   r5  = output byte address of one 4-byte little-endian f32 slot
;   r13 = 1
;
; Success:
;   r1 = 1, r9 = 0
;   bytes [r5, r5+4) = score as IEEE-754 binary32 little-endian
;   no other output byte is written.
;
; Rejection:
;   r1 = 0, r9 = cause, and the four output bytes are completely unchanged.
;   cause 1: operator code is 0, above 8, or otherwise not an exact code 1..8
;   cause 2: left is non-finite (NaN, +Inf, or -Inf)
;   cause 3: right is non-finite (NaN, +Inf, or -Inf)
;   cause 4: confidence is non-finite (NaN, +Inf, or -Inf)
;   cause 5: confidence is finite but outside the inclusive interval [0,1]
;   cause 6: the finite inputs produce a non-finite score (binary32 overflow
;            or an IEEE invalid result), so no finite score can be published
;
; Checks run in the order code, left, right, confidence finite, confidence
; range, compute, then result finite. The first active check wins. All checks
; and the complete computation occur before the first output store, so
; rejection is atomic. The caller owns the output span, its alignment, and
; any aliasing policy; this leaf does not validate pointers.
;
; Confidence policy (exact)
; -------------------------
; Confidence is a linear gain, not a probability and not a truth value.
; +0.0 and -0.0 are accepted because both compare equal to zero. +1.0 is
; accepted because the interval is inclusive. Any value below zero or above
; one rejects with cause 5; it is NEVER silently clamped or saturated.
; A +0.0 confidence therefore yields IEEE signed zero from the multiplication
; (for example +0.0 for a positive base and -0.0 for a negative base), not an
; implicit false verdict. A confidence of +1.0 publishes the unscaled base.
;
; Scale and non-claims
; --------------------
; The score is an arbitrary finite scalar with the sign and magnitude of the
; documented base expression times the caller's confidence gain. It is not a
; calibrated probability, not a truth degree, and not a learned shared-matrix
; composition. The caller remains responsible for calibration, composition,
; admission, lease, and any interpretation of the score.
;
; Register and instruction contract
; ---------------------------------
; Clobbers r1-r12, r14, and flags. Preserves r0, r13, r15. Leaf routine:
; no CALL, no static scratch, no self-modification, no loop, no allocation.
; Only native integer address arithmetic, STB byte stores, FADD, FSUB, FMUL,
; FCMP, and branches are used. The straight-line path is far below the
; fixture's 1,000,000-step execution bound.

mth_relation_operator_apply_f32:
mth_relation_operator_apply:
  MOVI r12,0                  ; local zero for register copies

  ; ---- operator code gate: exactly 1..8 (unsigned, wraps safely) ----
  ADDI r10,r1,-1              ; code-1; code 0 becomes 0xFFFFFFFF
  MOVI r11,7
  CMP r11,r10                 ; 7 < code-1 => unknown code
  JMP[LT] @mth_relation_op_apply_reject_1

  ; ---- finite-input preflight, in left/right/confidence order ----
  MOVI r14,0
  MOVHI r14,0x7F80            ; r14 = 0x7F800000 exponent-all-ones mask

  BOOL.8 r10,r2,r14           ; left exponent bits
  CMP r10,r14
  JMP[EQ] @mth_relation_op_apply_reject_2

  BOOL.8 r10,r3,r14           ; right exponent bits
  CMP r10,r14
  JMP[EQ] @mth_relation_op_apply_reject_3

  BOOL.8 r10,r4,r14           ; confidence exponent bits
  CMP r10,r14
  JMP[EQ] @mth_relation_op_apply_reject_4

  ; ---- confidence interval [0.0, 1.0], inclusive, no clamping ----
  MOVI r10,0                  ; +0.0
  FCMP r4,r10                 ; confidence < 0.0 ?
  JMP[LT] @mth_relation_op_apply_reject_5

  MOVI r10,0
  MOVHI r10,0x3F80            ; +1.0
  FCMP r10,r4                 ; 1.0 < confidence ?
  JMP[LT] @mth_relation_op_apply_reject_5

  ; ---- dispatch: the code is known to be 1..8 ----
  MOVI r10,1
  CMP r1,r10
  JMP[EQ] @mth_relation_op_apply_is_a
  MOVI r10,2
  CMP r1,r10
  JMP[EQ] @mth_relation_op_apply_part_of
  MOVI r10,3
  CMP r1,r10
  JMP[EQ] @mth_relation_op_apply_causes
  MOVI r10,4
  CMP r1,r10
  JMP[EQ] @mth_relation_op_apply_supports
  MOVI r10,5
  CMP r1,r10
  JMP[EQ] @mth_relation_op_apply_refutes
  MOVI r10,6
  CMP r1,r10
  JMP[EQ] @mth_relation_op_apply_equivalent
  MOVI r10,7
  CMP r1,r10
  JMP[EQ] @mth_relation_op_apply_transforms
  JMP @mth_relation_op_apply_observes

  ; ---- code 1: is_a = min(L,R) ----
mth_relation_op_apply_is_a:
  FCMP r2,r3
  JMP[GT] @mth_relation_op_apply_is_a_right
  ADD r6,r2,r12
  JMP @mth_relation_op_apply_finish
mth_relation_op_apply_is_a_right:
  ADD r6,r3,r12
  JMP @mth_relation_op_apply_finish

  ; ---- code 2: part_of = max(L,R) ----
mth_relation_op_apply_part_of:
  FCMP r2,r3
  JMP[LT] @mth_relation_op_apply_part_of_right
  ADD r6,r2,r12
  JMP @mth_relation_op_apply_finish
mth_relation_op_apply_part_of_right:
  ADD r6,r3,r12
  JMP @mth_relation_op_apply_finish

  ; ---- code 3: causes = L - R ----
mth_relation_op_apply_causes:
  FSUB r6,r2,r3
  JMP @mth_relation_op_apply_finish

  ; ---- code 4: supports = L + R ----
mth_relation_op_apply_supports:
  FADD r6,r2,r3
  JMP @mth_relation_op_apply_finish

  ; ---- code 5: refutes = R - L ----
mth_relation_op_apply_refutes:
  FSUB r6,r3,r2
  JMP @mth_relation_op_apply_finish

  ; ---- code 6: equivalent = min(L,R) - max(L,R) ----
mth_relation_op_apply_equivalent:
  FCMP r2,r3
  JMP[GT] @mth_relation_op_apply_equiv_min_right
  ADD r6,r2,r12               ; r6 = min
  JMP @mth_relation_op_apply_equiv_have_min
mth_relation_op_apply_equiv_min_right:
  ADD r6,r3,r12
mth_relation_op_apply_equiv_have_min:
  FCMP r2,r3
  JMP[LT] @mth_relation_op_apply_equiv_max_right
  ADD r7,r2,r12               ; r7 = max
  JMP @mth_relation_op_apply_equiv_have_max
mth_relation_op_apply_equiv_max_right:
  ADD r7,r3,r12
mth_relation_op_apply_equiv_have_max:
  FSUB r6,r6,r7
  JMP @mth_relation_op_apply_finish

  ; ---- code 7: transforms = L * R ----
mth_relation_op_apply_transforms:
  FMUL r6,r2,r3
  JMP @mth_relation_op_apply_finish

  ; ---- code 8: observes = max(L-R, R-L) ----
mth_relation_op_apply_observes:
  FSUB r6,r2,r3               ; L - R
  FSUB r7,r3,r2               ; R - L
  FCMP r6,r7
  JMP[LT] @mth_relation_op_apply_observes_right
  JMP @mth_relation_op_apply_finish
mth_relation_op_apply_observes_right:
  ADD r6,r7,r12
  JMP @mth_relation_op_apply_finish

  ; ---- confidence gain, finite-result gate, then the only stores ----
mth_relation_op_apply_finish:
  FMUL r6,r6,r4               ; score = base * confidence

  BOOL.8 r10,r6,r14
  CMP r10,r14
  JMP[EQ] @mth_relation_op_apply_reject_6

  STB r6,r5,0
  SHR r6,r6,8
  STB r6,r5,1
  SHR r6,r6,8
  STB r6,r5,2
  SHR r6,r6,8
  STB r6,r5,3

  MOVI r1,1
  MOVI r9,0
  RET

  ; ---- atomic rejection: no output byte has been written ----
mth_relation_op_apply_reject_1:
  MOVI r9,1
  JMP @mth_relation_op_apply_reject
mth_relation_op_apply_reject_2:
  MOVI r9,2
  JMP @mth_relation_op_apply_reject
mth_relation_op_apply_reject_3:
  MOVI r9,3
  JMP @mth_relation_op_apply_reject
mth_relation_op_apply_reject_4:
  MOVI r9,4
  JMP @mth_relation_op_apply_reject
mth_relation_op_apply_reject_5:
  MOVI r9,5
  JMP @mth_relation_op_apply_reject
mth_relation_op_apply_reject_6:
  MOVI r9,6
mth_relation_op_apply_reject:
  MOVI r1,0
  RET
