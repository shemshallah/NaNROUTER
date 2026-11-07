; MTH weighted graph quadratic energy v1 — native NaN16.
; E(x) = sum_{undirected edges {u,v}} w_uv * (x[u]-x[v])^2.
;
; ABI:
;   r1=edge_u, r2=edge_v, r3=weights, r4=x, r5=output,
;   r6=edge_count (0..32640), r7=caller-owned 16-word scratch,
;   r13=1.
; Output: unsigned I64 Q32.32, low U32 then high U32.
; State: signed Q16.16 raw in [-65536,+65536] (real [-1,+1]).
; Edges: canonical undirected list, U8 endpoints with u<v, strictly
; lexicographically increasing (u,v); U8 integer weights 1..255.
; All validation completes before output is written. No rounding.
;
; Bound: |x[u]-x[v]| <= 2^17 raw. The squared difference is <=2^34;
; weighted edge energy <=255*2^34 <2^42. At most 32640 edges,
; so total <2^57 and fits unsigned I64. The output scale is Q32.32.
; This is a separately bounded energy ABI; it does not silently widen
; the v2 Laplacian's state domain.

mth_graph_energy_weighted_q16_16_u64_v1:
  ADD r11,r7,r0
  ST r1,r11,0
  ST r2,r11,1
  ST r3,r11,2
  ST r4,r11,3
  ST r5,r11,4
  ST r6,r11,5

  CMP r6,r0
  JMP[LT] @mth_energy_v1_bad_state
  MOVI r8,32640
  CMP r6,r8
  JMP[GT] @mth_energy_v1_bad_state

  ; Validate all 256 signed Q16.16 states in [-1,+1].
  ADD r8,r4,r0
  MOVI r9,256
mth_energy_v1_validate_x:
  LD r10,r8,0
  SHR r12,r10,16
  CMP r12,r0
  JMP[EQ] @mth_energy_v1_x_valid
  MOVI r1,65535
  CMP r12,r1
  JMP[EQ] @mth_energy_v1_x_valid
  MOVI r1,1
  CMP r12,r1
  JMP[NE] @mth_energy_v1_bad_state
  MOVI r1,65536
  CMP r10,r1
  JMP[NE] @mth_energy_v1_bad_state
mth_energy_v1_x_valid:
  ADD r8,r8,r13
  SUB r9,r9,r13
  CMP r9,r0
  JMP[GT] @mth_energy_v1_validate_x

  ; Validate canonical edge list and every weight before touching output.
  LD r8,r11,0
  LD r9,r11,1
  LD r10,r11,2
  LD r12,r11,5
  MOVI r7,0
mth_energy_v1_validate_edges:
  CMP r12,r0
  JMP[EQ] @mth_energy_v1_apply_setup
  LD r1,r8,0
  LD r2,r9,0
  SHR r3,r1,8
  CMP r3,r0
  JMP[NE] @mth_energy_v1_bad_edge
  SHR r3,r2,8
  CMP r3,r0
  JMP[NE] @mth_energy_v1_bad_edge
  CMP r1,r2
  JMP[LT] @mth_energy_v1_endpoint_order_ok
  JMP @mth_energy_v1_bad_edge
mth_energy_v1_endpoint_order_ok:
  ; Enforce strict lexicographic ordering using key=(u<<8)|v.
  SHL r3,r1,8
  BOOL.14 r3,r3,r2
  CMP r3,r7
  JMP[GT] @mth_energy_v1_key_order_ok
  JMP @mth_energy_v1_bad_edge
mth_energy_v1_key_order_ok:
  ADD r7,r3,r0
  LD r3,r10,0
  SHR r4,r3,8
  CMP r4,r0
  JMP[NE] @mth_energy_v1_bad_weight
  CMP r3,r0
  JMP[EQ] @mth_energy_v1_bad_weight
  ADD r8,r8,r13
  ADD r9,r9,r13
  ADD r10,r10,r13
  SUB r12,r12,r13
  JMP @mth_energy_v1_validate_edges

mth_energy_v1_apply_setup:
  MOVI r1,0
  ST r1,r11,6
  ST r1,r11,7
  ST r1,r11,8

mth_energy_v1_edge_loop:
  LD r8,r11,6
  LD r9,r11,5
  CMP r8,r9
  JMP[LT] @mth_energy_v1_edge_body
  JMP @mth_energy_v1_finish
mth_energy_v1_edge_body:
  LD r1,r11,0
  ADD r1,r1,r8
  LD r2,r1,0
  LD r1,r11,1
  ADD r1,r1,r8
  LD r3,r1,0
  LD r1,r11,3
  ADD r1,r1,r2
  LD r4,r1,0
  LD r1,r11,3
  ADD r1,r1,r3
  LD r5,r1,0
  SUB r1,r4,r5
  SHR r2,r1,31
  CMP r2,r0
  JMP[EQ] @mth_energy_v1_abs_ready
  SUB r1,r0,r1
mth_energy_v1_abs_ready:
  ST r1,r11,9

  ; Exact 32x32 -> 64 square by shift-and-add.
  MOVI r3,0
  MOVI r4,0
  MOVI r5,0
  ADD r6,r1,r0
  ADD r7,r1,r0
  MOVI r8,32
mth_energy_v1_square_loop:
  MOVI r10,1
  BOOL.8 r9,r7,r10
  CMP r9,r0
  JMP[EQ] @mth_energy_v1_square_shift
  ADD r10,r4,r0
  ADD r4,r4,r6
  CMP r4,r10
  JMP[LT] @mth_energy_v1_square_carry
  ADD r3,r3,r5
  JMP @mth_energy_v1_square_shift
mth_energy_v1_square_carry:
  ADD r3,r3,r5
  ADD r3,r3,r13
mth_energy_v1_square_shift:
  SHR r9,r6,31
  SHL r6,r6,1
  SHL r5,r5,1
  BOOL.14 r5,r5,r9
  SHR r7,r7,1
  SUB r8,r8,r13
  CMP r8,r0
  JMP[GT] @mth_energy_v1_square_loop
  ST r4,r11,14
  ST r3,r11,15

  ; Multiply the 64-bit square by its U8 weight using eight shift/add
  ; rounds. Product remains below 2^42 by the ABI proof.
  LD r1,r11,6
  LD r2,r11,2
  ADD r2,r2,r1
  LD r7,r2,0
  LD r6,r11,14
  LD r5,r11,15
  MOVI r3,0
  MOVI r4,0
  MOVI r8,8
mth_energy_v1_weight_loop:
  MOVI r10,1
  BOOL.8 r9,r7,r10
  CMP r9,r0
  JMP[EQ] @mth_energy_v1_weight_shift
  ADD r10,r3,r0
  ADD r3,r3,r6
  CMP r3,r10
  JMP[LT] @mth_energy_v1_weight_carry
  ADD r4,r4,r5
  JMP @mth_energy_v1_weight_shift
mth_energy_v1_weight_carry:
  ADD r4,r4,r5
  ADD r4,r4,r13
mth_energy_v1_weight_shift:
  SHR r9,r6,31
  SHL r6,r6,1
  SHL r5,r5,1
  BOOL.14 r5,r5,r9
  SHR r7,r7,1
  SUB r8,r8,r13
  CMP r8,r0
  JMP[GT] @mth_energy_v1_weight_loop

  ; Add weighted edge contribution to the unsigned I64 total.
  LD r6,r11,7
  LD r7,r11,8
  ADD r8,r6,r0
  ADD r6,r6,r3
  CMP r6,r8
  JMP[LT] @mth_energy_v1_total_carry
  ADD r7,r7,r4
  JMP @mth_energy_v1_total_store
mth_energy_v1_total_carry:
  ADD r7,r7,r4
  ADD r7,r7,r13
mth_energy_v1_total_store:
  ST r6,r11,7
  ST r7,r11,8
  LD r8,r11,6
  ADD r8,r8,r13
  ST r8,r11,6
  JMP @mth_energy_v1_edge_loop

mth_energy_v1_finish:
  LD r1,r11,4
  LD r2,r11,7
  LD r3,r11,8
  ST r2,r1,0
  ST r3,r1,1
  MOVI r1,1
  RET

mth_energy_v1_bad_state:
  MOVI r1,0
  RET
mth_energy_v1_bad_edge:
  MOVI r1,2
  RET
mth_energy_v1_bad_weight:
  MOVI r1,3
  RET
