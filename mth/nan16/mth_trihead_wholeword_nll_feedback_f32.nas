; Original 48M R25 FULL-WORD probability feedback, guest-native NaN16.
;
; This is NOT character-only CE. Records contain per-token exact normalized
; full-word probabilities from the frozen R25 decoder including its known-word
; token masses, 69974-word known set, and 205073-node prefix-trie exclusion.
; The unmodified Python R25 decoder supplies probabilities as inference
; transport. This native kernel ALONE decides candidate admission by sum NLL.
; It never delegates acceptance, optimizer arithmetic, or meta credit to host.
;
; ABI r13=1:
;  r1  = rows[count][2]: old_true_word_p_f32, candidate_true_word_p_f32
;  r2  = count (1..1024)
;  r3  = trusted permissions[256]
;  r4  = proposal[4] [proposer,h,a,b] (coordinate indices, not ASCII)
;  r5  = trusted tile[3] [canonical mirror relative byte offset, weight_f32, epoch]
;  r6  = trusted meta_credit[256] f32 [0,1]
;  r7  = out[5] [before_sum_nll, after_sum_nll, admitted_u32,
;                resulting_weight_f32, resulting_credit_f32]
;  r8  = scratch[16], r9 = required epoch
;  r10 = mode 1=dev commit, 0=readonly heldout audit
;  r11 = candidate weight f32 (predeclared native proposal, |-w|<=1)
; returns r1=1,r9=0 on success; r1=0,r9=1 on failure.
;
; Preflight rejects 255 axes / proposer, mismatched mirror mapping, missing
; permission, stale tile, malformed candidate/credit, every nonfinite,
; nonpositive or >1 input probability. Output, tile and credit remain untouched
; on rejection. No active-bank or original 8 MiB root writes.
; Native NLL=-sum log(P_true) for old and candidate; requires the
; mth_log256_scalar entry included from mth_vector_log256_f32.nas.
;
mth_trihead_wholeword_nll_feedback_f32:
  MOVI r0,0
  ST r15,r8,0
  ST r1,r8,1
  ST r2,r8,2
  ST r3,r8,3
  ST r4,r8,4
  ST r5,r8,5
  ST r6,r8,6
  ST r7,r8,7
  ST r9,r8,8
  ST r10,r8,9
  ST r11,r8,10
  CMP r2,r0
  JMP[LE] @mth_ww_invalid
  MOVI r12,1024
  CMP r12,r2
  JMP[LT] @mth_ww_invalid
  MOVI r12,1
  CMP r10,r12
  JMP[GT] @mth_ww_invalid
  LD r12,r4,0            ; candidate proposer
  MOVI r14,254
  CMP r14,r12
  JMP[LT] @mth_ww_invalid
  ST r12,r8,15
  ADD r14,r3,r12
  LD r14,r14,0
  CMP r14,r13
  JMP[NE] @mth_ww_invalid
  LD r1,r4,1
  LD r2,r4,2
  LD r3,r4,3
  CALL @mth_hypertensor256_mirror_arena_map
  CMP r1,r13
  JMP[NE] @mth_ww_invalid
  LD r12,r8,5
  LD r14,r12,0
  CMP r14,r6
  JMP[NE] @mth_ww_invalid
  LD r14,r12,2
  LD r11,r8,8
  CMP r14,r11
  JMP[NE] @mth_ww_invalid

  ; Validate bounded finite candidate and current tile weights.
  MOVI r3,0
mth_ww_weights_preflight:
  CMP r3,r0
  JMP[EQ] @mth_ww_candidate_preflight
  LD r12,r8,5
  LD r11,r12,1
  JMP @mth_ww_one_weight
mth_ww_candidate_preflight:
  LD r11,r8,10
mth_ww_one_weight:
  MOVI r14,0
  MOVHI r14,0x7F80
  BOOL.8 r12,r11,r14
  CMP r12,r14
  JMP[EQ] @mth_ww_invalid
  MOVI r14,0xFFFF
  MOVHI r14,0x7FFF
  BOOL.8 r12,r11,r14
  MOVI r14,0
  MOVHI r14,0x3F80
  FCMP r12,r14
  JMP[GT] @mth_ww_invalid
  ADDI r3,r3,1
  MOVI r14,2
  CMP r3,r14
  JMP[LT] @mth_ww_weights_preflight

  ; Read trusted meta-credit only.
  LD r14,r8,6
  LD r12,r8,15
  ADD r14,r14,r12
  LD r11,r14,0
  MOVI r14,0
  MOVHI r14,0x7F80
  BOOL.8 r12,r11,r14
  CMP r12,r14
  JMP[EQ] @mth_ww_invalid
  FCMP r11,r0
  JMP[LT] @mth_ww_invalid
  MOVI r14,0
  MOVHI r14,0x3F80
  FCMP r11,r14
  JMP[GT] @mth_ww_invalid

  ; Full preflight before loss or any persistent outputs.
  MOVI r12,0
mth_ww_preflight:
  LD r10,r8,1
  SHL r11,r12,1
  ADD r10,r10,r11
  MOVI r9,0
mth_ww_preflight_side:
  ADD r11,r10,r9
  LD r11,r11,0
  FCMP r11,r0
  JMP[LE] @mth_ww_invalid
  MOVI r14,0
  MOVHI r14,0x3F80
  FCMP r11,r14
  JMP[GT] @mth_ww_invalid
  MOVI r14,0
  MOVHI r14,0x7F80
  BOOL.8 r11,r11,r14
  CMP r11,r14
  JMP[EQ] @mth_ww_invalid
  ADDI r9,r9,1
  MOVI r14,2
  CMP r9,r14
  JMP[LT] @mth_ww_preflight_side
  ADDI r12,r12,1
  LD r14,r8,2
  CMP r12,r14
  JMP[LT] @mth_ww_preflight

  ST r0,r8,11            ; before sum f32
  ST r0,r8,12            ; after sum f32
  ST r0,r8,13            ; row index
mth_ww_score:
  LD r11,r8,13
  SHL r11,r11,1
  LD r10,r8,1
  ADD r10,r10,r11
  LD r1,r10,0            ; unmodified exact-word probability
  ADD r14,r8,r0          ; scalar ln() preserves r14
  CALL @mth_log256_scalar
  ADD r8,r14,r0
  LD r11,r8,11
  FSUB r11,r11,r1
  ST r11,r8,11
  LD r1,r10,1            ; proposed exact-word probability
  ADD r14,r8,r0
  CALL @mth_log256_scalar
  ADD r8,r14,r0
  LD r11,r8,12
  FSUB r11,r11,r1
  ST r11,r8,12
  LD r11,r8,13
  ADDI r11,r11,1
  ST r11,r8,13
  LD r12,r8,2
  CMP r11,r12
  JMP[LT] @mth_ww_score

  ; STRICT whole-word native dev-NLL gate, never character-only.
  ; Compare the exact same causal token positions; small margin 0.001 nat.
  LD r11,r8,12
  MOVI r12,0x126F
  MOVHI r12,0x3A83        ; 1e-3 f32 = 0x3A83126F
  FADD r11,r11,r12
  LD r12,r8,11
  MOVI r10,0
  FCMP r11,r12
  JMP[GE] @mth_ww_gate_done
  MOVI r10,1
mth_ww_gate_done:
  ST r10,r8,14

  ; Read-only heldout evaluation MUST NEVER change tile or credit.
  LD r12,r8,9
  CMP r12,r0
  JMP[EQ] @mth_ww_publish

  ; meta_credit += (admitted-credit)/8.
  LD r11,r8,6
  LD r12,r8,15
  ADD r11,r11,r12
  LD r12,r11,0
  CVTIF r9,r10
  FSUB r9,r9,r12
  MOVI r14,0
  MOVHI r14,0x3E00        ; 0.125
  FMUL r9,r9,r14
  FADD r12,r12,r9
  ST r12,r11,0
  CMP r10,r0
  JMP[EQ] @mth_ww_publish
  LD r11,r8,5
  LD r12,r8,10
  ST r12,r11,1             ; only candidate weight, never active/root

mth_ww_publish:
  LD r11,r8,7
  LD r12,r8,11
  ST r12,r11,0
  LD r12,r8,12
  ST r12,r11,1
  LD r12,r8,14
  ST r12,r11,2
  LD r9,r8,5
  LD r9,r9,1
  ST r9,r11,3
  LD r9,r8,6
  LD r12,r8,15
  ADD r9,r9,r12
  LD r9,r9,0
  ST r9,r11,4
  LD r15,r8,0
  MOVI r1,1
  MOVI r9,0
  RET
mth_ww_invalid:
  LD r15,r8,0
  MOVI r1,0
  MOVI r9,1
  RET
