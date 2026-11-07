# Math Rule Lifecycle (P9)

Status: implemented in `runner_riddle/math_learning.py`; tests in
`tests/test_math_learning.py`.

This layer is the **learning/rule-proposal authority** for `GAME_PLAN_::` §13
and P9. It turns a discovery proposal into an append-only, digest-bound rule
version and moves it through validation, testing, approval, commit, and
activation. It does not evaluate mathematics, execute a kernel, build a route,
or grant execution authority.

Authorization is an optional, separate policy layer. When configured, the
existing `MathAuthorizer` from `runner_riddle/math_auth.py` gates every
store-mutating lifecycle action before any version, mapping, or event is
written. When no authorizer is configured, the service keeps its original
behavior exactly.

Persistence uses only the existing `MathStore` tables created by
`runner_riddle/math_store.py`:

| Table | Use |
|---|---|
| `math_rule` / `math_rule_version` | immutable lifecycle versions |
| `math_mapping` | the single transactional rule pointer (`rule:<rule_id>`) |
| `math_event` | append-only proposals, transitions, denials, and experiment evidence |
| `math_payload` | canonical version payloads |

No new database table, schema row, or migration is introduced.

---

## 1. Orthogonal axes

A rule never has one overloaded status field. Every managed version carries
five separate axes under `contract["axes"]`:

```json
{
  "truth":     {"status": "unknown|definitional|theorem|refuted|open|independent",
                "claim": "open|definitional|theorem|...", "basis": []},
  "validity":  {"claimed": "V0|V1|V2|V3", "earned": "V0|V1|V2|V3",
                "basis": [], "stale": false},
  "proof":     {"status": "none|sketch|candidate|checked|refuted|stale|quarantined",
                "proof_digest": null, "checker_digest": null, "trusted": false},
  "lifecycle": {"state": "...", "version": 1, "generation": 1,
                "isolated": false, "active_version": null,
                "proposal_digest": "...", "proposer": "...",
                "validator": null, "tester": null, "approver": null,
                "committer": null, "activator": null,
                "rollback_to": null, "updated_tick": 0},
  "utility":   {"status": "unknown|supported|inconclusive|rejected",
                "score": null, "outcomes": [], "scope": null}
}
```

Rules for the axes:

* A client may set `claimed_validity`; it is stored as `validity.claimed` and
  is **never** authority. `validity.earned` starts at `V0`.
* Structural/type/scope validation earns at most `V1`.
* A bounded deterministic test earns `V2`; it does **not** change `proof` and
  does **not** set truth to `theorem`.
* Only a proof object accepted by a checker configured in
  `trusted_checkers` earns `V3`, sets `proof.status = "checked"`, and may set
  truth to `theorem` (or `definitional` for a definitional claim).
* An untrusted proof is recorded as `proof.status = "candidate"` and earns no
  authority.
* Experiment outcomes update only `utility`. They never change truth,
  validity, proof, or lifecycle state.
* The same digest-bound version must not silently change doctrine: a client
  contract may not contain `validity`, `truth_status`, `proof_status`,
  `axes`, `lifecycle`, `self_promoted`, `production`, `authoritative`, or
  other authority keys. See `_RESERVED_CONTRACT_KEYS`.

`MathRule.proof_status` is derived conservatively: `checked` maps to
`verified`, candidate/sketch maps to `stated`, refuted maps to `rejected`, and
everything else maps to `none`. A passing numerical test never sets
`MathRule.proof_status` to `proven` or `verified`.

---

## 2. Lifecycle state machine

```
proposed
  └─ hash → hashed
       └─ validate → validated
            └─ test → tested
                 └─ approve → approved
                      └─ commit → committed
                           └─ activate → active
                                ├─ deprecate → deprecated
                                │    ├─ revoke → revoked
                                │    └─ archive → archived
                                ├─ revoke → revoked → archive → archived
                                └─ rollback → rolled_back
                                     (mapping points to an earlier active version)

Any pre-active stage may become:
  rejected  (failed structural test / failed bounded tests)
  blocked   (contradiction, or quarantine after an activation CAS failure)
```

Allowed transitions are enforced by explicit methods, never by a free-form
`status` setter:

| Method | Required state | Resulting state |
|---|---|---|
| `propose()` | new identity or superseding terminal identity | `proposed` |
| `hash_proposal()` | `proposed` | `hashed` |
| `validate()` | `hashed` | `validated` or `blocked` |
| `test()` | `validated` | `tested`, `rejected`, or no change on inconclusive |
| `approve()` | `tested` | `approved` or `blocked` |
| `commit()` | `approved` | `committed` or `blocked` |
| `activate()` | `committed` | `active` or `blocked` |
| `deprecate()` | `active` | `deprecated` |
| `revoke()` | active/deprecated/approved/committed/tested/validated | `revoked` |
| `archive()` | deprecated/revoked/blocked/rejected/rolled_back | `archived` |
| `rollback()` | active/deprecated/committed/rolled_back | `rolled_back` |

Every transition creates a **new immutable rule version** with
`version = previous + 1` and `generation = previous + 1`. Old versions remain
readable; no version row or payload is rewritten. Activation and rollback move
the single `math_mapping` row (`rule:<rule_id>`) with compare-and-swap.

---

## 3. API

```python
from runner_riddle.math_learning import (
    ExperimentOutcome,
    MathLearningService,
    RuleProposal,
)
from runner_riddle.math_store import MathStore

store = MathStore(bs0_path, mc0_path)
service = MathLearningService(store, trusted_checkers={"checker:verified"})

proposal = RuleProposal(
    rule_id="math.rule.vector.assoc",
    level=1,
    contract={"claims": {"associative": True}},
    scope={"function_ids": ["math.vector.add"]},
    claim_class="rewrite",
    truth_claim="open",
    claimed_validity="V1",
)

record = service.propose(proposal, proposer="learning:boolean-head-7")
service.hash_proposal("math.rule.vector.assoc", actor="learning:boolean-head-7")
service.validate("math.rule.vector.assoc", validator="validity:engine")
service.test(
    "math.rule.vector.assoc",
    tester="experiment:bounded-1",
    harness="harness:vec-add-1",
    cases=[{"inputs": {"shape": [256]}, "expected": 1, "observed": 1}],
    bounded=True,
)
service.approve("math.rule.vector.assoc", approver="owner:policy")
service.commit("math.rule.vector.assoc", actor="lifecycle:commit")
active = service.activate("math.rule.vector.assoc", actor="lifecycle:activate")

print(active.state)                    # "active"
print(active.version, active.rule.status)
print(service.active_rules())          # production snapshot candidates
```

### Constructors and reads

| Member | Purpose |
|---|---|
| `MathLearningService(store, *, trusted_checkers=(), level0_rules=(), max_test_cases=4096, authorizer=None, principal=None)` | bind the store, proof policy, and optional authorization policy |
| `propose(proposal, *, proposer, expected_generation=None, tick=0)` | write proposal v1 (or a superseding version) |
| `hash_proposal(rule_id, *, actor=None, expected_generation=None, tick=0)` | freeze/hash the proposal |
| `validate(rule_id, *, validator, proof_digest=None, checker=None, expected_generation=None, tick=0)` | structural validation and optional proof submission |
| `test(rule_id, *, tester, cases, harness, bounded=True, expected_generation=None, tick=0)` | bounded evidence; never proof |
| `approve(rule_id, *, approver, expected_generation=None, tick=0)` | independent approval |
| `commit(rule_id, *, actor, expected_generation=None, tick=0)` | immutable commit; still not active |
| `activate(rule_id, *, actor, isolated=False, expected_generation=None, tick=0)` | transactional active mapping |
| `deprecate`, `revoke`, `archive` | terminal lifecycle transitions |
| `rollback(rule_id, *, actor, target_version=None, expected_generation=None, tick=0)` | restore an earlier active mapping pointer |
| `record_experiment(rule_id, outcome, *, actor, request_promotion=False, tick=0)` | append utility evidence only |
| `promote(rule_id, target_level, *, actor, proof_digest=None, checker=None, ...)` | separate level-promotion operation |
| `axes(rule_id, version=None)` | immutable five-axis view |
| `lifecycle(rule_id, version=None)` | head lifecycle view |
| `active_rules(*, include_isolated=False)` | mapping-resolved production/isolated rules |
| `rule_snapshot_id(*, include_isolated=False)` | digest bound to the active rule set |
| `negative_memory()` | reconstructed rejected/blocked/revoked/archived content keys |
| `audit(rule_id)` / `verify_audit(rule_id)` | ordered evidence chain |
| `register_level0(rule)` / `level0_baseline(rule_id)` | pin immutable baselines |

All mutation methods accept an optional `expected_generation`. When supplied it
is checked against the current rule head; stale callers receive
`math_store.StaleGenerationError` before any version is written. When omitted,
the service still reads the current head and passes it to `MathStore.put_rule`
as the CAS expectation, so a concurrent writer cannot be silently overwritten.

### Optional authorization enforcement

`authorizer` is a `runner_riddle.math_auth.MathAuthorizer`; `principal` is an
already-authenticated `runner_riddle.math_auth.Principal`. The service does not
authenticate callers, issue tokens, or store credentials.

* With `authorizer=None`, the service is unchanged: no role, capability, or
  revocation check runs, and `principal` is inert.
* With an authorizer configured, every store-mutating lifecycle action first
  calls the private `_authorize(action, context)`. A missing principal, a
  revoked principal, a missing role, or a missing capability raises
  `LearningAuthorizationDenied` before any rule version, mapping pointer, or
  `math_event` row is written. This error is both a `MathLearningError` and an
  `AuthorizationDenied`, and carries `reason`, `action`, `principal_id`, and the
  typed decision.
* Authorization denials do not append `denied_*` events because that would
  mutate the store. Existing service-level denials (self-validation, negative
  memory, contradictions) still append their events as before.
* The existing separation-of-duty checks remain in force. The authorizer also
  receives the current lifecycle `proposer_id` in its context, so its own
  separation rule applies to approval, commit, activation, and promotion.

Action mapping:

| Lifecycle method | Authorization action | Capability |
|---|---|---|
| `propose`, `hash_proposal` | `rule.propose` | — |
| `validate` | `rule.validate` | — |
| `test`, `record_experiment` | `rule.test` | — |
| `approve` | `rule.approve` | — |
| `commit` | `rule.commit` | — |
| `activate`, `rollback` | `rule.activate` | `rule.activate` |
| `promote` | `rule.promote` | `rule.promote` |
| `deprecate`, `revoke`, `archive` | `rule.prune` | `rule.prune` |

This module has no `prune()` lifecycle method; structural prune plans remain in
`runner_riddle/math_retention.py`. `register_level0()` is intentionally not
authorized because it only pins an in-memory baseline and does not mutate the
store. `promote_by_experiment()` is intentionally not authorized because it
always raises `ExperimentPromotionDenied` and never writes.

### Test cases

`test()` records observed outcomes supplied by an external harness. It does not
compute mathematics:

```python
cases = [
    {"case_id": "c1", "inputs": {"a": [1, 2]}, "expected": 3, "observed": 3},
    {"case_id": "c2", "outcome": "pass"},
    {"case_id": "c3", "outcome": "inconclusive"},
]
```

Allowed normalized outcomes are `pass`, `fail`, and `inconclusive`. If both
`expected` and `observed` are present, their canonical digests must match or
the case is a failure. A failure moves the rule to `rejected`; an inconclusive
case records a denial but leaves the rule at `validated`.

---

## 4. Level 0 and level 3 policy

### Level 0 — immutable

Level 0 covers axioms, type safety, and domain-compatibility rules. Learning
cannot propose them, validate them, promote them, revoke them, or overwrite
them. Protection is applied in three places:

1. `propose()` rejects `level=0` immediately.
2. `_assert_not_level0()` scans every stored version of the same `rule_id` and
   raises `Level0ImmutableError` if any version is level 0.
3. `register_level0()`/`level0_rules=` pins a digest baseline supplied by the
   registry authority, so even a rule not present in the current store is
   protected.

The store still permits the system/registry authority to publish level-0 rules
with `MathStore.put_rule`; the learning service never exercises that path.

### Level 3 — isolation only

* A level-3 proposal may be proposed, validated, tested, approved, committed,
  and activated, but activation requires `isolated=True`.
* `active_rules()` excludes level-3 rules by default.
  `active_rules(include_isolated=True)` includes them for an isolated
  experiment harness.
* `rule_snapshot_id()` changes when the isolation boundary changes.
* Activating a non-level-3 rule with `isolated=True` is rejected.
* A level-3 rule cannot be promoted to a more authoritative level without the
  separate `promote()` operation and a checked, trusted proof.

A level-3 rule can propose another rule. It cannot change level 0 or execute
outside isolation.

---

## 5. Contradiction blocking

Before `validated`, `approved`, `committed`, and `active`, the candidate is
compared with the mapped active rule set:

* claims with the same key and different values;
* a token required by one rule and forbidden by another;
* an explicit `contract["contradicts"]` target;
* only rules in the same isolation domain and overlapping scope are compared.

On a contradiction the candidate becomes `blocked`; the event payload names the
affected rule IDs and the claim/token. The service raises `ContradictionError`
with `record` and `affected`. It never selects a "last writer". The active rule
set is unchanged. Blocked content enters negative memory.

A contradiction does not mean either rule is mathematically false. It means the
pair cannot be promoted into the same authority scope without resolution.

---

## 6. Duplicate proposal and negative memory

Proposal identity is content-addressed:

```text
content = {schema, rule_id, level, claim_class, contract, scope,
           statement, theory, truth_claim, claimed_validity}
content_digest = SHA-256(canonical_json(content))
```

Provenance, proposer identity, tick, evidence, and lifecycle state are
excluded, so two heads that discover the same rule produce the same key.

* Identical content against a non-negative head returns
  `duplicate=True` without creating a version; a `duplicate_proposal` audit
  event is appended.
* Different content for a non-terminal identity raises
  `DuplicateProposalConflict`.
* Supplanting a terminal identity requires
  `supersedes=<previous content digest>`; the new immutable version keeps the
  same level. Level changes require `promote()`.
* Re-proposing unchanged content after `rejected`, `blocked`, `revoked`, or
  `archived` raises `NegativeMemoryError`.
* A retry is allowed only with `supersedes=<negative content digest>` **and** a
  new `new_evidence_digest` different from the prior one.

Negative memory is reconstructed from append-only rule versions, so it
survives process restart without a new table.

---

## 7. Experiment outcomes (Boolean heads / R7 / LM)

```python
service.record_experiment(
    "math.rule.vector.assoc",
    ExperimentOutcome(
        source="r7",                    # boolean_head | r7 | lm_ablation
        outcome="supported",            # supported | ablation_passed |
                                        # inconclusive | rejected
        scope={"function_ids": ["math.vector.add"]},
        sample_size=128,
        seeds=("seed-1", "seed-2"),
        data_digest="a" * 64,
        score=7,
    ),
    actor="experiment:r7-2",
)
```

Guarantees:

* truth, validity, proof, and lifecycle state are byte-for-byte unchanged;
* only `utility.outcomes`, `utility.status`, `utility.score`, and
  `utility.scope` are updated;
* `supported`/`ablation_passed` with synthetic data, underpowered data, zero
  samples, or no data digest is downgraded to `inconclusive`, with the
  requested outcome and reasons retained;
* `request_promotion=True` and `promote_by_experiment()` always raise
  `ExperimentPromotionDenied`;
* activation/completion still requires `validate → test → approve → commit →
  activate`.

This implements `GAME_PLAN_::` §13.8: `supported` and `ablation_passed` are
experiment outcomes, not `validity_level`, `truth_status`, or `proof_status`.

---

## 8. Transactional mapping, rollback, and recovery

`MathStore` enforces one mapping per `(object_type, object_id)`, so the single
`rule:<rule_id>` mapping is the pointer for both the head and activation.

* `put_rule()` CASes both `expected_version` and `expected_generation` inside a
  SQLite transaction.
* `activate()` creates the immutable active version and then confirms the
  mapping with `set_mapping()` using the current mapping version/generation.
  If the mapping CAS fails, the unpointed head is quarantined as `blocked` and
  the error is raised.
* `rollback()` writes an immutable `rolled_back` marker, then calls
  `rollback_mapping("rule:<rule_id>", target_version, expected_version=...,
  expected_generation=...)`. Only the pointer moves; every rule version and
  payload remains readable.
* A rollback target must be an earlier, existing, still-`active` version at the
  same level. The pointer cannot move forward, and no level change is hidden in
  a rollback.
* Repeating the same rollback is idempotent: no new version and no new pointer
  move.

`active_rules()` resolves the mapping to a version and filters on
`rule.status == "active"` plus `axes.lifecycle.state == "active"`. A committed
but not activated version is therefore never production authority. Level-3
rules are excluded unless the caller opts into isolation.

---

## 9. Evidence and audit

Every successful transition appends a `math_event` with:

```json
{
  "layer": "nanrouter.math-learning.v1",
  "action": "propose|hash|validate|test|approve|commit|activate|...",
  "state": "...",
  "proposal_digest": "...",
  "rule_version": 7,
  "generation": 7,
  "actor": "...",
  "truth": "...",
  "validity_earned": "V2",
  "proof": "none",
  "isolated": false,
  "reason": ""
}
```

Denied attempts (self-validation, self-approval, self-promotion, negative
memory, unbounded/inconclusive tests) append `denied_*` events without changing
lifecycle state. `audit(rule_id)` returns the ordered learning events, the
mapping pointer, the current axes, and a chained `audit_digest`:

```text
chain_n = SHA-256(canonical_json({
    "previous": chain_(n-1),
    "evidence_id": event_id,
    "action": action,
    "state": state,
}))
```

`verify_audit()` checks that the chain exists, begins at `proposed`, and (when
`expected_digest` is supplied) matches. `math_event` is protected by SQLite
triggers that reject `UPDATE` and `DELETE`; the test suite verifies this.

---

## 10. Failure semantics

| Condition | Error | State effect |
|---|---|---|
| client sets an authority axis | `ProposalRejected` | no write |
| level 0 touched | `Level0ImmutableError` | no write |
| proposer validates/tests/approves/commits/activates/promotes | `SelfApprovalDenied` | denial event only |
| contradiction | `ContradictionError` | `blocked` + event |
| bounded test failure | `TestFailure` | `rejected` + event |
| inconclusive/missing evidence | `InconclusiveEvidence` | no version change |
| stale generation | `StaleGenerationError` | no version change |
| duplicate content | returned with `duplicate=True` | no version change |
| same identity, different content | `DuplicateProposalConflict` | no write |
| unchanged negative memory | `NegativeMemoryError` | denial event only |
| level-3 activation without isolation | `Level3IsolationError` | denial event only |
| authorization missing/revoked/denied | `LearningAuthorizationDenied` | no write and no event |
| experiment used for promotion | `ExperimentPromotionDenied` | no write |
| wrong lifecycle stage | `LifecycleStateError` | no write |
| audit chain failure | `AuditError` | read-only failure |

Missing or corrupt payload references raise `MathReferenceError` from
`MathStore`; the learning layer never substitutes zero or null.

---

## 11. Test coverage

Run:

```sh
python3 -m unittest tests.test_math_learning -v
```

The 26 tests cover:

| Test | Acceptance link |
|---|---|
| full lifecycle and five axes | G-02, X-01 |
| no new database tables | P0-11 |
| level-0 immutability (stored and pinned) | G-03 |
| level-3 isolation and snapshot exclusion | G-01 |
| self-validation/test/approval/commit/activation denial | A13–A14 |
| contradiction blocking without last writer | G-04, X-10 |
| explicit `contradicts` target | G-04 |
| stale generation CAS | X-11 |
| duplicate proposal dedup | X-14 |
| negative memory and controlled retry | X-14 |
| rollback and idempotence | G-02, X-11 |
| deprecate/revoke/archive | G-02 |
| separate proof-gated level promotion | A13–A14, X-02 |
| experiment outcome utility-only | G-05, X-16 |
| synthetic/underpowered downgrade | X-16 |
| trusted proof → V3/theorem; test ≠ proof | G-05, X-02 |
| client authority-axis rejection | X-01 |
| ordered append-only audit | S-05, D-04 |
| inconclusive test non-promotion | G-05 |
| non-level-3 isolation rejection | G-01 |
| authorization-denied activation fails closed | §15 |
| prune capability required for terminal transitions | §15 |
| revoked principal denied before any write | §15 |
| missing principal fails closed before any write | §15 |
| legacy no-authorizer behavior preserved | §15 |
| authorized admin completes the full lifecycle | §15 |

The module deliberately does not claim:

* that the optional authorizer authenticates the principal, issues sessions,
  or stores secrets — the caller must authenticate before constructing a
  `Principal`;
* that an authorization decision proves mathematical validity, truth, or
  execution authority;
* that a bounded test proves a universal theorem;
* that a Boolean head, R7 result, or LM ablation is validity evidence;
* that an active rule is mathematically true;
* that a rollback deletes or rewrites history;
* that level 3 may be used outside isolation.

Those remain separate authorities and separate evidence, as required by
`GAME_PLAN_::` §13 and §20.8.
