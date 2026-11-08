# Logical-lane work queues and stealing

Status: implemented in `runner_riddle/lane_work.py`; contract tests in
`tests/test_lane_work.py` (10 tests) and execution-path integration tests in
`tests/test_lane_work_integration.py` (11 tests).

This is a host-control contract for `GAME_PLAN_::` §11.4. It does not execute
mathematics, allocate pages, or own a durable job/lease ledger.

## Authority

`WaveStore` job rows and `MthSystem` lease rows remain the authoritative job and
lease ledger. A `WorkItem` is only a bounded queue projection of an already
submitted packet or an already acquired lease. The optional
`LaneWorkAdapter` never submits, leases, completes, executes, or extends work
unless the caller explicitly delegates one of those bridge operations. Queue
operations (`enqueue*`, `begin`, `executing`, `finish`, `steal*`, `reject`) do
not call a bridge, scheduler, executor, or execution callback.

The adapter stores no second job/lease/result table:

- `job_id`, `lease_id`, `lease_epoch`, `lease_owner`, and `deadline_tick` are
  copied projection metadata;
- a raw lease token is never stored, only its optional SHA-256 digest;
- the existing `MathExecutionBridge` remains the only bridge and is referenced
  only by the explicit `submit`/`lease`/`execute`/`complete`/`fail`/`cancel`
  wrappers, which delegate to it rather than reimplement it.

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
- Critical roles and any item marked `critical` are not stolen; they remain in
  their assigned lane queue.
- Duplicate packet identities with different scheduling/content metadata,
  lane, job, lease identity, or lease epoch are rejected instead of silently
  merged. An identical mirror is idempotent.
- Statistics never claim 255 simultaneous runners. The adapter does not create
  runner slots; real concurrency remains the bridge/ring's single active
  runner slot.
- `finish(..., state=...)` maps `completed`/`committed`/`done` to `completed`
  and `rejected`/`failed`/`cancelled` to `rejected`.

## Core API

- `WorkItem` — typed packet/queue record, including optional projected job and
  lease identity.
- `LaneWorkQueues.enqueue(...)` — bounded typed enqueue with conflict detection.
- `dequeue(lane_id)` — priority/tick/packet-ID deterministic pop.
- `bind_lease(packet_id, ...)` — attach already-authoritative lease identity.
- `begin(packet_id, ...)` / `executing(packet_id)` / `finish(packet_id, ...)` —
  explicit lease/execution/terminal transitions; execution is never stealable.
- `steal(thief_lane, capabilities=..., capability_epoch=...)` — deterministic
  capability-safe move of one queued item, or `None`.
- `steal_item(packet_id, thief_lane, ...)` — targeted move with typed
  `NotStealable`, `CapabilityMismatch`, or `QueueFull` failures.
- `can_steal(...)` — side-effect-free eligibility check.
- `reject(packet_id)` and `stats()` — terminal bookkeeping and token-free health.

## Adapter API

`LaneWorkAdapter` (aliases `LaneWorkExecutionAdapter`, `LaneWorkBridgeAdapter`,
`LaneWorkQueueAdapter`, `LaneWorkSubmissionAdapter`, `LaneWorkLeaseAdapter`,
`WorkQueueAdapter`, `ExecutionWorkAdapter`) is optional and wraps a
`LaneWorkQueues` plus an optional existing bridge:

- `enqueue_submission(submission)` / `enqueue_packet(packet)` — project a
  submitted packet into `queued`.
- `enqueue_lease(lease)` — project an already acquired lease; an `EXECUTING`
  lease is mirrored as `executing`, otherwise as `leased`.
- `begin(...)`, `executing(...)`, `finish(...)`, `reject(...)` — lifecycle
  transitions with idempotent retry handling.
- `steal(...)`, `steal_item(...)`, `can_steal(...)` — deterministic
  capability/epoch-checked stealing.
- `submit(...)`, `submit_batch(...)`, `lease(...)`, `execute(...)`,
  `complete(...)`, `fail(...)`, `cancel(...)` — explicit delegation wrappers.
  Only these call the supplied bridge; they never create a second bridge.

Existing callers can continue using `LaneWorkQueues` alone. The adapter is not
required by `MathExecutionBridge`, the scheduler, or any execution path.

## Non-claims

- This module does not perform work stealing across processes.
- It does not create a second scheduler or a second lease ledger.
- It does not guarantee remote-worker capability discovery; callers supply the
  current capability set/epoch from the ring/store authority.
- If a bridge operation succeeds but the mirror enqueue fails (for example the
  destination queue is full), the bridge/WaveStore state remains authoritative;
  the adapter reports the queue error and does not roll back or fabricate work.
- The queue/adapter does not itself enforce the ring's one-active-runner
  concurrency guard; `MathExecutionBridge`/`WaveRingScheduler` lease
  accounting remains responsible for that invariant.
- Remote/process stealing and durable ring-epoch recovery remain outside this
  contract.
