# Math authorization policy

Status: implemented in `runner_riddle/math_auth.py`; tests in
`tests/test_math_auth.py` (9 tests). Optional `MathStore` enforcement is
implemented in `runner_riddle/math_store.py`; tests in
`tests/test_math_store.py`.

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

## MathStore enforcement

`MathStore(..., authorizer=None, principal=None)` optionally enforces this
policy. With no authorizer, behavior is unchanged and no principal is needed.
When an authorizer is configured:

- Every public read requires `math.read`; every mutation requires `math.write`.
  This includes payloads, leaves/versions, mappings/CAS/rollback, events,
  candidates/admissions, functions/rules, preflight cache writes/deletes, NMP
  packet/transitions, commit intent/evidence/finalize/fail/recovery, discovery
  events, and health projections.
- A missing principal is denied (`PRINCIPAL_REQUIRED`), a revoked principal is
  denied (`PRINCIPAL_REVOKED`), and a role/capability denial raises
  `MathStoreAuthorizationDenied` (also an `AuthorizationDenied`) before any SQL
  touches BS0DB or MC0DB.
- Denials are fail-closed: no payload, version, mapping, event, cache entry,
  NMP record, intent, or evidence row is written. A denied rollback/CAS leaves
  the previous mapping pointer intact.
- A mutation that returns a freshly stored object reloads it without a second
  read check, so a write-only capability is sufficient for the write itself.
  Direct reads still require `math.read`.

Relation versions have no dedicated writer; relation writes flow through mapping
CAS/rollback with `object_type="relation"`. The store keeps only the configured
`Principal` (identity, roles, capabilities, epoch, attributes); it never stores
bearer tokens, passwords, credentials, or secrets. The caller must authenticate
the principal before constructing the store.

## Non-claims

- This module does not validate bearer tokens, issue sessions, or store
  secrets.
- It does not make a rule mathematically valid, execute a kernel, or grant a
  runner capability. Validity, capability admission, ring/JAHS, and lifecycle
  remain separate axes.
- `MathLearningService` optionally enforces this policy (`authorizer=` plus
  `principal=`); with no authorizer, legacy behavior is preserved. Denied
  lifecycle mutations fail closed before any store write. `MathStore` applies
  the same optional pattern to its own reads and writes.
