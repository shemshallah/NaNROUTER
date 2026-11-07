# BRAINSTORM 1 — GAME_PLAN `::` traceability and parallel execution plan

**Date:** 2026-11-07
**Repository:** `/data/data/com.termux/files/home/NaNROUTER`
**Baseline:** `606cb77`; full suite 653 tests, 1 skipped, OK.
**Canonical plan:** `docs/GAME_PLAN_::.md`
**Evidence ledger:** `docs/R10_IMPLEMENTATION_EVIDENCE.md`
**Status:** audit + implementation brainstorm. This document is not an implementation claim.

This file consolidates three independent read-only audits of the game plan:

1. **Agent A** — §§3–8: authority, namespace/identity, leaves, registry, linker, validity.
2. **Agent B** — §§9–12: NMP, storage, ring/lanes/capabilities, absence.
3. **Agent C** — §§13–20: learning/proof, retention, security, 2 MiB, demo, phases, verification matrix.

The third audit agent was interrupted repeatedly; its §9–12 report below is reconstructed from direct inspection of the code, schemas, and tests during this session. It is explicitly marked as reconstructed rather than claiming an uninterrupted agent transcript.

The final section is the unified parallel implementation plan.

---

# Agent A — §§3–8 audit

## 1. Gap table

| Requirement | Code / test evidence | Status | Exact gap |
|---|---|---|---|
| §3.2 “validity engine must be on the only path”; §8.1 “only writer of preflight authorization” | `runner_riddle/math_runtime.py:272-309`; `runner_riddle/mth_system.py:172-240`; `tests/test_math_end_to_end.py:136-147` | partial | `MathRuntime.submit()` calls `MthSystem.submit_plan()` after `require_admission()` only. It creates no NMP packet, no ring binding, and no capability gate. `MthSystem.submit_plan()` has no admission parameter. This is a second host execution path besides `MathExecutionBridge`. |
| §3.2 / §8.1 candidate-bound admission | `runner_riddle/math_runtime.py:182-186`; `runner_riddle/math_execution.py:799-862`; `runner_riddle/math_validity.py:2949-2988` | partial | `compile()` checks only `admission.verdict == VALID`. It does not check `admission.candidate_id == candidate.candidate_id`, snapshot equality, or function-version equality. `_validate_compiled_binding()` never compares `compiled.admission.candidate_id` to the packet/compiled candidate. A VALID admission for candidate A can authorize candidate B if they share a snapshot. |
| §7.2 candidate → preflight chain; §8.2 snapshot lock | `runner_riddle/math_runtime.py:134-177`; `runner_riddle/math_linker.py:377-388`; `runner_riddle/math_validity.py:414-460` | partial | `snapshot_for()` rebuilds a snapshot containing only one function and leaf pins, with `rules=()` and `capabilities=()`. It uses `self.functions.require(candidate.function_id)` without `candidate.function_version`. `LinkSnapshot` carries only digests, not rule/function contracts, so `MathRuntime.preflight(candidate)` cannot bind the linker’s rule/capability snapshot. |
| §3.2 lease with matching snapshot; §8.5 cache invalidation | `runner_riddle/math_execution.py:953-1000, 1564-1794, 1978-2123`; `runner_riddle/nmp.py:2079-2090` | partial | `submit()` calls `runtime.submit()`, which calls `require_admission()` once. `lease()`, `execute()`, and `complete()` do not re-run `require_admission()`. `ruleset_snapshot` and authorization context are optional; with the default `None`, `_ruleset_gate()` only checks that the packet has a ruleset ID. A rule/auth/capability change after submit is not detected. |
| §3.2 “experimental candidate … executed as if level 0” | `runner_riddle/math_validity.py:2898-2919`; `runner_riddle/nmp.py:2016-2029` | partial / ambiguity | Validity allows `EXPERIMENTAL` with `allow_experimental` + isolated plan. NMP `_admission_gate()` requires `VALID`, and `_ADMISSION_FAILURE` maps `EXPERIMENTAL` to a terminal failure. There is no isolated NMP execution path, so the two layers disagree. |
| §3.3 orthogonal truth/validity/proof/lifecycle axes | `runner_riddle/math_objects.py:97-288`; `runner_riddle/math_learning.py:16-23, 407-469` | partial | `MathLeaf`, `MathFunction`, and `MathRule` have no separate truth axis, no V0–V3 validity level, and no utility axis. `MathFunction.proof_status` mixes proof/truth-like values (`proven`, `verified`, `tested`). Only `MathLearningService` proposal/rule records implement the five axes. |
| §4.1 / §4.3 aliases and identity | `runner_riddle/math_linker.py:625-714, 810-825` | partial | `HW0:*` aliases exist only as an in-memory `aliases` mapping supplied by the caller. There is no persistent alias record, version, ACL, or schema. `via_alias` is transient and not part of stored identity. |
| §4.2 router must reject `math://` with `route_context_mismatch` | `runner_riddle/address.py:36-52`; `runner_riddle/cache.py:197-202` | missing | `parse_address()` matches only `nan://`. A `math://` string raises generic `AddressError("invalid NaN address root…")`. No code or test anywhere emits or asserts `route_context_mismatch`. |
| §4.4 address regions; §4.4a typed MOA / non-palindromic pair binding | Only `docs/GAME_PLAN_::.md:322-349`; `spec/math-leaf.schema.json:10` | missing / doc-only | No M0–M6 allocator, MOA bit encoding, pair-index binding, palindrome rejection, or region reservation exists in `spec/` or code. Leaf IDs are only `nml:`. The plan itself says the exact encoding must be frozen before implementation. |
| §4.5 / §5.1 content digest integrity | `runner_riddle/math_objects.py:140-145`; `runner_riddle/math_store.py:781-787, 1003-1075` | partial | `MathLeaf.content_digest` trusts `content["digest"]`. `MathStore.put_leaf()` computes the actual payload digest but never requires it to equal the declared `content["digest"]`. `get_leaf()` verifies the payload hash and that decoded content equals `leaf.content`, but not that `leaf.content["digest"]` equals the stored `content_digest`. |
| §5.1 minimum leaf fields | `runner_riddle/math_objects.py:97-145, 147-162`; `spec/math-leaf.schema.json:7-28` | partial | No `metadata_version`. The schema does not require `parents`, `operation`, or `provenance`. `type` subfields (`name`, `domain`, `shape`, `precision`, `encoding`) are not validated. Parent roles and operation `function_id`/`ruleset_id`/`ruleset_version` are not validated. |
| §5.2 leaf kinds and per-kind contracts | `runner_riddle/math_objects.py:22-26, 132-138`; `spec/math-leaf.schema.json:12` | partial | `function`, `rule`, `relation`, and `hypergraph` leaves have no required contract body. Only `result` leaves require an operation. `cancelled` exists in `LEAF_KINDS` but is absent from the schema enum. |
| §5.3 committed contents immutable | `runner_riddle/math_objects.py:97-131, 188-221, 248-274` | partial | Frozen dataclasses hold mutable `dict`/tuple-of-dicts fields. `leaf.type[...] = ...`, `function.signature[...] = ...`, or `rule.contract[...] = ...` mutate in place and change the computed digest. Store immutability only catches this on later reload. |
| §5.4 result provenance | `runner_riddle/math_objects.py:137-138`; `runner_riddle/math_store.py:813-892`; `tools/run_math_demo.py:130-143`; `runner_riddle/math_execution.py:2090-2098` | partial | Result leaves only require an `operation`; empty provenance is accepted and committed. No enforcement of input leaf IDs/versions/digests, function/rule snapshots, linker/candidate ID, runner/lease, native source/fixture digest, numerical policy, output digest, or signature. Demo/bridge provenance covers only a subset. |
| §5.5 null leaf must carry failure class, reason, parents, linker ID, rule snapshot, candidate count | `runner_riddle/math_linker.py:2532-2564`; `runner_riddle/math_absence.py` | partial | Linker `_typed_null()` metadata has `reason`, `snapshot_id`, mode/objective, inputs, `rejected_count`, and producer `math.linker.v1`, but no `failure_class`, explicit `linker_id`, `rule_snapshot_id`, or `candidate_count`. `math_absence` is not imported by the linker or validity engine. |
| §6.1 function family / contract fields | `runner_riddle/math_objects.py:188-245`; `runner_riddle/math_registry.py:62-67, 558-568`; `spec/math-function.schema.json:12-13` | partial | `family` is validated from the catalog then dropped by `MathFunction`. The schema allows `title`, but `_FUNCTION_KEYS` rejects it. The contract digest excludes both. There is no ruleset ID/version field on the function contract. |
| §6.2 `NmpPlan` and `to_v2_dict()` wrapper | No implementation; requirement at `docs/GAME_PLAN_::.md:543,553` | missing | No `NmpPlan`, no `MthPlan.to_v2_dict()`, no wrapper carrying plan digest, typed pins, admission, ruleset, or peak workspace. `MthPlan` remains the only plan. |
| §6.4 composition creates a new function leaf | `runner_riddle/math_registry.py:989-1105` | partial | `compose()` returns a `MathFunction`; it never creates or persists a function `MathLeaf`. There is no fused-implementation path that preserves original composition provenance. |
| §6.5 rule registry fields | `runner_riddle/math_objects.py:248-288`; `runner_riddle/math_learning.py:407-469, 520-694`; no `spec/math-rule.schema.json` | partial | `MathRule` has only `contract`, proof/status, scope, and `certificate_digest`; no explicit pre/postconditions, invariants, undefined conditions, numerical policy, or test references. `MathLearningService` supplies lifecycle but no rule catalog/schema/registry. |
| §6.6 deterministic compatibility index | `runner_riddle/math_registry.py:1107-1134` | partial | The key is a hash of the full signature, and entries are one row per function. It is not `(type_a,type_b,domain_a,domain_b,shape_class) -> ordered candidate function IDs`. It is recomputed on demand, has no versioned cache, and no rule-version invalidation. |
| §6.7 relation shared domains / rule snapshot / hypergraph leaf | `runner_riddle/math_relation.py:615-718, 1089-1157, 1564` | partial | `RelationSchema` has no shared-domain or cross-domain permission field, and `RelationRecord` has no rule-snapshot field. `Hypergraph` is a separate class, not a `MathLeaf` kind `hypergraph` contract. |
| §6.8 `XFSC365` opaque function reference | Only `docs/GAME_PLAN_::.md:645-658` | missing | No XFSC/function-reference resolver, MC0DB binding, contract lookup, or test. `parse_ref()` rejects `math.` function IDs as leaf operands but provides no function-reference path. |
| §7.2–7.5 candidate contract digest and dedup key | `runner_riddle/math_objects.py:290-327, 366-385`; `runner_riddle/math_linker.py:1330-1354, 2271-2284`; `runner_riddle/nmp.py:530-573` | partial | `MathCandidate` and `NmpPacket` have no `contract_digest` field. `candidate_id_for()` and NMP `dedupe_key_for()` omit contract digest, explicit rule snapshot, and numerical policy. The linker’s `_function_contract_digest()` returns a caller-supplied `contract_digest` without recomputing or comparing it to the contract. |
| §7.4 “execute a selected candidate … bounded candidate batch” | `runner_riddle/math_linker.py:2166-2170`; `docs/GAME_PLAN_::.md:724-733` | doc-only / ambiguity | §7.4 says the linker should support execution of selected candidates/batches; §3.4 says the linker may not execute. The code follows §3.4 and rejects `execute=True`. No batch execution seam exists. |
| §7.6 current-snapshot contract / unavailable implementation | `runner_riddle/math_linker.py:2220-2229, 2239-2256, 1330-1354` | partial | The linker creates its own snapshot from the supplied registry; it does not validate a candidate against an external/current snapshot. It proposes functions even when supplied capabilities show no usable implementation, because capability data only affects the snapshot digest. |
| §8.2 preflight order / resource window | `runner_riddle/math_validity.py:1736-1853, 2158-2203` | partial / ambiguity | Workspace/resource validation runs before rule and predicate checks, and returns `INVALID` with `WORKSPACE_EXCEEDED`. §8.2 puts the resource window after capability, and §3.1/§8.3 treat capacity as separate from mathematical validity. |
| §8.6 no host mathematical precondition evaluation | `runner_riddle/math_validity.py:905-918, 1091-1094`; `tests/test_math_validity.py:623-628` | partial — unsafe | Any well-formed certificate digest satisfies a numeric predicate when the snapshot pins no certificates (`certificate in context.certificates or not context.certificates`). There is no native certificate kernel call, no certificate content check, and no fail-closed behavior. The test explicitly expects `VALID` for declared-only. |
| §8.5 cache / §8.1 admission identity and durability | `runner_riddle/math_objects.py:378-385`; `runner_riddle/math_validity.py:2874-2876, 3051-3059`; `runner_riddle/math_store.py:1648-1710` | partial | `admission_id_for()` excludes preflight digest, authorization, and capability context, so different contexts can share an admission ID; `_issued_by_id` overwrites earlier entries. `_issued` is process-local; stored `math_admission` rows cannot be rehydrated/re-verified after restart. |
| §3.1 authorization is a separate policy decision | `runner_riddle/math_validity.py:2653-2709`; `runner_riddle/math_runtime.py:173-177` | partial | There is no authenticated principal or WaveService ACL integration. `_authorization_outcome()` defaults to `ALLOWED` when the config is empty. Preflight/bridge calls do not pass a request authorization context. |

## 2. Host-side arithmetic / authority-collapse violations

1. **HIGH — unverified certificate digest is treated as a satisfied numeric precondition.**
   `math_validity.py:1091-1094` and `:910-914`: `if certificate in context.certificates or not context.certificates: SATISFIED`. With no pinned certificates, any syntactically valid digest passes `lt/lte/gt/gte/norm_le/residual_le/...`. This contradicts §8.6 and §15. The test at `tests/test_math_validity.py:623-628` locks in the unsafe behavior.

2. **HIGH — preflight snapshot substitution.**
   `math_runtime.py:134-147` builds `MathSnapshot(snapshot_id=candidate.snapshot_id, functions=(function,), leaf_pins=..., capabilities=())` with **no rules**. `MathRuntime.preflight()` at `:173-177` uses this default snapshot. The linker’s rule snapshot, capability set, and contract context in `LinkResult.snapshot` are discarded. The resulting admission claims the linker’s snapshot ID but was evaluated under an empty rule set.

3. **HIGH — cross-candidate admission reuse.**
   `math_runtime.py:182-186` checks only the verdict. `math_execution.py:799-862` does not compare `compiled.admission.candidate_id` with `compiled.candidate.candidate_id`. A valid admission for candidate A can compile/execute candidate B under the same snapshot.

4. **HIGH — direct `MathRuntime.submit()` path bypasses the NMP/ring gate.**
   `math_runtime.py:272-309` calls `MthSystem.submit_plan()` directly; `mth_system.py:172-240` has no admission, NMP packet, capability, or ring parameter. This contradicts §3.2’s single pipeline and the docs claim that the bridge is the only host path.

5. **HIGH — compiled implementation is not the admission-selected implementation.**
   `math_runtime.py:188-203` always selects `implementations[0]`. `_capability_outcome()` in `math_validity.py` may select a different implementation/capability. A preflight that selected implementation B can execute implementation A.

6. **MEDIUM — no post-lease revalidation (TOCTOU).**
   `math_execution.py:1564-1794` leases without calling `validity.require_admission()`, and `:1978-2123` completes without checking current snapshot/rule/auth context.

7. **MEDIUM — admission identity collision and process-local authority.**
   `math_objects.py:378-385` excludes preflight digest/auth/capability from `admission_id_for()`. `math_validity.py:2874-2876, 3051-3059` keeps `_issued` only in memory. Persisted `math_admission` rows are not re-verifiable after restart.

8. **MEDIUM — content digest is caller-controlled.**
   `math_objects.py:140-145`; `math_store.py:781-787, 1003-1075`. The store hashes the actual payload but never requires `leaf.content["digest"]` to equal that hash.

9. **MEDIUM — records are not deeply immutable.**
   `MathLeaf`, `MathFunction`, and `MathRule` are frozen at the dataclass level but expose mutable dicts.

10. **LOW / ambiguity — default authorization is allow.**
    `math_validity.py:2653-2709` returns `ALLOWED` when no authorization config is present.

11. **Not a math violation:** linker ranking hints and execution workspace arithmetic are control/resource metadata. No `math`/`numpy` numeric operator was found in `math_validity.py`; the unsafe path is certificate acceptance.

## 3. Smallest high-value changes, in dependency order

1. Close the preflight snapshot gap. Add `MathRuntime.preflight_for(LinkResult, candidate)` that reconstructs function/rule/capability pins. Use `candidate.function_version`. Fail closed if the snapshot cannot be reproduced.
2. Bind admission to candidate, snapshot, function ID, and function version. Add cross-candidate rejection tests.
3. Remove or gate `MathRuntime.submit()`. Require NMP/admission binding at `MthSystem.submit_plan()` or migrate callers to `MathExecutionBridge`.
4. Make numeric certificates fail closed. Return `UNKNOWN`/`UNSUPPORTED` unless a pinned certificate and verifier exist.
5. Bind the selected implementation from admission and reject mismatch in `compile()`.
6. Add post-lease revalidation in `check()`, `lease()`, and `complete()`.
7. Enforce identity/immutability: deep-freeze nested JSON, content-digest equality, `metadata_version`, required result provenance, null metadata.
8. Add `spec/math-rule.schema.json`, `NmpPlan`/`MthPlan.to_v2_dict()`, rule snapshot adapter, and a real compatibility index key/invalidation.
9. Add address-context handling: coded `route_context_mismatch` for `math://`. Freeze or defer MOA. Add XFSC resolver or mark deferred.
10. Fix stale docs after code/tests.

## 4. Stale docs / test-count claims

- `README.md:132` says 61-kernel manifest; actual 63.
- `docs/GAME_PLAN_::.md:546,550` says 61-kernel manifest/count; line 110 says 63.
- `docs/DEEP_PLAN_CONT.md:71` says `mth_registry` 26 tests; actual 29.
- `docs/DEEP_PLAN_CONT.md:74`, `docs/IMPLEMENTATION_TODO.md:238`, `docs/MTH_SYSTEM_RUNTIME.md:213` say `mth_system` 11 tests; actual 16.
- `docs/DEEP_PLAN_CONT.md:73` and `docs/IMPLEMENTATION_TODO.md:237` say point-0 35 tests; actual 36.
- `docs/DEEP_PLAN_CONT.md:72` and `docs/IMPLEMENTATION_TODO.md:236` say scheduler 27 tests; actual 28.
- `docs/MATH_EXECUTION_BRIDGE.md:5-7` claims the bridge is the only host path; false while `MathRuntime.submit()` exists.
- `docs/IMPLEMENTATION_TODO.md:40` marks P1 complete; no MOA/bit-layout or cell-pair binding exists.
- 653-test total is accurate. P2/P3/P4/P7/P8/P9/P10/P11/P12 per-module counts are accurate.

---

# Agent B — §§9–12 audit (reconstructed from direct code inspection)

The dedicated agent session was interrupted three times. This section is a direct audit performed in the same session against the files listed. It preserves the same headings and evidence standard.

## 1. Gap table

| Requirement | Evidence | Status | Exact gap |
|---|---|---|---|
| §9.0 NMP is host control; no durable native state | `nmp.py` module docstring; `tests/test_nmp.py::test_module_owns_no_private_durable_state` | implemented | Native receives only payload and seal. No native durable queue. |
| §9.0 batch = one parent + N children; no parent lease | `nmp.py:786-808`; `tests/test_nmp.py::test_parent_has_no_lease_and_children_are_independent`, `::test_seal_requires_all_children_and_never_leases_parent` | implemented | Parent/child and no-parent-lease rules enforced. |
| §9.1 typed packet/state machine | `nmp.py` states/transitions; `tests/test_nmp.py` | implemented | Core transition table covered. |
| §9.2 packet fields | `nmp.py:640-690`; serialization at `:940-1030` | partial | Has snapshot, generation, lane, universe, function/version, candidate, inputs, admission, preflight, ruleset, capability set/digest/epoch, guest words, plan digest, numerical policy, operation/request, cancellation, result, output, job/lease/ring, JAHS, batch, evidence. Missing flattened `registry_digest`/`linker_id`; capability is not a single structured object with selected runner/implementation; output is flat rather than `{leaf_id,digest,kind}`; no `contract_digest`. |
| §9.3 states and invalid transitions fail closed | `nmp.py` `ALL_STATES`/transition map; `tests/test_nmp.py::test_proposed_cannot_jump_to_executing` | implemented | Terminal branches include NULL/UNDEFINED/REJECTED/UNAVAILABLE/UNAUTHORIZED/STALE/FAILED/CANCELLED. `COMMITTED` evidence requirements tested. |
| §9.4 snapshot identity | `nmp.py` packet fields; `math_execution.py` binding; `tests/test_nmp.py::test_stale_admission_snapshot_ruleset_and_preflight_are_rejected` | partial | Packet binds leaf/function/ruleset/capability/numerical policy/ring fields. Learned rule snapshot is not derived from the authority. Ring epoch/incarnation are not durably recoverable. Selected implementation is not embedded in the packet capability. |
| §9.5 dedup/in-flight | `nmp.py` dedupe/in-flight; `tests/test_nmp.py::DedupeTests`; `tests/test_math_execution.py::test_duplicate_submit_reuses_one_durable_job` | partial | Dedupe reuses jobs, but key omits contract digest, explicit rule snapshot, and numerical policy. No test proves one executor invocation and shared subscriber result. |
| §9.6 state storage / append-only evidence | `nmp.py` in-memory packet; `wave_store.py` jobs/leases; `math_store.py` `math_event`; no `math_nmp_packet` table | partial | No durable append-only NMP packet/transition table. Current state lives in WaveStore job/lease rows and in-memory packet history. Bridge projection reconstructs state from jobs. |
| §9.7 cross-store intent/finalize | No implementation; §9.7 text only | missing | BS0DB/MC0DB writes are separate. No commit intent, finalize, recovery, or crash-injection test. |
| §10.1 store ownership | `math_store.py:1-25`; schema tests | implemented | Math tables are additive; wave schema remains 1. |
| §10.2 proposed tables | `math_store.py:131-425`; `spec/math-store.schema.json` | partial | Has `math_leaf`, `math_leaf_version`, `math_function`, `math_function_version`, `math_rule`, `math_rule_version`, `math_relation(_version)`, `math_candidate`, `math_admission`, `math_mapping`, `math_preflight_cache`, `math_payload`, `math_event`, `math_certificate`. Missing explicit `math_nmp_packet`/transition table and a durable general payload cache. |
| §10.3 mapping version/CAS/rollback | `math_store.py` mapping methods; `tests/test_math_store.py::test_rollback_is_a_new_mapping_event_and_is_recoverable` | implemented | CAS on version/generation, rollback as new event, old pointer recoverable. |
| §10.4 cache/recovery | `math_store.py` payload chunking and preflight cache; `tests/test_math_store.py::test_missing_payload_is_a_reference_error_not_null`, `::test_cache_reload_and_invalidation` | partial | Payload reference errors and chunk recovery exist. No eviction/recovery cache layer; no corrupt-cache generation test beyond preflight cache. |
| §11.1 exactly one active runner | `lane_registry.py` constants; `tests/test_lane_registry.py::test_health_is_deterministic_and_never_claims_255_runners` | implemented | 255 logical lanes, one active runner, one guest working set. |
| §11.2 lane identity/pass schedule | `lane_registry.py:39-60`; tests | implemented | 0..254, NANNET0 at 255, 17×15, home page accounting. |
| §11.3 logical head roles | `lane_registry.py` role ranges | implemented | Role vocabulary and control/numerical separation declared. |
| §11.4 work queues/work stealing | No implementation in `lane_registry.py`/scheduler | missing | No bounded per-role queues, stealing rules, stolen-packet snapshot binding, or critical-queue starvation protection. |
| §11.5 capabilities | `wave_store.py` capability rows; `math_validity.py` capability outcome; `nmp.py` capability digest/epoch | partial | Separate valid/available/authorized outcomes exist. Capability digest is caller-supplied; no signed fixture envelope; capability selected implementation not bound into packet/admission. |
| §11.6 determinism | `spec/math-functions.v1.json` numerical policy fields; `math_execution.py` policy dict | partial | Policy is carried, but no enforced canonical result check for deterministic contracts, no nondeterministic tagging/rejection test. |
| §11.7 integration with runtime | `math_execution.py`, `mth_system.py`, `wave_service.py` | partial | `MthPlan` remains plan; no `NmpPlan` wrapper. `MathRuntime.submit()` bypasses `WaveService.submit_job` NMP payload path. Point-0 remains ingress, but no math routes. |
| §12.1 typed absence rules | `math_absence.py`; `tests/test_math_absence.py` 59 tests | implemented | ZERO/NULL/VOID/UNDEFINED/EMPTY/INFINITY/UNKNOWN/ERROR/CANCELLED distinct; no host zero collapse. |
| §12.2 conjunction semantics | `math_absence.py` conjunction table; tests | implemented | Explicit object/void/null/undefined/empty/error/cancelled combinations; missing-reference dominance. |
| §12 linker integration | `math_linker.py` `_typed_null`; no import of `math_absence` | partial | Linker emits typed null metadata but does not use absence algebra or carry complete failure class/linker/rule snapshot/candidate count. |

## 2. Top authority/persistence violations

1. **No durable NMP packet ledger.** Packet history is in memory; only job/lease rows survive restart. A packet can be projected, but its full transition evidence is not append-only persisted.
2. **No cross-store transaction protocol.** §9.7 is unimplemented; a crash between BS0DB evidence and MC0DB mapping can leave an orphan or ambiguous commit.
3. **Durable ring epoch absent.** `WaveRingScheduler._epoch` is in memory. Restart projection trusts store rows, but incarnation/epoch fencing is not restored from durable state.
4. **Capability digest is caller-controlled.** NMP compares the packet digest, but the underlying capability registration accepts a supplied `verified_digest` without a signed fixture/CI envelope.
5. **Learned rule snapshot not bound.** Store and learning have rule versions, but NMP packet's `ruleset_snapshot_id` is caller-supplied and not derived from the active learned-rule set.
6. **Packet/input/evidence size unbounded.** Individual text fields are capped, but total inputs/history/evidence/metadata and serialized packet size are not.
7. **Secrets in evidence.** Lease bearer tokens appear in packet evidence/provenance and lease rows.
8. **Scratch leaves linkable.** Retention/validity know scratch, but linker classification does not filter scratch/quarantined/tombstoned.
9. **No math health.** `MthSystem.health()` reports store/registry/ring/budget, not math store/linker/validity/execution health.
10. **No math HTTP ingress.** `/v1/math/link` and `/v1/math/execute` do not exist; `wave_http.MAX_BODY_BYTES` is 1 MiB.

## 3. Smallest high-value changes, in order

1. Add admission/candidate/snapshot/implementation binding at the runtime and bridge boundary.
2. Add a durable NMP packet/transition table or explicitly make WaveStore job/lease rows the sole ledger and persist transition evidence in `math_event`.
3. Implement §9.7 intent/finalize with crash injection.
4. Persist ring incarnation/epoch or restore it from a durable checkpoint.
5. Bound packet inputs/history/evidence size and redact tokens.
6. Derive `ruleset_snapshot_id` and capability selected implementation from authority, not caller input.
7. Filter scratch/quarantined/tombstoned leaves in linker and runtime pins.
8. Add math health provider to `MthSystem.health()`.
9. Add work-stealing contract and tests, or explicitly defer §11.4.
10. Add math HTTP ingress at 2 MiB via point-0 or raise the relevant body limit.

## 4. Stale claims

- `docs/MATH_EXECUTION_BRIDGE.md` “only host path” claim.
- `docs/POINT0_BRIDGE.md` 1 MiB/131,072 words vs code 2 MiB/262,144.
- `docs/POINT0_HTTP.md` 1 MiB body vs code 2 MiB.
- `docs/MTH_MEMORY_1MIB.md` says runner default is 1 MiB; code default is 2 MiB.
- `docs/IMPLEMENTATION_TODO.md` P0.2/P0.4 checkmarks overclaim tests that do not exist.
- `README.md` 61-kernel manifest vs actual 63.

---

# Agent C — §§13–20 audit

## 1. Ordered matrix coverage

The plan contains **107 explicitly enumerated ordered test IDs** in §20.1–20.5, §20.8, §20.9. Summary: approximately **53 covered, 38 partial, 16 missing**. A01–A20 are never enumerated.

### §20.1 P0

| ID | Status | Test / gap |
|---|---|---|
| P0-01 | C | `tests/test_guest_budget.py::test_standard_profile_is_two_mib`; `test_mth_system.py::test_default_guest_budget_is_2_mib_and_overridable` |
| P0-02 | C | `test_guest_budget.py::test_legacy_profile_is_one_mib`; `test_mth_system.py::test_2_mib_default_admits_full_pair_and_legacy_1_mib_rejects` |
| P0-03 | P | No exact 262,144-word acceptance / +1 rejection at 2 MiB. Closest uses tiny budget or 7 GiB. `submit_plan` uses `>`; boundary itself untested. |
| P0-04 | C | `test_point0_bridge.py::test_boundary_lengths_and_oversized_frames_are_rejected`; `test_point0_http.py::test_oversized_body_and_word_count_are_rejected` |
| P0-05 | C | `test_mth_system.py::test_2_mib_default_admits_full_pair_and_legacy_1_mib_rejects` |
| P0-06 | P | 512 KiB override rejection exists; no old 512 KiB fixture still runnable test. |
| P0-07 | M | No `glt_1mib`/`glt_2mib` evidence test; only asserts `glt_enforced == False`. |
| P0-08 | C | JAHS tests in MthSystem, point-0, NMP. |
| P0-09 | P | No 196,608-word capability / epoch-2 six-slot test. |
| P0-10 | C | Point-0 frame/body bounds. |
| P0-11 | C | Math store additive schema tests. |
| P0-12 | C | Peak-liveness admission test. |
| P0-13 | C | Custom words ceiling/slack test. |

### §20.2 L / F

L-01–L-04 C; F-01–F-04 C. See audit table.

### §20.3 V / K / N

- V-01, V-02, V-03, V-07, V-09, V-12, V-13, V-14: C.
- V-04 matrix×vector: M.
- V-05 incompatible matrix×vector: M.
- V-06 vector+scalar: M.
- V-08 unknown function returns UNSUPPORTED, oracle wants REJECTED: P.
- V-10 invalid preflight bypass: P; no bridge executor-spy.
- V-11 stale epoch/lease: P; no bridge lease-epoch mismatch before executor.
- K-01, K-02, K-04 partial: deterministic candidates and dedupe exist; no single-execution/subscriber-share assertion.
- K-03: linker side covered; router side rejects `math://` generically, not `route_context_mismatch`: P.
- N-01–N-04: C.

### §20.4 S / R

- S-01 mapping CAS: P; stale rollback CAS tested, direct `set_mapping` stale test missing.
- S-02 C.
- S-03 payload cache/eviction: M.
- S-04 C.
- S-05 C.
- R-01 C.
- R-02 eviction/recovery: P.
- R-03 vector::hyperedge / hyperedge::hypergraph linker: P.
- R-04 C.
- R-05 C.

### §20.5 G / O / E / D

- G-01 runtime path for level-3 isolation: P.
- G-02–G-05 C.
- O-01 depth/fan-out/candidate exhaustion: P.
- O-02 C.
- O-03 cache eviction + truth preservation: P.
- O-04 scratch lifecycle/visibility/promotion: M.
- E-01 C.
- E-02 work stealing: M.
- E-03 durable ring incarnation/epoch: P.
- E-04 end-to-end canonical result determinism: P.
- D-01 C.
- D-02 full T01–T20/A01–A20 negative suite: M.
- D-03 path-wide no-host-math audit: P.
- D-04 demo evidence completeness: P.

### §20.8 X

- X-01 auth/capability mutation orthogonality: P.
- X-02 stale proof drops V3: P.
- X-03 statement/theory/checker/dependency change invalidates proof: M.
- X-04 authorization matrix/audit: P.
- X-05 wrong kernel cannot promote truth: P.
- X-06 alpha-equivalence/normalization rejection: M.
- X-07 cross-store intent/finalize crash test: M.
- X-08 scratch network/token/live-mapping/commit isolation: M.
- X-09 refuted truth + counterexample retention: P.
- X-10 C.
- X-11 C.
- X-12 refutation/audit-digest protection: P.
- X-13 C.
- X-14 subsumption dedupe: P.
- X-15 Boolean-head 1,024/1,024, leakage=0, control head, shuffled baseline: M.
- X-16 R7/LM outcomes never set validity/truth integration: P.
- X-17 Class C checker/policy/ACL/control-head guard: P.
- X-18 deprecate→prune→restore replay: P.

### §20.9 B

- B-01 cross-selector duplicate rejection: M.
- B-02 stale rule/capability before executor: P.
- B-03 invalid preflight zero executor calls: P.
- B-04 unavailable capability zero executor calls: P.
- B-05 durable bridge lease + ring cycle: P.
- B-06 incarnation fencing/expiry reclaim: P.
- B-07 all six slots registered: M.
- B-08 C.
- B-09 C.
- B-10 bridge batch execution: P.
- B-11 C.
- B-12 C.
- B-13 point-0 2 MiB code/constants/docs agree: P; docs stale.
- B-14 candidate-batch promotion ineligibility: M.
- B-15 all 512 page digests: C.
- B-16 C.
- B-17 physical worker slots/memory pinning/12-worker case: P.
- B-18 real 256-tile native test: P.
- B-19 canonical head unchanged assertion: P.

## 2. Normative gaps §§13–17

| Requirement | Status | Gap |
|---|---|---|
| §13.1 five learning mechanisms | M | Lifecycle governance exists; structural/transformational/derivational/relational/operational discovery does not. |
| §13.2 lifecycle/transactional activation/in-flight isolation | P | No `PROVEN/VERIFIED`; no integration between learned active rules and runtime/bridge snapshot. |
| §13.3 proof vocabulary | P | `MathLeaf` proof statuses match plan; learning uses `none/sketch/candidate/checked/refuted/stale` and maps checked→verified; no empirical/experimental state. |
| §13.4 Boolean heads limits | P | Only utility records; no head implementation/role gate/leakage test. |
| §13.5 not by association/popularity/performance | P | No test proving all paths separate rank/popularity from validity. |
| §13.6 LM/R7 integration | P/M | Harnesses exist; no math evidence consumption; P13 blocked. |
| §13.7 self-modification classes A/B/C | P/M | A/B partial; Class C signed policy transition/ACL root/control-head guard absent. |
| §13.8 experiments not validity; native + cost/latency gate | P | Utility-only enforced; native verification and cost/latency enablement gate missing. |
| §14.1 scratch non-authoritative/bounded/invisible/non-promotable | P/M | Scratch tier exists; linker ignores status; no budget/lifecycle/compaction/promotion gate. |
| §14.2 full oscillation cycle | M/P | Only state/budget/detector; no OBSERVE→…→EVALUATE integration. |
| §14.3 learned retention weights | P | Static defaults. |
| §14.4 tiers/no truth deletion | P | Tier ledger exists; no actual cache eviction/payload deletion; protection is metadata-based. |
| §15 authenticated principal/ACL | M/P | Learning actors free-form; store mutators unauthenticated. |
| §15 lease/epoch/generation + JAHS | P | Bridge enforces; direct `MthSystem`/`WaveService` submit path exists. |
| §15 digest/snapshot-bound preflight | P | Capability digest caller-supplied; no signed fixture envelope. |
| §15 secrets never in leaves/NMP/logs/evidence | M | Lease tokens leak into evidence/provenance/rows. |
| §15 bounded recursion/fan-out/candidate/fuel/workspace/packet/network | P | NMP total packet/inputs/evidence size unbounded. |
| §15 denied operation audit-recorded | P | Learning denies recorded; validity/execution denies not durably recorded. |
| §15 remote workers receive only selected step | M | No remote-worker protocol. |
| §15 promotion stronger auth than proposal | P | Separation by actor string only. |
| §15 no hidden host math/native certificate | P | Module audits exist; runtime certificate enforcement absent. |
| §16.0 guest words vs bytes | P | Docs stale 1 MiB. |
| §16.1 budget model/adjustable | P | live_preflight accepts only exactly 1/2 MiB. |
| §16.2 changes at 2 MiB | P | Some defaults updated; pair-budget aggregate only; old docs stale. |
| §16.3 required tests | P/M | Exact ±1, 4 MiB platform, 512 KiB fixtures, source, migration, explicit GLT missing. |
| §16.4 code points | P | `register_wave_capabilities.py:142` MiB conversion bug; comment stale. |
| §17.1 canonical fixture L0:123/L0:234 | P | Demo uses `nml:U0:vector:demo-1/2`. |
| §17.2 sequence 1–10 | P/M | Output leaf lacks parents/function/rule/JAHS/evidence; no hypergraph feedback; no combined negative suite; no path-wide audit. |
| §17.3 acceptance | P | Control-plane commit works; full provenance/reusable transformation/typed negatives incomplete. |
| P13 | blocked | Real LM/R7/capacity/live Koyeb/NANNET0/production MC0DB missing. |

## 3. Security/capability gaps

1. No authenticated principals or ACL in math control plane.
2. No separate `rule.activate`/`rule.prune` capability or Class C policy transition.
3. Capability digest caller-supplied; no signed fixture/CI envelope.
4. `MathExecutionBridge.execute()` invokes the executor before token/lease/cancel validation.
5. Lease tokens leak into evidence/provenance/rows.
6. Direct `MthSystem.submit_plan`/`WaveService.submit_job` can enqueue math work without NMP/preflight/JAHS.
7. Math health absent from `MthSystem.health()`.
8. No `/v1/math/link` or `/v1/math/execute`; `wave_http` body limit 1 MiB.
9. NMP packet/input/evidence size unbounded.
10. Ring epoch not durable.
11. Scratch leaves linkable.
12. No cross-store intent/finalize.
13. Learned rules not on execution path.
14. No 2 MiB adjustment beyond 1/2 MiB in live preflight.
15. `tools/register_wave_capabilities.py:142` multiplies MiB by 262,144, so `1` means 2 MiB.

## 4. P13: blocked vs local

**Genuinely blocked:** live Koyeb/NANNET0, signed volume registry, production MC0DB, real frozen-model/data ablation, real R7 held-out, capacity-vs-SNR, GLT-enforced loading.

**Blocked by toolchain but implementable later:** native numeric executor / real 256-tile run; native admission receipt production.

**Implementable locally now:** all P0–P12 test gaps, exact 2 MiB/GLT evidence record, 4 MiB declaration, 196,608-word capability test, six-slot registration, math health/HTTP, pre-dispatch validation/token redaction, learning snapshot binding, scratch filtering, cross-store crash injection, full negative suite, B-17 worker declarations, candidate-batch gate, synthetic Boolean-head control gate, machine-readable P13 blocked record.

## 5. Smallest high-value changes, in order

1. Fix budget tool/docs; add 1/2/4 MiB tests.
2. Add P0 boundary tests, GLT evidence gate, 196,608-word capability test, six-slot test.
3. Wire math health into `MthSystem.health()`.
4. Harden execution pre-dispatch and redact tokens.
5. Bind learned rules to runtime.
6. Integrate scratch/retention into linkage/validity.
7. Add math HTTP ingress and 2 MiB body handling.
8. Add cross-store intent/finalize + fault injection.
9. Add full negative suite T01–T20/A01–A20.
10. Wire real pair executor integration behind skip-capable native tests.

## 6. Stale docs

- `GAME_PLAN_::.md:110-111` says 63 kernels then 58 local/59 total fixtures; actual 60 local/61 total.
- `GAME_PLAN_::.md:1686` calls 653 the pre-math baseline; 653 includes math tests.
- `POINT0_BRIDGE.md` 1 MiB/131,072 words; code 2 MiB/262,144.
- `POINT0_HTTP.md` 1 MiB body; code 2 MiB.
- `MTH_MEMORY_1MIB.md` says runner default 1 MiB; code default 2 MiB.
- `README.md:132` 61-kernel manifest; actual 63.
- `IMPLEMENTATION_TODO.md:182` 58 kernels; actual 63.
- `GRAPH_SPECTRAL_MTH_PLAN.md:227` 52 kernels; actual 63.
- `R10_IMPLEMENTATION_EVIDENCE.md:131` 62-kernel dry run; actual 63.
- Per-module counts: `mth_registry` 29 (docs 26), `mth_system` 16 (docs 11), point-0 36 (docs 35), scheduler 28 (docs 27), capabilities 5 (docs 4).

---

# Unified brainstorm — how to execute everything in parallel

## 1. What this audit actually says

The plan’s control-plane primitives are real, but **the authority spine is not yet closed**. The next implementation cycle must not start with more feature breadth. It must start with six invariants:

1. One admission = one candidate + one snapshot + one function version + one implementation.
2. One execution path = NMP → admission → ring/JAHS/capability → lease → executor → commit.
3. No executor call before pre-dispatch validation.
4. No learned rule or capability snapshot may be silently substituted.
5. No secret enters durable evidence.
6. No scratch/proposal object enters normal linkage or promotion.

Once those are true, the remaining work is mostly bounded integration and test closure.

## 2. Workstreams and file ownership

Run 3–4 agents at a time. The integrator owns the shared branch.

| Track | Owns | First deliverable | Depends on |
|---|---|---|---|
| **A. Authority spine** | `math_runtime.py`, `math_execution.py`, `math_validity.py`, `nmp.py` | candidate/snapshot/implementation binding; remove direct submit; fail-closed certificates | none |
| **B. Identity/storage** | `math_objects.py`, `math_store.py`, `spec/math-leaf.schema.json`, `spec/math-rule.schema.json` | deep immutability, content-digest equality, metadata_version, cross-store intent | schema decisions |
| **C. Learning/security** | `math_learning.py`, rule snapshot adapter | active learned rules bound to execution; ACL/capability gates; Boolean-head gate | A snapshot interface |
| **D. 2 MiB/config** | `budget.py`, `register_wave_capabilities.py`, `live_preflight.py`, `point0_bridge.py`, `point0_http.py`, `wave_http.py`, `mth_system.health()` | MiB conversion fix; exact boundaries; all-six-slot test; health | none |
| **E. Verification** | new negative suite + test additions | red tests for A/B/D and T01–T20/A01–A20 inventory | can start immediately |
| **F. Native/P13** | native guest adapter, blocked-evidence records | synthetic receipt producer; skip-capable 256-tile test; blocked manifest | external toolchain for green path |
| **G. Docs** | docs/README/TODO/R10 | final synchronized evidence | A–F |

### Conflict rules

- A owns the execution files exclusively.
- B owns object/store files exclusively.
- C waits for A’s snapshot interface, then owns learning files.
- D owns budget/HTTP/health files.
- E writes tests only; it can add red tests before code lands.
- F never fabricates numeric results.
- G commits last.

## 3. Parallel batches

### Batch 0 — decisions and red tests

- Enumerate A01–A20 as concrete tests.
- Freeze: linker never executes; certificates fail closed; scratch invisible; NMP parent never leased; secrets redacted.
- Freeze MOA: recommend deferring §4.4 encoding, mark partial.
- Write failing tests for admission binding, token leakage, exact 2 MiB boundaries, and executor-spy denials.

### Batch 1 — parallel

- **A:** bind admission to candidate/snapshot/function version/implementation; remove/gate direct submit; fail-closed certificates.
- **B:** deep-freeze objects; require content digest equality; add `metadata_version`; validate leaf-kind bodies.
- **D:** fix `--guest-workspace-mib`; add exact boundary tests; all-six-slot registration; health provider.
- **E:** add V-04–V-06, T10, K-03 router side, cross-selector duplicate, executor-spy tests.

### Batch 2 — parallel

- **A:** pre-dispatch token/lease/cancel/expiry checks; post-lease revalidation; token redaction.
- **B:** scratch filtering, cross-store intent/finalize, cache eviction/recovery, direct mapping CAS test.
- **C:** rule snapshot adapter; active learned rules in runtime; rule schema; snapshot invalidation.
- **D:** math health; `/v1/math/link` and `/v1/math/execute`; 2 MiB HTTP decision; docs alignment.

### Batch 3 — parallel

- **C:** five learning mechanisms; Boolean-head gate; ACL/capabilities; Class C guards; refutation/counterexample retention.
- **E:** full T01–T20/A01–A20 negative suite; B-17 worker declarations; B-18/B-19 native scaffolding.
- **F:** synthetic native receipt producer; native executor adapter behind capability; skip if NaN0S absent; P13 blocked evidence.

### Batch 4 — integration

- Merge order: B → D → A → C → E → F.
- Run full suite, demo, and native contract workflow if available.
- Update docs and evidence.
- Push only green.

## 4. First ten concrete changes

1. **Bind admission identity.** Require candidate/snapshot/function-version equality in `math_runtime.py`; compare `compiled.admission.candidate_id` in `math_execution.py`.
2. **Rebuild the real preflight snapshot.** Add `preflight_for(LinkResult, candidate)` that preserves rules/capabilities/function version.
3. **Remove the second submit path.** Deprecate `MathRuntime.submit()` or require an NMP/admission wrapper; migrate `test_math_end_to_end.py` to the bridge.
4. **Bind selected implementation.** Persist admission-selected kernel; compile must use it or fail.
5. **Fail closed on certificates.** Remove `or not context.certificates`; add `UNKNOWN`/`UNSUPPORTED` path.
6. **Pre-dispatch validation.** Validate token, lease, expiry, cancellation, packet state, ring/JAHS, generation before executor; add executor-spy tests.
7. **Redact tokens.** Replace raw lease tokens in dicts/evidence/provenance/rows with digests.
8. **Deep-freeze objects.** Freeze nested JSON; require content digest equality; add provenance/null metadata validation.
9. **Isolate scratch.** Filter scratch/quarantined/tombstoned in linker and runtime pins.
10. **Fix 2 MiB.** Correct MiB conversion; add exact 262,144/+1 tests; all six slots; GLT blocked/pass evidence record.

## 5. Decisions to freeze

| Decision | Recommendation |
|---|---|
| MOA/65,536-cell layout | Defer; mark §4.4 partial. Do not invent an encoding. |
| A01–A20 | Author explicit tests before claiming coverage. |
| Linker execution | Proposal only; bridge executes selected children. |
| Certificates | Fail closed; V2 production cap. |
| Scratch | Invisible and non-promotable unless opt-in. |
| Batch NMP | One parent, independent children, no parent lease. |
| Secrets | Tokens are bearer secrets; only digests enter evidence. |
| P13 | Explicit blocked evidence, no fabrication. |
| GLT | Separate gate; text-loader is not enforcement. |
| Native numeric result | External executor or NaN0S only. |

## 6. Definition of done

A phase is green only when:

- Every enumerated test ID has a concrete test or explicit blocked record.
- No path bypasses NMP + admission + ring + JAHS.
- Admission/packet/lease/job/candidate/snapshot/implementation are digest-bound.
- Executor is never called on a denied packet.
- Secrets never enter evidence.
- Scratch cannot be linked or promoted.
- Rule changes invalidate in-flight execution.
- Exact 2 MiB boundaries and all six slots are tested.
- Full suite and demo pass; docs match code.
- P13 remains blocked unless real evidence exists.

## 7. Immediate start

Start with **Track A** because every other track depends on its interfaces. In parallel:

- **Track D** can fix the 2 MiB conversion and boundaries without touching Track A files.
- **Track E** can add red tests for admission binding, token leakage, executor denial, and missing V/T cases.
- **Track B** can begin deep-freeze/content-digest work independently.

Track C waits until Track A freezes the snapshot/admission interface.

---

# Post-audit implementation log — 2026-11-07

The first parallel implementation batch landed after this brainstorm:

| Commit | Scope | Evidence |
|---|---|---|
| `513834a` | Admission/candidate/snapshot/function-version/implementation binding; certificate fail-closed behavior; direct `MathRuntime.submit()` disabled; pre-dispatch lease/deadline/cancel checks; bearer-token redaction; matrix-vector and zero-vector tests | `tests/test_math_execution.py` 11 tests; `tests/test_math_validity.py` 25 tests; `tests/test_math_end_to_end.py` 2 tests |
| `ab42f95` | Deep-frozen `MathLeaf`/`MathFunction`/`MathRule`; nested mutation rejection; `metadata_version`; result-leaf provenance checks; opt-in strict content-digest enforcement in `MathStore` | `tests/test_math_objects.py` + `tests/test_math_store.py` 35 tests |
| `7328075` | 1 MiB/2 MiB/4 MiB adjustable live budgets; corrected `--guest-workspace-mib` conversion; exact 262,144/+1 boundary; optional math health in `MthSystem.health()` | `tests/test_wave_capabilities.py`, `test_guest_budget.py`, `test_live_preflight.py`, `test_mth_system.py` |
| `539f6f5` | Runtime `rule_provider` binds active learned rules into preflight snapshots; scratch leaves invisible unless `allow_scratch=True`; quarantined/tombstoned/superseded leaves never linkable | `tests/test_math_end_to_end.py` 5 tests; `tests/test_math_linker.py` 27 tests |
| pending | Machine-readable P13 blocked-gate ledger (`spec/p13-gates.json`) with eight explicit gates and no fabricated result fields | `tests/test_p13_gates.py` 2 tests; `docs/P13_GATES.md` |
| pending | Cross-store intent/evidence/finalize recovery; math health; NmpPlan wrapper; lane work stealing; typed authorization; math HTTP ingress; A06/A09-A12 negative suite | 12 + 9 + 5 + 8 + 9 + 21 + 8 tests; docs `MATH_STORE_CROSS.md`, `LANE_WORK_QUEUES.md`, `MATH_AUTHORIZATION.md`, `MATH_HTTP.md` |

**Current full-suite result:** 749 tests, 1 skipped, OK.

Still open from the audits:

- learned-rule snapshot binding into runtime/execution;
- five learning mechanisms and Boolean-head gate;
- authenticated principal/ACL and separate rule capabilities;
- scratch filtering in linker/runtime;
- cross-store intent/finalize and crash injection;
- work stealing, durable ring epoch, durable NMP packet/transition ledger;
- math HTTP routes and 2 MiB `wave_http` alignment;
- XFSC/MOA decision;
- full T01–T20/A01–A20 negative suite and A01–A20 enumeration;
- native receipt production/operator dispatch and all P13 live/experiment gates.
