; BS0:0 rooted five-tier route admission for the shared NaN16 network.
; This is the canonical native *structural* gate, not the DB authority.
; The host supplies only authenticated MC0DB/SC0DB existence and keypair
; bindings; guest NaN16 decides structural permission and the next tier.
;
; Tiers: HW=1, BS=2, MC=3, SC=4, GM=5.
; All HW0..255 reside UNDER the one BS0:0 runner-ring/NANNET port.
; There is NO direct HW-to-HW transport or second runner-ring entry.
; BS1..255 may exist as dormant reservations under MC0 before deployment.
; MC0 up to SC0; SC0 up to GM0. SC0/GM0 default DB-only, not live VMs.
;
; nhr_hw_admit: r1=HW idx, r2=authoritative binding:
;     0 unbound, 1 reserved paired identity, 2 on-demand leased identity.
;   returns r1=logical point idx+1, r2=0 reserved / 1 dynamic,
;           r3=0 permitted or 1 bad ID / 2 no verified binding /
;              3 invalid class / 4 HW0 may not originate a connector.
;   HW0 requires separate host-root logic, never connector origin.
;   HW1..4 are preallocated and must be paired/reserved, never dynamic.
;   HW5..255 must be backed by an authenticated on-demand lease.
nhr_hw_admit:
  MOVI r4,255
  CMP r1,r4
  JMP[GT] @nhr_hw_bad
  CMP r1,r0
  JMP[EQ] @nhr_hw_root
  MOVI r4,5
  CMP r1,r4
  JMP[LT] @nhr_hw_reserved
  MOVI r4,2
  CMP r2,r4
  JMP[NE] @nhr_hw_unbound
  MOVI r2,1
  ADDI r1,r1,1
  MOVI r3,0
  RET
nhr_hw_reserved:
  MOVI r4,1
  CMP r2,r4
  JMP[NE] @nhr_hw_unbound
  MOVI r2,0
  ADDI r1,r1,1
  MOVI r3,0
  RET
nhr_hw_root:
  MOVI r3,4
  MOVI r1,0
  MOVI r2,0
  RET
nhr_hw_bad:
  MOVI r3,1
  MOVI r1,0
  MOVI r2,0
  RET
nhr_hw_unbound:
  MOVI r3,2
  MOVI r1,0
  MOVI r2,0
  RET

; nhr_up: r1=tier (HW=1..SC=4), r2=child id,
;         r3=server-proven child state (0 absent,1 active,2 database-only).
;   returns r1=next parent tier, r2=0 parent (BS0,MC0,SC0,GM0),
;           r3=0 routable/live, 3 dormant or DB-only, 1 malformed.
;   r4=original child ID for durable mapping on return.
; A dormant/future mapping is NEVER implicitly an executable route.
nhr_up:
  MOVI r4,255
  CMP r2,r4
  JMP[GT] @nhr_up_bad
  CMP r1,r0
  JMP[EQ] @nhr_up_bad
  MOVI r4,4
  CMP r1,r4
  JMP[GT] @nhr_up_bad
  MOVI r4,0
  ADD r4,r2,r0
  MOVI r5,3
  CMP r1,r5
  JMP[GT] @nhr_up_force_db
  ADDI r1,r1,1
  MOVI r2,0
  MOVI r5,1
  CMP r3,r5
  JMP[EQ] @nhr_up_active
  MOVI r3,3
  RET
nhr_up_force_db:
  ADDI r1,r1,1
  MOVI r2,0
  MOVI r3,3
  RET
nhr_up_active:
  MOVI r3,0
  RET
nhr_up_bad:
  MOVI r1,0
  MOVI r2,0
  MOVI r3,1
  RET

; nhr_down: r1=parent tier (BS=2..GM=5), r2=target child index,
;           r3=server-backed child state (0 reserved/absent,1 live,2 DB-only).
;   Returns r1=child tier, r2=child index, r3=0 routable or
;           3 unresolved/dormant or 1 invalid.
;   A GM0 -> SC0 or SC0 -> MC0 path is DB-only until a later live
;   dispatch adapter is explicitly authenticated. This function cannot
;   fabricate an active SC0/GM0 VM or open an absent BS1 process.
nhr_down:
  MOVI r4,2
  CMP r1,r4
  JMP[LT] @nhr_down_bad
  MOVI r4,5
  CMP r1,r4
  JMP[GT] @nhr_down_bad
  MOVI r4,255
  CMP r2,r4
  JMP[GT] @nhr_down_bad
  MOVI r4,4
  CMP r1,r4
  JMP[GE] @nhr_down_db
  SUB r1,r1,r13
  MOVI r4,1
  CMP r3,r4
  JMP[EQ] @nhr_down_active
  MOVI r3,3
  RET
nhr_down_db:
  SUB r1,r1,r13
  MOVI r3,3
  RET
nhr_down_active:
  MOVI r3,0
  RET
nhr_down_bad:
  MOVI r1,0
  MOVI r2,0
  MOVI r3,1
  RET
