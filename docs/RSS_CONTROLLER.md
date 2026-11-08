# RSS Verb Controller

Status: host-only control-plane implementation for `D-04`
(`docs/MASTER_COMPLETION_TODO.md`) and the §6 verb mapping in
`docs/GRAPH_SPECTRAL_MTH_PLAN.md`.

Source: `runner_riddle/rss_controller.py`
Tests: `tests/test_rss_controller.py`

## 1. Purpose and boundary

`RssController` maps the eight public RSS verbs to registered NaN16 kernels and
composes a validated `MthPlan` for each dispatchable route. It is deliberately a
selector/composer only:

- it performs no numerical or host-language mathematics;
- it executes no kernel and opens no execution, transport, or database path;
- it never substitutes Python/host arithmetic when a kernel is unavailable;
- every math step is a registered `kernel_id` inside an `MthPlan`.

Actual execution remains with the existing admission/NMP/MTH runtime path. A
route result is planning evidence, not execution evidence.

## 2. Verb routing

`DEFAULT_ROUTES` contains one declared kernel per public verb:

| Verb | Default kernel | Intent |
|---|---|---|
| `ENCODE` | `mth.encode.256.full.f32` | preserve relation writes and provenance at the typed boundary |
| `QUERY` | `mth.sparse.laplacian.q16.16` | apply a registered graph operator |
| `MATCH` | `mth.vector.cosine256.f32` | compare normalized signatures with the cosine metric |
| `FILTER` | `mth.graph.filter.poly2.q16.16` | polynomial filter route; currently typed `UNAVAILABLE` |
| `DRIVE` | `mth.drive.source.256.f32` | bounded source injection |
| `PROPAGATE` | `mth.graph.wave_step.f32` | native wave-step primitive |
| `FOLD` | `mth.graph.fold.f32` | guarded symmetry reduction |
| `DECODE` | `mth.decode.256.full.f32` | typed readout/consumer boundary |

Routes can be overridden at construction time. A route value may be a kernel ID,
a sequence of kernel IDs, mappings with `kernel_id`/`name`/`inputs`/`outputs`/
`depends_on`, or `RssPlanStepSpec` objects. Multi-step routes are chained
deterministically: an omitted input consumes the previous step output, an
omitted dependency names the previous step, and omitted names use
`<verb>.<index>`.

`PROPAGATE` and `FOLD` are public route names here because they are part of the
required eight-verb control surface. The lower-level `PROJECT` primitive remains
an internal query/match/filter stage and is not a ninth top-level verb.

## 3. API

```python
from runner_riddle.mth_registry import MthRegistry
from runner_riddle.rss_controller import RssController

registry = MthRegistry.load("spec/wave-capabilities.json")
controller = RssController(
    registry,
    routes=None,              # optional per-verb overrides
    max_steps=16,             # bounded route length
    max_workspace_words=None, # optional hard controller budget
)

result = controller.route(
    "QUERY",
    plan_id=None,             # default: rss.<verb>
    workspace_words=None,     # optional caller bound
    fuel=None,
    cancel_after=None,
)
```

`controller.compose(...)` is an alias of `route(...)`; neither method executes
the plan.

### Result

`RssRouteResult` fields:

| Field | Meaning |
|---|---|
| `verb` | normalized public verb |
| `status` | `PLANNED` or `UNAVAILABLE` |
| `kernel_ids` | ordered kernel IDs for the route |
| `plan` | validated `MthPlan`, or `None` when unavailable |
| `plan_digest` | deterministic SHA-256 of canonical `plan.to_dict()`, or `None` |
| `workspace_words` | validated plan workspace bound |
| `step_count` | number of composed steps |
| `deterministic` | mirrors the plan's deterministic flag |
| `reason`, `detail` | stable reason code and human-readable detail for unavailable routes |

`result.require_plan()` returns the plan for `PLANNED` routes and raises
`RssUnavailableError` otherwise. `result.to_dict()` is JSON-safe.

Other helpers:

- `controller.verbs` — the eight public verbs;
- `controller.routes` — normalized kernel IDs per verb;
- `controller.availability()` — typed status/reason for every verb without
  executing anything;
- `controller.to_dict()` — controller schema, bounds, and route templates;
- `plan_digest(plan)` — canonical plan digest helper.

## 4. Rejection and availability semantics

The controller rejects rather than silently adapting:

- **Unknown/unregistered kernel** → `RssKernelError` with
  `reason="unknown_kernel"`.
- **Non-`native_verified` kernel** → `RssKernelError` with
  `reason="kernel_not_native_verified"`.
- **Registered but not CI-verified kernel** → `RssKernelError` with
  `reason="kernel_not_ci_verified"` (except FILTER, below).
- **Workspace below the plan's required bound**, or above
  `max_workspace_words` → `RssWorkspaceError` with
  `reason="unsupported_workspace"`.
- **Route longer than `max_steps`** → `RssStepLimitError` with
  `reason="step_limit_exceeded"`.
- **Unknown verb** → `RssVerbError` with `reason="unknown_verb"`.
- **Malformed plan request** (including invalid plan ID/fuel/cancel) →
  `RssRequestError` with `reason="plan_rejected"`.

FILTER is intentionally the exception: if its kernel is absent, the route is
returned as `status="UNAVAILABLE"` with no plan and no digest. If the kernel is
registered but not CI-verified, the route is also `UNAVAILABLE`
(`reason="filter_kernel_not_ci_verified"`). This is a typed availability result,
not an error and not a fallback to host math.

At present `mth.graph.filter.poly2.q16.16` is `native_verified` in the manifest
but `ci_verified` is false, so the default FILTER route is `UNAVAILABLE`. It
becomes `PLANNED` automatically only when the registry descriptor is both
`native_verified` and CI-verified; no controller change or host substitution is
required.

## 5. Determinism and no-bypass guarantees

- Plan documents use the existing `MthPlan` v1 serialization, step order, typed
  dataflow names, and registry validation.
- Digests use canonical sorted JSON (`math_objects.canonical_json`) and SHA-256.
  Identical registry, route, plan ID, bounds, and request produce identical
  plan digests.
- The controller has no `execute`, `dispatch`, `submit`, `run`, or `apply`
  method and imports no math/numeric package, subprocess, database, or socket
  module.
- The test suite parses the controller source with `ast` and asserts that there
  are no host math imports, arithmetic `BinOp`/`AugAssign` operations, or
  arithmetic built-in calls such as `sum`, `min`, `max`, `round`, or `pow`.

## 6. Tests

Run:

```sh
python3 -m unittest tests.test_rss_controller -q
```

The 12 tests cover:

1. the eight-verb default route table;
2. validated plan composition for every dispatchable verb;
3. ordered multi-kernel custom route composition;
4. unknown kernel rejection;
5. non-`native_verified` rejection;
6. unknown verb rejection;
7. workspace below requirement and controller budget rejection;
8. bounded step-count rejection;
9. FILTER unavailable when its kernel is absent;
10. real FILTER unavailable because its current descriptor is not CI-verified;
11. deterministic/reproducible plan digests;
12. no host math imports/operations and no execution-bypass API.

## 7. Limitations

- This is a routing/composition layer only. Execution, admission, NMP packets,
  leases, cancellation epochs, and result evidence remain the responsibility of
  the existing runtime path.
- Route kernel IDs and typed value names are control-plane declarations. The
  controller does not validate the numeric ABI, actual input shapes, Q format,
  aliasing, or kernel scratch behavior beyond what `MthRegistry`/`MthPlan`
  already checks.
- MATCH chooses the registered cosine kernel but does not implement metric
  policy, thresholds, or confidence semantics; those belong to the pattern/RSS
  consumer layer.
- FILTER remains unavailable until a dispatchable FILTER kernel exists. No
  host eigensystem, recurrence, or polynomial fallback is allowed.
- FOLD routing does not itself prove the exact symmetry invariant; the guarded
  native kernel and its verification remain authoritative.
- No NANNET page transfer, semantic ledger write, or provenance mutation occurs
  here.
- Plan digests are deterministic identity, not signatures or execution receipts.
