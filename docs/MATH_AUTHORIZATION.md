# Math authorization policy

Status: implemented in `runner_riddle/math_auth.py`; tests in
`tests/test_math_auth.py` (9 tests).

This is the **authorization policy decision point** for `GAME_PLAN_::` §15. It
does not authenticate callers and stores no credentials. The caller must
authenticate the principal through the existing WaveService/point-0 path before
constructing a `Principal`.

## Policy

- Roles map to explicit actions: proposer, validator, tester, approver,
  committer, activator, promoter, pruner, executor, store writer, admin,
  supervisor.
- Revoked principals are denied before any role/capability check.
- `rule.activate` requires the `rule.activate` capability; `rule.prune`
  requires `rule.prune`; promotion requires `rule.promote`; grants require
  `math.grant`.
- Approval, commit, activation, and promotion enforce separation of duty when
  the request context names a proposer: the approver/activator cannot be the
  proposer.
- Admin is explicit (`admin` role or `math.all` capability) and remains
  auditable through the principal digest.
- `require()` raises `AuthorizationDenied`; `authorize()` returns a typed
  `AuthorizationDecision` for normal denials.

## Non-claims

- This module does not validate bearer tokens, issue sessions, or store
  secrets.
- It does not make a rule mathematically valid, execute a kernel, or grant a
  runner capability. Validity, capability admission, ring/JAHS, and lifecycle
  remain separate axes.
- `MathLearningService` optionally enforces this policy (`authorizer=` plus
  `principal=`); with no authorizer, legacy behavior is preserved. Denied
  lifecycle mutations fail closed before any store write.
