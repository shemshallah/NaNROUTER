.org 0
JMP @mth_mirror_bounds_test_main
.include "../nan16/mth_mirror_bounds_check.nas"

; Fixture for the canonical 8,388,608-byte mirror-memory address validator.
;
; Coverage:
;   1. head boundaries h=0, h=1, h=255 with exact [start,end) extents;
;   2. pair boundaries id=1, 2, 32,639, 32,640 with exact record extents,
;      including the last record ending exactly at 8,388,608;
;   3. lane boundaries lane=0/1 on the first and last pair records, with
;      128-byte extents that meet without overlap;
;   4. field boundaries field=0 and field=127 on both lanes, including the
;      last field byte at 8,388,607 ending at 8,388,608;
;   5. all rejection classes: unknown kind, head 256, pair id 0 and 32,641,
;      lane 2, field 128, unsigned 0xFFFFFFFF/0x80000000 values, and values
;      that would wrap the shifted record address;
;   6. every rejection must clear r1, r3, and r4.
;
; The kernel computes addresses only; this fixture does not materialize the
; 8 MiB region.
;
; Register plan (kernel clobbers only r0-r6):
;   r7  = unused spare
;   r8  = unused spare
;   r9  = unused spare
;   r10 = saved CALL/RET link across the nested kernel call
;   r11 = expected start byte
;   r12 = expected end byte (exclusive)
;   r13 = 1
;   r14 = unused spare
;   r15 = CALL/RET link

mth_mirror_bounds_test_main:
  MOVI r13,1
  MOVI r0,0

  ; ================= head boundaries =================
  ; kind=0, a=0 -> [0, 128)
  MOVI r1,0
  MOVI r2,0
  MOVI r3,0
  MOVI r4,0
  MOVI r11,0
  MOVI r12,128
  CALL @mth_mirror_bounds_test_expect

  ; kind=0, a=1 -> [128, 256)
  MOVI r1,0
  MOVI r2,1
  MOVI r11,128
  MOVI r12,256
  CALL @mth_mirror_bounds_test_expect

  ; kind=0, a=255 -> [32,640, 32,768)
  MOVI r1,0
  MOVI r2,255
  MOVI r11,32640
  MOVI r12,32768
  CALL @mth_mirror_bounds_test_expect

  ; ================= pair boundaries =================
  ; kind=1, a=1 -> [32,768, 33,024)
  MOVI r1,1
  MOVI r2,1
  MOVI r3,0
  MOVI r4,0
  MOVI r11,32768
  MOVI r12,33024
  CALL @mth_mirror_bounds_test_expect

  ; kind=1, a=2 -> [33,024, 33,280)
  MOVI r1,1
  MOVI r2,2
  MOVI r11,33024
  MOVI r12,33280
  CALL @mth_mirror_bounds_test_expect

  ; kind=1, a=32,639 -> [8,388,096, 8,388,352)
  MOVI r1,1
  MOVI r2,32639
  MOVI r11,0xFE00
  MOVHI r11,0x7F
  MOVI r12,0xFF00
  MOVHI r12,0x7F
  CALL @mth_mirror_bounds_test_expect

  ; kind=1, a=32,640 -> [8,388,352, 8,388,608)
  MOVI r1,1
  MOVI r2,32640
  MOVI r11,0xFF00
  MOVHI r11,0x7F
  MOVI r12,0
  MOVHI r12,0x80
  CALL @mth_mirror_bounds_test_expect

  ; ================= lane boundaries =================
  ; kind=2, a=1, b=0 -> [32,768, 32,896)
  MOVI r1,2
  MOVI r2,1
  MOVI r3,0
  MOVI r4,0
  MOVI r11,32768
  MOVI r12,32896
  CALL @mth_mirror_bounds_test_expect

  ; kind=2, a=1, b=1 -> [32,896, 33,024)
  MOVI r1,2
  MOVI r2,1
  MOVI r3,1
  MOVI r11,32896
  MOVI r12,33024
  CALL @mth_mirror_bounds_test_expect

  ; kind=2, a=32,640, b=0 -> [8,388,352, 8,388,480)
  MOVI r1,2
  MOVI r2,32640
  MOVI r3,0
  MOVI r11,0xFF00
  MOVHI r11,0x7F
  MOVI r12,0xFF80
  MOVHI r12,0x7F
  CALL @mth_mirror_bounds_test_expect

  ; kind=2, a=32,640, b=1 -> [8,388,480, 8,388,608)
  MOVI r1,2
  MOVI r2,32640
  MOVI r3,1
  MOVI r11,0xFF80
  MOVHI r11,0x7F
  MOVI r12,0
  MOVHI r12,0x80
  CALL @mth_mirror_bounds_test_expect

  ; ================= field boundaries =================
  ; kind=3, a=1, b=0, c=0 -> [32,768, 32,769)
  MOVI r1,3
  MOVI r2,1
  MOVI r3,0
  MOVI r4,0
  MOVI r11,32768
  MOVI r12,32769
  CALL @mth_mirror_bounds_test_expect

  ; kind=3, a=1, b=1, c=127 -> [33,023, 33,024)
  MOVI r1,3
  MOVI r2,1
  MOVI r3,1
  MOVI r4,127
  MOVI r11,33023
  MOVI r12,33024
  CALL @mth_mirror_bounds_test_expect

  ; kind=3, a=32,640, b=0, c=127 -> [8,388,479, 8,388,480)
  MOVI r1,3
  MOVI r2,32640
  MOVI r3,0
  MOVI r4,127
  MOVI r11,0xFF7F
  MOVHI r11,0x7F
  MOVI r12,0xFF80
  MOVHI r12,0x7F
  CALL @mth_mirror_bounds_test_expect

  ; kind=3, a=32,640, b=1, c=0 -> [8,388,480, 8,388,481)
  MOVI r1,3
  MOVI r2,32640
  MOVI r3,1
  MOVI r4,0
  MOVI r11,0xFF80
  MOVHI r11,0x7F
  MOVI r12,0xFF81
  MOVHI r12,0x7F
  CALL @mth_mirror_bounds_test_expect

  ; kind=3, a=32,640, b=1, c=127 -> [8,388,607, 8,388,608)
  MOVI r1,3
  MOVI r2,32640
  MOVI r3,1
  MOVI r4,127
  MOVI r11,0xFFFF
  MOVHI r11,0x7F
  MOVI r12,0
  MOVHI r12,0x80
  CALL @mth_mirror_bounds_test_expect

  ; ================= invalid kind =================
  ; kind=4 (just above the valid dispatch range)
  MOVI r1,4
  MOVI r2,0
  MOVI r3,0
  MOVI r4,0
  CALL @mth_mirror_bounds_test_reject

  ; kind=0xFFFFFFFF
  MOVI r1,0xFFFF
  MOVHI r1,0xFFFF
  MOVI r2,0
  MOVI r3,0
  MOVI r4,0
  CALL @mth_mirror_bounds_test_reject

  ; kind=0x80000000
  MOVI r1,0
  MOVHI r1,0x8000
  MOVI r2,0
  MOVI r3,0
  MOVI r4,0
  CALL @mth_mirror_bounds_test_reject

  ; ================= invalid head =================
  ; head 256
  MOVI r1,0
  MOVI r2,256
  MOVI r3,0
  MOVI r4,0
  CALL @mth_mirror_bounds_test_reject

  ; head 0xFFFFFFFF
  MOVI r1,0
  MOVI r2,0xFFFF
  MOVHI r2,0xFFFF
  CALL @mth_mirror_bounds_test_reject

  ; head 0x80000000 (128*head would wrap to 0)
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,0x8000
  CALL @mth_mirror_bounds_test_reject

  ; ================= invalid pair id =================
  ; pair id 0 (void sentinel)
  MOVI r1,1
  MOVI r2,0
  MOVI r3,0
  MOVI r4,0
  CALL @mth_mirror_bounds_test_reject

  ; pair id 32,641
  MOVI r1,1
  MOVI r2,32641
  CALL @mth_mirror_bounds_test_reject

  ; pair id 0xFFFFFFFF
  MOVI r1,1
  MOVI r2,0xFFFF
  MOVHI r2,0xFFFF
  CALL @mth_mirror_bounds_test_reject

  ; pair id 0x01000000: (id-1)*256 would wrap the 32-bit address
  MOVI r1,1
  MOVI r2,0
  MOVHI r2,0x0100
  CALL @mth_mirror_bounds_test_reject

  ; ================= invalid lane =================
  ; lane 2
  MOVI r1,2
  MOVI r2,1
  MOVI r3,2
  MOVI r4,0
  CALL @mth_mirror_bounds_test_reject

  ; lane 0xFFFFFFFF
  MOVI r1,2
  MOVI r2,1
  MOVI r3,0xFFFF
  MOVHI r3,0xFFFF
  CALL @mth_mirror_bounds_test_reject

  ; lane 0x80000000 (lane*128 would wrap to 0)
  MOVI r1,2
  MOVI r2,1
  MOVI r3,0
  MOVHI r3,0x8000
  CALL @mth_mirror_bounds_test_reject

  ; lane with pair id 0
  MOVI r1,2
  MOVI r2,0
  MOVI r3,0
  CALL @mth_mirror_bounds_test_reject

  ; lane with pair id 32,641
  MOVI r1,2
  MOVI r2,32641
  MOVI r3,1
  CALL @mth_mirror_bounds_test_reject

  ; ================= invalid field =================
  ; field 128
  MOVI r1,3
  MOVI r2,1
  MOVI r3,0
  MOVI r4,128
  CALL @mth_mirror_bounds_test_reject

  ; field 0xFFFFFFFF
  MOVI r1,3
  MOVI r2,1
  MOVI r3,0
  MOVI r4,0xFFFF
  MOVHI r4,0xFFFF
  CALL @mth_mirror_bounds_test_reject

  ; field 0x80000000
  MOVI r1,3
  MOVI r2,1
  MOVI r3,0
  MOVI r4,0
  MOVHI r4,0x8000
  CALL @mth_mirror_bounds_test_reject

  ; field with lane 2
  MOVI r1,3
  MOVI r2,1
  MOVI r3,2
  MOVI r4,0
  CALL @mth_mirror_bounds_test_reject

  ; field with pair id 0
  MOVI r1,3
  MOVI r2,0
  MOVI r3,0
  MOVI r4,0
  CALL @mth_mirror_bounds_test_reject

  ; field with pair id 32,641
  MOVI r1,3
  MOVI r2,32641
  MOVI r3,1
  MOVI r4,0
  CALL @mth_mirror_bounds_test_reject

  MOVI r1,@mth_mirror_bounds_test_pass
  CALL @mth_mirror_bounds_test_puts
  HALT

; r1=kind, r2=a, r3=b, r4=c; r11=expected start, r12=expected end.
; Verifies success, start, and end.
mth_mirror_bounds_test_expect:
  ADD r10,r15,r0                        ; save caller link across nested CALL
  CALL @mth_mirror_bounds_check
  ADD r15,r10,r0                        ; restore caller link
  CMP r1,r13
  JMP[NE] @mth_mirror_bounds_test_fail
  CMP r3,r11
  JMP[NE] @mth_mirror_bounds_test_fail
  CMP r4,r12
  JMP[NE] @mth_mirror_bounds_test_fail
  RET

; r1=kind, r2=a, r3=b, r4=c already set. Requires r1=0 and r3=r4=0
; after rejection.
mth_mirror_bounds_test_reject:
  ADD r10,r15,r0                        ; save caller link across nested CALL
  CALL @mth_mirror_bounds_check
  ADD r15,r10,r0                        ; restore caller link
  CMP r1,r0
  JMP[NE] @mth_mirror_bounds_test_fail
  CMP r3,r0
  JMP[NE] @mth_mirror_bounds_test_fail
  CMP r4,r0
  JMP[NE] @mth_mirror_bounds_test_fail
  RET

mth_mirror_bounds_test_fail:
  MOVI r1,@mth_mirror_bounds_test_bad
  CALL @mth_mirror_bounds_test_puts
  HALT

mth_mirror_bounds_test_puts:
  MOVI r4,255
mth_mirror_bounds_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_mirror_bounds_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_mirror_bounds_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_mirror_bounds_test_puts_word

.org 1024
mth_mirror_bounds_test_pass:
.str "MTH MIRROR BOUNDS CHECK PASS\n"
mth_mirror_bounds_test_bad:
.str "MTH MIRROR BOUNDS CHECK FAIL\n"
