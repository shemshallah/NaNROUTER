# Wave Ring Scheduler

`runner_riddle/wave_ring_scheduler.py` is a standard-library-only control-plane
scheduler for the six-slot NaNROUTER runner ring. It models a single active
runner at a time and refuses any handoff that would overlap live leases or live
working memory.

The scheduler does not start processes, allocate host memory, or persist
checkpoint payloads. It is the authoritative in-process state machine that a
runner supervisor must obey.

## Slot identities

There are exactly six slots:

| Index | Canonical ID | Alias |
|---|---|---|
| 0 | `MC0:0/R0` | `NANROUTER-0` |
| 1 | `MC0:0/R1` | `NANROUTER-1` |
| 2 | `MC0:0/R2` | `NANROUTER-2` |
| 3 | `MC0:0/R3` | `NANROUTER-3` |
| 4 | `MC0:0/R4` | `NANROUTER-4` |
| 5 | `MC0:0/R5` | `NANROUTER-5` |

`MC0_SLOTS` and `RING_SLOTS` are the canonical tuple. `NANROUTER_ALIASES` is the
alias tuple, not a second ring. `resolve_slot()` accepts an index, canonical ID,
or alias and returns the same `0..5` index.

## Hard invariants

1. After `start()`, exactly one slot is active.
2. The active slot may reserve at most `max_active_memory_bytes`, which defaults
   to `7 * 1024 ** 3` (7 GiB).
3. Only the active slot may reserve memory or register leases.
4. `cycle()` and `force_failover()` refuse to activate another slot while the
   active slot has any lease or any reserved memory.
5. A checkpoint is taken before the next slot is activated.
6. The previous slot becomes `standby` after a normal cycle and `degraded` after
   a forced failover. Both states have zero reserved memory and zero leases.
7. Every activation increments the ring epoch. The first activation has epoch
   `1`; epochs never decrease.

## Construction

```python
from runner_riddle.wave_ring_scheduler import WaveRingScheduler

scheduler = WaveRingScheduler(
    cycle_ticks=64,
    max_active_memory_bytes=7 * 1024 ** 3,
    now_tick=0,
    checkpoint_store=None,
)
```

- `cycle_ticks` must be a positive integer. It is the expected rotation cadence
  and the heartbeat staleness threshold.
- `max_active_memory_bytes` must be a positive integer.
- `now_tick` is the initial monotonic scheduler tick and must be nonnegative.
- `checkpoint_store` is an optional callable receiving one checkpoint digest
  string. If omitted, checkpoint digests are retained only in process memory.

The constructor does not activate a slot. Call `start()` explicitly.

## State

Each slot records:

- `status`: one of `active`, `standby`, `draining`, `checkpointing`,
  `degraded`, or `revoked`;
- `heartbeat_tick` (or `None` while there is no live heartbeat);
- `memory_reserved_bytes`;
- `lease_count`;
- the last `checkpoint_digest`;
- the `activated_epoch` in which it last became active.

The ring records the active slot index, the current epoch, the last checkpoint,
and the last forced-failover reason and tick.

## API

All tick arguments are monotonic. Omitting a tick uses the scheduler's current
tick. Supplying a tick below the current tick raises `WaveRingSchedulerError`.
All state-changing methods return a detached `snapshot()` on success.

### `start(now_tick=None)`

Activates exactly one eligible slot. It normally selects index `0`, but skips a
slot that was revoked before startup. Calling `start()` twice raises
`RingStateError`.

### `reserve_memory(n)` / `release_memory(n)`

`reserve_memory(n)` adds `n` bytes to the active slot. A reservation that would
exceed `max_active_memory_bytes` raises `RingCapacityError` without changing
state. `release_memory(n)` removes bytes and raises `RingStateError` rather than
allowing underflow. Zero is a no-op; negative and non-integer values are
rejected. New reservations are allowed only while the active slot is `active`,
not while it is draining.

### `register_lease(count=1)` / `release_lease(count=1)`

Registers or releases one or more leases on the active slot. New leases are
accepted only while the slot is `active`. Release is also allowed while the slot
is `draining` or `degraded`, so an interrupted handoff can be completed.

### `heartbeat(now_tick=None)`

Updates the active slot's heartbeat. The heartbeat is stale when:

```text
now_tick - heartbeat_tick > cycle_ticks
```

`is_stale(now_tick)` and `stale_slots(now_tick)` expose the same calculation.
`snapshot(now_tick)` is non-mutating and can be used to evaluate staleness at a
future tick.

### `cycle(now_tick=None)`

Normal handoff:

1. If the active slot has live leases or reserved memory, its status becomes
   `draining`, the tick is recorded, and `RingBusyError` is raised. The epoch and
   active slot do not change.
2. After the caller releases the remaining leases and memory, `cycle()` computes
   a checkpoint digest for the old slot and passes it to the checkpoint store.
3. The old slot becomes `standby` with zero memory, zero leases, and no live
   heartbeat.
4. The next non-revoked slot becomes `active`, receives the heartbeat tick, and
   the ring epoch increments.

If the checkpoint store fails, the old slot becomes `degraded`, the exception is
wrapped as `RingCheckpointError`, and no activation occurs. A later `cycle()`
can retry the handoff.

### `force_failover(now_tick=None, reason="forced")`

Forced handoff after a stale or failed runner. It follows the same drain rules
and refuses with `RingBusyError` while leases or memory remain. With a clean
working set it checkpoints the old slot, marks it `degraded`, records the reason
and tick, activates the next non-revoked slot, and increments the epoch.

Reasons must be a non-blank printable string of at most 256 characters. They are
included in the snapshot as operational metadata, so callers must not put
secrets in them.

### `revoke_slot(slot)` / `restore_slot(slot)`

Revokes a standby or degraded slot so `cycle()` skips it, or restores a revoked
slot to `standby`. The active slot cannot be revoked in place; cycle or fail over
first. A slot holding leases or memory cannot be revoked. Slot arguments accept
canonical IDs and `NANROUTER-*` aliases.

## Checkpoint digests and the JAHS handoff seal

Each handoff computes a lowercase SHA-256 digest over the mandatory `JAHS`
domain separator, the old slot identity, the current epoch, the handoff tick,
and that slot's previous checkpoint digest. The digest is deterministic for the
same state and creates a per-slot chain. The checkpoint store, when configured,
receives exactly that digest string. Its return value is ignored; persistence
is its responsibility.

`JAHS` is the owner's initials and an easter egg that is also load-bearing:
it expands to **"Just A Handoff Seal"**. Every snapshot exposes a `jahs` object
with `seal`, `name`, and `epoch`; every checkpoint records `jahs: "JAHS"`; and
`MthSystem.lease()` refuses to lease work when the active snapshot has no valid
JAHS seal. The runner-side gate is the native NaN16 kernel
`mth/nan16/mth_jahs_gate.nas`, which accepts only the exact 64-bit word
`0x4A414853` ("JAHS" in ASCII). A handoff without the seal is not a valid
handoff.

The latest checkpoint is also exposed in the snapshot as `last_checkpoint` with
the slot index, canonical ID, alias, epoch, tick, digest, and JAHS seal. No
checkpoint payload or credential is stored by the scheduler.

## Snapshot

`snapshot(now_tick=None)` returns plain JSON-safe data: no callable, lock, or
live internal object is exposed. Top-level fields include:

- `schema`, `slot_count`, `slot_ids`, `slot_aliases`;
- `started`, `now_tick`, `cycle_ticks`, `max_active_memory_bytes`;
- `epoch`, `active_slot`, `active_slot_id`, `active_alias`, `active_count`;
- `active_memory_bytes`, `active_memory_reserved_bytes`, `active_lease_count`;
- `jahs` (`seal`, `name`, `epoch`) and the mandatory handoff seal;
- `stale`, `last_checkpoint`, `last_failover_reason`, `last_failover_tick`;
- `health` (`idle`, `green`, `degraded`, `stale`, or `failed`);
- `slots`, with per-slot status, heartbeat, memory, lease, checkpoint, and epoch
  details.

Mutating a returned snapshot does not modify scheduler state.

## Example

```python
scheduler = WaveRingScheduler(cycle_ticks=64, now_tick=1000)
scheduler.start(1000)
scheduler.heartbeat(1010)
scheduler.reserve_memory(512 * 1024 ** 2)
scheduler.register_lease()

try:
    scheduler.cycle(1020)
except RingBusyError:
    # The active slot is now draining. Drain real work before retrying.
    scheduler.release_memory(512 * 1024 ** 2)
    scheduler.release_lease()

snapshot = scheduler.cycle(1030)
assert snapshot["active_slot"] == 1
assert snapshot["epoch"] == 2
assert snapshot["slots"][0]["status"] == "standby"
```

## Limitations

- This is an in-process control plane. It does not enforce memory limits with
  the operating system, cgroups, or a remote runner API. The runner supervisor
  must refuse work when the scheduler reports no reservation or no active slot.
- Only a digest is produced. A real checkpoint payload, its durability, and its
  restore path remain the responsibility of the checkpoint store and runner.
- State is not persisted across process restarts. Recovery must reconstruct the
  ring from the existing runner-ring registry and durable job/lease stores.
- The scheduler does not provide cross-process fencing. Workers should still
  present the ring epoch and their existing lease tokens to the durable store.
- The clock is caller-supplied and must be monotonic. Wall-clock time and
  automatic tick advancement are not modeled.
- The checkpoint callback runs while the scheduler lock is held. It should be
  short and must not block on another thread that needs the same scheduler.
- By design there is no six-way parallelism. The ring provides liveness through
  rotation, not concurrent throughput.

## Tests

```sh
python3 -m unittest tests.test_wave_ring_scheduler -v
```
