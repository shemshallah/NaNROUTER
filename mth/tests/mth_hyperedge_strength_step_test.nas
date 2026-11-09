; MTH hyperedge-strength update fixture — native NaN16 only.
;
; In-guest coverage, no host arithmetic:
;   1. valid updates over three records with eta = 0.25, exact f32 results,
;      and unchanged next links;
;   2. high and low clamp saturation at exactly +8.0 and -8.0;
;   3. atomic rejection of id 0 and of id r2+1, with every record byte unchanged;
;   4. atomic rejection of a NaN gradient and of a +Inf gradient;
;   5. duplicate ids applied in array order, so the later duplicate sees the
;      earlier clamped result;
;   6. untouched records and untouched next fields after a single-record update;
;   7. a referenced record with a NaN stored strength rejects atomically;
;   8. eta behaviour: +0.0 is a value no-op, negative eta steps in the
;      +gradient direction, and NaN/+Inf eta reject atomically;
;   9. every success returns r1=1, r9=0; every rejection returns r1=0 with
;      the documented r9 cause and no strength/next mutation.
;
; The record arena is laid out as packed eight-byte records in the NaN16
; payload byte space: strength word, next word, stride two words. The test
; uses LD/ST for direct word inspection and passes label<<2 as the byte
; address of each arena.
;
; All checks and all arithmetic are native NaN16 instructions. No host math,
; no external oracle, and no shared test table are used.

.org 0
JMP @mth_hs_test_main
.include "../nan16/mth_hyperedge_strength_step.nas"

mth_hs_test_main:
  MOVI r13,1

  ; ================= Case 1: valid updates =================
  CALL @mth_hs_test_reset
  MOVI r1,@mth_hs_ids
  MOVI r2,1
  ST r2,r1,0
  MOVI r2,2
  ST r2,r1,1
  MOVI r2,3
  ST r2,r1,2
  MOVI r1,@mth_hs_grads
  MOVI r2,0
  MOVHI r2,0x3F80            ; +1.0
  ST r2,r1,0
  MOVI r2,0
  MOVHI r2,0xBF80            ; -1.0
  ST r2,r1,1
  MOVI r2,0
  MOVHI r2,0x3F00            ; +0.5
  ST r2,r1,2
  MOVI r7,3
  MOVI r8,0
  MOVHI r8,0x3E80            ; eta = +0.25
  MOVI r9,6
  CALL @mth_hs_test_call
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_1
  CMP r9,r0
  JMP[NE] @mth_hs_test_fail_1

  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x3F40            ; 0.75
  MOVI r3,0x11
  CALL @mth_hs_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_1

  MOVI r1,1
  MOVI r2,0
  MOVHI r2,0x4010            ; 2.25
  MOVI r3,0x22
  CALL @mth_hs_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_1

  MOVI r1,2
  MOVI r2,0
  MOVHI r2,0xBF90            ; -1.125
  MOVI r3,0x33
  CALL @mth_hs_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_1

  MOVI r1,3
  MOVI r2,0
  MOVHI r2,0x40F0            ; 7.5 untouched
  MOVI r3,0x44
  CALL @mth_hs_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_1

  MOVI r1,4
  MOVI r2,0
  MOVHI r2,0xC0F0            ; -7.5 untouched
  MOVI r3,0x55
  CALL @mth_hs_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_1

  MOVI r1,5
  MOVI r2,0
  MOVHI r2,0x4050            ; 3.25 untouched
  MOVI r3,0x66
  CALL @mth_hs_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_1

  ; ================= Case 2: clamp high and low =================
  CALL @mth_hs_test_reset
  MOVI r1,@mth_hs_ids
  MOVI r2,4
  ST r2,r1,0
  MOVI r2,5
  ST r2,r1,1
  MOVI r1,@mth_hs_grads
  MOVI r2,0
  MOVHI r2,0xC000            ; -2.0
  ST r2,r1,0
  MOVI r2,0
  MOVHI r2,0x4000            ; +2.0
  ST r2,r1,1
  MOVI r7,2
  MOVI r8,0
  MOVHI r8,0x3F80            ; eta = +1.0
  MOVI r9,6
  CALL @mth_hs_test_call
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_2
  CMP r9,r0
  JMP[NE] @mth_hs_test_fail_2

  MOVI r1,3
  MOVI r2,0
  MOVHI r2,0x4100            ; +8.0 saturated
  MOVI r3,0x44
  CALL @mth_hs_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_2

  MOVI r1,4
  MOVI r2,0
  MOVHI r2,0xC100            ; -8.0 saturated
  MOVI r3,0x55
  CALL @mth_hs_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_2

  MOVI r1,5
  MOVI r2,0
  MOVHI r2,0x4050            ; still untouched
  MOVI r3,0x66
  CALL @mth_hs_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_2

  ; ================= Case 3: id 0 rejects atomically =================
  CALL @mth_hs_test_reset
  MOVI r1,@mth_hs_ids
  MOVI r2,2
  ST r2,r1,0
  MOVI r2,0
  ST r2,r1,1
  MOVI r2,4
  ST r2,r1,2
  MOVI r1,@mth_hs_grads
  MOVI r2,0
  MOVHI r2,0x3F80
  ST r2,r1,0
  ST r2,r1,1
  ST r2,r1,2
  MOVI r7,3
  MOVI r8,0
  MOVHI r8,0x3F00            ; eta = +0.5
  MOVI r9,6
  CALL @mth_hs_test_call
  CMP r1,r0
  JMP[NE] @mth_hs_test_fail_3
  MOVI r10,1
  CMP r9,r10
  JMP[NE] @mth_hs_test_fail_3
  CALL @mth_hs_test_check_all_initial
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_3

  ; ================= Case 4: id r2+1 rejects atomically =================
  CALL @mth_hs_test_reset
  MOVI r1,@mth_hs_ids
  MOVI r2,1
  ST r2,r1,0
  MOVI r2,7
  ST r2,r1,1
  MOVI r2,3
  ST r2,r1,2
  MOVI r1,@mth_hs_grads
  MOVI r2,0
  MOVHI r2,0x3F80
  ST r2,r1,0
  ST r2,r1,1
  ST r2,r1,2
  MOVI r7,3
  MOVI r8,0
  MOVHI r8,0x3F00
  MOVI r9,6
  CALL @mth_hs_test_call
  CMP r1,r0
  JMP[NE] @mth_hs_test_fail_4
  MOVI r10,1
  CMP r9,r10
  JMP[NE] @mth_hs_test_fail_4
  CALL @mth_hs_test_check_all_initial
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_4

  ; ================= Case 5: NaN gradient rejects atomically =================
  CALL @mth_hs_test_reset
  MOVI r1,@mth_hs_ids
  MOVI r2,1
  ST r2,r1,0
  MOVI r2,2
  ST r2,r1,1
  MOVI r2,3
  ST r2,r1,2
  MOVI r1,@mth_hs_grads
  MOVI r2,0
  MOVHI r2,0x3F80
  ST r2,r1,0
  MOVI r2,0
  MOVHI r2,0x7FC0            ; canonical quiet NaN
  ST r2,r1,1
  MOVI r2,0
  MOVHI r2,0x3F80
  ST r2,r1,2
  MOVI r7,3
  MOVI r8,0
  MOVHI r8,0x3F00
  MOVI r9,6
  CALL @mth_hs_test_call
  CMP r1,r0
  JMP[NE] @mth_hs_test_fail_5
  MOVI r10,2
  CMP r9,r10
  JMP[NE] @mth_hs_test_fail_5
  CALL @mth_hs_test_check_all_initial
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_5

  ; ================= Case 6: +Inf gradient rejects atomically =================
  CALL @mth_hs_test_reset
  MOVI r1,@mth_hs_ids
  MOVI r2,1
  ST r2,r1,0
  MOVI r2,2
  ST r2,r1,1
  MOVI r2,3
  ST r2,r1,2
  MOVI r1,@mth_hs_grads
  MOVI r2,0
  MOVHI r2,0x3F80
  ST r2,r1,0
  MOVI r2,0
  MOVHI r2,0x7F80            ; +Inf
  ST r2,r1,1
  MOVI r2,0
  MOVHI r2,0x3F80
  ST r2,r1,2
  MOVI r7,3
  MOVI r8,0
  MOVHI r8,0x3F00
  MOVI r9,6
  CALL @mth_hs_test_call
  CMP r1,r0
  JMP[NE] @mth_hs_test_fail_6
  MOVI r10,2
  CMP r9,r10
  JMP[NE] @mth_hs_test_fail_6
  CALL @mth_hs_test_check_all_initial
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_6

  ; ================= Case 7: duplicate ids are sequential =================
  CALL @mth_hs_test_reset
  MOVI r1,@mth_hs_ids
  MOVI r2,1
  ST r2,r1,0
  ST r2,r1,1
  ST r2,r1,2
  MOVI r1,@mth_hs_grads
  MOVI r2,0
  MOVHI r2,0x3F80
  ST r2,r1,0
  ST r2,r1,1
  ST r2,r1,2
  MOVI r7,3
  MOVI r8,0
  MOVHI r8,0x3E80            ; eta = +0.25
  MOVI r9,6
  CALL @mth_hs_test_call
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_7
  CMP r9,r0
  JMP[NE] @mth_hs_test_fail_7

  ; 1.0 -> 0.75 -> 0.50 -> 0.25
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x3E80            ; 0.25
  MOVI r3,0x11
  CALL @mth_hs_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_7

  ; The other records remain at their initial values.
  MOVI r1,1
  MOVI r2,0
  MOVHI r2,0x4000            ; 2.0
  MOVI r3,0x22
  CALL @mth_hs_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_7

  ; ================= Case 8: untouched records and non-finite old strength ===
  CALL @mth_hs_test_reset
  MOVI r1,@mth_hs_ids
  MOVI r2,2
  ST r2,r1,0
  MOVI r1,@mth_hs_grads
  MOVI r2,0
  MOVHI r2,0x3F80
  ST r2,r1,0
  MOVI r7,1
  MOVI r8,0
  MOVHI r8,0x3F00            ; eta = +0.5
  MOVI r9,6
  CALL @mth_hs_test_call
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_8
  CMP r9,r0
  JMP[NE] @mth_hs_test_fail_8

  ; id 2 becomes 2.0 - 0.5*1.0 = 1.5.
  MOVI r1,1
  MOVI r2,0
  MOVHI r2,0x3FC0            ; 1.5
  MOVI r3,0x22
  CALL @mth_hs_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_8

  ; Every other record, including every next field, is untouched.
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x3F80
  MOVI r3,0x11
  CALL @mth_hs_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_8
  MOVI r1,2
  MOVI r2,0
  MOVHI r2,0xBF80
  MOVI r3,0x33
  CALL @mth_hs_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_8
  MOVI r1,3
  MOVI r2,0
  MOVHI r2,0x40F0
  MOVI r3,0x44
  CALL @mth_hs_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_8
  MOVI r1,4
  MOVI r2,0
  MOVHI r2,0xC0F0
  MOVI r3,0x55
  CALL @mth_hs_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_8
  MOVI r1,5
  MOVI r2,0
  MOVHI r2,0x4050
  MOVI r3,0x66
  CALL @mth_hs_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_8

  ; Referenced record 3 gets a NaN stored strength. The call must reject
  ; with cause 4 before any write, leaving the NaN and every other record.
  CALL @mth_hs_test_reset
  MOVI r1,@mth_hs_records
  ADDI r1,r1,4
  MOVI r2,0
  MOVHI r2,0x7FC0
  ST r2,r1,0
  MOVI r1,@mth_hs_ids
  MOVI r2,3
  ST r2,r1,0
  MOVI r1,@mth_hs_grads
  MOVI r2,0
  MOVHI r2,0x3F80
  ST r2,r1,0
  MOVI r7,1
  MOVI r8,0
  MOVHI r8,0x3F00
  MOVI r9,6
  CALL @mth_hs_test_call
  CMP r1,r0
  JMP[NE] @mth_hs_test_fail_8
  MOVI r10,4
  CMP r9,r10
  JMP[NE] @mth_hs_test_fail_8

  MOVI r1,2
  MOVI r2,0
  MOVHI r2,0x7FC0            ; NaN strength still present
  MOVI r3,0x33
  CALL @mth_hs_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_8
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x3F80
  MOVI r3,0x11
  CALL @mth_hs_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_8
  MOVI r1,1
  MOVI r2,0
  MOVHI r2,0x4000
  MOVI r3,0x22
  CALL @mth_hs_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_8

  ; ================= Case 9: eta semantics =================
  ; 9a: eta = +0.0 is a value no-op, but the call still validates and commits.
  CALL @mth_hs_test_reset
  MOVI r1,@mth_hs_ids
  MOVI r2,1
  ST r2,r1,0
  MOVI r1,@mth_hs_grads
  MOVI r2,0
  MOVHI r2,0x4000            ; +2.0
  ST r2,r1,0
  MOVI r7,1
  MOVI r8,0                  ; eta = +0.0
  MOVI r9,6
  CALL @mth_hs_test_call
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_9
  CMP r9,r0
  JMP[NE] @mth_hs_test_fail_9
  CALL @mth_hs_test_check_all_initial
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_9

  ; 9b: negative eta steps in the +gradient direction: 1.0 -(-0.5*1.0)=1.5.
  CALL @mth_hs_test_reset
  MOVI r1,@mth_hs_ids
  MOVI r2,1
  ST r2,r1,0
  MOVI r1,@mth_hs_grads
  MOVI r2,0
  MOVHI r2,0x3F80            ; +1.0
  ST r2,r1,0
  MOVI r7,1
  MOVI r8,0
  MOVHI r8,0xBF00            ; eta = -0.5
  MOVI r9,6
  CALL @mth_hs_test_call
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_9
  CMP r9,r0
  JMP[NE] @mth_hs_test_fail_9
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x3FC0            ; 1.5
  MOVI r3,0x11
  CALL @mth_hs_test_check_record
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_9

  ; 9c: NaN eta rejects with cause 3 and no mutation.
  CALL @mth_hs_test_reset
  MOVI r1,@mth_hs_ids
  MOVI r2,1
  ST r2,r1,0
  MOVI r1,@mth_hs_grads
  MOVI r2,0
  MOVHI r2,0x3F80
  ST r2,r1,0
  MOVI r7,1
  MOVI r8,0
  MOVHI r8,0x7FC0
  MOVI r9,6
  CALL @mth_hs_test_call
  CMP r1,r0
  JMP[NE] @mth_hs_test_fail_9
  MOVI r10,3
  CMP r9,r10
  JMP[NE] @mth_hs_test_fail_9
  CALL @mth_hs_test_check_all_initial
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_9

  ; 9d: +Inf eta rejects with cause 3 and no mutation.
  CALL @mth_hs_test_reset
  MOVI r1,@mth_hs_ids
  MOVI r2,1
  ST r2,r1,0
  MOVI r1,@mth_hs_grads
  MOVI r2,0
  MOVHI r2,0x3F80
  ST r2,r1,0
  MOVI r7,1
  MOVI r8,0
  MOVHI r8,0x7F80
  MOVI r9,6
  CALL @mth_hs_test_call
  CMP r1,r0
  JMP[NE] @mth_hs_test_fail_9
  MOVI r10,3
  CMP r9,r10
  JMP[NE] @mth_hs_test_fail_9
  CALL @mth_hs_test_check_all_initial
  CMP r1,r13
  JMP[NE] @mth_hs_test_fail_9

  MOVI r1,@mth_hs_test_pass
  CALL @mth_hs_test_puts
  HALT

; ---- failure reporting ----
mth_hs_test_fail_1:
  MOVI r6,1
  JMP @mth_hs_test_fail
mth_hs_test_fail_2:
  MOVI r6,2
  JMP @mth_hs_test_fail
mth_hs_test_fail_3:
  MOVI r6,3
  JMP @mth_hs_test_fail
mth_hs_test_fail_4:
  MOVI r6,4
  JMP @mth_hs_test_fail
mth_hs_test_fail_5:
  MOVI r6,5
  JMP @mth_hs_test_fail
mth_hs_test_fail_6:
  MOVI r6,6
  JMP @mth_hs_test_fail
mth_hs_test_fail_7:
  MOVI r6,7
  JMP @mth_hs_test_fail
mth_hs_test_fail_8:
  MOVI r6,8
  JMP @mth_hs_test_fail
mth_hs_test_fail_9:
  MOVI r6,9

mth_hs_test_fail:
  MOVI r1,@mth_hs_test_bad_prefix
  CALL @mth_hs_test_puts
  MOVI r1,48
  ADD r1,r1,r6
  PUTC r1
  MOVI r1,@mth_hs_test_nl
  CALL @mth_hs_test_puts
  HALT

; ---- helpers ----
; Copy the twelve initial record words back into the live arena.
mth_hs_test_reset:
  MOVI r1,@mth_hs_records
  MOVI r2,@mth_hs_initial
  MOVI r3,12
  BCOPY r1,r2,r3
  RET

; r7 = entry count, r8 = eta bits, r9 = record count.
; Calls the kernel with the test arena and packed id/gradient arrays.
mth_hs_test_call:
  ST r15,r0,@mth_hs_test_link
  MOVI r1,@mth_hs_records
  SHL r1,r1,2
  ADD r2,r9,r0
  MOVI r3,@mth_hs_ids
  SHL r3,r3,2
  MOVI r4,@mth_hs_grads
  SHL r4,r4,2
  ADD r5,r7,r0
  ADD r6,r8,r0
  CALL @mth_hyperedge_strength_step
  LD r15,r0,@mth_hs_test_link
  RET

; r1 = zero-based record index, r2 = expected strength bits,
; r3 = expected next word. Returns r1 = 1 iff both match.
mth_hs_test_check_record:
  MOVI r4,@mth_hs_records
  SHL r5,r1,1
  ADD r4,r4,r5
  LD r5,r4,0
  CMP r5,r2
  JMP[NE] @mth_hs_test_check_record_bad
  LD r5,r4,1
  CMP r5,r3
  JMP[NE] @mth_hs_test_check_record_bad
  MOVI r1,1
  RET
mth_hs_test_check_record_bad:
  MOVI r1,0
  RET

; Compare all twelve live record words with the initial table.
; Returns r1 = 1 iff every strength and next word is unchanged.
mth_hs_test_check_all_initial:
  MOVI r1,@mth_hs_records
  MOVI r2,@mth_hs_initial
  MOVI r3,12
mth_hs_test_check_all_loop:
  LD r4,r1,0
  LD r5,r2,0
  CMP r4,r5
  JMP[NE] @mth_hs_test_check_all_bad
  ADD r1,r1,r13
  ADD r2,r2,r13
  SUB r3,r3,r13
  CMP r3,r0
  JMP[GT] @mth_hs_test_check_all_loop
  MOVI r1,1
  RET
mth_hs_test_check_all_bad:
  MOVI r1,0
  RET

; r1 = NUL-terminated string; writes bytes through PUTC.
mth_hs_test_puts:
  MOVI r4,255
mth_hs_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_hs_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_hs_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_hs_test_puts_word

; ---- data ----
.org 2048
mth_hs_records:
.word 0x3F800000
.word 0x00000011
.word 0x40000000
.word 0x00000022
.word 0xBF800000
.word 0x00000033
.word 0x40F00000
.word 0x00000044
.word 0xC0F00000
.word 0x00000055
.word 0x40500000
.word 0x00000066

mth_hs_initial:
.word 0x3F800000
.word 0x00000011
.word 0x40000000
.word 0x00000022
.word 0xBF800000
.word 0x00000033
.word 0x40F00000
.word 0x00000044
.word 0xC0F00000
.word 0x00000055
.word 0x40500000
.word 0x00000066

mth_hs_ids:
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
mth_hs_grads:
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
mth_hs_test_link:
.word 0

mth_hs_test_pass:
.str "MTH HYPEREDGE STRENGTH STEP PASS\n"
mth_hs_test_bad_prefix:
.str "MTH HYPEREDGE STRENGTH STEP FAIL "
mth_hs_test_nl:
.str "\n"
