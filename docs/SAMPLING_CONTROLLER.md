# Sampling controller (host-only output/sampling plans)

**Status:** host-only control-plane selector. It composes validated MTH plans
and never executes them. This is the `B-37` output/sampling implementation
slice in `docs/MASTER_COMPLETION_TODO.md`; it is not native kernel evidence and
does not close the native sampling work.

**Module:** `runner_riddle/sampling_controller.py`
**Tests:** `tests/test_sampling_controller.py`
**Scope:** `docs/GAME_PLAN_MTH.md` §4, "Output and sampling operations":
logit scaling, temperature, explicit penalties, top-k, top-p, stable
normalization, seeded categorical sampling, greedy argmax, and deterministic
tie-breaking.

## Boundary

The controller is a selector, not a math implementation:

- it does not compute logits, probabilities, penalties, top-k, top-p, or any
  PRNG value;
- it does not execute, dispatch, submit, or schedule a kernel;
- it does not import `math`, `random`, `secrets`, NumPy, SciPy, or another host
  math/PRNG library;
- it does not substitute a host fallback for a missing native kernel.

A route result is either `PLANNED`, carrying a registry-validated `MthPlan`
and a deterministic SHA-256 plan digest, or `UNAVAILABLE`, carrying a stable
reason code and no plan. A missing or non-dispatchable stage kernel is always
typed `UNAVAILABLE`.

## Stages and modes

Declared stages (`SAMPLING_STAGES`):

| Stage | Purpose |
|---|---|
| `logit_scale` | scale logits by a declared scale |
| `temperature` | temperature transform |
| `penalty` | repetition or frequency penalty, only when explicitly requested |
| `top_k` | top-k candidate selection |
| `top_p` | nucleus / top-p candidate selection |
| `normalize` | stable probability normalization |
| `sample` | seeded categorical sampling |
| `greedy_tiebreak` | greedy argmax with deterministic tie-breaking |

Sampling mode (`mode="sample"`, the default):

```
logit_scale -> temperature -> [penalty] -> top_k -> top_p -> normalize -> sample
```

Greedy mode (`mode="greedy"`):

```
logit_scale -> temperature -> [penalty] -> greedy_tiebreak
```

The optional `penalty` stage is present only when
`penalty_policy` is `repetition` or `frequency`. The default policy is `none`,
matching the game-plan rule that penalties are applied only when explicitly
requested by the model policy.

The seeded sample stage receives `u64.sampling.seed.<seed>` when a seed is
supplied, or `u64.sampling.seed` otherwise. The seed is control-plane metadata
only; it is never used to generate values.

## Declared kernels

`DEFAULT_STAGE_KERNELS` and `STAGE_KERNEL_FAMILIES` in the module are the
authoritative declaration. Current values:

| Stage | Declared kernel | Current manifest state |
|---|---|---|
| `logit_scale` | `mth.sampling.logit.scale.f32` | not registered |
| `temperature` | `mth.sampling.temperature.f32` | not registered |
| `penalty` (repetition) | `mth.sampling.penalty.repetition.f32` | not registered |
| `penalty` (frequency) | `mth.sampling.penalty.frequency.f32` | not registered |
| `top_k` | `mth.topk.256.f32` | registered, `native_verified`, CI-verified |
| `top_p` | `mth.sampling.top.p.f32` | not registered |
| `normalize` | `mth.sampling.softmax.stable.f32` | not registered |
| `sample` | `mth.sampling.categorical.seeded.f32` | not registered |
| `greedy_tiebreak` | `mth.vector.argmax256.f32` | registered, `native_verified`, not CI-verified |

Consequently, on the current manifest every full route is typed `UNAVAILABLE`
because a mandatory stage kernel is missing or not CI-verified. The controller
does not pretend that the registered top-k/argmax kernels complete a sampling
pipeline.

## API

Constants:

- `SAMPLING_STAGES`, `SAMPLING_MODES` (`sample`, `greedy`),
  `SAMPLING_PENALTY_POLICIES` (`none`, `repetition`, `frequency`)
- `DEFAULT_SAMPLING_MODE = "sample"`, `DEFAULT_PENALTY_POLICY = "none"`
- `DEFAULT_STAGE_KERNELS`, `STAGE_KERNEL_FAMILIES`, `PENALTY_KERNELS`
- `SAMPLING_MAX_SEED = 18446744073709551615`
- status constants `SAMPLING_STATUS_PLANNED`, `SAMPLING_STATUS_UNAVAILABLE`
- stable `SAMPLING_REASON_*` codes

Main types:

- `SamplingStageSpec(kernel_id, name=None, inputs=(), outputs=(),
  depends_on=())` — optional per-stage override. Empty fields are filled from
  the declared typed dataflow.
- `SamplingRouteResult` — `status`, `mode`, `penalty_policy`, `seed`, `stages`,
  `kernel_ids`, optional `plan`/`plan_digest`, `reason`, `detail`,
  `workspace_words`, `step_count`, `deterministic`. `require_plan()` raises
  `SamplingUnavailableError` when no plan exists.
- `SamplingController(registry, stages=None, *, max_steps=8,
  max_workspace_words=None, sampling_mode="sample", penalty_policy="none")`
- `controller.route(...)` / `controller.compose(...)` — compose a plan or
  return typed `UNAVAILABLE`.
- `controller.kernel_ids(mode=..., penalty_policy=...)` — declared kernel ids
  for the active stages.
- `controller.availability(...)` — typed status report without execution.
- `controller.to_dict()` — deterministic controller declaration.
- `plan_digest(plan)` — SHA-256 over canonical JSON of the validated plan.

Example:

```python
from runner_riddle.mth_registry import MthRegistry
from runner_riddle.sampling_controller import SamplingController

registry = MthRegistry.load("spec/wave-capabilities.json")
controller = SamplingController(registry)

result = controller.route(
    mode="sample",
    penalty_policy="repetition",
    seed=7,
    workspace_words=4096,
)
if result.available:
    plan = result.require_plan()   # control-plane document only
    print(result.plan_digest)
else:
    print(result.status, result.reason, result.detail)
```

## Validation rules

- `registry` must be an `MthRegistry`.
- `max_steps` must be an integer >= 1.
- `max_workspace_words`, when set, must be an integer >= 0.
- A request's active stage count above `max_steps` raises
  `SamplingStepLimitError` with `step_limit_exceeded`.
- A request workspace below the composed plan's required workspace, or above
  the controller budget, raises `SamplingWorkspaceError` with
  `unsupported_workspace`.
- Mode and penalty policy values are case-insensitive and must be declared;
  otherwise `SamplingModeError` / `SamplingPenaltyError` is raised.
- `seed`, when supplied, must be an unsigned 64-bit integer. It is rejected in
  greedy mode rather than silently ignored.
- Every stage kernel must be present in the registry, have status
  `native_verified`, and have `ci_verified=True`. Declared family kernels that
  fail these checks produce typed `UNAVAILABLE`; an override outside the
  declared family raises `SamplingKernelError`.
- Stage overrides must name a known stage and contain only `kernel_id`, `name`,
  `inputs`, `outputs`, and `depends_on`.
- The composed plan is validated by `MthRegistry.compose`/`validate_plan`;
  failures raise `SamplingRequestError` with `plan_rejected`.

## Reason codes

- Stage capability gaps: `logit_scale_kernel_unavailable`,
  `temperature_kernel_unavailable`, `penalty_kernel_unavailable`,
  `top_k_kernel_unavailable`, `top_p_kernel_unavailable`,
  `normalize_kernel_unavailable`, `sample_kernel_unavailable`,
  `greedy_tiebreak_kernel_unavailable`.
- Rejections: `invalid_config`, `invalid_request`, `invalid_mode`,
  `invalid_penalty_policy`, `unknown_kernel`, `kernel_not_native_verified`,
  `kernel_not_ci_verified`, `step_limit_exceeded`, `unsupported_workspace`,
  `plan_rejected`, `route_unavailable`.

## Determinism

For the same registry declaration, controller configuration, mode, penalty
policy, seed, plan id, workspace bound, fuel, and cancellation bound, the plan
document, route document, and `plan_digest` are identical. Changing the mode,
penalty policy, seed, or plan id changes the plan digest.

## Tests

`tests/test_sampling_controller.py` covers:

1. an available sample-mode plan with stage order, dataflow, workspace, and
   digest;
2. penalty policy stage insertion and greedy-mode tie-break routing;
3. typed `UNAVAILABLE` on the real manifest;
4. typed `UNAVAILABLE` for each missing stage kernel;
5. non-native and non-CI default kernels producing `UNAVAILABLE`;
6. unknown override kernels and invalid stage configuration;
7. workspace-budget rejection and request bounds;
8. step-limit rejection;
9. mode/penalty-policy validation;
10. deterministic digests, seed handling, fuel, and cancellation bounds;
11. availability reporting without execution;
12. an AST boundary check proving no host math/PRNG imports, host arithmetic,
    or execute/dispatch/submit surface.

Run:

```sh
python3 -m unittest tests.test_sampling_controller -q
```

## Limitations

- No sampling, normalization, temperature, penalty, top-p, or logit-scale
  kernel is registered or implemented by this slice.
- `mth.vector.argmax256.f32` is not CI-verified in the current manifest, so the
  greedy route remains unavailable even though the kernel exists.
- Numeric temperature, top-k, top-p, and penalty coefficients are not encoded
  in the plan document. The controller currently selects kernels, stage order,
  penalty policy, and seed only. Numeric hyperparameters require a declared
  typed plan field or kernel ABI extension.
- The seed is metadata for a future native seeded sampler; this module never
  generates random values.
- The controller does not execute, benchmark, or produce evidence for a
  kernel. A `PLANNED` result is not execution evidence and cannot promote a
  kernel.
- Workspace accounting follows `MthRegistry`'s conservative plan bound; it is
  not a measured native working-set claim.
