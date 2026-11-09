; MTH batch hyperedge-strength update — NaN16 only.
;
; This is an independent batch implementation. It does not include, link,
; call, or otherwise depend on the existing single-step kernel.
;
; Record layout (byte addresses)
; ------------------------------
; A record is exactly eight bytes with eight-byte stride:
;
;   record h, h = 1..r2:
;     +0  f32  strength   little-endian IEEE-754 binary32 payload
;     +4  u32  next       little-endian membership-chain link
;
; The kernel reads and writes only the strength field. The next field is
; never read, written, normalised, or reordered. A record occupies two
; consecutive NaN16 payload words (strength then next), so the arena is
; addressed with LDB/STB over the packed 32-bit payload byte space.
;
; ABI (r13 = 1)
; -------------
;   r1 = record-array base                 (byte address)
;   r2 = record count                      (u32, records are ids 1..r2)
;   r3 = u32 id array base                 (byte address)
;   r4 = f32 gradient array base           (byte address)
;   r5 = number of id/gradient entries     (u32)
;   r6 = eta                               (f32 payload, passed by value)
;   returns r1 = 1 on success
;           r1 = 0 on rejection
;   success also sets r9 = 0
;   rejection sets r9 to the cause code below and mutates nothing
;
; Entry k of the id and gradient arrays is at byte address r3 + 4*k and
; r4 + 4*k respectively. The caller owns all spans, alignment, and overlap.
; The kernel performs no allocation and no host operation.
;
; Update law
; ----------
; For each entry k in increasing k:
;
;   h = id[k]                              (validated in 1..r2)
;   old = strength of record h
;   g   = gradient[k]
;   x   = old - eta*g                      (one FMUL, then one FSUB)
;   new = clamp(x, -8.0, +8.0)
;   strength of record h = new
;
; Clamp is exactly:
;   x > +8.0  -> +8.0
;   x < -8.0  -> -8.0
;   otherwise -> x
; The bounds are inclusive. +Inf saturates to +8.0 and -Inf saturates to
; -8.0. Because old, eta, and g are all required finite, no finite input
; can produce a NaN candidate.
;
; Duplicate ids are legal. Entries are applied in array order, so a later
; duplicate observes the earlier clamped result. There is no deduplication,
; sorting, accumulation, or atomic multi-record transaction beyond the
; all-or-nothing preflight described below.
;
; Count and structural validation
; -------------------------------
; r5 = 0 is a valid empty batch. In that case no id, gradient, or record
; byte is read or written and the call succeeds after eta validation.
; Otherwise r2 and r5 are limited to 0x0FFFFFFF so that the record span
; 8*r2 and the id/gradient span 4*r5 fit in 32 bits. The exclusive span
; ends r1 + 8*r2, r3 + 4*r5, and r4 + 4*r5 must not wrap the 32-bit byte
; address space (end < base is rejected). These checks are cause 5.
;
; Eta semantics
; -------------
; r6 is the raw IEEE-754 binary32 payload of eta, passed by value, not an
; address. Every finite payload is accepted, including +0.0, -0.0,
; subnormals, and negative values. A negative eta updates in the
; +gradient direction. A NaN or infinity in eta rejects the whole call
; with cause 3 before any record is touched. Eta is validated even when
; r5 = 0.
;
; Validation, atomicity, and cause codes
; --------------------------------------
; A complete preflight runs before the first strength store. Checks and
; their priority are:
;
;   cause 5: r2 > 0x0FFFFFFF or r5 > 0x0FFFFFFF, or the record span,
;            id span, or gradient span would wrap the 32-bit byte
;            address space.
;   cause 3: eta is NaN, +Inf, or -Inf (exponent bits 0x7F80).
;   cause 1: some id[k] is 0 or greater than r2. The first bad entry in
;            increasing k determines the rejection.
;   cause 2: some gradient[k] is NaN, +Inf, or -Inf, tested by its
;            exponent-all-ones class. The first bad entry in increasing k
;            determines the rejection.
;   cause 4: a referenced record's stored strength is NaN, +Inf, or -Inf.
;            Such a record cannot yield a well-defined clamped result.
;            Records that are not referenced are not inspected.
;
; The checks run in the order listed, so if several defects are present
; the lowest-priority-numbered active check above wins (cause 5 first,
; then 3, 1, 2, 4). On any rejection, no strength, next, id, or gradient
; byte is written. r1 = 0 and r9 = cause. A caller must test r1 before
; consuming any record.
;
; On success r1 = 1, r9 = 0, and every referenced record strength is a
; finite value in [-8.0, +8.0]. The next fields and all non-referenced
; records are byte-for-byte unchanged.
;
; Register and instruction contract
; ---------------------------------
; Clobbers r1-r12, r14, and flags.
; Preserves r0, r13, r15. The routine is a leaf: no CALL, no static
; scratch, no self-modification. Only native integer, LDB/STB, FMUL/FSUB,
; FCMP, and branch instructions are used. No host arithmetic and no
; lookup table are used.

mth_hyperedge_strength_batch:
  ; ---- Structural count/span gate: exact arithmetic in 32 bits. ----
  MOVI r10,0xFFFF
  MOVHI r10,0x0FFF            ; r10 = 0x0FFFFFFF
  CMP r10,r2
  JMP[LT] @mth_hyperedge_strength_batch_reject_5
  CMP r10,r5
  JMP[LT] @mth_hyperedge_strength_batch_reject_5

  ; Record span: end = r1 + 8*r2. Reject wrap (end < base).
  SHL r10,r2,3
  ADD r11,r1,r10
  CMP r11,r1
  JMP[LT] @mth_hyperedge_strength_batch_reject_5

  ; Id span and gradient span: end = base + 4*r5. Reject wrap.
  SHL r10,r5,2
  ADD r11,r3,r10
  CMP r11,r3
  JMP[LT] @mth_hyperedge_strength_batch_reject_5
  ADD r11,r4,r10
  CMP r11,r4
  JMP[LT] @mth_hyperedge_strength_batch_reject_5

  ; ---- Eta must be finite before any record is examined. ----
  MOVI r14,0
  MOVHI r14,0x7F80            ; exponent-all-ones mask
  BOOL.8 r11,r6,r14
  CMP r11,r14
  JMP[EQ] @mth_hyperedge_strength_batch_reject_3

  ; ---- Preflight every id: 1 <= id <= r2. ----
  MOVI r7,0                    ; k = 0
mth_hyperedge_strength_batch_id_loop:
  CMP r7,r5
  JMP[GE] @mth_hyperedge_strength_batch_id_done
  SHL r10,r7,2
  ADD r10,r10,r3               ; id[k] byte address
  LDB r8,r10,0
  LDB r11,r10,1
  SHL r11,r11,8
  BOOL.14 r8,r8,r11
  LDB r11,r10,2
  SHL r11,r11,16
  BOOL.14 r8,r8,r11
  LDB r11,r10,3
  SHL r11,r11,24
  BOOL.14 r8,r8,r11            ; r8 = id[k]
  CMP r8,r13                   ; id < 1
  JMP[LT] @mth_hyperedge_strength_batch_reject_1
  CMP r2,r8                    ; r2 < id
  JMP[LT] @mth_hyperedge_strength_batch_reject_1
  ADD r7,r7,r13
  JMP @mth_hyperedge_strength_batch_id_loop
mth_hyperedge_strength_batch_id_done:

  ; ---- Preflight every gradient payload as finite. ----
  MOVI r7,0
mth_hyperedge_strength_batch_grad_loop:
  CMP r7,r5
  JMP[GE] @mth_hyperedge_strength_batch_grad_done
  SHL r10,r7,2
  ADD r10,r10,r4               ; gradient[k] byte address
  LDB r12,r10,0
  LDB r11,r10,1
  SHL r11,r11,8
  BOOL.14 r12,r12,r11
  LDB r11,r10,2
  SHL r11,r11,16
  BOOL.14 r12,r12,r11
  LDB r11,r10,3
  SHL r11,r11,24
  BOOL.14 r12,r12,r11          ; r12 = gradient[k] bits
  MOVI r14,0
  MOVHI r14,0x7F80
  BOOL.8 r11,r12,r14
  CMP r11,r14
  JMP[EQ] @mth_hyperedge_strength_batch_reject_2
  ADD r7,r7,r13
  JMP @mth_hyperedge_strength_batch_grad_loop
mth_hyperedge_strength_batch_grad_done:

  ; ---- Preflight every referenced stored strength as finite. ----
  MOVI r7,0
mth_hyperedge_strength_batch_old_loop:
  CMP r7,r5
  JMP[GE] @mth_hyperedge_strength_batch_old_done
  SHL r10,r7,2
  ADD r10,r10,r3
  LDB r8,r10,0
  LDB r11,r10,1
  SHL r11,r11,8
  BOOL.14 r8,r8,r11
  LDB r11,r10,2
  SHL r11,r11,16
  BOOL.14 r8,r8,r11
  LDB r11,r10,3
  SHL r11,r11,24
  BOOL.14 r8,r8,r11            ; r8 = validated id[k] again
  ADDI r10,r8,-1
  SHL r10,r10,3
  ADD r10,r10,r1               ; record h strength byte address
  LDB r11,r10,0
  LDB r12,r10,1
  SHL r12,r12,8
  BOOL.14 r11,r11,r12
  LDB r12,r10,2
  SHL r12,r12,16
  BOOL.14 r11,r11,r12
  LDB r12,r10,3
  SHL r12,r12,24
  BOOL.14 r11,r11,r12          ; r11 = old strength bits
  MOVI r14,0
  MOVHI r14,0x7F80
  BOOL.8 r12,r11,r14
  CMP r12,r14
  JMP[EQ] @mth_hyperedge_strength_batch_reject_4
  ADD r7,r7,r13
  JMP @mth_hyperedge_strength_batch_old_loop
mth_hyperedge_strength_batch_old_done:

  ; ---- Commit pass: every input is valid, so these stores cannot fail. ----
  MOVI r7,0
mth_hyperedge_strength_batch_update_loop:
  CMP r7,r5
  JMP[GE] @mth_hyperedge_strength_batch_success

  ; Load id[k] once more.
  SHL r10,r7,2
  ADD r10,r10,r3
  LDB r8,r10,0
  LDB r11,r10,1
  SHL r11,r11,8
  BOOL.14 r8,r8,r11
  LDB r11,r10,2
  SHL r11,r11,16
  BOOL.14 r8,r8,r11
  LDB r11,r10,3
  SHL r11,r11,24
  BOOL.14 r8,r8,r11

  ; Record h strength byte address = r1 + (h-1)*8.
  ADDI r10,r8,-1
  SHL r10,r10,3
  ADD r10,r10,r1

  ; Load old strength.
  LDB r11,r10,0
  LDB r12,r10,1
  SHL r12,r12,8
  BOOL.14 r11,r11,r12
  LDB r12,r10,2
  SHL r12,r12,16
  BOOL.14 r11,r11,r12
  LDB r12,r10,3
  SHL r12,r12,24
  BOOL.14 r11,r11,r12          ; r11 = old

  ; Load gradient[k] into r12.
  SHL r8,r7,2
  ADD r8,r8,r4
  LDB r12,r8,0
  LDB r14,r8,1
  SHL r14,r14,8
  BOOL.14 r12,r12,r14
  LDB r14,r8,2
  SHL r14,r14,16
  BOOL.14 r12,r12,r14
  LDB r14,r8,3
  SHL r14,r14,24
  BOOL.14 r12,r12,r14          ; r12 = gradient[k]

  ; x = old - eta*gradient. One FMUL then one FSUB, no FMA.
  FMUL r12,r6,r12
  FSUB r11,r11,r12             ; r11 = candidate

  ; Clamp to the inclusive interval [-8.0, +8.0].
  MOVI r14,0
  MOVHI r14,0x4100             ; +8.0
  FCMP r11,r14
  JMP[GT] @mth_hyperedge_strength_batch_clamp_high
  MOVI r14,0
  MOVHI r14,0xC100             ; -8.0
  FCMP r11,r14
  JMP[LT] @mth_hyperedge_strength_batch_clamp_low
  JMP @mth_hyperedge_strength_batch_store
mth_hyperedge_strength_batch_clamp_high:
  MOVI r11,0
  MOVHI r11,0x4100             ; +8.0
  JMP @mth_hyperedge_strength_batch_store
mth_hyperedge_strength_batch_clamp_low:
  MOVI r11,0
  MOVHI r11,0xC100             ; -8.0

mth_hyperedge_strength_batch_store:
  ; Store only strength bytes +0..+3. Bytes +4..+7 (next) are untouched.
  MOVI r14,255
  BOOL.8 r12,r11,r14
  STB r12,r10,0
  SHR r12,r11,8
  BOOL.8 r12,r12,r14
  STB r12,r10,1
  SHR r12,r11,16
  BOOL.8 r12,r12,r14
  STB r12,r10,2
  SHR r12,r11,24
  BOOL.8 r12,r12,r14
  STB r12,r10,3

  ADD r7,r7,r13
  JMP @mth_hyperedge_strength_batch_update_loop

mth_hyperedge_strength_batch_success:
  MOVI r9,0
  MOVI r1,1
  RET

mth_hyperedge_strength_batch_reject_5:
  MOVI r9,5
  JMP @mth_hyperedge_strength_batch_reject
mth_hyperedge_strength_batch_reject_3:
  MOVI r9,3
  JMP @mth_hyperedge_strength_batch_reject
mth_hyperedge_strength_batch_reject_1:
  MOVI r9,1
  JMP @mth_hyperedge_strength_batch_reject
mth_hyperedge_strength_batch_reject_2:
  MOVI r9,2
  JMP @mth_hyperedge_strength_batch_reject
mth_hyperedge_strength_batch_reject_4:
  MOVI r9,4
mth_hyperedge_strength_batch_reject:
  MOVI r1,0
  RET
