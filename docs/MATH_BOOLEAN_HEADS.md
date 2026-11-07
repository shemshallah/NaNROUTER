# Boolean-head experiment gate

Status: implemented in `runner_riddle/math_boolean.py`; tests in
`tests/test_math_boolean.py` (10 tests).

This is the §13.4 / §20.8 X-15 gate for Boolean learning heads. It decides
whether a head's supplied decisions are eligible for an **experiment result or
promotion recommendation**. It is not a mathematical authority, proof checker,
lifecycle service, or executor.

## API

```python
BooleanObservation(
    subject_id: str,
    decision: bool,
    label: bool,
    leaked_label: bool = False,
    leaked_feature: bool = False,
)

BooleanHeadReport(
    head_id: str,
    observations: tuple[BooleanObservation, ...],
    synthetic: bool = False,
    provenance: str = "",
)

BooleanHeadGate().evaluate(
    head: BooleanHeadReport,
    *,
    control_heads: Sequence[BooleanHeadReport],
    shuffled_baseline: BooleanHeadReport,
) -> BooleanHeadGateResult

evaluate_boolean_head(head, *, control_heads, shuffled_baseline)
    -> BooleanHeadGateResult
```

`BooleanHeadReport` also exposes `total`, `correct`, `accuracy`,
`leakage_count`, `label_prevalence`, `chance_accuracy`, `subject_ids()`,
`digest()`, `validate()`, and `to_evidence()`.

`BooleanHeadGateResult` exposes `status`, `eligible`, `reasons`, `checks`,
`max_control_accuracy`, `authority_axes`, `forbidden_axes`, `can_set(axis)`,
`authority()`, and `to_evidence()`.

## Gate rules

A result is eligible only when all of these hold:

1. The candidate report has exactly **1,024** observations.
2. The candidate has exactly **1,024/1,024** correct Boolean decisions.
3. Candidate, every control, and the shuffled baseline have **leakage = 0**.
4. At least **6 control-head reports** are supplied and the candidate's accuracy
   is **strictly greater than every control head's accuracy**. Matching or
   underperforming a control is ineligible.
5. Candidate accuracy is strictly above the majority-class chance rate for its
   labels, and the shuffled baseline is at or below chance plus the fixed
   `CHANCE_TOLERANCE` of `0.02`.
6. The candidate report is not marked synthetic.

Control, shuffled-baseline, and candidate reports must cover exactly the same
subject IDs and each report's subject IDs must be unique. Head IDs must also be
unique across the candidate, controls, and shuffled baseline.

## Fail-closed errors

All derive from `BooleanHeadGateError(ValueError)`:

- `MissingObservationError` — no observations or no controls;
- `ObservationCountError` — not exactly 1,024 observations;
- `DuplicateObservationError` — repeated subject ID within one report;
- `InvalidLabelError` / `InvalidDecisionError` — non-Boolean label/decision;
- `SubjectMismatchError` — reports cover different subject sets;
- `LeakageError` with `LabelLeakageError` / `FeatureLeakageError` — any leaked
  label or feature rejects the report;
- `DuplicateHeadError` — a head ID is reused.

## Utility-only authority

The gate result cannot set mathematical validity, truth, proof, or lifecycle
state. This is explicit in two places:

- `BooleanHeadGateResult.can_set(axis)` returns `True` only for `utility` and
  `experiment_evidence`; every forbidden or unknown axis returns `False`.
- `BooleanHeadGateResult.to_evidence()["authority"]` records
  `can_set_truth=False`, `can_set_validity=False`, `can_set_proof=False`,
  `can_set_lifecycle=False`, `can_promote_rule=False`, and
  `can_execute_candidate=False`.

The evidence record has no `truth_status`, `validity_level`, `proof_status`, or
`lifecycle_state` field. Eligibility is a recommendation, not a promotion; a
separate lifecycle/proof authority must still act.

## Tests

`tests/test_math_boolean.py` covers:

1. perfect head eligibility plus control/shuffled/chance reporting;
2. missing and short observation reports;
3. duplicate subject IDs in candidate and control reports;
4. invalid labels and decisions;
5. mismatched subject IDs for control and shuffled reports;
6. leaked labels, leaked features, and leaked controls;
7. matching/underperforming control and an imperfect candidate;
8. shuffled baseline above chance and fewer than six controls;
9. utility-only `can_set` / authority evidence;
10. wrapper parity and invalid argument handling.

Run:

```sh
python3 -m unittest tests.test_math_boolean -q
```

## Limitations

- Decisions, labels, leakage flags, control reports, and the shuffled baseline
  are entirely caller-supplied. The gate does not train or inspect a head.
- The gate cannot prove held-out separation; `leaked_label` and
  `leaked_feature` are declarations.
- Six control reports are compared by current accuracy. The gate cannot prove
  the control heads were not modified before submission.
- The shuffled baseline is one supplied evaluation, not a distributional
  significance test.
- The result is report-local and is not persisted or wired into
  `MathLearningService` by this module.
- Passing the gate does not authorize execution, activation, or mathematical
  truth.
