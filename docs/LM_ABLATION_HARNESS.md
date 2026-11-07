# R9 frozen-base LM adapter ablation harness

Status: control-plane harness and tests are source-written; the test suite is
green with a deterministic fake model. No real language model was run, no
native executor was bound, and no LM, creativity, or generalization benefit is
claimed. The adapter remains disabled until a real held-out ablation passes.

## 1. Purpose

`runner_riddle/lm_ablation.py` is the evidence gate between the R9 adapter
contract (`docs/MTH_LM_ADAPTER_ABI.md`) and any future adapter promotion. It
accepts caller-supplied model behaviour, a held-out task set, and a native
residual executor callback. It then schedules the ablation conditions, scores
the returned strings, computes paired deltas with deterministic paired-bootstrap
intervals, and emits a JSON-serializable evidence record.

The harness deliberately does **not**:

- encode a prompt or run a model;
- compute `h + beta * C u` or any matrix/vector mathematics;
- synthesize, repair, or default a prediction;
- inspect frozen-state tensors or validate their shape;
- call a network, database, GPU, or native process;
- mutate `WaveAdapterConfig` or persist the evidence record.

Every model call is explicit, counted, and issued by the harness. The harness
cannot see calls that caller hooks make internally.

## 2. Files and tests

- `runner_riddle/lm_ablation.py` — the control-plane harness.
- `tests/test_lm_ablation.py` — 16 deterministic tests with a fake frozen model
  and fake residual executor.
- `docs/LM_ABLATION_HARNESS.md` — this contract.

Run the tests:

```text
python3 -m unittest tests.test_lm_ablation -v
Ran 16 tests
OK
```

The native arithmetic this callback is expected to wrap is specified in:

- `docs/MTH_ADAPTER_RESIDUAL_128_ABI.md` and
  `mth/nan16/mth_adapter_residual_128.nas`;
- `docs/MTH_ADAPTER_RESIDUAL_256_BLOCK16_ABI.md` and
  `mth/nan16/mth_adapter_residual_256_block16.nas`.

The harness does not invoke either kernel directly. It only passes a typed
request to the caller's executor.

## 3. API

### 3.1 Construction

```python
from runner_riddle.lm_ablation import LMAdapterAblation, AblationSpec
from runner_riddle.wave_adapter import WaveAdapterConfig

config = WaveAdapterConfig(
    adapter_id="r9-heldout-1",
    universe_id="universe-0",
    base_model_id="frozen-model-id",
    readout_dim=128,
    residual_scale=0.125,
    mode="ring_readout",
    evidence_level="native_verified",
    ablations=("ring_on_off",),
)

harness = LMAdapterAblation(config, spec=AblationSpec())
description = harness.describe()
```

Construction validates only the adapter descriptor and protocol. It requires
no model, executor, or dataset and makes zero model calls. `describe()` reports
`model_required_for_construction: false` and `model_calls_made: 0`.

The harness accepts either a `WaveAdapterConfig` or its `to_dict()` mapping.
`adapter_config_digest` is `sha256(canonical-json(config.to_dict()))`.
`base_model_id` comes from the adapter config.

### 3.2 Frozen model hook ABI

The caller supplies an object with:

```python
model.model_id: str

model.encode(prompt, *, task_id: str, seed: int) -> EncodedState

model.predict(
    state,
    prompt,
    *,
    task_id: str,
    seed: int,
) -> str
```

`EncodedState` is:

```python
EncodedState(base_state: Any, readout_state: Any)
```

The state values are opaque to the harness. It passes `base_state` to the
base-only, adapter-off, and zero-residual paths, and passes the executor result
to the adapter-on path. Only returned strings are scored; the harness never
interprets a state. The frozen model is condition-blind: it is not told which
ablation condition produced a state, so the condition cannot act as a side
channel. The residual executor, which must distinguish enabled/disabled and
zero/nonzero beta, does receive the condition in its typed request.

`model.model_id` must be non-empty and must equal
`adapter_config.base_model_id`; otherwise `ModelBindingError` is raised before
any encode/predict call. The harness cannot verify that the model is actually
frozen, that it was not trained, or that its hooks are deterministic.

### 3.3 Residual executor ABI

```python
executor(ResidualRequest) -> ResidualResult
```

`ResidualRequest` carries:

| Field | Meaning |
|---|---|
| `adapter_id`, `adapter_mode`, `adapter_config_digest` | Adapter identity and digest. |
| `task_id`, `prompt`, `seed`, `condition` | Call site. |
| `base_state`, `readout_state` | Caller-owned encoded state. |
| `beta` | Residual scale for this condition. |
| `enabled` | Whether the adapter path is contract-enabled. |
| `readout_dim` | Adapter descriptor readout dimension. |

`ResidualResult` carries:

| Field | Meaning |
|---|---|
| `state` | Combined or unchanged caller-owned state. |
| `applied` | Whether the residual path executed. |
| `note` | Optional caller note. |

Required executor behaviour:

| Condition | Request | Required result |
|---|---|---|
| `adapter_on` | `enabled=True`, `beta=residual_scale` | `applied=True` |
| `adapter_off` | `enabled=False`, `beta=0.0` | `applied=False`, `state == base_state` |
| `zero_residual` | `enabled=True`, `beta=0.0` | `applied=True`, `state == base_state` |

State equality uses `==`. If equality cannot be evaluated, the harness raises
`ResidualExecutorError`. The executor is expected to wrap a verified native
kernel, but the harness cannot verify that.
`residual_executor.native_verified_by_harness` is always reported as false;
caller-provided evidence is echoed, not trusted.

### 3.4 Task set

```python
AblationTask(task_id, prompt, expected, split="heldout")
AblationTaskSet(
    dataset_id,
    tasks,
    excluded_tasks=(),
    synthetic=False,
    provenance="",
)
```

`expected` is either one accepted string or a tuple of accepted strings.

Validation rules:

- every evaluated task must have `split == "heldout"`;
- task IDs must be unique;
- normalized prompts must be unique;
- excluded task IDs or normalized prompts must not overlap the held-out split;
- task IDs are 1..128 characters;
- prompts and accepted answers must be non-empty.

Non-held-out tasks are rejected with `SplitLeakageError`. Duplicate task IDs or
normalized prompts are rejected with `DuplicateTaskError`. Excluded tasks are
never evaluated; they exist only to prove that caller-declared train/dev data
does not leak into the held-out split.

`task_split_digest` is SHA-256 over canonical JSON containing the dataset ID,
synthetic flag, provenance, sorted held-out task IDs, normalized prompts,
normalized accepted answers, and the excluded task IDs/prompts. It is
independent of task order.

### 3.5 Run

```python
report = harness.run(
    task_set,
    frozen_model=model,
    residual_executor=executor,
)
```

`task_set` is optional only so a missing dataset can produce an `inconclusive`
record. If it is missing or empty, no model or executor is needed and zero
hooks are called. With a non-empty task set, both `frozen_model` and
`residual_executor` are required.

`run_lm_adapter_ablation(config, task_set, *, frozen_model, residual_executor,
spec=None)` is a convenience wrapper that constructs and runs the harness.

## 4. Conditions and controls

| Name | Model path | Purpose |
|---|---|---|
| `base_only` | `predict(encoded.base_state)` | Frozen-base baseline. |
| `adapter_on` | executor with `enabled=True`, `beta=residual_scale`, then predict | Treatment. |
| `adapter_off` | executor with `enabled=False`, `beta=0`, then predict | Contract-disabled control with the executor path exercised. |
| `zero_residual` | executor with `enabled=True`, `beta=0`, then predict | Matched compute control with zero residual. |
| `shuffled_labels` | reuses the `adapter_on` prediction, scores it against shifted held-out labels | Label-permutation control; no extra model call. |

The label control shifts accepted answers by
`label_control_shift % task_count` in task-ID order. The shift is deterministic.
An effective shift of zero, or a shift that leaves every task's accepted-answer
set unchanged, is reported as a degenerate control and cannot pass.

### Call counts

For `N` held-out tasks and `S` seeds, the harness issues exactly:

```text
encode              N * S
predict             N * S * 4
residual_executor   N * S * 3
```

The report records actual and expected counts plus
`matches_expected: true/false`. These counts cover only harness-issued calls.

## 5. Scoring and paired deltas

Matching is intentionally simple and model-free:

- `exact`: raw prediction equals an accepted answer after outer whitespace
  stripping;
- `match`: normalized prediction equals an accepted answer after stripping,
  collapsing whitespace, and casefolding;
- `token_match`: fraction of accepted-answer tokens covered by the prediction,
  reported for diagnostics but not used by the hard gate.

The hard gate uses the binary `match` value. For each task, the harness
computes paired deltas:

```text
adapter_on_vs_base_only
adapter_on_vs_adapter_off
adapter_on_vs_zero_residual
adapter_on_vs_shuffled_labels
```

Each task's delta is averaged over seeds. The aggregate reports:

- `mean_delta`, `improved_tasks`, `worse_tasks`, `tied_tasks`;
- per-seed mean deltas;
- a deterministic percentile paired-bootstrap confidence interval over tasks;
- `reproducible`, meaning at least `min_seeds` seeds were present and every
  seed mean exceeded `min_effect`. `min_seeds` must be at least 2, so a pass
  cannot rest on one seed.

The bootstrap uses a fixed `bootstrap_seed` and a deterministic per-comparison
seed derived from it. It resamples tasks, not prompts or model calls.

## 6. Evidence record

The report has schema `nanrouter.lm-ablation.v1` and includes:

| Field | Meaning |
|---|---|
| `status`, `evidence_level` | `ablation_passed`, `rejected`, or `inconclusive`. |
| `passed` | True only for `ablation_passed`. |
| `claim` | Explicit `creativity_claim: false` and `generalization_claim: false`. |
| `base_model_id` | Frozen base identity from the adapter descriptor. |
| `adapter_config_digest` | SHA-256 of the canonical adapter config. |
| `task_split_digest` | Held-out split digest; null when no dataset was supplied. |
| `model` | Reported model ID and binding status. |
| `adapter` | Full config, digest, evidence level before the run, and recommended level. |
| `dataset` | Dataset ID, digest, task count, split, synthetic/admissible flags. |
| `protocol` | Seeds, conditions, controls, bootstrap parameters, minimums. |
| `residual_executor` | Caller-declared executor ID/evidence; never natively verified. |
| `call_counts` | Actual and expected hook counts. |
| `per_task` | Per-run predictions, exact/match flags, shuffled-label score, deltas. |
| `aggregates.conditions` | Match/exact/token rates for every condition and control. |
| `aggregates.deltas` | Paired deltas, CIs, per-seed results, status and reason. |
| `gate` | Every check, its status, and all non-pass reasons. |
| `limitations` | Explicit non-claims and unverified properties. |

The report is JSON-serializable and does not contain opaque model states.

## 7. Hard gate

`ablation_passed` is emitted only when all of the following hold:

1. a non-empty held-out dataset is present;
2. the dataset is not marked `synthetic`;
3. `task_count >= min_tasks`;
4. `len(seeds) >= min_seeds`;
5. `residual_scale > 0`;
6. the frozen model ID matches `base_model_id`;
7. the shuffled-label control is non-degenerate;
8. every comparison has `mean_delta > min_effect`;
9. every comparison's bootstrap lower bound is `> min_effect`;
10. every comparison's per-seed mean is `> min_effect`.

For an admissible dataset, if any check definitively fails (for example, no
improvement over base or a control), the status is `rejected`. If the evidence
is insufficient or unstable (for example, the CI includes zero or one seed
does not improve), the status is `inconclusive`. A synthetic, underpowered,
missing, or empty dataset is always `inconclusive`; a missing or empty dataset
also makes zero model calls.

Status semantics:

| Status | Meaning |
|---|---|
| `ablation_passed` | This held-out task set and control matrix met every gate. |
| `rejected` | The adapter did not beat the base and/or matched controls, or a definitive check failed. |
| `inconclusive` | Missing, synthetic, underpowered, degenerate, or statistically unstable evidence. |

`ablation_passed` is not a creativity or general-capability claim. It is
report-local and does not mutate the adapter descriptor; the caller must decide
whether to persist or promote the evidence separately.

## 8. Example

```python
from runner_riddle.lm_ablation import (
    AblationSpec, AblationTask, AblationTaskSet, LMAdapterAblation,
)

task_set = AblationTaskSet(
    dataset_id="heldout-v1",
    tasks=(
        AblationTask("assoc-001", "prompt one", ("expected one",)),
        AblationTask("assoc-002", "prompt two", ("expected two",)),
        # ...
    ),
    provenance="frozen prompt set; not used in training",
)

harness = LMAdapterAblation(config, spec=AblationSpec(
    seeds=(0, 1, 2),
    bootstrap_samples=4000,
    min_tasks=30,
    min_seeds=2,
))

report = harness.run(
    task_set,
    frozen_model=frozen_model,          # caller-supplied encode/predict
    residual_executor=native_executor,  # caller-supplied ResidualRequest -> ResidualResult
)
```

## 9. Limitations and non-claims

- **No model math.** The harness never encodes, decodes, applies a residual,
  or chooses a prediction. A fake model can pass the tests; that proves the
  gate mechanics, not LM benefit.
- **No native verification.** The executor callback is trusted only to follow
  the `ResidualRequest`/`ResidualResult` contract. The harness does not verify
  native provenance, kernel correctness, overlap preconditions, NaN/Inf
  handling, non-reentrancy, or digest binding.
- **No hidden-call audit.** Caller hooks can make internal model calls that the
  harness cannot see. `call_counts` is an audit of harness-issued calls only.
- **Seeds are not independent replicates by themselves.** If hooks ignore the
  seed, repeated runs demonstrate repeatability, not independent replication.
  The caller must supply genuinely seed-varying frozen behaviour for a stronger
  reproducibility claim.
- **No training-contamination proof.** The harness can reject caller-declared
  task-ID/prompt overlap, but it cannot prove the frozen model never saw the
  held-out prompts or answers during training. Dataset hygiene still depends on
  caller-supplied provenance.
- **Bootstrap scope.** The CI resamples the supplied held-out tasks. It does not
  establish generalization to other tasks, datasets, models, or prompts.
- **Synthetic and underpowered data cannot pass.** A toy dataset is never
  admissible evidence, even if every fake prediction matches.
- **Not a creativity claim.** No novelty, usefulness, intelligence,
  consciousness, or quantum-tunneling conclusion follows from a match-rate
  delta.
- **No persistence or promotion.** The harness does not write MC0DB, mutate the
  adapter config, change `evidence_level`, or enable the adapter.
- **No multiple-comparison correction.** The four comparisons are reported
  individually. A caller making a broader claim should apply its own
  family-wise or false-discovery control.
- **No cost claim.** Latency, energy, and memory are outside this harness. R7
  and R9 still require cost justification before promotion.
- **No real result yet.** The only executed evidence is the deterministic fake
  test suite in `tests/test_lm_ablation.py`.

## 10. Next gates

1. Bind a real frozen model with immutable `model_id` and seed-stable
   `encode`/`predict` hooks.
2. Bind the residual executor to the verified native 128- or 256-block kernel
   with a recorded operator/source digest.
3. Supply a real held-out task set with excluded train/dev material and
   non-synthetic provenance.
4. Run multiple seeds and the full control matrix; retain the JSON evidence
   record.
5. Promote only if the status is `ablation_passed` and the cost/latency evidence
   separately justifies enabling the adapter.
