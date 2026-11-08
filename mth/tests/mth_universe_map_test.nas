; MTH full 8 MiB universe map fixture — NaN16 only.
;
; The fixture exhaustively walks all 256 fixed-head points and all 32,640
; mirror-pair points:
;   * every head maps to its page and records word 0;
;   * head 0 is the NANNET0 alias on page 255;
;   * every mirror pair maps to page n%255 and the two-word slot
;     3840 + 2*(n/255);
;   * all 256 pages are covered, pages 0..254 receive exactly 128 mirror
;     records, and page 255 receives only the NANNET0 head;
;   * every accepted guest word is inside the 8 MiB universe;
;   * layer 0..9 is echoed, while layer 10 and cell 32896 are rejected.
;
; No host arithmetic supplies expected values. The expected page/slot pair is
; advanced incrementally in the guest and compared with the kernel result.

.org 0
JMP @mth_umap_main
.include "../nan16/mth_universe_map.nas"

mth_umap_main:
  MOVI r13,1

  ; Clear both counter arrays and the incremental expected page/slot.
  MOVI r1,@mth_umap_head_counts
  MOVI r2,256
  MOVI r4,0
  CALL @mth_umap_fill
  MOVI r1,@mth_umap_mp_counts
  MOVI r2,256
  MOVI r4,0
  CALL @mth_umap_fill
  ST r4,r0,@mth_umap_exp_page
  ST r4,r0,@mth_umap_exp_slot

  ; ---- Fixed heads 0..255 ----
  MOVI r14,0
mth_umap_head_loop:
  ADD r1,r14,r0
  MOVI r2,0
  CALL @mth_universe_map
  CMP r1,r13
  JMP[NE] @mth_umap_fail
  CMP r5,r0
  JMP[NE] @mth_umap_fail
  CMP r6,r14
  JMP[NE] @mth_umap_fail
  CMP r7,r0
  JMP[NE] @mth_umap_fail
  CMP r3,r0
  JMP[NE] @mth_umap_fail

  CMP r14,r0
  JMP[EQ] @mth_umap_head_nannet_page
  SUB r8,r14,r13
  JMP @mth_umap_head_page_ready
mth_umap_head_nannet_page:
  MOVI r8,255
mth_umap_head_page_ready:
  CMP r2,r8
  JMP[NE] @mth_umap_fail
  ADD r9,r4,r0
  SHL r8,r2,12
  CMP r9,r8
  JMP[NE] @mth_umap_fail

  MOVI r8,@mth_umap_head_counts
  ADD r8,r8,r2
  LD r9,r8,0
  ADD r9,r9,r13
  ST r9,r8,0

  ADD r14,r14,r13
  MOVI r8,256
  CMP r14,r8
  JMP[LT] @mth_umap_head_loop

  ; ---- Mirror pairs 0..32639 ----
  MOVI r14,0
mth_umap_mp_loop:
  MOVI r1,256
  ADD r1,r1,r14
  MOVI r2,0
  CALL @mth_universe_map
  CMP r1,r13
  JMP[NE] @mth_umap_fail
  CMP r5,r13
  JMP[NE] @mth_umap_fail
  CMP r6,r14
  JMP[NE] @mth_umap_fail
  CMP r7,r0
  JMP[NE] @mth_umap_fail

  LD r8,r0,@mth_umap_exp_page
  CMP r2,r8
  JMP[NE] @mth_umap_fail
  LD r8,r0,@mth_umap_exp_slot
  SHL r8,r8,1
  MOVI r9,3840
  ADD r8,r8,r9
  CMP r3,r8
  JMP[NE] @mth_umap_fail
  SHL r8,r2,12
  ADD r8,r8,r3
  CMP r4,r8
  JMP[NE] @mth_umap_fail

  MOVI r8,@mth_umap_mp_counts
  ADD r8,r8,r2
  LD r9,r8,0
  ADD r9,r9,r13
  ST r9,r8,0

  ; Advance expected page/slot exactly as n increases.
  LD r8,r0,@mth_umap_exp_page
  ADD r8,r8,r13
  MOVI r9,255
  CMP r8,r9
  JMP[LT] @mth_umap_mp_store_page
  MOVI r8,0
  LD r9,r0,@mth_umap_exp_slot
  ADD r9,r9,r13
  ST r9,r0,@mth_umap_exp_slot
mth_umap_mp_store_page:
  ST r8,r0,@mth_umap_exp_page

  ADD r14,r14,r13
  MOVI r8,32640
  CMP r14,r8
  JMP[LT] @mth_umap_mp_loop

  ; ---- Coverage counters ----
  MOVI r14,0
mth_umap_check_heads:
  MOVI r8,@mth_umap_head_counts
  ADD r8,r8,r14
  LD r9,r8,0
  CMP r9,r13
  JMP[NE] @mth_umap_fail
  ADD r14,r14,r13
  MOVI r8,256
  CMP r14,r8
  JMP[LT] @mth_umap_check_heads

  MOVI r14,0
mth_umap_check_mps:
  MOVI r8,@mth_umap_mp_counts
  ADD r8,r8,r14
  LD r9,r8,0
  MOVI r10,255
  CMP r14,r10
  JMP[EQ] @mth_umap_check_nannet_page
  MOVI r10,128
  CMP r9,r10
  JMP[NE] @mth_umap_fail
  JMP @mth_umap_check_next_page
mth_umap_check_nannet_page:
  CMP r9,r0
  JMP[NE] @mth_umap_fail
mth_umap_check_next_page:
  ADD r14,r14,r13
  MOVI r8,256
  CMP r14,r8
  JMP[LT] @mth_umap_check_mps

  ; ---- Layer echo and boundary checks ----
  ; NANNET0 head 0: page 255, word 0, guest word 255*4096.
  MOVI r1,0
  MOVI r2,9
  CALL @mth_universe_map
  CMP r1,r13
  JMP[NE] @mth_umap_fail
  MOVI r8,255
  CMP r2,r8
  JMP[NE] @mth_umap_fail
  CMP r3,r0
  JMP[NE] @mth_umap_fail
  MOVI r8,0xF000
  MOVHI r8,0x000F
  CMP r4,r8
  JMP[NE] @mth_umap_fail
  CMP r5,r0
  JMP[NE] @mth_umap_fail
  CMP r6,r0
  JMP[NE] @mth_umap_fail
  MOVI r8,9
  CMP r7,r8
  JMP[NE] @mth_umap_fail

  ; Head 255: page 254, word 0, guest word 254*4096.
  MOVI r1,255
  MOVI r2,9
  CALL @mth_universe_map
  CMP r1,r13
  JMP[NE] @mth_umap_fail
  MOVI r8,254
  CMP r2,r8
  JMP[NE] @mth_umap_fail
  CMP r3,r0
  JMP[NE] @mth_umap_fail
  MOVI r8,0xE000
  MOVHI r8,0x000F
  CMP r4,r8
  JMP[NE] @mth_umap_fail
  MOVI r8,255
  CMP r6,r8
  JMP[NE] @mth_umap_fail
  MOVI r8,9
  CMP r7,r8
  JMP[NE] @mth_umap_fail

  ; Mirror pair 0: page 0, slot 0, word 3840.
  MOVI r1,256
  MOVI r2,9
  CALL @mth_universe_map
  CMP r1,r13
  JMP[NE] @mth_umap_fail
  CMP r2,r0
  JMP[NE] @mth_umap_fail
  MOVI r8,3840
  CMP r3,r8
  JMP[NE] @mth_umap_fail
  CMP r4,r8
  JMP[NE] @mth_umap_fail
  CMP r5,r13
  JMP[NE] @mth_umap_fail
  CMP r6,r0
  JMP[NE] @mth_umap_fail
  MOVI r8,9
  CMP r7,r8
  JMP[NE] @mth_umap_fail

  ; Final mirror pair 32639: page 254, slot 127, word 4094.
  MOVI r1,32895
  MOVI r2,9
  CALL @mth_universe_map
  CMP r1,r13
  JMP[NE] @mth_umap_fail
  MOVI r8,254
  CMP r2,r8
  JMP[NE] @mth_umap_fail
  MOVI r8,4094
  CMP r3,r8
  JMP[NE] @mth_umap_fail
  MOVI r8,0xEFFE
  MOVHI r8,0x000F
  CMP r4,r8
  JMP[NE] @mth_umap_fail
  MOVI r8,32639
  CMP r6,r8
  JMP[NE] @mth_umap_fail
  MOVI r8,9
  CMP r7,r8
  JMP[NE] @mth_umap_fail

  ; Cell 32896 and layer 10 must be rejected.
  MOVI r1,32896
  MOVI r2,0
  CALL @mth_universe_map
  CMP r1,r0
  JMP[NE] @mth_umap_fail
  MOVI r1,0
  MOVI r2,10
  CALL @mth_universe_map
  CMP r1,r0
  JMP[NE] @mth_umap_fail

  MOVI r1,@mth_umap_pass
  CALL @mth_umap_puts
  HALT

mth_umap_fail:
  MOVI r1,@mth_umap_bad
  CALL @mth_umap_puts
  HALT

; r1=destination, r2=count, r4=value. Clobbers r1,r2.
mth_umap_fill:
  ST r4,r1,0
  ADD r1,r1,r13
  SUB r2,r2,r13
  JMP[NE] @mth_umap_fill
  RET

; r1=NUL-terminated string; writes bytes through PUTC.
mth_umap_puts:
  MOVI r4,255
mth_umap_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_umap_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_umap_puts_byte
  ADD r1,r1,r13
  JMP @mth_umap_puts_word

; ---- data ----
.org 20000
mth_umap_head_counts:
.org 20256
mth_umap_mp_counts:
.org 20512
mth_umap_exp_page:
.word 0
mth_umap_exp_slot:
.word 0
mth_umap_pass:
.str "MTH UNIVERSE MAP PASS\n"
mth_umap_bad:
.str "MTH UNIVERSE MAP FAIL\n"
