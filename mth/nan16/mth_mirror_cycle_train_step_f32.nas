; MTH content-dependent mirror-cycle training step — NaN16 float32 only.
;
; Native "write" half of the Round 038/039 dynamic-memory architecture:
;
;   prediction[c] = sum(d=0..15) x[d] * CycleFlux(d,c)
;   error[c]      = target[c] - prediction[c]
;   delta(d,c)    = lr * gate[c] * error[c] * x[d]
;   edge(0,a,c)  += delta(d,c)/3
;   edge(a,b,c)  += delta(d,c)/3
;   edge(0,b,c)  -= delta(d,c)/3
;
; with a = base + 2*d and b = a + 1. Each edge update is mirrored into both
; 128-byte lanes: lane 0 receives +v, lane 1 receives -v. Consequently the
; native circulation
;
;   F(d,c) = edge(0,a,c) + edge(a,b,c) - edge(0,b,c)
;
; changes by exactly delta(d,c) while the physical mirror invariant remains
; intact. This is a gated delta-rule write, not a hidden dense parameter
; update: the amount depends on the current input x, the current target, the
; content gate, and the prediction error.
;
; Bank geometry
; -------------
; The 16 x 16 coefficient bank uses 16 disjoint adjacent pairs
; (a,a+1) for d=0..15 and the reference-head edges (0,a), (0,b). The caller
; chooses a base head in 1..223; the bank therefore occupies heads
; base..base+31. The same physical 8 MiB pair universe is used; this is a
; reserved logical bank, not a second universe. A scheduler must lease it
; before concurrent relation writes.
;
; Pair word addressing (derived from the physical profile):
;   pair id (0,a) = a
;   pair id (a,b) = 1 + a*(511-a)/2
;   pair id (0,b) = b
;   word  = 8192 + (pair_id-1)*64 + channel
;   lane 0 channel c = c, lane 1 channel c = 32+c
;
; ABI (r13=1)
; -----------
;   r1 = x, 16 float32 payloads at word addresses (read-only)
;   r2 = target, 16 float32 payloads at word addresses (read-only)
;   r3 = gate, 16 float32 payloads at word addresses (read-only)
;   r4 = learning rate, one raw float32 payload
;   r5 = base head, unsigned 1..223
;   r6 = scratch, 17 float32 word addresses: error[0..15] and SSE at [16]
;   r13 = 1
;
; Success:
;   r1 = 1, r9 = 0, r7 = sum(error[c]^2) as a raw float32 payload.
;   The cycle bank, scratch, and mirror lanes are updated in place.
;
; Rejection (r1=0, r9=cause):
;   1  x is non-finite or |x[d]| > 1
;   2  target is non-finite or |target[c]| > 1
;   3  gate is non-finite or outside [0,1]
;   4  learning rate is non-finite or |lr| > 1
;   5  base head is outside 1..223
;   6  an edge in the bank is non-finite
;
; The input-domain checks run before the bank is touched. The first
; (prediction/error) pass writes error scratch and SSE but not the cycle bank;
; an edge rejection therefore leaves the bank unchanged. Once the second pass
; begins, all later operations are finite under the accepted domain, so the
; bank update completes.
;
; Numeric order:
;   prediction uses one FMUL then one FADD per d, increasing d.
;   error is one FSUB.
;   delta is (((lr * gate[c]) * error[c]) * x[d]), increasing d, one FMUL
;   each; third is delta * (1/3) as one final FMUL. No FMA, no reassociation,
;   no host math.
;
; Register effects: r0=0; r1-r14 clobbered; r15 preserved. The kernel has no
; CALL, no static storage, no allocation, and no self-modification.

mth_mirror_cycle_train_step_f32:
  MOVI r0,0
  ADD r14,r15,r0              ; save return link

  ; Save ABI pointers before using argument registers as temporaries.
  ADD r7,r1,r0                ; x base
  ADD r8,r2,r0                ; target base
  ADD r9,r3,r0                ; gate base
  ADD r10,r4,r0               ; learning rate
  ADD r11,r5,r0               ; base head (validated below)
  ADD r12,r6,r0               ; scratch

  ; ---- base head domain: 1..223 ----
  CMP r11,r0
  JMP[EQ] @mth_cycle_train_bad_base
  MOVI r1,223
  CMP r1,r11
  JMP[LT] @mth_cycle_train_bad_base

  ; ---- learning rate: finite and |lr| <= 1 ----
  MOVI r1,0
  MOVHI r1,0x7F80             ; exponent-all-ones mask
  BOOL.8 r2,r10,r1
  CMP r2,r1
  JMP[EQ] @mth_cycle_train_bad_lr
  MOVI r1,0xFFFF
  MOVHI r1,0x7FFF             ; clear-sign mask
  BOOL.8 r2,r10,r1
  MOVI r1,0
  MOVHI r1,0x3F80             ; 1.0
  FCMP r2,r1
  JMP[GT] @mth_cycle_train_bad_lr

  ; ---- x[t]: finite and |x[t]| <= 1 ----
  MOVI r4,0
mth_cycle_train_x_gate:
  ADD r1,r7,r4
  LD r1,r1,0
  MOVI r2,0
  MOVHI r2,0x7F80
  BOOL.8 r3,r1,r2
  CMP r3,r2
  JMP[EQ] @mth_cycle_train_bad_x
  MOVI r2,0xFFFF
  MOVHI r2,0x7FFF
  BOOL.8 r3,r1,r2
  MOVI r2,0
  MOVHI r2,0x3F80
  FCMP r3,r2
  JMP[GT] @mth_cycle_train_bad_x
  ADDI r4,r4,1
  MOVI r2,16
  CMP r4,r2
  JMP[LT] @mth_cycle_train_x_gate

  ; ---- target[t]: finite and |target[t]| <= 1 ----
  MOVI r4,0
mth_cycle_train_t_gate:
  ADD r1,r8,r4
  LD r1,r1,0
  MOVI r2,0
  MOVHI r2,0x7F80
  BOOL.8 r3,r1,r2
  CMP r3,r2
  JMP[EQ] @mth_cycle_train_bad_target
  MOVI r2,0xFFFF
  MOVHI r2,0x7FFF
  BOOL.8 r3,r1,r2
  MOVI r2,0
  MOVHI r2,0x3F80
  FCMP r3,r2
  JMP[GT] @mth_cycle_train_bad_target
  ADDI r4,r4,1
  MOVI r2,16
  CMP r4,r2
  JMP[LT] @mth_cycle_train_t_gate

  ; ---- gate[t]: finite and 0 <= gate[t] <= 1 ----
  MOVI r4,0
mth_cycle_train_g_gate:
  ADD r1,r9,r4
  LD r1,r1,0
  MOVI r2,0
  MOVHI r2,0x7F80
  BOOL.8 r3,r1,r2
  CMP r3,r2
  JMP[EQ] @mth_cycle_train_bad_gate
  FCMP r1,r0
  JMP[LT] @mth_cycle_train_bad_gate
  MOVI r2,0
  MOVHI r2,0x3F80
  FCMP r1,r2
  JMP[GT] @mth_cycle_train_bad_gate
  ADDI r4,r4,1
  MOVI r2,16
  CMP r4,r2
  JMP[LT] @mth_cycle_train_g_gate

  ; ---- SSE accumulator lives in scratch[16] ----
  MOVI r1,0
  ADDI r2,r12,16
  ST r1,r2,0

  ; ================= prediction and error pass =================
  MOVI r6,0                   ; c = 0
mth_cycle_train_c_loop:
  ; Keep target[c] in scratch[c] while the d loop uses r8 as a temporary.
  ADD r1,r8,r6
  LD r1,r1,0
  ADD r3,r12,r6
  ST r1,r3,0

  MOVI r4,0                   ; acc = +0.0
  MOVI r5,0                   ; d = 0
mth_cycle_train_d_loop:
  ; ---- x_0a ----
  SHL r1,r5,1
  ADD r1,r1,r11               ; a = base + 2*d
  ADDI r3,r1,-1
  SHL r3,r3,6
  ADDI r3,r3,8192
  ADD r3,r3,r6
  LD r3,r3,0                  ; x_0a

  ; finite edge check (cause 6)
  MOVI r2,0
  MOVHI r2,0x7F80
  BOOL.8 r1,r3,r2
  CMP r1,r2
  JMP[EQ] @mth_cycle_train_bad_edge
  ADD r1,r3,r0                ; save x_0a in r1 (r2 still mask)

  ; ---- x_ab ----
  SHL r3,r5,1
  ADD r3,r3,r11               ; a
  MOVI r2,511
  SUB r2,r2,r3
  MUL r2,r3,r2
  SHR r2,r2,1                 ; a*(511-a)/2
  SHL r2,r2,6
  ADDI r2,r2,8192
  ADD r2,r2,r6
  LD r3,r2,0                  ; x_ab
  FADD r1,r1,r3               ; x_0a + x_ab

  ; ---- x_0b ----
  SHL r3,r5,1
  ADD r3,r3,r11               ; a
  ADDI r3,r3,1                ; b
  ADDI r3,r3,-1               ; b-1 = a
  SHL r3,r3,6
  ADDI r3,r3,8192
  ADD r3,r3,r6
  LD r3,r3,0                  ; x_0b
  FSUB r1,r1,r3               ; flux = (x_0a + x_ab) - x_0b

  ; finite edge result (cause 6)
  MOVI r3,0
  MOVHI r3,0x7F80
  BOOL.8 r2,r1,r3
  CMP r2,r3
  JMP[EQ] @mth_cycle_train_bad_edge

  ; acc += x[d] * flux
  ADD r2,r7,r5
  LD r2,r2,0
  FMUL r1,r1,r2
  FADD r4,r4,r1

  ADDI r5,r5,1
  MOVI r2,16
  CMP r5,r2
  JMP[LT] @mth_cycle_train_d_loop

  ; error[c] = target[c] - acc; sse += error^2
  ADD r1,r12,r6
  LD r3,r1,0
  FSUB r3,r3,r4
  ST r3,r1,0
  FMUL r3,r3,r3
  ADDI r2,r12,16
  LD r1,r2,0
  FADD r1,r1,r3
  ST r1,r2,0

  ADDI r6,r6,1
  MOVI r2,16
  CMP r6,r2
  JMP[LT] @mth_cycle_train_c_loop

  ; ================= gated delta-rule write pass =================
  MOVI r6,0                   ; c = 0
mth_cycle_train_write_c:
  ; g = (lr * gate[c]) * error[c]
  ADD r1,r9,r6
  LD r1,r1,0
  FMUL r1,r1,r10              ; lr * gate
  ADD r2,r12,r6
  LD r2,r2,0                  ; error
  FMUL r3,r1,r2               ; g

  MOVI r5,0                   ; d = 0
mth_cycle_train_write_d:
  ; delta = g * x[d]; third = delta * (1/3)
  ADD r1,r7,r5
  LD r1,r1,0
  FMUL r2,r3,r1               ; delta
  MOVI r1,0xAAAB
  MOVHI r1,0x3EAA             ; 1/3 = 0x3EAAAAAB
  FMUL r1,r2,r1               ; third

  ; ---- pair (0,a): lane0 += third, lane1 -= third ----
  SHL r4,r5,1
  ADD r4,r4,r11               ; a
  ADDI r2,r4,-1
  SHL r2,r2,6
  ADDI r2,r2,8192
  ADD r2,r2,r6                ; lane0 word for (0,a,c)
  LD r8,r2,0
  FADD r8,r8,r1
  ST r8,r2,0
  ADDI r2,r2,32
  LD r8,r2,0
  FSUB r8,r8,r1
  ST r8,r2,0

  ; ---- pair (a,b): lane0 += third, lane1 -= third ----
  SHL r4,r5,1
  ADD r4,r4,r11               ; a
  MOVI r2,511
  SUB r2,r2,r4
  MUL r2,r4,r2
  SHR r2,r2,1                 ; a*(511-a)/2
  SHL r2,r2,6
  ADDI r2,r2,8192
  ADD r2,r2,r6
  LD r8,r2,0
  FADD r8,r8,r1
  ST r8,r2,0
  ADDI r2,r2,32
  LD r8,r2,0
  FSUB r8,r8,r1
  ST r8,r2,0

  ; ---- pair (0,b): lane0 -= third, lane1 += third ----
  SHL r4,r5,1
  ADD r4,r4,r11               ; a
  ADDI r4,r4,1                ; b
  ADDI r2,r4,-1               ; b-1 = a
  SHL r2,r2,6
  ADDI r2,r2,8192
  ADD r2,r2,r6
  LD r8,r2,0
  FSUB r8,r8,r1
  ST r8,r2,0
  ADDI r2,r2,32
  LD r8,r2,0
  FADD r8,r8,r1
  ST r8,r2,0

  ADDI r5,r5,1
  MOVI r2,16
  CMP r5,r2
  JMP[LT] @mth_cycle_train_write_d

  ADDI r6,r6,1
  MOVI r2,16
  CMP r6,r2
  JMP[LT] @mth_cycle_train_write_c

  ; ---- publish SSE ----
  ADDI r2,r12,16
  LD r7,r2,0
  MOVI r1,1
  MOVI r9,0
  ADD r15,r14,r0
  RET

mth_cycle_train_bad_x:
  MOVI r9,1
  JMP @mth_cycle_train_reject
mth_cycle_train_bad_target:
  MOVI r9,2
  JMP @mth_cycle_train_reject
mth_cycle_train_bad_gate:
  MOVI r9,3
  JMP @mth_cycle_train_reject
mth_cycle_train_bad_lr:
  MOVI r9,4
  JMP @mth_cycle_train_reject
mth_cycle_train_bad_base:
  MOVI r9,5
  JMP @mth_cycle_train_reject
mth_cycle_train_bad_edge:
  MOVI r9,6
mth_cycle_train_reject:
  MOVI r1,0
  MOVI r7,0
  ADD r15,r14,r0
  RET
