; MTH R2 radial energy/localization fixture — NaN16 only.
.org 0
JMP @mth_radial_energy_test_main
.include "../nan16/mth_radial_energy.nas"

mth_radial_energy_test_main:
  MOVI r13,1

  ; diag = 2.0, offdiag = -1.0, x = 1.0.
  LA r6,@mth_radial_energy_test_diag
  MOVI r7,0
  MOVHI r7,0x4000
  MOVI r8,0
mth_radial_energy_test_fill_diag:
  ST r7,r6,0
  ADD r6,r6,r13
  ADD r8,r8,r13
  MOVI r9,256
  CMP r8,r9
  JMP[LT] @mth_radial_energy_test_fill_diag

  LA r6,@mth_radial_energy_test_off
  MOVI r7,0
  MOVHI r7,0xBF80
  MOVI r8,0
mth_radial_energy_test_fill_off:
  ST r7,r6,0
  ADD r6,r6,r13
  ADD r8,r8,r13
  MOVI r9,255
  CMP r8,r9
  JMP[LT] @mth_radial_energy_test_fill_off

  CALL @mth_radial_energy_test_fill_one

  LA r1,@mth_radial_energy_test_diag
  LA r2,@mth_radial_energy_test_off
  LA r3,@mth_radial_energy_test_x
  LA r4,@mth_radial_energy_test_energy
  LA r5,@mth_radial_energy_test_loc
  CALL @mth_radial_energy
  CMP r1,r13
  JMP[NE] @mth_radial_energy_test_fail

  ; x=1 gives energy=2.0 and localization=1/256 (0x3B800000).
  LA r6,@mth_radial_energy_test_energy
  LD r6,r6,0
  MOVI r7,0
  MOVHI r7,0x4000
  CMP r6,r7
  JMP[NE] @mth_radial_energy_test_fail
  LA r6,@mth_radial_energy_test_loc
  LD r6,r6,0
  MOVI r7,0
  MOVHI r7,0x3B80
  CMP r6,r7
  JMP[NE] @mth_radial_energy_test_fail

  ; Zero x: energy=0, localization=0.
  CALL @mth_radial_energy_test_zero_x
  LA r1,@mth_radial_energy_test_diag
  LA r2,@mth_radial_energy_test_off
  LA r3,@mth_radial_energy_test_x
  LA r4,@mth_radial_energy_test_energy
  LA r5,@mth_radial_energy_test_loc
  CALL @mth_radial_energy
  LA r6,@mth_radial_energy_test_energy
  LD r6,r6,0
  CMP r6,r0
  JMP[NE] @mth_radial_energy_test_fail
  LA r6,@mth_radial_energy_test_loc
  LD r6,r6,0
  CMP r6,r0
  JMP[NE] @mth_radial_energy_test_fail

  ; x=e0: energy=2, localization=1.
  CALL @mth_radial_energy_test_zero_x
  LA r6,@mth_radial_energy_test_x
  MOVI r7,0
  MOVHI r7,0x3F80
  ST r7,r6,0
  LA r1,@mth_radial_energy_test_diag
  LA r2,@mth_radial_energy_test_off
  LA r3,@mth_radial_energy_test_x
  LA r4,@mth_radial_energy_test_energy
  LA r5,@mth_radial_energy_test_loc
  CALL @mth_radial_energy
  LA r6,@mth_radial_energy_test_energy
  LD r6,r6,0
  MOVI r7,0
  MOVHI r7,0x4000
  CMP r6,r7
  JMP[NE] @mth_radial_energy_test_fail
  LA r6,@mth_radial_energy_test_loc
  LD r6,r6,0
  MOVI r7,0
  MOVHI r7,0x3F80
  CMP r6,r7
  JMP[NE] @mth_radial_energy_test_fail

  ; x=e128: energy=2, localization=1.
  CALL @mth_radial_energy_test_zero_x
  LA r6,@mth_radial_energy_test_x
  MOVI r7,128
  ADD r6,r6,r7
  MOVI r7,0
  MOVHI r7,0x3F80
  ST r7,r6,0
  LA r1,@mth_radial_energy_test_diag
  LA r2,@mth_radial_energy_test_off
  LA r3,@mth_radial_energy_test_x
  LA r4,@mth_radial_energy_test_energy
  LA r5,@mth_radial_energy_test_loc
  CALL @mth_radial_energy
  LA r6,@mth_radial_energy_test_energy
  LD r6,r6,0
  MOVI r7,0
  MOVHI r7,0x4000
  CMP r6,r7
  JMP[NE] @mth_radial_energy_test_fail
  LA r6,@mth_radial_energy_test_loc
  LD r6,r6,0
  MOVI r7,0
  MOVHI r7,0x3F80
  CMP r6,r7
  JMP[NE] @mth_radial_energy_test_fail

  LA r1,@mth_radial_energy_test_pass
  CALL @mth_radial_energy_test_puts
  HALT

mth_radial_energy_test_fill_one:
  LA r6,@mth_radial_energy_test_x
  MOVI r7,0
  MOVHI r7,0x3F80
  MOVI r8,0
mth_radial_energy_test_fill_one_loop:
  ST r7,r6,0
  ADD r6,r6,r13
  ADD r8,r8,r13
  MOVI r9,256
  CMP r8,r9
  JMP[LT] @mth_radial_energy_test_fill_one_loop
  RET

mth_radial_energy_test_zero_x:
  LA r6,@mth_radial_energy_test_x
  MOVI r8,0
mth_radial_energy_test_zero_x_loop:
  ST r0,r6,0
  ADD r6,r6,r13
  ADD r8,r8,r13
  MOVI r9,256
  CMP r8,r9
  JMP[LT] @mth_radial_energy_test_zero_x_loop
  RET

mth_radial_energy_test_fail:
  LA r1,@mth_radial_energy_test_fail_msg
  CALL @mth_radial_energy_test_puts
  HALT

mth_radial_energy_test_puts:
  MOVI r4,255
mth_radial_energy_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_radial_energy_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_radial_energy_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_radial_energy_test_puts_word

.org 512
mth_radial_energy_test_diag:
.word 0
.org 1024
mth_radial_energy_test_off:
.word 0
.org 1280
mth_radial_energy_test_x:
.word 0
.org 1536
mth_radial_energy_test_energy:
.word 0
mth_radial_energy_test_loc:
.word 0
mth_radial_energy_test_pass:
.word 0x2048544D,0x49444152,0x45204C41,0x4752454E,0x41502059,0x00005353
mth_radial_energy_test_fail_msg:
.word 0x4C494146,0
