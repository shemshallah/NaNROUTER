# Ring epoch export and recovery

Status: implemented in `WaveRingScheduler.export_state()` /
`WaveRingScheduler.restore_state()`; tests in `tests/test_wave_ring_scheduler.py`.

The scheduler owns the six-slot, one-active-runner ring. Its epoch advances on
every handoff. Previously the epoch existed only in process memory. Export and
restore now provide a durable seam without making the scheduler a second store:

- `export_state()` returns canonical plain data for cycle cadence, memory cap,
  tick, started/active slot, epoch, checkpoint/failover metadata, and all six
  slot records.
- `restore_state(state)` validates schema, slot identity/order, active-count,
  status values, numeric fields, aliases, and checkpoint digests, then rebuilds
  the scheduler.
- A started scheduler must have exactly one active slot and epoch >= 1; an
  unstarted scheduler must have no active slot and epoch 0.
- The next handoff after restore advances from the restored epoch, not from 1.

The caller remains responsible for persisting the exported document and for
making the real runner honor it. Export/restore does **not** create a durable
lease ledger, a second job ledger, or a distributed lock.

## Non-claims

- The document must be stored by an existing durable owner (for example a
  WaveStore/BS0DB record or deployment checkpoint).
- Restore does not reclaim remote leases or stop a remote process.
- JAHS remains mandatory in checkpoint digests and handoff evidence.
