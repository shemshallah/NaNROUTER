; MTH angular ring address fixture — NaN16 only.
;
; Verifies:
;   * the real ring is exactly 0..254;
;   * NANNET0 is the invariant ring position 255 and is never returned by a
;     rotation;
;   * offsets are modulo 255, including negative and multi-turn offsets;
;   * exhaustive lane x offset coverage over -255..255;
;   * lanes 255, 256 and 0xFFFFFFFF reject atomically;
;   * positive and negative wrap boundaries.

.org 0
JMP @mth_ring_angular_test_main
.include "../nan16/mth_ring_angular_map.nas"

mth_ring_angular_test_main:
  MOVI r0,0
  MOVI r13,1

  ; Known mappings.
  MOVI r1,7
  MOVI r2,0
  ADD r3,r1,r0
  CALL @mth_ring_angular_expect
  MOVI r1,7
  MOVI r2,255
  ADD r3,r1,r0
  CALL @mth_ring_angular_expect
  MOVI r1,7
  MOVI r2,0xFF01
  MOVHI r2,0xFFFF            ; -255
  ADD r3,r1,r0
  CALL @mth_ring_angular_expect
  MOVI r1,7
  MOVI r2,510
  ADD r3,r1,r0
  CALL @mth_ring_angular_expect
  MOVI r1,7
  MOVI r2,0xFE02
  MOVHI r2,0xFFFF            ; -510
  ADD r3,r1,r0
  CALL @mth_ring_angular_expect
  MOVI r1,254
  MOVI r2,1
  MOVI r3,0
  CALL @mth_ring_angular_expect
  MOVI r1,0
  MOVI r2,0xFFFF
  MOVHI r2,0xFFFF            ; -1
  MOVI r3,254
  CALL @mth_ring_angular_expect
  MOVI r1,17
  MOVI r2,0xFFEF
  MOVHI r2,0xFFFF            ; -17
  MOVI r3,0
  CALL @mth_ring_angular_expect
  MOVI r1,17
  MOVI r2,238
  MOVI r3,0
  CALL @mth_ring_angular_expect

  ; Exhaustive real lanes 0..254, offsets -255..255.
  MOVI r6,0
mth_ring_angular_lane_loop:
  MOVI r7,0xFF01
  MOVHI r7,0xFFFF            ; -255
mth_ring_angular_offset_loop:
  ADD r1,r6,r0
  ADD r2,r7,r0
  CALL @mth_ring_angular_map_u32
  CMP r1,r13
  JMP[NE] @mth_ring_angular_fail
  CMP r9,r0
  JMP[NE] @mth_ring_angular_fail
  MOVI r8,254
  CMP r8,r3
  JMP[LT] @mth_ring_angular_fail
  MOVI r8,255
  CMP r4,r8
  JMP[NE] @mth_ring_angular_fail
  CMP r5,r13
  JMP[NE] @mth_ring_angular_fail

  ADDI r7,r7,1
  MOVI r8,255
  CMPS r7,r8
  JMP[LE] @mth_ring_angular_offset_loop

  ADDI r6,r6,1
  MOVI r8,255
  CMP r6,r8
  JMP[LT] @mth_ring_angular_lane_loop

  ; Reject 255, 256, and 0xFFFFFFFF.
  MOVI r1,255
  MOVI r2,0
  CALL @mth_ring_angular_reject
  MOVI r1,256
  MOVI r2,0
  CALL @mth_ring_angular_reject
  MOVI r1,0xFFFF
  MOVHI r1,0xFFFF
  MOVI r2,1
  CALL @mth_ring_angular_reject

  ; Recovery after rejections.
  MOVI r1,7
  MOVI r2,255
  ADD r3,r1,r0
  CALL @mth_ring_angular_expect

  MOVI r1,@mth_ring_angular_pass
  CALL @mth_ring_angular_puts
  HALT

; r1=lane, r2=offset, r3=expected mapped lane.
mth_ring_angular_expect:
  ST r15,r0,@mth_ring_angular_ret
  MOVI r8,@mth_ring_angular_saved_lane
  ST r3,r8,0
  CALL @mth_ring_angular_map_u32
  CMP r1,r13
  JMP[NE] @mth_ring_angular_fail
  CMP r9,r0
  JMP[NE] @mth_ring_angular_fail
  LD r8,r0,@mth_ring_angular_saved_lane
  CMP r3,r8
  JMP[NE] @mth_ring_angular_fail
  MOVI r8,255
  CMP r4,r8
  JMP[NE] @mth_ring_angular_fail
  CMP r5,r13
  JMP[NE] @mth_ring_angular_fail
  LD r15,r0,@mth_ring_angular_ret
  RET

; r1=lane, r2=offset; requires rejection and no real-lane output.
mth_ring_angular_reject:
  ST r15,r0,@mth_ring_angular_ret
  CALL @mth_ring_angular_map_u32
  CMP r1,r0
  JMP[NE] @mth_ring_angular_fail
  MOVI r8,1
  CMP r9,r8
  JMP[NE] @mth_ring_angular_fail
  CMP r3,r0
  JMP[NE] @mth_ring_angular_fail
  MOVI r8,255
  CMP r4,r8
  JMP[NE] @mth_ring_angular_fail
  CMP r5,r13
  JMP[NE] @mth_ring_angular_fail
  LD r15,r0,@mth_ring_angular_ret
  RET

mth_ring_angular_fail:
  MOVI r1,@mth_ring_angular_bad
  CALL @mth_ring_angular_puts
  HALT

mth_ring_angular_puts:
  MOVI r4,255
mth_ring_angular_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_ring_angular_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_ring_angular_puts_byte
  ADD r1,r1,r13
  JMP @mth_ring_angular_puts_word

mth_ring_angular_pass:
.str "MTH RING ANGULAR MAP PASS\n"
mth_ring_angular_bad:
.str "MTH RING ANGULAR MAP FAIL\n"

.org 4096
mth_ring_angular_ret:
.word 0
mth_ring_angular_saved_lane:
.word 0
