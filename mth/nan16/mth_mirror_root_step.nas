; MTH Round 026 pair-lane mirror-root gradient step — NaN16 float32 only.
;
; Applies one 26-slot gradient step to the two residual lanes of a mirror-pair
; root:
;
;   delta_clamped[j] = clamp(delta[j], -0.05, +0.05)
;   lane0[j]         = lane0[j] - delta_clamped[j]
;   lane1[j]         = lane1[j] + delta_clamped[j]
;
; for j = 0..25 in increasing order. The two lanes move in opposite
; directions, so the gradient is mirrored across the pair root.
;
; ABI:
;   r1  = lane0 base, 26 float32 residual slots, updated in place
;   r2  = lane1 base, 26 float32 residual slots, updated in place
;   r3  = delta, 26 float32 gradient slots, read-only
;   r13 = 1
;   returns r1=1, r9=0 on success
;           r1=0, r9=1 if any delta word is non-finite (NaN, +inf, -inf)
;   clobbers r4-r12, r14; preserves r13 and r15
;
; DOMAIN AND ATOMICITY:
;   A complete preflight over all 26 delta words tests
;
;     (payload & 0x7F800000) == 0x7F800000
;
;   which is exactly the binary32 exponent-all-ones class (NaN and both
;   infinities). The first such word rejects the call before the first lane
;   store, so lane0 and lane1 are unchanged on rejection. The kernel does not
;   publish partial progress, and a caller must test r1 before consuming the
;   lanes. The two lane spans and delta must be caller-owned, distinct, and
;   non-overlapping; this leaf kernel does not validate pointers or aliasing.
;
; NUMERIC POLICY:
;   Clamping is an ordered float32 comparison against the exact binary32
;   constants +0.05 (0x3D4CCCCD) and -0.05 (0xBD4CCCCD). A clamped value is
;   an exact bit copy of the bound, never a re-rounded computation. The lane
;   update is one FSUB and one FADD per slot; no FMA, no reordering, and no
;   host math. Only integer address arithmetic and the finite-domain mask
;   test supplement the float instructions.

mth_mirror_root_step_f32:
mth_mirror_root_step:
  ; Preflight every delta word before touching either lane.
  MOVI r5,0
  MOVHI r5,0x7F80            ; r5 = 0x7F800000 exponent mask
  MOVI r4,0                  ; j = 0
  MOVI r12,26
mth_mirror_root_step_preflight:
  ADD r6,r3,r4
  LD r6,r6,0
  BOOL.8 r6,r6,r5            ; exponent bits only
  CMP r6,r5
  JMP[EQ] @mth_mirror_root_step_reject
  ADD r4,r4,r13
  CMP r4,r12
  JMP[LT] @mth_mirror_root_step_preflight

  ; Exact float32 clamp bounds.
  MOVI r10,0xCCCD
  MOVHI r10,0x3D4C           ; r10 = +0.05
  MOVI r11,0xCCCD
  MOVHI r11,0xBD4C           ; r11 = -0.05

  MOVI r4,0                  ; j = 0
mth_mirror_root_step_loop:
  ADD r6,r3,r4
  LD r6,r6,0                 ; delta[j]

  FCMP r6,r10
  JMP[GT] @mth_mirror_root_step_hi
  FCMP r6,r11
  JMP[LT] @mth_mirror_root_step_lo
  JMP @mth_mirror_root_step_apply
mth_mirror_root_step_hi:
  ADD r6,r10,r0              ; clamp to +0.05 by exact bit copy
  JMP @mth_mirror_root_step_apply
mth_mirror_root_step_lo:
  ADD r6,r11,r0              ; clamp to -0.05 by exact bit copy

mth_mirror_root_step_apply:
  ADD r7,r1,r4
  LD r8,r7,0
  FSUB r8,r8,r6              ; lane0[j] -= delta
  ST r8,r7,0
  ADD r7,r2,r4
  LD r8,r7,0
  FADD r8,r8,r6              ; lane1[j] += delta
  ST r8,r7,0

  ADD r4,r4,r13
  CMP r4,r12
  JMP[LT] @mth_mirror_root_step_loop

  MOVI r1,1
  MOVI r9,0
  RET

mth_mirror_root_step_reject:
  MOVI r1,0
  MOVI r9,1
  RET
