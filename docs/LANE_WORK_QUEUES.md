# Logical-lane work queues and stealing

Status: implemented in `runner_riddle/lane_work.py`; tests in
`tests/test_lane_work.py` (8 tests).

This is a host-control contract for `GAME_PLAN_::` §11.4. It does not execute
mathematics, allocate pages, or own a durable job/lease ledger.

## Invariants

- One queue per logical lane `0..254`; lane `255` is NANNET0 and is rejected.
- Every queue is bounded. A configurable critical reserve prevents speculative
  work from starving control work.
- Only `queued` packets are stealable. `leased`, `executing`, `completed`, and
  `rejected` packets are never moved.
- A stolen item carries its snapshot, preflight digest, capability requirement,
  capability epoch, fuel, role, and priority. It never loses or rewrites them.
- The thief must hold every required capability and an epoch at least as new as
  the item's epoch.
- Critical roles are not stolen; they remain in their assigned lane queue.
- Duplicate packet identities with different scheduling/content metadata are
  rejected instead of silently merged.
- Statistics never claim 255 simultaneous runners. `executing` is at most the
  single active runner slot.

## API

- `WorkItem` — typed packet/queue record.
- `LaneWorkQueues.enqueue(...)` — bounded typed enqueue with conflict detection.
- `dequeue(lane_id)` — priority/tick/packet-ID deterministic pop.
- `begin(packet_id)` / `executing(packet_id)` / `finish(packet_id)` — explicit
  lease/execution/terminal transitions; execution cannot be stolen.
- `steal(thief_lane, capabilities=..., capability_epoch=...)` — deterministic
  capability-safe move of one queued item.
- `reject(packet_id)` and `stats()` — terminal bookkeeping and token-free health.

## Non-claims

- This module does not perform work stealing across processes.
- It does not create a second scheduler or a second lease ledger.
- It does not guarantee remote-worker capability discovery; callers supply the
  current capability set/epoch from the ring/store authority.
