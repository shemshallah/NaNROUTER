# Verification matrix — T01–T20 and A01–A20

Status reflects the current code/tests, not the plan's aspirational wording.
`DONE` = direct test; `PARTIAL` = covered but not the full oracle; `OPEN` =
missing; `BLOCKED` = external evidence only.

## T01–T20

| ID | Oracle | Evidence | Status |
|---|---|---|---|
| T01 | vector add valid, vector result | `test_math_validity::test_t01_vector_add_is_valid` | PARTIAL (result-kind assertion missing) |
| T02 | unequal dims INVALID → typed NULL, no execution | `test_t02...`, `test_math_linker::test_dimension_mismatch_returns_typed_null` | DONE |
| T03 | dot valid, scalar leaf | `test_t03...`, demo output | PARTIAL (no result-leaf assertion in validity test) |
| T04 | matrix×vector valid, vector result | `test_math_validity::test_matrix_vector_compatible_and_incompatible` | PARTIAL (result-kind assertion missing) |
| T05 | matrix×vector incompatible → typed NULL | same test | PARTIAL (no typed-NULL assertion) |
| T06 | vector+scalar invalid unless registered | `test_math_validity::test_t06_vector_scalar_is_invalid_without_mixed_contract` | DONE |
| T07 | vector::hyperedge typed candidate/null | `test_math_negative_suite::test_t07...` | PARTIAL (typed relation data, not linker candidate generation) |
| T08 | hyperedge::hypergraph bounded | `test_math_negative_suite::test_t08...` | PARTIAL (validation/traversal, not linker candidate generation) |
| T09 | OBJECT::VOID UNKNOWN/reference error, never zero | `test_math_absence` VOID tests | PARTIAL (no linker path) |
| T10 | zero-vector dot valid scalar zero | `test_math_validity::test_t10...` | PARTIAL (no scalar-zero result assertion) |
| T11 | division by zero UNDEFINED | `test_t11...` | DONE |
| T12 | unknown function REJECTED before execution | `test_t12...`, NMP gate | PARTIAL (preflight returns UNSUPPORTED; gate maps to REJECTED) |
| T13 | old packet retains snapshot; new request STALE | `test_t13...`, bridge rule-change test | DONE |
| T14 | duplicate conjunction one execution/commit | `test_t14...`, NMP dedupe, A12 | PARTIAL (no subscriber-share assertion) |
| T15 | invalid preflight/scratch cannot execute | negative suite A06/A09/A10 | DONE |
| T16 | experimental isolated, no production execution/promotion | validity/learning level-3 tests | PARTIAL (no runtime execution-path test) |
| T17 | same content, distinct identity | object/store tests | DONE |
| T18 | evicted cache recovers canonical, no zero/null | `test_math_cache` | DONE |
| T19 | same contract/snapshot/inputs stable result identity | `test_math_negative_suite::test_t19...`, NmpPlan | DONE |
| T20 | bounded recursion/dedupe/quarantine | retention/linker tests | PARTIAL (no unified recursive-generation test) |

## A01–A20

| ID | Requirement | Evidence | Status |
|---|---|---|---|
| A01 | leaf identity/version metadata integrity | `test_math_negative_suite::test_a01...` | DONE |
| A02 | content digest is not identity | `test_a02...` | DONE |
| A03 | absence never carries zero/numeric content | `test_a03...` | DONE |
| A04 | address context mismatch | `test_a04...`, router test | DONE |
| A05 | zero candidates typed NULL, no side effects | `test_a05...` | DONE |
| A06 | invalid preflight cannot reach executor | `test_a06...` | DONE |
| A07 | stale snapshot cannot execute | `test_a07...` | DONE |
| A08 | contradiction quarantines scope | validity/learning tests | DONE |
| A09 | capability unavailable ≠ NULL | `test_a09...` | DONE |
| A10 | implementation binding mismatch rejected | `test_a10...` | DONE |
| A11 | stale/expired lease rejected before executor | `test_a11...` | DONE |
| A12 | duplicate conjunction one job/executor/commit | `test_a12...` | DONE |
| A13 | level-0 immutable, no self-promotion | learning/validity tests | DONE |
| A14 | failed promotion preserves prior state | `test_a14...` | DONE |
| A15 | oscillation budgets terminate | `test_a15...` | DONE |
| A16 | pruning preserves truth/proof and payload | `test_a16...` | DONE |
| A17 | crash/restart no duplicate commit | restart tests + A12 | PARTIAL (no explicit crash-injection traversal) |
| A18 | cross-store intent/finalize atomicity | `test_math_store_cross` (12) | DONE |
| A19 | canonical result independent of location | `test_t19...` | DONE |
| A20 | 255 lanes/six runners, unauthorized tokens | `test_a20...`, lane/ring tests | DONE |

## Remaining explicit verification work

1. Strengthen T01/T03/T04/T05/T10 result-kind/typed-NULL assertions.
2. Add a T12 vocabulary note or align preflight/gate naming.
3. Add actual linker candidate generation for T07/T08.
4. Add OBJECT::VOID linker test for T09.
5. Add subscriber-result-sharing assertion for T14.
6. Add runtime execution-path test for T16.
7. Add unified recursive-generation test for T20.
8. Add explicit A17 crash-injection/restart test across complete→commit.
