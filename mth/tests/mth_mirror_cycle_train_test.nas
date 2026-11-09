; MTH content-dependent mirror-cycle training fixture — NaN16 only.
;
; The fixture leases base head 1 and uses the native 16x16 cycle bank:
;   (0,a), (a,a+1), (0,b), a=1,3,5,...,31.
;
; It zeroes the bank, trains one-hot x[0]=1 against target[c]=1 with gate=1
; and lr=0.25, and verifies:
;   * first-step SSE is exactly 16.0;
;   * all sixteen predictions are 0.25 after the first step;
;   * for eight further native steps SSE decreases strictly each time;
;   * final predictions are all above 0.8;
;   * the lane-0/lane-1 mirror sum is zero for all three edges and all 16
;     channels;
;   * domain rejections for x, target, gate, lr, base head, and a non-finite
;     bank edge, plus prediction base rejection.
;
; No host math is used at runtime; all arithmetic is in the native kernel.

.org 0
JMP @mth_cycle_test_main
.include "../nan16/mth_mirror_cycle_train_step_f32.nas"
.include "../nan16/mth_mirror_cycle_predict16_f32.nas"

mth_cycle_test_main:
  MOVI r0,0
  MOVI r13,1

  CALL @mth_cycle_test_zero_bank
  CALL @mth_cycle_test_init_vectors

  ; ---- first training step ----
  CALL @mth_cycle_test_train
  CMP r1,r13
  JMP[NE] @mth_cycle_test_fail
  CMP r9,r0
  JMP[NE] @mth_cycle_test_fail
  ADD r1,r7,r0
  MOVI r2,0
  MOVHI r2,0x4180            ; 16.0
  MOVI r3,0
  MOVHI r3,0x3586            ; 1e-6
  CALL @mth_cycle_test_near
  CMP r1,r13
  JMP[NE] @mth_cycle_test_fail
  ST r7,r0,@mth_cycle_test_prev_sse
  MOVI r1,0
  MOVHI r1,0x3E80            ; 0.25
  CALL @mth_cycle_test_expect_outputs

  ; ---- eight more steps, strict SSE decrease ----
  ST r0,r0,@mth_cycle_test_loop_count
mth_cycle_test_train_loop:
  CALL @mth_cycle_test_train
  CMP r1,r13
  JMP[NE] @mth_cycle_test_fail
  CMP r9,r0
  JMP[NE] @mth_cycle_test_fail
  LD r2,r0,@mth_cycle_test_prev_sse
  FCMP r7,r2
  JMP[GE] @mth_cycle_test_fail
  ST r7,r0,@mth_cycle_test_prev_sse
  LD r4,r0,@mth_cycle_test_loop_count
  ADDI r4,r4,1
  ST r4,r0,@mth_cycle_test_loop_count
  MOVI r2,8
  CMP r4,r2
  JMP[LT] @mth_cycle_test_train_loop

  ; final predictions must all exceed 0.8
  MOVI r1,0
  MOVHI r1,0x3F4C            ; 0.8 = 0x3F4CCCCD
  MOVI r1,0xCCCD
  MOVHI r1,0x3F4C
  CALL @mth_cycle_test_expect_outputs_gt

  ; ---- mirror invariant on the three edge families, d=0 ----
  MOVI r1,1
  CALL @mth_cycle_test_mirror_record
  MOVI r1,256
  CALL @mth_cycle_test_mirror_record
  MOVI r1,2
  CALL @mth_cycle_test_mirror_record

  ; ---- rejection and recovery checks ----
  CALL @mth_cycle_test_rejections

  ; train once more after all rejections
  CALL @mth_cycle_test_train
  CMP r1,r13
  JMP[NE] @mth_cycle_test_fail

  MOVI r1,@mth_cycle_test_pass
  CALL @mth_cycle_test_puts
  HALT

; ---------------------------------------------------------------------------
; bank and vector setup
; ---------------------------------------------------------------------------

mth_cycle_test_zero_bank:
  ST r15,r0,@mth_cycle_test_ret
  MOVI r4,1
mth_cycle_test_zero_refs:
  ADD r1,r4,r0
  CALL @mth_cycle_test_zero_record
  ADDI r4,r4,1
  MOVI r2,32
  CMP r4,r2
  JMP[LE] @mth_cycle_test_zero_refs

  MOVI r4,1
mth_cycle_test_zero_pairs:
  MOVI r2,511
  SUB r2,r2,r4
  MUL r2,r4,r2
  SHR r2,r2,1
  ADDI r1,r2,1
  CALL @mth_cycle_test_zero_record
  ADDI r4,r4,2
  MOVI r2,31
  CMP r4,r2
  JMP[LE] @mth_cycle_test_zero_pairs
  LD r15,r0,@mth_cycle_test_ret
  RET

; r1 = pair id; zero all 64 words of its record.
mth_cycle_test_zero_record:
  ADDI r2,r1,-1
  SHL r2,r2,6
  ADDI r2,r2,8192
  MOVI r3,64
mth_cycle_test_zero_record_loop:
  ST r0,r2,0
  ADDI r2,r2,1
  ADDI r3,r3,-1
  CMP r3,r0
  JMP[GT] @mth_cycle_test_zero_record_loop
  RET

mth_cycle_test_init_vectors:
  ST r15,r0,@mth_cycle_test_ret
  MOVI r4,0
mth_cycle_test_init_loop:
  MOVI r2,@mth_cycle_test_x
  ADD r2,r2,r4
  ST r0,r2,0
  MOVI r1,0
  MOVHI r1,0x3F80            ; 1.0
  MOVI r2,@mth_cycle_test_target
  ADD r2,r2,r4
  ST r1,r2,0
  MOVI r2,@mth_cycle_test_gate
  ADD r2,r2,r4
  ST r1,r2,0
  ADDI r4,r4,1
  MOVI r2,16
  CMP r4,r2
  JMP[LT] @mth_cycle_test_init_loop

  ; x[0] = 1.0
  MOVI r1,0
  MOVHI r1,0x3F80
  ST r1,r0,@mth_cycle_test_x
  LD r15,r0,@mth_cycle_test_ret
  RET

; Call the native training step with the fixture's fixed configuration.
mth_cycle_test_train:
  ST r15,r0,@mth_cycle_test_train_ret
  MOVI r1,@mth_cycle_test_x
  MOVI r2,@mth_cycle_test_target
  MOVI r3,@mth_cycle_test_gate
  MOVI r4,0
  MOVHI r4,0x3E80            ; lr = 0.25
  MOVI r5,1                  ; base head
  MOVI r6,@mth_cycle_test_scratch
  CALL @mth_mirror_cycle_train_step_f32
  LD r15,r0,@mth_cycle_test_train_ret
  RET

; ---------------------------------------------------------------------------
; prediction and mirror checks
; ---------------------------------------------------------------------------

; r1 = expected output (f32 payload). Predict with one-hot x and check all 16.
mth_cycle_test_expect_outputs:
  ST r15,r0,@mth_cycle_test_ret
  ST r1,r0,@mth_cycle_test_expected
  MOVI r1,@mth_cycle_test_x
  MOVI r2,@mth_cycle_test_out
  MOVI r3,1
  CALL @mth_mirror_cycle_predict16_f32
  CMP r1,r13
  JMP[NE] @mth_cycle_test_fail
  CMP r9,r0
  JMP[NE] @mth_cycle_test_fail

  MOVI r6,0
mth_cycle_test_expect_loop:
  MOVI r7,@mth_cycle_test_out
  ADD r7,r7,r6
  LD r1,r7,0
  LD r2,r0,@mth_cycle_test_expected
  MOVI r3,0
  MOVHI r3,0x3586            ; 1e-6
  CALL @mth_cycle_test_near
  CMP r1,r13
  JMP[NE] @mth_cycle_test_fail
  ADDI r6,r6,1
  MOVI r2,16
  CMP r6,r2
  JMP[LT] @mth_cycle_test_expect_loop
  LD r15,r0,@mth_cycle_test_ret
  RET

; r1 = lower bound; every prediction must be strictly greater.
mth_cycle_test_expect_outputs_gt:
  ST r15,r0,@mth_cycle_test_ret
  ST r1,r0,@mth_cycle_test_expected
  MOVI r1,@mth_cycle_test_x
  MOVI r2,@mth_cycle_test_out
  MOVI r3,1
  CALL @mth_mirror_cycle_predict16_f32
  CMP r1,r13
  JMP[NE] @mth_cycle_test_fail
  MOVI r6,0
mth_cycle_test_gt_loop:
  MOVI r7,@mth_cycle_test_out
  ADD r7,r7,r6
  LD r1,r7,0
  LD r2,r0,@mth_cycle_test_expected
  FCMP r1,r2
  JMP[LE] @mth_cycle_test_fail
  ADDI r6,r6,1
  MOVI r2,16
  CMP r6,r2
  JMP[LT] @mth_cycle_test_gt_loop
  LD r15,r0,@mth_cycle_test_ret
  RET

; r1 = pair id; check lane0 + lane1 == 0 for all channels 0..15.
mth_cycle_test_mirror_record:
  ST r15,r0,@mth_cycle_test_ret
  ST r1,r0,@mth_cycle_test_mirror_id
  MOVI r6,0
mth_cycle_test_mirror_loop:
  LD r7,r0,@mth_cycle_test_mirror_id
  ADDI r7,r7,-1
  SHL r7,r7,6
  ADDI r7,r7,8192
  ADD r7,r7,r6
  LD r1,r7,0
  ADDI r7,r7,32
  LD r2,r7,0
  FADD r4,r1,r2
  MOVI r5,0
  MOVHI r5,0x7FFF
  BOOL.8 r4,r4,r5
  MOVI r5,0
  MOVHI r5,0x3586            ; 1e-6
  FCMP r4,r5
  JMP[GT] @mth_cycle_test_fail
  ADDI r6,r6,1
  MOVI r2,16
  CMP r6,r2
  JMP[LT] @mth_cycle_test_mirror_loop
  LD r15,r0,@mth_cycle_test_ret
  RET

; ---------------------------------------------------------------------------
; rejection checks
; ---------------------------------------------------------------------------

mth_cycle_test_rejections:
  ST r15,r0,@mth_cycle_test_reject_ret

  ; base head 0 -> cause 5
  MOVI r1,@mth_cycle_test_x
  MOVI r2,@mth_cycle_test_target
  MOVI r3,@mth_cycle_test_gate
  MOVI r4,0
  MOVHI r4,0x3E80
  MOVI r5,0
  MOVI r6,@mth_cycle_test_scratch
  CALL @mth_mirror_cycle_train_step_f32
  CMP r1,r0
  JMP[NE] @mth_cycle_test_fail
  MOVI r2,5
  CMP r9,r2
  JMP[NE] @mth_cycle_test_fail

  ; lr = 2.0 -> cause 4
  MOVI r1,@mth_cycle_test_x
  MOVI r2,@mth_cycle_test_target
  MOVI r3,@mth_cycle_test_gate
  MOVI r4,0
  MOVHI r4,0x4000
  MOVI r5,1
  MOVI r6,@mth_cycle_test_scratch
  CALL @mth_mirror_cycle_train_step_f32
  CMP r1,r0
  JMP[NE] @mth_cycle_test_fail
  MOVI r2,4
  CMP r9,r2
  JMP[NE] @mth_cycle_test_fail

  ; gate[0] = -0.5 -> cause 3
  MOVI r1,0
  MOVHI r1,0xBF00
  ST r1,r0,@mth_cycle_test_gate
  MOVI r1,@mth_cycle_test_x
  MOVI r2,@mth_cycle_test_target
  MOVI r3,@mth_cycle_test_gate
  MOVI r4,0
  MOVHI r4,0x3E80
  MOVI r5,1
  MOVI r6,@mth_cycle_test_scratch
  CALL @mth_mirror_cycle_train_step_f32
  CMP r1,r0
  JMP[NE] @mth_cycle_test_fail
  MOVI r2,3
  CMP r9,r2
  JMP[NE] @mth_cycle_test_fail
  MOVI r1,0
  MOVHI r1,0x3F80
  ST r1,r0,@mth_cycle_test_gate

  ; x[0] = 2.0 -> cause 1
  MOVI r1,0
  MOVHI r1,0x4000
  ST r1,r0,@mth_cycle_test_x
  CALL @mth_cycle_test_train
  CMP r1,r0
  JMP[NE] @mth_cycle_test_fail
  MOVI r2,1
  CMP r9,r2
  JMP[NE] @mth_cycle_test_fail
  MOVI r1,0
  MOVHI r1,0x3F80
  ST r1,r0,@mth_cycle_test_x

  ; target[0] = 2.0 -> cause 2
  MOVI r1,0
  MOVHI r1,0x4000
  ST r1,r0,@mth_cycle_test_target
  CALL @mth_cycle_test_train
  CMP r1,r0
  JMP[NE] @mth_cycle_test_fail
  MOVI r2,2
  CMP r9,r2
  JMP[NE] @mth_cycle_test_fail
  MOVI r1,0
  MOVHI r1,0x3F80
  ST r1,r0,@mth_cycle_test_target

  ; non-finite bank edge -> cause 6
  MOVI r1,0
  MOVHI r1,0x7FC0
  MOVI r2,8192
  ST r1,r2,0
  CALL @mth_cycle_test_train
  CMP r1,r0
  JMP[NE] @mth_cycle_test_fail
  MOVI r2,6
  CMP r9,r2
  JMP[NE] @mth_cycle_test_fail
  MOVI r2,8192
  ST r0,r2,0

  ; predict base 0 -> cause 1
  MOVI r1,@mth_cycle_test_x
  MOVI r2,@mth_cycle_test_out
  MOVI r3,0
  CALL @mth_mirror_cycle_predict16_f32
  CMP r1,r0
  JMP[NE] @mth_cycle_test_fail
  MOVI r2,1
  CMP r9,r2
  JMP[NE] @mth_cycle_test_fail

  LD r15,r0,@mth_cycle_test_reject_ret
  RET

; |r1-r2| <= r3, preserving r6-r15.
mth_cycle_test_near:
  MOVI r4,0
  MOVHI r4,0x7FFF
  FSUB r5,r1,r2
  BOOL.8 r5,r5,r4
  FCMP r5,r3
  JMP[GT] @mth_cycle_test_near_fail
  MOVI r1,1
  RET
mth_cycle_test_near_fail:
  MOVI r1,0
  RET

mth_cycle_test_fail:
  MOVI r1,@mth_cycle_test_bad
  CALL @mth_cycle_test_puts
  HALT

mth_cycle_test_puts:
  MOVI r4,255
mth_cycle_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_cycle_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_cycle_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_cycle_test_puts_word

mth_cycle_test_pass:
.str "MTH MIRROR CYCLE TRAIN PASS\n"
mth_cycle_test_bad:
.str "MTH MIRROR CYCLE TRAIN FAIL\n"

.org 4096
mth_cycle_test_ret:
.word 0
mth_cycle_test_train_ret:
.word 0
mth_cycle_test_reject_ret:
.word 0
mth_cycle_test_prev_sse:
.word 0
mth_cycle_test_loop_count:
.word 0
mth_cycle_test_expected:
.word 0
mth_cycle_test_mirror_id:
.word 0
mth_cycle_test_x:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_cycle_test_target:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_cycle_test_gate:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_cycle_test_out:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
mth_cycle_test_scratch:
.word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
