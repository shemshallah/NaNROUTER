; Native NaN16 trihead candidate + independent feedback gate (no host ML).
;
; ALL authorized proposer heads 0..254 can nominate a sparse update to ANY
; target coordinate (h,a,b) in the full mirrored rank-three tensor. Thus
; heads do not own exclusive tensor planes; head255 is void and never votes,
; proposes, or becomes a trainable coordinate. Head0 remains governed by
; the existing NANNET/BSR authority, represented here by permissions[0].
;
; Every authorized proposer has native meta_credit[proposer] in [0,1].
; Candidate delta is scaled by 0.25 + 0.75*credit, NEVER to zero.
; After each decision credit <- credit + 0.125*(accepted - credit).
; This is a recurrent feedback loop: even unsuccessful proposers retain
; candidate access, but future proposals are downweighted; successful
; proposers recover influence. The meta objective remains trusted feedback.
;
; An input proposal is NOT authority. The trusted meta slot owns its target
; and current weight; neither target nor prior weight is supplied by a head.
; Meta evaluates old loss=(weight-target)^2 and candidate loss
; (weight+delta-target)^2 in native f32. It accepts ONLY strictly improved
; candidates, then changes the guest-owned candidate tile value. Rejected
; candidates leave tensor values unchanged. Multiple heads may propose
; consecutive updates to the same slot; feedback is recomputed after each.
;
; This is an ACTUAL self-modifying *candidate tile* in NaN16 guest memory.
; The full 64 MiB per-bank backing, its journaled promotion, and connection
; to the frozen language decoder still require a separately admitted
; external-arena controller. This kernel does NOT write the 8 MiB root.
;
; ABI (r13=1):
;   r1 = proposal[count][6], each:
;       [proposer, h, a, b, delta_f32_bits, trusted_tile_slot]
;   r2 = count, 1..255
;   r3 = permissions[256], each 0/1 (native-authorized snapshot)
;   r4 = trusted_tile[256][4], entries:
;       [mirror_arena_byte_offset, candidate_weight_f32,
;        independent_feedback_target_f32, epoch_u32]
;   r5 = required epoch
;   r7 = meta_credit[256] f32, native trust state initialized in [0,1]
;   r11 = optional journal[count][5] guest word buffer, or 0 (disabled)
;       each [proposer, relative_mirror_offset, accepted_flag,
;             candidate_value_f32_bits, updated_credit_f32_bits]
;       For replay, the caller MUST bind this to a trusted native run,
;       not accept arbitrary unsigned external log text as authority.
;   r6 = stats[4], outputs:
;       [accepted, feedback_rejected, improvement_sum_f32, attempted]
;   r12 = scratch[13] caller-owned zero/overwritable
;   r13 = 1
; output r1=1,r9=0 on success; r1=0,r9=1 on invalid batch.
; Full preflight before the first tile or stats write. Invalid input leaves
; tiles, meta-credit state, stats AND optional journal unchanged. No aliasing between pointers is permitted.
;
; Per-proposal |delta|<=1; old weight and trusted target finite, |x|<=4
; at preflight. Only a strict squared-error reduction is accepted. This
; bound ensures feedback computations cannot overflow for <=255 proposals.
; This is a scalar trusted-target feedback pilot, not full held-out CE or
; autonomous meta-training; later hooks must replace the feedback oracle.
;
; CALL dependency: mth_hypertensor256_mirror_arena_map.
; Input memory is guest-addressed 32-bit words. Mapper output is a relative
; external 64 MiB byte address used as an exact identity in the tile cache.
;
mth_trihead_meta_feedback_f32:
  MOVI r0,0
  ST r1,r12,0
  ST r2,r12,1
  ST r3,r12,2
  ST r4,r12,3
  ST r5,r12,4
  ST r6,r12,5
  ST r15,r12,6
  ST r11,r12,12           ; decision journal destination (optional)
  ST r7,r12,11            ; recurrent meta-credit vector

  CMP r2,r0
  JMP[LE] @mth_tm_invalid
  MOVI r11,255
  CMP r11,r2
  JMP[LT] @mth_tm_invalid

  MOVI r8,0
mth_tm_preflight:
  LD r9,r12,0
  MOVI r10,6
  MUL r10,r8,r10
  ADD r9,r9,r10                ; candidate record
  LD r10,r9,0                 ; proposer
  MOVI r11,254
  CMP r11,r10
  JMP[LT] @mth_tm_invalid
  LD r11,r12,2                ; permissions[proposer]
  ADD r11,r11,r10
  LD r11,r11,0
  CMP r11,r13
  JMP[NE] @mth_tm_invalid

  ; Check all three tensor coordinates and derive exact mirror byte offset.
  LD r1,r9,1
  LD r2,r9,2
  LD r3,r9,3
  CALL @mth_hypertensor256_mirror_arena_map
  CMP r1,r13
  JMP[NE] @mth_tm_invalid

  LD r11,r9,5                 ; trusted tile slot (u8)
  SHR r14,r11,8
  CMP r14,r0
  JMP[NE] @mth_tm_invalid
  SHL r11,r11,2
  LD r10,r12,3
  ADD r10,r10,r11             ; trusted tile record
  LD r11,r10,0
  CMP r11,r6                  ; exact mapped offset
  JMP[NE] @mth_tm_invalid
  LD r11,r10,3
  LD r14,r12,4
  CMP r11,r14                 ; epoch freshness
  JMP[NE] @mth_tm_invalid

  ; Meta state may not be spoofed by proposer. It is trusted native memory.
  LD r11,r9,0                 ; proposer
  LD r14,r12,11               ; credit table
  ADD r14,r14,r11
  LD r11,r14,0
  MOVI r14,0
  MOVHI r14,0x7F80
  BOOL.8 r1,r11,r14
  CMP r1,r14
  JMP[EQ] @mth_tm_invalid
  FCMP r11,r0
  JMP[LT] @mth_tm_invalid
  MOVI r14,0
  MOVHI r14,0x3F80
  FCMP r11,r14
  JMP[GT] @mth_tm_invalid

  ; Validate delta finite and bounded in absolute value by one.
  LD r11,r9,4
  MOVI r14,0
  MOVHI r14,0x7F80
  BOOL.8 r1,r11,r14
  CMP r1,r14
  JMP[EQ] @mth_tm_invalid
  MOVI r14,0xFFFF
  MOVHI r14,0x7FFF
  BOOL.8 r1,r11,r14
  MOVI r14,0
  MOVHI r14,0x3F80
  FCMP r1,r14
  JMP[GT] @mth_tm_invalid

  ; The feedback target is an independently populated trusted tile field.
  ; Protect native feedback arithmetic with a bounded finite input domain.
  MOVI r7,1
mth_tm_check_feedback_word:
  ADD r11,r10,r7
  LD r11,r11,0
  MOVI r14,0
  MOVHI r14,0x7F80
  BOOL.8 r1,r11,r14
  CMP r1,r14
  JMP[EQ] @mth_tm_invalid
  MOVI r14,0xFFFF
  MOVHI r14,0x7FFF
  BOOL.8 r1,r11,r14
  MOVI r14,0
  MOVHI r14,0x4080         ; 4.0f
  FCMP r1,r14
  JMP[GT] @mth_tm_invalid
  ADDI r7,r7,1
  MOVI r14,3
  CMP r7,r14
  JMP[LT] @mth_tm_check_feedback_word

  ADDI r8,r8,1
  LD r11,r12,1
  CMP r8,r11
  JMP[LT] @mth_tm_preflight

  ; The preflight has completed with no modifications to tile or stats.
  ST r0,r12,8
  ST r0,r12,9
  ST r0,r12,10
  MOVI r8,0
mth_tm_feedback:
  LD r9,r12,0
  MOVI r10,6
  MUL r10,r8,r10
  ADD r9,r9,r10
  LD r11,r9,5
  SHL r11,r11,2
  LD r10,r12,3
  ADD r10,r10,r11

  LD r2,r10,1               ; current candidate weight
  LD r3,r10,2               ; trusted feedback target
  LD r14,r9,4               ; proposed delta
  ; Influence is learned but nonzero: effective_delta = d*(.25+.75*credit).
  LD r11,r9,0
  LD r7,r12,11
  ADD r7,r7,r11
  LD r11,r7,0
  MOVI r7,0
  MOVHI r7,0x3F40          ; 0.75f
  FMUL r11,r11,r7
  MOVI r7,0
  MOVHI r7,0x3E80          ; 0.25f
  FADD r11,r11,r7
  FMUL r14,r14,r11
  FSUB r4,r2,r3
  FMUL r4,r4,r4            ; loss_before
  FADD r5,r2,r14           ; candidate weight
  FSUB r6,r5,r3
  FMUL r6,r6,r6            ; loss_after
  FCMP r6,r4
  JMP[GE] @mth_tm_rejected

  ; Strict improvement: update ONLY candidate tile, not root/active tensor.
  ST r5,r10,1
  FSUB r4,r4,r6
  LD r11,r12,10
  FADD r11,r11,r4
  ST r11,r12,10
  LD r11,r12,8
  ADDI r11,r11,1
  ST r11,r12,8
  MOVI r4,1                ; accepted integer flag
  MOVI r6,0
  MOVHI r6,0x3F80          ; accepted feedback signal = 1.0f
  JMP @mth_tm_credit
mth_tm_rejected:
  LD r11,r12,9
  ADDI r11,r11,1
  ST r11,r12,9
  MOVI r4,0                ; rejected integer flag
  MOVI r6,0                ; rejected feedback signal = 0.0f
mth_tm_credit:
  ; Native EMA feedback: credit[h] += (signal-credit[h])/8.
  ; No credit value can block proposal submission: min influence is 0.25.
  LD r11,r9,0
  LD r7,r12,11
  ADD r7,r7,r11
  LD r11,r7,0
  FSUB r6,r6,r11
  MOVI r14,0
  MOVHI r14,0x3E00          ; 0.125f
  FMUL r6,r6,r14
  FADD r11,r11,r6
  ST r11,r7,0

  ; Emit exact native decision journal; transport may apply ACCEPTED values
  ; to a matching external candidate bank after authenticated admission.
  ; This output is not a root write and never targets the active bank.
  LD r14,r12,12
  CMP r14,r0
  JMP[EQ] @mth_tm_next
  MOVI r1,5
  MUL r1,r8,r1
  ADD r14,r14,r1
  LD r1,r9,0
  ST r1,r14,0             ; proposer ID
  LD r1,r10,0
  ST r1,r14,1             ; relative 64 MiB mirror offset
  ST r4,r14,2             ; native admission bit
  LD r1,r10,1
  ST r1,r14,3             ; exact resulting candidate weight f32 bits
  ST r11,r14,4            ; learned meta-credit bits
mth_tm_next:
  ADDI r8,r8,1
  LD r11,r12,1
  CMP r8,r11
  JMP[LT] @mth_tm_feedback

  LD r10,r12,5             ; external stats
  LD r11,r12,8
  ST r11,r10,0
  LD r11,r12,9
  ST r11,r10,1
  LD r11,r12,10
  ST r11,r10,2
  LD r11,r12,1
  ST r11,r10,3
  LD r15,r12,6
  MOVI r1,1
  MOVI r9,0
  RET

mth_tm_invalid:
  LD r15,r12,6
  MOVI r1,0
  MOVI r9,1
  RET
