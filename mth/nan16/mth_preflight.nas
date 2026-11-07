; MTH typed-object preflight gate — NaN16 only.
;
; This is an execution gate, NOT a second function registry. The caller passes
; the canonical operator contract resolved by the existing MC0/NaN0S registry
; and the concrete typed leaf descriptors. The gate checks applicability and
; reserves no memory. The output descriptor is committed only after every
; check succeeds.
;
; Object descriptor (8 NaN16 words):
;   [0] kind [1] rank [2] dim0 [3] dim1 [4] domain
;   [5] payload_word_address [6] payload_words [7] flags
; Contract descriptor (10 words):
;   [0] left_kind [1] right_kind [2] output_kind
;   [3] left_rank [4] right_rank [5] output_rank
;   [6] domain [7] shape_rule [8] required_capability_bits
;   [9] precondition_bits
; Output descriptor uses the same 8-word layout. Its payload address and
; capacity at [5]/[6] must be reserved by the caller before preflight.
;
; Shape rules:
;   0 = equal shapes (elementwise / shape-preserving relation)
;   1 = vector dot: rank-1 equal dimensions -> scalar
;   2 = matrix-vector: [m,n] x [n] -> [m]
;   3 = matrix-matrix: [m,n] x [n,p] -> [m,p]
;   4 = scalar-scalar -> scalar
;
; Preconditions:
;   bit 0 = right operand's first word must be nonzero (e.g. divisor)
;   bit 1 = output payload must not alias either input payload
;   bit 2 = both input descriptors must carry finite flag bit 0
;   bit 3 = both input dimensions must be nonzero
;
; ABI:
;   r1=left descriptor, r2=right descriptor, r3=contract
;   r4=available capability bits, r5=output descriptor
;   r12=caller-owned 24-word scratch, r13=1
; Returns r1=0 on success; otherwise reason:
;   1 descriptor/pointer, 2 missing payload, 3 kind, 4 rank,
;   5 domain, 6 shape, 7 capability, 8 precondition, 9 capacity.
; Output descriptor is byte-for-byte unchanged on every rejection.
;
; This gate validates metadata and applicability only. Kernel execution,
; numerical exceptions, and mathematical undefinedness remain distinct.

mth_preflight:
  CMP r1,r0
  JMP[EQ] @mth_preflight_bad_descriptor
  CMP r2,r0
  JMP[EQ] @mth_preflight_bad_descriptor
  CMP r3,r0
  JMP[EQ] @mth_preflight_bad_descriptor
  CMP r5,r0
  JMP[EQ] @mth_preflight_bad_descriptor
  CMP r12,r0
  JMP[EQ] @mth_preflight_bad_descriptor

  ST r1,r12,0
  ST r2,r12,1
  ST r3,r12,2
  ST r5,r12,3
  ST r4,r12,4

  ; Preserve the caller-reserved output payload and capacity.
  LD r6,r5,5
  LD r7,r5,6
  CMP r6,r0
  JMP[EQ] @mth_preflight_bad_payload
  ST r6,r12,17
  ST r7,r12,18

  ; Read the contract once. Its identity and semantics are owned upstream.
  LD r6,r3,0
  ST r6,r12,10
  LD r6,r3,1
  ST r6,r12,11
  LD r6,r3,2
  ST r6,r12,12
  LD r6,r3,3
  ST r6,r12,13
  LD r6,r3,4
  ST r6,r12,14
  LD r6,r3,5
  ST r6,r12,15
  LD r6,r3,6
  ST r6,r12,19
  LD r6,r3,7
  ST r6,r12,8
  LD r6,r3,8
  ST r6,r12,20
  LD r6,r3,9
  ST r6,r12,9

  ; Resolve the concrete endpoint descriptors.
  LD r1,r12,0
  LD r6,r1,0
  LD r7,r1,1
  LD r8,r1,2
  LD r9,r1,3
  LD r10,r1,4
  LD r11,r1,5
  LD r3,r1,6
  LD r4,r1,7
  ST r6,r12,21
  ST r7,r12,22
  ST r8,r12,5
  ST r9,r12,6
  ST r10,r12,23
  ST r11,r12,15
  ST r3,r12,16
  ST r4,r12,7
  CMP r11,r0
  JMP[EQ] @mth_preflight_bad_payload

  LD r1,r12,1
  LD r6,r1,0
  LD r7,r1,1
  LD r8,r1,2
  LD r9,r1,3
  LD r10,r1,4
  LD r11,r1,5
  LD r3,r1,6
  LD r4,r1,7
  ST r6,r12,24
  ST r7,r12,25
  ST r8,r12,26
  ST r9,r12,27
  ST r10,r12,28
  ST r11,r12,16
  ST r3,r12,29
  ST r4,r12,30
  CMP r11,r0
  JMP[EQ] @mth_preflight_bad_payload

  ; Kind, rank, and domain must match the resolved contract exactly.
  LD r6,r12,21
  LD r7,r12,10
  CMP r6,r7
  JMP[NE] @mth_preflight_bad_kind
  LD r6,r12,24
  LD r7,r12,11
  CMP r6,r7
  JMP[NE] @mth_preflight_bad_kind

  LD r6,r12,22
  LD r7,r12,13
  CMP r6,r7
  JMP[NE] @mth_preflight_bad_rank
  LD r6,r12,25
  LD r7,r12,14
  CMP r6,r7
  JMP[NE] @mth_preflight_bad_rank

  LD r6,r12,23
  LD r7,r12,19
  CMP r6,r7
  JMP[NE] @mth_preflight_bad_domain
  LD r6,r12,28
  LD r7,r12,19
  CMP r6,r7
  JMP[NE] @mth_preflight_bad_domain

  ; Capability subset check: (available & required) == required.
  LD r6,r12,4
  LD r7,r12,20
  BOOL.8 r8,r6,r7
  CMP r8,r7
  JMP[NE] @mth_preflight_bad_capability

  ; Compute input element counts and reject rank > 2 / empty dimensions.
  LD r6,r12,22
  CMP r6,r0
  JMP[EQ] @mth_preflight_left_scalar
  MOVI r7,1
  CMP r6,r7
  JMP[EQ] @mth_preflight_left_vector
  MOVI r7,2
  CMP r6,r7
  JMP[EQ] @mth_preflight_left_matrix
  JMP @mth_preflight_bad_rank
mth_preflight_left_scalar:
  MOVI r6,1
  ST r6,r12,5
  JMP @mth_preflight_left_count_done
mth_preflight_left_vector:
  LD r6,r12,5
  CMP r6,r0
  JMP[EQ] @mth_preflight_bad_shape
  ST r6,r12,5
  JMP @mth_preflight_left_count_done
mth_preflight_left_matrix:
  LD r6,r12,5
  LD r7,r12,6
  CMP r6,r0
  JMP[EQ] @mth_preflight_bad_shape
  CMP r7,r0
  JMP[EQ] @mth_preflight_bad_shape
  MUL r6,r6,r7
  ST r6,r12,5
mth_preflight_left_count_done:
  LD r6,r12,25
  CMP r6,r0
  JMP[EQ] @mth_preflight_right_scalar
  MOVI r7,1
  CMP r6,r7
  JMP[EQ] @mth_preflight_right_vector
  MOVI r7,2
  CMP r6,r7
  JMP[EQ] @mth_preflight_right_matrix
  JMP @mth_preflight_bad_rank
mth_preflight_right_scalar:
  MOVI r6,1
  ST r6,r12,26
  JMP @mth_preflight_right_count_done
mth_preflight_right_vector:
  LD r6,r12,26
  CMP r6,r0
  JMP[EQ] @mth_preflight_bad_shape
  ST r6,r12,26
  JMP @mth_preflight_right_count_done
mth_preflight_right_matrix:
  LD r6,r12,26
  LD r7,r12,27
  CMP r6,r0
  JMP[EQ] @mth_preflight_bad_shape
  CMP r7,r0
  JMP[EQ] @mth_preflight_bad_shape
  MUL r6,r6,r7
  ST r6,r12,26
mth_preflight_right_count_done:
  ; Input buffers must contain their complete declared shapes.
  LD r6,r12,16
  LD r7,r12,5
  CMP r6,r7
  JMP[LT] @mth_preflight_bad_capacity
  LD r6,r12,29
  LD r7,r12,26
  CMP r6,r7
  JMP[LT] @mth_preflight_bad_capacity

  ; Derive output rank and dimensions from the selected shape rule.
  LD r6,r12,8
  CMP r6,r0
  JMP[EQ] @mth_preflight_shape_equal
  MOVI r7,1
  CMP r6,r7
  JMP[EQ] @mth_preflight_shape_dot
  MOVI r7,2
  CMP r6,r7
  JMP[EQ] @mth_preflight_shape_matvec
  MOVI r7,3
  CMP r6,r7
  JMP[EQ] @mth_preflight_shape_matmul
  MOVI r7,4
  CMP r6,r7
  JMP[EQ] @mth_preflight_shape_scalar
  JMP @mth_preflight_bad_shape

mth_preflight_shape_equal:
  LD r6,r12,22
  LD r7,r12,25
  CMP r6,r7
  JMP[NE] @mth_preflight_bad_shape
  LD r6,r12,5
  LD r7,r12,26
  CMP r6,r7
  JMP[NE] @mth_preflight_bad_shape
  LD r6,r12,6
  LD r7,r12,27
  CMP r6,r7
  JMP[NE] @mth_preflight_bad_shape
  LD r6,r12,22
  ST r6,r12,11
  LD r6,r12,5
  ST r6,r12,12
  LD r6,r12,6
  ST r6,r12,13
  JMP @mth_preflight_shape_done

mth_preflight_shape_dot:
  LD r6,r12,22
  MOVI r7,1
  CMP r6,r7
  JMP[NE] @mth_preflight_bad_shape
  LD r6,r12,25
  CMP r6,r7
  JMP[NE] @mth_preflight_bad_shape
  LD r6,r12,5
  LD r7,r12,26
  CMP r6,r7
  JMP[NE] @mth_preflight_bad_shape
  MOVI r6,0
  ST r6,r12,11
  MOVI r6,1
  ST r6,r12,12
  ST r6,r12,13
  JMP @mth_preflight_shape_done

mth_preflight_shape_matvec:
  LD r6,r12,22
  MOVI r7,2
  CMP r6,r7
  JMP[NE] @mth_preflight_bad_shape
  LD r6,r12,25
  MOVI r7,1
  CMP r6,r7
  JMP[NE] @mth_preflight_bad_shape
  LD r6,r12,6
  LD r7,r12,26
  CMP r6,r7
  JMP[NE] @mth_preflight_bad_shape
  MOVI r6,1
  ST r6,r12,11
  LD r6,r12,5
  ST r6,r12,12
  MOVI r6,1
  ST r6,r12,13
  JMP @mth_preflight_shape_done

mth_preflight_shape_matmul:
  LD r6,r12,22
  MOVI r7,2
  CMP r6,r7
  JMP[NE] @mth_preflight_bad_shape
  LD r6,r12,25
  CMP r6,r7
  JMP[NE] @mth_preflight_bad_shape
  LD r6,r12,6
  LD r7,r12,26
  CMP r6,r7
  JMP[NE] @mth_preflight_bad_shape
  MOVI r6,2
  ST r6,r12,11
  LD r6,r12,5
  ST r6,r12,12
  LD r6,r12,27
  ST r6,r12,13
  JMP @mth_preflight_shape_done

mth_preflight_shape_scalar:
  LD r6,r12,22
  CMP r6,r0
  JMP[NE] @mth_preflight_bad_shape
  LD r6,r12,25
  CMP r6,r0
  JMP[NE] @mth_preflight_bad_shape
  MOVI r6,0
  ST r6,r12,11
  MOVI r6,1
  ST r6,r12,12
  ST r6,r12,13

mth_preflight_shape_done:
  ; Required output element count, then verify caller's reserved output page.
  LD r6,r12,11
  CMP r6,r0
  JMP[EQ] @mth_preflight_output_scalar
  MOVI r7,1
  CMP r6,r7
  JMP[EQ] @mth_preflight_output_vector
  MOVI r7,2
  CMP r6,r7
  JMP[EQ] @mth_preflight_output_matrix
  JMP @mth_preflight_bad_rank
mth_preflight_output_scalar:
  MOVI r6,1
  ST r6,r12,14
  JMP @mth_preflight_output_count_done
mth_preflight_output_vector:
  LD r6,r12,12
  ST r6,r12,14
  JMP @mth_preflight_output_count_done
mth_preflight_output_matrix:
  LD r6,r12,12
  LD r7,r12,13
  MUL r6,r6,r7
  ST r6,r12,14
mth_preflight_output_count_done:
  LD r6,r12,18
  LD r7,r12,14
  CMP r6,r7
  JMP[LT] @mth_preflight_bad_capacity

  ; Enforce the selected semantic preconditions.
  LD r6,r12,9
  MOVI r7,1
  BOOL.8 r8,r6,r7
  CMP r8,r0
  JMP[EQ] @mth_preflight_check_noalias
  LD r6,r12,16
  LD r6,r6,0
  CMP r6,r0
  JMP[EQ] @mth_preflight_bad_precondition

mth_preflight_check_noalias:
  LD r6,r12,9
  MOVI r7,2
  BOOL.8 r8,r6,r7
  CMP r8,r0
  JMP[EQ] @mth_preflight_check_finite
  LD r6,r12,17
  LD r7,r12,15
  CMP r6,r7
  JMP[EQ] @mth_preflight_bad_precondition
  LD r6,r12,17
  LD r7,r12,16
  CMP r6,r7
  JMP[EQ] @mth_preflight_bad_precondition

mth_preflight_check_finite:
  LD r6,r12,9
  MOVI r7,4
  BOOL.8 r8,r6,r7
  CMP r8,r0
  JMP[EQ] @mth_preflight_check_nonempty
  LD r6,r12,7
  MOVI r7,1
  BOOL.8 r8,r6,r7
  CMP r8,r0
  JMP[EQ] @mth_preflight_bad_precondition
  LD r6,r12,30
  MOVI r7,1
  BOOL.8 r8,r6,r7
  CMP r8,r0
  JMP[EQ] @mth_preflight_bad_precondition

mth_preflight_check_nonempty:
  LD r6,r12,9
  MOVI r7,8
  BOOL.8 r8,r6,r7
  CMP r8,r0
  JMP[EQ] @mth_preflight_commit
  LD r6,r12,5
  CMP r6,r0
  JMP[EQ] @mth_preflight_bad_precondition
  LD r6,r12,26
  CMP r6,r0
  JMP[EQ] @mth_preflight_bad_precondition

mth_preflight_commit:
  ; No failure path below this point: publish the derived output descriptor.
  LD r6,r12,3
  LD r7,r12,12
  ST r7,r6,0
  LD r7,r12,11
  ST r7,r6,1
  LD r7,r12,12
  ST r7,r6,2
  LD r7,r12,13
  ST r7,r6,3
  LD r7,r12,19
  ST r7,r6,4
  MOVI r7,0
  ST r7,r6,7
  LD r3,r12,12
  LD r4,r12,11
  LD r5,r12,12
  LD r6,r12,13
  MOVI r1,0
  MOVI r2,0
  RET

mth_preflight_bad_descriptor:
  MOVI r1,1
  RET
mth_preflight_bad_payload:
  MOVI r1,2
  RET
mth_preflight_bad_kind:
  MOVI r1,3
  RET
mth_preflight_bad_rank:
  MOVI r1,4
  RET
mth_preflight_bad_domain:
  MOVI r1,5
  RET
mth_preflight_bad_shape:
  MOVI r1,6
  RET
mth_preflight_bad_capability:
  MOVI r1,7
  RET
mth_preflight_bad_precondition:
  MOVI r1,8
  RET
mth_preflight_bad_capacity:
  MOVI r1,9
  RET
