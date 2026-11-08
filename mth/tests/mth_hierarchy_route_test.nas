; Canonical real guest route gate: reserved HW0-4, dynamic HW5-255,
; every HW descends from BS0:0; MC0/SC0/GM0 future paths cannot execute.
.org 0
JMP @t_hier_main
.include "../nan16/mth_hierarchy_route.nas"
t_hier_main:
 MOVI r13,1
 MOVI r1,0
 MOVI r2,1
 CALL @nhr_hw_admit
 MOVI r4,4
 CMP r3,r4
 JMP[NE] @t_hier_fail
 MOVI r1,2
 MOVI r2,1
 CALL @nhr_hw_admit
 MOVI r4,3
 CMP r1,r4
 JMP[NE] @t_hier_fail
 CMP r3,r0
 JMP[NE] @t_hier_fail
 CMP r2,r0
 JMP[NE] @t_hier_fail
 MOVI r1,4
 MOVI r2,1
 CALL @nhr_hw_admit
 MOVI r4,5
 CMP r1,r4
 JMP[NE] @t_hier_fail
 MOVI r1,5
 MOVI r2,2
 CALL @nhr_hw_admit
 MOVI r4,6
 CMP r1,r4
 JMP[NE] @t_hier_fail
 MOVI r4,1
 CMP r2,r4
 JMP[NE] @t_hier_fail
 MOVI r1,255
 MOVI r2,2
 CALL @nhr_hw_admit
 MOVI r4,256
 CMP r1,r4
 JMP[NE] @t_hier_fail
 MOVI r1,5
 MOVI r2,1
 CALL @nhr_hw_admit
 MOVI r4,2
 CMP r3,r4
 JMP[NE] @t_hier_fail
 MOVI r1,3
 MOVI r2,2
 CALL @nhr_hw_admit
 MOVI r4,2
 CMP r3,r4
 JMP[NE] @t_hier_fail
 MOVI r1,256
 MOVI r2,2
 CALL @nhr_hw_admit
 MOVI r4,1
 CMP r3,r4
 JMP[NE] @t_hier_fail
 ; HW2 -> BS0 -> MC0 -> SC0 -> GM0 (top DB-only).
 MOVI r1,1
 MOVI r2,2
 MOVI r3,1
 CALL @nhr_up
 MOVI r4,2
 CMP r1,r4
 JMP[NE] @t_hier_fail
 CMP r2,r0
 JMP[NE] @t_hier_fail
 CMP r3,r0
 JMP[NE] @t_hier_fail
 MOVI r1,2
 MOVI r2,0
 MOVI r3,1
 CALL @nhr_up
 MOVI r4,3
 CMP r1,r4
 JMP[NE] @t_hier_fail
 CMP r3,r0
 JMP[NE] @t_hier_fail
 MOVI r1,3
 MOVI r2,0
 MOVI r3,1
 CALL @nhr_up
 MOVI r4,4
 CMP r1,r4
 JMP[NE] @t_hier_fail
 CMP r3,r0
 JMP[NE] @t_hier_fail
 MOVI r1,4
 MOVI r2,0
 MOVI r3,2
 CALL @nhr_up
 MOVI r4,5
 CMP r1,r4
 JMP[NE] @t_hier_fail
 MOVI r4,3
 CMP r3,r4
 JMP[NE] @t_hier_fail
 ; MC0 -> future BS1:0 is a valid *address*, never live execution.
 MOVI r1,3
 MOVI r2,1
 MOVI r3,0
 CALL @nhr_down
 MOVI r4,2
 CMP r1,r4
 JMP[NE] @t_hier_fail
 MOVI r4,1
 CMP r2,r4
 JMP[NE] @t_hier_fail
 MOVI r4,3
 CMP r3,r4
 JMP[NE] @t_hier_fail
 ; SC0:0 DB-only -> MC0 and GM0 -> SC0 remain non-executable.
 MOVI r1,4
 MOVI r2,0
 MOVI r3,2
 CALL @nhr_down
 MOVI r4,3
 CMP r1,r4
 JMP[NE] @t_hier_fail
 CMP r3,r4
 JMP[NE] @t_hier_fail
 MOVI r1,5
 MOVI r2,0
 MOVI r3,2
 CALL @nhr_down
 MOVI r4,4
 CMP r1,r4
 JMP[NE] @t_hier_fail
 MOVI r4,3
 CMP r3,r4
 JMP[NE] @t_hier_fail
 MOVI r1,3
 MOVI r2,0
 MOVI r3,1
 CALL @nhr_down
 MOVI r4,2
 CMP r1,r4
 JMP[NE] @t_hier_fail
 CMP r3,r0
 JMP[NE] @t_hier_fail
 MOVI r1,@t_hier_good
 CALL @t_hier_puts
 HALT
t_hier_fail:
 MOVI r1,@t_hier_bad
 CALL @t_hier_puts
 HALT
t_hier_puts:
 MOVI r5,255
t_hier_next:
 LD r2,r1,0
 MOVI r3,4
t_hier_byte:
 BOOL.8 r4,r2,r5
 CMP r4,r0
 RET[EQ]
 PUTC r4
 SHR r2,r2,8
 SUB r3,r3,r13
 JMP[NE] @t_hier_byte
 ADD r1,r1,r13
 JMP @t_hier_next
t_hier_good:
 .str "NAN HIERARCHY PASS\\n"
t_hier_bad:
 .str "NAN HIERARCHY FAIL\\n"
