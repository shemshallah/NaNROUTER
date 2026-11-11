; NaN16 global 256-vertex incidence/coboundary test.
; Three-edge oriented 0→1→2→0 flow yields zero divergence
; at each of the 256 vertices and curl +3 (reverse orientation -3).
.org 0
JMP @mth_gh_test_main
.include "../nan16/mth_global_hodge256_f32.nas"

mth_gh_test_main:
  MOVI r0,0
  MOVI r13,1
  ; Canonical flat indices: (0,1)=0; (0,2)=1; (1,2)=255.
  MOVI r10,0
  MOVHI r10,0x3F80         ; +1
  ST r10,r0,@mth_gh_flows
  MOVI r11,@mth_gh_flows
  ADDI r11,r11,255
  ST r10,r11,0
  MOVI r10,0
  MOVHI r10,0xBF80         ; -1 on low0→high2, so 2→0 is +1
  ST r10,r0,@mth_gh_flows+1

  MOVI r10,0
  ST r10,r0,@mth_gh_triads
  MOVI r10,1
  ST r10,r0,@mth_gh_triads+1
  MOVI r10,2
  ST r10,r0,@mth_gh_triads+2

  MOVI r1,@mth_gh_flows
  MOVI r2,@mth_gh_triads
  MOVI r3,1
  MOVI r4,@mth_gh_div
  MOVI r5,@mth_gh_curl
  MOVI r6,@mth_gh_divscratch
  MOVI r7,@mth_gh_curlscratch
  CALL @mth_global_hodge256_f32
  CMP r1,r13
  JMP[NE] @mth_gh_test_fail
  MOVI r10,0
  MOVHI r10,0x4040       ; +3 curl
  LD r11,r0,@mth_gh_curl
  CMP r11,r10
  JMP[NE] @mth_gh_test_fail

  MOVI r8,0
mth_gh_zero_div_check:
  MOVI r12,@mth_gh_div
  ADD r12,r12,r8
  LD r10,r12,0
  FCMP r10,r0
  JMP[NE] @mth_gh_test_fail
  ADDI r8,r8,1
  MOVI r12,256
  CMP r8,r12
  JMP[LT] @mth_gh_zero_div_check

  ; Reverse triangle (0,2,1) to verify oriented curl sign.
  MOVI r10,2
  ST r10,r0,@mth_gh_triads+1
  MOVI r10,1
  ST r10,r0,@mth_gh_triads+2
  MOVI r1,@mth_gh_flows
  MOVI r2,@mth_gh_triads
  MOVI r3,1
  MOVI r4,@mth_gh_div
  MOVI r5,@mth_gh_curl
  MOVI r6,@mth_gh_divscratch
  MOVI r7,@mth_gh_curlscratch
  CALL @mth_global_hodge256_f32
  CMP r1,r13
  JMP[NE] @mth_gh_test_fail
  MOVI r10,0
  MOVHI r10,0xC040       ; -3 curl
  LD r11,r0,@mth_gh_curl
  CMP r11,r10
  JMP[NE] @mth_gh_test_fail

  ; Non-finite at the LAST canonical pair rejects before publishing.
  MOVI r10,0
  MOVHI r10,0x7FC0
  MOVI r11,@mth_gh_flows
  ADDI r11,r11,32639
  ST r10,r11,0
  MOVI r1,@mth_gh_flows
  MOVI r2,@mth_gh_triads
  MOVI r3,1
  MOVI r4,@mth_gh_div
  MOVI r5,@mth_gh_curl
  MOVI r6,@mth_gh_divscratch
  MOVI r7,@mth_gh_curlscratch
  CALL @mth_global_hodge256_f32
  CMP r1,r0
  JMP[NE] @mth_gh_test_fail
  MOVI r10,0
  MOVHI r10,0xC040
  LD r11,r0,@mth_gh_curl
  CMP r11,r10
  JMP[NE] @mth_gh_test_fail

  ; Void head 255 cannot carry active pair flow.
  MOVI r10,0
  MOVI r11,@mth_gh_flows
  ADDI r11,r11,32639
  ST r10,r11,0              ; restore poisoned last pair
  MOVI r10,0
  MOVHI r10,0x3F80         ; +1.0 on edge(0,255) is forbidden
  MOVI r11,@mth_gh_flows
  ADDI r11,r11,254
  ST r10,r11,0
  MOVI r1,@mth_gh_flows
  MOVI r2,@mth_gh_triads
  MOVI r3,1
  MOVI r4,@mth_gh_div
  MOVI r5,@mth_gh_curl
  MOVI r6,@mth_gh_divscratch
  MOVI r7,@mth_gh_curlscratch
  CALL @mth_global_hodge256_f32
  CMP r1,r0
  JMP[NE] @mth_gh_test_fail
  MOVI r10,0
  MOVHI r10,0xC040
  LD r11,r0,@mth_gh_curl
  CMP r11,r10
  JMP[NE] @mth_gh_test_fail
  MOVI r10,0
  MOVI r11,@mth_gh_flows
  ADDI r11,r11,254
  ST r10,r11,0

  ; 255 is not a valid simplicial face vertex, even with zero pair flow.
  MOVI r10,255
  ST r10,r0,@mth_gh_triads+1
  MOVI r1,@mth_gh_flows
  MOVI r2,@mth_gh_triads
  MOVI r3,1
  MOVI r4,@mth_gh_div
  MOVI r5,@mth_gh_curl
  MOVI r6,@mth_gh_divscratch
  MOVI r7,@mth_gh_curlscratch
  CALL @mth_global_hodge256_f32
  CMP r1,r0
  JMP[NE] @mth_gh_test_fail
  MOVI r10,0
  MOVHI r10,0xC040
  LD r11,r0,@mth_gh_curl
  CMP r11,r10
  JMP[NE] @mth_gh_test_fail

  MOVI r1,@mth_gh_test_pass
  CALL @mth_gh_puts
  HALT
mth_gh_test_fail:
  MOVI r1,@mth_gh_test_bad
  CALL @mth_gh_puts
  HALT
mth_gh_puts:
  MOVI r4,255
mth_gh_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_gh_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_gh_puts_byte
  ADD r1,r1,r13
  JMP @mth_gh_puts_word
mth_gh_test_pass:
.str "MTH GLOBAL HODGE256 PASS\n"
mth_gh_test_bad:
.str "MTH GLOBAL HODGE256 FAIL\n"

.org 8192
mth_gh_triads:
.word 0,0,0
.org 8256
mth_gh_div:
.word 0
.org 8540
mth_gh_curl:
.word 0
.org 8600
mth_gh_divscratch:
.word 0
.org 8900
mth_gh_curlscratch:
.word 0
.org 10000
mth_gh_flows:
.word 0
