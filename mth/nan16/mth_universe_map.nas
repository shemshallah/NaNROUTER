; MTH full 8 MiB universe map and NANNET relation-point address kernel.
;
; ABI (r13=1):
;   r1 = canonical cell, 0..32895
;        0..255   fixed heads (head 0 is NANNET0)
;        256..32895 mirror-pair canonical cells
;   r2 = relation layer, 0..9
;
; On success:
;   r1 = 1
;   r2 = page, 0..255
;   r3 = word inside the page, 0..4095
;   r4 = guest word address, 0..1048575 (the complete 8 MiB universe)
;   r5 = point kind (0 = fixed head, 1 = mirror pair)
;   r6 = head id or mirror-pair ordinal
;   r7 = layer echo
;
; On rejection:
;   r1 = 0 and r2..r7 are unspecified.
;
; Address law:
;   head 0          -> page 255, word 0        (NANNET0 alias)
;   head 1..255     -> page head-1, word 0
;   mirror pair n   -> page n % 255,
;                      word 3840 + 2*(n / 255)
;
; Guest word = page*4096 + word. The 2-word mirror-pair slots occupy words
; 3840..4095 of each real-head page: 128 slots x 255 pages = 32,640 pairs.
; The NANNET0 page is the single control page and contains no mirror records.
;
; This kernel performs address arithmetic only. It does not read or write
; relation data, execute another kernel, authorize a route, or claim that a
; relation is mathematically true.
;
; Clobbers r1-r13 and flags. The caller owns any memory the addresses refer to.
; The mirror-pair division is inlined so this kernel never nests CALL/RET
; through the single r15 link register.

mth_universe_map:
  MOVI r13,1
  MOVI r10,9
  CMP r2,r10
  JMP[GT] @mth_universe_map_reject
  MOVI r10,32895
  CMP r1,r10
  JMP[GT] @mth_universe_map_reject
  MOVI r10,256
  CMP r1,r10
  JMP[LT] @mth_universe_map_head

  ; ---- Mirror-pair cell: mp = cell-256; slot = mp/255; page = mp%255 ----
  ADD r11,r1,r0             ; preserve canonical cell
  ADD r12,r2,r0             ; preserve layer
  SUB r1,r1,r10             ; dividend = mp = cell - 256
  MOVI r5,0                 ; quotient (slot)
  MOVI r4,0                 ; remainder (page)
  MOVI r7,32                ; 32-bit restoring division
mth_universe_map_div_loop:
  SHR r8,r1,31              ; next dividend bit
  SHL r1,r1,1
  SHL r4,r4,1
  BOOL.14 r4,r4,r8          ; append dividend bit
  SHL r5,r5,1               ; make room for quotient bit
  MOVI r9,255
  CMP r4,r9
  JMP[LT] @mth_universe_map_div_no_sub
  SUB r4,r4,r9
  ADD r5,r5,r13
mth_universe_map_div_no_sub:
  SUB r7,r7,r13
  JMP[GT] @mth_universe_map_div_loop

  ADD r2,r4,r0              ; page = remainder
  SHL r3,r5,1               ; slot*2
  MOVI r4,3840
  ADD r3,r3,r4              ; word = 3840 + 2*slot
  SHL r4,r2,12              ; page*4096
  ADD r4,r4,r3              ; guest word
  MOVI r5,1                 ; mirror-pair kind
  MOVI r10,256
  SUB r6,r11,r10            ; mp ordinal
  ADD r7,r12,r0             ; layer echo
  MOVI r1,1
  RET

  ; ---- Fixed head: head 0 is the NANNET0 page; head 1..255 is page head-1 ----
mth_universe_map_head:
  ADD r11,r1,r0             ; preserve head id
  ADD r12,r2,r0             ; preserve layer
  CMP r1,r0
  JMP[EQ] @mth_universe_map_nannet0
  SUB r2,r1,r13             ; page = head-1
  JMP @mth_universe_map_head_done

mth_universe_map_nannet0:
  MOVI r2,255               ; NANNET0 page

mth_universe_map_head_done:
  MOVI r3,0                 ; head records start at word 0
  SHL r4,r2,12              ; page*4096
  MOVI r5,0                 ; fixed-head kind
  ADD r6,r11,r0             ; head id
  ADD r7,r12,r0             ; layer echo
  MOVI r1,1
  RET

mth_universe_map_reject:
  MOVI r1,0
  RET
