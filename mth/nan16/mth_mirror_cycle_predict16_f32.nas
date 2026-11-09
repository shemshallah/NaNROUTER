; MTH native 16x16 mirror-cycle forward readout — NaN16 float32 only.
;
; Computes the "CycleRead" half of the Round 039 state transition:
;
;   out[c] = sum(d=0..15) x[d] * CycleFlux(d,c)
;
; where each circulation is the native triangle expression
;
;   CycleFlux(d,c) = edge(0,a,c) + edge(a,b,c) - edge(0,b,c)
;   a = base + 2*d, b = a + 1
;
; The bank geometry is the same leased bank documented in
; mth_mirror_cycle_train_step_f32.nas. This kernel performs no writes to the
; bank; it reads the three lane-0 fields of each triangle, evaluates exactly
; one FADD and one FSUB per circulation, then one FMUL and one FADD per
; element of the dot product. No FMA, no reassociation, no host math.
;
; ABI (r13=1):
;   r1  = x, 16 float32 payloads at word addresses (read-only)
;   r2  = out, 16 float32 payloads at word addresses (written)
;   r3  = base head, unsigned 1..223
;   r13 = 1
; Success: r1=1, r9=0, out[0..15] complete.
; Rejection: r1=0, r9=1 if the base head is outside 1..223.
; The bank fields and pointers are caller-owned; this leaf does not validate
; extents or aliasing. The kernel clobbers r4-r11 and flags, preserves
; r0-r3, r12-r15.

mth_mirror_cycle_predict16_f32:
  MOVI r0,0

  ; ---- base head domain ----
  CMP r3,r0
  JMP[EQ] @mth_cycle_predict_bad_base
  MOVI r4,223
  CMP r4,r3
  JMP[LT] @mth_cycle_predict_bad_base

  MOVI r4,0                   ; c = 0
mth_cycle_predict_c:
  MOVI r6,0                   ; acc = +0.0
  MOVI r5,0                   ; d = 0
mth_cycle_predict_d:
  ; ---- x_0a ----
  SHL r7,r5,1
  ADD r7,r7,r3                ; a = base + 2*d
  ADDI r8,r7,-1
  SHL r8,r8,6
  ADDI r8,r8,8192
  ADD r8,r8,r4
  LD r8,r8,0                  ; x_0a

  ; ---- x_ab ----
  SHL r7,r5,1
  ADD r7,r7,r3
  MOVI r9,511
  SUB r9,r9,r7
  MUL r9,r7,r9
  SHR r9,r9,1                 ; a*(511-a)/2
  SHL r9,r9,6
  ADDI r9,r9,8192
  ADD r9,r9,r4
  LD r9,r9,0                  ; x_ab
  FADD r8,r8,r9               ; x_0a + x_ab

  ; ---- x_0b ----
  SHL r7,r5,1
  ADD r7,r7,r3
  ADDI r7,r7,1                ; b
  ADDI r7,r7,-1               ; b-1 = a
  SHL r7,r7,6
  ADDI r7,r7,8192
  ADD r7,r7,r4
  LD r7,r7,0                  ; x_0b
  FSUB r8,r8,r7               ; flux

  ; ---- acc += x[d] * flux ----
  ADD r9,r1,r5
  LD r9,r9,0
  FMUL r8,r8,r9
  FADD r6,r6,r8

  ADDI r5,r5,1
  MOVI r9,16
  CMP r5,r9
  JMP[LT] @mth_cycle_predict_d

  ADD r7,r2,r4
  ST r6,r7,0
  ADDI r4,r4,1
  MOVI r7,16
  CMP r4,r7
  JMP[LT] @mth_cycle_predict_c

  MOVI r1,1
  MOVI r9,0
  RET

mth_cycle_predict_bad_base:
  MOVI r1,0
  MOVI r9,1
  RET
