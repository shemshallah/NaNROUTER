; MTH contradiction-preserving evidence pair — NaN16 float32 only.
;
; A relation may carry supporting and opposing evidence at the same time. This
; primitive does not collapse the pair to a single truth value and does not
; force the losing side to zero. It preserves both magnitudes and publishes:
;
;   conflict = min(support, oppose)
;   balance  = support - oppose
;
; conflict is high when both sides are present; balance is the signed
; difference. Neither is a probability or a truth verdict.
;
; ABI (r13=1):
;   r1 = support, finite nonnegative f32 payload
;   r2 = oppose,  finite nonnegative f32 payload
; Success:
;   r1 = 1, r9 = 0
;   r2 = conflict = min(support, oppose)
;   r3 = balance  = support - oppose
;   r4 = support  (exact payload copy)
;   r5 = oppose   (exact payload copy)
; Rejection:
;   r1 = 0, r9 = cause; r2-r5 unspecified
;   cause 1: support is non-finite
;   cause 2: oppose is non-finite
;   cause 3: support is negative
;   cause 4: oppose is negative
;
; Negative zero is accepted because it compares equal to zero. No clamping,
; normalization, truth collapse, memory access, CALL, or host math is used.
; Clobbers r1-r10 and flags; preserves r0, r11-r15.

mth_mirror_cycle_contradiction_f32:
  MOVI r0,0
  ADD r6,r1,r0               ; support
  ADD r7,r2,r0               ; oppose

  ; ---- finite preflight, support then oppose ----
  MOVI r4,0
  MOVHI r4,0x7F80
  BOOL.8 r5,r6,r4
  CMP r5,r4
  JMP[EQ] @mth_cycle_contradiction_bad_support
  BOOL.8 r5,r7,r4
  CMP r5,r4
  JMP[EQ] @mth_cycle_contradiction_bad_oppose

  ; ---- nonnegative domain ----
  FCMP r6,r0
  JMP[LT] @mth_cycle_contradiction_negative_support
  FCMP r7,r0
  JMP[LT] @mth_cycle_contradiction_negative_oppose

  ; ---- conflict = min(support, oppose), exact payload copy ----
  FCMP r6,r7
  JMP[GT] @mth_cycle_contradiction_oppose_min
  ADD r2,r6,r0
  JMP @mth_cycle_contradiction_balance
mth_cycle_contradiction_oppose_min:
  ADD r2,r7,r0

mth_cycle_contradiction_balance:
  FSUB r3,r6,r7              ; balance = support - oppose

  ; Preserve both sides in the output registers.
  ADD r4,r6,r0
  ADD r5,r7,r0
  MOVI r1,1
  MOVI r9,0
  RET

mth_cycle_contradiction_bad_support:
  MOVI r9,1
  JMP @mth_cycle_contradiction_reject
mth_cycle_contradiction_bad_oppose:
  MOVI r9,2
  JMP @mth_cycle_contradiction_reject
mth_cycle_contradiction_negative_support:
  MOVI r9,3
  JMP @mth_cycle_contradiction_reject
mth_cycle_contradiction_negative_oppose:
  MOVI r9,4
mth_cycle_contradiction_reject:
  MOVI r1,0
  RET
