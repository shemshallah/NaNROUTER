# Execution evidence contract

Status: implemented in `runner_riddle/execution_evidence.py`; tests in
`tests/test_execution_evidence.py` (5 tests).

This closes the “more than a result digest” gap without pretending the host
verified the result. It is host-control evidence only.

## Fields

- packet/job/kernel/runner identity
- result and optional output digests
- precision
- residual, error bound, saturation, iterations (declared integers)
- guest source/image digests
- lease epoch, ring incarnation/epoch, JAHS
- numerical policy and bounded provenance

## Rules

- Required identities/digests are validated.
- Epochs must be positive; residual/error/saturation/iterations non-negative.
- Secret-like keys are rejected recursively.
- `validate_binding()` checks packet/job/kernel/lease agreement.
- `from_native_mapping()` converts the existing
  `nanrouter.native-kernel-execution.v1` record without host arithmetic.
- The evidence digest is canonical and deterministic.

It does not verify numerical correctness, proof, validity, or truth. A result
digest remains caller/native-executor evidence.
