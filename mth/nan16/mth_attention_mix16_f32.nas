; MTH 16-candidate attention/value mix — NaN16 float32 only.
;
; Keeps multiple candidate paths active and mixes their value vectors under
; caller-supplied nonnegative weights:
;
;   out[c] = sum(p=0..15) weight[p] * values[p*16 + c]
;
; This is the readout half of candidate competition. It does not compute
; Q/K scores, softmax, or a projection; the caller owns those. It does not
; select a single path, so contradictory or ambiguous candidates remain
; represented until the caller decides.
;
; ABI (r13=1):
;   r1 = weights[16], f32 word addresses (read-only)
;   r2 = values[16][16] row-major, f32 word addresses (read-only)
;   r3 = out[16], f32 word addresses (written on success)
;   r13 = 1
; Success: r1=1, r9=0, out complete.
; Rejection:
;   cause 1: a weight is non-finite
;   cause 2: a weight is negative
;   cause 3: a value is non-finite
;   r1=0, r9=cause, out untouched. The complete weight/value preflight runs
;   before the first output store.
;
; Numeric order: p increasing for each c, one FMUL then one FADD per term.
; No FMA, no reassociation, no normalization, no host math.
; Clobbers r1-r10 and flags; preserves r0, r11-r15.

mth_attention_mix16_f32:
  MOVI r0,0

  ; ---- weight preflight: finite and >= 0 ----
  MOVI r4,0
  MOVI r9,0
  MOVHI r9,0x7F80
mth_attention_mix16_w_gate:
  ADD r8,r1,r4
  LD r7,r8,0
  BOOL.8 r10,r7,r9
  CMP r10,r9
  JMP[EQ] @mth_attention_mix16_bad_weight
  FCMP r7,r0
  JMP[LT] @mth_attention_mix16_negative_weight
  ADDI r4,r4,1
  MOVI r8,16
  CMP r4,r8
  JMP[LT] @mth_attention_mix16_w_gate

  ; ---- value preflight: all 256 finite ----
  MOVI r4,0
mth_attention_mix16_v_gate:
  ADD r8,r2,r4
  LD r7,r8,0
  BOOL.8 r10,r7,r9
  CMP r10,r9
  JMP[EQ] @mth_attention_mix16_bad_value
  ADDI r4,r4,1
  MOVI r8,256
  CMP r4,r8
  JMP[LT] @mth_attention_mix16_v_gate

  ; ---- output[c] = sum_p w[p] * v[p*16+c] ----
  MOVI r5,0                  ; c
mth_attention_mix16_c_loop:
  MOVI r6,0                  ; acc = +0.0
  MOVI r4,0                  ; p
mth_attention_mix16_p_loop:
  ADD r8,r1,r4
  LD r7,r8,0                 ; weight[p]
  SHL r8,r4,4
  ADD r8,r8,r5
  ADD r8,r2,r8
  LD r8,r8,0                 ; value[p*16+c]
  FMUL r7,r7,r8
  FADD r6,r6,r7
  ADDI r4,r4,1
  MOVI r8,16
  CMP r4,r8
  JMP[LT] @mth_attention_mix16_p_loop

  ADD r8,r3,r5
  ST r6,r8,0
  ADDI r5,r5,1
  MOVI r8,16
  CMP r5,r8
  JMP[LT] @mth_attention_mix16_c_loop

  MOVI r1,1
  MOVI r9,0
  RET

mth_attention_mix16_bad_weight:
  MOVI r9,1
  JMP @mth_attention_mix16_reject
mth_attention_mix16_negative_weight:
  MOVI r9,2
  JMP @mth_attention_mix16_reject
mth_attention_mix16_bad_value:
  MOVI r9,3
mth_attention_mix16_reject:
  MOVI r1,0
  RET
