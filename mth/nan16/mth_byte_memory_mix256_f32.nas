; MTH 256-byte base/memory probability interpolation — NaN16 float32 only.
;
;   out[i] = (1 - weight) * base[i] + weight * memory[i]
;
; This is the Round 043 memory-conditioned next-byte seam. The caller supplies
; the frozen base probabilities and the associative-memory probabilities; the
; kernel does not train, normalize, or decide the cache gate.
;
; ABI (r13=1):
;   r1 = base[256], float32 word addresses
;   r2 = memory[256], float32 word addresses
;   r3 = weight, finite f32 in [0,1]
;   r4 = out[256], written on success only
;   r13 = 1
; Success: r1=1, r9=0.
; Rejection:
;   cause 1: weight non-finite or outside [0,1]
;   cause 2: base non-finite
;   cause 3: memory non-finite
;   out untouched.
;
; Numeric order: inv=1-weight (FSUB), then per i: (inv*base) + (weight*memory),
; one FMUL, one FMUL, one FADD. No FMA, reassociation, or host math.

mth_byte_memory_mix256_f32:
  MOVI r0,0

  ; weight finite
  MOVI r9,0
  MOVHI r9,0x7F80
  BOOL.8 r10,r3,r9
  CMP r10,r9
  JMP[EQ] @mth_memory_mix_bad_weight
  FCMP r3,r0
  JMP[LT] @mth_memory_mix_bad_weight
  MOVI r9,0
  MOVHI r9,0x3F80
  FCMP r3,r9
  JMP[GT] @mth_memory_mix_bad_weight

  ; base finite
  MOVI r9,0
  MOVHI r9,0x7F80
  MOVI r5,0
mth_memory_mix_base_gate:
  ADD r8,r1,r5
  LD r7,r8,0
  BOOL.8 r10,r7,r9
  CMP r10,r9
  JMP[EQ] @mth_memory_mix_bad_base
  ADDI r5,r5,1
  MOVI r8,256
  CMP r5,r8
  JMP[LT] @mth_memory_mix_base_gate

  ; memory finite
  MOVI r5,0
mth_memory_mix_mem_gate:
  ADD r8,r2,r5
  LD r7,r8,0
  BOOL.8 r10,r7,r9
  CMP r10,r9
  JMP[EQ] @mth_memory_mix_bad_memory
  ADDI r5,r5,1
  MOVI r8,256
  CMP r5,r8
  JMP[LT] @mth_memory_mix_mem_gate

  ; inv = 1 - weight
  MOVI r6,0
  MOVHI r6,0x3F80
  FSUB r6,r6,r3

  MOVI r5,0
mth_memory_mix_loop:
  ADD r8,r1,r5
  LD r7,r8,0
  FMUL r7,r7,r6              ; inv*base
  ADD r10,r2,r5
  LD r10,r10,0
  FMUL r10,r10,r3            ; weight*memory
  FADD r7,r7,r10
  ADD r8,r4,r5
  ST r7,r8,0
  ADDI r5,r5,1
  MOVI r8,256
  CMP r5,r8
  JMP[LT] @mth_memory_mix_loop

  MOVI r1,1
  MOVI r9,0
  RET

mth_memory_mix_bad_weight:
  MOVI r9,1
  JMP @mth_memory_mix_reject
mth_memory_mix_bad_base:
  MOVI r9,2
  JMP @mth_memory_mix_reject
mth_memory_mix_bad_memory:
  MOVI r9,3
mth_memory_mix_reject:
  MOVI r1,0
  RET
