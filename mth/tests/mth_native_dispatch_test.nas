.org 0
JMP @mth_dispatch_test_main
.include "../nan16/mth_native_dispatch.nas"

mth_dispatch_test_main:
  MOVI r13,1
  ; Fill x=2.0 and y=3.0; dot must be exactly 1536.0.
  MOVI r1,@mth_dispatch_x
  MOVI r2,@mth_dispatch_y
  MOVI r6,256
  MOVI r7,0
  MOVHI r7,0x4000
mth_dispatch_fill_x:
  ST r7,r1,0
  ADD r1,r1,r13
  SUB r6,r6,r13
  CMP r6,r0
  JMP[GT] @mth_dispatch_fill_x
  MOVI r2,@mth_dispatch_y
  MOVI r6,256
  MOVI r7,0
  MOVHI r7,0x4040
mth_dispatch_fill_y:
  ST r7,r2,0
  ADD r2,r2,r13
  SUB r6,r6,r13
  CMP r6,r0
  JMP[GT] @mth_dispatch_fill_y

  MOVI r1,900
  MOVI r2,@mth_dispatch_x
  MOVI r3,@mth_dispatch_y
  MOVI r4,@mth_dispatch_out
  MOVI r5,@mth_dispatch_scratch
  MOVI r6,256
  CALL @mth_native_dispatch
  CMP r1,r0
  JMP[NE] @mth_dispatch_fail_dot
  MOVI r8,@mth_dispatch_out
  LD r9,r8,0
  MOVI r10,0
  MOVHI r10,0x44C0
  CMP r9,r10
  JMP[NE] @mth_dispatch_fail_dot

  ; Program 901 dispatches cosine; distinct caller scratch preserves reentry.
  MOVI r1,901
  MOVI r2,@mth_dispatch_x
  MOVI r3,@mth_dispatch_x
  MOVI r4,@mth_dispatch_out
  MOVI r5,@mth_dispatch_scratch
  MOVI r6,256
  CALL @mth_native_dispatch
  CMP r1,r0
  JMP[NE] @mth_dispatch_fail_cosine
  MOVI r8,@mth_dispatch_out
  LD r9,r8,0
  MOVI r10,0
  MOVHI r10,0x3F80
  CMP r9,r10
  JMP[NE] @mth_dispatch_fail_cosine

  ; Unknown IDs and unsupported dimensions are rejected before kernel entry.
  MOVI r8,@mth_dispatch_out
  MOVI r9,77
  ST r9,r8,0
  MOVI r1,999
  MOVI r2,@mth_dispatch_x
  MOVI r3,@mth_dispatch_y
  MOVI r4,@mth_dispatch_out
  MOVI r5,@mth_dispatch_scratch
  MOVI r6,256
  CALL @mth_native_dispatch
  MOVI r9,1
  CMP r1,r9
  JMP[NE] @mth_dispatch_fail_unknown
  LD r9,r8,0
  MOVI r10,77
  CMP r9,r10
  JMP[NE] @mth_dispatch_fail_unknown

  MOVI r1,900
  MOVI r2,@mth_dispatch_x
  MOVI r3,@mth_dispatch_y
  MOVI r4,@mth_dispatch_out
  MOVI r5,@mth_dispatch_scratch
  MOVI r6,255
  CALL @mth_native_dispatch
  MOVI r9,2
  CMP r1,r9
  JMP[NE] @mth_dispatch_fail_dimension
  LD r9,r8,0
  MOVI r10,77
  CMP r9,r10
  JMP[NE] @mth_dispatch_fail_dimension

  MOVI r1,@mth_dispatch_pass
  CALL @mth_dispatch_puts
  HALT

mth_dispatch_fail_dot:
  MOVI r1,@mth_dispatch_dot_bad
  CALL @mth_dispatch_puts
  HALT
mth_dispatch_fail_cosine:
  MOVI r1,@mth_dispatch_cosine_bad
  CALL @mth_dispatch_puts
  HALT
mth_dispatch_fail_unknown:
  MOVI r1,@mth_dispatch_unknown_bad
  CALL @mth_dispatch_puts
  HALT
mth_dispatch_fail_dimension:
  MOVI r1,@mth_dispatch_dimension_bad
  CALL @mth_dispatch_puts
  HALT

mth_dispatch_puts:
  MOVI r4,255
mth_dispatch_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_dispatch_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_dispatch_puts_byte
  ADD r1,r1,r13
  JMP @mth_dispatch_puts_word

.org 1024
mth_dispatch_x:
.word 0
.org 2048
mth_dispatch_y:
.word 0
.org 3072
mth_dispatch_out:
.word 77
.org 3584
mth_dispatch_scratch:
.word 0,0,0,0,0,0,0,0,0,0,0
mth_dispatch_pass:
.str "MTH NATIVE DISPATCH PASS\n"
mth_dispatch_dot_bad:
.str "MTH NATIVE DISPATCH FAIL: dot\n"
mth_dispatch_cosine_bad:
.str "MTH NATIVE DISPATCH FAIL: cosine\n"
mth_dispatch_unknown_bad:
.str "MTH NATIVE DISPATCH FAIL: unknown id\n"
mth_dispatch_dimension_bad:
.str "MTH NATIVE DISPATCH FAIL: dimension\n"
