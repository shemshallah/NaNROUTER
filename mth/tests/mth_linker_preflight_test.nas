.org 0
JMP @mth_link_pf_main
.include "../nan16/mth_preflight_gate.nas"
.include "../nan16/mth_preflight.nas"
.include "../nan16/mth_admission.nas"
.include "../../nan0s/src/nannet/route_address.nas"
.include "../../nan0s/src/nannet/object_key_decode.nas"
.include "../../nan0s/src/nannet/math_registry.nas"
.include "../../nan0s/src/nannet/route_object_resolve.nas"
.include "../../nan0s/src/nannet/vector_ops.nas"
.include "../../nan0s/src/nannet/mc0db_scratch.nas"
.include "../../nan0s/src/nannet/math_expression.nas"

mth_link_pf_main:
  MOVI r13,1
  MOVI r12,@mth_link_pf_scratch

  ; Register two leaf objects at distinct logical HW0 points.
  MOVI r1,123
  MOVI r2,4
  MOVI r3,1
  MOVI r4,0x1234
  CALL @nmr_obj_put
  CMP r3,r0
  JMP[NE] @mth_link_pf_fail_pre_10
  MOVI r1,234
  MOVI r2,4
  MOVI r3,2
  MOVI r4,0x5678
  CALL @nmr_obj_put
  CMP r3,r0
  JMP[NE] @mth_link_pf_fail_pre_11
  MOVI r1,123
  MOVI r2,@mth_link_pf_left_payload
  CALL @nmr_obj_bind_data
  CMP r3,r0
  JMP[NE] @mth_link_pf_fail_pre_12
  MOVI r1,234
  MOVI r2,@mth_link_pf_right_payload
  CALL @nmr_obj_bind_data
  CMP r3,r0
  JMP[NE] @mth_link_pf_fail_pre_13

  ; Existing shape metadata is used by the legacy route-expression parser.
  MOVI r1,123
  MOVI r2,1
  MOVI r3,3
  MOVI r4,1
  MOVI r5,3
  CALL @nmr_shape_put
  CMP r3,r0
  JMP[NE] @mth_link_pf_fail_pre_14
  MOVI r1,234
  MOVI r2,1
  MOVI r3,3
  MOVI r4,1
  MOVI r5,3
  CALL @nmr_shape_put
  CMP r3,r0
  JMP[NE] @mth_link_pf_fail_pre_15

  ; Register the operator once, then attach its immutable typed contract.
  MOVI r1,77
  MOVI r2,4
  MOVI r3,4
  MOVI r4,3
  MOVI r5,900
  CALL @nmr_op_put
  CMP r3,r0
  JMP[NE] @mth_link_pf_fail_pre_16
  MOVI r1,77
  MOVI r2,1
  MOVI r3,1
  MOVI r4,0
  MOVI r5,2
  MOVI r6,1
  MOVI r7,1
  MOVI r8,0
  CALL @nmr_contract_put
  CMP r3,r0
  JMP[NE] @mth_link_pf_fail_pre_17

  ; The literal ::op: expression is parsed and resolved by the canonical
  ; NaN0S linker. Its r10 is the registered 10-word contract descriptor.
  MOVI r1,@mth_link_pf_expression
  SHL r1,r1,2
  CALL @nmr_expr_resolve
  CMP r8,r0
  JMP[NE] @mth_link_pf_fail_pre_18
  MOVI r6,123
  CMP r1,r6
  JMP[NE] @mth_link_pf_fail_pre_19
  MOVI r6,234
  CMP r2,r6
  JMP[NE] @mth_link_pf_fail_pre_20
  MOVI r6,77
  CMP r3,r6
  JMP[NE] @mth_link_pf_fail_pre_21
  MOVI r6,3
  CMP r4,r6
  JMP[NE] @mth_link_pf_fail_pre_22
  MOVI r6,900
  CMP r5,r6
  JMP[NE] @mth_link_pf_fail_pre_23
  MOVI r6,3
  CMP r9,r6
  JMP[NE] @mth_link_pf_fail_pre_24
  CMP r10,r0
  JMP[EQ] @mth_link_pf_fail_pre_25
  ST r10,r0,@mth_link_pf_contract

  ; mth_admit performs both gates; pass the exact registry contract pointer.
  MOVI r12,@mth_link_pf_scratch

  ; Reuse the exact registry-owned contract pointer through composed admission.
  ; This binds the authoritative rule snapshot first, then concrete typed leaves.
  MOVI r1,@mth_link_pf_candidate
  MOVI r2,@mth_link_pf_rule
  MOVI r3,@mth_link_pf_left
  MOVI r4,@mth_link_pf_right
  LD r5,r0,@mth_link_pf_contract
  MOVI r6,1
  MOVI r7,@mth_link_pf_output
  MOVI r12,@mth_link_pf_scratch
  CALL @mth_admit
  CMP r1,r0
  JMP[NE] @mth_link_pf_fail_1

  ; A stale rule epoch is rejected before typed applicability.
  MOVI r8,@mth_link_pf_candidate
  MOVI r9,6
  ST r9,r8,9
  MOVI r1,@mth_link_pf_candidate
  MOVI r2,@mth_link_pf_rule
  MOVI r3,@mth_link_pf_left
  MOVI r4,@mth_link_pf_right
  LD r5,r0,@mth_link_pf_contract
  MOVI r6,1
  MOVI r7,@mth_link_pf_output
  MOVI r12,@mth_link_pf_scratch
  CALL @mth_admit
  MOVI r9,18
  CMP r1,r9
  JMP[NE] @mth_link_pf_fail_2
  MOVI r8,@mth_link_pf_candidate
  MOVI r9,7
  ST r9,r8,9

  ; Concrete dimension mismatch is rejected by the second gate and leaves
  ; the caller's output descriptor untouched.
  MOVI r8,@mth_link_pf_right
  MOVI r9,2
  ST r9,r8,2
  MOVI r8,@mth_link_pf_output
  MOVI r9,55
  ST r9,r8,0
  MOVI r1,@mth_link_pf_candidate
  MOVI r2,@mth_link_pf_rule
  MOVI r3,@mth_link_pf_left
  MOVI r4,@mth_link_pf_right
  LD r5,r0,@mth_link_pf_contract
  MOVI r6,1
  MOVI r7,@mth_link_pf_output
  MOVI r12,@mth_link_pf_scratch
  CALL @mth_admit
  MOVI r9,38
  CMP r1,r9
  JMP[NE] @mth_link_pf_fail_3
  ; mth_admit may clobber r8; reload the output descriptor before checking it.
  MOVI r8,@mth_link_pf_output
  LD r10,r8,0
  MOVI r9,55
  CMP r10,r9
  JMP[NE] @mth_link_pf_fail_4

  MOVI r1,@mth_link_pf_pass
  CALL @mth_link_pf_puts
  MOVI r1,@mth_link_pf_admit_pass
  CALL @mth_link_pf_puts
  HALT

mth_link_pf_fail_pre_10:
  MOVI r12,@mth_link_pf_scratch
  MOVI r8,10
  ST r8,r12,47
  JMP @mth_link_pf_fail_print
mth_link_pf_fail_pre_11:
  MOVI r12,@mth_link_pf_scratch
  MOVI r8,11
  ST r8,r12,47
  JMP @mth_link_pf_fail_print
mth_link_pf_fail_pre_12:
  MOVI r12,@mth_link_pf_scratch
  MOVI r8,12
  ST r8,r12,47
  JMP @mth_link_pf_fail_print
mth_link_pf_fail_pre_13:
  MOVI r12,@mth_link_pf_scratch
  MOVI r8,13
  ST r8,r12,47
  JMP @mth_link_pf_fail_print
mth_link_pf_fail_pre_14:
  MOVI r12,@mth_link_pf_scratch
  MOVI r8,14
  ST r8,r12,47
  JMP @mth_link_pf_fail_print
mth_link_pf_fail_pre_15:
  MOVI r12,@mth_link_pf_scratch
  MOVI r8,15
  ST r8,r12,47
  JMP @mth_link_pf_fail_print
mth_link_pf_fail_pre_16:
  MOVI r12,@mth_link_pf_scratch
  MOVI r8,16
  ST r8,r12,47
  JMP @mth_link_pf_fail_print
mth_link_pf_fail_pre_17:
  MOVI r12,@mth_link_pf_scratch
  MOVI r8,17
  ST r8,r12,47
  JMP @mth_link_pf_fail_print
mth_link_pf_fail_pre_18:
  MOVI r12,@mth_link_pf_scratch
  MOVI r8,18
  ST r8,r12,47
  JMP @mth_link_pf_fail_print
mth_link_pf_fail_pre_19:
  MOVI r12,@mth_link_pf_scratch
  MOVI r8,19
  ST r8,r12,47
  JMP @mth_link_pf_fail_print
mth_link_pf_fail_pre_20:
  MOVI r12,@mth_link_pf_scratch
  MOVI r8,20
  ST r8,r12,47
  JMP @mth_link_pf_fail_print
mth_link_pf_fail_pre_21:
  MOVI r12,@mth_link_pf_scratch
  MOVI r8,21
  ST r8,r12,47
  JMP @mth_link_pf_fail_print
mth_link_pf_fail_pre_22:
  MOVI r12,@mth_link_pf_scratch
  MOVI r8,22
  ST r8,r12,47
  JMP @mth_link_pf_fail_print
mth_link_pf_fail_pre_23:
  MOVI r12,@mth_link_pf_scratch
  MOVI r8,23
  ST r8,r12,47
  JMP @mth_link_pf_fail_print
mth_link_pf_fail_pre_24:
  MOVI r12,@mth_link_pf_scratch
  MOVI r8,24
  ST r8,r12,47
  JMP @mth_link_pf_fail_print
mth_link_pf_fail_pre_25:
  MOVI r12,@mth_link_pf_scratch
  MOVI r8,25
  ST r8,r12,47
  JMP @mth_link_pf_fail_print
mth_link_pf_fail_pre_26:
  MOVI r12,@mth_link_pf_scratch
  MOVI r8,26
  ST r8,r12,47
  JMP @mth_link_pf_fail_print
mth_link_pf_fail_pre_27:
  MOVI r12,@mth_link_pf_scratch
  MOVI r8,27
  ST r8,r12,47
  JMP @mth_link_pf_fail_print
mth_link_pf_fail_pre_28:
  MOVI r12,@mth_link_pf_scratch
  MOVI r8,28
  ST r8,r12,47
  JMP @mth_link_pf_fail_print
mth_link_pf_fail_pre_29:
  MOVI r12,@mth_link_pf_scratch
  MOVI r8,29
  ST r8,r12,47
  JMP @mth_link_pf_fail_print
mth_link_pf_fail_pre_30:
  MOVI r12,@mth_link_pf_scratch
  MOVI r8,30
  ST r8,r12,47
  JMP @mth_link_pf_fail_print
mth_link_pf_fail_1:
  MOVI r12,@mth_link_pf_scratch
  ST r1,r12,47
  JMP @mth_link_pf_fail_print
mth_link_pf_fail_2:
  MOVI r12,@mth_link_pf_scratch
  MOVI r8,2
  ST r8,r12,47
  JMP @mth_link_pf_fail_print
mth_link_pf_fail_3:
  MOVI r12,@mth_link_pf_scratch
  MOVI r8,3
  ST r8,r12,47
  JMP @mth_link_pf_fail_print
mth_link_pf_fail_4:
  MOVI r12,@mth_link_pf_scratch
  MOVI r8,4
  ST r8,r12,47
  JMP @mth_link_pf_fail_print
mth_link_pf_fail:
  MOVI r12,@mth_link_pf_scratch
  MOVI r8,99
  ST r8,r12,47
mth_link_pf_fail_print:
  MOVI r1,@mth_link_pf_bad
  CALL @mth_link_pf_puts
  HALT

mth_link_pf_puts:
  MOVI r4,255
mth_link_pf_puts_word:
  LD r2,r1,0
  MOVI r3,4
mth_link_pf_puts_byte:
  BOOL.8 r5,r2,r4
  CMP r5,r0
  RET[EQ]
  PUTC r5
  SHR r2,r2,8
  SUB r3,r3,r13
  JMP[NE] @mth_link_pf_puts_byte
  ADD r1,r1,r13
  JMP @mth_link_pf_puts_word

.org 30000
mth_link_pf_left:
.word 4,1,3,1,2,@mth_link_pf_left_payload,3,1
mth_link_pf_right:
.word 4,1,3,1,2,@mth_link_pf_right_payload,3,1
mth_link_pf_output:
.word 0,0,0,0,0,@mth_link_pf_output_payload,1,0
mth_link_pf_candidate:
.word 1,7,4,4,3,2,2,3,3,7,1,1,2,1,100,101,102,103,104,105,106,107
mth_link_pf_rule:
.word 1,7,4,4,3,2,1,1,1,100,101,102,103,104,105,106,107

.org 30256
mth_link_pf_left_payload:
.word 1,2,3
mth_link_pf_right_payload:
.word 4,5,6
mth_link_pf_output_payload:
.word 0
mth_link_pf_scratch:
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
.word 0
mth_link_pf_contract:
.word 0
mth_link_pf_expression:
.str "nan://GM0:SC0:MC0:BS0:HW0::HW0:1::vector123::op:77::nan://GM0:SC0:MC0:BS0:HW0::HW0:2::vector234"
mth_link_pf_pass:
.str "MTH LINKER PREFLIGHT PASS\n"
mth_link_pf_admit_pass:
.str "MTH LINKER COMPOSED ADMISSION PASS\n"
mth_link_pf_bad:
.str "MTH LINKER PREFLIGHT FAIL\n"
