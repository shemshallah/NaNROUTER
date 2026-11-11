; Exhaustive guest proof for one four-tier NaN16 64-bit volume codec.
; 4 tiers x 256 shards: round-trip and same-type +sNaN heads.
.org 0
JMP @v64_test_main
.include "../nan16/mth_nan_volume_address64.nas"

v64_test_main:
  MOVI r0,0
  MOVI r13,1
  MOVI r9,1
  ST r9,r0,@v64_tier
v64_test_tier_loop:
  MOVI r9,0
  ST r9,r0,@v64_shard
v64_test_shard_loop:
  LD r1,r0,@v64_tier
  LD r2,r0,@v64_shard
  CALL @mth_nan_volume64_encode
  CMP r4,r13
  JMP[NE] @v64_test_fail
  ; Exact immutable near head and high payload magic+format+tier.
  MOVI r8,0x4E10
  MOVHI r8,0x7FF1
  LD r9,r0,@v64_tier
  ADD r8,r8,r9
  CMP r1,r8
  JMP[NE] @v64_test_fail
  MOVI r8,0xFFFF
  BOOL.8 r9,r2,r8
  MOVI r8,0xF17F
  CMP r9,r8
  JMP[NE] @v64_test_fail

  ST r1,r0,@v64_raw_hi
  ST r2,r0,@v64_raw_lo
  CALL @mth_nan_volume64_validate
  CMP r6,r13
  JMP[NE] @v64_test_fail
  CMP r7,r0
  JMP[NE] @v64_test_fail
  LD r8,r0,@v64_tier
  CMP r3,r8
  JMP[NE] @v64_test_fail
  LD r8,r0,@v64_shard
  CMP r4,r8
  JMP[NE] @v64_test_fail
  ; Compare the CRC against the stored payload byte.
  LD r8,r0,@v64_raw_lo
  SHR r8,r8,16
  MOVI r9,255
  BOOL.8 r8,r8,r9
  CMP r5,r8
  JMP[NE] @v64_test_fail

  ; Independent pinned canonical shader-zero 64-bit vectors.
  LD r9,r0,@v64_shard
  CMP r9,r0
  JMP[NE] @v64_test_next_shard
  LD r8,r0,@v64_tier
  MOVI r11,0xE8
  MOVI r9,1
  CMP r8,r9
  JMP[EQ] @v64_test_oracle
  MOVI r11,0xD7
  MOVI r9,2
  CMP r8,r9
  JMP[EQ] @v64_test_oracle
  MOVI r11,0xC2
  MOVI r9,3
  CMP r8,r9
  JMP[EQ] @v64_test_oracle
  MOVI r11,0xA9
v64_test_oracle:
  LD r8,r0,@v64_raw_lo
  SHR r8,r8,16
  MOVI r9,255
  BOOL.8 r8,r8,r9
  CMP r8,r11
  JMP[NE] @v64_test_fail

v64_test_next_shard:
  LD r9,r0,@v64_shard
  ADDI r9,r9,1
  MOVI r10,256
  CMP r9,r10
  JMP[GE] @v64_test_next_tier
  ST r9,r0,@v64_shard
  JMP @v64_test_shard_loop
v64_test_next_tier:
  LD r9,r0,@v64_tier
  ADDI r9,r9,1
  MOVI r10,5
  CMP r9,r10
  JMP[GE] @v64_test_invalid
  ST r9,r0,@v64_tier
  JMP @v64_test_tier_loop

v64_test_invalid:
  ; Bad tier, noncanonical shard or type cannot create a valid identity.
  MOVI r1,0
  MOVI r2,3
  CALL @mth_nan_volume64_encode
  CMP r4,r0
  JMP[NE] @v64_test_fail
  MOVI r1,5
  MOVI r2,3
  CALL @mth_nan_volume64_encode
  CMP r4,r0
  JMP[NE] @v64_test_fail
  MOVI r1,1
  MOVI r2,256
  CALL @mth_nan_volume64_encode
  CMP r4,r0
  JMP[NE] @v64_test_fail
  ; BS0 shard0 oracle 0x7FF1_4E11_00E8_F17F.
  MOVI r1,0x4E11
  MOVHI r1,0x7FF1
  MOVI r2,0xF17F
  MOVHI r2,0x00E9          ; CRC corrupted E8->E9
  CALL @mth_nan_volume64_validate
  CMP r6,r0
  JMP[NE] @v64_test_fail
  MOVI r10,3
  CMP r7,r10
  JMP[NE] @v64_test_fail
  MOVI r1,0x4E11
  MOVHI r1,0x7FF1
  MOVI r2,0xF170           ; corrupted far +sNaN head
  MOVHI r2,0x00E8
  CALL @mth_nan_volume64_validate
  CMP r6,r0
  JMP[NE] @v64_test_fail
  MOVI r10,1
  CMP r7,r10
  JMP[NE] @v64_test_fail
  MOVI r1,0x4E15          ; unsupported tier5
  MOVHI r1,0x7FF1
  MOVI r2,0xF17F
  MOVHI r2,0x00E8
  CALL @mth_nan_volume64_validate
  CMP r6,r0
  JMP[NE] @v64_test_fail
  MOVI r10,2
  CMP r7,r10
  JMP[NE] @v64_test_fail
  MOVI r1,0x4F11          ; bad magic/version
  MOVHI r1,0x7FF1
  MOVI r2,0xF17F
  MOVHI r2,0x00E8
  CALL @mth_nan_volume64_validate
  CMP r6,r0
  JMP[NE] @v64_test_fail
  MOVI r10,1
  CMP r7,r10
  JMP[NE] @v64_test_fail

  MOVI r1,@v64_test_pass
  CALL @v64_puts
  HALT
v64_test_fail:
  MOVI r1,@v64_test_bad
  CALL @v64_puts
  HALT
v64_puts:
  MOVI r4,255
v64_puts_word:
  LD r2,r1,0
  MOVI r3,4
v64_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @v64_puts_byte
  ADD r1,r1,r13
  JMP @v64_puts_word
v64_tier:
  .word 1
v64_shard:
  .word 0
v64_raw_hi:
  .word 0
v64_raw_lo:
  .word 0
v64_test_pass:
.str "MTH NAN VOLUME64 ALL SHARDS PASS\n"
v64_test_bad:
.str "MTH NAN VOLUME64 ALL SHARDS FAIL\n"
