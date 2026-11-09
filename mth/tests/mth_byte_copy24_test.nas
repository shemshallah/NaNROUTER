; MTH exact 24-byte episodic-copy fixture — NaN16 only.
;
; Exercises mth_byte_copy24 over the canonical 8 MiB payload byte space:
;
;   r1 = source byte address, r2 = destination byte address,
;   r3 = length 1..24, r13 = 1.
;
; Coverage:
;   1-byte, 4-byte, and 24-byte copies with the source at byte 0 and with
;   the destination at byte 0;
;   the same three lengths with the source at 8388608-N and with the
;   destination at 8388608-N, ending exactly at the canonical root end;
;   exact source == destination aliases at 0, in the scratch arena, and at
;   the root end (no-op success with r4 = length);
;   strict partial-overlap rejection for source < destination and
;   destination < source, including a one-byte overlap at each boundary;
;   the adjacent, non-overlapping boundary (destination == source + length
;   and source == destination + length) must succeed;
;   destination poisoning: a rejected partial overlap leaves every poisoned
;   destination byte unchanged;
;   length 0 and length > 24 rejection, including length 0 with an exact
;   alias;
;   source/destination at or beyond 8388608, last-byte-plus-one crosses,
;   and genuine 32-bit address+length wraps;
;   validation priority: length before address, source before destination;
;   guard bytes around every successful destination span remain unchanged;
;   a final 24-byte copy after all negative cases proves recovery.
;
; Every source pattern and expected byte is generated in-guest with native
; STB/LDB. There are no host-computed arrays, no floating point, and no host
; arithmetic. The fixture relocates above the low 64 KiB before writing byte
; addresses 0..23, so the boot stub can be overwritten safely.

.org 0
  LA r1,@mth_copy_test_main
  JMPR r1

.org 16384
.include "../nan16/mth_byte_copy24.nas"

mth_copy_test_main:
  MOVI r0,0
  MOVI r13,1

  CALL @mth_copy_test_len1
  CALL @mth_copy_test_len4
  CALL @mth_copy_test_len24
  CALL @mth_copy_test_alias
  CALL @mth_copy_test_overlap
  CALL @mth_copy_test_bounds
  CALL @mth_copy_test_recovery

  MOVI r1,@mth_copy_test_pass
  CALL @mth_copy_test_puts
  HALT

mth_copy_test_fail:
  MOVI r1,@mth_copy_test_bad
  CALL @mth_copy_test_puts
  HALT

; ---- length 1 -----------------------------------------------------------

mth_copy_test_len1:
  ST r15,r0,@mth_copy_test_ret_section

  ; source at byte 0 -> destination 0x8100, guards at 0x80F8 and 0x8101
  MOVI r1,0
  MOVI r2,1
  MOVI r3,0x11
  CALL @mth_copy_test_fill_ramp

  MOVI r1,0x80F8
  MOVI r2,17
  MOVI r3,0xA5
  CALL @mth_copy_test_fill_const

  MOVI r1,0
  MOVI r2,0x8100
  MOVI r3,1
  MOVI r4,0x11
  CALL @mth_copy_test_expect_success

  MOVI r1,0x80F8
  MOVI r2,8
  MOVI r3,0xA5
  CALL @mth_copy_test_check_const
  MOVI r1,0x8101
  MOVI r2,8
  MOVI r3,0xA5
  CALL @mth_copy_test_check_const

  ; destination at byte 0 <- source 0x8200, trailing guard at byte 1
  MOVI r1,0
  MOVI r2,9
  MOVI r3,0xA5
  CALL @mth_copy_test_fill_const

  MOVI r1,0x8200
  MOVI r2,1
  MOVI r3,0x33
  CALL @mth_copy_test_fill_ramp

  MOVI r1,0x8200
  MOVI r2,0
  MOVI r3,1
  MOVI r4,0x33
  CALL @mth_copy_test_expect_success

  MOVI r1,1
  MOVI r2,8
  MOVI r3,0xA5
  CALL @mth_copy_test_check_const

  ; source at 0x7FFFFF -> destination 0x8300
  MOVI r1,0xFFFF
  MOVHI r1,0x007F
  MOVI r2,1
  MOVI r3,0x55
  CALL @mth_copy_test_fill_ramp

  MOVI r1,0x82F8
  MOVI r2,17
  MOVI r3,0xA5
  CALL @mth_copy_test_fill_const

  MOVI r1,0xFFFF
  MOVHI r1,0x007F
  MOVI r2,0x8300
  MOVI r3,1
  MOVI r4,0x55
  CALL @mth_copy_test_expect_success

  MOVI r1,0x82F8
  MOVI r2,8
  MOVI r3,0xA5
  CALL @mth_copy_test_check_const
  MOVI r1,0x8301
  MOVI r2,8
  MOVI r3,0xA5
  CALL @mth_copy_test_check_const

  ; destination at 0x7FFFFF <- source 0x8400, guard at 0x7FFFF7
  ; The +1 beyond the root end also proves the last-byte store stops there.
  MOVI r1,0xFFF7
  MOVHI r1,0x007F
  MOVI r2,10
  MOVI r3,0xA5
  CALL @mth_copy_test_fill_const

  MOVI r1,0x8400
  MOVI r2,1
  MOVI r3,0x66
  CALL @mth_copy_test_fill_ramp

  MOVI r1,0x8400
  MOVI r2,0xFFFF
  MOVHI r2,0x007F
  MOVI r3,1
  MOVI r4,0x66
  CALL @mth_copy_test_expect_success

  MOVI r1,0xFFF7
  MOVHI r1,0x007F
  MOVI r2,8
  MOVI r3,0xA5
  CALL @mth_copy_test_check_const
  MOVI r1,0
  MOVHI r1,0x0080
  MOVI r2,1
  MOVI r3,0xA5
  CALL @mth_copy_test_check_const

  LD r15,r0,@mth_copy_test_ret_section
  RET

; ---- length 4 -----------------------------------------------------------

mth_copy_test_len4:
  ST r15,r0,@mth_copy_test_ret_section

  ; source at byte 0 -> destination 0x8100
  MOVI r1,0
  MOVI r2,4
  MOVI r3,0x21
  CALL @mth_copy_test_fill_ramp

  MOVI r1,0x80F8
  MOVI r2,20
  MOVI r3,0xA5
  CALL @mth_copy_test_fill_const

  MOVI r1,0
  MOVI r2,0x8100
  MOVI r3,4
  MOVI r4,0x21
  CALL @mth_copy_test_expect_success

  MOVI r1,0x80F8
  MOVI r2,8
  MOVI r3,0xA5
  CALL @mth_copy_test_check_const
  MOVI r1,0x8104
  MOVI r2,8
  MOVI r3,0xA5
  CALL @mth_copy_test_check_const

  ; destination at byte 0 <- source 0x8200
  MOVI r1,0
  MOVI r2,12
  MOVI r3,0xA5
  CALL @mth_copy_test_fill_const

  MOVI r1,0x8200
  MOVI r2,4
  MOVI r3,0x43
  CALL @mth_copy_test_fill_ramp

  MOVI r1,0x8200
  MOVI r2,0
  MOVI r3,4
  MOVI r4,0x43
  CALL @mth_copy_test_expect_success

  MOVI r1,4
  MOVI r2,8
  MOVI r3,0xA5
  CALL @mth_copy_test_check_const

  ; source at 0x7FFFFC -> destination 0x8300
  MOVI r1,0xFFFC
  MOVHI r1,0x007F
  MOVI r2,4
  MOVI r3,0x65
  CALL @mth_copy_test_fill_ramp

  MOVI r1,0x82F8
  MOVI r2,20
  MOVI r3,0xA5
  CALL @mth_copy_test_fill_const

  MOVI r1,0xFFFC
  MOVHI r1,0x007F
  MOVI r2,0x8300
  MOVI r3,4
  MOVI r4,0x65
  CALL @mth_copy_test_expect_success

  MOVI r1,0x82F8
  MOVI r2,8
  MOVI r3,0xA5
  CALL @mth_copy_test_check_const
  MOVI r1,0x8304
  MOVI r2,8
  MOVI r3,0xA5
  CALL @mth_copy_test_check_const

  ; destination at 0x7FFFFC <- source 0x8400
  MOVI r1,0xFFF4
  MOVHI r1,0x007F
  MOVI r2,13
  MOVI r3,0xA5
  CALL @mth_copy_test_fill_const

  MOVI r1,0x8400
  MOVI r2,4
  MOVI r3,0x76
  CALL @mth_copy_test_fill_ramp

  MOVI r1,0x8400
  MOVI r2,0xFFFC
  MOVHI r2,0x007F
  MOVI r3,4
  MOVI r4,0x76
  CALL @mth_copy_test_expect_success

  MOVI r1,0xFFF4
  MOVHI r1,0x007F
  MOVI r2,8
  MOVI r3,0xA5
  CALL @mth_copy_test_check_const
  MOVI r1,0
  MOVHI r1,0x0080
  MOVI r2,1
  MOVI r3,0xA5
  CALL @mth_copy_test_check_const

  LD r15,r0,@mth_copy_test_ret_section
  RET

; ---- length 24 ----------------------------------------------------------

mth_copy_test_len24:
  ST r15,r0,@mth_copy_test_ret_section

  ; source at byte 0 -> destination 0x8100
  MOVI r1,0
  MOVI r2,24
  MOVI r3,0x31
  CALL @mth_copy_test_fill_ramp

  MOVI r1,0x80F8
  MOVI r2,40
  MOVI r3,0xA5
  CALL @mth_copy_test_fill_const

  MOVI r1,0
  MOVI r2,0x8100
  MOVI r3,24
  MOVI r4,0x31
  CALL @mth_copy_test_expect_success

  MOVI r1,0x80F8
  MOVI r2,8
  MOVI r3,0xA5
  CALL @mth_copy_test_check_const
  MOVI r1,0x8118
  MOVI r2,8
  MOVI r3,0xA5
  CALL @mth_copy_test_check_const

  ; destination at byte 0 <- source 0x8200
  MOVI r1,0
  MOVI r2,32
  MOVI r3,0xA5
  CALL @mth_copy_test_fill_const

  MOVI r1,0x8200
  MOVI r2,24
  MOVI r3,0x53
  CALL @mth_copy_test_fill_ramp

  MOVI r1,0x8200
  MOVI r2,0
  MOVI r3,24
  MOVI r4,0x53
  CALL @mth_copy_test_expect_success

  MOVI r1,24
  MOVI r2,8
  MOVI r3,0xA5
  CALL @mth_copy_test_check_const

  ; source at 0x7FFFE8 -> destination 0x8300
  MOVI r1,0xFFE8
  MOVHI r1,0x007F
  MOVI r2,24
  MOVI r3,0x75
  CALL @mth_copy_test_fill_ramp

  MOVI r1,0x82F8
  MOVI r2,40
  MOVI r3,0xA5
  CALL @mth_copy_test_fill_const

  MOVI r1,0xFFE8
  MOVHI r1,0x007F
  MOVI r2,0x8300
  MOVI r3,24
  MOVI r4,0x75
  CALL @mth_copy_test_expect_success

  MOVI r1,0x82F8
  MOVI r2,8
  MOVI r3,0xA5
  CALL @mth_copy_test_check_const
  MOVI r1,0x8318
  MOVI r2,8
  MOVI r3,0xA5
  CALL @mth_copy_test_check_const

  ; destination at 0x7FFFE8 <- source 0x8400
  MOVI r1,0xFFE0
  MOVHI r1,0x007F
  MOVI r2,33
  MOVI r3,0xA5
  CALL @mth_copy_test_fill_const

  MOVI r1,0x8400
  MOVI r2,24
  MOVI r3,0x86
  CALL @mth_copy_test_fill_ramp

  MOVI r1,0x8400
  MOVI r2,0xFFE8
  MOVHI r2,0x007F
  MOVI r3,24
  MOVI r4,0x86
  CALL @mth_copy_test_expect_success

  MOVI r1,0xFFE0
  MOVHI r1,0x007F
  MOVI r2,8
  MOVI r3,0xA5
  CALL @mth_copy_test_check_const
  MOVI r1,0
  MOVHI r1,0x0080
  MOVI r2,1
  MOVI r3,0xA5
  CALL @mth_copy_test_check_const

  ; unaligned 24-byte copy across payload-word boundaries
  MOVI r1,0x8F03
  MOVI r2,24
  MOVI r3,0xC5
  CALL @mth_copy_test_fill_ramp

  MOVI r1,0x8F7B
  MOVI r2,40
  MOVI r3,0xA5
  CALL @mth_copy_test_fill_const

  MOVI r1,0x8F03
  MOVI r2,0x8F83
  MOVI r3,24
  MOVI r4,0xC5
  CALL @mth_copy_test_expect_success

  MOVI r1,0x8F7B
  MOVI r2,8
  MOVI r3,0xA5
  CALL @mth_copy_test_check_const
  MOVI r1,0x8F9B
  MOVI r2,8
  MOVI r3,0xA5
  CALL @mth_copy_test_check_const

  LD r15,r0,@mth_copy_test_ret_section
  RET

; ---- exact source == destination aliases --------------------------------

mth_copy_test_alias:
  ST r15,r0,@mth_copy_test_ret_section

  ; 24-byte alias in the scratch arena
  MOVI r1,0x8500
  MOVI r2,24
  MOVI r3,0x77
  CALL @mth_copy_test_fill_ramp

  MOVI r1,0x8500
  MOVI r2,0x8500
  MOVI r3,24
  MOVI r4,0x77
  CALL @mth_copy_test_expect_success

  ; 24-byte alias at byte 0 (no store may touch the low stub)
  MOVI r1,0
  MOVI r2,24
  MOVI r3,0x99
  CALL @mth_copy_test_fill_ramp

  MOVI r1,0
  MOVI r2,0
  MOVI r3,24
  MOVI r4,0x99
  CALL @mth_copy_test_expect_success

  ; 24-byte alias at the canonical root end
  MOVI r1,0xFFE8
  MOVHI r1,0x007F
  MOVI r2,24
  MOVI r3,0xBB
  CALL @mth_copy_test_fill_ramp

  MOVI r1,0xFFE8
  MOVHI r1,0x007F
  MOVI r2,0xFFE8
  MOVHI r2,0x007F
  MOVI r3,24
  MOVI r4,0xBB
  CALL @mth_copy_test_expect_success

  LD r15,r0,@mth_copy_test_ret_section
  RET

; ---- partial-overlap rejection and adjacency ----------------------------

mth_copy_test_overlap:
  ST r15,r0,@mth_copy_test_ret_section

  ; source < destination, partial overlap: src 0x8600, dst 0x8604, n 24
  MOVI r1,0x8600
  MOVI r2,32
  MOVI r3,0x5A
  CALL @mth_copy_test_fill_ramp

  MOVI r1,0x8600
  MOVI r2,0x8604
  MOVI r3,24
  MOVI r4,5
  CALL @mth_copy_test_expect_reject

  MOVI r1,0x8600
  MOVI r2,32
  MOVI r3,0x5A
  CALL @mth_copy_test_check_ramp

  ; destination < source, partial overlap: src 0x8700, dst 0x86F8, n 24
  MOVI r1,0x86F8
  MOVI r2,32
  MOVI r3,0x6B
  CALL @mth_copy_test_fill_ramp

  MOVI r1,0x8700
  MOVI r2,0x86F8
  MOVI r3,24
  MOVI r4,5
  CALL @mth_copy_test_expect_reject

  MOVI r1,0x86F8
  MOVI r2,32
  MOVI r3,0x6B
  CALL @mth_copy_test_check_ramp

  ; one-byte overlap at the high end: dst == src + 23
  MOVI r1,0x8800
  MOVI r2,48
  MOVI r3,0x7C
  CALL @mth_copy_test_fill_ramp

  MOVI r1,0x8800
  MOVI r2,0x8817
  MOVI r3,24
  MOVI r4,5
  CALL @mth_copy_test_expect_reject

  MOVI r1,0x8800
  MOVI r2,48
  MOVI r3,0x7C
  CALL @mth_copy_test_check_ramp

  ; one-byte overlap at the low end: src == dst + 23
  MOVI r1,0x88E9
  MOVI r2,48
  MOVI r3,0x8D
  CALL @mth_copy_test_fill_ramp

  MOVI r1,0x8900
  MOVI r2,0x88E9
  MOVI r3,24
  MOVI r4,5
  CALL @mth_copy_test_expect_reject

  MOVI r1,0x88E9
  MOVI r2,48
  MOVI r3,0x8D
  CALL @mth_copy_test_check_ramp

  ; destination poisoned 0xA5, source overlaps it: reject leaves every
  ; destination byte poisoned. src [0x8EB0,0x8EC8), dst [0x8EC0,0x8ED8).
  MOVI r1,0x8EC0
  MOVI r2,24
  MOVI r3,0xA5
  CALL @mth_copy_test_fill_const

  MOVI r1,0x8EB0
  MOVI r2,16
  MOVI r3,0x3C
  CALL @mth_copy_test_fill_ramp

  MOVI r1,0x8EB0
  MOVI r2,0x8EC0
  MOVI r3,24
  MOVI r4,5
  CALL @mth_copy_test_expect_reject

  MOVI r1,0x8EC0
  MOVI r2,24
  MOVI r3,0xA5
  CALL @mth_copy_test_check_const

  MOVI r1,0x8EB0
  MOVI r2,16
  MOVI r3,0x3C
  CALL @mth_copy_test_check_ramp

  ; disjoint bytes inside one payload word are not overlap.
  ; Copy +0 -> +2 and prove the other three payload bytes survive.
  MOVI r1,0x8D80
  MOVI r2,4
  MOVI r3,0xA0
  CALL @mth_copy_test_fill_ramp

  MOVI r1,0x8D80
  MOVI r2,0x8D82
  MOVI r3,1
  MOVI r4,0xA0
  CALL @mth_copy_test_expect_success

  MOVI r1,0x8D80
  MOVI r2,1
  MOVI r3,0xA0
  CALL @mth_copy_test_check_const
  MOVI r1,0x8D81
  MOVI r2,1
  MOVI r3,0xA1
  CALL @mth_copy_test_check_const
  MOVI r1,0x8D82
  MOVI r2,1
  MOVI r3,0xA0
  CALL @mth_copy_test_check_const
  MOVI r1,0x8D83
  MOVI r2,1
  MOVI r3,0xA3
  CALL @mth_copy_test_check_const

  ; The reverse same-word disjoint case: copy +3 -> +0.
  MOVI r1,0x8D80
  MOVI r2,4
  MOVI r3,0xB0
  CALL @mth_copy_test_fill_ramp

  MOVI r1,0x8D83
  MOVI r2,0x8D80
  MOVI r3,1
  MOVI r4,0xB3
  CALL @mth_copy_test_expect_success

  MOVI r1,0x8D80
  MOVI r2,1
  MOVI r3,0xB3
  CALL @mth_copy_test_check_const
  MOVI r1,0x8D81
  MOVI r2,1
  MOVI r3,0xB1
  CALL @mth_copy_test_check_const
  MOVI r1,0x8D82
  MOVI r2,1
  MOVI r3,0xB2
  CALL @mth_copy_test_check_const
  MOVI r1,0x8D83
  MOVI r2,1
  MOVI r3,0xB3
  CALL @mth_copy_test_check_const

  ; adjacent, non-overlapping: dst == src + 24 is accepted
  MOVI r1,0x8A00
  MOVI r2,24
  MOVI r3,0x6C
  CALL @mth_copy_test_fill_ramp

  MOVI r1,0x8A18
  MOVI r2,32
  MOVI r3,0xA5
  CALL @mth_copy_test_fill_const

  MOVI r1,0x8A00
  MOVI r2,0x8A18
  MOVI r3,24
  MOVI r4,0x6C
  CALL @mth_copy_test_expect_success

  MOVI r1,0x8A30
  MOVI r2,8
  MOVI r3,0xA5
  CALL @mth_copy_test_check_const

  ; adjacent, non-overlapping: src == dst + 24 is accepted
  MOVI r1,0x8AF8
  MOVI r2,64
  MOVI r3,0xA5
  CALL @mth_copy_test_fill_const

  MOVI r1,0x8B18
  MOVI r2,24
  MOVI r3,0x9E
  CALL @mth_copy_test_fill_ramp

  MOVI r1,0x8B18
  MOVI r2,0x8B00
  MOVI r3,24
  MOVI r4,0x9E
  CALL @mth_copy_test_expect_success

  MOVI r1,0x8AF8
  MOVI r2,8
  MOVI r3,0xA5
  CALL @mth_copy_test_check_const
  MOVI r1,0x8B30
  MOVI r2,8
  MOVI r3,0xA5
  CALL @mth_copy_test_check_const

  LD r15,r0,@mth_copy_test_ret_section
  RET

; ---- length, bounds, wrap, and validation-order rejection ---------------

mth_copy_test_bounds:
  ST r15,r0,@mth_copy_test_ret_section

  ; valid scratch source and poisoned destination
  MOVI r1,0x8D00
  MOVI r2,24
  MOVI r3,0x21
  CALL @mth_copy_test_fill_ramp

  MOVI r1,0x8C00
  MOVI r2,32
  MOVI r3,0xC3
  CALL @mth_copy_test_fill_const

  ; cause 1: length zero
  MOVI r1,0x8D00
  MOVI r2,0x8C00
  MOVI r3,0
  MOVI r4,1
  CALL @mth_copy_test_expect_reject

  MOVI r1,0x8C00
  MOVI r2,32
  MOVI r3,0xC3
  CALL @mth_copy_test_check_const

  ; cause 1: length zero even for an exact alias
  MOVI r1,0x8C00
  MOVI r2,0x8C00
  MOVI r3,0
  MOVI r4,1
  CALL @mth_copy_test_expect_reject

  MOVI r1,0x8C00
  MOVI r2,32
  MOVI r3,0xC3
  CALL @mth_copy_test_check_const

  ; cause 2: length 25
  MOVI r1,0x8D00
  MOVI r2,0x8C00
  MOVI r3,25
  MOVI r4,2
  CALL @mth_copy_test_expect_reject

  MOVI r1,0x8C00
  MOVI r2,32
  MOVI r3,0xC3
  CALL @mth_copy_test_check_const

  ; cause 2: length 0xFFFFFFFF
  MOVI r1,0x8D00
  MOVI r2,0x8C00
  MOVI r3,0xFFFF
  MOVHI r3,0xFFFF
  MOVI r4,2
  CALL @mth_copy_test_expect_reject

  MOVI r1,0x8C00
  MOVI r2,32
  MOVI r3,0xC3
  CALL @mth_copy_test_check_const

  ; cause 3: source exactly at the canonical root end
  MOVI r1,0
  MOVHI r1,0x0080
  MOVI r2,0x8C00
  MOVI r3,1
  MOVI r4,3
  CALL @mth_copy_test_expect_reject

  MOVI r1,0x8C00
  MOVI r2,32
  MOVI r3,0xC3
  CALL @mth_copy_test_check_const

  ; cause 3: source at the last byte with length 2
  MOVI r1,0xFFFF
  MOVHI r1,0x007F
  MOVI r2,0x8C00
  MOVI r3,2
  MOVI r4,3
  CALL @mth_copy_test_expect_reject

  MOVI r1,0x8C00
  MOVI r2,32
  MOVI r3,0xC3
  CALL @mth_copy_test_check_const

  ; cause 3: source 0xFFFFFFFF + 1 wraps
  MOVI r1,0xFFFF
  MOVHI r1,0xFFFF
  MOVI r2,0x8C00
  MOVI r3,1
  MOVI r4,3
  CALL @mth_copy_test_expect_reject

  MOVI r1,0x8C00
  MOVI r2,32
  MOVI r3,0xC3
  CALL @mth_copy_test_check_const

  ; cause 3: source 0xFFFFFFFE + 4 wraps
  MOVI r1,0xFFFE
  MOVHI r1,0xFFFF
  MOVI r2,0x8C00
  MOVI r3,4
  MOVI r4,3
  CALL @mth_copy_test_expect_reject

  MOVI r1,0x8C00
  MOVI r2,32
  MOVI r3,0xC3
  CALL @mth_copy_test_check_const

  ; cause 4: destination exactly at the canonical root end
  MOVI r1,0
  MOVHI r1,0x0080
  MOVI r2,8
  MOVI r3,0xE7
  CALL @mth_copy_test_fill_const

  MOVI r1,0x8D00
  MOVI r2,0
  MOVHI r2,0x0080
  MOVI r3,1
  MOVI r4,4
  CALL @mth_copy_test_expect_reject

  MOVI r1,0
  MOVHI r1,0x0080
  MOVI r2,8
  MOVI r3,0xE7
  CALL @mth_copy_test_check_const

  ; cause 4: destination at the last byte with length 2
  MOVI r1,0xFFFF
  MOVHI r1,0x007F
  MOVI r2,2
  MOVI r3,0xE7
  CALL @mth_copy_test_fill_const

  MOVI r1,0x8D00
  MOVI r2,0xFFFF
  MOVHI r2,0x007F
  MOVI r3,2
  MOVI r4,4
  CALL @mth_copy_test_expect_reject

  MOVI r1,0xFFFF
  MOVHI r1,0x007F
  MOVI r2,2
  MOVI r3,0xE7
  CALL @mth_copy_test_check_const

  ; cause 4: destination 0xFFFFFFF0 + 24 wraps to byte 8
  MOVI r1,8
  MOVI r2,24
  MOVI r3,0xE7
  CALL @mth_copy_test_fill_const

  MOVI r1,0x8D00
  MOVI r2,0xFFF0
  MOVHI r2,0xFFFF
  MOVI r3,24
  MOVI r4,4
  CALL @mth_copy_test_expect_reject

  MOVI r1,8
  MOVI r2,24
  MOVI r3,0xE7
  CALL @mth_copy_test_check_const

  ; cause 4: destination 0xFFFFFFFF + 1 wraps
  MOVI r1,0x8D00
  MOVI r2,0xFFFF
  MOVHI r2,0xFFFF
  MOVI r3,1
  MOVI r4,4
  CALL @mth_copy_test_expect_reject

  ; validation priority: length 0 before invalid source and destination
  MOVI r1,0
  MOVHI r1,0x0080
  MOVI r2,0
  MOVHI r2,0x0080
  MOVI r3,0
  MOVI r4,1
  CALL @mth_copy_test_expect_reject

  ; validation priority: length 25 before invalid source
  MOVI r1,0
  MOVHI r1,0x0080
  MOVI r2,0x8C00
  MOVI r3,25
  MOVI r4,2
  CALL @mth_copy_test_expect_reject

  ; validation priority: source bound before destination bound
  MOVI r1,0
  MOVHI r1,0x0080
  MOVI r2,0
  MOVHI r2,0x0080
  MOVI r3,1
  MOVI r4,3
  CALL @mth_copy_test_expect_reject

  ; the valid destination scratch is still poison after every rejection
  MOVI r1,0x8C00
  MOVI r2,32
  MOVI r3,0xC3
  CALL @mth_copy_test_check_const

  LD r15,r0,@mth_copy_test_ret_section
  RET

; ---- recovery after every negative case --------------------------------

mth_copy_test_recovery:
  ST r15,r0,@mth_copy_test_ret_section

  MOVI r1,0x8E00
  MOVI r2,24
  MOVI r3,0x44
  CALL @mth_copy_test_fill_ramp

  MOVI r1,0x8E40
  MOVI r2,32
  MOVI r3,0xA5
  CALL @mth_copy_test_fill_const

  MOVI r1,0x8E00
  MOVI r2,0x8E40
  MOVI r3,24
  MOVI r4,0x44
  CALL @mth_copy_test_expect_success

  MOVI r1,0x8E58
  MOVI r2,8
  MOVI r3,0xA5
  CALL @mth_copy_test_check_const

  LD r15,r0,@mth_copy_test_ret_section
  RET

; ---- helpers ------------------------------------------------------------

; r1 = byte address, r2 = count, r3 = first value.
; Fills count bytes with (first + i) mod 256.
mth_copy_test_fill_ramp:
  ADD r4,r1,r2
mth_copy_test_fill_ramp_loop:
  STB r3,r1,0
  ADDI r1,r1,1
  ADDI r3,r3,1
  CMP r1,r4
  JMP[LT] @mth_copy_test_fill_ramp_loop
  RET

; r1 = byte address, r2 = count, r3 = value.
; Fills count bytes with the low byte of r3.
mth_copy_test_fill_const:
  ADD r4,r1,r2
mth_copy_test_fill_const_loop:
  STB r3,r1,0
  ADDI r1,r1,1
  CMP r1,r4
  JMP[LT] @mth_copy_test_fill_const_loop
  RET

; r1 = byte address, r2 = count, r3 = first expected value.
; Jumps to the fail marker on the first mismatching byte.
mth_copy_test_check_ramp:
  ADD r4,r1,r2
  MOVI r6,255
mth_copy_test_check_ramp_loop:
  LDB r5,r1,0
  BOOL.8 r7,r3,r6
  CMP r5,r7
  JMP[NE] @mth_copy_test_fail
  ADDI r1,r1,1
  ADDI r3,r3,1
  CMP r1,r4
  JMP[LT] @mth_copy_test_check_ramp_loop
  RET

; r1 = byte address, r2 = count, r3 = expected value.
; Jumps to the fail marker on the first mismatching byte.
mth_copy_test_check_const:
  ADD r4,r1,r2
  MOVI r6,255
  BOOL.8 r7,r3,r6
mth_copy_test_check_const_loop:
  LDB r5,r1,0
  CMP r5,r7
  JMP[NE] @mth_copy_test_fail
  ADDI r1,r1,1
  CMP r1,r4
  JMP[LT] @mth_copy_test_check_const_loop
  RET

; r1 = source, r2 = destination, r3 = length, r4 = first source byte.
; Requires success, r4 == length, r9 == 0, and an exact destination ramp.
mth_copy_test_expect_success:
  ST r15,r0,@mth_copy_test_ret_helper
  ST r1,r0,@mth_copy_test_src
  ST r2,r0,@mth_copy_test_dst
  ST r3,r0,@mth_copy_test_len
  ST r4,r0,@mth_copy_test_first
  CALL @mth_byte_copy24
  CMP r1,r13
  JMP[NE] @mth_copy_test_fail
  CMP r9,r0
  JMP[NE] @mth_copy_test_fail
  LD r5,r0,@mth_copy_test_len
  CMP r4,r5
  JMP[NE] @mth_copy_test_fail
  LD r1,r0,@mth_copy_test_dst
  LD r2,r0,@mth_copy_test_len
  LD r3,r0,@mth_copy_test_first
  CALL @mth_copy_test_check_ramp
  LD r15,r0,@mth_copy_test_ret_helper
  RET

; r1 = source, r2 = destination, r3 = length, r4 = expected cause.
; Requires r1 == 0, r9 == cause, and r4 == 0.
mth_copy_test_expect_reject:
  ST r15,r0,@mth_copy_test_ret_helper
  ST r4,r0,@mth_copy_test_cause
  CALL @mth_byte_copy24
  CMP r1,r0
  JMP[NE] @mth_copy_test_fail
  LD r5,r0,@mth_copy_test_cause
  CMP r9,r5
  JMP[NE] @mth_copy_test_fail
  CMP r4,r0
  JMP[NE] @mth_copy_test_fail
  LD r15,r0,@mth_copy_test_ret_helper
  RET

mth_copy_test_puts:
  MOVI r4,255
mth_copy_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_copy_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_copy_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_copy_test_puts_word

; ---- data (word-addressed; byte addresses are label << 2) ---------------

.org 24576
mth_copy_test_ret_section:
.word 0
mth_copy_test_ret_helper:
.word 0
mth_copy_test_src:
.word 0
mth_copy_test_dst:
.word 0
mth_copy_test_len:
.word 0
mth_copy_test_first:
.word 0
mth_copy_test_cause:
.word 0
mth_copy_test_pass:
.str "MTH BYTE COPY24 PASS\n"
mth_copy_test_bad:
.str "MTH BYTE COPY24 FAIL\n"
