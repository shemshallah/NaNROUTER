; MTH gated cycle-bank retention / consolidation — NaN16 float32 only.
;
; Blends a live 16x16 triangle-circulation bank toward a retained snapshot
; bank without collapsing the mirror structure:
;
;   current_edge = current_edge + gain * (source_edge - current_edge)
;
; for every channel c=0..15, every d=0..15, all three triangle edges, and
; both physical lanes. gain=0 leaves the current bank unchanged; gain=1 copies
; the source bank; intermediate values retain a mixture.
;
; The two banks use the same leased geometry as the cycle trainer:
; 16 adjacent pairs (a,a+1), a = base+2d, plus (0,a) and (0,b). The bases must
; be in 1..224 and their 32-head spans must not overlap.
;
; ABI (r13=1):
;   r1 = current base head, 1..224
;   r2 = source  base head, 1..224
;   r3 = retention gain, finite f32 in [0,1]
; Success: r1=1, r9=0, current bank updated in place.
; Rejection: r1=0, r9=cause; current bank unchanged only for the base/gain
;   checks, which run before any write.
;   cause 1: current base invalid
;   cause 2: source base invalid
;   cause 3: source/current 32-head spans overlap
;   cause 4: gain non-finite or outside [0,1]
;
; The kernel assumes both banks contain finite f32 values; a non-finite edge
; propagates through the documented float operations. No clamping, truth
; collapse, host math, or allocation is used.
;
; Clobbers r1-r3, r5, r7, r9-r10; preserves r0, r4, r6, r8, r11-r15.

mth_mirror_cycle_retain_f32:
  MOVI r0,0
  ADD r6,r15,r0              ; save return link
  ADD r4,r1,r0               ; current base
  ADD r12,r2,r0              ; source base
  ADD r8,r3,r0               ; gain

  ; ---- base domains ----
  CMP r4,r0
  JMP[EQ] @mth_cycle_retain_bad_current
  MOVI r7,224
  CMP r7,r4
  JMP[LT] @mth_cycle_retain_bad_current
  CMP r12,r0
  JMP[EQ] @mth_cycle_retain_bad_source
  CMP r7,r12
  JMP[LT] @mth_cycle_retain_bad_source

  ; ---- disjoint 32-head spans ----
  SUB r7,r4,r12
  CMPS r7,r0
  JMP[GE] @mth_cycle_retain_abs_ready
  SUB r7,r0,r7
mth_cycle_retain_abs_ready:
  MOVI r9,32
  CMP r7,r9
  JMP[LT] @mth_cycle_retain_bad_overlap

  ; ---- gain finite and in [0,1] ----
  MOVI r7,0
  MOVHI r7,0x7F80
  BOOL.8 r9,r8,r7
  CMP r9,r7
  JMP[EQ] @mth_cycle_retain_bad_gain
  FCMP r8,r0
  JMP[LT] @mth_cycle_retain_bad_gain
  MOVI r7,0
  MOVHI r7,0x3F80
  FCMP r8,r7
  JMP[GT] @mth_cycle_retain_bad_gain

  MOVI r11,0                 ; d = 0
mth_cycle_retain_d_loop:
  ; (0,a)
  SHL r1,r11,1
  ADD r1,r1,r4               ; current a
  SHL r2,r11,1
  ADD r2,r2,r12              ; source a
  CALL @mth_cycle_retain_pair

  ; (a,a+1), ids = 1 + a*(511-a)/2
  SHL r1,r11,1
  ADD r1,r1,r4
  MOVI r3,511
  SUB r3,r3,r1
  MUL r3,r1,r3
  SHR r3,r3,1
  ADDI r1,r3,1
  SHL r2,r11,1
  ADD r2,r2,r12
  MOVI r3,511
  SUB r3,r3,r2
  MUL r3,r2,r3
  SHR r3,r3,1
  ADDI r2,r3,1
  CALL @mth_cycle_retain_pair

  ; (0,b), ids = a+1
  SHL r1,r11,1
  ADD r1,r1,r4
  ADDI r1,r1,1
  SHL r2,r11,1
  ADD r2,r2,r12
  ADDI r2,r2,1
  CALL @mth_cycle_retain_pair

  ADDI r11,r11,1
  MOVI r7,16
  CMP r11,r7
  JMP[LT] @mth_cycle_retain_d_loop

  MOVI r1,1
  MOVI r9,0
  ADD r15,r6,r0
  RET

; r1 = current pair id, r2 = source pair id, r8 = gain.
; Preserves r4, r6, r8, r11-r15.
mth_cycle_retain_pair:
  MOVI r5,0                  ; c = 0
mth_cycle_retain_c_loop:
  ; lane 0 words
  ADDI r7,r1,-1
  SHL r7,r7,6
  ADDI r7,r7,8192
  ADD r7,r7,r5
  ADDI r9,r2,-1
  SHL r9,r9,6
  ADDI r9,r9,8192
  ADD r9,r9,r5

  LD r10,r7,0                ; current
  LD r3,r9,0                 ; source
  FSUB r3,r3,r10             ; source-current
  FMUL r3,r3,r8              ; gain*(source-current)
  FADD r10,r10,r3
  ST r10,r7,0

  ; lane 1 words
  ADDI r7,r7,32
  ADDI r9,r9,32
  LD r10,r7,0
  LD r3,r9,0
  FSUB r3,r3,r10
  FMUL r3,r3,r8
  FADD r10,r10,r3
  ST r10,r7,0

  ADDI r5,r5,1
  MOVI r7,16
  CMP r5,r7
  JMP[LT] @mth_cycle_retain_c_loop
  RET

mth_cycle_retain_bad_current:
  MOVI r9,1
  JMP @mth_cycle_retain_reject
mth_cycle_retain_bad_source:
  MOVI r9,2
  JMP @mth_cycle_retain_reject
mth_cycle_retain_bad_overlap:
  MOVI r9,3
  JMP @mth_cycle_retain_reject
mth_cycle_retain_bad_gain:
  MOVI r9,4
mth_cycle_retain_reject:
  MOVI r1,0
  ADD r15,r6,r0
  RET
