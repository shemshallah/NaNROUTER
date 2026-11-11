; Fully-native 28-symbol masked CE guest regression for 48M hybrid bridge.
; No Python/C model evaluation. 28 real character/EOS classes, 228 -inf
; pads and head255 void. Live candidate mirror index (0,2,4).
.org 0
JMP @mth_mask_main
.include "../nan16/mth_hypertensor256_mirror_arena_map.nas"
.include "../nan16/mth_lm_cross_entropy256_f32.nas"
.include "../nan16/mth_trihead_decoder_ce_feedback_f32.nas"

mth_mask_main:
  MOVI r0,0
  MOVI r13,1
  MOVI r11,0
  MOVHI r11,0xBF80      ; -1 float32 for all 28 legal classes
  MOVI r8,0
mth_mask_fill_real:
  MOVI r9,@mth_mask_record
  ADD r9,r9,r8
  ST r11,r9,0
  ADDI r8,r8,1
  MOVI r10,28
  CMP r8,r10
  JMP[LT] @mth_mask_fill_real

  MOVI r11,0
  MOVHI r11,0xFF80      ; exactly -infinity, masked channels
mth_mask_fill_void:
  MOVI r9,@mth_mask_record
  ADD r9,r9,r8
  ST r11,r9,0
  ADDI r8,r8,1
  MOVI r10,256
  CMP r8,r10
  JMP[LT] @mth_mask_fill_void

  ; Chosen real symbol class 4 is observed, logits[4]=0.
  MOVI r11,4
  ST r0,r0,@mth_mask_record+4
  ST r11,r0,@mth_mask_record+256
  ST r13,r0,@mth_mask_permissions+1

  ; Run DEVELOPMENT native CE admission with a +0.5 class residual.
  MOVI r1,@mth_mask_proposal
  MOVI r2,@mth_mask_permissions
  MOVI r3,@mth_mask_credit
  MOVI r4,@mth_mask_tile
  MOVI r5,@mth_mask_record
  MOVI r6,1
  MOVI r7,@mth_mask_stats
  MOVI r8,@mth_mask_work
  MOVI r9,7
  MOVI r10,1
  CALL @mth_trihead_decoder_ce_feedback_f32
  CMP r1,r13
  JMP[NE] @mth_mask_fail
  LD r11,r0,@mth_mask_stats+2
  CMP r11,r13
  JMP[NE] @mth_mask_fail
  LD r11,r0,@mth_mask_tile+1
  MOVI r12,0
  MOVHI r12,0x3F00
  CMP r11,r12                ; candidate gained exactly +0.5
  JMP[NE] @mth_mask_fail
  LD r11,r0,@mth_mask_stats
  LD r12,r0,@mth_mask_stats+1
  FCMP r12,r11
  JMP[GE] @mth_mask_fail

  ; Independently evaluate TEST; zero writes are allowed to credit/tile.
  MOVI r1,@mth_mask_proposal
  MOVI r2,@mth_mask_permissions
  MOVI r3,@mth_mask_credit
  MOVI r4,@mth_mask_tile
  MOVI r5,@mth_mask_record
  MOVI r6,1
  MOVI r7,@mth_mask_stats
  MOVI r8,@mth_mask_work
  MOVI r9,7
  MOVI r10,0
  CALL @mth_trihead_decoder_ce_feedback_f32
  CMP r1,r13
  JMP[NE] @mth_mask_fail
  LD r11,r0,@mth_mask_tile+1
  MOVI r12,0
  MOVHI r12,0x3F00
  CMP r11,r12
  JMP[NE] @mth_mask_fail
  LD r11,r0,@mth_mask_credit+1
  MOVI r12,0
  MOVHI r12,0x3F80
  CMP r11,r12
  JMP[NE] @mth_mask_fail

  ; Make the REAL target point at an unsupported -infinity class.
  ; Preflight must now fail before writing any output, tensor or credit.
  MOVI r11,28
  ST r11,r0,@mth_mask_record+256
  MOVI r11,777
  ST r11,r0,@mth_mask_stats
  MOVI r1,@mth_mask_proposal
  MOVI r2,@mth_mask_permissions
  MOVI r3,@mth_mask_credit
  MOVI r4,@mth_mask_tile
  MOVI r5,@mth_mask_record
  MOVI r6,1
  MOVI r7,@mth_mask_stats
  MOVI r8,@mth_mask_work
  MOVI r9,7
  MOVI r10,1
  CALL @mth_trihead_decoder_ce_feedback_f32
  CMP r1,r0
  JMP[NE] @mth_mask_fail
  LD r11,r0,@mth_mask_stats
  MOVI r12,777
  CMP r11,r12
  JMP[NE] @mth_mask_fail
  LD r11,r0,@mth_mask_tile+1
  MOVI r12,0
  MOVHI r12,0x3F00
  CMP r11,r12
  JMP[NE] @mth_mask_fail

  MOVI r1,@mth_mask_pass
  CALL @mth_mask_puts
  HALT
mth_mask_fail:
  MOVI r1,@mth_mask_bad
  CALL @mth_mask_puts
  HALT

mth_mask_puts:
  MOVI r4,255
mth_mask_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_mask_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_mask_puts_byte
  ADD r1,r1,r13
  JMP @mth_mask_puts_word

.org 20000
mth_mask_record:
.word 0
.org 20500
mth_mask_proposal:
.word 1,0,2,4,0x3F000000,0
mth_mask_tile:
.word 5104,0,7
mth_mask_permissions:
.word 0
.org 21000
mth_mask_credit:
.word 0,0x3F800000
mth_mask_stats:
.word 0,0,0,0,0,0
mth_mask_pass:
.str "MTH MASKED 28-CLASS REAL DECODER CE PASS\n"
mth_mask_bad:
.str "MTH MASKED 28-CLASS REAL DECODER CE FAIL\n"
.org 30000
mth_mask_work:
.word 0
