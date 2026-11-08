# Sequence Controller (host-only token/sequence plans)

**Status:** host-only control-plane selector for the `B-36` token/sequence
implementation slice in `docs/MASTER_COMPLETION_TODO.md`. It composes validated
MTH plans and never executes them. It is not native kernel evidence and does not
close the native token/sequence work.

**Module:** `runner_riddle/sequence_controller.py`
**Tests:** `tests/test_sequence_controller.py`
**Scope:** `docs/GAME_PLAN_MTH.md` §4, "Token and sequence operations":
embedding gather, position application, slicing/windowing, masks, n-grams, and
optional multi-head concatenation.

## Boundary

The controller is a selector, not a math or token implementation:

- it does not compute embeddings, positions, slices, masks, counts, or n-grams;
- it performs no token indexing or host token arithmetic;
- it does not execute, dispatch, submit, or schedule a kernel;
- it does not import `math`, NumPy, SciPy, `random`, `secrets`, or another host
  math/sequence library;
- it does not substitute a host fallback for a missing native kernel.

A route result is either `PLANNED`, carrying a registry-validated `MthPlan` and
a deterministic SHA-256 plan digest, or `UNAVAILABLE`, carrying a stable reason
code and no plan. A missing or non-dispatchable declared stage kernel is always
typed `UNAVAILABLE`.

## Stages

Declared stages (`SEQUENCE_STAGES`):

| Stage | Purpose |
|---|---|
| `embedding_gather` | gather embedding rows for token IDs |
| `position_add` | apply a declared position representation |
| `slice_window` | sequence slice or bounded window |
| `mask_apply` | causal, padding, or combined mask |
| `ngram_build` | n-gram / frequency construction |
| `head_concat` | concatenate per-head sequence contexts (optional) |

Base route (`include_head_concat=False`, the default):

```
embedding_gather -> position_add -> slice_window -> mask_apply -> ngram_build
```

Multi-head route (`include_head_concat=True`):

```
embedding_gather -> position_add -> slice_window -> mask_apply -> ngram_build
                 -> head_concat
```

Every active step depends on the previous step unless a stage override declares
different dependencies. `head_concat` is the only optional stage
(`SEQUENCE_OPTIONAL_STAGES`); the other five are mandatory.

## Declared kernels

`DEFAULT_STAGE_KERNELS` and `STAGE_KERNEL_FAMILIES` are authoritative:

| Stage | Declared kernel | Current manifest state |
|---|---|---|
| `embedding_gather` | `mth.sequence.embedding.gather.f32` | not registered |
| `position_add` | `mth.sequence.position.add.f32` | not registered |
| `slice_window` | `mth.sequence.slice.window.f32` | not registered |
| `mask_apply` | `mth.sequence.mask.apply.f32` | not registered |
| `ngram_build` | `mth.sequence.ngram.build.u32` | not registered |
| `head_concat` | `mth.sequence.head.concat.f32` | not registered |

Consequently, on the current manifest every route is typed `UNAVAILABLE` at the
first stage (`embedding_gather_kernel_unavailable`). The controller does not
pretend that unrelated registered vector kernels implement token/sequence
semantics.

## API

Constants:

- `SEQUENCE_STAGES`, `SEQUENCE_BASE_STAGES`, `SEQUENCE_OPTIONAL_STAGES`
- `SEQUENCE_MASK_POLICIES` (`none`, `causal`, `padding`, `causal_padding`)
- `DEFAULT_MASK_POLICY = "causal"`, `DEFAULT_NGRAM_ORDER = 2`
- `SEQUENCE_MAX_NGRAM_ORDER = 64`, `SEQUENCE_MAX_WINDOW = 1048576`
- `DEFAULT_STAGE_KERNELS`, `STAGE_KERNEL_FAMILIES`
- status constants `SEQUENCE_STATUS_PLANNED`, `SEQUENCE_STATUS_UNAVAILABLE`
- stable `SEQUENCE_REASON_*` codes

Main types:

- `SequenceStageSpec(kernel_id, name=None, inputs=(), outputs=(),
  depends_on=())` — optional per-stage override. Empty fields are filled from
  the declared typed dataflow.
- `SequenceRouteResult` — `status`, `mask_policy`, `include_head_concat`,
  `window`, `ngram_order`, `stages`, `kernel_ids`, optional `plan`/`plan_digest`,
  `reason`, `detail`, `workspace_words`, `step_count`, `deterministic`.
  `require_plan()` raises `SequenceUnavailableError` when no plan exists.
- `SequenceController(registry, stages=None, *, max_steps=8,
  max_workspace_words=None, mask_policy="causal", window=None,
  ngram_order=2, include_head_concat=False)`
- `controller.route(...)` / `controller.compose(...)` — compose a plan or
  return typed `UNAVAILABLE`. Both are planning-only.
- `controller.kernel_ids(include_head_concat=...)` — declared kernel IDs for
  the active stages.
- `controller.availability(...)` — typed status report without execution.
- `controller.to_dict()` — deterministic controller declaration.
- `plan_digest(plan)` — SHA-256 over canonical JSON of the validated plan.

Example:

```python
from runner_riddle.mth_registry import MthRegistry
from runner_riddle.sequence_controller import SequenceController

registry = MthRegistry.load("spec/wave-capabilities.json")
controller = SequenceController(
    registry,
    mask_policy="causal_padding",
    window=128,
    ngram_order=3,
    include_head_concat=True,
)

result = controller.route(workspace_words=4096)
if result.available:
    plan = result.require_plan()   # control-plane document only
    print(result.plan_digest)
else:
    print(result.status, result.reason, result.detail)
```

Request parameters `mask_policy`, `window`, `ngram_order`, and
`include_head_concat` use an internal "unset" sentinel. Omitting one keeps the
controller default. Passing `window=None` explicitly declares an unbounded
window; passing `ngram_order` or `include_head_concat` explicitly normalizes and
validates the request value.

## Validation rules

- `registry` must be an `MthRegistry`.
- `max_steps` must be an integer >= 1.
- `max_workspace_words`, when set, must be an integer >= 0.
- A request's active stage count above `max_steps` raises
  `SequenceStepLimitError` with `step_limit_exceeded`.
- A request workspace below the composed plan's required workspace, or above
  the controller budget, raises `SequenceWorkspaceError` with
  `unsupported_workspace`.
- Mask policies are case-insensitive and must be declared; an invalid value
  raises `SequenceMaskError` with `invalid_mask_policy`.
- `window`, when supplied, must be an integer in `1..SEQUENCE_MAX_WINDOW`.
- `ngram_order` must be an integer in `1..SEQUENCE_MAX_NGRAM_ORDER`.
- `include_head_concat` must be a boolean.
- Every active stage kernel must be present in the registry, have status
  `native_verified`, and have `ci_verified=True`. A declared family kernel that
  fails these checks produces typed `UNAVAILABLE`. An override outside the
  declared family is accepted only when it is registered and passes the same
  native/CI checks; otherwise it raises `SequenceKernelError` (`unknown_kernel`,
  `kernel_not_native_verified`, or `kernel_not_ci_verified`).
- Stage overrides must name a known stage and contain only `kernel_id`, `name`,
  `inputs`, `outputs`, and `depends_on`.
- The composed plan is validated by `MthRegistry.compose`/`validate_plan`;
  failures raise `SequenceRequestError` with `plan_rejected`.

## Reason codes

Stage capability gaps:

- `embedding_gather_kernel_unavailable`
- `position_add_kernel_unavailable`
- `slice_window_kernel_unavailable`
- `mask_apply_kernel_unavailable`
- `ngram_build_kernel_unavailable`
- `head_concat_kernel_unavailable`

Rejections:

- `invalid_config`, `invalid_request`, `invalid_mask_policy`
- `unknown_kernel`, `kernel_not_native_verified`, `kernel_not_ci_verified`
- `step_limit_exceeded`, `unsupported_workspace`
- `plan_rejected`, `route_unavailable`

## Determinism

For the same registry declaration, controller configuration, mask policy,
window, n-gram order, head-concat selection, plan ID, workspace bound, fuel, and
cancellation bound, the plan document, route document, and `plan_digest` are
identical. Changing the mask policy, window, n-gram order, head-concat
selection, or plan ID changes the plan digest because those declarations are
encoded in typed plan value names.

`window=None` is encoded as `f32[256].sequence.window.unbounded`; a declared
window is encoded as `f32[256].sequence.window.<n>`. Mask outputs are encoded as
`f32[256].sequence.masked.<policy>`, and n-gram outputs as
`u32[256].sequence.ngram.<order>`.

## Tests

`tests/test_sequence_controller.py` contains 13 tests covering:

1. an available base plan with stage order, typed dataflow, workspace, and
   digest;
2. optional head-concat composition and its digest change;
3. typed `UNAVAILABLE` on the real manifest;
4. typed `UNAVAILABLE` for each missing stage kernel;
5. non-native and non-CI declared kernels producing `UNAVAILABLE`;
6. unknown override kernels and invalid stage configuration;
7. workspace-budget rejection and request bounds;
8. step-limit rejection;
9. mask/window/n-gram validation bounds;
10. mask, window, and n-gram variants producing distinct digests;
11. deterministic plan digests, request bounds, fuel/cancel, and the
    `compose` alias;
12. availability reporting without execution;
13. an AST boundary check proving no host math/token-arithmetic imports or
    operations and no execute/dispatch/submit surface.

Run:

```sh
python3 -m unittest tests.test_sequence_controller -q
```

## Limitations

- No embedding-gather, position, slice/window, mask, n-gram, or head-concat
  kernel is registered or implemented by this slice. Every real-manifest route
  is therefore `UNAVAILABLE`.
- The controller does not know actual token counts, sequence lengths, embedding
  dimensions, head counts, strides, or table layouts. Those belong to the
  eventual kernel ABIs and typed descriptors.
- Numeric window and n-gram-order values are declarations encoded in plan value
  names; the controller never slices, indexes, counts, or builds n-grams.
- The mask stage is always planned, including `mask_policy="none"`; the policy
  token records the declared identity/no-mask choice rather than omitting the
  step.
- The controller does not execute, benchmark, or produce evidence for a kernel.
  A `PLANNED` result is not execution evidence and cannot promote a kernel.
- Workspace accounting follows `MthRegistry`'s conservative plan bound; it is
  not a measured native working-set claim.
- Plan digests are deterministic identity, not signatures or execution
  receipts.
