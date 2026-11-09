; MTH canonical mirror-memory head-record field I/O — NaN16 integer only.
;
; Canonical head record (byte addresses, little-endian payloads):
;
;   record h, h = 0..255:
;     +0    u32  first_hyperedge
;     +4    u32  state
;     +8    f32  score                 (raw IEEE-754 binary32 payload)
;     +12   u32  generation
;     +16   ..   reserved, 112 bytes
;
; Record h starts at
;
;   base + head * 128
;
; so record 0 starts at the caller's base and record 255 ends at
; base + 32,768. The canonical 8 MiB profile uses base = 0. A fixture or a
; host-side materialization may pass any non-overlapping 32 KiB head region;
; the kernel never validates or allocates the caller-owned span. The base
; must be four-byte aligned so each field is one payload word; the canonical
; base 0 satisfies this and alignment is a caller contract.
;
; Head 0 is the NANNET0/control head. Heads 1..255 are the real heads.
; This leaf performs storage I/O only: it does not interpret head role,
; hyperedge ids, state bits, generations, or the score as a number. The
; score field is read and written as its exact 32-bit binary32 payload; no
; finiteness, ranking, or other numeric policy is applied here. Score
; finiteness and generation monotonicity are schema invariants owned by
; callers, not by this byte transport.
;
; Field selectors
; ---------------
;   0 = first_hyperedge
;   1 = state
;   2 = score
;   3 = generation
;
; Selectors 4 and above are rejected for both get and set: 4..31 would
; address the reserved 112-byte tail, and 32 and above are outside the
; 128-byte record. In particular, a reserved write cannot be issued through
; this ABI. The reserved bytes themselves are never read or written by
; either routine; a set touches exactly the four payload bytes of the
; selected field.
;
; ABI (r13 = 1, r0 = 0 as usual)
; ------------------------------
; mth_mirror_head_record_get:
;   r1 = head-region base             (byte address)
;   r2 = head                         (u32, 0..255)
;   r3 = field                        (u32, 0..3)
;   success: r1 = 1, r2 = field payload, r9 = 0, r10 = field payload
;   rejection: r1 = 0, r2 = 0, r10 = 0, r9 = cause
;     cause 1: head > 255
;     cause 2: field > 3
;
; mth_mirror_head_record_set:
;   r1 = head-region base             (byte address)
;   r2 = head                         (u32, 0..255)
;   r3 = field                        (u32, 0..3)
;   r4 = new 32-bit payload
;   success: r1 = 1, r9 = 0
;   rejection: r1 = 0, r9 = cause
;     cause 1: head > 255
;     cause 2: field > 3
;
; Validation order is head first, then field, for both routines. Head and
; field comparisons are unsigned, so 256, 257, and 0xFFFFFFFF are rejected
; exactly like every other value above the documented limit. All checks
; complete before the first store; a rejected set mutates no byte.
;
; Named per-field wrappers:
;   mth_mirror_head_record_get_first_hyperedge: r1=base, r2=head
;       -> r1=1, r2=payload, r9=0, r10=payload,
;          or r1=0, r2=0, r10=0, r9=cause
;   ..._get_state / ..._get_score / ..._get_generation: same shape
;   mth_mirror_head_record_set_first_hyperedge: r1=base, r2=head, r3=value
;       -> r1=1, r9=0, or r1=0, r9=cause
;   ..._set_state / ..._set_score / ..._set_generation: same shape
;
; Register effects:
;   get clobbers r1-r10 and flags; preserves r0, r11-r15.
;   set clobbers r1-r9 and flags; preserves r0, r10-r15.
; Both routines are leaves: no CALL, no static scratch, no self-modification,
; and no host arithmetic.

.equ MTH_HEAD_FIELD_FIRST_HYPEREDGE 0
.equ MTH_HEAD_FIELD_STATE 1
.equ MTH_HEAD_FIELD_SCORE 2
.equ MTH_HEAD_FIELD_GENERATION 3
.equ MTH_HEAD_MAX 255
.equ MTH_HEAD_LAST_FIELD 3

mth_mirror_head_record_get:
  MOVI r10,0
  MOVI r9,0

  ; ---- unsigned head gate: 0..255 ----
  MOVI r5,#MTH_HEAD_MAX
  CMP r5,r2
  JMP[LT] @mth_mirror_head_record_get_bad_head

  ; ---- unsigned field gate: 0..3; reserved selectors are rejected ----
  MOVI r5,#MTH_HEAD_LAST_FIELD
  CMP r5,r3
  JMP[LT] @mth_mirror_head_record_get_bad_field

  ; ---- target byte address = base + head*128 + field*4 ----
  SHL r6,r2,7
  ADD r6,r1,r6
  SHL r7,r3,2
  ADD r6,r6,r7

  ; ---- assemble the little-endian payload from four field bytes ----
  LDB r10,r6,0
  LDB r7,r6,1
  SHL r7,r7,8
  BOOL.14 r10,r10,r7
  LDB r7,r6,2
  SHL r7,r7,16
  BOOL.14 r10,r10,r7
  LDB r7,r6,3
  SHL r7,r7,24
  BOOL.14 r10,r10,r7

  ADD r2,r10,r0
  MOVI r1,1
  MOVI r9,0
  RET

mth_mirror_head_record_get_bad_head:
  MOVI r1,0
  MOVI r2,0
  MOVI r9,1
  MOVI r10,0
  RET

mth_mirror_head_record_get_bad_field:
  MOVI r1,0
  MOVI r2,0
  MOVI r9,2
  MOVI r10,0
  RET

mth_mirror_head_record_set:
  ; ---- unsigned head gate ----
  MOVI r5,#MTH_HEAD_MAX
  CMP r5,r2
  JMP[LT] @mth_mirror_head_record_set_bad_head

  ; ---- unsigned field gate; rejects every reserved-tail selector ----
  MOVI r5,#MTH_HEAD_LAST_FIELD
  CMP r5,r3
  JMP[LT] @mth_mirror_head_record_set_bad_field

  ; ---- target byte address = base + head*128 + field*4 ----
  SHL r6,r2,7
  ADD r6,r1,r6
  SHL r7,r3,2
  ADD r6,r6,r7

  ; ---- store exactly four little-endian payload bytes ----
  STB r4,r6,0
  SHR r5,r4,8
  STB r5,r6,1
  SHR r5,r5,8
  STB r5,r6,2
  SHR r5,r5,8
  STB r5,r6,3

  MOVI r1,1
  MOVI r9,0
  RET

mth_mirror_head_record_set_bad_head:
  MOVI r1,0
  MOVI r9,1
  RET

mth_mirror_head_record_set_bad_field:
  MOVI r1,0
  MOVI r9,2
  RET

; ---------------------------------------------------------------------------
; Named per-field wrappers. Get leaves the payload in r10; set takes the
; payload in r3. The field index is fixed by the entry point.
; ---------------------------------------------------------------------------

mth_mirror_head_record_get_first_hyperedge:
  MOVI r3,#MTH_HEAD_FIELD_FIRST_HYPEREDGE
  JMP @mth_mirror_head_record_get

mth_mirror_head_record_get_state:
  MOVI r3,#MTH_HEAD_FIELD_STATE
  JMP @mth_mirror_head_record_get

mth_mirror_head_record_get_score:
  MOVI r3,#MTH_HEAD_FIELD_SCORE
  JMP @mth_mirror_head_record_get

mth_mirror_head_record_get_generation:
  MOVI r3,#MTH_HEAD_FIELD_GENERATION
  JMP @mth_mirror_head_record_get

mth_mirror_head_record_set_first_hyperedge:
  ADD r4,r3,r0
  MOVI r3,#MTH_HEAD_FIELD_FIRST_HYPEREDGE
  JMP @mth_mirror_head_record_set

mth_mirror_head_record_set_state:
  ADD r4,r3,r0
  MOVI r3,#MTH_HEAD_FIELD_STATE
  JMP @mth_mirror_head_record_set

mth_mirror_head_record_set_score:
  ADD r4,r3,r0
  MOVI r3,#MTH_HEAD_FIELD_SCORE
  JMP @mth_mirror_head_record_set

mth_mirror_head_record_set_generation:
  ADD r4,r3,r0
  MOVI r3,#MTH_HEAD_FIELD_GENERATION
  JMP @mth_mirror_head_record_set
