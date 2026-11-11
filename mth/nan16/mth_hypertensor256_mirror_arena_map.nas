; Native NaN16 address resolver for a rank-3 256^3 tensor whose last
; two axes use the canonical palindromic mirror-pair geometry.
;
; This is an EXTERNAL TENSOR ARENA, not an extension of the 8 MiB root.
; Each h bank is 256 KiB: 256 diagonal values + 32,640 paired cells
; with two independent directional f32 values = 65,536 f32 slots.
; 256 banks = 64 MiB total, full shape 256x256x256.
;
; Native mathematical head 255 is ZERO/VOID. A read or write request for
; h=255, a=255 or b=255 is rejected, not remapped onto 254.
; Raw address capacity includes reserved slots, but training MUST NOT write
; these and MUST NOT treat physical head 0 as an unpermissioned writer.
;
; For h,a,b in 0..254:
;   base = h * 262144                         (h << 18)
;   a == b: cell = a; lane = 0;
;           byte_offset = base + 4*a
;   a != b: low=min(a,b), high=max(a,b)
;           p0 = low*(511-low)/2 + high-low-1
;           cell = 256+p0; lane = (a>b) ? 1 : 0
;           byte_offset = base + 1024 + 8*p0 + 4*lane
; A mirror pair is one identity with two oriented data words; its two
; values are NOT forced to be negatives, equal, or otherwise symmetric.
;
; ABI: r1=h, r2=a, r3=b; requires r13=1.
; success: r1=1, r4=canonical cell [0,32895], r5=lane [0,1],
;          r6=byte offset in [0,67108864), divisible by 4.
; reject:  r1=0, r4=r5=r6=0, no memory writes.
; r0,r1,r4-r7 and flags clobbered. r2,r3,r8-r15 preserved.
; This resolver computes addresses only. All arena admission, bounds,
; finiteness, permissions, generation, and transactional writes belong
; to the native external-arena controller, NOT the host-language model.
; No model arithmetic or data updates occur in this routine.

mth_hypertensor256_mirror_arena_map:
  MOVI r0,0
  MOVI r7,254
  CMP r7,r1
  JMP[LT] @mth_h256_map_reject
  CMP r7,r2
  JMP[LT] @mth_h256_map_reject
  CMP r7,r3
  JMP[LT] @mth_h256_map_reject

  ; Full 256-wide physical bank stride, including reserved slot 255.
  SHL r6,r1,18
  CMP r2,r3
  JMP[NE] @mth_h256_map_pair

  ; Palindromic fixed point: a == b.
  ADD r4,r2,r0
  MOVI r5,0
  SHL r7,r2,2
  ADD r6,r6,r7
  MOVI r1,1
  RET

mth_h256_map_pair:
  ADD r4,r2,r0             ; low candidate
  ADD r5,r3,r0             ; high candidate
  MOVI r7,0               ; low->high lane
  CMP r2,r3
  JMP[LT] @mth_h256_map_ordered
  ADD r4,r3,r0
  ADD r5,r2,r0
  MOVI r7,1               ; high->low lane

mth_h256_map_ordered:
  ; Zero-based canonical off-diagonal pair ordinal.
  MOVI r1,511
  SUB r1,r1,r4
  MUL r1,r1,r4
  SHR r1,r1,1
  SUB r5,r5,r4
  ADDI r5,r5,-1
  ADD r1,r1,r5

  ; Reserve first 256 values for fixed points (diagonal head cells).
  MOVI r4,256
  ADD r4,r4,r1
  SHL r5,r1,3             ; 8 bytes per mirror pair, 2 f32 directions
  ADDI r5,r5,1024         ; diagonal block = 256 * 4 bytes
  ADD r6,r6,r5
  SHL r5,r7,2             ; high->low word is +4 bytes
  ADD r6,r6,r5
  ADD r5,r7,r0
  MOVI r1,1
  RET

mth_h256_map_reject:
  MOVI r1,0
  MOVI r4,0
  MOVI r5,0
  MOVI r6,0
  RET
