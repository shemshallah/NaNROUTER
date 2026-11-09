; MTH two-lane native evidence state — NaN16 float32 only.
;
; Reads the support (channel 0) and explicit-refutation (channel 1) triangle
; circulations for the anchored triangle (0,a,b):
;
;   F_c = E_c(0,a) + E_c(a,b) - E_c(0,b)
;
; and classifies the four paraconsistent states:
;
;   state 0 unknown : support <= 0 and refute <= 0
;   state 1 support : support > 0 and refute <= 0
;   state 2 refute  : support <= 0 and refute > 0
;   state 3 both    : support > 0 and refute > 0
;
; A contradiction is preserved rather than collapsed. The state is a typed
; classification of two continuous lanes; it is not a truth probability.
;
; ABI (r13=1):
;   r1 = a, 1..254
;   r2 = b, a+1..255
; Success:
;   r1 = 1, r9 = 0
;   r3 = support circulation (f32 payload)
;   r4 = refute circulation (f32 payload)
;   r5 = state 0..3
; Rejection:
;   r1 = 0, r9 = 1 for an invalid head pair
;   r1 = 0, r9 = 2 for a non-finite lane/result
;   r3-r5 are cleared on rejection.
;
; Channel addressing uses the canonical physical pair geometry:
;   pair id (0,a)=a; (a,b)=1+a*(511-a)/2; (0,b)=b
;   word = 8192 + (pair_id-1)*64 + channel
; No writes, host math, static storage, or allocation. Clobbers r1-r10 and
; flags; preserves r0, r11-r15.

mth_mirror_evidence_cycle_state_f32:
  MOVI r0,0

  ; ---- canonical head pair domain ----
  CMP r1,r0
  JMP[EQ] @mth_evidence_state_bad_pair
  MOVI r6,254
  CMP r6,r1
  JMP[LT] @mth_evidence_state_bad_pair
  MOVI r6,255
  CMP r6,r2
  JMP[LT] @mth_evidence_state_bad_pair
  CMP r2,r1
  JMP[LE] @mth_evidence_state_bad_pair

  ; ---- support channel 0 ----
  ; word (0,a)
  ADDI r7,r1,-1
  SHL r7,r7,6
  ADDI r7,r7,8192
  LD r8,r7,0                 ; E0(0,a)
  ; word (a,b) = 8192 + (a*(511-a)/2)*64
  MOVI r9,511
  SUB r9,r9,r1
  MUL r9,r1,r9
  SHR r9,r9,1
  SHL r9,r9,6
  ADDI r9,r9,8192
  LD r10,r9,0                ; E0(a,b)
  FADD r8,r8,r10
  ; word (0,b)
  ADDI r7,r2,-1
  SHL r7,r7,6
  ADDI r7,r7,8192
  LD r10,r7,0                ; E0(0,b)
  FSUB r8,r8,r10             ; support flux
  MOVI r9,0
  MOVHI r9,0x7F80
  BOOL.8 r10,r8,r9
  CMP r10,r9
  JMP[EQ] @mth_evidence_state_bad_value

  ; ---- refute channel 1 (word +1) ----
  ADDI r7,r1,-1
  SHL r7,r7,6
  ADDI r7,r7,8193
  LD r10,r7,0
  MOVI r9,511
  SUB r9,r9,r1
  MUL r9,r1,r9
  SHR r9,r9,1
  SHL r9,r9,6
  ADDI r9,r9,8193
  LD r7,r9,0
  FADD r10,r10,r7
  ADDI r7,r2,-1
  SHL r7,r7,6
  ADDI r7,r7,8193
  LD r7,r7,0
  FSUB r10,r10,r7             ; refute flux
  MOVI r9,0
  MOVHI r9,0x7F80
  BOOL.8 r7,r10,r9
  CMP r7,r9
  JMP[EQ] @mth_evidence_state_bad_value

  ; ---- classify positive evidence in each lane ----
  MOVI r5,0
  FCMP r8,r0
  JMP[LE] @mth_evidence_state_no_support
  MOVI r5,1
mth_evidence_state_no_support:
  FCMP r10,r0
  JMP[LE] @mth_evidence_state_publish
  ADDI r5,r5,2

mth_evidence_state_publish:
  ADD r3,r8,r0
  ADD r4,r10,r0
  MOVI r1,1
  MOVI r9,0
  RET

mth_evidence_state_bad_pair:
  MOVI r9,1
  JMP @mth_evidence_state_reject
mth_evidence_state_bad_value:
  MOVI r9,2
mth_evidence_state_reject:
  MOVI r3,0
  MOVI r4,0
  MOVI r5,0
  MOVI r1,0
  RET
