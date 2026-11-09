# MTH cross-repo sync — 2026-11-09

**Evidence class:** source inspection only. Findings come from
`git rev-parse`, `git show origin/main:<path>`, `git ls-tree`, and workflow
YAML. No sibling worktree was fetched, checked out, reset, or modified. No CI
run or live deployment is claimed here.

The NaNROUTER working tree was dirty during this audit; sibling evidence was
read from fetched `origin/main` refs, not from dirty worktrees. The HERMES
worktree in particular contains untracked local MTH experiments and is not a
source of truth for the remote contract.

## 1. Snapshot

| Repository | `origin/main` observed | Relevant state |
|---|---|---|
| NaNROUTER | `12980a3` (then `0fdb60c`, `90cd84b`, `43b7f99`) | 96-kernel MTH catalog, 94 runner fixtures |
| NaNLMind_HERMES | `f49079e` | N16ROOT1/N16SNAP1/N16PACK1, native head bank, L0–L9 |
| nan0s | `fe63617` | native VM, 255-head bank, N16T transport |
| NaNLMind_android | `53cce7e` | N16T client, raw-word ABI parity |
| NaNLMind | `4610a80` | 256 structural heads / 255 MP writers / 250 curriculum roles |
| NaNLM | `181a379` | experiment-only mixer |
| NaNLMind_CLOCKED | `93b3ea9` | HW3 demonstration only |

The NaNROUTER SHA advances during active work; contract checks should record
the exact SHA used for each audit rather than treating `main` as stable.

## 2. What the unified provider audit confirms

The seven provider artifact and substring contracts in
`spec/mth-unified-system.v1.json` currently resolve against worktree files or
fetched `origin/main`:

- `nanrouter.control`
- `nan0s.vm`
- `hermes.runtime`
- `nanlmind.android`
- `nanlmind.core`
- `nanlm.experiment`
- `nanlmind.clocked`

This is a narrow presence/contract-string check. It is **not** a semantic
route, allowlist, or native-execution check.

## 3. Critical semantic mismatch: checked u32 math route

HERMES `origin/main` expects a router math lease:

- `runner_riddle`-side route: `/v1/hermes/leases/math`
- action `"math"`
- function IDs `mth.u32.add_checked` and `mth.u32.sub_checked`
- native result fields `value_u32`, `exact`, `native_nan16_execution`,
  `native_guest_route_admitted`, `native_guest_universe_id`, and
  `native_guest_node_point`

NaNLMind `origin/main` also calls these two function IDs in its cross-repo
smoke test.

NaNROUTER `origin/main` currently:

- has no `"math"` action in the Hermes lease allowlist;
- has no `mth_u32_add_checked` / `mth_u32_sub_checked` native labels;
- admits only programs 900–903 in `mth_execute.nas`, mapped to the four vector
  dispatch kernels;
- has `mth.integer.checked.i32` as a fixture-only checked integer kernel, not
  the expected u32 aliases and not an admitted dynamic dispatch path.

The unmerged NaNROUTER branch
`origin/feat/native-hierarchy-router-hermes-bridge`
(`98dc8e0`) supplies the missing math action, labels, and includes. Until that
contract is merged or the downstream consumers are changed, the three main
branches do not agree on the checked-integer execution path.

**Action:** either merge the branch contract into main with native CI, or
change HERMES/NaNLMind to the canonical `mth.integer.checked.i32` identity and
add a canonical dispatch path. Do not maintain two MTH identities for the same
operation.

## 4. N16PACK / N16SNAP ownership correction

`spec/mth-unified-system.v1.json` currently says `nan0s.vm` owns N16PACK. That
is wrong. N16PACK1 is implemented in HERMES:

- `nanlmind_hermes/universe_pack.py` — `N16PACK1`
- `nanlmind_hermes/chart_storage.py` — `N16SNAP1` dual-slot chart snapshots
- `nanlmind_hermes/native_head_checkpoint.py` — full-page CAS checkpoint
- `nanlmind_hermes/universe_chart.py` — 8 MiB chart geometry

nan0s owns the VM, raw-word transport, and head-bank guest. It has no
N16PACK source.

The HERMES provider artifact list should include `universe_pack.py`,
`chart_storage.py`, `native_head_checkpoint.py`, and `universe_chart.py`.
The Android provider should include the raw-word ABI files and
`nan16-raw-parity.yml`, not only the N16T document.

## 5. Upstream native sources and workflow coverage

There are no new upstream **numerical MTH** kernels in this window beyond the
catalogued graph-claim probe. Upstream added head-bank, chart transport,
snapshot, storage, N16T, and routing sources:

- nan0s: `n16_head_store.nas`, `n16_head_runtime.nas`, `n16_head_worker.nas`
  and their gates.
- HERMES: `universe_root.py`, `head_bank_transport.py`,
  `native_head_fence.py`, `chart_storage.py`, `native_head_checkpoint.py`,
  `universe_pack.py`, plus eight native `nan/*.nas` guests.
- Android: raw-word `nan16.c/h`, JNI/Kotlin transport, `nan16-raw-parity.yml`.
- NaNLMind: `integration/cross_repo_drift.py` and related workflows.

The NaNROUTER static audit globs only `NaNROUTER/mth/nan16/*.nas`. It does not
inventory sibling-repo workflows. Provider artifact checks are the only
cross-repo source coverage; they are not a workflow inventory.

## 6. Pins that need review

Observed source-level risks:

| Workflow | Pin | Finding |
|---|---|---|
| `native-graph-path-witness.yml` | NaN0S `24b3584` | object absent in local fetched clone |
| `hermes-head-e2e.yml` | HERMES `2d6ed9f` | object absent in local fetched clone |
| `hermes-native-nannet.yml` | NaN0S `bb4598f` | exists but is not an ancestor of nan0s `origin/main` |
| `native-head-guest.yml` | NaN0S `3b045ff` | ancestor, older but valid |
| `native-graph-claim-probe.yml` | NaN0S `7f250a1` | ancestor; should move to the current pinned VM |
| Android `nan16-raw-parity.yml` | NaN0S `f31143e` | ancestor; current VM is `fe63617` |

These are workflow-definition observations, not CI results. A pin should be
updated only after the referenced object is fetched and the workflow is
re-run.

## 7. Prioritized unification actions

1. Resolve the checked-u32 math contract (§3) and run native admission plus
   NMP receipt tests.
2. Correct N16PACK/N16SNAP ownership and extend required provider artifacts
   (§4).
3. Record exact provider `origin/main` SHAs and validate semantic allowlists,
   not only substrings.
4. Add Android raw-word parity and NaNLMind head-role contracts to the
   provider audit.
5. Inventory sibling native workflows separately from the NaNROUTER kernel
   audit; do not silently merge them into the numerical manifest.
6. Fix or verify stale pins (§6) before claiming a cross-repo green.
7. Fix the README wording: four excluded native sources, not three; the
   fourth is the multihop path witness.

## 8. Non-claims

- A provider artifact match is not a live deployment.
- A workflow pin is not a CI result.
- A native source file is not an admitted MTH operation.
- A candidate graph witness is not mathematical proof, authorization, a merge,
  or a head-bank update.
