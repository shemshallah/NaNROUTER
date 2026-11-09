; MTH batch hyperedge-strength update fixture — native NaN16 only.
;
; In-guest coverage, no host arithmetic:
;   1. valid batch over four of eight records with eta = 0.25, exact f32
;      results, unchanged next links, and untouched trailing records;
;   2. high and low clamp saturation at exactly +8.0 and -8.0;
;   3. duplicate ids applied in array order, so each later duplicate sees
;      the earlier result;
;   4. atomic rejection of id 0 and of id r2+1 with cause 1;
;   5. atomic rejection of NaN, +Inf, and -Inf gradients with cause 2;
;   6. atomic rejection of NaN, +Inf, and -Inf eta with cause 3;
;   7. an empty batch succeeds without reading entries, including an
;      empty batch over a zero-record arena;
;   8. atomic rejection of a count above 0x0FFFFFFF and of an oversized
;      record count with cause 5;
;   9. atomic rejection of a referenced NaN stored strength with cause 4;
;  10. every success returns r1=1, r9=0; every rejection returns r1=0 with
;      the documented r9 cause and no strength/next mutation.
;
; The record arena is laid out as packed eight-byte records in the NaN16
; payload byte space: strength word, next word, stride two words. The test
; uses LD/ST for direct word inspection and passes label<<2 as the byte
; address of each arena.

.org 0
JMP @mth_hb_test_main
.include "../nan16/mth_hyperedge_strength_batch.nas"

mth_hb_test_main:
  MOVI r13,1

  ; ================= Case 1: valid batch =================
  CALL @mth_hb_test_reset
  MOVI r1,0
  MOVI r2,1
  CALL @mth_hb_test_set_id
  MOVI r1,1
  MOVI r2,2
  CALL @mth_hb_test_set_id
  MOVI r1,2
  MOVI r2,3
  CALL @mth_hb_test_set_id
  MOVI r1,3
  MOVI r2,7
  CALL @mth_hb_test_set_id

  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x3F80            ; +1.0
  CALL @mth_hb_test_set_grad
  MOVI r1,1
  MOVI r2,0
  MOVHI r2,0xBF80            ; -1.0
  CALL @mth_hb_test_set_grad
  MOVI r1,2
  MOVI r2,0
  MOVHI r2,0x3F00            ; +0.5
  CALL @mth_hb_test_set_grad
  MOVI r1,3
  MOVI r2,0
  MOVHI r2,0xC000            ; -2.0
  CALL @mth_hb_test_set_grad

  MOVI r7,4
  MOVI r8,0
  MOVHI r8,0x3E80            ; eta = +0.25
  MOVI r9,8
  CALL @mth_hb_test_call
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_1
  CMP r9,r0
  JMP[NE] @mth_hb_test_fail_1

  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x3E80            ; 0.25
  MOVI r3,0x11
  CALL @mth_hb_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_1

  MOVI r1,1
  MOVI r2,0
  MOVHI r2,0x4010            ; 2.25
  MOVI r3,0x22
  CALL @mth_hb_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_1

  MOVI r1,2
  MOVI r2,0
  MOVHI r2,0x4048            ; 3.125
  MOVI r3,0x33
  CALL @mth_hb_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_1

  MOVI r1,6
  MOVI r2,0
  MOVHI r2,0x3FC0            ; 1.5
  MOVI r3,0x77
  CALL @mth_hb_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_1

  ; Untouched records, including the trailing record 8.
  MOVI r1,3
  MOVI r2,0
  MOVHI r2,0x40F0            ; 7.5
  MOVI r3,0x44
  CALL @mth_hb_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_1
  MOVI r1,4
  MOVI r2,0
  MOVHI r2,0xC0F0            ; -7.5
  MOVI r3,0x55
  CALL @mth_hb_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_1
  MOVI r1,5
  MOVI r2,0
  MOVHI r2,0xC000            ; -2.0
  MOVI r3,0x66
  CALL @mth_hb_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_1
  MOVI r1,7
  MOVI r2,0
  MOVHI r2,0xBF80            ; -1.0
  MOVI r3,0x88
  CALL @mth_hb_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_1

  ; ================= Case 2: clamp high and low =================
  CALL @mth_hb_test_reset
  MOVI r1,0
  MOVI r2,4
  CALL @mth_hb_test_set_id
  MOVI r1,1
  MOVI r2,5
  CALL @mth_hb_test_set_id
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0xC000            ; -2.0
  CALL @mth_hb_test_set_grad
  MOVI r1,1
  MOVI r2,0
  MOVHI r2,0x4000            ; +2.0
  CALL @mth_hb_test_set_grad
  MOVI r7,2
  MOVI r8,0
  MOVHI r8,0x3F80            ; eta = +1.0
  MOVI r9,8
  CALL @mth_hb_test_call
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_2
  CMP r9,r0
  JMP[NE] @mth_hb_test_fail_2

  MOVI r1,3
  MOVI r2,0
  MOVHI r2,0x4100            ; +8.0 saturated
  MOVI r3,0x44
  CALL @mth_hb_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_2
  MOVI r1,4
  MOVI r2,0
  MOVHI r2,0xC100            ; -8.0 saturated
  MOVI r3,0x55
  CALL @mth_hb_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_2
  ; Records 6, 7, and 8 are untouched, including trailing record 8.
  MOVI r1,5
  MOVI r2,0
  MOVHI r2,0xC000
  MOVI r3,0x66
  CALL @mth_hb_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_2
  MOVI r1,6
  MOVI r2,0
  MOVHI r2,0x3F80
  MOVI r3,0x77
  CALL @mth_hb_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_2
  MOVI r1,7
  MOVI r2,0
  MOVHI r2,0xBF80
  MOVI r3,0x88
  CALL @mth_hb_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_2

  ; ================= Case 3: duplicate ids are sequential =================
  CALL @mth_hb_test_reset
  MOVI r1,0
  MOVI r2,1
  CALL @mth_hb_test_set_id
  MOVI r1,1
  MOVI r2,1
  CALL @mth_hb_test_set_id
  MOVI r1,2
  MOVI r2,1
  CALL @mth_hb_test_set_id
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x3F80
  CALL @mth_hb_test_set_grad
  MOVI r1,1
  MOVI r2,0
  MOVHI r2,0x3F80
  CALL @mth_hb_test_set_grad
  MOVI r1,2
  MOVI r2,0
  MOVHI r2,0x3F80
  CALL @mth_hb_test_set_grad
  MOVI r7,3
  MOVI r8,0
  MOVHI r8,0x3E80            ; eta = +0.25
  MOVI r9,8
  CALL @mth_hb_test_call
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_3
  CMP r9,r0
  JMP[NE] @mth_hb_test_fail_3

  ; 0.5 -> 0.25 -> 0.0 -> -0.25
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0xBE80            ; -0.25
  MOVI r3,0x11
  CALL @mth_hb_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_3
  MOVI r1,1
  MOVI r2,0
  MOVHI r2,0x4000            ; 2.0
  MOVI r3,0x22
  CALL @mth_hb_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_3
  MOVI r1,2
  MOVI r2,0
  MOVHI r2,0x4050            ; 3.25
  MOVI r3,0x33
  CALL @mth_hb_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_3
  MOVI r1,7
  MOVI r2,0
  MOVHI r2,0xBF80            ; trailing record unchanged
  MOVI r3,0x88
  CALL @mth_hb_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_3

  ; ================= Case 4: id 0 rejects atomically =================
  CALL @mth_hb_test_reset
  MOVI r1,0
  MOVI r2,1
  CALL @mth_hb_test_set_id
  MOVI r1,1
  MOVI r2,0
  CALL @mth_hb_test_set_id
  MOVI r1,2
  MOVI r2,3
  CALL @mth_hb_test_set_id
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x3F80
  CALL @mth_hb_test_set_grad
  MOVI r1,1
  MOVI r2,0
  MOVHI r2,0x3F80
  CALL @mth_hb_test_set_grad
  MOVI r1,2
  MOVI r2,0
  MOVHI r2,0x3F80
  CALL @mth_hb_test_set_grad
  MOVI r7,3
  MOVI r8,0
  MOVHI r8,0x3F00            ; eta = +0.5
  MOVI r9,8
  CALL @mth_hb_test_call
  CMP r1,r0
  JMP[NE] @mth_hb_test_fail_4
  MOVI r10,1
  CMP r9,r10
  JMP[NE] @mth_hb_test_fail_4
  CALL @mth_hb_test_check_all_initial
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_4

  ; ================= Case 5: id r2+1 rejects atomically =================
  CALL @mth_hb_test_reset
  MOVI r1,0
  MOVI r2,1
  CALL @mth_hb_test_set_id
  MOVI r1,1
  MOVI r2,9
  CALL @mth_hb_test_set_id
  MOVI r1,2
  MOVI r2,3
  CALL @mth_hb_test_set_id
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x3F80
  CALL @mth_hb_test_set_grad
  MOVI r1,1
  MOVI r2,0
  MOVHI r2,0x3F80
  CALL @mth_hb_test_set_grad
  MOVI r1,2
  MOVI r2,0
  MOVHI r2,0x3F80
  CALL @mth_hb_test_set_grad
  MOVI r7,3
  MOVI r8,0
  MOVHI r8,0x3F00
  MOVI r9,8
  CALL @mth_hb_test_call
  CMP r1,r0
  JMP[NE] @mth_hb_test_fail_5
  MOVI r10,1
  CMP r9,r10
  JMP[NE] @mth_hb_test_fail_5
  CALL @mth_hb_test_check_all_initial
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_5

  ; ================= Case 6: NaN gradient rejects atomically =================
  CALL @mth_hb_test_reset
  MOVI r1,0
  MOVI r2,1
  CALL @mth_hb_test_set_id
  MOVI r1,1
  MOVI r2,2
  CALL @mth_hb_test_set_id
  MOVI r1,2
  MOVI r2,3
  CALL @mth_hb_test_set_id
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x3F80
  CALL @mth_hb_test_set_grad
  MOVI r1,1
  MOVI r2,0
  MOVHI r2,0x7FC0            ; canonical quiet NaN
  CALL @mth_hb_test_set_grad
  MOVI r1,2
  MOVI r2,0
  MOVHI r2,0x3F80
  CALL @mth_hb_test_set_grad
  MOVI r7,3
  MOVI r8,0
  MOVHI r8,0x3F00
  MOVI r9,8
  CALL @mth_hb_test_call
  CMP r1,r0
  JMP[NE] @mth_hb_test_fail_6
  MOVI r10,2
  CMP r9,r10
  JMP[NE] @mth_hb_test_fail_6
  CALL @mth_hb_test_check_all_initial
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_6

  ; ================= Case 7: +Inf gradient rejects atomically =================
  CALL @mth_hb_test_reset
  MOVI r1,0
  MOVI r2,1
  CALL @mth_hb_test_set_id
  MOVI r1,1
  MOVI r2,2
  CALL @mth_hb_test_set_id
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x3F80
  CALL @mth_hb_test_set_grad
  MOVI r1,1
  MOVI r2,0
  MOVHI r2,0x7F80            ; +Inf
  CALL @mth_hb_test_set_grad
  MOVI r7,2
  MOVI r8,0
  MOVHI r8,0x3F00
  MOVI r9,8
  CALL @mth_hb_test_call
  CMP r1,r0
  JMP[NE] @mth_hb_test_fail_7
  MOVI r10,2
  CMP r9,r10
  JMP[NE] @mth_hb_test_fail_7
  CALL @mth_hb_test_check_all_initial
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_7

  ; ================= Case 8: -Inf gradient rejects atomically =================
  CALL @mth_hb_test_reset
  MOVI r1,0
  MOVI r2,1
  CALL @mth_hb_test_set_id
  MOVI r1,1
  MOVI r2,2
  CALL @mth_hb_test_set_id
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x3F80
  CALL @mth_hb_test_set_grad
  MOVI r1,1
  MOVI r2,0
  MOVHI r2,0xFF80            ; -Inf
  CALL @mth_hb_test_set_grad
  MOVI r7,2
  MOVI r8,0
  MOVHI r8,0x3F00
  MOVI r9,8
  CALL @mth_hb_test_call
  CMP r1,r0
  JMP[NE] @mth_hb_test_fail_8
  MOVI r10,2
  CMP r9,r10
  JMP[NE] @mth_hb_test_fail_8
  CALL @mth_hb_test_check_all_initial
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_8

  ; ================= Case 9: NaN eta rejects atomically =================
  CALL @mth_hb_test_reset
  MOVI r1,0
  MOVI r2,1
  CALL @mth_hb_test_set_id
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x3F80
  CALL @mth_hb_test_set_grad
  MOVI r7,1
  MOVI r8,0
  MOVHI r8,0x7FC0
  MOVI r9,8
  CALL @mth_hb_test_call
  CMP r1,r0
  JMP[NE] @mth_hb_test_fail_9
  MOVI r10,3
  CMP r9,r10
  JMP[NE] @mth_hb_test_fail_9
  CALL @mth_hb_test_check_all_initial
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_9

  ; ================= Case 10: +Inf eta rejects atomically =================
  CALL @mth_hb_test_reset
  MOVI r1,0
  MOVI r2,1
  CALL @mth_hb_test_set_id
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x3F80
  CALL @mth_hb_test_set_grad
  MOVI r7,1
  MOVI r8,0
  MOVHI r8,0x7F80
  MOVI r9,8
  CALL @mth_hb_test_call
  CMP r1,r0
  JMP[NE] @mth_hb_test_fail_10
  MOVI r10,3
  CMP r9,r10
  JMP[NE] @mth_hb_test_fail_10
  CALL @mth_hb_test_check_all_initial
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_10

  ; ================= Case 11: -Inf eta rejects atomically =================
  CALL @mth_hb_test_reset
  MOVI r1,0
  MOVI r2,1
  CALL @mth_hb_test_set_id
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x3F80
  CALL @mth_hb_test_set_grad
  MOVI r7,1
  MOVI r8,0
  MOVHI r8,0xFF80
  MOVI r9,8
  CALL @mth_hb_test_call
  CMP r1,r0
  JMP[NE] @mth_hb_test_fail_11
  MOVI r10,3
  CMP r9,r10
  JMP[NE] @mth_hb_test_fail_11
  CALL @mth_hb_test_check_all_initial
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_11

  ; ================= Case 12: empty batch =================
  CALL @mth_hb_test_reset
  ; Poison entry 0. With count 0 it must not be inspected.
  MOVI r1,0
  MOVI r2,0
  CALL @mth_hb_test_set_id
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x7FC0
  CALL @mth_hb_test_set_grad
  MOVI r7,0
  MOVI r8,0
  MOVHI r8,0x3F00            ; eta = +0.5
  MOVI r9,8
  CALL @mth_hb_test_call
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_12
  CMP r9,r0
  JMP[NE] @mth_hb_test_fail_12
  CALL @mth_hb_test_check_all_initial
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_12

  ; Empty batch over a zero-record arena is also a success.
  MOVI r7,0
  MOVI r8,0
  MOVHI r8,0x3F00
  MOVI r9,0
  CALL @mth_hb_test_call
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_12
  CMP r9,r0
  JMP[NE] @mth_hb_test_fail_12
  CALL @mth_hb_test_check_all_initial
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_12

  ; ================= Case 13: count above 0x0FFFFFFF =================
  CALL @mth_hb_test_reset
  MOVI r7,0
  MOVHI r7,0x1000            ; 0x10000000 entries
  MOVI r8,0
  MOVHI r8,0x3F00
  MOVI r9,8
  CALL @mth_hb_test_call
  CMP r1,r0
  JMP[NE] @mth_hb_test_fail_13
  MOVI r10,5
  CMP r9,r10
  JMP[NE] @mth_hb_test_fail_13
  CALL @mth_hb_test_check_all_initial
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_13

  ; ================= Case 14: record count above 0x0FFFFFFF =================
  CALL @mth_hb_test_reset
  MOVI r7,0
  MOVI r8,0
  MOVHI r8,0x3F00
  MOVI r9,0
  MOVHI r9,0x1000
  CALL @mth_hb_test_call
  CMP r1,r0
  JMP[NE] @mth_hb_test_fail_14
  MOVI r10,5
  CMP r9,r10
  JMP[NE] @mth_hb_test_fail_14
  CALL @mth_hb_test_check_all_initial
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_14

  ; ================= Case 15: referenced NaN strength =================
  CALL @mth_hb_test_reset
  MOVI r1,@mth_hb_records
  ADDI r1,r1,4
  MOVI r2,0
  MOVHI r2,0x7FC0
  ST r2,r1,0                 ; record 3 strength = NaN
  MOVI r1,0
  MOVI r2,3
  CALL @mth_hb_test_set_id
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x3F80
  CALL @mth_hb_test_set_grad
  MOVI r7,1
  MOVI r8,0
  MOVHI r8,0x3F00
  MOVI r9,8
  CALL @mth_hb_test_call
  CMP r1,r0
  JMP[NE] @mth_hb_test_fail_15
  MOVI r10,4
  CMP r9,r10
  JMP[NE] @mth_hb_test_fail_15

  ; The NaN strength remains, and no other record or next field moved.
  MOVI r1,2
  MOVI r2,0
  MOVHI r2,0x7FC0
  MOVI r3,0x33
  CALL @mth_hb_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_15
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x3F00
  MOVI r3,0x11
  CALL @mth_hb_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_15
  MOVI r1,1
  MOVI r2,0
  MOVHI r2,0x4000
  MOVI r3,0x22
  CALL @mth_hb_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_15
  MOVI r1,7
  MOVI r2,0
  MOVHI r2,0xBF80
  MOVI r3,0x88
  CALL @mth_hb_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hb_test_fail_15

  MOVI r1,@mth_hb_test_pass
  CALL @mth_hb_test_puts
  HALT

; ---- failure reporting ----
mth_hb_test_fail_1:
  MOVI r6,49
  JMP @mth_hb_test_fail
mth_hb_test_fail_2:
  MOVI r6,50
  JMP @mth_hb_test_fail
mth_hb_test_fail_3:
  MOVI r6,51
  JMP @mth_hb_test_fail
mth_hb_test_fail_4:
  MOVI r6,52
  JMP @mth_hb_test_fail
mth_hb_test_fail_5:
  MOVI r6,53
  JMP @mth_hb_test_fail
mth_hb_test_fail_6:
  MOVI r6,54
  JMP @mth_hb_test_fail
mth_hb_test_fail_7:
  MOVI r6,55
  JMP @mth_hb_test_fail
mth_hb_test_fail_8:
  MOVI r6,56
  JMP @mth_hb_test_fail
mth_hb_test_fail_9:
  MOVI r6,57
  JMP @mth_hb_test_fail
mth_hb_test_fail_10:
  MOVI r6,65
  JMP @mth_hb_test_fail
mth_hb_test_fail_11:
  MOVI r6,66
  JMP @mth_hb_test_fail
mth_hb_test_fail_12:
  MOVI r6,67
  JMP @mth_hb_test_fail
mth_hb_test_fail_13:
  MOVI r6,68
  JMP @mth_hb_test_fail
mth_hb_test_fail_14:
  MOVI r6,69
  JMP @mth_hb_test_fail
mth_hb_test_fail_15:
  MOVI r6,70

mth_hb_test_fail:
  MOVI r1,@mth_hb_test_bad_prefix
  CALL @mth_hb_test_puts
  PUTC r6
  MOVI r1,@mth_hb_test_nl
  CALL @mth_hb_test_puts
  HALT

; ---- helpers ----
; Copy the sixteen initial record words back into the live arena.
mth_hb_test_reset:
  MOVI r1,@mth_hb_records
  MOVI r2,@mth_hb_initial
  MOVI r3,16
  BCOPY r1,r2,r3
  RET

; r1 = word index into the id array, r2 = value.
mth_hb_test_set_id:
  MOVI r3,@mth_hb_ids
  ADD r3,r3,r1
  ST r2,r3,0
  RET

; r1 = word index into the gradient array, r2 = value.
mth_hb_test_set_grad:
  MOVI r3,@mth_hb_grads
  ADD r3,r3,r1
  ST r2,r3,0
  RET

; r7 = entry count, r8 = eta bits, r9 = record count.
; Calls the kernel with the test arena and packed id/gradient arrays.
mth_hb_test_call:
  ST r15,r0,@mth_hb_test_link
  MOVI r1,@mth_hb_records
  SHL r1,r1,2
  ADD r2,r9,r0
  MOVI r3,@mth_hb_ids
  SHL r3,r3,2
  MOVI r4,@mth_hb_grads
  SHL r4,r4,2
  ADD r5,r7,r0
  ADD r6,r8,r0
  CALL @mth_hyperedge_strength_batch
  LD r15,r0,@mth_hb_test_link
  RET

; r1 = zero-based record index, r2 = expected strength bits,
; r3 = expected next word. Returns r1 = 1 iff both match.
mth_hb_test_check_record:
  MOVI r4,@mth_hb_records
  SHL r5,r1,1
  ADD r4,r4,r5
  LD r5,r4,0
  CMP r5,r2
  JMP[NE] @mth_hb_test_check_record_bad
  LD r5,r4,1
  CMP r5,r3
  JMP[NE] @mth_hb_test_check_record_bad
  MOVI r1,1
  RET
mth_hb_test_check_record_bad:
  MOVI r1,0
  RET

; Compare all sixteen live record words with the initial table.
; Returns r1 = 1 iff every strength and next word is unchanged.
mth_hb_test_check_all_initial:
  MOVI r1,@mth_hb_records
  MOVI r2,@mth_hb_initial
  MOVI r3,16
mth_hb_test_check_all_loop:
  LD r4,r1,0
  LD r5,r2,0
  CMP r4,r5
  JMP[NE] @mth_hb_test_check_all_bad
  ADD r1,r1,r13
  ADD r2,r2,r13
  SUB r3,r3,r13
  CMP r3,r0
  JMP[GT] @mth_hb_test_check_all_loop
  MOVI r1,1
  RET
mth_hb_test_check_all_bad:
  MOVI r1,0
  RET

; r1 = NUL-terminated string; writes bytes through PUTC.
mth_hb_test_puts:
  MOVI r4,255
mth_hb_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_hb_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_hb_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_hb_test_puts_word

; ---- data ----
.org 2048
mth_hb_records:
.word 0x3F000000
.word 0x00000011
.word 0x40000000
.word 0x00000022
.word 0x40500000
.word 0x00000033
.word 0x40F00000
.word 0x00000044
.word 0xC0F00000
.word 0x00000055
.word 0xC0000000
.word 0x00000066
.word 0x3F800000
.word 0x00000077
.word 0xBF800000
.word 0x00000088

mth_hb_initial:
.word 0x3F000000
.word 0x00000011
.word 0x40000000
.word 0x00000022
.word 0x40500000
.word 0x00000033
.word 0x40F00000
.word 0x00000044
.word 0xC0F00000
.word 0x00000055
.word 0xC0000000
.word 0x00000066
.word 0x3F800000
.word 0x00000077
.word 0xBF800000
.word 0x00000088

mth_hb_ids:
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
mth_hb_grads:
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
mth_hb_test_link:
.word 0

mth_hb_test_pass:
.str "MTH HYPEREDGE STRENGTH BATCH PASS\n"
mth_hb_test_bad_prefix:
.str "MTH HYPEREDGE STRENGTH BATCH FAIL "
mth_hb_test_nl:
.str "\n"
