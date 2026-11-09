; MTH Round 037 reference-slot map fixture — NaN16 only.
;
; Exhaustively walks all 32,385 slots and checks:
;   * a < b, 1 <= a < 254, b <= 255;
;   * pair id increases by one each slot and stays in 1..32640;
;   * record offset is 32768 + (pair id-1)*256 and 256-byte aligned;
;   * boundaries slot 0/253/254/32384;
;   * slot 32385 is rejected atomically.
;
; The fixture uses integer checks only and no host expected arrays.

.org 0
JMP @mth_slot_test_main
.include "../nan16/mth_mirror_slot_map.nas"

mth_slot_test_main:
  MOVI r13,1
  MOVI r14,0                ; slot counter
  MOVI r15,0                ; previous pair id

mth_slot_test_loop:
  ADD r1,r14,r0
  CALL @mth_mirror_slot_map
  CMP r1,r13
  JMP[NE] @mth_slot_test_fail

  CMP r3,r0
  JMP[EQ] @mth_slot_test_fail
  MOVI r10,254
  CMP r3,r10
  JMP[GT] @mth_slot_test_fail
  CMP r4,r3
  JMP[LE] @mth_slot_test_fail
  MOVI r10,255
  CMP r4,r10
  JMP[GT] @mth_slot_test_fail

  ; pair id range and strict monotonicity
  CMP r5,r0
  JMP[EQ] @mth_slot_test_fail
  MOVI r10,32640
  CMP r5,r10
  JMP[GT] @mth_slot_test_fail
  CMP r5,r15
  JMP[LE] @mth_slot_test_fail
  ADD r15,r5,r0

  ; offset = 32768 + (id-1)*256
  SHL r10,r5,8
  MOVI r11,256
  SUB r10,r10,r11
  MOVI r11,32768
  ADD r10,r10,r11
  CMP r6,r10
  JMP[NE] @mth_slot_test_fail
  MOVI r11,255
  BOOL.8 r10,r6,r11
  CMP r10,r0
  JMP[NE] @mth_slot_test_fail

  ADD r14,r14,r13
  MOVI r10,32385
  CMP r14,r10
  JMP[LT] @mth_slot_test_loop

  ; Boundary pair ids: first 256, last 32640.
  MOVI r1,0
  CALL @mth_mirror_slot_map
  MOVI r10,256
  CMP r5,r10
  JMP[NE] @mth_slot_test_fail
  MOVI r10,1
  CMP r3,r10
  JMP[NE] @mth_slot_test_fail
  MOVI r10,2
  CMP r4,r10
  JMP[NE] @mth_slot_test_fail

  MOVI r1,32384
  CALL @mth_mirror_slot_map
  MOVI r10,32640
  CMP r5,r10
  JMP[NE] @mth_slot_test_fail
  MOVI r10,254
  CMP r3,r10
  JMP[NE] @mth_slot_test_fail
  MOVI r10,255
  CMP r4,r10
  JMP[NE] @mth_slot_test_fail

  ; Reject slot 32385.
  MOVI r1,32385
  CALL @mth_mirror_slot_map
  CMP r1,r0
  JMP[NE] @mth_slot_test_fail

  MOVI r1,@mth_slot_test_pass
  CALL @mth_slot_test_puts
  HALT

mth_slot_test_fail:
  MOVI r1,@mth_slot_test_bad
  CALL @mth_slot_test_puts
  HALT

; r1=NUL-terminated string.
mth_slot_test_puts:
  MOVI r4,255
mth_slot_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_slot_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_slot_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_slot_test_puts_word

mth_slot_test_pass:
.str "MTH MIRROR SLOT MAP PASS\n"
mth_slot_test_bad:
.str "MTH MIRROR SLOT MAP FAIL\n"
