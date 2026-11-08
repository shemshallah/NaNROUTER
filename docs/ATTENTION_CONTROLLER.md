# Attention Plan Controller

Status: host-only control-plane implementation for `B-34`
(`docs/MASTER_COMPLETION_TODO.md`) and the §4 attention composition in
`docs/GAME_PLAN_MTH.md`.

Source: `runner_riddle/attention_controller.py`
Tests: `tests/test_attention_controller.py`

## 1. Purpose and boundary

`AttentionController` maps the attention vertical slice to explicit registered
NaN16 kernels and composes a validated `MthPlan`:

```
qk_dot -> scale -> [mask] -> softmax -> weighted_sum -> head_concat -> projection
```

It is deliberately a selector/composer only:

- it performs no numerical or host-language mathematics;
- it executes no kernel and opens no execution, transport, or database path;
- it never substitutes Python/host arithmetic when a stage kernel is missing
  or not dispatchable;
- every math step is a registered `kernel_id` inside an `MthPlan`.

Actual execution remains with the existing admission/NMP/MTH runtime path. A
route result is planning evidence, not execution evidence. `B-34` is not
closed by this controller: the native mask, stable-softmax, weighted-sum, and
head-concat kernels still do not exist in the capability manifest.

## 2. Stage routing

`DEFAULT_STAGE_KERNELS` declares one kernel per stage:

| Stage | Default kernel | Intent |
|---|---|---|
| `qk_dot` | `mth.vector.dot256.f32` | query-key dot products |
| `scale` | `mth.vector.axpy256.f32` | declared scaling stage (`y = a*x + y` with a zero-initialized accumulator) |
| `mask` | `mth.attention.mask.f32` | causal and/or padding mask; not registered yet |
| `softmax` | `mth.attention.softmax.stable.f32` | max-subtracted stable softmax; not registered yet |
| `weighted_sum` | `mth.attention.weighted.sum.f32` | weighted value accumulation; not registered yet |
| `head_concat` | `mth.attention.head.concat.f32` | concatenate per-head contexts; not registered yet |
| `projection` | `mth.matvec256.full.f32` | output projection |

The first two and the projection kernel are currently registered and
CI-verified. The mask, softmax, weighted-sum, and head-concat kernel IDs are
intentional placeholders: the route remains typed `UNAVAILABLE` until real
dispatchable kernels are registered under those IDs.

Stage order is fixed. The `mask` stage is omitted only when the requested mask
policy is `none`. Every other stage is mandatory, and every step depends on
the previous step unless a stage override declares different dependencies.

## 3. API

```python
from runner_riddle.attention_controller import AttentionController
from runner_riddle.mth_registry import MthRegistry

registry = MthRegistry.load("spec/wave-capabilities.json")
controller = AttentionController(
    registry,
    stages=None,               # optional per-stage overrides
    max_steps=8,               # bounded active-step count
    max_workspace_words=None,  # optional hard controller budget
    mask_policy="causal",      # controller default
)

result = controller.route(
    plan_id=None,              # default: attention.attend
    mask_policy=None,          # request override; None keeps the default
    workspace_words=None,      # optional caller bound
    fuel=None,
    cancel_after=None,
)
```

`controller.compose(...)` is an alias of `route(...)`; neither method executes
the plan.

A stage override may be a kernel ID, a mapping with
`kernel_id`/`name`/`inputs`/`outputs`/`depends_on`, or an
`AttentionStageSpec`. Empty override fields are filled deterministically from
the declared stage dataflow. Override keys are stage names such as `qk_dot`,
`softmax`, or `projection`.

### Result

`AttentionRouteResult` fields:

| Field | Meaning |
|---|---|
| `status` | `PLANNED` or `UNAVAILABLE` |
| `mask_policy` | normalized mask policy used for the route |
| `stages` | active stage names in plan order |
| `kernel_ids` | ordered kernel IDs for the route |
| `plan` | validated `MthPlan`, or `None` when unavailable |
| `plan_digest` | deterministic SHA-256 of canonical `plan.to_dict()`, or `None` |
| `workspace_words` | validated plan workspace bound |
| `step_count` | number of composed steps |
| `deterministic` | mirrors the plan's deterministic flag |
| `reason`, `detail` | stable reason code and human-readable detail for unavailable routes |

`result.require_plan()` returns the plan for `PLANNED` routes and raises
`AttentionUnavailableError` otherwise. `result.to_dict()` is JSON-safe.

Other helpers:

- `controller.stages` — the fixed stage sequence;
- `controller.critical_stages` — `mask`, `softmax`, `weighted_sum`;
- `controller.kernel_ids` — configured kernel ID per stage;
- `controller.availability(mask_policy=...)` — typed route status without
  executing anything;
- `controller.to_dict()` — controller schema, bounds, policies, and stage
  kernels;
- `plan_digest(plan)` — canonical plan digest helper.

## 4. Mask policy

`mask_policy` must be one of:

- `none` — no mask stage; non-causal, unpadded attention;
- `causal` — lower-triangular causal mask;
- `padding` — exclude padded key positions;
- `causal_padding` — both masks.

Policy tokens are case-insensitive. The policy is encoded in the mask stage's
typed output name, so `causal`, `padding`, and `causal_padding` produce
different deterministic plan digests even though they currently share the same
declared kernel ID. An unknown token or non-string value raises
`AttentionMaskError` with `reason="invalid_mask_policy"`.

## 5. Rejection and availability semantics

The controller rejects rather than silently adapting:

- **Unknown/unregistered kernel in a non-critical stage** → `AttentionKernelError`
  with `reason="unknown_kernel"`.
- **Non-`native_verified` non-critical kernel** → `AttentionKernelError` with
  `reason="kernel_not_native_verified"`.
- **Registered but not CI-verified non-critical kernel** →
  `AttentionKernelError` with `reason="kernel_not_ci_verified"`.
- **Invalid mask policy** → `AttentionMaskError` with
  `reason="invalid_mask_policy"`.
- **Workspace below the plan's required bound**, or above
  `max_workspace_words` → `AttentionWorkspaceError` with
  `reason="unsupported_workspace"`.
- **More active stages than `max_steps`** → `AttentionStepLimitError` with
  `reason="step_limit_exceeded"`.
- **Malformed plan request** (including invalid plan ID/fuel/cancel) →
  `AttentionRequestError` with `reason="plan_rejected"`.

The mask, softmax, and weighted-sum stages are critical. If a critical kernel
is absent, not `native_verified`, or not CI-verified, the route is returned as
`status="UNAVAILABLE"` with no plan and no digest. The reason is stage-specific:

- `mask_kernel_unavailable`
- `softmax_kernel_unavailable`
- `weighted_sum_kernel_unavailable`

This is a typed availability result, not an error and not a fallback to host
math. Because the current manifest has no registered mask kernel, the default
real-manifest route is `UNAVAILABLE` with `mask_kernel_unavailable`; the
`none` policy advances to the missing softmax stage and is also unavailable.

## 6. Determinism and no-bypass guarantees

- Plan documents use the existing `MthPlan` v1 serialization, step order, typed
  dataflow names, and registry validation.
- Digests use canonical sorted JSON (`math_objects.canonical_json`) and SHA-256.
  Identical registry, stage configuration, mask policy, plan ID, bounds, and
  request produce identical plan digests.
- The plan is bounded by `max_steps` and an optional `max_workspace_words`
  budget; `fuel` and `cancel_after` are passed through to the plan contract.
- The controller has no `execute`, `dispatch`, `submit`, `run`, or `apply`
  method and imports no math/numeric package, subprocess, database, or socket
  module.
- The test suite parses the controller source with `ast` and asserts that there
  are no host math imports, arithmetic `BinOp`/`AugAssign` operations, or
  arithmetic built-in calls such as `sum`, `min`, `max`, `round`, or `pow`.

## 7. Tests

Run:

```sh
python3 -m unittest tests.test_attention_controller -q
```

The 12 tests cover:

1. available route composition with all seven explicit kernel steps;
2. default real-manifest `UNAVAILABLE` for the missing mask kernel;
3. missing softmax kernel typed `UNAVAILABLE`;
4. missing mask and weighted-sum kernels typed `UNAVAILABLE`;
5. non-CI softmax typed `UNAVAILABLE` instead of a host fallback;
6. unknown non-critical kernel and unknown stage rejection;
7. non-`native_verified` and non-CI non-critical kernel rejection;
8. workspace below requirement and controller budget rejection;
9. bounded step-count rejection;
10. mask policy validation, `none` behavior, and policy-specific digests;
11. deterministic plan digests and fuel/cancel bounds;
12. no host math imports/operations and no execution-bypass API.

## 8. Limitations

- This is a planning/composition layer only. Execution, admission, NMP packets,
  leases, cancellation epochs, per-head loops, and result evidence remain the
  responsibility of the existing runtime path.
- The mask, stable-softmax, weighted-sum, and head-concat kernels do not exist
  in the current manifest, so the default route is `UNAVAILABLE`. No host
  softmax, mask arithmetic, weighted sum, concatenation, or projection fallback
  is permitted.
- `mth.vector.axpy256.f32` is declared as the scaling stage; the controller
  does not verify the kernel's zero-accumulator calling convention or numeric
  scale factor. That ABI belongs to the eventual attention composition.
- The QK dot stage uses the existing 256-element dot kernel. The controller
  does not orchestrate per-head/per-query loops, batch dimensions, or actual
  tensor shapes.
- Typed value names are control-plane declarations. The controller does not
  validate numeric ABI, actual input shapes, Q format, aliasing, or kernel
  scratch behavior beyond what `MthRegistry`/`MthPlan` already checks.
- Plan digests are deterministic identity, not signatures or execution
  receipts.
