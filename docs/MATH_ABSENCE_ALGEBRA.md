# Typed absence algebra

Status: implemented in `runner_riddle/math_absence.py`; 59 tests pass.

`ZERO`, `NULL`, `VOID`, `EMPTY`, `UNDEFINED`, `INFINITY`, `UNKNOWN`, `ERROR`,
and `CANCELLED` are distinct typed states. They are never collapsed into a
host `0`/`None`/NaN payload.

## API

- `AbsenceAlgebra.classify(value)` — classify a typed leaf/value without host
  numeric arithmetic.
- `AbsenceAlgebra.to_leaf(state, reason=..., failure_class=..., parents=...)`
  — create an immutable absence leaf; IDs are deterministic.
- `AbsenceAlgebra.conjoin(left, right, missing_is_unknown=True)` — explicit
  table for object/void/null/undefined/empty/error/cancelled conjunctions.
- `AbsenceAlgebra.require_present(value)` — fail closed when a required object
  is absent.

Terminal states (`NULL`, `VOID`, `UNDEFINED`, `UNKNOWN`, `ERROR`, `CANCELLED`)
produce typed leaves with no numeric content and a mandatory reason/failure
class. `ZERO` and `EMPTY` remain valid results and are distinct from absence.

## Semantics

- `NULL` is not numeric zero.
- `VOID` is not a wildcard.
- `OBJECT :: VOID` is `UNKNOWN` if the object can still arrive, or `ERROR` when
  the caller declares the reference required.
- `VOID :: VOID` is an explicit void result.
- `UNDEFINED` is a mathematical result, not an execution error.
- `ERROR`/`CANCELLED` are execution/control outcomes, not mathematical null.
- Missing required objects fail closed.

The host does not evaluate numeric values here; it only classifies typed
metadata and constructs evidence records.
