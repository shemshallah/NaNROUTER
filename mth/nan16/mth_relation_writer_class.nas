; MTH Round 037 relation-writer class codec — NaN16 integer only.
;
; The external writer predicts four classes:
;   0 forward subtype
;   1 reverse subtype
;   2 negated subtype
;   3 uncertain subtype
;
; decode ABI:
;   r1 = class 0..3
;   success: r1=1, r3=direction code (1 forward, 2 reverse, 0 none),
;            r4=negated 0/1, r5=uncertain 0/1
;   rejection: r1=0
;
; encode ABI:
;   r1 = direction code 0/1/2, r2 = negated 0/1, r3 = uncertain 0/1
;   success: r1=1, r4=class 0..3
;   rejection: r1=0
;
; This codec only maps labels to flags. It does not classify prose, train a
; writer, store a relation, or promote a claim.

mth_relation_writer_decode:
  MOVI r10,0
  CMP r1,r10
  JMP[EQ] @mth_writer_decode_forward
  MOVI r10,1
  CMP r1,r10
  JMP[EQ] @mth_writer_decode_reverse
  MOVI r10,2
  CMP r1,r10
  JMP[EQ] @mth_writer_decode_negated
  MOVI r10,3
  CMP r1,r10
  JMP[EQ] @mth_writer_decode_uncertain
  MOVI r1,0
  RET

mth_writer_decode_forward:
  MOVI r3,1
  MOVI r4,0
  MOVI r5,0
  MOVI r1,1
  RET
mth_writer_decode_reverse:
  MOVI r3,2
  MOVI r4,0
  MOVI r5,0
  MOVI r1,1
  RET
mth_writer_decode_negated:
  MOVI r3,1
  MOVI r4,1
  MOVI r5,0
  MOVI r1,1
  RET
mth_writer_decode_uncertain:
  MOVI r3,0
  MOVI r4,0
  MOVI r5,1
  MOVI r1,1
  RET

mth_relation_writer_encode:
  MOVI r10,1
  CMP r1,r10
  JMP[EQ] @mth_writer_encode_forward
  MOVI r10,2
  CMP r1,r10
  JMP[EQ] @mth_writer_encode_reverse
  CMP r1,r0
  JMP[EQ] @mth_writer_encode_none
  MOVI r1,0
  RET
mth_writer_encode_forward:
  CMP r2,r0
  JMP[NE] @mth_writer_encode_negated_check
  CMP r3,r0
  JMP[NE] @mth_writer_encode_reject
  MOVI r4,0
  MOVI r1,1
  RET

mth_writer_encode_negated_check:
  CMP r3,r0
  JMP[NE] @mth_writer_encode_reject
  MOVI r4,2
  MOVI r1,1
  RET
mth_writer_encode_reverse:
  CMP r2,r0
  JMP[NE] @mth_writer_encode_reject
  CMP r3,r0
  JMP[NE] @mth_writer_encode_reject
  MOVI r4,1
  MOVI r1,1
  RET
mth_writer_encode_none:
  CMP r2,r0
  JMP[NE] @mth_writer_encode_reject
  MOVI r10,1
  CMP r3,r10
  JMP[NE] @mth_writer_encode_reject
  MOVI r4,3
  MOVI r1,1
  RET
mth_writer_encode_reject:
  MOVI r1,0
  RET
