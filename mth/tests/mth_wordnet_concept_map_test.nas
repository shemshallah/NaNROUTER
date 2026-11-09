; Fixture for the native WordNet concept coordinate map.
;
; Coverage:
;   1. ordinals 0..1023: success, head/peer range, head != peer, pair id
;      range 1..32,640, offset formula 32,768+(id-1)*256, offset range, and
;      256-byte record alignment. The same sweep tracks the observed head
;      minimum and maximum and requires both 0 and 255 to occur.
;   2. 256 rejection probes, one for every high byte while ordinal bits 8..15
;      are 0xFF: the derived peer equals the head, so status, head, pair id,
;      offset, and peer must all be zero (pair id 0 is the void sentinel).
;   3. hard-coded known ordinals, including both pair/offset extremes and
;      swapped endpoints. Expected values are constants; the guest does not
;      derive them from a host oracle.
;   4. explicit collision cases:
;        - 0x00000004 and 0x00000094 produce identical coordinates;
;        - 0x00000000 and 0x000001D2 share head 0 but have different pairs.
;   5. deterministic repeat: the same ordinal is evaluated twice and every
;      output word must match, for both accepted and rejected ordinals.
;
; This fixture proves coordinate hashing only. It does not test or claim a
; semantic WordNet mapping.
;
; Register plan (kernel clobbers only r0-r6 and preserves r7-r15):
;   r7..r10 = expected/saved outputs
;   r11     = saved caller link in helpers
;   r12     = saved ordinal/status in the repeat helper
;   r13     = 1
;   r14     = loop index, later the repeat helper's first status
;   r15     = CALL/RET link

.org 0
JMP @mth_wcm_test_main
.include "../nan16/mth_wordnet_concept_map.nas"

mth_wcm_test_main:
  MOVI r13,1
  MOVI r0,0

  ; ---- sweep ordinals 0..1023, tracking observed head min/max ----
  MOVI r7,255                           ; observed min head
  MOVI r8,0                             ; observed max head
  MOVI r14,0                            ; ordinal
mth_wcm_test_sweep:
  ADD r1,r14,r0
  CALL @mth_wordnet_concept_map

  CMP r1,r13
  JMP[NE] @mth_wcm_test_fail

  ; head and peer are in 0..255
  MOVI r12,255
  CMP r12,r3
  JMP[LT] @mth_wcm_test_fail
  CMP r12,r6
  JMP[LT] @mth_wcm_test_fail

  ; the derived endpoints are distinct on success
  CMP r3,r6
  JMP[EQ] @mth_wcm_test_fail

  ; pair id is one-based and inside 1..32,640
  CMP r4,r0
  JMP[EQ] @mth_wcm_test_fail
  MOVI r12,32640
  CMP r12,r4
  JMP[LT] @mth_wcm_test_fail

  ; offset must equal 32,768 + (pair_id-1)*256
  MOVI r12,0xFFFF
  MOVHI r12,0xFFFF                      ; -1
  ADD r10,r4,r12                        ; pair_id-1
  MOVI r12,256
  MUL r10,r10,r12
  MOVI r12,32768
  ADD r10,r10,r12
  CMP r10,r5
  JMP[NE] @mth_wcm_test_fail

  ; offset is inside [32,768, 8,388,608)
  MOVI r12,32768
  CMP r5,r12
  JMP[LT] @mth_wcm_test_fail
  MOVI r12,0
  MOVHI r12,0x0080                      ; 8,388,608
  CMP r5,r12
  JMP[GE] @mth_wcm_test_fail

  ; records are 256-byte aligned
  MOVI r12,255
  BOOL.8 r10,r5,r12
  CMP r10,r0
  JMP[NE] @mth_wcm_test_fail

  ; observed head min/max
  CMP r3,r7
  JMP[GE] @mth_wcm_test_sweep_no_min
  ADD r7,r3,r0
mth_wcm_test_sweep_no_min:
  CMP r3,r8
  JMP[LE] @mth_wcm_test_sweep_no_max
  ADD r8,r3,r0
mth_wcm_test_sweep_no_max:

  ADD r14,r14,r13
  MOVI r12,1024
  CMP r14,r12
  JMP[LT] @mth_wcm_test_sweep

  ; the sweep must have touched both ends of the 8-bit head range
  CMP r7,r0
  JMP[NE] @mth_wcm_test_fail
  MOVI r12,255
  CMP r8,r12
  JMP[NE] @mth_wcm_test_fail

  ; ---- exhaustive rejection class: bits 8..15 == 0xFF, all high bytes ----
  MOVI r9,0                             ; rejection counter
  MOVI r14,0
mth_wcm_test_reject_loop:
  SHL r1,r14,16
  MOVI r12,0xFF00
  ADD r1,r1,r12
  CALL @mth_wcm_test_expect_reject
  ADD r9,r9,r13
  ADD r14,r14,r13
  MOVI r12,256
  CMP r14,r12
  JMP[LT] @mth_wcm_test_reject_loop
  MOVI r12,256
  CMP r9,r12
  JMP[NE] @mth_wcm_test_fail

  ; ---- hard-coded known accepted ordinals ----
  ; n=0x00000000 -> head 0, peer 1, id 1, offset 32,768
  MOVI r1,0x0000
  MOVHI r1,0x0000
  MOVI r7,0
  MOVI r8,1
  MOVI r9,1
  MOVI r10,32768
  MOVHI r10,0x0000
  CALL @mth_wcm_test_expect

  ; n=0x00000001 -> head 158, peer 159, id 27,888, offset 7,171,840
  MOVI r1,0x0001
  MOVHI r1,0x0000
  MOVI r7,158
  MOVI r8,159
  MOVI r9,27888
  MOVI r10,0x6F00
  MOVHI r10,0x006D
  CALL @mth_wcm_test_expect

  ; n=0x00000004 -> head 120, peer 121, id 23,461, offset 6,038,528
  MOVI r1,0x0004
  MOVHI r1,0x0000
  MOVI r7,120
  MOVI r8,121
  MOVI r9,23461
  MOVI r10,0x2400
  MOVHI r10,0x005C
  CALL @mth_wcm_test_expect

  ; n=0x00000048 -> head 127, peer 128, id 24,385, offset 6,275,072
  MOVI r1,0x0048
  MOVHI r1,0x0000
  MOVI r7,127
  MOVI r8,128
  MOVI r9,24385
  MOVI r10,0xC000
  MOVHI r10,0x005F
  CALL @mth_wcm_test_expect

  ; n=0x00000059 -> head 1, peer 2, id 256, offset 98,048
  MOVI r1,0x0059
  MOVHI r1,0x0000
  MOVI r7,1
  MOVI r8,2
  MOVI r9,256
  MOVI r10,0x7F00
  MOVHI r10,0x0001
  CALL @mth_wcm_test_expect

  ; n=0x00000090 -> head 255, peer 0 (canonical swap), id 255, offset 97,792
  MOVI r1,0x0090
  MOVHI r1,0x0000
  MOVI r7,255
  MOVI r8,0
  MOVI r9,255
  MOVI r10,0x7E00
  MOVHI r10,0x0001
  CALL @mth_wcm_test_expect

  ; n=0x00000094 -> same full coordinates as n=4 (collision case 1)
  MOVI r1,0x0094
  MOVHI r1,0x0000
  MOVI r7,120
  MOVI r8,121
  MOVI r9,23461
  MOVI r10,0x2400
  MOVHI r10,0x005C
  CALL @mth_wcm_test_expect

  ; n=0x000000A1 -> head 128, peer 129, id 24,513, offset 6,307,840
  MOVI r1,0x00A1
  MOVHI r1,0x0000
  MOVI r7,128
  MOVI r8,129
  MOVI r9,24513
  MOVI r10,0x4000
  MOVHI r10,0x0060
  CALL @mth_wcm_test_expect

  ; n=0x000000B2 -> head 2, peer 3, id 510, offset 163,072
  MOVI r1,0x00B2
  MOVHI r1,0x0000
  MOVI r7,2
  MOVI r8,3
  MOVI r9,510
  MOVI r10,0x7D00
  MOVHI r10,0x0002
  CALL @mth_wcm_test_expect

  ; n=0x00000120 -> head 254, peer 0, id 254, offset 97,536
  MOVI r1,0x0120
  MOVHI r1,0x0000
  MOVI r7,254
  MOVI r8,0
  MOVI r9,254
  MOVI r10,0x7D00
  MOVHI r10,0x0001
  CALL @mth_wcm_test_expect

  ; n=0x000001B0 -> head 253, peer 255, id 32,639, offset 8,388,096
  MOVI r1,0x01B0
  MOVHI r1,0x0000
  MOVI r7,253
  MOVI r8,255
  MOVI r9,32639
  MOVI r10,0xFE00
  MOVHI r10,0x007F
  CALL @mth_wcm_test_expect

  ; n=0x000001D2 -> head 0, peer 2 (same head as n=0, different pair)
  MOVI r1,0x01D2
  MOVHI r1,0x0000
  MOVI r7,0
  MOVI r8,2
  MOVI r9,2
  MOVI r10,0x8100
  MOVHI r10,0x0000
  CALL @mth_wcm_test_expect

  ; n=0x0000FE2A -> head 255, peer 254, id 32,640, offset 8,388,352
  MOVI r1,0xFE2A
  MOVHI r1,0x0000
  MOVI r7,255
  MOVI r8,254
  MOVI r9,32640
  MOVI r10,0xFF00
  MOVHI r10,0x007F
  CALL @mth_wcm_test_expect

  ; n=0x0000FEFF -> head 163, peer 162 (swap), id 28,270, offset 7,269,632
  MOVI r1,0xFEFF
  MOVHI r1,0x0000
  MOVI r7,163
  MOVI r8,162
  MOVI r9,28270
  MOVI r10,0xED00
  MOVHI r10,0x006E
  CALL @mth_wcm_test_expect

  ; n=0x00010000 -> head 121, peer 122, id 23,596, offset 6,073,088
  MOVI r1,0x0000
  MOVHI r1,0x0001
  MOVI r7,121
  MOVI r8,122
  MOVI r9,23596
  MOVI r10,0xAB00
  MOVHI r10,0x005C
  CALL @mth_wcm_test_expect

  ; n=0x80000000 -> head 128, peer 129, id 24,513, offset 6,307,840
  MOVI r1,0x0000
  MOVHI r1,0x8000
  MOVI r7,128
  MOVI r8,129
  MOVI r9,24513
  MOVI r10,0x4000
  MOVHI r10,0x0060
  CALL @mth_wcm_test_expect

  ; n=0xFFFFFEFF -> head 42, peer 41 (swap), id 9,636, offset 2,499,328
  MOVI r1,0xFEFF
  MOVHI r1,0xFFFF
  MOVI r7,42
  MOVI r8,41
  MOVI r9,9636
  MOVI r10,0x2300
  MOVHI r10,0x0026
  CALL @mth_wcm_test_expect

  ; ---- known rejected ordinals: derived peer == head, pair id 0 ----
  MOVI r1,0xFF00
  MOVHI r1,0x0000
  CALL @mth_wcm_test_expect_reject

  MOVI r1,0xFFFF
  MOVHI r1,0x0000
  CALL @mth_wcm_test_expect_reject

  MOVI r1,0xFFFF
  MOVHI r1,0x7FFF
  CALL @mth_wcm_test_expect_reject

  MOVI r1,0xFFFE
  MOVHI r1,0xFFFF
  CALL @mth_wcm_test_expect_reject

  MOVI r1,0xFFFF
  MOVHI r1,0xFFFF
  CALL @mth_wcm_test_expect_reject

  ; ---- explicit collision case 1: identical full coordinates ----
  MOVI r1,0x0004
  MOVHI r1,0x0000
  CALL @mth_wordnet_concept_map
  CMP r1,r13
  JMP[NE] @mth_wcm_test_fail
  ADD r7,r3,r0
  ADD r8,r4,r0
  ADD r9,r5,r0
  ADD r10,r6,r0

  MOVI r1,0x0094
  MOVHI r1,0x0000
  CALL @mth_wordnet_concept_map
  CMP r1,r13
  JMP[NE] @mth_wcm_test_fail
  CMP r3,r7
  JMP[NE] @mth_wcm_test_fail
  CMP r4,r8
  JMP[NE] @mth_wcm_test_fail
  CMP r5,r9
  JMP[NE] @mth_wcm_test_fail
  CMP r6,r10
  JMP[NE] @mth_wcm_test_fail

  ; ---- explicit collision case 2: same head, different pair ----
  MOVI r1,0x0000
  MOVHI r1,0x0000
  CALL @mth_wordnet_concept_map
  CMP r1,r13
  JMP[NE] @mth_wcm_test_fail
  ADD r7,r3,r0                          ; head 0
  ADD r8,r4,r0                          ; id 1
  ADD r9,r5,r0                          ; offset
  ADD r10,r6,r0                         ; peer 1

  MOVI r1,0x01D2
  MOVHI r1,0x0000
  CALL @mth_wordnet_concept_map
  CMP r1,r13
  JMP[NE] @mth_wcm_test_fail
  CMP r3,r7                             ; head must match
  JMP[NE] @mth_wcm_test_fail
  CMP r4,r8                             ; pair id must differ
  JMP[EQ] @mth_wcm_test_fail
  CMP r5,r9                             ; offset must differ
  JMP[EQ] @mth_wcm_test_fail
  CMP r6,r10                            ; peer must differ
  JMP[EQ] @mth_wcm_test_fail

  ; ---- deterministic repeat, accepted and rejected ordinals ----
  MOVI r1,0x0000
  MOVHI r1,0x0000
  CALL @mth_wcm_test_expect_repeat

  MOVI r1,0x0004
  MOVHI r1,0x0000
  CALL @mth_wcm_test_expect_repeat

  MOVI r1,0x0094
  MOVHI r1,0x0000
  CALL @mth_wcm_test_expect_repeat

  MOVI r1,0xFEFF
  MOVHI r1,0xFFFF
  CALL @mth_wcm_test_expect_repeat

  MOVI r1,0xFF00
  MOVHI r1,0x0000
  CALL @mth_wcm_test_expect_repeat

  MOVI r1,0xFFFF
  MOVHI r1,0xFFFF
  CALL @mth_wcm_test_expect_repeat

  MOVI r1,@mth_wcm_test_pass
  CALL @mth_wcm_test_puts
  HALT

; r1=ordinal, r7=head, r8=peer, r9=pair id, r10=offset.
; Calls the kernel once and checks every output word.
mth_wcm_test_expect:
  ADD r11,r15,r0
  CALL @mth_wordnet_concept_map
  ADD r15,r11,r0
  CMP r1,r13
  JMP[NE] @mth_wcm_test_fail
  CMP r3,r7
  JMP[NE] @mth_wcm_test_fail
  CMP r6,r8
  JMP[NE] @mth_wcm_test_fail
  CMP r4,r9
  JMP[NE] @mth_wcm_test_fail
  CMP r5,r10
  JMP[NE] @mth_wcm_test_fail
  RET

; r1=ordinal. Requires status 0 and r3-r6 all zero.
mth_wcm_test_expect_reject:
  ADD r11,r15,r0
  CALL @mth_wordnet_concept_map
  ADD r15,r11,r0
  CMP r1,r0
  JMP[NE] @mth_wcm_test_fail
  CMP r3,r0
  JMP[NE] @mth_wcm_test_fail
  CMP r4,r0
  JMP[NE] @mth_wcm_test_fail
  CMP r5,r0
  JMP[NE] @mth_wcm_test_fail
  CMP r6,r0
  JMP[NE] @mth_wcm_test_fail
  RET

; r1=ordinal. Calls twice; status and all four output words must match.
; Clobbers r14 (first status) but preserves r13.
mth_wcm_test_expect_repeat:
  ADD r11,r15,r0
  ADD r12,r1,r0
  CALL @mth_wordnet_concept_map
  ADD r14,r1,r0
  ADD r7,r3,r0
  ADD r8,r4,r0
  ADD r9,r5,r0
  ADD r10,r6,r0
  ADD r1,r12,r0
  CALL @mth_wordnet_concept_map
  ADD r15,r11,r0
  CMP r1,r14
  JMP[NE] @mth_wcm_test_fail
  CMP r3,r7
  JMP[NE] @mth_wcm_test_fail
  CMP r4,r8
  JMP[NE] @mth_wcm_test_fail
  CMP r5,r9
  JMP[NE] @mth_wcm_test_fail
  CMP r6,r10
  JMP[NE] @mth_wcm_test_fail
  RET

mth_wcm_test_fail:
  MOVI r1,@mth_wcm_test_bad
  CALL @mth_wcm_test_puts
  HALT

; r1=NUL-terminated string; writes bytes through PUTC.
mth_wcm_test_puts:
  MOVI r4,255
mth_wcm_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_wcm_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_wcm_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_wcm_test_puts_word

.org 2048
mth_wcm_test_pass:
.str "MTH WORDNET CONCEPT MAP PASS\n"
mth_wcm_test_bad:
.str "MTH WORDNET CONCEPT MAP FAIL\n"
