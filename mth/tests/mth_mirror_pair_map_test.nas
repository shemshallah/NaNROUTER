.org 0
JMP @mth_mirror_test_main
.include "../nan16/mth_mirror_pair_map.nas"

; Fixture for the canonical 8,388,608-byte mirror-memory pair map.
;
; Coverage:
;   1. exhaustive lexicographic sweep of every unordered pair a<b over
;      0..255 (32,640 calls), checking:
;        - success status r1=1;
;        - pair_id r3 == the running id 1..32,640 (monotone, no gaps);
;        - explicit id range 1..32,640;
;        - byte offset r4 == the running offset 32,768 + (id-1)*256;
;        - r4 within [32,768, 8,388,608) and 256-byte record aligned;
;        - lane0 r5 == record base;
;        - lane1 - lane0 == 128.
;   2. final counter checks: next id 32,641 and next offset 8,388,608.
;   3. hard-coded known/sampled pairs (including both ends of the id range
;      and rows in the middle) checked against exact ids and byte offsets.
;   4. one reverse-order call, checking endpoint canonicalization.
;   5. rejection of a==b and unsigned out-of-range endpoints, including
;      large 32-bit values, with r3-r6 cleared.
;
; The fixture computes addresses only; it does not materialize the 8 MiB
; pair arena. The kernel's contract is address mapping, not memory access.
;
; Register plan (kernel clobbers only r0-r6):
;   r7  = a
;   r8  = b
;   r9  = expected pair id
;   r10 = expected record offset (reused by the helpers after the sweep
;         to save their nested-call return link)
;   r11/r12/r14 = check temporaries
;   r13 = 1
;   r15 = CALL/RET link

mth_mirror_test_main:
  MOVI r13,1
  MOVI r0,0

  ; ---- exhaustive sweep: a = 0..254, b = a+1..255 ----
  MOVI r7,0                             ; a = 0
  MOVI r9,1                             ; first pair id
  MOVI r10,32768                        ; first record byte offset
mth_mirror_test_row:
  ADD r8,r7,r13                         ; b = a+1
mth_mirror_test_col:
  ADD r1,r7,r0
  ADD r2,r8,r0
  CALL @mth_mirror_pair_map

  CMP r1,r13
  JMP[NE] @mth_mirror_test_fail

  ; pair id must equal the lexicographic running count
  CMP r3,r9
  JMP[NE] @mth_mirror_test_fail

  ; explicit range: 1 <= id <= 32,640 (0 is the void sentinel)
  MOVI r12,0
  CMP r3,r12
  JMP[EQ] @mth_mirror_test_fail
  MOVI r12,32640
  CMP r12,r3
  JMP[LT] @mth_mirror_test_fail

  ; record offset must equal 32,768 + (id-1)*256
  CMP r4,r10
  JMP[NE] @mth_mirror_test_fail

  ; offset range [32,768, 8,388,608)
  MOVI r12,32768
  CMP r4,r12
  JMP[LT] @mth_mirror_test_fail
  MOVI r12,0
  MOVHI r12,0x80                        ; 8,388,608
  CMP r4,r12
  JMP[GE] @mth_mirror_test_fail

  ; 256-byte record alignment: low byte of offset is zero
  MOVI r12,255
  BOOL.8 r14,r4,r12
  CMP r14,r0
  JMP[NE] @mth_mirror_test_fail

  ; lane0 is the record base; lane1 is exactly 128 bytes later
  CMP r5,r4
  JMP[NE] @mth_mirror_test_fail
  SUB r14,r6,r5
  MOVI r12,128
  CMP r14,r12
  JMP[NE] @mth_mirror_test_fail

  ; advance expected id and offset
  ADD r9,r9,r13
  MOVI r12,256
  ADD r10,r10,r12

  ; next b in this row
  ADD r8,r8,r13
  MOVI r12,256
  CMP r8,r12
  JMP[LT] @mth_mirror_test_col

  ; next a (0..254)
  ADD r7,r7,r13
  MOVI r12,255
  CMP r7,r12
  JMP[LT] @mth_mirror_test_row

  ; ---- final sweep counters ----
  MOVI r12,32641
  CMP r9,r12
  JMP[NE] @mth_mirror_test_fail
  MOVI r12,0
  MOVHI r12,0x80                        ; 8,388,608
  CMP r10,r12
  JMP[NE] @mth_mirror_test_fail

  ; ---- exact known/sampled pairs ----
  ; (0,1): id 1, record 32,768
  MOVI r1,0
  MOVI r2,1
  MOVI r3,1
  MOVI r4,32768
  CALL @mth_mirror_test_expect

  ; (0,2): id 2, record 33,024
  MOVI r1,0
  MOVI r2,2
  MOVI r3,2
  MOVI r4,33024
  CALL @mth_mirror_test_expect

  ; (1,2): id 256, record 98,048
  MOVI r1,1
  MOVI r2,2
  MOVI r3,256
  MOVI r4,32512
  MOVHI r4,1
  CALL @mth_mirror_test_expect

  ; (1,3): id 257, record 98,304
  MOVI r1,1
  MOVI r2,3
  MOVI r3,257
  MOVI r4,32768
  MOVHI r4,1
  CALL @mth_mirror_test_expect

  ; (2,3): id 510, record 163,072
  MOVI r1,2
  MOVI r2,3
  MOVI r3,510
  MOVI r4,32000
  MOVHI r4,2
  CALL @mth_mirror_test_expect

  ; (2,4): id 511, record 163,328
  MOVI r1,2
  MOVI r2,4
  MOVI r3,511
  MOVI r4,32256
  MOVHI r4,2
  CALL @mth_mirror_test_expect

  ; (127,128): id 24,385, record 6,275,072
  MOVI r1,127
  MOVI r2,128
  MOVI r3,24385
  MOVI r4,49152
  MOVHI r4,0x5F
  CALL @mth_mirror_test_expect

  ; (128,255): id 24,639, record 6,340,096
  MOVI r1,128
  MOVI r2,255
  MOVI r3,24639
  MOVI r4,48640
  MOVHI r4,0x60
  CALL @mth_mirror_test_expect

  ; boundary: (0,255) -> id 255, record 97,792
  MOVI r1,0
  MOVI r2,255
  MOVI r3,255
  MOVI r4,32256
  MOVHI r4,1
  CALL @mth_mirror_test_expect

  ; boundary: (254,255) -> id 32,640, record 8,388,352
  MOVI r1,254
  MOVI r2,255
  MOVI r3,32640
  MOVI r4,65280
  MOVHI r4,0x7F
  CALL @mth_mirror_test_expect

  ; reverse-order call (255,0) must canonicalize to the same unordered pair
  MOVI r1,255
  MOVI r2,0
  MOVI r3,255
  MOVI r4,32256
  MOVHI r4,1
  CALL @mth_mirror_test_expect

  ; ---- rejection: a == b ----
  MOVI r1,0
  MOVI r2,0
  CALL @mth_mirror_test_expect_reject

  MOVI r1,255
  MOVI r2,255
  CALL @mth_mirror_test_expect_reject

  ; ---- rejection: unsigned out-of-range endpoints ----
  MOVI r1,256
  MOVI r2,257
  CALL @mth_mirror_test_expect_reject

  MOVI r1,0
  MOVI r2,256
  CALL @mth_mirror_test_expect_reject

  MOVI r1,255
  MOVI r2,256
  CALL @mth_mirror_test_expect_reject

  MOVI r1,0xFFFF
  MOVHI r1,0xFFFF
  MOVI r2,0
  CALL @mth_mirror_test_expect_reject

  MOVI r1,0
  MOVI r2,0xFFFF
  MOVHI r2,0xFFFF
  CALL @mth_mirror_test_expect_reject

  MOVI r1,0
  MOVHI r1,1                            ; 65,536
  MOVI r2,0
  CALL @mth_mirror_test_expect_reject

  MOVI r1,@mth_mirror_test_pass
  CALL @mth_mirror_test_puts
  HALT

; r1=a, r2=b, r3=expected pair id, r4=expected record offset.
; Verifies success, id, offset, lane0, and lane1 separation.
mth_mirror_test_expect:
  ADD r10,r15,r0                        ; save caller link across nested CALL
  ADD r11,r3,r0
  ADD r12,r4,r0
  CALL @mth_mirror_pair_map
  ADD r15,r10,r0                        ; restore caller link
  CMP r1,r13
  JMP[NE] @mth_mirror_test_fail
  CMP r3,r11
  JMP[NE] @mth_mirror_test_fail
  CMP r4,r12
  JMP[NE] @mth_mirror_test_fail
  CMP r5,r12
  JMP[NE] @mth_mirror_test_fail
  SUB r14,r6,r5
  MOVI r11,128
  CMP r14,r11
  JMP[NE] @mth_mirror_test_fail
  RET

; r1=a, r2=b already set. Requires r1=0 and r3-r6=0 after rejection.
mth_mirror_test_expect_reject:
  ADD r10,r15,r0                        ; save caller link across nested CALL
  CALL @mth_mirror_pair_map
  ADD r15,r10,r0                        ; restore caller link
  CMP r1,r0
  JMP[NE] @mth_mirror_test_fail
  CMP r3,r0
  JMP[NE] @mth_mirror_test_fail
  CMP r4,r0
  JMP[NE] @mth_mirror_test_fail
  CMP r5,r0
  JMP[NE] @mth_mirror_test_fail
  CMP r6,r0
  JMP[NE] @mth_mirror_test_fail
  RET

mth_mirror_test_fail:
  MOVI r1,@mth_mirror_test_bad
  CALL @mth_mirror_test_puts
  HALT

mth_mirror_test_puts:
  MOVI r4,255
mth_mirror_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_mirror_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_mirror_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_mirror_test_puts_word

.org 1024
mth_mirror_test_pass:
.str "MTH MIRROR PAIR MAP PASS\n"
mth_mirror_test_bad:
.str "MTH MIRROR PAIR MAP FAIL\n"
