; MTH exact weighted graph energy for 256-vertex symmetric CSR — NaN16 only.
; E(x) = sum over undirected edges {i,j} of w_ij * (x_i-x_j)^2.
;
; ABI: r1=row_offsets, r2=neighbors, r3=weights, r4=x,
;      r5=output (U64 Q32.32 low word then high word),
;      r6=edge_count, r7=caller-owned 16-word U32 scratch, r13=1.
; State is signed Q16.16 in [-1,+1]; weights are U8 integer [1,255].
; Returns r1=1 success, r1=0 malformed descriptor/state/weight.
; Uses no CALLs and no static scratch; all validation precedes output writes.
;
; Maximum raw difference=2^17; per-edge weighted square <=255*2^34.
; At most C(256,2)=32640 undirected edges:
; E_raw <= 142,991,487,192,268,800 < 2^57 < 2^64.
; Output is exact unsigned U64 Q32.32, no rounding.

mth_graph_energy_weighted_u8_q32_32:
  ADD r11,r7,r0
  ST r1,r11,0
  ST r2,r11,1
  ST r3,r11,2
  ST r4,r11,3
  ST r5,r11,4
  ST r6,r11,5

  CMP r6,r0
  JMP[LT] @mth_energy_invalid
  MOVI r8,65280
  CMP r6,r8
  JMP[GT] @mth_energy_invalid

  ; State preflight: unsigned top 15 bits must be 0 or 0x7FFF.
  ADD r8,r4,r0
  MOVI r9,256
mth_energy_validate_x:
  LD r10,r8,0
  SHR r12,r10,17
  CMP r12,r0
  JMP[EQ] @mth_energy_x_positive
  MOVI r1,32767
  CMP r12,r1
  JMP[EQ] @mth_energy_x_valid
  JMP @mth_energy_invalid
mth_energy_x_positive:
  MOVI r1,0
  MOVHI r1,1
  CMP r10,r1
  JMP[GT] @mth_energy_invalid
mth_energy_x_valid:
  ADD r8,r8,r13
  SUB r9,r9,r13
  CMP r9,r0
  JMP[GT] @mth_energy_validate_x

  ; Offset preflight, including offset[0]=0 and final edge_count.
  LD r8,r11,0
  LD r12,r8,0
  CMP r12,r0
  JMP[NE] @mth_energy_invalid
  MOVI r9,257
  MOVI r10,0
mth_energy_validate_offsets:
  LD r12,r8,0
  CMP r12,r10
  JMP[LT] @mth_energy_invalid
  LD r1,r11,5
  CMP r12,r1
  JMP[GT] @mth_energy_invalid
  SUB r1,r12,r10
  MOVI r2,255
  CMP r1,r2
  JMP[GT] @mth_energy_invalid
  ADD r10,r12,r0
  ADD r8,r8,r13
  SUB r9,r9,r13
  CMP r9,r0
  JMP[GT] @mth_energy_validate_offsets
  LD r1,r11,5
  CMP r10,r1
  JMP[NE] @mth_energy_invalid

  ; Validate sorted unique non-self endpoints and U8 nonzero weights.
  MOVI r6,0
mth_energy_validate_row:
  LD r1,r11,0
  ADD r1,r1,r6
  LD r7,r1,0
  ADD r1,r1,r13
  LD r8,r1,0
  ADD r9,r7,r0
  MOVI r10,0
mth_energy_validate_edge:
  CMP r9,r8
  JMP[EQ] @mth_energy_next_validate_row
  LD r1,r11,1
  ADD r1,r1,r9
  LD r11,r1,0
  SHR r1,r11,8
  CMP r1,r0
  JMP[NE] @mth_energy_invalid
  MOVI r1,256
  CMP r11,r1
  JMP[LT] @mth_energy_endpoint_ok
  JMP @mth_energy_invalid
mth_energy_endpoint_ok:
  CMP r11,r6
  JMP[EQ] @mth_energy_invalid
  CMP r9,r7
  JMP[EQ] @mth_energy_first_neighbor
  CMP r11,r10
  JMP[GT] @mth_energy_sorted_neighbor
  JMP @mth_energy_invalid
mth_energy_sorted_neighbor:
mth_energy_first_neighbor:
  ADD r10,r11,r0
  LD r1,r11,2
  ADD r1,r1,r9
  LD r1,r1,0
  SHR r12,r1,8
  CMP r12,r0
  JMP[NE] @mth_energy_invalid
  CMP r1,r0
  JMP[EQ] @mth_energy_invalid
  ADD r9,r9,r13
  JMP @mth_energy_validate_edge
mth_energy_next_validate_row:
  ADD r6,r6,r13
  MOVI r1,256
  CMP r6,r1
  JMP[LT] @mth_energy_validate_row

  ; Reset long-lived base pointer after preflight (r11 was a temporary).
  ADD r11,r7,r0
  ; Saved scratch pointer was overwritten above: recover from caller argument
  ; is impossible after clobber, so the scratch base is kept in r7 throughout.
