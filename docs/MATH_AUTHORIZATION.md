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

## Class C policy transitions

`ClassCPolicyTransition` is a separate signed record for checker, schema,
ACL-root, control-head, and validity-semantics changes. It requires distinct
proposer and approver principals, the `policy_authority` role, and the
`math.policy` capability. It records old/new policy digests and a detached
signature digest, and explicitly reports `signature_verified=False`; this module
does not perform cryptographic verification. The transition is not yet wired
into every policy mutation.

## Worker identity binding

`WorkerIdentityBinder` maps SHA-256 token fingerprints to a capability owner.
It never stores raw tokens, rejects rebinding the same token to another owner,
and exposes a `verify(token, owner)` callback compatible with the NMP HTTP
`verify_worker_identity` seam. It does not authenticate a credential by itself;
the deployment must obtain the token from its trusted transport.

## Non-claims

- This module does not validate bearer tokens, issue sessions, or store
  secrets.
- It does not make a rule mathematically valid, execute a kernel, or grant a
  runner capability. Validity, capability admission, ring/JAHS, and lifecycle
  remain separate axes.
- `MathLearningService` optionally enforces this policy (`authorizer=` plus
  `principal=`); with no authorizer, legacy behavior is preserved. Denied
  lifecycle mutations fail closed before any store write.
