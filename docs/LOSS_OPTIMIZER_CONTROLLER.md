# Loss / Gradient / Optimizer Plan Controller

Status: host-only control-plane implementation for the planning portion of
`B-35` (`docs/MASTER_COMPLETION_TODO.md`) and the Tier 5 learning primitives in
`docs/GAME_PLAN_MTH.md` §3.

Source: `runner_riddle/loss_controller.py`
Tests: `tests/test_loss_controller.py`

## 1. Purpose and boundary

`LossOptimizerController` maps a training-step route to explicit registered
NaN16 kernels and composes a validated `MthPlan`:

```
loss -> gradient_accumulate -> clip -> moving_average -> update
```

The loss stage selects cross-entropy or negative log likelihood. The update
stage selects Adam or momentum-style parameter update. Every stage is a
declared `kernel_id` inside an `MthPlan`.

It is deliberately a selector/composer only:

- it performs no numerical or host-language mathematics;
- it computes no loss, gradient, norm, moving average, or parameter value;
- it executes no kernel and opens no execution, transport, or database path;
- it never substitutes Python/host arithmetic when a stage kernel is missing
  or not dispatchable;
- every math step is a registered `kernel_id` inside an `MthPlan`.

Actual execution remains with the existing admission/NMP/MTH runtime path. A
route result is planning evidence, not execution evidence. `B-35` is not
closed by this controller: the loss, gradient, clipping, moving-average, Adam,
and momentum kernels do not exist in the current capability manifest, and
finite-difference checks are not implemented here.

## 2. Stage routing

`LOSS_STAGES` fixes the route order:

| Stage | Default kernel | Intent |
|---|---|---|
| `loss` | `mth.loss.cross_entropy.f32` | cross-entropy/NLL value plus loss gradient |
| `gradient_accumulate` | `mth.gradient.accumulate.f32` | deterministic gradient accumulation |
| `clip` | `mth.gradient.clip.global_norm.f32` | gradient clipping / norm constraint |
| `moving_average` | `mth.optimizer.moving_average.f32` | moving-average optimizer state |
| `update` | `mth.optimizer.adam.f32` | Adam parameter update |

Variant kernels are declared explicitly:

| Variant | Stage | Kernel |
|---|---|---|
| `cross_entropy` | `loss` | `mth.loss.cross_entropy.f32` |
| `nll` | `loss` | `mth.loss.nll.f32` |
| `adam` | `update` | `mth.optimizer.adam.f32` |
| `momentum` | `update` | `mth.optimizer.momentum.f32` |

Every kernel ID above is a control-plane placeholder in this revision. None is
registered in `spec/wave-capabilities.json`, so the default route against the
real manifest is typed `UNAVAILABLE`. The controller becomes `PLANNED`
automatically only when real descriptors exist with `status="native_verified"`
and `ci_verified=true`; no controller change or host fallback is required.

Stage order is fixed. Each default step depends on the previous step and
consumes its first output:

- the loss step emits the loss gradient first and the scalar loss value second,
  so gradient accumulation consumes the gradient;
- accumulation feeds clipping;
- clipping feeds the moving-average stage;
- the moving-average result plus optimizer state and model parameters feed the
  update stage.

The loss-kind token and optimizer token appear in typed value names, so
variants have distinct deterministic plan documents even when a caller routes
them through the same stage sequence.

## 3. API

```python
from runner_riddle.loss_controller import LossOptimizerController
from runner_riddle.mth_registry import MthRegistry

registry = MthRegistry.load("spec/wave-capabilities.json")
controller = LossOptimizerController(
    registry,
    stages=None,               # optional per-stage overrides
    max_steps=8,               # bounded stage count
    max_workspace_words=None,  # optional hard controller budget
    loss_kind="cross_entropy",
    optimizer="adam",
)

result = controller.route(
    plan_id=None,              # default: loss.optimize
    loss_kind=None,            # request override; None keeps the default
    optimizer=None,            # request override; None keeps the default
    workspace_words=None,      # optional caller bound
    fuel=None,
    cancel_after=None,
)
```

`controller.compose(...)` is an alias of `route(...)`; neither method executes
the plan.

A stage override may be a kernel ID, a mapping with
`kernel_id`/`name`/`inputs`/`outputs`/`depends_on`, or a `LossStageSpec`.
Empty override fields are filled deterministically from the declared stage
dataflow. Override keys are stage names such as `loss`, `clip`, or `update`.
A stage override replaces the variant-selected default kernel for that stage.

### Result

`LossRouteResult` fields:

| Field | Meaning |
|---|---|
| `status` | `PLANNED` or `UNAVAILABLE` |
| `loss_kind` | normalized loss kind used for the route |
| `optimizer` | normalized optimizer used for the route |
| `stages` | stage names in fixed plan order |
| `kernel_ids` | ordered kernel IDs for the route |
| `plan` | validated `MthPlan`, or `None` when unavailable |
| `plan_digest` | deterministic SHA-256 of canonical `plan.to_dict()`, or `None` |
| `workspace_words` | validated plan workspace bound |
| `step_count` | number of composed steps |
| `deterministic` | mirrors the plan's deterministic flag |
| `reason`, `detail` | stable reason code and human-readable detail for unavailable routes |

`result.require_plan()` returns the plan for `PLANNED` routes and raises
`LossUnavailableError` otherwise. `result.to_dict()` is JSON-safe.

Other helpers:

- `controller.stages` — the fixed stage sequence;
- `controller.loss_kinds` — `cross_entropy`, `nll`;
- `controller.optimizers` — `adam`, `momentum`;
- `controller.kernel_ids(loss_kind=..., optimizer=...)` — configured kernel ID
  per stage for one variant;
- `controller.availability(loss_kind=..., optimizer=...)` — typed route status
  without executing anything;
- `controller.to_dict()` — controller schema, bounds, defaults, stage kernels,
  and declared kernel families;
- `plan_digest(plan)` — canonical plan digest helper.

## 4. Rejection and availability semantics

The controller rejects rather than silently adapting:

- **Unknown override kernel** → `LossKernelError` with
  `reason="unknown_kernel"`.
- **Non-`native_verified` registered kernel** → `LossKernelError` with
  `reason="kernel_not_native_verified"`.
- **Registered but not CI-verified kernel** → `LossKernelError` with
  `reason="kernel_not_ci_verified"`.
- **Unknown loss kind** → `LossKindError` with `reason="invalid_loss_kind"`.
- **Unknown optimizer** → `LossOptimizerError` with `reason="invalid_optimizer"`.
- **Workspace below the plan's required bound**, or above
  `max_workspace_words` → `LossWorkspaceError` with
  `reason="unsupported_workspace"`.
- **More stages than `max_steps`** → `LossStepLimitError` with
  `reason="step_limit_exceeded"`.
- **Invalid stage override or controller bound** → `LossConfigError` with
  `reason="invalid_config"`.
- **Malformed plan request** (including invalid plan ID/fuel/cancel or a
  negative request workspace) → `LossRequestError` with
  `reason="plan_rejected"` or `"invalid_request"` as applicable.

A declared stage-family kernel that is absent from the registry is a typed
capability gap, not a configuration error. The route is returned as
`status="UNAVAILABLE"` with no plan and no digest. The reason is stage-specific:

- `loss_kernel_unavailable`
- `gradient_accumulate_kernel_unavailable`
- `clip_kernel_unavailable`
- `moving_average_kernel_unavailable`
- `update_kernel_unavailable`

This distinction is deliberate: a missing declared capability is
`UNAVAILABLE`, while a caller-supplied kernel ID outside the declared stage
family is a rejected unknown kernel. Neither case falls back to host math.

## 5. Determinism and no-bypass guarantees

- Plan documents use the existing `MthPlan` v1 serialization, step order, typed
  dataflow names, and registry validation.
- Digests use canonical sorted JSON (`math_objects.canonical_json`) and SHA-256.
  Identical registry, stage configuration, loss kind, optimizer, plan ID,
  bounds, and request produce identical plan digests.
- The plan is bounded by `max_steps` and an optional `max_workspace_words`
  budget; `fuel` and `cancel_after` are passed through to the plan contract.
- The controller has no `execute`, `dispatch`, `submit`, `run`, or `apply`
  method and imports no math/numeric package, subprocess, database, or socket
  module.
- The test suite parses the controller source with `ast` and asserts that there
  are no host math imports, arithmetic `BinOp`/`AugAssign` operations, or
  arithmetic built-in calls such as `sum`, `min`, `max`, `round`, or `pow`.

## 6. Tests

Run:

```sh
python3 -m unittest tests.test_loss_controller -q
```

The 12 tests cover:

1. available route composition with all five explicit native stage steps;
2. loss-kind and optimizer kernel selection plus variant-specific digests;
3. default real-manifest `UNAVAILABLE` for the missing loss kernel;
4. stage-specific typed `UNAVAILABLE` for each missing stage kernel;
5. unknown override kernel, unknown stage, empty kernel, and unknown override
   field rejection;
6. non-`native_verified` and non-CI kernel rejection;
7. workspace below requirement and controller workspace budget rejection;
8. bounded step-count and invalid bound rejection;
9. loss-kind and optimizer validation;
10. deterministic plan digests, plan-ID variation, and fuel/cancel pass-through;
11. availability reports `PLANNED`, `UNAVAILABLE`, and `REJECTED` without
    execution;
12. no host math imports/operations and no execution-bypass API.

## 7. Limitations

- This is a planning/composition layer only. Execution, admission, NMP packets,
  leases, cancellation epochs, gradient buffers, parameter-state ownership, and
  result evidence remain the responsibility of the existing runtime path.
- The loss, gradient, clipping, moving-average, Adam, and momentum kernels do
  not exist in the current manifest, so the default route is `UNAVAILABLE`. No
  host loss, gradient, clipping, moving-average, or optimizer fallback is
  permitted.
- Typed value names are control-plane declarations. The controller does not
  validate numeric ABI, actual shapes, Q format, aliasing, kernel scratch
  behavior, or in-place state contracts beyond what `MthRegistry`/`MthPlan`
  already checks.
- Hyperparameters are not represented in the plan: loss reduction mode,
  accumulation count, clipping threshold/norm order, moving-average decay,
  Adam betas/epsilon, momentum coefficient, and learning rate belong to the
  eventual kernel ABI or caller-side typed inputs. The controller does not
  compute or validate them.
- The moving-average stage is always present. There is no `none` policy in this
  revision, so a missing moving-average kernel makes the route `UNAVAILABLE`
  rather than silently skipping the stage.
- Finite-difference gradient checks from Tier 5 are not implemented by this
  controller. They require native fixture execution and evidence, not a plan
  composition.
- Plan digests are deterministic identity, not signatures or execution
  receipts.
