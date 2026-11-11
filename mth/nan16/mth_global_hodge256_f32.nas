; Native NaN16 global simplicial B1/B2^T incidence on 256 heads.
; Physical root is NOT modified and vector sources are NOT matrixized.
; Pair_flow[p] = directed scalar flow low_head -> high_head, for
; canonical unordered pair p=i*(511-i)/2 + (j-i-1), 0<=i<j<256.
; Selected triangles T[t] = oriented triple (a,b,c), distinct U8 heads.
; Index 255 is reserved zero/VOID: all (a,255) flows must equal signed
; float32 zero and no admitted triangle may reference vertex 255.
; The active mathematical head domain is 0..254. Physical 256-point
; chart and existing head-0 NANNET root authority remain unchanged.
; Computes divergence[a]+=flow(a,b), divergence[b]-=flow(a,b).
; Computes curl[t]=flow(a,b)+flow(b,c)+flow(c,a), with signs depending
; on orientation. Caller admits actual simplicial faces from hot/cold
; observed pair masks: 2/3 candidate motifs are NOT automatically faces.
; ABI (r13=1):
;   r1=pair_flow[32640] f32, r2=triads[16][3] U32, r3=count 0..16,
;   r4=div_out[256] f32, r5=curl_out[16] f32,
;   r6=div_scratch[256], r7=curl_scratch[24] float32/U32 word spans.
; scratch_curl[16..18]=current triple, [19]=index, [20]=saved link,
; [21]=sum. All arrays disjoint. Only outputs published after every
; validation and finite check. r1=1,r9=0 success; r1=0,r9=1 reject.
; No host-language math, no hidden root write, no static scratch.
mth_global_hodge256_f32:
  MOVI r0,0
  ST r15,r7,20
  CMP r3,r0
  JMP[LT] @mth_gh256_reject
  MOVI r8,16
  CMP r3,r8
  JMP[GT] @mth_gh256_reject
  MOVI r14,0
  MOVHI r14,0x7F80
  MOVI r8,0
mth_gh256_gate_flows:
  ADD r9,r1,r8
  LD r9,r9,0
  BOOL.8 r10,r9,r14
  CMP r10,r14
  JMP[EQ] @mth_gh256_reject
  ADDI r8,r8,1
  MOVI r9,32640
  CMP r8,r9
  JMP[LT] @mth_gh256_gate_flows

  MOVI r8,0
mth_gh256_gate_triangles:
  CMP r8,r3
  JMP[GE] @mth_gh256_gate_done
  MOVI r14,3
  MUL r12,r8,r14
  ADD r12,r2,r12
  LD r9,r12,0             ; a
  LD r10,r12,1            ; b
  LD r11,r12,2            ; c
  SHR r14,r9,8
  CMP r14,r0
  JMP[NE] @mth_gh256_reject
  SHR r14,r10,8
  CMP r14,r0
  JMP[NE] @mth_gh256_reject
  SHR r14,r11,8
  CMP r14,r0
  JMP[NE] @mth_gh256_reject
  MOVI r14,255
  CMP r9,r14
  JMP[EQ] @mth_gh256_reject
  CMP r10,r14
  JMP[EQ] @mth_gh256_reject
  CMP r11,r14
  JMP[EQ] @mth_gh256_reject
  CMP r9,r10
  JMP[EQ] @mth_gh256_reject
  CMP r9,r11
  JMP[EQ] @mth_gh256_reject
  CMP r10,r11
  JMP[EQ] @mth_gh256_reject
  ADDI r8,r8,1
  JMP @mth_gh256_gate_triangles
mth_gh256_gate_done:
  MOVI r8,0
mth_gh256_zero_div:
  ADD r9,r6,r8
  ST r0,r9,0
  ADDI r8,r8,1
  MOVI r9,256
  CMP r8,r9
  JMP[LT] @mth_gh256_zero_div
  MOVI r8,0
mth_gh256_zero_curl:
  ADD r9,r7,r8
  ST r0,r9,0
  ADDI r8,r8,1
  MOVI r9,16
  CMP r8,r9
  JMP[LT] @mth_gh256_zero_curl

  ; Global B1 edge incidence in canonical increasing-pair order.
  MOVI r8,0                 ; a
  MOVI r11,0                ; flat pair index
mth_gh256_div_a:
  ADD r9,r8,r13             ; b
mth_gh256_div_b:
  MOVI r12,256
  CMP r9,r12
  JMP[GE] @mth_gh256_div_next_a
  ADD r12,r1,r11
  LD r10,r12,0              ; directed f[a,b]
  ; The physical pair with void head 255 exists, but is not a live
  ; computational lane. Reject nonzero evidence instead of silently using it.
  MOVI r12,255
  CMP r9,r12
  JMP[NE] @mth_gh256_active_pair
  FCMP r10,r0
  JMP[NE] @mth_gh256_reject
  ADDI r11,r11,1
  ADDI r9,r9,1
  JMP @mth_gh256_div_b
mth_gh256_active_pair:
  ADD r12,r6,r8
  LD r14,r12,0
  FADD r14,r14,r10
  ST r14,r12,0
  ADD r12,r6,r9
  LD r14,r12,0
  FSUB r14,r14,r10
  ST r14,r12,0
  ADDI r11,r11,1
  ADDI r9,r9,1
  JMP @mth_gh256_div_b
mth_gh256_div_next_a:
  ADDI r8,r8,1
  MOVI r12,255
  CMP r8,r12
  JMP[LT] @mth_gh256_div_a

  ; Local B2^T: one curl per admitted oriented 2-simplex.
  ST r0,r7,19
mth_gh256_tri_loop:
  LD r12,r7,19
  CMP r12,r3
  JMP[GE] @mth_gh256_check_output
  MOVI r14,3
  MUL r12,r12,r14
  ADD r12,r2,r12
  LD r10,r12,0
  ST r10,r7,16
  LD r10,r12,1
  ST r10,r7,17
  LD r10,r12,2
  ST r10,r7,18

  LD r8,r7,16
  LD r9,r7,17
  CALL @mth_gh256_oriented_edge
  ST r10,r7,21

  LD r8,r7,17
  LD r9,r7,18
  CALL @mth_gh256_oriented_edge
  LD r11,r7,21
  FADD r11,r11,r10
  ST r11,r7,21

  LD r8,r7,18
  LD r9,r7,16
  CALL @mth_gh256_oriented_edge
  LD r11,r7,21
  FADD r11,r11,r10
  LD r12,r7,19
  ADD r12,r7,r12
  ST r11,r12,0

  LD r12,r7,19
  ADDI r12,r12,1
  ST r12,r7,19
  JMP @mth_gh256_tri_loop

  ; Oriented edge lookup. r8=u, r9=v, r10=oriented float32.
  ; Preserves r1-r7 and r13; changes r8-r12 and r14.
mth_gh256_oriented_edge:
  MOVI r11,0
  CMP r8,r9
  JMP[LT] @mth_gh256_edge_sorted
  ADD r12,r8,r0
  ADD r8,r9,r0
  ADD r9,r12,r0
  MOVI r11,1                 ; invert sign for reverse direction
mth_gh256_edge_sorted:
  MOVI r12,511
  SUB r12,r12,r8
  MUL r12,r12,r8
  SHR r12,r12,1
  SUB r14,r9,r8
  ADDI r14,r14,-1
  ADD r12,r12,r14
  ADD r12,r1,r12
  LD r10,r12,0
  CMP r11,r0
  JMP[EQ] @mth_gh256_edge_return
  FSUB r10,r0,r10
mth_gh256_edge_return:
  RET

mth_gh256_check_output:
  MOVI r14,0
  MOVHI r14,0x7F80
  MOVI r8,0
mth_gh256_check_div:
  ADD r9,r6,r8
  LD r9,r9,0
  BOOL.8 r10,r9,r14
  CMP r10,r14
  JMP[EQ] @mth_gh256_reject
  ADDI r8,r8,1
  MOVI r9,256
  CMP r8,r9
  JMP[LT] @mth_gh256_check_div
  MOVI r8,0
mth_gh256_check_curl:
  ADD r9,r7,r8
  LD r9,r9,0
  BOOL.8 r10,r9,r14
  CMP r10,r14
  JMP[EQ] @mth_gh256_reject
  ADDI r8,r8,1
  MOVI r9,16
  CMP r8,r9
  JMP[LT] @mth_gh256_check_curl

  MOVI r8,0
mth_gh256_publish_div:
  ADD r9,r6,r8
  LD r9,r9,0
  ADD r10,r4,r8
  ST r9,r10,0
  ADDI r8,r8,1
  MOVI r10,256
  CMP r8,r10
  JMP[LT] @mth_gh256_publish_div
  MOVI r8,0
mth_gh256_publish_curl:
  ADD r9,r7,r8
  LD r9,r9,0
  ADD r10,r5,r8
  ST r9,r10,0
  ADDI r8,r8,1
  MOVI r10,16
  CMP r8,r10
  JMP[LT] @mth_gh256_publish_curl
  LD r15,r7,20
  MOVI r1,1
  MOVI r9,0
  RET
mth_gh256_reject:
  LD r15,r7,20
  MOVI r1,0
  MOVI r9,1
  RET
