.org 0
JMP @mth_link_pf_main
.include "../nan16/mth_preflight.nas"
.include "../../nan0s/src/nannet/route_address.nas"
.include "../../nan0s/src/nannet/object_key_decode.nas"
.include "../../nan0s/src/nannet/math_registry.nas"
.include "../../nan0s/src/nannet/route_object_resolve.nas"
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
  JMP[NE] @mth_link_pf_fail
  MOVI r1,234
  MOVI r2,4
  MOVI r3,2
  MOVI r4,0x5678
  CALL @nmr_obj_put
  CMP r3,r0
  JMP[NE] @mth_link_pf_fail
  MOVI r1,123
  MOVI r2,@mth_link_pf_left_payload
  CALL @nmr_obj_bind_data
  CMP r3,r0
  JMP[NE] @mth_link_pf_fail
  MOVI r1,234
  MOVI r2,@mth_link_pf_right_payload
  CALL @nmr_obj_bind_data
  CMP r3,r0
  JMP[NE] @mth_link_pf_fail

  ; Existing shape metadata is used by the legacy route-expression parser.
  MOVI r1,123
  MOVI r2,1
  MOVI r3,3
  MOVI r4,1
  MOVI r5,3
  CALL @nmr_shape_put
  CMP r3,r0
  JMP[NE] @mth_link_pf_fail
  MOVI r1,234
  MOVI r2,1
  MOVI r3,3
  MOVI r4,1
  MOVI r5,3
  CALL @nmr_shape_put
  CMP r3,r0
  JMP[NE] @mth_link_pf_fail

  ; Register the operator once, then attach its immutable typed contract.
  MOVI r1,77
  MOVI r2,4
  MOVI r3,4
  MOVI r4,3
  MOVI r5,900
  CALL @nmr_op_put
  CMP r3,r0
  JMP[NE] @mth_link_pf_fail
  MOVI r1,77
  MOVI r2,1
  MOVI r3,1
  MOVI r4,0
  MOVI r5,1
  MOVI r6,1
  MOVI r7,1
  MOVI r8,0
  CALL @nmr_contract_put
  CMP r3,r0
  JMP[NE] @mth_link_pf_fail

  ; The literal ::op: expression is parsed and resolved by the canonical
  ; NaN0S linker. Its r10 is the registered 10-word contract descriptor.
  MOVI r1,@mth_link_pf_expression
  SHL r1,r1,2
  CALL @nmr_expr_resolve
  CMP r8,r0
  JMP[NE] @mth_link_pf_fail
  MOVI r6,123
  CMP r1,r6
  JMP[NE] @mth_link_pf_fail
  MOVI r6,234
  CMP r2,r6
  JMP[NE] @mth_link_pf_fail
  MOVI r6,77
  CMP r3,r6
  JMP[NE] @mth_link_pf_fail
  MOVI r6,3
  CMP r4,r6
  JMP[NE] @mth_link_pf_fail
  MOVI r6,900
  CMP r5,r6
  JMP[NE] @mth_link_pf_fail
  MOVI r6,3
  CMP r9,r6
  JMP[NE] @mth_link_pf_fail
  CMP r10,r0
  JMP[EQ] @mth_link_pf_fail
  ST r10,r0,@mth_link_pf_contract

  ; The exact contract pointer returned by :: now gates output publication.
  MOVI r1,@mth_link_pf_left
  MOVI r2,@mth_link_pf_right
  LD r3,r0,@mth_link_pf_contract
  MOVI r4,1
  MOVI r5,@mth_link_pf_output
  CALL @mth_preflight
  CMP r1,r0
  JMP[NE] @mth_link_pf_fail
  LD r6,r5,0
  MOVI r7,3
  CMP r6,r7
  JMP[NE] @mth_link_pf_fail
  LD r6,r5,1
  CMP r6,r0
  JMP[NE] @mth_link_pf_fail
  LD r6,r5,2
  MOVI r7,1
  CMP r6,r7
  JMP[NE] @mth_link_pf_fail
  LD r6,r5,4
  MOVI r7,1
  CMP r6,r7
  JMP[NE] @mth_link_pf_fail

  MOVI r1,@mth_link_pf_pass
  CALL @mth_link_pf_puts
  HALT

mth_link_pf_fail:
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
.word 4,1,3,1,1,@mth_link_pf_left_payload,3,1
mth_link_pf_right:
.word 4,1,3,1,1,@mth_link_pf_right_payload,3,1
mth_link_pf_output:
.word 0,0,0,0,0,@mth_link_pf_output_payload,1,0

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
mth_link_pf_contract:
.word 0
mth_link_pf_expression:
.str "nan://GM0:SC0:MC0:BS0:HW0::HW0:1::vector123::op:77::nan://GM0:SC0:MC0:BS0:HW0::HW0:2::vector234"
mth_link_pf_pass:
.str "MTH LINKER PREFLIGHT PASS\n"
mth_link_pf_bad:
.str "MTH LINKER PREFLIGHT FAIL\n"
