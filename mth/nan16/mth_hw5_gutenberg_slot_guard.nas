; NaN16-only BS0 hardware-node admission contract, revision 1.
; These are GLOBAL hardware-node coordinates, not local palindrome head indices.
; HW5:0 is the immutable Gutenberg corpus point. HW4:0 is WordNet.
; HW0..HW3 and HW6..HW8 remain dedicated; public registrations start HW9.
; This is a native coordinate gate, NOT a signature verifier or lease issuer.
; The canonical portal must still verify signed authorization and stale leases.
;
; ABI r1=hardware index (0..255), r2=operation, r3=revision(1), r13=1.
; operation: 0 public registration; 1 Gutenberg HW5; 2 WordNet HW4;
;            3 fixed control HW0..HW3/HW6..HW8.
; Returns r1=1 accepted, r2=0, r3=node_point (one-based index);
;         r1=0 rejected, r2=reason (1 invalid index, 2 operation,
;                               3 mismatch/reserved, 4 version);
;         r3=0 on rejection.
; Deterministic leaf; no memory, model, route or allocator side effects.
mth_hw5_gutenberg_slot_guard:
  MOVI r0,0
  MOVI r4,1
  CMP r3,r4
  JMP[NE] @hw5_guard_version
  CMPS r1,r0
  JMP[LT] @hw5_guard_index
  MOVI r4,255
  CMP r1,r4
  JMP[GT] @hw5_guard_index
  CMP r2,r0
  JMP[EQ] @hw5_guard_public
  MOVI r4,1
  CMP r2,r4
  JMP[EQ] @hw5_guard_gutenberg
  MOVI r4,2
  CMP r2,r4
  JMP[EQ] @hw5_guard_wordnet
  MOVI r4,3
  CMP r2,r4
  JMP[EQ] @hw5_guard_control
  MOVI r2,2
  JMP @hw5_guard_reject
hw5_guard_public:
  MOVI r4,9
  CMP r1,r4
  JMP[LT] @hw5_guard_reserved
  JMP @hw5_guard_allow
hw5_guard_gutenberg:
  MOVI r4,5
  CMP r1,r4
  JMP[EQ] @hw5_guard_allow
  JMP @hw5_guard_reserved
hw5_guard_wordnet:
  MOVI r4,4
  CMP r1,r4
  JMP[EQ] @hw5_guard_allow
  JMP @hw5_guard_reserved
hw5_guard_control:
  MOVI r4,4
  CMP r1,r4
  JMP[LT] @hw5_guard_allow
  MOVI r4,6
  CMP r1,r4
  JMP[LT] @hw5_guard_reserved
  MOVI r4,9
  CMP r1,r4
  JMP[LT] @hw5_guard_allow
hw5_guard_reserved:
  MOVI r2,3
  JMP @hw5_guard_reject
hw5_guard_index:
  MOVI r2,1
  JMP @hw5_guard_reject
hw5_guard_version:
  MOVI r2,4
hw5_guard_reject:
  MOVI r1,0
  MOVI r3,0
  RET
hw5_guard_allow:
  ADD r3,r1,r13
  MOVI r1,1
  MOVI r2,0
  RET
