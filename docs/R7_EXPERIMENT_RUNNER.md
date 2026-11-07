# R7 held-out creativity/association experiment runner

Status: control-plane harness and tests are source-written. The test suite is
green with deterministic fake evaluators and synthetic task fixtures. No real
language model was run, no native kernel was executed by this harness, and no
creativity, tunneling, or generalization result is claimed.

## 1. Purpose

`runner_riddle/r7_experiment.py` implements the held-out association part of the
R7 protocol in `docs/R7_CREATIVITY_EXPERIMENT.md`. It accepts:

- a deterministic held-out task split with caller-declared train/dev material;
- caller-supplied baseline and coupled evaluators, or prediction mappings; and
- caller-supplied native evidence from the avoided-crossing sweep, the coupling
  primitive, and the 128-sample phase-coherence fixture.

It scores held-out predictions, computes paired deltas against the disconnected
and random-coupling baselines, produces a deterministic paired bootstrap interval
and sign-flip permutation p-value, and emits a JSON evidence record with a
`supported`, `rejected`, or `inconclusive` status.

The harness deliberately does **not**:

- encode prompts, run an LM, or invent a prediction;
- apply coupling `eta`, diagonalize a Hamiltonian, compute an eigenvalue, or
  evaluate a phasor;
- execute a `.nas` fixture, native process, network, or database;
- treat novelty, usefulness, diversity, latency, or energy as a substitute for
  held-out correctness; or
- persist or promote the result.

Accepted task answers are never passed to an evaluator. `R7EvaluationRequest`
contains only public task and condition metadata.

## 2. Files and tests

- `runner_riddle/r7_experiment.py` — task contract, evaluator hooks, native
  evidence records, scoring, statistics, and gate.
- `tests/test_r7_experiment.py` — 21 deterministic tests covering leakage and
  duplicate rejection, baseline ties, supported improvement, harm, small
  samples, synthetic data, novelty-only output, native-evidence failures, seed
  instability, prediction mappings, reproducible digests, and JSON
  reproducibility.
- `docs/R7_EXPERIMENT_RUNNER.md` — this contract.

```text
python3 -m unittest tests.test_r7_experiment -v
Ran 21 tests
OK
```

Relevant native ABIs:

- `docs/MTH_AVOIDED_CROSSING_SWEEP_ABI.md`;
- `docs/MTH_GRAPH_COUPLE_ABI.md`;
- `docs/MTH_PHASE_COHERENCE_128_ABI.md`.

## 3. API

### 3.1 Construction and protocol

```python
from runner_riddle.r7_experiment import R7Experiment, R7Spec

harness = R7Experiment(R7Spec(
    seeds=(0, 1),
    bootstrap_samples=4000,
    permutation_samples=4000,
    min_tasks=30,
    min_seeds=2,
    min_effect=0.02,
    candidate_eta=0.25,
))
description = harness.describe()
```

Construction requires no evaluator, task set, or native record and makes zero
evaluator calls.

`R7Spec` fields:

| Field | Default | Meaning |
|---|---:|---|
| `seeds` | `(0, 1)` | Unique deterministic evaluation seeds. |
| `bootstrap_samples` | `2000` | Paired task-bootstrap resamples. |
| `permutation_samples` | `2000` | Paired sign-flip permutation samples. |
| `bootstrap_seed` | `20261107` | Base seed for deterministic bootstrap RNGs. |
| `permutation_seed` | `20261108` | Base seed for deterministic permutation RNGs. |
| `confidence` | `0.95` | Two-sided interval confidence; alpha is `1 - confidence`. |
| `min_tasks` | `8` | Minimum admissible held-out task count. |
| `min_seeds` | `2` | Minimum seeds; support cannot rest on one seed. |
| `min_effect` | `0.0` | Required paired mean-delta improvement, exclusive. |
| `candidate_eta` | `0.25` | Coupled-candidate mixing coefficient. |
| `random_eta` | `None` | Random baseline eta; defaults to `candidate_eta`. |
| `novelty_floor` | `0.0` | Novelty gain that triggers the novelty-only check. |

The fixed conditions are:

| Condition | Role | eta | Purpose |
|---|---|---:|---|
| `disconnected` | baseline | `0` | Disconnected D0 control. |
| `random_coupling` | baseline | `random_eta` | Norm-matched R1 random-coupling control. |
| `coupled` | candidate | `candidate_eta` | Coupled treatment. |

Support requires `0 < candidate_eta < 1`; a disconnected or fully mixed
candidate does not test the weak-coupling hypothesis.

### 3.2 Held-out task contract

```python
R7Task(
    task_id="assoc-001",
    prompt="...",
    expected=("accepted answer", "accepted variant"),
    split="heldout",
    task_family="remote_association",
)

R7TaskSet(
    dataset_id="r7-heldout-v1",
    tasks=(...),
    excluded_tasks=(...),       # caller-declared train/dev material
    synthetic=False,
    provenance="frozen prompt set; not used in training",
)
```

Validation rules:

- evaluated tasks must have `split == "heldout"`;
- held-out task IDs and normalized prompts must be unique;
- excluded tasks must not be marked `heldout`; `train`, `dev`, and
  `validation` are conventional labels, and any other non-held-out label is
  metadata only;
- excluded task IDs and normalized prompts must be unique;
- an excluded task ID or normalized prompt may not overlap the held-out split;
- task IDs are 1..128 characters; prompts, task-family names, and accepted
  answers are non-empty.

`R7TaskSet.train_tasks` is a read-only alias for `excluded_tasks`.
Non-held-out evaluated tasks and train/held-out overlap raise
`SplitLeakageError`. Duplicate IDs or normalized prompts raise
`DuplicateTaskError`.

`task_split_digest` is SHA-256 over canonical JSON containing the dataset ID,
synthetic flag, provenance, sorted held-out task identities/prompts/answers,
and sorted excluded task identities/prompts/answers. It is independent of task
order and changes when task content, dataset identity, provenance, or split
material changes.

### 3.3 Evaluator and prediction ABI

Evaluators are callables receiving an `R7EvaluationRequest`:

```python
request.dataset_id
request.task_id
request.prompt
request.task_family
request.split
request.seed
request.condition        # disconnected | random_coupling | coupled
request.role             # baseline | candidate
request.eta
```

The request does **not** contain accepted answers. An evaluator returns either a
prediction string or:

```python
R7Prediction(
    text="candidate answer",
    novelty=0.0..1.0 | None,
    usefulness=0.0..1.0 | None,
)
```

`baseline_evaluator` is called for both baseline conditions, so it can inspect
`request.condition`. `coupled_evaluator` is called for the candidate.

Alternatively, supply prediction mappings:

```python
report = harness.run(
    task_set,
    baseline_predictions={
        "disconnected": {task_id: "..."},
        "random_coupling": {task_id: "..."},
    },
    coupled_predictions={task_id: "..."},
    native_evidence=native,
)
```

A direct `{task_id: prediction}` mapping is reused for both baselines. Nested
maps keyed by condition are also accepted. Supplying both an evaluator and a
prediction map for the same role raises `EvaluatorBindingError`.

### 3.4 Native evidence ABI

The harness accepts three validated records. Values are caller-supplied fixture
outputs or caller-computed summaries; the harness does not recompute them.

```python
from runner_riddle.r7_experiment import (
    AvoidedCrossingEvidence,
    CouplingEvidence,
    PhaseCoherenceEvidence,
    R7NativeEvidence,
)

native = R7NativeEvidence(
    avoided_crossing=AvoidedCrossingEvidence(
        couplings=(0.0, 1.0, 2.0),
        gaps=(...),               # required, same length as couplings
        lower=(...),              # optional, must pair with upper
        upper=(...),
        a=1.0,
        b=3.0,
        source="mth/tests/mth_avoided_crossing_sweep_test.nas",
        status="native_verified", # or fixture_pass | pass | caller_supplied
        steps=11651,
    ),
    phase_coherence=PhaseCoherenceEvidence(
        coherence=1.0,
        sample_count=128,
        source="mth/tests/mth_phase_coherence_128_test.nas",
        status="native_verified",
        steps=11381,
    ),
    coupling=CouplingEvidence(
        eta=0.25,
        source="mth/tests/mth_graph_couple_128_test.nas",
        status="native_verified",
        steps=8637,
    ),
)
```

`R7NativeEvidence.from_mapping(...)` accepts an equivalent dictionary with
`avoided_crossing`/`sweep`, `phase_coherence`/`phase`, and `coupling` keys.
The phase mapping accepts `coherence`, `phase_coherence`, `ratio`, or `r`.

Validation:

- avoided-crossing couplings and gaps are finite, non-empty, at most 256
  entries, and the same length;
- gaps are nonnegative; lower/upper, when supplied, are finite, the same
  length, and ordered `lower <= upper`;
- a non-`caller_supplied` phase-coherence record uses exactly 128 samples;
  `R` is finite and within a small float32 tolerance of `[0, 1]`;
- coupling `eta` is finite in `[0, 1]`;
- evidence status is `native_verified`, `fixture_pass`, `pass`, or
  `caller_supplied`.

`native_verified` records are checked for the expected fixture marker, but the
harness does not re-run the fixture, hash the guest image, or independently
verify provenance. The report always says `verified_by_harness: false`.

Recorded native metrics:

| Group | Report field | Contents |
|---|---|---|
| Transition | `transition_metrics` | `min_gap`, `max_gap`, `mean_gap`, `gap_range`, `min_gap_coupling`, `zero_coupling_gap`, `decoupled_count`, monotonicity, lower/upper extents when supplied. |
| Coupling | `coupling_metrics` | `eta`, `partial_coupling`, `disconnected`, `full_mixing`, mixing weights. |
| Phase | `phase_metrics` | `coherence` (`R`), `incoherence` (`1-R`), sample count. |

The full record includes per-record digests and an overall `evidence_digest`.
Raw arrays are digested, not copied into the report.

Support requires both avoided-crossing and phase-coherence evidence and a
coupling record whose `eta` equals `R7Spec.candidate_eta`. Missing evidence
leaves the result `inconclusive`; contradictory evidence (for example, a
different eta) fails the gate.

### 3.5 Run

```python
report = harness.run(
    task_set,
    baseline_evaluator=baseline,
    coupled_evaluator=coupled,
    native_evidence=native,
)
```

`run_r7_experiment(task_set, *, spec=None, ...)` is a convenience wrapper.
A missing or empty task set produces an `inconclusive` record without calling
any evaluator.

## 4. Scoring and statistics

Prediction matching is model-free:

- `exact`: raw prediction equals an accepted answer after outer whitespace
  stripping;
- `match`: normalized equality after stripping, collapsing whitespace, and
  casefolding;
- `token_match`: accepted-answer token coverage, reported for diagnostics but
  not used by the hard gate.

The hard gate uses the binary `match` value. For each baseline, each task's
delta is the candidate match minus the baseline match, averaged over seeds.
The aggregate records:

- candidate/baseline match rates, `mean_delta`, improved/worse/tied task
  counts, and per-seed deltas;
- a deterministic percentile paired-bootstrap confidence interval over tasks;
- a deterministic two-sided paired sign-flip permutation p-value;
- `reproducible`, meaning every seed mean exceeds `min_effect`;
- novelty means and `novelty_without_correctness`.

The bootstrap resamples tasks, not model calls. RNG seeds are derived
deterministically from `bootstrap_seed`/`permutation_seed` and the baseline
name. Re-running the same inputs produces the same report.

## 5. Hard gate

`supported` is emitted only when all of the following hold:

1. a non-empty held-out dataset is present;
2. the dataset is not marked `synthetic` and has at least `min_tasks` tasks;
3. at least `min_seeds` seeds are present;
4. `0 < candidate_eta < 1`;
5. native avoided-crossing, phase-coherence, and coupling evidence is present
   and valid;
6. the native coupling eta matches `candidate_eta`;
7. for every baseline (`disconnected` and `random_coupling`):
   - paired `mean_delta > min_effect`;
   - the bootstrap lower bound is `> min_effect`;
   - the permutation p-value is `<= 1 - confidence`;
   - every per-seed mean is `> min_effect`; and
8. novelty is not the only improvement: if novelty rises while correctness
   does not, the gate fails.

A candidate that merely ties a baseline fails (`mean_delta <= min_effect`). A
candidate that is worse fails the harm check. If any check definitively fails,
the status is `rejected`.

The status is `inconclusive` when evidence is missing, synthetic, underpowered,
or statistically unstable: for example, a wide interval that includes the
threshold, a permutation p-value above alpha, or an effect that does not
reproduce across seeds. Synthetic or below-`min_tasks` datasets are always
`inconclusive`, even when the observed effect is large or harmful, because they
cannot adjudicate the hypothesis.

Status semantics:

| Status | Meaning |
|---|---|
| `supported` | This held-out task set, baseline matrix, native evidence, and seeded protocol met every gate. |
| `rejected` | The candidate did not improve over a baseline, harmed it, or contradicted required evidence. |
| `inconclusive` | Missing, synthetic, underpowered, or statistically unstable evidence. |

`supported` is not a creativity claim. It means a correct, non-novelty-only
association improvement survived this controlled protocol.

## 6. Evidence record

The report schema is `nanrouter.r7-experiment.v1` and includes:

| Field | Meaning |
|---|---|
| `status`, `evidence_level`, `passed` | Gate result; `passed` is true only for `supported`. |
| `claim` | Explicit `creativity_claim`, `tunneling_claim`, and `generalization_claim` false. |
| `task_split_digest` | Held-out split digest; null when no dataset was supplied. |
| `dataset` | Dataset ID, digest, task count/families, excluded train/dev IDs/splits, synthetic/admissible flags. |
| `protocol` | Seeds, conditions, thresholds, bootstrap/permutation parameters, alpha. |
| `evaluators` | Baseline/coupled source kind and caller ID when available. |
| `native_evidence` | Transition, coupling, and phase metrics, record digests, and `verified_by_harness: false`. |
| `call_counts` | Evaluator calls, prediction lookups, evaluations, expected evaluations. |
| `per_task` | Per-seed condition scores, deltas, novelty deltas, expected answers, prompt digests. |
| `aggregates.conditions` | Match/exact/token rates plus novelty/usefulness means when supplied. |
| `aggregates.deltas` | Per-baseline paired deltas, intervals, p-values, per-seed results, status, reason. |
| `gate` | Every check, its status, and all non-pass reasons. |
| `limitations` | Explicit non-claims and unverified properties. |

The report is JSON-serializable and contains no opaque model state.

## 7. Example

```python
from runner_riddle.r7_experiment import R7Experiment, R7Spec, R7Task, R7TaskSet

task_set = R7TaskSet(
    dataset_id="r7-heldout-v1",
    tasks=(
        R7Task("assoc-001", "prompt one", ("target one",)),
        R7Task("assoc-002", "prompt two", ("target two",)),
        # ...
    ),
    excluded_tasks=(
        R7Task("train-001", "train prompt", ("train answer",), split="train"),
    ),
    provenance="held-out prompts excluded from candidate training",
)

harness = R7Experiment(R7Spec(
    seeds=(0, 1, 2),
    bootstrap_samples=4000,
    permutation_samples=4000,
    min_tasks=30,
    min_effect=0.02,
    candidate_eta=0.25,
))

report = harness.run(
    task_set,
    baseline_evaluator=baseline_hook,   # R7EvaluationRequest -> str/R7Prediction
    coupled_evaluator=coupled_hook,     # R7EvaluationRequest -> str/R7Prediction
    native_evidence=native_evidence,    # fixture outputs, caller-supplied
)
```

## 8. Limitations and non-claims

- **No model.** The harness contains no LM, tokenizer, encoder, or decoder. A
  fake evaluator can pass the tests; that proves gate mechanics only.
- **No native execution or verification.** Fixture outputs are caller data. The
  harness does not assemble or run `.nas` files, hash guest images, or prove
  that a record came from a fixture run.
- **No matrix math.** Coupling, eigenvalue, and phase metrics are accepted as
  scalars/arrays and summarized. The harness does not compute eigenvalues,
  apply `H(eta)`, or evaluate phasors.
- **No contamination proof.** Train/held-out ID and prompt overlap is rejected,
  but the harness cannot prove the candidate evaluator never saw held-out
  answers during training.
- **Bootstrap scope.** The interval resamples only the supplied held-out tasks;
  it does not establish generalization to new tasks or datasets.
- **Synthetic/underpowered data cannot support.** A toy dataset is never
  admissible evidence, regardless of effect size.
- **Novelty is not evidence.** High novelty with unchanged or worse correctness
  is rejected.
- **Only two baselines.** Shuffled-geometry (S1) and phase-scrambled (P1)
  controls from the R7 protocol are not implemented here. The harness also
  cannot verify that the random baseline is topology/norm-matched or that the
  candidate and baselines are compute-matched.
- **No multiple-comparison correction.** The two baseline comparisons are
  reported individually. A broader claim needs the caller's own family-wise or
  false-discovery control.
- **No cost claim.** Latency, energy, memory, and human usefulness ratings are
  outside the hard gate even when caller-supplied.
- **No persistence or promotion.** The harness does not write MC0DB, mutate a
  registry, or enable an adapter.
- **No real result yet.** The only executed evidence is the deterministic fake
  test suite in `tests/test_r7_experiment.py`.

## 9. Next gates

1. Supply a real held-out association/analogy task set with excluded train/dev
   material and non-synthetic provenance.
2. Bind baseline and coupled evaluators that are deterministic under the fixed
   seed protocol and do not inspect accepted answers.
3. Attach avoided-crossing, coupling, and phase-coherence outputs from the
   canonical fixture run, including source/step records.
4. Run multiple seeds, retain the full JSON report, and apply any needed
   multiple-comparison correction.
5. Promote only if the status is `supported` and cost/latency evidence is
   separately justified. Never promote on novelty alone.
