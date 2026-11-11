; Native NaN16 META feedback with actual frozen decoder next-byte logits.
; This is the decoder-loss integration path, NOT a scalar target MSE proxy.
; Uses established mth_lm_cross_entropy256_f32 (softmax cross entropy).
; The 256th byte is void and must be exactly -inf in all supplied traces.
;
; A trusted read-only decoder supplies *CAUSAL* logits (before observing
; the target byte). A single tensor value T[h,a,b] is an additive residual
; to class b for each row whose preceding context was exactly (h,a).
; The source trace builder/decoder must attest that context binding.
; The guest tests old vs candidate CE over the exact SAME rows.
;
; Repeated dev proposals compare CURRENT candidate to CURRENT+delta; test
; compares FROZEN base to selected candidate and never commits. All these
; score comparisons are exact paired examples scored in native NaN16.
;
; Any authorized proposer 0..254 may request any (h,a,b) coordinate.
; Neither proposer nor an external host decides admission: the guest
; accepts only if aggregate dev loss decreases by >1e-4 nats; test mode
; evaluates an already accepted candidate WITHOUT writing any weights
; or meta-credit. Head255 is never a trainable/proposing coordinate.
;
; ABI r13=1:
;  r1=proposal[6] [proposer,h,a,b,delta_f32_bits,tile_slot=0]
;  r2=permissions[256] (trusted 0/1 authority snapshot)
;  r3=meta_credit[256] float32 values in [0,1] (trusted guest memory)
;  r4=tile[3] [relative mirror offset, candidate_weight, epoch]
;  r5=decoder_records[count][257], 256 logits f32 then target byte U32
;  r6=count (1..32), r7=out[6], r8=work[279] words
;  r9=required_epoch, r10=mode 1=dev commit, 0=read-only test
; Return r1=1,r9=0 success; r1=0,r9=1 reject invalid input.
; out: [before_ce_sum_f32, after_ce_sum_f32, improved_u32,
;       candidate_weight_f32, meta_credit_f32, count_u32].
; No output/weight/meta writes occur until all decoder rows and both CE
; sums have passed. Trust metadata/permissions/target logits remain read-only.
; For mode=1 delta_eff=delta*(.25+.75*credit); if CE improves it is added
; to candidate tile weight and credit EMA success, otherwise credit EMA fail.
; For mode=0 delta_eff=tile.weight and no state modifications; reports
; held-out CE only, never decides whether to promote based on test.
; The active 64 MiB tensor and canonical 8 MiB root are untouched.
;
; WORK LAYOUT:
;  [0..255] scratch candidate logits
;  [256..263] pointers, epoch, mode, return link
;  [264..268] index, before_sum, after_sum, delta_eff, current target
;  [269..270] CE output words, [271..275] CE subkernel scratch
;  [276..278] proposer and selected tensor class
;
; Requires include of mth_hypertensor256_mirror_arena_map and
; mth_lm_cross_entropy256_f32 before entry. Kernel itself only calls
; existing native NaN16 instructions; the host never scores candidates.
;
mth_trihead_decoder_ce_feedback_f32:
  MOVI r0,0
  ST r1,r8,256
  ST r2,r8,257
  ST r3,r8,258
  ST r4,r8,259
  ST r5,r8,260
  ST r6,r8,261
  ST r7,r8,262
  ST r15,r8,263
  ST r9,r8,276             ; expected native epoch
  ST r10,r8,277            ; dev / read-only test mode

  CMP r6,r0
  JMP[LE] @mth_dce_invalid
  MOVI r11,32
  CMP r11,r6
  JMP[LT] @mth_dce_invalid
  MOVI r11,1
  CMP r10,r11
  JMP[GT] @mth_dce_invalid

  LD r11,r1,5              ; trusted tile slot exactly 0
  CMP r11,r0
  JMP[NE] @mth_dce_invalid
  LD r11,r1,0              ; proposer
  MOVI r14,254
  CMP r14,r11
  JMP[LT] @mth_dce_invalid
  ST r11,r8,278
  ADD r12,r2,r11
  LD r12,r12,0             ; authority permission
  CMP r12,r13
  JMP[NE] @mth_dce_invalid

  ; Map coordinate to the palindromic mirror and check the trusted tile.
  LD r1,r8,256
  LD r2,r1,1               ; h
  LD r3,r1,2               ; a
  LD r12,r1,3              ; b
  ST r12,r8,279            ; token class
  ADD r1,r2,r0
  ADD r2,r3,r0
  ADD r3,r12,r0
  CALL @mth_hypertensor256_mirror_arena_map
  CMP r1,r13
  JMP[NE] @mth_dce_invalid
  LD r11,r8,259
  LD r12,r11,0
  CMP r12,r6
  JMP[NE] @mth_dce_invalid
  LD r12,r11,2
  LD r14,r8,276
  CMP r12,r14
  JMP[NE] @mth_dce_invalid

  ; Validate finite tile, credit and bounded proposal (|weight|<=4,
  ; |delta|<=1). Subkernel CE will validate each decoder logit.
  LD r12,r11,1            ; current candidate weight
  MOVI r14,0
  MOVHI r14,0x7F80
  BOOL.8 r1,r12,r14
  CMP r1,r14
  JMP[EQ] @mth_dce_invalid
  MOVI r14,0xFFFF
  MOVHI r14,0x7FFF
  BOOL.8 r1,r12,r14
  MOVI r14,0
  MOVHI r14,0x4080
  FCMP r1,r14
  JMP[GT] @mth_dce_invalid

  LD r11,r8,278           ; proposer credit
  LD r12,r8,258
  ADD r12,r12,r11
  LD r12,r12,0
  MOVI r14,0
  MOVHI r14,0x7F80
  BOOL.8 r1,r12,r14
  CMP r1,r14
  JMP[EQ] @mth_dce_invalid
  FCMP r12,r0
  JMP[LT] @mth_dce_invalid
  MOVI r14,0
  MOVHI r14,0x3F80
  FCMP r12,r14
  JMP[GT] @mth_dce_invalid

  LD r11,r8,256
  LD r11,r11,4
  MOVI r14,0
  MOVHI r14,0x7F80
  BOOL.8 r1,r11,r14
  CMP r1,r14
  JMP[EQ] @mth_dce_invalid
  MOVI r14,0xFFFF
  MOVHI r14,0x7FFF
  BOOL.8 r1,r11,r14
  MOVI r14,0
  MOVHI r14,0x3F80
  FCMP r1,r14
  JMP[GT] @mth_dce_invalid

  ; Determine effective candidate residual; read-only uses existing tile.
  LD r14,r8,277
  CMP r14,r0
  JMP[EQ] @mth_dce_readonly_delta
  MOVI r14,0
  MOVHI r14,0x3F40        ; .75
  FMUL r12,r12,r14
  MOVI r14,0
  MOVHI r14,0x3E80        ; .25
  FADD r12,r12,r14
  FMUL r11,r11,r12
  ST r11,r8,267
  JMP @mth_dce_preflight_begin
mth_dce_readonly_delta:
  LD r11,r8,259
  LD r11,r11,1
  ST r11,r8,267

mth_dce_preflight_begin:
  ; Preflight all target bytes and ALL 256 logits before any output/write.
  MOVI r9,0
mth_dce_preflight_record:
  MOVI r11,257
  MUL r11,r9,r11
  LD r12,r8,260
  ADD r12,r12,r11
  LD r14,r12,256
  MOVI r11,254
  CMP r11,r14
  JMP[LT] @mth_dce_invalid
  MOVI r10,0
mth_dce_preflight_logit:
  ADD r11,r12,r10
  LD r11,r11,0
  MOVI r14,255
  CMP r10,r14
  JMP[NE] @mth_dce_preflight_finite
  MOVI r14,0
  MOVHI r14,0xFF80
  CMP r11,r14
  JMP[NE] @mth_dce_invalid
  JMP @mth_dce_preflight_next
mth_dce_preflight_finite:
  MOVI r14,0
  MOVHI r14,0x7F80
  BOOL.8 r1,r11,r14
  CMP r1,r14
  JMP[EQ] @mth_dce_invalid
mth_dce_preflight_next:
  ADDI r10,r10,1
  MOVI r14,256
  CMP r10,r14
  JMP[LT] @mth_dce_preflight_logit
  ADDI r9,r9,1
  LD r11,r8,261
  CMP r9,r11
  JMP[LT] @mth_dce_preflight_record

  MOVI r11,0
  ST r11,r8,264            ; index
  ST r11,r8,265            ; before sum
  ST r11,r8,266            ; after sum

mth_dce_record:
  ; Construct the frozen decoder's logits on an isolated scratch vector.
  ; During development we must compare against CURRENT candidate state,
  ; not silently re-score each new proposal against a zero-weight tensor.
  ; Read-only test mode compares frozen base against the final candidate.
  LD r9,r8,264
  MOVI r11,257
  MUL r11,r9,r11
  LD r12,r8,260
  ADD r12,r12,r11
  LD r14,r12,256
  ST r14,r8,268            ; exact same causal next-byte target
  MOVI r10,0
mth_dce_copy:
  ADD r14,r12,r10
  LD r14,r14,0
  ADD r11,r8,r10
  ST r14,r11,0
  ADDI r10,r10,1
  MOVI r11,256
  CMP r10,r11
  JMP[LT] @mth_dce_copy

  ; dev baseline = frozen logits + existing candidate tile residual.
  ; test baseline = frozen logits; read-only candidate = frozen + tile.
  LD r10,r8,277
  CMP r10,r0
  JMP[EQ] @mth_dce_before_ce
  LD r10,r8,259
  LD r14,r10,1
  LD r10,r8,279
  ADD r11,r8,r10
  LD r12,r11,0
  FADD r12,r12,r14
  ST r12,r11,0

mth_dce_before_ce:
  ADD r1,r8,r0             ; baseline logit scratch
  LD r2,r8,268            ; next-byte target
  ADDI r3,r8,269           ; old CE result
  ADDI r4,r8,271           ; CE subkernel scratch
  CALL @mth_lm_cross_entropy256_f32
  CMP r1,r13
  JMP[NE] @mth_dce_invalid_after_call
  ; CE returns its out pointer in r2. Recover the outer workspace r8.
  ADDI r8,r2,-269
  LD r9,r8,269
  LD r11,r8,265
  FADD r11,r11,r9
  ST r11,r8,265

  ; Only a single mirrored tensor coordinate's CLASS b is perturbed.
  ; The native NaN16 tensor-mapper verified that coordinate already.
  LD r10,r8,279
  ADD r11,r8,r10
  LD r12,r11,0
  LD r14,r8,267             ; dev: proposed effective delta
                             ; test: currently selected tile weight
  FADD r12,r12,r14
  ST r12,r11,0

  ADD r1,r8,r0              ; candidate logits
  LD r2,r8,268             ; *same* true next-byte label
  ADDI r3,r8,270           ; candidate CE
  ADDI r4,r8,271           ; CE scratch
  CALL @mth_lm_cross_entropy256_f32
  CMP r1,r13
  JMP[NE] @mth_dce_invalid_after_call
  ADDI r8,r2,-270
  LD r9,r8,270
  LD r11,r8,266
  FADD r11,r11,r9
  ST r11,r8,266

  LD r9,r8,264
  ADDI r9,r9,1
  ST r9,r8,264
  LD r11,r8,261
  CMP r9,r11
  JMP[LT] @mth_dce_record

  ; Exact aggregate CE admission: only dev mode can alter native credit
  ; and candidate weight; TEST NEVER COMMITS. Small margin avoids noisy ties.
  MOVI r10,0
  LD r9,r8,266             ; after
  MOVI r11,0xD1B7
  MOVHI r11,0x38D1         ; 0.0001 approximately? overridden below
  ; actual binary32 1e-4 = 0x38D1B717
  MOVI r11,0xB717
  MOVHI r11,0x38D1
  FADD r9,r9,r11
  LD r12,r8,265             ; before
  FCMP r12,r9
  JMP[LE] @mth_dce_no_improve
  MOVI r10,1
mth_dce_no_improve:
  LD r11,r8,277
  CMP r11,r0
  JMP[EQ] @mth_dce_publish

  ; Native META EMA credit and candidate tile (only on dev).
  LD r12,r8,278             ; proposer
  LD r9,r8,258              ; credit vector base
  ADD r9,r9,r12
  LD r11,r9,0               ; old credit
  CVTIF r12,r10             ; accepted signal (0 or 1) -> f32
  FSUB r12,r12,r11
  MOVI r14,0
  MOVHI r14,0x3E00         ; 0.125
  FMUL r12,r12,r14
  FADD r11,r11,r12
  ST r11,r9,0              ; updated meta-credit
  CMP r10,r0
  JMP[EQ] @mth_dce_publish
  LD r9,r8,259              ; trusted candidate tile
  LD r11,r9,1
  LD r12,r8,267
  FADD r11,r11,r12
  ST r11,r9,1
mth_dce_publish:
  LD r9,r8,262             ; result pointer
  LD r11,r8,265
  ST r11,r9,0
  LD r11,r8,266
  ST r11,r9,1
  ST r10,r9,2
  LD r11,r8,259
  LD r11,r11,1
  ST r11,r9,3
  LD r11,r8,258
  LD r12,r8,278
  ADD r11,r11,r12
  LD r11,r11,0
  ST r11,r9,4
  LD r11,r8,261
  ST r11,r9,5
  LD r15,r8,263
  MOVI r1,1
  MOVI r9,0
  RET

mth_dce_invalid_after_call:
  ; CE returns r2=output ptr on success. Failure must be treated as
  ; hard rejection: this branch is only reached after preflight, and
  ; should be unreachable for correctly decoded finite logits.
  ; Reconstruct from the known output buffer r2 if needed.
  ADDI r8,r2,-269
mth_dce_invalid:
  LD r15,r8,263
  MOVI r1,0
  MOVI r9,1
  RET
