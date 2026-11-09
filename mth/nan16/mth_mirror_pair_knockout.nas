; MTH causal pair knockout/restore — NaN16 float32 transport.
;
; Saves the 26 residual slots of both physical lanes of one mirror pair into a
; caller-owned 52-word backup, then either:
;
;   mode 0: backup + zero both residual lanes (causal deletion)
;   mode 1: restore both residual lanes from the backup
;
; Lane 0 residual words are record base + 0..25; lane 1 residual words are
; record base + 32..57. Metadata words 26..31 on lane 0 and the reserved lane-1
; tail are never touched. This is a physical evidence knockout, not a semantic
; truth operation.
;
; ABI (r13=1):
;   r1 = pair id, 1..32640
;   r2 = backup, 52 float32 word addresses:
;        [0..25] lane 0 residuals, [26..51] lane 1 residuals
;   r3 = mode, 0 = save+zero, 1 = restore
; Success: r1=1, r9=0.
; Rejection: r1=0, r9=1 bad pair id, r9=2 bad mode; no backup/lane word is
; written on rejection. The caller owns extents and aliasing.
;
; Register effects: r0=0; r1-r8 and flags clobbered; r9-r15 preserved except
; r9 receives the status cause on rejection. No float arithmetic, host math,
; static storage, or allocation is used.

mth_mirror_pair_knockout_f32:
  MOVI r0,0

  ; pair id 1..32640
  CMP r1,r0
  JMP[EQ] @mth_pair_knockout_bad_id
  MOVI r4,32640
  CMP r4,r1
  JMP[LT] @mth_pair_knockout_bad_id

  ; mode 0 or 1
  MOVI r4,1
  CMP r4,r3
  JMP[LT] @mth_pair_knockout_bad_mode

  ; record word base = 8192 + (id-1)*64
  ADDI r5,r1,-1
  SHL r5,r5,6
  ADDI r5,r5,8192

  MOVI r4,0                  ; i=0
mth_pair_knockout_loop:
  ADD r6,r5,r4               ; lane0 word
  ADDI r7,r5,32
  ADD r7,r7,r4               ; lane1 word

  CMP r3,r0
  JMP[NE] @mth_pair_knockout_restore

  ; save+zero
  LD r8,r6,0
  ADD r6,r2,r4
  ST r8,r6,0                 ; backup[i]
  LD r8,r7,0
  ADDI r6,r4,26
  ADD r6,r2,r6
  ST r8,r6,0                 ; backup[26+i]
  ADD r6,r5,r4
  ST r0,r6,0                 ; zero lane0 (address base+i)
  ADDI r6,r5,32
  ADD r6,r6,r4
  ST r0,r6,0                 ; zero lane1
  JMP @mth_pair_knockout_next

mth_pair_knockout_restore:
  ADD r6,r2,r4
  LD r8,r6,0
  ADD r6,r5,r4
  ST r8,r6,0
  ADDI r6,r4,26
  ADD r6,r2,r6
  LD r8,r6,0
  ADDI r6,r5,32
  ADD r6,r6,r4
  ST r8,r6,0

mth_pair_knockout_next:
  ADDI r4,r4,1
  MOVI r6,26
  CMP r4,r6
  JMP[LT] @mth_pair_knockout_loop

  MOVI r1,1
  MOVI r9,0
  RET

mth_pair_knockout_bad_id:
  MOVI r9,1
  JMP @mth_pair_knockout_reject
mth_pair_knockout_bad_mode:
  MOVI r9,2
mth_pair_knockout_reject:
  MOVI r1,0
  RET
