; Native NaN16 four-tier 64-bit logical volume-identity codec.
; One shared architecture for rawroute BS0 / MC0 / SC0 / GM0 mounts.
; 64-bit NaN identity = 0x7FF1_4E1T_SSCC_F17F (upper/lower U32).
; Both head types are +sNaN (far F17F byte-swapped, near 7FF1).
; T=1..4, SS=shard 0..255, CC=CRC-8/ATM over [4E,1T,SS].
; Logical identity is immutable across Koyeb physical-volume relocation.
; CRC detects corruption ONLY, never replaces signature/ACL/lease.
; No filesystem, route-mount, model, or external tensor memory mutation.
;
; mth_nan_volume64_encode: r1=tier 1..4; r2=shard 0..255, r13=1.
;   success r1=raw_hi32, r2=raw_lo32, r3=CRC8, r4=1
;   reject  r1=r2=r3=r4=0.
; mth_nan_volume64_validate: r1=raw_hi32,r2=raw_lo32,r13=1.
;   success r3=tier,r4=shard,r5=CRC8,r6=1,r7=0
;   reject r3=r4=r5=r6=0,r7=1 heads/magic/version,2 tier,3 CRC.
; Both are non-allocating non-reentrant leaf-like guest routines; the
; CRC helper uses the saved r15 link in r12, r13 must equal one.

mth_nan_volume64_crc8:
  MOVI r3,0
  MOVI r8,0
mth_volume64_crc_byte:
  MOVI r5,0x4E
  CMP r8,r0
  JMP[EQ] @mth_volume64_crc_byte_ready
  MOVI r5,0x10
  ADD r5,r5,r1
  MOVI r6,1
  CMP r8,r6
  JMP[EQ] @mth_volume64_crc_byte_ready
  ADD r5,r2,r0
mth_volume64_crc_byte_ready:
  BOOL.6 r3,r3,r5
  MOVI r6,8
mth_volume64_crc_bit:
  SHR r7,r3,7
  SHL r3,r3,1
  MOVI r11,255
  BOOL.8 r3,r3,r11
  CMP r7,r0
  JMP[EQ] @mth_volume64_crc_no_xor
  MOVI r11,7
  BOOL.6 r3,r3,r11
mth_volume64_crc_no_xor:
  SUB r6,r6,r13
  CMP r6,r0
  JMP[GT] @mth_volume64_crc_bit
  ADDI r8,r8,1
  MOVI r11,3
  CMP r8,r11
  JMP[LT] @mth_volume64_crc_byte
  RET

mth_nan_volume64_encode:
  MOVI r0,0
  CMP r1,r13
  JMP[LT] @mth_volume64_encode_deny
  MOVI r4,4
  CMP r1,r4
  JMP[GT] @mth_volume64_encode_deny
  SHR r4,r2,8
  CMP r4,r0
  JMP[NE] @mth_volume64_encode_deny
  ADD r12,r15,r0
  CALL @mth_nan_volume64_crc8
  ADD r15,r12,r0
  ; hi U32 is 7FF1_4E1T.
  MOVI r4,0x4E10
  MOVHI r4,0x7FF1
  ADD r1,r4,r1
  ; lo U32 is SSCC_F17F.
  SHL r2,r2,24
  SHL r4,r3,16
  BOOL.14 r2,r2,r4
  MOVI r4,0xF17F
  BOOL.14 r2,r2,r4
  MOVI r4,1
  RET
mth_volume64_encode_deny:
  MOVI r1,0
  MOVI r2,0
  MOVI r3,0
  MOVI r4,0
  RET

mth_nan_volume64_validate:
  MOVI r0,0
  ; Both heads, magic and format are exact.
  SHR r8,r1,16
  MOVI r9,0x7FF1
  CMP r8,r9
  JMP[NE] @mth_volume64_bad_header
  MOVI r9,0xFFFF
  BOOL.8 r8,r2,r9
  MOVI r9,0xF17F
  CMP r8,r9
  JMP[NE] @mth_volume64_bad_header
  MOVI r9,0xFFFF
  BOOL.8 r8,r1,r9
  MOVI r9,0xFFF0
  BOOL.8 r8,r8,r9
  MOVI r9,0x4E10
  CMP r8,r9
  JMP[NE] @mth_volume64_bad_header
  MOVI r9,15
  BOOL.8 r3,r1,r9             ; decoded tier
  CMP r3,r13
  JMP[LT] @mth_volume64_bad_tier
  MOVI r9,4
  CMP r3,r9
  JMP[GT] @mth_volume64_bad_tier
  SHR r4,r2,24
  SHR r5,r2,16
  MOVI r9,255
  BOOL.8 r5,r5,r9             ; actual CRC
  ADD r14,r5,r0
  ADD r1,r3,r0                ; tier into CRC function
  ADD r2,r4,r0                ; shard into CRC function
  ADD r12,r15,r0
  CALL @mth_nan_volume64_crc8
  ADD r15,r12,r0
  CMP r3,r14
  JMP[NE] @mth_volume64_bad_crc
  ADD r5,r3,r0
  ADD r3,r1,r0
  MOVI r6,1
  MOVI r7,0
  RET
mth_volume64_bad_header:
  MOVI r7,1
  JMP @mth_volume64_validate_deny
mth_volume64_bad_tier:
  MOVI r7,2
  JMP @mth_volume64_validate_deny
mth_volume64_bad_crc:
  MOVI r7,3
mth_volume64_validate_deny:
  MOVI r3,0
  MOVI r4,0
  MOVI r5,0
  MOVI r6,0
  RET
