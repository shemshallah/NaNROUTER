# Math execution bridge (P5)

Status: implemented in `runner_riddle/math_execution.py`; tests in
`tests/test_math_execution.py` (7 tests) plus the end-to-end demo test.

`MathExecutionBridge` is the only host path from a prepared NMP packet to one
`MthSystem` lease on the active six-slot runner ring. It does not execute
numeric math. The caller supplies an executor callback; the bridge binds the
typed admission, plan digest, NMP packet, durable WaveStore job, ring
incarnation/epoch, JAHS seal, and one lease.

## Flow

```text
MathRuntime.compile
   -> bridge.prepare_packet            # PREFLIGHTED, JAHS-bound
   -> bridge.submit                    # NMP QUEUED + WaveStore queued job
   -> bridge.lease                     # EXECUTING + one active runner lease
   -> bridge.execute(callback)         # caller-supplied result digest
   -> bridge.complete(commit=True)     # COMPLETED/COMMITTED + ring release
```

`bridge.cancel` cancels before a lease, or requests cooperative cancellation
at a plan-step boundary after a lease. A completed result always stands.

## Binding checks

Before creating or leasing a job the bridge checks:

- packet/candidate/function/version/snapshot/admission/preflight/plan digest
  agreement;
- typed admission is `VALID`;
- capability row covers the required workspace and capability epoch;
- current ruleset snapshot and cancellation epoch;
- active ring has a JAHS seal, an active slot, a non-stale heartbeat, and a
  positive epoch;
- the lease owner is the active slot (or a resolvable alias);
- job generation equals the packet generation and the job is still `queued`.

A zero-workspace native kernel is normalized to a one-word NMP guard at the
gate. The capability row must cover that guard; the durable job keeps the real
compiled workspace bound.

## Restart and evidence

The bridge owns no durable truth. `project`, `restart`, and `project_execution`
derive packet state from the authoritative WaveStore job/lease rows. A process
restart therefore reconstructs `QUEUED`, `EXECUTING`, `COMPLETED`, `COMMITTED`,
`FAILED`, or `CANCELLED` from the job rather than trusting an in-memory packet.
The NMP duplicate table is explicitly in-memory and non-durable.

Completion records the result generation, lease token/epoch, admission and
snapshot identifiers in the packet evidence. `commit=True` adds provenance and
an optional output leaf reference.

## Tests

Tests cover ring/JAHS refusal, missing capability, workspace guard coverage,
tampered candidate binding, idempotent duplicate submission, pre-lease
cancellation, lease/execute/complete with ring release, restart projection, and
the demo's committed result with output feedback.
