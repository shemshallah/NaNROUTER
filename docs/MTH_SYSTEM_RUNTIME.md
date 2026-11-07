# MTH system runtime facade

Status: implemented. `runner_riddle/mth_system.py` composes the existing MTH
registry, wave store, authenticated service, and runner-ring scheduler behind
one small control-plane object. It executes no kernel and performs no host
mathematics.

## 1. Purpose

The rest of NaNROUTER should not have to assemble four control-plane objects
before submitting or leasing MTH work. `MthSystem` is a thin delegation layer:

- `MthRegistry` remains the only plan resolver and validator;
- `WaveStore` remains the only owner of jobs, leases, capabilities, and evidence;
- `WaveService` remains the only role-authentication boundary;
- `WaveRingScheduler` remains the only authority for the active runner slot.

`MthSystem` adds no database schema, no second lease ledger, no second math
authority, and no private runner dispatch. It never calls a NaN16 kernel.

## 2. Files

| File | Role |
|---|---|
| `runner_riddle/mth_system.py` | runtime composition facade |
| `tests/test_mth_system.py` | real registry/service/scheduler and temp-SQLite tests |
| `docs/MTH_SYSTEM_RUNTIME.md` | this document |

The registry, store, service, and scheduler modules are not modified.

## 3. Construction

```python
from runner_riddle.mth_registry import MthRegistry
from runner_riddle.mth_system import MthSystem
from runner_riddle.wave_ring_scheduler import WaveRingScheduler
from runner_riddle.wave_service import WaveService
from runner_riddle.wave_store import WaveStore

store = WaveStore("bs0db.sqlite3", "mc0db.sqlite3")
service = WaveService(store, submit_token, worker_token, admin_token)
scheduler = WaveRingScheduler(cycle_ticks=64, now_tick=0)
registry = MthRegistry.load("spec/wave-capabilities.json")

system = MthSystem(
    registry,
    store,
    service,
    scheduler,
    guest_budget_bytes=1024 * 1024,  # 1 MiB target; override per deployment
    workspace_word_bytes=8,           # 64-bit NaN16 word
    enforce_active_slot=True,
)
scheduler.start(now_tick=0)
```

The constructor does not start the scheduler. The caller still owns ring
startup, heartbeat, cycle, failover, and checkpoint policy.

`guest_budget_bytes` is separate from the plan bound and from the runner
ceiling. If it is omitted, the 1 MiB target
(`DEFAULT_GUEST_BUDGET_BYTES = 1024 * 1024`) is used. The effective workspace
budget is:

```text
workspace_budget_bytes = min(guest_budget_bytes, scheduler.max_active_memory_bytes)
```

Health reports derived `guest_budget_words` and `guest_budget_pages` at the
declared 32 KiB page size, plus `workspace_budget_words`, so an adjustable
deployment budget is visible without host-side plan math.

The value is adjustable through the constructor; the 1 MiB default is policy,
not a hardware measurement. No hardware size is invented by this module. `workspace_word_bytes` defaults
to `8` because the point-0 framing contract counts 64-bit NaN16 words; a caller
using a different workspace word width must declare it.

The constructor rejects a service that does not wrap the supplied store, so a
facade cannot accidentally authorize against one store while enqueueing into
another.

## 4. API

| Method | Contract |
|---|---|
| `plan(plan_spec)` | `registry.compose(plan_spec)`, returning a validated `MthPlan` |
| `submit_plan(plan, submit_token, job_id, universe_id, operator_digest, generation, payload, now_tick)` | validate the plan, enforce workspace bounds, then `WaveService.submit_job` |
| `lease(worker_token, owner, now_tick, lease_ticks)` | check the active slot/alias, then `WaveService.lease_job` |
| `complete(worker_token, job_id, lease_token, lease_epoch, result_digest, now_tick)` | `WaveService.complete_job` |
| `register_capability(admin_token, ...)` | `WaveService.register_capability` |
| `store_trace(...)` / `store_seal(...)` / `store_signature(...)` | `WaveService` evidence delegates |
| `ring()` | detached `WaveRingScheduler.snapshot()` |
| `health()` | merged store, registry, ring, and budget report |
| `active_slot()` | point-0 document with current slot and JAHS evidence |
| `point_zero_route()` | stable point-0 route with current slot evidence |

`lease` also requires the scheduler snapshot's `jahs` handoff seal
(`"JAHS"`, "Just A Handoff Seal"). A missing seal is a hard slot error; this is
the same seal carried into every checkpoint digest and checked by the native
`mth_jahs_gate` kernel before a runner accepts activation.

`submit_plan`, `lease`, `complete`, and `register_capability` also accept the
optional keyword arguments of their underlying service methods. In addition,
`submit_plan(..., workspace=N)` lets a caller request a smaller workspace; the
request is capped at `plan.workspace_words`.

### Workspace rules

`submit_plan` applies two independent checks:

1. **Plan bound cap.** The job's workspace is never larger than
   `plan.workspace_words`. If a caller asks for more, the value is clamped to
   the plan bound. A value below the sum required by the plan's steps is
   rejected.
2. **Budget rejection.** The declared plan bound is converted with
   `workspace_word_bytes` and rejected when it exceeds the effective
   guest/runner budget. The check runs before the service or store is called,
   so a rejected plan enqueues nothing.

This keeps the plan bound, the guest budget, and the runner ceiling distinct
instead of treating the 7 GiB active-runner ceiling as a flat product workspace.

### Ring and lease rules

With `enforce_active_slot=True` (the default), `lease` accepts:

- the canonical active slot, such as `MC0:0/R0`;
- the matching declared alias, such as `NANROUTER-0`;
- the active slot index.

Any other slot, an unknown label, or a lease attempt before `scheduler.start()`
raises `MthSystemSlotError` before the service is called. Temporary mismatches
are therefore rejected at the facade, while the durable lease token/epoch check
remains owned by `WaveStore`.

## 5. Point 0

The public route is the canonical address from `spec/address-grammar.md`:

```text
nan://GM0:SC0:MC0:BS0:0:HW0:0
```

`point_zero_route()` and `active_slot()` return the same stable route document.
The current slot is separate evidence:

```json
{
  "schema": "nanrouter.mth-point-zero.v1",
  "route": "nan://GM0:SC0:MC0:BS0:0:HW0:0",
  "point_zero": "BS0:0",
  "wire": "BSR0",
  "started": true,
  "active_slot": 0,
  "active_slot_id": "MC0:0/R0",
  "active_alias": "NANROUTER-0",
  "epoch": 1,
  "stale": false,
  "health": "green"
}
```

The `route` string never contains `R0..R5` or `NANROUTER-*`. The slot identity
and epoch are internal evidence only; they may change behind point 0 without
renumbering clients.

## 6. Health and secrets

`health()` returns schema `nanrouter.mth-system-health.v1` with:

- `status`: `green`, `idle`, or `degraded`;
- `store`: `WaveStore.health()`;
- `registry`: `MthRegistry.health()`;
- `ring`: detached scheduler snapshot;
- `point_zero`: stable route identity;
- `budgets`: word width, declared guest budget, runner budget, effective budget;
- `enforce_active_slot`.

No submit, worker, or admin token is stored on `MthSystem`, passed to the
store, or included in `health()`, `repr()`, or an exception raised by this
module. Lease tokens are store-generated values and are never included in the
health report. The scheduler snapshot contains no callable or credential.

## 7. Error types

| Error | Meaning |
|---|---|
| `MthSystemConfigError` | invalid components or constructor budget/word width |
| `MthSystemPlanError` | the submitted object is not an `MthPlan` |
| `MthSystemWorkspaceError` | plan/job workspace exceeds a bound or budget |
| `MthSystemSlotError` | lease owner is not the active slot/alias |

Registry validation errors (`MthPlanError`) and store errors
(`StaleGenerationError`, `JobConflictError`, `LeaseError`, and so on) propagate
unchanged so callers keep the existing error contracts. Service authorization
errors remain `WaveServiceAuthError`.

## 8. Tests

```sh
python3 -m unittest tests.test_mth_system -v
```

The suite uses a real `MthRegistry` over `spec/wave-capabilities.json`, a real
`WaveService`, a real `WaveRingScheduler`, and temporary SQLite BS0DB/MC0DB
files. It covers plan resolution, submit/lease/complete, active-slot and alias
lease rejection, token-free health, stable point-0 routing across a ring
rotation, stale generation rejection, plan-bound capping, the 7 GiB runner
ceiling, and a separately declared guest budget.

Local result: `Ran 11 tests ... OK`.

## 9. Limitations

- This is an in-process composition layer. It does not start, stop, fence, or
  communicate with a real runner process.
- It does not execute or validate kernel mathematics; a valid plan is only a
  contract candidate.
- It does not call `scheduler.register_lease()` or `release_lease()`. The ring's
  lease counter is a supervisor concern; the durable lease remains in
  `WaveStore`. A supervisor that uses the ring counter must keep both in sync.
- Scheduler state and budgets are not persisted across process restarts.
- The facade does not rotate tokens, implement per-universe ACLs, or add HTTP
  transport. Tokens are supplied on each call.
- The workspace conversion is an explicit declared word width. It is not a
  measurement of the host or guest memory.
- Evidence methods delegate one call at a time; there is no cross-store
  transaction spanning a job and its trace/seal/signature.
- `MthSystem` is imported from `runner_riddle.mth_system`; it is not re-exported
  from the package `__init__` in this change.
