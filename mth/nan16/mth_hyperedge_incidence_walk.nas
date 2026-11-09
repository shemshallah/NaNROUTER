; MTH native bounded hyperedge-incidence chain walk — NaN16 integer only.
;
; This is a local read primitive over a small fixed-capacity arena. It walks
; the caller-selected prefix of one singly linked membership chain and copies
; the hyperedge ids into the caller's output array. It does not allocate, grow
; the arena, infer relationships, or execute host code.
;
; Arena layout (payload byte addresses)
; -------------------------------------
; The arena has MTH_HEW_ARENA_RECORDS = 5 slots of exactly eight bytes:
;
;   record i, i = 0..4:
;     +0  u32  next          little-endian record index
;     +4  u32  hyperedge_id  little-endian id payload
;
; A NaN16 LD/ST address selects one 32-bit payload word. LDB/STB address the
; four payload bytes of a word little-endian, so an eight-byte record spans
; two consecutive payload words and the arena is addressed in payload byte
; space. The caller passes an arena word address shifted left by two, exactly
; as the other packed-arena MTH kernels do.
;
; ABI (r0 = 0, r13 = 1)
; ---------------------
;   r1 = arena base                  (payload byte address)
;   r2 = head index                  (u32, 0..4)
;   r3 = max_steps                   (u32, 0..5)
;   r4 = output u32 id array base    (payload byte address)
;
;   success: r1 = 1, r5 = count = max_steps, r9 = 0
;   rejection: r1 = 0, r5 = 0, r9 = cause, output untouched
;
; Walk law
; --------
; The kernel collects exactly max_steps records beginning at the head index.
; max_steps = 0 returns an empty chain with count 0 and no output write. The
; next field of a collected record is read only when another step is needed,
; so a link after the max_steps-th record is not examined. Because the walk
; is bounded and repeats are rejected, the largest possible valid walk has
; five records and max_steps greater than five is an invalid bound.
;
; Link value 0 is a valid record index. The null sentinel is 0xFFFFFFFF; any
; link value greater than or equal to five is out of range. A null or
; out-of-range link that the walk would need to follow rejects the whole call.
; A link to a record index already collected is a cycle/repeat and rejects
; the whole call.
;
; Validation and atomicity
; ------------------------
; All structural checks and a complete preflight walk run before the first
; output store. Checks and cause codes, in priority order:
;
;   cause 1: head index >= 5
;   cause 2: max_steps > 5
;   cause 3: arena span r1 + 8*5 wraps the 32-bit byte address space
;   cause 4: output span r4 + 4*max_steps wraps the 32-bit byte address space
;   cause 5: a required link is null (0xFFFFFFFF) or >= 5
;   cause 6: a required link revisits a record already collected
;
; A rejection writes no output word and leaves every arena byte unchanged.
; On success only output entries [0, count) are written; entries at and past
; count are untouched. The caller owns output capacity, alignment, and
; non-overlap; the kernel only enforces the 32-bit span checks above.
;
; Register contract
; -----------------
; Clobbers r1, r5-r12, r14, and flags.
; Preserves r0, r2, r3, r4, r13, r15.
; Leaf routine: no CALL, no static scratch, no self-modification.

mth_hyperedge_incidence_walk:
  ; ---- structural bounds before any arena or output access ----
  MOVI r10,5
  CMP r2,r10
  JMP[GE] @mth_hew_reject_1    ; head >= 5
  CMP r3,r10
  JMP[GT] @mth_hew_reject_2    ; max_steps > 5

  MOVI r10,40
  ADD r11,r1,r10               ; arena end = base + 8*5
  CMP r11,r1
  JMP[LT] @mth_hew_reject_3    ; arena span wraps

  SHL r10,r3,2
  ADD r11,r4,r10               ; output end = base + 4*max_steps
  CMP r11,r4
  JMP[LT] @mth_hew_reject_4    ; output span wraps

  ; ---- preflight walk: validate every required link and reject repeats ----
  MOVI r5,0                    ; count
  ADD r6,r2,r0                 ; current record index
  MOVI r12,0                   ; visited bitmask (bit i = record i)
mth_hew_preflight_loop:
  CMP r5,r3
  JMP[GE] @mth_hew_preflight_done

  ; mask = 1 << current (current is always in 0..4)
  MOVI r10,1
  ADD r11,r6,r0
  CMP r11,r0
  JMP[EQ] @mth_hew_mask_ready
mth_hew_mask_loop:
  SHL r10,r10,1
  SUB r11,r11,r13
  JMP[GT] @mth_hew_mask_loop
mth_hew_mask_ready:
  BOOL.8 r14,r12,r10           ; already visited?
  CMP r14,r0
  JMP[NE] @mth_hew_reject_6
  BOOL.14 r12,r12,r10

  ADD r5,r5,r13
  CMP r5,r3
  JMP[GE] @mth_hew_preflight_done

  ; Load next of the current record from bytes +0..+3.
  SHL r10,r6,3
  ADD r10,r10,r1
  LDB r7,r10,0
  LDB r11,r10,1
  SHL r11,r11,8
  BOOL.14 r7,r7,r11
  LDB r11,r10,2
  SHL r11,r11,16
  BOOL.14 r7,r7,r11
  LDB r11,r10,3
  SHL r11,r11,24
  BOOL.14 r7,r7,r11            ; r7 = next

  MOVI r10,5
  CMP r7,r10
  JMP[GE] @mth_hew_reject_5    ; null (0xFFFFFFFF) or out of range
  ADD r6,r7,r0
  JMP @mth_hew_preflight_loop
mth_hew_preflight_done:

  ; ---- commit: every required link is valid; write exactly count ids ----
  ADD r6,r2,r0
  MOVI r5,0
mth_hew_commit_loop:
  CMP r5,r3
  JMP[GE] @mth_hew_success

  ; Load hyperedge_id from bytes +4..+7.
  SHL r10,r6,3
  ADD r10,r10,r1
  LDB r7,r10,4
  LDB r11,r10,5
  SHL r11,r11,8
  BOOL.14 r7,r7,r11
  LDB r11,r10,6
  SHL r11,r11,16
  BOOL.14 r7,r7,r11
  LDB r11,r10,7
  SHL r11,r11,24
  BOOL.14 r7,r7,r11            ; r7 = hyperedge_id

  ; Store one u32 little-endian at out + 4*count.
  SHL r10,r5,2
  ADD r10,r10,r4
  STB r7,r10,0
  SHR r11,r7,8
  STB r11,r10,1
  SHR r11,r11,8
  STB r11,r10,2
  SHR r11,r11,8
  STB r11,r10,3

  ADD r5,r5,r13
  CMP r5,r3
  JMP[GE] @mth_hew_success

  ; Advance only when another step is required. This link was validated by
  ; the preflight pass, so the commit pass cannot fail.
  SHL r10,r6,3
  ADD r10,r10,r1
  LDB r7,r10,0
  LDB r11,r10,1
  SHL r11,r11,8
  BOOL.14 r7,r7,r11
  LDB r11,r10,2
  SHL r11,r11,16
  BOOL.14 r7,r7,r11
  LDB r11,r10,3
  SHL r11,r11,24
  BOOL.14 r7,r7,r11
  ADD r6,r7,r0
  JMP @mth_hew_commit_loop

mth_hew_success:
  MOVI r9,0
  MOVI r1,1
  RET

mth_hew_reject_1:
  MOVI r9,1
  JMP @mth_hew_reject
mth_hew_reject_2:
  MOVI r9,2
  JMP @mth_hew_reject
mth_hew_reject_3:
  MOVI r9,3
  JMP @mth_hew_reject
mth_hew_reject_4:
  MOVI r9,4
  JMP @mth_hew_reject
mth_hew_reject_5:
  MOVI r9,5
  JMP @mth_hew_reject
mth_hew_reject_6:
  MOVI r9,6
mth_hew_reject:
  MOVI r5,0
  MOVI r1,0
  RET
