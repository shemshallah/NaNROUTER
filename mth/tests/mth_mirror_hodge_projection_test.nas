; MTH Round 023 in-place Hodge projection fixture — NaN16 only.
;
; Coverage:
;   1. Complete 256-vertex canonical graph, 32,640 unordered pairs.
;      Small integer lane values make every intermediate exactly
;      representable in binary32, so the projected root is checked
;      word-for-word against an in-guest oracle, the divergence vanishes
;      exactly, the symmetric part is preserved exactly, and a second
;      projection is bit-identical (idempotence).
;   2. A pure-gradient complete graph.  The antisymmetric component is
;      exactly g[b]-g[a], so the projection must remove it completely and
;      leave both lanes equal to the stored symmetric part.
;   3. A non-dyadic complete graph generated in-guest by CVTIF/FDIV.
;      Divergence after projection, symmetric-part preservation, and
;      idempotence are checked with absolute binary32 tolerances.
;   4. Rejection atomicity: -inf at the last pair rejects after a complete
;      finite preflight.  Every root lane start and every divergence scratch
;      word must remain byte-for-byte unchanged.
;
; All pair values are generated in the guest.  There are no host-computed
; arrays.  Expected values for case 1 are built by a separate in-guest scan
; that reads the stored symmetric/antisymmetric parts and the divergence
; oracle; case 2 checks the gradient-removal identity directly; case 3 uses
; tolerant checks because FDIV introduces binary32 rounding.
;
; Storage:
;   canonical root:        word 0 .. 2,097,151  (8 MiB payload bytes)
;   pair region:           word 8,192 .. 2,097,151
;   kernel divergence:     word 2,097,152
;   oracle divergence:     word 2,097,408
;   symmetric part s0:     word 2,097,664
;   antisymmetric part a0: word 2,130,432
;   expected/snapshot x:   word 2,163,200
;   expected/snapshot y:   word 2,195,968
; The verification arrays are outside the 8 MiB root.  The kernel itself
; uses only the root and the 256-word caller scratch.
;
; The test-code and string bytes occupy the low head-region words; the
; kernel never reads or writes that region.  No head record is inspected.

.equ HODGE_D_KERNEL 0x200000
.equ HODGE_D_ORACLE 0x200100
.equ HODGE_S0 0x200200
.equ HODGE_ANTI0 0x208200
.equ HODGE_EXPX 0x210200
.equ HODGE_EXPY 0x218200
.equ HODGE_ROOT 8192
.equ HODGE_PAIR_BYTES 32768

.org 0
JMP @mth_hodge_test_main
.include "../nan16/mth_mirror_hodge_projection.nas"

; ============================================================================
; main
; ============================================================================
mth_hodge_test_main:
  MOVI r0,0
  MOVI r13,1

  CALL @mth_hodge_test_case_exact
  CALL @mth_hodge_test_case_gradient
  CALL @mth_hodge_test_case_tolerance
  CALL @mth_hodge_test_case_reject

  LA r1,@mth_hodge_test_pass
  CALL @mth_hodge_test_puts
  HALT

mth_hodge_test_fail:
  LA r1,@mth_hodge_test_bad
  CALL @mth_hodge_test_puts
  HALT

; ============================================================================
; Case 1 — exact complete graph
; ============================================================================
mth_hodge_test_case_exact:
  ST r15,r0,@hodge_save_exact

  LA r1,#HODGE_D_ORACLE
  CALL @hodge_zero_256
  CALL @hodge_gen_exact

  LA r1,#HODGE_D_ORACLE
  CALL @hodge_div_scan
  CALL @hodge_build_expected_exact

  CALL @hodge_call_kernel
  CMP r1,r13
  JMP[NE] @mth_hodge_test_fail
  CMP r9,r0
  JMP[NE] @mth_hodge_test_fail

  ; The kernel's pre-projection divergence must equal the oracle scan.
  CALL @hodge_check_div_match

  ; Divergence of the projected field must be exactly zero.
  LA r1,#HODGE_D_KERNEL
  CALL @hodge_zero_256
  CALL @hodge_check_projected_exact
  LA r1,#HODGE_D_KERNEL
  CALL @hodge_check_zero_256

  ; A second in-place projection is a bit-exact no-op.
  CALL @hodge_call_kernel
  CMP r1,r13
  JMP[NE] @mth_hodge_test_fail
  CMP r9,r0
  JMP[NE] @mth_hodge_test_fail
  LA r1,#HODGE_D_KERNEL
  CALL @hodge_check_zero_256
  CALL @hodge_check_root_expected_exact

  LD r15,r0,@hodge_save_exact
  RET

; ============================================================================
; Case 2 — pure gradient is removed exactly, symmetric part survives
; ============================================================================
mth_hodge_test_case_gradient:
  ST r15,r0,@hodge_save_gradient

  CALL @hodge_gen_gradient

  ; Pair (0,255) is pair id 255 at record word 8192 + 254*64 = 24,448.
  ; The injected antisymmetric part there is g[255]-g[0] = 7, so this
  ; fixture is not testing an already-symmetric state.
  MOVI r3,24448
  LD r7,r3,0
  LD r8,r3,32
  CMP r7,r8
  JMP[EQ] @mth_hodge_test_fail

  CALL @hodge_call_kernel
  CMP r1,r13
  JMP[NE] @mth_hodge_test_fail
  CMP r9,r0
  JMP[NE] @mth_hodge_test_fail

  ; Exactly x' = y' = s for every pair.
  CALL @hodge_check_root_s0_exact

  ; Divergence of the projected field is exactly zero.
  LA r1,#HODGE_D_KERNEL
  CALL @hodge_zero_256
  LA r1,#HODGE_D_KERNEL
  CALL @hodge_div_scan
  LA r1,#HODGE_D_KERNEL
  CALL @hodge_check_zero_256

  LD r15,r0,@hodge_save_gradient
  RET

; ============================================================================
; Case 3 — non-dyadic values, tolerant divergence/idempotence checks
; ============================================================================
mth_hodge_test_case_tolerance:
  ST r15,r0,@hodge_save_tol

  LA r1,#HODGE_D_ORACLE
  CALL @hodge_zero_256
  CALL @hodge_gen_tolerance

  LA r1,#HODGE_D_ORACLE
  CALL @hodge_div_scan

  CALL @hodge_call_kernel
  CMP r1,r13
  JMP[NE] @mth_hodge_test_fail
  CMP r9,r0
  JMP[NE] @mth_hodge_test_fail

  ; The kernel's f32 accumulation order matches the oracle scan exactly.
  CALL @hodge_check_div_match

  ; Compute post-projection divergence, check divergence and symmetric
  ; preservation tolerances, and snapshot the projected lanes.
  LA r1,#HODGE_D_KERNEL
  CALL @hodge_zero_256
  CALL @hodge_check_tol_metrics

  ; Second projection: compare with the snapshot and recheck divergence.
  CALL @hodge_call_kernel
  CMP r1,r13
  JMP[NE] @mth_hodge_test_fail
  CMP r9,r0
  JMP[NE] @mth_hodge_test_fail
  CALL @hodge_check_kernel_d_tol
  LA r1,#HODGE_D_KERNEL
  CALL @hodge_zero_256
  CALL @hodge_check_idem_tol
  LA r1,#HODGE_D_KERNEL
  CALL @hodge_check_near_zero_256

  LD r15,r0,@hodge_save_tol
  RET

; ============================================================================
; Case 4 — non-finite rejection is atomic
; ============================================================================
mth_hodge_test_case_reject:
  ST r15,r0,@hodge_save_reject

  ; Every lane start of the complete graph becomes +1.0.
  LA r3,#HODGE_ROOT
  MOVI r4,0
  MOVI r5,0
  MOVHI r5,0x3F80
  MOVI r6,0x7F80              ; 32,640 pairs
hodge_reject_fill_a:
  ST r5,r3,0
  ST r5,r3,32
  ADDI r3,r3,64
  ADD r4,r4,r13
  CMP r4,r6
  JMP[LT] @hodge_reject_fill_a

  ; Poison only the last pair's lane 1 with -inf.
  ; Last record word = 8192 + 32,639*64 = 2,097,088; lane1 = 2,097,120.
  MOVI r7,0
  MOVHI r7,0xFF80
  MOVI r8,0xFFE0
  MOVHI r8,0x001F
  ST r7,r8,0

  ; The divergence scratch must stay untouched too.
  LA r1,#HODGE_D_KERNEL
  MOVI r2,0xBEEF
  MOVHI r2,0xDEAD
  CALL @hodge_fill_256

  CALL @hodge_call_kernel
  CMP r1,r0
  JMP[NE] @mth_hodge_test_fail
  CMP r9,r13
  JMP[NE] @mth_hodge_test_fail

  ; The scratch still contains the sentinel pattern.
  LA r1,#HODGE_D_KERNEL
  MOVI r2,0xBEEF
  MOVHI r2,0xDEAD
  CALL @hodge_check_fill_256

  ; The first 32,639 records are still +1.0 in both lanes.
  LA r3,#HODGE_ROOT
  MOVI r4,0
  MOVI r5,0
  MOVHI r5,0x3F80
  MOVI r6,0x7F7F              ; 32,639
hodge_reject_check_a:
  LD r7,r3,0
  CMP r7,r5
  JMP[NE] @mth_hodge_test_fail
  LD r7,r3,32
  CMP r7,r5
  JMP[NE] @mth_hodge_test_fail
  ADDI r3,r3,64
  ADD r4,r4,r13
  CMP r4,r6
  JMP[LT] @hodge_reject_check_a

  ; Last record: lane0 still +1.0, lane1 still -inf.
  LD r7,r3,0
  CMP r7,r5
  JMP[NE] @mth_hodge_test_fail
  LD r7,r3,32
  MOVI r8,0
  MOVHI r8,0xFF80
  CMP r7,r8
  JMP[NE] @mth_hodge_test_fail

  LD r15,r0,@hodge_save_reject
  RET

; ============================================================================
; Kernel call wrapper
; ============================================================================
hodge_call_kernel:
  ST r15,r0,@hodge_save_call
  LA r1,#HODGE_PAIR_BYTES
  LA r2,#HODGE_D_KERNEL
  CALL @mth_mirror_hodge_projection
  LD r15,r0,@hodge_save_call
  RET

; ============================================================================
; Generators
; ============================================================================

; Case 1: x = ((3a+5b)&31)-16, y = ((11a+7b)&31)-16.
; Both are exact small integers.  s0 and anti0 are exact halves.
hodge_gen_exact:
  LA r3,#HODGE_ROOT
  LA r6,#HODGE_S0
  LA r7,#HODGE_ANTI0
  MOVI r4,0
hodge_gen_exact_a:
  ADD r5,r4,r13
hodge_gen_exact_b:
  MOVI r1,256
  CMP r5,r1
  JMP[GE] @hodge_gen_exact_next_a

  MOVI r10,3
  MUL r10,r4,r10
  MOVI r12,5
  MUL r12,r5,r12
  ADD r10,r10,r12
  MOVI r12,31
  BOOL.8 r10,r10,r12
  ADDI r10,r10,-16
  CVTIF r10,r10

  MOVI r11,11
  MUL r11,r4,r11
  MOVI r12,7
  MUL r12,r5,r12
  ADD r11,r11,r12
  MOVI r12,31
  BOOL.8 r11,r11,r12
  ADDI r11,r11,-16
  CVTIF r11,r11

  ST r10,r3,0
  ST r11,r3,32

  MOVI r12,0
  MOVHI r12,0x3F00
  FADD r8,r10,r11
  FMUL r8,r8,r12
  FSUB r9,r10,r11
  FMUL r9,r9,r12
  ST r8,r6,0
  ST r9,r7,0

  ADD r6,r6,r13
  ADD r7,r7,r13
  ADDI r3,r3,64
  ADD r5,r5,r13
  JMP @hodge_gen_exact_b

hodge_gen_exact_next_a:
  ADD r4,r4,r13
  MOVI r1,256
  CMP r4,r1
  JMP[LT] @hodge_gen_exact_a
  RET

; Case 2: s = (((3a+5b)&15)-8)/4, g[a] = a&7,
; x = s + (g[b]-g[a]), y = s - (g[b]-g[a]).
hodge_gen_gradient:
  LA r3,#HODGE_ROOT
  LA r6,#HODGE_S0
  MOVI r4,0
hodge_gen_gradient_a:
  ADD r5,r4,r13
hodge_gen_gradient_b:
  MOVI r1,256
  CMP r5,r1
  JMP[GE] @hodge_gen_gradient_next_a

  ; s = (((3a+5b)&15)-8) * 0.25
  MOVI r10,3
  MUL r10,r4,r10
  MOVI r12,5
  MUL r12,r5,r12
  ADD r10,r10,r12
  MOVI r12,15
  BOOL.8 r10,r10,r12
  ADDI r10,r10,-8
  CVTIF r10,r10
  MOVI r12,0
  MOVHI r12,0x3E80
  FMUL r10,r10,r12

  ; dg = g[b]-g[a]
  MOVI r8,7
  BOOL.8 r8,r5,r8
  MOVI r9,7
  BOOL.8 r9,r4,r9
  SUB r8,r8,r9
  CVTIF r8,r8

  FADD r11,r10,r8
  FSUB r9,r10,r8
  ST r11,r3,0
  ST r9,r3,32
  ST r10,r6,0

  ADD r6,r6,r13
  ADDI r3,r3,64
  ADD r5,r5,r13
  JMP @hodge_gen_gradient_b

hodge_gen_gradient_next_a:
  ADD r4,r4,r13
  MOVI r1,256
  CMP r4,r1
  JMP[LT] @hodge_gen_gradient_a
  RET

; Case 3: x = (((37k+3a+7b)&255)-128)/257,
;         y = (((53k+5a+11b)&255)-128)/263.
; The two FDIVs introduce non-dyadic binary32 rounding.
hodge_gen_tolerance:
  LA r3,#HODGE_ROOT
  LA r6,#HODGE_S0
  LA r7,#HODGE_ANTI0
  MOVI r14,0
  MOVI r4,0
hodge_gen_tolerance_a:
  ADD r5,r4,r13
hodge_gen_tolerance_b:
  MOVI r1,256
  CMP r5,r1
  JMP[GE] @hodge_gen_tolerance_next_a

  MOVI r10,37
  MUL r10,r14,r10
  MOVI r12,3
  MUL r12,r4,r12
  ADD r10,r10,r12
  MOVI r12,7
  MUL r12,r5,r12
  ADD r10,r10,r12
  MOVI r12,255
  BOOL.8 r10,r10,r12
  ADDI r10,r10,-128
  CVTIF r10,r10
  MOVI r12,0x8000
  MOVHI r12,0x4380
  FDIV r10,r10,r12

  MOVI r11,53
  MUL r11,r14,r11
  MOVI r12,5
  MUL r12,r4,r12
  ADD r11,r11,r12
  MOVI r12,11
  MUL r12,r5,r12
  ADD r11,r11,r12
  MOVI r12,255
  BOOL.8 r11,r11,r12
  ADDI r11,r11,-128
  CVTIF r11,r11
  MOVI r12,0x3800
  MOVHI r12,0x4383
  FDIV r11,r11,r12

  ST r10,r3,0
  ST r11,r3,32

  MOVI r12,0
  MOVHI r12,0x3F00
  FADD r8,r10,r11
  FMUL r8,r8,r12
  FSUB r9,r10,r11
  FMUL r9,r9,r12
  ST r8,r6,0
  ST r9,r7,0

  ADD r6,r6,r13
  ADD r7,r7,r13
  ADDI r3,r3,64
  ADD r5,r5,r13
  ADD r14,r14,r13
  JMP @hodge_gen_tolerance_b

hodge_gen_tolerance_next_a:
  ADD r4,r4,r13
  MOVI r1,256
  CMP r4,r1
  JMP[LT] @hodge_gen_tolerance_a
  RET

; ============================================================================
; Divergence scan from the live root into r1 (256 f32 words)
; ============================================================================
hodge_div_scan:
  ADD r9,r1,r0
  LA r3,#HODGE_ROOT
  MOVI r12,0
  MOVHI r12,0x3F00
  MOVI r4,0
hodge_div_scan_a:
  ADD r5,r4,r13
hodge_div_scan_b:
  MOVI r1,256
  CMP r5,r1
  JMP[GE] @hodge_div_scan_next_a

  LD r7,r3,0
  LD r8,r3,32
  FSUB r7,r7,r8
  FMUL r7,r7,r12

  ADD r10,r9,r4
  LD r11,r10,0
  FADD r11,r11,r7
  ST r11,r10,0

  ADD r10,r9,r5
  LD r11,r10,0
  FSUB r11,r11,r7
  ST r11,r10,0

  ADDI r3,r3,64
  ADD r5,r5,r13
  JMP @hodge_div_scan_b

hodge_div_scan_next_a:
  ADD r4,r4,r13
  MOVI r1,256
  CMP r4,r1
  JMP[LT] @hodge_div_scan_a
  RET

; ============================================================================
; Case 1 expected projection, built in-guest from s0, anti0, and d_oracle
; ============================================================================
hodge_build_expected_exact:
  LA r3,#HODGE_D_ORACLE
  LA r6,#HODGE_S0
  LA r7,#HODGE_ANTI0
  LA r8,#HODGE_EXPX
  LA r9,#HODGE_EXPY
  MOVI r12,0
  MOVHI r12,0x3B80            ; 1/256
  MOVI r4,0
hodge_build_expected_a:
  ADD r5,r4,r13
hodge_build_expected_b:
  MOVI r1,256
  CMP r5,r1
  JMP[GE] @hodge_build_expected_next_a

  LD r10,r6,0                ; s
  LD r11,r7,0                ; anti
  ADD r14,r3,r4
  LD r14,r14,0               ; da
  ADD r1,r3,r5
  LD r1,r1,0                 ; db
  FSUB r14,r14,r1
  FMUL r14,r14,r12           ; gradient
  FSUB r11,r11,r14           ; anti'
  FADD r1,r10,r11
  ST r1,r8,0                 ; x'
  FSUB r1,r10,r11
  ST r1,r9,0                 ; y'

  ADD r6,r6,r13
  ADD r7,r7,r13
  ADD r8,r8,r13
  ADD r9,r9,r13
  ADD r5,r5,r13
  JMP @hodge_build_expected_b

hodge_build_expected_next_a:
  ADD r4,r4,r13
  MOVI r1,256
  CMP r4,r1
  JMP[LT] @hodge_build_expected_a
  RET

; ============================================================================
; Exact checks
; ============================================================================
hodge_check_div_match:
  LA r6,#HODGE_D_KERNEL
  LA r7,#HODGE_D_ORACLE
  MOVI r4,0
hodge_check_div_match_loop:
  LD r8,r6,0
  LD r9,r7,0
  CMP r8,r9
  JMP[NE] @mth_hodge_test_fail
  ADD r6,r6,r13
  ADD r7,r7,r13
  ADD r4,r4,r13
  MOVI r8,256
  CMP r4,r8
  JMP[LT] @hodge_check_div_match_loop
  RET

; Compare projected root with EXPX/EXPY, compare its symmetric part with
; S0, and accumulate its divergence into D_KERNEL (which the caller zeroed).
hodge_check_projected_exact:
  LA r3,#HODGE_ROOT
  LA r6,#HODGE_EXPX
  LA r7,#HODGE_EXPY
  LA r8,#HODGE_S0
  LA r9,#HODGE_D_KERNEL
  MOVI r12,0
  MOVHI r12,0x3F00
  MOVI r4,0
hodge_check_projected_a:
  ADD r5,r4,r13
hodge_check_projected_b:
  MOVI r1,256
  CMP r5,r1
  JMP[GE] @hodge_check_projected_next_a

  LD r10,r3,0
  LD r11,r3,32
  LD r14,r6,0
  CMP r10,r14
  JMP[NE] @mth_hodge_test_fail
  LD r14,r7,0
  CMP r11,r14
  JMP[NE] @mth_hodge_test_fail

  FADD r14,r10,r11
  FMUL r14,r14,r12
  LD r1,r8,0
  CMP r14,r1
  JMP[NE] @mth_hodge_test_fail

  FSUB r10,r10,r11
  FMUL r10,r10,r12

  ADD r14,r9,r4
  LD r1,r14,0
  FADD r1,r1,r10
  ST r1,r14,0

  ADD r14,r9,r5
  LD r1,r14,0
  FSUB r1,r1,r10
  ST r1,r14,0

  ADDI r3,r3,64
  ADD r6,r6,r13
  ADD r7,r7,r13
  ADD r8,r8,r13
  ADD r5,r5,r13
  JMP @hodge_check_projected_b

hodge_check_projected_next_a:
  ADD r4,r4,r13
  MOVI r1,256
  CMP r4,r1
  JMP[LT] @hodge_check_projected_a
  RET

hodge_check_root_expected_exact:
  LA r3,#HODGE_ROOT
  LA r6,#HODGE_EXPX
  LA r7,#HODGE_EXPY
  MOVI r4,0
hodge_check_root_expected_a:
  ADD r5,r4,r13
hodge_check_root_expected_b:
  MOVI r1,256
  CMP r5,r1
  JMP[GE] @hodge_check_root_expected_next_a

  LD r10,r3,0
  LD r11,r3,32
  LD r14,r6,0
  CMP r10,r14
  JMP[NE] @mth_hodge_test_fail
  LD r14,r7,0
  CMP r11,r14
  JMP[NE] @mth_hodge_test_fail

  ADDI r3,r3,64
  ADD r6,r6,r13
  ADD r7,r7,r13
  ADD r5,r5,r13
  JMP @hodge_check_root_expected_b

hodge_check_root_expected_next_a:
  ADD r4,r4,r13
  MOVI r1,256
  CMP r4,r1
  JMP[LT] @hodge_check_root_expected_a
  RET

hodge_check_root_s0_exact:
  LA r3,#HODGE_ROOT
  LA r6,#HODGE_S0
  MOVI r4,0
hodge_check_root_s0_a:
  ADD r5,r4,r13
hodge_check_root_s0_b:
  MOVI r1,256
  CMP r5,r1
  JMP[GE] @hodge_check_root_s0_next_a

  LD r10,r3,0
  LD r11,r3,32
  LD r14,r6,0
  CMP r10,r14
  JMP[NE] @mth_hodge_test_fail
  CMP r11,r14
  JMP[NE] @mth_hodge_test_fail

  ADDI r3,r3,64
  ADD r6,r6,r13
  ADD r5,r5,r13
  JMP @hodge_check_root_s0_b

hodge_check_root_s0_next_a:
  ADD r4,r4,r13
  MOVI r1,256
  CMP r4,r1
  JMP[LT] @hodge_check_root_s0_a
  RET

; ============================================================================
; Tolerant checks for case 3
; ============================================================================

; D_KERNEL must have been zeroed by the caller.  Accumulate divergence of
; the projected root, snapshot both projected lanes into EXPX/EXPY, and
; track max |divergence| and max |s' - s0|.
hodge_check_tol_metrics:
  ST r0,r0,@hodge_max_div
  ST r0,r0,@hodge_max_sym
  LA r3,#HODGE_ROOT
  LA r6,#HODGE_S0
  LA r7,#HODGE_EXPX
  LA r8,#HODGE_EXPY
  LA r9,#HODGE_D_KERNEL
  MOVI r12,0
  MOVHI r12,0x3F00
  MOVI r4,0
hodge_check_tol_metrics_a:
  ADD r5,r4,r13
hodge_check_tol_metrics_b:
  MOVI r1,256
  CMP r5,r1
  JMP[GE] @hodge_check_tol_metrics_next_a

  LD r10,r3,0
  LD r11,r3,32
  ST r10,r7,0                ; snapshot x
  ST r11,r8,0                ; snapshot y

  ; |((x+y)/2) - s0|
  FADD r14,r10,r11
  FMUL r14,r14,r12
  LD r1,r6,0
  FSUB r14,r14,r1
  MOVI r1,0xFFFF
  MOVHI r1,0x7FFF
  BOOL.8 r14,r14,r1
  LD r1,r0,@hodge_max_sym
  FCMP r14,r1
  JMP[LE] @hodge_check_tol_sym_ok
  ST r14,r0,@hodge_max_sym
hodge_check_tol_sym_ok:

  ; divergence accumulation
  FSUB r10,r10,r11
  FMUL r10,r10,r12
  ADD r14,r9,r4
  LD r1,r14,0
  FADD r1,r1,r10
  ST r1,r14,0
  ADD r14,r9,r5
  LD r1,r14,0
  FSUB r1,r1,r10
  ST r1,r14,0

  ADDI r3,r3,64
  ADD r6,r6,r13
  ADD r7,r7,r13
  ADD r8,r8,r13
  ADD r5,r5,r13
  JMP @hodge_check_tol_metrics_b

hodge_check_tol_metrics_next_a:
  ADD r4,r4,r13
  MOVI r1,256
  CMP r4,r1
  JMP[LT] @hodge_check_tol_metrics_a

  ; max |divergence| <= 2^-10
  LD r14,r0,@hodge_max_div
  MOVI r1,0
  MOVHI r1,0x3A80
  FCMP r14,r1
  JMP[GT] @mth_hodge_test_fail

  ; max |s' - s0| <= 2^-19
  LD r14,r0,@hodge_max_sym
  MOVI r1,0
  MOVHI r1,0x3600
  FCMP r14,r1
  JMP[GT] @mth_hodge_test_fail
  RET

; Check the kernel's own divergence scratch after the second projection.
hodge_check_kernel_d_tol:
  LA r6,#HODGE_D_KERNEL
  MOVI r8,0
  MOVHI r8,0x3A80
  MOVI r4,0
hodge_check_kernel_d_tol_loop:
  LD r7,r6,0
  MOVI r9,0xFFFF
  MOVHI r9,0x7FFF
  BOOL.8 r7,r7,r9
  FCMP r7,r8
  JMP[GT] @mth_hodge_test_fail
  ADD r6,r6,r13
  ADD r4,r4,r13
  MOVI r7,256
  CMP r4,r7
  JMP[LT] @hodge_check_kernel_d_tol_loop
  RET

; D_KERNEL must have been zeroed by the caller.  Compare root with the
; EXPX/EXPY snapshot and accumulate the post-second divergence there.
hodge_check_idem_tol:
  ST r0,r0,@hodge_max_idem
  LA r3,#HODGE_ROOT
  LA r6,#HODGE_EXPX
  LA r7,#HODGE_EXPY
  LA r8,#HODGE_D_KERNEL
  MOVI r9,0xFFFF
  MOVHI r9,0x7FFF
  MOVI r12,0
  MOVHI r12,0x3F00
  MOVI r4,0
hodge_check_idem_tol_a:
  ADD r5,r4,r13
hodge_check_idem_tol_b:
  MOVI r1,256
  CMP r5,r1
  JMP[GE] @hodge_check_idem_tol_next_a

  LD r10,r3,0
  LD r11,r3,32

  ; |x - snapshot_x|
  LD r14,r6,0
  FSUB r14,r10,r14
  BOOL.8 r14,r14,r9
  LD r1,r0,@hodge_max_idem
  FCMP r14,r1
  JMP[LE] @hodge_check_idem_x_ok
  ST r14,r0,@hodge_max_idem
hodge_check_idem_x_ok:

  ; |y - snapshot_y|
  LD r14,r7,0
  FSUB r14,r11,r14
  BOOL.8 r14,r14,r9
  LD r1,r0,@hodge_max_idem
  FCMP r14,r1
  JMP[LE] @hodge_check_idem_y_ok
  ST r14,r0,@hodge_max_idem
hodge_check_idem_y_ok:

  ; divergence accumulation
  FSUB r10,r10,r11
  FMUL r10,r10,r12
  ADD r14,r8,r4
  LD r1,r14,0
  FADD r1,r1,r10
  ST r1,r14,0
  ADD r14,r8,r5
  LD r1,r14,0
  FSUB r1,r1,r10
  ST r1,r14,0

  ADDI r3,r3,64
  ADD r6,r6,r13
  ADD r7,r7,r13
  ADD r5,r5,r13
  JMP @hodge_check_idem_tol_b

hodge_check_idem_tol_next_a:
  ADD r4,r4,r13
  MOVI r1,256
  CMP r4,r1
  JMP[LT] @hodge_check_idem_tol_a

  ; max |x''-x'|, |y''-y'| <= 2^-18
  LD r14,r0,@hodge_max_idem
  MOVI r1,0
  MOVHI r1,0x3680
  FCMP r14,r1
  JMP[GT] @mth_hodge_test_fail
  RET

; ============================================================================
; Small helpers
; ============================================================================
hodge_zero_256:
  ADD r6,r1,r0
  MOVI r4,0
hodge_zero_256_loop:
  ST r0,r6,0
  ADD r6,r6,r13
  ADD r4,r4,r13
  MOVI r7,256
  CMP r4,r7
  JMP[LT] @hodge_zero_256_loop
  RET

hodge_check_zero_256:
  ADD r6,r1,r0
  MOVI r4,0
hodge_check_zero_256_loop:
  LD r7,r6,0
  CMP r7,r0
  JMP[NE] @mth_hodge_test_fail
  ADD r6,r6,r13
  ADD r4,r4,r13
  MOVI r7,256
  CMP r4,r7
  JMP[LT] @hodge_check_zero_256_loop
  RET

hodge_fill_256:
  ADD r6,r1,r0
  ADD r7,r2,r0
  MOVI r4,0
hodge_fill_256_loop:
  ST r7,r6,0
  ADD r6,r6,r13
  ADD r4,r4,r13
  MOVI r8,256
  CMP r4,r8
  JMP[LT] @hodge_fill_256_loop
  RET

hodge_check_fill_256:
  ADD r6,r1,r0
  ADD r8,r2,r0
  MOVI r4,0
hodge_check_fill_256_loop:
  LD r7,r6,0
  CMP r7,r8
  JMP[NE] @mth_hodge_test_fail
  ADD r6,r6,r13
  ADD r4,r4,r13
  MOVI r7,256
  CMP r4,r7
  JMP[LT] @hodge_check_fill_256_loop
  RET

hodge_check_near_zero_256:
  ADD r6,r1,r0
  MOVI r8,0
  MOVHI r8,0x3A80
  MOVI r4,0
hodge_check_near_zero_256_loop:
  LD r7,r6,0
  MOVI r9,0xFFFF
  MOVHI r9,0x7FFF
  BOOL.8 r7,r7,r9
  FCMP r7,r8
  JMP[GT] @mth_hodge_test_fail
  ADD r6,r6,r13
  ADD r4,r4,r13
  MOVI r7,256
  CMP r4,r7
  JMP[LT] @hodge_check_near_zero_256_loop
  RET

mth_hodge_test_puts:
  MOVI r4,255
mth_hodge_test_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_hodge_test_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_hodge_test_puts_byte
  ADD r1,r1,r13
  JMP @mth_hodge_test_puts_word

; ============================================================================
; Static save slots and strings (inside the otherwise-unused head region)
; ============================================================================
.org 4096
hodge_save_exact:
.word 0
hodge_save_gradient:
.word 0
hodge_save_tol:
.word 0
hodge_save_reject:
.word 0
hodge_save_call:
.word 0
hodge_max_div:
.word 0
hodge_max_sym:
.word 0
hodge_max_idem:
.word 0

.org 4200
mth_hodge_test_pass:
.str "MTH MIRROR HODGE PROJECTION PASS\n"
mth_hodge_test_bad:
.str "MTH MIRROR HODGE PROJECTION FAIL\n"
