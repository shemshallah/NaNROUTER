; MTH mirror-root block checksum fixture — NaN16 only.
;
; Exercises mth_mirror_block_checksum over the canonical 8 MiB payload byte
; space. The test body relocates above the low 64 KiB before touching address
; 0, so the block-at-0 cases can overwrite the boot stub and padding without
; destroying the running code.
;
; Coverage:
;   * empty-length rejection at 0 and at the root end;
;   * maximum legal length 65536 at 0 and at 0x7F0000 (ending exactly at
;     8388608);
;   * one byte, four bytes, and 256 bytes at byte address 0;
;   * one byte, four bytes, and 256 bytes ending exactly at 8388608;
;   * published FNV-1a vectors "a", "test", "foobar", "hello";
;   * a caller-supplied seed of 0 (proves r3 initialises the hash);
;   * the 0..255 ramp and an all-zero 64 KiB block;
;   * deterministic repeat at 0 and at the root end;
;   * bounds rejection: start at 8388608, end beyond 8388608, length 65537,
;     length 0xFFFFFFFF, and three genuine 32-bit address+length wraps.
;
; Every expected checksum is an embedded scalar FNV constant. The guest does
; not call a host implementation and has no host-computed expected arrays.

.org 0
  LA r1,@mth_cksum_test_main
  JMPR r1

; The kernel and all test code/data live at or above word 16384 (byte address
; 65536), leaving the entire low 64 KiB available as the block-at-0 arena.
.org 16384
.include "../nan16/mth_mirror_block_checksum.nas"

mth_cksum_test_main:
  MOVI r0,0
  MOVI r13,1

  ; ---- empty-length rejection ----
  MOVI r1,0
  MOVI r2,0
  MOVI r3,0
  CALL @mth_cksum_test_reject

  MOVI r1,0
  MOVHI r1,0x0080            ; 8388608
  MOVI r2,0
  MOVI r3,0x9DC5
  MOVHI r3,0x811C
  CALL @mth_cksum_test_reject

  ; ---- zero the low 64 KiB arena (16384 NaN16 words) ----
  MOVI r1,0
  MOVI r2,0x4000
  BFILL r1,r0,r2

  ; ---- 65536 zero bytes at address 0: maximum legal length ----
  MOVI r1,0
  MOVI r2,0
  MOVHI r2,1                 ; 65536
  MOVI r3,0x9DC5
  MOVHI r3,0x811C            ; FNV offset basis
  MOVI r4,0x9DC5
  MOVHI r4,0x5E50            ; FNV-1a32(65536 x 0x00)
  CALL @mth_cksum_test_expect

  ; ---- 65536 zero bytes ending exactly at the root end ----
  MOVI r1,0
  MOVHI r1,0x007F            ; 0x007F0000
  MOVI r2,0
  MOVHI r2,1                 ; 65536
  MOVI r3,0x9DC5
  MOVHI r3,0x811C
  MOVI r4,0x9DC5
  MOVHI r4,0x5E50
  CALL @mth_cksum_test_expect

  ; ---- one byte at address 0: "a" ----
  MOVI r1,0
  MOVI r4,0x61               ; 'a'
  STB r4,r1,0
  MOVI r2,1
  MOVI r3,0x9DC5
  MOVHI r3,0x811C
  MOVI r4,0x292C
  MOVHI r4,0xE40C            ; FNV-1a32("a")
  CALL @mth_cksum_test_expect

  ; ---- same byte, seed 0: h = (0 XOR 0x61) * prime ----
  MOVI r1,0
  MOVI r2,1
  MOVI r3,0
  MOVI r4,0x98B3
  MOVHI r4,0x6100
  CALL @mth_cksum_test_expect

  ; ---- four bytes at address 0: "test" ----
  MOVI r1,0
  MOVI r4,0x74
  STB r4,r1,0
  MOVI r4,0x65
  STB r4,r1,1
  MOVI r4,0x73
  STB r4,r1,2
  MOVI r4,0x74
  STB r4,r1,3
  MOVI r2,4
  MOVI r3,0x9DC5
  MOVHI r3,0x811C
  MOVI r4,0x71E5
  MOVHI r4,0xAFD0            ; FNV-1a32("test")
  CALL @mth_cksum_test_expect

  ; ---- 256 bytes at address 0: ramp 0..255 ----
  MOVI r1,0
  MOVI r2,256
  MOVI r3,0
  CALL @mth_cksum_test_fill_ramp
  MOVI r1,0
  MOVI r2,256
  MOVI r3,0x9DC5
  MOVHI r3,0x811C
  MOVI r4,0x58C5
  MOVHI r4,0x90A4            ; FNV-1a32(0..255)
  CALL @mth_cksum_test_expect

  ; ---- deterministic repeat of the same block ----
  MOVI r1,0
  MOVI r2,256
  MOVI r3,0x9DC5
  MOVHI r3,0x811C
  MOVI r4,0x58C5
  MOVHI r4,0x90A4
  CALL @mth_cksum_test_expect

  ; ---- published vector: "foobar" ----
  LA r1,@mth_cksum_test_foobar
  SHL r1,r1,2                ; word index -> payload byte address
  MOVI r2,6
  MOVI r3,0x9DC5
  MOVHI r3,0x811C
  MOVI r4,0xF968
  MOVHI r4,0xBF9C
  CALL @mth_cksum_test_expect

  ; ---- published vector: "hello" ----
  LA r1,@mth_cksum_test_hello
  SHL r1,r1,2
  MOVI r2,5
  MOVI r3,0x9DC5
  MOVHI r3,0x811C
  MOVI r4,0x2CAB
  MOVHI r4,0x4F9F
  CALL @mth_cksum_test_expect

  ; ---- 256 bytes ending exactly at 8388608: 0x7FFF00..0x7FFFFF ----
  MOVI r1,0xFF00
  MOVHI r1,0x007F            ; 0x007FFF00
  MOVI r2,256
  MOVI r3,0
  CALL @mth_cksum_test_fill_ramp
  MOVI r1,0xFF00
  MOVHI r1,0x007F
  MOVI r2,256
  MOVI r3,0x9DC5
  MOVHI r3,0x811C
  MOVI r4,0x58C5
  MOVHI r4,0x90A4
  CALL @mth_cksum_test_expect

  ; ---- deterministic repeat at the root end ----
  MOVI r1,0xFF00
  MOVHI r1,0x007F
  MOVI r2,256
  MOVI r3,0x9DC5
  MOVHI r3,0x811C
  MOVI r4,0x58C5
  MOVHI r4,0x90A4
  CALL @mth_cksum_test_expect

  ; ---- one byte at the last root byte: 0x7FFFFF ----
  MOVI r1,0xFFFF
  MOVHI r1,0x007F
  MOVI r4,0x61               ; 'a'
  STB r4,r1,0
  MOVI r2,1
  MOVI r3,0x9DC5
  MOVHI r3,0x811C
  MOVI r4,0x292C
  MOVHI r4,0xE40C
  CALL @mth_cksum_test_expect

  ; ---- four bytes ending at the root end: "test" at 0x7FFFFC ----
  MOVI r1,0xFFFC
  MOVHI r1,0x007F            ; 0x007FFFFC
  MOVI r4,0x74
  STB r4,r1,0
  MOVI r4,0x65
  STB r4,r1,1
  MOVI r4,0x73
  STB r4,r1,2
  MOVI r4,0x74
  STB r4,r1,3
  MOVI r2,4
  MOVI r3,0x9DC5
  MOVHI r3,0x811C
  MOVI r4,0x71E5
  MOVHI r4,0xAFD0
  CALL @mth_cksum_test_expect

  ; ---- bounds rejection: start exactly at 8388608 ----
  MOVI r1,0
  MOVHI r1,0x0080
  MOVI r2,1
  MOVI r3,0x9DC5
  MOVHI r3,0x811C
  CALL @mth_cksum_test_reject

  ; ---- bounds rejection: last byte plus one more ----
  MOVI r1,0xFFFF
  MOVHI r1,0x007F            ; 0x007FFFFF
  MOVI r2,2
  MOVI r3,0x9DC5
  MOVHI r3,0x811C
  CALL @mth_cksum_test_reject

  ; ---- bounds rejection: end-256 plus 257 crosses the root end ----
  MOVI r1,0xFF00
  MOVHI r1,0x007F
  MOVI r2,0x0101             ; 257
  MOVI r3,0x9DC5
  MOVHI r3,0x811C
  CALL @mth_cksum_test_reject

  ; ---- wrap rejection: 0xFFFFFFFF + 1 ----
  MOVI r1,0xFFFF
  MOVHI r1,0xFFFF
  MOVI r2,1
  MOVI r3,0x9DC5
  MOVHI r3,0x811C
  CALL @mth_cksum_test_reject

  ; ---- wrap rejection: 0xFFFFFF00 + 0x200 ----
  MOVI r1,0xFF00
  MOVHI r1,0xFFFF
  MOVI r2,0x0200
  MOVI r3,0x9DC5
  MOVHI r3,0x811C
  CALL @mth_cksum_test_reject

  ; ---- wrap rejection: 0xFFFF0000 + 65536 ----
  MOVI r1,0
  MOVHI r1,0xFFFF
  MOVI r2,0
  MOVHI r2,1
  MOVI r3,0x9DC5
  MOVHI r3,0x811C
  CALL @mth_cksum_test_reject

  ; ---- length rejection: 65537 ----
  MOVI r1,0
  MOVI r2,1
  MOVHI r2,1                 ; 0x00010001
  MOVI r3,0x9DC5
  MOVHI r3,0x811C
  CALL @mth_cksum_test_reject

  ; ---- length rejection: 0xFFFFFFFF ----
  MOVI r1,0
  MOVI r2,0xFFFF
  MOVHI r2,0xFFFF
  MOVI r3,0x9DC5
  MOVHI r3,0x811C
  CALL @mth_cksum_test_reject

  MOVI r1,@mth_cksum_test_pass
  CALL @mth_cksum_test_puts
  HALT

mth_cksum_test_fail:
  MOVI r1,@mth_cksum_test_bad
  CALL @mth_cksum_test_puts
  HALT

; ---- Helpers ------------------------------------------------------------

; r1 = byte address, r2 = count, r3 = first value.
; Fills count bytes with (first + i) mod 256 via native byte stores.
mth_cksum_test_fill_ramp:
  ADD r4,r1,r2               ; end address
  ADD r5,r3,r0               ; current byte value
mth_cksum_test_fill_ramp_loop:
  STB r5,r1,0
  ADDI r1,r1,1
  ADDI r5,r5,1
  CMP r1,r4
  JMP[LT] @mth_cksum_test_fill_ramp_loop
  RET

; r1 = address, r2 = length, r3 = seed, r4 = expected checksum.
; Requires success, the exact checksum, and r5 == length.
mth_cksum_test_expect:
  ST r15,r0,@mth_cksum_test_ret
  ST r4,r0,@mth_cksum_test_exp_sum
  ST r2,r0,@mth_cksum_test_exp_len
  CALL @mth_mirror_block_checksum
  CMP r1,r13
  JMP[NE] @mth_cksum_test_fail
  LD r6,r0,@mth_cksum_test_exp_sum
  CMP r4,r6
  JMP[NE] @mth_cksum_test_fail
  LD r6,r0,@mth_cksum_test_exp_len
  CMP r5,r6
  JMP[NE] @mth_cksum_test_fail
  LD r15,r0,@mth_cksum_test_ret
  RET

; r1 = address, r2 = length. Requires r1=r4=r5=0 after the call.
mth_cksum_test_reject:
  ST r15,r0,@mth_cksum_test_ret
  CALL @mth_mirror_block_checksum
  CMP r1,r0
  JMP[NE] @mth_cksum_test_fail
  CMP r4,r0
  JMP[NE] @mth_cksum_test_fail
  CMP r5,r0
  JMP[NE] @mth_cksum_test_fail
  LD r15,r0,@mth_cksum_test_ret
  RET

mth_cksum_test_puts:
  MOVI r4,255
mth_cksum_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_cksum_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_cksum_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_cksum_test_puts_word

; ---- Data (word-addressed; byte addresses are label << 2) ----------------
.org 24576
mth_cksum_test_ret:
.word 0
mth_cksum_test_exp_sum:
.word 0
mth_cksum_test_exp_len:
.word 0
mth_cksum_test_foobar:
.str "foobar"
mth_cksum_test_hello:
.str "hello"
mth_cksum_test_pass:
.str "MTH MIRROR BLOCK CHECKSUM PASS\n"
mth_cksum_test_bad:
.str "MTH MIRROR BLOCK CHECKSUM FAIL\n"
