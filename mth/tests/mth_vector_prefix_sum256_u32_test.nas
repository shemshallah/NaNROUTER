; MTH inclusive prefix sum256 u32 fixture — NaN16 only.
;
; Every phase checks all 256 output words with integer CMP. Input values are
; generated at runtime; no host-side expected-value arithmetic is used.
;
; Phase 1: x[i] = i+1; out[i] = (i+1)(i+2)/2 (triangular numbers).
; Phase 2: all x[i] = 0; all out[i] = 0.
; Phase 3: x[0] = UINT32_MAX, x[1..255] = 0; all out[i] = UINT32_MAX.
; Phase 4: all x[i] = UINT32_MAX; overflow at i=1. out[0] is the seed and
;          out[1..255] are the 0xFFFFFFFF marker; r1=0.
; Phase 5: x[0] = 0xFFFFFF80, x[1..255] = 1; overflow at i=128. out[0..127]
;          are 0xFFFFFF80+i and out[128..255] are the 0xFFFFFFFF marker.
; Phase 6: exact alias out==x on the phase-1 ramp; checks all 256 results.
; Phase 7: exact alias out==x on the phase-5 overflow input; checks all 256
;          prefix/marker words after the input span has been overwritten.
;
; The output is pre-filled with 0xDEADBEEF before phases 1-5 so an unwritten
; word cannot pass by inheriting a previous phase's value.

.org 0
JMP @mth_psum_main
.include "../nan16/mth_vector_prefix_sum256_u32.nas"

mth_psum_main:
  MOVI r13,1

  ; ---- Phase 1: x[i] = i+1, out[i] = triangular(i+1). ----
  MOVI r1,@mth_psum_out
  MOVI r2,256
  MOVI r4,0xDEAD
  MOVHI r4,0xBEEF
  CALL @mth_psum_fill_const

  MOVI r1,@mth_psum_x
  MOVI r2,256
  MOVI r4,1
  CALL @mth_psum_fill_ramp

  MOVI r1,@mth_psum_x
  MOVI r2,@mth_psum_out
  CALL @mth_vector_prefix_sum256_u32
  CMP r1,r13
  JMP[NE] @mth_psum_fail

  MOVI r1,@mth_psum_out
  MOVI r2,256
  CALL @mth_psum_check_tri

  ; ---- Phase 2: all-zero input. ----
  MOVI r1,@mth_psum_out
  MOVI r2,256
  MOVI r4,0xDEAD
  MOVHI r4,0xBEEF
  CALL @mth_psum_fill_const

  MOVI r1,@mth_psum_x
  MOVI r2,256
  MOVI r4,0
  CALL @mth_psum_fill_const

  MOVI r1,@mth_psum_x
  MOVI r2,@mth_psum_out
  CALL @mth_vector_prefix_sum256_u32
  CMP r1,r13
  JMP[NE] @mth_psum_fail

  MOVI r1,@mth_psum_out
  MOVI r2,256
  MOVI r4,0
  CALL @mth_psum_check_const

  ; ---- Phase 3: maximum first word plus 255 zeros (no overflow). ----
  MOVI r1,@mth_psum_out
  MOVI r2,256
  MOVI r4,0xDEAD
  MOVHI r4,0xBEEF
  CALL @mth_psum_fill_const

  MOVI r1,@mth_psum_x
  MOVI r2,256
  MOVI r4,0
  CALL @mth_psum_fill_const
  MOVI r1,@mth_psum_x
  MOVI r4,0xFFFF
  MOVHI r4,0xFFFF
  ST r4,r1,0

  MOVI r1,@mth_psum_x
  MOVI r2,@mth_psum_out
  CALL @mth_vector_prefix_sum256_u32
  CMP r1,r13
  JMP[NE] @mth_psum_fail

  MOVI r1,@mth_psum_out
  MOVI r2,256
  MOVI r4,0xFFFF
  MOVHI r4,0xFFFF
  CALL @mth_psum_check_const

  ; ---- Phase 4: all-maximum input overflows at i=1. ----
  MOVI r1,@mth_psum_out
  MOVI r2,256
  MOVI r4,0xDEAD
  MOVHI r4,0xBEEF
  CALL @mth_psum_fill_const

  MOVI r1,@mth_psum_x
  MOVI r2,256
  MOVI r4,0xFFFF
  MOVHI r4,0xFFFF
  CALL @mth_psum_fill_const  ; all x[i] = 0xFFFFFFFF

  MOVI r1,@mth_psum_x
  MOVI r2,@mth_psum_out
  CALL @mth_vector_prefix_sum256_u32
  CMP r1,r0
  JMP[NE] @mth_psum_fail     ; overflow must return r1=0

  MOVI r1,@mth_psum_out
  MOVI r2,256
  MOVI r4,0xFFFF
  MOVHI r4,0xFFFF
  CALL @mth_psum_check_const ; seed and full marker suffix are all UINT32_MAX

  ; ---- Phase 5: overflow at i=128, partial prefix plus marker suffix. ----
  MOVI r1,@mth_psum_out
  MOVI r2,256
  MOVI r4,0xDEAD
  MOVHI r4,0xBEEF
  CALL @mth_psum_fill_const

  MOVI r1,@mth_psum_x
  MOVI r4,0xFF80
  MOVHI r4,0xFFFF            ; x[0] = 0xFFFFFF80
  ST r4,r1,0
  ADD r1,r1,r13
  MOVI r2,255
  MOVI r4,1
  CALL @mth_psum_fill_const  ; x[1..255] = 1

  MOVI r1,@mth_psum_x
  MOVI r2,@mth_psum_out
  CALL @mth_vector_prefix_sum256_u32
  CMP r1,r0
  JMP[NE] @mth_psum_fail     ; overflow must return r1=0

  MOVI r1,@mth_psum_out
  CALL @mth_psum_check_overflow

  ; ---- Phase 6: exact alias out==x, successful ramp. ----
  MOVI r1,@mth_psum_x
  MOVI r2,256
  MOVI r4,1
  CALL @mth_psum_fill_ramp

  MOVI r1,@mth_psum_x
  MOVI r2,@mth_psum_x
  CALL @mth_vector_prefix_sum256_u32
  CMP r1,r13
  JMP[NE] @mth_psum_fail

  MOVI r1,@mth_psum_x
  MOVI r2,256
  CALL @mth_psum_check_tri

  ; ---- Phase 7: exact alias out==x, overflow at i=128. ----
  MOVI r1,@mth_psum_x
  MOVI r4,0xFF80
  MOVHI r4,0xFFFF            ; x[0] = 0xFFFFFF80
  ST r4,r1,0
  ADD r1,r1,r13
  MOVI r2,255
  MOVI r4,1
  CALL @mth_psum_fill_const  ; x[1..255] = 1

  MOVI r1,@mth_psum_x
  MOVI r2,@mth_psum_x
  CALL @mth_vector_prefix_sum256_u32
  CMP r1,r0
  JMP[NE] @mth_psum_fail

  MOVI r1,@mth_psum_x
  CALL @mth_psum_check_overflow

  MOVI r1,@mth_psum_pass
  CALL @mth_psum_puts
  HALT

mth_psum_fail:
  MOVI r1,@mth_psum_bad
  CALL @mth_psum_puts
  HALT

; r1 = destination, r2 = count, r4 = payload. Clobbers r1, r2.
mth_psum_fill_const:
  ST r4,r1,0
  ADD r1,r1,r13
  SUB r2,r2,r13
  CMP r2,r0
  JMP[GT] @mth_psum_fill_const
  RET

; r1 = destination, r2 = count, r4 = first value. Clobbers r1, r2, r4.
mth_psum_fill_ramp:
  ST r4,r1,0
  ADD r1,r1,r13
  ADD r4,r4,r13
  SUB r2,r2,r13
  CMP r2,r0
  JMP[GT] @mth_psum_fill_ramp
  RET

; r1 = output, r2 = count, r4 = expected payload. Clobbers r1, r2, r5.
mth_psum_check_const:
  LD r5,r1,0
  CMP r5,r4
  JMP[NE] @mth_psum_fail
  ADD r1,r1,r13
  SUB r2,r2,r13
  CMP r2,r0
  JMP[GT] @mth_psum_check_const
  RET

; r1 = output, r2 = count. Expected out[i] = (i+1)(i+2)/2.
; Clobbers r1, r2, r4-r6.
mth_psum_check_tri:
  MOVI r4,1                  ; n = i+1
mth_psum_check_tri_loop:
  ADD r5,r4,r13              ; n+1
  MUL r6,r4,r5               ; n(n+1)
  SHR r6,r6,1                ; /2
  LD r5,r1,0
  CMP r5,r6
  JMP[NE] @mth_psum_fail
  ADD r1,r1,r13
  ADD r4,r4,r13
  SUB r2,r2,r13
  CMP r2,r0
  JMP[GT] @mth_psum_check_tri_loop
  RET

; r1 = output. Check the phase-5/7 overflow result:
;   out[k] = 0xFFFFFF80+k for k=0..127, out[k] = 0xFFFFFFFF for k=128..255.
; Clobbers r1, r2, r4, r5.
mth_psum_check_overflow:
  MOVI r2,128
  MOVI r4,0xFF80
  MOVHI r4,0xFFFF
mth_psum_check_overflow_prefix:
  LD r5,r1,0
  CMP r5,r4
  JMP[NE] @mth_psum_fail
  ADD r1,r1,r13
  ADD r4,r4,r13
  SUB r2,r2,r13
  CMP r2,r0
  JMP[GT] @mth_psum_check_overflow_prefix

  MOVI r2,128
  MOVI r4,0xFFFF
  MOVHI r4,0xFFFF
mth_psum_check_overflow_marker:
  LD r5,r1,0
  CMP r5,r4
  JMP[NE] @mth_psum_fail
  ADD r1,r1,r13
  SUB r2,r2,r13
  CMP r2,r0
  JMP[GT] @mth_psum_check_overflow_marker
  RET

mth_psum_puts:
  MOVI r4,255
mth_psum_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_psum_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_psum_puts_byte
  ADD r1,r1,r13
  JMP @mth_psum_puts_word

.org 1024
mth_psum_x:
.word 0
.org 2048
mth_psum_out:
.word 0
.org 4096
mth_psum_pass:
.str "MTH VECTOR PREFIX SUM256 U32 PASS\n"
mth_psum_bad:
.str "MTH VECTOR PREFIX SUM256 U32 FAIL\n"
