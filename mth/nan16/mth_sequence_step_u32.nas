; MTH bounded sequence transition step (U32) — native NaN16 integer only.
;
; This is one deterministic finite-state transducer step for a token/sequence
; stream. It is a native primitive, not the full sequence controller: it does
; not gather embeddings, apply positions, slice windows, apply masks, build
; n-grams, concatenate heads, allocate memory, or read host state.
;
; State model
; -----------
;   q   = input state word, valid range 0..15 (4-bit context/phase register)
;   t   = token word, any 32-bit value
;   n   = step index, valid range 0..1,048,575 (SEQUENCE_MAX_WINDOW-1)
;
;   f = x ^ (x >> 16)
;   f = f ^ (f >> 8)
;   f = f ^ (f >> 4)
;   fold4(x) = f & 0xF        ; XOR of all eight 4-bit nibbles of x
;
;   e = fold4(t)              ; token event: every token nibble contributes
;   p = fold4(n)              ; step phase: every step nibble contributes
;   h = (t >> 4) & 0xF        ; second token nibble (positional term)
;
; Transition law (all arithmetic modulo 2^32 except the explicit mask):
;   q' = (5*q + 3*e + h + p + 1) & 0xF
;   m  = t ^ (q' << 8) ^ (q << 4) ^ p
;
; The emitted token m is a 32-bit token word. Its bits 12..31 are copied from
; the input token; its low 12 bits are XOR-tagged with q, q', and p. The next
; state remains bounded to 0..15. The law is deterministic: the same (q,t,n)
; always yields the same (q',m), independent of prior output memory or call
; history.
;
; Bounds and failure
; ------------------
; Reject when q >= 16 or n >= 1,048,576 (0x00100000). On rejection the routine
; commits no transition and writes the canonical closed marker 0xFFFFFFFF to
; both output words. Any 32-bit token word is accepted. The state bound is
; checked before the step bound; both checks happen before any output write.
;
; ABI (r13 = 1):
;   r1 = input state word             (u32, 0..15)
;   r2 = token word                   (u32, any value)
;   r3 = step index                   (u32, 0..1048575)
;   r4 = output next-state address    (1 word)
;   r5 = output emitted-token address (1 word)
;   returns r1 = 1 on success, r1 = 0 on rejection
;
; Success:
;   [r4] = q' (0..15)
;   [r5] = m
;
; Rejection:
;   [r4] = [r5] = 0xFFFFFFFF
;
; The two output addresses must be distinct. Clobbers r6-r10 and flags.
; Preserves r2-r5 and r11-r15. Leaf routine: no CALL, no static scratch.

mth_sequence_step_u32:
  ; Validate the state word before touching either output.
  MOVI r6,16
  CMP r1,r6
  JMP[GE] @mth_sequence_step_u32_reject

  ; Validate the bounded step index (0..0x000FFFFF inclusive).
  MOVI r6,0
  MOVHI r6,0x0010           ; r6 = 0x00100000 = 1,048,576
  CMP r3,r6
  JMP[GE] @mth_sequence_step_u32_reject

  ; e = fold4(token): XOR every token nibble into the event nibble.
  ADD r6,r2,r0
  SHR r7,r6,16
  BOOL.6 r6,r6,r7
  SHR r7,r6,8
  BOOL.6 r6,r6,r7
  SHR r7,r6,4
  BOOL.6 r6,r6,r7
  MOVI r7,0x000F
  BOOL.8 r6,r6,r7

  ; p = fold4(step): XOR every step nibble into the phase nibble.
  ADD r7,r3,r0
  SHR r8,r7,16
  BOOL.6 r7,r7,r8
  SHR r8,r7,8
  BOOL.6 r7,r7,r8
  SHR r8,r7,4
  BOOL.6 r7,r7,r8
  MOVI r8,0x000F
  BOOL.8 r7,r7,r8

  ; h = (token >> 4) & 0xF.
  SHR r8,r2,4
  MOVI r9,0x000F
  BOOL.8 r8,r8,r9

  ; q' = (5*q + 3*e + h + p + 1) & 0xF.
  SHL r9,r1,2
  ADD r9,r9,r1              ; 5*q
  SHL r10,r6,1
  ADD r10,r10,r6            ; 3*e
  ADD r9,r9,r10
  ADD r9,r9,r8              ; + h
  ADD r9,r9,r7              ; + p
  ADD r9,r9,r13             ; + 1
  MOVI r10,0x000F
  BOOL.8 r9,r9,r10

  ; m = t ^ (q' << 8) ^ (q << 4) ^ p.
  SHL r10,r9,8
  SHL r6,r1,4
  BOOL.6 r10,r10,r6
  BOOL.6 r10,r10,r7
  BOOL.6 r10,r10,r2

  ST r9,r4,0
  ST r10,r5,0
  MOVI r1,1
  RET

mth_sequence_step_u32_reject:
  ; Canonical closed marker: no next state and no emitted token are committed.
  MOVI r6,0xFFFF
  MOVHI r6,0xFFFF
  ST r6,r4,0
  ST r6,r5,0
  MOVI r1,0
  RET
