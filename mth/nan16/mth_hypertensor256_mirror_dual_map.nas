; Full 128 MiB address extension for two COMPLETE rank-3 mirrored tensors.
;
; bank 0 = 64 MiB active tensor; bank 1 = 64 MiB candidate tensor.
; Each bank contains all 256^3 independent directed float32 coordinates.
; Every (h,a,b) retains its canonical (a,b) mirror identity and independent
; opposite-direction 32-bit values. No symmetry/antisymmetry is imposed.
;
; This mapper is address arithmetic only. It does not allocate the backing,
; grant native head permissions, read weights or promote a candidate bank.
; All trihead proposals must flow through meta-feedback and an admitted
; native commit path; no proposer can directly modify bank0 by this function.
;
; ABI:
;    r1=h, r2=a, r3=b, r8=bank(0 active,1 candidate), r13=1
;    success r1=1, r4=canonical cell, r5=orientation,
;            r6=absolute byte offset within 128 MiB [0,134217728)
;    reject r1=0, r4=r5=r6=0
;    r0,r1,r4-r7,r9,r11 clobbered, r2,r3,r8,r10,r12-r15 preserved.
;    r15 is preserved across nested CALL.
;
; WARNING: semantic coordinate 255 is void and rejected on ALL axes even
; though it still occupies real physical address capacity. The 8 MiB root
; remains a separate unchanged authoritative universe.
mth_hypertensor256_mirror_dual_map:
  MOVI r0,0
  SHR r9,r8,1             ; only bank 0 and 1 are valid
  CMP r9,r0
  JMP[NE] @mth_h256_dual_invalid
  ADD r11,r15,r0
  CALL @mth_hypertensor256_mirror_arena_map
  ADD r15,r11,r0
  CMP r1,r13
  JMP[NE] @mth_h256_dual_invalid
  SHL r9,r8,26            ; 64 MiB per complete 256^3 f32 tensor
  ADD r6,r6,r9
  MOVI r1,1
  RET

mth_h256_dual_invalid:
  MOVI r1,0
  MOVI r4,0
  MOVI r5,0
  MOVI r6,0
  RET
