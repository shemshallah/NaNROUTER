# R7 held-out experiment runner

Status: implemented in `runner_riddle/r7_experiment.py`; 21 deterministic tests
pass. This is a control-plane evidence harness, not a model or a creativity
claim.

## 1. Purpose

The R7 protocol compares a coupled candidate against disconnected and random
baselines on a deterministic held-out association-task set. It accepts native
avoided-crossing, phase-coherence, and coupling evidence as caller-supplied
records, scores caller-supplied predictions, computes paired deltas with a
deterministic bootstrap interval and sign-flip permutation p-value, and returns
one of:

- `supported` — the candidate beats every required baseline/control and all
  evidence checks pass;
- `rejected` — the candidate is not better, a control fails, or evidence is
  invalid;
- `inconclusive` — the data is missing, synthetic, underpowered, or cannot
  distinguish the candidate.

Novelty alone never passes. No result implies creativity, intelligence,
consciousness, quantum tunneling, or general capability.

## 2. Files

| File | Role |
|---|---|
| `runner_riddle/r7_experiment.py` | task/split contract, evaluator hooks, metrics, gate |
| `tests/test_r7_experiment.py` | leakage/duplicate/control/gate tests |
| `docs/R7_EXPERIMENT_RUNNER.md` | this document |

## 3. API

```python
from runner_riddle.r7_experiment import run_r7_experiment

report = run_r7_experiment(
    task_set,
    spec=spec,
    baseline_evaluator=baseline,   # or baseline_predictions={task_id: answer}
    coupled_evaluator=coupled,     # or coupled_predictions={task_id: answer}
    native_evidence=native_record,
)
```

The task set carries `train`/`dev`/`validation`/`heldout` split labels.
Leakage, duplicate task IDs, non-held-out evaluation, missing evaluators, and
malformed native evidence fail closed. The report includes:

- schema/version, task-split digest, held-out count, seed(s);
- per-task predictions and exact/token/match scores;
- paired deltas for disconnected and random baselines;
- bootstrap confidence interval and sign-flip permutation p-value;
- native avoided-crossing/phase/coupling evidence checks;
- `status` (`supported`/`rejected`/`inconclusive`), per-check outcomes, and
  limitations.

The harness makes no network call, runs no native process, performs no matrix
or eigensolver mathematics, and persists nothing.

## 4. Native evidence

Accepted record kinds:

- avoided-crossing sweep marker `MTH AVOIDED CROSSING SWEEP PASS` with
  couplings/gaps and optional lower/upper eigenvalues;
- phase-coherence marker `MTH PHASE COHERENCE 128 PASS` with the coherence
  ratio `R`;
- coupling marker `MTH GRAPH COUPLE 128 PASS` with `eta`.

The harness validates structure, ordering, finiteness, and marker digest; it
does not independently re-execute the kernels. Native evidence supports the
protocol, but a real result still requires a real frozen model/data holdout.

## 5. Gate

`supported` requires all of:

1. a real (not synthetic) held-out task set above the configured minimum;
2. at least the configured number of seeds and a non-degenerate control;
3. candidate improvement over every required baseline in the overall paired
   interval and in every seed;
4. matching native evidence and no invalid/leaked tasks;
5. no failed control or evidence check.

Otherwise the result is `rejected` or `inconclusive`. The report records why.

## 6. Tests

```bash
python3 -m unittest tests.test_r7_experiment -q
# Ran 21 tests ... OK
```

Coverage includes leakage/duplicate rejection, synthetic/underpowered
inconclusive results, baseline ties, candidate harm, supported improvement,
native-evidence validation, deterministic split/report digests, and the
explicit no-claim limitations.

## 7. Limitations

- No real LM/data set is bundled; all tests use deterministic fake evaluators.
- The harness cannot prove dataset hygiene or that a model never saw the
  held-out prompts.
- Bootstrap/permutation statistics cover only the supplied tasks.
- No creativity, tunneling, or generalization claim is made.
